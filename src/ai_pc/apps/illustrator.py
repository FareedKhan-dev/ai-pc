"""Illustrator by vector files: posters, logos and badges written as layered SVG (each part a named layer when
Illustrator, Inkscape, Affinity Designer or Figma opens it; text stays editable text, shapes stay shapes) plus a print
PDF made by headless Chrome. Checked: every layer is in the file, the SVG parses, and the PDF has one page of the right
size.

  "illustrator poster 1080x1350: title 'Grand Opening' white, subtitle 'Saturday 10 am' yellow, blue background, circle badge 'FREE GIFTS'"
  "illustrator logo 'Khan Electronics' with initials 'KE' green"
"""
import base64
import html
import re
from pathlib import Path
from xml.etree import ElementTree as ET

NAME, LABEL = "illustrator", "Illustrator: layered vector posters and logos (SVG + PDF)"
EXAMPLES = ["illustrator poster 1080x1350: title 'Grand Opening' white, subtitle 'Saturday 10 am' yellow, blue background, circle badge 'FREE GIFTS'",
            "illustrator logo 'Khan Electronics' with initials 'KE' green"]
COLORS = {"white": "#ffffff", "black": "#111111", "red": "#e53935", "yellow": "#fdd835", "gold": "#ffc107", "green": "#2e7d32", "blue": "#1565c0",
          "orange": "#fb8c00", "pink": "#d81b60", "purple": "#6a1b9a", "grey": "#9e9e9e", "navy": "#0d1b4c", "teal": "#00897b"}


def layer(name, inner):
    """An SVG group Illustrator, Inkscape and Affinity open as a named layer."""
    lid = re.sub(r"[^\w-]+", "_", name)
    return (f'<g id="{lid}" data-name="{html.escape(name)}" inkscape:groupmode="layer" inkscape:label="{html.escape(name)}">{inner}</g>')


def svg(w, h, layers):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}">' + "".join(layer(n, i) for n, i in layers) + "</svg>")


def _text(x, y, t, size, color, weight=800, anchor="middle"):
    return (f'<text x="{x}" y="{y}" font-family="Segoe UI, Arial, sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}" '
            f'text-anchor="{anchor}">{html.escape(t)}</text>')


def poster(w, h, title, subtitle="", bg="blue", title_color="white", sub_color="yellow", badge=None, picture=None):
    c = COLORS.get(bg, bg)
    layers = [("Background", f'<rect width="{w}" height="{h}" fill="{c}"/><rect y="{h * 0.72}" width="{w}" height="{h * 0.28}" fill="#000000" opacity="0.18"/>')]
    if picture:
        data = base64.b64encode(Path(picture).read_bytes()).decode()
        mime = "image/png" if picture.lower().endswith(".png") else "image/jpeg"
        layers.append(("Picture", f'<image x="{w * 0.15}" y="{h * 0.08}" width="{w * 0.7}" height="{h * 0.4}" preserveAspectRatio="xMidYMid meet" '
                                  f'xlink:href="data:{mime};base64,{data}"/>'))
    size = min(w * 0.9 / max(4, len(title)) * 1.7, h * 0.11)
    layers.append(("Title", _text(w / 2, h * 0.6, title, round(size), COLORS.get(title_color, title_color))))
    if subtitle:
        layers.append(("Subtitle", _text(w / 2, h * 0.6 + size * 0.95, subtitle, round(size * 0.45), COLORS.get(sub_color, sub_color), 600)))
    if badge:
        r = min(w, h) * 0.12
        cx, cy = w - r * 1.25, r * 1.25
        bsize = min(r * 0.32, 1.5 * r / (0.62 * max(1, len(badge))))  # the text fits inside the circle (a bold letter is about 0.62 em wide)
        layers.append(("Badge", f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{COLORS["red"]}"/>' +
                       _text(cx, cy + bsize * 0.35, badge, round(bsize), "#ffffff", 800)))
    return layers


def logo(name, initials, color):
    c = COLORS.get(color, color)
    return [("Mark", f'<rect x="40" y="40" width="200" height="200" rx="44" fill="{c}"/>' + _text(140, 172, initials, 96, "#ffffff", 900)),
            ("Name", _text(270, 155, name, 64, "#111111", 800, "start"))]


def check(path, names, pdf):
    from pypdf import PdfReader
    root = ET.parse(path).getroot()
    got = [g.get("data-name") for g in root.iter("{http://www.w3.org/2000/svg}g")]
    w, h = float(root.get("width")), float(root.get("height"))
    page = PdfReader(str(pdf)).pages
    pw, ph = float(page[0].mediabox.width), float(page[0].mediabox.height)
    return [("every layer is in the SVG, named", got == names), ("the PDF is one page of the design's shape", len(page) == 1 and abs(pw / ph - w / h) < 0.01)]


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\billustrator\b|\bvector\b|\bsvg\b", c):
        return None
    m = re.search(r"\blogo\s+['\"]([^'\"]+)['\"](?:\s+with\s+initials\s+['\"]([^'\"]+)['\"])?(?:\s+(" + "|".join(COLORS) + r"))?", text, re.I)
    if m:
        name = m.group(1)
        return {"op": "logo", "name": name, "initials": m.group(2) or "".join(w[0] for w in name.split()[:2]).upper(), "color": (m.group(3) or "blue").lower()}
    t = re.search(r"\btitle\s+['\"]([^'\"]+)['\"](?:\s+(" + "|".join(COLORS) + r"))?", text, re.I)
    if not t:
        return None
    s = re.search(r"\bsubtitle\s+['\"]([^'\"]+)['\"](?:\s+(" + "|".join(COLORS) + r"))?", text, re.I)
    bg = re.search(r"\b(" + "|".join(COLORS) + r")\s+background\b", c)
    b = re.search(r"\bbadge\s+['\"]([^'\"]+)['\"]", text, re.I)
    m = re.search(r"\b(\d{3,5})\s*[x×]\s*(\d{3,5})\b", c)
    pic = re.search(r"\b(?:picture|photo|image)\s+(\S+\.(?:png|jpe?g))", text, re.I)
    return {"op": "poster", "size": (int(m.group(1)), int(m.group(2))) if m else (1080, 1350), "title": t.group(1), "title_color": (t.group(2) or "white").lower(),
            "subtitle": s.group(1) if s else "", "sub_color": (s.group(2) or "yellow").lower() if s else "yellow", "bg": bg.group(1) if bg else "blue",
            "badge": b.group(1) if b else None, "picture": find_file(pic.group(1), ctx) if pic else None}


def run(op, ctx):
    out = Path(ctx["out"]) / "illustrator"
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "logo":
        w, h = 300 + len(op["name"]) * 38, 280
        layers = logo(op["name"], op["initials"], op["color"])
        stem = re.sub(r"[^\w-]+", "_", op["name"])
    else:
        w, h = op["size"]
        layers = poster(w, h, op["title"], op["subtitle"], op["bg"], op["title_color"], op["sub_color"], op.get("badge"), op.get("picture"))
        stem = re.sub(r"[^\w-]+", "_", op["title"])
    path = out / f"{stem}.svg"
    path.write_text(svg(w, h, layers), encoding="utf-8")
    page = out / f"{stem}.print.html"
    page.write_text(f"<!doctype html><html><head><style>@page{{size:{w}px {h}px;margin:0}}html,body{{margin:0;height:{h}px;overflow:hidden}}svg{{display:block}}</style>"
                    f"</head><body>{path.read_text(encoding='utf-8').split('?>', 1)[1]}"
                    "</body></html>", encoding="utf-8")
    from ai_pc.core import headless
    pdf = out / f"{stem}.pdf"
    headless.pdf(page, pdf, wait_ms=300, lane="apps")
    headless.png(page, out / f"{stem}.png", size=(w, h), wait_ms=300, lane="apps")
    checks = check(path, [n for n, _ in layers], pdf)
    bad = [x for x, ok in checks if not ok]
    return (f"Vector {'logo' if op['op'] == 'logo' else 'poster'} with {len(layers)} layers ({', '.join(n for n, _ in layers)}): {path} (opens in Illustrator, Inkscape, "
            f"Affinity, Figma with editable text), {pdf.name} for print, {stem}.png preview. " +
            ("Checked: " + "; ".join(x for x, _ in checks) if not bad else "NOT right: " + "; ".join(bad)) + ".")
