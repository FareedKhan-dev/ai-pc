"""Requests about converting a file read by rules (no model): 'convert it to mp4', 'make it ready for whatsapp', 'under
10 MB', 'half the size', 'smaller but same quality', '720p', 'vertical with a blurred background', 'rotate it left', 'cut
the first 5 seconds', 'keep 0:30 to 1:10', 'remove 1:00 to 1:20', 'speed it up 2x', 'remove the sound', 'extract the audio
as mp3', 'the sound is half a second late', 'make a gif of 0:05 to 0:08', 'screenshot at 0:12', 'split it into 3 parts',
'join it with intro.mp4', 'add logo.png in the corner', 'burn subs.srt', 'will it play on my tv?', 'save it to my desktop'.

  parse(clause, ctx) -> {"ops": [{"op": ..., "args": {...}}], "ask": None | "question back"}
ctx: {"duration": s, "has_video": bool, "has_audio": bool, "files": {lower name: path}}
"""
import re

from ..sound.soundparse import WORDNUM

UNIT = r"(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)"
T1 = r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?|\d+(?:\.\d+)?(?:\s*" + UNIT + r"\b(?:\s*(?:and\s*)?\d+(?:\.\d+)?\s*(?:seconds?|secs?|s)\b)?)?)"
SIZE = r"(\d+(?:\.\d+)?)\s*(kb|kbs|kilobytes?|mb|mbs|megabytes?|megs?|gb|gigabytes?)\b"
VIDEO_EXT = r"mp4|mov|mkv|webm|avi|m4v|wmv|flv|3gp|ts|mts|mpg|mpeg|gif"
AUDIO_EXT = r"mp3|wav|m4a|aac|flac|ogg|opus|wma|amr"
FILE = r"([A-Za-z]:\\[^\"'<>|]+?\.(?:{e})|\"[^\"]+?\.(?:{e})\"|'[^']+?\.(?:{e})'|[\w\-.()]+\.(?:{e}))\b"
TARGETS = [
    (r"\bwhats\s*app\b|\bwa status\b", "whatsapp"), (r"\b(?:e-?mail(?:ing)?|gmail|outlook|mail it|attach(?:ment)?)\b", "email"),
    (r"\bdiscord\b", "discord"), (r"\btelegram\b", "telegram"), (r"\bslack\b", "slack"),
    (r"\b(?:insta(?:gram)?|ig) (?:feed|post)\b", "instagram_post"), (r"\b(?:insta(?:gram)?|ig) stor(?:y|ies)\b", "instagram_story"),
    (r"\binsta(?:gram)?\b|\breels?\b", "instagram"), (r"\btik ?tok\b", "tiktok"), (r"\b(?:youtube|yt) shorts?\b|\bshorts\b", "youtube_shorts"),
    (r"\byoutube\b|\byt\b", "youtube"), (r"\bfacebook\b|\bfb\b", "facebook"), (r"\blinked ?in\b", "linkedin"), (r"\btwitter\b|\bfor x\b|\bon x\b", "x"),
    (r"\b(?:my |a |the )?(?:web ?site|web page|webpage|website|blog|html)\b|\bfor (?:the )?web\b", "web"),
    (r"\bi ?phones?\b|\bipad\b|\bmac(?:book)?\b|\bapple\b", "iphone"), (r"\bandroid\b|\bsamsung\b", "android"),
    (r"\b(?:smart ?)?tv\b|\btelevision\b|\busb\b|\bled\b|\blcd\b|\bdvd player\b", "tv"), (r"\bpower ?point\b|\bpresentation\b|\bslides?\b|\bppt\b", "powerpoint"),
    (r"\bediting\b|\bpremiere\b|\bdavinci\b|\bresolve\b|\bcapcut\b|\bto edit\b|\bvideo editor\b", "editing"),
    (r"\barchiv(?:e|ing)\b|\bkeep(?:ing)? (?:it )?for (?:later|years)\b|\bbackup\b|\bstorage\b|\bto store\b", "archive"),
    (r"\b(?:plays?|work|open)s? (?:everywhere|on (?:any|every|all) (?:device|phone|player|computer|pc)s?)\b|\bany device\b", "everywhere"),
]
FORMATS = r"(mp4|mkv|mov|webm|avi|gif|webp|mp3|wav|m4a|aac|flac|ogg|opus|m4v)"
NUMW = r"(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|half)"
WHERE = r"(desktop|downloads?|documents?|videos?|pictures?|photos?|music|one ?drive)"


def secs(s):
    s = s.strip().lower()
    if ":" in s:
        v = 0.0
        for p in s.split(":"):
            v = v * 60 + float(p)
        return v
    m = re.match(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", s)
    if m:
        return float(m.group(1)) * 3600
    m = re.match(r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|m)\b(?:\s*(?:and\s*)?(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b)?", s)
    if m:
        return float(m.group(1)) * 60 + float(m.group(3) or 0)
    m = re.match(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _unitless(s):
    return ":" not in s and not re.search(r"[a-z]", s)


def _pair(a, b):
    """'10 to 20 seconds': a unit after the second number counts for the first too ('1 to 2 minutes')."""
    x, y = secs(a), secs(b)
    if _unitless(a) and not _unitless(b) and re.search(r"min|m\b", b) and ":" not in b:
        x *= 60
    if _unitless(a) and not _unitless(b) and re.search(r"hour|hr|h\b", b):
        x *= 3600
    return x, y


def ranges(c):
    """Every 'A to B' / 'A-B' / 'between A and B' span in the text, as (a, b) seconds."""
    out = []
    for m in re.finditer(r"(?:\b(?:from|between)\s+)?" + T1 + r"\s*(?:to|till|until|through|-|–|and)\s*" + T1, c):
        a, b = m.group(1), m.group(2)
        bare = _unitless(a) and _unitless(b)  # '10 to 20' without units: only in a sentence about cutting
        if bare and not re.search(r"\b(?:cut|keep|remove|delete|trim|only|gif|clip|part|section|bit|portion|from|between)\b", c):
            continue
        if bare and float(a) >= 100 and float(b) >= 100 and not re.search(r"\b(?:from|between)\b", c):
            continue  # '1280 and 720' are sizes, not times
        x, y = _pair(a, b)
        if x is not None and y is not None and y > x:
            out.append((x, y))
    return out


def size_mb(c):
    m = re.search(r"(?:under|below|less than|max(?:imum)?|at most|smaller than|within|no (?:more|bigger) than|up to|to|fit (?:in|into)|<)\s*(?:about\s*)?" + SIZE, c) \
        or re.search(SIZE + r"\s*(?:or less|max(?:imum)?|or smaller|limit|at most)\b", c) or re.search(r"\b(?:make it|be|is|as|only)\s*" + SIZE, c)
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2)
    return n / 1000 if u.startswith("k") else n * 1000 if u.startswith("g") else n


def _files(raw, ctx, ext):
    out = []
    for m in re.finditer(FILE.format(e=ext), raw, re.I):
        name = m.group(1).strip("\"'")
        out.append((ctx.get("files") or {}).get(name.lower(), (ctx.get("files") or {}).get(name.split("\\")[-1].lower(), name)))
    return out


def _num(s):
    if s is None:
        return None
    s = s.strip().lower()
    return float(WORDNUM[s]) if s in WORDNUM else float(s)


def parse(clause, ctx=None):
    ctx = ctx or {}
    raw = clause.strip()
    c = " ".join(raw.lower().replace("’", "'").replace("×", "x").split())
    ops = []

    def op(kind, **args):
        ops.append({"op": kind, "args": args})

    def done(ask=None):
        seen, out = set(), []
        for o in reversed(ops):  # one op of a kind per clause (the last said wins); trims and cuts stack
            key = (o["op"], str(sorted(o["args"].items()))) if o["op"] in ("trim", "cut", "frames") else o["op"]
            if key not in seen:
                seen.add(key)
                out.append(o)
        return {"ops": list(reversed(out)), "ask": ask}

    # ------------------------------------------------ questions
    tgt = next((name for rx, name in TARGETS if re.search(rx, c)), None)
    if re.search(r"^\s*(?:will|would|does|do|can|could|is) (?:it|this|that|the (?:video|file))\b.*\b(?:play|work|open|send|go|be (?:ok|okay|fine))\b|"
                 r"^\s*can i (?:send|share|post|upload|play|open) (?:it|this)\b|^\s*is (?:it|this) (?:ok|okay|fine|good|ready) (?:for|to)\b", c) or \
            (tgt and re.search(r"^\s*(?:will|would|does|do|can|could|is|are)\b", c) and re.search(r"\b(?:play|watch|open|view|see|send|work|upload)\b", c)):
        return {"ops": [{"op": "ask", "args": {"what": "compat", "target": tgt or "everywhere"}}], "ask": None}
    if re.search(r"^\s*(?:what(?:'s| is) (?:this|it|the file|in it)|(?:show|tell) me (?:about )?(?:it|the file|the details|the info)|details|info(?:rmation)?|"
                 r"what (?:format|resolution|size|codec|quality|frame rate|fps) is (?:it|this)|how (?:big|large|long|heavy) is (?:it|this|the (?:file|video))|"
                 r"what are the (?:details|specs)|describe it)\b", c):
        return {"ops": [{"op": "ask", "args": {"what": "info"}}], "ask": None}
    if re.search(r"^\s*(?:how (?:good|bad) (?:is|does)|how does it look|is (?:it|this) (?:still )?(?:good|ok|okay|fine|bad|low|high) quality|is the quality (?:ok|good|fine|bad)|does it (?:still )?look (?:ok|good|the same|fine|bad)|"
                 r"did (?:it|the quality) (?:get worse|drop)|quality check)\b", c):
        return {"ops": [{"op": "ask", "args": {"what": "quality"}}], "ask": None}
    if re.search(r"^\s*(?:compare|how much (?:smaller|bigger|did it save)|what (?:changed|did you (?:do|change))|before and after)\b|"
                 r"\bcompared? (?:to|with) the original\b|\bvs\.? (?:the )?original\b|\bagainst the original\b", c):
        return {"ops": [{"op": "ask", "args": {"what": "compare"}}], "ask": None}
    if re.search(r"^\s*where (?:is|are|did you (?:save|put))\b|^\s*(?:show|open) (?:me )?the (?:folder|file)s?\b", c):
        return {"ops": [{"op": "ask", "args": {"what": "where"}}], "ask": None}
    # ------------------------------------------------ recording the screen
    if re.search(r"\b(?:record|capture) (?:my |the )?(?:screen|desktop|display|monitor)\b|\bscreen ?record", c) or re.search(r"^\s*start recording\b", c):
        m = re.search(r"\bfor\s+" + T1, c)
        op("record", seconds=secs(m.group(1)) if m else None, mic=bool(re.search(r"\b(?:mic|microphone|voice|my sound|narrat)", c)),
           screen=int(re.search(r"\b(?:screen|monitor|display) (\d)\b", c).group(1)) if re.search(r"\b(?:screen|monitor|display) (\d)\b", c) else 1)
        return done()
    if re.search(r"^\s*(?:stop|end|finish) (?:the )?(?:recording|record)\b|^\s*stop\s*$", c):
        op("record_stop")
        return done()
    # ------------------------------------------------ saving
    msave = re.search(r"\b(?:save|export|download)\b|\bgive me (?:the )?(?:file|video|result|copy)\b|"
                      r"\b(?:put|copy|move|send) (?:it|this|that|them|the (?:file|video|result|parts|pictures|gif)) (?:to|on|in|into|onto) (?:my |the )?" + WHERE, c)
    as_format = re.search(r"\b(?:save|export)\b(?: (?:it|this|that))? (?:as|in|to) (?:an? )?\.?" + FORMATS + r"\b", c)
    if msave and not as_format:
        mw = re.search(r"\b(?:to|on|in|into|onto) (?:my |the )?" + WHERE + r"\b", c)
        where = mw.group(1).replace(" ", "") if mw else ("original" if re.search(r"\b(?:next to|beside|same folder as|where) the original\b", c) else None)
        mname = re.search(r"\b(?:as|named|called)\s+[\"']?([\w\-. ()]+?\.(?:" + VIDEO_EXT + "|" + AUDIO_EXT + r"|png|jpg|jpeg|webp))[\"']?\s*$", raw, re.I)
        op("save", where=where, name=mname.group(1) if mname else None)
        return done()
    # ------------------------------------------------ where it is going
    if tgt and (re.search(r"\b(?:for|to|on|onto|ready|send|post|upload|share|attach|mail|email|e-mail|play|plays|works?|open|in|into|with)\b", c)
                or len(c.split()) <= 3) and not re.search(r"^\s*(?:will|would|does|can|is)\b", c):
        op("target", name=tgt)
    # ------------------------------------------------ the kind of file
    m = re.search(r"\b(?:convert|change|turn|make|save|export|transcode|re-?encode|into|to|as|in)\b(?: (?:it|this|the (?:video|file|format)))?(?: (?:in)?to| as| in| into)?"
                  r" (?:an? )?\.?" + FORMATS + r"\b(?! (?:file|video) (?:named|called))", c) or re.search(r"^\s*\.?" + FORMATS + r"\s*(?:please|pls|format|file)?\s*$", c)
    fmt = m.group(1) if m else None
    if not fmt:
        m = re.search(r"\b(?:an? )?\.?" + FORMATS + r" (?:of it|of this|version|copy|file)\b", c)
        fmt = m.group(1) if m else None
    if fmt == "gif" or re.search(r"\b(?:make|create|turn|convert)\b.*\bgif\b|\bgif\b (?:of|from)\b|^\s*(?:a )?gif\b", c):
        g = {}
        mm = size_mb(c)
        if mm:
            g["max_mb"] = mm
        mf = re.search(r"(\d+)\s*fps\b", c)
        if mf:
            g["fps"] = int(mf.group(1))
        mw = re.search(r"(\d{3,4})\s*(?:px|pixels?)?\s*wide\b|width (\d{3,4})", c)
        if mw:
            g["width"] = int(mw.group(1) or mw.group(2))
        for a, b in ranges(c):
            op("trim", start=a, end=b)
        op("gif", **g)
        return done()
    if fmt == "webp" or re.search(r"\banimated webp\b|\bsticker\b", c):
        for a, b in ranges(c):
            op("trim", start=a, end=b)
        op("gif", fmt="webp", **({"max_mb": size_mb(c)} if size_mb(c) else {}))
        return done()
    if re.search(r"\b(?:extract|rip|pull out|take out|get|save|keep|export|give me|separate)\b (?:only )?(?:the |its )?(?:audio|sound|music|song|voice)\b|"
                 r"\b(?:audio|sound) only\b|\bjust the (?:audio|sound|music)\b|\bonly the (?:audio|sound)\b", c) and not re.search(r"\b(?:remove|delete|mute|without)\b", c):
        op("extract_audio", fmt=fmt if fmt in ("mp3", "wav", "m4a", "aac", "flac", "ogg", "opus") else None)
    elif fmt:
        if fmt in ("mp3", "wav", "m4a", "aac", "flac", "ogg", "opus") or fmt != "gif":
            op("format", to=fmt)
    if re.search(r"\b(?:back to|make it|turn it into|as) an? (?:normal |regular )?video(?: again)?\b|\bvideo again\b|\bback to the video\b", c):
        op("video")
    mc = re.search(r"\b(h\.?264|avc|x264|h\.?265|hevc|x265|av1|vp9|prores)\b", c)
    if mc:
        op("codec", video={"h264": "h264", "h.264": "h264", "avc": "h264", "x264": "h264", "h265": "hevc", "h.265": "hevc", "hevc": "hevc", "x265": "hevc",
                           "av1": "av1", "vp9": "vp9", "prores": "prores"}[mc.group(1)])
    # ------------------------------------------------ size and quality
    mb = size_mb(c)
    if mb and not any(o["op"] == "gif" for o in ops):
        if re.search(r"\b(?:parts?|pieces?|chunks?|split)\b", c):
            op("split", max_mb=mb)
        else:
            op("compress", max_mb=mb)
    elif re.search(r"\bhalf (?:the|its) size\b|\bhalf as big\b", c):
        op("compress", percent=50)
    elif re.search(r"(\d+)\s*(?:%|percent) (?:smaller|less|lighter)\b|\breduce (?:it |the size )?by (\d+)\s*(?:%|percent)", c):
        m = re.search(r"(\d+)\s*(?:%|percent) (?:smaller|less|lighter)\b|\breduce (?:it |the size )?by (\d+)\s*(?:%|percent)", c)
        op("compress", percent=max(1.0, 100 - float(m.group(1) or m.group(2))))
    elif re.search(r"(\d+)\s*(?:%|percent) of (?:the|its) (?:original )?size\b", c):
        op("compress", percent=float(re.search(r"(\d+)\s*(?:%|percent) of", c).group(1)))
    elif re.search(r"\b(?:as small as (?:possible|it can)|smallest(?: possible)?|tiny|very small|super small)\b", c) and \
            not re.search(r"\b(?:same|keep|without losing|no loss)\b", c):
        op("compress", level="tiny")
    elif re.search(r"\b(?:much|a lot|way|far) smaller\b|\bsmaller still\b|\beven smaller\b", c):
        op("compress", level="small")
    elif re.search(r"\b(?:compress|shrink|reduce(?: the)? (?:file )?size|make (?:it|the file|the video) (?:smaller|lighter)|smaller file|lighter|"
                   r"(?:lower|reduce) (?:the )?(?:file )?size|too (?:big|large|heavy))\b|^\s*smaller\b", c):
        op("compress")
    if re.search(r"\b(?:best|highest|maximum|max|top|full) quality\b|\bas good as possible\b", c):
        op("quality", level="best")
    elif re.search(r"\bhigh(?:er)? quality\b|\bbetter quality\b", c) and not re.search(r"\bsmaller\b", c):
        op("quality", level="high")
    # ------------------------------------------------ frame size and rate
    if not any(o["op"] == "split" for o in ops):
        m = re.search(r"\b(\d{3,4})\s*x\s*(\d{3,4})\b", c)
        if m:
            op("resize", width=int(m.group(1)), height=int(m.group(2)))
        else:
            m = re.search(r"\b(2160|1440|1080|720|576|540|480|360|240)\s*p\b|\b(4k|uhd|2k|qhd|full ?hd|fhd|hd|sd)\b", c)
            if m:
                h = int(m.group(1)) if m.group(1) else {"4k": 2160, "uhd": 2160, "2k": 1440, "qhd": 1440, "full hd": 1080, "fullhd": 1080, "fhd": 1080, "hd": 720,
                                                         "sd": 480}[m.group(2)]
                op("resize", height=h)
            elif re.search(r"\bhalf (?:the )?(?:resolution|dimensions|width|frame size)\b|\bhalf as (?:wide|big on screen)\b", c):
                op("resize", scale=0.5)
            else:
                m = re.search(r"\b(\d{3,4})\s*(?:px|pixels)?\s*wide\b|\bwidth (?:of )?(\d{3,4})\b", c)
                if m:
                    op("resize", width=int(m.group(1) or m.group(2)))
    m = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*(?:fps|frames? (?:per|a) second|frame ?rate)\b|\bframe ?rate (?:to |of )?(\d{2,3})\b", c)
    if m:
        op("fps", fps=float(m.group(1) or m.group(2)))
    # ------------------------------------------------ shape and turns
    m = re.search(r"\b(9:16|16:9|1:1|4:5|4:3|3:4|21:9|2:3|3:2)\b", c)
    ratio = m.group(1) if m else ("9:16" if re.search(r"\bvertical\b|\bportrait\b|\bupright\b(?! it)|\bphone (?:shape|size|screen)\b", c) else
                                  "1:1" if re.search(r"\bsquare\b", c) else "16:9" if re.search(r"\b(?:landscape|horizontal|widescreen|wide screen)\b", c) else None)
    if ratio and not re.search(r"\b(?:rotate|turn (?:it )?(?:left|right|around|sideways))\b", c):
        fit = "crop" if re.search(r"\bcrop|\bfill (?:the )?(?:screen|frame)|\bzoom (?:in|to fill)|\bcut (?:off )?the sides\b|\bno (?:bars|borders|blur)\b", c) else \
            "bars" if re.search(r"\b(?:black )?(?:bars|borders|letterbox|pillarbox)\b", c) else "blur" if re.search(r"\bblur", c) else None
        args = {"ratio": ratio}
        if fit:
            args["fit"] = fit
        mf = re.search(r"\bkeep (?:the )?(left|right|top|bottom)\b|\bfocus (?:on )?(?:the )?(left|right|top|bottom)\b", c)
        if mf:
            args["focus"] = mf.group(1) or mf.group(2)
        op("aspect", **args)
    if re.search(r"\bupside down\b|\brotate (?:it )?180\b|\bturn (?:it )?(?:around|180)\b", c):
        op("rotate", deg=180)
    elif re.search(r"\b(?:rotate|turn)\b.*\b(?:other way|opposite|wrong way)\b|\bother way (?:round|around)\b|\bwrong way\b", c):
        op("rotate", deg="other")
    elif re.search(r"\b(?:rotate|turn)\b.*\b(?:left|anti-?clockwise|counter-?clockwise|ccw|-90|270)\b", c):
        op("rotate", deg=270)
    elif re.search(r"\brotate\b|\b(?:it'?s|is) (?:sideways|on its side|lying down|tilted)\b|\bsideways\b|\bturn (?:it )?(?:right|clockwise|90)\b", c):
        op("rotate", deg=90)
    if re.search(r"\b(?:flip|mirror)\b", c):
        op("flip", dir="v" if re.search(r"\bvertical(?:ly)?\b|\bupside\b|\btop to bottom\b", c) else "h")
    if re.search(r"\b(?:remove|cut|crop|get rid of|delete|take off)\b.*\b(?:black )?(?:bars|borders|edges|letterbox(?:ing)?)\b|\bno (?:black )?bars\b", c) and \
            not any(o["op"] == "aspect" for o in ops):
        op("bars")
    # ------------------------------------------------ cutting
    dur = ctx.get("duration")
    found_range = False
    if re.search(r"\b(?:remove|delete|cut out|take out|get rid of|drop|skip)\b", c) and ranges(c) and not re.search(r"\bkeep\b|\bonly\b", c):
        op("cut", ranges=[[a, b] for a, b in ranges(c)])
        found_range = True
    elif ranges(c) and re.search(r"\b(?:keep|only|trim|cut|clip|just|from|between|part|section|portion)\b", c) and not any(o["op"] in ("gif",) for o in ops):
        a, b = ranges(c)[0]
        op("trim", start=a, end=b)
        found_range = True
    if not found_range:
        m = re.search(r"\b(?:keep|only|just|trim (?:it )?to|cut (?:it )?to|use|want)\b (?:only )?(?:the )?first\s+(?:" + NUMW + r"\s*)?" + UNIT + r"\b", c) or \
            re.search(r"^\s*(?:the )?first\s+" + NUMW + r"\s*" + UNIT + r"\b(?: only)?\s*$", c)
        if m:
            n = _num(m.group(1)) if m.group(1) else 1.0
            op("trim", first=n * _unit(m.group(0)))
        m2 = re.search(r"\b(?:keep|only|just|use|want)\b (?:only )?(?:the )?last\s+(?:" + NUMW + r"\s*)?" + UNIT + r"\b", c)
        if m2:
            n = _num(m2.group(1)) if m2.group(1) else 1.0
            op("trim", last=n * _unit(m2.group(0)))
        m3 = re.search(r"\b(?:cut|remove|delete|skip|drop|trim|chop|lose|get rid of)\b(?: off| out)? (?:the )?first\s+(?:" + NUMW + r"\s*)?" + UNIT + r"\b", c)
        if m3 and not m:
            n = _num(m3.group(1)) if m3.group(1) else 1.0
            op("trim", drop_start=n * _unit(m3.group(0)))
        m4 = re.search(r"\b(?:cut|remove|delete|skip|drop|trim|chop|lose|get rid of)\b(?: off| out)? (?:the )?last\s+(?:" + NUMW + r"\s*)?" + UNIT + r"\b", c)
        if m4 and not m2:
            n = _num(m4.group(1)) if m4.group(1) else 1.0
            op("trim", drop_end=n * _unit(m4.group(0)))
        m5 = re.search(r"\b(?:start|begin)s? (?:it )?(?:at|from) " + T1, c)
        if m5:
            op("trim", start=secs(m5.group(1)))
        m6 = re.search(r"\b(?:end|stop|finish)(?:s)? (?:it )?(?:at|by) " + T1, c)
        if m6:
            op("trim", end=secs(m6.group(1)))
    if re.search(r"\b(?:exactly|precisely|frame[- ]accurate|to the frame)\b", c):
        op("exact")
    if re.search(r"\b(?:without re-?encoding|lossless(?:ly)?|no re-?encod|quick(?:ly)? cut|fast cut)\b", c):
        op("lossless")
    # ------------------------------------------------ speed
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*x\b(?! ?\d)", c) or re.search(r"\b(?:speed|x)\s*(\d+(?:\.\d+)?)\b", c)
    if m and re.search(r"\b(?:speed|fast|faster|slow|slower|times|x|timelapse|time-lapse)\b", c) and not re.search(r"\bx\s*\d{3}", c):
        op("speed", factor=float(m.group(1)))
    elif re.search(r"\btwice as fast\b|\bdouble (?:the )?speed\b", c):
        op("speed", factor=2.0)
    elif re.search(r"\b(?:half (?:the )?speed|slow[- ]?mo(?:tion)?|half as fast)\b", c):
        op("speed", factor=0.5)
        if re.search(r"\bsmooth\b", c):
            op("smooth")
    elif re.search(r"\b(?:speed (?:it )?up|faster|quicker|fast forward)\b", c):
        op("speed", factor=1.5)
    elif re.search(r"\b(?:slow (?:it )?down|slower)\b", c):
        op("speed", factor=0.75)
    # ------------------------------------------------ sound
    if re.search(r"\b(?:remove|delete|mute|kill|cut|strip|take out|get rid of|no|without)\b (?:the |all |any )?(?:audio|sound|music|noise track|voice)\b|\bsilent\b|\bmute (?:it|the video)\b", c) \
            and not re.search(r"\bbackground noise\b", c):
        op("mute")
    sounds = _files(raw, ctx, AUDIO_EXT)
    if sounds and re.search(r"\b(?:replace|swap|change|use|put|add|with|as|under|behind|background|music|song|sound|audio)\b", c) and \
            not any(o["op"] == "extract_audio" for o in ops):
        mix = bool(re.search(r"\b(?:under|behind|background|beneath|low|softly|mix|on top|over)\b", c)) and not re.search(r"\breplace\b|\binstead of the (?:sound|audio)\b", c)
        a = {"file": sounds[0], "mode": "mix" if mix else "replace"}
        md = re.search(r"(-?\d+)\s*db\b", c)
        if md:
            a["db"] = float(md.group(1))
        op("audio", **a)
    m = re.search(r"\b(?:louder|turn (?:it |the (?:sound|volume|audio) )?up|boost|raise|increase)\b.*?(\d+(?:\.\d+)?)\s*db\b|\b(?:\+|plus )(\d+(?:\.\d+)?)\s*db\b", c)
    if m:
        op("volume", db=float(m.group(1) or m.group(2)))
    elif re.search(r"\b(?:quieter|softer|turn (?:it |the (?:sound|volume|audio) )?down|lower the (?:sound|volume|audio)|reduce the (?:sound|volume))\b", c):
        md = re.search(r"(\d+(?:\.\d+)?)\s*db\b", c)
        op("volume", db=-(float(md.group(1)) if md else 6.0))
    elif re.search(r"\b(?:louder|turn (?:it |the (?:sound|volume|audio) )?up|raise the (?:sound|volume)|boost the (?:sound|volume|audio)|increase the volume|too quiet|can'?t hear)\b", c):
        op("volume", db=6.0)
    if re.search(r"\bnormali[sz]e\b|\beven out the (?:sound|volume|audio)\b|\blevel (?:out )?the (?:sound|audio|volume)\b|\bsame loudness\b", c):
        op("normalize", lufs=-16.0 if re.search(r"\bpodcast\b", c) else -14.0)
    if re.search(r"\bmono\b", c):
        op("mono")
    m = re.search(r"\b(?:sound|audio|voice|lips?)\b.*\b(?:late|behind|lagging|delayed|after)\b|\b(?:late|behind|lagging|delayed)\b.*\b(?:sound|audio|voice)\b", c)
    m2 = re.search(r"\b(?:sound|audio|voice)\b.*\b(?:early|ahead|before|too soon)\b|\b(?:early|ahead)\b.*\b(?:sound|audio|voice)\b", c)
    if m or m2:
        md = re.search(r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?)\b", c) or \
            re.search(r"\b(half|quarter|third|fifth|tenth) (?:a|of a) second\b", c)
        if md:
            v = {"half": 0.5, "quarter": 0.25, "third": 0.333, "fifth": 0.2, "tenth": 0.1}.get(md.group(1)) or \
                float(md.group(1)) / (1000 if md.group(2).startswith("m") else 1)
            op("sync", delay=-v if m else v)
        else:
            return {"ops": [], "ask": "By how much is the sound off? e.g. 'the sound is 0.3 seconds late'."}
    # ------------------------------------------------ picture fixes
    if re.search(r"\bstabili[sz]|\bshak(?:y|e|ing)\b|\bsteady\b|\bjitter", c):
        op("stabilize", strength="strong" if re.search(r"\b(?:very|really|a lot|strong)\b", c) else "medium")
    if re.search(r"\bde-?interlac|\binterlac|\bcomb(?:ing)? lines\b|\blines when (?:it )?moves?\b", c):
        op("deinterlace")
    if re.search(r"\b(?:de-?noise|grain(?:y)?|noisy picture|remove (?:the )?(?:noise|grain)|dots|clean (?:up )?the picture)\b", c) and not re.search(r"\b(?:sound|audio)\b", c):
        op("denoise", strength="strong" if re.search(r"\b(?:very|really|a lot|strong)\b", c) else "medium")
    if re.search(r"\bsharpen|\bsharper\b|\bcrisper\b", c):
        op("sharpen")
    if re.search(r"\bblack and white\b|\bb ?& ?w\b|\bgr[ae]y ?scale\b|\bmonochrome\b|\bno colou?r\b", c):
        op("gray")
    m = re.search(r"\bfade (in and out|in & out|in|out)\b(?:[^0-9]*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?))?", c)
    if m:
        d = float(m.group(2) or 1.0)
        op("fade", **({"in": d} if "in" in m.group(1) else {}), **({"out": d} if "out" in m.group(1) else {}))
    # ------------------------------------------------ logo, subtitles
    pics = _files(raw, ctx, "png|jpg|jpeg|webp|svg")
    if pics and re.search(r"\b(?:logo|watermark|stamp|brand|overlay|corner|put|add)\b", c):
        corner = "tl" if re.search(r"\btop[- ]left\b|\bupper left\b", c) else "tr" if re.search(r"\btop[- ]right\b|\bupper right\b|\btop corner\b", c) else \
            "bl" if re.search(r"\bbottom[- ]left\b|\blower left\b", c) else "center" if re.search(r"\b(?:center|centre|middle)\b", c) else "br"
        a = {"file": pics[0], "corner": corner}
        ms = re.search(r"\b(small|tiny|big|large)\b", c)
        if ms:
            a["size"] = {"small": 0.1, "tiny": 0.07, "big": 0.25, "large": 0.25}[ms.group(1)]
        op("logo", **a)
    subs = _files(raw, ctx, "srt|ass|ssa|vtt")
    if subs:
        op("subtitles", file=subs[0], burn=not re.search(r"\b(?:soft|as a track|separate|switchable|turn (?:on|off)|can be turned)\b", c))
    # ------------------------------------------------ pictures from it
    pics = (r"\b(?:screenshots?|snapshots?|screen ?grabs?|stills|a still|still (?:image|frame|picture|photo)s?|thumbnails?|cover(?: (?:picture|image|photo|frame))?|"
            r"poster frame|contact sheet|storyboard|(?:pictures?|photos?|images?|frames?)(?= (?:of|from|at|every)\b)|"
            r"(?:\d+|two|three|four|five|six|eight|ten|twelve|twenty) (?:pictures?|photos?|images?|frames?))\b")
    if re.search(pics, c) and not re.search(r"\b(?:fps|frame ?rate|frames? (?:per|a) second)\b", c) and \
            not (re.search(r"\bcover\b", c) and not re.search(r"\b(?:picture|image|photo|frame|thumbnail)\b", c)):
        fmt_i = "png" if re.search(r"\bpng\b", c) else "jpg"
        if re.search(r"\b(?:contact sheet|storyboard|grid|overview|preview sheet|all in one)\b", c):
            mcount = re.search(r"\b(\d+)\s*(?:frames?|pictures?|shots?|screenshots?)\b", c)
            op("frames", sheet=True, count=int(mcount.group(1)) if mcount else 16, fmt=fmt_i)
        elif re.search(r"\bevery\s+" + T1, c):
            op("frames", every=secs(re.search(r"\bevery\s+" + T1, c).group(1)), fmt=fmt_i)
        elif re.search(r"\b(?:at|from)\s+" + T1, c):
            times = [secs(x) for x in re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:s|secs?|seconds?)\b)", c)]
            op("frames", at=[t for t in times if t is not None], fmt=fmt_i)
        elif re.search(r"\b(\d+|two|three|four|five|six|eight|ten|twelve|twenty)\s+(?:screenshots?|snapshots?|stills?|frames?|pictures?|thumbnails?)\b", c):
            n = _num(re.search(r"\b(\d+|two|three|four|five|six|eight|ten|twelve|twenty)\s+(?:screenshots?|snapshots?|stills?|frames?|pictures?|thumbnails?)\b", c).group(1))
            op("frames", count=int(n), fmt=fmt_i)
        elif re.search(r"\b(?:thumbnail|cover|poster frame|best frame|good frame)\b", c):
            op("frames", best=True, fmt=fmt_i)
        else:
            return {"ops": [], "ask": "Which moment? e.g. 'a screenshot at 0:12', 'screenshots every 10 seconds', or 'a thumbnail'."}
    # ------------------------------------------------ split, join
    if (re.search(r"\b(?:split|divide|break|chop|cut)\b.*\b(?:parts?|pieces?|clips?|chunks?|segments?|halves|in half|in two)\b", c)
            or re.search(r"\b(?:split|divide|chop)\b(?: it| the video)? every\b", c)) and not any(o["op"] == "split" for o in ops):
        m = re.search(r"\b(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:equal )?(?:parts?|pieces?|clips?|chunks?|segments?)\b", c)
        me = re.search(r"\bevery\s+" + T1, c) or re.search(T1 + r"\s*(?:long )?(?:parts?|pieces?|clips?|chunks?|segments?)\b", c)
        if m:
            op("split", parts=int(_num(m.group(1))))
        elif re.search(r"\b(?:halves|in half|in two)\b", c):
            op("split", parts=2)
        elif me and secs(me.group(1)):
            op("split", every=secs(me.group(1)))
        else:
            return {"ops": [], "ask": "Into how many parts, or how long each? e.g. 'split it into 3 parts' or 'split it every 60 seconds'."}
    vids = [f for f in _files(raw, ctx, VIDEO_EXT) if not str(f).lower().endswith(".gif")]
    if vids and (re.search(r"\b(?:join|merge|combine|stitch|append|attach|glue|add)\b", c) or
                 re.search(r"\b(?:put|place|stick|play)\b.*\b(?:after|before|at the end|at the start|at the beginning|in front)\b", c)):
        op("join", files=vids, before=bool(re.search(r"\b(?:before|at the (?:start|beginning)|in front|first)\b", c)))
    elif re.search(r"^\s*(?:join|merge|combine|stitch) (?:them|these|all|the (?:videos|clips|files))\b", c):
        op("join", files="all")
    # ------------------------------------------------ the GPU or the processor
    if re.search(r"\b(?:use|on|with) (?:the )?(?:gpu|graphics(?: card)?|intel arc|hardware)\b", c):
        op("hw", use="gpu")
    elif re.search(r"\b(?:use|on|with) (?:the )?(?:cpu|processor|software)\b", c):
        op("hw", use="cpu")
    timed = re.search(r"\d{1,2}:\d{2}|\d\s*(?:seconds?|secs?|s|minutes?|mins?|hours?)\b", c)
    if timed and not any(o["op"] in ("trim", "cut", "frames", "split", "record", "fade", "sync", "gif") for o in ops):
        return {"ops": [], "ask": None}  # a time no rule placed: the model reads it rather than a guess
    return done()


def _unit(text):
    m = re.search(r"(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\s*$", text.strip())
    u = m.group(1) if m else "s"
    return 3600.0 if u.startswith("h") else 60.0 if u.startswith("m") else 1.0
