"""Discover installed apps at runtime (so brand-new software is found without any setup), launch them, find windows."""

import difflib
import json
import subprocess
import time

import win32gui

from ai_pc.core.config import STATE
from ai_pc.desktop import uia


def installed_apps(refresh=False, max_age_s=86400):
    cache = STATE / "apps.json"
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < max_age_s:
        return json.loads(cache.read_text(encoding="utf-8"))
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"], capture_output=True, text=True, timeout=60
    ).stdout
    data = json.loads(out)
    apps = [{"name": a["Name"], "appid": a["AppID"]} for a in (data if isinstance(data, list) else [data])]
    STATE.mkdir(exist_ok=True)
    cache.write_text(json.dumps(apps), encoding="utf-8")
    return apps


def find_app(name):
    apps = installed_apps()
    q = name.lower()
    scored = []
    for a in apps:
        n = a["name"].lower()
        s = difflib.SequenceMatcher(None, q, n).ratio() + (0.6 if q in n else 0) + (0.2 if n.startswith(q) else 0)
        scored.append((s, a))
    scored.sort(key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.75:
        return scored[0][1]
    for a in installed_apps(refresh=True):  # maybe it was installed a minute ago
        if q in a["name"].lower():
            return a
    return None


def visible_windows():
    res = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
            res.append(h)

    win32gui.EnumWindows(cb, None)
    return res


def launch(name, timeout=15):
    """Start an installed app by (fuzzy) name and return (main window handle, app name)."""
    app = find_app(name)
    if not app:
        return None, f"no installed app matches {name!r}"
    before = set(visible_windows())
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['appid']}"])
    toks = [t for t in app["name"].lower().split() if len(t) > 2]
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h in visible_windows():
            if h in before:
                continue
            i = uia.window_info(h)
            if any(t in i["title"].lower() for t in toks) or any(t in i["proc"] for t in toks):
                return h, app["name"]
        time.sleep(0.05)
    return None, f"{app['name']} did not show a window within {timeout}s"


def find_window(title_substr=None, proc=None, exclude=()):
    for h in visible_windows():
        i = uia.window_info(h)
        if i["proc"] in exclude:
            continue
        if (title_substr and title_substr.lower() in i["title"].lower()) or (proc and proc.lower() == i["proc"]):
            return h
    return None
