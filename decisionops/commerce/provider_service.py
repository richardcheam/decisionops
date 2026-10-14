"""Opt-in post-assessment routing; providers never establish facts or permissions."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from queue import Queue,Empty
from threading import Thread
import time

import sqlalchemy as sa

from . import schema as db
from .cases import (clock,event,lock_case,lock_business,investigate_case,show_case,
                    escalate_case,invalidate)
from .read_tools import AssessmentRequest,read_assessment
from .proposals import binding,document_hash
from .providers import (ProviderConfig,ProviderRequest,ProviderResult,Pricing,Limits,
                        FakeProvider,RulesProvider,validate_result,permitted_choices,response_id)
from . import provider_budget as ledger


@contextmanager
def transaction(engine,readonly=False):
    with engine.connect() as connection:
        if not readonly:connection=connection.execution_options(isolation_level='READ COMMITTED')
        with connection.begin():
            if readonly:connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
            yield connection


def request_from_call(row):
    if document_hash(row['request'])!=row['request_hash']:raise ValueError('Provider request hash mismatch')
    return ProviderRequest.from_record(row['request'])


def build_request(case,assessment,run_id,config,deadline,limits,pricing):
    bound={key:case[key] for key in ('generation','status','investigation_id','proposal_id','request')}
    bound.update(content_hash=case['proposal']['content_hash'] if case['proposal'] else None,
                 policy_id=assessment['policy_id'],source_versions=binding(assessment)['source_versions'])
    return ProviderRequest('route_investigated_case',case['id'],run_id,assessment['facts'],bound,
        permitted_choices(assessment['facts'],case['status']),config,deadline,limits,pricing)


def prepare(engine,case_id,run_id,budget_id,config,deadline_seconds=5):
    maximum=120 if config.mode in ('laya','gliclass') else 30
    if type(deadline_seconds) not in (int,float) or not 0<deadline_seconds<=maximum:
        raise ValueError('Provider deadline exceeds the bounded mode limit')
    with transaction(engine) as c:
        case=lock_case(c,case_id)
        saved=ledger.get_call(c,run_id)
        if saved:
            request=request_from_call(saved)
            if saved['case_id']!=case_id or saved['budget_id']!=budget_id or request.config!=config:
                raise ValueError('Run identifier binds a different case/budget/provider configuration')
            return saved
        if case['status'] in ('approved','executed','rejected','escalated'):
            raise ValueError('Explicitly reinvestigate this case before requesting a provider route')
        # Concrete insertion: complete bundled assessment/proposal FIRST. No adaptive tools.
        case=investigate_case(c,case_id)
        assessment=c.execute(sa.select(db.investigations.c.assessment).where(
            db.investigations.c.id==case['investigation_id'])).scalar_one()
        budget=ledger.get_budget(c,budget_id)
        prices=dict(budget['pricing']);prices.pop('simulated')
        req=build_request(case,assessment,run_id,config,clock(c)+timedelta(seconds=deadline_seconds),Limits(**budget['limits']),Pricing(**prices))
        row=ledger.reserve(c,budget_id,req)
        event(c,case_id,'provider_reserved',{'run_id':run_id,'state':row['state'],
              'simulated':config.mode=='fake','execution_authorized':False},clock(c))
        return row


def failure(request,kind,status='invalid',latency=0):
    if request.config.mode!='fake':
        from .local_provider import local_result
        return replace(local_result(request,status=status,error=kind),latency_ms=latency)
    return ProviderResult(None,request.config.provider_id,request.run_id,response_id('LOCAL',request.run_id),
                         status=status,input_tokens=None,output_tokens=None,latency_ms=latency,
                         error_kind=kind,error_message='Simulated provider failure; staff review required')


def dispatch(engine,run_id,provider=None):
    from .local_provider import LocalProvider
    with transaction(engine,True) as c:
        row=ledger.get_call(c,run_id)
        if row is None:raise ValueError('Run not found')
        initial=request_from_call(row)
    local=initial.config.mode in ('laya','gliclass')
    provider=provider or (LocalProvider() if local else FakeProvider())
    if not isinstance(provider,LocalProvider if local else FakeProvider):raise ValueError('Provider implementation/mode mismatch')
    with transaction(engine) as c:
        ledger.recover_expired(c,run_id)
        owned=ledger.claim(c,run_id)
    if owned is None:
        with transaction(engine,True) as c:return ledger.get_call(c,run_id)
    request=request_from_call(owned)
    if local:
        try:result=validate_result(request,provider.choose(request))
        except ValueError:result=failure(request,'invalid_local_result')
        with transaction(engine) as c:return ledger.settle(c,run_id,result,datetime.now(timezone.utc))
    started=time.monotonic();remaining=(request.deadline-datetime.now(timezone.utc)).total_seconds()
    queue=Queue(maxsize=1)
    def invoke():
        try:queue.put(('result',provider.choose(request)))
        except Exception as error:queue.put(('error',type(error).__name__))
    if remaining<=0:
        result=failure(request,'dispatch_deadline_expired','timeout')
    else:
        # Deadline returns without waiting for an uncooperative fake. Late results
        # only enter this private queue; they never write the ledger/application.
        Thread(target=invoke,daemon=True).start()
        try:
            kind,raw=queue.get(timeout=remaining)
            elapsed=int((time.monotonic()-started)*1000)
            if kind=='error':result=failure(request,raw,'timeout' if raw=='TimeoutError' else 'invalid',elapsed)
            else:
                try:result=replace(validate_result(request,raw),latency_ms=elapsed)
                except ValueError:
                    # A typed result with only a forbidden choice can still supply
                    # bounded known usage. Malformed identity/usage stays uncertain.
                    result=failure(request,'invalid_response',latency=elapsed)
                    if isinstance(raw,ProviderResult):
                        candidate=replace(raw,status='invalid',selected_choice=None,
                            error_kind='invalid_recommendation',error_message='Recommendation is not permitted',latency_ms=elapsed)
                        try:result=validate_result(request,candidate)
                        except ValueError:pass
        except Empty:
            result=failure(request,'deadline_timeout','timeout',int((time.monotonic()-started)*1000))
    received=datetime.now(timezone.utc)
    with transaction(engine) as c:return ledger.settle(c,run_id,result,received)


def public_row(row):
    return {key:(str(value) if isinstance(value,Decimal) else value.isoformat() if isinstance(value,datetime) else value)
            for key,value in row.items()}


def inspect(engine,run_id):
    with transaction(engine,True) as c:
        row=ledger.get_call(c,run_id)
        if row is None:raise ValueError('Run not found')
        request_from_call(row)
        return {'mode':request_from_call(row).config.mode,'simulated':request_from_call(row).config.mode=='fake','trace':public_row(row),
                'budget':ledger.summary(c,row['budget_id']),'case':show_case(c,row['case_id']),
                'execution_authorized':False}


def apply(engine,run_id):
    with transaction(engine) as c:
        first=ledger.get_call(c,run_id)
        if first is None:raise ValueError('Run not found')
        lock_case(c,first['case_id'])
        case=show_case(c,first['case_id'])
        row=ledger.get_call(c,run_id)
        req=request_from_call(row)
        if row['state'] in ('reserved','dispatching') or row['application_status']!='pending':
            pass
        else:
            bound=req.binding
            state_matches=all(case[key]==bound[key] for key in ('generation','status','investigation_id','proposal_id','request'))
            if state_matches:
                lock_business(c,AssessmentRequest(**case['request']))
                current=read_assessment(c,AssessmentRequest(**case['request']),clock(c))
                latest=binding(current)
                matches=(latest['source_versions']==dict(bound['source_versions'])
                         and latest['policy_id']==bound['policy_id']
                         and current['facts']==dict(req.facts)
                         and permitted_choices(current['facts'],case['status'])==req.allowed_choices
                         and (case['proposal']['content_hash'] if case.get('proposal') else None)==bound['content_hash'])
            else:matches=False
            # Business rows precede the call lock: prepare uses business->budget,
            # settlement uses budget->call. Never hold call while waiting business.
            row=ledger.get_call(c,run_id,True)
            if not matches:
                connection_change={'application_status':'stale','effective_choice':None}
                event(c,case['id'],'provider_result_stale',{'run_id':run_id,'state_changed':not state_matches},clock(c))
                if state_matches and case['status']=='awaiting_review':
                    invalidate(c,case,{'status':'requires_reinvestigation','current_decision':current['decision'],
                                      'reason':'Provider evidence changed or expired'},clock(c))
            else:
                result=row['result'] or {}
                good=row['state']=='settled' and result.get('status')=='success'
                choice=result['selected_choice'] if good else 'staff_review'
                if choice not in permitted_choices(current['facts'],case['status']):
                    raise ValueError('Stored provider choice is not permitted')
                if choice=='staff_review' and case['status']=='awaiting_review':
                    escalate_case(c,case['id'],'Provider routing requires staff review')
                # Blocked/unknown cases keep their deterministic status and facts.
                event(c,case['id'],'provider_routed',{'run_id':run_id,'effective_choice':choice,
                    'fallback':not good,'simulated':req.config.mode=='fake','execution_authorized':False},clock(c))
                connection_change={'application_status':'applied' if good else 'fallback','effective_choice':choice}
            c.execute(db.provider_calls.update().where(db.provider_calls.c.run_id==run_id).values(**connection_change))
    return inspect(engine,run_id)


def recover(engine,run_id):
    dispatch(engine,run_id)
    return apply(engine,run_id)


def recommend(engine,case_id,run_id,budget_id=None,config=None,*,deadline_seconds=5,provider=None):
    config=config or ProviderConfig(mode='rules')
    if config.mode=='rules':
        with transaction(engine) as c:
            case=investigate_case(c,case_id)
            assessment=c.execute(sa.select(db.investigations.c.assessment).where(db.investigations.c.id==case['investigation_id'])).scalar_one()
            request=build_request(case,assessment,run_id,config,clock(c)+timedelta(seconds=5),Limits(max_cost_usd='0'),Pricing.local())
            result=validate_result(request,RulesProvider().choose(request))
        return {'mode':'rules','case':case,'provider_calls':0,'execution_authorized':False,
                'recommendation':result.as_record()}
    if not budget_id:raise ValueError('Provider mode requires a durable budget')
    prepare(engine,case_id,run_id,budget_id,config,deadline_seconds)
    dispatch(engine,run_id,provider)
    return apply(engine,run_id)
