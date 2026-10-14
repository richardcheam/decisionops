"""Explicit opt-in local model-free adaptive CLI. Does not migrate or seed."""
import argparse
from contextlib import contextmanager
import json
import sys

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from . import adaptive_investigations as service
from .adaptive_evidence import TOOLS,canonical
from .database import database_engine


@contextmanager
def injected_failure(engine,tool):
    """Operator-only fault injection on named isolated test/demo databases."""
    if not tool:
        yield;return
    if not (engine.url.database or '').endswith(('_test','_demo')) or engine.url.port==55432:
        raise ValueError('Fault injection requires an isolated *_test or *_demo database, not port 55432')
    targets={'order_manifest':'orders','replacement_policy':'policy_versions','payment':'payments',
             'fulfilment':'shipments','carrier_loss':'shipments','compensation_history':'resolutions','inventory':'inventory'}
    def fail(connection,cursor,statement,*args):
        # Only business statements inside READ ONLY tool transactions. Audit writes
        # and inspection must remain available to record the explicit failure.
        if 'FROM '+targets[tool] in statement and connection.info.get('adaptive_tool')==tool:
            connection.exec_driver_sql('SELECT 1/0')
    event.listen(engine,'before_cursor_execute',fail)
    try:yield
    finally:event.remove(engine,'before_cursor_execute',fail)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    start=commands.add_parser('start');start.add_argument('--case',required=True)
    start.add_argument('--report',required=True)
    start.add_argument('--policy',default='fixed',choices=('fixed','cue','fake-override','fake-invalid','fake-unavailable','fake-refuse'))
    for name in ('inspect','run','advance','recover'):
        sub=commands.add_parser(name);sub.add_argument('--run',required=True)
        if name in ('advance','recover'):sub.add_argument('--context',required=True,type=int)
        if name=='advance':sub.add_argument('--action',required=True,help='Strict JSON kind/tool/reason object')
        if name=='run':sub.add_argument('--inject-tool-failure',choices=tuple(TOOLS))
    args=parser.parse_args(argv);engine=None
    try:
        engine=database_engine()
        if args.command=='start':result=service.start(engine,args.case,args.report,policy=args.policy)
        elif args.command=='inspect':result=service.inspect(engine,args.run)
        elif args.command=='advance':result=service.advance(engine,args.run,json.loads(args.action),expected_context=args.context)
        elif args.command=='recover':result=service.recover(engine,args.run,expected_context=args.context)
        else:
            with injected_failure(engine,args.inject_tool_failure):result=service.drive(engine,args.run)
        print(json.dumps(json.loads(canonical(result)),indent=2))
        return 4 if result['state']=='stale' else 0
    except ValueError as error:
        print(json.dumps({'event':'adaptive_input_error','error':str(error)}),file=sys.stderr);return 2
    except SQLAlchemyError:
        print(json.dumps({'event':'adaptive_database_error','message':'Inspect the isolated database; recover pending read after availability returns'}),file=sys.stderr);return 3
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
