"""The accounting software people use, kept in step with the books on this PC (which stay the record): QuickBooks Online,
TallyPrime, Xero and Zoho Books. Each document goes once: a link remembers where it went, every remote object it needs
on the way (a payment per invoice, an allocation, a status change) is remembered the moment it exists, so a retry
after a failure part-way never makes anything twice, and a lost answer is looked up (or the create is idempotent)
before anything is sent again. Customers, suppliers, items, accounts and tax rates are found there or made (and
remembered); what the software saved is read back and compared total for total; a document cancelled here is
cancelled there too.

  push(books, "xero", doc) -> {"remote", "verified", "notes"}     sync_all(books, "tally") -> [results]     pending(books, "zoho", kinds)
  connector(name) -> the system's connector (keys from the vault)  cli("steps"|"connect", name)
A connector has: name, label, kinds, ready() -> (ok, text), create(b, doc) -> remote id, read(b, doc, remote) -> {"total"},
void(b, doc, remote), and builds every create from Connector.step(..., look=...).
"""
import importlib
import re

from ..ledger import BooksError
from ..money import rs

MODULES = {"quickbooks": "quickbooks", "tally": "tally", "xero": "xero", "zoho": "zoho"}
LABEL = {"quickbooks": "QuickBooks Online", "tally": "TallyPrime", "xero": "Xero", "zoho": "Zoho Books", "fbr": "FBR Digital Invoicing"}
# what goes first: a receipt or credit note needs the invoice it settles to be there already
PRIORITY = {"invoice": 0, "quote": 0, "bill": 0, "expense": 0, "credit_note": 1, "receipt": 2, "payment": 2}
# our expense accounts, as the words other charts of accounts use for the same thing
EXPENSE_KEYS = {"6000": r"\brent", "6010": r"wage|salar|payroll", "6020": r"electric|light|power|utilit|heat|\bgas\b|water",
                "6030": r"phone|internet|telephone|communication", "6040": r"travel|motor|vehicle|transport|freight|fuel|courier",
                "6050": r"repair|maintenance", "6060": r"advertis|marketing|promotion", "6070": r"bank (?:fee|charge|service)",
                "6080": r"stationery|printing|office (?:suppl|exp)", "6090": r"general|other|misc|sundr"}


class SyncError(Exception):
    def __init__(self, message, kind="invalid"):
        super().__init__(message)
        self.kind = kind  # invalid | auth | limit | offline


def _mod(name):
    if name == "fbr":
        return importlib.import_module("..fbr", __name__)
    return importlib.import_module(f".{MODULES[name]}", __name__)


def connector(name, creds=None, transport=None):
    return _mod(name).System(creds, transport)


# ---------------------------------------------------------------- what this PC remembers about the other system
def _ensure_maps(b):
    b.cx.execute("CREATE TABLE IF NOT EXISTS maps (system TEXT, kind TEXT, local TEXT, remote TEXT, PRIMARY KEY (system, kind, local))")


def remembered(b, system, kind, local):
    _ensure_maps(b)
    r = b.cx.execute("SELECT remote FROM maps WHERE system=? AND kind=? AND local=?", (system, kind, str(local))).fetchone()
    return r[0] if r else None


def remember(b, system, kind, local, remote):
    _ensure_maps(b)
    b.cx.execute("INSERT OR REPLACE INTO maps VALUES (?,?,?,?)", (system, kind, str(local), str(remote)))


def forget(b, system, kind=None):
    _ensure_maps(b)
    if kind:
        b.cx.execute("DELETE FROM maps WHERE system=? AND kind=?", (system, kind))
    else:
        b.cx.execute("DELETE FROM maps WHERE system=?", (system,))


def once(b, system, kind, local, make):
    """A remote thing (a customer, a tax rate, an account) found or made once, then remembered."""
    rid = remembered(b, system, kind, local)
    if rid:
        return rid
    rid = make()
    remember(b, system, kind, local, rid)
    return rid


class Connector:
    """What every accounting system's connector shares: each remote object a document needs is a step, made once."""
    name = label = ""
    kinds = ()

    def __init__(self):
        self.notes, self.calls = [], 0

    def step(self, b, doc, key, make, look=None):
        """One remote object for a document: remembered the moment it exists; when it is not remembered, it is first
        looked for there by its own mark (the answer to an earlier try may have been lost after it was saved), and
        only then made. So a retry, even after a failure part-way, never makes anything twice."""
        k = f"{doc['id']}:{key}"
        rid = remembered(b, self.name, "part", k)
        if rid:
            return rid
        rid = look() if look is not None else None
        if rid:
            self.notes.append(f"{doc['number']} ({key}) was already there (an earlier answer was lost): not sent again")
        else:
            rid = make()
        remember(b, self.name, "part", k, rid)
        return rid


def linked(b, doc_id, system):
    r = b.cx.execute("SELECT remote FROM links WHERE doc_id=? AND system=?", (doc_id, system)).fetchone()
    return r[0] if r else None


# ---------------------------------------------------------------- shared reading of the books
def match_expense(code, accounts):
    """Our expense account (6000 Rent...) -> the id of the account in another chart [(id, name)] that means the same,
    else its general expenses, else the first."""
    rx = EXPENSE_KEYS.get(str(code))
    for pattern in ([rx] if rx else []) + [EXPENSE_KEYS["6090"]]:
        hit = next((a for a in accounts if re.search(pattern, a[1] or "", re.I)), None)
        if hit:
            return hit[0]
    return accounts[0][0] if accounts else None


def splits(b, doc):
    """Money in or out as the documents it settled: [(doc_id, cash, income tax withheld)], and what is left over as an
    advance (the tax withheld counts against the first documents)."""
    wht = doc.get("withheld") or 0
    out = []
    for doc_id, amount in b.cx.execute("SELECT doc_id, amount FROM allocations WHERE pay_id=? ORDER BY rowid", (doc["id"],)).fetchall():
        w = min(amount, wht)
        wht -= w
        out.append((doc_id, amount - w, w))
    return out, doc["total"] - sum(c + w for _, c, w in out)


def rate_of(amount, tax):
    """The tax rate that gives this tax on this amount (18 for 18,000 on 100,000), or None when there is no tax."""
    from decimal import Decimal
    from ..money import pct
    if not tax or not amount:
        return None
    for places in ("1", "0.1", "0.01"):
        r = (Decimal(tax) * 100 / Decimal(amount)).quantize(Decimal(places))
        if pct(amount, r) == tax:
            return r.normalize()
    raise SyncError(f"the tax {rs(tax)} on {rs(amount)} is not a whole rate")


def bill_account(b, ln):
    """Where a purchase line goes: goods (counted in stock or not) to purchases, a service to the expense its words name."""
    if ln.get("stock"):
        return "5000"
    return b.expense_account(ln.get("account") or ln.get("description") or "", "5000" if ln.get("kind", "goods") == "goods" else "6090")["code"]


def needs_first(b, doc, system):
    """The documents a receipt, payment or credit note settles that are not in the system yet."""
    if doc["kind"] == "credit_note":
        inv = b.doc_by_number(doc["invoice"])
        return [inv["number"]] if not linked(b, inv["id"], system) else []
    if doc["kind"] in ("receipt", "payment"):
        return [b.doc(i)["number"] for i, _, _ in splits(b, doc)[0] if not linked(b, i, system)]
    return []


# ---------------------------------------------------------------- sending
def push(b, name, doc, conn=None):
    """One document into the accounting software, once; read back and compared."""
    conn = conn or connector(name)
    if doc["kind"] not in conn.kinds:
        raise SyncError(f"{conn.label} does not take {doc['kind'].replace('_', ' ')}s from here")
    remote = linked(b, doc["id"], name)
    if doc["status"] == "void":
        if not remote:
            return {"remote": None, "verified": True, "notes": ["cancelled here before it was sent: nothing to send"]}
        if remembered(b, name, "voided", doc["id"]):
            return {"remote": remote, "verified": True, "notes": ["already cancelled there"]}
        conn.void(b, doc, remote)
        remember(b, name, "voided", doc["id"], remote)
        b._audit(f"sync {name}", f"void {doc['number']} ({remote})")
        return {"remote": remote, "verified": True, "notes": ["cancelled there too"]}
    conn.notes = []
    if remote:
        notes = ["already there"]
    else:
        notes = []
        missing = needs_first(b, doc, name)
        if missing:
            raise SyncError(f"send {', '.join(missing)} to {conn.label} first")
        remote = conn.create(b, doc)  # every part looked for before it is made (see Connector.step)
        b.link(doc["id"], name, remote)
        b._audit(f"sync {name}", f"{doc['number']} -> {remote}")
    notes += conn.notes
    got = conn.read(b, doc, remote)
    want = conn.expected(b, doc) if hasattr(conn, "expected") else doc["total"]
    ok = bool(got) and got.get("total") == want
    if not got:
        notes.append("could not be read back")
    elif not ok:
        notes.append(f"its total there is {rs(got.get('total') or 0)}, here {rs(want)}")
    return {"remote": remote, "verified": ok, "notes": notes + list((got or {}).get("notes") or []), "got": got}


def pending(b, name, kinds):
    """Documents not yet in the system, and cancellations not yet carried there, in the order they must go."""
    out = []
    for d in b.docs(limit=10 ** 7):
        if d["kind"] not in kinds:
            continue
        r = linked(b, d["id"], name)
        if (d["status"] == "void" and r and not remembered(b, name, "voided", d["id"])) or (d["status"] != "void" and not r):
            out.append(d)
    out.sort(key=lambda d: (PRIORITY.get(d["kind"], 3), d["date"], d["id"]))
    return out


def sync_all(b, name, conn=None, docs=None):
    """Every document not yet there (or the ones given); stops at a sign-in, limit or connection problem."""
    conn = conn or connector(name)
    out = []
    for d in (docs if docs is not None else pending(b, name, conn.kinds)):
        try:
            r = push(b, name, d, conn)
            out.append(dict(r, number=d["number"], ok=r["verified"]))
        except (SyncError, BooksError) as e:
            out.append({"number": d["number"], "ok": False, "notes": [str(e)], "kind": getattr(e, "kind", "invalid")})
            if getattr(e, "kind", "") in ("auth", "limit", "offline"):
                break
    return out


# ---------------------------------------------------------------- setting up
def cli(cmd, name):
    import getpass
    names = [name] if name else list(MODULES) + ["fbr"]
    for n in names:
        if n not in MODULES and n != "fbr":
            raise SystemExit(f"unknown: {n}; one of {', '.join(list(MODULES) + ['fbr'])}")
    if cmd == "steps":
        for n in names:
            s = _mod(n).APP
            print(f"\n== {s['label']}  (accounts.py connect {n})")
            for i, st in enumerate(s["steps"], 1):
                print(f"  {i}. {st}")
            if s.get("notes"):
                print(f"  Note: {s['notes']}")
        return
    n = names[0]
    m = _mod(n)
    cli("steps", n)
    vals = {}
    for key, prompt, secret in m.APP["fields"]:
        v = (getpass.getpass(f"{prompt} (hidden): ") if secret else input(f"{prompt}: ")).strip()
        if not v and not key.endswith("?"):
            raise SystemExit("nothing typed; nothing saved")
        vals[key.rstrip("?")] = v
    try:
        who = m.connect(vals)
        print(f"\nConnected {m.APP['label']}: {who.get('who')} ({who.get('where')}). Keys are kept encrypted for this Windows user.")
    except SyncError as e:
        print(f"\nNot connected: {e}")
