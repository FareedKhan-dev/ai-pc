"""Reflection: an honest report of one edit, written like an editor's hand-over note.

  scorecard     every ask of the client -> met / partly / not met, with the verifier's evidence at that moment
  substituted   what could not be done as asked, what was done instead, and why (VIP-only, not downloadable,
                did not render here, footage limits...)
  quality       hook, pacing (shot lengths), effects/transitions/titles, sound, loudness of the export
  flaws         what the checks still flag
  next          the best next improvements, most valuable first (what the user could give, what the agent could do)
  cost          time and AI spend of the run
Pure computation over the session (~0.5 s, mostly the loudness of the export). Saved as out/video/reports/<draft>.md.
"""

import re

from ai_pc.core.config import ROOT

REPORTS = ROOT / "out" / "video" / "reports"


def _status(ids, results):
    got = [results[i] for i in ids if i in results]
    if not ids:
        return "unverified", []
    if not got:
        return "not checked", []
    st = [g["status"] for g in got]
    if all(s == "pass" for s in st):
        return "met", got
    if any(s == "pass" for s in st) or any(s in ("warn", "skip") for s in st):
        return "partly", got
    return "not met", got


# words in a requirement entry -> the edit type that delivers it (the planner writes "transition 分割" or "filter 青橙"
# for what code later realises with another working item of the same kind)
TYPE_WORDS = {
    "transition": "transition",
    "filter": "filter",
    "grade": "filter",
    "colour": "filter",
    "color": "filter",
    "look": "filter",
    "title": "text",
    "label": "text",
    "text": "text",
    "caption": "captions",
    "subtitle": "captions",
    "shake": "shake",
    "zoom": "zoom",
    "music": "audio",
    "sfx": "audio",
    "sound": "audio",
}


def ask_ids(entry, made, R):
    """Edit / clip ids that deliver one entry of a requirement's "edits" list: an id, a recipe name (or close to one),
    an item name, or a kind of edit ("transition ...", "filter ...")."""
    e = str(entry).strip()
    low = e.lower()
    edits = R.get("edits", [])
    if any(x["id"] == e for x in edits) or any(c["id"] == e for c in R.get("clips", [])):
        return [e]
    if made.get(e):
        return list(made[e])
    for k, v in made.items():  # "zoom punch" ~ zoom_punch, "transition 分割" ~ transitions, "grade recipe" ~ grade
        stem = k.lower().rstrip("s").replace("_", " ")
        if stem and (stem in low.replace("_", " ") or k.lower() in low):
            return list(v)
    by_item = [x["id"] for x in edits if x.get("item") and x["item"].split(":", 1)[1] in e]
    if by_item:
        return by_item
    kind = next((t for w, t in TYPE_WORDS.items() if re.search(rf"\b{w}", low)), None)
    if kind:
        return [x["id"] for x in edits if x["type"] == kind] or [e]
    return [e]


def assess(sess):
    R, M = sess.get("resolved", {}), sess.get("map", {})
    rep = sess.get("report") or {"results": [], "counts": {}}
    results = {r["id"]: r for r in rep.get("results", [])}
    think = (sess.get("plan") or {}).get("think") or {}
    # edits and clips, and checks of the whole edit that deliver an ask ("t1:speed" for slow motion, "template_match")
    present = {e["id"] for e in R.get("edits", [])} | {c["id"] for c in R.get("clips", [])} | set(results)
    score = []
    made = (sess.get("plan") or {}).get("_recipe_ids") or {}
    for q in think.get("requirements") or []:
        ids = [j for i in (q.get("edits") or []) if isinstance(i, str) for j in ask_ids(i, made, R)]
        st, got = _status([i for i in ids if i in present], results)
        if ids and not any(i in present for i in ids):
            st = "not met"
        score.append(
            {
                "ask": q.get("ask"),
                "how": q.get("how"),
                "status": st,
                "confidence": q.get("confidence"),
                "evidence": [f"{g['id']}: {g.get('why', '')[:90]}" for g in got][:3],
                "fallback": q.get("fallback"),
            }
        )
    subs = [
        n
        for n in R.get("notes", [])
        if any(
            w in n
            for w in (
                "VIP",
                "does not download",
                "account",
                "did not render",
                "using",
                "read as",
                "dropped",
                "skipped",
                "lowered",
                "shortened",
                "moved",
            )
        )
    ]
    # quality
    clips = R.get("clips", [])
    durs = [c["dur"] for c in clips]
    edits = R.get("edits", [])
    kinds = {}
    for e in edits:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    hook = any(
        e.get("window") and e["window"][0] < 1.5 and e["type"] in ("effect", "transition", "text", "zoom", "shake", "animation") for e in edits
    )
    loud = None
    ex = sess.get("export") or {}
    if ex.get("ok") and ex.get("path"):
        try:
            from ai_pc.media.audio import analyze as audio_analyze

            a = audio_analyze(ex["path"])
            loud = a and a.get("loudness_db")
        except Exception:  # noqa: BLE001
            loud = None
    quality = {
        "length_s": R.get("end"),
        "shots": len(clips),
        "avg_shot_s": round(sum(durs) / len(durs), 2) if durs else None,
        "hook": hook,
        "edits": kinds,
        "loudness_db": loud,
    }
    flaws = [f"{r['id']} ({r.get('type')}): {r.get('why', '')[:100]}" for r in rep.get("results", []) if r.get("status") in ("fail", "warn")]
    nxt = []
    aw = sess.get("awareness") or {}
    foot = aw.get("footage") or {}
    for q in score:
        if q["status"] in ("not met", "partly"):
            nxt.append(f"'{q['ask']}' is {q['status']}" + (f": next try {q['fallback']}" if q.get("fallback") else ""))
    for v in aw.get("needs", []):
        if v.get("vip_exact"):
            nxt.append(f"the exact look for '{v['what']}' exists: {v['vip_exact']} in JianYing (often free in CapCut)")
        if v.get("footage"):
            nxt.append(f"for '{v['what']}': {v['footage']} (a closer shot would make it stronger)")
    if foot and not foot.get("has_music") and "generated" not in str(((sess.get("plan") or {}).get("_rhythm") or {}).get("source")):
        nxt.append("add a music track to media/ for beat-synced cuts and a fuller sound")
    if loud is not None and loud < -20:
        nxt.append(f"the export is quiet ({loud} dB): raise music/sfx volume for social platforms")
    if any("never used here before" in i.get("issue", "") for i in (sess.get("critic") or {}).get("lint_before", [])):
        nxt.append("some items were used for the first time; their look is now recorded for next runs")
    seen, nxt2 = set(), []
    for x in nxt:
        if x not in seen:
            seen.add(x)
            nxt2.append(x)
    t = sess.get("timings", {})
    out = {
        "draft": M.get("draft"),
        "video": ex.get("path"),
        "scorecard": score,
        "substituted": subs,
        "quality": quality,
        "flaws": flaws,
        "next": nxt2[:6],
        "critic": {k: (sess.get("critic") or {}).get(k) for k in ("score", "verdict", "applied")},
        "checks": rep.get("counts"),
        "time_s": t.get("total_s"),
        "ai_usd": sess.get("ai_usd"),
        "edit_type": sess.get("edit_type"),
        "reference": (sess.get("reference") or {}).get("file"),
    }
    return out, markdown(out, think)


def markdown(a, think=None):
    L = [f"# Edit report: {a['draft']}", ""]
    if a.get("video"):
        L += [f"Video: `{a['video']}`", ""]
    et = a.get("edit_type") or {}
    if et:
        L += [f"**Edit type:** {et.get('label')} ({et.get('confidence', 0) * 100:.0f}% sure) - {'; '.join(et.get('reasons') or [])[:200]}  "]
    if a.get("reference"):
        L += [f"**Style matched to:** {a['reference']}  "]
    if et or a.get("reference"):
        L += [""]
    if think:
        L += [f"**Concept:** {think.get('concept', '')}  ", f"**Hook:** {think.get('hook', '')}  ", f"**Climax:** {think.get('climax', '')}", ""]
    L += ["## Asked vs delivered", "", "| Ask | How | Status | Evidence |", "|---|---|---|---|"]
    for q in a["scorecard"]:
        L.append(f"| {q['ask']} | {q.get('how') or ''} | **{q['status']}** | {'; '.join(q['evidence']) or '-'} |")
    if a["substituted"]:
        L += ["", "## What was done differently, and why", ""] + [f"- {s}" for s in a["substituted"]]
    q = a["quality"]
    L += [
        "",
        "## Quality",
        "",
        f"- {q['length_s']} s, {q['shots']} shots (avg {q['avg_shot_s']} s), hook in the first 1.5 s: {'yes' if q['hook'] else 'no'}",
        f"- edits: {', '.join(f'{k} {v}' for k, v in q['edits'].items())}",
    ]
    if q.get("loudness_db") is not None:
        L.append(f"- loudness {q['loudness_db']} dB")
    c = a.get("checks") or {}
    if c:
        L.append(f"- checks at the edit points: {c.get('pass', 0)} pass, {c.get('warn', 0)} warn, {c.get('fail', 0)} fail")
    cr = a.get("critic") or {}
    if cr.get("score") is not None:
        L.append(f"- critic before rendering: {cr['score']}/10" + (f"; fixed: {'; '.join(cr['applied'])}" if cr.get("applied") else ""))
    if a["flaws"]:
        L += ["", "## Still flagged", ""] + [f"- {f}" for f in a["flaws"]]
    if a["next"]:
        L += ["", "## Best next improvements", ""] + [f"{i + 1}. {x}" for i, x in enumerate(a["next"])]
    L += ["", f"_time {a.get('time_s')} s, AI ${a.get('ai_usd') or 0:.4f}_"]
    return "\n".join(L)


def save(a, md):
    REPORTS.mkdir(parents=True, exist_ok=True)
    p = REPORTS / f"{a['draft']}.md"
    p.write_text(md, encoding="utf-8")
    return p


def short(a):
    """A few lines for the console."""
    s = [
        "asked vs delivered: " + ", ".join(f"{q['ask'][:40]} = {q['status']}" for q in a["scorecard"])
        if a["scorecard"]
        else "asked vs delivered: (no requirement map)"
    ]
    if a.get("edit_type"):
        s.insert(0, f"edit type: {a['edit_type'].get('label')}" + (f"; style matched to {a['reference']}" if a.get("reference") else ""))
    if a["substituted"]:
        s.append("done differently: " + " | ".join(re.sub(r"^edit \S+: ", "", x)[:90] for x in a["substituted"][:4]))
    if a["next"]:
        s.append("next best improvement: " + a["next"][0])
    return "\n".join(s)
