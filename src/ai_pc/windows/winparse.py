"""What a person says about their files and settings, read by rules into operations for winchat (the cheap model reads
the rest into the same operations).

  parse(clause, places, focus) -> {"ops": [...], "ask": str | None}
  a file set (what = {...}): {"where": "downloads" | path, "kind", "words": [...], "since", "until", "field", "larger",
                             "smaller", "focus": True (the files talked about last), "names": [exact names]}
"""

import calendar
import datetime as dt
import re
from pathlib import Path

from ai_pc.windows import fs as FS

KIND_WORDS = [
    (r"\bscreen ?shots?\b", "screenshot"),
    (r"\bwhats ?app (?:photos?|pictures?|images?|pics?)\b", "whatsapp"),
    (r"\b(?:photos?|pictures?|images?|pics?|jpe?gs?|pngs?)\b", "photo"),
    (r"\b(?:videos?|clips?|movies?|mp4s?|recordings? from my phone)\b", "video"),
    (r"\b(?:songs?|music|audio(?: files)?|mp3s?|voice ?notes?|podcasts?)\b", "audio"),
    (r"\bpdfs?\b", "pdf"),
    (r"\b(?:word (?:files?|documents?|docs?)|docx?(?: files)?|documents?|docs)\b", "document"),
    (r"\b(?:spreadsheets?|excel (?:files?|sheets?|workbooks?)|workbooks?|xlsx?(?: files)?|csvs?)\b", "spreadsheet"),
    (r"\b(?:presentations?|powerpoints?|slide ?decks?|pptx?(?: files)?)\b", "presentation"),
    (r"\b(?:zips?(?: files)?|archives?|rars?|compressed files?)\b", "archive"),
    (r"\b(?:installers?|setup files?|setups?|exes?|\.exe files?)\b", "installer"),
    (r"\b(?:unfinished|partial|incomplete|broken) downloads?\b", "partial"),
]
PLACE_RX = r"(downloads?|documents?|desktop|pictures|my photos|photos folder|videos folder|my videos|music folder|my music|onedrive)"
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1e3,
    "k": 1e3,
    "mb": 1e6,
    "m": 1e6,
    "meg": 1e6,
    "megs": 1e6,
    "gb": 1e9,
    "g": 1e9,
    "gig": 1e9,
    "gigs": 1e9,
}
STOP = set(
    """a an the my our your me i we you it its it's them those these this that some any all every each of in on at to into from for with by
and or but is are was were be been do does did can could would should will shall please pls find show list where what what's whats which how many
much locate search look looking get give tell file files folder folders called named name new old recent latest last first one ones there here thing
things stuff copy copies move delete remove rename zip unzip open my up out about than more less bigger smaller larger over under above below have
has had just also put send make made want need see convert turn change save export merge combine join extract resize shrink scale organize organise sort
clean tidy trash bin throw away get rid erase compress uncompress set use word one single into called named every everything anything something whatever
whole entire inside""".split()
)


SKIP_NAMES = {"$recycle.bin", "system volume information", "node_modules", ".git", "appdata", "__pycache__"}


def _subfolders(places, depth=2):
    """The folders under the known places, two levels down: {lower name: [(depth, place key, path)]}."""
    out = {}
    for key, base in places.items():
        if base is None:
            continue
        level = [Path(base)]
        for dep in range(1, depth + 1):
            nxt = []
            for d in level:
                try:
                    for q in d.iterdir():
                        if q.is_dir() and not q.name.startswith((".", "$")) and q.name.lower() not in SKIP_NAMES:
                            out.setdefault(q.name.lower(), []).append((dep, key, q))
                            nxt.append(q)
                except OSError:
                    continue
            level = nxt
    return out


def _best(cands):
    def newest(q):
        try:
            return -q.stat().st_mtime
        except OSError:
            return 0

    dep, key, q = min(cands, key=lambda x: (x[0], newest(x[2])))
    return key, q


def named_folder(c, places):
    """(place key, folder) for a real folder the clause names: 'the invoices folder', 'the New folder', 'a folder called
    taxes', '"Tax 2025" folder' (the shallowest one, then the newest), else (None, None)."""
    subs = None
    names = []
    for m in re.finditer(
        r"\bfolder\s+(?:called|named)\s+['\"]?([\w .&()'-]+?)['\"]?(?=\s+(?:in|inside|on|under|to|into)\b|\s*$)|\bfolder\s+['\"]([^'\"]+)['\"]|"
        r"['\"]([^'\"]+)['\"]\s+folder\b",
        c,
    ):
        names.append(next(g for g in m.groups() if g).strip().lower())
    for m in re.finditer(r"\bfolders?\b", c):
        ws = re.findall(r"[\w&().'-]+", c[: m.start()])[-5:]
        for i in range(len(ws)):
            cand = re.sub(r"^(?:(?:the|my|a|an|this|that|whole|entire|our)\s+)+", "", " ".join(ws[i:])).strip("'\"")
            if cand:
                names += [cand, cand + " folder"]
    for n in names:
        if n in ("new", "a", "the", "that", "this", "same", "empty", "new folder") and n != "new folder":
            continue
        if subs is None:
            subs = _subfolders(places)
        if n in subs:
            return _best(subs[n])
    return None, None


PLACE_WORD = r"(downloads?|documents?|desktop|pictures|photos|videos|music|onedrive)"


def place_match(c):
    """Where a clause names one of the known places, as (key, match) or (None, None). 'pictures', 'photos', 'videos',
    'music' and 'documents' are also kinds of file, so they are a place only after 'in / from / to ...', with 'folder',
    or as 'my documents': 'find the pictures in downloads' looks in Downloads."""
    m = (
        re.search(r"\b(?:in|from|on|to|into|onto|inside|under|at|of)\s+(?:my\s+|the\s+)?" + PLACE_WORD + r"\b(?:\s+folder)?", c)
        or re.search(r"\b(?:my\s+|the\s+)?" + PLACE_WORD + r"\s+folder\b", c)
        or re.search(r"\b(?:my|the)\s+(downloads?|desktop|onedrive)\b", c)
        or re.search(r"\bmy\s+(documents)\b", c)
        or re.search(r"^\s*" + PLACE_WORD + r"\b(?=\s*(?:[:?]|$))", c)
    )
    if not m:
        return None, None
    w = m.group(1)
    key = "downloads" if w.startswith("download") else "documents" if w.startswith("document") else "pictures" if w in ("pictures", "photos") else w
    return key, m


def place_of(c, places):
    """('downloads', its folder) for the place a clause names, else (None, None). 'the invoices folder' / 'documents\\taxes'
    / 'a folder called taxes' find a real folder under the known places; 'the Photos folder' is a real folder named
    Photos when there is one (organizing makes it), else the Pictures library."""
    key, m = place_match(c)
    if m:
        if m.group(1) in ("photos", "videos", "music") and re.search(r"\bfolder\b", m.group(0)):
            k2, f2 = named_folder(c, places)
            if f2 is not None and f2.name.lower() == m.group(1):
                return k2, f2
        base = places.get(key)
        sub = re.match(r"\s*(?:\\|/|>)\s*([\w .&()-]+)", c[m.end() :])
        if base is not None and sub:
            return key, base / sub.group(1).strip()
        return key, base
    return named_folder(c, places)


def folder_of(c, places):
    """The folder a whole-folder request is about ('organize my pictures', 'clean up the desktop'): here 'my pictures'
    is the Pictures folder, not a kind of file."""
    key, folder = place_of(c, places)
    if folder is None:
        m = re.search(r"\b(?:my|the)\s+(pictures|photos|videos|music|documents)\b", c)
        if m:
            key = "pictures" if m.group(1) in ("pictures", "photos") else m.group(1)
            folder = places.get(key)
    return key, folder


def kind_in(c):
    for rx, k in KIND_WORDS:
        if re.search(rx, c):
            return k
    return None


def size_in(c):
    out = {}
    for m in re.finditer(
        r"\b(bigger|larger|more|over|above|greater|smaller|less|under|below)\s+(?:than\s+)?(\d+(?:\.\d+)?)\s*(bytes?|kb|k|mb|m|megs?|gb|g|gigs?)\b", c
    ):
        n = float(m.group(2)) * UNITS[m.group(3)]
        out["larger" if m.group(1) in ("bigger", "larger", "more", "over", "above", "greater") else "smaller"] = n
    return out


def dates_in(c, now=None, info=None):
    """(since, until) for 'from August', 'in September 2025', 'last week', 'this month', 'yesterday', 'older than 30 days',
    'in the last 3 months', 'before 2024'. A month without a year is the latest one (info["any_year"] is set, so an
    earlier year can be tried when that one has nothing)."""
    now = now or dt.datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    m = (
        re.search(r"\b(?:in|from|during|of|taken in)\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(\d{4}))?", c)
        or re.search(
            r"\b(" + "|".join(sorted((k for k in MONTHS if k not in ("may", "mar", "march")), key=len, reverse=True)) + r")\b(?:\s+(\d{4}))?", c
        )
        or re.search(r"\b(may|march)\b(?:\s+(\d{4})|(?=\s+(?:photos?|pictures?|files?|videos?|bills?|invoices?)))", c)
    )
    if m:
        mo = MONTHS[m.group(1)]
        y = int(m.group(2)) if m.group(2) else (now.year if mo <= now.month else now.year - 1)
        if info is not None and not m.group(2):
            info["any_year"] = True
        a = dt.datetime(y, mo, 1)
        return a, (dt.datetime(y + 1, 1, 1) if mo == 12 else dt.datetime(y, mo + 1, 1))
    if re.search(r"\btoday\b", c):
        return today, None
    if re.search(r"\byesterday\b", c):
        return today - dt.timedelta(days=1), today
    if re.search(r"\bthis week\b", c):
        return today - dt.timedelta(days=today.weekday()), None
    if re.search(r"\blast week\b", c):
        start = today - dt.timedelta(days=today.weekday() + 7)
        return start, start + dt.timedelta(days=7)
    if re.search(r"\bthis month\b", c):
        return today.replace(day=1), None
    if re.search(r"\blast month\b", c):
        first = today.replace(day=1)
        prev = (first - dt.timedelta(days=1)).replace(day=1)
        return prev, first
    if re.search(r"\bthis year\b", c):
        return today.replace(month=1, day=1), None
    if re.search(r"\blast year\b", c):
        return dt.datetime(now.year - 1, 1, 1), dt.datetime(now.year, 1, 1)
    m = re.search(r"\b(?:in the |over the )?(?:last|past)\s+(\d+|few|couple of)\s+(days?|weeks?|months?|years?)\b", c)
    if m:
        n = {"few": 3, "couple of": 2}.get(m.group(1)) or int(m.group(1))
        days = n * {"d": 1, "w": 7, "m": 30, "y": 365}[m.group(2)[0]]
        return now - dt.timedelta(days=days), None
    m = re.search(r"\bolder than\s+(\d+|a|one|two|three|six)\s+(days?|weeks?|months?|years?)\b", c)
    if m:
        n = {"a": 1, "one": 1, "two": 2, "three": 3, "six": 6}.get(m.group(1)) or int(m.group(1))
        days = n * {"d": 1, "w": 7, "m": 30, "y": 365}[m.group(2)[0]]
        return None, now - dt.timedelta(days=days)
    m = re.search(r"\bbefore\s+(\d{4})\b", c)
    if m:
        return None, dt.datetime(int(m.group(1)), 1, 1)
    m = re.search(r"\b(?:after|since)\s+(\d{4})\b", c)
    if m:
        return dt.datetime(int(m.group(1)) + (1 if "after" in m.group(0) else 0), 1, 1), None
    return None, None


def words_in(c, raw=None):
    """The words that name the files ('my CV' -> cv, 'the bank statement' -> bank, statement), quoted names first."""
    q = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw or c)
    if q:
        return [x for pair in q for x in pair if x]
    t = c.lower()
    for rx, _ in KIND_WORDS:
        t = re.sub(rx, " ", t)
    t = re.sub(PLACE_RX, " ", t)
    t = re.sub(r"\b(?:(?:from|in|during|of|taken in)\s+)?(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+\d{4})?", " ", t)
    t = re.sub(
        r"\b(?:today|yesterday|this|last|past|week|month|year|days?|weeks?|months?|years?|older|newer|since|before|after|\d+(?:\.\d+)?\s*(?:kb|mb|gb|k|m|g)?)\b",
        " ",
        t,
    )
    t = re.sub(r"\b(?:biggest|largest|smallest|newest|oldest|duplicates?|same|bigger|larger|smaller|than|wide|tall|pixels?|px)\b", " ", t)
    ws = [w for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", t) if w not in STOP and len(w) > 1]
    return [w[:-1] if w.endswith("s") and len(w) > 4 and not w.endswith("ss") else w for w in ws]


ORD = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "last": -1,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
    "5th": 5,
    "6th": 6,
    "7th": 7,
    "8th": 8,
    "9th": 9,
    "10th": 10,
}
PLURAL = r"\b(?:them|those|these|they|the same files?|the ones you (?:found|made|moved|listed)|all of them|both(?: of them)?)\b"
SINGLE = r"\b(?:it|that one|this one|that file|this file)\b"


BEFORE_FOLDER = {
    "the",
    "my",
    "a",
    "an",
    "this",
    "that",
    "in",
    "from",
    "to",
    "into",
    "inside",
    "of",
    "whole",
    "entire",
    "our",
    "your",
    "rename",
    "move",
    "copy",
    "delete",
    "remove",
    "zip",
    "open",
    "trash",
    "find",
    "show",
    "list",
    "what's",
    "whats",
    "is",
    "what",
    "everything",
    "all",
    "files",
}


def folder_named(c):
    """The name said for a folder: 'the invoices folder' -> 'invoices', 'the New folder' -> 'new folder', 'a folder
    called Tax 2025' -> 'tax 2025'; None when no folder is named."""
    m = re.search(r"\bfolder\s+(?:called|named)\s+['\"]?([\w .&()'-]+?)['\"]?(?=\s+(?:in|inside|on|under|to|into)\b|\s*$)", c)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bfolder\b", c)
    if not m:
        return None
    name = []
    for w in reversed(re.findall(r"[\w&().'-]+", c[: m.start()])):
        if w in BEFORE_FOLDER or len(name) >= 3:
            break
        name.insert(0, w)
    n = " ".join(name).strip("'\"")
    return ("new folder" if n == "new" else n) or None


def what_in(c, raw, places, focus):
    """The files a clause is about: the ones talked about last ('them' all of them, 'it' the one, 'the second one' one
    of the list; a clause that names nothing at all), a folder itself ('the invoices folder'), or a search. A folder
    named that does not exist is said back ({"missing_folder"}), never guessed."""
    if focus and not re.sub(r"\b(?:please|now|too|also|as well|for me|again|right away|quickly|then|and)\b|[.,!?]", " ", c).strip():
        return {"focus": True}  # 'zip', 'delete': the files just talked about
    if focus:
        m = re.search(
            r"\bthe\s+(" + "|".join(ORD) + r")(?:\s+(?:one|file|photo|picture|image|pdf|document|doc|video|song|item|result|folder))?"
            r"(?=\s*$|\s+(?:to|into|as|in|from|and|then|please|instead|on|my|the)\b|\s*[,.?!])",
            c,
        ) or re.search(r"\b(?:number|no\.|#)\s*(\d{1,3})\b", c)
        if m:
            return {"focus": True, "pick": ORD.get(m.group(1)) or int(m.group(1))}
        if re.search(PLURAL, c):
            return {"focus": True}
        if re.search(SINGLE, c):
            return {"focus": True, "one": True}
    key, folder = place_of(c, places)
    if folder is not None and Path(folder) not in [Path(v) for v in places.values() if v]:
        nm = folder.name.lower()
        rest = c.replace(nm, " ")
        if re.search(
            r"^\s*(?:\w+\s+){0,2}?(?:the\s+|my\s+)?(?:whole\s+|entire\s+)?['\"]?" + re.escape(nm) + r"['\"]?(?:\s+folder)?\s*$", c
        ) and not kind_in(rest):
            return {"dirs": [str(folder)]}  # the folder itself ('move the invoices folder to documents')
    if folder is None and places:
        fn = folder_named(c)
        if fn and not place_match(c)[1]:
            return {"missing_folder": fn}
    if folder is None and re.search(r"\b(?:i|we)\s+(?:just\s+)?download(?:ed)?\b|\bdownloaded\b", c):
        _key, folder = "downloads", places.get("downloads")
    out = {"where": str(folder) if folder else None}
    pk, pm = place_match(c)
    if pm:
        c = c[: pm.start()] + " " + c[pm.end() :]
    elif folder is not None and Path(folder) not in [Path(v) for v in places.values() if v]:
        n_ = re.escape(folder.name.lower())
        c = re.sub(
            r"\b(?:in|from|inside|of)\s+(?:the\s+|my\s+)?['\"]?" + n_ + r"['\"]?(?:\s+folder)?|(?:the\s+|my\s+)?['\"]?" + n_ + r"['\"]?\s+folder\b",
            " ",
            c,
        )
    named = re.findall(
        r"([\w][\w .()&'\-]*\.(?:"
        + "|".join(sorted({e.lstrip(".") for exts in [*FS.KINDS.values(), FS.PARTIAL] for e in exts}, key=len, reverse=True))
        + r"))\b",
        c,
        re.I,
    )
    if named:
        out["names"] = [n.strip() for n in named]
        return out
    k = kind_in(c)
    if k == "screenshot":
        out.update(kind="photo", words=["screenshot"])
    elif k == "whatsapp":
        out.update(kind="photo", words=["whatsapp"])
    elif k:
        out["kind"] = k
    info = {}
    since, until = dates_in(c, info=info)
    if info.get("any_year"):
        out["any_year"] = True
    if since or until:
        out.update(
            since=since.isoformat() if since else None,
            until=until.isoformat() if until else None,
            field="taken" if (out.get("kind") == "photo" or re.search(r"\btaken\b", c)) else ("ctime" if re.search(r"\bcreated\b", c) else "mtime"),
        )
    out.update(size_in(c))
    ws = words_in(c, raw) if not out.get("words") else out["words"]
    if ws:
        out["words"] = ws
    return out


def _yes(c):
    return bool(
        re.search(r"^\s*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|do it|proceed|confirm(?:ed)?|please do|go|haan|han ji|ji haan|theek hai)\b", c)
    )


def _no(c):
    return bool(re.search(r"^\s*(?:no|nope|nah|cancel|stop|don'?t|do not|never ?mind|leave it|nahi|na)\b", c))


def parse(clause, places, focus=None, raw=None):
    c = " ".join(clause.lower().split())
    raw = raw or clause
    out = {"ops": [], "ask": None}

    def done(*ops):
        out["ops"] = list(ops)
        return out

    # ---------------------------------------------------------------- settings
    if re.search(r"\bdark (?:mode|theme)\b|\bdark\b.*\b(?:windows|screen|theme|mode)\b", c) or re.search(r"\blight (?:mode|theme)\b", c):
        if re.search(r"\b(?:is|am i|are we)\b.*\b(?:on|using)\b|\?$", c) and not re.search(r"\b(?:turn|switch|make|set|use|enable|disable|go)\b", c):
            return done({"op": "setting_get", "name": "dark_mode"})
        on = bool(re.search(r"\bdark\b", c)) != bool(re.search(r"\b(?:off|disable|stop|no more|turn off)\b", c))
        if re.search(r"\blight\b", c) and not re.search(r"\bdark\b", c):
            on = bool(re.search(r"\b(?:off|disable)\b", c))
        return done({"op": "setting", "name": "dark_mode", "value": on})
    if re.search(r"\btranspar", c):
        return done({"op": "setting", "name": "transparency", "value": not re.search(r"\b(?:off|disable|no|stop|remove)\b", c)})
    if re.search(r"\b(?:file )?extensions?\b", c) and re.search(r"\b(?:show|see|display|hide|turn|unhide)\b", c):
        return done({"op": "setting", "name": "file_extensions", "value": not re.search(r"\bhide\b|\boff\b|\bdon'?t show\b", c)})
    if re.search(r"\bhidden (?:files|folders|items)\b", c) and re.search(r"\b(?:show|see|display|hide|turn|unhide)\b", c):
        return done({"op": "setting", "name": "hidden_files", "value": not re.search(r"\bhide\b|\boff\b|\bdon'?t show\b", c)})
    if re.search(r"\btaskbar\b", c) and re.search(r"\b(?:left|center|centre|middle)\b", c):
        return done({"op": "setting", "name": "taskbar_left", "value": bool(re.search(r"\bleft\b", c))})
    if re.search(r"\bwall ?paper\b|\bdesktop background\b|\bbackground picture\b", c):
        if re.search(r"^\s*(?:what|which)\b", c):
            return done({"op": "setting_get", "name": "wallpaper"})
        return done({"op": "wallpaper", "what": what_in(c, raw, places, focus)})
    if re.search(
        r"\bpower (?:plan|mode|setting)|\bhigh performance\b|\bbest performance\b|\bpower saver\b|\bbattery saver\b|\bsave (?:the )?battery\b|\bbalanced\b",
        c,
    ):
        if re.search(r"^\s*(?:what|which)\b", c):
            return done({"op": "setting_get", "name": "power_plan"})
        plan = (
            "high performance"
            if re.search(r"\bhigh performance\b|\bbest performance\b|\bmaximum performance\b|\bfaster\b", c)
            else "power saver"
            if re.search(r"\bsaver\b|\bsave (?:the )?battery\b|\bpower saving\b", c)
            else "balanced"
        )
        return done({"op": "setting", "name": "power_plan", "value": plan})
    if re.search(r"\bprinter\b", c):
        if re.search(r"^\s*(?:what|which)\b|\blist\b", c):
            return done({"op": "setting_get", "name": "default_printer"})
        m = re.search(r"\b(?:to|as)\s+(?:the\s+)?['\"]?(.+?)['\"]?(?:\s+printer)?\s*$", c)
        return (
            done({"op": "setting", "name": "default_printer", "value": m.group(1)}) if m else done({"op": "setting_get", "name": "default_printer"})
        )
    if re.search(
        r"\b(?:start ?up|starts? with windows|starting with windows|opens? (?:when|with|at) (?:windows|start)|launch(?:es|ing)? (?:at|with|on) (?:boot|startup|windows)|at boot|on boot)\b",
        c,
    ):
        if re.search(r"^\s*(?:what|which)\b|\blist\b|\bshow\b", c):
            return done({"op": "startup_list"})
        off = bool(re.search(r"\b(?:stop|disable|don'?t|turn off|prevent|no longer|remove|keep)\b", c))
        m = re.search(
            r"\b(?:stop|disable|enable|turn off|turn on|prevent|let|allow|start|make)\s+(?:the\s+)?([\w .&+-]+?)\s+(?:from\s+)?(?:starting|opening|launching|"
            r"at startup|on startup|with windows|start with|starts|open|run|at boot|on boot|when)",
            c,
        )
        app = m.group(1).strip() if m else None
        if not app:
            m = re.search(r"\b(?:startup|start ?up)\s+(?:for\s+)?([\w .&+-]+)$", c)
            app = m.group(1).strip() if m else None
        return done({"op": "startup", "app": app, "on": not off}) if app else done({"op": "startup_list"})

    # ---------------------------------------------------------------- questions
    if re.search(
        r"\b(?:how much (?:free )?(?:space|storage|room)|disk space|storage left|space (?:is )?left|free space|how full)\b", c
    ) and not re.search(r"\bfree up\b", c):
        return done({"op": "space"})
    if re.search(
        r"\b(?:what(?:'s| is)? taking (?:up )?(?:the most )?(?:space|room)|biggest files|largest files|what(?:'s| is) using (?:up )?(?:space|storage))\b",
        c,
    ):
        key, folder = folder_of(c, places)
        return done(
            {
                "op": "find",
                "what": {
                    "where": str(folder) if folder else None,
                    **({"kind": kind_in(c)} if kind_in(c) and kind_in(c) not in ("screenshot", "whatsapp") else {}),
                },
                "sort": "largest",
                "limit": 10,
            }
        )
    if re.search(r"^\s*what(?:'s| is)? in (?:it|there|that folder|this folder)\b", c):
        return done({"op": "summary", "where": None, "focus": True})
    if re.search(r"^\s*(?:what(?:'s| is)?|show me what(?:'s| is)?)\s+in\s+(?:my\s+|the\s+)?", c):
        key, folder = folder_of(c, places)
        if folder is not None:
            return done({"op": "summary", "where": str(folder)})

    # ---------------------------------------------------------------- the Recycle Bin (it is never emptied here)
    if (
        re.search(r"\b(?:recycle bin|recycling bin|the bin|the trash|deleted (?:files|items|things|stuff))\b", c)
        or (re.search(r"\b(?:undelete|recover|bring back|get back|restore)\b", c) and re.search(r"\b(?:deleted|bin|trash|removed)\b", c))
        or re.search(r"^\s*(?:restore|undelete|recover)\b", c)
    ):
        if re.search(r"\b(?:empty|clear|purge|wipe)\b", c):
            return done(
                {
                    "op": "say",
                    "text": "I don't empty the Recycle Bin: that deletes for good, and nothing I do is permanent. When you are sure, "
                    "empty it yourself from its right-click menu.",
                }
            )
        if re.search(r"\b(?:restore|recover|bring back|get back|undelete|put back)\b", c):
            pm = re.search(r"\bthe\s+(" + "|".join(ORD) + r")(?:\s+(?:one|file|item))?\b", c) or re.search(r"\b(?:number|no\.|#)\s*(\d{1,3})\b", c)
            if pm:  # 'restore the first one': of the Recycle Bin list shown last
                return done({"op": "bin_restore", "pick": ORD.get(pm.group(1)) or int(pm.group(1))})
            cl = re.sub(
                r"\b(?:from|out of)\s+(?:the\s+)?(?:recycle bin|recycling bin|bin|trash)\b|\b(?:restore|recover|bring|back|get|undelete|put|deleted|removed|"
                r"i|you|that|which|had|have)\b",
                " ",
                c,
            )
            return done({"op": "bin_restore", "what": what_in(cl, raw, {}, None), "text": re.sub(r"\s+", " ", cl).strip()})
        return done({"op": "bin_list"})
    if re.search(r"^\s*(?:are there|do i have|find|show|list|any)\b.*\bduplicates?\b", c):
        key, folder = folder_of(c, places)
        return done({"op": "find_dupes", "where": str(folder) if folder else None})

    # ---------------------------------------------------------------- files
    if re.search(r"\b(?:clean ?up|declutter|free up (?:some )?space|tidy up)\b", c) and not re.search(
        r"\b(?:organi[sz]e|sort|by type|into folders|by date|by month)\b", c
    ):
        key, folder = folder_of(c, places)
        return done({"op": "cleanup", "where": str(folder) if folder else None})
    if re.search(r"\b(?:remove|delete|get rid of|clear|trash|bin)\b.*\bduplicates?\b|\bde-?dup", c):
        key, folder = folder_of(c, places)
        return done({"op": "dedupe", "where": str(folder) if folder else None})
    if re.search(r"\b(?:organi[sz]e|sort out|sort|arrange|tidy|put .* into folders|file away)\b", c) and not re.search(
        r"\bsort(?:ed)? by (?:size|name)\b.*\b(?:show|list)\b", c
    ):
        key, folder = folder_of(c, places)
        by = (
            "date"
            if re.search(r"\bby (?:date|month|year|when)\b|\binto months\b", c)
            else "ext"
            if re.search(r"\bby (?:extension|file extension)\b", c)
            else "kind"
            if re.search(r"\bby (?:type|kind)\b", c) or key not in ("pictures", "videos")
            else "date"
        )  # photos and videos sort by month
        w = what_in(c, raw, places, focus)
        taken = bool(re.search(r"\btaken\b", c) or w.get("kind") == "photo" or key == "pictures")
        if w.get("kind") and w.get("kind") == {"pictures": "photo", "videos": "video", "music": "audio"}.get(key):
            w.pop("kind")  # 'organize my pictures': all of Pictures, not only its photos
        return done(
            {"op": "organize", "where": str(folder) if folder else None, "by": by, "taken": taken, **({"kind": w["kind"]} if w.get("kind") else {})}
        )
    m = re.search(
        r"\b(?:make|create|add)\s+(?:a\s+)?(?:new\s+)?folder\s+(?:called|named)?\s*['\"]?([^'\"]+?)['\"]?(?=\s+(?:in|inside|on|under)\b|$)", c
    )
    if m:
        key, folder = place_of(c[m.end() :], places)
        return done(
            {
                "op": "mkdir",
                "name": re.search(re.escape(m.group(1).strip()), raw, re.I).group(0)
                if re.search(re.escape(m.group(1).strip()), raw, re.I)
                else m.group(1).strip(),
                "where": str(folder) if folder else None,
            }
        )
    if (
        re.search(r"\b(?:unzip|extract|uncompress|open up)\b", c)
        and re.search(r"\bzip|\barchive|\brar|\.zip\b|\bthem\b|\bit\b", c)
        and not re.search(r"\baudio|sound|mp3|music\b", c)
    ):
        return done(
            {
                "op": "unzip",
                "what": what_in(re.sub(r"\b(?:unzip|extract|uncompress)\b", " ", c), raw, places, focus)
                | ({"kind": "archive"} if not re.search(r"\bthem|\bit\b", c) else {}),
            }
        )
    if re.search(r"\b(?:extract|get|take|rip|pull|save)\b.*\b(?:audio|sound|music|mp3|song)\b.*\b(?:from|out of|of)\b", c):
        return done({"op": "audio", "what": what_in(re.sub(r"\b(?:audio|sound|music|mp3|song)\b", " ", c), raw, places, focus)})
    if re.search(r"\b(?:merge|combine|join|put together)\b.*\bpdfs?\b|\b(?:merge|combine)\s+(?:them|those|these)\b", c):
        nm = re.search(r"\b(?:called|named)\s+['\"]?([^'\"]+?)['\"]?\s*$", raw, re.I) or re.search(
            r"\binto\s+(?!one\b|a single\b|1\b)['\"]?([^'\"]+?)['\"]?\s*$", raw, re.I
        )
        return done(
            {
                "op": "merge_pdfs",
                "what": what_in(re.sub(r"\b(?:merge|combine|join)\b|\bcalled .*$|\bnamed .*$", " ", c), raw, places, focus) | {"kind": "pdf"},
                **(
                    {"name": nm.group(1).strip()}
                    if nm and not re.search(r"\b(?:one|a single|single)\b\s*(?:pdf|file)?$", nm.group(1).lower())
                    else {}
                ),
            }
        )
    mt = re.search(
        r"\b(?:convert|turn|change|save|export|make)\b.*\b(?:to|into|as)\s+(?:a\s+|an\s+)?(pdfs?|jpe?gs?|pngs?|webps?|mp3s?)\b|\bmake\s+pdfs?\s+(?:of|from)\b",
        c,
    )
    if mt:
        to = (mt.group(1) or "pdf").rstrip("s").replace("jpeg", "jpg")
        if to == "mp3":
            return done({"op": "audio", "what": what_in(c, raw, places, focus)})
        return done(
            {
                "op": "convert",
                "to": to,
                "what": what_in(re.sub(r"\b(?:to|into|as)\s+(?:a\s+|an\s+)?(?:pdfs?|jpe?gs?|pngs?|webps?)\b", " ", c), raw, places, focus),
            }
        )
    if re.search(r"\b(?:resize|shrink|scale|make (?:them|it|the \w+) smaller|reduce (?:the )?size|smaller for)\b", c) and not re.search(
        r"\bpdf\b", c
    ):
        w = re.search(r"\b(\d{2,5})\s*(?:px|pixels?)?\s*(?:wide|width|across)?\b", c)
        h = re.search(r"\b(\d{2,5})\s*(?:px|pixels?)?\s*(?:tall|high|height)\b", c)
        width = int(w.group(1)) if w and not h else None
        height = int(h.group(1)) if h else None
        if not width and not height:
            width = 1600 if re.search(r"whatsapp|share|email|web", c) else 1920
        return done(
            {"op": "resize", "width": width, "height": height, "what": what_in(re.sub(r"\b\d{2,5}\s*(?:px|pixels?)?\b", " ", c), raw, places, focus)}
        )
    if re.search(r"\b(?:zip|compress)\b", c) and not re.search(r"\bpdf\b", c):
        nm = re.search(r"\b(?:called|named|as)\s+['\"]?([^'\"]+?)['\"]?\s*$", raw, re.I)
        cz = re.sub(r"\b(?:zip|compress)\b", " ", c)
        fm = re.search(r"([\w&()-]+(?:\s+[\w&()-]+){0,2})\s+folder\b", cz)
        if fm:
            fname = re.sub(r"^(?:(?:the|my|a|up|whole|entire)\s+)+", "", fm.group(1).strip())
            key, folder = place_of(cz, places)
            if folder is not None and folder.name.lower() != fname.lower():
                folder = None
            fm = re.match(r"(.*)", fname)
            if folder is not None and folder.name.lower() == fm.group(1).strip().lower():
                return done({"op": "zip", "folder": str(folder), **({"name": nm.group(1).strip()} if nm else {})})
        return done(
            {
                "op": "zip",
                "what": what_in(re.sub(r"\b(?:zip|compress)\b|\bcalled .*$|\bnamed .*$", " ", c), raw, places, focus),
                **({"name": nm.group(1).strip()} if nm else {}),
            }
        )
    if (
        re.search(r"\brename\b", c)
        or re.search(r"\b(?:lower ?case|upper ?case|title case|capitali[sz]e)\b.*\bnames?\b", c)
        or re.search(r"\breplace\b.*\bin the (?:file )?names\b", c)
    ):
        what = what_in(re.sub(r"\brename\b|\b(?:to|as)\s+.*$|\bby (?:the )?(?:date|day|time).*$|\bwith (?:the )?date.*$", " ", c), raw, places, focus)
        if re.search(r"\bby (?:the )?(?:date|day|time)\b|\bwith (?:the )?date\b", c):
            pat = (
                "{taken:%Y-%m-%d %H.%M.%S}"
                if re.search(r"\btaken\b|\bphotos?\b|\bpictures?\b|\bimages?\b", c) or what.get("kind") == "photo"
                else "{date:%Y-%m-%d} {name}"
            )
            return done({"op": "rename", "what": what, "pattern": pat})
        m = re.search(r"\breplace\s+['\"]?(.+?)['\"]?\s+with\s+['\"]?(.*?)['\"]?(?:\s+in the (?:file )?names)?\s*$", raw, re.I)
        if m:
            return done({"op": "rename", "what": what, "replace": [m.group(1), m.group(2)]})
        cm = re.search(r"\b(lower ?case|upper ?case|title case|capitali[sz]e|underscores?|spaces)\b", c)
        if cm:
            k = cm.group(1).replace(" ", "")
            return done(
                {
                    "op": "rename",
                    "what": what,
                    "case": {
                        "lowercase": "lower",
                        "uppercase": "upper",
                        "titlecase": "title",
                        "capitalise": "title",
                        "capitalize": "title",
                        "underscore": "underscores",
                        "underscores": "underscores",
                        "spaces": "spaces",
                    }.get(k, "title"),
                }
            )
        m = re.search(r"\b(?:to|as)\s+['\"]?(.+?)['\"]?\s*$", raw, re.I)
        if m:
            new = m.group(1).strip()
            return done({"op": "rename", "what": what, "to": new})
        out["ask"] = "Rename them how? e.g. 'rename them by the date taken' or 'rename them to \"Lahore trip\"' (numbered 001, 002, ...)."
        return out
    m = re.search(r"\b(move|copy|put|send|drop|duplicate)\b", c)
    if m and re.search(r"\b(?:to|into|in|inside|onto)\b", c):
        verb = "copy" if m.group(1) in ("copy", "duplicate") else "move"
        mt2 = re.search(r"\b(?:to|into|inside|onto)\s+(.+)$", c) or re.search(r"\bin\s+(.+)$", c)
        dest_text = mt2.group(1) if mt2 else ""
        key, folder = place_of("to " + dest_text, places)
        sub = re.search(
            r"(?:a\s+(?:new\s+)?folder\s+(?:called|named)\s+['\"]?([^'\"]+?)['\"]?|\bfolder\s+['\"]([^'\"]+)['\"]|['\"]([^'\"]+)['\"]\s+folder)(?:\s+(?:in|inside|on)\b.*)?$",
            dest_text,
        )
        if sub:
            name = next(g for g in sub.groups() if g)
            rm = re.search(r"(?:called|named|folder)\s+['\"]?(" + re.escape(name.strip()) + r")", raw, re.I) or re.search(
                re.escape(name.strip()), raw, re.I
            )
            name = rm.group(1) if rm and rm.groups() else (rm.group(0) if rm else name)
            rest_key, rest_folder = place_of(dest_text[sub.end(0) - len(sub.group(0)) :], places)
            folder = (rest_folder or folder or places.get("documents")) / name.strip() if (rest_folder or folder or places.get("documents")) else None
        elif folder is None:
            sm = re.search(r"([\w .&-]+?)\s+(?:folder\s+)?(?:in|inside|on)\s+(?:my\s+|the\s+)?" + PLACE_RX, dest_text)
            if sm:
                base_key, base = place_of("in " + sm.group(2), places)
                nm_ = re.sub(r"^(?:the|a|my)\s+", "", sm.group(1).strip())
                rm = re.search(re.escape(nm_), raw, re.I)
                folder = base / (rm.group(0) if rm else nm_) if base else None
        if folder is None:
            out["ask"] = f"{'Copy' if verb == 'copy' else 'Move'} them where? e.g. 'to Documents' or 'to a folder called Invoices in Documents'."
            return out
        what = what_in(c[: mt2.start()] if mt2 else c, raw, places, focus)
        return done({"op": verb, "what": what, "to": str(folder)})
    if re.search(r"\b(?:delete|remove|trash|bin|get rid of|throw away|erase)\b", c):
        forever = bool(re.search(r"\bpermanently\b|\bfor good\b|\bforever\b|\bshift.?delete\b|\bcompletely\b", c))
        cl = re.sub(r"\b(?:delete|remove|trash|bin|get rid of|throw away|erase|permanently|for good|forever|completely)\b", " ", c)
        return done({"op": "trash", "what": what_in(cl, raw, places, focus), **({"forever": True} if forever else {})})
    if re.search(r"^\s*open\b", c):
        return done({"op": "open", "what": what_in(re.sub(r"^\s*open\b", " ", c), raw, places, focus)})
    if re.search(
        r"^\s*(?:find|search|look for|where(?:'s| is| are)|show me|list|which|how many|do i have|have i got|get me|locate)\b", c
    ) or re.search(r"\?\s*$", raw):
        w = what_in(c, raw, places, focus)
        sort = (
            "largest"
            if re.search(r"\b(?:biggest|largest|heaviest)\b", c)
            else "smallest"
            if re.search(r"\bsmallest\b", c)
            else "oldest"
            if re.search(r"\boldest\b", c)
            else "newest"
        )
        return done({"op": "find", "what": w, "sort": sort, "limit": 15, "count": bool(re.search(r"\bhow many\b", c))})
    return out
