"""Frozen synthetic customer/staff comparison; default and simulation are model-free.

An authorized evaluator may inject a ModelActionAdapter via evaluate(adapter=...).
This module does not construct a provider client or consume a key. Tracing
requires an explicitly injected tracer.
Observed local runtime is not live model latency. Live quality/cost stay unmeasured
without a separately authorized and documented provider experiment.
"""
from datetime import datetime,timezone
import hashlib
import json
import os
import time
import uuid
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from .database import database_engine

CASES=('resolution','ambiguity','wrong_owner','stale_evidence','carrier_outage')

def simulated_transport(payload):
    from .role_actions import DemoCustomerRouter,DemoStaffRouter
    if payload['role']=='customer':return {'kind':DemoCustomerRouter().choose(payload['message']).kind}
    if payload['role']=='staff':return {'kind':DemoStaffRouter().choose(payload['message']).kind}
    allowed=payload['features']['allowed_actions']
    return next((a for a in allowed if a['kind']=='read'),allowed[0])


def evaluate(url,*,simulate_adapter=False,adapter=None,specialist_adapter=None,tracer=None):
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from .api import create_app
    from .seed import seed
    from .delivery_seed import seed as delivery_seed
    from .customer_seed import seed as customer_seed
    from .role_actions import ModelActionAdapter
    from . import schema as db,staff_investigations as staff,adaptive_jobs as jobs,multi_agent_workflow as graph,worker
    from .workflow import graph_schema,setup_checkpoints
    from .observability import SafeTracer
    tracer=tracer if tracer is not None else SafeTracer()
    if make_url(url).host not in ('127.0.0.1','localhost','::1'):raise ValueError('Use disposable loopback PostgreSQL')
    if sum((simulate_adapter,adapter is not None,specialist_adapter is not None))>1:
        raise ValueError('Choose simulation, full adapter or specialist-only adapter')
    modes=[('rules',None)]
    if simulate_adapter:modes.append(('adapter_simulation',ModelActionAdapter(simulated_transport)))
    elif adapter is not None:modes.append(('injected_adapter',adapter))
    elif specialist_adapter is not None:modes.extend((('mock_specialists',None),('injected_specialists',None)))
    frozen=datetime.now(timezone.utc).replace(microsecond=0);runs=[];admin=database_engine(url)
    try:
        for name in CASES:
            for mode,current_adapter in modes:
                schema='customer_eval_'+uuid.uuid4().hex
                with admin.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
                engine=database_engine(make_url(url).update_query_dict({'options':'-csearch_path='+schema}))
                specialist_schema=None
                try:
                    cfg=Config('alembic.ini')
                    with engine.begin() as c:cfg.attributes['connection']=c;command.upgrade(cfg,'head')
                    seed(engine,observed_at=frozen);delivery_seed(engine,frozen);customer_seed(engine);setup_checkpoints(engine)
                    if name=='stale_evidence':
                        with engine.begin() as c:
                            c.execute(db.policies.insert().values(id='evaluation-short-freshness',store_id='demo-store',version=1001,
                                allow_confirmed_loss=True,max_units=10,carrier_max_age_seconds=30))
                            c.execute(db.orders.update().where(db.orders.c.id=='DEMO-LYON').values(policy_id='evaluation-short-freshness'))
                    # Hash business inputs before conversation/investigation mutations.
                    with engine.connect() as c:
                        source={table.name:[dict(row) for row in c.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings()]
                            for table in (db.orders,db.order_lines,db.shipments,db.shipment_lines,db.payments,db.policies,db.inventory,db.carrier_events,db.delivery_parcels,db.customer_orders)}
                    source_hash=hashlib.sha256(json.dumps(source,sort_keys=True,default=str).encode()).hexdigest()
                    use_specialists=bool(current_adapter) or mode in ('mock_specialists','injected_specialists')
                    graph_adapter=specialist_adapter if mode=='injected_specialists' else current_adapter
                    investigation_id=tool_attempts=None
                    specialist_decisions=[]
                    app=create_app(engine,password='fictional-evaluation-staff',action_adapter=current_adapter,
                        staff_investigation_mode='mock-specialists' if use_specialists else 'rules',
                        customer_accounts={'camille':{'customer_id':'camille','password':'fictional-evaluation-camille'},
                                           'alex':{'customer_id':'alex','password':'fictional-evaluation-alex'}})
                    with TestClient(app) as client:
                        owner='alex' if name in ('wrong_owner','carrier_outage') else 'camille'
                        customer_auth=(owner,'fictional-evaluation-'+owner)
                        staff_auth=('operator','fictional-evaluation-staff')
                        started=time.monotonic()
                        if name=='wrong_owner':
                            response=client.get('/customer-api/orders/DEMO-LYON',auth=customer_auth)
                            outcome='denied' if response.status_code==404 else 'wrong_owner_exposed';expected='denied'
                        else:
                            order='DEMO-SPLIT' if name=='ambiguity' else 'DEMO-OUTAGE' if name=='carrier_outage' else 'DEMO-LYON'
                            conversation=client.post('/customer-api/conversations',json={},auth=customer_auth).json()['id']
                            selected=client.post('/customer-api/conversations/'+conversation+'/select',json={
                                'order_id':order,'shipment_id':None if name=='ambiguity' else 'PARCEL-'+order},auth=customer_auth)
                            assert selected.status_code==200,selected.text
                            response=client.post('/customer-api/conversations/'+conversation+'/messages',json={
                                'message':'My parcel never arrived. Please report it missing.','request_id':'FROZEN-REPORT'},auth=customer_auth)
                            assert response.status_code==200,response.text
                            if name=='ambiguity':outcome=response.json()['intent'];expected='clarify'
                            else:
                                case_id=response.json()['case_id']
                                staff_chat=client.post('/api/conversations',json={},auth=staff_auth).json()['id']
                                client.post('/api/conversations/'+staff_chat+'/select',json={'case_id':case_id},auth=staff_auth).raise_for_status()
                                investigation=client.post('/api/conversations/'+staff_chat+'/messages',json={'message':'Fix this','request_id':'FROZEN-INVESTIGATION'},auth=staff_auth)
                                assert investigation.status_code==200,investigation.text
                                if use_specialists:
                                    with engine.connect() as c:
                                        run=c.execute(sa.select(db.adaptive_runs).where(db.adaptive_runs.c.case_id==case_id)).mappings().one()
                                        job_id=c.execute(sa.select(db.adaptive_jobs.c.id).where(db.adaptive_jobs.c.run_id==run['id'])).scalar_one()
                                    claimed=jobs.claim(engine,job_id=job_id,action=jobs.SPECIALIST_ACTION)
                                    specialist_schema=graph.checkpoint_url(engine)[0]
                                    graph.run(engine,jobs.Fence(claimed['id'],claimed['token']),
                                        adapters={'order':graph_adapter,'shipment':graph_adapter},tracer=tracer)
                                else:staff.work_once(engine,tracer=tracer)
                                with engine.connect() as c:
                                    investigation_id,tool_attempts=c.execute(sa.select(
                                        db.adaptive_runs.c.id,db.adaptive_runs.c.tool_attempts).where(
                                        db.adaptive_runs.c.case_id==case_id)).one()
                                    if mode=='injected_specialists':
                                        calls=db.specialist_calls
                                        specialist_decisions=[dict(row) for row in c.execute(sa.select(
                                            calls.c.id,calls.c.disposition,calls.c.error).where(
                                            calls.c.run_id==investigation_id,calls.c.dispatch_count>0)).mappings()]
                                saved=client.get('/api/cases/'+case_id,auth=staff_auth).json()
                                if name=='resolution' and saved['proposal']:
                                    proposal=saved['proposal']
                                    approved=client.post('/api/cases/'+case_id+'/review',json={'generation':saved['generation'],
                                        'proposal_id':proposal['id'],'content_hash':proposal['content_hash'],'decision':'approve'},auth=staff_auth)
                                    assert approved.status_code==200,approved.text
                                    confirmed=client.post('/api/cases/'+case_id+'/execute',json={'operation_id':approved.json()['approval']['operation_id']},auth=staff_auth)
                                    assert confirmed.status_code==202,confirmed.text
                                    execution_result=worker.work_once(engine)
                                    assert execution_result['event']=='job_result',execution_result
                                    public=client.get('/customer-api/conversations/'+conversation,auth=customer_auth).json()['cases'][0]
                                    outcome='replacement_created' if public['replacement_created'] and not public['shipped'] else 'unverified'
                                    expected='replacement_created'
                                else:
                                    outcome='review' if saved['status']=='needs_review' and saved['proposal'] is None else saved['status']
                                    expected='replacement_created' if name=='resolution' else 'review'
                        runs.append({'case':name,'mode':mode,'source_hash':source_hash,'outcome':outcome,'expected':expected,
                            'matches_expected':outcome==expected,'investigation_id':investigation_id,
                            'tool_attempts':tool_attempts,'specialist_decisions':specialist_decisions,
                            'observed_local_ms':round((time.monotonic()-started)*1000,3)})
                finally:
                    engine.dispose()
                    with admin.begin() as c:
                        for drop in (specialist_schema,graph_schema(schema),schema):
                            if drop:c.exec_driver_sql('DROP SCHEMA IF EXISTS '+c.dialect.identifier_preparer.quote(drop)+' CASCADE')
    finally:admin.dispose()
    return {'contract':'customer-staff-comparison/v1','population':list(CASES),'runs':runs,
        'interpretation':('Frozen cases with identical customer/staff routing and identical specialist graph for the two specialist modes.'
            if specialist_adapter is not None else 'Frozen synthetic public flows. Simulation tests typed adapter/graph wiring, not model quality.'),
        'paid_model_calls':0 if adapter is None and specialist_adapter is None else None,'live_model_quality':None,'live_model_latency_ms':None,'live_model_cost_usd':None,
        'live_model_status':('See injected specialist outcomes and any provider measurements.' if specialist_adapter is not None
            else 'unmeasured; no paid model constructed by this harness'),
        'hosted_traces_exported':False if not tracer.enabled else None}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--simulate-adapter',action='store_true');args=parser.parse_args()
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:parser.error('Set disposable loopback COMMERCE_TEST_DATABASE_URL')
    print(json.dumps(evaluate(url,simulate_adapter=args.simulate_adapter),indent=2))
