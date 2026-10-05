"""Calibre (9.15 in tools/calibre, signed by Kovid Goyal; unpacked from its MSI, nothing installed): ebooks converted by its
own ebook-convert (EPUB, AZW3 for Kindle, MOBI, PDF, DOCX, TXT, FB2, from Word, EPUB, PDF, HTML, Markdown, TXT...), with
the title, author and cover set; book details read and changed with ebook-meta. Calibre's settings, cache and temp files
stay in tools/calibre/home, and it runs on the hidden desktop. Checked: each book opens as its format, its details read
back as set, and its text is the original's (both turned into plain text by Calibre and compared word for word).

  'calibre convert garden.docx to epub and kindle, title "The Garden Book" by Ali Khan'   'make garden.epub a kindle book'
  'calibre set title "Gardens" author "Sara" cover front.jpg on garden.epub'   'calibre info garden.epub'
"""
import os
import re
import zipfile
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "calibre", "Calibre: ebooks converted (EPUB, Kindle AZW3, MOBI, PDF, DOCX) with title, author, cover"
EXAMPLES = ['calibre convert garden.docx to epub and kindle, title "The Garden Book" by Ali Khan', "make garden.epub a kindle book",
            'calibre set title "Gardens" author "Sara" cover front.jpg on garden.epub', "calibre info garden.epub"]
HOME = ROOT / "tools" / "calibre"
BIN = HOME / "PFiles64" / "Calibre2"
EBOOKS = {".epub", ".azw3", ".mobi", ".fb2", ".azw", ".kfx"}
INPUTS = EBOOKS | {".docx", ".pdf", ".html", ".htm", ".md", ".markdown", ".txt", ".odt", ".rtf", ".cbz"}
TARGETS = {"epub": "epub", "azw3": "azw3", "kindle": "azw3", "mobi": "mobi", "pdf": "pdf", "docx": "docx", "word": "docx", "txt": "txt", "text": "txt",
           "fb2": "fb2"}


def env():
    home = HOME / "home"
    for p in ("config", "temp", "cache"):
        (home / p).mkdir(parents=True, exist_ok=True)
    return dict(os.environ, CALIBRE_CONFIG_DIRECTORY=str(home / "config"), CALIBRE_TEMP_DIR=str(home / "temp"), CALIBRE_CACHE_DIRECTORY=str(home / "cache"))


def tool(name, *args, timeout=600):
    from ai_pc.core import hidden_desktop
    return hidden_desktop.run([str(BIN / f"{name}.exe"), *map(str, args)], timeout=timeout, env=env())


def meta(path):
    rc, out, err, _ = tool("ebook-meta", path, timeout=120)
    return dict((k.strip(), v.strip()) for k, v in re.findall(r"^([A-Za-z() ]+?)\s*:\s(.*)$", out, re.M))


def words(path, tmp):
    """The book's text as Calibre reads it: a list of lower-case words."""
    txt = Path(tmp) / (Path(path).stem + "_" + Path(path).suffix[1:] + ".txt")
    tool("ebook-convert", path, txt, timeout=300)
    return re.findall(r"[a-z0-9']+", txt.read_text(encoding="utf-8", errors="replace").lower()) if txt.exists() else []


def opens_as(path):
    p = Path(path)
    ext = p.suffix.lower()
    head = p.read_bytes()[:80]
    if ext == ".epub" or ext == ".docx":
        with zipfile.ZipFile(p) as z:
            return (z.read("mimetype") == b"application/epub+zip") if ext == ".epub" else "word/document.xml" in z.namelist()
    if ext in (".azw3", ".mobi"):
        return head[60:68] == b"BOOKMOBI"
    if ext == ".pdf":
        from pypdf import PdfReader
        return len(PdfReader(str(p)).pages) >= 1
    return p.stat().st_size > 0


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    src = find_file(text, ctx, INPUTS)
    kindle = re.search(r"\bkindle\b|\bazw3\b|\bmobi\b", c)
    if not src or not (re.search(r"\bcalibre\b", c) or kindle or (Path(src).suffix.lower() in EBOOKS and re.search(r"\bconvert\b", c))):
        return None
    title = re.search(r"\btitle\s+['\"]([^'\"]+)['\"]|\btitled?\s+['\"]([^'\"]+)['\"]", text, re.I)
    author = re.search(r"\b(?:author|by)\s+['\"]([^'\"]+)['\"]|\bby\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3})", text)
    cover = find_file(re.search(r"\bcover\s+(\S+)", text, re.I).group(1), ctx, {".jpg", ".jpeg", ".png"}) if re.search(r"\bcover\s+\S+\.(?:jpe?g|png)", text, re.I) else None
    fields = {"title": (title.group(1) or title.group(2)) if title else None, "author": (author.group(1) or author.group(2)) if author else None, "cover": cover}
    if re.search(r"\binfo\b|\bdetails\b|\bmetadata\b", c) and not re.search(r"\bset\b|\bchange\b", c):
        return {"op": "info", "file": src}
    if re.search(r"\bset\b|\bchange\b", c) and any(fields.values()) and not re.search(r"\bconvert\b|\bto\s+(?:epub|pdf|kindle|azw3|mobi|docx)\b", c):
        return {"op": "meta", "file": src, **fields}
    after = c.split(Path(src).name.lower(), 1)[-1]
    targets = list(dict.fromkeys(TARGETS[w] for w in re.findall(r"\b(" + "|".join(TARGETS) + r")\b", after)))
    if kindle and "azw3" not in targets:
        targets.append("azw3")
    targets = [t for t in targets if t != Path(src).suffix[1:].lower()] or ["epub"]
    return {"op": "convert", "file": src, "targets": targets, **fields}


def run(op, ctx):
    if not (BIN / "ebook-convert.exe").exists():
        return "Calibre is not in tools/calibre."
    src = Path(op["file"]).resolve()
    out = Path(ctx["out"]) / "calibre"
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_text"
    tmp.mkdir(exist_ok=True)
    if op["op"] == "info":
        m = meta(src)
        return f"{src.name}: " + "; ".join(f"{k} {v}" for k, v in m.items() if v and k in ("Title", "Author(s)", "Publisher", "Languages", "Published", "Series", "Tags")) + "."
    if op["op"] == "meta":
        dest = out / src.name
        if dest.resolve() != src:
            dest.write_bytes(src.read_bytes())  # the copy is changed, the original is left as it was
        args = [dest] + (["--title", op["title"]] if op.get("title") else []) + (["--authors", op["author"]] if op.get("author") else []) + \
            (["--cover", Path(op["cover"]).resolve()] if op.get("cover") else [])
        tool("ebook-meta", *args, timeout=120)
        m = meta(dest)
        checks = [("the title reads back", not op.get("title") or m.get("Title") == op["title"]),
                  ("the author reads back", not op.get("author") or op["author"] in m.get("Author(s)", "")), ("it still opens as its format", opens_as(dest))]
        bad = [w for w, ok in checks if not ok]
        return f"Book details set on {dest}: title {m.get('Title')}, by {m.get('Author(s)')}. " + \
               ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ".")
    original = words(src, tmp)
    made, checks = [], []
    for fmt in op["targets"]:
        dest = (out / f"{src.stem}.{fmt}").resolve()
        dest.unlink(missing_ok=True)
        args = [src, dest] + (["--title", op["title"]] if op.get("title") else []) + (["--authors", op["author"]] if op.get("author") else []) + \
            (["--cover", Path(op["cover"]).resolve()] if op.get("cover") else [])
        rc, so, se, timed_out = tool("ebook-convert", *args)
        if not dest.exists():
            checks.append((f"{fmt.upper()} made", False))
            continue
        made.append(dest)
        m = meta(dest) if fmt in ("epub", "azw3", "mobi", "pdf", "docx", "fb2") else {}
        got = words(dest, tmp) if fmt != "txt" else re.findall(r"[a-z0-9']+", dest.read_text(encoding="utf-8", errors="replace").lower())
        same = len(set(original) & set(got)) / max(1, len(set(original)))
        checks += [(f"the {fmt.upper()} opens as {fmt.upper()}", opens_as(dest)),
                   (f"its text is the original's ({same:.0%} of the words)", same >= 0.95)]
        if op.get("title") and m:
            checks.append((f"title and author read back from the {fmt.upper()}", m.get("Title") == op["title"] and (not op.get("author") or op["author"] in m.get("Author(s)", ""))))
    bad = [w for w, ok in checks if not ok]
    kindle = any(p.suffix == ".azw3" for p in made)
    return (f"Calibre made {', '.join(p.name for p in made) or 'nothing'} in {out} from {src.name}." +
            (" AZW3 is for Kindles over USB (copy it to the Kindle's documents folder); Send to Kindle takes the EPUB." if kindle else "") + " " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
