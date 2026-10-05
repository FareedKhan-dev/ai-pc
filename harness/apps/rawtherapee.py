"""RawTherapee 5.13 (tools/rawtherapee; GitHub SHA-256): RAW photos (CR2, CR3, NEF, ARW, DNG, ORF, RW2, RAF ...) and JPEG,
TIFF, PNG developed by RawTherapee's own command line on the hidden desktop. The look asked for in words (brighter,
darker, auto levels, black and white, vivid, warmer, cooler, sharpen, less noise) is written as a RawTherapee
processing profile (.pp3, kept beside the result so RawTherapee or the next photo can use it) on top of RawTherapee's
default profile. Its settings and cache live in tools/rawtherapee/home (RT_SETTINGS, RT_CACHE). Checked by measuring
the result against the original: each change asked for must be there (brightness, saturation, sharpness, warmth...).

  'rawtherapee IMG_0042.CR2 brighter and vivid'   'rawtherapee photo.jpg black and white, sharpen, as tiff'
"""
import os
import re
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "rawtherapee", "RawTherapee: RAW (and JPEG/TIFF) photos developed from words (exposure, B&W, vivid, warm, sharpen, denoise); each change measured"
EXAMPLES = ["rawtherapee IMG_0042.CR2 brighter and vivid", "rawtherapee photo.jpg black and white, sharpen, as tiff"]
HOME = ROOT / "tools" / "rawtherapee"
CLI = HOME / "rawtherapee-cli.exe"
RAWS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw", ".nrw", ".3fr", ".iiq", ".rwl"}
PHOTOS = RAWS | {".jpg", ".jpeg", ".tif", ".tiff", ".png"}
STEPS = {  # word -> (pp3 sections, what to measure)
    "brighter": ({"Exposure": {"Auto": "false", "Compensation": "0.8"}}, "brighter"),
    "darker": ({"Exposure": {"Auto": "false", "Compensation": "-0.8"}}, "darker"),
    "auto": ({"Exposure": {"Auto": "true", "Clip": "0.02"}}, "contrast"),
    "bw": ({"Black & White": {"Enabled": "true", "Method": "Desaturation"}}, "grey"),
    "vivid": ({"Vibrance": {"Enabled": "true", "Pastels": "60", "Saturated": "40", "ProtectSkins": "true"}}, "vivid"),
    "warmer": ({"White Balance": {"Enabled": "true", "Setting": "Custom", "Temperature": "8000", "Green": "1", "Equal": "1"}}, "warmer"),
    "cooler": ({"White Balance": {"Enabled": "true", "Setting": "Custom", "Temperature": "5200", "Green": "1", "Equal": "1"}}, "cooler"),
    "sharpen": ({"Sharpening": {"Enabled": "true", "Method": "usm", "Radius": "1.0", "Amount": "300", "Threshold": "20;80;2000;1200;"}}, "sharper"),
    "denoise": ({"Directional Pyramid Denoising": {"Enabled": "true", "Enhance": "false", "Median": "false", "Luma": "60", "Ldetail": "30",
                                                   "Chroma": "30", "Method": "Lab", "LMethod": "SLI", "CMethod": "MAN"}}, "smoother"),
}
WORDS = [("brighter", r"\bbright(?:er|en)\b|\blighter\b|\bexposure up\b"), ("darker", r"\bdark(?:er|en)\b"), ("auto", r"\bauto\b|\blevels\b|\bcontrast\b"),
         ("bw", r"\bblack\s*(?:and|&)\s*white\b|\bb\s*&\s*w\b|\bmonochrome\b|\bgr[ae]yscale\b"), ("vivid", r"\bvivid\b|\bvibran\w*|\bcolou?rful\b|\bpop\b"),
         ("warmer", r"\bwarm(?:er)?\b"), ("cooler", r"\bcool(?:er)?\b"), ("sharpen", r"\bsharp(?:en|er)?\b"), ("denoise", r"\bdenoise\b|\bnoise\b|\bgrain\b")]


def env():
    h = (HOME / "home").resolve()
    for d in ("settings", "cache"):
        (h / d).mkdir(parents=True, exist_ok=True)
    return dict(os.environ, RT_SETTINGS=str(h / "settings"), RT_CACHE=str(h / "cache"))


def pp3(steps):
    sections = {"Version": {"AppVersion": "5.13", "Version": "351"}}
    for s in steps:
        for sec, keys in STEPS[s][0].items():
            sections.setdefault(sec, {}).update(keys)
    return "\n".join(f"[{sec}]\n" + "".join(f"{k}={v}\n" for k, v in keys.items()) for sec, keys in sections.items())


def measure(path):
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((1600, 1600))
    a = np.asarray(im, dtype=np.float32)
    lum = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lap = lum[1:-1, 1:-1] * 4 - lum[:-2, 1:-1] - lum[2:, 1:-1] - lum[1:-1, :-2] - lum[1:-1, 2:]
    return {"mean": float(lum.mean()), "range": float(np.percentile(lum, 99.5) - np.percentile(lum, 0.5)), "sharp": float(lap.var()),
            "sat": float((a.max(-1) - a.min(-1)).mean()), "warm": float(a[..., 0].mean() / max(1.0, a[..., 2].mean()))}


def judged(kind, a, b):
    """(what changed, True if the change asked for is there) for before a, after b."""
    if kind == "brighter":
        return f"brighter (mean {a['mean']:.0f} -> {b['mean']:.0f})", b["mean"] > a["mean"] * 1.05
    if kind == "darker":
        return f"darker (mean {a['mean']:.0f} -> {b['mean']:.0f})", b["mean"] < a["mean"] * 0.95
    if kind == "contrast":
        return f"tones stretched (range {a['range']:.0f} -> {b['range']:.0f})", b["range"] >= a["range"] * 1.05 or b["range"] > 240
    if kind == "grey":
        return f"black and white (colour {a['sat']:.1f} -> {b['sat']:.1f})", b["sat"] < 2.5
    if kind == "vivid":
        return f"more colourful (colour {a['sat']:.1f} -> {b['sat']:.1f})", b["sat"] > a["sat"] * 1.08
    if kind == "warmer":
        return f"warmer (red/blue {a['warm']:.2f} -> {b['warm']:.2f})", b["warm"] > a["warm"] * 1.03
    if kind == "cooler":
        return f"cooler (red/blue {a['warm']:.2f} -> {b['warm']:.2f})", b["warm"] < a["warm"] * 0.97
    if kind == "sharper":
        return f"sharper (detail {a['sharp']:.0f} -> {b['sharp']:.0f})", b["sharp"] > a["sharp"] * 1.1
    if kind == "smoother":
        return f"less noise (detail {a['sharp']:.0f} -> {b['sharp']:.0f})", b["sharp"] < a["sharp"] * 0.95
    return kind, True


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\braw\s*therapee\b|\brawtherapee\b", c):
        return None
    f = find_file(text, ctx, PHOTOS)
    steps = [s for s, pat in WORDS if re.search(pat, c)]
    fmt = "tiff" if re.search(r"\btiff?\b", c) else "png" if re.search(r"\bpng\b", c) else "jpg"
    return {"op": "develop", "file": f, "steps": steps or ["auto"], "format": fmt} if f else None


def run(op, ctx):
    if not CLI.exists():
        return "RawTherapee is not in tools/rawtherapee."
    from .. import hidden_desktop
    src = Path(op["file"]).resolve()
    out = (Path(ctx["out"]) / "rawtherapee").resolve()
    out.mkdir(parents=True, exist_ok=True)
    steps = list(dict.fromkeys(op["steps"]))
    profile = out / f"{src.stem}_look.pp3"
    profile.write_text(pp3(steps), encoding="utf-8")
    dest = out / f"{src.stem}_developed.{ {'tiff': 'tif'}.get(op['format'], op['format'])}"  # RawTherapee writes TIFFs as .tif
    dest.unlink(missing_ok=True)
    fmt = {"jpg": ["-j95"], "tiff": ["-t"], "png": ["-n"]}[op["format"]]
    rc, so, se, timed_out = hidden_desktop.run([str(CLI), "-o", str(dest), "-d", "-p", str(profile), *fmt, "-Y", "-c", str(src)], timeout=600, env=env())
    if not dest.exists():
        return f"RawTherapee could not develop {src.name}: " + (se or so).strip()[-300:]
    before_path = src
    if src.suffix.lower() in RAWS:  # the original look of a RAW: RawTherapee's default development, nothing added
        before_path = out / f"{src.stem}_default.jpg"
        hidden_desktop.run([str(CLI), "-o", str(before_path), "-d", "-j95", "-Y", "-c", str(src)], timeout=600, env=env())
    a, b = measure(before_path), measure(dest)
    from PIL import Image
    same_size = Image.open(dest).size == (Image.open(src).size if src.suffix.lower() not in RAWS else Image.open(before_path).size)
    checks = [judged(STEPS[s][1], a, b) for s in steps] + [("the same size as the original", same_size)]
    bad = [w for w, good in checks if not good]
    return (f"RawTherapee developed {src.name} into {dest} with the profile {profile.name} ({', '.join(steps)}; load it in RawTherapee to use it again). " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
