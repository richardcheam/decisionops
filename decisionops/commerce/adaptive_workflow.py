"""Adaptive graph is a reconstructable PostgreSQL projection, never authority."""
import hashlib
import os
from typing import TypedDict
from urllib.parse import quote,urlencode
os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START,END,StateGraph
from . import adaptive_jobs as jobs,adaptive_investigations as service,adaptive_accounting as ledger
from .adaptive_runner import tick,run_until_pause

class State(TypedDict,total=False):
    job_id:str
    phase:str
    context_version:int
    committed_steps:list
    reservations:list

def checkpoint_url(engine):
    with engine.connect() as c:business=c.exec_driver_sql('SELECT current_schema()').scalar_one()
    namespace='commerce_adaptive_graph_'+hashlib.sha256(business.encode()).hexdigest()[:16]
    parsed=engine.url.set(drivername='postgresql').update_query_dict({'options':'-csearch_path='+namespace+' -ctimezone=UTC','connect_timeout':'3'})
    return namespace,parsed.set(query={}).render_as_string(hide_password=False)+'?'+urlencode(dict(parsed.query),quote_via=quote)

def setup_checkpoints(engine):
    namespace,url=checkpoint_url(engine)
    with engine.begin() as c:c.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS '+c.dialect.identifier_preparer.quote(namespace))
    with PostgresSaver.from_conn_string(url) as saver:saver.setup()
    return namespace

def authoritative(engine,job_id):
    with service.transaction(engine,readonly=True) as c:job=jobs.get(c,job_id)
    run=service.inspect(engine,job['run_id'])
    with service.transaction(engine,readonly=True) as c:
        from . import schema as db
        import sqlalchemy as sa
        calls=[dict(r) for r in c.execute(sa.select(db.adaptive_calls).where(db.adaptive_calls.c.run_id==run['id'])).mappings()]
    return dict(job_id=job_id,phase=run['state'],context_version=run['context_version'],
                committed_steps=[s['sequence'] for s in run['steps']],
                reservations=[{'id':r['id'],'state':r['state'],'application_status':r['application_status']} for r in calls])

def project(engine,job_id,fence=None):
    _,url=checkpoint_url(engine)
    with service.transaction(engine,readonly=True) as c:job=jobs.get(c,job_id)
    # Job/run identity is always reconstructed. Saved token/choices are never read.
    thread='commerce-adaptive/v1:'+job_id+':'+job['run_id']
    with PostgresSaver.from_conn_string(url) as saver:
        def domain(state):
            if fence is not None:tick(engine,fence)
            return authoritative(engine,job_id)
        builder=StateGraph(State);builder.add_node('project',domain)
        builder.add_edge(START,'project');builder.add_edge('project',END)
        return builder.compile(checkpointer=saver).invoke({'job_id':job_id},{'configurable':{'thread_id':thread}})

def inspect(engine,job_id):
    return authoritative(engine,job_id)

def resume(engine,job_id):
    with service.transaction(engine,readonly=True) as c:job=jobs.get(c,job_id);run=service.row(c,job['run_id'])
    if run['state']!='active':
        jobs.repair_terminal(engine,job_id)
        return project(engine,job_id)
    owned=jobs.claim(engine,job_id=job_id)
    if owned is None:raise ValueError('Job owned, expired run, or exhausted claims; inspect/recover explicitly')
    fence=jobs.Fence(job_id,owned['token'])
    for _ in range(34):
        projected=project(engine,job_id,fence)
        with service.transaction(engine,readonly=True) as c:call=ledger.latest(c,run['id'])
        current=service.inspect(engine,run['id'])
        if current['state']!='active' or current['pending_token'] or call and call['state'] in ('dispatching','uncertain'):return projected
        jobs.renew(engine,job_id,fence.token,30)
    return projected
