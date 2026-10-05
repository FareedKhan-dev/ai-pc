"""The Windows side of the AI PC command bar: the global key combo, the tray icon, one copy running, what the person is
looking at when they press the combo, the clipboard, and opening results.

Nothing here watches the keyboard or moves the mouse: the combo is a Windows hotkey (RegisterHotKey; Windows tells only
this program, only when that combo is pressed), and 'still held?' is read with GetAsyncKeyState only while the combo is
down. What the person is looking at is read, never changed: the files selected in the File Explorer window (or on the
desktop) in front, or the document open in Word, Excel or PowerPoint in front.

  sh = Shell(on_event, {"bar": "ctrl+alt+space"}, tray=True)   # on_event("hotkey"|"hotkey_up"|"show"|"menu"|"tray", data) on its thread
  sh.start(); sh.ready.wait(); sh.registered -> {"bar": "Ctrl+Alt+Space"}
  context_files(foreground())                  -> ["C:\\Users\\me\\Videos\\clip.mp4"]
"""
import ctypes
import os
import re
import struct
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetConsoleWindow.restype = wintypes.HWND

MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
VK = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "insert": 0x2D, "home": 0x24, "end": 0x23, "pause": 0x13,
      "`": 0xC0, "backquote": 0xC0, "grave": 0xC0, ";": 0xBA, "/": 0xBF, "\\": 0xDC, ".": 0xBE, ",": 0xBC, "=": 0xBB,
      **{f"f{i}": 0x6F + i for i in range(1, 25)}}
NAMES = {0x20: "Space", 0x0D: "Enter", 0x09: "Tab", 0xC0: "`", **{0x6F + i: f"F{i}" for i in range(1, 25)}}
WM_HOTKEY, WM_APP, WM_CLOSE, WM_DESTROY, WM_COMMAND, WM_NULL = 0x0312, 0x8000, 0x0010, 0x0002, 0x0111, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_TRAY, WM_SHOWBAR = WM_APP + 7, WM_APP + 1
NIN_BALLOONUSERCLICK = 0x0405
ERROR_ALREADY_EXISTS = 183
OFFICE = {"OpusApp": ("Word.Application", "ActiveDocument"), "XLMAIN": ("Excel.Application", "ActiveWorkbook"),
          "PPTFrameClass": ("PowerPoint.Application", "ActivePresentation")}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------- the key combo
def parse_hotkey(text):
    """'ctrl+alt+space' -> (modifier bits, virtual key, 'Ctrl+Alt+Space'). ValueError when it is not one combo with a modifier."""
    parts = [p for p in re.split(r"\s*\+\s*", (text or "").strip().lower()) if p]
    mods, key = 0, None
    for p in parts:
        if p in MODS:
            mods |= MODS[p]
        elif key is None:
            key = p
        else:
            raise ValueError(f"two keys in '{text}'")
    if key is None or not mods:
        raise ValueError(f"'{text}' needs Ctrl, Alt, Shift or Win and one key")
    if key in VK:
        vk = VK[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"unknown key '{key}' in '{text}'")
    label = "+".join([n for n, b in (("Ctrl", 2), ("Alt", 1), ("Shift", 4), ("Win", 8)) if mods & b] + [NAMES.get(vk, chr(vk))])
    return mods, vk, label


def key_down(vk):
    """Is this key held right now (read only while the combo is down, to tell a tap from holding it to talk)."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class Shell(threading.Thread):
    """A never-shown window on its own thread for the global hotkeys, the tray icon and 'show yourself' from a second start.

    on_event(kind, data) is called on this thread: "hotkey" {name, vk, label, fg, time} when a combo is pressed, "hotkey_up"
    {name, held} when its key is let go, "show" from a second start, "tray" {click} for the icon, "menu" {id} for its menu.
    """

    def __init__(self, on_event, hotkeys, name="AIPC_Shell", tray=True, tip="AI PC", icon=None, menu=None, key_state=key_down,
                 fallbacks=(), front=None):
        super().__init__(daemon=True, name="aipc-shell")
        self.on_event, self.wanted, self.cls_name = on_event, dict(hotkeys), name
        self.tray, self.tip, self.icon_path, self.menu = tray, tip, icon, menu  # menu(): [(id, label, checked)] or None for a line
        self.key_state, self.fallbacks, self.front = key_state, list(fallbacks), front or foreground
        self.ready = threading.Event()
        self.hwnd, self.registered, self.failed, self.ids = None, {}, {}, {}
        self.tray_ok, self._hicon = False, None

    # runs on its own thread: everything a window needs lives here
    def run(self):
        import win32api
        import win32con
        import win32gui
        try:
            self._taskbar = win32gui.RegisterWindowMessage("TaskbarCreated")
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = self.cls_name
            wc.lpfnWndProc = {WM_HOTKEY: self._hotkey, WM_SHOWBAR: self._show, WM_TRAY: self._tray_msg, WM_COMMAND: self._command,
                              self._taskbar: self._readd, WM_CLOSE: self._close, WM_DESTROY: self._destroy}
            atom = win32gui.RegisterClass(wc)
            # an ordinary top-level window that is never shown (a message-only window would miss 'TaskbarCreated')
            self.hwnd = win32gui.CreateWindow(atom, self.tip, win32con.WS_OVERLAPPED, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
            for i, (name, combo) in enumerate(self.wanted.items(), 1):
                tries = [combo] + (self.fallbacks if i == 1 else [])
                for c in tries:
                    try:
                        mods, vk, label = parse_hotkey(c)
                    except ValueError as e:  # a typo in the settings: try the next combo
                        self.failed[c] = str(e)
                        continue
                    if user32.RegisterHotKey(self.hwnd, i, mods | MOD_NOREPEAT, vk):
                        self.registered[name], self.ids[i] = label, (name, vk, label)
                        break
                    self.failed[c] = ctypes.get_last_error()
            if self.registered:
                self.tip = f"{self.tip} ({next(iter(self.registered.values()))})"
            if self.tray:
                self._add_tray()
        except Exception as e:  # noqa: BLE001 - said through the event, the bar still works from the tray or a second start
            self.failed["window"] = repr(e)
        finally:
            self.ready.set()
        if self.hwnd:
            win32gui.PumpMessages()

    def _hotkey(self, hwnd, msg, wparam, lparam):
        item = self.ids.get(int(wparam))
        if not item:
            return 0
        name, vk, label = item
        t0 = time.monotonic()
        self.on_event("hotkey", {"name": name, "vk": vk, "label": label, "fg": self.front(), "time": t0})

        def watch():  # tell a tap from holding the combo down (to talk)
            while self.key_state(vk) and time.monotonic() - t0 < 120:
                time.sleep(0.02)
            self.on_event("hotkey_up", {"name": name, "held": time.monotonic() - t0})
        threading.Thread(target=watch, daemon=True, name="aipc-hold").start()
        return 0

    def _show(self, hwnd, msg, wparam, lparam):
        self.on_event("show", {"fg": self.front()})
        return 0

    def _close(self, hwnd, msg, wparam, lparam):
        import win32gui
        win32gui.DestroyWindow(hwnd)
        return 0

    def _destroy(self, hwnd, msg, wparam, lparam):
        import win32gui
        for i in self.ids:
            user32.UnregisterHotKey(hwnd, i)
        if self.tray_ok:
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
            except Exception:  # noqa: BLE001
                pass
        win32gui.PostQuitMessage(0)
        return 0

    # ---------------------------------------------------------------- tray
    def _load_icon(self):
        import win32api
        import win32con
        import win32gui
        if self._hicon:
            return self._hicon
        if self.icon_path and Path(self.icon_path).is_file():
            try:
                n = win32api.GetSystemMetrics(win32con.SM_CXSMICON)  # the tray's own icon size: sharp, not scaled down
                self._hicon = win32gui.LoadImage(0, str(self.icon_path), win32con.IMAGE_ICON, n, n, win32con.LR_LOADFROMFILE)
            except Exception:  # noqa: BLE001
                self._hicon = None
        return self._hicon or win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

    def _add_tray(self):
        import win32gui
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (self.hwnd, 0, flags, WM_TRAY, self._load_icon(), self.tip))
            self.tray_ok = True
        except Exception:  # noqa: BLE001 - no taskbar (a hidden desktop, Explorer restarting): 'TaskbarCreated' adds it later
            self.tray_ok = False

    def _readd(self, hwnd, msg, wparam, lparam):
        if self.tray:
            self._add_tray()
        return 0

    def _tray_msg(self, hwnd, msg, wparam, lparam):
        ev = lparam & 0xFFFF
        if ev == WM_LBUTTONUP or ev == NIN_BALLOONUSERCLICK:
            self.on_event("tray", {"click": "balloon" if ev == NIN_BALLOONUSERCLICK else "left", "fg": self.front()})
        elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU) and self.menu:
            self._popup()
        return 0

    def _popup(self):
        import win32con
        import win32gui
        m = win32gui.CreatePopupMenu()
        for item in self.menu() or []:
            if item is None:
                win32gui.AppendMenu(m, win32con.MF_SEPARATOR, 0, "")
            else:
                mid, label, checked = item
                win32gui.AppendMenu(m, win32con.MF_STRING | (win32con.MF_CHECKED if checked else 0), mid, label)
        x, y = win32gui.GetCursorPos()
        try:
            win32gui.SetForegroundWindow(self.hwnd)  # the documented way to have the menu close when clicking elsewhere
        except Exception:  # noqa: BLE001 - Windows said no: the menu still opens
            pass
        win32gui.TrackPopupMenu(m, win32con.TPM_LEFTALIGN | win32con.TPM_BOTTOMALIGN | win32con.TPM_RIGHTBUTTON, x, y, 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, WM_NULL, 0, 0)
        win32gui.DestroyMenu(m)

    def _command(self, hwnd, msg, wparam, lparam):
        self.on_event("menu", {"id": wparam & 0xFFFF})
        return 0

    def notify(self, title, text):
        """A Windows notification from the tray icon (for a long job that finished while the bar was hidden)."""
        if not self.tray_ok:
            return False
        import win32gui
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, (self.hwnd, 0, win32gui.NIF_INFO, WM_TRAY, self._load_icon(), self.tip,
                                                            text[:250], 10000, title[:60], 0x4))  # NIIF_USER: our icon
            return True
        except Exception:  # noqa: BLE001
            return False

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


# ---------------------------------------------------------------- one copy running
def single_instance(name="Local\\AIPC_Bar"):
    """A handle when this is the only copy running (keep it open while running), else None."""
    h = kernel32.CreateMutexW(None, False, name)
    if not h:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(h)
        return None
    return h


def poke_running(cls_name="AIPC_Shell"):
    """Ask the copy already running to show its bar (a second start does that, then ends)."""
    hwnd = user32.FindWindowW(cls_name, None)
    return bool(hwnd and user32.PostMessageW(hwnd, WM_SHOWBAR, 0, 0))


# ---------------------------------------------------------------- the window in front
def _text(hwnd):
    b = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, b, 512)
    return b.value


def _cls(hwnd):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, b, 256)
    return b.value


def foreground():
    """{"hwnd", "class", "title", "pid"} of the window in front (read when the combo is pressed, before the bar shows)."""
    h = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    if h:
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return {"hwnd": int(h or 0), "class": _cls(h) if h else "", "title": _text(h) if h else "", "pid": pid.value}


def explorer_selection(top):
    """The files selected in the File Explorer window `top` (the tab in front when it has tabs)."""
    import pythoncom
    import win32com.client
    import win32gui
    from win32com.shell import shell
    front_tab = win32gui.FindWindowEx(top, 0, "ShellTabWindowClass", None)  # the tab in front is the first one
    wins = win32com.client.Dispatch("Shell.Application").Windows()
    for i in range(wins.Count):
        w = wins.Item(i)
        try:
            if w is None or int(w.HWND) != top:
                continue
            try:
                tab = w._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider).QueryService(shell.SID_STopLevelBrowser, shell.IID_IShellBrowser).GetWindow()
            except Exception:  # noqa: BLE001 - older Explorer: one tab per window
                tab = None
            if tab and front_tab and tab != front_tab:
                continue
            items = w.Document.SelectedItems()
            return [items.Item(j).Path for j in range(min(items.Count, 50))]
        except Exception:  # noqa: BLE001 - a window closing while we look
            continue
    return []


def desktop_selection():
    """The files selected on the desktop."""
    import win32com.client
    d = win32com.client.Dispatch("Shell.Application").Windows().FindWindowSW(0, 0, 8, 0, 1)  # SWC_DESKTOP, SWFO_NEEDDISPATCH
    items = d.Document.SelectedItems()
    return [items.Item(j).Path for j in range(min(items.Count, 50))]


def office_document(cls):
    """The saved file open in the Word / Excel / PowerPoint window in front."""
    import win32com.client
    prog, prop = OFFICE[cls]
    doc = getattr(win32com.client.GetActiveObject(prog), prop)
    name = str(doc.FullName) if doc is not None else ""
    return [name] if re.match(r"^[A-Za-z]:\\|^\\\\", name) else []


def context_files(fg, timeout=1.5):
    """What the person is looking at when they pressed the combo: selected files in the Explorer window or desktop in front,
    or the document open in Office in front. Read only; [] when there is nothing (or it takes too long)."""
    cls = (fg or {}).get("class", "")
    if cls not in ("CabinetWClass", "ExploreWClass", "Progman", "WorkerW") and cls not in OFFICE:
        return []
    found = []

    def work():
        import pythoncom
        pythoncom.CoInitialize()
        try:
            if cls in ("CabinetWClass", "ExploreWClass"):
                found.extend(explorer_selection(fg["hwnd"]))
            elif cls in ("Progman", "WorkerW"):
                found.extend(desktop_selection())
            else:
                found.extend(office_document(cls))
        except Exception:  # noqa: BLE001 - nothing to read is not an error
            pass
        finally:
            pythoncom.CoUninitialize()
    t = threading.Thread(target=work, daemon=True, name="aipc-context")
    t.start()
    t.join(timeout)
    out = []
    for p in list(found):
        try:
            if p and Path(p).exists() and str(Path(p)) not in out:
                out.append(str(Path(p)))
        except OSError:
            continue
    return out


def where_from(fg):
    """'File Explorer' / 'Word' / 'the desktop' for the chips that show where the files came from."""
    return {"CabinetWClass": "File Explorer", "ExploreWClass": "File Explorer", "Progman": "the desktop", "WorkerW": "the desktop",
            "OpusApp": "Word", "XLMAIN": "Excel", "PPTFrameClass": "PowerPoint"}.get((fg or {}).get("class", ""), "")


def bring_to_front(hwnd):
    """Give the bar the keyboard. Allowed right after our hotkey; else attach to the thread in front for a moment."""
    if user32.SetForegroundWindow(hwnd):
        return True
    fg = user32.GetForegroundWindow()
    other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    if other and other != me and user32.AttachThreadInput(me, other, True):
        try:
            return bool(user32.SetForegroundWindow(hwnd))
        finally:
            user32.AttachThreadInput(me, other, False)
    return False


def has_console():
    """Does this program have a console, with a window or not? pythonw has none, so console programs it started would each open one."""
    return bool(kernel32.GetConsoleCP())


def is_ours(hwnd):
    """Does this window belong to this program (the bar, or a dialog it opened)?"""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def work_area(hwnd=None):
    """(left, top, right, bottom) of the screen area (without the taskbar) of the monitor with that window, else the one with the mouse."""
    if hwnd:
        mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    else:
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        mon = user32.MonitorFromPoint(pt, 2)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        r = mi.rcWork
        return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ---------------------------------------------------------------- look
def theme():
    """{"dark": bool, "accent": "#rrggbb" or None} from the Windows settings (Personalization > Colors)."""
    import winreg
    dark, accent = False, None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            dark = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            v = winreg.QueryValueEx(k, "AccentColor")[0]  # 0xAABBGGRR
            accent = f"#{v & 0xFF:02x}{(v >> 8) & 0xFF:02x}{(v >> 16) & 0xFF:02x}"
    except OSError:
        pass
    return {"dark": dark, "accent": accent}


def style_window(hwnd, dark, border=None):
    """Windows 11 look for a borderless window: rounded corners, a thin border, a shadow (each skipped where Windows has none)."""
    dwm = ctypes.WinDLL("dwmapi")
    top = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT

    def attr(n, value):
        v = ctypes.c_int(value)
        return dwm.DwmSetWindowAttribute(wintypes.HWND(top), n, ctypes.byref(v), ctypes.sizeof(v)) == 0
    ok = attr(33, 2)  # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
    attr(20, 1 if dark else 0)  # DWMWA_USE_IMMERSIVE_DARK_MODE
    if border:
        r, g, b = int(border[1:3], 16), int(border[3:5], 16), int(border[5:7], 16)
        attr(34, r | (g << 8) | (b << 16))  # DWMWA_BORDER_COLOR (COLORREF)
    try:
        get, put = (user32.GetClassLongPtrW, user32.SetClassLongPtrW) if hasattr(user32, "GetClassLongPtrW") else (user32.GetClassLongW, user32.SetClassLongW)
        get.restype = put.restype = ctypes.c_size_t
        get.argtypes = [wintypes.HWND, ctypes.c_int]
        put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_size_t]
        put(top, -26, get(top, -26) | 0x00020000)  # GCL_STYLE |= CS_DROPSHADOW
    except Exception:  # noqa: BLE001
        pass
    return ok, int(top)


def dpi_aware():
    """Sharp text on high-DPI screens (call before the window is made)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        try:
            user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- clipboard and files
def clipboard_files_or_image(save_dir):
    """Files copied in Explorer, or a copied picture saved as a PNG in save_dir; [] for plain text (the box pastes that)."""
    try:
        from PIL import ImageGrab
        got = ImageGrab.grabclipboard()
    except Exception:  # noqa: BLE001
        return []
    if isinstance(got, list):
        return [str(Path(p)) for p in got if Path(p).exists()][:20]
    if got is not None and hasattr(got, "save"):
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        p = Path(save_dir) / f"pasted_{time.strftime('%Y%m%d_%H%M%S')}.png"
        got.save(p)
        return [str(p)]
    return []


def dropfiles(paths):
    """The CF_HDROP bytes for these files (what Explorer puts on the clipboard when you copy files)."""
    names = ("\0".join(str(Path(p).resolve()) for p in paths) + "\0\0").encode("utf-16-le")
    return struct.pack("<IiiII", 20, 0, 0, 0, 1) + names  # DROPFILES: offset of the names, point, fNC, wide characters


def copy_files(paths):
    """Put files on the clipboard, so Ctrl+V pastes them in Explorer, WhatsApp, Slack, an email."""
    import win32clipboard
    import win32con
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, dropfiles(paths))
        win32clipboard.SetClipboardData(win32clipboard.RegisterClipboardFormat("Preferred DropEffect"), struct.pack("<I", 1))  # copy
    finally:
        win32clipboard.CloseClipboard()


def open_file(path):
    os.startfile(str(path))  # noqa: S606 - the person clicked it


def show_in_folder(path):
    subprocess.Popen(["explorer", f"/select,{Path(path)}"])  # noqa: S603,S607


# ---------------------------------------------------------------- starting
def launch_command(root, executable=None, startup=False):
    """The command that starts the bar with no window of its own (pythonw), as the shortcut and Windows' Run list use it
    (startup: quietly, with no 'ready' notification at every sign-in)."""
    exe = Path(executable or sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    return f'"{pyw}" -m ai_pc bar' + (" --startup" if startup else "")


def starts_with_windows(name="AIPC"):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return False


def set_starts_with_windows(on, command, name="AIPC"):
    """Start the bar when you sign in to Windows (your own Run list; turned on or off only from the tray menu)."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass


def make_shortcut(lnk, command, icon=None, workdir=None):
    """A Windows shortcut (.lnk) that runs command (to pin the bar to Start or the taskbar)."""
    import pythoncom
    from win32com.shell import shell
    exe, args = re.match(r'^"([^"]+)"\s*(.*)$', command).groups()
    pythoncom.CoInitialize()
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(exe)
    link.SetArguments(args)
    link.SetWorkingDirectory(str(workdir or Path(exe).parent))
    link.SetDescription("AI PC: press the key combo and ask")
    if icon:
        link.SetIconLocation(str(icon), 0)
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(lnk), 0)
    return Path(lnk).is_file()
