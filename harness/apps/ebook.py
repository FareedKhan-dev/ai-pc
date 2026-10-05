"""Ebooks: a Word file, Markdown or plain text becomes an EPUB 3 (chapters from the headings, a contents page, a cover
when one is given) that Kindle (Send to Kindle), Google Play Books, Apple Books and every e-reader open. Written by
code with no ebook program; checked by reading the EPUB back: the mimetype first and uncompressed, every file the
package lists present, every page well-formed XHTML, the chapters in order.

  'make an ebook from novel.docx by Ayesha Khan'   'epub from notes.md with cover.jpg'
"""
import datetime as dt
import html
import re
import uuid
import zipfile
from pathlib import Path

NAME, LABEL = "ebook", "Ebooks: EPUB from Word, Markdown or text"
EXAMPLES = ["make an ebook from novel.docx by Ayesha Khan", "epub from notes.md with cover.jpg"]


def chapters_of(path):
    """[(title, [paragraph html])]."""
    p = Path(path)
    chs = []
    if p.suffix.lower() == ".docx":
        from docx import Document
        for para in Document(p).paragraphs:
            t = para.text.strip()
            if not t:
                continue
            if para.style.name.lower().startswith(("heading 1", "title")) or (para.style.name.lower().startswith("heading 2") and not chs):
                chs.append((t, []))
            else:
                if not chs:
                    chs.append(("Start", []))
                runs = "".join(f"<em>{html.escape(r.text)}</em>" if r.italic else f"<strong>{html.escape(r.text)}</strong>" if r.bold else html.escape(r.text)
                               for r in para.runs)
                tag = "h2" if para.style.name.lower().startswith("heading") else "p"
                chs[-1][1].append(f"<{tag}>{runs or html.escape(t)}</{tag}>")
        return chs
    text = p.read_text(encoding="utf-8", errors="replace")
    md = p.suffix.lower() in (".md", ".markdown")
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b:
            continue
        head = re.match(r"^#\s+(.+)$", b) if md else re.match(r"^((?:chapter|part)\s+[\w-]+.*)$", b, re.I)
        if head and "\n" not in b:
            chs.append((head.group(1).strip(), []))
            continue
        if not chs:
            chs.append(("Start", []))
        if md:
            sub = re.match(r"^#{2,6}\s+(.+)$", b)
            if sub:
                chs[-1][1].append(f"<h2>{html.escape(sub.group(1))}</h2>")
                continue
            b = re.sub(r"\*\*(.+?)\*\*", lambda m: "\x01" + m.group(1) + "\x02", b)
            b = html.escape(b).replace("\x01", "<strong>").replace("\x02", "</strong>")
            b = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*", r"<em>\1</em>", b)
            chs[-1][1].append(f"<p>{b}</p>")
        else:
            chs[-1][1].append(f"<p>{html.escape(b)}</p>")
    return chs


def xhtml(title, body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
            f'xml:lang="en"><head><meta charset="utf-8"/><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>'
            f"<body>{body}</body></html>")


def make(src, out, title=None, author=None, cover=None):
    chs = chapters_of(src)
    if not chs:
        raise ValueError("no text in the file")
    title = title or Path(src).stem.replace("_", " ").title()
    author = author or "Unknown"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / (re.sub(r"[^\w-]+", "_", title) + ".epub")
    uid = f"urn:uuid:{uuid.uuid4()}"
    files = {}
    css = "body{font-family:serif;line-height:1.5;margin:0 5%}h1{text-align:center;margin:2em 0 1em}p{text-indent:1.2em;margin:0 0 .4em}" \
          "img.cover{max-width:100%;height:auto;display:block;margin:auto}"
    files["OEBPS/style.css"] = css
    items, spine = [], []
    if cover:
        ext = Path(cover).suffix.lower().lstrip(".").replace("jpg", "jpeg")
        files[f"OEBPS/cover.{ext.replace('jpeg', 'jpg')}"] = Path(cover).read_bytes()
        items.append(f'<item id="cover-image" href="cover.{ext.replace("jpeg", "jpg")}" media-type="image/{ext}" properties="cover-image"/>')
        files["OEBPS/cover.xhtml"] = xhtml("Cover", f'<img class="cover" src="cover.{ext.replace("jpeg", "jpg")}" alt="{html.escape(title)}"/>')
        items.append('<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="cover"/>')
    for i, (t, paras) in enumerate(chs, 1):
        files[f"OEBPS/ch{i:03d}.xhtml"] = xhtml(t, f"<h1>{html.escape(t)}</h1>" + "".join(paras))
        items.append(f'<item id="ch{i:03d}" href="ch{i:03d}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="ch{i:03d}"/>')
    nav = "".join(f'<li><a href="ch{i:03d}.xhtml">{html.escape(t)}</a></li>' for i, (t, _) in enumerate(chs, 1))
    files["OEBPS/nav.xhtml"] = xhtml("Contents", f'<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>{nav}</ol></nav>')
    points = "".join(f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{html.escape(t)}</text></navLabel><content src="ch{i:03d}.xhtml"/></navPoint>'
                     for i, (t, _) in enumerate(chs, 1))
    files["OEBPS/toc.ncx"] = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head>'
                              f'<meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{html.escape(title)}</text></docTitle><navMap>{points}</navMap></ncx>')
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files["OEBPS/content.opf"] = (
        '<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">'
        f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">{uid}</dc:identifier><dc:title>{html.escape(title)}</dc:title>'
        f'<dc:creator>{html.escape(author)}</dc:creator><dc:language>en</dc:language><meta property="dcterms:modified">{now}</meta>'
        + ('<meta name="cover" content="cover-image"/>' if cover else "") + '</metadata><manifest>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="css" href="style.css" media-type="text/css"/>' + "".join(items) + f'</manifest><spine toc="ncx">{"".join(spine)}</spine></package>')
    files["META-INF/container.xml"] = ('<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                                       '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return dest, chs


def check(dest, chs):
    from lxml import etree
    out = []
    with zipfile.ZipFile(dest) as z:
        first = z.infolist()[0]
        out.append(("the mimetype comes first, uncompressed", first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
                    and z.read("mimetype") == b"application/epub+zip"))
        opf = etree.fromstring(z.read("OEBPS/content.opf"))
        ns = {"o": "http://www.idpf.org/2007/opf"}
        hrefs = [i.get("href") for i in opf.findall(".//o:manifest/o:item", ns)]
        out.append(("every file the package lists is there", all(f"OEBPS/{h}" in z.namelist() for h in hrefs)))
        ok = True
        for h in hrefs:
            if h.endswith(".xhtml"):
                try:
                    etree.fromstring(z.read(f"OEBPS/{h}"))
                except etree.XMLSyntaxError:
                    ok = False
        out.append(("every page is well-formed XHTML", ok))
        spine = [i.get("idref") for i in opf.findall(".//o:spine/o:itemref", ns) if i.get("idref").startswith("ch")]
        out.append(("the chapters are in order", spine == [f"ch{i:03d}" for i in range(1, len(chs) + 1)]))
    return out


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\b(?:e-?book|epub|kindle book)\b", c):
        return None
    src = find_file(text, ctx, {".docx", ".md", ".markdown", ".txt"})
    cover = find_file(text, ctx, {".jpg", ".jpeg", ".png"}) if re.search(r"\bcover\b", c) else None
    if not src:
        return None
    by = re.search(r"\bby\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3})", text)
    title = re.search(r"\b(?:called|titled|title)\s+['\"]?([^'\"]+?)['\"]?(?:\s+by\b|$)", text, re.I)
    return {"op": "ebook", "file": src, "cover": cover, "author": by.group(1) if by else None, "title": title.group(1) if title else None}


def run(op, ctx):
    dest, chs = make(op["file"], Path(ctx["out"]) / "ebooks", op.get("title"), op.get("author"), op.get("cover"))
    checks = check(dest, chs)
    bad = [w for w, ok in checks if not ok]
    return (f"EPUB made: {dest} ({len(chs)} chapters" + (", with a cover" if op.get("cover") else "") + "). " +
            ("Checked: " + ", ".join(w for w, _ in checks) if not bad else "NOT right: " + ", ".join(bad)) +
            ". To read it on Kindle, send it with Amazon's Send to Kindle.")
