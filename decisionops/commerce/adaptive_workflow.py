"""Adaptive graph is a reconstructable PostgreSQL projection, never authority."""
import hashlib
import os
import time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from typing import TypedDict
from urllib.parse import quote,urlencode
os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START,END,StateGraph
from . import adaptive_jobs as jobs,adaptive_investigations as service,adaptive_accounting as ledger
from .adaptive_runner import tick
from .cases import clock

class State(TypedDict,total=False):
    job_id:str
    phase:str
    context_version:int
    committed_steps:list
    reservations:list
    session_phases:list

def checkpoint_url(engine):
    with service.transaction(engine,readonly=True) as c:business=c.exec_driver_sql('SELECT current_schema()').scalar_one()
    namespace='commerce_adaptive_graph_'+hashlib.sha256(business.encode()).hexdigest()[:16]
    parsed=engine.url.set(drivername='postgresql').update_query_dict({'options':'-csearch_path='+namespace+' -ctimezone=UTC -cstatement_timeout=5000 -clock_timeout=5000','connect_timeout':'3'})
    return namespace,parsed.set(query={}).render_as_string(hide_password=False)+'?'+urlencode(dict(parsed.query),quote_via=quote)

METADATA_TIMEOUT_SECONDS=5

class CheckpointFailure(RuntimeError):
    """Projection failed; authoritative domain commits are never rolled back/replayed."""

class BoundedCursor:
    def __init__(self,cursor,end):self.cursor=cursor;self.end=end
    def __getattr__(self,name):return getattr(self.cursor,name)
    def execute(self,query,params=None,**kwargs):
        remaining=self.end-time.monotonic()
        if remaining<=0:raise TimeoutError('Checkpoint deadline reached')
        milliseconds=max(1,min(5000,int(remaining*1000)))
        # Autocommit and synchronous execution: settings take effect before SQL.
        self.cursor.execute(f'SET statement_timeout = {milliseconds}')
        self.cursor.execute(f'SET lock_timeout = {milliseconds}')
        self.cursor.execute(query,params,**kwargs)
        return self
    def executemany(self,query,params_seq,**kwargs):
        for params in params_seq:self.execute(query,params,**kwargs)
        return self

class BoundedSaver(PostgresSaver):
    def __init__(self,connection,end):super().__init__(connection);self.end=end
    @contextmanager
    def _cursor(self, *, pipeline=False):
        # Do not pipeline batches: each SQL wait gets a newly computed bound.
        if not self.lock.acquire(timeout=max(0,self.end-time.monotonic())):
            raise TimeoutError('Checkpoint cursor deadline reached')
        try:
            with self.conn.cursor(binary=True,row_factory=dict_row) as cur:
                yield BoundedCursor(cur,self.end)
        finally:self.lock.release()

@contextmanager
def checkpoint_saver(url,end):
    try:
        with psycopg.connect(url,autocommit=True,prepare_threshold=0,row_factory=dict_row) as conn:
            yield BoundedSaver(conn,end)
    except (psycopg.Error,TimeoutError) as error:
        raise CheckpointFailure('Checkpoint '+type(error).__name__+
            '; domain records remain authoritative. Inspect and resume/recover explicitly; no automatic replay.') from error

def setup_checkpoints(engine):
    end=time.monotonic()+METADATA_TIMEOUT_SECONDS
    namespace,url=checkpoint_url(engine)
    with service.transaction(engine) as raw:
        from datetime import timedelta
        c=service.DeadlineConnection(raw,clock(raw)+timedelta(seconds=max(0,end-time.monotonic())))
        c.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS '+c.dialect.identifier_preparer.quote(namespace))
    with checkpoint_saver(url,end) as saver:saver.setup()
    return namespace

def authoritative(engine,job_id):
    with service.transaction(engine,readonly=True) as c:job=jobs.get(c,job_id)
    run=service.inspect(engine,job['run_id'])
    with service.transaction(engine,readonly=True) as c:
        from . import schema as db
        import sqlalchemy as sa
        calls=[dict(r) for r in c.execute(sa.select(db.adaptive_calls).where(db.adaptive_calls.c.run_id==run['id'])).mappings()]
    phases={}
    if run['contracts'].get('session'):
        from .adaptive_sessions import records
        with service.transaction(engine,readonly=True) as c:
            phases={'session_phases':[{k:r[k] for k in ('id','ordinal','state','retired','reserved_ms','actual_charge_ms','waiting_ms','load_ms','inference_ms','total_ms','diagnostics')} for r in records(c,run['id'])]}
    return dict(**phases,job_id=job_id,phase=run['state'],context_version=run['context_version'],
                committed_steps=[s['sequence'] for s in run['steps']],
                reservations=[{'id':r['id'],'state':r['state'],'application_status':r['application_status']} for r in calls])

def project(engine,job_id,fence=None,cancel=None,*,advance=True,adapter=None):
    end=time.monotonic()+METADATA_TIMEOUT_SECONDS
    with service.transaction(engine,readonly=True) as c:
        job=jobs.get(c,job_id)
        if fence is not None:
            run=service.row(c,job['run_id'])
            if run['state']=='active':
                owned=fence.check(c,run,False)
                end=time.monotonic()+max(0,(min(run['deadline'],owned['lease_until'])-clock(c)).total_seconds())
            else:fence=None  # Terminal projection has no advancement authority.
    _,url=checkpoint_url(engine)
    # Job/run identity is always reconstructed. Saved token/choices are never read.
    thread='commerce-adaptive/v1:'+job_id+':'+job['run_id']
    with checkpoint_saver(url,end) as saver:
        def domain(state):
            if fence is not None and advance:tick(engine,fence,cancel=cancel,adapter=adapter)
            return authoritative(engine,job_id)
        builder=StateGraph(State);builder.add_node('project',domain)
        builder.add_edge(START,'project');builder.add_edge('project',END)
        return builder.compile(checkpointer=saver).invoke({'job_id':job_id},{'configurable':{'thread_id':thread}})

def inspect(engine,job_id):
    return authoritative(engine,job_id)

def resume(engine,job_id,cancel=None):
    with service.transaction(engine,readonly=True) as c:job=jobs.get(c,job_id);run=service.row(c,job['run_id'])
    if cancel is not None and cancel.is_set():return {'event':'worker_stopped',**authoritative(engine,job_id)}
    if run['state']!='active':
        jobs.repair_terminal(engine,job_id)
        return project(engine,job_id)
    owned=jobs.claim(engine,job_id=job_id)
    if owned is None:raise ValueError('Job owned, expired run, or exhausted claims; inspect/recover explicitly')
    fence=jobs.Fence(job_id,owned['token'])
    from .adaptive_sessions import scope
    with scope(engine,fence,cancel) as adapter:
        for _ in range(34):
            if cancel is not None and cancel.is_set():return {'event':'worker_stopped',**authoritative(engine,job_id)}
            if adapter is not None:
                # Session waiting/loading/inference precedes the saver lifetime.
                # Projection then captures current renewed lease; effects never replay.
                outcome=tick(engine,fence,cancel=cancel,adapter=adapter)
                if outcome['event'] not in ('step','stale_recommendation','review_budget'):
                    return {**authoritative(engine,job_id),**outcome}
                projected=project(engine,job_id,fence,cancel=cancel,advance=False)
            else:projected=project(engine,job_id,fence,cancel=cancel)
            if cancel is not None and cancel.is_set():return {'event':'worker_stopped',**projected}
            with service.transaction(engine,readonly=True) as c:call=ledger.latest(c,run['id'])
            current=service.inspect(engine,run['id'])
            if current['state']!='active' or current['pending_token'] or call and call['state'] in ('dispatching','uncertain'):return projected
            jobs.renew(engine,job_id,fence.token,30)
        return projected
