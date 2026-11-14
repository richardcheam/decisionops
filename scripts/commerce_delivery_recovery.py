"""Hard process exit after committed specialist work, then fenced worker recovery.

Requires COMMERCE_TEST_DATABASE_URL. Creates and drops only a unique test schema.
No paid calls, real integrations or public-case mutations.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from decisionops.commerce.database import database_engine
    from decisionops.commerce.seed import seed
    from decisionops.commerce.cases import open_case,show_case,review_case
    from decisionops.commerce.read_tools import AssessmentRequest
    from decisionops.commerce import staff_investigations as staff,multi_agent as multi
    from decisionops.commerce.multi_agent_workflow import checkpoint_url
    from decisionops.commerce.jobs import enqueue
    from decisionops.commerce.worker import work_once
    from decisionops.commerce.workflow import setup_checkpoints,graph_schema
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:raise SystemExit('Set COMMERCE_TEST_DATABASE_URL to isolated local PostgreSQL')
    schema='delivery_recovery_'+uuid.uuid4().hex
    admin=database_engine(url)
    scoped=make_url(url).update_query_dict({'options':'-csearch_path='+schema})
    engine=database_engine(scoped)
    with admin.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
    specialist_schema=None;execution_schema=None
    try:
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine)
        with engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            case=open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
            run=staff.enqueue(c,engine,case['id'],'Lost parcel','PROCESS-RESTART',case['generation'],'mock-specialists')
        child='''import os
from decisionops.commerce.database import database_engine
from decisionops.commerce import adaptive_jobs as jobs,multi_agent_workflow as graph
engine=database_engine()
owned=jobs.claim(engine,job_id=os.environ['RECOVERY_JOB'],action=jobs.SPECIALIST_ACTION)
def hard_exit(name,current):
    if name=='order':os._exit(73)
graph.run(engine,jobs.Fence(owned['id'],owned['token']),after_node=hard_exit)
'''
        result=subprocess.run([sys.executable,'-B','-c',child],cwd=ROOT,
            env=dict(os.environ,COMMERCE_DATABASE_URL=scoped.render_as_string(hide_password=False),RECOVERY_JOB=run['job']['id']),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=35)
        assert result.returncode==73,'Worker did not reach committed process exit boundary'
        specialist_schema=checkpoint_url(engine)[0]
        with engine.begin() as c:
            completed={r['id'] for r in multi.calls(c,run['id'],'order') if r['disposition']=='applied'}
            assert len(completed)==2,'Order specialist not fully committed before process exit'
            c.exec_driver_sql("UPDATE commerce_adaptive_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(run['job']['id'],))
        recovered=staff.work_once(engine)
        assert recovered['state']=='proposed',recovered
        with engine.begin() as c:
            assert completed=={r['id'] for r in multi.calls(c,run['id'],'order') if r['disposition']=='applied'}
            saved=show_case(c,case['id'])
            approved=review_case(c,case['id'],saved['generation'],saved['proposal_id'],saved['proposal']['content_hash'],'approve')
            operation=approved['approval']['operation_id']
            first=enqueue(c,case['id'],'execute',operation)
            second=enqueue(c,case['id'],'execute',operation)
            assert first['id']==second['id'],'Duplicated confirmation created another job'
        setup_checkpoints(engine);execution_schema=graph_schema(schema)
        work_once(engine)
        with engine.begin() as c:
            assert c.exec_driver_sql('SELECT count(*) FROM commerce_proposals').scalar_one()==1
            assert c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one()==1
            assert c.exec_driver_sql('SELECT count(*) FROM commerce_reservations').scalar_one()==1
            assert show_case(c,case['id'])['status']=='executed'
        print(json.dumps({'hard_exit':73,'committed_order_steps_reused':2,'proposals':1,'operations':1,'reservations':1,'duplicate_confirmation':'same_job','paid_calls':0}))
    finally:
        engine.dispose()
        with admin.begin() as c:
            for name in (specialist_schema,execution_schema,schema):
                if name:c.exec_driver_sql('DROP SCHEMA IF EXISTS '+c.dialect.identifier_preparer.quote(name)+' CASCADE')
        admin.dispose()

if __name__=='__main__':main()
