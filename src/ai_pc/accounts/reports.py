"""Reports from the postings, and the checks every set of books must pass.

trial_balance(b, upto)          every account's debits and credits (they must be equal)
profit_loss(b, start, end)      income less expenses, gross profit after the cost of goods sold
balance_sheet(b, upto)          assets = liabilities + equity (+ this year's profit)
ageing(b, kind, upto)           who owes you (or whom you owe), by how long: 0-30, 31-60, 61-90, over 90 days
statement(b, party, start, end) a customer's or supplier's account, with a running balance
stock(b)                        every tracked item: quantity, average cost, value (it must equal the Stock account)
sales_tax(b, start, end)        output tax per invoice (the return's sales annex), input tax per bill, the difference due
day_book(b, start, end)         every entry in order
verify(b) -> [problems]         the books' own checks (all must pass after every change)
"""

import datetime as dt
from decimal import Decimal

ORDER = {"asset": 0, "liability": 1, "equity": 2, "income": 3, "expense": 4}


def _accounts(b):
    return {c: {"code": c, "name": n, "type": t, "role": r} for c, n, t, r in b.cx.execute("SELECT code, name, type, role FROM accounts")}


def _sums(b, start=None, end=None):
    q = "SELECT p.account, SUM(p.debit), SUM(p.credit) FROM postings p JOIN journal j ON j.id=p.entry_id"
    a, w = [], []
    if start:
        w.append("j.date>=?")
        a.append(str(start))
    if end:
        w.append("j.date<=?")
        a.append(str(end))
    if w:
        q += " WHERE " + " AND ".join(w)
    return {acc: (d or 0, c or 0) for acc, d, c in b.cx.execute(q + " GROUP BY p.account", a)}


def trial_balance(b, upto=None):
    accs, sums = _accounts(b), _sums(b, end=upto)
    rows = []
    for code, (d, c) in sorted(sums.items(), key=lambda x: (ORDER[accs[x[0]]["type"]], x[0])):
        if d == c == 0:
            continue
        bal = d - c
        rows.append(
            {"code": code, "name": accs[code]["name"], "type": accs[code]["type"], "debit": bal if bal > 0 else 0, "credit": -bal if bal < 0 else 0}
        )
    td, tc = sum(r["debit"] for r in rows), sum(r["credit"] for r in rows)
    return {"rows": rows, "debit": td, "credit": tc, "balanced": td == tc}


def profit_loss(b, start, end):
    accs, sums = _accounts(b), _sums(b, start, end)
    income, cogs, expenses = [], 0, []
    for code, (d, c) in sorted(sums.items()):
        a = accs[code]
        if a["type"] == "income" and c - d:
            income.append({"code": code, "name": a["name"], "amount": c - d})
        elif a["type"] == "expense" and d - c:
            if a["role"] == "cogs":
                cogs += d - c
            else:
                expenses.append({"code": code, "name": a["name"], "amount": d - c})
    sales = sum(x["amount"] for x in income)
    gross = sales - cogs
    exp = sum(x["amount"] for x in expenses)
    return {
        "start": str(start),
        "end": str(end),
        "income": income,
        "sales": sales,
        "cogs": cogs,
        "gross": gross,
        "expenses": expenses,
        "total_expenses": exp,
        "net": gross - exp,
    }


def _fy_start(d):
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
    return dt.date(d.year if d.month >= 7 else d.year - 1, 7, 1)


def balance_sheet(b, upto=None):
    upto = upto or dt.date.today()
    accs, sums = _accounts(b), _sums(b, end=upto)
    out = {"assets": [], "liabilities": [], "equity": []}
    profit_all = 0
    for code, (d, c) in sorted(sums.items()):
        a = accs[code]
        if a["type"] == "asset" and d - c:
            out["assets"].append({"code": code, "name": a["name"], "amount": d - c})
        elif a["type"] == "liability" and c - d:
            out["liabilities"].append({"code": code, "name": a["name"], "amount": c - d})
        elif a["type"] == "equity" and c - d:
            out["equity"].append({"code": code, "name": a["name"], "amount": c - d})
        elif a["type"] in ("income", "expense"):
            profit_all += c - d
    year = profit_loss(b, _fy_start(upto), upto)["net"]
    earlier = profit_all - year
    if earlier:
        out["equity"].append({"code": "3200", "name": "Retained Earnings (earlier years)", "amount": earlier})
    out["equity"].append({"code": "", "name": "Profit this year", "amount": year})
    ta = sum(x["amount"] for x in out["assets"])
    tl = sum(x["amount"] for x in out["liabilities"])
    te = sum(x["amount"] for x in out["equity"])
    return dict(out, upto=str(upto), total_assets=ta, total_liabilities=tl, total_equity=te, balanced=ta == tl + te)


def ageing(b, kind="receivable", upto=None):
    upto = upto or dt.date.today()
    doc_kind = "invoice" if kind == "receivable" else "bill"
    buckets = ("0-30", "31-60", "61-90", "90+")
    rows = {}
    for (pid,) in b.cx.execute("SELECT DISTINCT party_id FROM documents WHERE kind=? AND party_id IS NOT NULL", (doc_kind,)).fetchall():
        party = b.party_by_id(pid)
        for d in b.open_docs(pid, doc_kind):
            if d["date"] > str(upto):
                continue
            days = (upto - dt.date.fromisoformat(d["due"] or d["date"])).days
            k = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
            r = rows.setdefault(pid, {"party": party["name"], "phone": party.get("phone"), **{x: 0 for x in buckets}, "total": 0, "docs": []})
            r[k] += d["balance"]
            r["total"] += d["balance"]
            r["docs"].append(dict(d, days=max(days, 0)))
    out = sorted(rows.values(), key=lambda r: -r["total"])
    return {"rows": out, "total": sum(r["total"] for r in out), "buckets": buckets, "kind": kind}


def statement(b, party, start=None, end=None):
    p = party if isinstance(party, dict) else b.find_party(party)
    acc = "1100" if p["kind"] in ("customer", "both") else "2000"
    start = start or "2000-01-01"
    end = end or dt.date.today()
    opening = b.balance(acc, p["id"], dt.date.fromisoformat(str(start)) - dt.timedelta(days=1))
    rows, bal = [], opening
    q = (
        "SELECT j.date, j.memo, p.debit, p.credit, j.doc_id FROM postings p JOIN journal j ON j.id=p.entry_id WHERE p.account=? AND p.party_id=? "
        "AND j.date>=? AND j.date<=? ORDER BY j.date, j.id"
    )
    for date, memo, d, c, doc_id in b.cx.execute(q, (acc, p["id"], str(start), str(end))):
        bal += d - c
        number = b.cx.execute("SELECT number FROM documents WHERE id=?", (doc_id,)).fetchone()
        rows.append({"date": date, "number": number[0] if number else "", "memo": memo, "debit": d, "credit": c, "balance": bal})
    sign = 1 if acc == "1100" else -1
    return {"party": p["name"], "account": acc, "start": str(start), "end": str(end), "opening": sign * opening, "rows": rows, "closing": sign * bal}


def qty_str(q):
    """10 -> '10', 2.50 -> '2.5' (never '1E+1')."""
    s = format(Decimal(q).normalize(), "f") if q else "0"
    return s


def stock(b):
    rows = []
    for (iid,) in b.cx.execute("SELECT DISTINCT item_id FROM stock").fetchall():
        it = b.item_by_id(iid)
        qty, avg, value = b.on_hand(iid)
        rows.append(
            {
                "item": it["name"],
                "unit": it.get("unit"),
                "qty": qty_str(qty),
                "avg_cost": avg,
                "value": value,
                "low": bool(it.get("reorder") is not None and qty <= Decimal(str(it["reorder"]))),
            }
        )
    rows.sort(key=lambda r: r["item"].lower())
    return {"rows": rows, "value": sum(r["value"] for r in rows)}


def sales_tax(b, start, end):
    sales, purchases = [], []
    for d in b.docs("invoice", since=start, until=end):
        if d["status"] == "void":
            continue
        p = d["party"] or {}
        sales.append(
            {
                "number": d["number"],
                "date": d["date"],
                "buyer": p.get("name"),
                "ntn": p.get("ntn") or p.get("cnic"),
                "strn": p.get("strn"),
                "value": d["totals"]["subtotal"],
                "tax": d["totals"]["tax"],
                "further_tax": d["totals"]["further_tax"],
            }
        )
    for d in b.docs("credit_note", since=start, until=end):
        sales.append(
            {
                "number": d["number"],
                "date": d["date"],
                "buyer": (d["party"] or {}).get("name"),
                "value": -d["totals"]["subtotal"],
                "tax": -d["totals"]["tax"],
                "further_tax": -d["totals"]["further_tax"],
                "credit_note": True,
            }
        )
    for d in b.docs("bill", since=start, until=end):
        if d["status"] != "void" and d["totals"]["tax"]:
            purchases.append(
                {
                    "number": d.get("ref") or d["number"],
                    "date": d["date"],
                    "supplier": (d["party"] or {}).get("name"),
                    "strn": (d["party"] or {}).get("strn"),
                    "value": d["totals"]["subtotal"],
                    "tax": d["totals"]["tax"],
                }
            )
    for d in b.docs("expense", since=start, until=end):
        if d.get("tax"):
            purchases.append({"number": d["number"], "date": d["date"], "supplier": d.get("what"), "value": d["amount"], "tax": d["tax"]})
    out_tax = sum(x["tax"] for x in sales)
    further = sum(x.get("further_tax") or 0 for x in sales)
    in_tax = sum(x["tax"] for x in purchases)
    return {
        "start": str(start),
        "end": str(end),
        "sales": sales,
        "purchases": purchases,
        "output_tax": out_tax,
        "further_tax": further,
        "input_tax": in_tax,
        "payable": out_tax + further - in_tax,
    }


def day_book(b, start, end):
    out = []
    for eid, date, memo, doc_id in b.cx.execute(
        "SELECT id, date, memo, doc_id FROM journal WHERE date>=? AND date<=? ORDER BY date, id", (str(start), str(end))
    ):
        lines = [
            {"account": a, "debit": d, "credit": c}
            for a, d, c in b.cx.execute("SELECT account, debit, credit FROM postings WHERE entry_id=?", (eid,))
        ]
        out.append({"date": date, "memo": memo, "doc_id": doc_id, "lines": lines})
    return out


def verify(b):
    """The checks every set of books must pass. -> list of problems (empty = all good)."""
    problems = []
    for eid, d, c in b.cx.execute("SELECT entry_id, SUM(debit), SUM(credit) FROM postings GROUP BY entry_id"):
        if d != c:
            problems.append(f"entry {eid} does not balance ({d} vs {c})")
    tb = trial_balance(b)
    if not tb["balanced"]:
        problems.append(f"the trial balance does not balance ({tb['debit']} vs {tb['credit']})")
    bs = balance_sheet(b)
    if not bs["balanced"]:
        problems.append(
            f"the balance sheet does not balance (assets {bs['total_assets']}, liabilities + equity {bs['total_liabilities'] + bs['total_equity']})"
        )
    st = stock(b)
    inv = b.balance("1200")
    if st["value"] != inv:
        problems.append(f"stock is worth {st['value']} item by item but the Stock account says {inv}")
    for r in st["rows"]:
        if Decimal(r["qty"]) < 0:
            problems.append(f"{r['item']} is below zero ({r['qty']})")
    for acc, kind in (("1100", "invoice"), ("2000", "bill")):
        ctrl = b.balance(acc)
        parties = sum(b.balance(acc, pid) for (pid,) in b.cx.execute("SELECT id FROM parties"))
        if ctrl != parties:
            problems.append(f"account {acc} ({ctrl}) is not the sum of its parties' balances ({parties})")
    for i, kind, number, total, status in b.cx.execute(
        "SELECT id, kind, number, total, status FROM documents WHERE kind IN ('invoice','bill','quote','credit_note')"
    ):
        d = b.doc(i)
        t = d["totals"]
        if sum(x["amount"] for x in d["lines"]) != t["subtotal"] or t["subtotal"] + t["tax"] + t["further_tax"] != t["total"] or t["total"] != total:
            problems.append(f"{number}: its lines do not add up to its total")
        if kind in ("invoice", "bill") and status != "void" and d["paid"] > total:
            problems.append(f"{number}: more was paid ({d['paid']}) than it is for ({total})")
    seen = {}
    for kind, number in b.cx.execute("SELECT kind, number FROM documents ORDER BY id"):
        seen.setdefault((kind, number.rsplit("/", 1)[0]), []).append(int(number.rsplit("/", 1)[1]) if number.rsplit("/", 1)[-1].isdigit() else 0)
    for (kind, series), ns in seen.items():
        if ns and sorted(ns) != list(range(1, len(ns) + 1)):
            problems.append(f"{kind} numbers in {series} have gaps or repeats")
    return problems
