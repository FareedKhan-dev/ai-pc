"""Requests about social media read by rules (the cheap model reads only what these cannot).

  parse(text, ctx) -> {"ops": [...], "ask": None | "question back"}
ctx: {"connected": [platforms], "files": {name: path}, "now": datetime, "last": {post or job focus}}
Ops: compose (platforms, formats, media, text, title, when, privacy, fill, trim, utm), queue, cancel, delete, results,
comments, reply, hide, edit, retry, connected, auto (on/off), best_time.
"""
import re

from ..hub.hubparse import QUOTE, quoted, when

PLATFORMS = {"facebook": r"\bfacebook\b|\bfb\b", "instagram": r"\binstagram\b|\binsta\b|\big\b", "youtube": r"\byoutube\b|\byt\b",
             "tiktok": r"\btik ?tok\b", "linkedin": r"\blinked ?in\b", "x": r"\btwitter\b|\btweet\b|\bon x\b|\bto x\b|\b(?<!\w)x\b(?= and|,| or|$)",
             "threads": r"\bthreads\b"}
FORMATS = {"reel": r"\breels?\b", "story": r"\bstor(?:y|ies)\b", "short": r"\bshorts?\b", "carousel": r"\bcarousel\b|\bslides?\b|\balbum\b"}
FILE = r"([\w\-.()]+\.(?:mp4|mov|m4v|mkv|webm|avi|jpe?g|png|webp|gif|heic))\b"


def platforms_in(c, connected=None):
    if re.search(r"\b(?:everywhere|all (?:my )?(?:platforms|accounts|socials|social media)|every platform)\b", c):
        return list(connected or PLATFORMS)
    return [p for p, rx in PLATFORMS.items() if re.search(rx, c)]


def formats_in(c, plats):
    """Format per platform: 'reel' for Instagram/Facebook, 'short' for YouTube, 'story' wherever stories exist."""
    out = {}
    for f, rx in FORMATS.items():
        if re.search(rx, c):
            for p in plats:
                if f == "reel" and p in ("instagram", "facebook"):
                    out[p] = "reel"
                elif f == "short" and p == "youtube":
                    out[p] = "short"
                elif f == "story" and p in ("instagram", "facebook"):
                    out[p] = "story"
                elif f == "carousel" and p in ("instagram", "threads", "facebook", "linkedin"):
                    out[p] = "carousel"
    return out


def files_in(raw, ctx):
    names = ctx.get("files") or {}
    low = raw.lower()
    known = [k for k in names if k in low]
    found = [m.group(1) for m in re.finditer(FILE, raw, re.I)]
    out = []
    for f in sorted(set(known), key=low.find) + [f for f in found if f.lower() not in known]:
        p = names.get(f.lower(), f)
        if p not in out:
            out.append(p)
    return out


def caption_in(raw):
    q = quoted(raw)
    m = re.search(r"\b(?:caption|saying|with the (?:text|words|caption)|that says|description)\s*[:\-]?\s*(.+)$", raw, re.I | re.S)
    if q:
        return q[-1] if not re.search(r"\btitled?\s*" + QUOTE, raw, re.I) or len(q) == 1 else q[-1]
    return m.group(1).strip().strip("\"“”") if m else None


def title_in(raw):
    m = re.search(r"\btitled?\s*" + QUOTE + r"([^\"“”‘’]+)" + QUOTE, raw, re.I) or re.search(r"\btitle\s*[:\-]\s*" + QUOTE + r"?([^\"“”\n]+?)" + QUOTE + r"?(?:,|$|\s+(?:and|with)\b)", raw, re.I)
    return m.group(1).strip() if m else None


def parse(text, ctx=None):
    ctx = ctx or {}
    raw = text.strip()
    full = " ".join(raw.lower().replace("’", "'").split())
    c = re.sub(QUOTE + r"[^\"“”‘’]*?" + QUOTE + r"(?=\s|$|[,.;:!?])", ' "" ', full)  # words in quotes are content, never instructions
    out = {"ops": [], "ask": None}
    conn = ctx.get("connected") or []

    def done(*ops):
        out["ops"] = [o for o in ops if o]
        return out
    plats = platforms_in(c, conn)
    # ---------------------------------------------------------------- the lane itself
    if re.search(r"\b(?:what(?:'s| is| are)|which)\b.*\b(?:connected|linked)\b|\bmy accounts\b", c):
        return done({"op": "connected"})
    m = re.search(r"\b(?:turn|switch|set)\s+(on|off)\b.*\b(?:auto(?:matic)?|scheduled?)\s*(?:posting|publishing)?\b|\bauto(?:matic)? posting\s+(on|off)\b", c)
    if m:
        return done({"op": "auto", "on": (m.group(1) or m.group(2)) == "on"})
    if re.search(r"\bwhen should i post\b|\bbest time(?:s)? to post\b|\bbest time\b", c):
        return done({"op": "best_time", "platforms": plats})
    if re.search(r"\b(?:what(?:'s| is)|show|list)\b.*\b(?:scheduled|queue|queued|planned|pending|lined up)\b|\bmy queue\b|\bupcoming posts\b", c):
        return done({"op": "queue"})
    if re.search(r"\b(?:how did|how are|how's|how is|stats|statistics|analytics|insights|performance|results|views|reach|engagement)\b", c) and \
            not re.search(r"\b(?:post|upload|share|publish)\s+(?:this|it|the)\b", c):
        days = 7 if re.search(r"\bweek\b", c) else 30 if re.search(r"\bmonth\b", c) else 1 if re.search(r"\btoday\b|\byesterday\b", c) else None
        return done({"op": "results", "platforms": plats, "days": days, "report": bool(re.search(r"\breport\b|\bexcel\b|\bspreadsheet\b|\bpdf\b", c))})
    m = re.search(r"\b(?:reply|answer|respond)(?: to)?(?: the)?\s+(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last|\d+)"
                  r"(?:st|nd|rd|th)?(?:\s+(?:one|comment|reply))?\s*(?:[:\-,]|saying|with|and say)\s*(.+)$", raw, re.I) or \
        re.search(r"\b(?:reply|answer|respond) (?:to )?(?:comment )?#?(\d+|@?[\w.]+)\s*(?:[:\-]|saying|with)\s*(.+)$", raw, re.I)
    if m:
        ords = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "last": "last"}
        to = ords.get(m.group(1).lower(), m.group(1).lstrip("@#"))
        return done({"op": "reply", "to": str(to), "text": m.group(2).strip().lstrip(":-, ").strip().strip("\"“”")})
    m = re.search(r"\bhide (?:comment )?#?(\d+)\b", c)
    if m:
        return done({"op": "hide", "to": m.group(1)})
    if re.search(r"\b(?:new |any |show |read |check )?(?:comments|replies)\b", c) and not re.search(r"\bturn off comments\b|\bno comments\b", c):
        return done({"op": "comments", "platforms": plats})
    m = re.search(r"\b(?:cancel|don'?t post|stop)\b(?:\s+the)?(?:\s+(?:post|posts|one))?", c)
    if m and not re.search(r"\bcomment", c):
        return done({"op": "cancel", "platforms": plats, "which": "last"})
    if re.search(r"\b(?:delete|remove|take down)\b.*\b(?:post|video|reel|tweet|it|that|short|story)\b", c):
        return done({"op": "delete", "platforms": plats, "which": "last"})
    if re.search(r"\b(?:retry|try again)\b", c):
        return done({"op": "retry", "platforms": plats})
    if re.search(r"\b(?:change|edit|fix|update)\b.*\b(?:caption|text|title)\b|\bmove it to\b|\b(?:reschedule|postpone)\b", c) and ctx.get("last"):
        day, t = when(c, ctx.get("now")) if re.search(r"\b(?:move|reschedule|postpone|to)\b.*\b(?:at|am|pm|tomorrow|today|monday|tuesday|wednesday|"
                                                     r"thursday|friday|saturday|sunday)\b", c) else (None, None)
        q = quoted(raw)
        return done({"op": "edit", "text": q[-1] if q and re.search(r"\bcaption|text\b", c) else None,
                     "title": q[-1] if q and re.search(r"\btitle\b", c) else None, "day": day.isoformat() if day else None, "time": t.isoformat() if t else None})
    # ---------------------------------------------------------------- composing
    files = files_in(raw, ctx)
    verb = re.search(r"\b(?:post|upload|share|publish|put|send|schedule|tweet|go live with)\b", c)
    if verb and (plats or files):
        if not plats:
            out["ask"] = "Where should it go? e.g. Instagram, Facebook, YouTube, TikTok, LinkedIn, X, Threads, or 'everywhere'."
            return out
        if not files and ctx.get("last_file"):
            files = [ctx["last_file"]] if re.search(r"\b(?:it|this|that|the (?:video|picture|photo|image|poster|reel))\b", c) else []
        day, t = when(c, ctx.get("now"))
        at = None
        if day or t:
            if not t:
                out["ask"] = "At what time? e.g. 'tomorrow at 7 pm'."
                return out
            at = {"day": (day or ctx["now"].date()).isoformat(), "time": t.isoformat()}
        priv = re.search(r"\b(private|unlisted|public|only me|friends)\b", c)
        return done({"op": "compose", "platforms": plats, "formats": formats_in(c, plats), "media": files, "text": caption_in(raw), "title": title_in(raw),
                     "when": at, "privacy": {"only me": "private"}.get(priv.group(1), priv.group(1)) if priv else None,
                     "fill": "fit" if re.search(r"\b(?:fit|whole|don'?t crop|no crop|blurred)\b", c) else "crop" if re.search(r"\bcrop\b", c) else None,
                     "trim": bool(re.search(r"\b(?:cut|trim|shorten)\b.*\b(?:it|to|down)\b", c)),
                     "utm": bool(re.search(r"\b(?:track(?:ing)?|utm)\b", c)), "thread": bool(re.search(r"\bthread\b", c))})
    return out
