"""What a template IS, from what the client shares: a CapCut template link, a screenshot of its page, or the words.

  meta = from_link(url)                 one polite fetch of the template's public page (the client's own request):
                                        title, author, number of clips, length, uses, likes, size, hashtags
  meta = from_image(path, planner)      the same fields read off a screenshot by the vision model
  meta = from_text("SLOWMO HDR 4 clips 15s #slowmo #eid")

CapCut's rules are kept (robots.txt and llms.txt, checked 2026-10-03): its /templates/ folder and template links that
carry tracking parameters (from_page, from_page_click) are not for automated access, so a link is cleaned to
/template-detail/<id> first and checked against the robots rules before the one fetch. No login, no crawling of
listings, no media downloads: only the page the client points at, cached for a day.
"""
import html as _html
import json
import re
import time
import urllib.request
from pathlib import Path

from .config import ROOT

PAGES = ROOT / "state" / "templates" / "pages"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ai-pc/0.1 (personal, user-initiated)"
UA_TOKEN = "ai-pc"  # our own name in robots.txt
DETAIL = re.compile(r"^https?://(?:www\.)?capcut\.com/(?:[a-z]{2}(?:-[a-z]{2,4})?/)?template-detail/(?:[^/?#]+/)?(\d{8,25})/?(?:[?#].*)?$", re.I)


class NotAllowed(Exception):
    pass


def clean_url(url):
    """(template id, the clean /template-detail/<id> URL). Tracking parameters are dropped (CapCut asks agents not to
    fetch links that carry them); anything that is not one template's page is refused."""
    url = str(url).strip()
    m = DETAIL.match(url)
    if not m:
        raise NotAllowed("only a CapCut template's own page (capcut.com/template-detail/...) can be read; "
                         "listing pages (/templates/, /explore/...) are not crawled")
    tid = m.group(1)
    return tid, f"https://www.capcut.com/template-detail/{tid}"


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def robots_rules(max_age_s=86400):
    """CapCut's Disallow patterns for agents acting for a user (cached for a day)."""
    PAGES.mkdir(parents=True, exist_ok=True)
    cp = PAGES / "robots.txt"
    if not cp.exists() or time.time() - cp.stat().st_mtime > max_age_s:
        try:
            cp.write_text(_get("https://www.capcut.com/robots.txt"), encoding="utf-8")
        except Exception:  # noqa: BLE001  (no robots file reachable: keep the last known rules, or the strict defaults)
            if not cp.exists():
                return ["/templates/", "*/template-detail/*?*from_page=*", "*/template-detail/*?*from_page_click=*", "*/kep/*", "*/discover/*", "/t/"]
    groups, agents, rules, in_rules = [], [], [], False
    for line in cp.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(v.lower())
        elif k in ("disallow", "allow"):
            in_rules = True
            rules.append((k, v))
    if agents:
        groups.append((agents, rules))
    out = []
    for ags, rs in groups:
        if any(_applies(a) for a in ags):
            out += [v for k, v in rs if k == "disallow" and v]
    return out


def _applies(agent):
    """Does a robots.txt group speak to us? Our own name, '*', and every '<name>-user' group: sites list the agents that
    fetch a page for a person that way, and we obey all of their rules (the strictest that apply)."""
    return agent in (UA_TOKEN, "*") or agent.endswith("-user")


def _matches(pattern, path):
    rx = re.escape(pattern).replace(r"\*", ".*")
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.match(rx, path) is not None


def allowed(url):
    path = re.sub(r"^https?://[^/]+", "", url)
    return not any(_matches(p, path) for p in robots_rules())


def parse_page(page, tid):
    """The template's fields from its public page (the page's own data, then its visible text)."""
    out = {"source": "capcut", "id": tid}
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
    if m:
        out["title"] = _html.unescape(re.sub(r"\s*-\s*CapCut\s*$", "", m.group(1)).strip())
    # the page lists related templates too: THIS template's record is the stretch between its own "templateId" and the
    # next record's (or the previous record's and its own), and must carry the counts
    marks = [(x.start(), x.group(1)) for x in re.finditer(r'"templateId":"?(\d{8,25})', page)]
    best = None
    for k, (pos, idv) in enumerate(marks):
        if idv != tid:
            continue
        after = page[pos:marks[k + 1][0]] if k + 1 < len(marks) else page[pos:pos + 4000]
        before = page[marks[k - 1][0]:pos] if k else page[max(0, pos - 4000):pos]
        for seg in (after, before):
            if '"segmentAmount"' in seg and '"usageAmount"' in seg:
                best = seg
                break
        if best:
            break
    if best:
        def field(name, kind="num"):
            m_ = re.search(r'"' + name + r'":(' + (r'-?[0-9.]+' if kind == "num" else r'"(?:[^"\\]|\\.)*"') + r')', best)
            if not m_:
                return None
            v = m_.group(1)
            return json.loads(v) if kind == "str" else float(v)
        t = field("title", "str")
        if t:
            out["title"] = t
        out["desc"] = field("desc", "str")
        out["clips"] = int(field("segmentAmount") or 0) or None
        d = field("templateDuration")
        out["seconds"] = round(d / 1000.0, 2) if d else None
        out["uses"] = int(field("usageAmount") or 0) or None
        out["likes"] = int(field("likeAmount") or 0) or None
        w, h = field("videoWidth"), field("videoHeight")
        if w and h:
            out["size"] = [int(w), int(h)]
            out["aspect"] = "9:16" if h > w * 1.4 else "16:9" if w > h * 1.4 else "1:1" if abs(w - h) < 0.1 * w else "4:5" if h > w else "4:3"
        a = re.search(r'"author":\{[^{}]*?"name":"((?:[^"\\]|\\.)*)"', best)
        if a:
            out["author"] = json.loads(f'"{a.group(1)}"')
    if not out.get("desc"):
        m = re.search(r'<div class="template-subtitle">(.*?)</div>', page, re.S)
        if m:
            out["desc"] = _html.unescape(m.group(1)).strip()
    if not out.get("seconds"):
        m = re.search(r">(\d{1,2}):(\d{2})<", page)
        if m:
            out["seconds"] = int(m.group(1)) * 60 + int(m.group(2))
    out["tags"] = sorted({t.lower() for t in re.findall(r"#([^\s#]+)", str(out.get("desc") or ""))})
    out["url"] = f"https://www.capcut.com/template-detail/{tid}"
    return out


def from_link(url, max_age_s=86400):
    """One template's fields from its link: cleaned, checked against CapCut's robots rules, fetched once (cached a day)."""
    tid, clean = clean_url(url)
    if not allowed(clean):
        raise NotAllowed(f"CapCut's robots rules do not allow fetching {clean}")
    PAGES.mkdir(parents=True, exist_ok=True)
    cp = PAGES / f"{tid}.html"
    if not cp.exists() or time.time() - cp.stat().st_mtime > max_age_s:
        cp.write_text(_get(clean), encoding="utf-8")
    meta = parse_page(cp.read_text(encoding="utf-8"), tid)
    meta["fetched"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(cp.stat().st_mtime))
    return meta


IMAGE_SYSTEM = """You read a screenshot of a video template's page (CapCut or similar). Reply with ONE JSON object:
{"title": "<the template's title exactly>", "author": "<creator or null>", "clips": <number of clips/photos it needs, or null>,
 "seconds": <length in seconds, or null>, "uses": <number of uses as a plain number, or null>, "aspect": "9:16|16:9|1:1|4:5|null",
 "tags": ["<hashtags without #>"], "shows": "<what the preview frame shows, a few words>"}
Read only what is visible; null when a field is not shown."""


def from_image(path, planner):
    """The template's fields read off a screenshot of its page (one vision call)."""
    from . import frames as F
    from .vlm import ask
    fr = F.image(str(path))
    img = F.jpeg(fr, width=min(1280, fr.shape[1]), quality=88)  # the vision helper takes JPEG bytes
    d, _ = ask(planner, IMAGE_SYSTEM, "A screenshot of a template page.", [img], tier="vision")
    if not isinstance(d, dict):
        raise ValueError("the screenshot could not be read")
    out = {"source": "screenshot", "image": str(path)}
    for k in ("title", "author", "clips", "seconds", "uses", "aspect", "shows"):
        if d.get(k) not in (None, "", "null"):
            out[k] = d[k]
    out["tags"] = sorted({str(t).lstrip("#").lower() for t in d.get("tags") or [] if str(t).strip()})
    for k in ("clips", "uses"):
        try:
            out[k] = int(float(str(out[k]).replace(",", ""))) if out.get(k) is not None else None
        except ValueError:
            out[k] = None
    try:
        out["seconds"] = float(out["seconds"]) if out.get("seconds") is not None else None
    except ValueError:
        out["seconds"] = None
    return out


def from_text(text):
    """The fields from words the client typed ("SLOWMO HDR, 4 clips, 15 s, #slowmo #eid")."""
    t = str(text)
    out = {"source": "text"}
    m = re.search(r"(\d{1,2})\s*(?:clips?|photos?|videos?|slots?|shots?)\b", t, re.I)
    out["clips"] = int(m.group(1)) if m else None
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", t) or re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b", t, re.I)
    out["seconds"] = (int(m.group(1)) * 60 + int(m.group(2))) if m and m.lastindex == 2 else (float(m.group(1)) if m else None)
    m = re.search(r"\b(9:16|16:9|1:1|4:5)\b", t)
    out["aspect"] = m.group(1) if m else None
    out["tags"] = sorted({x.lower() for x in re.findall(r"#([^\s#,]+)", t)})
    title = re.split(r"[,#]|\d+\s*(?:clips?|photos?)", t)[0].strip(" -:")
    out["title"] = title[:60] if title else None
    return out
