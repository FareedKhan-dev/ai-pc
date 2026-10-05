"""Safety layer. The model's own risk rating is only one signal: this module classifies every action itself,
blocks dangerous targets, asks the user before risky steps, and provides a global kill switch.

Screen text is untrusted data (prompt-injection defence): nothing a window says can lower these checks.
"""

import ctypes
import re
import sys
import threading
import time
from dataclasses import dataclass

from ai_pc.core.config import BLOCKED_PROCS

HIGH = re.compile(
    r"\b(delete|remove|erase|empty (the )?(recycle bin|trash|bin|cache|folder|basket)|"
    r"format (the )?(disk|drive|partition|[a-z]:)|uninstall|"
    r"reset (this )?(pc|computer|device|settings|password|all|everything)|wipe|purge|purchase|buy|pay|checkout|place order|"
    r"subscribe|send|submit|publish|post|sign out|log ?out|shut ?down|restart|install|overwrite|replace all|"
    r"discard|don'?t save|permanently|factory|clear (all|data|history|browsing)|disable (security|firewall|defender)|"
    r"transfer|withdraw|unsubscribe|deactivate|terminate|"
    r"sign in|log ?in|sign up|register|join pro|upgrade|go pro|free trial|try pro)\b",
    re.I,
)  # accounts & paywalls: the user decides
MEDIUM = re.compile(r"\b(close|exit|quit|cancel|save as|share|upload|export|accept|agree|allow|grant|enable)\b", re.I)
BAD_COMBOS = {
    ("win", "r"),
    ("win", "x"),
    ("ctrl", "alt", "delete"),
    ("ctrl", "shift", "esc"),
    ("ctrl", "alt", "q"),
}  # Ctrl+Alt+Q is the kill switch: an app shortcut on the same keys would abort the run
MEDIUM_COMBOS = {("alt", "f4"), ("ctrl", "w"), ("ctrl", "shift", "w"), ("delete",), ("ctrl", "q")}


class Aborted(Exception):
    """Raised when the user pressed the kill switch (Ctrl+Alt+Q)."""


class SafetyBlock(Exception):
    pass


class Declined(Exception):
    pass


@dataclass
class Verdict:
    level: str  # low | medium | high | block
    reason: str = ""
    word: str = ""


def classify(action, el=None, goal="", proc="", allow_apps=()):
    op = action.get("op")
    if proc and proc in BLOCKED_PROCS and proc not in allow_apps:
        return Verdict("block", f"'{proc}' is on the blocked list (terminals, IDEs and password managers are never controlled)")
    if op in ("type", "set_text") and el is not None and el.password:
        return Verdict("block", "refusing to type into a password field")
    if op == "open_app":
        n = str(action.get("name", "")).lower()
        if any(b.replace(".exe", "") in n for b in BLOCKED_PROCS if b not in allow_apps):
            return Verdict("block", f"opening {action.get('name')!r} is not allowed")
    if op == "key":
        combo = tuple(str(k).lower() for k in action.get("keys", []))
        if combo in BAD_COMBOS:
            return Verdict("block", f"system hotkey {'+'.join(combo)} is not allowed")
        if combo in MEDIUM_COMBOS:
            return Verdict("medium", f"hotkey {'+'.join(combo)} may close or delete something", combo[-1])
    text = ""
    if el is not None:
        text = f"{el.name} {el.aid}"
    if op == "ground_click":
        text = str(action.get("target", ""))
    if op == "drag":
        text = f"{action.get('from', '')} {action.get('to', '')}"
    if op == "run_command":
        return Verdict("high", "running a shell command")
    m = HIGH.search(text)
    if m:
        return Verdict("high", f"'{text.strip()[:60]}' looks irreversible or costly", m.group(1).lower())
    m = MEDIUM.search(text)
    if m:
        return Verdict("medium", f"'{text.strip()[:60]}' may change state", m.group(1).lower())
    return Verdict("low")


class Confirmer:
    """mode: 'ask' (prompt on the console, deny on timeout), 'deny' (default for unattended runs), 'allow',
    'medium' (unattended: approve medium-risk steps such as closing a popup, refuse every high-risk one)."""

    def __init__(self, mode="deny", timeout=25):
        self.mode, self.timeout = mode, timeout

    def __call__(self, question, level=None):
        if self.mode == "allow":
            return True
        if self.mode == "medium":
            return level == "medium"
        if self.mode == "deny" or not sys.stdin or not sys.stdin.isatty():
            return False
        print(f"\n  CONFIRM: {question}  [y/N] (auto-deny in {self.timeout}s) ", end="", flush=True)
        ans = {}
        th = threading.Thread(target=lambda: ans.setdefault("v", sys.stdin.readline().strip().lower()), daemon=True)
        th.start()
        th.join(self.timeout)
        return ans.get("v", "") in ("y", "yes")

    def ask(self, question):
        if self.mode != "ask" or not sys.stdin or not sys.stdin.isatty():
            return None
        print(f"\n  AGENT ASKS: {question}\n  > ", end="", flush=True)
        return sys.stdin.readline().strip()


def decide(verdict, confirm, goal):
    """Raise SafetyBlock / Declined unless the action may run."""
    if verdict.level == "block":
        raise SafetyBlock(verdict.reason)
    if verdict.level == "low":
        return
    intended = bool(verdict.word) and verdict.word in goal.lower()
    if verdict.level == "medium" and intended:
        return
    if not confirm(f"{verdict.level.upper()} risk: {verdict.reason}. Goal: {goal[:80]!r}. Allow?", verdict.level):
        raise Declined(f"user did not approve: {verdict.reason}")


class KillSwitch:
    """Ctrl+Alt+Q aborts the run at the next step (polled every 20 ms in a background thread)."""

    def __init__(self):
        self.event = threading.Event()
        self._th = None

    def start(self):
        if self._th and self._th.is_alive():
            return
        self.event.clear()
        self._th = threading.Thread(target=self._poll, daemon=True)
        self._th.start()

    def _poll(self):
        gas = ctypes.windll.user32.GetAsyncKeyState
        while not self.event.is_set():
            if gas(0x11) & 0x8000 and gas(0x12) & 0x8000 and gas(0x51) & 0x8000:
                self.event.set()
                return
            time.sleep(0.02)

    def trip(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise Aborted("kill switch pressed")


def root_owner(hwnd):
    return ctypes.windll.user32.GetAncestor(hwnd, 3)  # GA_ROOTOWNER


def foreground_ok(expected_hwnd, expected_pid, fg_hwnd, fg_pid):
    """Input may only be sent while the foreground window is the target window, one it owns, or in the same process."""
    return fg_hwnd == expected_hwnd or fg_pid == expected_pid or root_owner(fg_hwnd) == root_owner(expected_hwnd)
