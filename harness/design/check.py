"""Checks on a rendered design, from what the page measured of itself and the pictures:

  every word asked for is on it; no text overflows its box or shrank below a readable size; text, logos and QR codes
  stay inside the safe area (3 mm in from the trim for print; the margins the apps keep for their own buttons);
  nothing overlaps; each word stands out from what is actually behind it (WCAG contrast, measured on a render with
  the words hidden); photos are sharp enough to print; the QR code scans; no words sit on a face; the fonts are on
  this PC; the PDF is one page per side at the exact size with bleed; screen designs are their exact pixel size.

  checks(spec, result) -> [{"ok", "what", "level": "fail" | "warn"}]
"""
import re

import numpy as np
from PIL import Image

from .kinds import KINDS, size_of
from .layouts import PX_PER_MM

TEXT_FIELDS = ("name", "title", "company", "phone", "email", "web", "address", "tagline", "brand", "headline", "sub", "offer", "dates", "cta",
               "recipient", "org", "reason", "date", "time", "event", "host", "rsvp", "note", "body", "heading")


KIND_FIELDS = {"card": ("name", "title", "company", "phone", "email", "web", "address", "tagline"),
               "post": ("brand", "headline", "sub", "offer", "dates", "cta", "phone", "web"), "thumbnail": ("headline", "sub"),
               "flyer": ("brand", "headline", "sub", "offer", "dates", "cta", "phone", "web", "address", "body", "date", "time"),
               "certificate": ("org", "recipient", "reason", "date"), "invitation": ("heading", "host", "event", "date", "time", "address", "note", "rsvp")}
KIND_FIELDS.update(portrait=KIND_FIELDS["post"], story=KIND_FIELDS["post"], poster=KIND_FIELDS["flyer"])


def _c(ok, what, level="fail"):
    return {"ok": bool(ok), "what": what, "level": level}


def rgb(css):
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", css or "")
    if not m:
        return None
    return tuple(float(m.group(i)) for i in (1, 2, 3)) + (float(m.group(4)) if m.group(4) else 1.0,)


def lum(c):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def ratio(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def safe_rect(spec, meas):
    """The safe area in CSS px of the page."""
    w, h, unit, bleed, safe = size_of(spec)
    W, H = meas["w"], meas["h"]
    if unit == "mm":
        m = (bleed + safe) * PX_PER_MM
        return (m - 1, m - 1, W - m + 1, H - m + 1)
    k = KINDS[spec["kind"]]
    return (safe - 1, k.get("safe_top", safe) - 1, W - safe + 1, H - k.get("safe_bottom", safe) + 1)


def tbox(i):
    """Where the letters are (falls back to the element's box)."""
    if i.get("tw"):
        return i["tx"], i["ty"], i["tw"], i["th"]
    return i["x"], i["y"], i["w"], i["h"]


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def checks(spec, result, faces=None):
    out = []
    pages = result["pages"]
    items_all = [i for p in pages for i in ((p.get("measure") or {}).get("items") or [])]
    if not all(p.get("measure") for p in pages):
        return [_c(False, "the page did not report its measurements")]
    fonts = {}
    for p in pages:
        fonts.update(p["measure"].get("fonts") or {})
    missing = [f for f, ok in fonts.items() if not ok]
    out.append(_c(not missing, f"fonts on this PC: {', '.join(sorted(fonts))}" + (f" (missing: {', '.join(missing)})" if missing else "")))
    # every word asked for is on the design
    shown = " | ".join(_norm(i["text"]) for i in items_all if i.get("text_el"))
    want = {k: v for k, v in (spec.get("fields") or {}).items() if k in KIND_FIELDS.get(spec["kind"], TEXT_FIELDS) and isinstance(v, str) and v.strip()}
    if spec["kind"] == "certificate":
        want.pop("title", None)  # split over two lines
        for k in ("signer1", "signer2"):
            if spec["fields"].get(k):
                want[k] = spec["fields"][k].split(",")[0]
    if spec["kind"] == "thumbnail":
        want = {k: v for k, v in want.items() if k in ("headline", "sub")}
    gone = [k for k, v in want.items() if _norm(v) not in shown]
    for it in (spec.get("fields") or {}).get("items") or []:
        if _norm(it.get("name")) not in shown:
            gone.append(it.get("name"))
    out.append(_c(not gone, f"every detail asked for is on it ({len(want)} fields)" + (f" (not: {', '.join(map(str, gone[:4]))})" if gone else "")))
    texts = [i for i in items_all if i.get("text_el") and i.get("text")]
    over = [i["role"] for i in texts if i.get("over")]
    out.append(_c(not over, "no text runs out of its box" + (f" (not: {', '.join(over[:4])})" if over else "")))
    w, h, unit, bleed, safe = size_of(spec)
    floor = 5.5 * 96 / 72 if unit == "mm" else (16 if spec["kind"] != "thumbnail" else 24)
    small = [f"{i['role']} {i['size'] * (72 / 96 if unit == 'mm' else 1):.1f}{'pt' if unit == 'mm' else 'px'}" for i in texts if i["size"] < floor - 0.05]
    out.append(_c(not small, f"all text big enough to read (at least {floor * (72 / 96 if unit == 'mm' else 1):.1f}{'pt' if unit == 'mm' else 'px'})"
                  + (f" (not: {', '.join(small[:3])})" if small else "")))
    for p in pages:
        meas = p["measure"]
        sx0, sy0, sx1, sy1 = safe_rect(spec, meas)
        boxes = [i for i in meas["items"] if (i.get("text_el") and i.get("text")) or i["role"] in ("logo", "qr")]
        outside = []
        for i in boxes:
            x, y, bw, bh = tbox(i) if i.get("text_el") else (i["x"], i["y"], i["w"], i["h"])
            if bw > 0 and (x < sx0 or y < sy0 or x + bw > sx1 or y + bh > sy1):
                outside.append(i["role"])
        out.append(_c(not outside, f"{p['name']}: everything inside the safe area" + (f" (not: {', '.join(outside[:4])})" if outside else "")))
        hits = []
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                ax, ay, aw, ah = tbox(boxes[a]) if boxes[a].get("text_el") else (boxes[a]["x"], boxes[a]["y"], boxes[a]["w"], boxes[a]["h"])
                bx, by, bw, bh = tbox(boxes[b]) if boxes[b].get("text_el") else (boxes[b]["x"], boxes[b]["y"], boxes[b]["w"], boxes[b]["h"])
                A, B = boxes[a], boxes[b]
                ix = min(ax + aw, bx + bw) - max(ax, bx)
                iy = min(ay + ah, by + bh) - max(ay, by)
                if ix > 1.5 and iy > 1.5 and ix * iy > 0.04 * min(aw * ah, bw * bh):
                    hits.append(f"{A['role']}/{B['role']}")
        out.append(_c(not hits, f"{p['name']}: nothing overlaps" + (f" (not: {', '.join(hits[:3])})" if hits else "")))
        if p.get("bg_png"):
            bg = np.asarray(Image.open(p["bg_png"]).convert("RGB"), dtype=np.float32)
            sc = bg.shape[1] / meas["w"]
            low = []
            for i in meas["items"]:
                if not (i.get("text_el") and i.get("text")) or i["w"] < 2 or i["h"] < 2:
                    continue
                col = rgb(i["color"])
                if col is None or col[3] < 0.2:
                    continue
                tx, ty, tw, th = tbox(i)
                x0, y0 = int(max(0, tx * sc)), int(max(0, ty * sc))
                x1, y1 = int(min(bg.shape[1], (tx + tw) * sc)), int(min(bg.shape[0], (ty + th) * sc))
                region = bg[y0:y1, x0:x1].reshape(-1, 3)
                if not len(region):
                    continue
                if i.get("stroke", 0) >= 2 and rgb(i.get("strokeColor")):
                    r = ratio(col, rgb(i["strokeColor"]))  # outlined type reads on anything its outline stands out from
                else:  # what most of the letters sit on: the worst 12% of the ground under them (a photo's bright patch counts)
                    pts = region[:: max(1, len(region) // 600)]
                    r = float(np.percentile([ratio(col, c) for c in pts], 12))
                bold = str(i.get("weight", "400")).isdigit() and int(i.get("weight", "400")) >= 700
                need = 3.0 if (i["size"] >= 24 or (i["size"] >= 18.66 and bold)) else 4.5
                if r < need:
                    low.append(f"{i['role']} {r:.1f}:1")
            out.append(_c(not low, f"{p['name']}: every word stands out from what is behind it (WCAG contrast)" + (f" (not: {', '.join(low[:4])})" if low else ""),
                          "fail" if any(float(x.split()[-1].split(':')[0]) < 2.5 for x in low) else "warn"))
        imgs = [i for i in meas["items"] if i.get("img") and i["img"]["nw"]]
        if unit == "mm":
            for i in imgs:
                dpi = min(i["img"]["nw"] / (i["w"] / 96), i["img"]["nh"] / (i["h"] / 96)) if i["img"]["fit"] != "cover" else \
                    max(i["img"]["nw"] / (i["w"] / 96), i["img"]["nh"] / (i["h"] / 96)) * min(i["w"] / i["img"]["nw"], i["h"] / i["img"]["nh"]) / \
                    max(i["w"] / i["img"]["nw"], i["h"] / i["img"]["nh"])
                out.append(_c(dpi >= 150, f"{p['name']}: the photo prints at {dpi:.0f} dpi (150 at least, 300 best)", "warn" if dpi >= 100 else "fail"))
        for q in [i for i in meas["items"] if i["role"] == "qr" and i.get("qr")]:
            out.append(_qr(p["png"], meas, q))
        if faces and p.get("name") in faces:
            covered = []
            for fb in faces[p["name"]]:
                fx, fy, fw, fh = fb
                for i in texts:
                    tx, ty, tw, th = tbox(i)
                    ix = min(fx + fw, tx + tw) - max(fx, tx)
                    iy = min(fy + fh, ty + th) - max(fy, ty)
                    if ix > 0 and iy > 0 and ix * iy > 0.12 * fw * fh and i in meas["items"]:
                        covered.append(i["role"])
            out.append(_c(not covered, f"{p['name']}: no words over a face" + (f" (not: {', '.join(covered[:3])})" if covered else "")))
    if result.get("pdf"):
        from pypdf import PdfReader
        r = PdfReader(result["pdf"])
        want_w, want_h = w + 2 * bleed, h + 2 * bleed
        sizes = [(float(pg.mediabox.width) / 72 * 25.4, float(pg.mediabox.height) / 72 * 25.4) for pg in r.pages]
        okp = len(r.pages) == len(pages) and all(abs(a - want_w) < 0.6 and abs(b - want_h) < 0.6 for a, b in sizes)
        out.append(_c(okp, f"PDF: {len(r.pages)} page(s) of {want_w:.1f} x {want_h:.1f} mm ({w:g} x {h:g} mm + {bleed:g} mm bleed)"
                      + ("" if okp else f" (got {[(round(a, 1), round(b, 1)) for a, b in sizes]})")))
    if unit == "px":
        sz = Image.open(pages[0]["png"]).size
        out.append(_c(sz == (w, h), f"picture is exactly {w} x {h} px" + ("" if sz == (w, h) else f" (got {sz[0]} x {sz[1]})")))
    return out


def _qr(png, meas, q):
    import cv2
    im = Image.open(png).convert("L")
    sc = im.width / meas["w"]
    pad = q["w"] * 0.15
    box = (int(max(0, (q["x"] - pad) * sc)), int(max(0, (q["y"] - pad) * sc)), int(min(im.width, (q["x"] + q["w"] + pad) * sc)), int(min(im.height, (q["y"] + q["h"] + pad) * sc)))
    crop = im.crop(box)
    if crop.width < 300:
        crop = crop.resize((crop.width * 3, crop.height * 3), Image.NEAREST)
    arr = np.asarray(crop)
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
    if not data:  # white quiet zone around the code helps the detector
        arr = np.pad(arr, 40, constant_values=255)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
    return _c(data == q["qr"], f"the QR code scans to {q['qr']}" + ("" if data == q["qr"] else f" (read: {data or 'nothing'})"))
