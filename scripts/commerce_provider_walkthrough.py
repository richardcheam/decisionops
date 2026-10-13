"""Simulated provider/usage demonstration in an owned disposable PostgreSQL schema."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from decisionops.commerce.database import database_engine
from decisionops.commerce.seed import seed


def main():
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:raise SystemExit('Set COMMERCE_TEST_DATABASE_URL to the isolated fictional database')
    schema='provider_walkthrough_'+uuid.uuid4().hex
    admin=database_engine(url)
    engine=database_engine(make_url(url).update_query_dict({'options':'-csearch_path='+schema}))
    (ROOT/'runs').mkdir(exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='provider-walkthrough-',dir=ROOT/'runs'))
    created=False
    try:
        with admin.begin() as c:c.exec_driver_sql(f'CREATE SCHEMA "{schema}"');created=True
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:
            config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine)
        env=dict(os.environ,COMMERCE_DATABASE_URL=engine.url.render_as_string(hide_password=False))
        def cli(name,module,*args,expected=0):
            done=subprocess.run([sys.executable,'-B','-m','decisionops.commerce.'+module,*args],cwd=ROOT,env=env,text=True,capture_output=True,timeout=20)
            (directory/(name+'.json')).write_text(done.stdout)
            (directory/(name+'.stderr.log')).write_text(done.stderr)
            if done.returncode!=expected:raise RuntimeError(f'{name}: exit {done.returncode}; inspect {directory}')
            return json.loads(done.stdout) if done.stdout else None
        def opened(name):return cli(name,'case_demo','open','--order','ORD-1042','--shipment','SHIP-1042','--item','shirt-blue-M:1')
        rules=opened('rules-case');rules=cli('rules-default','provider_demo','investigate','--case',rules['id'],'--run','RULES-1')
        assert rules['mode']=='rules' and rules['provider_calls']==0
        cli('budget','provider_demo','budget-create','--budget','DEMO-BUDGET')
        cases=[opened('case-'+str(i)) for i in range(4)]
        results=[]
        for index,scenario in enumerate(('success','review','timeout','success')):
            result=cli('route-'+scenario+'-'+str(index),'provider_demo','investigate',
                       '--mode','fake','--case',cases[index]['id'],'--run','RUN-'+str(index),
                       '--budget','DEMO-BUDGET','--scenario',scenario,expected=4 if index>=2 else 0)
            results.append(result)
        assert results[0]['case']['status']=='awaiting_review'
        assert results[1]['case']['status']=='escalated'
        assert results[2]['trace']['state']=='uncertain'
        assert results[3]['trace']['state']=='denied' and results[3]['trace']['dispatch_count']==0
        repeated=cli('recover-timeout','provider_demo','recover','--run','RUN-2',expected=4)
        assert repeated['trace']['dispatch_count']==1
        budget=cli('inspect-budget','provider_demo','budget','--budget','DEMO-BUDGET')
        assert budget['reserved_request_count']==3 and budget['committed_cost_usd']=='0.00284000'
        cli('fault-budget','provider_demo','budget-create','--budget','FAULT-BUDGET','--max-requests','10','--max-cost-usd','1')
        for scenario in ('instruction_override','unavailable','refused','malformed'):
            case=opened('fault-case-'+scenario)
            result=cli('fault-'+scenario,'provider_demo','investigate','--mode','fake','--case',case['id'],
                       '--run','FAULT-'+scenario,'--budget','FAULT-BUDGET','--scenario',scenario,expected=4)
            assert result['case']['status']=='escalated' and not result['case']['approval']
        case=results[0]['case']
        approved=cli('exact-approval','case_demo','review','--case',case['id'],'--generation',str(case['generation']),
                     '--proposal',case['proposal_id'],'--hash',case['proposal']['content_hash'],'--decision','approve')
        operation=approved['approval']['operation_id']
        executed=cli('approved-execution','case_demo','execute','--case',case['id'],'--operation',operation)
        duplicate=cli('duplicate-execution','case_demo','execute','--case',case['id'],'--operation',operation)
        assert executed['status']==duplicate['status']=='verified'
        cli('recover-completed-route','provider_demo','recover','--run','RUN-0')
        with engine.connect() as c:
            assert c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one()==1
            assert c.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one()==2
        print('SIMULATED providers and usage only; measured local integration, not model performance or billing')
        print('rules default: zero dispatch; offer: exact approval still required; review: actual case escalation')
        print('timeout: unresolved 0.00260000 simulated USD retained; recovery: dispatch_count remains 1')
        print('exhaustion: no dispatch; three reserved requests; committed simulated USD 0.00284000')
        print('instruction override/refusal/unavailability/malformed payload: explicit review, no invented facts')
        print('exact staff approval + execution + retry: one verified replacement/reservation, no provider authority')
        print('evidence: '+str(directory.relative_to(ROOT)))
    finally:
        engine.dispose()
        if created:
            with admin.begin() as c:c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
    print('Only owned schema removed; original public store unchanged')


if __name__=='__main__':main()
