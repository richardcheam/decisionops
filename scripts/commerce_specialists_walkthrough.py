"""Offline specialist comparison/traces in an owned disposable PostgreSQL schema.

Requires COMMERCE_TEST_DATABASE_URL pointing to an explicitly isolated test DB.
No API, models, original runtime, or telemetry. Raw reports are not exported.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from decisionops.commerce.database import database_engine
    from decisionops.commerce import adaptive_investigations as service, adaptive_jobs as jobs
    from decisionops.commerce import multi_agent as multi, multi_agent_workflow as graph
    from decisionops.commerce.seed import seed
    from decisionops.commerce.cases import open_case, show_case, review_case
    from decisionops.commerce.execution import execute
    from decisionops.commerce.read_tools import AssessmentRequest
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='runs/multi-agent/walkthrough');args=p.parse_args()
    url=make_url(os.environ['COMMERCE_TEST_DATABASE_URL'])
    if url.database!='specialists_test' or url.host not in ('127.0.0.1','localhost') or url.port!=55548:
        raise ValueError('Walkthrough requires the documented disposable specialists_test at loopback:55548')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    schema='specialist_demo_'+uuid.uuid4().hex
    admin=database_engine(url);engine=None;namespace=None
    with admin.begin() as c:
        binding=c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one()
        if binding[0]!='specialists_test' or binding[1]!='specialists_test':raise ValueError('Unexpected server identity')
        c.exec_driver_sql('CREATE SCHEMA "'+schema+'"')
    summary={'mode':'mocked specialists versus existing fixed-order adaptive rules','binding':list(binding),'scenarios':{},'api_calls':0}
    try:
        engine=database_engine(url.update_query_dict({'options':'-csearch_path='+schema}))
        cfg=Config('alembic.ini')
        with engine.begin() as c:cfg.attributes['connection']=c;command.upgrade(cfg,'head')
        seed(engine,observed_at=datetime.now(timezone.utc))
        def case():
            with service.transaction(engine) as c:return open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
        def own():
            run=multi.start(engine,case()['id'],'Customer reports a missing parcel. Investigate records.')
            saved=jobs.claim(engine,job_id=run['job']['id'],action=jobs.SPECIALIST_ACTION)
            return run,jobs.Fence(saved['id'],saved['token'])
        def save(label,run,start):
            result=service.inspect(engine,run['id']);trace=multi.trace(engine,run['id'])
            (out/(label+'.json')).write_text(json.dumps(trace,indent=2,default=str)+'\n')
            summary['scenarios'][label]={'state':result['state'],'tools':result['tool_attempts'],'decisions':result['decision_attempts'],
                'coverage':sum(v is not None for v in result['assessment']['facts'].values()),
                'elapsed_ms':round((time.monotonic()-start)*1000),'trace':label+'.json'}
            return result
        # Existing fixed-order controller baseline: same fictional request, all seven reads.
        initial=case();begin=time.monotonic();base=service.start(engine,initial['id'],'Customer reports a missing parcel. Investigate records.')
        base=service.drive(engine,base['id']);assert base['state']=='proposed'
        summary['baseline']={'name':'existing fixed-order adaptive rules','state':base['state'],'tools':base['tool_attempts'],
            'decisions':base['decision_attempts'],'elapsed_ms':round((time.monotonic()-begin)*1000)}
        begin=time.monotonic();run,fence=own();graph.run(engine,fence);namespace=graph.checkpoint_url(engine)[0]
        success=save('success',run,begin);assert success['state']=='proposed' and success['tool_attempts']==7
        # Completed order evidence survives an unavailable shipment specialist.
        class Unavailable:
            def choose(self,request,cancel):raise RuntimeError('Fictional adapter unavailable')
        begin=time.monotonic();run,fence=own();graph.run(engine,fence,adapters={'shipment':Unavailable()})
        failed=save('partial-failure',run,begin)
        assert failed['state']=='review' and failed['assessment']['facts']['paid'] is True and failed['assessment']['facts']['shipped'] is True
        assert failed['assessment']['facts']['loss_confirmed'] is None
        # Stop after order commits; reclaim expired ownership, replay graph projection.
        begin=time.monotonic();run,fence=own();multi.support(engine,fence);multi.branch(engine,fence,'order')
        before=multi.trace(engine,run['id']);(out/'recovery-before.json').write_text(json.dumps(before,indent=2,default=str)+'\n')
        retained={o['id'] for o in service.inspect(engine,run['id'])['observations']}
        with engine.begin() as c:c.exec_driver_sql("UPDATE commerce_adaptive_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(fence.job_id,))
        reclaimed=jobs.claim(engine,job_id=fence.job_id,action=jobs.SPECIALIST_ACTION)
        newfence=jobs.Fence(reclaimed['id'],reclaimed['token']);graph.run(engine,newfence)
        recovered=save('recovery-after',run,begin)
        assert recovered['state']=='proposed' and recovered['tool_attempts']==7
        assert retained<={o['id'] for o in recovered['observations']}
        summary['scenarios']['recovery-after']['retained_observations']=len(retained)
        # Explicit staff operations, separate from agent/graph authority.
        with service.transaction(engine) as c:
            saved=show_case(c,success['case_id'])
            approved=review_case(c,saved['id'],saved['generation'],saved['proposal_id'],saved['proposal']['content_hash'],'approve')
            op=approved['approval']['operation_id'];execute(c,saved['id'],op);execute(c,saved['id'],op)
            count=c.exec_driver_sql('SELECT count(*) FROM commerce_replacement_orders').scalar_one()
            assert count==1
            summary['fictional_execution']={'staff_approved_exact_proposal':True,'explicit_execution_invocations':2,'replacement_count':count}
        with engine.begin() as c:
            summary['proposal_count']=c.exec_driver_sql('SELECT count(*) FROM commerce_proposals').scalar_one()
            assert summary['proposal_count']==3  # rules + success + recovery, never partial failure.
        summary['cleanup']='owned business and checkpoint schemas dropped; isolated server retained'
        (out/'summary.json').write_text(json.dumps(summary,indent=2,default=str)+'\n')
        print(json.dumps(summary,indent=2,default=str))
    finally:
        if engine:engine.dispose()
        with admin.begin() as c:
            c.exec_driver_sql('DROP SCHEMA "'+schema+'" CASCADE')
            if namespace:c.exec_driver_sql('DROP SCHEMA IF EXISTS "'+namespace+'" CASCADE')
        admin.dispose()
if __name__=='__main__':main()
