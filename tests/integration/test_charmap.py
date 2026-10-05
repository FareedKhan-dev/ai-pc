"""Generalisation test on a classic Win32 app the agent has never seen: Character Map (harmless, multi-step).

python tests/integration/test_charmap.py
"""

import shutil
import sys
import time

from ai_pc import apps
from ai_pc.core.config import STATE  # noqa: E402
from ai_pc.desktop import inputs, uia  # noqa: E402
from ai_pc.desktop.agent import Agent  # noqa: E402
from ai_pc.desktop.grounder import Grounder  # noqa: E402
from ai_pc.desktop.safety import Confirmer  # noqa: E402
from ai_pc.desktop.skills import SkillStore  # noqa: E402
from ai_pc.llm.planner import ChatPlanner  # noqa: E402

GOAL = "using Character Map, find the Unicode code of the copyright symbol and tell me"
SK = STATE / "charmap_test_skills"
shutil.rmtree(SK, ignore_errors=True)
STORE = SkillStore(SK)


def win():
    return apps.find_window(title_substr="Character Map", exclude=("code.exe",))


def advanced_view_off():
    """Character Map remembers 'Advanced view'; switch it back off so the user's setting is unchanged."""
    h = win()
    if not h:
        h, _ = apps.launch("Character Map")
        time.sleep(0.8)
    snap = uia.snapshot(h)
    cb = next((e for e in snap.els if e.name.lower().startswith("advanced view")), None)
    if cb is not None:
        try:
            state = cb.el.GetCurrentPropertyValue(30086)  # ToggleState: 1 = on
            if state == 1:
                uia.invoke(cb)
                time.sleep(0.3)
        except Exception as e:  # noqa: BLE001
            print("  (could not reset Advanced view:", e, ")")


def close():
    h = win()
    if h:
        inputs.close_window(h)
        for _ in range(40):
            time.sleep(0.1)
            if not win():
                break


def run(verbose):
    a = Agent(planner=ChatPlanner(), grounder=Grounder(autostart=False), confirm=Confirmer("deny"), dry_run=False, store=STORE, verbose=verbose)
    r = a.run(GOAL, app="Character Map")
    print(
        f"\n>>> lane={r.lane} ok={r.ok} answer={r.answer!r}\n    total {r.ms} ms | model calls {r.llm_calls} | steps {r.steps} | {r.timings}"
        + (f"\n    error: {r.error}" if r.error else ""),
        flush=True,
    )
    return r


if __name__ == "__main__":
    if win():
        sys.exit("A Character Map window is already open; close it first so I don't touch yours.")
    try:
        advanced_view_off()
        close()
        print("=== first time (the agent has never seen Character Map)")
        run(True)
        for sk in STORE.list():
            print(
                f"\n  learned skill '{sk['name']}': "
                + " -> ".join(
                    f"{st['op']}({(st.get('loc') or {}).get('name') or st.get('text') or st.get('keys') or st.get('target') or ''})"
                    for st in sk["steps"]
                )
            )
        print("\n=== same task again, from the same starting state (should replay the learned skill)")
        advanced_view_off()
        close()
        run(False)
    finally:
        advanced_view_off()
        close()
