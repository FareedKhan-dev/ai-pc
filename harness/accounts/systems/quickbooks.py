"""QuickBooks Online (Accounting API, minor version 75) for a business on QuickBooks Online's global edition (Pakistan
has no edition of its own). An Intuit developer app is free: its Development keys work with a sandbox company at once;
Production keys need Intuit's short app assessment. Sign-in is OAuth 2 with the app's client secret (Intuit has no
PKCE): a sandbox answers to http://localhost:3011/callback on this PC; for production Intuit allows only an HTTPS
address, so you sign in in the browser and paste the address it lands on.

Access tokens last an hour; the refresh token lasts 100 days from its last use and changes about daily, so the newest
one is always kept. Every write carries a requestid made from the document's number and step (QuickBooks answers a
repeat with the first answer instead of writing twice), and each document's DocNumber is looked for before a new try.
Sales tax: the person turns tax on in QuickBooks once; a tax agency 'FBR' and a tax code 'Sales Tax 18%' (a sales and
a purchase rate) are made here; further tax rides in its own tax code with both rates. Quotations are estimates;
returns are credit memos applied to their invoice by a zero payment; money received is a payment (an advance stays as
the customer's credit; income tax withheld is a second payment into 'Income Tax Deducted by Customers'); money paid is
a bill payment (income tax withheld from a supplier is a journal entry against them); expenses are purchases. Writes
are single POSTs: Intuit counts batches against its free monthly allowance, and plain creates are not counted.
"""
import base64
import hashlib
import re
import secrets
import time
import urllib.parse
import webbrowser
from decimal import Decimal

from ...hub import vault
from ...hub.http import Api, HubError
from . import Connector, SyncError, bill_account, linked, match_expense, once, rate_of, remember, remembered, splits

AUTH = "https://appcenter.intuit.com/connect/oauth2"
TOKEN = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
BASE = {"sandbox": "https://sandbox-quickbooks.api.intuit.com", "production": "https://quickbooks.api.intuit.com"}
PORT, PATH = 3011, "/callback"
MINOR = "75"
MADE = {"wht": ("Income Tax Deducted by Customers", "Other Current Asset"), "wht_payable": ("Income Tax Withheld from Suppliers", "Other Current Liability"),
        "cash": ("Cash on hand", "Bank")}
APP = {
    "label": "QuickBooks Online",
    "fields": [("client_id", "Client ID of your Intuit app", False), ("client_secret", "Client Secret of your Intuit app", True),
               ("env?", "sandbox or production (Enter for sandbox)", False),
               ("redirect?", "Redirect URI for production (your HTTPS page; Enter for the sandbox's http://localhost:3011/callback)", False)],
    "steps": ["Sign in at https://developer.intuit.com (free) and create an app (My Hub > App dashboard > +) with the scope com.intuit.quickbooks.accounting.",
              "In the app's Development settings > Keys & credentials add the Redirect URI http://localhost:3011/callback and copy the Client ID and "
              "Client Secret; Development keys work with your free sandbox company.",
              "For your real company: fill in the app's details and Intuit's app assessment, add an HTTPS Redirect URI of yours (Intuit refuses localhost "
              "for production), and use the Production keys.",
              "In QuickBooks itself turn sales tax on once (Taxes > Set up); then run 'accounts.py connect quickbooks' and sign in."],
    "notes": "Intuit's developer use is free (its Builder tier: 500,000 metered reads a month; creates are not counted). QuickBooks has no Pakistan "
             "edition: the global edition is used, and sales tax is set up here as tax codes.",
}


def _basic(cid, secret):
    return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()


def _token(cid, secret, form, transport=None):
    try:
        return Api(TOKEN, service="intuit sign-in", transport=transport).request(
            "POST", TOKEN, data=urllib.parse.urlencode(form).encode(), retries=1,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": _basic(cid, secret)})
    except HubError as e:
        raise SyncError(f"Intuit refused the sign-in ({e}); run 'accounts.py connect quickbooks' again", "auth") from e


def connect(values, open_url=webbrowser.open, show=print, ask=input, transport=None, timeout=300, store=None):
    env = (values.get("env") or "sandbox").strip().lower()
    if env not in BASE:
        raise SyncError("env must be sandbox or production")
    redirect = (values.get("redirect") or "").strip()
    if env == "production" and not redirect.startswith("https://"):
        raise SyncError("for production Intuit needs an HTTPS Redirect URI of yours (the one set in the app's Production settings)")

    def build(redir, state):
        return AUTH + "?" + urllib.parse.urlencode({"client_id": values["client_id"], "response_type": "code", "scope": "com.intuit.quickbooks.accounting",
                                                    "redirect_uri": redir, "state": state})
    if env == "sandbox" and not redirect:
        from .loop import loopback_localhost
        got, redirect = loopback_localhost(build, PORT, PATH, show=show, open_url=open_url, timeout=timeout, who="QuickBooks")
    else:
        state = secrets.token_urlsafe(16)
        url = build(redirect, state)
        show(f"Sign in to QuickBooks in your browser (opening it now; or paste this link into it):\n{url}")
        open_url(url)
        landed = ask("Paste the full address the browser landed on: ").strip()
        got = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(landed).query).items()}
        if got.get("state") != state or not got.get("code"):
            raise SyncError("that address is not the answer to this sign-in (its code or state is missing or different); try again", "auth")
    return finish(values["client_id"], values["client_secret"], env, got["code"], got.get("realmId"), redirect, transport, store)


def finish(cid, secret, env, code, realm, redirect, transport=None, store=None):
    if not realm:
        raise SyncError("Intuit did not say which company (realmId): sign in again and choose your company", "auth")
    tok = _token(cid, secret, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect}, transport)
    creds = {"client_id": cid, "client_secret": secret, "env": env, "realm": realm, "access_token": tok["access_token"],
             "refresh_token": tok["refresh_token"], "expires_at": time.time() + int(tok.get("expires_in") or 3600) - 60}
    s = System(dict(creds), transport)
    info = s.call("GET", f"companyinfo/{realm}").get("CompanyInfo") or {}
    creds["company_name"] = info.get("CompanyName")
    (store or (lambda c: vault.put("quickbooks", c)))(creds)
    prefs = (s.call("GET", "preferences").get("Preferences") or {}).get("TaxPrefs") or {}
    warn = "" if prefs.get("UsingSalesTax") else "; turn sales tax on in QuickBooks (Taxes > Set up) before invoices with tax go"
    return {"who": info.get("CompanyName"), "where": f"QuickBooks Online ({env}){warn}"}


def _money(x):
    return int((Decimal(str(x or 0)) * 100).quantize(Decimal("1")))


def _q(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


class System(Connector):
    name, label = "quickbooks", "QuickBooks Online"
    kinds = ("invoice", "quote", "bill", "credit_note", "receipt", "payment", "expense")

    def __init__(self, creds=None, transport=None):
        super().__init__()
        self.from_vault = creds is None
        self.creds = (vault.get("quickbooks") or {}) if creds is None else creds
        self.transport = transport
        self._cache = {}

    def ready(self):
        if not self.creds.get("refresh_token") or not self.creds.get("realm"):
            return False, "QuickBooks Online is not connected: 'accounts.py steps quickbooks' shows how"
        return True, f"QuickBooks Online ({self.creds.get('company_name') or 'your company'})"

    def token(self, force=False):
        c = self.creds
        if not c.get("refresh_token"):
            raise SyncError("QuickBooks Online is not connected: run 'accounts.py steps quickbooks'", "auth")
        if not force and c.get("access_token") and c.get("expires_at", 0) > time.time() + 60:
            return c["access_token"]
        tok = _token(c["client_id"], c["client_secret"], {"grant_type": "refresh_token", "refresh_token": c["refresh_token"]}, self.transport)
        c.update(access_token=tok["access_token"], refresh_token=tok.get("refresh_token") or c["refresh_token"],  # its value changes: keep the newest
                 expires_at=time.time() + int(tok.get("expires_in") or 3600) - 60)
        if self.from_vault:
            vault.put("quickbooks", {k: c[k] for k in ("access_token", "refresh_token", "expires_at")})
        return c["access_token"]

    def call(self, method, path, body=None, params=None, requestid=None, _again=True):
        self.calls += 1
        p = dict(params or {}, minorversion=MINOR)
        if requestid:
            p["requestid"] = requestid
        api = Api(f"{BASE[self.creds.get('env', 'sandbox')]}/v3/company/{self.creds.get('realm')}", headers={"Authorization": f"Bearer {self.token()}"},
                  service="quickbooks", transport=self.transport)
        try:
            r = api.request(method, path, params=p, json_body=body)
        except HubError as e:
            if e.status == 401 and _again:  # an access token can die before its hour: renew once
                self.token(force=True)
                return self.call(method, path, body, params, requestid, _again=False)
            raise self.classify(e) from e
        if isinstance(r, dict) and r.get("Fault"):
            raise self.classify(HubError("fault", 400, r))
        return r

    @staticmethod
    def classify(e):
        b = e.body if isinstance(e.body, dict) else {}
        errs = (b.get("Fault") or {}).get("Error") or []
        codes = {str(x.get("code")) for x in errs}
        text = "; ".join(f"{x.get('Message')}: {x.get('Detail')}" for x in errs) or b.get("error") or str(e)
        if e.status is None:
            return SyncError(f"QuickBooks could not be reached ({e})", "offline")
        if e.status in (401, 403) or "3200" in codes:
            return SyncError("QuickBooks: the sign-in expired (or was disconnected); run 'accounts.py connect quickbooks'", "auth")
        if e.status == 429 or "003001" in codes:
            return SyncError("QuickBooks: too many requests this minute (or the month's allowance is used up); try again later", "limit")
        if "6190" in codes:
            return SyncError("QuickBooks: the company's subscription has ended", "auth")
        return SyncError("QuickBooks: " + text)

    def query(self, sql):
        r = self.call("GET", "query", params={"query": sql}).get("QueryResponse") or {}
        return next((v for k, v in r.items() if isinstance(v, list)), [])

    def _rid(self, b, doc, key):
        """The requestid of a write: the same for a retry of it, new only after QuickBooks refused the last try."""
        n = remembered(b, self.name, "attempt", f"{doc['id']}:{key}") or "0"
        return "aipc-" + hashlib.sha1(f"{self.creds.get('realm')}|{doc['kind']}|{doc['number']}|{key}|{n}".encode()).hexdigest()[:40]

    def write(self, b, doc, key, entity, body, operation=None):
        try:
            return self.call("POST", entity, body, params={"operation": operation} if operation else None, requestid=self._rid(b, doc, key))
        except SyncError as e:
            if e.kind == "invalid":  # refused: the next try is a new request
                k = f"{doc['id']}:{key}"
                remember(b, self.name, "attempt", k, int(remembered(b, self.name, "attempt", k) or 0) + 1)
            raise

    # ---------------------------------------------------------------- what a document needs there
    def entity(self, b, party, kind):
        table = "Vendor" if kind == "supplier" else "Customer"

        def make():
            for name in (party["name"], f"{party['name']} ({'supplier' if table == 'Vendor' else 'customer'})"):
                hit = self.query(f"SELECT * FROM {table} WHERE DisplayName = '{_q(name)}'")
                if hit:
                    return hit[0]["Id"]
                body = {"DisplayName": name[:500]}
                ids = ", ".join(f"{k.upper()} {party[k]}" for k in ("ntn", "strn", "cnic") if party.get(k))
                if ids:
                    body["Notes"] = ids
                if party.get("email"):
                    body["PrimaryEmailAddr"] = {"Address": party["email"]}
                if party.get("phone"):
                    body["PrimaryPhone"] = {"FreeFormNumber": party["phone"]}
                if party.get("address"):
                    body["BillAddr"] = {"Line1": party["address"], "Country": "Pakistan"}
                try:
                    return self.call("POST", table.lower(), body)[table]["Id"]
                except SyncError as e:
                    if "6240" not in str(e) and "Duplicate" not in str(e):  # the name is taken by a customer, supplier or employee: mark it
                        raise
            raise SyncError(f"QuickBooks: the name {party['name']} is taken")
        return once(b, self.name, "party", f"{party['id']}:{table}", make)

    def accounts(self):
        if "accounts" not in self._cache:
            self._cache["accounts"] = self.query("SELECT * FROM Account WHERE Active = true MAXRESULTS 1000")
        return self._cache["accounts"]

    def account(self, b, role):
        def of(types, rx=None):
            return [a for a in self.accounts() if a.get("AccountType") in types and (not rx or re.search(rx, a.get("Name") or "", re.I))]

        def make():
            if role.startswith("expense:"):
                aid = match_expense(role.split(":", 1)[1], [(a["Id"], a.get("Name")) for a in of(("Expense", "Other Expense"))])
                if not aid:
                    raise SyncError("QuickBooks: the company has no expense account")
                return aid
            pick = {"sales": of(("Income",), r"sales") or of(("Income",)), "services": of(("Income",), r"service") or of(("Income",)),
                    "purchases": of(("Cost of Goods Sold",)), "bank": [a for a in of(("Bank",)) if not re.search(r"cash", a.get("Name") or "", re.I)],
                    "cash": of(("Bank",), r"cash"), "payable": of(("Accounts Payable",)),
                    "wht": of(("Other Current Asset",), "^Income Tax Deducted by Customers$"),
                    "wht_payable": of(("Other Current Liability",), "^Income Tax Withheld from Suppliers$")}[role]
            if pick:
                return pick[0]["Id"]
            if role in MADE:
                name, typ = MADE[role]
                a = self.call("POST", "account", {"Name": name, "AccountType": typ})["Account"]
                self._cache.pop("accounts", None)
                return a["Id"]
            raise SyncError("QuickBooks: add your bank account first (Transactions > Chart of accounts > New: Bank)" if role == "bank" else
                            f"QuickBooks: the company has no {role} account")
        return once(b, self.name, "account", role, make)

    def item(self, b, ln):
        service = ln.get("kind") == "service"
        name = re.sub(r"[:\t\n]", "-", ln["description"] if ln.get("item_id") else ("Services" if service else "Goods"))[:100]

        def make():
            hit = self.query(f"SELECT * FROM Item WHERE Name = '{_q(name)}'")
            if hit:
                return hit[0]["Id"]
            body = {"Name": name, "Type": "Service" if service else "NonInventory", "IncomeAccountRef": {"value": self.account(b, "services" if service else "sales")}}
            if not service:
                try:
                    body["ExpenseAccountRef"] = {"value": self.account(b, "purchases")}
                except SyncError:
                    pass  # a company without a cost of goods account: the item is for sale only
            return self.call("POST", "item", body)["Item"]["Id"]
        return once(b, self.name, "item", ln.get("item_id") or name, make)

    def tax_code(self, b, rate, further=None):
        """The tax code for a line: 'Sales Tax 18%' (or with further tax), made with its agency FBR the first time."""
        want = Decimal(str(rate or 0)).normalize()
        name = f"Sales Tax {want}%" + (f" + Further Tax {Decimal(str(further)).normalize()}%" if further else "") if want else "No Tax 0%"

        def fbr():
            hit = self.query("SELECT * FROM TaxAgency WHERE DisplayName = 'FBR'")
            return hit[0]["Id"] if hit else self.call("POST", "taxagency", {"DisplayName": "FBR"})["TaxAgency"]["Id"]

        def make():
            hit = self.query(f"SELECT * FROM TaxCode WHERE Name = '{_q(name)}'")
            if hit:
                return hit[0]["Id"]
            agency = once(b, self.name, "agency", "FBR", fbr)
            rates =[{"TaxRateName": f"{name} sales", "RateValue": str(want), "TaxAgencyId": agency, "TaxApplicableOn": "Sales"},
                     {"TaxRateName": f"{name} purchases", "RateValue": str(want), "TaxAgencyId": agency, "TaxApplicableOn": "Purchase"}]
            if further:
                rates.insert(1, {"TaxRateName": f"Further Tax {Decimal(str(further)).normalize()}% sales", "RateValue": str(Decimal(str(further)).normalize()),
                                 "TaxAgencyId": agency, "TaxApplicableOn": "Sales"})
            return str(self.call("POST", "taxservice/taxcode", {"TaxCode": name, "TaxRateDetails": rates})["TaxCodeId"])
        return once(b, self.name, "tax", name, make)

    def _sales_lines(self, b, doc):
        out = []
        for ln in doc["lines"]:
            further = rate_of(ln["amount"], ln.get("further_tax")) if ln.get("further_tax") else None
            qty, rate = Decimal(ln["qty"]), Decimal(ln["rate"]) / 100
            amount = Decimal(ln["amount"]) / 100
            desc = ln["description"]
            if amount != qty * rate:  # a discount: QuickBooks wants Amount = Qty x UnitPrice, so the line is one lot at its net price
                desc += f" ({qty.normalize():f} x {rate:.2f} less {ln.get('discount')})"
                qty, rate = Decimal(1), amount
            out.append({"DetailType": "SalesItemLineDetail", "Amount": float(amount), "Description": desc,
                        "SalesItemLineDetail": {"ItemRef": {"value": self.item(b, ln)}, "Qty": float(qty), "UnitPrice": float(rate),
                                                "TaxCodeRef": {"value": self.tax_code(b, ln.get("tax_rate"), further)}}})
        return out

    def _expense_lines(self, b, doc):
        out = []
        for ln in doc["lines"]:
            code = bill_account(b, ln)
            acct = self.account(b, "purchases" if code == "5000" else f"expense:{code}")
            out.append({"DetailType": "AccountBasedExpenseLineDetail", "Amount": ln["amount"] / 100, "Description": f"{ln['description']} x {ln['qty']}",
                        "AccountBasedExpenseLineDetail": {"AccountRef": {"value": acct}, "TaxCodeRef": {"value": self.tax_code(b, ln.get("tax_rate"))}}})
        return out

    # ---------------------------------------------------------------- creating, reading, cancelling
    ENT = {"invoice": "Invoice", "quote": "Estimate", "credit_note": "CreditMemo", "bill": "Bill", "expense": "Purchase"}

    def _one(self, table, number, test=None):
        rows = [r for r in self.query(f"SELECT * FROM {table} WHERE DocNumber = '{_q(number)}'") if test is None or test(r)]
        return rows[0]["Id"] if rows else None

    def create(self, b, doc):
        k, p, n = doc["kind"], doc.get("party"), doc["number"]
        if len(n) > 21:
            raise SyncError(f"QuickBooks takes document numbers of up to 21 characters; {n} is longer")
        if k in ("invoice", "quote", "credit_note"):
            ent = self.ENT[k]

            def make():
                body = {"CustomerRef": {"value": self.entity(b, p, "customer")}, "TxnDate": doc["date"], "DocNumber": n,
                        "GlobalTaxCalculation": "TaxExcluded", "Line": self._sales_lines(b, doc), "PrivateNote": f"AI PC {n}"}
                if k == "invoice" and doc.get("due"):
                    body["DueDate"] = doc["due"]
                if k == "quote" and doc.get("due"):
                    body["ExpirationDate"] = doc["due"]
                return self.write(b, doc, "made", ent.lower(), body)[ent]["Id"]
            x = self.step(b, doc, "made", make, lambda: self._one(ent, n))
            if k == "credit_note":
                inv = linked(b, b.doc_by_number(doc["invoice"])["id"], self.name).split(":")[-1]
                cust = self.entity(b, p, "customer")
                ref = f"{n} APPLY"[:21]
                self.step(b, doc, "applied", lambda: self.write(b, doc, "applied", "payment", {
                    "CustomerRef": {"value": cust}, "TotalAmt": 0, "TxnDate": doc["date"], "PaymentRefNum": ref,
                    "Line": [{"Amount": doc["total"] / 100, "LinkedTxn": [{"TxnId": inv, "TxnType": "Invoice"}]},
                             {"Amount": doc["total"] / 100, "LinkedTxn": [{"TxnId": x, "TxnType": "CreditMemo"}]}]})["Payment"]["Id"],
                    lambda: next((r["Id"] for r in self.query(f"SELECT * FROM Payment WHERE PaymentRefNum = '{_q(ref)}'")), None))
            return f"{ent.lower()}:{x}"
        if k == "bill":
            num = (doc.get("ref") or n)[:21]

            def make():
                body = {"VendorRef": {"value": self.entity(b, p, "supplier")}, "TxnDate": doc["date"], "DocNumber": num, "PrivateNote": f"AI PC {n}",
                        "GlobalTaxCalculation": "TaxExcluded", "Line": self._expense_lines(b, doc)}
                if doc.get("due"):
                    body["DueDate"] = doc["due"]
                return self.write(b, doc, "made", "bill", body)["Bill"]["Id"]
            x = self.step(b, doc, "made", make, lambda: self._one("Bill", num, lambda r: f"AI PC {n}" in (r.get("PrivateNote") or "")))
            return f"bill:{x}"
        if k == "expense":
            def make():
                body = {"PaymentType": "Cash", "AccountRef": {"value": self.account(b, "bank" if doc.get("paid_from") == "bank" else "cash")},
                        "TxnDate": doc["date"], "DocNumber": n, "GlobalTaxCalculation": "TaxExcluded", "PrivateNote": f"AI PC {n}",
                        "Line": [{"DetailType": "AccountBasedExpenseLineDetail", "Amount": doc["amount"] / 100, "Description": doc.get("what") or "",
                                  "AccountBasedExpenseLineDetail": {"AccountRef": {"value": self.account(b, f"expense:{doc.get('account') or '6090'}")},
                                                                    "TaxCodeRef": {"value": self.tax_code(b, rate_of(doc["amount"], doc.get("tax")))}}}]}
                if p:
                    body["EntityRef"] = {"value": self.entity(b, p, "supplier"), "type": "Vendor"}
                return self.write(b, doc, "made", "purchase", body)["Purchase"]["Id"]
            return "purchase:" + self.step(b, doc, "made", make, lambda: self._one("Purchase", n))
        if k == "receipt":
            parts, advance = splits(b, doc)
            cust = self.entity(b, p, "customer")
            ids = []
            cash = [(linked(b, i, self.name).split(":")[-1], c) for i, c, _ in parts if c]
            wht = [(linked(b, i, self.name).split(":")[-1], w) for i, _, w in parts if w]
            for key, ref, rows, extra, acct in (("payment", n, cash, max(advance, 0), "bank" if doc.get("bank", True) else "cash"),
                                                ("tax withheld", f"{n} WHT", wht, 0, "wht")):
                if not rows and not extra:
                    continue
                body = {"CustomerRef": {"value": cust}, "TxnDate": doc["date"], "PaymentRefNum": ref, "DepositToAccountRef": {"value": self.account(b, acct)},
                        "TotalAmt": (sum(a for _, a in rows) + extra) / 100,
                        "Line": [{"Amount": a / 100, "LinkedTxn": [{"TxnId": t, "TxnType": "Invoice"}]} for t, a in rows]}
                ids.append("payment:" + self.step(b, doc, key, lambda: self.write(b, doc, key, "payment", body)["Payment"]["Id"],
                                                  lambda: next((r["Id"] for r in self.query(f"SELECT * FROM Payment WHERE PaymentRefNum = '{_q(ref)}'")), None)))
            return ",".join(ids)
        if k == "payment":
            parts, advance = splits(b, doc)
            vend = self.entity(b, p, "supplier")
            ids = []
            rows = [(linked(b, i, self.name).split(":")[-1], c) for i, c, _ in parts if c]
            if rows or advance > 0:
                body = {"VendorRef": {"value": vend}, "TxnDate": doc["date"], "DocNumber": n, "PayType": "Check",
                        "CheckPayment": {"BankAccountRef": {"value": self.account(b, "bank" if doc.get("bank", True) else "cash")}},
                        "TotalAmt": (sum(a for _, a in rows) + max(advance, 0)) / 100,
                        "Line": [{"Amount": a / 100, "LinkedTxn": [{"TxnId": t, "TxnType": "Bill"}]} for t, a in rows]}
                ids.append("billpayment:" + self.step(b, doc, "payment", lambda: self.write(b, doc, "payment", "billpayment", body)["BillPayment"]["Id"],
                                                      lambda: self._one("BillPayment", n)))
            wht = sum(w for _, _, w in parts)
            if wht:  # income tax withheld from the supplier: what we owe them goes down, what we owe FBR goes up
                ref = f"{n} WHT"
                body = {"TxnDate": doc["date"], "DocNumber": ref, "PrivateNote": f"Income tax withheld from {p['name']} on {n} (AI PC)",
                        "Line": [{"Amount": wht / 100, "DetailType": "JournalEntryLineDetail", "JournalEntryLineDetail": {
                            "PostingType": "Debit", "AccountRef": {"value": self.account(b, "payable")}, "Entity": {"Type": "Vendor", "EntityRef": {"value": vend}}}},
                                 {"Amount": wht / 100, "DetailType": "JournalEntryLineDetail", "JournalEntryLineDetail": {
                                     "PostingType": "Credit", "AccountRef": {"value": self.account(b, "wht_payable")}}}]}
                ids.append("journalentry:" + self.step(b, doc, "tax withheld", lambda: self.write(b, doc, "tax withheld", "journalentry", body)["JournalEntry"]["Id"],
                                                       lambda: self._one("JournalEntry", ref)))
                self.notes.append(f"the tax withheld on {n} is a journal entry against {p['name']}: apply it to their bill in QuickBooks (Pay bills)")
            return ",".join(ids)
        raise SyncError(f"QuickBooks: a {k} is not sent")

    def _get(self, ent, rid):
        table = {"invoice": "Invoice", "estimate": "Estimate", "creditmemo": "CreditMemo", "bill": "Bill", "purchase": "Purchase", "payment": "Payment",
                 "billpayment": "BillPayment", "journalentry": "JournalEntry"}[ent]
        return self.call("GET", f"{ent}/{rid}").get(table) or {}

    def read(self, b, doc, remote):
        total = 0
        for part in remote.split(","):
            ent, rid = part.split(":")
            x = self._get(ent, rid)
            total += _money(x.get("TotalAmt")) if ent != "journalentry" else _money(x["Line"][0]["Amount"])
        return {"total": total}

    def void(self, b, doc, remote):
        if doc["kind"] == "credit_note":
            raise SyncError(f"QuickBooks: cancel {doc['number']} there by hand (its application to the invoice must be removed first)")
        for part in remote.split(","):
            ent, rid = part.split(":")
            x = self._get(ent, rid)
            body = {"Id": rid, "SyncToken": x.get("SyncToken", "0")}
            self.write(b, doc, f"void {part}", ent, body, operation="void" if ent == "invoice" else "delete")
