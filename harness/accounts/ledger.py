"""The books: double-entry accounting in SQLite (state/accounts/books.db), the way accountants keep them.

  - money in whole paisa; every journal entry must balance (debits = credits) or nothing is saved
  - documents are numbered without gaps per kind and fiscal year (Pakistan: July to June), e.g. INV/26-27/0001
  - a posted document never changes: a mistake is corrected by a credit note, or the document is voided by a reversing
    entry (its number stays, marked void), so the audit trail is complete
  - stock at weighted-average cost; selling stock books its cost (COGS) at the average of that moment
  - sales tax per line (rate on the value excluding tax, rounded to the paisa); further tax on supplies to unregistered
    buyers when the business sets its rate; income tax a customer withholds is recorded when it pays

  b = Books()            b.setup(name=..., ntn=..., strn=...)          b.party("Ali Traders", kind="customer", ...)
  b.item("LED TV 55", rate="85,000", tax="18", stock=True)          d = b.invoice("Ali Traders", lines, due_days=15)
  b.receipt("Ali Traders", "100,000", bank=True)    b.bill(...)    b.expense(...)    b.credit_note(...)    b.void(doc)
  reports.py reads the postings: trial balance, profit and loss, balance sheet, ageing, statements, stock, sales tax.
"""
import datetime as dt
import json
import re
import sqlite3
import threading
from pathlib import Path

from ..config import STATE
from .money import MoneyError, mul, pct, to_paisa

DB = STATE / "accounts" / "books.db"

CHART = [  # code, name, type, role
    ("1000", "Cash in Hand", "asset", "cash"), ("1010", "Bank Account", "asset", "bank"), ("1100", "Accounts Receivable", "asset", "receivable"),
    ("1200", "Stock in Hand", "asset", "inventory"), ("1300", "Input Sales Tax", "asset", "input_tax"),
    ("1310", "Income Tax Deducted by Customers", "asset", "wht_receivable"),
    ("2000", "Accounts Payable", "liability", "payable"), ("2100", "Output Sales Tax", "liability", "output_tax"),
    ("2110", "Further Tax Payable", "liability", "further_tax"), ("2200", "Income Tax Withheld from Suppliers", "liability", "wht_payable"),
    ("3000", "Owner's Capital", "equity", "capital"), ("3100", "Owner's Drawings", "equity", "drawings"), ("3200", "Retained Earnings", "equity", "retained"),
    ("3900", "Opening Balance Equity", "equity", "opening"),
    ("4000", "Sales", "income", "sales"), ("4100", "Service Income", "income", "service_income"), ("4900", "Other Income", "income", "other_income"),
    ("5000", "Cost of Goods Sold", "expense", "cogs"),
    ("6000", "Rent", "expense", None), ("6010", "Salaries and Wages", "expense", None), ("6020", "Electricity and Utilities", "expense", None),
    ("6030", "Internet and Phone", "expense", None), ("6040", "Transport and Fuel", "expense", None), ("6050", "Repairs and Maintenance", "expense", None),
    ("6060", "Marketing and Advertising", "expense", None), ("6070", "Bank Charges", "expense", "bank_charges"), ("6080", "Office Supplies", "expense", None),
    ("6090", "General Expenses", "expense", "general"), ("6100", "Discount Allowed", "expense", "discount"),
]
EXPENSE_WORDS = {"6000": r"rent", "6010": r"salar|wage|staff|payroll", "6020": r"electric|wapda|lesco|k-?electric|gas|sui|water|utilit",
                 "6030": r"internet|phone|mobile|ptcl|broadband|jazz|zong|telenor|ufone", "6040": r"transport|fuel|petrol|diesel|freight|courier|travel|rickshaw|taxi",
                 "6050": r"repair|maintenance|service charge", "6060": r"marketing|advert|ads|facebook ads|promotion|printing|banner",
                 "6070": r"bank charge|bank fee", "6080": r"stationery|office suppl|paper|printer"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS company (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS accounts (code TEXT PRIMARY KEY, name TEXT, type TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS parties (id INTEGER PRIMARY KEY, kind TEXT, name TEXT UNIQUE COLLATE NOCASE, body TEXT);
CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE, body TEXT);
CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, kind TEXT, number TEXT, date TEXT, due TEXT, party_id INTEGER, status TEXT,
                                      total INTEGER, body TEXT, created TEXT, UNIQUE(kind, number));
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, date TEXT, doc_id INTEGER, memo TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS postings (entry_id INTEGER, account TEXT, party_id INTEGER, debit INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0,
                                     CHECK (debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0)));
CREATE INDEX IF NOT EXISTS postings_acct ON postings(account);
CREATE INDEX IF NOT EXISTS postings_party ON postings(party_id);
CREATE TABLE IF NOT EXISTS allocations (pay_id INTEGER, doc_id INTEGER, amount INTEGER);
CREATE TABLE IF NOT EXISTS stock (item_id INTEGER, date TEXT, qty TEXT, cost INTEGER, doc_id INTEGER);
CREATE TABLE IF NOT EXISTS sequences (kind TEXT, fy TEXT, n INTEGER, PRIMARY KEY (kind, fy));
CREATE TABLE IF NOT EXISTS links (doc_id INTEGER, system TEXT, remote TEXT, at TEXT, PRIMARY KEY (doc_id, system));
CREATE TABLE IF NOT EXISTS audit (ts TEXT, what TEXT, detail TEXT);
"""
PREFIX = {"invoice": "INV", "quote": "QUO", "bill": "BILL", "receipt": "RCV", "payment": "PAY", "expense": "EXP", "credit_note": "CN",
          "journal": "JV", "void": "VOID"}


class BooksError(Exception):
    pass


def fy_of(d):
    """Pakistan's fiscal year (July to June) of a date -> '26-27'."""
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}-{(y + 1) % 100:02d}"


def _today():
    return dt.date.today()


class Books:
    def __init__(self, path=None):
        self.path = Path(path or DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.execute("PRAGMA busy_timeout=5000")
        self.cx.executescript(SCHEMA)
        self._lock = threading.RLock()
        if not self.cx.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
            self.cx.executemany("INSERT INTO accounts VALUES (?,?,?,?)", CHART)

    def close(self):
        self.cx.close()

    # ---------------------------------------------------------------- the business
    def setup(self, **kv):
        for k, v in kv.items():
            self.cx.execute("INSERT OR REPLACE INTO company VALUES (?,?)", (k, json.dumps(v)))
        self._audit("setup", ", ".join(kv))
        return self.company()

    def company(self):
        c = {"name": "My Business", "currency": "PKR", "further_tax": None, "invoice_format": "{prefix}/{fy}/{n:04d}"}
        c.update({k: json.loads(v) for k, v in self.cx.execute("SELECT k, v FROM company")})
        return c

    def account(self, ref):
        """An account by code, role or name (expense words like 'electricity' find their account)."""
        ref = str(ref)
        r = self.cx.execute("SELECT code, name, type, role FROM accounts WHERE code=? OR role=? OR name=? COLLATE NOCASE", (ref, ref, ref)).fetchone()
        if not r:
            for code, rx in EXPENSE_WORDS.items():
                if re.search(rx, ref, re.I):
                    r = self.cx.execute("SELECT code, name, type, role FROM accounts WHERE code=?", (code,)).fetchone()
                    break
        if not r:
            raise BooksError(f"no account '{ref}'")
        return dict(zip(("code", "name", "type", "role"), r))

    def expense_account(self, words, default="6090"):
        """The expense account words point to (electricity, rent, fuel...), else the default."""
        try:
            a = self.account(words)
            return a if a["type"] == "expense" else self.account(default)
        except BooksError:
            return self.account(default)

    def add_account(self, code, name, type_, role=None):
        self.cx.execute("INSERT INTO accounts VALUES (?,?,?,?)", (code, name, type_, role))
        return self.account(code)

    # ---------------------------------------------------------------- people and things
    def party(self, name, kind=None, **info):
        """A customer or supplier, made or updated; -> dict with id."""
        name = " ".join(str(name).split())
        r = self.cx.execute("SELECT id, kind, body FROM parties WHERE name=?", (name,)).fetchone()
        if r:
            body = json.loads(r[2])
            body.update({k: v for k, v in info.items() if v not in (None, "")})
            k = r[1] if not kind or kind == r[1] else "both"
            self.cx.execute("UPDATE parties SET kind=?, body=? WHERE id=?", (k, json.dumps(body), r[0]))
            return dict(body, id=r[0], name=name, kind=k)
        cur = self.cx.execute("INSERT INTO parties (kind, name, body) VALUES (?,?,?)", (kind or "customer", name, json.dumps(info)))
        return dict(info, id=cur.lastrowid, name=name, kind=kind or "customer")

    def find_party(self, name):
        """A customer or supplier by name: exact, then starting with, then containing; several matches are asked about."""
        rows = self.cx.execute("SELECT id, kind, name, body FROM parties").fetchall()
        w = " ".join(str(name).lower().split())
        for test in (lambda n: n == w, lambda n: n.startswith(w), lambda n: w in n):
            hits = [r for r in rows if test(r[2].lower())]
            if len(hits) == 1:
                r = hits[0]
                return dict(json.loads(r[3]), id=r[0], kind=r[1], name=r[2])
            if len(hits) > 1:
                raise BooksError(f"'{name}' matches {', '.join(h[2] for h in hits[:5])}: which one?")
        return None

    def party_by_id(self, pid):
        r = self.cx.execute("SELECT id, kind, name, body FROM parties WHERE id=?", (pid,)).fetchone()
        return dict(json.loads(r[3]), id=r[0], kind=r[1], name=r[2]) if r else None

    def item(self, name, **info):
        """A product or service: rate (sale price), cost, tax (rate %), unit, stock (tracked), hs_code, kind goods/service."""
        name = " ".join(str(name).split())
        for k in ("rate", "cost"):
            if k in info and info[k] is not None and not isinstance(info[k], int):
                info[k] = to_paisa(info[k])
        r = self.cx.execute("SELECT id, body FROM items WHERE name=?", (name,)).fetchone()
        if r:
            body = json.loads(r[1])
            body.update({k: v for k, v in info.items() if v is not None})
            self.cx.execute("UPDATE items SET body=? WHERE id=?", (json.dumps(body), r[0]))
            return dict(body, id=r[0], name=name)
        info.setdefault("kind", "goods")
        info.setdefault("unit", "pcs" if info["kind"] == "goods" else "job")
        cur = self.cx.execute("INSERT INTO items (name, body) VALUES (?,?)", (name, json.dumps(info)))
        return dict(info, id=cur.lastrowid, name=name)

    def find_item(self, name):
        rows = self.cx.execute("SELECT id, name, body FROM items").fetchall()
        w = " ".join(str(name).lower().split())
        for test in (lambda n: n == w, lambda n: n.startswith(w) or w.startswith(n), lambda n: w in n or n in w):
            hits = [r for r in rows if test(r[1].lower())]
            if len(hits) == 1:
                return dict(json.loads(hits[0][2]), id=hits[0][0], name=hits[0][1])
            if len(hits) > 1:
                exact = [h for h in hits if h[1].lower() == w]
                if exact:
                    return dict(json.loads(exact[0][2]), id=exact[0][0], name=exact[0][1])
                raise BooksError(f"'{name}' matches {', '.join(h[1] for h in hits[:5])}: which one?")
        return None

    def item_by_id(self, iid):
        r = self.cx.execute("SELECT id, name, body FROM items WHERE id=?", (iid,)).fetchone()
        return dict(json.loads(r[2]), id=r[0], name=r[1]) if r else None

    # ---------------------------------------------------------------- stock
    def on_hand(self, iid, upto=None):
        """(quantity, average cost in paisa) of an item now (or up to a document id)."""
        q, a = "SELECT qty, cost FROM stock WHERE item_id=?", [iid]
        if upto is not None:
            q += " AND doc_id<=?"
            a.append(upto)
        from decimal import Decimal
        qty, value = Decimal(0), 0
        for sq, cost in self.cx.execute(q + " ORDER BY rowid", a):
            sq = Decimal(sq)
            if sq > 0:
                value += mul(cost, sq)
                qty += sq
            else:
                avg = (Decimal(value) / qty) if qty else Decimal(0)
                value -= int((avg * -sq).quantize(Decimal("1")))
                qty += sq
        avg = int((Decimal(value) / qty).quantize(Decimal("1"))) if qty else 0
        return qty, avg, value

    # ---------------------------------------------------------------- numbering and posting
    def _number(self, kind, date):
        fy = fy_of(date)
        r = self.cx.execute("SELECT n FROM sequences WHERE kind=? AND fy=?", (kind, fy)).fetchone()
        n = (r[0] if r else 0) + 1
        self.cx.execute("INSERT OR REPLACE INTO sequences VALUES (?,?,?)", (kind, fy, n))
        fmt = self.company().get("invoice_format") or "{prefix}/{fy}/{n:04d}"
        return fmt.format(prefix=self.company().get(f"{kind}_prefix") or PREFIX[kind], fy=fy, n=n)

    def _post(self, date, doc_id, memo, lines):
        """One balanced journal entry: lines = [(account code, debit, credit, party_id)]."""
        lines = [(a, int(d), int(c), p) for a, d, c, p in lines if int(d) or int(c)]
        dr, cr = sum(x[1] for x in lines), sum(x[2] for x in lines)
        if dr != cr:
            raise BooksError(f"the entry does not balance (debits {dr}, credits {cr}): nothing was saved")
        if not lines:
            raise BooksError("an entry with nothing in it")
        cur = self.cx.execute("INSERT INTO journal (date, doc_id, memo, created) VALUES (?,?,?,?)", (str(date), doc_id, memo, dt.datetime.now().isoformat()))
        eid = cur.lastrowid
        self.cx.executemany("INSERT INTO postings VALUES (?,?,?,?,?)", [(eid, a, p, d, c) for a, d, c, p in lines])
        return eid

    def _audit(self, what, detail=""):
        self.cx.execute("INSERT INTO audit VALUES (?,?,?)", (dt.datetime.now().isoformat(timespec="seconds"), what, str(detail)[:1000]))

    def _save_doc(self, kind, date, due, party, body, total, status="posted"):
        number = self._number(kind, date)
        body = dict(body, number=number)
        cur = self.cx.execute("INSERT INTO documents (kind, number, date, due, party_id, status, total, body, created) VALUES (?,?,?,?,?,?,?,?,?)",
                              (kind, number, str(date), str(due) if due else None, party["id"] if party else None, status, total, json.dumps(body),
                               dt.datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid, number

    def _tx(self):
        return _Tx(self)

    # ---------------------------------------------------------------- lines
    def lines(self, rows, buyer=None, purchase=False):
        """[{item or description, qty, rate, tax?, discount?}] -> priced lines with tax per line, and totals.
        A line names a known item (its rate, tax, unit and account follow) or is free text with a rate."""
        comp = self.company()
        default_tax = comp.get("default_tax")
        # further tax: a registered supplier selling to a buyer with no sales tax registration (no STRN)
        further = comp.get("further_tax") if (not purchase and comp.get("strn") and buyer is not None and not buyer.get("strn")) else None
        out, sub, tax, ftax = [], 0, 0, 0
        for r in rows:
            it = self.find_item(r["item"]) if r.get("item") else None
            from decimal import Decimal
            qty = Decimal(str(r.get("qty", 1)))
            if qty <= 0:
                raise BooksError("a quantity must be more than zero")
            rate = r.get("rate")
            rate = to_paisa(rate) if rate is not None and not isinstance(rate, int) else rate
            if rate is None:
                rate = (it or {}).get("cost" if purchase else "rate")
            if rate is None:
                raise BooksError(f"no price for {r.get('item') or r.get('description')}: say it, e.g. 'at 85,000'")
            amount = mul(rate, qty)
            disc = r.get("discount")
            if disc:
                d = pct(amount, str(disc).rstrip("%")) if str(disc).endswith("%") else to_paisa(disc)
                amount -= d
            t_rate = r.get("tax") if r.get("tax") is not None else (it or {}).get("tax", default_tax)
            t = pct(amount, t_rate) if t_rate not in (None, "", 0, "0") else 0
            f = pct(amount, further) if further and t else 0
            line = {"item_id": (it or {}).get("id"), "description": r.get("description") or (it or {}).get("name") or r.get("item"),
                    "qty": str(qty), "unit": r.get("unit") or (it or {}).get("unit") or "pcs", "rate": rate, "discount": r.get("discount"),
                    "amount": amount, "tax_rate": str(t_rate) if t else None, "tax": t, "further_tax": f, "hs_code": (it or {}).get("hs_code"),
                    "stock": bool((it or {}).get("stock")), "kind": (it or {}).get("kind", "goods"), "account": r.get("account")}
            out.append(line)
            sub, tax, ftax = sub + amount, tax + t, ftax + f
        return out, {"subtotal": sub, "tax": tax, "further_tax": ftax, "total": sub + tax + ftax}

    # ---------------------------------------------------------------- documents
    def _when(self, date):
        return dt.date.fromisoformat(str(date)) if date else _today()

    def quote(self, party, rows, date=None, valid_days=15, notes=None):
        p = self._party(party, "customer")
        d = self._when(date)
        lines, t = self.lines(rows, p)
        with self._tx():
            doc_id, number = self._save_doc("quote", d, d + dt.timedelta(days=valid_days), p, {"lines": lines, "totals": t, "notes": notes}, t["total"],
                                            status="open")
            self._audit("quote", number)
        return self.doc(doc_id)

    def invoice(self, party, rows, date=None, due_days=None, notes=None, from_quote=None, ref=None):
        p = self._party(party, "customer")
        d = self._when(date)
        due = d + dt.timedelta(days=int(due_days if due_days is not None else (p.get("terms") or self.company().get("terms") or 0)))
        lines, t = self.lines(rows, p)
        with self._tx():
            doc_id, number = self._save_doc("invoice", d, due, p, {"lines": lines, "totals": t, "notes": notes, "from_quote": from_quote, "ref": ref},
                                            t["total"])
            post = [("1100", t["total"], 0, p["id"])]
            for ln in lines:
                post.append(("4100" if ln["kind"] == "service" else "4000", 0, ln["amount"], None))
            post += [("2100", 0, t["tax"], None), ("2110", 0, t["further_tax"], None)]
            for ln in lines:  # stock leaves at its average cost
                if ln["stock"] and ln["item_id"]:
                    qty, avg, _ = self.on_hand(ln["item_id"])
                    from decimal import Decimal
                    if qty < Decimal(ln["qty"]):
                        raise BooksError(f"only {qty} {ln['unit']} of {ln['description']} in stock; {ln['qty']} asked (record the purchase first)")
                    cost = mul(avg, ln["qty"])
                    ln["cost"] = cost
                    self.cx.execute("INSERT INTO stock VALUES (?,?,?,?,?)", (ln["item_id"], str(d), str(-Decimal(ln["qty"])), avg, doc_id))
                    post += [("5000", cost, 0, None), ("1200", 0, cost, None)]
            self.cx.execute("UPDATE documents SET body=? WHERE id=?", (json.dumps({"lines": lines, "totals": t, "notes": notes, "from_quote": from_quote,
                                                                                   "ref": ref, "number": number}), doc_id))
            self._post(d, doc_id, f"Invoice {number} to {p['name']}", post)
            if from_quote:
                self.cx.execute("UPDATE documents SET status='invoiced' WHERE id=?", (from_quote,))
            self._audit("invoice", f"{number} {p['name']} {t['total']}")
        return self.doc(doc_id)

    def bill(self, party, rows, date=None, due_days=None, ref=None, notes=None):
        """A supplier's bill: goods into stock at their cost, expenses to their accounts, input tax kept to claim back."""
        p = self._party(party, "supplier")
        d = self._when(date)
        due = d + dt.timedelta(days=int(due_days or 0))
        lines, t = self.lines(rows, p, purchase=True)
        with self._tx():
            doc_id, number = self._save_doc("bill", d, due, p, {"lines": lines, "totals": t, "ref": ref, "notes": notes}, t["total"])
            post = [("2000", 0, t["total"], p["id"]), ("1300", t["tax"], 0, None)]
            from decimal import Decimal
            for ln in lines:
                if ln["stock"] and ln["item_id"]:
                    unit_cost = int((Decimal(ln["amount"]) / Decimal(ln["qty"])).quantize(Decimal("1")))
                    self.cx.execute("INSERT INTO stock VALUES (?,?,?,?,?)", (ln["item_id"], str(d), ln["qty"], unit_cost, doc_id))
                    post.append(("1200", ln["amount"], 0, None))
                else:  # goods not counted in stock are a purchase (cost of goods); services go to their expense
                    default = "5000" if ln.get("kind", "goods") == "goods" and not re.search("|".join(EXPENSE_WORDS.values()), ln["description"] or "", re.I) else "6090"
                    acc = self.expense_account(ln.get("account") or ln["description"] or "", default)["code"]
                    post.append((acc, ln["amount"], 0, None))
            self._post(d, doc_id, f"Bill {ref or number} from {p['name']}", post)
            self._audit("bill", f"{number} {p['name']} {t['total']}")
        return self.doc(doc_id)

    def expense(self, what, amount, date=None, paid_from="cash", tax=None, account=None, party=None, notes=None):
        """Money spent straight away (rent, electricity, fuel): its expense account found from the words."""
        d = self._when(date)
        amt = to_paisa(amount) if not isinstance(amount, int) else amount
        acc = self.expense_account(account or what)
        t = pct(amt, tax) if tax else 0
        src = "1010" if paid_from == "bank" else "1000"
        p = self._party(party, "supplier") if party else None
        with self._tx():
            doc_id, number = self._save_doc("expense", d, None, p, {"what": what, "account": acc["code"], "amount": amt, "tax": t, "paid_from": paid_from,
                                                                     "notes": notes}, amt + t)
            self._post(d, doc_id, f"{what}", [(acc["code"], amt, 0, None), ("1300", t, 0, None), (src, 0, amt + t, None)])
            self._audit("expense", f"{number} {what} {amt + t}")
        return self.doc(doc_id)

    def receipt(self, party, amount, date=None, bank=True, withheld=0, against=None, notes=None):
        """Money received from a customer, settling its invoices (oldest first, or the ones named). Income tax the customer
        withheld (s.153) counts towards the invoices and is kept as tax already paid."""
        p = self._party(party, "customer", create=False)
        d = self._when(date)
        amt = to_paisa(amount) if not isinstance(amount, int) else amount
        wht = to_paisa(withheld) if withheld and not isinstance(withheld, int) else int(withheld or 0)
        with self._tx():
            doc_id, number = self._save_doc("receipt", d, None, p, {"amount": amt, "withheld": wht, "bank": bank, "notes": notes}, amt + wht)
            self._post(d, doc_id, f"Received from {p['name']}", [("1010" if bank else "1000", amt, 0, None), ("1310", wht, 0, None), ("1100", 0, amt + wht, p["id"])])
            left = self._allocate(doc_id, p["id"], "invoice", amt + wht, against)
            self._audit("receipt", f"{number} {p['name']} {amt + wht} (unallocated {left})")
        return self.doc(doc_id)

    def payment(self, party, amount, date=None, bank=True, withheld=0, against=None, notes=None):
        """Money paid to a supplier, settling its bills; income tax withheld from it is owed to FBR."""
        p = self._party(party, "supplier", create=False)
        d = self._when(date)
        amt = to_paisa(amount) if not isinstance(amount, int) else amount
        wht = to_paisa(withheld) if withheld and not isinstance(withheld, int) else int(withheld or 0)
        with self._tx():
            doc_id, number = self._save_doc("payment", d, None, p, {"amount": amt, "withheld": wht, "bank": bank, "notes": notes}, amt + wht)
            self._post(d, doc_id, f"Paid {p['name']}", [("2000", amt + wht, 0, p["id"]), ("2200", 0, wht, None), ("1010" if bank else "1000", 0, amt, None)])
            left = self._allocate(doc_id, p["id"], "bill", amt + wht, against)
            self._audit("payment", f"{number} {p['name']} {amt + wht} (unallocated {left})")
        return self.doc(doc_id)

    def credit_note(self, invoice_number, rows=None, date=None, reason=None):
        """Goods returned or a price corrected: the invoice's lines (or some of them) reversed; stock comes back at its cost."""
        inv = self.doc_by_number(invoice_number)
        if inv["kind"] != "invoice" or inv["status"] == "void":
            raise BooksError(f"{invoice_number} is not a live invoice")
        p = self.party_by_id(inv["party_id"])
        d = self._when(date)
        src = inv["lines"]
        if rows:
            pick = []
            for r in rows:
                ln = next((x for x in src if r.get("item") and r["item"].lower() in (x["description"] or "").lower()), None)
                if not ln:
                    raise BooksError(f"{r.get('item')} is not on {invoice_number}")
                pick.append(dict(ln, qty=str(r.get("qty", ln["qty"]))))
        else:
            pick = [dict(x) for x in src]
        from decimal import Decimal
        lines, sub, tax, ftax = [], 0, 0, 0
        for ln in pick:
            k = Decimal(ln["qty"]) / Decimal(next(x for x in src if x["description"] == ln["description"])["qty"])
            amount = int((Decimal(ln["amount"]) * k).quantize(Decimal("1")))
            t = int((Decimal(ln["tax"]) * k).quantize(Decimal("1")))
            f = int((Decimal(ln.get("further_tax") or 0) * k).quantize(Decimal("1")))
            cost = int((Decimal(ln.get("cost") or 0) * k).quantize(Decimal("1")))
            lines.append(dict(ln, amount=amount, tax=t, further_tax=f, cost=cost))
            sub, tax, ftax = sub + amount, tax + t, ftax + f
        t = {"subtotal": sub, "tax": tax, "further_tax": ftax, "total": sub + tax + ftax}
        with self._tx():
            doc_id, number = self._save_doc("credit_note", d, None, p, {"lines": lines, "totals": t, "invoice": invoice_number, "reason": reason}, t["total"])
            post = [("1100", 0, t["total"], p["id"]), ("2100", tax, 0, None), ("2110", ftax, 0, None)]
            for ln in lines:
                post.append(("4100" if ln["kind"] == "service" else "4000", ln["amount"], 0, None))
                if ln.get("stock") and ln.get("item_id") and ln.get("cost"):
                    unit = int((Decimal(ln["cost"]) / Decimal(ln["qty"])).quantize(Decimal("1")))
                    self.cx.execute("INSERT INTO stock VALUES (?,?,?,?,?)", (ln["item_id"], str(d), ln["qty"], unit, doc_id))
                    post += [("1200", ln["cost"], 0, None), ("5000", 0, ln["cost"], None)]
            self._post(d, doc_id, f"Credit note {number} on {invoice_number}", post)
            self._allocate(doc_id, p["id"], "invoice", t["total"], [inv["id"]])
            self._audit("credit_note", f"{number} on {invoice_number} {t['total']}")
        return self.doc(doc_id)

    def void(self, number, reason=None):
        """A posted document cancelled by a reversing entry dated today; its number stays (marked void) so no number is lost."""
        d = self.doc_by_number(number)
        if d["status"] == "void":
            raise BooksError(f"{number} is already void")
        if self.cx.execute("SELECT SUM(amount) FROM allocations WHERE doc_id=?", (d["id"],)).fetchone()[0]:
            raise BooksError(f"{number} has payments against it: record a credit note instead")
        with self._tx():
            entries = self.cx.execute("SELECT id FROM journal WHERE doc_id=?", (d["id"],)).fetchall()
            for (eid,) in entries:
                rev = [(a, c, dr, p) for a, p, dr, c in self.cx.execute("SELECT account, party_id, debit, credit FROM postings WHERE entry_id=?", (eid,))]
                self._post(_today(), d["id"], f"Void {number}" + (f": {reason}" if reason else ""), rev)
            for iid, qty, cost in self.cx.execute("SELECT item_id, qty, cost FROM stock WHERE doc_id=?", (d["id"],)).fetchall():
                from decimal import Decimal
                self.cx.execute("INSERT INTO stock VALUES (?,?,?,?,?)", (iid, str(_today()), str(-Decimal(qty)), cost, d["id"]))
            self.cx.execute("DELETE FROM allocations WHERE pay_id=?", (d["id"],))
            self.cx.execute("UPDATE documents SET status='void' WHERE id=?", (d["id"],))
            self._audit("void", f"{number} {reason or ''}")
        return self.doc(d["id"])

    def journal(self, entries, date=None, memo=""):
        """A manual entry: [(account, debit, credit)] with amounts in rupees; it must balance."""
        d = self._when(date)
        lines = [(self.account(a)["code"], to_paisa(dr or 0), to_paisa(cr or 0), None) for a, dr, cr in entries]
        with self._tx():
            doc_id, number = self._save_doc("journal", d, None, None, {"memo": memo, "lines": [list(x[:3]) for x in lines]}, sum(x[1] for x in lines))
            self._post(d, doc_id, memo or number, lines)
            self._audit("journal", number)
        return self.doc(doc_id)

    def opening(self, cash=0, bank=0, capital=None, date=None):
        """Starting balances: cash and bank against the owner's capital (or opening balance equity)."""
        d = self._when(date)
        c, b = to_paisa(cash), to_paisa(bank)
        with self._tx():
            doc_id, number = self._save_doc("journal", d, None, None, {"memo": "Opening balances"}, c + b)
            self._post(d, doc_id, "Opening balances", [("1000", c, 0, None), ("1010", b, 0, None), ("3000" if capital else "3900", 0, c + b, None)])
        return self.doc(doc_id)

    # ---------------------------------------------------------------- settling
    def _allocate(self, pay_id, party_id, kind, amount, against=None):
        """Spread a payment over the party's open documents (the ones named first, else oldest first) -> what is left over."""
        left = amount
        docs = self.open_docs(party_id, kind)
        if against:
            ids = set(against)
            docs = [x for x in docs if x["id"] in ids] + [x for x in docs if x["id"] not in ids]
        for x in docs:
            if left <= 0:
                break
            take = min(left, x["balance"])
            if take > 0:
                self.cx.execute("INSERT INTO allocations VALUES (?,?,?)", (pay_id, x["id"], take))
                left -= take
        return left

    def paid(self, doc_id, kinds=None):
        q = "SELECT COALESCE(SUM(a.amount),0) FROM allocations a JOIN documents p ON p.id=a.pay_id WHERE a.doc_id=? AND p.status!='void'"
        a = [doc_id]
        if kinds:
            q += " AND p.kind IN (%s)" % ",".join("?" * len(kinds))
            a += list(kinds)
        return self.cx.execute(q, a).fetchone()[0]

    def open_docs(self, party_id, kind="invoice"):
        out = []
        for i, number, date, due, total, status in self.cx.execute(
                "SELECT id, number, date, due, total, status FROM documents WHERE party_id=? AND kind=? AND status NOT IN ('void') ORDER BY date, id",
                (party_id, kind)):
            bal = total - self.paid(i)
            if bal > 0:
                out.append({"id": i, "number": number, "date": date, "due": due, "total": total, "balance": bal})
        return out

    # ---------------------------------------------------------------- reading documents
    def doc(self, doc_id):
        r = self.cx.execute("SELECT id, kind, number, date, due, party_id, status, total, body FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not r:
            raise BooksError(f"no document {doc_id}")
        d = dict(zip(("id", "kind", "number", "date", "due", "party_id", "status", "total"), r[:8]))
        d.update(json.loads(r[8]))
        d["number"] = r[2]
        if d["kind"] in ("invoice", "bill"):
            d["paid"] = self.paid(d["id"])
            d["credited"] = self.paid(d["id"], ["credit_note"])
            d["balance"] = d["total"] - d["paid"] if d["status"] != "void" else 0
            d["state"] = "void" if d["status"] == "void" else "paid" if d["balance"] <= 0 else "partly paid" if d["paid"] else \
                ("overdue" if d.get("due") and d["due"] < str(_today()) else "unpaid")
        d["party"] = self.party_by_id(d["party_id"]) if d.get("party_id") else None
        d["links"] = {s: rem for s, rem in self.cx.execute("SELECT system, remote FROM links WHERE doc_id=?", (d["id"],))}
        return d

    def doc_by_number(self, number):
        n = str(number).strip().upper()
        r = self.cx.execute("SELECT id FROM documents WHERE UPPER(number)=?", (n,)).fetchone()
        if not r and re.fullmatch(r"\d+", n):  # 'invoice 12': the 12th of this year
            r = self.cx.execute("SELECT id FROM documents WHERE number LIKE ? ORDER BY id DESC", (f"%/{int(n):04d}",)).fetchone()
        if not r:
            raise BooksError(f"no document {number}")
        return self.doc(r[0])

    def docs(self, kind=None, party_id=None, since=None, until=None, limit=500):
        q, a, w = "SELECT id FROM documents", [], []
        if kind:
            w.append("kind=?")
            a.append(kind)
        if party_id:
            w.append("party_id=?")
            a.append(party_id)
        if since:
            w.append("date>=?")
            a.append(str(since))
        if until:
            w.append("date<=?")
            a.append(str(until))
        if w:
            q += " WHERE " + " AND ".join(w)
        q += " ORDER BY date, id LIMIT ?"
        return [self.doc(i) for (i,) in self.cx.execute(q, a + [limit]).fetchall()]

    def link(self, doc_id, system, remote):
        self.cx.execute("INSERT OR REPLACE INTO links VALUES (?,?,?,?)", (doc_id, system, str(remote), dt.datetime.now().isoformat(timespec="seconds")))

    def _party(self, party, kind, create=True):
        if isinstance(party, dict):
            return party
        p = self.find_party(party)
        if p:
            return p
        if not create:
            raise BooksError(f"no customer or supplier called '{party}'")
        return self.party(party, kind)

    def balance(self, account, party_id=None, upto=None):
        q = "SELECT COALESCE(SUM(p.debit),0) - COALESCE(SUM(p.credit),0) FROM postings p JOIN journal j ON j.id=p.entry_id WHERE p.account=?"
        a = [account]
        if party_id is not None:
            q += " AND p.party_id=?"
            a.append(party_id)
        if upto:
            q += " AND j.date<=?"
            a.append(str(upto))
        return self.cx.execute(q, a).fetchone()[0]


class _Tx:
    """One database transaction: everything a document does is saved together, or nothing is."""

    def __init__(self, books):
        self.b = books

    def __enter__(self):
        self.b._lock.acquire()
        self.b.cx.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, kind, exc, tb):
        try:
            if kind is None:
                self.b.cx.execute("COMMIT")
            else:
                self.b.cx.execute("ROLLBACK")
        finally:
            self.b._lock.release()
        if kind is MoneyError:
            raise BooksError(str(exc)) from exc
        return False
