"""Bounded Shopify Admin transport for fictional development-store orders."""

from dataclasses import dataclass, field
import json
import re
from urllib.parse import urlencode


API_VERSION = "2026-10"
SCOPES = ("read_orders", "read_returns", "write_returns")
SHOP = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com")
ORDER_LIMIT = 10
LINE_LIMIT = 8
RETURN_LIMIT = 10

SHOP_QUERY = "query PilotShop { shop { id myshopifyDomain } }"
ORDER_FIELDS = f"""
    id name test updatedAt cancelledAt
    fulfillments(first: {LINE_LIMIT + 1}) {{
        id deliveredAt status
        fulfillmentLineItems(first: {LINE_LIMIT}) {{
            pageInfo {{ hasNextPage }}
            nodes {{ id quantity lineItem {{ id title sku }} }}
        }}
    }}
"""
ORDER_LIST = f"""
query PilotOrders {{
    orders(first: {ORDER_LIMIT}, reverse: true, query: "test:true") {{
        nodes {{ id test }}
    }}
}}
"""
ORDER_QUERY = f"""
query PilotOrder($id: ID!) {{ order(id: $id) {{ {ORDER_FIELDS} }} }}
"""
RETURNABLE_QUERY = f"""
query PilotReturnable($id: ID!) {{
    returnableFulfillments(orderId: $id, first: {LINE_LIMIT}) {{
        pageInfo {{ hasNextPage }}
        nodes {{
            returnableFulfillmentLineItems(first: {LINE_LIMIT}) {{
                pageInfo {{ hasNextPage }}
                nodes {{ quantity fulfillmentLineItem {{ id }} }}
            }}
        }}
    }}
}}
"""
RETURN_FIELDS = f"""
    id status order {{ id }}
    returnLineItems(first: {LINE_LIMIT}) {{
        pageInfo {{ hasNextPage }}
        nodes {{
            __typename
            ... on ReturnLineItem {{ quantity returnReasonNote fulfillmentLineItem {{ id }} }}
        }}
    }}
"""
RETURN_QUERY = f"query PilotReturn($id: ID!) {{ return(id: $id) {{ {RETURN_FIELDS} }} }}"
ORDER_RETURNS = f"""
query PilotOrderReturns($id: ID!, $after: String) {{
    order(id: $id) {{
        id test
        returns(first: {RETURN_LIMIT}, after: $after) {{
            pageInfo {{ hasNextPage endCursor }}
            nodes {{ {RETURN_FIELDS} }}
        }}
    }}
}}
"""
RETURN_CREATE = """
mutation PilotReturnCreate($input: ReturnInput!) {
    returnCreate(returnInput: $input) {
        return { id }
        userErrors { field }
    }
}
"""


class ShopifyUnavailable(RuntimeError):
    """The remote state could not be established."""


class ShopifyUnauthorized(ShopifyUnavailable):
    """Shopify rejected the current credential."""


class ShopifyRejected(RuntimeError):
    """Shopify explicitly rejected the mutation."""


def domain(value):
    if not isinstance(value, str) or not SHOP.fullmatch(value):
        raise ValueError("Enter the store's exact myshopify.com domain")
    return value


def gid(value, kind):
    if not isinstance(value, str) or not re.fullmatch(rf"gid://shopify/{kind}/[0-9]{{1,32}}", value):
        raise ValueError("Invalid Shopify identifier")
    return value


def nodes(connection, *, complete=True):
    try:
        items = connection["nodes"]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError
        if complete and connection["pageInfo"]["hasNextPage"] is not False:
            raise ValueError
        return items
    except (KeyError, TypeError, ValueError):
        raise ShopifyUnavailable("Shopify evidence is incomplete") from None


@dataclass(frozen=True)
class Remote:
    shop: str
    access_token: str = field(repr=False)


class ShopifyGateway:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret

    def authorization_url(self, shop, callback, state):
        return f"https://{domain(shop)}/admin/oauth/authorize?" + urlencode({
            "client_id": self.client_id, "scope": ",".join(SCOPES),
            "redirect_uri": callback, "state": state,
        })

    def _post(self, shop, path, body, headers=None, *, form=False):
        import httpx

        url = f"https://{domain(shop)}{path}"
        try:
            with httpx.Client(timeout=12, trust_env=False, follow_redirects=False) as client:
                payload = {"data": body} if form else {"json": body}
                with client.stream("POST", url, headers=headers, **payload) as response:
                    if response.status_code == 401 and path.endswith("/graphql.json"):
                        raise ShopifyUnauthorized("Shopify rejected the connection")
                    actual_version = response.headers.get("x-shopify-api-version")
                    if (response.status_code != 200 or
                            path.endswith("/graphql.json") and actual_version not in (None, API_VERSION)):
                        raise ShopifyUnavailable("Shopify returned an unexpected response")
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 2_000_000:
                            raise ShopifyUnavailable("Shopify response exceeds the pilot limit")
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError
            return parsed
        except (httpx.HTTPError, ValueError):
            raise ShopifyUnavailable("Shopify could not be reached or verified") from None

    def exchange(self, shop, code):
        return self._post(shop, "/admin/oauth/access_token", {
            "client_id": self.client_id, "client_secret": self.client_secret, "code": code,
            "expiring": 1,
        }, form=True)

    def refresh(self, shop, refresh_token):
        return self._post(shop, "/admin/oauth/access_token", {
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }, form=True)

    def graphql(self, remote, query, variables=None):
        result = self._post(remote.shop, f"/admin/api/{API_VERSION}/graphql.json",
                            {"query": query, "variables": variables or {}},
                            {"X-Shopify-Access-Token": remote.access_token})
        if result.get("errors") or not isinstance(result.get("data"), dict):
            raise ShopifyUnavailable("Shopify could not verify the requested evidence")
        return result["data"]

    def shop_identity(self, remote):
        shop = self.graphql(remote, SHOP_QUERY).get("shop")
        if not isinstance(shop, dict) or shop.get("myshopifyDomain") != remote.shop:
            raise ShopifyUnavailable("The Shopify installation does not match this shop")
        return gid(shop.get("id"), "Shop")

    def orders(self, remote):
        data = self.graphql(remote, ORDER_LIST)
        for item in nodes(data.get("orders"), complete=False):
            if item.get("test") is True:
                yield self.order(remote, gid(item.get("id"), "Order"))

    def order(self, remote, order_id):
        data = self.graphql(remote, ORDER_QUERY, {"id": gid(order_id, "Order")}).get("order")
        if not isinstance(data, dict) or data.get("test") is not True or data.get("id") != order_id:
            raise ShopifyUnavailable("Only an existing Shopify test order can be considered")
        return data

    def returnable(self, remote, order_id):
        data = self.graphql(remote, RETURNABLE_QUERY, {"id": gid(order_id, "Order")})
        result = {}
        for fulfillment in nodes(data.get("returnableFulfillments")):
            for line in nodes(fulfillment.get("returnableFulfillmentLineItems")):
                identity = gid(line.get("fulfillmentLineItem", {}).get("id"), "FulfillmentLineItem")
                quantity = line.get("quantity")
                if identity in result or type(quantity) is not int or quantity < 0:
                    raise ShopifyUnavailable("Shopify returnable quantities could not be verified")
                result[identity] = quantity
        return result

    def create_return(self, remote, order_id, line_id, marker):
        response = self.graphql(remote, RETURN_CREATE, {"input": {
            "orderId": gid(order_id, "Order"),
            "returnLineItems": [{
                "fulfillmentLineItemId": gid(line_id, "FulfillmentLineItem"),
                "quantity": 1, "returnReasonNote": marker,
            }],
        }}).get("returnCreate")
        if not isinstance(response, dict):
            raise ShopifyUnavailable("The create result could not be verified")
        if response.get("userErrors") and response.get("return") is None:
            raise ShopifyRejected("Shopify rejected return creation")
        created = response.get("return")
        return gid(created.get("id") if isinstance(created, dict) else None, "Return")

    def read_return(self, remote, return_id):
        return self.graphql(remote, RETURN_QUERY, {"id": gid(return_id, "Return")}).get("return")

    def order_returns(self, remote, order_id):
        after = None
        results = []
        for _ in range(4):
            order = self.graphql(remote, ORDER_RETURNS, {
                "id": gid(order_id, "Order"), "after": after,
            }).get("order")
            if not isinstance(order, dict) or order.get("test") is not True or order.get("id") != order_id:
                raise ShopifyUnavailable("The test order return history could not be verified")
            connection = order.get("returns")
            results.extend(nodes(connection, complete=False))
            info = connection.get("pageInfo", {})
            if info.get("hasNextPage") is False:
                return results
            cursor = info.get("endCursor")
            if info.get("hasNextPage") is not True or not isinstance(cursor, str) or not cursor or cursor == after:
                break
            after = cursor
        raise ShopifyUnavailable("The test order return history exceeds the pilot limit")
