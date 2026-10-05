"""Looking after the PC by code: apps installed, updated and removed with winget (Windows' own package manager; each
change shown first and done after a yes), disk space, Windows Security (Defender) status and a quick scan, Wi-Fi and
battery. Reads run at once; installs, updates, removals and scans wait for a yes.

  'which apps can be updated?'  'update vlc'  'install 7-zip'  'how much disk space is left?'  'is my antivirus on?'  'wifi'  'battery'
"""
import json
import re
import subprocess
import unicodedata

import psutil

NAME, LABEL = "pccare", "PC care: apps (winget), disk, antivirus, Wi-Fi, battery"
EXAMPLES = ["which apps can be updated?", "install 7-zip", "how much disk space is left?", "is my antivirus on?"]
OUTWARD = {"install", "upgrade", "uninstall", "scan"}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NOWIN)
    return r.returncode, r.stdout, r.stderr


def _ps(script, timeout=120):
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script], timeout)


def _width(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def table(text):
    """winget's column table -> [{column: value}], cut by display width (a Chinese name is twice as wide as it is long)."""
    lines = [re.sub(r"^.*\r", "", ln) for ln in text.splitlines()]
    head = next((i for i, ln in enumerate(lines) if re.match(r"^\s*Name\s+Id\s+Version", ln)), None)
    if head is None:
        return []
    names = re.findall(r"\S+", lines[head])
    starts = [m.start() for m in re.finditer(r"\S+", lines[head])]
    rows = []
    for ln in lines[head + 2:]:
        if not ln.strip() or re.match(r"^\s*\d+ (?:upgrades?|packages?) ", ln) or set(ln.strip()) <= {"-"}:
            continue
        cells, col, buf, k = [], 0, "", 1
        for ch in ln:
            if k < len(starts) and col >= starts[k]:
                cells.append(buf.strip())
                buf, k = "", k + 1
            buf += ch
            col += _width(ch)
        cells.append(buf.strip())
        rows.append(dict(zip(names, cells + [""] * (len(names) - len(cells)))))
    return rows


def upgrades():
    code, out, err = _run(["winget", "upgrade", "--accept-source-agreements", "--disable-interactivity"])
    return [r for r in table(out) if r.get("Id")]


def search(words):
    code, out, err = _run(["winget", "search", words, "--accept-source-agreements", "--disable-interactivity", "--source", "winget"])
    return [r for r in table(out) if r.get("Id")]


def installed(words=None):
    cmd = ["winget", "list", "--accept-source-agreements", "--disable-interactivity"] + (["--name", words] if words else [])
    code, out, err = _run(cmd)
    return [r for r in table(out) if r.get("Id")]


def disks():
    out = []
    for p in psutil.disk_partitions(all=False):
        if "fixed" in p.opts or p.fstype:
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            out.append({"drive": p.mountpoint, "total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1), "used_pct": u.percent})
    return out


def defender():
    code, out, err = _ps("Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,AntivirusSignatureAge,QuickScanAge,"
                         "AntivirusSignatureLastUpdated | ConvertTo-Json -Compress")
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": (err or out).strip()[:200]}


def wifi():
    code, out, err = _run(["netsh", "wlan", "show", "interfaces"], 30)
    info = {}
    for k, v in re.findall(r"^\s*(SSID|State|Signal|Receive rate \(Mbps\)|Radio type)\s*:\s*(.+?)\s*$", out, re.M):
        info.setdefault(k, v)
    return info


def battery():
    b = psutil.sensors_battery()
    if b is None:
        return None
    left = None if b.power_plugged or b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else round(b.secsleft / 3600, 1)
    return {"percent": round(b.percent), "plugged": b.power_plugged, "hours_left": left}


def parse(text, ctx):
    c = text.lower().strip(" ?.!")
    if re.search(r"\b(?:apps?|programs?|software)\b.*\b(?:update|upgrade)|\b(?:updates?|upgrades?) (?:available|for my apps)|\boutdated\b", c) and \
            not re.search(r"^\s*(?:update|upgrade)\s+(?!all\b)\w", c):
        return {"op": "upgrades"}
    m = re.match(r"^\s*(?:please\s+)?(update|upgrade)\s+(?:the\s+)?(.+?)(?:\s+app)?$", c)
    if m and not re.search(r"\b(?:windows|drivers?|bios)\b", m.group(2)):
        return {"op": "upgrade", "what": m.group(2)}
    m = re.match(r"^\s*(?:please\s+)?(?:install|download and install|get me)\s+(?:the\s+)?(.+?)(?:\s+app)?$", c)
    if m and not re.search(r"\b(?:on|to|onto)\s+(?:my\s+|the\s+|a\s+)?(?:phone|mobile|tablet|android|iphone|device)\b", c) \
            and not re.search(r"\bextension\b|\bvs ?code\b|\bplugin\b", c):  # a phone is not this PC; editor extensions are not apps
        return {"op": "install", "what": m.group(1)}
    m = re.match(r"^\s*(?:please\s+)?(?:uninstall|remove the app|remove program)\s+(.+?)$", c)
    if m:
        return {"op": "uninstall", "what": m.group(1)}
    if re.search(r"\b(?:is|do i have)\b.*\binstalled\b|\bwhich version of\b", c):
        m = re.search(r"\b(?:is|do i have|version of)\s+(.+?)\s*(?:installed)?$", c)
        return {"op": "installed", "what": m.group(1).strip() if m else None}
    if re.search(r"\b(?:disk|storage|drive)\b.*\b(?:space|left|free|full)\b|\bhow much space\b", c):
        return {"op": "disks"}
    if re.search(r"\b(?:antivirus|defender|virus|windows security)\b", c):
        return {"op": "scan"} if re.search(r"\bscan\b", c) else {"op": "defender"}
    if re.search(r"\bwi-?fi\b|\binternet signal\b", c) and not re.search(r"\bqr\b|\bpassword\b", c):
        return {"op": "wifi"}
    if re.search(r"\bbattery\b", c):
        return {"op": "battery"}
    return None


def _pick(rows, what):
    w = what.lower()
    exact = [r for r in rows if r["Name"].lower() == w or r["Id"].lower() == w]
    return exact[0] if exact else (rows[0] if rows else None)


def preview(op, ctx):
    if op["op"] == "scan":
        return "A Windows Security quick scan takes a few minutes and slows the PC a little meanwhile."
    if op["op"] == "upgrade" and op["what"] in ("all", "everything", "all apps"):
        ups = upgrades()
        op["ids"] = [r["Id"] for r in ups]
        return f"Ready to update {len(ups)} apps: " + ", ".join(f"{r['Name']} {r['Version']} -> {r['Available']}" for r in ups) + \
            ". An app that installs for all users asks Windows for permission (a blue box you click)."
    rows = search(op["what"]) if op["op"] == "install" else installed(op["what"])
    r = _pick(rows, op["what"])
    if not r:
        op["missing"] = op["blocked"] = True  # nothing to confirm: the chat does not ask for a yes
        return f"No app called '{op['what']}' {'in winget' if op['op'] == 'install' else 'is installed'}; nothing will happen."
    op["id"], op["name"] = r["Id"], r["Name"]
    verb = {"install": "install", "upgrade": "update", "uninstall": "remove"}[op["op"]]
    return f"Ready to {verb} {r['Name']} ({r['Id']}" + (f", {r.get('Version')}" if r.get("Version") else "") + \
        (f" -> {r.get('Available')}" if op["op"] == "upgrade" and r.get("Available") else "") + ") with winget."


def run(op, ctx):
    k = op["op"]
    if k == "upgrades":
        ups = upgrades()
        return "All apps are up to date." if not ups else f"{len(ups)} apps can be updated: " + \
            "; ".join(f"{r['Name']} {r['Version']} -> {r['Available']}" for r in ups) + ". Say 'update all apps' or 'update <name>'."
    if k == "installed":
        rows = installed(op.get("what"))
        return "Not installed." if not rows else "; ".join(f"{r['Name']} {r['Version']}" for r in rows[:10])
    if k == "disks":
        return "; ".join(f"{d['drive']} {d['free_gb']} GB free of {d['total_gb']} GB ({d['used_pct']}% used)" for d in disks())
    if k == "defender":
        s = defender()
        if "error" in s:
            return f"Couldn't read Windows Security: {s['error']}"
        return (f"Antivirus {'on' if s.get('AntivirusEnabled') else 'OFF'}, real-time protection {'on' if s.get('RealTimeProtectionEnabled') else 'OFF'}; "
                f"virus definitions {s.get('AntivirusSignatureAge')} day(s) old; last quick scan {s.get('QuickScanAge')} day(s) ago.")
    if k == "wifi":
        w = wifi()
        return "Not connected to Wi-Fi." if not w.get("SSID") else f"Wi-Fi {w['SSID']}: signal {w.get('Signal')}, {w.get('Receive rate (Mbps)', '?')} Mbps, {w.get('Radio type', '')}."
    if k == "battery":
        b = battery()
        return "No battery (a desktop PC)." if b is None else f"Battery {b['percent']}%" + (", charging" if b["plugged"] else
                                                                                         f", about {b['hours_left']} h left" if b["hours_left"] else "") + "."
    if not op.get("confirmed"):
        return preview(op, ctx)
    if k == "scan":
        code, out, err = _ps("Start-MpScan -ScanType QuickScan; (Get-MpComputerStatus).QuickScanAge", timeout=3600)
        return "Quick scan done; " + ("no age reported." if code else f"last quick scan now {out.strip().splitlines()[-1]} day(s) ago.") + \
            (f" ({err.strip()[:200]})" if code else "")
    if op.get("missing"):
        return "Nothing to do."
    ids = op.get("ids") or [op["id"]]
    done = []
    for pid in ids:
        cmd = ["winget", {"install": "install", "upgrade": "upgrade", "uninstall": "uninstall"}[k], "--id", pid, "--exact", "--silent",
               "--accept-source-agreements", "--disable-interactivity"] + (["--accept-package-agreements"] if k != "uninstall" else [])
        code, out, err = _run(cmd, timeout=1800)
        done.append((pid, code == 0, (out + err).strip().splitlines()[-1:] or [""]))
    # check: what winget now says is installed
    after = {r["Id"]: r for r in installed()}
    lines = []
    for pid, ok, msg in done:
        there = pid in after
        good = ok and (there if k != "uninstall" else not there)
        lines.append(f"{pid}: {'done' if good else 'NOT done'}" + ("" if good else f" ({msg[0][:120]})") +
                     (f", now {after[pid].get('Version')}" if there and k != "uninstall" else ""))
    return "; ".join(lines) + "."
