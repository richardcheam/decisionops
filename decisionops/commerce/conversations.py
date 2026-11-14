"""Typed conversation routing. Server state owns scope; no model business authority."""
from dataclasses import dataclass
import json
import re
import sqlalchemy as sa
from . import schema as db
from .cases import clock,identifier,show_case

KINDS=('weekly_deliveries','problems','investigate','status','clarify')

@dataclass(frozen=True)
class Intent:
    kind: str
    order_id: str | None=None
    def __post_init__(self):
        if self.kind not in KINDS or self.order_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',self.order_id):
            raise ValueError('Invalid conversation intent')

class DemoRouter:
    def choose(self,message):
        text=message.lower().replace('’',"'")
        order=re.search(r'\b(?:ORD|DEMO)-[A-Za-z0-9_-]+\b',message,re.I)
        bound=order.group().upper() if order else None
        if 'how many' in text and any(w in text for w in ('deliver','week')):kind='weekly_deliveries'
        elif any(w in text for w in ('problem','exception')):kind='problems'
        elif any(w in text for w in ('fix','investigate')):kind='investigate'
        elif any(w in text for w in ('missing','status','progress')):kind='status'
        else:kind='clarify'
        return Intent(kind,bound)

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
    from .adaptive_investigations import snapshot,row
    from .adaptive_tools import read_tool,DEPENDENCIES
    from .adaptive_evidence import History
    from .read_tools import AssessmentRequest
    from .execution import reconcile
    operation=c.execute(sa.select(db.operations.c.id).where(db.operations.c.case_id==case['id'])).scalar_one_or_none()
    if operation:
        verified=reconcile(c,operation)
        return {'intent':'status','text':'Replacement verified.' if verified['status']=='verified' else 'Replacement requires reconciliation.', 'operation':verified}
    investigation=view(c,case['id'])
    if not investigation:return {'intent':'status','text':'No saved investigation. Choose Fix this to start.'}
    run=row(c,investigation['id']);history=snapshot(c,run)[0];now=clock(c)
    # Terminal case statuses legitimately differ from active run state, so compare
    # generation/request, then verify evidence and source versions without writes.
    stale=(run['generation']!=case['generation'] or run['request']!=case['request'])
    invalid=[o.id for o in history.active() if history.invalid_reason(o,now) or history.content_conflict(o.record()['tool'])]
    fresh=History(run['request'])
    for tool in DEPENDENCIES:
        active=history.active(tool)
        if not active:continue
        try:
            original=history.select(tool,now)
            current=read_tool(c,tool,AssessmentRequest(**run['request']),fresh,now,
                dependencies=tuple(fresh.select(dep,now) for dep in DEPENDENCIES[tool]))
            fresh.append(current)
            if original.version!=current.version:invalid.extend(o.id for o in active)
        except ValueError:invalid.extend(o.id for o in active)
    stale=stale or bool(invalid)
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

def message(c,engine,conversation,text,request_id,mode,router=None,now=None):
    previous=c.execute(sa.select(db.conversation_messages).where(sa.and_(
        db.conversation_messages.c.conversation_id==conversation['id'],db.conversation_messages.c.request_id==request_id))).mappings().one_or_none()
    if previous:
        if previous['message']!=text:raise ValueError('Message request identity reused')
        return previous['response']
    intent=(router or DemoRouter()).choose(text)
    selected=conversation['selected_case_id'];links=[];store=conversation['store_id']
    if intent.order_id:
        matches=c.execute(sa.select(db.cases).join(db.orders,db.orders.c.id==db.cases.c.order_id).where(
            sa.and_(db.orders.c.store_id==store,db.orders.c.id==intent.order_id)).order_by(db.cases.c.created_at)).mappings().all()
        links=[{'case_id':r['id'],'order_id':r['order_id'],'shipment_id':r['request']['shipment_id']} for r in matches]
        if len(matches)==1:
            selected=matches[0]['id'];select(c,conversation,selected)
        else:
            intent=Intent('clarify');selected=None
            select(c,conversation,None)
    result={'intent':intent.kind,'selected_case_id':selected}
    if intent.kind=='weekly_deliveries':
        from .delivery import report
        value=report(c,store,now)
        result.update(report=value,case_links=value['case_links'],text=f"{value['completed']} deliveries completed this week ({value['start']} to {value['end']}, Europe/Paris).")
    elif intent.kind=='problems':
        from .delivery import queue
        rows=queue(c,store,now)
        result.update(text=f'{len(rows)} delivery exceptions need attention. In-app case updates are shown in the queue.',case_links=[{k:r[k] for k in ('case_id','order_id','shipment_id')} for r in rows])
    elif intent.kind in ('status','investigate') and selected:
        case=authorized_case(c,selected,store)
        if case is None:raise LookupError('Case not found')
        if intent.kind=='investigate' and case['status'] in ('open','needs_review','blocked','escalated','rejected'):
            # A completed run is never replaced just to answer a follow-up.
            existing=c.execute(sa.select(db.adaptive_runs.c.id).where(db.adaptive_runs.c.case_id==selected)).first()
            if existing:result.update(status(c,case))
            else:
                from .staff_investigations import enqueue
                run=enqueue(c,engine,selected,text,'CHAT-'+conversation['id']+'-'+request_id,case['generation'],mode)
                result.update(text='Investigation requested. The coordinator binds the case, then the shipment and order specialists gather evidence.',investigation={'id':run['id'],'state':run['state']})
        else:result.update(status(c,case))
    else:
        result.update(intent='clarify',text='Select the exact case and parcel to continue.' if not links else 'Several cases or parcels match. Select the exact case.',case_links=links)
    # Serialize timestamps once so replay returns byte-equivalent JSON values.
    from .adaptive_evidence import canonical
    result=json.loads(canonical(result))
    c.execute(db.conversation_messages.insert().values(conversation_id=conversation['id'],request_id=request_id,
        message=text,response=result,created_at=clock(c)))
    return result
