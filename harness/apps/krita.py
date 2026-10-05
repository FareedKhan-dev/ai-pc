"""Krita (6.0.4 portable in tools/krita, checked against KDE's published SHA-256): layered artwork written as OpenRaster
(.ora, the open layered format Krita, GIMP and MyPaint read), then Krita itself, on the hidden desktop, turns it into its
own .kra and renders a PNG. Posters and stacked pictures use the same words as the Photoshop program; a painter's blank
canvas gets named empty layers over a paper-white background. Checked: Krita's .kra holds every layer by name, and Krita's
own render matches the picture the layers make.

  "krita poster 1080x1350: title 'Art Fair' white, subtitle 'Sunday 4 pm' yellow"   'krita layers sky.png and tree.png'
  'krita canvas 3000x2000 with layers sketch, ink, colours'
"""
import os
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from ..config import ROOT

NAME, LABEL = "krita", "Krita: layered artwork (posters, stacked pictures, painters' canvases) as .kra + PNG"
EXAMPLES = ["krita poster 1080x1350: title 'Art Fair' white, subtitle 'Sunday 4 pm' yellow", "krita layers sky.png and tree.png",
            "krita canvas 3000x2000 with layers sketch, ink, colours"]
HOME = ROOT / "tools" / "krita"


def exe():
    hits = sorted(HOME.rglob("krita.exe")) if HOME.exists() else []
    return hits[0] if hits else None


def write_ora(path, size, layers):
    """OpenRaster: a zip with 'mimetype' first (stored), stack.xml listing the layers top first, each layer a PNG, the merged picture."""
    w, h = size
    flat = Image.new("RGBA", size, (0, 0, 0, 0))
    for _, im, (x, y) in layers:
        flat.alpha_composite(im.convert("RGBA"), (x, y))
    stack = ET.Element("image", version="0.0.3", w=str(w), h=str(h), xres="72", yres="72")
    st = ET.SubElement(stack, "stack")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        for i, (name, im, (x, y)) in reversed(list(enumerate(layers))):
            ET.SubElement(st, "layer", name=name, src=f"data/layer{i}.png", x=str(x), y=str(y), opacity="1.0", visibility="visible",
                          **{"composite-op": "svg:src-over"})
        for i, (name, im, _) in enumerate(layers):
            buf = BytesIO()
            im.convert("RGBA").save(buf, "PNG")
            z.writestr(f"data/layer{i}.png", buf.getvalue(), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("stack.xml", ET.tostring(stack, encoding="unicode", xml_declaration=True), compress_type=zipfile.ZIP_DEFLATED)
        for name, im in (("mergedimage.png", flat), ("Thumbnails/thumbnail.png", flat.copy())):
            if name.startswith("Thumbnails"):
                im.thumbnail((256, 256))
            buf = BytesIO()
            im.save(buf, "PNG")
            z.writestr(name, buf.getvalue(), compress_type=zipfile.ZIP_DEFLATED)
    return flat


def krita(*args, timeout=300):
    """Krita on the hidden desktop. It has no portable mode: its settings file is always AppData\\Local\\kritarc, so (when the
    user has no Krita of their own) a kritarc pointing its resources (97 MB of brushes and the like) into tools/krita/home is
    there only while it runs; anything it made in AppData is removed after."""
    from .. import hidden_desktop
    local, roam = Path(os.environ["LOCALAPPDATA"]), Path(os.environ["APPDATA"])
    rc = local / "kritarc"
    leftovers = [rc, local / "kritadisplayrc", roam / "krita", local / "krita"]
    had = {p: p.exists() for p in leftovers}
    res = (HOME / "home" / "resources").resolve()
    res.mkdir(parents=True, exist_ok=True)
    if not had[rc]:
        rc.write_text(f"ResourceDirectory={res.as_posix()}\n", encoding="utf-8")
    try:
        return hidden_desktop.run([str(exe()), *map(str, args)], timeout=timeout, env=dict(os.environ))
    finally:
        for p in leftovers:
            if not had[p] and p.exists():
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


def kra_layers(path):
    """Layer names in a .kra, top first, from its maindoc.xml."""
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read("maindoc.xml"))
    return [l.get("name") for l in doc.iter() if l.tag.endswith("layer") and l.get("name")]


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bkrita\b|\bopenraster\b|\.ora\b", c):
        return None
    m = re.search(r"\bcanvas\b(?:\s+(\d{3,5})\s*[x×]\s*(\d{3,5}))?(?:.*?\blayers?\s+(.+))?$", c)
    if m and "canvas" in c:
        names = [n.strip().title() for n in re.split(r",|\band\b", m.group(3) or "sketch, ink, colours") if n.strip()]
        return {"op": "canvas", "size": (int(m.group(1)), int(m.group(2))) if m.group(1) else (3000, 2000), "layers": names}
    from . import photoshop
    op = photoshop.parse(re.sub(r"\bkrita\b", "photoshop", text, flags=re.I), ctx)
    return dict(op, app="krita") if op else None


def run(op, ctx):
    if not exe():
        return "Krita is not in tools/krita."
    from . import photoshop
    out = Path(ctx["out"]) / "krita"
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "canvas":
        size = op["size"]
        layers = [("Paper", Image.new("RGBA", size, (255, 255, 255, 255)), (0, 0))] + [(n, Image.new("RGBA", size, (0, 0, 0, 0)), (0, 0)) for n in op["layers"]]
        stem = "canvas_" + "_".join(n.lower() for n in op["layers"])
    elif op["op"] == "stack":
        ims = [Image.open(f).convert("RGBA") for f in op["files"]]
        size = (max(i.width for i in ims), max(i.height for i in ims))
        layers = [(Path(f).stem, i, ((size[0] - i.width) // 2, (size[1] - i.height) // 2)) for f, i in zip(op["files"], ims)]
        stem = "layers"
    else:
        size = op["size"]
        layers = photoshop.poster(size, op.get("background"), op.get("logo"), op.get("logo_at", "top-left"), op.get("texts", []))
        stem = re.sub(r"[^\w-]+", "_", (op.get("texts") or [("", "poster", "")])[0][1]).strip("_") or "poster"
    ora, kra, png = ((out / f"{stem}.{x}").resolve() for x in ("ora", "kra", "png"))
    for p in (kra, png):
        p.unlink(missing_ok=True)
    flat = write_ora(ora, size, layers)
    r1 = krita("--export", "--export-filename", kra, ora)
    r2 = krita("--export", "--export-filename", png, kra if kra.exists() else ora)
    names = kra_layers(kra) if kra.exists() else []
    diff = None
    if png.exists():
        import numpy as np
        a = np.asarray(Image.open(png).convert("RGBA"), dtype=np.int16)
        b = np.asarray(flat.convert("RGBA"), dtype=np.int16)
        if a.shape == b.shape:
            diff = float(np.abs(a - b).mean())
    checks = [("Krita made its own .kra with every layer by name", kra.exists() and set(n for n, _, _ in layers) <= set(names)),
              ("Krita's render matches the picture the layers make" + (f" (mean difference {diff:.2f} of 255)" if diff is not None else ""),
               diff is not None and diff < 1.0)]
    bad = [w for w, ok in checks if not ok]
    return (f"Krita file {kra} ({size[0]}x{size[1]}, layers: {', '.join(n for n, _, _ in reversed(layers))}), {png.name} rendered by Krita, and "
            f"{ora.name} (OpenRaster: also opens in GIMP and MyPaint). Made by Krita on a hidden desktop. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f". {(r1[2] or r1[1])[-200:]}"))
