"""Engine tests for the 3D lane (Blender 5.2, portable, in the background), with no model:
  the house geometry from CAD plans, checked in plain Python (walls never overlap, stairs reach the next floor on every
  plan, a floor for every room, glass in every window, an open terrace, the parapet round the roof's outline);
  houses rendered (1 and 2 storeys, every view, a turn-around video) with every check passing;
  the checks shown to fail on spoiled results (a blank picture, an empty silhouette, a cut-off subject, a still video);
  a 3D title; all six mockups with the picture checked the right way round, and a mirrored print caught;
  3D files measured (a closed cube, a box with no lid), pictured, converted and opened again;
  requests read by rules; and chats (a house through the CAD lane, mockups, a 3D file).

  .venv\\Scripts\\python.exe tests\\test_three.py
About six minutes. Everything is written under out\\_tests\\three\\engine.
"""
import itertools
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
from PIL import Image, ImageOps  # noqa: E402

from harness.cad import floorplan as F  # noqa: E402
from harness.three import checks as K  # noqa: E402
from harness.three import make as MK  # noqa: E402
from harness.three.house import CLEAR_H, SLAB, house_spec  # noqa: E402
from harness.three.threechat import ThreeChat  # noqa: E402
from harness.three.threeparse import parse  # noqa: E402

OUT = ROOT / "out" / "_tests" / "three" / "engine"
CARD = ROOT / "out" / "_tests" / "design" / "engine" / "card_modern_front.png"
FAILS = []
quiet = lambda *_: None  # noqa: E731


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def all_pass(r):
    bad = [c for c in r["checks"] if not c["ok"]]
    return not bad, "; ".join(f"{c['what']}: {c['detail']}" for c in bad)


def fixtures():
    OUT.mkdir(parents=True, exist_ok=True)
    v = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    faces = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (3, 4, 8, 7), (4, 1, 5, 8), (2, 3, 7, 6)]
    for name, fs in (("cube.obj", faces), ("open_box.obj", [f for f in faces if f != (5, 6, 7, 8)])):
        (OUT / name).write_text("\n".join([f"v {x} {y} {z}" for x, y, z in v] + [f"f {' '.join(map(str, f))}" for f in fs]) + "\n")
    card = OUT / "card.png"
    if CARD.exists():
        shutil.copyfile(CARD, card)
    else:  # a picture with words and shapes of its own when the design tests have not been run
        im = Image.new("RGB", (1050, 600), (245, 245, 245))
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 360, 600], fill=(40, 90, 170))
        d.ellipse([110, 230, 250, 370], fill=(255, 255, 255))
        for k, t in enumerate(("AHMED KHAN", "SALES MANAGER", "0300-1234567", "Shop 12, Hall Road")):
            d.text((420, 120 + k * 90), t, fill=(30, 60, 120))
        im.save(card)
    ImageOps.mirror(Image.open(card)).save(OUT / "card_mirrored.png")
    return card


def main():
    t0 = time.time()
    card = fixtures()
    # ------------------------------------------------ house geometry from plans (plain Python)
    plans = {"5 marla": F.plan({"plot": [25, 45], "bedrooms": 2, "floors": 1}), "7 marla 2 storeys": F.plan({"plot": [30, 60], "bedrooms": 3, "floors": 2}),
             "1 kanal 2 storeys": F.plan({"plot": [50, 90], "bedrooms": 5, "floors": 2})}
    for nm, lay in plans.items():
        s = house_spec(lay)
        boxes = s["boxes"]
        overlaps = 0
        for grp in {b["c"] for b in boxes if b["c"].endswith("_walls")}:
            bs = [b["b"] for b in boxes if b["c"] == grp and "b" in b]
            for a, b in itertools.combinations(bs, 2):
                if min(a[3], b[3]) - max(a[0], b[0]) > 0.01 and min(a[4], b[4]) - max(a[1], b[1]) > 0.01 and min(a[5], b[5]) - max(a[2], b[2]) > 0.01:
                    overlaps += 1
        check(f"{nm}: no two wall blocks overlap", overlaps == 0, str(overlaps))
        res = {"labels": len(s["labels"])}
        bad = [c for c in MK.model_checks(s, lay, res) if not c["ok"]]
        check(f"{nm}: floors, glass, stairs to the next floor, front door", not bad, "; ".join(c["what"] + " " + c["detail"] for c in bad))
        steps = [b for b in boxes if b["c"] == "out_ground_stairs" and "_step" in b["n"]]
        risers = {round(b["b"][5] - b["b"][2], 1) for b in steps}
        treads = sorted(b["b"][4] - b["b"][1] for b in steps)
        check(f"{nm}: stairs like built ones (risers 6.5-8.5 in, treads 9-12 in)", 6.5 <= (CLEAR_H + SLAB) / len(steps) <= 8.5 and 9 <= treads[0] <= 12.1,
              f"{len(steps)} steps, first tread {treads[0]:.1f}")
        if lay.get("upper"):
            terr = [r for r in lay["upper"]["rooms"] if r["kind"] == "terrace"]
            slabs = [b["b"] for b in boxes if b["c"] == "out_slabs" and b["b"][2] > 150]
            over = [sl for sl in slabs for t in terr if min(sl[3], t["x1"]) - max(sl[0], t["x0"]) > 1 and min(sl[4], t["y1"]) - max(sl[1], t["y0"]) > 1]
            check(f"{nm}: the terrace is open to the sky", terr and not over)
        check(f"{nm}: a parapet round the roof", sum(1 for b in boxes if b["c"] == "out_parapet") >= 4)
        check(f"{nm}: cladding round the front windows", any(b["c"] == "out_cladding" for b in boxes))
        check(f"{nm}: every room named, with its size", len([x for x in s["labels"] if x.get("kind") != "size"]) == len([r for r in lay["rooms"] if r["kind"] != "passage"]))
    # ------------------------------------------------ houses rendered
    r = MK.house(plans["5 marla"], OUT, "h1", views=("plan3d", "top", "front"), log=quiet)
    ok, why = all_pass(r)
    check(f"1 storey: 3D plan, top and front rendered, every check passing ({r['seconds']:.0f} s)", ok and len(r["outputs"]) == 3, why)
    r = MK.house(plans["7 marla 2 storeys"], OUT, "h2", views=("front", "aerial", "orbit"), storey="first", log=quiet, seconds=2, colors={"wall": "plaster_cream"})
    ok, why = all_pass(r)
    check(f"2 storeys: front, aerial and a 2 s turn-around, every check passing ({r['seconds']:.0f} s)", ok and Path(r["outputs"]["orbit"]).exists(), why)
    # ------------------------------------------------ the checks fail on spoiled results
    blank = OUT / "blank.png"
    Image.new("RGB", (640, 360), (128, 128, 128)).save(blank)
    empty = OUT / "empty_mask.png"
    Image.new("RGBA", (480, 270), (0, 0, 0, 0)).save(empty)
    cut = OUT / "cut_mask.png"
    m = Image.new("RGBA", (480, 270), (0, 0, 0, 0))
    m.paste((255, 255, 255, 255), (300, 50, 480, 200))
    m.save(cut)
    cs = {c["what"].split(": ")[1]: c for c in K.view_checks("spoiled", {"framing": {"x0": 0.6, "x1": 1.2, "y0": 0.2, "y1": 0.8, "behind": 0}}, blank, empty)}
    check("checks: a blank picture fails", not cs["a real picture"]["ok"])
    check("checks: nothing in view fails", not cs["subject visible"]["ok"])
    check("checks: a subject out of frame is caught", not cs["whole subject framed"]["ok"])
    cs = {c["what"].split(": ")[1]: c for c in K.view_checks("spoiled", {}, blank, cut)}
    check("checks: a cut-off subject is caught", not cs["nothing cut off"]["ok"])
    still_dir = OUT / "still_frames"
    shutil.rmtree(still_dir, ignore_errors=True)
    still_dir.mkdir()
    for k in range(1, 31):
        shutil.copyfile(OUT / "h1_front.png", still_dir / f"frame_{k:04d}.png")
    K.encode(still_dir, OUT / "still.mp4", 30)
    vc = {c["what"]: c for c in K.video(OUT / "still.mp4", 30, 30)}
    check("checks: a video that does not move fails", not vc["video: it moves"]["ok"])
    # ------------------------------------------------ a 3D title
    r = MK.text({"text": "Khan Electronics", "sub": "Best prices in town", "material": "gold", "seconds": 2}, OUT, "t1", log=quiet)
    ok, why = all_pass(r)
    check(f"3D title: 2 s video and its last frame, centred, lit, moving ({r['seconds']:.0f} s)", ok, why)
    # ------------------------------------------------ mockups
    for kind in ("box", "card", "laptop", "phone", "mug", "poster"):
        r = MK.mockup({"kind": kind, "images": [str(card)]}, OUT, f"k_{kind}", log=quiet)
        ok, why = all_pass(r)
        right = next((c for c in r["checks"] if "right way round" in c["what"]), None)
        check(f"mockup {kind}: picture on it, the right way round, every check passing", ok and right is not None, why)
    for kind in ("box", "mug"):
        r = MK.mockup({"kind": kind, "images": [str(OUT / "card_mirrored.png")]}, OUT, f"mirror_{kind}", log=quiet)
        same, mirrored = MK.picture_match(r["outputs"][kind], r["quad"], card, r["u_range"], r["v_range"])
        check(f"mockup {kind}: a mirrored print is caught", mirrored > same + 0.03, f"{same:.2f} vs {mirrored:.2f}")
    # ------------------------------------------------ 3D files
    r = MK.model({"file": str(OUT / "cube.obj"), "export": "glb"}, OUT, "m1", log=quiet)
    st = r["stats"]
    check("3D file: a 2 m cube measured (12 triangles, watertight, 8 m3)", st["triangles"] == 12 and st["watertight"] and abs(st["volume_m3"] - 8) < 1e-3, str(st))
    ok, why = all_pass(r)
    check("3D file: pictured and saved as GLB, opened again the same", ok and Path(r["outputs"]["export"]).exists(), why)
    r = MK.model({"file": str(OUT / "open_box.obj"), "export": "stl", "render": False}, OUT, "m2", log=quiet)
    check("3D file: a box with no lid is not watertight (4 open edges)", not r["stats"]["watertight"] and r["stats"]["open_edges"] == 4)
    ok, why = all_pass(r)
    check("3D file: saved as STL and opened again the same", ok, why)
    # ------------------------------------------------ rules
    ctx = {"files": {"card.png": "C:/x/card.png", "chair.glb": "C:/x/chair.glb"}}
    cases = {("a 3D model of a 5 marla house with 3 bedrooms", None): ("house_new",), ("make my house plan 3d", None): ("house_from_cad",),
             ("show the front", "house"): ("view",), ("make a video going round it", "house"): ("view",), ("make the kitchen bigger", "house"): ("cad",),
             ("grey walls with wood panels", "house"): ("colors", "colors"), ("the first floor", "house"): ("storey",), ("no furniture", "house"): ("furniture",),
             ("a 3D intro for Khan Electronics in gold", None): ("text_new", "text_style"), ("make it spin in", "text"): ("text_style",),
             ("put card.png on a box", None): ("mockup",), ("now a mug", "mockup"): ("mockup_kind",), ("show me chair.glb", None): ("model",),
             ("convert it to stl", "model"): ("model_export",), ("is it ready for 3d printing?", "model"): ("ask",), ("save it to my desktop", "house"): ("save",),
             ("put it on my desktop", "house"): ("save",)}
    for (text, subj), want in cases.items():
        got = tuple(o["op"] for o in parse(text, dict(ctx, subject=subj))["ops"])
        check(f"rules: {text!r}", got == want, str(got))
    got = [(o["op"], o["args"].get("kind")) for o in parse("put card.png on a mug", dict(ctx, subject=None))["ops"]]
    check("rules: a file's name is not a word ('card.png' on a mug is a mug)", got == [("mockup", "mug")], str(got))
    got = [(o["op"], o["args"].get("kind")) for o in parse("my client wants their visiting card card.png shown on a coffee mug", dict(ctx, subject=None))["ops"]]
    check("rules: the product after 'on a' gets the picture", got == [("mockup", "mug")], str(got))
    got = [o["args"].get("text") for o in parse("make me a logo animation for 'Pak Motors' that looks like chrome", dict(ctx, subject=None))["ops"] if o["op"] == "text_new"]
    check("rules: a title's words come from the quotes", got == ["Pak Motors"], str(got))
    got = [o["op"] for o in parse("can a 3D printer handle this?", dict(ctx, subject="model"))["ops"]]
    check("rules: a printing question is a question, not a conversion", got == ["ask"], str(got))
    got = [(o["op"], o["args"].get("fmt")) for o in parse("give it to me as an STL file", dict(ctx, subject="model"))["ops"]]
    check("rules: 'give it to me as an STL file'", got == [("model_export", "stl")], str(got))
    # ------------------------------------------------ chats (rules only)
    chats = OUT / "chats"
    c = ThreeChat.start(chats_dir=chats, log=quiet, files=[card, OUT / "cube.obj"])
    a = c.say("a 3D model of a 7 marla house with 2 bedrooms")
    check("chat: a house from words (the CAD lane draws the plan)", c.cur() and c.cur()["subject"] == "house" and "plan3d" in c.cur()["outputs"], a[:160])
    plan1 = c.state["params"]["plan"]
    a = c.say("make the kitchen bigger")
    check("chat: a change to the plan goes to the CAD lane, the 3D follows", c.state["params"]["plan"] != plan1 and c.cur()["v"] == 1, a[:200])
    c.say("cream walls with brick cladding")
    check("chat: colours from words", c.state["params"]["colors"].get("wall") == "plaster_cream" and c.state["params"]["colors"].get("accent") == "brick_red")
    c.say("undo")
    check("chat: undo", c.state["cur"] == 1)
    c.say(f"put {card.name} on a mug")
    check("chat: a mockup", c.cur()["subject"] == "mockup" and c.cur()["params"]["kind"] == "mug")
    c.say("show me cube.obj")
    a = c.say("is it ready for 3D printing?")
    check("chat: a 3D file and the printing question", "watertight" in a and a.startswith("Yes"), a)
    print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)} in {time.time() - t0:.0f} s")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
