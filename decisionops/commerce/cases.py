"""Authoritative local case lifecycle. CLI operator is a demo identity, not authentication."""
from dataclasses import asdict
import json
import uuid

import sqlalchemy as sa

from . import schema as db
from .investigations import investigate, load_proposal, recheck
from .read_tools import AssessmentRequest, canonical


def identifier(prefix):
    return prefix + '-' + uuid.uuid4().hex


def clock(connection, now=None):
    # Execution freshness must include time spent waiting for locks.
    return now if now is not None else connection.exec_driver_sql('SELECT clock_timestamp()').scalar_one()


def event(connection, case_id, kind, details, now):
    connection.execute(db.case_events.insert().values(id=identifier('EVT'), case_id=case_id,
        kind=kind, details=json.loads(canonical(details)), created_at=now))


def lock_case(connection, case_id):
    row = connection.execute(sa.select(db.cases).where(db.cases.c.id == case_id).with_for_update()).mappings().one_or_none()
    if row is None:
        raise ValueError('Case not found')
    return dict(row)


def lock_business(connection, request):
    """All writers use case -> order -> policy/lines/payment/shipment -> sorted stock.

    Order/line FOR UPDATE also excludes FK inserts. Compensation's insertion guard
    writes the order revision, so historical repeatable-read writers serialize safely.
    Caller uses READ COMMITTED; after locks the bound rows cannot drift during reads.
    """
    order = connection.execute(sa.select(db.orders).where(db.orders.c.id == request.order_id).with_for_update()).mappings().one_or_none()
    if order is None:
        raise ValueError('Order not found')
    specs = [
        (db.policies, sa.and_(db.policies.c.id == order['policy_id'], db.policies.c.store_id == order['store_id'])),
        (db.order_lines, db.order_lines.c.order_id == request.order_id),
        (db.payments, db.payments.c.order_id == request.order_id),
        (db.shipments, db.shipments.c.order_id == request.order_id),
        (db.shipment_lines, db.shipment_lines.c.order_id == request.order_id),
        (db.inventory, sa.and_(db.inventory.c.store_id == order['store_id'], db.inventory.c.variant_id.in_(request.items))),
    ]
    for table, condition in specs:
        query = sa.select(table).where(condition).order_by(*table.primary_key.columns)
        # Policy versions are immutable; a shared key lock avoids serializing all
        # orders on one exclusive policy lock while preserving the FK identity.
        query = query.with_for_update(read=True, key_share=True) if table is db.policies else query.with_for_update()
        connection.execute(query).all()
    return dict(order)


def show_case(connection, case_id):
    row = connection.execute(sa.select(db.cases).where(db.cases.c.id == case_id)).mappings().one_or_none()
    if row is None:
        raise ValueError('Case not found')
    result = dict(row)
    result['proposal'] = load_proposal(connection, row['proposal_id']) if row['proposal_id'] else None
    result['approval'] = None
    if row['approval_id']:
        review = connection.execute(sa.select(db.reviews).where(sa.and_(db.reviews.c.id == row['approval_id'],
            db.reviews.c.case_id == case_id, db.reviews.c.generation == row['generation'],
            db.reviews.c.proposal_id == row['proposal_id'], db.reviews.c.decision == 'approve'))).mappings().one_or_none()
        if review is None:
            raise ValueError('Case approval binding is inconsistent')
        result['approval'] = dict(review)
    result['events'] = [dict(item) for item in connection.execute(sa.select(db.case_events).where(
        db.case_events.c.case_id == case_id).order_by(db.case_events.c.sequence)).mappings()]
    result['execution_authorized'] = False  # Display alone never authorizes an action.
    return result


def open_case(connection, request, now=None):
    if not connection.execute(sa.select(db.orders.c.id).where(db.orders.c.id == request.order_id)).first():
        raise ValueError('Order not found')
    now = clock(connection, now)
    case_id = identifier('CASE')
    connection.execute(db.cases.insert().values(id=case_id, order_id=request.order_id,
        request=asdict(request), status='open', generation=0, created_at=now, updated_at=now))
    event(connection, case_id, 'opened', {'request': asdict(request)}, now)
    return show_case(connection, case_id)


def investigate_case(connection, case_id, now=None):
    case = lock_case(connection, case_id)
    if case['status'] == 'executed':
        raise ValueError('Executed cases cannot be reinvestigated')
    request = AssessmentRequest(**case['request'])
    lock_business(connection, request)
    now = clock(connection, now)
    saved = investigate(connection, request, now)
    status = 'awaiting_review' if saved['proposal_id'] else (
        'blocked' if saved['decision']['status'] == 'ineligible' else 'needs_review')
    generation = case['generation'] + 1
    connection.execute(db.cases.update().where(db.cases.c.id == case_id).values(status=status,
        generation=generation, investigation_id=saved['investigation_id'], proposal_id=saved['proposal_id'],
        approval_id=None, updated_at=now))
    event(connection, case_id, 'investigated', {'generation': generation, **saved,
        'superseded_approval_id': case['approval_id']}, now)
    return show_case(connection, case_id)


def invalidate(connection, case, check, now):
    connection.execute(db.cases.update().where(db.cases.c.id == case['id']).values(
        status='needs_review', approval_id=None, updated_at=now))
    event(connection, case['id'], 'approval_invalidated' if case['approval_id'] else 'proposal_stale',
          {'approval_id': case['approval_id'], 'generation': case['generation'],
           'proposal_id': case['proposal_id'], 'check': check}, now)
    return {'status': 'requires_reinvestigation', 'case_id': case['id'], 'check': check,
            'execution_authorized': False}


def review_case(connection, case_id, generation, proposal_id, content_hash, decision, now=None, *, actor='local-demo-operator'):
    if not isinstance(actor, str) or not 1 <= len(actor) <= 128:
        raise ValueError('Review requires a bounded authenticated or local-demo actor')
    if decision not in ('approve', 'reject') or type(generation) is not int or generation < 1:
        raise ValueError('Review needs approve/reject and a positive generation')
    case = lock_case(connection, case_id)
    if generation != case['generation'] or proposal_id != case['proposal_id']:
        raise ValueError('Review does not match current case generation/proposal')
    proposal = load_proposal(connection, proposal_id)
    if content_hash != proposal['content_hash']:
        raise ValueError('Review content hash does not match proposal')
    previous = connection.execute(sa.select(db.reviews).where(sa.and_(
        db.reviews.c.case_id == case_id, db.reviews.c.generation == generation))).mappings().one_or_none()
    if previous:
        expected = 'approved' if decision == 'approve' else 'rejected'
        if previous['decision'] == decision and previous['actor'] == actor and case['status'] in (expected, 'executed'):
            return show_case(connection, case_id)
        raise ValueError('This generation was already reviewed or its approval was revoked')
    if case['status'] != 'awaiting_review':
        raise ValueError('Case is not awaiting review; investigate again')
    if decision == 'approve':
        lock_business(connection, AssessmentRequest(**case['request']))
        now = clock(connection, now)
        check = recheck(connection, proposal_id, now)
        if check['status'] != 'valid_for_review':
            return invalidate(connection, case, check, now)
    now = clock(connection, now)
    review_id = identifier('REVIEW')
    operation_id = identifier('OP') if decision == 'approve' else None
    connection.execute(db.reviews.insert().values(id=review_id, case_id=case_id, generation=generation,
        proposal_id=proposal_id, content_hash=content_hash, decision=decision,
        actor=actor, operation_id=operation_id, created_at=now))
    connection.execute(db.cases.update().where(db.cases.c.id == case_id).values(
        status='approved' if decision == 'approve' else 'rejected',
        approval_id=review_id if decision == 'approve' else None, updated_at=now))
    event(connection, case_id, 'reviewed', {'review_id': review_id, 'decision': decision,
        'generation': generation, 'proposal_id': proposal_id, 'content_hash': content_hash,
        'operation_id': operation_id, 'actor': actor}, now)
    return show_case(connection, case_id)


def escalate_case(connection, case_id, reason, now=None):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError('Escalation reason must contain 1-500 characters')
    case = lock_case(connection, case_id)
    if case['status'] == 'executed':
        raise ValueError('Executed cases cannot be escalated')
    now = clock(connection, now)
    connection.execute(db.cases.update().where(db.cases.c.id == case_id).values(
        status='escalated', approval_id=None, updated_at=now))
    event(connection, case_id, 'escalated', {'reason': reason, 'superseded_approval_id': case['approval_id']}, now)
    return show_case(connection, case_id)
