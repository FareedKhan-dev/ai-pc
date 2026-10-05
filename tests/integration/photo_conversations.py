"""Conversations about photos, each turn checked on the image it made: a green-screen presenter cut out, put on new
backgrounds, made into passport photos and a print sheet, titled and saved for a story; a dark car fixed, cropped to
the car, labelled, watermarked, compared and saved small; a party with its faces hidden, then pixelated instead (what
came after is redone), a meme, a border kept outside a later crop; a sunset car with a cinematic look for a YouTube
thumbnail; a photographed page scanned to a PDF; four photos in a collage; and a photo whose location is removed.

  .venv\\Scripts\\python.exe tests\\integration\\photo_conversations.py [--offline]
--offline: rules only (the turns that need the model are skipped).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image  # noqa: E402

from ai_pc.photo import analyze as A  # noqa: E402
from ai_pc.photo.photochat import PhotoChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "photo" / "conv"
GS = ROOT / "media/derived/mixkit_28287_still_7.50.png"
CAR = ROOT / "media/derived/parked-red-sports-car-66_still_8.20.png"
PARTY = ROOT / "media/derived/woman-dancing-at-a-party-in-a-_still_8.20.png"
BMW = ROOT / "media/josh-berquist-_4sWbzH5fp8-unsplash.jpg"
LAND = ROOT / "media/derived/natural-landscape-with-a-road-_still_16.70.png"


class W:
    def __init__(self, c, reply, turn):
        self.c, self.reply, self.turn = c, reply, turn
        self.im = c.image()

    def says(self, *rx):
        return all(re.search(r, self.reply, re.I) for r in rx)

    def size(self):
        return self.im.size

    def px(self, x, y):
        return self.im.convert("RGB").getpixel((int(x * (self.im.width - 1)), int(y * (self.im.height - 1))))

    def st(self):
        return A.stats(self.im)

    def export(self):
        return Path(self.c.state["exports"][-1]["path"]) if self.c.state["exports"] else None

    def kb(self):
        return self.export().stat().st_size / 1024

    def v(self):
        return self.c.state["cur"]

    def last_ops(self):
        return self.c.state["versions"][self.c.state["cur"]]["ops"]


def near(c, want, tol=12):
    return max(abs(a - b) for a, b in zip(c[:3], want)) <= tol


def _page():
    import test_photo
    test_photo.OUT.mkdir(parents=True, exist_ok=True)
    _, doc, _, _, gps = test_photo.made_up()
    p = OUT / "page_photo.jpg"
    doc.save(p, quality=92)
    return p, gps


CHATS = [
    ("presenter", GS, [], [
        ("what's in the photo?", "describe", lambda w: w.says(r"green screen", r"1 face")),
        ("remove the background", "remove_background", lambda w: w.im.mode == "RGBA" and w.im.getchannel("A").getpixel((5, 5)) == 0 and w.says(r"green screen keyed")),
        ("make the background light blue", "replace_background", lambda w: near(w.px(0.02, 0.02), (207, 232, 255))),
        ("make a passport photo", "passport", lambda w: w.size() == (413, 531) and near(w.px(0.03, 0.03), (255, 255, 255), 6) and w.says(r"head 7\d%")),
        ("print 6 of them on a 4x6 sheet", "passport", lambda w: w.size() == (1200, 1800) and w.says(r"6 copies")),
        ("go back to v1", "goto", lambda w: w.v() == 1),
        ("replace the background with natural-landscape-with-a-road-_still_16.70.png", "replace_background",
         lambda w: w.im.mode == "RGB" and not near(w.px(0.02, 0.5), (90, 220, 30), 60) and w.says(r"natural-landscape")),
        ("add a title 'Live every Friday' at the top", "text", lambda w: w.says(r"Live every Friday", r"at the top")),
        ("move the title to the bottom", "text", lambda w: w.says(r"at the bottom", r"Changed the text")),
        ("save it for an instagram story without cropping under 400 kb", "export",
         lambda w: w.export().suffix == ".jpg" and Image.open(w.export()).size == (1080, 1920) and w.kb() <= 400),
    ]),
    ("car", CAR, [], [
        ("it's too dark, fix it", "auto", lambda w: w.st()["brightness"] > 0.35 and w.says(r"it was dark")),
        ("crop to the car", "crop", lambda w: w.size()[0] < 1280 and abs(w.size()[0] / w.size()[1] - 16 / 9) < 0.02),
        ("add 'FOR SALE' at the top in red", "text", lambda w: w.says(r"FOR SALE", r"red")),
        ("make the text bigger", "text", lambda w: w.last_ops()[-1].get("size") == "huge" and w.says(r"Changed the text")),
        ("watermark '© Fareed Motors'", "watermark", lambda w: w.says(r"35% opacity")),
        ("compare with the original", "compare", lambda w: Path(re.search(r"Side by side: (.+?\.jpg)", w.reply).group(1)).exists()),
        ("undo", "undo", lambda w: w.v() == 4 and w.says(r"make the text bigger")),
        ("save it as webp under 150 kb", "export", lambda w: w.export().suffix == ".webp" and w.kb() <= 150),
    ]),
    ("party", PARTY, [], [
        ("blur all the faces", "blur_faces", lambda w: w.says(r"Blurred (8|9|10) face")),
        ("make it warmer", "warmth", lambda w: w.st()["warmth"] > A.stats(Image.open(PARTY))["warmth"]),
        ("crop it to 4:5", "crop", lambda w: abs(w.size()[0] / w.size()[1] - 0.8) < 0.01),
        ("pixelate the faces instead", "blur_faces", lambda w: w.says(r"Pixelated", r"redid the 2 edit") and abs(w.size()[0] / w.size()[1] - 0.8) < 0.01),
        ("make it a meme: 'when the beat drops' / 'and you know every word'", "meme", lambda w: w.says(r"Meme text")),
        ("add a white border", "border", lambda w: near(w.px(0, 0), (255, 255, 255), 2)),
        ("crop it square", "crop", lambda w: w.size()[0] == w.size()[1] and near(w.px(0, 0), (255, 255, 255), 2) and w.says(r"stays on the outside")),
        ("history", "history", lambda w: len(w.reply.splitlines()) >= 7),
    ]),
    ("sunset car", BMW, [], [
        ("make it cinematic", "cinematic", lambda w: w.says(r"cinematic")),
        ("add a title 'New Arrival'", "text", lambda w: w.says(r"New Arrival")),
        ("export it for a youtube thumbnail", "export", lambda w: Image.open(w.export()).size == (1280, 720)),
        ("make it a polaroid with the caption 'Dream car'", "polaroid", lambda w: w.size()[1] > w.size()[0] * 1.0 and near(w.px(0.5, 0.97), (250, 250, 247), 30)),
    ]),
    ("page", None, [], [
        ("scan this document", "document", lambda w: w.st()["brightness"] > 0.75 and 1.15 < w.size()[1] / w.size()[0] < 1.65),
        ("save it as pdf", "export", lambda w: w.export().suffix == ".pdf" and w.export().read_bytes()[:5] == b"%PDF-"),
    ]),
    ("collage", BMW, [CAR, PARTY, LAND], [
        ("make a collage", "collage", lambda w: w.size()[0] == 2048 and w.says(r"4 photos")),
        ("add a thin white border", "border", lambda w: near(w.px(0, 0), (255, 255, 255), 2)),
    ]),
    ("location", None, [], [
        ("where was this taken?", "describe", lambda w: w.says(r"31\.5\d", r"74\.3\d", r"TestCam")),
        ("remove the location and save it", "export", lambda w: not Image.open(w.export()).getexif().get_ifd(0x8825) and w.says(r"location removed")),
    ]),
    ("model", LAND, [], [
        ("give it a moody film noir feel", None, lambda w: w.st()["saturation"] < 0.12, True),
        ("the colours look a bit washed out, can you bring them back?", None, lambda w: w.st()["saturation"] > 0.0, True),
    ]),
]


def run(planner):
    t_all = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    page, gps = _page()
    rows = []
    for name, src, extra, turns in CHATS:
        src = src or (page if name == "page" else gps)
        c = PhotoChat.start(src, extra=extra, chats_dir=OUT / "chats", planner=planner)
        print(f"--- {name}: {Path(src).name}" + (f" + {len(extra)} more" if extra else ""))
        for row in turns:
            msg, want, check = row[:3]
            if len(row) > 3 and row[3] and planner is None:
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
                check_ok = bool(check(W(c, reply, c.last_turn)))
            except Exception as e:  # noqa: BLE001
                check_ok, err = False, err or f"check {type(e).__name__}: {e}"
            ok = intent_ok and check_ok and not err
            rows.append({"chat": name, "msg": msg, "ok": ok, "intents": intents, "seconds": round(secs, 2), "llm": bool(c.last_turn.get("llm")), "reply": reply[:900],
                         "error": err})
            print(f"{'OK ' if ok else 'BAD'} [{','.join(intents)}{'+llm' if c.last_turn.get('llm') else ''}] {secs:5.2f}s  {msg}\n      {reply[:300]}", flush=True)
            if not ok:
                print(f"      intent_ok={intent_ok} check_ok={check_ok} {err or ''}")
    n, ok = len(rows), sum(r["ok"] for r in rows)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{ok}/{n} turns OK; {sum(r['seconds'] for r in rows):.1f} s of turns; {time.perf_counter() - t_all:.0f} s in all; ${usd:.4f}")
    (OUT / "report.json").write_text(json.dumps({"ok": ok, "turns": n, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return ok, n


if __name__ == "__main__":
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    ok, n = run(planner)
    sys.exit(0 if ok == n else 1)
