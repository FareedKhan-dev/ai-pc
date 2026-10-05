"""Our own JianYing 5.9 export driver. It uses the same accessibility names as pyJianYingDraft's JianyingController
(HomePageDraftTitle:<name>, MainWindowTitleBarExportBtn, ExportPath, ExportOkBtn, ExportSucceedCloseBtn, ...), but it
WAITS FOR EACH CONTROL TO APPEAR (with deadlines) instead of sleeping a fixed 10 s, re-presses Export while the editor
is still loading, never loops without a deadline, and checks the kill switch between every step.

It never touches the user's mouse: every click is a UI Automation Invoke when the control offers one, otherwise mouse
messages posted straight to JianYing's window (the cursor does not move, and JianYing can stay behind other windows).
"""
import shutil
import time
from pathlib import Path

import uiautomation as uia
import win32api
import win32con
import win32gui
import win32process

MAIN = "剪映专业版"   # JianYing's main window title
EXPORT_WIN = "导出"   # the export dialog (its own window, owned by the main window)
LOGIN_WIN = "登录"    # JianYing asks for a login when a project uses an item an anonymous user cannot get


class DriverError(Exception):
    pass


def _desc(c):
    try:
        return c.GetPropertyValue(30159) or ""  # UIA FullDescription: where JianYing puts its control names
    except Exception:  # noqa: BLE001
        return ""


def _hwnd_of(ctrl):
    """The native window that draws a control (its nearest ancestor with a window handle)."""
    c = ctrl
    for _ in range(40):
        if c is None:
            return None
        try:
            h = c.NativeWindowHandle
        except Exception:  # noqa: BLE001
            h = 0
        if h:
            return h
        c = c.GetParentControl()
    return None


def _post_click(ctrl):
    try:
        r = ctrl.BoundingRectangle
        hwnd = _hwnd_of(ctrl)
    except Exception as e:  # noqa: BLE001  (COMError: the control went away, e.g. its window is closing)
        raise DriverError(f"the control is gone ({type(e).__name__})") from e
    if not hwnd or r.width() <= 0:
        raise DriverError(f"cannot click {ctrl.ControlTypeName} {_desc(ctrl) or ctrl.Name!r}: no window or no size")
    cx, cy = win32gui.ScreenToClient(hwnd, ((r.left + r.right) // 2, (r.top + r.bottom) // 2))
    lp = win32api.MAKELONG(cx & 0xFFFF, cy & 0xFFFF)
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lp)
    time.sleep(0.02)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)


def bg_click(ctrl, prefer="message"):
    """Click a control without moving the user's mouse: mouse messages posted to its window (what JianYing's
    buttons react to), or UI Automation Invoke. Returns how it was done."""
    order = ["message", "invoke"] if prefer == "message" else ["invoke", "message"]
    for how in order:
        if how == "invoke":
            try:
                inv = ctrl.GetPattern(uia.PatternId.InvokePattern)
                if inv:
                    inv.Invoke()
                    return "invoke"
            except Exception:  # noqa: BLE001
                continue
        else:
            try:
                _post_click(ctrl)
                return "message"
            except DriverError:
                continue
    raise DriverError(f"cannot click {_desc(ctrl) or ctrl.Name!r}")


def click_until(ctrl, done, wait=3.0, tries=2, log=None):
    """Click (posted mouse message, then UI Automation Invoke) until done() is true. JianYing's controls differ:
    project tiles and the title-bar Export button react only to mouse messages, the dialog's Export button to Invoke."""
    for attempt in range(tries):
        for how in ("message", "invoke"):
            try:
                bg_click(ctrl, prefer=how)
            except DriverError:
                continue
            end = time.time() + wait
            while time.time() < end:
                if done():
                    if log:
                        log(f"({how})")
                    return how
                time.sleep(0.2)
    return None


def close_app_windows(titles, exe="jianyingpro.exe"):
    """Close (WM_CLOSE = cancel) visible top-level windows of JianYing with these titles. Returns the titles closed."""
    from ai_pc.desktop.appknow import exe_path
    found = []

    def cb(h, _):
        try:
            if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) in titles:
                pid = win32process.GetWindowThreadProcessId(h)[1]
                if str(exe_path(pid) or "").lower().endswith(exe):
                    found.append((h, win32gui.GetWindowText(h)))
        except Exception:  # noqa: BLE001
            pass
    win32gui.EnumWindows(cb, None)
    for h, _ in found:
        win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    return [t for _, t in found]


def keep_behind(hwnd):
    """Put a window at the bottom of the stack without activating it (the user's windows stay in front)."""
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
    except Exception:  # noqa: BLE001
        pass


class JianyingDriver:
    def __init__(self, kill=None, log=print, on_poll=None):
        self.kill, self.log, self.on_poll = kill, log, on_poll  # on_poll: e.g. a pop-up sweep, run from the same thread
        self.t0 = time.perf_counter()

    def _say(self, msg):
        self.log(f"  [{time.perf_counter() - self.t0:6.1f}s] {msg}", flush=True)

    def _check(self):
        if self.kill is not None and self.kill.event.is_set():
            raise DriverError("kill switch pressed")

    def _wait(self, fn, timeout, what, poll=0.25):
        """Poll fn() until it returns something truthy; DriverError after `timeout` seconds."""
        end = time.time() + timeout
        while True:
            self._check()
            r = fn()
            if r:
                return r
            if time.time() > end:
                raise DriverError(f"timed out after {timeout:.0f} s waiting for {what}")
            if self.on_poll:
                self.on_poll()
            time.sleep(poll)

    # ------------------------------------------------------------------ finding things
    @staticmethod
    def main():
        try:
            w = uia.WindowControl(searchDepth=1, Name=MAIN)
            return w if w.Exists(0) else None
        except Exception:  # noqa: BLE001  (COM errors while JianYing swaps windows)
            return None

    def state(self):
        """'export' | 'home' | 'edit' | 'other', or None while JianYing is closed or between windows."""
        try:
            w = self.main()
            if not w:
                return None
            if w.WindowControl(searchDepth=1, Name=EXPORT_WIN).Exists(0):
                return "export"
            cls = w.ClassName
            return "home" if "HomePage" in cls else ("edit" if "MainWindow" in cls else "other")
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def text(parent, desc, exact=True, depth=3):
        if parent is None:  # JianYing is between windows (or gone): nothing to find this time
            return None
        c = parent.TextControl(searchDepth=depth, Compare=lambda ctrl, d: (_desc(ctrl) == desc) if exact else (desc in _desc(ctrl)))
        return c if c.Exists(0) else None

    # ------------------------------------------------------------------ steps
    def to_home(self, timeout=30):
        if self.state() == "home":
            return
        if self.state() == "export":
            raise DriverError("an export dialog is open; not closing it blindly")
        w = self._wait(self.main, 10, "the JianYing window")
        if self.state() == "edit":
            close = w.GroupControl(searchDepth=1, ClassName="TitleBarButton", foundIndex=3)  # the editor's close button
            if not close.Exists(0):
                raise DriverError("editor close button not found")
            if not click_until(close, lambda: self.state() == "home", wait=6):
                raise DriverError("the editor did not close")
            self._say("closed the editor (JianYing saves the project) to get back to the home screen")
        self._wait(lambda: self.state() == "home", timeout, "the home screen")

    def open_project(self, name, timeout=120):
        self.to_home()
        self.main()
        for attempt in range(4):  # right after launch a click can land before the home list takes input: click again
            title = self._wait(lambda: self.text(self.main(), f"HomePageDraftTitle:{name}"), 30, f"project '{name}' in the home list")
            how = bg_click(title.GetParentControl(), prefer="message" if attempt % 2 == 0 else "invoke")
            self._say(f"opened project {name} ({how}" + (f", click {attempt + 1})" if attempt else ")"))
            try:
                self._wait(lambda: self.state() in ("edit", "export"), 8, "the editor")
                break
            except DriverError:
                if self.state() != "home" or attempt == 3:
                    self._wait(lambda: self.state() in ("edit", "export"), 30, "the editor")
                    break
        # the editor shows its Export button before it has finished loading: keep pressing it until the dialog opens
        end = time.time() + timeout
        while self.state() != "export":
            self._check()
            if time.time() > end:
                raise DriverError(f"the export dialog did not open within {timeout} s (editor still loading?)")
            btn = self.text(self.main(), "MainWindowTitleBarExportBtn", exact=False)
            if btn:
                bg_click(btn)
            t = time.time()
            while time.time() - t < 4 and self.state() != "export":
                if self.on_poll:
                    self.on_poll()
                time.sleep(0.25)
        w = self.main()
        if w:
            keep_behind(w.NativeWindowHandle)  # the editor may have come to the front: back behind the user's windows
        self._say("export dialog is open")

    def _dialog_for(self, name):
        """The open export dialog, if it is exporting `name` (so an interrupted run can carry on from it)."""
        if self.state() != "export":
            return None
        dlg = self.main().WindowControl(searchDepth=1, Name=EXPORT_WIN)
        path = self.text(dlg, "ExportPath", exact=False)
        sib = path.GetSiblingControl(lambda c: True) if path else None
        return dlg if sib and Path(_desc(sib)).stem == name else None

    def abort_export(self, why):
        """Close the export dialog (cancel) and any login window, go back home, and stop with `why`."""
        close_app_windows({LOGIN_WIN})
        close_app_windows({EXPORT_WIN})
        try:
            self._wait(lambda: self.state() in ("edit", "home"), 10, "the export dialog to close")
            self.to_home()
        except DriverError:
            pass
        raise DriverError(why)

    def export(self, name, output, resolution=None, framerate=None, render_timeout=900, preflight=None):
        """resolution / framerate: None keeps JianYing's remembered setting (its drop-downs do not open without the
        real mouse, which this driver never uses). preflight(): called once the project is open, before Export is
        pressed; a returned problem text cancels the export (e.g. items JianYing could not download)."""
        if close_app_windows({LOGIN_WIN}):
            self._say("closed a login window left open earlier")
        if not self._dialog_for(name):
            self.open_project(name)
        if preflight:
            problem = preflight()
            if problem:
                self.abort_export(problem)
        dlg = self.main().WindowControl(searchDepth=1, Name=EXPORT_WIN)
        path_label = self._wait(lambda: self.text(dlg, "ExportPath", exact=False), 15, "the export path field")
        sib = path_label.GetSiblingControl(lambda c: True)
        src = Path(_desc(sib)) if sib else None
        if not src or not src.suffix:
            raise DriverError(f"could not read the export path ({_desc(sib) if sib else None!r})")
        for field, value in (("ExportSharpnessInput", resolution), ("FrameRateInput", framerate)):
            if not value:
                continue
            box = self.text(dlg, field, exact=False, depth=4)
            if box:
                bg_click(box)
                try:
                    item = self._wait(lambda: self.text(self.main(), value, exact=True, depth=4), 3, f"the {value} option")
                    bg_click(item)
                except DriverError:
                    self._say(f"could not set {field} to {value}; keeping JianYing's current setting")
        finished = lambda: self.text(self.main(), "ExportSucceedCloseBtn", exact=False, depth=4) if self.main() else None  # noqa: E731
        if not finished():  # (an interrupted run may have left a finished or running export behind)
            ok = self.text(dlg, "ExportOkBtn")
            if ok:
                if src.exists():
                    src.unlink()  # a stale file of the same name would make the 'file appeared' check meaningless
                started = lambda: finished() or not self.text(self.main().WindowControl(searchDepth=1, Name=EXPORT_WIN), "ExportOkBtn")  # noqa: E731
                how = click_until(ok, lambda: started() or bool(close_app_windows({LOGIN_WIN})))
                if not how:
                    raise DriverError("the dialog's Export button did not start the export")
                if self.text(self.main().WindowControl(searchDepth=1, Name=EXPORT_WIN), "ExportOkBtn") and not finished():
                    self.abort_export("JianYing asked for a login to export: an item of this project needs an account")
                self._say(f"rendering to {src} ... ({how})")
            else:
                self._say("an export of this project is already running; waiting for it")
        def finished_or_blocked():
            if close_app_windows({LOGIN_WIN}):
                self.abort_export("JianYing asked for a login to export: an item of this project needs an account")
            return finished()
        done = self._wait(finished_or_blocked, render_timeout, "the export to finish", poll=1.0)
        self._say("render finished")
        # the video is complete now: take it into the project first (it must never stay in the user's Videos folder),
        # then close the dialog as well as possible (a dialog that stays open does not make a finished export fail)
        out = Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()
        self._wait(lambda: src.exists() and src.stat().st_size > 0, 20, "the exported file on disk")
        for _ in range(40):  # JianYing may hold the file for a moment after the render
            try:
                shutil.move(str(src), str(out))
                break
            except PermissionError:
                time.sleep(0.5)
        self._say(f"video moved to {out}")
        try:
            if not click_until(done, lambda: self.state() in ("edit", "home")):
                close_app_windows({EXPORT_WIN})
            self.to_home()
        except Exception as e:  # noqa: BLE001
            self._say(f"could not close the export dialog ({type(e).__name__}); the next export starts JianYing afresh if needed")
        return out
