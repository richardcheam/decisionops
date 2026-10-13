"""Operator CLI for rules versus simulated provider routing. Never calls a live API."""
import argparse
import json
import sys

from psycopg import Error as PsycopgError
from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from .read_tools import canonical
from .providers import Limits,Pricing,ProviderConfig,SCENARIOS
from .provider_budget import create_budget,summary
from .provider_service import transaction,recommend,prepare,recover,inspect,public_row


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    setup=commands.add_parser('budget-create')
    setup.add_argument('--budget',required=True)
    setup.add_argument('--max-requests',type=int,default=3)
    setup.add_argument('--max-cost-usd',default='0.00300000')
    setup.add_argument('--max-input-tokens',type=int,default=2000)
    setup.add_argument('--max-output-tokens',type=int,default=300)
    setup.add_argument('--pricing-version',default='simulated-v1')
    setup.add_argument('--input-usd-per-million',default='1')
    setup.add_argument('--output-usd-per-million',default='2')
    budget=commands.add_parser('budget');budget.add_argument('--budget',required=True)
    for name in ('investigate','prepare'):
        command=commands.add_parser(name)
        command.add_argument('--case',required=True);command.add_argument('--run',required=True)
        command.add_argument('--budget')
        command.add_argument('--mode',choices=('rules','fake'),default='rules' if name=='investigate' else 'fake')
        command.add_argument('--scenario',choices=SCENARIOS,default='success')
        command.add_argument('--delay-ms',type=int,default=0)
        command.add_argument('--deadline-seconds',type=float,default=5)
    for name in ('show','recover'):
        command=commands.add_parser(name);command.add_argument('--run',required=True)
    args=parser.parse_args(argv);engine=None
    try:
        engine=database_engine()
        if args.command=='budget-create':
            limits=Limits(args.max_requests,args.max_cost_usd,args.max_input_tokens,args.max_output_tokens)
            pricing=Pricing(args.pricing_version,'USD',args.input_usd_per_million,args.output_usd_per_million)
            with transaction(engine) as c:create_budget(c,args.budget,limits,pricing)
            with transaction(engine,True) as c:result=summary(c,args.budget)
        elif args.command=='budget':
            with transaction(engine,True) as c:result=summary(c,args.budget)
        elif args.command=='show':result=inspect(engine,args.run)
        elif args.command=='recover':result=recover(engine,args.run)
        else:
            config=ProviderConfig(mode=args.mode,scenario=args.scenario,delay_ms=args.delay_ms)
            if args.command=='prepare':
                if config.mode!='fake' or not args.budget:raise ValueError('Prepare requires fake mode and budget')
                prepare(engine,args.case,args.run,args.budget,config,args.deadline_seconds)
                result=inspect(engine,args.run)
            else:result=recommend(engine,args.case,args.run,args.budget,config,
                                  deadline_seconds=args.deadline_seconds)
        print(canonical(result))
        if args.command in ('investigate','recover') and result.get('mode')=='fake':
            return 0 if result['trace']['application_status']=='applied' else 4
        return 0
    except ValueError as error:
        print(json.dumps({'event':'provider_input_error','error':str(error)}),file=sys.stderr)
        return 2
    except (SQLAlchemyError,PsycopgError) as error:
        print(json.dumps({'event':'provider_database_unavailable','error_kind':type(error).__name__,
          'recover':'Inspect/recover the SAME run after readiness; do not assume dispatch failed'}),file=sys.stderr)
        return 3
    finally:
        if engine is not None:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
