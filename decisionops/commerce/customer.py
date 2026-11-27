"""Owned customer conversations; business authority stays with Commerce services."""
import re
import sqlalchemy as sa
from . import schema as db
from .cases import clock, identifier, event
from .role_actions import CustomerAction, DemoCustomerRouter, clear_report_intent, explicit_orders


CUSTOMER_HELP = (
    'I can show what you ordered, help you track a parcel, report it missing, '
    'or check an existing case. I can also explain who can help with returns, '
    'refunds, and order changes. Try “What did I order?” or “How do I return an item?”'
)
SHOP_GUIDANCE = {
    'help': CUSTOMER_HELP,
    'returns_help': (
        'Contact the shop with your order reference and the item you want to return or exchange. '
        'Staff can check whether it qualifies and give you return instructions before you send it back.'
    ),
    'refund_help': (
        'Contact the shop with your order reference and the reason for the request. '
        'Staff can check eligibility or look up your refund status. A refund request here does not issue a refund.'
    ),
    'order_change_help': (
        'For an address change or cancellation, contact the shop as soon as possible with your order reference. '
        'Staff can check whether it is still possible, especially if the order has already shipped.'
    ),
    'support_help': (
        'Contact the shop and include your order reference and a short description of what you need. '
        'If you already reported a missing parcel, include the case reference too.'
    ),
}


def owned_order(c,customer,store,order):
    found=c.execute(sa.select(db.customer_orders.c.order_id).where(
        db.customer_orders.c.customer_id==customer,db.customer_orders.c.store_id==store,
        db.customer_orders.c.order_id==order)).scalar_one_or_none()
    if found is None:raise LookupError('Order not found')
    return found


def parcel(c,customer,store,shipment):
    row=c.execute(sa.select(db.delivery_parcels.c.shipment_id,db.delivery_parcels.c.order_id,
        db.delivery_parcels.c.promised_at,db.shipments.c.carrier_status).join(db.customer_orders,
        sa.and_(db.customer_orders.c.order_id==db.delivery_parcels.c.order_id,
                db.customer_orders.c.store_id==db.delivery_parcels.c.store_id)).join(db.shipments,
        db.shipments.c.id==db.delivery_parcels.c.shipment_id).where(db.customer_orders.c.customer_id==customer,
        db.customer_orders.c.store_id==store,db.delivery_parcels.c.shipment_id==shipment)).mappings().one_or_none()
    if row is None:raise LookupError('Parcel not found')
    return {'shipment_id':row['shipment_id'],'order_id':row['order_id'],
            'promised_at':row['promised_at'],'status':row['carrier_status']}


def order(c,customer,store,identity):
    owned_order(c,customer,store,identity)
    shipments=c.execute(sa.select(db.delivery_parcels.c.shipment_id).where(
        db.delivery_parcels.c.order_id==identity,db.delivery_parcels.c.store_id==store)).scalars()
    return {'id':identity,'parcels':[parcel(c,customer,store,s) for s in shipments]}


def _order_summary(c, order_id, parcel_count):
    lines = c.execute(sa.select(db.order_lines.c.variant_id, db.order_lines.c.quantity).where(
        db.order_lines.c.order_id == order_id).order_by(db.order_lines.c.variant_id))
    items = ', '.join(f"{quantity} × {variant.replace('-', ' ')}" for variant, quantity in lines)
    parcel_label = 'parcel' if parcel_count == 1 else 'parcels'
    text = f'Order {order_id} includes {items or "no recorded items"}. It has {parcel_count} {parcel_label}.'
    return {'intent': 'order_summary', 'text': text}


def orders(c,customer,store):
    identities=c.execute(sa.select(db.customer_orders.c.order_id).where(
        db.customer_orders.c.customer_id==customer,db.customer_orders.c.store_id==store).order_by(db.customer_orders.c.order_id)).scalars()
    return [order(c,customer,store,i) for i in identities]


def case(c,customer,store,identity):
    row=c.execute(sa.select(db.cases).join(db.customer_orders,db.customer_orders.c.order_id==db.cases.c.order_id).where(
        db.cases.c.id==identity,db.customer_orders.c.customer_id==customer,
        db.customer_orders.c.store_id==store)).mappings().one_or_none()
    if row is None:raise LookupError('Case not found')
    # Never return staff assessment, notes, compensation, approval or stock records.
    created=False
    operation=c.execute(sa.select(db.operations.c.id).where(db.operations.c.case_id==identity)).scalar_one_or_none()
    if operation:
        from .execution import reconcile
        created=reconcile(c,operation)['status']=='verified'
    if created:
        text='Your replacement was created. It has not been shipped yet.';status='replacement_created'
    elif operation:
        text='We are checking the replacement result. Please wait for a confirmed update.';status='in_review'
    elif row['status'] in ('needs_review','blocked','rejected','escalated'):
        text='Your report needs a staff review. No replacement has been confirmed.';status='in_review'
    elif row['generation']:
        text='Staff are checking your report. No replacement has been confirmed yet.';status='in_review'
    else:
        text='We received your report. Staff will check what happened.';status='received'
    return {'case_id':identity,'order_id':row['order_id'],'shipment_id':row['request']['shipment_id'],
            'status':status,'text':text,'replacement_created':created,'shipped':False}


def owned_conversation(c,identity,customer,store,lock=False):
    query=sa.select(db.customer_conversations).join(db.customers,db.customers.c.id==db.customer_conversations.c.customer_id).where(db.customer_conversations.c.id==identity,
        db.customer_conversations.c.customer_id==customer,db.customers.c.store_id==store)
    if lock:query=query.with_for_update()
    row=c.execute(query).mappings().one_or_none()
    if row is None:raise LookupError('Conversation not found')
    return dict(row)


def view(c,identity,customer,store):
    conversation=owned_conversation(c,identity,customer,store)
    if conversation['selected_order_id']:owned_order(c,customer,store,conversation['selected_order_id'])
    messages=[{'message':r['message'],'response':r['response']} for r in c.execute(sa.select(db.customer_messages).where(
        db.customer_messages.c.conversation_id==identity).order_by(db.customer_messages.c.created_at,db.customer_messages.c.request_id)).mappings()]
    references=c.execute(sa.select(db.customer_reports.c.case_id).where(db.customer_reports.c.conversation_id==identity).distinct()).scalars()
    from .returns import conversation_cases
    return {'id':identity,'selected_order_id':conversation['selected_order_id'],
        'selected_shipment_id':conversation['selected_shipment_id'],'messages':messages,
        'cases':[case(c,customer,store,i) for i in references],
        'returns':conversation_cases(c,customer,store,identity)}


def create(c,customer,store):
    if c.execute(sa.select(db.customers.c.id).where(db.customers.c.id==customer,db.customers.c.store_id==store)).scalar_one_or_none() is None:raise LookupError('Customer not found')
    identity=identifier('CUSTOMER-CHAT')
    c.execute(db.customer_conversations.insert().values(id=identity,customer_id=customer,created_at=clock(c)))
    return view(c,identity,customer,store)


def select(c,identity,customer,store,order_id,shipment_id):
    owned_conversation(c,identity,customer,store,True)
    owned_order(c,customer,store,order_id)
    if shipment_id and parcel(c,customer,store,shipment_id)['order_id']!=order_id:raise LookupError('Parcel not found')
    c.execute(db.customer_conversations.update().where(db.customer_conversations.c.id==identity).values(
        selected_order_id=order_id,selected_shipment_id=shipment_id))
    return view(c,identity,customer,store)



def message(c,identity,customer,store,text,request_id,router=None):
    conversation=owned_conversation(c,identity,customer,store,True)
    previous=c.execute(sa.select(db.customer_messages).where(db.customer_messages.c.conversation_id==identity,
        db.customer_messages.c.request_id==request_id)).mappings().one_or_none()
    if previous:
        if previous['message']!=text:raise ValueError('Message request identity reused')
        # A replay acknowledges the original report, never replays a verified outcome.
        if previous['response'].get('case_id'):case(c,customer,store,previous['response']['case_id'])
        return previous['response']
    explicit_parcels=tuple(dict.fromkeys(re.findall(r'\bPARCEL-[A-Za-z0-9_-]+',text,re.I)))
    references=explicit_orders(re.sub(r'\bPARCEL-[A-Za-z0-9_-]+','',text,flags=re.I))
    for ref in references:owned_order(c,customer,store,ref)
    for ref in explicit_parcels:parcel(c,customer,store,ref.upper())
    case_refs=tuple(dict.fromkeys(re.findall(r'\bCASE-[A-Za-z0-9_-]+',text,re.I)))
    case_rows=[case(c,customer,store,ref) for ref in case_refs]
    order_id=conversation['selected_order_id'];shipment_id=conversation['selected_shipment_id']
    conflict=False
    if len(case_rows)==1:
        target=case_rows[0]
        conflict=(bool(references) and references[0]!=target['order_id'] or bool(explicit_parcels) and explicit_parcels[0].upper()!=target['shipment_id'])
        if not conflict:order_id=target['order_id'];shipment_id=target['shipment_id']
    ambiguous = len(references)>1 or len(explicit_parcels)>1 or len(case_rows)>1 or conflict
    model_only = getattr(router, 'model_only', False)
    if ambiguous:
        default_action = CustomerAction('clarify')
    elif model_only:
        default_action = router.choose(text)
    else:
        default_action = DemoCustomerRouter().choose(text)
    if ambiguous:
        c.execute(db.customer_conversations.update().where(db.customer_conversations.c.id==identity).values(selected_order_id=None,selected_shipment_id=None))
        result={'intent':'clarify','text':'Which order and parcel do you mean? Please select one.'}
    elif default_action.kind in SHOP_GUIDANCE:
        result={'intent':default_action.kind,'text':SHOP_GUIDANCE[default_action.kind]}
        if default_action.kind == 'returns_help':
            parcel_order = (parcel(c,customer,store,explicit_parcels[0].upper())['order_id']
                            if explicit_parcels else None)
            return_order = references[0] if references else parcel_order or order_id
            if references and parcel_order and references[0] != parcel_order:
                result = {'intent': 'clarify', 'text': 'The order and parcel do not match. Which order should we check?'}
            elif return_order:
                result.update(return_order_id=return_order, text='Choose an item to check if it can be returned.')
            else:
                result['text'] += ' Select an order to check whether an item can be returned.'

    else:
        if references:
            if order_id!=references[0]:shipment_id=None
            order_id=references[0]
        if explicit_parcels:
            found=parcel(c,customer,store,explicit_parcels[0].upper())
            if references and found['order_id']!=order_id:raise LookupError('Parcel not found')
            order_id=found['order_id'];shipment_id=found['shipment_id']
        if not order_id:
            result={'intent':'clarify','text':'Select an order first. ' + CUSTOMER_HELP if model_only else CUSTOMER_HELP}
        else:
            owned_order(c,customer,store,order_id)
            choices=order(c,customer,store,order_id)['parcels']
            if shipment_id is None and len(choices)==1:shipment_id=choices[0]['shipment_id']
            if default_action.kind=='order_summary':
                result=_order_summary(c,order_id,len(choices))
            elif shipment_id is None:
                c.execute(db.customer_conversations.update().where(db.customer_conversations.c.id==identity).values(selected_order_id=order_id,selected_shipment_id=None))
                result={'intent':'clarify','text':'This order has more than one parcel. Which parcel do you mean?',
                        'parcels':[{'shipment_id':r['shipment_id']} for r in choices]}
            else:
                found=parcel(c,customer,store,shipment_id)
                if found['order_id']!=order_id:raise LookupError('Parcel not found')
                c.execute(db.customer_conversations.update().where(db.customer_conversations.c.id==identity).values(
                    selected_order_id=order_id,selected_shipment_id=shipment_id))
                try:
                    action=router.choose(text) if router and not model_only else default_action
                    if not isinstance(action,CustomerAction):raise ValueError('Invalid customer action')
                except (ValueError,TypeError,TimeoutError):action=default_action
                if action.kind=='report_nonreceipt' and not clear_report_intent(text):
                    action=CustomerAction('clarify') if model_only else default_action
                if action.kind=='report_nonreceipt':
                    from .delivery import report_nonreceipt
                    report_nonreceipt(c,store,shipment_id)
                    case_id=c.execute(sa.select(db.delivery_case_links.c.case_id).where(
                        db.delivery_case_links.c.store_id==store,db.delivery_case_links.c.shipment_id==shipment_id)).scalar_one()
                    report_id=identifier('CUSTOMER-REPORT')
                    c.execute(db.customer_reports.insert().values(id=report_id,conversation_id=identity,customer_id=customer,
                        request_id=request_id,case_id=case_id,shipment_id=shipment_id,store_id=store,order_id=order_id,message=text,created_at=clock(c)))
                    event(c,case_id,'customer_report_received',{'report_id':report_id,'message':text},clock(c))
                    result={'intent':'report_nonreceipt','case_id':case_id,
                        'text':f'We received your report. Your case reference is {case_id}. Staff will check what happened.'}
                elif action.kind=='case_status':
                    link=c.execute(sa.select(db.delivery_case_links.c.case_id).where(db.delivery_case_links.c.store_id==store,
                        db.delivery_case_links.c.shipment_id==shipment_id)).scalar_one_or_none()
                    result={'intent':'case_status','text':case(c,customer,store,link)['text'] if link else 'There is no case for this parcel yet.'}
                elif action.kind=='delivery_status':
                    result={'intent':'delivery_status','text':f"The carrier status for your parcel is {found['status'].replace('_',' ')}.",
                        'shipment_id':shipment_id,'status':found['status']}
                elif action.kind=='order_summary':
                    result=_order_summary(c,order_id,len(choices))
                elif action.kind in SHOP_GUIDANCE:
                    result={'intent':action.kind,'text':SHOP_GUIDANCE[action.kind]}
                else:
                    result={'intent':'clarify','text':CUSTOMER_HELP}
    c.execute(db.customer_messages.insert().values(conversation_id=identity,request_id=request_id,message=text,
        response=result,created_at=clock(c)))
    return result
