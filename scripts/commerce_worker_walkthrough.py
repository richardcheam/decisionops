"""Persisted review pause and dead-worker recovery in an isolated fictional schema."""
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
from decisionops.commerce.worker import claim_one
from decisionops.commerce.workflow import graph_schema


def main():
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:
        raise SystemExit('Set COMMERCE_TEST_DATABASE_URL to the local fictional demo database')
    schema='worker_walkthrough_'+uuid.uuid4().hex
    admin=database_engine(url)
    scoped=make_url(url).update_query_dict({'options':'-csearch_path='+schema})
    engine=database_engine(scoped)
    (ROOT/'runs').mkdir(exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='worker-walkthrough-',dir=ROOT/'runs'))
    created=False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created=True
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as connection:
            config.attributes['connection']=connection
            command.upgrade(config,'head')
        seed(engine)
        env=dict(os.environ,COMMERCE_DATABASE_URL=scoped.render_as_string(hide_password=False))
        def cli(name,module,*args,expected=0):
            result=subprocess.run([sys.executable,'-B','-m','decisionops.commerce.'+module,*args],cwd=ROOT,env=env,text=True,capture_output=True,timeout=25)
            (directory/(name+'.json')).write_text(result.stdout)
            (directory/(name+'.stderr.log')).write_text(result.stderr)
            if result.returncode!=expected:
                raise RuntimeError(f'{name}: exit {result.returncode}; see {directory}')
            return json.loads(result.stdout) if result.stdout else None
        cli('setup','worker','setup')
        opened=cli('open','case_demo','open','--order','ORD-1042','--shipment','SHIP-1042','--item','shirt-blue-M:1')
        queued=cli('enqueue','worker','enqueue','--case',opened['id'],'--action','investigate')
        # Simulate a process that died after committing a claim, before domain work.
        abandoned=claim_one(engine,1)
        (directory/'abandoned-claim.json').write_text(json.dumps({'id':abandoned['id'],'attempts':abandoned['attempts']}))
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE commerce_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(queued['id'],))
        recovered=cli('recovered-worker','worker','once')
        assert recovered['phase']=='awaiting_review'
        paused=cli('durable-checkpoint','worker','show','--job',queued['id'])
        assert paused['graph']['next']==['review_gate'] and paused['job']['attempts']==2
        cli('fake-resume','worker','resume','--job',queued['id'],expected=2)
        case=cli('inspect-case','case_demo','show-case','--case',opened['id'])
        approved=cli('approve','case_demo','review','--case',case['id'],'--generation',str(case['generation']),
                     '--proposal',case['proposal']['id'],'--hash',case['proposal']['content_hash'],'--decision','approve')
        resumed=cli('resume-after-review','worker','resume','--job',queued['id'])
        assert resumed['phase']=='approved'
        operation=approved['approval']['operation_id']
        execution=cli('enqueue-execution','worker','enqueue','--case',case['id'],'--action','execute','--operation',operation)
        assert cli('execute-worker','worker','once')['phase']=='verified'
        assert cli('replay-completed','worker','replay','--job',execution['id'])['phase']=='verified'
        assert cli('reconcile','case_demo','reconcile','--operation',operation)['status']=='verified'
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one()==1
            assert connection.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one()==2
        print('expired claim recovered: attempt 2; original worker token fenced')
        print('review interrupt persisted across processes; fake resume rejected')
        print('real review -> resume -> queued execution: verified')
        print('completed outcome replay: one operation; no additional stock reservation')
        print('artifacts: '+str(directory.relative_to(ROOT)))
    finally:
        engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{graph_schema(schema)}" CASCADE')
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
    print('isolated business/checkpoint schemas removed; public records unchanged')


if __name__=='__main__':
    main()
