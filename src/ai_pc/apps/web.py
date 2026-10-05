"""Web pages by code (headless Chrome runs the page's scripts, nothing shows on screen): a page's readable text (menus,
footers, scripts and adverts left out) saved as Markdown, its tables saved to Excel, its links listed, and the page
saved as a PDF or a full-length picture.

  'read https://example.com/article'   'tables from https://example.com/prices'   'links on https://example.com'
  'save https://example.com as pdf'   'screenshot of https://example.com'
"""
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

NAME, LABEL = "web", "Web pages: readable text, tables to Excel, links, PDF, screenshots"
EXAMPLES = ["read https://example.com/article", "tables from https://example.com/prices", "save https://example.com as pdf"]
SKIP = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button")


def page(url):
    """The page's HTML after its scripts ran, as an lxml tree."""
    from lxml import html as lh

    from ai_pc.core import headless
    return lh.fromstring(headless.dom(url, wait_ms=2500, lane="apps")), url


def readable(tree):
    """Title and the article's headings, paragraphs and list items, in order, as Markdown."""
    for bad in tree.xpath("|".join(f"//{t}" for t in SKIP)):
        bad.drop_tree()
    for bad in tree.xpath("//*[contains(@class,'cookie') or contains(@class,'advert') or contains(@id,'cookie') or @aria-hidden='true']"):
        bad.drop_tree()
    title = (tree.findtext(".//title") or "").strip()
    main = (tree.xpath("//article") or tree.xpath("//main") or tree.xpath("//body") or [tree])[0]
    out = [f"# {title}"] if title else []
    for el in main.iter("h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre"):
        t = " ".join(el.text_content().split())
        if len(t) < 2:
            continue
        if el.tag in ("h1", "h2", "h3", "h4"):
            out.append("#" * int(el.tag[1]) + " " + t)
        elif el.tag == "li":
            out.append(f"- {t}")
        elif el.tag == "blockquote":
            out.append(f"> {t}")
        else:
            out.append(t)
    seen, md = set(), []
    for line in out:  # a heading repeated as the title, nested list items: once each
        if line not in seen:
            seen.add(line)
            md.append(line)
    return "\n\n".join(md)


def tables(tree):
    out = []
    for t in tree.iter("table"):
        rows = []
        for tr in t.iter("tr"):
            cells = [" ".join(td.text_content().split()) for td in tr if td.tag in ("td", "th")]
            if any(cells):
                rows.append(cells)
        if len(rows) > 1:
            out.append(rows)
    return out


def links(tree, base):
    out, seen = [], set()
    for a in tree.iter("a"):
        href = a.get("href") or ""
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        u = urljoin(base, href)
        if u not in seen:
            seen.add(u)
            out.append((" ".join(a.text_content().split()) or u, u))
    return out


def _num(s):
    t = re.sub(r"(?i)^(?:rs\.?|pkr)\s*", "", s.replace(",", "").strip())
    return float(t) if re.fullmatch(r"-?\d+(?:\.\d+)?", t) else s


def parse(text, ctx):
    m = re.search(r"((?:https?://|file:///)\S+)", text)
    if not m or re.search(r"\b(?:postman|newman|collection|github|wordpress|shopify)\b", text, re.I):
        return None  # an address inside another program's request is that program's
    url, c = m.group(1).rstrip(".,)"), text.lower()
    if re.search(r"\btables?\b", c):
        return {"op": "tables", "url": url}
    if re.search(r"\blinks?\b", c):
        return {"op": "links", "url": url}
    if re.search(r"\bpdf\b", c):
        return {"op": "pdf", "url": url}
    if re.search(r"\bscreenshot\b|\bpicture of\b|\bimage of\b", c):
        return {"op": "shot", "url": url}
    if re.search(r"\b(?:read|text|article|summari[sz]e|what does|get)\b", c):  # 'open <address>' is the desktop's: the browser
        return {"op": "read", "url": url}
    return None


def run(op, ctx):
    out = Path(ctx["out"]) / "web"
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", (urlparse(op["url"]).netloc + urlparse(op["url"]).path).strip("/"))[:60] or "page"
    from ai_pc.core import headless
    if op["op"] == "pdf":
        r = headless.pdf(op["url"], out / f"{stem}.pdf", wait_ms=2500, lane="apps")
        from pypdf import PdfReader
        return f"Saved as PDF: {r['path']} ({len(PdfReader(r['path']).pages)} pages)."
    if op["op"] == "shot":
        r = headless.png(op["url"], out / f"{stem}.png", size=(1366, 2400), wait_ms=2500, lane="apps")
        return f"Picture of the page: {r['path']}."
    tree, url = page(op["url"])
    if op["op"] == "read":
        md = readable(tree)
        dest = out / f"{stem}.md"
        dest.write_text(md, encoding="utf-8")
        words = len(md.split())
        lines = [ln for ln in md.splitlines() if ln.strip()]
        return f"{words} words read from the page; saved as {dest}. It starts: " + " / ".join(lines[:3])[:300]
    if op["op"] == "tables":
        ts = tables(tree)
        if not ts:
            return "No tables on that page."
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for i, rows in enumerate(ts, 1):
            ws = wb.create_sheet(f"Table {i}")
            for r in rows:
                ws.append([_num(x) if j else x for j, x in enumerate(r)])
        dest = out / f"{stem}.tables.xlsx"
        wb.save(dest)
        return f"{len(ts)} table(s) ({', '.join(f'{len(t) - 1} rows' for t in ts)}) saved to {dest} (numbers kept as numbers)."
    ls = links(tree, url)
    dest = out / f"{stem}.links.csv"
    import csv
    with dest.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Text", "Address"])
        w.writerows(ls)
    return f"{len(ls)} links saved to {dest}:\n" + "\n".join(f"- {t[:60]}: {u}" for t, u in ls[:10])
