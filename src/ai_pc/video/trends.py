"""Trend vocabulary: what template titles and hashtags ask for, in this editor's techniques.

Frames show cuts, flashes, zooms and colour; they do not show that a template is slow motion, that it is a glow-up
reveal, or that it is made for Eid. A template's title and hashtags do ("SLOWMO HDR #slowmo #eid"). techniques()
turns them into settings the template filler applies:

  speed / ramp       slow motion on every slot, or fast-slow-fast speed ramps (velocity)
  look               the grade in words (HDR, dreamy, vintage, warm festive...) for the filter search
  bw / bw_until_drop black and white, or black and white until the drop then colour (glow-up reveals)
  push / punch       slow push-ins / zoom punches on the beat;  shake: shakes on the hits
  cut                how the template cuts: flash, blur, dissolve, glitch;  grain / letterbox textures
  greeting           a text the occasion suggests (offered, added only when asked for)
  music              the music style;  bpm the tempo it usually has;  photos: a photo-dump template

Hashtags that say nothing about the edit (#fyp, #viral, the creator's handle) are ignored. A tag the dictionary does
not know is mapped once by the cheap model onto these same settings (checked, then remembered in state/trends.json).
"""

import json
import re

from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json

STORE = ROOT / "state" / "trends.json"

TRENDS = [  # (name, words in the title or hashtags, settings, why)
    ("slowmo", r"slow ?-?mo|slomo|slow ?motion|smooth ?mo", {"speed": 0.45, "bpm": 100}, "slow motion on every slot"),
    (
        "velocity",
        r"velocity|velo\b|speed ?ramp|\bramp\b|vlc",
        {"ramp": "fast-slow-fast", "bpm": 140, "cut": "flash"},
        "fast-slow-fast speed ramps on the moments",
    ),
    (
        "hdr",
        r"\bhdr\b|hdr$|high ?dynamic|clarity|ultra ?hd|\buhd\b|4k ?look|crisp",
        {"look": "HDR high contrast clarity vivid sharp"},
        "an HDR look: deep blacks, bright highlights, vivid colour",
    ),
    (
        "glowup",
        r"glow ?up|before ?(?:and|&|n) ?after|transformation|then ?(?:and|&) ?now|reveal",
        {"bw_until_drop": True, "look": "vivid warm"},
        "black and white until the drop, then colour (the reveal)",
    ),
    ("3dzoom", r"3d ?zoom|\b3d\b|parallax", {"push": 1.18}, "3D-style slow push-ins"),
    ("zoom", r"(?<!3d )(?<!3d)\bzoom", {"punch": True}, "zoom punches on the beat"),
    ("shake", r"shake|earthquake|vibrat|tremble", {"shake": True}, "shakes on the hits"),
    ("flash", r"flash|strobe|blink", {"cut": "flash"}, "flash cuts"),
    ("blur", r"\bblur|motion ?blur", {"cut": "blur"}, "blur transitions"),
    ("glitch", r"glitch|\brgb\b|error|distort", {"cut": "glitch"}, "glitch transitions"),
    ("beat", r"\bbeat|\bsync|bass|\bdrop\b", {"punch": True}, "cuts and hits on the beat"),
    ("lyrics", r"lyric|caption|quote|\btext\b|words", {"kinetic_text": True}, "words on screen with the music"),
    (
        "aesthetic",
        r"aesthetic|dreamy|\bsoft\b|pastel|\bvibes?\b",
        {"look": "soft dreamy pastel glow", "cut": "dissolve", "bpm": 90},
        "a soft, dreamy look",
    ),
    (
        "cinematic",
        r"cinematic|movie|\bfilm\b",
        {"look": "cinematic film teal", "letterbox": True, "cut": "dissolve", "bpm": 90},
        "a cinematic film look",
    ),
    (
        "retro",
        r"retro|vintage|old ?school|\b90s\b|\b80s\b|y2k|camcorder|vhs",
        {"look": "vintage retro film faded", "grain": True},
        "a vintage film look",
    ),
    ("bw", r"black ?(?:and|&) ?white|\bbw\b|b&w|monochrome|noir", {"bw": True}, "black and white"),
    ("neon", r"neon|cyber|synthwave", {"look": "neon cyberpunk vivid night"}, "a neon look"),
    ("phonk", r"phonk|drift", {"music": "phonk", "shake": True, "bpm": 140, "cut": "flash"}, "phonk energy: hits, shakes, flashes"),
    ("anime", r"anime|\bamv\b|manga", {"cut": "flash", "punch": True, "bpm": 140}, "anime-edit hits"),
    ("eid", r"\beid\b|eid ?mubarak|ramadan|ramzan", {"look": "warm golden festive", "greeting": "Eid Mubarak"}, "a warm, festive Eid look"),
    ("birthday", r"birthday|\bbday\b|\bhbd\b", {"look": "warm vivid bright", "greeting": "Happy Birthday"}, "a bright birthday look"),
    (
        "wedding",
        r"wedding|shaadi|nikah|bride|groom|mehndi|barat|walima",
        {"look": "warm romantic soft", "cut": "dissolve", "bpm": 80},
        "a soft romantic wedding look",
    ),
    ("love", r"\blove|couple|romantic|valentine|\bbae\b|\bjaan\b", {"look": "warm romantic soft", "cut": "dissolve"}, "a warm romantic look"),
    (
        "sad",
        r"\bsad\b|emotional|broken|alone|heartbreak|dard",
        {"look": "muted cold desaturated", "speed": 0.75, "bpm": 80, "cut": "dissolve"},
        "a muted, slow, emotional feel",
    ),
    ("gym", r"\bgym\b|workout|fitness|motivation|grind", {"look": "dark moody gritty", "shake": True, "bpm": 140}, "a dark gritty gym look"),
    ("car", r"\bcars?\b|racing|supercar|\bjdm\b", {"look": "teal orange cinematic", "punch": True}, "a teal-orange car look"),
    ("summer", r"summer|beach|sunny|tropical", {"look": "warm bright vivid"}, "a warm summer look"),
    ("night", r"\bnight|city ?lights|\bclub\b|party", {"look": "neon night vivid", "cut": "flash"}, "a night look with flashes"),
    ("photodump", r"photo ?dump|\bdump\b|carousel|slideshow|memories", {"photos": True, "push": 1.08}, "a photo dump: stills with slow pushes"),
    ("travel", r"travel|\btrip\b|vacation|holiday|wanderlust", {"look": "warm vivid travel"}, "a bright travel look"),
]
TRENDS = [(n, re.compile(p, re.I), s, w) for n, p, s, w in TRENDS]
IGNORE = re.compile(
    r"^(fyp\w*|for ?you\w*|viral\w*|trend\w*|capcut\w*|templates?|new\w*|edit\w*|explore\w*|tiktok\w*|reels?|insta\w*|"
    r"instagram|youtube|shorts?|xyz\w*|foryoupag\w*|trendingsong|song|music|audio|video|cc|ib|credit\w*|like\w*|follow\w*|"
    r"subscribe|share|duet|stitch|pov|\d+)$",
    re.I,
)
KEYS = {
    "speed",
    "ramp",
    "look",
    "bw",
    "bw_until_drop",
    "push",
    "punch",
    "shake",
    "cut",
    "grain",
    "letterbox",
    "greeting",
    "music",
    "bpm",
    "photos",
    "kinetic_text",
}


def _learned():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def techniques(title="", tags=(), request="", planner=None):
    """Settings for the template filler from a template's title and hashtags (and the client's request words).
    {"settings": {...}, "matched": [[word, trend, why]], "unknown": [tags]}"""
    words = [("title", str(title or ""))] + [("tags", str(t)) for t in tags or []] + ([("request", str(request))] if request else [])
    settings, matched = {}, []
    looks = {"title": [], "tags": [], "request": []}  # the title says what the template IS; hashtags are for being found
    seen, given = set(), {}
    for src, w in words:
        for name, rx, s, why in TRENDS:
            if name in seen or not rx.search(w):
                continue
            seen.add(name)
            given[name] = s
            matched.append([w.strip()[:40], name, why])
            for k, v in s.items():
                if k == "look":
                    looks[src].append(v)
                elif k == "speed":
                    settings["speed"] = min(settings.get("speed", 1.0), v)  # the slowest asked for
                elif k not in settings:
                    settings[k] = v
    learned = _learned()
    unknown = []
    for t in tags or []:
        t = str(t).lower().strip("#")
        if not t or IGNORE.match(t) or any(rx.search(t) for _, rx, _, _ in TRENDS):
            continue
        if t in learned:
            for k, v in (learned[t] or {}).items():
                if k == "look":
                    looks["tags"].append(v)
                elif k in KEYS and k not in settings:
                    settings[k] = v
            if learned[t]:
                given[f"#{t}"] = learned[t]
                matched.append([t, f"#{t}", ", ".join(f"{k}: {v}" for k, v in learned[t].items())[:80]])
        else:
            unknown.append(t)
    if unknown and planner is not None:
        learned.update(_ask(unknown, title, planner))
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(learned, ensure_ascii=False, indent=1), encoding="utf-8")
        return techniques(title, tags, request, None)
    # one look, not a blend: a filter found for "HDR ... warm golden festive" fits neither. The title's look leads,
    # the hashtags' only when the title has none; the rest is kept as a suggestion
    order = [looks[k] for k in ("title", "tags", "request") if looks[k]]
    if order:
        settings["look"] = order[0][0]
        rest = [v for group in order for v in group][1:]
        if rest:
            settings["look_also"] = rest[0]
    for m in matched:  # what each word really changed (a second look, or a value already set, is not applied)
        s = given.get(m[1]) or {}
        m.append(sorted(k for k, v in s.items() if settings.get(k) == v))
    return {"settings": settings, "matched": matched, "unknown": unknown}


ASK_SYSTEM = """Map video-template hashtags to editing settings. For each tag give ONE JSON object of settings, or {} when the tag
says nothing about how the video is edited (a name, a handle, a place, a generic word). Settings (only these keys):
"speed": 0.3-1.0 (slow motion), "ramp": "fast-slow-fast", "look": "<grade in a few words>", "bw": true, "bw_until_drop": true,
"push": 1.05-1.2, "punch": true, "shake": true, "cut": "flash|blur|dissolve|glitch", "grain": true, "letterbox": true,
"greeting": "<short text for an occasion>", "music": "hype|phonk|epic|pop|chill|cinematic", "bpm": 70-160, "photos": true.
Reply with ONE JSON object: {"<tag>": {settings}, ...}"""


def _ask(tags, title, planner):
    try:
        r = planner._call(
            "fast",
            [
                {"role": "system", "content": ASK_SYSTEM},
                {"role": "user", "content": f"Template title: {title}\nTags: {', '.join(tags[:20])}\nThe JSON:"},
            ],
        )
        d = parse_json(r.text) or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for t in tags:
        s = d.get(t) if isinstance(d.get(t), dict) else {}
        clean = {}
        for k, v in s.items():  # only known settings, in range
            if k not in KEYS:
                continue
            if k == "speed" and isinstance(v, (int, float)) and 0.3 <= v <= 1.0:
                clean[k] = round(float(v), 2)
            elif k == "push" and isinstance(v, (int, float)) and 1.0 < v <= 1.25:
                clean[k] = round(float(v), 2)
            elif k == "bpm" and isinstance(v, (int, float)) and 60 <= v <= 180:
                clean[k] = int(v)
            elif k == "cut" and v in ("flash", "blur", "dissolve", "glitch"):
                clean[k] = v
            elif k == "music" and v in ("hype", "phonk", "epic", "pop", "chill", "cinematic"):
                clean[k] = v
            elif k == "ramp" and v == "fast-slow-fast":
                clean[k] = v
            elif k in ("look", "greeting") and isinstance(v, str) and 0 < len(v) <= 60:
                clean[k] = v
            elif k in ("bw", "bw_until_drop", "punch", "shake", "grain", "letterbox", "photos", "kinetic_text") and v is True:
                clean[k] = True
        out[t] = clean
    return out


KEY_TEXT = {
    "speed": lambda v: f"slow motion ({v}x)",
    "ramp": lambda v: "fast-slow-fast speed ramps",
    "look": lambda v: f"a {v} look",
    "bw": lambda v: "black and white",
    "bw_until_drop": lambda v: "black and white until the drop",
    "push": lambda v: "slow push-ins",
    "punch": lambda v: "zoom punches on the beat",
    "shake": lambda v: "shakes on the hits",
    "cut": lambda v: f"{v} cuts",
    "grain": lambda v: "film grain",
    "letterbox": lambda v: "letterbox bars",
    "greeting": lambda v: f"the greeting '{v}' (on request)",
    "music": lambda v: f"{v} music",
    "photos": lambda v: "a photo dump",
    "kinetic_text": lambda v: "words with the music",
}


def _parts(tech):
    """[(what it does, the word it came from)] for the settings each matched word really gives."""
    out = []
    st = tech.get("settings") or {}
    for m in tech.get("matched") or []:
        keys = m[3] if len(m) > 3 else None
        if keys is None:  # an older record: the trend's own words
            out.append((m[2], m[0]))
            continue
        shown = [k for k in keys if k != "bpm"]
        if not shown:
            continue
        own = next((s for n, _, s, _ in TRENDS if n == m[1]), None)
        if own is not None and set(own) - {"bpm"} <= set(keys):  # everything it asks for is applied: its own words
            out.append((m[2], m[0]))
        else:
            out.append((", ".join(KEY_TEXT[k](st.get(k)) for k in shown if k in KEY_TEXT), m[0]))
    return out


def short(tech):
    """The styles alone, for a chat reply ("slow motion on every slot, an HDR look: ...")."""
    return "; ".join(w for w, _ in _parts(tech)[:4])


def explain(tech):
    """The techniques in words, with the words they came from."""
    return "; ".join(f"{w} (from '{src}')" for w, src in _parts(tech)) or "no trend words"
