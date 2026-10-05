"""Shotcut (26.9.27 portable in tools/shotcut, hash-checked) by its own project files: a timeline from words (the same words
as the Premiere program: 'intro.mp4 0-5, main.mp4 10-40; music song.mp3', plus a title over the start) written as a
Shotcut .mlt project, then rendered to MP4 by Shotcut's engine (melt) on the hidden desktop, with no window. Open the
.mlt in Shotcut to keep editing. Checked: the video is as long as the cuts, has sound, every cut shows the right part of
its clip (a frame from the middle of each cut matches the source at that moment), and the title is readable (Windows OCR).

  "shotcut timeline: intro.mp4 0-5, main.mp4 10-40; music song.mp3; title 'My Trip'"
"""

import html
import re
import subprocess
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "shotcut", "Shotcut: timelines from words as .mlt projects, rendered to MP4 by its engine (cuts, music, title)"
EXAMPLES = ["shotcut timeline: intro.mp4 0-5, main.mp4 10-40; music song.mp3; title 'My Trip'"]
HOME = ROOT / "tools" / "shotcut"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def melt():
    hits = sorted(HOME.rglob("melt.exe")) if HOME.exists() else []
    return hits[0] if hits else None


def mlt(tl, title_text=None, project="AI PC edit"):
    """A Shotcut-compatible MLT project: V1 with the cuts, A1 with the music (faded out), a title over the first 3 seconds."""
    fps = tl["fps"]
    e = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    total = tl["total_f"]
    x = [
        '<?xml version="1.0" standalone="no"?>',
        f'<mlt LC_NUMERIC="C" version="7.0.0" title="{e(project)}" producer="tractor0">',  # the timeline is what melt plays (main_bin is only the bin)
        f'  <profile description="{tl["width"]}x{tl["height"]} {float(fps):.2f} fps" width="{tl["width"]}" height="{tl["height"]}" progressive="1" '
        f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{tl["width"]}" display_aspect_den="{tl["height"]}" '
        f'frame_rate_num="{fps.numerator}" frame_rate_den="{fps.denominator}" colorspace="709"/>',
        '  <playlist id="main_bin"><property name="xml_retain">1</property></playlist>',
    ]
    for i, it in enumerate(tl["items"]):
        x.append(
            f'  <producer id="clip{i}" in="0" out="{it["file_f"] - 1}"><property name="resource">{e(it["path"])}</property>'
            f'<property name="mlt_service">avformat</property><property name="shotcut:caption">{e(it["name"])}</property></producer>'
        )
    x.append('  <playlist id="playlist0"><property name="shotcut:video">1</property><property name="shotcut:name">V1</property>')
    for i, it in enumerate(tl["items"]):
        x.append(f'    <entry producer="clip{i}" in="{it["in_f"]}" out="{it["out_f"] - 1}"/>')
    x.append("  </playlist>")
    tracks = ['    <track producer="playlist0"/>']
    trans = []
    if tl.get("music"):
        m = tl["music"]
        fade = min(round(2 * fps), m["len_f"] // 3)
        x.append(
            f'  <producer id="music" in="0" out="{m["file_f"] - 1}"><property name="resource">{e(m["path"])}</property>'
            f'<property name="mlt_service">avformat</property><property name="shotcut:caption">{e(m["name"])}</property>'
            f'<filter id="fadeout" in="{m["len_f"] - fade}" out="{m["len_f"] - 1}"><property name="mlt_service">volume</property>'
            f'<property name="level">0=0;{fade - 1}=-60</property><property name="shotcut:filter">fadeOutVolume</property></filter></producer>'
        )
        x.append(
            '  <playlist id="playlist1"><property name="shotcut:audio">1</property><property name="shotcut:name">A1</property>'
            f'<entry producer="music" in="0" out="{m["len_f"] - 1}"/></playlist>'
        )
        tracks.append('    <track producer="playlist1" hide="video"/>')
        trans.append(
            '    <transition id="mix1"><property name="a_track">0</property><property name="b_track">1</property>'
            '<property name="mlt_service">mix</property><property name="always_active">1</property><property name="sum">1</property></transition>'
        )
    x.append(f'  <tractor id="tractor0" title="{e(project)}" in="0" out="{total - 1}"><property name="shotcut">1</property>')
    x += tracks + trans
    if title_text:
        x.append(
            f'    <filter id="title" in="0" out="{min(total, round(3 * fps)) - 1}"><property name="mlt_service">dynamictext</property>'
            f'<property name="argument">{e(title_text)}</property><property name="geometry">0 {tl["height"] * 0.38:.0f} {tl["width"]} {tl["height"] * 0.24:.0f} 1</property>'
            '<property name="family">Arial</property><property name="size">' + str(round(tl["height"] * 0.12)) + "</property>"
            '<property name="weight">750</property><property name="fgcolour">#ffffffff</property><property name="bgcolour">#99000000</property>'
            '<property name="olcolour">#ff000000</property><property name="outline">2</property><property name="halign">center</property>'
            '<property name="valign">middle</property><property name="shotcut:filter">dynamicText</property></filter>'
        )
    x += ["  </tractor>", "</mlt>"]
    return "\n".join(x)


def frame(path, seconds, png):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{seconds:.3f}", "-i", str(path), "-frames:v", "1", str(png)],
        capture_output=True,
        creationflags=NOWIN,
    )
    return Path(png).exists()


def check(tl, video, work, title_text):
    import numpy as np
    from PIL import Image

    from ai_pc.apps import premiere

    info = premiere.probe(video)
    want = tl["total_f"] / float(tl["fps"])
    checks = [
        (f"the video is {want:.1f} s, as long as the cuts", abs(info["duration"] - want) <= 0.15),
        ("it has sound", info["audio"]),
        (f"{tl['width']}x{tl['height']}", (info["width"], info["height"]) == (tl["width"], tl["height"])),
    ]
    diffs = []
    fps = float(tl["fps"])
    title_end = 3.0 if title_text else 0.0
    for k, it in enumerate(tl["items"]):
        if not it["video"]:
            continue
        offset = it["len_f"] * 0.75 / fps  # three quarters into the cut, after the title (shown over the first 3 s) where possible
        if (it["at_f"] / fps + offset) < title_end:
            offset = min((it["len_f"] - 2) / fps, title_end - it["at_f"] / fps + 0.2)
        a = work / f"cut{k}_render.png"
        if not frame(video, it["at_f"] / fps + offset, a):
            continue
        x = np.asarray(Image.open(a).convert("L").resize((320, 180)), dtype=np.float64).ravel()

        def corr(t, tag):
            b = work / f"cut{k}_{tag}.png"
            if not (0 <= t <= it["duration"] and frame(it["path"], t, b)):
                return None
            y = np.asarray(Image.open(b).convert("L").resize((320, 180)), dtype=np.float64).ravel()
            return float(np.corrcoef(x, y)[0, 1])

        # correlation, not raw difference: melt's colour conversion shifts colours a little but not the picture
        right = max(c for c in (corr(it["start"] + offset + s / fps, f"src{s}") for s in (-1, 0, 1)) if c is not None)
        decoys = [c for c in (corr(it["start"] + offset + d, f"decoy{d}") for d in (-1.0, 1.0)) if c is not None]
        diffs.append((right, max(decoys) if decoys else None))
    checks.append(
        (
            "every cut shows the right moment of its clip ("
            + ", ".join(f"match {r:.3f}" + (f" vs {d:.3f} a second off" if d is not None else "") for r, d in diffs)
            + ")",
            bool(diffs) and all(r >= 0.9 and (d is None or r >= d - 0.002) for r, d in diffs),
        )
    )
    if title_text:
        shot = work / "title_frame.png"
        frame(video, 1.0, shot)
        try:
            from ai_pc.apps import ocr

            seen = re.sub(r"\s+", " ", ocr.read_picture(shot, work=work)["text"].lower())
        except Exception:  # noqa: BLE001
            seen = ""
        checks.append(
            (f"the title '{title_text}' is readable on screen (Windows OCR)", all(w in seen for w in re.findall(r"[a-z0-9]+", title_text.lower())))
        )
    return checks


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bshotcut\b|\bkdenlive\b|\bmlt\b", c):
        return None
    from ai_pc.apps import premiere

    title = re.search(r"\btitle\s+['\"]([^'\"]+)['\"]", text, re.I)
    body = re.sub(r";?\s*\btitle\s+['\"][^'\"]+['\"]", "", text, flags=re.I)
    op = premiere.parse(re.sub(r"\b(?:shotcut|kdenlive|mlt)\b", "premiere", body, flags=re.I), ctx)
    if not op:
        return None
    return dict(op, op="render", overlay=title.group(1) if title else None)


def run(op, ctx):
    if not melt():
        return "Shotcut is not in tools/shotcut."
    from ai_pc.apps import premiere
    from ai_pc.core import hidden_desktop

    try:
        tl = premiere.plan(op["clips"], op.get("music"))
    except ValueError as e:
        return f"Couldn't make the timeline: {e}."
    out = (Path(ctx["out"]) / "shotcut").resolve()
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", op.get("overlay") or op.get("title") or "edit").strip("_") or "edit"
    project, video = out / f"{stem}.mlt", out / f"{stem}.mp4"
    project.write_text(mlt(tl, op.get("overlay"), op.get("title") or stem), encoding="utf-8")
    video.unlink(missing_ok=True)
    rc, so, se, timed_out = hidden_desktop.run(
        [
            str(melt()),
            str(project),
            "-silent",
            "-consumer",
            f"avformat:{video}",
            "vcodec=libx264",
            "crf=21",
            "preset=veryfast",
            "acodec=aac",
            "ab=160k",
            "real_time=0",
        ],
        timeout=1800,
    )
    if not video.exists():
        return f"Shotcut's engine did not render: {(se or so)[-400:]}"
    work = out / "_check"
    work.mkdir(exist_ok=True)
    checks = check(tl, video, work, op.get("overlay"))
    bad = [w for w, ok in checks if not ok]
    secs = tl["total_f"] / float(tl["fps"])
    ctx.setdefault("memo", {})["video"] = str(video)
    return (
        f"Shotcut project {project} (open it in Shotcut to keep editing) rendered by Shotcut's engine to {video} ({secs:.1f} s, {len(tl['items'])} cuts"
        + (", music faded out" if tl.get("music") else "")
        + (f", title '{op['overlay']}'" if op.get("overlay") else "")
        + "). "
        + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ".")
    )
