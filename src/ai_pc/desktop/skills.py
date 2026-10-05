"""Skill store: a successful run becomes a replayable, parameterised step list (the 'reflex' layer).

Steps use semantic locators (automation id / role / name), not pixel positions, so they survive window moves and
re-layouts. Replay needs no language-model calls.
"""
import copy
import hashlib
import json
import re
import time

from ai_pc.core.config import SKILLS_DIR
from ai_pc.core.util import slug

TEXT_FIELDS = ("text", "target", "name", "question")


def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower().strip().rstrip(".!?"))


KIND_RE = {"num": r"-?\d+(?:[.,]\d+)?", "word": r"\S+", "text": r".+?"}


def _kind(v):
    """Shape of a learned parameter value: a number, a single word, or free text."""
    if re.fullmatch(KIND_RE["num"], v):
        return "num"
    return "word" if re.fullmatch(r"\S+", v) else "text"


def _intent_regex(intent, kinds=None):
    """Template -> regex. Each placeholder only matches the shape of the values it was learned from (numbers match
    numbers), so 'calculate {a} + {b}' cannot swallow 'calculate 12 + 30 and tell me the result'."""
    kinds = kinds or {}
    pat = re.escape(norm(intent))
    pat = re.sub(r"\\\{(\w+)\\\}", lambda m: f"(?P<{m.group(1)}>{KIND_RE[kinds.get(m.group(1), 'text')]})", pat)
    return re.compile("^" + pat + "$")


class SkillStore:
    def __init__(self, directory=SKILLS_DIR):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, name):
        return self.dir / f"{name}.json"

    def list(self):
        out = []
        for p in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - a damaged skill file is skipped, not fatal
                pass
        return out

    def get(self, name):
        p = self.path(name)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def save(self, skill):
        self.dir.mkdir(parents=True, exist_ok=True)  # the folder may have been cleaned while we were running
        self.path(skill["name"]).write_text(json.dumps(skill, indent=1, ensure_ascii=False), encoding="utf-8")

    def delete(self, name):
        p = self.path(name)
        if p.exists():
            p.unlink()
            return True
        return False

    def match(self, goal, struct=None, min_sim=0.8):
        """Return (skill, params) for a goal. Parametric skills match by template; plain skills only on an exact goal.
        If `struct` (what the window looks like now) is given, only variants recorded from a similar starting state match."""
        g = norm(goal)
        best, best_sim, best_params = None, -1.0, None
        for sk in self.list():
            if sk.get("disabled"):
                continue
            if sk.get("params"):
                m = _intent_regex(sk["intent"], sk.get("param_kinds")).match(g)
                params = {k: v.strip() for k, v in m.groupdict().items()} if m else None
            else:
                params = {} if norm(sk["intent"]) == g else None
            if params is None:
                continue
            sim = 1.0
            if struct is not None and sk.get("pre_struct"):
                a, b = set(struct), set(sk["pre_struct"])
                sim = len(a & b) / max(1, len(a | b))
                if sim < min_sim:
                    continue
            if sim > best_sim:
                best, best_sim, best_params = sk, sim, params
        return (best, best_params) if best else (None, None)

    def record_run(self, skill, ok, ms):
        st = skill.setdefault("stats", {"runs": 0, "ok": 0, "fails_in_row": 0, "ms": []})
        st["runs"] += 1
        st["ok"] += bool(ok)
        st["fails_in_row"] = 0 if ok else st.get("fails_in_row", 0) + 1
        if ok:
            st["ms"] = (st.get("ms", []) + [round(ms)])[-20:]
        if st["fails_in_row"] >= 2:
            skill["disabled"] = True  # stops replaying a skill that keeps breaking; the planner will relearn it
        self.save(skill)


def _sub_text(s, params, used):
    for k, v in params.items():
        if v and v in s:
            s = s.replace(v, "{{" + k + "}}")
            used[k] = used.get(k, 0) + 1
    return s


def struct_keys(struct):
    """frozenset of (aid-or-name, role) -> sorted list of strings (JSON-friendly, comparable)"""
    return sorted(f"{a}|{r}" for a, r in struct)


def compile_skill(goal, steps, meta=None, answer_loc=None, app=None, answer=None, pre_struct=None):
    """Turn the executed steps of a successful run into a skill. Parameters are kept only if they really occur in the
    steps (otherwise replaying with different values would silently do the wrong thing)."""
    meta = meta or {}
    declared = {k: str(v) for k, v in (meta.get("params") or {}).items() if v not in (None, "")}
    intent = meta.get("intent") or goal
    sub, used = copy.deepcopy(steps), {}
    for st in sub:
        for f in TEXT_FIELDS:
            if isinstance(st.get(f), str):
                st[f] = _sub_text(st[f], declared, used)
        if st.get("loc") and isinstance(st["loc"].get("name"), str):
            st["loc"]["name"] = _sub_text(st["loc"]["name"], declared, used)
    parametric = bool(declared) and all(used.get(k) for k in declared) and all("{" + k + "}" in intent for k in declared)
    if parametric:
        final_steps, final_intent, params = sub, intent, list(declared)
    else:
        final_steps, final_intent, params = copy.deepcopy(steps), goal, []
    suffix = "-" + hashlib.md5("|".join(pre_struct).encode()).hexdigest()[:6] if pre_struct else ""
    return {"name": slug(final_intent) + suffix, "intent": final_intent, "params": params, "app": app or {}, "steps": final_steps,
            "pre_struct": pre_struct or [], "param_kinds": {k: _kind(declared[k]) for k in params},
            "final": {"read": answer_loc} if answer_loc else {}, "example_answer": answer, "version": 1,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), "stats": {"runs": 0, "ok": 0, "fails_in_row": 0, "ms": []}}


def fill(step, params):
    """Substitute {{param}} placeholders with run-time values."""
    st = copy.deepcopy(step)
    for f in TEXT_FIELDS:
        if isinstance(st.get(f), str):
            for k, v in params.items():
                st[f] = st[f].replace("{{" + k + "}}", v)
    if st.get("loc") and isinstance(st["loc"].get("name"), str):
        for k, v in params.items():
            st["loc"]["name"] = st["loc"]["name"].replace("{{" + k + "}}", v)
    return st
