"""Durable local rules worker; no inference/provider calls or hosted trace export."""
import argparse
import json
import signal
import sys
from threading import Event

from psycopg import Error as PsycopgError
from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from . import jobs
from .read_tools import canonical
from .workflow import setup_checkpoints, run_graph, resume_graph, inspect_graph


def claim_one(engine,lease_seconds=30):
    with engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
        connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        return jobs.claim(connection,lease_seconds)


def work_once(engine,lease_seconds=30):
    owned=claim_one(engine,lease_seconds)
    if owned is None:
        return {'event':'idle'}
    try:
        result=run_graph(engine,owned['id'],owned['token'])
        return {'event':'job_result','job_id':owned['id'],'case_id':owned['case_id'],'phase':result['phase']}
    except jobs.LeaseLost:
        return {'event':'lease_lost','job_id':owned['id'],'recover':'Wait for the active lease owner or reclaim after expiry'}
    except Exception as error:
        # A graph checkpoint may fail after domain commit: preserve completed outcome.
        with engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
            current=jobs.get_job(connection,owned['id'])
            if current['status']!='completed':
                jobs.fail(connection,owned['id'],owned['token'],type(error).__name__)
        return {'event':'checkpoint_incomplete' if current['status']=='completed' else 'job_failed',
                'job_id':owned['id'],'error_kind':type(error).__name__,
                'recover':'Replay saved completed outcome, or inspect failure and enqueue a new job'}


def render(result):
    print(canonical(result),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('setup')
    queue=commands.add_parser('enqueue')
    queue.add_argument('--case',required=True)
    queue.add_argument('--action',choices=('investigate','execute'),required=True)
    queue.add_argument('--operation')
    for name in ('show','resume','replay'):
        command=commands.add_parser(name)
        command.add_argument('--job',required=True)
    once=commands.add_parser('once')
    once.add_argument('--lease-seconds',type=int,default=30)
    run=commands.add_parser('run')
    run.add_argument('--lease-seconds',type=int,default=30)
    run.add_argument('--poll-seconds',type=float,default=1)
    args=parser.parse_args(argv)
    engine=None
    try:
        engine=database_engine()
        if args.command=='setup':
            render({'event':'checkpoints_ready','schema':setup_checkpoints(engine)})
        elif args.command=='enqueue':
            with engine.connect().execution_options(isolation_level='READ COMMITTED') as connection,connection.begin():
                connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                result=jobs.enqueue(connection,args.case,args.action,args.operation)
            render(result)
        elif args.command=='show':
            with engine.connect() as connection:
                job=jobs.get_job(connection,args.job)
            render({'job':job,'graph':inspect_graph(engine,args.job)})
        elif args.command=='resume':
            render(resume_graph(engine,args.job))
        elif args.command=='replay':
            with engine.connect() as connection:
                job=jobs.get_job(connection,args.job)
            if job['status']!='completed':
                raise ValueError('Only completed job outcomes may be replayed; queued/expired work must be claimed')
            render(run_graph(engine,args.job,job['token']))
        elif args.command=='once':
            result=work_once(engine,args.lease_seconds)
            render(result)
            return 3 if result['event'] in ('job_failed','checkpoint_incomplete','lease_lost') else 0
        else:
            if not 0.25<=args.poll_seconds<=30 or not 1<=args.lease_seconds<=3600:
                raise ValueError('Poll seconds 0.25-30 and lease seconds 1-3600 are required')
            stopped=Event()
            signal.signal(signal.SIGINT,lambda *_:stopped.set())
            signal.signal(signal.SIGTERM,lambda *_:stopped.set())
            render({'event':'worker_started','lease_seconds':args.lease_seconds})
            while not stopped.is_set():
                try:
                    result=work_once(engine,args.lease_seconds)
                    if result['event']!='idle':
                        render(result)
                except (SQLAlchemyError,PsycopgError):
                    render({'event':'database_unavailable','recover':'Check readiness; worker will retry after polling delay'})
                stopped.wait(args.poll_seconds)
            render({'event':'worker_stopped'})
        return 0
    except ValueError as error:
        print(json.dumps({'event':'input_error','error':str(error)}),file=sys.stderr)
        return 2
    except (SQLAlchemyError,PsycopgError) as error:
        print(json.dumps({'event':'database_error','error_kind':type(error).__name__,
                          'message':'Check database readiness, business migration and worker setup'}),file=sys.stderr)
        return 3
    finally:
        if engine is not None:
            engine.dispose()


if __name__=='__main__':
    raise SystemExit(main())
