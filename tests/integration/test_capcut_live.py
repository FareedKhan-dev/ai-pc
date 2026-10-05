"""Live test on CapCut (custom-drawn UI, no UI Automation tree -> vision lane):
"open capcut, add any video randomly from downloads folder, apply a filter and export it".

  python tests/integration/test_capcut_live.py
"""

import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

from ai_pc import apps  # noqa: E402
from ai_pc.core.config import STATE  # noqa: E402
from ai_pc.desktop.agent import Agent  # noqa: E402
from ai_pc.desktop.grounder import make_grounder  # noqa: E402
from ai_pc.desktop.safety import Confirmer  # noqa: E402
from ai_pc.desktop.skills import SkillStore  # noqa: E402
from ai_pc.llm.planner import ChatPlanner  # noqa: E402

DOWNLOADS = Path(os.environ["USERPROFILE"]) / "Downloads"
# small clips only (quick export); the full-length movie file in Downloads is deliberately excluded
CANDIDATES = ["astra-demo.mp4", "eclosion.mp4", "qwen_3.8_max_v2-reddit.mp4"]


def breakdown(trace, total_s):
    """Where the time went, from the run's trace: planner calls per model, vision clicks, explicit waits."""
    import json

    calls, ground, waits, deep = {}, [0, 0.0], 0.0, None
    for line in open(trace, encoding="utf-8"):
        e = json.loads(line)
        if e["kind"] == "plan":
            c = calls.setdefault(e["model"], [0, 0.0])
            c[0] += 1
            c[1] += e.get("ms", 0) / 1000
        elif e["kind"] == "deep_plan":
            deep = (e.get("ms", 0) / 1000, bool(e.get("background")))
        elif e["kind"] == "act":
            m = re.search(r" in (\d+) ms", str(e.get("detail", "")))
            if e.get("op") in ("ground_click", "hover") and m:
                ground[0] += 1
                ground[1] += int(m.group(1)) / 1000
            if e.get("op") == "wait":
                waits += e.get("ms", 0) / 1000
    out = [f"    TIME SPLIT of {total_s:.0f} s:"]
    for m, (n, s) in calls.items():
        out.append(f"      planner {m}: {n} calls, {s:.1f} s (avg {s / n:.1f} s)")
    if deep:
        out.append(f"      deep plan: {deep[0]:.1f} s" + (" (in the background, overlapped with acting)" if deep[1] else ""))
    out.append(f"      vision clicks: {ground[0]}, {ground[1]:.1f} s finding targets")
    out.append(f"      explicit waits (app loading/exporting): {waits:.1f} s")
    return "\n".join(out)


def new_videos(since, roots):
    """Video files created/modified after `since` (independent check that an export really happened)."""
    found = []
    for root in roots:
        if not root.exists():
            continue
        base_depth = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= 3:
                dirs[:] = []
            for f in files:
                if f.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                    p = Path(dirpath) / f
                    try:
                        if p.stat().st_mtime >= since:
                            found.append((p, p.stat().st_size))
                    except OSError:
                        pass
    return found


if __name__ == "__main__":
    if apps.find_window(title_substr="CapCut", exclude=("code.exe",)):
        sys.exit("CapCut is already open; close it first so the test starts from a known state.")
    name = random.choice([c for c in CANDIDATES if (DOWNLOADS / c).exists()])
    goal = (
        f"open CapCut, add the video {name} from the Downloads folder ({DOWNLOADS / name}) to a new project, "
        f"apply any free (non-Pro) filter to it, and export it"
    )
    print(f"randomly chosen video: {name}\nGOAL: {goal}\n", flush=True)
    sk = STATE / "capcut_test_skills"
    shutil.rmtree(sk, ignore_errors=True)
    grounder = make_grounder()
    grounder.ensure()  # the click model is a background service (started once, like a daemon), not part of the task time
    agent = Agent(
        planner=ChatPlanner(),
        grounder=grounder,
        confirm=Confirmer("medium"),
        dry_run=False,
        store=SkillStore(sk),
        verbose=True,
        limits={"max_steps": 60, "max_llm_calls": 40, "max_seconds": 600},
    )
    t0 = time.time()
    r = agent.run(goal, app="CapCut", deep=True)
    took = time.time() - t0
    print(
        f"\n>>> ok={r.ok} lane={r.lane} answer={r.answer!r}\n    TOTAL {took:.1f} s | model calls {r.llm_calls} | steps {r.steps} | "
        f"{r.timings}" + (f"\n    error: {r.error}" if r.error else "") + f"\n    trace: {r.run_dir}"
    )
    print(breakdown(Path(r.run_dir) / "trace.jsonl", took))
    home = Path(os.environ["USERPROFILE"])
    vids = new_videos(t0, [home / "Videos", home / "Documents", home / "Desktop", home / "Downloads", Path(os.environ["LOCALAPPDATA"]) / "CapCut"])
    print("\nexported files found on disk:" if vids else "\nNO new video file found on disk (export did not happen)")
    for p, size in vids:
        print(f"    {p}  ({size / 1e6:.1f} MB)")
