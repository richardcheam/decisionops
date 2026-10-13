"""Opt-in real PostgreSQL tests; isolated schema, no demo-data reset."""

from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)


@unittest.skipUnless(os.environ.get("COMMERCE_TEST_DATABASE_URL"), "PostgreSQL integration is opt-in")
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        from sqlalchemy.engine import make_url
        from decisionops.commerce.database import database_engine
        from decisionops.commerce.seed import seed

        cls.schema = "test_commerce_" + uuid.uuid4().hex
        cls.admin = database_engine(os.environ["COMMERCE_TEST_DATABASE_URL"])
        with cls.admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{cls.schema}"')
        cls.addClassCleanup(cls.cleanup_schema)
        url = make_url(os.environ["COMMERCE_TEST_DATABASE_URL"]).update_query_dict(
            {"options": "-csearch_path=" + cls.schema})
        cls.engine = database_engine(url)
        cls.addClassCleanup(cls.engine.dispose)
        cls.config = Config(str(ROOT / "alembic.ini"))
        with cls.engine.begin() as connection:
            cls.config.attributes["connection"] = connection
            command.upgrade(cls.config, "head")
        seed(cls.engine, observed_at=NOW)

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

    def result(self, order="ORD-1042", shipment="SHIP-1042", items=None):
        from decisionops.commerce.read_tools import AssessmentRequest, read_assessment
        return read_assessment(self.connection, AssessmentRequest(
            order, shipment, items or {"shirt-blue-M": 1}), NOW)

    def test_eligible_records_produce_bound_evidence(self):
        result = self.result()
        self.assertEqual(result["decision"]["status"], "eligible_to_propose")
        detail = result["evidence"]["loss_confirmed"][0]["details"]
        self.assertEqual(detail["shipment_id"], "SHIP-1042")
        self.assertEqual(result["request"]["items"], {"shirt-blue-M": 1})
        self.assertEqual(result["policy_id"], "demo-policy-v1")

    def test_wrong_order_shipment_is_not_loss_evidence(self):
        result = self.result(shipment="SHIP-STOCK")
        self.assertEqual(result["decision"]["status"], "needs_review")
        self.assertIsNone(result["facts"]["loss_confirmed"])
        self.assertIn("shipment_order_mismatch", result["scope_reasons"])

    def test_insufficient_stock_is_a_false_condition(self):
        result = self.result("ORD-STOCK", "SHIP-STOCK", {"shirt-red-M": 1})
        self.assertEqual(result["decision"]["status"], "ineligible")
        self.assertIn("stock_available", result["decision"]["blockers"])

    def test_existing_compensation_blocks_duplicate(self):
        result = self.result("ORD-COMP", "SHIP-COMP")
        self.assertEqual(result["decision"]["status"], "ineligible")
        self.assertIn("no_previous_compensation", result["decision"]["blockers"])

    def test_partial_shipments_and_compensation_require_review(self):
        for order, shipment in (("ORD-PARTIAL", "SHIP-PARTIAL"),
                                ("ORD-PARTCOMP", "SHIP-PARTCOMP")):
            with self.subTest(order=order):
                result = self.result(order, shipment, {"shirt-blue-M": 2})
                self.assertEqual(result["decision"]["status"], "needs_review")
                self.assertEqual(result["scope_issue"], "unsupported_case")

    def test_incomplete_history_never_means_no_compensation(self):
        result = self.result("ORD-HISTORY", "SHIP-HISTORY")
        self.assertIsNone(result["facts"]["no_previous_compensation"])
        self.assertEqual(result["decision"]["status"], "needs_review")

    def test_wrong_variant_and_excess_quantity_are_false(self):
        for items in ({"shirt-red-M": 1}, {"shirt-blue-M": 2}):
            with self.subTest(items=items):
                result = self.result(items=items)
                self.assertFalse(result["facts"]["quantities_valid"])

    def test_subset_request_requires_review(self):
        result = self.result("ORD-PARTCOMP", "SHIP-PARTCOMP", {"shirt-blue-M": 1})
        self.assertIn("partial_request", result["scope_reasons"])

    def test_stale_tracking_and_missing_inventory_are_unknown(self):
        import sqlalchemy as sa
        from decisionops.commerce.schema import shipments, inventory
        self.connection.execute(sa.update(shipments).where(shipments.c.id == "SHIP-1042").values(
            carrier_observed_at=datetime(2026, 10, 9, tzinfo=timezone.utc)))
        self.connection.execute(sa.delete(inventory).where(inventory.c.variant_id == "shirt-blue-M"))
        result = self.result()
        self.assertIsNone(result["facts"]["loss_confirmed"])
        self.assertIsNone(result["facts"]["stock_available"])

    def test_database_rejects_cross_order_shipment_line(self):
        import sqlalchemy as sa
        from sqlalchemy.exc import IntegrityError
        from decisionops.commerce.schema import shipment_lines
        with self.assertRaises(IntegrityError):
            self.connection.execute(sa.insert(shipment_lines).values(
                shipment_id="SHIP-STOCK", order_id="ORD-1042",
                variant_id="shirt-blue-M", quantity=1))

    def test_read_only_assessment_cannot_write(self):
        import sqlalchemy as sa
        from decisionops.commerce.store_demo import database_assessment
        from decisionops.commerce.schema import inventory, resolutions
        before_stock = self.connection.execute(sa.select(inventory)).all()
        before_resolutions = self.connection.execute(sa.select(resolutions)).all()
        result = database_assessment(self.engine, "ORD-1042", "SHIP-1042", {"shirt-blue-M": 1})
        self.assertTrue(result["read_only"])
        self.assertEqual(self.connection.execute(sa.select(inventory)).all(), before_stock)
        self.assertEqual(self.connection.execute(sa.select(resolutions)).all(), before_resolutions)

    def test_failed_history_lookup_discards_partial_snapshot(self):
        from sqlalchemy import event
        from sqlalchemy.exc import SQLAlchemyError
        from decisionops.commerce.store_demo import database_assessment

        def fail_history(connection, cursor, statement, parameters, context, executemany):
            if "FROM resolutions" in statement:
                raise SQLAlchemyError("simulated history lookup failure")

        event.listen(self.engine, "before_cursor_execute", fail_history)
        try:
            result = database_assessment(self.engine, "ORD-1042", "SHIP-1042", {"shirt-blue-M": 1})
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_history)
        self.assertEqual(result["database_status"], "unavailable")
        self.assertIsNone(result["facts"]["no_previous_compensation"])
        self.assertEqual(set(result["decision"]["unknowns"]), {
            "paid", "shipped", "loss_confirmed", "quantities_valid",
            "no_previous_compensation", "stock_available", "policy_permits"})

    def test_postgresql_rejects_an_accidental_write_in_assessment(self):
        import sqlalchemy as sa
        from unittest.mock import patch
        from decisionops.commerce.schema import inventory
        from decisionops.commerce.store_demo import database_assessment

        def accidental_write(connection, request, now):
            connection.execute(sa.update(inventory).where(
                inventory.c.variant_id == "shirt-blue-M").values(reserved=2))

        with patch("decisionops.commerce.store_demo.read_assessment", accidental_write):
            result = database_assessment(self.engine, "ORD-1042", "SHIP-1042", {"shirt-blue-M": 1})
        self.assertEqual(result["database_status"], "unavailable")
        # A new transaction observes committed state, not an old repeatable-read snapshot.
        with self.engine.connect() as connection:
            reserved = connection.execute(sa.select(inventory.c.reserved).where(
                inventory.c.variant_id == "shirt-blue-M")).scalar_one()
        self.assertEqual(reserved, 1)

    def test_seed_is_idempotent_without_overwriting_records(self):
        from decisionops.commerce.seed import seed
        self.assertEqual(seed(self.engine), "already_seeded")

    def test_migration_matches_metadata(self):
        from alembic import command
        self.config.attributes["connection"] = self.connection
        command.check(self.config)


if __name__ == "__main__":
    unittest.main()
