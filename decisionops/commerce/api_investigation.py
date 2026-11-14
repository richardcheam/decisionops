"""Explicit isolated operator entry point. No migration, seed, approval or execution."""
import argparse,json,os
from pathlib import Path
from .database import database_engine
from . import schema as db,adaptive_jobs as jobs,adaptive_investigations as service
from .adaptive_runner import _run_until_pause
from .api_decisions import config_for,OpenAIAdapter
from .api_accounting import create_budget
from .proposals import document_hash

def adapter_for(config):
    if config.version=="commerce-decisions/v1":
        from .openai_decisions import DecisionsAdapter
        return DecisionsAdapter
    return OpenAIAdapter

def mock_transport(config,scenario):
    import httpx
    def handler(request):
        if scenario=='timeout':raise httpx.ReadTimeout('Simulated transport timeout',request=request)
        features=json.loads(json.loads(request.content)['input']);actions=features['allowed_actions']
        index=999 if scenario=='invalid' else next((i for i,a in enumerate(actions) if a['kind']=='propose'),None)
        if index is None:index=next((i for i,a in enumerate(actions) if a['kind']=='read'),0)
        if config.version=='commerce-decisions/v1':
            values=[v['value'] for v in json.loads(request.content)['questions'][0]['choices']]
            selected=values[index] if index<len(values) else 'unlisted'
            return httpx.Response(200,json={'model':config.model,
                'answers':[{'type':'choice','name':'investigation_action','choice':selected,'confidence':1.0,
                            'probabilities':[{'value':v,'probability':float(v==selected)} for v in values]}],
                'usage':{'input_tokens':100,'output_tokens':0,'total_tokens':100}})
        return httpx.Response(200,json={'id':'resp_simulated','object':'response','created_at':1,'status':'completed','model':config.model,
             'output':[{'type':'message','id':'msg_simulated','role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps({'action_index':index}),'annotations':[]}]}],
             'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110}})
    return httpx.MockTransport(handler)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('start');s.add_argument('--config',type=Path,required=True);s.add_argument('--case',required=True);s.add_argument('--report',required=True)
    s.add_argument('--approved-config-sha256');s.add_argument('--mock-scenario',choices=('success','timeout','invalid'),default='success');s.add_argument('--output',type=Path,required=True)
    s=sub.add_parser('inspect');s.add_argument('--run',required=True)
    s=sub.add_parser('recover');s.add_argument('--job',required=True);s.add_argument('--token',required=True)
    s=sub.add_parser('resume');s.add_argument('--job',required=True);s.add_argument('--token',required=True);s.add_argument('--approved-config-sha256')
    args=p.parse_args(argv);engine=database_engine()
    try:
        url=engine.url
        identity=(url.host,url.port,url.database,url.username)
        permitted={('127.0.0.1',55445,'commerce_api_test','commerce_api'),('127.0.0.1',55446,'commerce_decisions_test','commerce_decisions')}
        if identity not in permitted:raise ValueError('Requires a verified isolated API demonstration environment on 55445/55446')
        with engine.connect() as c:
            if tuple(c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one())!=(url.database,url.username,5432):raise ValueError('Database identity mismatch')
        if args.command=='inspect':run=service.inspect(engine,args.run)
        elif args.command=='recover':
            jobs.recover(engine,jobs.Fence(args.job,args.token))
            with service.transaction(engine,readonly=True) as c:job=jobs.get(c,args.job)
            run=service.inspect(engine,job['run_id'])
        else:
            if args.command=='start':
                if args.output.exists():raise ValueError('Preserve existing trace output')
                cfg=config_for(json.loads(args.config.read_text()))
            else:
                with service.transaction(engine,readonly=True) as c:job=jobs.get(c,args.job)
                saved=service.inspect(engine,job['run_id']);cfg=config_for(saved['contracts']['api'])
            expected_port=55446 if cfg.version=='commerce-decisions/v1' else 55445
            if url.port!=expected_port:raise ValueError('API contract/database environment mismatch')
            if cfg.execution=='live':
                if args.approved_config_sha256!=document_hash(cfg.record()):raise ValueError('Live configuration requires explicit matching approval hash')
                if not os.environ.get('OPENAI_API_KEY'):raise ValueError('External OPENAI_API_KEY unavailable')
                adapter=adapter_for(cfg)(approved_config_hash=args.approved_config_sha256)
            else:adapter=adapter_for(cfg)(api_key='fictional-mock-only',transport=mock_transport(cfg,getattr(args,'mock_scenario','success')))
            if args.command=='start':
                with engine.begin() as c:
                    existing=c.execute(db.provider_budgets.select().where(db.provider_budgets.c.id==cfg.budget_id)).mappings().one_or_none()
                    if existing is None:create_budget(c,cfg.record())
                    elif existing['limits']!={'task':'choose_investigation_action/v1','config':cfg.record()}:raise ValueError('Budget already exists with another binding')
                job=jobs.enqueue(engine,args.case,args.report,api=cfg.record());owner=jobs.claim(engine,job_id=job['id'])
                fence=jobs.Fence(owner['id'],owner['token'])
            else:fence=jobs.Fence(args.job,args.token)
            outcome=_run_until_pause(engine,fence,adapter=adapter);run=service.inspect(engine,job['run_id'])
            run['operator_outcome']=outcome
        with engine.connect() as c:
            money=[dict(r) for r in c.execute(db.provider_calls.select().where(db.provider_calls.c.case_id==run['case_id'])).mappings() if r['request'].get('task')=='choose_investigation_action/v1']
            calls=[dict(r) for r in c.execute(db.adaptive_calls.select().where(db.adaptive_calls.c.run_id==run['id'])).mappings()]
        trace={'run':run,'decisions':calls,'monetary_reservations':money,'simulation':run['contracts']['api']['execution']=='mock','execution_authorized':False}
        if args.command=='start':
            args.output.mkdir(parents=True);(args.output/'trace.json').write_text(json.dumps(trace,indent=2,default=str)+'\n')
        print(json.dumps(trace,indent=2,default=str));return 0
    finally:engine.dispose()
if __name__=='__main__':raise SystemExit(main())
