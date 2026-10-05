"""End to end: an edit request in plain words -> plan (1 model call) -> CapCut project (pyCapCut, no clicking)
-> export through CapCut (the only screen step) -> verified video in out/video/. Prints where the time went.

  .venv\\Scripts\\python.exe video_demo.py "your request"

Media comes only from the project's media/ folder. Ctrl+Alt+Q stops the screen step.
"""
import sys
import time

from harness import capcut_export as ce
from harness import video_lane as vl
from harness.planner import ChatPlanner

DEFAULT = ("Make a 16:9 YouTube intro: 3 seconds of the eclosion clip from second 5 with the Peach Fuzz look and a slow "
           "zoom out, then 4 seconds of the astra demo from second 20 at 2x speed in black and white, a white flash "
           "between them, a bold yellow title 'MY CHANNEL' in the center for the first 2.5 seconds, a small white "
           "'subscribe' at the bottom from second 4 to the end, and the openrouter audio as music at 40% with a short fade in.")


def main():
    req = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    print(f"REQUEST: {req}\n", flush=True)
    t0 = time.perf_counter()
    files = vl.media_files()
    plan, plan_ms = vl.make_plan(req, ChatPlanner(), files)
    res = vl.build(plan, files)
    vl.save_plan(req, plan, res)
    print(f"plan  {plan_ms / 1000:5.1f} s  ->  {len(plan.get('clips') or [])} clips, {len(plan.get('texts') or [])} texts, "
          f"music={'yes' if plan.get('music') else 'no'}; canvas {plan.get('canvas')}")
    print(f"build {res['ms'] / 1000:5.2f} s  ->  {res['draft']} ({res['seconds']} s)" + (f"; notes: {res['notes']}" if res["notes"] else ""),
          flush=True)
    dest, info, export_s, steps = ce.export(res["draft"])
    total = time.perf_counter() - t0
    w, h = vl.CANVAS.get(str(plan.get("canvas", "16:9")), vl.CANVAS["16:9"])
    ok = abs(info["seconds"] - res["seconds"]) <= 0.3 and (info["width"], info["height"]) == (w, h)
    print("\nTIME SPLIT")
    print(f"  plan (model call)        {plan_ms / 1000:6.1f} s")
    print(f"  build project (pyCapCut) {res['ms'] / 1000:6.2f} s")
    for k, v in steps.items():
        print(f"  {k:24s} {v:6.1f} s")
    print(f"  TOTAL                    {total:6.1f} s")
    print(f"\nOUTPUT {dest}\n  {info}  ->  {'MATCHES the plan' if ok else 'DOES NOT match the plan (' + str(res['seconds']) + f' s, {w}x{h})'}")


if __name__ == "__main__":
    main()
