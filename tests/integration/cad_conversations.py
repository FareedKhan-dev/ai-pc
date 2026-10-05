"""Conversations with the drafting agent, each turn checked on the drawing it made (the plan's rooms, the DXF, the
printed sheet): a family on a 5 marla plot (a bedroom that does not fit, double story, a kitchen that cannot grow, a
store with no room, undo and redo, the title block, exports); a 10 marla house (an exact bedroom size, a bigger
kitchen, straight stairs, a bigger sheet, a scale the sheet cannot hold); a 3 marla plot (no room for a porch);
plates and a flange for a laser cutter (hole sizes and edge distances, corners, hole counts, the cut file); and, with
the model, requests the rules cannot read.

  .venv\\Scripts\\python.exe tests\\integration\\cad_conversations.py [--offline]
--offline: rules only (the turns that need the model are skipped).
"""
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import ezdxf  # noqa: E402

from ai_pc.cad.cadchat import CadChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "cad" / "conv"
RESULTS = []


class Turn:
    def __init__(self, c, reply):
        self.c, self.reply = c, reply
        self.v = c.cur()

    def says(self, *rx):
        return all(re.search(r, self.reply, re.I) for r in rx)

    def room(self, rid):
        return next((r for r in self.v["info"]["summary"]["rooms"] if r["id"] == rid), None) if self.v and self.v["kind"] == "house" else None

    def ok(self):
        return self.v is not None and not [c for c in self.v["checks"] if not c["ok"] and c["level"] == "fail"]

    def texts(self):
        doc = ezdxf.readfile(self.v["files"]["dxf"])
        return " ".join([e.dxf.text for e in doc.modelspace().query("TEXT")] + [e.plain_text() for e in doc.modelspace().query("MTEXT")])


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
        s = time.perf_counter() - t0
        RESULTS.append((name, msg, good))
        print(f"{'ok  ' if good else 'FAIL'} [{s:4.1f}s] {msg}" + ("" if good else f"\n       why: {why}\n       reply: {reply[:400]}"))


def same_version(n):
    return lambda t: (t.c.state["cur"] == n, f"now v{t.c.state['cur']}, wanted v{n}")


def five_marla(planner):
    c = CadChat.start(chats_dir=OUT, planner=planner)
    w = {}

    def first(t):
        w["lounge"] = t.room("lounge")["w"]
        return (t.ok() and t.v["info"]["floors"] == 1 and t.says(r"BED ROOM 3 does not fit|first floor") and Path(t.v["files"]["pdf"]).exists()
                and t.v["info"]["paper"] == "A3", t.reply[:200])

    def lounge_grew(t):
        return (t.ok() and t.room("lounge")["w"] >= w["lounge"] + 5.5 and t.v["v"] == 2, f"lounge {t.room('lounge')['w']} vs {w['lounge']}")

    def named(t):
        tx = t.texts()
        return ("Ahmed House" in tx and "Mr Ahmed" in tx, tx[:120])

    def exported(t):
        p = Path(c.state["exports"][-1]["path"]) if c.state["exports"] else None
        return (p is not None and p.exists() and p.suffix == ".pdf" and "Ahmed House" in p.name, str(p))

    run("5 marla family", c, [
        ("a 5 marla house with 3 bedrooms", first),
        ("what's the covered area?", lambda t: (t.says(r"1,050 sq ft", r"5\.0 marla"), "")),
        ("can I fit 3 bedrooms?", lambda t: (t.says(r"double story"), "")),
        ("make it double story", lambda t: (t.ok() and t.v["info"]["floors"] == 2 and t.says(r"first floor added", r"23/23"), "")),
        ("make the kitchen bigger", lambda t: (t.says(r"can't get bigger") and t.c.state["cur"] == 1, "")),
        ("add a store", lambda t: (t.says(r"no room for a store", r"stays as v1") and t.c.state["cur"] == 1, "")),
        ("make the lounge bigger", lounge_grew),
        ("undo", same_version(1)),
        ("redo", same_version(2)),
        ("go back to v0", lambda t: (t.c.state["cur"] == 0 and t.v["info"]["floors"] == 1, "")),
        ("call it Ahmed House", lambda t: (t.ok() and t.v["spec"].get("name") == "Ahmed House", "")),
        ("client is Mr Ahmed", named),
        ("export the pdf", exported),
        ("give me the dwg", lambda t: (t.says(r"ODA", r"\.dxf") and Path(c.state["exports"][-1]["path"]).suffix == ".dxf", "")),
        ("how big is bedroom 1?", lambda t: (t.says(r"Bed Room 1: \d+'-\d", r"sq ft"), "")),
        ("any problems?", lambda t: (t.says(r"All checks pass|Notes"), "")),
        ("history", lambda t: (t.says(r"v0 house", r"<- now"), "")),
    ])


def ten_marla(planner):
    c = CadChat.start(chats_dir=OUT, planner=planner)
    w = {}

    def first(t):
        w["kitchen"] = t.room("kitchen")["area_sqft"]
        return (t.ok() and t.room("dining") is not None and sum(1 for r in t.v["info"]["summary"]["rooms"] if r["id"].startswith("bed") and "_" not in r["id"]) == 4, "")

    def bed2(t):
        r = t.room("bed2")
        w["kitchen"] = t.room("kitchen")["area_sqft"]
        return (t.ok() and abs(r["w"] - 132) < 0.6 and abs(r["d"] - 168) < 1.1, f"{r['size']}")

    def kitchen(t):  # bigger: more floor, and the other rooms changed as little as can be
        return (t.ok() and t.room("kitchen")["area_sqft"] >= w["kitchen"] + 5 or t.says(r"can't get bigger"), f"{t.room('kitchen')['size']}")

    run("10 marla", c, [
        ("make a 10 marla house plan with 4 bedrooms and a dining room", first),
        ("make bedroom 2 13 x 14", lambda t: (t.says(r"can't be 13' x 14'", r"without losing Bed Room 3", r"stays as v0") and t.c.state["cur"] == 0, "")),
        ("make bedroom 2 11 x 14", bed2),
        ("make the kitchen bigger", kitchen),
        ("straight stairs", lambda t: (t.ok() and abs(t.room("stairs")["w"] - 42) < 0.6, t.room("stairs")["size"])),
        ("on A2", lambda t: (t.ok() and t.v["info"]["paper"] == "A2", "")),
        ("scale 1:50", lambda t: (t.says(r"Couldn't draw that: at 1:50", r"fits A2") and t.v["info"]["scale"] != 50, "")),
        ("export the png", lambda t: (Path(c.state["exports"][-1]["path"]).suffix == ".png", "")),
        ("list the rooms", lambda t: (t.says(r"Ground floor: .*Dining", r"Bed Room 4"), "")),
    ])


def three_marla(planner):
    c = CadChat.start(chats_dir=OUT, planner=planner)
    run("3 marla", c, [
        ("3 marla house with 1 bedroom", lambda t: (t.ok() and t.room("porch") is None and t.says(r"no room for a car porch"), "")),
        ("can I fit 2 bedrooms?", lambda t: (t.says(r"^(Yes|Not on one floor)"), "")),
        ("make it double story", lambda t: (t.ok() and t.v["info"]["floors"] == 2, "")),
    ])


def parts(planner):
    c = CadChat.start(chats_dir=OUT, planner=planner)

    def holes(n):
        return lambda t: (t.v["info"]["holes"] == n and t.ok(), f"{t.v['info']['holes']} holes")

    def cut(t):
        p = Path(c.state["exports"][-1]["path"])
        doc = ezdxf.readfile(str(p))
        msp = doc.modelspace()
        return (p.exists() and {e.dxf.layer for e in msp} == {"CUT"} and len(msp.query("CIRCLE")) == 6, f"{p.name}")

    run("plates and a flange", c, [
        ("a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners and a 30 mm hole in the centre", holes(5)),
        ("make the holes 14", lambda t: (t.says(r"to look at: edge distance 13\.0 mm"), "")),
        ("move the holes 25 from the edges", lambda t: (t.ok() and not t.says(r"to look at"), "")),
        ("round the corners 10", lambda t: (t.ok() and t.v["spec"]["corner"] == {"r": 10.0}, "")),
        ("remove the centre hole", holes(4)),
        ("6 holes", holes(6)),
        ("give me the laser cut file", cut),
        ("make it 250 x 120", lambda t: (t.ok() and (t.v["spec"]["w"], t.v["spec"]["h"]) == (250.0, 120.0), "")),
        ("a flange OD 200 ID 80, 6 holes of 18 on a 150 PCD, 16 thick", lambda t: (t.ok() and t.v["spec"]["kind"] == "flange" and t.v["info"]["holes"] == 6, "")),
        ("8 holes", lambda t: (t.ok() and t.v["spec"]["n"] == 8, "")),
        ("make the holes 20", lambda t: (t.v["spec"]["hole_d"] == 20.0, "")),
        ("export the pdf on A3", lambda t: (t.v["info"]["paper"] == "A3" and Path(c.state["exports"][-1]["path"]).suffix == ".pdf", "")),
        ("undo", lambda t: (t.v["info"]["paper"] == "A4", t.v["info"]["paper"])),
    ])


def with_model(planner):
    c = CadChat.start(chats_dir=OUT, planner=planner)
    run("read by the model", c, [
        ("design me a place to live, plot is forty by eighty feet, need four sleeping rooms", lambda t: (
            t.ok() and t.v["info"]["plot"] == [40, 80] and sum(1 for r in t.v["info"]["summary"]["rooms"] if r["id"].startswith("bed") and "_" not in r["id"]) >= 3, t.reply[:200])),
        ("I'd like the cooking area to be roomier", lambda t: ((t.ok() and t.c.last_turn["llm"]) or t.says(r"can't get bigger"), t.reply[:200])),
    ])


if __name__ == "__main__":
    offline = "--offline" in sys.argv
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    planner = None
    if not offline:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    t0 = time.perf_counter()
    five_marla(planner)
    ten_marla(planner)
    three_marla(planner)
    parts(planner)
    if not offline:
        with_model(planner)
    bad = [(n, m) for n, m, g in RESULTS if not g]
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} turns right in {time.perf_counter() - t0:.0f} s (AI ${usd:.4f})" + ("" if not bad else "\nFAILED: " + "; ".join(f"{n}: {m}" for n, m in bad)))
    sys.exit(1 if bad else 0)
