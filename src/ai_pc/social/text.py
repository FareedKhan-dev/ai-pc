"""Words fitted to each platform, never cut silently: lengths counted the way each platform counts them (X weighs most
symbols, emoji and CJK as two and every link as 23), hashtag and mention limits, titles where a platform needs one,
LinkedIn's reserved characters escaped, long X posts turned into a numbered thread, links tagged for tracking on
request (utm_source=<platform>).

  fit(text, platform, fmt, limits, title=None, link=None) -> {"text", "title", "parts", "tags", "problems", "notes"}
"""
import re
import unicodedata
import urllib.parse

URL = re.compile(r"https?://[^\s<>\"']+", re.I)
HASHTAG = re.compile(r"(?<![\w&])#(\w[\w_]*)", re.U)
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{1,30})")
X_LIGHT = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]  # twitter-text v3: these count as one, everything else as two
JOINERS = {0x200D, 0xFE0F, 0xFE0E} | set(range(0x1F3FB, 0x1F400))  # zero-width joiner, variation selectors, skin tones


def _emoji(cp):
    return cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF


def x_length(text):
    """X's own count (twitter-text v3): links 23 each; within the light ranges 1; emoji sequences 2; the rest 2."""
    n = 0
    for _ in URL.finditer(text):
        n += 23
    rest = URL.sub("", text)
    i, cps = 0, [ord(c) for c in unicodedata.normalize("NFC", rest)]
    while i < len(cps):
        cp = cps[i]
        if _emoji(cp):
            n += 2
            i += 1
            while i < len(cps) and (cps[i] in JOINERS or (i > 0 and cps[i - 1] == 0x200D)):  # the rest of an emoji sequence is free
                i += 1
            continue
        n += 1 if any(a <= cp <= b for a, b in X_LIGHT) else 2
        i += 1
    return n


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def threads_length(text):
    """Threads counts each emoji as its UTF-8 bytes (so one emoji can take four of the 500)."""
    return sum(len(ch.encode("utf-8")) if _emoji(ord(ch)) else 1 for ch in text)


def count(text, how="chars"):
    if how == "x":
        return x_length(text)
    if how == "threads":
        return threads_length(text)
    if how == "utf16":
        return utf16_length(text)
    if how == "bytes":
        return len(text.encode("utf-8"))
    return len(text)


def hashtags(text):
    return HASHTAG.findall(text or "")


def mentions(text):
    return MENTION.findall(text or "")


def linkedin_escape(text):
    """LinkedIn's 'little text' commentary treats these as markup unless escaped with a backslash: \\ | { } @ [ ] ( ) < > # * _ ~
    (unescaped, they can cut the post short). A #word stays a hashtag."""
    out = []
    for i, ch in enumerate(text):
        if ch == "#" and i + 1 < len(text) and (text[i + 1].isalnum() or text[i + 1] == "_") and (i == 0 or not text[i - 1].isalnum()):
            out.append(ch)
        else:
            out.append("\\" + ch if ch in "\\|{}@[]()<>#*_~" else ch)
    return "".join(out)


def add_utm(text, platform, campaign=None, skip=("facebook.com", "instagram.com", "youtube.com", "youtu.be", "tiktok.com", "linkedin.com", "x.com",
                                                 "twitter.com", "threads.net", "wa.me", "whatsapp.com")):
    """Tag your own links so your website's analytics can tell which platform sent each visitor."""
    def tag(m):
        u = m.group(0)
        trail = ""
        while u and u[-1] in ".,;:!?)":
            trail, u = u[-1] + trail, u[:-1]
        p = urllib.parse.urlsplit(u)
        if any(p.netloc.lower().endswith(d) for d in skip):
            return u + trail
        q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        have = {k for k, _ in q}
        for k, v in (("utm_source", platform), ("utm_medium", "social"), ("utm_campaign", campaign)):
            if v and k not in have:
                q.append((k, v))
        return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment)) + trail
    return URL.sub(tag, text)


def split_thread(text, limit=280, how="x"):
    """A post too long for one X post as a numbered thread, split between sentences (or words), each part within the limit."""
    sentences = re.split(r"(?<=[.!?۔])\s+|\n{2,}", text.strip())
    parts, cur = [], ""
    room = limit - 7  # " (12/12)"
    for s in sentences:
        cand = (cur + " " + s).strip() if cur else s
        if count(cand, how) <= room:
            cur = cand
            continue
        if cur:
            parts.append(cur)
        cur = ""
        for w in s.split():
            cand = (cur + " " + w).strip()
            if count(cand, how) <= room:
                cur = cand
            else:
                if cur:
                    parts.append(cur)
                cur = w
    if cur:
        parts.append(cur)
    if len(parts) > 1:
        parts = [f"{p} ({i}/{len(parts)})" for i, p in enumerate(parts, 1)]
    return parts


def fit(text, platform, fmt, limits, title=None, link=None, utm=None):
    """limits: the platform's text rules (specs.TEXT[platform]): chars, how, title, title_chars, hashtags, mentions, links,
    thread (bool), escape ('linkedin'), tags_chars (YouTube tags)."""
    text = (text or "").strip()
    problems, notes = [], []
    if limits.get("chars") == 0:  # a story: no words go with it
        if text:
            notes.append(limits.get("note") or f"{limits['label']} takes no words with this kind of post; they are left out")
        return {"text": "", "title": None, "parts": None, "tags": [], "problems": problems, "notes": notes}
    if limits.get("how") == "bytes":  # YouTube refuses < and > in descriptions as in titles
        text = text.replace("<", "‹").replace(">", "›")
    if utm:
        text = add_utm(text, platform, utm if isinstance(utm, str) else None)
    if link and link not in text and limits.get("link_in_text", True):
        text = (text + "\n\n" + link).strip()
    tags = hashtags(text)
    out = {"text": text, "title": None, "parts": None, "tags": tags, "problems": problems, "notes": notes}
    if limits.get("needs_title") or title:
        t = (title or text.split("\n")[0]).strip()
        t = re.sub(r"[<>]", "", t)  # YouTube refuses < and > in titles
        tmax = limits.get("title_chars") or 100
        if count(t) > tmax:
            if title:
                problems.append(f"the title is {count(t)} characters; {limits['label']} takes {tmax}")
            else:
                t = t[: tmax - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
                notes.append(f"title made from the first line, shortened to {tmax} characters")
        out["title"] = t
    n = count(text, limits.get("how", "chars"))
    cap = limits.get("chars")
    if cap and n > cap:
        if limits.get("thread"):
            out["parts"] = split_thread(text, cap, limits.get("how", "chars"))
            notes.append(f"{n} characters is too long for one {limits['label']} post: it goes as a thread of {len(out['parts'])}")
        else:
            problems.append(f"the text is {n} characters; {limits['label']} takes {cap} (shorten it, or let me shorten it)")
    if limits.get("hashtags") is not None and len(tags) > limits["hashtags"]:
        problems.append(f"{len(tags)} hashtags; {limits['label']} allows {limits['hashtags']}")
    if limits.get("mentions") is not None and len(mentions(text)) > limits["mentions"]:
        problems.append(f"{len(mentions(text))} @mentions; {limits['label']} allows {limits['mentions']}")
    if limits.get("max_links") is not None and len(URL.findall(text)) > limits["max_links"]:
        problems.append(f"{len(URL.findall(text))} links; {limits['label']} allows {limits['max_links']}")
    if URL.search(text) and limits.get("links") == "dead":
        notes.append(f"{limits['label']} does not make links in captions clickable (put it in your bio, or say 'link in bio')")
    if limits.get("tags_chars") and tags:
        kept, used = [], 0
        for t in tags:
            if used + len(t) + 1 > limits["tags_chars"]:
                break
            kept.append(t)
            used += len(t) + 1
        out["tags"] = kept
    if limits.get("escape") == "linkedin":
        out["text"] = linkedin_escape(text)
    return out
