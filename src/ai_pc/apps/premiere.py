"""Premiere Pro, DaVinci Resolve and Final Cut Pro by their timeline files: clips (with the part of each to use) and a
music bed laid on a sequence at the first clip's frame rate and size, written as Premiere XML (File > Import in
Premiere), FCPXML 1.10 (Final Cut Pro, DaVinci Resolve: File > Import Timeline), CMX 3600 EDL (every editor) and
OpenTimelineIO (Resolve, Avid via adapters). Each file is read back and its clips and length checked against the plan.

  "premiere timeline: intro.mp4 0-5, main.mp4 10-40, outro.mp4; music song.mp3; called 'Shop promo'"
  'resolve timeline from a.mp4, b.mp4'   'final cut timeline from clip1.mov 2-8, clip2.mov'
"""

import json
import re
import subprocess
import urllib.parse
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

NAME, LABEL = "premiere", "Premiere Pro, DaVinci Resolve, Final Cut Pro: timelines (XML, FCPXML, EDL, OTIO)"
EXAMPLES = ["premiere timeline: intro.mp4 0-5, main.mp4 10-40, outro.mp4; music song.mp3", "resolve timeline from a.mp4, b.mp4"]
MEDIA = {".mp4", ".mov", ".mkv", ".avi", ".mxf", ".m4v", ".wav", ".mp3", ".m4a", ".aac"}


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    return {
        "duration": float((j.get("format") or {}).get("duration") or 0),
        "video": bool(v),
        "audio": any(s.get("codec_type") == "audio" for s in j.get("streams", [])),
        "fps": Fraction(v["r_frame_rate"]) if v and v.get("r_frame_rate", "0/0") != "0/0" else None,
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
    }


def plan(clips, music=None):
    """[(path, in s, out s)] -> the timeline: fps, size, each clip's frames, the music bed."""
    items = []
    for path, a, b in clips:
        info = probe(path)
        a = a or 0.0
        b = min(b if b is not None else info["duration"], info["duration"])
        if b <= a:
            raise ValueError(f"{Path(path).name}: the part {a:g}-{b:g} s is empty (the clip is {info['duration']:.1f} s)")
        items.append(dict(info, path=str(Path(path).resolve()), name=Path(path).name, start=a, end=b))
    first = next((i for i in items if i["video"]), None)
    fps = first["fps"] if first and first["fps"] else Fraction(30)
    fps = min(
        (Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60)),
        key=lambda f: abs(f - fps),
    )
    t = 0
    for i in items:
        i["in_f"], i["out_f"] = round(i["start"] * fps), round(i["end"] * fps)
        i["len_f"], i["at_f"], i["file_f"] = i["out_f"] - i["in_f"], t, round(i["duration"] * fps)
        t += i["len_f"]
    m = None
    if music:
        info = probe(music)
        m = dict(
            info,
            path=str(Path(music).resolve()),
            name=Path(music).name,
            len_f=min(t, round(info["duration"] * fps)),
            file_f=round(info["duration"] * fps),
        )
    return {
        "fps": fps,
        "width": first["width"] if first else 1920,
        "height": first["height"] if first else 1080,
        "items": items,
        "music": m,
        "total_f": t,
    }


def _rate(fps):
    tb = round(float(fps))
    return f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if fps.denominator == 1001 else 'FALSE'}</ntsc></rate>"


def _pathurl(p):
    return "file://localhost/" + urllib.parse.quote(p.replace("\\", "/"), safe="/")


def xmeml(tl, title):
    """Final Cut Pro 7 XML, which Premiere Pro imports."""
    fps, files, vid, aud = tl["fps"], {}, [], []

    def file_el(i):
        if i["path"] in files:
            return f'<file id="{files[i["path"]]}"/>'
        fid = files[i["path"]] = f"file-{len(files) + 1}"
        media = (
            "<video><samplecharacteristics><width>{}</width><height>{}</height></samplecharacteristics></video>".format(i["width"], i["height"])
            if i["video"]
            else ""
        ) + ("<audio><channelcount>2</channelcount></audio>" if i["audio"] else "")
        return (
            f'<file id="{fid}"><name>{escape(i["name"])}</name><pathurl>{escape(_pathurl(i["path"]))}</pathurl>{_rate(fps)}<duration>{i["file_f"]}</duration>'
            f"<media>{media}</media></file>"
        )

    for n, i in enumerate(tl["items"], 1):
        body = (
            f"<name>{escape(i['name'])}</name><duration>{i['file_f']}</duration>{_rate(fps)}<start>{i['at_f']}</start><end>{i['at_f'] + i['len_f']}</end>"
            f"<in>{i['in_f']}</in><out>{i['out_f']}</out>"
        )
        if i["video"]:
            vid.append(f'<clipitem id="clipitem-v{n}">{body}{file_el(i)}</clipitem>')
        if i["audio"]:
            aud.append(
                f'<clipitem id="clipitem-a{n}">{body}{file_el(i)}<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>'
            )
    m = tl["music"]
    music = ""
    if m:
        music = (
            f'<track><clipitem id="clipitem-music"><name>{escape(m["name"])}</name><duration>{m["file_f"]}</duration>{_rate(fps)}<start>0</start>'
            f"<end>{m['len_f']}</end><in>0</in><out>{m['len_f']}</out>{file_el(dict(m, video=False, audio=True))}</clipitem></track>"
        )
    fmt = (
        f"<format><samplecharacteristics>{_rate(fps)}<width>{tl['width']}</width><height>{tl['height']}</height>"
        "<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="sequence-1">'
        f"<name>{escape(title)}</name><duration>{tl['total_f']}</duration>{_rate(fps)}<media><video>{fmt}<track>{''.join(vid)}</track></video>"
        f"<audio><track>{''.join(aud)}</track>{music}</audio></media></sequence></xmeml>"
    )


def _t(frames, fps):
    """A time in FCPXML's rational seconds, on the frame grid."""
    v = Fraction(frames) / fps
    return f"{v.numerator}/{v.denominator}s" if v.denominator != 1 else f"{v.numerator}s"


def fcpxml(tl, title):
    fps = tl["fps"]
    fd = 1 / fps
    res = [f'<format id="r1" frameDuration="{fd.numerator}/{fd.denominator}s" width="{tl["width"]}" height="{tl["height"]}"/>']
    ids = {}
    for i in tl["items"] + ([tl["music"]] if tl["music"] else []):
        if i["path"] not in ids:
            ids[i["path"]] = f"r{len(ids) + 2}"
            src = Path(i["path"]).resolve().as_uri()
            res.append(
                f'<asset id="{ids[i["path"]]}" name="{escape(Path(i["name"]).stem)}" start="0s" duration="{_t(i["file_f"], fps)}" '
                f'hasVideo="{int(i["video"])}" hasAudio="{int(i["audio"])}"'
                + (' format="r1"' if i["video"] else "")
                + f'><media-rep kind="original-media" src="{escape(src)}"/></asset>'
            )
    spine = []
    for n, i in enumerate(tl["items"]):
        inner = ""
        if n == 0 and tl["music"]:
            m = tl["music"]
            inner = (
                f'<asset-clip ref="{ids[m["path"]]}" lane="-1" offset="{_t(i["in_f"], fps)}" name="{escape(Path(m["name"]).stem)}" start="0s" '
                f'duration="{_t(m["len_f"], fps)}" audioRole="music"/>'
            )
        spine.append(
            f'<asset-clip ref="{ids[i["path"]]}" offset="{_t(i["at_f"], fps)}" name="{escape(Path(i["name"]).stem)}" start="{_t(i["in_f"], fps)}" '
            f'duration="{_t(i["len_f"], fps)}"' + (' format="r1"' if i["video"] else "") + ' tcFormat="NDF">' + inner + "</asset-clip>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10"><resources>' + "".join(res) + "</resources>"
        f'<library><event name="AI PC"><project name="{escape(title)}"><sequence format="r1" duration="{_t(tl["total_f"], fps)}" tcStart="0s" tcFormat="NDF">'
        f"<spine>{''.join(spine)}</spine></sequence></project></event></library></fcpxml>"
    )


def _tc(frames, tb):
    s, f = divmod(frames, tb)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def edl(tl, title):
    tb = round(float(tl["fps"]))
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for n, i in enumerate(tl["items"], 1):
        lines += [
            f"{n:03d}  AX       {'V' if i['video'] else 'A'}     C        {_tc(i['in_f'], tb)} {_tc(i['out_f'], tb)} {_tc(i['at_f'], tb)} "
            f"{_tc(i['at_f'] + i['len_f'], tb)}",
            f"* FROM CLIP NAME: {i['name']}",
            "",
        ]
    return "\n".join(lines)


def otio(tl, title):
    rate = float(tl["fps"])

    def clip(i, frames_in, frames_len):
        return {
            "OTIO_SCHEMA": "Clip.1",
            "name": i["name"],
            "metadata": {},
            "effects": [],
            "markers": [],
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "target_url": Path(i["path"]).resolve().as_uri(),
                "metadata": {},
                "available_range": {
                    "OTIO_SCHEMA": "TimeRange.1",
                    "start_time": {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": 0.0},
                    "duration": {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": float(i["file_f"])},
                },
            },
            "source_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": float(frames_in)},
                "duration": {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": float(frames_len)},
            },
        }

    tracks = [
        {
            "OTIO_SCHEMA": "Track.1",
            "name": "V1",
            "kind": "Video",
            "metadata": {},
            "effects": [],
            "markers": [],
            "source_range": None,
            "children": [clip(i, i["in_f"], i["len_f"]) for i in tl["items"] if i["video"]],
        }
    ]
    if tl["music"]:
        tracks.append(
            {
                "OTIO_SCHEMA": "Track.1",
                "name": "Music",
                "kind": "Audio",
                "metadata": {},
                "effects": [],
                "markers": [],
                "source_range": None,
                "children": [clip(tl["music"], 0, tl["music"]["len_f"])],
            }
        )
    return json.dumps(
        {
            "OTIO_SCHEMA": "Timeline.1",
            "name": title,
            "metadata": {},
            "global_start_time": None,
            "tracks": {
                "OTIO_SCHEMA": "Stack.1",
                "name": "tracks",
                "metadata": {},
                "effects": [],
                "markers": [],
                "source_range": None,
                "children": tracks,
            },
        },
        indent=1,
    )


def make(clips, out, title="AI PC edit", music=None):
    tl = plan(clips, music)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", title)
    files = {"premiere": out / f"{stem}.premiere.xml", "fcpxml": out / f"{stem}.fcpxml", "edl": out / f"{stem}.edl", "otio": out / f"{stem}.otio"}
    files["premiere"].write_text(xmeml(tl, title), encoding="utf-8")
    files["fcpxml"].write_text(fcpxml(tl, title), encoding="utf-8")
    files["edl"].write_text(edl(tl, title), encoding="utf-8")
    files["otio"].write_text(otio(tl, title), encoding="utf-8")
    return tl, files


def check(tl, files):
    out = []
    x = ET.parse(files["premiere"]).getroot()
    vclips = x.findall(".//video/track/clipitem")
    out.append(
        (
            "Premiere XML: every clip, ending at the sequence's length",
            len(vclips) == sum(1 for i in tl["items"] if i["video"]) and max(int(c.findtext("end")) for c in vclips) == tl["total_f"],
        )
    )
    f = ET.parse(files["fcpxml"]).getroot()
    fd = 1 / tl["fps"]
    spine = f.findall(".//spine/asset-clip")
    times = [Fraction(c.get(k).rstrip("s")) for c in f.iter("asset-clip") for k in ("offset", "start", "duration")]
    out.append(("FCPXML: every clip, every time on the frame grid", len(spine) == len(tl["items"]) and all((t / fd).denominator == 1 for t in times)))
    e = [ln for ln in files["edl"].read_text(encoding="utf-8").splitlines() if re.match(r"^\d{3}\s", ln)]
    out.append(("EDL: one event per clip", len(e) == len(tl["items"])))
    o = json.loads(files["otio"].read_text(encoding="utf-8"))
    total = sum(c["source_range"]["duration"]["value"] for c in o["tracks"]["children"][0]["children"])
    out.append(("OTIO: the video track's length is the sequence's", total == sum(i["len_f"] for i in tl["items"] if i["video"])))
    return out


def _secs(s):
    if s is None:
        return None
    if ":" in s:
        p = [float(x) for x in s.split(":")]
        return sum(v * 60**k for k, v in enumerate(reversed(p)))
    return float(s)


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\b(?:premiere|resolve|davinci|final cut|fcp|fcpxml|edl|otio)\b", c) or not re.search(
        r"\btimeline|\bsequence|\bexport|\bedit\b", c
    ):
        return None
    title = re.search(r"\bcalled\s+['\"]([^'\"]+)['\"]", text, re.I)
    body = re.sub(r"\bcalled\s+['\"][^'\"]+['\"]", "", text, flags=re.I)
    body = re.sub(r"^.*?(?:timeline|sequence|export)\s*(?:for\s+\w+(?:\s+\w+)?\s*)?(?::|from|of)\s*", "", body, flags=re.I | re.S)
    music = None
    m = re.search(r"\bmusic\s*:?\s*(\S+\.(?:mp3|wav|m4a|aac))", body, re.I)
    if m:
        music = find_file(m.group(1), ctx, MEDIA) or (m.group(1) if Path(m.group(1)).exists() else None)
        body = body[: m.start()] + body[m.end() :]
    clips = []
    for part in re.split(r"[,;]|\band\b", body):
        mm = re.match(r"\s*(\S+\.(?:mp4|mov|mkv|avi|mxf|m4v))(?:\s+(\d[\d:.]*)\s*-\s*(\d[\d:.]*))?", part.strip(), re.I)
        if mm:
            path = find_file(mm.group(1), ctx, MEDIA) or (mm.group(1) if Path(mm.group(1)).exists() else None)
            if path:
                clips.append((path, _secs(mm.group(2)), _secs(mm.group(3))))
    if not clips:
        return None
    return {"op": "timeline", "clips": clips, "music": music, "title": title.group(1) if title else "AI PC edit"}


def run(op, ctx):
    tl, files = make(op["clips"], Path(ctx["out"]) / "timelines", op["title"], op.get("music"))
    checks = check(tl, files)
    bad = [w for w, ok in checks if not ok]
    secs = tl["total_f"] / float(tl["fps"])
    return (
        f"Timeline '{op['title']}': {len(tl['items'])} clips, {secs:.1f} s at {float(tl['fps']):.3g} fps, {tl['width']}x{tl['height']}"
        + (f", music {tl['music']['name']}" if tl["music"] else "")
        + ". Premiere Pro: File > Import "
        + files["premiere"].name
        + "; DaVinci Resolve or Final Cut Pro: File > Import Timeline "
        + files["fcpxml"].name
        + "; any editor: "
        + files["edl"].name
        + "; OTIO: "
        + files["otio"].name
        + f" (in {files['edl'].parent}). "
        + ("Checked: " + "; ".join(w for w, _ in checks) if not bad else "NOT right: " + "; ".join(bad))
        + "."
    )
