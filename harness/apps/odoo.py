"""Odoo (external API over JSON-RPC, Odoo 18 and 19): products with SKU, price and stock, sales orders waiting to be
invoiced, and customer invoices made as drafts (the customer found or added, each line's product found by its SKU or
name). Signs in with an API key (Preferences > Account Security / Security > New API Key). On Odoo Online the external
API needs Odoo's Custom plan; a self-hosted Odoo has no such limit. A draft invoice is shown first and made after a yes.

  'odoo products'   'odoo orders to invoice'   'odoo invoice for Ayesha Khan: 2 LS-01 at 2,500, 1 delivery at 300'
"""
import itertools
import re

from ..hub import vault
from ..hub.http import Api, HubError
from .storekit import money

NAME, LABEL = "odoo", "Odoo: products, orders to invoice, draft invoices"
EXAMPLES = ["odoo products", "odoo orders to invoice", "odoo invoice for Ayesha Khan: 2 LS-01 at 2,500"]
OUTWARD = {"invoice"}
APP = {"label": "Odoo",
       "fields": [("url", "Your Odoo address (https://yourco.odoo.com)", False), ("db", "Database name (often the same as the subdomain)", False),
                  ("login", "Your login (email)", False), ("key", "API key", True)],
       "steps": ["In Odoo: your avatar > Preferences (My Profile) > Account Security / Security > New API Key: a description, then copy it (shown once).",
                 "Run 'apps.py connect odoo' with the address, database, login and key."],
       "notes": "On Odoo Online the external API needs the Custom plan; self-hosted Odoo Community needs nothing extra. API keys can expire (90 days on Odoo 19)."}
_ids = itertools.count(1)


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport, self.uid = creds, transport, creds.get("uid")

    def rpc(self, service, method, *args):
        try:
            r = Api(self.c["url"].rstrip("/"), service="odoo", transport=self.transport).request(
                "POST", "jsonrpc", json_body={"jsonrpc": "2.0", "method": "call", "id": next(_ids), "params": {"service": service, "method": method, "args": list(args)}},
                retries=0 if method == "execute_kw" and args and args[4] in ("create", "write", "unlink", "action_post") else 3)
        except HubError as e:
            raise RuntimeError(f"Odoo: {e}") from e
        if r.get("error"):
            d = r["error"].get("data") or {}
            raise RuntimeError(f"Odoo: {d.get('message') or r['error'].get('message')}")
        return r.get("result")

    def x(self, model, method, args, kw=None):
        if not self.uid:
            self.uid = self.rpc("common", "authenticate", self.c["db"], self.c["login"], self.c["key"], {})
            if not self.uid:
                raise RuntimeError("Odoo refused the login or API key")
        return self.rpc("object", "execute_kw", self.c["db"], self.uid, self.c["key"], model, method, args, kw or {})

    def products(self):
        return self.x("product.product", "search_read", [[["sale_ok", "=", True]]], {"fields": ["name", "default_code", "lst_price", "qty_available"], "limit": 80})

    def orders(self):
        return self.x("sale.order", "search_read", [[["state", "=", "sale"], ["invoice_status", "=", "to invoice"]]],
                      {"fields": ["name", "partner_id", "amount_total", "date_order"], "limit": 50})

    def partner(self, name):
        hit = self.x("res.partner", "search_read", [[["name", "=ilike", name]]], {"fields": ["id", "name"], "limit": 1})
        return hit[0]["id"] if hit else self.x("res.partner", "create", [{"name": name}])

    def product(self, word):
        for dom in ([["default_code", "=", word]], [["name", "=ilike", word]], [["name", "ilike", word]]):
            hit = self.x("product.product", "search_read", [dom], {"fields": ["id", "name"], "limit": 2})
            if len(hit) == 1:
                return hit[0]
        return None

    def invoice(self, customer, lines):
        rows = []
        for ln in lines:
            p = self.product(ln["item"])
            vals = {"quantity": ln["qty"], "price_unit": float(ln["price"])}
            vals.update({"product_id": p["id"]} if p else {"name": ln["item"]})
            rows.append([0, 0, vals])
        mid = self.x("account.move", "create", [{"move_type": "out_invoice", "partner_id": self.partner(customer), "invoice_line_ids": rows}])
        mid = mid[0] if isinstance(mid, list) else mid
        back = self.x("account.move", "read", [[mid]], {"fields": ["name", "state", "amount_untaxed", "amount_total"]})[0]
        return mid, back


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Odoo is not connected: 'apps.py steps odoo' shows how")
    return Client(c)


def connect(values, transport=None, store=None):
    c = Client(dict(values), transport)
    c.products()  # the login works and the products can be read
    (store or (lambda v: vault.put(NAME, v)))(dict(values))
    return {"who": values["login"], "where": f"Odoo at {values['url']}"}


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bodoo\b", c):
        return None
    m = re.match(r"^\s*odoo\s+invoice\s+(?:for|to)\s+(.+?)\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        lines = []
        for part in re.split(r",(?!\d{3}\b)|;|\band\b", m.group(2)):
            mm = re.match(r"^\s*(\d+(?:\.\d+)?)\s+(.+?)\s+(?:at|@)\s+((?:rs\.?\s*)?\d[\d,]*(?:\.\d+)?(?:\s*(?:lakh|k))?)\s*(?:each)?\s*$", part, re.I)
            if mm:
                lines.append({"qty": float(mm.group(1)), "item": mm.group(2).strip(), "price": money(mm.group(3))})
        return {"op": "invoice", "customer": m.group(1).strip(), "lines": lines} if lines else None
    if re.search(r"\borders?\b", c):
        return {"op": "orders"}
    if re.search(r"\bproducts?\b|\bitems?\b|\bstock\b", c):
        return {"op": "products"}
    return None


def preview(op, ctx):
    total = sum(ln["qty"] * float(ln["price"]) for ln in op["lines"])
    return f"Ready to make a DRAFT invoice in Odoo for {op['customer']}: " + "; ".join(f"{ln['qty']:g} x {ln['item']} at Rs {float(ln['price']):,.2f}"
                                                                                     for ln in op["lines"]) + f" (before tax Rs {total:,.2f})."


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "products":
        ps = c.products()
        return "\n".join(f"- {p.get('default_code') or '-'}: {p['name']}, Rs {p.get('lst_price', 0):,.2f}, {p.get('qty_available', 0):g} in stock" for p in ps) \
            or "No products in Odoo."
    if op["op"] == "orders":
        os_ = c.orders()
        return "\n".join(f"- {o['name']}: {o['partner_id'][1] if o.get('partner_id') else ''}, Rs {o['amount_total']:,.2f}" for o in os_) or "No orders waiting for an invoice."
    if not op.get("confirmed"):
        return preview(op, ctx)
    mid, back = c.invoice(op["customer"], op["lines"])
    want = sum(ln["qty"] * float(ln["price"]) for ln in op["lines"])
    ok = abs(float(back["amount_untaxed"]) - want) < 0.01 and back["state"] == "draft"
    return f"Draft invoice {mid} in Odoo for {op['customer']}: before tax Rs {float(back['amount_untaxed']):,.2f}, total Rs {float(back['amount_total']):,.2f} " + \
        ("(read back: a draft with these lines)" if ok else "(NOT as asked when read back)") + ". Confirm it in Odoo when it is right."
