"""Task-bound API money companion to the unchanged adaptive duration ledger."""
from decimal import Decimal
import sqlalchemy as sa
from . import schema as db
from .cases import clock
from .adaptive_recommendations import TASK
from .api_decisions import config_for,pricing_for
from .proposals import document_hash

def create_budget(c,config):
    cfg=config_for(config)
    c.execute(db.provider_budgets.insert().values(id=cfg.budget_id,limits={'task':TASK,'config':cfg.record()},pricing=pricing_for(cfg),created_at=clock(c)))

def reserve(c,request,case_id):
    cfg=config_for(request.api)
    budget=c.execute(sa.select(db.provider_budgets).where(db.provider_budgets.c.id==cfg.budget_id).with_for_update()).mappings().one()
    expected=pricing_for(cfg)
    if budget['pricing']!=expected:raise ValueError('API pricing binding mismatch')
    if budget['limits']!={'task':TASK,'config':cfg.record()}:raise ValueError('API budget/config mismatch')
    rows=c.execute(sa.select(db.provider_calls).where(db.provider_calls.c.budget_id==cfg.budget_id)).mappings().all()
    if any(r['request'].get('task')!=TASK for r in rows):raise ValueError('Budget task mismatch')
    maximum=Decimal('0') if len(request.policy.allowed)==1 else cfg.maximum()
    committed=sum((r['actual_cost_usd'] if r['actual_cost_usd'] is not None else r['reserved_cost_usd'] for r in rows),Decimal('0'))
    if len(rows)>=cfg.max_requests or committed+maximum>Decimal(cfg.max_cost_usd):raise ValueError('API budget exhausted')
    record=request.record()
    c.execute(db.provider_calls.insert().values(run_id=request.id,case_id=case_id,budget_id=cfg.budget_id,request=record,request_hash=document_hash(record),state='reserved',reserved_cost_usd=maximum,created_at=clock(c),deadline=request.deadline))

def transition(c,call,state,result=None):
    if not call['request']['configuration'].get('api'):return
    row=c.execute(sa.select(db.provider_calls).where(db.provider_calls.c.run_id==call['id']).with_for_update()).mappings().one()
    if row['request'].get('task')!=TASK:raise ValueError('API reservation task mismatch')
    if row['state'] in ('settled','uncertain'):return
    values={'state':state}
    if state=='dispatching':values['dispatch_count']=int(len(call['request']['features']['allowed_actions'])>1)
    if state=='settled':
        cfg=config_for(call['request']['configuration']['api'])
        usage=result.metadata['usage'] if result.metadata else None
        cost=Decimal('0') if row['dispatch_count']==0 else cfg.cost(**usage)
        values.update(actual_cost_usd=cost,result=result.record(),finished_at=clock(c))
    c.execute(db.provider_calls.update().where(db.provider_calls.c.run_id==call['id']).values(**values))
