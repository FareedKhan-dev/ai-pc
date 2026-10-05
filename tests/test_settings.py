"""Generalisation test on a different, larger app the agent has never seen: Windows Settings (read-only task).

  python tests/test_settings.py
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import apps, inputs  # noqa: E402
from harness.agent import Agent  # noqa: E402
from harness.config import STATE  # noqa: E402
from harness.grounder import Grounder  # noqa: E402
from harness.planner import ChatPlanner  # noqa: E402
from harness.safety import Confirmer  # noqa: E402
from harness.skills import SkillStore  # noqa: E402

GOAL = "find out which edition and version of Windows this PC is running and tell me"
SK = STATE / "settings_test_skills"
shutil.rmtree(SK, ignore_errors=True)
STORE = SkillStore(SK)


def settings_window():
    return apps.find_window(title_substr="Settings", exclude=("code.exe",))


def close_settings():
    h = settings_window()
    if h:
        inputs.close_window(h)
        for _ in range(40):
            time.sleep(0.1)
            if not settings_window():
                break


def run(verbose):
    a = Agent(planner=ChatPlanner(), grounder=Grounder(autostart=False), confirm=Confirmer("deny"), dry_run=False,
              store=STORE, verbose=verbose)
    r = a.run(GOAL, app="Settings")
    print(f"\n>>> lane={r.lane} ok={r.ok} answer={r.answer!r}\n    total {r.ms} ms | model calls {r.llm_calls} | steps {r.steps} | {r.timings}"
          + (f"\n    error: {r.error}" if r.error else ""), flush=True)
    return r


if __name__ == "__main__":
    if settings_window():
        sys.exit("A Settings window is already open; close it first so I don't touch yours.")
    try:
        print("=== first time (the agent has never seen Settings)")
        r1 = run(True)
        print("\n=== again from a fresh Settings window (should replay the learned skill)")
        close_settings()
        r2 = run(False)
        print("\n=== again with Settings already open on the result page")
        r3 = run(False)
    finally:
        close_settings()
