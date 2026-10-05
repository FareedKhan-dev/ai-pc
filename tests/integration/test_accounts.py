"""Accounts lane: the books (double entry, exact money, Pakistan's sales tax), documents, the rules that read requests,
and the chat, with every expected figure worked out by hand.

  .venv\\Scripts\\python.exe tests\\integration\\test_accounts.py
No network and no keys; everything is written under out\\_tests\\accounts.
"""
import datetime as dt
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_pc.accounts import documents as DOCS  # noqa: E402
from ai_pc.accounts import reports as R  # noqa: E402
from ai_pc.accounts.accountsparse import parse  # noqa: E402
from ai_pc.accounts.ledger import Books, BooksError, fy_of  # noqa: E402
from ai_pc.accounts.money import pct, rs, to_paisa, words  # noqa: E402

OUT = ROOT / "out" / "_tests" / "accounts"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f"\n     why: {str(detail)[:600]}"))


def money():
    check("money: amounts as people write them", [to_paisa(x) for x in ("1,97,200.50", "Rs 85,000", "2.5 lakh", "1 crore", "Rs. 3,500/-", "12k")] ==
          [19720050, 8500000, 25000000, 1000000000, 350000, 1200000])
    check("money: tax rounded half up to the paisa, once per line", pct(333, 18) == 60 and pct(8500000, 18) == 1530000 and pct(25, 18) == 5)
    check("money: Pakistani grouping on request, international by default", rs(12345678900, grouping="lakh") == "Rs 12,34,56,789" and rs(12345678900) == "Rs 123,456,789")
    check("money: amounts in words with lakh and crore", words(19720050) == "Rupees One Lakh Ninety-Seven Thousand Two Hundred and Fifty Paisa Only"
          and words(12345678900) == "Rupees Twelve Crore Thirty-Four Lakh Fifty-Six Thousand Seven Hundred Eighty-Nine Only")
    check("money: Pakistan's fiscal year runs July to June", (fy_of("2026-07-01"), fy_of("2027-06-30"), fy_of("2026-06-30")) == ("26-27", "26-27", "25-26"))


def books():
    b = Books(OUT / "books.db")
    b.setup(name="Khan Electronics", ntn="1234567-8", strn="3277876123456", default_tax="18", further_tax="4", terms=15, address="Shop 12, Hall Road, Lahore",
            phone="042-111-000-111", bank="Meezan Bank, Khan Electronics, PK36MEZN0001234567890123")
    b.opening(cash="50,000", bank="5 lakh", capital=True, date="2026-07-01")
    b.item("LED TV 55", rate="85,000", cost="70,000", tax="18", stock=True, hs_code="8528.7200")
    b.item("Wall Mount", rate="3,500", tax="18")
    b.item("Installation", rate="2,000", kind="service", tax="16")
    b.party("Haier Pakistan", "supplier", strn="1111111111111")
    b.party("Ali Traders", "customer", strn="2222222222222", ntn="7654321-0", phone="0300-1234567", address="45 Main Boulevard, Gulberg, Lahore")
    b.party("Walk-in Customer", "customer")
    bill = b.bill("Haier Pakistan", [{"item": "LED TV 55", "qty": 10, "rate": "70,000"}], date="2026-07-05", due_days=30, ref="HP-778")
    check("bill: 10 TVs at 70,000 + 18% = 826,000; the input tax kept to claim", bill["total"] == 82600000 and bill["totals"]["tax"] == 12600000)
    inv = b.invoice("Ali Traders", [{"item": "LED TV 55", "qty": 2}, {"item": "Wall Mount", "qty": 2}, {"item": "Installation", "qty": 2}], date="2026-07-10")
    t = inv["totals"]
    check("invoice: lines priced from the items, tax per line (18% goods, 16% service): 181,000 + 32,500 = 213,500", (t["subtotal"], t["tax"], t["total"]) ==
          (18100000, 3250000, 21350000), t)
    check("invoice: numbered INV/26-27/0001, due after the 15-day terms", inv["number"] == "INV/26-27/0001" and inv["due"] == "2026-07-25")
    check("invoice: a registered buyer pays no further tax", t["further_tax"] == 0)
    inv2 = b.invoice("Walk-in Customer", [{"item": "LED TV 55", "qty": 1}], date="2026-07-12")
    check("invoice: an unregistered buyer pays 4% further tax (85,000 -> 3,400)", inv2["totals"]["further_tax"] == 340000 and inv2["total"] == 10370000)
    check("invoice: selling stock books its cost (2 x 70,000) and takes it out of stock", b.on_hand(inv["lines"][0]["item_id"])[0] == 7
          and inv["lines"][0]["cost"] == 14000000)
    r = b.receipt("Ali Traders", "1,50,000", withheld="4,000", date="2026-07-20")
    d = b.doc(inv["id"])
    check("receipt: 150,000 + 4,000 tax the customer withheld settle 154,000 of the invoice", d["paid"] == 15400000 and d["balance"] == 5950000
          and d["state"] in ("partly paid", "overdue") and r["total"] == 15400000, (d["paid"], d["state"]))
    b.expense("electricity bill", "25,000", paid_from="bank", date="2026-07-25")
    b.payment("Haier Pakistan", "4 lakh", date="2026-07-28")
    cn = b.credit_note(inv["number"], [{"item": "Wall Mount", "qty": 1}], date="2026-07-29", reason="one mount returned")
    check("credit note: one mount back: 3,500 + 630 tax = 4,130 off what Ali Traders owes", cn["total"] == 413000 and b.doc(inv["id"])["balance"] == 5537000)
    pl = R.profit_loss(b, "2026-07-01", "2026-07-31")
    check("profit and loss: sales 262,500, cost of goods 210,000, gross 52,500, electricity 25,000, net 27,500",
          (pl["sales"], pl["cogs"], pl["gross"], pl["net"]) == (26250000, 21000000, 5250000, 2750000), pl)
    bs = R.balance_sheet(b, "2026-07-31")
    check("balance sheet: assets 1,054,070 = liabilities + equity", bs["balanced"] and bs["total_assets"] == 105407000, bs["total_assets"])
    check("trial balance balances", R.trial_balance(b)["balanced"])
    st = R.stock(b)
    check("stock: 7 TVs at 70,000 = 490,000, the same as the Stock account", st["value"] == 49000000 == b.balance("1200"))
    tx = R.sales_tax(b, "2026-07-01", "2026-07-31")
    check("sales tax: output 47,170, further 3,400, input 126,000: 75,430 carried forward", (tx["output_tax"], tx["further_tax"], tx["input_tax"], tx["payable"]) ==
          (4717000, 340000, 12600000, -7543000), tx)
    ag = R.ageing(b, "receivable", dt.date(2026, 9, 15))
    check("ageing: who owes what, by how long", [(r["party"], r["total"]) for r in ag["rows"]] == [("Walk-in Customer", 10370000), ("Ali Traders", 5537000)]
          and ag["rows"][0]["31-60"] == 10370000)
    s = R.statement(b, "Ali Traders")
    check("statement: invoice, receipt and credit note with a running balance", [x["number"] for x in s["rows"]] == ["INV/26-27/0001", "RCV/26-27/0001",
                                                                                                                       "CN/26-27/0001"] and s["closing"] == 5537000)
    check("the books' own checks all pass", R.verify(b) == [], R.verify(b))
    v = b.void(inv2["number"], "entered twice")
    check("void: a reversing entry; the number stays, marked void; the TV is back in stock", v["status"] == "void" and b.on_hand(inv["lines"][0]["item_id"])[0] == 8
          and R.verify(b) == [])
    inv3 = b.invoice("Walk-in Customer", [{"item": "Wall Mount", "qty": 1}], date="2026-07-30")
    check("numbers run on without gaps after a void (INV/26-27/0003)", inv3["number"] == "INV/26-27/0003")
    try:
        b.void(inv["number"])
        check("void: an invoice with payments against it cannot be voided (credit note instead)", False)
    except BooksError as e:
        check("void: an invoice with payments against it cannot be voided (credit note instead)", "credit note" in str(e))
    n_before = b.cx.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    try:
        b.journal([("1000", "1,000", 0), ("4900", 0, "900")], memo="wrong")
        check("an entry that does not balance is refused and nothing is saved", False)
    except BooksError:
        check("an entry that does not balance is refused and nothing is saved", b.cx.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == n_before
              and R.verify(b) == [])
    try:
        b.invoice("Ali Traders", [{"item": "LED TV 55", "qty": 50}])
        check("selling more stock than there is is refused (record the purchase first)", False)
    except BooksError as e:
        check("selling more stock than there is is refused (record the purchase first)", "only 8" in str(e) and R.verify(b) == [], str(e))
    q = b.quote("Ali Traders", [{"item": "LED TV 55", "qty": 3, "rate": "84,000"}], date="2026-07-31", valid_days=7)
    check("quotation: priced and numbered, no entry in the books", q["number"] == "QUO/26-27/0001" and q["total"] == 29736000 and
          b.cx.execute("SELECT COUNT(*) FROM journal WHERE doc_id=?", (q["id"],)).fetchone()[0] == 0)
    b.receipt("Walk-in Customer", "500,000", date="2026-08-01")
    check("a payment larger than what is owed settles everything and leaves an advance", b.doc(inv3["id"])["state"] == "paid" and R.verify(b) == [])
    return b, inv, cn, q


def documents(b, inv, cn, q):
    for d in (b.doc(inv["id"]), b.doc_by_number("RCV/26-27/0001"), b.doc(cn["id"]), b.doc(q["id"])):
        r = DOCS.make(b, d, OUT / "documents")
        bad = [c for c in r["checks"] if not c["ok"]]
        check(f"document: {d['number']} as PDF, read back: " + ", ".join(c["what"] for c in r["checks"][:3]), not bad and Path(r["pdf"]).exists(), bad)
    h = DOCS.html_for(b, b.doc(inv["id"]))
    check("document: a sales tax invoice shows NTN, STRN, the buyer's STRN, HS code, value excluding tax, the rate and the tax",
          all(x in h for x in ("SALES TAX INVOICE", "NTN: 1234567-8", "STRN: 3277876123456", "STRN: 2222222222222", "HS code 8528.7200", "Value excl. tax",
                               "18%", "30,600")))
    check("document: dates as people write them (10 Jul 2026)", "10 Jul 2026" in h)
    d2 = dict(b.doc(inv["id"]), fbr_invoice="1234567ABCD20260710123456")
    h2 = DOCS.html_for(b, d2)
    check("document: an FBR digital invoice number is printed with its QR code", "FBR Digital Invoicing System" in h2 and "1234567ABCD20260710123456" in h2
          and "data:image/svg+xml;base64," in h2 and "width:1in" in h2)


PHRASES = [
    ("make an invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 2 wall mounts at 3,500, installation 2,000, 18% tax, due in 15 days",
     lambda o: o["op"] == "invoice" and o["party"] == "Ali Traders" and [(x["item"], x["qty"], x.get("rate"), x["tax"]) for x in o["lines"]] ==
     [("LED TV 55", "2", "85,000", "18"), ("Wall Mount", "2", "3,500", "18"), ("Installation", "1", "2,000", "18")] and o["due_days"] == 15),
    ("quotation for Ahmed Electronics: 5 LED TV 55 at 82,000 each, valid for 7 days", lambda o: o["op"] == "quote" and o["party"] == "Ahmed Electronics"
     and o["valid_days"] == 7),
    ("invoice Ali Traders 1 LED TV 55 and 1 wall mount", lambda o: [(x["item"], x.get("rate")) for x in o["lines"]] == [("LED TV 55", None), ("Wall Mount", None)]),
    ("invoice Bilal Stores for 3 LED TV 65", lambda o: o["party"] == "Bilal Stores" and o["lines"][0]["item"] == "LED TV 65"),
    ("Invoice for M/s Rehman Brothers: 3 x LED TV 55 @ 85000, less 5% discount, due on 25 october",
     lambda o: o["party"] == "Rehman Brothers" and o["lines"][0]["discount"] == "5%" and o["due_days"] == 21 and o["date"] is None),
    ("sales tax invoice to Ali Traders: 10 kg copper wire at 2,400 per kg, 18% tax", lambda o: o["lines"][0] == {"rate": "2,400", "unit": "kg", "qty": "10",
                                                                                                                 "item": "copper wire", "tax": "18"}),
    ("make an invoice for Zubair & Sons: consultancy 50,000 (16% tax), travel 8,000 no tax", lambda o: [(x["item"], x["tax"]) for x in o["lines"]] ==
     [("consultancy", "16"), ("travel", "0")]),
    ("invoice for Ali Traders: 2 iPhone 15 at 3,20,000, installation 500", lambda o: [(x["item"], x.get("rate")) for x in o["lines"]] ==
     [("iPhone 15", "3,20,000"), ("Installation", "500")]),
    ("invoice for Ali Traders dated 10 july: 2 LED TV 55", lambda o: o["date"] == "2026-07-10"),
    ("Ali Traders paid us 1.5 lakh by bank and deducted 4,000 income tax", lambda o: o == {"op": "receipt", "party": "Ali Traders", "amount": "1.5 lakh", "bank": True,
                                                                                          "withheld": "4,000", "against": None, "date": None}),
    ("received 50,000 from Walk-in Customer in cash", lambda o: o["op"] == "receipt" and o["bank"] is False),
    ("paid Haier Pakistan 4 lakh by cheque", lambda o: o["op"] == "payment" and o["party"] == "Haier Pakistan" and o["amount"] == "4 lakh"),
    ("paid electricity bill 25,000 from bank", lambda o: o["op"] == "expense" and o["paid_from"] == "bank" and o["amount"] == "25,000"),
    ("spent 3,000 on fuel", lambda o: o["op"] == "expense" and o["what"] == "fuel"),
    ("bought 10 LED TV 55 from Haier Pakistan at 70,000 each plus 18% tax, bill no HP-778, due in 30 days",
     lambda o: o["op"] == "bill" and o["ref"] == "HP-778" and o["lines"][0] == {"rate": "70,000", "qty": "10", "item": "LED TV 55", "tax": "18"} and o["due_days"] == 30),
    ("Ali Traders returned 1 wall mount from invoice 1", lambda o: o["op"] == "credit_note" and o["invoice"] == "1" and o["lines"][0]["item"] == "Wall Mount"),
    ("cancel invoice 2 because entered twice", lambda o: o == {"op": "void", "kind": "invoice", "ref": "2", "reason": "entered twice"}),
    ("show invoice 1", lambda o: o == {"op": "show", "kind": "invoice", "ref": "1"}),
    ("email invoice 1 to ali@alitraders.pk", lambda o: o["op"] == "email" and o["to"] == "ali@alitraders.pk"),
    ("who owes me money?", lambda o: o == {"op": "report", "what": "owed"}),
    ("what do I owe?", lambda o: o == {"op": "report", "what": "owing"}),
    ("profit for july", lambda o: o["what"] == "profit" and o["period"] == {"start": "2026-07-01", "end": "2026-07-31"}),
    ("sales tax for september", lambda o: o["what"] == "sales_tax" and o["period"]["start"] == "2026-09-01"),
    ("how many LED TV 55 left?", lambda o: o == {"op": "report", "what": "stock", "item": "LED TV 55"}),
    ("statement for Ali Traders", lambda o: o["what"] == "statement" and o["party"] == "Ali Traders"),
    ("my business is Khan Electronics, NTN 1234567-8, STRN 3277876123456, phone 042-111000111",
     lambda o: o["op"] == "setup" and o["name"] == "Khan Electronics" and o["strn"] == "3277876123456"),
    ("add item LED TV 65 price 1,40,000 cost 1,15,000 18% tax stock", lambda o: o["op"] == "item" and o["name"] == "LED TV 65" and o["stock"] is True),
    ("add customer Bilal Stores NTN 1112223-4 phone 0321-7654321", lambda o: o["op"] == "party" and o["name"] == "Bilal Stores" and o["phone"] == "0321-7654321"),
    ("opening balances cash 50,000 bank 5 lakh", lambda o: o == {"op": "opening", "cash": "50,000", "bank": "5 lakh"}),
    ("send invoice 1 to quickbooks", lambda o: o["op"] == "sync" and o["system"] == "quickbooks" and o["ref"] == "1"),
    ("sync everything to tally", lambda o: o["op"] == "sync" and o["system"] == "tally" and o["all"]),
    ("turn quote 3 into an invoice", lambda o: o == {"op": "convert", "ref": "3"}),
    ("we sell the LED TV 55 for 85,000, it costs us 70,000, 18% tax, keep a stock count",
     lambda o: o["op"] == "item" and o["name"] == "LED TV 55" and o["rate"] == "85,000" and o["cost"] == "70,000" and o["tax"] == "18" and o["stock"] is True),
    ("got 10 LED TV 55 from Haier Pakistan at 70k each with 18% tax", lambda o: o["op"] == "bill" and o["party"] == "Haier Pakistan"
     and o["lines"][0] == {"rate": "70k", "qty": "10", "item": "LED TV 55", "tax": "18"}),
    ("bill Ali Traders for 2 of the LED TV 55 at 85,000 each plus tax, payment in 2 weeks",
     lambda o: o["op"] == "invoice" and o["lines"][0]["rate"] == "85,000" and o["lines"][0]["qty"] == "2" and o["due_days"] == 14),
    ("stock", lambda o: o == {"op": "report", "what": "stock", "item": None}),
]


def phrases():
    ctx = {"parties": ["Ali Traders", "Haier Pakistan", "Walk-in Customer"], "items": ["LED TV 55", "LED TV 65", "Wall Mount", "Installation"],
           "now": dt.datetime(2026, 10, 4, 12)}
    bad = []
    for text, ok in PHRASES:
        r = parse(text, ctx)
        try:
            good = bool(r["ops"]) and ok(r["ops"][0])
        except Exception:  # noqa: BLE001
            good = False
        if not good:
            bad.append((text, r["ops"] or r["ask"]))
    check(f"rules: {len(PHRASES) - len(bad)}/{len(PHRASES)} everyday requests read without the model", not bad, bad)


def chat():
    from ai_pc.accounts.accountschat import AccountsChat
    db = OUT / "chat.db"
    for f in OUT.glob("chat.db*"):
        f.unlink()
    ac = AccountsChat.start(chats_dir=OUT / "chats", db=db)
    r = ac.say("my business is Khan Electronics, NTN 1234567-8, STRN 3277876123456, address Shop 12 Hall Road Lahore, phone 042-111000111")
    check("chat: the business set up, what is still missing said", r.startswith("Saved:") and "Still missing" not in r, r)
    ac.say("set sales tax to 18%")
    ac.say("add item LED TV 55 price 85,000 cost 70,000 18% tax stock")
    ac.say("add customer Ali Traders NTN 7654321-0 STRN 2222222222222 phone 0300-1234567")
    r = ac.say("bought 10 LED TV 55 from Haier Pakistan at 70,000 each plus 18% tax, bill no HP-778")
    check("chat: a purchase previewed first (new supplier said)", r.startswith("Bill from Haier Pakistan (new: added as a supplier)") and "826,000" in r, r)
    r = ac.say("yes")
    check("chat: then saved, its input tax noted, the books checked", "BILL/" in r and "input tax Rs 126,000" in r and "Books checked" in r, r)
    r = ac.say("invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 1 installation at 2,000 (16% tax), due in 15 days")
    check("chat: an invoice previewed with its lines, tax, total in words and stock left", "LED TV 55: 2 pcs x 85,000 = 170,000 + 18% tax 30,600" in r and
          "Rupees" in r and "8 left after this" in r and r.endswith("'due in 30 days')."), r)
    r = ac.say("make the TV 84,000")
    check("chat: changed in words before saving", "LED TV 55: 2 pcs x 84,000 = 168,000" in r, r)
    r = ac.say("yes")
    check("chat: saved, PDF made and checked, books checked", "Invoice INV/" in r and ".pdf" in r and "checked:" in r and "Books checked" in r, r)
    r = ac.say("Ali Traders paid us 1 lakh by bank")
    check("chat: a receipt previewed: what it settles, what stays owed", r.startswith("Ready to record Rs 100,000 received from Ali Traders") and "settles INV/" in r, r)
    r = ac.say("yes")
    check("chat: the receipt saved with its PDF", "Receipt RCV/" in r and "now owes" in r, r)
    r = ac.say("paid electricity bill 25,000 from bank")
    check("chat: an expense goes to its account (Electricity and Utilities)", "Electricity and Utilities" in r, r)
    ac.say("yes")
    r = ac.say("who owes me money?")
    check("chat: who owes what", "Ali Traders" in r and "Owed to you" in r, r)
    r = ac.say("profit this month")
    check("chat: profit with the cost of goods taken off", "gross profit" in r and "net" in r, r)
    r = ac.say("how many LED TV 55 left?")
    check("chat: stock left", "LED TV 55: 8 pcs" in r, r)
    r = ac.say("undo")
    check("chat: undo offers to cancel the last entry (shown first)", r.startswith("Ready to cancel EXP/"), r)
    r = ac.say("yes")
    check("chat: and cancels it with a reversing entry", "is void" in r and "Books checked" in r, r)
    r = ac.say("invoice for Ali Traders: 500 LED TV 55")
    check("chat: more than in stock is warned in the preview", "only 8" in r and "record the purchase first" in r, r)
    r = ac.say("yes")
    check("chat: and refused when confirmed, nothing saved", r.startswith("Couldn't:") and "only 8" in r, r)
    ac.b.close()


def main():
    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    money()
    b, inv, cn, q = books()
    documents(b, inv, cn, q)
    phrases()
    b.close()
    chat()
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not bad else f'{len(bad)} FAILED'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)}, {time.time() - t0:.0f} s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
