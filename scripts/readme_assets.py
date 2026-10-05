"""Builds the README's pictures from the logos in docs/assets/logos/ (where each came from: SOURCES.md there).

  docs/assets/hero-light.png, hero-dark.png   the language models in the middle, joined to the programs around them
  docs/assets/tiles/<name>.png                each logo on a white rounded tile, readable on light and dark pages

  .venv\\Scripts\\python.exe scripts\\readme_assets.py

The hero is an HTML page drawn by the hidden headless browser (ai_pc.core.headless), so nothing opens on screen.
"""

import math

from PIL import Image, ImageDraw

from ai_pc.core import headless
from ai_pc.core.paths import ROOT

ASSETS = ROOT / "docs" / "assets"
LOGOS = ASSETS / "logos"
W, H = 1280, 600  # CSS pixels; drawn at twice that
CX, CY = 640, 290
HUB = 90  # radius of the circle holding the models
SCALE = 1.5  # drawn at 1.5x: 1920 px wide, sharp at the width GitHub shows a README

MODELS = {"glm": 0.78, "qwen": 1.0, "deepseek": 1.0, "kimi": 0.8}  # size in the circle: solid letter marks look bigger, so smaller
# joined to the models: an inner ring and an outer ring, clockwise from the right
INNER = ["blender", "powerpoint", "capcut", "gimp", "excel", "word", "vscode", "kicad"]
OUTER = ["audacity", "musescore", "freecad", "krita", "qgis", "libreoffice", "prusaslicer", "godot"]
# loose around the edges: (logo, x, y)
LOOSE = [
    ("python", 74, 108),
    ("telegram", 182, 46),
    ("nodejs", 60, 470),
    ("postgresql", 300, 300),
    ("rust", 382, 58),
    ("drawio", 392, 548),
    ("r", 146, 556),
    ("octave", 520, 40),
    ("lmms", 772, 562),
    ("openscad", 896, 52),
    ("slack", 892, 552),
    ("rawtherapee", 988, 300),
    ("dotnet", 1118, 40),
    ("calibre", 1206, 112),
    ("mongodb", 1172, 392),
    ("keepassxc", 1220, 482),
    ("handbrake", 1102, 562),
    ("flutter", 108, 372),
]

THEMES = {
    "light": {
        "bg": "radial-gradient(ellipse 70% 80% at 50% 48%, #ffffff 0%, #f5f6ff 50%, #e8ecfb 100%)",
        "dots": "rgba(79,70,229,.10)",
        "frame": "rgba(79,70,229,.16)",
        "orbit": "rgba(79,70,229,.20)",
        "spoke": "#6366f1",
        "tile_shadow": "0 1px 2px rgba(15,23,42,.06), 0 8px 22px rgba(15,23,42,.10)",
        "tile_border": "rgba(15,23,42,.06)",
        "hub_glow": "0 0 0 14px rgba(99,102,241,.07), 0 0 0 30px rgba(99,102,241,.04), 0 20px 60px rgba(79,70,229,.28)",
    },
    "dark": {
        "bg": "radial-gradient(ellipse 70% 80% at 50% 48%, #18204a 0%, #0f1530 50%, #090d1d 100%)",
        "dots": "rgba(165,180,252,.10)",
        "frame": "rgba(129,140,248,.22)",
        "orbit": "rgba(129,140,248,.24)",
        "spoke": "#818cf8",
        "tile_shadow": "0 1px 2px rgba(0,0,0,.3), 0 10px 26px rgba(0,0,0,.45)",
        "tile_border": "rgba(255,255,255,.10)",
        "hub_glow": "0 0 0 14px rgba(129,140,248,.10), 0 0 0 30px rgba(129,140,248,.05), 0 0 70px rgba(129,140,248,.35)",
    },
}


def ring(names, rx, ry, start_deg):
    step = 360 / len(names)
    return [
        (n, CX + rx * math.cos(math.radians(start_deg + i * step)), CY + ry * math.sin(math.radians(start_deg + i * step)))
        for i, n in enumerate(names)
    ]


def spoke(x, y, tile_r, bend, color, i):
    """A gently curved line from the edge of the models' circle to the edge of a tile."""
    dx, dy = x - CX, y - CY
    d = math.hypot(dx, dy)
    ux, uy = dx / d, dy / d
    x0, y0 = CX + ux * (HUB + 6), CY + uy * (HUB + 6)
    x1, y1 = x - ux * (tile_r + 8), y - uy * (tile_r + 8)
    mx, my = (x0 + x1) / 2 - uy * bend * (d - HUB), (y0 + y1) / 2 + ux * bend * (d - HUB)
    return (
        f'<linearGradient id="g{i}" gradientUnits="userSpaceOnUse" x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}">'
        f'<stop offset="0" stop-color="{color}" stop-opacity=".9"/><stop offset="1" stop-color="{color}" stop-opacity=".35"/></linearGradient>'
        f'<path d="M{x0:.1f},{y0:.1f} Q{mx:.1f},{my:.1f} {x1:.1f},{y1:.1f}" fill="none" stroke="url(#g{i})" stroke-width="2.2" stroke-linecap="round"/>'
        f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="3.2" fill="{color}" fill-opacity=".7"/>'
    )


def tile(name, x, y, size, radius, t, opacity=1.0):
    pad = round(size * 0.16)
    return (
        f'<div class="tile" style="left:{x - size / 2:.1f}px;top:{y - size / 2:.1f}px;width:{size}px;height:{size}px;border-radius:{radius};'
        f'padding:{pad}px;opacity:{opacity};box-shadow:{t["tile_shadow"]};border:1px solid {t["tile_border"]}">'
        f'<img src="logos/{name}.png"></div>'
    )


def hero_html(theme):
    t = THEMES[theme]
    inner = ring(INNER, 268, 188, 0)
    outer = ring(OUTER, 470, 232, 22.5)
    paths = [spoke(x, y, 38, 0.10 if i % 2 else -0.10, t["spoke"], i) for i, (_, x, y) in enumerate(inner)]
    paths += [spoke(x, y, 32, -0.08 if i % 2 else 0.08, t["spoke"], 100 + i) for i, (_, x, y) in enumerate(outer)]
    orbits = (
        f'<ellipse cx="{CX}" cy="{CY}" rx="268" ry="188" fill="none" stroke="{t["orbit"]}" stroke-width="1.2" stroke-dasharray="2 7"/>'
        f'<ellipse cx="{CX}" cy="{CY}" rx="470" ry="232" fill="none" stroke="{t["orbit"]}" stroke-width="1.2" stroke-dasharray="2 7"/>'
    )
    tiles = [tile(n, x, y, 76, "20px", t) for n, x, y in inner]
    tiles += [tile(n, x, y, 64, "17px", t) for n, x, y in outer]
    tiles += [tile(n, x, y, 50, "50%", t, 0.92) for n, x, y in LOOSE]
    models = "".join(f'<img src="logos/{m}.png" style="transform:scale({k})">' for m, k in MODELS.items())
    return f"""<!doctype html><meta charset="utf-8">
<style>
html, body {{ margin: 0; background: transparent; }}
.frame {{ position: relative; width: {W}px; height: {H}px; overflow: hidden; border-radius: 28px; background: {t["bg"]};
          box-shadow: inset 0 0 0 1px {t["frame"]}; }}
.frame::before {{ content: ""; position: absolute; inset: 0; background-image: radial-gradient({t["dots"]} 1.1px, transparent 1.5px);
                  background-size: 22px 22px; }}
svg {{ position: absolute; inset: 0; }}
.tile {{ position: absolute; box-sizing: border-box; background: #ffffff; display: flex; align-items: center; justify-content: center; }}
.tile img {{ width: 100%; height: 100%; object-fit: contain; }}
.hub {{ position: absolute; left: {CX - HUB}px; top: {CY - HUB}px; width: {2 * HUB}px; height: {2 * HUB}px; border-radius: 50%;
        background: #ffffff; box-shadow: {t["hub_glow"]}; display: grid; grid-template-columns: 50px 50px; gap: 14px 16px;
        place-content: center; }}
.hub img {{ width: 50px; height: 50px; object-fit: contain; }}
</style>
<div class="frame">
<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{orbits}{"".join(paths)}</svg>
{"".join(tiles)}
<div class="hub">{models}</div>
</div>"""


def build_hero():
    for theme in THEMES:
        page = ASSETS / f".hero-{theme}.html"
        page.write_text(hero_html(theme), encoding="utf-8")
        out = ASSETS / f"hero-{theme}.png"
        out.unlink(missing_ok=True)
        try:
            headless._run(
                [
                    f"--screenshot={out}",
                    f"--window-size={W},{H}",
                    f"--force-device-scale-factor={SCALE}",
                    "--virtual-time-budget=2000",
                    "--default-background-color=00000000",
                ],
                page.resolve().as_uri(),
            )
        finally:
            page.unlink(missing_ok=True)
        im = Image.open(out)
        im.save(out, optimize=True)
        print(f"{out.relative_to(ROOT)}  {im.size[0]}x{im.size[1]}  {out.stat().st_size // 1024} KB")


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


if __name__ == "__main__":
    build_tiles()
    build_hero()
