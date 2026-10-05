"""The document plan: what the model writes (content and structure, as simple blocks) and what code makes exact.

  plan = {"doctype": "report", "title": ..., "subtitle": ..., "meta": {"author": ..., "org": ..., "date": ...},
          "theme": "corporate", "accent": "teal", "page": {"size": "A4", "orientation": "portrait"},
          "language": "en", "cover": None, "toc": None, "target_pages": 5, "blocks": [...]}

Blocks (inline **bold** and *italic* work in every text):
  heading {text, level 1-3}            paragraph {text, style: normal|lead|quote|note|small, align}
  bullets {items: [str | {text, items}], numbered}                          quote {text, by}
  table {columns, rows, caption, total: true | [columns]}                   callout {title, text}
  chart {chart: column|bar|line|pie|doughnut|area|stacked, title, categories, series: [{name, values}], caption}
  image {path, width_cm, caption}      kv {items: [[label, value]]}         references {items}
  entry {title, org, place, dates, text, bullets}            (a CV / experience line, dates on the right)
  invoice_items {items: [{desc, qty, price}], currency, tax_rate, tax_label, discount}   (code does the sums)
  address {lines, align}  date {text}  subject {text}  salutation {text}  closing {text, name, title}
  signature {name, title, org, date}   page_break   toc   spacer

resolve(plan) checks and completes it: types and fields cleaned, tables' numbers recognised (right-aligned, totals
summed by code), invoice amounts computed, tables and figures numbered, headings numbered for academic work, a cover
and a table of contents decided from the document type and its length.
"""
import copy
import datetime as dt
import re

from . import themes

BLOCKS = {"heading", "paragraph", "bullets", "table", "chart", "image", "callout", "kv", "quote", "entry", "invoice_items", "address", "date",
          "subject", "salutation", "closing", "signature", "references", "page_break", "toc", "spacer"}
CHARTS = {"column", "bar", "line", "pie", "doughnut", "area", "stacked", "stacked_bar"}
COVER_TYPES = {"report", "proposal", "assignment", "thesis", "research", "business_plan", "manual"}
TOC_TYPES = COVER_TYPES
NO_HEADER = {"letter", "application", "cv", "certificate", "invoice", "quotation", "notice", "memo"}
NUM = re.compile(r"^\s*(?P<pre>[A-Za-z$€£₹]{0,4}\.?\s?)(?P<num>[-+]?\d[\d,]*(?:\.\d+)?)\s*(?P<post>%|[A-Za-z]{0,4})\s*$")


def number(v):
    """(value, prefix, suffix, decimals) for a cell that is a number ("1,200", "Rs. 450.50", "12%"), else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        s = repr(float(v))
        return float(v), "", "", 0 if float(v).is_integer() else min(2, len(s.split(".")[1]))
    m = NUM.match(str(v))
    if not m:
        return None
    raw = m.group("num").replace(",", "")
    try:
        x = float(raw)
    except ValueError:
        return None
    dec = len(raw.split(".")[1]) if "." in raw else 0
    return x, m.group("pre"), m.group("post"), min(dec, 2)


def fmt(x, dec=0, pre="", post=""):
    s = f"{x:,.{dec}f}"
    return f"{pre}{s}{post}" if not post else f"{pre}{s}{'' if post == '%' else ' '}{post}".replace(" %", "%")


def _text(v):
    return " ".join(str(v if v is not None else "").split())


def _clean_block(b):
    if not isinstance(b, dict):
        return None
    t = str(b.get("type") or "").lower().strip()
    t = {"h": "heading", "title": "heading", "para": "paragraph", "p": "paragraph", "list": "bullets", "bullet": "bullets",
         "numbered": "bullets", "ol": "bullets", "ul": "bullets", "figure": "image", "graph": "chart", "break": "page_break",
         "pagebreak": "page_break", "note": "callout", "box": "callout", "keyvalue": "kv", "items": "invoice_items",
         "experience": "entry", "job": "entry", "reference": "references", "bibliography": "references"}.get(t, t)
    if t not in BLOCKS:
        return None
    b = {**b, "type": t}
    if t == "heading":
        b["text"] = _text(b.get("text"))
        b["level"] = max(1, min(3, int(b.get("level") or 1)))
        return b if b["text"] else None
    if t in ("paragraph", "quote", "date", "subject", "salutation"):
        b["text"] = str(b.get("text") or "").strip()
        return b if b["text"] else None
    if t == "bullets":
        def items(xs):
            out = []
            for x in xs or []:
                if isinstance(x, dict):
                    tx = _text(x.get("text"))
                    if tx:
                        out.append({"text": tx, "items": items(x.get("items"))})
                elif isinstance(x, list):
                    if out:
                        out[-1]["items"] = out[-1].get("items", []) + items(x)
                elif _text(x):
                    out.append({"text": _text(x), "items": []})
            return out
        b["items"] = items(b.get("items"))
        b["numbered"] = bool(b.get("numbered")) or str(b.get("style", "")).lower() in ("numbered", "number", "ol") or b.get("type0") == "numbered"
        return b if b["items"] else None
    if t == "table":
        cols = [_text(c) for c in b.get("columns") or b.get("header") or []]
        rows = [list(r) if isinstance(r, (list, tuple)) else [r] for r in b.get("rows") or [] if r is not None]
        if not cols and rows:
            cols, rows = [_text(c) for c in rows[0]], rows[1:]
        n = len(cols)
        if not n or not rows:
            return None
        b["columns"] = cols
        b["rows"] = [[("" if c is None else c) for c in (r + [""] * n)[:n]] for r in rows]
        return b
    if t == "chart":
        kind = str(b.get("chart") or b.get("kind") or "column").lower().replace(" ", "_")
        kind = {"bar_chart": "bar", "column_chart": "column", "pie_chart": "pie", "line_chart": "line", "donut": "doughnut",
                "horizontal_bar": "bar", "stacked_column": "stacked", "histogram": "column"}.get(kind, kind)
        b["chart"] = kind if kind in CHARTS else "column"
        cats = [_text(c) for c in b.get("categories") or b.get("labels") or []]
        series = []
        for s in b.get("series") or ([{"name": b.get("title") or "Value", "values": b.get("values")}] if b.get("values") else []):
            if not isinstance(s, dict):
                continue
            vals = []
            for v in (s.get("values") or [])[:len(cats)]:
                p = number(v)
                vals.append(p[0] if p else None)
            if cats and len(vals) == len(cats) and any(v is not None for v in vals):
                series.append({"name": _text(s.get("name")) or "Series", "values": vals})
        if not cats or not series:
            return None
        if b["chart"] in ("pie", "doughnut"):
            series = series[:1]
        b["categories"], b["series"] = cats, series
        return b
    if t == "image":
        return b if b.get("path") else None
    if t in ("callout",):
        b["text"] = str(b.get("text") or "").strip()
        return b if b["text"] or b.get("title") else None
    if t == "kv":
        its = []
        for x in b.get("items") or []:
            if isinstance(x, (list, tuple)) and len(x) >= 2:
                its.append([_text(x[0]), str(x[1] if x[1] is not None else "")])
            elif isinstance(x, dict) and (x.get("label") or x.get("key")):
                its.append([_text(x.get("label") or x.get("key")), str(x.get("value") or "")])
        b["items"] = its
        return b if its else None
    if t == "entry":
        b["title"] = _text(b.get("title") or b.get("role") or b.get("degree"))
        b["bullets"] = [_text(x) for x in b.get("bullets") or [] if _text(x)]
        return b if b["title"] else None
    if t == "invoice_items":
        its = []
        for x in b.get("items") or []:
            if not isinstance(x, dict):
                continue
            q, p = number(x.get("qty", 1)), number(x.get("price", x.get("rate", x.get("unit_price"))))
            if _text(x.get("desc") or x.get("description") or x.get("item")) and p:
                its.append({"desc": _text(x.get("desc") or x.get("description") or x.get("item")), "qty": q[0] if q else 1.0, "price": p[0]})
        b["items"] = its
        return b if its else None
    if t in ("address",):
        b["lines"] = [_text(x) for x in b.get("lines") or [] if _text(x)]
        return b if b["lines"] else None
    if t == "references":
        b["items"] = [_text(x) for x in b.get("items") or [] if _text(x)]
        return b if b["items"] else None
    return b


def resolve(plan):
    """The plan checked and completed (see the module notes). Returns a new dict."""
    p = copy.deepcopy(plan or {})
    p["doctype"] = str(p.get("doctype") or "other").lower().replace(" ", "_")
    p["title"] = _text(p.get("title"))
    p["subtitle"] = _text(p.get("subtitle"))
    p["meta"] = {k: "\n".join(_text(x) for x in str(v).splitlines() if _text(x)) for k, v in (p.get("meta") or {}).items() if _text(v)}
    p["meta"].setdefault("date", dt.date.today().strftime("%d %B %Y"))
    th = themes.get(p.get("theme"), p.get("accent"), p["doctype"])
    p["theme"] = th["name"]
    tight = int(p.get("tight") or 0)  # the fixer's answer to a last page that is almost empty
    if tight:
        th["size"] = max(9.5, th["size"] - 0.5 * tight)
        th["after"] = max(2.0, round(th["after"] * 0.65 ** tight, 1))
        th["line"] = max(1.0, round(th["line"] - 0.05 * tight, 2))
        th["h_scale"] = 0.7 ** tight
        th["margins"] = max(1.6, th["margins"] - 0.4 * tight)
    p["th"] = th
    page = p.get("page") or {}
    p["page"] = {"size": "Letter" if str(page.get("size", "")).lower() in ("letter", "us letter") else "A4",
                 "orientation": "landscape" if str(page.get("orientation", "")).lower() == "landscape" or p["doctype"] == "certificate" else "portrait",
                 "margins": float(page.get("margins") or th["margins"])}
    p["language"] = "ur" if str(p.get("language", "")).lower() in ("ur", "urdu") else "en"
    blocks = []
    for i, b in enumerate(p.get("blocks") or []):
        x = _clean_block(b)
        if x:
            x["src"] = i  # its place in the plan as written (fixes point back to it)
            blocks.append(x)
    # one lead paragraph at most (the opening): a larger grey paragraph in every section reads as inconsistent
    leads = [b for b in blocks if b["type"] == "paragraph" and str(b.get("style") or "").lower() == "lead"]
    for b in leads[1:]:
        b["style"] = "normal"
    # tables: numbers right-aligned, totals summed by code (a model's arithmetic is not trusted)
    for b in blocks:
        if b["type"] == "table":
            n = len(b["columns"])
            numeric = []
            for j in range(n):
                cells = [r[j] for r in b["rows"] if _text(r[j])]
                parsed = [number(c) for c in cells]
                numeric.append(bool(cells) and sum(1 for x in parsed if x) >= 0.7 * len(cells) and j > 0)
            b["numeric"] = numeric
            want = b.get("total")
            if want:
                cols = [j for j in range(n) if numeric[j] and (want is True or b["columns"][j] in (want if isinstance(want, list) else []))]
                cols = [j for j in cols if not re.search(r"%|rate|percent|year|no\.?$|#|id\b|code|phone", b["columns"][j], re.I)]
                if cols:
                    row = ["Total"] + [""] * (n - 1)
                    for j in cols:
                        ps = [number(r[j]) for r in b["rows"]]
                        ps = [x for x in ps if x]
                        dec = max((x[3] for x in ps), default=0)
                        row[j] = fmt(sum(x[0] for x in ps), dec, ps[0][1] if ps else "", ps[0][2] if ps else "")
                    b["total_row"] = row
        if b["type"] == "invoice_items":
            cur = _text(b.get("currency") or "Rs.")
            sub = sum(x["qty"] * x["price"] for x in b["items"])
            dec = 0 if all(float(x["qty"] * x["price"]).is_integer() for x in b["items"]) else 2
            disc = 0.0
            if b.get("discount"):
                d = number(b["discount"])
                if d:
                    disc = sub * d[0] / 100 if d[2] == "%" else d[0]
            rate = number(b.get("tax_rate") or 0)
            r = (rate[0] / 100 if rate and (rate[2] == "%" or rate[0] > 1) else (rate[0] if rate else 0.0))
            tax = round((sub - disc) * r, 2)
            total = sub - disc + tax
            if not float(tax).is_integer() or not float(total).is_integer():
                dec = 2
            b["computed"] = {"currency": cur, "decimals": dec, "lines": [x["qty"] * x["price"] for x in b["items"]], "subtotal": sub,
                             "discount": disc, "tax_rate": r, "tax": tax, "total": total,
                             "tax_label": _text(b.get("tax_label")) or (f"Sales tax ({r * 100:g}%)" if r else "")}
    # numbering: tables, figures; academic headings 1 / 1.1 / 1.1.1
    nt = nf = 0
    counters = [0, 0, 0]
    for b in blocks:
        if b["type"] == "table" and (b.get("caption") or len(b["rows"]) > 2):
            nt += 1
            b["label"] = f"Table {nt}"
        elif b["type"] in ("chart", "image") and (b.get("caption") or b["type"] == "chart"):
            nf += 1
            b["label"] = f"Figure {nf}"
        elif b["type"] == "heading" and th["numbered"] and p["doctype"] not in ("letter", "application", "cv", "certificate", "invoice"):
            lv = b["level"]
            if not re.match(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[A-Z]\.)\s", b["text"]) and not re.match(
                    r"^(?:references|bibliography|acknowledg|abstract|appendix|table of contents|contents)", b["text"], re.I):
                counters[lv - 1] += 1
                for k in range(lv, 3):
                    counters[k] = 0
                b["text"] = ".".join(str(c) for c in counters[:lv]) + " " + b["text"]
    h1 = sum(1 for b in blocks if b["type"] == "heading" and b["level"] == 1)
    long_doc = (p.get("target_pages") or 0) >= 5 or h1 >= 5
    if p.get("cover") is None:
        p["cover"] = p["doctype"] in COVER_TYPES and (long_doc or p["doctype"] in ("assignment", "thesis", "proposal"))
    if p.get("toc") is None:
        p["toc"] = p["doctype"] in TOC_TYPES and long_doc and h1 >= 3 and not any(b["type"] == "toc" for b in blocks)
    if p.get("header") is None:
        p["header"] = "" if p["doctype"] in NO_HEADER else (p["title"][:80] if p["cover"] or long_doc else "")
    foot = p.get("footer") if isinstance(p.get("footer"), dict) else {}
    p["footer"] = {"page_numbers": foot.get("page_numbers", p["doctype"] not in ("certificate", "cv", "letter", "application", "notice", "invoice")),
                   "text": _text(foot.get("text"))}
    p["blocks"] = blocks
    return p


INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|__[^_]+__)")


def runs(text):
    """[(text, {"bold": bool, "italic": bool})] from **bold**, *italic*, __underline__ marks."""
    out = []
    for part in INLINE.split(str(text or "")):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append((part[2:-2], {"bold": True}))
        elif part.startswith("__") and part.endswith("__") and len(part) > 4:
            out.append((part[2:-2], {"underline": True}))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append((part[1:-1], {"italic": True}))
        else:
            out.append((part, {}))
    return out


def plain(text):
    return "".join(t for t, _ in runs(text))
