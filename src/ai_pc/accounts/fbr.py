"""FBR Digital Invoicing (Sales Tax Rules, Chapter XIV): a sales tax registered business sends each sale invoice to FBR
as it is issued and prints FBR's invoice number and its QR code on it. This talks to PRAL's DI API (PRAL is the free
licensed integrator; DI API v1.12): an invoice is first VALIDATED (nothing is issued) and POSTED only after a yes;
FBR's number is kept with the invoice and printed with its QR code (version 2, 1 x 1 inch). After that FBR's invoice
can be changed or cancelled only in FBR's own system, within 72 hours.

Basic for now: sale invoices of goods at the standard rate (18%), with further tax for unregistered buyers. Credit
notes are not in FBR's API yet (v1.12 takes sale invoices and debit notes): those go in IRIS by hand. Services are
provincial sales tax (PRA, SRB, KPRA, BRA), not FBR's.
"""
import datetime as dt
import re
from decimal import Decimal

from ai_pc.accounts.money import mul
from ai_pc.accounts.systems import SyncError, remember, remembered
from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

GW = "https://gw.fbr.gov.pk"
PATHS = {"post": "/di_data/v1/di/postinvoicedata", "validate": "/di_data/v1/di/validateinvoicedata"}
PROVINCES = ("Punjab", "Sindh", "Khyber Pakhtunkhwa", "Balochistan", "Capital Territory", "Gilgit Baltistan", "Azad Jammu and Kashmir")
CITIES = {"Punjab": r"lahore|faisalabad|rawalpindi|multan|gujranwala|sialkot|sargodha|bahawalpur|sheikhupura|jhang|gujrat|sahiwal|okara|kasur",
          "Sindh": r"karachi|hyderabad|sukkur|larkana|nawabshah|mirpur khas|thatta", "Khyber Pakhtunkhwa": r"peshawar|mardan|abbottabad|swat|kohat|dera ismail|mansehra",
          "Balochistan": r"quetta|gwadar|turbat|khuzdar|chaman", "Capital Territory": r"islamabad", "Gilgit Baltistan": r"gilgit|skardu|hunza",
          "Azad Jammu and Kashmir": r"muzaffarabad|mirpur|kotli|bagh"}
UOM = {"pcs": "Numbers, pieces, units", "piece": "Numbers, pieces, units", "pieces": "Numbers, pieces, units", "units": "Numbers, pieces, units",
       "unit": "Numbers, pieces, units", "nos": "Numbers, pieces, units", "set": "Numbers, pieces, units", "kg": "KG", "kgs": "KG",
       "litre": "Liter", "litres": "Liter", "l": "Liter", "m": "Meter", "meter": "Meter", "metre": "Meter"}
APP = {
    "label": "FBR Digital Invoicing",
    "fields": [("token", "Your PRAL Digital Invoicing token", True), ("env?", "sandbox or production (Enter for sandbox)", False)],
    "steps": ["Log in to IRIS (iris.fbr.gov.pk) > Digital Invoicing > API Integration > 'Proceed with PRAL as Licensed Integrator' (free).",
              "Give the software's details and 1-3 FIXED public IP addresses of the computer that will send invoices; PRAL approves them in about 2 "
              "working hours. A home connection without a fixed IP cannot post directly: ask your internet provider for a static IP.",
              "Copy the sandbox token and run 'ai-pc accounts connect fbr'; post one valid invoice of each scenario FBR assigned you "
              "('post invoice 3 to FBR'); then FBR issues the production token (valid 5 years): connect again with env production.",
              "Put FBR's Digital Invoicing logo (IRIS gives it) at state/accounts/fbr_di_logo.png so it prints beside the QR code."],
    "notes": "Every sales tax registered business must issue FBR digital invoices; an invoice without FBR's number and QR code risks a "
             "Rs 500,000 penalty. Debit and credit notes must be electronic too (SRO 1666(I)/2026), but FBR's API takes credit notes later.",
}


def digits(s):
    return re.sub(r"\D", "", str(s or ""))


def reg_no(ntn=None, cnic=None):
    """A registration number as DI wants it: the 7-digit NTN (without its check digit) or the 13-digit CNIC."""
    c = digits(cnic)
    if len(c) == 13:
        return c
    n = digits(ntn)
    return n[:7] if len(n) in (7, 8) else (n if len(n) in (9, 13) else "")


ALIASES = {"kp": "Khyber Pakhtunkhwa", "kpk": "Khyber Pakhtunkhwa", "ict": "Capital Territory", "islamabad": "Capital Territory",
           "gb": "Gilgit Baltistan", "ajk": "Azad Jammu and Kashmir", "baluchistan": "Balochistan"}


def province_of(info):
    """The province FBR's list names, from what was said ('Punjab', 'KPK') or the city in the address."""
    p = str(info.get("province") or "").strip().lower()
    hit = next((prov for prov in PROVINCES if p == prov.lower()), None) or ALIASES.get(p)
    if hit:
        return hit
    for prov, rx in CITIES.items():
        if re.search(rf"\b(?:{rx})\b", str(info.get("address") or ""), re.I):
            return prov
    return None


def connect(values, transport=None, store=None):
    env = (values.get("env") or "sandbox").strip().lower()
    if env not in ("sandbox", "production"):
        raise SyncError("env must be sandbox or production")
    creds = {"token": values["token"].strip(), "env": env}
    System(creds, transport).provinces()  # the token works (and this PC's IP is allowed)
    (store or (lambda c: vault.put("fbr", c)))(creds)
    return {"who": "PRAL token accepted", "where": f"FBR Digital Invoicing ({env})"}


class System:
    name, label = "fbr", "FBR Digital Invoicing"

    def __init__(self, creds=None, transport=None):
        self.creds = (vault.get("fbr") or {}) if creds is None else creds
        self.transport = transport

    def ready(self):
        if not self.creds.get("token"):
            return False, "FBR Digital Invoicing is not connected: 'ai-pc accounts steps fbr' shows how (a PRAL token from IRIS)"
        return True, f"FBR Digital Invoicing ({self.creds.get('env', 'sandbox')})"

    def call(self, method, path, body=None, retries=3):
        api = Api(GW, headers={"Authorization": f"Bearer {self.creds.get('token', '')}"}, service="fbr", transport=self.transport, timeout=60)
        try:
            return api.request(method, path, json_body=body, retries=retries)
        except HubError as e:
            if e.status is None:
                raise SyncError(f"FBR could not be reached ({e})", "offline") from e
            if e.status == 401:
                raise SyncError("FBR refused the token (or this PC's IP address is not one PRAL approved): check it in IRIS and connect again", "auth") from e
            raise SyncError(f"FBR: {e}") from e

    def provinces(self):
        return self.call("GET", "/pdi/v1/provinces")

    # ---------------------------------------------------------------- the invoice as FBR wants it
    def payload(self, b, doc):
        """(the request, the problems that stop it going)."""
        c, p = b.company(), doc.get("party") or {}
        problems = []
        if doc["kind"] != "invoice":
            problems.append("FBR's API takes sale invoices (credit notes go in IRIS by hand for now)" if doc["kind"] == "credit_note" else
                            f"only sale invoices go to FBR, not a {doc['kind'].replace('_', ' ')}")
        if doc.get("status") == "void":
            problems.append(f"{doc['number']} is cancelled")
        if not c.get("strn"):
            problems.append("your business has no STRN: only sales tax registered businesses issue FBR invoices")
        seller = reg_no(c.get("ntn"), c.get("cnic"))
        if not seller:
            problems.append("your NTN (7 digits) or CNIC (13 digits): say 'my NTN is ...'")
        sprov = province_of(c)
        if not sprov:
            problems.append("your province: say 'my address is ..., Lahore' or 'we are in Punjab'")
        bprov = province_of(p) or sprov
        registered = bool(p.get("strn"))
        buyer = reg_no(p.get("ntn"), p.get("cnic"))
        if registered and not buyer:
            problems.append(f"{p.get('name')}'s NTN or CNIC (they are registered): say 'add customer {p.get('name')} NTN ...'")
        items = []
        for ln in doc.get("lines") or []:
            if ln.get("kind") == "service":
                problems.append(f"{ln['description']} is a service: services are provincial sales tax (PRA, SRB...), not FBR's; invoice goods and services separately")
                continue
            hs = ln.get("hs_code") or (b.item_by_id(ln["item_id"]) or {}).get("hs_code") if ln.get("item_id") else ln.get("hs_code")
            if not hs:
                problems.append(f"the HS code of {ln['description']}: say 'item {ln['description']} hs code 8528.7200'")
            rate = Decimal(ln.get("tax_rate") or 0).normalize()
            if rate != 18:
                problems.append(f"{ln['description']} is at {rate}%: only standard-rate (18%) goods go from here for now; reduced, zero-rated and exempt "
                                "goods need their SRO (enter them in IRIS)")
            items.append({"hsCode": hs or "", "productDescription": ln["description"], "rate": f"{rate}%", "uoM": UOM.get((ln.get("unit") or "pcs").lower(),
                                                                                                                         "Numbers, pieces, units"),
                          "quantity": float(Decimal(ln["qty"]).quantize(Decimal("0.0001"))), "totalValues": (ln["amount"] + ln["tax"] + (ln.get("further_tax") or 0)) / 100,
                          "valueSalesExcludingST": ln["amount"] / 100, "fixedNotifiedValueOrRetailPrice": 0.0, "salesTaxApplicable": ln["tax"] / 100,
                          "salesTaxWithheldAtSource": 0.0, "extraTax": 0.0, "furtherTax": (ln.get("further_tax") or 0) / 100, "sroScheduleNo": "",
                          "fedPayable": 0.0, "discount": (mul(ln["rate"], ln["qty"]) - ln["amount"]) / 100, "saleType": "Goods at standard rate (default)",
                          "sroItemSerialNo": ""})
        body = {"invoiceType": "Sale Invoice", "invoiceDate": doc["date"], "sellerNTNCNIC": seller, "sellerBusinessName": c.get("name") or "",
                "sellerProvince": sprov or "", "sellerAddress": c.get("address") or "", "buyerNTNCNIC": buyer, "buyerBusinessName": p.get("name") or "",
                "buyerProvince": bprov or "", "buyerAddress": p.get("address") or "", "buyerRegistrationType": "Registered" if registered else "Unregistered",
                "invoiceRefNo": "", "items": items}
        if self.creds.get("env", "sandbox") == "sandbox":
            body["scenarioId"] = "SN001" if registered else "SN002"
        return body, problems

    def _path(self, what):
        return PATHS[what] + ("_sb" if self.creds.get("env", "sandbox") == "sandbox" else "")

    @staticmethod
    def _answer(r):
        """(valid, FBR's invoice number, the errors): every line must be valid too, whatever the header says."""
        v = r.get("validationResponse") or {}
        lines = v.get("invoiceStatuses") or []
        ok = v.get("statusCode") == "00" and str(v.get("status", "")).lower() == "valid" and all(str(x.get("status", "")).lower() == "valid" for x in lines)
        errors = ([f"{v.get('errorCode')}: {v.get('error')}"] if v.get("error") else []) + \
            [f"line {x.get('itemSNo')}: {x.get('errorCode')} {x.get('error')}" for x in lines if str(x.get("status", "")).lower() != "valid"]
        return ok, r.get("invoiceNumber"), errors

    def validate(self, b, doc):
        body, problems = self.payload(b, doc)
        if problems:
            return {"ok": False, "problems": problems}
        ok, _, errors = self._answer(self.call("POST", self._path("validate"), body))
        return {"ok": ok, "problems": errors}

    def post(self, b, doc, again=False):
        """FBR's number for the invoice. Never sent blindly twice: FBR has no way to look an invoice up by our number, so a
        post whose answer was lost waits for the person to check IRIS (and say the number, or 'again')."""
        done = (doc.get("links") or {}).get("fbr")
        if done:
            return done
        if remembered(b, "fbr", "attempt", doc["id"]) and not again:
            raise SyncError(f"FBR did not answer the last time {doc['number']} was posted: look for it in IRIS (Digital Invoicing > invoices). If it is "
                            f"there, say 'FBR number of {doc['number']} is ...'; if not, say 'post {doc['number']} to FBR again'.")
        body, problems = self.payload(b, doc)
        if problems:
            raise SyncError("; ".join(problems))
        remember(b, "fbr", "attempt", doc["id"], dt.datetime.now().isoformat(timespec="seconds"))
        try:
            r = self.call("POST", self._path("post"), body, retries=0)
        except SyncError as e:
            if e.kind == "offline":
                raise SyncError(f"FBR did not answer, so it may or may not have taken {doc['number']}: look for it in IRIS before posting again "
                                f"(say 'FBR number of {doc['number']} is ...' or 'post {doc['number']} to FBR again')", "offline") from e
            raise
        ok, number, errors = self._answer(r)
        if not ok or not number:
            b.cx.execute("DELETE FROM maps WHERE system='fbr' AND kind='attempt' AND local=?", (str(doc["id"]),))
            raise SyncError("FBR refused it: " + ("; ".join(errors) or "no invoice number came back"))
        b.link(doc["id"], "fbr", number)
        b._audit("fbr", f"{doc['number']} -> {number}")
        return number

    @staticmethod
    def record(b, doc, number):
        """FBR's number said by the person (found in IRIS after a lost answer)."""
        number = number.strip().upper()
        if not re.fullmatch(r"\d{7,13}DI\d{10,16}", number):
            raise SyncError(f"'{number}' does not look like an FBR invoice number (NTN or CNIC, 'DI', then digits)")
        b.link(doc["id"], "fbr", number)
        b._audit("fbr", f"{doc['number']} -> {number} (said by the person)")
        return number
