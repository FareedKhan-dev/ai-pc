"""Conversations with the 3D lane, each turn checked on what it made (the version's subject, settings and files, and its
own checks), not on what it said: a house described in everyday words, seen from the street, repainted, turned round in
a video and changed in plan; a title animation for a shop; a visiting card on a mug and a laptop; and a 3D file asked
about for printing and converted.

  .venv\\Scripts\\python.exe tests\\integration\\three_conversations.py [--offline]
About eight minutes. Chats are kept under out\\_tests\\three\\conv.
"""
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from ai_pc.three.threechat import ThreeChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "three" / "conv"
ENGINE = ROOT / "out" / "_tests" / "three" / "engine"
RESULTS = []


def passed(c):
    v = c.cur()
    return v is not None and not [x for x in v["checks"] if not x["ok"] and x["level"] == "fail"]


def run(name, c, turns):
    print(f"\n== {name}")
    for msg, test in turns:
        t0 = time.perf_counter()
        v_before = c.state["cur"]
        reply = c.say(msg)
        try:
            good, why = test(c, reply, v_before)
        except Exception as e:  # noqa: BLE001
            good, why = False, f"{type(e).__name__}: {e}"
        RESULTS.append((name, msg, good))
        llm = " [model]" if (c.last_turn or {}).get("llm") else ""
        print(f"{'ok  ' if good else 'FAIL'} > {msg}{llm}  ({time.perf_counter() - t0:.0f} s)")
        for line in reply.splitlines()[:3]:
            print(f"       {line[:170]}")
        if not good:
            print(f"     why: {why}")


def main():
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    for f in ("card.png", "cube.obj", "open_box.obj"):
        if (ENGINE / f).exists():
            shutil.copyfile(ENGINE / f, OUT / f)
    t0 = time.time()
    quiet = lambda *_: None  # noqa: E731

    c = ThreeChat.start(chats_dir=OUT / "chats", planner=planner, log=quiet)

    def new_house(c, r, b):
        v = c.cur()
        return v["subject"] == "house" and "plan3d" in v["outputs"] and passed(c), r[:120]

    def front(c, r, b):
        v = c.cur()
        return "front" in v["outputs"] and v["v"] != b and passed(c), str(v["params"]["views"])

    def repaint(c, r, b):
        col = c.cur()["params"].get("colors") or {}
        return col.get("wall") == "plaster_cream" and col.get("accent") == "wood_light" and passed(c), str(col)

    def orbit(c, r, b):
        v = c.cur()
        return "orbit" in v["outputs"] and Path(v["outputs"]["orbit"]).exists() and passed(c), str(list(v["outputs"]))

    def bigger_lounge(c, r, b):
        return c.cur()["v"] != b and "Plan:" in r and passed(c), r[:160]
    run("a house in everyday words", c, [
        ("can you show me what a 7 marla double storey house with 3 bedrooms would look like in 3D", new_house),
        ("I want to see it from the street", front),
        ("paint it beige and give the front some wooden texture", repaint),
        ("now spin the camera slowly around the whole house, 4 seconds is enough", orbit),
        ("the tv lounge feels small, can it be larger?", bigger_lounge),
    ])

    c = ThreeChat.start(chats_dir=OUT / "chats", planner=planner, log=quiet)

    def logo(c, r, b):
        p = c.cur()["params"]
        return c.cur()["subject"] == "text" and "pak motors" in p["text"].lower() and p.get("material") == "chrome" and passed(c), str(p)

    def tagline(c, r, b):
        p = c.cur()["params"]
        return bool(p.get("sub")) and "drive" in p["sub"].lower() and passed(c), str(p)
    run("a title animation for a shop", c, [
        ("make me a logo animation for 'Pak Motors' that looks like chrome", logo),
        ("put 'Drive your dream' underneath it", tagline),
    ])

    c = ThreeChat.start(chats_dir=OUT / "chats", planner=planner, log=quiet, files=[OUT / "card.png"])

    def mug(c, r, b):
        p = c.cur()["params"]
        return c.cur()["subject"] == "mockup" and p["kind"] == "mug" and passed(c), str(p)

    def laptop(c, r, b):
        return c.cur()["params"]["kind"] == "laptop" and passed(c), str(c.cur()["params"])
    run("a visiting card on things", c, [
        ("my client wants their visiting card card.png shown on a coffee mug", mug),
        ("show it on a laptop screen too instead", laptop),
    ])

    c = ThreeChat.start(chats_dir=OUT / "chats", planner=planner, log=quiet, files=[OUT / "open_box.obj"])

    def opened(c, r, b):
        return c.cur()["subject"] == "model" and passed(c), r[:120]

    def printable(c, r, b):
        return bool(re.search(r"not (?:yet|watertight)|open edges", r, re.I)), r

    def converted(c, r, b):
        o = c.cur()["outputs"]
        return "export" in o and o["export"].endswith(".stl") and passed(c), str(o)
    run("a 3D file for printing", c, [
        ("open the model open_box.obj", opened),
        ("can a 3D printer handle this?", printable),
        ("give it to me as an STL file", converted),
    ])

    ok = sum(1 for *_, g in RESULTS if g)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{ok}/{len(RESULTS)} turns right in {time.time() - t0:.0f} s; model ${usd:.4f}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
