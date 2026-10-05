"""TallyPrime through its XML gateway on this PC (http://127.0.0.1:9000; TallyPrime 1.x to 7.1). Nothing to sign in to:
TallyPrime only has to be open with the company loaded and its gateway on (F1 > Settings > Connectivity > Client/Server
configuration: 'TallyPrime is acting as' Both, port 9000).

Every request names the company (SVCURRENTCOMPANY), goes as UTF-16, one at a time (the gateway does one thing at a
time and keeps working after a client gives up). Masters are made only when missing (a Create on an existing ledger
would silently alter the person's own): customers under Sundry Debtors and suppliers under Sundry Creditors with
bill-by-bill on; the person's own Sales, Purchase, bank and cash ledgers are used when they have them; tax, income tax
and expense ledgers are made in their groups; stock items with their unit. Each voucher carries a REMOTEID made from
our number, so sending it again updates it instead of making a second one. A sale or purchase of stock is an item
invoice (Invoice Voucher View); everything else is an accounting voucher. A debit is ISDEEMEDPOSITIVE Yes with a
negative amount, and a voucher is sent only if it sums to zero. A write counts only when Tally's own counters say so
(created or altered, no errors, no exceptions, no LINEERROR); then the voucher is read back from the Day Book (found by
our number in its narration) and its total compared. A document cancelled here is cancelled in Tally (ACTION Cancel
keeps the voucher and its number, as here).
"""
import datetime as dt
import re
import urllib.error
import xml.etree.ElementTree as ET
from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

from ...hub import vault
from ...hub.http import TRANSPORT
from . import EXPENSE_KEYS, Connector, SyncError, bill_account, once, rate_of, remember, remembered, splits

APP = {
    "label": "TallyPrime",
    "fields": [("company", "Your company's name exactly as TallyPrime shows it", False), ("port?", "Gateway port (Enter for 9000)", False)],
    "steps": ["Open TallyPrime on this PC and open (load) your company.",
              "Turn its gateway on: F1 (Help) > Settings > Connectivity > Client/Server configuration (TallyPrime 7: Alt+Z Exchange > Configure > "
              "Data Synchronisation): 'TallyPrime is acting as' = Both, Port = 9000; save and restart TallyPrime.",
              "Optional: set the Sales, Purchase, Credit Note, Receipt and Payment voucher types' numbering to Manual, so Tally keeps our numbers "
              "(Alt+G > Alter > Voucher Type).",
              "Run 'accounts.py connect tally' and type the company's name. No key is needed; keep port 9000 closed to other computers in Windows Firewall."],
    "notes": "TallyPrime has no Pakistan tax module: sales tax goes to 'Output Sales Tax 18%' and 'Input Sales Tax 18%' ledgers under Duties & Taxes. "
             "Without a licence (Educational mode) Tally accepts only dates on the 1st, 2nd and 31st of a month.",
}
UNITS = {"pcs": ("Nos", "Numbers", 0), "piece": ("Nos", "Numbers", 0), "pieces": ("Nos", "Numbers", 0), "unit": ("Nos", "Numbers", 0),
         "units": ("Nos", "Numbers", 0), "nos": ("Nos", "Numbers", 0), "kg": ("Kg", "Kilograms", 3), "g": ("g", "Grams", 0),
         "m": ("m", "Metres", 2), "ft": ("ft", "Feet", 2), "box": ("Box", "Boxes", 0), "boxes": ("Box", "Boxes", 0), "set": ("Set", "Sets", 0),
         "job": ("Job", "Jobs", 0), "hour": ("Hrs", "Hours", 2), "hours": ("Hrs", "Hours", 2), "l": ("Ltr", "Litres", 2), "litre": ("Ltr", "Litres", 2)}
# ledgers made when missing: role -> (name, group)
LEDGERS = {"sales": ("Sales", "Sales Accounts"), "services": ("Service Income", "Sales Accounts"), "purchases": ("Purchase", "Purchase Accounts"),
           "further_tax": ("Further Tax Payable", "Duties & Taxes"), "wht": ("Income Tax Deducted by Customers", "Loans & Advances (Asset)"),
           "wht_payable": ("Income Tax Withheld from Suppliers", "Duties & Taxes"), "bank": ("Bank Account", "Bank Accounts"), "cash": ("Cash", "Cash-in-Hand")}
OWN = {"sales": "Sales Accounts", "purchases": "Purchase Accounts", "bank": "Bank Accounts", "cash": "Cash-in-Hand"}  # their own ledger, by group
VTYPE = {"invoice": "Sales", "bill": "Purchase", "credit_note": "Credit Note", "receipt": "Receipt", "payment": "Payment", "expense": "Payment"}
ENTRY_TAGS = ("LEDGERENTRIES.LIST", "ALLLEDGERENTRIES.LIST", "ALLINVENTORYENTRIES.LIST")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _amt(paisa):
    return f"{Decimal(paisa) / 100:.2f}"


def _day(iso):
    return iso.replace("-", "")


def _tag(name, value):
    return f"<{name}>{escape(str(value))}</{name}>"


def _clean(text):
    """Tally's replies carry control characters (&#4; before group names) that XML parsers refuse."""
    text = re.sub(r"&#(\d+);", lambda m: "" if int(m.group(1)) < 32 and int(m.group(1)) not in (9, 10, 13) else m.group(0), text)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def _decode(content):
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return content.decode("utf-16")
    if len(content) > 1 and content[1:2] == b"\x00":
        return content.decode("utf-16-le")
    return content.decode("utf-8", "replace")


def _names(root, tag):
    return [(x.get("NAME") or x.findtext("NAME") or "").strip() for x in root.iter(tag)]


def connect(values, transport=None, store=None):
    creds = {"company": values["company"].strip(), "port": int(values.get("port") or 9000), "host": values.get("host") or "127.0.0.1"}
    loaded = System(dict(creds), transport).companies()
    hit = next((c for c in loaded if c.lower() == creds["company"].lower()), None)
    if not hit:
        raise SyncError(f"'{creds['company']}' is not open in TallyPrime" + (f" (open: {', '.join(loaded)})" if loaded else "") +
                        ": open it there (F3, Select Company) and connect again")
    creds["company"] = hit
    (store or (lambda c: vault.put("tally", c)))(creds)
    return {"who": hit, "where": f"TallyPrime on this PC, port {creds['port']}"}


class System(Connector):
    name, label = "tally", "TallyPrime"
    kinds = ("invoice", "bill", "credit_note", "receipt", "payment", "expense")

    def __init__(self, creds=None, transport=None):
        super().__init__()
        self.creds = (vault.get("tally") or {}) if creds is None else creds
        self.transport = transport
        self._ledgers = None

    @property
    def url(self):
        return f"http://{self.creds.get('host') or '127.0.0.1'}:{self.creds.get('port') or 9000}/"

    def ready(self):
        if not self.creds.get("company"):
            return False, "TallyPrime is not connected: 'accounts.py steps tally' shows how (no key needed)"
        return True, f"TallyPrime ({self.creds['company']})"

    # ---------------------------------------------------------------- the gateway
    def post(self, xml):
        self.calls += 1
        try:
            status, _, content = (self.transport or TRANSPORT).send("POST", self.url, {"Content-Type": "text/xml; charset=utf-16"}, xml.encode("utf-16"), 180)
        except (OSError, urllib.error.URLError) as e:
            raise SyncError(f"TallyPrime is not answering on port {self.creds.get('port') or 9000} ({type(e).__name__}): open TallyPrime with "
                            "your company and turn its gateway on (F1 > Settings > Connectivity); if a message is showing in Tally, close it", "offline") from e
        text = _clean(_decode(content))
        if status >= 400 or "Unknown Request" in text:
            raise SyncError(f"TallyPrime could not read the request ({status}): {text[:200]}")
        try:
            return ET.fromstring(text)
        except ET.ParseError as e:
            raise SyncError(f"TallyPrime answered something that is not XML: {text[:200]}") from e

    def _company(self):
        return f"<SVCURRENTCOMPANY>{escape(self.creds['company'])}</SVCURRENTCOMPANY>" if self.creds.get("company") else ""

    def _import(self, body, what):
        root = self.post(f"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Import</TALLYREQUEST><TYPE>Data</TYPE><ID>{what}</ID></HEADER>"
                         f"<BODY><DESC><STATICVARIABLES>{self._company()}</STATICVARIABLES></DESC><DATA><TALLYMESSAGE>{body}</TALLYMESSAGE></DATA>"
                         "</BODY></ENVELOPE>")
        got = {k: int((root.findtext(f".//{k}") or "0").strip() or 0) for k in ("CREATED", "ALTERED", "DELETED", "CANCELLED", "LASTVCHID", "ERRORS",
                                                                                   "EXCEPTIONS", "IGNORED", "COMBINED")}
        got["LINEERROR"] = (root.findtext(".//LINEERROR") or "").strip()
        if "SVCurrentCompany" in got["LINEERROR"]:
            raise SyncError(f"'{self.creds['company']}' is not open in TallyPrime: open it there and sync again", "offline")
        if got["ERRORS"] or got["EXCEPTIONS"] or got["LINEERROR"] or not (got["CREATED"] or got["ALTERED"] or got["CANCELLED"] or got["DELETED"]):
            raise SyncError("TallyPrime refused it: " + (got["LINEERROR"] or f"{got['ERRORS']} error(s), {got['EXCEPTIONS']} exception(s) "
                                                                             "(Tally.imp in TallyPrime's folder says why)"))
        return got

    def _export(self, kind, ident, statics="", tdl="", company=True):
        return self.post(f"<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>{kind}</TYPE><ID>{ident}</ID></HEADER>"
                         f"<BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>{self._company() if company else ''}{statics}"
                         f"</STATICVARIABLES>{tdl}</DESC></BODY></ENVELOPE>")

    def _collection(self, name, type_, fetch, company=True):
        return self._export("Collection", name, tdl=f'<TDL><TDLMESSAGE><COLLECTION NAME="{name}" ISMODIFY="No"><TYPE>{type_}</TYPE>'
                                                    f"<FETCH>{fetch}</FETCH></COLLECTION></TDLMESSAGE></TDL>", company=company)

    def companies(self):
        """The companies open in TallyPrime (asked without naming one: a company that is not open would answer nothing)."""
        return _names(self._collection("AIPCCompanies", "Company", "Name", company=False), "COMPANY")

    # ---------------------------------------------------------------- masters, made only when missing
    def ledgers(self, fresh=False):
        if self._ledgers is None or fresh:
            root = self._collection("AIPCLedgers", "Ledger", "Name, Parent")
            self._ledgers = {(x.get("NAME") or x.findtext("NAME") or "").strip(): (x.findtext("PARENT") or "").strip() for x in root.iter("LEDGER")}
        return self._ledgers

    def _make_ledger(self, name, group, extra=""):
        hit = next((n for n in self.ledgers() if n.lower() == name.lower()), None)
        if hit:
            return hit
        self._import(f'<LEDGER NAME={quoteattr(name)} ACTION="Create">{_tag("NAME", name)}{_tag("PARENT", group)}{extra}</LEDGER>', "All Masters")
        self._ledgers[name] = group
        return name

    def party(self, b, p, kind):
        def make():
            hit = next((n for n in self.ledgers() if n.lower() == p["name"].lower()), None)
            if hit:  # their own ledger (it may sit in either group when they both buy and sell)
                return hit
            extra = "<ISBILLWISEON>Yes</ISBILLWISEON>"
            if p.get("address"):
                extra += f'<ADDRESS.LIST TYPE="String">{_tag("ADDRESS", p["address"])}</ADDRESS.LIST><COUNTRYNAME>Pakistan</COUNTRYNAME>'
            return self._make_ledger(p["name"], "Sundry Creditors" if kind == "supplier" else "Sundry Debtors", extra)
        return once(b, self.name, "party", p["id"], make)

    def ledger(self, b, role):
        def make():
            if role in OWN:
                ours = {v[0].lower() for v in LEDGERS.values()} - {LEDGERS[role][0].lower()}
                own = [n for n, g in self.ledgers().items() if g.lower() == OWN[role].lower() and n.lower() not in ours]
                if own:
                    return sorted(own, key=lambda n: (LEDGERS[role][0].lower() not in n.lower(), n))[0]
            if role.startswith("expense:"):
                code = role.split(":", 1)[1]
                rx = EXPENSE_KEYS.get(code)
                own = [n for n, g in self.ledgers().items() if g.lower() == "indirect expenses" and rx and re.search(rx, n, re.I)]
                return own[0] if own else self._make_ledger(b.account(code)["name"], "Indirect Expenses")
            if role.startswith(("output:", "input:")):
                side, rate = role.split(":")
                return self._make_ledger(f"{side.title()} Sales Tax {rate}%", "Duties & Taxes")
            name, group = LEDGERS[role]
            return self._make_ledger(name, group)
        return once(b, self.name, "ledger", role, make)

    def unit(self, b, unit):
        name, formal, places = UNITS.get((unit or "pcs").lower(), ((unit or "Nos").title()[:10], (unit or "Numbers").title(), 2))

        def make():
            hit = next((u for u in _names(self._collection("AIPCUnits", "Unit", "Name"), "UNIT") if u.lower() == name.lower()), None)
            if hit:
                return hit
            self._import(f'<UNIT NAME={quoteattr(name)} ACTION="Create">{_tag("NAME", name)}<ISSIMPLEUNIT>Yes</ISSIMPLEUNIT>'
                         f"{_tag('ORIGINALNAME', formal)}<DECIMALPLACES>{places}</DECIMALPLACES></UNIT>", "All Masters")
            return name
        return once(b, self.name, "unit", name, make)

    def stock_item(self, b, ln):
        unit = self.unit(b, ln.get("unit"))

        def make():
            have = _names(self._collection("AIPCItems", "StockItem", "Name, BaseUnits"), "STOCKITEM")
            hit = next((x for x in have if x.lower() == ln["description"].lower()), None)
            if hit:
                return hit
            self._import(f'<STOCKITEM NAME={quoteattr(ln["description"])} ACTION="Create">{_tag("NAME", ln["description"])}{_tag("BASEUNITS", unit)}'
                         "</STOCKITEM>", "All Masters")
            return ln["description"]
        return once(b, self.name, "item", ln["item_id"], make), unit

    # ---------------------------------------------------------------- vouchers
    @staticmethod
    def entry(ledger, paisa, tag, party=False, bills=()):
        """A ledger line: paisa > 0 is a debit (ISDEEMEDPOSITIVE Yes, negative amount), < 0 a credit (No, positive). A bill
        allocation takes the sign of its line: bills = [(name, 'New Ref'|'Agst Ref'|'Advance', paisa, extra xml)]."""
        x = f"<{tag}>{_tag('LEDGERNAME', ledger)}<ISDEEMEDPOSITIVE>{'Yes' if paisa > 0 else 'No'}</ISDEEMEDPOSITIVE>"
        x += ("<ISPARTYLEDGER>Yes</ISPARTYLEDGER>" if party else "") + f"<AMOUNT>{_amt(-paisa)}</AMOUNT>"
        for name, kind, amount, extra in bills:
            x += f"<BILLALLOCATIONS.LIST>{_tag('NAME', name)}{_tag('BILLTYPE', kind)}{extra}<AMOUNT>{_amt(-amount)}</AMOUNT></BILLALLOCATIONS.LIST>"
        return x + f"</{tag}>"

    def stock(self, b, ln, ledger, paisa):
        """A stock line: paisa > 0 leaves (sold: No, positive), < 0 comes in (bought or returned: Yes, negative)."""
        item, unit = self.stock_item(b, ln)
        q = escape(f"{Decimal(ln['qty']).normalize():f} {unit}")
        flag = "No" if paisa > 0 else "Yes"
        disc = f"<DISCOUNT>{str(ln['discount']).rstrip('%').strip()}</DISCOUNT>" if str(ln.get("discount") or "").endswith("%") else ""
        return (f"<ALLINVENTORYENTRIES.LIST>{_tag('STOCKITEMNAME', item)}<ISDEEMEDPOSITIVE>{flag}</ISDEEMEDPOSITIVE>"
                f"<RATE>{_amt(ln['rate'])}/{escape(unit)}</RATE>{disc}<ACTUALQTY>{q}</ACTUALQTY><BILLEDQTY>{q}</BILLEDQTY><AMOUNT>{_amt(paisa)}</AMOUNT>"
                f"<BATCHALLOCATIONS.LIST><GODOWNNAME>Main Location</GODOWNNAME><BATCHNAME>Primary Batch</BATCHNAME><ACTUALQTY>{q}</ACTUALQTY>"
                f"<BILLEDQTY>{q}</BILLEDQTY><AMOUNT>{_amt(paisa)}</AMOUNT></BATCHALLOCATIONS.LIST><ACCOUNTINGALLOCATIONS.LIST>{_tag('LEDGERNAME', ledger)}"
                f"<ISDEEMEDPOSITIVE>{flag}</ISDEEMEDPOSITIVE><AMOUNT>{_amt(paisa)}</AMOUNT></ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>")

    @staticmethod
    def bill_name(doc):
        """The bill-by-bill reference a document is known by in Tally."""
        return (doc.get("ref") or doc["number"]) if doc["kind"] == "bill" else doc["number"]

    def _goods(self, b, doc, party, bills):
        """An invoice (sign +1: the customer owes, sales and tax are credited), a bill or a return (sign -1: the other way)."""
        sign = 1 if doc["kind"] == "invoice" else -1
        purchase = doc["kind"] == "bill"
        stocked = any(ln.get("stock") and ln.get("item_id") for ln in doc["lines"])
        tag = "LEDGERENTRIES.LIST" if stocked else "ALLLEDGERENTRIES.LIST"
        led, inv = {}, []
        for ln in doc["lines"]:
            code = bill_account(b, ln) if purchase else None
            ledger = self.ledger(b, ("purchases" if code == "5000" else f"expense:{code}") if purchase else
                                 ("services" if ln.get("kind") == "service" else "sales"))
            if ln.get("stock") and ln.get("item_id"):
                inv.append(self.stock(b, ln, ledger, sign * ln["amount"]))
            else:
                led[ledger] = led.get(ledger, 0) + ln["amount"]
            if ln.get("tax"):
                t = self.ledger(b, f"{'input' if purchase else 'output'}:{Decimal(ln['tax_rate']).normalize()}")
                led[t] = led.get(t, 0) + ln["tax"]
            if ln.get("further_tax"):
                f = self.ledger(b, "further_tax")
                led[f] = led.get(f, 0) + ln["further_tax"]
        lines = [self.entry(party, sign * doc["total"], tag, party=True, bills=bills)] + [self.entry(n, -sign * a, tag) for n, a in led.items()]
        return lines + inv, "Invoice Voucher View" if stocked else "Accounting Voucher View"

    def _voucher(self, doc, party, view, body, narration):
        n = doc["number"]
        vtype = VTYPE[doc["kind"]]
        rid = "aipc:" + self.creds["company"] + ":" + doc["kind"] + ":" + n  # the same voucher every time it is sent
        x = (f'<VOUCHER REMOTEID={quoteattr(rid)} VCHTYPE={quoteattr(vtype)} ACTION="Create" '
             f"OBJVIEW={quoteattr(view)}><DATE>{_day(doc['date'])}</DATE><EFFECTIVEDATE>{_day(doc['date'])}</EFFECTIVEDATE>{_tag('VOUCHERTYPENAME', vtype)}"
             f"{_tag('VOUCHERNUMBER', n)}{_tag('REFERENCE', doc.get('ref') if doc['kind'] == 'bill' and doc.get('ref') else n)}"
             f"{_tag('NARRATION', f'{narration} (AI PC {n})')}")
        if party:
            x += _tag("PARTYLEDGERNAME", party)
        x += _tag("PERSISTEDVIEW", view) + ("<ISINVOICE>Yes</ISINVOICE>" if view == "Invoice Voucher View" else "")
        return x + "".join(body) + "</VOUCHER>"

    def create(self, b, doc):
        k, p = doc["kind"], doc.get("party")
        party = self.party(b, p, "supplier" if k in ("bill", "payment") else "customer") if p and k != "expense" else None
        if k in ("invoice", "bill", "credit_note"):
            if k == "invoice":
                days = (dt.date.fromisoformat(doc["due"]) - dt.date.fromisoformat(doc["date"])).days if doc.get("due") else 0
                bills = [(doc["number"], "New Ref", doc["total"], f"<BILLCREDITPERIOD>{days} Days</BILLCREDITPERIOD>")]
            elif k == "bill":
                bills = [(self.bill_name(doc), "New Ref", -doc["total"], "")]
            else:
                bills = [(doc["invoice"], "Agst Ref", -doc["total"], "")]
            body, view = self._goods(b, doc, party, bills)
            what = {"invoice": "Sale", "bill": f"Purchase, their bill {doc.get('ref') or '-'}", "credit_note": f"Goods returned against {doc.get('invoice')}"}[k]
            xml = self._voucher(doc, party, view, body, what)
        elif k in ("receipt", "payment"):
            rec = k == "receipt"
            parts, advance = splits(b, doc)
            cash = sum(c for _, c, _ in parts) + max(advance, 0)
            wht = sum(w for _, _, w in parts)
            s = -1 if rec else 1  # the party is credited by money received, debited by money paid
            bills = [(self.bill_name(b.doc(i)), "Agst Ref", s * (c + w), "") for i, c, w in parts]
            if advance > 0:
                bills.append((doc["number"], "Advance", s * advance, ""))
            src = self.ledger(b, "bank" if doc.get("bank", True) else "cash")
            tag = "ALLLEDGERENTRIES.LIST"
            lines = [self.entry(party, s * doc["total"], tag, party=True, bills=bills), self.entry(src, -s * cash, tag)]
            if wht:
                lines.append(self.entry(self.ledger(b, "wht" if rec else "wht_payable"), -s * wht, tag))
            xml = self._voucher(doc, party, "Accounting Voucher View", lines, "Received" if rec else "Paid")
        elif k == "expense":
            tag = "ALLLEDGERENTRIES.LIST"
            lines = [self.entry(self.ledger(b, f"expense:{doc.get('account') or '6090'}"), doc["amount"], tag)]
            if doc.get("tax"):
                lines.append(self.entry(self.ledger(b, f"input:{rate_of(doc['amount'], doc['tax'])}"), doc["tax"], tag))
            lines.append(self.entry(self.ledger(b, "bank" if doc.get("paid_from") == "bank" else "cash"), -doc["total"], tag))
            xml = self._voucher(doc, None, "Accounting Voucher View", lines, doc.get("what") or "Expense")
        else:
            raise SyncError(f"TallyPrime: a {k} is not sent")
        total = sum(Decimal(e.findtext("AMOUNT")) for e in ET.fromstring(xml) if e.tag in ENTRY_TAGS)
        if total != 0:  # never send a voucher that does not balance
            raise SyncError(f"TallyPrime: {doc['number']} would not balance ({total}); nothing sent")
        got = self._import(xml, "Vouchers")  # the same REMOTEID again updates it, so a resend is safe
        return str(got["LASTVCHID"] or doc["number"])

    # ---------------------------------------------------------------- reading back, cancelling
    def _find(self, doc):
        root = self._export("Data", "Day Book", statics=f'<SVFROMDATE TYPE="Date">{_day(doc["date"])}</SVFROMDATE>'
                                                       f'<SVTODATE TYPE="Date">{_day(doc["date"])}</SVTODATE><EXPLODEFLAG>Yes</EXPLODEFLAG>')
        for v in root.iter("VOUCHER"):
            if f"(AI PC {doc['number']})" in (v.findtext("NARRATION") or "") and (v.findtext("ISCANCELLED") or "No").strip() != "Yes":
                return v
        return None

    def read(self, b, doc, remote):
        v = self._find(doc)
        if v is None:
            return {}
        vch = (v.findtext("VOUCHERNUMBER") or "").strip()
        remember(b, self.name, "vchno", doc["id"], vch)
        entries = [e for e in v if e.tag in ENTRY_TAGS[:2]]
        party = [e for e in entries if (e.findtext("ISPARTYLEDGER") or "").strip() == "Yes"]
        amounts = [Decimal((e.findtext("AMOUNT") or "0").strip() or 0) for e in (party or entries)]
        total = abs(sum(amounts)) if party else sum(-a for a in amounts if a < 0)
        notes = [] if vch == doc["number"] else [f"Tally numbered it {vch} (its numbering is automatic; our number is in the narration)"]
        return {"total": int(total * 100), "notes": notes}

    def void(self, b, doc, remote):
        vch = remembered(b, self.name, "vchno", doc["id"]) or doc["number"]
        d = dt.date.fromisoformat(doc["date"])
        day = f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"  # Tally's own date form here, in English whatever the PC's language
        note = f"Cancelled (AI PC {doc['number']})"
        self._import(f'<VOUCHER DATE="{day}" TAGNAME="Voucher Number" TAGVALUE={quoteattr(vch)} VCHTYPE={quoteattr(VTYPE[doc["kind"]])} '
                     f'ACTION="Cancel">{_tag("NARRATION", note)}</VOUCHER>', "Vouchers")
