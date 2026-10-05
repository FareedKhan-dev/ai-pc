"""Template mode, offline (no export): a learned template filled with other footage keeps the template's exact cut
frames, never uses a moment twice, lines the music's beats up with the cuts, puts the client's words where the
template has text, and follow-ups change footage / music / format but not the template's timing.

  .venv\\Scripts\\python.exe tests\\test_templates.py
Needs the 'gym_hype' template (learned from out/video/agent_no_180359.mp4; it is learned on the fly if missing).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from harness import analyze as AN  # noqa: E402
from harness import editplan as EP  # noqa: E402
from harness import template as TP  # noqa: E402
from harness.studio import load  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main():
    tpl = TP.load("gym_hype") or TP.learn(ROOT / "out" / "video" / "agent_no_180359.mp4", None, name="gym_hype", log=lambda *a: None)
    files = [f for f in load("agent_road_195510")["files"] if "music_" not in f]
    an = AN.analyze(files, planner=None, log=lambda *a: None)
    plan, info = TP.fill(tpl, an, request="travel in this template, title 'ROAD TRIP'", log=lambda *a: None)
    R = EP.resolve(plan, an)
    want = plan["_template"]["cuts"]
    got = [c["start"] for c in R["clips"][1:]]
    drift = max((abs(a - b) for a, b in zip(got, want)), default=0)
    check("every cut on the template's frame", len(got) == len(want) and drift < 0.002, f"{len(got)} vs {len(want)} cuts, drift {drift:.3f} s")
    check("same length as the template", abs(R["end"] - tpl["seconds"]) < 0.05, f"{R['end']} vs {tpl['seconds']}")
    spans = {}
    overlap = 0
    for c in R["clips"]:
        p = c["pieces"][0]
        for a0, a1 in spans.get(c["file"], []):
            if p["src_from"] < a1 - 0.05 and a0 < p["src_from"] + p["src_span"] - 0.05:
                overlap += 1
        spans.setdefault(c["file"], []).append((p["src_from"], p["src_from"] + p["src_span"]))
    check("no moment of footage used twice", overlap == 0, f"{overlap} overlaps")
    adj = sum(1 for a, b in zip(R["clips"], R["clips"][1:]) if a["file"] == b["file"])
    check("the same file rarely twice in a row", adj <= max(2, len(R["clips"]) // 10), f"{adj} times")
    m = next((e for e in plan["edits"] if e.get("id") == "music"), None)
    beat = 60.0 / round(tpl["bpm"]) if tpl.get("bpm") else None
    check("music at the template's tempo, offset under a beat", m is not None and beat and 0 <= m["from"] < beat + 1e-6,
          f"music {m and m.get('file')} from {m and m.get('from')}")
    texts = [e for e in R["edits"] if e["type"] == "text"]
    check("the client's words where the template has text", any(t["text"] == "ROAD TRIP" for t in texts), str([t["text"] for t in texts][:3]))
    kinds = {e["type"] for e in R["edits"]}
    check("the template's moves and transitions are there", {"transition", "shake"} <= kinds, str(sorted(kinds)))
    # follow-ups
    d = {"template": tpl["name"], "pins": {}, "avoid_files": [], "music": None, "canvas": plan["canvas"], "texts": None}
    beach = next(f for f in (Path(x).name for x in files) if "beach" in f)
    d2, done, failed = TP.apply_design(d, [{"op": "shot_move", "to": "first", "file": beach}, {"op": "pace", "mul": 0.8},
                                           {"op": "avoid_file", "file": next(Path(x).name for x in files if "motorcycle" in x)}])
    check("follow-ups: footage pinned and avoided, pacing refused (the template sets it)",
          len(done) == 2 and len(failed) == 1 and "template" in failed[0], f"done {done}, failed {failed}")
    p2 = TP.refill(d2, an, "", log=lambda *a: None)
    check("a pinned file opens the edit", p2["clips"][0]["file"] == beach, p2["clips"][0]["file"])
    check("an avoided file is gone", not any("motorcycle" in c["file"] for c in p2["clips"]))
    check("re-fill keeps the timing", [round(c["duration"], 3) for c in p2["clips"]] == [round(c["duration"], 3) for c in plan["clips"]])
    print("\n" + ("all passed" if not FAILS else f"{len(FAILS)} failed: {FAILS}"))


if __name__ == "__main__":
    main()
