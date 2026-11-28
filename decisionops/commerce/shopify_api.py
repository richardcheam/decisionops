"""Shopify pilot routes. Membership is enforced before touching a scoped case."""

import base64
import hmac
import json
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .shopify_pilot import ShopifyPilot, Settings, verified_callback
from .shopify_transport import ShopifyUnavailable, domain, gid


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Connect(Body):
    shop: str = Field(max_length=253)


class Start(Body):
    order_id: str = Field(max_length=120)
    fulfillment_line_id: str = Field(max_length=120)


class Binding(Body):
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def install_shopify(app, engine, identity, *, origin, adapter=None):
    if urlsplit(origin).scheme != "https" and adapter is None:
        raise ValueError("Shopify connections require an HTTPS pilot origin")
    service = adapter or ShopifyPilot(engine, Settings.from_environment())
    router = APIRouter(prefix="/pilot-api/shopify")

    def run(fn):
        try:
            return fn()
        except LookupError:
            raise HTTPException(404, "Pilot record not found") from None
        except ShopifyUnavailable:
            raise HTTPException(503, "Shopify evidence could not be verified. Try resync or reconnect.") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @router.get("/callback")
    def callback(request: Request):
        try:
            params = verified_callback(list(request.query_params.multi_items()), service.settings.client_secret)
            state = service.callback_state(params)
            actor = identity.approver(request, state["store_id"])
            service.complete_connection(state, actor.user_id, params["code"])
        except (KeyError, ValueError, ShopifyUnavailable):
            raise HTTPException(400, "Shopify connection could not be verified. Start a new connection.") from None
        return RedirectResponse("/pilot?store_id=" + quote(state["store_id"], safe=""), status_code=303)

    @router.post("/webhooks/uninstalled", status_code=204)
    async def uninstalled(request: Request):
        from starlette.concurrency import run_in_threadpool

        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, "Shopify webhook too large")
        signature = request.headers.get("x-shopify-hmac-sha256", "")
        expected = base64.b64encode(hmac.digest(service.settings.client_secret.encode(), raw, "sha256")).decode()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "Invalid Shopify webhook signature")
        delivery = request.headers.get("x-shopify-webhook-id", "")
        if not delivery or len(delivery) > 128 or request.headers.get("x-shopify-topic") != "app/uninstalled":
            raise HTTPException(400, "Invalid Shopify webhook delivery")
        try:
            value = json.loads(raw)
            shop = domain(value["myshopify_domain"])
            if shop != domain(request.headers.get("x-shopify-shop-domain")):
                raise ValueError
            shop_gid = gid(f'gid://shopify/Shop/{value["id"]}', "Shop")
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "Invalid Shopify webhook shop identity") from None
        try:
            await run_in_threadpool(service.uninstall, shop, shop_gid, delivery, bytes(raw))
        except ShopifyUnavailable:
            raise HTTPException(503, "Shopify uninstall could not be verified") from None
        return Response(status_code=204)

    @router.get("/{store_id}")
    def connection(actor=Depends(identity.staff)):
        return run(lambda: service.connection_status(actor.store_id))

    @router.post("/{store_id}/connect")
    def connect(body: Connect, actor=Depends(identity.approver)):
        return run(lambda: service.begin_connection(actor.store_id, actor.user_id, body.shop, origin))

    @router.get("/{store_id}/orders")
    def orders(actor=Depends(identity.staff)):
        return run(lambda: service.orders(actor.store_id))

    @router.post("/{store_id}/resync")
    def resync(body: Body, actor=Depends(identity.staff)):
        return run(lambda: service.resync(actor.store_id))

    @router.get("/{store_id}/cases")
    def cases(actor=Depends(identity.staff)):
        return run(lambda: service.cases(actor.store_id))

    @router.post("/{store_id}/cases")
    def start(body: Start, actor=Depends(identity.staff)):
        return run(lambda: service.start(actor.store_id, body.order_id, body.fulfillment_line_id))

    @router.post("/{store_id}/cases/{case_id}/propose")
    def propose(case_id: str, body: Body, actor=Depends(identity.staff)):
        return run(lambda: service.propose(actor.store_id, case_id))

    @router.post("/{store_id}/cases/{case_id}/approve")
    def approve(case_id: str, body: Binding, actor=Depends(identity.approver)):
        return run(lambda: service.approve(actor.store_id, case_id, body.proposal_hash, actor.user_id))

    @router.post("/{store_id}/cases/{case_id}/confirm")
    def confirm(case_id: str, body: Binding, actor=Depends(identity.approver)):
        return run(lambda: service.confirm(actor.store_id, case_id, body.proposal_hash, actor.user_id))

    @router.post("/{store_id}/cases/{case_id}/reconcile")
    def reconcile(case_id: str, body: Body, actor=Depends(identity.approver)):
        return run(lambda: service.reconcile(actor.store_id, case_id))

    app.include_router(router)
    return service
