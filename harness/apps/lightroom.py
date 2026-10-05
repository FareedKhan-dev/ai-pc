"""Lightroom (and Photoshop Camera Raw) by preset files: a look from words ('warm film', 'moody', 'black and white',
'bright and airy', or sliders like 'exposure +0.5, contrast 20, vignette -20') written as a Lightroom .xmp develop preset
that Lightroom Classic, Lightroom and Camera Raw import; the same look is applied here to the photos given, so finished
JPEGs come out at once (a RAW photo gets an .xmp sidecar beside a copy, so Lightroom shows the edit when it imports it).
Checked: the preset is valid XMP that Lightroom reads (type, name, every slider in range), and each edited photo really
changed the way the sliders say (brighter, warmer, more colourful, darker corners, grey).

  "lightroom preset 'Warm Film': warm vintage, exposure +0.3, vignette -20 for beach.jpg"   'lightroom moody preset'
"""
import re
import shutil
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

NAME, LABEL = "lightroom", "Lightroom: develop presets (.xmp) and the same look applied to photos"
EXAMPLES = ["lightroom preset 'Warm Film': warm vintage, exposure +0.3, vignette -20 for beach.jpg", "lightroom moody preset"]
# our slider -> (Lightroom name, low, high)
SLIDERS = {"exposure": ("Exposure2012", -5, 5), "contrast": ("Contrast2012", -100, 100), "highlights": ("Highlights2012", -100, 100),
           "shadows": ("Shadows2012", -100, 100), "whites": ("Whites2012", -100, 100), "blacks": ("Blacks2012", -100, 100), "texture": ("Texture", -100, 100),
           "clarity": ("Clarity2012", -100, 100), "dehaze": ("Dehaze", -100, 100), "vibrance": ("Vibrance", -100, 100), "saturation": ("Saturation", -100, 100),
           "temperature": ("IncrementalTemperature", -100, 100), "tint": ("IncrementalTint", -100, 100), "vignette": ("PostCropVignetteAmount", -100, 100),
           "grain": ("GrainAmount", 0, 100), "fade": (None, 0, 50)}
WORDS = {"temperature": r"temperature|warmth|temp", "vignette": r"vignette", "fade": r"fade|matte"}
LOOKS = {
    "warm": {"temperature": 15, "vibrance": 15, "contrast": 10},
    "cool": {"temperature": -15, "vibrance": 10, "contrast": 10},
    "bw": {"grayscale": True, "contrast": 25, "clarity": 15},
    "vintage": {"temperature": 10, "contrast": -10, "fade": 20, "grain": 25, "saturation": -15, "vignette": -15},
    "moody": {"exposure": -0.3, "contrast": 20, "highlights": -40, "shadows": -10, "saturation": -20, "vignette": -25, "clarity": 15},
    "bright": {"exposure": 0.4, "contrast": -10, "highlights": -20, "shadows": 40, "vibrance": 10, "temperature": 5},
    "vivid": {"contrast": 25, "vibrance": 30, "clarity": 20, "dehaze": 10},
    "matte": {"fade": 25, "contrast": -15, "saturation": -10},
}
LOOK_WORDS = {"warm": r"warm(?:er)?|golden", "cool": r"cool(?:er)?|cold|blue\s+tone", "bw": r"black\s*(?:and|&)\s*white|b\s*&\s*w|\bbw\b|monochrome|grayscale|greyscale",
              "vintage": r"vintage|film|retro", "moody": r"moody|dark\s+and\s+moody", "bright": r"bright(?:\s+and\s+airy)?|airy",
              "vivid": r"vivid|punchy|pop", "matte": r"matte|faded"}
PHOTO = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
RAW = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2"}
NS = {"x": "adobe:ns:meta/", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "crs": "http://ns.adobe.com/camera-raw-settings/1.0/"}


def settings_from(text):
    c = text.lower()
    s = {}
    for look, pat in LOOK_WORDS.items():
        if re.search(r"\b(?:" + pat + r")\b", c):
            for k, v in LOOKS[look].items():  # looks add up: 'warm vintage' is both
                s[k] = v if k == "grayscale" else round(s.get(k, 0) + v, 2)
    for k in SLIDERS:  # a number said for a slider wins over the look
        m = re.search(r"\b(?:" + WORDS.get(k, k) + r")\s*(?:to|:|=|of)?\s*([+-]?\d+(?:\.\d+)?)", c)
        if m:
            s[k] = float(m.group(1))
    for k, (_, lo, hi) in SLIDERS.items():
        if k in s:
            s[k] = max(lo, min(hi, round(s[k], 2) if k == "exposure" else round(s[k])))
    return {k: v for k, v in s.items() if v}


def _num(k, v):
    return f"{v:+.2f}" if k == "exposure" else ("0" if v == 0 else f"{int(v):+d}" if SLIDERS[k][1] < 0 else str(int(v)))


def xmp(name, s, preset=True):
    """A Lightroom develop preset (or, preset=False, a sidecar for a RAW photo) with these settings."""
    attrs = {"crs:Version": "15.0", "crs:ProcessVersion": "11.0", "crs:HasSettings": "True", "crs:ConvertToGrayscale": "True" if s.get("grayscale") else "False"}
    if preset:
        attrs = {"crs:PresetType": "Normal", "crs:Cluster": "", "crs:UUID": uuid.uuid5(uuid.NAMESPACE_URL, "aipc-lr/" + name).hex.upper(), "crs:SupportsAmount": "False",
                 "crs:SupportsColor": "True", "crs:SupportsMonochrome": "True", "crs:SupportsHighDynamicRange": "True", "crs:SupportsNormalDynamicRange": "True",
                 "crs:SupportsSceneReferred": "True", "crs:SupportsOutputReferred": "True", "crs:CameraModelRestriction": "", "crs:Copyright": "",
                 "crs:ContactInfo": "", **attrs}
    for k, (lr, _, _) in SLIDERS.items():
        if lr and k in s:
            attrs["crs:" + lr] = _num(k, s[k])
    if s.get("vignette"):
        attrs.update({"crs:PostCropVignetteStyle": "1", "crs:PostCropVignetteMidpoint": "50", "crs:PostCropVignetteFeather": "50", "crs:PostCropVignetteRoundness": "0"})
    if s.get("grain"):
        attrs.update({"crs:GrainSize": "25", "crs:GrainFrequency": "50"})
    curve = ""
    if s.get("fade"):
        attrs["crs:ToneCurveName2012"] = "Custom"
        f = round(s["fade"] * 1.2)
        curve = f'<crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, {f}</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq></crs:ToneCurvePV2012>'
    alt = lambda tag, t: f'<crs:{tag}><rdf:Alt><rdf:li xml:lang="x-default">{t}</rdf:li></rdf:Alt></crs:{tag}>'  # noqa: E731
    from html import escape
    names = (alt("Name", escape(name)) + alt("ShortName", "") + alt("SortName", "") + alt("Group", "AI PC") + alt("Description", "")) if preset else ""
    return ('<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000 1.000000, 0000/00/00-00:00:00        ">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"\n' +
            "".join(f'   {k}="{v}"\n' for k, v in attrs.items()) + "   >\n   " + names + curve + "\n  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n")


def apply(im, s):
    """The look applied by numpy, close to what Lightroom's sliders do (the preset itself is what Lightroom uses)."""
    import numpy as np
    from PIL import Image, ImageFilter
    a = np.asarray(im.convert("RGB"), dtype=np.float32) / 255
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4) * 2 ** s.get("exposure", 0)
    t, ti = s.get("temperature", 0) / 100, s.get("tint", 0) / 100
    lin = lin * np.array([1 + 0.25 * t, 1 - 0.15 * ti, 1 - 0.25 * t], dtype=np.float32)
    a = np.clip(np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.clip(lin, 1e-8, None) ** (1 / 2.4) - 0.055), 0, 1)
    w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    L = a @ w
    a = a + (s.get("shadows", 0) * 0.0035 * (1 - L) ** 3 + s.get("highlights", 0) * 0.0035 * L ** 3 +
             s.get("whites", 0) * 0.0015 * L ** 6 + s.get("blacks", 0) * 0.0015 * (1 - L) ** 6)[..., None]
    a = np.clip(0.5 + (np.clip(a, 0, 1) - 0.5) * (1 + 0.006 * s.get("contrast", 0)), 0, 1)
    h, wd = L.shape
    for key, radius, k in (("clarity", max(2, wd / 60), 0.008), ("texture", max(1, wd / 300), 0.006)):
        if s.get(key):
            L = a @ w
            blur = np.asarray(Image.fromarray((L * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255
            a = np.clip(a + ((L - blur) * s[key] * k)[..., None], 0, 1)
    dh = s.get("dehaze", 0) / 100
    if dh:
        a = np.clip((a - 0.08 * dh) / (1 - 0.08 * dh), 0, 1)
    grey = (a @ w)[..., None]
    sat = (a.max(-1) - a.min(-1))[..., None]
    k = 1 + s.get("saturation", 0) / 100 + s.get("vibrance", 0) / 100 * (1 - sat) + 0.3 * dh
    a = np.clip(grey + (a - grey) * k, 0, 1)
    if s.get("grayscale"):
        a = np.repeat((a @ w)[..., None], 3, -1)
    if s.get("fade"):
        f = s["fade"] * 1.2 / 255
        a = f + a * (1 - f)
    if s.get("vignette"):
        yy, xx = np.mgrid[0:h, 0:wd].astype(np.float32)
        r = ((xx / max(1, wd - 1) - 0.5) ** 2 + (yy / max(1, h - 1) - 0.5) ** 2) / 0.5
        a = a * (1 + s["vignette"] / 100 * 0.8 * r ** 1.5)[..., None]
    if s.get("grain"):
        a = a + np.random.default_rng(7).normal(0, s["grain"] / 100 * 0.06, (h, wd))[..., None]
    return Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))


def check_preset(path, name, s):
    root = ET.parse(path).getroot()
    d = root.find(".//rdf:Description", NS)
    crs = "{" + NS["crs"] + "}"
    li = d.find(f"{crs}Name/rdf:Alt/rdf:li", NS)
    ranges = all(lo <= float(d.get(crs + lr, 0)) <= hi for k, (lr, lo, hi) in SLIDERS.items() if lr and k in s)
    return [("the preset is XMP Lightroom reads: a develop preset with its name, every slider in range",
             d.get(crs + "PresetType") == "Normal" and li is not None and li.text == name and ranges and d.get(crs + "HasSettings") == "True")]


def check_photo(before, after, s):
    import numpy as np
    a = np.asarray(before.convert("RGB"), dtype=np.float32) / 255
    b = np.asarray(after, dtype=np.float32) / 255
    w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    out = []
    if abs(s.get("exposure", 0)) >= 0.2:
        out.append(("brighter" if s["exposure"] > 0 else "darker", ((b @ w).mean() - (a @ w).mean()) * s["exposure"] > 0))
    if s.get("grayscale"):
        out.append(("black and white", float((b.max(-1) - b.min(-1)).mean()) < 0.02))
    else:
        if abs(s.get("temperature", 0)) >= 5:
            out.append(("warmer" if s["temperature"] > 0 else "cooler", ((b[..., 0] - b[..., 2]).mean() - (a[..., 0] - a[..., 2]).mean()) * s["temperature"] > 0))
        v = s.get("vibrance", 0) + s.get("saturation", 0)
        if abs(v) >= 10:
            out.append(("more colourful" if v > 0 else "less colourful", ((b.max(-1) - b.min(-1)).mean() - (a.max(-1) - a.min(-1)).mean()) * v > 0))
    if s.get("vignette", 0) <= -5:  # against the same look with no vignette: the corners darker, the middle about the same
        c = np.asarray(apply(before, {k: v for k, v in s.items() if k != "vignette"}), dtype=np.float32) / 255
        h, wd = b.shape[:2]
        corner = lambda x: (x[: h // 8, : wd // 8] @ w).mean()  # noqa: E731
        mid = lambda x: (x[3 * h // 8: 5 * h // 8, 3 * wd // 8: 5 * wd // 8] @ w).mean()  # noqa: E731
        out.append(("with darker corners", corner(b) < corner(c) * 0.95 and abs(mid(b) - mid(c)) < 0.03))
    return out


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\blightroom\b|\bcamera\s+raw\b|\b(?:photo|develop)\s+preset\b|\.xmp\b", c):
        return None
    m = re.search(r"\bpreset\s+['\"]([^'\"]+)['\"]|['\"]([^'\"]+)['\"]\s+preset\b", text, re.I)
    c = re.sub(r"['\"][^'\"]*['\"]", " ", c)  # the preset's own name is not a look
    s = settings_from(c)
    if not s:
        return None
    look = next((k for k, p in LOOK_WORDS.items() if re.search(r"\b(?:" + p + r")\b", c)), None)
    name = (m.group(1) or m.group(2)) if m else ({"bw": "Black and White"}.get(look) or (look or "AI PC").title() + " Look")
    photos = [p for n, p in (ctx.get("files") or {}).items() if Path(p).suffix.lower() in PHOTO | RAW]
    photos += [p for p in re.findall(r"([a-z]:\\[^\"<>|?*\n]+?\.(?:jpe?g|png|tiff?|webp|dng|cr2|cr3|nef|arw|raf|orf|rw2))\b", text, re.I) if Path(p).exists()]
    return {"op": "preset", "name": name, "settings": s, "photos": list(dict.fromkeys(photos))}


def run(op, ctx):
    from PIL import Image
    out = Path(ctx["out"]) / "lightroom"
    out.mkdir(parents=True, exist_ok=True)
    name, s = op["name"], op["settings"]
    stem = re.sub(r"[^\w-]+", "_", name).strip("_")
    preset = out / f"{stem}.xmp"
    preset.write_text(xmp(name, s), encoding="utf-8")
    checks = check_preset(preset, name, s)
    done, raws = [], []
    for p in op["photos"]:
        src = Path(p)
        if src.suffix.lower() in RAW:  # a copy with its sidecar: Lightroom reads the sidecar when it imports the RAW
            shutil.copy2(src, out / src.name)
            (out / f"{src.stem}.xmp").write_text(xmp(name, s, preset=False), encoding="utf-8")
            raws.append(src.name)
            continue
        with Image.open(src) as im:
            im.load()
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)
            edited = apply(im, s)
            dest = out / f"{src.stem}_{stem}.jpg"
            edited.save(dest, quality=92)
            for what, ok in check_photo(im, edited, s):
                checks.append((f"{src.name} came out {what}", ok))
            done.append(dest.name)
    bad = [w for w, ok in checks if not ok]
    shown = ", ".join(f"{k} {_num(k, v) if k in SLIDERS else v}" for k, v in s.items() if k != "grayscale") + (", black and white" if s.get("grayscale") else "")
    return (f"Lightroom preset '{name}' ({shown}): {preset}. Import it in Lightroom Classic (Develop > Presets > + > Import Presets), Lightroom "
            "(Edit > Presets > ... > Import Presets) or Photoshop Camera Raw (Presets > ... > Import Profiles & Presets). " +
            (f"Applied here to {len(done)} photo(s): {', '.join(done)}. " if done else "") +
            (f"RAW photos copied with their .xmp sidecar (import the folder into Lightroom): {', '.join(raws)}. " if raws else "") +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
