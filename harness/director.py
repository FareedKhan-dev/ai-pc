"""Director: a request in plain words -> an edit plan (schema v2, see editplan.py). Two model calls, no code execution.

1. BRIEF  (fast model, ~1-2 s, runs while the media is being analysed): platform, length, mood, the story in beats,
          and every visual/audio idea as a "need" with the catalogue kinds to search and English search words.
2. SEARCH (knowledge base, milliseconds): the best free catalogue items for every need, plus a style palette
          (transitions, title fonts and animations, colour looks) matching the mood.
3. AWARE  (milliseconds): what is possible here for every need (awareness.py) and lessons from earlier runs.
4. PLAN   (video model, ~8-20 s): a short editor's treatment and requirement map ("think"), then the full plan from
          the request, the brief, what is in each file (analyze.describe), the awareness sheet and the candidate items.
          Only candidate names and real files can survive the resolver afterwards.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from . import analyze as AN
from . import frames as F
from .editplan import PLATFORMS, Catalog
from . import taxonomy as TX
from .util import parse_json

KINDS = ("scene_effect", "character_effect", "filter", "transition", "clip_intro", "clip_outro", "clip_combo", "text_intro",
         "text_outro", "text_loop", "font", "audio_effect", "voice", "speech_to_song")

BRIEF_SYSTEM = """You are an assistant editor. Turn a video-editing request into a brief for the lead editor.
Reply with ONE JSON object:
{"platform": "instagram_reels|tiktok|youtube_shorts|instagram_feed|youtube|square|none",
 "target_seconds": <number: what was asked, else what suits the platform and the footage>,
 "mood": "<3-6 words>", "pace": "slow|medium|fast",
 "story": ["<beat 1: what the viewer sees>", "<beat 2>", "..."],
 "needs": [{"id": "n1", "what": "<one visual or audio idea>", "kinds": ["<KINDS>"], "query": "<English search words>", "when": "<which beat>",
            "target": "eyes|face|head|body|hands|none"}],
 "texts": [{"text": "<on-screen words>", "role": "title|caption|label|call to action"}],
 "music": "<the sound the edit needs, or 'none'>", "keep_original_sound": true|false,
 "edit_type": "<the ONE edit type below that this request is>"}
EDIT TYPES: %s
KINDS: scene_effect (full-frame: light, glitch, flash, shake, weather, retro, particles...), character_effect (follows a
person: face, eyes, body, outline), filter (colour look), transition (between clips), clip_intro, clip_outro, clip_combo
(clip animations), text_intro, text_outro, text_loop (text animations), font, audio_effect, voice (voice changer),
speech_to_song. Camera shake, zoom punches, slow motion / speed ramps, freeze frames, reverse, reframing, green-screen
removal, masks and blend modes are built in: list them as needs with "kinds": [].
"target": the body part an effect must sit on when the request names one ("lightning on my eyes" -> eyes), else none.
List EVERY idea in the request (nothing may be lost), plus what a professional editor would add for this mood (a
transition style, a title look and animation, a colour look). Queries: concrete visual words and synonyms
("lightning electric spark glow eyes"), not the user's sentence. Only use files that exist; no other text."""

PLAN_SYSTEM = """You are a professional video editor working in JianYing (CapCut's Chinese edition). You never write code:
you output ONE JSON object, the edit plan, which is checked and built automatically.

PLAN FORMAT (all times in seconds):
{"think": {                           FIRST think like a senior editor (short phrases):
   "concept": "<the feel and the story in one line>", "hook": "<what grabs the viewer in the first 1.5 s>",
   "arc": ["<time range: beat>", ...], "climax": "<time: what>", "pacing": "<cut rhythm>",
   "look": "<colour, texture, typography>", "sound": "<sound design>",
   "requirements": [{"ask": "<every thing the client asked, in their words>", "how": "<the technique you use>",
                     "edits": ["<ids of the clips/edits that deliver it>"], "confidence": "high|medium|low",
                     "fallback": "<what to use instead if it does not show>"}]},
 "name": "<short_name>", "platform": "<from the brief>", "canvas": "9:16|16:9|1:1|4:5",
 "beat_sync": false,                  true = move cuts onto the beats of the first music track
 "clips": [ MAIN TRACK, played back to back in this order; each clip is one continuous part of a file
   {"id": "c1", "file": "<MEDIA file>", "from": <start in the file>, "duration": <seconds on the timeline>,
    "speed": 1.0,                     0.1-10; or a speed ramp: "ramp": [[<s of the FILE after 'from'>, <speed>], ...] (each speed holds until
                                      the next point; the last one continues) and "duration" = the clip's length on the timeline
    "reverse": false, "freeze": <time in the file to hold as a still for 'duration'>,
    "reframe": "subject"|"center"|"fit"|{"x": 0-1, "y": 0-1, "zoom": 1-3},   default subject = keep the main face in view
    "volume": 1.0, "fade_in": 0, "fade_out": 0,
    "chroma": "auto",                 removes a green/blue screen (MEDIA says when a file has one)
    "background": "blur"|"#RRGGBB"|{"blur": "light|medium|strong|max"},   fills the canvas around the clip and behind a removed screen
    "mask": {"type": "circle|rectangle|heart|star|linear|mirror", "x": 0-1, "y": 0-1, "size": 0-1, "feather": 0-100, "invert": false},
    "blend": "screen|multiply|overlay|soft light|hard light|lighten|darken|color dodge|color burn|linear burn",
    "opacity": 1.0, "flip": "h"|"v", "rotation": 0, "crop": {"left": 0, "right": 0, "top": 0, "bottom": 0},
    "stretch": [1, 1] (x, y factors: squash / stretch), "pitch_with_speed": false (true: sped-up sound gets higher)}],
 "layers": [ OVERLAYS above the main track: the clip fields plus "at": <timeline start>, "scale": 0.05-10, "position": [x, y] (-1..1, 0,0 = centre, y up) ],
 "edits": [ everything else; each edit has a unique "id" and an "expect": what a viewer sees or hears at that moment if it worked
   {"id", "type": "transition", "after": "<clip id>", "name": "<TRANSITION>", "duration": 0.3-1.5, "expect"},
   {"id", "type": "effect", "name": "<SCENE or CHARACTER EFFECT (type is always "effect")>", "on": "<clip id>" (optional), "start", "duration", "params": {"<param>": 0-100}, "over_text": false, "expect"},
   {"id", "type": "filter", "name": "<FILTER>", "on": "<clip id>" (optional), "start", "duration", "strength": 0-100, "expect"},
   {"id", "type": "animation", "on": "<clip, layer or text id>", "kind": "intro|outro|combo|loop", "name": "<CLIP or TEXT ANIMATION>", "duration", "expect"},
   {"id", "type": "shake", "on": "<clip id>", "start", "duration": 0.2-1.5, "strength": 0-1, "expect"},
   {"id", "type": "zoom", "on": "<clip id>", "start", "duration", "to": 1.1-2.0, "back": true (punch in, then settle) | false (slow push), "expect"},
   {"id", "type": "keyframes", "on": "<clip, layer or text id>", "property": "scale|x|y|rotation|opacity|brightness|contrast|saturation|volume",
    "points": [[<s into the item>, <value>], ...], "expect"}   scale multiplies the framing; x/y add (canvas units); brightness/contrast/saturation -1..1; opacity 0-1; volume multiplies
   {"id", "type": "text", "text": "...", "start", "duration", "position": "top|upper|center|lower|bottom" or [x, y], "font": "<FONT>", "size": 6-30,
    "color": "#FFFFFF", "bold": true, "outline": {"color": "#000000", "width": 0-100}, "shadow": true, "background": {"color": "#000000", "alpha": 0.5},
    "intro": "<TEXT INTRO>", "outro": "<TEXT OUTRO>", "loop": "<TEXT LOOP>", "vertical": false, "max_width": 0.82, "expect"},
   {"id", "type": "captions", "lines": [{"start", "end", "text"}], "position": "lower", "size": 7, "font": "<FONT>", "intro": "<TEXT INTRO>", "expect"},
   {"id", "type": "audio", "file": "<MEDIA sound file>", "at": <timeline start>, "from": <start in the file>, "duration", "volume": 0-2,
    "fade_in", "fade_out", "effect": "<AUDIO EFFECT | VOICE | SPEECH TO SONG>", "keyframes": [[<s>, <volume factor>]], "duck_under_speech": false, "expect"},
   {"id", "type": "sfx", "sound": "impact|hit|whoosh|swoosh|riser|sub_drop|thunder|glitch", "at": <timeline s of the moment>, "volume": 0.4-1.5, "expect"}]}
   (sfx are synthesised here, always available; a riser ENDS at "at", every other sound starts there)
"start" and "duration" are seconds on the final timeline; with "on": <clip id> they count from that clip's start, and
the duration defaults to the rest of the clip.

RULES
- Read RUNTIME AWARENESS first: build on DIRECT and BUILT-IN options; for APPROXIMATE needs use the best substitute and say
  so in "how"; never plan what is NOT POSSIBLE (use its "instead"). Follow the lessons from earlier runs.
- Effect, filter, transition, animation, font and sound-effect names: copy them EXACTLY from CANDIDATES. Files: only MEDIA.
  Items marked (proven) rendered correctly in earlier exports here: prefer them when they fit as well.
- Keep "from" + duration x speed inside each file. Use the MEDIA notes (shots, faces, motion, highlights, sound) to pick
  WHICH part of a file shows each beat of the story.
- When the request names a body part ("my eyes", "his face", "hands"), use a candidate whose target is that part (the
  [target ...] tag); add a second, broader effect (around the person / full frame) only as support.
- Character effects need a clear person: put them where MEDIA shows a face (eyes visible for eye effects); if the face
  is small, add a zoom on that clip.
- Effects marked moves_image already move the picture: no shake on top of them. At most two effects at the same moment.
- Impact moment = shake + zoom punch + a flash (transition or effect) together, on a hit or beat if there is music.
- Slow motion (0.3-0.5x via ramp) for entrances and hero moments; normal speed or faster around them.
- Sound design (use sfx even without music): impact or hit on every impact moment (with its shake / zoom punch), whoosh
  or swoosh on fast transitions, a riser ending on the climax, thunder with lightning, glitch with glitch effects.
- Titles: 2-6 words, size 12-18 on 9:16 (8-12 on 16:9), a bold font, outline or shadow, an intro animation, >= 1.2 s.
- Start strong (a hook in the first 1.5 s) and hit the target length: the clips' durations add up to the video length;
  every text and effect must fall inside it. Every idea in the brief must appear in the plan.
- Each "expect" says what THAT item really does (from its candidate description), concrete and checkable in one frame
  or a short window ("red glowing flare from the man's eye", "white flash between the two clips", "the title THE BOSS IS
  HERE pops in at the top").
Output compact JSON only, no comments."""


DESIGN_SYSTEM = """You are a senior short-form and YouTube editor. You DESIGN the edit; code then cuts it on the beat and
writes every keyframe, so you choose and never compute. Output ONE JSON object:
{"think": {"concept": "<feel + story, one line>", "hook": "<first 1.5 s>", "arc": ["<section: beat>"], "climax": "<what, which shot>",
           "pacing": "<cut rhythm>", "look": "<grade, texture, typography>", "sound": "<music + sound design>",
           "requirements": [{"ask": "<each thing the client asked, in their words>", "how": "<technique>",
                             "edits": ["<shot ids, edit ids or recipe names that deliver it>"], "confidence": "high|medium|low",
                             "fallback": "<plan B>"}]},
 "name": "<short_name>", "platform": "<from the brief>", "canvas": "9:16|16:9|1:1|4:5",
 "style": "<STYLE>",
 "music": {"generate": "hype|phonk|epic|pop|chill|cinematic", "bpm": <70-160>} | {"file": "<MEDIA audio>", "from": <s>} | "none",
 "shots": [ in timeline order
   {"id": "s1", "section": "intro|verse|build|drop|break|outro", "label": "<optional on-screen label: a step, room, place, score, feature>",
    "file": "<MEDIA video or photo>", "around": <time in the file of the key
    moment, or null = let the cut engine pick the best moment>, "beats": <1-8, how long on the beat grid>,
    "speed": "normal|slow|fast|velocity|freeze", "want": "<what this shot must show>", "hold": true (optional: keep it whole, a hero moment),
    "reframe": "subject|center" (optional), "chroma": "auto" (only for green-screen files), "background": "#RRGGBB" (behind a removed screen)}
   or a FILL shot for a run of quick cuts: {"id": "f1", "section": "drop", "fill": <beats>, "files": ["<MEDIA>", ...], "want": "..."}
   (the code cuts that many beats at the style's pace from those files, never repeating a moment)],
 "voiceover": {"file": "<MEDIA audio with narration>", "from": <s>, "duration": <s>, "captions": "minimal|bold_pop|none"}
            (documentaries / faceless explainers: narration over the shots, subtitles, music ducked under it),
 "speech": {"file": "<MEDIA video with someone talking>", "cut_pauses": true, "max_pause": 0.35, "drop_fillers": true,
            "captions": "bold_pop|minimal|none", "emphasis": ["<spoken words to colour and zoom on>"],
            "broll": [{"word": "<a spoken word>", "file": "<MEDIA>", "around": <s in that file>, "seconds": 1.5}]}
            (talking-head / YouTube / podcast edits: the shots are cut from the speech automatically; leave "shots" empty),
 "recipes": [ the style's default recipes run automatically; list one only to change it ({"use": "zoom_punch", "strength": 1.2}),
              switch it off ({"use": "flash", "off": true}) or add one ({"use": "kinetic_title", "text": "...", "at": "drop"}) ],
 "edits": [ hand-placed extras in the edit format below, "on": "<shot id>" (e.g. the eye effect on the close-up shot) ]}

STYLES (pick the one the request implies; they set pacing, default recipes, transitions, type, grade and music):
%s

RECIPES (params in brackets):
  zoom_punch [on: beats|downbeats|drop, every, sections, strength 1.05-1.4, blur]   shake [on, every, sections, strength 0-1]
  flash [on: drop|downbeats|beats, every, sections]   rgb_hit [on, every, sections]   ken_burns [amount 1.03-1.15]
  transitions [family: flash|zoom|whip|glitch|dissolve|blur|slide, at: sections|every, every: N, duration]
  grade [look: words for the colour look, grain, vignette, letterbox, light_leak]   hook [text, duration]
  kinetic_title [text (2-6 words), at: drop|start|end|<s>]: word by word on the beat, the last word slammed
  captions [lines: [{"start","end","text"}], position]   sfx [transitions: whoosh|swoosh, drop: true, words: hit]
  jump_zoom [amount] (talking heads)   face_punch [strength] (memes)

EDIT FORMAT for extras. Never absolute seconds: the code decides the final timeline. Place an extra "on": "<shot id>"
("start"/"duration" = seconds from that shot's start) or "at": "drop" | "end" | "<shot id>". Text "size": 8-20 on 9:16,
6-14 on 16:9 (a shot "label" is already a text: never add a text extra with the same words).
  {"id", "type": "effect", "name": "<SCENE or CHARACTER EFFECT from CANDIDATES>", "on": "<shot id>", "start", "duration", "params": {"<param>": 0-100}, "expect"}
  {"id", "type": "text", "text": "...", "start", "duration", "position": "top|upper|center|lower|bottom", "size", "font", "color", "intro", "expect"}
  {"id", "type": "sfx", "sound": "impact|hit|whoosh|swoosh|riser|sub_drop|thunder|glitch", "at": "drop|end|<shot id>" or "on" + "start", "expect"}
  (zoom, shake, keyframes, filter, transition, animation, audio: as usual)

TIMING: one beat = 60/bpm seconds (140 BPM = 0.43 s, 118 = 0.51 s, 84 = 0.71 s). A shot lasts "beats" beats; the video is
the sum of the shots; the first "drop" shot starts the climax and the music's drop is put exactly there.
LONG EDITS (~1 minute): give the edit a shape with several sections, e.g. intro (8 beats) -> verse -> build -> drop ->
break -> build -> drop -> outro; the music is generated to follow exactly those sections. Use EVERY file at least once,
the best ones several times at different moments. Cover the FULL target length (beats x beat length, e.g. 60 s at
140 BPM = 140 beats): hand-pick the key shots (hook, labels, hero moments, the climax, the ending) and use FILL shots for
the runs of quick cuts in between. The code then fine-tunes the length to the second.
GENRE HINTS: recipe = steps in order with labels ("STEP 1 · ..."); property tour = style "tour" (bright, clean, no grain
or vignette), areas in a natural walk-through order with area labels; travel = arrival -> places (labels with place names) -> best moment on the drop -> sunset outro;
sports = plays building to the best play on the drop, freeze + label on the key moment; wedding = slow, emotional,
dissolves, the kiss/rings on the climax; product = problem -> product reveal on the drop -> feature labels -> logo/end card;
documentary = voiceover + slow cinematic shots matching what is said; party/dance = colourful, flashes and hits on beats.

RULES
- Read RUNTIME AWARENESS: build on DIRECT and BUILT-IN options; never plan what is NOT POSSIBLE.
- Pros cut fast: hype 2 beats per shot in the drop, montage 2, cinematic 4; something must change every 1-2 s. A 15 s hype
  edit has 10-16 shots: re-use a file at different moments ("around"); the code never repeats a moment, spreads the
  footage over all files and splits long ordinary shots (held moments, labelled story beats and the climax stay whole).
- Hook in the first 1.5 s (a hook text, a striking shot or a hit). The climax is the most striking shot + the drop.
- A label names what its shot really SHOWS (read MEDIA): never put "Pool" on a shot without a pool. If the client asked
  for something the footage does not have, say so in that requirement ("confidence": "low", "fallback") instead of faking it.
- Looks follow the genre: bright and clean for property, product, food and wedding-day; dark/gritty only for hype, gym,
  night and car; grain and vignette are a vintage/film choice, not a default.
- A REFERENCE STYLE (the client's sample) decides the style: cut rhythm, grade, music tempo, effects and text look follow
  it, even against the EDIT TYPE's habits; the edit type then only guides the structure and the content (labels, story).
  Only what the request itself names (a colour, a music style) goes before the sample.
- Choose shots with MEDIA: faces for face/eye effects (eyes visible), motion for velocity, highlights for the drop; vary files.
- velocity = fast-slow-fast speed ramp on the key moment; slow = slow motion; freeze = hold one frame (endings, reveals).
- Eye/face asks: an extra effect with a matching [target] on the close-up shot, plus a broader effect as support.
- Names of items in extras: copy EXACTLY from CANDIDATES. Files: only MEDIA.
- Each requirement lists what delivers it (shot ids, extra ids or recipe names).
- One title per moment: a kinetic_title OR a text extra for the same words, never both; the hook text is separate.
- Talking heads (MEDIA shows "said:"): style talking + "speech"; emphasis = 3-6 words that carry the message (numbers,
  promises, names); b-roll on words that name something visible in another file; music quiet ("generate": "chill" or "none").
Output compact JSON only."""


def _card_line(c, proven=None):
    bits = [f"{c['category']} {c['name']} \"{c.get('en') or ''}\" - {c.get('desc') or ''}"]
    if proven and f"{c['category']}:{c['name']}" in proven:
        bits.append("(proven)")
    extra = []
    for f in ("target", "look", "mood", "motion", "style", "weight", "sound"):
        if c.get(f):
            extra.append(f"{f} {c[f]}")
    if c.get("moves_image"):
        extra.append("moves_image")
    if extra:
        bits.append("[" + "; ".join(str(x) for x in extra) + "]")
    if c.get("params"):
        bits.append("params: " + ", ".join(f"{k.replace('effects_adjust_', '').replace('change_voice_param_', '')}"
                                           f"({v.split('default ')[-1].rstrip(')')})" for k, v in c["params"].items()))
    if c.get("default_duration_s"):
        bits.append(f"default {c['default_duration_s']} s")
    return "  " + " ".join(bits)


class Director:
    def __init__(self, planner, catalog=None, log=print, v3=True):
        self.planner, self.cat, self.log, self.v3 = planner, catalog or Catalog.shared(), log, v3
        self.design_json = None

    def brief(self, request, quick_media):
        lines = "\n".join(f"- {m['file']} ({m['kind']}" + (f", {m['seconds']:.1f} s" if m.get("seconds") else "") +
                          (f", {m['width']}x{m['height']}" if m.get("width") else "") + (", has sound" if m.get("has_audio") else "") + ")"
                          for m in quick_media)
        system = BRIEF_SYSTEM % TX.brief_list()
        r = self.planner._call("fast", [{"role": "system", "content": system},
                                        {"role": "user", "content": f"REQUEST:\n{request}\n\nFILES:\n{lines}"}])
        b = parse_json(r.text)
        if not isinstance(b, dict):
            r = self.planner._call("fast", [{"role": "system", "content": system},
                                            {"role": "user", "content": f"REQUEST:\n{request}\n\nFILES:\n{lines}\n\nReply with the JSON object only."}])
            b = parse_json(r.text) or {}
        return b

    def candidates(self, brief, per_kind=5):
        """{group title: [card, ...]} for every need of the brief, plus a style palette for the mood."""
        groups, seen = {}, set()
        ix = self.cat.index
        for n in (brief.get("needs") or [])[:20]:
            kinds = [k for k in (n.get("kinds") or []) if k in KINDS]
            if not kinds:
                continue
            q = f"{n.get('query') or ''} {n.get('what') or ''}"
            part = str(n.get("target") or "none").lower()
            if part in ("eyes", "face", "head", "body", "hands") and "character_effect" not in kinds and any(k.endswith("effect") for k in kinds):
                kinds = ["character_effect"] + kinds
            cards = []
            for k in kinds:
                found = ix.search(q, categories=[k], k=per_kind * 3, exclude=self.cat.missing, boost=self.cat.rank)
                if k == "character_effect" and part in ("eyes", "face", "head", "body", "hands"):
                    # the named body part comes first: an eye effect for "lightning on my eyes", even if its name says "red glow"
                    on_part = [c for c in ix.search(f"{part} {q}", categories=[k], k=40, exclude=self.cat.missing, boost=self.cat.rank)
                               if c.get("target") == part][:3]
                    found = on_part + [c for c in found if c not in on_part]
                for c in found[:per_kind + (3 if k == "character_effect" else 0)]:
                    key = f"{c['category']}:{c['name']}"
                    if key not in seen:
                        seen.add(key)
                        cards.append(c)
            if cards:
                title = f"{n.get('id', '?')}: {n.get('what', '')}"
                if part in ("eyes", "face", "head", "body", "hands"):
                    title += f" (must sit on the {part}: use an item with target {part}, plus a broader effect if wanted)"
                groups[title] = cards
        mood = f"{brief.get('mood') or ''} {brief.get('pace') or ''}"
        palette = {"transition": f"{mood} transition", "text_intro": f"{mood} pop bounce slam typewriter", "text_outro": f"{mood} fade out",
                   "font": f"{mood} bold heavy display title", "filter": f"{mood} cinematic", "clip_intro": f"{mood} zoom", "clip_combo": f"{mood}"}
        style = []
        for k, q in palette.items():
            got = [c for c in ix.search(q, categories=[k], k=8, exclude=self.cat.missing, boost=self.cat.rank)
                   if f"{c['category']}:{c['name']}" not in seen][:4]
            if k == "font":  # titles in this project are usually Latin; keep readable Latin fonts first
                got = sorted(got, key=lambda c: 0 if c.get("script") in ("latin", "both") else 1)
            for c in got:
                seen.add(f"{c['category']}:{c['name']}")
            style += got
        groups["style palette"] = style
        return groups

    def design(self, request, brief, analyses, groups, aware_text="", extra=""):
        """The v3 path: style + music + shot list + recipes (+ extras); recipes.compose() writes the edits."""
        from .styles import describe
        plat = brief.get("platform") if brief.get("platform") in PLATFORMS else None
        pinfo = ""
        if plat:
            p = PLATFORMS[plat]
            sf = p["safe"]
            pinfo = (f"{plat}: canvas {p['aspect']}" + (f", at most {p['max_s']} s" if p["max_s"] else "") +
                     f"; the app covers the top {sf['top'] * 100:.0f}%, bottom {sf['bottom'] * 100:.0f}% and right {sf['right'] * 100:.0f}%")
        media = "\n".join(AN.describe(a) for a in analyses.values())
        proven = {k for k, f in self.cat.boost.items() if f > 1.3}
        cands = "\n".join(f"[{g}]\n" + "\n".join(_card_line(c, proven) for c in cards) for g, cards in groups.items())
        user = (f"REQUEST:\n{request}\n\nBRIEF:\n{json.dumps(brief, ensure_ascii=False)}\n\nPLATFORM:\n{pinfo or 'none given'}\n\n"
                f"{extra}MEDIA:\n{media}\n\n{aware_text}\n\nCANDIDATES (free catalogue items; copy names exactly):\n{cands}\n\nWrite the design JSON.")
        msgs = [{"role": "system", "content": DESIGN_SYSTEM % describe()}, {"role": "user", "content": user}]
        r = self.planner._call("video", msgs)
        d = parse_json(r.text)
        if not isinstance(d, dict) or not d.get("shots"):
            r = self.planner._call("video", msgs + [{"role": "assistant", "content": r.text[:3000]},
                                                    {"role": "user", "content": "Reply with the design JSON only (it needs a shots list)."}])
            d = parse_json(r.text)
        if not isinstance(d, dict) or not d.get("shots"):
            raise ValueError("the planner returned no valid design")
        d.setdefault("platform", plat)
        return d, r.usage, len(user)

    def plan(self, request, brief, analyses, groups, aware_text=""):
        plat = brief.get("platform") if brief.get("platform") in PLATFORMS else None
        pinfo = ""
        if plat:
            p = PLATFORMS[plat]
            sf = p["safe"]
            pinfo = (f"{plat}: canvas {p['aspect']}" + (f", at most {p['max_s']} s" if p["max_s"] else "") +
                     f"; the app covers the top {sf['top'] * 100:.0f}%, bottom {sf['bottom'] * 100:.0f}% and right {sf['right'] * 100:.0f}% "
                     "(text is moved out of there automatically)")
        media = "\n".join(AN.describe(a) for a in analyses.values())
        proven = {k for k, f in self.cat.boost.items() if f > 1.3}
        cands = "\n".join(f"[{g}]\n" + "\n".join(_card_line(c, proven) for c in cards) for g, cards in groups.items())
        user = (f"REQUEST:\n{request}\n\nBRIEF:\n{json.dumps(brief, ensure_ascii=False)}\n\nPLATFORM:\n{pinfo or 'none given'}\n\n"
                f"MEDIA:\n{media}\n\n{aware_text}\n\nCANDIDATES (free catalogue items; copy names exactly):\n{cands}\n\nWrite the plan JSON.")
        msgs = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}]
        r = self.planner._call("video", msgs)
        plan = parse_json(r.text)
        if not isinstance(plan, dict):
            r = self.planner._call("video", msgs + [{"role": "assistant", "content": r.text[:3000]},
                                                    {"role": "user", "content": "That was not one valid JSON object. Reply with the plan JSON only."}])
            plan = parse_json(r.text)
        if not isinstance(plan, dict):
            raise ValueError("the planner returned no valid plan")
        plan.setdefault("platform", plat)
        return plan, r.usage, len(user)

    def run(self, request, files, references=None):
        """(plan, brief, groups, analyses, timings) for a request and a list of media paths. references: sample edits
        whose style the new edit should match (measured, never used as footage)."""
        t0 = time.perf_counter()
        quick = []
        for f in files:
            k = AN.kind_of(f)
            info = F.probe(f) if k in ("video", "audio") else {}
            if k == "image":
                from PIL import Image
                with Image.open(f) as im:
                    info = {"width": im.width, "height": im.height}
            quick.append({"file": str(f).replace("\\", "/").split("/")[-1], "kind": k, **info})
        from . import reference as RF
        with ThreadPoolExecutor(3) as ex:
            fa = ex.submit(AN.analyze, files, self.planner, self.log)
            fr = [ex.submit(RF.fingerprint, r, self.planner, self.log) for r in (references or [])]
            tb = time.perf_counter()
            brief = self.brief(request, quick)
            t_brief = time.perf_counter() - tb
            analyses = fa.result()
            refs = []
            for f in fr:
                try:
                    refs.append(f.result())
                except Exception as e:  # noqa: BLE001  (a bad sample must not stop the edit)
                    self.log(f"  reference not usable: {type(e).__name__}: {e}")
        self.reference = RF.merge(refs) if refs else None
        self.ref_profile = RF.profile(self.reference) if self.reference else None
        t_an = time.perf_counter() - t0
        from . import speech as SP
        if SP.available():  # what is said, for captions, cuts and emphasis (~2 s per minute of speech, cached)
            for a in analyses.values():
                snd = a.get("sound") or {}
                if a.get("kind") in ("video", "audio") and snd.get("kind") in ("speech", "mixed/ambient") and snd.get("syllabic", 0) > 0.3:
                    try:
                        SP.transcribe(a["path"], log=self.log)
                    except Exception as e:  # noqa: BLE001
                        self.log(f"  transcription failed for {a['file']}: {type(e).__name__}: {e}")
        groups = self.candidates(brief)
        from . import awareness, lessons
        aware, aware_text = awareness.snapshot(brief, analyses, groups, self.cat, lessons.text(), request)
        self.edit_type = et = TX.classify(request, analyses, brief, self.reference)
        nxt = et["alternatives"][0] if et["alternatives"] else None
        self.log(f"edit type: {et['label']} ({et['confidence'] * 100:.0f}%"
                 + (f"; then {TX.TYPES[nxt[0]]['label']} {nxt[1] * 100:.0f}%" if nxt else "") + f") - {'; '.join(et['reasons'][:2])}")
        extra = TX.design_block(et) + "\n\n"
        if self.reference:
            extra += RF.describe(self.reference, self.ref_profile) + "\n\n"
        self.aware, self.aware_text, self.groups = aware, aware_text, groups
        t1 = time.perf_counter()
        if self.v3:
            from .styles import STYLES
            from .recipes import compose

            def settle(d):
                if self.ref_profile:
                    d["_reference"] = self.ref_profile  # compose cuts to the sample's rhythm and recipes
                if d.get("style") not in STYLES:
                    d["style"] = (self.ref_profile or {}).get("style") or et["profile"]["style"]
                if brief.get("target_seconds") and not d.get("target_seconds"):
                    d["target_seconds"] = brief["target_seconds"]  # compose fits the cut to it exactly
                d["_edit_type"] = et["type"]
                return d
            design, usage, chars = self.design(request, brief, analyses, groups, aware_text, extra)
            design = settle(design)
            try:
                plan = compose(design, analyses, self.cat, self.log, request)
            except Exception as e:  # noqa: BLE001  (an odd design must not end the job: ask for another one, once)
                self.log(f"compose failed ({type(e).__name__}: {str(e)[:120]}); asking for a new design")
                design, usage, chars = self.design(request, brief, analyses, groups, aware_text, extra)
                design = settle(design)
                plan = compose(design, analyses, self.cat, self.log, request)
            self.design_json = design
        else:
            plan, usage, chars = self.plan(request, brief, analyses, groups, aware_text)
        t_plan = time.perf_counter() - t1
        timings = {"brief_s": round(t_brief, 1), "analysis_s": round(t_an, 1), "plan_s": round(t_plan, 1),
                   "plan_tokens": [usage.get("prompt_tokens"), usage.get("completion_tokens")], "prompt_chars": chars}
        self.log(f"brief {t_brief:.1f} s (parallel with analysis {t_an:.1f} s), {sum(len(v) for v in groups.values())} candidates, "
                 f"plan {t_plan:.1f} s ({usage.get('prompt_tokens')} -> {usage.get('completion_tokens')} tokens)")
        return plan, brief, groups, analyses, timings
