"""Durable audit integration tests in a disposable PostgreSQL schema."""
from datetime import timedelta
import os
from pathlib import Path
import unittest
import uuid

from test_commerce_postgres import NOW


@unittest.skipUnless(os.environ.get("COMMERCE_TEST_DATABASE_URL"), "PostgreSQL integration is opt-in")
class InvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        from decisionops.commerce.seed import seed
        cls.schema = "test_investigations_" + uuid.uuid4().hex
        cls.admin = database_engine(os.environ["COMMERCE_TEST_DATABASE_URL"])
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{cls.schema}"')
        cls.addClassCleanup(cls.cleanup_schema)
        url = make_url(os.environ["COMMERCE_TEST_DATABASE_URL"]).update_query_dict(
            {"options": "-csearch_path=" + cls.schema})
        cls.engine = database_engine(url)
        cls.addClassCleanup(cls.engine.dispose)
        cls.config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with cls.engine.begin() as connection:
            cls.config.attributes["connection"] = connection
            command.upgrade(cls.config, "0001")
        seed(cls.engine, observed_at=NOW)
        with cls.engine.begin() as connection:
            before = connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all()
            cls.config.attributes["connection"] = connection
            command.upgrade(cls.config, "head")
            assert connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all() == before

    @classmethod
    def cleanup_schema(cls):
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{cls.schema}" CASCADE')
        cls.admin.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.addCleanup(self.connection.close)
        self.addCleanup(self.transaction.rollback)

    def investigate(self, order="ORD-1042", shipment="SHIP-1042", items=None):
        from decisionops.commerce.investigations import investigate
        from decisionops.commerce.read_tools import AssessmentRequest
        return investigate(self.connection, AssessmentRequest(order, shipment, items or {"shirt-blue-M": 1}), NOW)

    def test_eligible_snapshot_and_proposal_are_persisted_without_business_writes(self):
        from decisionops.commerce.investigations import inspect_investigation, recheck
        before = self.connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all()
        result = self.investigate()
        saved = inspect_investigation(self.connection, result["investigation_id"])
        self.assertEqual(saved["assessment"]["decision"]["status"], "eligible_to_propose")
        self.assertEqual(saved["proposal"]["document"]["request"]["shipment_id"], "SHIP-1042")
        check = recheck(self.connection, result["proposal_id"], NOW)
        self.assertEqual(check["status"], "valid_for_review")
        self.assertFalse(check["execution_authorized"])
        self.assertEqual(self.connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all(), before)
        self.assertEqual(self.connection.exec_driver_sql("SELECT COUNT(*) FROM resolutions WHERE order_id='ORD-1042'").scalar_one(), 0)

    def test_blocked_unknown_partial_and_wrong_order_create_no_proposal(self):
        scenarios = [("ORD-STOCK", "SHIP-STOCK", {"shirt-red-M": 1}),
                     ("ORD-HISTORY", "SHIP-HISTORY", None),
                     ("ORD-PARTIAL", "SHIP-PARTIAL", {"shirt-blue-M": 2}),
                     ("ORD-1042", "SHIP-STOCK", None), ("MISSING", "MISSING", None)]
        for order, shipment, items in scenarios:
            with self.subTest(order=order, shipment=shipment):
                self.assertIsNone(self.investigate(order, shipment, items)["proposal_id"])

    def test_stock_drift_invalidates_even_when_stock_remains_sufficient(self):
        from decisionops.commerce.investigations import recheck, inspect_investigation
        result = self.investigate()
        self.connection.exec_driver_sql("UPDATE inventory SET on_hand=9 WHERE variant_id='shirt-blue-M'")
        check = recheck(self.connection, result["proposal_id"], NOW)
        self.assertEqual(check["current_decision"]["status"], "eligible_to_propose")
        self.assertEqual(check["status"], "requires_reinvestigation")
        self.assertIn("stock_available", check["changed_requirements"])
        saved = inspect_investigation(self.connection, result["investigation_id"])
        self.assertEqual(saved["assessment"]["read_tools"][5]["details"]["available_units"]["shirt-blue-M"], 9)

    def test_compensation_or_policy_change_invalidates(self):
        from decisionops.commerce.investigations import recheck
        for statement, requirement in [
            ("INSERT INTO resolutions VALUES ('new-refund','ORD-1042','shirt-blue-M',1,'refund')", "no_previous_compensation"),
            ("UPDATE orders SET policy_id='demo-policy-v2' WHERE id='ORD-1042'", "policy_permits")]:
            with self.connection.begin_nested() as nested:
                result = self.investigate()
                self.connection.exec_driver_sql(statement)
                check = recheck(self.connection, result["proposal_id"], NOW)
                self.assertEqual(check["status"], "requires_reinvestigation")
                self.assertIn(requirement, check["changed_requirements"])
                nested.rollback()

    def test_carrier_expiry_invalidates_unchanged_versions(self):
        from decisionops.commerce.investigations import recheck
        result = self.investigate()
        check = recheck(self.connection, result["proposal_id"], NOW + timedelta(days=2))
        self.assertEqual(check["changed_requirements"], [])
        self.assertEqual(check["status"], "requires_reinvestigation")
        self.assertIn("loss_confirmed", check["current_decision"]["unknowns"])

    def test_database_rejects_edit_or_delete_of_audit_rows(self):
        from sqlalchemy.exc import DBAPIError
        result = self.investigate()
        for table, identifier in (("commerce_investigations", result["investigation_id"]),
                                  ("commerce_proposals", result["proposal_id"])):
            for statement in (f"UPDATE {table} SET id='tampered' WHERE id=%s",
                              f"DELETE FROM {table} WHERE id=%s"):
                with self.connection.begin_nested() as nested:
                    with self.assertRaises(DBAPIError):
                        self.connection.exec_driver_sql(statement, (identifier,))
                    nested.rollback()

    def test_proposal_insert_failure_rolls_back_investigation(self):
        from sqlalchemy import event
        from sqlalchemy.exc import SQLAlchemyError
        before = self.connection.exec_driver_sql("SELECT COUNT(*) FROM commerce_investigations").scalar_one()
        def fail_proposal(connection, cursor, statement, parameters, context, executemany):
            if "INSERT INTO commerce_proposals" in statement:
                raise SQLAlchemyError("simulated proposal persistence failure")
        event.listen(self.connection, "before_cursor_execute", fail_proposal)
        try:
            with self.connection.begin_nested() as nested:
                with self.assertRaises(SQLAlchemyError):
                    self.investigate()
                nested.rollback()
        finally:
            event.remove(self.connection, "before_cursor_execute", fail_proposal)
        self.assertEqual(self.connection.exec_driver_sql("SELECT COUNT(*) FROM commerce_investigations").scalar_one(), before)

    def test_missing_or_tampered_proposal_is_not_accepted(self):
        import sqlalchemy as sa
        from decisionops.commerce.investigations import recheck
        from decisionops.commerce.schema import proposals
        with self.assertRaises(ValueError):
            recheck(self.connection, "missing", NOW)
        result = self.investigate()
        row = self.connection.execute(sa.select(proposals).where(proposals.c.id == result["proposal_id"])).mappings().one()
        fake = dict(row)
        fake.update(id="fake", investigation_id=self.investigate("ORD-STOCK", "SHIP-STOCK", {"shirt-red-M": 1})["investigation_id"], content_hash="0" * 64)
        self.connection.execute(sa.insert(proposals).values(**fake))
        with self.assertRaisesRegex(ValueError, "hash"):
            recheck(self.connection, "fake", NOW)

    def cli(self, *arguments):
        import json
        import subprocess
        import sys
        env = dict(os.environ, COMMERCE_DATABASE_URL=self.engine.url.render_as_string(hide_password=False))
        result = subprocess.run([sys.executable, "-B", "-m", "decisionops.commerce.case_demo", *arguments],
                                env=env, text=True, capture_output=True, timeout=15)
        return result, json.loads(result.stdout) if result.stdout else None

    def test_cli_persists_then_inspects_across_processes(self):
        result, saved = self.cli("investigate", "--order", "ORD-HISTORY", "--shipment", "SHIP-HISTORY",
                                 "--item", "shirt-blue-M:1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(saved["decision"]["status"], "needs_review")
        self.assertIsNone(saved["proposal_id"])
        result, inspected = self.cli("inspect", "--investigation", saved["investigation_id"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(inspected["assessment"]["facts"]["no_previous_compensation"])

    def test_cli_bad_item_missing_id_and_unavailable_database(self):
        result, _ = self.cli("investigate", "--order", "ORD-1042", "--shipment", "SHIP-1042", "--item", "bad:0")
        self.assertEqual(result.returncode, 2)
        result, _ = self.cli("inspect", "--investigation", "does-not-exist")
        self.assertEqual(result.returncode, 2)
        import json
        from contextlib import redirect_stderr, redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from sqlalchemy.exc import OperationalError
        from decisionops.commerce.case_demo import main
        stderr, stdout = StringIO(), StringIO()
        with patch("decisionops.commerce.case_demo.database_engine", side_effect=OperationalError("secret", {}, Exception("secret"))):
            with redirect_stderr(stderr), redirect_stdout(stdout):
                code = main(["inspect", "--investigation", "missing"])
        self.assertEqual(code, 3)
        self.assertNotIn("secret", stderr.getvalue())
        self.assertEqual(json.loads(stderr.getvalue())["event"], "database_error")

    def test_cli_check_exit_code_and_read_only_transaction(self):
        from decisionops.commerce.investigations import investigate
        from decisionops.commerce.read_tools import AssessmentRequest
        with self.engine.begin() as connection:
            saved = investigate(connection, AssessmentRequest("ORD-1042", "SHIP-1042", {"shirt-blue-M": 1}), NOW)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE shipments SET carrier_observed_at=CURRENT_TIMESTAMP - INTERVAL '2 days' WHERE id='SHIP-1042'")
        try:
            result, check = self.cli("check", "--proposal", saved["proposal_id"])
        finally:
            with self.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE shipments SET carrier_observed_at=%s WHERE id='SHIP-1042'", (NOW,))
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(check["status"], "requires_reinvestigation")
        self.assertFalse(check["execution_authorized"])
        self.assertTrue(check["read_only"])

    def test_downgrade_and_reupgrade_preserve_original_business_records(self):
        from alembic import command
        self.investigate()
        before = self.connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all()
        self.config.attributes["connection"] = self.connection
        command.downgrade(self.config, "0001")
        self.assertIsNone(self.connection.exec_driver_sql("SELECT to_regclass('commerce_proposals')").scalar_one())
        self.assertEqual(self.connection.exec_driver_sql("SELECT * FROM inventory ORDER BY variant_id").all(), before)
        command.upgrade(self.config, "head")
        self.assertEqual(self.connection.exec_driver_sql("SELECT COUNT(*) FROM commerce_investigations").scalar_one(), 0)
