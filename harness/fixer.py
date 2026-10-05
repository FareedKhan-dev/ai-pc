"""Fixer: turns verification results into plan patches. Only the failed or weak edits change; everything that passed
stays exactly as it was. Deterministic rules first (stronger parameters, longer transitions, bigger zoom, more legible
text); when an item itself is the problem it is swapped for the closest free item that works here (preferring items
proven in earlier exports). With a model available, "visible but not what was asked" is judged by the fast model,
which picks the replacement from catalogue candidates.

patch(plan, resolved, report, tried) -> (new plan, [change descriptions], {edit ids to re-check})
"""
import copy
import json

from .editplan import EFFECT_CATS, Catalog
from .util import parse_json

STRONG = ("intensity", "strength", "size", "range", "number", "color", "filter", "luminance", "speed")

SWAP_SYSTEM = """You fix one edit of a video. It was checked in the exported video and did not look as intended.
Pick the best replacement from CANDIDATES (copy its name exactly), or "keep" if none is closer to the intention.
Reply with ONE JSON object: {"name": "<candidate name or keep>", "why": "<=12 words"}"""


def _raw_edit(plan, eid):
    for e in plan.get("edits") or []:
        if isinstance(e, dict) and e.get("id") == eid:
            return e
    return None


def _owner_text(plan, resolved, an_id):
    """The plan text an inline text animation came from (text 'intro'/'outro'/'loop' fields), and which field."""
    a = next((e for e in resolved["edits"] if e["id"] == an_id), None)
    if not a or not a.get("on_text"):
        return None, None
    return _raw_edit(plan, a["on"]), a["kind"]


class Fixer:
    def __init__(self, catalog=None, planner=None, log=print):
        self.cat, self.planner, self.log = catalog or Catalog.shared(), planner, log

    def _swap(self, card_cats, query, avoid, expect=None, seen=None):
        """A replacement item name for the categories, by meaning, avoiding names already tried."""
        ix = self.cat.index
        hits = [h for h in ix.search(query, categories=card_cats, k=12, exclude=self.cat.missing, boost=self.cat.boost)
                if h["name"] not in avoid]
        if not hits:
            return None, "no other candidate"
        if self.planner is not None and expect and seen:
            lines = "\n".join(f"- {h['name']} \"{h.get('en')}\": {h.get('desc')}" for h in hits[:8])
            r = self.planner._call("fast", [{"role": "system", "content": SWAP_SYSTEM},
                                            {"role": "user", "content": f"INTENDED: {expect}\nSEEN IN THE EXPORT: {seen}\nCANDIDATES:\n{lines}"}])
            d = parse_json(r.text) or {}
            name = str(d.get("name") or "")
            if name and name != "keep" and any(h["name"] == name for h in hits):
                return name, f"model pick: {d.get('why', '')}"
            if name == "keep":
                return None, "model: keep"
        return hits[0]["name"], f"closest match \"{hits[0].get('en')}\""

    def patch(self, plan, resolved, report, tried=None):
        plan = copy.deepcopy(plan)
        tried = tried if tried is not None else {}
        changes, recheck = [], set()
        redits = {e["id"]: e for e in resolved["edits"]}
        for r in report["results"]:
            st, rid = r.get("status"), r.get("id")
            if st not in ("fail", "warn"):
                continue
            re_ = redits.get(rid)
            raw = _raw_edit(plan, rid)
            hist = tried.setdefault(rid, [])
            why = r.get("why", "")
            if re_ is None:
                if r.get("type") == "clip":  # framing: keep the subject in view; a removed screen fully gone
                    c = next((c for c in plan.get("clips") or [] if c.get("id") == rid), None)
                    if c is not None and c.get("reframe") != "subject" and "edge" in why:
                        c["reframe"] = "subject"
                        changes.append(f"{rid}: reframed on the subject ({why})")
                        recheck.add(rid)
                    if c is not None and "screen colour" in why:
                        ch = c.get("chroma") if isinstance(c.get("chroma"), dict) else {}
                        c["chroma"] = {**ch, "color": ch.get("color", "auto"), "intensity": min(100, float(ch.get("intensity", 30) or 30) + 25)}
                        c["background"] = "#0A0A12"
                        changes.append(f"{rid}: stronger screen removal and a dark background ({why})")
                        recheck.add(rid)
                continue
            typ = re_["type"]
            if re_.get("layer") == "texture":
                continue  # grain / vignette / bars are subtle on purpose
            if typ == "effect" and raw is not None and any(w in why.lower() for w in ("obscur", "covered", "hidden", "blocked")):
                # hidden behind another effect at the same moment: move the other one out of the way
                a0, a1 = re_["window"]
                others = [o for o in resolved["edits"] if o["type"] == "effect" and o["id"] != rid and o["window"][0] < a1 and a0 < o["window"][1]]
                moved = False
                for o in others:
                    ro = _raw_edit(plan, o["id"])
                    if ro is None or o["id"] in tried.get("_moved", []):
                        continue
                    o0, o1 = o["window"]
                    # keep the part of the other effect that lies outside this one (the longer side)
                    before, after = max(0.0, a0 - o0), max(0.0, o1 - a1)
                    if max(before, after) < 0.4:
                        # no room inside its own window: the longest free stretch of the same clip, else remove it
                        clip = next((c for c in resolved["clips"] if c["start"] - 1e-6 <= o0 < c["end"]), None)
                        slots = [(clip["start"], a0), (a1, clip["end"])] if clip else []
                        s0, s1 = max(slots, key=lambda x: x[1] - x[0]) if slots else (0, 0)
                        if s1 - s0 >= 0.6:
                            n1 = min(s1, s0 + (o1 - o0))
                            ro.pop("on", None)
                            ro["start"], ro["duration"] = round(s0, 3), round(n1 - s0, 3)
                            changes.append(f"{o['id']}: moved to {s0:.1f}-{n1:.1f} s (it hid {rid}); the two now follow each other")
                        else:
                            ro["_drop"] = True
                            changes.append(f"{o['id']}: removed, it hid {rid} ({why[:50]})")
                    else:
                        n0, n1 = (o0, a0) if before >= after else (a1, o1)
                        ro.pop("on", None)
                        ro["start"], ro["duration"] = round(n0, 3), round(n1 - n0, 3)
                        changes.append(f"{o['id']}: moved to {n0:.1f}-{n1:.1f} s so it no longer hides {rid}")
                    tried.setdefault("_moved", []).append(o["id"])
                    recheck |= {rid, o["id"]}
                    moved = True
                if moved:
                    continue
            if typ == "effect" and raw is not None:
                card = self.cat.card(re_["item"])
                strong = [p for p in (card.get("params") or {}) if any(s in p for s in STRONG)]
                if "strength" not in hist and strong and st == "fail" or ("strength" not in hist and strong and "weak" in why):
                    raw["params"] = {**(raw.get("params") or {}), **{p.replace("effects_adjust_", ""): 90 for p in strong[:2]}}
                    if raw.get("duration") and raw["duration"] < 1.5:
                        raw["duration"] = round(raw["duration"] + 0.6, 2)
                    hist.append("strength")
                    changes.append(f"{rid}: {card['name']} made stronger ({', '.join(strong[:2])} -> 90)")
                    recheck.add(rid)
                    continue
                cats = [card["category"]]
                if card["category"] == "character_effect" and re_.get("face_share", 1) < 0.3:
                    cats = ["scene_effect"]  # no clear person there: a full-frame effect instead
                avoid = set(hist) | {card["name"]}
                name, how = self._swap(cats if st == "fail" else list(EFFECT_CATS), f"{re_.get('expect')} {card.get('en')}", avoid,
                                       re_.get("expect"), why)
                if name:
                    hist.append(card["name"])
                    raw["name"] = name
                    raw.pop("params", None)
                    changes.append(f"{rid}: {card['name']} -> {name} ({how}; was: {why[:60]})")
                    recheck.add(rid)
            elif typ == "filter" and raw is not None:
                s = float(raw.get("strength", raw.get("intensity", 80)) or 80)
                if s < 95 and "strength" not in hist:
                    raw["strength"] = min(100, s + 30)
                    hist.append("strength")
                    changes.append(f"{rid}: filter strength {s:.0f} -> {raw['strength']:.0f}")
                else:
                    card = self.cat.card(re_["item"])
                    name, how = self._swap(["filter"], f"{re_.get('expect')} {card.get('look') or ''}", set(hist) | {card["name"]})
                    if name:
                        hist.append(card["name"])
                        raw["name"] = name
                        changes.append(f"{rid}: filter {card['name']} -> {name} ({how})")
                recheck.add(rid)
            elif typ == "transition" and raw is not None:
                d = float(raw.get("duration") or 0.5)
                if plan.get("_template") and st != "fail":
                    continue  # a template's transitions keep their length and kind: a faint one is the template's own style
                if d < 0.45 and "longer" not in hist and not plan.get("_template"):
                    raw["duration"] = 0.6
                    hist.append("longer")
                    changes.append(f"{rid}: transition {d:.2f} -> 0.6 s")
                else:
                    card = self.cat.card(re_["item"])
                    name, how = self._swap(["transition"], f"{re_.get('expect')} {card.get('motion') or ''}", set(hist) | {card["name"]})
                    if name:
                        hist.append(card["name"])
                        raw["name"] = name
                        changes.append(f"{rid}: transition {card['name']} -> {name} ({how})")
                recheck.add(rid)
            elif typ == "shake" and raw is not None and st == "fail":
                raw["strength"] = round(min(1.0, float(raw.get("strength", 0.5)) + 0.35), 2)
                changes.append(f"{rid}: shake strength -> {raw['strength']}")
                recheck.add(rid)
            elif typ == "zoom" and raw is not None and st == "fail" and any(
                    l["start"] - 0.1 <= re_["window"][0] <= l["end"] for l in resolved.get("layers", [])):
                raw["_drop"] = True  # hidden under an overlay: escalating it would never show
                changes.append(f"{rid}: removed (it happens under an overlay, where nobody can see it)")
            elif typ == "zoom" and raw is not None and st == "fail":
                raw["to"] = round(min(1.8, float(raw.get("to", 1.25)) + 0.2), 2)
                changes.append(f"{rid}: zoom -> x{raw['to']}")
                recheck.add(rid)
            elif typ in ("text", "captions") and raw is not None:
                if "read as" in why or "hard to read" in why:
                    raw["size"] = min(30, float(raw.get("size", 10)) + 2)
                    raw.setdefault("outline", {"color": "#000000", "width": 60})
                    if "read as" in why and "font" not in hist:  # a font that does not render the words: a proven one
                        words = str(raw.get("text") or "")
                        good = [k for k, f in self.cat.boost.items() if k.startswith("font:") and f > 1.3]
                        if sum(ch.isascii() for ch in words) >= 0.8 * max(1, len(words)):  # English: a Latin face first
                            good.sort(key=lambda k: self.cat.index.notes.get(k, {}).get("script") != "latin")
                        if good:
                            raw["font"] = self.cat.item(good[0])["name"]
                            hist.append("font")
                    changes.append(f"{rid}: text size {raw['size']:.0f}, outline" + (f", font {raw.get('font')}" if "font" in hist else ""))
                elif "covers" in why:  # just out of the app's way: subtitles stay low, titles stay high (never the centre)
                    pos = (re_ or {}).get("position")
                    y = pos[1] if isinstance(pos, list) and len(pos) == 2 else 0
                    raw["position"] = "lower" if y <= 0 else "upper"
                    changes.append(f"{rid}: text moved to the {raw['position']} third (was under the app's buttons)")
                recheck.add(rid)
            elif typ == "animation":
                owner, field = _owner_text(plan, resolved, rid)
                target = owner if owner is not None else raw
                if target is None or st == "warn" or "no animation seen" not in why:
                    continue  # an animation that moves (even differently, or unclear) is kept
                card = self.cat.card(re_["item"])
                name, how = self._swap([card["category"]], f"{re_.get('expect')} {card.get('motion') or ''}", set(hist) | {card["name"]})
                if name:
                    hist.append(card["name"])
                    if owner is not None:
                        owner[field] = name
                    else:
                        raw["name"] = name
                    changes.append(f"{rid}: animation {card['name']} -> {name} ({how})")
                    recheck.add(rid)
            elif typ == "audio" and raw is not None and st == "fail":
                raw["volume"] = round(min(2.0, float(raw.get("volume", 1.0)) * 1.6), 2)
                changes.append(f"{rid}: volume -> {raw['volume']}")
                recheck.add(rid)
        plan["edits"] = [e for e in plan.get("edits") or [] if not (isinstance(e, dict) and e.get("_drop"))]
        return plan, changes, recheck


def merge_reports(old, new):
    """The newest result per edit id."""
    by = {r["id"]: r for r in old["results"]}
    by.update({r["id"]: r for r in new["results"]})
    res = list(by.values())
    order = {"fail": 0, "warn": 1, "pass": 2, "skip": 3}
    res.sort(key=lambda r: (order.get(r.get("status"), 9), str(r.get("id"))))
    counts = {k: sum(1 for r in res if r.get("status") == k) for k in order}
    return {**new, "results": res, "counts": counts, "checked": len(res)}


def plan_diff(a, b):
    """Edit ids whose plan entry differs between two plans (for re-checking only what changed)."""
    ea = {e.get("id"): json.dumps(e, sort_keys=True, ensure_ascii=False) for e in a.get("edits") or [] if isinstance(e, dict)}
    eb = {e.get("id"): json.dumps(e, sort_keys=True, ensure_ascii=False) for e in b.get("edits") or [] if isinstance(e, dict)}
    return {k for k in set(ea) | set(eb) if ea.get(k) != eb.get(k)}
