"""Real customer/staff browser journey against a disposable PostgreSQL schema.

Synthetic accounts only. No model calls, hosted tracing or external integration.
Requires the locked Commerce environment, frontend dependencies and a local browser.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url
    from decisionops.commerce.database import database_engine
    from decisionops.commerce.seed import seed
    from decisionops.commerce.delivery_seed import seed as delivery_seed
    from decisionops.commerce.customer_seed import seed as customer_seed
    from decisionops.commerce.portfolio_seed import seed as portfolio_seed
    from decisionops.commerce.workflow import setup_checkpoints, graph_schema
    from decisionops.commerce.multi_agent_workflow import checkpoint_url
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8167)
    parser.add_argument('--compact', action='store_true', help='Use the three-case portfolio seed')
    args = parser.parse_args()
    url = os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:
        parser.error('Set disposable COMMERCE_TEST_DATABASE_URL')
    schema = 'customer_browser_' + uuid.uuid4().hex
    admin = database_engine(url)
    scoped = make_url(url).update_query_dict({'options': '-csearch_path=' + schema})
    engine = database_engine(scoped)
    with admin.begin() as c:
        c.exec_driver_sql('CREATE SCHEMA ' + schema)
    child = None
    specialist_schema = None
    try:
        config = Config(str(ROOT / 'alembic.ini'))
        with engine.begin() as c:
            config.attributes['connection'] = c
            command.upgrade(config, 'head')
        if args.compact:
            portfolio_seed(engine)
        else:
            seed(engine)
            delivery_seed(engine)
            customer_seed(engine)
        setup_checkpoints(engine)
        specialist_schema = checkpoint_url(engine)[0]
        subprocess.run(['npm', '--prefix', 'frontend', 'run', 'build'], cwd=ROOT, check=True)
        env = dict(os.environ, COMMERCE_COMPACT_DEMO='1' if args.compact else '0',
            COMMERCE_DATABASE_URL=scoped.render_as_string(hide_password=False),
            COMMERCE_STAFF_USERNAME='operator', COMMERCE_STAFF_PASSWORD='fictional-browser-demo-only',
            COMMERCE_HELPER_PASSWORD='fictional-helper-demo-only',
            COMMERCE_CUSTOMER_CAMILLE_PASSWORD='fictional-camille-browser-only',
            COMMERCE_CUSTOMER_ALEX_PASSWORD='fictional-alex-browser-only',
            COMMERCE_WEB_URL=f'http://127.0.0.1:{args.port}',
            LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
        with open(ROOT / 'runs/customer-browser-server.log', 'w') as output:
            child = subprocess.Popen([sys.executable, '-B', 'scripts/commerce_delivery_local.py', '--port', str(args.port)],
                cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            for _ in range(200):
                if child.poll() is not None:
                    raise RuntimeError('Customer browser app exited before readiness; inspect runs/customer-browser-server.log')
                try:
                    with urllib.request.urlopen(env['COMMERCE_WEB_URL'] + '/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Customer browser app readiness deadline')
            subprocess.run(['npx', 'playwright', 'test', '--config', 'playwright.customer.config.ts'],
                cwd=ROOT / 'frontend', env=env, check=True, timeout=240)
            with engine.connect() as c:
                counts = c.exec_driver_sql("""SELECT
                    (SELECT count(*) FROM commerce_operations WHERE order_id='DEMO-LYON'),
                    (SELECT count(*) FROM commerce_replacement_orders r JOIN commerce_operations o ON o.id=r.operation_id WHERE o.order_id='DEMO-LYON'),
                    (SELECT count(*) FROM commerce_reservations r JOIN commerce_operations o ON o.id=r.operation_id WHERE o.order_id='DEMO-LYON'),
                    (SELECT sum(r.quantity) FROM commerce_reservations r JOIN commerce_operations o ON o.id=r.operation_id WHERE o.order_id='DEMO-LYON'),
                    (SELECT count(*) FROM commerce_delivery_case_links WHERE order_id='DEMO-LYON')""").one()
                assert tuple(counts) == (1, 1, 1, 1, 1), 'Duplicate/missing business records: ' + repr(tuple(counts))
            print(json.dumps({'browser': 'passed', 'lyon_operations': 1, 'replacement_orders': 1,
                'reservations': 1, 'reserved_units': 1, 'canonical_case_links': 1, 'paid_calls': 0}))
    finally:
        if child:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        engine.dispose()
        with admin.begin() as c:
            for name in (specialist_schema, graph_schema(schema), schema):
                if name:
                    c.exec_driver_sql('DROP SCHEMA IF EXISTS ' + c.dialect.identifier_preparer.quote(name) + ' CASCADE')
        admin.dispose()


if __name__ == '__main__':
    (ROOT / 'runs').mkdir(exist_ok=True)
    main()
