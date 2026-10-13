"""Rules-only LangGraph projection; PostgreSQL cases/operations remain authoritative."""
import hashlib
import os
from typing import TypedDict
from urllib.parse import quote, urlencode

# Optional hosted tracing is explicitly disabled in this no-cost local workflow.
os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, END, StateGraph
from langgraph.types import Command, interrupt

from . import jobs
from .cases import show_case


class WorkflowState(TypedDict, total=False):
    job_id: str
    token: str
    outcome: dict
    phase: str


def graph_schema(business_schema):
    return 'commerce_graph' if business_schema=='public' else 'commerce_graph_'+hashlib.sha256(business_schema.encode()).hexdigest()[:16]


def checkpoint_url(engine):
    with engine.connect() as connection:
        business=connection.exec_driver_sql('SELECT current_schema()').scalar_one()
    namespace=graph_schema(business)
    parsed=engine.url.set(drivername='postgresql').update_query_dict({
        'options':'-csearch_path='+namespace+' -ctimezone=UTC', 'connect_timeout':'3'})
    # libpq URI parsing preserves '+' literally; encode query spaces as %20.
    base=parsed.set(query={}).render_as_string(hide_password=False)
    return namespace,base+'?'+urlencode(dict(parsed.query),quote_via=quote)


def setup_checkpoints(engine):
    namespace,url=checkpoint_url(engine)
    with engine.begin() as connection:
        quoted=connection.dialect.identifier_preparer.quote(namespace)
        connection.exec_driver_sql('CREATE SCHEMA IF NOT EXISTS '+quoted)
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
    return namespace


def build_graph(engine,saver):
    def domain(state):
        with engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
            connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
            outcome=jobs.complete(connection,state['job_id'],state['token'])
        return {'outcome':outcome,'phase':outcome['status']}

    def review_gate(state):
        saved=state['outcome']
        with engine.connect() as connection:
            current=show_case(connection,saved['id'])
        if current['generation']!=saved['generation'] or current['proposal_id']!=saved['proposal_id']:
            return {'phase':'superseded'}
        if current['status']=='awaiting_review':
            # No database transaction or lease remains open during this pause.
            interrupt({'case_id':current['id'],'generation':current['generation'],
                       'proposal_id':current['proposal_id'], 'content_hash':current['proposal']['content_hash']})
            with engine.connect() as connection:
                current=show_case(connection,saved['id'])
            if current['status']=='awaiting_review':
                raise ValueError('Review has not been durably recorded; graph input cannot approve')
        return {'phase':current['status']}

    builder=StateGraph(WorkflowState)
    builder.add_node('domain',domain)
    builder.add_node('review_gate',review_gate)
    builder.add_edge(START,'domain')
    builder.add_conditional_edges('domain',lambda state:'review_gate' if state['phase']=='awaiting_review' else END)
    builder.add_edge('review_gate',END)
    return builder.compile(checkpointer=saver)


def run_graph(engine,job_id,token):
    _,url=checkpoint_url(engine)
    with PostgresSaver.from_conn_string(url) as saver:
        graph=build_graph(engine,saver)
        result=graph.invoke({'job_id':job_id,'token':token},{'configurable':{'thread_id':job_id}})
        return {'job_id':job_id,'phase':result['phase'],'outcome':result['outcome']}


def inspect_graph(engine,job_id):
    _,url=checkpoint_url(engine)
    with PostgresSaver.from_conn_string(url) as saver:
        state=build_graph(engine,saver).get_state({'configurable':{'thread_id':job_id}})
        return {'job_id':job_id,'values':dict(state.values),'next':list(state.next),
                'interrupts':[item.value for task in state.tasks for item in task.interrupts]}


def resume_graph(engine,job_id):
    with engine.connect() as connection:
        job=jobs.get_job(connection,job_id)
        case=show_case(connection,job['case_id'])
        if case['status'] in ('open','awaiting_review'):
            raise ValueError('Record a real case review/escalation before resuming graph')
    _,url=checkpoint_url(engine)
    with PostgresSaver.from_conn_string(url) as saver:
        graph=build_graph(engine,saver)
        config={'configurable':{'thread_id':job_id}}
        state=graph.get_state(config)
        if not state.values:
            raise ValueError('No checkpoint found; replay completed job first')
        if not state.next:
            return {'job_id':job_id,'phase':state.values['phase'],'outcome':state.values['outcome']}
        result=graph.invoke(Command(resume={'source':'durable_case_review'}),config)
        return {'job_id':job_id,'phase':result['phase'],'outcome':result['outcome']}
