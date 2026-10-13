"""Exact, simulated PostgreSQL reservations. Callers use short READ COMMITTED txs."""
from dataclasses import replace
from decimal import Decimal
import json

import sqlalchemy as sa

from . import schema as db
from .cases import clock
from .proposals import document_hash
from .providers import ProviderRequest,ProviderResult,Limits,Pricing,identifier,validate_result,response_id


def create_budget(connection,budget_id,limits,pricing):
    identifier(budget_id)
    existing=connection.execute(sa.select(db.provider_budgets).where(db.provider_budgets.c.id==budget_id)).mappings().one_or_none()
    record={'id':budget_id,'limits':limits.as_record(),'pricing':pricing.as_record()}
    if existing:
        if any(existing[name]!=value for name,value in record.items()):raise ValueError('Budget configuration/version is immutable')
        return dict(existing)
    # ON CONFLICT makes concurrent identical setup safe; changed setup fails afterward.
    from sqlalchemy.dialects.postgresql import insert
    connection.execute(insert(db.provider_budgets).values(**record,created_at=clock(connection)).on_conflict_do_nothing())
    saved=connection.execute(sa.select(db.provider_budgets).where(db.provider_budgets.c.id==budget_id)).mappings().one()
    if any(saved[name]!=value for name,value in record.items()):raise ValueError('Budget configuration/version is immutable')
    return dict(saved)


def get_budget(connection,budget_id,lock=False):
    query=sa.select(db.provider_budgets).where(db.provider_budgets.c.id==budget_id)
    if lock:query=query.with_for_update()
    row=connection.execute(query).mappings().one_or_none()
    if row is None:raise ValueError('Budget not found; create an explicit simulated budget first')
    return dict(row)


def get_call(connection,run_id,lock=False):
    query=sa.select(db.provider_calls).where(db.provider_calls.c.run_id==run_id)
    if lock:query=query.with_for_update()
    row=connection.execute(query).mappings().one_or_none()
    return dict(row) if row else None


def summary(connection,budget_id):
    budget=get_budget(connection,budget_id)
    calls=db.provider_calls
    cost=sa.case((calls.c.state=='denied',Decimal('0')),
                 (calls.c.state=='settled',calls.c.actual_cost_usd),else_=calls.c.reserved_cost_usd)
    count,committed=connection.execute(sa.select(
        sa.func.coalesce(sa.func.sum(sa.case((calls.c.state!='denied',1),else_=0)),0),
        sa.func.coalesce(sa.func.sum(cost),Decimal('0'))).where(calls.c.budget_id==budget_id)).one()
    return {'budget_id':budget_id,'limits':budget['limits'],'pricing':budget['pricing'],
            'reserved_request_count':count,'committed_cost_usd':format(committed,'.8f'),'simulated':True}


def reserve(connection,budget_id,request):
    if request.config.mode!='fake':raise ValueError('Only simulated calls may reserve this ledger')
    budget=get_budget(connection,budget_id,True)
    if budget['limits']!=request.limits.as_record() or budget['pricing']!=request.pricing.as_record():
        raise ValueError('Request budget/pricing configuration mismatch')
    record=request.as_record();digest=document_hash(record)
    existing=get_call(connection,request.run_id)
    if existing:
        if existing['request_hash']!=digest or existing['budget_id']!=budget_id:
            raise ValueError('Run identifier already binds a different request/budget')
        return existing
    # Unique run IDs also race across different budgets; INSERT rolls the loser back.
    totals=summary(connection,budget_id)
    maximum=request.pricing.cost(request.limits.max_input_tokens,request.limits.max_output_tokens)
    denied=(totals['reserved_request_count']>=request.limits.max_requests
            or Decimal(totals['committed_cost_usd'])+maximum>request.limits.max_cost_usd)
    now=clock(connection)
    result=ProviderResult(None,request.config.provider_id,request.run_id,response_id('LOCAL',request.run_id),
                         status='unavailable',input_tokens=0,output_tokens=0,
                         error_kind='budget_exhausted',error_message='No dispatch: simulated budget exhausted') if denied else None
    connection.execute(db.provider_calls.insert().values(run_id=request.run_id,case_id=request.case_id,
        budget_id=budget_id,request=record,request_hash=digest,state='denied' if denied else 'reserved',
        reserved_cost_usd=Decimal('0') if denied else maximum,
        actual_cost_usd=Decimal('0') if denied else None,
        result=result.as_record() if result else None,created_at=now,deadline=request.deadline,
        finished_at=now if denied else None))
    return get_call(connection,request.run_id)


def claim(connection,run_id):
    row=get_call(connection,run_id,True)
    if row is None:raise ValueError('Run not found')
    if row['state']!='reserved':return None
    if clock(connection)>=row['deadline']:
        request=ProviderRequest.from_record(row['request'])
        result=ProviderResult(None,request.config.provider_id,run_id,response_id('LOCAL',run_id),status='timeout',
            input_tokens=0,output_tokens=0,error_kind='deadline_before_dispatch',error_message='No dispatch: deadline expired')
        connection.execute(db.provider_calls.update().where(db.provider_calls.c.run_id==run_id).values(
            state='settled',result=result.as_record(),actual_cost_usd=Decimal('0'),finished_at=clock(connection)))
        return None
    connection.execute(db.provider_calls.update().where(db.provider_calls.c.run_id==run_id).values(state='dispatching',dispatch_count=1))
    return get_call(connection,run_id)


def settle(connection,run_id,result,finished_at):
    first=get_call(connection,run_id)
    if first is None:raise ValueError('Run not found')
    get_budget(connection,first['budget_id'],True)
    row=get_call(connection,run_id,True)
    if row['state']!='dispatching':return row
    request=ProviderRequest.from_record(row['request'])
    result=validate_result(request,result)
    known=result.input_tokens is not None and result.output_tokens is not None
    if finished_at>row['deadline']:
        result=replace(result,status='timeout',selected_choice=None,
                       error_kind='late_result',error_message='Outcome arrived after the dispatch deadline')
    cost=request.pricing.cost(result.input_tokens,result.output_tokens) if known else None
    connection.execute(db.provider_calls.update().where(db.provider_calls.c.run_id==run_id).values(
        state='settled' if known else 'uncertain',actual_cost_usd=cost,result=result.as_record(),finished_at=finished_at))
    return get_call(connection,run_id)


def recover_expired(connection,run_id):
    row=get_call(connection,run_id,True)
    if row is None:raise ValueError('Run not found')
    if row['state']=='dispatching' and row['deadline']<=clock(connection):
        req=ProviderRequest.from_record(row['request'])
        result=ProviderResult(None,req.config.provider_id,run_id,response_id('LOCAL',run_id),status='timeout',
            input_tokens=None,output_tokens=None,error_kind='unknown_after_restart',
            error_message='No redispatch; unknown outcome retains maximum reservation')
        connection.execute(db.provider_calls.update().where(db.provider_calls.c.run_id==run_id).values(
            state='uncertain',result=result.as_record(),finished_at=clock(connection)))
    return get_call(connection,run_id)
