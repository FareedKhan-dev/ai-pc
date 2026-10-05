"""Engine tests for the sound agent: the measures on recordings made for the test (a Windows voice, then hum, rumble,
noise and clipping added by numpy), every change with its own check, the checks shown to fail on results spoiled on
purpose, captions (cues, files, re-timing after cuts, burning into a video), the timeline a video is cut by, and
requests read by rules (no model).

  .venv\\Scripts\\python.exe tests\\test_sound.py
About two minutes. Everything is written under out\\_tests\\sound\\engine.
"""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402

from harness.sound import captions as C  # noqa: E402
from harness.sound import measure as M  # noqa: E402
from harness.sound import ops as O  # noqa: E402
from harness.sound import tts  # noqa: E402
from harness.sound.soundchat import _compose  # noqa: E402
from harness.sound.soundparse import parse, secs  # noqa: E402

OUT = ROOT / "out" / "_tests" / "sound" / "engine"
MUSIC = ROOT / "media" / "derived" / "music_chill_120_10.4_4.00_3.wav"
VIDEO = ROOT / "media" / "talking_test.mp4"
FAILS = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


def write(y, path, sr=44100):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-c:a", "pcm_s16le", str(path)],
                   input=np.asarray(y, np.float32).tobytes(), creationflags=0x08000000)
    return path


def made_up():
    """A clean voice with fillers and long pauses, and copies spoiled the ways real recordings are."""
    clean = OUT / "voice_clean.wav"
    tts.speak("Hello and welcome to the channel. Today, um, we are going to talk about saving money on your electricity bill. [pause 2s] "
              "First, uh, check your meter every month... and switch off the lights you are not using. [pause 1.5s] "
              "Second, use energy saving bulbs. They cost a little more, but they last for years. [pause 2.5s] "
              "That's it for today. Please like and subscribe.", clean, voice="zira")
    y = M.load(clean, sr=44100)
    t = np.arange(len(y)) / 44100
    rng = np.random.default_rng(7)
    white = rng.standard_normal(len(y))
    brown = np.cumsum(white)
    brown = brown - np.convolve(brown, np.ones(200) / 200, mode="same")
    brown /= np.abs(brown).max()
    hum50 = sum((0.6 / k) * np.sin(2 * np.pi * 50 * k * t) for k in (1, 2, 3, 4))
    hum60 = sum((0.6 / k) * np.sin(2 * np.pi * 60 * k * t) for k in (1, 2, 3, 4))
    files = {"clean": clean,
             "dirty": write(np.clip(y * 0.5 + 0.02 * brown + 0.009 * white + 0.025 * hum50 + 0.02 * np.sin(2 * np.pi * 22 * t), -1, 1), OUT / "voice_dirty.wav"),
             "hum60": write(y * 0.5 + 0.03 * hum60, OUT / "voice_hum60.wav"),
             "noisy": write(y * 0.5 + 0.02 * brown + 0.01 * white, OUT / "voice_noisy.wav"),
             "clipped": write(np.clip(y * 3.0, -1, 1), OUT / "voice_clipped.wav"),
             "hiss": write(y * 0.5 + 0.004 * np.diff(np.concatenate([[0], white])), OUT / "voice_hiss.wav")}
    return files


def measures(f):
    c, d, h60, cl = (M.describe(f[k]) for k in ("clean", "dirty", "hum60", "clipped"))
    check("hum: 50 Hz found in the spoiled copy, none in the clean one", (d["hum"]["hz"] == 50) and c["hum"]["hz"] is None, f"{d['hum']} / {c['hum']}")
    check("hum: 60 Hz told from 50 Hz", h60["hum"]["hz"] == 60, str(h60["hum"]))
    check("rumble: the spoiled copy has it, the clean one not", d["rumble_db"] > -15 and c["rumble_db"] < -25, f"{d['rumble_db']} / {c['rumble_db']}")
    check("noise: the floor rises when noise is added (SNR under 20 dB)", d["snr_db"] < 20 and c["noise_db"] < -80, f"{d['snr_db']} / {c['noise_db']}")
    check("pauses: the three long ones heard (1.5-2.5 s asked, about 2-3.4 s with the sentence ends)", 2.0 <= c["longest_pause"] <= 3.8 and len([p for p in c["pauses"] if p[1] - p[0] > 1.2]) >= 3,
          f"{c['longest_pause']} {c['pauses'][:5]}")
    check("clipping: a voice pushed 3x is seen as clipped", cl["clipped"] > 0.002 and c["clipped"] == 0, f"{cl['clipped']}")
    check("pitch: a female voice measures 150-230 Hz", c["pitch_hz"] and 150 <= c["pitch_hz"] <= 230, str(c["pitch_hz"]))
    check("loudness: EBU R128 by FFmpeg gives LUFS and a true peak", -40 < c["lufs"] < -5 and c["true_peak"] is not None, str(c["lufs"]))
    return c, d


CASES = [("dirty", "clean", {}), ("dirty", "denoise", {"strength": "medium"}), ("noisy", "denoise", {"strength": "light"}), ("dirty", "dehum", {}),
         ("hum60", "dehum", {}), ("dirty", "highpass", {}), ("clipped", "declip", {}), ("clean", "deess", {}), ("clean", "compress", {}),
         ("clean", "normalize", {"platform": "youtube"}), ("clean", "normalize", {"platform": "broadcast"}), ("clean", "volume", {"db": -6}),
         ("clean", "volume", {"db": 6}), ("clean", "trim", {"start": 2, "end": 20}), ("clean", "cut", {"ranges": [[5, 8], [12, 13]]}),
         ("clean", "keep", {"start": 3, "end": 9}), ("clean", "fade", {"in": 1, "out": 2}), ("clean", "tighten", {"max_pause": 0.5}),
         ("clean", "fillers", {}), ("clean", "speed", {"factor": 1.25}), ("clean", "speed", {"factor": 0.8}), ("clean", "pitch", {"semitones": -3}),
         ("clean", "pitch", {"semitones": 4}), ("clean", "music", {"file": str(MUSIC)}), ("clean", "join", {"file": str(MUSIC)}),
         ("clean", "join", {"file": str(MUSIC), "crossfade": 1.0}), ("clean", "echo", {}), ("clean", "reverb", {}), ("clean", "telephone", {}),
         ("clean", "stereo", {}), ("hiss", "denoise", {"strength": "strong"})]


def every_op(f):
    cache = {}
    for name, op, args in CASES:
        t = time.perf_counter()
        src = f[name]
        b = cache.get((name, op)) or O.describe(src, op)
        cache[(name, op)] = b
        dst = OUT / f"{name}_{op}_{len(cache)}.wav"
        try:
            info = O.run(op, src, dst, args, b)
            a = O.describe(dst, op)
            chk = O.check(op, b, a, args, info)
        except Exception as e:  # noqa: BLE001
            check(f"op {op} {args} on {name}", False, f"{type(e).__name__}: {e}")
            continue
        bad = [c["what"] for c in chk if not c["ok"]]
        check(f"op {op} {json.dumps(args)[:40]} on {name}: {len(chk)} check(s) pass ({time.perf_counter() - t:.1f} s)", not bad and chk, "; ".join(bad))


def spoiled(f, c, d):
    """Each check must be able to fail: results that did not do what was asked."""
    clean = f["clean"]
    b = O.describe(clean)
    chk = O.check("normalize", b, dict(b), {}, {"target": -14.0, "tp": -1.5})
    check("spoiled: loudness left at -21 LUFS when -14 was asked -> fails", any(not x["ok"] for x in chk))
    bd = O.describe(f["dirty"])
    chk = O.check("denoise", bd, dict(bd), {}, {"strength": "medium"})
    check("spoiled: noise unchanged -> the denoise check fails", any(not x["ok"] for x in chk))
    chk = O.check("dehum", bd, dict(bd), {}, {"hz": 50, "found": 50})
    check("spoiled: hum unchanged -> the hum check fails", any(not x["ok"] for x in chk))
    chk = O.check("tighten", b, dict(b), {}, {"count": 3, "max_pause": 0.5, "removed": 4.0, "expect": b["duration"] - 4})
    check("spoiled: pauses not shortened -> the tighten check fails", any(not x["ok"] for x in chk))
    quiet = OUT / "spoiled_quiet.wav"
    O.ff([clean], quiet, af="volume=-12dB")
    chk = O.check("denoise", bd, O.describe(quiet), {}, {"strength": "medium"})
    check("spoiled: everything turned down (the voice too) -> 'the voice kept its level' fails", any(not x["ok"] and "voice" in x["what"] for x in chk))
    cut = OUT / "spoiled_cut.wav"
    O.ff([clean], cut, af="atrim=0:10")
    chk = O.check("speed", b, O.describe(cut), {}, {"factor": 1.25, "expect": b["duration"] / 1.25})
    check("spoiled: cut short instead of sped up -> the length check fails", any(not x["ok"] for x in chk))
    shifted = OUT / "spoiled_pitch.wav"
    O.ff([clean], shifted, af="asetrate=44100*1.26,aresample=48000")  # chipmunk: pitch AND speed
    chk = O.check("speed", b, O.describe(shifted), {}, {"factor": 1.26, "expect": b["duration"] / 1.26})
    check("spoiled: sped up by raising the pitch -> 'pitch kept' fails", any(not x["ok"] and "pitch" in x["what"] for x in chk))
    words = [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("one two three four five six seven eight".split())]
    bad_cues = [{"start": 0, "end": 2.0, "text": "one two three four", "lines": ["one two three four"], "words": words[:4]},
                {"start": 1.5, "end": 3.9, "text": "five six seven eight", "lines": ["five six seven eight"], "words": words[4:]}]
    check("spoiled captions: two overlapping -> fails", any(not x["ok"] and "overlapping" in x["what"] for x in C.check_cues(bad_cues, words, {"kind": "clean"})))
    check("spoiled captions: words left out -> fails", any(not x["ok"] and "every word" in x["what"] for x in C.check_cues(bad_cues[:1], words, {"kind": "clean"})))
    long_cue = [{"start": 0, "end": 4.0, "text": "x" * 60, "lines": ["x" * 60], "words": words}]
    check("spoiled captions: a 60-character line -> fails", any(not x["ok"] and "lines" in x["what"] for x in C.check_cues(long_cue, words, {"kind": "clean"})))
    cues = C.make_cues(O.transcribe_words(VIDEO), {"kind": "clean"})
    check("spoiled burn: the video without its captions -> 'words on the picture' fails",
          any(not x["ok"] and "words are on the picture" in x["what"] for x in C.check_burn(VIDEO, VIDEO, cues, {"kind": "clean"})))


def captions():
    words = O.transcribe_words(VIDEO)
    check("Whisper hears the talking video (28 words or so)", 24 <= len(words) <= 32 and "router" in " ".join(w["w"].lower() for w in words), str(len(words)))
    for kind in ("clean", "bold", "karaoke", "boxed"):
        st = dict(C.default_style({"w": 1920, "h": 1080}), kind=kind, upper=kind == "bold")
        cues = C.make_cues(words, st)
        chk = C.check_cues(cues, words, st)
        check(f"captions {kind}: {len(cues)} cues, every reading rule met", not [x for x in chk if not x["ok"]], "; ".join(x["what"] for x in chk if not x["ok"]))
    st = C.default_style({"w": 1920, "h": 1080})
    cues = C.make_cues(words, st)
    files = C.write(cues, st, OUT, "caps", {"w": 1920, "h": 1080})
    s = Path(files["srt"]).read_text(encoding="utf-8")
    times = re.findall(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})", s)
    starts = [int(h) * 3600 + int(m) * 60 + int(x) + int(ms) / 1000 for h, m, x, ms, *_ in times]
    check("SRT: numbered cues with times in order", len(times) == len(cues) and starts == sorted(starts) and s.startswith("1\n"))
    check("VTT and ASS written (ASS sized to the video, Arial)", Path(files["vtt"]).read_text(encoding="utf-8").startswith("WEBVTT") and
          "PlayResX: 1920" in Path(files["ass"]).read_text(encoding="utf-8-sig") and ",Arial," in Path(files["ass"]).read_text(encoding="utf-8-sig"))
    kept = [(0.0, 3.0), (5.0, 12.2)]
    moved = C.remap(cues, kept, speed=1.0)
    gone = [w for c in cues for w in c["words"] if w["start"] < 5.0 and w["end"] > 3.0]  # a word the cut touches is no longer said whole
    n_before = sum(len(c["words"]) for c in cues)
    n_after = sum(len(c["words"]) for c in moved)
    late = [w for c in moved for w in c["words"] if w["start"] > 10.3]
    check("captions re-timed after a cut: the cut words go, later words move 2 s earlier", n_after == n_before - len(gone) and not late, f"{n_before} -> {n_after}, {len(gone)} cut")
    fast = C.remap(cues, [(0.0, 12.2)], speed=1.25)
    check("captions re-timed after 1.25x speed", abs(fast[-1]["words"][-1]["end"] - cues[-1]["words"][-1]["end"] / 1.25) < 0.01)
    work = OUT / "burn"
    work.mkdir(exist_ok=True)
    for kind in ("bold", "clean"):
        stb = dict(st, kind=kind, upper=kind == "bold")
        cb = C.make_cues(words, stb)
        C.write(cb, stb, work, "c", {"w": 1920, "h": 1080})
        dst = work / f"burn_{kind}.mp4"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(VIDEO), "-vf", "subtitles=c.ass", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-an",
                            dst.name], cwd=str(work), capture_output=True, creationflags=0x08000000)
        chk = C.check_burn(VIDEO, dst, cb, stb)
        check(f"burned {kind} captions are on the frames while said, nothing between lines", r.returncode == 0 and not [x for x in chk if not x["ok"]],
              "; ".join(x["what"] for x in chk if not x["ok"]) or r.stderr.decode()[-200:])


def timeline():
    tl = {"keep": [[0.0, 30.0]], "speed": 1.0}
    a = _compose(tl, [(0.0, 10.0), (12.0, 30.0)])
    check("timeline: a cut keeps the source parts", a == {"keep": [[0.0, 10.0], [12.0, 30.0]], "speed": 1.0}, str(a))
    b = _compose(a, [(0.0, 28.0)], 2.0)
    check("timeline: then 2x speed (28 s of it)", b["speed"] == 2.0 and b["keep"] == [[0.0, 10.0], [12.0, 30.0]], str(b))
    cc = _compose(b, [(2.0, 8.0)])
    check("timeline: then keep 2-8 s of the fast version -> source 4-10 and 12-18 s", cc["keep"] == [[4.0, 10.0], [12.0, 18.0]] and cc["speed"] == 2.0, str(cc))


PHRASES = [
    ("clean it up", lambda o: o[0]["op"] == "clean"), ("make my voice sound clearer", lambda o: o[0]["op"] == "clean"),
    ("clean it up for youtube", lambda o: o[0] == {"op": "clean", "args": {"platform": "youtube"}}),
    ("remove the background noise", lambda o: o[0] == {"op": "denoise", "args": {"strength": "medium"}}),
    ("remove the hum", lambda o: o[0]["op"] == "dehum"), ("there's a buzzing sound, remove it", lambda o: o[0]["op"] == "dehum"),
    ("cut the rumble", lambda o: o[0]["op"] == "highpass"), ("fix the harsh s sounds", lambda o: o[0]["op"] == "deess"),
    ("remove the clicks", lambda o: o[0]["op"] == "declick"), ("it's distorted", lambda o: o[0]["op"] == "declip"),
    ("even out the volume", lambda o: o[0]["op"] == "compress"), ("normalize for podcast", lambda o: o[0] == {"op": "normalize", "args": {"platform": "podcast"}}),
    ("make it -16 lufs", lambda o: o[0]["args"]["lufs"] == -16), ("make it louder", lambda o: o[0] == {"op": "volume", "args": {"db": 6}}),
    ("a little quieter", lambda o: o[0] == {"op": "volume", "args": {"db": -3}}), ("cut the first 5 seconds", lambda o: o[0] == {"op": "trim", "args": {"start": 5.0}}),
    ("remove the last 10 seconds", lambda o: o[0] == {"op": "trim", "args": {"drop_end": 10.0}}),
    ("remove 1:20 to 1:45", lambda o: o[0] == {"op": "cut", "args": {"ranges": [[80.0, 105.0]]}}),
    ("keep only 0:30 to 2:00", lambda o: o[0] == {"op": "keep", "args": {"start": 30.0, "end": 120.0}}),
    ("fade in and out", lambda o: o[0]["op"] == "fade" and o[0]["args"]["in"] and o[0]["args"]["out"]),
    ("fade out over 4 seconds", lambda o: o[0] == {"op": "fade", "args": {"in": 0, "out": 4.0}}),
    ("remove the long pauses", lambda o: o[0] == {"op": "tighten", "args": {"max_pause": 0.5}}),
    ("cut pauses longer than 1 second", lambda o: o[0]["args"]["max_pause"] == 1.0), ("remove the ums and uhs", lambda o: o[0]["op"] == "fillers"),
    ("speed it up 1.25x", lambda o: o[0] == {"op": "speed", "args": {"factor": 1.25}}), ("make it 20% slower", lambda o: o[0]["args"]["factor"] == 0.8),
    ("make my voice deeper", lambda o: o[0] == {"op": "pitch", "args": {"semitones": -3}}),
    ("add music.mp3 under my voice", lambda o: o[0]["op"] == "music" and o[0]["args"]["file"] == "music.mp3"),
    ("add some background music", lambda o: True), ("make the music quieter", lambda o: o == [{"op": "music_level", "args": {"by": -6}}]),
    ("add intro.mp3 at the start", lambda o: o[0]["op"] == "join" and o[0]["args"]["before"]), ("add echo", lambda o: o[0]["op"] == "echo"),
    ("make it sound like an old radio", lambda o: o[0]["op"] == "telephone"), ("add captions", lambda o: o[0]["op"] == "captions"),
    ("word by word captions in yellow", lambda o: o[0] == {"op": "captions", "args": {"kind": "bold", "color": "yellow"}}),
    ("make the captions bigger and at the top", lambda o: o[0]["args"] == {"size_by": 1.25, "position": "top"}),
    ("save as mp3 under 5 MB", lambda o: o[0] == {"op": "export", "args": {"fmt": "mp3", "max_mb": 5.0}}),
    ("export the video", lambda o: o[0]["args"]["fmt"] == "mp4"), ("save the srt", lambda o: o[0]["args"]["fmt"] == "srt"),
    ("save the transcript as word", lambda o: o[0]["args"]["fmt"] == "docx"), ("how loud is it?", lambda o: o[0]["args"]["what"] == "loudness"),
    ("is it noisy?", lambda o: o[0]["args"]["what"] == "quality"), ("what does it say?", lambda o: o[0]["args"]["what"] == "transcript"),
]


def phrases():
    ctx = {"has_video": True, "has_captions": True, "files": {}}
    for text, ok in PHRASES:
        r = parse(text, ctx)
        try:
            good = bool(r["ops"] or r.get("ask")) and (ok(r["ops"]) if r["ops"] else text == "add some background music")
        except (KeyError, IndexError, TypeError):
            good = False
        check(f"reads: {text}", good, str(r)[:200])
    check("times: 1:20 / 90s / 2 min 10 s / 1:02:03", (secs("1:20"), secs("90s"), secs("2 min 10 s"), secs("1:02:03")) == (80, 90, 130, 3723))


if __name__ == "__main__":
    t0 = time.perf_counter()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    f = made_up()
    c, d = measures(f)
    every_op(f)
    spoiled(f, c, d)
    captions()
    timeline()
    phrases()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.0f} s)")
    sys.exit(1 if FAILS else 0)
