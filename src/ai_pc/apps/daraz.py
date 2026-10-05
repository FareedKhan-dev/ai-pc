"""Daraz (Daraz.pk Open Platform): products with price and stock, prices and stock changed by seller SKU, new orders,
and orders packed and set ready to ship (Daraz's own logistics gives the tracking number). Every call is signed
(HMAC-SHA256 of the API path and the sorted parameters with the app secret). Setting up needs Daraz's approvals: the
developer account, the 'Seller In-house APP' category and, before real prices and stock show, the data 'unmask';
adding new products also needs the category's attributes (basic here: an existing category id). Changes are shown
first and done after a yes.

  'daraz products'   'set stock of LS-01 on daraz to 25'   'new orders on daraz'   'mark order 123456789 shipped on daraz'
"""

import datetime as dt
import hashlib
import hmac
import json
import time
import urllib.parse
from xml.sax.saxutils import escape

from ai_pc.apps import storekit
from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

NAME, LABEL = "daraz", "Daraz seller: products, prices, stock, orders, ready to ship"
EXAMPLES = ["daraz products", "set stock of LS-01 on daraz to 25", "new orders on daraz"]
OUTWARD = {"add", "update", "ship"}
GATEWAY = "https://api.daraz.pk/rest"
APP = {
    "label": "Daraz",
    "fields": [("app_key", "App Key", False), ("app_secret", "App Secret", True), ("callback", "Your app's callback address (https://...)", False)],
    "steps": [
        "open.daraz.com > Create Account (ID approval) > App Console: apply for the category 'Seller In-house APP' (1-2 working days).",
        "Create App with a callback address: any https:// page of yours (nothing needs to run there; you copy the code from the address bar).",
        "App Overview shows the App Key; Basic Information shows the App Secret; Auth Management > Authorized Seller Whitelist: add your seller account.",
        "Advanced Information > Sensitive Data Privilege > Apply Unmask (until approved, prices, stock and orders come back masked).",
        "Run 'ai-pc apps connect daraz': a Daraz sign-in opens; after it, paste the address the browser lands on (it holds ?code=, valid 30 minutes).",
    ],
    "notes": "A Test-status app's sign-in lasts 30 days (then sign in again); 'Online' status needs 1,000+ calls a day for two weeks.",
}


def sign(path, params, secret):
    s = path + "".join(f"{k}{params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), s.encode(), hashlib.sha256).hexdigest().upper()


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport = creds, transport

    def call(self, path, params=None, post=False, token=True):
        p = {"app_key": self.c["app_key"], "timestamp": str(int(time.time() * 1000)), "sign_method": "sha256", **(params or {})}
        if token:
            p["access_token"] = self.token()
        p["sign"] = sign(path, p, self.c["app_secret"])
        api = Api(GATEWAY, service="daraz", transport=self.transport)
        try:
            if post:
                r = api.request(
                    "POST",
                    GATEWAY + path,
                    data=urllib.parse.urlencode(p).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    retries=0,
                )
            else:
                r = api.request("GET", GATEWAY + path, params=p)
        except HubError as e:
            raise RuntimeError(f"Daraz: {e}") from e
        if str(r.get("code", "0")) != "0":
            raise RuntimeError(
                f"Daraz: {r.get('code')} {r.get('message')}" + (" (too many requests: wait a minute)" if r.get("code") == "E901" else "")
            )
        return r

    def token(self):
        c = self.c
        if c.get("access_token") and c.get("expires_at", 0) > time.time() + 300:
            return c["access_token"]
        if not c.get("refresh_token"):
            raise RuntimeError("Daraz is not signed in: run 'ai-pc apps connect daraz'")
        r = self.call("/auth/token/refresh", {"refresh_token": c["refresh_token"]}, token=False)
        c.update(
            access_token=r["access_token"],
            refresh_token=r.get("refresh_token", c["refresh_token"]),
            expires_at=time.time() + int(r.get("expires_in") or 0),
        )
        return c["access_token"]

    def products(self):
        r = self.call("/products/get", {"filter": "all", "limit": 50, "offset": 0})
        out = []
        for p in (r.get("data") or {}).get("products") or []:
            for s in p.get("skus") or []:
                out.append(
                    {
                        "sku": s.get("SellerSku"),
                        "title": (p.get("attributes") or {}).get("name"),
                        "price": s.get("price"),
                        "stock": s.get("quantity"),
                        "item_id": p.get("item_id"),
                        "sku_id": s.get("SkuId"),
                    }
                )
        return out

    def find(self, sku):
        try:
            r = self.call("/product/item/get", {"seller_sku": sku})
        except RuntimeError:
            return None
        d = r.get("data") or {}
        s = next((x for x in d.get("skus") or [] if x.get("SellerSku") == sku), None)
        return (
            {
                "sku": sku,
                "title": (d.get("attributes") or {}).get("name"),
                "price": s.get("price"),
                "stock": s.get("quantity"),
                "item_id": d.get("item_id"),
                "sku_id": s.get("SkuId"),
            }
            if s
            else None
        )

    def add(self, title, price, sku, stock, image=None, category=None):
        if not category:
            raise RuntimeError("Daraz needs the product's category: say '... category <id>' (the id of a leaf category from Daraz's category tree)")
        imgs = ""
        if image:
            r = self.call("/image/migrate", {"payload": f"<Request><Image><Url>{escape(image)}</Url></Image></Request>"}, post=True)
            imgs = f"<Images><Image>{escape(r['data']['image']['url'])}</Image></Images>"
        payload = (
            f"<Request><Product><PrimaryCategory>{escape(str(category))}</PrimaryCategory>{imgs}<Attributes><name>{escape(title)}</name>"
            f"<short_description>{escape(title)}</short_description><brand>No Brand</brand></Attributes><Skus><Sku><SellerSku>{escape(sku)}</SellerSku>"
            f"<quantity>{int(stock)}</quantity><price>{price}</price><package_length>30</package_length><package_width>20</package_width>"
            "<package_height>5</package_height><package_weight>0.5</package_weight></Sku></Skus></Product></Request>"
        )
        r = self.call("/product/create", {"payload": payload}, post=True)
        return f"item {r['data']['item_id']} (Daraz checks new products before they show)"

    def update(self, sku, price=None, stock=None):
        p = self.find(sku)
        x = f"<ItemId>{p['item_id']}</ItemId><SkuId>{p['sku_id']}</SkuId><SellerSku>{escape(sku)}</SellerSku>"
        if price is not None:
            x += f"<Price>{price}</Price>"
        if stock is not None:
            x += f"<Quantity>{int(stock)}</Quantity>"
        self.call("/product/price_quantity/update", {"payload": f"<Request><Product><Skus><Sku>{x}</Sku></Skus></Product></Request>"}, post=True)

    def orders(self):
        since = (dt.datetime.now(dt.timezone(dt.timedelta(hours=5))) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S+05:00")
        r = self.call("/orders/get", {"created_after": since, "status": "pending", "limit": 100, "offset": 0})
        return [
            {
                "id": o["order_id"],
                "number": str(o.get("order_number") or o["order_id"]),
                "total": str(o.get("price") or "0").replace(",", ""),
                "created": o.get("created_at", ""),
            }
            for o in (r.get("data") or {}).get("orders") or []
        ]

    def ship(self, number, company=None, tracking=None):
        o = next((x for x in self.orders() if x["number"] == str(number)), None)
        if not o:
            raise RuntimeError(f"order {number} is not pending on Daraz")
        items = [i["order_item_id"] for i in self.call("/order/items/get", {"order_id": o["id"]}).get("data") or []]
        pack = self.call(
            "/order/fulfill/pack",
            {
                "packReq": json.dumps(
                    {
                        "pack_order_list": [{"order_id": o["id"], "order_item_list": items}],
                        "delivery_type": "dropship",
                        "shipping_allocate_type": "TFS",
                    }
                )
            },
            post=True,
        )
        done = [i for po in pack["result"]["data"]["pack_order_list"] for i in po["order_item_list"]]
        bad = [i for i in done if str(i.get("item_err_code")) != "0"]
        if bad:
            raise RuntimeError(f"Daraz refused to pack {len(bad)} item(s): {bad[0].get('item_err_code')}")
        pkgs = sorted({i["package_id"] for i in done})
        rts = self.call("/order/package/rts", {"readyToShipReq": json.dumps({"packages": [{"package_id": p} for p in pkgs]})}, post=True)
        bad = [p for p in rts["result"]["data"]["packages"] if str(p.get("item_err_code")) != "0"]
        if bad:
            raise RuntimeError(f"Daraz refused ready-to-ship: {bad[0].get('item_err_code')}")
        tracks = sorted({i.get("tracking_number") for i in done if i.get("tracking_number")})
        return f"packed and ready to ship; Daraz's tracking {', '.join(tracks)}"


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Daraz is not connected: 'ai-pc apps steps daraz' shows how")
    return Client(c)


def connect(values, transport=None, store=None, open_url=None, ask=input, show=print):
    import webbrowser

    url = "https://api.daraz.pk/oauth/authorize?" + urllib.parse.urlencode(
        {"response_type": "code", "force_auth": "true", "redirect_uri": values["callback"], "client_id": values["app_key"]}
    )
    show(f"Sign in to Daraz Seller Center in your browser (opening it; or paste this link):\n{url}")
    (open_url or webbrowser.open)(url)
    landed = ask("Paste the full address the browser landed on: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(landed).query).get("code", [landed])[0]
    c = Client(dict(values), transport)
    r = c.call("/auth/token/create", {"code": code}, token=False)
    creds = {
        "app_key": values["app_key"],
        "app_secret": values["app_secret"],
        "access_token": r["access_token"],
        "refresh_token": r["refresh_token"],
        "expires_at": time.time() + int(r.get("expires_in") or 0),
        "account": r.get("account"),
    }
    (store or (lambda v: vault.put(NAME, v)))(creds)
    return {"who": r.get("account"), "where": "Daraz"}


def parse(text, ctx):
    return storekit.parse_store(text, r"\bdaraz\b")


def preview(op, ctx):
    if op["op"] == "ship":
        return f"Ready to pack order {op['number']} on Daraz and set it ready to ship (Daraz's courier collects it and gives the tracking number)."
    return storekit.preview(op, "Daraz")


def run(op, ctx):
    return storekit.run(op, client(ctx), "Daraz")
