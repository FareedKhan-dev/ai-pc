"""Positive control: the same UIA method on Windows Calculator, with timings.

Answers two questions:
  1. Does my probe work on an app that *does* expose a UI tree? (so CapCut's empty tree is real)
  2. How fast is the "fast lane" really, and where does the time go?

Safety: hard 45 s kill-timer, and Calculator is always closed in `finally`.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time

import uiautomation as auto

if auto.WindowControl(searchDepth=1, Name="Calculator").Exists(0, 0):
    raise SystemExit("A Calculator window is already open; close it first so I don't touch your own.")

def close_calc():
    # same message the X button sends; WindowPattern.Close() silently fails on UWP frame windows
    try:
        ctypes.windll.user32.PostMessageW(win.NativeWindowHandle, 0x0010, 0, 0)
        for _ in range(20):
            time.sleep(0.25)
            if not win.Exists(0, 0):
                break
        print("calculator closed:", not win.Exists(0, 0), flush=True)
    except Exception as e:
        print("close failed:", e, flush=True)


def watchdog():
    print("WATCHDOG: took too long, closing", flush=True)
    close_calc()
    os._exit(2)


threading.Timer(45, watchdog).start()


def ms(t0):
    return (time.perf_counter() - t0) * 1000


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


subprocess.Popen(["calc.exe"])
win = auto.WindowControl(searchDepth=1, Name="Calculator")
try:
    if not win.Exists(20, 0.5):
        raise SystemExit("Calculator window not found")
    time.sleep(1.5)

    # 1) discovery: how much of the UI is visible, and how long does a full walk take?
    t0 = time.perf_counter()
    total = named = 0
    ids = set()

    def walk(c, d=0):
        global total, named
        total += 1
        named += bool(c.Name)
        if c.AutomationId:
            ids.add(c.AutomationId)
        if d < 12:
            for ch in c.GetChildren():
                walk(ch, d + 1)

    walk(win)
    print(f"[discovery] full walk {ms(t0):.0f} ms -> {total} elements, {named} named, {len(ids)} automation ids")

    # 2) find digit buttons once (client-side tree search)
    digits = ["num1Button", "num2Button", "num3Button", "num4Button"]
    t0 = time.perf_counter()
    btns = {n: win.ButtonControl(AutomationId=n) for n in digits}
    for b in btns.values():
        b.Exists(3, 0.1)
    print(f"[lookup]    find {len(digits)} controls: {ms(t0):.0f} ms ({ms(t0)/len(digits):.0f} ms each)")

    # 3) where does the per-action time go? split pattern fetch from Invoke
    fetch, inv = [], []
    for _ in range(10):
        for n in digits:
            t0 = time.perf_counter()
            p = btns[n].GetInvokePattern()
            fetch.append(ms(t0))
            if p is None:
                continue
            t0 = time.perf_counter()
            p.Invoke(waitTime=0)  # library default is a built-in 0.5 s sleep!
            inv.append(ms(t0))
    print(f"[split]     GetInvokePattern: median {pct(fetch,.5):.1f} ms | Invoke(): median {pct(inv,.5):.1f} ms, p95 {pct(inv,.95):.1f} ms  (n={len(inv)})")

    # 4) best case: fetch each pattern ONCE, then reuse the object
    pats = {n: btns[n].GetInvokePattern() for n in digits}
    lat = []
    for _ in range(25):
        for n in digits:
            t0 = time.perf_counter()
            pats[n].Invoke(waitTime=0)
            lat.append(ms(t0))
    print(f"[reuse]     cached pattern Invoke(): median {pct(lat,.5):.1f} ms, p95 {pct(lat,.95):.1f} ms, min {min(lat):.1f} ms (n={len(lat)})")

    # 5) can we read the result back? (verification step)
    t0 = time.perf_counter()
    shown = win.TextControl(AutomationId="CalculatorResults").Name
    print(f"[verify]    read display in {ms(t0):.0f} ms -> {shown!r}")
finally:
    close_calc()
    sys.stdout.flush()
    os._exit(0)
