"""Knowledge base of everything the video engine can do.

Items: every catalogue entry of the engine (pyJianYingDraft for JianYing 5.9; pyCapCut for CapCut is the same code with
engine="capcut") - filters, transitions, scene effects, face/body-tracked character effects, clip in/out/combo
animations, text in/out/loop animations, fonts, masks, blend modes, audio scene effects, voice changers, speech-to-song -
with the engine's own facts (Pro flag, ids, tunable parameters and their ranges, default durations) plus an English name,
a description and search tags written by a model (the catalogue itself only has Chinese names).

Search: BM25 over English text, tags (with synonyms) and the original name, filtered by category and Pro flag. The
planner gets the top candidates WITH descriptions and picks from them, so it can never invent an item.

Files (all inside the project): kb/<engine>/items.json (facts), kb/<engine>/notes.json (descriptions, resumable),
kb/<engine>/params.json (what each tunable parameter does).
"""
import json
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import ROOT

KB = ROOT / "kb"

# category key -> (enum name in the engine, what it is / where it goes)
CATEGORIES = {
    "filter":           ("FilterType", "colour grade / look applied to one clip or, on a filter track, to everything below it"),
    "transition":       ("TransitionType", "transition between two neighbouring clips on the main video track"),
    "scene_effect":     ("VideoSceneEffectType", "full-frame visual effect on a clip, or on an effect track over a time range"),
    "character_effect": ("VideoCharacterEffectType", "effect that tracks a person (face, eyes, body, hands) in a clip"),
    "clip_intro":       ("IntroType", "how a video clip enters (plays at the clip's start)"),
    "clip_outro":       ("OutroType", "how a video clip leaves (plays at the clip's end)"),
    "clip_combo":       ("GroupAnimationType", "animation that runs over a whole video clip (in + out together)"),
    "text_intro":       ("TextIntro", "how a text enters"),
    "text_outro":       ("TextOutro", "how a text leaves"),
    "text_loop":        ("TextLoopAnim", "looping animation while a text is on screen"),
    "font":             ("FontType", "font for titles and subtitles"),
    "mask":             ("MaskType", "shape mask that cuts a video clip"),
    "blend":            ("MixModeType", "blend mode of a video clip over the tracks below it"),
    "audio_effect":     ("AudioSceneEffectType", "sound effect / processing applied to an audio clip"),
    "voice":            ("ToneEffectType", "voice changer for speech in an audio clip"),
    "speech_to_song":   ("SpeechToSongType", "turns speech into a sung melody in a style"),
}
# what the model must add per category, besides en / desc / tags / conf
EXTRA = {
    "filter": '"look": "<colours, contrast, grain, era; <=10 words>", "mood": "<1-3 words>"',
    "transition": '"motion": "<e.g. zoom in, slide left, spin, glitch, dissolve, flash, wipe; <=6 words>"',
    "scene_effect": '"target": "frame|edges|background|overlay", "moves_image": <true ONLY if it shakes, zooms, rotates or warps the whole picture like a camera move; false for overlays>, "use": ["intro|outro|impact|beat|transition|ambient|highlight|retro|glitch|light|weather|party|romantic|scary|funny|dramatic"]',
    "character_effect": '"target": "face|eyes|head|body|hands|outline|around person", "moves_image": <true ONLY if it shakes, zooms or warps the whole picture; false for overlays on the person>, "use": ["intro|impact|beat|highlight|funny|cute|cool|scary|romantic|dramatic|beauty"]',
    "clip_intro": '"motion": "<fade|slide|zoom|spin|bounce|shake|flip|blur|glitch|wipe|... and direction; <=6 words>"',
    "clip_outro": '"motion": "<fade|slide|zoom|spin|bounce|shake|flip|blur|glitch|wipe|... and direction; <=6 words>"',
    "clip_combo": '"motion": "<what the clip does over its whole length; <=8 words>"',
    "text_intro": '"motion": "<typewriter|fade|slide|pop|bounce|zoom|blur|glitch|... ; <=6 words>"',
    "text_outro": '"motion": "<fade|slide|pop|blur|dissolve|... ; <=6 words>"',
    "text_loop": '"motion": "<what the text does repeatedly; <=6 words>"',
    "font": '"style": "<sans|serif|script|handwritten|display|pixel|brush|rounded|condensed|calligraphy|... >", "script": "latin|chinese|both|other", "weight": "light|regular|bold|heavy"',
    "audio_effect": '"sound": "<what it sounds like; <=10 words>"',
    "voice": '"sound": "<what the voice sounds like; <=10 words>"',
    "speech_to_song": '"sound": "<music style; <=8 words>"',
}
# small, fixed sets: described by hand (exact)
HAND = {
    "mask": {"线性": ("Linear", "straight-line split: one side visible, the other hidden", "linear split half line divide"),
             "镜面": ("Mirror strip", "band between two parallel lines stays visible", "mirror band strip letterbox stripe"),
             "圆形": ("Circle", "circle or ellipse window", "circle round oval ellipse spotlight vignette"),
             "矩形": ("Rectangle", "rectangle window, corners can be rounded", "rectangle box frame rounded square window pip"),
             "爱心": ("Heart", "heart-shaped window", "heart love romantic shape"),
             "星形": ("Star", "star-shaped window", "star shape sparkle")},
    "blend": {"正片叠底": ("Multiply", "darkens: multiplies colours with the layers below", "multiply darken shadow"),
              "颜色减淡": ("Color dodge", "brightens strongly where the layer is light", "color dodge brighten glow"),
              "颜色加深": ("Color burn", "darkens strongly with more contrast", "color burn darken contrast"),
              "线性加深": ("Linear burn", "darkens by subtracting brightness", "linear burn darken"),
              "柔光": ("Soft light", "gentle contrast/light overlay", "soft light overlay gentle"),
              "强光": ("Hard light", "strong contrast overlay", "hard light contrast overlay"),
              "滤色": ("Screen", "brightens: black disappears, light parts show (good for light leaks, fire, sparks on black)", "screen lighten remove black light leak overlay"),
              "叠加": ("Overlay", "contrast overlay: darks darker, lights lighter", "overlay contrast"),
              "变亮": ("Lighten", "keeps the lighter pixel of the two layers", "lighten brighter"),
              "变暗": ("Darken", "keeps the darker pixel of the two layers", "darken darker")},
}


def _engine_module(engine):
    if engine == "jianying":
        import pyJianYingDraft as m
    else:
        import pycapcut as m
    return m


def extract(engine="jianying"):
    """Facts for every catalogue item, straight from the engine's metadata."""
    m = _engine_module(engine)
    items = []
    for cat, (enum_name, _) in CATEGORIES.items():
        enum = getattr(m, enum_name, None)
        if enum is None:
            continue
        for member in enum:
            v = member.value
            it = {"key": f"{cat}:{member.name}", "category": cat, "name": member.name,
                  "pro": bool(getattr(v, "is_vip", False)),
                  "resource_id": getattr(v, "resource_id", None), "effect_id": getattr(v, "effect_id", None),
                  "md5": getattr(v, "md5", None)}
            if getattr(v, "params", None):
                it["params"] = [{"name": p.name, "min": p.min_value, "max": p.max_value, "default": p.default_value} for p in v.params]
            if getattr(v, "duration", None):
                it["default_duration_s"] = round(v.duration / 1e6, 2)
            if getattr(v, "default_duration", None):
                it["default_duration_s"] = round(v.default_duration / 1e6, 2)
            if hasattr(v, "is_overlap"):
                it["overlaps_clips"] = bool(v.is_overlap)
            if getattr(v, "resource_type", None):
                it["shape"] = v.resource_type
            items.append(it)
    d = KB / engine
    d.mkdir(parents=True, exist_ok=True)
    (d / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=0), encoding="utf-8")
    return items


# ---------------------------------------------------------------------------------------------------- annotation
NOTE_SYSTEM = """You annotate the catalogue of a video editor (JianYing / CapCut). Item names are mostly Chinese; some are English, Korean or brand-like.
For each item, infer from the name (and the category) what it looks or sounds like. Be concrete and visual. If a name is not self-explanatory (a number, year, brand, place or unclear word), give your best guess and set conf to "medium" or "low"; use "high" only when the name clearly says what it is.
Reply with ONE JSON object: {"items": [ {"i": <index>, "en": "<short English name>", "desc": "<what it does / looks like, <=20 words>", "tags": ["<6-12 lowercase search words incl. synonyms>"], "conf": "high|medium|low", <EXTRA>} ... ]}
Include every index exactly once. No other text."""


def _notes_path(engine):
    return KB / engine / "notes.json"


def load_notes(engine="jianying"):
    p = _notes_path(engine)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _annotate_batch(planner, cat, batch, tier):
    from .util import parse_json
    lines = "\n".join(f"{i}. {it['name']}" + (f"  [params: {', '.join(p['name'].replace('effects_adjust_', '') for p in it.get('params', []))}]" if it.get("params") else "")
                      for i, it in enumerate(batch))
    system = NOTE_SYSTEM.replace("<EXTRA>", EXTRA.get(cat, ""))
    user = f"CATEGORY: {cat} - {CATEGORIES[cat][1]}\nITEMS:\n{lines}\n\nReply with the JSON object only."
    r = planner._call(tier, [{"role": "system", "content": system}, {"role": "user", "content": user}])
    d = parse_json(r.text) or {}
    out = {}
    for row in d.get("items") or []:
        try:
            idx = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(batch) and row.get("en") and row.get("desc"):
            row.pop("i", None)
            out[batch[idx]["key"]] = row
    return out


def annotate(engine="jianying", tier="annotate", batch_size=40, workers=8, categories=None, limit=None, log=print):
    """Describe every item that has no description yet (resumable: saved after every batch)."""
    from .planner import ChatPlanner
    items_path = KB / engine / "items.json"
    items = json.loads(items_path.read_text(encoding="utf-8")) if items_path.exists() else extract(engine)
    notes = load_notes(engine)
    for cat, table in HAND.items():  # hand-written, exact
        for name, (en, desc, tags) in table.items():
            notes[f"{cat}:{name}"] = {"en": en, "desc": desc, "tags": tags.split(), "conf": "high", "by": "hand"}
    todo = [it for it in items if it["key"] not in notes and (not categories or it["category"] in categories)]
    if limit:
        todo = todo[:limit]
    batches = []
    for cat in dict.fromkeys(it["category"] for it in todo):
        group = [it for it in todo if it["category"] == cat]
        batches += [(cat, group[i:i + batch_size]) for i in range(0, len(group), batch_size)]
    log(f"{len(todo)} items to describe in {len(batches)} batches ({workers} at a time)")
    planner, t0, done = ChatPlanner(), time.perf_counter(), 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_annotate_batch, planner, cat, b, tier): (cat, b) for cat, b in batches}
        for f in as_completed(futs):
            cat, b = futs[f]
            try:
                got = f.result()
            except Exception as e:  # noqa: BLE001  (a failed batch is retried on the next run)
                log(f"  batch failed ({cat}): {type(e).__name__}: {str(e)[:80]}")
                continue
            for k, v in got.items():
                v["by"] = "name"
                notes[k] = v
            done += len(got)
            _notes_path(engine).write_text(json.dumps(notes, ensure_ascii=False, indent=0), encoding="utf-8")
            log(f"  {cat}: +{len(got)}/{len(b)}  (total {done}/{len(todo)}, {time.perf_counter() - t0:.0f} s)")
    return notes


PARAM_SYSTEM = """You explain the tunable parameters of a video editor's effects. Parameter names look like effects_adjust_speed or change_voice_param_pitch_shift. Values are numbers from min to max (usually 0 to 1).
Reply with ONE JSON object mapping each parameter name to a short English explanation of what increasing it does (<=12 words). No other text."""


def describe_params(engine="jianying", tier="annotate"):
    from .planner import ChatPlanner
    from .util import parse_json
    items = json.loads((KB / engine / "items.json").read_text(encoding="utf-8"))
    names = sorted({p["name"] for it in items for p in it.get("params", [])})
    r = ChatPlanner()._call(tier, [{"role": "system", "content": PARAM_SYSTEM}, {"role": "user", "content": "\n".join(names)}])
    d = parse_json(r.text) or {}
    out = {n: d.get(n, n.replace("effects_adjust_", "").replace("change_voice_param_", "").replace("_", " ")) for n in names}
    (KB / engine / "params.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


API_SYSTEM = """You document the Python API of a video-editing engine (pyJianYingDraft, which writes JianYing/CapCut projects) for an AI planner that will use it.
For each entry (signature + original documentation, often Chinese), write precise English. Reply with ONE JSON object:
{"entries": [{"name": "<as given>", "what": "<what it does, 1-2 sentences>", "args": {"<arg>": "<meaning, units, range, default>"}, "rules": ["<constraints, side effects, gotchas>"]}]}
Times are in microseconds unless strings like "1.5s" are accepted. Keep every entry; no other text."""


def describe_api(engine="jianying", tier="annotate", chunk=24, log=print):
    """English capability manifest of the engine's API (kb/<engine>/capabilities.json)."""
    from .planner import ChatPlanner
    from .util import parse_json
    raw = json.loads((KB / engine / "api_raw.json").read_text(encoding="utf-8"))
    planner = ChatPlanner()
    parts = [raw[i:i + chunk] for i in range(0, len(raw), chunk)]

    def one(part):
        r = planner._call(tier, [{"role": "system", "content": API_SYSTEM},
                                 {"role": "user", "content": json.dumps(part, ensure_ascii=False)}])
        return (parse_json(r.text) or {}).get("entries") or []
    entries = []
    with ThreadPoolExecutor(max_workers=len(parts)) as ex:
        for got in ex.map(one, parts):
            entries += got
    by = {e.get("name"): e for e in entries if isinstance(e, dict)}
    out = []
    for x in raw:
        e = by.get(x["name"], {})
        out.append({"name": x["name"], "kind": x["kind"], "signature": x.get("signature"), "values": x.get("values"),
                    "what": e.get("what", ""), "args": e.get("args", {}), "rules": e.get("rules", [])})
    (KB / engine / "capabilities.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"described {sum(1 for o in out if o['what'])} of {len(out)} API entries")
    return out


# ---------------------------------------------------------------------------------------------------- search
_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]")


def _toks(text):
    t = _TOKEN.findall(str(text).lower())
    cjk = [c for c in t if "一" <= c <= "鿿"]
    return t + [a + b for a, b in zip(cjk, cjk[1:])]  # Chinese: single characters + character pairs


class Index:
    """BM25 over each item's English name, description, tags, extra fields and original name."""

    FIELD_WEIGHT = {"en": 3, "tags": 2, "name": 2, "desc": 1, "extra": 1}

    def __init__(self, engine="jianying"):
        d = KB / engine
        self.items = {it["key"]: it for it in json.loads((d / "items.json").read_text(encoding="utf-8"))}
        self.notes = load_notes(engine)
        p = d / "params.json"
        self.params = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        self.docs, self.df = {}, Counter()
        for k, it in self.items.items():
            n = self.notes.get(k, {})
            extra = " ".join(str(v) for kk, v in n.items() if kk not in ("en", "desc", "tags", "conf", "by"))
            tf = Counter()
            for field, text in (("en", n.get("en", "")), ("tags", " ".join(n.get("tags", []))), ("name", it["name"]),
                                ("desc", n.get("desc", "")), ("extra", extra)):
                for tok in _toks(text):
                    tf[tok] += self.FIELD_WEIGHT[field]
            self.docs[k] = tf
            self.df.update(tf.keys())
        self.n = len(self.docs)
        self.avg = sum(sum(t.values()) for t in self.docs.values()) / max(1, self.n)

    def search(self, query, categories=None, free_only=True, k=8, exclude=None, boost=None):
        """Top-k cards. exclude: keys never returned (e.g. known not to download); boost: {key: factor} (e.g. items
        already downloaded rank a little higher)."""
        q = _toks(query)
        scores = []
        for key, tf in self.docs.items():
            it = self.items[key]
            if categories and it["category"] not in categories:
                continue
            if free_only and it["pro"]:
                continue
            if exclude and key in exclude:
                continue
            dl = sum(tf.values())
            s = 0.0
            for tok in q:
                if tok in tf:
                    idf = math.log(1 + (self.n - self.df[tok] + 0.5) / (self.df[tok] + 0.5))
                    s += idf * tf[tok] * 2.2 / (tf[tok] + 1.2 * (0.25 + 0.75 * dl / self.avg))
            if s > 0:
                scores.append((s * (boost.get(key, 1.0) if boost else 1.0), key))
        scores.sort(reverse=True)
        return [self.card(key, score) for score, key in scores[:k]]

    def card(self, key, score=None):
        """What the planner sees for one item."""
        it, n = self.items[key], self.notes.get(key, {})
        c = {"category": it["category"], "name": it["name"], "en": n.get("en"), "desc": n.get("desc")}
        for f in ("target", "moves_image", "use", "look", "mood", "motion", "style", "script", "weight", "sound"):
            if f in n:
                c[f] = n[f]
        if it.get("params"):  # the engine takes every parameter as 0-100 (mapped onto the item's own range)
            c["params"] = {p["name"]: f"{self.params.get(p['name'], p['name'])} (0-100, default "
                           f"{round(100 * (p['default'] - p['min']) / ((p['max'] - p['min']) or 1))})" for p in it["params"]}
        if it.get("default_duration_s"):
            c["default_duration_s"] = it["default_duration_s"]
        if it["pro"]:
            c["pro"] = True
        if score is not None:
            c["score"] = round(score, 2)
        return c
