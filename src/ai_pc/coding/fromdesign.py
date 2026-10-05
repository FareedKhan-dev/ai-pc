"""A design from Figma or Canva becomes a coding project (a web page in a git history, VS Code ready), checked against the
design itself: the page loads cleanly, every element is measured against where the design puts it, every text is there
and fits, the fonts load, and the page's screenshot is compared with the design's own picture.

  r = from_figma(figma_connector, "https://www.figma.com/design/KEY/Shop?node-id=1-2", frame=None, projects_dir=...)
  r = from_canva(canva_connector, "Eid sale", pages=None, email=False, projects_dir=...)
  r: {"project", "page", "check", "web", "sha", "fonts": (saved, missing), "notes", "source", "name"}

Figma: its description of the frame (read once and kept while the file is unchanged), the pictures the frame uses, and
Figma's own PNG of the frame (one API call; skipped with a note when Figma's monthly allowance is used up).
Canva: the design exported as PowerPoint (read by pptxtree.py) and as PNG pages (the reference, and the source for
anything with no web equivalent). Email designs can come as Canva's own HTML instead.
"""
import re
import shutil
import zipfile
from pathlib import Path

from ai_pc.coding import design2code as D
from ai_pc.coding import designcheck as DC
from ai_pc.coding import pptxtree as PT
from ai_pc.coding import verify as V
from ai_pc.coding.project import Project, ProjectError
from ai_pc.core.config import STATE
from ai_pc.hub.http import HubError

WORK = STATE / "design"
SAFE_EXT = {".html", ".htm", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".woff2", ".ttf", ".otf", ".json", ".txt", ".js"}


def _folder(projects_dir, name):
    base = re.sub(r"[^a-z0-9]+", "_", (name or "design").lower()).strip("_")[:40] or "design"
    folder, k = Path(projects_dir) / base, 2
    while folder.exists():
        folder, k = Path(projects_dir) / f"{base}_{k}", k + 1
    return folder


def _finish(folder, page, ref, notes, message, source):
    """The page written into a new web project with its fonts, checked every way, saved as the first version."""
    page.notes = list(dict.fromkeys(list(notes) + list(page.notes)))
    proj = Project.create(folder, "web")
    font_css, saved, missing = D.google_fonts(page.fonts, folder)
    page.write(folder, font_css)
    if ref and Path(ref).exists():
        shutil.copyfile(ref, folder / "design" / "reference.png")
    web = V.check(proj, design=False)
    try:
        dc = DC.check(folder)
    except DC.CheckError as e:
        dc = {"ok": False, "lines": [f"the page could not be measured ({e})"], "placed": [0, 0], "picture": None}
    sha = proj.commit(message)
    return {"project": proj, "page": page, "check": dc, "web": web, "sha": sha, "fonts": (saved, missing), "notes": page.notes, "source": source,
            "name": page.title}


def from_figma(conn, link, frame=None, projects_dir=None, reference=True):
    from ai_pc.hub.services.figma import key_of
    key, node = key_of(link)
    data = conn.file(key)
    if node:
        n = D.find(data["document"], node)
        if n is None:
            raise ProjectError(f"the link points to a layer ({node}) that is not in the file any more")
        if n.get("type") in ("CANVAS", "DOCUMENT"):
            node = None
    if not node:
        node = conn.find_frame(key, frame, data)["id"]
    root = D.find(data["document"], node)
    name = root.get("name") or "frame"
    refs = D.image_refs(root)
    notes = []
    images = conn.download_images(key, refs) if refs else {}
    if refs - set(images):
        notes.append(f"{len(refs - set(images))} picture(s) could not be fetched from Figma")
    if data.get("_stale"):
        notes.append("Figma could not be asked whether the file changed, so the copy saved on this PC was used")
    page = D.build(data, node, images, source="figma", origin_info={"file": key, "node": node, "link": link, "file_name": data.get("name")})
    folder = _folder(projects_dir, f"{data.get('name') or 'figma'} {name}")
    ref = None
    if reference:
        ver = re.sub(r"[^\w-]+", "", str(data.get("_version") or ""))[:24]
        cached = WORK / "figma" / key / f"{node.replace(':', '-')}_v{ver}.png"
        if cached.exists():
            ref = cached
        else:
            try:
                got = conn.export(key, [node], "png", scale=1, folder=cached.parent, names={node: cached.stem})
                ref = got[0]["path"] if got and got[0].get("path") else None
            except HubError as e:
                notes.append(f"Figma's own picture of the frame was not fetched ({e}); the page is measured against the design's boxes only")
    return _finish(folder, page, ref, notes, f"First version, from the Figma frame '{name}'", "figma")


def _stack(pngs, width, out):
    """Several page pictures one under another, at the page width (the reference for a page made of sections)."""
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in pngs]
    ims = [im.resize((int(width), max(1, int(round(im.height * width / im.width))))) for im in ims]
    sheet = Image.new("RGB", (int(width), sum(im.height for im in ims)), "white")
    y = 0
    for im in ims:
        sheet.paste(im, (0, y))
        y += im.height
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def _unzip(zpath, folder):
    """Canva's HTML bundle into the project: only web files, never outside the folder."""
    folder = Path(folder).resolve()
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            name = m.filename.replace("\\", "/")
            if m.is_dir() or name.startswith("/") or ".." in name.split("/") or Path(name).suffix.lower() not in SAFE_EXT:
                continue
            dest = (folder / name).resolve()
            if folder not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(m))
    pages = sorted(folder.rglob("*.htm*"))
    if pages and not (folder / "index.html").exists():
        shutil.copyfile(pages[0], folder / "index.html")


def from_canva(conn, name, pages=None, email=False, projects_dir=None):
    if not name:
        raise ProjectError("which Canva design? Say its name, e.g. 'make a website from my Canva design \"Eid sale\"'")
    d = conn.find(name)
    work = WORK / "canva" / re.sub(r"[^\w-]+", "", d["id"])
    if email:
        z = conn.export(d, "html_bundle", folder=work)["files"][0]
        folder = _folder(projects_dir, d["name"])
        proj = Project.create(folder, "web")
        _unzip(z, folder)
        web = V.check(proj, design=False)
        sha = proj.commit(f"First version, Canva's HTML of the email design '{d['name']}'")
        return {"project": proj, "page": None, "check": None, "web": web, "sha": sha, "fonts": ([], []), "notes": [], "source": "canva",
                "name": d["name"]}
    pptx = conn.export(d, "pptx", folder=work, name="design")["files"][0]
    pngs = conn.export(d, "png", folder=work, pages=pages, name="page")["files"]
    nums = list(pages) if pages else list(range(1, len(pngs) + 1))
    pictures = dict(zip(nums, pngs))
    notes = []
    want = nums
    if len(want) > 8:
        want = want[:1]
        notes.append(f"the design has {len(nums)} pages; only page 1 was made (ask for others by number)")
    tree, images, pnotes = PT.load(pptx, want, pictures, work=work / "img", title=d["name"])
    page = D.build(tree, None, images, source="canva", title=d["name"], origin_info={"design": d["id"], "link": d.get("link"), "pages": want})
    ref = pictures.get(want[0]) if len(want) == 1 else _stack([pictures[p] for p in want if p in pictures], page.w, work / "stacked.png")
    folder = _folder(projects_dir, d["name"])
    return _finish(folder, page, ref, notes + pnotes, f"First version, from the Canva design '{d['name']}'", "canva")


def summary(r):
    """One reply for the person: what was made, how it checks out, where it is."""
    proj, page = r["project"], r["page"]
    files = [f for f in proj.files() if not f.startswith(".")]
    if page is None:
        web = "; ".join(c["what"] for c in r["web"] if c["level"] != "info")
        return f"Made {proj.folder.name} (web) from Canva's own HTML for the email design '{r['name']}': {', '.join(files[:8])}. {web}. " \
               f"Version {r['sha']}. Folder: {proj.folder}."
    kinds = [e.get("type") for cls, e in page.elements.items() if cls != page.root]
    pics = sum(1 for a in page.assets if not a.startswith("assets/fonts/"))
    icons = sum(1 for k in kinds if k in D.VECTORS)
    saved, missing = r["fonts"]
    where = {"figma": "the Figma frame", "canva": "the Canva design"}[r["source"]]
    head = f"Made {proj.folder.name} (web) from {where} '{r['name']}' ({D.fmt(page.w)} x {D.fmt(page.h)}): {len(kinds)} elements, " \
           f"{kinds.count('TEXT')} texts, {pics} pictures, {icons} icons" + (f"; fonts saved in the project: {', '.join(saved)}" if saved else "") + \
           (f"; not free to include (a stand-in is used): {', '.join(missing)}" if missing else "") + "."
    bad = [c for c in r["web"] if not c["ok"] and c["level"] == "fail"]
    web = "the page loads with no errors" if not bad else "; ".join(c["what"] for c in bad)
    dc = r["check"] or {}
    checks = "; ".join([web] + list(dc.get("lines") or []))
    tail = f" Version {r['sha']}. Folder: {proj.folder}. Say 'open it in VS Code', or ask for changes (e.g. 'make it work on phones')."
    notes = (" Not kept exactly: " + "; ".join(r["notes"][:3]) + ".") if r["notes"] else ""
    return f"{head} Checks: {checks}.{notes}{tail}"
