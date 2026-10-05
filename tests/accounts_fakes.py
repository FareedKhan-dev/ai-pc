"""Fake accounting systems for the accounts lane's tests: Xero and Zoho Books (QuickBooks Online, TallyPrime and FBR's
Digital Invoicing are added below them), each enough of the real API to keep books in step with. They keep what they
are sent, work out totals their own way (per line, half up), refuse what the real one refuses (an overpayment, a
duplicate number, an unknown account or tax), and fail to order: an answer lost after the work was done ('drop'), a
server error ('500'), a limit ('429'), an expired sign-in ('401').

  fx = FakeXero(); conn = xero.System(fx.creds(), fx); fx.failing("PUT", "/Payments", "drop", times=4)
Transports answer send(method, url, headers, data, timeout) -> (status, headers, bytes), like the hub's.
"""
import base64
import datetime as dt
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape as escape_xml


def D(x):
    return Decimal(str(x if x is not None else 0))


def r2(x):
    return D(x).quantize(Decimal("0.01"), ROUND_HALF_UP)


def num(x):
    return float(r2(x))


class Fake:
    def __init__(self):
        self.sent, self.fail, self.n = [], [], 0

    def failing(self, method, frag, how, times=1, skip=0):
        """The next `times` matching requests (after `skip` that go through) fail this way."""
        self.fail.append({"method": method, "frag": frag, "how": how, "times": times, "skip": skip})

    def _rule(self, method, url):
        for r in self.fail:
            if r["method"] == method and r["frag"] in url and r["times"] > 0:
                if r["skip"] > 0:
                    r["skip"] -= 1
                    continue
                r["times"] -= 1
                return r["how"]
        return None

    def nid(self, prefix):
        self.n += 1
        return f"{prefix}-{self.n:04d}"

    @staticmethod
    def js(status, body, headers=None):
        return status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(body).encode()

    def record(self, method, url, headers, data):
        body = None
        if data:
            try:
                body = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                try:
                    body = {k: v[0] for k, v in urllib.parse.parse_qs(data.decode()).items()}
                except UnicodeDecodeError:
                    body = data
        self.sent.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return body


# ==================================================================== Xero
class FakeXero(Fake):
    TOKEN = "https://identity.xero.com/connect/token"
    CONNECTIONS = "https://api.xero.com/connections"
    API = "https://api.xero.com/api.xro/2.0/"

    def __init__(self):
        super().__init__()
        self.access, self.refresh, self.tenant, self.code = "xero-access-1", "xero-refresh-1", "tenant-khan", "good-code"
        self.idem, self.replays = {}, 0
        self.contacts, self.invoices, self.quotes, self.credits, self.payments, self.banktx = {}, {}, {}, {}, {}, {}
        self.taxrates = [{"Name": "No Tax", "TaxType": "NONE", "EffectiveRate": 0, "Status": "ACTIVE", "CanApplyToRevenue": True, "CanApplyToExpenses": True},
                         {"Name": "Tax on Imports 5%", "TaxType": "TAXIMP", "EffectiveRate": 5, "Status": "ACTIVE", "CanApplyToRevenue": False,
                          "CanApplyToExpenses": True}]
        self.accounts = [{"AccountID": f"a-{c}", "Code": c, "Name": n, "Type": t, "Status": "ACTIVE"} for c, n, t in (
            ("200", "Sales", "REVENUE"), ("260", "Other Revenue", "REVENUE"), ("300", "Purchases", "DIRECTCOSTS"), ("310", "Cost of Goods Sold", "DIRECTCOSTS"),
            ("404", "Bank Fees", "OVERHEADS"), ("429", "General Expenses", "OVERHEADS"), ("445", "Light, Power, Heating", "OVERHEADS"),
            ("469", "Rent", "OVERHEADS"), ("477", "Wages and Salaries", "EXPENSE"), ("489", "Telephone & Internet", "OVERHEADS"))]
        self.accounts += [{"AccountID": "bank-meezan", "Code": "", "Name": "Meezan Business Account", "Type": "BANK", "Status": "ACTIVE"},
                          {"AccountID": "bank-petty", "Code": "", "Name": "Petty Cash", "Type": "BANK", "Status": "ACTIVE"}]

    def creds(self):
        return {"client_id": "xero-client", "access_token": self.access, "refresh_token": self.refresh, "expires_at": 9e12, "tenant": self.tenant,
                "tenant_name": "Khan Electronics"}

    # ---------------------------------------------------------------- the wire
    def send(self, method, url, headers, data, timeout):
        body = self.record(method, url, headers, data)
        if url.startswith(self.TOKEN):
            return self._token(body or {})
        if url.startswith(self.CONNECTIONS):
            if headers.get("Authorization") != f"Bearer {self.access}":
                return self.js(401, {"Title": "Unauthorized"})
            return self.js(200, [{"tenantId": self.tenant, "tenantType": "ORGANISATION", "tenantName": "Khan Electronics"}])
        how = self._rule(method, url)
        if how == "401" or headers.get("Authorization") != f"Bearer {self.access}":
            return self.js(401, {"Title": "Unauthorized", "Detail": "TokenExpired: token expired"})
        if headers.get("Xero-tenant-id") != self.tenant:
            return self.js(403, {"Title": "Forbidden", "Detail": "AuthenticationUnsuccessful"})
        if how in ("429", "500"):
            return self.js(int(how), {"Title": "Too Many Requests" if how == "429" else "Server error"}, {"Retry-After": "0", "X-Rate-Limit-Problem": "day"})
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        key = headers.get("Idempotency-Key")
        if key and key in self.idem:
            res = self.idem[key]
            self.replays += 1
        else:
            try:
                res = self.js(200, self.route(method, u.path.split("/api.xro/2.0/")[1], q, body))
            except ValueError as e:
                res = self.js(400, {"ErrorNumber": 10, "Type": "ValidationException", "Message": "A validation exception occurred",
                                    "Elements": [{"ValidationErrors": [{"Message": str(e)}]}]})
            if key and res[0] < 400:
                self.idem[key] = res
        if how == "drop":
            raise ConnectionResetError("the connection dropped before the answer came")
        return res

    def _token(self, form):
        if form.get("grant_type") == "authorization_code":
            if form.get("code") != self.code or not form.get("code_verifier"):
                return self.js(400, {"error": "invalid_grant"})
            self.code = None
        elif form.get("grant_type") == "refresh_token":
            if form.get("refresh_token") != self.refresh:
                return self.js(400, {"error": "invalid_grant"})
        else:
            return self.js(400, {"error": "unsupported_grant_type"})
        n = int(self.refresh.rsplit("-", 1)[1]) + 1
        self.access, self.refresh = f"xero-access-{n}", f"xero-refresh-{n}"  # refresh tokens rotate
        return self.js(200, {"access_token": self.access, "refresh_token": self.refresh, "expires_in": 1800, "token_type": "Bearer"})

    # ---------------------------------------------------------------- the API
    @staticmethod
    def _where(rows, q):
        w = q.get("where")
        conds = re.findall(r'([\w.]+)=="([^"]*)"', w or "")
        out = []
        for r in rows:
            ok = True
            for f, v in conds:
                x = r
                for part in f.split("."):
                    x = (x or {}).get(part) if isinstance(x, dict) else None
                ok = ok and str(x) == v
            if ok:
                out.append(r)
        return out

    def _rate(self, tax_type):
        t = next((t for t in self.taxrates if t["TaxType"] == tax_type), None)
        if not t:
            raise ValueError(f"The TaxType code {tax_type} does not exist or cannot be used for this type of transaction.")
        return D(t["EffectiveRate"])

    def _acct(self, ref):
        a = next((a for a in self.accounts if (ref.get("AccountID") and a["AccountID"] == ref["AccountID"]) or (ref.get("Code") and a["Code"] == ref["Code"])), None)
        if not a:
            raise ValueError("Account could not be found")
        return a

    def _totals(self, x):
        sub, tax = D(0), D(0)
        for ln in x["LineItems"]:
            if not any(a["Code"] == ln.get("AccountCode") for a in self.accounts if a["Code"]):
                raise ValueError(f"Account code '{ln.get('AccountCode')}' is not a valid code for this document.")
            base = D(ln["Quantity"]) * D(ln["UnitAmount"])
            disc = base * D(ln["DiscountRate"]) / 100 if ln.get("DiscountRate") else D(ln.get("DiscountAmount") or 0)
            amount = r2(base - disc)
            t = r2(amount * self._rate(ln.get("TaxType", "NONE")) / 100) if x.get("LineAmountTypes") == "Exclusive" else D(0)
            ln.update(LineAmount=num(amount), TaxAmount=num(t))
            sub, tax = sub + amount, tax + t
        x.update(SubTotal=num(sub), TotalTax=num(tax), Total=num(sub + tax))
        return x

    def route(self, method, path, q, body):
        parts = path.strip("/").split("/")
        what, rid = parts[0], (parts[1] if len(parts) > 1 else None)
        if what == "Contacts":
            if method == "GET":
                return {"Contacts": self._where(list(self.contacts.values()), q)}
            out = []
            for c in body["Contacts"]:
                if any(x["Name"].lower() == c["Name"].lower() for x in self.contacts.values()):
                    raise ValueError("The contact name is already assigned to another contact. The contact name must be unique across all active contacts.")
                c = dict(c, ContactID=self.nid("contact"), ContactStatus="ACTIVE")
                self.contacts[c["ContactID"]] = c
                out.append(c)
            return {"Contacts": out}
        if what == "TaxRates":
            if method == "GET":
                return {"TaxRates": self.taxrates}
            out = []
            for t in body["TaxRates"]:
                rate = sum(D(c["Rate"]) for c in t["TaxComponents"])
                t = dict(t, TaxType=f"TAX{len(self.taxrates):03d}", EffectiveRate=float(rate), DisplayTaxRate=float(rate), Status="ACTIVE",
                         CanApplyToRevenue=True, CanApplyToExpenses=True)
                self.taxrates.append(t)
                out.append(t)
            return {"TaxRates": out}
        if what == "Accounts":
            if method == "GET":
                return {"Accounts": self.accounts}
            if any(a["Code"] == body["Code"] for a in self.accounts):
                raise ValueError("Please enter a unique Code.")
            a = dict(body, AccountID=self.nid("acct"), Status="ACTIVE")
            self.accounts.append(a)
            return {"Accounts": [a]}
        if what == "Invoices":
            if method == "GET" and rid:
                return {"Invoices": [self.invoices[rid]]}
            if method == "GET":
                rows = list(self.invoices.values())
                if q.get("InvoiceNumbers"):
                    rows = [r for r in rows if r["InvoiceNumber"] in q["InvoiceNumbers"].split(",")]
                return {"Invoices": self._where(rows, q)}
            if rid:  # void
                inv = self.invoices[rid]
                if D(inv["AmountPaid"]) or D(inv["AmountCredited"]):
                    raise ValueError("Invoice not of valid status for modification. This document cannot be edited as it has a payment or credit note allocated to it.")
                inv["Status"] = "VOIDED"
                return {"Invoices": [inv]}
            out = []
            for x in body["Invoices"]:
                errs = []
                if x["Contact"]["ContactID"] not in self.contacts:
                    errs.append("The contact does not exist")
                if x["Type"] == "ACCREC" and any(i["InvoiceNumber"] == x["InvoiceNumber"] and i["Type"] == "ACCREC" and i["Status"] not in ("VOIDED", "DELETED")
                                                 for i in self.invoices.values()):
                    errs.append("Invoice # must be unique.")
                if not errs:
                    try:
                        self._totals(x)
                    except ValueError as e:
                        errs.append(str(e))
                if errs:
                    out.append(dict(x, HasErrors=True, StatusAttributeString="ERROR", ValidationErrors=[{"Message": m} for m in errs]))
                    continue
                x = dict(x, InvoiceID=self.nid("inv"), AmountDue=x["Total"], AmountPaid=0.0, AmountCredited=0.0, StatusAttributeString="OK", HasErrors=False)
                self.invoices[x["InvoiceID"]] = x
                out.append(x)
            return {"Invoices": out}
        if what == "Quotes":
            if method == "GET" and rid:
                return {"Quotes": [self.quotes[rid]]}
            if method == "GET":
                return {"Quotes": [r for r in self.quotes.values() if not q.get("QuoteNumber") or r["QuoteNumber"] == q["QuoteNumber"]]}
            if rid:
                self.quotes[rid]["Status"] = body["Quotes"][0]["Status"]
                return {"Quotes": [self.quotes[rid]]}
            out = []
            for x in body["Quotes"]:
                x = self._totals(dict(x, QuoteID=self.nid("quote")))
                self.quotes[x["QuoteID"]] = x
                out.append(x)
            return {"Quotes": out}
        if what == "CreditNotes":
            if len(parts) == 3 and parts[2] == "Allocations":
                cn = self.credits[rid]
                for a in body["Allocations"]:
                    inv = self.invoices[a["Invoice"]["InvoiceID"]]
                    amt = D(a["Amount"])
                    if amt > D(inv["AmountDue"]) or amt > D(cn["RemainingCredit"]):
                        raise ValueError("The amount allocated is more than the amount outstanding on the invoice or remaining on the credit note.")
                    inv["AmountDue"], inv["AmountCredited"] = num(D(inv["AmountDue"]) - amt), num(D(inv["AmountCredited"]) + amt)
                    cn["RemainingCredit"] = num(D(cn["RemainingCredit"]) - amt)
                    cn.setdefault("Allocations", []).append({"Invoice": {"InvoiceID": inv["InvoiceID"]}, "Amount": num(amt)})
                    if D(inv["AmountDue"]) == 0:
                        inv["Status"] = "PAID"
                return {"Allocations": body["Allocations"]}
            if method == "GET" and rid:
                return {"CreditNotes": [self.credits[rid]]}
            if method == "GET":
                return {"CreditNotes": self._where(list(self.credits.values()), q)}
            out = []
            for x in body["CreditNotes"]:
                x = self._totals(dict(x, CreditNoteID=self.nid("cn")))
                x["RemainingCredit"] = x["Total"]
                self.credits[x["CreditNoteID"]] = x
                out.append(x)
            return {"CreditNotes": out}
        if what == "Payments":
            if method == "GET" and rid:
                return {"Payments": [self.payments[rid]]}
            if method == "GET":
                return {"Payments": self._where(list(self.payments.values()), q)}
            if rid:  # delete
                p = self.payments[rid]
                if p["Status"] != "DELETED":
                    inv = self.invoices[p["Invoice"]["InvoiceID"]]
                    inv["AmountDue"], inv["AmountPaid"], inv["Status"] = num(D(inv["AmountDue"]) + D(p["Amount"])), num(D(inv["AmountPaid"]) - D(p["Amount"])), "AUTHORISED"
                    p["Status"] = "DELETED"
                return {"Payments": [p]}
            out = []
            for p in body["Payments"]:
                inv = self.invoices.get(p["Invoice"]["InvoiceID"])
                if not inv or inv["Status"] not in ("AUTHORISED",):
                    raise ValueError("Payments can only be made against Authorised documents")
                if D(p["Amount"]) > D(inv["AmountDue"]):
                    raise ValueError("Payment amount exceeds the amount outstanding on this document")
                a = self._acct(p["Account"])
                if a["Type"] != "BANK" and not a.get("EnablePaymentsToAccount"):
                    raise ValueError("Account type is invalid for making a payment to/from")
                p = dict(p, PaymentID=self.nid("pay"), Status="AUTHORISED")
                inv["AmountDue"], inv["AmountPaid"] = num(D(inv["AmountDue"]) - D(p["Amount"])), num(D(inv["AmountPaid"]) + D(p["Amount"]))
                if D(inv["AmountDue"]) == 0:
                    inv["Status"] = "PAID"
                self.payments[p["PaymentID"]] = p
                out.append(p)
            return {"Payments": out}
        if what == "BankTransactions":
            if method == "GET" and rid:
                return {"BankTransactions": [self.banktx[rid]]}
            if method == "GET":
                return {"BankTransactions": self._where(list(self.banktx.values()), q)}
            if rid:
                self.banktx[rid]["Status"] = "DELETED"
                return {"BankTransactions": [self.banktx[rid]]}
            out = []
            for x in body["BankTransactions"]:
                if self._acct(x["BankAccount"])["Type"] != "BANK":
                    raise ValueError("The BankAccount must be a bank account")
                if x["Contact"]["ContactID"] not in self.contacts:
                    raise ValueError("The contact does not exist")
                x = self._totals(dict(x, BankTransactionID=self.nid("bt"), Status="AUTHORISED"))
                self.banktx[x["BankTransactionID"]] = x
                out.append(x)
            return {"BankTransactions": out}
        raise ValueError(f"no such endpoint {method} {path}")


# ==================================================================== Zoho Books
class FakeZoho(Fake):
    ACCOUNTS = "https://accounts.zoho.com/oauth/v2/token"
    API = "https://www.zohoapis.com/books/v3/"
    ONE = {"invoices": "invoice", "estimates": "estimate", "creditnotes": "creditnote", "bills": "bill", "expenses": "expense",
           "customerpayments": "payment", "vendorpayments": "vendorpayment"}
    IDS = {"invoices": "invoice_id", "estimates": "estimate_id", "creditnotes": "creditnote_id", "bills": "bill_id", "expenses": "expense_id",
           "customerpayments": "payment_id", "vendorpayments": "payment_id"}

    def __init__(self):
        super().__init__()
        self.access, self.refresh, self.code, self.org = "zoho-access-1", "zoho-refresh-1", "good-code", "org-khan"
        self.contacts, self.items = {}, {}
        self.docs = {k: {} for k in self.ONE}
        self.taxes = [{"tax_id": "tax-vat5", "tax_name": "VAT 5%", "tax_percentage": 5, "tax_type": "tax"}]
        self.chart = [{"account_id": f"z-{i}", "account_name": n, "account_type": t, "is_active": True} for i, (n, t) in enumerate((
            ("Sales", "income"), ("General Income", "income"), ("Cost of Goods Sold", "cost_of_goods_sold"), ("Utility Expense", "expense"),
            ("Rent Expense", "expense"), ("Salaries and Employee Wages", "expense"), ("Telephone Expense", "expense"), ("Other Expenses", "expense"),
            ("Bank Fees and Charges", "expense"), ("HBL Current Account", "bank"), ("Petty Cash", "cash"), ("Undeposited Funds", "cash")))]

    def creds(self):
        return {"client_id": "zoho-client", "client_secret": "zoho-secret", "accounts": "https://accounts.zoho.com", "api": "https://www.zohoapis.com",
                "refresh_token": self.refresh, "access_token": self.access, "expires_at": 9e12, "org": self.org, "org_name": "Khan Electronics"}

    def send(self, method, url, headers, data, timeout):
        body = self.record(method, url, headers, data)
        if url.startswith(self.ACCOUNTS):
            f = body or {}
            if f.get("grant_type") == "authorization_code":
                if f.get("code") != self.code or f.get("client_secret") != "zoho-secret":
                    return self.js(200, {"error": "invalid_code"})
                self.code = None
                return self.js(200, {"access_token": self.access, "refresh_token": self.refresh, "api_domain": "https://www.zohoapis.com",
                                     "token_type": "Bearer", "expires_in": 3600})
            if f.get("grant_type") == "refresh_token" and f.get("refresh_token") == self.refresh:
                self.access = f"zoho-access-{int(self.access.rsplit('-', 1)[1]) + 1}"
                return self.js(200, {"access_token": self.access, "api_domain": "https://www.zohoapis.com", "token_type": "Bearer", "expires_in": 3600})
            return self.js(200, {"error": "invalid_client"})
        how = self._rule(method, url)
        if how == "401" or headers.get("Authorization") != f"Zoho-oauthtoken {self.access}":
            return self.js(401, {"code": 57, "message": "You are not authorized to perform this operation"})
        if how in ("429", "500"):
            return self.js(int(how), {"code": 44 if how == "429" else 500, "message": "Too many requests" if how == "429" else "Internal error"},
                           {"Retry-After": "0"})
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        path = u.path.split("/books/v3/")[1].strip("/")
        if path != "organizations" and q.get("organization_id") != self.org:
            return self.js(400, {"code": 6041, "message": "This user is not associated with the organisation"})
        try:
            res = self.js(200, dict({"code": 0, "message": "success"}, **self.route(method, path, q, body or {})))
        except ValueError as e:
            res = self.js(400, {"code": 1001, "message": str(e)})
        if how == "drop":
            raise ConnectionResetError("the connection dropped before the answer came")
        return res

    # ---------------------------------------------------------------- the API
    def _tax(self, tid):
        if not tid:
            return []
        t = next((t for t in self.taxes if t["tax_id"] == tid), None)
        if not t:
            raise ValueError("Invalid value passed for tax_id")
        return [D(c["tax_percentage"]) for c in t.get("components") or [t]]

    def _acct(self, aid, types=None):
        a = next((a for a in self.chart if a["account_id"] == aid), None)
        if not a or (types and a["account_type"] not in types):
            raise ValueError("Invalid value passed for account_id")
        return a

    def _totals(self, x, purchase=False):
        sub, tax = D(0), D(0)
        for ln in x["line_items"]:
            if purchase:
                self._acct(ln.get("account_id"))
            if ln.get("item_id") and ln["item_id"] not in self.items:
                raise ValueError("Invalid value passed for item_id")
            base = D(ln["rate"]) * D(ln["quantity"])
            d = ln.get("discount")
            disc = (base * D(str(d).rstrip("%")) / 100) if isinstance(d, str) and d.endswith("%") else D(d or 0)
            amount = r2(base - disc)
            t = sum((r2(amount * p / 100) for p in self._tax(ln.get("tax_id"))), D(0))
            ln.update(item_total=num(amount))
            sub, tax = sub + amount, tax + t
        x.update(sub_total=num(sub), tax_total=num(tax), total=num(sub + tax), balance=num(sub + tax))
        return x

    def route(self, method, path, q, body):
        parts = path.split("/")
        what, rid = parts[0], (parts[1] if len(parts) > 1 else None)
        if what == "organizations":
            return {"organizations": [{"organization_id": self.org, "name": "Khan Electronics", "currency_code": "PKR", "is_default_org": True}]}
        if what == "contacts":
            if method == "GET":
                return {"contacts": [c for c in self.contacts.values() if not q.get("contact_name") or c["contact_name"].lower() == q["contact_name"].lower()]}
            if any(c["contact_name"].lower() == body["contact_name"].lower() and c["contact_type"] == body["contact_type"] for c in self.contacts.values()):
                raise ValueError(f"The {body['contact_type']} \"{body['contact_name']}\" already exists.")
            c = dict(body, contact_id=self.nid("contact"))
            self.contacts[c["contact_id"]] = c
            return {"contact": c}
        if what == "items":
            if method == "GET":
                return {"items": [i for i in self.items.values() if not q.get("name") or i["name"].lower() == q["name"].lower()]}
            i = dict(body, item_id=self.nid("item"))
            self.items[i["item_id"]] = i
            return {"item": i}
        if what == "settings" and rid == "taxes":
            if method == "GET":
                return {"taxes": self.taxes}
            t = dict(body, tax_id=self.nid("tax"))
            self.taxes.append(t)
            return {"tax": t}
        if what == "settings" and rid == "taxgroups":
            comps = [next(t for t in self.taxes if t["tax_id"] == i) for i in body["taxes"].split(",")]
            g = {"tax_id": self.nid("taxgroup"), "tax_name": body["tax_group_name"], "tax_percentage": float(sum(D(c["tax_percentage"]) for c in comps)),
                 "tax_type": "tax_group", "components": comps}
            self.taxes.append(g)
            return {"tax_group": {"tax_group_id": g["tax_id"], "tax_group_name": g["tax_name"], "taxes": comps}}
        if what == "chartofaccounts":
            if method == "GET":
                return {"chartofaccounts": self.chart}
            a = dict(body, account_id=self.nid("acct"), is_active=True)
            self.chart.append(a)
            return {"chart_of_account": a}
        if what in self.docs:
            return self._doc(method, what, rid, parts[2:], q, body)
        raise ValueError(f"no such endpoint {method} {path}")

    def _doc(self, method, what, rid, rest, q, body):
        store, one, idf = self.docs[what], self.ONE[what], self.IDS[what]
        if method == "GET" and rid:
            return {one: store[rid]}
        if method == "GET":
            rows = list(store.values())
            for f in ("invoice_number", "estimate_number", "creditnote_number", "reference_number"):
                if q.get(f):
                    rows = [r for r in rows if r.get(f) == q[f]]
            return {what: rows}
        if method == "DELETE":
            x = store.pop(rid)
            for a in x.get("invoices") or x.get("bills") or []:
                d = self.docs["invoices" if what == "customerpayments" else "bills"][a.get("invoice_id") or a.get("bill_id")]
                d["balance"] = num(D(d["balance"]) + D(a["amount_applied"]))
                d["status"] = "sent" if what == "customerpayments" else "open"
            return {}
        if rid and rest and rest[0] == "status":
            x, want = store[rid], rest[1]
            if want == "void" and what in ("invoices", "bills") and D(x["balance"]) != D(x["total"]):
                raise ValueError("Transactions with payments applied cannot be voided.")
            x["status"] = want
            return {}
        if rid and rest == ["invoices"]:  # a credit note applied to invoices
            cn = store[rid]
            for a in body["invoices"]:
                inv = self.docs["invoices"][a["invoice_id"]]
                amt = D(a["amount_applied"])
                if amt > D(inv["balance"]) or amt > D(cn["balance"]):
                    raise ValueError("The amount applied is more than the balance.")
                inv["balance"], cn["balance"] = num(D(inv["balance"]) - amt), num(D(cn["balance"]) - amt)
                cn.setdefault("invoices_credited", []).append({"invoice_id": inv["invoice_id"], "amount_applied": num(amt)})
                if D(inv["balance"]) == 0:
                    inv["status"] = "paid"
            return {"apply_to_invoices": body}
        x = dict(body, **{idf: self.nid(one)})
        if what in ("invoices", "estimates", "creditnotes"):
            if x.get("customer_id") not in self.contacts:
                raise ValueError("Invalid value passed for customer_id")
            field = {"invoices": "invoice_number", "estimates": "estimate_number", "creditnotes": "creditnote_number"}[what]
            if x.get(field) and q.get("ignore_auto_number_generation") != "true":
                raise ValueError(f"{field} is generated automatically: pass ignore_auto_number_generation=true to give your own")
            if any(r.get(field) == x.get(field) and r.get("status") != "void" for r in store.values()):
                raise ValueError(f"{one.title()} \"{x.get(field)}\" already exists.")
            self._totals(x)
            x["status"] = "open" if what == "creditnotes" else "draft"
        elif what == "bills":
            if x.get("vendor_id") not in self.contacts or not x.get("bill_number"):
                raise ValueError("Invalid value passed for vendor_id or bill_number")
            self._totals(x, purchase=True)
            x["status"] = "draft"
        elif what == "expenses":
            self._acct(x["account_id"], ("expense", "cost_of_goods_sold", "other_expense"))
            self._acct(x["paid_through_account_id"], ("bank", "cash"))
            t = sum((r2(D(x["amount"]) * p / 100) for p in self._tax(x.get("tax_id"))), D(0))
            x.update(total=num(D(x["amount"]) + t), status="unbilled")
        elif what in ("customerpayments", "vendorpayments"):
            rec = what == "customerpayments"
            if x.get("customer_id" if rec else "vendor_id") not in self.contacts:
                raise ValueError("Invalid contact")
            self._acct(x["account_id" if rec else "paid_through_account_id"], ("bank", "cash", "other_current_asset", "other_current_liability"))
            applied = x.get("invoices" if rec else "bills") or []
            if sum(D(a["amount_applied"]) for a in applied) > D(x["amount"]):
                raise ValueError("The amount applied is more than the payment.")
            for a in applied:
                d = self.docs["invoices" if rec else "bills"].get(a.get("invoice_id") or a.get("bill_id"))
                if not d or d["status"] in ("draft", "void"):
                    raise ValueError("Payments can be recorded only for sent invoices or open bills.")
                if D(a["amount_applied"]) > D(d["balance"]):
                    raise ValueError("The amount entered is more than the balance due.")
            for a in applied:
                d = self.docs["invoices" if rec else "bills"][a.get("invoice_id") or a.get("bill_id")]
                d["balance"] = num(D(d["balance"]) - D(a["amount_applied"]))
                if D(d["balance"]) == 0:
                    d["status"] = "paid"
            x["unused_amount"] = num(D(x["amount"]) - sum(D(a["amount_applied"]) for a in applied))
        store[x[idf]] = x
        return {one: x}


# ==================================================================== TallyPrime
GROUPS = ("Sundry Debtors", "Sundry Creditors", "Sales Accounts", "Purchase Accounts", "Duties & Taxes", "Indirect Expenses", "Indirect Incomes",
          "Direct Expenses", "Direct Incomes", "Bank Accounts", "Cash-in-Hand", "Current Assets", "Current Liabilities", "Loans & Advances (Asset)",
          "Capital Account", "Fixed Assets", "Stock-in-Hand", "Suspense A/c", "Provisions", "Bank OD A/c")
VTYPES = ("Sales", "Purchase", "Receipt", "Payment", "Journal", "Contra", "Credit Note", "Debit Note")


class FakeTally(Fake):
    """TallyPrime's XML gateway: UTF-16 in and out, the company must be loaded, masters by name (a Create on an existing
    ledger silently alters it, as Tally does), vouchers upserted by REMOTEID, refused when they do not balance, when a
    flag disagrees with its sign or a ledger or item is missing; automatic voucher numbering; Day Book export."""
    URL = "http://127.0.0.1:9000/"

    def __init__(self, company="Khan Electronics", manual_numbers=False):
        super().__init__()
        self.company, self.manual = company, manual_numbers
        self.ledgers = {"Cash": {"PARENT": "Cash-in-Hand"}, "Profit & Loss A/c": {"PARENT": "Primary"},
                        "HBL Current A/c": {"PARENT": "Bank Accounts"}, "Electricity Charges": {"PARENT": "Indirect Expenses"},
                        "Ali Traders": {"PARENT": "Sundry Debtors", "ISBILLWISEON": "Yes"}}
        self.units, self.items, self.vouchers, self.altered_masters = {}, {}, {}, []
        self.mid, self.seq, self.down = 100, {}, False

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url, "headers": dict(headers), "body": data})
        if self.down:
            raise ConnectionRefusedError("No connection could be made because the target machine actively refused it")
        how = self._rule(method, url)
        if "charset=utf-16" not in (headers.get("Content-Type") or "") or data[:2] != b"\xff\xfe":
            return self._answer("<RESPONSE>Unknown Request, cannot be processed</RESPONSE>")
        try:
            env = ET.fromstring(data.decode("utf-16"))
        except ET.ParseError:
            return self._answer("<RESPONSE>Unknown Request, cannot be processed</RESPONSE>")
        req, typ, ident = env.findtext("HEADER/TALLYREQUEST"), env.findtext("HEADER/TYPE"), env.findtext("HEADER/ID")
        comp = env.findtext(".//SVCURRENTCOMPANY")
        if req == "Import":
            res = self._import(env, comp)
        elif req == "Export":
            res = self._export(env, typ, ident, comp)
        else:
            res = "<RESPONSE>Unknown Request, cannot be processed</RESPONSE>"
        if how == "drop":
            raise ConnectionResetError("the connection dropped before the answer came")
        return self._answer(res)

    @staticmethod
    def _answer(xml):
        return 200, {"Content-Type": "text/xml; charset=utf-16"}, xml.encode("utf-16-le")  # no BOM, as Tally answers

    @staticmethod
    def _result(**kw):
        c = {k: kw.get(k, 0) for k in ("CREATED", "ALTERED", "DELETED", "LASTVCHID", "LASTMID", "COMBINED", "IGNORED", "ERRORS", "CANCELLED", "EXCEPTIONS")}
        line = f"<LINEERROR>{escape_xml(kw['LINEERROR'])}</LINEERROR>" if kw.get("LINEERROR") else ""
        return ("<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA><IMPORTRESULT>" +
                "".join(f"<{k}>{v}</{k}>" for k, v in c.items()) + f"</IMPORTRESULT>{line}</DATA></BODY></ENVELOPE>")

    # ---------------------------------------------------------------- imports
    def _import(self, env, comp):
        if comp != self.company:
            return self._result(ERRORS=1, LINEERROR=f"Could not set 'SVCurrentCompany' to '{comp}'")
        out = {"CREATED": 0, "ALTERED": 0, "CANCELLED": 0}
        for obj in env.find(".//TALLYMESSAGE"):
            if obj.tag in ("LEDGER", "UNIT", "STOCKITEM"):
                store = {"LEDGER": self.ledgers, "UNIT": self.units, "STOCKITEM": self.items}[obj.tag]
                name = obj.findtext("NAME") or obj.get("NAME")
                fields = {c.tag: (c.text or "") for c in obj if c.tag != "NAME"}
                if obj.tag == "LEDGER" and fields.get("PARENT") not in GROUPS:
                    return self._result(EXCEPTIONS=1, LINEERROR=f"Group '{fields.get('PARENT')}' does not exist!")
                if obj.tag == "STOCKITEM" and fields.get("BASEUNITS") not in self.units:
                    return self._result(EXCEPTIONS=1, LINEERROR=f"Unit '{fields.get('BASEUNITS')}' does not exist!")
                if name in store:
                    self.altered_masters.append(name)  # Tally would silently change the person's own master
                    store[name].update(fields)
                    out["ALTERED"] += 1
                else:
                    store[name] = fields
                    out["CREATED"] += 1
            elif obj.tag == "VOUCHER":
                err = self._voucher(obj, out)
                if err:
                    return self._result(EXCEPTIONS=1, LINEERROR=err)
        return self._result(**out)

    def _voucher(self, v, out):
        vtype = v.get("VCHTYPE") or v.findtext("VOUCHERTYPENAME")
        if vtype not in VTYPES:
            return f"Voucher Type '{vtype}' does not exist!"
        if v.get("ACTION") == "Cancel":
            day = dt.datetime.strptime(v.get("DATE"), "%d-%b-%Y").strftime("%Y%m%d")
            hit = next((x for x in self.vouchers.values() if x["VOUCHERNUMBER"] == v.get("TAGVALUE") and x["VOUCHERTYPENAME"] == vtype
                        and x["DATE"] == day and x["ISCANCELLED"] == "No"), None)
            if not hit:
                return f"Voucher '{v.get('TAGVALUE')}' does not exist!"
            hit["ISCANCELLED"] = "Yes"
            out["CANCELLED"] += 1
            return None
        view = v.findtext("PERSISTEDVIEW")
        if not view:
            return "No Entries in Voucher!"
        ledger_tag = "LEDGERENTRIES.LIST" if view == "Invoice Voucher View" else "ALLLEDGERENTRIES.LIST"
        lines = [{"LEDGERNAME": e.findtext("LEDGERNAME"), "ISDEEMEDPOSITIVE": e.findtext("ISDEEMEDPOSITIVE"), "ISPARTYLEDGER": e.findtext("ISPARTYLEDGER") or "No",
                  "AMOUNT": D(e.findtext("AMOUNT")), "BILLS": [{"NAME": x.findtext("NAME"), "BILLTYPE": x.findtext("BILLTYPE"), "AMOUNT": D(x.findtext("AMOUNT"))}
                                                               for x in e.findall("BILLALLOCATIONS.LIST")]}
                 for e in v.findall(ledger_tag)]  # the other list is silently dropped, as Tally does
        inv = [{"STOCKITEMNAME": e.findtext("STOCKITEMNAME"), "ISDEEMEDPOSITIVE": e.findtext("ISDEEMEDPOSITIVE"), "AMOUNT": D(e.findtext("AMOUNT")),
                "ACTUALQTY": e.findtext("ACTUALQTY"), "LEDGER": e.findtext("ACCOUNTINGALLOCATIONS.LIST/LEDGERNAME")} for e in v.findall("ALLINVENTORYENTRIES.LIST")]
        for x in lines + inv:
            if (x["ISDEEMEDPOSITIVE"] == "Yes") != (x["AMOUNT"] < 0):
                return "ISDEEMEDPOSITIVE does not agree with the sign of the amount"
        for x in lines:
            if x["LEDGERNAME"] not in self.ledgers:
                return f"Ledger '{x['LEDGERNAME']}' does not exist!"
        for x in inv:
            if x["STOCKITEMNAME"] not in self.items:
                return f"Stock Item '{x['STOCKITEMNAME']}' does not exist!"
            if x["LEDGER"] not in self.ledgers:
                return f"Ledger '{x['LEDGER']}' does not exist!"
        total = sum((x["AMOUNT"] for x in lines + inv), D(0))
        if total != 0:
            return f"Voucher totals do not match! Diff: {total}"
        rid = v.get("REMOTEID")
        old = next((k for k, x in self.vouchers.items() if x["REMOTEID"] == rid), None)
        if old is None:
            self.mid += 1
            mid = self.mid
            self.seq[vtype] = self.seq.get(vtype, 0) + 1
            number = v.findtext("VOUCHERNUMBER") if self.manual else str(self.seq[vtype])
            out["CREATED"] += 1
        else:
            mid, number = old, self.vouchers[old]["VOUCHERNUMBER"]
            out["ALTERED"] += 1
        for x in lines:  # bill by bill only on ledgers that have it on
            if self.ledgers[x["LEDGERNAME"]].get("ISBILLWISEON") != "Yes":
                x["BILLS"] = []
        self.vouchers[mid] = {"MASTERID": mid, "REMOTEID": rid, "VOUCHERTYPENAME": vtype, "DATE": v.findtext("DATE"), "VOUCHERNUMBER": number,
                              "REFERENCE": v.findtext("REFERENCE") or "", "NARRATION": v.findtext("NARRATION") or "", "VIEW": view,
                              "PARTYLEDGERNAME": v.findtext("PARTYLEDGERNAME") or "", "ISCANCELLED": "No", "LINES": lines, "INV": inv}
        out["LASTVCHID"] = mid
        return None

    def bills(self, party):
        """What is outstanding bill by bill for a party (owed to us positive), from the live vouchers."""
        out = {}
        for x in self.vouchers.values():
            if x["ISCANCELLED"] == "Yes":
                continue
            for ln in x["LINES"]:
                if ln["LEDGERNAME"] == party:
                    for bl in ln["BILLS"]:
                        out[bl["NAME"]] = out.get(bl["NAME"], D(0)) - bl["AMOUNT"]
        return {k: v for k, v in out.items() if v}

    # ---------------------------------------------------------------- exports
    def _export(self, env, typ, ident, comp):
        if comp is not None and comp != self.company:
            return "<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>"
        if typ == "Collection":
            ctype = env.findtext(".//COLLECTION/TYPE")
            if ctype == "Company":
                rows = f'<COMPANY NAME="{escape_xml(self.company)}"><NAME>{escape_xml(self.company)}</NAME></COMPANY>'
            elif ctype == "Ledger":
                rows = "".join(f'<LEDGER NAME="{escape_xml(n)}"><PARENT TYPE="String">&#4; {escape_xml(f["PARENT"])}</PARENT></LEDGER>'
                               for n, f in self.ledgers.items())
            elif ctype == "Unit":
                rows = "".join(f'<UNIT NAME="{escape_xml(n)}"><NAME>{escape_xml(n)}</NAME></UNIT>' for n in self.units)
            elif ctype == "StockItem":
                rows = "".join(f'<STOCKITEM NAME="{escape_xml(n)}"><BASEUNITS>{escape_xml(f.get("BASEUNITS", ""))}</BASEUNITS></STOCKITEM>'
                               for n, f in self.items.items())
            else:
                return "<RESPONSE>Unknown Request, cannot be processed</RESPONSE>"
            return f"<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DESC></DESC><DATA><COLLECTION>{rows}</COLLECTION></DATA></BODY></ENVELOPE>"
        if typ == "Data" and ident == "Day Book":
            a, z = env.findtext(".//SVFROMDATE"), env.findtext(".//SVTODATE")
            out = []
            for x in self.vouchers.values():
                if not a <= x["DATE"] <= z:
                    continue
                tag = "LEDGERENTRIES.LIST" if x["VIEW"] == "Invoice Voucher View" else "ALLLEDGERENTRIES.LIST"
                ents = "".join(f"<{tag}><LEDGERNAME>{escape_xml(ln['LEDGERNAME'])}</LEDGERNAME><ISDEEMEDPOSITIVE>{ln['ISDEEMEDPOSITIVE']}</ISDEEMEDPOSITIVE>"
                               f"<ISPARTYLEDGER>{ln['ISPARTYLEDGER']}</ISPARTYLEDGER><AMOUNT>{ln['AMOUNT']:.2f}</AMOUNT></{tag}>" for ln in x["LINES"])
                out.append(f'<TALLYMESSAGE><VOUCHER REMOTEID="tally-{x["MASTERID"]}" VCHTYPE="{escape_xml(x["VOUCHERTYPENAME"])}">'
                           f"<DATE>{x['DATE']}</DATE><VOUCHERTYPENAME>{escape_xml(x['VOUCHERTYPENAME'])}</VOUCHERTYPENAME>"
                           f"<VOUCHERNUMBER>{escape_xml(x['VOUCHERNUMBER'])}</VOUCHERNUMBER><REFERENCE>{escape_xml(x['REFERENCE'])}</REFERENCE>"
                           f"<NARRATION>{escape_xml(x['NARRATION'])}</NARRATION><ISCANCELLED>{x['ISCANCELLED']}</ISCANCELLED>{ents}</VOUCHER></TALLYMESSAGE>")
            return f"<ENVELOPE><BODY><DATA>{''.join(out)}</DATA></BODY></ENVELOPE>"
        return "<RESPONSE>Unknown Request, cannot be processed</RESPONSE>"


# ==================================================================== QuickBooks Online
class QboFault(Exception):
    def __init__(self, code, message, detail=""):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail


class FakeQbo(Fake):
    """QuickBooks Online's Accounting API (global edition): OAuth with Basic client auth and a refresh token whose value
    changes; SQL-like queries; customers and vendors sharing one name space; tax codes made through taxservice; Amount
    must equal Qty x UnitPrice; DocNumber unique; payments applied to invoices and credit memos; SyncToken on deletes;
    a requestid answered again with its first answer (refusals too, which is why a refused write needs a new one)."""
    TOKEN = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company/"
    TABLES = ("Customer", "Vendor", "Item", "Account", "TaxAgency", "TaxCode", "TaxRate", "Invoice", "Estimate", "CreditMemo", "Bill", "Purchase", "Payment",
              "BillPayment", "JournalEntry")

    def __init__(self):
        super().__init__()
        self.access, self.refresh, self.code, self.realm = "qbo-access-1", "qbo-refresh-1", "good-code", "9130"
        self.cid, self.secret, self.using_tax = "qbo-client", "qbo-secret", True
        self.requests, self.replays = {}, 0
        self.t = {k: {} for k in self.TABLES}
        for name, typ in (("Sales of Product Income", "Income"), ("Services", "Income"), ("Cost of Goods Sold", "Cost of Goods Sold"),
                          ("Utilities", "Expense"), ("Rent or Lease", "Expense"), ("Miscellaneous", "Expense"), ("Meezan Current", "Bank"),
                          ("Accounts Payable (A/P)", "Accounts Payable"), ("Accounts Receivable (A/R)", "Accounts Receivable")):
            self._add("Account", {"Name": name, "AccountType": typ, "Active": True})

    def creds(self):
        return {"client_id": self.cid, "client_secret": self.secret, "env": "sandbox", "realm": self.realm, "access_token": self.access,
                "refresh_token": self.refresh, "expires_at": 9e12, "company_name": "Khan Electronics"}

    def _add(self, table, obj):
        obj = dict(obj, Id=str(len(self.t[table]) + 1 + 100 * self.TABLES.index(table)), SyncToken="0")
        self.t[table][obj["Id"]] = obj
        return obj

    def send(self, method, url, headers, data, timeout):
        body = self.record(method, url, headers, data)
        if url.startswith(self.TOKEN):
            return self._token(headers, body or {})
        how = self._rule(method, url)
        if how == "401" or headers.get("Authorization") != f"Bearer {self.access}":
            return self.js(401, {"fault": {"error": [{"message": "message=AuthenticationFailed; errorCode=003200; statusCode=401"}]}})
        if how == "429":
            return self.js(429, {"Fault": {"Error": [{"Message": "message=ThrottleExceeded; errorCode=003001; statusCode=429", "code": "003001"}]}},
                           {"Retry-After": "0"})
        u = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        realm, _, path = u.path.split("/v3/company/")[1].partition("/")
        if realm != self.realm or q.get("minorversion") != "75":
            return self.js(400, {"Fault": {"Error": [{"Message": "wrong company or minor version", "code": "100"}]}})
        rid = q.get("requestid")
        if rid and rid in self.requests:
            self.replays += 1
            res = self.requests[rid]
        else:
            try:
                if how and how.startswith("fault"):
                    raise QboFault(how[5:], "Business Validation Error", "refused to order")
                res = self.js(200, dict(self.route(method, path, q, body or {}), time="2026-10-04T10:00:00.000-07:00"))
            except QboFault as e:
                res = self.js(400, {"Fault": {"Error": [{"Message": e.message, "Detail": e.detail, "code": e.code}], "type": "ValidationFault"}})
            if rid:
                self.requests[rid] = res  # answered again the same, refusals too
        if how == "drop":
            raise ConnectionResetError("the connection dropped before the answer came")
        return res

    def _token(self, headers, form):
        if headers.get("Authorization") != "Basic " + base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode():
            return self.js(401, {"error": "invalid_client"})
        if form.get("grant_type") == "authorization_code" and form.get("code") == self.code and form.get("redirect_uri"):
            self.code = None
        elif not (form.get("grant_type") == "refresh_token" and form.get("refresh_token") == self.refresh):
            return self.js(400, {"error": "invalid_grant"})
        n = int(self.refresh.rsplit("-", 1)[1]) + 1
        self.access, self.refresh = f"qbo-access-{n}", f"qbo-refresh-{n}"
        return self.js(200, {"access_token": self.access, "refresh_token": self.refresh, "expires_in": 3600, "x_refresh_token_expires_in": 8640000,
                             "token_type": "bearer"})

    # ---------------------------------------------------------------- queries
    def query(self, sql):
        m = re.match(r"SELECT \* FROM (\w+)(?: WHERE (.+?))?(?: MAXRESULTS \d+)?$", sql.strip())
        if not m:
            raise QboFault("4000", "Error parsing query", sql)
        rows = list(self.t[m.group(1)].values())
        for f, v in re.findall(r"(\w+) = ('(?:[^'\\]|\\.)*'|true|false)", m.group(2) or ""):
            v = v[1:-1].replace("\\'", "'").replace("\\\\", "\\") if v.startswith("'") else (v == "true")
            rows = [r for r in rows if r.get(f) == v]
        return {"QueryResponse": {m.group(1): rows} if rows else {}}

    # ---------------------------------------------------------------- writes
    def _ref(self, table, ref, types=None):
        x = self.t[table].get((ref or {}).get("value"))
        if not x or (types and x.get("AccountType") not in types):
            raise QboFault("2500", "Invalid Reference Id", f"{table} {ref}")
        return x

    def _rates(self, code_ref, side):
        code = self._ref("TaxCode", code_ref)
        return [D(self.t["TaxRate"][r["TaxRateRef"]["value"]]["RateValue"]) for r in code[f"{side}TaxRateList"]["TaxRateDetail"]]

    def _txn(self, x, side, item_lines=True):
        if x.get("GlobalTaxCalculation") != "TaxExcluded":
            raise QboFault("6000", "A business validation error has occurred", "GlobalTaxCalculation is required for this company")
        if x.get("DocNumber") and len(x["DocNumber"]) > 21:
            raise QboFault("6000", "String length is either shorter or longer than supported", "DocNumber")
        sub, tax = D(0), D(0)
        for ln in x["Line"]:
            if item_lines:
                d = ln["SalesItemLineDetail"]
                self._ref("Item", d["ItemRef"])
                if r2(D(d["Qty"]) * D(d["UnitPrice"])) != r2(ln["Amount"]):
                    raise QboFault("6070", "Amount is not equal to UnitPrice * Qty", f"{ln['Amount']}")
                code = d["TaxCodeRef"]
            else:
                d = ln["AccountBasedExpenseLineDetail"]
                self._ref("Account", d["AccountRef"])
                code = d.get("TaxCodeRef")
            t = sum((r2(D(ln["Amount"]) * r / 100) for r in self._rates(code, side)), D(0)) if code else D(0)
            sub, tax = sub + D(ln["Amount"]), tax + t
        x.update(TotalAmt=num(sub + tax), TxnTaxDetail={"TotalTax": num(tax)}, Balance=num(sub + tax))
        return x

    def _unique_doc(self, table, x):
        if x.get("DocNumber") and any(r.get("DocNumber") == x["DocNumber"] and not r.get("Voided") for r in self.t[table].values()):
            raise QboFault("6140", "Duplicate Document Number Error", f"Duplicate Document Number Error : You must specify a different number. {x['DocNumber']}")

    def route(self, method, path, q, body):
        parts = path.split("/")
        what = parts[0]
        if method == "GET":
            if what == "query":
                return self.query(q["query"])
            if what == "companyinfo":
                return {"CompanyInfo": {"CompanyName": "Khan Electronics", "Country": "PK"}}
            if what == "preferences":
                return {"Preferences": {"TaxPrefs": {"UsingSalesTax": self.using_tax}}}
            table = next(t for t in self.TABLES if t.lower() == what)
            return {table: self.t[table][parts[1]]}
        if what == "taxservice":
            if not self.using_tax:
                raise QboFault("6000", "A business validation error has occurred", "Set up sales tax in QuickBooks first")
            code = self._add("TaxCode", {"Name": body["TaxCode"], "SalesTaxRateList": {"TaxRateDetail": []}, "PurchaseTaxRateList": {"TaxRateDetail": []}})
            for d in body["TaxRateDetails"]:
                rate = self._add("TaxRate", {"Name": d["TaxRateName"], "RateValue": d["RateValue"], "AgencyRef": {"value": d["TaxAgencyId"]}})
                code[f"{d['TaxApplicableOn']}TaxRateList"]["TaxRateDetail"].append({"TaxRateRef": {"value": rate["Id"]}})
            return {"TaxCode": code["Name"], "TaxCodeId": code["Id"], "TaxRateDetails": body["TaxRateDetails"]}
        table = next(t for t in self.TABLES if t.lower() == what)
        if q.get("operation") in ("delete", "void"):
            x = self.t[table][body["Id"]]
            if x["SyncToken"] != body.get("SyncToken"):
                raise QboFault("5010", "Stale Object Error", "You and someone else edited the same thing")
            if table == "Payment":
                for ln in x["Line"]:
                    for lt in ln["LinkedTxn"]:
                        inv = self.t["Invoice" if lt["TxnType"] == "Invoice" else "CreditMemo"][lt["TxnId"]]
                        key = "Balance" if lt["TxnType"] == "Invoice" else "RemainingCredit"
                        inv[key] = num(D(inv[key]) + D(ln["Amount"]))
            if q["operation"] == "void":
                x.update(Voided=True, TotalAmt=0.0, Balance=0.0, SyncToken=str(int(x["SyncToken"]) + 1))
                return {table: x}
            del self.t[table][body["Id"]]
            return {table: {"Id": body["Id"], "status": "Deleted"}}
        x = dict(body)
        if table in ("Customer", "Vendor"):
            if any(r["DisplayName"].lower() == x["DisplayName"].lower() for t in ("Customer", "Vendor") for r in self.t[t].values()):
                raise QboFault("6240", "Duplicate Name Exists Error", f"The name supplied already exists. : {x['DisplayName']}")
        elif table == "Item":
            if any(r["Name"].lower() == x["Name"].lower() for r in self.t["Item"].values()):
                raise QboFault("6240", "Duplicate Name Exists Error", x["Name"])
            self._ref("Account", x["IncomeAccountRef"], ("Income",))
        elif table in ("Invoice", "Estimate", "CreditMemo"):
            self._ref("Customer", x["CustomerRef"])
            self._unique_doc(table, x)
            self._txn(x, "Sales")
            if table == "CreditMemo":
                x["RemainingCredit"] = x["TotalAmt"]
        elif table == "Bill":
            self._ref("Vendor", x["VendorRef"])
            self._txn(x, "Purchase", item_lines=False)
        elif table == "Purchase":
            self._ref("Account", x["AccountRef"], ("Bank",))
            self._unique_doc(table, x)
            self._txn(x, "Purchase", item_lines=False)
        elif table == "Payment":
            self._ref("Customer", x["CustomerRef"])
            if D(x["TotalAmt"]):
                self._ref("Account", x["DepositToAccountRef"], ("Bank", "Other Current Asset"))
            net = D(0)
            for ln in x["Line"]:
                for lt in ln["LinkedTxn"]:
                    if lt["TxnType"] == "Invoice":
                        inv = self.t["Invoice"].get(lt["TxnId"])
                        if not inv or D(ln["Amount"]) > D(inv["Balance"]):
                            raise QboFault("6000", "A business validation error has occurred", "The payment is more than the invoice's balance")
                        net += D(ln["Amount"])
                    else:
                        cm = self.t["CreditMemo"][lt["TxnId"]]
                        if D(ln["Amount"]) > D(cm["RemainingCredit"]):
                            raise QboFault("6000", "A business validation error has occurred", "More than the credit memo's remaining credit")
                        net -= D(ln["Amount"])
            if net > D(x["TotalAmt"]):
                raise QboFault("6000", "A business validation error has occurred", "Applied more than the payment")
            for ln in x["Line"]:
                for lt in ln["LinkedTxn"]:
                    t = self.t["Invoice" if lt["TxnType"] == "Invoice" else "CreditMemo"][lt["TxnId"]]
                    key = "Balance" if lt["TxnType"] == "Invoice" else "RemainingCredit"
                    t[key] = num(D(t[key]) - D(ln["Amount"]))
            x["UnappliedAmt"] = num(D(x["TotalAmt"]) - net)
        elif table == "BillPayment":
            self._ref("Vendor", x["VendorRef"])
            self._ref("Account", x["CheckPayment"]["BankAccountRef"], ("Bank",))
            for ln in x["Line"]:
                bill = self.t["Bill"][ln["LinkedTxn"][0]["TxnId"]]
                if D(ln["Amount"]) > D(bill["Balance"]):
                    raise QboFault("6000", "A business validation error has occurred", "The payment is more than the bill's balance")
                bill["Balance"] = num(D(bill["Balance"]) - D(ln["Amount"]))
        elif table == "JournalEntry":
            dr = sum(D(ln["Amount"]) for ln in x["Line"] if ln["JournalEntryLineDetail"]["PostingType"] == "Debit")
            cr = sum(D(ln["Amount"]) for ln in x["Line"] if ln["JournalEntryLineDetail"]["PostingType"] == "Credit")
            if dr != cr:
                raise QboFault("2300", "The transaction is not balanced", f"{dr} != {cr}")
            for ln in x["Line"]:
                a = self._ref("Account", ln["JournalEntryLineDetail"]["AccountRef"])
                if a["AccountType"] == "Accounts Payable" and not ln["JournalEntryLineDetail"].get("Entity"):
                    raise QboFault("6000", "A business validation error has occurred", "A payable line needs a vendor")
        return {table: self._add(table, x)}


# ==================================================================== FBR Digital Invoicing (PRAL)
class FakeFbr(Fake):
    """PRAL's DI API v1.12: the Bearer token, validate (no number) and post (a number: seller + 'DI' + time), each line
    checked (HS code, rate, the tax worked out from the value), the reference list of provinces."""
    GW = "https://gw.fbr.gov.pk"

    def __init__(self):
        super().__init__()
        self.token, self.posted, self.clock = "pral-sandbox-token", [], 1759560000000

    def send(self, method, url, headers, data, timeout):
        body = self.record(method, url, headers, data)
        if headers.get("Authorization") != f"Bearer {self.token}":
            return self.js(401, {"message": "Unauthorized"})
        path = urllib.parse.urlparse(url).path
        if path == "/pdi/v1/provinces":
            return self.js(200, [{"stateProvinceCode": 7, "stateProvinceDesc": "PUNJAB"}, {"stateProvinceCode": 8, "stateProvinceDesc": "SINDH"}])
        how = self._rule(method, url)
        if not path.startswith("/di_data/v1/di/"):
            return self.js(404, {"message": "no such method"})
        errs = []
        if len(body.get("sellerNTNCNIC", "")) not in (7, 13):
            errs.append(("0001", "Seller not registered for sales tax, please provide valid registration/NTN."))
        if path.endswith("_sb") and not body.get("scenarioId"):
            errs.append(("0090", "Provide scenario id."))
        lines = []
        for i, it in enumerate(body["items"], 1):
            e = None
            if not it["hsCode"]:
                e = ("0019", "Please provide HSCode")
            elif not it["rate"].endswith("%"):
                e = ("0046", "Provide rate.")
            elif r2(D(it["valueSalesExcludingST"]) * D(it["rate"].rstrip("%")) / 100) != r2(it["salesTaxApplicable"]):
                e = ("0102", "The calculated sales tax does not match the provided sales tax")
            lines.append({"itemSNo": str(i), "statusCode": "01" if e else "00", "status": "Invalid" if e else "Valid", "invoiceNo": None,
                          "errorCode": e[0] if e else "", "error": e[1] if e else ""})
        if errs:
            res = {"dated": "2026-10-04 10:00:00", "validationResponse": {"statusCode": "01", "status": "Invalid", "errorCode": errs[0][0], "error": errs[0][1],
                                                                          "invoiceStatuses": None}}
        else:
            ok = all(x["status"] == "Valid" for x in lines)
            res = {"dated": "2026-10-04 10:00:00", "validationResponse": {"statusCode": "00", "status": "Valid" if ok else "invalid", "error": "",
                                                                          "invoiceStatuses": lines}}
            if ok and "postinvoicedata" in path:
                self.clock += 1
                number = f"{body['sellerNTNCNIC']}DI{self.clock}"
                res["invoiceNumber"] = number
                for x in lines:
                    x["invoiceNo"] = f"{number}-{x['itemSNo']}"
                self.posted.append(dict(body, invoiceNumber=number))
        if how == "drop":
            raise ConnectionResetError("the connection dropped before the answer came")
        return self.js(200, res)
