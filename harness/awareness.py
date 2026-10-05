"""Runtime awareness: what this agent can and cannot do RIGHT NOW for a request, before anything is planned.

For every need of the brief it decides: direct (a fitting item exists and works here), approximate (only a look-alike;
the exact look is VIP-only, missing or for another body part), built-in (one of our own techniques: shake, zoom, speed
ramp, freeze, reverse, reframing, chroma, sound effects...), or not possible (and what to do instead). It reads the
footage for what each idea needs (a clear face for eye effects, sound for ducking, music for beat cuts), knows how
reliable each catalogue item is here (proven in exports / downloaded / never tried / broken) and lists the hard limits.

The planner gets this as its "what is possible" sheet, the critic checks against it, and the final report explains
every substitution with it. Pure computation: ~10-50 ms.
"""
from . import sfx

LIMITS = [
    "free catalogue items only (VIP items need a JianYing membership to export)",
    "exports are 1080p at 30 fps",
    "clip scale tops out at 500% (zoom punches get headroom automatically)",
    "no stickers, text bubbles or fancy-text presets",
    "speech-to-text is local Whisper (base): good for clear speech, weaker on music or heavy accents",
    f"no music library: music only from audio files given; sound effects are synthesised ({', '.join(sfx.KINDS)})",
    "CapCut-only catalogue items cannot render in JianYing",
]
TECHNIQUES = {
    "shake": "camera shake (position keyframes, any strength)", "zoom": "zoom punch or slow push (scale keyframes)",
    "slow": "slow motion / speed ramp (split clip)", "ramp": "speed ramp", "freeze": "freeze frame", "reverse": "reverse playback",
    "reframe": "reframing on the subject (face tracking)", "chroma": "green/blue screen removal", "green screen": "green screen removal",
    "mask": "shape masks", "blend": "blend modes", "beat": "cuts snapped to music beats (needs a music file)",
    "duck": "music ducking under speech", "sound": "synthesised sound effects", "sfx": "synthesised sound effects",
    "whoosh": "synthesised whoosh", "impact": "synthesised impact", "riser": "synthesised riser", "flash": "white flash (transition 闪白 or effect)",
    "text": "titles with fonts and animations", "title": "titles", "caption": "captions from given text",
}
PARTS = ("eyes", "face", "head", "body", "hands")


def footage(analyses):
    """What the footage offers the plan: clear faces and when, sound, music, green screens."""
    files, best_face, has_music, has_speech, screens = [], 0.0, False, False, []
    for a in analyses.values():
        k = a.get("kind")
        snd = a.get("sound") or {}
        if k == "audio":
            has_music |= snd.get("kind") in ("music", "mixed/ambient")
            files.append({"file": a["file"], "kind": "audio", "sound": snd.get("kind"), "bpm": snd.get("bpm")})
            continue
        faces = [x for x in a.get("faces", []) if x["faces"]]
        sizes = [f["faces"][0]["box"][2] * f["faces"][0]["box"][3] for f in faces]
        big = [x["t"] for x in faces if x["faces"][0]["box"][2] * x["faces"][0]["box"][3] >= 0.015 and x["faces"][0]["score"] > 0.75]
        clear = []
        for t in big:  # time ranges with a clear face
            if clear and t - clear[-1][1] <= 0.6:
                clear[-1][1] = t
            else:
                clear.append([t, t])
        top = max(sizes, default=0.0)
        best_face = max(best_face, top)
        has_speech |= snd.get("kind") == "speech"
        if a.get("screen"):
            screens.append(a["file"])
        files.append({"file": a["file"], "kind": k, "seconds": a.get("seconds"), "face_max": round(top, 4),
                      "clear_face": [[round(x, 1), round(y + 0.25, 1)] for x, y in clear][:6], "sound": snd.get("kind"),
                      "screen": (a.get("screen") or {}).get("kind")})
    return {"files": files, "best_face": round(best_face, 4), "has_music": has_music, "has_speech": has_speech, "screens": screens}


def _state(cat, key):
    f = cat.boost.get(key)
    return "proven" if f and f > 1.3 else "downloaded" if f else "untried"


def feasibility(brief, groups, cat, foot):
    """One verdict per need of the brief."""
    out = []
    by_need = {}
    for title, cards in groups.items():
        nid = title.split(":")[0].strip()
        by_need[nid] = cards
    ix = cat.index
    for n in (brief.get("needs") or [])[:20]:
        nid, what = str(n.get("id", "?")), str(n.get("what", ""))
        part = str(n.get("target") or "none").lower()
        kinds = [k for k in (n.get("kinds") or [])]
        v = {"need": nid, "what": what, "target": part}
        if not kinds:
            hit = next((d for k, d in TECHNIQUES.items() if k in what.lower()), None)
            v.update(status="built-in", how=hit or "built-in technique", reliability="proven")
            if "beat" in what.lower() and not foot["has_music"]:
                v.update(status="not possible", how="no music file to take beats from", instead="cut on visual hits; add sound effects")
        else:
            cards = by_need.get(nid, [])
            if not cards:
                v.update(status="not possible", how="no free item matches", instead="a built-in technique or a different look")
            else:
                best = cards[0]
                key = f"{best['category']}:{best['name']}"
                matches_part = part not in PARTS or best.get("target") == part
                v.update(status="direct" if matches_part else "approximate", how=f"{best.get('en')} ({best['name']})",
                         reliability=_state(cat, key), options=[f"{c.get('en')} ({c['name']}, {_state(cat, c['category'] + ':' + c['name'])})"
                                                                 for c in cards[:4]])
                # is the exact look only available as VIP?
                q = f"{n.get('query') or ''} {what}"
                pro = [h for h in ix.search(q, categories=kinds, free_only=False, k=3) if h.get("pro")]
                free_top = (ix.search(q, categories=kinds, k=1, exclude=cat.missing) or [{"score": 0}])[0]["score"]
                if pro and pro[0]["score"] > 1.25 * free_top:
                    v["vip_exact"] = f"{pro[0].get('en')} ({pro[0]['name']}) is VIP-only"
                    v["status"] = "approximate"
        if part in ("eyes", "face", "head"):
            if foot["best_face"] < 0.006:
                v["footage"] = "no clear face in the footage: face/eye effects will barely show; use a broader effect"
                v["status"] = "approximate" if v.get("status") == "direct" else v.get("status")
            elif foot["best_face"] < 0.02:
                v["footage"] = "faces are small: pair the effect with a zoom on the face"
        out.append(v)
    return out


COLOURS = ("red", "white", "black", "blue", "green", "yellow", "orange", "silver", "grey", "gray", "pink", "purple", "gold",
           "golden", "brown", "beige")
_STOP = {"a", "an", "the", "and", "with", "in", "on", "of", "for", "to", "at", "my", "our", "your", "its"}


def off_brief(request, analyses):
    """Files that show a different version of the thing the request is about: "an ad for the red sports car" and a
    file captioned "a luxury white sports car". {file: why}. Only colour + thing, which captions state reliably."""
    import re
    req = str(request or "").lower()
    out = {}
    for m in re.finditer(r"\b(" + "|".join(COLOURS) + r")\s+([a-z][a-z\s-]{2,40})", req):
        colour = m.group(1)
        words = [w for w in re.split(r"[\s-]+", re.split(r"[,.:;!?]", m.group(2))[0]) if w and w not in _STOP][:3]
        if not words:
            continue
        thing = words[-1]  # the head noun: "sports car" -> car
        for a in analyses.values():
            if a.get("kind") not in ("video", "image"):
                continue
            text = " ".join([a.get("file", "").replace("-", " ").replace("_", " "), str(a.get("summary") or "")] +
                            [str(x.get("subject") or "") for x in a.get("moments", [])]).lower()
            if not re.search(rf"\b{thing}s?\b", text) or re.search(rf"\b{colour}\b(\s+[a-z-]+){{0,3}}\s+{thing}", text):
                continue
            other = next((c for c in COLOURS if c != colour and re.search(rf"\b{c}\b(\s+[a-z-]+){{0,3}}\s+{thing}", text)), None)
            if other:
                out[a["file"]] = f"shows a {other} {thing}; the request is about the {colour} {' '.join(words)}"
    vids = [a for a in analyses.values() if a.get("kind") in ("video", "image")]
    return out if len(vids) - len(out) >= 2 else {}  # never leave the edit without footage


def snapshot(brief, analyses, groups, cat, lessons_text="", request=""):
    """(structured awareness, the text block the planner and critic read)."""
    foot = footage(analyses)
    feas = feasibility(brief, groups, cat, foot)
    off = off_brief(request, analyses)
    lines = ["RUNTIME AWARENESS (what is possible here, now):", "footage:"]
    for f, why in off.items():
        lines.append(f"  OFF-BRIEF, do not use: {f} ({why})")
    for f in foot["files"]:
        if f["kind"] == "audio":
            lines.append(f"  {f['file']}: audio ({f.get('sound')}{', ' + str(f['bpm']) + ' BPM' if f.get('bpm') else ''})")
            continue
        face = (f"clear face at {', '.join(f'{a}-{b} s' for a, b in f['clear_face'])} (up to {f['face_max'] * 100:.1f}% of the frame)"
                if f["clear_face"] else f"no clear face (largest {f['face_max'] * 100:.2f}% of the frame)")
        lines.append(f"  {f['file']}: {face}; sound: {f.get('sound') or 'none'}" + (f"; {f['screen']} screen" if f.get("screen") else ""))
    lines.append(f"  music file: {'yes' if foot['has_music'] else 'NO (use synthesised sound effects for impact and rhythm)'}"
                 f"; speech in the clips: {'yes' if foot['has_speech'] else 'no'}")
    lines.append("needs:")
    for v in feas:
        s = f"  {v['need']} {v['what']} -> {v['status'].upper()}: {v.get('how', '')}"
        if v.get("reliability"):
            s += f" [{v['reliability']}]"
        if v.get("vip_exact"):
            s += f"; the exact look {v['vip_exact']}"
        if v.get("footage"):
            s += f"; {v['footage']}"
        if v.get("instead"):
            s += f"; instead: {v['instead']}"
        lines.append(s)
    lines.append("limits: " + "; ".join(LIMITS))
    if lessons_text:
        lines.append(lessons_text)
    return {"footage": foot, "needs": feas, "limits": LIMITS, "off_brief": off}, "\n".join(lines)
