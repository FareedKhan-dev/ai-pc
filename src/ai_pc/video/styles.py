"""Style profiles: how a professional cuts each kind of short-form or YouTube edit. A style sets the pacing (how many
beats per shot in each section), which recipes run by default and with what strength, the transition family, the text
look, the colour/texture, the music bed and how dense the sound design is. The planner picks a style (or the brief
implies one); the recipes (recipes.py) and the cut engine (cutting.py) turn it into dozens of precisely timed edits.

Item names are given as search phrases, resolved against the knowledge base at run time (only working items are used).
"""

STYLES = {
    "hype": {
        "drop_by": 0.25,  # the first drop lands by this share of the length (code never grows the build-up past it)
        "label": {"position": "upper", "size": 12, "intro": "screen punch slam", "background": None},
        "about": "hype / velocity / boss / phonk / sports / car edits: fast cuts on the beat, speed ramps, punch zooms, flashes",
        "music": "hype",
        "bpm": 140,
        "beats_per_shot": {"intro": 4, "verse": 2, "build": 2, "drop": 2, "break": 4, "outro": 4},
        "speed": {"intro": "normal", "build": "normal", "drop": "velocity", "outro": "slow"},
        "recipes": [
            {"use": "zoom_punch", "on": "beats", "every": 2, "sections": ["drop"], "strength": 1.14, "blur": True},
            {"use": "shake", "on": "downbeats", "sections": ["drop"], "strength": 0.5},
            {"use": "flash", "on": "drop"},
            {"use": "rgb_hit", "on": "downbeats", "every": 2, "sections": ["drop"]},
            {"use": "transitions", "family": "flash", "at": "sections"},
            {"use": "grade", "look": "dark contrast cinematic", "grain": True, "vignette": True},
            {"use": "sfx", "transitions": "whoosh", "drop": True, "words": "hit"},
        ],
        "text": {"font": "Anton bold heavy", "size": 18, "color": "#FFFFFF", "accent": "#FF2D2D", "intro": "screen punch slam", "outline": 70},
        "transition": {"flash": "white flash", "zoom": "zoom in push", "whip": "horizontal blur whip", "glitch": "glitch"},
    },
    "cinematic": {
        "drop_by": 0.5,  # the first drop lands by this share of the length (code never grows the build-up past it)
        "label": {"position": "bottom_left", "size": 8, "intro": "fade in", "background": None},
        "about": "cinematic / travel / aesthetic film look: long shots, slow motion, slow push-ins, dissolves, letterbox",
        "music": "cinematic",
        "bpm": 84,
        "beats_per_shot": {"intro": 4, "verse": 4, "build": 4, "drop": 4, "break": 6, "outro": 6},
        "speed": {"intro": "slow", "build": "slow", "drop": "normal", "outro": "slow"},
        "recipes": [
            {"use": "ken_burns", "amount": 1.08},
            {"use": "transitions", "family": "dissolve", "at": "every", "every": 2},
            {"use": "grade", "look": "teal orange film cinematic", "grain": True, "letterbox": True, "light_leak": False},
            {"use": "sfx", "transitions": "swoosh", "drop": False},
        ],
        "text": {"font": "elegant serif", "size": 13, "color": "#F4EDE4", "accent": "#F4EDE4", "intro": "fade in", "outline": 0},
        "transition": {"dissolve": "cross dissolve", "blur": "blur", "fade": "fade black"},
    },
    "montage": {
        "drop_by": 0.3,  # the first drop lands by this share of the length (code never grows the build-up past it)
        "label": {"position": "upper", "size": 10, "intro": "pop bounce", "background": "#000000"},
        "about": "upbeat montage / vlog recap / travel reel / photo slideshow: cuts every 2 beats, gentle zooms, light leaks",
        "music": "pop",
        "bpm": 118,
        "beats_per_shot": {"intro": 2, "verse": 2, "build": 2, "drop": 2, "break": 4, "outro": 4},
        "speed": {"intro": "normal", "build": "normal", "drop": "normal", "outro": "slow"},
        "recipes": [
            {"use": "ken_burns", "amount": 1.06},
            {"use": "zoom_punch", "on": "downbeats", "every": 1, "sections": ["drop"], "strength": 1.08, "blur": False},
            {"use": "transitions", "family": "zoom", "at": "every", "every": 3},
            {"use": "grade", "look": "bright warm vivid", "grain": False, "light_leak": True},
            {"use": "sfx", "transitions": "swoosh", "drop": True},
        ],
        "text": {"font": "Montserrat bold rounded", "size": 15, "color": "#FFFFFF", "accent": "#FFD23F", "intro": "pop bounce", "outline": 40},
        "transition": {"zoom": "zoom in push", "slide": "slide", "dissolve": "cross dissolve"},
    },
    "tour": {
        "drop_by": 0.5,  # the first drop lands by this share of the length (code never grows the build-up past it)
        "label": {"position": "bottom_left", "size": 10, "intro": "fade in slide", "background": "#000000"},
        "about": "property / hotel / venue / product-space tour: bright clean airy look (no grain, no vignette), slow pans "
        "and push-ins, soft dissolves, elegant labels for each area, calm music",
        "music": "cinematic",
        "bpm": 80,
        "beats_per_shot": {"intro": 4, "verse": 4, "build": 4, "drop": 4, "break": 6, "outro": 6},
        "speed": {"intro": "normal", "build": "normal", "drop": "normal", "outro": "slow"},
        "recipes": [
            {"use": "ken_burns", "amount": 1.06},
            {"use": "transitions", "family": "dissolve", "at": "every", "every": 2},
            {"use": "grade", "look": "bright clean natural airy", "grain": False, "vignette": False, "letterbox": False},
            {"use": "sfx", "transitions": "swoosh", "drop": False},
        ],
        "text": {"font": "elegant serif", "size": 13, "color": "#FFFFFF", "accent": "#E8D8B0", "intro": "fade in", "outline": 30},
        "transition": {"dissolve": "cross dissolve", "fade": "fade white", "blur": "blur"},
    },
    "talking": {
        "label": {"position": "top", "size": 9, "intro": "pop in", "background": "#000000"},
        "about": "talking head / YouTube / podcast clip / storytime: pauses cut out, jump-cut zooms, captions, emphasis pops",
        "music": None,
        "bpm": None,
        "beats_per_shot": None,
        "speed": {},
        "recipes": [
            {"use": "jump_zoom", "amount": 1.15},
            {"use": "captions", "style": "bold_pop"},
            {"use": "sfx", "words": "pop"},
        ],
        "text": {"font": "Montserrat Black heavy", "size": 11, "color": "#FFFFFF", "accent": "#FFE135", "intro": "pop in", "outline": 80},
        "transition": {},
    },
    "meme": {
        "label": {"position": "top", "size": 14, "intro": "pop in", "background": None},
        "about": "meme / funny reaction: dramatic punch zooms on faces with a boom, freeze frames, shakes, big impact text",
        "music": None,
        "bpm": None,
        "beats_per_shot": None,
        "speed": {},
        "recipes": [
            {"use": "face_punch", "strength": 1.5},
            {"use": "sfx", "drop": True},
        ],
        "text": {"font": "impact bold heavy", "size": 20, "color": "#FFFFFF", "accent": "#FFFFFF", "intro": "pop in", "outline": 90},
        "transition": {},
    },
    "product": {
        "drop_by": 0.3,  # the first drop lands by this share of the length (code never grows the build-up past it)
        "label": {"position": "bottom_left", "size": 9, "intro": "slide up", "background": "#000000"},
        "about": "product showcase / ad: clean cuts on the beat, slow zooms on details, labels, bright grade",
        "music": "pop",
        "bpm": 112,
        "beats_per_shot": {"intro": 4, "verse": 2, "build": 2, "drop": 2, "break": 4, "outro": 4},
        "speed": {"intro": "slow", "build": "normal", "drop": "normal", "outro": "slow"},
        "recipes": [
            {"use": "ken_burns", "amount": 1.1},
            {"use": "transitions", "family": "slide", "at": "sections"},
            {"use": "grade", "look": "bright clean crisp", "grain": False},
            {"use": "sfx", "transitions": "swoosh", "drop": True},
        ],
        "text": {"font": "Montserrat bold clean sans", "size": 13, "color": "#FFFFFF", "accent": "#00E5FF", "intro": "slide up", "outline": 0},
        "transition": {"slide": "slide left", "zoom": "zoom in push"},
    },
}

TRIGGERS = {
    "hype": ("hype", "velocity", "boss", "phonk", "sigma", "beast", "car", "sports", "gym", "fight", "edit like", "aggressive", "intense", "arena"),
    "cinematic": ("cinematic", "film", "movie", "travel", "aesthetic", "dreamy", "emotional", "golden hour", "calm", "elegant"),
    "montage": ("montage", "recap", "slideshow", "photo dump", "vlog", "trip", "memories", "highlights", "upbeat"),
    "tour": (
        "property",
        "real estate",
        "realestate",
        "house tour",
        "home tour",
        "apartment",
        "villa",
        "hotel",
        "airbnb",
        "venue",
        "interior",
        "listing",
        "room tour",
        "book a viewing",
    ),
    "talking": (
        "talking",
        "podcast",
        "interview",
        "explain",
        "tutorial",
        "storytime",
        "youtube video",
        "remove silence",
        "pauses",
        "captions",
        "subtitles",
    ),
    "meme": ("meme", "funny", "vine boom", "reaction", "troll", "dramatic zoom"),
    "product": ("product", "ad ", "advert", "showcase", "unboxing", "brand"),
}


# words that say what the video IS (a tour, a product ad, a podcast): they outweigh mood words like "cinematic"
GENRE_WORDS = {
    "tour": TRIGGERS["tour"],
    "product": ("product", "advert", "unboxing", "product ad", "app ad"),
    "talking": ("talking head", "podcast", "interview", "storytime"),
    "meme": ("meme",),
}


def guess(request, brief=None):
    """The style a request implies (the planner may override it)."""
    import re

    text = f"{request} {(brief or {}).get('mood', '')} {(brief or {}).get('pace', '')}".lower()

    def has(w):
        return re.search(r"(?<![a-z])" + re.escape(w.strip()) + r"(?![a-z])", text) is not None

    best, hits = "montage", 0
    for name, words in TRIGGERS.items():
        n = sum(1 for w in words if has(w)) + 2 * sum(1 for w in GENRE_WORDS.get(name, ()) if has(w))
        if n > hits:
            best, hits = name, n
    return best


def describe():
    return "\n".join(f"  {k}: {v['about']}" for k, v in STYLES.items())
