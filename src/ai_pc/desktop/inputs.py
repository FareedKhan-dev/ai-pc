"""Direct keyboard / mouse injection with SendInput (no sleeps, no library delays) and window focus helpers."""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


KEYUP, UNICODE, EXTENDED = 0x2, 0x4, 0x1
VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "enter": 0x0D, "return": 0x0D, "esc": 0x1B,
      "escape": 0x1B, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "space": 0x20, "up": 0x26,
      "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "pgup": 0x21, "pageup": 0x21,
      "pgdn": 0x22, "pagedown": 0x22, "insert": 0x2D, "=": 0xBB, "+": 0xBB, "-": 0xBD, ",": 0xBC, ".": 0xBE,
      "/": 0xBF, ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD, "\\": 0xDC, "`": 0xC0}
for _i in range(1, 13):
    VK[f"f{_i}"] = 0x6F + _i
EXT_KEYS = {0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E, 0x5B}


def _send(items):
    arr = (INPUT * len(items))(*items)
    n = user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))
    if n != len(items):
        raise OSError(f"SendInput delivered {n}/{len(items)} events (blocked by a higher-privilege window?)")


def _key(vk, up=False, scan=0, flags=0):
    i = INPUT(type=1)
    ext = EXTENDED if (vk in EXT_KEYS and not flags & UNICODE) else 0
    i.ki = KEYBDINPUT(vk, scan, flags | (KEYUP if up else 0) | ext, 0, 0)
    return i


def _mouse(flags, data=0):
    i = INPUT(type=0)
    i.mi = MOUSEINPUT(0, 0, data, flags, 0, 0)
    return i


def vk_of(name):
    n = str(name).lower()
    if n in VK:
        return VK[n]
    if len(n) == 1 and n.isalnum():
        return ord(n.upper())
    raise ValueError(f"unknown key {name!r}")


def hotkey(*keys):
    vks = [vk_of(k) for k in keys]
    _send([_key(v) for v in vks] + [_key(v, up=True) for v in reversed(vks)])


def type_text(text):
    """Type any Unicode text in one batch (fast: no per-character delays)."""
    ev = []
    for ch in text:
        if ch == "\n":
            ev += [_key(0x0D), _key(0x0D, up=True)]
        else:
            ev += [_key(0, scan=ord(ch), flags=UNICODE), _key(0, up=True, scan=ord(ch), flags=UNICODE)]
    _send(ev)


def click(x, y, button="left", double=False):
    user32.SetCursorPos(int(x), int(y))
    d, u = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}[button]
    _send([_mouse(d), _mouse(u)] * (2 if double else 1))


def move(x, y):
    user32.SetCursorPos(int(x), int(y))


def hover(x, y):
    """Put the pointer on a spot with a genuine move event, so hover-only controls (a '+' on a thumbnail) appear."""
    user32.SetCursorPos(int(x) - 3, int(y))
    _send([_mouse(0x1)])
    time.sleep(0.03)
    user32.SetCursorPos(int(x), int(y))
    _send([_mouse(0x1)])


def drag(x1, y1, x2, y2, steps=25):
    """Press, move in small steps with real move events (apps need motion past their drag threshold), pause, release."""
    user32.SetCursorPos(int(x1), int(y1))
    time.sleep(0.05)
    _send([_mouse(0x2)])
    time.sleep(0.08)
    for i in range(1, steps + 1):
        user32.SetCursorPos(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
        _send([_mouse(0x1)])  # MOUSEEVENTF_MOVE (0,0): a genuine move event at the new position
        time.sleep(0.012)
    time.sleep(0.12)
    _send([_mouse(0x4)])


def scroll(amount, x=None, y=None):
    """amount > 0 scrolls up, < 0 down (in wheel notches)"""
    if x is not None:
        user32.SetCursorPos(int(x), int(y))
    _send([_mouse(0x800, ctypes.c_ulong(int(amount * 120) & 0xFFFFFFFF).value)])


def foreground():
    return user32.GetForegroundWindow()


def _wait_fg(hwnd, timeout):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if foreground() == hwnd:
            return True
        time.sleep(0.01)
    return foreground() == hwnd


def set_foreground(hwnd, timeout=0.6):
    """Bring a window to the front. Windows blocks background processes from stealing focus, so try, in order:
    attaching to the foreground thread's input, the task-switcher call (what Alt+Tab uses), and minimise/restore."""
    if foreground() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    cur = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(foreground(), None)
    user32.AttachThreadInput(cur, fg_tid, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur, fg_tid, False)
    if _wait_fg(hwnd, timeout / 3):
        return True
    user32.SwitchToThisWindow(hwnd, True)
    if _wait_fg(hwnd, timeout / 3):
        return True
    user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE (a restored window is activated)
    return _wait_fg(hwnd, timeout)


def close_window(hwnd):
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: the same message the X button sends
