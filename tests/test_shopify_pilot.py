"""Shopify API tests with real memberships and PostgreSQL, using a fake remote."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hmac
import os
from unittest import TestCase, skipUnless
from urllib.parse import parse_qs, urlencode, urlsplit

from test_pilot_identity import PilotIdentityFixture


SHOP = "first-pilot.myshopify.com"
ORDER = "gid://shopify/Order/1"
LINE = "gid://shopify/FulfillmentLineItem/2"
RETURN = "gid://shopify/Return/3"


def connection(items):
    return {"nodes": items, "pageInfo": {"hasNextPage": False}}


class FakeShopify:
    def __init__(self):
        self.create_count = 0
        self.timeout = False
        self.visible = True
        self.return_record = None
        self.snapshot = {
            "id": ORDER, "test": True, "name": "#12", "updatedAt": "version-1", "cancelledAt": None,
            "fulfillments": [{
                "status": "SUCCESS",
                "deliveredAt": datetime.now(timezone.utc).isoformat(),
                "fulfillmentLineItems": connection([
                    {"id": LINE, "quantity": 1, "lineItem": {"title": "Tote", "sku": "tote"}},
                ]),
            }],
        }

    def authorization_url(self, shop, callback, state):
        return f"https://{shop}/authorize?" + urlencode({"state": state})

    def exchange(self, shop, code):
        return {"scope": "read_orders,write_returns,read_returns", "access_token": "fake-access",
                "refresh_token": "fake-refresh", "expires_in": 86400, "refresh_token_expires_in": 2592000}

    def shop_identity(self, remote):
        return "gid://shopify/Shop/1"

    def orders(self, remote):
        return [deepcopy(self.snapshot)]

    def order(self, remote, order_id):
        return deepcopy(self.snapshot)

    def returnable(self, remote, order_id):
        return {LINE: 1}

    def create_return(self, remote, order_id, line_id, marker):
        from decisionops.commerce.shopify_transport import ShopifyUnavailable

        self.create_count += 1
        self.return_record = {"id": RETURN, "status": "OPEN", "order": {"id": order_id},
                              "returnLineItems": connection([{
                                  "__typename": "ReturnLineItem", "quantity": 1, "returnReasonNote": marker,
                                  "fulfillmentLineItem": {"id": line_id},
                              }])}
        if self.timeout:
            raise ShopifyUnavailable("Simulated timeout after commit")
        return RETURN

    def read_return(self, remote, return_id):
        return self.return_record if self.visible else None

    def order_returns(self, remote, order_id):
        return [self.return_record] if self.visible and self.return_record else []


@skipUnless(os.environ.get("COMMERCE_TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class ShopifyPilotTests(PilotIdentityFixture, TestCase):
    def setUp(self):
        super().setUp()
        from decisionops.commerce.shopify_api import install_shopify
        from decisionops.commerce.shopify_pilot import Settings, ShopifyPilot

        self.settings = Settings("fake-client", "fake-secret", b"x" * 32, frozenset({SHOP}))
        self.remote = FakeShopify()
        service = ShopifyPilot(self.engine, self.settings, gateway=self.remote)
        install_shopify(self.app, self.engine, self.identity, origin=self.origin, adapter=service)

    def post(self, client, path, body=None, expected=200, store="shop-a"):
        response = client.post(f"/pilot-api/shopify/{store}{path}", json=body or {}, headers=self.headers)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def connected(self):
        manager, support, other = self.client(), self.client(), self.client()
        self.assertEqual(self.login(manager).status_code, 200)
        self.assertEqual(self.login(other, self.other).status_code, 200)
        self.assertEqual(self.accept(support, self.invite(manager)).status_code, 200)
        self.post(manager, "/connect", {"shop": "unauthorized.myshopify.com"}, expected=409)
        url = self.post(manager, "/connect", {"shop": SHOP})["url"]
        query = {"state": parse_qs(urlsplit(url).query)["state"][0], "shop": SHOP, "code": "fake-code",
                 "timestamp": str(int(datetime.now(timezone.utc).timestamp()))}
        query["hmac"] = hmac.digest(self.settings.client_secret.encode(),
                                   urlencode(sorted(query.items())).encode(), "sha256").hex()
        callback = "/pilot-api/shopify/callback"
        self.assertEqual(manager.get(callback, params={**query, "hmac": "invalid"}).status_code, 400)
        self.assertEqual(manager.get(callback, params=query, follow_redirects=False).status_code, 303)
        self.assertEqual(manager.get(callback, params=query).status_code, 400)
        self.assertEqual(self.post(support, "/resync")[0]["order_id"], ORDER)
        return manager, support, other

    def approved(self):
        manager, support, other = self.connected()
        request = {"order_id": ORDER, "fulfillment_line_id": LINE}
        self.post(other, "/cases", request, expected=404, store="shop-b")
        self.post(other, "/cases", request, expected=404)
        case = self.post(support, "/cases", request)
        path = "/cases/" + case["id"]
        self.assertEqual(self.post(support, "/cases", request)["id"], case["id"])
        self.post(other, path + "/propose", expected=404, store="shop-b")
        proposal = self.post(support, path + "/propose")
        binding = {"proposal_hash": proposal["proposal_hash"]}
        self.post(support, path + "/approve", binding, expected=403)
        self.post(support, path + "/confirm", binding, expected=403)
        self.post(manager, path + "/confirm", binding, expected=409)
        self.post(manager, path + "/approve", {"proposal_hash": "0" * 64}, expected=409)
        self.assertEqual(self.post(manager, path + "/approve", binding)["status"], "approved")
        self.assertEqual(self.remote.create_count, 0)
        return manager, path, binding

    def test_exact_approval_and_concurrent_confirmation(self):
        manager, path, binding = self.approved()
        second = self.client()
        self.assertEqual(self.login(second).status_code, 200)
        with ThreadPoolExecutor(max_workers=2) as jobs:
            results = list(jobs.map(lambda client: self.post(client, path + "/confirm", binding),
                                    [manager, second]))
        self.assertIn("verified", {row["status"] for row in results})
        self.assertEqual(self.post(manager, path + "/confirm", binding)["external_return_id"], RETURN)
        self.assertEqual(self.remote.create_count, 1)

    def test_stale_approval_refers_without_sending(self):
        manager, path, binding = self.approved()
        self.remote.snapshot["updatedAt"] = "version-2"
        result = self.post(manager, path + "/confirm", binding)
        self.assertEqual(result["status"], "needs_review")
        self.assertIsNone(result["proposal_hash"])
        self.assertEqual(self.remote.create_count, 0)

    def test_accepted_timeout_never_resends(self):
        manager, path, binding = self.approved()
        self.remote.timeout = True
        self.remote.visible = False
        self.assertEqual(self.post(manager, path + "/confirm", binding)["status"], "needs_review")
        self.assertEqual(self.post(manager, path + "/confirm", binding)["status"], "needs_review")
        self.remote.visible = True
        result = self.post(manager, path + "/reconcile")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["external_return_id"], RETURN)
        self.assertEqual(self.remote.create_count, 1)

    def test_uninstall_dedupe_preserves_a_new_valid_grant(self):
        import base64
        import json

        from decisionops.commerce.shopify_transport import ShopifyUnauthorized, ShopifyUnavailable

        manager, _, _ = self.connected()
        payload = json.dumps({"id": 1, "myshopify_domain": SHOP}).encode()
        headers = {
            "x-shopify-topic": "app/uninstalled",
            "x-shopify-shop-domain": SHOP,
            "x-shopify-webhook-id": "old-grant",
            "x-shopify-hmac-sha256": base64.b64encode(
                hmac.digest(self.settings.client_secret.encode(), payload, "sha256")).decode(),
        }
        webhook = "/pilot-api/shopify/webhooks/uninstalled"
        status = "/pilot-api/shopify/shop-a"
        self.assertEqual(manager.post(webhook, content=payload, headers={
            **headers, "x-shopify-hmac-sha256": "invalid"}).status_code, 401)
        self.assertEqual(manager.post(webhook, content=payload, headers=headers).status_code, 204)
        self.assertTrue(manager.get(status).json()["connected"])

        def unavailable(remote):
            raise ShopifyUnavailable("Simulated transient outage")

        retry_headers = {**headers, "x-shopify-webhook-id": "current-grant"}
        self.remote.shop_identity = unavailable
        self.assertEqual(manager.post(webhook, content=payload, headers=retry_headers).status_code, 503)
        self.assertTrue(manager.get(status).json()["connected"])

        def rejected(remote):
            raise ShopifyUnauthorized("Simulated revoked credential")

        self.remote.shop_identity = rejected
        self.assertEqual(manager.post(webhook, content=payload, headers=headers).status_code, 204)
        self.assertTrue(manager.get(status).json()["connected"])
        self.assertEqual(manager.post(webhook, content=payload, headers=retry_headers).status_code, 204)
        self.assertFalse(manager.get(status).json()["connected"])
