"""AutoHotkey v2 (tools/autohotkey; GitHub's and Scoop's SHA-256 agree): Windows automation scripts from words: text
expansion ('brb -> be right back') and hotkeys ('ctrl+alt+n opens notepad', 'win+shift+d types the date'). Checked by
AutoHotkey itself (/validate loads the script without running it: any syntax error comes back with its line), and every
item asked for is in the script. Starting a script puts its hotkeys on the user's own keyboard, so it waits for a yes;
'autohotkey stop' ends the scripts it started. A .ahk file given is checked the same way.

  'autohotkey script: brb -> be right back; addr -> House 12, Street 4, Lahore; ctrl+alt+n opens notepad; win+shift+d types the date'
  'autohotkey start it'   'autohotkey stop'   'autohotkey check macros.ahk'
"""

import re
import subprocess
from datetime import datetime
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "autohotkey", "AutoHotkey: text expansions and hotkeys from words, checked by AutoHotkey; started after a yes, stopped on request"
EXAMPLES = ["autohotkey script: brb -> be right back; ctrl+alt+n opens notepad; win+shift+d types the date", "autohotkey start it", "autohotkey stop"]
OUTWARD = {"start"}
EXE = ROOT / "tools" / "autohotkey" / "AutoHotkey64.exe"
APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "vs code": "code",
    "vscode": "code",
    "task manager": "taskmgr.exe",
    "snipping tool": "snippingtool.exe",
    "settings": "ms-settings:",
    "downloads": "shell:Downloads",
    "documents": "shell:Personal",
}
MODS = {"ctrl": "^", "control": "^", "alt": "!", "shift": "+", "win": "#", "windows": "#"}
KEY = r"[a-z0-9]|f\d{1,2}|space|enter|tab|home|end|delete|insert|pgup|pgdn|up|down|left|right"


def q(text):
    """An AutoHotkey v2 string literal."""
    return '"' + text.replace("`", "``").replace('"', '`"') + '"'


def item(text):
    """One request item -> (kind, AutoHotkey line, description) or None."""
    t = text.strip().strip(".")
    m = re.match(
        rf"^((?:(?:ctrl|control|alt|shift|win|windows)\s*\+\s*)+)({KEY})\s+(opens?|runs?|starts?|launch(?:es)?|types?|writes?|pastes?)\s+(.+)$",
        t,
        re.I,
    )
    if m:
        mods = "".join(dict.fromkeys(MODS[x.strip().lower()] for x in m.group(1).split("+") if x.strip()))
        key, verb, what = m.group(2).lower(), m.group(3).lower(), m.group(4).strip().strip("'\"")
        if verb.startswith(("type", "write", "paste")):
            if re.fullmatch(r"(?:the |today'?s )?date", what, re.I):
                action = 'SendText FormatTime(, "dd-MM-yyyy")'
            elif re.fullmatch(r"(?:the )?(?:current )?time", what, re.I):
                action = 'SendText FormatTime(, "HH:mm")'
            else:
                action = f"SendText {q(what)}"
        else:
            target = APPS.get(what.lower(), what)
            action = f"Run {q(target)}"
        return "hotkey", f"{mods}{key}::{action}", f"{m.group(1).replace(' ', '')}{key} {verb} {what}"
    m = re.match(r"^(\S{2,20})\s*(?:->|=>|→)\s*(.+)$", t)
    if m:
        abbr, full = m.group(1), m.group(2).strip()
        if ":" in abbr or "`" in abbr:
            return None
        return "hotstring", f":T:{abbr}::{full.replace('`', '``').replace(';', '`;')}", f"{abbr} -> {full}"
    return None


def validate(script):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run([str(EXE), "/ErrorStdOut", "/validate", str(script)], timeout=60)
    msg = (out + err).strip()
    m = re.search(r"\((\d+)\) : ==> (.+)", msg)
    return rc == 0 and not timed_out, (f"{Path(script).name}:{m.group(1)} {m.group(2).strip()}" if m else msg[-200:])


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bautohotkey\b|\bahk\b", c):
        return None
    if re.search(r"\bstop\b|\bquit\b|\bexit\b|\bend\b", c) and not re.search(r"script\s*:", c):
        return {"op": "stop"}
    f = find_file(text, ctx, {".ahk"})
    if re.search(r"\bstart\b|\brun\b|\bturn on\b|\bactivate\b", c) and not re.search(r"script\s*:", c):
        return {"op": "start", "file": f}
    if f and re.search(r"\bcheck\b|\bvalidate\b|\btest\b", c):
        return {"op": "check", "file": f}
    m = re.search(r"(?:script|macros?|shortcuts?|hotkeys?)\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        return {"op": "make", "items": [s for s in re.split(r";|\n", m.group(1)) if s.strip()]}
    return None


def _script(op, ctx):
    return op.get("file") or ((ctx.get("memo") or {}).get("autohotkey") or {}).get("script")


def preview(op, ctx):
    script = _script(op, ctx)
    if not script or not Path(script).exists():
        op["blocked"] = True
        return "There is no AutoHotkey script yet: ask for one first (e.g. autohotkey script: brb -> be right back; ctrl+alt+n opens notepad)."
    ok, why = validate(script)
    if not ok:
        op["blocked"] = True
        return f"{Path(script).name} has an error, so it will not be started: {why}."
    lines = [ln for ln in Path(script).read_text(encoding="utf-8").splitlines() if "::" in ln and not ln.startswith(";")]
    return (
        f"Start {Path(script).name} ({len(lines)} hotkey(s)/text expansion(s)): they work in every app until you exit it "
        "(right-click the green H in the taskbar corner, or say 'autohotkey stop')."
    )


def run(op, ctx):
    if not EXE.exists():
        return "AutoHotkey is not in tools/autohotkey."
    memo = ctx.setdefault("memo", {}).setdefault("autohotkey", {})
    if op["op"] == "stop":
        pids = memo.pop("pids", [])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=0x08000000)
        alive = [
            pid
            for pid in pids
            if str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, creationflags=0x08000000).stdout
        ]
        return (
            f"Stopped {len(pids)} AutoHotkey script(s) I started." + (" Checked: none is still running." if not alive else f" NOT stopped: {alive}")
            if pids
            else "No AutoHotkey script started by me is running."
        )
    if op["op"] == "start":
        script = _script(op, ctx)
        p = subprocess.Popen([str(EXE), str(script)])  # on the user's desktop: hotkeys only work there
        memo.setdefault("pids", []).append(p.pid)
        import time

        time.sleep(1.5)
        return f"Started {Path(script).name}. " + (
            "Checked: it is running (its green H is in the taskbar corner)."
            if p.poll() is None
            else f"NOT running: it ended with code {p.returncode}."
        )
    if op["op"] == "check":
        ok, why = validate(op["file"])
        return f"AutoHotkey checked {Path(op['file']).name}: " + ("no errors." if ok else f"FAILED: {why}.")
    parsed = [(s, item(s)) for s in op["items"]]
    good = [x for _, x in parsed if x]
    unknown = [s.strip() for s, x in parsed if not x]
    if not good:
        return (
            "I could not read any item. Write text expansions as 'brb -> be right back' and hotkeys as 'ctrl+alt+n opens notepad' "
            "or 'win+shift+d types the date', separated by ';'."
        )
    out = (Path(ctx["out"]) / "autohotkey").resolve()
    out.mkdir(parents=True, exist_ok=True)
    script = out / "my_shortcuts.ahk"
    hotstrings = [line for kind, line, _ in good if kind == "hotstring"]
    hotkeys = [line for kind, line, _ in good if kind == "hotkey"]
    text = (
        "#Requires AutoHotkey v2.0\n#SingleInstance Force\n"
        f"; Made by the AI PC on {datetime.now():%Y-%m-%d}. Exit or pause: right-click the green H in the taskbar corner.\n"
        + ("\n; Text expansion: type the short form, then a space, Enter or punctuation\n" + "\n".join(hotstrings) + "\n" if hotstrings else "")
        + ("\n; Hotkeys (^ Ctrl, ! Alt, + Shift, # Win)\n" + "\n".join(hotkeys) + "\n" if hotkeys else "")
    )
    script.write_text(text, encoding="utf-8-sig")  # with a BOM: AutoHotkey then reads it as UTF-8
    ok, why = validate(script)
    memo["script"] = str(script)
    written = sum(1 for ln in script.read_text(encoding="utf-8-sig").splitlines() if "::" in ln and not ln.startswith(";"))
    checks = [("AutoHotkey loads it with no errors (/validate, nothing run)", ok), (f"all {len(good)} item(s) are in it", written == len(good))]
    bad = [w for w, g in checks if not g]
    return (
        f"AutoHotkey script {script}: "
        + "; ".join(d for _, _, d in good)
        + ". "
        + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f" ({why}).")
        + (f" Not understood: {', '.join(unknown)}." if unknown else "")
        + " Say 'autohotkey start it' to turn it on (after a yes)."
    )
