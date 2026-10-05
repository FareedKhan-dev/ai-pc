"""Edits on a real PowerPoint deck, in place (python-pptx keeps every part it does not touch: the client's masters,
layouts, pictures and animations), and the map of a deck for finding slides and answering questions.

  m = deck_map(prs)                  {"slides": [{"n", "layout", "title", "texts": [...], "notes", "chart", "table", "picture"}], "count", ...}
  done = apply(prs, op, ctx)          ctx: {"planner", "th" (the deck's look)}; raises OpError
  ok, what = check(op, before, after, info)

Targets: {"kind": "slide", "n": 3} {"kind": "slide", "which": "first|last"} {"kind": "slides", "ns": [2, 5]} {"kind": "all"}
         {"kind": "slide", "contains": "text"}
Operations:
  slide_delete {target}        slide_move {slide, to (position) | before / after: n}      slide_duplicate {slide}
  slide_add {after: n | "end" | "start", layout, title, bullets, ... | about: "..."}  (drawn in the deck's own look)
  title_set {slide, text}      replace {find, with}        rewrite {target, instruction}     translate {target, language}
  style {part: titles|body|all, target, set: {font, size, color, bold, italic}}    background {color, target}
  notes {target, text | write: true}       shrink {target}       bullet_add {slide, text, at}       bullet_delete {slide, n}
"""

import copy
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.oxml.ns import qn
from pptx.util import Pt

from ai_pc.office import pptx_build as PB
from ai_pc.office.docplan import runs as md_runs

TITLES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
DECO = {"SlideNumber", "QuoteMark"}


class OpError(Exception):
    pass


def _prs(x):
    return Presentation(str(x)) if not hasattr(x, "slides") else x


def is_title(sh):
    if sh.name == "Title":
        return True
    try:
        return sh.is_placeholder and sh.placeholder_format.type in TITLES
    except Exception:  # noqa: BLE001
        return False


def slide_title(slide):
    for sh in slide.shapes:
        if sh.has_text_frame and is_title(sh) and sh.text_frame.text.strip():
            return sh.text_frame.text.strip()
    for sh in slide.shapes:  # no title shape: the first text (a quote, a big number)
        if sh.has_text_frame and sh.name not in DECO and sh.text_frame.text.strip():
            return sh.text_frame.text.strip()[:80]
    return ""


def para_md(p):
    out = []
    for r in p.runs:
        t = r.text
        if not t:
            continue
        b, i = bool(r.font.bold), bool(r.font.italic)
        core = t.strip()
        if core and (b or i) and not (b and i):
            lead, trail = t[: len(t) - len(t.lstrip())], t[len(t.rstrip()) :]
            mark = "**" if b else "*"
            out.append(f"{lead}{mark}{core}{mark}{trail}")
        else:
            out.append(t)
    return "".join(out)


def set_para_md(p, md):
    """New text for a paragraph (marks become bold / italic runs); its level and the first run's font stay."""
    base = None
    for r in p.runs:
        if r.text.strip():
            base = copy.deepcopy(r._r.find(qn("a:rPr")))
            break
    for r in list(p.runs):
        p._p.remove(r._r)
    for br in p._p.findall(qn("a:br")):
        p._p.remove(br)
    for t, f in md_runs(md):
        r = p.add_run()
        r.text = t
        if base is not None:
            old = r._r.find(qn("a:rPr"))
            if old is not None:
                r._r.remove(old)
            new = copy.deepcopy(base)
            for k in ("b", "i"):
                if k in new.attrib:
                    del new.attrib[k]
            r._r.insert(0, new)
        if f.get("bold"):
            r.font.bold = True
        if f.get("italic"):
            r.font.italic = True


def deck_map(src):
    prs = _prs(src)
    slides = []
    for i, s in enumerate(prs.slides, start=1):
        texts = []
        for k, sh in enumerate(s.shapes):
            if sh.has_text_frame and sh.text_frame.text.strip() and sh.name not in DECO:
                texts.append(
                    {
                        "shape": k,
                        "name": sh.name,
                        "kind": "title" if is_title(sh) else "text",
                        "text": sh.text_frame.text.strip(),
                        "paras": [
                            {"level": p.level, "text": "".join(r.text for r in p.runs)}
                            for p in sh.text_frame.paragraphs
                            if "".join(r.text for r in p.runs).strip()
                        ],
                    }
                )
        kinds = {sh.shape_type for sh in s.shapes}
        notes = s.notes_slide.notes_text_frame.text.strip() if s.has_notes_slide else ""
        cover = any(sh.name == "Meta" for sh in s.shapes) or any(
            getattr(sh, "is_placeholder", False) and sh.placeholder_format.type == PP_PLACEHOLDER.CENTER_TITLE for sh in s.shapes
        )
        slides.append(
            {
                "n": i,
                "layout": s.slide_layout.name,
                "title": slide_title(s),
                "texts": texts,
                "notes": notes,
                "cover": cover,
                "chart": any(getattr(sh, "has_chart", False) and sh.has_chart for sh in s.shapes),
                "table": any(getattr(sh, "has_table", False) and sh.has_table for sh in s.shapes),
                "picture": MSO_SHAPE_TYPE.PICTURE in kinds,
            }
        )
    cp = prs.core_properties
    return {
        "slides": slides,
        "count": len(slides),
        "title": cp.title or (slides[0]["title"] if slides else ""),
        "keywords": cp.keywords or "",
        "size": [round(prs.slide_width / 914400, 2), round(prs.slide_height / 914400, 2)],
        "words": sum(len(t["text"].split()) for s in slides for t in s["texts"]),
    }


def find(m, t):
    """Slide numbers (1-based) a target points at."""
    t = t or {"kind": "all"}
    n = m["count"]
    if t.get("kind") == "all":
        return list(range(1, n + 1))
    if t.get("kind") == "slides":
        return [x for x in t.get("ns") or [] if 1 <= x <= n]
    if t.get("which") == "last":
        return [n] if n else []
    if t.get("which") == "first":
        return [1] if n else []
    if t.get("contains"):
        c = str(t["contains"]).lower()
        return [s["n"] for s in m["slides"] if c in (s["title"] + " " + " ".join(x["text"] for x in s["texts"])).lower()][:1]
    try:
        k = int(t.get("n"))
    except (TypeError, ValueError):
        return []
    return [k] if 1 <= k <= n else []


def describe_target(m, t):
    ns = find(m, t)
    if (t or {}).get("kind") == "all":
        return "every slide"
    return ("slides " + ", ".join(str(x) for x in ns)) if len(ns) > 1 else (f"slide {ns[0]}" if ns else "that slide")


def deck_theme(prs):
    """The deck's own look: the theme recorded when the agent made it, else the corporate look with the colour of its titles."""
    kw = prs.core_properties.keywords or ""
    m = re.search(r"theme:(\w+)", kw)
    a = re.search(r"accent:([0-9A-Fa-f]{6})", kw)
    if m:
        return PB.deck_theme(m.group(1), a.group(1) if a else None)
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame and is_title(sh):
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        try:
                            if r.font.color and r.font.color.type is not None and r.font.color.rgb is not None:
                                return PB.deck_theme("corporate", str(r.font.color.rgb))
                        except Exception:  # noqa: BLE001
                            continue
    return PB.deck_theme("corporate")


def _slide_ids(prs):
    return prs.slides._sldIdLst


def renumber(prs):
    """Our slide-number boxes say the slide's place again after slides were added, moved or deleted."""
    for i, s in enumerate(prs.slides, start=1):
        for sh in s.shapes:
            if sh.name == "SlideNumber" and sh.has_text_frame and sh.text_frame.paragraphs and sh.text_frame.paragraphs[0].runs:
                sh.text_frame.paragraphs[0].runs[0].text = str(i)


def _move_to(prs, old_index, new_index):
    lst = _slide_ids(prs)
    items = list(lst)
    el = items[old_index]
    lst.remove(el)
    lst.insert(new_index, el)


def _slides_of(prs, t, m=None):
    m = m or deck_map(prs)
    ns = find(m, t)
    if not ns:
        raise OpError(f"no such slide (the deck has {m['count']})")
    return m, ns


def op_slide_delete(prs, op, ctx):
    m, ns = _slides_of(prs, op.get("target"))
    if len(ns) >= m["count"]:
        raise OpError("that would delete every slide")
    lst = _slide_ids(prs)
    items = list(lst)
    for k in sorted(ns, reverse=True):
        el = items[k - 1]
        prs.part.drop_rel(el.get(qn("r:id")))
        lst.remove(el)
    renumber(prs)
    return (
        f"deleted slide{'s' if len(ns) > 1 else ''} {', '.join(str(x) for x in ns)} ({', '.join(repr(m['slides'][k - 1]['title'][:25]) for k in ns)})"
    )


def op_slide_move(prs, op, ctx):
    m = deck_map(prs)
    n = int(op.get("slide") or 0)
    if not 1 <= n <= m["count"]:
        raise OpError(f"no slide {n}")
    if op.get("to") is not None:
        to = m["count"] if op["to"] in ("end", "last") else 1 if op["to"] in ("start", "first") else int(op["to"])
    elif op.get("after") is not None:
        a = int(op["after"])
        to = a if a < n else a  # after slide a: position a+1 counting before removal
        to = a + 1 if a < n else a
    elif op.get("before") is not None:
        b = int(op["before"])
        to = b if b < n else b - 1
    else:
        raise OpError("where to?")
    to = max(1, min(m["count"], to))
    if to == n:
        raise OpError(f"slide {n} is already there")
    _move_to(prs, n - 1, to - 1)
    renumber(prs)
    return f"slide {n} ('{m['slides'][n - 1]['title'][:30]}') moved to position {to}"


def op_slide_swap(prs, op, ctx):
    m = deck_map(prs)
    a, b = int(op.get("a") or 0), int(op.get("b") or 0)
    if not (1 <= a <= m["count"] and 1 <= b <= m["count"]) or a == b:
        raise OpError("which two slides?")
    a, b = sorted((a, b))
    lst = _slide_ids(prs)
    items = list(lst)
    ea, eb = items[a - 1], items[b - 1]
    pa = ea.getprevious()  # never eb: a comes first
    eb.addprevious(ea)  # a goes where b was ...
    if pa is None:  # ... and b where a was
        lst.insert(0, eb)
    else:
        pa.addnext(eb)
    renumber(prs)
    return f"slides {a} and {b} swapped ('{m['slides'][a - 1]['title'][:25]}' <-> '{m['slides'][b - 1]['title'][:25]}')"


def op_slide_duplicate(prs, op, ctx):
    m = deck_map(prs)
    n = int(op.get("slide") or 0)
    if not 1 <= n <= m["count"]:
        raise OpError(f"no slide {n}")
    src = prs.slides[n - 1]
    new = prs.slides.add_slide(src.slide_layout)
    for sh in list(new.shapes):
        sh._element.getparent().remove(sh._element)
    for sh in src.shapes:
        if getattr(sh, "has_chart", False) and sh.has_chart:  # a chart gets a part of its own: a copy with its look and its data
            el = copy.deepcopy(sh._element)
            new.shapes._spTree.append(el)
            try:
                _clone_chart(prs, sh, el, new)
            except Exception:  # noqa: BLE001  (an unusual chart: made again from its numbers)
                el.getparent().remove(el)
                ch = sh.chart
                from pptx.chart.data import CategoryChartData

                cd = CategoryChartData()
                cd.categories = [str(c) for c in ch.plots[0].categories]
                for s_ in ch.plots[0].series:
                    cd.add_series(s_.name, list(s_.values))
                new.shapes.add_chart(ch.chart_type, sh.left, sh.top, sh.width, sh.height, cd)
            continue
        el = copy.deepcopy(sh._element)
        new.shapes._spTree.append(el)
        for blip in el.iter(qn("a:blip")):  # pictures: the copy points at the same image
            rid = blip.get(qn("r:embed"))
            if rid:
                blip.set(qn("r:embed"), new.part.relate_to(src.part.related_part(rid), src.part.rels[rid].reltype))
    try:
        new.background._cSld.insert(0, copy.deepcopy(src.background._cSld.bg)) if src.background._cSld.bg is not None else None
    except Exception:  # noqa: BLE001
        pass
    if src.has_notes_slide:
        new.notes_slide.notes_text_frame.text = src.notes_slide.notes_text_frame.text
    _move_to(prs, len(prs.slides) - 1, n)
    renumber(prs)
    return f"slide {n} duplicated (the copy is slide {n + 1})"


def _clone_chart(prs, sh, el, new_slide):
    """A copy of a chart's part (its XML and the workbook inside it) related to the new slide, so the copy keeps every
    colour, label and title of the original."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.parts.chart import ChartPart

    src = sh.chart.part
    pkg = prs.part.package
    part = ChartPart.load(pkg.next_partname("/ppt/charts/chart%d.xml"), src.content_type, pkg, src.blob)
    ext = part._element.find(qn("c:externalData"))  # it still points at the original's workbook: the copy gets its own
    if ext is not None:
        part._element.remove(ext)
    xlsx = src.chart_workbook.xlsx_part
    if xlsx is not None:
        part.chart_workbook.update_from_xlsx_blob(xlsx.blob)
    rid = new_slide.part.relate_to(part, RT.CHART)
    for c in el.iter(qn("c:chart")):
        c.set(qn("r:id"), rid)


SLIDE_SYSTEM = """You write ONE slide for a client's existing deck (its slide titles are given). Reply with ONE JSON object, one of:
  {"layout": "bullets", "title": "...", "bullets": ["...", ...], "notes": "..."}
  {"layout": "stats", "title": "...", "stats": [{"value": "...", "label": "..."}], "notes": "..."}
  {"layout": "process", "title": "...", "steps": [{"title": "...", "text": "..."}], "notes": "..."}
  {"layout": "comparison", "title": "...", "left": {"heading": "...", "bullets": [...]}, "right": {"heading": "...", "bullets": [...]}, "notes": "..."}
  {"layout": "chart", "title": "...", "chart": {"chart": "column|bar|pie|line", "categories": [...], "series": [{"name": "...", "values": [...]}]},
   "takeaway": "...", "notes": "..."}
  {"layout": "quote", "text": "...", "by": "...", "notes": "..."}     {"layout": "agenda", "items": [...]}
  {"layout": "closing", "title": "Thank you", "subtitle": "...", "contact": "..."}
Slide title = the message as a short sentence; at most 6 bullets of at most 12 words; no invented statistics; the deck's language."""


def op_slide_add(prs, op, ctx):
    m = deck_map(prs)
    spec = {k: v for k, v in op.items() if k not in ("op", "after", "about", "position")}
    if op.get("about"):
        if ctx.get("planner") is None:
            raise OpError("writing a slide needs the model")
        from ai_pc.office.edit_llm import _ask

        titles = "; ".join(f"{s['n']}. {s['title']}" for s in m["slides"])
        lay = f" Use the '{op['layout']}' layout." if op.get("layout") else ""
        spec = _ask(ctx["planner"], SLIDE_SYSTEM, f"DECK: {m['title']}\nSLIDES: {titles}\nWRITE A SLIDE: {op['about']}.{lay}")
        if not spec:
            raise OpError("the slide could not be written")
    lay = str(spec.get("layout") or "bullets")
    if lay == "bullets" and not spec.get("bullets"):
        spec["bullets"] = []
    after = op.get("after", "end")
    pos = m["count"] if after in ("end", "last", None) else 0 if after in ("start", "first") else int(after)
    th = ctx.get("th") or deck_theme(prs)
    d = PB._Deck.__new__(PB._Deck)
    d.d, d.th, d.prs, d.blank, d.n, d.out = {"title": m["title"], "meta": {}, "slides": []}, th, prs, _blank_layout(prs), pos, []
    rd = PB.resolve_deck({"title": m["title"], "theme": th["name"], "slides": [spec]})
    s = rd["slides"][-1]  # resolve_deck adds a title slide in front of a deck that has none
    getattr(d, "l_" + s["layout"])(s)
    _move_to(prs, len(prs.slides) - 1, pos)
    renumber(prs)
    title = s.get("title") or s.get("text") or ""
    ctx.setdefault("info", {})["added"] = {"at": pos + 1, "title": title, "layout": s["layout"]}
    return f"slide {pos + 1} added ({s['layout']}: '{str(title)[:40]}')"


def _blank_layout(prs):
    for lay in prs.slide_layouts:
        if not any(True for _ in lay.placeholders):
            return lay
    return prs.slide_layouts[min(6, len(prs.slide_layouts) - 1)]


def _text_shapes(slide, part="all"):
    out = []
    for sh in slide.shapes:
        if not sh.has_text_frame or sh.name in DECO or not sh.text_frame.text.strip():
            continue
        if part == "titles" and not is_title(sh):
            continue
        if part == "body" and is_title(sh):
            continue
        out.append(sh)
    return out


def op_title_set(prs, op, ctx):
    m = deck_map(prs)
    n = int(op.get("slide") or 0)
    if not 1 <= n <= m["count"]:
        raise OpError(f"no slide {n}")
    shs = _text_shapes(prs.slides[n - 1], "titles")
    if not shs:
        raise OpError(f"slide {n} has no title")
    p = shs[0].text_frame.paragraphs[0]
    set_para_md(p, str(op.get("text") or ""))
    for extra in shs[0].text_frame.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    return f"slide {n} title: '{op.get('text')}'"


def _replace_runs(p, find, repl):
    runs = list(p.runs)
    texts = [r.text for r in runs]
    full = "".join(texts)
    ms = list(re.finditer(r"(?<!\w)" + re.escape(find) + r"(?!\w)", full, re.I))
    if not ms:
        return 0
    bounds, pos = [], 0
    for t in texts:
        bounds.append((pos, pos + len(t)))
        pos += len(t)
    for mt in reversed(ms):
        s, e = mt.span()
        got = mt.group(0)
        new = repl.upper() if got.isupper() and len(got) > 1 and not repl.isupper() else (repl[:1].upper() + repl[1:] if got[:1].isupper() else repl)
        idx = [i for i, (a, b) in enumerate(bounds) if a < e and b > s]
        if not idx:
            continue
        f = idx[0]
        a, b = bounds[f]
        texts[f] = texts[f][: s - a] + new + (texts[f][e - a :] if e <= b else "")
        for i in idx[1:]:
            a2, b2 = bounds[i]
            texts[i] = texts[i][e - a2 :] if e < b2 else ""
    for r, t in zip(runs, texts):
        if r.text != t:
            r.text = t
    return len(ms)


def op_replace(prs, op, ctx):
    find, repl = str(op.get("find") or ""), str(op.get("with") or "")
    if not find:
        raise OpError("nothing to find")
    n = 0
    for s in prs.slides:
        for sh in s.shapes:
            frames = [sh.text_frame] if sh.has_text_frame else []
            if getattr(sh, "has_table", False) and sh.has_table:
                frames += [c.text_frame for row in sh.table.rows for c in row.cells]
            for tf in frames:
                for p in tf.paragraphs:
                    n += _replace_runs(p, find, repl)
        if s.has_notes_slide:
            for p in s.notes_slide.notes_text_frame.paragraphs:
                n += _replace_runs(p, find, repl)
    if not n:
        raise OpError(f"'{find}' is not in the deck")
    ctx.setdefault("info", {})["replaced"] = n
    return f"'{find}' replaced with '{repl}' ({n} time(s))"


def _rewrite_shapes(prs, op, ctx, translate=None):
    from ai_pc.office import edit_llm as EL

    if ctx.get("planner") is None:
        raise OpError("rewriting needs the model")
    m, ns = _slides_of(prs, op.get("target"))
    paras, where = [], []
    for k in ns:
        for sh in _text_shapes(prs.slides[k - 1], op.get("part") or "all"):
            for p in sh.text_frame.paragraphs:
                md = para_md(p)
                if md.strip():
                    paras.append(md)
                    where.append(p)
    if not paras:
        raise OpError("no text there")
    if translate:
        new = EL.translate(ctx["planner"], paras, translate, title=m["title"])
    else:
        new = EL.rewrite(
            ctx["planner"],
            paras,
            str(op.get("instruction") or "make it clearer") + ". These are slide texts: titles and short bullets.",
            keep_count=True,
            title=m["title"],
        )
    if len(new) != len(paras):
        raise OpError("the rewrite came back in a different shape; nothing changed")
    if new == paras:
        raise OpError("the new wording came out the same as the old")
    for p, md in zip(where, new):
        set_para_md(p, md)
    w0, w1 = sum(len(x.split()) for x in paras), sum(len(x.split()) for x in new)
    ctx.setdefault("info", {}).update(words_before=w0, words_after=w1, slides=ns)
    return f"{describe_target(m, op.get('target'))} {'translated into ' + str(translate) if translate else 'rewritten (' + str(op.get('instruction')) + ')'}: {w0} -> {w1} words"


def op_rewrite(prs, op, ctx):
    return _rewrite_shapes(prs, op, ctx)


def op_translate(prs, op, ctx):
    return _rewrite_shapes(prs, op, ctx, translate=op.get("language") or "Urdu")


def _colour(v):
    from ai_pc.office.docx_ops import colour

    try:
        return colour(v)
    except Exception as e:  # noqa: BLE001
        raise OpError(str(e)) from None


def _part_runs(slide, part="all"):
    """The runs a style reaches: titles, body (text boxes and table cells), table (cells only) or all."""
    if part != "table":
        for sh in _text_shapes(slide, part):
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.text.strip():
                        yield r
    if part in ("body", "all", "table"):
        for sh in slide.shapes:
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            for r in p.runs:
                                if r.text.strip():
                                    yield r


def op_style(prs, op, ctx):
    s = op.get("set") or {}
    if not s:
        raise OpError("nothing to change")
    m, ns = _slides_of(prs, op.get("target") or {"kind": "all"})
    part = op.get("part") or "all"
    n = 0
    for k in ns:
        for r in _part_runs(prs.slides[k - 1], part):
            if s.get("font"):
                r.font.name = s["font"]
            if s.get("size") is not None:
                cur = r.font.size.pt if r.font.size else 18.0
                from ai_pc.office.docx_ops import _new_size

                r.font.size = Pt(_new_size(cur, s["size"]))
            if s.get("color"):
                r.font.color.rgb = RGBColor.from_string(_colour(s["color"]))
            for kk in ("bold", "italic"):
                if s.get(kk) is not None:
                    setattr(r.font, kk, bool(s[kk]))
            n += 1
    if not n:
        raise OpError("no text there")
    from ai_pc.office.docx_ops import _say_set

    return f"{'titles' if part == 'titles' else 'body text' if part == 'body' else 'table text' if part == 'table' else 'text'} on {describe_target(m, op.get('target') or {'kind': 'all'})}: {_say_set(s)}"


SCHEME_LIGHT = re.compile(r"BACKGROUND_1|LIGHT_1|\bbg1\b|\blt1\b")
SCHEME_DARK = re.compile(r"TEXT_1|DARK_1|\btx1\b|\bdk1\b")


def _rgb_of(cf, default=None):
    """The RGB a colour format says, as far as the slide itself says it (its own RGB, the theme's light or dark text colour)."""
    try:
        if cf is None or cf.type is None:
            return default
        if cf.type == MSO_COLOR_TYPE.RGB:
            return str(cf.rgb)
        name = str(cf.theme_color)
        if SCHEME_LIGHT.search(name):
            return "FFFFFF"
        if SCHEME_DARK.search(name):
            return "000000"
    except Exception:  # noqa: BLE001
        pass
    return default


def _fill_rgb(x):
    """A shape's or a cell's own solid fill colour, or None (no fill, a picture, a gradient, the theme's)."""
    try:
        if x.fill.type == MSO_FILL.SOLID:
            return _rgb_of(x.fill.fore_color, None)
    except Exception:  # noqa: BLE001
        pass
    return None


def _xml_colour(el):
    """srgbClr / schemeClr (bg1, tx1) under an element, read without changing anything."""
    if el is None:
        return None
    for c in el.iter(qn("a:srgbClr"), qn("a:schemeClr")):
        if c.tag == qn("a:srgbClr"):
            return str(c.get("val")).upper()
        v = c.get("val") or ""
        return "FFFFFF" if SCHEME_LIGHT.search(v) else "000000" if SCHEME_DARK.search(v) else None
    return None


def slide_bg(slide):
    """The colour behind a slide's text: its own background, else its layout's, else its master's, else white. Read from the
    XML (python-pptx's background.fill would add an empty background to the layout or master just by looking)."""
    for owner in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        try:
            bg = owner._element.cSld.bg
        except Exception:  # noqa: BLE001
            bg = None
        if bg is None:
            continue
        pr = bg.find(qn("p:bgPr"))
        if pr is not None and pr.find(qn("a:solidFill")) is not None:
            c = _xml_colour(pr.find(qn("a:solidFill")))
            if c:
                return c
        ref = bg.find(qn("p:bgRef"))
        if ref is not None:
            c = _xml_colour(ref)
            if c:
                return c
    return "FFFFFF"


def _backdrop(slide, sh, bg):
    """What a text box reads against: its own fill, else the topmost filled shape under its middle (a card, a panel),
    else the slide's background."""
    own = _fill_rgb(sh)
    if own:
        return own
    try:
        cx, cy = sh.left + sh.width // 2, sh.top + sh.height // 2
    except Exception:  # noqa: BLE001
        return bg
    under = bg
    for other in slide.shapes:
        if other._element is sh._element:
            break
        try:
            if other.left <= cx <= other.left + other.width and other.top <= cy <= other.top + other.height:
                f = _fill_rgb(other)
                if f:
                    under = f
        except Exception:  # noqa: BLE001
            continue
    return under


def best_text(hx):
    return max(("FFFFFF", "1F2937"), key=lambda c: contrast(c, hx))


def _text_runs(slide, bg):
    """(run, backdrop) for every text on a slide: text boxes, table cells and charts' own texts are separate."""
    for sh in slide.shapes:
        if sh.has_text_frame:
            under = _backdrop(slide, sh, bg)
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.text.strip():
                        yield r, under, sh
        if getattr(sh, "has_table", False) and sh.has_table:
            for row in sh.table.rows:
                for cell in row.cells:
                    under = _fill_rgb(cell)
                    if under is None:
                        continue  # the table style paints it: not ours to judge
                    for p in cell.text_frame.paragraphs:
                        for r in p.runs:
                            if r.text.strip():
                                yield r, under, sh


def unreadable(prs, ns, limit=3.0):
    """Texts on these slides whose colour is too close to what is behind them (contrast under 3:1)."""
    bad = []
    for k in ns:
        slide = prs.slides[k - 1]
        bg = slide_bg(slide)
        for r, under, sh in _text_runs(slide, bg):
            c = _rgb_of(r.font.color)
            if c and contrast(c, under) < limit:
                bad.append({"slide": k, "text": r.text.strip()[:30], "colour": c, "behind": under, "contrast": round(contrast(c, under), 2)})
    return bad


def _chart_text(chart, old_bg, new_bg):
    """A chart's labels, legend and titles readable on a new background (labels inside bars or slices keep theirs)."""
    from pptx.text.text import Font

    n = 0
    els = list(chart._chartSpace.iter(qn("a:defRPr"), qn("a:rPr")))
    if not els:
        els = [chart.font._element] if hasattr(chart.font, "_element") else []
        els = els or list(chart._chartSpace.iter(qn("a:defRPr")))
    want = best_text(new_bg)
    for el in els:
        inside = False
        for anc in el.iterancestors(qn("c:dLbls")):
            pos = anc.find(qn("c:dLblPos"))
            inside = pos is not None and pos.get("val") in ("ctr", "inEnd", "inBase")
            break
        if inside:
            continue
        f = Font(el)
        cur = _rgb_of(f.color) or best_text(old_bg)
        if contrast(cur, new_bg) < 3.0:
            f.color.rgb = RGBColor.from_string(want)
            n += 1
    return n


def _lum(hx):
    r, g, b = (int(hx[i : i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def op_background(prs, op, ctx):
    """A background colour. Text that would no longer read against it (contrast under 3:1) turns white or near-black;
    text on a card or panel reads against that and stays; table rows painted in the old background colour take the new
    one; chart labels and legends follow the background."""
    m, ns = _slides_of(prs, op.get("target") or {"kind": "all"})
    hx = _colour(op.get("color") or "white")
    want = best_text(hx)
    fixed = 0
    for k in ns:
        slide = prs.slides[k - 1]
        old = slide_bg(slide)
        shapes = list(slide.shapes)
        cards = [(_backdrop(slide, sh, "BG") if sh.has_text_frame else None) for sh in shapes]  # judged before the background changes
        f = slide.background.fill
        f.solid()
        f.fore_color.rgb = RGBColor.from_string(hx)
        for sh, card in zip(shapes, cards):
            if sh.has_text_frame and card == "BG":  # on the background itself, not on a card
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if not r.text.strip():
                            continue
                        cur = _rgb_of(r.font.color) or best_text(old)  # inherited colour: it read against the old background
                        if contrast(cur, hx) < 3.0:
                            r.font.color.rgb = RGBColor.from_string(want)
                            fixed += 1
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        if _fill_rgb(cell) == old:
                            cell.fill.solid()
                            cell.fill.fore_color.rgb = RGBColor.from_string(hx)
                            for p in cell.text_frame.paragraphs:
                                for r in p.runs:
                                    cur = _rgb_of(r.font.color) or best_text(old)
                                    if r.text.strip() and contrast(cur, hx) < 3.0:
                                        r.font.color.rgb = RGBColor.from_string(want)
                                        fixed += 1
            if getattr(sh, "has_chart", False) and sh.has_chart:
                fixed += _chart_text(sh.chart, old, hx)
    return f"background {op.get('color')} on {describe_target(m, op.get('target') or {'kind': 'all'})}" + (
        f" ({fixed} text(s) recoloured so they still read)" if fixed else ""
    )


NOTES_SYSTEM = """You write speaker notes for slides: what the presenter says, 2-4 natural sentences per slide, adding the context the
slide leaves out (never just repeating the bullets). Reply with ONE JSON object: {"notes": ["...", ...]} one per slide, in order."""


def op_notes(prs, op, ctx):
    m, ns = _slides_of(prs, op.get("target") or {"kind": "all"})
    if op.get("text"):
        for k in ns:
            prs.slides[k - 1].notes_slide.notes_text_frame.text = str(op["text"])
        return f"notes set on {describe_target(m, op.get('target'))}"
    if ctx.get("planner") is None:
        raise OpError("writing notes needs the model")
    from ai_pc.office.edit_llm import _ask

    lines = [f"SLIDE {k}: " + " | ".join(t["text"].replace("\n", " / ") for t in m["slides"][k - 1]["texts"])[:600] for k in ns]
    d = _ask(ctx["planner"], NOTES_SYSTEM, f"DECK: {m['title']}\n" + "\n".join(lines)) or {}
    raw = d.get("notes") if isinstance(d, dict) else d
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, dict):  # {"1": "...", "2": "..."} / {"slide 4": "..."}
        raw = [raw[k] for k in sorted(raw, key=lambda x: int(re.sub(r"\D", "", str(x)) or 0))]
    notes = [str(x.get("notes") or x.get("text") or "") if isinstance(x, dict) else str(x) for x in raw or []]
    notes = [x.strip() for x in notes if x and x.strip()]
    if len(ns) == 1 and len(notes) > 1:  # one slide's notes sent as a list of sentences
        notes = [" ".join(notes)]
    if len(notes) != len(ns):
        raise OpError("the notes came back for a different number of slides")
    for k, t in zip(ns, notes):
        prs.slides[k - 1].notes_slide.notes_text_frame.text = t
    return f"speaker notes written for {describe_target(m, op.get('target') or {'kind': 'all'})} ({sum(len(x.split()) for x in notes)} words)"


def op_shrink(prs, op, ctx):
    """Smaller text. With "fit" ({"<slide>:<shape name>": [text height / box height, text width / box width]}, PowerPoint's
    measure) only the boxes that overflow, each by what it needs (wrapped text grows with the square of its size);
    else the body text by a factor."""
    m, ns = _slides_of(prs, op.get("target"))
    fit = op.get("fit") or {}
    n, said = 0, []
    for k in ns:
        shapes = [sh for sh in prs.slides[k - 1].shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        for sh in shapes:
            key = f"{k}:{sh.name}"
            if fit:
                if key not in fit:
                    continue
                rh, rw = (list(fit[key]) + [1.0, 1.0])[:2]
                txt = sh.text_frame.text.strip()
                if rh > 1.05 and rw <= 1.02 and txt and " " not in txt and sh.text_frame.word_wrap is not False:
                    sh.text_frame.word_wrap = False  # one line now; the next measure gives its width to size it by
                    said.append(f"{sh.name} on slide {k} kept on one line")
                    n += 1
                    continue
                f = max(0.55, min(0.95, min((1.0 / max(rh, 1e-6)) ** 0.5, 1.0 / max(rw, 1e-6)) * 0.95))
            else:
                if is_title(sh) or sh.name in DECO:
                    continue
                f = float(op.get("factor") or 0.85)
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(max(10, round((r.font.size.pt if r.font.size else 18.0) * f, 1)))
                    n += 1
            said.append(f"{sh.name} on slide {k} to {round(f * 100)}%")
    if not n:
        raise OpError("no text to shrink there")
    return (
        "text made smaller: " + ", ".join(said[:6])
        if fit
        else f"text made {round((1 - float(op.get('factor') or 0.85)) * 100)}% smaller on {describe_target(m, op.get('target'))}"
    )


def _body_shape(slide):
    shs = [sh for sh in _text_shapes(slide, "body") if sh.name in ("Body",) or (getattr(sh, "is_placeholder", False) and not is_title(sh))]
    return shs[0] if shs else None


def _no_list(prs, m, n):
    s = m["slides"][n - 1]
    what = "a chart" if s["chart"] else "a table" if s["table"] else "a picture" if s["picture"] else "no list"
    have = [k for k, sl in enumerate(prs.slides, start=1) if _body_shape(sl) is not None]
    return OpError(f"slide {n} ('{s['title'][:30]}') has {what}, not a bullet list; the slides with bullets are {have[:15] or 'none'}")


def op_bullet_add(prs, op, ctx):
    m = deck_map(prs)
    n = int(op.get("slide") or 0)
    if not 1 <= n <= m["count"]:
        raise OpError(f"no slide {n}")
    sh = _body_shape(prs.slides[n - 1])
    if sh is None:
        raise _no_list(prs, m, n)
    ps = [p for p in sh.text_frame.paragraphs if "".join(r.text for r in p.runs).strip()]
    model = ps[-1] if ps else sh.text_frame.paragraphs[0]
    new = copy.deepcopy(model._p)
    model._p.addnext(new)
    from pptx.text.text import _Paragraph

    p = _Paragraph(new, model._parent)
    set_para_md(p, str(op.get("text") or ""))
    return f"bullet added to slide {n}: '{op.get('text')}'"


def op_bullet_delete(prs, op, ctx):
    m = deck_map(prs)
    n = int(op.get("slide") or 0)
    if not 1 <= n <= m["count"]:
        raise OpError(f"no slide {n}")
    sh = _body_shape(prs.slides[n - 1])
    if sh is None:
        raise _no_list(prs, m, n)
    ps = [p for p in sh.text_frame.paragraphs if "".join(r.text for r in p.runs).strip() and p.level == 0]
    k = op.get("n")
    try:
        p = ps[-1] if k in ("last", -1) else ps[int(k) - 1]
    except (TypeError, ValueError, IndexError):
        raise OpError(f"slide {n} has {len(ps)} bullet(s)") from None
    txt = "".join(r.text for r in p.runs)
    p._p.getparent().remove(p._p)
    return f"bullet removed from slide {n}: '{txt[:40]}'"


OPS = {
    "slide_delete": op_slide_delete,
    "slide_move": op_slide_move,
    "slide_swap": op_slide_swap,
    "slide_duplicate": op_slide_duplicate,
    "slide_add": op_slide_add,
    "title_set": op_title_set,
    "replace": op_replace,
    "rewrite": op_rewrite,
    "translate": op_translate,
    "style": op_style,
    "background": op_background,
    "notes": op_notes,
    "shrink": op_shrink,
    "bullet_add": op_bullet_add,
    "bullet_delete": op_bullet_delete,
}


def _bad_keys(bad):
    return {(b["slide"], b["text"], b["colour"], b["behind"]) for b in bad}


def renumber_parts(prs):
    """Slide part names in slide order. python-pptx names a new slide by the number of slides, so after a deletion that
    name can belong to a slide still there: two parts with one name make a file PowerPoint cannot open."""
    from pptx.opc.packuri import PackURI

    slides = list(prs.slides)
    if all(str(sl.part.partname) == f"/ppt/slides/slide{i}.xml" for i, sl in enumerate(slides, start=1)):
        return
    for i, sl in enumerate(slides, start=1):
        sl.part.partname = PackURI(f"/ppt/slides/_slide{i}.xml")
    for i, sl in enumerate(slides, start=1):
        sl.part.partname = PackURI(f"/ppt/slides/slide{i}.xml")


def apply(prs, op, ctx):
    fn = OPS.get(op.get("op"))
    if fn is None:
        raise OpError(f"no deck operation '{op.get('op')}'")
    renumber_parts(prs)
    if op.get("op") in ("background", "style"):
        ctx.setdefault("info", {})["unreadable_before"] = _bad_keys(unreadable(prs, range(1, len(prs.slides) + 1)))
    return fn(prs, op, ctx)


def _style_misses(prs, op):
    """Texts in the styled part of the targeted slides that do not have the asked font / colour / bold / italic."""
    m = deck_map(prs)
    s = op.get("set") or {}
    n = miss = 0
    for k in find(m, op.get("target") or {"kind": "all"}):
        for r in _part_runs(prs.slides[k - 1], op.get("part") or "all"):
            n += 1
            if (
                (s.get("font") and r.font.name != s["font"])
                or (s.get("color") and _rgb_of(r.font.color) != _colour(s["color"]))
                or any(s.get(kk) is not None and bool(getattr(r.font, kk)) != bool(s[kk]) for kk in ("bold", "italic"))
            ):
                miss += 1
    return n, miss


def check(op, before, after, info=None, prs=None):
    k = op.get("op")
    info = info or {}
    if k in ("data_slide", "data_refresh") and prs is not None:
        return check_data(op, prs)
    if prs is not None and k in ("background", "style"):
        ns = find(after, op.get("target") or {"kind": "all"})
        old = info.get("unreadable_before") or set()
        bad = [b for b in unreadable(prs, ns) if (b["slide"], b["text"], b["colour"], b["behind"]) not in old]
        say = f"; hard to read: {', '.join(repr(b['text']) + ' on slide ' + str(b['slide']) for b in bad[:3])}" if bad else ""
        if k == "background":
            hx = _colour(op.get("color") or "white")
            wrong = [n for n in ns if slide_bg(prs.slides[n - 1]) != hx]
            return (
                not wrong and not bad,
                f"background {hx} on {len(ns) - len(wrong)}/{len(ns)} slides; every text reads"
                if not bad
                else f"background {hx} on {len(ns) - len(wrong)}/{len(ns)} slides{say}",
            )
        n, miss = _style_misses(prs, op)
        return n > 0 and not miss and not bad, f"{n - miss}/{n} texts styled{say}"
    if k == "slide_delete":
        return after["count"] < before["count"], f"{before['count']} -> {after['count']} slides"
    if k in ("slide_add", "slide_duplicate"):
        ok = after["count"] == before["count"] + 1
        if k == "slide_add" and info.get("added"):
            got = after["slides"][info["added"]["at"] - 1]["title"]
            ok = ok and (not info["added"]["title"] or str(info["added"]["title"])[:15].lower() in got.lower())
        return ok, f"{before['count']} -> {after['count']} slides"
    if k in ("slide_move", "slide_swap"):
        return [s["title"] for s in after["slides"]] != [s["title"] for s in before["slides"]], "order: " + " / ".join(
            s["title"][:14] for s in after["slides"][:8]
        )
    if k == "title_set":
        n = int(op.get("slide") or 0)
        return after["slides"][n - 1]["title"].lower().startswith(
            str(op.get("text"))[:20].lower()
        ), f"slide {n}: '{after['slides'][n - 1]['title'][:40]}'"
    if k == "replace":
        left = sum(
            1 for s in after["slides"] for t in s["texts"] if re.search(r"(?<!\w)" + re.escape(str(op.get("find"))) + r"(?!\w)", t["text"], re.I)
        )
        return left == 0, f"{info.get('replaced', '?')} replaced; {left} left"
    if k == "notes":
        ns = find(after, op.get("target") or {"kind": "all"})
        have = sum(1 for n in ns if after["slides"][n - 1]["notes"])
        return have == len(ns), f"{have}/{len(ns)} slides have notes"
    if k == "translate":
        ns = find(after, op.get("target") or {"kind": "all"})
        txt = " ".join(t["text"] for n in ns for t in after["slides"][n - 1]["texts"])
        letters = sum(1 for ch in txt if ch.isalpha())
        script = sum(1 for ch in txt if "\u0600" <= ch <= "\u06ff")
        if str(op.get("language", "")).lower() in ("urdu", "ur", "arabic", "persian", "farsi"):
            return (
                letters > 0 and script >= 0.5 * letters,
                f"{script}/{letters} letters in Arabic script on {describe_target(after, op.get('target') or {'kind': 'all'})}",
            )
        return txt != " ".join(t["text"] for n in ns for t in before["slides"][n - 1]["texts"]), "text changed"
    if k == "rewrite":
        w0, w1 = info.get("words_before"), info.get("words_after")
        if w0 and w1 and re.search(r"short|concise|fewer|brief|trim", str(op.get("instruction")), re.I):
            return w1 < w0, f"{w0} -> {w1} words"
        return True, f"{w0} -> {w1} words"
    if k in ("bullet_add", "bullet_delete"):
        n = int(op.get("slide") or 0)
        b0 = len(before["slides"][n - 1]["texts"]) and sum(len(t["paras"]) for t in before["slides"][n - 1]["texts"])
        b1 = sum(len(t["paras"]) for t in after["slides"][n - 1]["texts"])
        return (b1 > b0) if k == "bullet_add" else (b1 < b0), f"{b0} -> {b1} lines on slide {n}"
    return True, "applied"


def describe(op):
    k = op.get("op")
    t = op.get("target") or {}
    where = f" on slide {t.get('n')}" if t.get("n") else ""
    if k == "replace":
        return f"replace '{op.get('find')}' with '{op.get('with')}'"
    if k == "slide_add":
        return f"add a slide{' about ' + str(op.get('about')) if op.get('about') else ''}"
    if k == "slide_move":
        return f"move slide {op.get('slide')}"
    if k == "style":
        from ai_pc.office.docx_ops import _say_set

        return f"{op.get('part') or 'text'}{where}: {_say_set(op.get('set') or {})}"
    return k.replace("_", " ") + where


# ------------------------------------------------------------------------------------------------ data from a workbook
def linked(prs, link):
    """(slide number, shape) of the chart or table linked to a workbook by `link` (its name ends with '[aisrc_...]')."""
    for k, s in enumerate(prs.slides, start=1):
        for sh in s.shapes:
            if f"[{link}]" in (sh.name or ""):
                return k, sh
    return None, None


def data_links(prs):
    return sorted({m.group(1) for s in prs.slides for sh in s.shapes for m in [re.search(r"\[(aisrc_[0-9a-z]+)\]", sh.name or "")] if m})


def _takeaway(data, spec):
    """One sentence computed from the data itself (never written by a model): who leads, by how much."""
    try:
        s = spec["series"][0]
        j = data["header"].index(s["name"])
        pairs = [(c, v, data["rows"][i][j]) for i, (c, v) in enumerate(zip(spec["categories"], s["values"])) if v is not None]
        if len(pairs) < 2:
            return None
        top = max(pairs, key=lambda x: x[1])
        tot = sum(v for _, v, _ in pairs)
        if spec["chart"] == "line":
            low = min(pairs, key=lambda x: x[1])
            return f"Highest in {top[0]} ({top[2]}); lowest in {low[0]} ({low[2]})."
        return f"{top[0]} leads with {top[2]}" + (f", {top[1] / tot:.0%} of the total." if tot > 0 and all(v >= 0 for _, v, _ in pairs) else ".")
    except Exception:  # noqa: BLE001
        return None


def op_data_slide(prs, op, ctx):
    from ai_pc.office.docx_data import chart_spec

    data = op.get("data") or {}
    if not data.get("rows"):
        raise OpError("no data for the slide")
    kind = op.get("kind") or "chart"
    if kind == "table":
        rows = data["rows"] + ([data["total"]] if data.get("total") else [])
        if len(rows) > 12:
            raise OpError(f"{len(rows)} rows do not fit on a slide; ask for a chart, or a summary of it")
        spec = {"layout": "table", "title": op.get("title") or data.get("title") or "Figures", "table": {"columns": data["header"], "rows": rows}}
    else:
        cs = chart_spec(data, op)
        spec = {
            "layout": "chart",
            "title": op.get("title") or data.get("title") or cs["caption"],
            "chart": {"chart": cs["chart"], "categories": cs["categories"], "series": cs["series"]},
        }
        take = op.get("takeaway") if isinstance(op.get("takeaway"), str) else _takeaway(data, cs)
        if take:
            spec["takeaway"] = take
    done = op_slide_add(prs, {"op": "slide_add", "after": op.get("after", "end"), **spec}, ctx)
    at = ctx["info"]["added"]["at"]
    sh = next((x for x in prs.slides[at - 1].shapes if x.name in ("Chart", "Table")), None)
    if sh is None:
        raise OpError("the chart or table could not be drawn")
    sh.name = f"{sh.name} [{op['link']}]"
    if kind == "table" and data.get("total") and getattr(sh, "has_table", False) and sh.has_table:  # the totals row reads as one
        last = sh.table.rows[len(sh.table.rows) - 1]
        for cell in last.cells:
            for p_ in cell.text_frame.paragraphs:
                for r in p_.runs:
                    r.font.bold = True
    ctx["info"]["link"] = op["link"]
    return done + f", {'a native chart' if kind != 'table' else 'a table'} from {data.get('source') or 'the workbook'}"


def _set_cell(cell, text):
    tf = cell.text_frame
    p = tf.paragraphs[0]
    if p.runs:
        p.runs[0].text = str(text)
        for r in p.runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        p.add_run().text = str(text)
    for extra in tf.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


def op_data_refresh(prs, op, ctx):
    """The linked chart or table shows the workbook's current data again (a chart keeps its type and look)."""
    from pptx.chart.data import CategoryChartData

    from ai_pc.office.docx_data import chart_spec

    k, sh = linked(prs, op.get("link"))
    if sh is None:
        raise OpError("that chart or table is no longer in the deck")
    data = op.get("data") or {}
    if getattr(sh, "has_chart", False) and sh.has_chart:
        cs = chart_spec(data, op)
        cd = CategoryChartData()
        cd.categories = cs["categories"]
        for s in cs["series"]:
            cd.add_series(s["name"], s["values"])
        sh.chart.replace_data(cd)
        slide = prs.slides[k - 1]
        tk = next((x for x in slide.shapes if x.name == "Takeaway" and x.has_text_frame), None)
        new_take = _takeaway(data, cs)
        if tk is not None and new_take:  # the computed sentence follows the numbers
            set_para_md(tk.text_frame.paragraphs[0], new_take)
        return f"chart on slide {k} refreshed ({len(cs['categories'])} points, from {data.get('source') or 'the workbook'})"
    if getattr(sh, "has_table", False) and sh.has_table:
        rows = [data["header"]] + data["rows"] + ([data["total"]] if data.get("total") else [])
        t = sh.table
        if len(t.rows) == len(rows) and len(t.columns) == len(rows[0]):
            for i, r in enumerate(rows):
                for j, v in enumerate(r):
                    _set_cell(t.cell(i, j), v)
            return f"table on slide {k} refreshed ({len(rows) - 1} rows)"
        slide = prs.slides[k - 1]  # a different shape: the slide is drawn again in its place, with its title and notes
        title = slide_title(slide)
        notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        op_slide_delete(prs, {"target": {"kind": "slide", "n": k}}, ctx)
        renumber_parts(prs)
        op_data_slide(prs, {"after": k - 1, "kind": "table", "data": data, "title": title, "link": op["link"]}, ctx)
        if notes:
            prs.slides[k - 1].notes_slide.notes_text_frame.text = notes
        return f"table on slide {k} drawn again ({len(rows) - 1} rows, from {data.get('source') or 'the workbook'})"
    raise OpError("the linked shape is neither a chart nor a table")


def check_data(op, prs):
    """The linked chart holds exactly the workbook's values; the linked table shows exactly Excel's cells."""
    from ai_pc.office.docx_data import chart_spec

    k, sh = linked(prs, op.get("link"))
    if sh is None:
        return False, "the linked chart or table is missing"
    data = op.get("data") or {}
    if getattr(sh, "has_chart", False) and sh.has_chart:
        cs = chart_spec(data, op)
        plot = sh.chart.plots[0]
        cats = [str(c) for c in plot.categories]
        vals = [list(s.values) for s in plot.series]
        ok = cats == [str(c) for c in cs["categories"]] and all(
            all((a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-6) for a, b in zip(x, y["values"]))
            for x, y in zip(vals, cs["series"])
        )
        return ok, f"slide {k}: {len(cats)} categories, {len(vals)} series {'equal to' if ok else 'different from'} the workbook's"
    rows = [data["header"]] + data["rows"] + ([data["total"]] if data.get("total") else [])
    t = sh.table
    got = [[" ".join(t.cell(i, j).text.split()) for j in range(len(t.columns))] for i in range(len(t.rows))]
    want = [[" ".join(str(x).split()) for x in r] for r in rows]
    bad = sum(1 for a, b in zip(got, want) for x, y in zip(a, b) if x != y) + abs(len(got) - len(want))
    return bad == 0, f"slide {k}: {sum(len(r) for r in want) - bad}/{sum(len(r) for r in want)} cells equal Excel's"


OPS.update({"data_slide": op_data_slide, "data_refresh": op_data_refresh})
