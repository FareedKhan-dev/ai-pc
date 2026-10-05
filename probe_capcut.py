"""Probe whether CapCut exposes its UI through Windows UI Automation."""
import glob
import os
import subprocess
import time
from collections import Counter

import uiautomation as auto

exe = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\CapCut\Apps\*\CapCut.exe"))[0]
print("exe:", exe)
subprocess.Popen([exe])

win = None
for _ in range(40):
    time.sleep(1)
    w = auto.WindowControl(searchDepth=1, RegexName=r".*CapCut.*")
    if w.Exists(0, 0):
        win = w
        break
if not win:
    print("no CapCut window found")
    raise SystemExit
time.sleep(5)  # let UI finish rendering
print("window:", win.Name, win.ClassName)

t = time.perf_counter()
counts, named, samples = Counter(), 0, []
total = 0


def walk(c, depth=0, maxdepth=12):
    global named, total
    total += 1
    counts[c.ControlTypeName] += 1
    if c.Name:
        named += 1
        if len(samples) < 40 and c.ControlTypeName in ("ButtonControl", "MenuItemControl", "TabItemControl", "TextControl"):
            samples.append(f"{c.ControlTypeName}: {c.Name}")
    if depth < maxdepth:
        for ch in c.GetChildren():
            walk(ch, depth + 1, maxdepth)


walk(win)
print(f"walk: {time.perf_counter() - t:.2f}s  total={total} named={named}")
print(counts.most_common(12))
print("\n".join(samples))
