"""Pilot workflow using scoped Shopify evidence and a durable single-send claim."""

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlencode
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from . import schema as db
from .returns import WINDOW_DAYS
from .shopify_transport import LINE_LIMIT, Remote, ShopifyGateway, ShopifyRejected, ShopifyUnauthorized, ShopifyUnavailable, domain, gid, nodes


CALLBACK = "/pilot-api/shopify/callback"
POLICY = f"shopify-test-return-one-unit-v1:{WINDOW_DAYS}-days"


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str = field(repr=False)
    key: bytes = field(repr=False)
    dev_shops: frozenset[str]

    @classmethod
    def from_environment(cls):
        try:
            key = base64.b64decode(os.environ["COMMERCE_SHOPIFY_TOKEN_KEY"], altchars=b"-_", validate=True)
            client = os.environ["COMMERCE_SHOPIFY_CLIENT_ID"]
            secret = os.environ["COMMERCE_SHOPIFY_CLIENT_SECRET"]
            shops = frozenset(domain(shop.strip()) for shop in os.environ["COMMERCE_SHOPIFY_DEV_SHOPS"].split(","))
            if len(key) != 32 or not client.strip() or not secret.strip():
                raise ValueError
        except (KeyError, ValueError):
            raise RuntimeError("Configure Shopify client ID, secret, development shops and a 32-byte base64 token key") from None
        return cls(client, secret, key, shops)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


def verified_callback(items, secret):
    query = dict(items)
    if len(query) != len(items) or any(not isinstance(value, str) or len(value) > 2048 for value in query.values()):
        raise ValueError("Invalid Shopify callback")
    proof = query.pop("hmac", "")
    signed = urlencode(sorted(query.items())).encode()
    if not hmac.compare_digest(proof, hmac.digest(secret.encode(), signed, "sha256").hex()):
        raise ValueError("Invalid Shopify callback signature")
    timestamp = query.get("timestamp", "")
    if not timestamp.isascii() or not timestamp.isdecimal() or len(timestamp) > 12 or abs(int(timestamp) - utcnow().timestamp()) > 600:
        raise ValueError("Expired Shopify callback")
    if not query.get("code") or not query.get("state"):
        raise ValueError("Missing Shopify callback values")
    return query


def token_record(reply):
    scope = reply.get("scope")
    access, refresh = reply.get("access_token"), reply.get("refresh_token")
    expires, refresh_expires = reply.get("expires_in"), reply.get("refresh_token_expires_in")
    if (not isinstance(scope, str) or not {"read_orders", "write_returns"} <= set(scope.split(","))
            or not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
            or type(expires) is not int or not 30 < expires <= 24 * 3600
            or type(refresh_expires) is not int or not 0 < refresh_expires <= 120 * 24 * 3600):
        raise ShopifyUnavailable("Shopify did not grant the required expiring offline access")
    now = utcnow().timestamp()
    return {"access": access, "refresh": refresh, "expires_at": now + expires,
            "refresh_expires_at": now + refresh_expires}


def project_order(order):
    """Extract the bounded, non-customer evidence used by the workflow."""
    identity = gid(order.get("id"), "Order")
    if order.get("test") is not True:
        raise ShopifyUnavailable("Only Shopify test orders are supported")
    fulfillments = order.get("fulfillments")
    if not isinstance(fulfillments, list) or len(fulfillments) > LINE_LIMIT:
        raise ShopifyUnavailable("Shopify fulfillment evidence exceeds the pilot limit")
    lines = {}
    for fulfillment in fulfillments:
        for node in nodes(fulfillment.get("fulfillmentLineItems")):
            line_id = gid(node.get("id"), "FulfillmentLineItem")
            line_item, quantity = node.get("lineItem"), node.get("quantity")
            if line_id in lines or not isinstance(line_item, dict) or type(quantity) is not int or quantity < 1:
                raise ShopifyUnavailable("Shopify fulfillment-line evidence is incomplete")
            lines[line_id] = {
                "fulfillment_line_id": line_id,
                "title": str(line_item.get("title") or "Item")[:200],
                "sku": str(line_item.get("sku") or "")[:120],
                "quantity": quantity,
                "delivered_at": fulfillment.get("deliveredAt"),
                "status": fulfillment.get("status"),
            }
    version = order.get("updatedAt")
    if not isinstance(version, str) or not version:
        raise ShopifyUnavailable("Shopify order version is missing")
    return {"order_id": identity, "name": str(order.get("name") or "Test order")[:120],
            "lines": list(lines.values()), "version": version, "cancelled": order.get("cancelledAt") is not None}


def eligibility(snapshot, line, remaining, now):
    if snapshot["cancelled"]:
        return False, "Shopify order is canceled"
    delivered = line.get("delivered_at")
    if line.get("status") != "SUCCESS" or not isinstance(delivered, str):
        return False, "Verified delivery is required"
    try:
        at = datetime.fromisoformat(delivered)
        if at.tzinfo is None or at > now:
            raise ValueError
    except (TypeError, ValueError):
        return False, "Verified delivery evidence is incomplete"
    if now > at + timedelta(days=WINDOW_DAYS):
        return False, "Return window has closed"
    if line.get("sku") == "return-final-sale":
        return False, "This item is final sale under the pilot policy"
    if type(remaining) is not int or remaining < 1:
        return False, "Shopify does not show a remaining returnable unit"
    return True, "Eligible for one unit"


def _bound_evidence(store, shop, snapshot, line, remaining):
    return {
        "policy": POLICY, "store_id": store, "shop_gid": shop, "order_id": snapshot["order_id"],
        "order_version": snapshot["version"], "fulfillment_line_id": line["fulfillment_line_id"],
        "delivered_at": line["delivered_at"], "sku": line["sku"], "quantity": 1,
        "fulfilled_quantity": line["quantity"], "returnable_quantity": remaining,
    }


def _case_view(row):
    result = {key: row[key] for key in ("id", "order_id", "fulfillment_line_id", "quantity",
                                       "status", "reason", "proposal_hash", "external_return_id", "evidence")}
    result["dispatched"] = row["dispatch_marker"] is not None
    return result


class ShopifyPilot:
    def __init__(self, engine, settings, *, gateway=None, now=utcnow):
        self.engine = engine
        self.settings = settings
        self.gateway = gateway or ShopifyGateway(settings.client_id, settings.client_secret)
        self.now = now

    def _connection(self):
        return self.engine.connect().execution_options(isolation_level="READ COMMITTED")

    def _shop_lock(self, connection, shop):
        connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:shop, 10202610))"), {"shop": shop})

    def _seal(self, store, shop, value):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self.settings.key).encrypt(
            nonce, json.dumps(value).encode(), f"{store}:{shop}".encode())
        return base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def _unseal(self, row):
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        try:
            raw = base64.urlsafe_b64decode(row["sealed_token"])
            aad = f'{row["store_id"]}:{row["shop"]}'.encode()
            return json.loads(AESGCM(self.settings.key).decrypt(raw[:12], raw[12:], aad))
        except (ValueError, InvalidTag):
            raise ShopifyUnavailable("Reconnect the Shopify installation") from None

    def _binding(self, connection, store, lock=False):
        query = sa.select(db.shopify_connections).where(db.shopify_connections.c.store_id == store)
        return connection.execute(query.with_for_update() if lock else query).mappings().one_or_none()

    def connection_status(self, store):
        with self._connection() as connection:
            row = self._binding(connection, store)
        return {"shop": row["shop"] if row else None, "connected": bool(row and row["status"] == "connected")}

    def begin_connection(self, store, actor, shop, origin):
        shop = domain(shop)
        if shop not in self.settings.dev_shops:
            raise ValueError("That Shopify development shop is outside this pilot")
        state = secrets.token_urlsafe(32)
        with self._connection() as connection, connection.begin():
            existing = self._binding(connection, store)
            if existing and existing["shop"] != shop:
                raise ValueError("This workspace is already bound to a different Shopify shop")
            if connection.execute(sa.select(db.shopify_connections.c.store_id).where(
                    db.shopify_connections.c.shop == shop, db.shopify_connections.c.store_id != store)).first():
                raise ValueError("That Shopify shop is already connected to a workspace")
            connection.execute(db.shopify_oauth.delete().where(db.shopify_oauth.c.expires_at < self.now()))
            connection.execute(db.shopify_oauth.insert().values(
                state_hash=digest(state.encode()), store_id=store, actor_id=actor, shop=shop,
                expires_at=self.now() + timedelta(minutes=8),
            ))
        return {"url": self.gateway.authorization_url(shop, origin + CALLBACK, state)}

    def callback_state(self, params):
        state_hash = digest(params["state"].encode())
        with self._connection() as connection:
            state = connection.execute(sa.select(db.shopify_oauth).where(
                db.shopify_oauth.c.state_hash == state_hash)).mappings().one_or_none()
        if not state or state["expires_at"] <= self.now() or state["shop"] != domain(params["shop"]):
            raise ValueError("The Shopify connection link is invalid or expired")
        return state

    def complete_connection(self, state, actor, code):
        if state["actor_id"] != actor:
            raise ValueError("Sign in as the manager who started this connection")
        store, shop = state["store_id"], state["shop"]
        if shop not in self.settings.dev_shops:
            raise ValueError("That Shopify development shop is outside this pilot")
        # Consume before calling OAuth. A failed exchange needs a new connection attempt.
        with self._connection() as connection, connection.begin():
            consumed = connection.execute(db.shopify_oauth.delete().where(
                db.shopify_oauth.c.state_hash == state["state_hash"],
                db.shopify_oauth.c.expires_at > self.now(),
            ).returning(db.shopify_oauth.c.state_hash)).scalar_one_or_none()
            if consumed is None:
                raise ValueError("The Shopify connection link was already used")
        with self._connection() as connection, connection.begin():
            self._shop_lock(connection, shop)
            # Serialize the first installation for this store even when its connection row does not exist.
            connection.execute(sa.select(db.pilot_stores.c.id).where(db.pilot_stores.c.id == store).with_for_update()).scalar_one()
            existing = self._binding(connection, store, lock=True)
            same_shop = connection.execute(sa.select(db.shopify_connections.c.store_id).where(
                db.shopify_connections.c.shop == shop)).scalar_one_or_none()
            if (existing and existing["shop"] != shop) or same_shop not in (None, store):
                raise ValueError("That connection would change the workspace's Shopify binding")
            value = token_record(self.gateway.exchange(shop, code))
            shop_gid = self.gateway.shop_identity(Remote(shop, value["access"]))
            if existing and existing["shop_gid"] != shop_gid:
                raise ValueError("The Shopify shop identity changed")
            values = {"shop": shop, "shop_gid": shop_gid, "sealed_token": self._seal(store, shop, value),
                      "status": "connected"}
            if existing:
                connection.execute(db.shopify_connections.update().where(
                    db.shopify_connections.c.store_id == store).values(**values))
            else:
                connection.execute(db.shopify_connections.insert().values(store_id=store, **values))

    def remote(self, store):
        with self._connection() as connection, connection.begin():
            first = self._binding(connection, store)
            if first is None:
                raise ValueError("Connect a Shopify development store first")
            self._shop_lock(connection, first["shop"])
            row = self._binding(connection, store, lock=True)
            if row["status"] != "connected" or row["shop"] not in self.settings.dev_shops:
                raise ValueError("Reconnect the Shopify development store")
            token = self._unseal(row)
            now = self.now().timestamp()
            if token["expires_at"] <= now + 25:
                if token["refresh_expires_at"] <= now:
                    raise ShopifyUnavailable("Reconnect the expired Shopify installation")
                token = token_record(self.gateway.refresh(row["shop"], token["refresh"]))
                connection.execute(db.shopify_connections.update().where(
                    db.shopify_connections.c.store_id == store).values(
                        sealed_token=self._seal(store, row["shop"], token)))
            return Remote(row["shop"], token["access"]), row["shop_gid"]

    def resync(self, store):
        remote, _ = self.remote(store)
        eligible_orders = []
        for order in self.gateway.orders(remote):
            if order.get("test") is not True:
                continue
            try:
                snapshot = project_order(order)
                returnable = self.gateway.returnable(remote, snapshot["order_id"])
            except (ValueError, ShopifyUnavailable):
                # An incomplete order remains unavailable for case creation.
                continue
            for line in snapshot["lines"]:
                line["eligible"], line["reason"] = eligibility(
                    snapshot, line, returnable.get(line["fulfillment_line_id"], 0), self.now())
            eligible_orders.append(snapshot)
        with self._connection() as connection, connection.begin():
            self._shop_lock(connection, remote.shop)
            current = self._binding(connection, store, lock=True)
            if current is None or current["status"] != "connected" or current["shop"] != remote.shop:
                raise ShopifyUnavailable("Shopify connection changed during import")
            for row in eligible_orders:
                upsert = insert(db.shopify_orders).values(store_id=store, order_id=row["order_id"], snapshot=row)
                connection.execute(upsert.on_conflict_do_update(
                    index_elements=["store_id", "order_id"], set_={"snapshot": upsert.excluded.snapshot}))
        return self.orders(store)

    def orders(self, store):
        with self._connection() as connection:
            return connection.execute(sa.select(db.shopify_orders.c.snapshot).where(
                db.shopify_orders.c.store_id == store).order_by(db.shopify_orders.c.order_id)).scalars().all()

    def _case(self, connection, store, case_id, lock=False):
        query = sa.select(db.shopify_cases).where(
            db.shopify_cases.c.store_id == store, db.shopify_cases.c.id == case_id)
        row = connection.execute(query.with_for_update() if lock else query).mappings().one_or_none()
        if row is None:
            raise LookupError("Return case not found")
        return row

    def cases(self, store):
        with self._connection() as connection:
            rows = connection.execute(sa.select(db.shopify_cases).where(
                db.shopify_cases.c.store_id == store).order_by(db.shopify_cases.c.created_at.desc())).mappings()
            return [_case_view(row) for row in rows]

    def start(self, store, order_id, line_id):
        gid(order_id, "Order")
        gid(line_id, "FulfillmentLineItem")
        with self._connection() as connection, connection.begin():
            order = connection.execute(sa.select(db.shopify_orders.c.snapshot).where(
                db.shopify_orders.c.store_id == store, db.shopify_orders.c.order_id == order_id)).scalar_one_or_none()
            line = next((line for line in order["lines"] if line["fulfillment_line_id"] == line_id), None) if order else None
            if line is None:
                raise LookupError("Imported order line not found")
            connection.execute(insert(db.shopify_cases).values(
                id=str(uuid4()), store_id=store, order_id=order_id, fulfillment_line_id=line_id,
                quantity=1, status="draft", reason=line["reason"], created_at=self.now(),
            ).on_conflict_do_nothing(index_elements=["store_id", "order_id", "fulfillment_line_id"]))
            row = connection.execute(sa.select(db.shopify_cases).where(
                db.shopify_cases.c.store_id == store, db.shopify_cases.c.order_id == order_id,
                db.shopify_cases.c.fulfillment_line_id == line_id)).mappings().one()
            return _case_view(row)

    def _save(self, connection, row, **values):
        updated = connection.execute(db.shopify_cases.update().where(
            db.shopify_cases.c.store_id == row["store_id"], db.shopify_cases.c.id == row["id"],
        ).values(**values).returning(db.shopify_cases)).mappings().one()
        return _case_view(updated)

    def _fresh(self, row, remote, shop):
        snapshot = project_order(self.gateway.order(remote, row["order_id"]))
        if snapshot["order_id"] != row["order_id"]:
            raise ShopifyUnavailable("Shopify returned a different order")
        line = next((line for line in snapshot["lines"] if line["fulfillment_line_id"] == row["fulfillment_line_id"]), None)
        if not line:
            return None, "The fulfillment line is no longer present"
        remaining = self.gateway.returnable(remote, row["order_id"]).get(row["fulfillment_line_id"], 0)
        allowed, reason = eligibility(snapshot, line, remaining, self.now())
        if not allowed:
            return None, reason
        return _bound_evidence(row["store_id"], shop, snapshot, line, remaining), reason

    def propose(self, store, case_id):
        with self._connection() as connection:
            previous = self._case(connection, store, case_id)
        if previous["dispatch_marker"] is not None or previous["status"] not in ("draft", "needs_review"):
            raise ValueError("This case cannot submit a new proposal")
        remote, shop = self.remote(store)
        evidence, reason = self._fresh(previous, remote, shop)
        with self._connection() as connection, connection.begin():
            row = self._case(connection, store, case_id, lock=True)
            if row["dispatch_marker"] is not None or row["status"] not in ("draft", "needs_review"):
                raise ValueError("This case changed before submission")
            proposal = digest(json.dumps(
                {"case_id": case_id, "generation": str(uuid4()), "evidence": evidence}, sort_keys=True,
            ).encode()) if evidence else None
            return self._save(connection, row, status="proposed" if proposal else "needs_review",
                              reason=reason, evidence=evidence, proposal_hash=proposal, approved_by=None)

    def approve(self, store, case_id, proposal_hash, actor):
        with self._connection() as connection, connection.begin():
            row = self._case(connection, store, case_id, lock=True)
            if row["status"] not in ("proposed", "approved") or row["proposal_hash"] != proposal_hash:
                raise ValueError("Approve the exact current proposal")
            if row["status"] == "approved":
                return _case_view(row)
            return self._save(connection, row, status="approved", reason="Approved, awaiting separate confirmation",
                              approved_by=actor)

    def confirm(self, store, case_id, proposal_hash, actor):
        with self._connection() as connection:
            previous = self._case(connection, store, case_id)
        if previous["proposal_hash"] != proposal_hash:
            raise ValueError("Confirm the exact approved proposal")
        if previous["dispatch_marker"] is not None:
            return _case_view(previous)
        if previous["status"] != "approved" or previous["approved_by"] is None:
            raise ValueError("Manager approval is required before confirmation")
        remote, shop = self.remote(store)
        with self._connection() as connection, connection.begin():
            self._shop_lock(connection, remote.shop)
            bound = self._binding(connection, store, lock=True)
            if bound is None or bound["status"] != "connected" or bound["shop_gid"] != shop:
                raise ValueError("The Shopify connection changed")
            row = self._case(connection, store, case_id, lock=True)
            if row["proposal_hash"] != proposal_hash:
                raise ValueError("Confirm the exact approved proposal")
            if row["dispatch_marker"] is not None:
                return _case_view(row)
            if row["status"] != "approved" or row["approved_by"] is None:
                raise ValueError("Manager approval is required before confirmation")
            evidence, reason = self._fresh(row, remote, shop)
            if not evidence or evidence != row["evidence"]:
                return self._save(connection, row, status="needs_review", evidence=evidence,
                                  reason=reason if not evidence else "Shopify evidence changed after approval",
                                  approved_by=None, proposal_hash=None)
            marker = f"DecisionOps pilot return {uuid4()}"
            self._save(connection, row, status="pending", dispatch_marker=marker,
                       confirmed_by=actor, reason="Waiting for verified Shopify read-back")

        # A committed marker fences every subsequent invocation, including after process death.
        try:
            remote_id = self.gateway.create_return(remote, row["order_id"], row["fulfillment_line_id"], marker)
        except (ShopifyRejected, ShopifyUnavailable, ValueError):
            return self.reconcile(store, case_id)
        with self._connection() as connection, connection.begin():
            current = self._case(connection, store, case_id, lock=True)
            if current["status"] == "verified":
                return _case_view(current)
            if current["external_return_id"] not in (None, remote_id):
                return self._save(connection, current, status="needs_review",
                                  reason="Shopify returned conflicting references. Staff review required.")
            self._save(connection, current, external_return_id=remote_id)
        return self.reconcile(store, case_id)

    def reconcile(self, store, case_id):
        with self._connection() as connection:
            row = self._case(connection, store, case_id)
        if row["status"] == "verified":
            return _case_view(row)
        if row["dispatch_marker"] is None:
            raise ValueError("Only a sent Shopify return can be reconciled")
        try:
            remote, shop = self.remote(store)
            if shop != row["evidence"]["shop_gid"]:
                raise ShopifyUnavailable("The Shopify installation changed")
            if row["external_return_id"]:
                options = [self.gateway.read_return(remote, row["external_return_id"])]
            else:
                options = self.gateway.order_returns(remote, row["order_id"])
            matches = [item["id"] for item in options if self._matches_return(item, row)]
        except (ShopifyUnavailable, ValueError, KeyError, TypeError):
            matches = []
        with self._connection() as connection, connection.begin():
            current = self._case(connection, store, case_id, lock=True)
            if current["status"] == "verified":
                return _case_view(current)
            if len(matches) == 1 and current["external_return_id"] in (None, matches[0]):
                return self._save(connection, current, status="verified", external_return_id=matches[0],
                                  reason="Shopify return verified by read-back")
            return self._save(connection, current, status="needs_review",
                              reason="Shopify outcome could not be verified. Reconcile only; do not create again.")

    @staticmethod
    def _matches_return(item, row):
        if (not isinstance(item, dict) or item.get("status") != "OPEN"
                or (item.get("order") or {}).get("id") != row["order_id"]):
            return False
        identity = gid(item.get("id"), "Return")
        if row["external_return_id"] not in (None, identity):
            return False
        lines = nodes(item.get("returnLineItems"))
        if len(lines) != 1:
            return False
        line = lines[0]
        return (line.get("__typename") == "ReturnLineItem"
                and line.get("returnReasonNote") == row["dispatch_marker"]
                and type(line.get("quantity")) is int and line["quantity"] == row["quantity"]
                and (line.get("fulfillmentLineItem") or {}).get("id") == row["fulfillment_line_id"])

    def uninstall(self, shop, shop_gid, delivery, body):
        with self._connection() as connection, connection.begin():
            self._shop_lock(connection, shop)
            row = connection.execute(sa.select(db.shopify_connections).where(
                db.shopify_connections.c.shop == shop, db.shopify_connections.c.shop_gid == shop_gid,
            ).with_for_update()).mappings().one_or_none()
            if row is None:
                return
            inserted = connection.execute(insert(db.shopify_webhooks).values(
                store_id=row["store_id"], delivery_id=delivery, body_digest=digest(body),
            ).on_conflict_do_nothing().returning(db.shopify_webhooks.c.delivery_id)).scalar_one_or_none()
            if inserted is None or row["status"] != "connected":
                return
            # A delayed uninstall can belong to an earlier grant. Check the current grant.
            token = self._unseal(row)
            if token["expires_at"] <= self.now().timestamp():
                raise ShopifyUnavailable("Reconnect before the uninstall can be verified")
            try:
                self.gateway.shop_identity(Remote(shop, token["access"]))
            except ShopifyUnauthorized:
                connection.execute(db.shopify_connections.update().where(
                    db.shopify_connections.c.store_id == row["store_id"],
                ).values(status="revoked", sealed_token=""))
