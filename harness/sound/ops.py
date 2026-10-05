"""Changes to a recording, each done by FFmpeg and each with its own measured check (like the photo agent's ops):

  info = run(op, src, dst, args, before)          before = measure.describe(src); dst is a 48 kHz 24-bit WAV
  checks = check(op, before, after, args, info)   after = measure.describe(dst); [{"ok", "what", "level"}]

Cleaning: denoise, dehum, highpass, deess, declick, declip, compress, normalize (a platform's loudness), volume, and
"clean" (the steps a recording needs, chosen from its measures, each one checked). Time: trim, cut, keep, fade,
tighten (long pauses shortened), fillers ('um', 'uh' cut, found by Whisper), speed, pitch. Mixing: music under the
voice with ducking, join. Effects: echo, reverb, telephone, mono, stereo. Time changes return the parts kept, so a
video and its captions can be cut the same way.
"""
import json
import math
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np

from . import measure as M

RATE = 48000
TARGETS = {"youtube": -14.0, "spotify": -14.0, "tiktok": -14.0, "instagram": -14.0, "facebook": -14.0, "podcast": -16.0, "apple": -16.0,
           "whatsapp": -16.0, "voice": -16.0, "audiobook": -19.0, "broadcast": -23.0, "tv": -23.0, "radio": -23.0}
FILLERS = {"um", "uh", "erm", "uhm", "umm", "uhh", "hmm", "mm", "ah", "eh", "er"}


class OpError(Exception):
    pass


def _c(ok, what, level="fail"):
    return {"ok": bool(ok), "what": what, "level": level}


def ff(inputs, dst, af=None, fc=None, maps=None, extra=(), rate=RATE):
    """One FFmpeg run to a 24-bit WAV (or what extra asks for). inputs: paths or arg lists (e.g. ['-stream_loop', '-1', '-i', p])."""
    args = ["ffmpeg", "-v", "error", "-y", "-nostdin"]
    for i in inputs:
        args += i if isinstance(i, list) else ["-i", str(i)]
    if af:
        args += ["-af", af]
    if fc:
        args += ["-filter_complex", fc]
    for m in maps or []:
        args += ["-map", m]
    args += ["-vn", "-ar", str(rate), "-c:a", "pcm_s24le", *extra, str(dst)]
    code, _, err = M.run(args)
    if code or not Path(dst).exists():
        raise OpError(f"FFmpeg: {err.strip()[-300:]}")


def _layout(m):
    return "mono" if (m.get("audio") or {}).get("channels", 1) == 1 else "stereo"


# ---------------------------------------------------------------- cleaning
def _denoise(src, dst, a, m):
    """Hum and rumble are noise to the person asking, and the hiss reducer cannot take them: they go first."""
    strength = a.get("strength", "medium")
    nr = {"light": 12, "medium": 20, "strong": 30}.get(strength, 20)
    pre, also = [], []
    if m.get("rumble_db", -99) > -25:
        pre.append("highpass=f=80,highpass=f=80")
        also.append("the rumble")
    hz = (m.get("hum") or {}).get("hz")
    if hz:
        pre.append(",".join(f"bandreject=f={hz * k}:width_type=h:width={1.5 if k <= 2 else 2.5}" for k in range(1, 9)))
        also.append(f"the {hz} Hz hum")
    floor = m.get("noise_db", -50)
    if pre:
        mid = Path(dst).with_suffix(".pre.wav")
        ff([src], mid, af=",".join(pre))
        floor = M.describe(mid, deep=False)["noise_db"]
        src = mid
    nf = max(-80, min(-20, round(floor + 5)))  # just above the measured floor: tracking it instead takes out far less
    ff([src], dst, af=f"afftdn=nr={nr}:nf={nf}")
    if pre:
        Path(src).unlink(missing_ok=True)
    return {"strength": strength, "nr": nr, "nf": nf, "also": also}


def _check_denoise(b, a, args, info):
    if b["noise_db"] < -70:
        return [_c(True, f"the recording was already quiet between words ({b['noise_db']:.0f} dB); nothing to take out")]
    need = {"light": 3, "medium": 5, "strong": 7}.get(info["strength"], 5)
    drop = b["noise_db"] - a["noise_db"]
    sp = a["speech_db"] - b["speech_db"]
    also = f" (with {' and '.join(info['also'])})" if info.get("also") else ""
    return [_c(drop >= need, f"background noise {b['noise_db']:.0f} -> {a['noise_db']:.0f} dB ({drop:.1f} dB quieter, wanted {need}+){also}"),
            _c(-3.5 <= sp <= 1.5, f"the voice kept its level ({sp:+.1f} dB)")]


def _dehum(src, dst, a, m):
    hz = a.get("hz") or (m.get("hum") or {}).get("hz") or 50
    notches = ",".join(f"bandreject=f={hz * k}:width_type=h:width={1.5 if k <= 2 else 2.5}" for k in range(1, 9))
    ff([src], dst, af=notches)
    return {"hz": hz, "found": (m.get("hum") or {}).get("hz")}


def _check_dehum(b, a, args, info):
    hb, ha = (b.get("hum") or {}).get("db", 0), (a.get("hum") or {}).get("db", 0)
    if not info["found"]:
        return [_c(ha < 10, f"no hum was there to remove ({hb:.0f} dB); none now ({ha:.0f} dB)")]
    return [_c(ha < 8 or hb - ha >= 15, f"{info['hz']} Hz hum {hb:.0f} -> {ha:.0f} dB above the sound around it"),
            _c(abs(a["speech_db"] - b["speech_db"]) <= 2.5, f"the voice kept its level ({a['speech_db'] - b['speech_db']:+.1f} dB)")]


def _highpass(src, dst, a, m):
    f = a.get("hz", 80)
    ff([src], dst, af=f"highpass=f={f},highpass=f={f}")
    return {"hz": f}


def _check_highpass(b, a, args, info):
    out = [_c(abs(a["speech_db"] - b["speech_db"]) <= 2.5, f"the voice kept its level ({a['speech_db'] - b['speech_db']:+.1f} dB)")]
    if b["rumble_db"] > -30:
        out.insert(0, _c(b["rumble_db"] - a["rumble_db"] >= 6, f"rumble under {info['hz']} Hz {b['rumble_db']:.0f} -> {a['rumble_db']:.0f} dB"))
    return out


def _deess(src, dst, a, m):
    i = {"light": 0.4, "medium": 0.6, "strong": 0.85}.get(a.get("strength", "medium"), 0.6)
    ff([src], dst, af=f"deesser=i={i}:m=0.5:f=0.5:s=o")
    return {"intensity": i}


def _check_deess(b, a, args, info):
    d = b["sibilance_db"] - a["sibilance_db"]
    if b["sibilance_db"] < -22:
        return [_c(d >= -0.5, f"the 's' sounds were not harsh ({b['sibilance_db']:.0f} dB); left as they were ({-d:+.1f} dB)")]
    return [_c(d >= 1.0, f"harsh 's' sounds {b['sibilance_db']:.1f} -> {a['sibilance_db']:.1f} dB")]


def clicks(path):
    """Sudden one-sample spikes per minute (pops and mouth clicks)."""
    y = M.load(path, sr=44100)
    if len(y) < 1000:
        return 0.0
    d2 = np.abs(np.diff(y, 2))
    thr = max(0.2, 8 * float(np.percentile(d2, 99)))
    hits = np.flatnonzero(d2 > thr)
    n = int((np.diff(hits) > 50).sum() + (1 if len(hits) else 0))
    return round(n / (len(y) / 44100 / 60), 1)


def _declick(src, dst, a, m):
    before = clicks(src)
    ff([src], dst, af="adeclick=w=55:o=75:t=2")
    return {"clicks_before": before, "clicks_after": clicks(dst)}


def _check_declick(b, a, args, info):
    cb, ca = info["clicks_before"], info["clicks_after"]
    if cb < 3:
        return [_c(ca <= cb + 1, f"there were hardly any clicks ({cb:.0f} a minute)")]
    return [_c(ca <= cb * 0.5, f"clicks {cb:.0f} -> {ca:.0f} a minute")]


def _declip(src, dst, a, m):
    ff([src], dst, af="volume=-3dB,adeclip=w=55:o=75:a=8:t=10:n=1000")
    return {}


def _check_declip(b, a, args, info):
    if b["clipped"] < 1e-4:
        return [_c(a["clipped"] <= b["clipped"] + 1e-4, "nothing was clipped")]
    return [_c(a["clipped"] <= b["clipped"] * 0.3, f"clipped samples {b['clipped']:.3%} -> {a['clipped']:.3%}")]


def _compress(src, dst, a, m):
    amt = a.get("amount", "medium")
    thr, ratio = {"light": (-20, 2), "medium": (-24, 3), "strong": (-28, 5)}.get(amt, (-24, 3))
    ff([src], dst, af=f"acompressor=threshold={thr}dB:ratio={ratio}:attack=10:release=200:makeup=2:knee=4")
    return {"amount": amt, "threshold": thr, "ratio": ratio}


def spread(path):
    """How much the voice's level wanders: 90th - 40th percentile of the frames that are not silence (dB)."""
    y = M.load(path)
    db = M.frames_db(y)
    s = db[db > np.percentile(db, 90) - 30]
    return round(float(np.percentile(s, 90) - np.percentile(s, 40)), 2) if len(s) > 10 else 0.0


def _check_compress(b, a, args, info):
    sb, sa = b.get("_spread") or 0, a.get("_spread") or 0
    return [_c(sa <= sb - 0.7 or (b.get("lra") or 0) - (a.get("lra") or 0) >= 0.7, f"the level evens out: spread {sb:.1f} -> {sa:.1f} dB, "
               f"loudness range {b.get('lra') or 0:.1f} -> {a.get('lra') or 0:.1f} LU")]


def _loudnorm_pass1(src, target, tp, lra):
    code, _, err = M.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af", f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json",
                          "-f", "null", "-"])
    js = err[err.rfind("{"):err.rfind("}") + 1]
    return json.loads(js)


def _normalize(src, dst, a, m):
    target = float(a.get("lufs") or TARGETS.get(a.get("platform", "podcast"), -16.0))
    tp = float(a.get("tp", -1.5))
    lra = 11 if target > -20 else 15
    p1 = _loudnorm_pass1(src, target, tp, lra)
    af = (f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={p1['input_i']}:measured_TP={p1['input_tp']}:measured_LRA={p1['input_lra']}"
          f":measured_thresh={p1['input_thresh']}:offset={p1['target_offset']}:linear=true")
    ff([src], dst, af=af)
    after = M.loudness(dst)
    if abs(after["lufs"] - target) > 0.8:  # dynamic mode left it off target (a very peaky file): one more gain step, then a limiter
        tmp = Path(dst).with_suffix(".n2.wav")
        g = target - after["lufs"]
        ff([dst], tmp, af=f"volume={g:.2f}dB,alimiter=limit={10 ** (tp / 20):.4f}:level=disabled")
        shutil.move(tmp, dst)
    return {"target": target, "tp": tp, "platform": a.get("platform")}


def _check_normalize(b, a, args, info):
    return [_c(abs(a["lufs"] - info["target"]) <= 1.0, f"loudness {b['lufs']:.1f} -> {a['lufs']:.1f} LUFS (target {info['target']:g}"
               + (f" for {info['platform']}" if info.get("platform") else "") + ")"),
            _c((a["true_peak"] if a["true_peak"] is not None else -99) <= info["tp"] + 0.5, f"true peak {a['true_peak']} dBTP (at most {info['tp']:g})")]


def _volume(src, dst, a, m):
    db = float(a.get("db", 6))
    ff([src], dst, af=f"volume={db:.2f}dB,alimiter=limit=0.891:level=disabled")
    return {"db": db}


def _check_volume(b, a, args, info):
    ch = a["lufs"] - b["lufs"]
    want = info["db"]
    ok = (abs(ch - want) <= 1.5) or (want > 0 and ch >= min(want, 2) and (a["true_peak"] or 0) <= -0.5)
    return [_c(ok, f"loudness {b['lufs']:.1f} -> {a['lufs']:.1f} LUFS ({ch:+.1f} dB, asked {want:+g})"),
            _c((a["true_peak"] if a["true_peak"] is not None else -99) <= -0.4, f"no clipping (true peak {a['true_peak']} dBTP)")]


# ---------------------------------------------------------------- time
def segments_filter(segs, label="0:a", fade=0.008):
    parts = []
    for i, (s, e) in enumerate(segs):
        d = e - s
        f = min(fade, d / 4)
        parts.append(f"[{label}]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS,afade=t=in:d={f:.4f},afade=t=out:st={max(0, d - f):.4f}:d={f:.4f}[s{i}]")
    return ";".join(parts) + ";" + "".join(f"[s{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[out]"


def keep_segments(src, dst, segs):
    segs = [(max(0.0, a), b) for a, b in segs if b - a > 0.02]
    if not segs:
        raise OpError("that would leave nothing")
    ff([src], dst, fc=segments_filter(segs), maps=["[out]"])
    return segs


def _complement(cuts, dur):
    keep, t = [], 0.0
    for a, b in sorted((max(0, a), min(dur, b)) for a, b in cuts):
        if a > t:
            keep.append((t, a))
        t = max(t, b)
    if t < dur:
        keep.append((t, dur))
    return keep


def _trim(src, dst, a, m):
    dur = m["duration"]
    s = float(a.get("start", 0) or 0)
    e = float(a["end"]) if a.get("end") is not None else dur - float(a.get("drop_end", 0) or 0)
    if e - s < 0.1:
        raise OpError("that would leave nothing")
    segs = keep_segments(src, dst, [(s, min(e, dur))])
    return {"keep": segs, "expect": segs[0][1] - segs[0][0]}


def _cut(src, dst, a, m):
    dur = m["duration"]
    cuts = [(float(x), float(y)) for x, y in a["ranges"]]
    if any(x >= dur for x, _ in cuts):
        raise OpError(f"the recording is only {dur:.1f} s long")
    keep = _complement(cuts, dur)
    segs = keep_segments(src, dst, keep)
    return {"keep": segs, "expect": sum(b - a for a, b in segs)}


def _keep(src, dst, a, m):
    s, e = float(a["start"]), min(float(a["end"]), m["duration"])
    segs = keep_segments(src, dst, [(s, e)])
    return {"keep": segs, "expect": e - s}


def _check_time(b, a, args, info):
    return [_c(abs(a["duration"] - info["expect"]) <= 0.08, f"{b['duration']:.2f} s -> {a['duration']:.2f} s (expected {info['expect']:.2f})")]


def _fade(src, dst, a, m):
    fi, fo = float(a.get("in", 0) or 0), float(a.get("out", 0) or 0)
    d = m["duration"]
    parts = ([f"afade=t=in:st=0:d={fi:.3f}"] if fi else []) + ([f"afade=t=out:st={max(0, d - fo):.3f}:d={fo:.3f}"] if fo else [])
    if not parts:
        raise OpError("say how long the fade is")
    ff([src], dst, af=",".join(parts))
    return {"in": fi, "out": fo}


def _edge_db(path, at_start, span=0.03):
    p = M.probe(path)
    y = M.load(path, sr=RATE, start=0 if at_start else max(0, p["duration"] - span), dur=span)
    return 20 * math.log10(max(float(np.sqrt((y.astype(np.float64) ** 2).mean())) if len(y) else 0, 1e-6))


def _check_fade(b, a, args, info, path=None):
    out = []
    if info["in"]:
        out.append(_c(a["_start_db"] <= -45, f"fades in from silence ({a['_start_db']:.0f} dB at the start)"))
    if info["out"]:
        out.append(_c(a["_end_db"] <= -45, f"fades out to silence ({a['_end_db']:.0f} dB at the end)"))
    return out


def _tighten(src, dst, a, m):
    mx = float(a.get("max_pause", 0.5))
    long_ = [(s, e) for s, e in m.get("pauses", []) if e - s > mx + 0.05]
    level = {"floor": m["noise_db"], "speech": m["speech_db"]}  # the pause threshold, kept for the check (a re-measured one drifts)
    if not long_:
        shutil.copy(src, dst)
        return {"keep": [(0.0, m["duration"])], "removed": 0.0, "max_pause": mx, "count": 0, "level": level}
    cuts = [(s + mx / 2, e - mx / 2) for s, e in long_]
    keep = _complement(cuts, m["duration"])
    segs = keep_segments(src, dst, keep)
    return {"keep": segs, "removed": round(sum(e - s for s, e in cuts), 2), "max_pause": mx, "count": len(cuts), "expect": sum(b - a for a, b in segs), "level": level}


def _check_tighten(b, a, args, info):
    if not info["count"]:
        return [_c(True, f"no pause was longer than {info['max_pause']:g} s")]
    lv = info.get("level") or {"floor": b["noise_db"], "speech": b["speech_db"]}
    after = M.pauses(M.frames_db(M.load(a["_path"])), lv["floor"], lv["speech"])  # measured against the same threshold as before
    longest = max((e - s for s, e in after), default=0.0)
    sb = b["duration"] - sum(e - s for s, e in b.get("pauses", []))
    sa = a["duration"] - sum(e - s for s, e in after)
    return [_c(longest <= info["max_pause"] + 0.2, f"{info['count']} long pause(s) shortened: the longest is now {longest:.2f} s "
               f"(was {b['longest_pause']:.2f})"),
            _c(abs(a["duration"] - info["expect"]) <= 0.1, f"{info['removed']:.1f} s of silence taken out ({b['duration']:.1f} -> {a['duration']:.1f} s)"),
            _c(abs(sa - sb) <= max(0.4, 0.05 * sb), f"all the speech kept ({sb:.1f} s -> {sa:.1f} s of sound)")]


def _fillers(src, dst, a, m):
    words = transcribe_words(src, verbatim=True)
    hits = [w for w in words if _norm(w["w"]) in FILLERS]
    if not hits:
        shutil.copy(src, dst)
        return {"keep": [(0.0, m["duration"])], "count": 0, "words_before": len(words), "found": []}
    cuts = []
    for w in hits:  # the filler and the breath around it, never into the next word
        i = words.index(w)
        lo = max(w["start"] - 0.05, words[i - 1]["end"] + 0.02 if i > 0 else 0.0)
        hi = min(w["end"] + 0.08, words[i + 1]["start"] - 0.02 if i + 1 < len(words) else m["duration"])
        if hi > lo:
            cuts.append((lo, hi))
    keep = _complement(cuts, m["duration"])
    segs = keep_segments(src, dst, keep)
    return {"keep": segs, "count": len(cuts), "words_before": len(words) - len(hits), "found": [w["w"] for w in hits], "expect": sum(b - a for a, b in segs)}


def _check_fillers(b, a, args, info):
    if not info["count"]:
        return [_c(True, "no 'um' or 'uh' was heard")]
    words = transcribe_words(a["_path"], verbatim=True)
    left = [w["w"] for w in words if _norm(w["w"]) in FILLERS]
    kept = len(words) - len(left)
    return [_c(len(left) <= max(0, info["count"] // 4), f"{info['count']} filler(s) cut ({', '.join(info['found'][:6])}); {len(left)} still heard"),
            _c(kept >= info["words_before"] - max(1, info["words_before"] // 20), f"the other words kept ({info['words_before']} -> {kept})")]


def _speed(src, dst, a, m):
    f = float(a.get("factor", 1.25))
    if not 0.25 <= f <= 4:
        raise OpError("speed must be between 0.25x and 4x")
    ff([src], dst, af=f"rubberband=tempo={f:.4f}:pitch=1:transients=crisp")
    return {"factor": f, "keep": [(0.0, m["duration"])], "speed": f, "expect": m["duration"] / f}


def _check_speed(b, a, args, info):
    out = [_c(abs(a["duration"] - info["expect"]) <= max(0.1, 0.02 * info["expect"]), f"{b['duration']:.1f} s -> {a['duration']:.1f} s at {info['factor']:g}x")]
    if b.get("pitch_hz") and a.get("pitch_hz"):
        r = a["pitch_hz"] / b["pitch_hz"]
        out.append(_c(0.9 <= r <= 1.1, f"the voice's pitch kept ({b['pitch_hz']:.0f} -> {a['pitch_hz']:.0f} Hz)"))
    return out


def _pitch(src, dst, a, m):
    st = float(a.get("semitones", -3))
    ratio = 2 ** (st / 12)
    ff([src], dst, af=f"rubberband=pitch={ratio:.5f}:formant={'preserved' if a.get('natural', True) else 'shifted'}")
    return {"semitones": st, "ratio": ratio}


def _check_pitch(b, a, args, info):
    out = [_c(abs(a["duration"] - b["duration"]) <= 0.05 * b["duration"] + 0.05, f"length kept ({b['duration']:.1f} -> {a['duration']:.1f} s)")]
    if b.get("pitch_hz") and a.get("pitch_hz"):
        r = a["pitch_hz"] / b["pitch_hz"]
        out.append(_c(abs(math.log2(r) * 12 - info["semitones"]) <= 1.5, f"pitch {b['pitch_hz']:.0f} -> {a['pitch_hz']:.0f} Hz ({math.log2(r) * 12:+.1f} semitones, "
                      f"asked {info['semitones']:+g})"))
    return out


# ---------------------------------------------------------------- mixing
def _music(src, dst, a, m):
    music = Path(a["file"])
    if not music.exists():
        raise OpError(f"no music file {music.name}")
    d = m["duration"]
    mm = M.loudness(music)
    bed = float(a.get("below", 18))  # dB under the voice
    gain = (m["lufs"] - bed) - mm["lufs"]
    lay = _layout(m)
    fo = min(3.0, d / 4)
    duck = a.get("duck", True)
    fc = (f"[1:a]atrim=0:{d:.3f},asetpts=PTS-STARTPTS,aresample={RATE},aformat=channel_layouts={lay},volume={gain:.2f}dB,"
          f"afade=t=in:d={min(1.5, d / 6):.2f},afade=t=out:st={max(0, d - fo):.3f}:d={fo:.2f}[m];"
          f"[0:a]aresample={RATE},aformat=channel_layouts={lay},asplit=2[v][sc];")
    if duck:
        fc += "[m][sc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=450:makeup=1[md];"
    else:
        fc += "[m]anull[md];[sc]anullsink;"
    fc += "[md]asplit=2[md1][md2];[v][md1]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.891:level=disabled[out]"
    stem = Path(dst).with_suffix(".music.wav")
    args = ["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(src), "-stream_loop", "-1", "-i", str(music), "-filter_complex", fc,
            "-map", "[out]", "-ar", str(RATE), "-c:a", "pcm_s24le", str(dst), "-map", "[md2]", "-ar", str(RATE), "-c:a", "pcm_s24le", str(stem)]
    code, _, err = M.run(args)
    if code:
        raise OpError(f"FFmpeg: {err.strip()[-300:]}")
    return {"file": music.name, "below": bed, "gain": round(gain, 1), "duck": duck, "stem": str(stem), "voice_pauses": m.get("pauses", [])}


def _check_music(b, a, args, info):
    out = [_c(abs(a["duration"] - b["duration"]) <= 0.08, f"length kept ({a['duration']:.1f} s)"),
           _c((a["true_peak"] if a["true_peak"] is not None else -99) <= -0.4, f"no clipping (true peak {a['true_peak']} dBTP)")]
    pz = [(s + 0.25, e - 0.1) for s, e in info["voice_pauses"] if e - s >= 0.8]
    talk = _complement([(s, e) for s, e in info["voice_pauses"]], b["duration"])
    under = M.level_db(info["stem"], talk)
    out.append(_c(b["speech_db"] - under >= 10, f"the voice stays on top: music {b['speech_db'] - under:.0f} dB under it while talking"))
    if info["duck"] and pz:
        free = M.level_db(info["stem"], pz)
        out.append(_c(free - under >= 5, f"the music dips {free - under:.0f} dB while the voice talks and comes back in the pauses"))
    return out


def _join(src, dst, a, m):
    other = Path(a["file"])
    if not other.exists():
        raise OpError(f"no file {other.name}")
    lay = _layout(m)
    x = float(a.get("crossfade", 0) or 0)
    pre = f"[0:a]aresample={RATE},aformat=channel_layouts={lay}[a0];[1:a]aresample={RATE},aformat=channel_layouts={lay}[a1];"
    fc = pre + (f"[a0][a1]acrossfade=d={x:.2f}[out]" if x else "[a0][a1]concat=n=2:v=0:a=1[out]")
    od = M.probe(other)["duration"]
    first = not a.get("before")
    ins = [src, other] if first else [other, src]
    ff(ins, dst, fc=fc, maps=["[out]"])
    return {"file": other.name, "expect": m["duration"] + od - x, "other": od, "first": first}


def _check_join(b, a, args, info):
    return [_c(abs(a["duration"] - info["expect"]) <= 0.12, f"{b['duration']:.1f} s + {info['other']:.1f} s -> {a['duration']:.1f} s")]


# ---------------------------------------------------------------- effects
def _echo(src, dst, a, m):
    ff([src], dst, af="aecho=0.8:0.7:280|560:0.35|0.18")
    return {}


def _reverb(src, dst, a, m):
    ff([src], dst, af="aecho=0.8:0.85:43|71|97|131:0.32|0.26|0.21|0.16,highpass=f=60")
    return {}


def _check_tail(b, a, args, info):
    pb = [(s + 0.05, min(e, s + 0.6)) for s, e in b.get("pauses", []) if e - s > 0.3]
    if not pb:
        return [_c(True, "added (no pause to hear it in)")]
    lb, la = M.level_db(b["_path"], pb), M.level_db(a["_path"], pb)
    return [_c(la - lb >= 6, f"the sound now rings on into the pauses ({lb:.0f} -> {la:.0f} dB just after the words)")]


def _telephone(src, dst, a, m):
    ff([src], dst, af="highpass=f=320,highpass=f=320,lowpass=f=3300,lowpass=f=3300,acompressor=threshold=-20dB:ratio=4")
    return {}


def _check_telephone(b, a, args, info):
    return [_c(b["telephone_db"] - a["telephone_db"] >= 10, f"the sound outside 300-3400 Hz cut by {b['telephone_db'] - a['telephone_db']:.0f} dB")]


def _channels(n):
    def go(src, dst, a, m):
        ff([src], dst, extra=["-ac", str(n)])
        return {"channels": n}
    return go


def _check_channels(b, a, args, info):
    return [_c(a["audio"]["channels"] == info["channels"], f"{a['audio']['channels']} channel(s)")]


# ---------------------------------------------------------------- the whole clean-up
def plan_clean(m, target=None, platform=None):
    """The steps a voice recording needs, from its measures, each with the reason."""
    steps = []
    if m.get("rumble_db", -99) > -25:
        steps.append(("highpass", {"hz": 80}, f"rumble under 80 Hz ({m['rumble_db']:.0f} dB)"))
    if (m.get("hum") or {}).get("hz"):
        steps.append(("dehum", {"hz": m["hum"]["hz"]}, f"{m['hum']['hz']} Hz hum ({m['hum']['db']:.0f} dB)"))
    if m.get("clipped", 0) > 1e-4:
        steps.append(("declip", {}, f"clipped peaks ({m['clipped']:.2%})"))
    snr = m.get("snr_db", 99)
    if m.get("noise_db", -99) > -60 and snr < 40:
        st = "strong" if snr < 15 else "medium" if snr < 26 else "light"
        steps.append(("denoise", {"strength": st}, f"background noise {snr:.0f} dB under the voice"))
    if m.get("sibilance_db", -99) > -14:
        steps.append(("deess", {"strength": "medium"}, f"harsh 's' sounds ({m['sibilance_db']:.0f} dB)"))
    if (m.get("lra") or 0) > 9:
        steps.append(("compress", {"amount": "light"}, f"the level wanders ({m['lra']:.0f} LU)"))
    steps.append(("normalize", {"platform": platform or "podcast", **({"lufs": target} if target else {})},
                  f"loudness {m['lufs']:.0f} LUFS -> {target or TARGETS.get(platform or 'podcast', -16):g}"))
    return steps


def _clean(src, dst, a, m):
    steps = plan_clean(m, a.get("lufs"), a.get("platform"))
    done, cur, cur_m = [], Path(src), m
    tmpd = Path(tempfile.mkdtemp(prefix="clean_", dir=Path(dst).parent))
    try:
        for k, (op, args, why) in enumerate(steps):
            nxt = tmpd / f"s{k}.wav"
            info = run(op, cur, nxt, args, cur_m)
            after = describe(nxt, op)
            chk = check(op, cur_m, after, args, info)
            done.append({"op": op, "why": why, "checks": chk})
            cur, cur_m = nxt, after
        shutil.copy(cur, dst)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    return {"steps": done}


def _check_clean(b, a, args, info):
    out = []
    for s in info["steps"]:
        for c in s["checks"]:
            out.append(dict(c, what=f"{s['op']}: {c['what']}"))
    return out


# ---------------------------------------------------------------- speech words (Whisper)
def _norm(w):
    return re.sub(r"[^\w']", "", w.lower())


_VERBATIM = "Umm, let me think, uh, like, hmm... Okay, so, um, here's what I'm, uh, thinking."


def transcribe_words(path, verbatim=False, language=None):
    """Words with times from the local Whisper (models/whisper/base); with verbatim=True it keeps 'um' and 'uh'."""
    from .. import speech
    if not speech.available():
        raise OpError("the speech model is missing (models/whisper/base)")
    y = M.load(path, sr=16000)
    if len(y) < 16000 * 0.3:
        return []
    segs, info = speech._load().transcribe(y, language=language, word_timestamps=True, vad_filter=False, beam_size=5,
                                           condition_on_previous_text=False, initial_prompt=_VERBATIM if verbatim else None)
    out = []
    for s in segs:
        for w in s.words or []:
            out.append({"w": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3), "prob": round(float(w.probability), 3)})
    return out


# ---------------------------------------------------------------- the table
OPS = {
    "clean": (_clean, _check_clean, "clean up the recording"),
    "denoise": (_denoise, _check_denoise, "reduce the background noise"),
    "dehum": (_dehum, _check_dehum, "remove mains hum"),
    "highpass": (_highpass, _check_highpass, "cut rumble"),
    "deess": (_deess, _check_deess, "soften harsh 's' sounds"),
    "declick": (_declick, _check_declick, "remove clicks"),
    "declip": (_declip, _check_declip, "repair clipped peaks"),
    "compress": (_compress, _check_compress, "even out the level"),
    "normalize": (_normalize, _check_normalize, "set the loudness"),
    "volume": (_volume, _check_volume, "louder or quieter"),
    "trim": (_trim, _check_time, "trim the start or end"),
    "cut": (_cut, _check_time, "cut out a part"),
    "keep": (_keep, _check_time, "keep only a part"),
    "fade": (_fade, _check_fade, "fade in or out"),
    "tighten": (_tighten, _check_tighten, "shorten long pauses"),
    "fillers": (_fillers, _check_fillers, "cut 'um' and 'uh'"),
    "speed": (_speed, _check_speed, "speed up or slow down"),
    "pitch": (_pitch, _check_pitch, "a higher or deeper voice"),
    "music": (_music, _check_music, "background music under the voice"),
    "join": (_join, _check_join, "add another recording"),
    "echo": (_echo, _check_tail, "echo"),
    "reverb": (_reverb, _check_tail, "room reverb"),
    "telephone": (_telephone, _check_telephone, "telephone / radio voice"),
    "mono": (_channels(1), _check_channels, "mono"),
    "stereo": (_channels(2), _check_channels, "stereo"),
}
TIME_OPS = {"trim", "cut", "keep", "tighten", "fillers", "speed", "join"}


def run(op, src, dst, args, before):
    if op not in OPS:
        raise OpError(f"unknown change {op}")
    return OPS[op][0](Path(src), Path(dst), dict(args or {}), before)


def describe(path, op=None):
    """The measures a check needs (the costly ones only for the ops that use them)."""
    m = M.describe(path)
    m["_path"] = str(path)
    if op in ("compress",):
        m["_spread"] = spread(path)
    if op in ("fade",):
        m["_start_db"], m["_end_db"] = _edge_db(path, True), _edge_db(path, False)
    return m


def check(op, before, after, args, info):
    if op == "compress" and "_spread" not in before:
        before["_spread"] = spread(before["_path"])
    return OPS[op][1](before, after, args or {}, info)
