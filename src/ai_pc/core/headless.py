"""Headless Chrome (or Edge) as a renderer: HTML and SVG pages to PDF (exact paper sizes, vector) and PNG, and the page
read back after its scripts ran (for measurements made inside the page).

It always starts its own hidden browser with a profile inside the project (out/chrome_profile), so the person's own
Chrome, its windows, tabs and logins, are never touched, and nothing appears on screen. Each call is one short-lived
process with a timeout; calls are serialised (one profile, one browser at a time).

  pdf(html_or_svg_path, out_pdf)                      @page size in the page decides the paper
  png(html_or_svg_path, out_png, (width, height))     CSS pixels at device scale 1 (scale=2 for retina)
  dom(html_path) -> str                               the page's HTML after its scripts ran
"""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from ai_pc.core.config import ROOT

PROFILE = ROOT / "out" / "chrome_profile"
_LOCK = threading.Lock()
CANDIDATES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RenderError(Exception):
    pass


def browser():
    for c in CANDIDATES:
        if os.path.isfile(c):
            return c
    raise RenderError("no Chrome or Edge found")


_LOCKS = {}


def _run(extra, url, timeout=90, lane=None):
    """One hidden browser run. lane: a name for a profile of its own (out/chrome_profile/<lane>), so several runs can go
    at once (each profile is used by one browser at a time)."""
    prof = PROFILE / lane if lane else PROFILE
    prof.mkdir(parents=True, exist_ok=True)
    lock = _LOCKS.setdefault(str(prof), threading.Lock()) if lane else _LOCK
    args = [browser(), "--headless=new", f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-sync", "--disable-background-networking", "--disable-component-update", "--disable-default-apps", "--mute-audio",
            "--hide-scrollbars", "--disable-gpu", "--allow-file-access-from-files", "--run-all-compositor-stages-before-draw", *extra, url]
    with lock:
        t0 = time.perf_counter()
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            raise RenderError(f"the browser took longer than {timeout} s")
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), time.perf_counter() - t0


def _url(path):
    s = str(path)
    if s.startswith(("http://", "https://", "file:", "data:")):  # a web address goes as it is
        return s
    return Path(path).resolve().as_uri()


def pdf(src, out_pdf, wait_ms=1500, timeout=90, lane=None):
    """A PDF of the page; its CSS @page decides the paper size (no browser header or footer is added)."""
    out_pdf = Path(out_pdf).resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.unlink(missing_ok=True)
    _, err, secs = _run([f"--print-to-pdf={out_pdf}", "--no-pdf-header-footer", "--generate-pdf-document-outline=false",
                         f"--virtual-time-budget={int(wait_ms)}"], _url(src), timeout, lane)
    if not out_pdf.exists() or out_pdf.stat().st_size < 200:
        raise RenderError(f"no PDF was written ({err.strip()[-200:]})")
    return {"path": str(out_pdf), "seconds": round(secs, 2)}


def png(src, out_png, size=(1280, 720), scale=1, wait_ms=1500, timeout=90, lane=None):
    """A screenshot of the page at a window of size (CSS px)."""
    out_png = Path(out_png).resolve()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_png.unlink(missing_ok=True)
    _, err, secs = _run([f"--screenshot={out_png}", f"--window-size={int(size[0])},{int(size[1])}", f"--force-device-scale-factor={scale}",
                         f"--virtual-time-budget={int(wait_ms)}", "--default-background-color=FFFFFFFF"], _url(src), timeout, lane)
    if not out_png.exists():
        raise RenderError(f"no picture was written ({err.strip()[-200:]})")
    return {"path": str(out_png), "seconds": round(secs, 2)}


def dom(src, wait_ms=1500, timeout=90, lane=None):
    """The page's HTML after its scripts ran (a page can write its own measurements into itself)."""
    out, err, secs = _run(["--dump-dom", f"--virtual-time-budget={int(wait_ms)}"], _url(src), timeout, lane)
    if not out.strip():
        raise RenderError(f"the page came back empty ({err.strip()[-200:]})")
    return out


def wipe_profile():
    shutil.rmtree(PROFILE, ignore_errors=True)
