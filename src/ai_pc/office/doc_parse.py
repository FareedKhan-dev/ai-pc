"""What a client's message asks of a Word document, as docx_ops operations, by rules (no model). What the rules cannot
read goes to the cheap model (docchat._llm), which answers in the same operations.

  r = parse(clause, m, focus)   m: docmap.docx_map; focus: the last target talked about ("make it bold" after "the title")
  -> {"ops": [...], "focus": target | None, "ask": question | None}

The targets a clause names (target_in): the title, headings / subheadings, the body, the whole document, a section by
name or number ("the introduction", "section 3", "the last section"), a paragraph ("the 2nd paragraph of the
conclusion"), a table ("table 2", "the last table", "all tables"), a list, or "it / this / that" (the focus).
"""

import re

from ai_pc.office import docmap as DM
from ai_pc.office import themes

ORD = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "sixth": 6,
    "6th": 6,
    "seventh": 7,
    "7th": 7,
    "eighth": 8,
    "8th": 8,
    "ninth": 9,
    "9th": 9,
    "tenth": 10,
    "10th": 10,
    "last": "last",
    "final": "last",
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}
COLOURS = dict(
    themes.COLOUR_WORDS,
    **{
        "dark blue": "1F3864",
        "light blue": "5B9BD5",
        "dark red": "8B0000",
        "dark green": "1B5E20",
        "white": "FFFFFF",
        "yellow": "FFC000",
        "light yellow": "FFF2CC",
        "light green": "C6EFCE",
        "light red": "FFC7CE",
        "pink": "FF66CC",
        "violet": "6A1B9A",
        "dark grey": "404040",
        "dark gray": "404040",
        "light grey": "A6A6A6",
        "light gray": "A6A6A6",
        "golden": "B8860B",
        "crimson": "B71C1C",
        "turquoise": "00838F",
        "indigo": "3949AB",
        "magenta": "AD1457",
    },
)
COLOUR_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in COLOURS), key=len, reverse=True)) + r")\b")
FONTS = [
    "times new roman",
    "arial",
    "calibri",
    "cambria",
    "georgia",
    "garamond",
    "segoe ui",
    "verdana",
    "tahoma",
    "century gothic",
    "book antiqua",
    "palatino linotype",
    "trebuchet ms",
    "consolas",
    "comic sans ms",
    "aptos",
    "helvetica",
    "candara",
    "constantia",
    "corbel",
    "franklin gothic",
    "gill sans",
    "lucida sans",
    "bahnschrift",
    "sitka",
    "ebrima",
    "nirmala ui",
    "jameel noori nastaleeq",
]
FONT_ALIAS = {"helvetica": "Arial", "times": "Times New Roman", "tnr": "Times New Roman", "segoe": "Segoe UI"}
LANGS = r"urdu|english|arabic|french|german|spanish|chinese|hindi|punjabi|turkish|persian|farsi"
NORMAL = [
    (r"\bpls\b|\bplz\b|\bplease\b", ""),
    (r"\bu\b", "you"),
    (r"\bur\b", "your"),
    (r"\bthx\b|\bthanks\b", "thanks"),
    (r"\bhead(?:ng|in|dng)s?\b", "headings"),
    (r"\bhedings?\b", "headings"),
    (r"\bparagra(?:f|ph|h)s?\b|\bpara\b", "paragraph"),
    (r"\bcolor\b", "colour"),
    (r"\bcentre\b", "center"),
    (r"\btabel\b|\btabl\b", "table"),
    (r"\bbull?its?\b", "bullets"),
    (r"\bmargine?s\b", "margins"),
    (r"\bfont ?size\b", "size"),
    (r"\bdocu?ment\b|\bdoc\b", "document"),
    (r"\btable of content\b", "table of contents"),
    (r"\bpage no\.?s?\b|\bpage numbering\b", "page numbers"),
    # Roman Urdu (a few common words)
    (r"\bkaro\b|\bkardo\b|\bkar do\b|\bkr do\b|\bkrdo\b", "make"),
    (r"\bhatao\b|\bhata do\b|\bnikalo\b|\bnikal do\b", "remove"),
    (r"\blagao\b|\blaga do\b|\bdaal do\b|\bdalo\b", "add"),
    (r"\bneela\b|\bnila\b", "blue"),
    (r"\blaal\b|\blal\b", "red"),
    (r"\bhara\b", "green"),
    (r"\bkala\b", "black"),
    (r"\bmota\b", "bold"),
    (r"\bbara\b|\bbada\b", "bigger"),
    (r"\bchota\b", "smaller"),
    (r"\bmein\b|\bme\b", "in"),
    (r"\bko\b", ""),
    (r"\baur\b", "and"),
]
QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”|(?<![A-Za-z])\'([^\']+)\'(?![A-Za-z])')
EDIT_VERB = (
    r"make|add|insert|put|remove|delete|drop|change|set|use|replace|rename|move|swap|rewrite|rephrase|paraphrase|shorten|expand|translate|"
    r"sort|center|centre|justify|bold|italic|italicize|underline|highlight|number|convert|turn|fix|proofread|correct|apply|format|style|"
    r"summarize|summarise|write|create|increase|decrease|reduce|enlarge|indent|align|start|split|merge|update|give|show|switch|colour|color|"
    r"filter|freeze|unfreeze|plot|pivot|trim|clean|fill|hide|unhide|round|rank|calculate|compute|chart|graph|tidy|look up|lookup|bring"
)


def normalize(text):
    s = " " + " ".join(str(text or "").split()) + " "
    quotes = []

    def keep(m):
        quotes.append(m.group(0))
        return f" QQ{len(quotes) - 1}QQ "

    s = QUOTE.sub(keep, s)
    s = s.lower()
    for a, b in NORMAL:
        s = re.sub(a, b, s)
    s = " ".join(s.split())
    for i, q in enumerate(quotes):
        s = s.replace(f"qq{i}qq", q)
    return s


def quoted(raw):
    return [a or b or c for a, b, c in QUOTE.findall(str(raw))]


ABBREV = re.compile(r"\b(dr|mr|mrs|ms|prof|st|no|vs|etc|e\.g|i\.e|approx|fig|vol|jr|sr|inc|ltd|co)\.\s", re.I)
FEATURES = (
    r"(?:a |an |the )?(?:table of contents|toc|contents page|page numbers?|header|footer|cover page|title page|margins?|page breaks?|"
    r"heading numbers|total row|totals)"
)


def clauses(text):
    """A message split into requests: sentences, then ' and ' / ', ' where a new request begins with an edit verb, and
    lists of features after one verb ("add a table of contents and page numbers" -> two requests)."""
    parts = []
    text = ABBREV.sub(lambda m_: m_.group(1) + "\u2024 ", str(text).strip())  # "Dr. Sana" is one sentence (one-dot leader, put back below)
    for sent in re.split(r"(?<=[.!?;])\s+|\n+", text):
        sent = sent.replace("\u2024", ".")
        sent = sent.strip(" .;")
        if not sent:
            continue
        pieces = re.split(
            r",?\s+(?:and then|then|and also|also|and|plus)\s+(?=(?:please\s+)?(?:" + EDIT_VERB + r")\b)|,\s+(?=(?:" + EDIT_VERB + r")\b)", sent
        )
        for piece in (p.strip(" ,") for p in pieces if p and p.strip(" ,")):
            mv = re.match(
                r"^((?:please\s+)?(?:add|insert|put|include|remove|delete|drop)\s+)(" + FEATURES + r")((?:\s*,\s*|\s+and\s+)" + FEATURES + r")+(.*)$",
                piece,
                re.I,
            )
            if mv:
                verb = mv.group(1)
                feats = re.findall(FEATURES, piece[len(verb) :], re.I)
                tail = re.sub(r"^(?:\s*(?:,|and)\s*" + FEATURES + r")+", "", piece[len(verb) + len(mv.group(2)) :], flags=re.I).strip()
                parts += [f"{verb}{f.strip()}" + (f" {tail}" if tail and i == len(feats) - 1 else "") for i, f in enumerate(feats)]
            else:
                parts.append(piece)
    return parts


# ------------------------------------------------------------------------------------------------ targets
def _sections_named(c, m):
    """Sections whose title is named in the clause (longest title first)."""
    out = []
    for s in sorted(m["sections"], key=lambda s: -len(s["title"])):
        t = DM._norm(re.sub(r"^\d+(\.\d+)*\.?\s+", "", s["title"]))
        if not t:
            continue
        words = t.split()
        if (
            re.search(r"\b" + re.escape(t) + r"\b", c)
            or (len(words) >= 2 and re.search(r"\b" + re.escape(" ".join(words[:2])) + r"\b", c))
            or (len(words) == 1 and len(t) > 4 and re.search(r"\b" + re.escape(t[: max(5, len(t) - 2)]), c))
        ):
            out.append(s)
    syn = {"intro": "introduction", "summary": "summary", "conclusions": "conclusion", "recommendation": "recommendations", "refs": "references"}
    for k, v in syn.items():
        if re.search(r"\b" + k + r"\b", c):
            s = DM.find_section(m, {"name": v})
            if s and s not in out:
                out.append(s)
    return out


def target_in(c, m, focus=None):
    """The target a clause names, or None."""
    if re.search(
        r"^\s*(?:please\s+)?(?:format|style|restyle|re-?format)\s+(?:it|this|everything|the (?:whole |entire )?(?:document|file|essay|assignment|report))\b",
        c,
    ):
        return {"kind": "all"}
    mm = re.search(
        r"\b(?:the )?(first|second|third|fourth|fifth|sixth|last|final|\d+(?:st|nd|rd|th)) paragraph\b(?:\s+(?:of|in|from)\s+(?:the\s+)?(.+?))?(?=$|\s+(?:to|into|with|as|and|bold|italic|shorter|longer|more|in)\b|,)",
        c,
    )
    if mm:
        n = ORD.get(mm.group(1), None) or int(re.sub(r"\D", "", mm.group(1)) or 1)
        t = {"kind": "paragraph", **({"which": "last"} if n == "last" else {"n": n})}
        if mm.group(2):
            secs = _sections_named(mm.group(2), m)
            sn = re.search(r"section (\d+)", mm.group(2))
            if secs:
                t["in"] = {"kind": "section", "name": re.sub(r"^\d+(\.\d+)*\.?\s+", "", secs[0]["title"])}
            elif sn:
                t["in"] = {"kind": "section", "n": int(sn.group(1))}
        return t
    mm = re.search(r"\bparagraph (\d+)\b", c)
    if mm:
        return {"kind": "paragraph", "n": int(mm.group(1))}
    mm = re.search(r"\b(?:all|every|both|the)\s+tables\b|\btables\b", c)
    if mm and not re.search(r"\btable of contents\b", c):
        return {"kind": "table", "which": "all"}
    mm = re.search(r"\b(?:the )?(first|second|third|fourth|fifth|last|\d+(?:st|nd|rd|th)) table\b|\btable (\d+)\b", c)
    if mm and not re.search(r"\btable of contents\b", c):
        w = mm.group(1) or mm.group(2)
        n = ORD.get(w) or int(re.sub(r"\D", "", w) or 1)
        return {"kind": "table", **({"which": "last"} if n == "last" else {"n": n})}
    if re.search(r"\bthe table\b|\bthis table\b|\btable\b", c) and not re.search(r"\btable of contents\b", c) and m["tables"]:
        return {"kind": "table", "n": 1} if len(m["tables"]) == 1 or not (focus or {}).get("kind") == "table" else focus
    mm = re.search(
        r"\b(?:the )?(first|second|third|fourth|fifth|sixth|last|final|\d+(?:st|nd|rd|th)) (?:section|chapter|part)\b|\b(?:section|chapter) (\d+)\b",
        c,
    )
    if mm:
        w = mm.group(1) or mm.group(2)
        n = ORD.get(w) or int(re.sub(r"\D", "", w) or 1)
        return {"kind": "section", **({"which": "last"} if n == "last" else {"n": n})}
    secs = _sections_named(c, m)
    if secs:
        return {"kind": "section", "name": re.sub(r"^\d+(\.\d+)*\.?\s+", "", secs[0]["title"])}
    if re.search(r"\bsub-?headings?\b|\bsub ?titles?\b|\bsecond[- ]level headings?\b", c):
        return {"kind": "headings", "level": 2}
    if re.search(r"\b(?:main|top[- ]level|section|chapter) (?:headings?|titles?)\b", c):
        return {"kind": "headings", "level": 1}
    if re.search(r"\bheadings?\b|\bheaders? of (?:the )?sections\b", c):
        return {"kind": "headings"}
    if re.search(r"\b(?:the |document )title\b|\bmain title\b|\btitle\b", c) and not re.search(r"\btitle page\b|\btitle case\b", c):
        return {"kind": "title"}
    if re.search(r"\b(?:the )?(?:list|bullets|bullet points)\b", c) and m["items"] and any(it.get("list") for it in m["items"]):
        return {"kind": "list", "n": 1}
    if re.search(r"\b(?:body(?: text)?|paragraphs|normal text|main text|running text)\b", c):
        return {"kind": "body"}
    if re.search(
        r"\b(?:whole|entire|full|all of the) (?:document|text|thing|file)\b|\beverything\b|\ball (?:the )?text\b|\bthroughout\b|\beverywhere\b", c
    ):
        return {"kind": "all"}
    if re.search(r"\b(?:it|this|that|them|those|these)\b", c) and focus:
        return focus
    return None


# ------------------------------------------------------------------------------------------------ properties
def style_set(c):
    """Font, size, colour, emphasis, alignment, spacing and case words in a clause -> {"set": ...}."""
    s = {}
    col = COLOUR_RX.search(c)
    if col and not re.search(r"\bhighlight", c):
        s["color"] = col.group(1)
    for f in FONTS:
        if re.search(r"\b" + re.escape(f) + r"\b", c):
            s["font"] = FONT_ALIAS.get(f, " ".join(w.capitalize() if w not in ("ui", "ms") else w.upper() for w in f.split()))
            break
    mm = re.search(
        r"\b(?:size|to|at|in)\s*(\d{1,2}(?:\.5)?)\s*(?:pt|points?|px)?\b(?!\s*(?:cm|mm|inch|in\b|%|spacing|line|columns?))", c
    ) or re.search(r"\b(\d{1,2}(?:\.5)?)\s*(?:pt|points?)\b", c)
    if not mm and s.get("font"):
        mm = re.search(re.escape(s["font"].lower()) + r"\s*,?\s*(?:size\s*)?(\d{1,2}(?:\.5)?)\b(?!\s*(?:cm|mm|inch|%|spacing|line|columns?))", c)
    if mm and float(mm.group(1)) >= 6 and not re.search(r"spacing|margins?", c[max(0, mm.start() - 15) : mm.end() + 12]):
        s["size"] = float(mm.group(1))
    elif re.search(r"\b(?:bigger|larger|increase|enlarge|grow)\b", c) and not re.search(r"spacing|margins?", c):
        s["size"] = "bigger"
    elif (
        re.search(r"\b(?:smaller|decrease|reduce|shrink)\b", c)
        and re.search(r"\b(?:font|size|text|smaller)\b", c)
        and not re.search(r"spacing|margins?", c)
    ):
        s["size"] = "smaller"
    neg = re.search(r"\b(?:not|no|remove|un|without)\s*(?:the\s*)?(bold|italics?|underline)", c)
    if re.search(r"\bbold(?:er)?\b", c) and not (neg and neg.group(1) == "bold"):
        s["bold"] = True
    if neg and neg.group(1) == "bold" or re.search(r"\bunbold\b", c):
        s["bold"] = False
    if re.search(r"\bitali(?:c|cs|ci[sz]e)\b", c) and not (neg and neg.group(1).startswith("italic")):
        s["italic"] = True
    if neg and neg.group(1).startswith("italic"):
        s["italic"] = False
    if re.search(r"\bunderlined?\b", c) and not (neg and neg.group(1) == "underline"):
        s["underline"] = True
    if re.search(r"\bjustif(?:y|ied)\b", c):
        s["align"] = "justify"
    elif re.search(r"\bcent(?:er|re)(?:ed)?\b", c):
        s["align"] = "center"
    elif re.search(r"\bright[- ]align(?:ed)?\b|\balign(?:ed)? (?:to the )?right\b", c):
        s["align"] = "right"
    elif re.search(r"\bleft[- ]align(?:ed)?\b|\balign(?:ed)? (?:to the )?left\b", c):
        s["align"] = "left"
    mm = re.search(
        r"\b(single|double|1\.15|1\.5|one and a half|2|2\.0|1)\s*(?:-|\s)?(?:line\s*)?spac(?:ing|ed)\b|\bline spacing (?:of |to )?(\d(?:\.\d+)?)\b|\bdouble[- ]spaced\b",
        c,
    )
    if mm:
        v = mm.group(1) or mm.group(2) or "double"
        s["line_spacing"] = {"single": 1.0, "double": 2.0, "one and a half": 1.5}.get(v, v)
    mm = re.search(r"\bspac(?:e|ing) after (?:each |every )?(?:paragraphs?)? ?(?:of |to )?(\d{1,2})\s*(?:pt|points?)?", c)
    if mm:
        s["space_after"] = float(mm.group(1))
    if re.search(r"\bindent (?:the )?first lines?\b|\bfirst[- ]line indent\b", c):
        s["first_line_indent"] = 1.27
    elif re.search(r"\b(?:no|remove (?:the )?)(?:first[- ]line )?indent", c):
        s["first_line_indent"] = 0.0
    if re.search(r"\b(?:upper ?case|all caps|capital letters|capitals)\b", c):
        s["case"] = "upper"
    elif re.search(r"\btitle case\b|\bcapitali[sz]e (?:each|every|all) words?\b", c):
        s["case"] = "title"
    elif re.search(r"\blower ?case\b|\bsmall letters\b", c):
        s["case"] = "lower"
    elif re.search(r"\bsentence case\b", c):
        s["case"] = "sentence"
    return s


def _cm(v, unit):
    v = float(v)
    return round(v * 2.54, 2) if unit.startswith("in") or unit == '"' else round(v / 10, 2) if unit == "mm" else round(v, 2)


# ------------------------------------------------------------------------------------------------ the parser
def parse(clause, m, focus=None, raw=None, carry=False):
    """carry: the clause continues the previous one of the same message ("make the headings blue and use Georgia"):
    without a target of its own it means the same thing."""
    c = normalize(clause)
    raw = raw or clause
    q = quoted(raw)
    cm = QUOTE.sub(" QQ ", c)  # the clause with its quoted text masked: what to find or write is not a target
    t = target_in(cm, m, focus)
    if t is None and carry and focus:
        t = focus
    out = {"ops": [], "focus": t or focus, "ask": None}

    def done(*ops, focus_=None):
        out["ops"] = [o for o in ops if o]
        if focus_ is not None:
            out["focus"] = focus_
        return out

    remove = bool(re.search(r"\b(?:remove|delete|drop|get rid of|take (?:out|off)|no more|without|hide|turn off)\b", c))
    bool(re.search(r"\b(?:add|insert|put|include|create|give|show|need|want|write|place|make)\b", c))

    # ---- page numbers, header / footer, contents page, cover
    if re.search(r"\bpage numbers?\b|\bnumber the pages\b|\bpage x of y\b", c):
        if remove:
            return done({"op": "page_numbers", "remove": True})
        pos = "top" if re.search(r"\btop\b|\bheader\b", c) else "bottom"
        al = "right" if re.search(r"\bright\b", c) else "left" if re.search(r"\bleft\b", c) else "center"
        f = (
            "Page X of Y"
            if re.search(r"\bof y\b|\bout of\b|\bx of y\b|\btotal\b", c)
            else "X"
            if re.search(r"\bjust (?:the )?numbers?\b|\bonly (?:the )?numbers?\b", c)
            else "Page X"
        )
        return done(
            {
                "op": "page_numbers",
                "position": pos,
                "align": al,
                "format": f,
                "skip_first": bool(re.search(r"\bnot on (?:the )?(?:first|cover)|\bskip (?:the )?(?:first|cover)", c)),
            }
        )
    mm = re.search(r"\b(header|footer)\b", c)
    if mm and not re.search(r"\bheader row\b|\bheaders? of (?:the )?(?:table|columns)\b|\btable header\b", c):
        which = mm.group(1)
        if remove:
            return done({"op": which, "remove": True})
        text = q[0] if q else None
        if not text:
            mt = re.search(r"\b(?:saying|that says|with|reading|:)\s+(.+)$", raw, re.I)
            text = mt.group(1).strip(" .") if mt else None
        if text:
            al = "left" if re.search(r"\bleft\b", c) else "center" if re.search(r"\bcent", c) else None
            return done({"op": which, "text": text, **({"align": al} if al else {})})
        out["ask"] = f"What should the {which} say?"
        return out
    if re.search(r"\btable of contents\b|\btoc\b|\bcontents page\b|\bcontents\b(?= (?:at|to|in|page))|\bindex page\b", c):
        if remove:
            return done({"op": "toc", "remove": True})
        return done({"op": "toc"})
    if re.search(r"\b(?:cover|title|front) page\b", c):
        if remove:
            return done({"op": "cover", "remove": True})
        lines = []
        for lbl, rx in (
            ("Submitted by", r"\b(?:my name(?: is)?|name|by|student)\s*:?\s*([A-Z][\w.]*(?: [A-Z][\w.]*){0,3})"),
            ("Roll No.", r"\broll (?:no\.?|number|#)\s*:?\s*([\w-]+)"),
            ("Course", r"\bcourse\s*:?\s*([\w -]+?)(?=,| and |$)"),
            (
                "Submitted to",
                r"\b(?:teacher|instructor|professor|submitted to|sir|madam|miss)\s*:?\s*((?:dr\.?|mr\.?|ms\.?|mrs\.?|prof\.?)?\s*[A-Z][\w.]*(?: [A-Z][\w.]*){0,3})",
            ),
            ("Date", r"\bdate\s*:?\s*([\w ,]+?)(?=,| and |$)"),
        ):
            mt = re.search(rx, raw)
            if mt:
                lines.append(f"**{lbl}:** {mt.group(1).strip()}")
        return done({"op": "cover", **({"title": q[0]} if q else {}), "lines": lines})
    # ---- a whole look ("make it look academic", "format it professionally")
    mm = re.search(
        r"\b(?:make (?:it|this|the document|everything)\s+)?look(?:s)?\s+(?:more\s+|very\s+|really\s+)?(professional|formal|academic|university|"
        r"scholarly|modern|elegant|minimal|clean|corporate|business|warm|classic|simple)\b|\b(?:apply|use)\s+(?:an?\s+|the\s+)?(academic|university|corporate|"
        r"business|modern|elegant|minimal|warm|professional)\s+(?:formatting|style|look|theme|format)\b|\b(professional|academic|university|corporate|modern|"
        r"elegant|minimal)\s+(?:formatting|theme|look)\b",
        c,
    )
    if mm:
        w = mm.group(1) or mm.group(2) or mm.group(3)
        name = {
            "professional": "corporate",
            "formal": "corporate",
            "business": "corporate",
            "corporate": "corporate",
            "academic": "academic",
            "university": "academic",
            "scholarly": "academic",
            "modern": "modern",
            "elegant": "elegant",
            "classic": "elegant",
            "minimal": "minimal",
            "clean": "minimal",
            "simple": "minimal",
            "warm": "warm",
        }[w]
        col = COLOUR_RX.search(c)
        sx = {k: v for k, v in style_set(c).items() if k not in ("color",)}  # explicit values beat the theme ("academic, but Arial 11")
        return done(
            {"op": "theme", "name": name, **({"accent": col.group(1)} if col else {})},
            *([{"op": "style", "target": {"kind": "all"}, "set": sx}] if sx else []),
        )
    # ---- page set-up
    page = {}
    mm = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(inch|inches|in|\"|cm|mm)\s*margins?\b|\bmargins?\s*(?:of|to|at|=|:)?\s*(\d+(?:\.\d+)?)\s*(inch|inches|in|\"|cm|mm)\b",
        c,
    )
    if mm:
        page["margins"] = _cm(mm.group(1) or mm.group(3), mm.group(2) or mm.group(4))
    elif re.search(r"\bnarrow margins?\b", c):
        page["margins"] = 1.27
    elif re.search(r"\b(?:normal|standard|default) margins?\b", c):
        page["margins"] = 2.54
    elif re.search(r"\bwide margins?\b", c):
        page["margins"] = 3.18
    if re.search(r"\blandscape\b", c):
        page["orientation"] = "landscape"
    elif re.search(r"\bportrait\b", c):
        page["orientation"] = "portrait"
    mm = re.search(r"\b(a4|a5|letter|legal)\b(?:\s+(?:size|paper|page))?", c)
    if mm and re.search(r"\b(?:size|paper|page|set|use|make|to)\b", c):
        page["size"] = mm.group(1)
    mm = re.search(r"\b(one|single|two|2|three|3)\s+columns?\b|\bcolumns?\s*(?:to|=)?\s*(\d)\b", c)
    if mm and not re.search(r"\btable\b|\bcolumn (?:called|named)\b|\badd (?:a |an )?column\b", c):
        page["columns"] = (
            {"one": 1, "single": 1, "two": 2, "three": 3}.get(mm.group(1) or "", int(mm.group(1) or mm.group(2) or 1))
            if (mm.group(1) or "") not in ("2", "3")
            else int(mm.group(1))
        )
    if page:
        return done({"op": "page", "set": page})
    # ---- themes, structure, numbering, lists, page breaks
    mm = re.search(
        r"\b(?:look|make it|format|style|formatting|restyle|apply)\b.*?\b(professional|formal|academic|university|scholarly|modern|elegant|minimal|"
        r"clean|corporate|business|warm|classic|simple)\b",
        c,
    )
    if mm and not t or (mm and t and t.get("kind") == "all"):
        name = {
            "professional": "corporate",
            "formal": "corporate",
            "business": "corporate",
            "corporate": "corporate",
            "academic": "academic",
            "university": "academic",
            "scholarly": "academic",
            "modern": "modern",
            "elegant": "elegant",
            "classic": "elegant",
            "minimal": "minimal",
            "clean": "minimal",
            "simple": "minimal",
            "warm": "warm",
        }[mm.group(1)]
        col = COLOUR_RX.search(c)
        sx = {k: v for k, v in style_set(c).items() if k not in ("color",)}  # explicit values beat the theme ("academic, but Arial 11")
        return done(
            {"op": "theme", "name": name, **({"accent": col.group(1)} if col else {})},
            *([{"op": "style", "target": {"kind": "all"}, "set": sx}] if sx else []),
        )
    if re.search(r"\bformat (?:it|this|the document|my (?:assignment|document|report))? ?(?:properly|nicely|correctly|professionally|well)\b", c):
        return done({"op": "theme", "name": "academic" if re.search(r"\bassignment|university|thesis|essay\b", c) else "corporate"})
    if re.search(r"\b(?:real|proper|actual) headings?\b|\bheading styles?\b|\bfix (?:the )?headings?\b|\bdetect (?:the )?headings?\b", c):
        return done({"op": "structure"})
    if re.search(
        r"\bnumber (?:the |all (?:the )?)?(?:headings|sections|chapters)\b|\bnumbered headings\b|\bheading numbers?\b|\bsection numbers?\b", c
    ):
        return done({"op": "heading_numbers", "remove": remove})
    if re.search(
        r"\b(?:each|every|all) (?:section|chapter|heading)s? (?:on|starts? on|begins? on|from|to start on) (?:a )?new page\b|\bpage breaks? before\b",
        c,
    ):
        return done({"op": "page_breaks", "level": 2 if re.search(r"\bsub", c) else 1})
    if remove and re.search(r"\b(?:page breaks?|blank pages?|empty pages?)\b", c):
        return done({"op": "page_breaks", "remove": True})
    if (
        re.search(r"\b(?:bullet(?:ed)? (?:list|points)|bullets|numbered list|a list)\b", c)
        and t
        and t.get("kind") in ("paragraph", "section", "section_body", "paragraphs")
        and re.search(r"\b(?:make|turn|convert|change|as|into|to)\b", c)
    ):
        tt = {**t, "kind": "section_body"} if t.get("kind") == "section" else t
        return done({"op": "list", "target": tt, "kind": "numbered" if re.search(r"\bnumbered\b", c) else "bullets"}, focus_=tt)
    if re.search(r"\bremove (?:the )?(?:bullets|bullet points|numbering)\b", c) and t:
        return done({"op": "list", "target": t, "kind": "none"})
    # ---- tables
    tabley = (
        re.search(r"\btables?\b", c)
        and not re.search(r"\btable of contents\b", c)
        or (
            m["tables"]
            and re.search(r"\b(?:columns?|rows?|totals?)\b", c)
            and re.search(r"\b(?:add|insert|delete|remove|drop|sort|total|put|include)\b", c)
            and not re.search(r"\b(?:two|three|\d) columns\b|\bcolumns? layout\b", c)
        )
        or (m["tables"] and re.search(r"\bsort\b", c))
    )
    if tabley:
        tt = t if t and t.get("kind") == "table" else (focus if (focus or {}).get("kind") == "table" else {"kind": "table", "n": 1})
        if (
            re.search(r"\b(?:total|totals|sum)\b", c)
            and re.search(r"\b(?:add|put|include|show|give|calculate|total)\b", c)
            and not re.search(r"\bcolumn\b", c)
        ):
            return done({"op": "table_total", "target": tt}, focus_=tt)
        mm = re.search(
            r"\bsort\b.*?\bby\s+(?:the\s+)?(.+?)(?:\s+column)?(?:\s+(desc\w*|asc\w*|highest first|lowest first|largest first|smallest first|"
            r"biggest first|a-z|z-a|alphabetical\w*|reverse))?\s*$",
            c,
        )
        if mm:
            desc = bool(mm.group(2) and re.search(r"desc|highest|largest|biggest|z-a|reverse", mm.group(2)))
            return done({"op": "table_sort", "target": tt, "by": mm.group(1).strip(), "desc": desc}, focus_=tt)
        if re.search(r"\b(?:add|insert|put)\b.*\brow\b", c):
            mt = re.search(r"\brow\b[^:]*:\s*(.+)$", raw, re.I) or re.search(r"\brow (?:with|for|containing)\s+(.+)$", raw, re.I)
            vals = [v.strip() for v in re.split(r"\s*[;|]\s*|,\s+", mt.group(1).strip(" ."))] if mt else []
            if not vals:
                out["ask"] = "What goes in the new row? (e.g. 'add a row: Batteries, 350,000')"
                return out
            return done({"op": "table_add_row", "target": tt, "values": vals}, focus_=tt)
        mm = re.search(
            r"\b(?:delete|remove|drop)\b.*?\b(?:the )?(first|last|second|third|\d+(?:st|nd|rd|th)?) row\b|\brow (\d+)\b|\brow (?:with|containing|for)\s+(.+)$",
            c,
        )
        if mm and remove:
            w = mm.group(1) or mm.group(2)
            if mm.group(3):
                return done({"op": "table_delete_row", "target": tt, "match": mm.group(3).strip(" .")}, focus_=tt)
            return done(
                {"op": "table_delete_row", "target": tt, "row": "last" if w == "last" else ORD.get(w) or int(re.sub(r"\D", "", w) or 1)}, focus_=tt
            )
        if re.search(r"\b(?:add|insert|put)\b.*\bcolumn\b", c):
            mt = re.search(
                r"\bcolumn\s+(?:called|named|for|titled)?\s*['\"]?([\w %().-]+?)['\"]?\s*(?:=|:|as|showing|with|that shows|which is|that is|equal to)\s*(.+)$",
                raw,
                re.I,
            )
            if mt:
                name, expr = mt.group(1).strip(), mt.group(2).strip(" .")
                pm = (
                    None
                    if re.match(r"^\s*\d+(?:\.\d+)?\s*%", expr)
                    else re.search(r"(?:share|percent(?:age)?|%) of (?:the )?(?:total )?['\"]?([\w ()]+?)['\"]?$", expr, re.I)
                )  # "18% of X" is a rate, not a share
                if pm:
                    return done({"op": "table_add_column", "target": tt, "name": name, "percent_of": pm.group(1).strip()}, focus_=tt)
                head = next((tb["header"] for tb in m["tables"] if tb["t"] == tt.get("n", 1)), m["tables"][0]["header"] if m["tables"] else [])
                f = expr
                for h in sorted(head, key=len, reverse=True):
                    core = re.sub(r"\s*\(.*?\)\s*", "", h).strip()
                    for name_ in {h, core}:
                        if name_ and re.search(r"(?<![\w\[])" + re.escape(name_) + r"(?![\w\]])", f, re.I):
                            f = re.sub(r"(?<![\w\[])" + re.escape(name_) + r"(?![\w\]])", f"[{h}]", f, flags=re.I)
                mp = re.match(r"^(\d+(?:\.\d+)?)\s*%\s*of\s*(\[.+\])$", f)
                if mp:
                    f = f"{mp.group(2)} * {float(mp.group(1)) / 100}"
                f = f.replace("×", "*").replace(" x ", " * ").replace("÷", "/")
                if "[" in f:
                    return done({"op": "table_add_column", "target": tt, "name": name, "formula": f}, focus_=tt)
            out["ask"] = "What should the new column hold? (e.g. 'add a column Tax = 18% of Amount' or 'add a column Share = share of Amount')"
            return out
        mm = re.search(r"\b(?:delete|remove|drop)\s+(?:the\s+)?['\"]?(.+?)['\"]?\s+column\b|\bcolumn\s+['\"]?(.+?)['\"]?\b", c)
        if mm and remove:
            return done({"op": "table_delete_column", "target": tt, "name": (mm.group(1) or mm.group(2)).strip()}, focus_=tt)
        if re.search(r"\b(?:total|totals|sum)\b", c) and re.search(r"\b(?:add|put|include|show|give|calculate|total)\b", c):
            return done({"op": "table_total", "target": tt}, focus_=tt)
        mm = re.search(r"\b(bar|column|pie|line|doughnut|donut|area)?\s*(?:chart|graph|plot)\b", c)
        if mm:
            kind = {"donut": "doughnut"}.get(mm.group(1) or "", mm.group(1) or "column")
            return done({"op": "chart", "target": tt, "chart": kind}, focus_=tt)
        if re.search(
            r"\b(?:style|format|design|colou?r|make (?:it|them|the tables?) look|professional|nicer|better|consistent)\b", c
        ) and not re.search(r"\bdelete|remove\b", c):
            col = COLOUR_RX.search(c)
            all_ = {"kind": "table", "which": "all"} if re.search(r"\btables\b|\ball\b", c) else tt
            return done({"op": "table_style", "target": all_, **({"accent": col.group(1)} if col else {})}, focus_=all_)
    if re.search(r"\b(?:chart|graph)\b.*\b(?:from|of|for)\b.*\b(?:table|data|numbers)\b", c) and m["tables"]:
        mm = re.search(r"\b(bar|column|pie|line|doughnut|area)\b", c)
        return done({"op": "chart", "target": {"kind": "table", "n": 1}, "chart": mm.group(1) if mm else "column"})
    # ---- translate, rewrite, summaries
    mm = re.search(
        r"\btranslate\b.*?\b(?:in|into|to)\s+("
        + LANGS
        + r")\b|\b(?:in|into)\s+("
        + LANGS
        + r")\b.*\btranslat|\bconvert\b.*\b(?:in|into|to)\s+("
        + LANGS
        + r")\b",
        c,
    )
    if mm:
        lang = mm.group(1) or mm.group(2) or mm.group(3)
        tt = t or {"kind": "body"}
        return done({"op": "translate", "target": {**tt, "kind": "section_body"} if tt.get("kind") == "section" else tt, "language": lang}, focus_=tt)
    if re.search(r"\b(?:fix|correct|check)\b.*\b(?:grammar|spelling|typos?|mistakes|errors|punctuation)\b|\bproof-?read\b|\bspell ?check\b", c):
        tt = t or {"kind": "body"}
        return done(
            {
                "op": "rewrite",
                "target": {**tt, "kind": "section_body"} if tt.get("kind") == "section" else tt,
                "instruction": "correct grammar, spelling and punctuation only; change nothing else",
                "keep_count": True,
            },
            focus_=tt,
        )
    how = None
    mm = re.search(
        r"\b(?:make|rewrite|write)\b.*?\b(?:it|this|that|them)?\s*(?:a (?:lot|bit|little) )?(shorter|longer|more (?:\w+)|less (?:\w+)|simpler|clearer|"
        r"concise|formal|informal|friendlier|professional|persuasive|academic|engaging|polite|stronger)\b",
        c,
    )
    if mm:
        how = mm.group(1)
    elif re.search(r"\b(?:shorten|condense|cut down|trim|summari[sz]e (?:it|this|that|the section)? ?in place)\b", c):
        how = "shorter"
    elif re.search(r"\b(?:expand|elaborate|lengthen|add more detail|flesh out)\b", c):
        how = "longer"
    elif re.search(r"\b(?:rewrite|rephrase|reword|paraphrase|improve|polish|simplify)\b", c):
        how = re.search(r"\b(rewrite|rephrase|reword|paraphrase|improve|polish|simplify)\b", c).group(1)
    if how and (t or focus or re.search(r"\b(?:document|text|everything|whole)\b", c)):
        tt = t or focus or {"kind": "body"}
        if tt.get("kind") == "section":
            tt = {**tt, "kind": "section_body"}
        words = re.search(r"\b(?:to|in|under|about)\s+(\d{2,4})\s+words\b", c)
        bullets = re.search(r"\b(?:as|into|in)\s+(\d+\s+)?bullets?(?: points)?\b", c)
        instruction = {
            "shorter": "make it about 40% shorter; keep the key points",
            "longer": "make it about 50% longer with concrete detail",
            "simpler": "simpler words and shorter sentences",
            "concise": "more concise",
            "rephrase": "rephrase in fresh words",
            "reword": "rephrase in fresh words",
            "paraphrase": "paraphrase in fresh words, same meaning",
            "rewrite": "rewrite it better",
            "improve": "improve clarity and flow",
            "polish": "polish the wording",
            "simplify": "simpler words and shorter sentences",
        }.get(how, f"make it {how}")
        if words:
            instruction += f"; about {words.group(1)} words in total"
        if bullets:
            instruction += f"; as {bullets.group(1) or '3-6 '}short bullet points, one per paragraph"
        keep = not (how in ("shorter", "longer", "concise") or words or bullets or "short" in how or "long" in how)
        ops = [{"op": "rewrite", "target": tt, "instruction": instruction, "keep_count": keep}]
        return done(*ops, focus_=tt)
    mm = re.search(r"\b(?:add|write|insert|include|create|give me)\b.*?\b(executive summary|abstract|summary|key (?:takeaways|points)|tl;?dr)\b", c)
    if (
        mm
        and t
        and t.get("kind") == "section"
        and DM._norm(t.get("name")).startswith(DM._norm(mm.group(1))[:7])
        and not re.search(r"\bnew\b|\banother\b|\bsecond\b", c)
    ):
        out["ask"] = f"There is already a '{t.get('name')}' section. Should I rewrite it, or add another one?"
        return out
    if mm and not t or (mm and t and t.get("kind") in ("all", None)):
        kind = mm.group(1).replace("tl;dr", "summary").replace("tldr", "summary")
        where = "end" if re.search(r"\b(?:at the end|end|bottom|last)\b", c) or "takeaway" in kind or "points" in kind else "start"
        return done({"op": "summarize", "target": {"kind": "all"}, "kind": kind, "where": where})
    # ---- insert new content
    if re.search(r"\b(?:add|write|insert|include|create|put)\b", c) and not re.search(r"\b(?:page numbers?|header|footer|cover|contents|chart)\b", c):
        mm = re.search(
            r"\b(?:a |an |the )?(?:new )?(?:section|chapter|part|heading)\s+(?:on|about|called|titled|named|for)\s+['\"]?(.+?)['\"]?(?=\s+(?:after|before|at the|to the end|at the end)\b|$)",
            c,
        )
        sec = mm.group(1).strip(" .") if mm else None
        if not sec:
            mm = re.search(
                r"\b(?:a |an )?(conclusion|introduction|background|methodology|methods|results|discussion|recommendations|limitations|"
                r"future work|references|bibliography|acknowledg\w*|objectives|scope|risks|timeline|budget|faqs?|glossary|appendix|"
                r"literature review|problem statement|executive summary)\b(?:\s+section)?",
                c,
            )
            sec = mm.group(1) if mm else None
            if (
                sec
                and t
                and t.get("kind") == "section"
                and DM._norm(t.get("name")).startswith(DM._norm(sec)[:7])
                and not re.search(r"\bnew\b|\banother\b", c)
            ):
                out["ask"] = f"There is already a '{t.get('name')}' section. Should I rewrite it, make it longer, or add another one?"
                return out
        anchor_kw = re.search(r"\b(after|before|below|above|under)\s+(?:the\s+)?(.+?)$", c)
        anchor, where = None, None
        if anchor_kw:
            at = target_in(anchor_kw.group(2), m, focus)
            if at:
                anchor, where = at, "after" if anchor_kw.group(1) in ("after", "below", "under") else "before"
        if sec:
            mraw = re.search(re.escape(sec.strip()), str(raw), re.I)  # the client's own spelling ("IMF", not "Imf")
            title = mraw.group(0) if mraw and not mraw.group(0).islower() else sec.strip()
            if title.islower():
                title = " ".join(
                    w if w in ("of", "and", "the", "in", "on", "for", "to", "a", "an") and i else w.capitalize() for i, w in enumerate(title.split())
                )
            if title.lower() in ("references", "bibliography"):
                about = "a references list of real, well-known sources on the document's subject (no invented titles or authors)"
            else:
                about = f"a '{title}' section for this document"
            if not where:
                where = "start" if title.lower() in ("introduction", "background", "abstract", "objectives", "problem statement") else "end"
            words = re.search(r"\b(\d{2,4})\s+words\b", c)
            return done(
                {
                    "op": "insert",
                    "heading": title,
                    "about": about,
                    "where": where,
                    **({"anchor": anchor} if anchor else {}),
                    "words": int(words.group(1)) if words else 200,
                },
                focus_={"kind": "section", "name": title},
            )
        mm = re.search(
            r"\b(?:a |an |one |another )?(?:short |new |closing |opening |brief )?paragraph\b(?:\s+(?:about|on|explaining|describing|that)\s+(.+?))?(?=\s+(?:to|in|at|after|before)\b|$)",
            c,
        )
        if mm and (mm.group(1) or q):
            tt = t if t and t.get("kind") in ("section", "section_body", "paragraph") else None
            op = {"op": "insert", "where": where or ("after" if tt else "end"), **({"anchor": anchor or tt} if (anchor or tt) else {})}
            if q:
                op["text"] = q[0]
            else:
                op["about"] = f"one paragraph about {mm.group(1)}"
                op["words"] = 110
            return done(op)
        if q and anchor:
            return done({"op": "insert", "text": q[0], "where": where, "anchor": anchor})
        mm = re.search(r"\b(?:a |an )?table\s+(?:of|showing|with|listing|comparing)\s+(.+?)(?=\s+(?:to|in|at|after|before)\b|$)", c)
        if mm:
            return done(
                {
                    "op": "insert",
                    "about": f"a table of {mm.group(1)} with a short introducing sentence",
                    "kinds": ["paragraph", "table"],
                    "where": where or ("after" if t and t.get("kind") == "section" else "end"),
                    **({"anchor": anchor or t} if (anchor or (t and t.get("kind") == "section")) else {}),
                    "words": 120,
                }
            )
    # ---- move, delete
    mm = re.search(
        r"\bmove\b\s+(.+?)\s+(?:to\s+)?(before|after|above|below|to the end|to the start|to the beginning|to the top|to the bottom)\s*(.*)$", c
    )
    if mm:
        what = target_in(mm.group(1), m, focus)
        if what:
            pos = mm.group(2)
            if pos.startswith("to the"):
                end = pos in ("to the end", "to the bottom")
                [s for s in m["sections"] if s["level"] == 1] or m["sections"]
                anchor = {"kind": "section", "which": "last" if end else "first"}
                return done({"op": "move", "target": what, "to": {"target": anchor, "where": "after" if end else "before"}}, focus_=what)
            other = target_in(mm.group(3), m, focus)
            if other:
                return done(
                    {"op": "move", "target": what, "to": {"target": other, "where": "after" if pos in ("after", "below") else "before"}}, focus_=what
                )
    mm = re.search(r"\bswap\b\s+(.+?)\s+(?:and|with)\s+(.+)$", c)
    if mm:
        a, b = target_in(mm.group(1), m, focus), target_in(mm.group(2), m, focus)
        if a and b and a.get("kind") == b.get("kind") == "section":
            return done(
                {"op": "move", "target": a, "to": {"target": b, "where": "after"}},
                {"op": "move", "target": b, "to": {"target": a, "where": "before"}},
            )
    if remove and t and t.get("kind") in ("section", "paragraph", "table", "list", "paragraphs", "title"):
        return done({"op": "delete", "target": t}, focus_=None)
    if remove and q:
        return done({"op": "delete", "target": {"kind": "paragraphs", "contains": q[0]}})
    # ---- replace
    mm = re.search(
        r"\b(?:replace|change|rename|swap|switch)\s+(.+?)\s+(?:with|to|into|by|as|for)\s+(.+?)(?:\s+(?:everywhere|throughout|in the whole document|all over))?$",
        raw,
        re.I,
    )
    if mm:
        a, b = (q[0], q[1]) if len(q) >= 2 else (mm.group(1).strip(" '\"."), mm.group(2).strip(" '\"."))
        body_text = " ".join(it["text"] for it in m["items"]).lower()
        styleish = re.search(
            r"\b(?:font|size|colou?r|heading|title|margins?|spacing|alignment|theme|style|orientation|page|table|column|row|layout)\b", a.lower()
        )
        if a and b and (len(q) >= 2 or (a.lower() in body_text and not styleish)):
            return done({"op": "replace", "find": a, "with": b, "case": False, "whole_word": True})
    # ---- emphasis on words
    if re.search(r"\bkey (?:terms|words|points|phrases)\b|\bimportant (?:terms|words|points)\b", c) and re.search(
        r"\bbold|italic|highlight|underline|emphasi[sz]e\b", c
    ):
        s = (
            {"bold": True}
            if re.search(r"\bbold\b|emphasi", c)
            else {"italic": True}
            if re.search(r"\bitalic", c)
            else {"highlight": (COLOUR_RX.search(c).group(1) if COLOUR_RX.search(c) else "yellow")}
            if re.search(r"\bhighlight", c)
            else {"underline": True}
        )
        return done({"op": "emphasis", "auto": 8, "set": s, "target": t or {"kind": "body"}})
    if q and re.search(r"\b(?:bold|italic\w*|underline|highlight|colou?r|red|blue|green)\b", c):
        s = style_set(c)
        s = {k: v for k, v in s.items() if k in ("bold", "italic", "underline", "color")}
        if re.search(r"\bhighlight", c):
            col = COLOUR_RX.search(c.replace("highlight", ""))
            s["highlight"] = col.group(1) if col else "yellow"
        if s:
            return done({"op": "emphasis", "find": q[0], "set": s, "target": t or {"kind": "all"}})
    # ---- style (fonts, colours, sizes, emphasis, alignment, spacing, case)
    s = style_set(c)
    if s:
        tt = t
        if tt is None:
            if set(s) <= {"line_spacing", "align", "first_line_indent", "space_after"} or (
                set(s) <= {"font", "size", "line_spacing", "align"} and "font" in s and not carry
            ):
                tt = {"kind": "body" if set(s) & {"line_spacing", "align", "first_line_indent", "space_after"} and "font" not in s else "all"}
            elif focus:
                tt = focus
            elif set(s) <= {"color"}:
                tt = {"kind": "headings"}
            else:
                tt = {"kind": "all"}
        if (
            tt.get("kind") == "section"
            and not (set(s) - {"color", "font", "size", "bold", "italic", "underline", "case"})
            and re.search(r"\b(?:heading|title)\b", c)
        ):
            tt = {"kind": "items", "k": [DM.find(m, tt)[0]]} if DM.find(m, tt) else tt
        return done({"op": "style", "target": tt, "set": s}, focus_=tt)
    return out
