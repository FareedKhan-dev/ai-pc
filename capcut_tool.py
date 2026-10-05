"""CapCut accessibility investigation tool (read-mostly; never clicks anything).

  python capcut_tool.py launch [--qt-a11y]   start CapCut detached, wait for its window
  python capcut_tool.py probe                windows, child HWNDs, UIA, MSAA, ports, loaded DLLs
  python capcut_tool.py shot NAME            screenshot of the CapCut window -> shots/NAME.png
  python capcut_tool.py close [--force]      WM_CLOSE its windows, verify processes are gone
"""
import ctypes
import glob
import os
import subprocess
import sys
import time
from collections import Counter

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels everywhere

import psutil  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402
import uiautomation as auto  # noqa: E402

INSTALL = os.path.expandvars(r"%LOCALAPPDATA%\CapCut")
EXE = glob.glob(INSTALL + r"\Apps\*\CapCut.exe")[0]


def capcut_procs():
    out = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        try:
            if p.info["exe"] and p.info["exe"].lower().startswith(INSTALL.lower()):
                out.append(p)
        except Exception:
            pass
    return out


def top_windows(pids, visible_only=True):
    res = []

    def cb(h, _):
        _, pid = win32process.GetWindowThreadProcessId(h)
        if pid in pids and (win32gui.IsWindowVisible(h) or not visible_only):
            res.append(h)

    win32gui.EnumWindows(cb, None)
    return res


def describe(h):
    return (
        f"hwnd={h} class={win32gui.GetClassName(h)!r} title={win32gui.GetWindowText(h)!r} "
        f"rect={win32gui.GetWindowRect(h)} visible={bool(win32gui.IsWindowVisible(h))}"
    )


def child_classes(h):
    c = Counter()

    def cb(ch, _):
        c[win32gui.GetClassName(ch)] += 1

    win32gui.EnumChildWindows(h, cb, None)
    return c


def msaa_child_count(hwnd):
    try:
        import comtypes.client

        comtypes.client.GetModule("oleacc.dll")
        from comtypes.gen.Accessibility import IAccessible

        ptr = ctypes.POINTER(IAccessible)()
        ctypes.oledll.oleacc.AccessibleObjectFromWindow(
            hwnd, ctypes.c_ulong(0xFFFFFFFC), ctypes.byref(IAccessible._iid_), ctypes.byref(ptr)
        )
        return ptr.accChildCount
    except Exception as e:  # noqa: BLE001
        return f"err:{str(e)[:60]}"


def uia_stats(hwnd, maxdepth=14):
    ctl = auto.ControlFromHandle(hwnd)
    total = named = 0
    types = Counter()
    sample = []
    t0 = time.perf_counter()

    def walk(c, d):
        nonlocal total, named
        total += 1
        types[c.ControlTypeName] += 1
        if c.Name:
            named += 1
            if len(sample) < 12 and c is not ctl:
                sample.append(f"{c.ControlTypeName}:{c.Name[:40]}")
        if d < maxdepth:
            for ch in c.GetChildren():
                walk(ch, d + 1)

    walk(ctl, 0)
    return total, named, types.most_common(6), sample, (time.perf_counter() - t0) * 1000


def cmd_launch():
    if capcut_procs():
        sys.exit("CapCut is already running; not touching your instance.")
    env = os.environ.copy()
    if "--qt-a11y" in sys.argv:
        env["QT_ACCESSIBILITY"] = "1"
        print("launching with QT_ACCESSIBILITY=1")
    subprocess.Popen([EXE], env=env, creationflags=0x00000008 | 0x00000200, close_fds=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(1.5)
        pids = {p.pid for p in capcut_procs()}
        wins = top_windows(pids)
        classes = [win32gui.GetClassName(h) for h in wins]
        if any("Splash" not in c for c in classes) and classes:
            time.sleep(4)
            break
    pids = {p.pid for p in capcut_procs()}
    for h in top_windows(pids):
        print(describe(h))


def cmd_probe():
    procs = capcut_procs()
    pids = {p.pid for p in procs}
    print(f"== processes ({len(procs)}):", sorted(Counter(p.name() for p in procs).items()))
    print("== visible top-level windows")
    wins = top_windows(pids)
    for h in wins:
        print(" ", describe(h))
        cc = child_classes(h)
        print("    child HWND classes:", dict(cc.most_common(8)) or "none")
    print("== UIA (raw walk) / MSAA per window")
    for h in wins:
        try:
            total, named, types, sample, t = uia_stats(h)
            print(f"  {win32gui.GetClassName(h)}: UIA {total} elements, {named} named, {t:.0f} ms, types={types}")
            if sample:
                print("     sample:", sample)
        except Exception as e:  # noqa: BLE001
            print("  UIA error:", str(e)[:100])
        print(f"  {win32gui.GetClassName(h)}: MSAA accChildCount = {msaa_child_count(h)}")
    print("== listening TCP ports owned by CapCut processes")
    found = False
    for c in psutil.net_connections(kind="inet"):
        if c.pid in pids and c.status == "LISTEN":
            print("  ", c.laddr, "pid", c.pid, psutil.Process(c.pid).name())
            found = True
    if not found:
        print("   none")
    print("== interesting loaded DLLs (all CapCut processes)")
    seen = set()
    for p in procs:
        try:
            for m in p.memory_maps(grouped=False):
                n = os.path.basename(m.path).lower()
                if any(k in n for k in ("uiautomationcore", "oleacc", "deepagents", "libcef", "chrome_elf", "platinumwebview", "qt6quick.", "qt6gui", "qwindows", "qtaccess", "nvda", "uia")):
                    seen.add((p.name(), n))
        except Exception:
            pass
    for name, dll in sorted(seen):
        print("  ", name, dll)


def cmd_shot(name):
    from PIL import ImageGrab

    pids = {p.pid for p in capcut_procs()}
    wins = top_windows(pids)
    if not wins:
        sys.exit("no visible CapCut window")
    h = max(wins, key=lambda w: (lambda r: (r[2] - r[0]) * (r[3] - r[1]))(win32gui.GetWindowRect(w)))
    try:
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass
    time.sleep(0.6)
    l, t, r, b = win32gui.GetWindowRect(h)
    os.makedirs("shots", exist_ok=True)
    path = os.path.join("shots", f"{name}.png")
    ImageGrab.grab(bbox=(l, t, r, b), all_screens=True).save(path)
    print("saved", path, (r - l, b - t))


def cmd_click(x, y):
    """Post a left click at SCREEN (x, y) to the topmost CapCut window under that point.

    Uses window messages, so the real mouse cursor and keyboard focus are not touched.
    """
    import win32con

    pids = {p.pid for p in capcut_procs()}
    # dialogs are separate top-level windows drawn over the main one: prefer the smallest window under the point
    hits = []
    for h in top_windows(pids):
        l, t, r, b = win32gui.GetWindowRect(h)
        if l <= x < r and t <= y < b:
            hits.append(((r - l) * (b - t), h))
    target = min(hits)[1] if hits else None
    if not target:
        sys.exit(f"no CapCut window contains ({x},{y})")
    cx, cy = win32gui.ScreenToClient(target, (x, y))
    lp = (cy << 16) | (cx & 0xFFFF)
    print(f"click ({x},{y}) -> hwnd {target} class={win32gui.GetClassName(target)!r} client=({cx},{cy})")
    win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lp)
    time.sleep(0.15)
    win32gui.PostMessage(target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
    time.sleep(0.08)
    win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lp)


def cmd_close():
    procs = capcut_procs()
    pids = {p.pid for p in procs}
    for h in top_windows(pids, visible_only=False):
        win32gui.PostMessage(h, 0x0010, 0, 0)  # WM_CLOSE
    for _ in range(40):
        time.sleep(0.5)
        if not capcut_procs():
            break
    left = capcut_procs()
    print("remaining CapCut processes:", [(p.pid, p.name()) for p in left] or "none")
    if left and "--force" in sys.argv:
        for p in left:
            try:
                p.kill()
            except Exception:
                pass
        time.sleep(1)
        print("after force:", [(p.pid, p.name()) for p in capcut_procs()] or "none")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "launch":
        cmd_launch()
    elif cmd == "probe":
        cmd_probe()
    elif cmd == "shot":
        cmd_shot(sys.argv[2] if len(sys.argv) > 2 else "capcut")
    elif cmd == "click":
        cmd_click(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "close":
        cmd_close()
    else:
        print(__doc__)
