"""Engine tests for the photo agent: measures, every edit with its check, saving (size limits, location removed), and
requests read by rules (no model).

  .venv\\Scripts\\python.exe tests\\integration\\test_photo.py
About a minute. Real photos from media\\ (a green-screen presenter, a dark car in a garage, a party with nine faces, a
car at sunset, a landscape) and made-up ones for what those do not have: a leaning horizon, a photographed page, a
date stamp, grain, and a photo carrying GPS location. Everything is written under out\\_tests\\photo.
"""
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from ai_pc.photo import analyze as A  # noqa: E402
from ai_pc.photo import ops as O  # noqa: E402
from ai_pc.photo.photochat import PhotoChat  # noqa: E402
from ai_pc.photo.photoparse import parse  # noqa: E402

OUT = ROOT / "out" / "_tests" / "photo" / "engine"
FAILS = []
GS = ROOT / "media/derived/mixkit_28287_still_7.50.png"
CAR = ROOT / "media/derived/parked-red-sports-car-66_still_8.20.png"
PARTY = ROOT / "media/derived/woman-dancing-at-a-party-in-a-_still_8.20.png"
BMW = ROOT / "media/josh-berquist-_4sWbzH5fp8-unsplash.jpg"
LAND = ROOT / "media/derived/natural-landscape-with-a-road-_still_16.70.png"


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


def edit(name, im, args=None):
    out, info = O.run(name, im, args or {})
    chk = O.check(name, im, out, args or {}, info)
    return out, info, chk


def all_ok(chk):
    return all(c["ok"] for c in chk)


def made_up():
    """Photos the real ones cannot stand in for."""
    W, H = 1600, 1000
    sea = Image.new("RGB", (W, H), (120, 170, 220))  # a horizon: sky over sea, with a few boats
    d = ImageDraw.Draw(sea)
    d.rectangle((0, H // 2, W, H), fill=(30, 70, 110))
    for x in range(200, 1400, 300):
        d.rectangle((x, H // 2 - 40, x + 90, H // 2), fill=(240, 240, 240))
    tilted = sea.rotate(4, resample=Image.BICUBIC, expand=False, fillcolor=(120, 170, 220)).crop((80, 60, W - 80, H - 60))
    page = Image.new("RGB", (850, 1200), (250, 250, 246))  # a page of text photographed at an angle on a wooden table
    pd = ImageDraw.Draw(page)
    f = O.font("serif", 30)
    pd.text((70, 70), "INVOICE  INV-0042", font=O.font("bold", 44), fill=(20, 20, 20))
    for i in range(22):
        pd.text((70, 170 + i * 44), "Item %02d   Rooftop solar panel 550 W   Rs %d,000" % (i + 1, 40 + i * 3), font=f, fill=(35, 35, 35))
    table = np.zeros((1300, 1700, 3), np.uint8)
    table[:] = (60, 90, 140)  # BGR brown
    table = cv2.add(table, np.random.default_rng(1).integers(0, 25, table.shape, dtype=np.uint8))
    src = np.float32([[0, 0], [850, 0], [850, 1200], [0, 1200]])
    dst = np.float32([[520, 60], [1180, 110], [1220, 1240], [480, 1200]])  # a portrait page, seen a little from one side
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(cv2.cvtColor(np.asarray(page), cv2.COLOR_RGB2BGR), M, (1700, 1300))
    mask = cv2.warpPerspective(np.full((1200, 850), 255, np.uint8), M, (1700, 1300))
    table[mask > 0] = warped[mask > 0]
    shade = np.linspace(0.75, 1.05, 1700)[None, :, None]  # uneven light, like a phone photo near a window
    doc = Image.fromarray(cv2.cvtColor(np.clip(table * shade, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB))
    stamped = Image.open(LAND).convert("RGB")
    sd = ImageDraw.Draw(stamped)
    sd.text((stamped.width - 330, stamped.height - 70), "2024 08 12", font=O.font("mono", 42), fill=(255, 140, 20))
    grainy = Image.open(LAND).convert("RGB")
    g = np.asarray(grainy, dtype=np.float32) + np.random.default_rng(3).normal(0, 18, (grainy.height, grainy.width, 3))
    grainy = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8))
    gps = OUT / "with_location.jpg"
    ex = Image.Exif()
    ex[0x010F] = "TestCam"
    ex[0x8825] = {1: "N", 2: (31.0, 31.0, 12.0), 3: "E", 4: (74.0, 21.0, 30.0)}  # Lahore
    Image.open(CAR).convert("RGB").save(gps, quality=90, exif=ex.tobytes())
    return tilted, doc, stamped, grainy, gps


def main():
    t0 = time.perf_counter()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    gs, car, party, bmw, land = (Image.open(p).convert("RGB") for p in (GS, CAR, PARTY, BMW, LAND))
    tilted, doc, stamped, grainy, gps = made_up()

    # ---------------------------------------------------------------- measures
    check("faces: 1 presenter, 9 at the party, none in a landscape", len(A.faces(gs)) == 1 and len(A.faces(party)) >= 8 and not A.faces(land))
    check("backdrop: a green screen; a dark garage is a scene, not a backdrop", A.backdrop(gs)["kind"] == "green" and A.backdrop(car)["kind"] is None)
    x, y, w, h = A.subject(car)
    check("the subject of the garage shot is the red car (in the middle band)", 0.3 < (y + h / 2) / car.height < 0.85 and w < car.width * 0.8, f"{(x, y, w, h)}")
    t = A.tilt(tilted)
    check("a leaning horizon is measured", 2.5 < abs(t) < 5.5, f"{t}")
    check("a photographed page's four corners are found", A.document_quad(doc) is not None)
    st = A.stats(car)
    check("the garage shot reads as very dark and flat", st["brightness"] < 0.2 and st["contrast"] < 0.12)

    # ---------------------------------------------------------------- edits, each with its own check
    cases = [("brightness", car, {"amount": 0.5}), ("brightness", land, {"amount": -0.2}), ("contrast", car, {"amount": 0.3}), ("saturation", party, {"amount": 0.3}),
             ("warmth", party, {"amount": 0.4}), ("warmth", land, {"amount": -0.4}), ("shadows", car, {"amount": 0.5}), ("white_balance", party, {}),
             ("clarity", land, {"amount": 0.6}), ("auto", car, {}), ("auto", bmw, {}), ("auto", gs, {}), ("bw", bmw, {}), ("sepia", land, {}), ("vintage", party, {}),
             ("cinematic", bmw, {}), ("sketch", land, {}), ("cartoon", party, {}), ("invert", land, {}), ("crop", gs, {"aspect": "1:1"}), ("crop", gs, {"aspect": "9:16"}),
             ("crop", car, {"subject": True}), ("rotate", bmw, {"degrees": 90}), ("flip", land, {"how": "horizontal"}), ("resize", bmw, {"width": 1080}),
             ("canvas", bmw, {"aspect": "9:16", "size": (1080, 1920)}), ("border", party, {"color": "white"}), ("rounded", land, {}), ("vignette", land, {"amount": 0.4}),
             ("sharpen", land, {}), ("blur_faces", party, {}), ("blur_faces", party, {"style": "pixelate"}), ("blur_background", gs, {}), ("remove_background", gs, {}),
             ("replace_background", gs, {"color": "white"}), ("smooth_skin", gs, {}), ("brighten_faces", party, {}),
             ("text", bmw, {"text": "New Arrival", "style": "title"}), ("text", car, {"text": "FOR SALE", "where": "top", "color": "red"}),
             ("meme", party, {"top": "when the beat drops", "bottom": "and you know every word"}), ("watermark", bmw, {"text": "© Fareed Motors"}),
             ("watermark", land, {"text": "PREVIEW", "tiled": True}), ("passport", gs, {}), ("passport", gs, {"standard": "us"}), ("passport", gs, {"sheet": "4x6"}),
             ("straighten", tilted, {}), ("document", doc, {}), ("erase", stamped, {"where": "bottom-right"}), ("denoise", grainy, {})]
    bad = []
    t1 = time.perf_counter()
    for name, im, args in cases:
        try:
            out, info, chk = edit(name, im, args)
            if not all_ok(chk):
                bad.append(f"{name}: " + "; ".join(c["what"] for c in chk if not c["ok"]))
            if name in ("document", "straighten", "erase", "passport", "remove_background"):
                out.save(OUT / f"{name}_{len(bad)}_{args.get('standard', args.get('sheet', ''))}.png")
        except O.OpError as e:
            bad.append(f"{name}: {e}")
    check(f"every edit passes its own check: {len(cases) - len(bad)}/{len(cases)} ({time.perf_counter() - t1:.0f} s)", not bad, "; ".join(bad[:4]))
    out, info, chk = edit("straighten", tilted)
    check("straightened: the lean is gone and no empty corners", abs(A.tilt(out)) < 1.0 and min(out.convert("L").getpixel((1, 1)), out.convert("L").getpixel((out.width - 2, out.height - 2))) > 20,
          f"{A.tilt(out)}")
    out, info, chk = edit("document", doc)
    check("the page comes out flat: about A4 in shape, white paper, dark ink", 1.25 < out.height / out.width < 1.6 and all_ok(chk), f"{out.size} {chk}")
    out, info, chk = edit("erase", stamped, {"where": "bottom-right"})
    corner = np.asarray(out.crop((out.width - 340, out.height - 80, out.width, out.height)).convert("RGB"), dtype=np.int16)
    orange = ((corner[..., 0] > 200) & (corner[..., 1] > 100) & (corner[..., 1] < 180) & (corner[..., 2] < 80)).sum()
    check("the date stamp is gone", orange < 30, f"{orange} orange pixels left")
    out, info, chk = edit("text", gs, {"text": "Meet our new host"})
    fx, fy, fw, fh = A.faces(gs)[0]["box"]
    bx = info["box"]
    check("text placed by itself is not over the face and can be read", all_ok(chk) and (bx[3] < fy or bx[1] > fy + fh), f"{bx} vs face {(fx, fy, fw, fh)}")
    cut, _ = O.run("remove_background", gs)
    out, info, chk = edit("text", cut, {"text": "Live every Friday", "where": "top"})
    a = np.asarray(out.getchannel("A"))
    check("words written on a transparent part can be seen (they are solid there)", (a[info["box"][1]:info["box"][3], info["box"][0]:info["box"][2]] > 200).mean() > 0.05)
    out, info = O.canvas(cut, size=(1080, 1920))
    check("a cut-out fitted into a story stays a cut-out (no blurred green filling the sides)", out.mode == "RGBA" and out.getchannel("A").getpixel((5, 5)) == 0)

    # ---------------------------------------------------------------- saving
    c = PhotoChat.start(gps, chats_dir=OUT / "chats")
    r = c.say("save it")
    saved = Path(c.state["exports"][-1]["path"])
    ex = Image.open(saved).getexif()
    check("a saved photo carries no location; the camera is kept; the reply says so", not ex.get_ifd(0x8825) and ex.get(0x010F) == "TestCam" and "location removed" in r, r)
    r = c.say("save it as webp under 60 kb")
    kb = Path(c.state["exports"][-1]["path"]).stat().st_size / 1024
    check("under a size asked (WebP, 60 KB)", kb <= 60 and Path(c.state["exports"][-1]["path"]).suffix == ".webp", f"{kb:.0f} KB; {r}")
    r = c.say("export it for instagram")
    with Image.open(c.state["exports"][-1]["path"]) as im:
        check("for Instagram: 1080x1080", im.size == (1080, 1080), r)
    r = c.say("remove all metadata and save it as jpg")
    check("all metadata removed when asked", not Image.open(c.state["exports"][-1]["path"]).getexif().get(0x010F), r)
    check("the original file is never changed", Image.open(gps).getexif().get_ifd(0x8825) != {})

    # ---------------------------------------------------------------- requests read by rules
    cases = [
        ("make it brighter", lambda o: o[0] == {"op": "brightness", "amount": 0.25}), ("a bit darker", lambda o: o[0]["op"] == "brightness" and o[0]["amount"] == -0.1),
        ("it's too dark, fix it", lambda o: o[0]["op"] == "auto" and o[0].get("brighter") and len(o) == 1), ("make it look better", lambda o: o[0]["op"] == "auto"),
        ("more contrast and much more colourful", lambda o: [x["op"] for x in o] == ["contrast", "saturation"] and o[1]["amount"] > 0.4),
        ("warmer", lambda o: o[0]["op"] == "warmth" and o[0]["amount"] > 0), ("make it cooler", lambda o: o[0]["amount"] < 0),
        ("black and white", lambda o: o[0]["op"] == "bw"), ("give it a vintage look", lambda o: o[0]["op"] == "vintage"), ("cinematic please", lambda o: o[0]["op"] == "cinematic"),
        ("turn it into a pencil sketch", lambda o: o[0]["op"] == "sketch"), ("crop it square", lambda o: o[0] == {"op": "crop", "aspect": "1:1"}),
        ("crop to 16:9", lambda o: o[0]["aspect"] == "16:9"), ("crop to the car", lambda o: o[0].get("subject")), ("crop it for an instagram story", lambda o: o[0]["aspect"] == "9:16"),
        ("fit it in a story without cropping", lambda o: o[0]["op"] == "canvas" and o[0]["size"] == [1080, 1920]), ("rotate it left", lambda o: o[0] == {"op": "rotate", "degrees": 270}),
        ("turn it upside down", lambda o: o[0]["degrees"] == 180), ("the horizon is crooked, straighten it", lambda o: o[0]["op"] == "straighten"),
        ("resize it to 1080 wide", lambda o: o[0] == {"op": "resize", "width": 1080}), ("make it half the size", lambda o: o[0].get("percent") == 50),
        ("blur the faces", lambda o: o[0] == {"op": "blur_faces", "style": "blur"}), ("pixelate their faces", lambda o: o[0]["style"] == "pixelate"),
        ("blur the background", lambda o: o[0]["op"] == "blur_background"), ("remove the background", lambda o: o[0]["op"] == "remove_background"),
        ("make the background white", lambda o: o[0] == {"op": "replace_background", "color": "white"}),
        ("replace the background with beach.jpg", lambda o: o[0] == {"op": "replace_background", "image": "beach.jpg"}),
        ("smooth the skin", lambda o: o[0]["op"] == "smooth_skin"), ("make a passport photo", lambda o: o[0]["op"] == "passport" and "standard" not in o[0]),
        ("US visa photo please", lambda o: o[0]["standard"] == "us"), ("print 6 of them on a 4x6 sheet", lambda o: o[0]["op"] == "passport" and o[0]["sheet"] == "4x6" and o[0]["want"] == 6),
        ("scan this document", lambda o: o[0]["op"] == "document"), ("remove the date stamp in the corner", lambda o: o[0]["op"] == "erase"),
        ("add 'FOR SALE' at the top in red", lambda o: o[0] == {"op": "text", "text": "FOR SALE", "where": "top", "color": "red"}),
        ('write "Happy Birthday Ali" in big yellow letters at the bottom', lambda o: o[0]["text"] == "Happy Birthday Ali" and o[0]["color"] == "yellow" and o[0]["size"] == "large"),
        ("add a banner saying SALE 50% OFF", lambda o: o[0]["op"] == "text" and o[0]["style"] == "banner" and o[0]["text"] == "SALE 50% OFF"),
        ("make it a meme: 'when the beat drops' / 'and you know every word'", lambda o: o[0]["op"] == "meme" and o[0]["bottom"] == "and you know every word"),
        ("watermark '© Fareed' across the photo", lambda o: o[0]["op"] == "watermark" and o[0]["tiled"]), ("move the text to the top", lambda o: o[0] == {"op": "text", "modify": True, "where": "top"}),
        ("make the text bigger and red", lambda o: o[0]["modify"] and o[0]["color"] == "red" and o[0]["size_rel"] == 1),
        ("change the text to 'Saturday night'", lambda o: o[0]["modify"] and o[0]["text"] == "Saturday night"),
        ("sepia instead", lambda o: o[0] == {"op": "sepia", "instead": True}), ("make it vintage instead of sepia", lambda o: o[0]["op"] == "vintage" and o[0]["instead"]),
        ("add a thin black border", lambda o: o[0]["op"] == "border" and o[0]["color"] == "black" and o[0]["percent"] == 0.02),
        ("polaroid frame with the caption 'Dream car'", lambda o: o[0] == {"op": "polaroid", "caption": "Dream car"}),
        ("remove the grain", lambda o: o[0]["op"] == "denoise"), ("sharpen it a bit", lambda o: o[0]["op"] == "sharpen" and o[0]["amount"] == 0.3),
        ("save it for instagram under 300 kb", lambda o: o[0]["op"] == "export" and o[0]["preset"] == "instagram" and o[0]["max_kb"] == 300),
        ("export as png", lambda o: o[0] == {"op": "export", "fmt": "png"}), ("remove the location", lambda o: o[0] == {"op": "strip", "what": "gps"}),
        ("make a collage", lambda o: o[0]["op"] == "collage"), ("what's in the photo?", lambda o: o[0]["op"] == "describe"),
    ]
    bad = []
    for msg, ok in cases:
        r = parse(msg)
        try:
            good = bool(r["ops"]) and ok(r["ops"])
        except Exception:  # noqa: BLE001
            good = False
        if not good:
            bad.append(f"{msg!r} -> {r['ops'] or r['ask']}")
    check(f"requests read by rules: {len(cases) - len(bad)}/{len(cases)}", not bad, "; ".join(bad[:4]))
    print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.0f} s)")
    return not FAILS


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
