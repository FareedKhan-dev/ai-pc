"""Accounts lane, part 2: the books kept in step with the accounting software people use, each against a fake of its
real API (tests/accounts_fakes.py): everything goes once and in the right order, the totals there match the books, a
lost answer or a failure part-way never makes anything twice, an expired sign-in is renewed, a limit stops the run,
and a document cancelled here is cancelled there.

  .venv\\Scripts\\python.exe tests\\test_accounts_systems.py
No network and no keys; everything is written under out\\_tests\\accounts_systems.
"""
import shutil
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from decimal import Decimal as DD  # noqa: E402

import harness.hub.http as H  # noqa: E402
from accounts_fakes import FakeFbr, FakeQbo, FakeTally, FakeXero, FakeZoho  # noqa: E402
from harness.accounts import documents as DOCS  # noqa: E402
from harness.accounts import fbr  # noqa: E402
from harness.accounts import reports as R  # noqa: E402
from harness.accounts import systems as S  # noqa: E402
from harness.accounts.accountschat import AccountsChat  # noqa: E402
from harness.accounts.ledger import Books  # noqa: E402
from harness.accounts.systems import quickbooks, tally, xero, zoho  # noqa: E402

H.time = types.SimpleNamespace(sleep=lambda s: None)  # the hub's polite retries, without the waiting
OUT = ROOT / "out" / "_tests" / "accounts_systems"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f"\n     why: {str(detail)[:900]}"))


def build(path):
    """A month of a small electronics shop: a purchase, two sales (one to a buyer without an STRN), a quotation, money in
    with income tax withheld, an expense, a payment to the supplier, a return, and a receipt bigger than what was owed."""
    b = Books(path)
    b.setup(name="Khan Electronics", ntn="1234567-8", strn="3277876123456", default_tax="18", further_tax="4", terms=15,
            address="Shop 12, Hall Road, Lahore", province="Punjab")
    b.item("LED TV 55", rate="85,000", cost="70,000", tax="18", stock=True, hs_code="8528.7200")
    b.item("Wall Mount", rate="3,500", tax="18", hs_code="8302.5000")
    b.item("Installation", rate="2,000", kind="service", tax="16")
    b.party("Haier Pakistan", "supplier", strn="1111111111111", ntn="1111111-1")
    b.party("Ali Traders", "customer", strn="2222222222222", ntn="7654321-0", phone="0300-1234567", address="45 Main Boulevard, Gulberg, Lahore")
    b.party("Walk-in Customer", "customer")
    d = {"bill": b.bill("Haier Pakistan", [{"item": "LED TV 55", "qty": 10, "rate": "70,000"}], date="2026-07-05", due_days=30, ref="HP-778"),
         "inv1": b.invoice("Ali Traders", [{"item": "LED TV 55", "qty": 2}, {"item": "Wall Mount", "qty": 2, "discount": "10%"}, {"item": "Installation", "qty": 2}],
                           date="2026-07-10"),
         "inv2": b.invoice("Walk-in Customer", [{"item": "LED TV 55", "qty": 1}], date="2026-07-12"),
         "quote": b.quote("Ali Traders", [{"item": "LED TV 55", "qty": 3, "rate": "84,000"}], date="2026-07-13", valid_days=7),
         "rcv1": b.receipt("Ali Traders", "1,50,000", withheld="4,000", date="2026-07-20"),
         "exp": b.expense("electricity bill", "25,000", paid_from="bank", date="2026-07-25"),
         "pay": b.payment("Haier Pakistan", "4 lakh", date="2026-07-28")}
    d["cn"] = b.credit_note(d["inv1"]["number"], [{"item": "Wall Mount", "qty": 1}], date="2026-07-29")
    d["rcv2"] = b.receipt("Walk-in Customer", "5 lakh", date="2026-08-01")  # settles INV 2 (103,700) and leaves 396,300 as an advance
    return b, d


def scenario(b, d):
    t = (d["inv1"]["total"], d["inv2"]["total"], d["quote"]["total"], d["cn"]["total"], b.doc(d["inv1"]["id"])["balance"])
    check("the month: invoice 212,674 (10% off the mounts, 18%/16% tax), 103,700 with further tax, quote 297,360, return 3,717, 54,957 still owed",
          t == (21267400, 10370000, 29736000, 371700, 5495700), t)


def common(name, b, conn, res):
    check(f"{name}: all 9 documents go, each read back with the same total", len(res) == 9 and all(r["ok"] for r in res),
          [(r["number"], r["notes"]) for r in res if not r["ok"]])
    order = [r["number"] for r in res]
    check(f"{name}: invoices and bills first, then the return, then the money that settles them",
          order.index("CN/26-27/0001") > order.index("INV/26-27/0002") and order[-3:] == ["RCV/26-27/0001", "PAY/26-27/0001", "RCV/26-27/0002"], order)
    check(f"{name}: a second sync has nothing to send", S.sync_all(b, name, conn) == [] and S.pending(b, name, conn.kinds) == [])


# ==================================================================== Xero
def xero_tests():
    b, d = build(OUT / "xero.db")
    scenario(b, d)
    fx = FakeXero()
    check("xero: not connected says how to connect", xero.System({}, fx).ready() == (False, "Xero is not connected: 'accounts.py steps xero' shows how "
                                                                                       "(free, a few minutes)"))
    got = {}
    who = xero.finish("xero-client", "good-code", "http://localhost:3009/callback", "v" * 64, fx, store=got.update)
    check("xero: the sign-in's code becomes tokens and the organisation it allowed", who["who"] == "Khan Electronics" and got["tenant"] == "tenant-khan"
          and got["refresh_token"] == "xero-refresh-2", (who, got))
    conn = xero.System(dict(got), fx)
    res = S.sync_all(b, "xero", conn)
    common("xero", b, conn, res)
    inv1 = next(i for i in fx.invoices.values() if i["InvoiceNumber"] == "INV/26-27/0001")
    check("xero: INV/26-27/0001 there totals 212,674 and owes 54,957 after the receipt, the tax withheld and the return, as in the books",
          (inv1["Total"], inv1["AmountDue"]) == (212674.0, 54957.0), (inv1["Total"], inv1["AmountDue"]))
    inv2 = next(i for i in fx.invoices.values() if i["InvoiceNumber"] == "INV/26-27/0002")
    check("xero: further tax for a buyer without an STRN is its own line to 'Further Tax Payable'; the invoice is paid",
          any(x["Description"].startswith("Further tax") and x["AccountCode"] == "2110" for x in inv2["LineItems"]) and inv2["Total"] == 103700.0
          and inv2["Status"] == "PAID", inv2)
    check("xero: sales tax 18% and 16% made once as tax rates (the 5% imports rate left alone)",
          sorted(t["Name"] for t in fx.taxrates if t["TaxType"].startswith("TAX0")) == ["Sales Tax 16%", "Sales Tax 18%"], fx.taxrates)
    wht = [p for p in fx.payments.values() if p["Reference"] == "RCV/26-27/0001 WHT"]
    check("xero: income tax the customer withheld is a payment from 'Income Tax Deducted by Customers'", len(wht) == 1 and wht[0]["Amount"] == 4000.0
          and wht[0]["Account"] == {"Code": "1310"}, wht)
    adv = [x for x in fx.banktx.values() if x["Type"] == "RECEIVE-PREPAYMENT"]
    check("xero: money beyond what was owed stays as the customer's advance (a prepayment of 396,300)", len(adv) == 1 and adv[0]["Total"] == 396300.0, adv)
    exp = [x for x in fx.banktx.values() if x["Type"] == "SPEND"]
    check("xero: the electricity bill goes to 'Light, Power, Heating', paid from the bank account", len(exp) == 1 and exp[0]["LineItems"][0]["AccountCode"] == "445"
          and exp[0]["BankAccount"] == {"AccountID": "bank-meezan"}, exp)
    bill = next(i for i in fx.invoices.values() if i["Type"] == "ACCPAY")
    check("xero: the bill keeps the supplier's number (HP-778) and our reference; 426,000 left to pay", bill["InvoiceNumber"] == "HP-778"
          and bill["Reference"] == "BILL/26-27/0001" and bill["AmountDue"] == 426000.0, bill)
    cn = next(iter(fx.credits.values()))
    check("xero: the return is a credit note of 3,717 allocated to its invoice", cn["Total"] == 3717.0 and cn["RemainingCredit"] == 0.0, cn)
    q = next(iter(fx.quotes.values()))
    check("xero: the quotation keeps its number and total", q["QuoteNumber"] == "QUO/26-27/0001" and q["Total"] == 297360.0, q)
    creates = [r for r in fx.sent if r["method"] in ("PUT", "POST") and "/api.xro/" in r["url"]]
    check("xero: every create carried an Idempotency-Key and the tenant", creates and all(r["headers"].get("Idempotency-Key") and
                                                                                          r["headers"].get("Xero-tenant-id") == "tenant-khan" for r in creates))
    # an answer lost once: the hub retries the same call with the same key, Xero replays its answer
    r3 = b.receipt("Ali Traders", "10,000", date="2026-08-02")
    fx.failing("PUT", "/Payments", "drop", times=1)
    res = S.sync_all(b, "xero", conn)
    pays = [p for p in fx.payments.values() if p["Reference"] == r3["number"]]
    check("xero: an answer lost once: the retry carries the same Idempotency-Key, Xero replays it, one payment", res and res[0]["ok"] and len(pays) == 1
          and fx.replays == 1, (res, len(pays), fx.replays))
    # no answer on any try: the next sync finds it by its reference
    r4 = b.receipt("Ali Traders", "5,000", date="2026-08-03")
    fx.failing("PUT", "/Payments", "drop", times=4)
    res = S.sync_all(b, "xero", conn)
    check("xero: no answer at all: the run stops, saying Xero could not be reached", len(res) == 1 and not res[0]["ok"] and res[0]["kind"] == "offline", res)
    res = S.sync_all(b, "xero", conn)
    pays = [p for p in fx.payments.values() if p["Reference"] == r4["number"]]
    check("xero: next time it is found there by its reference: linked, not sent again", res and res[0]["ok"] and len(pays) == 1
          and any("not sent again" in x for x in res[0]["notes"]), res)
    b.void(r4["number"], "entered twice")
    res = S.sync_all(b, "xero", conn)
    check("xero: a receipt cancelled here is deleted there, and the invoice owes it again (44,957)", res and res[0]["ok"] and pays[0]["Status"] == "DELETED"
          and inv1["AmountDue"] == 44957.0 and b.doc(d["inv1"]["id"])["balance"] == 4495700, (res, inv1["AmountDue"]))
    conn.creds["expires_at"] = 0
    b.expense("internet bill", "3,000", paid_from="bank", date="2026-08-04")
    res = S.sync_all(b, "xero", conn)
    check("xero: an expired sign-in is renewed and the new (rotated) refresh token kept; internet goes to 'Telephone & Internet'",
          res and res[0]["ok"] and conn.creds["refresh_token"] == fx.refresh == "xero-refresh-3"
          and any(x["LineItems"][0]["AccountCode"] == "489" for x in fx.banktx.values()), res)
    b.expense("shop rent", "40,000", paid_from="bank", date="2026-08-05")
    fx.failing("PUT", "/BankTransactions", "429", times=4)
    res = S.sync_all(b, "xero", conn)
    check("xero: today's API limit stops the run with a clear message", len(res) == 1 and res[0]["kind"] == "limit" and "limit" in res[0]["notes"][0], res)
    res = S.sync_all(b, "xero", conn)
    check("xero: and the next run sends it (rent to 'Rent')", res and res[0]["ok"] and any(x["LineItems"][0]["AccountCode"] == "469" for x in fx.banktx.values()))
    check("xero: the books' own checks still pass", R.verify(b) == [], R.verify(b))
    b.close()


# ==================================================================== Zoho Books
def zoho_tests():
    b, d = build(OUT / "zoho.db")
    fz = FakeZoho()
    got = {}
    who = zoho.connect({"client_id": "zoho-client", "client_secret": "zoho-secret", "code": "good-code"}, fz, store=got.update)
    check("zoho: the Self Client's code becomes a refresh token; the organisation is found", who["who"] == "Khan Electronics" and got["org"] == "org-khan"
          and got["refresh_token"] == "zoho-refresh-1" and got["api"] == "https://www.zohoapis.com", (who, got))
    try:
        zoho.connect({"client_id": "zoho-client", "client_secret": "zoho-secret", "code": "good-code"}, fz, store=lambda c: None)
        check("zoho: a code used twice is refused, with what to do", False)
    except S.SyncError as e:
        check("zoho: a code used twice is refused, with what to do", e.kind == "auth" and "generate a new code" in str(e), e)
    conn = zoho.System(dict(got), fz)
    res = S.sync_all(b, "zoho", conn)
    common("zoho", b, conn, res)
    docs = fz.docs
    inv1 = next(x for x in docs["invoices"].values() if x["invoice_number"] == "INV/26-27/0001")
    check("zoho: INV/26-27/0001 keeps our number, is marked sent, totals 212,674 and owes 54,957", (inv1["total"], inv1["balance"], inv1["status"]) ==
          (212674.0, 54957.0, "sent"), (inv1["total"], inv1["balance"], inv1["status"]))
    inv2 = next(x for x in docs["invoices"].values() if x["invoice_number"] == "INV/26-27/0002")
    group = next((t for t in fz.taxes if t["tax_type"] == "tax_group"), {})
    check("zoho: further tax rides in a tax group 'Sales Tax 18% + Further Tax 4%' (both stay tax); the invoice is paid",
          group.get("tax_name") == "Sales Tax 18% + Further Tax 4%" and inv2["line_items"][0]["tax_id"] == group.get("tax_id") and inv2["total"] == 103700.0
          and inv2["status"] == "paid", (group, inv2.get("total"), inv2.get("status")))
    est = next(iter(docs["estimates"].values()))
    bill = next(iter(docs["bills"].values()))
    check("zoho: the quotation is an estimate (sent); the bill keeps HP-778, is open, 426,000 to pay", (est["estimate_number"], est["status"], est["total"]) ==
          ("QUO/26-27/0001", "sent", 297360.0) and (bill["bill_number"], bill["reference_number"], bill["status"], bill["balance"]) ==
          ("HP-778", "BILL/26-27/0001", "open", 426000.0), (est, bill))
    wht_acct = next(a for a in fz.chart if a["account_name"] == "Income Tax Deducted by Customers")
    wht = [p for p in docs["customerpayments"].values() if p["reference_number"] == "RCV/26-27/0001 WHT"]
    check("zoho: income tax withheld is a second payment into 'Income Tax Deducted by Customers' (made as an other current asset)",
          len(wht) == 1 and wht[0]["amount"] == 4000.0 and wht[0]["account_id"] == wht_acct["account_id"] and wht_acct["account_type"] == "other_current_asset")
    adv = next(p for p in docs["customerpayments"].values() if p["reference_number"] == "RCV/26-27/0002")
    check("zoho: money beyond what was owed stays as the customer's unused credit (396,300)", adv["unused_amount"] == 396300.0, adv)
    exp = next(iter(docs["expenses"].values()))
    acct = {a["account_id"]: a["account_name"] for a in fz.chart}
    check("zoho: the electricity bill goes to 'Utility Expense', paid through the bank", acct[exp["account_id"]] == "Utility Expense"
          and acct[exp["paid_through_account_id"]] == "HBL Current Account", exp)
    cn = next(iter(docs["creditnotes"].values()))
    check("zoho: the return is a credit note of 3,717 applied to its invoice", cn["total"] == 3717.0 and cn["balance"] == 0.0, cn)
    names = [c["contact_name"] for c in fz.contacts.values()]
    check("zoho: each customer and supplier made once, with NTN and STRN noted", sorted(names) == ["Ali Traders", "Haier Pakistan", "Walk-in Customer"]
          and any("STRN 2222222222222" in (c.get("notes") or "") for c in fz.contacts.values()), names)
    # the answer to the second payment (the tax withheld) is lost after Zoho saved it
    r3 = b.receipt("Ali Traders", "20,000", withheld="1,000", date="2026-08-02")
    fz.failing("POST", "/customerpayments", "drop", skip=1)
    res = S.sync_all(b, "zoho", conn)
    check("zoho: the second payment's answer is lost: the run stops (a create is never retried blindly)", len(res) == 1 and res[0]["kind"] == "offline", res)
    res = S.sync_all(b, "zoho", conn)
    pays = [p for p in docs["customerpayments"].values() if p["reference_number"].startswith(r3["number"])]
    check("zoho: next time the first payment is remembered and the second found by its mark: two payments, not three, 21,000",
          res and res[0]["ok"] and len(pays) == 2 and sum(p["amount"] for p in pays) == 21000.0, (res, pays))
    b.void(r3["number"])
    res = S.sync_all(b, "zoho", conn)
    check("zoho: cancelled here, both payments deleted there; the invoice owes 54,957 again", res and res[0]["ok"] and inv1["balance"] == 54957.0
          and not [p for p in docs["customerpayments"].values() if p["reference_number"].startswith(r3["number"])], (res, inv1["balance"]))
    conn.creds["expires_at"] = 0
    b.expense("internet bill", "3,000", paid_from="cash", date="2026-08-04")
    res = S.sync_all(b, "zoho", conn)
    check("zoho: an expired access token is renewed from the refresh token; cash goes through 'Petty Cash'",
          res and res[0]["ok"] and conn.creds["access_token"] == fz.access == "zoho-access-2"
          and any(acct.get(x["paid_through_account_id"]) == "Petty Cash" for x in docs["expenses"].values()), res)
    b.expense("shop rent", "40,000", paid_from="bank", date="2026-08-05")
    fz.failing("POST", "/expenses", "401", times=1)
    res = S.sync_all(b, "zoho", conn)
    check("zoho: a sign-in Zoho refuses stops the run and says to connect again", len(res) == 1 and res[0]["kind"] == "auth"
          and "connect zoho" in res[0]["notes"][0], res)
    check("zoho: the books' own checks still pass", R.verify(b) == [], R.verify(b))
    b.close()


# ==================================================================== TallyPrime
def tally_tests():
    b, d = build(OUT / "tally.db")
    ft = FakeTally()
    ft.down = True
    try:
        tally.connect({"company": "Khan Electronics"}, ft, store=lambda c: None)
        check("tally: TallyPrime not running: says to open it and turn its gateway on", False)
    except S.SyncError as e:
        check("tally: TallyPrime not running: says to open it and turn its gateway on", e.kind == "offline" and "turn its gateway on" in str(e), e)
    ft.down = False
    try:
        tally.connect({"company": "Khan Traders"}, ft, store=lambda c: None)
        check("tally: a company that is not open is named, with the ones that are", False)
    except S.SyncError as e:
        check("tally: a company that is not open is named, with the ones that are", "not open in TallyPrime" in str(e) and "Khan Electronics" in str(e), e)
    got = {}
    who = tally.connect({"company": "khan electronics"}, ft, store=got.update)
    check("tally: connected to the open company, its own spelling kept; no key", who["who"] == "Khan Electronics"
          and got == {"company": "Khan Electronics", "port": 9000, "host": "127.0.0.1"}, got)
    conn = tally.System(dict(got), ft)
    res = S.sync_all(b, "tally", conn)
    check("tally: 8 documents go (TallyPrime keeps no quotations), each read back from the Day Book with the same total",
          len(res) == 8 and all(r["ok"] for r in res), [(r["number"], r["notes"]) for r in res if not r["ok"]])
    check("tally: a second sync has nothing to send", S.sync_all(b, "tally", conn) == [])
    check("tally: every request went as UTF-16", all(r["body"][:2] == b"\xff\xfe" for r in ft.sent))
    inv1 = next(x for x in ft.vouchers.values() if "(AI PC INV/26-27/0001)" in x["NARRATION"])
    check("tally: a sale of stock is an item invoice: the TVs as stock, mounts and installation as ledger lines, 18% and 16% output tax",
          inv1["VIEW"] == "Invoice Voucher View" and [i["STOCKITEMNAME"] for i in inv1["INV"]] == ["LED TV 55"]
          and {ln["LEDGERNAME"] for ln in inv1["LINES"]} == {"Ali Traders", "Sales", "Service Income", "Output Sales Tax 18%", "Output Sales Tax 16%"},
          (inv1["VIEW"], [ln["LEDGERNAME"] for ln in inv1["LINES"]]))
    lines = [ln["LEDGERNAME"] for x in ft.vouchers.values() for ln in x["LINES"]]
    check("tally: their own ledgers are used and never altered (Ali Traders, HBL Current A/c, Electricity Charges)",
          not ft.altered_masters and "HBL Current A/c" in lines and "Electricity Charges" in lines, (ft.altered_masters, sorted(set(lines))))
    check("tally: bill by bill: Ali Traders owes 54,957 on INV/26-27/0001, Haier is owed 426,000 on HP-778, Walk-in has a 396,300 advance",
          ft.bills("Ali Traders") == {"INV/26-27/0001": DD("54957.00")} and ft.bills("Haier Pakistan") == {"HP-778": DD("-426000.00")}
          and ft.bills("Walk-in Customer") == {"RCV/26-27/0002": DD("-396300.00")},
          (ft.bills("Ali Traders"), ft.bills("Haier Pakistan"), ft.bills("Walk-in Customer")))
    check("tally: Tally numbered the vouchers itself (automatic numbering): ours is in the narration, and the person is told",
          inv1["VOUCHERNUMBER"] == "1" and any("Tally numbered it" in n for r in res for n in r["notes"]))
    r3 = b.receipt("Ali Traders", "10,000", date="2026-08-02")
    ft.failing("POST", "/", "drop", times=1)
    res = S.sync_all(b, "tally", conn)
    check("tally: the answer lost after Tally saved the receipt: the run stops", len(res) == 1 and res[0]["kind"] == "offline", res)
    res = S.sync_all(b, "tally", conn)
    same = [x for x in ft.vouchers.values() if f"(AI PC {r3['number']})" in x["NARRATION"]]
    check("tally: sent again with the same REMOTEID, Tally updates it: one voucher, not two", res and res[0]["ok"] and len(same) == 1, (res, len(same)))
    b.void(r3["number"])
    res = S.sync_all(b, "tally", conn)
    check("tally: cancelled here, cancelled in Tally by Tally's own voucher number; Ali Traders owes 54,957 again",
          res and res[0]["ok"] and same[0]["ISCANCELLED"] == "Yes" and ft.bills("Ali Traders") == {"INV/26-27/0001": DD("54957.00")}, res)
    b.party("Bilal & Sons", "customer")
    b.invoice("Bilal & Sons", [{"item": "Wall Mount", "qty": 1}], date="2026-08-03")
    res = S.sync_all(b, "tally", conn)
    check("tally: a name with '&' is escaped (one raw & would make Tally refuse the whole request)", res and res[0]["ok"] and "Bilal & Sons" in ft.ledgers, res)
    ft.company = "Other Co"
    b.expense("internet bill", "3,000", paid_from="cash", date="2026-08-04")
    res = S.sync_all(b, "tally", conn)
    check("tally: the company closed in TallyPrime: the run stops and says to open it", len(res) == 1 and res[0]["kind"] == "offline"
          and "not open in TallyPrime" in res[0]["notes"][0], res)
    check("tally: the books' own checks still pass", R.verify(b) == [], R.verify(b))
    b.close()


# ==================================================================== QuickBooks Online (basic)
def quickbooks_tests():
    b, d = build(OUT / "quickbooks.db")
    fq = FakeQbo()
    got = {}
    who = quickbooks.finish("qbo-client", "qbo-secret", "sandbox", "good-code", "9130", "http://localhost:3011/callback", fq, store=got.update)
    check("quickbooks: the sign-in's code becomes tokens for the company it chose (realm 9130)", who["who"] == "Khan Electronics" and got["realm"] == "9130",
          (who, got))
    conn = quickbooks.System(dict(got), fq)
    fq.failing("POST", "/payment?", "drop", times=1)  # an answer lost once: the hub's retry carries the same requestid
    res = S.sync_all(b, "quickbooks", conn)
    common("quickbooks", b, conn, res)
    inv = next(x for x in fq.t["Invoice"].values() if x["DocNumber"] == "INV/26-27/0001")
    check("quickbooks: INV/26-27/0001 totals 212,674 and owes 54,957 (the return applied by a zero payment)", (inv["TotalAmt"], inv["Balance"]) ==
          (212674.0, 54957.0), (inv["TotalAmt"], inv["Balance"]))
    codes = sorted(x["Name"] for x in fq.t["TaxCode"].values())
    check("quickbooks: tax codes made under the agency FBR: 16%, 18%, 18% + further tax 4%, and 0% for untaxed lines",
          codes == ["No Tax 0%", "Sales Tax 16%", "Sales Tax 18%", "Sales Tax 18% + Further Tax 4%"]
          and [a["DisplayName"] for a in fq.t["TaxAgency"].values()] == ["FBR"], codes)
    refs = [p.get("PaymentRefNum") for p in fq.t["Payment"].values()]
    check("quickbooks: a lost answer retried with the same requestid is answered again, not written twice", fq.replays == 1 and len(refs) == len(set(refs)), refs)
    check("quickbooks: the books' own checks still pass", R.verify(b) == [], R.verify(b))
    b.close()


# ==================================================================== FBR Digital Invoicing (basic)
def fbr_tests():
    b, d = build(OUT / "fbr.db")
    ff = FakeFbr()
    got = {}
    who = fbr.connect({"token": "pral-sandbox-token"}, ff, store=got.update)
    check("fbr: the PRAL token is checked against FBR's reference list and kept", who["where"] == "FBR Digital Invoicing (sandbox)" and got["env"] == "sandbox")
    conn = fbr.System(dict(got), ff)
    v = conn.validate(b, b.doc(d["inv1"]["id"]))
    check("fbr: an invoice with a service on it is stopped before FBR (services are provincial sales tax)", not v["ok"] and "Installation is a service" in
          " ".join(v["problems"]), v)
    inv2 = b.doc(d["inv2"]["id"])
    body, problems = conn.payload(b, inv2)
    check("fbr: INV/26-27/0002 as FBR wants it: NTN 1234567, Punjab (from 'Lahore'), unregistered buyer (SN002), 85,000 + 15,300 + further 3,400",
          not problems and body["sellerNTNCNIC"] == "1234567" and body["sellerProvince"] == "Punjab" and body["buyerRegistrationType"] == "Unregistered"
          and body["scenarioId"] == "SN002" and body["items"][0]["hsCode"] == "8528.7200" and (body["items"][0]["valueSalesExcludingST"],
                                                                                                 body["items"][0]["salesTaxApplicable"], body["items"][0]["furtherTax"],
                                                                                                 body["items"][0]["totalValues"]) == (85000.0, 15300.0, 3400.0, 103700.0),
          (problems, body))
    check("fbr: FBR validates it first (no number issued)", conn.validate(b, inv2)["ok"] and not ff.posted)
    ff.failing("POST", "postinvoicedata", "drop")
    try:
        conn.post(b, inv2)
        check("fbr: the post's answer lost: told to look in IRIS before posting again", False)
    except S.SyncError as e:
        check("fbr: the post's answer lost: told to look in IRIS before posting again", "IRIS" in str(e) and len(ff.posted) == 1, e)
    try:
        conn.post(b, b.doc(inv2["id"]))
        check("fbr: and it is not posted a second time without the person's word", False)
    except S.SyncError as e:
        check("fbr: and it is not posted a second time without the person's word", "did not answer the last time" in str(e) and len(ff.posted) == 1, e)
    n = conn.record(b, b.doc(inv2["id"]), ff.posted[0]["invoiceNumber"].lower())
    check("fbr: the number found in IRIS is recorded with the invoice", b.doc(inv2["id"])["links"]["fbr"] == n == ff.posted[0]["invoiceNumber"], n)
    doc = DOCS.make(b, b.doc(inv2["id"]), OUT / "fbr_documents")
    check("fbr: the PDF shows FBR's number with its QR code (version 2, 1 inch), and the check reads it back",
          all(c["ok"] for c in doc["checks"]) and any("FBR's invoice number" in c["what"] for c in doc["checks"]), doc["checks"])
    b.close()


# ==================================================================== the chat (basic)
def chat_tests():
    b, d = build(OUT / "chat.db")
    fx, ff = FakeXero(), FakeFbr()
    b.item("LED TV 65", rate="1,40,000", tax="18", hs_code="8528.7200")
    ac = AccountsChat.start(chats_dir=OUT / "chats", books=b, connectors={"xero": xero.System(fx.creds(), fx), "fbr": fbr.System({"token": ff.token}, ff),
                                                                         "zoho": zoho.System({}, FakeZoho())})
    r = ac.say("send everything to xero")
    check("chat: 'send everything to xero' shows what goes first", r.startswith("Ready to send 9 documents (1 bill, 2 invoices,") and
          "to Xero (Khan Electronics)" in r and not fx.invoices, r)
    r = ac.say("yes")
    check("chat: and on yes sends all 9, each read back", r.startswith("Sent to Xero: 9 of 9") and len(fx.invoices) == 3, r)
    r = ac.say("sync with zoho")
    check("chat: a system not connected says how to connect it", "Zoho Books is not connected" in r and "accounts.py steps zoho" in r, r)
    r = ac.say("invoice for Ali Traders: 1 LED TV 65, due in 15 days")
    r2 = ac.say("send invoice 1 to xero")
    check("chat: a new request while something waits for a yes is not taken as the yes", "Ready to send INV/26-27/0001" in r2 or "already" in r2.lower()
          and len(fx.invoices) == 3, (r, r2))
    r = ac.say("invoice for Ali Traders: 1 LED TV 65, due in 15 days")
    ac.say("yes")
    num = ac.state["made"][-1]
    r = ac.say(f"post {num} to fbr")
    check("chat: 'post INV... to FBR' is validated by FBR first and waits for a yes", r.startswith(f"FBR checked {num}") and "valid" in r and not ff.posted, r)
    r = ac.say("yes")
    check("chat: on yes FBR issues its number; the PDF shows it with the QR code", r.startswith(f"Posted to FBR: {num} is FBR invoice 1234567DI")
          and "(checked)" in r and len(ff.posted) == 1, r)
    b.close()


def main():
    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    xero_tests()
    zoho_tests()
    tally_tests()
    quickbooks_tests()
    fbr_tests()
    chat_tests()
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not bad else f'{len(bad)} FAILED'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)}, {time.time() - t0:.0f} s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
