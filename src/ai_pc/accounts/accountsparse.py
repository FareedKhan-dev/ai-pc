"""Requests about the books read by rules (the cheap model reads only what these cannot).

  parse(text, ctx) -> {"ops": [...], "ask": None | "question back"}
ctx: {"parties": [names], "items": [names], "now": datetime, "last": last document number}
Ops: setup, item, party, opening, invoice, quote, convert, bill, receipt, payment, expense, credit_note, void, show, email,
report (owed, owing, profit, balance_sheet, trial_balance, sales_tax, stock, statement, day_book), sync, undo.
"""
import datetime as dt
import re

from ai_pc.hub.hubparse import when

AMT = r"(?:rs\.?\s*|pkr\s*)?\d(?:[\d,]*\d)?(?:\.\d+)?(?:\s*(?:lakh|lac|crore|k|thousand|million))?(?:\s*/-)?"  # never ends on a comma
UNITS = r"pcs|pieces?|units?|kg|kgs|g|grams?|litres?|liters?|ltr|l|m|meters?|metres?|ft|feet|boxes|box|cartons?|dozens?|hours?|hrs?|days?|jobs?|sets?|packs?|bags?|rolls?"
SYSTEMS = {"quickbooks": r"\bquick ?books\b|\bqbo\b", "tally": r"\btally(?: ?prime)?\b", "xero": r"\bxero\b", "zoho": r"\bzoho(?: books)?\b"}
BANKISH = r"\b(?:bank|cheque|check|transfer|online|ibft|raast|easypaisa|jazzcash|card)\b"
DOCWORDS = {"invoice": r"invoice|inv", "quote": r"quotation|quote|quo|estimate", "bill": r"bill", "receipt": r"receipt|rcv",
            "credit_note": r"credit note|cn", "payment": r"payment voucher|pay"}


def _split(s):
    """Line items separated by commas (not the ones inside 85,000 or 1,97,200), semicolons, 'and' or new lines."""
    parts = re.split(r"\s*(?:;|\n|,(?!\d{2,3}\b)|\band\b|\+(?!\s*\d+(?:\.\d+)?\s*%))\s*", s)
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


def parse_line(seg, items=()):
    """'2 LED TV 55 at 85,000 each (16% tax)' -> {"item", "qty", "rate", "tax", "discount", "unit"}; None if no item in it."""
    s = " " + " ".join(seg.split()) + " "
    out = {}
    hold = None
    for it in sorted(items, key=len, reverse=True):  # 'LED TV 55': the 55 belongs to the name
        k = s.lower().find(it.lower())
        if k >= 0 and re.search(r"\d", it):
            hold = it
            s = s[:k] + " \x00ITEM\x00 " + s[k + len(it):]
            break
    m = re.search(r"[(\s]\+?\s*(\d+(?:\.\d+)?)\s*%\s*(?:sales\s*)?(?:tax|gst|st)\)?", s, re.I)
    if m:
        out["tax"] = m.group(1)
        s = s[:m.start()] + " " + s[m.end():]
    m = re.search(r"\b(?:less\s+)?(\d+(?:\.\d+)?%|rs\.?\s*[\d,]+)\s*(?:discount|off)\b|\bless\s+(\d+(?:\.\d+)?%|rs\.?\s*[\d,]+)", s, re.I)
    if m:
        out["discount"] = (m.group(1) or m.group(2)).replace(" ", "")
        s = s[:m.start()] + " " + s[m.end():]
    m = re.search(r"\s(?:at|@|for|rate|price|=|-)\s*(" + AMT + r")\s*(?:each|per\s+(\w+)|/\s*([a-z]+)|a piece|apiece)?\s*$", s, re.I)
    if m:
        out["rate"] = m.group(1)
        if m.group(2) or m.group(3):
            out["unit"] = (m.group(2) or m.group(3)).lower()
        s = s[:m.start()]
    else:
        m = re.search(r"^(.*[a-z\x00].*?)\s+(" + AMT + r")\s*(?:each)?\s*$", s, re.I)
        looks = m and (re.search(r"[,.]|rs|lakh|lac|crore|k\b|thousand|million", m.group(2), re.I) or len(re.sub(r"\D", "", m.group(2))) >= 3)
        if m and looks and not re.fullmatch(r"\s*\d+(?:\.\d+)?\s*(?:" + UNITS + r")?\s*", m.group(1), re.I):
            out["rate"] = m.group(2)
            s = " " + m.group(1)
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:x|×|nos?\.?|pcs\s+of)?\s*(?:(" + UNITS + r")\b\s*(?:of\s+)?)?(.+)$", s, re.I)
    if m and re.search(r"[a-z]", m.group(3), re.I):
        out["qty"] = m.group(1)
        if m.group(2):
            out["unit"] = m.group(2).lower()
        name = m.group(3)
    else:
        name = s
        m = re.search(r"\s(?:x|×|qty|quantity)\s*(\d+(?:\.\d+)?)\s*$", name, re.I)
        if m:
            out["qty"] = m.group(1)
            name = name[:m.start()]
    name = re.sub(r"\s+(?:each|only)$", "", name.strip(" -:,."), flags=re.I).strip()
    if hold:
        name = name.replace("\x00ITEM\x00", hold).strip()
    if not name or not re.search(r"[a-z]", name, re.I):
        return None
    known = sorted((i for i in items if i.lower() in name.lower() or name.lower().rstrip("s") == i.lower() or name.lower() in i.lower()), key=len, reverse=True)
    out["item"] = known[0] if known else re.sub(r"(?<=[a-z]{3})s$", "", name, flags=re.I) if re.search(r"(?<=[a-z]{3})s$", name, re.I) and \
        not re.search(r"(?:ss|us|is)$", name, re.I) else name
    out.setdefault("qty", "1")
    return out


def lines_in(text, items=()):
    """The line items in a request (after 'for <party>:' or the like): [{item, qty, rate, ...}], and the tax said for all."""
    t = text
    glob = None
    m = re.search(r"(?:\bplus\b|\bwith\b|\+|,)?\s*(\d+(?:\.\d+)?)\s*%\s*(?:sales\s*)?(?:tax|gst)\s*(?:on (?:all|everything|each))?", t, re.I)
    if m and not re.search(r"\(\s*$", t[:m.start()]):
        glob = m.group(1)
    if re.search(r"\b(?:no|without|zero|exempt(?:ed)?(?: from)?|free of|tax[- ]?free|excluding)\s*(?:sales\s*)?(?:tax|gst)?\b", t, re.I) and \
            re.search(r"\btax|\bgst|\bexempt", t, re.I) and not glob:
        glob = "0"
    t = re.sub(r"(?:\bplus\b|\bwith\b|\+)?\s*\d+(?:\.\d+)?\s*%\s*(?:sales\s*)?(?:tax|gst)\s*(?:on (?:all|everything|each))?(?!\))", " ", t, flags=re.I) if glob not in (None, "0") else t
    t = re.sub(r"\b(?:no|without|zero)\s*(?:sales\s*)?(?:tax|gst)\b|\btax[- ]?free\b|\bexempt(?:ed)?(?: from (?:sales )?tax)?\b", " ", t, flags=re.I)
    t = re.sub(r",?\s*\b(?:due|payable|payment)\b.*$|,?\s*\b(?:dated|valid for|valid till|valid until)\b.*$", "", t, flags=re.I)
    t = re.sub(r"\s*(?:\bplus\b|\bwith\b|\+|\bincluding\b|\bincl\.?|\bexcluding\b|\bexcl\.?|\bexclusive of\b)\s*(?:the\s+)?(?:sales\s+)?(?:tax|gst)\b(?!\s*\d)",
               " ", t, flags=re.I)
    disc = None
    m = re.search(r"(?:^|[,;]|\band\b)\s*(?:less|minus|with|give|giving)?\s*(\d+(?:\.\d+)?\s*%|rs\.?\s*[\d,]+)\s*(?:discount|off)(?:\s+on (?:all|everything|each))?\s*(?=[,;]|$)",
                  t, re.I)
    if m:
        disc = m.group(1).replace(" ", "")
        t = t[:m.start()] + t[m.end():]
    out = []
    for seg in _split(t):
        ln = parse_line(seg, items)
        if ln:
            if glob is not None and "tax" not in ln:
                ln["tax"] = glob
            if disc and "discount" not in ln:
                ln["discount"] = disc
            out.append(ln)
    return out


def party_in(raw, parties=(), after=r"(?:for|to|from)"):
    low = raw.lower()
    known = sorted((p for p in parties if re.search(r"\b" + re.escape(p.lower()) + r"\b", low)), key=len, reverse=True)
    if known:
        return known[0]
    m = re.search(r"\b" + after + r"\s+(?:(?i:m/s|mr|mrs|ms|messrs)\.?\s+)?([A-Z][\w&.'-]*(?:\s+(?:&\s+)?[A-Z][\w&.'-]*){0,5})", raw)
    return m.group(1).strip(" .,:") if m else None


def due_in(c, now):
    m = re.search(r"\b(?:due|payable|payment)\s+(?:in|within|after)\s+(\d+)\s*(day|week|month)s?\b", c)
    if m:
        n = int(m.group(1))
        return n * {"day": 1, "week": 7, "month": 30}[m.group(2)]
    if re.search(r"\b(?:due|payable)\s+(?:on\s+)?receipt\b|\bcash on delivery\b|\bimmediately\b", c):
        return 0
    m = re.search(r"\b(?:due|payable)\s+(?:on|by)\s+(.+?)(?:,|$)", c)
    if m:
        day, _ = when(m.group(1), now)
        if day:
            return max(0, (day - now.date()).days)
    return None


def date_in(c, now):
    m = re.search(r"\b(?:dated|date|(?<!due )(?<!payable )(?<!valid )(?<!until )(?<!till )on|for)\s+((?:\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|"
                  r"sep|oct|nov|dec)[a-z]*|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?)(?:\s+\d{4})?|yesterday|today)\b", c)
    if m:
        if m.group(1) == "yesterday":
            return (now.date() - dt.timedelta(days=1)).isoformat()
        day, _ = when(m.group(1), now)
        if day and day > now.date() and not re.search(r"\d{4}", m.group(1)):
            day = day.replace(year=day.year - 1)  # a date without a year is in the past for books
        return day.isoformat() if day else None
    return None


def amount_in(s):
    m = re.search(r"(?<![\w/])(" + AMT + r")", s, re.I)
    return m.group(1) if m and re.search(r"\d", m.group(1)) else None


def doc_ref(c):
    """'invoice 12', 'INV/26-27/0012', 'quote 3' -> (kind, ref)."""
    m = re.search(r"\b([a-z]{2,4}/\d{2}-\d{2}/\d{3,5})\b", c, re.I)
    if m:
        pre = m.group(1).split("/")[0].lower()
        kind = {"inv": "invoice", "quo": "quote", "bill": "bill", "rcv": "receipt", "cn": "credit_note", "pay": "payment", "exp": "expense"}.get(pre, "invoice")
        return kind, m.group(1).upper()
    for kind, rx in DOCWORDS.items():
        m = re.search(r"\b(?:" + rx + r")\s*(?:no\.?|number|#)?\s*(\d{1,5})\b", c)
        if m:
            return kind, m.group(1)
    return None, None


def parse(text, ctx=None):
    ctx = ctx or {}
    now = ctx.get("now") or dt.datetime.now()
    raw = " ".join(text.strip().split())
    c = raw.lower().replace("’", "'")
    out = {"ops": [], "ask": None}
    parties, items = ctx.get("parties") or [], ctx.get("items") or []

    def done(*ops):
        out["ops"] = [o for o in ops if o]
        return out
    # ---------------------------------------------------------------- the lane itself
    if re.match(r"^\s*(?:undo|take (?:that|it) back)\b", c):
        return done({"op": "undo"})
    if re.search(r"\bfbr\b|\be-?invoic|\bdigital invoic", c):  # FBR's Digital Invoicing
        kind, ref = doc_ref(c)
        num = re.search(r"\b(\d{7,13}DI\d{10,16})\b", raw, re.I)
        if ref or num or re.search(r"\b(?:send|post|submit|upload|report|validate|check)\b", c):
            return done({"op": "fbr", "kind": kind or "invoice", "ref": ref or ctx.get("last"), "fbr_number": num.group(1).upper() if num else None,
                         "again": bool(re.search(r"\bagain\b", c))})
    sysm = next((s for s, rx in SYSTEMS.items() if re.search(rx, c)), None)
    if sysm and re.search(r"\b(?:send|push|sync|post|copy|upload|export|put|enter|record)\b", c):
        kind, ref = doc_ref(c)
        return done({"op": "sync", "system": sysm, "kind": kind, "ref": ref, "all": bool(re.search(r"\b(?:all|everything|every)\b", c)) or not ref})
    # ---------------------------------------------------------------- reports (read at once)
    if re.search(r"\bwho owes\b|\b(?:receivables?|outstanding|owed to me|owe me|unpaid invoices?|overdue)\b", c) and not re.search(r"\bi owe\b|\bwe owe\b", c):
        return done({"op": "report", "what": "owed"})
    if re.search(r"\b(?:i|we) owe\b|\bpayables?\b|\bunpaid bills?\b|\bowe to suppliers\b", c):
        return done({"op": "report", "what": "owing"})
    if re.search(r"\bprofit\b|\bloss\b|\bp ?& ?l\b|\bincome statement\b|\bhow (?:much )?did (?:i|we) (?:make|earn)\b|\bearnings?\b", c) and \
            not re.search(r"\bprofit margin on\b", c):
        return done({"op": "report", "what": "profit", "period": period_in(c, now)})
    if re.search(r"\bbalance sheet\b|\bnet worth\b|\bassets\b", c):
        return done({"op": "report", "what": "balance_sheet"})
    if re.search(r"\btrial balance\b", c):
        return done({"op": "report", "what": "trial_balance"})
    if re.search(r"\b(?:sales )?tax (?:return|summary|payable|for|report|due)\b|\bhow much (?:sales )?tax\b|\bannex[- ]?c\b", c) and \
            not re.search(r"\b(?:invoice|quote|bill)\b.*\b(?:for|to)\b", c):
        return done({"op": "report", "what": "sales_tax", "period": period_in(c, now)})
    if (re.search(r"\bhow (?:much|many)\b.*\b(?:left|in hand|available|have|stock)\b|\b(?:show|list|check|what(?:'s| is)|report|value of)\b.*\b(?:stock|inventory)\b|"
                  r"^\s*(?:stock|inventory|stock report|stock summary)\s*\??$|\b(?:stock|inventory)\s+(?:report|summary|level|position|value)\b", c)
            and not re.search(r"\b(?:bought|purchase|add|sell|sells|cost|costs|keep)\b", c)):
        it = next((i for i in sorted(items, key=len, reverse=True) if i.lower() in c), None)
        return done({"op": "report", "what": "stock", "item": it})
    m = re.search(r"\b(?:statement|ledger|account|history)\b\s+(?:of|for)\s+(.+)$", raw, re.I)
    if m or re.search(r"\bstatement\b", c):
        p = party_in(raw, parties, r"(?:of|for)") or (m.group(1).strip(" ?.") if m else None)
        return done({"op": "report", "what": "statement", "party": p, "period": period_in(c, now)})
    if re.search(r"\bday ?book\b|\bwhat did (?:i|we) (?:record|enter)\b", c):
        return done({"op": "report", "what": "day_book", "period": period_in(c, now) or {"start": now.date().isoformat(), "end": now.date().isoformat()}})
    # ---------------------------------------------------------------- documents shown, sent, cancelled
    kind, ref = doc_ref(c)
    em = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw)
    if em and re.search(r"\b(?:email|mail|send)\b", c):
        return done({"op": "email", "kind": kind, "ref": ref or ctx.get("last"), "to": em.group(0)})
    if ref and re.search(r"\b(?:cancel|void|delete|remove)\b", c):
        return done({"op": "void", "kind": kind, "ref": ref, "reason": (re.search(r"\b(?:because|reason)\s*:?\s*(.+)$", raw, re.I) or [None, None])[1]})
    if ref and re.search(r"\b(?:show|open|print|pdf|see|view|send me|make a pdf|download)\b", c):
        return done({"op": "show", "kind": kind, "ref": ref})
    if ref and kind == "quote" and re.search(r"\b(?:turn|convert|make|change)\b.*\binvoice\b", c):
        return done({"op": "convert", "ref": ref})
    # ---------------------------------------------------------------- setting up
    if re.search(r"\b(?:my|our) (?:business|company|shop|firm)(?:'s name)? is\b|\b(?:my|our) (?:ntn|strn|address|phone|email|bank)\b|"
                 r"\bset (?:the )?(?:sales )?tax (?:to|at)\b|\bfurther tax\b.*\d+\s*%|\bpayment terms\b", c):
        return done(dict({"op": "setup"}, **setup_in(raw)))
    m = re.search(r"\b(?:opening balances?|start(?:ing)? with)\b", c)
    if m:
        cash = re.search(r"\bcash\s+(?:of\s+)?(" + AMT + ")", c)
        bank = re.search(r"\bbank\s+(?:of\s+)?(" + AMT + ")", c)
        return done({"op": "opening", "cash": cash.group(1) if cash else "0", "bank": bank.group(1) if bank else "0"})
    m = re.search(r"\badd (?:a |an |new )?(item|product|service)\s+(.+)$", raw, re.I) or re.search(r"\b(?:the )?price of\s+(.+?)\s+is\s+(" + AMT + ")", raw, re.I)
    if m and m.re.pattern.startswith("\\badd"):
        return done(dict({"op": "item"}, **item_in(m.group(2), m.group(1).lower() == "service")))
    if m:
        return done({"op": "item", "name": m.group(1).strip(), "rate": m.group(2)})
    m = re.search(r"\b(?:we|i)\s+sell\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:for|at)\s+(" + AMT + r")", raw, re.I)
    if m and not re.search(r"\b(?:to|sold)\s+[A-Z]", raw[m.end():]):
        info = item_in(raw[m.start():], service=bool(re.search(r"\bservice\b", c)))
        info.update(name=m.group(1).strip(" ,."), rate=m.group(2))
        cm = re.search(r"\bcosts?\s+(?:us\s+|me\s+)?(" + AMT + ")", raw, re.I)
        if cm:
            info["cost"] = cm.group(1)
        info["stock"] = bool(re.search(r"\b(?:stock|inventory|count)\b", c)) and not info.get("kind") == "service"
        return done(dict({"op": "item"}, **info))
    m = re.search(r"\badd (?:a |an |new )?(customer|client|supplier|vendor)\s+(.+)$", raw, re.I)
    if m:
        return done(dict({"op": "party", "kind": "supplier" if m.group(1).lower() in ("supplier", "vendor") else "customer"}, **party_info(m.group(2))))
    # ---------------------------------------------------------------- money in and out
    wht = re.search(r"\b(?:deducted|withheld|cut|kept)\s+(" + AMT + r")\s*(?:as\s+|of\s+)?(?:income\s+)?(?:tax|wht)", c)
    via_bank = bool(re.search(BANKISH, c))
    via_cash = bool(re.search(r"\bcash\b", c))
    against = doc_ref(c)[1] if re.search(r"\bagainst\b|\bfor (?:invoice|bill)\b", c) else None
    m = re.search(r"^(?:mr\.?\s+|m/s\.?\s+)?(.+?)\s+(?:has\s+)?(?:paid|sent|transferred|deposited|gave|cleared)\s+(?:us\s+|me\s+)?(" + AMT + ")", raw, re.I)
    m2 = re.search(r"\b(?:received|got|collected)\s+(" + AMT + r")\s+from\s+(.+?)(?:\s+(?:by|in|via|through|as|against|and)\b|$)", raw, re.I)
    if m and not re.match(r"^(?:i|we|you)$", m.group(1).strip(), re.I) and not re.search(r"^(?:i|we)\s", m.group(1), re.I):
        who = party_in(m.group(1), parties, "") or m.group(1).strip()
        return done({"op": "receipt", "party": who, "amount": m.group(2), "bank": via_bank or not via_cash, "withheld": wht.group(1) if wht else None,
                     "against": against, "date": date_in(c, now)})
    if m2:
        who = party_in(m2.group(2), parties, "") or m2.group(2).strip()
        return done({"op": "receipt", "party": who, "amount": m2.group(1), "bank": via_bank or not via_cash, "withheld": wht.group(1) if wht else None,
                     "against": against, "date": date_in(c, now)})
    if re.search(r"\b(?:bought|purchased|purchase of|received goods|bill from|got a bill)\b", c) or \
            re.search(r"\b(?:got|received|took)\s+\d+(?:\.\d+)?\s+\D.*\bfrom\b", c):
        sup = party_in(raw, parties, r"(?:from)")
        part = re.sub(r"^.*?\b(?:bought|purchased|purchase of|received goods|got|received|took)\b\s*", "", raw, flags=re.I)
        part = re.sub(r"\s+\bfrom\b\s+.*?(?=\s+(?:at|@)\s+\d|$)", " ", part, flags=re.I) if sup else part
        ref = re.search(r"\b(?:bill|invoice)\s*(?:no\.?|number|#)\s*([\w/-]+)", raw, re.I)
        part = re.sub(r",?\s*\b(?:their |the )?(?:bill|invoice)\s*(?:no\.?|number|#)\s*[\w/-]+", " ", part, flags=re.I)
        lines = lines_in(part, items)
        if not sup:
            out["ask"] = "From which supplier? e.g. 'bought 10 LED TV 55 from Haier at 70,000 each'."
            return out
        if not lines:
            out["ask"] = "What was bought, how many and at what price? e.g. '10 LED TV 55 at 70,000 each plus 18% tax'."
            return out
        return done({"op": "bill", "party": sup, "lines": lines, "ref": ref.group(1) if ref else None, "due_days": due_in(c, now), "date": date_in(c, now)})
    m = re.search(r"\b(?:we\s+|i\s+)?(?:paid|pay|sent)\s+(?:to\s+)?(.+?)\s+(" + AMT + r")(?:\s|$)", raw, re.I) or \
        re.search(r"\b(?:paid|pay)\s+(" + AMT + r")\s+(?:to|for)\s+(.+?)(?:\s+(?:by|in|via|from|through)\b|$)", raw, re.I)
    sp = re.search(r"\bspent\s+(" + AMT + r")\s+on\s+(.+?)(?:\s+(?:by|in|via|from|through)\b|$)", raw, re.I)
    if sp or m:
        if sp:
            what, amt = sp.group(2), sp.group(1)
        elif re.match(r"\d|rs", m.group(1), re.I):
            amt, what = m.group(1), m.group(2)
        else:
            what, amt = m.group(1), m.group(2)
        what = re.sub(r"^(?:the|our|my)\s+", "", what.strip(" .,"), flags=re.I)
        sup = party_in(what, parties, "")
        if sup and sup.lower() in what.lower() and not re.search(r"\bbill for\b", what.lower()):
            return done({"op": "payment", "party": sup, "amount": amt, "bank": via_bank or not via_cash, "withheld": wht.group(1) if wht else None,
                         "against": against, "date": date_in(c, now)})
        tax = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:sales\s*)?tax", c)
        return done({"op": "expense", "what": what, "amount": amt, "paid_from": "bank" if via_bank else "cash", "tax": tax.group(1) if tax else None,
                     "date": date_in(c, now)})
    if re.search(r"\breturned\b|\breturn of\b|\bcredit note\b", c):
        who = party_in(raw, parties, r"(?:for|to|from)") or (re.match(r"^(.+?)\s+returned\b", raw, re.I) or [None, None])[1]
        part = re.sub(r"^.*?\breturned\b\s*|^.*?\bcredit note\b\s*(?:for|to)?\s*", "", raw, flags=re.I)
        part = re.sub(r"\s*\b(?:from|of|on|against)\s+(?:invoice|inv)\b.*$", "", part, flags=re.I)
        return done({"op": "credit_note", "party": who, "invoice": ref, "lines": lines_in(part, items), "reason": None})
    # ---------------------------------------------------------------- invoices and quotations
    is_quote = re.search(r"\b(?:quotation|quote|estimate|proforma)\b", c)
    if re.search(r"\b(?:invoice|bill(?! from)|quotation|quote|estimate|proforma|sold|sale to|sell)\b", c) and \
            (re.search(r"\b(?:make|create|new|prepare|raise|issue|generate|send|give|write|draft|sold|sell|bill)\b", c) or
             re.match(r"^\s*(?:an? |new )?(?:sales (?:tax )?)?(?:invoice|quotation|quote|estimate|proforma)\b", c)):
        p = party_in(raw, parties, r"(?:for|to)")
        if not p:  # 'invoice Bilal Stores for 3 LED TV 65': the customer right after the word
            mm = re.search(r"\b(?:invoice|quotation|quote|estimate|proforma|bill)\s+(?:to\s+|for\s+)?(?:(?i:m/s|messrs)\.?\s+)?([A-Z][\w&.'-]*(?:\s+(?:&\s+)?[A-Z][\w&.'-]*){0,5})",
                           raw)
            p = mm.group(1).strip(" .,:") if mm else None
        part = raw
        mm = re.search(r":\s*(.+)$", raw)
        if mm:
            part = mm.group(1)
        else:
            if p:
                part = raw[raw.lower().find(p.lower()) + len(p):] if p.lower() in raw.lower() else raw
                part = re.sub(r"^\s*(?:for|with)\b", "", part, flags=re.I)
            part = re.sub(r"^.*?\b(?:sold|sell)\b", "", part, flags=re.I) if re.search(r"\bsold\b|\bsell\b", part, re.I) else part
        lines = lines_in(part, items)
        if not p:
            out["ask"] = "For which customer? e.g. 'invoice for Ali Traders: 2 LED TV 55 at 85,000 each'."
            return out
        if not lines:
            out["ask"] = "What goes on it? e.g. '2 LED TV 55 at 85,000 each, 1 wall mount at 3,500, 18% tax'."
            return out
        vd = re.search(r"\bvalid (?:for )?(\d+)\s*days?\b", c)
        return done({"op": "quote" if is_quote else "invoice", "party": p, "lines": lines, "due_days": due_in(c, now), "date": date_in(c, now),
                     "valid_days": int(vd.group(1)) if vd else None, "notes": (re.search(r"\bnotes?\s*:\s*(.+)$", raw, re.I) or [None, None])[1]})
    return out


def period_in(c, now):
    d = now.date()
    if re.search(r"\btoday\b", c):
        return {"start": d.isoformat(), "end": d.isoformat()}
    if re.search(r"\bthis week\b", c):
        return {"start": (d - dt.timedelta(days=d.weekday())).isoformat(), "end": d.isoformat()}
    if re.search(r"\blast month\b", c):
        e = d.replace(day=1) - dt.timedelta(days=1)
        return {"start": e.replace(day=1).isoformat(), "end": e.isoformat()}
    if re.search(r"\bthis month\b|\bso far this month\b|\bmonth to date\b", c):
        return {"start": d.replace(day=1).isoformat(), "end": d.isoformat()}
    if re.search(r"\bthis (?:financial |fiscal )?year\b|\bso far this year\b|\bytd\b", c):
        y = d.year if d.month >= 7 else d.year - 1
        return {"start": dt.date(y, 7, 1).isoformat(), "end": d.isoformat()}
    if re.search(r"\blast (?:financial |fiscal )?year\b", c):
        y = (d.year if d.month >= 7 else d.year - 1) - 1
        return {"start": dt.date(y, 7, 1).isoformat(), "end": dt.date(y + 1, 6, 30).isoformat()}
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    m = re.search(r"\b(" + "|".join(months + [x[:3] for x in months]) + r")\b(?:\s+(\d{4}))?", c)
    if m:
        k = next(i for i, x in enumerate(months, 1) if x.startswith(m.group(1)[:3]))
        y = int(m.group(2)) if m.group(2) else (d.year if k <= d.month else d.year - 1)
        start = dt.date(y, k, 1)
        end = (dt.date(y + (k == 12), k % 12 + 1, 1) - dt.timedelta(days=1))
        return {"start": start.isoformat(), "end": min(end, d).isoformat()}
    return None


def setup_in(raw):
    out = {}
    m = re.search(r"\b(?:business|company|shop|firm)(?:'s name)? is\s+([^,;]+)", raw, re.I)
    if m:
        out["name"] = m.group(1).strip(" .")
    for k, rx in (("ntn", r"\bntn\s*(?:is|:|number)?\s*([\d-]{7,10})"), ("strn", r"\bstrn\s*(?:is|:|number)?\s*([\d-]{12,17})"),
                  ("phone", r"\bphone\s*(?:is|:|number)?\s*([+\d][\d -]{7,15}\d)"), ("email", r"([\w.+-]+@[\w-]+(?:\.[\w-]+)+)"),
                  ("address", r"\baddress\s*(?:is|:)?\s*([^;]+?)(?:,\s*(?:ntn|strn|phone|email)\b|$)"), ("bank", r"\bbank\s*(?:is|:|details?\s*(?:are|:)?)\s*([^;]+)$")):
        m = re.search(rx, raw, re.I)
        if m:
            out[k] = m.group(1).strip(" .")
    m = re.search(r"\bset (?:the )?(?:sales )?tax (?:to|at)\s*(\d+(?:\.\d+)?)\s*%", raw, re.I) or re.search(r"\bsales tax (?:is|of)\s*(\d+(?:\.\d+)?)\s*%", raw, re.I)
    if m:
        out["default_tax"] = m.group(1)
    m = re.search(r"\bfurther tax\D*(\d+(?:\.\d+)?)\s*%", raw, re.I)
    if m:
        out["further_tax"] = m.group(1)
    m = re.search(r"\bpayment terms\D*(\d+)\s*days?", raw, re.I)
    if m:
        out["terms"] = int(m.group(1))
    return out


def item_in(s, service=False):
    out = {"kind": "service" if service else "goods"}
    m = re.search(r"\b(?:price|rate|sells? (?:at|for)|selling price|sale price|at)\s*(?:is|of|:)?\s*(" + AMT + ")", s, re.I)
    if m:
        out["rate"] = m.group(1)
    m = re.search(r"\b(?:cost|buying price|purchase price|bought at)\s*(?:is|of|:)?\s*(" + AMT + ")", s, re.I)
    if m:
        out["cost"] = m.group(1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:sales\s*)?(?:tax|gst)", s, re.I)
    if m:
        out["tax"] = m.group(1)
    m = re.search(r"\bhs\s*(?:code)?\s*:?\s*([\d.]{4,12})", s, re.I)
    if m:
        out["hs_code"] = m.group(1)
    m = re.search(r"\bper\s+(" + UNITS + r")\b|\bunit\s*:?\s*(\w+)", s, re.I)
    if m:
        out["unit"] = (m.group(1) or m.group(2)).lower()
    out["stock"] = bool(re.search(r"\b(?:stock|track|inventory|keep count)\b", s, re.I)) and not service
    m = re.search(r"\breorder (?:at|level)?\s*(\d+)", s, re.I)
    if m:
        out["reorder"] = m.group(1)
    name = re.split(r",|\s+\b(?:price|rate|sells?|selling|sale|cost|buying|purchase|at|with|hs|per|unit|tax|\d+(?:\.\d+)?\s*%|stock|track|reorder)\b", s, maxsplit=1,
                    flags=re.I)[0]
    out["name"] = name.strip(" .:-")
    return out


def party_info(s):
    out = {}
    for k, rx in (("ntn", r"\bntn\s*:?\s*([\d-]{7,10})"), ("strn", r"\bstrn\s*:?\s*([\d-]{12,17})"), ("cnic", r"\bcnic\s*:?\s*(\d{5}-?\d{7}-?\d)"),
                  ("phone", r"\b(?:phone|mobile|cell|whatsapp)\s*:?\s*([+\d][\d -]{7,15}\d)|((?:\+92|0)3\d{2}-?\d{7})"),
                  ("email", r"([\w.+-]+@[\w-]+(?:\.[\w-]+)+)"), ("address", r"\baddress\s*:?\s*([^,;]+(?:,[^,;]+){0,2})"),
                  ("terms", r"\bterms?\s*:?\s*(\d+)\s*days?")):
        m = re.search(rx, s, re.I)
        if m:
            out[k] = next(g for g in m.groups() if g).strip(" .")
    if out.get("terms"):
        out["terms"] = int(out["terms"])
    name = re.split(r",|\s+\b(?:ntn|strn|cnic|phone|mobile|cell|whatsapp|email|address|terms?)\b|\s+(?:\+92|0)3\d{2}", s, maxsplit=1, flags=re.I)[0]
    out["name"] = name.strip(" .:-")
    return out
