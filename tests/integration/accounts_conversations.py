"""Conversations with the accounts lane in everyday words, each turn checked on what it did to the books (documents made,
figures, balances), with the cheap model reading what the rules cannot.

  .venv\\Scripts\\python.exe tests\\integration\\accounts_conversations.py [--offline]
"""

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from ai_pc.accounts import reports as R  # noqa: E402
from ai_pc.accounts.accountschat import AccountsChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "accounts_conv"
RESULTS = []


def run(name, c, turns):
    print(f"\n== {name}")
    for msg, test in turns:
        t0 = time.perf_counter()
        reply = c.say(msg)
        try:
            good, why = test(c, reply)
        except Exception as e:  # noqa: BLE001
            good, why = False, f"{type(e).__name__}: {e}"
        RESULTS.append((name, msg, good))
        llm = " [model]" if (c.last_turn or {}).get("llm") else ""
        print(f"{'ok  ' if good else 'FAIL'} > {msg}{llm}  ({time.perf_counter() - t0:.0f} s)")
        for line in reply.splitlines()[:4]:
            print(f"       {line[:180]}")
        if not good:
            print(f"     why: {why}")


def main():
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    t0 = time.time()
    c = AccountsChat.start(planner=planner, chats_dir=OUT / "chats", db=OUT / "books.db")
    b = c.b

    def company(c, r):
        co = b.company()
        return co.get("name") == "Khan Electronics" and co.get("strn") == "3277876123456" and co.get("ntn") == "1234567-8", (co, r[:200])

    def item(c, r):
        it = b.find_item("LED TV 55") or {}
        return it.get("rate") == 8500000 and it.get("cost") == 7000000 and str(it.get("tax")) == "18" and it.get("stock"), (it, r[:200])

    def bill_preview(c, r):
        return "Bill from Haier" in r and "826,000" in r and (c.state.get("pending") or {}).get("op") == "bill", r[:300]

    def saved(prefix):
        def t(c, r):
            return prefix in r and "Books checked" in r, r[:300]

        return t

    def invoice_preview(c, r):
        p = c.state.get("pending") or {}
        return r.startswith("Invoice for Ali Traders") and p.get("due_days") == 14 and "200,600" in r.replace("Rs ", ""), (p, r[:300])

    def receipt_preview(c, r):
        p = c.state.get("pending") or {}
        return r.startswith("Ready to record Rs 100,000 received from Ali Traders") and p.get("bank") is True, r[:300]

    def profit(c, r):
        return "gross profit" in r and "net" in r, r[:300]

    def stock(c, r):
        return "LED TV 55: 8 pcs" in r, r[:300]

    def owed(c, r):
        return "Ali Traders: Rs 100,600" in r, r[:300]

    run(
        "a shop's first week of books",
        c,
        [
            ("set up my business: Khan Electronics, NTN 1234567-8, STRN 3277876123456, Hall Road Lahore", company),
            ("we sell the LED TV 55 for 85,000, it costs us 70,000, 18% tax, keep a stock count", item),
            ("got 10 LED TV 55 from Haier at 70k each with 18% tax", bill_preview),
            ("yes", saved("Bill BILL/")),
            ("bill Ali Traders for 2 of the LED TV 55 at 85,000 each plus tax, payment in 2 weeks", invoice_preview),
            ("yes", saved("Invoice INV/")),
            ("Ali sent 100000 through easypaisa", receipt_preview),
            ("yes", saved("Receipt RCV/")),
            ("how's business this month?", profit),
            ("what's left in the shop?", stock),
            ("who still has to pay me?", owed),
        ],
    )
    problems = R.verify(b)
    print(f"\nbooks' own checks: {'all pass' if not problems else problems}")
    ok = sum(1 for *_, g in RESULTS if g)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"{ok}/{len(RESULTS)} turns right in {time.time() - t0:.0f} s; model ${usd:.4f}")
    b.close()
    return 0 if ok == len(RESULTS) and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
