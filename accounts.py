"""A small business's books by conversation: invoices, quotations, bills, money in and out, returns, stock, sales tax
and reports, kept in double entry on this PC (state/accounts/books.db), with sales tax invoices as PDF; linked to
QuickBooks Online, TallyPrime, Xero and Zoho Books when you connect them. Every entry is shown first and saved only after
your yes; the books check themselves after every change.

  .venv\\Scripts\\python.exe accounts.py talk -m "my business is Khan Electronics, NTN 1234567-8, STRN 3277876123456"
  .venv\\Scripts\\python.exe accounts.py talk -m "invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 18% tax, due in 15 days" -m "yes"
  .venv\\Scripts\\python.exe accounts.py report owed | profit | balance | trial | tax | stock
  .venv\\Scripts\\python.exe accounts.py pdf INV/26-27/0001
  .venv\\Scripts\\python.exe accounts.py steps quickbooks|tally|xero|zoho       connect quickbooks|xero|zoho     (TallyPrime needs no key)

Things to say: 'invoice for <customer>: <qty> <item> at <price>, 18% tax, due in 15 days', 'quotation for ...',
'turn quote 3 into an invoice', '<customer> paid 50,000 by bank (and deducted 2,000 tax)', 'paid <supplier> 1 lakh',
'bought 10 <item> from <supplier> at 70,000 each plus 18% tax', 'paid rent 40,000 from bank', '<customer> returned 1 <item>
from invoice 3', 'cancel invoice 4', 'who owes me money?', 'profit this month', 'sales tax for september', 'stock',
'statement for <customer>', 'email invoice 3 to ali@x.com', 'send invoice 3 to quickbooks', 'undo'.
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="a small business's books by conversation, kept in double entry and checked after every change")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation")
    t.add_argument("-m", "--say", action="append", default=[])
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    r = sub.add_parser("report", help="a report at once")
    r.add_argument("what", choices=["owed", "owing", "profit", "balance", "trial", "tax", "stock"])
    p = sub.add_parser("pdf", help="a document as PDF")
    p.add_argument("number")
    s = sub.add_parser("steps", help="how to connect accounting software")
    s.add_argument("system", nargs="?")
    c = sub.add_parser("connect", help="connect accounting software")
    c.add_argument("system")
    a = ap.parse_args()
    from harness.accounts.accountschat import AccountsChat
    if a.cmd == "report":
        what = {"balance": "balance_sheet", "trial": "trial_balance", "tax": "sales_tax"}.get(a.what, a.what)
        return print(AccountsChat.start().run({"op": "report", "what": what}))
    if a.cmd == "pdf":
        return print(AccountsChat.start().run({"op": "show", "kind": None, "ref": a.number}))
    if a.cmd in ("steps", "connect"):
        from harness.accounts import systems
        return systems.cli(a.cmd, getattr(a, "system", None))
    planner = None
    if not a.offline:
        from harness.planner import ChatPlanner
        planner = ChatPlanner()
    ac = AccountsChat.start(planner=planner)
    print(f"Accounts chat {ac.state['id']} for {ac.b.company().get('name')}. 'quit' to leave.")
    for m in a.say or iter(lambda: input("> ").strip(), "quit"):
        if a.say:
            print(f"> {m}")
        if m.lower() in ("quit", "exit", "q", "bye"):
            break
        if m:
            print(ac.say(m), flush=True)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"(AI ${usd:.4f})")


if __name__ == "__main__":
    main()
