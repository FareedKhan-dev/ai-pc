"""Lessons: what earlier runs taught the agent, as short rules the planner and the critic read before every edit.

Sources: the fixer (a repair it had to make is a mistake not to plan again), the critic (issues it keeps finding),
and the user's own follow-ups (a request to change something is a preference). Same rule twice = a higher count; the
most frequent and most recent rules are shown first. Stored in kb/jianying/lessons.json.
"""
import json
import re
import time

from ai_pc.core.config import ROOT

FILE = ROOT / "kb" / "jianying" / "lessons.json"


def load():
    return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else []


def _save(rows):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def add(rule, source, why="", kind="rule"):
    rows = load()
    key = re.sub(r"\W+", " ", rule.lower()).strip()
    for r in rows:
        if re.sub(r"\W+", " ", r["rule"].lower()).strip() == key:
            r["count"] = r.get("count", 1) + 1
            r["last"] = time.strftime("%Y-%m-%d %H:%M")
            break
    else:
        rows.append({"rule": rule, "why": why, "source": source, "kind": kind, "count": 1, "last": time.strftime("%Y-%m-%d %H:%M")})
    _save(rows)


def text(k=8):
    rows = sorted(load(), key=lambda r: (r.get("count", 1), r.get("last", "")), reverse=True)[:k]
    if not rows:
        return ""
    prefs = [r for r in rows if r.get("kind") == "preference"]
    rules = [r for r in rows if r.get("kind") != "preference"]
    out = []
    if rules:
        out.append("lessons from earlier runs: " + " | ".join(f"{r['rule']}" + (f" (x{r['count']})" if r.get("count", 1) > 1 else "") for r in rules))
    if prefs:
        out.append("this user asked before: " + " | ".join(r["rule"] for r in prefs))
    return "\n".join(out)


def from_fixes(changes, resolved):
    """Turn the fixer's repairs into rules."""
    names = {e["id"]: e for e in resolved.get("edits", [])}
    for c in changes:
        m = re.match(r"(\S+): moved to .* \(it hid (\S+)\)", c) or re.match(r"(\S+): removed, it hid (\S+)", c)
        if m:
            a, b = names.get(m.group(1), {}), names.get(m.group(2), {})
            add(f"do not overlap a full-frame overlay effect ({a.get('en') or a.get('item', '?')}) with a face/eye effect "
                f"({b.get('en') or b.get('item', '?')}): put them one after the other", "fixer", why=c)
            continue
        m = re.match(r"(\S+): (.+?) -> (.+?) \(", c)
        if m and "strength" not in c:
            add(f"'{m.group(2)}' did not look as intended here; prefer '{m.group(3)}' for that idea", "fixer", why=c)


def from_feedback(request):
    """A follow-up request is a preference of this user."""
    add(f"\"{request.strip()[:140]}\"", "user", kind="preference")
