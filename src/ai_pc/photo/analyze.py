"""What a photo is like, measured: light, contrast, colour, noise, sharpness, faces, its background (a green screen, a
plain backdrop), tilt, the main subject, a document in it, and where it is quiet enough for text.

  st = stats(im)            {"brightness", "contrast", "saturation", "warmth", "cast", "clip_dark", "clip_light", "sharpness", "noise", ...}
  fs = faces(im)            [{"box": (x, y, w, h) in pixels, "score"}], biggest first
  bg = backdrop(im)         {"kind": "green" | "blue" | "plain" | None, "color": (r, g, b), "share": 0-1}
  box = subject(im)         (x, y, w, h): faces with their heads and shoulders, else the backdrop's foreground, else saliency
  q = document_quad(im)     four corners of a sheet of paper in the photo, or None
  where = quiet_band(im)    "top" | "bottom" | "middle": the calmest band for text (faces avoided)
  describe(im)              one paragraph a person can read
All measures are 0-1 unless said otherwise. Photos are measured at a reduced size (the longer side 800 px), so it is fast.
"""
import math

import cv2
import numpy as np
from PIL import Image

WORK = 800  # the longer side measures are taken at


def small(im, side=WORK):
    """A reduced RGB copy (and the scale from it back to the photo)."""
    im = im.convert("RGB")
    s = min(1.0, side / max(im.size))
    if s < 1:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BILINEAR)
    return im, s


def arr(im):
    """float32 RGB 0-1."""
    return np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0


def lum(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def bgr(im):
    return cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def hsv(a):
    """H 0-360, S 0-1, V 0-1 from float RGB."""
    h = cv2.cvtColor(a, cv2.COLOR_RGB2HSV)
    return h[..., 0], h[..., 1], h[..., 2]


def sharpness(im):
    """Variance of the Laplacian of a grey 800 px copy (about 50 soft, 300+ crisp). A sky or a wall lowers it, so
    'is it blurry' is asked of edge_sharpness."""
    g = cv2.cvtColor(np.asarray(small(im)[0]), cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def edge_sharpness(im):
    """How crisp the photo's sharpest edges are: the 99.5th percentile of the Laplacian's size (under ~25 is soft)."""
    g = cv2.cvtColor(np.asarray(small(im)[0]), cv2.COLOR_RGB2GRAY)
    return float(np.percentile(np.abs(cv2.Laplacian(g, cv2.CV_64F)), 99.5))


def noise(im):
    """Noise level 0-1: the spread of the fine detail in the flattest parts of the photo."""
    g = cv2.cvtColor(np.asarray(small(im)[0]), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    hp = g - cv2.GaussianBlur(g, (0, 0), 1.2)
    local = cv2.GaussianBlur(np.abs(g - cv2.GaussianBlur(g, (0, 0), 4)), (0, 0), 4)
    flat = local < np.percentile(local, 30)
    return float(np.std(hp[flat])) if flat.any() else 0.0


def stats(im):
    """The numbers the edits are checked by."""
    s, _ = small(im)
    a = arr(s)
    L = lum(a)
    H, S, V = hsv(a)
    m = a.reshape(-1, 3).mean(0)
    grey = m.mean()
    cast = (m - grey) / max(grey, 1e-3)
    colourful = np.sqrt(np.std(a[..., 0] - a[..., 1]) ** 2 + np.std(0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]) ** 2) + \
        0.3 * np.sqrt(np.mean(a[..., 0] - a[..., 1]) ** 2 + np.mean(0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]) ** 2)
    out = {"width": im.width, "height": im.height, "brightness": float(L.mean()), "contrast": float(L.std()), "saturation": float(S.mean()),
           "warmth": float(m[0] - m[2]), "cast": [round(float(c), 3) for c in cast], "clip_dark": float((L < 0.02).mean()), "clip_light": float((L > 0.98).mean()),
           "colourful": float(colourful), "sharpness": sharpness(im), "edges": edge_sharpness(im), "noise": noise(im), "dark_mean": float(L[L < 0.3].mean()) if (L < 0.3).any() else 0.0,
           "light_mean": float(L[L > 0.7].mean()) if (L > 0.7).any() else 1.0, "alpha": im.mode in ("RGBA", "LA") and np.asarray(im.getchannel("A")).min() < 250}
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


# ------------------------------------------------------------------------------------------------ faces
def faces(im, min_score=0.55):
    """Faces in pixels of the photo, biggest first: [{"box": (x, y, w, h), "score", "eyes": ((x, y), (x, y))}]. Found by
    YuNet (models/yunet, checked by SHA-256) at up to 1600 px, so small faces in group photos are found too."""
    from ai_pc.media.frames import faces as yunet
    rgb = im.convert("RGB")
    s = min(1.0, 1600 / max(rgb.size))
    if s < 1:
        rgb = rgb.resize((round(rgb.width * s), round(rgb.height * s)), Image.BILINEAR)
    found = yunet(bgr(rgb), min_score=min_score)
    W, H = im.size
    out = []
    for f in found:
        x, y, w, h = f["box"]
        out.append({"box": (int(x * W), int(y * H), max(1, int(w * W)), max(1, int(h * H))), "score": f["score"],
                    "eyes": ((f["right_eye"][0] * W, f["right_eye"][1] * H), (f["left_eye"][0] * W, f["left_eye"][1] * H))})
    return out


# ------------------------------------------------------------------------------------------------ the background
def backdrop(im):
    """A studio background: a green or blue screen, or a plain backdrop (white wall, product table), from the photo's
    border. {"kind", "color", "share": the share of border pixels that are it}."""
    s, _ = small(im, 400)
    a = arr(s)
    b = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    r, g, bl = b[:, 0], b[:, 1], b[:, 2]
    green = (g > r * 1.25) & (g > bl * 1.25) & (g > 0.25)
    blue = (bl > r * 1.25) & (bl > g * 1.1) & (bl > 0.25)
    if green.mean() > 0.55:
        return {"kind": "green", "color": tuple(int(v * 255) for v in np.median(b[green], 0)), "share": round(float(green.mean()), 3)}
    if blue.mean() > 0.55:
        return {"kind": "blue", "color": tuple(int(v * 255) for v in np.median(b[blue], 0)), "share": round(float(blue.mean()), 3)}
    med = np.median(b, 0)
    lab = cv2.cvtColor(b.reshape(1, -1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    mlab = cv2.cvtColor(med.reshape(1, 1, 3).astype(np.float32), cv2.COLOR_RGB2LAB).reshape(3)
    close = np.linalg.norm(lab - mlab, axis=1) < 12
    if close.mean() > 0.7 and lum(med.reshape(1, 3))[0] > 0.3:  # a studio backdrop is lit; a dark border is a dark scene (a garage at night)
        return {"kind": "plain", "color": tuple(int(v * 255) for v in med), "share": round(float(close.mean()), 3)}
    return {"kind": None, "color": tuple(int(v * 255) for v in med), "share": round(float(close.mean()), 3)}


def key_mask(im, kind):
    """The background of a green / blue screen (1 = background), soft-edged, at the photo's size."""
    a = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if kind == "green":
        d = g - np.maximum(r, b)
    else:
        d = b - np.maximum(r, g)
    m = np.clip((d - 0.06) / 0.12, 0, 1)  # how much greener (bluer) than the other two: 0 at +0.06, 1 at +0.18
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.GaussianBlur(m, (0, 0), 1.0)


def plain_mask(im, color, tol=14):
    """The background of a plain backdrop (1 = background): colours near the border's, joined to the border (a white
    shirt in the middle of a white wall's photo stays)."""
    s, sc = small(im, 900)
    lab = cv2.cvtColor(np.asarray(s, dtype=np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    ref = cv2.cvtColor(np.array([[color]], dtype=np.float32) / 255.0, cv2.COLOR_RGB2LAB)[0, 0]
    near = (np.linalg.norm(lab - ref, axis=2) < tol).astype(np.uint8)
    n, lab_img = cv2.connectedComponents(near)
    border = set(np.unique(np.concatenate([lab_img[0], lab_img[-1], lab_img[:, 0], lab_img[:, -1]]))) - {0}
    bgm = np.isin(lab_img, list(border)).astype(np.float32)
    bgm = cv2.morphologyEx(bgm, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    bgm = cv2.resize(bgm, im.size, interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(bgm, (0, 0), 1.2)


def person_mask(im, face_list=None, iters=5):
    """The foreground (1 = person or subject) of an ordinary photo by GrabCut, started from the faces (a head and
    shoulders grow down to the bottom of the photo) or from the salient subject."""
    s, sc = small(im, 700)
    W, H = s.size
    fl = face_list if face_list is not None else faces(im)
    if fl:
        xs, ys, xe = [], [], []
        for f in fl:
            x, y, w, h = (v * sc for v in f["box"])
            xs.append(x - 1.6 * w)
            xe.append(x + w + 1.6 * w)
            ys.append(y - 0.7 * h)
        rect = (int(max(1, min(xs))), int(max(1, min(ys))), 0, 0)
        rect = (rect[0], rect[1], int(min(W - 2, max(xe)) - rect[0]), H - 1 - rect[1])
    else:
        x, y, w, h = (int(v * sc) for v in subject(im))
        rect = (max(1, x), max(1, y), max(2, min(W - 2 - x, w)), max(2, min(H - 2 - y, h)))
    mask = np.zeros((H, W), np.uint8)
    bgdm, fgdm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    img = bgr(s)
    cv2.grabCut(img, mask, rect, bgdm, fgdm, iters, cv2.GC_INIT_WITH_RECT)
    if fl:  # the faces themselves are surely foreground: a second pass with them marked
        for f in fl:
            x, y, w, h = (int(v * sc) for v in f["box"])
            mask[max(0, y):y + h, max(0, x):x + w] = cv2.GC_FGD
        cv2.grabCut(img, mask, None, bgdm, fgdm, 2, cv2.GC_INIT_WITH_MASK)
    fg = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1.0, 0.0).astype(np.float32)
    n, lab_img, st, _ = cv2.connectedComponentsWithStats((fg > 0.5).astype(np.uint8))
    if n > 1:  # the biggest pieces only (stray bits of background go)
        keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > 0.04 * st[1:, cv2.CC_STAT_AREA].max()]
        fg = np.isin(lab_img, keep).astype(np.float32)
    fg = cv2.resize(fg, im.size, interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(fg, (0, 0), 1.5)


def foreground(im):
    """(mask 1 = foreground, how it was found): a green / blue screen keyed, a plain backdrop cut, else GrabCut."""
    bd = backdrop(im)
    if bd["kind"] in ("green", "blue"):
        return 1.0 - key_mask(im, bd["kind"]), f"{bd['kind']} screen keyed"
    if bd["kind"] == "plain":
        return 1.0 - plain_mask(im, bd["color"]), "plain backdrop cut"
    fl = faces(im)
    return person_mask(im, fl), "GrabCut around " + (f"{len(fl)} face(s)" if fl else "the main subject")


# ------------------------------------------------------------------------------------------------ the subject, tilt, a document, room for text
def saliency(im):
    """A 0-1 map of what stands out (spectral residual + colour distinctness + a slight pull to the centre), at the
    reduced size."""
    s, _ = small(im, 256)
    a = arr(s)
    g = cv2.cvtColor(np.asarray(s), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    g64 = cv2.resize(g, (64, 64))
    F = np.fft.fft2(g64)
    A = np.log(np.abs(F) + 1e-9)
    P = np.angle(F)
    sr = np.abs(np.fft.ifft2(np.exp((A - cv2.blur(A, (3, 3))) + 1j * P))) ** 2
    sr = cv2.GaussianBlur(sr.astype(np.float32), (0, 0), 2.5)
    sr = cv2.resize(sr / (sr.max() + 1e-9), s.size)
    lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB)
    # what touches the border is background (a sky, a wall, a floor): distance to the nearest of the border's colours
    border = np.concatenate([lab[:4].reshape(-1, 3), lab[-4:].reshape(-1, 3), lab[:, :4].reshape(-1, 3), lab[:, -4:].reshape(-1, 3)]).astype(np.float32)
    k = min(8, len(border))
    _, _, centres = cv2.kmeans(border, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 2, cv2.KMEANS_PP_CENTERS)
    flat = lab.reshape(-1, 3)
    dist = np.min(np.linalg.norm(flat[:, None, :] - centres[None, :, :], axis=2), axis=1).reshape(lab.shape[:2])
    dist = cv2.GaussianBlur(dist, (0, 0), 3)
    dist = dist / (dist.max() + 1e-9)
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w]
    centre = np.exp(-(((xx - w / 2) / (0.6 * w)) ** 2 + ((yy - h / 2) / (0.6 * h)) ** 2))
    sal = (0.3 * sr + 0.7 * dist) * (0.55 + 0.45 * centre)
    return sal / (sal.max() + 1e-9)


def subject(im):
    """(x, y, w, h) in pixels of what the photo is of: faces with their heads and shoulders, else the foreground of a
    studio backdrop, else the most salient region."""
    W, H = im.size
    fl = faces(im)
    if fl:
        xs = [f["box"][0] - 0.5 * f["box"][2] for f in fl]
        ys = [f["box"][1] - 0.6 * f["box"][3] for f in fl]
        xe = [f["box"][0] + 1.5 * f["box"][2] for f in fl]
        ye = [f["box"][1] + 2.2 * f["box"][3] for f in fl]
        x0, y0, x1, y1 = max(0, min(xs)), max(0, min(ys)), min(W, max(xe)), min(H, max(ye))
        return int(x0), int(y0), int(x1 - x0), int(y1 - y0)
    bd = backdrop(im)
    if bd["kind"] is not None:
        m = (1.0 - (key_mask(im, bd["kind"]) if bd["kind"] in ("green", "blue") else plain_mask(im, bd["color"]))) > 0.5
        ys_, xs_ = np.nonzero(m)
        if len(xs_) > 0.01 * W * H:
            return int(np.percentile(xs_, 1)), int(np.percentile(ys_, 1)), int(np.percentile(xs_, 99) - np.percentile(xs_, 1)), \
                int(np.percentile(ys_, 99) - np.percentile(ys_, 1))
    sal = saliency(im)
    h, w = sal.shape
    th = (sal > max(0.35, np.percentile(sal, 85))).astype(np.uint8)
    n, lab_img, st, _ = cv2.connectedComponentsWithStats(th)
    if n <= 1:
        return 0, 0, W, H
    best = max(range(1, n), key=lambda i: sal[lab_img == i].sum())
    x, y, bw, bh = st[best, 0], st[best, 1], st[best, 2], st[best, 3]
    sx, sy = W / w, H / h
    pad = 0.08
    x0, y0 = max(0, (x - pad * bw) * sx), max(0, (y - pad * bh) * sy)
    x1, y1 = min(W, (x + bw * (1 + pad)) * sx), min(H, (y + bh * (1 + pad)) * sy)
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def tilt(im):
    """How many degrees the photo leans (the long straight lines near horizontal or vertical: a horizon, a building),
    or 0.0 when there are not enough lines to be sure. Positive = turn it clockwise to level it."""
    s, _ = small(im, 900)
    g = cv2.cvtColor(np.asarray(s), cv2.COLOR_RGB2GRAY)
    e = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(e, 1, np.pi / 720, threshold=80, minLineLength=max(s.size) // 6, maxLineGap=8)
    if lines is None:
        return 0.0
    angs, wts = [], []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):  # OpenCV 5 returns (N, 4), OpenCV 4 (N, 1, 4)
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        ang = (ang + 90) % 180 - 90  # -90..90
        dev = ang if abs(ang) <= 45 else (ang - 90 if ang > 0 else ang + 90)  # off horizontal, or off vertical
        if abs(dev) < 12:
            angs.append(dev)
            wts.append(math.hypot(x2 - x1, y2 - y1))
    if not angs or sum(wts) < max(s.size) * 0.6:  # one long horizon is enough; a few short lines are not
        return 0.0
    order = np.argsort(angs)
    cum = np.cumsum(np.array(wts)[order])
    med = float(np.array(angs)[order][np.searchsorted(cum, cum[-1] / 2)])
    return round(med, 2) if abs(med) >= 0.3 else 0.0


def document_quad(im):
    """The four corners (tl, tr, br, bl, in pixels) of a sheet of paper that fills a good part of the photo, else None."""
    s, sc = small(im, 1000)
    g = cv2.cvtColor(np.asarray(s), cv2.COLOR_RGB2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    best = None
    for lo, hi in ((50, 150), (25, 90), (75, 200)):
        e = cv2.dilate(cv2.Canny(g, lo, hi), np.ones((3, 3), np.uint8), iterations=2)
        cnts, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:8]:
            peri = cv2.arcLength(c, True)
            ap = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(ap) == 4 and cv2.isContourConvex(ap) and cv2.contourArea(ap) > 0.2 * s.size[0] * s.size[1]:
                best = ap.reshape(4, 2).astype(np.float32)
                break
        if best is not None:
            break
    if best is None:  # a light sheet on a darker table: the biggest bright region
        _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) > 0.2 * s.size[0] * s.size[1]:
                ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
                best = ap.reshape(-1, 2).astype(np.float32) if len(ap) == 4 else cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float32)
    if best is None:
        return None
    pts = best / sc
    ssum, diff = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(ssum)], pts[np.argmin(diff)], pts[np.argmax(ssum)], pts[np.argmax(diff)]], dtype=np.float32)


def busy(im):
    """How busy each part is (edge density), 0-1, at a reduced size."""
    s, _ = small(im, 400)
    g = cv2.cvtColor(np.asarray(s), cv2.COLOR_RGB2GRAY)
    e = cv2.Canny(g, 60, 160).astype(np.float32) / 255.0
    return cv2.GaussianBlur(e, (0, 0), 6)


def quiet_band(im, face_list=None, band=0.22):
    """The calmest of the top, bottom and middle bands for text: least edge detail, and never over a face."""
    W, H = im.size
    b = busy(im)
    h = b.shape[0]
    fl = face_list if face_list is not None else faces(im)
    scores = {}
    for name, (a0, a1) in {"top": (0.0, band), "bottom": (1 - band, 1.0), "middle": (0.5 - band / 2, 0.5 + band / 2)}.items():
        sc = float(b[int(a0 * h):max(int(a0 * h) + 1, int(a1 * h))].mean())
        for f in fl:
            fy0, fy1 = f["box"][1] / H, (f["box"][1] + f["box"][3]) / H
            if fy0 < a1 and fy1 > a0:
                sc += 1.0  # a face there: not this band
        scores[name] = sc + (0.004 if name == "middle" else 0)  # top or bottom first when it is a tie
    return min(scores, key=scores.get)


def contrast_ratio(c1, c2):
    def rl(c):
        v = [x / 255 for x in c[:3]]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    a, b = sorted((rl(c1), rl(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


# ------------------------------------------------------------------------------------------------ in words
def describe(im, st=None, fl=None, bd=None):
    st = st or stats(im)
    fl = fl if fl is not None else faces(im)
    bd = bd or backdrop(im)
    W, H = im.size
    r = W / H
    shape = "square" if abs(r - 1) < 0.03 else "landscape" if r > 1 else "portrait"
    named = {16 / 9: "16:9", 4 / 3: "4:3", 3 / 2: "3:2", 1.0: "1:1", 4 / 5: "4:5", 9 / 16: "9:16", 2 / 3: "2:3", 3 / 4: "3:4"}
    asp = next((n for v, n in named.items() if abs(r - v) < 0.01), f"{r:.2f}:1")
    b = st["brightness"]
    light = "very dark" if b < 0.2 else "dark" if b < 0.33 else "bright" if b > 0.68 else "well exposed"
    con = "flat (low contrast)" if st["contrast"] < 0.13 else "punchy (high contrast)" if st["contrast"] > 0.3 else "normal contrast"
    sat = "black and white" if st["saturation"] < 0.04 else "muted colours" if st["saturation"] < 0.18 else "vivid colours" if st["saturation"] > 0.5 else "natural colours"
    cast = max(range(3), key=lambda i: abs(st["cast"][i]))
    tint = f", a {['red', 'green', 'blue'][cast]}{'dish' if st['cast'][cast] > 0 else ''} tint" if abs(st["cast"][cast]) > 0.12 and st["cast"][cast] > 0 and bd["kind"] is None else ""
    sharp = "soft or blurry" if st["edges"] < 25 else "sharp"
    parts = [f"{W}x{H} {shape} ({asp}), {W * H / 1e6:.1f} MP", f"light: {light} ({b:.0%} average), {con}", f"{sat}{tint}", sharp]
    if st["noise"] > 0.025:
        parts.append("grainy")
    if fl:
        parts.append(f"{len(fl)} face(s)" + (f", the main one {fl[0]['box'][2] / W:.0%} of the width" if fl else ""))
    if bd["kind"] in ("green", "blue"):
        parts.append(f"a {bd['kind']} screen behind the subject")
    elif bd["kind"] == "plain":
        parts.append("a plain backdrop")
    if st.get("alpha"):
        parts.append("a transparent background")
    t = tilt(im)
    if abs(t) >= 0.8:
        parts.append(f"tilted about {abs(t):.1f} degrees")
    return "; ".join(parts) + "."
