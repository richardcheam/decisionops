"""Typed conversation routing. Server state owns scope; no model business authority."""
from dataclasses import dataclass
from datetime import datetime
import json
import re
import sqlalchemy as sa
from . import schema as db
from .cases import clock,identifier,show_case

from .role_actions import STAFF_KINDS as KINDS,StaffAction as Intent,DemoStaffRouter as DemoRouter,explicit_orders

STAFF_HELP = (
    'I can show delivery totals, list parcels that need attention, investigate a case, '
    'or tell you what is still missing. Try “Which parcels are late?” '
    'or open a case and ask “What’s still missing?” An authorized staff member approves '
    'and confirms replacements from the case screen.'
)

class BoundedRouter:
    """Optional transport gets bounded text and emits exactly one typed intent.

    One decision, at most five seconds; late output is discarded. Integrations
    must also bound their transport I/O. No tool or authority fields are accepted.
    """
    def __init__(self,transport,*,timeout_seconds=1):
        if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=5:raise ValueError('Routing deadline must be 0..5 seconds')
        self.transport=transport;self.timeout_seconds=timeout_seconds
    def choose(self,message):
        if not isinstance(message,str) or len(message.encode())>2000:raise ValueError('Message too large')
        from queue import Queue,Empty
        from threading import Thread
        results=Queue(maxsize=1)
        def invoke():
            try:results.put(('result',self.transport({'message':message,'allowed_intents':list(KINDS)})))
            except Exception as error:results.put(('error',type(error).__name__))
        Thread(target=invoke,daemon=True).start()
        try:kind,raw=results.get(timeout=self.timeout_seconds)
        except Empty:raise TimeoutError('Routing decision deadline reached') from None
        if kind=='error':raise ValueError('Routing transport failed')
        if isinstance(raw,str):
            if len(raw.encode())>2048:raise ValueError('Routing reply too large')
            raw=json.loads(raw)
        if not isinstance(raw,dict) or not set(raw)<= {'kind','order_id'}:raise ValueError('Invalid routing fields')
        return Intent(**raw)

def create(c,actor,store_id):
    identity=identifier('CHAT')
    c.execute(db.conversations.insert().values(id=identity,actor=actor,store_id=store_id,created_at=clock(c)))
    return {'id':identity,'selected_case_id':None}

def owned(c,identity,actor,store_id):
    row=c.execute(sa.select(db.conversations).where(sa.and_(db.conversations.c.id==identity,
        db.conversations.c.actor==actor,db.conversations.c.store_id==store_id)).with_for_update()).mappings().one_or_none()
    return dict(row) if row else None

def authorized_case(c,case_id,store_id):
    return c.execute(sa.select(db.cases).join(db.orders,db.orders.c.id==db.cases.c.order_id).where(
        sa.and_(db.cases.c.id==case_id,db.orders.c.store_id==store_id))).mappings().one_or_none()

def select(c,conversation,case_id):
    if case_id is not None and authorized_case(c,case_id,conversation['store_id']) is None:raise LookupError('Case not found')
    c.execute(db.conversations.update().where(db.conversations.c.id==conversation['id']).values(selected_case_id=case_id))
    return {'id':conversation['id'],'selected_case_id':case_id}

def status(c,case):
    from .staff_investigations import view
    from .execution import reconcile
    operation=c.execute(sa.select(db.operations.c.id).where(db.operations.c.case_id==case['id'])).scalar_one_or_none()
    if operation:
        verified=reconcile(c,operation)
        return {'intent':'status','text':'Replacement verified.' if verified['status']=='verified' else 'Replacement requires reconciliation.', 'operation':verified}
    investigation=view(c,case['id'])
    if not investigation or investigation.get('historical'):
        if case['proposal_id']:
            from .investigations import recheck
            check=recheck(c,case['proposal_id'],clock(c))
            current=check['status']=='valid_for_review'
            text=('Exact proposal approved. Separate confirmation is required to create the replacement.'
                if case['status']=='approved' else 'Replacement proposal ready for exact staff approval.') if current else 'Saved proposal evidence expired or source records changed. Explicitly refresh before relying on it.'
            return {'intent':'status','text':text,'proposal_id':case['proposal_id'],'evidence_current':current}
        if case['investigation_id']:
            return {'intent':'status','text':'Saved rules investigation requires review. Open the case for its recorded findings; explicitly refresh to establish current evidence.', 'evidence_current':False}
        return {'intent':'status','text':'No saved investigation yet. Ask “Investigate this case” to check the carrier records, previous compensation, and stock.'}
    if investigation['reason']=='invalid_committed_evidence':
        return {'intent':'status','text':'Saved evidence failed validation and requires staff review. No replacement proposal is authorized.',
            'investigation':investigation,'evidence_current':False}
    # The shared view reauthorizes generation/scope and compares every committed
    # observation with current sources for active and terminal runs alike.
    stale=not investigation['evidence_current']
    if stale:
        for evidence in investigation['evidence']:
            evidence['value']=None;evidence['applicability']='refresh_required'
        investigation['evidence_current']=False
        investigation['facts']={fact:None for fact in investigation['facts']}
        text='Saved evidence expired or source records changed. Explicitly refresh the investigation before relying on it.'
    elif investigation['state']=='active':text='Investigation in progress. Saved checks are shown below.'
    elif case['status']=='approved':text='Exact proposal approved. Separate confirmation is required to create the replacement.'
    elif case['proposal_id']:text='Replacement proposal ready for exact staff approval.'
    else:text='Investigation needs review. Missing: '+(', '.join(investigation['unknowns']) or investigation['reason'] or 'staff decision')
    return {'intent':'status','text':text,'investigation':investigation,'evidence_current':not stale}

def message(c,engine,conversation,text,request_id,mode,router=None,now=None,*,model=None):
    previous=c.execute(sa.select(db.conversation_messages).where(sa.and_(
        db.conversation_messages.c.conversation_id==conversation['id'],db.conversation_messages.c.request_id==request_id))).mappings().one_or_none()
    if previous:
        if previous['message']!=text:raise ValueError('Message request identity reused')
        return previous['response']
    references=explicit_orders(text)
    # Scope ambiguity is resolved by staff, before any configured router can
    # choose a case or request an investigation on their behalf.
    if len(references)>1:
        intent=Intent('clarify')
    else:
        intent=(router or DemoRouter()).choose(text)
    if len(references)==1:
        intent=Intent(intent.kind,references[0])
    elif not references and intent.order_id is not None:
        # A router chooses an intent, never a new case binding. Without an
        # explicit staff reference, keep the server-owned session selection.
        intent=Intent(intent.kind)
    selected=conversation['selected_case_id'];links=[];store=conversation['store_id']
    if len(references)>1:
        matches=c.execute(sa.select(db.cases).join(db.orders,db.orders.c.id==db.cases.c.order_id).where(
            sa.and_(db.orders.c.store_id==store,db.orders.c.id.in_(references)))
            .order_by(db.cases.c.order_id,db.cases.c.created_at)).mappings().all()
        links=[{'case_id':r['id'],'order_id':r['order_id'],'shipment_id':r['request']['shipment_id']} for r in matches]
        selected=None;select(c,conversation,None)
    elif intent.order_id:
        matches=c.execute(sa.select(db.cases).join(db.orders,db.orders.c.id==db.cases.c.order_id).where(
            sa.and_(db.orders.c.store_id==store,db.orders.c.id==intent.order_id)).order_by(db.cases.c.created_at)).mappings().all()
        links=[{'case_id':r['id'],'order_id':r['order_id'],'shipment_id':r['request']['shipment_id']} for r in matches]
        if len(matches)==1:
            selected=matches[0]['id'];select(c,conversation,selected)
        else:
            intent=Intent('clarify');selected=None
            select(c,conversation,None)
    result={'intent':intent.kind,'selected_case_id':selected}
    if intent.kind=='help':
        result.update(text=STAFF_HELP)
    elif intent.kind=='weekly_deliveries':
        from .delivery import report
        value=report(c,store,now)
        result.update(report=value,case_links=value['case_links'],text=f"{value['completed']} deliveries completed this week ({value['start']} to {value['end']}, Europe/Paris).")
    elif intent.kind in ('problems','overdue'):
        from .delivery import queue
        rows=queue(c,store,now)
        if intent.kind=='overdue':
            as_of=clock(c,now)
            rows=[row for row in rows if datetime.fromisoformat(row['promised_at']) < as_of]
            text_reply=f'There are {len(rows)} overdue parcels in the exception queue.'
        else:
            text_reply=f'{len(rows)} delivery exceptions need attention. In-app case updates are shown in the queue.'
        result.update(text=text_reply,case_links=[{k:r[k] for k in ('case_id','order_id','shipment_id')} for r in rows])
    elif intent.kind in ('status','investigate') and selected:
        case=authorized_case(c,selected,store)
        if case is None:raise LookupError('Case not found')
        result['case_generation']=case['generation']
        if intent.kind=='investigate' and case['status'] in ('open','needs_review','blocked','escalated','rejected'):
            # A completed run is never replaced just to answer a follow-up.
            existing=c.execute(sa.select(db.adaptive_runs.c.id).where(db.adaptive_runs.c.case_id==selected)).first()
            if existing:result.update(status(c,case))
            else:
                from .staff_investigations import enqueue
                run=enqueue(c,engine,selected,text,'CHAT-'+conversation['id']+'-'+request_id,case['generation'],mode,model=model)
                result.update(text='Investigation requested. The coordinator binds the case, then the shipment and order specialists gather evidence.',investigation={'id':run['id'],'state':run['state']})
        else:result.update(status(c,case))
    elif intent.kind=='clarify' and not references:
        result.update(text=STAFF_HELP)
    else:
        result.update(intent='clarify',text='Select the exact case and parcel to continue.' if not links else 'Several cases or parcels match. Select the exact case.',case_links=links)
    # Serialize timestamps once so replay returns byte-equivalent JSON values.
    from .adaptive_evidence import canonical
    result=json.loads(canonical(result))
    c.execute(db.conversation_messages.insert().values(conversation_id=conversation['id'],request_id=request_id,
        message=text,response=result,created_at=clock(c)))
    return result
