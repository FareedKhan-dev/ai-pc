"""Shopify (Admin GraphQL API 2026-10): products with price and stock, products added, prices and stock changed by SKU,
new orders, and orders marked shipped with a courier's tracking number. Since 1 January 2026 a store's own app is made
in Shopify's Dev Dashboard: its client id and secret buy a 24-hour token (client credentials, no web address needed);
an older admin-made app's permanent shpat_ token works too. Changes are shown first and done after a yes.

  'shopify products'   'add Lawn Suit to shopify at 2,500, sku LS-01, 10 in stock'   'set stock of LS-01 on shopify to 25'
  'new orders on shopify'   'mark order 1001 shipped on shopify with TCS 1234567890'
"""
import time
import urllib.parse
import uuid

from ..hub import vault
from ..hub.http import Api, HubError
from . import storekit

NAME, LABEL = "shopify", "Shopify store: products, prices, stock, orders, shipping"
EXAMPLES = ["shopify products", "add Lawn Suit to shopify at 2,500, sku LS-01, 10 in stock", "new orders on shopify"]
OUTWARD = {"add", "update", "ship"}
VERSION = "2026-10"
SCOPES = "read_products,write_products,read_inventory,write_inventory,read_locations,read_orders,read_merchant_managed_fulfillment_orders," \
         "write_merchant_managed_fulfillment_orders"
APP = {"label": "Shopify",
       "fields": [("shop", "Your shop's address (yourshop.myshopify.com)", False), ("client_id", "Client ID of your Dev Dashboard app", False),
                  ("client_secret", "Client secret", True)],
       "steps": ["Open dev.shopify.com/dashboard with your store owner's login > Create app > Start from Dev Dashboard.",
                 f"Versions: App URL https://shopify.dev/apps/default-app-home, scopes {SCOPES}; Release; then Install app on your store.",
                 "App settings: copy the Client ID and Client secret; run 'apps.py connect shopify'. (An older admin-made app: paste its shpat_ token as the "
                 "client secret and leave the Client ID as 'token'.)"],
       "notes": "Orders older than 60 days need read_all_orders; customers' names and addresses need Shopify's Grow plan or higher for custom apps."}


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport, self._loc = creds, transport, None

    def token(self):
        c = self.c
        if c.get("client_id") == "token":
            return c["client_secret"]
        if c.get("access_token") and c.get("expires_at", 0) > time.time() + 120:
            return c["access_token"]
        try:
            r = Api(f"https://{c['shop']}", service="shopify sign-in", transport=self.transport).request(
                "POST", "admin/oauth/access_token", data=urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": c["client_id"],
                                                                                "client_secret": c["client_secret"]}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"}, retries=1)
        except HubError as e:
            raise RuntimeError(f"Shopify refused the app's keys ({e}): is the app installed on {c['shop']}?") from e
        c.update(access_token=r["access_token"], expires_at=time.time() + int(r.get("expires_in") or 86399))
        return c["access_token"]

    def gql(self, query, variables=None):
        api = Api(f"https://{self.c['shop']}/admin/api/{VERSION}", headers={"X-Shopify-Access-Token": self.token()}, service="shopify", transport=self.transport)
        for attempt in range(4):
            r = api.request("POST", "graphql.json", json_body={"query": query, "variables": variables or {}})
            errs = r.get("errors") or []
            if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errs) and attempt < 3:
                time.sleep(1.5 * (attempt + 1) if self.transport is None else 0)
                continue
            if errs:
                raise RuntimeError("Shopify: " + "; ".join(e.get("message", "") for e in errs))
            return r["data"]
        raise RuntimeError("Shopify: still throttled; try again in a minute")

    @staticmethod
    def _user_errors(block):
        errs = (block or {}).get("userErrors") or []
        if errs:
            raise RuntimeError("Shopify: " + "; ".join(e.get("message", "") for e in errs))
        return block

    def _variant(self, v):
        return {"sku": v.get("sku"), "title": v["product"]["title"], "price": v.get("price"), "stock": v.get("inventoryQuantity"), "id": v["id"],
                "product_id": v["product"]["id"], "inventory_item": (v.get("inventoryItem") or {}).get("id")}

    def products(self):
        out, cursor = [], None
        while True:
            d = self.gql("query($c:String){productVariants(first:100,after:$c){nodes{id sku price inventoryQuantity inventoryItem{id} product{id title}} "
                         "pageInfo{hasNextPage endCursor}}}", {"c": cursor})["productVariants"]
            out += [self._variant(v) for v in d["nodes"]]
            if not d["pageInfo"]["hasNextPage"]:
                return out
            cursor = d["pageInfo"]["endCursor"]

    def find(self, sku):
        nodes = self.gql("query($q:String){productVariants(first:5,query:$q){nodes{id sku price inventoryQuantity inventoryItem{id} product{id title}}}}",
                         {"q": f"sku:{sku}"})["productVariants"]["nodes"]
        hit = next((v for v in nodes if v.get("sku") == sku), None)
        return self._variant(hit) if hit else None

    def location(self):
        if not self._loc:
            self._loc = self.gql("{locations(first:5){nodes{id name}}}")["locations"]["nodes"][0]["id"]
        return self._loc

    def add(self, title, price, sku, stock, image=None, **_):
        inp = {"title": title, "productOptions": [{"name": "Title", "values": [{"name": "Default Title"}]}],
               "variants": [{"optionValues": [{"optionName": "Title", "name": "Default Title"}], "price": str(price), "sku": sku, "inventoryItem": {"tracked": True},
                             "inventoryQuantities": [{"locationId": self.location(), "name": "available", "quantity": int(stock)}]}]}
        if image:
            inp["files"] = [{"originalSource": image, "contentType": "IMAGE"}]
        d = self.gql("mutation($i:ProductSetInput!){productSet(synchronous:true,input:$i){product{id} userErrors{field message}}}", {"i": inp})
        return self._user_errors(d["productSet"])["product"]["id"]

    def update(self, sku, price=None, stock=None):
        v = self.find(sku)
        if price is not None:
            d = self.gql("mutation($p:ID!,$v:[ProductVariantsBulkInput!]!){productVariantsBulkUpdate(productId:$p,variants:$v){userErrors{field message}}}",
                         {"p": v["product_id"], "v": [{"id": v["id"], "price": str(price)}]})
            self._user_errors(d["productVariantsBulkUpdate"])
        if stock is not None:
            d = self.gql("mutation($in:InventorySetQuantitiesInput!,$k:String!){inventorySetQuantities(input:$in) @idempotent(key:$k){userErrors{code field message}}}",
                         {"in": {"name": "available", "reason": "correction", "quantities": [{"inventoryItemId": v["inventory_item"], "locationId": self.location(),
                                                                                           "quantity": int(stock), "changeFromQuantity": None}]},
                          "k": str(uuid.uuid4())})
            self._user_errors(d["inventorySetQuantities"])

    def orders(self):
        d = self.gql("{orders(first:50,query:\"status:open fulfillment_status:unfulfilled\"){nodes{id name createdAt totalPriceSet{shopMoney{amount}} "
                     "fulfillmentOrders(first:5){nodes{id status}}}}}")["orders"]["nodes"]
        return [{"id": o["id"], "number": o["name"].lstrip("#"), "total": o["totalPriceSet"]["shopMoney"]["amount"], "created": o["createdAt"],
                 "fulfillment_orders": [f["id"] for f in o["fulfillmentOrders"]["nodes"] if f["status"] in ("OPEN", "IN_PROGRESS")]} for o in d]

    def ship(self, number, company=None, tracking=None):
        o = next((x for x in self.orders() if x["number"] == str(number).lstrip("#")), None)
        if not o or not o["fulfillment_orders"]:
            raise RuntimeError(f"order {number} is not open and unshipped on Shopify")
        f = {"lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": x} for x in o["fulfillment_orders"]], "notifyCustomer": True}
        if tracking:
            f["trackingInfo"] = {"company": company or "Courier", "number": tracking}
        d = self.gql("mutation($f:FulfillmentInput!){fulfillmentCreate(fulfillment:$f){fulfillment{id status} userErrors{field message}}}", {"f": f})
        return "Shopify says " + self._user_errors(d["fulfillmentCreate"])["fulfillment"]["status"]


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Shopify is not connected: 'apps.py steps shopify' shows how")
    return Client(c)


def connect(values, transport=None, store=None):
    c = Client(dict(values), transport)
    c.location()
    (store or (lambda v: vault.put(NAME, v)))({k: values[k] for k in ("shop", "client_id", "client_secret")})
    return {"who": values["shop"], "where": "Shopify"}


def parse(text, ctx):
    return storekit.parse_store(text, r"\bshopify\b")


def preview(op, ctx):
    return storekit.preview(op, "Shopify")


def run(op, ctx):
    return storekit.run(op, client(ctx), "Shopify")
