"""Fast UI Automation: one cross-process call returns the whole window's elements with cached properties.

Compared with walking the tree element by element (what most Python wrappers do), this avoids a COM round trip per
property. Actions use UIA patterns (Invoke/Toggle/Value/...) so they need no mouse and no sleeps.
"""
import ctypes
import ctypes.wintypes
import difflib
import time
from dataclasses import dataclass, field

import comtypes.client
import psutil
import win32gui
import win32process

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels everywhere
except Exception:
    pass

UIA = comtypes.client.GetModule("UIAutomationCore.dll")
IUIA = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=UIA.IUIAutomation)

# property / pattern ids (verified against the uiautomation package)
P_RECT, P_CTYPE, P_NAME, P_FOCUS, P_ENABLED, P_AID, P_CLASS, P_PASSWORD, P_OFFSCREEN = 30001, 30003, 30005, 30008, 30010, 30011, 30012, 30019, 30022
P_INVOKE, P_VALUE, P_TOGGLE, P_EXPAND, P_SELITEM, P_SCROLL = 30031, 30043, 30041, 30028, 30036, 30034
P_VALUEVAL = 30045  # ValuePattern.Value (the text in a field)
P_TOGGLESTATE = 30086  # TogglePattern.ToggleState (0 off, 1 on, 2 indeterminate)
PAT_INVOKE, PAT_VALUE, PAT_TOGGLE, PAT_EXPAND, PAT_SELITEM, PAT_SCROLLITEM = 10000, 10002, 10015, 10005, 10010, 10017

ROLES = {50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
         50006: "Image", 50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
         50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar", 50015: "Slider", 50016: "Spinner",
         50017: "StatusBar", 50018: "Tab", 50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50022: "ToolTip",
         50023: "Tree", 50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb", 50028: "DataGrid",
         50029: "DataItem", 50030: "Document", 50031: "SplitButton", 50032: "Window", 50033: "Pane", 50034: "Header",
         50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator"}
STRUCTURAL = {"Pane", "Group", "Custom", "Window", "Separator", "Image", "ScrollBar", "Thumb", "TitleBar", "ToolBar",
              "List", "Tree", "Table", "Menu", "MenuBar", "Tab", "Header", "StatusBar"}

_CR = IUIA.CreateCacheRequest()
for _p in (P_RECT, P_CTYPE, P_NAME, P_FOCUS, P_ENABLED, P_AID, P_CLASS, P_PASSWORD, P_INVOKE, P_VALUE, P_TOGGLE,
           P_EXPAND, P_SELITEM, P_SCROLL, P_VALUEVAL, P_TOGGLESTATE):
    _CR.AddProperty(_p)
_CR.TreeScope = 1  # cache only the element itself
_COND_VISIBLE = IUIA.CreateAndCondition(IUIA.ControlViewCondition, IUIA.CreatePropertyCondition(P_OFFSCREEN, False))
_COND_ALL = IUIA.ControlViewCondition


@dataclass
class El:
    id: str
    role: str
    name: str
    aid: str
    cls: str
    rect: tuple
    enabled: bool
    focus: bool
    password: bool
    ops: tuple
    el: object = field(repr=False, default=None)
    value: str = ""
    toggled: object = None

    @property
    def center(self):
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)


@dataclass
class Snapshot:
    hwnd: int
    title: str
    pid: int
    proc: str
    rect: tuple
    els: list
    ms: float
    found: int
    truncated: bool = False

    def by_id(self, eid):
        for e in self.els:
            if e.id == eid:
                return e
        return None

    @property
    def richness(self):
        return sum(1 for e in self.els if e.ops and (e.name or e.aid))


_proc_cache = {}


def proc_name(pid):
    if pid not in _proc_cache:
        try:
            _proc_cache[pid] = psutil.Process(pid).name().lower()
        except Exception:
            _proc_cache[pid] = "?"
    return _proc_cache[pid]


def window_info(hwnd):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return {"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "cls": win32gui.GetClassName(hwnd), "pid": pid,
            "proc": proc_name(pid), "rect": win32gui.GetWindowRect(hwnd)}


def snapshot(hwnd, max_elements=300, visible_only=True):
    t0 = time.perf_counter()
    info = window_info(hwnd)
    root = IUIA.ElementFromHandle(hwnd)
    arr = root.FindAllBuildCache(4, _COND_VISIBLE if visible_only else _COND_ALL, _CR)  # TreeScope_Descendants
    n = arr.Length
    els, k = [], 0
    for i in range(min(n, max_elements * 4)):
        if len(els) >= max_elements:
            break
        el = arr.GetElement(i)
        role = ROLES.get(el.CachedControlType, "Custom")
        name, aid = el.CachedName or "", el.CachedAutomationId or ""
        if not name and not aid and role != "Edit":
            continue
        ops = []
        if el.GetCachedPropertyValue(P_INVOKE):
            ops.append("invoke")
        if el.GetCachedPropertyValue(P_TOGGLE):
            ops.append("toggle")
        if el.GetCachedPropertyValue(P_VALUE):
            ops.append("value")
        if el.GetCachedPropertyValue(P_SELITEM):
            ops.append("select")
        if el.GetCachedPropertyValue(P_EXPAND):
            ops.append("expand")
        if el.GetCachedPropertyValue(P_SCROLL):
            ops.append("scroll")
        if role in STRUCTURAL and not ops:
            continue
        r = el.CachedBoundingRectangle
        if r.right - r.left <= 0 or r.bottom - r.top <= 0:
            continue
        k += 1
        pw = bool(el.CachedIsPassword)
        val = ""
        if "value" in ops and not pw and role in ("Edit", "ComboBox", "Document", "Spinner"):
            try:
                val = str(el.GetCachedPropertyValue(P_VALUEVAL) or "")
            except Exception:  # noqa: BLE001
                val = ""
        tog = None
        if "toggle" in ops:
            try:
                tog = int(el.GetCachedPropertyValue(P_TOGGLESTATE))
            except Exception:  # noqa: BLE001
                tog = None
        els.append(El(f"e{k}", role, name, aid, el.CachedClassName or "", (r.left, r.top, r.right, r.bottom),
                      bool(el.CachedIsEnabled), bool(el.CachedHasKeyboardFocus), pw, tuple(ops), el, val, tog))
    return Snapshot(hwnd, info["title"], info["pid"], info["proc"], info["rect"], els,
                    (time.perf_counter() - t0) * 1000, n, n > max_elements * 4)


# ---------------------------------------------------------------- acting through patterns
def _pattern(e, pid, iface):
    p = e.el.GetCurrentPattern(pid)
    return p.QueryInterface(iface) if p else None


def invoke(e):
    """Press / toggle / select / expand an element using the best available UIA pattern. Returns (ok, how)."""
    try:
        if "invoke" in e.ops:
            _pattern(e, PAT_INVOKE, UIA.IUIAutomationInvokePattern).Invoke()
            return True, "invoke"
        if "toggle" in e.ops:
            _pattern(e, PAT_TOGGLE, UIA.IUIAutomationTogglePattern).Toggle()
            return True, "toggle"
        if "select" in e.ops:
            _pattern(e, PAT_SELITEM, UIA.IUIAutomationSelectionItemPattern).Select()
            return True, "select"
        if "expand" in e.ops:
            p = _pattern(e, PAT_EXPAND, UIA.IUIAutomationExpandCollapsePattern)
            p.Expand() if p.CurrentExpandCollapseState == 0 else p.Collapse()
            return True, "expand"
    except Exception as ex:  # noqa: BLE001
        return False, f"{type(ex).__name__}: {str(ex)[:80]}"
    return False, "no pattern"


def set_value(e, text):
    try:
        if "value" in e.ops:
            p = _pattern(e, PAT_VALUE, UIA.IUIAutomationValuePattern)
            if p and not p.CurrentIsReadOnly:
                p.SetValue(text)
                return True, "value"
        return False, "no writable value pattern"
    except Exception as ex:  # noqa: BLE001
        return False, f"{type(ex).__name__}: {str(ex)[:80]}"


def get_value(e):
    """Current text of an edit-like control (ValuePattern), or None."""
    try:
        if "value" in e.ops:
            p = _pattern(e, PAT_VALUE, UIA.IUIAutomationValuePattern)
            return p.CurrentValue if p else None
    except Exception:  # noqa: BLE001
        return None
    return None


def is_enabled(e):
    try:
        return bool(e.el.CurrentIsEnabled)
    except Exception:  # noqa: BLE001
        return False


def has_focus(e):
    try:
        return bool(e.el.CurrentHasKeyboardFocus)
    except Exception:  # noqa: BLE001
        return False


def focus(e):
    try:
        e.el.SetFocus()
        return True, "focus"
    except Exception as ex:  # noqa: BLE001
        return False, f"{type(ex).__name__}: {str(ex)[:80]}"


def live_name(e):
    try:
        return e.el.CurrentName or ""
    except Exception:
        return None  # element went stale


def element_at(x, y):
    """The UIA element under a screen point (used as a safety check on vision clicks)."""
    try:
        el = IUIA.ElementFromPoint(ctypes.wintypes.POINT(x, y))
        return {"name": el.CurrentName or "", "aid": el.CurrentAutomationId or "", "role": ROLES.get(el.CurrentControlType, "Custom")}
    except Exception:
        return None


# ---------------------------------------------------------------- locating elements again (for skills)
def locator_of(e):
    return {"aid": e.aid, "role": e.role, "name": e.name, "cls": e.cls}


def find_best(snap, loc, min_score=5.0):
    """Best matching element for a saved locator: automation id beats name beats fuzzy name."""
    best, best_s = None, 0.0
    for e in snap.els:
        s = 0.0
        if loc.get("aid") and e.aid == loc["aid"]:
            s += 10
        if loc.get("role") and e.role == loc["role"]:
            s += 2
        nm = loc.get("name") or ""
        if nm and e.name == nm:
            s += 5
        elif nm and e.name:
            r = difflib.SequenceMatcher(None, nm.lower(), e.name.lower()).ratio()
            s += 4 * r if r > 0.8 else 0
        if s > best_s:
            best, best_s = e, s
    return best if best_s >= min_score else None
