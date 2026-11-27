"""Authenticated single-store API; background work is queued, never run on polling."""
from contextlib import asynccontextmanager, contextmanager
import hmac
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg import Error as PsycopgError
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from . import schema as db
from .cases import open_case, show_case, review_case, escalate_case, lock_case, identifier
from .role_actions import ModelActionAdapter, ModelUnavailable
from .jobs import enqueue, get_job
from .execution import reconcile
from .read_tools import AssessmentRequest


class StrictBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class CaseRequest(StrictBody):
    order_id: Annotated[str,Field(min_length=1,max_length=128)]
    shipment_id: Annotated[str,Field(min_length=1,max_length=128)]
    items: Annotated[dict[Annotated[str,Field(min_length=1,max_length=128)],Annotated[int,Field(ge=1,le=1000)]],Field(min_length=1,max_length=100)]


class ReviewRequest(StrictBody):
    generation: Annotated[int,Field(ge=1)]
    proposal_id: Annotated[str,Field(min_length=1,max_length=128)]
    content_hash: Annotated[str,Field(pattern='^[0-9a-f]{64}$')]
    decision: Literal['approve','reject']


class ExecutionRequest(StrictBody):
    operation_id: Annotated[str,Field(min_length=1,max_length=128)]


class EscalationRequest(StrictBody):
    reason: Annotated[str,Field(min_length=1,max_length=500)]


class ShipmentReport(StrictBody):
    report: Annotated[str,Field(min_length=1,max_length=2000)]
    request_id: Annotated[str,Field(min_length=1,max_length=128)]
    expected_generation: Annotated[int,Field(ge=0)]
    @field_validator('report')
    @classmethod
    def bounded_report(cls,value):
        if not value.strip() or len(value.encode('utf-8'))>2000:raise ValueError('Report must contain 1..2000 UTF-8 bytes')
        return value


class ConversationSelection(StrictBody):
    case_id: Annotated[str,Field(min_length=1,max_length=128)] | None


class ConversationMessage(StrictBody):
    message: Annotated[str,Field(min_length=1,max_length=2000)]
    request_id: Annotated[str,Field(min_length=1,max_length=128)]
    @field_validator('message')
    @classmethod
    def bounded_message(cls,value):
        if not value.strip() or len(value.encode('utf-8'))>2000:raise ValueError('Message exceeds bound')
        return value


def create_app(engine=None,*,password=None,username=None,store_id=None,origins=None,staff_investigation_mode=None,staff_accounts=None,demo_clock=None,conversation_router=None,customer_accounts=None,customer_router=None,action_adapter=None):
    from .staff_investigations import MODES
    staff_investigation_mode=staff_investigation_mode or os.environ.get('COMMERCE_STAFF_INVESTIGATION_MODE','rules')
    if staff_investigation_mode not in MODES:raise ValueError('Unknown staff investigation mode')
    model_name = None
    if staff_investigation_mode == 'llm':
        if any(adapter is not None for adapter in (action_adapter, conversation_router, customer_router)):
            raise ValueError('LLM mode uses the configured local model')
        from .local_llm import LocalModel
        model = LocalModel.from_environment()
        model_name = model.model
        action_adapter = ModelActionAdapter(model.route, timeout_seconds=5, fallback=False)
    if action_adapter is not None:
        if conversation_router is not None or customer_router is not None:raise ValueError('Configure one action adapter')
        conversation_router=action_adapter.staff();customer_router=action_adapter.customer()
    session_mode = 'local_llm' if model_name else 'fictional_store_rules'
    password=password if password is not None else os.environ.get('COMMERCE_STAFF_PASSWORD','')
    username=username or os.environ.get('COMMERCE_STAFF_USERNAME','operator')
    store_id=store_id or os.environ.get('COMMERCE_STORE_ID','demo-store')
    origins=origins if origins is not None else set(os.environ.get('COMMERCE_ORIGINS','http://127.0.0.1:8080,http://localhost:8080').split(','))
    if len(password)<16 or not 1<=len(username)<=128:
        raise ValueError('Configure a staff password of at least 16 characters and a bounded username before startup')
    accounts={username:{'password':password,'role':'approver'}}
    staff_accounts=dict(staff_accounts or {})
    helper_password=os.environ.get('COMMERCE_HELPER_PASSWORD')
    if helper_password:staff_accounts.setdefault('staff',{'password':helper_password,'role':'staff'})
    for name,account in staff_accounts.items():
        if name==username or not 1<=len(name)<=128 or account.get('role') not in ('staff','approver') or len(account.get('password',''))<16:
            raise ValueError('Invalid local staff account')
        accounts[name]=dict(account)
    owned=engine is None
    engine=engine or database_engine()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned:
            engine.dispose()

    app=FastAPI(title='DecisionOps Commerce',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    @app.middleware('http')
    async def private_responses(request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    basic=HTTPBasic(auto_error=False)

    def staff(credentials: HTTPBasicCredentials | None=Depends(basic)):
        if credentials is None:
            raise HTTPException(401,'Authentication required',headers={'WWW-Authenticate':'Basic realm="Commerce"'})
        account=accounts.get(credentials.username)
        user_ok=account is not None
        password_ok=hmac.compare_digest(credentials.password.encode(),(account['password'] if account else password).encode())
        if not (user_ok and password_ok):
            raise HTTPException(401,'Invalid staff credentials',headers={'WWW-Authenticate':'Basic realm="Commerce"'})
        return credentials.username

    def approver(actor: str=Depends(staff)):
        if accounts[actor]['role']!='approver':raise HTTPException(403,'Approver permission required')
        return actor

    def mutation(request: Request):
        if request.headers.get('content-type','').lower().split(';',1)[0].strip()!='application/json':
            raise HTTPException(415,'Use application/json')
        origin=request.headers.get('origin')
        if origin is not None and origin not in origins:
            raise HTTPException(403,'Origin is not permitted')

    @contextmanager
    def transaction(readonly=False):
        with engine.connect() as connection:
            if not readonly:
                connection=connection.execution_options(isolation_level='READ COMMITTED')
            with connection.begin():
                if readonly:
                    connection.exec_driver_sql('SET TRANSACTION READ ONLY')
                connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                yield connection

    def authorize_order(connection,order_id,lock=False):
        query=sa.select(db.orders.c.id).where(sa.and_(db.orders.c.id==order_id,db.orders.c.store_id==store_id))
        if lock:
            query=query.with_for_update()
        found=connection.execute(query).first()
        if not found:
            raise HTTPException(404,'Order not found')

    def authorize_case(connection,case_id,lock=False):
        query=sa.select(db.cases.c.order_id).where(db.cases.c.id==case_id)
        if lock:
            query=query.with_for_update()
        order=connection.execute(query).scalar_one_or_none()
        if order is None:
            raise HTTPException(404,'Case not found')
        authorize_order(connection,order,lock)

    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(PsycopgError)
    async def unavailable(request,error):
        return JSONResponse(status_code=503,content={'detail':'Database unavailable. Check PostgreSQL readiness and migrations.'})

    @app.exception_handler(ModelUnavailable)
    async def model_unavailable(request,error):
        return JSONResponse(status_code=503,content={'detail':'Local assistant unavailable. Check the model and try again.'})

    @app.exception_handler(ValueError)
    async def conflict(request,error):
        return JSONResponse(status_code=409,content={'detail':str(error)})

    @app.get('/health')
    def health():
        from .schema_readiness import validate_readiness,SchemaNotReady
        try:
            with transaction(True) as connection:validate_readiness(connection)
        except SchemaNotReady:
            raise HTTPException(503,'Business schema is not ready for this release; check migrations and schema compatibility') from None
        return {'status':'ready','mode':session_mode}

    router=APIRouter(prefix='/api',dependencies=[Depends(staff)])

    @router.get('/session')
    def session(actor: str=Depends(staff)):
        return {'username':actor,'store_id':store_id,'mode':session_mode,'role':accounts[actor]['role']}

    @router.get('/deliveries')
    def delivery_report():
        from .delivery import report
        with transaction(True) as c:return report(c,store_id,demo_clock() if demo_clock else None)

    @router.get('/exceptions')
    def exception_queue():
        from .delivery import queue
        with transaction(True) as c:return queue(c,store_id,demo_clock() if demo_clock else None)

    @router.post('/conversations',status_code=201,dependencies=[Depends(mutation)])
    def conversation_create(body: StrictBody,actor: str=Depends(staff)):
        from .conversations import create
        with transaction() as c:return create(c,actor,store_id)

    def conversation_owned(c,identity,actor):
        from .conversations import owned
        found=owned(c,identity,actor,store_id)
        if found is None:raise HTTPException(404,'Conversation not found')
        return found

    @router.post('/conversations/{identity}/select',dependencies=[Depends(mutation)])
    def conversation_select(identity: str,body: ConversationSelection,actor: str=Depends(staff)):
        from .conversations import select
        with transaction() as c:
            conversation=conversation_owned(c,identity,actor)
            if body.case_id:authorize_case(c,body.case_id)
            return select(c,conversation,body.case_id)

    @router.post('/conversations/{identity}/messages',dependencies=[Depends(mutation)])
    def conversation_message(identity: str,body: ConversationMessage,actor: str=Depends(staff)):
        from .conversations import message
        with transaction() as c:
            conversation=conversation_owned(c,identity,actor)
            if conversation['selected_case_id']:authorize_case(c,conversation['selected_case_id'])
            return message(c,engine,conversation,body.message,body.request_id,staff_investigation_mode,
                router=conversation_router,now=demo_clock() if demo_clock else None,model=model_name)

    @router.get('/orders')
    def orders():
        with transaction(True) as connection:
            result=[]
            for row in connection.execute(sa.select(db.orders).where(db.orders.c.store_id==store_id).order_by(db.orders.c.id).limit(100)).mappings():
                lines=[dict(item) for item in connection.execute(sa.select(db.order_lines).where(db.order_lines.c.order_id==row['id'])).mappings()]
                shipments=[dict(item) for item in connection.execute(sa.select(db.shipments).where(db.shipments.c.order_id==row['id'])).mappings()]
                result.append({'id':row['id'],'currency':row['currency'],'lines':lines,'shipments':shipments})
        return result

    @router.get('/cases')
    def cases():
        with transaction(True) as connection:
            query=sa.select(db.cases).join(db.orders,db.cases.c.order_id==db.orders.c.id).where(db.orders.c.store_id==store_id).order_by(db.cases.c.updated_at.desc(),db.cases.c.id).limit(100)
            return [dict(row) for row in connection.execute(query).mappings()]

    @router.post('/cases',status_code=201,dependencies=[Depends(mutation)])
    def create_case(body: CaseRequest):
        with transaction() as connection:
            authorize_order(connection,body.order_id,True)
            result=open_case(connection,AssessmentRequest(**body.model_dump()))
        return result

    @router.get('/cases/{case_id}')
    def case_detail(case_id: str):
        with transaction(True) as connection:
            authorize_case(connection,case_id)
            result=show_case(connection,case_id)
            parcel=connection.execute(sa.select(db.delivery_parcels).where(sa.and_(
                db.delivery_parcels.c.shipment_id==result['request']['shipment_id'],
                db.delivery_parcels.c.store_id==store_id))).mappings().one_or_none()
            result['delivery']=None
            if parcel:
                from .delivery import timeline
                result['delivery']={**dict(parcel),'carrier_events':timeline(connection,store_id,parcel['shipment_id'])}
            job=connection.execute(sa.select(db.jobs.c.id,db.jobs.c.status,db.jobs.c.action,db.jobs.c.error_kind).where(
                db.jobs.c.case_id==case_id).order_by(db.jobs.c.created_at.desc(),db.jobs.c.id).limit(1)).mappings().one_or_none()
            result['latest_job']=dict(job) if job else None
            result['assessment']=None
            if result['investigation_id']:
                result['assessment']=connection.execute(sa.select(db.investigations.c.assessment).where(db.investigations.c.id==result['investigation_id'])).scalar_one()
            operation=connection.execute(sa.select(db.operations.c.id).where(db.operations.c.case_id==case_id)).scalar_one_or_none()
            result['operation']=reconcile(connection,operation) if operation else None
            from .staff_investigations import view
            result['shipment_investigation']=view(connection,case_id)
            investigation=result['shipment_investigation']
            if investigation and not investigation.get('historical') and (investigation['state']=='active' or not result['assessment']):
                result['assessment']={'facts':investigation['facts'],'decision':{'unknowns':investigation['unknowns'],'blockers':investigation['blockers'],'status':'needs_review'},'read_tools':[]}
            if investigation and not investigation.get('historical') and investigation['state']=='active':
                result['latest_job']={'id':investigation['id'],'status':investigation['job_status'],'action':'shipment_investigation','error_kind':None}
        return result

    @router.post('/cases/{case_id}/investigate',status_code=202,dependencies=[Depends(mutation)])
    def investigate_case_job(case_id: str,body: StrictBody):
        with transaction() as connection:
            authorize_case(connection,case_id,True)
            if model_name:
                from .staff_investigations import enqueue as start
                case = lock_case(connection, case_id)
                run = start(connection,engine,case_id,'Staff requested a case check.',
                            identifier('STAFF-CHECK'),case['generation'],staff_investigation_mode,model=model_name)
                return {'run_id':run['id'],'state':run['state']}
            result=enqueue(connection,case_id,'investigate')
        result.pop('token',None)
        return result

    @router.post('/cases/{case_id}/shipment-investigation',status_code=202,dependencies=[Depends(mutation)])
    def shipment_investigation(case_id: str,body: ShipmentReport):
        from .staff_investigations import enqueue as start
        with transaction() as connection:
            authorize_case(connection,case_id,True)
            result=start(connection,engine,case_id,body.report,body.request_id,body.expected_generation,staff_investigation_mode,model=model_name)
            return {'run_id':result['id'],'state':result['state']}

    @router.post('/cases/{case_id}/review',dependencies=[Depends(mutation)])
    def review(case_id: str,body: ReviewRequest,actor: str=Depends(approver)):
        with transaction() as connection:
            authorize_case(connection,case_id,True)
            result=review_case(connection,case_id,body.generation,body.proposal_id,body.content_hash,body.decision,actor=actor)
        return result

    @router.post('/cases/{case_id}/escalate',dependencies=[Depends(mutation)])
    def escalate(case_id: str,body: EscalationRequest):
        with transaction() as connection:
            authorize_case(connection,case_id,True)
            result=escalate_case(connection,case_id,body.reason)
        return result

    @router.post('/cases/{case_id}/execute',status_code=202,dependencies=[Depends(mutation)])
    def execute_job(case_id: str,body: ExecutionRequest,actor: str=Depends(approver)):
        with transaction() as connection:
            authorize_case(connection,case_id,True)
            result=enqueue(connection,case_id,'execute',body.operation_id)
        result.pop('token',None)
        return result

    @router.get('/jobs/{job_id}')
    def job_detail(job_id: str):
        with transaction(True) as connection:
            exists=connection.execute(sa.select(db.jobs.c.id).where(db.jobs.c.id==job_id)).first()
            if not exists:
                raise HTTPException(404,'Job not found')
            result=get_job(connection,job_id)
            authorize_case(connection,result['case_id'])
        result.pop('token',None)
        return result

    from . import returns as return_service

    class ReturnProposal(StrictBody):
        proposal_hash: Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]

    def return_transaction(fn, readonly=False):
        try:
            with transaction(readonly) as connection:
                return fn(connection)
        except LookupError:
            raise HTTPException(404, 'Return case not found') from None

    def return_clock():
        return demo_clock() if demo_clock else None

    @router.get('/returns')
    def return_queue():
        return return_transaction(lambda c: return_service.staff_queue(c, store_id), True)

    @router.get('/returns/{case_id}')
    def return_detail(case_id: str):
        return return_transaction(lambda c: return_service.staff_case(c, store_id, case_id), True)

    @router.post('/returns/{case_id}/investigate', dependencies=[Depends(mutation)])
    def investigate_return(case_id: str, body: StrictBody):
        return return_transaction(lambda c: return_service.investigate(c, store_id, case_id, return_clock()))

    @router.post('/returns/{case_id}/approve', dependencies=[Depends(mutation)])
    def approve_return(case_id: str, body: ReturnProposal, actor: str = Depends(approver)):
        return return_transaction(lambda c: return_service.approve(c, store_id, case_id, body.proposal_hash,
                                                                    actor, return_clock()))

    @router.post('/returns/{case_id}/confirm', dependencies=[Depends(mutation)])
    def confirm_return(case_id: str, body: ReturnProposal, actor: str = Depends(approver)):
        return return_transaction(lambda c: return_service.confirm(c, store_id, case_id, body.proposal_hash,
                                                                    actor, return_clock()))

    app.include_router(router)
    from .customer_api import install as install_customer_api
    install_customer_api(app,transaction=transaction,mutation=mutation,StrictBody=StrictBody,
        ConversationMessage=ConversationMessage,store_id=store_id,staff_names=set(accounts),
        accounts=customer_accounts,router=customer_router,demo_clock=demo_clock)
    web_dist=os.environ.get('COMMERCE_WEB_DIST')
    if web_dist:
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
        from pathlib import Path
        @app.get('/customer',include_in_schema=False)
        @app.get('/staff',include_in_schema=False)
        def role_entry():return FileResponse(Path(web_dist)/'index.html')
        app.mount('/',StaticFiles(directory=web_dist,html=True),name='workspace')
    return app
