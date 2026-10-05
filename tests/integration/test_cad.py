"""Engine tests for the drafting agent: units, the house planner on plots from 3 marla to 2 kanal, size limits asked
for in a chat, the drawings read back and printed, the checks shown to fail on drawings spoiled on purpose, parts and
their cut files, and requests read by rules (no model).

  .venv\\Scripts\\python.exe tests\\integration\\test_cad.py
About two minutes (each sheet is printed by headless Chrome). Everything is written under out\\_tests\\cad\\engine.
"""

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import ezdxf  # noqa: E402
from PIL import Image  # noqa: E402

from ai_pc.cad import check as CK  # noqa: E402
from ai_pc.cad import draft as DR  # noqa: E402
from ai_pc.cad import floorplan as F  # noqa: E402
from ai_pc.cad import parts as P  # noqa: E402
from ai_pc.cad import render as RD  # noqa: E402
from ai_pc.cad import units as U  # noqa: E402
from ai_pc.cad.cadparse import parse  # noqa: E402

OUT = ROOT / "out" / "_tests" / "cad" / "engine"
FAILS = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


def fails(checks):
    return [c["what"] for c in checks if not c["ok"] and c["level"] == "fail"]


def failed(checks, words):
    """The check whose words start so has failed."""
    return any(not c["ok"] and c["what"].lower().startswith(words.lower()) for c in checks) or any(
        not c["ok"] and words.lower() in c["what"].lower() for c in checks
    )


def units():
    check("ft_in 150 -> 12'-6\"", U.ft_in(150) == "12'-6\"", U.ft_in(150))
    check("ft_in 66.5 -> 5'-6½\"", U.ft_in(66.5) == "5'-6½\"", U.ft_in(66.5))
    check("parse_len 12'-6\" -> 150", abs(U.parse_len("12'-6\"") - 150) < 0.01)
    check("5 marla is 25 x 45 (1125 sq ft)", tuple(U.plot_of(5)) == (25, 45) and abs(U.marla_of(25, 45) - 5) < 0.01)
    check("1 kanal is 50 x 90", tuple(U.plot_of(1, "kanal")) == (50, 90))


BRIEFS = {
    "3 marla, 1 bed": {"plot": [20, 34], "bedrooms": 1},
    "5 marla, 2 bed": {"plot": [25, 45], "bedrooms": 2},
    "5 marla, 3 bed (one does not fit)": {"plot": [25, 45], "bedrooms": 3},
    "7 marla, 3 bed": {"plot": [30, 52], "bedrooms": 3},
    "8 marla corner, 3 bed, dining": {"plot": [30, 60], "bedrooms": 3, "corner": True, "dining": True},
    "10 marla, 3 bed": {"plot": [35, 65], "bedrooms": 3},
    "10 marla, 4 bed, dining, double": {"plot": [35, 65], "bedrooms": 4, "dining": True, "floors": 2},
    "12 marla, 4 bed, store, powder": {"plot": [40, 68], "bedrooms": 4, "store": True, "powder": True},
    "1 kanal, 4 bed, all extras, double": {
        "plot": [50, 90],
        "bedrooms": 4,
        "dining": True,
        "store": True,
        "powder": True,
        "servant": True,
        "floors": 2,
    },
    "2 kanal, 5 bed, guest": {"plot": [75, 120], "bedrooms": 5, "dining": True, "guest": True},
    "5 marla, no porch, straight stairs": {"plot": [25, 45], "bedrooms": 2, "porch": False, "stair_type": "straight"},
}


def planner():
    for name, b in BRIEFS.items():
        t = time.perf_counter()
        try:
            lay = F.plan(b)
        except F.PlanError as e:
            check(f"plan {name}", False, str(e))
            continue
        s = time.perf_counter() - t
        bad = fails(CK.design(lay))
        beds = sum(1 for r in lay["rooms"] if r["kind"] == "bedroom")
        check(f"plan {name}: design rules pass ({beds} bed down, {s:.1f} s)", not bad and s < 4.0, "; ".join(bad) or f"{s:.1f} s")
        if b.get("floors", 1) > 1:
            up = lay.get("upper")
            check(f"plan {name}: first floor over the same stairs", up is not None and not F.unreachable(up))
    lay = F.plan(BRIEFS["5 marla, 3 bed (one does not fit)"])
    check("a bedroom that does not fit is said so", any("does not fit" in n or "at the front" in n for n in lay["notes"]), lay["notes"])
    lay = F.plan({"plot": [25, 45], "bedrooms": 2, "store": True})
    check(
        "a store with no room on 5 marla is left out, and said so (with the stairs tip)",
        "store" in lay.get("dropped", []) and any("store" in n and "stairs" in n for n in lay["notes"]),
        lay["notes"][:2],
    )
    base = F.plan({"plot": [35, 65], "bedrooms": 3})
    k0 = next(r for r in base["rooms"] if r["id"] == "kitchen")
    w0 = (k0["x1"] - k0["x0"]) / 12
    big = F.plan({"plot": [35, 65], "bedrooms": 3, "min": {"kitchen": [w0 + 1, None]}})
    k1 = next(r for r in big["rooms"] if r["id"] == "kitchen")
    check(
        "a minimum width is kept (kitchen a foot wider)",
        (k1["x1"] - k1["x0"]) >= w0 * 12 + 11.5 and not fails(CK.design(big)),
        f"{(k1['x1'] - k1['x0']) / 12:.2f} vs {w0:.2f}",
    )
    d0 = next(r for r in base["rooms"] if r["id"] == "drawing")
    dw = (d0["x1"] - d0["x0"]) / 12
    small = F.plan({"plot": [35, 65], "bedrooms": 3, "max": {"drawing": [None, (d0["y1"] - d0["y0"]) / 12 - 1]}})
    d1 = next(r for r in small["rooms"] if r["id"] == "drawing")
    check("a maximum depth is kept (drawing room a foot shallower)", (d1["y1"] - d1["y0"]) <= (d0["y1"] - d0["y0"]) - 11.5, f"{dw:.1f}")
    exact = F.plan({"plot": [35, 65], "bedrooms": 3, "sizes": {"kitchen": [10, 12]}})
    k2 = next(r for r in exact["rooms"] if r["id"] == "kitchen")
    check(
        "an exact size is drawn (kitchen 10' x 12')",
        abs(k2["x1"] - k2["x0"] - 120) < 0.6 and abs(k2["y1"] - k2["y0"] - 144) < 1.1,
        f"{U.ft_in(k2['x1'] - k2['x0'])} x {U.ft_in(k2['y1'] - k2['y0'])}",
    )


def drawings():
    """Three plans drawn, read back and printed; every check passes. Returns one plan's files for the spoiling tests."""
    keep = None
    for name, b, want_paper in (
        ("5m", BRIEFS["5 marla, 2 bed"], "A3"),
        ("10m2", BRIEFS["10 marla, 4 bed, dining, double"], "A3"),
        ("1k2", BRIEFS["1 kanal, 4 bed, all extras, double"], "A2"),
    ):
        lay = F.plan(b)
        doc, sh = DR.drawing(lay, project="Test House", client="Mr Test")
        stem = OUT / name
        doc.saveas(stem.with_suffix(".dxf"))
        files = RD.render(doc, sh, stem)
        cks = CK.check(stem.with_suffix(".dxf"), lay, files, sh)
        check(
            f"drawing {name}: all {len(cks)} checks pass, {sh['paper']} at 1:{sh['scale']}",
            not [c for c in cks if not c["ok"]],
            "; ".join(c["what"] for c in cks if not c["ok"]),
        )
        check(
            f"drawing {name}: paper chosen {want_paper} (no smaller than 1:150)",
            sh["paper"] == want_paper and sh["scale"] <= 150,
            f"{sh['paper']} 1:{sh['scale']}",
        )
        txt = " ".join(e.dxf.text for e in ezdxf.readfile(str(stem.with_suffix(".dxf"))).modelspace().query("TEXT"))
        check(f"drawing {name}: title block names the project and client", "Test House" in txt and "Mr Test" in txt)
        if name == "5m":
            keep = (lay, stem, files, sh)
    return keep


def spoiled(keep):
    """The checks must be able to fail: each spoiled copy of a good drawing trips the check meant for it."""
    lay, stem, files, sh = keep
    good = stem.with_suffix(".dxf")

    def spoil(tag, fn):
        doc = ezdxf.readfile(str(good))
        fn(doc, doc.modelspace())
        p = OUT / f"spoiled_{tag}.dxf"
        doc.saveas(p)
        return CK.dxf_file(p, lay, sh["plans"])

    def drop_label(doc, msp):
        for e in list(msp.query("MTEXT")):
            if "KITCHEN" in e.plain_text().upper():
                msp.delete_entity(e)

    check("spoiled: a room's name removed -> 'every room is named' fails", failed(spoil("label", drop_label), "every room is named"))

    def lie_dim(doc, msp):
        d = next(e for e in msp.query("DIMENSION") if e.dxf.get("text", "") not in ("", "<>"))
        d.dxf.text = "99'-0\""

    check("spoiled: a dimension's text changed -> the dimension check fails", failed(spoil("dim", lie_dim), "dimension(s), each"))

    def drop_arc(doc, msp):
        msp.delete_entity(msp.query("ARC[layer=='A-DOOR']")[0])

    check("spoiled: a door swing removed -> the door count fails", failed(spoil("door", drop_arc), "door swing"))

    def drop_area(doc, msp):
        msp.delete_entity(msp.query("LWPOLYLINE[layer=='A-AREA']")[0])

    check("spoiled: a room outline removed -> the area check fails", failed(spoil("area", drop_area), "room outline"))

    def mm_units(doc, msp):
        doc.header["$INSUNITS"] = 4

    check("spoiled: units set to mm -> the units check fails", failed(spoil("units", mm_units), "drawing units are inches"))

    def no_glass(doc, msp):
        for e in list(msp.query("LINE[layer=='A-GLAZ']")):
            msp.delete_entity(e)

    check("spoiled: the windows' glass removed -> the window check fails", failed(spoil("glass", no_glass), "window(s) drawn"))
    bad = OUT / "spoiled_truncated.dxf"
    bad.write_bytes(good.read_bytes()[:3000])
    check("spoiled: a cut-short DXF -> 'does not open' (or audit) fails", any(not c["ok"] for c in CK.dxf_file(bad, lay)))
    blank = OUT / "spoiled_blank.png"
    Image.new("RGB", (800, 560), "white").save(blank)
    check("spoiled: a blank preview -> the preview check fails", failed(CK.sheet({"png": str(blank)}, sh), "preview"))
    check(
        "spoiled: the A3 PDF said to be A2 -> the PDF check fails",
        failed(CK.sheet({"pdf": files["pdf"]}, dict(sh, paper="A2", paper_mm=(594, 420))), "PDF"),
    )
    import copy

    lay2 = copy.deepcopy(lay)
    lay2["doors"] = [d for d in lay2["doors"] if d["to"] != "bed2" and d["from"] != "bed2"]
    check("spoiled plan: bedroom 2's door taken away -> reachability fails", failed(CK.design(lay2), "every room can be reached"))
    lay3 = copy.deepcopy(lay)
    k = next(r for r in lay3["rooms"] if r["id"] == "kitchen")
    k["x1"] = k["x0"] + 40
    check("spoiled plan: kitchen squeezed to 3'-4\" -> the minimum size check fails", failed(CK.design(lay3), "no room under its minimum"))
    lay4 = copy.deepcopy(lay)
    a, b = lay4["rooms"][0], lay4["rooms"][1]
    b["x0"], b["x1"], b["y0"], b["y1"] = a["x0"] + 10, a["x1"] + 10, a["y0"], a["y1"]
    check("spoiled plan: two rooms on top of each other -> the overlap check fails", failed(CK.design(lay4), "no two rooms overlap"))


def parts():
    plate = {
        "kind": "plate",
        "w": 200.0,
        "h": 100.0,
        "t": 10.0,
        "material": "ms",
        "corner": {"r": 8.0},
        "holes": [{"d": 12.0, "pattern": "corners", "n": 4, "e": 20.0}, {"d": 30.0, "pattern": "center"}],
    }
    flange = {"kind": "flange", "od": 150.0, "id": 60.0, "pcd": 110.0, "n": 4, "hole_d": 14.0, "t": 12.0, "material": "ms"}
    for name, spec, holes in (("plate", plate, 5), ("flange", flange, 4)):
        doc, sh = P.part_drawing(spec)
        stem = OUT / f"part_{name}"
        doc.saveas(stem.with_suffix(".dxf"))
        files = RD.render(doc, sh, stem)
        pc = P.part_checks(spec)
        check(f"part {name}: design rules pass", not [c for c in pc if not c["ok"]], "; ".join(c["what"] for c in pc if not c["ok"]))
        aud = ezdxf.readfile(str(stem.with_suffix(".dxf"))).audit()
        check(
            f"part {name}: the drawing audits clean, PDF and preview made",
            not aud.has_errors and Path(files["pdf"]).exists() and Path(files["png"]).exists(),
        )
        cut = P.cut_file(spec)
        cp = OUT / f"part_{name}_cut.dxf"
        cut.saveas(cp)
        cdoc = ezdxf.readfile(str(cp))
        msp = cdoc.modelspace()
        layers = {e.dxf.layer for e in msp}
        circles = len(msp.query("CIRCLE"))
        from ezdxf import bbox

        ext = bbox.extents(msp)
        size = (round(ext.size.x, 1), round(ext.size.y, 1))
        want = (spec["w"], spec["h"]) if name == "plate" else (spec["od"], spec["od"])
        check(
            f"part {name}: cut file is outline + holes only, 1:1 ({size[0]:g} x {size[1]:g} mm, {circles} circles)",
            layers == {"CUT"} and abs(size[0] - want[0]) < 0.2 and abs(size[1] - want[1]) < 0.2 and circles == holes + (2 if name == "flange" else 0),
            f"layers {layers}, size {size}, circles {circles}",
        )
    tight = dict(plate, holes=[{"d": 12.0, "pattern": "corners", "e": 9.0}])
    check(
        "part rule: holes 3 mm from the edge -> edge distance flagged",
        any(not c["ok"] and "edge distance" in c["what"] for c in P.part_checks(tight)),
    )
    out_ = dict(plate, holes=[{"d": 12.0, "pattern": "corners", "e": 4.0}])
    check(
        "part rule: a hole past the edge -> 'inside the plate' fails",
        any(not c["ok"] and c["level"] == "fail" and "inside the plate" in c["what"] for c in P.part_checks(out_)),
    )
    crowd = dict(plate, holes=[{"d": 20.0, "pattern": "row", "n": 12, "e": 15.0}])
    check("part rule: twelve 20 mm holes in a 200 mm row -> spacing fails", any(not c["ok"] and "apart" in c["what"] for c in P.part_checks(crowd)))
    wrong = dict(flange, pcd=160.0)
    check(
        "part rule: a bolt circle outside the flange -> fails", any(not c["ok"] and "bore < bolt circle" in c["what"] for c in P.part_checks(wrong))
    )
    rim = dict(flange, pcd=70.0, hole_d=18.0)
    check("part rule: bolt holes into the bore -> fails", any(not c["ok"] and "clear of the bore" in c["what"] for c in P.part_checks(rim)))


PHRASES = [
    (
        "a 5 marla house with 2 bedrooms",
        None,
        lambda o: o[0]["op"] == "house" and o[0]["brief"]["plot"] == [25, 45] and o[0]["brief"]["bedrooms"] == 2,
    ),
    ("1 kanal double story house with 5 bedrooms", None, lambda o: o[0]["brief"]["plot"] == [50, 90] and o[0]["brief"]["floors"] == 2),
    (
        "30x60 house, 3 bed, corner plot, facing north",
        None,
        lambda o: o[0]["brief"]["plot"] == [30, 60] and o[0]["brief"]["corner"] and o[0]["brief"]["facing"] == "north",
    ),
    ("ghar ka naqsha 5 marla 3 kamray", None, lambda o: o[0]["op"] == "house" and o[0]["brief"]["bedrooms"] == 3),
    ("a home for my family of six on a 10 marla plot", None, lambda o: o[0]["brief"]["bedrooms"] == 3 and o[0]["brief"]["plot"] == [35, 65]),
    ("make it double story", "house", lambda o: o == [{"op": "set", "brief": {"floors": 2}}]),
    ("add a store", "house", lambda o: o[0]["brief"] == {"store": True}),
    ("no car porch", "house", lambda o: o[0]["brief"] == {"porch": False}),
    ("make the kitchen bigger", "house", lambda o: o[0] == {"op": "grow", "room": "kitchen", "by": 1}),
    ("make the lounge a lot bigger", "house", lambda o: o[0] == {"op": "grow", "room": "lounge", "by": 2}),
    ("make the drawing room smaller", "house", lambda o: o[0] == {"op": "grow", "room": "drawing", "by": -1}),
    ("make bedroom 2 12 x 14", "house", lambda o: o[0] == {"op": "size", "room": "bed2", "w": 12.0, "d": 14.0}),
    ("can I fit 4 bedrooms?", "house", lambda o: o[0] == {"op": "ask", "what": "fit", "bedrooms": 4}),
    ("what's the covered area?", "house", lambda o: o[0]["what"] == "area"),
    ("how big is the lounge?", "house", lambda o: o[0] == {"op": "ask", "what": "room", "room": "lounge"}),
    ("give me the dwg", "house", lambda o: o[0] == {"op": "export", "fmt": "dwg"}),
    ("print it on A3", "house", lambda o: o[0] == {"op": "paper", "paper": "A3"}),
    ("scale 1:100", "house", lambda o: o[0] == {"op": "scale", "scale": 100}),
    ("call it Khan Residence", "house", lambda o: o[0]["brief"] == {"name": "Khan Residence"}),
    (
        "a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners and a 30 mm hole in the centre",
        None,
        lambda o: o[0]["spec"]["w"] == 200 and o[0]["spec"]["holes"][0]["e"] == 20 and o[0]["spec"]["holes"][1]["pattern"] == "center",
    ),
    (
        "a flange 150 od 60 bore 4 holes of 14 on 110 pcd 12 thick",
        None,
        lambda o: (o[0]["spec"]["od"], o[0]["spec"]["id"], o[0]["spec"]["pcd"]) == (150, 60, 110),
    ),
    (
        "flange OD 200 ID 80, 6 holes of 18 on a 150 PCD, 16 thick",
        None,
        lambda o: (o[0]["spec"]["od"], o[0]["spec"]["id"], o[0]["spec"]["n"]) == (200, 80, 6),
    ),
    ("make the holes 14", "part", lambda o: o[0]["spec"] == {"hole_size": 14.0}),
    ("move the holes 25 from the edges", "part", lambda o: o[0]["spec"] == {"hole_edge": 25.0}),
    ("remove the centre hole", "part", lambda o: o[0]["spec"] == {"drop_center": True}),
    ("make it 250 x 120", "part", lambda o: o[0]["spec"] == {"w": 250.0, "h": 120.0}),
    ("8 holes", "part", lambda o: o[0]["spec"] == {"hole_count": 8}),
    ("add a 30 mm hole in the centre", "part", lambda o: o[0]["spec"]["holes"] == [{"d": 30.0, "pattern": "center"}]),
    ("round the corners 10", "part", lambda o: o[0]["spec"] == {"corner": {"r": 10.0}}),
    ("give me the laser cut file", "part", lambda o: o[0] == {"op": "export", "fmt": "cut"}),
]


def phrases():
    for text, kind, ok in PHRASES:
        r = parse(text, kind)
        try:
            good = bool(r["ops"]) and ok(r["ops"])
        except (KeyError, IndexError, TypeError):
            good = False
        check(f"reads: {text[:70]}", good, str(r)[:200])


if __name__ == "__main__":
    t0 = time.perf_counter()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    units()
    planner()
    keep = drawings()
    spoiled(keep)
    parts()
    phrases()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.0f} s)")
    sys.exit(1 if FAILS else 0)
