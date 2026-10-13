"""Approved local replacement, atomic stock reservation, and ledger reconciliation."""
import sqlalchemy as sa

from . import schema as db
from .cases import clock, event, invalidate, lock_business, lock_case
from .investigations import load_proposal, recheck
from .read_tools import AssessmentRequest


def reconcile(connection, operation_id):
    operation = connection.execute(sa.select(db.operations).where(db.operations.c.id == operation_id)).mappings().one_or_none()
    if operation is None:
        return {'status': 'not_found', 'operation_id': operation_id, 'retry_requires_approval_check': True}
    heads = connection.execute(sa.select(db.replacement_orders).where(db.replacement_orders.c.operation_id == operation_id)).mappings().all()
    lines = connection.execute(sa.select(db.replacement_lines).where(db.replacement_lines.c.operation_id == operation_id)).mappings().all()
    held = connection.execute(sa.select(db.reservations).where(db.reservations.c.operation_id == operation_id)).mappings().all()
    resolutions = connection.execute(sa.select(db.resolutions).where(db.resolutions.c.operation_id == operation_id)).mappings().all()
    expected = operation['request']['items']
    line_items = {row['variant_id']: row['quantity'] for row in lines}
    held_items = {row['variant_id']: row['quantity'] for row in held}
    covered = {row['variant_id']: row['quantity'] for row in resolutions if row['kind'] == 'replacement' and row['order_id'] == operation['order_id']}
    inventory_issues = []
    for reservation in held:
        condition = sa.and_(db.inventory.c.store_id == reservation['store_id'],
                            db.inventory.c.variant_id == reservation['variant_id'])
        ledger_total = sa.select(sa.func.coalesce(sa.func.sum(db.reservations.c.quantity), 0)).where(sa.and_(
            db.reservations.c.store_id == reservation['store_id'],
            db.reservations.c.variant_id == reservation['variant_id'])).scalar_subquery()
        # One statement observes counter and ledger in one MVCC snapshot, including
        # idempotent execute retries whose transaction uses READ COMMITTED.
        stock = connection.execute(sa.select(db.inventory.c.reserved, ledger_total).where(condition)).one_or_none()
        actual, total = stock if stock is not None else (None, None)
        if actual is None or actual < total:
            inventory_issues.append({'store_id': reservation['store_id'], 'variant_id': reservation['variant_id'],
                                     'reserved_counter': actual, 'ledger_reserved': total})
    case = connection.execute(sa.select(db.cases).where(db.cases.c.id == operation['case_id'])).mappings().one_or_none()
    lifecycle_matches = (case is not None and case['status'] == 'executed'
                         and case['approval_id'] == operation['review_id'] and case['request'] == operation['request'])
    valid = (len(heads) == 1 and line_items == held_items == covered == expected
             and not inventory_issues and lifecycle_matches)
    return {'status': 'verified' if valid else 'inconsistent', 'operation_id': operation_id,
            'case_id': operation['case_id'], 'order_id': operation['order_id'],
            'replacement_id': heads[0]['id'] if len(heads) == 1 else None,
            'items': expected, 'inventory_issues': inventory_issues, 'reservations': [dict(row) for row in held],
            'resolutions': [dict(row) for row in resolutions], 'completed_at': operation['completed_at'],
            'meaning': 'Replacement recorded and stock reserved in fictional store; not shipped'}


def execute(connection, case_id, operation_id, now=None):
    case = lock_case(connection, case_id)
    existing = connection.execute(sa.select(db.operations.c.case_id).where(db.operations.c.id == operation_id)).scalar_one_or_none()
    if existing is not None:
        if existing != case_id:
            raise ValueError('Operation belongs to another case')
        return reconcile(connection, operation_id)
    if case['status'] != 'approved' or not case['approval_id']:
        raise ValueError('Execution requires an active staff approval')
    approval = connection.execute(sa.select(db.reviews).where(sa.and_(db.reviews.c.id == case['approval_id'],
        db.reviews.c.case_id == case_id, db.reviews.c.generation == case['generation'],
        db.reviews.c.proposal_id == case['proposal_id'], db.reviews.c.decision == 'approve',
        db.reviews.c.operation_id == operation_id))).mappings().one_or_none()
    if approval is None:
        raise ValueError('Operation does not match the active approved review')
    proposal = load_proposal(connection, case['proposal_id'])
    if proposal['content_hash'] != approval['content_hash'] or proposal['document']['request'] != case['request']:
        raise ValueError('Approval/proposal/request binding is inconsistent')
    request = AssessmentRequest(**case['request'])
    order = lock_business(connection, request)
    now = clock(connection, now)
    check = recheck(connection, case['proposal_id'], now)
    if check['status'] != 'valid_for_review':
        return invalidate(connection, case, check, now)
    connection.execute(db.operations.insert().values(id=operation_id, review_id=approval['id'],
        case_id=case_id, order_id=case['order_id'], request=case['request'], completed_at=now))
    replacement_id = 'REPL-' + operation_id
    connection.execute(db.replacement_orders.insert().values(id=replacement_id, operation_id=operation_id, created_at=now))
    for variant, quantity in sorted(request.items.items()):
        updated = connection.execute(db.inventory.update().where(sa.and_(db.inventory.c.store_id == order['store_id'],
            db.inventory.c.variant_id == variant, db.inventory.c.on_hand - db.inventory.c.reserved >= quantity))
            .values(reserved=db.inventory.c.reserved + quantity))
        if updated.rowcount != 1:
            # Never return a normal result after partial writes: caller must roll back.
            raise ValueError('Stock update failed; roll back transaction and reinvestigate')
        resolution_id = 'RES-' + operation_id + '-' + variant
        connection.execute(db.resolutions.insert().values(id=resolution_id, order_id=case['order_id'],
            variant_id=variant, quantity=quantity, kind='replacement', operation_id=operation_id))
        connection.execute(db.replacement_lines.insert().values(replacement_id=replacement_id, variant_id=variant,
            operation_id=operation_id, order_id=case['order_id'], quantity=quantity, resolution_id=resolution_id))
        connection.execute(db.reservations.insert().values(operation_id=operation_id, variant_id=variant,
            store_id=order['store_id'], quantity=quantity))
    connection.execute(db.cases.update().where(db.cases.c.id == case_id).values(status='executed', updated_at=now))
    event(connection, case_id, 'executed', {'operation_id': operation_id, 'replacement_id': replacement_id}, now)
    result = reconcile(connection, operation_id)
    if result['status'] != 'verified':
        raise ValueError('Replacement records inconsistent; roll back and investigate')
    return result
