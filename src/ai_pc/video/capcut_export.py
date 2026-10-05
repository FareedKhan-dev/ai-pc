"""Export a CapCut project through CapCut's own UI: the only step of the video lane that needs the screen.

Steps, each verified, with screenshots kept in runs/export_<time>/:
  1. CapCut on its home screen (if CapCut is open it is closed first; it saves projects automatically);
  2. open the project by clicking its thumbnail (click model, zoomed). Verified on disk, not by pixels: CapCut
     converts a pyCapCut draft (a Timelines/ folder appears) only when that project is opened;
  3. Ctrl+M (CapCut's own export shortcut, from its keymap file), then the dialog's Export button;
  4. wait for the new video file to appear and stop growing, move it into out/video/ and check it with ffprobe.
Clicks outside CapCut's window are refused; the kill switch (Ctrl+Alt+Q) aborts between steps.
"""

import json
import subprocess
import time
from pathlib import Path

import win32gui
import win32process

from ai_pc.core.config import ROOT, RUNS
from ai_pc.desktop import apps, inputs, screen, uia
from ai_pc.desktop.safety import KillSwitch, SafetyBlock
from ai_pc.video.video_lane import DRAFTS


class ExportError(Exception):
    pass


def _capcut_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"CapCut.exe"')}


def _windows():
    """Visible CapCut top-level windows: [(hwnd, rect, area)] largest first."""
    pids, res = _capcut_pids(), []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32process.GetWindowThreadProcessId(h)[1] in pids:
            r = win32gui.GetWindowRect(h)
            res.append((h, r, max(0, r[2] - r[0]) * max(0, r[3] - r[1])))

    win32gui.EnumWindows(cb, None)
    return sorted(res, key=lambda x: -x[2])


class Exporter:
    def __init__(self, grounder, log=print):
        self.g, self.log = grounder, log
        self.kill = KillSwitch()
        self.dir = RUNS / f"export_{time.strftime('%Y%m%d-%H%M%S')}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.t0 = time.perf_counter()
        self.n = 0

    def _say(self, msg):
        line = f"  [{time.perf_counter() - self.t0:6.1f}s] {msg}"
        try:
            self.log(line, flush=True)
        except TypeError:  # a custom log function without flush
            self.log(line)

    def _shot(self, label):
        w = _windows()
        if not w:
            return None
        self.n += 1
        img = screen.grab(w[0][1])
        img.save(self.dir / f"{self.n:02d}_{label}.png")
        return img

    def _main(self):
        w = _windows()
        if not w:
            raise ExportError("CapCut has no visible window")
        return w[0][0], w[0][1]

    def _click(self, target, zoom=True):
        """Ground a described target in CapCut's main window and click it (refused outside the window)."""
        self.kill.check()
        h, rect = self._main()
        inputs.set_foreground(h)
        time.sleep(0.15)
        img = screen.grab(rect)
        res = self.g.ground_zoom(img, target) if zoom and hasattr(self.g, "ground_zoom") else self.g.ground(img, target)
        x, y = rect[0] + res["point"][0], rect[1] + res["point"][1]
        if not (rect[0] <= x < rect[2] and rect[1] <= y < rect[3]):
            raise SafetyBlock(f"click point ({x},{y}) for {target!r} is outside CapCut's window")
        if inputs.foreground() != h and uia.window_info(inputs.foreground())["proc"] != "capcut.exe":
            raise SafetyBlock("CapCut is not in front; refusing to click")
        inputs.click(x, y)
        self._say(f"clicked {target!r} at ({x},{y}) in {res['ms']:.0f} ms")
        return x, y

    def _wait_still(self, max_s=12, still_s=0.8):
        """Until CapCut's window stops changing (a loading screen finished)."""
        t, prev, still = time.time(), None, None
        while time.time() - t < max_s:
            self.kill.check()
            w = _windows()
            if not w:  # between the home window closing and the editor window appearing
                prev, still = None, None
                time.sleep(0.2)
                continue
            rect = w[0][1]
            sig = screen.signature(screen.grab(rect))
            if prev is not None and screen.diff(sig, prev) < 0.0015:
                still = still or time.time()
                if time.time() - still >= still_s:
                    return True
            else:
                still = None
            prev = sig
            time.sleep(0.15)
        return False

    # ------------------------------------------------------------------ steps
    @staticmethod
    def _kind(h, r):
        """'HomeWindow' (project list) or 'MainWindow' (editor): CapCut's window reports it through UI Automation.
        The window must be in front, or the point lookup would read whatever window covers it."""
        inputs.set_foreground(h)
        time.sleep(0.15)
        return (uia.element_at((r[0] + r[2]) // 2, r[1] + 12) or {}).get("aid")

    def home(self):
        """CapCut showing its home screen. Starts CapCut if needed; if a project is open, closes only the editor
        window (CapCut saves the project and goes back to its home screen). Never closes anything else."""
        if not _capcut_pids():
            apps.launch("CapCut")
            t = time.time()
            while time.time() - t < 40:
                w = _windows()
                if w and (w[0][1][2] - w[0][1][0]) > 1000:
                    break
                time.sleep(0.5)
            self._say("started CapCut")
        for _ in range(3):
            self._wait_still(max_s=15)
            w = _windows()
            if not w:
                raise ExportError("CapCut shows no window")
            h, r = w[0][0], w[0][1]
            kind = self._kind(h, r)
            if kind == "HomeWindow":
                self._shot("home")
                self._say("CapCut home screen ready")
                return
            if kind != "MainWindow":
                raise ExportError(f"unexpected CapCut window ({kind!r}); leaving it alone")
            inputs.close_window(h)
            self._say("closed the open project's editor (CapCut saves it) to get back to the home screen")
            t = time.time()
            while time.time() - t < 15 and _windows() and _windows()[0][0] == h:
                time.sleep(0.3)
        raise ExportError("could not reach CapCut's home screen")

    def open_project(self, name):
        """Click the project's thumbnail; verified by CapCut converting that draft on disk."""
        marker = DRAFTS / name / "Timelines"
        if not (DRAFTS / name).is_dir():
            raise ExportError(f"no draft named {name}")
        for attempt in range(2):
            self._click(f"the project named {name} in the Projects list")
            t = time.time()
            while time.time() - t < 15:
                if marker.exists():
                    self._wait_still(max_s=20)
                    self._shot("editor")
                    self._say(f"project {name} is open (CapCut converted its draft)")
                    return
                time.sleep(0.25)
            self._shot(f"open_failed_{attempt}")
            self._say("the project did not open; retrying")
        raise ExportError(f"could not open project {name}")

    def open_export_dialog(self):
        h, _ = self._main()
        inputs.set_foreground(h)
        time.sleep(0.15)
        self.kill.check()
        inputs.hotkey("ctrl", "m")
        time.sleep(1.5)
        self._wait_still(max_s=6)
        self._shot("export_dialog")
        self._say("pressed Ctrl+M (CapCut's export shortcut)")


def explore(name):
    """Stage 1 only: home -> open the project -> Ctrl+M, then stop (nothing is exported)."""
    from ai_pc.desktop.grounder import make_grounder

    g = make_grounder()
    g.ensure()
    ex = Exporter(g)
    ex.kill.start()
    ex.home()
    ex.open_project(name)
    ex.open_export_dialog()
    print("screenshots:", ex.dir)
    return ex


def _dialog(name, timeout=8.0):
    """CapCut's export dialog for this project: a window titled 'Export-<name>' (checked by title, not by pixels)."""
    t = time.time()
    while time.time() - t < timeout:
        for h, r, _ in _windows():
            if win32gui.GetWindowText(h) == f"Export-{name}":
                return h, r
        time.sleep(0.2)
    return None, None


def _find_export(name, since, roots):
    """New '<name>*.mp4' files directly inside the candidate export folders (no deep walk: CapCut's data folder holds
    huge caches)."""
    hits = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.glob(f"{name}*.mp4"):
            try:
                if p.stat().st_mtime >= since - 1:
                    hits.append(p)
            except OSError:
                pass
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def probe(path):
    """Duration and picture size of a video, read with ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    d = json.loads(out or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "seconds": round(float(d.get("format", {}).get("duration", 0)), 2),
        "width": v.get("width"),
        "height": v.get("height"),
        "audio": any(s.get("codec_type") == "audio" for s in d.get("streams", [])),
    }


def _open_dialog(self, name):
    """Top-right Export button (Ctrl+M did not open the dialog in CapCut 9.5), verified by the dialog's title."""
    h, r = _dialog(name, timeout=0.5)
    if h:
        return h, r
    self._click("the Export button at the top right of the window")
    h, r = _dialog(name)
    if not h:
        self._shot("no_export_dialog")
        raise ExportError("the export dialog did not open")
    self._say(f"export dialog for {name} is open")
    return h, r


def _start(self, name):
    """Click the dialog's own Export button (bottom right), refusing any point outside that part of the dialog."""
    h, r = _dialog(name)
    if not h:
        raise ExportError("the export dialog is not open")
    self.kill.check()
    inputs.set_foreground(h)
    time.sleep(0.2)
    img = screen.grab(r)
    res = self.g.ground(img, "the Export button at the bottom right of the dialog")
    x, y = r[0] + res["point"][0], r[1] + res["point"][1]
    w, hgt = r[2] - r[0], r[3] - r[1]
    if not (r[0] + 0.55 * w <= x < r[2] and r[1] + 0.85 * hgt <= y < r[3]):
        raise SafetyBlock(f"the Export button was located at ({x},{y}), outside the dialog's bottom-right area; not clicking")
    since = time.time()
    inputs.click(x, y)
    self._say(f"clicked the dialog's Export button at ({x},{y})")
    return since


def _wait_export(self, name, since, timeout=600, appear_s=None):
    """Until CapCut has written the video and it stopped growing; returns its path. With `appear_s`, gives up
    (returns None) if no file has appeared by then."""
    import os

    home = Path(os.environ["USERPROFILE"])
    roots = [
        Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "Videos",  # CapCut 9.5's default "Export to" folder
        home / "Videos",
        home / "Videos" / "CapCut",
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    t, last, stable, seen = time.time(), -1, 0, False
    while time.time() - t < timeout:
        self.kill.check()
        p = _find_export(name, since, roots)
        if p:
            seen = True
            size = p.stat().st_size
            stable = stable + 1 if size == last and size > 0 else 0
            last = size
            if stable >= 3:
                self._say(f"export finished: {p} ({size / 1e6:.1f} MB)")
                return p
        elif appear_s and time.time() - t > appear_s:
            return None
        time.sleep(1.0)
    raise ExportError("no exported file appeared in time" if not seen else "the exported file never stopped growing")


def _quick_export(self):
    """Ctrl+M: in CapCut 9.5 this exports straight away with the last export settings (no dialog is shown)."""
    h, _ = self._main()
    inputs.set_foreground(h)
    time.sleep(0.2)
    self.kill.check()
    since = time.time()
    inputs.hotkey("ctrl", "m")
    self._say("pressed Ctrl+M (CapCut's export shortcut)")
    return since


def _finish(self, name, src):
    """Close the share dialog, COPY the video into the project (out/video/), verify the copy, then remove CapCut's
    original once CapCut has let go of it (it may keep the file open for its preview; then it is left in place)."""
    import shutil

    self._shot("export_done")
    h, _ = _dialog(name, timeout=2)
    if h:
        inputs.close_window(h)
    dest_dir = ROOT / "out" / "video"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(str(src), dest)
    if dest.stat().st_size != src.stat().st_size:
        raise ExportError("the copy in out/video does not match CapCut's export")
    for _ in range(20):
        try:
            src.unlink()
            break
        except PermissionError:
            time.sleep(0.5)
    info = probe(dest)
    self._say(f"video in the project: {dest} {info}" + ("" if not src.exists() else f" (CapCut still holds {src})"))
    return dest, info


Exporter.open_dialog = _open_dialog
Exporter.start = _start
Exporter.wait_export = _wait_export
Exporter.quick_export = _quick_export
Exporter.finish = _finish


def export(name, grounder=None, restart=True):
    """The whole export: home -> open project -> Ctrl+M -> file -> out/video/. Falls back to the Export dialog when
    Ctrl+M produced nothing. Returns (path, info, seconds, steps)."""
    from ai_pc.desktop.grounder import make_grounder

    g = grounder or make_grounder()
    g.ensure()
    ex = Exporter(g)
    ex.kill.start()
    steps = {}
    if restart:
        t = time.perf_counter()
        ex.home()
        steps["start CapCut"] = round(time.perf_counter() - t, 1)
        t = time.perf_counter()
        ex.open_project(name)
        steps["open project"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    since = ex.quick_export()
    src = ex.wait_export(name, since, appear_s=20)
    if src is None:  # Ctrl+M did not export: use the Export dialog
        ex._say("Ctrl+M produced no file; using the Export dialog")
        ex.open_dialog(name)
        since = ex.start(name)
        src = ex.wait_export(name, since)
    steps["export (render)"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    dest, info = ex.finish(name, src)
    steps["copy + verify"] = round(time.perf_counter() - t, 1)
    return dest, info, round(time.perf_counter() - ex.t0, 1), steps
