"""Fresh PostgreSQL/browser acceptance for the same local Commerce application.

Requires a disposable COMMERCE_TEST_DATABASE_URL, locked Commerce dependencies,
Node20+ and frontend npm ci. Uses only synthetic credentials and carrier fixtures.
Creates a unique schema; preserves all other databases, schemas and applications.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from decisionops.commerce.database import database_engine
    from decisionops.commerce.seed import seed
    from decisionops.commerce.delivery_seed import seed as delivery_seed
    from decisionops.commerce.workflow import setup_checkpoints,graph_schema
    from decisionops.commerce.multi_agent_workflow import checkpoint_url
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8157)
    args=parser.parse_args()
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:parser.error('Set isolated COMMERCE_TEST_DATABASE_URL')
    schema='delivery_browser_'+uuid.uuid4().hex
    admin=database_engine(url)
    scoped=make_url(url).update_query_dict({'options':'-csearch_path='+schema})
    engine=database_engine(scoped)
    with admin.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
    child=None;specialist_schema=None
    try:
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine);delivery_seed(engine);setup_checkpoints(engine)
        # Existing foreign-store case proves authorization, not merely unknown-ID404.
        from decisionops.commerce import schema as db
        from decisionops.commerce.cases import open_case
        from decisionops.commerce.read_tools import AssessmentRequest
        with engine.begin() as c:
            c.execute(db.policies.insert().values(id='foreign-policy',store_id='foreign-store',version=1,
                allow_confirmed_loss=True,max_units=10,carrier_max_age_seconds=86400))
            c.execute(db.orders.insert().values(id='FOREIGN-ORDER',store_id='foreign-store',policy_id='foreign-policy',currency='EUR',resolution_history_complete=True))
            foreign=open_case(c,AssessmentRequest('FOREIGN-ORDER','FOREIGN-PARCEL',{'fictional-item':1}))
        # Real persisted specialist findings followed by real inventory drift.
        # Browser acceptance must recover through the existing rules refresh.
        from decisionops.commerce import staff_investigations as staff
        with engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
            stale_case=open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
            staff.enqueue(c,engine,stale_case['id'],'Missing parcel','BROWSER-STALE-FIXTURE',stale_case['generation'],'mock-specialists')
        assert staff.work_once(engine)['state']=='proposed'
        with engine.begin() as c:
            c.execute(db.inventory.update().where(db.inventory.c.variant_id=='shirt-blue-M').values(on_hand=20))
        specialist_schema=checkpoint_url(engine)[0]
        subprocess.run(['npm','--prefix','frontend','run','build'],cwd=ROOT,check=True)
        env=dict(os.environ,COMMERCE_DATABASE_URL=scoped.render_as_string(hide_password=False),
            COMMERCE_STAFF_USERNAME='operator',COMMERCE_STAFF_PASSWORD='fictional-browser-demo-only',
            COMMERCE_HELPER_PASSWORD='fictional-helper-demo-only',COMMERCE_FOREIGN_CASE_ID=foreign['id'],COMMERCE_STALE_CASE_ID=stale_case['id'],COMMERCE_WEB_URL=f'http://127.0.0.1:{args.port}',
            LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
        with open(ROOT/'runs/delivery-browser-server.log','w') as output:
            child=subprocess.Popen([sys.executable,'-B','scripts/commerce_delivery_local.py','--port',str(args.port)],
                cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT)
            ready=False
            for _ in range(120):
                if child.poll() is not None:raise RuntimeError('Browser app exited before readiness')
                try:
                    with urllib.request.urlopen(env['COMMERCE_WEB_URL']+'/health',timeout=1) as response:ready=response.status==200
                except OSError:pass
                if ready:break
                time.sleep(.1)
            if not ready:raise RuntimeError('Browser app readiness deadline')
            subprocess.run(['npx','playwright','test','--config','playwright.delivery.config.ts'],cwd=ROOT/'frontend',env=env,check=True,timeout=180)
            with engine.connect() as c:
                counts=c.exec_driver_sql("SELECT (SELECT count(*) FROM commerce_operations WHERE order_id='DEMO-LYON'),(SELECT count(*) FROM commerce_replacement_orders r JOIN commerce_operations o ON o.id=r.operation_id WHERE o.order_id='DEMO-LYON'),(SELECT count(*) FROM commerce_reservations r JOIN commerce_operations o ON o.id=r.operation_id WHERE o.order_id='DEMO-LYON'),(SELECT sum(r.quantity) FROM commerce_reservations r JOIN commerce_operations o ON o.id=r.operation_id WHERE o.order_id='DEMO-LYON')").one()
                assert tuple(counts)==(1,1,1,1),'Browser execution did not leave exactly one operation and reservation set'
            print(json.dumps({'browser':'passed','lyon_operations':1,'replacement_orders':1,'reservations':1,'reserved_units':1,'paid_calls':0}))
    finally:
        if child:
            child.terminate()
            try:child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        engine.dispose()
        with admin.begin() as c:
            for name in (specialist_schema,graph_schema(schema),schema):
                if name:c.exec_driver_sql('DROP SCHEMA IF EXISTS '+c.dialect.identifier_preparer.quote(name)+' CASCADE')
        admin.dispose()

if __name__=='__main__':
    (ROOT/'runs').mkdir(exist_ok=True)
    main()
