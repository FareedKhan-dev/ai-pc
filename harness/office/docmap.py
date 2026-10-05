"""What is in a Word document, for finding what a request points at and for answering questions about it.

  m = docx_map(doc)                  (a python-docx Document or a path)
  m["items"]     the body in order: {"k": n, "kind": "p"|"table", "style", "level" (headings), "text", "md", "list"}
  m["headings"]  [item]; m["sections"]: [{"h": item index, "end": index after the section, "level", "title"}]
  m["tables"]    [{"k", "t", "rows", "cols", "header", "texts"}]; plus title, page setup, header / footer, contents, stats
  find(m, target)  -> item indexes a target descriptor points at (see TARGETS)
  paragraph_md(p) / set_paragraph_md(p, md)   a paragraph as text with **bold** / *italic* marks, and back (the
                                              paragraph's style and its first run's look are kept)

Target descriptors (the parser and the model both write these):
  {"kind": "all"}  {"kind": "body"}  {"kind": "title"}  {"kind": "headings", "level": 1|2|3|None}
  {"kind": "section", "name": "Introduction" | "n": 2 | "which": "first|last"}         the heading and everything under it
  {"kind": "section_body", ...same}                                                   everything under the heading only
  {"kind": "paragraph", "n": 2 | "which": "first|last", "in": <section descriptor>}   a body paragraph (headings not counted)
  {"kind": "paragraphs", "contains": "text"}     {"kind": "table", "n": 1 | "which": "last" | "all"}
  {"kind": "list", "n": 1 | "which": "last"}     {"kind": "items", "k": [indexes]}
"""
import copy
import re

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

TARGETS = {"all", "body", "title", "headings", "section", "section_body", "paragraph", "paragraphs", "table", "list", "items"}


def _doc(x):
    return Document(str(x)) if not hasattr(x, "element") else x


def heading_level(p):
    name = (p.style.name if p.style is not None else "") or ""
    m = re.match(r"^Heading (\d)$", name)
    if m:
        return int(m.group(1))
    ol = p._p.pPr.find(qn("w:outlineLvl")) if p._p.pPr is not None else None
    if ol is not None and ol.get(qn("w:val")) not in (None, "9"):
        return int(ol.get(qn("w:val"))) + 1
    return None


def is_list(p):
    ppr = p._p.pPr
    name = (p.style.name if p.style is not None else "") or ""
    return name.startswith("List") or (ppr is not None and ppr.find(qn("w:numPr")) is not None)


def paragraph_md(p):
    """The paragraph's text with **bold** and *italic* marks from its runs (fields and drawings left out)."""
    out = []
    for r in p.runs:
        t = r.text
        if not t:
            continue
        b, i = bool(r.bold), bool(r.italic)
        core = t.strip()
        if not core or not (b or i):
            out.append(t)
            continue
        lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
        mark = "**" if b and not i else "*" if i and not b else "***"
        out.append(f"{lead}{mark}{core}{mark}{trail}")
    s = "".join(out)
    return re.sub(r"\*\*\s*\*\*", "", s).replace("****", "")


def set_paragraph_md(p, md, keep_base=True):
    """Replace the paragraph's text with `md` (marks become bold / italic runs). The paragraph's style, its properties
    and the first text run's look (font, size, colour) stay; fields, bookmarks and drawings in it are removed."""
    from .docplan import runs as md_runs
    base = None
    for r in p.runs:
        if r.text.strip():
            base = copy.deepcopy(r._r.rPr) if r._r.rPr is not None else None
            break
    for child in list(p._p):
        if child.tag != qn("w:pPr"):
            p._p.remove(child)
    for t, f in md_runs(md):
        r = p.add_run(t)
        if keep_base and base is not None:
            rpr = copy.deepcopy(base)
            for tag in ("w:b", "w:i", "w:bCs", "w:iCs"):
                for el in rpr.findall(qn(tag)):
                    rpr.remove(el)
            r._r.insert(0, rpr)
        if f.get("bold"):
            r.bold = True
        if f.get("italic"):
            r.italic = True
        if f.get("underline"):
            r.underline = True
    return p


def body_elements(doc):
    """The body's paragraphs and tables in order (the final section properties left out)."""
    out = []
    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            out.append(Paragraph(el, doc))
        elif el.tag == qn("w:tbl"):
            out.append(Table(el, doc))
    return out


def _fields(el):
    codes = [x.text or "" for x in el.iter(qn("w:instrText"))]
    codes += [x.get(qn("w:instr")) or "" for x in el.iter(qn("w:fldSimple"))]
    return " ".join(codes)


def docx_map(src):
    doc = _doc(src)
    items, tables = [], []
    els = body_elements(doc)
    t_n = 0
    for k, el in enumerate(els):
        if isinstance(el, Paragraph):
            lvl = heading_level(el)
            name = el.style.name if el.style is not None else ""
            items.append({"k": k, "kind": "p", "style": name, "level": lvl, "text": el.text, "md": paragraph_md(el), "list": is_list(el),
                          "drawing": bool(el._p.findall(".//" + qn("w:drawing"))), "chart": "drawingml/2006/chart" in el._p.xml if el._p.findall(".//" + qn("w:drawing")) else False,
                          "page_break": any(br.get(qn("w:type")) == "page" for br in el._p.iter(qn("w:br"))) or el.paragraph_format.page_break_before,
                          "toc": "TOC" in _fields(el._p) or name.startswith("TOC ") or name.lower().startswith("toc ")})
        else:
            rows = [[c.text.strip() for c in r.cells] for r in el.rows]
            texts = [x for r in rows for x in r]
            ncols = max((len(r) for r in rows), default=0)
            if len(rows) == 1 and ncols == 1:  # a one-cell box (a callout), not a data table
                items.append({"k": k, "kind": "box", "text": texts[0] if texts else "", "rows": 1, "cols": 1, "header": []})
                continue
            t_n += 1
            tables.append({"k": k, "t": t_n, "rows": len(rows), "cols": ncols, "header": rows[0] if rows else [], "data": rows[:60]})
            items.append({"k": k, "kind": "table", "t": t_n, "text": " | ".join(texts)[:400], "rows": len(rows), "cols": ncols,
                          "header": tables[-1]["header"]})
    _visual_headings(doc, items, els)
    heads = [it for it in items if it["kind"] == "p" and it.get("level")]
    sections = []
    for h in heads:
        end = next((it["k"] for it in items if it["k"] > h["k"] and it["kind"] == "p" and it.get("level") and it["level"] <= h["level"]), len(items))
        sections.append({"h": h["k"], "end": end, "level": h["level"], "title": h["text"].strip()})
    title = next((it for it in items if it["kind"] == "p" and it["style"] == "Title" and it["text"].strip()), None)
    sec = doc.sections[0]
    head_txt = " ".join(p.text for p in sec.header.paragraphs if p.text.strip())
    foot_txt = " ".join(p.text for p in sec.footer.paragraphs if p.text.strip())
    foot_fields = " ".join(_fields(p._p) for p in sec.footer.paragraphs) + " " + " ".join(_fields(p._p) for p in sec.header.paragraphs)
    normal = doc.styles["Normal"]
    words = sum(len(it["text"].split()) for it in items if it["kind"] == "p") + sum(len(t_["texts"]) if "texts" in t_ else 0 for t_ in tables)
    return {"items": items, "headings": heads, "sections": sections, "tables": tables,
            "title": title["text"].strip() if title else (heads[0]["text"].strip() if heads else next((it["text"].strip() for it in items if it["kind"] == "p" and it["text"].strip()), "")),
            "title_k": title["k"] if title else None,
            "page": {"width_cm": round(sec.page_width.cm, 2) if sec.page_width else None, "height_cm": round(sec.page_height.cm, 2) if sec.page_height else None,
                     "orientation": "landscape" if sec.page_width and sec.page_height and sec.page_width > sec.page_height else "portrait",
                     "margins_cm": [round(x.cm, 2) if x is not None else None for x in (sec.top_margin, sec.right_margin, sec.bottom_margin, sec.left_margin)],
                     "columns": _columns(sec)},
            "header": head_txt, "footer": foot_txt, "page_numbers": "PAGE" in foot_fields.upper(),
            "toc": any(it.get("toc") for it in items),
            "fonts": {"body": _style_font(normal), "body_size": normal.font.size.pt if normal.font.size else None},
            "stats": {"paragraphs": sum(1 for it in items if it["kind"] == "p" and it["text"].strip()), "words": words, "tables": len(tables),
                      "headings": len(heads), "images": sum(1 for it in items if it.get("drawing") and not it.get("chart")),
                      "charts": sum(1 for it in items if it.get("chart"))}}


def _visual_headings(doc, items, els):
    """Paragraphs that look like headings without a heading style (short, bold or larger, no closing full stop, followed by
    text): common in documents typed by hand. They get a level and "visual": True, so they can be found and styled."""
    if any(it.get("level") for it in items if it["kind"] == "p"):
        return
    normal = doc.styles["Normal"].font.size
    base = normal.pt if normal else 11.0
    cands = []
    for it, el in zip(items, els):
        if it["kind"] != "p" or it["list"] or it["style"] in ("Title", "Subtitle"):
            continue
        t = it["text"].strip()
        if not t or len(t.split()) > 12 or t.endswith((".", ",", ";", ":")) and not t.endswith(":"):
            continue
        rs = [r for r in el.runs if r.text.strip()]
        if not rs:
            continue
        bold = all(r.bold or (el.style is not None and el.style.font.bold) for r in rs)
        size = max((r.font.size.pt for r in rs if r.font.size), default=base)
        if bold or size >= base + 1.5:
            cands.append((it, size))
    for k, (it, size) in enumerate(cands):
        nxt = next((x for x in items[it["k"] + 1:] if x["kind"] != "p" or x["text"].strip()), None)
        if nxt is None or (nxt["kind"] == "p" and nxt["k"] in {c[0]["k"] for c in cands}) and len(cands) > 1 and k == len(cands) - 1:
            continue
        it["level"] = 1 if size >= max(s for _, s in cands) - 0.5 else 2
        it["visual"] = True


def _columns(sec):
    cols = sec._sectPr.find(qn("w:cols"))
    try:
        return int(cols.get(qn("w:num"))) if cols is not None and cols.get(qn("w:num")) else 1
    except ValueError:
        return 1


def _theme_font(style, which):
    """A theme font ('minorHAnsi' -> the theme's body font) from the document's theme part."""
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        doc_part = style.part.package.main_document_part
        theme = doc_part.part_related_by(RT.THEME)
        from lxml import etree
        root = etree.fromstring(theme.blob)
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        kind = "a:majorFont" if str(which).startswith("major") else "a:minorFont"
        el = root.find(f".//{kind}/a:latin", ns)
        return el.get("typeface") if el is not None else None
    except Exception:  # noqa: BLE001
        return None


def _fonts_of(rpr, style):
    if rpr is None or rpr.find(qn("w:rFonts")) is None:
        return None
    rf = rpr.find(qn("w:rFonts"))
    f = rf.get(qn("w:ascii")) or rf.get(qn("w:hAnsi"))
    if f:
        return f
    t = rf.get(qn("w:asciiTheme")) or rf.get(qn("w:hAnsiTheme"))
    return _theme_font(style, t) if t else None


def _style_font(style):
    """The font a style really draws with, as Word resolves it: the style, the styles it is based on, the document's
    defaults, the theme. (Word moves the body font into the document defaults when it refreshes a contents page.)"""
    st, seen = style, 0
    while st is not None and seen < 12:
        f = _fonts_of(st.element.rPr, style)
        if f:
            return f
        st, seen = st.base_style, seen + 1
    try:
        dd = style.element.getparent().find(qn("w:docDefaults"))
        rpd = dd.find(qn("w:rPrDefault")) if dd is not None else None
        f = _fonts_of(rpd.find(qn("w:rPr")) if rpd is not None else None, style)
        if f:
            return f
    except Exception:  # noqa: BLE001
        pass
    return style.font.name


# ------------------------------------------------------------------------------------------------ targets
def _norm(s):
    return " ".join(re.sub(r"[^\w\s&%-]+", " ", str(s or "").lower()).split())


def find_section(m, desc):
    secs = m["sections"]
    if not secs:
        return None
    if desc.get("n") is not None:
        lvl = desc.get("level") or min(s["level"] for s in secs)
        top = [s for s in secs if s["level"] == lvl]
        try:
            n = int(desc["n"])
        except (TypeError, ValueError):
            return None
        return top[n - 1] if 0 < n <= len(top) else (top[n] if n < 0 and -n <= len(top) else None)
    if desc.get("which") in ("first", "last"):
        lvl = min(s["level"] for s in secs)
        top = [s for s in secs if s["level"] == lvl]
        return top[0] if desc["which"] == "first" else top[-1]
    name = _norm(desc.get("name"))
    if not name:
        return None
    exact = [s for s in secs if _norm(re.sub(r"^\d+(\.\d+)*\.?\s+", "", s["title"])) == name or _norm(s["title"]) == name]
    if exact:
        return exact[0]
    part = [s for s in secs if name in _norm(s["title"]) or (len(name) > 3 and _norm(s["title"]).startswith(name[:6]))]
    if part:
        return min(part, key=lambda s: s["level"])
    words = set(name.split())
    scored = [(len(words & set(_norm(s["title"]).split())) / max(1, len(words)), s) for s in secs]
    best = max(scored, key=lambda x: x[0], default=(0, None))
    return best[1] if best[0] >= 0.5 else None


def find(m, t):
    """Item indexes (m["items"] positions) that a target descriptor points at; [] when it points at nothing."""
    t = t or {"kind": "all"}
    kind = t.get("kind", "all")
    items = m["items"]
    body = [it["k"] for it in items if it["kind"] == "p" and not it.get("level") and it["style"] not in ("Title", "Subtitle", "Caption")
            and it["text"].strip() and not it.get("toc")]
    if kind == "all":
        return [it["k"] for it in items]
    if kind == "body":
        return body
    if kind == "title":
        if m.get("title_k") is not None:
            return [m["title_k"]]
        first = next((it["k"] for it in items if it["kind"] == "p" and it["text"].strip()), None)
        return [first] if first is not None else []
    if kind == "headings":
        lv = t.get("level")
        return [it["k"] for it in m["headings"] if lv in (None, "all") or it["level"] == int(lv)]
    if kind in ("section", "section_body"):
        s = find_section(m, t)
        if not s:
            return []
        return list(range(s["h"] + (1 if kind == "section_body" else 0), s["end"]))
    if kind == "paragraph":
        pool = body
        if t.get("in"):
            s = find_section(m, t["in"])
            if not s:
                return []
            pool = [k for k in body if s["h"] < k < s["end"]]
        if not pool:
            return []
        if t.get("which") == "last":
            return [pool[-1]]
        if t.get("which") == "first":
            return [pool[0]]
        try:
            n = int(t.get("n") or 1)
        except (TypeError, ValueError):
            return []
        return [pool[n - 1]] if 0 < n <= len(pool) else ([pool[n]] if n < 0 and -n <= len(pool) else [])
    if kind == "paragraphs":
        c = _norm(t.get("contains"))
        return [it["k"] for it in items if it["kind"] == "p" and c and c in _norm(it["text"])]
    if kind == "table":
        tabs = m["tables"]
        if not tabs:
            return []
        if t.get("which") == "all" or t.get("n") == "all":
            return [x["k"] for x in tabs]
        if t.get("which") == "last":
            return [tabs[-1]["k"]]
        if t.get("contains"):
            c = _norm(t["contains"])
            return [x["k"] for x in tabs if any(c in _norm(h) for h in x["header"])][:1]
        try:
            n = int(t.get("n") or 1)
        except (TypeError, ValueError):
            return []
        return [tabs[n - 1]["k"]] if 0 < n <= len(tabs) else []
    if kind == "list":
        runs_, cur = [], []
        for it in items:
            if it["kind"] == "p" and it.get("list"):
                cur.append(it["k"])
            elif cur:
                runs_.append(cur)
                cur = []
        if cur:
            runs_.append(cur)
        if not runs_:
            return []
        if t.get("which") == "last":
            return runs_[-1]
        try:
            n = int(t.get("n") or 1)
        except (TypeError, ValueError):
            return []
        return runs_[n - 1] if 0 < n <= len(runs_) else []
    if kind == "items":
        return [k for k in t.get("k") or [] if 0 <= k < len(items)]
    return []


def describe_target(m, t):
    """Words for a target, for replies ("the Introduction section", "paragraph 2 of Conclusion", "table 1")."""
    t = t or {"kind": "all"}
    kind = t.get("kind", "all")
    if kind in ("section", "section_body"):
        s = find_section(m, t)
        return f"the '{s['title']}' section" if s else "that section"
    if kind == "paragraph":
        where = ""
        if t.get("in"):
            s = find_section(m, t["in"])
            where = f" of '{s['title']}'" if s else ""
        which = t.get("which") or (f"{t.get('n')}" if t.get("n") else "1")
        return f"the {which if which in ('first', 'last') else _ordinal(which)} paragraph{where}"
    if kind == "table":
        return "every table" if t.get("which") == "all" else f"table {t.get('n') or t.get('which') or 1}"
    if kind == "headings":
        return f"the level-{t['level']} headings" if t.get("level") else "the headings"
    return {"all": "the whole document", "body": "the body text", "title": "the title", "paragraphs": f"paragraphs with '{t.get('contains')}'",
            "list": "the list", "items": "those parts"}.get(kind, kind)


def _ordinal(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def outline_text(m, limit=60):
    """The document in a few lines, for the model: title, sections with their paragraph counts, tables."""
    lines = [f"TITLE: {m['title'][:100]}", f"PAGE: {m['page']['orientation']}, margins {m['page']['margins_cm']} cm, columns {m['page']['columns']}",
             f"BODY FONT: {m['fonts']['body']} {m['fonts']['body_size']} pt; page numbers: {m['page_numbers']}; contents page: {m['toc']}; "
             f"header: '{m['header'][:60]}'; footer: '{m['footer'][:60]}'",
             f"STATS: {m['stats']}", "SECTIONS:"]
    for s in m["sections"][:limit]:
        n_par = sum(1 for it in m["items"][s["h"] + 1:s["end"]] if it["kind"] == "p" and it["text"].strip() and not it.get("level"))
        n_tab = sum(1 for it in m["items"][s["h"] + 1:s["end"]] if it["kind"] == "table")
        lines.append(f"  {'  ' * (s['level'] - 1)}- [{s['level']}] {s['title'][:80]} ({n_par} paragraphs" + (f", {n_tab} table(s)" if n_tab else "") + ")")
    for tb in m["tables"][:10]:
        lines.append(f"TABLE {tb['t']}: {tb['rows']} rows x {tb['cols']} cols; header {tb['header'][:8]}")
    return "\n".join(lines)
