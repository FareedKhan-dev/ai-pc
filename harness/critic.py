"""Critic: the supervising editor who reviews a plan BEFORE it is rendered (a render costs ~30 s; a review ~2-4 s).

1. lint()    ~15 deterministic checks on the resolved timeline: every requirement covered, nothing dropped, a hook in
             the first 1.5 s, length vs target, titles long enough and not on top of each other, at most two effects
             at once, no full-frame overlay hiding a face/eye effect, person effects only where a face is visible,
             impact sounds on impacts, no silent video, pacing for the mood, risky (never tried) items, the ending.
2. review()  one fast model call: the request, the editor's treatment and requirement map, the timeline in absolute
             seconds, the lint results and what is possible here -> a score, issues and a few patch operations.
3. improve() applies the patches, resolves again and keeps the new plan only if the checks did not get worse.
"""
import copy
import json
import re
import time

from .report import ask_ids
from .util import parse_json

SEV = {"high": 3, "medium": 2, "low": 1}
OVERLAY_TARGETS = ("frame", "edges", "overlay", "background")

CRITIC_SYSTEM = """You are the supervising editor. You review a planned edit BEFORE it is rendered: the client's request,
the editor's treatment and requirement map, the timeline in absolute seconds, automatic check results and what is
possible here. Find what would disappoint the client or look amateur, and fix it with a few precise operations. Do not
redesign what works.
Look for: an ask with no working technique, or at the wrong moment; sync (an impact sound and a flash with every shake
or zoom punch; face/eye effects while the face is clearly visible); a hook in the first 1.5 s; pacing for the mood;
titles readable (>= 1.2 s, not on top of each other); an effect hidden by another at the same time; a weak ending.
Reply with ONE JSON object:
{"score": <0-10 for the plan as it is>, "verdict": "ship"|"fix", "issues": ["<short>", ...],
 "patch": [{"op": "set", "id": "<edit or clip id>", "field": "<plan field>", "value": <new value>},
           {"op": "move", "id": "<edit id>", "at": <absolute start, s>, "duration": <s, optional>},
           {"op": "add", "edit": {<a new edit in the plan format; absolute "start"/"at"; a new id>}},
              e.g. {"op": "add", "edit": {"id": "k1", "type": "sfx", "sound": "impact|hit|whoosh|swoosh|riser|sub_drop|thunder|glitch", "at": 0.5}},
           {"op": "remove", "id": "<edit id>"}]}
Names of items: only ones already in the plan or in ALTERNATIVES. At most 6 operations; [] if it is good. No other text."""

CRITIC_DESIGN_SYSTEM = """You are the supervising editor. You review an edit BEFORE it is rendered. It was DESIGNED as shots on a
beat grid plus recipes (patterns compiled into exact edits) plus a few hand-placed extras; the timeline below is what the
code made of it. Find what would disappoint the client or look amateur and fix the DESIGN with a few precise operations;
do not redesign what works.
Look for: an ask with no working technique or at the wrong moment; a weak hook (first 1.5 s); a climax that is not the
strongest shot; shots too long for the style; two titles at once or the same words twice; face/eye effects on shots
without a clear face; an effect hidden by another; a weak ending.
Reply with ONE JSON object:
{"score": <0-10 for the design as it is>, "verdict": "ship"|"fix", "issues": ["<short>", ...],
 "patch": [{"op": "shot", "id": "<shot id>", "field": "beats|speed|around|want|file|section|reframe", "value": <new value>},
           {"op": "recipe", "use": "<recipe>", <params>} (adds or changes a recipe; "off": true removes it),
           {"op": "set", "id": "<extra edit id>", "field": "<field>", "value": <value>},
           {"op": "move", "id": "<extra edit id>", "at": <absolute start, s>},
           {"op": "add", "edit": {<a new extra edit; "on": "<shot id>" or an absolute "start"/"at">}},
           {"op": "remove", "id": "<shot id or extra edit id>"}]}
Item names only from the design or ALTERNATIVES. At most 6 operations; [] if it is good. No other text."""

SHOT_FIELDS = {"beats", "speed", "around", "want", "file", "section", "reframe", "chroma", "background"}

SETTABLE = {"name", "params", "strength", "intensity", "to", "back", "text", "position", "size", "color", "font", "bold", "outline",
            "shadow", "background", "intro", "outro", "loop", "volume", "sound", "kind", "speed", "ramp", "reframe", "fade_in",
            "fade_out", "expect", "duration", "from", "chroma", "points", "property", "over_text", "max_width", "vertical"}


def timeline(R, cat=None):
    """The resolved edit in absolute seconds (what a reviewer or a reviser needs to reason about moments)."""
    if cat is None:
        from .editplan import Catalog
        cat = Catalog.shared()
    lines = []
    for c in R.get("clips", []):
        sp = "/".join(f"{p['speed']:g}x" for p in c["pieces"])
        lines.append(f"  clip {c['id']} {c['start']:.1f}-{c['end']:.1f} s: {c['file']} (file {c['window'][0]:.1f}-{c['window'][1]:.1f} s, speed {sp})")
    for e in sorted(R.get("edits", []), key=lambda e: (e.get("window") or [0])[0]):
        w = e.get("window") or [0, 0]
        what = e.get("text") or e.get("sfx") or e.get("file") or ""
        if e.get("item"):
            card = cat.card(e["item"])
            what = f"{card.get('en')} ({card['name']})" + (f" [target {card['target']}]" if card.get("target") else "")
        if e["type"] in ("shake", "zoom"):
            what = f"strength {e.get('strength')}" if e["type"] == "shake" else f"to x{e.get('to')}{' and back' if e.get('back') else ''}"
        lines.append(f"  {e['id']} {e['type']} {w[0]:.1f}-{w[1]:.1f} s: {what}" + (f" on {e['on']}" if e.get("on") else ""))
    return "\n".join(lines)


def _overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def lint(R, plan, brief, cat=None):
    if cat is None:
        from .editplan import Catalog
        cat = Catalog.shared()
    issues = []

    def add(sev, eid, issue, hint):
        issues.append({"severity": sev, "id": eid, "issue": issue, "hint": hint})
    end = R.get("end", 0.0)
    edits = [e for e in R.get("edits", []) if e.get("window")]
    present = {e["id"] for e in R.get("edits", [])} | {c["id"] for c in R.get("clips", [])}
    for n in R.get("notes", []):
        m = re.match(r"(?:edit|clip|layer) (\S+?)[: ]", n)
        if any(w in n for w in ("dropped", "skipped", "no free item")):
            add("high", m.group(1) if m else "global", n, "use another candidate or a built-in technique")
    think = plan.get("think") if isinstance(plan.get("think"), dict) else {}
    reqs = think.get("requirements") or []
    if not reqs:
        add("medium", "global", "no requirement map in the plan", "map every ask to edit ids")
    made = plan.get("_recipe_ids") or {}
    for q in reqs:
        ids = [j for i in (q.get("edits") or []) if isinstance(i, str) for j in ask_ids(i, made, R)]
        if not ids:
            add("medium", "global", f"requirement '{q.get('ask')}' is not tied to any edit", "add an edit for it")
        elif not any(i in present for i in ids):
            add("high", ids[0], f"requirement '{q.get('ask')}' lost its edits ({', '.join(ids)})", "re-add a working edit for it")
    if not any(e["window"][0] < 1.5 and e["type"] in ("effect", "transition", "text", "zoom", "shake", "animation") for e in edits):
        add("medium", "global", "nothing happens in the first 1.5 s (no hook)", "open with a title, a zoom punch or an effect")
    tgt = brief.get("target_seconds")
    if isinstance(tgt, (int, float)) and tgt > 0 and abs(end - tgt) > max(2.0, 0.2 * tgt):
        add("medium", "global", f"the video is {end:.1f} s, the target was {tgt} s", "change clip durations")
    alltexts = [e for e in edits if e["type"] == "text"]
    for i, a in enumerate(alltexts):
        for b in alltexts[i + 1:]:
            if _overlap(a["window"], b["window"]) and (str(a["id"]).startswith("kt") != str(b["id"]).startswith("kt")):
                add("medium", b["id"], f"two titles at once: '{a['text'][:20]}' and '{b['text'][:20]}'", "keep one title per moment")
    texts = [e for e in edits if e["type"] == "text" and not str(e["id"]).startswith("kt")]  # kinetic words are short by design
    for t in texts:
        if t["window"][1] - t["window"][0] < 1.2:
            add("medium", t["id"], f"title '{t['text'][:30]}' is on screen only {t['window'][1] - t['window'][0]:.1f} s", "keep titles >= 1.2 s")
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if _overlap(a["window"], b["window"]) and a.get("box") and b.get("box"):
                ax0, ay0, ax1, ay1 = a["box"]
                bx0, by0, bx1, by1 = b["box"]
                if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                    add("medium", b["id"], f"titles {a['id']} and {b['id']} cover each other", "move one or change its time")
    fx = [e for e in edits if e["type"] == "effect" and not e.get("layer")]  # textures and quick accents are not "effects at once"
    for e in fx:
        at_once = [o for o in fx if o is not e and _overlap(o["window"], e["window"])]
        if len(at_once) >= 2:
            add("medium", e["id"], f"{len(at_once) + 1} effects at once around {e['window'][0]:.1f} s", "at most two effects at the same moment")
        if e.get("category") == "character_effect":
            if e.get("face_share", 1) < 0.3:
                add("high", e["id"], f"person effect at {e['window'][0]:.1f}-{e['window'][1]:.1f} s but a clear face is visible only "
                                     f"{e.get('face_share', 0) * 100:.0f}% of that time", "move it where the face is visible, or use a full-frame effect")
            for o in at_once:
                card = cat.card(o["item"]) if o.get("item") else {}
                if o.get("category") == "scene_effect" and card.get("target") in OVERLAY_TARGETS:
                    add("high", o["id"], f"full-frame effect {card.get('en')} runs over the person effect {e['id']} and may hide it",
                        "put them one after the other")
    impacts = [e for e in edits if e["type"] == "shake" or (e["type"] == "zoom" and e.get("back"))]
    sounds = [e for e in edits if e["type"] == "audio"]
    if any(not s.get("sfx") for s in sounds):
        impacts = []  # music under a beat-synced edit already carries every hit
    for e in impacts:
        if not any(abs(s["window"][0] - e["window"][0]) <= 0.25 or (s.get("sfx") == "riser" and abs(s["window"][1] - e["window"][0]) <= 0.25) for s in sounds):
            add("low", e["id"], f"{e['type']} at {e['window'][0]:.1f} s has no impact sound with it", "add an sfx impact or hit at that moment")
    clip_sound = any(c.get("volume", 1) > 0.05 for c in R.get("clips", []))
    if not sounds and not clip_sound:
        add("medium", "global", "the video is silent", "add music or sound effects")
    if str(brief.get("pace", "")).lower() == "fast":
        for c in R.get("clips", []):
            if len(c["pieces"]) == 1 and c["pieces"][0]["speed"] >= 1 and c["pieces"][0]["kind"] == "video" and c["dur"] > 4.5:
                add("low", c["id"], f"a {c['dur']:.1f} s shot in a fast-paced edit", "cut it shorter or add movement")
    untried = sorted({e["item"] for e in edits if e.get("item") and e["item"] not in cat.boost})
    if untried:
        add("low", "global", f"{len(untried)} item(s) never used here before ({', '.join(u.split(':', 1)[1] for u in untried[:4])})",
            "fine, but prefer proven items when equal")
    if end > 2 and not any(e["window"][1] >= end - 1.2 for e in edits if e["type"] in ("text", "zoom", "animation", "effect", "audio")):
        add("low", "global", "the ending has no final beat (title, push-in, outro or sound)", "end on a moment")
    return issues


def score(issues):
    return sum(SEV.get(i["severity"], 1) for i in issues)


def alternatives(groups, cat, limit=40):
    proven = {k for k, f in cat.boost.items() if f > 1.3}
    out = []
    for g, cards in groups.items():
        for c in cards:
            k = f"{c['category']}:{c['name']}"
            out.append(f"{c['category']} {c['name']} \"{c.get('en')}\"" + (" (proven)" if k in proven else "") +
                       (f" [target {c['target']}]" if c.get("target") else ""))
    return "\n".join(out[:limit])


def review(planner, request, brief, plan, R, issues, aware_text, alts, design=None):
    think = plan.get("think") or {}
    checks = "\n".join(f"  [{i['severity']}] {i['id']}: {i['issue']} -> {i['hint']}" for i in issues) or "  none"
    dz = ""
    if design is not None:
        slim = {k: design.get(k) for k in ("style", "music", "shots", "recipes", "edits")}
        dz = f"DESIGN:\n{json.dumps(slim, ensure_ascii=False)}\nRHYTHM: {json.dumps(plan.get('_rhythm'), ensure_ascii=False)}\n\n"
    user = (f"REQUEST:\n{request}\n\nTREATMENT AND REQUIREMENT MAP:\n{json.dumps(think, ensure_ascii=False)}\n\n{dz}"
            f"TIMELINE (absolute seconds, {R.get('end', 0):.1f} s long):\n{timeline(R)}\n\nAUTOMATIC CHECKS:\n{checks}\n\n"
            f"{aware_text}\n\nALTERNATIVES:\n{alts}\n\nReview it and reply with the JSON.")
    system = CRITIC_DESIGN_SYSTEM if design is not None else CRITIC_SYSTEM
    r = planner._call("fast", [{"role": "system", "content": system}, {"role": "user", "content": user}])
    d = parse_json(r.text)
    return d if isinstance(d, dict) else {}


def apply_patch(plan, ops):
    """Apply critic operations to a plan (a copy). Returns (new plan, descriptions of what was applied)."""
    p = copy.deepcopy(plan)
    edits = [e for e in p.get("edits") or [] if isinstance(e, dict)]
    p["edits"] = edits
    clips = [c for c in (p.get("clips") or []) + (p.get("layers") or []) if isinstance(c, dict)]
    by = {**{c.get("id"): c for c in clips}, **{e.get("id"): e for e in edits}}
    done = []
    for op in (ops or [])[:8]:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        tgt = by.get(op.get("id"))
        if kind == "set" and tgt is not None and op.get("field") in SETTABLE:
            tgt[op["field"]] = op.get("value")
            done.append(f"set {op['id']}.{op['field']} = {json.dumps(op.get('value'), ensure_ascii=False)[:60]}")
        elif kind == "move" and tgt is not None and tgt in edits and isinstance(op.get("at", op.get("start")), (int, float)):
            at = float(op.get("at", op.get("start")))
            tgt.pop("on", None)
            if str(tgt.get("type")) in ("sfx", "audio", "sound_effect"):
                tgt["at"] = at
            else:
                tgt["start"] = at
                if tgt.get("type") == "transition":
                    continue
            if isinstance(op.get("duration"), (int, float)):
                tgt["duration"] = float(op["duration"])
            done.append(f"move {op['id']} to {at:.2f} s")
        elif kind == "add" and isinstance(op.get("edit"), dict) and op["edit"].get("type"):
            e = dict(op["edit"])
            if str(e.get("type")).lower() in ("audio", "sound", "sound_effect") and not e.get("file") and (e.get("sound") or e.get("name")):
                e["type"], e["sound"] = "sfx", e.get("sound") or e.get("name")  # a sound effect without a file is a synthesised one
            n, base = 1, str(e.get("id") or "k")
            while e.get("id") in by or not e.get("id"):
                e["id"] = f"{base}{n}"
                n += 1
            edits.append(e)
            by[e["id"]] = e
            done.append(f"add {e['id']} ({e.get('type')} {e.get('name') or e.get('sound') or e.get('text') or ''})".strip())
        elif kind == "remove" and tgt is not None and tgt in edits:
            edits.remove(tgt)
            done.append(f"remove {op['id']}")
    return p, done


def apply_design_patch(design, ops):
    """Critic operations on a design (shots, recipes, extras). Returns (new design, descriptions)."""
    d = copy.deepcopy(design)
    shots = [x for x in d.get("shots") or [] if isinstance(x, dict)]
    d["shots"] = shots
    extras = [e for e in d.get("edits") or [] if isinstance(e, dict)]
    d["edits"] = extras
    recipes = [r for r in d.get("recipes") or [] if isinstance(r, dict)]
    d["recipes"] = recipes
    sb, eb = {x.get("id"): x for x in shots}, {e.get("id"): e for e in extras}
    think = d.get("think") if isinstance(d.get("think"), dict) else {}
    # what delivers one of the client's asks is never removed (it can be changed or moved)
    asked = {i for q in think.get("requirements") or [] if isinstance(q, dict) for i in q.get("edits") or [] if isinstance(i, str)}
    done = []
    for op in (ops or [])[:8]:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if kind == "remove" and op.get("id") in asked:
            done.append(f"kept {op['id']} (it delivers an ask; not removed)")
            continue
        if kind == "shot" and op.get("id") in sb and op.get("field") in SHOT_FIELDS:
            field, value = op["field"], op.get("value")
            if field == "reframe" and isinstance(value, dict) and not ({"x", "y", "zoom"} & set(value)):
                if not value.get("file"):
                    continue  # not a framing at all
                field, value = "file", value["file"]  # "reframe": {"file": ...} = use other footage for this shot
            sb[op["id"]][field] = value
            done.append(f"shot {op['id']}.{field} = {json.dumps(value, ensure_ascii=False)[:50]}")
        elif kind == "recipe" and op.get("use"):
            r = {k: v for k, v in op.items() if k != "op"}
            same = [x for x in recipes if x.get("use") == r["use"]]
            if same and r["use"] not in ("kinetic_title", "hook", "captions"):
                same[0].update(r)
            else:
                recipes.append(r)
            done.append(f"recipe {r['use']}" + (" off" if r.get("off") else f" {json.dumps({k: v for k, v in r.items() if k != 'use'}, ensure_ascii=False)[:60]}"))
        elif kind in ("set", "move", "add") or (kind == "remove" and op.get("id") in eb):
            sub, ds = apply_patch({"clips": [], "edits": extras}, [op])
            d["edits"] = extras = sub["edits"]
            eb = {e.get("id"): e for e in extras}
            done += ds
        elif kind == "remove" and op.get("id") in sb and len(shots) > 1:
            shots.remove(sb.pop(op["id"]))
            done.append(f"remove shot {op['id']}")
    return d, done


def improve(planner, request, brief, plan, analyses, aware_text, groups, log=print, design=None):
    """Review before rendering. Returns (plan, resolved, critique summary)."""
    from .editplan import Catalog, resolve
    t0 = time.perf_counter()
    cat = Catalog.shared()
    R = resolve(plan, analyses)
    before = lint(R, plan, brief, cat)
    crit = review(planner, request, brief, plan, R, before, aware_text, alternatives(groups, cat), design)
    ops = crit.get("patch") if isinstance(crit.get("patch"), list) else []
    summary = {"score": crit.get("score"), "verdict": crit.get("verdict"), "issues": crit.get("issues") or [],
               "lint_before": before, "applied": [], "kept": True, "design": design}
    if ops:
        if design is not None:  # a designed edit: change the design, let the code cut it on the beat again
            from .recipes import compose
            design2, done = apply_design_patch(design, ops)
        else:
            plan2, done = apply_patch(plan, ops)
        try:
            if design is not None:
                plan2 = compose(design2, analyses, cat, lambda *a: None, request)
            R2 = resolve(plan2, analyses)
            after = lint(R2, plan2, brief, cat)
        except Exception as e:  # noqa: BLE001  (a bad patch must not break the run)
            after, R2 = None, None
            log(f"critic patch rejected: {type(e).__name__}: {e}")
        if R2 is not None and score(after) <= score(before):
            plan, R = plan2, R2
            summary.update(applied=done, lint_after=after)
            if design is not None:
                summary["design"] = design2
        else:
            summary.update(kept=False, rejected=done, lint_after=after)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    log(f"critic {summary['seconds']} s: score {summary['score']}/10, {len(before)} check(s) flagged"
        + (f"; applied {len(summary['applied'])}: " + "; ".join(summary["applied"]) if summary["applied"] else "")
        + ("; patch rejected (it made the checks worse)" if not summary["kept"] else ""))
    return plan, R, summary
