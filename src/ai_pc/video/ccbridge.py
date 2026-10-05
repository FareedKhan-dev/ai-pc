"""Bridge: CapCut-international catalogue items (pyCapCut's metadata) inside JianYing projects (pyJianYingDraft).

pyCapCut lists 4,957 items; only 294 are the same resources as JianYing's (same id). The rest carry CapCut's own
resource ids. Both libraries share the metadata layout, so a CapCut item can be wrapped as a member of the matching
pyJianYingDraft enum and written into a JianYing draft. Whether JianYing can then download and render it is a
property of each item, learned like any other (jyres.py: downloaded / proven / missing / needs login).

Keys: CapCut-only items live in the merged catalogue as "<category>:cc:<name>" so they never collide with JianYing's
own "<category>:<name>" (many share a Chinese name but are different resources).
"""
import json
from functools import lru_cache

from ai_pc.video.kb import CATEGORIES, KB


@lru_cache(maxsize=1)
def _jy_ids():
    items = json.loads((KB / "jianying" / "items.json").read_text(encoding="utf-8"))
    return {(it["category"], str(it["resource_id"])) for it in items}


@lru_cache(maxsize=1)
def items():
    """CapCut-only items with merged keys: {"<category>:cc:<name>": item}."""
    p = KB / "capcut" / "items.json"
    if not p.exists():
        return {}
    out = {}
    for it in json.loads(p.read_text(encoding="utf-8")):
        if (it["category"], str(it["resource_id"])) in _jy_ids():
            continue  # the same resource is already in JianYing's own catalogue
        key = f"{it['category']}:cc:{it['name']}"
        out[key] = {**it, "key": key, "source": "capcut", "cc_key": it["key"]}
    return out


@lru_cache(maxsize=1)
def notes():
    p = KB / "capcut" / "notes.json"
    raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {k: raw[it["cc_key"]] for k, it in items().items() if it["cc_key"] in raw}


def is_cc(key):
    return ":cc:" in str(key)


def jy_member(key):
    """A pyJianYingDraft enum member that carries the CapCut item's metadata (passes the library's type checks)."""
    import pycapcut as cc
    import pyJianYingDraft as jy
    it = items()[key]
    enum_name = CATEGORIES[it["category"]][0]
    meta = getattr(getattr(cc, enum_name), it["name"]).value
    m = object.__new__(getattr(jy, enum_name))
    m._name_ = f"cc_{it['name']}"
    m._value_ = meta
    return m
