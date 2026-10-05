"""Tables and charts in a Word document that come from a workbook: written as real Word tables and native charts in the
document's own look, each with an invisible bookmark ('aisrc_...') that links it back to its source, so it can be
refreshed in place when the workbook changes and checked cell by cell against what Excel shows.

Operations (registered in docx_ops.OPS):
  data_table   {data: {header, rows, total}, link, caption, anchor, where}
  data_chart   {data: {header, rows, values}, link, chart, series: [columns], caption, anchor, where}
  data_refresh {link, data, chart}
"""
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from ai_pc.office import docx_build as DB


def _ops():
    """The Word edit engine, imported when used (it registers these operations when it loads)."""
    from ai_pc.office import docx_ops
    return docx_ops


class _Err:
    def __call__(self, msg):
        return _ops().OpError(msg)


OpError = _Err()

C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _norm(s):
    return " ".join(str(s or "").replace(" ", " ").split())


def _next_id(doc):
    ids = [int(x) for x in doc.element.body.xpath(".//w:bookmarkStart/@w:id") if str(x).isdigit()]
    return max(ids, default=0) + 1


def mark(doc, p_el, name):
    """An invisible bookmark around a paragraph's content: kept by Word, the link back to the data's source."""
    bid = str(_next_id(doc))
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), bid)
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), bid)
    ppr = p_el.find(qn("w:pPr"))
    if ppr is not None:
        ppr.addnext(start)
    else:
        p_el.insert(0, start)
    p_el.append(end)


def find_link(doc, name):
    """("table", the w:tbl) or ("chart", the chart's w:p) for a link, or (None, None)."""
    for bs in doc.element.body.iter(qn("w:bookmarkStart")):
        if bs.get(qn("w:name")) != name:
            continue
        p = bs if bs.tag == qn("w:p") else next(bs.iterancestors(qn("w:p")), None)
        if p is None:
            return None, None
        tbl = next(p.iterancestors(qn("w:tbl")), None)
        if tbl is not None:
            return "table", tbl
        return ("chart", p) if next(p.iter(f"{{{C_NS}}}chart"), None) is not None else (None, None)
    return None, None


def links(doc):
    return sorted({bs.get(qn("w:name")) for bs in doc.element.body.iter(qn("w:bookmarkStart")) if str(bs.get(qn("w:name")) or "").startswith("aisrc_")})


def _place(op):
    return {k: op[k] for k in ("anchor", "where") if op.get(k)} or {"where": "end"}


def chart_spec(data, op):
    """Categories from the first column, one series per number column (or the ones named), values as Excel holds them."""
    header, vals = data["header"], data["values"]
    cats = [str(r[0]) for r in data["rows"]]
    names = op.get("series") or []
    cols = [j for j in range(1, len(header)) if (header[j] in names if names else not re.search(r"\bgrand total\b|^total$|%|share|rank", header[j], re.I))
            and sum(1 for r in vals if isinstance(r[j], (int, float)) and not isinstance(r[j], bool)) >= max(1, len(vals) // 2)]
    if not cols:
        raise OpError("the data has no number column to chart")
    kind = op.get("chart") or ("line" if re.search(r"month|date|year|quarter|week", header[0], re.I) and len(cats) > 2 else "bar" if len(cats) > 8 else "column")
    if kind in ("pie", "doughnut"):
        cols = cols[:1]
    series = [{"name": header[j], "values": [float(r[j]) if isinstance(r[j], (int, float)) and not isinstance(r[j], bool) else None for r in vals]} for j in cols[:6]]
    return {"type": "chart", "chart": kind, "categories": cats, "series": series,
            "title": op.get("title") or (series[0]["name"] if len(series) == 1 else ""), "caption": op.get("caption") or data.get("title") or
            (f"{series[0]['name']} by {header[0]}" if len(series) == 1 else f"{header[0]}: {', '.join(s['name'] for s in series)}")}


def _new_charts(doc, before):
    return [p for p in doc.element.body.iter(qn("w:p")) if p not in before and next(p.iter(f"{{{C_NS}}}chart"), None) is not None]


def op_data_table(doc, op, ctx):
    data = op.get("data") or {}
    if not data.get("header") or not data.get("rows"):
        raise OpError("no data to put in the table")
    before = set(doc.element.body.iter(qn("w:tbl")))
    block = {"type": "table", "columns": data["header"], "rows": data["rows"], **({"total_row": data["total"]} if data.get("total") else {}),
             "caption": op.get("caption") or data.get("title") or f"{data['header'][-1]} by {data['header'][0]}"}
    done = _ops().op_insert(doc, {"blocks": [block], **_place(op)}, ctx)
    new = [t for t in doc.element.body.iter(qn("w:tbl")) if t not in before]
    if not new:
        raise OpError("the table could not be written")
    mark(doc, next(new[0].iter(qn("w:p"))), op["link"])
    ctx.setdefault("info", {})["link"] = op["link"]
    return f"table '{block['caption']}' ({len(data['rows'])} rows{' and a total' if data.get('total') else ''}, from {data.get('source') or 'the workbook'}) " + \
        done.split(") ", 1)[-1]


def op_data_chart(doc, op, ctx):
    data = op.get("data") or {}
    if not data.get("rows"):
        raise OpError("no data to chart")
    spec = chart_spec(data, op)
    before = set(doc.element.body.iter(qn("w:p")))
    done = _ops().op_insert(doc, {"blocks": [spec], **_place(op)}, ctx)
    new = _new_charts(doc, before)
    if not new:
        raise OpError("the chart could not be written")
    mark(doc, new[0], op["link"])
    ctx.setdefault("info", {})["chart"] = spec
    return f"{spec['chart']} chart '{spec['caption']}' ({len(spec['categories'])} {data['header'][0].lower()} values, from {data.get('source') or 'the workbook'}) " + \
        done.split(") ", 1)[-1]


def _drop_new_captions(doc, new_els):
    for el in new_els:
        if el.tag == qn("w:p"):
            st = el.find(qn("w:pPr"))
            sid = st.find(qn("w:pStyle")).get(qn("w:val")) if st is not None and st.find(qn("w:pStyle")) is not None else ""
            if sid.lower() == "caption" or re.match(r"^(Table|Figure) \d+", "".join(t.text or "" for t in el.iter(qn("w:t")))):
                el.getparent().remove(el)


def op_data_refresh(doc, op, ctx):
    """The linked table or chart written again from new data, in the same place, under the same caption."""
    kind, el = find_link(doc, op["link"])
    if el is None:
        raise OpError("that table or chart is no longer in the document (it may have been deleted)")
    data = op.get("data") or {}
    th = ctx.get("th") or DB.theme_of(doc)
    if kind == "table":
        new = DB.insert_blocks(doc, [{"type": "table", "columns": data["header"], "rows": data["rows"], **({"total_row": data["total"]} if data.get("total") else {})}],
                               anchor=el, where="after", th=th, numbering=_ops()._counts(doc))
        _drop_new_captions(doc, new)
        tbl = next(x for x in new if x.tag == qn("w:tbl"))
        el.getparent().remove(el)
        mark(doc, next(tbl.iter(qn("w:p"))), op["link"])
        return f"table refreshed ({len(data['rows'])} rows, from {data.get('source') or 'the workbook'})"
    spec = chart_spec(data, op)
    spec.pop("caption", None)
    old = next(el.iter(f"{{{C_NS}}}chart"))
    rid = old.get(R_ID)
    new = DB.insert_blocks(doc, [spec], anchor=el, where="after", th=th, numbering=_ops()._counts(doc))
    _drop_new_captions(doc, new)
    par = next(x for x in new if x.tag == qn("w:p") and next(x.iter(f"{{{C_NS}}}chart"), None) is not None)
    el.getparent().remove(el)
    try:
        doc.part.drop_rel(rid)
    except Exception:  # noqa: BLE001
        pass
    mark(doc, par, op["link"])
    ctx.setdefault("info", {})["chart"] = spec
    return f"chart refreshed ({len(spec['categories'])} points, from {data.get('source') or 'the workbook'})"


def chart_values(doc, p_el):
    """(categories, [[values per series]]) read back from a chart's own part."""
    ch = next(p_el.iter(f"{{{C_NS}}}chart"))
    part = doc.part.related_parts[ch.get(R_ID)]
    root = etree.fromstring(part.blob)
    ns = {"c": C_NS}
    sers = root.findall(".//c:ser", ns)
    cats = [v.text for v in sers[0].findall("./c:cat//c:pt/c:v", ns)] if sers else []
    vals = [[float(v.text) for v in s.findall("./c:val//c:pt/c:v", ns)] for s in sers]
    return cats, vals


def check(op, doc_after):
    """The linked table shows exactly the cells Excel shows; the linked chart holds exactly its values."""
    kind, el = find_link(doc_after, op.get("link"))
    if el is None:
        return False, "the linked table or chart is missing"
    data = op.get("data") or {}
    if kind == "table":
        rows = [[_norm("".join(t.text or "" for t in tc.iter(qn("w:t")))) for tc in tr.iter(qn("w:tc"))] for tr in el.iter(qn("w:tr"))]
        want = [data["header"]] + data["rows"] + ([data["total"]] if data.get("total") else [])
        want = [[_norm(x) for x in r] for r in want]
        bad = sum(1 for a, b in zip(rows, want) for x, y in zip(a, b) if x != y) + abs(len(rows) - len(want))
        return bad == 0, f"{len(want) * len(want[0]) - bad}/{len(want) * len(want[0])} cells equal Excel's"
    cats, vals = chart_values(doc_after, el)
    spec = chart_spec(data, op)
    want_v = [[v for v in s["values"]] for s in spec["series"]]
    ok = [_norm(c) for c in cats] == [_norm(c) for c in spec["categories"]] and all(
        len(a) == len([x for x in b if x is not None]) and all(abs(x - y) < 1e-6 for x, y in zip(a, [x for x in b if x is not None])) for a, b in zip(vals, want_v))
    return ok, f"{len(cats)} categories, {len(vals)} series: {'equal to' if ok else 'different from'} the workbook's values"


OPS = {"data_table": op_data_table, "data_chart": op_data_chart, "data_refresh": op_data_refresh}
