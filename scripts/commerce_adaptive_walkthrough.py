"""Stage 2 CLI success/fault demo in an owned disposable PostgreSQL schema only."""
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
    from decisionops.commerce.adaptive_evidence import canonical
    base=os.environ.get('COMMERCE_TEST_DATABASE_URL','')
    url=make_url(base)
    if url.host not in ('127.0.0.1','localhost') or url.port==55432 or not url.database.endswith(('_test','_demo')):
        raise ValueError('Use an explicitly isolated loopback *_test or *_demo database, never port 55432')
    admin=database_engine(url);schema='demo_adaptive_'+uuid.uuid4().hex
    outputs=Path(tempfile.mkdtemp(prefix='stage2-walkthrough-',dir=ROOT/'runs'))
    with admin.begin() as c:
        assert c.exec_driver_sql('SELECT current_database()').scalar_one()==url.database
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped=url.update_query_dict({'options':'-csearch_path='+schema})
    engine=database_engine(scoped)
    commands=[]
    def cli(name,module,*args):
        argv=[sys.executable,'-B','-m',module,*args]
        commands.append(argv)
        result=subprocess.run(argv,cwd=ROOT,env={**os.environ,'COMMERCE_DATABASE_URL':scoped.render_as_string(hide_password=False)},
                              capture_output=True,text=True,timeout=30)
        (outputs/(name+'.stdout.json')).write_text(result.stdout)
        (outputs/(name+'.stderr.log')).write_text(result.stderr)
        if result.returncode:raise RuntimeError(f'{name} failed: see {outputs}')
        return json.loads(result.stdout)
    try:
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:
            assert c.exec_driver_sql('SELECT current_schema()').scalar_one()==schema
            config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine)
        results={}
        for label in ('success','failure'):
            case=cli(label+'-open','decisionops.commerce.case_demo','open','--order','ORD-1042',
                     '--shipment','SHIP-1042','--item','shirt-blue-M:1')
            run=cli(label+'-start','decisionops.commerce.adaptive_demo','start','--case',case['id'],
                    '--report','Customer reports that their parcel has not arrived. Inspect store records.')
            args=['run','--run',run['id']]
            if label=='failure':args += ['--inject-tool-failure','order_manifest']
            final=cli(label+'-run','decisionops.commerce.adaptive_demo',*args)
            inspected=cli(label+'-inspect','decisionops.commerce.adaptive_demo','inspect','--run',run['id'])
            assert inspected['state']==final['state']
            assert not final['terminal']['execution_authorized']
            assert final['state']==('proposed' if label=='success' else 'review')
            if label=='failure':assert all(v is None for v in final['assessment']['facts'].values())
            results[label]={'run_id':run['id'],'state':final['state'],'tool_attempts':final['tool_attempts'],
                            'decision_attempts':final['decision_attempts'],'terminal':final['terminal']}
        (outputs/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        summary={'database':url.database,'host_port':url.port,'owned_schema':schema,'outputs':str(outputs),
                 'results':results,'agent_executed':True,'models_used':False,'schema_retained':False}
        (outputs/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary,indent=2))
    finally:
        engine.dispose()
        with admin.begin() as c:c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


if __name__=='__main__':main()
