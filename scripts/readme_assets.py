"""Builds the README's pictures from the logos in docs/assets/logos/ (where each came from: SOURCES.md there).

  docs/assets/hero-light.png, hero-dark.png   the models in the middle, every program and service on the orbits around
  docs/assets/tiles/<name>.png                each logo on a white rounded tile, readable on light and dark pages
  docs/assets/gallery/<name>.png              each command bar picture in docs/assets/screens/ on a card

  .venv\\Scripts\\python.exe scripts\\readme_assets.py [tiles] [hero] [gallery]

Everything is drawn as HTML by the hidden headless browser (ai_pc.core.headless), so nothing opens on screen.
"""

import base64
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from ai_pc.core import headless
from ai_pc.core.paths import ROOT

ASSETS = ROOT / "docs" / "assets"
LOGOS = ASSETS / "logos"
W, H = 1600, 960  # CSS pixels
CX, CY = 800, 480
HUB = 124  # radius of the circle holding the models
SCALE = 1.25  # 2000 px wide: sharp at the width GitHub shows a README

# the model families in the middle, with a size factor (solid letter marks look bigger, so smaller)
MODELS = {"glm": 0.8, "qwen": 1.0, "deepseek": 1.0, "kimi": 0.8, "llama": 1.0, "mistral": 0.9, "gemini": 0.95, "openai": 0.86}
# logos that name providers only (shown in the README's provider table, not on the hero)
PROVIDERS = {
    "nebius", "groq", "together", "fireworks", "deepinfra", "openrouter", "huggingface", "alibabacloud", "moonshot", "xai", "cerebras",
    "sambanova", "nvidia", "novita", "cohere", "siliconflow", "ollama", "lmstudio", "vllm", "llamacpp",
}  # fmt: skip
# the orbits, from the middle out: (logos, x radius, y radius, tile size, corner radius, first angle)
RINGS = [
    (["word", "excel", "powerpoint", "capcut", "blender", "photoshop", "vscode", "autocad", "premiere", "kicad", "figma", "gimp"],
     285, 215, 68, "19px", -75),
    (["illustrator", "aftereffects", "lightroom", "davinci", "jianying", "audacity", "obs", "musescore", "freecad", "qgis", "krita",
      "prusaslicer", "libreoffice", "unity", "godot", "drawio", "outlook", "teams", "slack", "chrome"],
     452, 306, 56, "15px", -84),
    (["python", "nodejs", "typescript", "java", "cplusplus", "dotnet", "go", "rust", "php", "flutter", "android", "androidstudio",
      "intellij", "pycharm", "visualstudio", "git", "github", "docker", "jupyter", "postgresql", "mysql", "mongodb", "sqlite", "r",
      "octave", "powerbi", "access", "onenote"],
     612, 381, 46, "50%", -90),
    (["facebook", "instagram", "threads", "youtube", "tiktok", "linkedin", "x", "whatsapp", "telegram", "gmail", "gdrive", "gcalendar",
      "gdocs", "gsheets", "gslides", "gforms", "onedrive", "trello", "asana", "notion", "jira", "hubspot", "zoom", "shopify",
      "woocommerce", "wordpress", "odoo", "mailchimp", "brevo", "dropbox", "discord", "spotify", "salesforce", "xero", "zoho",
      "quickbooks"],
     752, 446, 38, "50%", -95),
]  # fmt: skip
CORNERS = [
    "shotcut", "handbrake", "ffmpeg", "lmms", "openscad", "rawtherapee", "calibre", "keepassxc", "7zip", "autohotkey", "windows",
    "vlc", "obsidian", "anki", "postman", "revit", "webstorm", "clion", "goland", "rider", "phpstorm", "arduino",
]  # fmt: skip
CORNER_SIZE = 34

THEMES = {
    "light": {
        "bg": "radial-gradient(ellipse 72% 78% at 50% 50%, #ffffff 0%, #f6f5ff 46%, #e9ebfb 100%)",
        "glow": ("#6366f1", 0.20),
        "stars": ("#6366f1", 0.10, 0.28),
        "orbit": "rgba(99,102,241,.24)",
        "spoke": "#6366f1",
        "link": "rgba(99,102,241,.22)",
        "frame": "rgba(79,70,229,.16)",
        "tile_shadow": "0 1px 2px rgba(15,23,42,.06), 0 6px 18px rgba(15,23,42,.10)",
        "tile_border": "rgba(15,23,42,.07)",
        "hub_glow": "0 0 0 12px rgba(99,102,241,.08), 0 0 0 28px rgba(99,102,241,.045), 0 22px 70px rgba(79,70,229,.30)",
    },
    "dark": {
        "bg": "radial-gradient(ellipse 72% 78% at 50% 50%, #1a2152 0%, #0f1533 48%, #080b19 100%)",
        "glow": ("#818cf8", 0.38),
        "stars": ("#e0e7ff", 0.18, 0.62),
        "orbit": "rgba(165,180,252,.26)",
        "spoke": "#a5b4fc",
        "link": "rgba(165,180,252,.20)",
        "frame": "rgba(129,140,248,.24)",
        "tile_shadow": "0 1px 2px rgba(0,0,0,.35), 0 8px 22px rgba(0,0,0,.5)",
        "tile_border": "rgba(255,255,255,.12)",
        "hub_glow": "0 0 0 12px rgba(129,140,248,.12), 0 0 0 28px rgba(129,140,248,.06), 0 0 90px rgba(129,140,248,.45)",
    },
}


def on_ring(names, rx, ry, start):
    step = 360 / len(names)
    return [(n, CX + rx * math.cos(math.radians(start + i * step)), CY + ry * math.sin(math.radians(start + i * step))) for i, n in enumerate(names)]


def corner_spots(placed, n, size):
    """n places in the canvas corners, clear of the outer orbit and of each other, spread as far apart as possible."""
    rx, ry = RINGS[-1][1] + 34, RINGS[-1][2] + 30
    m = size / 2 + 16
    cands = [
        (x, y)
        for x in range(int(m), int(W - m) + 1, 6)
        for y in range(int(m), int(H - m) + 1, 6)
        if ((x - CX) / rx) ** 2 + ((y - CY) / ry) ** 2 > 1 and all(math.hypot(x - px, y - py) > (size + ps) / 2 + 18 for px, py, ps in placed)
    ]
    chosen = []
    while len(chosen) < n and cands:
        if not chosen:  # start from the top-left corner
            best = min(cands, key=lambda c: c[0] + c[1])
        else:
            best = max(cands, key=lambda c: min(math.hypot(c[0] - x, c[1] - y) for x, y in chosen))
        chosen.append(best)
        cands = [c for c in cands if math.hypot(c[0] - best[0], c[1] - best[1]) > size + 22]
    if len(chosen) < n:
        raise SystemExit(f"only {len(chosen)} of {n} corner places fit")
    # read the corners clockwise from the top left, so neighbours in the list sit near each other
    return sorted(chosen, key=lambda c: (math.atan2(c[1] - CY, c[0] - CX) + math.pi * 0.75) % (2 * math.pi))


def spark(size, color_a, color_b):
    """The AI PC spark (the command bar's and tray icon's shape)."""
    c, big, small = size / 2, size * 0.46, size * 0.11
    pts = [
        (c, c - big),
        (c + small, c - small),
        (c + big, c),
        (c + small, c + small),
        (c, c + big),
        (c - small, c + small),
        (c - big, c),
        (c - small, c - small),
    ]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}"><defs><linearGradient id="sp" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{color_a}"/><stop offset="1" stop-color="{color_b}"/></linearGradient></defs>'
        f'<polygon points="{poly}" fill="url(#sp)"/></svg>'
    )


def tile(name, x, y, size, radius, t, opacity=1.0):
    pad = round(size * 0.17)
    return (
        f'<div class="tile" style="left:{x - size / 2:.1f}px;top:{y - size / 2:.1f}px;width:{size}px;height:{size}px;border-radius:{radius};'
        f'padding:{pad}px;opacity:{opacity};box-shadow:{t["tile_shadow"]};border:1px solid {t["tile_border"]}">'
        f'<img src="logos/{name}.png"></div>'
    )


def curve(x0, y0, x1, y1, bend):
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    return f"M{x0:.1f},{y0:.1f} Q{mx - dy * bend:.1f},{my + dx * bend:.1f} {x1:.1f},{y1:.1f}"


def hero_html(theme):
    t = THEMES[theme]
    rings = [on_ring(names, rx, ry, start) for names, rx, ry, *_rest, start in RINGS]
    placed = [(x, y, spec[3]) for ring, spec in zip(rings, RINGS) for _, x, y in ring]
    corners = list(zip(CORNERS, corner_spots(placed, len(CORNERS), CORNER_SIZE)))
    svg = []
    gc, go = t["glow"]
    svg.append(
        f'<radialGradient id="glow"><stop offset="0" stop-color="{gc}" stop-opacity="{go}"/><stop offset="1" stop-color="{gc}" stop-opacity="0"/>'
        f'</radialGradient><ellipse cx="{CX}" cy="{CY}" rx="520" ry="380" fill="url(#glow)"/>'
    )
    rnd = random.Random(7)  # the same stars every time
    sc, lo, hi = t["stars"]
    for _ in range(170):
        svg.append(
            f'<circle cx="{rnd.uniform(0, W):.1f}" cy="{rnd.uniform(0, H):.1f}" r="{rnd.uniform(0.5, 1.5):.2f}" fill="{sc}" '
            f'fill-opacity="{rnd.uniform(lo, hi):.2f}"/>'
        )
    for names, rx, ry, *_ in RINGS:
        svg.append(
            f'<ellipse cx="{CX}" cy="{CY}" rx="{rx}" ry="{ry}" fill="none" stroke="{t["orbit"]}" stroke-width="1.2" stroke-dasharray="1.5 7"/>'
        )
    # every second-orbit logo is linked to its nearest first-orbit logo, faintly
    for _, x, y in rings[1]:
        _, nx, ny = min(rings[0], key=lambda r: math.hypot(r[1] - x, r[2] - y))
        svg.append(f'<path d="{curve(nx, ny, x, y, 0.12)}" fill="none" stroke="{t["link"]}" stroke-width="1.3"/>')
    # the models reach every first-orbit logo
    size0 = RINGS[0][3]
    for i, (_, x, y) in enumerate(rings[0]):
        d = math.hypot(x - CX, y - CY)
        ux, uy = (x - CX) / d, (y - CY) / d
        x0, y0, x1, y1 = CX + ux * (HUB + 6), CY + uy * (HUB + 6), x - ux * (size0 / 2 + 8), y - uy * (size0 / 2 + 8)
        svg.append(
            f'<linearGradient id="s{i}" gradientUnits="userSpaceOnUse" x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}">'
            f'<stop offset="0" stop-color="{t["spoke"]}" stop-opacity=".95"/><stop offset="1" stop-color="{t["spoke"]}" stop-opacity=".4"/>'
            f'</linearGradient><path d="{curve(x0, y0, x1, y1, 0.1 if i % 2 else -0.1)}" fill="none" stroke="url(#s{i})" stroke-width="2.4" '
            f'stroke-linecap="round"/><circle cx="{x1:.1f}" cy="{y1:.1f}" r="3.4" fill="{t["spoke"]}"/>'
        )
    tiles = []
    for ring, (names, rx, ry, size, radius, _) in zip(rings, RINGS):
        fade = 1.0 if size >= 56 else 0.96
        tiles += [tile(n, x, y, size, radius, t, fade) for n, x, y in ring]
    tiles += [tile(n, x, y, CORNER_SIZE, "50%", t, 0.92) for n, (x, y) in corners]
    k = len(MODELS)
    models = "".join(
        f'<img src="logos/{m}.png" style="left:{HUB + 84 * math.cos(math.radians(-90 + i * 360 / k)) - 20:.1f}px;'
        f'top:{HUB + 84 * math.sin(math.radians(-90 + i * 360 / k)) - 20:.1f}px;transform:scale({f})">'
        for i, (m, f) in enumerate(MODELS.items())
    )
    return f"""<!doctype html><meta charset="utf-8">
<style>
html, body {{ margin: 0; background: transparent; }}
.frame {{ position: relative; width: {W}px; height: {H}px; overflow: hidden; border-radius: 30px; background: {t["bg"]};
          box-shadow: inset 0 0 0 1px {t["frame"]}; }}
svg.bg {{ position: absolute; inset: 0; }}
.tile {{ position: absolute; box-sizing: border-box; background: #ffffff; display: flex; align-items: center; justify-content: center; }}
.tile img {{ width: 100%; height: 100%; object-fit: contain; }}
.hub {{ position: absolute; left: {CX - HUB}px; top: {CY - HUB}px; width: {2 * HUB}px; height: {2 * HUB}px; border-radius: 50%;
        background: radial-gradient(circle at 38% 30%, #ffffff 0%, #ffffff 58%, #f1f0ff 100%); box-shadow: {t["hub_glow"]}; }}
.hub img {{ position: absolute; width: 40px; height: 40px; object-fit: contain; }}
.hub .spark {{ position: absolute; left: {HUB - 37}px; top: {HUB - 37}px; }}
</style>
<div class="frame">
<svg class="bg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">{"".join(svg)}</svg>
{"".join(tiles)}
<div class="hub"><div class="spark">{spark(74, "#6366f1", "#a855f7")}</div>{models}</div>
</div>"""


def check_coverage():
    """Every program logo is on the hero once; model and provider logos are not."""
    on_hero = [n for names, *_ in RINGS for n in names] + CORNERS
    dupes = {n for n in on_hero if on_hero.count(n) > 1}
    programs = {p.stem for p in LOGOS.glob("*.png")} - set(MODELS) - PROVIDERS
    missing, unknown = programs - set(on_hero), set(on_hero) - programs
    if dupes or missing or unknown:
        raise SystemExit(f"hero logos: duplicated {sorted(dupes)}, missing {sorted(missing)}, no such logo {sorted(unknown)}")
    return len(on_hero)


def render(html, out, size, scale):
    page = ASSETS / f".{out.stem}.html"
    page.write_text(html, encoding="utf-8")
    out.unlink(missing_ok=True)
    try:
        headless._run(
            [
                f"--screenshot={out}",
                f"--window-size={size[0]},{size[1]}",
                f"--force-device-scale-factor={scale}",
                "--virtual-time-budget=2500",
                "--default-background-color=00000000",
            ],
            page.resolve().as_uri(),
        )
    finally:
        page.unlink(missing_ok=True)
    im = Image.open(out)
    im.save(out, optimize=True)
    print(f"{out.relative_to(ROOT)}  {im.size[0]}x{im.size[1]}  {out.stat().st_size // 1024} KB")


def build_hero():
    n = check_coverage()
    print(f"hero: {n} programs and services, {len(MODELS)} model families")
    for theme in THEMES:
        render(hero_html(theme), ASSETS / f"hero-{theme}.png", (W, H), SCALE)


def build_tiles(size=128, radius=30, logo=88):
    """Each logo centred on a white rounded square with a faint edge (drawn 4x larger, then reduced for smooth corners)."""
    folder = ASSETS / "tiles"
    folder.mkdir(exist_ok=True)
    big = size * 4
    base = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle((2, 2, big - 3, big - 3), radius * 4, fill=(255, 255, 255, 255), outline=(15, 23, 42, 34), width=6)
    base = base.resize((size, size), Image.LANCZOS)
    for f in sorted(LOGOS.glob("*.png")):
        mark = Image.open(f).convert("RGBA")
        mark.thumbnail((logo, logo), Image.LANCZOS)
        t = base.copy()
        t.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
        t.save(folder / f.name, optimize=True)
    print(f"{folder.relative_to(ROOT)}  {len(list(folder.glob('*.png')))} tiles")


# ---------------------------------------------------------------- the gallery of command bar pictures
# picture in docs/assets/screens -> (logo, program, what was asked, card colours)
GALLERY = {
    "demo-word": ("word", "Microsoft Word", "leave application to my principal for 3 days, fever, Fatima Noor class 9-B", ("#1e40af", "#3b82f6")),
    "demo-powerpoint": ("powerpoint", "Microsoft PowerPoint", "a 10 slide presentation for homeowners on going solar", ("#9a3412", "#f97316")),
    "demo-excel": ("excel", "Microsoft Excel", "marks sheet in Excel for 8 students with totals, grades and a class summary", ("#14532d", "#22c55e")),
    "demo-autocad": ("autocad", "AutoCAD drawing", "a 10 marla house with 3 bedrooms", ("#7f1d1d", "#ef4444")),
    "demo-blender": ("blender", "Blender", "a 3D intro for Khan Electronics in gold", ("#7c2d12", "#f59e0b")),
    "demo-design": ("aipc", "Design", "an instagram post for Khan Motors 'Eid Sale' 20% off 1-15 June, shop now", ("#4c1d95", "#a855f7")),
    "demo-video": ("ffmpeg", "Video with FFmpeg", "make it under 5 MB for whatsapp", ("#0f172a", "#14b8a6")),
    "bar-reply-dark": ("aipc", "Photos", "make it brighter", ("#0c4a6e", "#38bdf8")),
    "bar-confirm-dark": ("slack", "Slack", "send it to slack #general", ("#3f0f40", "#e01e5a")),
}
CARD_W, CARD_H = 1000, 860


def data_uri(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def card_html(screen, logo, program, asked, colours):
    a, b = colours
    with Image.open(screen) as im:
        sw, sh = im.size
    k = min(1.0, (CARD_W - 120) / sw, (CARD_H - 250) / sh)
    # AI PC's own work (photos, designs) carries its spark; a program's work carries that program's logo
    mark = spark(64, "#6366f1", "#a855f7") if logo == "aipc" else f'<img src="{data_uri(LOGOS / (logo + ".png"))}">'
    return f"""<!doctype html><meta charset="utf-8">
<style>
html, body {{ margin: 0; background: transparent; }}
.card {{ position: relative; width: {CARD_W}px; height: {CARD_H}px; border-radius: 28px; overflow: hidden;
         background: radial-gradient(ellipse 90% 70% at 15% 0%, {b} 0%, {a} 62%, #0b1020 100%); font-family: "Segoe UI Variable Display", "Segoe UI", sans-serif; }}
.card::after {{ content: ""; position: absolute; inset: 0; background-image: radial-gradient(rgba(255,255,255,.08) 1px, transparent 1.4px);
                background-size: 20px 20px; }}
.head {{ position: absolute; left: 56px; top: 44px; right: 56px; display: flex; align-items: center; gap: 22px; z-index: 2; }}
.logo {{ width: 92px; height: 92px; border-radius: 24px; background: #fff; display: flex; align-items: center; justify-content: center;
         box-shadow: 0 10px 30px rgba(0,0,0,.35); flex: none; }}
.logo img, .logo svg {{ width: 64px; height: 64px; object-fit: contain; }}
.prog {{ color: #fff; font-size: 48px; font-weight: 700; letter-spacing: .01em; line-height: 1.05; }}
.asked {{ color: rgba(255,255,255,.88); font-size: 27px; margin-top: 6px; line-height: 1.25; max-width: 790px; }}
.shot {{ position: absolute; left: 50%; top: 214px; transform: translateX(-50%); z-index: 2; border-radius: 14px; overflow: hidden;
         box-shadow: 0 30px 80px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.14); }}
.shot img {{ display: block; width: {sw * k:.0f}px; height: {sh * k:.0f}px; }}
</style>
<div class="card">
  <div class="head"><div class="logo">{mark}</div>
    <div><div class="prog">{program}</div><div class="asked">&ldquo;{asked}&rdquo;</div></div></div>
  <div class="shot"><img src="{data_uri(screen)}"></div>
</div>"""


def build_gallery():
    folder = ASSETS / "gallery"
    folder.mkdir(exist_ok=True)
    for name, (logo, program, asked, colours) in GALLERY.items():
        screen = ASSETS / "screens" / f"{name}.png"
        if screen.is_file():
            render(card_html(screen, logo, program, asked, colours), folder / f"{name.replace('-dark', '')}.png", (CARD_W, CARD_H), 1)


if __name__ == "__main__":
    jobs = sys.argv[1:] or ["tiles", "hero", "gallery"]
    if "tiles" in jobs:
        build_tiles()
    if "hero" in jobs:
        build_hero()
    if "gallery" in jobs:
        build_gallery()
