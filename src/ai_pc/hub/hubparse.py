"""Requests about work apps read by rules (the cheap model reads the rest into the same actions).

  parse(text, ctx) -> {"ops": [action, ...], "ask": None | "question back"}
ctx: {"services": [connected service names], "files": {name: path}, "now": datetime}
Actions: post, read, email, inbox, events, meeting, task, tasks, move, done, comment, contact, deal, upload, brief, undo, log, services;
design tools: designs, design, export, import, upload (Canva); frames, export, comments, comment, tokens (Figma).
"""
import datetime as dt
import re

QUOTE = r"[\"“”'‘’]"
EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
                                      "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
TASK_APPS = ("trello", "asana", "notion", "jira")
FIGMA_LINK = r"https?://(?:www\.)?figma\.com/(?:file|design|proto|board)/[A-Za-z0-9]{10,}[^\s\"'<>]*"
FOLDERS = r"\b(?:to|in|into|on)\s+(?:my\s+|the\s+)?(desktop|downloads?|documents?|pictures|photos|videos)\b"
CANVA_KINDS = r"(instagram post|instagram story|facebook post|youtube thumbnail|presentation|slides|deck|document|doc|whiteboard|poster|flyer|a4|" \
              r"business card|logo|banner)"


def quoted(raw):
    return [m.group(1).strip() for m in re.finditer(QUOTE + r"([^\"“”‘’]{1,}?)" + QUOTE + r"(?=\s|$|[,.;:!?])", raw)]


def when(c, now):
    """'tomorrow at 3 pm', 'friday 10am', 'on 12 october at 4:30 pm', 'next monday', 'today' -> (date, time or None)."""
    day = None
    if re.search(r"\btoday\b|\btonight\b", c):
        day = now.date()
    elif re.search(r"\btomorrow\b", c):
        day = now.date() + dt.timedelta(days=1)
    elif re.search(r"\bday after tomorrow\b", c):
        day = now.date() + dt.timedelta(days=2)
    else:
        m = re.search(r"\b(?:on |next |this )?(" + "|".join(DAYS) + r")\b", c)
        if m:
            k = DAYS.index(m.group(1))
            ahead = (k - now.weekday()) % 7 or 7
            if re.search(r"\bnext " + m.group(1), c) and ahead < 7:
                ahead += 7 if ahead <= (6 - now.weekday()) else 0
            day = now.date() + dt.timedelta(days=ahead)
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\b(?:\s+(\d{4}))?|\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", c)
        if m:
            d = int(m.group(1) or m.group(5))
            mo = MONTHS[m.group(2) or m.group(4)]
            y = int(m.group(3)) if m.group(3) else now.year
            try:
                day = dt.date(y, mo, d)
                if day < now.date() and not m.group(3):
                    day = dt.date(y + 1, mo, d)
            except ValueError:
                day = None
    t = None
    m = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", c) or re.search(r"\bat\s+(\d{1,2}):(\d{2})\b()", c)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        ap = (m.group(3) or "").replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if 0 <= h < 24 and 0 <= mi < 60:
            t = dt.time(h, mi)
    elif re.search(r"\bnoon\b", c):
        t = dt.time(12, 0)
    return day, t


def minutes_in(c):
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", c)
    if m:
        v = float(m.group(1))
        return int(v * 60) if m.group(2).startswith("h") else int(v)
    if re.search(r"\bfor (?:an|one) hour\b", c):
        return 60
    if re.search(r"\bfor half an hour\b", c):
        return 30
    return None


def service_named(c, ctx):
    for s, rx in (("slack", r"\bslack\b"), ("telegram", r"\btelegram\b"), ("whatsapp", r"\bwhats ?app\b"), ("teams", r"\b(?:ms |microsoft )?teams\b"),
                  ("google", r"\bgmail\b|\bgoogle\b|\bdrive\b|\bsheets?\b"), ("microsoft", r"\boutlook\b|\bonedrive\b|\bhotmail\b"),
                  ("trello", r"\btrello\b"), ("asana", r"\basana\b"), ("notion", r"\bnotion\b"), ("jira", r"\bjira\b"), ("hubspot", r"\bhubspot\b|\bcrm\b"),
                  ("zoom", r"\bzoom\b"), ("canva", r"\bcanva\b"), ("figma", r"\bfigma\b")):
        if re.search(rx, c):
            return s
    return None


def first(ctx, *names):
    have = ctx.get("services") or []
    return next((n for n in names if n in have), names[0] if names else None)


def parse(text, ctx=None):
    ctx = ctx or {}
    now = ctx.get("now") or dt.datetime.now()
    raw = text.strip()
    full = " ".join(raw.lower().replace("’", "'").split())
    c = re.sub(QUOTE + r"[^\"“”‘’]*?" + QUOTE + r"(?=\s|$|[,.;:!?])", ' "" ', full)  # words in quotes are content, never instructions
    out = {"ops": [], "ask": None}

    def done(*ops):
        out["ops"] = [o for o in ops if o]
        return out
    named = service_named(c, ctx)
    q = quoted(raw)
    # ---------------------------------------------------------------- the hub itself
    if re.search(r"^\s*(?:undo|take (?:that|it) back|delete (?:that|what you (?:just )?(?:sent|posted))|unsend)\b", c):
        return done({"op": "undo"})
    if re.search(r"\bwhat (?:did you|have you) (?:do|done)\b|\b(?:show (?:me )?)?(?:the )?(?:audit|activity) log\b|\bwhat did you send\b", c):
        return done({"op": "log"})
    if re.search(r"\b(?:what(?:'s| is| are)|which (?:apps|services)?\s*(?:are|is)?)\s*(?:connected|linked)\b|\bwhat can you (?:reach|use)\b", c):
        return done({"op": "services"})
    if re.search(r"\b(?:brief me|briefing|morning (?:brief|summary|report)|daily (?:brief|summary|digest)|what(?:'s| is) (?:new|happening) today|catch me up)\b", c):
        op = {"op": "brief"}
        if re.search(r"\b(?:send|post) (?:it|that|the brief)\b.*\btelegram\b|\bto (?:my )?telegram\b", c):
            op["send_to"] = "telegram"
        return done(op)
    # ---------------------------------------------------------------- design tools: Canva and Figma
    flink = re.search(FIGMA_LINK, raw)
    if flink or re.search(r"\bfigma\b", c):
        link = flink.group(0) if flink else ctx.get("figma_link")
        if not link:
            out["ask"] = "Paste the Figma file's link (in Figma: Share > Copy link)."
            return out
        fmt = re.search(r"\b(?:as|to|in)\s+(?:an?\s+)?\.?(png|svg|pdf|jpe?g)\b", c)
        if re.search(r"\bcomment(?:s)?\b", c) and q and re.search(r"\b(?:add|post|leave|write|put|comment)\b", c):
            return done({"op": "comment", "service": "figma", "link": link, "text": q[-1]})
        if re.search(r"\bcomments?\b|\bfeedback\b", c):
            return done({"op": "comments", "service": "figma", "link": link})
        if re.search(r"\b(?:colou?rs?|fonts?|text styles|styles|design tokens|tokens|palette|typography)\b", c):
            return done({"op": "tokens", "service": "figma", "link": link})
        if re.search(r"\b(?:export|download|save|get)\b", c) and not re.search(r"\b(?:website|web ?page|html|code)\b", c):
            dest = re.search(FOLDERS, c)
            return done({"op": "export", "service": "figma", "link": link, "frame": q[0] if q else None, "format": (fmt.group(1) if fmt else "png").replace("jpeg", "jpg"),
                         "to": dest.group(1) if dest else None})
        if re.search(r"\bframes?\b|\bpages?\b|\bwhat(?:'s| is) in\b|\bopen\b|\bshow\b|\blist\b", c):
            return done({"op": "frames", "service": "figma", "link": link})
    if re.search(r"\bcanva\b", c):
        known = [k for k in (ctx.get("files") or {}) if k in full]  # files the chat was started with, by their full names
        m = re.search(r"([\w\-.()]+\.(?:pptx|docx|pdf|xlsx|psd|ai|key|odp|png|jpe?g|gif|webp|heic|svg|mp4|mov))\b", raw, re.I)
        if known or m:
            fname = max(known, key=len) if known else m.group(1).strip()
            path = (ctx.get("files") or {}).get(fname.lower(), fname)
            picture = re.search(r"\.(?:png|jpe?g|gif|webp|heic|svg|mp4|mov)$", fname, re.I)
            return done({"op": "upload" if picture else "import", "service": "canva", "path": path})
        fmt = re.search(r"\b(?:as|to|in)\s+(?:an?\s+|a\s+)?\.?(pdf|png|jpe?g|gif|mp4|video|pptx|powerpoint)\b", c)
        if re.search(r"\b(?:export|download|save|get)\b", c) and fmt:
            dest = re.search(FOLDERS, c)
            mm = re.search(r"\bdesign\s+(?:called\s+|named\s+)?([\w][\w &'-]{0,60}?)\s+(?:as|to|in)\b", raw, re.I)
            name = q[0] if q else (mm.group(1).strip() if mm else None)
            if not name:
                out["ask"] = "Which Canva design? Put its name in quotes, e.g. export my Canva design \"Eid sale\" as a PDF."
                return out
            return done({"op": "export", "service": "canva", "design": name, "format": fmt.group(1).replace("jpeg", "jpg"), "to": dest.group(1) if dest else None})
        if re.search(r"\b(?:make|create|start|new|open)\b.*\bdesign\b|\b(?:make|create|start)\b.*\b" + CANVA_KINDS + r"\b", c):
            k = re.search(r"\b" + CANVA_KINDS + r"\b", c)
            return done({"op": "design", "service": "canva", "title": q[0] if q else "Untitled design", "kind": k.group(1) if k else None})
        if re.search(r"\b(?:list|show|find|search|what are|which|my)\b.*\bdesigns?\b|\bdesigns?\b", c):
            return done({"op": "designs", "service": "canva", "query": q[0] if q else None})
    # ---------------------------------------------------------------- reading
    m = re.search(r"\b(?:what(?:'s| is| was)? (?:new|happening|going on|said)|summari[sz]e|catch me up on|read|show (?:me )?(?:the )?(?:latest|messages)(?: in| from)?|"
                  r"any (?:new )?messages)\b.*?(#[\w-]+)", c)
    if m:
        hours = 24 * 7 if re.search(r"\bthis week\b|\blast week\b", c) else 24
        return done({"op": "read", "service": named if named in ("slack", "teams") else first(ctx, "slack", "microsoft"), "where": m.group(1), "hours": hours,
                     "summarize": bool(re.search(r"\bsummari[sz]e|\bwhat(?:'s| is) (?:new|happening)|\bcatch me up\b", c))})
    if re.search(r"\b(?:check|read|show|any|what(?:'s| is)? in|summari[sz]e)\b.*\b(?:e-?mails?|inbox|mail)\b|\bunread\b", c) and not re.search(r"\b(?:send|draft|write|reply)\b", c):
        return done({"op": "inbox", "service": named if named in ("google", "microsoft") else first(ctx, "google", "microsoft"),
                     "summarize": bool(re.search(r"\bsummari[sz]e|\bimportant\b", c))})
    if re.search(r"\b(?:what(?:'s| is)|show|any)\b.*\b(?:calendar|meetings?|schedule|events?|agenda)\b|\bam i free\b|\bwhat do i have\b", c) and \
            not re.search(r"\b(?:schedule|book|set up|create|arrange)\s+(?:a|an|the)\b", c):
        day, _ = when(c, now)
        return done({"op": "events", "service": named if named in ("google", "microsoft", "zoom") else first(ctx, "google", "microsoft", "zoom"),
                     "day": (day or now.date()).isoformat()})
    if re.search(r"\b(?:my|open|pending|show|list|what are)\b.*\b(?:tasks?|cards?|issues?|tickets?|to-?dos?)\b", c) and \
            not re.search(r"\b(?:add|create|make|new)\b", c):
        svc = named if named in TASK_APPS else first(ctx, *TASK_APPS)
        m = re.search(r"\b(?:in|on|from) (?:the )?([\w &-]+?)(?: board| project| list| database)?\s*$", c)
        return done({"op": "tasks", "service": svc, "where": m.group(1).strip() if m and m.group(1).strip() not in TASK_APPS else None})
    # ---------------------------------------------------------------- email
    if re.search(r"\b(?:e-?mail|mail)\b", c) and re.search(r"\b(?:send|draft|write|compose|reply)\b", c) or re.search(r"^\s*(?:e-?mail)\s+" + EMAIL, c):
        to = re.findall(EMAIL, raw)
        if not to:
            out["ask"] = "Who should the email go to? Give the address (e.g. ali@khan.pk)."
            return out
        m = re.search(r"\bsubject\s*[:\-]?\s*" + QUOTE + r"(.+?)" + QUOTE, raw, re.I) or re.search(r"\babout\s+(?:the\s+)?(.+?)(?:\s+saying\b|\s+that\b|,|$)", raw, re.I)
        subject = m.group(1).strip() if m else None
        if subject:
            subject = subject[:1].upper() + subject[1:]
        m = re.search(r"\b(?:saying|that says|with the message|body)\s*[:\-]?\s*(.+)$", raw, re.I)
        body = m.group(1).strip().strip("\"“”") if m else (q[-1] if q and (not subject or q[-1] != subject) else None)
        attach = [p for k, p in (ctx.get("files") or {}).items() if k in c]
        return done({"op": "email", "service": named if named in ("google", "microsoft") else first(ctx, "google", "microsoft"), "to": to,
                     "subject": subject or (body[:60] if body else "Hello"), "body": body or "", "attach": attach,
                     "write": not body, "about": subject})
    # ---------------------------------------------------------------- meetings
    if re.search(r"\b(?:schedule|book|set up|arrange|create|plan|add)\b.*\b(?:meeting|call|event|appointment|sync|interview)\b", c):
        day, t = when(c, now)
        if not (day and t):
            out["ask"] = "When? e.g. 'tomorrow at 3 pm' or 'on 12 October at 11 am'."
            return out
        svc = "zoom" if re.search(r"\bzoom\b", c) else named if named in ("google", "microsoft") else first(ctx, "google", "microsoft", "zoom")
        m = re.search(r"\b(?:about|for|on|titled|called)\s+" + QUOTE + r"?(?!(?:\d|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|an hour|half))"
                      r"([^\"“”,]+?)" + QUOTE + r"?(?=\s+(?:on|at|tomorrow|today|next|this|for \d|with)\b|,|$)", raw, re.I)
        title = q[0] if q else (m.group(1).strip() if m else "Meeting")
        start = dt.datetime.combine(day, t)
        return done({"op": "meeting", "service": svc, "title": title, "start": start.isoformat(), "minutes": minutes_in(c) or 30,
                     "with": re.findall(EMAIL, raw), "online": not re.search(r"\bin person\b|\bat (?:the )?office\b", c)})
    # ---------------------------------------------------------------- tasks
    if re.search(r"\b(?:add|create|make|new|open|log|file)\b.*\b(?:task|card|to-?do|issue|bug|ticket|story|row|page)\b", c) and not re.search(r"\bhubspot|\bcrm\b", c):
        svc = named if named in TASK_APPS else ("jira" if re.search(r"\b(?:bug|issue|ticket|story)\b", c) and "jira" in (ctx.get("services") or []) else
                                                first(ctx, *TASK_APPS))
        title = q[0] if q else None
        if not title:
            m = re.search(r"\b(?:task|card|to-?do|issue|bug|ticket)\s*(?:called|named|titled|:|-)?\s*(.+?)(?:\s+(?:to|in|on|due|for)\b.*)?$", raw, re.I)
            title = m.group(1).strip() if m else None
        if not title:
            out["ask"] = "What should the task say? Put it in quotes, e.g. add a trello card \"Fix the AC\" to To Do."
            return out
        m = re.search(r"\b(?:to|in|on|into)\s+(?:the\s+)?(?:list\s+|project\s+|board\s+|database\s+)?" + QUOTE + r"?([\w &/-]+?)" + QUOTE +
                      r"?(?:\s+(?:list|column|project|board|database))?(?:\s+(?:on|in)\s+(?:the\s+)?([\w &-]+?)\s+board)?(?:\s+(?:due|by|on|in)\b|\s*$|,)", raw, re.I)
        where = m.group(1).strip() if m and m.group(1).lower() not in TASK_APPS else None
        board = m.group(2).strip() if m and m.lastindex and m.lastindex >= 2 and m.group(2) else None
        day, _ = when(c, now) if re.search(r"\b(?:due|by|deadline)\b", c) else (None, None)
        kind = "Bug" if re.search(r"\bbug\b", c) else "Story" if re.search(r"\bstory\b", c) else "Task"
        return done({"op": "task", "service": svc, "title": title, "where": where, "board": board, "due": day.isoformat() if day else None, "kind": kind})
    m = re.search(r"\bmove\s+(?:the\s+)?(?:card\s+|issue\s+|task\s+)?" + QUOTE + r"?(.+?)" + QUOTE + r"?\s+to\s+(?:the\s+)?" + QUOTE + r"?([\w &-]+?)" + QUOTE +
                  r"?(?:\s+(?:list|column|status))?\s*$", raw, re.I)
    if m:
        return done({"op": "move", "service": named if named in ("trello", "jira") else first(ctx, "trello", "jira"), "item": m.group(1).strip(), "to": m.group(2).strip()})
    m = re.search(r"\b(?:mark|set)\s+" + QUOTE + r"?(.+?)" + QUOTE + r"?\s+(?:as\s+)?(?:done|complete|completed|finished)\b|\b(?:complete|finish|tick off)\s+" + QUOTE + r"?(.+?)" + QUOTE + r"?\s*$", raw, re.I)
    if m:
        return done({"op": "done", "service": named if named in ("asana", "trello", "jira") else first(ctx, "asana", "trello", "jira"),
                     "item": (m.group(1) or m.group(2)).strip()})
    m = re.search(r"\bcomment\s+(?:on\s+)?" + QUOTE + r"?(.+?)" + QUOTE + r"?\s*[:\-]\s*(.+)$", raw, re.I)
    if m:
        return done({"op": "comment", "service": named if named in ("trello", "asana", "jira") else first(ctx, "trello", "asana", "jira"), "item": m.group(1).strip(),
                     "text": m.group(2).strip().strip("\"“”")})
    # ---------------------------------------------------------------- CRM
    if re.search(r"\b(?:add|create|new|save)\b.*\b(?:contact|lead|customer|client)\b|\bto (?:hubspot|the crm)\b", c):
        emails = re.findall(EMAIL, raw)
        m = re.search(r"\b(?:add|create|save|new)\s+(?:a\s+)?(?:contact|lead|customer|client)?\s*(?:called|named)?\s*([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+)?)", raw)
        name = (m.group(1) if m else "").split()
        ph = re.search(r"(?:\+92|0)3\d{2}[\s-]?\d{7}", raw)
        co = re.search(r"\b(?:from|at|of)\s+([A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,4})", raw)
        return done({"op": "contact", "service": "hubspot", "email": emails[0] if emails else None, "first": name[0] if name else None,
                     "last": " ".join(name[1:]) or None, "phone": ph.group(0) if ph else None, "company": co.group(1) if co else None})
    m = re.search(r"\b(?:add|create|new)\s+(?:a\s+)?deal\s+" + QUOTE + r"?(.+?)" + QUOTE + r"?(?:\s+(?:worth|for|of)\s+(?:rs\.?|pkr|\$)?\s*([\d,]+))?\s*$", raw, re.I)
    if m:
        return done({"op": "deal", "service": "hubspot", "name": m.group(1).strip(), "amount": (m.group(2) or "").replace(",", "") or None})
    # ---------------------------------------------------------------- files
    m = re.search(r"\b(?:upload|put|save|send|share|attach|post)\b.*?([\w\-. ()]+\.(?:pdf|docx?|xlsx?|pptx?|png|jpe?g|gif|webp|svg|csv|txt|md|zip|7z|rar|mp4|mov|webm|mkv|avi|m4v|mp3|wav|m4a|ogg|oga|flac|aac|epub|srt|vtt|dxf|stl|glb|obj|3mf|apk|html?|json|ics|vcf|mid|musicxml|mscz))\b", raw, re.I)
    if m:
        fname = m.group(1).strip()
        path = (ctx.get("files") or {}).get(fname.lower(), fname)
        share = re.findall(EMAIL, raw)
        if re.search(r"#[\w-]+", c) or named in ("slack", "telegram"):
            ch = re.search(r"(#[\w-]+)", c)
            return done({"op": "upload", "service": "telegram" if named == "telegram" else "slack", "path": path, "to": ch.group(1) if ch else "me"})
        return done({"op": "upload", "service": named if named in ("google", "microsoft") else first(ctx, "google", "microsoft"), "path": path, "share_with": share})
    # ---------------------------------------------------------------- messages
    m = re.search(r"\b(?:post|send|say|saying|tell|message|announce|write|dm|text)\b", c) or re.match(r"^\s*(?:whats ?app|telegram|slack)\b", c)
    if m:
        to = None
        mm = re.search(r"(#[\w-]+)", raw)
        if mm:
            to = mm.group(1)
        mm = re.search(r"(?:message|dm|tell|to)\s+(@[\w.-]+)", raw) or re.search(r"(?<![\w.])(@[a-z][\w.-]+)", raw)
        if not to and mm:
            to = mm.group(1)
        if re.search(r"\b(?:send me|text me|message me|remind me|notify me|tell me)\b", c):
            to = "me"
        ph = re.search(r"(?:\+92|0092|0)3\d{2}[\s-]?\d{7}", raw)
        svc = named or ("whatsapp" if ph else "telegram" if to == "me" else first(ctx, "slack", "microsoft", "telegram"))
        if svc == "whatsapp":
            to = ph.group(0) if ph else to
        if svc == "teams":
            svc = "microsoft"
        text_ = q[0] if q else None
        if not text_:
            mm = re.search(r"(?:\:\s*|\bsaying\s+|\bthat\s+)(.+)$", raw, re.I)
            text_ = mm.group(1).strip() if mm else None
        if not text_:
            out["ask"] = "What should it say? Put the words in quotes, e.g. post \"Meeting moved to 4 pm\" to #general."
            return out
        if not to:
            out["ask"] = "Where should it go? e.g. #general, @ali, 'me' (your Telegram) or a phone number for WhatsApp."
            return out
        team = re.search(r"\bin\s+(?:the\s+)?([\w &-]+?)\s+team\b", raw, re.I)
        return done({"op": "post", "service": svc, "to": to, "text": text_, **({"team": team.group(1)} if team else {})})
    return out
