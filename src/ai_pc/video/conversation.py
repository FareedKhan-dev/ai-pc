"""Conversation: one edit worked on over many turns, the way a client talks to an editor.

  c = Conversation.start("agent_road_195510")       a chat about a finished edit (a studio session)
  c = Conversation.load("chat_road_101530")
  print(c.say("make the title red and the music a bit quieter"))

A message is split into clauses (quick_edits.clauses); each clause is one of:
  question  about this edit ("what font is the title?", "what's at 0:12?", "why the shake?")         -> explain.py
            about what is possible ("any snow effects?", "can you do 4K?", "what can you do?")      -> catalogue / router
  change    "title red", "cut it to 30 s", "slow motion on the kiss"                                 -> quick_edits rules,
            the cheap model for what the rules do not cover (it answers in the same operations)
  version   undo, redo, "go back to v2", "start over", "the old music was better" (one element back)
  template  "any template for eid with 4 clips?" (the library, best fit first), "use the slowmo hdr template", a pasted
            CapCut template link (read once, politely): the edit is recut on the template's slots
  answer    to the editor's own question ("the second one", "yes", "both", "1 and 3")
  ack       "perfect", "thanks"; export: "export it", "render"
All changes of a message become ONE new version. Structural changes (length, pacing, shots, music, format, recipes) change
the design and the cut engine re-cuts it, keeping the items the edit already uses; the rest change the plan. Plan
changes are kept as an override list and applied again after any re-cut, so "title red" survives a later "make it
30 s". Every change is checked on the new timeline, and the reply says what was done, what was not and why.
Chats are saved in out/video/chats/<id>.json; every version is also a JianYing draft (<chat>_v<n>).
"""
import copy
import json
import re
import time
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json
from ai_pc.video import analyze as AN
from ai_pc.video import editplan as EP
from ai_pc.video import explain as EX
from ai_pc.video import quick_edits as QE

CHATS = ROOT / "out" / "video" / "chats"

# templates: a CapCut template link, "use the X template", questions about which templates exist
TEMPLATE_LINK = re.compile(r"https?://(?:www\.)?capcut\.com/[^\s<>\"']+", re.I)
TEMPLATE_USE = re.compile(
    r"\b(?:use|apply|try|follow|pick|choose|switch to|change to|go with|recut (?:it |this )?(?:on|with|like|using)|"
    r"(?:edit|make|do|redo|cut|turn) (?:it|this|the video|my video|the edit|everything)\s+(?:like|with|using|on|in|into))\s+"
    r"(?:the |this |that |a |an |your |my )?(?:template\s+(?:called\s+|named\s+)?['\"]?([\w\-'& ]{2,40}?)['\"]?(?=\s*(?:$|[,.!?]|\band\b|\bplease\b|\bpls\b))|"
    r"['\"]?([\w\-'& ]{1,40}?)['\"]?\s+template)\b", re.I)
TEMPLATE_WORDS = re.compile(r"\b(?:can you |could you |please |pls |plz )?(?:use|apply|try|follow|edit (?:it |this )?(?:with|like)|make (?:it|this) (?:like|with)|"
                            r"do (?:it|this) (?:like|with)|recut (?:it )?(?:with|on|like))?\s*(?:this|that|the|a)?\s*(?:capcut\s+)?template\b[:\s]*", re.I)
TEMPLATE_CATALOG = re.compile(r"\b(?:any|which|what|suggest|recommend|show|list|do you have|have you got|got|options?|available|fit|fits|good for|best|"
                              r"other|others|else|more|library|saved)\b", re.I)
TEMPLATE_THIS = re.compile(r"\b(?:did you use|is this|is it|are you using|you used|this edit|current(?:ly)?|following|follows|is used|in use)\b", re.I)
GENERIC_NAME = {"this", "that", "a", "the", "another", "other", "new", "different", "some", "any", "one", "your", "my", "same", "that one", "this one", "a new"}
ORDINAL = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "last": -1}
FILLER = re.compile(r"\b(?:please|pls|plz|and|it|now|for|me|with|this|that|on|my|the|a|an|video|clips?|edit|template|link|here|is|can|you|could|would|u|"
                    r"ok|okay|thanks?|thank you|bro|just|to|of|in|use|apply|try|follow|like|one)\b", re.I)

# ------------------------------------------------------------------------------------------------ what a clause is
LEAD = re.compile(r"^(?:(?:no|nope|nah)[,!.]+\s*|(?:hey|hi|hello|yo|ok(?:ay)?|so|um+|uh+|hmm+|well|also|and|now|then|alright|right|actually|oh|ah|wait|"
                  r"listen|bro|dude|man|sir|boss|please|pls|plz|kindly|just|quickly|one more thing|another thing|one more|one last thing|"
                  r"last thing|next|oh and|and also|lastly|finally)\b[,!.:]*(?:\s+|$))+", re.I)
POLITE = re.compile(r"^(?:(?:can|could|would|will|cud|wud) (?:you|u|ya|we|i)(?: please| pls| plz| maybe| just| also)?|"
                    r"i (?:want|need|would like|'d like|wanna|wish)(?: you| u)?(?: to)?|i'd love(?: it)? if you|let'?s|maybe|"
                    r"how about|what about|why not|what if (?:we|you)?|is it possible to|would it be possible to|possible to|"
                    r"any chance (?:you could|to)|do you mind|go ahead and|try(?: to)?|you should|we should|you need to|we need to)\s+", re.I)
QUESTION = re.compile(r"^(?:what|what's|which|who|why|how|when|where|is|are|does|do|did|was|were|have|has|any|show me|tell me|"
                      r"list|explain|got any|whats)\b|\?\s*$", re.I)
RHETORICAL = re.compile(r"^(?:isn'?t|aren'?t|don'?t you think|doesn'?t (?:it|this|that) (?:feel|look|seem)|wouldn'?t it be (?:better|nicer|cooler) (?:if|to)|"
                        r"shouldn'?t)\s+", re.I)
TOO_Q = re.compile(r"^(?:is|are|was|does|do)\b.*\b(?:too|enough)\b", re.I)

ACK = re.compile(r"^\s*(?:ok(?:ay)?|cool|nice|great|perfect|awesome|amazing|love it|i love it|looks (?:good|great|amazing|perfect|fire|sick)|"
                 r"that'?s (?:good|great|perfect|it|better|nice|much better|way better|fine)|good|thanks?|thank you|thx|ty|sweet|dope|fire|lit|sick|"
                 r"much better|better|way better|well done|good job|nice work|wow|yes that'?s it|exactly|nailed it|beautiful|"
                 r"zabardast|kamaal|bohat acha|ok|great work)\b[\s!.,]*(?:thanks?|thank you|bro|man|dude)?[\s!.]*$", re.I)
EXPORT = re.compile(r"\b(?:export|render|download (?:it|the video|the file|the mp4|link)|save (?:it|the video|the file)|send (?:it|me (?:the )?(?:video|file|final))|finali[sz]e|"
                    r"ship it|final (?:version|cut)|i'?m (?:done|happy with it)|that'?s final|let'?s export|give me the (?:video|file|mp4))\b", re.I)
VAGUE = re.compile(r"\b(?:make it better|improve (?:it|this|the (?:video|edit))|something(?:'s| is) (?:off|missing|wrong)|i don'?t (?:like|love) it|"
                   r"not (?:feeling|vibing (?:with)?) it|meh|could be better|not (?:great|good enough)|needs? (?:something|work|more work)|"
                   r"make it (?:more )?(?:professional|pro|nicer|cooler|amazing|awesome|good|great|insane|viral)|fix it|do your magic|"
                   r"it'?s (?:ok|okay|fine|alright) but|not quite (?:there|right)|feels? off|looks? (?:amateur|cheap|bad))\b", re.I)

UNDO = re.compile(r"\b(?:undo|revert|scratch that|never ?mind|cancel (?:that|it|the last)|take (?:that|it) back|change it back|go back|"
                  r"bring (?:it|them|that|those|these) back|put (?:them|those|these) back|"
                  r"put it back|back to how it was|(?:previous|old|last|earlier|other) (?:one|version|edit|cut) (?:was|is|looked|looks) better|"
                  r"(?:liked|prefer(?:red)?|preferred) (?:it|the (?:previous|old|last|earlier) (?:one|version)) (?:better|more|before)|"
                  r"(?:it )?(?:was|looked) better before|liked it before|before was better|wapis)\b", re.I)
REDO = re.compile(r"\bredo\b|\bundo the undo\b|\bput (?:it|that) back again\b|\bbring (?:it|that) back again\b", re.I)
GOTO = re.compile(r"\b(?:go|jump|switch|get|take me|revert) (?:back )?to (?:version|v) ?(\d+)\b|\buse (?:version|v) ?(\d+)\b|^\s*v(\d+)\s*$|"
                  r"\b(?:version|v) ?(\d+) (?:was|is|looked) (?:better|best|perfect)\b|\bback to (?:version|v) ?(\d+)\b", re.I)
RESET = re.compile(r"\b(?:start over|from scratch|reset (?:it|everything|all|the edit)|undo (?:all|everything)|"
                   r"(?:the|back to the) (?:very )?(?:first|original) (?:version|edit|cut)|back to the (?:very )?(?:first|original) one|as it was at the start|"
                   r"(?:go back|back|return|revert|restore|reset) to (?:the )?(?:very )?(?:first|original)(?: (?:version|edit|cut|one))?\s*$)", re.I)
HISTORY = re.compile(r"\bwhat (?:did you|have you|did u|you) (?:just )?(?:change|do|did)\b|\bwhat(?:'s| is| has)? (?:changed|different)\b|"
                     r"\bwhat changed\b|\bwhat was (?:changed|done)\b", re.I)
VERSIONS = re.compile(r"\b(?:show|list|see) (?:me )?(?:the |all )?(?:the )?(?:versions|history|changes)\b|\bhow many versions\b|"
                      r"\bwhich version (?:is this|am i on|are we on)\b|\bversion history\b", re.I)
COMPARE = re.compile(r"\bcompare\b|\bdifference between\b|\bwhat'?s the difference\b|\bdifferent (?:from|than|to) (?:the )?(?:original|first|v\d|version)|"
                     r"\bchanged? (?:from|since) (?:the )?(?:original|first|start|beginning|scratch|v\d)|\bsince (?:the beginning|the start|we started)|"
                     r"\bvs\.? (?:v\d|the original)|\bversus\b", re.I)
OLD = re.compile(r"\b(?:old|older|previous|earlier|original|first version'?s?|other)\b|\bv\d+'?s?\b|\bversion \d+'?s?\b|\b(?:like|as) (?:it was )?before\b|\bbefore was\b|"
                 r"\b(?:was|were|looked|sounded) better before\b|\bthe one before\b|\bback\b|\bbring back\b|\bput back\b|\breturn\b|\bpehle\b", re.I)

IMPOSSIBLE = [
    (r"\bstickers?\b|\bemojis?\b|\bgifs?\b|\bmemes? (?:image|picture)s?\b",
     "Stickers, emojis and GIFs can't be placed in these projects.", "I can put a text, an effect or a sound there instead."),
    (r"\b4k\b|\b2160p?\b|\b60 ?fps\b|\b120 ?fps\b|\bhdr\b|\b8k\b", "Exports here are 1080p at 30 fps.", None),
    (r"\b(?:face ?swap|deep ?fake|swap (?:his|her|their|the) faces?)\b", "Face swapping isn't offered.", None),
    (r"\b(?:remove|erase|delete|get rid of|take out) (?:the |that |this )?(?:person|people|guy|man|woman|object|logo|watermark|sign|"
     r"car|tree|crowd|background people)s? (?:in|from|behind|at the back of) (?:the )?(?:background|shot|clip|frame|footage|picture|back)\b",
     "Removing things from inside the picture isn't possible here.", "I can crop or reframe the shot, cover the spot with a text or effect, or leave that shot out."),
    (r"\b(?:change|recolou?r) (?:his|her|their|the) (?:shirt|clothes|dress|hair|eye|car|jacket|shoes?) colou?r\b|"
     r"\bmake (?:him|her|them|the (?:guy|man|woman|girl|boy)) (?:smile|look happier|look taller|wear|dance|jump)\b",
     "Changing what happens in the footage itself isn't possible.", "I can change the colour look of the shot or pick another moment."),
    (r"\b(?:upload|post|publish) (?:it )?(?:to|on) (?:instagram|insta|tiktok|youtube|facebook|snapchat|twitter|x)\b",
     "I can't post to social media.", "I export the file ready for that platform; you upload it."),
    (r"\b(?:text to speech|tts|ai voice|robot voice reading|voice ?over (?:that )?(?:says|saying)|narrate (?:it|this|the video)|read (?:it|this|the text) out)\b",
     "There is no text-to-speech voice here.", "Record the voiceover and send the file: I add it with subtitles and duck the music under it."),
    (r"\b(?:despacito|taylor swift|drake|bad bunny|the weeknd|eminem|beyonce|bollywood song|trending (?:song|audio|sound)|popular song|"
     r"that song from|spotify|apple music|copyrighted song|famous song|a real song)\b",
     "I can't fetch songs from a library or the internet.", "I generate a music bed in any style (hype, phonk, epic, pop, chill, cinematic) or use a music file you send."),
    (r"\b(?:ai[- ]generate|generate (?:a|an|some|new) (?:video|footage|clip|image|shot|scene)s?|create (?:a|an|some) (?:new )?(?:shot|clip|footage|scene)s? of|"
     r"film (?:a|some) new)\b", "I can't create new footage.", "Send the clip and I'll cut it in."),
]
IMPOSSIBLE = [(re.compile(p, re.I), a, b) for p, a, b in IMPOSSIBLE]
NEED_FOOTAGE = re.compile(r"\b(?:add|show|use|put|include|insert|need|want) (?:a |an |some |more |the |another )?(?:\w+ )?(?:shots?|clips?|footage|scenes?|parts?|"
                          r"b-?roll) (?:of|with|where|showing) (?:a |an |the |some |my |our )?(.+)$", re.I)

ORD = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1,
       "option one": 1, "option two": 2, "option three": 3, "option four": 4, "number one": 1, "number two": 2, "number three": 3}


def _picked(text, n):
    """Which of n options a reply picks: [indices], [] (declined) or None (not an answer to the options)."""
    t = " " + str(text).lower().strip(" .!") + " "
    if re.fullmatch(r"\s*(?:no|nope|nah|neither|none|no thanks|skip|leave it|forget it|never ?mind|keep it|it'?s fine)\b.*", t):
        return []
    if re.search(r"\b(?:all|both|everything|all of (?:them|it|those)|do all|all three|all 3|every one)\b", t):
        return list(range(n))
    nums = [int(x) for x in re.findall(r"(?<![\d:.])\b([1-9])\b(?![\d:.]|\s*(?:s|sec|seconds|x|%))", t)]
    for w, k in ORD.items():
        if re.search(r"\b" + w + r"\b(?: one| option| idea)?", t) and (w != "one" or re.search(r"\b(?:the|that|this) one\b", t) is None):
            nums.append(n if k == -1 else k)
    picks = sorted({i - 1 for i in nums if 1 <= i <= n})
    if picks and (len(t.split()) <= 6 or re.search(r"\b(?:option|number|#)\s*\d|\b(?:the )?(?:first|second|third|fourth|fifth|last) (?:one|option|idea)\b", t)) \
            and not re.search(r"\b(?:export|render|make it|change|remove|add)\b", t):
        return picks
    if n == 1 and re.fullmatch(r"\s*(?:yes|yeah|yep|yup|ya|sure|ok(?:ay)?|do it|go ahead|please do|sounds good|why not|haan|han|ji|"
                               r"go for it|let'?s do it|try it|yes please|ok do it)\b.*", t):
        return [0]
    return None


ACK_WORDS = set("""thanks thank you thx ty that's thats it is perfect great nice cool awesome amazing love it looks good so much really
the one this what i wanted needed was looking for we're done all set exactly just right spot on and lol haha
very much better way wow beautiful excellent brilliant fantastic exactly nailed sweet dope fire lit sick bro man dude ok okay
yes yeah good job work well done appreciate appreciated cheers lovely gorgeous stunning zabardast kamaal bohat acha shukriya
jazakallah now wonderful superb top notch""".split())


def _is_ack(text):
    words = re.findall(r"[a-z']+", str(text).lower())
    return bool(words) and len(words) <= 9 and all(w in ACK_WORDS for w in words) and \
        bool(set(words) & {"thanks", "thank", "thx", "ty", "perfect", "great", "love", "awesome", "amazing", "nice", "cool", "good",
                           "beautiful", "excellent", "wow", "cheers", "lovely", "zabardast", "kamaal", "shukriya", "superb", "wonderful"})


def _strip_lead(c):
    prev = None
    while prev != c:
        prev = c
        c = LEAD.sub("", c).strip()
    return c


def _pin_fonts(plan, R):
    """The plan's text fonts as the edit shows them. The resolver stands in a proven face for an untried one, and which
    stand-in it picks depends on what recent videos used; pinned, later versions keep the face the client saw (and "the
    previous font" brings that face back)."""
    plan = copy.deepcopy(plan)
    shown = {e["id"]: (e.get("style") or {}).get("font") for e in R.get("edits") or [] if e.get("type") == "text"}
    for e in plan.get("edits") or []:
        f = shown.get(e.get("id"))
        if e.get("type") == "text" and f and e.get("font") and not e.get("font_asked") and str(f).split(":", 1)[-1] != e["font"]:
            e["font"] = str(f).split(":", 1)[-1]
    return plan


def _used_items(R):
    """Catalogue items the edit uses (kept by a re-cut). A font the client asked for one text is not a house font."""
    out = set()
    for e in R["edits"]:
        if e.get("item"):
            out.add(e["item"])
        st = e.get("style") or {}
        if st.get("font") and not st.get("asked"):
            out.add(st["font"])
    return out


SYSTEM_LLM = """You are the editor's assistant in a chat about ONE video edit that already exists. Turn the client's message
into change operations for the automatic editor. Reply with ONE JSON object:
{"ops": [<operations>], "reply": "<one short sentence to the client about what you changed>",
 "question": "<only when guessing would likely be wrong: a short question>", "options": ["<short option>", ...],
 "impossible": "<what cannot be done here, and the closest alternative>"}
OPERATIONS (exact forms; every field is optional unless shown):
 {"op":"text","who":{"role":"title|label|cta|caption|text|all","match":"<words of a text in THE EDIT>"},"set":{"text":"<new words>","color":"#RRGGBB","position":"top|upper|center|lower|bottom","font_style":"<handwritten|bold|elegant|futuristic|playful|minimal|retro|serif...>","bold":true,"case":"upper|lower","shadow":true,"outline":{"color":"#000000","width":60},"start":<seconds on the timeline>,"shift":<+/- seconds>},"mul":{"size":1.2,"duration":1.5}}
 {"op":"text","who":{...},"remove":true}
 {"op":"text_add","text":"...","anchor":"start|end|drop|<seconds>","role":"title|label|cta","position":"top|center|lower","color":"#RRGGBB"}
 {"op":"audio","who":"music|voice|sfx","mul":{"volume":0.7}}  {"op":"audio","who":"music","remove":true}  {"op":"audio","who":"music","set":{"fade_out":3}}
 {"op":"music","generate":"hype|phonk|epic|pop|chill|cinematic"}  {"op":"music","bpm_mul":1.1}
 {"op":"sfx_add","sound":"whoosh|swoosh|impact|riser|sub_drop|thunder|glitch|hit","anchor":"transitions|drop|end|start|<seconds>"}
 {"op":"length","seconds":30}  {"op":"length","mul":0.8}
 {"op":"pace","mul":0.8} (below 1 = faster cuts, above 1 = longer shots; "sections":["intro|verse|build|drop|break|outro"] optional)
 {"op":"section_beats","section":"intro|verse|build|drop|break|outro","mul":0.6}
 {"op":"canvas","value":"9:16|16:9|1:1|4:5"}
 {"op":"look","words":"<colour look in words>","name":"<short name>"}  {"op":"look","mul":{"strength":0.7}}  {"op":"look","remove":true}
 {"op":"texture","what":"grain|vignette|letterbox|leak","add":true}  {"op":"texture","what":"...","remove":true}
 {"op":"transitions","family":"dissolve|blur|zoom|whip|spin|glitch|flash|slide|leak"}  {"op":"transitions","remove":true}
 {"op":"transitions","every":true}  {"op":"transitions","thin":2}  {"op":"transitions","mul":{"duration":1.5}}
 {"op":"fx","kind":"shake|zoom|flash|glitch|effect","remove":true | "thin":2 | "mul":{"strength":0.6},"section":"intro|middle|drop|outro","at":<seconds>}
 {"op":"recipe","use":"zoom_punch|shake|flash|rgb_hit","on":"beats|downbeats|drop","sections":["build","drop"],"strength":1.2}
 {"op":"move_add","kind":"zoom|shake","anchor":"drop|end|start|<seconds>"}
 {"op":"fx_add","words":"<the effect in plain words: lightning, snow, sparkles, light leak, smoke...>","anchor":"drop|end|start|whole|<seconds>","target":"eyes|face|null"}
 {"op":"shot","id":"<shot id>","field":"speed","value":"slow|velocity|freeze|fast|normal"}
 {"op":"shot_move","id":"<shot id>","to":"first|last|drop"}  {"op":"shot_remove","ids":["<shot id>"]}  {"op":"swap_shots","a":"<id>","b":"<id>"}
 {"op":"avoid_file","file":"<file>"}  {"op":"more_of","file":"<file>"}
 {"op":"clips","files":[],"set":{"volume":0}} (the clips' own sound; [] = all clips)
RULES: change only what is asked; ids and files only from THE EDIT. A complex ask may need several ops ("a more
emotional ending": slow motion on the last shot + dissolves + a longer outro + cinematic music). If the ask is vague,
make the 1-3 most likely concrete changes and say what you did in "reply"; ask a "question" only when a guess would
probably be wrong. Not possible here: stickers, emojis, 4K/60 fps, songs by name, face swaps, removing things from inside
the picture, new footage that is not in the files. Output the JSON only."""


class Conversation:
    def __init__(self, state, planner=None, log=print, export=False, drafts=None, build=True, chats_dir=None):
        self.state, self.planner, self.log = state, planner, log
        self.chats = Path(chats_dir) if chats_dir else CHATS
        self.do_export, self.drafts, self.do_build = export, drafts, build
        derived = ROOT / "media" / "derived"
        for v in state["versions"]:  # generated music beds the plans use, even if the session did not list them
            for e in (v.get("plan") or {}).get("edits") or []:
                f = str(e.get("file") or "")
                if e.get("type") == "audio" and f.startswith("music_") and (derived / f).exists() and str(derived / f) not in state["files"]:
                    state["files"].append(str(derived / f))
        self.analyses = AN.analyze(state["files"], planner=None, log=lambda *a: None)
        self._R = {}

    # ------------------------------------------------------------------ creating, loading, saving
    @classmethod
    def start(cls, draft, **kw):
        from ai_pc.video import studio
        sess = studio.load(draft)
        word = re.sub(r"[^a-z0-9]", "", draft.split("_")[1] if "_" in draft else draft)[:10] or "edit"
        stamp = time.strftime("%H%M%S")
        design = sess.get("design") or {}
        state = {"id": f"chat_{word}_{stamp}", "drafts_prefix": f"agent_{word}{stamp}", "base": draft, "request": sess["request"],
                 "files": sess["files"], "edit_type": sess.get("edit_type"), "reference": sess.get("reference"),
                 "versions": [{"v": 0, "parent": None, "design": design, "plan": _pin_fonts(sess["plan"], sess["resolved"]), "overrides": [], "said": None,
                               "done": ["the first edit"], "failed": [], "checks": [], "draft": draft,
                               "seconds": round(sess["resolved"]["end"], 2), "export": (sess.get("export") or {}).get("path")}],
                 "cur": 0, "turns": [], "focus": None, "pending": None, "last_ops": []}
        c = cls(state, **kw)
        c._R[0] = sess["resolved"]
        return c

    @classmethod
    def load(cls, chat_id, **kw):
        folder = Path(kw.get("chats_dir") or CHATS)
        return cls(json.loads((folder / f"{chat_id}.json").read_text(encoding="utf-8")), **kw)

    @classmethod
    def latest(cls, draft, **kw):
        """The most recent chat about a draft (or None)."""
        folder = Path(kw.get("chats_dir") or CHATS)
        best = None
        for p in sorted(folder.glob("chat_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                st = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if st.get("base") == draft or any(v.get("draft") == draft for v in st.get("versions") or []):
                best = st
                break
        return cls(best, **kw) if best else None

    def save(self):
        self.chats.mkdir(parents=True, exist_ok=True)
        p = self.chats / f"{self.state['id']}.json"
        p.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        return p

    # ------------------------------------------------------------------ the current version
    @property
    def version(self):
        return self.state["versions"][self.state["cur"]]

    def resolved(self, v=None):
        v = self.state["cur"] if v is None else v
        if v not in self._R:
            self._R[v] = EP.resolve(self.state["versions"][v]["plan"], self.analyses)
        return self._R[v]

    def sess(self):
        v = self.version
        return {"resolved": self.resolved(), "design": v["design"], "plan": v["plan"], "edit_type": self.state.get("edit_type"),
                "reference": self.state.get("reference"), "request": self.state["request"]}

    def _ctx(self):
        v = self.version
        R = self.resolved()
        secs = {}
        for n, a, b in QE.sections(v["plan"], v["design"]):
            secs[n] = secs.get(n, 0.0) + (b - a)
        return {"design": v["design"], "plan": v["plan"], "analyses": self.analyses, "focus": self.state.get("focus"),
                "last_ops": self.state.get("last_ops") or [], "seconds": R["end"], "section_seconds": secs,
                "bpm": (v["plan"].get("_rhythm") or {}).get("bpm")}

    def _lineage(self, v=None):
        """Versions from the current one back to the first: [cur, parent, grandparent, ...]."""
        out, i = [], self.state["cur"] if v is None else v
        while i is not None:
            out.append(i)
            i = self.state["versions"][i]["parent"]
        return out

    # ------------------------------------------------------------------ one message
    def say(self, message, files=()):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "ops": [], "v_before": self.state["cur"], "llm": False}
        self._turn = turn
        out = []
        if files:
            out.append(self._new_media(files, turn))
        norm = QE.normalize(message)
        QE.ORIGINAL["text"] = str(message)
        pend, self.state["pending"] = self.state.get("pending"), None
        tr = self._template_request(message, turn)
        if tr is not None:  # a CapCut template link or "use the X template" (read before typo fixing changes the name)
            out.append(tr["reply"])
            if tr.get("rest"):
                out.append(self.say_inner(QE.normalize(tr["rest"]), turn, raw=tr["rest"]))
            return self._finish(turn, out, t0)
        if not pend and self.state.get("last_options") and re.search(r"\b(?:the )?(?:first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th) one\b|"
                                                                     r"\boption \d\b|\bnumber \d\b", norm):
            pend = self.state["last_options"]
        if pend and pend.get("template") and not pend["options"]:
            r = QE.parse(_strip_lead(norm), self._ctx())
            if not r["ops"] and not QUESTION.search(norm) and not UNDO.search(norm):
                turn["intents"].append("option")
                ans = re.sub(r"^(?:on|at|in|for|during|to|over|the one (?:with|where))\s+", "", _strip_lead(norm).rstrip(" .!?"))
                norm = pend["template"].format(ans)
                out.append(self.say_inner(norm, turn, raw=message))
                return self._finish(turn, out, t0)
            pend = None
        if pend and len(pend["options"]) > 1 and re.fullmatch(r"\s*(?:yes|yeah|yep|sure|ok(?:ay)?|do it|go ahead|haan)\W*", norm):
            self.state["pending"] = pend
            turn["intents"].append("ask")
            return self._finish(turn, [f"Which one (1-{len(pend['options'])}), or 'all'?"], t0)
        if pend:  # an answer to the editor's own question?
            pick = _picked(norm, len(pend["options"]))
            if pick is not None:
                turn["intents"].append("option")
                if not pick:
                    out.append("OK, leaving it as it is.")
                else:
                    ops = [copy.deepcopy(o) for i in pick for o in pend["options"][i].get("ops") or []]
                    msgs = [pend["options"][i]["message"] for i in pick if pend["options"][i].get("message")]
                    if ops:
                        out.append(self._change(ops, message, turn))
                    for m in msgs:
                        out.append(self.say_inner(m, turn))
                return self._finish(turn, out, t0)
        if re.fullmatch(r"\s*(?:try|use|pick|take|go with|i(?:'ll| will)? take)? ?(?:the )?(?:first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th) one\s*", norm) \
                or re.fullmatch(r"\s*(?:option|number) \d\s*", norm):
            turn["intents"].append("ask")
            return self._finish(turn, ["I haven't offered options to pick from just now. Tell me what you'd like, or ask e.g. 'what other transitions do you have?'"], t0)
        out.append(self.say_inner(norm, turn, raw=message))
        return self._finish(turn, out, t0)

    def say_inner(self, norm, turn, raw=None):
        ops, out, unknown, asks, acks, export_after = [], [], [], [], [], False
        ctx = self._ctx()

        def flush():
            nonlocal ops, ctx
            seen, uniq = set(), []
            for o in ops:
                k = json.dumps(o, sort_keys=True, ensure_ascii=False, default=str)
                if k not in seen:
                    seen.add(k)
                    uniq.append(o)
            merged = []
            for o in uniq:
                if o.get("op") == "look" and o.get("words") and merged and merged[-1].get("op") == "look" and merged[-1].get("words"):
                    merged[-1] = {**merged[-1], "words": f"{merged[-1]['words']} {o['words']}", "name": f"{merged[-1].get('name')}, {o.get('name')}"}
                else:
                    merged.append(o)
            ops = merged
            if ops:
                out.append(self._change(ops, raw or norm, turn))
                ops = []
                ctx = self._ctx()
        whole = _strip_lead(norm)
        vague = bool(VAGUE.search(whole))  # options only if nothing concrete was asked as well (see below)
        for cl in QE.clauses(norm):
            cl = _strip_lead(cl)
            if not cl:
                continue
            kind, payload = self._clause(cl, ctx)
            turn["intents"].append(kind)
            if kind == "change":
                export_after = export_after or bool(payload.get("export_after"))
                ops += payload["ops"]
                ctx["focus"] = payload.get("focus") or ctx.get("focus")
                ctx["last_ops"] = payload["ops"]
                self.state["focus"] = ctx["focus"]
            elif kind == "ack":
                acks.append(payload)
            elif kind == "context":
                if isinstance(payload, dict) and payload.get("focus"):
                    self.state["focus"] = ctx["focus"] = payload["focus"]
            elif kind in ("question", "catalog", "capability", "help", "impossible"):
                if kind == "question":
                    flush()
                out.append(payload if isinstance(payload, str) else payload.get("text", ""))
                if isinstance(payload, dict) and payload.get("options"):
                    self.state["pending"] = self.state["last_options"] = {"question": payload.get("text"), "options": payload["options"]}
                if isinstance(payload, dict) and payload.get("focus"):
                    self.state["focus"] = ctx["focus"] = payload["focus"]
            elif kind == "ask":
                asks.append(payload)
            elif kind == "unknown":
                unknown.append(cl)
            elif kind in ("undo", "redo", "goto", "reset", "history", "versions", "compare", "restore", "export"):
                flush()
                out.append(payload())
                ctx = self._ctx()
        if vague and unknown and not ops and not out and not asks:  # "make it better": concrete directions to pick from
            turn["intents"].append("ask")
            return self._vague()
        if unknown:
            r = self._llm(unknown, raw or norm, turn, done=[QE.describe(o) for o in ops] + [x.split(".")[0][:120] for x in out if x])
            if r.get("ops"):
                turn["intents"].append("change")
            ops += r.get("ops") or []
            if r.get("reply_text"):
                out.append(r["reply_text"])
            if r.get("ask"):
                asks.append(r["ask"])
        flush()
        if export_after:
            turn["intents"].append("export")
            out.append(self.export())
        if acks and not out and not asks:
            out.append(acks[0])
        for a in asks[:1]:  # one question back at a time
            out.append(a["question"] + ("\n" + "\n".join(f"  {i + 1}) {o['label']}" for i, o in enumerate(a.get("options") or [])) if a.get("options") else ""))
            if a.get("options") or a.get("template"):
                self.state["pending"] = {"question": a["question"], "options": a.get("options") or [], "template": a.get("template")}
        return "\n".join(x for x in out if x)

    def _finish(self, turn, out, t0):
        reply = "\n".join(x for x in out if x).strip() or "OK."
        turn.update(reply=reply, v_after=self.state["cur"], seconds=round(time.perf_counter() - t0, 2))
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    # ------------------------------------------------------------------ what one clause asks
    def _clause(self, cl, ctx):
        c = cl.strip()
        low = c.lower()
        # a request phrased as a question ("can you make the title red?", "how about chill music?") is a request
        polite = POLITE.match(c)
        typed = POLITE.sub("", c, count=1).strip(" ?") if polite else c
        rhet = RHETORICAL.match(typed)
        if rhet:
            typed = RHETORICAL.sub("", typed, count=1).strip(" ?")
        body = typed.lower()
        for pat, why, alt in IMPOSSIBLE:
            if pat.search(body):
                return "impossible", f"{why}" + (f" {alt}" if alt else "")
        m = NEED_FOOTAGE.search(body)
        head = (QE.content_words(m.group(1)) or [""])[0] if m else ""
        if m and head and not QE.match_files(head, self.analyses):
            thing = re.sub(r"\b(?:at|in|on|to)\b.*$", "", m.group(1)).strip(" .?!") or m.group(1)
            return "impossible", f"There is no {thing} in your clips, so I can't add that shot. Send a clip of it and I'll cut it in."
        if re.fullmatch(r"(?:(?:hmm+|hm+|no+|nope|nah|ok(?:ay)?|yes|yeah|well|so|actually|wait|ah+|oh+|lol|haha+|um+|uh+|right|alright|hey|"
                        r"listen|look|bro|dude|man)[\s,.!?]*)+", body):
            return "context", ""
        if re.match(r"^(?:because|since|cause|cuz|coz|so that|as)\b", body) or (
                re.search(r"\b(?:people|viewers|audience|they|users|my (?:boss|client|followers))\b", body) and
                re.search(r"\b(?:scroll|skip|leave|lose interest|get bored|bored|swipe|watch|like it|hate it|love it)\b", body) and not QE._subjects(body)):
            return "context", ""
        # versions
        if COMPARE.search(body):
            return "compare", lambda: self.compare(body)
        if REDO.search(body):
            return "redo", self.redo
        g = GOTO.search(body)
        if g:
            n = int(next(x for x in g.groups() if x))
            return "goto", lambda: self.goto(n)
        if RESET.search(body) and not [x for x in QE._subjects(body) if x not in ("shot", "length")]:
            return "reset", lambda: self.goto(0, "the first version")
        if HISTORY.search(body):
            return "history", self.history
        if VERSIONS.search(body):
            return "versions", self.versions_text
        if COMPARE.search(body):
            return "compare", lambda: self.compare(body)
        if re.search(r"\b(?:bring back|put back|add back|use (?:it |them )?again|include again|back in)\b", body):
            hit = QE.match_files(re.sub(r"\b(?:bring|put|add|back|use|again|include|the|shots?|clips?|footage|scenes?|in)\b", " ", body), self.analyses)
            avoided = {str(f).lower() for f in self.version["design"].get("avoid_files") or []}
            if hit and hit[0][0].lower() in avoided:
                return "change", {"ops": [{"op": "unavoid_file", "file": hit[0][0]}, {"op": "more_of", "file": hit[0][0], "n": 2}], "focus": {"kind": "shot"}}
        subj = [s for s in QE._subjects(body) if s not in ("shot",)] or QE._subjects(body)
        if not subj and re.search(r"\b(?:put|bring|go|get|switch)\b.*\b(?:one|version|thing)\b.*\bback\b|\bback to the \w+ one\b", body):
            if any(p_.search(body) for p_, _, _ in QE.LOOKS):  # "put the warm one back": the look
                subj = ["look"]
            elif any(p_.search(body) for p_ in QE.GENRE_RE.values()):
                subj = ["music"]
            elif any(p_.search(body) for p_, _, _ in QE.FAMILIES.values()):
                subj = ["transition"]
        km = re.search(r"\bkeep (?:the |my |all the )?[a-z ]+?(?: though| tho| at least| please| pls| still| in)?\s*$", body)
        if km and subj and self.version["parent"] is not None:
            cur, par = self._snap(self.state["cur"], subj[0]), self._snap(self.version["parent"], subj[0])
            if cur is not None and par is not None and self._sig(cur, subj[0]) != self._sig(par, subj[0]):
                return "restore", lambda: self.restore(subj[0], "")
        if subj and (UNDO.search(body) or (OLD.search(body) and re.search(
                r"\b(?:back|was (?:better|nicer|cooler|prettier|good|perfect)|were (?:better|nicer|good)|looked better|sounded better|"
                r"(?:like|as) (?:it was )?before|bring|restore|return|like it was|as it was|liked|prefer(?:red)?|pehle|wapis)\b", body))):
            return "restore", lambda: self.restore(subj[0], body)
        if UNDO.search(body) and not QE.parse(body, ctx)["ops"]:
            nm = re.search(r"\b(two|2|three|3|four|4|five|5)\s+(?:versions?|changes?|steps?|edits?|times|things)\b|\b(twice)\b|\bundo (both)\b", body)
            n = {"two": 2, "2": 2, "three": 3, "3": 3, "four": 4, "4": 4, "five": 5, "5": 5, "twice": 2, "both": 2}.get(
                next((g for g in nm.groups() if g), "") if nm else "", 1)

            def undo_n(n=n):
                out = [self.undo() for _ in range(n)]
                return out[-1] if n == 1 else f"Undone {n} changes: back to v{self.state['cur']}."
            return "undo", undo_n
        # thanks / export
        if (ACK.match(body) or _is_ack(body)) and not QE._subjects(body):
            return "ack", self._ack()
        if EXPORT.search(body):
            rest = EXPORT.sub("", body).strip(" ,.")
            r = QE.parse(EXPORT.sub("", typed).strip(" ,."), ctx) if rest else {"ops": []}
            if r["ops"]:  # "export it for youtube": the change first, then the export
                return "change", {**r, "export_after": True}
            return "export", self.export
        # which templates fit ("any template for eid with 4 clips?", "suggest a template")
        if re.search(r"\btemplates?\b", body) and TEMPLATE_CATALOG.search(body) and not TEMPLATE_THIS.search(body):
            return self._templates(body)
        # questions
        is_q = QUESTION.search(body) and not polite and not rhet
        if is_q and TOO_Q.match(body):  # "is the music too loud?": an answer, and the change on offer
            parsed = QE.parse(re.sub(r"^(?:is|are|was|does|do)\s+", "", body).rstrip(" ?"), ctx)
            ans = EX.answer(body, self.sess()) or ""
            if parsed["ops"]:
                return "question", {"text": (ans + "\n" if ans else "") + f"Want me to change it ({'; '.join(QE.describe(o) for o in parsed['ops'])})?",
                                    "options": [{"label": "; ".join(QE.describe(o) for o in parsed["ops"]), "ops": parsed["ops"]}],
                                    "focus": parsed.get("focus")}
        if is_q or (polite and re.match(r"^(?:tell me|show me|explain|list)\b", body)):
            return self._question(body, ctx)
        # a change
        if self.version["design"].get("template"):  # a template edit: slow motion, ramps or normal speed on every slot
            sp = self._tpl_speed(typed.lower())
            if sp:
                return "change", {"ops": [sp], "focus": {"kind": "speed"}}
        if re.search(r"\b(?:add|put|show|include|with|want|wish)\b.{0,15}\bgreetings?\b", body):
            g = self._greeting()
            if g:
                return "change", {"ops": [{"op": "text_add", "text": g, "anchor": "start", "role": "title", "position": "lower", "color": None}],
                                  "focus": {"kind": "text", "who": {"match": g}}}
            return "ask", {"question": "Which greeting should I add? (e.g. 'Eid Mubarak', 'Happy Birthday')", "options": [], "template": "add {}"}
        r = QE.parse(typed, ctx)
        if r["ops"]:
            return "change", r
        if r.get("note") == "context":  # an opinion that the next ask refers to ("the DJ shots are the best")
            return "context", {"focus": r.get("focus")}
        if r.get("ask"):
            return "ask", {"question": r["ask"], "options": r.get("options") or [], "template": r.get("template")}
        if polite and re.match(r"^(?:do|make|add|use|put|create|give)\b", body) is None and re.search(r"\b(?:possible|support|able)\b", low):
            return self._question(body, ctx)
        vague = self._vague_one(body, r)
        if vague:
            return "ask", vague
        return "unknown", c

    # ------------------------------------------------------------------ questions
    def _question(self, q, ctx):
        from ai_pc.video import catalog_qa as CQ
        from ai_pc.video import router as RT
        if re.search(r"\bwhat can you do\b|\bwhat do you (?:do|support)\b|\bhelp\b", q) and not CQ.parse(q)["kinds"]:
            return "help", RT.help_text()
        ans = EX.answer(q, self.sess())
        spec = CQ.parse(q)
        item_word = re.search(r"\b(?:effects?|filters?|transitions?|fonts?|animations?|looks?|luts?|presets?|sounds?|sfx|templates?|stickers?|"
                              r"overlays?|styles?|typefaces?|intros?|outros?)\b", q)
        about_items = (spec["kinds"] and item_word) or spec["unsupported"] or (item_word and re.search(
            r"\b(?:do you have|got any|are there|is there|available|options|other|others|similar|alternatives?|else)\b", q))
        catalogue_q = re.search(r"\b(?:other|others|similar|alternatives?|else|available|do you have|got any|is there|are there|any)\b", q) and \
            not re.search(r"\b(?:in (?:the|this|my|it)|did you use|you used|are used|is used|in it|so far|right now|currently|now)\b", q) and \
            not (re.match(r"how many\b", q) and not re.search(r"\b(?:do you have|available|catalogue|catalog|library|exist)\b", q))
        if ans and not (about_items and catalogue_q):
            return "question", {"text": ans, "focus": self._focus_from(q)}
        if about_items:
            return self._catalog(q, ctx)
        if re.search(r"\b(?:can you|could you|is it possible|possible|do you support|are you able)\b", q):
            return "capability", RT.capability(q, self.planner)
        if ans:
            return "question", {"text": ans}
        if self.planner is not None:
            try:
                r = self.planner._call("fast", [{"role": "system", "content": "You answer a client's question about a video edit, in 1-3 short "
                                                 "sentences, only from THE EDIT below (times, shots, texts, music, look). If it is not there, say so."},
                                                {"role": "user", "content": f"THE EDIT:\n{self.brief()}\n\nQUESTION: {q}"}])
                self._turn["llm"] = True
                txt = re.sub(r"<think>.*?</think>", "", r.text or "", flags=re.S).strip()
                if txt:
                    return "question", {"text": txt[:600]}
            except Exception:  # noqa: BLE001
                pass
        return "question", {"text": "I'm not sure what you mean; you can ask about the music, fonts, transitions, effects, colours, "
                                    "what happens at a moment (e.g. 'what's at 0:12?') or why something is there."}

    def _focus_from(self, q):
        for name, kind in (("title", "text"), ("label", "text"), ("font", "text"), ("transition", "transition"), ("music", "music"),
                           ("song", "music"), ("filter", "look"), ("colou?r", "look"), ("look", "look"), ("effect", "effects"),
                           ("shake", "shake"), ("zoom", "zoom"), ("flash", "flash")):
            if re.search(r"\b" + name, q):
                if kind == "text":
                    return {"kind": "text", "who": {"role": "label" if name == "label" else "title"}}
                return {"kind": kind}
        return None

    def _catalog(self, q, ctx):
        """Items for a question about what exists ("any snow effects?", "other transitions like this?"), with the ones
        that work here offered as options ("use the 2nd")."""
        from ai_pc.video import catalog_qa as CQ
        R = self.resolved()
        like = re.search(r"\b(?:like (?:this|that|these|the current|what you used|the one you used)|similar|other|others|alternatives?|instead|else)\b", q)
        spec = CQ.parse(q)
        current = set()
        if like:  # "like this": the words of what the edit uses now, for the kinds asked about
            kinds = spec["kinds"] or {"transition": ["transition"], "look": ["filter"], "effects": ["scene_effect"]}.get((ctx.get("focus") or {}).get("kind"), [])
            for e in R["edits"]:
                k = e.get("item") or (e.get("style") or {}).get("font")
                if k and k.split(":")[0] in kinds:
                    current.add(k)
            q = re.sub(r"\b(?:any|other|others|similar|alternatives?|else|instead|more|different|ones?|like (?:this|that|these|the current|"
                       r"what you used|the one you used))\b", " ", q)
            own = [w for w in CQ.parse(q)["words"] if w not in ("transition", "transitions", "filter", "filters", "effect", "effects", "font", "fonts")]
            if current and not own:
                n = self.cat.index.notes
                words = " ".join(" ".join([str(n.get(k, {}).get("en") or ""), " ".join((n.get(k, {}).get("tags") or [])[:4])]) for k in list(current)[:2])
                q = f"{q} {words}"
        r = CQ.ask(q, self.planner if spec.get("recommend") else None)
        items = [it for it in r["items"] if it["state"] in ("ready", "untried") and it["key"] not in current][:5]
        text = r["text"]
        if like and current:
            names = ", ".join(self.cat.item(k)["name"] for k in list(current)[:2])
            text = f"Now using: {names}.\n" + text
        opts = []
        anchor = QE._anchor(q)
        for it in items:
            cat_ = it["category"]
            if cat_ == "transition":
                op = {"op": "transitions", "item": it["key"]}
            elif cat_ == "filter":
                op = {"op": "look", "item": it["key"], "name": it["en"]}
            elif cat_ in ("scene_effect", "character_effect"):
                op = {"op": "fx_add", "item": it["key"], "anchor": anchor if anchor is not None else "drop", "target": spec.get("target"), "label": it["en"]}
            elif cat_ == "font":
                op = {"op": "text", "who": (ctx.get("focus") or {}).get("who") or {"role": "title"}, "set": {"font": it["name"], "font_asked": True}}
            elif cat_ == "text_intro":
                op = {"op": "text", "who": (ctx.get("focus") or {}).get("who") or {"role": "title"}, "set": {"intro": it["name"]}}
            else:
                continue
            opts.append({"label": f"{it['name']} ({it['en']})", "ops": [op]})
        if opts:
            text += "\n\nTo try one, say e.g. 'use the 2nd': " + "; ".join(f"{i + 1}) {o['label']}" for i, o in enumerate(opts))
        kind = {"transition": "transition", "filter": "look", "font": "text"}.get((spec["kinds"] or [""])[0], "effects")
        focus = {"kind": kind, **({"who": {"role": "title"}} if kind == "text" else {})}
        return "catalog", {"text": text, "options": opts, "focus": focus}

    @property
    def cat(self):
        return QE._cat()

    # ------------------------------------------------------------------ vague asks: a question back, with concrete options
    def _vague_one(self, body, parsed):
        """A clause too unclear to act on alone ("make it bigger" with nothing to point at): the likely meanings."""
        if re.fullmatch(r"(?:make )?(?:it|this|that|everything)? ?(?:bigger|larger|huge)", body.strip()):
            return {"question": "What should be bigger?", "options": [
                {"label": "the title", "ops": [{"op": "text", "who": {"role": "title"}, "mul": {"size": 1.25}}]},
                {"label": "all the text", "ops": [{"op": "text", "who": {"role": "all"}, "mul": {"size": 1.2}}]},
                {"label": "stronger zoom punches", "ops": [{"op": "fx", "kind": "zoom", "mul": {"strength": 1.4}}]}]}
        if re.fullmatch(r"(?:make )?(?:it|this|that|everything)? ?(?:smaller|tiny)", body.strip()):
            return {"question": "What should be smaller?", "options": [
                {"label": "the title", "ops": [{"op": "text", "who": {"role": "title"}, "mul": {"size": 0.8}}]},
                {"label": "all the text", "ops": [{"op": "text", "who": {"role": "all"}, "mul": {"size": 0.85}}]}]}
        if re.fullmatch(r"(?:change|swap|replace) (?:it|this|that|everything)", body.strip()):
            f = (self.state.get("focus") or {}).get("kind")
            if not f:
                return {"question": "What should I change: the music, the look, the transitions or the title?", "options": [
                    {"label": "the music", "ops": [{"op": "music", "generate": "_next"}]},
                    {"label": "the colour look", "ops": [{"op": "look", "words": "", "name": "a different look", "different": True}]},
                    {"label": "the transitions", "ops": [{"op": "transitions", "family": "_different"}]},
                    {"label": "the title font", "ops": [{"op": "text", "who": {"role": "title"}, "set": {"font_style": ""}}]}]}
        return None

    def _vague(self):
        """'make it better': three concrete directions for this edit (from its style), to pick from."""
        p, d = self.version["plan"], self.version["design"]
        style = str(p.get("style") or d.get("style") or "")
        calm = style in ("cinematic", "tour", "talking", "documentary") or (self.state.get("edit_type") or {}).get("type") in ("wedding", "real_estate", "documentary")
        opts = []
        if calm:
            opts.append({"label": "slower, more emotional ending (longer last shots, soft fade)",
                         "ops": [{"op": "section_beats", "section": "outro", "mul": 1.4}, {"op": "audio", "who": "music", "set": {"fade_out": 3.0}}]})
            opts.append({"label": "richer film look (cinematic grade + subtle grain)",
                         "ops": [{"op": "look", "words": "cinematic film warm soft contrast", "name": "cinematic"}, {"op": "texture", "what": "grain", "add": True}]})
            opts.append({"label": "smoother flow (dissolves at every section change)", "ops": [{"op": "transitions", "family": "dissolve"}]})
        else:
            opts.append({"label": "tighter cuts (faster pacing)", "ops": [{"op": "pace", "mul": 0.85}]})
            opts.append({"label": "punchier drop (zoom punches, a flash and a shake on the hits)",
                         "ops": [{"op": "recipe", "use": "zoom_punch", "on": "downbeats", "sections": ["drop"], "strength": 1.2},
                                 {"op": "fx_add", "item": QE._effect_key("white flash", "flash") or "scene_effect:闪白", "anchor": "drop", "label": "white flash", "duration": 0.4},
                                 {"op": "move_add", "kind": "shake", "anchor": "drop", "strength": 0.6}]})
            opts.append({"label": "bolder title (bigger, outlined, pops in)",
                         "ops": [{"op": "text", "who": {"role": "title"}, "set": {"outline": {"color": "#000000", "width": 70}, "shadow": True, "intro_words": "pop in"}, "mul": {"size": 1.15}}]})
        opts.append({"label": "different music", "ops": [{"op": "music", "generate": "_next"}]})
        self.state["pending"] = {"question": "which direction", "options": opts}
        return "Happy to. Which direction?\n" + "\n".join(f"  {i + 1}) {o['label']}" for i, o in enumerate(opts)) + "\n(or say 'all')"

    def _ack(self):
        n = self.state["cur"]
        return f"Glad you like it (v{n}). Say 'export' when you want the video file, or keep the changes coming."

    # ------------------------------------------------------------------ the model, for what the rules do not cover
    def brief(self):
        """The edit in a few lines, for the model: length, sections, shots, texts, effects, music, look, files."""
        v, R = self.version, self.resolved()
        d, p = v["design"], v["plan"]
        roles = QE.text_roles(p)
        music = next((e for e in R["edits"] if e["id"] == "music"), None)
        mu = (f"generated {music['file'].split('_')[1]} {music['file'].split('_')[2]} BPM, volume {music.get('volume')}"
              if music and str(music.get("file", "")).startswith("music_") else (f"file {music['file']}" if music else "none"))
        fx = {}
        for e in p.get("edits") or []:
            for k in QE.fx_kinds(e, p) & {"shake", "zoom", "flash", "glitch", "grain", "vignette", "letterbox", "leak", "effect", "pushin"}:
                fx[k] = fx.get(k, 0) + 1
        tr = [e for e in R["edits"] if e["type"] == "transition"]
        fl = [e for e in R["edits"] if e["type"] == "filter"]
        lines = [f"length {R['end']:.1f} s, canvas {d.get('canvas') or p.get('canvas')}, style {p.get('style')}, music: {mu}",
                 "sections: " + ", ".join(f"{n} {a:.1f}-{b:.1f}" for n, a, b in QE.sections(p, d)),
                 "shots (design): " + "; ".join(f"{s['id']} [{s.get('section')}] {s.get('file') or ','.join(s.get('files') or [])}"
                                                + (f" label '{s['label']}'" if s.get("label") else "") + f": {str(s.get('want') or '')[:50]}"
                                                for s in d.get("shots") or [] if isinstance(s, dict))[:3000],
                 "texts: " + "; ".join(f"{roles.get(str(e['id']), 'text')} '{e['text'][:30]}' at {e['window'][0]:.1f} s ({e['style']['font'].split(':')[-1] if e['style'].get('font') else 'default'}, "
                                       f"{e['style']['color']}, size {e['style']['size']})" for e in R["edits"] if e["type"] == "text")[:1500],
                 "effects: " + (", ".join(f"{k} x{n}" for k, n in fx.items()) or "none"),
                 "transitions: " + (f"{len(tr)} x " + ", ".join(sorted({EX._name(e['item']) for e in tr})) if tr else "hard cuts only"),
                 "look: " + (", ".join(EX._name(e["item"]) for e in fl) or "no filter"),
                 "files: " + "; ".join(f"{a['file']}: {str(a.get('summary') or '')[:70]}" for a in self.analyses.values() if a.get("kind") in ("video", "image"))[:2500]]
        return "\n".join(lines)

    def _llm(self, clauses, message, turn, done=()):
        if self.planner is None:
            return {"reply_text": "I didn't understand: " + "; ".join(f"'{c}'" for c in clauses) + ". Could you say it another way?"}
        recent = "\n".join(f"client: {t['user']}\neditor: {t.get('reply', '')[:200]}" for t in self.state["turns"][-3:])
        user = (f"THE EDIT (version {self.state['cur']}):\n{self.brief()}\n\nORIGINAL REQUEST: {self.state['request']}\n\n"
                f"RECENT CHAT:\n{recent or '(none)'}\n\nCLIENT MESSAGE: {message}\n"
                + (f"ALREADY DONE by the editor (do NOT repeat): {'; '.join(done)}\n" if done else "")
                + f"PARTS TO HANDLE (only these): {json.dumps(clauses, ensure_ascii=False)}\n\nThe JSON:")
        turn["llm"] = True
        try:
            r = self.planner._call("fast", [{"role": "system", "content": SYSTEM_LLM}, {"role": "user", "content": user}])
            d = parse_json(r.text)
        except Exception as e:  # noqa: BLE001  (a failed call must not end the chat)
            return {"reply_text": f"I couldn't work out '{'; '.join(clauses)}' ({type(e).__name__}); could you say it more concretely?"}
        if not isinstance(d, dict):
            return {"reply_text": f"I couldn't work out '{'; '.join(clauses)}'; could you say it more concretely?"}
        ops = [o for o in (self._valid(o) for o in d.get("ops") or [] if isinstance(o, dict)) if o]
        out = {"ops": ops}
        txt = []
        if d.get("impossible"):
            txt.append(str(d["impossible"]))
        if d.get("question") and not ops:
            out["ask"] = {"question": str(d["question"]), "options": [{"label": str(o), "message": str(o)} for o in (d.get("options") or [])[:4]]}
        elif not ops and not d.get("impossible"):
            txt.append(f"I couldn't turn '{'; '.join(clauses)}' into a change; could you say it more concretely?")
        out["reply_text"] = " ".join(txt)
        return out

    def _valid(self, op):
        """An operation from the model, checked against what exists (ids, files, items); None if unusable."""
        k = op.get("op")
        v = self.version
        shots = {s.get("id"): s for s in v["design"].get("shots") or [] if isinstance(s, dict)}
        files = {str(a.get("file", "")).lower(): a["file"] for a in self.analyses.values() if a.get("kind") in ("video", "image")}
        if k == "fx_add":
            if op.get("item") not in self.cat.index.items:
                key = QE._effect_key(str(op.get("words") or op.get("label") or op.get("name") or ""), target=op.get("target") if op.get("target") in ("eyes", "face", "head", "body") else None)
                if not key:
                    return None
                op["item"] = key
            op["label"] = self.cat.index.notes.get(op["item"], {}).get("en") or op["item"].split(":", 1)[1]
            return op
        if k in ("shot", "shot_move"):
            if op.get("id") not in shots:
                return None
            if k == "shot_move":
                op["file"] = shots[op["id"]].get("file")
                op["to"] = op.get("to") if op.get("to") in ("first", "last", "drop") else "drop"
            elif op.get("field") != "speed" or op.get("value") not in ("slow", "velocity", "freeze", "fast", "normal"):
                return None
            return op
        if k == "shot_remove":
            ids = [i for i in op.get("ids") or [] if i in shots]
            return {**op, "ids": ids, "file": shots[ids[0]].get("file")} if ids else None
        if k in ("avoid_file", "more_of"):
            f = files.get(str(op.get("file", "")).lower())
            return {**op, "file": f} if f else None
        if k == "swap_shots":
            return op if op.get("a") in shots and op.get("b") in shots else None
        if k == "text":
            if not isinstance(op.get("who"), dict):
                op["who"] = {"role": "title"}
            st = op.get("set") if isinstance(op.get("set"), dict) else {}
            if st.get("font") and not any(x.startswith("font:") for x in self.cat.exact(st["font"])):
                st["font_style"] = st.pop("font")
            if isinstance(st.get("color"), str) and not re.fullmatch(r"#[0-9A-Fa-f]{6}", st["color"]):
                c = QE.COLOURS.get(st["color"].lower())
                if c:
                    st["color"] = c
                else:
                    st.pop("color")
            if "set" in op:
                op["set"] = st
            mul = op.get("mul") if isinstance(op.get("mul"), dict) else {}
            op["mul"] = {f: max(0.3, min(3.0, float(x))) for f, x in mul.items() if f in ("size", "duration") and isinstance(x, (int, float))}
            if not op["mul"]:
                op.pop("mul")
            return op if (op.get("set") or op.get("mul") or op.get("remove")) else None
        if k == "music":
            if op.get("generate") and op["generate"] not in QE.GENRES:
                return None
            return op if (op.get("generate") or op.get("bpm_mul") or op.get("file")) else None
        if k == "length":
            if isinstance(op.get("seconds"), (int, float)) and 5 <= op["seconds"] <= 600:
                return op
            return op if isinstance(op.get("mul"), (int, float)) and 0.2 <= op["mul"] <= 3 else None
        if k == "pace":
            return op if isinstance(op.get("mul"), (int, float)) and 0.4 <= op["mul"] <= 2.5 else None
        if k == "canvas":
            return op if op.get("value") in ("9:16", "16:9", "1:1", "4:5") else None
        if k == "transitions":
            if op.get("family") and op["family"] not in QE.FAMILIES and op["family"] != "_different":
                return None
            return op
        if k == "recipe":
            return op if op.get("use") in ("zoom_punch", "shake", "flash", "rgb_hit", "ken_burns") else None
        if k == "fx":
            return op if op.get("kind") in ("shake", "zoom", "flash", "glitch", "effect") else None
        if k == "texture":
            return op if op.get("what") in ("grain", "vignette", "letterbox", "leak") else None
        if k == "sfx_add":
            return op if op.get("sound") in ("whoosh", "swoosh", "impact", "riser", "sub_drop", "thunder", "glitch", "hit") else None
        if k in ("text_add", "audio", "look", "section_beats", "move_add", "clips", "speed_reset"):
            return op
        return None

    # ------------------------------------------------------------------ making a version
    def _change(self, ops, said, turn):
        """Apply operations as ONE new version; check each on the new timeline; the reply."""
        v0 = self.version
        R0 = self.resolved()
        ctx = self._ctx()
        design_ops = [o for o in ops if QE.is_design(o)]
        plan_ops = [o for o in ops if not QE.is_design(o)]
        done, failed = [], []
        design, plan = v0["design"], v0["plan"]
        overrides0 = v0["overrides"]
        use = [o for o in design_ops if o.get("op") == "use_template"]
        if use:  # recut on a template: its slots and timing; the edit's footage, avoided files and main title stay
            design_ops = [o for o in design_ops if o.get("op") != "use_template"]
            r = self._switch_template(use[-1])
            if isinstance(r, str):
                failed.append(r)
                ops = [o for o in ops if o.get("op") != "use_template"]  # nothing to check on the timeline
            else:
                design, plan, dd = r
                done += dd
                overrides0 = []  # earlier changes were to the old cut; the template's plan starts clean
        if design_ops and design.get("template"):  # a template edit: its timing stays; footage, music and format can change
            from ai_pc.video import template as TP
            design, dd, df = TP.apply_design(design, design_ops, ctx)
            done += dd
            failed += df
            if dd:
                req = " ".join([self.state["request"]] + [t["user"] for t in self.state["turns"]])
                try:
                    plan = TP.refill(design, self.analyses, req, log=lambda *a: None, chat=True)
                except Exception as e:  # noqa: BLE001
                    failed.append(f"could not re-fill the template ({type(e).__name__}: {str(e)[:80]})")
                    design, plan = v0["design"], v0["plan"]
                else:
                    plan, _, _ = QE.apply_plan(plan, overrides0, {**ctx, "plan": plan, "design": design})
                    for a in self.analyses.values():
                        if a.get("path") and a["path"] not in self.state["files"] and str(a.get("file", "")).startswith("music_"):
                            self.state["files"].append(a["path"])
        elif design_ops:
            from ai_pc.video.recipes import compose
            design, dd, df = QE.apply_design(design, design_ops, ctx)
            done += dd
            failed += df
            if dd:
                req = " ".join([self.state["request"]] + [t["user"] for t in self.state["turns"]])
                try:
                    plan = compose(copy.deepcopy(design), self.analyses, self.cat, log=lambda *a: None, request=req, keep=_used_items(R0))
                except Exception as e:  # noqa: BLE001  (an impossible structure must not end the chat)
                    failed.append(f"could not re-cut the edit ({type(e).__name__}: {str(e)[:80]})")
                    design, plan = v0["design"], v0["plan"]
                else:
                    plan, _, _ = QE.apply_plan(plan, v0["overrides"], {**ctx, "plan": plan, "design": design})  # earlier changes again
                    for a in self.analyses.values():  # a new music bed is a file of this edit now
                        if a.get("path") and a["path"] not in self.state["files"] and str(a.get("file", "")).startswith("music_"):
                            self.state["files"].append(a["path"])
        if plan_ops:
            plan, pd, pf = QE.apply_plan(plan, plan_ops, {**ctx, "plan": plan, "design": design})
            done += pd
            failed += pf
        turn["ops"] += ops
        if not done:
            return "Nothing changed: " + "; ".join(failed or ["that is already how it is"]) + "."
        try:
            R1 = EP.resolve(plan, self.analyses)
        except Exception as e:  # noqa: BLE001
            return f"That change broke the edit ({type(e).__name__}: {str(e)[:100]}); nothing was changed."
        checks = []
        for op in ops:
            try:
                ok, what = QE.check(op, R0, R1, plan)
            except Exception as e:  # noqa: BLE001
                ok, what = False, f"check failed: {type(e).__name__}"
            checks.append({"op": QE.describe(op), "ok": bool(ok), "what": what})
        n = len(self.state["versions"])
        ver = {"v": n, "parent": self.state["cur"], "design": design, "plan": plan, "overrides": overrides0 + plan_ops, "said": said,
               "done": done, "failed": failed, "checks": checks, "draft": None, "seconds": round(R1["end"], 2), "export": None}
        if self.do_build:
            from ai_pc.video import jybuild as JB
            try:
                M = JB.build(R1, **({"drafts": self.drafts} if self.drafts else {}), name=f"{self.state['drafts_prefix']}_v{n}")
                ver["draft"] = M["draft"]
                self._M = M
            except Exception as e:  # noqa: BLE001
                failed.append(f"draft not built ({type(e).__name__}: {str(e)[:80]})")
        self.state["versions"].append(ver)
        self.state["cur"] = n
        self._R[n] = R1
        self.state["last_ops"] = ops
        bad = [c for c in checks if not c["ok"]]
        msg = f"v{n}: " + "; ".join(done) + "."
        if failed:
            msg += " Couldn't: " + "; ".join(failed) + "."
        msg += (f" Checked on the timeline: {len(checks) - len(bad)}/{len(checks)} OK" +
                (" (" + "; ".join(f"{c['op']}: {c['what']}" for c in bad) + ")" if bad else "") + ".") if checks else ""
        if R1["notes"] and len(R1["notes"]) > len(R0.get("notes") or []):
            new = [x for x in R1["notes"] if x not in (R0.get("notes") or [])][:2]
            if new:
                msg += " Note: " + "; ".join(new)
        if self.do_export == "always":
            msg += "\n" + self.export()
        return msg

    # ------------------------------------------------------------------ templates
    def _template_request(self, message, turn):
        """A CapCut template link, or "use the X template" / "make it like the X template": the edit is recut on it (a
        question with a link gets what the template is, with the recut on offer). None when the message is not that."""
        from ai_pc.video import template as TP
        from ai_pc.video import template_meta as TM
        raw = " ".join(str(message or "").split())
        link = TEMPLATE_LINK.search(raw)
        if link:
            src = link.group(0).rstrip(").,!?;:'\"")
            rest = (raw[:link.start()] + " " + raw[link.end():]).strip()
            try:
                tpl = TP.resolve(src, self.planner, log=lambda *a: None)
            except TM.NotAllowed as e:
                turn["intents"].append("impossible")
                return {"reply": f"I can't read that link: {e}. Paste the template's own page (capcut.com/template-detail/...), a screenshot of it, "
                                 "or a video of the template."}
            except Exception as e:  # noqa: BLE001  (offline, a changed page...)
                turn["intents"].append("impossible")
                return {"reply": f"I couldn't read that template ({type(e).__name__}: {str(e)[:100]}). A screenshot of its page or a video of it works too."}
            nr = QE.normalize(rest)
            if rest.rstrip().endswith("?") or (QUESTION.search(nr) and not POLITE.match(nr)):
                turn["intents"].append("question")
                text = self._template_text(tpl) + "\nWant me to recut your edit on it?"
                self.state["pending"] = self.state["last_options"] = {"question": text, "options": [{"label": f"use {tpl['name']}", "ops": [self._use_op(tpl)]}]}
                return {"reply": text}
            turn["intents"].append("change")
            rest = TEMPLATE_WORDS.sub(" ", rest).strip(" ,.;:")
            return self._use_with(tpl, rest if re.search(r"[a-z]{3,}", FILLER.sub(" ", rest.lower())) else None, message, turn)
        m = TEMPLATE_USE.search(raw.lower())
        if not m or QUESTION.match(raw.lower()) and not POLITE.match(raw.lower()):
            return None
        words = (m.group(1) or m.group(2) or "").strip()
        rest = (raw[:m.start()] + " " + raw[m.end():]).strip(" ,.;:")
        rest = rest if re.search(r"[a-z]{3,}", FILLER.sub(" ", rest.lower())) else None
        tpl = self._find_template(words)
        k = ORDINAL.get(words.lower())
        offered = [o for o in (self.state.get("last_options") or {}).get("options") or [] if any(x.get("op") == "use_template" for x in o.get("ops") or [])]
        if tpl is None and k is not None and offered and -len(offered) <= k < len(offered):  # "use the second template" after a list
            tpl = TP.load(next(x["name"] for x in offered[k]["ops"] if x.get("op") == "use_template"))
        if tpl is None:
            turn["intents"].append("ask")
            lib = TP.library()
            if not lib:
                return {"reply": "There are no templates saved yet. Paste a CapCut template's link (capcut.com/template-detail/...), a screenshot of its "
                                 "page, or a video of it, and I'll recut the edit on it."}
            kind, payload = self._templates(" ".join([self.state["request"], words]))
            head = "Which template?" if words.lower() in GENERIC_NAME or not words else f"I have no template called '{words}'."
            if payload.get("options"):
                self.state["pending"] = self.state["last_options"] = {"question": payload["text"], "options": payload["options"]}
            return {"reply": head + " " + payload["text"]}
        turn["intents"].append("change")
        return self._use_with(tpl, rest, message, turn)

    def _use_with(self, tpl, rest, message, turn):
        """The recut and what else the message asks ("... and make the title gold") as ONE version when the rules read
        the rest; otherwise the rest is handled after, as its own turn."""
        ops, later = [self._use_op(tpl)], rest
        if rest:
            r = QE.parse(_strip_lead(QE.normalize(rest)), self._ctx())
            if r.get("ops"):
                ops += r["ops"]
                later = None
        return {"reply": self._change(ops, message, turn), "rest": later}

    def _find_template(self, words):
        """The library's template a client names: by its name or its page title, typos and 'slowmo'/'slow motion' alike."""
        from ai_pc.video import template as TP
        w = " ".join(str(words or "").lower().replace("_", " ").split())
        if not w or w in GENERIC_NAME:
            return None

        def toks(x):
            return set(re.findall(r"[a-z0-9]+", QE.normalize(str(x or "").replace("_", " ")))) - {"the", "a", "template", "edit"}
        q = toks(w)
        best, bs = None, 0.0
        for nm in TP.library():
            t = TP.load(nm) or {}
            for cand in (nm, (t.get("meta") or {}).get("title")):
                cw = toks(cand)
                if not cw or not q:
                    continue
                sc = len(q & cw) / len(q | cw)
                if q <= cw or cw <= q:
                    sc = max(sc, 0.8)
                if sc > bs:
                    best, bs = t, sc
        return best if bs >= 0.5 else None

    def _use_op(self, tpl):
        return {"op": "use_template", "name": tpl["name"], "label": ((tpl.get("meta") or {}).get("title") or tpl["name"]).strip(),
                "slots": len(tpl.get("slots") or []), "seconds": tpl.get("seconds")}

    def _template_text(self, tpl):
        """What a template is, in two or three sentences."""
        from ai_pc.video import trends as TR
        m = tpl.get("meta") or {}
        head = f"'{(m.get('title') or tpl['name']).strip()}'" + (f" by {m['author'].strip()}" if m.get("author") else "") + \
            f": {len(tpl.get('slots') or [])} clips, {float(tpl['seconds']):.1f} s" + (f", {m['aspect']}" if m.get("aspect") else "") + \
            (f", {int(m['uses']):,} uses" if m.get("uses") else "") + "."
        bits = [head]
        style = TR.short(tpl.get("techniques") or {})
        if style:
            bits.append(f"Style: {style}.")
        bits.append("An exact copy (learned from its video)." if tpl.get("exact", True) else
                    "Made from its page: the clip count and length are exact, the cuts are even beats (send a video of it for its exact frames).")
        vids = [a for a in self.analyses.values() if a.get("kind") in ("video", "image") and not str(a.get("file", "")).startswith(("music_", "sfx_"))]
        moments = sum(1 if a.get("kind") == "image" else max(1, int(float(a.get("seconds") or 0) // 1.5)) for a in vids)
        if vids and len(tpl.get("slots") or []) > moments:
            bits.append(f"It needs {len(tpl['slots'])} moments and your footage has about {moments}: some would repeat.")
        return " ".join(bits)

    def _templates(self, q):
        """Which saved templates fit this edit's footage and the words asked, as options to recut on."""
        from ai_pc.video import template as TP
        if not TP.library():
            return "question", {"text": "No templates saved yet. Paste a CapCut template's link (capcut.com/template-detail/...), a screenshot of its "
                                        "page, or a video of it, and I'll add it and recut the edit on it."}
        cur = self.version["design"].get("template")
        lines, opts = [], []
        for x in TP.suggest(q, self.analyses, k=4):
            t = TP.load(x["name"]) or {}
            lines.append(f"{len(opts) + 1}) {x['name']}" + (f" ('{x['title'].strip()}')" if x.get("title") else "") +
                         f": {x['clips']} clips, {float(x['seconds']):.0f} s, {'exact' if x['exact'] else 'from its page'}" +
                         (f"; {x['why']}" if x["why"] != "no strong match" else "") + (" (in use now)" if x["name"] == cur else ""))
            opts.append({"label": x["name"], "ops": [self._use_op(t)]})
        return "catalog", {"text": "Templates that fit, best first:\n" + "\n".join(lines) +
                                   "\nSay e.g. 'use the 1st' to recut this edit on one, or paste a CapCut template link to add another.", "options": opts}

    def _switch_template(self, op):
        """(design, plan, what was done) for recutting this edit on a template, or why it could not be."""
        from ai_pc.video import template as TP
        from ai_pc.video import trends as TR
        tpl = TP.load(op["name"])
        if tpl is None:
            try:
                tpl = TP.resolve(op["name"], self.planner, log=lambda *a: None)
            except Exception as e:  # noqa: BLE001
                return f"could not use the template '{op['name']}' ({str(e)[:100]})"
        cur = self.version["design"]
        if cur.get("template") == tpl["name"]:
            return f"the edit already follows '{tpl['name']}'"
        texts = sorted((e for e in self.version["plan"].get("edits") or [] if e.get("type") == "text" and e.get("text")),
                       key=lambda e: float(e.get("start") or 0))
        main = QE.main_title(texts)
        own = [main[0]["text"]] if main else (cur.get("texts") or None)
        req = " ".join([self.state["request"]] + [t["user"] for t in self.state["turns"]])
        d = {"template": tpl["name"], "template_source": tpl.get("source"), "pins": {}, "avoid_files": list(cur.get("avoid_files") or []),
             "music": None, "canvas": None, "texts": own, "speed": None}
        try:
            plan, info = TP.refill(d, self.analyses, req, log=lambda *a: None, chat=True, with_info=True)
        except Exception as e:  # noqa: BLE001
            return f"could not fill the template ({type(e).__name__}: {str(e)[:80]})"
        for a in self.analyses.values():  # its music bed is a file of this edit now
            if a.get("path") and a["path"] not in self.state["files"] and str(a.get("file", "")).startswith("music_"):
                self.state["files"].append(a["path"])
        op["slots"], op["seconds"] = len(plan["clips"]), tpl["seconds"]
        done = [f"recut on the template '{tpl['name']}' ({len(plan['clips'])} slots, {float(tpl['seconds']):.1f} s, " +
                ("its exact cut frames" if tpl.get("exact", True) else "made from its page: even slots on the beat") + ")"]
        style = "; ".join(p for p in TR.short(tpl.get("techniques") or {}).split("; ") if p and "greeting" not in p)  # the greeting: its own tip below
        if style:
            done.append(f"style: {style}")
        if own:
            done.append(f"your title '{own[0]}' kept")
        g = TP.settings(tpl, "").get("greeting")
        if g:
            done.append(f"its tags suggest the greeting '{g}' (say 'add {g}')")
        return d, plan, done

    def _tpl_speed(self, b):
        """Slow motion / speed ramps / normal speed on every slot of a template edit, or None."""
        from ai_pc.video import template as TP
        if not re.search(r"slow ?-?mo|slow motion|\bspeed\b|velocity|\bramps?\b|real ?-?time|\bfaster\b|\bslower\b", b):
            return None
        if re.search(r"\b(?:cuts?|cutting|pace|pacing|music|song|beat|tempo|bpm|transitions?|text|title)\b", b):
            return None
        if re.search(r"\b(?:no|remove|without|drop|kill|stop|get rid of|take (?:out|off)|turn off|don'?t (?:want|need|like))\b.{0,20}"
                     r"\b(?:slow ?-?mo|slow motion|speed ramps?|ramps?|velocity)\b|\b(?:normal|regular|original|real ?-?time|natural) speed\b|\bin real ?-?time\b", b):
            return {"op": "tpl_speed", "value": "normal"}
        if re.search(r"\b(?:speed ramps?|velocity|ramps?)\b", b):
            return {"op": "tpl_speed", "value": "ramp"}
        d = self.version["design"]
        st = TP.settings(TP.load(d["template"]) or {}, "")
        sp = d.get("speed")
        eff = 1.0 if sp in ("normal", "ramp") else float(sp) if sp is not None else (1.0 if st.get("ramp") else float(st.get("speed") or 1.0))
        if re.search(r"\b(?:more|even|extra|super|very|much)\b.{0,12}\b(?:slow ?-?mo|slow motion|slow(?:er)?)\b|\bslower\b", b):
            return {"op": "tpl_speed", "value": round(max(0.25, eff * 0.7), 2) if eff < 0.95 else 0.45}
        if eff < 0.95 and re.search(r"\b(?:less|not so|not as)\b.{0,12}\b(?:slow ?-?mo|slow motion|slow)\b|\bfaster\b", b):
            v = round(eff / 0.7, 2)
            return {"op": "tpl_speed", "value": "normal" if v >= 0.95 else v}
        if re.search(r"\b(?:slow ?-?mo|slow motion)\b", b):
            return {"op": "tpl_speed", "value": 0.5 if eff >= 0.95 else round(eff, 2)}
        return None

    def _greeting(self):
        """The greeting this edit's occasion suggests: its template's tags, else the request ('eid video' -> Eid Mubarak)."""
        from ai_pc.video import template as TP
        from ai_pc.video import trends as TR
        d = self.version["design"]
        if d.get("template"):
            g = TP.settings(TP.load(d["template"]) or {}, "").get("greeting")
            if g:
                return g
        return TR.techniques("", (), " ".join([self.state["request"]] + [t["user"] for t in self.state["turns"]]))["settings"].get("greeting")

    def _new_media(self, files, turn):
        from pathlib import Path
        new = [str(Path(f)) for f in files if str(Path(f)) not in self.state["files"]]
        if not new:
            return ""
        an = AN.analyze(new, planner=self.planner, log=lambda *a: None)
        self.analyses.update(an)
        self.state["files"] += new
        ops = [{"op": "more_of", "file": a["file"], "n": 2} for a in an.values() if a.get("kind") in ("video", "image")]
        turn["intents"].append("media")
        return self._change(ops, f"new media: {', '.join(Path(f).name for f in new)}", turn) if ops else f"Added {len(new)} file(s)."

    # ------------------------------------------------------------------ versions
    def undo(self):
        v = self.version
        if v["parent"] is None:
            return "Nothing to undo: this is the first version."
        self.state["cur"] = v["parent"]
        return f"Undone: back to v{self.state['cur']} (before: {'; '.join(v['done'])[:120]})."

    def redo(self):
        kids = [x["v"] for x in self.state["versions"] if x["parent"] == self.state["cur"]]
        if not kids:
            return "Nothing to redo."
        self.state["cur"] = kids[-1]
        return f"Redone: v{self.state['cur']} ({'; '.join(self.version['done'])[:120]})."

    def goto(self, n, what=None):
        if not 0 <= n < len(self.state["versions"]):
            return f"There is no v{n}; versions go from v0 to v{len(self.state['versions']) - 1}."
        self.state["cur"] = n
        return f"Back to v{n}" + (f" ({what})" if what else f" ({'; '.join(self.version['done'])[:120]})") + ". Changes from here make a new version."

    def history(self):
        v = self.version
        if v["parent"] is None:
            return "This is the first version: nothing changed yet."
        bad = [c for c in v.get("checks") or [] if not c["ok"]]
        return (f"v{v['v']} (from v{v['parent']}, you said: '{v['said']}'): " + "; ".join(v["done"]) +
                (". Not done: " + "; ".join(v["failed"]) if v.get("failed") else "") +
                (". Not confirmed on the timeline: " + "; ".join(c["op"] for c in bad) if bad else "") + ".")

    def versions_text(self):
        lines = []
        for x in self.state["versions"]:
            mark = " <- now" if x["v"] == self.state["cur"] else ""
            lines.append(f"  v{x['v']}: {x['seconds']:.0f} s, " + ("; ".join(x["done"]))[:90] + mark)
        return f"{len(self.state['versions'])} versions:\n" + "\n".join(lines)

    def compare(self, text):
        nums = [int(x) for x in re.findall(r"\bv(?:ersion)? ?(\d+)\b", text)]
        if re.search(r"\b(?:original|first|beginning|start|scratch|started)\b", text) and 0 not in nums:
            nums = [0] + nums
        a = nums[0] if nums else (self.version["parent"] if self.version["parent"] is not None else 0)
        b = nums[1] if len(nums) > 1 else self.state["cur"]
        if not all(0 <= x < len(self.state["versions"]) for x in (a, b)):
            return "I can only compare versions that exist."
        Ra, Rb = self.resolved(a), self.resolved(b)

        def summ(R):
            m = next((e for e in R["edits"] if e["id"] == "music"), {})
            return {"length": f"{R['end']:.1f} s", "shots": len(R["clips"]), "format": f"{R['canvas'][0]}x{R['canvas'][1]}",
                    "music": f"{str(m.get('file', 'none')).split('_')[1] if str(m.get('file', '')).startswith('music_') else m.get('file', 'none')} vol {m.get('volume')}",
                    "texts": ", ".join(f"'{e['text'][:16]}'" for e in R["edits"] if e["type"] == "text")[:120],
                    "transitions": ", ".join(sorted({EX._name(e['item']) for e in R["edits"] if e["type"] == "transition"})) or "none",
                    "look": ", ".join(EX._name(e["item"]) for e in R["edits"] if e["type"] == "filter") or "none",
                    "effects": sum(1 for e in R["edits"] if e["type"] in ("effect", "shake", "zoom"))}
        sa, sb = summ(Ra), summ(Rb)
        diff = [f"{k}: {sa[k]} -> {sb[k]}" for k in sa if sa[k] != sb[k]]
        return f"v{a} vs v{b}: " + ("; ".join(diff) if diff else "no visible difference") + "."

    def _snap(self, v, what):
        x = self.state["versions"][v]
        d, p = x["design"], x["plan"]
        if what == "music":
            m = next((e for e in p.get("edits") or [] if e.get("id") == "music"), {})
            return {"design": d.get("music"), "volume": m.get("volume"), "file": m.get("file")}
        if what in ("title", "label", "cta", "caption", "text"):
            roles = QE.text_roles(p)
            return [copy.deepcopy(e) for e in p.get("edits") or [] if e.get("type") in ("text", "captions")
                    and (what == "text" or roles.get(str(e.get("id"))) == what)]
        if what in ("transition", "look", "sfx"):
            t = {"look": "filter"}.get(what, what)
            return [copy.deepcopy(e) for e in p.get("edits") or [] if e.get("type") == t]
        if what in ("shake", "zoom", "flash", "glitch", "effects", "texture"):
            kind = {"effects": "effect"}.get(what, what)
            return [copy.deepcopy(e) for e in p.get("edits") or [] if e.get("type") not in ("text", "captions", "audio", "sfx", "transition", "filter", "animation")
                    and kind in QE.fx_kinds(e, p)]
        if what == "length":
            return x.get("seconds")
        if what == "pace":
            return d.get("pace") or 1
        if what == "canvas":
            return d.get("canvas")
        if what == "shot":
            return {"shots": d.get("shots"), "avoid": d.get("avoid_files") or []}
        return None

    @staticmethod
    def _sig(snap, what):
        if isinstance(snap, list):
            keys = ("text", "color", "size", "font", "position", "name", "after", "duration", "strength", "to", "on", "start", "sound", "at", "params")
            return json.dumps(sorted(json.dumps({k: e.get(k) for k in keys}, sort_keys=True, ensure_ascii=False) for e in snap), ensure_ascii=False)
        return json.dumps(snap, sort_keys=True, ensure_ascii=False, default=str)

    ASPECTS = {"font": ("font",), "colour": ("color",), "size": ("size",), "position": ("position",), "words": ("text",),
               "animation": ("intro", "outro", "loop")}

    def restore(self, what, text=""):
        """One element (music, title, labels, look, transitions, shakes, length...) back to how it was in an earlier version:
        the latest earlier version where it differs, or the one whose words match ("the red title", "the chill music").
        For texts, one aspect can come back alone ("the previous title FONT was nicer" keeps the new words)."""
        what = {"effects": "effects", "speed": "shot", "clip_audio": "shot", "voice": "music"}.get(what, what)
        aspect = None
        if what in ("title", "label", "cta", "caption", "text"):
            aspect = next((a for a, pat in (("font", r"\bfonts?|typeface"), ("colour", r"\bcolou?rs?\b"), ("size", r"\bsize|bigger|smaller"),
                                            ("position", r"\bposition|place|where it was"), ("words", r"\bwords|wording|text was|it said|name"),
                                            ("animation", r"\banimation|intro|how it came in")) if re.search(pat, text)), None)
            if what == "text" and aspect:
                what = "title" if re.search(r"\btitle", text) else "label" if re.search(r"\blabel", text) else "text"
        fields = self.ASPECTS.get(aspect)
        cur = self._snap(self.state["cur"], what)
        if cur is None:
            return f"I can't bring back the {what} of an earlier version; tell me how it should be instead."

        def sig_of(sn):
            if fields and isinstance(sn, list):
                return json.dumps(sorted(json.dumps({"id": e.get("id"), **{f: e.get(f) for f in fields}}, sort_keys=True, ensure_ascii=False) for e in sn))
            return self._sig(sn, what)
        sig = sig_of(cur)
        generic = {"old", "previou", "earlier", "back", "bring", "put", "befor", "better", "restor", "return", "like", "liked", "was", "were",
                   "music", "song", "title", "label", "text", "transition", "look", "colour", "color", "filter", "go", "want", "one",
                   "version", "undo", "revert", "nicer", "cooler", "prettier", "good", "perfect", "prefer", "preferr", "first", "original",
                   "font", "size", "position", "word", "animation", "it", "them", "keep", "though", "tho", "shake", "zoom", "flash",
                   "glitch", "effect", "transit", "sound", "track", "beat", "grade", "colours", "length", "pace", "speed", "shot",
                   "clip", "versions", "sounded", "looked", "lik", "realli", "actual", "thought", "felt", "much", "way", "kind"}
        words = [w for w in QE.content_words(text) if w not in generic and not w.startswith(("previou", "prefer", "restor", "revert"))]
        chain = self._lineage()[1:] + [i for i in range(len(self.state["versions"]) - 1, -1, -1) if i not in self._lineage()]
        if re.search(r"\b(?:first|original|very first)\b", text):
            chain = [0]
        vn = re.search(r"\bv(?:ersion)? ?(\d+)\b", text)
        if vn and int(vn.group(1)) < len(self.state["versions"]):
            chain = [int(vn.group(1))]
            if sig_of(self._snap(chain[0], what)) == sig:
                return f"The {what}{' ' + aspect if aspect else ''} is already as it was in v{chain[0]}."
        pick = None
        for i in chain:
            s = self._snap(i, what)
            if s is None or sig_of(s) == sig:
                continue
            if words:
                blob = (json.dumps(s, ensure_ascii=False, default=str) + " " + " ".join(self.state["versions"][i]["done"]) + " " +
                        str(self.state["versions"][i]["said"] or "")).lower()
                hexes = {QE.COLOURS[w] .lower() for w in QE.COLOURS if w in words}
                if not all(w in blob for w in words if w not in QE.COLOURS) or (hexes and not any(h in blob for h in hexes)):
                    continue
            pick = i
            break
        if pick is None:
            return f"The {what} hasn't changed in earlier versions" + (" in that way" if words else "") + "; tell me how it should be instead."
        snap = self._snap(pick, what)
        if what == "music":
            ops = [{"op": "music", "set": snap["design"]}] + ([{"op": "audio", "who": "music", "set": {"volume": snap["volume"]}}] if snap.get("volume") is not None else [])
        elif what in ("title", "label", "cta", "caption", "text"):
            ops = [{"op": "restore", "kind": "text", "role": what, "edits": snap, **({"fields": list(fields)} if fields else {})}]
        elif what in ("transition", "sfx"):
            ops = [{"op": "restore", "kind": what, "edits": snap}]
        elif what == "look":
            ops = [{"op": "restore", "kind": "filter", "edits": snap}]
        elif what in ("shake", "zoom", "flash", "glitch", "effects", "texture"):
            ops = [{"op": "restore", "kind": what, "edits": snap}]
        elif what == "length":
            ops = [{"op": "length", "seconds": snap}]
        elif what == "pace":
            ops = [{"op": "pace_set", "value": snap}]
        elif what == "canvas":
            ops = [{"op": "canvas", "value": snap}]
        elif what == "shot":
            ops = [{"op": "shots_set", **snap}]
        else:
            return f"I can't bring back the {what}; tell me how it should be instead."
        msg = self._change(ops, f"{what} as in v{pick}", getattr(self, "_turn", {"ops": []}))
        return f"{what.capitalize()}{' ' + aspect if aspect else ''} as in v{pick}. " + msg

    # ------------------------------------------------------------------ export
    def export(self):
        v = self.version
        if not self.do_export:
            return f"Export is off in this chat; the JianYing draft {v.get('draft') or self.state['base']} (v{v['v']}) is ready."
        if v.get("export"):
            return f"v{v['v']} is already exported: {v['export']}"
        from ai_pc.video import verify as V
        from ai_pc.video.studio import Studio
        R = self.resolved()
        if not v.get("draft"):
            from ai_pc.video import jybuild as JB
            M = JB.build(R, name=f"{self.state['drafts_prefix']}_v{v['v']}")
            v["draft"] = M["draft"]
        else:
            M = getattr(self, "_M", None)
            if not M or M.get("draft") != v["draft"]:
                from ai_pc.video import jybuild as JB
                M = JB.build(R, name=v["draft"])
        st = Studio(self.planner, log=self.log, export=True)
        sess = {"map": M, "plan": v["plan"], "resolved": R}
        r = st._export(sess, self.analyses)
        if not r.get("ok"):
            return f"Export failed: {r.get('error')}"
        v["export"] = r["path"]
        rep = V.verify(r["path"], sess["map"], planner=self.planner, log=lambda *a: None)
        c = rep["counts"]
        return f"Exported v{v['v']}: {r['path']} (checks at the edit points: {c['pass']} pass, {c['warn']} warn, {c['fail']} fail)."
