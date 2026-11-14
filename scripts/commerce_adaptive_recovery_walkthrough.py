"""Stage 3 only: isolated CLI and crash/recovery/accounting trace export."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from decisionops.commerce.database import database_engine
    from decisionops.commerce.seed import seed
    from decisionops.commerce import adaptive_jobs as jobs,adaptive_investigations as service,schema as db
    from decisionops.commerce.adaptive_runner import tick,Interrupted,run_until_pause
    from decisionops.commerce.cases import open_case
    from decisionops.commerce.read_tools import AssessmentRequest
    from decisionops.commerce import adaptive_workflow as graph
    import sqlalchemy as sa
    base=make_url(os.environ['COMMERCE_TEST_DATABASE_URL'])
    if base.host not in ('localhost','127.0.0.1') or base.port==55432 or not base.database.endswith('_test'):
        raise ValueError('Verified isolated loopback *_test environment required')
    schema='demo_adaptive_recovery_'+uuid.uuid4().hex
    output=Path(tempfile.mkdtemp(prefix='stage3-recovery-',dir=ROOT/'runs'))
    admin=database_engine(base)
    with admin.begin() as c:
        assert c.exec_driver_sql('SELECT current_database()').scalar_one()==base.database
        c.exec_driver_sql('CREATE SCHEMA "'+schema+'"')
    scoped=base.update_query_dict({'options':'-csearch_path='+schema});engine=database_engine(scoped)
    config=Config(str(ROOT/'alembic.ini'));commands=[];namespace=None
    def dump(name,result):
        (output/(name+'.json')).write_text(json.dumps(result,indent=2,default=str)+'\n')
    def cli(name,*args):
        argv=[sys.executable,'-B','-m','decisionops.commerce.adaptive_worker',*args];commands.append(argv)
        result=subprocess.run(argv,cwd=ROOT,env={**os.environ,'COMMERCE_DATABASE_URL':scoped.render_as_string(hide_password=False)},
                              text=True,capture_output=True,timeout=40)
        (output/(name+'.stdout')).write_text(result.stdout);(output/(name+'.stderr')).write_text(result.stderr)
        if result.returncode:raise RuntimeError(f'{name}: {result.returncode}; see {output}')
        return json.loads(result.stdout)
    def new_case():
        with engine.begin() as c:return open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
    try:
        with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine)
        namespace=cli('setup','setup')['checkpoint_namespace']
        job=cli('enqueue','enqueue','--case',new_case()['id'],'--report','Lost parcel; inspect permitted business records')
        cli('once','once');complete=cli('inspect-success','inspect','--job',job['id'])
        assert complete['run']['state']=='proposed' and complete['job']['status']=='completed'
        owned=jobs.claim(engine,job_id=jobs.enqueue(engine,new_case()['id'],'Customer reports a missing parcel')['id'])
        fence=jobs.Fence(owned['id'],owned['token'])
        try:tick(engine,fence,fault='after_dispatch')
        except Interrupted:pass
        before=cli('inspect-interrupted','inspect','--job',owned['id']);dump('uncertain-pause',tick(engine,fence))
        cli('recover','recover','--job',owned['id'],'--token',owned['token'])
        cli('resume','resume','--job',owned['id'],'--token',owned['token'])
        final=cli('inspect-recovered','inspect','--job',owned['id'])
        assert final['run']['state']=='proposed' and final['run']['decision_attempts']==9
        with engine.begin() as c:
            calls=[dict(r) for r in c.execute(sa.select(db.adaptive_calls)).mappings()]
            events=[dict(r) for r in c.execute(sa.select(db.adaptive_call_events).order_by(db.adaptive_call_events.c.call_id,db.adaptive_call_events.c.sequence)).mappings()]
        dump('recommendations',calls);dump('recommendation-events',events);dump('commands',commands)
        assert sum(r['state']=='uncertain' for r in calls)==1
        assert all(r['dispatch_count']==1 for r in calls)
        summary={'database':base.database,'port':base.port,'schema':schema,'checkpoint_namespace':namespace,
                 'success':{'run_id':complete['run']['id'],'decisions':complete['run']['decision_attempts'],'tools':complete['run']['tool_attempts']},
                 'recovery':{'run_id':final['run']['id'],'decisions':final['run']['decision_attempts'],'tools':final['run']['tool_attempts'],
                    'uncertain_reservations':1,'duplicate_dispatches':0},'output':str(output),'agent_executed':True,'model_inference':False}
        dump('summary',summary);print(json.dumps(summary,indent=2))
    finally:
        engine.dispose()
        with admin.begin() as c:
            if namespace:c.exec_driver_sql('DROP SCHEMA IF EXISTS "'+namespace+'" CASCADE')
            c.exec_driver_sql('DROP SCHEMA "'+schema+'" CASCADE')
        admin.dispose()

if __name__=='__main__':main()
