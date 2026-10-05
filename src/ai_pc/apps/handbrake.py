"""HandBrake (HandBrakeCLI 1.11.2 in tools/handbrake; GitHub digest and the HandBrake Team's GPG signature checked): videos
made smaller or ready for a place with HandBrake's own official presets, picked from words: Discord (10 MB), Gmail /
email (25 MB) by the video's length, phones (Android, iPhone), YouTube (Creator), 720p / 1080p, H.265, or fast on this PC's
Intel GPU (QuickSync). Runs on the hidden desktop. Checked: as long as the original, the size limit kept, the picture
size of the preset, and the sound kept.

  'handbrake compress trip.mp4 for discord'   'handbrake trip.mp4 for gmail'   'handbrake trip.mp4 to 720p'   "handbrake trip.mp4 preset 'Fast 1080p30'"
"""
import json
import re
import subprocess
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "handbrake", "HandBrake: videos made smaller or ready for Discord/Gmail/phones/YouTube with its official presets"
EXAMPLES = ["handbrake compress trip.mp4 for discord", "handbrake trip.mp4 for gmail", "handbrake trip.mp4 to 720p"]
EXE = ROOT / "tools" / "handbrake" / "HandBrakeCLI.exe"
VIDEOS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".wmv", ".flv", ".mts", ".3gp"}
SOCIAL = {10: [(30, "Social 10 MB 30 Seconds 720p60"), (60, "Social 10 MB 1 Minute 540p60"), (120, "Social 10 MB 2 Minutes 360p60")],
          25: [(30, "Social 25 MB 30 Seconds 1080p60"), (60, "Social 25 MB 1 Minute 720p60"), (120, "Social 25 MB 2 Minutes 540p60"),
               (300, "Social 25 MB 5 Minutes 360p60")]}
WORDS = [(r"\bandroid\b|\bphone\b|\bmobile\b", "Android 1080p30"), (r"\biphone\b|\bipad\b|\bapple\b", "Apple 1080p30 Surround"),
         (r"\byoutube\b|\bcreator\b", "Creator 1080p60"), (r"\bqsv\b|\bquicksync\b|\bgpu\b|\bhardware\b|\bintel\b", "H.265 QSV 1080p"),
         (r"\bh\.?265\b|\bhevc\b", "H.265 MKV 1080p30"), (r"\b480p\b", "Fast 480p30"), (r"\b576p\b", "Fast 576p25"), (r"\b720p\b", "Fast 720p30"),
         (r"\b1080p\b", "Fast 1080p30"), (r"\b(?:4k|2160p)\b", "Fast 2160p60 4K HEVC")]
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height", "-of", "json", str(path)],
                       capture_output=True, text=True, creationflags=NOWIN)
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"seconds": float((j.get("format") or {}).get("duration") or 0), "bytes": int((j.get("format") or {}).get("size") or 0),
            "w": v.get("width"), "h": v.get("height"), "audio": any(s.get("codec_type") == "audio" for s in j.get("streams", []))}


def pick(c, seconds):
    """(preset, size limit in MB or None, why) from the words and the video's length."""
    m = re.search(r"\bpreset\s+['\"]([^'\"]+)['\"]", c)
    if m:
        return m.group(1), None, "the preset asked"
    limit = 10 if re.search(r"\bdiscord\b|\b10\s*mb\b", c) else 25 if re.search(r"\bgmail\b|\be-?mail\b|\boutlook\b|\b25\s*mb\b", c) else None
    if limit:
        fits = [p for s, p in SOCIAL[limit] if seconds <= s + 0.5]
        if not fits:
            return None, limit, f"{seconds:.0f} s is too long for {limit} MB with HandBrake's presets (they go up to {SOCIAL[limit][-1][0] // 60} minutes)"
        return fits[0], limit, f"{limit} MB for a {seconds:.0f} s video"
    for rx, preset in WORDS:
        if re.search(rx, c):
            return preset, None, "for " + re.search(rx, c).group(0)
    return "Fast 1080p30", None, "smaller, still HD"


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bhandbrake\b", c):
        return None
    f = find_file(text, ctx, VIDEOS) or (ctx.get("memo") or {}).get("video") if re.search(r"\b(?:it|this|that)\b", c) else find_file(text, ctx, VIDEOS)
    return {"op": "encode", "file": f, "words": text} if f else None


def run(op, ctx):
    if not EXE.exists():
        return "HandBrake is not in tools/handbrake."
    from ai_pc.core import hidden_desktop
    src = Path(op["file"]).resolve()
    before = probe(src)
    if not before["seconds"]:
        return f"{src.name} is not a video FFmpeg can read."
    preset, limit, why = pick(op["words"].lower(), before["seconds"])
    if not preset:
        return f"Can't: {why}. Try 'handbrake {src.name} to 720p' and send it as a link instead."
    ext = ".mkv" if "MKV" in preset else ".mp4"
    out = (Path(ctx["out"]) / "handbrake").resolve()
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{src.stem}_{re.sub(r'[^\w]+', '_', preset).strip('_')}{ext}"
    dest.unlink(missing_ok=True)
    rc, so, se, timed_out = hidden_desktop.run([str(EXE), "-i", str(src), "-o", str(dest), "--preset", preset], timeout=3600)
    if not dest.exists() and "QSV" in preset:  # this PC's Intel GPU refuses HandBrake's QSV presets (low-power H.265): the software preset instead
        why += "; Intel GPU encoding isn't available with HandBrake's preset here, so its software H.265 preset was used"
        preset = "H.265 MKV 1080p30"
        dest = out / f"{src.stem}_H_265_MKV_1080p30.mkv"
        dest.unlink(missing_ok=True)
        rc, so, se, timed_out = hidden_desktop.run([str(EXE), "-i", str(src), "-o", str(dest), "--preset", preset], timeout=3600)
    if not dest.exists():
        return f"HandBrake did not finish ({'timed out' if timed_out else f'exit {rc}'}): {(se or so).strip()[-300:]}"
    after = probe(dest)
    target_h = int(m.group(1)) if (m := re.search(r"(\d{3,4})p", preset)) else None
    checks = [(f"as long as the original ({before['seconds']:.1f} s)", abs(after["seconds"] - before["seconds"]) <= 0.25),
              (f"the picture is {after['w']}x{after['h']}" + (f" (the preset's {target_h}p or less)" if target_h else ""),
               not target_h or (after["h"] or 0) <= target_h + 8),
              ("the sound kept", after["audio"] or not before["audio"])]
    if limit:
        checks.append((f"under {limit} MB ({after['bytes'] / 1e6:.1f} MB)", after["bytes"] <= limit * 1_000_000))
    bad = [w for w, ok in checks if not ok]
    ctx.setdefault("memo", {})["video"] = str(dest)
    return (f"HandBrake made {dest} with its preset '{preset}' ({why}): {before['bytes'] / 1e6:.1f} MB -> {after['bytes'] / 1e6:.1f} MB. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
