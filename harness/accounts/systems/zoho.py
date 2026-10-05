"""Zoho Books (API v3) through a Self Client: no browser redirect and nothing listening on this PC. The person makes a
Self Client in Zoho's API console, generates a one-time code there and pastes it here once; it becomes a refresh token
(kept encrypted) that makes hour-long access tokens. Zoho's free plan allows 1,000 API calls a day, 100 a minute.

A Pakistan organisation uses Zoho's global edition: sales tax is a tax made here once ('Sales Tax 18%'), and for a
buyer without an STRN a tax group adds 'Further Tax 4%' to it, so both stay tax liabilities there. Customers,
suppliers and items are found by name or made; invoices, quotations and credit notes keep our numbers and are marked
sent/open; money in and out are customer and vendor payments applied to their invoices and bills (income tax a
customer withheld is a second payment into an 'Income Tax Deducted by Customers' account; an advance stays as the
customer's unused credit); expenses are expenses. Zoho has no idempotency key: a create is never retried blindly, and
each remote object carries our number as its mark and is looked for before a new try.
"""
import time
import urllib.parse
from decimal import Decimal

from ...hub import vault
from ...hub.http import Api, HubError
from ..money import mul
from . import Connector, SyncError, bill_account, linked, match_expense, once, rate_of, splits

# Zoho's data centres: your Zoho address -> (sign-in server, API server)
DCS = {"com": ("https://accounts.zoho.com", "https://www.zohoapis.com"), "eu": ("https://accounts.zoho.eu", "https://www.zohoapis.eu"),
       "in": ("https://accounts.zoho.in", "https://www.zohoapis.in"), "com.au": ("https://accounts.zoho.com.au", "https://www.zohoapis.com.au"),
       "jp": ("https://accounts.zoho.jp", "https://www.zohoapis.jp"), "ca": ("https://accounts.zohocloud.ca", "https://www.zohoapis.ca"),
       "sa": ("https://accounts.zoho.sa", "https://www.zohoapis.sa"), "uk": ("https://accounts.zoho.uk", "https://www.zohoapis.uk")}
SCOPES = "ZohoBooks.contacts.ALL,ZohoBooks.settings.ALL,ZohoBooks.estimates.ALL,ZohoBooks.invoices.ALL,ZohoBooks.customerpayments.ALL," \
         "ZohoBooks.creditnotes.ALL,ZohoBooks.bills.ALL,ZohoBooks.vendorpayments.ALL,ZohoBooks.expenses.ALL,ZohoBooks.accountants.ALL"
MADE = {"wht": ("Income Tax Deducted by Customers", "other_current_asset", "1310"),
        "wht_payable": ("Income Tax Withheld from Suppliers", "other_current_liability", "2200")}
APP = {
    "label": "Zoho Books",
    "fields": [("dc?", "Your Zoho address ends in (com, eu, in, com.au, jp, ca, sa, uk; Enter for com)", False),
               ("client_id", "Client ID of the Self Client", False), ("client_secret", "Client Secret of the Self Client", True),
               ("code", "The code you generated (within its 10 minutes)", True)],
    "steps": ["Open https://api-console.zoho.com (use your own Zoho address, e.g. api-console.zoho.eu) and sign in with your Zoho Books login.",
              "Click 'Add Client', choose 'Self Client', then 'Create'; the Client ID and Client Secret are on its 'Client Secret' tab.",
              f"On its 'Generate Code' tab paste this scope: {SCOPES} ; Time Duration: 10 minutes; Description: AI PC; click Create "
              "(choose your Zoho Books organisation if asked) and copy the code.",
              "Within those 10 minutes run 'accounts.py connect zoho' and paste the Client ID, the Client Secret and the code."],
    "notes": "Zoho Books Free allows 1,000 API calls a day; paid plans more. The code works once; the refresh token it becomes is kept encrypted.",
}
# kind -> (list path, the field our number goes in, id field, the key one object comes back under)
PATHS = {"invoice": ("invoices", "invoice_number", "invoice_id", "invoice"), "quote": ("estimates", "estimate_number", "estimate_id", "estimate"),
         "credit_note": ("creditnotes", "creditnote_number", "creditnote_id", "creditnote"), "bill": ("bills", "reference_number", "bill_id", "bill"),
         "expense": ("expenses", "reference_number", "expense_id", "expense"),
         "receipt": ("customerpayments", "reference_number", "payment_id", "payment"),
         "payment": ("vendorpayments", "reference_number", "payment_id", "vendorpayment")}


def _token(accounts, form, transport=None):
    try:
        r = Api(accounts, service="zoho sign-in", transport=transport).request(
            "POST", f"{accounts}/oauth/v2/token", data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, retries=1)
    except HubError as e:
        raise SyncError(f"Zoho refused the sign-in ({e})", "auth") from e
    if r.get("error") or not r.get("access_token"):  # Zoho answers 200 with {"error": "invalid_code"}
        raise SyncError(f"Zoho refused the sign-in ({r.get('error') or 'no token'}): generate a new code and connect again", "auth")
    return r


def connect(values, transport=None, store=None):
    dc = (values.get("dc") or "com").strip().lower().replace("zoho.", "").strip(".") or "com"
    if dc not in DCS:
        raise SyncError(f"unknown Zoho address '{dc}': one of {', '.join(DCS)}")
    accounts, api = DCS[dc]
    tok = _token(accounts, {"grant_type": "authorization_code", "client_id": values["client_id"], "client_secret": values["client_secret"],
                            "code": values["code"]}, transport)
    if not tok.get("refresh_token"):
        raise SyncError("Zoho gave no refresh token (the code was used before?): generate a new code and connect again", "auth")
    creds = {"client_id": values["client_id"], "client_secret": values["client_secret"], "accounts": accounts, "api": tok.get("api_domain") or api,
             "refresh_token": tok["refresh_token"], "access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in") or 3600) - 60}
    s = System(dict(creds), transport)
    orgs = s.call("GET", "organizations", org=False).get("organizations") or []
    if not orgs:
        raise SyncError("this Zoho login has no Zoho Books organisation")
    org = next((o for o in orgs if o.get("is_default_org")), orgs[0])
    creds.update(org=org["organization_id"], org_name=org.get("name"), currency=org.get("currency_code"))
    (store or (lambda c: vault.put("zoho", c)))(creds)
    return {"who": org.get("name"), "where": f"Zoho Books, {org.get('currency_code') or ''}".strip(", ")}


def _cents(x):
    return int((Decimal(str(x or 0)) * 100).quantize(Decimal("1")))


class System(Connector):
    name, label = "zoho", "Zoho Books"
    kinds = ("invoice", "quote", "bill", "credit_note", "receipt", "payment", "expense")

    def __init__(self, creds=None, transport=None):
        super().__init__()
        self.from_vault = creds is None
        self.creds = (vault.get("zoho") or {}) if creds is None else creds
        self.transport = transport
        self._cache = {}

    def ready(self):
        if not self.creds.get("refresh_token") or not self.creds.get("org"):
            return False, "Zoho Books is not connected: 'accounts.py steps zoho' shows how (free, a few minutes)"
        return True, f"Zoho Books ({self.creds.get('org_name') or 'your organisation'})"

    def token(self):
        c = self.creds
        if not c.get("refresh_token") and not c.get("access_token"):
            raise SyncError("Zoho Books is not connected: run 'accounts.py steps zoho'", "auth")
        if c.get("access_token") and c.get("expires_at", 0) > time.time() + 60:
            return c["access_token"]
        tok = _token(c["accounts"], {"grant_type": "refresh_token", "client_id": c["client_id"], "client_secret": c["client_secret"],
                                     "refresh_token": c["refresh_token"]}, self.transport)
        c.update(access_token=tok["access_token"], expires_at=time.time() + int(tok.get("expires_in") or 3600) - 60)
        if self.from_vault:
            vault.put("zoho", {"access_token": c["access_token"], "expires_at": c["expires_at"]})
        return c["access_token"]

    def call(self, method, path, body=None, params=None, create=False, org=True):
        """One API call; a create is never retried blindly (Zoho has no idempotency key)."""
        self.calls += 1
        p = dict(params or {})
        if org:
            p["organization_id"] = self.creds.get("org")
        api = Api(self.creds.get("api", DCS["com"][1]).rstrip("/") + "/books/v3", headers={"Authorization": f"Zoho-oauthtoken {self.token()}"},
                  service="zoho", transport=self.transport)
        try:
            r = api.request(method, path, params=p, json_body=body, retries=0 if create else 3)
        except HubError as e:
            raise self.classify(e) from e
        if isinstance(r, dict) and r.get("code") not in (0, None):
            raise SyncError(f"Zoho Books: {r.get('message') or r.get('code')}")
        return r

    @staticmethod
    def classify(e):
        b = e.body if isinstance(e.body, dict) else {}
        if e.status is None:
            return SyncError(f"Zoho Books could not be reached ({e})", "offline")
        if e.status == 401 or b.get("code") in (14, 57):
            return SyncError("Zoho Books: the sign-in expired or lacks a permission; run 'accounts.py connect zoho'", "auth")
        if e.status == 429:
            return SyncError("Zoho Books: the API limit for this minute or today is reached; try again later", "limit")
        return SyncError(f"Zoho Books: {b.get('message') or e}")

    def _one(self, path, field, value, key, test=None):
        rows = self.call("GET", path, params={field: value}).get(path) or []
        rows = [r for r in rows if r.get(field) == value and r.get("status") != "void" and (test is None or test(r))]
        return rows[0][key] if rows else None

    # ---------------------------------------------------------------- what a document needs there
    def contact(self, b, party, kind):
        ztype = "vendor" if kind == "supplier" else "customer"

        def make():
            found = self.call("GET", "contacts", params={"contact_name": party["name"]}).get("contacts") or []
            hit = next((x for x in found if (x.get("contact_name") or "").lower() == party["name"].lower() and x.get("contact_type", ztype) == ztype), None)
            if hit:
                return hit["contact_id"]
            body = {"contact_name": party["name"], "contact_type": ztype}
            ids = ", ".join(f"{k.upper()} {party[k]}" for k in ("ntn", "strn", "cnic") if party.get(k))
            if ids:
                body["notes"] = ids
            if party.get("email") or party.get("phone"):
                body["contact_persons"] = [{"first_name": party["name"][:100], "email": party.get("email") or "", "phone": party.get("phone") or "",
                                            "is_primary_contact": True}]
            if party.get("address"):
                body["billing_address"] = {"address": party["address"]}
            return self.call("POST", "contacts", body, create=True)["contact"]["contact_id"]
        return once(b, self.name, "party", f"{party['id']}:{ztype}", make)

    def _taxes(self, fresh=False):
        if "taxes" not in self._cache or fresh:
            self._cache["taxes"] = self.call("GET", "settings/taxes").get("taxes") or []
        return self._cache["taxes"]

    def tax(self, b, rate, further=None):
        """The tax (or, with further tax, the tax group) to put on a line; '' for none."""
        if not rate or Decimal(str(rate)) == 0:
            return ""

        def one(r, name):
            want = Decimal(str(r))

            def make():
                hit = next((t for t in self._taxes() if "group" not in str(t.get("tax_type", "")).lower() and
                            Decimal(str(t.get("tax_percentage", -1))) == want and name.split()[0].lower() in (t.get("tax_name") or "").lower()), None)
                if hit:
                    return hit["tax_id"]
                return self.call("POST", "settings/taxes", {"tax_name": f"{name} {want.normalize()}%", "tax_percentage": float(want), "tax_type": "tax"},
                                 create=True)["tax"]["tax_id"]
            return once(b, self.name, "tax", f"{name} {want.normalize()}", make)
        st = one(rate, "Sales Tax")
        if not further:
            return st
        ft = one(further, "Further Tax")
        gname = f"Sales Tax {Decimal(str(rate)).normalize()}% + Further Tax {Decimal(str(further)).normalize()}%"

        def group():
            hit = next((t for t in self._taxes(fresh=True) if (t.get("tax_name") or "") == gname), None)
            if hit:
                return hit["tax_id"]
            return self.call("POST", "settings/taxgroups", {"tax_group_name": gname, "taxes": f"{st},{ft}"}, create=True)["tax_group"]["tax_group_id"]
        return once(b, self.name, "tax", gname, group)

    def _chart(self, fresh=False):
        if "chart" not in self._cache or fresh:
            self._cache["chart"] = [a for a in self.call("GET", "chartofaccounts").get("chartofaccounts") or [] if a.get("is_active", True)]
        return self._cache["chart"]

    def account(self, b, role):
        def of(types, word=None):
            return [a for a in self._chart() if a.get("account_type") in types and (not word or word in (a.get("account_name") or "").lower())]

        def make():
            if role in MADE:
                name, typ, code = MADE[role]
                hit = next((a for a in self._chart() if (a.get("account_name") or "").lower() == name.lower()), None)
                if hit:
                    return hit["account_id"]
                made = self.call("POST", "chartofaccounts", {"account_name": name, "account_type": typ, "account_code": code}, create=True)
                self._chart(fresh=True)
                return made["chart_of_account"]["account_id"]
            if role.startswith("expense:"):
                aid = match_expense(role.split(":", 1)[1], [(a["account_id"], a.get("account_name")) for a in of(("expense", "other_expense"))])
                if not aid:
                    raise SyncError("Zoho Books: the organisation has no expense account")
                return aid
            pick = {"bank": [a for a in of(("bank",)) if "cash" not in (a.get("account_name") or "").lower()] or of(("bank",)),
                    "cash": of(("cash",), "petty") or of(("cash",)),
                    "sales": of(("income",), "sales") or of(("income",)),
                    "services": of(("income",), "service") or of(("income",), "sales") or of(("income",)),
                    "purchases": of(("cost_of_goods_sold",)) or of(("expense",), "purchase")}[role]
            if not pick:
                raise SyncError("Zoho Books: add a bank account first (Banking > Add Bank)" if role == "bank" else f"Zoho Books: no {role} account")
            return pick[0]["account_id"]
        return once(b, self.name, "account", role, make)

    def item(self, b, ln):
        def make():
            found = self.call("GET", "items", params={"name": ln["description"]}).get("items") or []
            hit = next((x for x in found if (x.get("name") or "").lower() == ln["description"].lower()), None)
            if hit:
                return hit["item_id"]
            return self.call("POST", "items", {"name": ln["description"], "rate": ln["rate"] / 100, "unit": ln.get("unit") or ""},
                             create=True)["item"]["item_id"]
        return once(b, self.name, "item", ln["item_id"], make)

    def _lines(self, b, doc, purchase=False):
        out = []
        for ln in doc["lines"]:
            further = rate_of(ln["amount"], ln.get("further_tax")) if ln.get("further_tax") else None
            row = {"name": ln["description"], "description": "", "rate": ln["rate"] / 100, "quantity": float(Decimal(ln["qty"])),
                   "tax_id": self.tax(b, ln.get("tax_rate"), further)}
            if ln.get("unit"):
                row["unit"] = ln["unit"]
            if ln.get("discount"):
                d = str(ln["discount"]).replace(" ", "")
                row["discount"] = d if d.endswith("%") else (mul(ln["rate"], ln["qty"]) - ln["amount"]) / 100
            if purchase:
                code = bill_account(b, ln)
                row["account_id"] = self.account(b, "purchases" if code == "5000" else f"expense:{code}")
            elif ln.get("item_id"):
                row["item_id"] = self.item(b, ln)
            out.append(row)
        return out

    def _common(self, b, doc, purchase=False):
        body = {"date": doc["date"], "line_items": self._lines(b, doc, purchase), "is_inclusive_tax": False}
        if any(ln.get("discount") for ln in doc["lines"]):
            body.update(discount_type="item_level", is_discount_before_tax=True)
        return body

    def _live(self, b, doc, path, one, rid, want):
        """A draft made live (sent / open), once: done only while it is still a draft there."""
        def make():
            if (self.call("GET", f"{path}/{rid}").get(one) or {}).get("status") == "draft":
                self.call("POST", f"{path}/{rid}/status/{want}")
            return want
        self.step(b, doc, want, make)

    # ---------------------------------------------------------------- creating, reading, cancelling
    def create(self, b, doc):
        k, p, n = doc["kind"], doc.get("party"), doc["number"]
        path, field, key, one = PATHS[k]
        auto = {"ignore_auto_number_generation": "true"}
        mark = lambda: self._one(path, field, n, key)  # noqa: E731 - our number, where it went
        if k in ("invoice", "quote", "credit_note"):
            def make():
                body = dict(self._common(b, doc), customer_id=self.contact(b, p, "customer"))
                body[field] = n
                if k == "invoice":
                    body.update(due_date=doc.get("due"), reference_number=doc.get("ref") or "")
                elif k == "quote":
                    body["expiry_date"] = doc.get("due")
                else:
                    body["reference_number"] = doc["invoice"]
                return self.call("POST", path, body, params=auto, create=True)[one][key]
            x = self.step(b, doc, "made", make, mark)
            self._live(b, doc, path, one, x, "sent" if k != "credit_note" else "open")
            if k == "credit_note":
                target = linked(b, b.doc_by_number(doc["invoice"])["id"], self.name)

                def applied():
                    c = self.call("GET", f"{path}/{x}").get(one) or {}
                    return "applied" if any(i.get("invoice_id") == target for i in c.get("invoices_credited") or []) else None
                self.step(b, doc, "applied", lambda: (self.call("POST", f"{path}/{x}/invoices", {
                    "invoices": [{"invoice_id": target, "amount_applied": doc["total"] / 100}]}, create=True), "applied")[1], applied)
            return x
        if k == "bill":
            def make():
                body = dict(self._common(b, doc, purchase=True), vendor_id=self.contact(b, p, "supplier"), bill_number=doc.get("ref") or n,
                            reference_number=n, due_date=doc.get("due"))
                return self.call("POST", path, body, create=True)[one][key]
            x = self.step(b, doc, "made", make, mark)
            self._live(b, doc, path, one, x, "open")
            return x
        if k in ("receipt", "payment"):
            parts, advance = splits(b, doc)
            rec = k == "receipt"
            who = self.contact(b, p, "customer" if rec else "supplier")
            cash = [(linked(b, i, self.name), c) for i, c, _ in parts if c]
            wht = [(linked(b, i, self.name), w) for i, _, w in parts if w]
            ids = []
            if cash or advance > 0:
                amount = sum(c for _, c in cash) + max(advance, 0)
                src = self.account(b, "bank" if doc.get("bank", True) else "cash")
                ids.append(self.step(b, doc, "payment", lambda: self._pay(rec, who, src, amount, cash, doc, n, "banktransfer" if doc.get("bank", True) else "cash"),
                                     mark))
            if wht:
                acct = self.account(b, "wht" if rec else "wht_payable")
                ids.append(self.step(b, doc, "tax withheld", lambda: self._pay(rec, who, acct, sum(w for _, w in wht), wht, doc, f"{n} WHT", "others"),
                                     lambda: self._one(path, field, f"{n} WHT", key)))
            if not ids:
                raise SyncError(f"{n} settles nothing that can go to Zoho Books")
            return ",".join(ids)
        if k == "expense":
            def make():
                body = {"account_id": self.account(b, f"expense:{doc.get('account') or '6090'}"), "date": doc["date"], "amount": doc["amount"] / 100,
                        "paid_through_account_id": self.account(b, "bank" if doc.get("paid_from") == "bank" else "cash"), "description": doc.get("what") or "",
                        "reference_number": n, "is_inclusive_tax": False}
                t = self.tax(b, rate_of(doc["amount"], doc.get("tax")))
                if t:
                    body["tax_id"] = t
                if p:
                    body["vendor_id"] = self.contact(b, p, "supplier")
                return self.call("POST", path, body, create=True)[one][key]
            return self.step(b, doc, "made", make, mark)
        raise SyncError(f"Zoho Books: a {k} is not sent")

    def _pay(self, rec, who, account, amount, applied, doc, ref, mode):
        if rec:
            body = {"customer_id": who, "payment_mode": mode, "amount": amount / 100, "date": doc["date"], "reference_number": ref,
                    "account_id": account, "invoices": [{"invoice_id": t, "amount_applied": a / 100} for t, a in applied]}
            return self.call("POST", "customerpayments", body, create=True)["payment"]["payment_id"]
        body = {"vendor_id": who, "payment_mode": mode, "amount": amount / 100, "date": doc["date"], "reference_number": ref,
                "paid_through_account_id": account, "bills": [{"bill_id": t, "amount_applied": a / 100} for t, a in applied]}
        return self.call("POST", "vendorpayments", body, create=True)["vendorpayment"]["payment_id"]

    def read(self, b, doc, remote):
        path, _, _, one = PATHS[doc["kind"]]
        total, notes = 0, []
        for rid in remote.split(","):
            x = self.call("GET", f"{path}/{rid}").get(one) or {}
            total += _cents(x.get("total", x.get("amount")))
            if x.get("status") in ("draft", "void"):
                notes.append(f"its status there is {x['status']}")
        return {"total": total, "notes": notes}

    def void(self, b, doc, remote):
        path = PATHS[doc["kind"]][0]
        for rid in remote.split(","):
            if doc["kind"] in ("invoice", "bill", "credit_note"):
                self.call("POST", f"{path}/{rid}/status/void")
            elif doc["kind"] == "quote":
                self.call("POST", f"{path}/{rid}/status/declined")
            else:
                self.call("DELETE", f"{path}/{rid}")
