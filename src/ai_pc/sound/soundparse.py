"""Requests about a recording read by rules (no model): 'clean it up', 'remove the hum', 'make it louder', 'cut the
first 5 seconds', 'remove 1:20 to 1:45', 'remove the long pauses', 'cut the ums', 'speed it up 1.25x', 'add music.mp3
under my voice', 'add captions', 'word by word captions in yellow', 'save as mp3
under 5 MB', 'export the video', 'how loud is it?'.

  parse(clause, ctx) -> {"ops": [{"op": ..., "args": {...}}], "ask": None | "question back"}
ctx: {"has_video": bool, "has_captions": bool, "files": {name: path} for files the person mentioned}
"""

import re

from ai_pc.sound.ops import TARGETS

NUM = r"(\d+(?:\.\d+)?)"
WORDNUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "half": 0.5,
    "a": 1,
    "an": 1,
}
TIME = r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?|m|min|mins|minutes?)(?:\s*(?:and\s*)?\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?))?)"
COLOR_WORDS = r"(white|yellow|green|red|blue|orange|pink|cyan|black|purple|gold)"


def secs(s):
    """'1:20' -> 80, '1:02:03' -> 3723, '90s' -> 90, '2 min 10 s' -> 130, '5 seconds' -> 5."""
    s = s.strip().lower()
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        v = 0.0
        for p in parts:
            v = v * 60 + p
        return v
    m = re.match(r"(\d+(?:\.\d+)?)\s*(m|min|mins|minutes?)\b(?:\s*(?:and\s*)?(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?))?", s)
    if m:
        return float(m.group(1)) * 60 + float(m.group(3) or 0)
    m = re.match(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _n(s):
    return float(WORDNUM.get(s, s)) if s else None


def _file(c, raw, ctx):
    """A file the person names: a path, or a name with an audio extension (looked up in ctx['files'])."""
    ext = r"\.(?:mp3|wav|m4a|aac|ogg|opus|flac|wma)"
    m = re.search(rf"([A-Za-z]:\\[^\"'<>|]+?{ext})\b|\"([^\"]+?{ext})\"|'([^']+?{ext})'|([\w\-.()]+{ext})\b", raw, re.I)
    if not m:
        return None
    name = next(g for g in m.groups() if g)
    return (ctx.get("files") or {}).get(name.lower(), name)


def parse(clause, ctx=None):
    ctx = ctx or {}
    raw = clause.strip()
    c = " ".join(raw.lower().replace("’", "'").split())
    out = {"ops": [], "ask": None}

    def done(*ops):
        out["ops"] = [o for o in ops if o]
        return out

    def op(op_name, **args):
        return {"op": op_name, "args": args}

    # ------------------------------------------------ questions
    if re.search(r"^\s*(?:how loud|what(?:'s| is) the (?:loudness|volume|level)|is it (?:loud|quiet) enough|is it too (?:loud|quiet))\b", c):
        return done(op("ask", what="loudness"))
    if re.search(
        r"^\s*(?:is (?:it|there|the (?:audio|recording|sound)) (?:noisy|clean|any (?:noise|hum|hiss|buzz))|how (?:clean|noisy|good) is|any (?:noise|hum|problems)|"
        r"check (?:it|the audio|the sound|the recording)|what(?:'s| is) wrong with (?:it|the audio))",
        c,
    ):
        return done(op("ask", what="quality"))
    if re.search(r"^\s*(?:how long is|what(?:'s| is) the (?:length|duration))\b", c):
        return done(op("ask", what="length"))
    if re.search(
        r"^\s*(?:what (?:does (?:it|he|she) say|did (?:he|she|they|i) say|is said)|transcri(?:be|pt)(?: it| this)?\s*$|what are the words|show (?:me )?the transcript)",
        c,
    ):
        return done(op("ask", what="transcript"))
    if re.search(r"^\s*what language\b", c):
        return done(op("ask", what="language"))
    if re.search(r"^\s*(?:compare|before and after|what changed|what did you (?:do|change))\b", c):
        return done(op("ask", what="compare"))
    # ------------------------------------------------ saving
    m = re.search(
        r"\b(?:save|export|give me|download|convert|send|make it an?)\b.*?\b(mp3|wav|m4a|aac|ogg|opus|flac|mp4|video|srt|vtt|ass|subtitles? file|transcript|"
        r"text|txt|word|docx)\b|^\s*(?:as |in )?(mp3|wav|m4a|ogg|flac|mp4)\s*(?:please)?\s*$|\bfor whatsapp\b|\bunder \d+(?:\.\d+)?\s*mb\b",
        c,
    )
    if m and not re.search(r"\b(?:add|make|create|generate)\b.*\b(?:captions|subtitles)\b(?!.*\bfile\b)", c):
        fmt = (m.group(1) or m.group(2) or "").replace(" ", "") if m.lastindex else ""
        fmt = {"video": "mp4", "subtitlesfile": "srt", "subtitlefile": "srt", "text": "txt", "word": "docx", "transcript": "txt", "aac": "m4a"}.get(
            fmt, fmt
        )
        if not fmt:
            fmt = "ogg" if "whatsapp" in c and not ctx.get("has_video") else ("mp4" if ctx.get("has_video") and "video" in c else "mp3")
        if fmt == "txt" and re.search(r"\bword\b|\bdocx\b", c):
            fmt = "docx"
        args = {"fmt": fmt}
        mm = re.search(r"\bunder (\d+(?:\.\d+)?)\s*mb\b", c)
        if mm:
            args["max_mb"] = float(mm.group(1))
        if "whatsapp" in c:
            args["for"] = "whatsapp"
        if fmt == "mp4":
            args["burn"] = not re.search(r"\b(?:soft|without burning|not burned|selectable|that can be turned off)\b", c)
        mm = re.search(r"\b(\d{2,3})\s*k(?:bps)?\b", c)
        if mm:
            args["kbps"] = int(mm.group(1))
        return done(op("export", **args))
    # ------------------------------------------------ captions
    if re.search(r"\b(?:captions?|subtitles?|subs)\b", c) or re.search(r"\bword[- ]by[- ]word\b|\bkaraoke\b", c):
        ops = []
        style = {}
        if re.search(r"\bword[- ]by[- ]word\b|\bone word at a time\b|\bhormozi\b|\b(?:tiktok|reels?|shorts) style\b|\bbold\b|\bbig\b(?! enough)", c):
            style["kind"] = "bold"
        elif re.search(r"\bkaraoke\b|\bhighlight (?:each|the) word\b", c):
            style["kind"] = "karaoke"
        elif re.search(r"\bbox(?:ed)?\b|\bbackground (?:box|behind)\b|\bblack (?:box|background|bar)\b", c):
            style["kind"] = "boxed"
        elif re.search(r"\b(?:simple|clean|normal|plain|youtube)\b", c):
            style["kind"] = "clean"
        m = re.search(COLOR_WORDS + r"(?:\s+(?:captions?|subtitles?|text|words?|colou?r))?", c)
        if m and re.search(r"\b(?:make|in|colou?r|turn)\b", c):
            if re.search(r"\bhighlight", c):
                style["highlight"] = m.group(1)
            else:
                style["color"] = m.group(1)
        if re.search(r"\b(?:bigger|larger)\b", c):
            style["size_by"] = 1.25
        elif re.search(r"\bsmaller\b", c):
            style["size_by"] = 0.8
        m = re.search(r"\b(?:at|to|on) the (top|bottom|middle|centre|center)\b", c)
        if m:
            style["position"] = {"centre": "middle", "center": "middle"}.get(m.group(1), m.group(1))
        if re.search(r"\b(?:all )?(?:caps|upper ?case|capital)\b", c):
            style["upper"] = True
        elif re.search(r"\blower ?case\b|\bnormal case\b|\bsentence case\b", c):
            style["upper"] = False
        if re.search(r"\b(?:remove|delete|no|turn off|drop)\b.*\b(?:captions?|subtitles?)\b", c):
            return done(op("captions", remove=True))
        if style or not ops or re.search(r"\b(?:add|make|create|generate|put|burn)\b", c):
            ops.insert(0, op("captions", **style))
        if re.search(r"\bburn\w*\b|\binto the video\b|\bon the video\b", c) and ctx.get("has_video"):
            ops.append(op("export", fmt="mp4", burn=True))
        return done(*ops)
    m = re.search(r"\b(?:change|replace|fix|correct)\s+['\"]?(.+?)['\"]?\s+(?:to|with|->|into)\s+['\"]?(.+?)['\"]?\s*$", raw, re.I)
    if m and ctx.get("has_captions"):
        return done(op("fix_words", old=m.group(1), new=m.group(2)))
    # ------------------------------------------------ cleaning
    platform = next((p for p in TARGETS if re.search(rf"\b{p}\b", c)), None)
    m = re.search(r"(-\d+(?:\.\d+)?)\s*lufs\b", c)
    lufs = float(m.group(1)) if m else None
    if re.search(
        r"\bclean (?:it|this|the (?:audio|sound|recording|voice)|my (?:voice|audio|recording))?\s*(?:up)?\b|\bfix (?:the |my |this )?(?:audio|sound|voice|recording|it)\b"
        r"|\bmake (?:it|my voice|the voice|the audio) (?:sound )?(?:clear|clearer|better|professional|crisp)\b|\b(?:studio|podcast|professional) (?:quality|sound)\b"
        r"|\benhance (?:it|the (?:audio|voice|sound))\b|\bimprove (?:the )?(?:audio|sound|voice)\b",
        c,
    ):
        return done(op("clean", **({"platform": platform} if platform else {}), **({"lufs": lufs} if lufs else {})))
    ops = []
    strength = (
        "light"
        if re.search(r"\b(?:a (?:little|bit)|slightly|light(?:ly)?|gently)\b", c)
        else "strong"
        if re.search(r"\b(?:completely|all (?:of )?the|strong(?:ly)?|a lot|totally|heav(?:y|ily))\b", c)
        else "medium"
    )
    if re.search(r"\b(?:hum|humming|buzz(?:ing)?|electric(?:al)? (?:noise|sound|hum)|mains)\b", c):
        ops.append(op("dehum", **({"hz": 60} if re.search(r"\b60\b", c) else {})))
    if (
        re.search(
            r"\b(?:background )?noise\b|\bhiss(?:ing)?\b|\bstatic\b|\b(?:fan|ac|a\.c\.|generator|traffic|crowd) (?:noise|sound)s?\b|\bdenoise\b", c
        )
        and not ops
    ):
        ops.append(op("denoise", strength=strength))
    if re.search(r"\brumble\b|\blow (?:end|frequenc\w*) (?:noise|rumble)\b|\bwind noise\b|\bboomy\b|\bthumps?\b", c):
        ops.append(op("highpass"))
    if re.search(r"\b(?:harsh|sharp|hissy) (?:s|s's|ss)\b|\bsibilan\w*\b|\b's' sounds?\b|\bs sounds?\b|\bde-?ess\w*\b", c):
        ops.append(op("deess", strength=strength))
    if re.search(r"\bclicks?\b|\bpops?\b|\bcrackl\w*\b|\bmouth noise\b", c) and not re.search(r"\bmusic\b", c):
        ops.append(op("declick"))
    if re.search(r"\bclipp(?:ed|ing)\b|\bdistort(?:ed|ion)\b|\bcrunchy\b", c):
        ops.append(op("declip"))
    if re.search(
        r"\beven (?:out|up)\b|\b(?:consistent|same|steady) (?:volume|level)\b|\bcompress\w*\b|\bsome parts (?:are )?(?:too )?(?:quiet|loud)\b", c
    ):
        ops.append(op("compress", amount=strength))
    if re.search(r"\bnormali[sz]e\b|\bloudness\b", c) or (platform and re.search(r"\b(?:for|ready for|standard)\b", c) and not ops) or lufs:
        ops.append(op("normalize", **({"platform": platform} if platform else {}), **({"lufs": lufs} if lufs else {})))
    m = re.search(
        r"\b(louder|quieter|softer|lower the volume|raise the volume|volume (?:up|down)|boost (?:it|the volume)|turn (?:it )?(?:up|down))\b", c
    )
    if m and not re.search(r"\bmusic|\bsong\b|\bbgm\b", c):
        up = m.group(1) in ("louder", "raise the volume", "volume up", "boost it", "boost the volume", "turn up", "turn it up")
        mm = re.search(r"\bby\s*(\d+(?:\.\d+)?)\s*db\b", c)
        db = float(mm.group(1)) if mm else (3 if strength == "light" else 10 if strength == "strong" else 6)
        ops.append(op("volume", db=db if up else -db))
    # ------------------------------------------------ time
    m = re.search(
        r"\b(?:cut|remove|delete|trim|drop|chop)(?: off)? the (first|last) "
        + r"(\d+(?:\.\d+)?|"
        + "|".join(WORDNUM)
        + r")\s*(?:s|sec|secs|seconds?|(m|min|mins|minutes?))\b",
        c,
    )
    if m:
        v = _n(m.group(2)) * (60 if m.group(3) else 1)
        ops.append(op("trim", **({"start": v} if m.group(1) == "first" else {"drop_end": v})))
    m = re.search(r"\b(?:start|begin) (?:it )?(?:at|from) " + TIME, c)
    if m:
        ops.append(op("trim", start=secs(m.group(1))))
    m = re.search(r"\b(?:end|stop) (?:it )?at " + TIME, c)
    if m:
        ops.append(op("trim", end=secs(m.group(1))))
    m = re.search(r"\bkeep (?:only )?(?:from )?" + TIME + r"\s*(?:to|-|until|till)\s*" + TIME, c)
    if m:
        ops.append(op("keep", start=secs(m.group(1)), end=secs(m.group(2))))
    elif re.search(r"\b(?:cut|remove|delete|drop|skip)\b", c):
        rngs = re.findall(r"(?:from\s+)?" + TIME + r"\s*(?:to|-|until|till|and)\s*" + TIME, c)
        if rngs:
            ops.append(op("cut", ranges=[[secs(a), secs(b)] for a, b in rngs]))
    m = re.search(r"\bfade (?:it )?in\b(?:\s*(?:for|over|of)?\s*" + NUM + r"\s*(?:s|sec|seconds?))?", c)
    m2 = re.search(r"\bfade (?:it )?out\b(?:\s*(?:for|over|of)?\s*" + NUM + r"\s*(?:s|sec|seconds?))?", c)
    m3 = re.search(r"\bfade (?:it )?in and out\b(?:\s*(?:for|over|of)?\s*" + NUM + r"\s*(?:s|sec|seconds?))?", c)
    if m3:
        v = float(m3.group(1) or 2)
        ops.append(op("fade", **{"in": v, "out": v}))
    elif m or m2:
        ops.append(op("fade", **{"in": float(m.group(1) or 2) if m else 0, "out": float(m2.group(1) or 3) if m2 else 0}))
    if re.search(
        r"\b(?:remove|cut|shorten|tighten|trim|delete|take out|get rid of)\b.*\b(?:pauses?|silences?|gaps?|dead air|breaks)\b|\btighten (?:it )?up\b|\bjump ?cuts?\b",
        c,
    ):
        mm = re.search(r"\b(?:longer than|over|more than)\s*" + NUM + r"\s*(?:s|sec|seconds?)", c)
        ops.append(op("tighten", max_pause=float(mm.group(1)) if mm else (0.3 if re.search(r"\ball\b|\bevery\b", c) else 0.5)))
    if re.search(r"\b(?:ums?|uhs?|umms?|uhms?|errs?|filler(?: words?)?|hesitations?)\b", c):
        ops.append(op("fillers"))
    m = re.search(
        r"\b"
        + NUM
        + r"\s*x\b|\b"
        + NUM
        + r"\s*times (?:faster|slower|speed)\b|\bspeed\s*(?:it\s*)?(?:to|at)\s*"
        + NUM
        + r"(?:\s*x)?\b|\b(\d+)\s*% (faster|slower)\b",
        c,
    )
    if m and re.search(r"\bspeed|faster|slower|\d\s*x\b", c):
        if m.group(5):  # '20% slower'
            f = 1 + float(m.group(4)) / 100 * (1 if m.group(5) == "faster" else -1)
        else:
            f = float(m.group(1) or m.group(2) or m.group(3))
            if re.search(r"\bslower\b", c) and f > 1:
                f = 1 / f
        ops.append(op("speed", factor=round(f, 4)))
    elif re.search(r"\bspeed (?:it )?up\b|\bfaster\b", c):
        ops.append(op("speed", factor=1.15 if strength == "light" else 1.5 if strength == "strong" else 1.25))
    elif re.search(r"\bslow (?:it )?down\b|\bslower\b", c):
        ops.append(op("speed", factor=0.9 if strength == "light" else 0.75 if strength == "strong" else 0.85))
    m = re.search(r"\b([+-]?\d+(?:\.\d+)?)\s*semi-?tones?\b", c)
    if m:
        v = float(m.group(1))
        ops.append(op("pitch", semitones=-abs(v) if re.search(r"\b(?:down|lower|deeper)\b", c) else v))
    elif re.search(r"\bdeeper\b|\blower (?:the )?(?:pitch|voice)\b|\bmore bass in (?:my|the) voice\b|\bmanly\b", c):
        ops.append(op("pitch", semitones=-2 if strength == "light" else -5 if strength == "strong" else -3))
    elif re.search(r"\bhigher (?:the )?(?:pitch|voice)\b|\braise the pitch\b", c):
        ops.append(op("pitch", semitones=2 if strength == "light" else 5 if strength == "strong" else 3))
    elif re.search(r"\bchipmunk\b|\bcartoon voice\b", c):
        ops.append(op("pitch", semitones=7, natural=False))
    # ------------------------------------------------ mixing and effects
    f = _file(c, raw, ctx)
    musicish = re.search(r"\bmusic|\bsong\b|\bbgm\b|\bbackground (?:track|tune)\b|\bunder (?:my|the|his|her) voice\b|\bbehind (?:my|the) voice\b", c)
    if (
        musicish
        and (f or re.search(r"\b(?:add|put|with|use|play)\b", c))
        and not re.search(r"\b(?:remove|no|without|take out)\b.*\bmusic\b", c)
        and not re.search(r"\bmusic\b.*\b(?:quieter|louder|lower|higher|softer|down|up)\b|\b(?:quieter|louder|lower|softer)\b.*\bmusic\b", c)
    ):
        if not f:
            out["ask"] = "Which music file? Name it (e.g. 'add music.mp3 under my voice') or give its full path."
            return out
        mm = re.search(r"\b(?:quiet|soft|low)(?:er)?\b", c)
        ops.append(
            op(
                "music",
                file=f,
                below=24 if mm else (12 if re.search(r"\b(?:loud|louder)\b", c) else 18),
                duck=not re.search(r"\bno duck|\bwithout duck|\bconstant\b", c),
            )
        )
    elif musicish and re.search(r"\b(?:quieter|lower|softer|down)\b", c):
        ops.append(op("music_level", by=-6 if not re.search(r"\b(?:much|a lot)\b", c) else -10))
    elif musicish and re.search(r"\b(?:louder|higher|up)\b", c):
        ops.append(op("music_level", by=6 if not re.search(r"\b(?:much|a lot)\b", c) else 10))
    elif f and re.search(r"\b(?:add|append|join|attach|put|stick|combine|merge)\b|\b(?:intro|outro)\b", c):
        ops.append(
            op(
                "join",
                file=f,
                before=bool(re.search(r"\bintro\b|\bat the (?:start|beginning)\b|\bbefore\b", c)),
                crossfade=1.0 if re.search(r"\bcross-?fade\b|\bsmooth(?:ly)?\b|\bblend\b", c) else 0,
            )
        )
    if re.search(r"\becho\b", c):
        ops.append(op("echo"))
    if re.search(r"\breverb\b|\b(?:hall|room|church|cathedral) (?:sound|effect)\b|\bspacious\b", c):
        ops.append(op("reverb"))
    if re.search(
        r"\b(?:tele)?phone (?:call )?(?:effect|voice|sound)\b|\bradio (?:effect|voice)\b|\bwalkie[- ]talkie\b|\bover the phone\b|\bold radio\b", c
    ):
        ops.append(op("telephone"))
    if re.search(r"\b(?:make it |to |convert to )?mono\b", c) and not re.search(r"\bstereo\b", c):
        ops.append(op("mono"))
    elif re.search(r"\b(?:make it |to |convert to )stereo\b", c):
        ops.append(op("stereo"))
    if re.search(r"\bvoice[- ]?over\b|\bread (?:this|it|the following) (?:out|aloud)\b|\bsay:", c):
        m = re.search(r"(?:voice[- ]?over|aloud|say)\s*[:\-]?\s*['\"]?(.{8,}?)['\"]?\s*$", raw, re.I)
        if m:
            ops.append(op("voiceover", text=m.group(1), voice="hazel" if re.search(r"\bbritish|uk|hazel|female british\b", c) else "zira"))
    return done(*ops)
