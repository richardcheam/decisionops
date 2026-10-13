"""Model-free local-provider CLI failure/recovery proof in an owned schema."""
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
from decisionops.commerce.read_tools import canonical


def main():
    from importlib.util import find_spec
    if find_spec('torch') is not None:raise SystemExit('Use the commerce-only environment; this walkthrough deliberately requires absent model dependencies')
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:raise SystemExit('Set COMMERCE_TEST_DATABASE_URL to an isolated database')
    schema='local_failures_'+uuid.uuid4().hex;admin=database_engine(url)
    engine=database_engine(make_url(url).update_query_dict({'options':'-csearch_path='+schema}))
    (ROOT/'runs').mkdir(exist_ok=True);directory=Path(tempfile.mkdtemp(prefix='local-provider-failures-',dir=ROOT/'runs'))
    created=False
    try:
        with admin.begin() as c:c.exec_driver_sql(f'CREATE SCHEMA "{schema}"');created=True
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine)
        env=dict(os.environ,COMMERCE_DATABASE_URL=engine.url.render_as_string(hide_password=False),COMMERCE_MODEL_PYTHON=sys.executable)
        def cli(name,*arguments,expected=0):
            module=arguments[0];done=subprocess.run([sys.executable,'-B','-m','decisionops.commerce.'+module,*arguments[1:]],
                cwd=ROOT,env=env,text=True,capture_output=True,timeout=20)
            (directory/(name+'.json')).write_text(done.stdout);(directory/(name+'.stderr.log')).write_text(done.stderr)
            if done.returncode!=expected:raise RuntimeError(f'{name}: exit {done.returncode}; inspect {directory}')
            return json.loads(done.stdout)
        cli('budget','provider_demo','budget-create','--budget','FAILURES','--accounting','local','--max-requests','1','--max-cost-usd','0')
        def opened(name):return cli(name,'case_demo','open','--order','ORD-1042','--shipment','SHIP-1042','--item','shirt-blue-M:1')
        case=opened('dependency-case')
        failure=cli('missing-dependencies','provider_demo','investigate','--mode','laya','--case',case['id'],'--run','MISSING-DEPS',
            '--budget','FAILURES',expected=4)
        assert failure['trace']['result']['error_kind']=='ModuleNotFoundError' and failure['case']['status']=='escalated'
        assert failure['trace']['state']=='settled' and failure['trace']['result']['input_tokens'] is None
        denied=cli('exhausted','provider_demo','investigate','--mode','gliclass','--case',opened('denied-case')['id'],
            '--run','DENIED','--budget','FAILURES',expected=4)
        assert denied['trace']['dispatch_count']==0 and denied['trace']['state']=='denied'
        cli('timeout-budget','provider_demo','budget-create','--budget','TIMEOUT','--accounting','local','--max-cost-usd','0')
        slow=directory/'slow-worker.py';slow.write_text('import time;time.sleep(30)')
        # The worker script is injected only into this explicitly model-free proof;
        # production CLI always uses the fixed local_model_worker entry point.
        from decisionops.commerce.local_provider import LocalProvider
        from decisionops.commerce.provider_service import recommend,recover
        from decisionops.commerce.providers import ProviderConfig
        timeout=recommend(engine,opened('timeout-case')['id'],'TIMEOUT-1','TIMEOUT',ProviderConfig(mode='gliclass'),
            deadline_seconds=.2,provider=LocalProvider(python=sys.executable,worker=slow))
        (directory/'timeout.json').write_text(canonical(timeout))
        recovered=recover(engine,'TIMEOUT-1');assert recovered['trace']['dispatch_count']==1
        assert recovered['trace']['state']=='uncertain' and recovered['trace']['result']['metadata']['process_reaped']
        with engine.connect() as c:assert c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one()==0
        print('MODEL-FREE proof: missing dependency -> explicit staff review; exhausted request count -> zero dispatch')
        print('timeout -> process group reaped; same-run recovery dispatch_count=1; zero operations/API charges')
        print('Artifacts: '+str(directory.relative_to(ROOT)))
    finally:
        engine.dispose()
        if created:
            with admin.begin() as c:c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


if __name__=='__main__':main()
