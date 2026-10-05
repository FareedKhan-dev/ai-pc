"""Edits on a real Word document, in place (python-docx keeps every part it does not touch: the client's own styles,
images, fields, comments). Each edit is an operation; each has a check that reads the result back.

  done = apply(doc, op, ctx)        doc: python-docx Document; ctx: {"planner", "th", "folder", "title"}; raises OpError
  ok, what = check(op, before, after, info)     before / after: docmap.docx_map of the versions; info: what apply returned

Operations ({"op": ..., "target": a docmap target descriptor where it applies}):
  style        {target, set: {font, size (pt or "+2"/"-1"), color, bold, italic, underline, align, line_spacing, space_after,
                space_before, first_line_indent, highlight, case}}            headings and the body change their Word styles
  page         {set: {margins (cm, or {top, bottom, left, right}), orientation, size: A4|Letter|Legal, columns}}
  page_numbers {position: bottom|top, align: left|center|right, format: "Page X of Y"|"X"|"Page X", remove: bool}
  header / footer {text, align, remove: bool}       toc {remove: bool}         cover {title, subtitle, lines: [...], remove}
  theme        {name: corporate|academic|modern|elegant|minimal|warm, accent}  every style and table restyled, text kept
  table_style  {target}                              structure {}  (bold "headings" typed by hand become real headings)
  heading_numbers {remove: bool}                     list {target, kind: bullets|numbered|none}
  page_breaks  {before_sections: bool, remove: bool}
  replace      {find, with, target, case: bool, whole_word: bool}
  emphasis     {find | terms | auto: n, set: {bold, italic, underline, color, highlight}, target}
  delete       {target}                              move {target, to: {target, where: before|after}}
  insert       {where: before|after|start|end, anchor: target, blocks: [...] | text: "..." | about: "...", words, heading}
  rewrite      {target, instruction, keep_count: bool}         translate {target, language}
  summarize    {target (what to read), kind: "executive summary|abstract|key points|conclusion", where, anchor, words}
  table_sort   {target, by, desc}     table_add_row {target, values, position}    table_delete_row {target, row | match}
  table_add_column {target, name, values | formula: "[Qty] * [Price]" | percent_of: column}    table_delete_column {target, name}
  table_total  {target, columns}      chart {target (a table), chart, categories: column, values: [columns], title}
  image        {path, anchor, where, width_cm, caption}
"""
import copy
import re
from pathlib import Path

from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

from . import docmap as DM
from . import docx_build as DB
from . import themes
from .docplan import fmt as num_fmt
from .docplan import number

ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER, "centre": WD_ALIGN_PARAGRAPH.CENTER,
         "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY, "justified": WD_ALIGN_PARAGRAPH.JUSTIFY}
HIGHLIGHT = {"yellow": WD_COLOR_INDEX.YELLOW, "green": WD_COLOR_INDEX.BRIGHT_GREEN, "blue": WD_COLOR_INDEX.TURQUOISE, "pink": WD_COLOR_INDEX.PINK,
             "red": WD_COLOR_INDEX.RED, "grey": WD_COLOR_INDEX.GRAY_25, "gray": WD_COLOR_INDEX.GRAY_25}
PAGE_SIZES = {"a4": (21.0, 29.7), "letter": (21.59, 27.94), "legal": (21.59, 35.56), "a5": (14.8, 21.0)}
SKIP_NUMBER = re.compile(r"^(?:references|bibliography|works cited|acknowledg\w*|abstract|appendix|contents|table of contents|glossary)\b", re.I)


class OpError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ helpers
def els(doc):
    return DM.body_elements(doc)


def _targets(doc, target, need=True):
    m = DM.docx_map(doc)
    ks = DM.find(m, target or {"kind": "all"})
    if need and not ks:
        raise OpError(f"{DM.describe_target(m, target)} is not in the document")
    e = els(doc)
    return m, [e[k] for k in ks if k < len(e)]


def _paras(objs):
    """Every paragraph in the objects (paragraphs themselves, and the paragraphs inside tables)."""
    out = []
    for o in objs:
        if isinstance(o, Paragraph):
            out.append(o)
        elif isinstance(o, Table):
            for row in o.rows:
                for c in row.cells:
                    out.extend(c.paragraphs)
    return out


def colour(v):
    v = str(v or "").strip().lower()
    hx = themes.COLOUR_WORDS.get(v) or {"white": "FFFFFF", "dark blue": "1F3864", "light blue": "5B9BD5", "dark red": "8B0000",
                                         "violet": "6A1B9A", "yellow": "C9A000", "dark grey": "404040", "dark gray": "404040"}.get(v)
    if not hx and re.fullmatch(r"#?[0-9a-f]{6}", v):
        hx = v.lstrip("#")
    if not hx:
        raise OpError(f"no colour '{v}'")
    return hx.upper()


def _rfonts(rpr, name):
    DB._rfonts(rpr, name)


def _clear_run(r, props):
    rpr = r._r.rPr
    if rpr is None:
        return
    tags = {"font": ["w:rFonts"], "size": ["w:sz", "w:szCs"], "color": ["w:color"], "bold": ["w:b", "w:bCs"], "italic": ["w:i", "w:iCs"],
            "underline": ["w:u"], "highlight": ["w:highlight"]}
    for p_ in props:
        for t in tags.get(p_, []):
            for el in rpr.findall(qn(t)):
                if t == "w:rFonts" and any(str(el.get(qn(a)) or "").lower() in ("symbol", "wingdings") for a in ("w:ascii", "w:hAnsi")):
                    continue
                rpr.remove(el)


def _size_of(style_or_run, default=11.0):
    s = style_or_run.font.size
    return s.pt if s is not None else default


def _new_size(cur, v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().lower()
    if t in ("bigger", "larger", "up"):
        return cur + 2
    if t in ("smaller", "down"):
        return max(6, cur - 2)
    m = re.fullmatch(r"([+-])\s*(\d+(?:\.\d+)?)", t)
    if m:
        return max(6.0, cur + (float(m.group(2)) if m.group(1) == "+" else -float(m.group(2))))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:pt|px)?", t)
    if m:
        return float(m.group(1))
    raise OpError(f"no size '{v}'")


def _line_spacing(v):
    t = str(v).strip().lower()
    return {"single": 1.0, "1": 1.0, "1.0": 1.0, "1.15": 1.15, "1.5": 1.5, "one and a half": 1.5, "double": 2.0, "2": 2.0, "2.0": 2.0}.get(t) or float(t)


def _case(text, how):
    if how == "upper":
        return text.upper()
    if how == "lower":
        return text.lower()
    if how == "title":
        small = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "by", "with", "vs"}
        ws = text.split(" ")
        return " ".join(w if (w.isupper() and len(w) > 1) else (w.capitalize() if i == 0 or w.lower() not in small else w.lower()) for i, w in enumerate(ws))
    if how == "sentence":
        t = text.lower()
        return t[:1].upper() + t[1:]
    return text


def _style(doc, name):
    try:
        return doc.styles[name]
    except KeyError:
        return None


def _set_style(style, s, th_size=11.0):
    """Font properties on a Word style (what every paragraph of that style shows unless a run overrides it)."""
    f = style.font
    if s.get("font"):
        DB._style_font(style, s["font"])
    if s.get("size") is not None:
        f.size = Pt(_new_size(_size_of(style, th_size), s["size"]))
    if s.get("color"):
        f.color.rgb = RGBColor.from_string(colour(s["color"]))
    for k in ("bold", "italic"):
        if s.get(k) is not None:
            setattr(f, k, bool(s[k]))
    if s.get("underline") is not None:
        f.underline = bool(s["underline"])
    pf = style.paragraph_format
    if s.get("align"):
        pf.alignment = ALIGN.get(str(s["align"]).lower())
    if s.get("line_spacing") is not None:
        pf.line_spacing = _line_spacing(s["line_spacing"])
    if s.get("space_after") is not None:
        pf.space_after = Pt(float(s["space_after"]))
    if s.get("space_before") is not None:
        pf.space_before = Pt(float(s["space_before"]))
    if s.get("first_line_indent") is not None:
        pf.first_line_indent = Cm(float(s["first_line_indent"]))


def _set_runs(p, s):
    """The same properties straight on a paragraph and its runs (parts of a document, not a whole style)."""
    for r in p.runs:
        if s.get("font"):
            _rfonts(r._r.get_or_add_rPr(), s["font"])
        if s.get("size") is not None:
            r.font.size = Pt(_new_size(r.font.size.pt if r.font.size else _size_of(p.style) if p.style is not None else 11.0, s["size"]))
        if s.get("color"):
            r.font.color.rgb = RGBColor.from_string(colour(s["color"]))
        for k in ("bold", "italic"):
            if s.get(k) is not None:
                setattr(r.font, k, bool(s[k]))
        if s.get("underline") is not None:
            r.font.underline = bool(s["underline"])
        if s.get("highlight"):
            r.font.highlight_color = HIGHLIGHT.get(str(s["highlight"]).lower(), WD_COLOR_INDEX.YELLOW)
        if s.get("case"):
            r.text = _case(r.text, s["case"])
    pf = p.paragraph_format
    if s.get("align"):
        pf.alignment = ALIGN.get(str(s["align"]).lower())
    if s.get("line_spacing") is not None:
        pf.line_spacing = _line_spacing(s["line_spacing"])
    if s.get("space_after") is not None:
        pf.space_after = Pt(float(s["space_after"]))
    if s.get("space_before") is not None:
        pf.space_before = Pt(float(s["space_before"]))
    if s.get("first_line_indent") is not None:
        pf.first_line_indent = Cm(float(s["first_line_indent"]))


def split_runs_at(p, start, end):
    """Runs of p rearranged so that characters [start, end) are whole runs of their own; returns those runs."""
    pos, out = 0, []
    for r in all_runs(p):
        t = r.text
        a, b = pos, pos + len(t)
        pos = b
        if b <= start or a >= end or not t:
            continue
        cut_a, cut_b = max(start, a) - a, min(end, b) - a
        if cut_b < len(t):  # tail stays outside
            tail = copy.deepcopy(r._r)
            r._r.addnext(tail)
            Paragraph(p._p, p._parent).runs  # noqa: B018
            from docx.text.run import Run
            Run(tail, p).text = t[cut_b:]
            r.text = t[:cut_b]
            t = r.text
        if cut_a > 0:
            head = copy.deepcopy(r._r)
            r._r.addprevious(head)
            from docx.text.run import Run
            Run(head, p).text = t[:cut_a]
            r.text = t[cut_a:]
        out.append(r)
    return out


def all_runs(p):
    """The paragraph's runs in order, those inside hyperlinks included (python-docx's p.runs leaves them out)."""
    from docx.text.run import Run
    return [Run(r, p) for r in p._p.xpath("./w:r | ./w:hyperlink/w:r | ./w:ins/w:r | ./w:smartTag/w:r")]


def replace_in_paragraph(p, find, repl, case=False, whole=True):
    """Replace every `find` in the paragraph, across runs, keeping each run's look (the match takes the look of the run
    it starts in). An all-capitals or Title-case match gets the replacement in the same case. Returns the count."""
    runs = all_runs(p)
    texts = [r.text for r in runs]
    full = "".join(texts)
    if not find or (find.lower() not in full.lower()):
        return 0
    pat = (r"(?<!\w)" if whole and find[:1].isalnum() else "") + re.escape(find) + (r"(?!\w)" if whole and find[-1:].isalnum() else "")
    ms = list(re.finditer(pat, full, 0 if case else re.I))
    if not ms:
        return 0
    bounds, pos = [], 0
    for t in texts:
        bounds.append((pos, pos + len(t)))
        pos += len(t)
    for m in reversed(ms):
        s, e = m.span()
        got = m.group(0)
        new = repl.upper() if got.isupper() and len(got) > 1 and not repl.isupper() else (repl[:1].upper() + repl[1:] if got[:1].isupper() and repl[:1].islower() else repl)
        idx = [i for i, (a, b) in enumerate(bounds) if a < e and b > s] or [i for i, (a, b) in enumerate(bounds) if a <= s < b]
        if not idx:
            continue
        f = idx[0]
        a, b = bounds[f]
        texts[f] = texts[f][:s - a] + new + (texts[f][e - a:] if e <= b else "")
        for i in idx[1:]:
            a2, b2 = bounds[i]
            texts[i] = texts[i][e - a2:] if e < b2 else ""
    for r, t in zip(runs, texts):
        if r.text != t:
            r.text = t
    return len(ms)


def _all_paragraphs(doc, include_hf=True):
    ps = list(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                ps.extend(c.paragraphs)
    if include_hf:
        for s in doc.sections:
            for part in (s.header, s.footer, s.first_page_header, s.first_page_footer):
                try:
                    ps.extend(part.paragraphs)
                except Exception:  # noqa: BLE001
                    continue
    return ps


def _rtl(p, lang="ur-PK", font="Segoe UI"):
    ppr = p._p.get_or_add_pPr()
    if ppr.find(qn("w:bidi")) is None:
        ppr.append(OxmlElement("w:bidi"))
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for r in p.runs:
        rpr = r._r.get_or_add_rPr()
        if rpr.find(qn("w:rtl")) is None:
            rpr.append(OxmlElement("w:rtl"))
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        rf.set(qn("w:cs"), font)
        lang_el = rpr.find(qn("w:lang"))
        if lang_el is None:
            lang_el = OxmlElement("w:lang")
            rpr.append(lang_el)
        lang_el.set(qn("w:bidi"), lang)


def _delete(objs):
    for o in objs:
        el = o._p if isinstance(o, Paragraph) else o._tbl
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _el(o):
    return o._p if isinstance(o, Paragraph) else o._tbl


def _counts(doc):
    m = DM.docx_map(doc)
    caps = [it["text"] for it in m["items"] if it["kind"] == "p" and it["style"] == "Caption"]
    return (sum(1 for c in caps if c.startswith("Table ")), sum(1 for c in caps if c.startswith("Figure ")))


# ------------------------------------------------------------------------------------------------ operations
def op_style(doc, op, ctx):
    s = dict(op.get("set") or {})
    if not s:
        raise OpError("nothing to change")
    t = op.get("target") or {"kind": "all"}
    kind = t.get("kind")
    props = [k for k in ("font", "size", "color", "bold", "italic", "underline") if s.get(k) is not None]
    if kind == "headings":
        lv = t.get("level")
        levels = [int(lv)] if lv not in (None, "all") else [1, 2, 3]
        m = DM.docx_map(doc)
        visual = [it for it in m["headings"] if it.get("visual")]
        for L in levels:
            st = _style(doc, f"Heading {L}")
            if st is not None and not visual:
                _set_style(st, s)
        e = els(doc)
        for it in m["headings"]:
            if it["level"] in levels:
                p = e[it["k"]]
                if it.get("visual") or s.get("case") or s.get("highlight"):
                    _set_runs(p, s)
                else:
                    for r in p.runs:
                        _clear_run(r, props)
        return f"{DM.describe_target(m, t)}: " + _say_set(s)
    if kind in ("all", "body") and not s.get("case") and not s.get("highlight"):
        normal = doc.styles["Normal"]
        _set_style(normal, s)
        if s.get("font"):  # the document's defaults and the list styles follow; Word's theme fonts no longer win
            dd = doc.styles.element.find(qn("w:docDefaults"))
            rpr = dd.find(".//" + qn("w:rPr")) if dd is not None else None
            if rpr is not None:
                _rfonts(rpr, s["font"])
        m = DM.docx_map(doc)
        e = els(doc)
        skip = {it["k"] for it in m["headings"]} | ({m["title_k"]} if m.get("title_k") is not None else set())
        for it in m["items"]:
            if it["kind"] == "p" and (kind == "all" or it["k"] not in skip):
                for r in e[it["k"]].runs:
                    _clear_run(r, [p_ for p_ in props if p_ in ("font", "size", "color")])
                if s.get("align") or s.get("line_spacing") is not None or s.get("first_line_indent") is not None or s.get("space_after") is not None:
                    pf = e[it["k"]].paragraph_format
                    if s.get("align") and it["k"] not in skip and not it.get("list"):
                        pf.alignment = None  # the style's alignment applies
                    if s.get("line_spacing") is not None:
                        pf.line_spacing = None
                    if s.get("space_after") is not None and it["k"] not in skip:
                        pf.space_after = None
                    if s.get("first_line_indent") is not None and it.get("list"):
                        pf.first_line_indent = None
        if kind == "all":
            for L in (1, 2, 3):
                st = _style(doc, f"Heading {L}")
                if st is not None and s.get("font"):
                    DB._style_font(st, s["font"])
                if st is not None and s.get("color"):
                    st.font.color.rgb = RGBColor.from_string(colour(s["color"]))
            ti = _style(doc, "Title")
            if ti is not None and s.get("font"):
                DB._style_font(ti, s["font"])
            for tb in doc.tables:  # tables follow the new font too
                for p in _paras([tb]):
                    for r in p.runs:
                        if s.get("font"):
                            _rfonts(r._r.get_or_add_rPr(), s["font"])
        return ("the whole document" if kind == "all" else "the body text") + ": " + _say_set(s)
    m, objs = _targets(doc, t)
    if kind == "title":
        st = _style(doc, "Title")
        if st is not None and isinstance(objs[0], Paragraph) and objs[0].style is not None and objs[0].style.name == "Title":
            _set_style(st, s)
            for r in objs[0].runs:
                _clear_run(r, props)
            if s.get("case") or s.get("highlight"):
                _set_runs(objs[0], {k: v for k, v in s.items() if k in ("case", "highlight")})
            return "the title: " + _say_set(s)
    for p in _paras(objs):
        _set_runs(p, s)
    return f"{DM.describe_target(m, t)}: " + _say_set(s)


def _say_set(s):
    bits = []
    for k, v in s.items():
        if k == "color":
            bits.append(f"colour {v}")
        elif k in ("bold", "italic", "underline"):
            bits.append(k if v else f"not {k}")
        elif k == "size":
            bits.append(f"size {v}" + ("" if str(v).startswith(("+", "-")) or not str(v)[:1].isdigit() else " pt"))
        elif k == "line_spacing":
            bits.append(f"line spacing {v}")
        elif k == "align":
            bits.append(f"aligned {v}")
        else:
            bits.append(f"{k.replace('_', ' ')} {v}")
    return ", ".join(bits)


def op_page(doc, op, ctx):
    s = op.get("set") or {}
    done = []
    for sec in doc.sections:
        if s.get("size"):
            w, h = PAGE_SIZES.get(str(s["size"]).lower(), (None, None))
            if w is None:
                raise OpError(f"no page size '{s['size']}'")
            land = sec.page_width > sec.page_height
            sec.page_width, sec.page_height = (Cm(h), Cm(w)) if land else (Cm(w), Cm(h))
        if s.get("orientation"):
            want_land = str(s["orientation"]).lower().startswith("land")
            land = sec.page_width > sec.page_height
            if want_land != land:
                sec.page_width, sec.page_height = sec.page_height, sec.page_width
            sec.orientation = WD_ORIENT.LANDSCAPE if want_land else WD_ORIENT.PORTRAIT
        if s.get("margins") is not None:
            mg = s["margins"]
            if isinstance(mg, dict):
                for side in ("top", "bottom", "left", "right"):
                    if mg.get(side) is not None:
                        setattr(sec, f"{side}_margin", Cm(float(mg[side])))
            else:
                v = Cm(float(mg))
                sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = v
        if s.get("columns"):
            cols = sec._sectPr.find(qn("w:cols"))
            if cols is None:
                cols = OxmlElement("w:cols")
                sec._sectPr.append(cols)
            cols.set(qn("w:num"), str(int(s["columns"])))
            cols.set(qn("w:space"), "708")
    if s.get("size"):
        done.append(f"page size {s['size']}")
    if s.get("orientation"):
        done.append(str(s["orientation"]))
    if s.get("margins") is not None:
        done.append(f"margins {s['margins']} cm")
    if s.get("columns"):
        done.append(f"{s['columns']} column(s)")
    return "page: " + ", ".join(done)


def _hf_paragraph(part, clear=True):
    ps = part.paragraphs
    p = ps[0] if ps else part.add_paragraph()
    if clear:
        for child in list(p._p):
            if child.tag != qn("w:pPr"):
                p._p.remove(child)
    return p


def op_page_numbers(doc, op, ctx):
    pos = str(op.get("position") or "bottom").lower()
    align = str(op.get("align") or "center").lower()
    fmt_ = str(op.get("format") or "Page X of Y")
    for sec in doc.sections:
        for part in (sec.footer, sec.header):
            for p in part.paragraphs:  # an old page number goes (only paragraphs that hold one)
                if "PAGE" in (" ".join(x.text or "" for x in p._p.iter(qn("w:instrText"))) + " ".join(x.get(qn("w:instr")) or "" for x in p._p.iter(qn("w:fldSimple")))).upper():
                    for child in list(p._p):
                        if child.tag != qn("w:pPr"):
                            p._p.remove(child)
        if op.get("remove"):
            continue
        part = sec.footer if pos.startswith("bottom") else sec.header
        p = None
        for q in part.paragraphs:
            if not q.text.strip():
                p = q
                break
        if p is None:
            p = part.add_paragraph()
        p.alignment = ALIGN.get(align, WD_ALIGN_PARAGRAPH.CENTER)
        bits = re.split(r"(X|Y)", fmt_)
        th = ctx.get("th") or {}
        for b in bits:
            if not b:
                continue
            r = DB._field(p, "PAGE", "1") if b == "X" else DB._field(p, "NUMPAGES", "1") if b == "Y" else p.add_run(b)
            r.font.size = Pt(9)
            if th.get("muted"):
                r.font.color.rgb = RGBColor.from_string(th["muted"])
        if op.get("skip_first"):
            sec.different_first_page_header_footer = True
    return "page numbers removed" if op.get("remove") else f"page numbers '{fmt_}' at the {pos} {align}"


def op_header_footer(doc, op, ctx):
    which = op["op"]
    for sec in doc.sections:
        part = sec.header if which == "header" else sec.footer
        if op.get("remove"):
            for p in part.paragraphs:
                fields = " ".join(x.text or "" for x in p._p.iter(qn("w:instrText")))
                if "PAGE" not in fields.upper():
                    for child in list(p._p):
                        if child.tag != qn("w:pPr"):
                            p._p.remove(child)
            continue
        p = None
        for q in part.paragraphs:
            fields = " ".join(x.text or "" for x in q._p.iter(qn("w:instrText")))
            if "PAGE" not in fields.upper():
                p = q
                break
        if p is None:
            p = part.add_paragraph()
            if part.paragraphs and part.paragraphs[0]._p is not p._p:
                part.paragraphs[0]._p.addprevious(p._p)
        for child in list(p._p):
            if child.tag != qn("w:pPr"):
                p._p.remove(child)
        r = p.add_run(str(op.get("text") or ""))
        r.font.size = Pt(9)
        p.alignment = ALIGN.get(str(op.get("align") or ("right" if which == "header" else "center")).lower())
    return f"{which} removed" if op.get("remove") else f"{which} '{op.get('text')}'"


def op_toc(doc, op, ctx):
    e = els(doc)
    m = DM.docx_map(doc)
    tocs = [it["k"] for it in m["items"] if it.get("toc")]
    if op.get("remove"):
        if not tocs:
            raise OpError("there is no table of contents")
        k = tocs[0]
        kill = []
        depth, j = 0, k  # the whole field: from its begin to its end (Word writes each entry as a paragraph of its own)
        while j < len(e):
            el = e[j]
            if not isinstance(el, Paragraph):
                break
            kill.append(el)
            for fc in el._p.iter(qn("w:fldChar")):
                t_ = fc.get(qn("w:fldCharType"))
                depth += 1 if t_ == "begin" else -1 if t_ == "end" else 0
            if depth <= 0 and j > k or (depth <= 0 and j == k and any(fc.get(qn("w:fldCharType")) == "end" for fc in el._p.iter(qn("w:fldChar")))):
                break
            j += 1
        nxt = j + 1
        while nxt < len(e) and isinstance(e[nxt], Paragraph) and m["items"][nxt].get("toc"):
            kill.append(e[nxt])
            nxt += 1
        if k > 0 and isinstance(e[k - 1], Paragraph) and e[k - 1].text.strip().lower() in ("contents", "table of contents"):
            kill.append(e[k - 1])
        if nxt < len(e) and isinstance(e[nxt], Paragraph) and not e[nxt].text.strip() and m["items"][nxt].get("page_break"):
            kill.append(e[nxt])
        _delete(kill)
        return "table of contents removed"
    if tocs:
        return "the table of contents is there (Word refreshes it on every render)"
    if not m["headings"]:
        raise OpError("the document has no headings to list (say 'make the headings real headings' first)")
    first = m["headings"][0]["k"]
    th = ctx.get("th") or DB.theme_of(doc)
    anchor = e[first]
    # after a cover page (a page break before the first heading), else before the first heading
    title = doc.add_paragraph()
    r = title.add_run("Contents")
    r.bold, r.font.size = True, Pt(max(14, th.get("h1", 16)))
    r.font.color.rgb = RGBColor.from_string(th.get("head_color", "1F3864"))
    field_p = doc.add_paragraph()
    DB._field(field_p, 'TOC \\o "1-3" \\h \\z \\u', "Right-click to update the table of contents.")
    brk = doc.add_paragraph()
    brk.add_run().add_break(WD_BREAK.PAGE)
    for el in (title._p, field_p._p, brk._p):
        anchor.addprevious(el) if isinstance(anchor, Paragraph) is False else anchor._p.addprevious(el)
    return "table of contents added before the first heading (filled in by Word at the render)"


def op_cover(doc, op, ctx):
    e = els(doc)
    if op.get("remove"):
        m = DM.docx_map(doc)
        brk = next((it["k"] for it in m["items"][:15] if it.get("page_break")), None)
        if brk is None:
            raise OpError("no cover page found (no page break near the start)")
        _delete(e[:brk + 1])
        return "cover page removed"
    th = ctx.get("th") or DB.theme_of(doc)
    m = DM.docx_map(doc)
    title = op.get("title") or m["title"] or "Untitled"
    first = e[0] if e else None
    body = doc.element.body
    before = set(body)  # the elements themselves: ids of lxml proxies are reused once a proxy is freed
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(150)
    r = p.add_run(title)
    r.font.size, r.font.color.rgb = Pt(30), RGBColor.from_string(th.get("accent", "1F3864"))
    if op.get("subtitle"):
        q = doc.add_paragraph()
        rq = q.add_run(op["subtitle"])
        rq.font.size, rq.font.color.rgb = Pt(15), RGBColor.from_string(th.get("muted", "595959"))
    rule = doc.add_paragraph()
    DB._rule(rule, th.get("accent", "1F3864"), size=18, where="top", space=1)
    for line in op.get("lines") or []:
        q = doc.add_paragraph()
        DB._add_text(q, str(line), {"color": th.get("muted", "595959")})
        q.paragraph_format.space_after = Pt(2)
    end = doc.add_paragraph()
    end.add_run().add_break(WD_BREAK.PAGE)
    new = [x for x in body if x not in before and x.tag != qn("w:sectPr")]
    if first is not None:
        for x in new:
            _el(first).addprevious(x)
    for sec in doc.sections:
        sec.different_first_page_header_footer = True
    return f"cover page '{title}'"


def op_theme(doc, op, ctx):
    name = op.get("name") or "corporate"
    th = themes.get(name, op.get("accent"), "report")
    b = DB.builder_on(doc, th)
    b.styles()
    m = DM.docx_map(doc)
    e = els(doc)
    for it in m["items"]:
        if it["kind"] == "p":
            p = e[it["k"]]
            for r in p.runs:
                _clear_run(r, ["font", "size", "color"])
            if not it.get("level") and it["style"] not in ("Title", "Subtitle") and not it.get("list"):
                p.paragraph_format.alignment = None
                p.paragraph_format.line_spacing = None
                p.paragraph_format.space_after = None
    n = _style_tables(doc, th, [x for x in e if isinstance(x, Table)])
    ctx["th"] = th
    return f"restyled as '{th['name']}' ({th['body']} {th['size']} pt, line spacing {th['line']}{', justified' if th['justify'] else ''}; {n} table(s))"


def _style_tables(doc, th, tables):
    tt = th["table"]
    n = 0
    for t in tables:
        rows = t.rows
        if len(rows) < 2 or len(t.columns) < 2:
            continue
        n += 1
        DB._borders(t._tbl.tblPr, "w:tblBorders", {"top": (8, tt["header_fill"], "single"), "bottom": (8, tt["header_fill"], "single"),
                                                   "insideH": (4, tt["border"], "single"), "left": (0, "", ""), "right": (0, "", ""),
                                                   "insideV": (0, "", "")})
        for j, c in enumerate(rows[0].cells):
            DB._shade(c, tt["header_fill"])
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.bold = True
                    r.font.color.rgb = RGBColor.from_string(tt["header_text"])
        trpr = rows[0]._tr.get_or_add_trPr()
        if trpr.find(qn("w:tblHeader")) is None:
            trpr.append(OxmlElement("w:tblHeader"))
        for i, row in enumerate(rows[1:], start=1):
            for c in row.cells:
                if tt.get("stripe") and i % 2 == 0:
                    DB._shade(c, tt["stripe"])
                else:
                    tcpr = c._tc.get_or_add_tcPr()
                    for old in tcpr.findall(qn("w:shd")):
                        tcpr.remove(old)
            numeric = [number(c.text) is not None for c in row.cells]
            for c, isnum in zip(row.cells, numeric):
                for p in c.paragraphs:
                    if isnum:
                        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    return n


def op_table_style(doc, op, ctx):
    m, objs = _targets(doc, op.get("target") or {"kind": "table", "which": "all"})
    tabs = [o for o in objs if isinstance(o, Table)]
    if not tabs:
        raise OpError("no table there")
    th = ctx.get("th") or DB.theme_of(doc)
    if op.get("accent") or op.get("color"):
        th = dict(th)
        th["table"] = {**th["table"], "header_fill": colour(op.get("accent") or op.get("color"))}
    n = _style_tables(doc, th, tabs)
    return f"{n} table(s) restyled (coloured header row repeated on every page, rules, stripes, numbers right-aligned)"


def op_structure(doc, op, ctx):
    m = DM.docx_map(doc)
    vis = [it for it in m["headings"] if it.get("visual")]
    if not vis:
        raise OpError("no hand-made headings found (bold lines followed by text)")
    e = els(doc)
    for it in vis:
        p = e[it["k"]]
        try:
            p.style = doc.styles[f"Heading {it['level']}"]
        except KeyError:
            raise OpError("the document has no Heading styles") from None
        for r in p.runs:
            _clear_run(r, ["font", "size", "color", "bold"])
    return f"{len(vis)} bold line(s) made real headings (level 1: {sum(1 for x in vis if x['level'] == 1)}, level 2: {sum(1 for x in vis if x['level'] == 2)})"


def op_heading_numbers(doc, op, ctx):
    m = DM.docx_map(doc)
    e = els(doc)
    rx = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.|[A-Z]\.)\s+")
    n = 0
    counters = [0, 0, 0, 0]
    for it in m["headings"]:
        p = e[it["k"]]
        runs = [r for r in p.runs if r.text]
        if not runs:
            continue
        if op.get("remove"):
            if rx.match(runs[0].text):
                runs[0].text = rx.sub("", runs[0].text, count=1)
                n += 1
            continue
        if SKIP_NUMBER.match(it["text"].strip()) or rx.match(it["text"]):
            continue
        lv = min(4, it["level"])
        counters[lv - 1] += 1
        for k in range(lv, 4):
            counters[k] = 0
        runs[0].text = ".".join(str(c) for c in counters[:lv]) + " " + runs[0].text
        n += 1
    return f"heading numbers {'removed from' if op.get('remove') else 'added to'} {n} heading(s)"


def op_list(doc, op, ctx):
    m, objs = _targets(doc, op.get("target"))
    ps = [o for o in objs if isinstance(o, Paragraph) and o.text.strip() and not DM.heading_level(o)]
    if not ps:
        raise OpError("no paragraphs there to turn into a list")
    kind = str(op.get("kind") or "bullets")
    name = {"bullets": "List Bullet", "numbered": "List Number", "none": "Normal"}.get(kind, "List Bullet")
    if _style(doc, name) is None:
        raise OpError(f"the document has no '{name}' style")
    num_id = None
    for i, p in enumerate(ps):
        ppr = p._p.get_or_add_pPr()
        for np_ in ppr.findall(qn("w:numPr")):
            ppr.remove(np_)
        p.style = doc.styles[name]
        if kind == "numbered":
            num_id = DB._restart_numbering(doc, p) if i == 0 else (DB._use_num(p, num_id) or num_id)
    return f"{len(ps)} paragraph(s) made a {'numbered list' if kind == 'numbered' else 'bulleted list' if kind == 'bullets' else 'plain text'}"


def op_page_breaks(doc, op, ctx):
    m = DM.docx_map(doc)
    e = els(doc)
    n = 0
    if op.get("remove"):
        for it in m["items"]:
            p = e[it["k"]]
            if it["kind"] == "p" and it.get("page_break") and not it.get("toc"):
                for br in list(p._p.iter(qn("w:br"))):
                    if br.get(qn("w:type")) == "page":
                        br.getparent().remove(br)
                        n += 1
                if p.paragraph_format.page_break_before:
                    p.paragraph_format.page_break_before = False
                    n += 1
        return f"{n} page break(s) removed"
    lvl = int(op.get("level") or 1)
    first = True
    for it in m["headings"]:
        if it["level"] == lvl:
            if first:
                first = False
                continue
            e[it["k"]].paragraph_format.page_break_before = True
            n += 1
    return f"every level-{lvl} section starts on a new page ({n} break(s))"


def op_replace(doc, op, ctx):
    find, repl = str(op.get("find") or ""), str(op.get("with") if op.get("with") is not None else op.get("replace") or "")
    if not find:
        raise OpError("nothing to find")
    t = op.get("target")
    if t and t.get("kind") not in ("all", None):
        _, objs = _targets(doc, t)
        ps = _paras(objs)
    else:
        ps = _all_paragraphs(doc)
    n = sum(replace_in_paragraph(p, find, repl, bool(op.get("case")), op.get("whole_word", True) is not False) for p in ps)
    if not n:
        raise OpError(f"'{find}' is not in the document")
    ctx.setdefault("info", {})["replaced"] = n
    return f"'{find}' replaced with '{repl}' ({n} time(s))"


def op_emphasis(doc, op, ctx):
    s = dict(op.get("set") or {"bold": True})
    t = op.get("target") or {"kind": "body"}
    _, objs = _targets(doc, t)
    ps = _paras(objs)
    terms = [str(x) for x in (op.get("terms") or ([op["find"]] if op.get("find") else [])) if str(x).strip()]
    if not terms and op.get("auto"):
        from . import edit_llm as EL
        if ctx.get("planner") is None:
            raise OpError("choosing key terms needs the model")
        terms = EL.key_terms(ctx["planner"], "\n".join(p.text for p in ps), int(op.get("auto") or 8))
    if not terms:
        raise OpError("which words?")
    n = 0
    for p in ps:
        for term in terms:
            full = "".join(r.text for r in all_runs(p))
            for mt in reversed(list(re.finditer(re.escape(term), full, re.I))):
                for r in split_runs_at(p, mt.start(), mt.end()):
                    _set_runs_one(r, s)
                n += 1
    if not n:
        raise OpError("those words are not in that part")
    return f"{n} occurrence(s) of {', '.join(repr(x) for x in terms[:5])}" + ("..." if len(terms) > 5 else "") + ": " + _say_set(s)


def _set_runs_one(r, s):
    if s.get("bold") is not None:
        r.font.bold = bool(s["bold"])
    if s.get("italic") is not None:
        r.font.italic = bool(s["italic"])
    if s.get("underline") is not None:
        r.font.underline = bool(s["underline"])
    if s.get("color"):
        r.font.color.rgb = RGBColor.from_string(colour(s["color"]))
    if s.get("highlight"):
        r.font.highlight_color = HIGHLIGHT.get(str(s["highlight"]).lower(), WD_COLOR_INDEX.YELLOW)


def op_delete(doc, op, ctx):
    m, objs = _targets(doc, op.get("target"))
    words = sum(len(getattr(o, "text", "").split()) for o in objs if isinstance(o, Paragraph))
    _delete(objs)
    return f"{DM.describe_target(m, op.get('target'))} deleted ({len(objs)} part(s), {words} words)"


def op_move(doc, op, ctx):
    m, objs = _targets(doc, op.get("target"))
    to = op.get("to") or {}
    m2, anchor = _targets(doc, to.get("target") or to)
    where = str(to.get("where") or op.get("where") or "after")
    if any(_el(a) is _el(o) for a in anchor for o in objs):
        raise OpError("cannot move a part next to itself")
    if where == "after":
        ref = _el(anchor[-1])
        for o in reversed(objs):
            ref.addnext(_el(o))
    else:
        ref = _el(anchor[0])
        for o in objs:
            ref.addprevious(_el(o))
    return f"{DM.describe_target(m, op.get('target'))} moved {where} {DM.describe_target(m2, to.get('target') or to)}"


def _context(doc, ctx):
    m = DM.docx_map(doc)
    return "DOCUMENT OUTLINE:\n" + DM.outline_text(m)


def op_insert(doc, op, ctx):
    blocks = op.get("blocks")
    th = ctx.get("th") or DB.theme_of(doc)
    if not blocks and op.get("text"):
        blocks = [{"type": "paragraph", "text": str(op["text"])}]
        if op.get("heading"):
            blocks.insert(0, {"type": "heading", "text": op["heading"], "level": int(op.get("level") or 1)})
    if not blocks and op.get("about"):
        from . import edit_llm as EL
        if ctx.get("planner") is None:
            raise OpError("writing new text needs the model")
        blocks = EL.write_blocks(ctx["planner"], op["about"], _context(doc, ctx), op.get("words") or 180, op.get("heading"), op.get("kinds"))
    if not blocks:
        raise OpError("nothing to insert")
    where = str(op.get("where") or "end")
    anchor = None
    m = DM.docx_map(doc)
    if where in ("before", "after"):
        ks = DM.find(m, op.get("anchor"))
        if not ks:
            raise OpError(f"{DM.describe_target(m, op.get('anchor'))} is not in the document")
        e = els(doc)
        anchor = _el(e[ks[-1] if where == "after" else ks[0]])
    elif where == "start":
        e = els(doc)
        start = next((it["k"] for it in m["items"] if it.get("level")), 0)
        anchor, where = (_el(e[start]), "before") if e else (None, "end")
    elif where == "end":  # before a references / bibliography section when there is one
        refs = next((s for s in m["sections"] if SKIP_NUMBER.match(re.sub(r"^\d+(\.\d+)*\.?\s+", "", s["title"])) and
                     re.search(r"reference|bibliograph|works cited", s["title"], re.I)), None)
        if refs:
            anchor, where = _el(els(doc)[refs["h"]]), "before"
    new = DB.insert_blocks(doc, blocks, anchor, where, th, numbering=_counts(doc))
    heads = [b.get("text") for b in blocks if b.get("type") == "heading"]
    words = sum(len(str(b.get("text") or "").split()) + sum(len(str(x).split()) for x in b.get("items") or []) for b in blocks)
    ctx.setdefault("info", {})["inserted"] = [b for b in blocks]
    w = op.get("where") or "end"
    place = f"{w} {DM.describe_target(m, op.get('anchor'))}" if w in ("after", "before") and op.get("anchor") else ("at the start" if w == "start" else "at the end")
    return (f"section '{heads[0]}' added" if heads else f"{len(blocks)} block(s) added") + f" ({words} words, {len(new)} part(s)) {place}"


def _body_paragraphs(objs):
    return [o for o in objs if isinstance(o, Paragraph) and o.text.strip() and not DM.heading_level(o) and not (o.style is not None and o.style.name in ("Title", "Caption"))
            and "TOC" not in " ".join(x.text or "" for x in o._p.iter(qn("w:instrText")))]


def op_rewrite(doc, op, ctx, translate_to=None):
    from . import edit_llm as EL
    if ctx.get("planner") is None:
        raise OpError("rewriting needs the model")
    m, objs = _targets(doc, op.get("target") or {"kind": "body"})
    ps = _body_paragraphs(objs)
    if not ps:
        raise OpError("no text there to rewrite")
    old = [DM.paragraph_md(p) for p in ps]
    keep = bool(op.get("keep_count", True)) or translate_to is not None
    w_old = sum(len(x.split()) for x in old)
    ins = str(op.get("instruction") or "")
    if not translate_to and not re.search(r"\b\d+ words\b", ins):
        if re.search(r"\bshort|concise|condense|trim|cut\b", ins, re.I):
            op = {**op, "instruction": ins + f" (about {max(20, round(w_old * 0.6))} words in total, now {w_old})"}
        elif re.search(r"\blong|expand|elaborat|more detail", ins, re.I):
            op = {**op, "instruction": ins + f" (about {round(w_old * 1.5)} words in total, now {w_old})"}
    if translate_to:
        new = EL.translate(ctx["planner"], old, translate_to, title=m["title"])
    else:
        new = EL.rewrite(ctx["planner"], old, str(op.get("instruction") or "improve it"), keep_count=keep, title=m["title"],
                         context="OUTLINE:\n" + DM.outline_text(m, 30))
    if keep and len(new) != len(old):
        raise OpError("the rewrite came back in a different shape; nothing changed")
    if new == old:
        if re.search(r"grammar|spelling|punctuation", str(op.get("instruction") or ""), re.I):
            raise OpError("no grammar or spelling mistakes found there")
        raise OpError("the new wording came out the same as the old")
    for p, md in zip(ps, new):
        DM.set_paragraph_md(p, md)
    if len(new) > len(ps):  # more paragraphs than before: the extra ones follow the last, in its style
        last = ps[-1]
        for md in new[len(ps):]:
            q = copy.deepcopy(last._p)
            last._p.addnext(q)
            last = Paragraph(q, last._parent)
            DM.set_paragraph_md(last, md)
    elif len(new) < len(ps):
        _delete(ps[len(new):])
    if translate_to and str(translate_to).lower() in ("ur", "urdu", "ar", "arabic"):
        _, objs2 = _targets(doc, op.get("target") or {"kind": "body"}, need=False)
        for p in _paras(objs2):
            _rtl(p, "ur-PK" if str(translate_to).lower() in ("ur", "urdu") else "ar-SA")
    w0, w1 = sum(len(DM.paragraph_md(p).split()) for p in ps[:0]) or sum(len(x.split()) for x in old), sum(len(x.split()) for x in new)
    ctx.setdefault("info", {}).update(words_before=w0, words_after=w1, paragraphs_before=len(old), paragraphs_after=len(new))
    what = f"translated into {translate_to}" if translate_to else f"rewritten ({op.get('instruction')})"
    return f"{DM.describe_target(m, op.get('target') or {'kind': 'body'})} {what}: {len(old)} -> {len(new)} paragraph(s), {w0} -> {w1} words"


def op_summarize(doc, op, ctx):
    from . import edit_llm as EL
    if ctx.get("planner") is None:
        raise OpError("summarising needs the model")
    m, objs = _targets(doc, op.get("target") or {"kind": "all"})
    text = "\n".join(o.text for o in objs if isinstance(o, Paragraph) and o.text.strip())[:14000]
    kind = str(op.get("kind") or "executive summary")
    heading = op.get("heading") if op.get("heading") is not None else kind.title() if kind in ("executive summary", "abstract", "summary", "key takeaways",
                                                                                                    "conclusion", "key points") else None
    blocks = EL.write_blocks(ctx["planner"], f"a {kind} of the text below" + (" as 3-6 bullet points" if "point" in kind or "bullet" in kind else ""),
                             _context(doc, ctx) + "\n\nTEXT TO SUMMARISE:\n" + text, op.get("words") or 150, heading)
    where = op.get("where") or ("start" if kind in ("executive summary", "abstract", "summary") else "end")
    return op_insert(doc, {"op": "insert", "blocks": blocks, "where": where, "anchor": op.get("anchor")}, ctx).replace("block(s) added", f"{kind} added")


# ---- tables
def _table(doc, op):
    m, objs = _targets(doc, op.get("target") or {"kind": "table", "n": 1})
    tabs = [o for o in objs if isinstance(o, Table)]
    if not tabs:
        raise OpError("there is no table there")
    return m, tabs[0]


def _col(t, name):
    head = [c.text.strip() for c in t.rows[0].cells]
    if isinstance(name, int) or str(name).isdigit():
        j = int(name) - 1
        if 0 <= j < len(head):
            return j, head
    low = [h.lower() for h in head]
    n = str(name or "").strip().lower()
    if n in low:
        return low.index(n), head
    hit = [j for j, h in enumerate(low) if n and (n in h or h in n)]
    if hit:
        return hit[0], head
    raise OpError(f"no column '{name}' (the columns are {', '.join(head)})")


def _is_total(row):
    return bool(re.match(r"^\s*(?:total|grand total|sum|subtotal)\b", row.cells[0].text, re.I))


def _set_cell(cell, text, like=None):
    p = cell.paragraphs[0]
    base = None
    src = like if like is not None else p
    for r in src.runs:
        if r.text.strip():
            base = copy.deepcopy(r._r.rPr) if r._r.rPr is not None else None
            break
    for child in list(p._p):
        if child.tag != qn("w:pPr"):
            p._p.remove(child)
    r = p.add_run(str(text))
    if base is not None:
        r._r.insert(0, copy.deepcopy(base))
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


def op_table_sort(doc, op, ctx):
    m, t = _table(doc, op)
    j, head = _col(t, op.get("by") or 1)
    rows = list(t.rows)[1:]
    total = rows[-1] if rows and _is_total(rows[-1]) else None
    data = rows[:-1] if total is not None else rows
    if len(data) < 2:
        raise OpError("nothing to sort")

    def key(r):
        v = r.cells[j].text.strip()
        n = number(v)
        return (0, n[0]) if n else (1, v.lower())
    nums = sum(1 for r in data if number(r.cells[j].text.strip()))
    ordered = sorted(data, key=key, reverse=bool(op.get("desc")))
    anchor = rows[0]._tr.getprevious()
    for r in data:
        r._tr.getparent().remove(r._tr)
    ref = t.rows[0]._tr
    for r in ordered:
        ref.addnext(r._tr)
        ref = r._tr
    ctx.setdefault("info", {})["sorted"] = {"col": j, "desc": bool(op.get("desc")), "numeric": nums >= len(data) * 0.7}
    return f"table sorted by '{head[j]}' ({'largest' if op.get('desc') else 'smallest'} first)" if nums else \
        f"table sorted by '{head[j]}' ({'Z-A' if op.get('desc') else 'A-Z'})"


def op_table_add_row(doc, op, ctx):
    m, t = _table(doc, op)
    vals = list(op.get("values") or [])
    if not vals:
        raise OpError("what goes in the new row?")
    rows = list(t.rows)
    total = rows[-1] if len(rows) > 2 and _is_total(rows[-1]) else None
    model = rows[-2] if total is not None and len(rows) > 2 else rows[-1]
    new = copy.deepcopy(model._tr)
    (total._tr.addprevious(new) if total is not None else model._tr.addnext(new))
    from docx.table import _Row
    row = _Row(new, t)
    for k, c in enumerate(row.cells):
        _set_cell(c, vals[k] if k < len(vals) else "")
    if total is not None:
        _retotal(t)
    return f"row added: {', '.join(str(v) for v in vals)}" + (" (total updated)" if total is not None else "")


def op_table_delete_row(doc, op, ctx):
    m, t = _table(doc, op)
    rows = list(t.rows)
    if op.get("match"):
        hit = [r for r in rows[1:] if str(op["match"]).lower() in " ".join(c.text for c in r.cells).lower()]
    else:
        n = op.get("row")
        body = [r for r in rows[1:] if not _is_total(r)]
        try:
            hit = [body[-1]] if n in ("last", -1) else [body[int(n) - 1]]
        except (TypeError, ValueError, IndexError):
            hit = []
    if not hit:
        raise OpError("no such row")
    for r in hit:
        r._tr.getparent().remove(r._tr)
    if len(t.rows) > 2 and _is_total(t.rows[-1]):
        _retotal(t)
    return f"{len(hit)} row(s) deleted"


def _retotal(t):
    """The total row recomputed from the rows above it (code does the sums)."""
    rows = list(t.rows)
    if not rows or not _is_total(rows[-1]):
        return
    data = rows[1:-1]
    for j in range(1, len(rows[-1].cells)):
        ps = [number(r.cells[j].text.strip()) for r in data]
        ps = [p for p in ps if p]
        head = rows[0].cells[j].text
        pct = sum(1 for p in ps if p[2] == "%") >= len(ps) / 2
        if len(ps) >= max(1, len(data) * 0.7) and not pct and not re.search(r"%|rate|percent|share|year|no\.?$|#", head, re.I):
            dec = max(p[3] for p in ps)
            _set_cell(rows[-1].cells[j], num_fmt(sum(p[0] for p in ps), dec, ps[0][1], ps[0][2]))


def op_table_add_column(doc, op, ctx):
    m, t = _table(doc, op)
    name = str(op.get("name") or "New")
    head = [c.text.strip() for c in t.rows[0].cells]
    rows = list(t.rows)
    total = rows[-1] if len(rows) > 2 and _is_total(rows[-1]) else None
    data = rows[1:-1] if total is not None else rows[1:]
    vals = []
    if op.get("values"):
        vals = [str(v) for v in op["values"]]
    elif op.get("formula"):
        from .xlsx_build import py_value
        fmt_from = None
        for r in data:
            named = {}
            for k, h in enumerate(head):
                p_ = number(r.cells[k].text.strip())
                named[h] = p_[0] if p_ else r.cells[k].text.strip()
                if p_ and fmt_from is None and re.search(re.escape("[" + h + "]"), op["formula"], re.I):
                    fmt_from = p_
            v = py_value(op["formula"], named)
            if v is None:
                raise OpError(f"cannot compute '{op['formula']}' (columns: {', '.join(head)})")
            dec = 2 if not float(v).is_integer() else 0
            vals.append(num_fmt(v, dec, fmt_from[1] if fmt_from else "", fmt_from[2] if fmt_from and fmt_from[2] != "%" else ""))
    elif op.get("percent_of"):
        j, _ = _col(t, op["percent_of"])
        nums = [number(r.cells[j].text.strip()) for r in data]
        tot = sum(p[0] for p in nums if p)
        if not tot:
            raise OpError(f"'{head[j]}' has no numbers")
        vals = [f"{(p[0] / tot * 100):.1f}%" if p else "" for p in nums]
    else:
        raise OpError("what goes in the new column?")
    width = t.columns[-1].width or Cm(3)
    t.add_column(width)
    rows = list(t.rows)
    _set_cell(rows[0].cells[-1], name, like=rows[0].cells[-2].paragraphs[0])
    tcpr_src = rows[0].cells[-2]._tc.tcPr
    if tcpr_src is not None and tcpr_src.find(qn("w:shd")) is not None:
        DB._shade(rows[0].cells[-1], tcpr_src.find(qn("w:shd")).get(qn("w:fill")))
    for r, v in zip(data, vals):
        _set_cell(r.cells[-1], v, like=r.cells[-2].paragraphs[0])
        r.cells[-1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT if number(v) else None
    if total is not None:
        _set_cell(total.cells[-1], "", like=total.cells[-2].paragraphs[0])
        _retotal(t)
    ctx.setdefault("info", {})["column_values"] = vals
    return f"column '{name}' added ({len(vals)} values" + (f", computed as {op.get('formula')}" if op.get("formula") else
                                                            f", share of {op.get('percent_of')}" if op.get("percent_of") else "") + ")"


def op_table_delete_column(doc, op, ctx):
    m, t = _table(doc, op)
    j, head = _col(t, op.get("name"))
    if len(head) < 2:
        raise OpError("a table needs at least one column")
    for r in t.rows:
        tc = r.cells[j]._tc
        tc.getparent().remove(tc)
    grid = t._tbl.tblGrid
    cols = grid.findall(qn("w:gridCol"))
    if j < len(cols):
        grid.remove(cols[j])
    return f"column '{head[j]}' deleted"


def op_table_total(doc, op, ctx):
    m, t = _table(doc, op)
    rows = list(t.rows)
    if _is_total(rows[-1]):
        _retotal(t)
        return "total row recomputed"
    new = copy.deepcopy(rows[-1]._tr)
    rows[-1]._tr.addnext(new)
    from docx.table import _Row
    row = _Row(new, t)
    _set_cell(row.cells[0], "Total")
    for c in row.cells[1:]:
        _set_cell(c, "")
    for c in row.cells:
        for p in c.paragraphs:
            for r in p.runs:
                r.bold = True
        DB._borders(c._tc.get_or_add_tcPr(), "w:tcBorders", {"top": (8, "404040", "single")})
    _retotal(t)
    return "total row added (sums by code)"


def op_chart(doc, op, ctx):
    from . import charts as CH
    m, t = _table(doc, op)
    head = [c.text.strip() for c in t.rows[0].cells]
    rows = [r for r in list(t.rows)[1:] if not _is_total(r)]
    cj = _col(t, op["categories"])[0] if op.get("categories") else next((j for j in range(len(head)) if sum(1 for r in rows if number(r.cells[j].text.strip())) < len(rows) / 2), 0)
    vcols = [_col(t, v)[0] for v in op.get("values") or []] or [j for j in range(len(head)) if j != cj and sum(1 for r in rows if number(r.cells[j].text.strip())) >= len(rows) * 0.7
                                                                 and not re.search(r"%|share|rate|percent", head[j], re.I)][:3]
    if not vcols:
        raise OpError("the table has no number columns to chart")
    spec = {"chart": op.get("chart") or ("bar" if len(rows) > 8 else "column"), "title": op.get("title") or (head[vcols[0]] if len(vcols) == 1 else ""),
            "categories": [r.cells[cj].text.strip() for r in rows],
            "series": [{"name": head[j], "values": [(number(r.cells[j].text.strip()) or [None])[0] for r in rows]} for j in vcols]}
    if spec["chart"] in ("pie", "doughnut"):
        spec["series"] = spec["series"][:1]
    th = ctx.get("th") or DB.theme_of(doc)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    b = DB.builder_on(doc, th)
    CH.add_chart(doc, p, spec, th, width_cm=min(b.text_w, 15.5), height_cm=8.0)
    nf = _counts(doc)[1] + 1
    cap = doc.add_paragraph(style="Caption") if _style(doc, "Caption") is not None else doc.add_paragraph()
    r = cap.add_run(f"Figure {nf}: ")
    r.bold = True
    cap.add_run(op.get("caption") or spec["title"] or f"{', '.join(head[j] for j in vcols)} by {head[cj]}")
    t._tbl.addnext(cap._p)
    t._tbl.addnext(p._p)
    ctx.setdefault("info", {})["chart"] = spec
    return f"{spec['chart']} chart of {', '.join(head[j] for j in vcols)} by {head[cj]} added under the table ({len(rows)} bars/points)"


def op_image(doc, op, ctx):
    path = Path(str(op.get("path") or ""))
    if not path.exists():
        raise OpError(f"no image file '{path}'")
    th = ctx.get("th") or DB.theme_of(doc)
    b = DB.builder_on(doc, th)
    w = min(b.text_w, float(op.get("width_cm") or b.text_w * 0.8))
    doc.add_picture(str(path), width=Cm(w))
    pic = doc.paragraphs[-1]
    pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
    new = [pic._p]
    if op.get("caption"):
        cap = doc.add_paragraph(style="Caption") if _style(doc, "Caption") is not None else doc.add_paragraph()
        r = cap.add_run(f"Figure {_counts(doc)[1] + 1}: ")
        r.bold = True
        cap.add_run(str(op["caption"]))
        new.append(cap._p)
    if op.get("anchor"):
        m = DM.docx_map(doc)
        ks = DM.find(m, op["anchor"])
        if ks:
            e = els(doc)
            ref = _el(e[ks[-1] if (op.get("where") or "after") == "after" else ks[0]])
            for el in (reversed(new) if (op.get("where") or "after") == "after" else new):
                ref.addnext(el) if (op.get("where") or "after") == "after" else ref.addprevious(el)
    return f"image {path.name} added ({w:.1f} cm wide)"


OPS = {"style": op_style, "page": op_page, "page_numbers": op_page_numbers, "header": op_header_footer, "footer": op_header_footer,
       "toc": op_toc, "cover": op_cover, "theme": op_theme, "table_style": op_table_style, "structure": op_structure,
       "heading_numbers": op_heading_numbers, "list": op_list, "page_breaks": op_page_breaks, "replace": op_replace, "emphasis": op_emphasis,
       "delete": op_delete, "move": op_move, "insert": op_insert, "rewrite": op_rewrite,
       "translate": lambda d, o, c: op_rewrite(d, o, c, translate_to=o.get("language") or "Urdu"),
       "summarize": op_summarize, "table_sort": op_table_sort, "table_add_row": op_table_add_row, "table_delete_row": op_table_delete_row,
       "table_add_column": op_table_add_column, "table_delete_column": op_table_delete_column, "table_total": op_table_total,
       "chart": op_chart, "image": op_image}
NEEDS_MODEL = {"rewrite", "translate", "summarize"}


def renumber(doc):
    """'Table n' / 'Figure n' captions numbered again in the order they now appear (after an insert, move or delete)."""
    n = {"Table": 0, "Figure": 0}
    changed = 0
    for p in doc.paragraphs:
        runs = all_runs(p)
        if not runs:
            continue
        m = re.match(r"^(Table|Figure) (\d+)", runs[0].text)
        if not m or (p.style is not None and p.style.name != "Caption" and not runs[0].bold):
            continue
        n[m.group(1)] += 1
        if int(m.group(2)) != n[m.group(1)]:
            runs[0].text = f"{m.group(1)} {n[m.group(1)]}" + runs[0].text[m.end():]
            changed += 1
    return changed


def apply(doc, op, ctx):
    fn = OPS.get(op.get("op"))
    if fn is None:
        raise OpError(f"no operation '{op.get('op')}'")
    done = fn(doc, op, ctx)
    if op.get("op") in ("insert", "move", "delete", "chart", "image", "summarize", "data_table", "data_chart"):
        renumber(doc)
    if op.get("op") in ("insert", "move", "delete", "summarize"):
        m = DM.docx_map(doc)
        hs = [h for h in m["headings"] if not SKIP_NUMBER.match(re.sub(r"^\d+(\.\d+)*\.?\s+", "", h["text"]))]
        numbered = [h for h in hs if re.match(r"^\d+(\.\d+)*\.?\s", h["text"])]
        if hs and len(numbered) >= 0.6 * len(hs) and len(numbered) < len(hs) + 1:
            op_heading_numbers(doc, {"remove": True}, ctx)
            op_heading_numbers(doc, {}, ctx)
    return done


# ------------------------------------------------------------------------------------------------ checks
def check(op, before, after, info=None, doc_after=None, pdf_text=None):
    """Did the edit happen? (ok, what) from the maps of the two versions (and the rendered text when there is one)."""
    k = op.get("op")
    info = info or {}
    if k in ("data_table", "data_chart", "data_refresh") and doc_after is not None:
        from . import docx_data as DD
        return DD.check(op, doc_after)
    b_text = " ".join(it["text"] for it in before["items"] if not it.get("toc"))
    a_text = " ".join(it["text"] for it in after["items"] if not it.get("toc"))
    if k == "replace":
        find, repl = str(op.get("find")), str(op.get("with") or "")
        left = len(re.findall(re.escape(find), a_text, 0 if op.get("case") else re.I)) if find.lower() not in repl.lower() else 0
        return left == 0, f"{info.get('replaced', '?')} replaced; {left} left in the body"
    if k == "delete":
        gone = before["stats"]["words"] - after["stats"]["words"]
        return gone > 0 or before["stats"]["tables"] > after["stats"]["tables"], f"{gone} words fewer"
    if k == "insert" or k == "summarize":
        added = after["stats"]["words"] - before["stats"]["words"]
        heads = [str(b.get("text")) for b in (info.get("inserted") or []) if b.get("type") == "heading"]
        ok = added > 0 and all(any(h.lower() in it["text"].lower() for it in after["headings"]) for h in heads)
        return ok, f"{added} words added" + (f"; heading '{heads[0]}' in the outline" if heads else "")
    if k in ("rewrite", "translate"):
        w0, w1 = info.get("words_before"), info.get("words_after")
        if k == "translate" and str(op.get("language", "")).lower() in ("ur", "urdu", "ar", "arabic"):
            arabic = sum(1 for ch in a_text if "؀" <= ch <= "ۿ")
            return arabic > 20, f"{arabic} Arabic-script letters now"
        ins = str(op.get("instruction") or "").lower()
        if w0 and w1 and re.search(r"short|concise|brief|condense|cut|trim", ins):
            return w1 <= w0 * 0.9, f"{w0} -> {w1} words"
        if w0 and w1 and re.search(r"long|expand|elaborat|detail|more", ins):
            return w1 >= w0 * 1.1, f"{w0} -> {w1} words"
        return a_text != b_text, f"{w0} -> {w1} words"
    if k == "move":
        return [it["text"] for it in after["headings"]] != [it["text"] for it in before["headings"]] or a_text != b_text, \
            "order now: " + " / ".join(it["text"][:20] for it in after["headings"][:6])
    if k == "toc":
        return (after["toc"] != before["toc"]) or (after["toc"] and not op.get("remove")), f"contents page {'present' if after['toc'] else 'absent'}"
    if k == "page_numbers":
        return after["page_numbers"] != bool(op.get("remove")), "page number field " + ("present" if after["page_numbers"] else "absent")
    if k in ("header", "footer"):
        got = after["header" if k == "header" else "footer"]
        return (str(op.get("text") or "") in got) if not op.get("remove") else str(op.get("text") or "x") not in got, f"{k}: '{got[:50]}'"
    if k == "page":
        s, pg = op.get("set") or {}, after["page"]
        ok = True
        if s.get("orientation"):
            ok &= pg["orientation"] == ("landscape" if str(s["orientation"]).startswith("land") else "portrait")
        if s.get("margins") is not None and not isinstance(s["margins"], dict):
            ok &= all(abs(x - float(s["margins"])) < 0.05 for x in pg["margins_cm"] if x is not None)
        if s.get("columns"):
            ok &= pg["columns"] == int(s["columns"])
        return ok, f"{pg['orientation']}, margins {pg['margins_cm']} cm, {pg['columns']} column(s)"
    if k == "style":
        s = op.get("set") or {}
        if s.get("font") and doc_after is not None:
            t = op.get("target") or {}
            if t.get("kind") in ("all", "body"):
                got = DM._style_font(doc_after.styles["Normal"])
                return str(got).lower() == str(s["font"]).lower(), f"body style font {got}"
        return True, "applied"
    if k in ("table_sort", "table_add_row", "table_delete_row", "table_add_column", "table_delete_column", "table_total"):
        tb0 = {t["t"]: t for t in before["tables"]}
        tb1 = {t["t"]: t for t in after["tables"]}
        n = (op.get("target") or {}).get("n") or 1
        t0, t1 = tb0.get(n if isinstance(n, int) else 1), tb1.get(n if isinstance(n, int) else 1)
        if t0 is None or t1 is None:
            return False, "table not found after the edit"
        if k == "table_add_row":
            return t1["rows"] == t0["rows"] + 1, f"{t0['rows']} -> {t1['rows']} rows"
        if k == "table_delete_row":
            return t1["rows"] < t0["rows"], f"{t0['rows']} -> {t1['rows']} rows"
        if k == "table_add_column":
            return t1["cols"] == t0["cols"] + 1 and str(op.get("name", "")).lower() in [h.lower() for h in t1["header"]], f"{t0['cols']} -> {t1['cols']} columns"
        if k == "table_delete_column":
            return t1["cols"] == t0["cols"] - 1, f"{t0['cols']} -> {t1['cols']} columns"
        if k == "table_total":
            return bool(t1["data"]) and t1["data"][-1][0].lower().startswith("total"), "total row " + ("present" if t1["data"] and t1["data"][-1][0].lower().startswith("total") else "missing")
        if k == "table_sort":
            srt = info.get("sorted") or {}
            j = srt.get("col", 0)
            body = [r for r in t1["data"][1:] if r and not r[0].lower().startswith("total")]
            keys = [((number(r[j]) or [None])[0] if srt.get("numeric") else r[j].lower()) for r in body]
            keys = [x for x in keys if x is not None]
            ok = keys == sorted(keys, reverse=bool(srt.get("desc")))
            return ok, "rows in order" if ok else "rows not in order"
    if k == "chart":
        return after["stats"]["charts"] == before["stats"]["charts"] + 1, f"{after['stats']['charts']} chart(s) now"
    if k == "image":
        return after["stats"]["images"] == before["stats"]["images"] + 1, f"{after['stats']['images']} image(s) now"
    if k == "cover":
        return after["stats"]["words"] != before["stats"]["words"], "cover " + ("removed" if op.get("remove") else "added")
    if k == "structure":
        return sum(1 for h in after["headings"] if not h.get("visual")) > sum(1 for h in before["headings"] if not h.get("visual")), \
            f"{sum(1 for h in after['headings'] if not h.get('visual'))} real heading(s)"
    if k == "heading_numbers":
        numbered = sum(1 for h in after["headings"] if re.match(r"^\d+(\.\d+)*\s", h["text"]))
        return (numbered == 0) if op.get("remove") else numbered > 0, f"{numbered} numbered heading(s)"
    if k == "list":
        return sum(1 for it in after["items"] if it.get("list")) != sum(1 for it in before["items"] if it.get("list")) or op.get("kind") == "numbered", \
            f"{sum(1 for it in after['items'] if it.get('list'))} list item(s)"
    return True, "applied"


def describe(op):
    k = op.get("op")
    t = op.get("target") or {}
    where = ""
    if t.get("kind") == "section":
        where = f" in '{t.get('name') or t.get('n') or t.get('which')}'"
    if k == "style":
        return f"{t.get('kind', 'all')}{where}: {_say_set(op.get('set') or {})}"
    if k == "replace":
        return f"replace '{op.get('find')}' with '{op.get('with')}'"
    if k in ("rewrite",):
        return f"rewrite{where}: {op.get('instruction')}"
    if k == "translate":
        return f"translate{where} into {op.get('language')}"
    if k == "insert":
        return f"add {op.get('heading') or op.get('about') or 'text'}"
    return k.replace("_", " ") + where


from . import docx_data as _DD  # noqa: E402  (tables and charts that come from a workbook)

OPS.update(_DD.OPS)
