"""Questions about what the editor can use, answered from the knowledge base in milliseconds (no video is built):
"what eye filters are available?", "do you have glitch transitions?", "show me elegant fonts", "which effect is best
for a boss entrance?", "what text animations do you have?".

Answered the way an editor would:
  - the right KIND of item: eye looks are character effects (a filter recolours the whole frame), a "typing effect" is a
    text animation, a "zoom in effect" is a clip animation or a keyframed move;
  - grouped by what can really be used here: ready (proven in exports / already downloaded), free but not used here
    yet, VIP-only (and whether CapCut has it free), not working here (does not download / needs an account / never
    rendered visibly);
  - with what each item does and what it suits, and a tip from the editing rules (a face effect needs a clear face...).
A recommendation question ("which is best for...") also gets a short pick from the model, grounded in these items.

  ask(question, planner=None) -> {"spec", "groups", "text", "seconds"}
"""
import re
import time

from . import jyres
from . import kb

# loose words a user says -> catalogue categories (first match wins; order = most specific first)
KIND_WORDS = [
    (r"\btext (?:animations?|effects?|intros?|outros?|loops?)\b|\btitle (?:animations?|effects?)\b|\btyp(?:ing|ewriter) effects?\b",
     ("text_intro", "text_outro", "text_loop"), "text animations"),
    (r"\b(?:clip|video|in|intro|entrance|out|outro|exit|entry) animations?\b|\banimations? for (?:clips?|videos?)\b",
     ("clip_intro", "clip_outro", "clip_combo"), "clip animations"),
    (r"\btransitions?\b", ("transition",), "transitions"),
    (r"\bfilters?\b|\bluts?\b|\bcolou?r (?:grades?|grading|looks?|presets?)\b|\bgrades?\b|\bpresets?\b", ("filter",), "filters"),
    (r"\bfonts?\b|\btypefaces?\b|\btypography\b|\blettering\b", ("font",), "fonts"),
    (r"\bmasks?\b", ("mask",), "masks"),
    (r"\bblend(?:ing)? modes?\b|\bblends?\b", ("blend",), "blend modes"),
    (r"\bvoice (?:changers?|effects?|filters?)\b|\bvoices?\b", ("voice",), "voice changers"),
    (r"\bsound effects?\b|\bsfx\b|\baudio effects?\b|\bsounds?\b", ("audio_effect",), "sound effects"),
    (r"\b(?:face|body|eye|eyes|character|person|people|head|hand) effects?\b", ("character_effect",), "face and body effects"),
    (r"\banimations?\b", ("clip_intro", "clip_outro", "clip_combo", "text_intro", "text_outro", "text_loop"), "animations"),
    (r"\beffects?\b|\bfx\b|\bvfx\b|\boverlays?\b|\bfilters? effects?\b", ("scene_effect", "character_effect"), "effects"),
]
UNSUPPORTED = {r"\bstickers?\b|\bemojis?\b|\bgifs?\b": "stickers", r"\btemplates?\b": "templates",
               r"\bmusic\b|\bsongs?\b|\btracks?\b": "a music library"}
TARGETS = {"eyes": r"\beyes?\b|\beyeball|\bpupils?\b", "face": r"\bfaces?\b|\bfacial\b", "head": r"\bheads?\b|\bhair\b",
           "hands": r"\bhands?\b", "body": r"\bbody\b|\bbodies\b|\bperson\b|\bpeople\b|\bsilhouettes?\b"}
STOP = set("""what which who how do does did can could would should is are am be been any some all the a an of for to in on at
with and or me my i you your we our it its this that these those there here available have has got show list tell give
find get want need using use used please hey hi ok okay like kind kinds type types sort sorts options option good best
nice cool really very more most lot lots also just only free premium vip pro working ready that's what's whats
effect effects filter filters transition transitions font fonts animation animations text title clip video videos
style styles look looks thing things something anything stuff which's ones one recommend recommended suggest
add put make apply insert there's lemme let see between clips clip scene scenes shot shots frame frames part parts
footage media moment moments edit edits editing""".split())
SHORT = {"text_intro": "text in", "text_outro": "text out", "text_loop": "text loop", "clip_intro": "clip in",
         "clip_outro": "clip out", "clip_combo": "clip combo", "scene_effect": "scene", "character_effect": "face/body"}
PURPOSE = re.compile(r"\bfor (?:a |an |the |my )?(.{3,60}?)(?:\?|$|\.|,)")
# an editor's thesaurus: what a purpose or mood means in visual words the catalogue descriptions use
INTENT_WORDS = {
    ("calm", "soft", "gentle", "elegant", "romantic", "wedding", "dreamy", "emotional", "love", "smooth", "classy", "luxury",
     "documentary", "nature", "relaxing", "peaceful", "slow"): "dissolve fade soft blend smooth glow light dreamy romantic warm elegant",
    ("hype", "energetic", "aggressive", "boss", "sport", "sports", "gym", "phonk", "action", "intense", "epic", "fast", "car",
     "drop", "powerful", "badass"): "flash zoom whip shake glitch impact punch spin fast energetic",
    ("funny", "meme", "cute", "kids", "playful", "comedy", "silly"): "bounce pop cartoon funny cute playful spin",
    ("tech", "modern", "app", "digital", "futuristic", "cyber", "gaming", "startup"): "glitch digital rgb tech slide clean cyber",
    ("retro", "vintage", "nostalgic", "old", "80s", "90s", "vhs"): "film retro vhs grain old vintage nostalgic",
    ("travel", "summer", "vlog", "fun", "upbeat", "party", "festival"): "zoom slide swipe warm bright fun party",
    ("superpower", "superpowers", "super power", "super powers", "superhero", "hero", "powers", "magic", "magical", "villain",
     "anime", "supernatural", "wizard", "god mode", "powerful eyes"): "laser lightning electric fire flame glow energy beam power",
    ("scary", "horror", "creepy", "demon", "evil", "halloween"): "scary horror dark red glow creepy ghost",
}
CONCEPT_STOP = {"many", "much", "number", "count", "total", "lot", "lots"}  # "how many": a count, not a look
GENRE_PHRASE = re.compile(r"\b(wedding|travel|short|documentary|music|nature|fashion|car|product|gym|cooking|food) (film|video|edit|reel|clip)s?\b")
RECOMMEND = re.compile(r"\b(?:best|recommend|suggest|should i|which one|what would you|ideal|perfect)\b")

QA_SYSTEM = """You are a senior video editor answering a client's question about the effects you can use. You get the
question and the candidate items (only these exist; READY ones work right now). Recommend 1-3 items by their exact name
(original name + English name), say why each fits in one short line, and how you would use it (timing, pairing, which
shot). Prefer READY items; mention a VIP or CapCut-only item only as "the exact look" if it is clearly better. Plain
text, at most 6 lines, no preamble."""


class Catalogue:
    """The JianYing catalogue + what works here + the CapCut catalogue (to tell which VIP items CapCut has free)."""
    _shared = None

    def __init__(self):
        self.jy = kb.Index("jianying")
        try:
            self.cc = kb.Index("capcut")
            self.cc_free = {(it["category"], it["name"]) for it in self.cc.items.values() if not it["pro"]}
        except Exception:  # noqa: BLE001  (the CapCut knowledge base is optional)
            self.cc, self.cc_free = None, set()
        self.record = jyres.load()

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def state(self, key):
        """ready | untried | vip | broken, and a short note."""
        it = self.jy.items[key]
        r = self.record.get(key, {})
        st = r.get("state")
        if it["pro"]:
            free_cc = (it["category"], it["name"]) in self.cc_free
            return "vip", "VIP-only in JianYing" + ("; free in CapCut" if free_cc else "")
        if st in ("missing", "login", "invisible"):
            return "broken", {"missing": "does not download here", "login": "needs a JianYing account",
                              "invisible": "did not render visibly in exports"}[st]
        seen, unseen = r.get("visible", 0), r.get("not_visible", 0)
        rare = f"; seen in {seen}/{seen + unseen} checks" if seen + unseen >= 4 and seen / (seen + unseen) < 0.5 else ""
        if st == "exported":
            return "ready", "proven in exports" + rare
        if st == "ok":
            return "ready", "downloaded, ready" + rare
        return "untried", "free, not used here yet"


def parse(question):
    """What the question asks for: kinds (categories), target body part, style words, purpose, flags."""
    q = " ".join(str(question).lower().replace("’", "'").split())
    q = GENRE_PHRASE.sub(r"\1", q)  # "a calm wedding film": the genre is wedding, "film" is not a look word
    spec = {"question": question, "kinds": [], "label": None, "target": None, "words": [], "purpose": None,
            "recommend": bool(RECOMMEND.search(q)), "unsupported": [], "notes": [], "intent_words": [], "concepts": [],
            "count": bool(re.search(r"\bhow many\b|\bnumber of\b|\bhow much\b", q)),
            "yesno": bool(re.search(r"\b(is there|are there|any|do you have|got any|can i)\b", q))}
    for keys, expand in INTENT_WORDS.items():
        hit = next((k for k in keys if re.search(rf"\b{re.escape(k)}\b", q)), None)
        if hit:
            spec["intent_words"] += expand.split()
            spec["concepts"].append(hit)
    for pat, cats, label in KIND_WORDS:
        if re.search(pat, q):
            spec["kinds"], spec["label"] = list(cats), label
            break
    for pat, what in UNSUPPORTED.items():
        if re.search(pat, q):
            spec["unsupported"].append(what)
    for part, pat in TARGETS.items():
        if re.search(pat, q):
            spec["target"] = part
            break
    if spec["target"] and (not spec["kinds"] or spec["kinds"] == ["filter"] or "scene_effect" in spec["kinds"]):
        # a look ON a body part is a character effect: a filter (or a scene effect) colours the whole frame
        if spec["kinds"] == ["filter"]:
            spec["notes"].append(f"{spec['target'].rstrip('s')} looks are face/body effects in this editor: a filter recolours "
                                 f"the whole frame, it cannot pick out the {spec['target']}")
        spec["kinds"], spec["label"] = ["character_effect"], f"{spec['target'].rstrip('s')} effects"
    m = PURPOSE.search(q)
    if m and not re.search(r"\b(?:effects?|filters?|transitions?|fonts?)\b", m.group(1)):
        spec["purpose"] = m.group(1).strip()
    words = [w for w in kb._toks(q) if w not in STOP and len(w) > 2 and not w.isdigit()]
    for pat in list(TARGETS.values()):
        words = [w for w in words if not re.fullmatch(pat.replace(r"\b", ""), w)]
    concept_toks = {t for c in spec["concepts"] for t in kb._toks(c)}
    spec["words"] = [w for w in dict.fromkeys(words) if w not in CONCEPT_STOP and w not in concept_toks][:8]
    return spec


def find(spec, cat=None, limit=40):
    """Candidate items for a parsed question, best first, each with its state."""
    cat = cat or Catalogue.shared()
    ix = cat.jy
    kinds = spec["kinds"] or ["scene_effect", "character_effect", "filter", "transition", "text_intro", "clip_intro"]
    # what it should feel like counts twice (the thesaurus words), the literal words once
    query = " ".join(spec.get("intent_words", []) * 2 + spec["words"] + ([spec["purpose"]] if spec["purpose"] else []))
    scored = {}
    if query:
        for h in ix.search(query, categories=kinds, free_only=False, k=200):
            scored[f"{h['category']}:{h['name']}"] = h["score"]
    if spec["target"]:  # everything aimed at that body part counts, matching words or not
        for k, it in ix.items.items():
            if it["category"] in kinds and spec["target"].rstrip("s") in str(ix.notes.get(k, {}).get("target", "")).lower():
                scored[k] = scored.get(k, 0.0) + 5.0
        if query:  # with style words AND a body part, keep what fits both
            tgt = [k for k in scored if spec["target"].rstrip("s") in str(ix.notes.get(k, {}).get("target", "")).lower()]
            scored = {k: v for k, v in scored.items() if k in tgt} or scored
    if not scored and not query.strip():  # no words, no body part ("what transitions do you have?"): the ones that work here first
        for k, it in ix.items.items():
            if it["category"] in kinds:
                st, _ = cat.state(k)
                scored[k] = {"ready": 3, "untried": 1, "vip": 0.5, "broken": 0}[st] + (0.5 if ix.notes.get(k) else 0)
    order = {"ready": 0, "untried": 1, "vip": 2, "broken": 3}
    out = []
    for k, s in scored.items():
        st, note = cat.state(k)
        n = ix.notes.get(k, {})
        out.append({"key": k, "name": ix.items[k]["name"], "en": n.get("en") or ix.items[k]["name"], "desc": n.get("desc") or "",
                    "category": ix.items[k]["category"], "target": n.get("target"), "use": n.get("use"), "mood": n.get("mood"),
                    "state": st, "note": note, "score": round(s, 2)})
    top = max((x["score"] for x in out), default=0)
    # what works here first among the relevant ones (half the best score or better), then by relevance
    out.sort(key=lambda x: (x["score"] < 0.5 * top, order[x["state"]], -x["score"]))
    return out[:limit]


def _line(it, mixed=False):
    use = it.get("use")
    use = ", ".join(use[:3]) if isinstance(use, list) else (use or "")
    desc = it["desc"].rstrip(".")
    kind = f"{SHORT.get(it['category'], it['category'])}: " if mixed else ""
    return f"  - {kind}{it['name']} ({it['en']}): {desc[:110]}" + (f" [{use}]" if use else "") + \
        (f" ({it['note']})" if it["state"] in ("ready", "vip", "broken") and it["note"] not in ("proven in exports", "downloaded, ready") else "")


TIPS = {
    "character_effect": "Face and body effects follow the person: they need a clear, reasonably large face or body in the shot "
                        "(I zoom in on the face when it is small, and check it is visible at the edit point).",
    "filter": "A filter is one colour look over a shot or the whole video; I keep one look per shot (stacking two grades "
              "crushes the picture) and lower the strength on footage that is already dark.",
    "transition": "Transitions sit on a cut; most edits use hard cuts on the beat and keep transitions for section changes, "
                  "at most ~20% of the shorter shot so the edit never looks like double exposures.",
    "font": "Fonts: one face for all labels and one for titles in a video; English text gets fonts drawn for Latin letters.",
    "text_intro": "Text animations play when a title appears (intro), loops while it stays, and outro when it leaves.",
    "scene_effect": "Scene effects cover the whole frame (flashes, glitches, light leaks, grain); quick hits go on beats, at "
                    "most one at a time, never as a strobe.",
}


def answer_text(spec, items, cat=None, limit=8):
    cat = cat or Catalogue.shared()
    kind = spec["label"] or "items"
    lines = []
    for n in spec["notes"]:
        lines.append(n[0].upper() + n[1:] + ".")
    for what in spec["unsupported"]:
        lines.append(f"There is no {what} support in this editor (pyJianYingDraft cannot place them); I can do it with "
                     f"text, effects or a sound effect instead.")
    if not items:
        lines.append(f"No {kind} match that. Try other words (e.g. glitch, warm, neon, zoom, elegant).")
        return "\n".join(lines)
    vocab = set(spec.get("intent_words") or [])

    def fits(it):  # does this item carry the asked-for idea ("superpowers" -> laser, lightning, fire, glow...)?
        text = " ".join([it["en"], it["desc"], " ".join(it.get("use") or []) if isinstance(it.get("use"), list) else str(it.get("use") or "")]).lower()
        return any(re.search(rf"\b{re.escape(w)}", text) for w in vocab)
    if vocab:
        items = sorted(items, key=lambda it: not fits(it))  # the ones with the idea first in every group (stable)
    groups = {"ready": [], "untried": [], "vip": [], "broken": []}
    for it in items:
        groups[it["state"]].append(it)
    what = f"{kind}" + (f" for the {spec['target']}" if spec["target"] and "effects" not in kind else "") + \
        (f" matching '{' '.join(spec['words'])}'" if spec["words"] else "")
    lines.append(f"{len(items)} {what} in the catalogue ({len(groups['ready'])} ready to use here, {len(groups['untried'])} free but not "
                 f"used here yet, {len(groups['vip'])} VIP-only, {len(groups['broken'])} not working here).")
    if spec.get("concepts"):  # answer the actual question first: is there a <concept> one I can use?
        idea = spec["concepts"][0]
        idea = idea[:-1] if idea.endswith("s") and len(idea) > 5 else idea  # "superpowers" -> "superpower-style"
        hit = [it for it in items if fits(it)]
        usable = [it for it in hit if it["state"] in ("ready", "untried")]
        vip = [it for it in hit if it["state"] == "vip"]
        if usable:
            lines.append(f"Yes, {idea}-style ones you can use now: " + "; ".join(f"{it['name']} ({it['en']})" + (" - ready" if it["state"] == "ready" else "")
                                                                      for it in usable[:4]) + ".")
        else:
            lines.append(f"No free {idea}-style {kind} works here yet.")
        if vip:
            cc = any("CapCut" in it["note"] for it in vip)
            lines.append(f"The classic {idea} looks ({', '.join(it['en'] for it in vip[:4])}) are VIP-only in JianYing"
                         + ("; free in CapCut" if cc else "") + ".")
        if spec["target"]:  # how an editor sells it: the body-part effect plus a full-frame one in the same spirit
            pair = [it for it in find({**spec, "target": None, "kinds": ["scene_effect"], "words": [], "intent_words": sorted(vocab)}, cat)
                    if it["state"] == "ready" and fits(it)][:2]
            if pair:
                lines.append(f"To sell it, I would pair it with {' or '.join(f'{it['name']} ({it['en']})' for it in pair)} around the "
                             f"person (ready), plus a quick zoom and an impact sound on the moment.")
    lines.append("All of them:" if spec.get("concepts") else "")
    titles = {"ready": "Ready to use", "untried": "Free, not used here yet (works in most cases; checked on first use)",
              "vip": "VIP-only in JianYing", "broken": "Not working here"}
    mixed = len({it["category"] for it in items}) > 1
    for g in ("ready", "untried", "vip", "broken"):
        if groups[g]:
            lines.append(f"{titles[g]}:")
            lines += [_line(it, mixed) for it in groups[g][:limit if g != "broken" else 3]]
            if len(groups[g]) > limit:
                lines.append(f"  ... and {len(groups[g]) - limit} more")
    cats = {it["category"] for it in items}
    tip = next((TIPS[c] for c in ("character_effect", "filter", "transition", "font", "text_intro", "scene_effect") if c in cats), None)
    if tip:
        lines.append("Tip: " + tip)
    return "\n".join(lines)


def ask(question, planner=None, limit=8):
    """Answer a question about available items. With a planner, a recommendation question gets a grounded pick."""
    t0 = time.perf_counter()
    cat = Catalogue.shared()
    spec = parse(question)
    if spec["unsupported"] and not spec["kinds"]:  # only about something this editor cannot place: the closest stand-ins
        spec["words"] = ["sticker"] if "stickers" in spec["unsupported"] else spec["words"][:1]
        spec["kinds"], spec["label"] = ["scene_effect", "character_effect"], "sticker-like effects"
    items = find(spec, cat)
    if spec["kinds"] == ["font"] and sum(ch.isascii() for ch in str(question)) >= 0.9 * max(1, len(str(question))):
        items.sort(key=lambda it: cat.jy.notes.get(it["key"], {}).get("script") != "latin")  # stable: Latin first per group
    text = answer_text(spec, items, cat, limit)
    pick = None
    if planner is not None and spec["recommend"] and items:
        # the recommender sees what works here (and at most two VIP items, as "the exact look" context only)
        pool = [it for it in items if it["state"] in ("ready", "untried")][:12] + [it for it in items if it["state"] == "vip"][:2]
        cards = "\n".join(f"{it['state'].upper()} {it['category']} {it['name']} ({it['en']}): {it['desc']} [use: {it.get('use')}; "
                          f"mood: {it.get('mood')}]" for it in pool)
        try:
            r = planner._call("fast", [{"role": "system", "content": QA_SYSTEM},
                                       {"role": "user", "content": f"QUESTION: {question}\n\nITEMS:\n{cards}"}])
            pick = r.text.strip()
            text += "\n\nMy pick:\n" + pick
        except Exception as e:  # noqa: BLE001  (the list above already answers the question)
            text += f"\n\n(no recommendation: {type(e).__name__})"
    return {"spec": spec, "items": items, "text": text, "pick": pick, "seconds": round(time.perf_counter() - t0, 3)}
