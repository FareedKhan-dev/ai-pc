"""Exporting a JianYing 5.9 draft to an mp4, unattended and without touching the user's mouse or keyboard.

  ensure_running()  starts the frozen 5.9 (never its updating launcher) without taking focus, behind other windows
  export(name)      opens the project, checks that JianYing could download every catalogue item it uses (else stops and
                    says which), presses Export, waits for the render, closes the editor, moves the file to out/video/
  PopupGuard        dismisses known pop-ups with their safe answer; a login window is always closed, never used

Everything runs in ONE thread: UI Automation calls from two threads of one process deadlock (COM apartments), so the
pop-up sweep runs inside the driver's wait loops. Kill switch: Ctrl+Alt+Q.
"""
import atexit
import json
import subprocess
import time
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process

from . import jyres
from .config import ROOT
from .safety import KillSwitch

JIANYING = ROOT / "tools" / "jianying" / "app" / "JYPacket" / "5.9.0.11632" / "JianyingPro.exe"  # frozen 5.9, updater disabled
OUT = ROOT / "out" / "video"
SESSIONS = OUT / "sessions"

# Pop-ups JianYing may show at any moment, and the SAFE answer to each. The guard presses only these answers.
KNOWN_POPUPS = [
    ("开启推送通知", ["暂不"]),                          # "turn on push notifications?" -> "not now"
    ("环境检测", ["确定"]),                              # hardware check result (information only) -> "OK"
    ("发现新版本", ["暂不更新", "以后再说", "取消"]),      # update offers -> "later" (the updater is disabled anyway)
    ("版本更新", ["暂不更新", "以后再说", "取消"]),
]
NEVER_PRESS = {"开启", "同意", "允许", "立即更新", "升级", "开通", "购买", "登录", "确认支付"}  # enable/agree/update/buy/log in


class PopupGuard:
    """Dismisses known JianYing pop-ups with their safe answer. NOT a thread: the driver calls maybe_sweep() from its
    own wait loops."""

    def __init__(self, interval=1.5, log=print):
        self.interval, self.dismissed, self._last, self.log = interval, [], 0.0, log

    @staticmethod
    def _labels(ctrl, depth=0, out=None, max_depth=6):
        out = [] if out is None else out
        for ch in ctrl.GetChildren():
            label = (ch.Name or "").strip() or (ch.GetPropertyValue(30159) or "").strip()
            if label:
                out.append((label, ch))
            if depth < max_depth:
                PopupGuard._labels(ch, depth + 1, out, max_depth)
        return out

    def maybe_sweep(self):
        if time.time() - self._last < self.interval:
            return
        self._last = time.time()
        try:
            self.sweep()
        except Exception:  # noqa: BLE001  (a window closing mid-scan is normal)
            pass

    def sweep(self):
        import uiautomation as uia
        from .appknow import exe_path
        from .jianying_driver import bg_click
        for w in uia.GetRootControl().GetChildren():
            if not str(exe_path(w.ProcessId) or "").lower().endswith("jianyingpro.exe"):
                continue
            # the editor's own tree is large: there, look only inside its dialog windows (pop-ups live there)
            roots = [w] if "MainWindow" not in (w.ClassName or "") else \
                [c for c in w.GetChildren() if c.ControlTypeName == "WindowControl" and c.Name != "导出"]
            labels = [x for r in roots for x in self._labels(r)]
            for trigger, answers in KNOWN_POPUPS:
                if not any(trigger in lab for lab, _ in labels):
                    continue
                for lab, ctrl in labels:
                    if lab in answers and lab not in NEVER_PRESS:
                        bg_click(ctrl)  # never the real mouse: the user may be working
                        self.dismissed.append(f"{trigger} -> {lab}")
                        self.log(f"  pop-up guard: '{trigger}' dismissed with '{lab}'")
                        time.sleep(0.5)
                        return


GUARD = PopupGuard()


def _jianying_windows():
    """Visible top-level windows of JianYing (main window, export dialog, login window, ...)."""
    from .appknow import exe_path
    found = []

    def cb(h, _):
        try:
            if win32gui.IsWindowVisible(h):
                pid = win32process.GetWindowThreadProcessId(h)[1]
                if str(exe_path(pid) or "").lower().endswith("jianyingpro.exe"):
                    found.append(h)
        except Exception:  # noqa: BLE001
            pass
    win32gui.EnumWindows(cb, None)
    return found


class OffScreen:
    """Keeps JianYing's windows parked to the right of all monitors while the agent uses it: the user never sees it
    and cannot click into it by accident. UI Automation and the posted clicks do not care where a window is. When the
    process ends, the main window goes back where it was (JianYing remembers its position for the next manual start)."""

    def __init__(self):
        self.saved = {}  # hwnd -> window placement before parking
        self.enabled = True
        self._registered = False

    @staticmethod
    def _park_x():
        return win32api.GetSystemMetrics(76) + win32api.GetSystemMetrics(78) + 400  # virtual screen right edge + margin

    def hide(self):
        if not self.enabled:
            return unminimize()
        px, n = self._park_x(), 0
        for h in _jianying_windows():
            try:
                pl = win32gui.GetWindowPlacement(h)
                if win32gui.IsIconic(h):  # minimized (e.g. the user pressed Win+D): it ignores clicks until restored
                    if h not in self.saved:
                        self.saved[h] = pl
                    nl, nt, nr, nb = pl[4]
                    win32gui.SetWindowPlacement(h, (pl[0], win32con.SW_SHOWNOACTIVATE, pl[2], pl[3], (px, 0, px + nr - nl, nb - nt)))
                    pl = win32gui.GetWindowPlacement(h)  # Windows restores it onto a monitor: park it right away (below)
                l, t, r, b = win32gui.GetWindowRect(h)
                if l >= px - 10:
                    continue
                if h not in self.saved:
                    self.saved[h] = pl
                w, ht = r - l, b - t
                if pl[1] == win32con.SW_SHOWMAXIMIZED:  # a maximized window must become a normal one to move
                    win32gui.SetWindowPlacement(h, (pl[0], win32con.SW_SHOWNOACTIVATE, pl[2], pl[3], (px, 0, px + w, ht)))
                else:
                    win32gui.SetWindowPos(h, 0, px, t, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
                n += 1
            except Exception:  # noqa: BLE001  (a window closing meanwhile)
                continue
        if n and not self._registered:
            atexit.register(self.restore)
            self._registered = True
        return n

    def restore(self):
        """Put parked windows back (the main window keeps its size; it is not re-maximized, which would take focus)."""
        for h, pl in list(self.saved.items()):
            try:
                if win32gui.IsWindow(h):
                    flags, show, mn, mx, normal = pl
                    if show == win32con.SW_SHOWMAXIMIZED:
                        l, t, r, b = win32api.GetMonitorInfo(win32api.MonitorFromRect(normal, 2))["Work"]
                        normal = (l, t, r, b)
                    win32gui.SetWindowPlacement(h, (flags, win32con.SW_SHOWNOACTIVATE, mn, mx, normal))
                    win32gui.SetWindowPos(h, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
            except Exception:  # noqa: BLE001
                pass
        self.saved.clear()


def unminimize():
    """Restore minimized JianYing windows without activating them, then put them behind the user's windows: a
    minimized Qt window does not react to the posted clicks this agent uses (seen: 4 clicks, editor never opened)."""
    n = 0
    for h in _jianying_windows():
        try:
            if win32gui.IsIconic(h):
                pl = win32gui.GetWindowPlacement(h)
                win32gui.SetWindowPlacement(h, (pl[0], win32con.SW_SHOWNOACTIVATE, pl[2], pl[3], pl[4]))
                win32gui.SetWindowPos(h, win32con.HWND_BOTTOM, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


OFF = OffScreen()


def _poll():
    """Run from the driver's wait loops: keep new JianYing windows off-screen, dismiss known pop-ups."""
    OFF.hide()
    GUARD.maybe_sweep()


def prewarm():
    """Start JianYing in the background (no UI Automation, returns at once) so it is ready when the plan is."""
    import uiautomation as uia
    if uia.WindowControl(searchDepth=1, Name="剪映专业版").Exists(0) or not JIANYING.exists():
        return False
    if not (JIANYING.parent / "update.exe.disabled").exists() or (JIANYING.parent / "update.exe").exists():
        return False
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4  # SW_SHOWNOACTIVATE
    subprocess.Popen([str(JIANYING)], cwd=str(JIANYING.parent), creationflags=0x00000008 | 0x00000200, startupinfo=si)

    def park():  # win32 only (no UI Automation in this thread): park every new JianYing window as it appears
        end = time.time() + 30
        while time.time() < end:
            OFF.hide()
            time.sleep(0.1)
    import threading
    threading.Thread(target=park, daemon=True).start()
    return True


def _each_main_window(fn):
    def cb(h, _):
        if win32gui.GetWindowText(h) == "剪映专业版":
            fn(h)
    win32gui.EnumWindows(cb, None)


def send_behind():
    """JianYing works fine behind other windows: keep it there so the user's windows stay in front."""
    from .jianying_driver import keep_behind
    _each_main_window(keep_behind)


def not_topmost():
    _each_main_window(lambda h: win32gui.SetWindowPos(h, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE))


def home_ready(timeout=90):
    """Until JianYing shows its home screen (the exporter starts from there)."""
    import uiautomation as uia
    t = time.time()
    while time.time() - t < timeout:
        w = uia.WindowControl(searchDepth=1, Name="剪映专业版")
        if w.Exists(0) and "HomePage" in w.ClassName:
            return True
        _poll()
        time.sleep(0.25)
    return False


def ensure_running(log=print):
    """Start JianYing 5.9 if it is not open (straight from its version folder, never the updating launcher), without
    taking focus, and wait for its home screen. Returns seconds spent."""
    import uiautomation as uia
    t = time.perf_counter()
    if uia.WindowControl(searchDepth=1, Name="剪映专业版").Exists(0):
        return 0.0
    if not (JIANYING.parent / "update.exe.disabled").exists() or (JIANYING.parent / "update.exe").exists():
        raise RuntimeError("JianYing's updater is not disabled; refusing to start it (it could replace 5.9)")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 4  # SW_SHOWNOACTIVATE: appear without taking the keyboard from the user
    subprocess.Popen([str(JIANYING)], cwd=str(JIANYING.parent), creationflags=0x00000008 | 0x00000200, startupinfo=si)
    end = time.time() + 20
    while time.time() < end and not OFF.hide():  # park it the moment it appears (no flash on the user's screen)
        time.sleep(0.05)
    if not home_ready():
        raise RuntimeError("JianYing did not reach its home screen in time")
    send_behind()
    for _ in range(6):  # launch-time pop-ups appear in the first seconds
        _poll()
        time.sleep(0.5)
    log(f"started JianYing 5.9 ({time.perf_counter() - t:.1f} s to its home screen)")
    return time.perf_counter() - t


def restart(log=print, wait=15):
    """Close JianYing (politely, then by force after `wait` s) and start it again off-screen. It is our tool app,
    parked off-screen: nothing of the user's is open in it, and every draft is already saved on disk."""
    for h in _jianying_windows():
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:  # noqa: BLE001
            pass
    end = time.time() + wait
    while time.time() < end and _jianying_windows():
        _poll()
        time.sleep(0.5)
    if _jianying_windows():
        subprocess.run(["taskkill", "/F", "/T", "/IM", JIANYING.name], capture_output=True, creationflags=0x08000000)
        time.sleep(2)
    ensure_running(log)


def _items():
    from . import ccbridge
    own = {it["key"]: it for it in json.loads((ROOT / "kb" / "jianying" / "items.json").read_text(encoding="utf-8"))}
    return {**own, **ccbridge.items()}  # CapCut-only items ("<category>:cc:<name>") are checked the same way


def export(name, log=print, start=True, emap=None, offscreen=True):
    """Export draft `name` to out/video/<name>.mp4. Returns {"ok", "path", "info", "seconds", "error", "missing",
    "login", "used"}: missing = items JianYing could not download, login = JianYing asked for an account."""
    from .capcut_export import probe
    from .jianying_driver import DriverError, JianyingDriver
    res = {"ok": False, "path": None, "info": None, "seconds": 0.0, "error": None, "missing": [], "login": False, "used": []}
    t0 = time.perf_counter()
    OFF.enabled = offscreen
    OFF.hide()
    if start:
        ensure_running(log)
    if emap is None:
        sess = SESSIONS / f"{name}.json"
        emap = json.loads(sess.read_text(encoding="utf-8")).get("map") if sess.exists() else None
    items = _items()
    keys = {k for k in jyres.used_items(emap) if k in items} if emap else set()
    res["used"] = sorted(keys)
    kill = KillSwitch()
    kill.start()

    def preflight():
        if not keys:
            return None
        t = time.perf_counter()
        ok, missing = jyres.wait_downloads(keys, items, kill=kill, on_poll=_poll)
        jyres.record(ok=ok, missing=missing)
        res["missing"] = sorted(missing)
        log(f"  resources: {len(ok)}/{len(keys)} downloaded in {time.perf_counter() - t:.1f} s" + (f"; MISSING {sorted(missing)}" if missing else ""))
        return f"JianYing could not download: {', '.join(sorted(missing))}" if missing else None
    dest = OUT / f"{name}.mp4"
    try:
        JianyingDriver(kill=kill, log=lambda m, **k: log(m), on_poll=_poll).export(name, dest, preflight=preflight)
    except Exception as e:  # noqa: BLE001  (DriverError, or a COMError from a control that vanished mid-click)
        if not isinstance(e, DriverError):
            e = DriverError(f"UI Automation error ({type(e).__name__}: {str(e)[:80]}); JianYing is not responding")
        gone = not _jianying_windows()
        if gone and OFF.enabled and not getattr(export, "_retried", False):
            # JianYing closed while parked off-screen: never park again in this process, try once more on-screen
            log("JianYing closed while parked off-screen; trying again with it behind your windows instead")
            OFF.enabled = False
            export._retried = True
            try:
                return export(name, log=log, start=True, emap=emap, offscreen=False)
            finally:
                export._retried = False
        stuck = any(w in str(e) for w in ("waiting for the editor", "in the home list", "waiting for the home screen", "not responding"))
        if stuck and not gone and not res["missing"] and not getattr(export, "_restarted", False):
            # JianYing stopped reacting to clicks (a hidden dialog, a hung list): a fresh start always gets past it
            log(f"JianYing is not responding ({e}); restarting it and trying once more")
            kill.event.set()
            restart(log)
            export._restarted = True
            try:
                return export(name, log=log, start=True, emap=emap, offscreen=offscreen)
            finally:
                export._restarted = False
        res.update(error=str(e), login="login" in str(e), seconds=round(time.perf_counter() - t0, 1))
        if res["login"] and len(keys) == 1:  # a one-item project: that item needs an account
            jyres.record(login=keys)
        return res
    finally:
        kill.event.set()
        not_topmost()
    if keys:
        jyres.record(exported=keys)  # every item of a finished export is proven to work here
    res.update(ok=True, path=str(dest), info=probe(dest), seconds=round(time.perf_counter() - t0, 1))
    return res
