"""Staff-only durable investigation; rules default and mock-only optional transport."""
import argparse,json,signal,time,os
from threading import Event
import sqlalchemy as sa
from . import schema as db,adaptive_investigations as service,adaptive_jobs as jobs
from .cases import lock_case,event,clock,identifier
from .adaptive_tools import PROJECTIONS

MODES=('rules','mock-decisions','mock-specialists')

def expire_run(c,run_id):
    """Bounded system cleanup after the immutable deadline; no dispatch or reset."""
    from . import adaptive_accounting as ledger
    run,case=service.locked(c,run_id)
    if run['state']!='active' or not run['contracts'].get('staff_ui') or clock(c)<run['deadline']:return False
    job=c.execute(sa.select(db.adaptive_jobs).where(db.adaptive_jobs.c.run_id==run_id).with_for_update()).mappings().one()
    call=ledger.latest(c,run_id)
    if call and call['state']=='dispatching':ledger.uncertain(c,call['id'],'staff_run_deadline')
    elif call and call['state']=='reserved':ledger.expire_reserved(c,call['id'])
    if run['contracts'].get('specialists'):
        from .multi_agent import calls,get
        for saved in calls(c,run_id):
            saved=get(c,saved['id'])
            if saved['state']=='dispatching':
                c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id==saved['id']).values(state='uncertain',error='run_deadline'))
            elif saved['state']=='reserved':
                c.execute(db.specialist_calls.update().where(db.specialist_calls.c.id==saved['id']).values(state='settled',disposition='discarded',error='expired_before_dispatch'))
    history=service.snapshot(c,run)[0]
    service.finish(c,run,case,history,'run_deadline',stale=not service.matches(run,case))
    c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==job['id']).values(status='failed',error='RunDeadline',token=None,lease_until=None))
    return True

def reap_expired(engine):
    with service.transaction(engine,readonly=True) as c:
        ids=c.execute(sa.select(db.adaptive_runs.c.id).where(sa.and_(db.adaptive_runs.c.state=='active',
            db.adaptive_runs.c.contracts['staff_ui'].as_boolean()==True,db.adaptive_runs.c.deadline<=sa.func.clock_timestamp())).limit(20)).scalars().all()
    for run_id in ids:
        with service.transaction(engine) as c:expire_run(c,run_id)


def enqueue(c,engine,case_id,report,request_id,generation,mode='rules'):
    if mode not in MODES:raise ValueError('Staff investigation supports rules, mock-decisions or mock-specialists only')
    case=lock_case(c,case_id)
    overdue=c.execute(sa.select(db.adaptive_runs.c.id).where(sa.and_(db.adaptive_runs.c.case_id==case_id,db.adaptive_runs.c.state=='active',db.adaptive_runs.c.deadline<=sa.func.clock_timestamp(),db.adaptive_runs.c.contracts['staff_ui'].as_boolean()==True))).scalar_one_or_none()
    if overdue:
        expire_run(c,overdue);case=lock_case(c,case_id)
    previous=c.execute(sa.select(db.case_events.c.details).where(sa.and_(db.case_events.c.case_id==case_id,
        db.case_events.c.kind=='staff_investigation_requested'))).scalars().all()
    for saved in previous:
        if saved['request_id']==request_id:
            if saved['report']!=report or saved.get('mode','rules')!=mode or saved.get('expected_generation',generation)!=generation:raise ValueError('Request identity reused with changed report')
            return service.inspect_connection(c,saved['run_id'])
    active=c.execute(sa.select(db.adaptive_runs).where(sa.and_(db.adaptive_runs.c.case_id==case_id,db.adaptive_runs.c.state=='active'))).mappings().one_or_none()
    if active:
        if active['contracts'].get('staff_ui') and any(saved['run_id']==active['id'] and saved['report']==report for saved in previous) and bool(active['contracts'].get('specialists'))==(mode=='mock-specialists') and bool(active['contracts'].get('api'))==(mode=='mock-decisions'):
            if generation not in (active['generation']-1,active['generation']):raise ValueError('Case changed; refresh before investigating')
            event(c,case_id,'staff_investigation_requested',{'request_id':request_id,'run_id':active['id'],'report':report,'expected_generation':generation,'coalesced':True,'mode':mode},clock(c))
            return service.inspect_connection(c,active['id'])
        raise ValueError('Case already has an active investigation')
    if case['generation']!=generation:raise ValueError('Case changed; refresh before investigating')
    if c.execute(sa.select(db.jobs.c.id).where(sa.and_(db.jobs.c.case_id==case_id,db.jobs.c.status.in_(('queued','running'))))).first():raise ValueError('Case has another in-flight action')
    api=None
    if mode=='mock-decisions':
        from .openai_decisions import DecisionsConfig
        from .api_accounting import create_budget
        api=DecisionsConfig(identifier('STAFF-MOCK')).record();create_budget(c,api)
    reports=c.execute(sa.select(db.customer_reports.c.message).where(db.customer_reports.c.case_id==case_id)
        .order_by(db.customer_reports.c.created_at.desc()).limit(3)).scalars().all()
    context=report
    if reports:
        # Text helps select reads; deterministic source checks still decide eligibility.
        staff_text=report.encode('utf-8')[:700].decode('utf-8','ignore')
        customer_text='\n'.join(reports).encode('utf-8')[:1200].decode('utf-8','ignore')
        context=staff_text+'\nCustomer reports (untrusted context; not carrier evidence):\n'+customer_text
    run=service.start(engine,case_id,context,scheduled=True,api=api,connection=c,staff_ui=True,specialists=mode=='mock-specialists')
    event(c,case_id,'staff_investigation_requested',{'request_id':request_id,'run_id':run['id'],'report':report,'expected_generation':generation,'mode':mode},clock(c))
    return run

def view(c,case_id):
    run_id=c.execute(sa.select(db.adaptive_runs.c.id).where(sa.and_(db.adaptive_runs.c.case_id==case_id,
        db.adaptive_runs.c.contracts['staff_ui'].as_boolean()==True)).order_by(db.adaptive_runs.c.created_at.desc()).limit(1)).scalar_one_or_none()
    if not run_id:return None
    run=service.inspect_connection(c,run_id)
    case=c.execute(sa.select(db.cases).where(db.cases.c.id==case_id)).mappings().one()
    historical=(run['generation']!=case['generation'] or run['request']!=case['request']
        or run['request']['order_id']!=case['order_id'])
    if run.get('evidence_error'):
        return {'id':run_id,'generation':run['generation'],'historical':historical,'state':'review','report':run['report'],'mode':'mock_specialists' if run['contracts'].get('specialists') else 'rules',
            'reason':run['evidence_error'],'job_status':run['job']['status'],'unknowns':list(run['assessment']['facts']),
            'blockers':[],'facts':run['assessment']['facts'],'steps':[],'evidence':[],'specialists':[],
            'evidence_current':False,'planned_checks':[]}
    history,_,audit,_,_=service.snapshot(c,run);now=clock(c)
    active={o.id:o for o in history.active()};evidence=[]
    changed=set()
    if historical:
        changed.update(PROJECTIONS)
    from .adaptive_evidence import History
    from .adaptive_tools import DEPENDENCIES,read_tool
    from .read_tools import AssessmentRequest
    fresh=History(run['request'])
    for tool in DEPENDENCIES:
        if not history.active(tool):continue
        try:
            before=history.select(tool,now)
            current=read_tool(c,tool,AssessmentRequest(**run['request']),fresh,now,
                dependencies=tuple(fresh.select(dep,now) for dep in DEPENDENCIES[tool]))
            fresh.append(current)
            if before.version!=current.version:changed.add(tool)
        except ValueError:changed.add(tool)
    for saved in audit:
        record=saved['record'];obs=active.get(record['id'])
        applicability='discarded' if not saved['applied'] else 'superseded' if obs is None else 'current'
        reason=history.invalid_reason(obs,now) if obs is not None else None
        if record['tool'] in changed:reason='refresh_required'
        if obs is not None and history.content_conflict(record['tool']):reason='conflicting_active_contents'
        if reason:applicability=reason
        evidence.append({'tool':record['tool'],'value':record['value'] if applicability=='current' else None,
            'recorded_value':record['value'],'applicability':applicability,'status':record['status'],
            'reason':reason or record['reason'],'observed_at':record['observed_at'],'expires_at':record['expires_at'],
            'source':{'kind':'database_read','observation_id':record['id'],
                'version':record['source_version'],'order_id':record['request']['order_id'],
                'shipment_id':record['request']['shipment_id'],
                'tables':[table for table,columns in PROJECTIONS[record['tool']]]}})
    branches=[]
    if run['contracts'].get('specialists'):
        from .multi_agent import calls,result_status
        for name in ('order','shipment'):
            rows=calls(c,run['id'],name)
            branches.append({'name':name,'state':result_status(c,run,name),'tools':[r['tool'] for r in rows if r['tool']],
                'reason':next((r['error'] for r in rows if r['error']),None),'observations':[r['observation']['id'] for r in rows if r['observation']]})
    facts=dict(run['assessment']['facts'])
    from .adaptive_evidence import TOOLS
    for tool in changed:facts[TOOLS[tool]]=None
    return {'generation':run['generation'],'historical':historical,'evidence_current':not changed,'planned_checks':['Bind order and policy','Check shipment and carrier','Check payment and compensation','Check inventory and join evidence'],'specialists':branches,'id':run['id'],'state':run['state'],'report':run['report'],'mode':'mock_specialists' if run['contracts'].get('specialists') else 'simulated_decisions' if run['contracts'].get('api') else 'rules',
        'job_status':run['job']['status'],'reason':run['terminal'].get('reason') if run['terminal'] else None,
        'unknowns':[fact for fact,value in facts.items() if value is None],
        'blockers':[fact for fact,value in facts.items() if value is False],
        'facts':facts,'steps':[{'sequence':s['sequence'],'kind':s['kind'],'data':{k:v for k,v in s['data'].items() if k in ('tool','status','reason','action','chosen_action','requested_action','source','specialist','applied')},'created_at':s['created_at']} for s in run['steps']],
        'evidence':evidence}

def adapter_for(run):
    if not run['contracts'].get('api'):
        from .adaptive_recommendations import FakeAdapter
        return FakeAdapter()
    from .openai_decisions import DecisionsAdapter,DecisionsConfig
    cfg=DecisionsConfig(**run['contracts']['api'])
    if cfg.execution!='mock':raise ValueError('Staff worker refuses paid adapters')
    import httpx
    # Exercise the historical early-review gap: review while information is missing.
    def handler(request):
        features=json.loads(json.loads(request.content)['input']);actions=features['allowed_actions']
        index=next((i for i,a in enumerate(actions) if a['kind'] in ('propose','report_blocker')),None)
        if index is None:index=next(i for i,a in enumerate(actions) if a=={'kind':'request_review','reason':'unknown_evidence'})
        values=[v['value'] for v in json.loads(request.content)['questions'][0]['choices']];chosen=values[index]
        return httpx.Response(200,json={'model':cfg.model,'answers':[{'type':'choice','name':'investigation_action','choice':chosen,'confidence':.5,
            'probabilities':[{'value':v,'probability':float(v==chosen)} for v in values]}], 'usage':{'input_tokens':100,'output_tokens':0,'total_tokens':100}})
    return DecisionsAdapter(api_key='fictional-mock-only',transport=httpx.MockTransport(handler))

def work_once(engine,stop=None,step_delay=0,tracer=None):
    if not 0<=step_delay<=.5:raise ValueError('Step delay must be bounded to 0..0.5s')
    from .delivery import scan
    with service.transaction(engine) as c:
        scan(c,os.environ.get('COMMERCE_STORE_ID','demo-store'))
    reap_expired(engine)
    owned=jobs.claim(engine,staff_only=True)
    if not owned:
        owned=jobs.claim(engine,staff_only=True,action=jobs.SPECIALIST_ACTION)
        if not owned:return {'event':'idle'}
        from . import multi_agent_workflow
        fence=jobs.Fence(owned['id'],owned['token'])
        result=multi_agent_workflow.run(engine,fence,cancel=stop,node_delay=step_delay,tracer=tracer)
        return {'event':'specialists','state':result['state'],'run_id':result['id']}
    fence=jobs.Fence(owned['id'],owned['token']);run=service.inspect(engine,owned['run_id']);adapter=adapter_for(run)
    from .adaptive_runner import tick
    for _ in range(34):
        if stop is not None and stop.wait(step_delay):return {'event':'worker_stopped'}
        elif stop is None and step_delay:time.sleep(step_delay)
        result=tick(engine,fence,adapter=adapter,cancel=stop)
        from .observability import observe
        observe(engine,run['id'],tracer=tracer,attempt=owned['claims'])
        if result['event']!='step' or result.get('state')!='active':return result
        jobs.renew(engine,fence.job_id,fence.token)
    return {'event':'bounded_worker_pause'}

def main():
    from .database import database_engine
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--step-delay',type=float,default=0);args=p.parse_args()
    engine=database_engine();stop=Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    try:
        while not stop.is_set():
            try:
                result=work_once(engine,stop,args.step_delay)
                if result['event']!='idle':print(json.dumps(result,default=str),flush=True)
            except Exception as error:print(json.dumps({'event':'staff_worker_paused','error_kind':type(error).__name__}),flush=True)
            stop.wait(.25)
    finally:engine.dispose()
if __name__=='__main__':main()
