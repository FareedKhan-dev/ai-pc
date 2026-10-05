"""Which program a message is for, and the steps in it ("add a glow to my video, then send it to Slack #team").

Rules first (cheap, instant, testable): words that name a program or its work, the kinds of the files sent, what the 88
program modules recognise by their own rules, and the conversation in progress ("make it stronger" goes on with the
video). The model is asked only when the rules cannot tell or two programs tie, and it only chooses among the programs.

  steps = plan("add a glow effect to my video and then send it to slack", ctx)
      -> [{"lane": "video", "message": "add a glow effect to my video"}, {"lane": "hub", "message": "send it to slack"}]
"""

import json
import re

from ai_pc.assistant.artifacts import kind_of

I = re.I
SIGNALS = {
    "hub": [
        (r"\bslack\b|\b(?:ms |microsoft )?teams\b|\btrello\b|\basana\b|\bnotion\b|\bjira\b|\bhubspot\b|\bzoom\b", 10),
        (r"\boutlook\b|\bgmail\b|\binbox\b|\be-?mails?\b|\bmail (?:it|this|them|the)\b", 9),
        (r"\btelegram\b|\bone ?drive\b|\bgoogle drive\b|\bmy drive\b|\bfigma\b|\bcanva\b", 8),
        (r"\bwhats ?app\b", 7),
        (r"\bbrief me\b|\bmy (?:day|meetings|calendar|schedule)\b|\bwhat'?s new in\b|\bunread\b", 8),
        (r"(?:^|\s)#[a-z][\w-]*", 6),
        (r"\b(?:send|share|forward)\b.*\bto\s+(?:@\w+|[\w.+-]+@[\w-]+\.[\w.]+)", 7),
    ],
    "social": [
        (r"\binstagram\b|\binsta\b|\bfacebook\b|\bfb\b|\btik ?tok\b|\byou ?tube\b|\blinked ?in\b|\btwitter\b|\bthreads\b|\bx\.com\b", 6),
        (
            r"\b(?:post|upload|publish|share|schedule|put)\b.*\b(?:on|to)\s+(?:my\s+)?(?:instagram|insta|facebook|fb|tik ?tok|you ?tube|"
            r"linked ?in|twitter|threads|x)\b",
            11,
        ),
    ],
    "accounts": [
        (
            r"\binvoices?\b|\bbills?\b|\bpayments?\b|\bowes?\b|\bprofit\b|\bledger\b|\bsales tax\b|\bgst\b|\bfbr\b|\btally(?:prime)?\b|"
            r"\bquick ?books\b|\bxero\b|\bzoho(?: books)?\b|\bexpenses?\b|\breceivables?\b|\bpayables?\b|\btrial balance\b|\bbalance sheet\b|"
            r"\bp ?& ?l\b|\bkhata\b|\bpaid\b.*\b(?:rs|lakh|thousand|\d)",
            7,
        )
    ],
    "video": [
        (
            r"\beffects?\b|\btransitions?\b|\bslow[- ]?mo(?:tion)?\b|\bspeed ramp\b|\bglitch\b|\bglow\b|\bshake\b|\blightning\b|\bsparkles?\b|"
            r"\bbeat ?sync\b|\bcinematic\b|\breels?\b|\bmontage\b|\bhighlights?\b|\bintro\b|\boutro\b|\bcapcut\b|\bjianying\b|\bvlog\b|"
            r"\bmusic video\b|\bcolou?r grad(?:e|ing)\b|\bzoom (?:in|out)\b|\bfade\b|\bedit (?:my|this|the|these) (?:video|clip|footage)s?\b",
            6,
        ),
        (r"\bfilters?\b|\bedit\b|\btext\b|\btitle\b|\bmusic\b", 2),
    ],
    "convert": [
        (
            r"\bconvert\b|\bcompress\b|\bsmaller\b|\bshrink\b|\breduce (?:the )?(?:file )?size\b|\bunder \d+ ?(?:mb|kb|gb)\b|\bfile size\b|"
            r"\bto (?:mp4|mov|gif|mp3|webm|wav|m4a|avi|mkv|ogg)\b|\bgif\b|\btrim\b|\bcut (?:the )?(?:first|last)\b|"
            r"\b(?:ready|fit) for (?:whats ?app|email|gmail|discord|instagram)\b|\bwill it play\b|\bextract (?:the )?audio\b|"
            r"\brecord (?:my )?screen\b|\bscreen recording\b|\b(?:1080|720|480)p\b|\b4k\b|\brotate (?:the )?video\b|\bframe ?rate\b|\bfps\b",
            7,
        )
    ],
    "sound": [
        (
            r"\bnois(?:e|y)\b|\bpauses?\b|\bums?\b|\buhs?\b|\bfiller words\b|\bnormali[sz]e\b|\bloudness\b|\bpodcast\b|\bvoice[- ]?over\b|"
            r"\btext to speech\b|\bread (?:it|this) (?:out|aloud)\b|\bcaptions?\b|\bsubtitles?\b|\btranscri(?:be|pt|ption)\b|\bmusic under\b|"
            r"\bbackground music\b|\bdeeper voice\b|\becho\b|\bhum\b|\bmy voice\b|\bclean (?:it |this |the )?(?:audio|sound|voice|recording)\b",
            7,
        ),
        (r"\blouder\b|\bquieter\b", 3),
    ],
    "photo": [
        (
            r"\bbright(?:er|en|ness)?\b|\bdark(?:er|en)?\b|\bcrop\b|\bremove (?:the )?background\b|\bbackground\b|\bpassport\b|\bblur\b|"
            r"\bwatermark\b|\benhance\b|\bsharpen\b|\bresize\b|\bstraighten\b|\bblack and white\b|\bb ?& ?w\b|\bretouch\b|\bred ?eye\b|"
            r"\bfaces?\b|\bfilters?\b|\bvintage\b|\bcontrast\b|\bsaturation\b|\bexposure\b|\bfix (?:it|this|the (?:photo|picture|image))\b",
            4,
        ),
        (r"\bphotos?\b|\bpictures?\b|\bpics?\b|\bselfies?\b|\bimages?\b", 3),
    ],
    "design": [
        (
            r"\b(?:visiting|business) cards?\b|\binstagram (?:post|story)\b|\bthumbnail\b|\bflyers?\b|\bposters?\b|\bcertificates?\b|\bbanners?\b|"
            r"\binvitations?\b|\bmenu card\b|\bbrochures?\b|\bsocial (?:media )?post\b|\bwedding card\b|\bletterhead\b|\b(?:eid|greeting) card\b",
            7,
        ),
        (r"\b(?:make|create|design)\b.*\b(?:post|story|thumbnail|card|flyer|poster|banner|certificate|invitation)\b", 9),
    ],
    "office": [
        (
            r"\bword (?:document|doc|file)\b|\bdocx\b|\breport\b|\bletter\b|\bapplication\b|\bassignment\b|\b(?:cv|resume)\b|\bessay\b|"
            r"\bnotice\b|\bmemo\b|\bproposal\b|\bpresentation\b|\bslides?\b|\bdeck\b|\bpower ?point\b|\bpptx\b|\bexcel\b|\bspreadsheet\b|"
            r"\bworkbook\b|\bxlsx\b|\bmarks? ?sheet\b|\btimetable\b|\bbudget\b|\bpdfs?\b|\bquotation\b",
            6,
        )
    ],
    "windows": [
        (
            r"\bdownloads?\b|\bmy (?:desktop|documents|pictures|videos|music)\b|\bfolders?\b|\bclean ?up my\b|\borgani[sz]e\b|"
            r"\bsort (?:my )?(?:files|downloads)\b|\brename\b|\bfind my\b|\bwhere is my\b|\bwallpaper\b|\bdark mode\b|\blight mode\b|"
            r"\bnight light\b|\bstart-?up (?:apps|programs)\b|\brecycle bin\b|\bduplicates?\b|\bbig(?:gest)? files\b|\bfree up space\b|"
            r"\bscreen (?:timeout|off)\b|\bpower (?:plan|mode)\b|\bdefault printer\b",
            6,
        )
    ],
    "cad": [
        (
            r"\bhouse plan\b|\bfloor plan\b|\bmarla\b|\bkanal\b|\bbedrooms?\b|\bdouble stor(?:e)?y\b|\bnaksha\b|\bautocad\b|\bdxf\b|\bdwg\b|"
            r"\blaser[- ]cut\b|\bplate with\b|\bflange\b|\bbracket\b|\bholes? of\b|\bpcd\b",
            7,
        )
    ],
    "three": [
        (r"\b3d\b|\bthree[- ]d\b|\bblender\b", 10),
        (
            r"\brender(?:ing)?\b|\bglb\b|\bgltf\b|\bmock-?ups?\b|\bon a (?:mug|box|bottle|laptop|t-?shirt|cup|phone)\b|\bturntable\b|"
            r"\bgoing round\b|\bfly ?(?:through|around)\b|\bfrom the street\b",
            7,
        ),
    ],
    "coding": [
        (
            r"\bcode\b|\bscript\b|\bprogram\b|\bwebsite\b|\bweb ?page\b|\blanding page\b|\bweb ?app\b|\bpython\b|\bjavascript\b|\bhtml\b|"
            r"\bcss\b|\bfix (?:this|the) (?:error|bug)\b|\btraceback\b|\berror:|\bbug\b|\bfunction\b|\b(?:figma|canva) (?:to|into) code\b|"
            r"\bfrom (?:this|my|the) (?:figma|canva) design\b",
            6,
        )
    ],
}
# the program modules that make template projects: they win over the coding lane only when named
CODING_MODULES = {"pycharm", "nodejs", "php", "clion", "goland", "rustrover", "flutter", "visualstudio", "intellij", "androidstudio", "vscode"}
CODING_NAMES = re.compile(
    r"\bpycharm\b|\bwebstorm\b|\bphpstorm\b|\bclion\b|\bgoland\b|\brustrover\b|\bvisual studio\b|\bintellij\b|"
    r"\bandroid studio\b|\bvs ?code\b|\bflutter\b|\bxampp\b|\blaravel\b|\bcmake\b|\bcargo\b|\bmaven\b|\bgradle\b|\bdotnet\b|"
    r"\.net\b|\bgo\.mod\b|\bpubspec\b|\bpackage\.json\b|\bc\+\+|\bcalled\b|\bnamed\b|\bapk\b|\bandroid app\b",
    I,
)
# modules whose words are everyday words: their claim is weak unless the program is named
BROAD = {
    "calendar",
    "notes",
    "web",
    "desktop",
    "media",
    "printing",
    "maps",
    "codes",
    "contacts",
    "quiz",
    "cite",
    "diagrams",
    "ocr",
    "pccare",
    "database",
    "backup",
    "music",
    "stats",
    "grammar",
    "ebook",
}
BROAD_VERBS = {
    "printing": r"^\s*(?:please\s+)?print\b|\bprint (?:it|this|that|them|the)\b",
    "ocr": r"\bocr\b|\b(?:read|extract|copy) (?:the )?text\b",
    "media": r"^\s*(?:please\s+)?play\b|\bplaylist\b",
    "maps": r"\bdirections?\b|\broute\b|\bkml\b|\bgpx\b|\bhow far\b",
    "codes": r"\bqr\b|\bbar ?code\b",
    "contacts": r"\bvcard\b|\bcontact card\b|\b\.vcf\b",
    "calendar": r"\binvite\b|\.ics\b|\bremind me\b|\breminder\b",
    "backup": r"\bback ?up\b",
    "quiz": r"\bquiz(?:zes)?\b|\bmcqs?\b",
    "cite": r"\bcit(?:e|ation)s?\b|\bbibliography\b|\breferences? (?:list|for)\b",
    "diagrams": r"\bflow ?chart\b|\borg chart\b|\bmind ?map\b",
    "pccare": r"\binstall\b|\bupdates?\b|\bdisk space\b|\bantivirus\b|\bwi-?fi\b|\bbattery\b|\buninstall\b",
    "web": r"https?://",
    "desktop": r"\bscreenshot\b|\bclipboard\b",
    "notes": r"^\s*(?:note|remember|to-?do|task|jot down)\s*:",
    "database": r"\baccess (?:database|db)\b|\bsqlite\b|\.accdb\b",
    "ebook": r"\bepub\b|\be-?book\b",
    "music": r"^\s*(?:melody|tune|notes|music)\s*(?:'[^']*')?\s*:",
    "grammar": r"\bgrammar\b|\bspelling\b|\bproof ?read\b",
    "stats": r"\bt-?test\b|\banova\b|\bregression\b|\bcorrelation\b|\bchi-?square\b|\bdescriptives?\b|\bspss\b|\bcronbach\b",
}
FOLLOW = re.compile(
    r"^\s*(?:and |now |also |ok(?:ay)?,? |please |can you |could you )?(?:make|change|add|remove|delete|put|move|turn|set|use|try|"
    r"redo|undo|again|more|less|bigger|smaller|louder|quieter|brighter|darker|faster|slower|longer|shorter|instead|actually|"
    r"no\b|not\b|keep|save|export|show|compare|what|how|why|go back|previous|stronger|weaker|lighter|heavier)\b",
    I,
)
POINTERISH = re.compile(r"\b(?:it|this|that|them|these|those|the same|again|instead|more|less|bigger|smaller|stronger|weaker)\b", I)
UNDO = re.compile(r"^\s*(?:undo|redo|go back|previous version|compare|show (?:me )?(?:the )?versions?|versions?)\b", I)
SAVE_TO = re.compile(r"\b(?:save|export|put)\b.*\b(?:to|on|in)\s+(?:my\s+)?(?:desktop|downloads|documents|pictures|videos)\b", I)
SPLIT = re.compile(r"\s*,?\s*\b(?:and then|then|after that|afterwards|and after that|once (?:it'?s|that'?s|you'?re) done)\b\s*,?\s*", I)
AND_ACTION = re.compile(r"\s+and\s+(?=(?:send|post|share|email|e-mail|mail|upload|forward|publish|whatsapp|message|print|dm)\b)", I)
KIND_LANES = {
    "video": {"video": 3, "convert": 2, "sound": 1, "social": 1},
    "image": {"photo": 3, "design": 1, "social": 1},
    "audio": {"sound": 3, "convert": 1},
    "document": {"office": 4},
    "slides": {"office": 4},
    "sheet": {"office": 4},
    "pdf": {"office": 4},
    "drawing": {"cad": 3},
    "model": {"three": 3},
}


def split(message):
    """'X, then Y and send it to Z' -> ['X', 'Y', 'send it to Z'] (only where a new action starts)."""
    parts = [p.strip(" ,.") for p in SPLIT.split(message) if p and p.strip(" ,.")]
    out = []
    for p in parts:
        out += [q.strip(" ,.") for q in AND_ACTION.split(p) if q.strip(" ,.")]
    return out or [message.strip()]


def _norm(text):
    return re.sub(r"[\s\-_.']", "", text.lower())


_NAMES = None


def program_names():
    """{normalised program name: module} for the 88 program modules (their NAME and the program names in their label)."""
    global _NAMES
    if _NAMES is None:
        _NAMES = {}
        try:
            from ai_pc.apps import all_modules

            for m in all_modules():
                if m.NAME in BROAD:
                    continue
                names = {m.NAME} | {x.strip() for x in re.split(r"[,/]| and ", re.split(r":", m.LABEL)[0]) if x.strip()}
                for n in names:
                    n = re.sub(r"\(.*?\)", "", n).strip()
                    if len(_norm(n)) >= 3:
                        _NAMES.setdefault(_norm(n), m.NAME)
        except Exception:  # noqa: BLE001
            pass
    return _NAMES


def named_program(message):
    """The program module a message names outright ('musescore it', '7zip pack ...'), or None."""
    words = _norm(message)
    best = None
    for n, mod in program_names().items():
        if n in words and (best is None or len(n) > len(best[0])):
            best = (n, mod)
    return best[1] if best else None


def score(message, files=(), active=None, apps_claim=None, refs=(), editing=None, known=()):
    """{lane: score} and the program module that claims it (for 'apps'), with a short why per lane.
    files: sent with this message; refs: files it points at ('it' -> the last video), which count half; active: the program
    used last ('undo' is its); editing: the program last used to make something (edit follow-ups are its); known: the
    kinds of every file in the chat."""
    s, why = {}, {}
    for lane, sigs in SIGNALS.items():
        hits = []
        for pat, w in sigs:
            m = re.search(pat, message, I)
            if m:
                hits.append((w, m.group(0).strip()))
        if hits:
            hits.sort(reverse=True)
            s[lane] = hits[0][0] + 0.5 * (len(hits) - 1)
            why[lane] = hits[0][1]
    # what people mean by a program's name in someone else's words
    if (
        "social" in s
        and re.search(r"\b(?:make|create|design)\b.*\b(?:post|story|thumbnail|card|flyer|poster|banner)\b", message, I)
        and not re.search(
            r"\b(?:post|upload|publish|share|schedule|put)\b.*\b(?:on|to)\s+(?:my\s+)?(?:instagram|insta|facebook|fb|tik ?tok|you ?tube|linked ?in|twitter|threads|x)\b",
            message,
            I,
        )
    ):
        s["social"] -= 4  # "make an instagram post" is a design to make, not a post to publish
    if "hub" in s and "social" in s and why.get("hub", "").strip().startswith("#"):
        s["hub"] -= 4  # '#eid' next to Instagram is a hashtag, not a Slack channel
    if (
        "hub" in s
        and "convert" in s
        and re.search(r"\b(?:ready|fit) for (?:whats ?app|email)\b", message, I)
        and not re.search(r"\b(?:send|share|forward|post)\b", message, I)
    ):
        s["hub"] -= 5
    if "office" in s and "accounts" in s and re.search(r"\binvoices?\b", message, I) and not re.search(r"\bword\b|\bdocx\b|\bdocument\b", message, I):
        s["office"] -= 3  # an invoice is bookkeeping unless a Word document is asked for
    if "three" in s and "cad" in s and re.search(r"\b3d\b|\bthree[- ]d\b|\bblender\b", message, I):
        s["cad"] -= 3
    kinds = {kind_of(f) for f in files}
    for k in kinds:
        for lane, w in KIND_LANES.get(k, {}).items():
            s[lane] = s.get(lane, 0) + w
            why.setdefault(lane, f"a {k} file")
    rkinds = {kind_of(f) for f in refs} - kinds
    for k in rkinds:
        for lane, w in KIND_LANES.get(k, {}).items():
            s[lane] = s.get(lane, 0) + w / 2
            why.setdefault(lane, f"the {k} it points at")
    allk = kinds | rkinds
    if "convert" in s and allk and not allk & {"video", "audio", "image"}:
        s["convert"] -= 5  # converting a 3D model or a document is the 3D or Office program's job
        if "model" in allk:
            s["three"] = s.get("three", 0) + 5
            why["three"] = "converting a 3D file"
        if allk & {"document", "slides", "sheet", "pdf"}:
            s["office"] = s.get("office", 0) + 4
            why["office"] = "converting a document"
    have = kinds | set(known)
    if "photo" in s and "image" not in have and not re.search(r"\bphotos?\b|\bpictures?\b|\bpics?\b|\bselfies?\b|\bimages?\b", message, I):
        s["photo"] -= 2  # photo words with no photo anywhere
    if "video" in s and "video" not in have and "image" not in have and not re.search(r"\bvideos?\b|\bclips?\b|\breels?\b|\bfootage\b", message, I):
        s["video"] -= 2
    claim = apps_claim(message, list(files) + list(refs)) if apps_claim else None
    outright = named_program(message)
    if outright and not claim:
        claim = outright  # named, though its rules want more ('musescore it' before a melody): its own chat explains
    if claim:
        named = (
            outright == claim
            or re.search(rf"\b{re.escape(claim)}\b", message, I)
            or re.search(r"\b" + re.escape(claim_word(claim)) + r"\b", message, I)
        )
        w = 12 if named else (4 if claim in BROAD else 8)
        if claim in BROAD and re.search(BROAD_VERBS.get(claim, r"(?!)"), message, I):
            w = max(w, 9)  # 'print it', 'make a qr code': the module's own action word
        if claim in CODING_MODULES and not CODING_NAMES.search(message):
            w = min(w, 5)  # "make a python program that ..." is the coding lane's to write
        s["apps"] = max(s.get("apps", 0), w)
        why["apps"] = claim
    if active and UNDO.search(message):
        s[active] = s.get(active, 0) + 12
        why[active] = "undo / versions"
    elif editing or active:
        on = editing or active
        if SAVE_TO.search(message):
            s[on] = s.get(on, 0) + 8
            why[on] = "saving what was made"
        elif FOLLOW.search(message) or POINTERISH.search(message):
            strongest_other = max([v for k, v in s.items() if k != on] or [0])
            if strongest_other < 8:
                s[on] = s.get(on, 0) + 6
                why[on] = "goes on with what we were doing"
    return s, why


_WORDS = {}


def claim_word(module):
    """The program name a module answers to (its NAME, or the first words of its label)."""
    if module not in _WORDS:
        try:
            from ai_pc.apps import load

            label = load(module).LABEL
            _WORDS[module] = re.split(r"[:(/,]", label)[0].strip().lower()
        except Exception:  # noqa: BLE001
            _WORDS[module] = module
    return _WORDS[module]


def pick(message, files=(), active=None, apps_claim=None, planner=None, catalogue="", arts_text="", log=None, refs=(), editing=None, known=()):
    """One step's program: (lane or None, why, asked); 'asked' is a question when nothing fits."""
    s, why = score(message, files, active, apps_claim, refs, editing, known)
    ranked = sorted(s.items(), key=lambda kv: -kv[1])
    best = ranked[0] if ranked else (None, 0)
    second = ranked[1] if len(ranked) > 1 else (None, 0)
    clear = best[0] and best[1] >= 5 and best[1] - second[1] >= 1.5
    if clear or (best[0] and planner is None and best[1] >= 3):
        return best[0], why.get(best[0], ""), None
    if planner is not None:
        lane = ask_model(message, files, active, planner, catalogue, arts_text, [k for k, _ in ranked[:4]])
        if lane:
            return lane, "the model chose", None
    if best[0] and best[1] >= 3:
        return best[0], why.get(best[0], ""), None
    return (
        None,
        "",
        "What should I do? For example: 'add a glow effect to my video', 'make my photo brighter', 'send it to slack #general', "
        "'write a 2 page report on ...', 'what can you do?'",
    )


SYSTEM = """You choose which program on a Windows PC handles a request. Programs (key: what it does):
{catalogue}
Reply with JSON only: {{"lane": "<key>"}}. Choose "none" only when no program fits."""


def ask_model(message, files, active, planner, catalogue, arts_text, likely):
    user = (
        f"REQUEST: {message}\nFILES SENT NOW: {', '.join(f.split(chr(92))[-1] for f in files) or 'none'}\n"
        f"FILES IN THIS CHAT: {arts_text or 'none'}\nPROGRAM IN USE: {active or 'none'}\nLIKELY: {', '.join(likely) or 'any'}"
    )
    try:
        r = planner._call("fast", [{"role": "system", "content": SYSTEM.format(catalogue=catalogue)}, {"role": "user", "content": user}])
        m = re.search(r"\{.*\}", r.text, re.S)
        lane = (json.loads(m.group(0)) if m else {}).get("lane")
    except Exception:  # noqa: BLE001 - the rules' best guess stands
        return None
    return lane if lane and lane != "none" else None
