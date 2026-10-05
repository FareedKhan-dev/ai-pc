"""What a video or sound file is, measured with FFprobe and FFmpeg (no model):

p = probe(path)        container, length, size, bitrate; the picture as it is shown (rotation and odd pixel shapes
                       applied), frame rate and whether it varies, bit depth, colour (HDR), interlacing; the sound
                       tracks; subtitles; whether an MP4 starts playing before it has fully downloaded
describe(p)            the same in plain words
keyframes(path, t)     where the picture can be cut without re-encoding, near a time
bars(p)                black bars around the picture (w, h, x, y), measured at three places
interlaced(path)       True when the frames are interlaced (combing on movement)
decodes(path, ...)     errors met when the file is played through (empty = it plays)
"""

import json
import os
import re
import struct
from collections import Counter
from pathlib import Path

from ai_pc.sound.measure import run

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr", ".aiff", ".aif", ".mka"}
VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".wmv",
    ".flv",
    ".m4v",
    ".3gp",
    ".ts",
    ".mts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".vob",
    ".gif",
    ".ogv",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic"}
CODEC_WORDS = {
    "h264": "H.264",
    "hevc": "HEVC (H.265)",
    "av1": "AV1",
    "vp9": "VP9",
    "vp8": "VP8",
    "mpeg4": "MPEG-4 (Xvid)",
    "msmpeg4v3": "DivX",
    "mpeg2video": "MPEG-2",
    "mpeg1video": "MPEG-1",
    "prores": "ProRes",
    "dnxhd": "DNxHD",
    "mjpeg": "Motion JPEG",
    "wmv3": "Windows Media",
    "vc1": "Windows Media (VC-1)",
    "wmv2": "Windows Media",
    "gif": "GIF",
    "theora": "Theora",
    "ffv1": "FFV1 (lossless)",
    "rawvideo": "uncompressed",
    "aac": "AAC",
    "mp3": "MP3",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "ac3": "Dolby Digital (AC-3)",
    "eac3": "Dolby Digital Plus",
    "dts": "DTS",
    "truehd": "Dolby TrueHD",
    "flac": "FLAC",
    "alac": "Apple Lossless",
    "wmav2": "Windows Media Audio",
    "wmapro": "Windows Media Audio",
    "amr_nb": "AMR (phone recording)",
    "amr_wb": "AMR-WB",
    "mp2": "MP2",
    "pcm_s16le": "uncompressed (PCM)",
    "pcm_s24le": "uncompressed (PCM 24-bit)",
    "pcm_f32le": "uncompressed (PCM float)",
    "pcm_s16be": "uncompressed (PCM)",
    "mov_text": "text",
    "subrip": "SRT",
    "ass": "ASS",
    "hdmv_pgs_subtitle": "picture (PGS)",
    "dvd_subtitle": "picture (DVD)",
    "webvtt": "WebVTT",
}
TEXT_SUBS = {"mov_text", "subrip", "ass", "ssa", "webvtt", "text"}


class MediaError(ValueError):
    pass


def _ratio(s):
    try:
        n, d = (str(s or "0/1").split("/") + ["1"])[:2]
        return float(n) / float(d) if float(d) else 0.0
    except ValueError:
        return 0.0


def _container(fmt, path, v):
    ext = Path(path).suffix.lower().lstrip(".")
    f = fmt or ""
    if "mp4" in f or "mov" in f:
        return ext if ext in ("mp4", "mov", "m4a", "m4v", "3gp") else "mp4"
    if "matroska" in f or "webm" in f:
        return "webm" if ext == "webm" else "mkv"
    for name in ("avi", "gif", "mp3", "wav", "flac", "ogg", "flv", "mpegts", "aac", "asf", "amr", "aiff"):
        if name in f:
            return {"mpegts": "ts", "asf": "wmv" if v else "wma"}.get(name, name)
    if "image2" in f or f.endswith("_pipe"):
        return "image"
    return ext or f


def probe(path):
    """Everything the converter needs to know about a file; raises MediaError when it is not a media file."""
    path = Path(path).resolve()  # FFmpeg runs in the chat's folder, so every path is kept whole
    if not path.is_file():
        raise MediaError(f"{path.name} is not there")
    code, out, err = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60)
    if code:
        raise MediaError(f"cannot read {path.name}: {err.strip()[:160] or 'not a video or sound file'}")
    d = json.loads(out or b"{}")
    fmt = d.get("format") or {}
    streams = d.get("streams") or []
    vs = [s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    aus = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    if not vs and not aus:
        raise MediaError(f"{path.name} has no picture and no sound")
    v = vs[0] if vs else None
    dur = float(fmt.get("duration") or (v or {}).get("duration") or (aus[0] if aus else {}).get("duration") or 0)
    size = int(fmt.get("size") or path.stat().st_size)
    video = None
    if v:
        rot = 0
        for sd in v.get("side_data_list") or []:
            if "rotation" in sd:
                rot = int(round(float(sd["rotation"])))
        if not rot and (v.get("tags") or {}).get("rotate"):
            rot = -int((v.get("tags") or {})["rotate"])  # the old tag turns the other way round from the display matrix
        rot = ((rot % 360) + 360) % 360
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        sar = _ratio((v.get("sample_aspect_ratio") or "1:1").replace(":", "/")) or 1.0
        dw = int(round(w * sar)) if abs(sar - 1) > 0.01 else w
        if rot in (90, 270):
            dw, h_ = h, dw
        else:
            h_ = h
        pix = v.get("pix_fmt") or ""
        avg, rfr = _ratio(v.get("avg_frame_rate")), _ratio(v.get("r_frame_rate"))
        fps = avg if 0 < avg < 1000 else rfr
        image = (fmt.get("format_name") or "").startswith("image2") or (v.get("codec_name") in ("png", "mjpeg", "bmp", "webp", "tiff") and dur < 0.1)
        video = {
            "codec": v.get("codec_name"),
            "profile": v.get("profile"),
            "level": v.get("level"),
            "tag": v.get("codec_tag_string"),
            "w": dw,
            "h": h_,
            "coded_w": w,
            "coded_h": h,
            "rotation": rot,
            "sar": round(sar, 4),
            "pix_fmt": pix,
            "bits": 12 if "12" in pix else 10 if ("10" in pix or "p010" in pix) else 8,
            "chroma": "444"
            if "444" in pix
            else "422"
            if "422" in pix
            else "rgb"
            if ("rgb" in pix or "bgr" in pix or pix.startswith("gbr"))
            else "420",
            "fps": round(fps, 3),
            "r_fps": round(rfr, 3),
            "vfr": bool(avg and rfr and abs(rfr - avg) / max(rfr, avg) > 0.02 and not image),
            "hdr": v.get("color_transfer") in ("smpte2084", "arib-std-b67"),
            "transfer": v.get("color_transfer"),
            "interlaced": {"progressive": False, "tt": True, "bb": True, "tb": True, "bt": True}.get(v.get("field_order")),
            "frames": int(v["nb_frames"]) if str(v.get("nb_frames") or "").isdigit() else None,
            "bitrate": int(v.get("bit_rate") or 0),
            "image": bool(image),
        }
    tracks = [
        {
            "codec": a.get("codec_name"),
            "sr": int(a.get("sample_rate") or 0),
            "channels": int(a.get("channels") or 0),
            "layout": a.get("channel_layout"),
            "bitrate": int(a.get("bit_rate") or 0),
            "lang": (a.get("tags") or {}).get("language"),
        }
        for a in aus
    ]
    p = {
        "path": str(path),
        "name": path.name,
        "size": size,
        "duration": dur,
        "format": fmt.get("format_name", ""),
        "container": _container(fmt.get("format_name"), path, v),
        "bitrate": int(fmt.get("bit_rate") or (size * 8 / dur if dur else 0)),
        "video": video,
        "audio": tracks[0] if tracks else None,
        "audio_tracks": tracks,
        "subs": [
            {"codec": s.get("codec_name"), "lang": (s.get("tags") or {}).get("language"), "text": s.get("codec_name") in TEXT_SUBS} for s in subs
        ],
        "faststart": faststart(path) if path.suffix.lower() in (".mp4", ".mov", ".m4a", ".m4v", ".3gp") else None,
    }
    return p


def faststart(path):
    """True when the index (moov) comes before the media (mdat) of an MP4/MOV: it starts playing while downloading."""
    try:
        total = os.path.getsize(path)
        with open(path, "rb") as f:
            pos = 0
            for _ in range(64):
                if pos + 8 > total:
                    return None
                f.seek(pos)
                size, typ = struct.unpack(">I4s", f.read(8))
                if size == 1:
                    size = struct.unpack(">Q", f.read(8))[0]
                elif size == 0:
                    size = total - pos
                if typ == b"moov":
                    return True
                if typ == b"mdat":
                    return False
                if size < 8:
                    return None
                pos += size
    except (OSError, struct.error):
        return None
    return None


def mmss(t):
    t = max(0.0, float(t or 0))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{int(h)}:{int(m):02d}:{int(s):02d}"
    return f"{int(m)}:{s:04.1f}" if t < 60 else f"{int(m)}:{int(s):02d}"


def human(n):
    """Sizes the way Windows Explorer shows them (1 KB = 1024 bytes)."""
    n = float(n or 0)
    for u in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "bytes" else f"{n:.1f} {u}" if n < 100 else f"{n:.0f} {u}"
        n /= 1024


def channels_words(n):
    return {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(n, f"{n}-channel")


def describe(p):
    """'1:22, 1920x1080 at 60 fps (HEVC (H.265)), AAC stereo sound, 96 MB (9.8 Mbps)'."""
    v, a = p.get("video"), p.get("audio")
    bits = [mmss(p["duration"])] if not (v and v.get("image")) else []
    if v:
        extra = [CODEC_WORDS.get(v["codec"], v["codec"] or "?")]
        if v["bits"] > 8:
            extra.append(f"{v['bits']}-bit")
        still = v["codec"] in ("gif", "webp", "png", "mjpeg", "apng")
        if v["chroma"] in ("422", "444", "rgb") and not still:
            extra.append(f"{v['chroma']} colour" if v["chroma"] != "rgb" else "RGB colour")
        if v["hdr"]:
            extra.append("HDR")
        if v["vfr"] and not still:
            extra.append("frame rate varies")
        if v["interlaced"]:
            extra.append("interlaced")
        if v["rotation"]:
            extra.append("stored sideways with a turn flag" if v["rotation"] in (90, 270) else "stored upside down with a turn flag")
        fps = "" if v.get("image") else f" at {v['fps']:g} fps"
        bits.append(f"{v['w']}x{v['h']}{fps} ({', '.join(extra)})")
    else:
        bits.append("sound only")
    if a:
        more = f" + {len(p['audio_tracks']) - 1} more sound track{'s' if len(p['audio_tracks']) > 2 else ''}" if len(p["audio_tracks"]) > 1 else ""
        bits.append(f"{CODEC_WORDS.get(a['codec'], a['codec'])} {channels_words(a['channels'])} sound{more}")
    elif v and not v.get("image"):
        bits.append("no sound")
    if p.get("subs"):
        bits.append(f"{len(p['subs'])} subtitle track{'s' if len(p['subs']) > 1 else ''}")
    br = p.get("bitrate") or 0
    rate = (
        (f" ({br / 1e6:.1f} Mbps)" if br >= 1e6 else f" ({br / 1e3:.0f} kbps)") if br and p["duration"] > 0.5 and not (v and v.get("image")) else ""
    )
    bits.append(f"{human(p['size'])}{rate}")
    return f"{p['name']} ({p['container'].upper()}): " + ", ".join(bits)


def keyframes(path, near=None, span=20.0):
    """Keyframe times (seconds); only those within `span` seconds of `near` when it is given (fast on long files)."""
    args = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0"]
    if near is not None:
        args += ["-read_intervals", f"{max(0.0, near - span):.3f}%{near + 1.0:.3f}"]
    code, out, _ = run(args + [str(path)], timeout=120)
    kf = []
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 2 and "K" in parts[1] and parts[0] not in ("", "N/A"):
            kf.append(float(parts[0]))
    return sorted(set(kf))


def bars(p, limit=24):
    """Black bars around the picture: (w, h, x, y) to crop to, or None. The widest picture found at three places wins,
    so a dark scene is never mistaken for a bar."""
    v = p.get("video")
    if not v or v.get("image"):
        return None
    dur = p["duration"] or 0
    found = []
    for frac in (0.2, 0.5, 0.8):
        t = max(0.0, dur * frac - 1)
        code, _, err = run(
            [
                "ffmpeg",
                "-hide_banner",
                "-ss",
                f"{t:.2f}",
                "-i",
                p["path"],
                "-t",
                "2",
                "-vf",
                f"cropdetect=limit={limit}:round=2:reset=0",
                "-an",
                "-f",
                "null",
                "-",
            ],
            timeout=120,
        )
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
        if m:
            found.append(tuple(int(x) for x in m[-1]))
    if not found:
        return None
    w = max(f[0] for f in found)
    h = max(f[1] for f in found)
    x = min(f[2] for f in found if f[0] == w)
    y = min(f[3] for f in found if f[1] == h)
    if w >= v["w"] * 0.98 and h >= v["h"] * 0.98:
        return None
    return (w - w % 2, h - h % 2, x, y)


def interlaced(path, frames=300):
    code, _, err = run(["ffmpeg", "-hide_banner", "-i", str(path), "-frames:v", str(frames), "-vf", "idet", "-an", "-f", "null", "-"], timeout=120)
    m = re.search(r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)", err)
    if not m:
        return False
    tff, bff, prog = (int(x) for x in m.groups())
    return tff + bff > 2 * max(prog, 1)


BENIGN = re.compile(
    r"Trailing garbage|deprecated pixel format|Last message repeated|non monotonically increasing dts|"
    r"Application provided invalid, non monotonically|Could not find codec parameters|Estimating duration",
    re.I,
)


def decodes(path, duration=None, pixels=None, budget_s=45.0):
    """Errors met when the file is played through: the whole file when that is quick, else its start, middle and end."""
    p = Path(path)
    dur = float(duration or 0)
    work = dur * (pixels or 1280 * 720) / (1280 * 720)  # seconds of 720p to decode
    spans = [(None, None)] if work < budget_s * 8 else [(0.0, 4.0), (max(0.0, dur / 2 - 2), 4.0), (max(0.0, dur - 4.5), 4.0)]
    errs = []
    for s, t in spans:
        args = (
            ["ffmpeg", "-hide_banner", "-v", "error"]
            + (["-ss", f"{s:.2f}"] if s else [])
            + ["-i", str(p)]
            + (["-t", f"{t:.2f}"] if t else [])
            + ["-f", "null", "-"]
        )
        code, _, err = run(args, timeout=max(120, int(budget_s * 4)))
        lines = [x for x in err.splitlines() if x.strip() and not BENIGN.search(x)]
        if code:
            lines.append(f"stopped with code {code}")
        errs += lines[:5]
    return errs


def mostly(values):
    return Counter(values).most_common(1)[0][0] if values else None
