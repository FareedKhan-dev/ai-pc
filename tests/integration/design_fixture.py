"""A landing page in exactly the shape Figma's REST API describes a frame (GET /v1/files/:key?geometry=paths), with every
box worked out by hand from Figma's own layout rules, so a converted page can be measured against it. It has what real
designs have: auto layout (space-between, gaps, padding, fill / hug / fixed children), a picture fill under a see-through
overlay, mixed text styles, a list, a link, a gradient button, a turned badge, a turned icon, a mask, a line, shadows,
borders and rounded corners. Fonts: Poppins (a Google font, saved into the project) and Arial (on every Windows PC).
"""

import math
from pathlib import Path

RX, RY = 100.0, 200.0  # where the frame sits on Figma's canvas (pages are never at 0, 0)


def _hex(h, a=1.0):
    h = h.lstrip("#")
    return {"r": int(h[0:2], 16) / 255, "g": int(h[2:4], 16) / 255, "b": int(h[4:6], 16) / 255, "a": a}


def solid(h, opacity=None):
    p = {"type": "SOLID", "visible": True, "color": _hex(h)}
    if opacity is not None:
        p["opacity"] = opacity
    return p


def node(nid, name, kind, x, y, w, h, **kw):
    n = {
        "id": nid,
        "name": name,
        "type": kind,
        "visible": True,
        "absoluteBoundingBox": {"x": RX + x, "y": RY + y, "width": w, "height": h},
        "size": {"x": w, "y": h},
        "fills": [],
        "strokes": [],
        "effects": [],
    }
    n.update(kw)
    return n


def text(
    nid,
    name,
    chars,
    x,
    y,
    w,
    h,
    family="Arial",
    size=16,
    weight=400,
    lh=24,
    color="#000000",
    align="LEFT",
    auto="HEIGHT",
    sizing=("FIXED", "HUG"),
    **kw,
):
    st = {
        "fontFamily": family,
        "fontPostScriptName": None,
        "fontWeight": weight,
        "fontSize": size,
        "textAlignHorizontal": align,
        "textAlignVertical": kw.pop("valign", "TOP"),
        "letterSpacing": kw.pop("letter", 0),
        "lineHeightPx": lh,
        "lineHeightUnit": "PIXELS",
        "textAutoResize": auto,
    }
    st.update(kw.pop("style", {}))
    return node(
        nid,
        name,
        "TEXT",
        x,
        y,
        w,
        h,
        characters=chars,
        style=st,
        fills=[solid(color)],
        layoutSizingHorizontal=sizing[0],
        layoutSizingVertical=sizing[1],
        characterStyleOverrides=kw.pop("overrides", []),
        styleOverrideTable=kw.pop("table", {}),
        **kw,
    )


def turned(n, deg, cx, cy, parent_xy):
    """Turn a node by deg (Figma's way: anticlockwise on screen) about its centre (cx, cy) on the page."""
    w, h = n["size"]["x"], n["size"]["y"]
    t = math.radians(deg)
    a, b, c, d = math.cos(t), -math.sin(t), math.sin(t), math.cos(t)
    xs = [a * u + c * v for u, v in ((0, 0), (w, 0), (0, h), (w, h))]
    ys = [b * u + d * v for u, v in ((0, 0), (w, 0), (0, h), (w, h))]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    n["absoluteBoundingBox"] = {"x": RX + cx - bw / 2, "y": RY + cy - bh / 2, "width": bw, "height": bh}
    lx, ly = cx - parent_xy[0], cy - parent_xy[1]
    n["relativeTransform"] = [[a, c, lx - (a * w / 2 + c * h / 2)], [b, d, ly - (b * w / 2 + d * h / 2)]]
    return n


CHECK = "M9 16.17L4.83 12L3.41 13.41L9 19L21 7L19.59 5.59L9 16.17Z"
STAR = "M20 0L25 15L40 20L25 25L20 40L15 25L0 20L15 15Z"
CARDS = [
    ("Genuine products", "Original phones and laptops from trusted brands, with a proper bill."),
    ("Fast delivery", "Free delivery anywhere in Lahore within two working days of ordering."),
    ("Easy instalments", "Pay in easy monthly instalments with no hidden charges or extra fees."),
]


def landing():
    """-> the file JSON (as Figma's API returns it) and the frame's id."""
    nav = node(
        "1:1",
        "Navbar",
        "FRAME",
        0,
        0,
        1440,
        80,
        fills=[solid("#0F172A")],
        layoutMode="HORIZONTAL",
        primaryAxisAlignItems="SPACE_BETWEEN",
        counterAxisAlignItems="CENTER",
        paddingLeft=80,
        paddingRight=80,
        paddingTop=0,
        paddingBottom=0,
        itemSpacing=0,
        primaryAxisSizingMode="FIXED",
        counterAxisSizingMode="FIXED",
        layoutSizingHorizontal="FIXED",
        layoutSizingVertical="FIXED",
        children=[
            text("1:2", "Logo", "Khan Electronics", 80, 24, 260, 32, family="Poppins", size=24, weight=700, lh=32, color="#FFFFFF"),
            node(
                "1:3",
                "Links",
                "FRAME",
                630,
                28,
                320,
                24,
                layoutMode="HORIZONTAL",
                itemSpacing=32,
                counterAxisAlignItems="CENTER",
                primaryAxisSizingMode="FIXED",
                counterAxisSizingMode="AUTO",
                layoutSizingHorizontal="FIXED",
                layoutSizingVertical="HUG",
                children=[
                    text("1:4", "Home", "Home", 630, 28, 56, 24, color="#CBD5E1", weight=500),
                    text("1:5", "Products", "Products", 718, 28, 88, 24, color="#CBD5E1", weight=500),
                    text("1:6", "Contact", "Contact", 838, 28, 72, 24, color="#CBD5E1", weight=500),
                ],
            ),
            node(
                "1:7",
                "Call button",
                "FRAME",
                1240,
                16,
                120,
                48,
                layoutMode="HORIZONTAL",
                paddingLeft=24,
                paddingRight=24,
                paddingTop=12,
                paddingBottom=12,
                itemSpacing=8,
                primaryAxisSizingMode="AUTO",
                counterAxisSizingMode="AUTO",
                layoutSizingHorizontal="HUG",
                layoutSizingVertical="HUG",
                cornerRadius=8,
                fills=[
                    {
                        "type": "GRADIENT_LINEAR",
                        "visible": True,
                        "gradientHandlePositions": [{"x": 0, "y": 0.5}, {"x": 1, "y": 0.5}, {"x": 0, "y": 1}],
                        "gradientStops": [{"color": _hex("#2563EB"), "position": 0}, {"color": _hex("#7C3AED"), "position": 1}],
                    }
                ],
                children=[text("1:8", "Call now", "Call now", 1264, 28, 72, 24, weight=700, color="#FFFFFF", align="CENTER")],
            ),
        ],
    )
    hero = node(
        "2:1",
        "Hero",
        "FRAME",
        0,
        80,
        1440,
        560,
        clipsContent=True,
        fills=[{"type": "IMAGE", "visible": True, "scaleMode": "FILL", "imageRef": "hero-photo"}],
        children=[
            node("2:2", "Overlay", "RECTANGLE", 0, 80, 1440, 560, fills=[solid("#000000", 0.45)]),
            text(
                "2:3",
                "Title",
                "Best prices in town",
                360,
                260,
                720,
                68,
                family="Poppins",
                size=56,
                weight=700,
                lh=68,
                color="#FFFFFF",
                align="CENTER",
            ),
            text(
                "2:4",
                "Subtitle",
                "Phones, laptops and TVs with 1 year warranty",
                370,
                348,
                700,
                30,
                size=20,
                lh=30,
                color="#E2E8F0",
                align="CENTER",
                overrides=[0] * 29 + [1] * 15,
                table={"1": {"fontWeight": 700, "fills": [solid("#FBBF24")]}},
            ),
            turned(node("2:5", "Badge", "RECTANGLE", 0, 0, 140, 44, cornerRadius=22, fills=[solid("#F59E0B")]), 15, 1180, 200, (0, 80)),
            turned(
                text(
                    "2:6",
                    "Badge text",
                    "SALE 20% OFF",
                    0,
                    0,
                    140,
                    44,
                    size=18,
                    weight=700,
                    lh=44,
                    color="#FFFFFF",
                    align="CENTER",
                    auto="NONE",
                    valign="CENTER",
                    sizing=("FIXED", "FIXED"),
                ),
                15,
                1180,
                200,
                (0, 80),
            ),
            text(
                "2:7",
                "Promises",
                "Free delivery\nEasy returns\nCash on delivery",
                500,
                420,
                440,
                72,
                color="#FFFFFF",
                lineTypes=["UNORDERED", "UNORDERED", "UNORDERED"],
                lineIndentations=[1, 1, 1],
            ),
            node(
                "2:8",
                "Founder",
                "GROUP",
                80,
                520,
                80,
                80,
                children=[
                    node("2:9", "Circle", "ELLIPSE", 80, 520, 80, 80, isMask=True, fills=[solid("#FFFFFF")]),
                    node(
                        "2:10",
                        "Founder photo",
                        "RECTANGLE",
                        80,
                        520,
                        80,
                        80,
                        fills=[{"type": "IMAGE", "visible": True, "scaleMode": "FILL", "imageRef": "face"}],
                    ),
                ],
            ),
            node(
                "2:11",
                "Divider",
                "LINE",
                80,
                620,
                1280,
                0,
                strokes=[solid("#FFFFFF", 0.3)],
                strokeWeight=1,
                strokeAlign="CENTER",
                relativeTransform=[[1, 0, 80], [0, 1, 540]],
                fillGeometry=[],
                strokeGeometry=[{"path": "M0 -0.5L1280 -0.5L1280 0.5L0 0.5L0 -0.5Z"}],
            ),
        ],
    )
    cards = []
    for i, (title, body) in enumerate(CARDS):
        x = 80 + i * (410.667 + 24)
        k = 3 + i * 4
        cards.append(
            node(
                f"3:{k}",
                "Card",
                "FRAME",
                x,
                704,
                410.667,
                172,
                layoutMode="VERTICAL",
                itemSpacing=12,
                paddingLeft=24,
                paddingRight=24,
                paddingTop=24,
                paddingBottom=24,
                primaryAxisSizingMode="AUTO",
                counterAxisSizingMode="FIXED",
                layoutSizingHorizontal="FILL",
                layoutSizingVertical="HUG",
                cornerRadius=16,
                fills=[solid("#FFFFFF")],
                strokes=[solid("#E2E8F0")],
                strokeWeight=1,
                strokeAlign="INSIDE",
                effects=[
                    {"type": "DROP_SHADOW", "visible": True, "color": _hex("#0F172A", 0.08), "offset": {"x": 0, "y": 4}, "radius": 12, "spread": 0}
                ],
                children=[
                    node(
                        f"3:{k + 1}",
                        "Icon",
                        "VECTOR",
                        x + 24,
                        728,
                        24,
                        24,
                        fills=[solid("#2563EB")],
                        fillGeometry=[{"path": CHECK, "windingRule": "NONZERO"}],
                        strokeGeometry=[],
                        layoutSizingHorizontal="FIXED",
                        layoutSizingVertical="FIXED",
                    ),
                    text(
                        f"3:{k + 2}",
                        "Card title",
                        title,
                        x + 24,
                        764,
                        362.667,
                        28,
                        size=20,
                        weight=700,
                        lh=28,
                        color="#0F172A",
                        sizing=("FILL", "HUG"),
                    ),
                    text(f"3:{k + 3}", "Card text", body, x + 24, 804, 362.667, 48, color="#475569", sizing=("FILL", "HUG")),
                ],
            )
        )
    features = node(
        "3:1",
        "Features",
        "FRAME",
        0,
        640,
        1440,
        300,
        fills=[solid("#F8FAFC")],
        layoutMode="HORIZONTAL",
        itemSpacing=24,
        paddingLeft=80,
        paddingRight=80,
        paddingTop=64,
        paddingBottom=64,
        counterAxisAlignItems="MIN",
        primaryAxisSizingMode="FIXED",
        counterAxisSizingMode="AUTO",
        layoutSizingHorizontal="FIXED",
        layoutSizingVertical="HUG",
        children=cards,
    )
    footer = node(
        "4:1",
        "Footer",
        "FRAME",
        0,
        940,
        1440,
        240,
        fills=[solid("#0F172A")],
        clipsContent=True,
        children=[
            text("4:2", "Copyright", "© 2026 Khan Electronics. All rights reserved.", 80, 1040, 600, 24, size=14, color="#94A3B8"),
            text(
                "4:3",
                "Shop link",
                "Visit our shop",
                80,
                1080,
                200,
                24,
                color="#60A5FA",
                style={"textDecoration": "UNDERLINE", "hyperlink": {"type": "URL", "url": "https://example.com/shop"}},
            ),
            node(
                "4:4",
                "Dot",
                "ELLIPSE",
                1300,
                1020,
                60,
                60,
                fills=[
                    {
                        "type": "GRADIENT_RADIAL",
                        "visible": True,
                        "gradientHandlePositions": [{"x": 0.5, "y": 0.5}, {"x": 1, "y": 0.5}, {"x": 0.5, "y": 1}],
                        "gradientStops": [{"color": _hex("#60A5FA"), "position": 0}, {"color": _hex("#1E3A8A"), "position": 1}],
                    }
                ],
            ),
            turned(
                node(
                    "4:5",
                    "Spark",
                    "VECTOR",
                    0,
                    0,
                    40,
                    40,
                    fills=[solid("#FBBF24")],
                    fillGeometry=[{"path": STAR, "windingRule": "NONZERO"}],
                    strokeGeometry=[],
                ),
                30,
                1240,
                1050,
                (0, 940),
            ),
        ],
    )
    root = node("0:1", "Home", "FRAME", 0, 0, 1440, 1180, fills=[solid("#FFFFFF")], clipsContent=True, children=[nav, hero, features, footer])
    doc = {
        "name": "Khan Electronics site",
        "version": "2001",
        "lastModified": "2026-10-04T08:00:00Z",
        "styles": {},
        "document": {
            "id": "0:0",
            "name": "Document",
            "type": "DOCUMENT",
            "children": [{"id": "0:p", "name": "Page 1", "type": "CANVAS", "children": [root]}],
        },
    }
    return doc, "0:1"


def pictures(folder):
    """The two pictures the design uses (a shop photo and a face), drawn here: {imageRef: file}."""
    from PIL import Image, ImageDraw

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1440, 560))
    d = ImageDraw.Draw(im)
    for yy in range(560):
        d.line([(0, yy), (1440, yy)], fill=(30 + yy // 8, 60 + yy // 10, 110 + yy // 6))
    for i in range(9):
        d.rectangle([60 + i * 155, 300 - (i % 3) * 40, 170 + i * 155, 520], fill=(200 - i * 12, 160 + i * 6, 90 + i * 15))
        d.ellipse([90 + i * 155, 250 - (i % 3) * 40, 140 + i * 155, 300 - (i % 3) * 40], fill=(240, 220 - i * 10, 120))
    hero = folder / "hero.jpg"
    im.save(hero, quality=90)
    f = Image.new("RGB", (160, 160), (235, 200, 170))
    d = ImageDraw.Draw(f)
    d.ellipse([40, 30, 120, 120], fill=(200, 150, 120))
    d.rectangle([20, 120, 140, 160], fill=(40, 70, 140))
    face = folder / "face.png"
    f.save(face)
    return {"hero-photo": str(hero), "face": str(face)}
