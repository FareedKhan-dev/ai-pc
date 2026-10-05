"""Music and video with VLC: playlists made from folders (.m3u8 and VLC's .xspf, in natural order or shuffled, with the
total length measured by ffprobe), and files, folders or playlists played in VLC when asked.

  'make a playlist from D:\\Music\\Naats'   'shuffle playlist from D:\\Music'   'play D:\\Music\\naats.m3u8 in vlc'
"""

import html
import json
import random
import re
import subprocess
from pathlib import Path

NAME, LABEL = "media", "Music and video: playlists, VLC"
EXAMPLES = ["make a playlist from D:\\Music\\Naats", "play D:\\Music\\naats.m3u8 in vlc"]
MEDIA = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v"}
VLC = [Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe"), Path(r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe")]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def natural(p):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", Path(p).name)]


def duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=NOWIN,
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (ValueError, KeyError):
        return 0.0


def playlist(folder, out, shuffle=False, name=None, seed=None):
    files = sorted((p for p in Path(folder).rglob("*") if p.suffix.lower() in MEDIA), key=natural)
    if not files:
        raise ValueError(f"no music or video in {folder}")
    if shuffle:
        random.Random(seed).shuffle(files)
    durs = [duration(f) for f in files[:500]] + [0.0] * max(0, len(files) - 500)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stem = name or Path(folder).name or "playlist"
    m3u = out / f"{stem}.m3u8"
    m3u.write_text("#EXTM3U\n" + "".join(f"#EXTINF:{int(d)},{f.stem}\n{f}\n" for f, d in zip(files, durs)), encoding="utf-8")
    xspf = out / f"{stem}.xspf"
    tracks = "".join(
        f"<track><location>{html.escape(f.resolve().as_uri())}</location><title>{html.escape(f.stem)}</title>"
        f"<duration>{int(d * 1000)}</duration></track>"
        for f, d in zip(files, durs)
    )
    xspf.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><playlist version="1" xmlns="http://xspf.org/ns/0/"><title>{html.escape(stem)}</title>'
        f"<trackList>{tracks}</trackList></playlist>",
        encoding="utf-8",
    )
    return files, sum(durs), [m3u, xspf]


def vlc():
    return next((p for p in VLC if p.exists()), None)


def parse(text, ctx):
    c = text.lower()
    path = re.search(r"([a-z]:\\[^\"<>|?*\n]+?)(?:\s+in\s+vlc|\s*$|\s+(?:shuffled|on shuffle))", text, re.I)
    if re.search(r"\bplaylist\b", c) and re.search(r"\b(?:make|create|build|shuffle)\b", c) and path:
        return {"op": "playlist", "folder": path.group(1).strip(), "shuffle": bool(re.search(r"\bshuffle", c))}
    if re.match(r"^\s*play\b", c) and (path or re.search(r"\bvlc\b", c)):
        from ai_pc.apps.appschat import find_file

        target = path.group(1).strip() if path else find_file(text, ctx)
        if target:
            return {"op": "play", "target": target}
    return None


def run(op, ctx):
    if op["op"] == "playlist":
        files, total, outs = playlist(op["folder"], Path(ctx["out"]) / "playlists", op.get("shuffle"))
        back = [ln for ln in outs[0].read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
        ok = back == [str(f) for f in files]
        h, m = divmod(int(total) // 60, 60)
        return (
            (f"Playlist of {len(files)} files ({h} h {m} min" if h else f"Playlist of {len(files)} files ({m} min")
            + f"{', shuffled' if op.get('shuffle') else ''}): {outs[0]} and {outs[1]} ({'checked' if ok else 'NOT the same when read back'}). Say 'play {outs[0]} in vlc'."
        )
    exe = vlc()
    if not exe:
        return "VLC is not installed (say 'install vlc')."
    target = Path(op["target"])
    if not target.exists():
        return f"{target} does not exist."
    subprocess.Popen([str(exe), str(target)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return f"Playing {target.name} in VLC."
