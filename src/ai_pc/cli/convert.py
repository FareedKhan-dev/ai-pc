"""The converter, from the command line: videos and sound converted, shrunk, cut, joined, turned and fixed by code
(FFmpeg on this PC, the Intel GPU when it helps), each result read back and checked, and its look measured against the
original. The original is never changed: versions go to the chat's folder; 'save' copies one where you want it.

  ai-pc convert talk holiday.mov                         a conversation about one file
  ai-pc convert talk holiday.mov -m "will it play on whatsapp?" -m "make it ready for whatsapp" -m "save it to my desktop"
  ai-pc convert talk --chat convert_holiday_101500      continue a saved chat
  ai-pc convert look holiday.mov                         what it is, and where it would not play
  ai-pc convert batch "C:\\Users\\me\\Videos" -m "for whatsapp"       the same on many files
  ai-pc convert record --seconds 20 --mic                record the screen

Things to say: 'convert it to mp4', 'make it ready for whatsapp / email / discord / instagram / tiktok / youtube / my tv
/ my iphone / powerpoint / editing', 'under 10 MB', 'half the size', 'make it smaller but keep the quality', '720p',
'30 fps', 'make it vertical with a blurred background', 'square with black bars', 'rotate it left', 'it's upside down',
'remove the black bars', 'cut the first 5 seconds', 'keep 0:30 to 1:10', 'remove 1:00 to 1:20', 'speed it up 2x', 'slow
motion', 'remove the sound', 'extract the audio as mp3', 'replace the audio with song.mp3', 'add song.mp3 in the
background', 'louder', 'normalize the volume', 'the sound is half a second late', 'stabilize it', 'black and white',
'fade in and out', 'add logo.png in the corner', 'burn subs.srt', 'make a gif of 0:05 to 0:08', 'screenshot at 0:12',
'screenshots every 10 seconds', 'a contact sheet', 'split it into 3 parts', 'split into parts under 16 MB', 'join it
with intro.mp4', 'use the cpu', 'will it play on my tv?', 'what is this file?', 'how good is it?', 'compare', 'save it to
my desktop', 'record my screen for 20 seconds', 'undo', 'go back to v1', 'history'.
"""
import argparse
import sys
import time
from pathlib import Path

from ai_pc.core.paths import ROOT

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the converter: videos and sound converted, shrunk, cut and fixed by code, each result checked")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation about a file")
    t.add_argument("file", nargs="?")
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="other files the chat may use (to join, music, a logo, subtitles)")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    lk = sub.add_parser("look", help="what a file is, and where it would not play")
    lk.add_argument("file")
    b = sub.add_parser("batch", help="the same changes on many files")
    b.add_argument("inputs", nargs="+")
    b.add_argument("-m", "--say", action="append", default=[])
    b.add_argument("--out", default=None)
    b.add_argument("--offline", action="store_true")
    r = sub.add_parser("record", help="record the screen")
    r.add_argument("--seconds", type=float, default=10.0)
    r.add_argument("--mic", action="store_true")
    r.add_argument("--screen", type=int, default=1)
    a = ap.parse_args(argv)

    from ai_pc.convert import media as MD
    from ai_pc.convert.convchat import ConvertChat
    if a.cmd == "look":
        from ai_pc.convert.presets import PRESETS, issues
        p = MD.probe(a.file)
        print(MD.describe(p))
        for key in ("everywhere", "whatsapp", "email", "tv", "iphone", "instagram", "editing"):
            found = issues(p, key)
            print(f"  {PRESETS[key]['label']}: " + ("fine as it is" if not found else "; ".join(x["why"] for x in found)))
        return
    if a.cmd == "record":
        c = ConvertChat.start()
        print(c.say(f"record my screen {a.screen} for {a.seconds:g} seconds" + (" with my mic" if a.mic else "")))
        print(f"(chat {c.state['id']}; continue it with: ai-pc convert talk --chat {c.state['id']})")
        return
    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    if a.cmd == "talk":
        c = ConvertChat.load(a.chat, planner=planner) if a.chat else ConvertChat.start(a.file, planner=planner, files=a.extra)
        print(f"Chat {c.state['id']}" + (f" about {c.src['name']}" if c.src else "") + f" (now v{c.state['cur']}). 'quit' to leave.")
        if c.src:
            print(c.state["versions"][0]["summary"])
        if a.say:
            for msg in a.say:
                print(f"> {msg}")
                print(c.say(msg), flush=True)
        else:
            while True:
                try:
                    msg = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if msg.lower() in ("quit", "exit", "q", "bye"):
                    break
                if msg:
                    print(c.say(msg), flush=True)
        usd = planner.cost()[1] if planner is not None else 0.0
        print(f"(chat {c.state['id']}: {len(c.state['versions'])} versions, now v{c.state['cur']}; files in {c.folder}; AI ${usd:.4f})")
        return
    files = []
    for i in a.inputs:
        p = Path(i)
        files += sorted(q for q in p.iterdir() if q.suffix.lower() in MD.VIDEO_EXTS | MD.AUDIO_EXTS) if p.is_dir() else ([p] if p.is_file() else [])
    if not files:
        sys.exit("no videos or sound files found")
    out = Path(a.out) if a.out else ROOT / "out" / "convert" / f"batch_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    ok, t0 = 0, time.perf_counter()
    for f in files:
        try:
            c = ConvertChat.start(f, chats_dir=out / "chats", planner=planner)
        except MD.MediaError as e:
            print(f"BAD {f.name}: {e}")
            continue
        replies = [c.say(m) for m in a.say]
        v = c.cur()
        good = v["v"] > 0 and not any(x for x in v["checks"] if not x["ok"] and x["level"] == "fail")
        if v["v"] > 0:
            for k, src in enumerate(v["outputs"]):
                dst = out / (f"{f.stem}{Path(src).suffix}" if len(v["outputs"]) == 1 else f"{f.stem}_part{k + 1}{Path(src).suffix}")
                dst.write_bytes(Path(src).read_bytes())
        ok += good
        print(f"{'ok ' if good else 'BAD'} {f.name}: " + " | ".join(x.splitlines()[0][:110] for x in replies), flush=True)
    print(f"\n{ok}/{len(files)} done in {time.perf_counter() - t0:.0f} s; copies in {out}")


if __name__ == "__main__":
    main()
