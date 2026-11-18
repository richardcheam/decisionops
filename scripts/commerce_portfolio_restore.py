"""Restore synthetic business records and checkpoints into a disposable database.

Creates BOTH source and target databases with unique portfolio_restore_* names.
Never dumps, changes or drops the database named in COMMERCE_TEST_DATABASE_URL.
Requires CREATEDB on an explicitly supplied loopback-only PostgreSQL server.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, help='Directory containing pg_dump and pg_restore')
    args = parser.parse_args()
    from sqlalchemy.engine import make_url
    from alembic import command
    from alembic.config import Config
    from decisionops.commerce.database import database_engine
    from decisionops.commerce.seed import seed
    from decisionops.commerce.delivery_seed import seed as delivery_seed
    from decisionops.commerce.workflow import setup_checkpoints, inspect_graph
    from decisionops.commerce.schema_readiness import validate_readiness, SUPPORTED_REVISION
    from decisionops.commerce.cases import open_case, show_case, review_case
    from decisionops.commerce import jobs
    from decisionops.commerce.worker import work_once
    from decisionops.commerce.read_tools import AssessmentRequest
    from decisionops.commerce.execution import reconcile
    raw = os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not raw:
        parser.error('Set an explicit disposable loopback COMMERCE_TEST_DATABASE_URL')
    url = make_url(raw)
    if url.host not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('Restore rehearsal is restricted to an explicit loopback test server')
    binaries = args.pg_bin
    dump_tool = str(binaries / 'pg_dump') if binaries else shutil.which('pg_dump')
    restore_tool = str(binaries / 'pg_restore') if binaries else shutil.which('pg_restore')
    if not dump_tool or not restore_tool or not Path(dump_tool).is_file() or not Path(restore_tool).is_file():
        parser.error('Install PostgreSQL client tools or pass --pg-bin; no database changes made')
    # The connected database is only used as a server-control connection. Each
    # business database is newly created and receives a fresh migrated fixture.
    admin = database_engine(url.set(query={}))
    suffix = uuid.uuid4().hex
    source, target = 'portfolio_restore_source_' + suffix, 'portfolio_restore_target_' + suffix
    engines, created = [], []
    (ROOT / 'runs').mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='portfolio-restore-', dir=ROOT / 'runs'))
    directory.chmod(0o700)
    dump = directory / 'synthetic.dump'
    def engine_for(name):
        engine = database_engine(url.set(database=name, query={}))
        engines.append(engine)
        return engine
    def snapshot(engine):
        result = {}
        with engine.connect() as c:
            tables = c.exec_driver_sql("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2").all()
            for schema, table in tables:
                quote = c.dialect.identifier_preparer.quote
                value = c.exec_driver_sql(f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM {quote(schema)}.{quote(table)} t").scalar_one()
                result[schema + '.' + table] = {'rows': len(json.loads(value)), 'sha256': hashlib.sha256(value.encode()).hexdigest()}
        return result
    try:
        for name in (source, target):
            with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
                c.exec_driver_sql('CREATE DATABASE ' + c.dialect.identifier_preparer.quote(name) + " TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'")
            created.append(name)
        original, restored = engine_for(source), engine_for(target)
        config = Config(str(ROOT / 'alembic.ini'))
        with original.begin() as c:
            config.attributes['connection'] = c
            command.upgrade(config, 'head')
        seed(original)
        delivery_seed(original)
        try:
            from decisionops.commerce.customer_seed import seed as customer_seed
        except ImportError:
            raise RuntimeError('Customer seed is required; wait for the integrated portfolio source') from None
        customer_seed(original)
        setup_checkpoints(original)
        # Populate actual worker graph checkpoints as well as business ledgers.
        # The investigation graph pauses for review, then a separate execution
        # job records the replacement after exact staff approval.
        with original.begin() as c:
            case = open_case(c, AssessmentRequest('ORD-1042', 'SHIP-1042', {'shirt-blue-M': 1}))
            investigation_job = jobs.enqueue(c, case['id'], 'investigate')
        if work_once(original)['event'] != 'job_result':
            raise RuntimeError('Synthetic investigation worker did not save graph progress')
        with original.begin() as c:
            case = show_case(c, case['id'])
            proposal = case['proposal']
            if proposal is None:
                raise RuntimeError('Synthetic restore fixture did not produce a proposal')
            case = review_case(c, case['id'], case['generation'], proposal['id'], proposal['content_hash'], 'approve', actor='synthetic-restore-operator')
            operation = case['approval']['operation_id']
            execution_job = jobs.enqueue(c, case['id'], 'execute', operation)
        if work_once(original)['event'] != 'job_result':
            raise RuntimeError('Synthetic execution worker did not save graph progress')
        with original.connect() as c:
            if reconcile(c, operation)['status'] != 'verified':
                raise RuntimeError('Synthetic replacement did not reconcile before backup')
        graph_before = {job['id']: inspect_graph(original, job['id']) for job in (investigation_job, execution_job)}
        expected = snapshot(original)
        pg_env = dict(os.environ, PGHOST=url.host, PGPORT=str(url.port or 5432), PGUSER=url.username or '', PGDATABASE=source)
        if url.password:
            pg_env['PGPASSWORD'] = url.password
        with dump.open('xb') as output:
            dump.chmod(0o600)
            subprocess.run([dump_tool, '--format=custom', '--no-owner', '--no-acl'], env=pg_env, stdout=output, check=True, timeout=60)
        pg_env['PGDATABASE'] = target
        subprocess.run([restore_tool, '--exit-on-error', '--no-owner', '--no-acl', '--dbname', target, str(dump)], env=pg_env, check=True, timeout=60, stdout=subprocess.DEVNULL)
        actual = snapshot(restored)
        if expected != actual:
            raise RuntimeError('Restored table row counts/content hashes differ')
        graph_after = {identity: inspect_graph(restored, identity) for identity in graph_before}
        if graph_before != graph_after:
            raise RuntimeError('Restored graph progress differs')
        with restored.connect() as c:
            validate_readiness(c)
            if reconcile(c, operation)['status'] != 'verified':
                raise RuntimeError('Restored replacement does not reconcile')
        summary = {'status': 'passed', 'revision': SUPPORTED_REVISION, 'databases': 'new disposable source and target only', 'tables': actual, 'replacement_reconciled': True, 'worker_graphs_restored': len(graph_after), 'operator_database_unchanged': True}
        (directory / 'verification.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps({'status': 'passed', 'revision': SUPPORTED_REVISION, 'tables_compared': len(actual), 'replacement_reconciled': True, 'worker_graphs_restored': len(graph_after), 'evidence': str(directory.relative_to(ROOT) / 'verification.json')}))
    finally:
        for engine in engines:
            engine.dispose()
        # Never use a caller-supplied database name in DROP DATABASE.
        for name in reversed(created):
            if not name.startswith('portfolio_restore_') or not name.endswith(suffix):
                raise RuntimeError('Refusing unexpected database cleanup')
            with admin.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
                c.exec_driver_sql('DROP DATABASE ' + c.dialect.identifier_preparer.quote(name))
        admin.dispose()


if __name__ == '__main__':
    main()
