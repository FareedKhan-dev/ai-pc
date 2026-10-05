"""Xero (Accounting API) for a Pakistan organisation, through a PKCE app (no secret kept on this PC) on Xero's free
Starter developer tier (1,000 calls a day per organisation, 60 a minute).

A Pakistan organisation runs Xero's global edition: sales tax is a custom tax rate made here once ('Sales Tax 18%'),
further tax a line to its own liability account. Invoices go as ACCREC (AUTHORISED, tax exclusive, our number as the
InvoiceNumber), bills as ACCPAY, quotations as Quotes, returns as credit notes allocated to their invoice, money in and
out as payments against them (income tax a customer withheld as a payment from an 'Income Tax Deducted by Customers'
account, an advance as a prepayment), expenses as SPEND bank transactions. Every create carries an Idempotency-Key (a
retry of the call cannot make it twice), and every remote object carries our number as its mark, so it is looked for
before a new try (an answer lost after Xero saved it).

Sign-in: http://localhost:3009/callback (Xero refuses 127.0.0.1), PKCE S256; access tokens last 30 minutes, refresh
tokens 60 days and rotate (each new one is kept at once); Xero-tenant-id on every call.
"""

import base64
import hashlib
import re
import secrets
import time
import urllib.parse
import uuid
import webbrowser
from decimal import Decimal

from ai_pc.accounts.money import mul
from ai_pc.accounts.systems import Connector, SyncError, bill_account, linked, match_expense, once, rate_of, splits
from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

API = "https://api.xero.com/api.xro/2.0"
CONNECTIONS = "https://api.xero.com/connections"
AUTH = "https://login.xero.com/identity/connect/authorize"
TOKEN = "https://identity.xero.com/connect/token"
PORT, PATH = 3009, "/callback"
SCOPES = [
    "openid",
    "offline_access",
    "accounting.invoices",
    "accounting.payments",
    "accounting.banktransactions",
    "accounting.contacts",
    "accounting.settings",
    "accounting.reports.profitandloss.read",
    "accounting.reports.balancesheet.read",
    "accounting.reports.trialbalance.read",
    "accounting.reports.aged.read",
]
# accounts made in the organisation when missing: role -> (name, type, code)
MADE = {
    "further_tax": ("Further Tax Payable", "CURRLIAB", "2110"),
    "wht": ("Income Tax Deducted by Customers", "CURRASSET", "1310"),
    "wht_payable": ("Income Tax Withheld from Suppliers", "CURRLIAB", "2200"),
}
APP = {
    "label": "Xero",
    "fields": [("client_id", "Client id of your Xero app", False)],
    "steps": [
        "Open https://developer.xero.com/app/manage and sign in with your Xero login; click 'New app'.",
        "Choose 'Auth code with PKCE' (a desktop app: no secret), name it AI PC, Company or application URL: any page of yours, "
        "Redirect URI: http://localhost:3009/callback",
        "Copy the app's Client id, then run 'ai-pc accounts connect xero': a Xero sign-in opens once; pick your organisation and allow.",
        "Sales tax is set up in Xero as 'Sales Tax 18%' the first time an invoice goes (Pakistan organisations use Xero's global edition).",
    ],
    "notes": "Free for your own organisation (Xero's Starter developer tier: 1,000 calls a day). Xero's own Ignite/Starter plans cap how many "
    "invoices you can approve a month; Grow and above do not.",
}


def connect(values, open_url=webbrowser.open, show=print, transport=None, timeout=300, store=None):
    from ai_pc.accounts.systems.loop import loopback_localhost

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    def build(redirect, state):
        return (
            AUTH
            + "?"
            + urllib.parse.urlencode(
                {
                    "response_type": "code",
                    "client_id": values["client_id"],
                    "redirect_uri": redirect,
                    "scope": " ".join(SCOPES),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    got, redirect = loopback_localhost(build, PORT, PATH, show=show, open_url=open_url, timeout=timeout, who="Xero")
    return finish(values["client_id"], got["code"], redirect, verifier, transport, store)


def finish(client_id, code, redirect, verifier, transport=None, store=None):
    """The sign-in's code -> tokens -> the organisation it allowed; kept encrypted (or given to `store`)."""
    tok = _token(
        {"grant_type": "authorization_code", "client_id": client_id, "code": code, "redirect_uri": redirect, "code_verifier": verifier}, transport
    )
    conns = Api(CONNECTIONS, headers={"Authorization": f"Bearer {tok['access_token']}"}, service="xero", transport=transport).request(
        "GET", CONNECTIONS
    )
    orgs = [c for c in conns if c.get("tenantType") == "ORGANISATION"] if isinstance(conns, list) else []
    if not orgs:
        raise SyncError("Xero gave access to no organisation: connect again and tick your organisation", "auth")
    creds = {
        "client_id": client_id,
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": time.time() + int(tok.get("expires_in") or 1800) - 60,
        "tenant": orgs[0]["tenantId"],
        "tenant_name": orgs[0].get("tenantName"),
        "tenants": {o["tenantName"]: o["tenantId"] for o in orgs},
    }
    (store or (lambda c: vault.put("xero", c)))(creds)
    return {
        "who": orgs[0].get("tenantName"),
        "where": "Xero" + (f"; also allowed: {', '.join(o['tenantName'] for o in orgs[1:])}" if len(orgs) > 1 else ""),
    }


def _token(form, transport=None):
    try:
        return Api(TOKEN, service="xero sign-in", transport=transport).request(
            "POST", TOKEN, data=urllib.parse.urlencode(form).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, retries=1
        )
    except HubError as e:
        raise SyncError(f"Xero refused the sign-in ({e}); run 'ai-pc accounts connect xero' again", "auth") from e


def _cents(x):
    return int((Decimal(str(x or 0)) * 100).quantize(Decimal("1")))


class System(Connector):
    name, label = "xero", "Xero"
    kinds = ("invoice", "quote", "bill", "credit_note", "receipt", "payment", "expense")

    def __init__(self, creds=None, transport=None):
        super().__init__()
        self.from_vault = creds is None
        self.creds = (vault.get("xero") or {}) if creds is None else creds
        self.transport = transport
        self._accts = None

    def ready(self):
        if not self.creds.get("refresh_token") or not self.creds.get("tenant"):
            return False, "Xero is not connected: 'ai-pc accounts steps xero' shows how (free, a few minutes)"
        return True, f"Xero ({self.creds.get('tenant_name') or 'your organisation'})"

    def token(self):
        c = self.creds
        if not c.get("access_token") and not c.get("refresh_token"):
            raise SyncError("Xero is not connected: run 'ai-pc accounts steps xero'", "auth")
        if c.get("access_token") and c.get("expires_at", 0) > time.time() + 60:
            return c["access_token"]
        tok = _token({"grant_type": "refresh_token", "client_id": c["client_id"], "refresh_token": c["refresh_token"]}, self.transport)
        c.update(
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token") or c["refresh_token"],  # Xero's refresh tokens rotate
            expires_at=time.time() + int(tok.get("expires_in") or 1800) - 60,
        )
        if self.from_vault:
            vault.put("xero", {k: c[k] for k in ("access_token", "refresh_token", "expires_at")})
        return c["access_token"]

    def call(self, method, path, body=None, params=None, idem=False):
        self.calls += 1
        h = {"Idempotency-Key": uuid.uuid4().hex} if idem else None  # the same key on every retry of this call
        api = Api(
            API,
            headers={"Authorization": f"Bearer {self.token()}", "Xero-tenant-id": self.creds.get("tenant", "")},
            service="xero",
            transport=self.transport,
        )
        try:
            return api.request(method, path, params=params, json_body=body, headers=h)
        except HubError as e:
            raise self.classify(e) from e

    @staticmethod
    def classify(e):
        b = e.body if isinstance(e.body, dict) else {}
        if e.status is None:
            return SyncError(f"Xero could not be reached ({e})", "offline")
        if e.status == 401:
            return SyncError("Xero: the sign-in expired or lacks a permission; run 'ai-pc accounts connect xero'", "auth")
        if e.status == 403:
            return SyncError("Xero: this organisation is no longer connected to the app (or your user lacks the role); connect again", "auth")
        if e.status == 429:
            return SyncError("Xero: the API limit for this minute or today is reached (1,000 calls a day); try again later", "limit")
        msgs = [v.get("Message") for el in b.get("Elements") or [] for v in el.get("ValidationErrors") or []]
        text = "; ".join(m for m in msgs if m) or b.get("Message") or b.get("Detail") or str(e)
        if "limit of invoices" in text.lower():
            return SyncError("Xero: your Xero plan's monthly limit of approved invoices is reached", "limit")
        return SyncError("Xero: " + text)

    def _one(self, path, params, key, test=None):
        """The live object (not deleted or voided) a search finds, by its id field."""
        rows = [x for x in self.call("GET", path, params=params).get(path) or [] if x.get("Status") not in ("DELETED", "VOIDED")]
        rows = [x for x in rows if test is None or test(x)]
        return rows[0][key] if rows else None

    # ---------------------------------------------------------------- what a document needs there
    def contact(self, b, party):
        def make():
            name = party["name"].replace('"', "")
            found = self.call("GET", "Contacts", params={"where": f'Name=="{name}"'}).get("Contacts") or []
            if found:
                return found[0]["ContactID"]
            c = {"Name": party["name"]}
            if party.get("strn") or party.get("ntn") or party.get("cnic"):
                c["TaxNumber"] = party.get("strn") or party.get("ntn") or party.get("cnic")
            if party.get("email"):
                c["EmailAddress"] = party["email"]
            if party.get("phone"):
                c["Phones"] = [{"PhoneType": "DEFAULT", "PhoneNumber": party["phone"]}]
            if party.get("address"):
                c["Addresses"] = [{"AddressType": "STREET", "AddressLine1": party["address"]}]
            return self.call("PUT", "Contacts", {"Contacts": [c]}, idem=True)["Contacts"][0]["ContactID"]

        return once(b, self.name, "party", party["id"], make)

    def tax_type(self, b, rate):
        if not rate or Decimal(str(rate)) == 0:
            return "NONE"
        want = Decimal(str(rate))

        def make():
            for t in self.call("GET", "TaxRates").get("TaxRates") or []:
                if (
                    t.get("Status") == "ACTIVE"
                    and Decimal(str(t.get("EffectiveRate", t.get("DisplayTaxRate", -1)))) == want
                    and t.get("CanApplyToRevenue") is not False
                    and t.get("CanApplyToExpenses") is not False
                ):
                    return t["TaxType"]
            body = {
                "TaxRates": [
                    {
                        "Name": f"Sales Tax {want.normalize()}%",
                        "TaxComponents": [{"Name": "Sales Tax", "Rate": float(want), "IsCompound": False, "IsNonRecoverable": False}],
                    }
                ]
            }
            return self.call("PUT", "TaxRates", body, idem=True)["TaxRates"][0]["TaxType"]

        return once(b, self.name, "tax", f"sales tax {want.normalize()}", make)

    def accounts(self, fresh=False):
        if self._accts is None or fresh:
            self._accts = [a for a in self.call("GET", "Accounts").get("Accounts") or [] if a.get("Status", "ACTIVE") == "ACTIVE"]
        return self._accts

    def account(self, b, role):
        """The organisation's account for a role: by Code for lines, by AccountID for a bank account; made when missing."""

        def of(t, rx=None):
            return [a for a in self.accounts() if a.get("Type") in t and (not rx or re.search(rx, a.get("Name") or "", re.I))]

        def make():
            if role in MADE:
                name, typ, code = MADE[role]
                hit = next((a for a in self.accounts() if (a.get("Name") or "").lower() == name.lower()), None)
                if not hit:
                    body = {"Code": code, "Name": name, "Type": typ}
                    if role != "further_tax":
                        body["EnablePaymentsToAccount"] = True
                    hit = (self.call("PUT", "Accounts", body, idem=True).get("Accounts") or [{}])[0]
                    self.accounts(fresh=True)
                return hit["Code"]
            if role in ("bank", "cash"):
                banks = of(("BANK",))
                pick = (
                    [a for a in banks if re.search(r"cash", a.get("Name") or "", re.I)]
                    if role == "cash"
                    else [a for a in banks if not re.search(r"cash", a.get("Name") or "", re.I)]
                )
                pick = pick or banks
                if not pick:
                    raise SyncError("Xero: add your bank account in Xero first (Accounting > Bank accounts)")
                return pick[0]["AccountID"]
            if role.startswith("expense:"):
                code = match_expense(role.split(":", 1)[1], [(a["Code"], a.get("Name")) for a in of(("EXPENSE", "OVERHEADS")) if a.get("Code")])
                if not code:
                    raise SyncError("Xero: the organisation has no expense account")
                return code
            pick = {
                "sales": of(("REVENUE", "SALES"), r"sales") or of(("REVENUE", "SALES")),
                "services": of(("REVENUE", "SALES"), r"service") or of(("REVENUE", "SALES"), r"sales") or of(("REVENUE", "SALES")),
                "purchases": of(("DIRECTCOSTS",), r"purchase") or of(("DIRECTCOSTS",)),
            }[role]
            pick = [a for a in pick if a.get("Code")]
            if not pick:
                raise SyncError(f"Xero: the organisation has no {role} account")
            return pick[0]["Code"]

        return once(b, self.name, "account", role, make)

    def _line(self, b, ln, acct):
        row = {
            "Description": ln["description"],
            "Quantity": float(Decimal(ln["qty"])),
            "UnitAmount": ln["rate"] / 100,
            "AccountCode": acct,
            "TaxType": self.tax_type(b, ln.get("tax_rate")),
        }
        if ln.get("discount"):
            d = str(ln["discount"]).replace(" ", "")
            if d.endswith("%"):
                row["DiscountRate"] = float(d.rstrip("%"))
            else:  # the discount this line actually got (a part of a line returned gets its part of it)
                row["DiscountAmount"] = (mul(ln["rate"], ln["qty"]) - ln["amount"]) / 100
        return row

    def _lines(self, b, doc, purchase=False):
        out = []
        for ln in doc["lines"]:
            if purchase:
                code = bill_account(b, ln)
                acct = self.account(b, "purchases" if code == "5000" else f"expense:{code}")
            else:
                acct = self.account(b, "services" if ln.get("kind") == "service" else "sales")
            out.append(self._line(b, ln, acct))
        if (doc.get("totals") or {}).get("further_tax"):
            out.append(
                {
                    "Description": "Further tax (buyer without sales tax registration)",
                    "Quantity": 1,
                    "UnitAmount": doc["totals"]["further_tax"] / 100,
                    "AccountCode": self.account(b, "further_tax"),
                    "TaxType": "NONE",
                }
            )
        return out

    # ---------------------------------------------------------------- creating, reading, cancelling
    def create(self, b, doc):
        k, p, n = doc["kind"], doc.get("party"), doc["number"]
        if k in ("invoice", "bill"):

            def make():
                inv = {
                    "Type": "ACCREC" if k == "invoice" else "ACCPAY",
                    "Contact": {"ContactID": self.contact(b, p)},
                    "Date": doc["date"],
                    "DueDate": doc.get("due") or doc["date"],
                    "LineAmountTypes": "Exclusive",
                    "Status": "AUTHORISED",
                    "InvoiceNumber": n if k == "invoice" else (doc.get("ref") or n),
                    "Reference": n if k == "bill" else (doc.get("ref") or ""),
                    "LineItems": self._lines(b, doc, purchase=k == "bill"),
                }
                el = self.call("POST", "Invoices", {"Invoices": [inv]}, params={"summarizeErrors": "false"}, idem=True)["Invoices"][0]
                if el.get("HasErrors") or el.get("StatusAttributeString") == "ERROR":
                    raise SyncError("Xero: " + "; ".join(v.get("Message", "") for v in el.get("ValidationErrors") or []))
                return el["InvoiceID"]

            look = (
                (lambda: self._one("Invoices", {"InvoiceNumbers": n}, "InvoiceID", lambda x: x.get("Type") == "ACCREC"))
                if k == "invoice"
                else (lambda: self._one("Invoices", {"where": f'Type=="ACCPAY" AND Reference=="{n}"'}, "InvoiceID"))
            )
            return self.step(b, doc, "made", make, look)
        if k == "quote":

            def make():
                q = {
                    "Contact": {"ContactID": self.contact(b, p)},
                    "Date": doc["date"],
                    "ExpiryDate": doc.get("due"),
                    "QuoteNumber": n,
                    "LineAmountTypes": "Exclusive",
                    "Status": "SENT",
                    "LineItems": self._lines(b, doc),
                }
                return self.call("PUT", "Quotes", {"Quotes": [q]}, idem=True)["Quotes"][0]["QuoteID"]

            return self.step(b, doc, "made", make, lambda: self._one("Quotes", {"QuoteNumber": n}, "QuoteID"))
        if k == "credit_note":
            inv = b.doc_by_number(doc["invoice"])
            target = linked(b, inv["id"], self.name)

            def make():
                cn = {
                    "Type": "ACCRECCREDIT",
                    "Contact": {"ContactID": self.contact(b, p)},
                    "Date": doc["date"],
                    "CreditNoteNumber": n,
                    "Reference": inv["number"],
                    "LineAmountTypes": "Exclusive",
                    "Status": "AUTHORISED",
                    "LineItems": self._lines(b, doc),
                }
                return self.call("PUT", "CreditNotes", {"CreditNotes": [cn]}, idem=True)["CreditNotes"][0]["CreditNoteID"]

            cid = self.step(b, doc, "made", make, lambda: self._one("CreditNotes", {"where": f'CreditNoteNumber=="{n}"'}, "CreditNoteID"))

            def allocate():
                self.call(
                    "PUT",
                    f"CreditNotes/{cid}/Allocations",
                    {"Allocations": [{"Invoice": {"InvoiceID": target}, "Amount": doc["total"] / 100, "Date": doc["date"]}]},
                    idem=True,
                )
                return "allocated"

            def allocated():
                x = (self.call("GET", f"CreditNotes/{cid}").get("CreditNotes") or [{}])[0]
                return "allocated" if any((a.get("Invoice") or {}).get("InvoiceID") == target for a in x.get("Allocations") or []) else None

            self.step(b, doc, "allocated", allocate, allocated)
            return cid
        if k in ("receipt", "payment"):
            parts, advance = splits(b, doc)
            src = "bank" if doc.get("bank", True) else "cash"
            ids = []
            for i, (doc_id, cash, wht) in enumerate(parts, 1):
                target = linked(b, doc_id, self.name)
                if cash:
                    ids.append(
                        self.step(
                            b,
                            doc,
                            f"payment {i}",
                            lambda: self._pay(target, {"AccountID": self.account(b, src)}, cash, doc, n),
                            lambda: self._paid(target, cash, n),
                        )
                    )
                if wht:
                    acct = self.account(b, "wht" if k == "receipt" else "wht_payable")
                    ids.append(
                        self.step(
                            b,
                            doc,
                            f"tax withheld {i}",
                            lambda: self._pay(target, {"Code": acct}, wht, doc, f"{n} WHT"),
                            lambda: self._paid(target, wht, f"{n} WHT"),
                        )
                    )
            if advance > 0:
                ids.append(
                    "P"
                    + self.step(
                        b,
                        doc,
                        "advance",
                        lambda: self._prepay(b, doc, advance, src),
                        lambda: self._one("BankTransactions", {"where": f'Reference=="{n} ADVANCE"'}, "BankTransactionID"),
                    )
                )
            if not ids:
                raise SyncError(f"{n} settles nothing that can go to Xero")
            return ",".join(ids)
        if k == "expense":

            def make():
                who = self.contact(b, p) if p else self.contact(b, {"id": "expenses", "name": "Expenses (paid at once)"})
                line = {
                    "Description": doc.get("what"),
                    "Quantity": 1,
                    "UnitAmount": doc["amount"] / 100,
                    "AccountCode": self.account(b, f"expense:{doc.get('account') or '6090'}"),
                    "TaxType": self.tax_type(b, rate_of(doc["amount"], doc.get("tax"))),
                }
                bt = {
                    "Type": "SPEND",
                    "Contact": {"ContactID": who},
                    "Date": doc["date"],
                    "LineAmountTypes": "Exclusive",
                    "Reference": n,
                    "BankAccount": {"AccountID": self.account(b, "bank" if doc.get("paid_from") == "bank" else "cash")},
                    "LineItems": [line],
                }
                return self.call("PUT", "BankTransactions", {"BankTransactions": [bt]}, idem=True)["BankTransactions"][0]["BankTransactionID"]

            return self.step(
                b, doc, "made", make, lambda: self._one("BankTransactions", {"where": f'Reference=="{n}" AND Type=="SPEND"'}, "BankTransactionID")
            )
        raise SyncError(f"Xero: a {k} is not sent")

    def _pay(self, target, account, amount, doc, ref):
        body = {"Payments": [{"Invoice": {"InvoiceID": target}, "Account": account, "Date": doc["date"], "Amount": amount / 100, "Reference": ref}]}
        return self.call("PUT", "Payments", body, idem=True)["Payments"][0]["PaymentID"]

    def _paid(self, target, amount, ref):
        return self._one(
            "Payments",
            {"where": f'Reference=="{ref}"'},
            "PaymentID",
            lambda x: (x.get("Invoice") or {}).get("InvoiceID") == target and _cents(x.get("Amount")) == amount,
        )

    def _prepay(self, b, doc, amount, src):
        rec = doc["kind"] == "receipt"
        bt = {
            "Type": "RECEIVE-PREPAYMENT" if rec else "SPEND-PREPAYMENT",
            "Contact": {"ContactID": self.contact(b, doc["party"])},
            "Date": doc["date"],
            "LineAmountTypes": "NoTax",
            "Reference": f"{doc['number']} ADVANCE",
            "BankAccount": {"AccountID": self.account(b, src)},
            "LineItems": [
                {
                    "Description": f"Advance ({doc['number']})",
                    "Quantity": 1,
                    "UnitAmount": amount / 100,
                    "AccountCode": self.account(b, "sales" if rec else "purchases"),
                    "TaxType": "NONE",
                }
            ],
        }
        return self.call("PUT", "BankTransactions", {"BankTransactions": [bt]}, idem=True)["BankTransactions"][0]["BankTransactionID"]

    def read(self, b, doc, remote):
        k = doc["kind"]
        if k in ("receipt", "payment"):
            total = 0
            for pid in remote.split(","):
                if pid.startswith("P"):
                    total += _cents((self.call("GET", f"BankTransactions/{pid[1:]}").get("BankTransactions") or [{}])[0].get("Total"))
                else:
                    total += _cents((self.call("GET", f"Payments/{pid}").get("Payments") or [{}])[0].get("Amount"))
            return {"total": total}
        path = {"invoice": "Invoices", "bill": "Invoices", "quote": "Quotes", "credit_note": "CreditNotes", "expense": "BankTransactions"}[k]
        x = (self.call("GET", f"{path}/{remote}").get(path) or [{}])[0]
        notes = [f"its status there is {x.get('Status')}"] if x.get("Status") in ("DRAFT", "DELETED", "VOIDED") else []
        return {"total": _cents(x.get("Total")), "status": x.get("Status"), "notes": notes}

    def void(self, b, doc, remote):
        k = doc["kind"]
        if k in ("invoice", "bill"):
            self.call("POST", f"Invoices/{remote}", {"Invoices": [{"InvoiceID": remote, "Status": "VOIDED"}]})
        elif k == "quote":
            q = {"QuoteID": remote, "Contact": {"ContactID": self.contact(b, doc["party"])}, "Date": doc["date"], "Status": "DELETED"}
            self.call("POST", f"Quotes/{remote}", {"Quotes": [q]})
        elif k in ("receipt", "payment"):
            for pid in remote.split(","):
                if pid.startswith("P"):
                    self.call("POST", f"BankTransactions/{pid[1:]}", {"BankTransactions": [{"BankTransactionID": pid[1:], "Status": "DELETED"}]})
                else:
                    self.call("POST", f"Payments/{pid}", {"Status": "DELETED"})
        elif k == "expense":
            self.call("POST", f"BankTransactions/{remote}", {"BankTransactions": [{"BankTransactionID": remote, "Status": "DELETED"}]})
        else:
            raise SyncError(f"Xero: cancel {doc['number']} there by hand (its allocation to the invoice must be removed first)")
