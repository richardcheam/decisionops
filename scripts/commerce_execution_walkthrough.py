"""Full local approval/execution demo in a disposable fictional-store schema.

Requires COMMERCE_TEST_DATABASE_URL. Never approves or executes public demo cases.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from decisionops.commerce.database import database_engine
from decisionops.commerce.seed import seed
from decisionops.commerce.read_tools import canonical


def main():
    url = os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:
        raise SystemExit('Set COMMERCE_TEST_DATABASE_URL to your local fictional demo database')
    schema = 'execution_walkthrough_' + uuid.uuid4().hex
    admin = database_engine(url)
    scoped = make_url(url).update_query_dict({'options': '-csearch_path=' + schema})
    engine = database_engine(scoped)
    (ROOT / 'runs').mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='execution-walkthrough-', dir=ROOT / 'runs'))
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True
        config = Config(str(ROOT / 'alembic.ini'))
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        seed(engine)
        env = dict(os.environ, COMMERCE_DATABASE_URL=scoped.render_as_string(hide_password=False))
        def cli(name, *args, expected=0):
            completed = subprocess.run([sys.executable, '-B', '-m', 'decisionops.commerce.case_demo', *args],
                                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            (directory / (name + '.json')).write_text(completed.stdout)
            (directory / (name + '.stderr.log')).write_text(completed.stderr)
            if completed.returncode != expected:
                raise RuntimeError(f'{name}: exit {completed.returncode}, expected {expected}; see {directory}')
            return json.loads(completed.stdout) if completed.stdout else None
        case = cli('open', 'open', '--order', 'ORD-1042', '--shipment', 'SHIP-1042', '--item', 'shirt-blue-M:1')
        case_id = case['id']
        case = cli('investigate', 'investigate-case', '--case', case_id)
        def approve(name, case):
            return cli(name, 'review', '--case', case_id, '--generation', str(case['generation']),
                       '--proposal', case['proposal']['id'], '--hash', case['proposal']['content_hash'], '--decision', 'approve')
        case = approve('approve-first', case)
        old_operation = case['approval']['operation_id']
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
        stale = cli('stale-execution', 'execute', '--case', case_id, '--operation', old_operation, expected=4)
        assert stale['status'] == 'requires_reinvestigation'
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE inventory SET on_hand=10 WHERE variant_id='shirt-blue-M'")
        cli('revoked-approval', 'execute', '--case', case_id, '--operation', old_operation, expected=2)
        case = cli('reinvestigate', 'investigate-case', '--case', case_id)
        case = approve('approve-current', case)
        operation = case['approval']['operation_id']
        executed = cli('execute', 'execute', '--case', case_id, '--operation', operation)
        retry = cli('duplicate-execute', 'execute', '--case', case_id, '--operation', operation)
        recovered = cli('reconcile', 'reconcile', '--operation', operation)
        cli('final-case', 'show-case', '--case', case_id)
        assert executed['status'] == retry['status'] == recovered['status'] == 'verified'
        with engine.connect() as connection:
            records = {table: [dict(row) for row in connection.exec_driver_sql('SELECT * FROM ' + table).mappings()]
                       for table in ('commerce_operations', 'commerce_replacement_orders', 'commerce_replacement_lines',
                                     'commerce_reservations', 'resolutions', 'inventory')}
            assert len(records['commerce_operations']) == 1
            blue = next(row for row in records['inventory'] if row['variant_id'] == 'shirt-blue-M')
            assert blue['reserved'] == 2 and blue['on_hand'] == 10
        (directory / 'business-records.json').write_text(canonical(records))
        print('stock drift: approval revoked; old operation cannot execute after stock restoration')
        print('reinvestigate + approve + execute: verified; 1 replacement, 1 reservation, 1 compensation')
        print('duplicate execution + reconciliation: same operation; stock reserved only once')
        print('artifacts: ' + str(directory.relative_to(ROOT)))
    finally:
        engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
    print('isolated schema removed; public demo business records unchanged')


if __name__ == '__main__':
    main()
