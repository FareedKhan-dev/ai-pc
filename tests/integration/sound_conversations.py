"""Conversations with the sound agent, each turn checked on what it made (the sound measured again, the files read
back, the video's frames): a spoiled voice recording cleaned, tightened, levelled for YouTube instead of podcasts, put
over music that is then turned down, captioned and saved; a talking video captioned word by word, corrected,
restyled, sped up and exported with the captions burned in and the picture cut to match; a voice-over made from a
script; and, with the model, requests the rules cannot read.

  .venv\\Scripts\\python.exe tests\\integration\\sound_conversations.py [--offline]
"""

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import numpy as np  # noqa: E402

from ai_pc.sound import measure as M  # noqa: E402
from ai_pc.sound import tts  # noqa: E402
from ai_pc.sound.soundchat import SoundChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "sound" / "conv"
MUSIC = ROOT / "media" / "derived" / "music_chill_120_10.4_4.00_3.wav"
VIDEO = ROOT / "media" / "talking_test.mp4"
RESULTS = []


class Turn:
    def __init__(self, c, reply):
        self.c, self.reply = c, reply
        self.v = c.cur()

    def says(self, *rx):
        return all(re.search(r, self.reply, re.I) for r in rx)

    def m(self):
        return M.describe(self.v["wav"])

    def last_export(self):
        return Path(self.c.state["exports"][-1]["path"]) if self.c.state["exports"] else None

    def ok(self):
        return not [x for x in (self.v or {}).get("checks", []) if not x["ok"] and x["level"] == "fail"]


def run(name, c, turns):
    print(f"\n== {name}")
    for msg, test in turns:
        t0 = time.perf_counter()
        reply = c.say(msg)
        t = Turn(c, reply)
        try:
            good, why = test(t)
        except Exception as e:  # noqa: BLE001
            good, why = False, f"{type(e).__name__}: {e}"
        RESULTS.append((name, msg, good))
        print(
            f"{'ok  ' if good else 'FAIL'} [{time.perf_counter() - t0:4.1f}s] {msg}"
            + ("" if good else f"\n       why: {why}\n       reply: {reply[:500]}")
        )


def spoiled_voice():
    clean = OUT / "voice_clean.wav"
    tts.speak(
        "Hello and welcome to the channel. Today, um, we are going to talk about saving money on your electricity bill. [pause 2s] "
        "First, uh, check your meter every month... and switch off the lights you are not using. [pause 1.5s] "
        "Second, use energy saving bulbs. They cost a little more, but they last for years. [pause 2.5s] "
        "That's it for today. Please like and subscribe.",
        clean,
        voice="zira",
    )
    y = M.load(clean, sr=44100)
    t = np.arange(len(y)) / 44100
    rng = np.random.default_rng(3)
    white = rng.standard_normal(len(y))
    brown = np.cumsum(white)
    brown = brown - np.convolve(brown, np.ones(200) / 200, mode="same")
    brown /= np.abs(brown).max()
    hum = sum((0.6 / k) * np.sin(2 * np.pi * 50 * k * t) for k in (1, 2, 3, 4))
    dirty = np.clip(y * 0.5 + 0.02 * brown + 0.009 * white + 0.025 * hum + 0.02 * np.sin(2 * np.pi * 22 * t), -1, 1).astype(np.float32)
    p = OUT / "interview.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", "44100", "-ac", "1", "-i", "-", "-c:a", "pcm_s16le", str(p)],
        input=dirty.tobytes(),
        creationflags=0x08000000,
    )
    return p


def voice(planner):
    src = spoiled_voice()
    c = SoundChat.start(src, chats_dir=OUT, planner=planner, files=[MUSIC])
    base = M.describe(src)
    st = {}

    def cleaned(t):
        m = t.m()
        st["clean"] = m
        return (
            t.ok()
            and m["snr_db"] >= base["snr_db"] + 15
            and not m["hum"]["hz"]
            and abs(m["lufs"] + 16) <= 1,  # noise against the voice: levelling moves both
            f"SNR {base['snr_db']} -> {m['snr_db']}, hum {m['hum']}, {m['lufs']}",
        )

    def tightened(t):  # pauses measured against the same threshold as before the cut
        m = t.m()
        ps = M.pauses(M.frames_db(M.load(t.v["wav"])), st["clean"]["noise_db"], st["clean"]["speech_db"])
        longest = max((e - s for s, e in ps), default=0.0)
        return (t.ok() and longest <= 0.7 and m["duration"] < st["clean"]["duration"] - 4, f"{longest} {m['duration']}")

    def youtube(t):
        m = t.m()
        ops = [o["op"] for o in t.v["ops"]]
        return (t.ok() and abs(m["lufs"] + 14) <= 1 and ops.count("normalize") == 1 and "tighten" in ops and "fillers" in ops, f"{m['lufs']} {ops}")

    def music(t):
        mus = next(o for o in t.v["ops"] if o["op"] == "music")
        return (t.ok() and mus["args"]["below"] == 18, str(mus))

    def quieter(t):
        mus = next(o for o in t.v["ops"] if o["op"] == "music")
        return (t.ok() and mus["args"]["below"] == 24 and len(t.v["steps"]) == 1, f"{mus} steps {len(t.v['steps'])}")

    def mp3(t):
        p = t.last_export()
        pr = M.probe(p)
        return (
            p.suffix == ".mp3" and p.stat().st_size <= 1024 * 1024 and abs(pr["duration"] - t.v["summary"]["duration"]) < 0.15,
            f"{p} {pr['duration']}",
        )

    def srt(t):
        p = t.last_export()
        s = p.read_text(encoding="utf-8")
        return (p.suffix == ".srt" and s.startswith("1\n") and "-->" in s and "electricity" in s.lower(), s[:120])

    run(
        "a spoiled voice recording",
        c,
        [
            ("is it noisy?", lambda t: (t.says(r"50 Hz hum", r"background noise", r"long pauses"), "")),
            ("clean it up", cleaned),
            ("remove the long pauses", tightened),
            ("cut the ums and uhs", lambda t: (t.ok() and t.says(r"Cut [12] filler"), "")),
            ("normalize for youtube instead", youtube),
            (f"add {MUSIC.name} under my voice", music),
            ("make the music quieter", quieter),
            ("add captions", lambda t: (t.ok() and t.v["captions"] and len(t.v["captions"]["cues"]) >= 5, "")),
            ("save as mp3 under 1 MB", mp3),
            ("save the srt", srt),
            ("save the transcript as word", lambda t: (t.last_export().suffix == ".docx" and t.last_export().stat().st_size > 5000, "")),
            ("how loud is it?", lambda t: (t.says(r"-1[3-5]\.\d LUFS"), "")),
            ("compare with the original", lambda t: (t.says(r"hum 50 Hz .* -> none", r"longest pause"), "")),
            ("undo", lambda t: (t.c.state["cur"] == t.c.state["versions"][-1]["parent"], "")),
            ("go back to v1", lambda t: (t.c.state["cur"] == 1, "")),
        ],
    )


def video(planner):
    c = SoundChat.start(VIDEO, chats_dir=OUT, planner=planner)

    def exported(t):
        p = t.last_export()
        pr = M.probe(p)
        chk = t.c.state["exports"][-1].get("checks", [])
        return (
            p.suffix == ".mp4" and pr["video"] and abs(pr["duration"] - t.v["summary"]["duration"]) < 0.25 and chk and all(x["ok"] for x in chk),
            f"{pr['duration']} vs {t.v['summary']['duration']}; {[x['what'] for x in chk if not x['ok']]}",
        )

    run(
        "a talking video",
        c,
        [
            (
                "add word by word captions",
                lambda t: (t.ok() and t.v["captions"]["style"]["kind"] == "bold" and len(t.v["captions"]["cues"]) >= 8, ""),
            ),
            (
                "change 'open router' to 'OpenRouter'",
                lambda t: (any("OPENROUTER" in x["text"].upper().replace(" ", "") for x in t.v["captions"]["cues"]) and t.says(r"in 1 place"), ""),
            ),
            (
                "make the captions yellow and at the top",
                lambda t: (t.v["captions"]["style"]["color"] == "yellow" and t.v["captions"]["style"]["position"] == "top", ""),
            ),
            ("speed it up 1.25x", lambda t: (t.ok() and abs(t.v["summary"]["duration"] - 12.2 / 1.25) < 0.2 and t.says(r"Captions moved"), "")),
            ("export the video", exported),
            ("cut the first 2 seconds", lambda t: (t.ok() and abs(t.v["timeline"]["keep"][0][0] - 2.5) < 0.05, str(t.v["timeline"]))),
            ("export the video", exported),
        ],
    )


def voiceover(planner):
    c = SoundChat.start(None, chats_dir=OUT, planner=planner)
    run(
        "a voice-over",
        c,
        [
            (
                "voice-over: Welcome to Khan Electronics. We are open from nine to nine, every day except Friday.",
                lambda t: (t.v and 4 < t.v["summary"]["duration"] < 15, ""),
            ),
            ("make the voice deeper", lambda t: (t.ok() and t.says(r"Pitch -3"), "")),
            ("fade in and out", lambda t: (t.ok(), "")),
            ("save it for whatsapp", lambda t: (t.last_export().suffix == ".mp3" and M.probe(t.last_export())["audio"]["channels"] == 1, "")),
        ],
    )


def with_model(planner):
    c = SoundChat.start(VIDEO, chats_dir=OUT, planner=planner)
    run(
        "read by the model",
        c,
        [
            (
                "my voice sounds a bit far away and echoey, can you make it sound closer and more present",
                lambda t: (t.c.last_turn["llm"] and t.v["v"] >= 1 and t.ok(), t.reply[:200]),
            ),
            ("add captions", lambda t: (t.ok() and t.v["captions"], "")),
            (
                "export the video",
                lambda t: (
                    all(x["ok"] for x in t.c.state["exports"][-1].get("checks", [])) and t.c.state["exports"][-1]["fmt"] == "mp4",
                    t.reply[:300],
                ),
            ),
        ],
    )


if __name__ == "__main__":
    offline = "--offline" in sys.argv
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    planner = None
    if not offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    t0 = time.perf_counter()
    voice(planner)
    video(planner)
    voiceover(planner)
    if not offline:
        with_model(planner)
    bad = [(n, m) for n, m, g in RESULTS if not g]
    usd = planner.cost()[1] if planner is not None else 0.0
    print(
        f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} turns right in {time.perf_counter() - t0:.0f} s (AI ${usd:.4f})"
        + ("" if not bad else "\nFAILED: " + "; ".join(f"{n}: {m}" for n, m in bad))
    )
    sys.exit(1 if bad else 0)
