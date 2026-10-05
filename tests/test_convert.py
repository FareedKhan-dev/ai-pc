"""Engine tests for the converter: files made for the test (a 720p clip with a keyframe every second and a beep every
2 s, an MPEG-4 MKV of another shape and frame rate, a phone clip stored sideways with a turn flag, a letterboxed clip,
a flash-and-beep clip for sound sync, a sound file, subtitles and a logo), every kind of change made and then measured
independently of the converter's own checks (lengths, sizes, frames, pixels, loudness, where a beep lands, the pitch
after a speed change), the checks shown to fail on results spoiled on purpose, the timeline arithmetic, the quality
measure, and requests read by rules (no model).

  .venv\\Scripts\\python.exe tests\\test_convert.py [--record]
About five minutes. Everything is written under out\\_tests\\convert\\engine. --record also records the screen for 3 s
(the file is checked for length and size only, never looked at, and deleted at once).
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from harness.convert import encode as E  # noqa: E402
from harness.convert import media as MD  # noqa: E402
from harness.convert import plan as P  # noqa: E402
from harness.convert import record as R  # noqa: E402
from harness.convert.convchat import ConvertChat  # noqa: E402
from harness.convert.convparse import parse  # noqa: E402
from harness.convert.presets import issues  # noqa: E402
from harness.sound import measure as SM  # noqa: E402

OUT = ROOT / "out" / "_tests" / "convert" / "engine"
FAILS = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and (not ok or "--verbose" in sys.argv) else ""))
    if not ok:
        FAILS.append(name)


def ff(*args):
    code, _, err = MD.run(["ffmpeg", "-hide_banner", "-y", "-v", "error", *[str(a) for a in args]], timeout=300)
    if code:
        raise RuntimeError(err[-300:])


def make_media():
    OUT.mkdir(parents=True, exist_ok=True)
    m = {k: OUT / v for k, v in {"a": "a.mp4", "b": "b.mkv", "rot": "rot.mp4", "bars": "bars.mp4", "sync": "sync.mp4", "tone": "tone.wav",
                                  "srt": "subs.srt", "logo": "logo.png", "late": "late.mp4"}.items()}
    if not m["a"].exists():  # 12 s, 1280x720, 30 fps, a keyframe every second, a 440 Hz beep every 2 s (stereo)
        ff("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=12", "-f", "lavfi", "-i", "sine=f=440:d=12:beep_factor=4:sample_rate=48000",
           "-filter_complex", "[1:a]pan=stereo|c0=c0|c1=c0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-g", "30", "-keyint_min", "30",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", m["a"])
    if not m["b"].exists():  # 8 s, 640x480 (4:3), 25 fps MPEG-4 with mono MP3: another shape, rate and kind of file
        ff("-f", "lavfi", "-i", "mandelbrot=s=640x480:r=25", "-f", "lavfi", "-i", "sine=f=660:d=8", "-t", "8", "-c:v", "mpeg4", "-q:v", "4",
           "-c:a", "libmp3lame", "-b:a", "96k", m["b"])
    if not m["rot"].exists():  # a phone clip: stored landscape with a turn flag, shown upright (720x1280)
        ff("-display_rotation:v:0", "90", "-i", m["a"], "-c", "copy", m["rot"])
    if not m["bars"].exists():  # a 2.4:1 picture letterboxed into 1280x720
        ff("-f", "lavfi", "-i", "testsrc2=s=1280x534:r=30:d=6", "-vf", "pad=1280:720:0:93:black", "-c:v", "libx264", "-pix_fmt", "yuv420p", m["bars"])
    if not m["sync"].exists():  # a white flash and a beep, both at 3.0 s
        ff("-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=6", "-f", "lavfi", "-i", "sine=f=1000:d=6:sample_rate=48000",
           "-filter_complex", "[0:v]drawbox=enable='between(t,3,3.1)':color=white:t=fill[v];[1:a]volume=enable='not(between(t,3,3.1))':volume=0[a]",
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", m["sync"])
    if not m["tone"].exists():
        ff("-f", "lavfi", "-i", "sine=f=330:d=5:sample_rate=48000", "-ac", "2", m["tone"])
    m["srt"].write_text("1\n00:00:03,000 --> 00:00:05,000\nHELLO THERE\n\n2\n00:00:08,000 --> 00:00:09,500\nSECOND LINE\n", encoding="utf-8")
    if not m["logo"].exists():
        im = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([0, 0, 199, 99], fill=(255, 0, 255, 255))
        im.save(m["logo"])
    return m


def frame(path, t, w=None):
    """One frame as an RGB array (FFmpeg decodes)."""
    p = MD.probe(path)
    w = w or p["video"]["w"]
    h = p["video"]["h"] * w // p["video"]["w"]
    code, out, _ = MD.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], timeout=60)
    return np.frombuffer(out, np.uint8).reshape(h, w, 3).astype(np.float32)


def beep_onset(path, after=0.0):
    y = SM.load(path, sr=8000)
    env = np.abs(y)
    k = int(after * 8000)
    hit = np.nonzero(env[k:] > 0.1)[0]
    return (k + hit[0]) / 8000 if len(hit) else None


def pitch(path):
    y = SM.load(path, sr=16000)[:16000 * 2]
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    return float(np.fft.rfftfreq(len(y), 1 / 16000)[np.argmax(spec)])


def render(chain, srcs, name):
    return E.render(chain, [MD.probe(s) for s in srcs], OUT, name, log=lambda *_: None)


def no_fail(r):
    return [c for c in r["checks"] if not c["ok"] and c["level"] == "fail"]


def main():
    t0 = time.time()
    m = make_media()
    caps = E.caps()
    print(f"GPU encoders here: {', '.join(k for k, v in caps.items() if v) or 'none'}")
    # ------------------------------------------------ reading files
    a = MD.probe(m["a"])
    check("probe: length, frame, rate, codecs", abs(a["duration"] - 12) < 0.1 and (a["video"]["w"], a["video"]["h"], a["video"]["fps"]) == (1280, 720, 30.0)
          and a["video"]["codec"] == "h264" and a["audio"]["codec"] == "aac" and a["audio"]["channels"] == 2, MD.describe(a))
    rot = MD.probe(m["rot"])
    check("probe: a phone clip's turn flag shows it upright", (rot["video"]["w"], rot["video"]["h"]) == (720, 1280) and rot["video"]["rotation"] in (90, 270),
          f"{rot['video']['w']}x{rot['video']['h']} r{rot['video']['rotation']}")
    check("probe: MKV of another kind", MD.probe(m["b"])["container"] == "mkv" and MD.probe(m["b"])["video"]["codec"] == "mpeg4")
    kf = MD.keyframes(m["a"])
    check("keyframes every second", len(kf) >= 11 and abs(kf[1] - kf[0] - 1.0) < 0.05, str(kf[:4]))
    check("faststart: a fresh MP4 has its index at the end", a["faststart"] is False)
    check("black bars found", MD.bars(MD.probe(m["bars"])) is not None and abs(MD.bars(MD.probe(m["bars"]))[1] - 534) <= 4, str(MD.bars(MD.probe(m["bars"]))))
    check("no black bars on a full picture", MD.bars(a) is None)
    # ------------------------------------------------ where it would not play
    b = MD.probe(m["b"])
    wa = [x["why"] for x in issues(b, "whatsapp")]
    check("issues: MKV + MPEG-4 + MP3 for WhatsApp", any("MKV" in x for x in wa) and any("MPEG-4" in x for x in wa), "; ".join(wa))
    check("issues: a 720p H.264 MP4 is fine for WhatsApp", issues(a, "whatsapp") == [], "; ".join(x["why"] for x in issues(a, "whatsapp")))
    check("issues: a page waits for an MP4 with its index at the end", [x["level"] for x in issues(a, "web")] == ["minor"])
    check("issues: TVs ignore turn flags", any("turn flag" in x["why"] for x in issues(rot, "tv")))
    check("issues: landscape for TikTok", any("9:16" in x["why"] for x in issues(a, "tiktok")))
    # ------------------------------------------------ timeline arithmetic
    src = [{"duration": 12.0}, {"duration": 8.0}]
    pcs, sp = P.timeline([{"op": "cut", "args": {"ranges": [[2, 3], [6, 8]]}}], src)
    check("timeline: two cuts", abs(P.total(pcs) - 9.0) < 1e-6 and len(pcs) == 3, str(pcs))
    pcs, sp = P.timeline([{"op": "speed", "args": {"factor": 2}}, {"op": "trim", "args": {"start": 1, "end": 4}}], src)
    check("timeline: a trim after a speed-up is in the faster time", abs(pcs[0]["start"] - 2) < 1e-6 and abs(pcs[0]["end"] - 8) < 1e-6, str(pcs))
    pcs, sp = P.timeline([{"op": "join", "args": {"srcs": [1]}}, {"op": "trim", "args": {"start": 10, "end": 15}}], src)
    check("timeline: a trim across a join", [(p["src"], round(p["start"], 3), round(p["end"], 3)) for p in pcs] == [(0, 10.0, 12.0), (1, 0.0, 3.0)], str(pcs))
    pcs, sp = P.timeline([{"op": "trim", "args": {"last": 5}}], src)
    check("timeline: the last 5 seconds", abs(pcs[0]["start"] - 7) < 1e-6)
    try:
        P.timeline([{"op": "trim", "args": {"start": 20}}], src)
        check("timeline: a start past the end is refused", False)
    except P.PlanError:
        check("timeline: a start past the end is refused", True)
    check("size fit: 30 s at 1 Mbps -> below 1080p", P.fit_bitrate(1920, 1080, 30, 1000, "h264")[1] < 1080)
    check("size fit: vertical stays vertical", (lambda r: r[0] < r[1])(P.fit_bitrate(1080, 1920, 30, 1200, "h264")))
    # ------------------------------------------------ copies (nothing re-encoded)
    r = render([{"op": "format", "args": {"to": "mkv"}}], [m["a"]], "mkv")
    p = MD.probe(r["outputs"][0])
    check("MP4 -> MKV is a copy (seconds, nothing lost)", r["kind"] == "copy" and p["container"] == "mkv" and abs(p["duration"] - 12) < 0.1 and not no_fail(r))
    r = render([{"op": "trim", "args": {"start": 2.0, "end": 7.0}}], [m["a"]], "cutcopy")
    check("a cut on keyframes is copied", r["kind"] == "copy" and abs(MD.probe(r["outputs"][0])["duration"] - 5.0) < 0.15 and not no_fail(r), r["kind"])
    r = render([{"op": "trim", "args": {"start": 2.4, "end": 7.0}}], [m["a"]], "cutexact")
    check("a cut between keyframes is re-encoded to the exact frame", r["kind"] == "encode" and abs(MD.probe(r["outputs"][0])["duration"] - 4.6) < 0.1,
          f"{r['kind']} {MD.probe(r['outputs'][0])['duration']:.2f}")
    r = render([{"op": "trim", "args": {"start": 2.4, "end": 7.0}}, {"op": "lossless", "args": {}}], [m["a"]], "cutlossless")
    check("'without re-encoding' cuts at the keyframe before", r["kind"] == "copy" and abs(MD.probe(r["outputs"][0])["duration"] - 5.0) < 0.15
          and any("earlier than asked" in n for n in r["notes"]), str(r["notes"]))
    r = render([{"op": "target", "args": {"name": "whatsapp"}}], [m["a"]], "wa_copy")
    check("already fine for WhatsApp: copied, index moved to the front", r["kind"] == "copy" and MD.probe(r["outputs"][0])["faststart"] is True)
    # ------------------------------------------------ re-encodes
    r = render([{"op": "cut", "args": {"ranges": [[1, 2], [5, 6.5]]}}, {"op": "exact", "args": {}}], [m["a"]], "cut2")
    p = MD.probe(r["outputs"][0])
    check("two cuts: 9.5 s, the sound in step", abs(p["duration"] - 9.5) < 0.1 and not no_fail(r) and p["audio"]["channels"] == 2, f"{p['duration']:.2f}")
    r = render([{"op": "speed", "args": {"factor": 2}}], [m["a"]], "speed2")
    p = MD.probe(r["outputs"][0])
    check("2x speed: half as long, same pitch, same frame rate", abs(p["duration"] - 6) < 0.1 and abs(pitch(r["outputs"][0]) - 440) < 8
          and abs(p["video"]["fps"] - 30) < 0.1, f"{p['duration']:.2f} s, {pitch(r['outputs'][0]):.0f} Hz")
    r = render([{"op": "resize", "args": {"height": 480}}], [m["a"]], "r480")
    check("480p keeps the shape", (r["probe"]["video"]["w"], r["probe"]["video"]["h"]) == (854, 480) and not no_fail(r))
    r = render([{"op": "aspect", "args": {"ratio": "9:16"}}], [m["a"]], "blur916")
    f0 = frame(r["outputs"][0], 1.0)
    check("9:16 with a blurred fill: 720x1280, the fill is not black", (r["probe"]["video"]["w"], r["probe"]["video"]["h"]) == (720, 1280)
          and f0[:200].mean() > 20, f"{r['probe']['video']['w']}x{r['probe']['video']['h']} top {f0[:200].mean():.0f}")
    r = render([{"op": "aspect", "args": {"ratio": "9:16", "fit": "crop"}}], [m["a"]], "crop916")
    check("9:16 cropped: 404x720 (no upscale)", (r["probe"]["video"]["w"], r["probe"]["video"]["h"]) == (404, 720), f"{r['probe']['video']['w']}x{r['probe']['video']['h']}")
    r = render([{"op": "aspect", "args": {"ratio": "1:1", "fit": "bars"}}], [m["a"]], "bars11")
    f0 = frame(r["outputs"][0], 1.0)
    check("1:1 with black bars: 720x720 (the short side kept), black top", (r["probe"]["video"]["w"], r["probe"]["video"]["h"]) == (720, 720)
          and f0[:100].mean() < 5, f"{r['probe']['video']['w']}x{r['probe']['video']['h']} top {f0[:100].mean():.0f}")
    r = render([{"op": "rotate", "args": {"deg": 90}}], [m["a"]], "rot90")
    check("turned 90: 720x1280", (r["probe"]["video"]["w"], r["probe"]["video"]["h"]) == (720, 1280))
    r = render([{"op": "target", "args": {"name": "tv"}}], [m["rot"]], "rot_tv")
    check("for a TV: the turn baked in (no flag, upright)", r["kind"] == "encode" and (r["probe"]["video"]["w"], r["probe"]["video"]["h"]) == (720, 1280)
          and r["probe"]["video"]["rotation"] == 0)
    r = render([{"op": "bars", "args": {}}], [m["bars"]], "nobars")
    check("black bars cut off", abs(r["probe"]["video"]["h"] - 534) <= 4 and r["probe"]["video"]["w"] == 1280, f"{r['probe']['video']['w']}x{r['probe']['video']['h']}")
    r = render([{"op": "target", "args": {"name": "whatsapp"}}], [m["b"]], "b_wa")
    p = r["probe"]
    check("MKV/MPEG-4/MP3 -> WhatsApp: MP4, H.264, AAC, faststart, checks pass", p["container"] == "mp4" and p["video"]["codec"] == "h264"
          and p["audio"]["codec"] == "aac" and p["faststart"] and not no_fail(r))
    r = render([{"op": "compress", "args": {"max_mb": 0.6}}], [m["a"]], "cap06")
    check("under 0.6 MB: fits, plays, smaller frame or rate", r["size"] <= 0.6e6 and not no_fail(r), f"{MD.human(r['size'])} {r['probe']['video']['w']}x{r['probe']['video']['h']}")
    r = render([{"op": "compress", "args": {"percent": 50}}], [m["a"]], "half")
    check("half the size", r["size"] <= MD.probe(m["a"])["size"] * 0.5 and not no_fail(r), MD.human(r["size"]))
    try:
        render([{"op": "compress", "args": {"max_mb": 0.01}}], [m["a"]], "toosmall")
        check("an impossible size is refused with a reason", False)
    except P.PlanError as e:
        check("an impossible size is refused with a reason", "split" in str(e), str(e))
    r = render([{"op": "compress", "args": {}}], [m["a"]], "same")
    check("smaller at the same look: smaller and >= 93, or told it can't", (r["status"] == "no_gain") or (r["size"] < MD.probe(m["a"])["size"] and
          (r["quality"] or 0) >= 93), f"{r['status']} {MD.human(r['size'] or 0)} q={r['quality']}")
    # ------------------------------------------------ sound
    r = render([{"op": "extract_audio", "args": {"fmt": "mp3"}}], [m["a"]], "mp3")
    p = MD.probe(r["outputs"][0])
    check("the sound as MP3", p["video"] is None and p["audio"]["codec"] == "mp3" and abs(p["duration"] - 12) < 0.15)
    r = render([{"op": "extract_audio", "args": {"fmt": "m4a"}}], [m["a"]], "m4a")
    check("AAC sound to M4A is copied", r["kind"] == "copy" and MD.probe(r["outputs"][0])["audio"]["codec"] == "aac")
    r = render([{"op": "mute", "args": {}}], [m["a"]], "mute")
    check("no sound", r["probe"]["audio"] is None and not no_fail(r))
    r = render([{"op": "audio", "args": {"file": str(m["tone"]), "mode": "replace"}}], [m["a"]], "replace")
    check("sound replaced (5 s tone looped under 12 s), the picture copied", r["kind"] == "vcopy" and abs(pitch(r["outputs"][0]) - 330) < 8 and abs(r["probe"]["duration"] - 12) < 0.15,
          f"{pitch(r['outputs'][0]):.0f} Hz")
    r = render([{"op": "normalize", "args": {"lufs": -14}}], [m["a"]], "norm")
    lu = SM.loudness(r["outputs"][0])["lufs"]
    check("normalised to -14 LUFS", abs(lu + 14) < 1.5, f"{lu:.1f}")
    before = beep_onset(m["sync"], 1.0)
    r = render([{"op": "sync", "args": {"delay": -0.3}}], [m["sync"]], "sync")
    check("the output never takes a source's name", Path(r["outputs"][0]).resolve() != m["sync"].resolve())
    after = beep_onset(r["outputs"][0], 1.0)
    check("sound 0.3 s earlier: the beep moved", before and after and abs((before - after) - 0.3) < 0.03 and abs(r["probe"]["duration"] - 6) < 0.1,
          f"{before} -> {after}")
    # ------------------------------------------------ pictures, GIF, parts, joins
    r = render([{"op": "trim", "args": {"start": 1, "end": 5}}, {"op": "gif", "args": {"max_mb": 0.5}}], [m["a"]], "gif")
    check("GIF under 0.5 MB", r["size"] <= 0.5e6 and r["probe"]["video"]["codec"] == "gif" and not no_fail(r), MD.human(r["size"]))
    r = render([{"op": "frames", "args": {"every": 4}}], [m["a"]], "every4")
    check("a picture every 4 s: 3", len(r["outputs"]) == 3, str(len(r["outputs"])))
    r = render([{"op": "trim", "args": {"start": 0, "end": 3}}, {"op": "frames", "args": {"every": 20}}], [m["a"]], "every20short")
    check("a picture every 20 s of a 3 s clip: 1 (never none)", len(r["outputs"]) == 1)
    r = render([{"op": "frames", "args": {"at": [1.5, 6.0]}}], [m["a"]], "at")
    check("pictures at 1.5 s and 6 s", len(r["outputs"]) == 2 and all(Path(x).exists() for x in r["outputs"]))
    r = render([{"op": "frames", "args": {"sheet": True}}], [m["a"]], "sheet")
    check("a contact sheet", len(r["outputs"]) == 1 and MD.probe(r["outputs"][0])["video"]["w"] > 1500)
    r = render([{"op": "split", "args": {"parts": 3}}, {"op": "exact", "args": {}}, {"op": "resize", "args": {"height": 480}}], [m["a"]], "split3")
    durs = [MD.probe(x)["duration"] for x in r["outputs"]]
    check("split into 3 parts of 4 s", len(durs) == 3 and all(abs(d - 4) < 0.2 for d in durs), str(durs))
    r = render([{"op": "split", "args": {"max_mb": 1.5}}], [m["a"]], "splitmb")
    sizes = [Path(x).stat().st_size for x in r["outputs"]]
    check("split into parts under 1.5 MB", len(sizes) >= 3 and all(s <= 1.5e6 for s in sizes) and abs(sum(MD.probe(x)["duration"] for x in r["outputs"]) - 12) < 0.3,
          str([MD.human(s) for s in sizes]))
    r = render([{"op": "join", "args": {"srcs": [1]}}], [m["a"], m["b"]], "join")
    p = r["probe"]
    check("joined with a clip of another shape: 20 s, 1280x720, sound throughout", abs(p["duration"] - 20) < 0.2 and (p["video"]["w"], p["video"]["h"]) == (1280, 720)
          and p["audio"] is not None and not no_fail(r), f"{p['duration']:.2f}")
    r = render([{"op": "logo", "args": {"file": str(m["logo"]), "corner": "br", "opacity": 1.0}}], [m["a"]], "logo")
    f0 = frame(r["outputs"][0], 1.0)
    br = f0[-60:-25, -120:-40]
    check("logo in the bottom right corner", br[..., 0].mean() > 200 and br[..., 1].mean() < 60 and br[..., 2].mean() > 200, str(br.mean(axis=(0, 1))))
    r = render([{"op": "trim", "args": {"start": 2, "end": 10}}, {"op": "subtitles", "args": {"file": str(m["srt"]), "burn": True}}], [m["a"]], "subs")
    with_text, without = frame(r["outputs"][0], 1.5), frame(r["outputs"][0], 4.0)  # cue 1 (3-5 s) is at 1-3 s after cutting 2 s
    check("burned subtitles follow the cut", np.abs(with_text[-120:] - without[-120:]).mean() > 3, f"{np.abs(with_text[-120:] - without[-120:]).mean():.1f}")
    r = render([{"op": "fade", "args": {"in": 1.0, "out": 1.0}}], [m["a"]], "fade")
    check("fade in: the first frame is dark", frame(r["outputs"][0], 0.0).mean() < 20 and frame(r["outputs"][0], 6).mean() > 60)
    r = render([{"op": "gray", "args": {}}], [m["a"]], "gray")
    f0 = frame(r["outputs"][0], 2.0)
    check("black and white", np.abs(f0[..., 0] - f0[..., 1]).mean() < 3 and np.abs(f0[..., 1] - f0[..., 2]).mean() < 3)
    r = render([{"op": "stabilize", "args": {}}], [m["a"]], "stab")
    check("stabilize runs (two passes) and plays", r["kind"] == "encode" and not no_fail(r) and abs(r["probe"]["duration"] - 12) < 0.15)
    # ------------------------------------------------ the checks fail on spoiled results
    pieces, speed = P.timeline([{"op": "resize", "args": {"height": 480}}], [MD.probe(m["a"])])
    job = P.build(P.settings([{"op": "resize", "args": {"height": 480}}]), pieces, speed, [MD.probe(m["a"])], OUT, caps, {}, "spoil")
    bad = E.verify(job, [str(m["a"])])  # the untouched original is not what the job promised
    check("checks catch a wrong frame size", any(c["what"] == "picture size" and not c["ok"] for c in bad))
    trunc = OUT / "truncated.mp4"
    data = (OUT / "mkv.mkv").read_bytes()
    trunc.write_bytes(data[: len(data) // 2])
    check("checks catch a broken file", bool(MD.decodes(trunc, 12)) or not MD.probe(trunc)["duration"] >= 11.5)
    good_q = E.vmaf(job, job["out"]) if Path(job["out"]).exists() else None
    if good_q is None:
        E._make(job, None)
        good_q = E.vmaf(job, job["out"])
    worse = dict(job, venc=P.venc("libx264", q=45), out=str(OUT / "worse.mp4"))
    E._make(worse, None)
    bad_q = E.vmaf(job, worse["out"])
    check("the look measure tells a bad encode from a good one", good_q > 90 and bad_q < good_q - 15, f"{good_q:.1f} vs {bad_q:.1f}")
    # ------------------------------------------------ a chat (rules only): versions, branching, saving next to the original
    chats = OUT / "chats"
    c = ConvertChat.start(m["a"], chats_dir=chats)
    r1 = c.say("make a gif of 0:02 to 0:05")
    r2 = c.say("make it vertical for tiktok")
    v = c.cur()
    check("after a GIF, 'for TikTok' builds on the video", v["kind"] == "encode" and "Made from v0" in r2 and abs(v["duration"] - 12) < 0.2, r2.splitlines()[0])
    r3 = c.say("extract the audio as mp3")
    check("then the sound of that TikTok video", c.cur()["kind"] in ("audio", "copy") and abs(c.cur()["duration"] - 12) < 0.2, r3.splitlines()[0])
    r4 = c.say("make it 480p")
    check("a frame change on the sound file goes back to the video", "Made from v2" in r4 and c.cur()["kind"] == "encode", r4.splitlines()[0])
    c.say("undo")
    check("undo", c.state["cur"] == 3)
    c.say("go back to v1")
    check("go back to v1", c.cur()["kind"] == "gif")
    saved = c.say("save it")
    out_path = Path(saved.replace("Saved to ", "").strip())
    check("save it: next to the original, not over anything", out_path.exists() and out_path.parent == m["a"].parent and out_path.name != m["a"].name, saved)
    out_path.unlink(missing_ok=True)
    ans = c.say("will it play on whatsapp?")
    check("a question answered about the current version", "WhatsApp" in ans, ans)
    hist = c.say("history")
    check("history lists every version", hist.count("\n") >= 4)
    # ------------------------------------------------ rules
    ctx = {"duration": 60, "files": {"intro.mp4": "C:/x/intro.mp4", "song.mp3": "C:/x/song.mp3", "logo.png": "C:/x/logo.png", "subs.srt": "C:/x/subs.srt"}}
    cases = {
        "make it ready for whatsapp": [("target", {"name": "whatsapp"})], "under 10 MB": [("compress", {"max_mb": 10.0})],
        "half the size": [("compress", {"percent": 50})], "smaller but same quality": [("compress", {})], "720p": [("resize", {"height": 720})],
        "rotate it left": [("rotate", {"deg": 270})], "cut the first 5 seconds": [("trim", {"drop_start": 5.0})],
        "keep 0:30 to 1:10": [("trim", {"start": 30.0, "end": 70.0})], "remove 0:10 to 0:20": [("cut", {"ranges": [[10.0, 20.0]]})],
        "speed it up 2x": [("speed", {"factor": 2.0})], "remove the sound": [("mute", {})], "extract the audio as mp3": [("extract_audio", {"fmt": "mp3"})],
        "the sound is half a second late": [("sync", {"delay": -0.5})], "screenshot at 0:12": [("frames", {"at": [12.0], "fmt": "jpg"})],
        "split it into 3 parts": [("split", {"parts": 3})], "join it with intro.mp4": [("join", {"files": ["C:/x/intro.mp4"], "before": False})],
        "will it play on my tv?": [("ask", {"what": "compat", "target": "tv"})], "save it to my desktop": [("save", {"where": "desktop", "name": None})],
        "make it vertical with a blurred background": [("aspect", {"ratio": "9:16", "fit": "blur"})], "fade in and out 2 s": [("fade", {"in": 2.0, "out": 2.0})],
        "add song.mp3 in the background": [("audio", {"file": "C:/x/song.mp3", "mode": "mix"})], "convert it to mp4": [("format", {"to": "mp4"})],
    }
    for text, want in cases.items():
        got = [(o["op"], o["args"]) for o in parse(text, ctx)["ops"]]
        check(f"rules: {text!r}", got == want, str(got))
    check("rules: a time no rule places goes to the model", parse("cut it exactly at 0:05", ctx)["ops"] == [])
    # ------------------------------------------------ screen recording (only with --record)
    if "--record" in sys.argv:
        rec = R.start(OUT, seconds=3)
        path = R.wait_for(rec)
        p = MD.probe(path)
        check("3 s of the screen recorded", abs(p["duration"] - 3) < 0.8 and p["video"]["w"] >= 800, f"{p['duration']:.1f} s {p['video']['w']}x{p['video']['h']}")
        Path(path).unlink(missing_ok=True)
    print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)} in {time.time() - t0:.0f} s")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
