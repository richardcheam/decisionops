"""Owned-schema fake-session traces only. Never loads checkpoints or touches runtime."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from decisionops.commerce.database import database_engine
from decisionops.commerce.seed import seed
from decisionops.commerce.cases import open_case
from decisionops.commerce.read_tools import AssessmentRequest
from decisionops.commerce import adaptive_sessions as sessions,adaptive_jobs as jobs,schema as db

ROOT=Path(__file__).resolve().parents[1]
def dump(path,value):path.write_text(json.dumps(value,indent=2,default=str)+'\n')

def main():
    url=make_url(os.environ['COMMERCE_TEST_DATABASE_URL'])
    if (url.host,url.port,url.database)!=('127.0.0.1',55441,'commerce_stage5_test'):raise ValueError('Use verified disposable Stage 5 55441 test database only')
    admin=database_engine(url)
    with admin.connect() as c:
        identity=tuple(c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one())
    if identity!=('commerce_stage5_test','commerce_stage5',5432):raise ValueError('Unexpected isolated database identity')
    name='demo_adaptive_sessions_'+uuid.uuid4().hex;out=Path(tempfile.mkdtemp(prefix='stage5-session-',dir=ROOT/'runs'))
    with admin.begin() as c:c.exec_driver_sql('CREATE SCHEMA "'+name+'"')
    engine=database_engine(url.update_query_dict({'options':'-csearch_path='+name}));checkpoint=None;commands=[]
    def cli(label,*args):
        cmd=[sys.executable,'-B','-m','decisionops.commerce.adaptive_worker',*args]
        run=subprocess.run(cmd,cwd=ROOT,env={**os.environ,'COMMERCE_DATABASE_URL':engine.url.render_as_string(hide_password=False)},capture_output=True,text=True,timeout=30)
        (out/(label+'.stdout')).write_text(run.stdout);(out/(label+'.stderr')).write_text(run.stderr)
        commands.append({'command':cmd,'exit':run.returncode,'stdout':label+'.stdout','stderr':label+'.stderr'})
        if run.returncode:raise RuntimeError('CLI failed; inspect '+str(out))
        return json.loads(run.stdout)
    try:
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine,observed_at=datetime.now(timezone.utc));checkpoint=cli('setup','setup')['checkpoint_namespace']
        details={}
        for label,behavior in [('success','normal'),('uncertain','wrong-request')]:
            with engine.begin() as c:case=open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
            job=cli(label+'-enqueue','enqueue','--case',case['id'],'--report','Lost parcel','--session','fake','--fake-session-behavior',behavior)
            outcome=cli(label+'-once','once');state=cli(label+'-inspect','inspect','--job',job['id'])
            if behavior!='normal':
                if outcome['event']!='uncertain_decision':raise AssertionError('Expected wrong-correlation uncertainty')
                token=state['job']['token'];cli(label+'-recover','recover','--job',job['id'],'--token',token)
                cli(label+'-resume','resume','--job',job['id'],'--token',token)
                state=cli(label+'-final','inspect','--job',job['id'])
            with engine.begin() as c:
                phases=sessions.records(c,job['run_id']);calls=[dict(r) for r in c.execute(db.adaptive_calls.select().where(db.adaptive_calls.c.run_id==job['run_id'])).mappings()]
                events=[dict(r) for r in c.execute(db.adaptive_session_events.select().where(db.adaptive_session_events.c.session_id.in_([r['id'] for r in phases]))).mappings()]
            dump(out/(label+'-sessions.json'),phases);dump(out/(label+'-calls.json'),calls);dump(out/(label+'-phase-events.json'),events)
            details[label]={'state':state['run']['state'],'decisions':state['run']['decision_attempts'],'tools':state['run']['tool_attempts'],
                'sessions':len(phases),'loads':sum(bool(r['actual_charge_ms'] is not None and r['load_ms']) for r in phases),
                'uncertain_calls':sum(r['state']=='uncertain' for r in calls),'duplicate_dispatches':sum(max(0,r['dispatch_count']-1) for r in calls),
                'all_children_reaped':all(r['diagnostics'].get('process_reaped') for r in phases)}
        with engine.connect() as c:stock=c.exec_driver_sql("SELECT on_hand,reserved FROM inventory WHERE variant_id='shirt-blue-M'").one()
        if tuple(stock)!=(10,1):raise AssertionError('Investigation changed business stock')
        summary={'agent_executed':True,'simulated_provider':True,'model_loading':False,'database':url.database,'port':url.port,'schema':name,'checkpoint_namespace':checkpoint,'results':details,'stock_unchanged':True,'output':str(out)}
        dump(out/'summary.json',summary);dump(out/'commands.json',commands);print(json.dumps(summary,indent=2))
    finally:
        engine.dispose()
        with admin.begin() as c:
            if checkpoint:c.exec_driver_sql('DROP SCHEMA "'+checkpoint+'" CASCADE')
            c.exec_driver_sql('DROP SCHEMA "'+name+'" CASCADE')
        admin.dispose()

if __name__=='__main__':main()
