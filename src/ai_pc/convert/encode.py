"""Running the work: FFmpeg without a window, with a time limit and progress; the measuring passes a job needs first
(shake detection, loudness); the search for 'smaller at the same look'; a size forecast from samples before a long
encode; a second try when a file comes out over its size limit or the GPU encoder fails; splitting into parts; and the
checks on what was made: it plays through, its length, size, picture and sound are what was asked, and how close it
looks to the original (VMAF, both pictures on one frame clock so frames are compared with their true partners).

  r = render(chain, sources, folder, name, log=print)
      -> {"outputs": [paths], "kind", "notes", "checks", "quality", "seconds", "size", "probe", "status": "ok" | "no_gain"}
"""
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from ai_pc.convert import media as MD
from ai_pc.convert import plan as P
from ai_pc.convert.presets import ENCODERS, MPX_PER_S, QUALITY, SAME_VMAF
from ai_pc.core.config import STATE

NO_WINDOW = 0x08000000
CAPS_FILE = STATE / "convert_caps.json"
_CAPS = None


class EncodeError(RuntimeError):
    pass


def caps():
    """Which Intel GPU encoders work on this PC (tested once per FFmpeg version, remembered in state/)."""
    global _CAPS
    if _CAPS is not None:
        return _CAPS
    code, out, _ = MD.run(["ffmpeg", "-hide_banner", "-version"], timeout=30)
    ver = out.decode("utf-8", "replace").splitlines()[0] if out else "?"
    try:
        saved = json.loads(CAPS_FILE.read_text(encoding="utf-8"))
        if saved.get("ffmpeg") == ver:
            _CAPS = saved["caps"]
            return _CAPS
    except (OSError, ValueError, KeyError):
        pass
    found = {}
    for enc in ("h264_qsv", "av1_qsv", "hevc_qsv", "vp9_qsv"):
        c, _, _ = MD.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30", "-frames:v", "8", "-c:v", enc,
                          "-f", "null", "-"], timeout=60)
        found[enc] = c == 0
    CAPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CAPS_FILE.write_text(json.dumps({"ffmpeg": ver, "caps": found}, indent=1), encoding="utf-8")
    _CAPS = found
    return found


def ff(args, cwd=None, timeout=900, total=None, log=None, label="working", level="error"):
    """FFmpeg with a watchdog and progress lines ('encoding 40%') on long runs: (returncode, stderr text)."""
    cmd = ["ffmpeg", "-hide_banner", "-y", "-nostdin", "-v", level, "-progress", "pipe:1", "-nostats"] + [str(a) for a in args]
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    err = []
    t_err = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)
    t_err.start()
    dog = threading.Timer(timeout, p.kill)
    dog.start()
    t0, shown = time.time(), 0.0
    try:
        for line in iter(p.stdout.readline, b""):
            m = re.match(rb"out_time_us=(\d+)", line)
            if m and total and log:
                done = int(m.group(1)) / 1e6 / total
                if done - shown >= 0.2 and time.time() - t0 > 10:
                    log(f"  {label} {min(done, 0.99):.0%}")
                    shown = done
        p.wait()
    finally:
        dog.cancel()
    t_err.join(timeout=10)
    text = b"".join(x for x in err if x).decode("utf-8", "replace")
    if time.time() - t0 >= timeout - 1:
        text += f"\n(stopped after {timeout} s)"
    return p.returncode, text


def _timeout(job):
    D = job.get("D") or 60
    enc = job.get("venc_name") or "libx264"
    mpx = (job.get("w") or 1280) * (job.get("h") or 720) * (job.get("fps") or 30) * D / 1e6
    return int(max(300, mpx / MPX_PER_S.get(enc, 100) * 6 + D * 2))


def command(job, out=None, passn=None):
    """The FFmpeg arguments for a job (without 'ffmpeg -y ...')."""
    out = str(out or job["out"])
    args = [x for i in job["inputs"] for x in i]
    kind = job["kind"]
    if kind in ("copy", "cutcopy"):
        args += job["maps"] + job["venc"] + job["aenc"] + (job.get("sub_enc") or [] if "0:s?" in job["maps"] else []) + job["opts"]
        return args + ["-f", job["mux"], out]
    if kind == "vcopy":  # the picture copied, the sound through the graph
        text, _, al = P.graph(job, "encode")
        return args + ["-filter_complex", text] + job["maps"] + ["-map", f"[{al}]"] + job["venc"] + job["aenc"] + job["opts"] + ["-f", job["mux"], out]
    text, vl, al = P.graph(job, "ref" if passn == 1 else "encode")  # the measuring pass of two takes the picture only
    args += ["-filter_complex", text]
    if vl:
        args += ["-map", f"[{vl}]"]
    if al and passn != 1:
        args += ["-map", f"[{al}]"]
    if kind == "frames":
        if job.get("sheet"):
            return args + job["venc"] + ["-update", "1", out]
        return args + job["venc"] + ["-f", "image2", job["pattern"]]
    if job.get("subs_in") and passn != 1:
        args += ["-map", f"{job['subs_in']['idx']}:s:0", "-c:s", job["subs_in"]["codec"]]
    args += job["venc"]
    if passn:
        args += ["-pass", str(passn), "-passlogfile", "pass"]
    if passn == 1:
        return args + ["-an", "-f", "null", "-"]
    args += (job["aenc"] if al else []) + job["opts"]
    return args + ["-f", job["mux"], out]


def _pre(job, log):
    """The passes a job needs before it is made: shake detection (stabilize) and the loudness measure (normalize)."""
    cwd = job["folder"]
    if "stab" in job["pre"]:
        text, vl, _ = P.graph(job, "stab")
        code, err = ff([x for i in job["inputs"] for x in i] + ["-filter_complex", text, "-map", f"[{vl}]", "-f", "null", "-"], cwd=cwd,
                       timeout=_timeout(job), total=job["D"], log=log, label="finding the shake")
        if code:
            raise EncodeError(f"shake detection failed: {err.strip()[-200:]}")
    if "loud" in job["pre"]:
        text, _, al = P.graph(job, "loud")
        code, err = ff([x for i in job["inputs"] for x in i] + ["-filter_complex", text, "-map", f"[{al}]", "-f", "null", "-"], cwd=cwd,
                       timeout=_timeout(job), level="info")
        m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
        if code or not m:
            raise EncodeError("the loudness measure failed")
        d = json.loads(m.group(0))
        ln = (f"loudnorm=I={job['loud_target']}:TP=-1.5:LRA=11:measured_I={d['input_i']}:measured_TP={d['input_tp']}:measured_LRA={d['input_lra']}"
              f":measured_thresh={d['input_thresh']}:offset={d['target_offset']}:linear=true")
        job["asteps"] = [ln if s.startswith("loudnorm") else s for s in job["asteps"]]
        job["loud_before"] = float(d["input_i"])


def _make(job, log, out=None):
    """One job made: two passes for x264 at a bitrate, else one; frames as their own runs."""
    cwd = job["folder"]
    if job["kind"] == "frames" and job.get("runs"):
        for r in job["runs"]:
            code, err = ff(r, cwd=cwd, timeout=120)
            if code:
                return code, err
        return 0, ""
    two = job.get("venc_name") in ("libx264", "libvpx-vp9") and (job.get("rate") or {}).get("kind") == "bitrate"
    if two:
        code, err = ff(command(job, out, passn=1), cwd=cwd, timeout=_timeout(job), total=job["D"], log=log, label="measuring")
        if code:
            return code, err
    code, err = ff(command(job, out, passn=2 if two else None), cwd=cwd, timeout=_timeout(job), total=job["D"], log=log,
                   label={"encode": "encoding", "copy": "copying", "cutcopy": "copying", "audio": "saving the sound", "gif": "making the GIF"}.get(job["kind"], "working"))
    for f in Path(cwd).glob("pass*.log*"):
        f.unlink(missing_ok=True)
    return code, err


# ---------------------------------------------------------------- quality
def vmaf(job, out_path, a=None, b=None, ref_job=None):
    """How close the output looks to what it should be (0-100), the reference being the same pieces through the same
    picture filters, not encoded. a..b: only that stretch of the output (ref_job is then built for it)."""
    rj = ref_job or job
    text, vl, _ = P.graph(rj, "ref")
    di = len(rj["inputs"])
    out_in = (["-ss", f"{max(0.0, a - 0.0005):.6f}", "-t", f"{b - a:.6f}"] if a is not None else []) + ["-i", str(out_path)]
    p = MD.probe(out_path)
    fps = (p.get("video") or {}).get("r_fps") or (p.get("video") or {}).get("fps") or 25
    frames = (b - a if a is not None else job["D"]) * fps
    sub = max(1, int(frames / 240))
    down = ",scale=-2:1080:flags=bicubic" if (p.get("video") or {}).get("h", 0) > 1080 and (p.get("video") or {}).get("w", 0) > 1080 else ""
    lav = (f"{text};[{vl}]setpts=PTS-STARTPTS,fps={fps:.5f},format=yuv420p{down}[r];"
           f"[{di}:v:0]setpts=PTS-STARTPTS,fps={fps:.5f},format=yuv420p{down}[d];[d][r]libvmaf=n_subsample={sub}:n_threads={os.cpu_count() or 4}")
    code, err = ff([x for i in rj["inputs"] for x in i] + out_in + ["-filter_complex", lav, "-f", "null", "-"], cwd=rj["folder"], timeout=900, level="info")
    m = re.search(r"VMAF score:\s*([\d.]+)", err)
    return float(m.group(1)) if m else None


def _windows(D, n=3, length=6.0, fps=None, starts=(0.0,)):
    """Stretches of the output to sample: (a, b) seconds, each starting on the frame grid of the piece it falls in
    (starts: where each piece begins in the output), so an output frame and its reference frame are the same moment."""
    if D <= length * n + 2:
        return [(0.0, D)]
    out = []
    for f in (0.2, 0.5, 0.8)[:n]:
        a = max(0.0, D * f - length / 2)
        if fps:
            s0 = max(x for x in starts if x <= a + 1e-9)
            a = s0 + round((a - s0) * fps) / fps
        out.append((a, min(D, a + length)))
    return out


def _starts(job):
    acc, out = 0.0, []
    for p in job["pieces"]:
        out.append(acc / job["speed"])
        acc += p["end"] - p["start"]
    return out


def _quality(job, out, S, sources, caps_, folder):
    """VMAF of the whole output when it is short, else of three 6 s stretches; None when it does not apply."""
    if job["kind"] != "encode" or not out:
        return None
    if job["D"] <= 75:
        return vmaf(job, out)
    if job.get("pre") and "stab" in job["pre"]:
        return None  # the shake fix is worked out over the whole video; a stretch of it would not match
    tmp = Path(folder) / "_ref"
    tmp.mkdir(exist_ok=True)
    scores = []
    fps = job.get("fps") or (MD.probe(out).get("video") or {}).get("r_fps")
    for k, (a, b) in enumerate(_windows(job["D"], fps=fps, starts=_starts(job))):
        S2 = dict(S, fade_in=0.0, fade_out=0.0, split=None, max_mb=None, percent=None, same=False)
        rj = P.build(S2, P.window(job["pieces"], job["speed"], a, b), job["speed"], sources, tmp, caps_,
                     {"encode": True, "q": 20, "dims": (job["w"], job["h"], job["fps"])}, name=f"r{k}")
        v = vmaf(job, out, a, b, ref_job=rj)
        if v is not None:
            scores.append((v, b - a))
    shutil.rmtree(tmp, ignore_errors=True)
    return sum(v * d for v, d in scores) / sum(d for _, d in scores) if scores else None


# ---------------------------------------------------------------- checks
def _check(what, ok, detail="", level="fail"):
    return {"what": what, "ok": bool(ok), "level": "info" if ok else level, "detail": detail}


def verify(job, outputs):
    """What was made, read back: it plays through, and its length, size, picture and sound are what was asked."""
    exp = job.get("expect") or {}
    checks = []
    if job["kind"] == "frames":
        files = [Path(f) for f in outputs]
        checks.append(_check("pictures", len(files) >= max(1, int(exp.get("images", 1) * 0.8)) and all(f.exists() and f.stat().st_size > 0 for f in files),
                             f"{len(files)} saved (expected {exp.get('images')})"))
        if files and exp.get("w") and not job.get("sheet"):
            v = MD.probe(files[0]).get("video") or {}
            checks.append(_check("picture size", (v.get("w"), v.get("h")) == (exp["w"], exp["h"]), f"{v.get('w')}x{v.get('h')}", "warn"))
        return checks
    for k, f in enumerate(outputs):
        tag = f" (part {k + 1})" if len(outputs) > 1 else ""
        try:
            p = MD.probe(f)
        except MD.MediaError as e:
            checks.append(_check(f"readable{tag}", False, str(e)))
            continue
        v, a = p.get("video"), p.get("audio")
        errs = MD.decodes(f, p["duration"], (v or {}).get("w", 0) * (v or {}).get("h", 0) or None)
        checks.append(_check(f"plays through{tag}", not errs, "; ".join(errs[:2])))
        if exp.get("max_bytes"):
            checks.append(_check(f"size{tag}", p["size"] <= exp["max_bytes"], f"{MD.human(p['size'])} (limit {exp['max_bytes'] / 1e6:g} MB)"))
        if len(outputs) > 1:
            continue
        fps = (v or {}).get("fps") or 25
        tol = exp.get("tol") or (0.35 if job["kind"] in ("gif", "webp") else max(0.25, 2.5 / fps))
        checks.append(_check("length", abs(p["duration"] - exp["duration"]) <= tol, f"{MD.mmss(p['duration'])} (expected {MD.mmss(exp['duration'])})"))
        if exp.get("video"):
            if not v:
                checks.append(_check("picture", False, "no picture in the file"))
            else:
                fam = {"gif": "gif", "webp": "webp"}.get(job["kind"], exp.get("vcodec"))
                checks.append(_check("picture codec", v["codec"] == fam, MD.CODEC_WORDS.get(v["codec"], v["codec"])))
                if exp.get("w"):
                    checks.append(_check("picture size", (v["w"], v["h"]) == (exp["w"], exp["h"]), f"{v['w']}x{v['h']}"))
                if exp.get("fps"):
                    checks.append(_check("frame rate", abs(v["fps"] - exp["fps"]) <= max(0.05, exp["fps"] * 0.01), f"{v['fps']:g} fps"))
                if exp.get("pix8"):
                    checks.append(_check("plays on phones and TVs", v["bits"] == 8 and v["chroma"] == "420", f"{v['pix_fmt']}", "warn"))
        if exp.get("audio") is not None and job["kind"] not in ("gif", "webp"):
            checks.append(_check("sound", bool(a) == bool(exp["audio"]), "has sound" if a else "no sound"))
            if a and exp.get("acodec"):
                checks.append(_check("sound codec", a["codec"] == exp["acodec"], MD.CODEC_WORDS.get(a["codec"], a["codec"]), "warn"))
            if a and exp.get("channels"):
                checks.append(_check("mono", a["channels"] == exp["channels"], MD.channels_words(a["channels"]), "warn"))
        if exp.get("faststart"):
            checks.append(_check("starts playing before it has downloaded", p.get("faststart") is True, "", "warn"))
    return checks


# ---------------------------------------------------------------- the search for 'smaller, same look'
def _sample(S, pieces, speed, sources, folder, caps_, over, log, windows, measure=True):
    """Encode the windows with these settings: (VMAF or None, kbps) over them."""
    tmp = Path(folder) / "_samples"
    tmp.mkdir(exist_ok=True)
    scores, nbytes, secs = [], 0, 0.0
    for k, (a, b) in enumerate(windows):
        S2 = dict(S, fade_in=0.0, fade_out=0.0, split=None, max_mb=None, percent=None)
        wj = P.build(S2, P.window(pieces, speed, a, b), speed, sources, tmp, caps_, dict(over, encode=True), name=f"s{k}")
        _pre(wj, None)
        code, err = _make(wj, None)
        if code:
            raise EncodeError(f"a sample failed: {err.strip()[-160:]}")
        v = vmaf(wj, wj["out"]) if measure else None
        if v is not None:
            scores.append((v, b - a))
        nbytes += Path(wj["out"]).stat().st_size
        secs += b - a
    shutil.rmtree(tmp, ignore_errors=True)
    vm = sum(v * d for v, d in scores) / sum(d for _, d in scores) if scores else None
    return vm, nbytes * 8 / max(secs, 0.01) / 1000


def search(S, pieces, speed, sources, folder, caps_, job, log):
    """The highest quality knob (smallest file) whose samples still look the same (VMAF >= SAME_VMAF)."""
    enc = job["venc_name"]
    table = QUALITY.get(enc)
    if not table:
        return job["rate"].get("q"), None, None
    lo, hi = table["range"]
    D = job["D"]
    wins = _windows(D, length=5.0)
    tried = {}

    def at(q):
        if q not in tried:
            tried[q] = _sample(S, pieces, speed, sources, folder, caps_, {"q": q}, log, wins)
            if log:
                log(f"  quality {q}: looks {tried[q][0]:.1f}/100 at {tried[q][1]:.0f} kbps")
        return tried[q]
    def passes(q):
        v = at(q)[0]
        if v is None:
            raise EncodeError("the look of the samples could not be measured")
        return v >= SAME_VMAF
    q0 = table["good"]
    if passes(q0):
        a, b = q0, min(hi, q0 + 12)  # a passes: find the highest knob that still passes (VMAF falls as the knob rises)
    else:
        a, b = lo, q0 - 1
        if not passes(a):
            return a, at(a)[0], at(a)[1]
    while a < b:
        m = (a + b + 1) // 2
        if passes(m):
            a = m
        else:
            b = m - 1
    return a, at(a)[0], at(a)[1]


# ---------------------------------------------------------------- splitting
def _split(out, sp, cap, log):
    """The finished file cut into parts without re-encoding: equal parts, every N seconds, or under a size each."""
    p = MD.probe(out)
    D = p["duration"]
    ext = Path(out).suffix
    stem = Path(out).with_suffix("")
    n = None
    if sp.get("max_mb") or (cap and not sp.get("parts") and not sp.get("every")):
        lim = (sp.get("max_mb") or cap / 1e6) * 1e6
        n = max(2, math.ceil(p["size"] / (lim * 0.94)))
    for attempt in range(6):
        times = P.split_times({"parts": n} if n else sp, D)
        for f in Path(out).parent.glob(f"{stem.name}_part*{ext}"):
            f.unlink(missing_ok=True)
        args = ["-i", out, "-map", "0", "-c", "copy", "-f", "segment", "-segment_times", ",".join(f"{max(0.0, x - 0.01):.3f}" for x in times), "-reset_timestamps", "1"]
        if ext in (".mp4", ".mov", ".m4a"):
            args += ["-segment_format", ext.lstrip("."), "-segment_format_options", "movflags=+faststart"]
        code, err = ff(args + [f"{stem}_part%02d{ext}"], timeout=600)
        if code:
            raise EncodeError(f"splitting failed: {err.strip()[-160:]}")
        parts = sorted(Path(out).parent.glob(f"{stem.name}_part*{ext}"))
        big = [x for x in parts if sp.get("max_mb") and x.stat().st_size > sp["max_mb"] * 1e6]
        if not big:
            return [str(x) for x in parts]
        n = (n or len(parts)) + 1
    raise EncodeError("could not split it into parts small enough")


# ---------------------------------------------------------------- one version, made
def render(chain, sources, folder, name, log=print, caps_=None):
    t0 = time.time()
    caps_ = caps_ if caps_ is not None else caps()
    folder = Path(folder).resolve()  # FFmpeg runs inside this folder, so every path in a job is whole
    pieces, speed = P.timeline(chain, sources)
    S = P.settings(chain)
    used = {str(Path(s["path"]).resolve()).lower() for s in sources}
    for ext in ("mp4", "mkv", "mov", "webm", "avi", "gif", "webp", "mp3", "m4a", "wav", "flac", "ogg", "opus", "aac"):
        if str((folder / f"{name}.{ext}").resolve()).lower() in used:
            name = f"{name}_out"  # a source sits where the result would go: never write over a file being read
            break
    job = P.build(S, pieces, speed, sources, folder, caps_, {}, name)
    notes = list(job["notes"])
    rate = job.get("rate") or {}
    status = "ok"
    found = None
    if rate.get("kind") == "search":
        q, vm, kbps = search(S, pieces, speed, sources, folder, caps_, job, log)
        est = P.est_size(job["pieces"], speed, sources)
        if kbps and kbps * job["D"] / 8 * 1000 >= est * 0.93:
            return {"outputs": [], "kind": "none", "notes": notes, "checks": [], "quality": vm, "seconds": round(time.time() - t0, 1), "size": None,
                    "probe": None, "status": "no_gain", "predicted": kbps * job["D"] / 8 * 1000, "est": est}
        found = (q, vm)
        job = P.build(S, pieces, speed, sources, folder, caps_, {"q": q}, name)
        notes = list(job["notes"])
    elif rate.get("kind") == "bitrate" and job["kind"] == "encode" and job["D"] > 12 and not S.get("resize") and not S.get("fps"):
        # how many kbps this video needs at full size for good quality (a sample, no sound), then the biggest frame that fits
        S2 = dict(S, max_mb=None, percent=None, mute=True, audio=None)
        q = QUALITY.get(job["venc_name"], {}).get("good")
        if q:
            _, k_native = _sample(S2, pieces, speed, sources, folder, caps_, {"q": q, "nofit": True}, None, _windows(job["D"], length=4.0), measure=False)
            job = P.build(S, pieces, speed, sources, folder, caps_, {"k_native": k_native}, name)
            notes = list(job["notes"])
    elif rate.get("kind") == "quality" and rate.get("cap") and job["kind"] == "encode" and job["D"] > 40:
        _, kbps = _sample(S, pieces, speed, sources, folder, caps_, {"q": rate["q"]}, None, _windows(job["D"], length=4.0), measure=False)
        if kbps * job["D"] / 8 * 1000 * 1.08 > rate["cap"]:  # it would come out over the limit: aim at the limit instead
            job = P.build(S, pieces, speed, sources, folder, caps_, {"sized": True}, name)
            notes = list(job["notes"])
    _pre(job, log)
    code, err = _make(job, log)
    if code and str(job.get("venc_name", "")).endswith("_qsv"):
        sw = ENCODERS.get(job["vcodec"], (None, None))[1]
        notes.append("the Intel GPU encoder failed, so the processor made it")
        job = P.build(S, pieces, speed, sources, folder, caps_, {"enc": sw, **({"q": found[0]} if found else {})}, name)
        _pre(job, log)
        code, err = _make(job, log)
    if code:
        raise EncodeError(_why(err))
    out = job["out"]
    cap = (job.get("expect") or {}).get("max_bytes")
    tries = 0
    while cap and job["kind"] in ("encode", "gif", "webp") and Path(out).stat().st_size > cap and tries < 3:
        tries += 1
        size = Path(out).stat().st_size
        if job["kind"] == "encode":
            prev = (job.get("rate") or {}).get("kind")
            if prev == "bitrate":  # aimed at the limit and still over: aim lower by what it missed
                scale = (job.get("_scale") or 1.0) * (cap / size) * 0.97
                job2 = P.build(S, pieces, speed, sources, folder, caps_, {"sized": True, "kbps_scale": scale}, name)
                job2["_scale"] = scale
            else:  # a quality encode came out over: what it needed tells which frame fits the limit
                vk = ((MD.probe(out).get("video") or {}).get("bitrate") or size * 8 / job["D"] * 0.9) / 1000
                job2 = P.build(S, pieces, speed, sources, folder, caps_, {"sized": True, "k_native": vk}, name)
                job2["_scale"] = 1.0
        else:
            k = math.sqrt(cap / size) * 0.92
            g = S.get("gif") or {}
            long0 = job.get("_long") or int(g.get("width") or 480)
            fps0 = job.get("_fps") or float(job.get("fps") or 12)
            over = {"gif_long": max(160, int(long0 * min(0.9, k))), "gif_fps": max(6.0, fps0 - (2 if k < 0.8 else 0)), "colors": 128 if k < 0.7 else 256,
                    "webp_q": max(30, int(70 * k))}
            job2 = P.build(S, pieces, speed, sources, folder, caps_, over, name)
            job2["_long"], job2["_fps"] = over["gif_long"], over["gif_fps"]
        _pre(job2, log)
        code, err = _make(job2, log)
        if code:
            raise EncodeError(_why(err))
        job = job2
        notes = list(job["notes"]) + [f"made it again smaller to fit {cap / 1e6:g} MB"]
    outputs = [out] if job["kind"] != "frames" else (job.get("frames_out") or sorted(str(x) for x in Path(job["out"]).glob("*.*")))
    sp = job.get("split")
    if sp and job["kind"] in ("encode", "copy", "cutcopy", "audio"):
        outputs = _split(out, sp, cap, log)
        Path(out).unlink(missing_ok=True)
        notes.append(f"split into {len(outputs)} parts")
    checks = verify(job, outputs)
    quality = None
    if job["kind"] == "encode" and len(outputs) == 1:
        try:
            quality = _quality(job, outputs[0], S, sources, caps_, folder)
        except Exception as e:  # noqa: BLE001  (a failed measure must not lose the file)
            notes.append(f"the look could not be measured ({type(e).__name__})")
        if quality is not None:
            checks.append(_check("looks like the original", quality >= 80, f"{quality:.0f}/100", "warn"))
    for f in ("stab.trf", f"{name}_parts.txt"):
        (folder / f).unlink(missing_ok=True)
    size = sum(Path(f).stat().st_size for f in outputs if Path(f).is_file())
    probe = MD.probe(outputs[0]) if outputs and job["kind"] != "frames" else None
    return {"outputs": outputs, "kind": job["kind"], "notes": notes, "checks": checks, "quality": quality, "seconds": round(time.time() - t0, 1),
            "size": size, "probe": probe, "status": status, "search": found, "job": {k: job.get(k) for k in ("D", "w", "h", "fps", "venc_name", "vcodec",
                                                                                                                "acodec", "ext", "rate", "mode")},
            "loud_before": job.get("loud_before")}


def _why(err):
    lines = [x for x in (err or "").splitlines() if x.strip() and not x.startswith(("frame=", "size="))]
    tail = " ".join(lines[-2:])[:240]
    return f"FFmpeg stopped: {tail or 'no reason given'}"
