"""A design becomes a web page you can keep working on. The input is Figma's own description of a frame (its REST API
JSON; a Canva page is first read into the same shape from Canva's PowerPoint export, see pptxtree.py), the output plain
HTML and CSS:

  - auto layout becomes flexbox (direction, gaps, padding, alignment, wrapping; each child fixed, hugging or filling);
    everything else is placed exactly where the design puts it, rotations and flips kept
  - texts stay real text, in the design's fonts (free Google fonts are saved into the project), with their sizes, weights,
    line heights, letter spacing, colours, mixed styles, links, lists, alignment and truncation
  - fills (colours, linear / radial / angular gradients, pictures), borders, rounded corners, shadows, blurs, opacity,
    blend modes, clipping and masks
  - icons and other vector shapes become SVG drawn from the design's own outlines; pictures become files in assets/
  - one CSS class per layer, named after the layer; indented HTML; landmarks (header, nav, section, footer), headings by
    size, buttons and links where the layers say so

  page = build(doc, node_id, images={imageRef: local file})     page.write(folder, font_css)
  page.elements: {css class: {"name", "type", "box": [x, y, w, h] in the design, "text"...}}  (what designcheck.py measures)
  page.fonts: {family: {(weight, italic)}}    page.notes: what could not be kept exactly
"""
import datetime as dt
import hashlib
import html
import json
import math
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from ai_pc.core.config import STATE

FONT_CACHE = STATE / "fonts"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
SYSTEM_FONTS = {"arial", "helvetica", "segoe ui", "times new roman", "georgia", "verdana", "tahoma", "calibri", "cambria", "courier new",
                "trebuchet ms", "impact", "consolas", "comic sans ms", "segoe ui emoji", "sans-serif", "serif", "monospace", "system-ui"}
CONTAINERS = {"FRAME", "GROUP", "COMPONENT", "COMPONENT_SET", "INSTANCE", "SECTION"}
VECTORS = {"VECTOR", "STAR", "REGULAR_POLYGON", "BOOLEAN_OPERATION", "LINE"}
SKIP = {"SLICE", "STICKY", "CONNECTOR", "WIDGET", "EMBED", "LINK_UNFURL", "STAMP", "HIGHLIGHT", "WASHI_TAPE", "CODE_BLOCK", "MEDIA"}
GENERIC = re.compile(r"^(?:frame|group|rectangle|ellipse|vector|line|polygon|star|image|img|photo|picture|union|subtract|intersect|exclude|"
                     r"text|component|instance|auto layout|layer|shape|path|mask group|mask|boolean|container|div|wrapper|"
                     r"text ?box|rounded rectangle|oval|freeform|straight connector|connector|"
                     r"(?:content|text|picture|title) placeholder|google shape)[\s_;-]*\d*$"
                     r"|^(?:title|subtitle|chart)[\s_-]*\d+$", re.I)  # PowerPoint's own names carry a number; a designer's 'Title' is kept
SECTIONS = re.compile(r"\b(?:hero|features?|pricing|plans?|testimonials?|reviews?|faq|about|contact|services?|team|gallery|blog|cta|"
                      r"newsletter|products?|how it works|stats|partners|clients|portfolio|banner|section)\b", re.I)
WEIGHTS = {"thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "regular": 400, "normal": 400, "book": 400,
           "medium": 500, "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800, "ultrabold": 800, "black": 900, "heavy": 900}


# ---------------------------------------------------------------- small helpers
def fmt(v, nd=2):
    v = round(float(v), nd)
    if v == 0:
        return "0"
    return f"{v:.{nd}f}".rstrip("0").rstrip(".")


def px(v):
    s = fmt(v)
    return "0" if s == "0" else s + "px"


def rgba(c, opacity=1.0):
    c = c or {}
    r, g, b = (round(max(0.0, min(1.0, float(c.get(k, 0)))) * 255) for k in ("r", "g", "b"))
    a = max(0.0, min(1.0, float(c.get("a", 1)) * (1.0 if opacity is None else float(opacity))))
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {fmt(a, 3)})"


def visible(paints):
    return [p for p in (paints or []) if p.get("visible", True) and float(p.get("opacity", 1)) > 0.001]


def bbox(n):
    b = n.get("absoluteBoundingBox") or {}
    return float(b.get("x", 0)), float(b.get("y", 0)), float(b.get("width", 0)), float(b.get("height", 0))


def turn(n):
    """The node's own rotation or flip (the 2x2 part of its transform), or None when it has none."""
    t = n.get("relativeTransform")
    if not t or not n.get("size"):
        return None
    a, c, b, d = t[0][0], t[0][1], t[1][0], t[1][1]
    if abs(a - 1) < 1e-3 and abs(d - 1) < 1e-3 and abs(b) < 1e-3 and abs(c) < 1e-3:
        return None
    return a, b, c, d


def matrix_css(m):
    return "matrix(" + ", ".join(fmt(v, 6) for v in m) + ", 0, 0)"


def slug(s, fallback="layer"):
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:32].strip("-")
    if not s:
        s = fallback
    return ("n-" + s) if s[0].isdigit() else s


def walk(n):
    yield n
    for k in n.get("children") or []:
        if k.get("visible", True):
            yield from walk(k)


def find(node, node_id):
    for n in walk(node):
        if n.get("id") == node_id:
            return n
    return None


def family_weight(name, weight=None):
    """'Montserrat Bold' -> ('Montserrat', 700) (PowerPoint keeps weights in names); 'Inter' -> ('Inter', weight)."""
    parts = str(name or "").split()
    w = weight
    while len(parts) > 1 and parts[-1].lower().replace("-", "") in WEIGHTS | {"italic": 0}:
        word = parts.pop().lower().replace("-", "")
        if word != "italic":
            w = w or WEIGHTS[word]
    return " ".join(parts) or str(name), w or 400


def stack(family):
    f = family.lower()
    generic = "monospace" if "mono" in f or "code" in f else "serif" if re.search(r"serif|times|georgia|garamond|playfair|merriweather|lora|"
                                                                                  r"baskerville|bodoni", f) and "sans" not in f else "sans-serif"
    fall = {"sans-serif": "Arial, sans-serif", "serif": "Georgia, serif", "monospace": "Consolas, monospace"}[generic]
    return f'"{family}", {fall}'


def sniff(path):
    head = Path(path).read_bytes()[:16]
    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:2] == b"\xff\xd8":
        return "jpg"
    if head.startswith(b"GIF8"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.lstrip().startswith((b"<svg", b"<?xml")):
        return "svg"
    return None


# ---------------------------------------------------------------- gradients
def gradient_css(p, w, h):
    stops, hp, op = p.get("gradientStops") or [], p.get("gradientHandlePositions") or [], p.get("opacity", 1)
    if len(hp) < 2 or not stops:
        return None
    x0, y0, x1, y1 = hp[0]["x"] * w, hp[0]["y"] * h, hp[1]["x"] * w, hp[1]["y"] * h
    t = p["type"]
    if t == "GRADIENT_LINEAR":
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        ux, uy = dx / ln, dy / ln
        ang = math.degrees(math.atan2(dx, -dy)) % 360  # CSS: 0deg points up, turning clockwise
        L = abs(w * ux) + abs(h * uy) or 1.0  # the length of CSS's gradient line for that angle, through the centre
        sx, sy = w / 2 - ux * L / 2, h / 2 - uy * L / 2
        base = (x0 - sx) * ux + (y0 - sy) * uy
        parts = [f"{rgba(s['color'], op)} {fmt((base + s['position'] * ln) / L * 100)}%" for s in stops]
        return f"linear-gradient({fmt(ang)}deg, {', '.join(parts)})"
    if t in ("GRADIENT_RADIAL", "GRADIENT_DIAMOND"):
        rx = math.hypot(x1 - x0, y1 - y0)
        ry = math.hypot(hp[2]["x"] * w - x0, hp[2]["y"] * h - y0) if len(hp) > 2 else rx
        parts = [f"{rgba(s['color'], op)} {fmt(s['position'] * 100)}%" for s in stops]
        return f"radial-gradient({px(rx)} {px(ry)} at {px(x0)} {px(y0)}, {', '.join(parts)})"
    if t == "GRADIENT_ANGULAR":
        ang = math.degrees(math.atan2(x1 - x0, -(y1 - y0))) % 360
        parts = [f"{rgba(s['color'], op)} {fmt(s['position'] * 360)}deg" for s in stops]
        return f"conic-gradient(from {fmt(ang)}deg at {px(x0)} {px(y0)}, {', '.join(parts)})"
    return None


def first_color(p):
    if p.get("type") == "SOLID":
        return rgba(p.get("color"), p.get("opacity", 1))
    st = p.get("gradientStops") or []
    return rgba(st[0]["color"], p.get("opacity", 1)) if st else "#000000"


# ---------------------------------------------------------------- layout
def flex_container(n):
    horiz = n.get("layoutMode") == "HORIZONTAL"
    css = {"display": "flex", "flex-direction": "row" if horiz else "column"}
    pad = [n.get("paddingTop", 0) or 0, n.get("paddingRight", 0) or 0, n.get("paddingBottom", 0) or 0, n.get("paddingLeft", 0) or 0]
    jc = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "SPACE_BETWEEN": "space-between"}.get(n.get("primaryAxisAlignItems") or "MIN", "flex-start")
    if jc != "flex-start":
        css["justify-content"] = jc
    css["align-items"] = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "BASELINE": "baseline"}.get(n.get("counterAxisAlignItems") or "MIN",
                                                                                                                  "flex-start")
    gap = float(n.get("itemSpacing", 0) or 0)
    if n.get("layoutWrap") == "WRAP":
        css["flex-wrap"] = "wrap"
        cross = float(n.get("counterAxisSpacing", gap) or 0)
        css["gap"] = f"{px(cross)} {px(gap)}" if horiz else f"{px(gap)} {px(cross)}"
        css["align-content"] = "space-between" if n.get("counterAxisAlignContent") == "SPACE_BETWEEN" else "flex-start"
    elif gap > 0 and jc != "space-between":
        css["gap"] = px(gap)
    if any(pad):
        css["padding"] = " ".join(px(p) for p in pad)
    return css


def own_hug(n):
    """(hugs its width, hugs its height) from the node's own settings."""
    if n.get("type") == "TEXT":
        mode = (n.get("style") or {}).get("textAutoResize") or "NONE"
        return mode == "WIDTH_AND_HEIGHT", mode in ("WIDTH_AND_HEIGHT", "HEIGHT")
    if n.get("layoutMode") in ("HORIZONTAL", "VERTICAL"):
        p = n.get("primaryAxisSizingMode") == "AUTO"
        c = n.get("counterAxisSizingMode") == "AUTO"
        return (p, c) if n["layoutMode"] == "HORIZONTAL" else (c, p)
    return False, False


def sizing(n, parent=None):
    """'FIXED' | 'HUG' | 'FILL' for width and height."""
    sh, sv = n.get("layoutSizingHorizontal"), n.get("layoutSizingVertical")
    if sh and sv:
        return sh, sv
    hx, hy = own_hug(n)
    horiz = (parent or {}).get("layoutMode") == "HORIZONTAL"
    vert = (parent or {}).get("layoutMode") == "VERTICAL"
    grow, stretch = (n.get("layoutGrow") or 0) >= 1, n.get("layoutAlign") == "STRETCH"
    x = "FILL" if (horiz and grow) or (vert and stretch) else "HUG" if hx else "FIXED"
    y = "FILL" if (vert and grow) or (horiz and stretch) else "HUG" if hy else "FIXED"
    return sh or x, sv or y


def radius(n):
    rr = n.get("rectangleCornerRadii")
    if rr and len(set(round(v, 2) for v in rr)) > 1:
        return {"border-radius": " ".join(px(v) for v in rr)}
    r = n.get("cornerRadius") or (rr[0] if rr else 0)
    return {"border-radius": px(r)} if r else {}


class Page:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def write(self, folder, font_css=""):
        """index.html, styles.css, assets/, design/design.json and a README into folder -> the files written (relative)."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        written = []
        for rel, src in self.assets.items():
            p = folder / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(src, (bytes, bytearray)):
                p.write_bytes(src)
            else:
                shutil.copyfile(src, p)
            written.append(rel)
        (folder / "index.html").write_text(self.html, encoding="utf-8", newline="\n")
        (folder / "styles.css").write_text((font_css + "\n" if font_css else "") + self.css, encoding="utf-8", newline="\n")
        d = folder / "design"
        d.mkdir(exist_ok=True)
        meta = {"source": self.source, "name": self.title, "w": self.w, "h": self.h, "root": self.root, "made": dt.datetime.now().isoformat(timespec="seconds"),
                "fonts": {k: sorted([list(x) for x in v]) for k, v in self.fonts.items()}, "notes": self.notes, "elements": self.elements,
                **self.origin_info}
        (d / "design.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
        (folder / "README.md").write_text(self.readme(), encoding="utf-8", newline="\n")
        return written + ["index.html", "styles.css", "design/design.json", "README.md"]

    def readme(self):
        where = {"figma": "the Figma frame", "canva": "the Canva design"}.get(self.source, "the design")
        lines = [f"# {self.title}", "",
                 f"Made by the AI PC from {where} \"{self.title}\" ({fmt(self.w)} x {fmt(self.h)} px) on {dt.date.today():%d %B %Y}.", "",
                 "Open `index.html` in a browser. `styles.css` has one rule per design layer, named after the layer.", "",
                 "- `assets/`: the pictures, and the fonts (from Google Fonts, free licences: SIL Open Font License or Apache 2.0)",
                 "- `design/design.json`: where every element sits in the design (the AI PC measures the page against it)",
                 "- `design/reference.png`: the design as the design tool draws it, when it could be fetched"]
        if self.notes:
            lines += ["", "Not kept exactly:", *[f"- {n}" for n in self.notes[:20]]]
        return "\n".join(lines) + "\n"


class Build:
    def __init__(self, root, images=None, source="figma"):
        self.root, self.images, self.source = root, images or {}, source
        self.used = Counter()
        self.rules = []  # (selector, {prop: value})
        self.assets, self.img_src = {}, {}
        self.elements, self.notes, self.fonts = {}, [], {}
        self.origin = bbox(root)[:2]
        sizes = sorted({round((t.get("style") or {}).get("fontSize", 0)) for t in walk(root) if t.get("type") == "TEXT"}, reverse=True)
        self.levels = {s: f"h{i}" for i, s in enumerate([s for s in sizes if s >= 24][:3], 1)}

    # ---------------------------------------------------------------- names, rules, records
    def name(self, n, fallback=None):
        nm = (n.get("name") or "").strip()
        base = slug(nm if nm and not GENERIC.match(nm) else (fallback or nm or n.get("type", "layer")), (n.get("type") or "layer").lower())
        self.used[base] += 1
        return base if self.used[base] == 1 else f"{base}-{self.used[base]}"

    def rule(self, selector, css, slot=None):
        css = {k: v for k, v in css.items() if v is not None and not k.startswith("_")}
        r = (selector if selector[0] in ".#*:" or " " in selector else "." + selector, css) if css else None
        if slot is not None:
            self.rules[slot] = r
        elif r:
            self.rules.append(r)

    def note(self, s):
        if s not in self.notes:
            self.notes.append(s)

    def record(self, cls, n, **extra):
        x, y, w, h = bbox(n)
        e = {"name": n.get("name", ""), "type": n.get("type"), "box": [round(x - self.origin[0], 2), round(y - self.origin[1], 2), round(w, 2), round(h, 2)]}
        e.update(extra)
        self.elements[cls] = e

    def font(self, family, weight, italic):
        if family:
            self.fonts.setdefault(family, set()).add((int(round(weight / 100.0) * 100) or 400, bool(italic)))

    # ---------------------------------------------------------------- placing
    def place(self, n, ctx):
        css = {}
        x, y, w, h = bbox(n)
        flex = ctx.get("flex")
        t = n.get("type")
        if flex is not None and n.get("layoutPositioning") != "ABSOLUTE":
            horiz = flex.get("layoutMode") == "HORIZONTAL"
            sx, sy = sizing(n, flex)
            prim, cross = (sx, sy) if horiz else (sy, sx)
            pd, cd = ("width", "height") if horiz else ("height", "width")
            pv, cv = (w, h) if horiz else (h, w)
            if prim == "FILL":
                css["flex"] = "1 1 0"
                css["min-" + pd] = "0"
            else:
                css["flex"] = "none"
                if prim == "FIXED":
                    css[pd] = px(pv)
            if cross == "FILL":
                css["align-self"] = "stretch"
            elif cross == "FIXED":
                css[cd] = px(cv)
            for k, prop in (("minWidth", "min-width"), ("maxWidth", "max-width"), ("minHeight", "min-height"), ("maxHeight", "max-height")):
                if n.get(k):
                    css[prop] = px(n[k])
            if ctx.get("margin"):
                css[ctx["margin"][0]] = px(ctx["margin"][1])
            if ctx.get("z") is not None:
                css["position"], css["z-index"] = "relative", str(ctx["z"])
            m = None if t in VECTORS else turn(n)
            if m:
                css["transform"] = matrix_css(m)
            return css
        ox, oy = ctx["origin"]
        m = None if (t in VECTORS or ctx.get("no_turn")) else turn(n)
        if ctx.get("rotated") and n.get("relativeTransform") and n.get("size"):  # inside a rotated frame: the frame's own coordinates
            (a, c, e), (b, d, f) = n["relativeTransform"][0], n["relativeTransform"][1]
            sw, sh = n["size"]["x"], n["size"]["y"]
            if t in VECTORS:
                xs, ys = [a * u + c * v for u, v in ((0, 0), (sw, 0), (0, sh), (sw, sh))], [b * u + d * v for u, v in ((0, 0), (sw, 0), (0, sh), (sw, sh))]
                css.update(position="absolute", left=px(e + min(xs)), top=px(f + min(ys)))
                return css
            cx, cy = a * sw / 2 + c * sh / 2 + e, b * sw / 2 + d * sh / 2 + f
            css.update(position="absolute", left=px(cx - sw / 2), top=px(cy - sh / 2), width=px(sw), height=px(sh))
            if m:
                css["transform"] = matrix_css(m)
            return css
        if m:
            sw, sh = n["size"]["x"], n["size"]["y"]
            cx, cy = x + w / 2 - ox, y + h / 2 - oy  # a rotated box's centre is its bounding box's centre
            css.update(position="absolute", left=px(cx - sw / 2), top=px(cy - sh / 2), width=px(sw), height=px(sh), transform=matrix_css(m))
            return css
        css.update(position="absolute", left=px(x - ox), top=px(y - oy))
        hx, hy = own_hug(n)
        if t == "TEXT" or not hx:
            css["width"] = px(w)
        if not hy:
            css["height"] = px(h)
        if ctx.get("z") is not None:
            css["z-index"] = str(ctx["z"])
        return css

    # ---------------------------------------------------------------- paint
    def paint(self, n, w, h):
        fills = visible(n.get("fills"))
        if not fills:
            return {}
        layers = []
        for p in reversed(fills):  # CSS lists the top layer first, Figma the bottom one
            t = p.get("type", "")
            if t == "SOLID":
                layers.append(("solid", rgba(p.get("color"), p.get("opacity", 1)), None))
            elif t.startswith("GRADIENT"):
                g = gradient_css(p, w, h)
                if g:
                    layers.append(("image", g, None))
            elif t == "IMAGE":
                src = self.image_src(p.get("imageRef"), n)
                if src:
                    layers.append(("image", f'url("{src}")', p.get("scaleMode") or "FILL"))
                    if p.get("opacity", 1) < 0.999:
                        self.note(f"'{n.get('name')}': a see-through picture fill is shown solid")
                    if p.get("filters"):
                        self.note(f"'{n.get('name')}': picture adjustments (exposure, contrast...) are not applied")
        if not layers:
            return {}
        if len(layers) == 1 and layers[0][0] == "solid":
            return {"background-color": layers[0][1]}
        css, imgs, sizes, reps, poss = {}, [], [], [], []
        for i, (kind, val, mode) in enumerate(layers):
            if kind == "solid":
                if i == len(layers) - 1:
                    css["background-color"] = val
                    continue
                imgs.append(f"linear-gradient({val}, {val})")
                sizes.append("auto")
                reps.append("no-repeat")
                poss.append("center")
                continue
            imgs.append(val)
            sizes.append({"FIT": "contain", "TILE": "auto"}.get(mode, "cover") if mode else "auto")
            reps.append("repeat" if mode == "TILE" else "no-repeat")
            poss.append("top left" if mode == "TILE" else "center")
        if imgs:
            css["background-image"] = ", ".join(imgs)
            if any(s != "auto" for s in sizes):
                css["background-size"] = ", ".join(sizes)
            css["background-position"] = ", ".join(poss)
            css["background-repeat"] = ", ".join(reps)
        return css

    def image_src(self, ref, n):
        if ref in self.img_src:
            return self.img_src[ref]
        src = self.images.get(ref) if ref else None
        if not src or not Path(src).exists():
            self.note(f"'{n.get('name')}': its picture could not be fetched")
            return None
        ext = sniff(src) or Path(src).suffix.lstrip(".").lower() or "png"
        nm = (n.get("name") or "").strip()
        base = slug(nm if nm and not GENERIC.match(nm) else "image", "image")
        rel, k = f"assets/{base}.{ext}", 2
        while rel in self.assets:
            rel, k = f"assets/{base}-{k}.{ext}", k + 1
        self.assets[rel] = Path(src)
        self.img_src[ref] = rel
        return rel

    def decorate(self, n, css, kind="box"):
        """Borders, shadows, blurs, opacity and blend mode."""
        shadows, filters, backdrop, tshadows = [], [], [], []
        strokes = visible(n.get("strokes"))
        wgt = float(n.get("strokeWeight", 0) or 0)
        if strokes and kind == "box":
            col = first_color(strokes[-1])
            if strokes[-1].get("type", "").startswith("GRADIENT") or strokes[-1].get("type") == "IMAGE":
                self.note(f"'{n.get('name')}': a gradient or picture border is drawn in one colour")
            iw = n.get("individualStrokeWeights")
            if iw and len({round(iw.get(k, 0), 2) for k in ("top", "right", "bottom", "left")}) > 1:
                t, r, b, l = (float(iw.get(k, 0) or 0) for k in ("top", "right", "bottom", "left"))
                shadows += [s for s, v in ((f"inset 0 {px(t)} 0 0 {col}", t), (f"inset {px(-r)} 0 0 0 {col}", r), (f"inset 0 {px(-b)} 0 0 {col}", b),
                                           (f"inset {px(l)} 0 0 0 {col}", l)) if v]
            elif wgt > 0:
                align = n.get("strokeAlign") or "INSIDE"
                css["outline"] = f"{px(wgt)} {'dashed' if n.get('strokeDashes') else 'solid'} {col}"
                css["outline-offset"] = px({"INSIDE": -wgt, "CENTER": -wgt / 2}.get(align, 0))
        elif strokes and kind == "text" and wgt > 0:
            css["-webkit-text-stroke"] = f"{px(wgt)} {first_color(strokes[-1])}"
        has_fill = bool(visible(n.get("fills")))
        for e in reversed(n.get("effects") or []):
            if not e.get("visible", True):
                continue
            t = e.get("type")
            if t in ("DROP_SHADOW", "INNER_SHADOW"):
                c, o = rgba(e.get("color")), e.get("offset") or {"x": 0, "y": 0}
                r, s = float(e.get("radius", 0) or 0), float(e.get("spread", 0) or 0)
                if kind == "text":
                    if t == "DROP_SHADOW":
                        tshadows.append(f"{px(o['x'])} {px(o['y'])} {px(r)} {c}")
                elif t == "DROP_SHADOW" and (kind == "svg" or not has_fill):
                    filters.append(f"drop-shadow({px(o['x'])} {px(o['y'])} {px(r)} {c})")
                elif kind != "svg":
                    shadows.append(f"{'inset ' if t == 'INNER_SHADOW' else ''}{px(o['x'])} {px(o['y'])} {px(r)}{' ' + px(s) if s else ''} {c}")
            elif t == "LAYER_BLUR":
                filters.append(f"blur({px(float(e.get('radius', 0)) / 2)})")
            elif t == "BACKGROUND_BLUR":
                backdrop.append(f"blur({px(float(e.get('radius', 0)) / 2)})")
        if shadows:
            css["box-shadow"] = ", ".join(shadows)
        if tshadows:
            css["text-shadow"] = ", ".join(tshadows)
        if filters:
            css["filter"] = " ".join(filters)
        if backdrop:
            css["backdrop-filter"] = " ".join(backdrop)
        op = n.get("opacity", 1)
        if op is not None and op < 0.999:
            css["opacity"] = fmt(op, 3)
        bm = (n.get("blendMode") or "").upper()
        if bm and bm not in ("PASS_THROUGH", "NORMAL"):
            css["mix-blend-mode"] = bm.lower().replace("_", "-").replace("linear-burn", "color-burn").replace("linear-dodge", "color-dodge")

    # ---------------------------------------------------------------- the tree
    def render(self, n, ctx, ind):
        t = n.get("type")
        if not n.get("visible", True) or t in SKIP:
            if t in SKIP and t != "SLICE":
                self.note(f"'{n.get('name')}' ({t.lower()}) is left out")
            return []
        x, y, w, h = bbox(n)
        if w <= 0 and h <= 0 and t not in VECTORS:
            return []
        if t == "TEXT":
            return self.text(n, ctx, ind)
        if t in VECTORS or (t == "ELLIPSE" and self.partial_arc(n)):
            return self.vector(n, ctx, ind)
        if t in ("RECTANGLE", "ELLIPSE") or t in CONTAINERS or n.get("children"):
            fills = visible(n.get("fills"))
            if len(fills) == 1 and fills[0].get("type") == "IMAGE" and not n.get("children") and fills[0].get("scaleMode") != "TILE" \
                    and not visible(n.get("strokes")):
                return self.picture(n, ctx, ind, fills[0])
            return self.box(n, ctx, ind)
        self.note(f"'{n.get('name')}' ({str(t).lower()}) is not drawn")
        return []

    @staticmethod
    def partial_arc(n):
        a = n.get("arcData")
        return bool(a) and (abs((a.get("endingAngle", 0) - a.get("startingAngle", 0)) - 2 * math.pi) > 1e-3 or a.get("innerRadius", 0) > 1e-3)

    def tag(self, n, ctx):
        nm = (n.get("name") or "").strip().lower()
        if ctx.get("phrasing"):
            return "span"
        if re.search(r"\b(?:button|btn)\b", nm) and not any(re.search(r"\b(?:button|btn|link)\b", (k.get("name") or "").lower())
                                                            for k in list(walk(n))[1:]):
            return "button"
        if ctx.get("depth") == 1:
            if re.search(r"\b(?:nav|navbar|navigation|menu)\b", nm):
                return "nav"
            if re.search(r"\b(?:header|top ?bar)\b", nm):
                return "header"
            if re.search(r"\bfooter\b", nm):
                return "footer"
            if SECTIONS.search(nm):
                return "section"
        return "div"

    def box(self, n, ctx, ind):
        t = n.get("type")
        x, y, w, h = bbox(n)
        cls = self.name(n)
        css = self.place(n, ctx)
        kids = [k for k in n.get("children") or [] if k.get("visible", True)]
        auto = n.get("layoutMode") in ("HORIZONTAL", "VERTICAL") and t != "GROUP"
        if n.get("layoutMode") == "GRID":
            self.note(f"'{n.get('name')}': its grid layout is kept as fixed positions")
        if kids and "position" not in css:
            css["position"] = "relative"
        if auto:
            css.update(flex_container(n))
            css["box-sizing"] = "border-box"
        css.update(self.paint(n, w, h))
        css.update(radius(n))
        if t == "ELLIPSE":
            css["border-radius"] = "50%"
        if n.get("clipsContent") and kids:
            css["overflow"] = "hidden"
        self.decorate(n, css)
        tag = self.tag(n, ctx)
        self.record(cls, n)
        self.rule(cls, css)
        attrs = ' type="button"' if tag == "button" else ""
        if not kids:
            return [f'{ind}<{tag} class="{cls}"{attrs}></{tag}>']
        sub = dict(origin=(x, y), flex=n if auto else None, rotated=bool(turn(n)) and t != "GROUP", depth=ctx.get("depth", 0) + 1,
                   phrasing=ctx.get("phrasing") or tag in ("button", "a"), landmark=ctx.get("landmark") or tag in ("nav", "header", "footer", "button"))
        return [f'{ind}<{tag} class="{cls}"{attrs}>'] + self.children(n, kids, sub, ind + "  ") + [f"{ind}</{tag}>"]

    def children(self, n, kids, sub, ind):
        out = []
        auto = sub.get("flex") is not None
        gap = float(n.get("itemSpacing", 0) or 0)
        neg = auto and gap < 0 and n.get("primaryAxisAlignItems") != "SPACE_BETWEEN"
        rev = auto and n.get("itemReverseZIndex")
        flow = [id(k) for k in kids if k.get("layoutPositioning") != "ABSOLUTE"]
        i = 0
        while i < len(kids):
            k = kids[i]
            if k.get("isMask"):
                out += self.mask(k, kids[i + 1:], sub, ind)
                break
            c = dict(sub)
            if neg and id(k) in flow and flow.index(id(k)) > 0:
                c["margin"] = ("margin-left" if n.get("layoutMode") == "HORIZONTAL" else "margin-top", gap)
            if rev and id(k) in flow:
                c["z"] = len(flow) - flow.index(id(k))
            out += self.render(k, c, ind)
            i += 1
        return out

    def mask(self, m, group, ctx, ind):
        """A mask: the layers above it in its container show only inside its shape."""
        x, y, w, h = bbox(m)
        cls = self.name(m, "mask")
        css = self.place(m, dict(ctx, flex=None, no_turn=True))
        css["width"], css["height"] = px(w), px(h)
        if m.get("type") == "ELLIPSE":
            css["border-radius"], css["overflow"] = "50%", "hidden"
        elif m.get("type") in ("RECTANGLE", "FRAME"):
            css.update(radius(m))
            css["overflow"] = "hidden"
        elif m.get("fillGeometry") and not turn(m):
            css["clip-path"] = "path('" + " ".join(g["path"] for g in m["fillGeometry"]) + "')"
        else:
            css["overflow"] = "hidden"
            self.note(f"'{m.get('name')}': a turned mask is kept as a box")
        self.rule(cls, css)
        self.record(cls, m)
        sub = dict(ctx, origin=(x, y), flex=None, rotated=False)
        inner = []
        for k in group:
            inner += self.render(k, sub, ind + "  ")
        return [f'{ind}<div class="{cls}">'] + inner + [f"{ind}</div>"]

    def picture(self, n, ctx, ind, fill):
        cls = self.name(n, "image")
        css = self.place(n, ctx)
        src = self.image_src(fill.get("imageRef"), n)
        css["object-fit"] = {"FIT": "contain", "STRETCH": "fill"}.get(fill.get("scaleMode"), "cover")
        css.update(radius(n))
        if n.get("type") == "ELLIPSE":
            css["border-radius"] = "50%"
        self.decorate(n, css)
        self.record(cls, n)
        self.rule(cls, css)
        nm = (n.get("name") or "").strip()
        alt = "" if GENERIC.match(nm) else nm
        if not src:
            css2 = {"background-color": "#d9d9d9"}
            self.rule(cls + "-missing", css2)
            return [f'{ind}<div class="{cls} {cls}-missing" role="img" aria-label="{html.escape(alt)}"></div>']
        return [f'{ind}<img class="{cls}" src="{src}" alt="{html.escape(alt)}">']

    # ---------------------------------------------------------------- vectors
    def vector(self, n, ctx, ind):
        cls = self.name(n, "icon")
        css = self.place(n, ctx)
        x, y, w, h = bbox(n)
        size = n.get("size") or {"x": w, "y": h}
        sw, sh = float(size["x"]), float(size["y"])
        a, b, c, d = turn(n) or (1.0, 0.0, 0.0, 1.0)
        xs = [a * u + c * v for u, v in ((0, 0), (sw, 0), (0, sh), (sw, sh))]
        ys = [b * u + d * v for u, v in ((0, 0), (sw, 0), (0, sh), (sw, sh))]
        minx, miny = min(xs), min(ys)
        bw, bh = max(max(xs) - minx, 1.0), max(max(ys) - miny, 1.0)
        if ctx.get("flex") is None or n.get("layoutPositioning") == "ABSOLUTE":
            css["width"], css["height"] = px(bw), px(bh)
        defs, body = [], []
        for g in n.get("fillGeometry") or []:
            rule_ = "evenodd" if g.get("windingRule") == "EVENODD" else "nonzero"
            for p in visible(n.get("fills")):
                paint, extra = self.svg_paint(p, sw, sh, defs, cls, n)
                if paint:
                    body.append(f'<path d="{g["path"]}" fill="{paint}" fill-rule="{rule_}"{extra}/>')
        for g in n.get("strokeGeometry") or []:
            for p in visible(n.get("strokes")):
                paint, extra = self.svg_paint(p, sw, sh, defs, cls, n)
                if paint:
                    body.append(f'<path d="{g["path"]}" fill="{paint}"{extra}/>')
        if not body and (n.get("fillGeometry") is None and n.get("strokeGeometry") is None):
            fills = visible(n.get("fills")) or visible(n.get("strokes"))
            if fills:
                body.append(f'<rect width="{fmt(sw)}" height="{fmt(sh)}" fill="{first_color(fills[-1])}"/>')
                self.note(f"'{n.get('name')}': drawn as a box (the design was read without its outlines)")
        tf = (a, b, c, d) != (1.0, 0.0, 0.0, 1.0) or abs(minx) > 1e-6 or abs(miny) > 1e-6
        g_open = f'<g transform="matrix({fmt(a, 6)} {fmt(b, 6)} {fmt(c, 6)} {fmt(d, 6)} {fmt(-minx, 3)} {fmt(-miny, 3)})">' if tf else ""
        css["overflow"] = "visible"
        self.decorate(n, css, "svg")
        self.record(cls, n)
        self.rule(cls, css)
        svg = (f'<svg class="{cls}" width="{fmt(bw)}" height="{fmt(bh)}" viewBox="0 0 {fmt(bw)} {fmt(bh)}" fill="none" xmlns="http://www.w3.org/2000/svg" '
               f'aria-hidden="true">' + (f"<defs>{''.join(defs)}</defs>" if defs else "") + g_open + "".join(body) + ("</g>" if tf else "") + "</svg>")
        return [ind + svg]

    def svg_paint(self, p, sw, sh, defs, cls, n):
        t = p.get("type", "")
        if t == "SOLID":
            col = p.get("color") or {}
            a = float(col.get("a", 1)) * float(p.get("opacity", 1))
            return rgba(dict(col, a=1)), (f' fill-opacity="{fmt(a, 3)}"' if a < 0.999 else "")
        gid = f"{cls}-p{len(defs)}"
        if t.startswith("GRADIENT"):
            hp, op = p.get("gradientHandlePositions") or [], float(p.get("opacity", 1))
            if len(hp) < 2:
                return None, ""
            stops = "".join(f'<stop offset="{fmt(s["position"], 4)}" stop-color="{rgba(dict(s["color"], a=1))}"'
                            + (f' stop-opacity="{fmt(s["color"].get("a", 1) * op, 3)}"' if s["color"].get("a", 1) * op < 0.999 else "") + "/>"
                            for s in p.get("gradientStops") or [])
            x0, y0, x1, y1 = hp[0]["x"] * sw, hp[0]["y"] * sh, hp[1]["x"] * sw, hp[1]["y"] * sh
            if t == "GRADIENT_LINEAR":
                defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{fmt(x0)}" y1="{fmt(y0)}" x2="{fmt(x1)}" y2="{fmt(y1)}">{stops}'
                            "</linearGradient>")
            else:
                defs.append(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{fmt(x0)}" cy="{fmt(y0)}" r="{fmt(math.hypot(x1 - x0, y1 - y0))}">'
                            f"{stops}</radialGradient>")
                if t == "GRADIENT_ANGULAR":
                    self.note(f"'{n.get('name')}': an angular gradient in an icon is drawn as a radial one")
            return f"url(#{gid})", ""
        if t == "IMAGE":
            src = self.image_src(p.get("imageRef"), n)
            if not src:
                return None, ""
            defs.append(f'<pattern id="{gid}" patternUnits="userSpaceOnUse" width="{fmt(sw)}" height="{fmt(sh)}"><image href="{src}" width="{fmt(sw)}" '
                        f'height="{fmt(sh)}" preserveAspectRatio="xMidYMid slice"/></pattern>')
            return f"url(#{gid})", ""
        return None, ""

    # ---------------------------------------------------------------- text
    def text_css(self, st, fills, w, h):
        css = {}
        fam = st.get("fontFamily") or "Inter"
        wt = int(st.get("fontWeight") or 400)
        it = bool(st.get("italic"))
        self.font(fam, wt, it)
        css["font-family"] = stack(fam)
        css["font-size"] = px(st.get("fontSize", 16))
        css["font-weight"] = str(wt)
        if it:
            css["font-style"] = "italic"
        if st.get("lineHeightPx"):
            css["line-height"] = px(st["lineHeightPx"])
        ls = float(st.get("letterSpacing") or 0)
        if abs(ls) > 0.001:
            css["letter-spacing"] = px(ls)
        al = {"CENTER": "center", "RIGHT": "right", "JUSTIFIED": "justify"}.get(st.get("textAlignHorizontal"))
        if al:
            css["text-align"] = al
        case = st.get("textCase")
        if case in ("UPPER", "LOWER", "TITLE"):
            css["text-transform"] = {"UPPER": "uppercase", "LOWER": "lowercase", "TITLE": "capitalize"}[case]
        elif case in ("SMALL_CAPS", "SMALL_CAPS_FORCED"):
            css["font-variant-caps"] = "small-caps" if case == "SMALL_CAPS" else "all-small-caps"
        deco = {"UNDERLINE": "underline", "STRIKETHROUGH": "line-through"}.get(st.get("textDecoration"))
        if deco:
            css["text-decoration"] = deco
        if st.get("paragraphIndent"):
            css["text-indent"] = px(st["paragraphIndent"])
        fl = visible(fills)
        if fl:
            top = fl[-1]
            if top.get("type") == "SOLID":
                css["color"] = rgba(top.get("color"), top.get("opacity", 1))
            elif top.get("type", "").startswith("GRADIENT"):
                css.update({"background-image": gradient_css(top, w, h), "-webkit-background-clip": "text", "background-clip": "text",
                            "color": "transparent"})
            else:
                css["color"] = "#000000"
        elif fills is not None:
            css["color"] = "transparent"
        return css

    def run_css(self, st, base):
        css = {}
        fam = st.get("fontFamily", base.get("fontFamily"))
        wt = int(st.get("fontWeight", base.get("fontWeight", 400)) or 400)
        it = bool(st.get("italic", base.get("italic")))
        if fam != base.get("fontFamily") or wt != int(base.get("fontWeight") or 400) or it != bool(base.get("italic")):
            self.font(fam, wt, it)
        if st.get("fontFamily") and st["fontFamily"] != base.get("fontFamily"):
            css["font-family"] = stack(st["fontFamily"])
        if "fontWeight" in st and int(st["fontWeight"]) != int(base.get("fontWeight") or 400):
            css["font-weight"] = str(int(st["fontWeight"]))
        if "italic" in st and bool(st["italic"]) != bool(base.get("italic")):
            css["font-style"] = "italic" if st["italic"] else "normal"
        if st.get("fontSize") and st["fontSize"] != base.get("fontSize"):
            css["font-size"] = px(st["fontSize"])
        if st.get("lineHeightPx") and st["lineHeightPx"] != base.get("lineHeightPx"):
            css["line-height"] = px(st["lineHeightPx"])
        if "letterSpacing" in st and st["letterSpacing"] != base.get("letterSpacing"):
            css["letter-spacing"] = px(st["letterSpacing"] or 0)
        if "textDecoration" in st and st["textDecoration"] != base.get("textDecoration"):
            css["text-decoration"] = {"UNDERLINE": "underline", "STRIKETHROUGH": "line-through"}.get(st["textDecoration"], "none")
        if "textCase" in st and st["textCase"] != base.get("textCase"):
            css["text-transform"] = {"UPPER": "uppercase", "LOWER": "lowercase", "TITLE": "capitalize"}.get(st["textCase"], "none")
        fl = visible(st.get("fills"))
        if fl and fl[-1].get("type") == "SOLID":
            css["color"] = rgba(fl[-1].get("color"), fl[-1].get("opacity", 1))
        return css

    def text_tag(self, n, ctx, lists):
        if ctx.get("phrasing"):
            return "span"
        if lists:
            return "div"
        if ctx.get("landmark"):  # a logo or a menu item in a navigation bar or footer is not a heading
            return "p"
        return self.levels.get(round((n.get("style") or {}).get("fontSize", 0)), "p")

    def text(self, n, ctx, ind):
        st = n.get("style") or {}
        x, y, w, h = bbox(n)
        cls = self.name(n, ((n.get("characters") or "text").strip().split("\n")[0])[:24])
        css = self.place(n, ctx)
        css.update(self.text_css(st, n.get("fills"), w, h))
        mode = st.get("textAutoResize") or "NONE"
        css["white-space"] = "pre" if mode == "WIDTH_AND_HEIGHT" else "pre-wrap"
        if mode != "WIDTH_AND_HEIGHT":
            css["overflow-wrap"] = "break-word"
        if mode == "TRUNCATE" or st.get("textTruncation") == "ENDING":
            css["overflow"], css["text-overflow"] = "hidden", "ellipsis"
            ml = st.get("maxLines")
            if ml and ml > 1:
                css.update({"display": "-webkit-box", "-webkit-box-orient": "vertical", "-webkit-line-clamp": str(int(ml))})
            elif mode != "HEIGHT":
                css["white-space"] = "pre"
        lists = any(t in ("ORDERED", "UNORDERED") for t in n.get("lineTypes") or [])
        slot = len(self.rules)
        self.rules.append(None)  # the text's own rule goes before the rules of its runs
        inner = self.text_inner(n, cls, lists)
        valign = st.get("textAlignVertical") or "TOP"
        if "height" in css and valign in ("CENTER", "BOTTOM") and "display" not in css:
            css.update({"display": "flex", "flex-direction": "column", "justify-content": "center" if valign == "CENTER" else "flex-end"})
            inner = f'<span class="{cls}-in">{inner}</span>'
            self.rule(cls + "-in", {"display": "block"})
        self.decorate(n, css, "text")
        tag = self.text_tag(n, ctx, lists)
        link = st.get("hyperlink") or {}
        if link.get("type") == "URL" and link.get("url") and not ctx.get("phrasing"):
            inner = f'<a href="{html.escape(link["url"])}">{inner}</a>'
        self.rule(cls, css, slot)
        # what the checks will look for: the words, and whether the box is fixed (a wider font would spill out of it)
        self.record(cls, n, text=n.get("characters", ""), nowrap=mode == "WIDTH_AND_HEIGHT", fixed_h=mode in ("NONE", "TRUNCATE"),
                    hug=ctx.get("flex") is not None and sizing(n, ctx["flex"])[0] == "HUG")
        return [f'{ind}<{tag} class="{cls}">{inner}</{tag}>']

    def text_inner(self, n, cls, lists):
        chars = (n.get("characters") or "").replace(" ", "\n")
        ov = n.get("characterStyleOverrides") or []
        table = {str(k): v for k, v in (n.get("styleOverrideTable") or {}).items()}
        base = n.get("style") or {}
        runs, i16 = [], 0
        for ch in chars:  # Figma counts characters in UTF-16 units (an emoji is two)
            sid = ov[i16] if i16 < len(ov) else 0
            i16 += 2 if ord(ch) > 0xFFFF else 1
            sid = sid if str(sid) in table and sid else 0
            if runs and runs[-1][1] == sid:
                runs[-1][0].append(ch)
            else:
                runs.append(([ch], sid))
        runs = [("".join(a), s) for a, s in runs]
        made = set()

        def span(text, sid):
            t = html.escape(text, quote=False)
            if not sid:
                return t
            st = table[str(sid)]
            sc = f"{cls}-s{sid}"
            if sc not in made:
                made.add(sc)
                self.rule(sc, self.run_css(st, base))
            t = f'<span class="{sc}">{t}</span>'
            link = st.get("hyperlink") or {}
            if link.get("type") == "URL" and link.get("url"):
                t = f'<a href="{html.escape(link["url"])}">{t}</a>'
            return t

        lines = [[]]
        for text, sid in runs:
            for j, part in enumerate(text.split("\n")):
                if j:
                    lines.append([])
                if part:
                    lines[-1].append((part, sid))
        if lists:
            types = n.get("lineTypes") or []
            out, cur = [], None
            for k, segs in enumerate(lines):
                lt = types[k] if k < len(types) else "NONE"
                body = "".join(span(t, s) for t, s in segs)
                if lt in ("ORDERED", "UNORDERED"):
                    tg = "ol" if lt == "ORDERED" else "ul"
                    if cur != tg:
                        if cur:
                            out.append(f"</{cur}>")
                        out.append(f'<{tg} class="{cls}-list">')
                        cur = tg
                    out.append(f"<li>{body}</li>")
                else:
                    if cur:
                        out.append(f"</{cur}>")
                        cur = None
                    out.append(f'<span class="{cls}-line">{body or "&#8203;"}</span>')
            if cur:
                out.append(f"</{cur}>")
            self.rule(cls + "-list", {"margin": "0", "padding-left": "1.4em", "white-space": "normal"})
            self.rule(cls + "-line", {"display": "block"})
            return "".join(out)
        ps = float(base.get("paragraphSpacing") or 0)
        if ps > 0 and len(lines) > 1:
            self.rule(cls + "-p", {"display": "block"})
            self.rule(f".{cls}-p + .{cls}-p", {"margin-top": px(ps)})
            return "".join(f'<span class="{cls}-p">{"".join(span(t, s) for t, s in segs) or "&#8203;"}</span>' for segs in lines)
        return "".join(span(t, s) for t, s in runs)

    # ---------------------------------------------------------------- the page
    def page(self, title=None, origin_info=None):
        r = self.root
        rx, ry, W, H = bbox(r)
        cls = self.name(r, "page")
        auto = r.get("layoutMode") in ("HORIZONTAL", "VERTICAL")
        css = {"position": "relative", "width": px(W), "margin": "0 auto"}
        if auto:
            css.update(flex_container(r))
            css["min-height"] = px(H)
        else:
            css["height"] = px(H)
        css.update(self.paint(r, W, H))
        css.update(radius(r))
        if r.get("clipsContent", True):
            css["overflow"] = "hidden"
        self.decorate(r, css)
        self.record(cls, r)
        self.rule(cls, css)
        kids = [k for k in r.get("children") or [] if k.get("visible", True)]
        sub = dict(origin=(rx, ry), flex=r if auto else None, rotated=False, depth=1, phrasing=False)
        body = self.children(r, kids, sub, "    ")
        solid = [p for p in visible(r.get("fills")) if p.get("type") == "SOLID"]
        bg = rgba(solid[-1]["color"], solid[-1].get("opacity", 1)) if solid else "#ffffff"
        name = title or r.get("name") or "Page"
        page_html = "\n".join(["<!doctype html>", '<html lang="en">', "<head>", '  <meta charset="utf-8">',
                               '  <meta name="viewport" content="width=device-width, initial-scale=1">', f"  <title>{html.escape(name)}</title>",
                               '  <link rel="stylesheet" href="styles.css">', "</head>", "<body>", f'  <main class="{cls}">', *body, "  </main>",
                               "</body>", "</html>", ""])
        base = [("*, *::before, *::after", {"box-sizing": "border-box"}), ("html, body", {"margin": "0", "padding": "0"}),
                ("body", {"background": bg, "-webkit-font-smoothing": "antialiased", "text-rendering": "geometricPrecision"}),
                ("h1, h2, h3, h4, h5, h6, p, ul, ol, figure", {"margin": "0"}), ("img, svg", {"display": "block"}),
                ("button", {"border": "0", "margin": "0", "padding": "0", "background": "none", "font": "inherit", "color": "inherit",
                            "text-align": "inherit", "cursor": "pointer"}),
                ("a", {"color": "inherit", "text-decoration": "none"})]
        css_text = "\n".join(f"{sel} {{\n" + "".join(f"  {k}: {v};\n" for k, v in props.items()) + "}\n" for sel, props in base + [r for r in self.rules if r])
        return Page(title=name, w=W, h=H, html=page_html, css=css_text, assets=self.assets, elements=self.elements, notes=self.notes,
                    fonts=self.fonts, root=cls, source=self.source, origin_info=origin_info or {})


def build(doc, node_id=None, images=None, source="figma", title=None, origin_info=None):
    """doc: a Figma file (its JSON) or a node tree of the same shape. node_id: the frame (or a page: its first frame)."""
    top = doc.get("document") or doc
    root = find(top, node_id) if node_id else None
    if root is None:
        if node_id:
            raise ValueError(f"no node {node_id} in the design")
        root = top
    while root.get("type") in ("DOCUMENT", "CANVAS"):
        kids = [k for k in root.get("children") or [] if k.get("visible", True) and k.get("type") not in ("SLICE",)]
        if not kids:
            raise ValueError("the page has no frames")
        frames = [k for k in kids if k.get("type") in CONTAINERS] or kids
        root = frames[0]
    return Build(root, images, source).page(title, origin_info)


def image_refs(node):
    """Every picture a frame uses (imageRef), so only those are fetched."""
    refs = set()
    for n in walk(node):
        for p in visible(n.get("fills")) + visible(n.get("strokes")):
            if p.get("type") == "IMAGE" and p.get("imageRef"):
                refs.add(p["imageRef"])
    return refs


# ---------------------------------------------------------------- fonts (free Google fonts saved into the project)
def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def google_fonts(fonts, folder, fetch=_get):
    """@font-face CSS for the families Google Fonts has, with their files saved in folder/assets/fonts (latin and latin-ext);
    -> (css, saved families, families left to the PC's own fonts)."""
    folder = Path(folder)
    out, saved, missing = [], [], []
    for fam, combos in sorted(fonts.items()):
        if not fam or fam.lower() in SYSTEM_FONTS:
            continue
        combos = sorted({(w, it) for w, it in combos}, key=lambda c: (c[1], c[0]))  # Google wants them by italic, then weight
        css = None
        q = "family=" + urllib.parse.quote(fam).replace("%20", "+")
        want = q + ":ital,wght@" + ";".join(f"{int(it)},{w}" for w, it in combos) + "&display=swap"
        try:
            css = _cached_css("https://fonts.googleapis.com/css2?" + want, fetch)
        except (urllib.error.URLError, OSError, ValueError):
            parts = []
            for w, it in combos:  # one weight the family lacks spoils the whole request: ask for each alone
                try:
                    parts.append(_cached_css("https://fonts.googleapis.com/css2?" + q + f":ital,wght@{int(it)},{w}&display=swap", fetch))
                except (urllib.error.URLError, OSError, ValueError):
                    continue
            css = "\n".join(parts) if parts else None
        if not css:
            missing.append(fam)
            continue
        blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", css, re.S) or [("all", b) for b in re.findall(r"@font-face\s*\{.*?\}", css, re.S)]
        keep = [(s, b) for s, b in blocks if s in ("latin", "latin-ext", "all")] or blocks
        dest = folder / "assets" / "fonts"
        dest.mkdir(parents=True, exist_ok=True)
        done = {}
        for subset, block in keep:
            m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", block)
            if not m:
                continue
            url = m.group(1)
            wt = re.search(r"font-weight:\s*(\d+)", block)
            sty = re.search(r"font-style:\s*(\w+)", block)
            ext = url.rsplit(".", 1)[-1].split("?")[0][:5] or "woff2"
            if url not in done:
                name = f"{slug(fam)}-{wt.group(1) if wt else '400'}{'i' if sty and sty.group(1) == 'italic' else ''}-{subset}.{ext}"
                cache = FONT_CACHE / "files" / (hashlib.sha1(url.encode()).hexdigest() + "." + ext)
                if not cache.exists():
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(fetch(url))
                shutil.copyfile(cache, dest / name)
                done[url] = name
            out.append(block.replace(url, f"assets/fonts/{done[url]}"))
        if done:
            saved.append(fam)
        else:
            missing.append(fam)
    return "\n".join(out), saved, missing


def _cached_css(url, fetch):
    p = FONT_CACHE / "css" / (hashlib.sha1(url.encode()).hexdigest() + ".css")
    if p.exists():
        return p.read_text(encoding="utf-8")
    try:
        css = fetch(url).decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ValueError(f"Google Fonts: {e.code}") from e
    if "@font-face" not in css:
        raise ValueError("Google Fonts sent no fonts")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(css, encoding="utf-8")
    return css
