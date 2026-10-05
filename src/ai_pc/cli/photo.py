"""The photo agent, from the command line: photos edited by code, every change measured (Windows Photos or any viewer
only shows the result). The original is never changed: versions and saved copies go to the chat's folder.

  ai-pc photo talk car.jpg                     a conversation about one photo
  ai-pc photo talk car.jpg -m "it's too dark, fix it" -m "crop to the car" -m "add 'FOR SALE' at the top in red"
        -m "save it for instagram under 500 kb"
  ai-pc photo talk party.jpg --with a.jpg b.jpg -m "make a collage"
  ai-pc photo talk --chat photo_car_183012      (continue a saved chat)
  ai-pc photo look car.jpg                      what the photo is like, and its metadata (date, camera, location)
  ai-pc photo batch "C:\\Users\\me\\Pictures\\Trip" -m "fix it" -m "watermark '© Me'" --save "for instagram under 500 kb"
        (the same edits on every photo in a folder; each one checked; copies saved to out\\photo\\batch_<time> or --out)

Things to say: 'fix it', 'brighter', 'warmer', 'more contrast', 'black and white', 'vintage', 'cinematic', 'crop it square',
'crop to the car', 'fit it in a story without cropping', 'straighten it', 'blur the faces', 'blur the background',
'remove the background', 'make the background white', 'replace the background with beach.jpg', 'make a passport photo',
'print 6 on a 4x6 sheet', 'scan this document', 'add "SALE" at the top in red', 'move the text to the bottom',
'watermark "© Me"', 'sepia instead', 'undo', 'go back to v2', 'compare with the original', 'save it as png'.
Saved copies leave out the GPS location unless you ask otherwise.
"""
import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
from ai_pc.core.paths import ROOT

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the photo agent: photos edited by code, each change checked")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation about a photo")
    t.add_argument("file", nargs="?")
    t.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    t.add_argument("--with", dest="extra", nargs="*", default=[], help="more photos (for a collage or a new background)")
    t.add_argument("--chat", default=None, help="continue a saved chat by its id")
    t.add_argument("--offline", action="store_true", help="rules only, no model")
    lk = sub.add_parser("look", help="what a photo is like")
    lk.add_argument("file")
    b = sub.add_parser("batch", help="the same edits on many photos")
    b.add_argument("inputs", nargs="+", help="photos, or folders of photos")
    b.add_argument("-m", "--say", action="append", default=[], help="an edit (repeat for several)")
    b.add_argument("--save", default="save it", help="how to save each, e.g. 'for instagram under 500 kb' or 'as png'")
    b.add_argument("--out", default=None, help="the folder for the copies (default out\\photo\\batch_<time>)")
    b.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)

    from ai_pc.photo.photochat import PhotoChat
    planner = None
    if not getattr(a, "offline", True) and a.cmd != "look":
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    if a.cmd == "look":
        c = PhotoChat.start(a.file, chats_dir=ROOT / "out" / "photo" / "looks")
        print(c.describe())
        print(c.metadata())
        return
    if a.cmd == "talk":
        if a.chat:
            c = PhotoChat.load(a.chat, planner=planner)
        else:
            if not a.file:
                sys.exit("say which photo: ai-pc photo talk <photo>")
            c = PhotoChat.start(a.file, extra=a.extra, planner=planner)
        print(f"Chat {c.state['id']} about {Path(c.state['src']).name} (now v{c.state['cur']}). 'help' for ideas, 'quit' to leave.")
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
    # batch: the same edits on every photo, each in its own chat (so each can be undone or looked at later)
    files = []
    for i in a.inputs:
        p = Path(i)
        if p.is_dir():
            files += sorted(q for q in p.iterdir() if q.suffix.lower() in EXTS)
        elif p.is_file():
            files.append(p)
    if not files:
        sys.exit("no photos found")
    out = Path(a.out) if a.out else ROOT / "out" / "photo" / f"batch_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ok = 0
    for f in files:
        c = PhotoChat.start(f, chats_dir=out / "chats", planner=planner)
        replies = [c.say(m) for m in a.say]
        c.say(a.save if a.save.lower().startswith(("save", "export")) else f"save it {a.save}")
        saved = Path(c.state["exports"][-1]["path"]) if c.state["exports"] else None
        good = saved is not None and "not right" not in " ".join(replies) and "Couldn't" not in " ".join(replies)
        if saved:
            dst = out / saved.name.replace(" (edited)", "")
            k = 2
            while dst.exists():
                dst = out / f"{saved.stem.replace(' (edited)', '')} ({k}){saved.suffix}"
                k += 1
            dst.write_bytes(saved.read_bytes())
        ok += good
        print(f"{'ok ' if good else 'BAD'} {f.name}: " + " | ".join(x.splitlines()[0][:90] for x in replies) + f" -> {dst.name if saved else 'not saved'}", flush=True)
    print(f"\n{ok}/{len(files)} photos done in {time.perf_counter() - t0:.0f} s; copies in {out}")


if __name__ == "__main__":
    main()
