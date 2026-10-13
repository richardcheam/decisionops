"""Real PostgreSQL tests of approved fictional replacement transactions."""
from datetime import timedelta
import os
from pathlib import Path
import unittest
import uuid

from test_commerce_postgres import NOW


@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'PostgreSQL integration is opt-in')
class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        from decisionops.commerce.seed import seed
        cls.admin = database_engine(os.environ['COMMERCE_TEST_DATABASE_URL'])
        cls.schema = 'test_execution_' + uuid.uuid4().hex
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{cls.schema}"')
        cls.addClassCleanup(cls.cleanup_schema)
        cls.engine = database_engine(make_url(os.environ['COMMERCE_TEST_DATABASE_URL']).update_query_dict({'options': '-csearch_path=' + cls.schema}))
        cls.addClassCleanup(cls.engine.dispose)
        cls.config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with cls.engine.begin() as connection:
            cls.config.attributes['connection'] = connection
            command.upgrade(cls.config, 'head')
        seed(cls.engine, observed_at=NOW)

    @classmethod
    def cleanup_schema(cls):
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{cls.schema}" CASCADE')
        cls.admin.dispose()

    def setUp(self):
        self.connection = self.engine.connect().execution_options(isolation_level='READ COMMITTED')
        self.transaction = self.connection.begin()
        self.addCleanup(self.connection.close)
        self.addCleanup(self.transaction.rollback)

    def ready(self, approve=True):
        from decisionops.commerce.cases import open_case, investigate_case, review_case
        from decisionops.commerce.read_tools import AssessmentRequest
        case = open_case(self.connection, AssessmentRequest('ORD-1042', 'SHIP-1042', {'shirt-blue-M': 1}), NOW)
        case = investigate_case(self.connection, case['id'], NOW)
        if approve:
            case = review_case(self.connection, case['id'], case['generation'], case['proposal']['id'],
                               case['proposal']['content_hash'], 'approve', NOW)
        return case

    def test_approval_execution_and_verified_reconciliation(self):
        from decisionops.commerce.execution import execute, reconcile
        case = self.ready()
        self.assertEqual(case['status'], 'approved')
        operation = case['approval']['operation_id']
        result = execute(self.connection, case['id'], operation, NOW)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(self.connection.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(), 2)
        self.assertEqual(self.connection.exec_driver_sql("SELECT COUNT(*) FROM resolutions WHERE order_id='ORD-1042'").scalar_one(), 1)
        self.assertEqual(reconcile(self.connection, operation)['status'], 'verified')

    def test_unapproved_and_wrong_operation_cannot_execute(self):
        from decisionops.commerce.execution import execute
        case = self.ready(approve=False)
        with self.assertRaises(ValueError):
            execute(self.connection, case['id'], 'OP-arbitrary', NOW)
        case = self.ready()
        with self.assertRaises(ValueError):
            execute(self.connection, case['id'], 'OP-arbitrary', NOW)
        self.assertEqual(self.connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 0)

    def test_duplicate_review_and_execution_are_idempotent(self):
        from decisionops.commerce.cases import review_case
        from decisionops.commerce.execution import execute
        case = self.ready()
        again = review_case(self.connection, case['id'], case['generation'], case['proposal']['id'],
                            case['proposal']['content_hash'], 'approve', NOW)
        self.assertEqual(again['approval']['id'], case['approval']['id'])
        operation = case['approval']['operation_id']
        execute(self.connection, case['id'], operation, NOW)
        self.assertEqual(execute(self.connection, case['id'], operation, NOW)['status'], 'verified')
        self.assertEqual(self.connection.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(), 2)
        self.assertEqual(self.connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 1)

    def test_wrong_proposal_hash_generation_and_case_are_rejected(self):
        from decisionops.commerce.cases import review_case
        first, second = self.ready(False), self.ready(False)
        for generation, proposal, digest in [(0, first['proposal']['id'], first['proposal']['content_hash']),
                                             (first['generation'], second['proposal']['id'], first['proposal']['content_hash']),
                                             (first['generation'], first['proposal']['id'], '0'*64)]:
            with self.assertRaises(ValueError):
                review_case(self.connection, first['id'], generation, proposal, digest, 'approve', NOW)

    def test_stale_approval_is_permanently_invalidated(self):
        from decisionops.commerce.execution import execute
        from decisionops.commerce.cases import show_case
        case = self.ready()
        operation = case['approval']['operation_id']
        self.connection.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
        result = execute(self.connection, case['id'], operation, NOW)
        self.assertEqual(result['status'], 'requires_reinvestigation')
        self.assertIsNone(show_case(self.connection, case['id'])['approval'])
        self.connection.exec_driver_sql("UPDATE inventory SET on_hand=10 WHERE variant_id='shirt-blue-M'")
        with self.assertRaises(ValueError):
            execute(self.connection, case['id'], operation, NOW)
        self.assertEqual(self.connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 0)

    def test_carrier_expiry_and_new_compensation_block_execution(self):
        from decisionops.commerce.execution import execute
        for compensation in (False, True):
            with self.connection.begin_nested() as nested:
                case = self.ready()
                if compensation:
                    self.connection.exec_driver_sql("INSERT INTO resolutions (id,order_id,variant_id,quantity,kind) VALUES ('new-refund','ORD-1042','shirt-blue-M',1,'refund')")
                result = execute(self.connection, case['id'], case['approval']['operation_id'], NOW if compensation else NOW + timedelta(days=2))
                self.assertEqual(result['status'], 'requires_reinvestigation')
                nested.rollback()

    def test_reinvestigation_reject_and_escalate_revoke_execution(self):
        from decisionops.commerce.cases import investigate_case, review_case, escalate_case
        from decisionops.commerce.execution import execute
        case = self.ready()
        old_operation = case['approval']['operation_id']
        fresh = investigate_case(self.connection, case['id'], NOW)
        self.assertEqual(fresh['generation'], 2)
        with self.assertRaises(ValueError):
            execute(self.connection, case['id'], old_operation, NOW)
        rejected = review_case(self.connection, fresh['id'], fresh['generation'], fresh['proposal']['id'], fresh['proposal']['content_hash'], 'reject', NOW)
        self.assertEqual(rejected['status'], 'rejected')
        other = self.ready()
        self.assertEqual(escalate_case(self.connection, other['id'], 'Carrier needs staff review', NOW)['status'], 'escalated')
        with self.assertRaises(ValueError):
            execute(self.connection, other['id'], other['approval']['operation_id'], NOW)

    def test_mid_transaction_failure_rolls_back_every_write(self):
        from sqlalchemy import event
        from sqlalchemy.exc import SQLAlchemyError
        from decisionops.commerce.execution import execute
        case = self.ready()
        operation = case['approval']['operation_id']
        def fail(connection, cursor, statement, parameters, context, executemany):
            if 'INSERT INTO commerce_reservations' in statement:
                raise SQLAlchemyError('simulated failure after stock update')
        event.listen(self.connection, 'before_cursor_execute', fail)
        try:
            with self.connection.begin_nested() as nested:
                with self.assertRaises(SQLAlchemyError):
                    execute(self.connection, case['id'], operation, NOW)
                nested.rollback()
        finally:
            event.remove(self.connection, 'before_cursor_execute', fail)
        self.assertEqual(self.connection.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(), 1)
        self.assertEqual(self.connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 0)
        self.assertEqual(self.connection.exec_driver_sql("SELECT COUNT(*) FROM resolutions WHERE order_id='ORD-1042'").scalar_one(), 0)
        self.assertEqual(execute(self.connection, case['id'], operation, NOW)['status'], 'verified')

    def test_database_guards_compensation_and_policy_versions(self):
        from sqlalchemy.exc import DBAPIError
        with self.connection.begin_nested() as nested:
            self.connection.exec_driver_sql("INSERT INTO resolutions (id,order_id,variant_id,quantity,kind) VALUES ('refund-one','ORD-1042','shirt-blue-M',1,'refund')")
            with self.assertRaises(DBAPIError):
                self.connection.exec_driver_sql("INSERT INTO resolutions (id,order_id,variant_id,quantity,kind) VALUES ('refund-two','ORD-1042','shirt-blue-M',1,'refund')")
            nested.rollback()
        with self.connection.begin_nested() as nested:
            with self.assertRaises(DBAPIError):
                self.connection.exec_driver_sql("UPDATE policy_versions SET max_units=9 WHERE id='demo-policy-v1'")
            nested.rollback()

    def test_reconcile_missing_and_inconsistent_records_never_claims_success(self):
        from decisionops.commerce.execution import reconcile
        self.assertEqual(reconcile(self.connection, 'OP-missing')['status'], 'not_found')
        # Inject a database read failure; it must propagate, not become not_found.
        from sqlalchemy import event
        from sqlalchemy.exc import SQLAlchemyError
        def fail(connection, cursor, statement, parameters, context, executemany):
            if 'FROM commerce_operations' in statement:
                raise SQLAlchemyError('ledger unavailable')
        event.listen(self.connection, 'before_cursor_execute', fail)
        try:
            with self.assertRaises(SQLAlchemyError):
                reconcile(self.connection, 'OP-missing')
        finally:
            event.remove(self.connection, 'before_cursor_execute', fail)

    def test_reconcile_detects_missing_reserved_stock(self):
        from decisionops.commerce.execution import execute, reconcile
        case = self.ready()
        operation = case['approval']['operation_id']
        execute(self.connection, case['id'], operation, NOW)
        self.connection.exec_driver_sql("UPDATE inventory SET reserved=0 WHERE variant_id='shirt-blue-M'")
        self.assertEqual(reconcile(self.connection, operation)['status'], 'inconsistent')

    def test_case_cli_open_investigate_show_escalate(self):
        import json
        import subprocess
        import sys
        env = dict(os.environ, COMMERCE_DATABASE_URL=self.engine.url.render_as_string(hide_password=False))
        def cli(*arguments):
            result = subprocess.run([sys.executable, '-B', '-m', 'decisionops.commerce.case_demo', *arguments], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        opened = cli('open', '--order', 'ORD-HISTORY', '--shipment', 'SHIP-HISTORY', '--item', 'shirt-blue-M:1')
        self.assertEqual(opened['status'], 'open')
        result = cli('investigate-case', '--case', opened['id'])
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['proposal'])
        shown = cli('show-case', '--case', opened['id'])
        self.assertEqual([event['kind'] for event in shown['events']], ['opened', 'investigated'])
        self.assertEqual(cli('escalate', '--case', opened['id'], '--reason', 'Retrieve compensation history')['status'], 'escalated')

@unittest.skipUnless(os.environ.get('COMMERCE_TEST_DATABASE_URL'), 'PostgreSQL integration is opt-in')
class ExecutionRaceTests(unittest.TestCase):
    def setUp(self):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        from decisionops.commerce.seed import seed
        self.schema = 'test_race_' + uuid.uuid4().hex
        self.admin = database_engine(os.environ['COMMERCE_TEST_DATABASE_URL'])
        with self.admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.addCleanup(self.cleanup_schema)
        self.engine = database_engine(make_url(os.environ['COMMERCE_TEST_DATABASE_URL']).update_query_dict({'options': '-csearch_path=' + self.schema}))
        self.addCleanup(self.engine.dispose)
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        with self.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        seed(self.engine, observed_at=NOW)

    def cleanup_schema(self):
        with self.admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.dispose()

    def ready(self, order='ORD-1042', shipment='SHIP-1042'):
        from decisionops.commerce.cases import open_case, investigate_case, review_case
        from decisionops.commerce.read_tools import AssessmentRequest
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            case = open_case(connection, AssessmentRequest(order, shipment, {'shirt-blue-M': 1}), NOW)
            case = investigate_case(connection, case['id'], NOW)
            return review_case(connection, case['id'], case['generation'], case['proposal']['id'], case['proposal']['content_hash'], 'approve', NOW)

    def parallel(self, calls):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        gate = Barrier(len(calls))
        def run(call):
            with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
                connection.exec_driver_sql("SET LOCAL statement_timeout='8s'")
                gate.wait(timeout=5)
                return call(connection)
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            futures = [pool.submit(run, call) for call in calls]
            return [future.result(timeout=15) for future in futures]

    def test_concurrent_duplicate_execution_commits_once(self):
        from decisionops.commerce.execution import execute
        case = self.ready()
        call = lambda connection: execute(connection, case['id'], case['approval']['operation_id'], NOW)
        results = self.parallel([call, call])
        self.assertEqual([result['status'] for result in results], ['verified', 'verified'])
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 1)
            self.assertEqual(connection.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(), 2)

    def test_two_cases_for_same_order_do_not_duplicate_compensation(self):
        from decisionops.commerce.execution import execute
        cases = [self.ready(), self.ready()]
        results = self.parallel([lambda connection, case=case: execute(connection, case['id'], case['approval']['operation_id'], NOW) for case in cases])
        self.assertEqual(sorted(result['status'] for result in results), ['requires_reinvestigation', 'verified'])
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT COUNT(*) FROM resolutions WHERE order_id='ORD-1042'").scalar_one(), 1)

    def test_two_orders_contend_for_last_available_unit(self):
        from decisionops.commerce.execution import execute
        with self.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE inventory SET on_hand=2,reserved=1 WHERE variant_id='shirt-blue-M'")
            connection.exec_driver_sql("INSERT INTO orders (id,store_id,policy_id,currency,resolution_history_complete) SELECT 'ORD-RACE',store_id,policy_id,currency,true FROM orders WHERE id='ORD-1042'")
            connection.exec_driver_sql("INSERT INTO order_lines SELECT 'ORD-RACE',variant_id,quantity,unit_price_minor FROM order_lines WHERE order_id='ORD-1042'")
            connection.exec_driver_sql("INSERT INTO payments SELECT 'ORD-RACE',status,amount_minor,currency FROM payments WHERE order_id='ORD-1042'")
            connection.exec_driver_sql("INSERT INTO shipments SELECT 'SHIP-RACE','ORD-RACE',fulfilment_status,carrier_status,carrier_observed_at FROM shipments WHERE id='SHIP-1042'")
            connection.exec_driver_sql("INSERT INTO shipment_lines SELECT 'SHIP-RACE','ORD-RACE',variant_id,quantity FROM shipment_lines WHERE shipment_id='SHIP-1042'")
        cases = [self.ready(), self.ready('ORD-RACE', 'SHIP-RACE')]
        results = self.parallel([lambda connection, case=case: execute(connection, case['id'], case['approval']['operation_id'], NOW) for case in cases])
        self.assertEqual(sorted(result['status'] for result in results), ['requires_reinvestigation', 'verified'])
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 1)
            self.assertEqual(connection.exec_driver_sql("SELECT on_hand-reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(), 0)

    def test_direct_concurrent_refunds_cannot_overcompensate(self):
        from sqlalchemy.exc import DBAPIError
        def refund(connection, identifier):
            try:
                with connection.begin_nested():
                    connection.exec_driver_sql("INSERT INTO resolutions (id,order_id,variant_id,quantity,kind) VALUES (%s,'ORD-1042','shirt-blue-M',1,'refund')", (identifier,))
                return 'accepted'
            except DBAPIError:
                return 'blocked'
        results = self.parallel([lambda connection: refund(connection, 'refund-a'), lambda connection: refund(connection, 'refund-b')])
        self.assertEqual(sorted(results), ['accepted', 'blocked'])

    def test_lost_response_after_commit_reconciles_without_second_reservation(self):
        from decisionops.commerce.execution import execute, reconcile
        case = self.ready()
        operation = case['approval']['operation_id']
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            execute(connection, case['id'], operation, NOW)
        # The real transaction committed; simulate the caller losing its response.
        with self.engine.connect() as connection:
            self.assertEqual(reconcile(connection, operation)['status'], 'verified')
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            self.assertEqual(execute(connection, case['id'], operation, NOW)['status'], 'verified')
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql('SELECT COUNT(*) FROM commerce_operations').scalar_one(), 1)
            self.assertEqual(connection.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one(), 2)

    def test_retry_reconciliation_uses_one_stock_snapshot_during_other_commit(self):
        import sqlalchemy as sa
        from decisionops.commerce.execution import execute
        with self.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE inventory SET reserved=0 WHERE variant_id='shirt-blue-M'")
            connection.exec_driver_sql("UPDATE shipments SET carrier_status='lost' WHERE id='SHIP-TRACKING'")
        first = self.ready()
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            execute(connection, first['id'], first['approval']['operation_id'], NOW)
        second = self.ready('ORD-TRACKING', 'SHIP-TRACKING')
        committed = []
        def commit_other(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith('SELECT') and 'FROM inventory' in statement and not committed:
                committed.append(True)
                with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as other, other.begin():
                    execute(other, second['id'], second['approval']['operation_id'], NOW)
        with self.engine.connect().execution_options(isolation_level='READ COMMITTED') as connection, connection.begin():
            sa.event.listen(connection, 'after_cursor_execute', commit_other)
            result = execute(connection, first['id'], first['approval']['operation_id'], NOW)
            self.assertEqual(result['status'], 'verified')
        self.assertTrue(committed, 'The second real transaction must commit between reconciliation reads')
