"""A design's pages to files: each page's HTML is loaded in headless Chrome (ai_pc.core.headless) three ways: once to
read back what the page measured of itself, once for the picture (PNG, true pixels for screen designs, about 300 dpi
for print), and once with every word made invisible, so the checks can see what each word sits on. Print designs
also get a vector PDF at the exact paper size with the bleed.

The page measures itself (MEASURE): text in a box with data-fit shrinks until it fits, never below its floor; then
every element with data-role reports its box, type size, colour, outline, whether it still overflows, and whether
the fonts it asks for are on this PC.
"""
import json
import re
import time
from pathlib import Path

from ai_pc.core import headless
from ai_pc.design.kinds import KINDS, size_of
from ai_pc.design.layouts import PX_PER_MM, build

MEASURE = r"""<script>
(function(){
  function over(el){  // glyphs hang past tight line boxes: a third of the type size below is not overflow, an extra line is
    var fs = parseFloat(getComputedStyle(el).fontSize);
    return el.scrollWidth > el.clientWidth + 1 + fs * 0.04 || el.scrollHeight > el.clientHeight + fs * 0.34;
  }
  function fit(el){
    var min = parseFloat(el.dataset.fit), s = parseFloat(getComputedStyle(el).fontSize), n = 0;
    el.dataset.base = s;
    while (over(el) && s > min && n < 600) { s = Math.max(min, s - Math.max(0.2, s * 0.015)); el.style.fontSize = s + 'px'; n++; }
    el.dataset.fitted = s;
  }
  function installed(fam){
    var c = document.createElement('canvas').getContext('2d'), probe = 'mmmmmmmmmmlliWW@#&0123', out = false;
    ['monospace', 'serif'].forEach(function(base){
      c.font = '40px "' + fam + '", ' + base; var a = c.measureText(probe).width;
      c.font = '40px ' + base; if (a !== c.measureText(probe).width) out = true;
    });
    return out;
  }
  document.fonts.ready.then(function(){
    document.querySelectorAll('[data-fit]').forEach(fit);
    var page = document.querySelector('.page').getBoundingClientRect();
    var out = {w: page.width, h: page.height * document.querySelectorAll('.page').length, items: [], fonts: {}};
    var fams = {};
    document.querySelectorAll('[data-role]').forEach(function(el){
      var r = el.getBoundingClientRect(), cs = getComputedStyle(el), tr = r;
      if (el.classList.contains('t')) { var rg = document.createRange(); rg.selectNodeContents(el); tr = rg.getBoundingClientRect(); }
      var fam = (cs.fontFamily.split(',')[0] || '').replace(/["']/g, '').trim();
      if (el.classList.contains('t')) fams[fam] = 1;
      out.items.push({role: el.dataset.role, text: (el.innerText || '').trim(), x: r.left - page.left, y: r.top - page.top, w: r.width, h: r.height,
        tx: tr.left - page.left, ty: tr.top - page.top, tw: tr.width, th: tr.height,
        size: parseFloat(cs.fontSize), color: cs.color, weight: cs.fontWeight, family: fam, stroke: parseFloat(cs.webkitTextStrokeWidth) || 0,
        strokeColor: cs.webkitTextStrokeColor, shadow: cs.textShadow, over: el.classList.contains('t') ? over(el) : false,
        fit: el.dataset.fit ? parseFloat(el.dataset.fit) : null, fitted: el.dataset.fitted ? parseFloat(el.dataset.fitted) : null,
        base: el.dataset.base ? parseFloat(el.dataset.base) : null,
        text_el: el.classList.contains('t'), tag: el.tagName, qr: el.dataset.qr || null,
        img: el.tagName === 'IMG' ? {nw: el.naturalWidth, nh: el.naturalHeight, fit: cs.objectFit} : null});
    });
    Object.keys(fams).forEach(function(f){ out.fonts[f] = installed(f); });
    var s = document.createElement('script'); s.type = 'application/json'; s.id = 'measure'; s.textContent = JSON.stringify(out);
    document.body.appendChild(s);
  });
})();
</script>"""
HIDE_TEXT = "<style>.t,.t *{color:transparent!important;-webkit-text-stroke-color:transparent!important;text-shadow:none!important}.qr{visibility:hidden}</style>"


def prepare(spec, folder):
    """Photo work before the layout, by the photo agent: a thumbnail's person cut from a green, blue or plain
    backdrop; on a photo post the words go to the end of the picture without faces. Returns the faces (in the
    photo's own fractions) for the check."""
    img = spec.get("image")
    if not img:
        return {}
    from PIL import Image, ImageOps

    from ai_pc.photo import analyze as A
    from ai_pc.photo import ops as PO
    im = ImageOps.exif_transpose(Image.open(img))
    im.load()
    info = {"faces": [(f["box"][0] / im.width, f["box"][1] / im.height, f["box"][2] / im.width, f["box"][3] / im.height) for f in A.faces(im)]}
    if spec["kind"] == "thumbnail" and spec.get("style", "face") == "face" and not spec.get("_cutout"):
        bd = A.backdrop(im)
        if bd["kind"] in ("green", "blue", "plain"):
            out, _ = PO.run("remove_background", im, {})
            box = out.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()  # the person, not the empty frame around them
            if box:
                pad = int(0.03 * max(out.size))
                out = out.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(out.width, box[2] + pad), out.height))
            cut = Path(folder) / f"cutout_{Path(img).stem[:20]}.png"
            out.save(cut)
            spec["_cutout"] = str(cut)
            info["cutout"] = bd["kind"]
    if spec.get("style") == "photo" and info["faces"]:
        low = any(y + hh / 2 > 0.45 for _, y, _, hh in info["faces"])
        spec["_text_at"] = "top" if low else "bottom"
    return info


def faces_on_page(spec, info, meas):
    """The photo's faces in CSS px of a full-page cover photo (posts), for the 'no words over a face' check."""
    if not info.get("faces") or spec.get("style") != "photo":
        return None
    img = next((i for i in meas["items"] if i["role"] == "image" and i.get("img")), None)
    if not img:
        return None
    nw, nh = img["img"]["nw"], img["img"]["nh"]
    s = max(img["w"] / nw, img["h"] / nh)  # object-fit: cover
    ox, oy = img["x"] + (img["w"] - nw * s) / 2, img["y"] + (img["h"] - nh * s) / 2
    return [(ox + x * nw * s, oy + y * nh * s, w * nw * s, h * nh * s) for x, y, w, h in info["faces"]]


def _scale(spec):
    """Device scale for the picture: true pixels for screen designs, ~300 dpi for print (less for big sheets)."""
    w, h, unit, bleed, _ = size_of(spec)
    if unit == "px":
        return 1.0
    longest = max(w, h) + 2 * bleed
    return 300 / 96 if longest <= 220 else 200 / 96 if longest <= 320 else 150 / 96


def page_px(spec):
    w, h, unit, bleed, _ = size_of(spec)
    if unit == "px":
        return w, h
    return (w + 2 * bleed) * PX_PER_MM, (h + 2 * bleed) * PX_PER_MM


def render(spec, folder, stem, pdf=True, bg=True):
    """Every page of the design: {"pages": [{"name", "html", "png", "bg_png", "measure"}], "pdf": path | None, "seconds"}.

    All sides go in one document, stacked; four hidden browsers (each with its own profile) read the measurements,
    take the picture, take the picture with the words hidden, and print the PDF, at the same time; the pictures are
    then cut into one per side."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image
    t0 = time.perf_counter()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pages = build(spec)
    pw, ph = page_px(spec)
    doc = _join(pages)
    hp = folder / f"{stem}.html"
    hp.write_text(doc, encoding="utf-8")
    bp = folder / f"{stem}_bg.html"
    bp.write_text(doc.replace("</head>", HIDE_TEXT + "</head>", 1), encoding="utf-8")
    win = (int(round(pw + 0.49)), int(round(ph * len(pages) + 0.49)))
    sc = _scale(spec)
    all_png, all_bg = folder / f"{stem}_all.png", folder / f"{stem}_all_bg.png"
    pdf_path = folder / f"{stem}.pdf" if pdf and KINDS[spec["kind"]]["unit"] == "mm" else None
    jobs = {"dom": lambda: headless.dom(hp, wait_ms=2500, lane="measure"),
            "png": lambda: headless.png(hp, all_png, win, scale=sc, wait_ms=2500, lane="picture")}
    if bg:
        jobs["bg"] = lambda: headless.png(bp, all_bg, win, scale=1, wait_ms=2500, lane="ground")
    if pdf_path:
        jobs["pdf"] = lambda: headless.pdf(hp, pdf_path, wait_ms=2500, lane="print")
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {k: ex.submit(f) for k, f in jobs.items()}
        res = {k: f.result() for k, f in futs.items()}
    m = re.search(r'<script type="application/json" id="measure">(.*?)</script>', res["dom"], re.S)
    meas = json.loads(m.group(1)) if m else None
    out = []
    full = Image.open(all_png)
    full_bg = Image.open(all_bg) if bg else None
    for k, (name, _) in enumerate(pages):
        page_png = folder / f"{stem}_{name}.png"
        top, bottom = round(k * ph * sc), round((k + 1) * ph * sc)
        full.crop((0, top, round(pw * sc), min(full.height, bottom))).save(page_png)
        item = {"name": name, "html": str(hp), "png": str(page_png), "measure": _page_measure(meas, k, pw, ph) if meas else None}
        if full_bg is not None:
            bpng = folder / f"{stem}_{name}_bg.png"
            full_bg.crop((0, round(k * ph), round(pw), min(full_bg.height, round((k + 1) * ph)))).save(bpng)
            item["bg_png"] = str(bpng)
        out.append(item)
    all_png.unlink(missing_ok=True)
    if bg:
        all_bg.unlink(missing_ok=True)
    return {"pages": out, "pdf": str(pdf_path) if pdf_path else None, "seconds": round(time.perf_counter() - t0, 1), "window": win, "scale": sc}


def _page_measure(meas, k, pw, ph):
    """One side's share of the measurements of the stacked document, in that side's own coordinates."""
    items = []
    for i in meas["items"]:
        cy = i["y"] + i["h"] / 2
        if k * ph - 1 <= cy < (k + 1) * ph + 1:
            j = dict(i, y=i["y"] - k * ph)
            if "ty" in j:
                j["ty"] = j["ty"] - k * ph
            items.append(j)
    return {"w": pw, "h": ph, "items": items, "fonts": meas.get("fonts", {})}


def _join(pages):
    """All pages in one document for the PDF (each page keeps its own styles, scoped by a wrapper)."""
    if len(pages) == 1:
        return pages[0][1].replace("</body>", MEASURE + "</body>")
    # several sides: each keeps its own styles, scoped to it
    heads, bodies = [], []
    for i, (name, html) in enumerate(pages):
        css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
        body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
        # scope every rule of this page to its wrapper so the front's .box does not style the back's
        scoped = []
        for rule in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"@page\{[^}]*\}", "", css)):
            sel, decl = rule
            sel = sel.strip()
            if sel.startswith(":root") or sel in ("html,body", "body", "*"):
                scoped.append(f"{sel}{{{decl}}}" if i == 0 else "")
            else:
                scoped.append(",".join(f".p{i} {s.strip()}" if not s.strip().startswith(".page") else f".p{i}{s.strip()}" for s in sel.split(",")) + f"{{{decl}}}")
        page_rule = re.search(r"@page\{[^}]*\}", css).group(0)
        heads.append(("" if i else page_rule) + "".join(scoped))
        bodies.append(body.replace("<div class='page'", f"<div class='page p{i}'", 1))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{''.join(heads)}</style></head><body>{''.join(bodies)}{MEASURE}</body></html>"
