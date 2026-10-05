"""PDF work done by code (pypdf), with the extra pages drawn by Word and PowerPoint in the background: a pack of several
documents with a cover and bookmarks, page numbers, a watermark, compression, page selection, splitting. Every result is
checked on the PDF itself: pages, bookmarks, the page-number text on each page, the watermark on each page, the text
still the same after compression.

  r = pack([("Report", "r.pdf"), ("Deck", "d.pdf")], "pack.pdf", cover={"title": ..., "subtitle": ...}, numbers=True,
           watermark="DRAFT", server=render.Server())       -> {"path", "pages", "outline", "checks": [...]}
  compress(src, out)   select(src, out, pages)   delete(src, out, pages)   rotate(src, out, pages, 90)   split(src, folder)
"""
import datetime as _dt
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation

from . import render as RN

A4 = (595.28, 841.89)


class PdfError(Exception):
    pass


def info(path):
    r = PdfReader(str(path))
    out = []

    def walk(items, depth=0):
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1)
            else:
                try:
                    out.append({"title": str(it.title), "page": r.get_destination_page_number(it) + 1, "depth": depth})
                except Exception:  # noqa: BLE001
                    out.append({"title": str(getattr(it, "title", "")), "page": None, "depth": depth})
    try:
        walk(r.outline)
    except Exception:  # noqa: BLE001
        pass
    sizes = [(round(float(p.mediabox.width)), round(float(p.mediabox.height))) for p in r.pages]
    return {"pages": len(r.pages), "outline": out, "kb": round(Path(path).stat().st_size / 1024, 1), "sizes": sizes}


def texts(path):
    return RN.text(str(path))


def visible_texts(path):
    """Each page's text that lies inside the page (a mark placed off the page is in the file but nobody sees it)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    out = []
    for i in range(len(doc)):
        pg = doc[i]
        pw, ph = pg.get_size()
        out.append(pg.get_textpage().get_text_bounded(0, 0, pw, ph))
    return out


def _job(server, job, timeout=240):
    return server.run(job, timeout=timeout) if server is not None else RN.office(job)


# ------------------------------------------------------------------------------------------------ pages drawn by Office
def cover_pdf(folder, title, subtitle=None, lines=(), accent="1F3864", server=None):
    """A one-page A4 cover drawn by Word: the title, a subtitle, a rule, the date and any lines (prepared by ...)."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    from . import docx_build as DB
    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.5)
    p = d.add_paragraph()
    p.paragraph_format.space_before = Pt(220)
    r = p.add_run(title)
    r.font.size, r.font.bold, r.font.color.rgb = Pt(34), True, RGBColor.from_string(accent)
    if subtitle:
        q = d.add_paragraph()
        rq = q.add_run(subtitle)
        rq.font.size, rq.font.color.rgb = Pt(16), RGBColor.from_string("595959")
    rule = d.add_paragraph()
    DB._rule(rule, accent, size=18, where="top", space=1)
    for line in list(lines) + [_dt.date.today().strftime("%d %B %Y")]:
        q = d.add_paragraph()
        rq = q.add_run(str(line))
        rq.font.size, rq.font.color.rgb = Pt(12), RGBColor.from_string("595959")
        q.paragraph_format.space_after = Pt(2)
        q.alignment = WD_ALIGN_PARAGRAPH.LEFT
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "_cover.docx"
    d.save(str(src))
    pdf = folder / "_cover.pdf"
    r = _job(server, {"app": "word", "src": str(src.resolve()), "pdf": str(pdf.resolve())})
    if not r.get("ok") or not pdf.exists():
        raise PdfError(f"the cover could not be drawn: {r.get('error')}")
    return pdf


def _overlay_deck(folder, name, size_pt, pages, server=None):
    """A PDF of transparent pages drawn by PowerPoint, size_pt = (width, height) in points, one page per entry of
    `pages`: [(text, x_pt, y_pt_from_top, w_pt, h_pt, size_pt, colour, alpha, rotation, align)]. The slides have no
    background, so only the marks land on the page they are stamped on."""
    from lxml import etree
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(size_pt[0] * 12700)), Emu(int(size_pt[1] * 12700))
    blank = prs.slide_layouts[6]
    for items in pages:
        s = prs.slides.add_slide(blank)
        s.background.fill.background()  # no fill: transparent
        for ph in list(s.placeholders):
            ph._element.getparent().remove(ph._element)
        for text, x, y, w, h, size, colour, alpha, rot, align in items:
            tb = s.shapes.add_textbox(Emu(int(x * 12700)), Emu(int(y * 12700)), Emu(int(w * 12700)), Emu(int(h * 12700)))
            tb.rotation = rot
            tf = tb.text_frame
            tf.word_wrap = False
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = tf.paragraphs[0]
            p.alignment = {"left": PP_ALIGN.LEFT, "right": PP_ALIGN.RIGHT}.get(align, PP_ALIGN.CENTER)
            r = p.add_run()
            r.text = text
            r.font.size, r.font.bold, r.font.name = Pt(size), size > 40, "Calibri"
            r.font.color.rgb = RGBColor.from_string(colour)
            if alpha < 1:
                clr = r._r.find(qn("a:rPr")).find(qn("a:solidFill")).find(qn("a:srgbClr"))
                a = etree.SubElement(clr, qn("a:alpha"))
                a.set("val", str(int(alpha * 100000)))
    folder = Path(folder)
    src = folder / f"_{name}.pptx"
    prs.save(str(src))
    pdf = folder / f"_{name}.pdf"
    r = _job(server, {"app": "powerpoint", "src": str(src.resolve()), "pdf": str(pdf.resolve())})
    if not r.get("ok") or not pdf.exists():
        raise PdfError(f"the {name} layer could not be drawn: {r.get('error')}")
    return pdf


ZONES = [("centre", 0.38, 0.62), ("right", 0.70, 0.95), ("left", 0.05, 0.30)]


def free_zone(pdf_path, k):
    """Where a page number can go on page k (0-based) without touching what is printed there: bottom centre, else bottom
    right, else bottom left, else top right. (zone, x0, x1, y_bottom, y_top) in points from the page's bottom-left."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf_path))
    page = doc[k]
    pw, ph = page.get_size()
    tp = page.get_textpage()
    boxes = [tp.get_charbox(i) for i in range(tp.count_chars())]
    band = [(0.012 * ph, 0.058 * ph)]

    def clear(x0, x1, y0, y1):
        return not any(b[0] < x1 and b[2] > x0 and b[1] < y1 and b[3] > y0 for b in boxes)
    for name, a, b in ZONES:
        if clear(a * pw, b * pw, band[0][0], band[0][1]):
            return name, a * pw, b * pw, band[0][0], band[0][1], pw, ph
    if clear(0.70 * pw, 0.95 * pw, 0.945 * ph, 0.985 * ph):
        return "right", 0.70 * pw, 0.95 * pw, 0.945 * ph, 0.985 * ph, pw, ph
    return "centre", 0.38 * pw, 0.62 * pw, band[0][0], band[0][1], pw, ph


def _render_small(path, scale=0.12):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    return [doc[i].render(scale=scale).to_pil().convert("L") for i in range(len(doc))]


# ------------------------------------------------------------------------------------------------ the operations
def pack(parts, out, cover=None, numbers=False, watermark=None, server=None, compress_it=True):
    """Several PDFs as one: an optional cover, a bookmark per part, 'Page i of N' on every page after the cover (where the
    page has room for it, never over its own footer), an optional watermark across every page."""
    out = Path(out)
    folder = out.parent
    folder.mkdir(parents=True, exist_ok=True)
    w = PdfWriter()
    bookmarks = []
    if cover:
        cp = cover_pdf(folder, cover.get("title") or "Report", cover.get("subtitle"), cover.get("lines") or (), cover.get("accent") or "1F3864", server)
        w.append(str(cp), outline_item=cover.get("title") or "Cover")
        bookmarks.append(cover.get("title") or "Cover")
    first = len(w.pages)
    for title, path in parts:
        if not Path(path).exists():
            raise PdfError(f"no PDF for {title} ({path})")
        w.append(str(path), outline_item=title)
        bookmarks.append(title)
    n_body = len(w.pages) - first
    plain = folder / "_plain.pdf"
    with open(plain, "wb") as f:
        w.write(f)
    zones = []
    if numbers or watermark:
        sizes = [(float(pg.mediabox.width), float(pg.mediabox.height)) for pg in w.pages]
        W, H = max(x for x, _ in sizes), max(y for _, y in sizes)
        layers = []
        for i, (pw, ph) in enumerate(sizes):
            items = []
            if watermark:
                side = min(pw, ph)
                fs = max(48, round(side / 595 * 120))
                bw, bh = side * 1.25, fs * 1.6
                cx, cy = pw / 2, ph / 2
                items.append((str(watermark), cx - bw / 2, (ph - cy) - bh / 2, bw, bh, fs, "9CA3AF", 0.28, -45 if ph >= pw else -30, "centre"))
            if numbers and i >= first:
                z, x0, x1, y0, y1, _, _ = free_zone(plain, i)
                zones.append(z)
                items.append((f"Page {i - first + 1} of {n_body}", x0, ph - y1, x1 - x0, y1 - y0, 9.5, "595959", 1.0, 0, z))  # from the page's top
            layers.append(items)
        lay = _overlay_deck(folder, "marks", (W, H), layers, server)
        ov = PdfReader(str(lay))
        for i, page in enumerate(w.pages):
            o = ov.pages[i]
            # the layer page is as big as the biggest page; its top-left corner goes on this page's top-left corner
            tx = float(page.mediabox.left)
            ty = float(page.mediabox.bottom) + float(page.mediabox.height) - H
            page.merge_transformed_page(o, Transformation().translate(tx, ty), over=True)
    if compress_it:
        w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    tmp = out.with_suffix(".tmp.pdf")
    with open(tmp, "wb") as f:
        w.write(f)
    tmp.replace(out)
    rep = check_pack(out, bookmarks, first, n_body, numbers, watermark, plain)
    if zones:
        from collections import Counter
        rep["number_places"] = dict(Counter(zones))
    return {"path": str(out), **rep}


def check_pack(path, bookmarks, first, n_body, numbers, watermark, plain=None):
    inf = info(path)
    pages = visible_texts(path)
    checks = [{"op": "pages", "ok": inf["pages"] == first + n_body, "what": f"{inf['pages']} pages ({first} cover + {n_body})"}]
    titles = [o["title"] for o in inf["outline"] if o["depth"] == 0]
    checks.append({"op": "bookmarks", "ok": titles[:len(bookmarks)] == bookmarks, "what": " | ".join(titles[:8])})
    if numbers:
        miss = [i + 1 for i in range(n_body) if f"Page {i + 1} of {n_body}" not in " ".join((pages[first + i] or "").split())]
        checks.append({"op": "page numbers", "ok": not miss, "what": f"'Page i of {n_body}' on {n_body - len(miss)}/{n_body} pages" + (f"; missing on {miss[:5]}" if miss else "")})
    if watermark and plain is not None:  # a drawn mark has no text to find: the page must look different in its middle
        from PIL import ImageChops, ImageStat
        a, b = _render_small(plain), _render_small(path)
        miss = []
        for i, (x, y) in enumerate(zip(a, b)):
            wd, ht = x.size
            box = (int(wd * 0.25), int(ht * 0.3), int(wd * 0.75), int(ht * 0.7))
            if ImageStat.Stat(ImageChops.difference(x.crop(box), y.crop(box))).mean[0] < 0.4:
                miss.append(i + 1)
        checks.append({"op": "watermark", "ok": not miss, "what": f"'{watermark}' drawn across {len(b) - len(miss)}/{len(b)} pages" + (f"; not on {miss[:5]}" if miss else "")})
    return {"pages": inf["pages"], "outline": titles, "kb": inf["kb"], "checks": checks}


def compress(src, out, quality=60, max_px=1800):
    """Smaller: images re-encoded (JPEG at `quality`, at most `max_px` on the long side), content streams compressed,
    identical objects shared. Checked: the same pages with the same text."""
    from PIL import Image
    before = texts(src)
    w = PdfWriter(clone_from=str(src))
    imgs = 0
    for page in w.pages:
        for img in page.images:
            try:
                im = img.image
                if im is None:
                    continue
                if max(im.size) > max_px:
                    im.thumbnail((max_px, max_px), Image.LANCZOS)
                if im.mode in ("RGBA", "P", "LA"):
                    im = im.convert("RGB")
                img.replace(im, quality=quality)
                imgs += 1
            except Exception:  # noqa: BLE001  (an image pypdf cannot re-encode stays as it is)
                continue
        page.compress_content_streams()
    w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    out = Path(out)
    with open(out, "wb") as f:
        w.write(f)
    after = texts(out)
    kb0, kb1 = round(Path(src).stat().st_size / 1024, 1), round(out.stat().st_size / 1024, 1)
    same = len(before) == len(after) and all(" ".join((a or "").split()) == " ".join((b or "").split()) for a, b in zip(before, after))
    return {"path": str(out), "kb_before": kb0, "kb_after": kb1, "images": imgs,
            "checks": [{"op": "smaller", "ok": kb1 < kb0, "what": f"{kb0} KB -> {kb1} KB ({imgs} image(s) re-encoded)"},
                       {"op": "same pages and text", "ok": same, "what": f"{len(after)} pages, text {'unchanged' if same else 'CHANGED'}"}]}


def parse_pages(spec, n):
    """'2-4, 7, 9-' -> [2, 3, 4, 7, 9, ..., n] (1-based, within the document)."""
    out = []
    for part in re.split(r"\s*(?:,|and)\s*", str(spec).strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)?\s*(?:-|to)\s*(\d+)?", part)
        if m and (m.group(1) or m.group(2)):
            a, b = int(m.group(1) or 1), int(m.group(2) or n)
            out += list(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            out.append(int(part))
        elif part in ("last", "the last"):
            out.append(n)
    out = [p for p in out if 1 <= p <= n]
    if not out:
        raise PdfError(f"no pages '{spec}' in a {n}-page PDF")
    return out


def select(src, out, pages):
    r = PdfReader(str(src))
    ks = parse_pages(pages, len(r.pages)) if not isinstance(pages, list) else pages
    w = PdfWriter()
    for k in ks:
        w.add_page(r.pages[k - 1])
    with open(out, "wb") as f:
        w.write(f)
    got = info(out)["pages"]
    return {"path": str(out), "pages": got, "checks": [{"op": "pages", "ok": got == len(ks), "what": f"{got} page(s): {ks[:12]}"}]}


def delete(src, out, pages):
    r = PdfReader(str(src))
    n = len(r.pages)
    gone = set(parse_pages(pages, n))
    if len(gone) >= n:
        raise PdfError("that would delete every page")
    return select(src, out, [k for k in range(1, n + 1) if k not in gone])


def rotate(src, out, pages, angle=90):
    r = PdfReader(str(src))
    ks = set(parse_pages(pages, len(r.pages))) if pages not in (None, "all") else set(range(1, len(r.pages) + 1))
    w = PdfWriter(clone_from=str(src))
    for k in ks:
        w.pages[k - 1].rotate(int(angle))
    with open(out, "wb") as f:
        w.write(f)
    rr = PdfReader(str(out))
    ok = all(int(rr.pages[k - 1].get("/Rotate", 0)) % 360 == (int(r.pages[k - 1].get("/Rotate", 0)) + int(angle)) % 360 for k in ks)
    return {"path": str(out), "pages": len(rr.pages), "checks": [{"op": "rotated", "ok": ok, "what": f"{len(ks)} page(s) by {angle} degrees"}]}


def split(src, folder, by="bookmarks"):
    """One PDF per top-level bookmark (or per page)."""
    r = PdfReader(str(src))
    n = len(r.pages)
    marks = [o for o in info(src)["outline"] if o["depth"] == 0 and o["page"]]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    outs = []
    if by == "bookmarks" and marks:
        starts = [(m["title"], m["page"]) for m in marks]
        for i, (title, a) in enumerate(starts):
            b = (starts[i + 1][1] - 1) if i + 1 < len(starts) else n
            name = re.sub(r"[^\w\- ]+", "", title).strip()[:60] or f"part {i + 1}"
            outs.append(select(src, folder / f"{i + 1:02d} {name}.pdf", list(range(a, b + 1)))["path"])
    else:
        for k in range(1, n + 1):
            outs.append(select(src, folder / f"page {k:03d}.pdf", [k])["path"])
    total = sum(info(p)["pages"] for p in outs)
    return {"files": outs, "checks": [{"op": "pages kept", "ok": total == n, "what": f"{len(outs)} file(s), {total}/{n} pages"}]}
