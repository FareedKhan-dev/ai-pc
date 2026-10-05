"""Recipes: the patterns professional editors repeat, compiled into precisely timed edits (plan schema v2).

A model is good at choosing a style, the shots and which patterns to use; it is bad at writing forty keyframes on the
right beats. So the planner names recipes and this module writes the edits:

  zoom_punch   punch-in zooms on beats / downbeats / the drop (optionally with a quick motion blur)
  shake        camera shake on downbeats or hits          flash   white flash on the drop or chosen beats
  rgb_hit      chromatic-aberration hit on beats           transitions  a transition family at section changes / every N cuts
  ken_burns    slow push-in / pull-out across shots       grade   one colour look over everything (+ grain, vignette,
  hook         a hook text in the first 1.5 s                     letterbox, light leaks)
  kinetic_title  a title word by word on the beat, the last word slammed (accent colour, shake, flash, hit sound)
  captions     caption lines in a style (bold_pop / minimal)
  sfx          whooshes on transitions, hits on words, riser + impact into the drop (when the music has none)
  jump_zoom    talking heads: every other cut zoomed in, so jump cuts feel intentional
  face_punch   meme zoom onto a face with a boom
compose(plan) turns a planner's style + shots + recipes (+ hand-placed extras) into a full plan: beat-exact cuts
(cutting.py), a generated music bed when no music was given (music.py), and every recipe's edits.
"""

import json
import re

from ai_pc.media import music as MU
from ai_pc.video import analyze as AN
from ai_pc.video import cutting
from ai_pc.video.styles import STYLES, guess

# picked by recipes on their own (no one asked for a particular one): only items known to download and export here
SAFE_PICKS = {"font", "text_intro", "text_outro", "text_loop", "filter", "transition"}
ROOT_DERIVED = MU.OUT  # media/derived: files this agent makes (music beds, the dimming layer...)
SECTIONS = ("intro", "verse", "build", "drop", "break", "outro")
LOOK_WORDS = r"\b(warm|golden|cool|teal|orange|dark|moody|bright|vivid|pastel|black and white|b&w|vintage|retro|neon|grade|grading|colou?r|look)\b"
MUSIC_WORDS = r"\b(music|song|beat|bpm|phonk|pop|lofi|lo-fi|house|edm|trap|piano|epic|chill|soundtrack)\b"
SECTION_ALIASES = {
    "hook": "intro",
    "opening": "intro",
    "opener": "intro",
    "climax": "drop",
    "chorus": "drop",
    "peak": "drop",
    "hero": "drop",
    "finale": "outro",
    "ending": "outro",
    "end": "outro",
    "credits": "outro",
    "bridge": "break",
    "breakdown": "break",
    "pause": "break",
    "buildup": "build",
    "build-up": "build",
    "pre-drop": "build",
    "rise": "build",
    "middle": "verse",
    "body": "verse",
    "main": "verse",
    "story": "verse",
}
EXPLORE = 2  # untried items a video may try (a failure costs one re-export; a success joins the palette for good)
# themed looks: never chosen on their own unless the request is about that theme (a heart-and-"Love" vignette was
# once picked for "vignette" in a football reel)
THEMES = {
    "heart",
    "love",
    "romantic",
    "valentine",
    "wedding",
    "christmas",
    "xmas",
    "birthday",
    "halloween",
    "new year",
    "lunar",
    "festival",
    "cartoon",
    "cute",
    "kawaii",
    "baby",
    "anime",
    "santa",
    "snowman",
    "pumpkin",
    "graduation",
}


def _desc(cat, key):
    n = cat.index.notes.get(key, {})
    return " ".join(
        [
            str(n.get("en") or ""),
            str(n.get("desc") or ""),
            " ".join(map(str, n.get("tags") or [])),
            str(n.get("mood") or ""),
            str(n.get("look") or ""),
        ]
    ).lower()


def _themes(cat, key):
    n = cat.index.notes.get(key, {})
    text = " ".join([str(n.get("en") or ""), str(n.get("desc") or ""), " ".join(map(str, n.get("tags") or [])), str(n.get("mood") or "")]).lower()
    return {t for t in THEMES if t in text}


class Ctx:
    def __init__(self, timeline, beats, downbeats, drop, sections, style, cat, total):
        self.tl, self.beats, self.down, self.drop, self.sections = timeline, beats, downbeats, drop, sections
        self.style, self.cat, self.total = style, cat, total
        self.beat = (beats[1] - beats[0]) if len(beats) > 1 else 0.5
        self.n, self._picks, self.explored = 0, {}, 0
        self.keep = set()  # items the edit already uses (a recompose after a follow-up keeps them unless asked)

    def id(self, prefix):
        self.n += 1
        return f"{prefix}{self.n}"

    def pick(self, cats, query, plain=False, avoid=()):
        """The catalogue item for a phrase: what fits the phrase, works here and was not used in the last videos;
        up to EXPLORE untried items per video (one that fails costs a re-export, one that works widens every later
        video's palette). Fonts are never explored here (most untried ones are CJK faces or do not download).
        plain=True (layers over the whole video: grain, vignette, bars): the most generic fitting item, never rotated.
        Themed items (hearts, Christmas, birthday...) are only picked when the request is about that theme."""
        k = (tuple(cats), query, plain, tuple(avoid))
        if k not in self._picks:
            # relevance first (works here x fits the phrase); freshness only chooses among items that fit about as well:
            # a fresher item that does something else (a film-strip frame for "grain") is not variety, it is a mistake
            hits = self.cat.index.search(query, categories=list(cats), k=16, exclude=self.cat.missing, boost=self.cat.boost)
            req = getattr(self, "request", "")
            hits = [h for h in hits if not (_themes(self.cat, f"{h['category']}:{h['name']}") - {t for t in THEMES if t in req})] or hits
            if avoid:  # e.g. a soft / bright look: no filter whose own description is dark or moody
                hits = [h for h in hits if not any(w in _desc(self.cat, f"{h['category']}:{h['name']}") for w in avoid)] or hits
            top = hits[0]["score"] if hits else 0

            def key(h):
                return f"{h['category']}:{h['name']}"

            if self.keep:  # a follow-up changes what was asked, not the rest: what this edit already uses and still fits stays
                wide = self.cat.index.search(query, categories=list(cats), k=80, exclude=self.cat.missing, boost=self.cat.boost)
                pool = [key(h) for h in wide if h["score"] >= 0.2 * (wide[0]["score"] if wide else 0)]
                if "font" in cats:
                    pool += self.cat.known_like(query, ["font"])
                taken = {v for v in self._picks.values()}
                kept = [k2 for k2 in pool if k2 in self.keep]
                kept = next((k2 for k2 in kept if self.cat.item(k2)["name"] not in taken), kept[0] if kept else None)
                if kept:
                    self._picks[k] = self.cat.item(kept)["name"]
                    return self._picks[k]

            def fresh(hs, share):
                if plain:
                    return hs
                near = [h for h in hs if h["score"] >= share * (hs[0]["score"] if hs else 0)]
                return sorted(near, key=lambda h: -h["score"] * self.cat.recent.get(key(h), 1.0)) + [h for h in hs if h not in near]

            known = fresh([h for h in hits if self.cat.boost.get(key(h), 1) >= 1.1 and h["score"] >= 0.45 * top], 0.75)
            new = fresh([h for h in hits if key(h) not in self.cat.boost and h["score"] >= 0.7 * top], 0.75)
            if "font" in cats and getattr(self, "latin", False):  # English words: a face designed for Latin letters first
                pool = self.cat.known_like(query, ["font"])
                pool.sort(key=lambda k2: self.cat.index.notes.get(k2, {}).get("script") != "latin")
                known = [{"name": self.cat.item(k2)["name"]} for k2 in pool[:1]] or known
            choice = None
            if new and self.explored < EXPLORE and "font" not in cats and (not known or new[0]["score"] > known[0]["score"]):
                choice = new[0]  # fits clearly better than anything known (or nothing known fits): try it
                self.explored += 1
            elif known:
                choice = known[0]
            elif set(cats) & SAFE_PICKS:  # a look that is known to work here, even if it fits the phrase less
                alt = self.cat.known_like(query, list(cats))
                choice = {"name": self.cat.item(alt[0])["name"]} if alt else (hits[0] if hits else None)
            else:
                choice = hits[0] if hits else None
            self._picks[k] = (choice or {"name": None})["name"]
        return self._picks[k]

    def clip_at(self, t, margin=0.12):
        for c in self.tl:
            if c["start"] - 1e-6 <= t < c["end"] - margin:
                return c
        return None

    def in_sections(self, t, sections):
        if not sections:
            return True
        return any(s["name"] in sections and s["start"] - 1e-6 <= t < s["end"] for s in self.sections)

    def times(self, on="beats", every=1, sections=None):
        if on == "drop":
            return [self.drop] if self.drop is not None else []
        if on == "cuts":
            src = [c["start"] for c in self.tl[1:]]
        elif on == "downbeats":
            src = self.down
        else:
            src = self.beats
        src = [t for t in src if self.in_sections(t, sections) and t < self.total - 0.2]
        every = max(1, int(every or 1))
        return src[::every]


# ------------------------------------------------------------------------------------------------ recipes
def r_zoom_punch(x, r):
    out = []
    for t in x.times(r.get("on", "beats"), r.get("every", 1), r.get("sections")):
        c = x.clip_at(t)
        if not c:
            continue
        dur = round(min(0.45, x.beat * 0.85), 3)
        out.append(
            {
                "id": x.id("zp"),
                "type": "zoom",
                "on": c["id"],
                "start": round(t - c["start"], 3),
                "duration": dur,
                "to": float(r.get("strength", 1.14)),
                "back": True,
                "expect": "a punch-in zoom on the beat",
            }
        )
        if r.get("blur"):
            out.append(
                {
                    "id": x.id("bl"),
                    "type": "effect",
                    "name": x.pick(["scene_effect"], "motion blur radial zoom blur"),
                    "start": round(t, 3),
                    "duration": 0.15,
                    "layer": "accent",
                    "expect": "a quick motion blur with the punch",
                }
            )
    return out


def r_shake(x, r):
    out = []
    for t in x.times(r.get("on", "downbeats"), r.get("every", 1), r.get("sections")):
        c = x.clip_at(t)
        if c:
            out.append(
                {
                    "id": x.id("sk"),
                    "type": "shake",
                    "on": c["id"],
                    "start": round(t - c["start"], 3),
                    "duration": round(min(0.4, x.beat), 3),
                    "strength": float(r.get("strength", 0.5)),
                    "expect": "the picture shakes on the hit",
                }
            )
    return out


FLASH_GAP = 1.5  # seconds between white flashes at least: on bars, not beats (more is a strobe and washes the edit out)
HIT_GAP = 0.8  # colour-split hits: subtler, may come more often (still well under 3 a second)


def _spaced(x, r, on, every, gap=FLASH_GAP):
    """Hit times for flash-like recipes: on beats they stay in the drop sections unless sections are given, and two
    hits are never closer than FLASH_GAP (a flash on every beat of a minute is a strobe, not an edit)."""
    secs = r.get("sections") or (["drop"] if on in ("beats", "downbeats") else None)
    out = []
    for t in x.times(on, every, secs):
        if not out or t - out[-1] >= gap - 1e-6:
            out.append(t)
    return out


def r_flash(x, r):
    name = x.pick(["scene_effect"], "white flash quick light burst")
    return [
        {
            "id": x.id("fl"),
            "type": "effect",
            "name": name,
            "start": round(max(0.0, t - 0.02), 3),
            "duration": 0.2,
            "layer": "accent",
            "expect": "a white flash on the hit",
        }
        for t in _spaced(x, r, r.get("on", "drop"), r.get("every", 1))
    ]


def r_rgb_hit(x, r):
    name = x.pick(["scene_effect"], "rgb split chromatic aberration glitch hit")
    return [
        {
            "id": x.id("rg"),
            "type": "effect",
            "name": name,
            "start": round(t, 3),
            "duration": 0.25,
            "layer": "accent",
            "expect": "a colour-split glitch hit on the beat",
        }
        for t in _spaced(x, r, r.get("on", "downbeats"), r.get("every", 2), HIT_GAP)
    ]


def r_transitions(x, r):
    fam = r.get("family") or next(iter(x.style.get("transition") or {"flash": "white flash"}))
    query = (x.style.get("transition") or {}).get(fam, fam)
    name = r.get("name") or x.pick(["transition"], query)
    dur = float(r.get("duration") or (0.3 if x.style is STYLES["hype"] else 0.8 if x.style is STYLES["cinematic"] else 0.45))
    out = []
    for i in range(len(x.tl) - 1):
        a, b = x.tl[i], x.tl[i + 1]
        at = r.get("at", "sections")
        if at == "sections" and a["section"] == b["section"]:
            continue
        if at == "every" and (i + 1) % max(1, int(r.get("every", 2))) != 0:
            continue
        if b.get("speed") == "freeze" and fam == "dissolve":
            continue
        out.append(
            {
                "id": x.id("tr"),
                "type": "transition",
                "after": a["id"],
                "name": name,
                "duration": dur,
                "expect": f"a {fam} transition from {a['id']} to {b['id']}",
            }
        )
    return out


def r_ken_burns(x, r):
    amt = float(r.get("amount", 1.08))
    out = []
    for i, c in enumerate(x.tl):
        if c.get("speed") == "velocity":
            continue
        d = round(c["end"] - c["start"], 3)
        pts = [[0, 1.0], [d, amt]] if i % 2 == 0 else [[0, amt], [d, 1.0]]
        out.append(
            {
                "id": x.id("kb"),
                "type": "keyframes",
                "on": c["id"],
                "property": "scale",
                "points": pts,
                "expect": "the shot slowly pushes in" if i % 2 == 0 else "the shot slowly pulls out",
            }
        )
    return out


DARK_LOOK = ("dark", "moody", "gritty", "noir", "low key", "low-key", "crush", "shadow", "night")


def r_grade(x, r):
    out = []
    look = r.get("look") or "cinematic"
    dark_look = any(w in look.lower() for w in DARK_LOOK)
    f = r.get("name") or x.pick(["filter"], look, avoid=() if dark_look else ("dark", "moody", "shadow", "noir", "gloomy"))
    if getattr(x, "own_grade", 0) >= 0.5:  # the planner put its own filters on most shots: one grade per shot, not two
        f = None
    strength, skip = float(r.get("strength", 70)), set()
    bright = (getattr(x, "footage", None) or {}).get("brightness")
    if bright is not None and bright < 0.32 and dark_look:
        # the footage is already dark: a dark look at full strength (plus a vignette) crushes faces into black
        strength, skip = min(strength, 40.0), {"vignette"}
    if f:
        out.append(
            {
                "id": x.id("gr"),
                "type": "filter",
                "name": f,
                "start": 0,
                "duration": x.total,
                "strength": strength,
                "expect": f"one colour look over the whole video ({look})",
            }
        )
    for flag, query in (
        ("grain", "film grain texture noise"),
        ("vignette", "vignette dark edges"),
        ("letterbox", "letterbox black bars cinematic aspect"),
    ):
        if r.get(flag) and flag not in skip:
            out.append(
                {
                    "id": x.id("tx"),
                    "type": "effect",
                    "name": x.pick(["scene_effect"], query, plain=True),
                    "start": 0,
                    "duration": x.total,
                    "layer": "texture",
                    "expect": f"{flag} over the whole video",
                }
            )
    if r.get("light_leak"):  # a leak is a short glow at a few section changes: longer or more often washes the picture out
        secs = x.sections[1:]
        for s in secs[:: max(1, -(-len(secs) // 3))][:3]:
            out.append(
                {
                    "id": x.id("lk"),
                    "type": "effect",
                    "name": x.pick(["scene_effect"], "light leak warm glow"),
                    "start": s["start"],
                    "duration": min(0.8, s["end"] - s["start"]),
                    "layer": "accent",
                    "expect": "a warm light leak opening the section",
                }
            )
    return out


def _text_style(x, r, big=False):
    ts = x.style.get("text") or {}
    font = r.get("font") or x.pick(["font"], ts.get("font", "bold heavy display"))
    size = float(r.get("size") or ts.get("size", 14)) + (6 if big else 0)
    return (
        font,
        size,
        r.get("color") or ts.get("color", "#FFFFFF"),
        r.get("accent") or ts.get("accent", "#FFD23F"),
        x.pick(["text_intro"], r.get("intro") or ts.get("intro", "pop in")),
        int(ts.get("outline", 60)),
    )


def _when(x, at):
    if isinstance(at, (int, float)):
        return float(at)
    if at in ("start", "intro", None):
        return 0.2
    if at == "end":
        return max(0.0, x.total - 2.5)
    if at == "drop" and x.drop is not None:
        return x.drop
    sec = next((s for s in x.sections if s["name"] == at), None)
    return sec["start"] if sec else 0.2


def r_kinetic_title(x, r):
    words = [w for w in str(r.get("text") or "").split() if w][:6]
    if not words:
        return []
    font, size, color, accent, intro, outline = _text_style(x, r, big=True)
    size = max(size, 30.0)  # one slammed word fills most of the width
    t = _when(x, r.get("at", "drop"))
    step = x.beat if x.beat >= 0.35 else x.beat * 2
    out = []
    for i, w in enumerate(words):
        last = i == len(words) - 1
        dur = step * (3 if last else 1)
        st = t + i * step
        if st >= x.total - 0.3:
            break
        out.append(
            {
                "id": x.id("kt"),
                "type": "text",
                "text": w.upper(),
                "start": round(st, 3),
                "duration": round(min(dur, x.total - st), 3),
                "position": "center",
                "size": size + (4 if last else 0),
                "scale": 1.5,
                "font": font,
                "bold": True,
                "color": accent if last else color,
                "outline": {"color": "#000000", "width": outline},
                "shadow": True,
                "intro": intro,
                "intro_duration": 0.18,
                "expect": f"the word {w.upper()} slams in on the beat",
            }
        )
        out.append(
            {
                "id": x.id("kh"),
                "type": "sfx",
                "sound": "impact" if last else "hit",
                "at": round(st, 3),
                "volume": 0.9 if last else 0.6,
                "expect": "a hit sound with the word",
            }
        )
        if last:
            c = x.clip_at(st)
            if c:
                out.append(
                    {
                        "id": x.id("ks"),
                        "type": "shake",
                        "on": c["id"],
                        "start": round(st - c["start"], 3),
                        "duration": 0.4,
                        "strength": 0.7,
                        "expect": "the picture shakes as the last word lands",
                    }
                )
    return out


def r_hook(x, r):
    font, size, color, accent, intro, outline = _text_style(x, r)
    text = str(r.get("text") or "WAIT FOR IT").strip()[:40]
    d = float(r.get("duration", 1.6))
    return [
        {
            "id": x.id("hk"),
            "type": "text",
            "text": text,
            "start": 0.0,
            "duration": d,
            "position": "upper",
            "size": size,
            "font": font,
            "bold": True,
            "color": color,
            "outline": {"color": "#000000", "width": outline},
            "intro": intro,
            "intro_duration": 0.25,
            "expect": f"the hook '{text}' in the first seconds",
        },
        {"id": x.id("hs"), "type": "sfx", "sound": "swoosh", "at": 0.0, "volume": 0.6, "expect": "a swoosh with the hook"},
    ]


def r_captions(x, r):
    lines = [l for l in (r.get("lines") or []) if isinstance(l, dict) and l.get("text")]
    if not lines:
        return []
    font, size, color, accent, intro, outline = _text_style(x, r)
    return [
        {
            "id": x.id("cp"),
            "type": "captions",
            "lines": lines,
            "position": r.get("position", "lower"),
            "size": float(r.get("size") or size),
            "font": font,
            "bold": True,
            "color": color,
            "outline": {"color": "#000000", "width": outline},
            "intro": intro,
            "expect": "captions are readable and on time",
        }
    ]


def r_sfx(x, r, edits, music_has_drop):
    out = []
    if r.get("transitions"):
        for e in edits:
            if e["type"] == "transition":
                c = next((c for c in x.tl if c["id"] == e["after"]), None)
                if c:
                    out.append(
                        {
                            "id": x.id("sw"),
                            "type": "sfx",
                            "sound": r["transitions"],
                            "at": round(max(0.0, c["end"] - 0.3), 3),
                            "volume": 0.55,
                            "expect": "a whoosh with the transition",
                        }
                    )
    if r.get("drop") and x.drop is not None and not music_has_drop:
        out += [
            {"id": x.id("rs"), "type": "sfx", "sound": "riser", "at": round(x.drop, 3), "volume": 0.8, "expect": "a riser builds into the drop"},
            {"id": x.id("im"), "type": "sfx", "sound": "impact", "at": round(x.drop, 3), "volume": 1.0, "expect": "an impact on the drop"},
        ]
    return out


def r_face_punch(x, r, analyses):
    out = []
    by = {a["file"]: a for a in analyses.values()}
    for c in x.tl:
        a = by.get(c.get("file"))
        if not a or a.get("kind") != "video":
            continue
        out.append(
            {
                "id": x.id("fp"),
                "type": "zoom",
                "on": c["id"],
                "start": round(min(0.3, (c["end"] - c["start"]) / 3), 3),
                "duration": round(max(0.4, (c["end"] - c["start"]) * 0.6), 3),
                "to": float(r.get("strength", 1.5)),
                "back": False,
                "expect": "a dramatic zoom onto the face",
            }
        )
        out.append(
            {
                "id": x.id("fb"),
                "type": "sfx",
                "sound": "sub_drop",
                "at": round(c["start"] + min(0.3, (c["end"] - c["start"]) / 3), 3),
                "volume": 1.0,
                "expect": "a boom with the zoom",
            }
        )
        break  # one per edit is the joke; more is noise
    return out


RECIPES = {
    "zoom_punch": r_zoom_punch,
    "shake": r_shake,
    "flash": r_flash,
    "rgb_hit": r_rgb_hit,
    "transitions": r_transitions,
    "ken_burns": r_ken_burns,
    "grade": r_grade,
    "kinetic_title": r_kinetic_title,
    "hook": r_hook,
    "captions": r_captions,
}
SPECIAL = {"sfx", "jump_zoom", "face_punch"}


def merged_recipes(style, wanted):
    """The style's default recipes, with the planner's choices applied: same 'use' = override, 'off' = drop, new = add."""
    out = [dict(r) for r in style.get("recipes", [])]
    for w in wanted or []:
        if not isinstance(w, dict) or not w.get("use"):
            continue
        same = [r for r in out if r["use"] == w["use"] and (w["use"] not in ("kinetic_title", "hook", "flash") or w.get("replace"))]
        if w.get("off"):
            out = [r for r in out if r["use"] != w["use"]]
        elif same and w["use"] not in ("kinetic_title", "captions", "hook"):
            same[0].update(w)
        else:
            out.append(dict(w))
    return out


# ------------------------------------------------------------------------------------------------ talking heads
def speech_cut(plan, analyses, log=print):
    """Shots cut from what is said: pauses and filler words dropped (jump cuts), with a map from file time to timeline."""
    from ai_pc.media import speech as SP

    sp = plan["speech"]
    a = next((a for a in analyses.values() if a.get("file", "").lower() == str(sp.get("file", "")).lower()), None)
    if not a:
        log(f"speech: '{sp.get('file')}' is not an available file")
        return None
    tr = SP.transcribe(a["path"], log=log)
    if not tr or not tr.get("words"):
        log("speech: nothing to transcribe (no speech or no model); cut as normal shots")
        return None
    words = tr["words"]
    runs = (
        SP.speech_runs(words, max_pause=float(sp.get("max_pause", 0.35)), drop_fillers=sp.get("drop_fillers", True))
        if sp.get("cut_pauses", True)
        else [[0.0, float(a.get("seconds") or words[-1]["end"])]]
    )
    clips, tl, t = [], [], 0.0
    for i, (r0, r1) in enumerate(runs):
        cid = f"t{i + 1}"
        clips.append(
            {
                "id": cid,
                "file": a["file"],
                "from": r0,
                "duration": round(r1 - r0, 4),
                "speed": 1.0,
                **({"chroma": "auto", "background": "#0A0A12"} if a.get("screen") else {}),
            }
        )
        tl.append(
            {
                "id": cid,
                "start": round(t, 4),
                "end": round(t + r1 - r0, 4),
                "section": "drop",
                "speed": "normal",
                "kind": "video",
                "src": [r0, r1],
                "file": a["file"],
            }
        )
        t += r1 - r0

    def to_tl(ft):  # file time -> timeline time (None if that moment was cut out)
        for c in tl:
            if c["src"][0] - 1e-6 <= ft <= c["src"][1] + 1e-6:
                return c["start"] + ft - c["src"][0]
        return None

    kept = [{**w, "start": to_tl(w["start"]), "end": to_tl(w["end"])} for w in words]
    kept = [w for w in kept if w["start"] is not None and w["end"] is not None and w["w"].lower().strip(",.!?") not in SP.FILLERS]
    layers = []
    for j, b in enumerate(sp.get("broll") or []):
        if not isinstance(b, dict):
            continue
        hit = next((w for w in kept if str(b.get("word", "")).lower().strip() in w["w"].lower()), None)
        if hit:
            layers.append(
                {
                    "id": f"br{j + 1}",
                    "file": b.get("file"),
                    "at": round(hit["start"], 3),
                    "from": b.get("around") or 0,
                    "duration": float(b.get("seconds", 1.5)),
                    "reframe": "subject",
                }
            )
    saved = (a.get("seconds") or 0) - t
    log(f"speech: {len(words)} words, {len(runs)} cuts, {max(0.0, saved):.1f} s of pauses/fillers removed, {len(layers)} b-roll")
    return {"shots": [], "clips": clips, "timeline": tl, "words": kept, "layers": layers, "speech": sp}


def talk_edits(x, plan, talk, style):
    """Captions from the words (1-3 per line, never across a cut), emphasis words coloured with a punch-in and a pop."""
    from ai_pc.media import speech as SP

    sp, words, out = talk["speech"], talk["words"], []
    emph = [str(w).lower().strip(",.!?") for w in (sp.get("emphasis") or [])] or [w["w"].lower().strip(",.!?") for w in SP.keywords(words)]
    font, size, color, accent, intro, outline = _text_style(x, {})
    if sp.get("captions", "bold_pop") != "none":
        lines = []
        groups = [[w for w in words if c["start"] - 1e-6 <= w["start"] < c["end"]] for c in x.tl]  # never caption across a cut
        for ch in (ch for g in groups for ch in SP.chunks(g, n=3 if sp.get("captions") != "minimal" else 5)):
            hot = any(w.lower().strip(",.!?") in emph for w in ch["words"])
            lines.append(
                {"start": round(ch["start"], 3), "end": round(max(ch["end"], ch["start"] + 0.35), 3), "text": ch["text"].upper(), "hot": hot}
            )
        plain = [l for l in lines if not l["hot"]]
        hot = [l for l in lines if l["hot"]]
        if plain:
            out.append(
                {
                    "id": "cap1",
                    "type": "captions",
                    "lines": [{k: l[k] for k in ("start", "end", "text")} for l in plain],
                    "position": "lower",
                    "size": size,
                    "font": font,
                    "bold": True,
                    "color": color,
                    "outline": {"color": "#000000", "width": outline},
                    "intro": intro,
                    "expect": "captions follow the words",
                }
            )
        if hot:
            out.append(
                {
                    "id": "cap2",
                    "type": "captions",
                    "lines": [{k: l[k] for k in ("start", "end", "text")} for l in hot],
                    "position": "lower",
                    "size": size + 2,
                    "font": font,
                    "bold": True,
                    "color": accent,
                    "outline": {"color": "#000000", "width": outline},
                    "intro": intro,
                    "expect": "the key words pop in the accent colour",
                }
            )
    covered = [(l["at"], l["at"] + l["duration"]) for l in talk.get("layers", [])]
    for i, w in enumerate(w for w in words if w["w"].lower().strip(",.!?") in emph):
        c = x.clip_at(w["start"])
        if not c or any(a - 0.1 <= w["start"] <= b for a, b in covered):
            continue  # under a b-roll the punch-in would not be seen
        out.append(
            {
                "id": f"ez{i + 1}",
                "type": "zoom",
                "on": c["id"],
                "start": round(w["start"] - c["start"], 3),
                "duration": round(min(0.6, c["end"] - w["start"] - 0.05), 3),
                "to": 1.12,
                "back": True,
                "expect": f"a punch-in on the word '{w['w']}'",
            }
        )
        out.append(
            {"id": f"ep{i + 1}", "type": "sfx", "sound": "hit", "at": round(w["start"], 3), "volume": 0.35, "expect": "a soft pop on the key word"}
        )
    return out


WHERE_WORDS = [
    ("end", r"end(?:s|ing)? (?:with|on)|at the end|closing|outro|end card|to finish|finish(?:es|ing)? with"),
    ("drop", r"(?:at|on) the drop|when (?:it|the beat) drops|at the climax"),
    ("start", r"open(?:s|ing)? with|at the (?:start|beginning)|intro title|starts? with"),
]


def place_by_request(extras, request, drop, total):
    """Where the client said a text goes ("the text SATURDAY NIGHT at the drop", "end with see you next week"), from
    the words around it in the request; a text the plan put elsewhere (e.g. both at 0 s) is moved there."""
    import re

    req = " ".join(str(request or "").lower().split())
    notes = []
    for e in extras:
        txt = " ".join(str(e.get("text") or "").lower().split())
        if not txt or e.get("on") or str(e.get("type")).lower() not in ("text", "text_intro", "text_outro", "animation"):
            continue
        i = req.find(txt)
        if i < 0:
            continue
        j = i + len(txt)
        cues = []  # the cue nearest to the words wins ("SATURDAY NIGHT at the drop, and end with see you next week")
        for w, pat in WHERE_WORDS:
            for m in re.finditer(pat, req):
                d = i - m.end() if m.end() <= i else m.start() - j if m.start() >= j else 0
                if d <= 40:
                    cues.append((d, w))
        where = min(cues)[1] if cues else None
        try:
            at = float(e.get("start", e.get("at")) or 0)
            dur = float(e.get("duration") or 2.5)
        except (TypeError, ValueError):
            continue
        want = {"end": max(0.0, total - max(2.5, min(dur, 4.0))), "drop": drop, "start": 0.3}.get(where)
        if want is None or abs(at - want) < 1.0:
            continue
        twins = [o for o in extras if o is not e and " ".join(str(o.get("text") or "").lower().split()) == txt]
        if any(isinstance(o.get("start", o.get("at")), (int, float)) and abs(float(o.get("start", o.get("at"))) - want) < 2.0 for o in twins):
            continue  # the same words are already there (an opening + closing bookend): leave this one where it is
        e["start"] = round(want, 3)
        e.pop("at", None)
        if where == "end":
            e["duration"] = round(total - want, 3)
        notes.append(f"'{e.get('text')}' {at:.1f} s -> {want:.1f} s (the request puts it at the {where})")
    return notes


def anchor_extras(extras, tl, drop, total):
    """The planner cannot know the final timeline (pacing, the length fit and the critic change it), so extras can be
    placed by name: "at"/"start" = "drop" | "end" | "start" | a shot id. A sound effect whose expect puts it on / into
    the drop lands exactly there (a riser then ends on it). Returns notes on what moved."""
    import re

    starts = {c["id"]: c["start"] for c in tl}
    notes = []
    for e in extras:
        for k in ("at", "start"):
            v = e.get(k)
            if not isinstance(v, str):
                continue
            key = v.strip().lower()
            t = (
                drop
                if key in ("drop", "climax")
                else max(0.0, total - 1.0)
                if key in ("end", "ending", "outro")
                else 0.0
                if key in ("start", "intro", "beginning")
                else starts.get(v.strip())
            )
            if t is None:
                try:
                    t = float(v)
                except ValueError:
                    continue
            e[k] = round(t, 3)
        if str(e.get("type")).lower() == "sfx" and drop is not None and not e.get("on"):
            at = e.get("at", e.get("start"))
            if (
                isinstance(at, (int, float))
                and abs(at - drop) > 0.25
                and re.search(
                    r"\b(on|onto|into|at|before|to|hits?|lands?)( exactly)? (on )?the (music'?s? )?drop\b", str(e.get("expect") or "").lower()
                )
            ):
                notes.append(f"{e.get('id')}: {at:.1f} s -> the drop at {drop:.2f} s")
                e["at"] = round(drop, 3)
                e.pop("start", None)
    return notes


def _words(t):
    return " ".join(str(t or "").lower().split())


def _at(e):
    v = e.get("start", e.get("at"))
    return float(v) if isinstance(v, (int, float)) and not e.get("on") else None


def space_accents(edits, extras, x, gap=0.3):
    """One accent per hit: a recipe accent (flash, colour split, light leak) that lands on the same moment as another
    quick effect moves to the next free beat, else it is dropped; the planner's own hits keep their place.
    Returns (moved, dropped)."""
    taken = [t for t in (_at(e) for e in extras if str(e.get("type")).lower() == "effect" and float(e.get("duration") or 1) <= 0.8) if t is not None]
    moved = dropped = 0
    keep = []
    for e in edits:
        if e.get("type") != "effect" or e.get("layer") != "accent" or _at(e) is None:
            keep.append(e)
            continue
        t = _at(e)
        if all(abs(t - u) >= gap for u in taken):
            taken.append(t)
            keep.append(e)
            continue
        nxt = next((b for b in x.beats if b > t + 1e-3 and b < x.total - 0.3 and all(abs(b - u) >= gap for u in taken)), None)
        if nxt is not None and nxt - t <= 2 * x.beat + 1e-3:
            e["start"] = round(nxt, 3)
            taken.append(nxt)
            keep.append(e)
            moved += 1
        else:
            dropped += 1
    edits[:] = keep
    return moved, dropped


def label_edits(x, style, skip=()):
    """A label per shot that has one (step titles, room names, places, scores, feature callouts); not when the planner
    placed the same words itself (`skip`): one text per thing."""
    ls = style.get("label") or {}
    ts = style.get("text") or {}
    font = x.pick(["font"], ts.get("font", "bold sans"))
    runs = []  # the same label on shots in a row is one label over all of them
    for c in x.tl:
        text = str(c.get("label") or "").strip()
        if _words(text) in skip:
            continue
        if text and runs and runs[-1][0] == text and abs(runs[-1][2] - c["start"]) < 1e-3:
            runs[-1][2] = c["end"]
        elif text:
            runs.append([text, c["start"], c["end"]])
    out = []
    for text, s0, s1 in runs:
        d = s1 - s0
        e = {
            "id": x.id("lb"),
            "type": "text",
            "text": text[:60],
            "start": round(s0 + min(0.15, d * 0.1), 3),
            "duration": round(max(0.8, d - 0.3), 3),
            "position": ls.get("position", "bottom_left"),
            "size": float(ls.get("size", 9)),
            "font": font,
            "bold": True,
            "color": ts.get("color", "#FFFFFF"),
            "intro": x.pick(["text_intro"], ls.get("intro", "slide in")),
            "intro_duration": 0.35,
            "outro": x.pick(["text_outro"], "fade out"),
            "outro_duration": 0.3,
            "expect": f"the label '{text[:40]}' on this shot",
        }
        if ls.get("background"):
            e["background"] = {"color": ls["background"], "alpha": 0.55, "round": 0.25}
            e["outline"] = {"color": "#000000", "width": 0}
        else:
            e["outline"] = {"color": "#000000", "width": int(ts.get("outline", 50) or 50)}
        out.append(e)
    return out


def voiceover_edits(x, vo, analyses, style, music_edits, log=print):
    """Narration over the pictures: the narration track, captions from its words, the music ducked while it speaks."""
    from ai_pc.media import speech as SP

    a = next((a for a in analyses.values() if a.get("file", "").lower() == str(vo.get("file", "")).lower()), None)
    if not a:
        log(f"voiceover: '{vo.get('file')}' is not an available file")
        return []
    start_in = float(vo.get("from", 0) or 0)
    length = min(x.total - 0.3, float(vo.get("duration") or (a.get("seconds") or 0) - start_in))
    out = [
        {
            "id": "vo",
            "type": "audio",
            "file": a["file"],
            "at": float(vo.get("at", 0.3) or 0.3),
            "from": start_in,
            "duration": round(length, 3),
            "volume": float(vo.get("volume", 1.0)),
            "expect": "the narration is heard clearly",
        }
    ]
    at = out[0]["at"]
    tr = SP.transcribe(a["path"], log=log)
    if not tr or not tr.get("words"):
        return out
    words = [
        {**w, "start": w["start"] - start_in + at, "end": w["end"] - start_in + at}
        for w in tr["words"]
        if start_in <= w["start"] and w["end"] <= start_in + length
    ]
    if vo.get("captions", "minimal") != "none" and words:
        ts = style.get("text") or {}
        lines = [
            {"start": round(c["start"], 3), "end": round(max(c["end"], c["start"] + 0.5), 3), "text": c["text"]}
            for c in SP.chunks(words, n=7 if vo.get("captions", "minimal") == "minimal" else 3, max_chars=42)
        ]
        out.append(
            {
                "id": "voc",
                "type": "captions",
                "lines": lines,
                "position": "bottom",
                "size": 7,
                "font": x.pick(["font"], ts.get("font", "sans")),
                "color": "#FFFFFF",
                "background": {"color": "#000000", "alpha": 0.45, "round": 0.2},
                "outline": {"color": "#000000", "width": 0},
                "expect": "subtitles follow the narration",
            }
        )
    runs = SP.speech_runs(words, max_pause=0.8, drop_fillers=False, pad=0.15)
    for m in music_edits:  # the music steps back while the narrator speaks
        kf = []
        for r0, r1 in runs:
            kf += [[round(max(0.0, r0 - 0.3), 3), 1.0], [round(r0, 3), 0.35], [round(r1, 3), 0.35], [round(r1 + 0.4, 3), 1.0]]
        m["keyframes"] = sorted(k for k in kf if 0 <= k[0] <= m["duration"])
    log(f"voiceover: {len(words)} words over {length:.1f} s, music ducked {len(runs)}x")
    return out


# ------------------------------------------------------------------------------------------------ compose
def expand_fills(shots, limit):
    """A "fill" shot ({"section": "drop", "fill": 24, "files": [...], "want": ...}) = that many beats of quick cuts at
    the section's pace from those files (the planner names the material, the code writes the cuts)."""
    out = []
    for s in shots:
        try:
            n = int(round(float(s.get("fill") or 0)))
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            out.append(s)
            continue
        norm = limit.get(s.get("section") or "drop") or 2
        files = [f for f in (s.get("files") or [s.get("file")]) if f] or [None]
        base = str(s.get("id") or f"f{len(out) + 1}")
        k, left = 0, min(n, 64)
        while left > 0:
            b = min(norm, left)
            sub = {key: v for key, v in s.items() if key not in ("fill", "files", "around", "beats", "label", "hold")}
            sub.update(id=base if k == 0 else f"{base}_{k + 1}", beats=b, file=files[k % len(files)])
            if k == 0 and s.get("label"):
                sub["label"] = s["label"]
            if sub["file"] is None:
                sub["cutaway"] = True
            out.append(sub)
            k, left = k + 1, left - b
    return out


def match_look(clips, analyses, target, total, log=print):
    """Exposure matching to a darker sample: a black layer over the picture (under titles and effects) whose opacity
    follows each shot's own brightness, so a bright beach shot is dimmed more than a dark road. (JianYing ignores
    brightness keyframes written without its adjust material; a dimming layer is exact and always renders.)
    Returns (layers, edits) or ([], []) when the footage is not brighter than the sample."""
    from PIL import Image

    by = {a["file"].lower(): a for a in analyses.values() if a.get("file")}
    want = float(target.get("brightness") or 0)
    steps, t = [], 0.0
    for c in clips:
        a = by.get(str(c.get("file") or "").lower())
        b = (footage_look({0: a}) if a else {}).get("brightness")
        dur = float(c.get("duration") or 0)
        alpha = max(0.0, min(0.6, 1 - want / b)) if b and b > want + 0.05 else 0.0  # V scales by (1 - alpha) under black
        steps.append((t, round(alpha, 3)))
        t += dur
    if not steps or max(a for _, a in steps) < 0.05:
        return [], []
    path = ROOT_DERIVED / "black_1080.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1080, 1080), (0, 0, 0)).save(path)
    AN.analyze([str(path)], planner=None, log=lambda *a: None)
    analyses.update({path.name: {"file": path.name, "path": str(path), "kind": "image", "width": 1080, "height": 1080, "seconds": 0}})
    layer = {
        "id": "lk_dim",
        "file": path.name,
        "at": 0,
        "duration": round(total, 3),
        "reframe": "center",
        "opacity": steps[0][1],
        "expect": "the picture dimmed to the sample's exposure",
    }
    pts = []
    for i, (s0, a) in enumerate(steps):  # the opacity steps at each cut (two points per cut: hold, then jump)
        if i and abs(a - steps[i - 1][1]) > 0.01:
            pts += [[round(max(0.0, s0 - 0.02), 3), steps[i - 1][1]], [round(s0, 3), a]]
        elif not i:
            pts.append([0.0, a])
    pts.append([round(total, 3), steps[-1][1]])
    edits = (
        [
            {
                "id": "lk_dim_kf",
                "type": "keyframes",
                "on": "lk_dim",
                "property": "alpha",
                "points": pts,
                "adjust": True,
                "expect": "dimming follows each shot's brightness",
            }
        ]
        if len(pts) > 2
        else []
    )
    log(f"  exposure matched to the sample: a dimming layer, opacity {min(a for _, a in steps):.2f}-{max(a for _, a in steps):.2f} by shot")
    return [layer], edits


def footage_look(analyses):
    """Duration-weighted brightness / saturation of all the footage (from the analysis), for exposure-aware looks."""
    acc, w = {}, 0.0
    for a in analyses.values():
        for sh in a.get("shots", []):
            lk, d = sh.get("look"), max(0.1, float(sh.get("end", 0)) - float(sh.get("start", 0)))
            if lk:
                for k in ("brightness", "saturation", "contrast"):
                    acc[k] = acc.get(k, 0.0) + float(lk.get(k) or 0) * d
                w += d
    return {k: round(v / w, 3) for k, v in acc.items()} if w else {}


def enforce_pacing(shots, style, plan, analyses=None):
    """Shots longer than the style allows in their section, handled the way an editor would:
    - a held moment stays whole, only capped (4x the section's norm): the opening, the climax (first drop shot), the
      last shot, slow motion, speed ramps, freezes, shots marked "hold" and shots extras point at;
    - a labelled story beat (a place, step, room) keeps its own footage, capped at a bar or 2x the norm;
    - other long shots become several cuts: a file with several camera shots is cut at different moments of it (other
      angles); a single continuous take is not jump-cut but alternated with cutaways from other files (spread_files
      picks them). Only the first part keeps the label, the key moment and the id that extras point at."""
    limit = style.get("beats_per_shot") or {}
    shots = expand_fills([s for s in shots if isinstance(s, dict)], limit)
    keep = {e.get("on") for e in plan.get("edits") or [] if isinstance(e, dict) and e.get("on")}
    takes = {a["file"].lower(): len(a.get("shots") or [0]) for a in (analyses or {}).values() if a.get("file")}
    out = []
    for i, s in enumerate(shots):
        sec = s.get("section") or "drop"
        cap = limit.get(sec)
        n = cutting._beats(s, limit)
        hold = cutting.held(shots, i, keep) or str(s.get("speed")) in ("slow", "velocity")
        most = (4 * cap if hold else max(4, 2 * cap) if s.get("label") else 1.5 * cap) if cap else 0
        if not cap or n <= most:
            out.append(s)
            continue
        if hold or s.get("label"):
            out.append({**s, "beats": int(most)})  # fit() gives the time back to other shots if the edit is short
            continue
        parts = max(2, round(n / cap))
        base = str(s.get("id") or f"s{len(out) + 1}")
        sizes = [n // parts + (1 if j < n % parts else 0) for j in range(parts)]
        one_take = takes.get(str(s.get("file") or "").lower(), 1) < 2
        for j, b in enumerate(sizes):
            sub = {**s, "id": base if j == 0 else f"{base}{chr(97 + j)}", "beats": b}
            if j:
                sub.update(around=None, label=None)  # the cut engine finds the next best moment
                if one_take and j % 2 == 1:
                    sub.update(file=None, cutaway=True)
            out.append(sub)
    return out


def compose(plan, analyses, cat, log=print, request="", picks=None, keep=()):
    """Planner output (style + shots + recipes + extras) -> a full plan (schema v2) plus the rhythm it was cut to.
    keep: catalogue keys the edit already uses (a recompose after a follow-up keeps them where they still fit).
    Follow-up controls in the design: "pace" (x the shot lengths: 0.75 = faster cuts, 1.3 = calmer) and
    "avoid_files" (files the client does not want in the edit)."""
    keep_items = set(keep or ())  # (the name `keep` is used below for the shots that extras point at)
    style_name = plan.get("style") if plan.get("style") in STYLES else guess(request)
    style = STYLES[style_name]
    ref = plan.get("_reference") if isinstance(plan.get("_reference"), dict) else None
    if ref and ref.get("beats_per_shot"):  # "like this sample": its rhythm replaces the style's
        style = {**style, "beats_per_shot": {**(style.get("beats_per_shot") or {}), **ref["beats_per_shot"]}}
    try:
        pace = min(2.5, max(0.4, float(plan.get("pace") or 1)))
    except (TypeError, ValueError):
        pace = 1.0
    psec = plan.get("pace_sections") if isinstance(plan.get("pace_sections"), dict) else {}

    def scaled(v, f):  # whole beats, rounded the way asked (2 beats x 0.75 = 1 beat: faster; x 1.3 = 3: calmer)
        return max(1, int(float(v) * f + (0.25 if f < 1 else 0.75)))

    psec = plan.get("pace_sections") if isinstance(plan.get("pace_sections"), dict) else {}
    if psec:  # "faster cuts on the drop": only those sections' shots get shorter, the sections keep their length
        style = {
            **style,
            "beats_per_shot": {k: scaled(v, float(psec[k])) if k in psec else v for k, v in (style.get("beats_per_shot") or {}).items()},
        }
        plan = {
            **plan,
            "shots": [
                {**s_, "beats": scaled(s_["beats"], float(psec[s_.get("section")]))}
                if isinstance(s_, dict)
                and s_.get("section") in psec
                and isinstance(s_.get("beats"), (int, float))
                and not s_.get("hold")
                and not s_.get("label")
                else s_
                for s_ in plan.get("shots") or []
            ],
        }
    if pace != 1.0:  # "faster cuts" / "let it breathe": every shot length on the grid scales (fit() keeps the total)
        style = {**style, "beats_per_shot": {k: scaled(v, pace) for k, v in (style.get("beats_per_shot") or {}).items()}}
        plan = {
            **plan,
            "shots": [
                {**s_, "beats": scaled(s_["beats"], pace)}
                if isinstance(s_, dict) and isinstance(s_.get("beats"), (int, float)) and not s_.get("hold")
                else s_
                for s_ in plan.get("shots") or []
            ],
        }
    unwanted = {str(f).lower() for f in plan.get("avoid_files") or []}
    if unwanted:  # the client does not want these files: their shots go, the cut fills the time from the rest
        kept_shots = [
            s_
            for s_ in plan.get("shots") or []
            if not (
                isinstance(s_, dict)
                and (str(s_.get("file") or "").lower() in unwanted or (s_.get("files") and all(str(f).lower() in unwanted for f in s_["files"])))
            )
        ]
        kept_shots = [
            {**s_, "files": [f for f in s_["files"] if str(f).lower() not in unwanted]} if isinstance(s_, dict) and s_.get("files") else s_
            for s_ in kept_shots
        ]
        order = [s_.get("id") for s_ in plan.get("shots") or [] if isinstance(s_, dict)]
        kept_ids = [s_.get("id") for s_ in kept_shots if isinstance(s_, dict)]
        moved = {}
        for i, sid in enumerate(order):  # an extra on a removed shot goes to the next kept shot (else the one before)
            if sid not in kept_ids and kept_ids:
                nxt = next((o for o in order[i + 1 :] if o in kept_ids), None) or next((o for o in reversed(order[:i]) if o in kept_ids), None)
                moved[sid] = nxt
        extras = [({**e, "on": moved[e["on"]]} if isinstance(e, dict) and e.get("on") in moved else e) for e in plan.get("edits") or []]
        plan = {**plan, "shots": kept_shots or plan.get("shots"), "edits": extras}
    music = plan.get("music")
    req_l = str(request or "").lower()
    # "like this sample" means the sample decides the STYLE (grade, music, rhythm, effects); the edit type keeps the
    # structure and content. Only what the request itself names (a look, a music style) overrides the sample.
    ref_look = bool(ref) and not re.search(LOOK_WORDS, req_l)
    if (
        ref
        and ref.get("music")
        and not re.search(MUSIC_WORDS, req_l)
        and not (isinstance(music, dict) and music.get("file"))
        and not plan.get("_music_asked")
    ):
        music = dict(ref["music"])
    user_music, mfrom, _mat = None, 0.0, 0.0
    if isinstance(music, dict) and music.get("file"):
        a = next((a for a in analyses.values() if a.get("file", "").lower() == str(music["file"]).lower()), None)
        if a and (a.get("sound") or {}).get("beats"):
            user_music, mfrom = a, float(music.get("from", 0) or 0)
    if user_music:
        snd = user_music["sound"]
        beat = 60.0 / float(snd["bpm"])
        mdrop = (snd.get("drop") or 0) - mfrom if snd.get("drop") else None
        drop_at = mdrop if mdrop and mdrop > beat * 4 else None
    else:
        bpm = (music or {}).get("bpm") if isinstance(music, dict) else None
        beat = 60.0 / float(bpm or style.get("bpm") or 120)
        drop_at = None
    for s_ in plan.get("shots") or []:  # section names the music and pacing know (a planner may write "climax", "hook"...)
        if isinstance(s_, dict):
            sec = str(s_.get("section") or "drop").lower().strip()
            s_["section"] = sec if sec in SECTIONS else SECTION_ALIASES.get(sec, "verse")
    talk = speech_cut(plan, analyses, log) if isinstance(plan.get("speech"), dict) else None
    shots = talk["shots"] if talk else enforce_pacing(plan.get("shots") or [], style, plan, analyses)
    if not shots:  # no shot list: every file, best moments, the style's pacing
        shots = [
            {"id": f"s{i + 1}", "file": a["file"], "section": ("intro" if i == 0 else "drop")}
            for i, a in enumerate(analyses.values())
            if a.get("kind") in ("video", "image")
        ]
    try:
        target = float(plan.get("target_seconds") or 0) or None
    except (TypeError, ValueError):
        target = None
    vo = plan.get("voiceover") if isinstance(plan.get("voiceover"), dict) else None
    if vo and not talk:  # the pictures must last as long as the narration
        va = next((a for a in analyses.values() if a.get("file", "").lower() == str(vo.get("file", "")).lower()), None)
        need = float(vo["duration"]) + 0.8 if vo.get("duration") else ((va or {}).get("seconds") or 0) - float(vo.get("from", 0) or 0) + 0.8
        target = max(target or 0, need)
    if not talk:  # footage spread over the files, then the exact length (both the way an editor would do it)
        keep = {e.get("on") for e in plan.get("edits") or [] if isinstance(e, dict) and e.get("on")}
        bps = style.get("beats_per_shot") or {}
        n0, t0 = len(shots), sum(cutting.shot_lengths(shots, beat, bps, drop_at))
        from ai_pc.video.awareness import off_brief

        avoid = off_brief(request, analyses)
        avoid.update({a["file"]: "the client asked not to use it" for a in analyses.values() if str(a.get("file", "")).lower() in unwanted})
        less = {str(f).lower() for f in plan.get("less_files") or []}
        for f, why in avoid.items():
            log(f"  not using {f}: {why}")
        shots = cutting.spread_files(shots, analyses, keep, avoid, less)
        if target:
            shots = cutting.spread_files(cutting.fit(shots, beat, bps, target, drop_at, keep, style.get("drop_by")), analyses, keep, avoid, less)
            t1 = sum(cutting.shot_lengths(shots, beat, bps, drop_at))
            if abs(t1 - t0) > beat:
                log(f"length fitted: {t0:.1f} s ({n0} shots) -> {t1:.1f} s ({len(shots)} shots) for a {target:.0f} s target")
    if talk:
        clips, tl, drop = talk["clips"], talk["timeline"], None
    else:
        clips, tl, drop = cutting.cut(shots, analyses, beat, style, drop_at, plan.get("canvas"))
    if not clips:
        raise ValueError("no usable shots")
    total = tl[-1]["end"]
    edits_music, music_has_drop = [], False
    want_music = not (music in ("none", None, False) or (isinstance(music, dict) and music.get("none")))
    gen_style = (
        music.get("generate") if isinstance(music, dict) else music if isinstance(music, str) and music not in ("none",) else None
    ) or style.get("music")
    if user_music:
        snd = user_music["sound"]
        beats = [round(b - mfrom, 4) for b in snd["beats"] if b >= mfrom and b - mfrom < total]
        edits_music.append(
            {
                "id": "music",
                "type": "audio",
                "file": user_music["file"],
                "at": 0,
                "from": mfrom,
                "duration": total,
                "volume": float((music or {}).get("volume", 0.8)),
                "fade_out": 1.0,
                "expect": "the music plays under the edit",
            }
        )
        grid = {"beats": beats, "downbeats": beats[::4], "drop": drop, "source": "music file", "bpm": snd["bpm"]}
    elif (want_music or plan.get("music") is None) and gen_style and not (talk and plan.get("music") is None):
        secs_for_music = []
        for c in tl:  # the edit's own sections, so the music rises and drops exactly where the cut does
            if secs_for_music and secs_for_music[-1]["name"] == c["section"]:
                secs_for_music[-1]["end"] = c["end"]
            else:
                secs_for_music.append({"name": c["section"], "start": c["start"], "end": c["end"]})
        long_edit = total > 25 or len(secs_for_music) > 4
        path, grid = MU.bed(
            gen_style, total, bpm=round(60 / beat), drop_at=drop if drop is not None else None, sections=secs_for_music if long_edit else None
        )
        AN.analyze([str(path)], planner=None, log=lambda *a: None)
        analyses.update(
            {
                path.name: {
                    "file": path.name,
                    "path": str(path),
                    "kind": "audio",
                    "seconds": total,
                    "sound": {"kind": "music", "bpm": grid["bpm"], "beats": grid["beats"], "drop": grid["drop"]},
                }
            }
        )
        edits_music.append(
            {
                "id": "music",
                "type": "audio",
                "file": path.name,
                "at": 0,
                "from": 0,
                "duration": total,
                "volume": 0.22 if talk else (0.35 if plan.get("voiceover") else 0.85),
                "duck_under_speech": bool(talk),
                "fade_out": 1.0,
                "expect": f"a generated {gen_style} beat at {grid['bpm']} BPM" + (" quietly under the voice" if talk else ""),
            }
        )
        music_has_drop = True
    else:
        n = int(total / beat) + 1
        grid = {
            "beats": [round(i * beat, 4) for i in range(n)],
            "downbeats": [round(i * beat, 4) for i in range(0, n, 4)],
            "drop": drop,
            "source": "tempo only (no music)",
            "bpm": round(60 / beat),
        }
    sections = []
    for c in tl:  # sections from the shots themselves
        if sections and sections[-1]["name"] == c["section"]:
            sections[-1]["end"] = c["end"]
        else:
            sections.append({"name": c["section"], "start": c["start"], "end": c["end"]})
    grid["sections"] = sections
    x = Ctx(tl, grid["beats"], grid["downbeats"], drop, sections, style, cat, total)
    x.keep = keep_items
    for k, v in (picks or plan.get("_picks") or {}).items():  # a recompose keeps the items chosen the first time
        try:
            x._picks[tuple(tuple(p) if isinstance(p, list) else p for p in json.loads(k))] = v
        except (ValueError, TypeError):
            pass
    x.footage = footage_look(analyses)
    own = [e for e in plan.get("edits") or [] if isinstance(e, dict) and str(e.get("type")).lower() == "filter"]
    covered = 0.0
    for e in own:  # how much of the edit the planner's own filters cover (shot-anchored or absolute)
        try:
            covered += float(e.get("duration") or 0) or next((c["end"] - c["start"] for c in tl if c["id"] == e.get("on")), 0.0)
        except (TypeError, ValueError):
            pass
    x.own_grade = covered / max(1e-6, total)
    x.request = " ".join([str(request or ""), str(plan.get("name") or "")]).lower()
    words = " ".join(
        [request] + [str(s.get("label") or "") for s in shots] + [str(e.get("text") or "") for e in plan.get("edits") or [] if isinstance(e, dict)]
    )
    x.latin = sum(ch.isascii() for ch in words) >= 0.9 * max(1, len(words))
    # style defaults < the sample's measured recipes < what the designer chose explicitly
    own = [r for r in plan.get("recipes") or [] if isinstance(r, dict) and not (ref_look and r.get("use") == "grade")]
    recipes = merged_recipes(style, [{**r, "replace": True} for r in (ref or {}).get("recipes") or []] + own)
    edits, sfx_r, made = [], None, {}
    for r in recipes:
        use = r.get("use")
        before = len(edits)
        if use == "sfx":
            sfx_r = r
        elif use == "jump_zoom":
            for i, c in enumerate(clips):  # every other cut a little closer: jump cuts read as intentional
                if i % 2 == 1:
                    rf = c.get("reframe") if isinstance(c.get("reframe"), dict) else {"x": 0.5, "y": 0.4}
                    c["reframe"] = {**rf, "zoom": float(r.get("amount", 1.15))}
        elif use == "face_punch":
            edits += r_face_punch(x, r, analyses)
        elif use in RECIPES:
            try:
                edits += RECIPES[use](x, r)
            except Exception as e:  # noqa: BLE001
                log(f"recipe {use} skipped: {type(e).__name__}: {e}")
        made.setdefault(use, []).extend(e["id"] for e in edits[before:])
    if sfx_r:
        n0 = len(edits)
        edits += r_sfx(x, sfx_r, edits, music_has_drop)
        made["sfx"] = [e["id"] for e in edits[n0:]]
    if edits_music:
        made["music"] = ["music"]
    if talk:
        edits += talk_edits(x, plan, talk, style)
        made["speech"] = [e["id"] for e in edits if str(e["id"]).startswith(("cap", "ez", "ep"))]
    extras = [dict(e) for e in (plan.get("edits") or []) if isinstance(e, dict)]
    if ref_look:  # the sample decides the look: the planner's own colour filters would fight its grade

        def is_filter(e):
            return str(e.get("type")).lower() == "filter" or (
                str(e.get("type")).lower() == "effect" and any(cat.item(k)["category"] == "filter" for k in cat.exact(e.get("name")))
            )

        dropped = [e.get("id") for e in extras if is_filter(e)]
        extras = [e for e in extras if not is_filter(e)]
        if dropped:
            log(f"  the sample's grade replaces the planned filters {dropped}")
        if ref.get("target_look"):
            dim_layers, adj = match_look(clips, analyses, ref["target_look"], total, log)
            edits += adj
            plan = {**plan, "layers": list(plan.get("layers") or []) + dim_layers}
            made["look_match"] = [x["id"] for x in dim_layers + adj]
    for n in anchor_extras(extras, tl, drop, total) + place_by_request(extras, request, drop, total):
        log(f"  anchored {n}")
    moved, dropped = space_accents(edits, extras, x)
    if moved or dropped:
        log(f"  accents: {moved} moved to the next free beat, {dropped} dropped (one hit at a time reads; stacked ones wash out)")
    lab = label_edits(x, style, skip={_words(e.get("text")) for e in extras if e.get("text") and str(e.get("type")).lower() != "captions"})
    if lab:
        edits += lab
        made["labels"] = [e["id"] for e in lab]
    if isinstance(plan.get("voiceover"), dict):
        vo = voiceover_edits(x, plan["voiceover"], analyses, style, edits_music, log)
        edits += vo
        made["voiceover"] = [e["id"] for e in vo]
    out = {
        "name": plan.get("name") or style_name,
        "platform": plan.get("platform"),
        "canvas": plan.get("canvas"),
        "think": plan.get("think"),
        "style": style_name,
        "clips": clips,
        "layers": (plan.get("layers") or []) + (talk["layers"] if talk else []),
        "edits": edits_music + edits + extras,
        "_rhythm": {
            "bpm": grid.get("bpm"),
            "source": grid.get("source"),
            "drop": drop,
            "shots": len(clips),
            "recipes": [r["use"] for r in recipes],
            "sections": [{"name": z["name"], "start": round(z["start"], 3), "end": round(z["end"], 3)} for z in sections],
        },
        "_recipe_ids": made,
        "_picks": {json.dumps(list(k)): v for k, v in x._picks.items()},
    }
    log(
        f"composed {style_name}: {len(clips)} shots on a {grid.get('bpm')} BPM grid ({grid.get('source')}), drop at "
        f"{drop if drop is None else round(drop, 2)} s, {len(edits)} recipe edits + {len(extras)} hand-placed"
    )
    return out
