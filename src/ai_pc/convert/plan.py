"""A chain of changes turned into FFmpeg work, always made from the original files (one encode, so nothing is
compressed twice), and nothing re-encoded that can be copied.

  pieces, speed = timeline(chain, sources)     the output as pieces of the sources, and one playback speed for all
  S = settings(chain)                          what was asked, settled (a later change of the same kind wins)
  job = build(S, pieces, speed, sources, folder, caps, over, name)
      -> {"kind": "copy" | "cutcopy" | "encode" | "audio" | "gif" | "webp" | "frames", "inputs": [[...]], "vsteps", "asteps",
          "venc", "aenc", "opts", "out", "expect": {...}, "notes": [...], "rate": {...}, "pre": ["stab" | "loud"]}
  graph(job, stage) -> (filter graph, video label, sound label) for "encode", "stab" (shake detection), "loud" (loudness
                       measure) or "ref" (the picture as it should look, for the quality check)
  window(pieces, speed, a, b) -> the pieces under output seconds a..b (samples and quality checks)

Decisions made here, each with a note the person reads: copy the picture when nothing about it changes (lossless, in
seconds); cut on keyframes without re-encoding when a cut lands close to one or re-encoding would be slow; pick the frame
size and rate a file must have to fit a size limit and still look fine; give joined clips the first one's frame (with
blurred sides for a clip of another shape); keep the sound in step through cuts, speed changes and joins.
`over` changes one decision when a job is built again: {"q": knob} {"sized": True, "kbps_scale": 0.9} {"encode": True}
{"enc": name} {"gif_long": 360, "colors": 128} {"fast": True}.
"""

import math
import re
import shutil
from pathlib import Path

from ai_pc.convert import media as MD
from ai_pc.convert.presets import AUDIO_ONLY, BPP, CONTAINERS, ENCODERS, LEVELS, MPX_PER_S, PRESETS, QUALITY, VIDEO_CONTAINERS, ratio

TIME_OPS = {"trim", "cut", "join", "speed"}
TONEMAP = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
AAC_K = {"best": 256, "high": 192, "good": 160, "small": 112, "tiny": 80}
OPUS_K = {"best": 192, "high": 160, "good": 128, "small": 96, "tiny": 64}
MP3_Q = {"best": "0", "high": "2", "good": "3", "small": "5", "tiny": "7"}
MP3_RATES = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
SHORT_SIDES = (2160, 1440, 1080, 720, 540, 480, 360, 240)
WORDS = {"h264": "H.264", "av1": "AV1", "hevc": "HEVC", "vp9": "VP9", "prores": "ProRes", "mpeg4": "MPEG-4"}


class PlanError(ValueError):
    pass


def even(x):
    return max(2, int(round(float(x) / 2.0)) * 2)


def _down(w, h, k):
    """(w, h) scaled down by k (never up), even."""
    return (even(w * k), even(h * k)) if k < 0.999 else (w - w % 2, h - h % 2)


# ---------------------------------------------------------------- the timeline
def _merge(pieces):
    out = []
    for p in pieces:
        if p["end"] - p["start"] < 1e-3:
            continue
        if out and out[-1]["src"] == p["src"] and abs(out[-1]["end"] - p["start"]) < 1e-3:
            out[-1]["end"] = p["end"]
        else:
            out.append(dict(p))
    return out


def total(pieces):
    return sum(p["end"] - p["start"] for p in pieces)


def _keep(pieces, a, b):
    out, t = [], 0.0
    for p in pieces:
        n = p["end"] - p["start"]
        s, e = max(a, t), min(b, t + n)
        if e - s > 1e-3:
            out.append({"src": p["src"], "start": p["start"] + (s - t), "end": p["start"] + (e - t)})
        t += n
    return _merge(out)


def window(pieces, speed, a, b):
    return _keep(pieces, a * speed, b * speed)


def src_time(pieces, speed, t):
    """Output second t -> (source index, source second)."""
    x, acc = t * speed, 0.0
    for p in pieces:
        n = p["end"] - p["start"]
        if x <= acc + n + 1e-6:
            return p["src"], p["start"] + max(0.0, x - acc)
        acc += n
    return pieces[-1]["src"], pieces[-1]["end"]


def _span(a, tot):
    if a.get("first") is not None:
        return 0.0, min(tot, float(a["first"]))
    if a.get("last") is not None:
        return max(0.0, tot - float(a["last"])), tot
    s = float(a.get("start") or 0.0)
    e = a.get("end")
    if a.get("drop_start"):
        s = float(a["drop_start"])
    if a.get("drop_end"):
        e = tot - float(a["drop_end"])
    e = tot if e is None else min(float(e), tot)
    if s >= tot - 0.05:
        raise PlanError(f"it is only {MD.mmss(tot)} long, so there is nothing at {MD.mmss(s)}")
    if e - s < 0.05:
        raise PlanError(f"{MD.mmss(s)} to {MD.mmss(e)} is empty")
    return s, e


def timeline(chain, sources):
    """The output as pieces of the sources ({"src", "start", "end"} in source seconds) and one speed for all. Times
    in trims and cuts are output seconds at that point of the chain (after earlier cuts and speed changes)."""
    pieces = [{"src": 0, "start": 0.0, "end": float(sources[0]["duration"])}]
    speed = 1.0
    for o in chain:
        k, a = o["op"], o.get("args") or {}
        if k == "join":
            new = [{"src": j, "start": 0.0, "end": float(sources[j]["duration"])} for j in a.get("srcs") or []]
            pieces = _merge(new + pieces if a.get("before") else pieces + new)
        elif k == "speed":
            f = float(a.get("factor") or 1.0)
            if not 0.05 <= f <= 100:
                raise PlanError("the speed must be between 0.05x and 100x")
            speed *= f
        elif k == "trim":
            s, e = _span(a, total(pieces) / speed)
            pieces = _keep(pieces, s * speed, e * speed)
        elif k == "cut":
            tot = total(pieces) / speed
            for s, e in sorted(((float(r[0]), min(float(r[1]), tot)) for r in a.get("ranges") or [] if float(r[0]) < tot), reverse=True):
                if e - s > 0.01:
                    pieces = _merge(_keep(pieces, 0, s * speed) + _keep(pieces, e * speed, total(pieces)))
        if not pieces or total(pieces) < 0.05:
            raise PlanError("that would leave nothing")
    return pieces, speed


# ---------------------------------------------------------------- what was asked
DEFAULTS = {
    "mode": "video",
    "container": None,
    "vcodec": None,
    "acodec": None,
    "quality": None,
    "max_mb": None,
    "percent": None,
    "same": False,
    "preset": None,
    "resize": None,
    "fps": None,
    "aspect": None,
    "fit": None,
    "focus": None,
    "rotate": 0,
    "hflip": False,
    "vflip": False,
    "bars": False,
    "crop": None,
    "deint": False,
    "stab": None,
    "denoise": None,
    "sharpen": False,
    "gray": False,
    "logo": None,
    "subs": None,
    "fade_in": 0.0,
    "fade_out": 0.0,
    "mute": False,
    "audio": None,
    "volume_db": 0.0,
    "normalize": None,
    "sync": 0.0,
    "mono": False,
    "hw": None,
    "lossless": False,
    "exact": False,
    "gif": None,
    "frames": None,
    "split": None,
    "smooth": False,
}


def settings(chain):
    S = dict(DEFAULTS)
    for o in chain:
        k, a = o["op"], o.get("args") or {}
        if k == "target":
            S["preset"] = a.get("name")
        elif k == "format":
            to = (a.get("to") or "").lower().lstrip(".")
            to = {"jpeg": "jpg", "matroska": "mkv", "m4v": "mp4", "mpeg4": "mp4", "wave": "wav", "oga": "ogg", "quicktime": "mov"}.get(to, to)
            if to in AUDIO_ONLY:
                S.update(mode="audio", container=to)
            elif to in ("gif", "webp"):
                S.update(mode=to, gif=S["gif"] or {})
            elif to in VIDEO_CONTAINERS:
                S.update(mode="video", container=to, gif=None, frames=None)
            else:
                raise PlanError(f"I can't make {to.upper()} files here")
        elif k == "codec":
            S["vcodec"] = a.get("video") or S["vcodec"]
            S["acodec"] = a.get("audio") or S["acodec"]
        elif k == "compress":
            S.update(max_mb=None, percent=None, same=False)
            if a.get("max_mb"):
                S["max_mb"] = float(a["max_mb"])
            elif a.get("percent"):
                S["percent"] = float(a["percent"])
            elif a.get("level"):
                S["quality"] = a["level"]
            else:
                S["same"] = True
        elif k == "quality":
            S["quality"] = a.get("level")
            S["same"] = a.get("level") == "same"
        elif k == "resize":
            S["resize"] = dict(a)
        elif k == "fps":
            S["fps"] = float(a["fps"])
        elif k == "aspect":
            S["aspect"], S["fit"], S["focus"] = a.get("ratio"), a.get("fit") or S["fit"], a.get("focus") or S["focus"]
        elif k == "rotate":
            S["rotate"] = (S["rotate"] + int(a.get("deg", 90))) % 360
        elif k == "flip":
            S["hflip" if a.get("dir", "h") == "h" else "vflip"] ^= True
        elif k == "bars":
            S["bars"] = a.get("on", True)
        elif k == "crop":
            S["crop"] = dict(a)
        elif k in ("deinterlace", "sharpen", "gray", "mono", "smooth"):
            S[{"deinterlace": "deint"}.get(k, k)] = a.get("on", True)
        elif k == "stabilize":
            S["stab"] = a.get("strength", "medium")
        elif k == "denoise":
            S["denoise"] = a.get("strength", "medium")
        elif k == "logo":
            S["logo"] = dict(a)
        elif k == "subtitles":
            S["subs"] = dict(a)
        elif k == "fade":
            S["fade_in"] = float(a.get("in", S["fade_in"]) or 0)
            S["fade_out"] = float(a.get("out", S["fade_out"]) or 0)
        elif k == "mute":
            S.update(mute=True, audio=None)
        elif k == "audio":
            S.update(audio=dict(a), mute=False)
        elif k == "volume":
            S["volume_db"] += float(a.get("db", 0))
        elif k == "normalize":
            S["normalize"] = float(a.get("lufs", -14))
        elif k == "sync":
            S["sync"] += float(a.get("delay", 0))
        elif k == "extract_audio":
            fmt = a.get("fmt") if a.get("fmt") in AUDIO_ONLY else S["container"] if S["container"] in AUDIO_ONLY else "mp3"
            S.update(mode="audio", container=fmt)
        elif k == "gif":
            S.update(mode="webp" if a.get("fmt") == "webp" else "gif", gif=dict(a))
        elif k == "frames":
            S.update(mode="frames", frames=dict(a))
        elif k == "split":
            S["split"] = dict(a) if a else None
        elif k == "video":  # back to a video after a GIF, sound or pictures
            S.update(mode="video", container=a.get("to") if a.get("to") in VIDEO_CONTAINERS else None, gif=None, frames=None)
        elif k == "hw":
            S["hw"] = a.get("use")
        elif k == "lossless":
            S["lossless"] = True
        elif k == "exact":
            S["exact"] = True
    return S


# ---------------------------------------------------------------- encoders
def encoder(vcodec, S, caps):
    """The Intel GPU's encoder when this PC has it (faster, and on this PC as good per byte), else the processor's;
    'best quality' and 'use the processor' take the processor's."""
    hw, sw = ENCODERS.get(vcodec, (None, vcodec))
    if hw and caps.get(hw) and S.get("hw") != "cpu" and (S.get("hw") == "gpu" or S.get("quality") != "best"):
        return hw
    return sw


def venc(enc, q=None, kbps=None, fast=False):
    """Encoder arguments for a quality knob q, or for a bitrate in kbps."""
    rate = ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.6)}k", "-bufsize", f"{int(kbps * 2)}k"] if kbps else None
    if enc in ("h264_qsv", "av1_qsv"):
        return ["-c:v", enc, "-preset", "medium"] + (["-profile:v", "high"] if enc == "h264_qsv" else []) + (rate or ["-global_quality", str(q)])
    if enc == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast" if fast else "slow" if (q or 99) <= 18 else "medium", "-profile:v", "high"] + (
            rate or ["-crf", str(q)]
        )
    if enc == "libsvtav1":
        return ["-c:v", "libsvtav1", "-preset", "10" if fast else "6" if (q or 99) <= 22 else "8"] + (
            ["-b:v", f"{kbps}k"] if kbps else ["-crf", str(q)]
        )
    if enc == "libvpx-vp9":
        return ["-c:v", "libvpx-vp9", "-row-mt", "1", "-deadline", "good", "-cpu-used", "6" if fast else "4"] + (
            ["-b:v", f"{kbps}k"] if kbps else ["-crf", str(q), "-b:v", "0"]
        )
    if enc == "libx265":
        return ["-c:v", "libx265", "-preset", "fast" if fast else "medium", "-x265-params", "log-level=error"] + (
            ["-b:v", f"{kbps}k"] if kbps else ["-crf", str(q)]
        )
    if enc == "prores_ks":
        return ["-c:v", "prores_ks", "-profile:v", "2", "-vendor", "apl0"]
    if enc == "mpeg4":
        return ["-c:v", "mpeg4", "-vtag", "xvid"] + (["-b:v", f"{kbps}k"] if kbps else ["-q:v", str(q)])
    raise PlanError(f"no encoder {enc}")


def aenc(codec, level="good", kbps=None, channels=None):
    ch = ["-ac", str(channels)] if channels else []
    if codec == "aac":
        return ["-c:a", "aac", "-b:a", f"{kbps or AAC_K.get(level, 160)}k"] + ch
    if codec == "mp3":
        if kbps:
            kbps = min(MP3_RATES, key=lambda r: (r > kbps, abs(r - kbps)))  # the nearest standard rate at or under it
            return ["-c:a", "libmp3lame", "-b:a", f"{kbps}k"] + ch
        return ["-c:a", "libmp3lame", "-q:a", MP3_Q.get(level, "3")] + ch
    if codec in ("opus", "vorbis"):
        return ["-c:a", "libopus", "-b:a", f"{kbps or OPUS_K.get(level, 128)}k"] + ch
    if codec in ("flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_f32le", "ac3"):
        return ["-c:a", codec] + ch
    raise PlanError(f"no sound encoder for {codec}")


def atempo(f):
    """A speed change for sound that keeps its pitch, in steps atempo takes (0.5-2 each)."""
    out = []
    while f > 2.0 + 1e-9:
        out.append("atempo=2.0")
        f /= 2.0
    while f < 0.5 - 1e-9:
        out.append("atempo=0.5")
        f /= 0.5
    if abs(f - 1) > 1e-6:
        out.append(f"atempo={f:.6g}")
    return out


def fit_bitrate(w, h, fps, kbps, codec):
    """The biggest frame (and, for fast footage, 30 fps) a bitrate can fill and still look fine: (w, h, fps, fine)."""
    need = BPP.get(codec, 0.055)
    short = min(w, h)
    sides = [short] + [s for s in SHORT_SIDES if s < short]
    rates = [fps] + ([30.0] if fps > 31 else [])
    for s in sides:
        ww, hh = _down(w, h, s / short)
        for r in rates:
            if kbps * 1000 / (ww * hh * r) >= need:
                return ww, hh, r, True
    ww, hh = _down(w, h, 240 / short)
    return ww, hh, min(fps, 24.0), False


def fit_sample(w, h, fps, kbps, k_native):
    """Like fit_bitrate, from what a sample of this video needed at full size for good quality (k_native kbps): the
    biggest frame whose estimated need (it falls about as pixels^0.75) the bitrate covers, allowing a little under 'good'
    (a sharper frame a touch below 'good' beats a softer one well above it). None when even 240p would not fit."""
    short = min(w, h)
    for s in [short] + [x for x in SHORT_SIDES if x < short]:
        ww, hh = _down(w, h, s / short)
        for r in [fps] + ([30.0] if fps > 31 else []):
            if k_native * ((ww * hh * r) / (w * h * fps)) ** 0.75 <= kbps * 1.15:
                return ww, hh, r, True
    return None


# ---------------------------------------------------------------- the filter graph
class Graph:
    def __init__(self):
        self.lines, self.k = [], 0

    def new(self, p="v"):
        self.k += 1
        return f"{p}{self.k}"

    def chain(self, src, filters, p="v"):
        if not filters:
            return src
        dst = self.new(p)
        srcs = "".join(f"[{s}]" for s in (src if isinstance(src, (list, tuple)) else [src]))
        self.lines.append(f"{srcs}{','.join(filters)}[{dst}]")
        return dst

    def source(self, text, p="a"):
        dst = self.new(p)
        self.lines.append(f"{text}[{dst}]")
        return dst

    def text(self):
        return ";".join(self.lines)


def _blurpad(g, lab, W, H):
    """The picture fitted inside W x H over a blurred, darker copy of itself filling the rest."""
    a, b = g.new(), g.new()
    g.lines.append(f"[{lab}]split[{a}][{b}]")
    bw, bh = even(W / 4), even(H / 4)
    bg = g.chain(
        a, [f"scale={bw}:{bh}:force_original_aspect_ratio=increase", f"crop={bw}:{bh}", "boxblur=8:3", f"scale={W}:{H}", "eq=brightness=-0.06"]
    )
    fg = g.chain(b, [f"scale={W}:{H}:force_original_aspect_ratio=decrease", "setsar=1"])
    return g.chain([bg, fg], ["overlay=(W-w)/2:(H-h)/2", "setsar=1"])


def _logo(g, lab, idx, o, W, H):
    lw = even(W * float(o.get("size", 0.15)))
    m = max(8, int(min(W, H) * 0.03))
    pos = {
        "br": (f"W-w-{m}", f"H-h-{m}"),
        "bl": (f"{m}", f"H-h-{m}"),
        "tr": (f"W-w-{m}", f"{m}"),
        "tl": (f"{m}", f"{m}"),
        "center": ("(W-w)/2", "(H-h)/2"),
    }.get(o.get("corner", "br"), (f"W-w-{m}", f"H-h-{m}"))
    lg = g.chain(f"{idx}:v:0", [f"scale={lw}:-1", "format=rgba", f"colorchannelmixer=aa={float(o.get('opacity', 0.85)):.2f}"])
    return g.chain([lab, lg], [f"overlay=x={pos[0]}:y={pos[1]}:format=auto"])


def _palette(g, lab, colors):
    a, b = g.new(), g.new()
    g.lines.append(f"[{lab}]split[{a}][{b}]")
    p = g.chain(a, [f"palettegen=max_colors={colors}:stats_mode=diff"])
    return g.chain([b, p], ["paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"])


def graph(job, stage="encode"):
    """(filter graph text, video label or None, sound label or None)."""
    g = Graph()
    want_v = stage in ("encode", "stab", "ref") and job.get("vsteps") is not None
    want_a = stage in ("encode", "loud") and job.get("asteps") is not None
    ai = job.get("audio_in")
    keep_a = want_a and not (ai and ai["mode"] == "replace")  # a replaced sound is not read at all
    vlabs, alabs = [], []
    for pc in job["pieces_in"]:
        if want_v:
            if pc["vnorm"] == "blurpad":  # a joined clip of another shape: fitted into the first clip's frame
                lab = _blurpad(g, g.chain(f"{pc['idx']}:v:0", ["setpts=PTS-STARTPTS"]), *job["canvas"])
                vlabs.append(g.chain(lab, [f"fps={job['canvas_fps']:g}", "format=yuv420p"]))
            else:
                vlabs.append(g.chain(f"{pc['idx']}:v:0", pc["vnorm"]))
        if keep_a:
            alabs.append(
                g.chain(f"{pc['idx']}:a:0", pc["anorm"], p="a")
                if pc["has_a"]
                else g.source(f"anullsrc=r=48000:cl={job.get('layout', 'stereo')},atrim=duration={pc['dur']:.3f}")
            )
    vl = al = None
    n = len(job["pieces_in"])
    if n > 1 and (want_v or keep_a):
        ins = [x for k in range(n) for x in ([vlabs[k]] if want_v else []) + ([alabs[k]] if keep_a else [])]
        outs = ([g.new()] if want_v else []) + ([g.new("a")] if keep_a else [])
        g.lines.append("".join(f"[{x}]" for x in ins) + f"concat=n={n}:v={int(want_v)}:a={int(keep_a)}" + "".join(f"[{x}]" for x in outs))
        vl = outs[0] if want_v else None
        al = outs[-1] if keep_a else None
    elif n == 1:
        vl = vlabs[0] if want_v else None
        al = alabs[0] if keep_a else None
    if want_v:
        buf = []
        for st in job["vsteps"]:
            if st[0] == "f":
                buf.append(st[1])
                continue
            vl, buf = g.chain(vl, buf), []
            if st[0] == "stab":
                if stage == "stab":
                    buf.append(f"vidstabdetect=shakiness={st[1]}:accuracy=15:result=stab.trf")
                    break
                buf += [f"vidstabtransform=input=stab.trf:smoothing={st[2]}:optzoom=1:interpol=bicubic", "unsharp=5:5:0.6:3:3:0.3"]
            elif st[0] == "blurpad":
                vl = _blurpad(g, vl, st[1], st[2])
            elif st[0] == "logo":
                vl = _logo(g, vl, st[1], st[2], st[3], st[4])
            elif st[0] == "palette":
                vl = _palette(g, vl, st[1])
        vl = g.chain(vl, buf)
    if want_a:
        steps = list(job["asteps"])
        if stage == "loud":
            steps = [s for s in steps if not s.startswith("loudnorm")] + [f"loudnorm=I={job['loud_target']}:TP=-1.5:LRA=11:print_format=json"]
        if ai:  # a sound file instead of, or under, the original sound
            m = g.chain(
                f"{ai['idx']}:a:0",
                [
                    f"atrim=0:{ai['dur']:.3f}",
                    "asetpts=PTS-STARTPTS",
                    f"volume={ai['db']:.1f}dB",
                    "aresample=48000",
                    "aformat=sample_fmts=fltp:channel_layouts=stereo",
                ],
                p="a",
            )
            if ai["mode"] == "mix" and al is not None:
                al = g.chain(al, ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo"], p="a")
                al = g.chain([al, m], ["amix=inputs=2:duration=first:dropout_transition=0:normalize=0"], p="a")
            else:
                al = m
        al = g.chain(al, steps, p="a")
    return g.text(), vl, al


# ---------------------------------------------------------------- building a job
def _inputs_for(pieces, sources):
    """One input per piece, opened at its start (fast seeking; frame-exact, since the picture is re-encoded)."""
    ins = []
    for p in pieces:
        src = sources[p["src"]]
        s, e = p["start"], p["end"]
        args = []
        if s > 0.001:  # half a millisecond early, so a frame that sits exactly at s is the first one (rounding never skips it)
            args += ["-ss", f"{max(0.0, s - 0.0005):.6f}"]
        if e < float(src["duration"]) - 0.001 or s > 0.001:
            args += ["-t", f"{e - s:.6f}"]
        ins.append(args + ["-i", src["path"]])
    return ins


def _pieces_in(job, sources, video=True, canvas=None, canvas_fps=None):
    """Per piece: its input and the filters that make all pieces alike (size, frame rate, sound format)."""
    multi = len(job["pieces"]) > 1
    joined = len({p["src"] for p in job["pieces"]}) > 1
    layout = "mono" if all((sources[p["src"]].get("audio") or {}).get("channels", 1) == 1 for p in job["pieces"]) else "stereo"
    out = []
    for k, p in enumerate(job["pieces"]):
        src = sources[p["src"]]
        v = src.get("video")
        vnorm = ["setpts=PTS-STARTPTS"]
        if video and v and abs((v.get("sar") or 1) - 1) > 0.01:
            vnorm += ["scale=iw*sar:ih", "setsar=1"]
        if video and joined and canvas:
            W, H = canvas
            vnorm = (
                "blurpad" if abs(v["w"] / v["h"] - W / H) > 0.03 else vnorm + [f"scale={W}:{H}", "setsar=1", f"fps={canvas_fps:g}", "format=yuv420p"]
            )
        anorm = ["asetpts=PTS-STARTPTS"] + (["aresample=48000", f"aformat=sample_fmts=fltp:channel_layouts={layout}"] if multi else [])
        out.append({"idx": k, "vnorm": vnorm, "anorm": anorm, "has_a": bool(src.get("audio")), "dur": p["end"] - p["start"]})
    job["pieces_in"], job["layout"] = out, layout


def _keyframe_snap(src, t):
    """The last keyframe at or before t (where a copy can start cleanly)."""
    if t < 0.01:
        return 0.0
    before = [k for k in MD.keyframes(src["path"], near=t) if k <= t + 0.002]
    return before[-1] if before else 0.0


def _cap(S, preset, gif, D, est):
    """The size limit (bytes) and where it came from: asked ('under 10 MB', 'half the size'), or the target's."""
    if gif and gif.get("max_mb"):
        return gif["max_mb"] * 1e6, "asked"
    if S.get("max_mb"):
        return S["max_mb"] * 1e6, "asked"
    if S.get("percent"):
        return est * S["percent"] / 100.0, "asked"
    if preset and preset.get("max_mb"):
        return preset["max_mb"] * 1e6, "preset"
    return None, None


def est_size(pieces, speed, sources):
    """What the pieces weigh as they are (bytes)."""
    return sum(sources[p["src"]]["size"] * (p["end"] - p["start"]) / max(float(sources[p["src"]]["duration"]), 0.01) for p in pieces)


def build(S, pieces, speed, sources, folder, caps, over=None, name="out"):
    over = over or {}
    preset = PRESETS.get(S.get("preset")) if S.get("preset") else None
    D = total(pieces) / speed
    used = sorted({p["src"] for p in pieces})
    has_v = any((sources[i].get("video") and not sources[i]["video"].get("image")) for i in used)
    has_a = any(sources[i].get("audio") for i in used)
    mode = S["mode"]
    job = {
        "mode": mode,
        "D": D,
        "pieces": pieces,
        "speed": speed,
        "notes": [],
        "pre": [],
        "preset": S.get("preset"),
        "split": S.get("split"),
        "folder": str(folder),
        "name": name,
        "audio_in": None,
    }
    if mode in ("video", "gif", "webp", "frames") and not has_v:
        if mode != "video":
            raise PlanError("it is sound only, so there is no picture for that")
        job["mode"] = "audio"
        if S["container"] in VIDEO_CONTAINERS:
            job["notes"].append("it is sound only, so it stays a sound file")
    if job["mode"] == "audio":
        return _build_audio(job, S, sources, preset, over, has_a)
    if job["mode"] == "frames":
        return _build_frames(job, S, sources)
    return _build_video(job, S, sources, preset, caps, over, has_a)


def _asteps(S, D, speed, job):
    """The sound's own changes after the pieces are joined (speed, sync, volume, loudness, fades)."""
    if S.get("mute"):
        return []
    st = atempo(speed)
    if S.get("sync"):
        d = float(S["sync"])
        st += [f"adelay=delays={int(d * 1000)}:all=1"] if d > 0 else [f"atrim=start={-d:.3f}", "asetpts=PTS-STARTPTS"]
        st += [f"apad=whole_dur={D:.3f}", f"atrim=0:{D:.3f}"]
    if S.get("volume_db"):
        st.append(f"volume={S['volume_db']:.1f}dB")
    if S.get("normalize") is not None:
        job["loud_target"] = S["normalize"]
        if "loud" not in job["pre"]:
            job["pre"].append("loud")
        st.append("loudnorm=PENDING")  # the measured values go here once the first pass has measured them
    if S.get("fade_in"):
        st.append(f"afade=t=in:st=0:d={S['fade_in']:.2f}")
    if S.get("fade_out"):
        st.append(f"afade=t=out:st={max(0.0, D - S['fade_out']):.3f}:d={S['fade_out']:.2f}")
    return st


def _audio_input(job, S, sources):
    a = S.get("audio")
    if not a:
        return
    p = MD.probe(a["file"])
    if not p.get("audio"):
        raise PlanError(f"{p['name']} has no sound")
    loop = p["duration"] < job["D"] - 0.05
    idx = len(job["inputs"])
    job["inputs"].append((["-stream_loop", "-1"] if loop else []) + ["-i", p["path"]])
    mode = a.get("mode", "replace") if any(sources[x["src"]].get("audio") for x in job["pieces"]) else "replace"
    job["audio_in"] = {"idx": idx, "dur": job["D"], "mode": mode, "db": float(a.get("db", -14 if mode == "mix" else 0))}
    if loop:
        job["notes"].append(f"{p['name']} is shorter than the video, so it repeats")


def _build_audio(job, S, sources, preset, over, has_a):
    pieces, speed, D = job["pieces"], job["speed"], job["D"]
    if not has_a and not S.get("audio"):
        raise PlanError("it has no sound to save")
    main = sources[pieces[0]["src"]]
    src_a = (main.get("audio") or {}).get("codec")
    if S["container"] in AUDIO_ONLY:
        cont = S["container"]
    elif main.get("video") is None and main["container"] in AUDIO_ONLY and src_a in CONTAINERS[main["container"]]["audio"]:
        cont = main["container"]  # a sound file stays the kind it is unless another is asked for
    else:
        cont = "mp3"
    allowed = CONTAINERS[cont]["audio"]
    acodec = S["acodec"] if S["acodec"] in allowed else (src_a if src_a in allowed else CONTAINERS[cont]["default"][1])
    level = S.get("quality") if S.get("quality") in LEVELS else (preset or {}).get("quality") if (preset or {}).get("quality") in LEVELS else "high"
    cap, _ = _cap(S, preset, None, D, est_size(pieces, speed, sources))
    fx = _asteps(S, D, speed, job)
    single = len(pieces) == 1 and pieces[0]["src"] == 0
    est = est_size(pieces, speed, sources) if main.get("video") is None else (main["audio"]["bitrate"] or 128000) * D / 8
    if single and not fx and not S.get("audio") and src_a == acodec and not S.get("quality") and not (cap and est > cap):
        whole = pieces[0]["start"] < 0.01 and pieces[0]["end"] > main["duration"] - 0.01
        job.update(
            kind="copy",
            inputs=_inputs_for(pieces, sources),
            maps=["-map", "0:a:0"],
            venc=["-vn"],
            aenc=["-c:a", "copy"],
            vsteps=None,
            asteps=None,
            acodec=src_a,
        )
        job["notes"].append(
            f"copied the {MD.CODEC_WORDS.get(src_a, src_a)} sound as it is (no quality lost)"
            if whole
            else "cut without re-encoding the sound (no quality lost)"
        )
    else:
        kbps = None
        if cap:
            kbps = int(cap * 8 / D / 1000 * 0.97)
            if kbps < 24:
                raise PlanError(f"{MD.mmss(D)} of sound cannot fit in {cap / 1e6:.1f} MB (it would need under 24 kbps)")
            kbps = min(kbps, 320)
            if acodec in ("flac", "pcm_s16le", "pcm_s24le", "alac"):
                acodec, cont = "mp3", "mp3"
                job["notes"].append("lossless sound cannot be squeezed, so it is MP3")
        job.update(
            kind="audio",
            inputs=_inputs_for(pieces, sources),
            vsteps=None,
            asteps=fx,
            acodec=acodec,
            venc=["-vn"],
            aenc=aenc(acodec, level, kbps if acodec in ("mp3", "aac", "opus", "vorbis") else None, 1 if S.get("mono") else None),
        )
        _pieces_in(job, sources, video=False)
        _audio_input(job, S, sources)
    job.update(
        ext=cont,
        mux=CONTAINERS[cont]["mux"],
        opts=(["-movflags", "+faststart"] if cont == "m4a" else []),
        rate={"kind": "audio", "cap": cap},
        out=str(Path(job["folder"]) / f"{job['name']}.{cont}"),
    )
    job["expect"] = {
        "duration": D,
        "video": False,
        "audio": True,
        "acodec": job["acodec"],
        "max_bytes": cap,
        "channels": 1 if S.get("mono") else None,
    }
    return job


def _build_video(job, S, sources, preset, caps, over, has_a):
    pieces, speed, D = job["pieces"], job["speed"], job["D"]
    if job["mode"] in ("gif", "webp"):
        preset = None
    main = sources[pieces[0]["src"]]
    mv = main["video"]
    used = sorted({p["src"] for p in pieces})
    joined = len(used) > 1
    notes = job["notes"]
    mode = job["mode"]
    t = preset or {}
    # ---- container and codecs
    if mode in ("gif", "webp"):
        cont = mode
    else:
        cont = S["container"] or t.get("container") or (main["container"] if main["container"] in VIDEO_CONTAINERS else "mp4")
    allowed_v, allowed_a = CONTAINERS[cont]["video"], CONTAINERS[cont]["audio"]
    if S["vcodec"] and S["vcodec"] not in allowed_v and mode == "video":
        notes.append(f"{MD.CODEC_WORDS.get(S['vcodec'], S['vcodec'])} does not go in {cont.upper()}")
    want_v = S["vcodec"] if S["vcodec"] in allowed_v else (t["vcodec"] if t.get("vcodec") in allowed_v and not S["container"] else None)
    keep_v = mv["codec"] if mv["codec"] in allowed_v else None
    vfam = (
        mode
        if mode in ("gif", "webp")
        else want_v or (keep_v if keep_v in ("h264", "av1", "prores", "vp9") else None) or CONTAINERS[cont]["default"][0]
    )
    src_a = (main.get("audio") or {}).get("codec")
    want_a = S["acodec"] if S["acodec"] in allowed_a else (t["acodec"] if t.get("acodec") in allowed_a else None)
    enc_a = want_a or CONTAINERS[cont]["default"][1]
    out_a = bool(allowed_a) and not S.get("mute") and (has_a or bool(S.get("audio")))
    # ---- what the picture needs
    fps_src = mv["fps"] or 30.0
    bits_bad = t.get("bits8") and (mv["bits"] > 8 or mv["chroma"] != "420")
    hdr_fix = bool(mv["hdr"])
    pre_aspect = bool(t.get("aspect")) and abs(mv["w"] / mv["h"] - ratio(t["aspect"])) > 0.03
    cfr_fix = bool(t.get("cfr") and mv["vfr"])
    spatial = any(
        [
            S["rotate"],
            S["hflip"],
            S["vflip"],
            S["bars"],
            S["crop"],
            S["aspect"],
            S["resize"],
            S["fps"],
            S["deint"],
            S["stab"],
            S["denoise"],
            S["sharpen"],
            S["gray"],
            S["logo"],
            (S["subs"] or {}).get("burn", True) if S["subs"] else False,
            S["fade_in"],
            S["fade_out"],
            speed != 1,
            joined,
            t.get("max_long") and max(mv["w"], mv["h"]) > t["max_long"],
            t.get("max_fps") and fps_src > t["max_fps"] + 0.5,
            bits_bad,
            pre_aspect,
            cfr_fix,
            t.get("bake_rotation") and mv["rotation"],
            mv["w"] % 2,
            mv["h"] % 2,
            mv["interlaced"] and preset,
            mode in ("gif", "webp"),
            abs((mv.get("sar") or 1) - 1) > 0.01 and preset,
            S.get("smooth"),
            hdr_fix and (preset or S["vcodec"]),
        ]
    )
    est = est_size(pieces, speed, sources)
    cap, cap_why = _cap(S, preset, S.get("gif") if mode in ("gif", "webp") else None, D, est)
    asked_rate = bool(S.get("same") or S.get("quality") or cap_why == "asked")
    can_copy_v = (
        mode == "video"
        and not spatial
        and not asked_rate
        and not (cap and est > cap * 0.97)
        and mv["codec"] in allowed_v
        and want_v in (None, mv["codec"])
        and (not t or mv["codec"] in t.get("vcodecs_ok", {t.get("vcodec")}))
    )
    a_changes = bool(_asteps(S, D, speed, {"pre": [], "notes": []}) or S.get("audio"))
    can_copy_a = (not out_a) or (
        src_a in allowed_a and want_a in (None, src_a) and not a_changes and (not t or src_a in t.get("acodecs_ok", {t.get("acodec")}))
    )
    if (
        cap_why == "asked"
        and mode == "video"
        and est <= cap * 0.97
        and not spatial
        and not S.get("same")
        and not S.get("quality")
        and mv["codec"] in allowed_v
        and want_v in (None, mv["codec"])
        and (not t or mv["codec"] in t.get("vcodecs_ok", {t.get("vcodec")}))
    ):
        can_copy_v = True  # it already fits: nothing to squeeze
        notes.append(f"it is already {MD.human(est)}, under {cap / 1e6:g} MB")
    # ---- copy: the picture as it is (a new container, a cut on keyframes, a size it already fits; the sound remade if it changes)
    if can_copy_v and not over.get("encode") and not (a_changes and len(pieces) > 1):
        whole = len(pieces) == 1 and pieces[0]["start"] < 0.01 and pieces[0]["end"] > main["duration"] - 0.01
        enc_s = mv["w"] * mv["h"] * fps_src * D / 1e6 / MPX_PER_S.get(encoder(vfam, S, caps), 150)
        snaps = [] if whole else [(p, _keyframe_snap(sources[p["src"]], p["start"])) for p in pieces]
        worst = max((p["start"] - s for p, s in snaps), default=0.0)
        if whole or (not S.get("exact") and (worst <= 0.25 or S.get("lossless") or enc_s > 45)):
            return _copy_job(job, S, sources, cont, snaps, whole, worst, enc_s, can_copy_a, out_a, enc_a, src_a, mv, cap, a_changes)
    # ---- the geometry: the frame after crops and turns, the shape asked for, the final size and frame rate
    canvas = (mv["w"] - mv["w"] % 2, mv["h"] - mv["h"] % 2)
    canvas_fps = round(fps_src, 3) if not mv["vfr"] else float(round(fps_src))
    job["canvas"], job["canvas_fps"] = canvas, canvas_fps
    if joined:
        if not all(sources[i].get("video") for i in used):
            raise PlanError("one of the files to join has no picture")
        odd = [sources[i]["name"] for i in used[1:] if abs(sources[i]["video"]["w"] / sources[i]["video"]["h"] - canvas[0] / canvas[1]) > 0.03]
        if odd:
            notes.append(f"{', '.join(odd)} {'is' if len(odd) == 1 else 'are'} another shape, so blurred sides fill the frame")
    _pieces_in(job, sources, video=True, canvas=canvas if joined else None, canvas_fps=canvas_fps)
    w, h = canvas
    crop_bars = None
    if S["bars"] and not joined:
        crop_bars = MD.bars(main)
        if crop_bars:
            notes.append(f"cut off the black bars ({w}x{h} -> {crop_bars[0]}x{crop_bars[1]})")
            w, h = crop_bars[0], crop_bars[1]
        else:
            notes.append("found no black bars to cut")
    crop_manual = None
    if S["crop"]:
        c = S["crop"]
        cw_, ch_ = min(w, even(c["w"])), min(h, even(c["h"]))
        crop_manual = (cw_, ch_, int(c.get("x", (w - cw_) / 2)), int(c.get("y", (h - ch_) / 2)))
        w, h = cw_, ch_
    rot = S["rotate"] % 360
    if rot in (90, 270):
        w, h = h, w
    aspect = S["aspect"] or t.get("aspect")
    fit = S["fit"] or "blur"
    shape = None  # (how, crop w, crop h) or (how, canvas w, canvas h)
    if aspect and abs(w / h - ratio(aspect)) > 0.01:
        r = ratio(aspect)
        wide = w / h > r
        if fit == "crop":
            nw, nh = (even(h * r), h - h % 2) if wide else (w - w % 2, even(w / r))
            notes.append(f"cropped to {aspect}: the {'sides' if wide else 'top and bottom'} are cut off")
        else:
            nw, nh = (w - w % 2, even(w / r)) if wide else (even(h * r), h - h % 2)
            notes.append(
                f"made it {aspect} with {'black bars' if fit == 'bars' else 'a blurred copy of the video'} filling the "
                f"{'top and bottom' if wide else 'sides'}"
            )
        shape = (fit, nw, nh)
        short0 = min(w, h)
        w, h = nw, nh
        if fit != "crop" and min(w, h) > short0:  # the frame grows to hold the picture: its short side stays the original's
            w, h = _down(w, h, short0 / min(w, h))  # (720p landscape -> 720x1280; a 1080 square -> 1080x1920)
    fw, fh = w - w % 2, h - h % 2
    if S["resize"]:
        rz = S["resize"]
        if rz.get("scale"):
            fw, fh = even(fw * float(rz["scale"])), even(fh * float(rz["scale"]))
        elif rz.get("width") and rz.get("height"):
            fw, fh = even(rz["width"]), even(rz["height"])
        elif rz.get("width"):
            fw, fh = even(rz["width"]), even(fh * float(rz["width"]) / fw)
        elif rz.get("height"):  # '720p' is the short side, for a landscape or a vertical picture alike
            k = float(rz["height"]) / min(fw, fh)
            fw, fh = even(fw * k), even(fh * k)
        elif rz.get("long"):
            k = float(rz["long"]) / max(fw, fh)
            fw, fh = even(fw * k), even(fh * k)
        if fw * fh > w * h * 1.02:
            notes.append("made it bigger than the original, which adds no detail")
    elif t.get("size"):
        pw, ph = t["size"]
        fw, fh = _down(fw, fh, min(pw / fw, ph / fh))
    if t.get("max_long") and max(fw, fh) > t["max_long"] and not S["resize"]:
        fw, fh = _down(fw, fh, t["max_long"] / max(fw, fh))
        notes.append(f"made it {min(fw, fh)}p, the most {t['label']} keeps")
    fps_out = S["fps"] or None
    if not fps_out and t.get("max_fps") and fps_src > t["max_fps"] + 0.5:
        fps_out = float(t["max_fps"])
        notes.append(f"{fps_src:g} -> {fps_out:g} fps, the most {t['label']} keeps")
    if not fps_out and (cfr_fix or speed != 1 or joined):
        fps_out = canvas_fps
    if over.get("dims"):  # the geometry of another job (a stretch of it rebuilt as the reference for the quality check)
        fw, fh, fps_out = over["dims"][0], over["dims"][1], over["dims"][2] or fps_out
    if mode in ("gif", "webp"):
        gopt = S.get("gif") or {}
        fps_out = float(over.get("gif_fps") or gopt.get("fps") or min(fps_src, 12.0 if mode == "gif" else 15.0))
        long = int(over.get("gif_long") or gopt.get("width") or 480)
        fw, fh = _down(fw, fh, long / max(fw, fh))
        if D > 20:
            notes.append(f"a {MD.mmss(D)} GIF is big; an MP4 of it would be about 10 times smaller")
    # ---- how good, or how big
    sized = mode == "video" and bool(cap) and (over.get("sized") or (cap_why == "asked" and not S.get("same")))
    ench = over.get("enc") or (ENCODERS[mode][1] if mode in ("gif", "webp") else encoder(vfam, S, caps))
    level = S["quality"] if S.get("quality") in LEVELS else t.get("quality") if t.get("quality") in LEVELS else "good"
    q = over.get("q")
    kbps = abps = None
    if sized:
        total_k = cap * 8 / D / 1000 * 0.95
        abps = 0 if not out_a else 160 if total_k > 3000 else 128 if total_k > 1200 else 96 if total_k > 500 else 64 if total_k > 200 else 48
        vk = total_k - abps
        if vk < 50:
            raise PlanError(
                f"{MD.mmss(D)} of video cannot fit in {cap / 1e6:.3g} MB and still be watchable; say 'split it into parts under "
                f"{cap / 1e6:.3g} MB', cut it shorter, or save the sound only"
            )
        if not S["resize"] and not S["fps"] and not over.get("nofit"):
            nw, nh, nf, fine = (fit_sample(fw, fh, fps_out or fps_src, vk, over["k_native"]) if over.get("k_native") else None) or fit_bitrate(
                fw, fh, fps_out or fps_src, vk, vfam
            )
            if (nw, nh) != (fw, fh):
                notes.append(f"made it {min(nw, nh)}p so {MD.mmss(D)} fits in {cap / 1e6:.3g} MB" + ("" if fine else "; it will look soft"))
                fw, fh = nw, nh
            if abs(nf - (fps_out or fps_src)) > 0.01:
                notes.append(f"{fps_src:g} -> {nf:g} fps to fit {cap / 1e6:.3g} MB")
                fps_out = nf
        kbps = max(40, int(vk * over.get("kbps_scale", 1.0)))
        job["rate"] = {"kind": "bitrate", "kbps": kbps, "abps": abps, "cap": cap, "why": cap_why}
    elif mode == "video":
        if S.get("same") or (t.get("quality") == "same" and not S.get("quality")):
            job["rate"] = {"kind": "search", "q": q, "cap": cap, "why": cap_why}
            q = q or QUALITY.get(ench, {}).get("good")
        else:
            q = q or QUALITY.get(ench, {}).get(level)
            job["rate"] = {"kind": "quality", "q": q, "level": level, "cap": cap, "why": cap_why}
    else:
        job["rate"] = {"kind": mode, "cap": cap, "why": cap_why}
    # ---- the picture's filters, in order
    steps = []
    if speed != 1:
        steps.append(("f", f"setpts=PTS/{speed:.6g}"))
    if hdr_fix:
        steps.append(("f", TONEMAP))
        notes.append("turned its HDR colours into normal ones, so they look right on every screen")
    if S["deint"] or (mv["interlaced"] and (preset or mode != "video")):
        steps.append(("f", "bwdif=mode=send_frame:deint=all"))
    if crop_bars:
        steps.append(("f", "crop={}:{}:{}:{}".format(*crop_bars)))
    if crop_manual:
        steps.append(("f", "crop={}:{}:{}:{}".format(*crop_manual)))
    if S["stab"]:
        sh, sm = {"light": (4, 8), "medium": (6, 15), "strong": (9, 30)}.get(S["stab"], (6, 15))
        steps.append(("stab", sh, sm))
        job["pre"].append("stab")
    steps += [("f", x) for x in {90: ["transpose=1"], 270: ["transpose=2"], 180: ["hflip", "vflip"]}.get(rot, [])]
    if S["hflip"]:
        steps.append(("f", "hflip"))
    if S["vflip"]:
        steps.append(("f", "vflip"))
    scaled = False
    if shape:
        how, nw, nh = shape
        if how == "crop":
            focus = S.get("focus") or "center"
            x = "0" if focus == "left" else f"iw-{nw}" if focus == "right" else f"(iw-{nw})/2"
            y = "0" if focus == "top" else f"ih-{nh}" if focus == "bottom" else f"(ih-{nh})/2"
            steps.append(("f", f"crop={nw}:{nh}:{x}:{y}"))
        elif how == "bars":
            steps += [
                ("f", f"scale={fw}:{fh}:force_original_aspect_ratio=decrease:flags=lanczos"),
                ("f", f"pad={fw}:{fh}:(ow-iw)/2:(oh-ih)/2:color=black"),
                ("f", "setsar=1"),
            ]
            scaled = True
        else:
            steps.append(("blurpad", fw, fh))
            scaled = True
    if not scaled and ((fw, fh) != (w, h)):
        steps += [("f", f"scale={fw}:{fh}:flags=lanczos"), ("f", "setsar=1")]
    if S["denoise"]:
        steps.append(
            ("f", {"light": "hqdn3d=1.5:1.5:4:4", "medium": "hqdn3d=3:3:6:6", "strong": "hqdn3d=5:4:9:7"}.get(S["denoise"], "hqdn3d=3:3:6:6"))
        )
    if S["sharpen"]:
        steps.append(("f", "unsharp=5:5:0.8:3:3:0.4"))
    if S["gray"]:
        steps.append(("f", "hue=s=0"))
    if fps_out and (abs(fps_out - fps_src) > 0.01 or mv["vfr"] or speed != 1 or joined):
        steps.append(
            ("f", f"minterpolate=fps={fps_out:g}:mi_mode=mci:mc_mode=aobmc:vsbmc=1" if S.get("smooth") and speed < 1 else f"fps={fps_out:g}")
        )
    inputs = _inputs_for(pieces, sources)
    if S["logo"]:
        steps.append(("logo", len(inputs), S["logo"], fw, fh))
        inputs.append(["-i", str(Path(S["logo"]["file"]))])
    subs_soft = None
    if S["subs"]:
        sub_name = _subs_file(S["subs"]["file"], pieces, speed, Path(job["folder"]))
        if not sub_name:
            notes.append("no subtitle falls in the part kept, so there are none")
        elif S["subs"].get("burn", True):
            steps.append(("f", f"subtitles={sub_name}:force_style='FontName=Arial,FontSize=20,Outline=1.2,Shadow=0,MarginV=24'"))
        else:
            subs_soft = sub_name
    if S["fade_in"]:
        steps.append(("f", f"fade=t=in:st=0:d={S['fade_in']:.2f}"))
    if S["fade_out"]:
        steps.append(("f", f"fade=t=out:st={max(0.0, D - S['fade_out']):.3f}:d={S['fade_out']:.2f}"))
    ten = mode == "video" and t.get("bits8") is False and mv["bits"] > 8 and vfam in ("av1", "hevc") and not hdr_fix
    if mode == "gif":
        steps.append(("palette", int(over.get("colors") or (S.get("gif") or {}).get("colors") or 256)))
    elif vfam == "prores":
        steps.append(("f", "format=yuv422p10le"))
    elif mode == "video":
        qsv = ench.endswith("_qsv")
        steps.append(("f", "format=" + (("p010le" if qsv else "yuv420p10le") if ten else ("nv12" if qsv else "yuv420p"))))
    job.update(kind=mode if mode in ("gif", "webp") else "encode", inputs=inputs, vsteps=steps, w=fw, h=fh, fps=fps_out, venc_name=ench, vcodec=vfam)
    job["asteps"] = _asteps(S, D, speed, job) if out_a else None
    if out_a:
        _audio_input(job, S, sources)
    if mode == "video":
        job["venc"] = venc(ench, q=q, kbps=kbps if sized else None, fast=bool(over.get("fast")))
        job["aenc"] = aenc(enc_a, level if level in AAC_K else "good", kbps=abps or None, channels=1 if S.get("mono") else None) if out_a else ["-an"]
        job["acodec"] = enc_a if out_a else None
    elif mode == "gif":
        job.update(venc=["-c:v", "gif", "-loop", "0"], aenc=["-an"], acodec=None)
    else:
        job.update(
            venc=["-c:v", "libwebp_anim", "-lossless", "0", "-q:v", str(int(over.get("webp_q", 70))), "-loop", "0", "-compression_level", "4"],
            aenc=["-an"],
            acodec=None,
        )
    opts = []
    if cont in ("mp4", "mov"):
        opts += ["-movflags", "+faststart"] + (["-tag:v", "hvc1"] if vfam == "hevc" else [])
    if len(pieces) > 1 or pieces[0]["start"] > 0.01 or speed != 1:
        opts += ["-map_chapters", "-1"]
    split_t = _split_times(S.get("split") or {}, D)
    if split_t and mode == "video":
        opts += ["-force_key_frames", ",".join(f"{x:.3f}" for x in split_t)] + (["-forced_idr", "1"] if ench.endswith("_qsv") else [])
    if subs_soft:
        job["subs_in"] = {"idx": len(job["inputs"]), "codec": {"mp4": "mov_text", "mov": "mov_text", "mkv": "srt", "webm": "webvtt"}.get(cont, "srt")}
        job["inputs"].append(["-i", str(Path(job["folder"]) / subs_soft)])
    job.update(ext=cont, mux=CONTAINERS[cont]["mux"], opts=opts, out=str(Path(job["folder"]) / f"{job['name']}.{cont}"))
    job["expect"] = {
        "duration": D,
        "video": True,
        "vcodec": vfam,
        "w": fw,
        "h": fh,
        "fps": fps_out if mode == "video" else None,
        "audio": out_a,
        "acodec": enc_a if out_a else None,
        "max_bytes": cap,
        "faststart": cont in ("mp4", "mov"),
        "pix8": vfam in ("h264", "hevc", "av1", "vp9") and not ten,
        "channels": 1 if (S.get("mono") and out_a) else None,
    }
    if mode == "video":
        notes.append(f"made the picture as {WORDS.get(vfam, vfam)} on {'the Intel GPU' if ench.endswith('_qsv') else 'the processor'}")
    return job


def _copy_job(job, S, sources, cont, snaps, whole, worst, enc_s, can_copy_a, out_a, enc_a, src_a, mv, cap, a_changes=False):
    pieces = job["pieces"]
    notes = job["notes"]
    main = sources[pieces[0]["src"]]
    if snaps:
        pieces = [dict(p, start=s) for p, s in snaps]
        job["pieces"], job["D"] = pieces, total(pieces) / job["speed"]
        if worst > 0.25:
            notes.append(
                f"cut at the nearest clean cut point (up to {worst:.1f} s earlier than asked) so nothing is re-encoded"
                + (f"; say 'cut it exactly' to re-encode instead (about {max(1, round(enc_s / 60))} min)" if enc_s > 45 else "")
            )
    acopy = can_copy_a and out_a
    if len(pieces) > 1:  # pieces of one file joined back without re-encoding (the concat demuxer, from keyframe to cut)
        lst = Path(job["folder"]) / f"{job['name']}_parts.txt"
        lines = []
        for p in pieces:
            path = Path(sources[p["src"]]["path"]).as_posix().replace("'", "'\\''")
            lines += [f"file '{path}'", f"inpoint {p['start']:.3f}", f"outpoint {p['end']:.3f}"]
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        inputs, kind = [["-f", "concat", "-safe", "0", "-i", str(lst)]], "cutcopy"
    else:
        inputs, kind = _inputs_for(pieces, sources), "copy"
    maps = ["-map", "0:v:0"] + (["-map", "0:a?"] if acopy else ["-map", "0:a:0?"] if out_a else [])
    subs = main.get("subs") or []
    subs_ok = cont == "mkv" or (cont in ("mp4", "mov") and all(s["text"] for s in subs))
    if subs and whole and subs_ok:
        maps += ["-map", "0:s?"]
    elif subs:
        notes.append("its subtitle tracks were left out (they cannot go in this kind of file, or were cut)")
    if whole:
        notes.append(
            "copied the picture as it is (no quality lost)"
            + ("" if acopy or not out_a else f"; the sound was made {MD.CODEC_WORDS.get(enc_a, enc_a)}")
        )
    else:
        notes.append("cut without re-encoding (no quality lost)")
    opts = (["-movflags", "+faststart"] if cont in ("mp4", "mov") else []) + (
        ["-tag:v", "hvc1"] if mv["codec"] == "hevc" and cont in ("mp4", "mov") else []
    )
    job.update(
        kind=kind,
        inputs=inputs,
        maps=maps,
        venc=["-c:v", "copy"],
        aenc=["-c:a", "copy"] if acopy else aenc(enc_a, "high") if out_a else ["-an"],
        sub_enc=["-c:s", "mov_text"] if cont in ("mp4", "mov") else ["-c:s", "copy"],
        vsteps=None,
        asteps=None,
        opts=opts,
        ext=cont,
        mux=CONTAINERS[cont]["mux"],
        out=str(Path(job["folder"]) / f"{job['name']}.{cont}"),
        acodec=(src_a if acopy else enc_a) if out_a else None,
        vcodec=mv["codec"],
        w=mv["w"],
        h=mv["h"],
        fps=None,
        rate={"kind": "copy", "cap": cap},
        venc_name="copy",
    )
    if a_changes and out_a:  # the picture copied, the sound remade through its filters (replaced, levelled, moved in time)
        job.update(
            kind="vcopy",
            inputs=_inputs_for(pieces, sources),
            vsteps=None,
            maps=["-map", "0:v:0"],
            asteps=_asteps(S, job["D"], job["speed"], job),
            aenc=aenc(enc_a, "high", channels=1 if S.get("mono") else None),
            acodec=enc_a,
        )
        _pieces_in(job, sources, video=False)
        _audio_input(job, S, sources)
        notes[-1] = "copied the picture as it is (no quality lost) and remade the sound"
    job["expect"] = {
        "duration": job["D"],
        "video": True,
        "vcodec": mv["codec"],
        "w": mv["w"],
        "h": mv["h"],
        "fps": None,
        "audio": out_a,
        "acodec": job["acodec"],
        "max_bytes": cap,
        "faststart": cont in ("mp4", "mov"),
        "pix8": None,
        "copy": True,
        "tol": 0.3 if job["kind"] in ("copy", "vcopy") else 0.5 + 0.1 * len(pieces),
    }
    if (S.get("split") or {}).get("parts") or (S.get("split") or {}).get("every"):
        notes.append("the parts start at the nearest clean cut points, so their lengths differ a little")
    return job


def _split_times(sp, D):
    if sp.get("parts"):
        n = max(2, int(sp["parts"]))
        return [D * k / n for k in range(1, n)]
    if sp.get("every"):
        e = float(sp["every"])
        return [x * e for x in range(1, int(math.ceil(D / e))) if D - x * e > 0.5]
    return []


def split_times(sp, D):
    return _split_times(sp or {}, D)


def _subs_file(path, pieces, speed, folder):
    """Subtitles copied next to the work under a name of their own (the filter wants a plain name; the person's file is
    never written to) and moved onto the cut, sped-up timeline. None when no subtitle falls in the part kept."""
    p = Path(path).resolve()
    ext = p.suffix.lower()
    moved = len(pieces) > 1 or pieces[0]["start"] > 0.01 or speed != 1 or pieces[0]["src"] != 0
    out = folder / f"work_subs{ext if (ext in ('.srt', '.ass', '.ssa', '.vtt') and not moved) else '.srt'}"
    if out.resolve() == p:
        out = out.with_name(f"work_subs_2{out.suffix}")
    if not moved:
        shutil.copyfile(p, out)
        return out.name
    if ext not in (".srt", ".vtt"):
        raise PlanError("styled (ASS) subtitles cannot follow cuts yet; use an SRT file")
    new = []
    for a, b, text in _read_srt(p.read_text(encoding="utf-8-sig", errors="replace")):
        new += [(na, nb, text) for na, nb in _map_span(pieces, speed, a, b)]
    if not new:
        return None
    out.write_text("\n".join(f"{k + 1}\n{_srt_t(a)} --> {_srt_t(b)}\n{text}\n" for k, (a, b, text) in enumerate(new)), encoding="utf-8")
    return out.name


def _map_span(pieces, speed, a, b):
    """A cue's source times -> the output spans it survives as (cues in cut parts vanish)."""
    out, acc = [], 0.0
    for p in pieces:
        if p["src"] == 0:
            s, e = max(a, p["start"]), min(b, p["end"])
            if e - s > 0.05:
                out.append(((acc + s - p["start"]) / speed, (acc + e - p["start"]) / speed))
        acc += p["end"] - p["start"]
    return out


def _read_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if m:
            g = [int(x) for x in m.groups()]
            cues.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, block[m.end() :].strip("\n")))
    return cues


def _srt_t(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_frames(job, S, sources):
    pieces, speed, D = job["pieces"], job["speed"], job["D"]
    f = S["frames"] or {}
    fmt = "png" if f.get("fmt") == "png" else "jpg"
    mv = sources[pieces[0]["src"]]["video"]
    q = ["-q:v", "2"] if fmt == "jpg" else []
    rot = S["rotate"] % 360
    turns = (
        {90: ["transpose=1"], 270: ["transpose=2"], 180: ["hflip", "vflip"]}.get(rot, [])
        + (["hflip"] if S["hflip"] else [])
        + (["vflip"] if S["vflip"] else [])
    )
    w, h = (mv["h"], mv["w"]) if rot in (90, 270) else (mv["w"], mv["h"])
    folder = Path(job["folder"])
    job.update(kind="frames", asteps=None, rate={"kind": "frames"}, ext=fmt)
    if f.get("at") or f.get("best"):
        runs, outs = [], []
        times = [min(max(0.0, float(x)), max(0.0, D - 0.05)) for x in f.get("at") or []]
        for t in times:
            si, st = src_time(pieces, speed, t)
            o = folder / f"{job['name']}_at_{MD.mmss(t).replace(':', '-').replace('.', '_')}.{fmt}"
            runs.append(
                ["-ss", f"{st:.3f}", "-i", sources[si]["path"], "-frames:v", "1"] + (["-vf", ",".join(turns)] if turns else []) + q + [str(o)]
            )
            outs.append(str(o))
        if f.get("best"):  # the most typical frame of the middle of the video (FFmpeg's thumbnail filter)
            si, st = src_time(pieces, speed, D * 0.15)
            o = folder / f"{job['name']}_thumbnail.{fmt}"
            runs.append(
                [
                    "-ss",
                    f"{st:.3f}",
                    "-t",
                    f"{max(1.0, D * 0.7 * speed):.3f}",
                    "-i",
                    sources[si]["path"],
                    "-vf",
                    ",".join(turns + ["thumbnail=120"]),
                    "-frames:v",
                    "1",
                ]
                + q
                + [str(o)]
            )
            outs.append(str(o))
        job.update(runs=runs, frames_out=outs, out=outs[0], vsteps=None, expect={"images": len(outs), "w": w, "h": h})
        return job
    sheet = f.get("sheet")
    n = int(f.get("count") or (16 if sheet else 0))
    every = float(f["every"]) if f.get("every") else (D / n if n else 10.0)
    n = n or max(1, int(math.floor((D - 1e-3) / every)) + 1)
    if n > 400:
        raise PlanError(f"that would be {n} pictures; pick a longer gap")
    job["inputs"] = _inputs_for(pieces, sources)
    _pieces_in(job, sources, video=True)
    steps = ([("f", f"setpts=PTS/{speed:.6g}")] if speed != 1 else []) + [("f", x) for x in turns]
    if sheet:
        cols = 4
        rows = max(1, math.ceil(n / cols))
        tw = 480 if w >= h else 270
        steps += [("f", f"fps={n / max(D, 0.1):.6f}"), ("f", f"scale={tw}:-2"), ("f", f"tile={cols}x{rows}:padding=6:margin=6:color=white")]
        o = folder / f"{job['name']}_sheet.{fmt}"
        job.update(vsteps=steps, sheet=True, out=str(o), frames_out=[str(o)], venc=["-frames:v", "1"] + q, expect={"images": 1})
        return job
    sub = folder / f"{job['name']}_frames"
    sub.mkdir(exist_ok=True)
    steps.append(("f", f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{every:.4f})'"))
    job.update(
        vsteps=steps,
        sheet=False,
        pattern=str(sub / f"frame_%03d.{fmt}"),
        out=str(sub),
        venc=["-fps_mode", "vfr"] + q,
        expect={"images": n, "w": w, "h": h},
    )
    return job
