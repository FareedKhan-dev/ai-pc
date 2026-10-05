"""A conversation that keeps the books. Every entry (an invoice, a bill, money in or out, a return, a cancellation) is shown
first with its figures, tax and total in words, and saved only after a yes; then its document (PDF) is made and checked,
and the books' own checks run (debits = credits, the balance sheet balances, stock agrees with the Stock account).
Reports are read at once. A pending invoice can be changed in words before it is saved.

  ac = AccountsChat.start()
  ac.say("invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 1 wall mount at 3,500, 18% tax, due in 15 days")  -> preview
  ac.say("make the TV 84,000") -> new preview      ac.say("yes") -> INV/26-27/0001 saved, PDF made and checked
  ac.say("Ali Traders paid 1 lakh by bank") / ac.say("who owes me money?") / ac.say("profit this month") / ac.say("sales tax for september")
"""
import datetime as dt
import json
import re
import time
from pathlib import Path

from ai_pc.accounts import documents as DOCS
from ai_pc.accounts import reports as R
from ai_pc.accounts.accountsparse import lines_in, parse
from ai_pc.accounts.ledger import Books, BooksError
from ai_pc.accounts.money import MoneyError, rs, to_paisa, words
from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json

CHATS = ROOT / "out" / "accounts" / "chats"
# a yes is the whole reply ('yes', 'ok, save it', 'send it please'): 'send invoice 2 to Xero' is a new request, not a yes
YES = re.compile(r"^\s*(?:yes|yeah|yep|y|ok|okay|sure|save|post|go|do it|confirm(?:ed)?|record|send|cancel it|void it)\b"
                 r"(?:[\s,]+(?:it|please|now|that|ahead|thanks|save|send|post|go|do|yes|ok|confirm))*[\s.!]*$", re.I)
NO = re.compile(r"^\s*(?:no|nope|n|stop|don'?t|drop it|never mind|forget it|discard)\b", re.I)
ACCOUNTS_SYSTEM = """You turn a request about a small business's books into actions for a program. Reply with ONE JSON object: {"ops": [...]} or {"ask": "<short question>"}.
Actions (amounts as the person wrote them, e.g. "85,000" or "1.5 lakh"):
 {"op": "invoice"|"quote", "party": "customer", "lines": [{"item": "...", "qty": "2", "rate": "85,000", "tax": "18"}], "due_days": 15}
 {"op": "bill", "party": "supplier", "lines": [...], "ref": "their bill number"}
 {"op": "receipt", "party": "customer", "amount": "...", "bank": true, "withheld": "income tax they deducted or null"}
 {"op": "payment", "party": "supplier", "amount": "...", "bank": true}
 {"op": "expense", "what": "electricity", "amount": "...", "paid_from": "cash|bank"}
 {"op": "credit_note", "party": "...", "invoice": "invoice number", "lines": [{"item": "...", "qty": "1"}]}
 {"op": "report", "what": "owed|owing|profit|balance_sheet|trial_balance|sales_tax|stock|statement|day_book", "party": null, "item": null,
  "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} or null}
 {"op": "void", "kind": "invoice", "ref": "number"}  {"op": "show", "kind": "invoice", "ref": "number"}
 {"op": "setup", "name": "business name", "ntn": "...", "strn": "...", "address": "...", "phone": "...", "default_tax": "18"}  (only the fields said)
 {"op": "item", "name": "...", "rate": "sale price", "cost": "cost price", "tax": "18", "stock": true, "kind": "goods|service"}
 {"op": "party", "name": "...", "kind": "customer|supplier", "ntn": "...", "strn": "...", "phone": "..."}
 {"op": "sync", "system": "quickbooks|tally|xero|zoho", "ref": "document number or null for everything"}  {"op": "fbr", "ref": "invoice number"}
Use only the person's own figures and names; never invent prices, quantities, tax rates or customers. Today is {today}."""


class AccountsChat:
    def __init__(self, state, planner=None, books=None, hub=None, connectors=None):
        self.state, self.planner = state, planner
        self.folder = Path(state["folder"])
        self.b = books or Books(state.get("db"))
        self.hub = hub
        self.connectors = dict(connectors or {})  # name -> connector (tests give fakes; otherwise made from the vault)
        self.last_turn = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, db=None, books=None, hub=None, connectors=None):
        cid = f"accounts_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        st = {"id": cid, "folder": str(folder), "turns": [], "pending": None, "made": [], "db": str(db) if db else None}
        return cls(st, planner, books if books is not None else (Books(db) if db else None), hub, connectors)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def ctx(self):
        b = self.b
        return {"parties": [r[0] for r in b.cx.execute("SELECT name FROM parties")], "items": [r[0] for r in b.cx.execute("SELECT name FROM items")],
                "now": dt.datetime.now(), "last": (self.state["made"] or [None])[-1]}

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "llm": False}
        self._turn = turn
        p = self.state.get("pending")
        try:
            if p and YES.search(message):
                self.state["pending"] = None
                turn["intents"].append("confirm")
                reply = getattr(self, "do_" + p["op"])(p)
            elif p and NO.search(message):
                self.state["pending"] = None
                turn["intents"].append("drop")
                reply = "Dropped; nothing was saved."
            elif p and p["op"] in ("invoice", "quote", "bill") and self._edit(p, message):
                turn["intents"].append("edit")
                reply = self.preview(p)
            else:
                if p:
                    self.state["pending"] = None
                r = parse(message, self.ctx())
                if not r["ops"] and not r.get("ask"):
                    r = self._llm(message)
                if r.get("ask") and not r["ops"]:
                    reply = r["ask"]
                else:
                    reply = "\n".join(self.run(op) for op in r["ops"]) or ("Tell me what to record, e.g. 'invoice for Ali Traders: 2 LED TV 55 at 85,000 each, "
                                                                          "18% tax' or 'who owes me money?'.")
        except (BooksError, MoneyError) as e:
            reply = f"Couldn't: {e}"
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2))
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, message):
        if self.planner is None:
            return {"ops": [], "ask": "Say it like 'invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 18% tax', 'Ali Traders paid 50,000', "
                                      "'paid rent 40,000 from bank' or 'profit this month'."}
        self._turn["llm"] = True
        c = self.ctx()
        sys_ = ACCOUNTS_SYSTEM.replace("{today}", dt.date.today().strftime("%A %d %B %Y"))
        try:
            r = self.planner._call("fast", [{"role": "system", "content": sys_},
                                            {"role": "user", "content": f"CUSTOMERS AND SUPPLIERS: {', '.join(c['parties'][:60]) or 'none'}\n"
                                                                        f"ITEMS: {', '.join(c['items'][:80]) or 'none'}\nREQUEST: {message}"}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op")]
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    def run(self, op):
        self._turn["intents"].append(op["op"])
        fn = getattr(self, "op_" + op["op"], None)
        if not fn:
            return f"I can't {op['op']} yet."
        return fn(op)

    # ---------------------------------------------------------------- the business and its lists
    def op_setup(self, op):
        vals = {k: v for k, v in op.items() if k != "op" and v}
        if not vals:
            return "Tell me what to set, e.g. 'my business is Khan Electronics, NTN 1234567-8, STRN 3277876123456, address ...'."
        c = self.b.setup(**vals)
        missing = [lab for k, lab in (("name", "the business name"), ("ntn", "NTN"), ("strn", "STRN (only if registered for sales tax)"),
                                      ("address", "address"), ("phone", "phone")) if not c.get(k)]
        return f"Saved: {', '.join(vals)}." + (f" Still missing: {', '.join(missing)}." if missing else "")

    def op_item(self, op):
        it = self.b.item(op["name"], **{k: v for k, v in op.items() if k not in ("op", "name") and v not in (None, "")})
        bits = [f"price {rs(it['rate'])}" if it.get("rate") else None, f"cost {rs(it['cost'])}" if it.get("cost") else None,
                f"{it['tax']}% tax" if it.get("tax") else None, "stock counted" if it.get("stock") else None]
        return f"Item {it['name']}: " + ", ".join(b for b in bits if b) + "."

    def op_party(self, op):
        p = self.b.party(op["name"], op.get("kind"), **{k: v for k, v in op.items() if k not in ("op", "name", "kind") and v})
        return f"{p['kind'].title()} {p['name']} saved" + (" (" + ", ".join(f"{k.upper()} {p[k]}" for k in ("ntn", "strn", "cnic") if p.get(k)) + ")"
                                                       if any(p.get(k) for k in ("ntn", "strn", "cnic")) else "") + "."

    def op_opening(self, op):
        self.state["pending"] = dict(op)
        return f"Ready to record opening balances: cash {rs(to_paisa(op['cash']))}, bank {rs(to_paisa(op['bank']))} (against the owner's capital). Say 'yes'."

    def do_opening(self, p):
        d = self.b.opening(p["cash"], p["bank"], capital=True)
        return f"Opening balances recorded ({d['number']}). " + self._checks()

    # ---------------------------------------------------------------- invoices, quotations, bills
    def op_invoice(self, op):
        return self._sale(op, "invoice")

    def op_quote(self, op):
        return self._sale(op, "quote")

    def op_bill(self, op):
        return self._sale(op, "bill")

    def _sale(self, op, kind):
        pend = {"op": kind, "party": op.get("party"), "lines": op.get("lines") or [], "due_days": op.get("due_days"), "date": op.get("date"),
                "ref": op.get("ref"), "notes": op.get("notes"), "valid_days": op.get("valid_days")}
        if not pend["party"]:
            return "For whom? e.g. 'invoice for Ali Traders: ...'."
        text = self.preview(pend)  # a preview that cannot be made (a missing price) leaves nothing pending
        self.state["pending"] = pend
        return text

    def preview(self, p):
        kind = p["op"]
        party = self.b.find_party(p["party"])
        new = party is None
        buyer = party or {"name": p["party"]}
        lines, t = self.b.lines(p["lines"], buyer, purchase=kind == "bill")
        c = self.b.company()
        today = dt.date.fromisoformat(p["date"]) if p.get("date") else dt.date.today()
        rows = []
        for i, ln in enumerate(lines, 1):
            q = ln["qty"].rstrip("0").rstrip(".") if "." in ln["qty"] else ln["qty"]
            row = f"  {i}. {ln['description']}: {q} {ln['unit']} x {rs(ln['rate'], '')} = {rs(ln['amount'], '')}"
            if ln.get("discount"):
                row += f" (after {ln['discount']} discount)"
            if ln["tax"]:
                row += f" + {ln['tax_rate']}% tax {rs(ln['tax'], '')}"
            if ln.get("further_tax"):
                row += f" + further tax {rs(ln['further_tax'], '')}"
            rows.append(row)
        what = {"invoice": "Invoice for", "quote": "Quotation for", "bill": "Bill from"}[kind]
        head = f"{what} {buyer['name']}" + (" (new: added as a " + ("supplier" if kind == "bill" else "customer") + ")" if new else "") + \
            f", dated {today:%d %b %Y}"
        if kind == "invoice":
            dd = p.get("due_days") if p.get("due_days") is not None else (buyer.get("terms") or c.get("terms") or 0)
            head += f", due {today + dt.timedelta(days=int(dd)):%d %b %Y}"
        if kind == "quote":
            head += f", valid {p.get('valid_days') or 15} days"
        out = [head + ":"] + rows
        out.append(f"Value excluding tax {rs(t['subtotal'])}; sales tax {rs(t['tax'])}" + (f"; further tax {rs(t['further_tax'])}" if t["further_tax"] else "") +
                   f"; total {rs(t['total'])} ({words(t['total'])}).")
        notes = []
        if kind == "invoice":
            for ln in lines:
                if ln["stock"] and ln["item_id"]:
                    from decimal import Decimal
                    qty = self.b.on_hand(ln["item_id"])[0]
                    left = qty - Decimal(ln["qty"])
                    notes.append(f"{ln['description']}: {R.qty_str(left)} left after this" if left >= 0 else
                                 f"only {R.qty_str(qty)} {ln['description']} in stock: record the purchase first")
            if t["tax"] and c.get("strn") and not (buyer.get("ntn") or buyer.get("cnic") or buyer.get("strn")):
                notes.append("a sales tax invoice should show the buyer's NTN or CNIC: say 'add customer ... NTN ...'")
            if t["further_tax"]:
                notes.append(f"further tax {c.get('further_tax')}% added: the buyer has no sales tax registration (STRN)")
        if notes:
            out.append("Note: " + "; ".join(notes) + ".")
        out.append("Say 'yes' to save it" + (" and make the PDF" if kind != "bill" else "") + ", 'no' to drop it, or change it ('make the TV 84,000', "
                                                                                          "'remove installation', 'due in 30 days').")
        return "\n".join(out)

    def _edit(self, p, msg):
        """Changes to a pending invoice, quotation or bill, in words."""
        c = msg.lower()
        lines = p["lines"]
        hit = False
        m = re.search(r"\b(?:make|change|set)\s+(?:the\s+)?(.+?)\s+(?:price\s+|rate\s+)?(?:to\s+)?(" + r"(?:rs\.?\s*)?\d[\d,]*(?:\.\d+)?(?:\s*(?:lakh|k))?" + r")\s*(?:each)?$", c)
        if m:
            name = m.group(1).replace(" price", "").replace(" rate", "")
            for ln in lines:
                if name in ln["item"].lower() or ln["item"].lower() in name:
                    ln["rate"] = m.group(2)
                    hit = True
        m = re.search(r"\b(?:make it|make that|change to)\s+(\d+(?:\.\d+)?)\s+(.+)$", c)
        if m:
            for ln in lines:
                if m.group(2).rstrip("s") in ln["item"].lower():
                    ln["qty"] = m.group(1)
                    hit = True
        m = re.search(r"\b(?:remove|delete|drop|take off)\s+(?:the\s+)?(.+)$", c)
        if m:
            n = len(lines)
            p["lines"] = [ln for ln in lines if m.group(1).rstrip("s") not in ln["item"].lower()]
            hit = hit or len(p["lines"]) != n
        m = re.match(r"^\s*(?:add|also|plus)\s+(.+)$", msg, re.I)
        if m:
            extra = lines_in(m.group(1), self.ctx()["items"])
            if extra:
                p["lines"] += extra
                hit = True
        m = re.search(r"\bdue\s+in\s+(\d+)\s*days?\b", c)
        if m:
            p["due_days"] = int(m.group(1))
            hit = True
        m = re.search(r"\b(?:no tax|without tax|tax free)\b", c)
        if m:
            for ln in p["lines"]:
                ln["tax"] = "0"
            hit = True
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*%\s*(?:sales\s*)?tax\b", c)
        if m and not re.search(r"\bno tax\b", c):
            for ln in p["lines"]:
                ln["tax"] = m.group(1)
            hit = True
        return hit

    def do_invoice(self, p):
        d = self.b.invoice(p["party"], p["lines"], date=p.get("date"), due_days=p.get("due_days"), notes=p.get("notes"), from_quote=p.get("from_quote"))
        return self._made(d)

    def do_quote(self, p):
        d = self.b.quote(p["party"], p["lines"], date=p.get("date"), valid_days=p.get("valid_days") or 15, notes=p.get("notes"))
        return self._made(d)

    def do_bill(self, p):
        d = self.b.bill(p["party"], p["lines"], date=p.get("date"), due_days=p.get("due_days"), ref=p.get("ref"))
        self.state["made"].append(d["number"])
        return f"Bill {d['number']}" + (f" (their number {d['ref']})" if d.get("ref") else "") + f" from {d['party']['name']} saved: {rs(d['total'])}, " \
            f"input tax {rs(d['totals']['tax'])} to claim. " + self._checks()

    def _made(self, d):
        self.state["made"].append(d["number"])
        doc = DOCS.make(self.b, d, self.folder / "documents")
        bad = [c for c in doc["checks"] if not c["ok"]]
        what = {"invoice": "Invoice", "quote": "Quotation"}.get(d["kind"], d["kind"].title())
        return (f"{what} {d['number']} for {d['party']['name']} saved: {rs(d['total'])}" + (f", due {d['due']}" if d["kind"] == "invoice" else "") +
                f". PDF: {doc['pdf']} (" + ("checked: " + ", ".join(c["what"] for c in doc["checks"][:3]) if not bad else
                                          "NOT right: " + "; ".join(c["what"] for c in bad)) + "). " + self._checks())

    def op_convert(self, op):
        q = self.b.doc_by_number(op["ref"]) if "/" in str(op["ref"]) else self._find("quote", op["ref"])
        if q["kind"] != "quote":
            return f"{q['number']} is not a quotation."
        lines = [{"item": ln["description"], "qty": ln["qty"], "rate": ln["rate"], "tax": ln.get("tax_rate") or "0", "discount": ln.get("discount")} for ln in q["lines"]]
        pend = {"op": "invoice", "party": q["party"]["name"], "lines": lines, "from_quote": q["id"]}
        self.state["pending"] = pend
        return self.preview(pend)

    def _find(self, kind, ref):
        if ref is None:
            raise BooksError("which one? give its number")
        if "/" in str(ref):
            return self.b.doc_by_number(ref)
        ds = [d for d in self.b.docs(kind) if d["number"].endswith(f"/{int(ref):04d}")]
        if not ds:
            raise BooksError(f"no {kind.replace('_', ' ')} {ref}")
        return ds[-1]

    # ---------------------------------------------------------------- money in and out
    def op_receipt(self, op):
        p = self.b.find_party(op["party"])
        if not p:
            return f"No customer called '{op['party']}'. Their invoices come first ('invoice for {op['party']}: ...')."
        amt = to_paisa(op["amount"])
        wht = to_paisa(op["withheld"]) if op.get("withheld") else 0
        open_ = self.b.open_docs(p["id"], "invoice")
        owed = sum(x["balance"] for x in open_)
        self.state["pending"] = dict(op, party=p["name"])
        settle, left = [], amt + wht
        for x in open_:
            take = min(left, x["balance"])
            if take > 0:
                settle.append(f"{x['number']} ({rs(take)}{' in full' if take == x['balance'] else ''})")
                left -= take
        return (f"Ready to record {rs(amt)} received from {p['name']} by {'bank' if op.get('bank', True) else 'cash'}" +
                (f", plus {rs(wht)} income tax they withheld" if wht else "") + f". They owed {rs(owed)}; this settles " +
                (", ".join(settle) if settle else "no invoice") + (f"; {rs(left)} stays as an advance" if left > 0 else "") +
                f". They will owe {rs(max(owed - amt - wht, 0))}. Say 'yes' to save it.")

    def do_receipt(self, p):
        d = self.b.receipt(p["party"], p["amount"], date=p.get("date"), bank=p.get("bank", True), withheld=p.get("withheld") or 0)
        self.state["made"].append(d["number"])
        doc = DOCS.make(self.b, d, self.folder / "documents")
        owed = sum(x["balance"] for x in self.b.open_docs(d["party_id"], "invoice"))
        return f"Receipt {d['number']} saved; {d['party']['name']} now owes {rs(owed)}. Receipt PDF: {doc['pdf']}. " + self._checks()

    def op_payment(self, op):
        p = self.b.find_party(op["party"])
        if not p:
            return f"No supplier called '{op['party']}'."
        amt = to_paisa(op["amount"])
        owe = sum(x["balance"] for x in self.b.open_docs(p["id"], "bill"))
        self.state["pending"] = dict(op, party=p["name"])
        return f"Ready to record {rs(amt)} paid to {p['name']} by {'bank' if op.get('bank', True) else 'cash'}. You owed them {rs(owe)}; after this {rs(max(owe - amt, 0))}." \
               " Say 'yes' to save it."

    def do_payment(self, p):
        d = self.b.payment(p["party"], p["amount"], date=p.get("date"), bank=p.get("bank", True), withheld=p.get("withheld") or 0)
        self.state["made"].append(d["number"])
        return f"Payment {d['number']} to {d['party']['name']} saved. " + self._checks()

    def op_expense(self, op):
        acc = self.b.expense_account(op["what"])
        amt = to_paisa(op["amount"])
        self.state["pending"] = dict(op)
        return f"Ready to record {rs(amt)} spent on {op['what']} ({acc['name']}), paid from {op.get('paid_from') or 'cash'}. Say 'yes' to save it."

    def do_expense(self, p):
        d = self.b.expense(p["what"], p["amount"], date=p.get("date"), paid_from=p.get("paid_from") or "cash", tax=p.get("tax"))
        self.state["made"].append(d["number"])
        return f"Expense {d['number']} saved ({rs(d['total'])}). " + self._checks()

    def op_credit_note(self, op):
        if op.get("invoice"):
            inv = self._find("invoice", op["invoice"])
        else:
            p = self.b.find_party(op.get("party") or "")
            if not p:
                return "Which invoice is the return against? e.g. 'Ali Traders returned 1 wall mount from invoice 1'."
            invs = [d for d in self.b.docs("invoice", party_id=p["id"]) if d["status"] != "void"]
            want = [ln["item"].lower() for ln in op.get("lines") or []]
            invs = [d for d in invs if any(w in ln["description"].lower() for ln in d["lines"] for w in want)] or invs
            if not invs:
                return f"{p['name']} has no invoice to return against."
            inv = invs[-1]
        self.state["pending"] = {"op": "credit_note", "invoice": inv["number"], "lines": op.get("lines") or None, "reason": op.get("reason")}
        what = ", ".join(f"{ln['qty']} {ln['item']}" for ln in op.get("lines") or []) or "the whole invoice"
        return f"Ready to record a credit note on {inv['number']} ({inv['party']['name']}) for {what}: the amount, its tax and the stock come back. Say 'yes'."

    def do_credit_note(self, p):
        d = self.b.credit_note(p["invoice"], p.get("lines"), reason=p.get("reason"))
        self.state["made"].append(d["number"])
        doc = DOCS.make(self.b, d, self.folder / "documents")
        return f"Credit note {d['number']} saved: {rs(d['total'])} back to {d['party']['name']}. PDF: {doc['pdf']}. " + self._checks()

    def op_void(self, op):
        d = self._find(op.get("kind") or "invoice", op["ref"])
        self.state["pending"] = {"op": "void", "number": d["number"], "reason": op.get("reason")}
        return f"Ready to cancel {d['number']} ({(d.get('party') or {}).get('name', '')}, {rs(d['total'])}): a reversing entry is made and its number is " \
               "kept, marked void. Say 'yes' to cancel it."

    def do_void(self, p):
        d = self.b.void(p["number"], p.get("reason"))
        return f"{d['number']} is void. " + self._checks()

    def op_undo(self, op):
        made = [n for n in self.state["made"] if self.b.doc_by_number(n)["status"] != "void"]
        if not made:
            return "Nothing saved in this chat to take back."
        return self.op_void({"kind": None, "ref": made[-1]})

    def op_show(self, op):
        d = self._find(op.get("kind") or "invoice", op["ref"])
        doc = DOCS.make(self.b, d, self.folder / "documents")
        return f"{d['number']}: {(d.get('party') or {}).get('name', '')}, {rs(d['total'])}" + (f", {d['state']}" if d.get("state") else "") + f". PDF: {doc['pdf']}"

    def op_email(self, op):
        d = self._find(op.get("kind") or "invoice", op["ref"]) if op.get("ref") else None
        if not d:
            return "Which document? e.g. 'email invoice 3 to ali@x.com'."
        doc = DOCS.make(self.b, d, self.folder / "documents")
        c = self.b.company()
        body = (f"Dear {(d.get('party') or {}).get('name', 'customer')},\n\nPlease find attached {d['kind'].replace('_', ' ')} {d['number']} for {rs(d['total'])}" +
                (f", due on {d['due']}" if d["kind"] == "invoice" and d.get("due") else "") + f".\n\nBest regards,\n{c.get('name')}")
        if self.hub is None:
            try:
                from ai_pc.hub.hubchat import HubChat
                self.hub = HubChat.start(files=[doc["pdf"]])
            except Exception as e:  # noqa: BLE001
                return f"The PDF is ready ({doc['pdf']}) but email is not set up ({e}). Connect Gmail or Outlook with 'ai-pc hub connect google'."
        self.hub.state["files"][Path(doc["pdf"]).name.lower()] = doc["pdf"]
        services = self.hub.services()
        svc = "google" if "google" in services else "microsoft" if "microsoft" in services else None
        if not svc:
            return f"The PDF is ready ({doc['pdf']}). To email it, connect Gmail or Outlook first ('ai-pc hub steps google')."
        reply = self.hub.run({"op": "email", "service": svc, "to": [op["to"]], "subject": f"{d['kind'].replace('_', ' ').title()} {d['number']} from {c.get('name')}",
                              "body": body, "attach": [doc["pdf"]]})
        self.state["pending"] = {"op": "hub"}
        return reply

    def do_hub(self, p):
        return self.hub.say("yes")

    # ---------------------------------------------------------------- other accounting software, and FBR
    def _conn(self, name):
        if name not in self.connectors:
            if name == "fbr":
                from ai_pc.accounts.fbr import System
                self.connectors[name] = System()
            else:
                from ai_pc.accounts import systems
                self.connectors[name] = systems.connector(name)
        return self.connectors[name]

    def op_sync(self, op):
        from ai_pc.accounts import systems as S
        conn = self._conn(op["system"])
        ok, where = conn.ready()
        if not ok:
            return where + "."
        if op.get("ref") and not op.get("all"):
            docs = [self._find(op.get("kind") or "invoice", op["ref"])]
        else:
            docs = S.pending(self.b, conn.name, conn.kinds)
        if not docs:
            return f"Everything is already in {where}."
        if any(d["kind"] not in conn.kinds for d in docs):
            return f"{conn.label} does not take {docs[0]['kind'].replace('_', ' ')}s from here."
        kinds = {}
        for d in docs:
            k = (d["kind"].replace("_", " "), d["status"] == "void")
            kinds[k] = kinds.get(k, 0) + 1
        self.state["pending"] = {"op": "sync", "system": conn.name, "numbers": [d["number"] for d in docs]}
        what = docs[0]["number"] if len(docs) == 1 else f"{len(docs)} documents (" + ", ".join(
            f"{n} {k}{'s' if n > 1 else ''}{' to cancel there' if void else ''}" for (k, void), n in kinds.items()) + ")"
        return (f"Ready to send {what} to {where}: its customers, items and tax rates are found there or made, then each is read back and its total "
                "compared. Say 'yes' to send.")

    def do_sync(self, p):
        from ai_pc.accounts import systems as S
        conn = self._conn(p["system"])
        res = S.sync_all(self.b, conn.name, conn, [self.b.doc_by_number(n) for n in p["numbers"]])
        good = [r for r in res if r["ok"]]
        bad = [r for r in res if not r["ok"]]
        out = f"Sent to {conn.label}: {len(good)} of {len(p['numbers'])}, each read back with the same total."
        notes = [f"{r['number']}: {n}" for r in good for n in r.get("notes") or [] if n != "already there"]
        if notes:
            out += " Notes: " + "; ".join(notes[:5]) + "."
        if bad:
            out += " NOT sent: " + "; ".join(f"{r['number']}: {r['notes'][0]}" for r in bad[:5]) + "."
            if len(good) + len(bad) < len(p["numbers"]):
                out += " The rest wait for the next 'sync'."
        return out

    def op_fbr(self, op):
        from ai_pc.accounts.systems import SyncError
        d = self._find(op.get("kind") or "invoice", op["ref"])
        conn = self._conn("fbr")
        if op.get("fbr_number"):
            try:
                n = conn.record(self.b, d, op["fbr_number"])
            except SyncError as e:
                return f"Couldn't: {e}"
            doc = DOCS.make(self.b, self.b.doc(d["id"]), self.folder / "documents")
            return f"Recorded FBR invoice number {n} for {d['number']}; the PDF now shows it with its QR code: {doc['pdf']}"
        if (d.get("links") or {}).get("fbr"):
            return f"{d['number']} is already with FBR as {d['links']['fbr']}."
        ok, where = conn.ready()
        if not ok:
            return where + "."
        try:
            v = conn.validate(self.b, d)
        except SyncError as e:
            return f"Couldn't check it with FBR: {e}"
        if not v["ok"]:
            return f"{d['number']} is not ready for FBR: " + "; ".join(v["problems"]) + "."
        self.state["pending"] = {"op": "fbr", "number": d["number"], "again": bool(op.get("again"))}
        return (f"FBR checked {d['number']} ({(d.get('party') or {}).get('name', '')}, {rs(d['total'])}) on {where}: valid. Say 'yes' to post it: FBR then "
                "issues its number, printed on the invoice with its QR code; after that it can be changed only in FBR's system, within 72 hours.")

    def do_fbr(self, p):
        from ai_pc.accounts.systems import SyncError
        d = self.b.doc_by_number(p["number"])
        try:
            n = self._conn("fbr").post(self.b, d, again=p.get("again"))
        except SyncError as e:
            return f"Not posted: {e}"
        doc = DOCS.make(self.b, self.b.doc(d["id"]), self.folder / "documents")
        bad = [c for c in doc["checks"] if not c["ok"]]
        return f"Posted to FBR: {d['number']} is FBR invoice {n}. PDF with FBR's number and QR code: {doc['pdf']}" + \
            (" (checked)." if not bad else " NOT right: " + "; ".join(c["what"] for c in bad))

    # ---------------------------------------------------------------- reports
    def op_report(self, op):
        w = op.get("what")
        today = dt.date.today()
        per = op.get("period") or {}
        if w == "owed" or w == "owing":
            a = R.ageing(self.b, "receivable" if w == "owed" else "payable")
            if not a["rows"]:
                return "Nobody owes you anything." if w == "owed" else "You owe nothing."
            head = f"{'Owed to you' if w == 'owed' else 'You owe'}: {rs(a['total'])}"
            rows = [f"- {r['party']}: {rs(r['total'])}" + (" (" + ", ".join(f"{rs(r[k])} {k} days" for k in a["buckets"] if r[k]) + ")") +
                    (f", {r['phone']}" if r.get("phone") else "") for r in a["rows"][:15]]
            return head + "\n" + "\n".join(rows)
        if w == "profit":
            s = per.get("start") or today.replace(day=1).isoformat()
            e = per.get("end") or today.isoformat()
            pl = R.profit_loss(self.b, s, e)
            ex = ", ".join(f"{x['name']} {rs(x['amount'])}" for x in sorted(pl["expenses"], key=lambda x: -x["amount"])[:5])
            return (f"{s} to {e}: sales {rs(pl['sales'])}, cost of goods {rs(pl['cogs'])}, gross profit {rs(pl['gross'])}; expenses {rs(pl['total_expenses'])}" +
                    (f" ({ex})" if ex else "") + f"; net {'profit' if pl['net'] >= 0 else 'LOSS'} {rs(abs(pl['net']))}.")
        if w == "balance_sheet":
            bs = R.balance_sheet(self.b)
            return (f"As of {bs['upto']}: assets {rs(bs['total_assets'])} = liabilities {rs(bs['total_liabilities'])} + equity {rs(bs['total_equity'])}"
                    f" ({'balanced' if bs['balanced'] else 'NOT balanced'}).\n" + "\n".join(f"- {x['name']}: {rs(x['amount'])}" for x in bs["assets"] + bs["liabilities"]))
        if w == "trial_balance":
            tb = R.trial_balance(self.b)
            return f"Trial balance: debits {rs(tb['debit'])}, credits {rs(tb['credit'])} ({'balanced' if tb['balanced'] else 'NOT balanced'}).\n" + \
                "\n".join(f"- {r['code']} {r['name']}: " + (f"Dr {rs(r['debit'])}" if r["debit"] else f"Cr {rs(r['credit'])}") for r in tb["rows"])
        if w == "sales_tax":
            s = per.get("start") or today.replace(day=1).isoformat()
            e = per.get("end") or today.isoformat()
            st = R.sales_tax(self.b, s, e)
            due = st["payable"]
            return (f"Sales tax {s} to {e}: output tax {rs(st['output_tax'])} on {len(st['sales'])} invoices" + (f", further tax {rs(st['further_tax'])}" if st["further_tax"]
                                                                                                                  else "") +
                    f"; input tax {rs(st['input_tax'])} on {len(st['purchases'])} purchases; " +
                    (f"payable {rs(due)}." if due >= 0 else f"{rs(-due)} more input tax than output: carried forward."))
        if w == "stock":
            s = R.stock(self.b)
            rows = [r for r in s["rows"] if not op.get("item") or r["item"].lower() == op["item"].lower()]
            if not rows:
                return "No stock is counted yet (items marked 'stock')."
            return "\n".join(f"- {r['item']}: {r['qty']} {r['unit']} at {rs(r['avg_cost'])} = {rs(r['value'])}" + (" (LOW)" if r["low"] else "") for r in rows) + \
                (f"\nTotal stock value {rs(s['value'])}." if not op.get("item") else "")
        if w == "statement":
            p = self.b.find_party(op.get("party") or "")
            if not p:
                return "Whose statement? e.g. 'statement for Ali Traders'."
            st = R.statement(self.b, p, per.get("start"), per.get("end"))
            return f"{p['name']}: opening {rs(st['opening'])}\n" + "\n".join(f"- {r['date']} {r['number']}: " + (f"+{rs(r['debit'])}" if r["debit"] else f"-{rs(r['credit'])}") +
                                                                         f" = {rs(abs(r['balance']))}" for r in st["rows"]) + f"\nBalance {rs(st['closing'])}."
        if w == "day_book":
            s = per.get("start") or today.isoformat()
            e = per.get("end") or today.isoformat()
            rows = R.day_book(self.b, s, e)
            return f"{len(rows)} entries {s} to {e}:\n" + "\n".join(f"- {r['date']} {r['memo']}: {rs(sum(x['debit'] for x in r['lines']))}" for r in rows[-20:])
        return "Which report? e.g. 'who owes me money?', 'profit this month', 'sales tax for september', 'stock', 'statement for Ali Traders'."

    def _checks(self):
        problems = R.verify(self.b)
        return "Books checked: debits = credits, the balance sheet balances, stock agrees." if not problems else "BOOKS CHECK FAILED: " + "; ".join(problems[:3])
