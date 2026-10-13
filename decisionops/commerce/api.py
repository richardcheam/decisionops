"""Authenticated single-store API; background work is queued, never run on polling."""
from contextlib import asynccontextmanager, contextmanager
import hmac
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from psycopg import Error as PsycopgError
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine
from . import schema as db
from .cases import open_case, show_case, review_case, escalate_case
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


def create_app(engine=None,*,password=None,username=None,store_id=None,origins=None):
    password=password if password is not None else os.environ.get('COMMERCE_STAFF_PASSWORD','')
    username=username or os.environ.get('COMMERCE_STAFF_USERNAME','operator')
    store_id=store_id or os.environ.get('COMMERCE_STORE_ID','demo-store')
    origins=origins if origins is not None else set(os.environ.get('COMMERCE_ORIGINS','http://127.0.0.1:8080,http://localhost:8080').split(','))
    if len(password)<16 or not 1<=len(username)<=128:
        raise ValueError('Configure a staff password of at least 16 characters and a bounded username before startup')
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
        user_ok=hmac.compare_digest(credentials.username.encode(),username.encode())
        password_ok=hmac.compare_digest(credentials.password.encode(),password.encode())
        if not (user_ok and password_ok):
            raise HTTPException(401,'Invalid staff credentials',headers={'WWW-Authenticate':'Basic realm="Commerce"'})
        return username

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

    @app.exception_handler(ValueError)
    async def conflict(request,error):
        return JSONResponse(status_code=409,content={'detail':str(error)})

    @app.get('/health')
    def health():
        with transaction(True) as connection:
            revision=connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
            if revision!='0004':
                raise HTTPException(503,'Apply the current business migration before starting this release')
        return {'status':'ready','mode':'fictional_store_rules'}

    router=APIRouter(prefix='/api',dependencies=[Depends(staff)])

    @router.get('/session')
    def session():
        return {'username':username,'store_id':store_id,'mode':'fictional_store_rules'}

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
            job=connection.execute(sa.select(db.jobs.c.id,db.jobs.c.status,db.jobs.c.action,db.jobs.c.error_kind).where(
                db.jobs.c.case_id==case_id).order_by(db.jobs.c.created_at.desc(),db.jobs.c.id).limit(1)).mappings().one_or_none()
            result['latest_job']=dict(job) if job else None
            result['assessment']=None
            if result['investigation_id']:
                result['assessment']=connection.execute(sa.select(db.investigations.c.assessment).where(db.investigations.c.id==result['investigation_id'])).scalar_one()
            operation=connection.execute(sa.select(db.operations.c.id).where(db.operations.c.case_id==case_id)).scalar_one_or_none()
            result['operation']=reconcile(connection,operation) if operation else None
        return result

    @router.post('/cases/{case_id}/investigate',status_code=202,dependencies=[Depends(mutation)])
    def investigate_case_job(case_id: str,body: StrictBody):
        with transaction() as connection:
            authorize_case(connection,case_id,True)
            result=enqueue(connection,case_id,'investigate')
        result.pop('token',None)
        return result

    @router.post('/cases/{case_id}/review',dependencies=[Depends(mutation)])
    def review(case_id: str,body: ReviewRequest,actor: str=Depends(staff)):
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
    def execute_job(case_id: str,body: ExecutionRequest):
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

    app.include_router(router)
    return app
