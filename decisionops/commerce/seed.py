"""Insert deterministic fictional scenarios once; never reset existing records."""

import json
import sys
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from . import schema as db

SEED_ID = "commerce-demo-v1"


def seed(engine, observed_at=None):
    with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection, connection.begin():
        # Serialize concurrent seed commands without changing business records.
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(10420001)")
        if connection.execute(sa.select(db.seed_versions).where(db.seed_versions.c.id == SEED_ID)).first():
            return "already_seeded"
        observed_at = observed_at or connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
        connection.execute(db.policies.insert(), [
            dict(id="demo-policy-v1", store_id="demo-store", version=1,
                 allow_confirmed_loss=True, max_units=10, carrier_max_age_seconds=86400),
            dict(id="demo-policy-v2", store_id="demo-store", version=2,
                 allow_confirmed_loss=False, max_units=10, carrier_max_age_seconds=86400),
        ])
        scenarios = (
            ("1042", "shirt-blue-M", 1), ("STOCK", "shirt-red-M", 1),
            ("COMP", "shirt-blue-M", 1), ("PARTIAL", "shirt-blue-M", 2),
            ("PARTCOMP", "shirt-blue-M", 2), ("HISTORY", "shirt-blue-M", 1),
            ("TRACKING", "shirt-blue-M", 1), ("POLICY", "shirt-blue-M", 1),
        )
        for suffix, variant, quantity in scenarios:
            order_id, shipment_id = "ORD-" + suffix, "SHIP-" + suffix
            connection.execute(db.orders.insert(), dict(
                id=order_id, store_id="demo-store",
                policy_id="demo-policy-v2" if suffix == "POLICY" else "demo-policy-v1",
                currency="USD", resolution_history_complete=suffix != "HISTORY"))
            connection.execute(db.order_lines.insert(), dict(
                order_id=order_id, variant_id=variant, quantity=quantity, unit_price_minor=2500))
            connection.execute(db.payments.insert(), dict(
                order_id=order_id, status="paid", amount_minor=2500 * quantity, currency="USD"))
            connection.execute(db.shipments.insert(), dict(
                id=shipment_id, order_id=order_id, fulfilment_status="shipped",
                carrier_status="in_transit" if suffix == "TRACKING" else "lost",
                carrier_observed_at=observed_at))
            connection.execute(db.shipment_lines.insert(), dict(
                shipment_id=shipment_id, order_id=order_id, variant_id=variant,
                quantity=1 if suffix == "PARTIAL" else quantity))
            if suffix in ("COMP", "PARTCOMP"):
                connection.execute(db.resolutions.insert(), dict(
                    id="RES-" + suffix, order_id=order_id,
                    variant_id=variant, quantity=1, kind="refund"))
        connection.execute(db.inventory.insert(), [
            dict(store_id="demo-store", variant_id="shirt-blue-M", on_hand=10, reserved=1),
            dict(store_id="demo-store", variant_id="shirt-red-M", on_hand=1, reserved=1),
        ])
        connection.execute(db.seed_versions.insert(), dict(id=SEED_ID))
    return "seeded"


def main():
    engine = None
    try:
        engine = database_engine()
        print(json.dumps({"event": seed(engine), "seed_version": SEED_ID}))
        return 0
    except (ValueError, SQLAlchemyError):
        print(json.dumps({"event": "seed_error", "message": "Check connection, migration and seed conflicts"}), file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
