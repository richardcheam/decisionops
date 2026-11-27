"""Customer-only API; authentication and ownership are server checks."""
import hmac
import os
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import Field
from . import customer, returns


def install(app,*,transaction,mutation,StrictBody,ConversationMessage,store_id,staff_names,accounts=None,router=None,demo_clock=None):
    configured=dict(accounts or {})
    for name in ('camille','alex'):
        password=os.environ.get('COMMERCE_CUSTOMER_'+name.upper()+'_PASSWORD')
        if password:configured.setdefault(name,{'password':password,'customer_id':name})
    for name,account in configured.items():
        if name in staff_names or not 1<=len(name)<=128 or len(account.get('password',''))<16 or account.get('customer_id') not in ('camille','alex'):
            raise ValueError('Invalid local customer account')
    basic=HTTPBasic(auto_error=False)
    def principal(credentials: HTTPBasicCredentials|None=Depends(basic)):
        account=configured.get(credentials.username) if credentials else None
        # Uniform response; never fall through to staff authentication.
        expected=account['password'] if account else 'unconfigured-fictional-customer'
        supplied=credentials.password if credentials else ''
        matched=hmac.compare_digest(supplied.encode(),expected.encode())
        if not account or not matched:raise HTTPException(401,'Customer authentication required')
        return account['customer_id']
    api=APIRouter(prefix='/customer-api',dependencies=[Depends(principal)])
    class Selection(StrictBody):
        order_id: Annotated[str,Field(min_length=1,max_length=128)]
        shipment_id: Annotated[str,Field(min_length=1,max_length=128)]|None=None
    class ReturnRequest(StrictBody):
        order_id: Annotated[str,Field(min_length=1,max_length=128)]
        variant_id: Annotated[str,Field(min_length=1,max_length=128)]

    def run(fn,readonly=False):
        try:
            with transaction(readonly) as c:return fn(c)
        except LookupError:
            raise HTTPException(404,'Requested customer record not found') from None
    @api.get('/session')
    def session(identity: str=Depends(principal)):
        names={'camille':'Camille Martin','alex':'Alex Bernard'}
        return {'customer_id':identity,'display_name':names[identity],'store_id':store_id,'role':'customer'}
    @api.get('/orders')
    def orders(identity: str=Depends(principal)):
        return run(lambda c:customer.orders(c,identity,store_id),True)
    @api.get('/orders/{order_id}')
    def order(order_id: str,identity: str=Depends(principal)):
        return run(lambda c:customer.order(c,identity,store_id,order_id),True)
    @api.get('/parcels/{shipment_id}')
    def parcel(shipment_id: str,identity: str=Depends(principal)):
        return run(lambda c:customer.parcel(c,identity,store_id,shipment_id),True)
    @api.get('/cases/{case_id}')
    def case(case_id: str,identity: str=Depends(principal)):
        return run(lambda c:customer.case(c,identity,store_id,case_id),True)
    @api.post('/conversations',status_code=201,dependencies=[Depends(mutation)])
    def create(body: StrictBody,identity: str=Depends(principal)):
        return run(lambda c:customer.create(c,identity,store_id))
    @api.get('/conversations/{conversation_id}')
    def conversation(conversation_id: str,identity: str=Depends(principal)):
        return run(lambda c:customer.view(c,conversation_id,identity,store_id),True)
    @api.post('/conversations/{conversation_id}/select',dependencies=[Depends(mutation)])
    def select(conversation_id: str,body: Selection,identity: str=Depends(principal)):
        return run(lambda c:customer.select(c,conversation_id,identity,store_id,body.order_id,body.shipment_id))
    @api.post('/conversations/{conversation_id}/messages',dependencies=[Depends(mutation)])
    def message(conversation_id: str,body: ConversationMessage,identity: str=Depends(principal)):
        return run(lambda c:customer.message(c,conversation_id,identity,store_id,body.message,body.request_id,router))
    @api.get('/returns/eligibility')
    def return_eligibility(order_id: str, variant_id: str | None = None, identity: str=Depends(principal)):
        return run(lambda c:returns.eligibility(c,identity,store_id,order_id,variant_id,
                                               demo_clock() if demo_clock else None),True)

    @api.post('/conversations/{conversation_id}/returns',dependencies=[Depends(mutation)])
    def start_return(conversation_id: str,body: ReturnRequest,identity: str=Depends(principal)):
        return run(lambda c:returns.start(c,identity,store_id,conversation_id,body.order_id,
                                          body.variant_id,demo_clock() if demo_clock else None))

    app.include_router(api)
