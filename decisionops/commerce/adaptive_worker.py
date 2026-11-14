"""Explicit operator commands; ordinary worker/browser/API remain unchanged."""
import argparse
import json
import signal
import sys
from decimal import Decimal
from threading import Event
from .database import database_engine
from . import adaptive_jobs as jobs,adaptive_workflow as graph,adaptive_investigations as service
from .adaptive_runner import run_until_pause
from .jobs import LeaseLost
from .session_protocol import SessionFailure
from sqlalchemy.exc import SQLAlchemyError


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='command',required=True)
    subs.add_parser('setup')
    q=subs.add_parser('enqueue');q.add_argument('--case',required=True);q.add_argument('--report',required=True)
    q.add_argument('--policy',choices=('fixed','cue','fake-override','fake-invalid','fake-unavailable','fake-refuse'),default='fixed')
    q.add_argument('--session',choices=('fake','laya','gliclass'));q.add_argument('--revision')
    q.add_argument('--fake-session-behavior',default='normal');q.add_argument('--preload-ms',type=int,default=120000)
    for name in ('inspect','resume','recover','cancel'):
        q=subs.add_parser(name);q.add_argument('--job',required=True)
        if name in ('resume','recover'):q.add_argument('--token')
    q=subs.add_parser('once')
    args=p.parse_args(argv);engine=database_engine();stopped=Event()
    signal.signal(signal.SIGINT,lambda *_:stopped.set());signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    try:
        if args.command=='setup':result={'checkpoint_namespace':graph.setup_checkpoints(engine)}
        elif args.command=='enqueue':
            session=None
            if args.session:
                from .session_protocol import Config
                revision=args.revision
                if args.session=='fake':revision='fake-v1'
                elif revision is None:
                    from pathlib import Path
                    from decisionops.backends import parse_revision_pins,REPOSITORIES
                    revision=parse_revision_pins(Path(__file__).resolve().parents[2]/'model-revisions.env')[REPOSITORIES[args.session][1]]
                session=Config(args.session,revision,behavior=args.fake_session_behavior,preload_ms=args.preload_ms).record()
            result=jobs.enqueue(engine,args.case,args.report,policy=args.policy,session=session)
        elif args.command=='inspect':
            with service.transaction(engine,readonly=True) as c:job=jobs.get(c,args.job)
            result={'job':job,'run':service.inspect(engine,job['run_id']),'graph':graph.inspect(engine,args.job)}
        elif args.command=='cancel':result=jobs.cancel(engine,args.job)
        elif args.command=='resume' and not args.token:result=graph.resume(engine,args.job,cancel=stopped)
        else:
            if args.command=='once':owned=jobs.claim(engine)
            elif args.token:
                with service.transaction(engine,readonly=True) as c:owned=jobs.get(c,args.job)
                owned['token']=args.token
            else:owned=jobs.claim(engine,job_id=args.job)
            if owned is None:raise ValueError('No claim available; inspect lease/deadline or cancel expired run')
            fence=jobs.Fence(owned['id'],owned['token'])
            if args.command=='recover':result=jobs.recover(engine,fence)
            else:
                result=run_until_pause(engine,fence,cancel=stopped)
                if not stopped.is_set():graph.project(engine,owned['id'],fence,cancel=stopped,advance=False)
        print(json.dumps(result,indent=2,default=lambda v:str(v) if isinstance(v,Decimal) else v.isoformat()))
        return 0
    except graph.CheckpointFailure as e:
        print(json.dumps({'event':'adaptive_checkpoint_error','kind':type(e).__name__,
                          'message':str(e),'domain_authority':'PostgreSQL','automatic_retry':False}),file=sys.stderr)
        return 3
    except (ValueError,SQLAlchemyError,SessionFailure) as e:
        print(json.dumps({'event':'adaptive_worker_error','kind':type(e).__name__,'message':str(e) if isinstance(e,ValueError) else 'Check isolated database readiness/migrations'}),file=sys.stderr)
        return 4 if isinstance(e,LeaseLost) else 2
    finally:engine.dispose()

if __name__=='__main__':raise SystemExit(main())
