"""Requests about 3D read by rules (no model).

  parse(clause, ctx) -> {"ops": [{"op": ..., "args": {...}}], "ask": None | "question back"}
ctx: {"subject": "house" | "text" | "mockup" | "model" | None, "files": {lower name: path}}

Houses: 'a 3D model of a 5 marla house with 3 bedrooms', 'make my house plan 3D', 'show the front', 'the 3D floor plan',
'top view', 'from above', 'make a video going round it', 'the first floor', 'grey walls', 'brick cladding', 'wood
panels', 'no furniture', 'without names', 'high quality', 'make the kitchen bigger' (the plan changes).
Text: 'a 3D intro for Khan Electronics in gold', 'make it silver', 'add the tagline Best prices in town', 'spin it in'.
Mockups: 'a box mockup with box.png', 'put card.png on a business card', 'show site.png on a laptop', 'a mug with logo.png'.
Models: 'show me chair.glb', 'convert it to stl', 'is it ready for 3D printing?', 'how big is it?'.
"""

import re

from ai_pc.convert.convparse import secs

IMG = r"png|jpg|jpeg|webp"
MODEL_EXT = r"glb|gltf|obj|fbx|stl|ply|usd|usdz|usda|usdc|blend|3mf"
VIEWS = [
    (r"\b(?:3d (?:floor )?plan|floor ?plan in 3d|doll ?house|inside|interior|furnished plan|layout in 3d|cut ?away)\b", "plan3d"),
    (r"\b(?:top view|from (?:straight )?above|from the top|bird'?s[- ]eye|plan view|overhead)\b", "top"),
    (r"\b(?:front(?: view| elevation)?|elevation|facade|façade|from the (?:road|street)|outside view|exterior)\b", "front"),
    (r"\b(?:aerial|drone|from up high|corner view|3/4 view|three[- ]quarter)\b", "aerial"),
    (r"\b(?:video|walk ?through|turn ?around|turntable|360|fly ?(?:around|over)|go(?:ing)? (?:a)?round|orbit|animation|animated)\b", "orbit"),
]
COLOURS = {
    "white": "plaster_white",
    "cream": "plaster_cream",
    "beige": "plaster_cream",
    "off ?white": "plaster_cream",
    "grey": "plaster_grey",
    "gray": "plaster_grey",
}
ACCENTS = {"brick": "brick_red", "stone": "stone_grey", "wood(?:en)?": "wood_light", "marble": "marble"}
MATERIALS = [
    "gold",
    "silver",
    "chrome",
    "copper",
    "bronze",
    "glass",
    "neon",
    "plastic",
    "marble",
    "wood",
    "rose gold",
    "black",
    "white",
    "red",
    "blue",
    "green",
    "orange",
    "purple",
    "pink",
]
MOCKS = [
    (r"\bbox(?:es)?\b|\bpackag", "box"),
    (r"\bbusiness cards?\b|\bvisiting cards?\b|\bcards?\b", "card"),
    (r"\blaptop\b|\bmacbook\b|\bcomputer screen\b", "laptop"),
    (r"\b(?:phone|mobile|iphone|android|smartphone|app)\b", "phone"),
    (r"\bmugs?\b|\bcups?\b", "mug"),
    (r"\bposter\b|\bframe(?:d)?\b|\bon (?:a|the) wall\b|\bcanvas\b|\bpainting\b", "poster"),
]


def _kind(words):
    """The product named: the one after 'on (a|the) ...' / 'as a' / 'into a' wins (the picture goes on it), else the last named."""
    found = []
    for rx, k in MOCKS:
        for m in re.finditer(rx, words):
            found.append(
                (
                    m.start(),
                    k,
                    bool(re.search(r"\b(?:on|onto|as|into|in)\s+(?:a|an|the|my|some|his|her|their)?\s*(?:\w+\s+){0,2}$", words[: m.start()])),
                )
            )
    if not found:
        return None
    after_on = [f for f in found if f[2]]
    return (max(after_on) if after_on else max(found))[1]


def _files(raw, ctx, ext):
    out = []
    for m in re.finditer(rf"([A-Za-z]:\\[^\"'<>|]+?\.(?:{ext})|\"[^\"]+?\.(?:{ext})\"|'[^']+?\.(?:{ext})'|[\w\-.()]+\.(?:{ext}))\b", raw, re.I):
        name = m.group(1).strip("\"'")
        out.append((ctx.get("files") or {}).get(name.lower(), (ctx.get("files") or {}).get(name.split("\\")[-1].lower(), name)))
    return out


def parse(clause, ctx=None):
    ctx = ctx or {}
    raw = clause.strip()
    c = " ".join(raw.lower().replace("’", "'").split())
    words = re.sub(r"[\w\-.()\\:]+\.(?:" + IMG + "|" + MODEL_EXT + r")\b", " ", c)  # the words without file names ('card.png' is not a card)
    subj = ctx.get("subject")
    ops = []

    def op(_op, **a):
        ops.append({"op": _op, "args": a})

    def done(ask=None):
        return {"ops": ops, "ask": ask}

    # ---------------------------------------------------------------- questions, saving
    if re.search(
        r"^\s*(?:how (?:big|large|tall|heavy|many)|what(?:'s| is) (?:its|the) (?:size|height|dimensions)|dimensions\b|"
        r"(?:is it|is this|can (?:it|this|i)) (?:be )?(?:ready|ok|fine|printable|print it|go) (?:for|to) (?:3d )?print)",
        c,
    ):
        op("ask", what="print" if "print" in c else "info")
        return done()
    if re.search(r"^\s*(?:what (?:did you|have you) (?:make|made|do)|show (?:me )?the files|where (?:is|are) (?:it|they|the files))\b", c):
        op("ask", what="where")
        return done()
    m = re.search(
        r"\b(?:save|export|download)\b(?: (?:it|them|this|the (?:pictures|images|renders|video|files)))?(?: (?:to|on|in|into) "
        r"(?:my |the )?(desktop|downloads?|documents?|videos?|pictures?|photos?))?",
        c,
    ) or re.search(
        r"\b(?:put|copy|move)\b (?:it|them|this|the (?:pictures|images|renders|video|files)) (?:to|on|in|into) (?:my |the )?"
        r"(desktop|downloads?|documents?|videos?|pictures?|photos?)\b",
        c,
    )
    if m and not re.search(r"\b(?:as|to|into) (?:an? )?\.?(?:" + MODEL_EXT + r")\b", c):
        op("save", where=m.group(1))
        return done()
    # ---------------------------------------------------------------- 3D files
    models = _files(raw, ctx, MODEL_EXT)
    if models and re.search(r"\b(?:show|open|look|render|view|preview|see|load|import|check|what)\b", c) or (models and not subj):
        op("model", file=models[0])
    mconv = re.search(r"\b(?:convert|export|save|turn|give|send|make|want|need)\b.*\b(?:to|as|into|in) (?:an? )?\.?(" + MODEL_EXT + r")\b", c)
    if mconv:
        op("model_export", fmt=mconv.group(1))
    if re.search(r"\b(?:3d )?print(?:ing|able|er|ers)?\b", c) and (subj == "model" or models) and not mconv:
        op("ask", what="print")
    # ---------------------------------------------------------------- houses
    house_word = re.search(r"\b(?:house|home|plan|bungalow|villa|marla|kanal|elevation|floor ?plan|building)\b", c)
    if re.search(
        r"\b(?:my|the|this|that) (?:house )?(?:plan|drawing|design)\b.*\b3d\b|\b3d\b.*\b(?:my|the|this|that) (?:house )?(?:plan|drawing|design)\b", c
    ) and not re.search(r"\b\d+(?:\.\d+)? (?:marla|kanal)\b|\bx\s*\d", c):
        op("house_from_cad")
    elif (
        house_word
        and re.search(r"\b(?:3d|three d|model|render|elevation|view|visual|walkthrough)\b", c)
        and re.search(r"\b(?:\d+(?:\.\d+)?\s*(?:marla|kanal)|\d+\s*(?:x|by)\s*\d+|bed ?rooms?|story|storey|double|single|floors?)\b", c)
    ):
        op("house_new", brief=raw)
    elif (
        subj == "house"
        and re.search(
            r"\b(?:bigger|smaller|larger|wider|longer|shorter|add|remove|another|extra|one more|double|single|story|storey|"
            r"bed ?rooms?|kitchen|lounge|drawing|dining|store|stairs?|porch|bath|marla|kanal|plot)\b",
            c,
        )
        and not re.search(r"\b(?:furniture|names?|labels?|walls?|colou?r|cladding|panels?|front|video|view|quality|camera|light)\b", c)
    ):
        op("cad", text=raw)
    for rx, v in VIEWS:
        if re.search(rx, c) and (subj == "house" or house_word or any(o["op"].startswith("house") for o in ops)):
            op("view", kind=v, only=bool(re.search(r"\bonly\b|\bjust\b", c)))
    if re.search(r"\bfirst floor\b|\bupstairs\b|\bupper floor\b|\bsecond floor\b", c):
        op("storey", which="first")
    elif re.search(r"\bground floor\b|\bdownstairs\b|\blower floor\b", c):
        op("storey", which="ground")
    for word, key in COLOURS.items():
        if re.search(
            rf"\b{word} (?:walls?|paint|plaster|colou?r|house|building|front)\b|\b(?:walls?|paint|house) (?:in |to )?{word}\b|\bmake it {word}\b", c
        ):
            op("colors", wall=key, parapet=key)
    for word, key in ACCENTS.items():
        if re.search(rf"\b{word} (?:cladding|panels?|tiles|front|facade|work|finish|accents?)\b", c):
            op("colors", accent=key)
    if re.search(r"\b(?:black|dark) (?:window )?frames?\b|\bblack windows\b", c):
        op("colors", frame="frame_black")
    elif re.search(r"\bwhite (?:window )?frames?\b|\bwhite windows\b", c):
        op("colors", frame="frame_white")
    elif re.search(r"\b(?:brown|wood(?:en)?) (?:window )?frames?\b", c):
        op("colors", frame="frame_brown")
    for st in ("modern", "warm", "classic"):
        if re.search(rf"\b{st} (?:look|style|design|elevation)\b|\bmake it {st}\b|\bmore {st}\b", c):
            op("style", name=st)
    if re.search(r"\b(?:no|without|remove|hide|take out) (?:the )?furniture\b|\bempty rooms?\b|\bunfurnished\b", c):
        op("furniture", on=False)
    elif re.search(r"\b(?:with|add|show|put in)(?: the| some)? furniture\b|\bfurnished\b", c):
        op("furniture", on=True)
    if re.search(r"\b(?:no|without|remove|hide) (?:the )?(?:room )?(?:names|labels|text|sizes)\b", c):
        op("labels", on=False)
    elif re.search(r"\b(?:with|add|show) (?:the )?(?:room )?(?:names|labels|sizes)\b", c):
        op("labels", on=True)
    if re.search(r"\b(?:high|best|top|better) quality\b|\brealistic\b|\bphoto[- ]?real|\bcycles\b|\bproper render\b", c):
        op("quality", level="high")
    elif re.search(r"\b(?:quick|fast|draft|preview) (?:render|quality|version)?\b", c) and not re.search(r"\bvideo\b", c):
        op("quality", level="normal")
    if re.search(r"\b(?:4k|bigger|larger|high[- ]?res(?:olution)?|print size|big) (?:image|picture|render|pictures|images)?\b", c) and not re.search(
        r"\b(?:room|kitchen|house|plot|text|box)\b", c
    ):
        op("big", on=True)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", c)
    if m and re.search(r"\b(?:video|long|intro|animation|clip|turn)\b", c):
        op("seconds", value=float(m.group(1)))
    # ---------------------------------------------------------------- 3D text and logo intros
    if (
        re.search(r"\b(?:3d |three d )?(?:intro|logo reveal|title|text|logo animation|opener|3d name|3d logo)\b", c)
        and re.search(r"\b(?:3d|intro|reveal|animation|opener|animated)\b", c)
        and not house_word
    ):
        tail = r"(?:\s+(?:in|with|on|using|as|that|which|looking|made of)\b.*)?\s*$"
        mt = (
            re.search(r"[\"“]([^\"”]+)[\"”]", raw)
            or re.search(r"(?<![\w])'([^']+)'(?![\w])", raw)
            or re.search(r"\bfor\s+(.+?)" + tail, raw, re.I)
            or re.search(r"\b(?:saying|that says|text|name)\s*[:\-]?\s*(.+?)\s*$", raw, re.I)
        )
        if mt and mt.group(1).strip():
            op("text_new", text=mt.group(1).strip().strip("\"'"))
    if subj == "text" or any(o["op"] == "text_new" for o in ops):
        mm = re.search(r"\b(rose gold|" + "|".join(MATERIALS) + r")\b", c)
        if mm:
            op("text_style", material=mm.group(1))
        mt = re.search(r"\b(?:tagline|subtitle|slogan|second line|under it|below it)\b\s*[:\-]?\s*[\"']?(.+?)[\"']?\s*$", raw, re.I)
        if mt:
            op("text_style", sub=mt.group(1).strip())
        for word, anim in (
            ("spin", "spin"),
            ("rotate", "spin"),
            ("zoom", "dolly"),
            ("fly", "dolly"),
            ("rise", "rise"),
            ("drop", "drop"),
            ("slide", "rise"),
        ):
            if re.search(rf"\b{word}", c):
                op("text_style", anim=anim)
                break
        mb = re.search(
            r"\b(dark|black|white|studio|blue|navy|red|green|purple|gradient)\b (?:background|backdrop|bg)\b|\bon (?:a )?(dark|black|white|blue|navy|red|green|purple) "
            r"(?:background|backdrop)?\b",
            c,
        )
        if mb:
            op("text_style", background=mb.group(1) or mb.group(2))
        mt = re.search(r"\b(?:change|make) the (?:text|words|name) (?:to|say|into)\s+[\"']?(.+?)[\"']?\s*$", raw, re.I)
        if mt:
            op("text_style", text=mt.group(1).strip())
    # ---------------------------------------------------------------- mockups
    imgs = _files(raw, ctx, IMG)
    if imgs:
        kind = _kind(words)
        if kind:
            op("mockup", kind=kind, images=imgs)
        elif subj == "mockup":
            op("mockup_image", images=imgs)
    elif subj == "mockup":
        kind = _kind(words)
        if kind and (re.search(r"\b(?:on|as|make it|turn it into|instead|try|now|what about|how about|switch to)\b", c) or len(c.split()) <= 3):
            op("mockup_kind", kind=kind)
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:x|by)\s*(\d+(?:\.\d+)?)\s*(?:x|by)\s*(\d+(?:\.\d+)?)\s*(cm|mm|in|inch(?:es)?)?\b", c)
    if m and (subj == "mockup" or any(o["op"] == "mockup" for o in ops)):
        k = {"mm": 0.1, "in": 2.54, "inch": 2.54, "inches": 2.54}.get(m.group(4) or "cm", 1.0)
        op("mockup_size", w=float(m.group(1)) * k, h=float(m.group(2)) * k, d=float(m.group(3)) * k)
    if re.search(
        r"\b(?:other|another|different) (?:angle|side|view)\b|\bfrom the (?:side|back|left|right)\b|\brotate (?:it|the camera)\b", c
    ) and subj in ("mockup", "model", "text"):
        op("angle", turn=40 if re.search(r"\bright\b", c) else -40 if re.search(r"\bleft\b", c) else 60)
    if not ops and re.search(r"\b\d{1,2}:\d{2}\b|\bsecs?\b", c):
        return {"ops": [], "ask": None}
    return done()


def seconds_in(text):
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?|minutes?|mins?)\b", text.lower())
    return secs(m.group(0)) if m else None
