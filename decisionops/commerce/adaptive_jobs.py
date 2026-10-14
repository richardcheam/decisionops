"""Partitioned adaptive ownership. Claims never touch business locks."""
from dataclasses import dataclass
from datetime import timedelta,datetime,timezone
import sqlalchemy as sa
from . import schema as db,adaptive_investigations as service
from .cases import clock,identifier
from .jobs import LeaseLost

EXECUTOR='commerce-adaptive-jobs/v1'
ACTION='adaptive_investigate/v1'

def get(connection,job_id,lock=False):
    q=sa.select(db.adaptive_jobs).where(db.adaptive_jobs.c.id==job_id)
    if lock:q=q.with_for_update()
    value=connection.execute(q).mappings().one_or_none()
    if value is None:raise ValueError('Adaptive job not found')
    return dict(value)

@dataclass(frozen=True)
class Fence:
    job_id:str
    token:str
    def check(self,c,run,lock=True):
        job=get(c,self.job_id,lock);now=clock(c)
        if (job['run_id']!=run['id'] or job['status']!='running' or job['token']!=self.token
            or job['lease_until']<=now or run['deadline']<=now):raise LeaseLost('Adaptive ownership lost/expired')
        return job

def enqueue(engine,case_id,report,policy='fixed',deadline_seconds=240):
    # Job and run creation commit atomically; no crash can orphan a scheduled run.
    return service.start(engine,case_id,report,policy=policy,deadline_seconds=deadline_seconds,scheduled=True)['job']

def claim(engine,job_id=None,lease_seconds=30):
    if type(lease_seconds) is not int or not 1<=lease_seconds<=240:raise ValueError('Lease seconds 1..240')
    with service.transaction(engine) as c:
        now=clock(c)
        q=sa.select(db.adaptive_jobs).where(sa.and_(db.adaptive_jobs.c.action==ACTION,
             db.adaptive_jobs.c.claims<16,sa.or_(db.adaptive_jobs.c.status=='queued',sa.and_(
             db.adaptive_jobs.c.status=='running',db.adaptive_jobs.c.lease_until<=now))))
        if job_id:q=q.where(db.adaptive_jobs.c.id==job_id)
        saved=c.execute(q.order_by(db.adaptive_jobs.c.created_at,db.adaptive_jobs.c.id)
                         .with_for_update(skip_locked=True).limit(1)).mappings().one_or_none()
        if saved is None:return None
        run=service.row(c,saved['run_id'])
        if run['state']!='active':
            c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==saved['id']).values(status='completed',token=None,lease_until=None))
            return None
        if now>=run['deadline']:
            c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==saved['id']).values(status='failed',error='RunDeadline',token=None,lease_until=None))
            return None
        c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==saved['id']).values(status='running',
            token=identifier('ALEASE'),lease_until=min(now+timedelta(seconds=lease_seconds),run['deadline']),claims=saved['claims']+1))
        return get(c,saved['id'])

def renew(engine,job_id,token,lease_seconds=30):
    if type(lease_seconds) is not int or not 1<=lease_seconds<=240:raise ValueError('Lease seconds 1..240')
    with service.transaction(engine) as c:
        job=get(c,job_id);run=service.row(c,job['run_id'])
        Fence(job_id,token).check(c,run,False)
        c=service.DeadlineConnection(c,min(job['lease_until'],run['deadline']))
        Fence(job_id,token).check(c,run)
        previous=get(c,job_id)['lease_until']
        c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==job_id).values(
            lease_until=min(clock(c)+timedelta(seconds=lease_seconds),run['deadline'])))
        if clock(c)>=previous:raise LeaseLost('Lease expired during renewal; roll back')
        return get(c,job_id)

def complete(engine,fence):
    with service.transaction(engine) as c:
        initial=get(c,fence.job_id);run,case=service.locked(c,initial['run_id']);job=get(c,fence.job_id,True)
        if job['status']=='completed':return job
        # Terminal domain commit can be repaired by a reclaimed owner; never replay it.
        now=clock(c)
        if job['status']!='running' or job['token']!=fence.token or job['lease_until']<=now:raise LeaseLost('Completion ownership lost')
        if run['state']=='active':raise ValueError('Adaptive run is not terminal')
        c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==job['id']).values(status='completed',lease_until=None))
        return get(c,job['id'])

def cancel(engine,job_id):
    with service.transaction(engine) as c:
        job=get(c,job_id);run,case=service.locked(c,job['run_id']);job=get(c,job_id,True)
        if job['status']=='completed':return job
        if run['state']=='active':
            history=service.snapshot(c,run)[0]
            service.finish(c,run,case,history,'job_cancelled',stale=not service.matches(run,case))
        c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==job_id).values(status='cancelled',token=None,lease_until=None))
        return get(c,job_id)

def recover(engine,fence):
    from . import adaptive_accounting as ledger
    with service.transaction(engine) as c:
        job=get(c,fence.job_id);run=service.row(c,job['run_id'])
    if run['deadline']<=datetime.now(timezone.utc):
        cancel(engine,fence.job_id);return service.inspect(engine,run['id'])
    if run['pending_token']:service.recover(engine,run['id'],expected_context=run['context_version'],fence=fence)
    with service.guarded(engine,run['id'],fence) as (c,current,case):
        call=ledger.latest(c,run['id'])
        if call and call['state']=='reserved' and clock(c)>=call['deadline']:
            ledger.expire_reserved(c,call['id']);ledger.disposition(c,call['id'],'stale')
            service.step(c,current,'recommendation_recovery',{'call_id':call['id'],'fallback':'fixed','not_dispatched':True})
        if call and call['state']=='dispatching':ledger.uncertain(c,call['id'],'operator_recovery')
        call=ledger.latest(c,run['id'])
        if call and call['state']=='uncertain' and call['application_status']=='pending':
            ledger.disposition(c,call['id'],'stale')
            service.step(c,current,'recommendation_recovery',{'call_id':call['id'],'fallback':'fixed','uncertain_reservation_retained':True})
    return service.inspect(engine,run['id'])


def repair_terminal(engine,job_id):
    """Checkpoint/completion repair after terminal commit; no domain replay."""
    with service.transaction(engine) as c:
        initial=get(c,job_id);run,case=service.locked(c,initial['run_id']);job=get(c,job_id,True)
        if run['state']=='active':raise ValueError('Only terminal completion may be repaired')
        if job['status']=='queued' or job['status']=='running' and job['lease_until']<=clock(c):
            c.execute(db.adaptive_jobs.update().where(db.adaptive_jobs.c.id==job_id).values(status='completed',token=None,lease_until=None))
        return get(c,job_id)
