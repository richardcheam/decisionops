"""Durable no-model work scheduling; token/lease fence every business commit."""
from datetime import timedelta
import json
import sqlalchemy as sa

from . import schema as db
from .cases import clock, identifier, lock_case, investigate_case
from .execution import execute
from .read_tools import canonical


class LeaseLost(ValueError):
    """This process cannot change a job owned by another/current worker."""


def get_job(connection, job_id):
    row=connection.execute(sa.select(db.jobs).where(db.jobs.c.id==job_id)).mappings().one_or_none()
    if row is None:
        raise ValueError('Job not found')
    return dict(row)


def enqueue(connection, case_id, action, operation_id=None):
    if action not in ('investigate','execute') or (action=='execute') != bool(operation_id):
        raise ValueError('Use investigate without operation or execute with approved operation ID')
    case=lock_case(connection,case_id)
    # Do not acquire a job lock while holding the case: worker locks job -> case.
    current=connection.execute(sa.select(db.jobs).where(sa.and_(db.jobs.c.case_id==case_id,
        db.jobs.c.status.in_(('queued','running'))))).mappings().one_or_none()
    if current:
        if current['action']==action and current['operation_id']==operation_id:
            return dict(current)
        raise ValueError('Case already has an in-flight job')
    if action=='investigate' and case['status']=='executed':
        raise ValueError('Executed cases cannot be investigated')
    if action=='execute':
        approved=connection.execute(sa.select(db.reviews.c.operation_id).where(sa.and_(
            db.reviews.c.id==case['approval_id'],db.reviews.c.case_id==case_id,
            db.reviews.c.generation==case['generation'],db.reviews.c.proposal_id==case['proposal_id']))).scalar_one_or_none()
        if case['status']!='approved' or approved!=operation_id:
            raise ValueError('Execution job requires the active approved operation')
    now=clock(connection)
    job_id=identifier('JOB')
    connection.execute(db.jobs.insert().values(id=job_id,case_id=case_id,action=action,
        operation_id=operation_id,status='queued',attempts=0,created_at=now,updated_at=now))
    return get_job(connection,job_id)


def claim(connection, lease_seconds=30):
    if type(lease_seconds) is not int or not 1<=lease_seconds<=3600:
        raise ValueError('Lease seconds must be an integer from 1 to 3600')
    now=clock(connection)
    # Exhausted leases become a visible failure; no infinite retry loop.
    exhausted=connection.execute(sa.select(db.jobs.c.id).where(sa.and_(db.jobs.c.status=='running',
        db.jobs.c.lease_until<=now,db.jobs.c.attempts>=3)).with_for_update(skip_locked=True).limit(100)).scalars().all()
    if exhausted:
        connection.execute(db.jobs.update().where(db.jobs.c.id.in_(exhausted)).values(status='failed',
            error_kind='AttemptsExhausted',lease_until=None,updated_at=now))
    row=connection.execute(sa.select(db.jobs).where(sa.and_(db.jobs.c.attempts<3,sa.or_(
        db.jobs.c.status=='queued',sa.and_(db.jobs.c.status=='running',db.jobs.c.lease_until<=now))))
        .order_by(db.jobs.c.created_at,db.jobs.c.id).with_for_update(skip_locked=True).limit(1)).mappings().one_or_none()
    if row is None:
        return None
    token=identifier('LEASE')
    connection.execute(db.jobs.update().where(db.jobs.c.id==row['id']).values(status='running',
        token=token,lease_until=now+timedelta(seconds=lease_seconds),attempts=row['attempts']+1,
        error_kind=None,updated_at=now))
    return get_job(connection,row['id'])


def complete(connection, job_id, token):
    row=connection.execute(sa.select(db.jobs).where(db.jobs.c.id==job_id).with_for_update()).mappings().one_or_none()
    if row is None:
        raise ValueError('Job not found')
    if row['status']=='completed':
        # Repairing graph state after business commit must not repeat domain writes.
        return row['outcome']
    now=clock(connection)
    if row['status']!='running' or row['token']!=token or row['lease_until']<=now:
        raise LeaseLost('Job lease expired or belongs to another worker')
    if row['action']=='investigate':
        result=investigate_case(connection,row['case_id'])
    else:
        result=execute(connection,row['case_id'],row['operation_id'])
    now=clock(connection)
    if row['lease_until']<=now:
        raise LeaseLost('Job expired during work; roll back and reclaim')
    outcome=json.loads(canonical(result))
    connection.execute(db.jobs.update().where(db.jobs.c.id==job_id).values(status='completed',
        outcome=outcome,lease_until=None,error_kind=None,updated_at=now))
    return outcome


def fail(connection, job_id, token, error_kind):
    now=clock(connection)
    connection.execute(db.jobs.update().where(sa.and_(db.jobs.c.id==job_id,db.jobs.c.status=='running',
        db.jobs.c.token==token,db.jobs.c.lease_until>now)).values(status='failed',
        error_kind=error_kind,lease_until=None,updated_at=now))
