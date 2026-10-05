"""The agent loop.

  goal -> [skill match?] -> REFLEX replay (no model calls, milliseconds)
                         -> otherwise QUICK PLANNER loop (observe -> plan -> safety -> act -> verify), escalating to the
                            DEEP THINKER when stuck; vision (screenshot + TinyClick grounder) only when the UI tree is thin
  success -> compiled into a skill, so the next run of the same task takes the reflex path.

Every step is timed; every action passes the safety layer; a kill switch (Ctrl+Alt+Q) aborts the run.
"""
import json
import re
import threading
import time
from dataclasses import dataclass, field

import win32gui
import win32process

from ai_pc.core.config import BLOCKED_PROCS, LIMITS, RUNS
from ai_pc.core.util import Timer, slug
from ai_pc.desktop import appknow, apps, inputs, observe, safety, screen, uia
from ai_pc.desktop.safety import Aborted, Declined, SafetyBlock
from ai_pc.desktop.skills import SkillStore, compile_skill, fill, struct_keys

ID_OPS = {"invoke", "click", "focus", "set_text"}
INPUT_OPS = {"type", "key", "click", "scroll", "ground_click", "set_text", "drag", "click_xy", "hover"}
TEXT_ROLES = ("Text", "Edit", "Document")


class ReplayFail(Exception):
    pass


_NUM = dict(zip("0123456789", ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")))
_SYM = {"+": "plus", "-": "minus", "*": "multiply", "/": "divide", "=": "equals"}
_STOP = {"the", "a", "an", "button", "icon", "item", "in", "on", "at", "of", "to", "left", "right", "top", "bottom",
         "sidebar", "menu", "tab", "panel", "click", "and", "with", "num", "btn", "control"}
_UNJUDGEABLE = {"Pane", "Group", "Custom", "Window", "Document", "Image"}


def _tokens(text):
    text = re.sub(r"([a-z])([A-Z0-9])", lambda m: m.group(1) + " " + m.group(2), text or "")  # num7Button -> num 7 Button
    out = set()
    for w in re.findall(r"[a-zA-Z]+|\d|[+\-*/=]", text):
        w = _NUM.get(w, _SYM.get(w, w.lower()))
        if w not in _STOP and len(w) > 1:
            out.add(w)
    return out


def _target_matches(target, under):
    """Is the element under the pointer plausibly the target that was described? Unnamed or container elements cannot be
    judged (custom-drawn apps) and pass; a named control sharing no word with the description fails."""
    if not under or not (under.get("name") or "").strip() or under.get("role") in _UNJUDGEABLE:
        return True
    t, u = _tokens(target), _tokens(f"{under.get('name', '')} {under.get('aid', '')}")
    if not t or not u:
        return True
    import difflib
    return bool(t & u) or any(difflib.SequenceMatcher(None, x, y).ratio() > 0.8 for x in t for y in u)


@dataclass
class RunResult:
    ok: bool
    answer: object = None
    lane: str = ""
    steps: int = 0
    ms: float = 0.0
    llm_calls: int = 0
    skill: str = None
    timings: dict = field(default_factory=dict)
    run_dir: str = ""
    error: str = None


class Agent:
    def __init__(self, planner=None, grounder=None, confirm=None, dry_run=True, allow_apps=(), verbose=True,
                 limits=None, store=None):
        self.planner, self.grounder = planner, grounder
        self.confirm = confirm or safety.Confirmer("deny")
        self.dry_run = dry_run
        self.allow_apps = {a.lower() for a in allow_apps}
        self.verbose = verbose
        self.limits = {**LIMITS, **(limits or {})}
        self.store = store or SkillStore()
        self.kill = safety.KillSwitch()
        self.hwnd = self.pid = self.main_hwnd = None
        self.snap = None
        self._watch = []
        self._shot = None
        self._appctx = {}  # pid -> the app's own keyboard shortcuts, rendered for the planner

    # ------------------------------------------------------------------ logging
    def _log(self, kind, **kw):
        ev = {"t": round(time.perf_counter() - self.t0, 3), "kind": kind, **kw}
        if self.trace_f:
            self.trace_f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            self.trace_f.flush()
        if self.verbose:
            extra = {k: v for k, v in kw.items() if k not in ("actions",)}
            line = f"  [{ev['t']:6.2f}s] {kind:<10s} " + " ".join(f"{k}={str(v)[:90]}" for k, v in extra.items())
            try:
                print(line, flush=True)
            except UnicodeEncodeError:  # Windows consoles (cp1252) cannot show every character a window may contain
                print(line.encode("ascii", "backslashreplace").decode(), flush=True)

    def _begin(self, goal):
        self.goal = goal
        self.t0 = time.perf_counter()
        self.t = {"observe": 0.0, "plan": 0.0, "act": 0.0, "settle": 0.0, "ground": 0.0}  # ground is part of act
        self.steps = self.llm_calls = 0
        self.rec = []
        self.messy = []
        self.pre_struct = None
        self.plan_snap = None   # the snapshot the planner's ids refer to (frozen per plan; see _target)
        self._last_el = None
        self.run_dir = RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug(goal, 30)}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace_f = open(self.run_dir / "trace.jsonl", "w", encoding="utf-8")
        self._shot = None
        self._missed = set()  # vision targets that were clicked without the expected effect: look closer next time

    # ------------------------------------------------------------------ windows
    def _set_window(self, hwnd):
        self.hwnd = self.main_hwnd = hwnd
        self.pid = uia.window_info(hwnd)["pid"] if hwnd else None

    def _app_main_window(self):
        """Largest visible titled top-level window of the target app (a splash screen dies; the real window lives)."""
        if not self.pid:
            return None
        best, area = None, 0
        for h in apps.visible_windows():
            info = uia.window_info(h)
            if info["pid"] != self.pid:
                continue
            l, t, r, b = info["rect"]
            a = max(0, r - l) * max(0, b - t)
            if a > area:
                best, area = h, a
        return best

    @staticmethod
    def _area(h):
        l, t, r, b = win32gui.GetWindowRect(h)
        return max(0, r - l) * max(0, b - t)

    def _current_hwnd(self):
        """The window to observe. Follows a dialog or menu that the same app opened, but not tooltips, previews or
        other title-less helper popups (observing those would hide the real UI from the planner)."""
        if self.main_hwnd and not win32gui.IsWindow(self.main_hwnd):
            self.main_hwnd = self._app_main_window()
        if self.hwnd and not win32gui.IsWindow(self.hwnd):
            self.hwnd = self.main_hwnd
        big = self._app_main_window() if self.main_hwnd else None
        if big and big != self.main_hwnd and self._area(big) > 1.5 * self._area(self.main_hwnd):
            if self.hwnd == self.main_hwnd:
                self.hwnd = big
            self.main_hwnd = big  # e.g. the splash screen was replaced by the real main window
        if self.hwnd:
            fg = inputs.foreground()
            if fg and fg != self.hwnd and win32gui.IsWindowVisible(fg):
                info = uia.window_info(fg)
                same_app = info["pid"] == self.pid or safety.root_owner(fg) == safety.root_owner(self.hwnd)
                real = bool(info["title"].strip()) or info["cls"] in ("#32770", "#32768")  # dialog / menu
                if same_app and real:
                    self.hwnd = fg
            if self.hwnd != self.main_hwnd and self.main_hwnd and win32gui.IsWindow(self.main_hwnd) \
                    and inputs.foreground() == self.main_hwnd:
                self.hwnd = self.main_hwnd  # the dialog closed and the main window is in front again
        return self.hwnd

    def _fg_ok(self):
        fg = inputs.foreground()
        info = uia.window_info(fg)
        if safety.foreground_ok(self.hwnd, self.pid, fg, info["pid"]):
            return
        inputs.set_foreground(self.hwnd)
        fg = inputs.foreground()
        if not safety.foreground_ok(self.hwnd, self.pid, fg, uia.window_info(fg)["pid"]):
            raise SafetyBlock("the target window lost focus; refusing to send input to another window")

    def _prepare(self, app):
        if not app:
            self._set_window(None)
            return
        h = apps.find_window(title_substr=app, exclude=BLOCKED_PROCS) or apps.find_window(proc=app.lower() + ".exe", exclude=BLOCKED_PROCS)
        if not h:
            if self.dry_run:
                self._log("prepare", note=f"would launch {app}")
                return
            h, info = apps.launch(app)
            if not h:
                raise SafetyBlock(f"could not open {app}: {info}")
            self._fresh = True
        proc = uia.window_info(h)["proc"]
        if proc in BLOCKED_PROCS and proc not in self.allow_apps:
            raise SafetyBlock(f"{proc} is on the blocked list")
        self._set_window(h)
        fg = inputs.set_foreground(h) if not self.dry_run else None
        self._log("prepare", window=uia.window_info(h)["title"], proc=proc, foreground=fg)

    # ------------------------------------------------------------------ observation
    _fresh = False

    def _observe(self):
        t = Timer()
        hwnd = self._current_hwnd()
        if not hwnd:
            self.snap, self._watch = None, []
            return "APP: (none) | no target window is selected. Use open_app to start the app you need."
        snap = uia.snapshot(hwnd, self.limits["max_elements"])
        if not snap.els and hwnd != self.main_hwnd and self.main_hwnd and win32gui.IsWindow(self.main_hwnd):
            self.hwnd = hwnd = self.main_hwnd  # followed a popup with nothing in it: go back to the main window
            snap = uia.snapshot(hwnd, self.limits["max_elements"])
        if self._fresh:
            # a just-launched app builds its window over a moment (a UWP frame shows its caption buttons before the
            # content): wait until the control count and the pixels both hold still, instead of the first non-empty tree
            t0, last_n, last_sig, still = time.time(), -1, None, 0
            while time.time() - t0 < 5.0:
                sig = screen.signature(screen.grab(snap.rect))
                if snap.richness == last_n and last_sig is not None and not screen.changed(sig, last_sig):
                    still += 1
                    if still >= 3 and (snap.richness > 3 or time.time() - t0 > 1.5):
                        break
                else:
                    still = 0
                last_n, last_sig = snap.richness, sig
                time.sleep(0.1)
                snap = uia.snapshot(hwnd, self.limits["max_elements"])
            self._fresh = False
        if snap.proc in BLOCKED_PROCS and snap.proc not in self.allow_apps:
            raise SafetyBlock(f"{snap.proc} is on the blocked list")
        self.snap = snap
        self._watch = [e for e in snap.els if e.role in TEXT_ROLES][:12] + [e for e in snap.els if e.focus][:1]
        self.t["observe"] += t.ms()
        return observe.render(snap)

    def _app_windows(self):
        """Visible top-level windows of the target app, including untitled popups (Qt menus are separate windows)."""
        if not self.pid:
            return frozenset()
        out = []

        def cb(h, _):
            if win32gui.IsWindowVisible(h) and win32process.GetWindowThreadProcessId(h)[1] == self.pid:
                out.append(h)
        win32gui.EnumWindows(cb, None)
        return frozenset(out)

    def _app_context(self):
        """The app's own keyboard shortcuts, read once per app from its keymap file (if it ships one)."""
        if not self.pid:
            return ""
        if self.pid not in self._appctx:
            try:
                self._appctx[self.pid] = appknow.shortcuts_text(self.pid)
            except Exception:  # noqa: BLE001
                self._appctx[self.pid] = ""
            if self._appctx[self.pid]:
                self._log("app_shortcuts", n=self._appctx[self.pid].count("="), source=appknow.last_source)
        txt = self._appctx[self.pid]
        return "\n\n" + txt if txt else ""

    def _sig(self):
        """What the window looks like right now: text labels (cheap, catch digit changes), a pixel thumbnail
        (catches panes, dialogs and mode switches that change no text) and the app's set of windows (a dialog or
        popup menu opening is progress even where it barely changes the main window's pixels)."""
        names = tuple((uia.live_name(e), uia.get_value(e) if (e.role in ("Edit", "ComboBox") and not e.password) else None)
                      for e in self._watch)
        return ("hybrid", names, screen.signature(screen.grab(self.snap.rect)), self._app_windows())

    @staticmethod
    def _differs(a, b):
        return a[1] != b[1] or screen.changed(a[2], b[2]) or a[3:] != b[3:]

    @staticmethod
    def _struct(snap):
        return frozenset((e.aid or e.name, e.role) for e in snap.els if e.ops)

    @staticmethod
    def _state(snap):
        """Everything the UI tree says about the window: texts, field values, toggles, enabled flags, layout."""
        return (snap.rect, frozenset((e.aid or e.name, e.role, e.name, e.value, e.toggled, e.enabled) for e in snap.els))

    @staticmethod
    def _nav_changed(old, new):
        """True when the set of interactable controls changed a lot (a page/dialog/mode switch), not just a button label."""
        return old is not None and len(old ^ new) >= max(4, int(0.2 * len(old)))

    @staticmethod
    def _texts(snap):
        return {(e.aid or f"t{i}"): e.name for i, e in enumerate(x for x in snap.els if x.role in TEXT_ROLES)}

    def _settle(self, sig0, max_ms=400):
        """Wait until the screen/UI reacts and stops changing (adaptive: polls every few ms, never a fixed sleep)."""
        t = Timer()
        changed, last, quiet = False, sig0, 0
        poll = 0.02
        while t.ms() < max_ms:
            time.sleep(poll)
            cur = self._sig()
            if self._differs(cur, sig0):
                changed = True
                quiet = quiet + 1 if not self._differs(cur, last) else 0
                if quiet >= 1:
                    break
            last = cur
        self.t["settle"] += t.ms()
        return changed

    def _check_expect(self, expect):
        if not expect:
            return True, ""
        t = Timer()
        while t.ms() < 1200:
            if "text_contains" in expect:
                want = str(expect["text_contains"]).lower()
                names = [uia.live_name(e) or "" for e in self._watch]
                if any(want in n.lower() for n in names):
                    return True, ""
                if t.ms() > 150:
                    self._observe()
                    if any(want in e.name.lower() for e in self.snap.els):
                        return True, ""
            elif "element" in expect:
                want = str(expect["element"]).lower()
                self._observe()
                if any(want in e.name.lower() for e in self.snap.els):
                    return True, ""
            else:
                return True, ""
            time.sleep(0.04)
        return False, f"expectation {expect} not met"

    # ------------------------------------------------------------------ acting
    def _screenshot_for_planner(self):
        region = self.snap.rect if self.snap else None
        img = screen.grab(region)
        self._shot = (img, screen.signature(img))
        self._shot_geom = ((region or (0, 0))[0], (region or (0, 0))[1], img.width / min(img.width, 1280))
        if self.grounder and self.grounder.alive():
            self.grounder.prefetch(img)  # encode on the GPU while the planner thinks
        jpeg = screen.thumb_jpeg(img)
        (self.run_dir / f"shot_{self.llm_calls}.jpg").write_bytes(jpeg)
        return jpeg

    def _observe_stable(self, max_ms=1200, ref_struct=None):
        """Observe; if the UI structure is still changing (a page or mode being built), keep observing until two
        snapshots in a row agree. Planning on a half-built UI hands the planner ids of controls that are being replaced."""
        t = Timer()
        obs = self._observe()
        if self.snap is None:
            return obs
        prev = self._struct(self.snap)
        if ref_struct is not None and prev == ref_struct:
            return obs  # nothing structural happened: one snapshot is enough
        while t.ms() < max_ms:
            time.sleep(0.04)
            obs = self._observe()
            cur = self._struct(self.snap)
            if cur == prev:
                break
            prev = cur
        return obs

    def _target(self, a):
        """The element an id-based action refers to, guarded against (1) the planner's id not matching the name it
        meant and (2) a UI that rebuilt itself since the snapshot (stale or recycled handles)."""
        snap = self.plan_snap or self.snap
        if snap is None:
            return None, "no window"
        el = snap.by_id(str(a.get("id")))
        want = str(a.get("name") or "").strip().lower()
        if want and (el is None or el.name.strip().lower() != want):
            alt = [e for e in snap.els if e.name.strip().lower() == want]
            if alt:
                self._log("id_fix", id=a.get("id"), wanted=a.get("name"), was=el.name if el else None, used=alt[0].id)
                el = alt[0]
        if el is None:
            return None, f"unknown element id {a.get('id')!r}"
        live = uia.live_name(el)
        if live is None or live != el.name:
            loc = uia.locator_of(el)
            self._observe_stable(max_ms=800)
            fresh = uia.find_best(self.snap, loc)
            self._log("rebind", id=el.id, name=el.name, live=live, found=bool(fresh))
            if fresh is None:
                return None, f"element '{el.name}' is gone (the UI changed)"
            el = fresh
        return el, ""

    def _exec(self, a):
        self.kill.check()
        op, t = a.get("op"), Timer()
        el = None
        if op in ID_OPS:
            el, why = self._target(a)
            if el is None:
                return {"ok": False, "detail": why, "ms": t.ms()}
            self._last_el = el
            if not el.enabled and op != "focus" and not uia.is_enabled(el):  # cached state may be stale: ask live
                return {"ok": False, "detail": f"element {el.id} '{el.name}' is disabled", "ms": t.ms()}
        chk = el
        if chk is None and op == "type" and self.snap:
            chk = next((e for e in self.snap.els if e.focus), None)
        proc = self.snap.proc if self.snap else ""
        verdict = safety.classify(a, chk, self.goal, proc, self.allow_apps)
        if verdict.level != "low":
            self._log("safety", op=op, level=verdict.level, why=verdict.reason)
        safety.decide(verdict, self.confirm, self.goal)
        if self.dry_run:
            return {"ok": True, "detail": "dry-run: not executed", "ms": t.ms(), "dry": True}
        if op in INPUT_OPS:
            self._fg_ok()
        try:
            if op == "invoke":
                ok, how = uia.invoke(el)
                if not ok and how == "no pattern":
                    self._fg_ok()
                    inputs.click(*el.center)
                    ok, how = True, "mouse click (no UIA pattern)"
                return {"ok": ok, "detail": how, "ms": t.ms()}
            if op == "click":
                inputs.click(*el.center, double=bool(a.get("double")))
                return {"ok": True, "detail": "mouse click", "ms": t.ms()}
            if op == "focus":
                ok, how = uia.focus(el)
                return {"ok": ok, "detail": how, "ms": t.ms()}
            if op == "set_text":
                return self._set_text(el, str(a.get("text", "")), t)
            if op == "type":
                inputs.type_text(str(a.get("text", "")))
                return {"ok": True, "detail": f"typed {len(str(a.get('text', '')))} chars", "ms": t.ms()}
            if op == "key":
                inputs.hotkey(*a.get("keys", []))
                return {"ok": True, "detail": "+".join(map(str, a.get("keys", []))), "ms": t.ms()}
            if op == "scroll":
                n = int(a.get("amount", 3)) * (1 if str(a.get("direction", "down")).lower() == "up" else -1)
                l, tp, r, b = self.snap.rect
                inputs.scroll(n, (l + r) // 2, (tp + b) // 2)
                return {"ok": True, "detail": f"scroll {n}", "ms": t.ms()}
            if op == "wait":
                return self._wait(min(int(a.get("ms", 200)), 10000), t)
            if op == "hover":
                return self._hover(a, t)
            if op == "open_app":
                h, info = apps.launch(str(a.get("name", "")))
                if not h:
                    return {"ok": False, "detail": str(info), "ms": t.ms()}
                self._set_window(h)
                self._fresh = True
                inputs.set_foreground(h)
                return {"ok": True, "detail": f"launched {info}", "ms": t.ms()}
            if op == "ground_click":
                return self._ground_click(a, t)
            if op == "drag":
                return self._drag(a, t)
            if op == "click_xy":
                return self._click_xy(a, t)
            if op == "ask_user":
                ans = self.confirm.ask(str(a.get("question", "")))
                if ans is None:
                    return {"ok": False, "detail": "needs the user: " + str(a.get("question", "")), "ms": t.ms(), "needs_user": True}
                return {"ok": True, "detail": f"user answered: {ans}", "ms": t.ms()}
        except safety.SafetyBlock:
            raise
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:100]}", "ms": t.ms()}
        return {"ok": False, "detail": f"unknown op {op!r}", "ms": t.ms()}

    def _set_text(self, el, text, t):
        """Fill a field so that the APP notices: clear it through UI Automation, focus it, then type real keystrokes
        (classic apps enable buttons / run searches on key events, which a direct value-set bypasses). Verified by
        reading the value back; falls back to a direct value-set if typing did not land."""
        cleared, _ = uia.set_value(el, "")
        self._fg_ok()
        uia.focus(el)
        t0 = time.perf_counter()
        while not uia.has_focus(el) and time.perf_counter() - t0 < 0.3:
            time.sleep(0.01)
        if not uia.has_focus(el):
            ok, how = uia.set_value(el, text)
            return {"ok": ok, "detail": f"value set directly (could not focus the field): {how}", "ms": t.ms()}
        if not cleared:
            inputs.hotkey("ctrl", "a")
        inputs.type_text(text)
        got = None
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 0.4:  # wait until the app has processed the keystrokes
            got = uia.get_value(el)
            if got is None or got == text:
                break
            time.sleep(0.01)
        if got is not None and got != text:
            ok, how = uia.set_value(el, text)
            return {"ok": ok, "detail": f"typing gave {got[:40]!r}; value set directly instead", "ms": t.ms()}
        return {"ok": True, "detail": "typed into the field", "ms": t.ms()}

    def _preground(self, actions):
        """Several consecutive ground_clicks in one batch: find all targets on ONE screenshot (one upload) first."""
        run = []
        for a in actions:
            if a.get("op") != "ground_click":
                if run:
                    break
                continue
            run.append(a)
        if len(run) < 2 or not self.grounder or self.dry_run or not self.snap:
            return
        self.grounder.ensure()
        self._stabilize()  # never ground on a half-drawn window
        region = self.snap.rect
        t = Timer()
        self.grounder.load(screen.grab(region))
        for a in run:
            try:
                p = self.grounder.find(str(a.get("target", "")))["point"]
                a["_pt"] = (region[0] + p[0], region[1] + p[1])
            except Exception:  # noqa: BLE001  (fall back to grounding on demand)
                pass
        pts = [(str(a.get("target", "")).lower(), a.get("_pt")) for a in run if a.get("_pt")]
        collapsed = any(ta != tb and abs(pa[0] - pb[0]) <= 6 and abs(pa[1] - pb[1]) <= 6
                        for i, (ta, pa) in enumerate(pts) for tb, pb in pts[i + 1:])
        if collapsed:  # different targets on the same spot = the grounder did not really see them
            for a in run:
                a.pop("_pt", None)
        self.t["ground"] += t.ms()
        self._log("preground", targets=len(run), ms=round(t.ms()), reliable=not collapsed)

    def _stabilize(self, max_ms=600):
        """Wait until the window stops moving (menus and panes animate in); grounding a half-drawn screen misclicks."""
        t = Timer()
        prev, stable = screen.signature(screen.grab(self.snap.rect)), 0
        while t.ms() < max_ms:
            time.sleep(0.03)
            cur = screen.signature(screen.grab(self.snap.rect))
            stable = stable + 1 if screen.diff(cur, prev) < 0.0015 else 0
            if stable >= 2:
                break
            prev = cur
        self.t["settle"] += t.ms()

    @staticmethod
    def _norm_target(target):
        return re.sub(r"\W+", " ", str(target or "").lower()).strip()

    def _wait(self, ms, t):
        """Wait up to `ms`, but stop early once the window has clearly changed (a loading screen gave way to the real
        UI, a dialog appeared) and then held still for 0.6 s. Small changes such as a progress bar do not end it."""
        if not self.snap or self.dry_run or ms < 800:
            time.sleep(ms / 1000)
            return {"ok": True, "detail": f"waited {ms} ms", "ms": t.ms()}
        start, wins0 = screen.signature(screen.grab(self.snap.rect)), self._app_windows()
        prev, big, still = start, False, None
        while t.ms() < ms:
            time.sleep(0.1)
            cur = screen.signature(screen.grab(self.snap.rect))
            big = big or screen.changed_frac(cur, start) > 0.12 or self._app_windows() != wins0
            if big and screen.diff(cur, prev) < 0.0015:
                still = still or time.perf_counter()
                if time.perf_counter() - still >= 0.6:
                    return {"ok": True, "detail": f"waited {t.ms():.0f} ms (the screen changed and settled)", "ms": t.ms()}
            else:
                still = None
            prev = cur
        return {"ok": True, "detail": f"waited {t.ms():.0f} ms", "ms": t.ms()}

    def _locate(self, a, img, key="target", attempt=0):
        """Ask the click model where a described target is on `img` (pixels of img). Looks closer (zoomed crop around the
        planner's rough 'near' hint or the first guess) when asked to, when re-aiming, or when the same target was
        already clicked without effect."""
        target = str(a.get(key, ""))
        zoom = bool(a.get("zoom")) or attempt > 0 or self._norm_target(target) in self._missed
        near = None
        if isinstance(a.get("near"), (list, tuple)) and len(a["near"]) == 2 and getattr(self, "_shot_geom", None):
            s = self._shot_geom[2]
            near = (float(a["near"][0]) * s, float(a["near"][1]) * s)
        if zoom and hasattr(self.grounder, "ground_zoom"):
            res = self.grounder.ground_zoom(img, target, near=near)
        else:
            res = self.grounder.ground(img, target)
        self.t["ground"] += res["ms"]
        return res

    def _hover(self, a, t):
        """Rest the pointer on a described spot so that hover-only controls appear (no click)."""
        if not self.grounder:
            return {"ok": False, "detail": "no vision grounder configured", "ms": t.ms()}
        self.grounder.ensure()
        self._stabilize()
        region = self.snap.rect
        img = screen.grab(region)
        if self._shot and screen.diff(screen.signature(img), self._shot[1]) < 0.002:
            img = self._shot[0]
        res = self._locate(a, img)
        x, y = region[0] + res["point"][0], region[1] + res["point"][1]
        if not self._inside(x, y):
            return {"ok": False, "detail": f"refused hover: ({x},{y}) is outside the app window", "ms": t.ms()}
        inputs.hover(x, y)
        time.sleep(0.35)  # hover effects fade in
        return {"ok": True, "detail": f"pointer resting on ({x},{y}){' (zoomed)' if res.get('zoom') else ''}", "ms": t.ms()}

    def _ground_click(self, a, t):
        if not self.grounder:
            return {"ok": False, "detail": "no vision grounder configured", "ms": t.ms()}
        region = self.snap.rect
        res, v, under, x, y = {"ms": 0.0}, safety.Verdict("low"), None, 0, 0
        for attempt in range(2):  # second attempt = re-aim after a risky pointer target
            if a.get("_pt") and attempt == 0 and not a.get("zoom") and self._norm_target(a.get("target")) not in self._missed:
                x, y = a["_pt"]
            else:
                self.grounder.ensure()
                self._stabilize()
                img = screen.grab(region)
                if attempt == 0 and self._shot and screen.diff(screen.signature(img), self._shot[1]) < 0.002:
                    img = self._shot[0]  # unchanged since the screenshot that was already uploaded
                res = self._locate(a, img, attempt=attempt)
                x, y = region[0] + res["point"][0], region[1] + res["point"][1]
            if not self._inside(x, y):
                return {"ok": False, "detail": f"refused vision click: ({x},{y}) is outside the app window", "ms": t.ms()}
            under = uia.element_at(x, y)
            # sanity checks on what is REALLY under the predicted point: is it risky? is it plausibly what was asked for?
            v = (safety.classify({"op": "ground_click", "target": f"{under['name']} {under['aid']}"}, None, self.goal,
                                 self.snap.proc, self.allow_apps) if under else safety.Verdict("low"))
            if v.level == "low" and not _target_matches(str(a.get("target", "")), under):
                v = safety.Verdict("block", f"the point is on {under.get('name')!r}, not on {a.get('target')!r}")
            if v.level == "low":
                break
            self._log("reaim", why=v.reason, under=under)
        if v.level == "block":
            return {"ok": False, "detail": f"refused vision click: {v.reason}", "ms": t.ms()}
        if v.level != "low":
            try:
                safety.decide(v, self.confirm, self.goal)
            except (Declined, SafetyBlock) as e:
                return {"ok": False, "detail": f"refused: the predicted click point is on {under} ({e})", "ms": t.ms()}
        inputs.click(x, y, double=bool(a.get("double")))
        a["_under"] = under
        a["_xy"] = (x, y)
        zoomed = " (zoomed)" if res.get("zoom") else ""
        return {"ok": True, "detail": f"vision click ({x},{y}){zoomed} in {res['ms']:.0f} ms; under pointer: {under}", "ms": t.ms()}

    def _inside(self, x, y):
        """Pointer input must stay inside the window being worked on (a bad coordinate must not click the desktop)."""
        l, tp, r, b = self.snap.rect if self.snap else (0, 0, 0, 0)
        return l <= x < r and tp <= y < b

    def _click_xy(self, a, t):
        """Click a point the vision planner picked on the attached screenshot (second aiming channel when the grounder
        keeps missing). Same pointer safety checks as ground_click."""
        if not getattr(self, "_shot_geom", None):
            return {"ok": False, "detail": "click_xy needs a screenshot first", "ms": t.ms()}
        ox, oy, scale = self._shot_geom
        x, y = int(ox + float(a.get("x", 0)) * scale), int(oy + float(a.get("y", 0)) * scale)
        if not self._inside(x, y):
            l, tp, r, b = self.snap.rect
            return {"ok": False, "detail": f"refused click_xy: ({a.get('x')},{a.get('y')}) is outside the screenshot "
                                           f"({round((r - l) / scale)}x{round((b - tp) / scale)} px)", "ms": t.ms()}
        under = uia.element_at(x, y)
        v = (safety.classify({"op": "ground_click", "target": f"{under['name']} {under['aid']}"}, None, self.goal,
                             self.snap.proc, self.allow_apps) if under else safety.Verdict("low"))
        if v.level == "low" and a.get("target") and not _target_matches(str(a["target"]), under):
            return {"ok": False, "detail": f"refused click_xy: the point is on {under.get('name')!r}", "ms": t.ms()}
        if v.level != "low":
            try:
                safety.decide(v, self.confirm, self.goal)
            except (Declined, SafetyBlock) as e:
                return {"ok": False, "detail": f"refused: the point is on {under} ({e})", "ms": t.ms()}
        inputs.click(x, y, double=bool(a.get("double")))
        a["_xy"] = (x, y)
        return {"ok": True, "detail": f"clicked screen ({x},{y}); under pointer: {under}", "ms": t.ms()}

    def _drag(self, a, t):
        """Drag by description (vision): find both ends on one settled screenshot, check the start point, then drag."""
        if not self.grounder:
            return {"ok": False, "detail": "no vision grounder configured", "ms": t.ms()}
        self.grounder.ensure()
        self._stabilize()
        region = self.snap.rect
        tg = Timer()
        self.grounder.load(screen.grab(region))
        p1 = self.grounder.find(str(a.get("from", "")))["point"]
        p2 = self.grounder.find(str(a.get("to", "")))["point"]
        self.t["ground"] += tg.ms()
        x1, y1 = region[0] + p1[0], region[1] + p1[1]
        x2, y2 = region[0] + p2[0], region[1] + p2[1]
        if not (self._inside(x1, y1) and self._inside(x2, y2)):
            return {"ok": False, "detail": "refused drag: an end point is outside the app window", "ms": t.ms()}
        under = uia.element_at(x1, y1)
        if under and not _target_matches(str(a.get("from", "")), under):
            return {"ok": False, "detail": f"refused drag: the start point is on {under.get('name')!r}", "ms": t.ms()}
        inputs.drag(x1, y1, x2, y2)
        return {"ok": True, "detail": f"dragged ({x1},{y1}) -> ({x2},{y2})", "ms": t.ms()}

    def _record(self, a):
        st = {"op": a["op"]}
        el = self._last_el if a.get("op") in ID_OPS else None
        if el:
            st["loc"] = uia.locator_of(el)
        for k in ("text", "keys", "target", "direction", "amount", "name", "ms", "double", "from", "to", "near", "zoom"):
            if k in a:
                st[k] = a[k]
        nm = f"{el.name} {el.aid}" if el else ""
        if re.search(r"\b(clear|backspace|delete|undo|erase|reset)\b", nm, re.I) or (
                a.get("op") == "key" and [str(k).lower() for k in a.get("keys", [])] in (["backspace"], ["delete"], ["ctrl", "z"])):
            self.messy.append("corrective action: " + (nm.strip() or str(a.get("keys"))))
        if a.get("op") == "ground_click":
            u = a.get("_under") or {}
            if u.get("name") or u.get("aid"):  # vision found it, UI Automation can name it: replays can use the fast lane
                st["loc"] = {"aid": u.get("aid", ""), "role": u.get("role", ""), "name": u.get("name", ""), "cls": ""}
        self.rec.append(st)

    # ------------------------------------------------------------------ reflex lane: skill replay
    def _resolve(self, loc, patient):
        """Find a step's control. 'patient' = the previous step changed the page: never reuse a handle from before it,
        and poll until the control exists (this IS the wait; no fixed delay)."""
        if patient:
            self._observe()
        el = uia.find_best(self.snap, loc) if self.snap else None
        if el:
            return el
        t = Timer()
        while t.ms() < (1800 if patient else 250):
            time.sleep(0.03)
            self._observe()
            el = uia.find_best(self.snap, loc)
            if el:
                return el
        raise ReplayFail(f"element not found: {loc.get('name') or loc.get('aid')!r}")

    def _try_resolve(self, loc, patient):
        if patient:
            self._observe()
        el = uia.find_best(self.snap, loc) if self.snap else None
        if el or not self.snap:
            return el
        t = Timer()
        while t.ms() < (800 if patient else 0):
            time.sleep(0.03)
            self._observe()
            el = uia.find_best(self.snap, loc)
            if el:
                return el
        return None

    def _replay(self, skill, params):
        steps = skill["steps"]
        self._log("replay", skill=skill["name"], steps=len(steps), params=params)
        if self.hwnd is None:
            app = skill.get("app") or {}
            h = apps.find_window(title_substr=app.get("title"), exclude=BLOCKED_PROCS) if app.get("title") else None
            if not h and app.get("launch") and not self.dry_run:
                h, _ = apps.launch(app["launch"])
                self._fresh = True
            if h:
                self._set_window(h)
                if not self.dry_run:
                    inputs.set_foreground(h)
        self.plan_snap = None  # replay resolves every step against the live snapshot
        if self.snap is None:
            self._observe()
        patient = False
        for i, st0 in enumerate(steps):
            st = fill(st0, params)
            op, a = st["op"], {k: v for k, v in st.items() if k not in ("loc", "nav")}
            if op == "open_app":
                pass
            elif op == "ground_click" and "loc" in st:
                # learned by vision, replayed by UI Automation when the element can be found; vision is only the fallback
                el = self._try_resolve(st["loc"], patient)
                if el is not None:
                    a = {"op": "invoke" if el.ops else "click", "id": el.id}
                    self._log("replay", note=f"vision step now runs through UI Automation: {el.name!r}")
            elif "loc" in st:
                if self.snap is None:
                    raise ReplayFail("no window to act on")
                el = self._resolve(st["loc"], patient)
                a["id"] = el.id
            nav = bool(st0.get("nav"))
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            next_has_target = bool(nxt and "loc" in nxt)
            last = nxt is None
            need_sig = (op in ("type", "key") or (nav and not next_has_target)) and self.snap and not self.dry_run
            sig0 = self._sig() if need_sig else None
            fin_el = fin_pre = None
            if last and not self.dry_run and self.snap and (skill.get("final") or {}).get("read"):
                fin_el = uia.find_best(self.snap, skill["final"]["read"])  # the result element: watch only its text
                fin_pre = uia.live_name(fin_el) if fin_el else None
            r = self._exec(a)
            self.t["act"] += r["ms"]
            if not r["ok"]:
                raise ReplayFail(f"step {i + 1} ({op}): {r['detail']}")
            self.steps += 1
            if op == "open_app":
                self._observe()
            elif nav and not self.dry_run:
                if not next_has_target:
                    # the next step types or presses keys, so the new view must be ready first
                    self._settle(sig0, max_ms=600)
                    self._observe_stable(max_ms=600)
                # else: the next step's patient _resolve waits exactly until its control exists (UIA presses do not
                # depend on animations finishing), which is the shortest correct wait
            elif sig0 is not None:
                # typing/keys need a moment to show up; wait only until the UI reacts (<=150 ms)
                self._settle(sig0, max_ms=150)
            if fin_el is not None and fin_pre is not None:
                t = Timer()  # before reading the answer, wait (polling ~1 ms reads) until the result text updates
                while t.ms() < 150 and uia.live_name(fin_el) == fin_pre:
                    time.sleep(0.003)
                self.t["settle"] += t.ms()
            patient = nav
        ans = None
        fin = (skill.get("final") or {}).get("read")
        if fin and self.snap and not self.dry_run:
            el = uia.find_best(self.snap, fin)
            name = uia.live_name(el) if el else None
            if name is None:
                self._observe()
                el = uia.find_best(self.snap, fin)
                name = uia.live_name(el) if el else None
            ans = name
        return ans

    # ------------------------------------------------------------------ planner lane
    def _answer_locator(self, answer, evidence=None):
        """Which on-screen element shows the result? Prefer the exact text the planner says it read; otherwise the text
        element that changed during the run and best overlaps the answer (stop-words and punctuation ignored)."""
        if not self.snap:
            return None
        texts = [e for e in self.snap.els if e.role in TEXT_ROLES and e.name]
        ev = str(evidence or "").strip().lower()
        if ev:
            for e in texts:
                if e.name.strip().lower() == ev:
                    return uia.locator_of(e)
            for e in texts:
                n = e.name.strip().lower()
                if len(n) > 2 and (ev in n or n in ev):
                    return uia.locator_of(e)
        if not answer:
            return None
        stop = {"the", "is", "of", "a", "an", "to", "and", "it", "result", "answer", "equals", "square", "root"}
        toks = [w.strip(".,:;!?()[]'\"").lower() for w in str(answer).split()]
        toks = [w for w in toks if w and w not in stop]
        base = getattr(self, "_texts0", {})
        changed = [e for i, e in enumerate(x for x in self.snap.els if x.role in TEXT_ROLES)
                   if base.get(e.aid or f"t{i}") != e.name]
        best, score = None, 0.0
        for e in (changed or texts):
            s = sum(1 for w in toks if w in e.name.lower()) + (0.5 if re.search(r"result|display|output|answer|value", e.aid or "", re.I) else 0)
            if s > score:
                best, score = e, s
        return uia.locator_of(best) if best and score >= 1 else None

    def _grounded(self, plan, obs):
        """Is the planner's answer visibly supported by the current window (evidence text, or the answer's key tokens)?"""
        ev = str(plan.evidence or "").strip().lower()
        texts = [f"{e.name} {e.value}".lower() for e in self.snap.els]
        if ev and (ev in obs.lower() or any(ev in t for t in texts)):
            return True
        toks = [w.strip(".,:;!?()[]'\"").lower() for w in str(plan.answer).split()]
        toks = [w for w in toks if len(w) >= 2 and any(ch.isdigit() for ch in w)]  # numbers/codes must be on screen
        return bool(toks) and all(any(w in t for t in texts) for w in toks)

    def _plan_loop(self, goal, use_deep):
        history, stuck, fails, deep_used, note = [], 0, 0, False, None
        grounded_retry = False
        clicked = []  # screen points of vision clicks this run
        obs = self._observe_stable()
        self.plan_snap = self.snap
        self.pre_struct = struct_keys(self._struct(self.snap)) if self.snap else None
        self._texts0 = self._texts(self.snap) if self.snap else {}
        plan_text, deep_bg = None, None  # plan_text: the deep thinker's plan, shown to the quick planner on EVERY call
        if use_deep and hasattr(self.planner, "deep_plan"):
            # the deep thinker (10-26 s) works in the background while the quick planner starts on the obvious first steps
            deep_used, holder, ctx = True, {}, obs + self._app_context()

            def think():
                tt = Timer()
                try:
                    holder["d"] = self.planner.deep_plan(goal, ctx)
                except Exception as e:  # noqa: BLE001
                    holder["error"] = f"{type(e).__name__}: {str(e)[:120]}"
                holder["ms"] = tt.ms()
            deep_bg = (threading.Thread(target=think, daemon=True), holder)
            deep_bg[0].start()
            deep_bg[0].join(0.3)  # a scripted/instant planner answers at once; a real one keeps thinking in the background
        while True:
            self.kill.check()
            if self.steps >= self.limits["max_steps"] or self.llm_calls >= self.limits["max_llm_calls"]:
                raise TimeoutError(f"budget exhausted (steps={self.steps}, llm_calls={self.llm_calls})")
            if time.perf_counter() - self.t0 > self.limits["max_seconds"]:
                raise TimeoutError("time budget exhausted")
            if deep_bg and not deep_bg[0].is_alive():
                h, deep_bg = deep_bg[1], None
                self.llm_calls += 1
                if "d" in h:
                    plan_text = self._plan_text(h["d"])
                    self._log("deep_plan", ms=round(h["ms"]), background=True, approach=str(h["d"].get("approach", ""))[:200],
                              subgoals=len(h["d"].get("subgoals", [])))
                else:
                    self._log("deep_plan_failed", why=h.get("error"))
            image = None
            if self.snap is None or self.snap.richness < 6 or stuck >= 1:
                image = self._screenshot_for_planner() if self.snap else None
            t = Timer()
            plan = self.planner.next(goal, obs + self._app_context(), history, image_jpeg=image, subgoal=plan_text, note=note)
            self.llm_calls += 1
            self.t["plan"] += t.ms()
            note = None
            self._log("plan", model=plan.model, ms=round(t.ms()), conf=plan.confidence, risk=plan.risk, thought=plan.thought,
                      n=len(plan.actions), done=plan.done, tokens=plan.tokens, actions=plan.actions)
            if plan.done:
                if (plan.success is not False and plan.answer and not grounded_retry and self.snap
                        and self.snap.richness >= 6 and not self._grounded(plan, obs)):
                    # the answer must come from the screen, not from the model's memory: ask once to point at it
                    grounded_retry = True
                    note = ("Your answer must be read from the screen. Quote, as 'evidence', the exact text of an element "
                            "in the OBSERVATION that shows it; if the result is not visible yet, act to make it visible.")
                    self._log("unverified_answer", answer=str(plan.answer)[:80], evidence=plan.evidence)
                    continue
                return plan
            if (plan.confidence is not None and plan.confidence < 0.6 and not deep_used and hasattr(self.planner, "deep_plan") and not self.dry_run
                    and self.llm_calls <= 2):
                # the quick planner is unsure about a new situation: think harder once, then plan again with that guidance
                t = Timer()
                d = self.planner.deep_plan(goal, obs + self._app_context() + "\n\nHISTORY:\n" + "\n".join(history[-6:])
                                           + f"\n\nQuick planner said (low confidence): {plan.thought}")
                self.llm_calls += 1
                self.t["plan"] += t.ms()
                deep_used = True  # (not 'messy': the unsure plan was never executed, so the recording stays clean)
                plan_text = self._plan_text(d)
                self._log("deep_plan", ms=round(t.ms()), reason="low confidence", approach=str(d.get("approach", ""))[:160])
                continue
            if self.dry_run:
                for a in plan.actions:
                    self._log("would_do", op=a.get("op"), detail=json.dumps(a, ensure_ascii=False)[:120])
                plan.done = True
                return plan
            if not plan.actions:
                stuck += 1
                history.append("(you returned no actions and did not finish; act or set done)")
                continue
            sig0 = self._sig() if self.snap else None
            texts0, struct0 = (self._texts(self.snap), self._struct(self.snap)) if self.snap else ({}, None)
            state0 = self._state(self.snap) if self.snap else None
            lines, batch_ok = [], True
            self._preground(plan.actions)
            for a in plan.actions:
                self._last_el = None
                r = self._exec(a)
                el = self._last_el
                label = f"{a.get('op')} {a.get('id', '')}".strip() + (f" '{el.name[:30]}'" if el else "") + (f" {str(a.get('text') or a.get('target') or a.get('keys') or '')[:40]}" if not el else "")
                self.t["act"] += r["ms"]
                self._log("act", op=a.get("op"), ok=r["ok"], ms=round(r["ms"], 1), detail=r["detail"],
                          id=a.get("id"), name=el.name if el else a.get("name"), aid=el.aid if el else None)
                if not r["ok"]:
                    self.messy.append("failed action")
                lines.append(f"{len(history) + len(lines) + 1}. {label} -> {'ok' if r['ok'] else 'FAILED'}: {r['detail']}")
                xy = a.get("_xy")
                if xy:
                    if any(abs(xy[0] - p[0]) <= 12 and abs(xy[1] - p[1]) <= 12 for p in clicked):
                        lines.append("   NOTE: this landed on the same spot as an earlier click. If that did not work, do not "
                                     "repeat it: add \"zoom\": true and a \"near\" hint, describe the target differently, or "
                                     "use a shortcut.")
                        if a.get("target"):
                            self._missed.add(self._norm_target(a["target"]))
                    clicked.append(xy)
                if not r["ok"]:
                    batch_ok = False
                    if r.get("needs_user"):
                        return plan.__class__(done=True, success=False, answer=r["detail"])
                    break
                self._record(a)
                self.steps += 1
            # custom-drawn apps animate menus and open dialogs slowly: give them longer to react (returns early on change)
            thin = self.snap is not None and self.snap.richness < 6
            slow = any(a.get("op") in ("key", "click", "invoke", "ground_click", "click_xy", "drag", "open_app") for a in plan.actions)
            changed = self._settle(sig0, max_ms=900 if (thin and slow) else 250) if sig0 else True
            exp_ok, exp_msg = self._check_expect(plan.actions[-1].get("expect")) if batch_ok else (True, "")
            # ALWAYS re-observe (and wait out UI rebuilds), so the ids in the next observation are exactly the handles we act on
            obs = self._observe_stable(ref_struct=struct0)
            self.plan_snap = self.snap
            if self.snap is not None and state0 is not None and self._state(self.snap) != state0:
                changed = True  # the UI tree says something changed (a value, toggle, layout...) even if pixels barely did
            if not changed and sig0 is not None and self.snap is not None:
                cur = self._sig()  # a fade-in that finished after the settle window still counts as a reaction
                changed = screen.changed(cur[2], sig0[2]) or cur[3] != sig0[3]
            if self.snap and self.rec and batch_ok and self._nav_changed(struct0, self._struct(self.snap)):
                self.rec[-1]["nav"] = True
            if self.snap:
                t1 = self._texts(self.snap)
                ch = [f"'{texts0[k]}' -> '{t1[k]}'" for k in t1 if k in texts0 and texts0[k] != t1[k]][:3]
                if ch:
                    lines.append("   TEXT CHANGES: " + "; ".join(ch))
            if batch_ok and not changed:
                lines.append("   (no visible change after these actions)")
                self._missed.update(self._norm_target(a.get("target")) for a in plan.actions
                                    if a.get("op") in ("ground_click", "hover") and a.get("target"))
            if not exp_ok:
                lines.append("   " + exp_msg)
            history.extend(lines)
            quiet_ops = all(a.get("op") in ("focus", "wait") for a in plan.actions)  # these legitimately change nothing
            stuck = stuck + 1 if (not changed and batch_ok and not quiet_ops) or not exp_ok else 0
            if stuck:
                self.messy.append("no visible progress")
            fails = fails + 1 if not batch_ok else 0
            if fails >= 3:
                raise TimeoutError("three failed batches in a row")
            if stuck >= self.limits["stuck_after"]:
                if deep_used or not hasattr(self.planner, "deep_plan"):
                    if stuck >= self.limits["stuck_after"] + 2:
                        raise TimeoutError("stuck: no visible progress")
                    note = ("No visible progress in the last batches. Change approach instead of repeating: use a shortcut "
                            "from APP SHORTCUTS, describe the target differently, use click_xy on the screenshot, or wait "
                            "if a slow operation (loading, importing, exporting) is running.")
                    continue
                t = Timer()
                d = self.planner.deep_plan(goal, obs + self._app_context() + "\n\nHISTORY:\n" + "\n".join(history[-10:])
                                           + "\n\nThe quick planner is stuck; re-plan.")
                self.llm_calls += 1
                self.t["plan"] += t.ms()
                deep_used, stuck = True, 0
                self.messy.append("deep re-plan after being stuck")
                plan_text = self._plan_text(d)
                note = "You were stuck; the PLAN above was just re-made for the current screen. Follow it."
                self._log("deep_plan", ms=round(t.ms()), reason="stuck", approach=str(d.get("approach", ""))[:160])

    @staticmethod
    def _plan_text(d):
        return ("PLAN from the deep thinker (follow it; some steps may already be done, so check HISTORY and the screen): "
                + json.dumps({k: d.get(k) for k in ("approach", "subgoals")}, ensure_ascii=False)[:1600])

    # ------------------------------------------------------------------ public API
    def run(self, goal, app=None, params=None, use_skill=True, learn=True, deep=False):
        self._begin(goal)
        total = Timer()
        lane, skill_name, answer, ok, error = "planner", None, None, False, None
        try:
            self.kill.start()
            self._prepare(app)
            replayed = False
            if use_skill:
                if self.hwnd:
                    self._observe()  # what does the window look like right now? (only variants recorded from a similar state may replay)
                skill, p = self.store.match(goal, struct_keys(self._struct(self.snap)) if self.snap else None)
                if skill:
                    t = Timer()
                    skill_name, lane = skill["name"], "skill"
                    try:
                        answer = self._replay(skill, {**(p or {}), **(params or {})})
                        ok, replayed = True, True
                        if not self.dry_run:
                            self.store.record_run(skill, True, t.ms())
                        self._log("replay_ok", ms=round(t.ms()), answer=answer)
                    except ReplayFail as e:
                        self._log("replay_failed", why=str(e))
                        if not self.dry_run:
                            self.store.record_run(skill, False, t.ms())
                        lane = "planner(after failed skill)"
                        learn = False  # the replay already changed the window, so a run started from here is not a clean recording
            if not replayed:
                if self.planner is None:
                    raise RuntimeError("no matching skill and no planner configured")
                plan = self._plan_loop(goal, deep)
                ok = bool(plan.done and plan.success is not False)
                answer = plan.answer
                self._log("done", ok=ok, answer=answer)
                if ok and learn and not self.dry_run and self.rec and self.messy:
                    self._log("skill_skipped", why="run was not clean: " + "; ".join(dict.fromkeys(self.messy)))
                if ok and learn and not self.dry_run and self.rec and self.snap and not self.messy:
                    app_sig = {"proc": self.snap.proc, "title": self.snap.title}
                    first = self.rec[0]
                    if first["op"] == "open_app":
                        app_sig["launch"] = first.get("name")
                    skill = compile_skill(goal, self.rec, plan.skill, self._answer_locator(answer, plan.evidence), app_sig, answer, self.pre_struct)
                    self.store.save(skill)
                    skill_name = skill["name"]
                    self._log("skill_saved", name=skill["name"], steps=len(skill["steps"]), params=skill["params"])
        except (Aborted, SafetyBlock, Declined, TimeoutError, RuntimeError) as e:
            error = f"{type(e).__name__}: {e}"
            self._log("stopped", why=error)
        except Exception as e:  # noqa: BLE001  (planner/network errors etc.)
            error = f"{type(e).__name__}: {str(e)[:200]}"
            self._log("error", why=error)
        finally:
            res = RunResult(ok=ok, answer=answer, lane=lane, steps=self.steps, ms=round(total.ms()), llm_calls=self.llm_calls,
                            skill=skill_name, timings={k: round(v) for k, v in self.t.items()}, run_dir=str(self.run_dir), error=error)
            (self.run_dir / "summary.json").write_text(json.dumps(res.__dict__, indent=1, default=str), encoding="utf-8")
            self.trace_f.close()
        return res
