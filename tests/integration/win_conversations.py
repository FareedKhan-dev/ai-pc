"""A long conversation about a PC's files and settings, each turn checked on the disk (a made-up Downloads, Documents
and Pictures inside out\\_tests\\win; settings in a test branch of the registry, so the PC's own never change): what is
there, what takes space, find and move, a clean-up shown first and done on 'yes', the Recycle Bin listed and restored,
organizing, photos found by the month they were taken (EXIF or the date in a WhatsApp name), copied, renamed, resized,
a wallpaper picked from a list, zips, merged PDFs, Word to PDF, sound out of a video, folders named, missing and brought
back, settings, the history, undo and redo.

  .venv\\Scripts\\python.exe tests\\integration\\win_conversations.py [--offline]
--offline: rules only (the turns that need the model are skipped).
"""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
from ai_pc.windows import fs  # noqa: E402
from ai_pc.windows import sandbox as win_sandbox  # noqa: E402
from ai_pc.windows.settings import Fake, Settings  # noqa: E402
from ai_pc.windows.winchat import WinChat  # noqa: E402

BASE = ROOT / "out" / "_tests" / "win" / "conv"
Y = dt.datetime.now().year


class W:
    """What a check sees: the reply, the turn, the chat, the folders."""

    def __init__(self, c, reply, turn, sb):
        self.c, self.reply, self.turn = c, reply, turn
        self.dl, self.docs, self.pics = sb["downloads"], sb["documents"], sb["pictures"]

    def says(self, *rx):
        return all(re.search(r, self.reply, re.I) for r in rx)

    def loose(self, folder=None):
        return sorted(p.name for p in (folder or self.dl).iterdir() if p.is_file())

    def names(self, folder):
        return sorted(p.name for p in Path(folder).iterdir()) if Path(folder).exists() else []

    def setting(self, name):
        return self.c.settings.get(name)

    def startup(self, app):
        return next(a["on"] for a in self.c.settings.startup() if a["name"].lower() == app.lower())


def _width(p):
    from PIL import Image
    with Image.open(p) as im:
        return im.size[0]


def _pages(p):
    from pypdf import PdfReader
    return len(PdfReader(str(p)).pages)


CLEANED = ["big-file.zip.part", "python-3.12.4-amd64.exe", "vlc-3.0.21-win64.exe", "Electricity bill Aug (1).pdf", f"IMG_{Y}0812_101500 (1).jpg"]

TURNS = [  # (message, the intent expected, a check, needs the model)
    ("what's in my downloads?", "summary", lambda w: w.says(r"23 files", r"1 empty folder", r"7 photos", r"2 unfinished downloads"), False),
    ("what's taking space?", "find", lambda w: w.says(r"Your folders: Downloads", r"Biggest files", r"Electricity bill Aug")),
    ("find my CV and move it to documents", "move",
     lambda w: (w.docs / "CV - Fareed Hassan.docx").exists() and not (w.dl / "CV - Fareed Hassan.docx").exists() and w.says(r"nothing lost: (\d+) before, \1 after")),
    ("clean up my downloads", "cleanup",
     lambda w: w.c.state["pending"] and all((w.dl / n).exists() for n in CLEANED) and w.says(r"6 items to the Recycle Bin", r"Left alone: movie\.mp4\.crdownload",
                                                                                           r"ZoomInstaller\.exe")),
    ("yes", "confirm", lambda w: not any((w.dl / n).exists() for n in CLEANED) and not (w.dl / "New folder").exists() and (w.dl / "movie.mp4.crdownload").exists()
     and (w.dl / "ZoomInstaller.exe").exists() and (w.dl / f"IMG_{Y}0812_101500.jpg").exists() and w.says(r"Checked: 6/6 OK")),
    ("what's in the recycle bin?", "bin_list", lambda w: w.says(r"6 items from your folders", r"big-file\.zip\.part", r"New folder")),
    ("undo", "undo", lambda w: all((w.dl / n).exists() for n in CLEANED) and (w.dl / "New folder").is_dir() and w.says(r"Checked: 6/6 OK")),
    ("organize my downloads", "organize", lambda w: w.c.state["pending"] and len(w.loose()) == 22 and w.says(r"sort 21 files", r"Photos \(7\)")),
    ("yes", "confirm", lambda w: w.loose() == ["movie.mp4.crdownload"] and len(w.names(w.dl / "Photos")) == 7 and len(w.names(w.dl / "PDFs")) == 3 and
     w.says(r"nothing lost: (\d+) before, \1 after")),
    ("find the photos from august", "find", lambda w: w.says(r"^4 found", r"WhatsApp Image") and len(w.c.state["focus"]) == 4),
    ("copy them to pictures", "copy", lambda w: len(w.names(w.pics)) == 4 and len(w.names(w.dl / "Photos")) == 7),
    ("rename them by the date they were taken", "rename",
     lambda w: w.names(w.pics) == sorted([f"{Y}-08-12 10.15.00.jpg", f"{Y}-08-12 10.15.00 (2).jpg", f"{Y}-08-19 18.30.00.jpg", f"{Y}-08-25 20.11.03.jpeg"])),
    ("make it my wallpaper", "ask", lambda w: w.says(r"Which one\?", r"1\. ") and Path(w.setting("wallpaper")).parent != w.pics),
    ("make the second one my wallpaper", "wallpaper", lambda w: Path(w.setting("wallpaper")).name == f"{Y}-08-12 10.15.00 (2).jpg"),
    ("resize them to 800 pixels wide", "resize", lambda w: len(w.names(w.pics / "Resized")) == 4 and all(_width(p) == 800 for p in (w.pics / "Resized").iterdir())),
    ("zip the PDFs folder", "zip", lambda w: (w.dl / "PDFs.zip").exists() and w.says(r"3 file\(s\)", r"every file reads back")),
    ("merge the pdfs in the PDFs folder into one", "merge_pdfs",
     lambda w: (w.dl / "PDFs" / "Merged.pdf").exists() and _pages(w.dl / "PDFs" / "Merged.pdf") == sum(
         _pages(p) for p in (w.dl / "PDFs").iterdir() if p.name != "Merged.pdf")),
    ("convert the word documents in documents to pdf", "convert", lambda w: (w.docs / "CV - Fareed Hassan.pdf").exists() and w.says(r"1 page")),
    ("extract the audio from the clip", "audio", lambda w: (w.dl / "Videos" / "clip from phone.mp3").exists() and w.says(r"3\.\d s of sound")),
    ("delete the new folder", "trash", lambda w: not (w.dl / "New folder").exists()),
    ("rename the new folder to Taxes", "ask", lambda w: w.says(r"no folder called 'new folder'", r"Recycle Bin") and not (w.dl / "Taxes").exists()),
    ("restore new folder", "bin_restore", lambda w: (w.dl / "New folder").is_dir()),
    ("rename the new folder to Taxes", "rename", lambda w: (w.dl / "Taxes").is_dir() and not (w.dl / "New folder").exists()),
    ("find the pdfs in the invoices folder", "ask", lambda w: w.says(r"no folder called 'invoices'")),
    ("delete everything in downloads", "trash", lambda w: w.c.state["pending"] and w.says(r"Plan", r"Recycle Bin") and (w.dl / "Photos").exists()),
    ("no", "cancel", lambda w: not w.c.state["pending"] and len(w.names(w.dl / "Photos")) == 7),
    ("yes", "nothing", lambda w: w.says(r"nothing waiting")),
    ("empty the recycle bin", "say", lambda w: w.says(r"don't empty the Recycle Bin")),
    ("turn on light mode", "setting", lambda w: w.setting("dark_mode") is False and w.says(r"light mode on")),
    ("show file extensions", "setting", lambda w: w.setting("file_extensions") is True),
    ("what starts with windows?", "startup_list", lambda w: w.says(r"Spotify", r"OneDrive")),
    ("stop spotify from starting with windows", "startup", lambda w: w.startup("spotify") is False),
    ("history", "history", lambda w: len(w.reply.splitlines()) >= 10 and w.says(r"\(undone\)", r"clean up my downloads")),
    ("undo the last two", "undo", lambda w: w.startup("spotify") is True and w.setting("file_extensions") is False),
    ("redo", "redo", lambda w: w.setting("file_extensions") is True and w.startup("spotify") is True),
    ("tell me about the biggest video I have", None, lambda w: w.says(r"clip from phone\.mp4"), True),
    ("I'd love it if the screenshot was a jpg instead", None, lambda w: any(p.suffix == ".jpg" and p.stem.startswith("Screenshot")
                                                                          for p in (w.dl / "Photos").iterdir()), True),
]


def run(planner):
    t_all = time.perf_counter()
    sb = win_sandbox.build(BASE / "sandbox")
    places = {"downloads": sb["downloads"], "documents": sb["documents"], "pictures": sb["pictures"]}
    Fake.wipe()
    c = WinChat.start(places=places, roots=[BASE / "sandbox"], chats_dir=BASE / "chats", settings=Settings(Fake(folder=BASE / "startup")), planner=planner)
    rows = []
    try:
        for row in TURNS:
            msg, want, check = row[:3]
            needs_model = len(row) > 3 and row[3]
            if needs_model and planner is None:
                print(f"SKIP (needs the model)  {msg}")
                continue
            t = time.perf_counter()
            err = None
            try:
                reply = c.say(msg)
            except Exception as e:  # noqa: BLE001
                reply, err = "", f"{type(e).__name__}: {e}"
                c.last_turn = {"intents": ["crash"]}
            secs = time.perf_counter() - t
            intents = c.last_turn.get("intents") or []
            intent_ok = want is None or want in intents
            try:
                check_ok = bool(check(W(c, reply, c.last_turn, sb)))
            except Exception as e:  # noqa: BLE001
                check_ok, err = False, err or f"check {type(e).__name__}: {e}"
            ok = intent_ok and check_ok and not err
            rows.append({"msg": msg, "ok": ok, "intents": intents, "seconds": round(secs, 2), "llm": bool(c.last_turn.get("llm")), "reply": reply[:900], "error": err})
            print(f"{'OK ' if ok else 'BAD'} [{','.join(intents)}{'+llm' if c.last_turn.get('llm') else ''}] {secs:5.2f}s  {msg}\n      {reply[:400]}", flush=True)
            if not ok:
                print(f"      intent_ok={intent_ok} check_ok={check_ok} {err or ''}")
    finally:
        c.close()
        left = [it["orig"] for it in fs.bin_items() if str(BASE).lower() in it["orig"].lower()]
        if left:
            fs.restore(left)
        Fake.wipe()
    clean = not [it for it in fs.bin_items() if str(BASE).lower() in it["orig"].lower()]
    n, ok = len(rows), sum(r["ok"] for r in rows)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{ok}/{n} turns OK; {sum(r['seconds'] for r in rows):.1f} s of turns; {time.perf_counter() - t_all:.0f} s in all; ${usd:.4f}; "
          f"Recycle Bin {'clean' if clean else 'NOT clean'} after")
    (BASE / "report.json").write_text(json.dumps({"ok": ok, "turns": n, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return ok, n, clean


if __name__ == "__main__":
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    ok, n, clean = run(planner)
    sys.exit(0 if ok == n and clean else 1)
