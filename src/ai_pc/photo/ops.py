"""Photo edits by code, each one checked by measuring the result (the brightness that was asked for is there, the
faces asked to be hidden are blurred, the text can be read on what is behind it, the file is under the size asked).

  im2, info = run("brightness", im, {"amount": 0.25})
  checks = check("brightness", im, im2, {"amount": 0.25}, info)      [{"ok", "what"}]

Light and colour: brightness, contrast, saturation, vibrance, warmth, tint, shadows, highlights, white_balance, levels,
  clarity, auto (decides from the measures and says why); looks: bw, sepia, vintage, cinematic, dramatic, fade, soft,
  pop, sketch, cartoon, painting, hdr, invert.
Shape: crop (an aspect or the subject, kept in frame), trim, rotate, flip, straighten (the horizon found), resize,
  canvas (fit a shape without cropping, the rest filled with a blurred copy), border, rounded, polaroid, vignette.
Retouch: denoise, sharpen, blur, blur_faces, blur_background, remove_background, replace_background, smooth_skin,
  brighten_faces, erase (a corner's date stamp or logo filled in from around it).
Words: text (placed where it is quiet and readable, never over a face), meme, watermark (a corner or tiled), banner.
Layouts: collage, side_by_side, passport (a standard's size and head height, white background, a print sheet),
  document (a photographed page flattened and cleaned like a scan).
Transparency and alpha are kept through edits; a transparent photo stays transparent.
"""
import math
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from ai_pc.photo import analyze as A

FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONTS = {"impact": "impact.ttf", "bold": "segoeuib.ttf", "segoe": "segoeui.ttf", "title": "bahnschrift.ttf", "bahnschrift": "bahnschrift.ttf",
         "georgia": "georgiab.ttf", "serif": "georgia.ttf", "elegant": "georgiai.ttf", "arial": "arialbd.ttf", "times": "timesbd.ttf",
         "comic": "comicbd.ttf", "script": "segoesc.ttf", "handwriting": "segoesc.ttf", "verdana": "verdanab.ttf", "condensed": "ARIALNB.TTF",
         "fun": "SHOWG.TTF", "bauhaus": "BAUHS93.TTF", "mono": "consolab.ttf", "calibri": "calibrib.ttf", "tahoma": "tahomabd.ttf",
         "trebuchet": "trebucbd.ttf", "candara": "Candarab.ttf"}
SIZES = {"tiny": 0.025, "small": 0.04, "medium": 0.065, "large": 0.095, "huge": 0.14}
ASPECTS = {"square": (1, 1), "1:1": (1, 1), "4:5": (4, 5), "5:4": (5, 4), "16:9": (16, 9), "9:16": (9, 16), "3:2": (3, 2), "2:3": (2, 3), "4:3": (4, 3),
           "3:4": (3, 4), "21:9": (21, 9), "a4": (210, 297), "a4 landscape": (297, 210), "portrait": (4, 5), "landscape": (16, 9), "story": (9, 16),
           "wide": (16, 9), "cinema": (21, 9), "passport": (35, 45)}
PRESETS = {  # name: (width, height)
    "instagram": (1080, 1080), "instagram post": (1080, 1080), "instagram portrait": (1080, 1350), "instagram story": (1080, 1920), "story": (1080, 1920),
    "reel": (1080, 1920), "tiktok": (1080, 1920), "whatsapp status": (1080, 1920), "youtube thumbnail": (1280, 720), "thumbnail": (1280, 720),
    "facebook post": (1200, 630), "facebook cover": (1640, 624), "linkedin banner": (1584, 396), "linkedin post": (1200, 627), "twitter header": (1500, 500),
    "x header": (1500, 500), "twitter post": (1600, 900), "whatsapp dp": (640, 640), "profile picture": (640, 640), "dp": (640, 640),
    "wallpaper": (1920, 1080), "desktop wallpaper": (1920, 1080), "phone wallpaper": (1080, 2340), "a4 print": (2480, 3508), "4x6 print": (1800, 1200),
    "6x4 print": (1800, 1200), "5x7 print": (1500, 2100), "pinterest": (1000, 1500), "email": (1200, 800)}
PASSPORTS = {  # name: (width mm, height mm, head height as a share of the photo's height: low, high)
    "35x45": (35, 45, 0.70, 0.80), "pakistan": (35, 45, 0.70, 0.80), "uk": (35, 45, 0.645, 0.755), "schengen": (35, 45, 0.70, 0.80),
    "india": (35, 45, 0.70, 0.80), "uae": (43, 55, 0.62, 0.72), "saudi": (40, 60, 0.55, 0.65), "us": (51, 51, 0.50, 0.69), "2x2": (51, 51, 0.50, 0.69),
    "canada": (50, 70, 0.443, 0.514), "china": (33, 48, 0.58, 0.69)}


class OpError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ helpers
def split(im):
    """(RGB, alpha or None): edits work on the colour and keep the transparency."""
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        return im.convert("RGB"), im.getchannel("A")
    return im.convert("RGB"), None


def merge(rgb, alpha):
    if alpha is None:
        return rgb
    out = rgb.convert("RGBA")
    out.putalpha(alpha.resize(rgb.size) if alpha.size != rgb.size else alpha)
    return out


def lut(fn):
    """A 256-entry table from a 0-1 curve."""
    return [int(max(0, min(255, round(255 * fn(i / 255))))) for i in range(256)]


def colour(c, default=(255, 255, 255)):
    if c is None:
        return default
    if isinstance(c, (tuple, list)):
        return tuple(int(v) for v in c[:3])
    names = {"off white": "#f5f3ee", "cream": "#fff8e7", "light blue": "#cfe8ff", "sky blue": "#87ceeb", "navy": "#1f2a44", "gold": "#d4a017",
             "light grey": "#d9d9d9", "light gray": "#d9d9d9", "dark grey": "#333333", "dark gray": "#333333", "beige": "#f5f5dc", "maroon": "#800000",
             "teal": "#008080", "mint": "#98ff98", "peach": "#ffe5b4", "coral": "#ff7f50", "lavender": "#e6e6fa", "olive": "#808000"}
    try:
        return ImageColor.getrgb(names.get(str(c).lower().strip(), str(c).strip()))
    except ValueError:
        raise OpError(f"I don't know the colour '{c}'")


def font(name, size):
    f = FONTS.get(str(name or "bold").lower(), str(name))
    p = FONT_DIR / f
    if not p.exists():
        p = FONT_DIR / FONTS["bold"]
    return ImageFont.truetype(str(p), max(6, int(size)))


def _diff(a, b, box=None):
    """Mean absolute difference 0-1 between two images (or within a box)."""
    a, b = a.convert("RGB"), b.convert("RGB").resize(a.size)
    if box:
        a, b = a.crop(box), b.crop(box)
    return float(np.asarray(ImageChops.difference(a, b), dtype=np.float32).mean() / 255)


def _lap_var(im, box=None):
    g = im.convert("L")
    if box:
        g = g.crop(box)
    return float(cv2.Laplacian(np.asarray(g), cv2.CV_64F).var())


def _ok(cond, what):
    return {"ok": bool(cond), "what": what}


def _box_clip(box, size):
    x0, y0, x1, y1 = box
    return max(0, int(x0)), max(0, int(y0)), min(size[0], int(x1)), min(size[1], int(y1))


def _aspect(v):
    if isinstance(v, (tuple, list)):
        return float(v[0]) / float(v[1])
    s = str(v).lower().strip()
    if s in ASPECTS:
        w, h = ASPECTS[s]
        return w / h
    if ":" in s or "x" in s:
        a, b = s.replace("x", ":").split(":")[:2]
        return float(a) / float(b)
    raise OpError(f"I don't know the shape '{v}'")


# ------------------------------------------------------------------------------------------------ light and colour
def brightness(im, amount=0.2, target=None):
    """Brighter or darker by a tone curve (gamma), so whites stay white and blacks black: amount +0.2 = a fifth brighter
    on average (or target = the average wanted, 0-1)."""
    rgb, al = split(im)
    a = A.arr(A.small(rgb, 400)[0])
    m = float(A.lum(a).mean())
    want = float(target) if target is not None else m * (1 + float(amount))
    want = min(0.9, max(0.04, want))
    lo, hi = 0.12, 8.0
    g = 1.0
    for _ in range(32):
        g = math.sqrt(lo * hi)
        if A.lum(a ** g).mean() > want:
            lo = g
        else:
            hi = g
    out = rgb.point(lut(lambda x: x ** g) * 3)
    return merge(out, al), {"from": m, "want": want, "gamma": round(g, 3)}


def contrast(im, amount=0.25):
    """More contrast by an S-curve around the photo's own middle (its average stays), less by easing towards it."""
    rgb, al = split(im)
    mid = float(A.lum(A.arr(A.small(rgb, 300)[0])).mean())
    amt = float(amount)
    if amt >= 0:
        k = 3 + 14 * amt

        def curve(x):
            s = lambda t: 1 / (1 + math.exp(-k * (t - mid)))  # noqa: E731
            return (s(x) - s(0)) / (s(1) - s(0))
    else:
        def curve(x):
            return mid + (x - mid) * (1 + amt)
    return merge(rgb.point(lut(curve) * 3), al), {}


def saturation(im, amount=0.25):
    rgb, al = split(im)
    return merge(ImageEnhance.Color(rgb).enhance(max(0.0, 1 + float(amount))), al), {}


def vibrance(im, amount=0.3):
    """More colour where there is little (skin and already strong colours are left mostly as they are)."""
    rgb, al = split(im)
    h = cv2.cvtColor(np.asarray(rgb, dtype=np.float32) / 255.0, cv2.COLOR_RGB2HSV)
    s = h[..., 1]
    h[..., 1] = np.clip(s + float(amount) * s * (1 - s) * 2.2, 0, 1)
    out = (np.clip(cv2.cvtColor(h, cv2.COLOR_HSV2RGB), 0, 1) * 255).round().astype(np.uint8)
    return merge(Image.fromarray(out), al), {}


def _channels(im, r=1.0, g=1.0, b=1.0):
    rgb, al = split(im)
    tables = lut(lambda x: x * r) + lut(lambda x: x * g) + lut(lambda x: x * b)
    return merge(rgb.point(tables), al)


def warmth(im, amount=0.3):
    """Warmer (more golden) or cooler (bluer): amount -1..1."""
    t = max(-1.0, min(1.0, float(amount)))
    return _channels(im, 1 + 0.16 * t, 1 + 0.03 * t, 1 - 0.18 * t), {}


def tint(im, amount=0.2):
    """Towards magenta (+) or green (-)."""
    t = max(-1.0, min(1.0, float(amount)))
    return _channels(im, 1 + 0.05 * t, 1 - 0.12 * t, 1 + 0.05 * t), {}


def shadows(im, amount=0.4):
    """Lift the shadows (detail out of the dark parts) or deepen them (amount < 0); the light parts barely move."""
    t = float(amount)
    rgb, al = split(im)
    return merge(rgb.point(lut(lambda x: x + t * 2.6 * x * (1 - x) ** 3) * 3), al), {}


def highlights(im, amount=0.4):
    """Bring the highlights down (a bright sky's detail back) or up (amount < 0)."""
    t = float(amount)
    rgb, al = split(im)
    return merge(rgb.point(lut(lambda x: x - t * 2.6 * x ** 3 * (1 - x)) * 3), al), {}


def white_balance(im, strength=0.85):
    """Neutral colours: the grey-world gains, measured on the mid-tones (not on black, white or strong colours)."""
    rgb, al = split(im)
    a = A.arr(A.small(rgb, 500)[0])
    L = A.lum(a)
    _, S, _ = A.hsv(a)
    use = (L > 0.08) & (L < 0.92) & (S < 0.6)
    if use.sum() < 100:
        use = np.ones_like(L, bool)
    m = a[use].mean(0)
    grey = m.mean()
    gains = [1 + float(strength) * (grey / max(c, 1e-3) - 1) for c in m]
    gains = [float(min(1.6, max(0.6, g))) for g in gains]
    return _channels(merge(rgb, al), *gains), {"gains": [round(g, 3) for g in gains]}


def levels(im, low=0.5, high=99.5, keep_mean=True):
    """Stretch from the darkest to the lightest tones (the same stretch on each channel, so colours stay). keep_mean:
    a midtone curve then puts the average back where it was, so this adds range without brightening."""
    rgb, al = split(im)
    a = A.arr(A.small(rgb, 500)[0])
    L = A.lum(a)
    lo, hi = float(np.percentile(L, low)), float(np.percentile(L, high))
    if hi - lo < 0.05:
        return merge(rgb, al), {"range": [lo, hi]}
    g = 1.0
    if keep_mean:
        m0 = float(L.mean())
        st = np.clip((a - lo) / (hi - lo), 0, 1)
        lo_g, hi_g = 0.2, 5.0
        for _ in range(30):
            g = math.sqrt(lo_g * hi_g)
            if A.lum(st ** g).mean() > m0:
                lo_g = g
            else:
                hi_g = g
    return merge(rgb.point(lut(lambda x: min(1.0, max(0.0, (x - lo) / (hi - lo))) ** g) * 3), al), {"range": [round(lo, 3), round(hi, 3)]}


def clarity(im, amount=0.5):
    """Local contrast (CLAHE on the lightness): texture and detail stand out, colours stay."""
    rgb, al = split(im)
    lab = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2LAB)
    cl = cv2.createCLAHE(clipLimit=1.0 + 2.5 * float(amount), tileGridSize=(8, 8))
    lab[..., 0] = cl.apply(lab[..., 0])
    return merge(Image.fromarray(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)), al), {}


def auto(im, brighter=False):
    """Make it look better, decided from the measures, each step with its reason: colour cast, tonal range, exposure,
    flatness, dull colour, noise and softness. brighter: the person said it is too dark, so a dark scene is lifted
    fully instead of being kept a night scene."""
    st = A.stats(im)
    bd = A.backdrop(im)
    steps, out = [], im
    if bd["kind"] in ("green", "blue"):  # the screen's colour rules every measure: only the subject's light is judged
        mask, _ = A.foreground(im)
        a = A.arr(im.convert("RGB"))
        m = mask > 0.5
        sub = float(A.lum(a)[m].mean()) if m.any() else st["brightness"]
        if sub < 0.33:
            lifted, _ = brightness(im, 0.3)
            fgm = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8))
            out = Image.composite(lifted, im.convert("RGB"), fgm)
            steps.append(f"brightened the subject (it was {sub:.0%}); the {bd['kind']} screen is left as it is for keying")
        else:
            steps.append(f"a {bd['kind']}-screen shot: the subject is already well lit ({sub:.0%}), so it is left as it is; say 'remove the background' to key it")
        return out, {"steps": steps, "before": {k: st[k] for k in ("brightness", "contrast", "saturation")}, "studio": bd["kind"]}
    if max(abs(c) for c in st["cast"]) > 0.08 and st["saturation"] < 0.55:
        out, inf = white_balance(out, 0.7)
        cast = max(range(3), key=lambda i: abs(st["cast"][i]))
        steps.append(f"evened out a {['red', 'green', 'blue'][cast]} cast")
    s2 = A.stats(out)
    L = A.lum(A.arr(A.small(out.convert("RGB"), 400)[0]))
    lo, hi = np.percentile(L, 0.5), np.percentile(L, 99.5)
    if hi - lo < 0.85:
        cand, _ = levels(out, 0.3, 99.9)
        if A.stats(cand)["clip_light"] <= max(s2["clip_light"] + 0.006, 0.01):  # only if no highlights are lost doing it
            out = cand
            steps.append(f"used the full range of tones (was {lo:.0%}-{hi:.0%})")
    b = A.stats(out)["brightness"]
    if b < 0.36 or (brighter and b < 0.45):
        target = 0.42 if brighter else min(0.46, b * 2.2) if b < 0.15 else min(0.46, b * 1.6)  # a night scene is lifted, not turned into day
        out, _ = brightness(out, target=max(target, b + 0.04))
        steps.append(f"brightened it: it was dark ({st['brightness']:.0%} average)")
    elif b > 0.7:
        out, _ = brightness(out, target=0.6)
        steps.append(f"toned it down: it was too bright ({st['brightness']:.0%} average)")
    s3 = A.stats(out)
    if s3["contrast"] < st["contrast"] * 0.94 and st["contrast"] >= 0.17:  # lifting the shadows flattens the photo: give the contrast back
        for _ in range(4):  # by deepening the darks again, which leaves the highlights where they are (no new blown whites)
            out, _ = shadows(out, -0.25)
            s3 = A.stats(out)
            if s3["contrast"] >= st["contrast"] * 0.94:
                break
        if s3["contrast"] < st["contrast"] * 0.94:
            out, _ = clarity(out, 0.3)
            s3 = A.stats(out)
        steps.append("kept its contrast while brightening")
    if s3["contrast"] < 0.17:
        out, _ = clarity(out, 0.45)
        steps.append(f"added depth: it was flat (contrast {st['contrast']:.2f})")
    if 0.04 < s3["saturation"] < 0.26 and bd["kind"] is None:
        out, _ = vibrance(out, 0.35)
        steps.append("livened up dull colours")
    if st["brightness"] < 0.25 and A.noise(out) > 0.012:
        out, _ = denoise(out, 0.6)
        steps.append("smoothed the grain that brightening brings out")
    if A.edge_sharpness(out) < 30:
        out, _ = sharpen(out, 0.4)
        steps.append("sharpened it a little: it was soft")
    if not steps:
        steps.append("it already looked balanced, so nothing big was changed")
    return out, {"steps": steps, "before": {k: st[k] for k in ("brightness", "contrast", "saturation")}}


# ------------------------------------------------------------------------------------------------ looks
def bw(im, punch=0.15):
    rgb, al = split(im)
    g = ImageOps.grayscale(rgb)
    out = Image.merge("RGB", (g, g, g))
    if punch:
        out, _ = contrast(out, punch)
    return merge(out, al), {}


def sepia(im):
    rgb, al = split(im)
    g = ImageOps.autocontrast(ImageOps.grayscale(rgb), cutoff=0.5)
    return merge(ImageOps.colorize(g, black="#2b1d0e", mid="#a07850", white="#fff4e0"), al), {}


def vintage(im):
    out, _ = saturation(im, -0.25)
    out, _ = warmth(out, 0.35)
    rgb, al = split(out)
    rgb = rgb.point(lut(lambda x: 0.07 + 0.88 * x) * 3)  # faded blacks and whites
    out, _ = vignette(merge(rgb, al), 0.35)
    rgb, al = split(out)
    rng = np.random.default_rng(7)
    a = np.asarray(rgb, dtype=np.float32) + rng.normal(0, 5, (rgb.height, rgb.width, 1))
    return merge(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), al), {}


def cinematic(im):
    """Teal shadows, warm highlights, a little more contrast: the film look."""
    rgb, al = split(im)
    a = np.asarray(rgb, dtype=np.float32) / 255.0
    L = A.lum(a)[..., None]
    sh = np.clip(1 - L * 2, 0, 1)
    hi = np.clip(L * 2 - 1, 0, 1)
    a = a + sh * np.array([-0.06, 0.02, 0.06]) + hi * np.array([0.07, 0.02, -0.06])
    out = Image.fromarray((np.clip(a, 0, 1) * 255).round().astype(np.uint8))
    out, _ = contrast(out, 0.15)
    return merge(out, al), {}


def dramatic(im):
    out, _ = clarity(im, 0.8)
    out, _ = contrast(out, 0.25)
    out, _ = saturation(out, -0.15)
    out, _ = vignette(out, 0.35)
    return out, {}


def fade(im):
    rgb, al = split(im)
    out = rgb.point(lut(lambda x: 0.09 + 0.86 * x) * 3)
    out, _ = saturation(out, -0.1)
    return merge(out, al), {}


def soft(im, amount=0.35):
    """A soft glow: a blurred copy screened over the photo."""
    rgb, al = split(im)
    blur = rgb.filter(ImageFilter.GaussianBlur(max(2, max(rgb.size) * 0.008)))
    out = Image.blend(rgb, ImageChops.screen(rgb, blur), float(amount))
    return merge(out, al), {}


def pop(im):
    out, _ = vibrance(im, 0.4)
    out, _ = contrast(out, 0.15)
    out, _ = clarity(out, 0.3)
    return out, {}


def sketch(im):
    rgb, al = split(im)
    g, _ = cv2.pencilSketch(A.bgr(rgb), sigma_s=60, sigma_r=0.07, shade_factor=0.06)
    return merge(Image.fromarray(g).convert("RGB"), al), {}


def cartoon(im):
    rgb, al = split(im)
    img = A.bgr(rgb)
    s = min(1.0, 1400 / max(rgb.size))
    small_ = cv2.resize(img, None, fx=s, fy=s) if s < 1 else img
    col = small_
    for _ in range(4):
        col = cv2.bilateralFilter(col, 9, 60, 9)
    grey = cv2.medianBlur(cv2.cvtColor(small_, cv2.COLOR_BGR2GRAY), 7)
    edges = cv2.adaptiveThreshold(grey, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 4)
    q = (col // 24) * 24 + 12  # fewer colours, flat areas
    out = cv2.bitwise_and(q, q, mask=edges)
    out = cv2.resize(out, rgb.size) if s < 1 else out
    return merge(Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), al), {}


def painting(im):
    rgb, al = split(im)
    out = cv2.stylization(A.bgr(rgb), sigma_s=60, sigma_r=0.45)
    return merge(Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), al), {}


def hdr(im):
    rgb, al = split(im)
    out = cv2.detailEnhance(A.bgr(rgb), sigma_s=12, sigma_r=0.15)
    return merge(Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), al), {}


def invert(im):
    rgb, al = split(im)
    return merge(ImageOps.invert(rgb), al), {}


# ------------------------------------------------------------------------------------------------ shape
def _subject_centre(im):
    fl = A.faces(im)
    if fl:  # eyes a little above the middle of the frame (a portrait's rule of thirds)
        f = fl[0]
        x, y, w, h = f["box"]
        return x + w / 2, y + h * 0.45, fl
    x, y, w, h = A.subject(im)
    return x + w / 2, y + h / 2, fl


def crop(im, aspect=None, subject=False, pad=0.12, box=None):
    """To a shape (the subject kept in frame, faces near the top third), or to the subject itself ('crop to the car'),
    or to a box (x0, y0, x1, y1 as 0-1 of the photo)."""
    W, H = im.size
    if box:
        x0, y0, x1, y1 = box
        return im.crop(_box_clip((x0 * W, y0 * H, x1 * W, y1 * H), im.size)), {"box": box}
    if subject and not aspect:  # around the subject, grown to the nearest pleasing shape that fits in the photo
        x, y, w, h = A.subject(im)
        w2, h2 = w * (1 + 2 * pad), h * (1 + 2 * pad)
        best = None
        for nm in ("16:9", "3:2", "4:3", "1:1", "4:5", "2:3", "9:16"):
            r = _aspect(nm)
            bw_, bh_ = (max(w2, h2 * r), max(w2, h2 * r) / r)
            if bw_ <= W and bh_ <= H and (best is None or bw_ * bh_ < best[1] * best[2]):
                best = (nm, bw_, bh_)
        if best is None:
            b = _box_clip((x - w * pad, y - h * pad, x + w * (1 + pad), y + h * (1 + pad)), im.size)
            return im.crop(b), {"box": b, "subject": (x, y, w, h)}
        nm, bw_, bh_ = best
        cx, cy = x + w / 2, y + h / 2
        x0 = min(max(0, cx - bw_ / 2), W - bw_)
        y0 = min(max(0, cy - bh_ / 2), H - bh_)
        b = (round(x0), round(y0), round(x0 + bw_), round(y0 + bh_))
        return im.crop(b), {"box": b, "subject": (x, y, w, h), "shape": nm}
    r = _aspect(aspect or "1:1")
    if W / H > r:
        cw, ch = round(H * r), H
    else:
        cw, ch = W, round(W / r)
    cx, cy, fl = _subject_centre(im)
    if fl:
        cy = cy + ch * 0.12  # the eyes at about 38% from the top
    x0 = int(min(max(0, cx - cw / 2), W - cw))
    y0 = int(min(max(0, cy - ch / 2), H - ch))
    return im.crop((x0, y0, x0 + cw, y0 + ch)), {"box": (x0, y0, x0 + cw, y0 + ch), "faces": [f["box"] for f in fl]}


def trim(im, amount=0.08):
    W, H = im.size
    t = float(amount)
    return im.crop(_box_clip((W * t, H * t, W * (1 - t), H * (1 - t)), im.size)), {}


def rotate(im, degrees=90):
    """Turned clockwise by degrees: quarter turns exactly (no loss), other angles cut to the biggest upright rectangle."""
    d = float(degrees) % 360
    ops = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}  # PIL turns anticlockwise
    if round(d) in ops and abs(d - round(d)) < 1e-6:
        return im.transpose(ops[round(d)]), {"degrees": d}
    cw = ((d + 180) % 360) - 180
    out, _ = _level(im, -cw)
    return out, {"degrees": d}


def flip(im, how="horizontal"):
    return (ImageOps.mirror(im) if how.startswith("h") else ImageOps.flip(im)), {"how": how}


def straighten(im, angle=None):
    """Level a leaning photo: the lean found from long straight lines (or given: the right side lower = positive), the
    photo turned against it and cut to the biggest upright rectangle so no empty corners show."""
    a = A.tilt(im) if angle is None else float(angle)
    if abs(a) < 0.05:
        return im, {"angle": 0.0}
    out, _ = _level(im, a)
    return out, {"angle": a}


def _level(im, ccw):
    """Turned anticlockwise by ccw degrees, then cut to the biggest upright rectangle inside the turned photo."""
    a = float(ccw)
    W, H = im.size
    r = im.rotate(a, resample=Image.BICUBIC, expand=True)
    th = math.radians(abs(a))
    # the largest axis-aligned rectangle inside a W x H rectangle turned by th
    if W <= 0 or H <= 0:
        return im, {"angle": a}
    long_, short_ = max(W, H), min(W, H)
    sin, cos = math.sin(th), math.cos(th)
    if short_ <= 2 * sin * cos * long_ or abs(sin - cos) < 1e-10:
        x = 0.5 * short_
        wr, hr = (x / sin, x / cos) if W >= H else (x / cos, x / sin)
    else:
        c2 = cos * cos - sin * sin
        wr, hr = (W * cos - H * sin) / c2, (H * cos - W * sin) / c2
    cx, cy = r.width / 2, r.height / 2
    out = r.crop(_box_clip((cx - wr / 2, cy - hr / 2, cx + wr / 2, cy + hr / 2), r.size))
    return out, {"angle": a}


def resize(im, width=None, height=None, percent=None):
    W, H = im.size
    if percent:
        w, h = round(W * float(percent) / 100), round(H * float(percent) / 100)
    elif width and height:
        w, h = int(width), int(height)
    elif width:
        w, h = int(width), round(H * int(width) / W)
    elif height:
        w, h = round(W * int(height) / H), int(height)
    else:
        raise OpError("resize to what size?")
    return im.resize((max(1, w), max(1, h)), Image.LANCZOS), {"size": (w, h)}


def cover(im, size):
    """Fill a size exactly: scaled to cover it and cut around the subject."""
    tw, th = size
    r = tw / th
    c, _ = crop(im, (tw, th)) if abs(im.width / im.height - r) > 0.002 else (im, {})
    return c.resize((tw, th), Image.LANCZOS)


def canvas(im, aspect="9:16", fill="blur", size=None):
    """Fit a shape without cutting anything: the photo whole in the middle, the rest filled with a blurred, darker copy
    of it (or a colour)."""
    W, H = im.size
    r = _aspect(aspect) if not size else size[0] / size[1]
    if W / H > r:
        cw, ch = W, round(W / r)
    else:
        cw, ch = round(H * r), H
    rgb, al = split(im)
    if al is not None and np.asarray(al).min() < 250:  # a cut-out stays a cut-out: the new room is transparent (or the colour asked)
        solid = str(fill).lower() not in ("blur", "blurred", "auto", "transparent")
        out = Image.new("RGBA", (cw, ch), (colour(fill) + (255,)) if solid else (0, 0, 0, 0))
        off = ((cw - W) // 2, (ch - H) // 2)
        out.alpha_composite(merge(rgb, al), off)
        if size:
            out = out.resize(tuple(size), Image.LANCZOS)
        return out, {"offset": off, "inner": (W, H), "canvas": (cw, ch)}
    if str(fill).lower() in ("blur", "blurred", "auto"):
        s = max(cw / W, ch / H)
        bg = rgb.resize((math.ceil(W * s), math.ceil(H * s)), Image.BILINEAR)
        bg = bg.crop(((bg.width - cw) // 2, (bg.height - ch) // 2, (bg.width - cw) // 2 + cw, (bg.height - ch) // 2 + ch))
        bg = bg.filter(ImageFilter.GaussianBlur(max(8, max(cw, ch) * 0.03)))
        bg = ImageEnhance.Brightness(bg).enhance(0.8)
    else:
        bg = Image.new("RGB", (cw, ch), colour(fill))
    off = ((cw - W) // 2, (ch - H) // 2)
    bg.paste(rgb, off, al)
    out = bg
    if size:
        out = out.resize(tuple(size), Image.LANCZOS)
    return out, {"offset": off, "inner": (W, H), "canvas": (cw, ch)}


def border(im, percent=0.04, color="white", px=None):
    W, H = im.size
    b = int(px) if px else max(1, round(min(W, H) * float(percent)))
    rgb, al = split(im)
    out = ImageOps.expand(rgb, border=b, fill=colour(color))
    if al is not None:
        out = merge(out, ImageOps.expand(al, border=b, fill=255))
    return out, {"px": b, "color": colour(color)}


def rounded(im, radius=0.06):
    rgb, al = split(im)
    r = max(2, round(min(rgb.size) * float(radius)))
    m = Image.new("L", rgb.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, rgb.width - 1, rgb.height - 1), r, fill=255)
    if al is not None:
        m = ImageChops.multiply(m, al)
    out = rgb.convert("RGBA")
    out.putalpha(m)
    return out, {"radius": r}


def polaroid(im, caption=None):
    rgb, al = split(im)
    W, H = rgb.size
    side = round(min(W, H) * 0.05)
    bottom = round(min(W, H) * 0.2)
    out = Image.new("RGB", (W + 2 * side, H + side + bottom), (250, 250, 247))
    out.paste(rgb, (side, side), al)
    if caption:
        f = font("handwriting", bottom * 0.38)
        d = ImageDraw.Draw(out)
        tw = d.textlength(caption, font=f)
        while tw > out.width * 0.9 and f.size > 8:
            f = font("handwriting", f.size * 0.9)
            tw = d.textlength(caption, font=f)
        d.text(((out.width - tw) / 2, H + side + (bottom - f.size) / 2 - f.size * 0.15), caption, font=f, fill=(40, 40, 40))
    return out, {"side": side, "bottom": bottom}


def vignette(im, amount=0.35):
    rgb, al = split(im)
    W, H = rgb.size
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    m = 1 - float(amount) * np.clip((d - 0.35) / 0.65, 0, 1) ** 1.6
    a = np.asarray(rgb, dtype=np.float32) * m[..., None]
    return merge(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)), al), {}


# ------------------------------------------------------------------------------------------------ retouch
def denoise(im, strength=0.6):
    rgb, al = split(im)
    h = 3 + 8 * float(strength)
    out = cv2.fastNlMeansDenoisingColored(A.bgr(rgb), None, h, h, 7, 21)
    return merge(Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), al), {}


def sharpen(im, amount=0.6):
    rgb, al = split(im)
    r = max(1.0, max(rgb.size) / 1200)
    return merge(rgb.filter(ImageFilter.UnsharpMask(radius=r * 1.6, percent=int(60 + 160 * float(amount)), threshold=2)), al), {}


def blur(im, amount=0.5):
    rgb, al = split(im)
    return merge(rgb.filter(ImageFilter.GaussianBlur(max(1, max(rgb.size) * 0.006 * (0.5 + float(amount) * 2)))), al), {}


def _face_boxes(im, fl=None, grow=1.35):
    fl = fl if fl is not None else A.faces(im, min_score=0.5)
    out = []
    for f in fl:
        x, y, w, h = f["box"]
        cx, cy = x + w / 2, y + h / 2
        w2, h2 = w * grow, h * grow * 1.15
        out.append(_box_clip((cx - w2 / 2, cy - h2 / 2, cx + w2 / 2, cy + h2 / 2), im.size))
    return out


def blur_faces(im, style="blur", faces=None):
    """Hide every face: a strong blur (or big pixels) inside a soft oval over each one."""
    boxes = _face_boxes(im, faces)
    if not boxes:
        raise OpError("I found no faces in this photo")
    rgb, al = split(im)
    out = rgb.copy()
    for b in boxes:
        x0, y0, x1, y1 = b
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        reg = rgb.crop(b)
        if style.startswith("pix"):
            n = max(4, (x1 - x0) // 9)
            hid = reg.resize((max(1, (x1 - x0) // n), max(1, (y1 - y0) // n)), Image.BILINEAR).resize(reg.size, Image.NEAREST)
        else:
            hid = reg.filter(ImageFilter.GaussianBlur(max(4, (x1 - x0) * 0.22)))
        m = Image.new("L", reg.size, 0)
        ImageDraw.Draw(m).ellipse((0, 0, reg.width - 1, reg.height - 1), fill=255)
        m = m.filter(ImageFilter.GaussianBlur(max(1, reg.width * 0.04)))
        out.paste(hid, b[:2], m)
    return merge(out, al), {"boxes": boxes, "style": style}


def _composite(fg, bg, mask):
    """fg over bg by a 0-1 mask (float array, the photo's size)."""
    m = np.clip(mask, 0, 1)[..., None]
    a = np.asarray(fg.convert("RGB"), dtype=np.float32) * m + np.asarray(bg.convert("RGB").resize(fg.size), dtype=np.float32) * (1 - m)
    return Image.fromarray(np.clip(a, 0, 255).round().astype(np.uint8))


def _despill(rgb, kind):
    """Take the screen's colour cast off the subject's edges and hair."""
    a = np.asarray(rgb, dtype=np.float32)
    if kind == "green":
        a[..., 1] = np.minimum(a[..., 1], np.maximum(a[..., 0], a[..., 2]) * 1.02 + 4)
    elif kind == "blue":
        a[..., 2] = np.minimum(a[..., 2], np.maximum(a[..., 0], a[..., 1]) * 1.02 + 4)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _fg(im):
    rgb, al = split(im)
    if al is not None and np.asarray(al).min() < 250:  # already cut out
        return rgb, np.asarray(al, dtype=np.float32) / 255.0, "the existing transparency", None
    bd = A.backdrop(rgb)
    mask, how = A.foreground(rgb)
    if bd["kind"] in ("green", "blue"):
        rgb = _despill(rgb, bd["kind"])
    return rgb, mask, how, bd["kind"]


def remove_background(im):
    rgb, mask, how, kind = _fg(im)
    out = rgb.convert("RGBA")
    out.putalpha(Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8)))
    return out, {"how": how, "fg_share": round(float((mask > 0.5).mean()), 3)}


def replace_background(im, color=None, image=None, blur_bg=False):
    """A new background behind the subject: a colour, another photo (scaled to cover), or the photo's own, blurred."""
    rgb, mask, how, kind = _fg(im)
    if image:
        other = Image.open(image)
        other = ImageOps.exif_transpose(other).convert("RGB")
        bg = cover(other, rgb.size)
        what = Path(str(image)).name
    elif blur_bg:
        bg = rgb.filter(ImageFilter.GaussianBlur(max(6, rgb.width * 0.02)))
        what = "blurred"
    else:
        c = colour(color or "white")
        bg = Image.new("RGB", rgb.size, c)
        what = c
    return _composite(rgb, bg, mask), {"how": how, "background": what, "fg_share": round(float((mask > 0.5).mean()), 3), "mask": mask}


def blur_background(im, amount=0.6):
    rgb, mask, how, kind = _fg(im)
    bgim = rgb.filter(ImageFilter.GaussianBlur(max(4, rgb.width * 0.01 * (0.6 + 1.6 * float(amount)))))
    soft_mask = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), max(1.5, rgb.width * 0.002))
    _, al = split(im)
    return merge(_composite(rgb, bgim, soft_mask), al), {"how": how, "mask": mask}


def smooth_skin(im, amount=0.5):
    """Softer skin on the faces: an edge-keeping blur where the colour is skin, inside the faces only."""
    boxes = _face_boxes(im, grow=1.2)
    if not boxes:
        raise OpError("I found no faces to retouch")
    rgb, al = split(im)
    out = rgb.copy()
    for b in boxes:
        reg = rgb.crop(b)
        arr_ = np.asarray(reg)
        sm = cv2.bilateralFilter(arr_, 9, 30 + 50 * float(amount), 9)
        ycc = cv2.cvtColor(arr_, cv2.COLOR_RGB2YCrCb)
        skin = ((ycc[..., 1] > 133) & (ycc[..., 1] < 180) & (ycc[..., 2] > 77) & (ycc[..., 2] < 135)).astype(np.float32)
        skin = cv2.GaussianBlur(skin, (0, 0), 3) * min(1.0, 0.5 + float(amount))
        mix = arr_.astype(np.float32) * (1 - skin[..., None]) + sm.astype(np.float32) * skin[..., None]
        out.paste(Image.fromarray(np.clip(mix, 0, 255).astype(np.uint8)), b[:2])
    return merge(out, al), {"boxes": boxes}


def brighten_faces(im, amount=0.35):
    """Lift dark faces (against a bright window or sky) without washing out the rest."""
    boxes = _face_boxes(im, grow=1.6)
    if not boxes:
        raise OpError("I found no faces to brighten")
    rgb, al = split(im)
    lifted, _ = brightness(rgb, amount)
    m = Image.new("L", rgb.size, 0)
    d = ImageDraw.Draw(m)
    for b in boxes:
        d.ellipse(b, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(4, min(rgb.size) * 0.03)))
    return merge(Image.composite(lifted, rgb, m), al), {"boxes": boxes}


CORNERS = {"top-left": (0, 0), "top-right": (1, 0), "bottom-left": (0, 1), "bottom-right": (1, 1), "top": (0.5, 0), "bottom": (0.5, 1),
           "left": (0, 0.5), "right": (1, 0.5), "center": (0.5, 0.5), "middle": (0.5, 0.5)}


def erase(im, where="bottom-right", size=0.18, box=None):
    """Remove what is in a corner (a date stamp, a logo, a watermark): the marks found there (text-like, unlike their
    surroundings) are filled in from around them."""
    rgb, al = split(im)
    W, H = rgb.size
    if box:
        x0, y0, x1, y1 = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    else:
        fx, fy = CORNERS.get(where, (1, 1))
        w, h = W * float(size) * 1.6, H * float(size)
        x0 = min(max(0, fx * W - w / 2 if fx == 0.5 else (W - w) * fx), W - w)
        y0 = min(max(0, fy * H - h / 2 if fy == 0.5 else (H - h) * fy), H - h)
        x1, y1 = x0 + w, y0 + h
    b = _box_clip((x0, y0, x1, y1), rgb.size)
    img = A.bgr(rgb)
    reg = img[b[1]:b[3], b[0]:b[2]]
    g = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    tophat = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, np.ones((9, 9), np.uint8))
    blackhat = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, np.ones((9, 9), np.uint8))
    marks = ((tophat > 40) | (blackhat > 40)).astype(np.uint8) * 255
    marks = cv2.dilate(marks, np.ones((5, 5), np.uint8), iterations=2)
    mask = np.zeros(img.shape[:2], np.uint8)
    mask[b[1]:b[3], b[0]:b[2]] = marks
    if mask.sum() == 0:
        raise OpError(f"I see nothing to remove in the {where.replace('-', ' ')}")
    out = cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA)
    return merge(Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), al), {"box": b, "marks": float((mask > 0).sum() / ((b[2] - b[0]) * (b[3] - b[1]) + 1))}


# ------------------------------------------------------------------------------------------------ words
def _wrap(d, text, f, max_w):
    words = str(text).split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        if d.textlength(cur + " " + w, font=f) <= max_w:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _place(where, W, H, bw, bh, margin):
    w = str(where or "bottom").lower().replace(" ", "-")
    fx, fy = CORNERS.get(w, (0.5, 1))
    x = margin if fx == 0 else W - margin - bw if fx == 1 else (W - bw) / 2
    y = margin if fy == 0 else H - margin - bh if fy == 1 else (H - bh) / 2
    return x, y


def _viewed(rgb, al):
    """What a viewer sees: transparent parts shown as white (as a JPG of it, or most apps, show them)."""
    return rgb if al is None else Image.composite(rgb, Image.new("RGB", rgb.size, "white"), al)


def _onto(rgb, al, layer):
    """A drawn RGBA layer put on the photo. On a transparent photo, what is drawn becomes solid (else words drawn on
    the transparent part would not be seen)."""
    out = Image.alpha_composite(rgb.convert("RGBA"), layer).convert("RGB")
    return merge(out, ImageChops.lighter(al, layer.getchannel("A")) if al is not None else None)


def text(im, text="", where="auto", color="auto", size=None, font_name=None, style="caption", bg=None, outline=None, upper=False):
    """Words on the photo: wrapped to fit, placed where it is calm (never over a face) unless told where, in a colour
    that can be read on what is behind (white on dark, near-black on light, with an outline when a colour asked for
    is close to what is behind). Short words default to big, long ones smaller."""
    if not str(text).strip():
        raise OpError("what should the text say?")
    rgb, al = split(im)
    W, H = rgb.size
    view = _viewed(rgb, al)
    fl = A.faces(view)
    pos = A.quiet_band(view, fl) if where in (None, "auto") else where
    pos = {"middle": "center", "centre": "center"}.get(pos, pos)
    if style == "meme":
        font_name, upper, color, outline = font_name or "impact", True, color if color not in (None, "auto") else "white", outline or "black"
    if style == "title" and font_name is None:
        font_name = "title"
    s = str(text).upper() if upper else str(text)
    if size is None:
        size = "large" if len(s) <= 16 or style == "title" else "medium" if len(s) <= 40 else "small"
    size_px = SIZES.get(str(size), 0.065) * H if not str(size).replace(".", "").isdigit() else float(size)
    margin = round(min(W, H) * 0.045)
    d = ImageDraw.Draw(view)
    f = font(font_name or "bold", size_px)
    lines = _wrap(d, s, f, W - 2 * margin)
    while (len(lines) > 3 or max(d.textlength(ln, font=f) for ln in lines) > W - 2 * margin) and f.size > 10:
        f = font(font_name or "bold", f.size * 0.9)
        lines = _wrap(d, s, f, W - 2 * margin)
    lh = round(f.size * 1.18)
    bw = max(d.textlength(ln, font=f) for ln in lines)
    bh = lh * len(lines)
    x, y = _place(pos, W, H, bw, bh, margin)
    box = _box_clip((x - f.size * 0.15, y - f.size * 0.1, x + bw + f.size * 0.15, y + bh + f.size * 0.1), rgb.size)
    behind = tuple(int(v) for v in np.asarray(view.crop(box), dtype=np.float32).reshape(-1, 3).mean(0))
    layer = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
    if style == "banner" or bg:
        band_c = colour(bg) if bg else (0, 0, 0)
        pad = f.size * 0.45
        bb = _box_clip((0 if style == "banner" else x - pad, y - pad, W if style == "banner" else x + bw + pad, y + bh + pad), rgb.size)
        ImageDraw.Draw(layer).rectangle(bb, fill=band_c + ((215,) if not bg else (255,)))
        behind = band_c
        box = bb
    if color in (None, "auto"):
        fill = (255, 255, 255) if A.contrast_ratio((255, 255, 255), behind) >= A.contrast_ratio((20, 20, 20), behind) else (20, 20, 20)
    else:
        fill = colour(color)
    cr = A.contrast_ratio(fill, behind)
    stroke_c = colour(outline) if outline else ((0, 0, 0) if sum(fill) > 382 else (255, 255, 255))
    stroke = max(1, round(f.size * 0.07)) if (outline or cr < 4.5 or style == "meme") else 0
    if not stroke and style != "banner":  # a soft shadow under clean text
        shadow = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        for i, ln in enumerate(lines):
            lx = x + (bw - d.textlength(ln, font=f)) / 2
            sd.text((lx + f.size * 0.04, y + i * lh + f.size * 0.05), ln, font=f, fill=(0, 0, 0, 150) if sum(fill) > 382 else (255, 255, 255, 120))
        layer = Image.alpha_composite(layer, shadow.filter(ImageFilter.GaussianBlur(max(1, f.size * 0.04))))
    ld = ImageDraw.Draw(layer)
    for i, ln in enumerate(lines):
        lx = x + (bw - d.textlength(ln, font=f)) / 2
        ld.text((lx, y + i * lh), ln, font=f, fill=fill + (255,), stroke_width=stroke, stroke_fill=stroke_c + (255,))
    return _onto(rgb, al, layer), {"box": box, "fill": fill, "behind": behind, "contrast": round(cr, 2), "stroke": stroke, "where": pos, "lines": lines,
                                   "font_px": f.size, "faces": [ff["box"] for ff in fl], "auto": where in (None, "auto")}


def meme(im, top=None, bottom=None):
    out, info = im, {"parts": []}
    if top:
        out, i1 = text(out, top, "top", style="meme", size="large")
        info["parts"].append(i1)
    if bottom:
        out, i2 = text(out, bottom, "bottom", style="meme", size="large")
        info["parts"].append(i2)
    if not info["parts"]:
        raise OpError("what should the meme say?")
    return out, info


def watermark(im, text=None, logo=None, where="bottom-right", opacity=0.35, tiled=False, size=None):
    rgb, al = split(im)
    W, H = rgb.size
    layer = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
    op = int(255 * max(0.05, min(1.0, float(opacity))))
    if logo:
        lg = Image.open(logo).convert("RGBA")
        lw = round(W * (float(size) if size else 0.16))
        lg = lg.resize((lw, max(1, round(lg.height * lw / lg.width))), Image.LANCZOS)
        lg.putalpha(lg.getchannel("A").point(lambda v: v * op // 255))
        x, y = _place(where, W, H, lg.width, lg.height, round(min(W, H) * 0.04))
        layer.paste(lg, (int(x), int(y)), lg)
        box = (int(x), int(y), int(x) + lg.width, int(y) + lg.height)
    else:
        t = str(text or "©")
        f = font("bold", (float(size) if size else (0.05 if tiled else 0.035)) * H)
        d = ImageDraw.Draw(layer)
        tw = d.textlength(t, font=f)
        if tiled:
            tile = Image.new("RGBA", (int(tw + f.size * 2), int(f.size * 3)), (0, 0, 0, 0))
            ImageDraw.Draw(tile).text((f.size, f.size), t, font=f, fill=(255, 255, 255, op), stroke_width=max(1, f.size // 18), stroke_fill=(0, 0, 0, op // 2))
            tile = tile.rotate(30, expand=True, resample=Image.BICUBIC)
            for yy in range(-tile.height, H + tile.height, int(tile.height * 0.9)):
                off = (yy // max(1, int(tile.height * 0.9))) % 2 * tile.width // 2
                for xx in range(-tile.width + off, W + tile.width, int(tile.width * 1.1)):
                    layer.paste(tile, (xx, yy), tile)
            box = (0, 0, W, H)
        else:
            x, y = _place(where, W, H, tw, f.size * 1.2, round(min(W, H) * 0.035))
            d.text((x, y), t, font=f, fill=(255, 255, 255, op), stroke_width=max(1, f.size // 16), stroke_fill=(0, 0, 0, op // 2))
            box = _box_clip((x, y, x + tw, y + f.size * 1.25), rgb.size)
    return _onto(rgb, al, layer), {"box": box, "opacity": op / 255, "tiled": bool(tiled)}


# ------------------------------------------------------------------------------------------------ layouts
def collage(images, layout="grid", gap=0.012, bg="white", width=2048):
    ims = [ImageOps.exif_transpose(Image.open(p) if not isinstance(p, Image.Image) else p).convert("RGB") for p in images]
    n = len(ims)
    if n < 2:
        raise OpError("a collage needs two photos or more")
    g = round(width * float(gap))
    if layout == "row":
        cols, rows = n, 1
    elif layout == "column":
        cols, rows = 1, n
    else:
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
    cell_w = (width - g * (cols + 1)) // cols
    cell_h = cell_w if layout == "grid" else round(cell_w * (ims[0].height / ims[0].width)) if layout == "row" else round(cell_w * 0.66)
    H = rows * cell_h + g * (rows + 1)
    out = Image.new("RGB", (width, H), colour(bg))
    cells = []
    for i, im in enumerate(ims):
        r_, c_ = divmod(i, cols)
        if r_ == rows - 1 and n % cols and layout == "grid":  # a short last row is centred
            c_ += (cols - n % cols) / 2
        x = round(g + c_ * (cell_w + g))
        y = g + r_ * (cell_h + g)
        out.paste(cover(im, (cell_w, cell_h)), (x, y))
        cells.append((x, y, x + cell_w, y + cell_h))
    return out, {"cells": cells, "count": n}


def side_by_side(a, b, labels=("Before", "After")):
    h = max(a.height, b.height)
    a2 = a.convert("RGB").resize((round(a.width * h / a.height), h))
    b2 = b.convert("RGB").resize((round(b.width * h / b.height), h))
    g = max(4, h // 100)
    out = Image.new("RGB", (a2.width + b2.width + g, h), "white")
    out.paste(a2, (0, 0))
    out.paste(b2, (a2.width + g, 0))
    if labels:
        for (lbl, x0, w) in ((labels[0], 0, a2.width), (labels[1], a2.width + g, b2.width)):
            f = font("bold", h * 0.045)
            d = ImageDraw.Draw(out)
            d.text((x0 + h * 0.03, h * 0.03), lbl, font=f, fill="white", stroke_width=max(1, f.size // 12), stroke_fill="black")
    return out, {"sizes": (a2.size, b2.size)}


def passport(im, standard="35x45", bg="white", dpi=300, sheet=None, ready=None):
    """A passport / visa photo: the face found, the photo cut so the head is the height the standard asks and centred,
    the background made plain, at the standard's size in pixels at 300 dpi. sheet='4x6' lays copies out on a print.
    ready: this already is the passport photo (its measures as a dict): only the sheet is made."""
    std = PASSPORTS.get(str(standard).lower().replace(" ", ""), PASSPORTS["35x45"])
    wmm, hmm, lo, hi = std
    if ready and sheet:
        info = dict(ready)
        return _sheet(im.convert("RGB"), info, sheet, dpi)
    fl = A.faces(im)
    if not fl:
        raise OpError("I found no face for a passport photo")
    if len(fl) > 1 and fl[1]["box"][2] > fl[0]["box"][2] * 0.6:
        raise OpError("there is more than one person in this photo; a passport photo needs one")
    if bg:
        im2, info_bg = replace_background(im, color=bg)
    else:
        im2, info_bg = im.convert("RGB"), {}
    x, y, w, h = fl[0]["box"]
    crown, chin = y - 0.5 * h, y + h * 1.02  # YuNet's box runs from the brows to the chin: the head is about 1.5 boxes high
    head = chin - crown
    target = (lo + hi) / 2
    ph = head / target
    pw = ph * wmm / hmm
    cx = x + w / 2
    top = crown - ph * (1 - target) * 0.45  # a little more room above the head than below the chin
    b = (cx - pw / 2, top, cx + pw / 2, top + ph)
    canvas_ = Image.new("RGB", (math.ceil(pw), math.ceil(ph)), colour(bg) if bg else (255, 255, 255))
    inside = _box_clip(b, im2.size)  # only what is in the photo: above the head (off the top) stays the plain background
    canvas_.paste(im2.convert("RGB").crop(inside), (int(inside[0] - b[0]), int(inside[1] - b[1])))
    px = (round(wmm / 25.4 * dpi), round(hmm / 25.4 * dpi))
    photo = canvas_.resize(px, Image.LANCZOS)
    info = {"standard": f"{wmm}x{hmm} mm", "px": px, "head_share": round(head / ph, 3), "range": (lo, hi), "dpi": dpi, "bg": info_bg.get("how")}
    if sheet:
        return _sheet(photo, info, sheet, dpi)
    return photo, info


def _sheet(photo, info, sheet, dpi=300):
    """Copies of a passport photo on a print (4x6 in, 5x7 in or A4), with thin grey cutting lines."""
    px = tuple(info.get("px") or photo.size)
    if photo.size != px:
        photo = photo.resize(px, Image.LANCZOS)
    sw, sh = {"4x6": (4, 6), "6x4": (6, 4), "5x7": (5, 7), "a4": (8.27, 11.69)}.get(str(sheet).lower(), (4, 6))
    S = (round(sw * dpi), round(sh * dpi))
    g = round(dpi * 0.08)
    cols, rows = max(1, (S[0] - g) // (px[0] + g)), max(1, (S[1] - g) // (px[1] + g))
    page = Image.new("RGB", S, "white")
    d = ImageDraw.Draw(page)
    ox = (S[0] - cols * px[0] - (cols - 1) * g) // 2
    oy = (S[1] - rows * px[1] - (rows - 1) * g) // 2
    for r_ in range(rows):
        for c_ in range(cols):
            xx, yy = ox + c_ * (px[0] + g), oy + r_ * (px[1] + g)
            page.paste(photo, (xx, yy))
            d.rectangle((xx - 1, yy - 1, xx + px[0], yy + px[1]), outline=(170, 170, 170))
    return page, dict(info, sheet=f"{sw}x{sh} in", copies=cols * rows, sheet_px=S)


def document(im, mode="scan"):
    """A photographed page made flat and clean: its four corners found, the page straightened to a rectangle, the
    lighting evened out and the paper made white ('scan'), or kept in colour ('color')."""
    q = A.document_quad(im)
    if q is None:
        raise OpError("I could not find the edges of a page in this photo")
    tl, tr, br, bl = q
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    M = cv2.getPerspectiveTransform(q, np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32))
    warped = cv2.warpPerspective(A.bgr(im), M, (w, h), flags=cv2.INTER_CUBIC)
    if mode == "color":
        out = Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))
        out, _ = levels(out, 1, 99)
        return out, {"corners": q.tolist(), "size": (w, h)}
    g = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bgl = cv2.GaussianBlur(g, (0, 0), max(15, min(w, h) / 25))
    flat = np.clip(g / np.maximum(bgl, 1) * 235, 0, 255)  # the paper's shading divided out
    lo, hi = np.percentile(flat, 2), np.percentile(flat, 60)
    clean = np.clip((flat - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(clean).convert("RGB"), {"corners": q.tolist(), "size": (w, h)}


# ------------------------------------------------------------------------------------------------ the registry, and the checks
OPS = {f.__name__: f for f in (brightness, contrast, saturation, vibrance, warmth, tint, shadows, highlights, white_balance, levels, clarity, auto,
                               bw, sepia, vintage, cinematic, dramatic, fade, soft, pop, sketch, cartoon, painting, hdr, invert,
                               crop, trim, rotate, flip, straighten, resize, canvas, border, rounded, polaroid, vignette,
                               denoise, sharpen, blur, blur_faces, blur_background, remove_background, replace_background, smooth_skin, brighten_faces,
                               erase, text, meme, watermark, passport, document)}
LOOKS = {"bw", "sepia", "vintage", "cinematic", "dramatic", "fade", "soft", "pop", "sketch", "cartoon", "painting", "hdr", "invert"}


def run(name, im, args=None):
    fn = OPS.get(name)
    if fn is None:
        raise OpError(f"no edit '{name}'")
    args = {k: v for k, v in (args or {}).items() if v is not None}
    if name == "text" and "font" in args:
        args["font_name"] = args.pop("font")
    if name == "replace_background" and "blur" in args:
        args["blur_bg"] = args.pop("blur")
    try:
        return fn(im, **args)
    except TypeError as e:
        raise OpError(f"{name}: {e}")


def check(name, before, after, args=None, info=None):
    """Did the edit do what it says? Measured on the result."""
    args, info = args or {}, info or {}
    sb, sa = A.stats(before), A.stats(after)
    out = []
    amt = float(args.get("amount", 0) or 0)
    if name == "brightness":
        want = info.get("want", sb["brightness"])
        moved = sa["brightness"] - sb["brightness"]
        out.append(_ok((want - sb["brightness"]) * moved > 0 and abs(sa["brightness"] - want) <= max(0.05, abs(want - sb["brightness"]) * 0.5),
                       f"average brightness {sb['brightness']:.0%} -> {sa['brightness']:.0%} (asked about {want:.0%})"))
    elif name == "contrast":
        out.append(_ok((sa["contrast"] - sb["contrast"]) * (amt or 1) > 0, f"contrast {sb['contrast']:.3f} -> {sa['contrast']:.3f}"))
    elif name in ("saturation", "vibrance"):
        out.append(_ok((sa["saturation"] - sb["saturation"]) * (amt or 1) > 0, f"colour {sb['saturation']:.0%} -> {sa['saturation']:.0%}"))
    elif name == "warmth":
        out.append(_ok((sa["warmth"] - sb["warmth"]) * (amt or 1) > 0, f"warmth (red minus blue) {sb['warmth']:+.3f} -> {sa['warmth']:+.3f}"))
    elif name == "shadows":
        out.append(_ok((sa["dark_mean"] - sb["dark_mean"]) * (amt or 1) > 0 or sb["dark_mean"] == 0, f"the dark parts {sb['dark_mean']:.0%} -> {sa['dark_mean']:.0%}"))
    elif name == "highlights":
        out.append(_ok((sb["light_mean"] - sa["light_mean"]) * (amt or 1) >= 0, f"the light parts {sb['light_mean']:.0%} -> {sa['light_mean']:.0%}"))
    elif name == "white_balance":
        cb, ca = max(abs(c) for c in sb["cast"]), max(abs(c) for c in sa["cast"])
        out.append(_ok(ca <= cb + 0.005, f"colour cast {cb:.3f} -> {ca:.3f}"))
    elif name == "levels":
        out.append(_ok(sa["contrast"] >= sb["contrast"] - 0.002, f"tonal spread {sb['contrast']:.3f} -> {sa['contrast']:.3f}"))
    elif name in ("clarity", "hdr", "dramatic"):
        out.append(_ok(sa["sharpness"] > sb["sharpness"] or sa["contrast"] > sb["contrast"], f"detail {sb['sharpness']:.0f} -> {sa['sharpness']:.0f}"))
    elif name == "auto" and info.get("studio"):
        out.append(_ok(_diff(before, after) < 0.15, "the screen behind is kept for keying"))
    elif name == "auto":
        b0, b1 = sb["brightness"], sa["brightness"]
        better = 0.38 <= b1 <= 0.6 or abs(b1 - 0.47) <= abs(b0 - 0.47) + 0.02
        out.append(_ok(better, f"brightness {b0:.0%} -> {b1:.0%} (nearer a balanced 40-55%)"))
        out.append(_ok(sa["contrast"] >= sb["contrast"] * 0.9, f"contrast kept or raised ({sb['contrast']:.2f} -> {sa['contrast']:.2f})"))
        out.append(_ok(sa["clip_light"] <= max(sb["clip_light"] + 0.01, 0.02), f"blown highlights {sb['clip_light']:.1%} -> {sa['clip_light']:.1%}"))
    elif name == "bw":
        out.append(_ok(sa["saturation"] < 0.02, f"colour left {sa['saturation']:.1%}"))
    elif name == "sepia":
        h, s, _ = A.hsv(A.arr(A.small(after.convert("RGB"), 200)[0]))
        hs = h[s > 0.05]
        hue = float(np.median(hs)) if hs.size else 0
        spread = float(np.percentile(hs, 90) - np.percentile(hs, 10)) if hs.size else 0
        out.append(_ok(15 <= hue <= 50 and spread < 25, f"one brown tone throughout (hue {hue:.0f} degrees, spread {spread:.0f})"))
    elif name in ("vintage", "fade"):
        out.append(_ok(sa["clip_dark"] < 0.002, f"no pure black left ({sa['clip_dark']:.1%})"))
    elif name == "invert":
        out.append(_ok(abs(sa["brightness"] - (1 - sb["brightness"])) < 0.08, f"brightness {sb['brightness']:.0%} -> {sa['brightness']:.0%}"))
    elif name == "sketch":
        out.append(_ok(sa["saturation"] < 0.03 and sa["brightness"] > 0.55, f"a light pencil drawing ({sa['brightness']:.0%} light)"))
    elif name in LOOKS:
        d = _diff(before, after)
        out.append(_ok(d > 0.015, f"the look changed it ({d:.1%} of the tones)"))
    elif name in ("crop", "canvas") and (args.get("aspect") or args.get("size")):
        r = (args["size"][0] / args["size"][1]) if args.get("size") else _aspect(args["aspect"])
        out.append(_ok(abs(after.width / after.height - r) / r < 0.01, f"shape {after.width}x{after.height} ({after.width / after.height:.3f}, asked {r:.3f})"))
        if name == "crop" and info.get("faces"):
            x0, y0, x1, y1 = info["box"]
            inside = all(fx >= x0 - 2 and fy >= y0 - 2 and fx + fw <= x1 + 2 and fy + fh <= y1 + 2 for fx, fy, fw, fh in info["faces"][:1])
            out.append(_ok(inside, "the main face is inside the frame"))
        if name == "canvas":
            ox, oy = info["offset"]
            iw, ih = info["inner"]
            scale = after.width / info["canvas"][0]
            box = tuple(round(v * scale) for v in (ox, oy, ox + iw, oy + ih))
            d = _diff(after.crop(box), before)
            out.append(_ok(d < 0.03, f"nothing cut: the whole photo is inside ({d:.1%} different)"))
    elif name == "crop":
        out.append(_ok(after.width < before.width or after.height < before.height, f"{before.width}x{before.height} -> {after.width}x{after.height}"))
    elif name == "trim":
        out.append(_ok(after.width < before.width and after.height < before.height, f"{before.width}x{before.height} -> {after.width}x{after.height}"))
    elif name == "rotate":
        d = float(args.get("degrees", 90)) % 180
        want = (before.height, before.width) if abs(d - 90) < 1e-6 else before.size
        out.append(_ok(after.size == want or abs(d) % 90, f"{before.width}x{before.height} -> {after.width}x{after.height}"))
    elif name == "flip":
        ref = ImageOps.mirror(before) if str(args.get("how", "h")).startswith("h") else ImageOps.flip(before)
        out.append(_ok(_diff(ref, after) < 0.002, "mirrored"))
    elif name == "straighten":
        t0, t1 = A.tilt(before), A.tilt(after)
        out.append(_ok(abs(t1) < abs(t0) or abs(t1) < 0.5 or not t0, f"lean {t0:+.1f} -> {t1:+.1f} degrees"))
    elif name == "resize":
        want = info.get("size")
        out.append(_ok(tuple(after.size) == tuple(want), f"{after.width}x{after.height}"))
    elif name == "border":
        px = after.convert("RGB").getpixel((1, 1))
        out.append(_ok(max(abs(a - b) for a, b in zip(px, info["color"])) < 4, f"a {info['px']} px border"))
    elif name == "rounded":
        out.append(_ok(after.mode == "RGBA" and after.getchannel("A").getpixel((0, 0)) == 0, f"corners rounded ({info['radius']} px), transparent"))
    elif name == "polaroid":
        out.append(_ok(info["bottom"] > info["side"], "a photo frame, deeper at the bottom"))
    elif name == "vignette":
        a = A.lum(A.arr(A.small(after.convert("RGB"), 200)[0]))
        b = A.lum(A.arr(A.small(before.convert("RGB"), 200)[0]))
        h, w = a.shape
        cor = lambda m: float(np.mean([m[:h // 6, :w // 6].mean(), m[:h // 6, -w // 6:].mean(), m[-h // 6:, :w // 6].mean(), m[-h // 6:, -w // 6:].mean()]))  # noqa: E731
        out.append(_ok(cor(a) < cor(b) - 0.005, f"corners {cor(b):.0%} -> {cor(a):.0%}"))
    elif name == "denoise":
        out.append(_ok(sa["noise"] <= sb["noise"] + 1e-4, f"grain {sb['noise']:.4f} -> {sa['noise']:.4f}"))
    elif name == "sharpen":
        out.append(_ok(sa["edges"] > sb["edges"], f"edge crispness {sb['edges']:.0f} -> {sa['edges']:.0f}"))
    elif name == "blur":
        out.append(_ok(sa["sharpness"] < sb["sharpness"], f"detail {sb['sharpness']:.0f} -> {sa['sharpness']:.0f}"))
    elif name == "blur_faces":
        def gone(b):
            x0, y0, x1, y1 = b
            core = (x0 + (x1 - x0) // 5, y0 + (y1 - y0) // 5, x1 - (x1 - x0) // 5, y1 - (y1 - y0) // 5)
            if info.get("style", "").startswith("pix"):  # big flat blocks: most pixels equal their neighbour, which a real face never does
                a_ = np.asarray(after.convert("RGB").crop(core)).astype(np.int16)
                b_ = np.asarray(before.convert("RGB").crop(core)).astype(np.int16)
                same = lambda z: float((np.abs(z[:, 1:] - z[:, :-1]).max(axis=2) <= 1).mean())  # noqa: E731
                return same(a_) > 0.6 and same(a_) > same(b_) + 0.25
            return _lap_var(after, core) < 0.35 * max(_lap_var(before, core), 1e-6)
        hidden = [b for b in info["boxes"] if (b[2] - b[0]) >= 4 and gone(b)]
        out.append(_ok(len(hidden) == len([b for b in info["boxes"] if (b[2] - b[0]) >= 4]), f"{len(hidden)}/{len(info['boxes'])} faces blurred"))
        rest = before.convert("RGB").copy()
        aft = after.convert("RGB").copy()
        dr, da = ImageDraw.Draw(rest), ImageDraw.Draw(aft)
        for b in info["boxes"]:
            dr.rectangle(b, fill=0)
            da.rectangle(b, fill=0)
        out.append(_ok(_diff(rest, aft) < 0.002, "nothing else changed"))
        left = [f for f in A.faces(after, 0.6) if any(abs(f["box"][0] - b[0]) < (b[2] - b[0]) for b in info["boxes"])]
        out.append(_ok(len(left) <= len(info["boxes"]) * 0.25, f"faces the detector still finds there: {len(left)}"))
    elif name == "remove_background":
        a = np.asarray(after.getchannel("A")) if after.mode == "RGBA" else None
        out.append(_ok(a is not None and 0.03 < (a > 127).mean() < 0.95, f"transparent background, the subject {info.get('fg_share', 0):.0%} of the photo ({info.get('how')})"))
        fl = A.faces(before)
        if fl and a is not None:
            x, y, w, h = fl[0]["box"]
            out.append(_ok(a[int(y + h / 2), int(x + w / 2)] > 200, "the face is kept"))
    elif name == "replace_background":
        m = info.get("mask")
        if m is not None and isinstance(info.get("background"), tuple):
            bgpx = np.asarray(after.convert("RGB"), dtype=np.float32)[m < 0.05]
            if len(bgpx):
                dev = float(np.abs(bgpx - np.array(info["background"], dtype=np.float32)).mean())
                out.append(_ok(dev < 6, f"the background is now {info['background']} (off by {dev:.1f}/255)"))
        out.append(_ok(0.03 < info.get("fg_share", 0) < 0.95, f"the subject kept ({info.get('fg_share', 0):.0%} of the photo; {info.get('how')})"))
    elif name == "blur_background":
        m = info.get("mask")
        if m is not None:
            bgm = cv2.resize((m < 0.2).astype(np.uint8), A.small(before)[0].size) > 0
            g0 = cv2.Laplacian(cv2.cvtColor(np.asarray(A.small(before.convert("RGB"))[0]), cv2.COLOR_RGB2GRAY), cv2.CV_64F)
            g1 = cv2.Laplacian(cv2.cvtColor(np.asarray(A.small(after.convert("RGB"))[0]), cv2.COLOR_RGB2GRAY), cv2.CV_64F)
            v0, v1 = float(g0[bgm].var()) if bgm.any() else 0, float(g1[bgm].var()) if bgm.any() else 0
            out.append(_ok(v1 < v0 * 0.6 or v0 < 1, f"background detail {v0:.0f} -> {v1:.0f} ({info.get('how')})"))
    elif name in ("smooth_skin", "brighten_faces"):
        ch = [_lap_var(after, b) <= _lap_var(before, b) + 1 if name == "smooth_skin" else A.lum(A.arr(after.crop(b))).mean() > A.lum(A.arr(before.crop(b))).mean()
              for b in info["boxes"]]
        out.append(_ok(all(ch), f"{sum(ch)}/{len(ch)} faces {'smoother' if name == 'smooth_skin' else 'brighter'}"))
    elif name == "erase":
        d = _diff(before, after, info["box"])
        out.append(_ok(d > 0.002, f"the {args.get('where', 'corner')} filled in ({d:.1%} changed there)"))
        rest = _diff(before, after) * (before.width * before.height) - d * ((info["box"][2] - info["box"][0]) * (info["box"][3] - info["box"][1]))
        out.append(_ok(rest / (before.width * before.height) < 0.003, "the rest untouched"))
    elif name == "text":
        x0, y0, x1, y1 = info["box"]
        out.append(_ok(x0 >= 0 and y0 >= 0 and x1 <= after.width and y1 <= after.height, f"the text fits ({len(info['lines'])} line(s), {info['font_px']} px)"))
        out.append(_ok(_diff(before, after, info["box"]) > 0.01, "it is on the photo"))
        out.append(_ok(info["contrast"] >= 4.5 or info["stroke"] > 0, f"readable: contrast {info['contrast']}:1 with what is behind" +
                       (" (outlined)" if info["stroke"] else "")))
        if info.get("auto") and info.get("faces"):
            over = [f for f in info["faces"] if not (f[0] + f[2] < x0 or f[0] > x1 or f[1] + f[3] < y0 or f[1] > y1)]
            out.append(_ok(not over, "not over a face"))
    elif name == "meme":
        out.append(_ok(all(p["stroke"] > 0 for p in info["parts"]), f"{len(info['parts'])} line(s) in white with a black outline"))
    elif name == "watermark":
        d = _diff(before, after, info["box"])
        out.append(_ok(0.002 < d < 0.25, f"a watermark at {info['opacity']:.0%} opacity ({d:.1%} change where it is)"))
    elif name == "passport":
        w, h = info["px"]
        out.append(_ok(True, f"{info['standard']} at {info['dpi']} dpi = {w}x{h} px"))
        lo, hi = info["range"]
        out.append(_ok(lo <= info["head_share"] <= hi, f"head {info['head_share']:.0%} of the height (the standard: {lo:.0%}-{hi:.0%})"))
        if info.get("copies"):
            out.append(_ok(info["copies"] >= 2, f"{info['copies']} copies on a {info['sheet']} print"))
        else:
            fl = A.faces(after)
            out.append(_ok(bool(fl) and abs((fl[0]["box"][0] + fl[0]["box"][2] / 2) / after.width - 0.5) < 0.06, "the face is centred"))
            edge = np.asarray(after.convert("RGB"), dtype=np.float32)[:max(2, after.height // 25), :max(2, after.width // 8)].mean()
            out.append(_ok(edge > 225, f"a plain light background ({edge / 255:.0%} white in the corner)"))
    elif name == "document":
        g = np.asarray(after.convert("L"), dtype=np.float32) / 255
        paper, ink = float(np.median(g)), float((g < 0.5).mean())
        out.append(_ok(paper > 0.8 and 0.003 < ink < 0.4, f"white paper ({paper:.0%}) with {ink:.1%} ink; {after.width}x{after.height}"))
    if not out:
        out.append(_ok(_diff(before, after) > 0.001 or before.size != after.size, "changed"))
    return out
