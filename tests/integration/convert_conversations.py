"""Conversations with the converter on real clips, each turn checked on what it made (the file read back: its kind,
frame, rate, length, size, sound) rather than on what it said: a 96 MB HEVC screen recording got ready for WhatsApp,
squeezed under a size, then under another size instead, undone and compared; a square clip turned into a TikTok, a cover
picture, its music dropped and a GIF; a talking video's sound moved into step and saved as MP3, then the video made
720p; clips joined with a narration over them; and requests in everyday words only the model can read.

  .venv\\Scripts\\python.exe tests\\integration\\convert_conversations.py [--offline]
About eight minutes. Chats are kept under out\\_tests\\convert\\conv.
"""
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from ai_pc.convert import media as MD  # noqa: E402
from ai_pc.convert.convchat import ConvertChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "convert" / "conv"
SCREEN = ROOT / "media" / "kimiK3.mp4"           # 1:22, 1920x1080, 60 fps, HEVC + AAC, 96 MB
SQUARE = ROOT / "media" / "eclosion.mp4"         # 0:36, 1080x1080, 30 fps, H.264 + AAC, 46 MB
TALK = ROOT / "media" / "talking_test.mp4"       # 0:12, 1920x1080, 60 fps, H.264 + mono AAC
CAR1 = ROOT / "media" / "stock" / "car" / "red-sports-car-74.mp4"
CAR2 = ROOT / "media" / "stock" / "car" / "parked-red-sports-car-66.mp4"
VOICE = ROOT / "media" / "stock" / "nature" / "narration_muir.mp3"
RESULTS = []


def out(c, k=0):
    v = c.cur()
    return MD.probe(v["outputs"][k]) if v and v["v"] and v["outputs"] else None


def failed(c):
    return [x for x in (c.cur() or {}).get("checks", []) if not x["ok"] and x["level"] == "fail"]


def run(name, c, turns):
    print(f"\n== {name}")
    for msg, test in turns:
        t0 = time.perf_counter()
        reply = c.say(msg)
        try:
            good, why = test(c, reply)
        except Exception as e:  # noqa: BLE001
            good, why = False, f"{type(e).__name__}: {e}"
        RESULTS.append((name, msg, good))
        llm = " [model]" if (c.last_turn or {}).get("llm") else ""
        print(f"{'ok  ' if good else 'FAIL'} > {msg}{llm}  ({time.perf_counter() - t0:.1f} s)")
        for line in reply.splitlines()[:4]:
            print(f"       {line[:180]}")
        if not good:
            print(f"     why: {why}")


def main():
    offline = "--offline" in sys.argv
    planner = None
    if not offline:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    t0 = time.time()
    quiet = lambda *_: None  # noqa: E731

    # ---------------------------------------------------------------- 1. a screen recording for WhatsApp
    c = ConvertChat.start(SCREEN, chats_dir=OUT, planner=planner, log=quiet)

    def wa(c, r):
        p = out(c)
        v = p["video"]
        return (p["container"] == "mp4" and v["codec"] == "h264" and max(v["w"], v["h"]) <= 1280 and v["fps"] <= 30.5 and p["size"] <= 64e6
                and p["faststart"] and p["audio"]["codec"] == "aac" and not failed(c)), MD.describe(p)

    def under(mb, more=None):
        def t(c, r):
            p = out(c)
            return p["size"] <= mb * 1e6 and (more is None or p["size"] > more * 1e6) and not failed(c), MD.describe(p)
        return t
    run("a 96 MB HEVC screen recording for WhatsApp", c, [
        ("will my friends be able to watch this on whatsapp?", lambda c, r: (c.state["cur"] == 0 and re.search(r"HEVC|not as it is|64 MB", r, re.I)
                                                                             is not None, r[:120])),
        ("ok sort it out for whatsapp", wa),
        ("it's still a bit big, can you get it under 8 megs", under(8)),
        ("hmm actually keep it under 15 instead", under(15, 8)),
        ("undo", lambda c, r: (c.state["cur"] == 2, f"now v{c.state['cur']}")),
        ("how does it look compared to the original?", lambda c, r: (re.search(r"\d+/100", r) is not None, r[:120])),
    ])

    # ---------------------------------------------------------------- 2. a square clip: TikTok, a cover, no music, a GIF
    c = ConvertChat.start(SQUARE, chats_dir=OUT, planner=planner, log=quiet)

    def tiktok(c, r):
        p = out(c)
        v = p["video"]
        return (v["w"], v["h"]) == (1080, 1920) and v["codec"] == "h264" and abs(p["duration"] - 36) < 0.5 and not failed(c), MD.describe(p)

    def cover(c, r):
        ex = c.state["extras"]
        return bool(ex) and len(ex[-1]["files"]) == 1 and Path(ex[-1]["files"][0]).exists(), str(ex[-1:] if ex else None)

    def nomusic(c, r):
        p = out(c)
        return p["audio"] is None and (p["video"]["w"], p["video"]["h"]) == (1080, 1920), MD.describe(p)

    def gif(c, r):
        p = out(c)
        return p["video"]["codec"] == "gif" and p["size"] <= 3e6 and abs(p["duration"] - 3) < 0.4, MD.describe(p)
    run("a square clip: TikTok, a cover picture, no music, a GIF", c, [
        ("turn this into a tiktok", tiktok),
        ("grab me a nice cover picture", cover),
        ("get rid of the music", nomusic),
        ("make a gif of 3 to 6 seconds, under 3 megs", gif),
    ])

    # ---------------------------------------------------------------- 3. a talking video: the sound in step, the voice as MP3, then 720p
    c = ConvertChat.start(TALK, chats_dir=OUT, planner=planner, log=quiet)

    def synced(c, r):
        v = c.cur()
        s = next((o["args"].get("delay") for o in v["ops"] if o["op"] == "sync"), None)
        p = out(c)
        return s is not None and abs(s + 0.2) < 0.05 and abs(p["duration"] - 12.2) < 0.3 and not failed(c), f"delay {s}; {MD.describe(p)}"

    def mp3(c, r):
        p = out(c)
        return p["video"] is None and p["audio"]["codec"] == "mp3" and abs(p["duration"] - 12.2) < 0.4, MD.describe(p)

    def v720(c, r):
        p = out(c)
        return p["video"] is not None and min(p["video"]["w"], p["video"]["h"]) == 720 and any(o["op"] == "sync" for o in c.cur()["ops"]), MD.describe(p)
    run("a talking video: the sound in step, the voice as MP3, then 720p", c, [
        ("the voice comes slightly after the lips, about a fifth of a second", synced),
        ("now just give me the voice as an mp3", mp3),
        ("go back to the video and make it 720p", v720),
    ])

    # ---------------------------------------------------------------- 4. clips joined, a narration over them, for YouTube
    c = ConvertChat.start(CAR1, chats_dir=OUT, planner=planner, log=quiet, files=[CAR2, VOICE])
    d1, d2 = MD.probe(CAR1)["duration"], MD.probe(CAR2)["duration"]

    def joined(c, r):
        p = out(c)
        return abs(p["duration"] - (d1 + d2)) < 0.4 and (p["video"]["w"], p["video"]["h"]) == (1280, 720) and not failed(c), MD.describe(p)

    def voiced(c, r):
        p = out(c)
        return p["audio"] is not None and abs(p["duration"] - (d1 + d2)) < 0.4 and any(o["op"] == "audio" for o in c.cur()["ops"]), MD.describe(p)

    def yt(c, r):
        p = out(c)
        return p["video"]["codec"] == "h264" and p["audio"] is not None and p["faststart"] and not failed(c), MD.describe(p)
    run("two clips joined, a narration over them, for YouTube", c, [
        (f"put {CAR2.name} after it", joined),
        (f"use {VOICE.name} as the soundtrack", voiced),
        ("make it ready for youtube", yt),
    ])

    # ---------------------------------------------------------------- 5. everyday words
    c = ConvertChat.start(SCREEN, chats_dir=OUT, planner=planner, log=quiet)

    def tv(c, r):
        p = out(c)
        v = p["video"]
        return v["codec"] == "h264" and v["bits"] == 8 and v["rotation"] == 0 and max(v["w"], v["h"]) <= 1920 and not failed(c), MD.describe(p)

    def bit(c, r):
        p = out(c)
        return abs(p["duration"] - 30) < 0.6, MD.describe(p)

    def fast2(c, r):
        p = out(c)
        return abs(p["duration"] - 15) < 0.6 and p["audio"] is not None, MD.describe(p)
    run("everyday words", c, [
        ("my uncle's old tv won't open this, sort it", tv),
        ("i only need the bit from 20 seconds to 50", bit),
        ("can you make the clip play twice as fast but keep the voices normal", fast2),
    ])

    ok = sum(1 for *_, g in RESULTS if g)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{ok}/{len(RESULTS)} turns right in {time.time() - t0:.0f} s; model ${usd:.4f}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
