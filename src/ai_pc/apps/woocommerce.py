"""WooCommerce (REST API v3 on your WordPress shop): products with price and stock, products added, prices and stock
changed by SKU (variations too), new orders (processing), and orders marked shipped: a note to the customer with the
courier and tracking number, then 'completed'. Keys: WooCommerce > Settings > Advanced > REST API > Add key (Read/Write);
the shop must be on HTTPS. Changes are shown first and done after a yes.

  'woocommerce products'   'add Lawn Suit to woocommerce at 2,500, sku LS-01, 10 in stock'   'set price of LS-01 on woocommerce to 2,300'
  'new orders on woocommerce'   'mark order 345 shipped on woocommerce with TCS 1234567890'
"""
import base64

from ai_pc.apps import storekit
from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

NAME, LABEL = "woocommerce", "WooCommerce store: products, prices, stock, orders, shipping"
EXAMPLES = ["woocommerce products", "add Lawn Suit to woocommerce at 2,500, sku LS-01, 10 in stock", "new orders on woocommerce"]
OUTWARD = {"add", "update", "ship"}
APP = {"label": "WooCommerce",
       "fields": [("url", "Your shop's address (https://...)", False), ("ck", "Consumer key (ck_...)", True), ("cs", "Consumer secret (cs_...)", True)],
       "steps": ["In WordPress admin: WooCommerce > Settings > Advanced > REST API > Add key: a description, your user, Permissions Read/Write > Generate.",
                 "Copy the consumer key (ck_...) and secret (cs_...): the secret is shown once. Settings > Permalinks must not be 'Plain'.",
                 "Run 'ai-pc apps connect woocommerce' with your shop's https:// address."],
       "notes": "The shop must use HTTPS. If your host strips the Authorization header, the keys go in the address instead (done automatically)."}


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport = creds, transport
        if not str(creds.get("url", "")).startswith("https://"):
            raise RuntimeError("WooCommerce keys are sent only to an https:// shop")
        self.query_keys = bool(creds.get("query_keys"))

    def call(self, method, path, body=None, params=None):
        h = {}
        p = dict(params or {})
        if self.query_keys:
            p.update(consumer_key=self.c["ck"], consumer_secret=self.c["cs"])
        else:
            h["Authorization"] = "Basic " + base64.b64encode(f"{self.c['ck']}:{self.c['cs']}".encode()).decode()
        api = Api(self.c["url"].rstrip("/") + "/wp-json/wc/v3", headers=h, service="woocommerce", transport=self.transport)
        try:
            return api.request(method, path, params=p, json_body=body, retries=0 if method in ("POST", "PUT") else 3)
        except HubError as e:
            b = e.body if isinstance(e.body, dict) else {}
            if e.status == 401 and "missing" in str(b.get("message", "")).lower() and not self.query_keys:
                self.query_keys = True  # the host dropped the Authorization header: send the keys in the address
                return self.call(method, path, body, params)
            raise RuntimeError(f"WooCommerce: {b.get('message') or e}") from e

    @staticmethod
    def _p(x):
        return {"sku": x.get("sku"), "title": x.get("name"), "price": x.get("regular_price") or x.get("price") or "0", "stock": x.get("stock_quantity"),
                "id": x["id"], "parent": x.get("parent_id") or 0}

    def products(self):
        out, page = [], 1
        while True:
            rows = self.call("GET", "products", params={"per_page": 100, "page": page})
            out += [self._p(x) for x in rows]
            if len(rows) < 100:
                return out
            page += 1

    def find(self, sku):
        rows = [x for x in self.call("GET", "products", params={"sku": sku}) if x.get("sku") == sku]
        return self._p(rows[0]) if rows else None

    def add(self, title, price, sku, stock, image=None, **_):
        body = {"name": title, "type": "simple", "regular_price": str(price), "sku": sku, "manage_stock": True, "stock_quantity": int(stock)}
        if image:
            body["images"] = [{"src": image}]
        return f"product {self.call('POST', 'products', body)['id']}"

    def update(self, sku, price=None, stock=None):
        p = self.find(sku)
        body = {}
        if price is not None:
            body["regular_price"] = str(price)
        if stock is not None:
            body.update(manage_stock=True, stock_quantity=int(stock))
        path = f"products/{p['parent']}/variations/{p['id']}" if p["parent"] else f"products/{p['id']}"
        self.call("PUT", path, body)

    def orders(self):
        return [{"id": o["id"], "number": str(o.get("number") or o["id"]), "total": o.get("total", "0"), "created": o.get("date_created", "")}
                for o in self.call("GET", "orders", params={"status": "processing", "per_page": 50})]

    def ship(self, number, company=None, tracking=None):
        o = next((x for x in self.orders() if x["number"] == str(number)), None)
        if not o:
            raise RuntimeError(f"order {number} is not waiting to ship (processing) on WooCommerce")
        note = "Your order has been shipped" + (f" via {company}, tracking number {tracking}" if tracking else "") + "."
        self.call("POST", f"orders/{o['id']}/notes", {"note": note, "customer_note": True})
        r = self.call("PUT", f"orders/{o['id']}", {"status": "completed"})
        return f"the customer was emailed the tracking note; the order is {r.get('status')}"


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("WooCommerce is not connected: 'ai-pc apps steps woocommerce' shows how")
    return Client(c)


def connect(values, transport=None, store=None):
    c = Client(dict(values), transport)
    c.call("GET", "products", params={"per_page": 1})
    (store or (lambda v: vault.put(NAME, v)))(dict(values, query_keys=c.query_keys))
    return {"who": values["url"], "where": "WooCommerce"}


def parse(text, ctx):
    return storekit.parse_store(text, r"\bwoo(?:commerce)?\b")


def preview(op, ctx):
    return storekit.preview(op, "WooCommerce")


def run(op, ctx):
    return storekit.run(op, client(ctx), "WooCommerce")
