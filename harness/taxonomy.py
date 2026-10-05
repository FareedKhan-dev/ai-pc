"""What KIND of video is being asked for, and how a professional edits that kind.

27 edit types, each with its editing grammar the way an experienced editor would brief a colleague: the structure,
the pacing, the look, the typography, the sound, and what to avoid. classify() reads every signal there is:
  - the request (genre nouns weigh most, mood words less, the platform a little),
  - what the footage shows (the analysis captions: subjects, actions, settings), whether people talk in it, whether a
    narration file was given, how much it moves, how big the faces are,
  - the brief's own vote (the brief model picks an edit type from this list, at no extra cost),
  - a reference edit's measured style when the user gave one ("make it like this").
It returns the best type with a confidence, the runner-ups, and the reasons, in ~1 ms. The designer gets the type's
grammar; the cut engine gets its style. Ambiguous cases (two types close) give the designer both.
"""
import math
import re

# id -> profile. style = the cut engine's style (styles.py); music = generated bed style + tempo range
TYPES = {
    "hype_edit": {
        "label": "Hype / velocity edit", "style": "hype", "aspect": "9:16", "seconds": (15, 60), "music": ("hype", 130, 150),
        "request": ("hype", "velocity", "edit like", "boss", "sigma", "beast mode", "aura", "badass", "epic edit", "fan edit", "anime edit"),
        "footage": ("running", "jumping", "fighting", "walking toward", "posing", "staring", "action"),
        "structure": "hook in 1 s (the strongest frame + a hit) -> short build -> the drop on the best action -> second drop -> hard ending",
        "pacing": "cuts every 2 beats, every beat in the drop; velocity speed ramps (fast-slow-fast) on action; holds only for the hero moment",
        "look": "dark high-contrast grade, crushed blacks, grain, vignette",
        "type": "bold condensed UPPERCASE words slammed one by one on the beat",
        "sound": "phonk or trap 130-150 BPM; impacts, whooshes, riser into the drop, bass drops",
        "avoid": "slow dissolves, long holds, pastel looks, small text",
    },
    "gym_motivation": {
        "label": "Gym / fitness motivation", "style": "hype", "aspect": "9:16", "seconds": (15, 60), "music": ("phonk", 135, 150),
        "request": ("gym", "workout", "fitness", "motivation", "discipline", "grind", "lifting", "bodybuilding", "no excuses", "training"),
        "footage": ("gym", "weights", "dumbbell", "barbell", "lifting", "workout", "exercise", "training", "battle rope", "kettlebell",
                    "muscular", "athlete", "push-up", "squat"),
        "structure": "hook (intense rep + slammed word) -> build -> drop on the heaviest lift -> motivational line -> hard cut ending",
        "pacing": "beat cuts (2 beats, 1 in the drop), velocity ramps on reps, shake + zoom punch on impacts",
        "look": "gritty teal-dark grade, but faces and muscle still readable; grain",
        "type": "heavy condensed or distressed UPPERCASE motivational lines, centre, one at a time",
        "sound": "phonk 135-150 BPM, impacts on reps, bass drops",
        "avoid": "bright pastel looks, soft dissolves, cute fonts",
    },
    "sports_highlights": {
        "label": "Sports highlights", "style": "hype", "aspect": "9:16", "seconds": (20, 90), "music": ("hype", 125, 150),
        "request": ("highlights", "highlight reel", "goal", "match", "game", "football", "soccer", "basketball", "score", "plays", "skate",
                    "tennis", "match day"),
        "footage": ("soccer", "football", "basketball", "ball", "player", "goal", "field", "pitch", "court", "match", "team",
                    "kick", "dribbl", "skateboard", "tennis"),
        "structure": "hook (best play teaser) -> plays building in intensity -> the key play on the drop (freeze + label) -> score card",
        "pacing": "beat cuts, speed ramps into the key moment, freeze frame + zoom on the goal, flashes on big plays",
        "look": "punchy contrast, saturated greens, slight vignette",
        "type": "bold italic sporty labels (GOAL!, player names, score), slammed in",
        "sound": "hype beat, crowd/impact hits on plays, riser into the key play",
        "avoid": "footage of other sports, slow pacing, romantic looks",
    },
    "car_commercial": {
        "label": "Car / automotive spot", "style": "hype", "aspect": "16:9", "seconds": (30, 60), "music": ("epic", 120, 140),
        "request": ("car", "automotive", "vehicle", "sports car", "supercar", "drift", "commercial", "test drive", "unleashed"),
        "footage": ("car", "wheel", "dashboard", "headlight", "road", "highway", "driving", "steering", "engine", "garage", "rims"),
        "structure": "dark dramatic reveal (details in the dark) -> details (slow) -> the drive (fast cuts on the beat) -> hero shot + title -> price/CTA card",
        "pacing": "slow-motion details 2-4 s, then beat cuts while it accelerates; light sweeps and flashes on hits",
        "look": "deep blacks, saturated paint colour, cinematic letterbox optional",
        "type": "wide-spaced bold or metallic title, clean price card",
        "sound": "epic/trailer beat, engine-like risers, impacts on reveals",
        "avoid": "footage of other cars when the ad is for one car, cute fonts, pastel looks",
    },
    "travel_reel": {
        "label": "Travel reel", "style": "montage", "aspect": "9:16", "seconds": (15, 60), "music": ("pop", 110, 128),
        "request": ("travel", "trip", "road trip", "vacation", "holiday", "journey", "adventure", "explore", "destinations", "wanderlust"),
        "footage": ("beach", "coast", "mountain", "road", "landscape", "aerial", "city", "street", "ocean", "lake", "island", "sunset",
                    "boat", "hotel", "temple", "market", "tourist"),
        "structure": "hook (most striking wide shot + title) -> places with name labels -> build -> best moment on the drop -> sunset outro + title",
        "pacing": "1-2 s shots on the beat, 3-4 s holds for hero landscapes; zoom/whip transitions between places",
        "look": "warm golden or vivid teal-orange, light leaks",
        "type": "clean bold place labels (one per place), a big title at the start or end",
        "sound": "upbeat pop/house 110-128 BPM, whooshes on transitions",
        "avoid": "heavy grain, dark grades, long static holds",
    },
    "cinematic_travel": {
        "label": "Cinematic travel / aesthetic film", "style": "cinematic", "aspect": "16:9", "seconds": (45, 180), "music": ("cinematic", 70, 95),
        "request": ("cinematic", "film", "aesthetic", "dreamy", "moody travel", "travel film", "b-roll", "cinematography"),
        "footage": ("landscape", "aerial", "mountain", "forest", "ocean", "city", "sunset", "fog", "street"),
        "structure": "slow opening (wide establishing) -> journey in chapters -> emotional peak on the swell -> quiet ending + title",
        "pacing": "3-6 s shots, slow motion, gentle push-ins, dissolves at chapter changes",
        "look": "film look: soft contrast, teal-orange or warm, letterbox, light grain",
        "type": "small elegant serif or thin sans, wide letter spacing, lower third",
        "sound": "ambient/cinematic score 70-95 BPM, swooshes, nature sound",
        "avoid": "flashes, shakes, fast beat cuts, bold impact text",
    },
    "vlog": {
        "label": "Vlog / day in the life", "style": "montage", "aspect": "9:16", "seconds": (30, 180), "music": ("chill", 90, 115),
        "request": ("vlog", "day in the life", "daily", "routine", "a day with", "my day", "diary", "weekend"),
        "footage": ("talking", "coffee", "room", "walking", "street", "friends", "car interior", "phone", "selfie"),
        "structure": "hook (best moment or line) -> the day in order -> highlight -> sign-off",
        "pacing": "jump cuts on speech, quick b-roll montages on the beat between talking parts",
        "look": "bright natural, slightly warm",
        "type": "casual captions, time stamps or small labels",
        "sound": "chill lo-fi 90-115 BPM ducked under speech",
        "avoid": "heavy effects, dark grades",
    },
    "wedding_film": {
        "label": "Wedding / love story highlight", "style": "cinematic", "aspect": "16:9", "seconds": (45, 240), "music": ("cinematic", 65, 90),
        "request": ("wedding", "bride", "groom", "love story", "engagement", "anniversary", "proposal", "forever", "vows", "romantic"),
        "footage": ("bride", "groom", "wedding", "ring", "dress", "bouquet", "veil", "kiss", "couple", "ceremony", "flowers"),
        "structure": "atmosphere (details, venue) -> the couple -> vows/rings -> emotional peak (kiss/rings) on the swell -> names + date ending",
        "pacing": "slow motion, 3-6 s shots, short soft dissolves (under a second), no hard hits",
        "look": "warm film, soft highlights, gentle grain, letterbox",
        "type": "elegant script or serif for names, thin sans for dates",
        "sound": "romantic piano/strings 65-90 BPM; vows audio when given",
        "avoid": "glitches, shakes, flashes, bold impact fonts, fast beat cuts",
    },
    "event_recap": {
        "label": "Event / party recap", "style": "montage", "aspect": "9:16", "seconds": (15, 60), "music": ("pop", 118, 130),
        "request": ("party", "event", "recap", "festival", "concert", "club", "night out", "celebration", "birthday party", "launch event"),
        "footage": ("party", "crowd", "dancing", "dj", "club", "concert", "lights", "confetti", "stage", "celebrat", "friends"),
        "structure": "hook (crowd energy) -> build -> the drop with the event title -> best moments -> see-you-next-time ending",
        "pacing": "cuts on every beat or two, flashes and colour hits on bars, speed ramps on dance moves",
        "look": "colourful neon, saturated, light leaks",
        "type": "bold rounded or neon titles at the drop, short CTA at the end",
        "sound": "house/dance 118-130 BPM, risers and drops",
        "avoid": "slow dissolves, desaturated looks, strobing",
    },
    "real_estate_tour": {
        "label": "Property / venue tour", "style": "tour", "aspect": "16:9", "seconds": (30, 120), "music": ("cinematic", 75, 95),
        "request": ("property", "real estate", "house tour", "home tour", "listing", "apartment", "villa", "airbnb", "hotel", "venue",
                    "interior", "book a viewing", "for sale", "for rent"),
        "footage": ("house", "living room", "kitchen", "bedroom", "bathroom", "pool", "interior", "apartment", "villa", "garden",
                    "terrace", "building", "room"),
        "structure": "exterior hero + title -> natural walk-through, area by area with labels -> best feature -> exterior + contact card",
        "pacing": "3-5 s slow glides and push-ins, soft dissolves, no hard hits",
        "look": "bright, clean, airy, true colours; no grain or vignette",
        "type": "elegant thin serif or clean sans area labels, lower third; price/contact card",
        "sound": "calm elegant music 75-95 BPM",
        "avoid": "glitches, shakes, dark or vintage looks, labels for rooms the footage does not show",
    },
    "product_ad": {
        "label": "Product ad / showcase", "style": "product", "aspect": "9:16", "seconds": (15, 45), "music": ("pop", 105, 125),
        "request": ("product", "ad", "advert", "advertisement", "showcase", "launch", "brand", "shop", "buy now", "sale", "promo"),
        "footage": ("product", "bottle", "package", "box", "hands holding", "packshot", "close-up", "cosmetic", "shoe", "watch"),
        "structure": "hook (problem or striking packshot) -> the product reveal on the drop -> 2-3 feature callouts -> logo/offer/CTA",
        "pacing": "clean cuts on the beat, slow push-ins on details, slide transitions between features",
        "look": "bright, clean, crisp, brand colours",
        "type": "clean modern sans callouts, one idea per line, CTA at the end",
        "sound": "upbeat modern pop 105-125 BPM, swooshes, clicks",
        "avoid": "grain, dark looks, cluttered text",
    },
    "tech_promo": {
        "label": "App / tech promo", "style": "product", "aspect": "16:9", "seconds": (15, 60), "music": ("pop", 110, 128),
        "request": ("app", "software", "saas", "tech", "technology", "smart", "ai", "startup", "download now", "platform", "dashboard"),
        "footage": ("phone", "smartphone", "laptop", "screen", "typing", "computer", "code", "interface", "tablet", "device", "headphones"),
        "structure": "hook (the problem/feeling) -> the app on screen -> feature callouts (one per beat group) -> CTA card (download)",
        "pacing": "beat cuts, glitch or slide transitions, push-ins on screens",
        "look": "cool clean blue-teal or brand colours, crisp",
        "type": "modern geometric sans, feature words with a glitch or typing intro",
        "sound": "electronic/pop 110-128 BPM, UI clicks, glitch hits",
        "avoid": "vintage film looks, romantic fonts",
    },
    "unboxing_review": {
        "label": "Unboxing / review", "style": "talking", "aspect": "9:16", "seconds": (30, 120), "music": ("chill", 95, 115),
        "request": ("unboxing", "review", "unbox", "first impressions", "honest review", "worth it", "haul"),
        "footage": ("box", "package", "hands", "opening", "product", "table"),
        "structure": "hook (the verdict or the product) -> unboxing details -> what is good / bad -> verdict + CTA",
        "pacing": "jump cuts on speech, close-up b-roll of details on keywords",
        "look": "bright clean",
        "type": "captions with emphasis words, pros/cons labels",
        "sound": "light background music under the voice, pops on emphasis",
        "avoid": "heavy effects over the product",
    },
    "recipe": {
        "label": "Recipe / cooking", "style": "montage", "aspect": "9:16", "seconds": (30, 60), "music": ("chill", 90, 110),
        "request": ("recipe", "cooking", "food", "dish", "how to make", "kitchen", "bake", "meal", "chef", "stir fry"),
        "footage": ("cooking", "pan", "frying", "chopping", "kitchen", "food", "dish", "vegetables", "sauce", "plate", "oven", "dough",
                    "stove", "meat", "egg"),
        "structure": "hook (the finished dish or the sizzle) -> steps in order with STEP labels -> plating -> dish + title",
        "pacing": "1-3 s shots, slow-motion pours and sizzles, zoom on textures",
        "look": "warm, appetising, saturated food colours",
        "type": "friendly rounded or clean bold step labels; dish title at the end",
        "sound": "cozy acoustic/lo-fi 90-110 BPM, sizzle/chop sounds kept",
        "avoid": "cold or dark grades, glitches",
    },
    "fashion_lookbook": {
        "label": "Fashion / lookbook / outfits", "style": "montage", "aspect": "9:16", "seconds": (15, 45), "music": ("pop", 115, 128),
        "request": ("fashion", "outfit", "lookbook", "ootd", "style", "clothing", "collection", "runway", "grwm", "get ready"),
        "footage": ("dress", "outfit", "model", "posing", "clothes", "jacket", "shoes", "mirror", "walking"),
        "structure": "hook (best look) -> outfit changes on the beat -> details -> brand/CTA",
        "pacing": "cut on every beat for outfit changes, flash or slide transitions, slow-mo walks",
        "look": "clean editorial, high-key or moody depending on the brand",
        "type": "minimal fashion serif or wide sans, small",
        "sound": "house/pop 115-128 BPM",
        "avoid": "clutter, cartoon effects",
    },
    "talking_head": {
        "label": "Talking head / YouTube / explainer", "style": "talking", "aspect": "16:9", "seconds": (30, 600), "music": ("chill", 85, 110),
        "request": ("talking head", "youtube video", "explainer", "commentary", "storytime", "my story", "explain", "remove pauses",
                    "remove silence", "captions", "subtitles", "jump cuts"),
        "footage": ("talking", "speaking", "facing the camera", "person sitting", "interview", "presenter"),
        "structure": "hook line first -> the points in order -> payoff -> CTA",
        "pacing": "pauses cut out (jump cuts), punch-in on every other cut, b-roll on nouns",
        "look": "natural, clean skin tones",
        "type": "bold captions in 2-4 word chunks, emphasis words coloured",
        "sound": "quiet music ducked under speech, pops on emphasis",
        "avoid": "music louder than speech, effects over the face",
    },
    "podcast_clip": {
        "label": "Podcast / interview clip", "style": "talking", "aspect": "9:16", "seconds": (20, 90), "music": None,
        "request": ("podcast", "interview", "clip from", "episode", "conversation", "guest", "quote"),
        "footage": ("microphone", "podcast", "two people talking", "interview", "studio", "headphones"),
        "structure": "the strongest quote first -> context -> the point -> follow CTA",
        "pacing": "cut on speaker changes, punch-ins on key lines, no dead air",
        "look": "natural studio look",
        "type": "large bold karaoke-style captions, speaker names as labels",
        "sound": "the voices only (or very low music)",
        "avoid": "flashy transitions, effects",
    },
    "tutorial": {
        "label": "Tutorial / how-to", "style": "product", "aspect": "16:9", "seconds": (30, 300), "music": ("chill", 90, 110),
        "request": ("tutorial", "how to", "how-to", "step by step", "guide", "learn", "tips", "explained", "walkthrough"),
        "footage": ("screen", "hands", "demonstrating", "pointing", "tool", "laptop", "whiteboard"),
        "structure": "what you will learn -> steps with numbers -> result -> recap",
        "pacing": "steady, zoom in on details, no fast cuts",
        "look": "clean bright",
        "type": "numbered step labels and callouts, captions",
        "sound": "light background under the voice",
        "avoid": "flashy effects that hide details",
    },
    "documentary": {
        "label": "Documentary / narrated story", "style": "cinematic", "aspect": "16:9", "seconds": (30, 600), "music": ("cinematic", 65, 90),
        "request": ("documentary", "narration", "narrated", "voiceover", "voice over", "story of", "history", "teaser", "explainer film"),
        "footage": ("landscape", "nature", "animal", "city", "archive", "people", "forest", "river"),
        "structure": "atmospheric opening + title -> narration-led chapters with shots matching the words -> reflective ending",
        "pacing": "3-7 s shots following the narration, slow pushes, dissolves at chapter changes",
        "look": "natural cinematic, letterbox optional",
        "type": "small clean subtitles at the bottom, elegant title",
        "sound": "narration first; soft score ducked under it",
        "avoid": "flashes, beat cuts, loud music under the voice",
    },
    "meme_reaction": {
        "label": "Meme / reaction / funny", "style": "meme", "aspect": "9:16", "seconds": (5, 30), "music": None,
        "request": ("meme", "funny", "reaction", "vine boom", "troll", "comedy", "prank", "dramatic zoom", "lol"),
        "footage": ("face", "reaction", "surprised", "laughing", "cat", "dog", "pet"),
        "structure": "setup -> the beat -> punchline (zoom + boom + freeze) -> tag",
        "pacing": "comedic timing: holds before the punch, sudden punch zooms",
        "look": "as shot; flashes or deep-fry only as a joke",
        "type": "Impact-style white text with black outline, top/bottom",
        "sound": "vine boom, record scratch, silence before the punch",
        "avoid": "cinematic grading, slow dissolves",
    },
    "music_video": {
        "label": "Music video / lyric edit", "style": "hype", "aspect": "9:16", "seconds": (15, 240), "music": None,
        "request": ("music video", "lyric", "lyrics", "song", "singing", "performance", "rap video", "cover"),
        "footage": ("singing", "microphone", "stage", "performing", "guitar", "rapper", "band"),
        "structure": "follows the song: verse/chorus sections, the chorus gets the strongest shots",
        "pacing": "cuts locked to the song's beats and phrases",
        "look": "stylised to the song's mood",
        "type": "lyric lines timed to the words (when lyrics are given)",
        "sound": "the song itself",
        "avoid": "talking over the song",
    },
    "gaming_montage": {
        "label": "Gaming montage", "style": "hype", "aspect": "16:9", "seconds": (15, 90), "music": ("hype", 140, 160),
        "request": ("gaming", "video game", "gaming clips", "game clips", "kills", "fortnite", "valorant", "minecraft", "gameplay",
                    "clutch", "cod", "pubg", "headshot"),
        "footage": ("gameplay", "game", "screen", "hud", "character", "weapon"),
        "structure": "best clip tease -> clips building -> the clutch on the drop -> outro",
        "pacing": "kills on the beat, zoom punches, shakes, speed ramps",
        "look": "saturated, RGB/glitch accents",
        "type": "bold gamer fonts, kill counters",
        "sound": "trap/dubstep 140-160 BPM, impacts",
        "avoid": "slow pacing",
    },
    "memories_slideshow": {
        "label": "Memories / photo slideshow", "style": "montage", "aspect": "9:16", "seconds": (15, 90), "music": ("chill", 80, 105),
        "request": ("memories", "slideshow", "photo dump", "photos", "throwback", "recap of the year", "year in review", "remember"),
        "footage": ("photo", "selfie", "group", "friends", "family"),
        "structure": "soft opening -> moments in time order -> the most emotional moment -> closing line",
        "pacing": "2-3 s per photo, ken burns on every photo, soft transitions",
        "look": "warm nostalgic, light leaks",
        "type": "handwritten or soft serif dates and captions",
        "sound": "nostalgic chill music",
        "avoid": "hard hits, glitches",
    },
    "trailer_teaser": {
        "label": "Trailer / teaser", "style": "cinematic", "aspect": "16:9", "seconds": (20, 90), "music": ("epic", 80, 110),
        "request": ("trailer", "teaser", "coming soon", "announcement", "premiere", "launching soon"),
        "footage": (),
        "structure": "quiet open -> rising tension with title cards -> fast montage on the swell -> black -> title + date",
        "pacing": "slow then accelerating; hits on title cards; a beat of black before the title",
        "look": "dark cinematic, letterbox",
        "type": "wide-spaced uppercase serif or bold sans title cards",
        "sound": "trailer score: braams, risers, impacts, silence before the title",
        "avoid": "cute fonts, constant music without dynamics",
    },
    "transformation": {
        "label": "Before / after / transformation", "style": "montage", "aspect": "9:16", "seconds": (10, 45), "music": ("hype", 120, 140),
        "request": ("before and after", "before after", "transformation", "glow up", "makeover", "renovation", "progress"),
        "footage": ("before", "after", "renovation", "makeup"),
        "structure": "the before (slow) -> the build -> the after revealed on the drop -> hold on the result",
        "pacing": "slow before, a riser, hard reveal on the drop",
        "look": "before slightly flat, after vivid",
        "type": "BEFORE / AFTER labels",
        "sound": "riser into a drop at the reveal",
        "avoid": "showing the after early",
    },
    "kids_family": {
        "label": "Kids / family / pets", "style": "montage", "aspect": "9:16", "seconds": (15, 60), "music": ("pop", 100, 120),
        "request": ("kids", "baby", "family", "children", "birthday", "pet", "puppy", "kitten", "toddler"),
        "footage": ("child", "baby", "kid", "family", "dog", "cat", "puppy", "playing", "toy"),
        "structure": "cute hook -> playful moments -> the sweetest moment -> warm ending",
        "pacing": "playful beat cuts, bouncy zooms",
        "look": "bright warm, soft",
        "type": "rounded playful fonts, emoji-like labels",
        "sound": "playful pop/ukulele",
        "avoid": "dark grades, aggressive effects",
    },
    "nature_ambient": {
        "label": "Nature / ambient / relaxing", "style": "cinematic", "aspect": "16:9", "seconds": (30, 300), "music": ("cinematic", 60, 85),
        "request": ("nature", "relaxing", "calm", "ambient", "peaceful", "meditation", "wildlife", "scenery", "asmr"),
        "footage": ("forest", "waterfall", "river", "lake", "mountain", "flowers", "trees", "animal", "bird", "sky", "clouds", "field"),
        "structure": "slow fade in -> a calm journey through the scenes -> a gentle peak -> slow fade out",
        "pacing": "5-8 s shots, slow push-ins, long soft dissolves",
        "look": "natural lush colours, soft contrast",
        "type": "minimal thin text or none",
        "sound": "ambient pads, nature sound",
        "avoid": "flashes, shakes, beat cuts, bold text",
    },
}

SHORT_FORM = ("tiktok", "reels", "reel", "shorts", "instagram", "story", "stories")
# words that say the format or a mood, not the genre: they lean a little, they never decide
WEAK = {"film", "video", "edit", "reel", "clips", "cinematic", "aesthetic", "montage", "highlights", "highlight", "commercial",
        "style", "calm", "smart", "game", "match", "explain", "captions", "subtitles", "story of", "teaser", "ad", "promo"}
LONG_FORM = ("youtube video", "16:9", "landscape", "documentary", "film")
FAST_TYPES = {"hype_edit", "gym_motivation", "sports_highlights", "event_recap", "gaming_montage", "fashion_lookbook", "music_video"}
SLOW_TYPES = {"cinematic_travel", "wedding_film", "real_estate_tour", "documentary", "nature_ambient", "memories_slideshow"}
TALK_TYPES = {"talking_head", "podcast_clip", "vlog", "unboxing_review", "tutorial"}


def _has(text, w):
    return re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) is not None


def _footage_text(a):
    return " ".join([str(a.get("file", "")).replace("-", " ").replace("_", " "), str(a.get("summary") or "")] +
                    [f"{m.get('subject') or ''} {m.get('action') or ''} {m.get('setting') or ''}" for m in a.get("moments", [])]).lower()


def classify(request, analyses=None, brief=None, reference=None):
    """{"type", "label", "confidence", "alternatives": [(type, p)], "reasons": [...], "profile": {...}}"""
    req = " ".join(str(request or "").lower().split())
    analyses = analyses or {}
    vids = [a for a in analyses.values() if a.get("kind") in ("video", "image")]
    auds = [a for a in analyses.values() if a.get("kind") == "audio"]
    score, why = {t: 0.0 for t in TYPES}, {t: [] for t in TYPES}

    for t, p in TYPES.items():  # 1. the request: genre words weigh most, format words ("film", "reel") little
        hits = [w for w in p["request"] if _has(req, w)]
        if hits:
            strong = [w for w in hits if w not in WEAK]
            score[t] += 3.0 * min(2, len(strong)) + 0.8 * min(2, len(hits) - len(strong))
            why[t].append("request says " + ", ".join(f"'{w}'" for w in hits[:3]))

    if vids:  # 2. what the footage shows (captions), how much of the footage shows it
        texts = [_footage_text(a) for a in vids]
        for t, p in TYPES.items():
            if not p["footage"]:
                continue
            per = [sum(1 for w in p["footage"] if _has(x, w)) for x in texts]
            share = sum(1 for n in per if n) / len(texts)
            if share:
                score[t] += 2.5 * share + 0.4 * min(4, sum(per)) / 4
                words = [w for w in p["footage"] if any(_has(x, w) for x in texts)][:4]
                why[t].append(f"footage shows {', '.join(words)} ({share * 100:.0f}% of the files)")
        speech = [a for a in vids if (a.get("sound") or {}).get("kind") == "speech"]
        if speech:
            for t in TALK_TYPES:
                score[t] += 2.0 * len(speech) / len(vids)
                why[t].append(f"{len(speech)} clip(s) with people talking")
        motion = [str(a.get("motion") or "") for a in vids]
        hi = sum(1 for m in motion if m in ("high", "medium")) / len(vids)
        if hi > 0.5:
            for t in FAST_TYPES:
                score[t] += 0.6
        elif hi < 0.2:
            for t in SLOW_TYPES:
                score[t] += 0.6
    narration = [a for a in auds if (a.get("sound") or {}).get("kind") == "speech" or (a.get("sound") or {}).get("syllabic", 0) > 0.4]
    if narration and not any((a.get("sound") or {}).get("kind") == "speech" for a in vids):
        score["documentary"] += 3.0
        why["documentary"].append("a narration track was given")
    if any((a.get("sound") or {}).get("kind") == "music" for a in auds):
        score["music_video"] += 0.5 if _has(req, "song") or _has(req, "lyrics") else 0.0

    short = any(_has(req, w) for w in SHORT_FORM)  # 3. the platform, a little
    longf = any(_has(req, w) for w in LONG_FORM)
    for t, p in TYPES.items():
        if short and p["aspect"] == "9:16" or longf and p["aspect"] == "16:9":
            score[t] += 0.3

    vote = (brief or {}).get("edit_type")  # 4. the brief model's own reading
    if vote in TYPES:
        score[vote] += 3.0
        why[vote].append("the brief reads it as this type")

    if reference:  # 5. a reference edit's measured rhythm
        cpm = float(reference.get("cuts_per_min") or 0)
        if reference.get("speech"):
            for t in TALK_TYPES:
                score[t] += 1.5
        elif cpm >= 35:
            for t in FAST_TYPES:
                score[t] += 1.5
                why[t].append(f"the reference cuts fast ({cpm:.0f} cuts/min)")
        elif cpm and cpm <= 14:
            for t in SLOW_TYPES:
                score[t] += 1.5
                why[t].append(f"the reference cuts slowly ({cpm:.0f} cuts/min)")

    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    z = [math.exp(s / 0.8) for _, s in ranked]  # sharp enough that a clear lead reads as confident among 27 types
    tot = sum(z) or 1.0
    probs = [(t, round(v / tot, 3)) for (t, _), v in zip(ranked, z)]
    best = probs[0][0]
    if ranked[0][1] <= 0.5:  # nothing points anywhere: a general montage, said honestly
        best = "travel_reel" if any(_has(" ".join(_footage_text(a) for a in vids), w) for w in ("beach", "mountain", "road")) else "event_recap"
        why[best].append("no clear signal: a general upbeat montage")
    return {"type": best, "label": TYPES[best]["label"], "confidence": dict(probs).get(best, 0.0),
            "alternatives": [x for x in probs[1:4] if x[1] >= 0.05], "reasons": why[best], "profile": TYPES[best],
            "scores": {t: round(s, 2) for t, s in ranked[:6]}}


def brief_list():
    """The type ids with their labels, for the brief prompt (the brief model votes for one)."""
    return ", ".join(f"{t} ({p['label']})" for t, p in TYPES.items())


def design_block(cls):
    """The designer's sheet for the chosen type (and a close runner-up)."""
    p = cls["profile"]
    alt = [f"{TYPES[t]['label']} {pr * 100:.0f}%" for t, pr in cls["alternatives"] if pr >= 0.15]
    lines = [f"EDIT TYPE: {p['label']} ({cls['confidence'] * 100:.0f}% sure" + (f"; also possible: {', '.join(alt)}" if alt else "") + ")",
             f"  why: {'; '.join(cls['reasons'][:3]) or 'general signals'}",
             f"  structure: {p['structure']}", f"  pacing: {p['pacing']}", f"  look: {p['look']}", f"  type: {p['type']}",
             f"  sound: {p['sound']}", f"  avoid: {p['avoid']}",
             f"  default style: {p['style']}; typical {p['seconds'][0]}-{p['seconds'][1]} s on {p['aspect']}"
             + (f"; music {p['music'][0]} {p['music'][1]}-{p['music'][2]} BPM" if p.get("music") else "; no music bed (voices / the song carry it)")]
    return "\n".join(lines)
