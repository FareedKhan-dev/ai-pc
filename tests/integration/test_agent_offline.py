"""Offline end-to-end tests of the agent loop on real Calculator, with a deterministic stand-in for the language model.

  python tests/integration/test_agent_offline.py [mechanics] [safety] [dryrun] [vision]      (default: all)

Live sections briefly drive Calculator (UI Automation; the typed/vision parts also use the real keyboard/mouse for ~1 s).
"""
import re
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
from ai_pc.llm.planner import ScriptedPlanner  # noqa: E402

TMP_SKILLS = STATE / "test_skills"
shutil.rmtree(TMP_SKILLS, ignore_errors=True)
STORE = SkillStore(TMP_SKILLS)
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"   {'PASS' if cond else 'FAIL'}  {name} {detail}")


def ids_by_aid(obs):
    return {m.group(2): m.group(1) for m in re.finditer(r'^(e\d+) \w+ "[^"]*" \[(\w+)\]', obs, re.M)}


def display(obs):
    m = re.search(r'Text "(Display is [^"]*)"', obs)
    return m.group(1) if m else None


def keypad_planner(goal, obs, history):
    """Stand-in for the model: press 1 2 + 3 0 = by UIA, then read the display."""
    by = ids_by_aid(obs)
    if not history:
        seq = ["num1Button", "num2Button", "plusButton", "num3Button", "num0Button", "equalButton"]
        return {"thought": "press the keys", "actions": [{"op": "invoke", "id": by[a]} for a in seq]}
    return {"thought": "read the result", "done": True, "success": True, "answer": display(obs), "actions": []}


def typed_planner(goal, obs, history):
    """Stand-in for the model: type the expression; declares the numbers as skill parameters."""
    if not history:
        return {"thought": "type it", "actions": [{"op": "type", "text": "12+30="}]}
    return {"thought": "done", "done": True, "success": True, "answer": display(obs), "actions": [],
            "skill": {"intent": "calculate {a} + {b}", "params": {"a": "12", "b": "30"}}}


def vision_planner(goal, obs, history):
    if not history:
        return {"thought": "click by vision", "actions": [{"op": "ground_click", "target": t} for t in
                                                         ("the 7 button", "the plus button", "the 8 button", "the equals button")]}
    return {"thought": "done", "done": True, "success": True, "answer": display(obs), "actions": []}


def new_agent(fn, dry=False, confirm="deny", grounder=None):
    return Agent(planner=ScriptedPlanner(fn), grounder=grounder, confirm=Confirmer(confirm), dry_run=dry, store=STORE, verbose=False)


def normal_calc():
    """Known starting state for layout-sensitive tests: restored (not maximised) window, Standard mode, cleared."""
    import ctypes

    from ai_pc.desktop import uia
    h = apps.find_window(title_substr="Calculator", exclude=("code.exe",))
    if not h:
        h, _ = apps.launch("calculator")
    t0 = time.time()
    while time.time() - t0 < 5 and uia.snapshot(h).richness < 6:
        time.sleep(0.1)
    if ctypes.windll.user32.IsZoomed(h):
        ctypes.windll.user32.ShowWindow(h, 9)  # SW_RESTORE
        time.sleep(0.4)
    inputs.set_foreground(h)
    inputs.hotkey("alt", "1")
    time.sleep(0.4)
    inputs.hotkey("esc")
    time.sleep(0.2)
    return h


def close_calc():
    h = apps.find_window(title_substr="Calculator", exclude=("code.exe",))
    if h:
        inputs.close_window(h)
        for _ in range(40):
            time.sleep(0.1)
            if not apps.find_window(title_substr="Calculator", exclude=("code.exe",)):
                break


def summary(res):
    return f"[{res.lane}] ok={res.ok} answer={res.answer!r} total={res.ms}ms llm_calls={res.llm_calls} steps={res.steps} timings={res.timings}" + (f" error={res.error}" if res.error else "")


def t_mechanics():
    print("\n== MECHANICS: planner lane -> compiled skill -> reflex replay")
    ag = new_agent(keypad_planner)
    r1 = ag.run("calculate 12 plus 30 with the keypad", app="Calculator")
    print("  run 1:", summary(r1))
    check("run 1 succeeded via planner", r1.ok and r1.lane == "planner" and "42" in str(r1.answer))
    check("skill saved", r1.skill and STORE.get(r1.skill) is not None, f"({r1.skill})")
    # second run: same goal, fresh agent object -> must take the skill path with zero model calls
    ag2 = new_agent(keypad_planner)
    ms_list = []
    for _ in range(5):  # Calculator stays open between replays so the number is the agent's own time, not app start-up
        r2 = ag2.run("calculate 12 plus 30 with the keypad", app="Calculator")
        ms_list.append(r2.ms)
        print("  replay:", summary(r2))
    check("replay used the skill with 0 model calls", r2.ok and r2.lane == "skill" and r2.llm_calls == 0 and "42" in str(r2.answer))
    print(f"  >>> reflex replay (6 UIA steps + read result): median {sorted(ms_list)[len(ms_list) // 2]} ms, best {min(ms_list)} ms")
    close_calc()
    r2c = new_agent(keypad_planner).run("calculate 12 plus 30 with the keypad", app="Calculator")
    print(f"  >>> including cold start of the app (launch + UI ready): {r2c.ms} ms")
    sk = STORE.get(r1.skill)
    print(f"  skill stats: {sk['stats']}")

    print("\n  -- parametric skill (typed keys)")
    close_calc()
    r3 = new_agent(typed_planner).run("calculate 12 + 30", app="Calculator")
    print("  run 3:", summary(r3))
    check("typed run succeeded", r3.ok and "42" in str(r3.answer))
    sk = STORE.get(r3.skill) if r3.skill else None
    check("compiled as a parametric skill", bool(sk and sk["params"] == ["a", "b"]), f"({sk['intent'] if sk else None}, steps={sk['steps'] if sk else None})")
    for goal, want in (("calculate 7 + 5", "12"), ("calculate 100 + 23", "123"), ("calculate 9 + 9", "18")):
        r = new_agent(typed_planner).run(goal, app="Calculator")
        print(f"  '{goal}':", summary(r))
        check(f"reused with new numbers: {goal}", r.ok and r.lane == "skill" and r.llm_calls == 0 and want in str(r.answer))
    close_calc()


def t_safety():
    print("\n== SAFETY")
    # 1) an attempt to press the window's Close button must be stopped (confirm=deny) and Calculator must survive
    def evil(goal, obs, history):
        by = ids_by_aid(obs)
        return {"thought": "close it", "risk": "low", "actions": [{"op": "invoke", "id": by["Close"]}]}
    r = new_agent(evil).run("tidy up the calculator window", app="Calculator")
    print("  close-button attempt:", summary(r))
    check("close button blocked (declined)", (not r.ok) and "Declined" in str(r.error))
    check("calculator still open", apps.find_window(title_substr="Calculator", exclude=("code.exe",)) is not None)
    # 2) prompt injection text on screen does not matter to the safety layer: classify by the element, not by who asked
    from ai_pc.desktop import safety
    from ai_pc.desktop.uia import El
    mk = lambda name, aid="", pw=False: El("e1", "Button", name, aid, "", (0, 0, 10, 10), True, False, pw, ("invoke",))  # noqa: E731
    cases = [("Delete all files", "high"), ("Empty recycle bin", "high"), ("Buy now", "high"), ("Close", "medium"), ("Seven", "low"), ("Equals", "low")]
    for name, want in cases:
        v = safety.classify({"op": "invoke"}, mk(name), "calculate 1 + 1", "calculator.exe")
        check(f"classify {name!r} -> {want}", v.level == want, f"(got {v.level})")
    check("password field blocked", safety.classify({"op": "type"}, mk("Password", pw=True), "", "app.exe").level == "block")
    check("terminal app blocked", safety.classify({"op": "invoke"}, mk("Run"), "", "powershell.exe").level == "block")
    check("IDE blocked", safety.classify({"op": "invoke"}, mk("Run"), "", "code.exe").level == "block")
    check("win+r blocked", safety.classify({"op": "key", "keys": ["win", "r"]}, None, "", "x.exe").level == "block")
    check("alt+f4 medium", safety.classify({"op": "key", "keys": ["alt", "f4"]}, None, "", "x.exe").level == "medium")
    # intended medium action passes without a prompt, unintended needs confirmation
    v = safety.classify({"op": "invoke"}, mk("Close"), "close the calculator", "x.exe")
    try:
        safety.decide(v, Confirmer("deny"), "close the calculator")
        ok = True
    except Exception:
        ok = False
    check("'close' allowed when the user asked for it", ok)
    # 3) a mis-grounded vision click (the grounder points at Maximize while we asked for "the 7 button") is refused
    import ctypes

    from ai_pc.desktop import uia

    class WrongGrounder:  # stands in for TinyClick returning a bad point
        def __init__(self, pt):
            self.pt = pt

        def ensure(self):
            return True

        def alive(self):
            return True

        def prefetch(self, img):
            pass

        def load(self, img):
            return 0.0

        def find(self, target, beams=3):
            return {"point": self.pt}

        def ground(self, img, target, beams=3):
            return {"point": self.pt, "ms": 1.0, "load_ms": 0.0}

    h = normal_calc()
    snap = uia.snapshot(h)
    mx = next(e for e in snap.els if e.aid == "Maximize")
    wl, wt = snap.rect[0], snap.rect[1]
    ag = new_agent(evil, grounder=WrongGrounder((mx.center[0] - wl, mx.center[1] - wt)))
    ag._begin("calculate 7 by vision")
    ag._prepare("Calculator")
    ag._observe()
    r = ag._exec({"op": "ground_click", "target": "the 7 button"})
    ag.trace_f.close()
    check("mis-grounded vision click refused", (not r["ok"]) and "refused vision click" in r["detail"], f"({r['detail'][:90]})")
    check("window was not maximised", not ctypes.windll.user32.IsZoomed(h))
    # 4) kill switch
    ag = new_agent(keypad_planner)
    ag._begin("kill test")
    ag.kill.trip()
    try:
        ag._exec({"op": "wait", "ms": 1})
        killed = False
    except safety.Aborted:
        killed = True
    check("kill switch aborts the next action", killed)
    close_calc()


def t_dryrun():
    print("\n== DRY RUN (must not touch the app)")
    close_calc()
    h, _ = apps.launch("calculator")
    time.sleep(1)
    r = new_agent(keypad_planner, dry=True).run("calculate 12 plus 30 with the keypad dry", app="Calculator")
    print("  ", summary(r))
    from ai_pc.desktop import uia
    snap = uia.snapshot(h)
    shown = next((e.name for e in snap.els if e.aid == "CalculatorResults"), None)
    check("dry run planned but changed nothing", r.ok and shown == "Display is 0", f"(display={shown!r})")
    close_calc()


def t_vision():
    print("\n== VISION LANE (TinyClick on the Arc GPU clicks Calculator keys by description)")
    g = Grounder()
    t = time.perf_counter()
    g.ensure()
    print(f"  grounder ready in {(time.perf_counter() - t) * 1000:.0f} ms")
    close_calc()
    normal_calc()
    ag = new_agent(vision_planner, grounder=g)
    ag.verbose = True
    r = ag.run("calculate 7 plus 8 by clicking with vision", app="Calculator")
    print("  ", summary(r))
    check("vision clicks produced 7 + 8 = 15", r.ok and "15" in str(r.answer))
    close_calc()


if __name__ == "__main__":
    if apps.find_window(title_substr="Calculator", exclude=("code.exe",)):
        sys.exit("A Calculator window is already open; close it first so I don't touch yours.")
    want = sys.argv[1:] or ["mechanics", "safety", "dryrun", "vision"]
    try:
        for name in want:
            {"mechanics": t_mechanics, "safety": t_safety, "dryrun": t_dryrun, "vision": t_vision}[name]()
    finally:
        close_calc()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed" + (f"  FAILED: {bad}" if bad else ""))
