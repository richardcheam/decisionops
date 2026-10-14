"""Independent projected business reads; callers own consistent, read-only transactions.

No bundled assessment, model, case mutation or hidden dependency refresh is performed.
"""
from dataclasses import asdict
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from . import schema as db
from .adaptive_evidence import canonical, observation
from .evidence import utc_timestamp
from .read_tools import AssessmentRequest

DEPENDENCIES = {
    'order_manifest': (),
    'replacement_policy': ('order_manifest',),
    'payment': ('order_manifest',),
    'fulfilment': ('order_manifest',),
    'carrier_loss': ('order_manifest', 'fulfilment', 'replacement_policy'),
    'compensation_history': ('order_manifest',),
    'inventory': ('order_manifest',),
}
PROJECTIONS = {
    'order_manifest': (('orders', ('id','store_id','policy_id','currency')),
                       ('order_lines', ('order_id','variant_id','quantity','unit_price_minor'))),
    'replacement_policy': (('policy_versions', ('id','store_id','version','allow_confirmed_loss',
                                               'max_units','carrier_max_age_seconds')),),
    'payment': (('payments', ('order_id','status','amount_minor','currency')),),
    'fulfilment': (('shipments', ('id','order_id','fulfilment_status')),
                   ('shipment_lines', ('shipment_id','order_id','variant_id','quantity'))),
    'carrier_loss': (('shipments', ('id','order_id','carrier_status','carrier_observed_at')),),
    'compensation_history': (('orders', ('id','resolution_history_complete','compensation_revision')),
                             ('resolutions', ('id','order_id','variant_id','quantity','kind','operation_id'))),
    'inventory': (('inventory', ('store_id','variant_id','on_hand','reserved')),),
}
MISMATCH_PROJECTION = ('shipments', ('order_id',))


def projected_rows(connection, table, columns, condition):
    projection = [table.c[name] for name in columns]
    order = [column for column in table.primary_key.columns if column.name in columns]
    query = sa.select(*projection).where(condition).order_by(*order)
    return [dict(row) for row in connection.execute(query).mappings()]


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def unique(rows, fields):
    return len({tuple(row[field] for field in fields) for row in rows}) == len(rows)


def read_tool(connection, tool, request, history, now, *, dependencies=(), stream='primary'):
    """Execute exactly one declared tool. Dependency rejection occurs before any SQL.

    SQL errors yield bounded unavailable observations; the caller must roll back an
    aborted transaction before another tool. No automatic retry occurs here.
    """
    # Snapshot and revalidate the nested items mapping, which a frozen dataclass
    # does not itself make immutable. Never query using caller-owned mutable data.
    request = AssessmentRequest(**asdict(request))
    if (tool not in DEPENDENCIES or stream not in history.streams
            or canonical(asdict(request)) != canonical(history.request)):
        raise ValueError('Unknown tool or mismatched request')
    utc_timestamp(now.isoformat())
    dependencies = tuple(dependencies)
    names = tuple(dep.record()['tool'] for dep in dependencies)
    if len(names) != len(set(names)) or set(names) != set(DEPENDENCIES[tool]):
        raise ValueError('Supply exactly the declared dependency observations')
    for dep in dependencies:
        name = dep.record()['tool']
        if dep not in history.active(name) or history.select(name, now).version != dep.version:
            raise ValueError('Dependency must be an active, current observation in this history')
    contexts = {dep.record()['tool']: dep.record()['payload'] for dep in dependencies}
    manifest = contexts.get('order_manifest')
    if tool == 'carrier_loss' and not contexts['fulfilment'].get('selected'):
        raise ValueError('Carrier read requires a bound selected shipment')
    payload = {}
    value = None
    status = 'success'
    reason = None
    scope_known = False
    scope = []
    expiry = now + timedelta(days=1)

    def query(index, condition):
        table_name, columns = PROJECTIONS[tool][index]
        return projected_rows(connection, db.metadata.tables[table_name], columns, condition)

    def unresolved(message, missing=False):
        nonlocal value, reason, status, scope_known
        value, reason, scope_known = None, message, False
        if missing:
            status = 'missing'

    try:
        if tool == 'order_manifest':
            orders = query(0, db.orders.c.id == request.order_id)
            lines = query(1, db.order_lines.c.order_id == request.order_id)
            payload = {'orders':orders, 'lines':lines}
            if not orders or not lines:
                unresolved('order_or_lines_missing', True)
            elif (len(orders) != 1 or orders[0]['id'] != request.order_id
                  or not unique(lines, ('variant_id',))
                  or any(line['order_id'] != request.order_id or not integer(line['quantity'],1)
                         or not integer(line['unit_price_minor']) for line in lines)):
                unresolved('conflicting_records')
            else:
                ordered = {line['variant_id']:line['quantity'] for line in lines}
                value = all(variant in ordered and qty <= ordered[variant]
                            for variant,qty in request.items.items())
                scope_known = True
                if value and request.items != ordered:
                    scope.append('partial_request')
        else:
            order = manifest['orders'][0]
            lines = manifest['lines']
            ordered = {line['variant_id']:line['quantity'] for line in lines}
            if tool == 'replacement_policy':
                rows = query(0, sa.and_(db.policies.c.id == order['policy_id'],
                                       db.policies.c.store_id == order['store_id']))
                payload = {'policies':rows}
                if not rows:
                    unresolved('policy_missing', True)
                elif (len(rows) != 1 or rows[0]['id'] != order['policy_id']
                      or rows[0]['store_id'] != order['store_id']
                      or type(rows[0]['allow_confirmed_loss']) is not bool
                      or any(not integer(rows[0][field],1) for field in
                             ('version','max_units','carrier_max_age_seconds'))):
                    unresolved('conflicting_records')
                else:
                    value = rows[0]['allow_confirmed_loss'] and sum(request.items.values()) <= rows[0]['max_units']
            elif tool == 'payment':
                rows = query(0, db.payments.c.order_id == request.order_id)
                payload = {'payments':rows}
                if not rows:
                    unresolved('payment_missing', True)
                elif (len(rows) != 1 or rows[0]['order_id'] != request.order_id
                      or rows[0]['status'] not in ('paid','pending','failed')
                      or not integer(rows[0]['amount_minor'])):
                    unresolved('conflicting_records')
                else:
                    value = (rows[0]['status'] == 'paid' and rows[0]['currency'] == order['currency']
                             and rows[0]['amount_minor'] == sum(line['quantity'] * line['unit_price_minor'] for line in lines))
            elif tool == 'fulfilment':
                shipments = query(0, db.shipments.c.order_id == request.order_id)
                selected = next((row for row in shipments if row['id'] == request.shipment_id), None)
                shipped_lines = query(1, sa.and_(db.shipment_lines.c.shipment_id == request.shipment_id,
                                                db.shipment_lines.c.order_id == request.order_id)) if selected else []
                payload = {'shipments':shipments,'selected':selected,'lines':shipped_lines}
                if not selected:
                    # Only binding metadata: do not expose another order's shipment contents.
                    binding = projected_rows(connection, db.shipments, MISMATCH_PROJECTION[1],
                                             db.shipments.c.id == request.shipment_id)
                    payload['binding_mismatch'] = bool(binding)
                    if binding:
                        scope.append('shipment_order_mismatch')
                    unresolved('shipment_missing_or_wrong_order', True)
                elif (not unique(shipments, ('id',)) or not unique(shipped_lines, ('variant_id',))
                      or any(row['order_id'] != request.order_id or row['fulfilment_status'] not in ('shipped','prepared') for row in shipments)
                      or any(row['order_id'] != request.order_id or row['shipment_id'] != request.shipment_id
                             or row['variant_id'] not in ordered or not integer(row['quantity'],1) for row in shipped_lines)):
                    unresolved('conflicting_records')
                elif not shipped_lines:
                    unresolved('shipment_lines_missing', True)
                else:
                    shipped = {row['variant_id']:row['quantity'] for row in shipped_lines}
                    value = selected['fulfilment_status'] == 'shipped' and shipped == ordered
                    scope_known = True
                    if len(shipments) > 1:
                        scope.append('split_shipment')
                    if shipped != ordered:
                        scope.append('partial_shipment')
            elif tool == 'carrier_loss':
                rows = query(0, sa.and_(db.shipments.c.id == request.shipment_id, db.shipments.c.order_id == request.order_id))
                payload = {'carrier':rows}
                if not rows:
                    unresolved('carrier_record_missing', True)
                elif (len(rows) != 1 or rows[0]['id'] != request.shipment_id
                      or rows[0]['order_id'] != request.order_id
                      or rows[0]['carrier_status'] not in ('lost','delivered','in_transit','unknown')):
                    unresolved('conflicting_records')
                else:
                    timestamp = rows[0]['carrier_observed_at']
                    if isinstance(timestamp,datetime): timestamp = timestamp.isoformat()
                    observed = utc_timestamp(timestamp)
                    max_age = contexts['replacement_policy']['policies'][0]['carrier_max_age_seconds']
                    expiry = min(expiry, observed + timedelta(seconds=max_age))
                    if observed > now or now > expiry:
                        unresolved('carrier_event_stale_or_future')
                    elif rows[0]['carrier_status'] in ('lost','delivered'):
                        value = rows[0]['carrier_status'] == 'lost'
                    else:
                        unresolved('loss_not_confirmed')
            elif tool == 'compensation_history':
                markers = query(0, db.orders.c.id == request.order_id)
                rows = query(1, db.resolutions.c.order_id == request.order_id)
                payload = {'markers':markers,'resolutions':rows}
                if not markers:
                    unresolved('history_marker_missing', True)
                elif (len(markers) != 1 or markers[0]['id'] != request.order_id
                      or type(markers[0]['resolution_history_complete']) is not bool
                      or not integer(markers[0]['compensation_revision'])
                      or not unique(rows, ('id',))
                      or any(row['order_id'] != request.order_id or row['variant_id'] not in ordered
                             or not integer(row['quantity'],1) or row['kind'] not in ('refund','replacement') for row in rows)):
                    unresolved('conflicting_records')
                elif not markers[0]['resolution_history_complete']:
                    unresolved('history_incomplete')
                else:
                    compensated = {variant:sum(row['quantity'] for row in rows if row['variant_id'] == variant) for variant in ordered}
                    value = not any(compensated.get(variant,0) > 0 for variant in request.items)
                    scope_known = True
                    if any(compensated.values()) and not all(compensated[v] >= ordered[v] for v in ordered):
                        scope.append('partial_compensation')
            elif tool == 'inventory':
                rows = query(0, sa.and_(db.inventory.c.store_id == order['store_id'], db.inventory.c.variant_id.in_(request.items)))
                payload = {'inventory':rows}
                if (not unique(rows, ('variant_id',))
                    or any(row['store_id'] != order['store_id'] or row['variant_id'] not in request.items
                           or not integer(row['on_hand']) or not integer(row['reserved'])
                           or row['reserved'] > row['on_hand'] for row in rows)):
                    unresolved('conflicting_records')
                elif set(row['variant_id'] for row in rows) != set(request.items):
                    unresolved('inventory_missing', True)
                else:
                    value = all(row['on_hand'] - row['reserved'] >= request.items[row['variant_id']] for row in rows)
    except SQLAlchemyError:
        payload = {}
        unresolved('database_error')
        status = 'unavailable'
    except (ValueError, TypeError, KeyError):
        # Malformed adapter rows cannot supply an established fact.
        unresolved('malformed_records')
    return observation(tool, asdict(request), now, value=value, payload=payload, status=status,
                       stream=stream, dependencies=tuple(dep.dependency() for dep in dependencies),
                       scope_known=scope_known, scope_reasons=scope, reason=reason, expires_at=expiry)
