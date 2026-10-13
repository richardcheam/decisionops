"""Local fictional-store workflow CLI. Explicit review before atomic replacement."""
import argparse
import json
import sys

from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from .investigations import investigate, inspect_investigation, recheck
from .read_tools import AssessmentRequest, canonical
from .cases import open_case, investigate_case, show_case, review_case, escalate_case
from .execution import execute, reconcile


def run_command(engine, args):
    # Parse before connecting: malformed input is not a database outage.
    request = None
    if args.command in ("investigate", "open"):
        items = {}
        for item in args.item:
            variant, quantity = item.rsplit(":", 1)
            if variant in items:
                raise ValueError("Duplicate requested variant")
            items[variant] = int(quantity)
        request = AssessmentRequest(args.order, args.shipment, items)
    readonly = args.command in ("inspect", "check", "show-case", "reconcile")
    case_mutation = args.command in ("open", "investigate-case", "review", "escalate", "execute")
    with engine.connect() as connection:
        if case_mutation:
            connection = connection.execution_options(isolation_level="READ COMMITTED")
        with connection.begin():
            if readonly:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '5s'")
            now = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
            if args.command == "investigate":
                result = investigate(connection, request, now)
            elif args.command == "inspect":
                result = inspect_investigation(connection, args.investigation)
            elif args.command == "check":
                result = recheck(connection, args.proposal, now)
            elif args.command == "open":
                result = open_case(connection, request)
            elif args.command == "investigate-case":
                result = investigate_case(connection, args.case)
            elif args.command == "show-case":
                result = show_case(connection, args.case)
            elif args.command == "review":
                result = review_case(connection, args.case, args.generation, args.proposal, args.content_hash, args.decision)
            elif args.command == "escalate":
                result = escalate_case(connection, args.case, args.reason)
            elif args.command == "execute":
                result = execute(connection, args.case, args.operation)
            else:
                result = reconcile(connection, args.operation)
            result.update(read_only=readonly, business_records_read_only=args.command != "execute",
                          database_status="available", schema_version=1,
                          kind="commerce_" + args.command)
    # Return only after commit has succeeded. No success output on commit failure.
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("investigate", help="Save an assessment and optional proposal")
    create.add_argument("--order", required=True)
    create.add_argument("--shipment", required=True)
    create.add_argument("--item", action="append", required=True, help="Exact variant ID:quantity")
    inspect = commands.add_parser("inspect", help="Read the original saved investigation")
    inspect.add_argument("--investigation", required=True)
    check = commands.add_parser("check", help="Check a proposal against current evidence")
    check.add_argument("--proposal", required=True)
    opened = commands.add_parser("open", help="Open a local fictional-store case")
    opened.add_argument("--order", required=True)
    opened.add_argument("--shipment", required=True)
    opened.add_argument("--item", action="append", required=True)
    for name in ("investigate-case", "show-case"):
        command = commands.add_parser(name)
        command.add_argument("--case", required=True)
    review = commands.add_parser("review", help="Explicit local operator approval/rejection of exact contents")
    review.add_argument("--case", required=True)
    review.add_argument("--generation", type=int, required=True)
    review.add_argument("--proposal", required=True)
    review.add_argument("--hash", dest="content_hash", required=True)
    review.add_argument("--decision", choices=("approve", "reject"), required=True)
    escalation = commands.add_parser("escalate")
    escalation.add_argument("--case", required=True)
    escalation.add_argument("--reason", required=True)
    execution = commands.add_parser("execute", help="Revalidate and atomically record an approved demo replacement")
    execution.add_argument("--case", required=True)
    execution.add_argument("--operation", required=True)
    recovery = commands.add_parser("reconcile", help="Read committed ledger and verify business records")
    recovery.add_argument("--operation", required=True)
    args = parser.parse_args(argv)
    engine = None
    try:
        engine = database_engine()
        result = run_command(engine, args)
        print(json.dumps(json.loads(canonical(result)), indent=2))
        return 4 if result.get("status") in ("requires_reinvestigation", "inconsistent", "not_found") else 0
    except ValueError as error:
        print(json.dumps({"event": "input_error", "error": str(error)}), file=sys.stderr)
        return 2
    except SQLAlchemyError as error:
        event = {"event": "database_error", "error_kind": type(error).__name__,
                 "message": "Check readiness, database URL and migrations"}
        if args.command in ("investigate", "open", "investigate-case", "review", "escalate", "execute"):
            event.update(outcome="not_confirmed",
                         guidance="Inspect recent investigations before repeating; a commit response may have been lost")
        if args.command == "execute":
            event.update(operation_id=args.operation, guidance="Reconcile this operation ID before retrying; commit may have succeeded")
        print(json.dumps(event), file=sys.stderr)
        return 3
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
