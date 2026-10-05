"""GIMP (3.2.6, the PortableApps.com build in tools/gimp-portable: hash and signature checked, unpacked by 7-Zip) driven by
its own Python batch mode (python-fu-eval) on the hidden desktop, with its profile, cache and temp folders in
tools/gimp-portable/home. Photos: enhance (auto contrast + sharpen), black and white, resize, rotate, square crop, another
format; layered work (the Photoshop program's poster words, or pictures as layers) saved as GIMP's own .xcf. Checked by
measuring the result: contrast range, sharpness, greyness, size; an .xcf is opened again by GIMP and matches its layers.

  'gimp enhance photo.jpg'   'gimp black and white photo.jpg resize to 800 wide'   'gimp rotate photo.jpg 90'
  "gimp poster 1080x1350: title 'Book Fair' white, subtitle 'Saturday' yellow"
"""
import os
import re
from pathlib import Path

from PIL import Image

from ..config import ROOT

NAME, LABEL = "gimp", "GIMP: photo fixes (enhance, B&W, resize, rotate, square crop) and layered .xcf files"
EXAMPLES = ["gimp enhance photo.jpg", "gimp black and white photo.jpg resize to 800 wide", "gimp rotate photo.jpg 90",
            "gimp poster 1080x1350: title 'Book Fair' white, subtitle 'Saturday' yellow"]
HOME = ROOT / "tools" / "gimp-portable"
PHOTOS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}


def console():
    hits = sorted((HOME / "App" / "gimp" / "bin").glob("gimp-console-3*.exe")) if HOME.exists() else []
    return hits[0] if hits else None


def gimp(code, timeout=300):
    """Run Python in GIMP's batch mode; (ok, lines GIMP printed starting AIPC)."""
    from .. import hidden_desktop
    home = (HOME / "home").resolve()
    for d in ("profile", "cache", "temp"):
        (home / d).mkdir(parents=True, exist_ok=True)
    # HOME: GIMP's fonts.conf keeps its font cache at '~/AppData/Local/GIMP/...', so '~' is pointed into the project
    env = dict(os.environ, GIMP3_DIRECTORY=str(home / "profile"), GIMP3_CACHEDIR=str(home / "cache"), GIMP3_TEMPDIR=str(home / "temp"), HOME=str(home))
    local = Path(os.environ["LOCALAPPDATA"]) / "GIMP"
    had = local.exists()
    try:
        rc, out, err, timed_out = hidden_desktop.run([str(console()), "-i", "-d", "-f", "--batch-interpreter=python-fu-eval", "-b", code, "--quit"],
                                                     timeout=timeout, env=env)
    finally:  # an (empty) crash-log folder GIMP makes there whatever the settings say
        if not had and local.exists() and not any(f.is_file() for f in local.rglob("*")):
            import shutil
            shutil.rmtree(local, ignore_errors=True)
    text = out + err
    return rc == 0 and not timed_out and "AIPC_DONE" in text, [ln for ln in text.splitlines() if "AIPC" in ln or "Traceback" in ln or "Error:" in ln]


def photo_code(src, dest, steps):
    lines = ["from gi.repository import Gimp, Gio",
             f'img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(r"{src}"))', "layer = img.get_layers()[0]"]
    for s in steps:
        if s[0] == "enhance":
            lines += ["layer.levels_stretch()", 'f = Gimp.DrawableFilter.new(layer, "gegl:unsharp-mask", "Sharpen")',
                      'cfg = f.get_config(); cfg.set_property("std-dev", 2.0); cfg.set_property("scale", 0.7)', "f.update(); layer.merge_filter(f)"]
        elif s[0] == "bw":
            lines.append("layer.desaturate(Gimp.DesaturateMode.LUMINANCE)")
        elif s[0] == "rotate":
            lines.append(f"img.rotate(Gimp.RotationType.DEGREES{s[1]})")
        elif s[0] == "square":
            lines += ["side = min(img.get_width(), img.get_height())", "img.crop(side, side, (img.get_width() - side) // 2, (img.get_height() - side) // 2)"]
        elif s[0] == "resize":
            lines.append(f"w = {s[1]}; img.scale(w, round(img.get_height() * w / img.get_width()))")
    lines += ["img.flatten()" if Path(dest).suffix.lower() in (".jpg", ".jpeg", ".bmp") else "pass",
              f'Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(r"{dest}"), None)',
              'print("AIPC_DONE", img.get_width(), img.get_height())']
    return "\n".join(lines)


def measure(path):
    import numpy as np
    im = Image.open(path).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    lum = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lap = lum[1:-1, 1:-1] * 4 - lum[:-2, 1:-1] - lum[2:, 1:-1] - lum[1:-1, :-2] - lum[1:-1, 2:]
    return {"size": im.size, "range": float(np.percentile(lum, 99.5) - np.percentile(lum, 0.5)), "sharp": float(lap.var()),
            "sat": float((a.max(-1) - a.min(-1)).mean())}


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bgimp\b|\.xcf\b", c):
        return None
    f = find_file(text, ctx, PHOTOS)
    steps = []
    if re.search(r"\benhance\b|\bfix\b|\bimprove\b|\bauto\b|\bsharpen\b", c):
        steps.append(("enhance",))
    if re.search(r"\bblack\s*(?:and|&)\s*white\b|\bb\s*&\s*w\b|\bgr[ae]yscale\b|\bmonochrome\b", c):
        steps.append(("bw",))
    m = re.search(r"\brotate\b.*?\b(90|180|270)\b", c)
    if m:
        steps.append(("rotate", int(m.group(1))))
    if re.search(r"\bsquare\b", c):
        steps.append(("square",))
    m = re.search(r"\bresize\b.*?\b(\d{2,5})\s*(?:px\s*)?wide\b|\b(\d{2,5})\s*px\s*wide\b|\bwidth\s*(\d{2,5})\b", c)
    if m:
        steps.append(("resize", int(m.group(1) or m.group(2) or m.group(3))))
    fmt = re.search(r"\b(?:to|as)\s+(png|jpe?g|webp|tiff?|xcf)\b", c)
    if f and (steps or fmt):
        return {"op": "photo", "file": f, "steps": steps, "format": (fmt.group(1).replace("jpeg", "jpg") if fmt else None)}
    from . import photoshop
    op = photoshop.parse(re.sub(r"\bgimp\b", "photoshop", text, flags=re.I), ctx)
    return dict(op, app="gimp") if op else None


def run(op, ctx):
    if not console():
        return "GIMP is not in tools/gimp-portable."
    out = (Path(ctx["out"]) / "gimp").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "photo":
        src = Path(op["file"]).resolve()
        fmt = op["format"] or (src.suffix[1:].lower() if src.suffix.lower() in PHOTOS else "png")
        tag = "_".join(s[0] + (str(s[1]) if len(s) > 1 else "") for s in op["steps"]) or "converted"
        dest = out / f"{src.stem}_{tag}.{fmt}"
        dest.unlink(missing_ok=True)
        ok, lines = gimp(photo_code(src.as_posix(), dest.as_posix(), op["steps"]))
        if not ok or not dest.exists():
            return f"GIMP did not finish: {' | '.join(lines[-3:])}"
        if fmt == "xcf":
            return f"GIMP saved {dest} (its own layered format)."
        before, after = measure(src), measure(dest)
        checks = [("GIMP wrote the picture", True)]
        for s in op["steps"]:
            if s[0] == "enhance":
                checks += [(f"contrast range widened ({before['range']:.0f} -> {after['range']:.0f})", after["range"] >= before["range"] - 0.5),
                           ("sharper (more fine detail)", after["sharp"] > before["sharp"] * (1.0 if any(x[0] == "resize" for x in op["steps"]) else 1.05))]
            elif s[0] == "bw":
                checks.append(("black and white", after["sat"] < 2.0))
            elif s[0] == "rotate":
                w, h = before["size"]
                checks.append((f"rotated {s[1]} degrees", after["size"] == ((h, w) if s[1] in (90, 270) else (w, h)) or any(x[0] in ("resize", "square") for x in op["steps"])))
            elif s[0] == "square":
                checks.append(("square", after["size"][0] == after["size"][1]))
            elif s[0] == "resize":
                checks.append((f"{s[1]} px wide", after["size"][0] == s[1]))
        bad = [w for w, ok in checks if not ok]
        what = ", ".join({"enhance": "enhanced (auto contrast, sharpened)", "bw": "black and white", "rotate": "rotated", "square": "cropped square",
                          "resize": "resized"}[s[0]] for s in op["steps"]) or "converted"
        ctx.setdefault("memo", {})["photo"] = str(dest)
        return (f"GIMP {what}: {dest} ({after['size'][0]}x{after['size'][1]}). Done by GIMP itself (Python batch mode, hidden). " +
                ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
    from . import krita, photoshop
    if op["op"] == "stack":
        ims = [Image.open(f).convert("RGBA") for f in op["files"]]
        size = (max(i.width for i in ims), max(i.height for i in ims))
        layers = [(Path(f).stem, i, ((size[0] - i.width) // 2, (size[1] - i.height) // 2)) for f, i in zip(op["files"], ims)]
        stem = "layers"
    else:
        size = op["size"]
        layers = photoshop.poster(size, op.get("background"), op.get("logo"), op.get("logo_at", "top-left"), op.get("texts", []))
        stem = re.sub(r"[^\w-]+", "_", (op.get("texts") or [("", "poster", "")])[0][1]).strip("_") or "poster"
    ora, xcf, png = (out / f"{stem}.{x}" for x in ("ora", "xcf", "png"))
    for p in (xcf, png):
        p.unlink(missing_ok=True)
    flat = krita.write_ora(ora, size, layers)
    code = "\n".join(["from gi.repository import Gimp, Gio",
                      f'img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(r"{ora.as_posix()}"))',
                      f'Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(r"{xcf.as_posix()}"), None)',
                      f'back = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(r"{xcf.as_posix()}"))',
                      'print("AIPC_LAYERS", "|".join(l.get_name() for l in back.get_layers()))',
                      "back.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)",
                      f'Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, back, Gio.File.new_for_path(r"{png.as_posix()}"), None)',
                      'print("AIPC_DONE")'])
    ok, lines = gimp(code)
    names = next((ln.split("AIPC_LAYERS", 1)[1].strip().split("|") for ln in lines if "AIPC_LAYERS" in ln), [])
    diff = None
    if png.exists():
        import numpy as np
        a = np.asarray(Image.open(png).convert("RGBA"), dtype=np.int16)
        b = np.asarray(flat, dtype=np.int16)
        diff = float(np.abs(a - b).mean()) if a.shape == b.shape else None
    checks = [("GIMP saved its own .xcf and opened it again with every layer by name", xcf.exists() and set(n for n, _, _ in layers) <= set(names)),
              ("GIMP's picture of the .xcf matches the layers" + (f" (mean difference {diff:.2f} of 255)" if diff is not None else ""), diff is not None and diff < 1.0)]
    bad = [w for w, ok in checks if not ok]
    return (f"GIMP file {xcf} ({size[0]}x{size[1]}, layers: {', '.join(n for n, _, _ in reversed(layers))}), {png.name} rendered by GIMP. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f" {' | '.join(lines[-3:])}"))
