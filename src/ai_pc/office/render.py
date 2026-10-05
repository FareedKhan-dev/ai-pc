"""Documents rendered the way JianYing exported videos: by the real app, in the background. Then read back for checks.

  r = to_pdf("out/docs/x.docx", update_fields=True, save=True)   Word updates the table of contents and fields, saves
                                                                 the file, exports a PDF; {"ok", "pdf", "pages", ...}
  pages(pdf, scale)  -> page images (PIL)            lines(pdf)   -> every text line with its page and box (points)
  outline(pdf)       -> the headings Word bookmarked  fonts(pdf)   -> the fonts the PDF really uses
  sheet(images, labels) -> one contact-sheet JPEG

Each Office job runs in a child process with a timeout. Office is started as a new instance of its own (COM
"-Embedding"), so a document the user has open is never touched, and only that instance is ever stopped.
"""
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

from ai_pc.core.config import ROOT

EXES = {"word": "WINWORD.EXE", "powerpoint": "POWERPNT.EXE", "excel": "EXCEL.EXE"}
APP_OF = {".docx": "word", ".doc": "word", ".rtf": "word", ".odt": "word", ".pptx": "powerpoint", ".ppt": "powerpoint",
          ".xlsx": "excel", ".xlsm": "excel", ".xls": "excel"}
NO_WINDOW = 0x08000000


def _ours(exe, before, since):
    """Office processes started for automation (COM '-Embedding') after `since`, that were not running before."""
    out = []
    for p in psutil.process_iter(["name", "create_time"]):
        try:
            if (p.info["name"] or "").upper() != exe or p.pid in before or (p.info["create_time"] or 0) < since - 1:
                continue
            cmd = " ".join(p.cmdline()).lower()
            if "-embedding" in cmd or "/automation" in cmd:
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def office(job, timeout=180):
    """Run one job in _com.py; returns its result dict (always with "ok")."""
    exe = EXES[job["app"]]
    before = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").upper() == exe}
    since = time.time()
    p = subprocess.Popen([sys.executable, "-m", "ai_pc.office._com", json.dumps(job)], cwd=str(ROOT),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        for q in _ours(exe, before, since):
            q.kill()
        return {"ok": False, "error": f"{job['app']} did not finish in {timeout} s; its background instance was stopped"}
    deadline = time.time() + 8  # Quit() normally ends the instance; one that stays behind is stopped
    while time.time() < deadline and _ours(exe, before, since):
        time.sleep(0.25)
    for q in _ours(exe, before, since):
        try:
            q.kill()
        except psutil.NoSuchProcess:
            pass
    line = next((ln for ln in out.decode("utf-8", "replace").splitlines()[::-1] if ln.startswith("@@RESULT ")), None)
    if line is None:
        return {"ok": False, "error": "no result from the Office job: " + err.decode("utf-8", "replace")[-600:]}
    return json.loads(line[len("@@RESULT "):])


class Server:
    """A worker process that keeps Word / PowerPoint / Excel open between jobs (a render in ~1-2 s, not ~6-8 s).
    One job at a time; a job that hangs is stopped with the worker and the Office instances it started, and the next
    job starts a fresh worker. close() ends it all."""

    def __init__(self):
        import queue
        import threading
        self.p, self.q, self.since = None, queue.Queue(), 0.0
        self.lock = threading.Lock()

    def _start(self):
        import threading
        self.since = time.time()
        self.p = subprocess.Popen([sys.executable, "-m", "ai_pc.office._com", "serve"], cwd=str(ROOT), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        p, q = self.p, self.q

        def pump():
            for raw in iter(p.stdout.readline, b""):
                q.put(raw.decode("utf-8", "replace"))
        threading.Thread(target=pump, daemon=True).start()

    def _kill(self):
        if self.p is not None:
            try:
                self.p.kill()
            except OSError:
                pass
        for exe in EXES.values():
            for q in _ours(exe, set(), self.since):
                try:
                    q.kill()
                except psutil.NoSuchProcess:
                    pass
        self.p = None

    def run(self, job, timeout=180):
        import queue
        with self.lock:
            if self.p is None or self.p.poll() is not None:
                self._start()
            while not self.q.empty():
                self.q.get_nowait()
            self.p.stdin.write((json.dumps(job) + "\n").encode("utf-8"))
            self.p.stdin.flush()
            deadline = time.time() + timeout
            while True:
                try:
                    line = self.q.get(timeout=max(0.1, deadline - time.time()))
                except queue.Empty:
                    self._kill()
                    return {"ok": False, "error": f"{job['app']} did not finish in {timeout} s; the background worker was restarted"}
                if line.startswith("@@RESULT "):
                    return json.loads(line[len("@@RESULT "):])

    def close(self):
        with self.lock:
            if self.p is not None and self.p.poll() is None:
                try:
                    self.p.stdin.write(b'{"quit": true}\n')
                    self.p.stdin.flush()
                    self.p.wait(timeout=20)
                except Exception:  # noqa: BLE001
                    pass
            self._kill()


def to_pdf(src, pdf=None, update_fields=False, save=False, timeout=180, server=None, **extra):
    """The document as a PDF made by its own app (Word / PowerPoint / Excel). Returns the job's result + "pdf".
    server: a Server keeping Office open between jobs (else a one-off process)."""
    src = Path(src).resolve()
    app = APP_OF.get(src.suffix.lower())
    if app is None:
        return {"ok": False, "error": f"no Office app for {src.suffix}"}
    pdf = Path(pdf).resolve() if pdf else src.with_suffix(".pdf")
    if pdf.exists():
        pdf.unlink()
    if extra.get("png_dir"):  # Office runs in its own working folder: every path it gets is absolute
        extra["png_dir"] = str(Path(extra["png_dir"]).resolve())
    job = {"app": app, "src": str(src), "pdf": str(pdf), "update_fields": update_fields, "save": save, **extra}
    r = server.run(job, timeout) if server is not None else office(job, timeout)
    if r.get("ok") and not pdf.exists():
        r = {**r, "ok": False, "error": "the app finished but wrote no PDF"}
    r["pdf"] = str(pdf)
    return r


# ------------------------------------------------------------------------------------------------ reading the PDF back
def pages(pdf, scale=1.0, first=None, last=None):
    """Page images (PIL, RGB). scale 1.0 = 72 dpi (A4 ~ 595x842 px)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        n = len(doc)
        a, b = (first or 0), min(n, (last + 1) if last is not None else n)
        return [doc[i].render(scale=scale).to_pil().convert("RGB") for i in range(a, b)]
    finally:
        doc.close()


def page_size(pdf):
    """[(width, height)] in points for every page."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [tuple(doc[i].get_size()) for i in range(len(doc))]
    finally:
        doc.close()


def lines(pdf):
    """Every text line: {"page": 0-based, "text", "box": [x0, y0, x1, y1]} in points from the page's top-left."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    out = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            h = page.get_height()
            tp = page.get_textpage()
            for k in range(tp.count_rects()):
                left, bottom, right, top = tp.get_rect(k)
                t = tp.get_text_bounded(left, bottom, right, top).strip()
                if t:
                    out.append({"page": i, "text": t, "box": [round(left, 1), round(h - top, 1), round(right, 1), round(h - bottom, 1)]})
            tp.close()
    finally:
        doc.close()
    return out


def text(pdf):
    """Each page's text in reading order (words joined as the page shows them, unlike `lines`, whose boxes split words
    at hyphens)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        out = []
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            out.append(tp.get_text_range())
            tp.close()
        return out
    finally:
        doc.close()


def outline(pdf):
    """[(level, title, page 0-based)] from the PDF's bookmarks (Word makes one per heading)."""
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    out = []

    def walk(items, level):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
            else:
                try:
                    out.append((level, str(it.title), r.get_destination_page_number(it)))
                except Exception:  # noqa: BLE001
                    continue
    walk(r.outline, 1)
    return out


def fonts(pdf):
    """Base names of the fonts the PDF uses (subset prefixes removed): {"Calibri", "Calibri-Bold", ...}."""
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    names = set()
    for pg in r.pages:
        res = pg.get("/Resources") or {}
        fd = res.get("/Font") if hasattr(res, "get") else None
        if not fd:
            continue
        for ref in fd.values():
            try:
                f = ref.get_object()
                bf = str(f.get("/BaseFont") or "")
            except Exception:  # noqa: BLE001
                continue
            if bf:
                names.add(bf.lstrip("/").split("+", 1)[-1])
    return names


def sheet(images, labels=None, cols=4, cell_w=360, quality=85):
    """A contact sheet of page images, each with its label, as JPEG bytes."""
    from PIL import Image, ImageDraw, ImageFont
    cells = []
    for im in images:
        h = round(im.height * cell_w / im.width)
        cells.append(im.resize((cell_w, h), Image.LANCZOS))
    cell_h = max(c.height for c in cells)
    rows = (len(cells) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell_w + (cols - 1) * 6, rows * cell_h + (rows - 1) * 6), (90, 90, 90))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arialbd.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for i, c in enumerate(cells):
        x, y = (i % cols) * (cell_w + 6), (i // cols) * (cell_h + 6)
        canvas.paste(c, (x, y))
        lab = (labels or [])[i] if labels and i < len(labels) else f"p{i + 1}"
        tw = draw.textlength(lab, font=font)
        draw.rectangle([x, y, x + tw + 10, y + 22], fill=(0, 0, 0))
        draw.text((x + 5, y + 2), lab, fill=(255, 255, 0), font=font)
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
