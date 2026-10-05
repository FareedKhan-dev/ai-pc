"""Questions about the edit being worked on, answered from its own record (no model call):
"what font did you use?", "what song is that?", "which transitions are in it?", "what's at 0:12?", "why did you add a
shake there?", "how many clips?", "what style is it?", "where's the title?".

Everything comes from the session: the resolved timeline (what is where), the design (why: concept, hook, climax, the
requirement map tying each client ask to the edits that deliver it), the checks (what was verified) and the edit type.
"""
import re

from .editplan import Catalog


def _t(x):
    m, s = divmod(max(0.0, float(x)), 60)
    return f"{int(m)}:{s:04.1f}"


def _name(key):
    if not key or ":" not in str(key):
        return str(key or "")
    cat = Catalog.shared()
    try:
        it = cat.item(key)
    except KeyError:
        return key.split(":", 1)[1]
    en = (cat.index.notes.get(key) or {}).get("en")
    return f"{it['name']} ({en})" if en and en != it["name"] else it["name"]


def _time_in(q):
    """A time the question points at ("0:12", "12s", "12 seconds", "at 12"), in seconds, or None."""
    m = re.search(r"\b(\d{1,2}):(\d{2})(?:\.\d+)?\b", q)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"\b(?:at|around|near)\s+(?:the\s+)?(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)?\b|\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)(?:\s+mark)?\b", q)
    if m:
        return float(m.group(1) or m.group(2))
    return None


def at_time(sess, t):
    R = sess["resolved"]
    clip = next((c for c in R["clips"] if c["start"] <= t < c["end"]), None)
    lines = []
    if clip:
        speed = clip["pieces"][0]["speed"] if clip.get("pieces") else 1
        lines.append(f"At {_t(t)}: shot {clip['id']} from {clip['file']} ({_t(clip['start'])}-{_t(clip['end'])}"
                     + (f", speed x{speed:g}" if speed != 1 else "") + ")")
    for e in R["edits"]:
        w = e.get("window")
        if not w or not (w[0] - 0.05 <= t <= w[1] + 0.05) or e["type"] == "audio" and not e.get("sfx"):
            continue
        what = {"text": lambda: f"text '{e.get('text', '')[:40]}'", "effect": lambda: f"effect {_name(e.get('item'))}",
                "filter": lambda: f"filter {_name(e.get('item'))}", "transition": lambda: f"transition {_name(e.get('item'))}",
                "zoom": lambda: f"zoom punch x{e.get('to')}", "shake": lambda: "camera shake",
                "keyframes": lambda: f"{e.get('property')} move", "animation": lambda: f"{e.get('kind')} animation {_name(e.get('item'))}",
                "audio": lambda: f"sound effect '{e.get('sfx')}'", "captions": lambda: "captions"}.get(e["type"])
        if what:
            lines.append(f"  - {what()} ({_t(w[0])}-{_t(w[1])})" + (f": {e['expect'][:80]}" if e.get("expect") else ""))
    return "\n".join(lines) or f"Nothing is placed at {_t(t)}."


def why(sess, q):
    """Why an edit is there: the client ask it serves (requirement map) and what it is meant to do."""
    R, d = sess["resolved"], sess.get("design") or sess.get("plan") or {}
    think = d.get("think") or {}
    t = _time_in(q)
    cands = []
    for e in R["edits"]:
        label = " ".join([e["type"], _name(e.get("item")), str(e.get("text") or ""), str(e.get("sfx") or ""), str(e.get("expect") or "")]).lower()
        qw = [re.sub(r"(?:es|s)$", "", w.replace("colour", "color")) for w in re.findall(r"[a-z]{4,}", q.lower())
              if w not in ("there", "that", "this", "with", "your", "added", "those", "these", "they", "them", "what", "does", "thing", "things")]
        hit = any(re.search(r"\b" + re.escape(w), label) for w in qw if len(w) >= 4 and w not in ("used", "using", "put", "add"))
        near = t is not None and e.get("window") and e["window"][0] - 0.3 <= t <= e["window"][1] + 0.3
        if hit or near:
            cands.append(e)
    if not cands:
        return None
    e = cands[0]
    reqs = [r for r in think.get("requirements") or [] if isinstance(r, dict) and
            any(str(x) in (e["id"], e.get("on")) or str(x).split()[0] in e["id"] for x in r.get("edits") or [])]
    out = [f"{_name(e.get('item')) or e['type']} at {_t(e['window'][0])}: {e.get('expect') or 'part of the style'}."]
    if reqs:
        out.append(f"It delivers your ask '{reqs[0].get('ask')}' ({reqs[0].get('how')}).")
    elif e["id"][:2] in ("zp", "sk", "fl", "rg", "tr", "kb", "gr", "tx", "lk"):
        out.append(f"It comes from the {sess.get('plan', {}).get('style', 'edit')} style's recipe "
                   f"({ {'zp': 'zoom punches on the beat', 'sk': 'shakes on hits', 'fl': 'flashes on the drop', 'rg': 'colour-split hits', 'tr': 'transitions', 'kb': 'slow push-ins', 'gr': 'the colour grade', 'tx': 'the texture', 'lk': 'light leaks'}[e['id'][:2]] }).")
    if think.get("concept"):
        out.append(f"The idea of the edit: {think['concept']}")
    return " ".join(out)


def why_subject(sess, q):
    """Why the look, the music, the pacing or the transitions are what they are: the designer's reasoning."""
    d = sess.get("design") or {}
    think = d.get("think") or (sess.get("plan") or {}).get("think") or {}
    rec = {r.get("use"): r for r in d.get("recipes") or [] if isinstance(r, dict)}
    et = (sess.get("edit_type") or {}).get("label")
    style = (sess.get("plan") or {}).get("style")
    if re.search(r"\b(look|colou?rs?|grade|grading|filter|tones?)\b", q):
        look = (rec.get("grade") or {}).get("look")
        return "The look: " + "; ".join(x for x in [f"chosen as '{look}'" if look else "", str(think.get("look") or ""),
                                                    f"it suits a {et.lower()}" if et else ""] if x) + "."
    if re.search(r"\b(music|song|beat|track|sound)\b", q):
        return "The music: " + "; ".join(x for x in [str(think.get("sound") or ""), f"the cut is timed to its beats, the drop is the climax"] if x) + "."
    if re.search(r"\b(pac(?:e|ing)|cuts?|fast|slow|rhythm)\b", q):
        return "The pacing: " + "; ".join(x for x in [str(think.get("pacing") or ""), f"the {style} style's rhythm" if style else ""] if x) + "."
    if re.search(r"\btransitions?\b", q):
        fam = (rec.get("transitions") or {}).get("family")
        return "The transitions: " + (f"{fam} transitions at the section changes, " if fam else "") + f"the {style} style's habit; hard cuts on the beat elsewhere."
    return None


def answer(question, sess):
    """Text answering a question about the session's edit, or None when the question is not about it."""
    q = " ".join(str(question).lower().split())
    R = sess["resolved"]
    edits = R["edits"]
    design = sess.get("design") or {}
    rhythm = (sess.get("plan") or {}).get("_rhythm") or {}
    tinfo = (sess.get("plan") or {}).get("_template") or {}
    if tinfo and re.search(r"\btemplates?\b", q) and not re.search(r"\b(?:any|other|others|else|more|available|suggest|recommend|do you have|list)\b", q):
        exact = tinfo.get("exact", True)
        return (f"This edit follows the template '{tinfo.get('name')}': {tinfo.get('slots')} slots "
                + ("on its exact cut frames" if exact else "made from its page (its clip count and length; the cuts are even beats)") +
                f", {R['end']:.1f} s" + (f", music at {rhythm.get('bpm'):.0f} BPM" if rhythm.get("bpm") else "") +
                (f". Its style: {tinfo['techniques']}" if tinfo.get("techniques") and tinfo["techniques"] != "no trend words" else "") +
                ". Footage, music, texts, colours, speed and format can change; its timing and pacing stay the template's.")
    if re.search(r"\bwhy\b", q):
        w = why_subject(sess, q) or why(sess, q)
        if w:
            return w
    m = re.search(r"\b(?:the )?(?:very )?(first|opening|last|final|closing|ending) (?:shot|clip|scene|frame|moment|thing|image|picture|seconds?)\b|"
                  r"\bwhat(?:'s| is) at the (start|beginning|end)\b|\bhow does it (start|open|begin|end|finish)\b|"
                  r"\bwhat (?:do )?(?:people|viewers|they) see (first|last)\b", q)
    if m and R["clips"]:
        first = next(g for g in m.groups() if g) in ("first", "opening", "start", "beginning", "open", "begin")
        c = R["clips"][0] if first else R["clips"][-1]
        return at_time(sess, c["start"] + 0.05 if first else max(c["start"], R["end"] - 0.3))
    m = re.search(r"\bhow many (flash|shake|zoom|transition|effect|text|title|label|step|shot|clip|cut|sound|whoosh|filter)", q)
    if m:
        k = m.group(1)
        if k in ("shot", "clip", "cut"):
            n = len(R["clips"])
            return f"{n} shots in {R['end']:.1f} s (one every {R['end'] / max(1, n):.1f} s on average)."
        if k in ("text", "title", "label", "step"):
            tx = [e for e in edits if e["type"] == "text"]
            return f"{len(tx)} texts: " + "; ".join(f"'{e['text'][:20]}'" for e in tx[:10]) + "."
        if k in ("sound", "whoosh"):
            sf = [e for e in edits if e.get("sfx")]
            return f"{len(sf)} sound effects" + (": " + ", ".join(f"{s_} x{sum(1 for e in sf if e['sfx'] == s_)}" for s_ in sorted({e['sfx'] for e in sf})) if sf else "") + "."
        if k in ("transition", "filter"):
            n = sum(1 for e in edits if e["type"] == k)
            return f"{n} {k}{'s' if n != 1 else ''}."
        words = {"flash": ("flash", "strobe"), "shake": ("shake",), "zoom": ("zoom",), "effect": ("",)}[k]
        hits = [e for e in edits if (e["type"] == k) or (e["type"] == "effect" and any(w in (_name(e.get("item")) + " " + str(e.get("expect") or "")).lower() for w in words))]
        return f"{len(hits)} {k}{'es' if k == 'flash' and len(hits) != 1 else 's' if len(hits) != 1 else ''}" + \
            (f" (at {', '.join(_t(e['window'][0]) for e in hits[:6])}{'...' if len(hits) > 6 else ''})" if hits else "") + "."
    if re.search(r"\b(narration|narrator|voice ?over|what (?:does|did) (?:he|she|the narrator|the voice) say|what is said|what'?s said)\b", q):
        caps = [e for e in edits if e["type"] == "captions"]
        lines = [str(x.get("text") or "") for c in caps for x in c.get("lines") or []]
        if not lines:
            return "There is no narration or speech in this edit."
        txt = " ".join(lines)
        return f"The narration ({len(lines)} subtitle lines): \"{txt[:260]}{'...' if len(txt) > 260 else ''}\""
    t = _time_in(q)
    if t is not None and re.search(r"\b(what|which|happens|going on|at|there)\b", q):
        return at_time(sess, t)
    cmp_ = re.search(r"\b(?:under|over|less than|more than|longer than|shorter than|within|below|above)\s+(?:a |an |one )?(\d+(?:\.\d+)?|minute|min)\s*(s|sec|secs|seconds?|m|mins?|minutes?)?\b", q)
    if cmp_ and re.search(r"\b(?:is|will|does|would)\b", q) and not re.search(r"\b(transition|title|text|label|shot|clip)s?\b", q):
        lim = 60.0 if cmp_.group(1).startswith("min") else float(cmp_.group(1)) * (60 if (cmp_.group(2) or "").startswith("m") else 1)
        under = R["end"] <= lim
        return f"It is {R['end']:.1f} s: {'under' if under else 'over'} {lim:.0f} s" + ("" if under else f" (by {R['end'] - lim:.1f} s; say 'cut it to {lim:.0f} s' to fit)") + "."
    if re.search(r"\bhow long\b|\b(length|duration|runtime)\b|\bhow many seconds\b", q) and not re.search(r"\b(transition|title|text|label|shot|clip)s?\b", q):
        n = len(R["clips"])
        return f"{R['end']:.1f} s, {n} shots (one every {R['end'] / max(1, n):.1f} s on average)."
    if re.search(r"\b(aspect|format|resolution|ratio|vertical|horizontal|landscape|portrait|square)\b", q):
        w, h = R["canvas"]
        return f"{w}x{h} ({'vertical 9:16' if h > w * 1.5 else 'horizontal 16:9' if w > h * 1.5 else 'square' if w == h else '4:5'})" + \
            (f", made for {R.get('platform')}" if R.get("platform") else "") + "."
    if re.search(r"\b(drop|climax|peak|best part|highlight)\b", q) and re.search(r"\b(when|where|what|which)\b", q):
        drop = rhythm.get("drop")
        if drop is None:
            return "This edit has no music drop; its high point is " + (f"at {_t(R['end'] * 0.6)}." if R["clips"] else "not set.")
        return f"The drop hits at {_t(drop)}.\n" + at_time(sess, drop + 0.05)
    if re.search(r"\bcolou?rs?\b", q) and re.search(r"\b(title|text|label|caption|words|font)s?\b", q):
        tx = [e for e in edits if e["type"] == "text"]
        if not tx:
            return "There is no text in this edit."
        by = {}
        for e in tx:
            by.setdefault(e["style"]["color"], []).append(f"'{e['text'][:20]}'")
        return "Text colours: " + "; ".join(f"{c}: {', '.join(v[:4])}" for c, v in by.items()) + "."
    if re.search(r"\bfonts?\b|\btypeface", q):
        by = {}
        for e in edits:
            if e["type"] in ("text", "captions") and (e.get("style") or {}).get("font"):
                role = "captions" if e["type"] == "captions" else "labels" if str(e["id"]).startswith("lb") or e["style"]["size"] <= 11 else "titles"
                by.setdefault(role, set()).add(_name(e["style"]["font"]))
        return ("Fonts: " + "; ".join(f"{r}: {', '.join(sorted(v))}" for r, v in by.items())) if by else "No text uses a special font (JianYing's default)."
    if re.search(r"\b(music|song|soundtrack|beat|bpm|track|audio)\b", q):
        m = next((e for e in edits if e["id"] == "music" or (e["type"] == "audio" and not e.get("sfx") and e.get("id") != "vo")), None)
        sfx = sorted({e.get("sfx") for e in edits if e.get("sfx")})
        if not m:
            return "There is no music in this edit." + (f" Sound effects: {', '.join(sfx)}." if sfx else "")
        gen = str(m.get("file", "")).startswith("music_")
        src = (f"a generated {m['file'].split('_')[1]} bed at {rhythm.get('bpm')} BPM, made for this edit (its drop sits at "
               f"{_t(rhythm.get('drop') or 0)}, where the cut's climax is)") if gen else f"your file {m.get('file')}"
        return f"Music: {src}, volume {m.get('volume', 1):.2f}." + (f" Sound effects: {', '.join(sfx)}." if sfx else "")
    if re.search(r"\btransitions?\b", q):
        tr = [e for e in edits if e["type"] == "transition"]
        if not tr:
            return "Only hard cuts: no transitions."
        names = {}
        for e in tr:
            names.setdefault(_name(e["item"]), []).append(_t(e["window"][0]))
        return f"{len(tr)} transitions: " + "; ".join(f"{n} x{len(ts)} (at {', '.join(ts[:4])}{'...' if len(ts) > 4 else ''})" for n, ts in names.items())
    if re.search(r"\b(filter|grade|grading|colou?r|look|lut)\b", q):
        fl = [e for e in edits if e["type"] == "filter"]
        dim = any(c["id"] == "lk_dim" for c in R.get("layers", []))
        parts = [f"{_name(e['item'])} ({_t(e['window'][0])}-{_t(e['window'][1])})" for e in fl]
        return ("Colour: " + ("; ".join(parts) if parts else "no filter") + (" + exposure matched to your sample with a dimming layer" if dim else "")
                + (f". Look in words: {design.get('recipes') and next((r.get('look') for r in design['recipes'] if r.get('use') == 'grade'), '') or ''}" if design else ""))
    if re.search(r"\b(effects?|fx|vfx)\b", q):
        fx = [e for e in edits if e["type"] == "effect"]
        if not fx:
            return "No catalogue effects (only cuts, moves and text)."
        names = {}
        for e in fx:
            names.setdefault(_name(e["item"]), []).append(_t(e["window"][0]))
        moves = sum(1 for e in edits if e["type"] in ("zoom", "shake"))
        return f"{len(fx)} effects: " + "; ".join(f"{n} x{len(ts)}" for n, ts in names.items()) + (f". Plus {moves} zoom punches/shakes." if moves else "")
    if re.search(r"\bthe title\b|\btitle say\b", q) and not re.search(r"\b(titles|font|colou?r|size)\b", q) and sess.get("plan"):
        from .quick_edits import pick_texts
        ids = {e.get("id") for e in pick_texts(sess["plan"], {"role": "title"})}
        main = [e for e in edits if e["type"] == "text" and e["id"] in ids]
        others = [e for e in edits if e["type"] == "text" and e["id"] not in ids]
        if main:
            return (f"The title is '{main[0]['text'].replace(chr(10), ' ')}' (at {_t(main[0]['window'][0])})" +
                    (f"; other texts: " + "; ".join(f"'{e['text'][:24]}' at {_t(e['window'][0])}" for e in others[:6]) if others else "") + ".")
    if re.search(r"\b(titles?|texts?|labels?|captions?|words|says?)\b", q):
        tx = [e for e in edits if e["type"] == "text"]
        caps = [e for e in edits if e["type"] == "captions"]
        out = [f"'{e['text'][:40]}' at {_t(e['window'][0])}" for e in tx[:12]]
        return ("Texts: " + "; ".join(out) if out else "No titles.") + (f" Plus captions ({sum(len(c.get('lines', [])) for c in caps)} lines)." if caps else "")
    if re.search(r"\b(how many|number of)\b.*\b(clips?|shots?|cuts?)\b|\b(clips?|shots?|cuts?)\b.*\bhow many\b", q):
        n = len(R["clips"])
        return f"{n} shots in {R['end']:.1f} s (one every {R['end'] / max(1, n):.1f} s on average), from {len({c['file'] for c in R['clips']})} files."
    if re.search(r"\b(style|vibe|type of (?:edit|video)|kind of (?:edit|video)|concept|idea)\b", q):
        et = sess.get("edit_type") or {}
        think = design.get("think") or {}
        return (f"{et.get('label', 'Edit')} in the {sess.get('plan', {}).get('style', '?')} style"
                + (f", matched to your sample {sess['reference']['file']}" if sess.get("reference") else "")
                + (f". Concept: {think.get('concept')}" if think.get("concept") else "")
                + (f". Hook: {think.get('hook')}" if think.get("hook") else "")
                + (f". Climax: {think.get('climax')}" if think.get("climax") else ""))
    return None
