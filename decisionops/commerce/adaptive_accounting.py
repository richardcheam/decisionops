"""Task-specific durable decision reservations. Legacy routing ledger is unchanged."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import sqlalchemy as sa
from . import schema as db,adaptive_investigations as service
from .cases import clock,identifier
from .adaptive_evidence import canonical
from .proposals import document_hash
from .adaptive_policies import PolicyRequest,Action
from .adaptive_recommendations import Request,Result,TASK,CONFIG_VERSION,validate

def get(c,call_id,lock=False):
    q=sa.select(db.adaptive_calls).where(db.adaptive_calls.c.id==call_id)
    if lock:q=q.with_for_update()
    value=c.execute(q).mappings().one_or_none()
    if value is None:raise ValueError('Recommendation not found')
    saved=dict(value)
    if document_hash(saved['request'])!=saved['request_hash']:raise ValueError('Immutable request hash mismatch')
    return saved

def latest(c,run_id):
    value=c.execute(sa.select(db.adaptive_calls).where(db.adaptive_calls.c.run_id==run_id)
                    .order_by(db.adaptive_calls.c.context_version.desc()).limit(1)).mappings().one_or_none()
    return dict(value) if value else None

def event(c,call_id,kind,data):
    sequence=c.execute(sa.select(sa.func.coalesce(sa.func.max(db.adaptive_call_events.c.sequence),0)).where(
                       db.adaptive_call_events.c.call_id==call_id)).scalar_one()+1
    c.execute(db.adaptive_call_events.insert().values(call_id=call_id,sequence=sequence,kind=kind,
              data=json.loads(canonical(data)),created_at=clock(c)))

def request_from(row):
    record=row['request'];f=record['features']
    policy=PolicyRequest(record['run_id'],record['context_version'],f['report'],f['observations'],
            tuple(Action.from_record(a) for a in f['allowed_actions']),tuple(f['attempted_tools']),f['remaining_budgets'],tuple(f['rejections']))
    return Request(row['id'],record['run_id'],record['generation'],record['case_revision'],policy,
                   record['configuration']['mode'],record['max_runtime_ms'],record['task'],record['configuration'].get('session'),row['deadline'])

def prepare(engine,run_id,fence):
    with service.guarded(engine,run_id,fence) as (c,run,case):
        if run['state']!='active' or run['pending_token']:raise ValueError('Terminal run or interrupted read; recover explicitly')
        old=latest(c,run_id)
        if old and old['application_status']=='pending':return get(c,old['id'])
        if run['decision_attempts']>=16:raise ValueError('Decision budget exhausted')
        history,steps,_,_,counts=service.snapshot(c,run)
        committed=c.execute(sa.select(sa.func.coalesce(sa.func.sum(sa.case(
            (db.adaptive_calls.c.state=='settled',db.adaptive_calls.c.actual_ms),else_=db.adaptive_calls.c.reserved_ms)),0))
            .where(db.adaptive_calls.c.run_id==run_id)).scalar_one()
        session_binding=None
        if run['contracts'].get('session'):
            from .adaptive_sessions import phase_charge,records
            committed+=phase_charge(c,run_id)
            fallback=bool(old and (old['application_status']=='stale' or old['result'] and old['result']['status']!='success' or old['request']['configuration'].get('source')=='rules'))
            if not fallback:
                sessions=records(c,run_id);ready=next((r for r in reversed(sessions) if r['state']=='ready' and not r['retired']),None)
                session_binding={'config':run['contracts']['session'],'session_id':ready['id'] if ready else None}
        now=clock(c);maximum=min(20000,int((run['deadline']-now).total_seconds()*1000),240000-committed)
        if maximum<=0:raise ValueError('Decision resource budget exhausted')
        mode=run['contracts']['policy']
        if old and (old['application_status']=='stale' or old['result'] and old['result']['status']!='success'):mode='fixed'
        if run['contracts'].get('session') and fallback:mode='fixed'
        initial=service.request_for(run,history,steps,counts,now)
        if session_binding is not None and len(initial.allowed)==1:session_binding['session_id']=None
        policy=replace(initial,context_version=run['context_version']+1,
                       budgets={**initial.budgets,'decisions':initial.budgets['decisions']-1})
        req=Request(identifier('AREC'),run_id,run['generation'],run['case_revision'],policy,mode,maximum,session=session_binding)
        record=req.record()
        if run['contracts'].get('session'):
            record['configuration'].update(source=('fake_session' if session_binding['config']['family']=='fake' else 'local_session') if session_binding else 'rules',fallback=fallback)
        record.update(case_id=case['id'],deadline=(now+timedelta(milliseconds=maximum)).isoformat(),
            contract_versions=run['contracts'],source_bindings=[o.dependency() for o in history.active()])
        if len(canonical(record).encode())>32768:raise ValueError('Recommendation request byte cap')
        service.step(c,run,'recommendation_reserved',{'call_id':req.id,'task':TASK,'request_hash':document_hash(record),
             'fallback':fallback if run['contracts'].get('session') else mode!=run['contracts']['policy'],'reserved_ms':maximum},decision_attempts=run['decision_attempts']+1)
        c.execute(db.adaptive_calls.insert().values(id=req.id,run_id=run_id,task=TASK,request=record,request_hash=document_hash(record),
             context_version=policy.context_version,state='reserved',reserved_ms=maximum,reserved_cost_usd=Decimal('0'),
             pricing_version='local-session-no-api/v1' if session_binding else CONFIG_VERSION,deadline=now+timedelta(milliseconds=maximum),created_at=now))
        event(c,req.id,'reserved',{'count':1,'maximum_ms':maximum,'api_charge_kind':'no_api_charge'})
        return get(c,req.id)

def claim(engine,call_id,fence):
    initial=None
    with service.transaction(engine,readonly=True) as c:initial=get(c,call_id)
    with service.guarded(engine,initial['run_id'],fence) as (c,run,case):
        row=get(c,call_id,True)
        if row['state']!='reserved':return None
        if row['context_version']!=run['context_version'] or not service.matches(run,case):raise ValueError('Stale dispatch context')
        if clock(c)>=row['deadline']:
            expire_reserved(c,call_id)
            return None
        c.execute(db.adaptive_calls.update().where(db.adaptive_calls.c.id==call_id).values(state='dispatching',dispatch_count=1))
        event(c,call_id,'dispatching',{'job_id':fence.job_id,'token':fence.token})
        return get(c,call_id)

def settle(c,call_id,result):
    row=get(c,call_id,True)
    result=validate(request_from(row),result)
    if row['state']!='dispatching':
        if row['state']=='uncertain':event(c,call_id,'late_result_discarded',result.record())
        return row
    c.execute(db.adaptive_calls.update().where(db.adaptive_calls.c.id==call_id).values(state='settled',
              actual_ms=result.elapsed_ms,actual_cost_usd=Decimal('0'),result=result.record()))
    event(c,call_id,'settled',{'elapsed_ms':result.elapsed_ms,'api_charge_kind':'no_api_charge'})
    return get(c,call_id)

def uncertain(c,call_id,reason):
    row=get(c,call_id,True)
    if row['state']=='dispatching':
        c.execute(db.adaptive_calls.update().where(db.adaptive_calls.c.id==call_id).values(state='uncertain'))
        event(c,call_id,'uncertain',{'reason':reason,'reservation_retained':True})
    return get(c,call_id)

def disposition(c,call_id,status):
    row=get(c,call_id,True)
    if row['application_status']=='pending':
        c.execute(db.adaptive_calls.update().where(db.adaptive_calls.c.id==call_id).values(application_status=status))
        event(c,call_id,status,{})
    return get(c,call_id)


def expire_reserved(c,call_id):
    """Known zero work: no dispatch occurred; this is not an uncertain call."""
    row=get(c,call_id,True)
    if row['state']=='reserved' and clock(c)>=row['deadline']:
        result=Result(call_id,None,0,'unavailable','deadline_before_dispatch')
        c.execute(db.adaptive_calls.update().where(db.adaptive_calls.c.id==call_id).values(state='settled',
                  actual_ms=0,actual_cost_usd=Decimal('0'),result=result.record()))
        event(c,call_id,'not_dispatched',{'reason':'deadline_before_dispatch','actual_ms':0})
    return get(c,call_id)
