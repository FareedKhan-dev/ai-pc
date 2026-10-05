"""The front door: what does the user want from this message?

  catalog     "what eye filters are available?", "do you have glitch transitions?", "show me elegant fonts"
  capability  "can you remove the green screen?", "is it possible to add stickers?", "how would you do a speed ramp?"
  classify    "what kind of video should this be?" (with files): the edit type and why
  style       "what style is this edit?" / "analyse this sample" (with a video): its measured style
  edit        a new edit (files given), optionally "like <sample>" to match a sample's style
  revise      a follow-up on the last edit ("make the lightning stronger")
  help        "what can you do?"

Rules decide in microseconds; only an unclear message goes to the cheap model (one short JSON call). answer() runs
the questions (catalog / capability / classify / style / help) and returns text; edit and revise are run by the studio.
"""
import json
import re

from ai_pc.core.util import parse_json
from ai_pc.video import awareness
from ai_pc.video import catalog_qa as CQ
from ai_pc.video import taxonomy as TX

Q_START = re.compile(r"^(what|which|who|how|do|does|did|can|could|is|are|any|show|list|tell|give|got|have|where|why|whats|what's|"
                     r"is there|are there)\b")
EDIT_VERBS = re.compile(r"\b(edit|make|create|cut|turn|put together|produce|build|montage|reel|compile|stitch)\b")
REVISE = re.compile(r"\b(make it|change|more|less|add|remove|replace|instead|stronger|weaker|faster|slower|swap|move|shorter|longer|"
                    r"louder|quieter|bigger|smaller|again|redo|fix)\b")
CAPABILITY = re.compile(r"\b(can you|could you|are you able|is it possible|possible to|do you support|can i|could i|"
                        r"how (?:do|would|can|could|should) (?:i|you|we))\b")
CLASSIFY = re.compile(r"\b(what (?:kind|type|sort) of (?:video|edit)|which (?:kind|type) of (?:video|edit)|classify|categori[sz]e|"
                      r"what (?:should|would) (?:this|it) be|what genre)\b")
STYLE_Q = re.compile(r"\b(what style|which style|analy[sz]e (?:this|the|my) (?:edit|video|sample|reference)|style of (?:this|the)|"
                     r"how (?:is|was) (?:this|it) edited|study this)\b")
HELP = re.compile(r"\b(what can you do|help|what do you (?:do|support)|your (?:features|capabilities)|features)\b")
LIKE = re.compile(r"\b(?:like|same (?:style|vibe) as|in the style of|similar to|match(?:ing)?)\s+(?:this|that|the|my)?\s*"
                  r"([\w\-. ]+\.(?:mp4|mov|mkv|webm|m4v))", re.I)

ROUTE_SYSTEM = """Classify a message to a video-editing assistant. Reply with ONE JSON object:
{"intent": "catalog|capability|classify|style|edit|revise|help", "why": "<few words>"}
catalog = asks which effects/filters/transitions/fonts/animations/sounds exist; capability = asks whether or how something
can be done; classify = asks what kind of video the footage/request is; style = asks to analyse an edited video's style;
edit = wants a new video made; revise = wants the last video changed; help = asks what the assistant can do."""

BUILT_IN = {  # what this editor does with its own tools (no catalogue item needed), and the words that ask for it
    r"\bshak(?:e|y|ing)\b": "camera shake (position keyframes, any strength, on beats or hits)",
    r"\bzoom|punch(?:-| )?in\b": "zoom punches and slow push-ins (scale keyframes, timed to beats)",
    r"\bslow(?:-| )?mo|slow motion|speed ramp|velocity\b": "slow motion and speed ramps (fast-slow-fast on the key moment)",
    r"\bfreeze\b": "freeze frames", r"\brevers": "reverse playback",
    r"\bgreen ?screen|chroma|blue screen\b": "green/blue screen removal (with a clean background behind it)",
    r"\bcaption|subtitle\b": "captions from speech (local Whisper) or from given text, styled and timed",
    r"\bvoice ?over|narrat": "voiceover: narration with subtitles and the music ducked under it",
    r"\bbeat|sync\b": "cuts on the music's beats (given music or a generated bed)",
    r"\bmusic|soundtrack\b": "generated music beds (hype, phonk, epic, pop, chill, cinematic) or the music you give",
    r"\bsound effects?|sfx|whoosh|impact|riser\b": "synthesised sound effects: impact, hit, whoosh, swoosh, riser, sub drop, thunder, glitch",
    r"\breframe|vertical|9:16|crop\b": "reframing for 9:16 / 16:9 / 1:1 that keeps faces in view",
    r"\bjump cuts?|pauses|silence\b": "jump cuts that remove pauses and filler words from speech",
    r"\bmask\b": "shape masks", r"\bblend\b": "blend modes", r"\blabels?|titles?|text\b": "titles, labels and kinetic text",
    r"\blike this|same style|reference|sample\b": "matching the style of a sample edit you give (rhythm, moves, look, text)",
}
NOT_POSSIBLE = {
    r"\bstickers?|emojis?|gifs?\b": "stickers: the draft format here cannot place them; I use text, effects or sound instead",
    r"\b4k|60 ?fps|120 ?fps\b": "4K / 60 fps: exports here are 1080p at 30 fps",
    r"\bmusic library|popular songs?|trending (?:song|audio)|spotify\b": "a music library: I generate a bed or use the music you give",
    r"\bvip|premium|pro effects?\b": "VIP items: they need a JianYing membership to export; I pick free look-alikes",
    r"\bface ?swap|deepfake\b": "face swapping: not offered",
}


def route(message, files=(), last_draft=None, planner=None):
    """{"intent", "why", "references", "request"} for a message (files: media given with it)."""
    m = " ".join(str(message).lower().split())
    refs = [x.strip() for x in LIKE.findall(str(message))]
    q = m.endswith("?") or bool(Q_START.match(m))
    spec = CQ.parse(m)
    if CLASSIFY.search(m):
        return {"intent": "classify", "why": "asks what kind of video", "references": refs}
    if STYLE_Q.search(m) and (files or refs):
        return {"intent": "style", "why": "asks for a video's style", "references": refs}
    if HELP.search(m) and not spec["kinds"]:
        return {"intent": "help", "why": "asks what the assistant can do", "references": refs}
    if q and CAPABILITY.search(m) and not (files and EDIT_VERBS.search(m)):
        return {"intent": "capability", "why": "asks whether / how something can be done", "references": refs}
    if q and (spec["kinds"] or spec["unsupported"]) and not files:
        return {"intent": "catalog", "why": f"asks about {spec['label'] or 'items'}", "references": refs}
    if files:
        return {"intent": "edit", "why": "media given", "references": refs}
    if last_draft and REVISE.search(m) and not q:
        return {"intent": "revise", "why": "a change to the last edit", "references": refs}
    if planner is not None:  # unclear: one short call to the cheap model
        try:
            r = planner._call("fast", [{"role": "system", "content": ROUTE_SYSTEM}, {"role": "user", "content": message}])
            d = parse_json(r.text) or {}
            if d.get("intent") in ("catalog", "capability", "classify", "style", "edit", "revise", "help"):
                return {"intent": d["intent"], "why": f"model: {d.get('why', '')}", "references": refs}
        except Exception:  # noqa: BLE001
            pass
    return {"intent": "catalog" if q and spec["words"] else "help", "why": "fallback", "references": refs}


def capability(message, planner=None):
    """Can it be done, how (built-in technique or catalogue items), and what is not possible (with the alternative)."""
    m = " ".join(str(message).lower().split())
    lines, yes = [], []
    for pat, how in BUILT_IN.items():
        if re.search(pat, m):
            yes.append(how)
    nope = [why for pat, why in NOT_POSSIBLE.items() if re.search(pat, m)]
    spec = CQ.parse(m)
    if nope:
        lines.append("Not possible here: " + "; ".join(nope) + ".")
    if yes:
        lines.append("Yes, built in: " + "; ".join(dict.fromkeys(yes)) + ".")
    looks = [w for w in spec["words"] if not any(re.search(p, w) for p in list(BUILT_IN) + list(NOT_POSSIBLE))]
    items = []
    if spec["target"] or (spec["kinds"] and looks) or (looks and not yes and not nope):
        spec = {**spec, "words": looks}
        found = CQ.find(spec)

        def name(it):
            return f"{it['name']} ({it['en']})" + (" - ready" if it["state"] == "ready" else "")

        def fits(it):
            return not looks or any(w in f"{it['en']} {it['desc']}".lower() for w in looks)
        usable = [it for it in found if it["state"] in ("ready", "untried")]
        exact = [it for it in usable if fits(it)]
        vip = [it for it in found if it["state"] == "vip" and fits(it)]
        moods = {u for it in vip for u in (it.get("use") if isinstance(it.get("use"), list) else [])}
        # closest stand-ins: what is ready first, then what shares the exact look's purpose (cool, impact...)
        usable.sort(key=lambda it: (it["state"] != "ready", -len(moods & set(it.get("use") if isinstance(it.get("use"), list) else []))))
        support = []
        if spec["target"] and looks:  # e.g. lightning on the eyes: a full-frame lightning around the person helps
            support = [it for it in CQ.find({**spec, "target": None, "kinds": ["scene_effect"]}) if it["state"] in ("ready", "untried") and fits(it)][:2]
        if exact:
            items = exact
            lines.append("Yes: " + "; ".join(name(it) for it in exact[:4]) + ".")
        else:
            if vip:
                cc = any("CapCut" in it["note"] for it in vip)
                lines.append(f"The exact look ({', '.join(it['en'] for it in vip[:3])}) is VIP-only in JianYing" + ("; free in CapCut" if cc else "") + ".")
            alt = usable[:2] + support
            items = alt
            if alt:
                lines.append("Closest that works here: " + "; ".join(name(it) for it in alt) +
                             (" (a face effect on the " + spec["target"] + " plus a full-frame one around the person)" if support and spec["target"] else "") + ".")
    if not (yes or nope or items):
        lines.append("I could not match that to a technique or a catalogue item; describe the look you want (e.g. 'lightning "
                     "around the eyes', 'a glitch between clips') and I will check.")
    return "\n".join(lines)


def help_text():
    groups = {}
    for t, p in TX.TYPES.items():
        groups.setdefault(p["style"], []).append(p["label"])
    return "\n".join([
        "I edit videos from plain requests: give me clips (and optionally a sample edit to match) and say what you want.",
        f"I recognise {len(TX.TYPES)} kinds of edit and edit each the way it is done professionally, e.g. "
        + ", ".join(p["label"] for p in list(TX.TYPES.values())[:8]) + ", and more.",
        "Built in: " + "; ".join(list(dict.fromkeys(BUILT_IN.values()))[:9]) + ".",
        "Catalogue: ~1,000 filters, ~1,100 scene effects, 240 face/body effects, ~450 transitions, ~500 animations, ~800 fonts "
        "(free ones usable; I know which work here).",
        "Ask me things like: 'what eye effects do you have?', 'do you have glitch transitions?', 'what kind of video are these "
        "clips?', 'make it like sample.mp4'.",
        "Limits: " + "; ".join(awareness.LIMITS[:4]) + "."])


def answer(message, files=(), planner=None, last_draft=None, log=print):
    """Answer a question-type message. Returns (intent, text). Edits and revisions are for the studio to run."""
    r = route(message, files, last_draft, planner)
    it = r["intent"]
    if it == "catalog":
        return it, CQ.ask(message, planner)["text"]
    if it == "capability":
        return it, capability(message, planner)
    if it == "help":
        return it, help_text()
    if it == "classify":
        from ai_pc.video import analyze as AN
        an = AN.analyze(list(files), planner=planner, log=log) if files else {}
        c = TX.classify(message, an)
        alts = ", ".join(f"{TX.TYPES[t]['label']} {p * 100:.0f}%" for t, p in c["alternatives"])
        return it, (f"{c['label']} ({c['confidence'] * 100:.0f}% sure" + (f"; also possible: {alts}" if alts else "") + ")\n"
                    f"Why: {'; '.join(c['reasons']) or 'general signals'}\n\nHow I would edit it:\n" + TX.design_block(c))
    if it == "style":
        from ai_pc.video import reference as RF
        target = (list(files) + r["references"])[:1]
        if not target:
            return it, "Give me the video to analyse."
        fp = RF.fingerprint(target[0], planner, log)
        return it, RF.describe(fp, RF.profile(fp))
    return it, json.dumps(r)
