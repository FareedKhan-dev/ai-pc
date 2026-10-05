"""What a person asks for, read by rules into a design or into changes to the one on screen (the cheap model reads
what the rules cannot into the same shapes).

  parse(clause, ctx) -> {"ops": [...], "ask": None | "question back"}
ops: {"op": "new", "kind", "fields", "style", "palette", "image", "logo", "qr"}   a new design
     {"op": "set", "fields": {...}} / {"op": "drop", "fields": [...]}           change or remove details
     {"op": "look", "style" | "palette" | "gradient" | "kind" | "paper"}         restyle, recolour, resize
     {"op": "size", "role": "name", "by": 1.2}                                 a piece bigger or smaller
     {"op": "image" | "logo", "path"} / {"op": "qr", "data"}                   pictures and a QR code
     {"op": "batch", "names": [...]} / {"op": "batch", "file": "names.xlsx"}    certificates for many people
     {"op": "export", "fmt": "pdf" | "png" | "both", "for": "print" | "whatsapp" | ...}
ctx: {"kind": the design on screen or None, "files": {name: path}}
"""

import re

from ai_pc.design.kinds import COLOR_WORDS, GRADIENTS, KINDS

PHONE = r"(?:\+92|0092|0)\s?3\d{2}[\s-]?\d{7}\b|(?:\+92|0)\s?\d{2,3}[\s-]?\d{6,8}\b|\+\d{1,3}[\s-]?\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}\b"
EMAIL = r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"
WEB = r"\b(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|pk|net|org|io|co|edu|info|store|shop|biz|ai|app|dev)(?:/[^\s,]*)?\b"
QUOTE = r"[\"“”'‘’]"
IMG = r"[\w\-.()]+\.(?:jpe?g|png|webp|bmp)"
KIND_WORDS = [
    (r"\b(?:visiting|business|contact|name) cards?\b", "card"),
    (r"\byoutube thumbnail\b|\bthumbnail\b", "thumbnail"),
    (r"\b(?:insta(?:gram)?|whatsapp|facebook|fb) (?:story|status)\b|\bstory\b|\bstatus\b|\breel cover\b", "story"),
    (r"\bportrait post\b|\b4:5\b", "portrait"),
    (r"\b(?:insta(?:gram)?|facebook|fb|social(?: media)?|linkedin) post\b|\bpost\b|\bad\b|\badvert", "post"),
    (r"\bflyers?\b|\bleaflets?\b|\bpamphlets?\b|\bhandbills?\b|\bbrochure\b", "flyer"),
    (r"\bposters?\b|\bbanners?\b|\bstandee\b", "poster"),
    (r"\bcertificates?\b", "certificate"),
    (r"\binvitations?\b|\binvites?\b|\bwedding cards?\b|\binvitation cards?\b", "invitation"),
]
STYLES = {s for k in KINDS.values() for s in k["styles"]}
KEYS = {
    "name": "name",
    "title": "title",
    "designation": "title",
    "position": "title",
    "job": "title",
    "company": "company",
    "business": "company",
    "shop": "company",
    "brand": "brand",
    "phone": "phone",
    "mobile": "phone",
    "cell": "phone",
    "whatsapp": "phone",
    "email": "email",
    "e-mail": "email",
    "website": "web",
    "web": "web",
    "site": "web",
    "address": "address",
    "location": "address",
    "tagline": "tagline",
    "slogan": "tagline",
    "headline": "headline",
    "heading": "headline",
    "subheading": "sub",
    "subtitle": "sub",
    "offer": "offer",
    "discount": "offer",
    "dates": "dates",
    "button": "cta",
    "cta": "cta",
    "recipient": "recipient",
    "awarded to": "recipient",
    "reason": "reason",
    "date": "date",
    "time": "time",
    "event": "event",
    "host": "host",
    "venue": "address",
    "rsvp": "rsvp",
    "note": "note",
    "organisation": "org",
    "organization": "org",
    "school": "org",
    "institute": "org",
    "description": "body",
    "details": "body",
}
CTAS = (
    r"\b(shop now|order now|buy now|call now|book now|visit us(?: today)?|register now|sign up(?: now)?|learn more|join us|get yours|apply now|contact us|"
    r"subscribe|watch now|dm (?:us|now)|whatsapp us)\b"
)
MONTHS = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)


def kind_of(c):
    for rx, k in KIND_WORDS:
        if re.search(rx, c):
            return k
    return None


def quoted(raw):
    return [m.group(1).strip() for m in re.finditer(QUOTE + r"([^\"“”'‘’]{2,}?)" + QUOTE, raw)]


def contacts(raw):
    f = {}
    m = re.search(EMAIL, raw)
    if m:
        f["email"] = m.group(0)
    rest = re.sub(EMAIL, " ", raw)
    m = re.search(WEB, rest, re.I)
    if m:
        f["web"] = re.sub(r"^https?://", "", m.group(0)).rstrip("/.")
    phones = re.findall(PHONE, raw)
    if phones:
        f["phone"] = phones[0].strip()
        if len(phones) > 1:
            f["phone2"] = phones[1].strip()
    return f


def keyvals(raw):
    """'name: Ahmed Khan, phone: 0300-1234567' style details."""
    f = {}
    for m in re.finditer(
        r"(?:^|[,;\n]|\band\b)\s*(" + "|".join(sorted(map(re.escape, KEYS), key=len, reverse=True)) + r")\s*(?:is|=|:)\s*([^,;\n]+)", raw, re.I
    ):
        k = KEYS[m.group(1).lower()]
        v = m.group(2).strip().strip("'\"“”")
        if v:
            f[k] = v
    return f


def files_in(raw, ctx, ext=IMG):
    out = []
    for m in re.finditer(
        r"([A-Za-z]:\\[^\"'<>|]+?\.(?:jpe?g|png|webp|bmp|xlsx|csv|txt))\b|[\"'“‘]([^\"'”’]+\.(?:jpe?g|png|webp|bmp|xlsx|csv|txt))[\"'”’]|("
        + ext
        + r")\b",
        raw,
        re.I,
    ):
        name = m.group(1) or m.group(2) or m.group(3)
        out.append((ctx.get("files") or {}).get(name.lower().strip(), name.strip()))
    return out


def look_words(c):
    out = {}
    for s in sorted(STYLES, key=len, reverse=True):
        if (
            re.search(rf"\b{s}\b(?: style| look| layout| design)?", c)
            and s not in ("photo", "face", "center", "split", "headline", "sale", "event")
            or re.search(rf"\b{s} (?:style|look|layout)\b", c)
        ):
            out["style"] = s
            break
    for g in GRADIENTS:
        if re.search(rf"\b{g}\b", c) and re.search(r"\bgradient\b|\b" + g + r" (?:colou?rs?|theme|look)\b", c):
            out["gradient"] = g
    for word in sorted(COLOR_WORDS, key=len, reverse=True):
        if re.search(rf"\b{word}\b", c) and re.search(r"\b(?:colou?rs?|theme|background|in|make it|use|palette|scheme)\b", c):
            out["palette"] = COLOR_WORDS[word]
            break
    m = re.search(r"\b(a3|a4|a5|a6|letter)\b", c)
    if m:
        out["paper"] = m.group(1)
    return out


def offer_dates_cta(c, raw):
    f = {}
    m = re.search(r"\b(?:up to |flat )?(\d{1,2})\s*%\s*(?:off|discount)\b", c)
    if m:
        f["offer"] = f"{m.group(1)}% OFF"
    elif re.search(r"\bbuy 1 get 1\b|\bbuy one get one\b|\bbogo\b", c):
        f["offer"] = "BUY 1 GET 1"
    m = re.search(r"\b(?:from )?(\d{1,2})(?:st|nd|rd|th)?\s*(?:-|to|till|until)\s*(\d{1,2})(?:st|nd|rd|th)?\s+(" + MONTHS + r")\b", c) or re.search(
        r"\b(?:on|till|until|from) (\d{1,2})(?:st|nd|rd|th)? (" + MONTHS + r")\b", c
    )
    if m:
        g = m.groups()
        f["dates"] = (
            f"{g[0]} - {g[1]} {g[2].title()}"
            if len(g) == 3
            else f"{'Till ' if re.search(r'\\b(?:till|until)\\b', m.group(0)) else ''}{g[0]} {g[1].title()}"
        )
    m = re.search(CTAS, c)
    if m:
        f["cta"] = m.group(1).capitalize() if not m.group(1).startswith("dm") else m.group(1).upper()
    return f


def parse(clause, ctx=None):
    ctx = ctx or {}
    raw = clause.strip()
    c = " ".join(raw.lower().replace("’", "'").split())
    out = {"ops": [], "ask": None}

    def done(*ops):
        out["ops"] = [o for o in ops if o]
        return out

    cur = ctx.get("kind")
    # ---------------------------------------------------------------- saving
    m = re.search(
        r"\b(?:export|save|download|give me|send|print)\b.*?\b(pdf|png|jpe?g|image|picture|both|print(?:able)?|files?)\b|\bfor (?:printing|the print(?:er| shop)|whatsapp|instagram)\b|^\s*(?:pdf|png)\s*$",
        c,
    )
    if m and not kind_of(c):
        fmt = (m.group(1) or "").replace("jpeg", "jpg") if m.lastindex else ""
        fmt = {"image": "png", "picture": "png", "print": "pdf", "printable": "pdf", "file": "both", "files": "both", "jpg": "png"}.get(fmt, fmt)
        if not fmt:
            fmt = "pdf" if re.search(r"\bprint", c) else "png"
        op = {"op": "export", "fmt": fmt}
        if re.search(r"\bprint", c):
            op["for"] = "print"
        elif "whatsapp" in c:
            op["for"] = "whatsapp"
        if re.search(r"\bcrop marks?\b", c):
            op["marks"] = True
        return done(op)
    # ---------------------------------------------------------------- certificates for many people
    if re.search(r"\bcertificates?\b", c) and re.search(
        r"\bfor (?:all |each of |every )?(?:the |these |those )?(?:names|people|students|participants|winners|attendees)\b|\bnames?\s*:", c
    ):
        f = files_in(raw, ctx, r"[\w\-.()]+\.(?:xlsx|csv|txt)")
        if f:
            return done(
                {"op": "batch", "file": f[0]},
                *([{"op": "new", "kind": "certificate", "fields": _cert_fields(raw, c)}] if cur != "certificate" else []),
            )
        m = re.search(r"(?:names?\s*(?:are|is|:)|for these names?:?|for)\s*(.+)$", raw, re.I)
        names = (
            [n.strip(" .") for n in re.split(r",|\band\b|\n|;", m.group(1)) if len(n.strip(" .").split()) in (1, 2, 3, 4) and n.strip()[:1].isupper()]
            if m
            else []
        )
        if names and len(names) >= 2:
            return done(
                *([{"op": "new", "kind": "certificate", "fields": _cert_fields(raw, c)}] if cur != "certificate" else []),
                {"op": "batch", "names": names},
            )
        out["ask"] = "Whose names? List them ('for Ali Raza, Sara Khan and Hamza Ali') or name a file ('names.xlsx', one name a row)."
        return out
    # ---------------------------------------------------------------- a new design
    k = kind_of(c)
    newish = (
        re.search(r"\b(?:make|create|design|draw|need|want|give me|generate|build|prepare)\b", c)
        or not cur
        or (k and k != cur)
        or re.match(r"^\s*(?:an?|another|one more|new)\b", c)
    )
    if (
        k
        and newish
        and not re.search(r"\bmake (?:it|this) (?:an? )?(?:story|post|thumbnail|portrait|flyer|poster|card|a4|a5|a3)\b|\bturn (?:it|this) into\b", c)
    ):
        fields = {}
        fields.update(contacts(raw))
        fields.update(keyvals(raw))
        fields.update({kk: vv for kk, vv in offer_dates_cta(c, raw).items() if k in ("post", "portrait", "story", "flyer", "poster")})
        q = quoted(raw)
        if k == "card":
            fields.update(_card_fields(raw, fields))
        elif k in ("post", "portrait", "story", "flyer", "poster", "thumbnail"):
            if q:
                fields.setdefault("headline", q[0])
                if len(q) > 1:
                    fields.setdefault("sub", q[1])
            m = re.search(r"\b(?:for|by) ([A-Z][\w&.'-]*(?: [A-Z][\w&.'-]*){0,4})", raw)
            if m and k != "thumbnail":
                fields.setdefault("brand", m.group(1).strip())
            if k == "thumbnail" and not fields.get("headline"):
                m = re.search(r"\b(?:saying|that says|titled|called|about)\s+(.+?)(?:,|\.|$| with | using )", raw, re.I)
                if m:
                    fields["headline"] = m.group(1).strip()
            items = re.findall(r"([A-Za-z][\w .'-]{2,40}?)\s*(?:-|:|=|at|for)\s*(Rs\.?\s?[\d,]+|PKR\s?[\d,]+|\$\s?[\d,.]+)", raw)
            if items:
                fields["items"] = [{"name": a.strip(), "price": p.replace("Rs.", "Rs").strip()} for a, p in items]
        elif k == "certificate":
            fields.update(_cert_fields(raw, c))
        elif k == "invitation":
            fields.update(_invite_fields(raw, c))
        op = {"op": "new", "kind": k, "fields": fields}
        op.update(look_words(c))
        imgs = files_in(raw, ctx)
        logo = re.search(r"\blogo\b", c)
        for path in imgs:
            if logo and re.search(r"logo", path, re.I) or (logo and len(imgs) == 1 and k in ("card", "certificate")):
                op["logo"] = path
            else:
                op.setdefault("image", path)
        if op.get("image") and k in ("post", "portrait", "story") and "style" not in op:
            op["style"] = "photo"
        if re.search(r"\bqr\b", c):
            op["qr"] = True
        return done(op)
    if k and not cur:
        return done({"op": "new", "kind": k, "fields": {}})
    # ---------------------------------------------------------------- changes to the design on screen
    ops = []
    m = re.search(
        r"\b(?:make|turn|change|convert) (?:it|this)(?: into| to)? (?:an? )?(story|instagram story|whatsapp status|square post|post|portrait post|thumbnail|flyer|poster)\b",
        c,
    )
    if m:
        ops.append({"op": "look", "kind": kind_of(m.group(1)) or m.group(1)})
    lk = look_words(c)
    if re.search(r"\b(?:another|different|other|next) (?:style|look|layout|design)\b|\btry (?:something|another)\b", c):
        lk["style"] = "next"
    if re.search(r"\bdark(?:er)? background\b|\bdark mode\b|\bmake it dark(?:er)?\b", c):
        lk["palette"] = "charcoal"
    elif re.search(r"\b(?:white|light(?:er)?) background\b|\bmake it light(?:er)?\b", c):
        lk["palette"] = "white"
    if lk:
        ops.append(dict({"op": "look"}, **lk))
    m = re.search(r"\b(?:make|set) (?:the )?([a-z ]+?) (bigger|larger|smaller|tinier|much bigger|much smaller|a bit bigger|a bit smaller)\b", c)
    if m:
        role = _role(m.group(1))
        if role:
            big = "big" in m.group(2) or "larg" in m.group(2)
            amt = 1.4 if "much" in m.group(2) else 1.12 if "bit" in m.group(2) else 1.25
            ops.append({"op": "size", "role": role, "by": amt if big else round(1 / amt, 3)})
    sets = {}
    sets.update(keyvals(raw))
    m = re.search(
        r"\b(?:change|update|replace|set|make|fix) (?:the |my |our )?(phone(?: number)?|mobile|number|email|website|web address|address|name|title|"
        r"designation|company|brand|headline|heading|tagline|slogan|offer|discount|dates?|button|cta|recipient|reason|venue|time|event|host)\s*"
        r"(?:to|into|as|=|:)\s*(.+)$",
        raw,
        re.I,
    )
    if m:
        key = {
            "phone number": "phone",
            "mobile": "phone",
            "number": "phone",
            "website": "web",
            "web address": "web",
            "designation": "title",
            "heading": "headline",
            "slogan": "tagline",
            "discount": "offer",
            "button": "cta",
            "venue": "address",
            "date": "dates" if cur in ("post", "story", "portrait", "flyer", "poster") else "date",
        }.get(m.group(1).lower(), m.group(1).lower())
        if key == "dates" and cur == "invitation":
            key = "date"
        sets[key] = m.group(2).strip().strip("'\"“”")
    q = quoted(raw)
    if q and re.search(r"\b(?:say|says|text|write|headline|title|heading|change|to)\b", c) and not sets:
        sets[
            "headline"
            if cur not in ("card", "certificate", "invitation")
            else ("name" if cur == "card" else "recipient" if cur == "certificate" else "event")
        ] = q[0]
    if re.search(r"\badd\b", c) and not re.search(r"\bqr\b", c):  # 'add a QR code for x.pk' is the code, not the address in words
        sets.update({kk: vv for kk, vv in contacts(raw).items() if kk not in sets})
        sets.update(offer_dates_cta(c, raw))
        m = re.search(
            r"\badd (?:a |the |our )?(tagline|slogan|subheading|subtitle|note|button)\s*[:\-]?\s*" + QUOTE + r"?(.+?)" + QUOTE + r"?\s*$", raw, re.I
        )
        if m:
            sets[KEYS.get(m.group(1).lower(), m.group(1).lower())] = m.group(2).strip()
    if sets:
        ops.append({"op": "set", "fields": sets})
    m = re.search(
        r"\b(?:remove|delete|drop|take (?:out|off)|hide|no)\b(?: the| my| our)? (phone(?: number)?|email|website|web address|address|title|designation|tagline|"
        r"slogan|offer|discount|dates?|button|cta|qr(?: code)?|logo|photo|picture|image|subheading|subtitle|note|rsvp|second signature|signer 2)\b",
        c,
    )
    if m:
        what = m.group(1)
        if what.startswith("qr"):
            ops.append({"op": "qr", "data": None})
        elif what in ("logo",):
            ops.append({"op": "logo", "path": None})
        elif what in ("photo", "picture", "image"):
            ops.append({"op": "image", "path": None})
        else:
            key = {
                "phone number": "phone",
                "web address": "web",
                "website": "web",
                "designation": "title",
                "slogan": "tagline",
                "discount": "offer",
                "button": "cta",
                "subheading": "sub",
                "subtitle": "sub",
                "date": "dates",
                "second signature": "signer2",
                "signer 2": "signer2",
            }.get(what, what)
            ops.append({"op": "drop", "fields": [key]})
    if re.search(r"\b(?:add|put|include|with) (?:a |an |the )?qr(?: code)?\b", c) and not re.search(r"\b(?:remove|delete|no)\b", c):
        m = re.search(WEB, raw, re.I)
        ops.append({"op": "qr", "data": re.sub(r"^https?://", "", m.group(0)) if m else True})
    imgs = files_in(raw, ctx)
    if imgs and re.search(r"\b(?:use|add|put|with|replace|change)\b", c):
        ops.append({"op": "logo" if re.search(r"\blogo\b", c) else "image", "path": imgs[0]})
    return done(*ops)


def _role(words):
    w = words.strip()
    for k, v in (
        ("name", "name"),
        ("title", "title"),
        ("designation", "title"),
        ("company", "company"),
        ("headline", "headline"),
        ("heading", "headline"),
        ("title text", "headline"),
        ("offer", "offer"),
        ("discount", "offer"),
        ("badge", "offer"),
        ("logo", "logo"),
        ("qr", "qr"),
        ("phone", "phone"),
        ("contact", "phone"),
        ("text", "headline"),
        ("words", "headline"),
        ("recipient", "recipient"),
        ("tagline", "tagline"),
        ("button", "cta"),
        ("price", "price"),
        ("prices", "price"),
        ("date", "dates"),
        ("subheading", "sub"),
        ("event", "event"),
    ):
        if re.search(rf"\b{k}\b", w):
            return v
    return None


def _card_fields(raw, have):
    """'for Ahmed Khan, Sales Manager at Khan Electronics' -> name, title, company; the address after 'address' or a known city."""
    f = {}
    m = re.search(
        r"\bfor ([A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+){0,3})\s*(?:,|\(|-|who is|,? the)?\s*([A-Za-z][\w &/-]{2,40}?)?\s+(?:at|of|in|from|,)\s+"
        r"([A-Z][\w&.'-]*(?: [A-Z&][\w&.'-]*){0,5})",
        raw,
    )
    if m:
        f["name"] = m.group(1).strip()
        if m.group(2):
            f["title"] = m.group(2).strip().title() if m.group(2).islower() else m.group(2).strip()
        f["company"] = m.group(3).strip()
    else:
        m = re.search(r"\bfor ([A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+){0,3})", raw)
        if m:
            f["name"] = m.group(1).strip()
    m = re.search(
        r"\b(?:address|located at|office at|shop at)\s*(?:is|:)?\s*([^;\n]+?)(?:$|;|\.(?:\s|$)|, (?:phone|email|web|website|mobile|cell)\b)",
        raw,
        re.I,
    )
    if m and "address" not in have:
        f["address"] = m.group(1).strip().rstrip(",")
    else:
        m = re.search(
            r"((?:shop|office|house|plot|flat|suite|floor)\s*(?:no\.?|#)?\s*\w+,?[^,;\n]*?,\s*[^,;\n]*?(?:lahore|karachi|islamabad|rawalpindi|faisalabad|multan|"
            r"peshawar|quetta|sialkot|gujranwala|hyderabad|abbottabad|bahawalpur|sargodha)\b)",
            raw,
            re.I,
        )
        if m and "address" not in have:
            f["address"] = m.group(1).strip()
    return f


def _cert_fields(raw, c):
    f = {}
    m = re.search(
        r"\bcertificate of (achievement|appreciation|participation|completion|excellence|merit|recognition|attendance|honou?r|training)\b", c
    )
    if m:
        f["title"] = f"Certificate of {m.group(1).title()}"
    m = re.search(r"\b(?:for|to|awarded to|presented to)\s+([A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+){0,3})\s*(?:for|,|$|on|from)", raw)
    if m:
        f["recipient"] = m.group(1).strip()
    m = re.search(
        r"\b(?:for|on)\s+((?:completing|winning|participating|taking part|attending|outstanding|excellent|securing|achieving|his|her|their)\b[^;]*?)"
        r"(?=,?\s*(?:signed by|dated|on \d)|[.;](?:\s|$)|$)",
        raw,
        re.I,
    )
    if m:
        f["reason"] = "for " + m.group(1).strip().rstrip(",")
    m = re.search(r"\b(?:from|by|issued by|at)\s+(?:the\s+)?([A-Z][\w&.'-]*(?: [A-Z&][\w&.'-]*){0,5})", raw)
    if m:
        f["org"] = m.group(1).strip()
    m = re.search(r"\bsigned by ((?:(?:mr|mrs|ms|dr|prof|engr|sir)\.?\s+)?[^;]+?)(?=$|;|\.\s|\.$)", raw, re.I)
    if m:
        parts = [p.strip() for p in re.split(r"\band\b|;", m.group(1)) if p.strip()]
        for i, p in enumerate(parts[:2], 1):
            f[f"signer{i}"] = p
    m = re.search(r"\b(?:dated?|on)\s+(\d{1,2}(?:st|nd|rd|th)? " + MONTHS + r"(?:,? \d{4})?)", raw, re.I)
    if m:
        f["date"] = m.group(1).strip()
    return f


def _invite_fields(raw, c):
    f = {}
    q = quoted(raw)
    if q:
        f["event"] = q[0]
    else:
        m = re.search(
            r"\bfor (?:my |our |the )?([\w' ]{3,40}?(?:wedding|walima|mehndi|barat|birthday(?: party)?|party|reception|ceremony|opening|launch|dinner|"
            r"gathering|meetup|seminar|workshop|graduation)(?: of [A-Z][\w ]+?)?)\b",
            raw,
            re.I,
        )
        if m:
            f["event"] = m.group(1).strip().title() if m.group(1).islower() else m.group(1).strip()
    m = re.search(
        r"\bon\s+((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s*)?(\d{1,2}(?:st|nd|rd|th)?\s+" + MONTHS + r"(?:,?\s*\d{4})?)",
        raw,
        re.I,
    )
    if m:
        f["date"] = ((m.group(1) or "").strip().title() + " " + m.group(2).strip()).strip()
    m = re.search(r"\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", c)
    if m:
        f["time"] = m.group(1)
    m = re.search(
        r"\b(?:at|venue:?)\s+([A-Z][^,.;]*?(?:hall|hotel|marquee|club|centre|center|restaurant|garden|lawn|banquet|house|school|university|office)[^.;]*)",
        raw,
    )
    if m:
        f["address"] = m.group(1).strip()
    m = re.search(r"\brsvp\s*(?:to|at|:)?\s*(" + PHONE + r"|[^.;]+)", raw, re.I)
    if m:
        f["rsvp"] = m.group(1).strip()
    m = re.search(r"\b(?:hosted by|from|by)\s+((?:mr|mrs|ms|dr)\.?[^,.;]+|the [A-Z][\w ]+ family)", raw, re.I)
    if m:
        f["host"] = m.group(1).strip()
    return f
