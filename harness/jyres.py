"""Which catalogue items JianYing can actually use here. pyJianYingDraft's catalogue lists every item, but JianYing
downloads each effect / filter / transition / animation / font the first time a project uses it, and some of them never
arrive for an anonymous user (removed, region-locked or account-only). A project with such an item shows "动画丢失"
(missing) in the editor, and exporting it asks for a login, which we never do.

So: after JianYing opens a project, check its download cache for every item the edit uses; record ok / missing per
item in kb/<engine>/availability.json; the planner and resolver then avoid missing items and prefer items already
downloaded (they also load instantly).
"""
import json
import os
import time
from pathlib import Path

from .config import ROOT

CACHE = Path(os.environ.get("LOCALAPPDATA", "")) / "JianyingPro" / "User Data" / "Cache"
AVAIL = ROOT / "kb" / "jianying" / "availability.json"
NO_DOWNLOAD = {"mask", "blend"}  # built into the app


def load():
    return json.loads(AVAIL.read_text(encoding="utf-8")) if AVAIL.exists() else {}


def save(d):
    AVAIL.parent.mkdir(parents=True, exist_ok=True)
    AVAIL.write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")


def is_cached(item):
    if item["category"] in NO_DOWNLOAD:
        return True
    ids = {str(item.get("effect_id")), str(item.get("resource_id"))}
    return any((CACHE / sub / i).exists() for sub in ("effect", "artistEffect") for i in ids if i and i != "None")


def used_items(emap):
    """Catalogue keys an edit map uses (effects, filters, transitions, animations, fonts, sound effects)."""
    keys = set()
    for e in emap["edits"]:
        for k in ("item", "effect", "intro"):
            if isinstance(e.get(k), str) and ":" in e[k]:
                keys.add(e[k])
        st = e.get("style") or {}
        if st.get("font"):
            keys.add(st["font"])
    for c in emap["clips"]:
        if c.get("mask"):
            keys.add(f"mask:{c['mask']['type']}")
        if c.get("blend"):
            keys.add(f"blend:{c['blend']}")
    return keys


def wait_downloads(keys, items, timeout=45, settle=5, kill=None, on_poll=None):
    """After a project is opened: wait until every item is downloaded, or nothing new arrived for `settle` seconds.
    Returns (ok keys, missing keys)."""
    t0 = last = time.time()
    have = {k for k in keys if is_cached(items[k])}
    while time.time() - t0 < timeout:
        if kill is not None and kill.event.is_set():
            break
        if len(have) == len(keys):
            break
        now = {k for k in keys if is_cached(items[k])}
        if now != have:
            have, last = now, time.time()
        elif time.time() - last > settle:
            break
        if on_poll:
            on_poll()
        time.sleep(0.5)
    return have, set(keys) - have


# states, best first: exported (proven in a finished export) > ok (downloaded) > unknown; never used: missing, login
RANK = {"exported": 3, "ok": 2, "missing": -1, "login": -2}


def record(ok=(), missing=(), exported=(), login=()):
    """Update the per-item record. A worse finding (missing / login) always wins over an older good one."""
    d = load()
    stamp = time.strftime("%Y-%m-%dT%H:%M")
    for state, keys in (("ok", ok), ("exported", exported), ("missing", missing), ("login", login)):
        for k in keys:
            r = d.setdefault(k, {})
            r[state] = r.get(state, 0) + 1
            old = r.get("state")
            if state in ("missing", "login") or old not in ("missing", "login") and RANK.get(state, 0) >= RANK.get(old, 0):
                r["state"] = state
            r["seen"] = stamp
    save(d)
    return d


def seed(items):
    """First run: every item already in JianYing's cache counts as available."""
    d = load()
    n = 0
    for k, it in items.items():
        if k not in d and is_cached(it):
            d[k] = {"ok": 1, "state": "ok", "seen": "cache"}
            n += 1
    save(d)
    return n


def states():
    """{key: 'exported' | 'ok' | 'missing' | 'login'} from the record."""
    return {k: v.get("state") for k, v in load().items()}


def blocked():
    return {k for k, v in states().items() if v in ("missing", "login", "invisible")}


def record_checks(emap, report):
    """Remember per catalogue item how it looked in real exports: an item that was invisible twice and never seen
    becomes 'invisible' (it does not render here: e.g. it needs a body-segmentation model that never arrived)."""
    d = load()
    stamp = time.strftime("%Y-%m-%dT%H:%M")
    by_id = {e["id"]: e for e in emap["edits"]}
    for r in report["results"]:
        e = by_id.get(r.get("id"))
        if not e or e.get("type") not in ("effect", "filter", "transition", "animation") or not e.get("item"):
            continue
        rec = d.setdefault(e["item"], {})
        why = str(r.get("why", ""))
        if r["status"] == "pass":
            rec["visible"] = rec.get("visible", 0) + 1
        elif r["status"] == "fail" and ("not visible" in why or "no colour change" in why):
            rec["not_visible"] = rec.get("not_visible", 0) + 1
            rec["not_visible_why"] = (rec.get("not_visible_why", []) + [why[:80]])[-3:]
        if rec.get("not_visible", 0) >= 2 and not rec.get("visible") and rec.get("state") not in ("missing", "login"):
            rec["state"] = "invisible"
        rec["checked"] = stamp
    save(d)


# ------------------------------------------------------------------------------------------------ variety
USAGE = ROOT / "kb" / "jianying" / "usage.json"


def note_usage(emap, keep=12):
    """Remember which catalogue items a finished video used (the last `keep` videos), so the next videos look
    different: the same filter, transition and font in every video reads as a template."""
    d = json.loads(USAGE.read_text(encoding="utf-8")) if USAGE.exists() else []
    d = [x for x in d if x.get("draft") != emap.get("draft")]
    d.append({"draft": emap.get("draft"), "items": sorted(used_items(emap))})
    USAGE.write_text(json.dumps(d[-keep:], ensure_ascii=False, indent=0), encoding="utf-8")


def recency(last=5, step=0.6, floor=0.25):
    """{item: factor < 1} for items used in the last few videos (0.6 per video that used it): rank them lower."""
    d = json.loads(USAGE.read_text(encoding="utf-8")) if USAGE.exists() else []
    out = {}
    for x in d[-last:]:
        for k in x.get("items", []):
            out[k] = max(floor, out.get(k, 1.0) * step)
    return out
