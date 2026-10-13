"""Read-only PostgreSQL assessment; fixture mode remains commerce.demo."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from .read_tools import AssessmentRequest, canonical, read_assessment, unavailable_assessment


def database_assessment(engine, order_id, shipment_id, items):
    request = AssessmentRequest(order_id, shipment_id, items)
    now = datetime.now(timezone.utc)
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '5s'")
                # Database-backed assessment always uses the actual database clock.
                now = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
                result = read_assessment(connection, request, now)
                readonly = connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
        result.update(read_only=readonly, database_status="available")
    except SQLAlchemyError as error:
        # No partial success survives a failed snapshot; history never becomes empty.
        result = unavailable_assessment(request, now, type(error).__name__)
        result.update(read_only=True, database_status="unavailable")
    result.update(schema_version=1, kind="commerce_database_assessment", as_of=now.isoformat())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", required=True)
    parser.add_argument("--shipment", required=True)
    parser.add_argument("--item", action="append", required=True, help="Exact variant ID:quantity")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    engine = None
    try:
        items = {}
        for item in args.item:
            variant, quantity = item.rsplit(":", 1)
            if variant in items:
                raise ValueError("Duplicate requested variant")
            items[variant] = int(quantity)
        AssessmentRequest(args.order, args.shipment, items)
        engine = database_engine()
        result = database_assessment(engine, args.order, args.shipment, items)
        rendered = json.dumps(json.loads(canonical(result)), indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
        print(rendered, end="")
        if result["database_status"] == "unavailable":
            print(json.dumps({"event": "database_unavailable", "message": "Check readiness, URL and migrations"}), file=sys.stderr)
            return 3
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"event": "input_error", "error": str(error)}), file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
