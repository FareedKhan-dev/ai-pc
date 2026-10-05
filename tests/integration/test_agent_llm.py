"""Real-model end-to-end test (Nebius): the agent learns tasks on Calculator by itself, then replays them as reflexes.

python tests/integration/test_agent_llm.py [easy] [unknown] [replay] [keep]
"""

import shutil
import sys
import time

from ai_pc import apps
from ai_pc.core.config import STATE  # noqa: E402
from ai_pc.desktop import inputs  # noqa: E402
from ai_pc.desktop.agent import Agent  # noqa: E402
from ai_pc.desktop.grounder import Grounder  # noqa: E402
from ai_pc.desktop.safety import Confirmer  # noqa: E402
from ai_pc.desktop.skills import SkillStore  # noqa: E402
from ai_pc.llm.planner import ChatPlanner  # noqa: E402

SK = STATE / "llm_test_skills"
if "keep" not in sys.argv:
    shutil.rmtree(SK, ignore_errors=True)
STORE = SkillStore(SK)
EASY = "calculate 12 + 30 and tell me the result"
UNKNOWN = "switch the calculator to Scientific mode, then compute the square root of 144 and tell me the result"
NL = chr(10)


def close_calc():
    h = apps.find_window(title_substr="Calculator", exclude=("code.exe",))
    if h:
        inputs.close_window(h)
        for _ in range(40):
            time.sleep(0.1)
            if not apps.find_window(title_substr="Calculator", exclude=("code.exe",)):
                break


def agent(verbose=True):
    return Agent(planner=ChatPlanner(), grounder=Grounder(autostart=False), confirm=Confirmer("deny"), dry_run=False, store=STORE, verbose=verbose)


def show(label, r):
    print(
        f"{NL}>>> {label}: ok={r.ok} lane={r.lane} answer={r.answer!r}{NL}    total {r.ms} ms | llm_calls {r.llm_calls} | steps {r.steps} | {r.timings}"
        + (f"{NL}    error: {r.error}" if r.error else "")
    )


def calc_in_mode(mode):
    """Open Calculator (if needed) and put it in Standard (Alt+1) or Scientific (Alt+2) mode, so every run starts from a known state."""
    from ai_pc.desktop import uia

    h = apps.find_window(title_substr="Calculator", exclude=("code.exe",))
    if not h:
        h, _ = apps.launch("calculator")
    inputs.set_foreground(h)
    t0 = time.time()
    while time.time() - t0 < 5 and uia.snapshot(h).richness < 6:
        time.sleep(0.1)
    inputs.hotkey("alt", "1" if mode == "standard" else "2")
    time.sleep(0.5)
    inputs.hotkey("esc")  # clear any leftover entry so every run starts from the same clean display
    time.sleep(0.2)
    return h


def t_easy():
    print(f"{NL}=== EASY (model plans, then the task is learned)")
    close_calc()
    show("first run (model in the loop)", agent().run(EASY, app="Calculator"))


def t_unknown():
    print(f"{NL}=== UNKNOWN TASK (multi-step; Calculator starts in Standard mode, the agent has never done this)")
    close_calc()
    calc_in_mode("standard")
    show("first run (model in the loop)", agent().run(UNKNOWN, app="Calculator"))


def t_replay():
    print(f"{NL}=== REPLAY (reflex lane, no model calls)")
    if STORE.match(EASY)[0]:
        close_calc()
        show("easy: replay from a cold start (launches Calculator)", agent(verbose=False).run(EASY, app="Calculator"))
        show("easy: replay with the app already open", agent(verbose=False).run(EASY, app="Calculator"))
    print(f"{NL}  -- the learned multi-step task, started from Standard mode (same state it was learned in)")
    close_calc()
    calc_in_mode("standard")
    show("unknown task replay, Standard start", agent(verbose=False).run(UNKNOWN, app="Calculator"))
    calc_in_mode("standard")
    show("unknown task replay again, Standard start", agent(verbose=False).run(UNKNOWN, app="Calculator"))
    print(f"{NL}  -- same goal, but Calculator now starts in Scientific mode: the Standard-mode skill must NOT be replayed blindly")
    calc_in_mode("scientific")
    show("Scientific start (expect planner lane, learns a 2nd variant)", agent(verbose=True).run(UNKNOWN, app="Calculator"))
    calc_in_mode("scientific")
    show("Scientific start again (expect skill lane)", agent(verbose=False).run(UNKNOWN, app="Calculator"))
    print(f"{NL}  learned skills:")
    for sk in STORE.list():
        print(f"    {sk['name']:<58s} steps={len(sk['steps'])} runs={sk['stats']['runs']} ok={sk['stats']['ok']} ms={sk['stats']['ms']}")
    close_calc()


def t_trials(n=3):
    """Reliability: learn the unknown task from scratch n times (clean skills, Standard mode), then replay each time."""
    rows = []
    for i in range(n):
        shutil.rmtree(SK, ignore_errors=True)
        close_calc()
        calc_in_mode("standard")
        r = agent(verbose=False).run(UNKNOWN, app="Calculator")
        learned = bool(STORE.match(UNKNOWN, None)[0])
        rep = None
        if learned:
            calc_in_mode("standard")
            rep = agent(verbose=False).run(UNKNOWN, app="Calculator")
        rows.append((r, learned, rep))
        print(
            f"  trial {i + 1}: learn ok={r.ok} answer={str(r.answer)[:40]!r} {r.ms} ms, {r.llm_calls} model calls, {r.steps} steps"
            f" | skill learned={learned}"
            + (f" | replay: lane={rep.lane} ok={rep.ok} answer={rep.answer!r} {rep.ms} ms" if rep else "")
            + (f" | error={r.error}" if r.error else ""),
            flush=True,
        )
    ok = sum(1 for r, _, _ in rows if r.ok and "12" in str(r.answer))
    print(
        f"{NL}  SUMMARY: learned correctly {ok}/{n}; skills saved {sum(1 for _, l, _ in rows if l)}/{n}; "
        f"replays correct {sum(1 for _, _, p in rows if p and p.ok and p.lane == 'skill' and '12' in str(p.answer))}/{n}"
    )
    close_calc()


if __name__ == "__main__":
    if apps.find_window(title_substr="Calculator", exclude=("code.exe",)):
        sys.exit("A Calculator window is already open; close it first so I don't touch yours.")
    want = [a for a in sys.argv[1:] if a != "keep"] or ["easy", "unknown", "replay"]
    try:
        for name in want:
            {"easy": t_easy, "unknown": t_unknown, "replay": t_replay, "trials": t_trials}[name]()
    finally:
        close_calc()
