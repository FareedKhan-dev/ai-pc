"""Is the page the design? The page is opened in headless Chrome at the design's own size and measured from inside: every
element's box against the box the design gives it, every text there and not spilling out of its box, every font really
loaded. When the design's own picture is at hand (Figma's PNG of the frame, Canva's PNG of the page), a screenshot of the
page is compared with it too: shapes (SSIM) and colour, cell by cell, so a miss can be named and found. A side-by-side
picture (design | page | differences) is saved to .out/compare.png.

  r = check(folder)  -> {"ok", "placed": [in place, total], "worst": [...], "texts": {...}, "fonts_missing": [...],
                         "picture": {"ssim", "delta_e", "cells"} or None, "lines": [sentences for the person]}
"""
import html
import json
import re
from pathlib import Path

from ai_pc.core import headless

TOL = 3.0  # px: closer than this is "where the design puts it"

MEASURE = """<script>
(function () {
  var ROOT = %(root)s, CLASSES = %(classes)s, FAMILIES = %(families)s;
  function has(f) {
    var c = document.createElement('canvas').getContext('2d'), s = 'mmmmmmmmmmlli1WQ@#&';
    c.font = '72px monospace'; var a = c.measureText(s).width; c.font = '72px "' + f + '", monospace'; var b = c.measureText(s).width;
    c.font = '72px serif'; var a2 = c.measureText(s).width; c.font = '72px "' + f + '", serif'; var b2 = c.measureText(s).width;
    return a !== b || a2 !== b2;
  }
  function go() {
    var root = document.querySelector('.' + ROOT); if (!root) { return; }
    var r0 = root.getBoundingClientRect(), out = {};
    CLASSES.forEach(function (c) {
      var e = document.querySelector('.' + CSS.escape(c)); if (!e) { return; }
      var r = e.getBoundingClientRect();
      out[c] = [r.left - r0.left, r.top - r0.top, r.width, r.height, (e.scrollWidth || 0) - (e.clientWidth || 0),
                (e.scrollHeight || 0) - (e.clientHeight || 0), (e.textContent || '').slice(0, 3000)];
    });
    var fonts = {}; FAMILIES.forEach(function (f) { fonts[f] = has(f); });
    var pre = document.createElement('pre'); pre.id = '__measure';
    pre.textContent = JSON.stringify({boxes: out, fonts: fonts, height: root.scrollHeight, width: root.scrollWidth});
    document.body.appendChild(pre);
  }
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { setTimeout(go, 30); }); }
  else { window.addEventListener('load', go); }
})();
</script>"""


class CheckError(Exception):
    pass


def measure(folder, meta, wait_ms=4000):
    """The page's own measurements, taken in headless Chrome at the design's width (a copy of the page with a measuring script)."""
    folder = Path(folder)
    src = (folder / "index.html").read_text(encoding="utf-8")
    script = MEASURE % {"root": json.dumps(meta["root"]), "classes": json.dumps(list(meta["elements"])),
                        "families": json.dumps(sorted(meta.get("fonts") or {}))}
    out = folder / ".out"
    out.mkdir(exist_ok=True)
    page = src.replace("<head>", '<head>\n  <base href="../">', 1)
    page = page.replace("</body>", script + "\n</body>", 1) if "</body>" in page else page + script
    tmp = out / "measure.html"
    tmp.write_text(page, encoding="utf-8")
    w, h = int(round(meta["w"])), int(round(meta["h"]))
    dom, err, _ = headless._run(["--dump-dom", f"--window-size={max(w, 320)},{max(min(h, 16000), 240)}", f"--virtual-time-budget={int(wait_ms)}"],
                                tmp.resolve().as_uri(), 120, "code")
    m = re.search(r'<pre id="__measure">(.*?)</pre>', dom, re.S)
    if not m:
        raise CheckError("the page did not report its measurements (" + err.strip()[-200:] + ")")
    return json.loads(html.unescape(m.group(1)))


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def boxes(meta, got, tol=TOL):
    """Each element against the design: -> (rows, in place, total). A row: (class, element, dx, dy, dw, dh) or (class, element, None)."""
    rows, ok = [], 0
    for cls, e in meta["elements"].items():
        if cls == meta["root"]:
            continue
        g = got["boxes"].get(cls)
        if g is None:
            rows.append((cls, e, None))
            continue
        x, y, w, h = e["box"]
        dx, dy, dw, dh = g[0] - x, g[1] - y, g[2] - w, g[3] - h
        text = e.get("type") == "TEXT"
        wt = max(tol, (0.08 if text else 0.02) * w)  # a text's width follows its font, a little wider or narrower is fine
        ht = max(tol, (0.3 * h if text and h < 40 else 0.08 * h) if text else 0.02 * h)
        good = abs(dx) <= tol and abs(dy) <= tol and abs(dw) <= wt and abs(dh) <= ht
        # centred or right-aligned text that is a little narrower or wider moves its left edge by half the difference
        if text and not good and abs(dy) <= tol and abs(dh) <= ht and abs(dw) <= wt and abs(dx) <= abs(dw) / 2 + tol:
            good = True
        ok += good
        rows.append((cls, e, dx, dy, dw, dh) if not good else (cls, e, 0.0, 0.0, 0.0, 0.0))
    return rows, ok, len(rows)


def describe(row):
    cls, e, *d = row
    nm = e.get("name") or cls
    if d[0] is None:
        return f"'{nm}' is missing from the page"
    dx, dy, dw, dh = d
    parts = []
    if abs(dy) > TOL:
        parts.append(f"{abs(dy):.0f} px {'lower' if dy > 0 else 'higher'}")
    if abs(dx) > TOL:
        parts.append(f"{abs(dx):.0f} px {'right' if dx > 0 else 'left'}")
    if abs(dw) > TOL:
        parts.append(f"{abs(dw):.0f} px {'wider' if dw > 0 else 'narrower'}")
    if abs(dh) > TOL:
        parts.append(f"{abs(dh):.0f} px {'taller' if dh > 0 else 'shorter'}")
    return f"'{nm}' is " + ", ".join(parts) if parts else f"'{nm}' is in place"


def texts(meta, got):
    present, spill, longer, missing = 0, [], [], []
    for cls, e in meta["elements"].items():
        if e.get("type") != "TEXT":
            continue
        g = got["boxes"].get(cls)
        if g is None:
            missing.append(e.get("name") or cls)
            continue
        if _squash(g[6]) == _squash(e.get("text", "")):
            present += 1
        else:
            missing.append(e.get("name") or cls)
        ox, oy = g[4] or 0, g[5] or 0
        if (e.get("nowrap") and ox > 2) or (e.get("fixed_h") and (oy > 2 or ox > 2)):
            spill.append(f"'{(e.get('text') or '').strip()[:40]}' ({max(ox, oy):.0f} px past its box)")
        elif not e.get("fixed_h") and g[3] - e["box"][3] > max(6, 0.4 * e["box"][3]):
            longer.append(f"'{(e.get('text') or '').strip()[:40]}' ({g[3] - e['box'][3]:.0f} px taller: it wraps onto more lines)")
    total = sum(1 for e in meta["elements"].values() if e.get("type") == "TEXT")
    return {"present": present, "total": total, "missing": missing, "spill": spill, "longer": longer}


# ---------------------------------------------------------------- pictures
def _load(path):
    import cv2
    import numpy as np
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise CheckError(f"cannot read {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:  # see-through parts on white, as a browser shows them
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3].astype(np.float32) * a + 255.0 * (1 - a)).astype(np.uint8)
    return img


def _ssim(x, y):
    import cv2
    import numpy as np
    x, y = x.astype(np.float64), y.astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = cv2.GaussianBlur(x, (11, 11), 1.5), cv2.GaussianBlur(y, (11, 11), 1.5)
    sxx = cv2.GaussianBlur(x * x, (11, 11), 1.5) - mx * mx
    syy = cv2.GaussianBlur(y * y, (11, 11), 1.5) - my * my
    sxy = cv2.GaussianBlur(x * y, (11, 11), 1.5) - mx * my
    return ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))


def picture(render_png, ref_png, out_png=None, meta=None, rows=None):
    """The page's screenshot against the design's own picture -> {"ssim", "delta_e", "cells": [(score, where, near)]}."""
    import cv2
    import numpy as np
    a, b = _load(render_png), _load(ref_png)
    hb, wb = b.shape[:2]
    a = cv2.resize(a, (wb, max(1, int(round(a.shape[0] * wb / a.shape[1])))), interpolation=cv2.INTER_AREA)
    h = min(a.shape[0], hb)
    a, b = a[:h], b[:h]
    f = min(1.0, 900.0 / wb)
    if f < 1:  # both made smaller the same way (the same target size), so equal pictures stay equal
        size = (max(1, int(round(wb * f))), max(1, int(round(h * f))))
        a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
        b = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    smap = _ssim(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    la = cv2.cvtColor(a.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    lb = cv2.cvtColor(b.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    de = np.sqrt(((la - lb) ** 2).sum(axis=2))
    # cells: 3 across; down the page, one row per ~ a third of the width (a long page gets more rows)
    hh, ww = smap.shape
    nr = max(3, min(12, int(round(hh / max(1, ww / 3)))))
    cells = []
    scale = (meta["w"] / ww) if meta else 1.0
    for i in range(nr):
        for j in range(3):
            y0, y1, x0, x1 = i * hh // nr, (i + 1) * hh // nr, j * ww // 3, (j + 1) * ww // 3
            s = float(smap[y0:y1, x0:x1].mean())
            d = float(de[y0:y1, x0:x1].mean())
            where = f"{['left', 'middle', 'right'][j]}, {int(y0 * scale)}-{int(y1 * scale)} px down"
            near = _near(meta, (x0 * scale, y0 * scale, x1 * scale, y1 * scale)) if meta else []
            cells.append((round(s, 3), round(d, 1), where, near))
    cells.sort(key=lambda c: c[0])
    if out_png:
        diff = np.clip(de * 6, 0, 255).astype(np.uint8)
        heat = cv2.applyColorMap(diff, cv2.COLORMAP_INFERNO)
        gap = np.full((a.shape[0], 8, 3), 255, np.uint8)
        cv2.imwrite(str(out_png), np.hstack([b, gap, a, gap, heat]))
    return {"ssim": round(float(smap.mean()), 3), "delta_e": round(float(de.mean()), 2), "cells": cells[:4]}


def _near(meta, rect):
    """The named elements in a part of the page (the biggest texts and boxes first)."""
    x0, y0, x1, y1 = rect
    hits = []
    for cls, e in meta["elements"].items():
        if cls == meta["root"]:
            continue
        x, y, w, h = e["box"]
        ix = max(0.0, min(x + w, x1) - max(x, x0))
        iy = max(0.0, min(y + h, y1) - max(y, y0))
        if ix * iy > 0.3 * min(w * h, (x1 - x0) * (y1 - y0)) and w * h < 0.9 * (meta["w"] * meta["h"]):
            hits.append((e.get("type") == "TEXT", w * h, e.get("name") or cls))
    hits.sort(reverse=True)
    return [h[2] for h in hits[:3]]


# ---------------------------------------------------------------- all of it
def check(folder, shot=True):
    folder = Path(folder)
    meta = json.loads((folder / "design" / "design.json").read_text(encoding="utf-8"))
    got = measure(folder, meta)
    rows, ok, total = boxes(meta, got)
    bad = sorted((r for r in rows if r[2] is None or max(abs(v) for v in r[2:]) > 0), key=lambda r: -1e9 if r[2] is None else -max(abs(v) for v in r[2:]))
    tx = texts(meta, got)
    fonts_missing = sorted(f for f, has in (got.get("fonts") or {}).items() if not has)
    pic = None
    ref = folder / "design" / "reference.png"
    if shot:
        shot_png = folder / ".out" / "page.png"
        w, h = int(round(meta["w"])), int(round(min(meta["h"], 16000)))
        headless.png(folder / "index.html", shot_png, (w, h), scale=1, wait_ms=3000, lane="code")
        if ref.exists():
            pic = picture(shot_png, ref, folder / ".out" / "compare.png", meta, rows)
    lines = [f"{ok}/{total} elements where the design puts them (within {TOL:.0f} px)"]
    if bad:
        lines.append("off: " + "; ".join(describe(r) for r in bad[:4]))
    lines.append(f"{tx['present']}/{tx['total']} texts on the page" + (f" (missing or changed: {', '.join(tx['missing'][:4])})" if tx["missing"] else ""))
    if tx["spill"]:
        lines.append("spilling out of their boxes: " + "; ".join(tx["spill"][:3]))
    if tx["longer"]:
        lines.append("wrapping differently: " + "; ".join(tx["longer"][:3]))
    fams = sorted(meta.get("fonts") or {})
    if fams:
        lines.append(("fonts loaded: " + ", ".join(f for f in fams if f not in fonts_missing)) if not fonts_missing else
                     f"fonts not available here (a stand-in is used): {', '.join(fonts_missing)}")
    if pic:
        verdict = "looks the same as" if pic["ssim"] >= 0.9 else "is close to" if pic["ssim"] >= 0.8 else "differs from"
        lines.append(f"the page {verdict} the design's picture (similarity {pic['ssim']:.2f}, colour difference {pic['delta_e']:.1f})"
                     + (f"; least alike: {pic['cells'][0][2]}" + (f" (near {', '.join(pic['cells'][0][3])})" if pic['cells'][0][3] else "")
                        if pic["ssim"] < 0.95 else ""))
    good = total and ok / total >= 0.9 and not tx["missing"] and not tx["spill"] and (pic is None or pic["ssim"] >= 0.8)
    return {"ok": bool(good), "placed": [ok, total], "worst": [describe(r) for r in bad[:8]], "texts": tx, "fonts_missing": fonts_missing,
            "picture": pic, "lines": lines, "height": got.get("height")}
