"""Fakes of the online-store and website APIs for tests/test_apps.py, from the research spec (2026-10): Shopify Admin
GraphQL 2026-10 (client-credentials token, throttling once), WooCommerce REST v3 (a host that strips the Authorization
header), Daraz Open Platform (every call's signature checked), WordPress REST (media + posts) and Odoo JSON-RPC.
Each answers send(method, url, headers, data, timeout) -> (status, headers, bytes) like the hub's transports."""
import base64
import hashlib
import hmac  # noqa: F401 - Daraz signatures
import json
import re
import urllib.parse
from xml.etree import ElementTree as ET


def js(status, body):
    return status, {"Content-Type": "application/json"}, json.dumps(body).encode()


def form(data):
    return {k: v[0] for k, v in urllib.parse.parse_qs(data.decode()).items()} if data else {}


class FakeShopify:
    SHOP = "khan.myshopify.com"

    def __init__(self):
        self.sent, self.token, self.throttle_once, self.n = [], None, True, 10
        self.variants = {}  # sku -> variant
        self.orders = [{"id": "gid://shopify/Order/1", "name": "#1001", "createdAt": "2026-10-03T10:00:00Z", "totalPriceSet": {"shopMoney": {"amount": "5000.00"}},
                        "fulfillmentOrders": {"nodes": [{"id": "gid://shopify/FulfillmentOrder/1", "status": "OPEN"}]}}]
        self.fulfilled = []

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"url": url, "headers": headers, "data": data})
        if url == f"https://{self.SHOP}/admin/oauth/access_token":
            f = form(data)
            if f.get("grant_type") != "client_credentials" or f.get("client_secret") != "shop-secret":
                return js(400, {"error": "invalid_client"})
            self.token = "shop-token-1"
            return js(200, {"access_token": self.token, "scope": "read_products", "expires_in": 86399})
        if url != f"https://{self.SHOP}/admin/api/2026-10/graphql.json" or headers.get("X-Shopify-Access-Token") != self.token:
            return js(401, {"errors": "[API] Invalid API key or access token"})
        if self.throttle_once:
            self.throttle_once = False
            return js(200, {"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]})
        b = json.loads(data)
        q, v = b["query"], b.get("variables") or {}
        if "productVariants(" in q:
            rows = list(self.variants.values())
            if v.get("q"):
                rows = [r for r in rows if r["sku"] == v["q"].split(":", 1)[1]]
            return js(200, {"data": {"productVariants": {"nodes": rows, "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        if "locations(" in q:
            return js(200, {"data": {"locations": {"nodes": [{"id": "gid://shopify/Location/1", "name": "Shop"}]}}})
        if "productSet(" in q:
            i = v["i"]
            var = i["variants"][0]
            if var["sku"] in self.variants:
                return js(200, {"data": {"productSet": {"product": None, "userErrors": [{"field": "sku", "message": "SKU taken"}]}}})
            self.n += 1
            self.variants[var["sku"]] = {"id": f"gid://shopify/ProductVariant/{self.n}", "sku": var["sku"], "price": var["price"],
                                         "inventoryQuantity": var["inventoryQuantities"][0]["quantity"], "inventoryItem": {"id": f"gid://shopify/InventoryItem/{self.n}"},
                                         "product": {"id": f"gid://shopify/Product/{self.n}", "title": i["title"]}}
            return js(200, {"data": {"productSet": {"product": {"id": f"gid://shopify/Product/{self.n}"}, "userErrors": []}}})
        if "productVariantsBulkUpdate(" in q:
            for x in v["v"]:
                hit = next(r for r in self.variants.values() if r["id"] == x["id"])
                hit["price"] = x["price"]
            return js(200, {"data": {"productVariantsBulkUpdate": {"userErrors": []}}})
        if "inventorySetQuantities(" in q:
            if "@idempotent(key:" not in q or not v.get("k"):
                return js(200, {"errors": [{"message": "an idempotency key is required"}]})
            for x in v["in"]["quantities"]:
                hit = next(r for r in self.variants.values() if r["inventoryItem"]["id"] == x["inventoryItemId"])
                hit["inventoryQuantity"] = x["quantity"]
            return js(200, {"data": {"inventorySetQuantities": {"userErrors": []}}})
        if "orders(" in q:
            return js(200, {"data": {"orders": {"nodes": [o for o in self.orders if o["id"] not in self.fulfilled]}}})
        if "fulfillmentCreate(" in q:
            f = v["f"]
            self.fulfilled.append("gid://shopify/Order/1")
            self.last_tracking = f.get("trackingInfo")
            return js(200, {"data": {"fulfillmentCreate": {"fulfillment": {"id": "gid://shopify/Fulfillment/1", "status": "SUCCESS"}, "userErrors": []}}})
        return js(200, {"errors": [{"message": f"unknown query {q[:60]}"}]})


class FakeWoo:
    BASE = "https://shop.pk/wp-json/wc/v3/"

    def __init__(self, strip_auth=True):
        self.sent, self.strip_auth, self.products, self.n, self.notes = [], strip_auth, {}, 30, []
        self.orders = {345: {"id": 345, "number": "345", "status": "processing", "total": "7500.00", "date_created": "2026-10-03T12:00:00"}}

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url, "headers": headers})
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        authed = (not self.strip_auth and headers.get("Authorization") == "Basic " + base64.b64encode(b"ck_1:cs_1").decode()) or \
            (q.get("consumer_key") == "ck_1" and q.get("consumer_secret") == "cs_1")
        if not authed:
            return js(401, {"code": "woocommerce_rest_authentication_error", "message": "Consumer key is missing.", "data": {"status": 401}})
        path = url.split(self.BASE, 1)[1].split("?")[0]
        b = json.loads(data) if data else {}
        if path == "products" and method == "GET":
            rows = [p for p in self.products.values() if not q.get("sku") or p["sku"] == q["sku"]]
            return js(200, rows)
        if path == "products" and method == "POST":
            if any(p["sku"] == b["sku"] for p in self.products.values()):
                return js(400, {"code": "product_invalid_sku", "message": "Invalid or duplicated SKU.", "data": {"status": 400}})
            self.n += 1
            self.products[self.n] = dict(b, id=self.n, parent_id=0, price=b["regular_price"])
            return js(201, self.products[self.n])
        m = re.fullmatch(r"products/(\d+)", path)
        if m and method == "PUT":
            self.products[int(m.group(1))].update(b)
            return js(200, self.products[int(m.group(1))])
        if path == "orders":
            return js(200, [o for o in self.orders.values() if o["status"] == q.get("status")])
        m = re.fullmatch(r"orders/(\d+)/notes", path)
        if m:
            self.notes.append(b)
            return js(201, dict(b, id=1))
        m = re.fullmatch(r"orders/(\d+)", path)
        if m and method == "PUT":
            self.orders[int(m.group(1))].update(b)
            return js(200, self.orders[int(m.group(1))])
        return js(404, {"code": "rest_no_route", "message": "No route", "data": {"status": 404}})


class FakeDaraz:
    SECRET = "daraz-secret"

    def __init__(self):
        self.sent, self.bad_signs = [], 0
        self.items = {"LS-01": {"item_id": 9001, "SkuId": 777, "price": 2500, "quantity": 10, "name": "Lawn Suit"}}
        self.orders = [{"order_id": 123456789, "order_number": 123456789, "price": "2,500.00", "created_at": "2026-10-03 11:00:00 +0500", "statuses": ["pending"]}]

    def send(self, method, url, headers, data, timeout):
        u = urllib.parse.urlparse(url)
        p = form(data) if method == "POST" else {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path.split("/rest", 1)[1]
        self.sent.append({"path": path, "params": p})
        got = p.pop("sign", None)
        want = hmac.new(self.SECRET.encode(), (path + "".join(f"{k}{p[k]}" for k in sorted(p))).encode(), hashlib.sha256).hexdigest().upper()
        if got != want or not p.get("timestamp") or p.get("sign_method") != "sha256":
            self.bad_signs += 1
            return js(200, {"type": "ISV", "code": "IncompleteSignature", "message": "The request signature does not conform to platform standards"})
        if path == "/product/item/get":
            it = self.items.get(p["seller_sku"])
            if not it:
                return js(200, {"type": "ISV", "code": "208", "message": "Product not found"})
            return js(200, {"code": "0", "data": {"item_id": it["item_id"], "attributes": {"name": it["name"]},
                                                 "skus": [{"SellerSku": p["seller_sku"], "SkuId": it["SkuId"], "price": it["price"], "quantity": it["quantity"]}]}})
        if path == "/products/get":
            return js(200, {"code": "0", "data": {"total_products": str(len(self.items)), "products": [
                {"item_id": it["item_id"], "attributes": {"name": it["name"]}, "skus": [{"SellerSku": s, "SkuId": it["SkuId"], "price": it["price"], "quantity": it["quantity"]}]}
                for s, it in self.items.items()]}})
        if path == "/product/price_quantity/update":
            sku = ET.fromstring(p["payload"]).find(".//Sku")
            it = self.items[sku.findtext("SellerSku")]
            if sku.findtext("Price"):
                it["price"] = float(sku.findtext("Price"))
            if sku.findtext("Quantity"):
                it["quantity"] = int(sku.findtext("Quantity"))
            return js(200, {"code": "0", "data": {}})
        if path == "/orders/get":
            if not p.get("created_after"):
                return js(200, {"type": "ISV", "code": "MISSING_PARAMETER", "message": "created_after or update_after is required"})
            return js(200, {"code": "0", "data": {"count": len(self.orders), "orders": self.orders}})
        if path == "/order/items/get":
            return js(200, {"code": "0", "data": [{"order_item_id": 456, "sku": "LS-01", "status": "pending"}]})
        if path == "/order/fulfill/pack":
            req = json.loads(p["packReq"])
            return js(200, {"code": "0", "result": {"success": True, "data": {"pack_order_list": [
                {"order_id": o["order_id"], "order_item_list": [{"order_item_id": i, "item_err_code": "0", "tracking_number": "DRZ123456", "shipment_provider": "Daraz Express",
                                                                "package_id": "FP001"} for i in o["order_item_list"]]} for o in req["pack_order_list"]]}}})
        if path == "/order/package/rts":
            req = json.loads(p["readyToShipReq"])
            self.orders = []
            return js(200, {"code": "0", "result": {"success": True, "data": {"packages": [{"package_id": x["package_id"], "item_err_code": "0"} for x in req["packages"]]}}})
        return js(200, {"type": "ISV", "code": "InvalidApi", "message": "no such api"})


class FakeWordPress:
    BASE = "https://blog.pk/wp-json/wp/v2/"

    def __init__(self):
        self.sent, self.posts, self.media, self.n = [], {}, {}, 100

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url, "headers": headers})
        if headers.get("Authorization") != "Basic " + base64.b64encode(b"ayesha:abcdabcdabcdabcdabcdabcd").decode():
            return js(401, {"code": "incorrect_password", "message": "The provided password is an invalid application password.", "data": {"status": 401}})
        path = url.split(self.BASE, 1)[1].split("?")[0]
        if path == "users/me":
            return js(200, {"id": 1, "name": "Ayesha"})
        if path == "media" and method == "POST":
            if "filename=" not in (headers.get("Content-Disposition") or ""):
                return js(400, {"code": "rest_upload_no_content_disposition", "message": "No Content-Disposition supplied.", "data": {"status": 400}})
            self.n += 1
            self.media[self.n] = len(data)
            return js(201, {"id": self.n, "source_url": f"https://blog.pk/wp-content/uploads/{self.n}.jpg", "media_type": "image"})
        if path == "posts" and method == "POST":
            b = json.loads(data)
            self.n += 1
            self.posts[self.n] = {"id": self.n, "title": {"raw": b["title"], "rendered": b["title"]}, "content": {"raw": b["content"]}, "status": b["status"],
                                  "featured_media": b.get("featured_media", 0), "link": f"https://blog.pk/?p={self.n}"}
            return js(201, self.posts[self.n])
        m = re.fullmatch(r"posts/(\d+)", path)
        if m and method == "GET":
            return js(200, self.posts[int(m.group(1))])
        if m and method == "POST":
            self.posts[int(m.group(1))].update(json.loads(data))
            return js(200, self.posts[int(m.group(1))])
        if path == "posts":
            return js(200, list(self.posts.values()))
        return js(404, {"code": "rest_no_route", "message": "No route", "data": {"status": 404}})


class FakeOdoo:
    URL = "https://khan.odoo.com/jsonrpc"

    def __init__(self):
        self.sent = []
        self.t = {"product.product": {7: {"id": 7, "name": "Lawn Suit", "default_code": "LS-01", "lst_price": 2500.0, "qty_available": 10.0, "sale_ok": True}},
                  "res.partner": {3: {"id": 3, "name": "Ali Traders"}}, "account.move": {},
                  "sale.order": {20: {"id": 20, "name": "S00020", "partner_id": [3, "Ali Traders"], "amount_total": 5000.0, "date_order": "2026-10-03",
                                      "state": "sale", "invoice_status": "to invoice"}}}

    def _match(self, row, dom):
        for f, op, v in dom:
            x = row.get(f)
            if op == "=" and x != v:
                return False
            if op == "=ilike" and str(x or "").lower() != str(v).lower():
                return False
            if op == "ilike" and str(v).lower() not in str(x or "").lower():
                return False
        return True

    def send(self, method, url, headers, data, timeout):
        b = json.loads(data)
        self.sent.append(b)
        p = b["params"]
        if p["service"] == "common" and p["method"] == "authenticate":
            db, login, key, _ = p["args"]
            return js(200, {"jsonrpc": "2.0", "id": b["id"], "result": 2 if (db, login, key) == ("khan", "ayesha@khan.pk", "odoo-key") else False})
        db, uid, key, model, meth, args, kw = p["args"]
        if uid != 2 or key != "odoo-key":
            return js(200, {"jsonrpc": "2.0", "id": b["id"], "error": {"code": 200, "message": "Odoo Server Error",
                                                                      "data": {"name": "odoo.exceptions.AccessDenied", "message": "Access Denied"}}})
        rows = self.t[model]
        if meth == "search_read":
            hit = [r for r in rows.values() if self._match(r, args[0])][:kw.get("limit", 80)]
            return js(200, {"jsonrpc": "2.0", "id": b["id"], "result": [{k: r.get(k) for k in kw.get("fields") or r} | {"id": r["id"]} for r in hit]})
        if meth == "create":
            vals = args[0]
            nid = max(list(rows) + [0]) + 1
            if model == "account.move":
                lines = [ln[2] for ln in vals["invoice_line_ids"]]
                untaxed = sum(ln["quantity"] * ln["price_unit"] for ln in lines)
                vals = dict(vals, name="/", state="draft", amount_untaxed=untaxed, amount_total=untaxed)
            rows[nid] = dict(vals, id=nid)
            return js(200, {"jsonrpc": "2.0", "id": b["id"], "result": nid})
        if meth == "read":
            return js(200, {"jsonrpc": "2.0", "id": b["id"], "result": [{k: rows[i].get(k) for k in kw.get("fields")} for i in args[0]]})
        return js(200, {"jsonrpc": "2.0", "id": b["id"], "error": {"code": 200, "message": "Odoo Server Error", "data": {"message": f"no {meth}"}}})


class FakeMailchimp:
    BASE = "https://us21.api.mailchimp.com/3.0/"

    def __init__(self):
        self.sent, self.members, self.campaigns = [], {}, {}
        self.lists = {"a1b2c3": {"id": "a1b2c3", "name": "Customers", "stats": {"member_count": 0}}}

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url})
        if headers.get("Authorization") != "Basic " + base64.b64encode(b"aipc:mc-key-us21").decode():
            return js(401, {"title": "API Key Invalid", "detail": "Your API key may be invalid"})
        path = url.split(self.BASE, 1)[1].split("?")[0]
        b = json.loads(data) if data else {}
        if path == "lists":
            return js(200, {"lists": list(self.lists.values())})
        m = re.fullmatch(r"lists/(\w+)/members/(\w+)", path)
        if m:
            if hashlib.md5(b["email_address"].lower().encode()).hexdigest() != m.group(2):  # noqa: S324
                return js(400, {"title": "Invalid Resource", "detail": "The subscriber hash does not match the email"})
            if m.group(2) not in self.members:
                self.lists[m.group(1)]["stats"]["member_count"] += 1
            self.members[m.group(2)] = b
            return js(200, dict(b, id=m.group(2)))
        if path == "campaigns" and method == "POST":
            cid = f"c{len(self.campaigns) + 1}"
            self.campaigns[cid] = dict(b, id=cid, status="save")
            return js(200, self.campaigns[cid])
        m = re.fullmatch(r"campaigns/(\w+)/(content|send-checklist|actions/send)", path)
        if m:
            c = self.campaigns[m.group(1)]
            if m.group(2) == "content":
                c["html"] = b["html"]
                return js(200, {"html": b["html"]})
            if m.group(2) == "send-checklist":
                ready = bool(c.get("html")) and bool(c["settings"].get("reply_to"))
                return js(200, {"is_ready": ready, "items": [] if ready else [{"type": "error", "details": "reply-to address missing"}]})
            c["status"] = "sent"
            return 204, {}, b""
        m = re.fullmatch(r"reports/(\w+)", path)
        if m:
            n = self.lists[self.campaigns[m.group(1)]["recipients"]["list_id"]]["stats"]["member_count"]
            return js(200, {"emails_sent": n, "opens": {"unique_opens": 1}, "clicks": {"unique_clicks": 0}})
        return js(404, {"title": "Resource Not Found"})


class FakeBrevo:
    BASE = "https://api.brevo.com/v3/"

    def __init__(self):
        self.sent, self.contacts, self.campaigns = [], {}, {}
        self.lists = {7: {"id": 7, "name": "Customers", "totalSubscribers": 0}}

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url})
        if headers.get("api-key") != "brevo-key":
            return js(401, {"code": "unauthorized", "message": "Key not found"})
        path = url.split(self.BASE, 1)[1].split("?")[0]
        b = json.loads(data) if data else {}
        if path == "contacts/lists":
            return js(200, {"lists": list(self.lists.values()), "count": len(self.lists)})
        if path == "contacts":
            new = b["email"] not in self.contacts
            self.contacts[b["email"]] = b
            for i in b["listIds"]:
                self.lists[i]["totalSubscribers"] += 1 if new else 0
            return (js(201, {"id": len(self.contacts)}) if new else (204, {}, b""))
        if path == "emailCampaigns" and method == "POST":
            if not b["sender"].get("email"):
                return js(400, {"code": "invalid_parameter", "message": "sender email is missing"})
            cid = len(self.campaigns) + 1
            self.campaigns[cid] = dict(b, id=cid, status="draft")
            return js(201, {"id": cid})
        m = re.fullmatch(r"emailCampaigns/(\d+)/sendNow", path)
        if m:
            self.campaigns[int(m.group(1))]["status"] = "sent"
            return 204, {}, b""
        m = re.fullmatch(r"emailCampaigns/(\d+)", path)
        if m:
            n = sum(self.lists[i]["totalSubscribers"] for i in self.campaigns[int(m.group(1))]["recipients"]["listIds"])
            return js(200, {"id": int(m.group(1)), "statistics": {"globalStats": {"sent": n, "uniqueViews": 1, "uniqueClicks": 1}}})
        return js(404, {"code": "document_not_found", "message": "not found"})


class FakeDropbox:
    def __init__(self):
        self.sent, self.files, self.links = [], {}, {}

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"url": url, "headers": headers})
        if headers.get("Authorization") != "Bearer dbx-token":
            return js(401, {"error_summary": "invalid_access_token/"})
        if url == "https://content.dropboxapi.com/2/files/upload":
            arg = json.loads(headers["Dropbox-API-Arg"])
            path = arg["path"]
            while path in self.files and arg.get("autorename"):
                path = path.replace(".", " (1).", 1)
            h = hashlib.sha256()
            for i in range(0, len(data), 4 * 1024 * 1024):
                h.update(hashlib.sha256(data[i:i + 4 * 1024 * 1024]).digest())
            self.files[path] = data
            return js(200, {"name": path.rsplit("/", 1)[-1], "path_display": path, "size": len(data), "content_hash": h.hexdigest()})
        b = json.loads(data)
        if url.endswith("/files/list_folder"):
            folder = b["path"]
            return js(200, {"entries": [{".tag": "file", "name": p.rsplit("/", 1)[-1], "path_display": p, "size": len(d)} for p, d in self.files.items()
                                        if p.rsplit("/", 1)[0] == folder], "has_more": False})
        if url.endswith("/sharing/create_shared_link_with_settings"):
            if b["path"] not in self.files:
                return js(409, {"error_summary": "path/not_found/"})
            if b["path"] in self.links:
                return js(409, {"error_summary": "shared_link_already_exists/"})
            self.links[b["path"]] = f"https://www.dropbox.com/scl/fi/abc/{b['path'].rsplit('/', 1)[-1]}?dl=0"
            return js(200, {"url": self.links[b["path"]]})
        return js(400, {"error_summary": "unknown"})


class FakeDiscord:
    HOOK = "https://discord.com/api/webhooks/1234567890/tok-en_1"

    def __init__(self):
        self.sent, self.messages, self.n = [], {}, 100

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url, "headers": headers})
        if method == "DELETE":
            mid = url.rsplit("/", 1)[-1]
            return (204, {}, b"") if self.messages.pop(mid, None) else js(404, {"message": "Unknown Message", "code": 10008})
        if not url.startswith(self.HOOK) or "wait=true" not in url:
            return js(404, {"message": "Unknown Webhook"})
        self.n += 1
        if headers.get("Content-Type", "").startswith("multipart/form-data"):
            text = re.search(rb'name="payload_json"\r\n\r\n(.*?)\r\n--', data, re.S)
            content = json.loads(text.group(1))["content"] if text else ""
            atts = [{"id": "1", "filename": m.decode()} for m in re.findall(rb'filename="([^"]+)"', data)]
        else:
            content, atts = json.loads(data)["content"], []
        self.messages[str(self.n)] = {"id": str(self.n), "content": content, "attachments": atts, "channel_id": "55"}
        return js(200, self.messages[str(self.n)])
