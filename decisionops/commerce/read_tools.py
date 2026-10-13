"""Typed deterministic read results derived from one PostgreSQL snapshot."""

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Literal

import sqlalchemy as sa

from . import schema as db
from .eligibility import REQUIREMENTS
from .evidence import assess_evidence

TRUSTED_SOURCES = {name: "postgres-" + name for name in REQUIREMENTS}


@dataclass(frozen=True)
class AssessmentRequest:
    order_id: str
    shipment_id: str
    items: dict[str, int]

    def __post_init__(self):
        if not self.order_id or not self.shipment_id or not self.items or len(self.items) > 100:
            raise ValueError("Specify order, shipment and 1–100 variants")
        if any(not isinstance(variant, str) or not variant or type(qty) is not int
               or not 1 <= qty <= 1000 for variant, qty in self.items.items()):
            raise ValueError("Item quantities must be integers from 1 to 1000")


@dataclass(frozen=True)
class ReadToolResult:
    requirement: str
    value: bool | None
    status: Literal["success", "missing", "unavailable"]
    source_id: str
    source_version: str
    order_id: str
    observed_at: str
    details: dict

    def as_record(self):
        return asdict(self)


def canonical(value):
    return json.dumps(value, sort_keys=True, default=lambda obj: obj.isoformat())


def tool_result(name, value, status, request, now, records, **details):
    # A content digest versions the actual rows, including empty history plus its completeness flag.
    version = hashlib.sha256(canonical(records).encode()).hexdigest()
    return ReadToolResult(name, value, status, TRUSTED_SOURCES[name], version,
                          request.order_id, now.isoformat(), {"records": records, **details})


def rows(connection, table, condition):
    query = sa.select(table).where(condition).order_by(*table.primary_key.columns)
    return [dict(row) for row in connection.execute(query).mappings()]


def read_assessment(connection, request, now):
    """Read-only queries. Caller supplies one consistent transaction and UTC clock."""
    order_rows = rows(connection, db.orders, db.orders.c.id == request.order_id)
    if not order_rows:
        tools = [tool_result(name, None, "missing", request, now, [], reason="order_missing")
                 for name in REQUIREMENTS]
        return assemble(request, now, tools, [], None)
    order = order_rows[0]
    line_rows = rows(connection, db.order_lines, db.order_lines.c.order_id == request.order_id)
    ordered = {line["variant_id"]: line["quantity"] for line in line_rows}
    policy_rows = rows(connection, db.policies, sa.and_(
        db.policies.c.id == order["policy_id"], db.policies.c.store_id == order["store_id"]))
    payment_rows = rows(connection, db.payments, db.payments.c.order_id == request.order_id)
    shipment_rows = rows(connection, db.shipments, db.shipments.c.order_id == request.order_id)
    selected = next((row for row in shipment_rows if row["id"] == request.shipment_id), None)
    shipped_rows = rows(connection, db.shipment_lines, sa.and_(
        db.shipment_lines.c.shipment_id == request.shipment_id,
        db.shipment_lines.c.order_id == request.order_id)) if selected else []
    shipped = {row["variant_id"]: row["quantity"] for row in shipped_rows}
    stock_rows = rows(connection, db.inventory, sa.and_(
        db.inventory.c.store_id == order["store_id"],
        db.inventory.c.variant_id.in_(request.items)))
    resolution_rows = rows(connection, db.resolutions, db.resolutions.c.order_id == request.order_id)

    scope = []
    quantities_valid = (all(variant in ordered and qty <= ordered[variant]
                            for variant, qty in request.items.items()) if ordered else None)
    if quantities_valid and request.items != ordered:
        scope.append("partial_request")
    if len(shipment_rows) > 1:
        scope.append("split_shipment")
    if selected and shipped != ordered:
        scope.append("partial_shipment")
    if not selected:
        binding = connection.execute(sa.select(db.shipments.c.order_id).where(
            db.shipments.c.id == request.shipment_id)).scalar_one_or_none()
        if binding is not None:
            scope.append("shipment_order_mismatch")
    compensated = {variant: sum(row["quantity"] for row in resolution_rows
                               if row["variant_id"] == variant) for variant in ordered}
    if any(compensated.values()) and not all(compensated[v] >= ordered[v] for v in ordered):
        scope.append("partial_compensation")

    payment = payment_rows[0] if payment_rows else None
    total_minor = sum(line["quantity"] * line["unit_price_minor"] for line in line_rows)
    paid = (payment["status"] == "paid" and payment["currency"] == order["currency"]
            and payment["amount_minor"] == total_minor) if payment and ordered else None
    policy = policy_rows[0] if policy_rows else None
    carrier_value, carrier_reason = None, "shipment_missing"
    if selected and policy:
        age = (now - selected["carrier_observed_at"]).total_seconds()
        if age < 0 or age > policy["carrier_max_age_seconds"]:
            carrier_reason = "carrier_event_stale_or_future"
        elif selected["carrier_status"] == "lost":
            carrier_value, carrier_reason = True, None
        elif selected["carrier_status"] == "delivered":
            carrier_value, carrier_reason = False, None
        else:
            carrier_reason = "loss_not_confirmed"
    history_complete = order["resolution_history_complete"]
    no_compensation = (not any(compensated.get(variant, 0) > 0 for variant in request.items)
                       if history_complete else None)
    stock = {row["variant_id"]: row["on_hand"] - row["reserved"] for row in stock_rows}
    available = (all(stock[v] >= q for v, q in request.items.items())
                 if all(v in stock for v in request.items) else None)
    tools = [
        tool_result("paid", paid, "success" if payment and ordered else "missing",
                    request, now, {"payment": payment_rows, "lines": line_rows, "currency": order["currency"]}),
        tool_result("shipped", selected["fulfilment_status"] == "shipped" and shipped == ordered
                    if selected and ordered else None, "success" if selected else "missing",
                    request, now, {"shipment": selected, "lines": shipped_rows}, shipment_id=request.shipment_id),
        tool_result("loss_confirmed", carrier_value, "success" if selected else "missing",
                    request, now, selected or {}, shipment_id=request.shipment_id, reason=carrier_reason),
        tool_result("quantities_valid", quantities_valid, "success" if ordered else "missing",
                    request, now, line_rows, requested_items=request.items),
        tool_result("no_previous_compensation", no_compensation, "success", request, now,
                    {"complete": history_complete, "resolutions": resolution_rows},
                    reason=None if history_complete else "history_incomplete"),
        tool_result("stock_available", available, "success" if available is not None else "missing",
                    request, now, stock_rows, available_units=stock, requested_items=request.items),
        tool_result("policy_permits", policy["allow_confirmed_loss"] and sum(request.items.values()) <= policy["max_units"]
                    if policy else None, "success" if policy else "missing", request, now, policy_rows,
                    policy_id=order["policy_id"]),
    ]
    return assemble(request, now, tools, scope, order["policy_id"])


def assemble(request, now, tools, scope, policy_id):
    records = [tool.as_record() for tool in tools]
    result = assess_evidence(records, order_id=request.order_id, supported_case=not scope,
                             now=now, trusted_sources=TRUSTED_SOURCES, max_age_seconds=86400)
    result.update(request=asdict(request), policy_id=policy_id, scope_reasons=scope,
                  read_tools=records)
    return result


def unavailable_assessment(request, now, error_kind):
    tools = [tool_result(name, None, "unavailable", request, now, [], reason=error_kind)
             for name in REQUIREMENTS]
    return assemble(request, now, tools, [], None)
