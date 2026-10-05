"""What the agent can learn about an app before touching it: the app's own keyboard shortcuts.

Many apps ship their keymap as a data file (CapCut: User Data/Config/Shortcut/*.json, ~80 editor actions such as
importMedia=Ctrl+I, exportVideo=Ctrl+M). Pressing a known shortcut is instant and exact; finding the same button by
vision costs seconds and can miss. Discovery runs once per app version (cached in state/appknow/).
"""
import ctypes
import json
import os
import re
import time
from pathlib import Path

from ai_pc.core.config import STATE

COMBO = re.compile(r"^(?:(?:ctrl|control|shift|alt|cmd|command|meta|win|option)\+)*"
                   r"(?:f\d{1,2}|[a-z0-9]|space|enter|return|escape|esc|tab|backspace|del|delete|home|end|up|down|left|"
                   r"right|pageup|pagedown|insert|[`\-=\[\];',./+])$", re.I)
HINT = re.compile(r"shortcut|hotkey|keymap|key_?bind|keyboard|accelerator", re.I)
SKIP_DIRS = re.compile(r"cache|log|temp|tmp|crash|dump|project|draft|media|thumb|effect|font|sticker|download|backup|"
                       r"resource[s]?$|locale|lang|node_modules|\.git", re.I)
EXTS = {".json", ".ini", ".cfg", ".conf", ".txt", ".xml", ""}
RESERVED = {"ctrl+alt+q"}  # the harness kill switch
FIRST = ("new", "open", "import", "export", "save", "render", "undo", "redo", "copy", "paste", "cut", "delete", "del",
         "select", "play", "find", "search", "zoom", "split", "close")
last_source = ""


def exe_path(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf, n = ctypes.create_unicode_buffer(1024), ctypes.c_ulong(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else None
    finally:
        k32.CloseHandle(h)


def _combos(v):
    out = []
    for x in (v if isinstance(v, list) else [v]):
        if isinstance(x, str):
            s = x.strip().replace(" ", "")
            if s and COMBO.match(s) and s.lower() not in RESERVED:
                out.append(s)
    return out


def _walk(o, out):
    if isinstance(o, dict):
        name = next((o[k] for k in ("command", "action", "name", "id") if isinstance(o.get(k), str)), None)
        keyv = next((o[k] for k in ("key", "keys", "shortcut", "hotkey", "accelerator", "binding") if k in o), None)
        if name and keyv is not None and _combos(keyv):
            out.setdefault(name, _combos(keyv))
        for k, v in o.items():
            c = _combos(v) if isinstance(k, str) and re.match(r"^[A-Za-z][\w .-]{1,60}$", k) else []
            if c:
                out.setdefault(k, c)
            elif isinstance(v, (dict, list)):
                _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


def parse_file(p):
    """{action: [combo, ...]} from a keymap file (JSON, or key=value lines)."""
    try:
        text = Path(p).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    out = {}
    try:
        _walk(json.loads(text), out)
    except ValueError:
        for k, v in re.findall(r"^\s*([A-Za-z][\w .-]{1,60}?)\s*[=:]\s*\"?([^\"\r\n]+?)\"?\s*$", text, re.M):
            c = _combos([s for s in re.split(r"[,;|]\s*", v)])
            if c:
                out.setdefault(k, c)
    return out


def _roots(exe):
    exe = Path(exe)
    name = exe.stem.lower()
    roots = [exe.parent]
    for anc in list(exe.parents)[:4]:
        if name in anc.name.lower():
            roots.append(anc)
    for env in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA"):
        base = os.environ.get(env)
        if base:
            roots += [Path(base) / exe.stem, Path(base) / "Programs" / exe.stem]
    seen, out = set(), []
    for r in roots:
        k = str(r).lower()
        if k not in seen and r.is_dir():
            seen.add(k)
            out.append(r)
    return out


def discover(exe, budget_s=1.5, max_files=8000):
    """Find keymap files under the app's install/data folders and return (source file, {action: combos})."""
    t0, n, found = time.time(), 0, []
    for root in _roots(exe):
        base = len(root.parts)
        for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
            depth = len(Path(dirpath).parts) - base
            dirs[:] = [] if depth >= 6 else [d for d in dirs if not SKIP_DIRS.search(d)]
            for f in files:
                n += 1
                p = Path(dirpath) / f
                if p.suffix.lower() in EXTS and (HINT.search(f) or HINT.search(Path(dirpath).name)):
                    try:
                        if p.stat().st_size < 1_000_000:
                            keys = parse_file(p)
                            if len(keys) >= 3:
                                found.append((p, keys))
                    except OSError:
                        pass
            if n > max_files or time.time() - t0 > budget_s:
                break
    if not found:
        return None, {}

    def score(item):  # several schemes (e.g. Custom1..3, "Premiere Pro"): prefer the app's default one
        s = item[0].stem.lower()
        return (("default" in s) * 3 + (s.endswith("1") or "custom" in s) * 2 + len(item[1]) / 50, -len(s))
    src, keys = max(found, key=score)
    return str(src), keys


def shortcuts(pid):
    """(source, {action: combos}) for the app that owns `pid`, cached per executable version."""
    exe = exe_path(pid)
    if not exe:
        return None, {}
    cache = STATE / "appknow" / (re.sub(r"[^\w.-]", "_", Path(exe).stem) + ".json")
    try:
        mtime = os.path.getmtime(exe)
        if cache.exists():
            c = json.loads(cache.read_text(encoding="utf-8"))
            if c.get("exe") == exe and c.get("mtime") == mtime:
                return c.get("source"), c.get("keys", {})
    except (OSError, ValueError):
        mtime = None
    src, keys = discover(exe)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"exe": exe, "mtime": mtime, "source": src, "keys": keys}, indent=1), encoding="utf-8")
    except OSError:
        pass
    return src, keys


def shortcuts_text(pid, max_chars=1800):
    """Planner-ready summary of the app's shortcuts, or '' if the app ships no keymap."""
    global last_source
    src, keys = shortcuts(pid)
    last_source = src or ""
    if not keys:
        return ""
    first = [k for k in keys if any(k.lower().startswith(w) for w in FIRST)]
    order = first + sorted(k for k in keys if k not in first)
    items, size = [], 0
    for k in order:
        s = f"{k}={'/'.join(keys[k][:2])}"
        if size + len(s) > max_chars:
            break
        items.append(s)
        size += len(s) + 2
    return (f"APP SHORTCUTS (read from the app's own keymap file {Path(src).name}; exact and instant, so prefer them to "
            "clicking when one fits. They need the app window focused and the right view open, e.g. editor shortcuts "
            "need a project open): " + "; ".join(items))
