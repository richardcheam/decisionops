"""Fictional carrier adapter, explicit Paris reporting and in-app case updates.

Verified lost/delivered events outrank transit scans regardless of arrival order.
Opposing verified terminal records, or reused source IDs with differing content,
project unknown until staff resolves the source conflict. All original records stay
append-only. Customer reports and missed promises never supply confirmed loss.
"""
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .cases import clock, event, open_case
from .read_tools import AssessmentRequest, canonical

PARIS = ZoneInfo('Europe/Paris')


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('An explicit timezone is required')
    return value.astimezone(timezone.utc)


def week_bounds(now):
    local = aware(now).astimezone(PARIS)
    start = datetime.combine(local.date()-timedelta(days=local.weekday()), time(), PARIS)
    return start, start+timedelta(days=7)


def _lock(connection, store_id):
    # Stable shop fence coordinates seed, ingest and scanners across processes.
    connection.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:shop,10420010))'), {'shop':store_id})


def _parcel(connection, store_id, shipment_id):
    row = connection.execute(sa.select(db.delivery_parcels).where(
        db.delivery_parcels.c.store_id==store_id, db.delivery_parcels.c.shipment_id==shipment_id)).mappings().one_or_none()
    if row is None:
        raise ValueError('Parcel not found in this shop')
    return row


def timeline(connection, store_id, shipment_id):
    _parcel(connection, store_id, shipment_id)
    return [dict(r) for r in connection.execute(sa.select(db.carrier_events).where(
        db.carrier_events.c.shipment_id==shipment_id).order_by(db.carrier_events.c.event_at,
        db.carrier_events.c.source,db.carrier_events.c.external_id,db.carrier_events.c.id)).mappings()]


def _projection(events, available=True):
    identities = {}
    for row in events:
        identities.setdefault((row['source'],row['external_id']),set()).add(row['id'])
    identity_conflict = any(len(values)>1 for values in identities.values())
    verified = [r for r in events if r['verified']]
    terminals = {r['status'] for r in verified if r['status'] in ('lost','delivered')}
    conflict = identity_conflict or len(terminals)>1
    if not available or conflict or not verified:
        return 'unknown', max((r['event_at'] for r in events),default=None), conflict
    if terminals:
        status = next(iter(terminals))
        return status,max(r['event_at'] for r in verified if r['status']==status),False
    newest = max(r['event_at'] for r in verified)
    statuses = {r['status'] for r in verified if r['event_at']==newest}
    return (next(iter(statuses)) if len(statuses)==1 else 'unknown'),newest,len(statuses)>1


def _reproject(connection, parcel, now):
    # Match Commerce business lock order. Carrier writes never lock a case.
    connection.execute(sa.select(db.orders.c.id).where(db.orders.c.id==parcel['order_id']).with_for_update()).all()
    connection.execute(sa.select(db.shipments.c.id).where(db.shipments.c.id==parcel['shipment_id']).with_for_update()).all()
    status, observed, conflict = _projection(timeline(connection,parcel['store_id'],parcel['shipment_id']),parcel['feed_available'])
    connection.execute(db.shipments.update().where(db.shipments.c.id==parcel['shipment_id']).values(
        carrier_status=status,carrier_observed_at=observed or now))
    return {'status':status,'conflict':conflict}


def ingest_event(connection, store_id, shipment_id, source, external_id, status, event_at, original, *, verified=None, now=None):
    """Replay-safe insert; conflicting payloads are additional immutable evidence.

    Source identity is globally scoped to an adapter. A reused identity bound to a
    different parcel is rejected, preventing evidence crossing parcel boundaries.
    """
    if status not in ('lost','in_transit','delivered','unknown'):
        raise ValueError('Unknown normalized carrier status')
    if not isinstance(source,str) or not 1<=len(source)<=128 or not isinstance(external_id,str) or not 1<=len(external_id)<=256:
        raise ValueError('Bounded source and external identity required')
    if not isinstance(original,dict):
        raise ValueError('Original fixture must be an object')
    verified = original.get('verified',False) if verified is None else verified
    if type(verified) is not bool:
        raise ValueError('Verified must be a boolean from the adapter')
    now, event_at = aware(clock(connection,now)), aware(event_at)
    if event_at>now:
        raise ValueError('Carrier event cannot be in the future')
    _lock(connection,store_id)
    parcel = _parcel(connection,store_id,shipment_id)
    # Fence the external ID globally as well, including across shop scanners.
    connection.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:identity,10420011))'),
        {'identity':canonical([source,external_id])})
    bindings = connection.execute(sa.select(db.carrier_events.c.shipment_id).where(
        db.carrier_events.c.source==source,db.carrier_events.c.external_id==external_id)).scalars().all()
    if any(value!=shipment_id for value in bindings):
        raise ValueError('Carrier identity already belongs to another parcel')
    payload = dict(shipment_id=shipment_id,source=source,external_id=external_id,event_at=event_at,
                   status=status,verified=verified,original=json.loads(canonical(original)))
    identity = hashlib.sha256(canonical(payload).encode()).hexdigest()
    result = connection.execute(insert(db.carrier_events).values(id=identity,received_at=now,**payload).on_conflict_do_nothing().returning(db.carrier_events.c.id)).scalar_one_or_none()
    projection = _reproject(connection,parcel,now)
    return {'event_id':identity,'inserted':result is not None,**projection}


class SimulatedCarrier:
    """One local fixture adapter; no network or credentials."""
    def ingest(self, connection, store_id, shipment_id, **event_record):
        return ingest_event(connection,store_id,shipment_id,**event_record)

    def replay(self, connection, store_id, records, now=None):
        return [self.ingest(connection,store_id,now=now,**record) for record in records]

    def set_available(self, connection, store_id, shipment_id, available, now=None):
        if type(available) is not bool:
            raise ValueError('Availability must be boolean')
        _lock(connection,store_id)
        parcel = dict(_parcel(connection,store_id,shipment_id))
        connection.execute(db.delivery_parcels.update().where(db.delivery_parcels.c.shipment_id==shipment_id).values(feed_available=available))
        parcel['feed_available']=available
        return _reproject(connection,parcel,aware(clock(connection,now)))


def _rows(connection, store_id):
    return [dict(row) for row in connection.execute(sa.select(db.delivery_parcels,
        db.shipments.c.carrier_status,db.shipments.c.carrier_observed_at).join(db.shipments,
        db.delivery_parcels.c.shipment_id==db.shipments.c.id).where(db.delivery_parcels.c.store_id==store_id)
        .order_by(db.delivery_parcels.c.shipment_id)).mappings()]


def _triggers(connection, row, now):
    status,_,conflict = _projection(timeline(connection,row['store_id'],row['shipment_id']),row['feed_available'])
    kinds = set()
    if row['promised_at']<now and status!='delivered': kinds.add('overdue')
    if row['reported_nonreceipt']: kinds.add('nonreceipt')
    if conflict: kinds.add('carrier_conflict')
    return kinds


def scan(connection, store_id, now=None):
    """Background-safe reconciliation. One durable case per shop and parcel.

    Recovery hides an entry while preserving the case, proposal and full history.
    A new trigger reuses that case. Executed/rejected/escalated cases close queue
    entries; the scanner never restarts investigation or changes staff decisions.
    """
    now = aware(clock(connection,now))
    _lock(connection,store_id)
    # Acquire every existing case before inserts take order FK locks. This keeps
    # scanning consistent with Commerce's case -> order lock order even when a
    # new parcel and an existing peer case belong to the same split order.
    existing=connection.execute(sa.select(db.delivery_case_links.c.case_id).where(
        db.delivery_case_links.c.store_id==store_id)).scalars().all()
    if existing:
        connection.execute(sa.select(db.cases.c.id).where(db.cases.c.id.in_(existing))
            .order_by(db.cases.c.id).with_for_update()).all()
    for row in _rows(connection,store_id):
        scope = (db.delivery_case_links.c.store_id==store_id,db.delivery_case_links.c.shipment_id==row['shipment_id'])
        link = connection.execute(sa.select(db.delivery_case_links).where(*scope)).mappings().one_or_none()
        kinds = _triggers(connection,row,now)
        if not link and not kinds: continue
        if not link:
            items = dict(connection.execute(sa.select(db.shipment_lines.c.variant_id,db.shipment_lines.c.quantity).where(
                db.shipment_lines.c.shipment_id==row['shipment_id'])).all())
            if not items:
                # Bind the requested order quantities, without asserting they
                # shipped. The fulfilment tool will report the missing manifest.
                items=dict(connection.execute(sa.select(db.order_lines.c.variant_id,db.order_lines.c.quantity)
                    .where(db.order_lines.c.order_id==row['order_id'])).all())
            if not items:
                # No valid replacement request exists. Retain source rows; do
                # not let one malformed order prevent unrelated jobs running.
                import logging
                logging.getLogger(__name__).warning('delivery_scope_unavailable')
                continue
            case = open_case(connection,AssessmentRequest(row['order_id'],row['shipment_id'],items),now)
            connection.execute(db.delivery_case_links.insert().values(store_id=store_id,shipment_id=row['shipment_id'],
                order_id=row['order_id'],case_id=case['id'],active=True))
            link = {'case_id':case['id'],'active':True}
        case = connection.execute(sa.select(db.cases).where(db.cases.c.id==link['case_id']).with_for_update()).mappings().one()
        closed = case['status'] in ('executed','rejected','escalated')
        if closed: kinds = set()
        previous = {r['kind']:r['active'] for r in connection.execute(sa.select(db.delivery_triggers).where(
            db.delivery_triggers.c.store_id==store_id,db.delivery_triggers.c.shipment_id==row['shipment_id'])).mappings()}
        for kind in sorted(set(previous)|kinds):
            active = kind in kinds
            if previous.get(kind,False)==active: continue
            connection.execute(insert(db.delivery_triggers).values(store_id=store_id,shipment_id=row['shipment_id'],kind=kind,
                active=active,updated_at=now).on_conflict_do_update(index_elements=['store_id','shipment_id','kind'],set_={'active':active,'updated_at':now}))
            event(connection,link['case_id'],'delivery_trigger_added' if active else 'delivery_trigger_cleared',
                  {'shipment_id':row['shipment_id'],'trigger':kind},now)
        active = bool(kinds)
        if link['active']!=active:
            connection.execute(db.delivery_case_links.update().where(*scope).values(active=active))
            event(connection,link['case_id'],'delivery_resolved' if closed else ('delivery_reopened' if active else 'delivery_recovered'),
                {'shipment_id':row['shipment_id'],'status':case['status']},now)
        if previous!={kind:kind in kinds for kind in set(previous)|kinds}:
            connection.execute(db.cases.update().where(db.cases.c.id==link['case_id']).values(updated_at=now))
    return queue(connection,store_id,now)


def report_nonreceipt(connection, store_id, shipment_id, now=None):
    _lock(connection,store_id)
    _parcel(connection,store_id,shipment_id)
    connection.execute(db.delivery_parcels.update().where(db.delivery_parcels.c.shipment_id==shipment_id).values(reported_nonreceipt=True))
    return scan(connection,store_id,now)


def queue(connection, store_id, now=None):
    # Read-only: HTTP reporting never creates cases or changes proposals.
    rows = connection.execute(sa.select(db.delivery_case_links,db.delivery_parcels.c.city,db.delivery_parcels.c.promised_at,
        db.shipments.c.carrier_status,db.cases.c.status,db.cases.c.updated_at).join(db.delivery_parcels,
        db.delivery_parcels.c.shipment_id==db.delivery_case_links.c.shipment_id).join(db.shipments,
        db.shipments.c.id==db.delivery_case_links.c.shipment_id).join(db.cases,db.cases.c.id==db.delivery_case_links.c.case_id)
        .where(db.delivery_case_links.c.store_id==store_id,db.delivery_case_links.c.active==True,
        db.cases.c.status.not_in(('executed','rejected','escalated'))).order_by(db.delivery_parcels.c.promised_at,db.delivery_case_links.c.shipment_id)).mappings()
    result=[]
    for row in rows:
        triggers=connection.execute(sa.select(db.delivery_triggers.c.kind).where(db.delivery_triggers.c.store_id==store_id,
            db.delivery_triggers.c.shipment_id==row['shipment_id'],db.delivery_triggers.c.active==True).order_by(db.delivery_triggers.c.kind)).scalars().all()
        status=row['status']
        action={'open':'Investigate parcel','awaiting_review':'Review proposal','approved':'Confirm execution',
                'needs_review':'Review missing or conflicting evidence','blocked':'Review blocker'}.get(status,'Review case')
        result.append({key:row[key] for key in ('case_id','order_id','shipment_id','city','status','carrier_status')} | {
            'triggers':triggers,'updated_at':row['updated_at'].isoformat(),'promised_at':row['promised_at'].isoformat(),'next_action':action})
    return result


def report(connection, store_id, now=None):
    now = aware(clock(connection,now))
    start,end=week_bounds(now)
    completed=0
    open_count=overdue=0
    freshness=[]
    for row in _rows(connection,store_id):
        events=[r for r in timeline(connection,store_id,row['shipment_id']) if r['event_at']<=now and r['received_at']<=now]
        status,_,_= _projection(events,row['feed_available'])
        # Distinct parcels with verified delivery in the local week, as known now.
        if any(r['verified'] and r['status']=='delivered' and start<=r['event_at']<end and r['event_at']<=now and r['received_at']<=now for r in events):
            completed+=1
        if row['dispatched_at']<=now and status!='delivered':
            open_count+=1
            overdue+=int(row['promised_at']<now)
        freshness.extend(r['received_at'] for r in events if r['received_at']<=now)
    links=[{k:r[k] for k in ('case_id','order_id','shipment_id')} for r in queue(connection,store_id,now)]
    return {'timezone':'Europe/Paris','start':start.isoformat(),'end':end.isoformat(),'as_of':now.isoformat(),
        'latest_carrier_receipt':max(freshness).isoformat() if freshness else None,
        'completed':completed,'open':open_count,'overdue':overdue,'exceptions':len(links),'case_links':links,
        'semantics':{'completed':'Distinct parcels with a verified delivered event during this Paris calendar week, received by as_of; conflicts remain visible as exceptions.',
            'open':'All dispatched parcels without an unconflicted verified delivery as of the report clock; not limited to this week.',
            'overdue':'Open parcels whose promised delivery time is before as_of; overdue does not establish loss.'}}
