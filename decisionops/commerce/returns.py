"""One-unit return authorization with independent eligibility and confirmation."""

from datetime import timedelta
from hashlib import sha256

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .cases import clock, identifier
from .delivery import _lock, _projection, aware, timeline
from .read_tools import canonical

POLICY = 'fictional-shop-returns-v1'
WINDOW_DAYS = 30
FINAL_SALE = {'return-final-sale'}


def _order(c, store, order_id, lock=False):
    query = sa.select(db.orders).where(db.orders.c.id == order_id, db.orders.c.store_id == store)
    row = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if row is None:
        raise LookupError('Order not found')
    return row


def _items(c, order_id):
    return [dict(row) for row in c.execute(sa.select(db.order_lines.c.variant_id, db.order_lines.c.quantity)
        .where(db.order_lines.c.order_id == order_id).order_by(db.order_lines.c.variant_id)).mappings()]


def _assessment(c, store, order, item, now):
    order_id, variant = order['id'], item['variant_id']
    evidence = {'policy': POLICY, 'window_days': WINDOW_DAYS, 'ordered_quantity': item['quantity']}
    prior = c.execute(sa.select(db.return_authorizations.c.id).join(db.return_cases)
        .where(db.return_cases.c.order_id == order_id, db.return_cases.c.variant_id == variant)).scalar_one_or_none()
    if prior:
        return 'ineligible', 'prior_return', evidence
    refunds = c.execute(sa.select(db.resolutions.c.id).where(db.resolutions.c.order_id == order_id,
        db.resolutions.c.variant_id == variant, db.resolutions.c.kind == 'refund')
        .order_by(db.resolutions.c.id)).scalars().all()
    evidence['refund_count'] = len(refunds)
    evidence['history_complete'] = order['resolution_history_complete']
    if refunds:
        return 'ineligible', 'prior_refund', evidence
    if not evidence['history_complete']:
        return 'review', 'history_incomplete', evidence
    if variant in FINAL_SALE:
        return 'ineligible', 'item_ineligible', evidence

    parcels = c.execute(sa.select(db.delivery_parcels).select_from(db.shipment_lines.outerjoin(
        db.delivery_parcels, sa.and_(db.shipment_lines.c.shipment_id == db.delivery_parcels.c.shipment_id,
                                     db.delivery_parcels.c.store_id == store)))
        .where(db.shipment_lines.c.order_id == order_id, db.shipment_lines.c.variant_id == variant).order_by(db.delivery_parcels.c.shipment_id)).mappings().all()
    if not parcels or any(parcel['shipment_id'] is None for parcel in parcels):
        return 'review', 'delivery_missing', evidence
    if len(parcels) != 1:
        return 'review', 'delivery_conflicting', evidence
    parcel = parcels[0]
    shipment = parcel['shipment_id']
    events = [r for r in timeline(c, store, shipment) if r['event_at'] <= now and r['received_at'] <= now]
    status, _, conflict = _projection(events, parcel['feed_available'])
    evidence.update(shipment_id=shipment, carrier_event_ids=[row['id'] for row in events])
    if conflict:
        return 'review', 'delivery_conflicting', evidence
    if not parcel['feed_available']:
        return 'review', 'delivery_unavailable', evidence
    if status != 'delivered':
        return 'review', 'delivery_not_verified', evidence

    deliveries = [aware(row['event_at']) for row in events if row['verified'] and row['status'] == 'delivered']
    if len(set(deliveries)) != 1 or deliveries[0] < parcel['dispatched_at']:
        return 'review', 'delivery_conflicting', evidence
    delivered_at = deliveries[0]
    deadline = delivered_at + timedelta(days=WINDOW_DAYS)
    evidence.update(delivered_at=delivered_at.isoformat(), deadline=deadline.isoformat())
    if now > deadline:
        return 'ineligible', 'outside_window', evidence
    return 'eligible', 'eligible', evidence


def eligibility(c, customer_id, store, order_id, variant_id=None, now=None):
    from .customer import owned_order
    owned_order(c, customer_id, store, order_id)
    order = _order(c, store, order_id)
    items = _items(c, order_id)
    if variant_id is None and len(items) != 1:
        return {'order_id': order_id, 'items': items, 'status': 'choose_item', 'reason': 'choose_item'}
    item = _item(items, variant_id or items[0]['variant_id'])
    status, reason, _ = _assessment(c, store, order, item, aware(clock(c, now)))
    return {'order_id': order_id, 'items': items, 'status': status, 'reason': reason}


def _item(items, variant):
    for item in items:
        if item['variant_id'] == variant:
            return item
    raise LookupError('Item not found')


def _public(row, authorization):
    return {key: row[key] for key in ('id', 'order_id', 'variant_id', 'status', 'reason')} | {
        'authorization_id': authorization,
    }


def _scoped(c, store, identity, lock=False):
    query = sa.select(db.return_cases).where(db.return_cases.c.id == identity, db.return_cases.c.store_id == store)
    row = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if row is None:
        raise LookupError('Return case not found')
    return row


def _authorization(c, case_id):
    return c.execute(sa.select(db.return_authorizations).where(
        db.return_authorizations.c.case_id == case_id)).mappings().one_or_none()


def _staff(c, row):
    authorization = _authorization(c, row['id'])
    return _public(row, authorization['id'] if authorization else None) | {
        'evidence': row['evidence'], 'proposal_hash': row['proposal_hash'], 'approved_by': row['approved_by'],
        'case_type': 'return', 'quantity': 1,
    }


def staff_case(c, store, identity):
    return _staff(c, _scoped(c, store, identity))


def staff_queue(c, store):
    rows = c.execute(sa.select(db.return_cases).where(db.return_cases.c.store_id == store)
        .order_by(db.return_cases.c.updated_at.desc(), db.return_cases.c.id)).mappings()
    return [_staff(c, row) for row in rows]


def conversation_cases(c, customer_id, store, conversation):
    rows = c.execute(sa.select(db.return_cases, db.return_authorizations.c.id.label('authorization_id'))
        .outerjoin(db.return_authorizations).where(db.return_cases.c.customer_id == customer_id,
            db.return_cases.c.store_id == store, db.return_cases.c.conversation_id == conversation)
        .order_by(db.return_cases.c.updated_at, db.return_cases.c.id)).mappings()
    return [_public(row, row['authorization_id']) for row in rows]


def start(c, customer_id, store, conversation, order_id, variant_id, now=None):
    from .customer import owned_conversation, owned_order
    owned_conversation(c, conversation, customer_id, store, lock=True)
    owned_order(c, customer_id, store, order_id)
    _item(_items(c, order_id), variant_id)
    c.execute(insert(db.return_cases).values(id=identifier('RETURN'), store_id=store, customer_id=customer_id,
        order_id=order_id, variant_id=variant_id, conversation_id=conversation, status='requested',
        reason='requested', evidence={}, updated_at=clock(c, now)).on_conflict_do_nothing(
        index_elements=[db.return_cases.c.order_id, db.return_cases.c.variant_id]))
    row = c.execute(sa.select(db.return_cases).where(db.return_cases.c.store_id == store,
        db.return_cases.c.customer_id == customer_id, db.return_cases.c.order_id == order_id,
        db.return_cases.c.variant_id == variant_id)).mappings().one()
    authorization = _authorization(c, row['id'])
    return _public(row, authorization['id'] if authorization else None) | {
        'conversation_id': row['conversation_id'],
    }


def _locked(c, store, identity, now):
    # The carrier feed uses the same shop fence. The compensation trigger and
    # normal evidence writers lock the order before changing its refund history.
    _lock(c, store)
    row = _scoped(c, store, identity, lock=True)
    order = _order(c, store, row['order_id'], lock=True)
    return row, order, aware(clock(c, now))


def _save(c, row, now, **changes):
    updated = c.execute(db.return_cases.update().where(db.return_cases.c.id == row['id'])
        .values(**changes, updated_at=now).returning(db.return_cases)).mappings().one()
    return _staff(c, updated)


def investigate(c, store, identity, now=None):
    row, order, at = _locked(c, store, identity, now)
    if row['status'] == 'authorized':
        return _staff(c, row)
    item = _item(_items(c, row['order_id']), row['variant_id'])
    status, reason, evidence = _assessment(c, store, order, item, at)
    proposal_hash = None
    if status == 'eligible':
        status = 'proposed'
        proposal = {key: row[key] for key in ('id', 'store_id', 'customer_id', 'order_id', 'variant_id')}
        proposal.update(generation=identifier('RETURN-PROPOSAL'), evidence=evidence, quantity=1)
        proposal_hash = sha256(canonical(proposal).encode()).hexdigest()
    return _save(c, row, at, status=status, reason=reason, evidence=evidence,
                 proposal_hash=proposal_hash, approved_by=None)


def approve(c, store, identity, proposal_hash, actor, now=None):
    row, _, at = _locked(c, store, identity, now)
    if row['status'] not in ('proposed', 'approved') or row['proposal_hash'] != proposal_hash:
        raise ValueError('The exact current return proposal is required')
    if row['status'] == 'approved':
        return _staff(c, row)
    return _save(c, row, at, status='approved', approved_by=actor)


def confirm(c, store, identity, proposal_hash, actor, now=None):
    row, order, at = _locked(c, store, identity, now)
    if row['status'] not in ('approved', 'authorized') or row['proposal_hash'] != proposal_hash:
        raise ValueError('The exact approved return proposal is required')
    if row['status'] == 'authorized':
        return _staff(c, row)
    item = _item(_items(c, row['order_id']), row['variant_id'])
    status, reason, evidence = _assessment(c, store, order, item, at)
    if status != 'eligible' or evidence != row['evidence']:
        return _save(c, row, at, status='review', reason=reason if status != 'eligible' else 'evidence_changed',
                     evidence=evidence, proposal_hash=None, approved_by=None)
    authorization_id = identifier('RETURN-AUTH')
    c.execute(db.return_authorizations.insert().values(id=authorization_id, case_id=identity,
        proposal_hash=proposal_hash, quantity=1, confirmed_by=actor, created_at=at))
    saved = _authorization(c, identity)
    if saved is None or (saved['id'], saved['proposal_hash'], saved['quantity']) != (authorization_id, proposal_hash, 1):
        raise RuntimeError('Return authorization verification failed')
    return _save(c, row, at, status='authorized')
