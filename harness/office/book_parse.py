"""What a client says about an Excel workbook, turned into operations for Excel (xlsx_com) by rules; the cheap model reads
what the rules cannot into the same operations (bookchat.BOOK_SYSTEM). Columns are found by their headers (singular or
plural, "column C"), values by what the data holds ("the cancelled orders" -> Status = Cancelled), formulas from words
("Qty times Unit Price", "10% of Salary", "Pass if Percentage is at least 50% else Fail").

  r = parse_book(clause, m, focus, raw, carry) -> {"ops": [...], "focus": {"sheet", "cols"}, "ask": str | None}
  q = question_query(clause, m, focus)          -> a query computed exactly by bookchat.run_query, or None
"""
import datetime as _dt
import re

from . import doc_parse as P
from . import xlsx_map as XM
from .xlsx_com import as_number

DESC = r"\b(?:desc(?:ending)?|highest first|largest first|biggest first|most first|high(?:est)? to low(?:est)?|z ?(?:to|-) ?a|newest first|latest first|most recent first|reverse(?:d)?|top first|best first)\b"
ASC = r"\b(?:asc(?:ending)?|lowest first|smallest first|least first|low(?:est)? to high(?:est)?|a ?(?:to|-) ?z|oldest first|earliest first|alphabetical(?:ly)?)\b"
ROWS = r"(?:rows?|records?|entries|entry|lines?|orders?|students?|items?|sales?|employees?|customers?|products?|people|transactions?|invoices?)"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
FNS = [(r"\baverage|\bmean\b|\bavg\b", "average"), (r"\bcount\b|\bnumber of\b|\bhow many\b", "count"), (r"\bhighest|\bmaximum\b|\bmax\b|\blargest|\bbiggest", "max"),
       (r"\blowest|\bminimum\b|\bmin\b|\bsmallest", "min"), (r"\btotal|\bsum\b", "sum")]


# ------------------------------------------------------------------------------------------------ finding things
def sheet_in(c, m):
    """A sheet named in a clause: 'the Products sheet', 'sheet Orders', 'on Orders', 'from the products tab', 'sheet 2'.
    A sheet whose name is made of the data's own words ('Amount by City') counts only with 'sheet' or 'tab' said."""
    main = XM.sheet(m)
    words = {x["name"].lower() for x in (main or {}).get("table", {}).get("cols", [])} if main and main.get("table") else set()
    for n in sorted(m["names"], key=len, reverse=True):
        e = re.escape(n.lower())
        if re.search(rf"(?<!\w){e}(?:'s)?\s+(?:sheet|tab|worksheet)\b|\b(?:sheet|tab)\s+(?:called\s+|named\s+)?['\"]?{e}(?!\w)", c):
            return n
        datawords = any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", n.lower()) for w in words)
        if not datawords and re.search(rf"\b(?:on|in|from)\s+(?:the\s+)?['\"]?{e}['\"]?(?!\w)", c):
            return n
    mm = re.search(r"\bsheet\s+(\d+)\b", c)
    if mm and 1 <= int(mm.group(1)) <= len(m["names"]):
        return m["names"][int(mm.group(1)) - 1]
    return None


def cols_in(c, s):
    """Columns named in a clause, in the order they appear (whole words; 'prices' finds 'Price'; 'column C')."""
    if not s or not s.get("table"):
        return []
    cols = s["table"]["cols"]
    found, taken = [], []
    for col in sorted(cols, key=lambda x: -len(x["name"])):
        name = " ".join(col["name"].lower().split())
        st = XM._stem(name)
        pats = [re.escape(name) + r"(?:s|es)?"] + ([re.escape(st) + r"(?:s|es)?"] if st and st != name and len(st) >= 3 else [])
        hit = None
        for p in pats:
            for mt in re.finditer(r"(?<![\w])" + p + r"(?![\w])", c):
                if not any(a <= mt.start() < b or a < mt.end() <= b for a, b in taken):
                    hit = mt
                    break
            if hit:
                break
        if hit:
            found.append((hit.start(), col))
            taken.append(hit.span())
    for mt in re.finditer(r"\bcolumn\s+([a-z]{1,2})\b", c):
        col = next((x for x in cols if x["letter"].lower() == mt.group(1)), None)
        if col and all(col is not f[1] for f in found):
            found.append((mt.start(), col))
    return [col for _, col in sorted(found, key=lambda x: x[0])]


def col_spans(c, s):
    """(start, end, column) for each column named, in order."""
    out = []
    for col in cols_in(c, s):
        name = " ".join(col["name"].lower().split())
        st = XM._stem(name)
        mt = re.search(r"(?<![\w])" + re.escape(name) + r"(?:s|es)?(?![\w])", c) or (re.search(r"(?<![\w])" + re.escape(st) + r"(?:s|es)?(?![\w])", c) if st else None)
        if not mt:
            mt = re.search(r"\bcolumn\s+" + col["letter"].lower() + r"\b", c)
        if mt:
            out.append((mt.start(), mt.end(), col))
    return sorted(out, key=lambda x: x[0])


def values_in(c, s, skip=()):
    """Values of the data named in a clause ('the cancelled orders', 'students who failed', 'only Lahore'):
    [(column, value)] in the order they appear."""
    out = []
    if not s or not s.get("table"):
        return out
    heads = {x["name"].lower() for x in s["table"]["cols"]}
    for col in s["table"]["cols"]:
        if col["kind"] != "text" or col["name"] in skip:
            continue
        vals = {}
        for v in XM.values(s, col):
            if isinstance(v, str) and v.strip():
                vals.setdefault(" ".join(v.split()).lower(), " ".join(v.split()))
        if not vals or len(vals) > 80:
            continue
        for low, v in sorted(vals.items(), key=lambda kv: -len(kv[0])):
            if len(low) < 3 or low in heads:
                continue
            mt = re.search(r"(?<![\w])" + re.escape(low) + r"(?:s|es|ed|d|ing)?(?![\w])", c)
            if mt:
                out.append((mt.start(), col, v))
    out.sort(key=lambda x: x[0])
    seen, res = set(), []
    for _, col, v in out:
        if (col["name"], v) not in seen:
            seen.add((col["name"], v))
            res.append((col, v))
    return res


def _years(s):
    ys = set()
    for col in s["table"]["cols"]:
        if col["kind"] == "date":
            for v in XM.values(s, col):
                if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v):
                    ys.add(int(v[:4]))
    return ys


def date_of(text, s=None):
    """'1 March', 'March 1st 2026', '01/03/2026', '2026-03-01' -> 'YYYY-MM-DD' (the data's year when none is said)."""
    from .xlsx_com import _parse_date
    t = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", str(text).strip(" .,"))
    d = _parse_date(t, "dmy")
    if d:
        return d.strftime("%Y-%m-%d")
    mm = re.match(r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?$|([a-z]+)\s+(\d{1,2})(?:,?\s+(\d{4}))?$", t.lower())
    if mm:
        day, mon, yr = (mm.group(1), mm.group(2), mm.group(3)) if mm.group(1) else (mm.group(5), mm.group(4), mm.group(6))
        if mon in MONTHS:
            ys = _years(s) if s else set()
            y = int(yr) if yr else (max(ys) if ys else _dt.date.today().year)
            try:
                return _dt.date(y, MONTHS[mon], int(day)).isoformat()
            except ValueError:
                return None
    return None


def month_range(text, s=None):
    """'in March' / 'during feb 2026' -> ('YYYY-MM-01', 'YYYY-MM-last')."""
    mm = re.search(r"\b(?:in|during|for|of)\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(\d{4}))?", text)
    if not mm:
        return None
    ys = _years(s) if s else set()
    y = int(mm.group(2)) if mm.group(2) else (max(ys) if ys else _dt.date.today().year)
    mo = MONTHS[mm.group(1)]
    last = (_dt.date(y + (mo == 12), mo % 12 + 1, 1) - _dt.timedelta(days=1)).day
    return f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{last:02d}"


CMP = [(r">=|\bat least\b|\bminimum of\b|\bno less than\b|\bor more\b|\bor above\b|\band above\b|\bor over\b", ">="),
       (r"<=|\bat most\b|\bmaximum of\b|\bno more than\b|\bor less\b|\bor below\b|\band below\b|\bup to\b|\bor under\b", "<="),
       (r"<>|!=|\bis not\b|\bisn'?t\b|\bare not\b|\baren'?t\b|\bnot equal(?: to)?\b|\bother than\b|\bexcept\b|\bnot\b", "<>"),
       (r"\bbetween\b", "between"), (r"\bstarts? with\b|\bbegins? with\b", "starts"),
       (r"\bcontain(?:s|ing)?\b|\bincludes?\b|\bincluding\b|\bhas\b.*\bin it\b", "contains"),
       (r"\b(?:is |are )?(?:blank|empty|missing)\b", "blank"),
       (r">|\babove\b|\bover\b|\bmore than\b|\bgreater than\b|\bhigher than\b|\bbigger than\b|\bexceed(?:s|ing)?\b|\bafter\b|\blater than\b", ">"),
       (r"<|\bbelow\b|\bunder\b|\bless than\b|\blower than\b|\bsmaller than\b|\bbefore\b|\bearlier than\b", "<"),
       (r"=|\bequals?\b|\bequal to\b|\bis\b|\bare\b|\bof\b|\bfor\b|\bin\b|\bfrom\b", "=")]


def value_for(col, text, s):
    """The value a condition compares a column with, read in the column's own terms (a number, a date, one of its texts)."""
    text = text.strip(" .,'\"")
    text = re.sub(r"^(?:the|a|an|to|than|of)\s+", "", text)
    if not text:
        return None
    if col["kind"] == "date":
        return date_of(text, s)
    if col["kind"] in ("number", "money", "percent"):
        mm = re.search(r"(?:rs\.?\s*|pkr\s*|\$)?-?\d[\d,]*(?:\.\d+)?\s*(?:%|k\b|m\b|mn\b|million\b|thousand\b|lakhs?\b|lac\b|crore\b|cr\b)?", text)
        if not mm:
            return None
        n = as_number(mm.group(0))
        if n is not None and col["kind"] == "percent" and "%" not in mm.group(0) and n > 1:
            n = n / 100  # "above 50" on a percentage column means 50%
        return n
    vals = {" ".join(str(v).split()).lower(): " ".join(str(v).split()) for v in XM.values(s, col) if isinstance(v, str) and v.strip()}
    low = " ".join(text.split()).lower()
    if low in vals:
        return vals[low]
    for k, v in vals.items():
        if re.fullmatch(re.escape(k) + r"(?:s|es|ed|d|ing)?", low):
            return v
    return text


def condition(c, s, col=None):
    """A condition in words on one column: 'Amount is above 5 lakh', 'status is not paid', 'date after 1 March',
    'city is Lahore or Karachi', 'in March' -> {"col", "op", "value", "value2"} or None."""
    spans = col_spans(c, s)
    if col is None:
        if not spans:
            return None
        start, end, col = spans[0]
    else:
        sp = next((x for x in spans if x[2] is col), None)
        start, end = (sp[0], sp[1]) if sp else (0, 0)
    rest = c[end:]
    nxt = next((x[0] for x in spans if x[0] > end), None)
    if nxt is not None:
        rest = c[end:nxt]
    rest = re.split(r"\b(?:and then|then|in (?:red|green|yellow|orange|blue|pink|purple|grey|gray))\b", rest)[0]
    if col["kind"] == "date":
        mr = month_range(rest if re.search(r"\b(?:in|during|for|of)\s+[a-z]", rest) else c[end:], s)
        if mr and not re.search(r"\b(?:before|after|between)\b", rest):
            return {"col": col["name"], "op": "between", "value": mr[0], "value2": mr[1]}
    for rx, opn in CMP:
        mm = re.search(rx, rest)
        if not mm:
            continue
        if opn == "between":
            mb = re.search(r"\bbetween\s+(.+?)\s+and\s+(.+)$", rest)
            if mb:
                a, b = value_for(col, mb.group(1), s), value_for(col, mb.group(2), s)
                if a is not None and b is not None:
                    return {"col": col["name"], "op": "between", "value": a, "value2": b}
            continue
        if opn == "blank":
            return {"col": col["name"], "op": "blank", "value": None}
        after = rest[mm.end():] if opn not in (">=", "<=") or mm.group(0).strip().startswith(("at", "minimum", "maximum", "no ", "up")) or mm.group(0) in (">=", "<=") else rest[:mm.start()]
        if opn in (">=", "<=") and not after.strip():
            after = rest[:mm.start()]
        after = re.sub(r"^\s*(?:is|are|=|equal to|equals)\s+", " ", after)
        parts = [p for p in re.split(r"\s+or\s+|\s*,\s*", after) if p.strip()]
        if opn in ("=", "<>") and len(parts) > 1 and col["kind"] == "text":
            vs = [value_for(col, p, s) for p in parts]
            if all(v is not None for v in vs):
                return {"col": col["name"], "op": "in" if opn == "=" else "<>", "value": vs if opn == "=" else vs[0]}
        v = value_for(col, after, s)
        if v is not None and v != "":
            return {"col": col["name"], "op": opn, "value": v}
    return None


METRIC = re.compile(r"amount|total|sales|revenue|value|profit|income|paid|price|cost|salary|marks?|score|balance", re.I)
DERIVED = re.compile(r"rank|share|running|\bid\b|\bno\.?$|number|percent|%|serial", re.I)
PERSON = re.compile(r"name|customer|client|student|employee|person|staff|member|seller|agent|teacher|buyer|vendor|supplier", re.I)


RATE = re.compile(r"price|rate\b|\bunit\b|per\s|cost per", re.I)
QTY = re.compile(r"\bqty\b|quantit|units?\s+sold|\bpcs\b|pieces|\bnos?\.?$|count", re.I)


def metric(t, nums=None, additive=False):
    """The number column a question means when it names none: money, then words like amount / total / sales; never a
    rank, a share or a running total; for totals ("sold the most") never a price per unit."""
    nums = nums if nums is not None else [x for x in t["cols"] if x["kind"] in ("number", "money", "percent")]
    if additive:
        nums = [x for x in nums if not RATE.search(x["name"])] or nums
    if not nums:
        return None
    return max(nums, key=lambda x: (x["kind"] == "money") * 3 + bool(METRIC.search(x["name"])) * 2 - bool(DERIVED.search(x["name"])) * 5
               - bool(RATE.search(x["name"])) * 2 + x["idx"] * 0.01)


def value_of_sales(t):
    """(qty column, price column) when a table has quantities and unit prices but no amount: their product is the money."""
    if any(x["kind"] == "money" or re.search(r"amount|total|revenue|sales|value", x["name"], re.I) for x in t["cols"] if x["kind"] in ("number", "money")):
        return None
    q = next((x for x in t["cols"] if x["kind"] in ("number", "money") and QTY.search(x["name"])), None)
    p = next((x for x in t["cols"] if x["kind"] in ("number", "money") and RATE.search(x["name"])), None)
    return (q, p) if q and p else None


def _desc_for(c, start, end):
    seg = c[start:end]
    if re.search(DESC, seg):
        return True
    if re.search(ASC, seg):
        return False
    return None


def _name(raw, guess):
    """The new column's name as the client wrote it (their capitals), else title case."""
    g = " ".join(str(guess).split()).strip(" '\"")
    mm = re.search(re.escape(g), raw, re.I)
    got = mm.group(0) if mm else g
    return got if any(ch.isupper() for ch in got) else got.title()


# ------------------------------------------------------------------------------------------------ formulas from words
def words_to_formula(e, s):
    """'Qty times Unit Price' -> '[Qty]*[Unit Price]'; '10% of Salary' -> '[Salary]*10%'; 'average of A, B and C' ->
    'AVERAGE([A],[B],[C])'; 'Pass if Percentage is at least 50% else Fail' -> IF(...). None when words remain that are not
    columns, numbers or arithmetic (the model reads those)."""
    e = " ".join(str(e).split()).strip(" .")
    e = re.sub(r"^(?:the\s+|a\s+|an\s+)", "", e)
    mif = re.match(r"^(?:if\s+)?(?P<cond>.+?)\s*(?:,|then)\s*(?P<a>[^,]+?)\s*,?\s*(?:else|otherwise)\s+(?P<b>.+)$", e) if e.startswith("if ") else \
        re.match(r"^(?P<a>.+?)\s+(?:if|when)\s+(?P<cond>.+?)\s*,?\s*(?:else|otherwise)\s+(?P<b>.+)$", e)
    if mif:
        cond = condition(mif.group("cond"), s)
        if not cond or cond["op"] not in (">", "<", ">=", "<=", "=", "<>"):
            return None

        def lit(x):
            x = x.strip(" '\".")
            f = words_to_formula(x, s) if cols_in(x, s) else None
            if f:
                return f
            n = as_number(x)
            return str(n if not float(n).is_integer() else int(n)) if n is not None else '"' + _name(x, x).replace('"', '""') + '"'
        v = cond["value"]
        vv = (str(int(v)) if float(v).is_integer() else str(v)) if isinstance(v, (int, float)) else f'"{v}"'
        return f"IF([{cond['col']}]{cond['op']}{vv},{lit(mif.group('a'))},{lit(mif.group('b'))})"
    toks = e
    names = sorted(s["table"]["cols"], key=lambda x: -len(x["name"]))
    marks = {}
    for i, col in enumerate(names):
        name = " ".join(col["name"].lower().split())
        st = XM._stem(name)
        for p in [re.escape(name) + r"(?:s|es)?"] + ([re.escape(st) + r"(?:s|es)?"] if st and st != name and len(st) >= 3 else []):
            new = re.sub(r"(?<![\w\[])" + p + r"(?![\w\]])", f" @{i}@ ", toks)
            if new != toks:
                toks = new
                marks[f"@{i}@"] = f"[{col['name']}]"
                break
    t = f" {toks} "
    agg = re.match(r"^\s*(sum|total|average|mean|max(?:imum)?|min(?:imum)?|highest|lowest)\s+of\s+(.+)$", t.strip())
    if agg:
        refs = re.findall(r"@\d+@", agg.group(2))
        if len(refs) >= 2 and not re.sub(r"@\d+@|,|\band\b|\s", "", agg.group(2)):
            fn = {"sum": "SUM", "total": "SUM", "average": "AVERAGE", "mean": "AVERAGE", "max": "MAX", "maximum": "MAX", "highest": "MAX",
                  "min": "MIN", "minimum": "MIN", "lowest": "MIN"}[agg.group(1)]
            return f"{fn}(" + ",".join(marks[r] for r in refs) + ")"
    diff = re.match(r"^\s*(?:the\s+)?difference between\s+(@\d+@)\s+and\s+(@\d+@)\s*$", t)
    if diff:
        return f"{marks[diff.group(1)]}-{marks[diff.group(2)]}"
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s+of\s+(@\d+@)", r"\2*\1%", t)
    t = re.sub(r"(@\d+@)\s+as\s+(?:a\s+)?(?:%|percent(?:age)?)\s+of\s+(@\d+@)", r"\1/\2", t)
    t = re.sub(r"\bratio of\s+(@\d+@)\s+to\s+(@\d+@)", r"\1/\2", t)
    reps = [(r"\bmultiplied by\b|\btimes\b|(?<=@)\s+x\s+(?=@)|(?<=\d)\s*x\s*(?=@)|(?<=@)\s*x\s*(?=\d)|×", "*"), (r"\bdivided by\b|\bover\b|\bper\b", "/"),
            (r"\bplus\b|\badded to\b", "+"), (r"\bminus\b|\bless\b|\bsubtract(?:ed)?\b", "-")]
    for rx, op in reps:
        t = re.sub(rx, f" {op} ", t)
    t = re.sub(r"(\d)\s*k\b", r"\g<1>000", t)
    left = re.sub(r"@\d+@|\d+(?:\.\d+)?%?|[-+*/()^,]|\s", "", t)
    if left or not marks or not re.search(r"@\d+@", t):
        return None
    t = re.sub(r"\s+", "", t)
    for k, v in marks.items():
        t = t.replace(k, v)
    f = t
    if re.search(r"[-+*/^]{2,}|^[*/^]|[-+*/^]$", f):
        return None
    return f


# ------------------------------------------------------------------------------------------------ the rules
def _force(c):
    return bool(re.search(r"\b(?:anyway|anyways|regardless|still|force|i'?m sure|yes delete)\b", c))


def _new_column(c, raw, s, m, q):
    """'add a column Amount = Qty times Unit Price', 'add a bonus column that is 10% of salary', 'add a running total of
    amount', 'add a rank by total', 'bring the category from the products sheet', 'number the rows'."""
    t = s["table"]
    mm = re.search(r"\b(?:add|insert|create|make|put|include|calculate|compute|give me)\b\s+(?:me\s+)?(?:a\s+|an\s+|new\s+|another\s+)*"
                   r"(?:column|col|field)\s+(?:called\s+|named\s+|for\s+|titled\s+)?(?P<name>.+?)\s*(?:=|:|\bthat(?: is| shows| gives)?\b|\bwhich(?: is)?\b|\bwith\b|\bshowing\b|"
                   r"\bas\b|\bto show\b|\bequal(?:s| to)\b|\bbeing\b|\bgiving\b)\s*(?P<expr>.+)$", c) or \
        re.search(r"\b(?:add|insert|create|make|put|include)\b\s+(?:me\s+)?(?:a\s+|an\s+|new\s+|another\s+)*(?P<name>[\w%#&/ .-]+?)\s+(?:column|col|field)\b\s*"
                  r"(?:=|:|\bthat(?: is| shows| gives)?\b|\bwhich(?: is)?\b|\bwith\b|\bshowing\b|\bas\b|\bto show\b|\bequal(?:s| to)\b|\bbeing\b|\bgiving\b|\bby\b|\bof\b)?\s*(?P<expr>.*)$", c) or \
        re.search(r"\b(?:calculate|compute|work out)\s+(?:the\s+)?(?P<name>[\w%#&/ .-]+?)\s+(?:as|=|by|from)\s+(?P<expr>.+)$", c)
    pos = {}
    pm = re.search(r"\b(after|before|next to|beside|right of|left of)\s+(?:the\s+)?(.+?)(?:\s+column)?\s*$", c)
    if pm:
        pc = cols_in(pm.group(2), s)
        if pc:
            pos = {"before" if pm.group(1) in ("before", "left of") else "after": pc[0]["name"]}
    special = re.search(r"\brunning\s+(?:total|sum|balance)\b(?:\s+of\s+(?P<a>.+?))?(?=\s+(?:after|before|next to)\b|$)|\brank(?:ing)?\b(?:\s+(?:by|of|on)\s+(?P<b>.+?))?(?=\s+(?:after|before)\b|$)|"
                        r"\b(?:share|percent(?:age)? of (?:the )?total|% of (?:the )?total|portion)\b(?:\s+of\s+(?P<c>.+?))?(?=\s+(?:after|before)\b|$)|"
                        r"\b(?:serial|s\.?\s?no|sr\.?\s?no|row number|sequence|numbering)\b", c)
    if special and (mm or re.search(r"\b(?:add|insert|create|put|include|number)\b", c)):
        target = special.group("a") or special.group("b") or special.group("c")
        cs = cols_in(target or c, s)
        nums = [x for x in cs if x["kind"] in ("number", "money", "percent")] or [x for x in t["cols"] if x["kind"] in ("number", "money")][-1:]
        if special.group(0).startswith("running"):
            if not nums:
                return None
            nm = "Running Total" if all(x["name"].lower() != "running total" for x in t["cols"]) else f"Running Total ({nums[0]['name']})"
            return {"op": "add_column", "name": nm, "running": nums[0]["name"], **(pos or {"after": nums[0]["name"]})}
        if special.group(0).startswith("rank"):
            if not nums:
                return None
            low = bool(re.search(r"\blowest\b.*\b(?:1|first|one)\b|\bascending\b|\bsmallest first\b", c))
            return {"op": "add_column", "name": "Rank", "rank": nums[0]["name"], "desc": not low, **pos}
        if re.search(r"share|total|portion", special.group(0)):
            if not nums:
                return None
            return {"op": "add_column", "name": f"Share of {nums[0]['name']}", "share": nums[0]["name"], **(pos or {"after": nums[0]["name"]})}
        return {"op": "add_column", "name": "No.", "series": {"start": 1}, "before": t["cols"][0]["name"]}
    look = re.search(r"\b(?:look ?up|bring|fetch|pull|get|add|copy)\b\s+(?:in\s+)?(?:the\s+|each\s+)?(?P<what>.+?)\s+(?:column\s+)?(?:from|out of)\s+(?:the\s+)?(?P<sheet>.+?)(?:\s+(?:sheet|tab))?"
                     r"(?:\s+(?:by|using|matching|based on|on)\s+(?:the\s+)?(?P<key>.+?))?\s*$", c)
    if look:
        other = sheet_in("from " + look.group("sheet") + " sheet", m) or sheet_in(c, m)
        o = XM.sheet(m, other) if other else None
        if o and o.get("table") and o["name"] != s["name"]:
            vcols = cols_in(look.group("what"), o)
            if not vcols:
                return {"ask": f"Which column of '{o['name']}'? It has {', '.join(x['name'] for x in o['table']['cols'])}."}
            here = cols_in(look.group("key") or "", s) if look.group("key") else []
            there_names = {x["name"].lower(): x for x in o["table"]["cols"]}
            key = here[0] if here else next((x for x in t["cols"] if x["name"].lower() in there_names and x["name"].lower() != vcols[0]["name"].lower()), None)
            if key is None:
                return {"ask": f"Which column matches the two sheets? (e.g. 'bring {vcols[0]['name']} from {o['name']} by Product')"}
            match = there_names.get(key["name"].lower()) or (cols_in(look.group("key") or "", o) or [None])[0]
            if match is None:
                return {"ask": f"Which column of '{o['name']}' holds the {key['name']}?"}
            return {"op": "add_column", "name": vcols[0]["name"] if all(x["name"].lower() != vcols[0]["name"].lower() for x in t["cols"]) else f"{vcols[0]['name']} ({o['name']})",
                    "lookup": {"sheet": o["name"], "key": key["name"], "match": match["name"], "value": vcols[0]["name"]}, **(pos or {"after": key["name"]})}
    if not mm:
        return None
    name = mm.group("name").strip(" '\"")
    name = re.sub(r"^(?:called|named|for|titled)\s+", "", name)
    expr = re.sub(r"\s+(?:after|before|next to|beside|right of|left of)\s+(?:the\s+)?\S.*$", "", mm.group("expr") or "").strip(" .")
    if q and not expr:
        name = q[0]
    if re.fullmatch(r"(?:a|an|new|another)?\s*", name) or not name:
        return None
    name = _name(raw, name)
    if not expr:
        return {"unknown": True}
    f = expr if re.search(r"\[[^\]]+\]", expr) else words_to_formula(expr, s)
    if not f:
        return {"unknown": True}
    return {"op": "add_column", "name": name, "formula": f, **pos}


def _new_row(c, raw, s, q):
    """'add a row for Zara Iqbal with Maths 81, English 77 and Urdu 90', 'add an order: SO-1018, 5 April 2026, ...'."""
    t = s["table"]
    if not re.search(r"\b(?:add|insert|append|put in|enter|record)\b\s+(?:a\s+|an\s+|another\s+|one\s+more\s+|new\s+)*" + ROWS + r"\b", c):
        return None
    vals = {}
    noun = re.search(r"\b(?:add|insert|append|put in|enter|record)\b\s+(?:a\s+|an\s+|another\s+|one\s+more\s+|new\s+)*(" + ROWS + r")\b", c)
    spans = [x for x in col_spans(c, s) if not (noun and x[0] == noun.start(1)) and not x[2]["formula"]]
    for i, (a, b, col) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(c)
        seg = c[b:end]
        seg = re.sub(r"^\s*(?:is|of|=|:|-|as)\s*", " ", seg)
        seg = re.split(r"\s*,\s*|\s+and\s+(?=\w+\s)|\s+and\s*$", seg.strip())[0].strip(" .")
        seg = re.sub(r"\s+(?:with|who|having|from|in|at)$", "", seg)
        if not seg:
            continue
        rawseg = re.search(re.escape(seg), raw, re.I)
        seg_raw = rawseg.group(0) if rawseg else seg
        if col["kind"] in ("number", "money", "percent"):
            n = as_number(seg)
            if n is not None:
                vals[col["name"]] = n
        else:
            vals[col["name"]] = seg_raw
    key = t["cols"][0]
    kn = re.search(r"\b(?:for|named|called|of)\s+(?P<k>[^,:]+?)(?=\s+(?:with|who|having|from|in|on|at)\b|\s*[,:]|$)", c) or \
        re.search(r"\b(?:add|insert|append|enter)\s+(?:a\s+|an\s+|another\s+|new\s+)*" + ROWS + r"\s+(?P<k>(?!with\b)[a-z][^,:]*?)\s+(?=with\b|who\b|having\b|:)", c)
    who = q[0] if q else None
    if not who and kn and not cols_in(kn.group("k"), s):
        got = re.search(re.escape(kn.group("k").strip()), raw, re.I)
        who = got.group(0) if got else kn.group("k").strip().title()
    if who:
        home = next((col for col, v in values_in(" " + who.lower() + " ", s) if v.lower() == who.lower()), None)
        target = home or next((x for x in t["cols"] if x["kind"] == "text" and not x["formula"] and not _is_id(s, x) and x["name"] not in vals), key)
        vals.setdefault(target["name"], who)
    if _is_id(s, key) and key["name"] not in vals:
        nxt = _next_id(s, key)
        if nxt:
            vals[key["name"]] = nxt
    explicit = len([k for k in vals if k != key["name"] or not _is_id(s, key)]) - (1 if who else 0)
    if not spans:  # values in order, after a colon: one per column the client types (formula columns compute)
        mm = re.search(r":\s*(.+)$", raw)
        if mm:
            items = [x.strip() for x in re.split(r"\s*,\s*", mm.group(1)) if x.strip()]
            typed = [x for x in t["cols"] if not x["formula"]]
            if len(items) in (len(typed), len(typed) - (1 if _is_id(s, typed[0]) else 0)):
                for col, v in zip(typed[len(typed) - len(items):], items):
                    n = as_number(v) if col["kind"] in ("number", "money", "percent") else None
                    vals[col["name"]] = n if n is not None else v
                explicit = len(items)
    if explicit < 2:
        return {"unknown": True}
    return {"op": "add_row", "values": vals}


ID_RX = re.compile(r"^([A-Za-z]*[-/ #]?)(\d+)$")


def _is_id(s, col):
    vals = [str(v).strip() for v in XM.values(s, col) if v not in (None, "")]
    return len(vals) >= 2 and sum(1 for v in vals if ID_RX.match(v)) >= 0.8 * len(vals) and len(set(vals)) == len(vals)


def _next_id(s, col):
    """The next number in an ID column (SO-1016 -> SO-1017), in its own pattern."""
    best = None
    for v in XM.values(s, col):
        mm = ID_RX.match(str(v).strip()) if v not in (None, "") else None
        if mm and (best is None or int(mm.group(2)) > int(best.group(2))):
            best = mm
    if not best:
        return None
    n = str(int(best.group(2)) + 1).zfill(len(best.group(2)))
    out = best.group(1) + n
    return int(out) if out.isdigit() and not best.group(1) else out


def _style_set(c):
    s = {}
    cols = [(mm.start(), mm.group(1)) for mm in P.COLOUR_RX.finditer(c)]
    texty = re.search(r"\b(?:text|font|writing|letters|words)\b", c)
    filly = re.search(r"\b(?:fill|background|shade|shaded|highlight)\b", c)
    if cols:
        if len(cols) >= 2:
            first, second = cols[0][1], cols[1][1]
            if texty and texty.start() < cols[1][0] and (not filly or filly.start() > texty.start()):
                s["fill"], s["color"] = first, second
            else:
                s["fill"], s["color"] = first, second
        elif texty and not filly:
            s["color"] = cols[0][1]
        else:
            s["fill"] = cols[0][1]
    if re.search(r"\bbold\b", c):
        s["bold"] = not re.search(r"\b(?:not bold|unbold|remove (?:the )?bold)\b", c)
    if re.search(r"\bitalic", c):
        s["italic"] = True
    mm = re.search(r"\b(?:size\s+)?(\d{1,2})\s*(?:pt|points?)\b", c)
    if mm:
        s["size"] = int(mm.group(1))
    elif re.search(r"\bbigger|larger\b", c):
        s["size"] = "+2"
    elif re.search(r"\bsmaller\b", c):
        s["size"] = "-1"
    fm = re.search(r"\b(?:font\s+|in\s+)(arial|calibri|cambria|georgia|times new roman|verdana|tahoma|segoe ui|aptos)\b", c)
    if fm:
        s["font"] = fm.group(1).title()
    if re.search(r"\bwrap\b", c):
        s["wrap"] = True
    am = re.search(r"\b(center|centre|left|right)[- ]?(?:align(?:ed)?)?\b", c)
    if am and re.search(r"\balign|center|centre\b", c):
        s["align"] = "center" if am.group(1) in ("center", "centre") else am.group(1)
    return s


def _cleanup(s):
    """'clean up the data': what this table needs, read from the data itself (only the steps that would change something)."""
    from .xlsx_com import _norm_cat, _parse_date
    t = s["table"]
    ops = []
    for col in t["cols"]:
        if col["formula"] or col["kind"] in ("date", "number", "money", "percent"):
            continue
        vals = [v for v in XM.values(s, col) if v not in (None, "")]
        texts = [v for v in vals if isinstance(v, str)]
        if not texts:
            continue
        if len(texts) >= 0.6 * len(vals) and sum(1 for v in texts if as_number(v) is not None) >= 0.8 * len(texts) and col["kind"] != "date":
            ops.append({"op": "to_number", "cols": [col["name"]]})
            continue
        if sum(1 for v in texts if _parse_date(v, "dmy")) >= 0.8 * len(texts):
            ops.append({"op": "to_date", "col": col["name"]})
            continue
        spell = {}
        for v in texts:
            spell.setdefault(_norm_cat(v), set()).add(v)
        if any(len({" ".join(x.split()) for x in g}) > 1 for g in spell.values()) and len(spell) <= 60:
            ops.append({"op": "map_values", "col": col["name"], "auto": True})  # one spelling each, trimmed too
        elif any(v != " ".join(v.split()) for v in texts):
            ops.append({"op": "clean_text", "cols": [col["name"]], "how": "trim"})
    rows = t["rows"]
    if any(all(v in (None, "") for v in r) for r in rows):
        ops.append({"op": "delete_rows", "blank": True})
    keys = [tuple(str(v).strip().lower() for v in r) for r in rows if not all(v in (None, "") for v in r)]
    if len(keys) != len(set(keys)):
        ops.append({"op": "remove_duplicates"})
    return ops


SUBSPLIT = re.compile(r",?\s+(?:and|then|plus|also|with)\s+(?=(?:a|an|the)\s+(?:(?:grand\s+)?total|totals|sum|average|count)\s+row\b|(?:a|an)\s+drop ?down\b)")


def parse_book(clause, m, focus=None, raw=None, carry=False):
    c = P.normalize(clause)
    raw = raw or clause
    parts = SUBSPLIT.split(c)
    if len(parts) > 1:  # "add a column Amount = Qty x Price and a total row"
        outs = [parse_book(p if i == 0 or re.match(r"\s*(?:add|make|insert|create|put)\b", p) else "add " + p, m, focus, raw=raw, carry=carry) for i, p in enumerate(parts)]
        merged = {"ops": [o for r in outs for o in r["ops"]], "focus": next((r["focus"] for r in reversed(outs) if r.get("focus")), focus),
                  "ask": None if all(r["ops"] for r in outs) else next((r["ask"] for r in outs if r.get("ask")), None)}
        if not all(r["ops"] for r in outs) and not merged["ask"]:
            merged["ops"] = []  # one half could not be read: the model reads the whole clause
        return merged
    q = P.quoted(raw)
    cm = P.QUOTE.sub(" QQ ", c)
    focus = focus or {}
    named_sheet = sheet_in(cm, m)
    if named_sheet and re.search(r"\b(?:look ?up|bring|fetch|pull|get|copy|add)\b", cm) and re.search(r"\b(?:from|out of)\s+(?:the\s+)?" + re.escape(named_sheet.lower()), cm):
        named_sheet = None  # "bring the cost from the Products sheet": Products is where it comes from
    sh = named_sheet or focus.get("sheet") or m["main"]
    s = XM.sheet(m, sh)
    out = {"ops": [], "focus": {"sheet": sh, "cols": focus.get("cols") or []}, "ask": None}
    if s is None:
        out["ask"] = f"I can't find that sheet. The sheets are {', '.join(m['names'])}."
        return out
    t = s.get("table")
    mentioned = cols_in(cm, s) if t else []
    if not mentioned and t and re.search(r"\b(?:it|its|that column|this column|that|them|those columns|these columns|the new column)\b", cm) and focus.get("cols"):
        # a column made earlier in the same message is not in the map yet: Excel will have it when this runs
        mentioned = [XM.col(m, sh, n) or {"name": n, "kind": "number", "letter": "?", "idx": -1, "formula": "new", "fmt": "", "formulas": 1, "blank": 0}
                     for n in focus["cols"]]
    if mentioned:
        out["focus"]["cols"] = [x["name"] for x in mentioned]
    S = {"sheet": s["name"]}

    def done(*ops):
        out["ops"] = [dict(S, **o) if o.get("op") not in ("add_sheet",) and "sheet" not in o else o for o in ops]
        made = [o["name"] for o in ops if o.get("op") == "add_column" and o.get("name")]
        if made:  # "...and round it": the new column
            out["focus"]["cols"] = made
        return out

    def ask(text):
        out["ask"] = text
        return out
    remove = bool(re.search(r"\b(?:delete|remove|drop|get rid of|take out|erase)\b", cm))

    # ---------------------------------------------------------------- sheets
    mm = re.search(r"\brename\s+(?:the\s+)?(?:sheet|tab)\s+['\"]?(.+?)['\"]?\s+(?:to|as|into)\s+['\"]?(.+?)['\"]?$|\brename\s+(?:the\s+)?['\"]?(.+?)['\"]?\s+(?:sheet|tab)\s+(?:to|as|into)\s+['\"]?(.+?)['\"]?$|"
                   r"\bcall\s+(?:the\s+)?['\"]?(.+?)['\"]?\s+(?:sheet|tab)\s+['\"]?(.+?)['\"]?$", c)
    if mm:
        old, new = next((mm.group(i), mm.group(i + 1)) for i in (1, 3, 5) if mm.group(i))
        sn = XM.sheet(m, old)
        if sn:
            nm = re.search(re.escape(new.strip()), raw, re.I)
            return done({"op": "rename_sheet", "sheet": sn["name"], "name": q[-1] if q else (nm.group(0) if nm else new).strip(" '\"")})
    mm = re.search(r"\b(?:add|insert|create|make)\s+(?:a\s+)?(?:new\s+|blank\s+|empty\s+)?(?:sheet|tab|worksheet)(?:\s+(?:called|named)\s+['\"]?(.+?)['\"]?)?$", c)
    if mm:
        nm = q[0] if q else (re.search(re.escape(mm.group(1)), raw, re.I).group(0) if mm.group(1) else "Sheet")
        return done({"op": "add_sheet", "name": nm})
    mm = re.search(r"\b(?:delete|remove|drop)\s+(?:the\s+)?['\"]?(.+?)['\"]?\s+(?:sheet|tab|worksheet)\b|\b(?:delete|remove|drop)\s+(?:the\s+)?(?:sheet|tab)\s+['\"]?(.+?)['\"]?(?:\s+anyway.*)?$", c)
    if mm:
        sn = XM.sheet(m, mm.group(1) or mm.group(2))
        if sn:
            return done({"op": "delete_sheet", "sheet": sn["name"], **({"force": True} if _force(c) else {})})
    mm = re.search(r"\b(hide|unhide|show)\s+(?:the\s+)?['\"]?(.+?)['\"]?\s+(?:sheet|tab)\b", c)
    if mm:
        sn = XM.sheet(m, mm.group(2))
        if sn:
            return done({"op": "hide", "sheet": sn["name"], "sheet_only": True, "show": mm.group(1) != "hide"})
    if not t:
        return ask(f"Sheet '{s['name']}' has no table to work on; say which sheet ({', '.join(x['name'] for x in m['sheets'] if x['table'])}).") if \
            re.search(r"\b(?:sort|filter|highlight|column|row|total|chart|pivot)\b", cm) else out
    cols = t["cols"]
    nums = [x for x in cols if x["kind"] in ("number", "money", "percent")]

    # ---------------------------------------------------------------- clean-up
    if re.search(r"\b(?:clean(?:\s+up)?|tidy(?:\s+up)?|fix)\s+(?:up\s+)?(?:the\s+|this\s+|my\s+)?(?:data|sheet|table|workbook|whole thing|everything|mess)\b", cm):
        ops = _cleanup(s)
        if not ops:
            return ask("The data already looks clean: no spaces to trim, no mixed spellings, no numbers or dates stored as text, no empty or repeated rows.")
        return done(*ops)
    if re.search(r"\b(?:convert|turn|change|make|fix)\b.*\b(?:to|into|as|real|proper)\s+(?:real\s+|proper\s+)?numbers?\b|\b(?:stored|saved) as text\b.*\bnumbers?\b|\btext numbers\b", cm) and mentioned:
        return done({"op": "to_number", "cols": [x["name"] for x in mentioned]})
    if re.search(r"\b(?:convert|turn|change|make|fix)\b.*\b(?:dates?)\b", cm) and (mentioned or [x for x in cols if x["kind"] == "date"]):
        dc = [x for x in mentioned if x["kind"] in ("date", "text")] or [x for x in cols if x["kind"] == "date" or re.search(r"date", x["name"], re.I)]
        if dc:
            order = "mdy" if re.search(r"\bmonth first\b|\bamerican\b|\bus format\b|mm/dd", cm) else "dmy" if re.search(r"\bday first\b|dd/mm", cm) else None
            return done({"op": "to_date", "col": dc[0]["name"], **({"order": order} if order else {})})
    if re.search(r"\btrim\b|\b(?:extra|double|trailing|leading)\s+spaces\b", cm):
        tc = [x for x in mentioned if x["kind"] == "text"]
        return done({"op": "clean_text", "how": "trim", **({"cols": [x["name"] for x in tc]} if tc else {})})
    mm = re.search(r"\b(proper case|title case|capitali[sz]e(?: each word| the first letters?)?|upper ?case|all caps|capital letters|lower ?case|small letters)\b", cm)
    if mm:
        how = "proper" if re.search(r"proper|title|capitali", mm.group(1)) else "upper" if re.search(r"upper|caps|capital", mm.group(1)) else "lower"
        tc = [x for x in mentioned if x["kind"] == "text"]
        return done({"op": "clean_text", "how": how, **({"cols": [x["name"] for x in tc]} if tc else {})})
    if re.search(r"\b(?:consistent|standardi[sz]e|one spelling|same spelling|spelt? differently|spelling|duplicates? names|variants|mixed case)\b", cm) and mentioned and not remove:
        return done(*[{"op": "map_values", "col": x["name"], "auto": True} for x in mentioned if x["kind"] == "text"][:3])
    mm = re.search(r"\bfill\s+(?:in\s+)?(?:the\s+|all\s+)?(?:blanks?|empty cells|gaps|missing(?: values)?|empty)\b(.*)$", cm)
    if mm:
        fc = mentioned or [x for x in cols if x["blank"]][:1]
        if not fc:
            return ask("No column has blank cells.")
        how = "above" if re.search(r"\babove\b|\bprevious\b|\bdown\b", cm) or not re.search(r"\bwith\b", cm) else "value"
        val = None
        if how == "value":
            wm = re.search(r"\bwith\s+(.+)$", mm.group(1))
            val = (q[0] if q else wm.group(1).strip(" .'\"")) if wm else 0
            n = as_number(val) if isinstance(val, str) else None
            val = 0 if str(val).lower() in ("zero", "0", "zeros", "zeroes") else (n if n is not None else _name(raw, val))
        return done(*[{"op": "fill_blanks", "col": x["name"], "how": how, **({"value": val} if how == "value" else {})} for x in fc[:3]])

    # ---------------------------------------------------------------- rows
    if remove and re.search(r"\b(?:empty|blank)\s+(?:rows?|lines?)\b", cm):
        return done({"op": "delete_rows", "blank": True})
    if remove and re.search(r"\bduplicat\w*\b|\brepeated\b|\bdouble entries\b", cm) or re.search(r"\bdedupe\b|\bde-?duplicate\b", cm):
        by = re.search(r"\b(?:by|based on|in|on|using|with the same|same)\b(.*)$", cm)
        dc = cols_in(by.group(1), s) if by else []
        return done({"op": "remove_duplicates", **({"cols": [x["name"] for x in dc]} if dc else {})})
    mrow = re.search(r"\b(?:delete|remove|drop)\s+rows?\s+(\d+(?:\s*(?:,|and|-|to)\s*\d+)*)\b", cm)
    if mrow:
        ns = [int(x) for x in re.findall(r"\d+", mrow.group(1))]
        if re.search(r"\d+\s*(?:-|to)\s*\d+", mrow.group(1)) and len(ns) == 2:
            ns = list(range(min(ns), max(ns) + 1))
        return done({"op": "delete_rows", "rows": ns})
    if remove and (re.search(r"\b" + ROWS + r"\b", cm) or values_in(cm, s)) and not re.search(r"\bcolumns?\b|\bhighlight|\bfilter|\bformat", cm):
        cond = None
        wm = re.search(r"\b(?:where|with|whose|that have|which have|that has|which has|having|if)\b(.*)$", cm)
        if wm and cols_in(wm.group(1), s):
            cond = condition(wm.group(1), s)
        if not cond:
            vs = values_in(cm, s)
            if len(vs) == 1:
                cond = {"col": vs[0][0]["name"], "op": "=", "value": vs[0][1]}
            elif len(vs) > 1 and len({x[0]["name"] for x in vs}) == 1:
                cond = {"col": vs[0][0]["name"], "op": "in", "value": [x[1] for x in vs]}
        if cond and cond["op"] == "in":
            return done(*[{"op": "delete_rows", "where": {"col": cond["col"], "op": "=", "value": v}} for v in cond["value"]])
        if cond:
            return done({"op": "delete_rows", "where": {k: v for k, v in cond.items() if k != "op"} | {"op": cond["op"]}})
    r = _new_row(cm, raw, s, q)
    if r:
        return out if r.get("unknown") else ask(r["ask"]) if r.get("ask") else done(r)

    # ---------------------------------------------------------------- columns
    if remove and mentioned and (re.search(r"\bcolumns?\b", cm) or re.fullmatch(r"\s*(?:delete|remove|drop|get rid of)\s+(?:the\s+)?[\w %#&/.-]+?(?:\s+anyway\w*)?\s*", cm)):
        return done(*[{"op": "delete_column", "col": x["name"], **({"force": True} if _force(cm) else {})} for x in mentioned])
    mm = re.search(r"\brename\s+(?:the\s+)?(?:column\s+)?(.+?)(?:\s+column)?\s+(?:to|as|into)\s+(.+)$|\bcall\s+(?:the\s+)?(.+?)\s+column\s+(.+)$|"
                   r"\bchange\s+(?:the\s+)?(?:header|heading|name)\s+(?:of\s+)?(?:the\s+)?(.+?)(?:\s+column)?\s+to\s+(.+)$", cm)
    if mm:
        old, new = next((mm.group(i), mm.group(i + 1)) for i in (1, 3, 5) if mm.group(i))
        oc = cols_in(old, s)
        if oc:
            nm = q[-1] if q else _name(raw, new.strip(" '\"."))
            return done({"op": "rename_column", "col": oc[0]["name"], "name": nm})
    mm = re.search(r"\bmove\s+(?:the\s+)?(.+?)(?:\s+column)?\s+(?:to\s+the\s+(end|start|front|beginning|left|right)|(after|before|next to|beside)\s+(?:the\s+)?(.+?)(?:\s+column)?)\s*$", cm)
    if mm and cols_in(mm.group(1), s):
        a = cols_in(mm.group(1), s)[0]
        if mm.group(2):
            return done({"op": "move_column", "col": a["name"], "to": "start" if mm.group(2) in ("start", "front", "beginning", "left") else "end"})
        b = cols_in(mm.group(4), s)
        if b:
            return done({"op": "move_column", "col": a["name"], ("before" if mm.group(3) == "before" else "after"): b[0]["name"]})
    mm = re.search(r"\b(hide|unhide|show)\b", cm)
    if mm and mentioned and re.search(r"\bcolumns?\b|\bhide\b|\bunhide\b", cm) and not re.search(r"\bonly\b|\brows?\b", cm):
        return done({"op": "hide", "cols": [x["name"] for x in mentioned], "show": mm.group(1) != "hide"})
    mm = re.search(r"\bsplit\s+(?:the\s+)?(.+?)(?:\s+column)?\s+into\s+(.+?)(?:\s+(?:by|on|at|using)\s+(?:the\s+)?(comma|space|dash|hyphen|slash|['\"].+?['\"]|\S))?\s*$", cm)
    if mm and cols_in(mm.group(1), s):
        names = [_name(raw, x) for x in re.split(r"\s*,\s*|\s+and\s+", mm.group(2).strip(" .")) if x.strip()]
        sep = {"comma": ",", "space": None, "dash": "-", "hyphen": "-", "slash": "/"}.get(mm.group(3), (mm.group(3) or "").strip("'\"") or None) if mm.group(3) else None
        return done({"op": "split_column", "col": cols_in(mm.group(1), s)[0]["name"], "names": names, **({"sep": sep} if sep else {})})
    r = _new_column(cm, raw, s, m, q)
    if r:
        if r.get("ask"):
            return ask(r["ask"])
        if r.get("unknown"):
            return out  # the model writes that formula
        if r.get("name") and any(x["name"].lower() == str(r["name"]).lower() for x in cols):
            return ask(f"There is already a column '{r['name']}'. Give the new one another name.")
        return done(r)

    # ---------------------------------------------------------------- sort and filter
    if re.search(r"\bsort\b|\bre-?order\b|\b(?:order|arrange)\s+(?:it|them|everything|the (?:rows|data|table|list|sheet|records)|by)\b", cm) and not re.search(r"\bsort of\b", cm):
        spans = col_spans(cm, s)
        if not spans:
            return ask(f"Sort by which column? ({', '.join(x['name'] for x in cols)})")
        by = []
        for i, (a, b, col) in enumerate(spans):
            nxt = spans[i + 1][0] if i + 1 < len(spans) else len(cm)
            d = _desc_for(cm, b, nxt)
            if d is None and i == 0:
                d = _desc_for(cm, 0, a)
            by.append({"col": col["name"], "desc": bool(d)})
        return done({"op": "sort", "by": by})
    if re.search(r"\b(?:clear|remove|turn off|reset|undo)\b.*\bfilters?\b|\bshow (?:all|every)(?: the)? rows\b|\bunfilter\b|\bshow everything\b", cm):
        return done({"op": "filter", "clear": True})
    fm = re.search(r"\bfilter\b|\b(?:show|display|keep)\s+(?:me\s+)?only\b|\bonly\s+(?:show|display|keep)\b|\bjust\s+show\b", cm)
    if fm:
        tm = re.search(r"\btop\s+(\d+)\b", cm)
        if tm and nums:
            tc = [x for x in mentioned if x in nums] or nums[-1:]
            return done({"op": "filter", "col": tc[0]["name"], "cmp": "top", "value": int(tm.group(1))})
        wm = re.search(r"\b(?:where|with|whose|when|that have|which have|for|if|in which)\b(.*)$", cm)
        cond = condition(wm.group(1), s) if wm and cols_in(wm.group(1), s) else (condition(cm, s) if mentioned else None)
        best = metric(t)
        if not cond and best and re.search(r"\b(?:over|above|under|below|more than|less than|at least|at most|between|greater than)\b", cm):
            cond = condition(" " + best["name"].lower() + " " + cm[fm.end():], s, best)
        if not cond:
            vs = values_in(cm, s)
            if vs:
                same_col = [x for x in vs if x[0] is vs[0][0]]
                cond = {"col": vs[0][0]["name"], "op": "in" if len(same_col) > 1 else "=", "value": [x[1] for x in same_col] if len(same_col) > 1 else vs[0][1]}
        if cond:
            op = {"op": "filter", "col": cond["col"], "cmp": cond["op"], "value": cond["value"], **({"value2": cond["value2"]} if cond.get("value2") is not None else {})}
            return done(op)
        return ask("Filter on what? e.g. 'show only Lahore' or 'filter where Amount is above 100,000'.")

    # ---------------------------------------------------------------- highlights
    if re.search(r"\b(?:remove|clear|delete|turn off|take off|get rid of)\b.*\b(?:highlight\w*|conditional format\w*|colou?r(?:s|ing)?|data bars|colou?r scale|heat ?map)\b", cm):
        return done({"op": "clear_highlights", **({"col": mentioned[0]["name"]} if mentioned else {})})
    if re.search(r"\bdata\s*bars?\b|\bin-?cell bars?\b", cm):
        tc = [x for x in mentioned if x in nums] or nums[-1:]
        return done({"op": "conditional", "col": tc[0]["name"], "rule": "bars"}) if tc else ask("Data bars on which number column?")
    if re.search(r"\bcolou?r\s*scale\b|\bheat\s*map\b|\btraffic[- ]light", cm):
        tc = [x for x in mentioned if x in nums] or nums[-1:]
        return done({"op": "conditional", "col": tc[0]["name"], "rule": "scale"}) if tc else ask("A colour scale on which number column?")
    hm = re.search(r"\b(?:highlight|mark|flag|shade|colou?r(?:-code)?)\b", cm)
    if hm and not re.search(r"\b(?:header|heading|title)s?\b", cm):
        colour = next((g.group(1) for g in P.COLOUR_RX.finditer(cm)), None)
        rows_too = bool(re.search(r"\b(?:rows?|whole (?:row|line)|entire (?:row|line)|lines?)\b|\b" + ROWS + r"\s+(?:who|that|which|where|with)\b", cm))
        top = re.search(r"\b(top|bottom|highest|lowest|best|worst)\s+(\d+)\s*(%|percent)?", cm)
        base = {"color": colour} if colour else {}
        if top:
            tc = [x for x in mentioned if x in nums] or nums[-1:]
            if tc:
                return done({"op": "conditional", "col": tc[0]["name"], "rule": "top" if top.group(1) in ("top", "highest", "best") else "bottom",
                             "value": int(top.group(2)), **({"percent": True} if top.group(3) else {}), **base})
        if re.search(r"\bduplicat\w*|\brepeated\b", cm):
            tc = mentioned or [x for x in cols if x["kind"] == "text"][:1]
            return done({"op": "conditional", "col": tc[0]["name"], "rule": "duplicates", **base})
        if re.search(r"\bunique\b", cm) and mentioned:
            return done({"op": "conditional", "col": mentioned[0]["name"], "rule": "unique", **base})
        am = re.search(r"\b(above|below)\s+(?:the\s+)?average\b", cm)
        if am:
            tc = [x for x in mentioned if x in nums] or nums[-1:]
            return done({"op": "conditional", "col": tc[0]["name"], "rule": am.group(1), **base})
        if re.search(r"\b(?:blanks?|empty cells?|missing)\b", cm):
            tc = mentioned or cols
            return done({"op": "conditional", "col": tc[0]["name"], "rule": "blank", **base})
        if re.search(r"\b(?:overdue|late|past due|past their due)\b", cm):
            due = next((x for x in cols if x["kind"] == "date" and re.search(r"due|deadline|expiry|end", x["name"], re.I)), None)
            st = next((x for x in cols if re.search(r"status|paid|state", x["name"], re.I)), None)
            if due:
                done_word = None
                if st:
                    vals = {str(v).strip().lower() for v in XM.values(s, st) if v}
                    done_word = next((w for w in ("paid", "done", "complete", "completed", "closed", "delivered") if w in vals), None)
                f = f"AND([{due['name']}]<TODAY()" + (f',[{st["name"]}]<>"{done_word.title()}"' if done_word else "") + ")"
                return done({"op": "conditional", "formula": f, **(base or {"color": "red"})})
        wm = re.search(r"\b(?:where|with|whose|when|if|that are|which are|that have|which have|who)\b(.*)$", cm)
        cond = None
        if wm and cols_in(wm.group(1), s):
            cond = condition(wm.group(1), s)
        if not cond and mentioned:
            cond = condition(cm[hm.end():], s)
        best = metric(t)
        if not cond and best and re.search(r"\b(?:over|above|under|below|more than|less than|at least|at most|between|greater than|>|<)\b", cm):
            cond = condition(" " + best["name"].lower() + " " + cm[hm.end():], s, best)
            rows_too = rows_too or bool(re.search(r"\b" + ROWS + r"\b", cm))
        if not cond:
            vs = values_in(cm, s)
            if vs:
                cond = {"col": vs[0][0]["name"], "op": "=", "value": vs[0][1]}
                rows_too = True if not re.search(r"\bcells?\b", cm) else rows_too
        if cond:
            if cond["op"] == "in":
                return done(*[{"op": "conditional", "col": cond["col"], "rule": "=", "value": v, "rows": rows_too, **base} for v in cond["value"]])
            rule = {"starts": "contains"}.get(cond["op"], cond["op"])
            return done({"op": "conditional", "col": cond["col"], "rule": rule, "value": cond["value"], **({"value2": cond["value2"]} if cond.get("value2") is not None else {}),
                         **({"rows": True} if rows_too else {}), **base})

    # ---------------------------------------------------------------- totals, summaries, pivots, charts
    if re.search(r"\b(?:total|totals|grand total|sum|average|averages|count|subtotal)\s+row\b|\badd\s+(?:up\s+)?(?:the\s+)?totals?\b(?!\s+(?:column|by|per|for))|\btotal\s+(?:up\s+)?(?:the\s+)?(?:columns?|numbers)\b", cm) or \
            (re.search(r"^\s*(?:total|sum)(?:\s+up)?\s+(?:the\s+)?", cm) and mentioned and not re.search(r"\b(?:by|per|for each|for every|in each)\b", cm)):
        fn = "average" if re.search(r"\baverages?\b|\bmean\b", cm) else "count" if re.search(r"\bcount\b", cm) else "max" if re.search(r"\bhighest|\bmax", cm) else \
            "min" if re.search(r"\blowest|\bmin", cm) else "sum"
        tc = [x for x in mentioned if x in nums]
        return done({"op": "total_row", "fn": fn, **({"cols": [x["name"] for x in tc]} if tc else {})})
    piv = re.search(r"\bpivot\b", cm)
    summ = re.search(r"\b(?:summary|summari[sz]e|breakdown|break(?:\s+it)?\s+down|group(?:ed)?)\b|\b(?:total|sum|average|count|number)\s+(?:of\s+)?(?:the\s+)?(?:[\w ]+?\s+)?(?:by|per|for each|for every|in each)\b|"
                     r"\b(?:monthly|quarterly|yearly|annual)\s+(?:totals?|summary|sales|figures)\b", cm)
    chart = re.search(r"\b(?:chart|graph|plot|visuali[sz]e|bar chart|pie|line chart)\b", cm)
    period = "month" if re.search(r"\bmonth(?:ly|s)?\b|\bper month\b", cm) else "quarter" if re.search(r"\bquarter(?:ly|s)?\b", cm) else \
        "year" if re.search(r"\byear(?:ly|s)?\b|\bannual\b", cm) else None
    if summ and chart and not re.search(r"\b(?:summary|summari[sz]e|breakdown|break(?:\s+it)?\s+down|group(?:ed)?)\b", cm):
        summ = None  # "a bar chart of total by student": the chart op totals a repeating column itself
    if piv or summ:
        bym = re.search(r"\b(?:by|per|for each|for every|in each|across|grouped by|group by)\b(.*)$", cm)
        bycols = cols_in(bym.group(1), s) if bym else []
        datec = next((x for x in cols if x["kind"] == "date"), None)
        if period and datec and not [x for x in bycols if x["kind"] == "date"]:
            bycols = [datec] + [x for x in bycols if x is not datec]
        if not bycols:
            return ask(f"By which column? e.g. 'summary of {(nums[-1]['name'] if nums else 'Amount')} by {next((x['name'] for x in cols if x['kind'] == 'text'), 'City')}'.")
        vals = [x for x in mentioned if x in nums and x not in bycols]
        fn = next((f for rx, f in FNS if re.search(rx, cm[:bym.start()] if bym else cm)), "sum")
        if fn == "count":
            vals = vals[:1]
        kind = None
        if chart:
            kind = "pie" if re.search(r"\bpie\b", cm) else "line" if re.search(r"\bline\b", cm) else "bar" if re.search(r"\bbar\b", cm) else True
        if piv:
            cm_cols = re.search(r"\b(?:across|split by|and by|columns? by|by .*? and)\s+(.+)$", cm)
            colf = [x for x in (cols_in(cm_cols.group(1), s) if cm_cols else []) if x not in bycols[:1]] if len(bycols) > 1 or cm_cols else []
            rowf = bycols[0]
            if period and rowf["kind"] == "date" and len(bycols) > 1:  # "by city and month": cities down, months across
                rowf, colf = next(x for x in bycols if x["kind"] != "date"), [rowf]
            return done({"op": "pivot", "rows": [rowf["name"]], **({"columns": [colf[0]["name"]]} if colf else {}), "values": [x["name"] for x in vals] if vals else [],
                         "fn": fn, **({"period": period} if period else {})})
        return done({"op": "summary", "by": bycols[0]["name"], "values": [x["name"] for x in vals], "fn": fn, **({"period": period} if period and bycols[0]["kind"] == "date" else {}),
                     **({"chart": kind} if kind else {})})
    if chart:
        kind = "pie" if re.search(r"\bpie\b", cm) else "doughnut" if re.search(r"\bdo(?:ugh)?nut\b", cm) else "line" if re.search(r"\bline\b|\bover time\b|\btrend\b", cm) else \
            "bar" if re.search(r"\bbar\b", cm) else "area" if re.search(r"\barea\b", cm) else "column"
        bym = re.search(r"\b(?:by|per|for each|against|vs\.?|versus|across|over|for)\b(.*)$", cm)
        xs = cols_in(bym.group(1), s) if bym else []
        if re.search(r"\bover time\b|\btrend\b", cm) or (period and not xs):
            dc = next((x for x in cols if x["kind"] == "date"), None)
            xs = [dc] if dc else xs
        ys = [x for x in mentioned if x in nums and x not in xs]
        x = xs[0] if xs else next((y for y in mentioned if y not in nums), None)
        place = "new_sheet" if re.search(r"\b(?:new|separate|own|another)\s+(?:sheet|tab)\b", cm) else "beside" if re.search(r"\b(?:beside|next to|right of)\b", cm) else None
        return done({"op": "chart", "type": kind, **({"x": x["name"]} if x else {}), **({"y": [y["name"] for y in ys]} if ys else {}), **({"place": place} if place else {})})

    # ---------------------------------------------------------------- formats and looks
    if re.search(r"\bunfreeze\b|\bremove (?:the )?freeze\b", cm):
        return done({"op": "freeze", "rows": 0, "cols": 0})
    if re.search(r"\bfreeze\b|\b(?:keep|lock)\s+(?:the\s+)?(?:header|top row|first row|titles?)\b", cm):
        rows_n = t["header"]
        cols_n = 0
        rm = re.search(r"\b(?:first|top)\s+(\d+|two|three)\s+rows\b", cm)
        if rm:
            rows_n = {"two": 2, "three": 3}.get(rm.group(1)) or int(rm.group(1))
        cm2 = re.search(r"\bfirst\s+(?:(\d+|two|three)\s+)?columns?\b", cm)
        if cm2:
            cols_n = {"two": 2, "three": 3}.get(cm2.group(1) or "") or int(cm2.group(1) or 1)
            if not re.search(r"\brows?\b|\bheader\b|\btop\b", cm):
                rows_n = 0 if re.search(r"\bonly\b", cm) else rows_n
        return done({"op": "freeze", "rows": rows_n, "cols": cols_n})
    fm = re.search(r"\b(currency|money|rupees?|rs\.?|pkr|dollars?|usd|\$|percent(?:age)?s?|%|dates?|thousands(?: separators?)?|commas?|whole numbers|integers|no decimals|"
                   r"(\d|one|two|three)\s*(?:decimals?|decimal places|dp|places))\b", cm)
    if fm and (re.search(r"\b(?:format|show|display|as|in|into|with|add|put|use|change|turn|set)\b", cm)) and mentioned and not re.search(r"\bhighlight|\bfilter\b|\bround\b", cm):
        w = fm.group(1)
        dm = fm.group(2)
        fmt = ("rs" if re.search(r"rupee|rs|currency|money", w) and not re.search(r"pkr", w) else "pkr" if "pkr" in w else "usd" if re.search(r"dollar|usd|\$", w) else
               "percent1" if re.search(r"percent|%", w) and re.search(r"\b1\b|one\s+decimal", cm) else "percent" if re.search(r"percent|%", w) else
               "date" if "date" in w else "thousands" if re.search(r"thousand|comma", w) else "integer" if re.search(r"whole|integer|no decimals", w) else
               {"1": "decimals1", "one": "decimals1", "2": "decimals2", "two": "decimals2", "3": "0.000", "three": "0.000"}.get(dm or "", "decimals2"))
        return done({"op": "number_format", "cols": [x["name"] for x in mentioned], "format": fmt})
    mm = re.search(r"\bround(?:\s+(?:off|up|down))?\b", cm)
    if mm and (mentioned or nums):
        dm = re.search(r"\b(\d|zero|no|one|two|three)\s*(?:decimals?|decimal places|dp|places)\b|\bto\s+(?:the\s+)?(?:nearest\s+)?(?:whole number|integer|rupee)\b", cm)
        d = 0 if not dm or not dm.group(1) else {"zero": 0, "no": 0, "one": 1, "two": 2, "three": 3}.get(dm.group(1), None)
        d = int(dm.group(1)) if dm and dm.group(1) and d is None else (d if dm else 2 if not re.search(r"whole|integer|nearest", cm) else 0)
        tc = [x for x in mentioned if x["kind"] in ("number", "money", "percent")] or nums[-1:]
        return done(*[{"op": "round", "col": x["name"], "digits": d} for x in tc])
    if re.search(r"\bdrop ?down|\bpick ?list|\bonly allow\b|\brestrict\b|\blimit\b.*\bto\b|\ballowed values\b|\bdata validation\b", cm) and mentioned:
        lm = re.search(r"(?:\bwith\b|:|\ballow(?:ing)?\b|\bvalues?\b|\boptions?\b)\s+(.+)$", cm) or re.search(r"\bto\s+(.+)$", cm)
        items = q if len(q) > 1 else [x.strip(" .'\"") for x in re.split(r"\s*,\s*|\s+or\s+|\s+and\s+", lm.group(1))] if lm else []
        items = [_name(raw, x) for x in items if x and not cols_in(x, s)]
        if not items:
            vals = sorted({str(v) for v in XM.values(s, mentioned[0]) if v not in (None, "")})
            if len(vals) <= 15:
                items = vals
        return done({"op": "validation", "col": mentioned[0]["name"], "list": items}) if items else ask("Which values should the dropdown offer?")
    if re.search(r"\bauto-?fit\b|\bfit\s+(?:the\s+)?columns\b|\b(?:widen|resize)\s+(?:the\s+)?columns\b|\bcolumns?\s+(?:are\s+)?too\s+narrow\b|\bmake\s+(?:the\s+)?columns\s+(?:wider|fit)\b|#####", cm):
        return done({"op": "autofit"})
    tgt = re.search(r"\b(header(?:s| row)?|heading(?:s| row)?|top row|titles?|column names|totals? row|grand total)\b", cm)
    st = _style_set(cm)
    if st and (tgt or mentioned) and re.search(r"\b(?:make|set|colou?r|turn|change|paint|fill|shade|bold|italic|style|format|give)\b", cm):
        target = "totals" if tgt and re.search(r"total", tgt.group(1)) else "header" if tgt else mentioned[0]["name"]
        return done({"op": "style", "target": target, "set": st})
    mm = re.search(r"\breplace\s+(.+?)\s+with\s+(.+?)(?:\s+(?:in|on)\s+(?:the\s+)?(.+?)(?:\s+column)?)?\s*$", cm)
    if mm:
        a, b = (q[0], q[1]) if len(q) >= 2 else (mm.group(1).strip(" '\""), mm.group(2).strip(" '\""))
        incol = cols_in(mm.group(3) or "", s) if mm.group(3) else []
        blob = " ".join(str(v) for r in t["rows"] for v in r if isinstance(v, str)).lower()
        if a.lower() in blob:
            ra = re.search(re.escape(a), raw, re.I)
            rb = re.search(re.escape(b), raw, re.I)
            whole = any(" ".join(str(v).split()).lower() == a.lower() for r in t["rows"] for v in r if isinstance(v, str))
            return done({"op": "replace", "find": ra.group(0) if ra else a, "with": rb.group(0) if rb else b, **({"col": incol[0]["name"]} if incol else {}),
                         **({"whole": True} if whole and incol else {})})
    return out


# ------------------------------------------------------------------------------------------------ questions computed exactly
def question_query(c, m, focus=None):
    """A data question read by rules into a query the program computes (never the model's arithmetic):
    {"sheet", "fn": sum|average|count|max|min|distinct|argmax|argmin|group|top|columns|sheets, "col", "where": [...], "by", "n"}."""
    c = P.normalize(c)
    focus = focus or {}
    sh = sheet_in(c, m) or focus.get("sheet") or m["main"]
    s = XM.sheet(m, sh)
    if not s:
        return None
    if re.search(r"\bwhat (?:are )?(?:the )?(?:sheets|tabs)\b|\bwhich sheets\b|\bhow many sheets\b", c):
        return {"fn": "sheets"}
    if not s.get("table"):
        return None
    t = s["table"]
    if re.search(r"\b(?:what|which) (?:are )?(?:the )?(?:columns|headers|fields)\b|\bhow many columns\b|\blist (?:the )?columns\b", c):
        return {"fn": "columns", "sheet": sh}
    if re.search(r"\b(?:any|are there)\b.*\b(?:errors?|#ref|#div|#n/a|#value)\b", c):
        return {"fn": "errors", "sheet": sh}
    mentioned = cols_in(c, s)
    nums = [x for x in t["cols"] if x["kind"] in ("number", "money", "percent")]
    fnwords = {"average", "total", "sum", "count", "max", "min", "mean", "highest", "lowest"}
    if sum(1 for x in mentioned if x in nums) > 1:
        mentioned = [x for x in mentioned if x["name"].lower() not in fnwords]
    where = []
    wm = re.search(r"\b(?:where|with|whose|for|in|from|that are|which are|that have|who)\b(.*)$", c)
    if wm and cols_in(wm.group(1), s):
        cond = condition(wm.group(1), s)
        if cond:
            where.append(cond)
    datec = next((x for x in t["cols"] if x["kind"] == "date"), None)
    mr = month_range(c, s)
    if mr and datec and not any(w["col"] == datec["name"] for w in where):
        where.append({"col": datec["name"], "op": "between", "value": mr[0], "value2": mr[1]})
    for col, v in values_in(c, s):
        if not any(w["col"] == col["name"] for w in where):
            where.append({"col": col["name"], "op": "=", "value": v})
    if re.search(r"\b(?:duplicates?|repeated)\b", c):
        return {"fn": "duplicates", "sheet": sh, **({"col": mentioned[0]["name"]} if mentioned else {})}
    if re.search(r"\b(?:blanks?|empty cells?|missing values?)\b", c):
        return {"fn": "blanks", "sheet": sh}
    if re.search(r"\bwhat (?:does|is)\b.*\b(?:formula|calculate|mean|compute)\b|\bhow is\b.*\bcalculated\b", c) and mentioned:
        return {"fn": "formula", "sheet": sh, "col": mentioned[0]["name"]}
    bym = re.search(r"\b(?:by|per|for each|for every|in each|broken down by|grouped by)\s+(.+)$", c)
    bycol = cols_in(bym.group(1), s)[0] if bym and cols_in(bym.group(1), s) else None
    if bym and not bycol and re.search(r"\bmonth", bym.group(1)) and datec:
        bycol = datec
    vcol = next((x for x in mentioned if x in nums and x is not bycol and not any(w["col"] == x["name"] for w in where)), None)
    if bycol is not None and bycol in nums and vcol is None and re.search(r"\b(?:top|bottom|best|worst|highest|lowest|most|least)\b", c):
        vcol, bycol = bycol, None
    label = next((x for x in mentioned if x["kind"] == "text" and x is not bycol and not any(w["col"] == x["name"] for w in where)), None)
    if label is None and re.match(r"\s*who\b", c):
        label = next((x for x in t["cols"] if x["kind"] == "text" and PERSON.search(x["name"])), None)
    additive = bool(re.search(r"\b(?:most|least|sold|sell|sells|selling|bought|buy|spent|spend|earned|earn|made|total|sum|revenue|sales|more|less|how much|turnover)\b", c))
    vs = value_of_sales(t)
    if vs and additive and vcol is None:  # "which customer bought the most": quantity times price, row by row
        return {"fn": "argmax" if not re.search(r"\bleast|lowest|fewest|less\b", c) else "argmin", "sheet": sh, "col": f"{vs[0]['name']} x {vs[1]['name']}",
                "product": [vs[0]["name"], vs[1]["name"]], "where": where, **({"label": label["name"]} if label else {}),
                **({"by": bycol["name"]} if bycol else {})} if re.search(r"\b(?:who|which)\b|\b(?:most|least|highest|lowest|top|best|biggest|fewest)\b", c) and not re.search(r"\bhow (?:many|much)\b", c) else \
            {"fn": "sum", "sheet": sh, "col": f"{vs[0]['name']} x {vs[1]['name']}", "product": [vs[0]["name"], vs[1]["name"]], "where": where,
             **({"by": bycol["name"]} if bycol else {})}
    best = metric(t, nums, additive=additive)
    who = re.search(r"\b(?:who|which|what)\b(?:\s+(?:\w+\s+){0,2}?)?\b(?:has|had|got|made|scored|sold|earned|spent|is|was|with|did)?\s*(?:the\s+)?(highest|most|largest|biggest|best|top|lowest|least|smallest|worst|fewest)\b", c)
    nums = [best] + [x for x in nums if x is not best] if best else nums
    nums = nums[::-1]  # nums[-1] is the metric below
    if who and (vcol or nums):
        return {"fn": "argmax" if who.group(1) in ("highest", "most", "largest", "biggest", "best", "top") else "argmin", "sheet": sh,
                "col": (vcol or nums[-1])["name"], "where": where, **({"by": bycol["name"]} if bycol else {}), **({"label": label["name"]} if label else {})}
    top = re.search(r"\b(top|bottom|best|worst|highest|lowest)\s+(\d+)\b", c)
    if top and (vcol or nums):
        return {"fn": "top", "sheet": sh, "col": (vcol or nums[-1])["name"], "n": int(top.group(2)), "desc": top.group(1) in ("top", "best", "highest"), "where": where,
                **({"by": bycol["name"]} if bycol else {}), **({"label": label["name"]} if label else {})}
    if re.search(r"\bhow many (?:different|unique|distinct)\b|\bnumber of (?:different|unique|distinct)\b", c):
        dc = next((x for x in mentioned if x is not bycol), None) or (values_in(c, s) or [(None,)])[0][0]
        if dc:
            return {"fn": "distinct", "sheet": sh, "col": dc["name"], "where": where}
    fn = next((f for rx, f in FNS if re.search(rx, c)), None)
    if fn in (None, "sum") and re.search(r"\bhow much\b|\b(?:sold|sell|sales|revenue|earned|spent|bought|turnover)\b", c) and not re.search(r"\bhow many\b", c):
        fn = "sum"  # "how much did Lahore sell?", "total sales": the money, summed
        if vcol is None:
            if vs:
                return {"fn": "sum", "sheet": sh, "col": f"{vs[0]['name']} x {vs[1]['name']}", "product": [vs[0]["name"], vs[1]["name"]], "where": where,
                        **({"by": bycol["name"]} if bycol else {})}
            vcol = metric(t, [x for x in t["cols"] if x["kind"] in ("number", "money", "percent")], additive=True)
    if fn == "count" or re.search(r"\bhow many\b", c):
        return {"fn": "count", "sheet": sh, "where": where, **({"by": bycol["name"]} if bycol else {})}
    if fn and (vcol or (bycol and nums)):
        return {"fn": fn, "sheet": sh, "col": (vcol or nums[-1])["name"], "where": where, **({"by": bycol["name"]} if bycol else {})}
    return None
