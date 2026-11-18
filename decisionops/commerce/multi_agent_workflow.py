"""Typed, bounded specialist graph. Checkpoints project PostgreSQL commitments.

Resume rebuilds graph progress from immutable domain rows, not saved authority.
Runtime cancellation and ownership live in closures, never checkpoint values.
"""
from contextlib import contextmanager
import hashlib
import time
from typing import TypedDict
from urllib.parse import urlencode, quote
from langgraph.graph import StateGraph, START, END
from . import multi_agent as multi, adaptive_jobs as jobs, adaptive_investigations as service
from .adaptive_workflow import checkpoint_saver, BoundedSaver, METADATA_TIMEOUT_SECONDS
from .cases import clock

class State(TypedDict, total=False):
    run_id: str
    identity: str
    bound: str
    order: str
    shipment: str
    terminal: str


def checkpoint_url(engine):
    with service.transaction(engine, readonly=True) as c: schema = c.exec_driver_sql('SELECT current_schema()').scalar_one()
    namespace = 'commerce_specialist_graph_'+hashlib.sha256(schema.encode()).hexdigest()[:16]
    parsed = engine.url.set(drivername='postgresql').update_query_dict({'options':'-csearch_path='+namespace+' -ctimezone=UTC -cstatement_timeout=5000 -clock_timeout=5000','connect_timeout':'3'})
    return namespace, parsed.set(query={}).render_as_string(hide_password=False)+'?'+urlencode(dict(parsed.query),quote_via=quote)


def setup(engine):
    namespace, url = checkpoint_url(engine)
    with service.transaction(engine) as c:
        c.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS '+c.dialect.identifier_preparer.quote(namespace))
    with checkpoint_saver(url,time.monotonic()+METADATA_TIMEOUT_SECONDS) as saver: saver.setup()
    return namespace


def run(engine, fence, adapters=None, cancel=None, after_node=None,node_delay=0,tracer=None):
    if not 0<=node_delay<=.5:raise ValueError('Node delay bounded to 0..0.5s')
    adapters = adapters or {}
    initial = multi.current(engine, fence)
    with service.transaction(engine, readonly=True) as c:
        job = jobs.get(c, fence.job_id)
        if job['action'] != jobs.SPECIALIST_ACTION: raise ValueError('Wrong graph job partition')
        if initial['state'] == 'active': fence.check(c, initial, False)
    from .observability import observe
    attempt=job['claims']
    observe(engine,initial['id'],tracer=tracer,event='resume' if attempt>1 else 'start',attempt=attempt)
    if multi.stopped(cancel): return initial
    if initial['state']=='active' and job['claims']>1:
        multi.recover(engine,fence)
    setup(engine)
    _, url = checkpoint_url(engine)
    end = time.monotonic()+max(0,(min(initial['deadline'],job['lease_until'])-clock_now()).total_seconds()) if initial['state']=='active' else time.monotonic()+5
    def node(name, action):
        def execute(state):
            if cancel is not None:
                cancel.wait(node_delay)
            elif node_delay:time.sleep(node_delay)
            current = multi.current(engine, fence)
            if current['state']=='active' and not multi.stopped(cancel):
                jobs.renew(engine, fence.job_id, fence.token)
                action()
            current = multi.current(engine, fence)
            observe(engine,initial['id'],tracer=tracer,node=name,attempt=attempt)
            if after_node is not None: after_node(name,current)
            return {name:current['state']}
        return execute
    builder = StateGraph(State)
    builder.add_node('identity', node('identity', lambda:multi.support(engine,fence,tools=('order_manifest',),cancel=cancel)))
    builder.add_node('bound', node('bound', lambda:multi.support(engine,fence,tools=('replacement_policy',),cancel=cancel)))
    builder.add_node('order', node('order', lambda:multi.branch(engine,fence,'order',adapter=adapters.get('order'),cancel=cancel)))
    builder.add_node('shipment', node('shipment', lambda:multi.branch(engine,fence,'shipment',adapter=adapters.get('shipment'),cancel=cancel)))
    builder.add_node('terminal', node('terminal', lambda:multi.join(engine,fence,cancel=cancel)))
    builder.add_edge(START,'identity');builder.add_edge('identity','bound')
    builder.add_edge('bound','order');builder.add_edge('bound','shipment')
    builder.add_edge(['order','shipment'],'terminal');builder.add_edge('terminal',END)
    # An interrupted checkpoint can repeat a node, but every node reconstructs its
    # completed decisions/reads and skips them. No saved token is ever trusted.
    class LiveSaver(BoundedSaver):
        @contextmanager
        def _cursor(self,*,pipeline=False):
            with service.transaction(engine,readonly=True) as c:
                current=service.row(c,initial['id']);owned=jobs.get(c,fence.job_id)
                if current['state']=='active':
                    fence.check(c,current,False)
                    self.end=time.monotonic()+max(0,(min(current['deadline'],owned['lease_until'])-clock(c)).total_seconds())
                else:self.end=time.monotonic()+METADATA_TIMEOUT_SECONDS
            with super()._cursor(pipeline=pipeline) as cursor:yield cursor
    with checkpoint_saver(url,end) as bounded:
        saver=LiveSaver(bounded.conn,end)
        try:
            builder.compile(checkpointer=saver).invoke({'run_id':initial['id']},
                {'configurable':{'thread_id':'commerce-specialists/v1:'+initial['id']},'recursion_limit':16})
        except Exception:
            observe(engine,initial['id'],tracer=tracer,event='failure',reason='worker_error',attempt=attempt)
            raise
    return multi.current(engine,fence)


def clock_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
