"""A conversation that posts to social media. One post is composed once; each platform gets its own version (its kind of
post, its words, its media converted and measured) shown BEFORE anything is published, and nothing goes out without a
yes. Then: links read back from each platform, posts scheduled (by the platform itself where it can, else by this PC),
results gathered, comments read and answered (each answer shown first), posts cancelled or deleted.

  sc = SocialChat.start(files=["eid.mp4"])
  sc.say("post eid.mp4 to instagram, tiktok and youtube tomorrow at 7 pm saying 'Eid sale is live!'")  -> versions + checks
  sc.say("yes")  ->  scheduled: Instagram and TikTok by this PC, YouTube by YouTube itself
  sc.say("what's scheduled?") / sc.say("how did my posts do this week?") / sc.say("any new comments?") / sc.say("reply to 2: thank you!")
"""
import datetime as dt
import json
import re
import time
from pathlib import Path

from ..config import ROOT
from ..util import parse_json
from . import runner as RN
from . import specs
from .base import SocialError
from .prepare import kind_of, prepare
from .socialparse import parse
from .store import Store, iso, now

CHATS = ROOT / "out" / "social" / "chats"
YES = re.compile(r"^\s*(?:yes|yeah|yep|y|ok|okay|sure|go(?: ahead)?|post it|publish(?: it)?|do it|confirm(?:ed)?|send it|schedule it|reply|hide it|"
                 r"delete it|cancel it)\b", re.I)
NO = re.compile(r"^\s*(?:no|nope|n|stop|don'?t|drop it|never mind|forget it|discard)\b", re.I)
SOCIAL_SYSTEM = """You turn a request about social media into actions for a program. Reply with ONE JSON object: {"ops": [...]} or {"ask": "<short question>"}.
Actions:
 {"op": "compose", "platforms": ["instagram","facebook","youtube","tiktok","linkedin","x","threads"], "formats": {"instagram": "reel|photo|carousel|story", "youtube": "short|video", "facebook": "post|photo|video|reel|story"},
  "media": ["file names given"], "text": "the caption, in the person's words", "title": "YouTube title or null", "when": {"day": "YYYY-MM-DD", "time": "HH:MM"} or null,
  "privacy": "public|private|unlisted|null"}
 {"op": "queue"}  {"op": "results", "platforms": [], "days": 7}  {"op": "comments", "platforms": []}  {"op": "reply", "to": "comment number", "text": "..."}
 {"op": "cancel", "platforms": []}  {"op": "delete", "platforms": []}  {"op": "connected"}  {"op": "best_time", "platforms": []}
Use only the person's own words for captions; never invent prices, phone numbers, addresses or claims. Today is {today}."""


def default_format(platform, kinds, media_info):
    """The kind of post each platform gets when the person does not say: video -> Reels / Shorts when vertical and short."""
    vids = [m for m, k in zip(media_info, kinds) if k == "video"]
    imgs = [m for m, k in zip(media_info, kinds) if k == "image"]
    v = vids[0] if vids else None
    vertical = bool(v and v.get("h", 0) > v.get("w", 0))
    short = bool(v and v.get("duration", 0) <= 180)
    if platform == "instagram":
        return "reel" if v else ("carousel" if len(imgs) > 1 else "photo")
    if platform == "facebook":
        return ("reel" if vertical and v.get("duration", 0) <= 90 else "video") if v else ("photo" if imgs else "post")
    if platform == "youtube":
        return "short" if v and vertical and short else "video"
    if platform == "tiktok":
        return "video" if v else "photo"
    if platform == "linkedin":
        return "video" if v else ("image" if imgs else "post")
    if platform == "threads":
        return "video" if v else ("carousel" if len(imgs) > 1 else "image" if imgs else "text")
    return "post"


def _info(path):
    k = kind_of(path)
    if k == "video":
        from ..convert import media as MD
        try:
            p = MD.probe(path)
            v = p.get("video") or {}
            return {"w": v.get("w"), "h": v.get("h"), "duration": p.get("duration")}
        except Exception:  # noqa: BLE001
            return {}
    if k == "image":
        from PIL import Image
        try:
            w, h = Image.open(path).size
            return {"w": w, "h": h}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _when_words(at):
    t = dt.datetime.fromisoformat(at)
    return t.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")


class SocialChat:
    def __init__(self, state, planner=None, platforms=None, store=None, prep=None, budget=600):
        self.state, self.planner = state, planner
        self.folder = Path(state["folder"])
        self.db = store or Store(state.get("db"))
        self._platforms = platforms  # tests: {name: connector}
        self.prep = prep or prepare
        self.budget = budget  # seconds to wait for uploads and processing before leaving the rest to the background runner
        self.last_turn = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, files=None, platforms=None, store=None, db=None, prep=None, budget=600):
        cid = f"social_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        st = {"id": cid, "folder": str(folder), "turns": [], "pending": None, "last_post": None, "db": str(db) if db else None,
              "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in (files or [])}, "comments": []}
        if files:
            st["last_file"] = str(Path(files[-1]).resolve())
        return cls(st, planner, platforms, store, prep, budget)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def platforms(self):
        if self._platforms is not None:
            return self._platforms
        from .platforms import connected
        return connected(self.db)

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "llm": False}
        self._turn = turn
        p = self.state.get("pending")
        try:
            if p and YES.search(message):
                self.state["pending"] = None
                turn["intents"].append("confirm")
                skip = [x for x in specs.NAMES if re.search(r"\bnot (?:on |to )?" + x, message.lower())]
                reply = self.confirm(p, skip)
            elif p and NO.search(message):
                self.state["pending"] = None
                turn["intents"].append("cancel")
                reply = "Dropped; nothing was posted."
            elif p and p["op"] == "compose" and re.search(r"^\s*(?:caption|change the caption|make the caption|title)\b", message, re.I):
                q = re.findall(r"[\"“']([^\"”']+)[\"”']", message)
                key = "title" if re.match(r"^\s*title", message, re.I) else "text"
                if q:
                    p["post"][key] = q[-1]
                reply = self.preview(p)
            else:
                if p:
                    self.state["pending"] = None
                ctx = {"connected": sorted(self.platforms()), "files": self.state["files"], "now": dt.datetime.now(), "last": self.state.get("last_post"),
                       "last_file": self.state.get("last_file")}
                r = parse(message, ctx)
                if not r["ops"] and not r.get("ask"):
                    r = self._llm(message, ctx)
                if r.get("ask") and not r["ops"]:
                    reply = r["ask"]
                else:
                    reply = "\n".join(self.run(op) for op in r["ops"]) or "Tell me what to post and where, e.g. 'post eid.mp4 to instagram and tiktok saying ...'."
        except SocialError as e:
            reply = f"Couldn't: {e}"
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2))
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, message, ctx):
        if self.planner is None:
            return {"ops": [], "ask": "Say what to post and where, e.g. 'post eid.mp4 to instagram reels and youtube shorts tomorrow at 7 pm saying ...'."}
        self._turn["llm"] = True
        sys_ = SOCIAL_SYSTEM.replace("{today}", dt.datetime.now().strftime("%A %d %B %Y, %H:%M"))
        try:
            listed = ""
            if self.state.get("comments"):
                cs = {(c["platform"], c["id"]): c for c in self.db.comments(limit=100)}
                listed = "LISTED COMMENTS (the person refers to them by number):\n" + "\n".join(
                    f"{i}. {specs.LABEL.get(p, p)}, {(cs.get((p, cid)) or {}).get('author', '')}: {(cs.get((p, cid)) or {}).get('text', '')[:120]}"
                    for i, (p, cid, _) in enumerate(self.state["comments"], 1)) + "\n"
            r = self.planner._call("fast", [{"role": "system", "content": sys_},
                                            {"role": "user", "content": f"CONNECTED: {', '.join(ctx['connected']) or 'none'}\nFILES: {', '.join(self.state['files']) or 'none'}\n"
                                                                        f"{listed}REQUEST: {message}"}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op")]
        for o in ops:  # the model names files; only files the chat knows are used
            if o.get("op") == "compose":
                o["media"] = [self.state["files"].get(str(m).lower(), m) for m in o.get("media") or [] if str(m).lower() in self.state["files"] or Path(str(m)).exists()]
                o.setdefault("formats", {})
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    def run(self, op):
        k = op["op"]
        self._turn["intents"].append(k)
        return getattr(self, "op_" + k)(op)

    # ---------------------------------------------------------------- composing and publishing
    def op_compose(self, op):
        plats = self.platforms()
        media = [str(Path(m).resolve()) if Path(m).exists() else m for m in op.get("media") or []]
        when = None
        if op.get("when"):
            t = dt.datetime.fromisoformat(f"{op['when']['day']}T{op['when']['time']}").astimezone()
            if t < now() - dt.timedelta(minutes=1):
                return f"{_when_words(iso(t))} has already passed; give a later time."
            when = iso(t)
        post = {"text": op.get("text") or "", "title": op.get("title"), "media": media, "when": when, "privacy": op.get("privacy"),
                "fill": op.get("fill"), "trim": op.get("trim"), "utm": op.get("utm")}
        kinds = [kind_of(m) for m in media]
        info = [_info(m) for m in media]
        targets, skipped = [], []
        for p in op["platforms"]:
            if p not in plats:
                skipped.append(f"{specs.LABEL.get(p, p)} is not connected (run 'social.py connect {p}')")
                continue
            fmt = (op.get("formats") or {}).get(p) or default_format(p, kinds, info)
            targets.append({"platform": p, "format": fmt})
        if not targets:
            return "Nothing to post to: " + "; ".join(skipped) + "."
        pend = {"op": "compose", "post": post, "targets": targets, "skipped": skipped}
        self.state["pending"] = pend
        return self.preview(pend)

    def preview(self, pend):
        post = pend["post"]
        lines = []
        for t in pend["targets"]:
            job = {"platform": t["platform"], "format": t["format"]}
            prep = self.prep(post, job)
            t["prepared"] = prep
            plat = self.platforms()[t["platform"]]
            label = f"{specs.LABEL.get(t['platform'], t['platform'])} {specs.FORMAT_WORDS.get(t['format'], t['format'])}"
            if prep.get("problems"):
                lines.append(f"- {label}: CANNOT as it is: " + "; ".join(prep["problems"][:3]))
                continue
            bits = []
            if post.get("media"):
                bits.append(", ".join(Path(m).name for m in post["media"]))
            for n in (prep.get("notes") or [])[:3]:
                bits.append(n)
            words = prep.get("parts") and f"a thread of {len(prep['parts'])}" or f"{len(prep.get('text') or '')} characters"
            bits.append(words + (f", title \"{prep['title']}\"" if prep.get("title") else ""))
            native = bool(post.get("when") and plat.native_schedule)
            t["native"] = native
            if post.get("when"):
                bits.append(f"{_when_words(post['when'])} ({'the platform publishes it, this PC may be off' if native else 'this PC publishes it: keep it on'})")
            for w in getattr(plat, "warnings", lambda *a: [])(post, t) or []:
                bits.append("NOTE " + w)
            lines.append(f"- {label}: " + "; ".join(bits))
        ok = [t for t in pend["targets"] if not t["prepared"].get("problems")]
        if not ok:
            self.state["pending"] = None
            return "Nothing can be posted as it is:\n" + "\n".join(lines) + ("\n" + "\n".join(pend["skipped"]) if pend["skipped"] else "")
        head = "Ready to " + ("schedule" if post.get("when") else "post") + (f": \"{post['text'][:120]}\"" if post.get("text") else "") + "\n"
        tail = "\nSay 'yes' to " + ("schedule it" if post.get("when") else "post it") + " (or 'yes but not on tiktok'), 'no' to drop it, or give a new caption."
        return head + "\n".join(lines) + ("\n" + "\n".join(pend["skipped"]) if pend["skipped"] else "") + tail

    def confirm(self, pend, skip=()):
        if pend["op"] != "compose":
            return getattr(self, "do_" + pend["op"])(pend)
        post = dict(pend["post"], status="queued")
        post = self.db.add_post(post)
        made = []
        for t in pend["targets"]:
            if t["platform"] in skip or t["prepared"].get("problems"):
                continue
            made.append(self.db.add_job({"post_id": post["id"], "platform": t["platform"], "format": t["format"], "prepared": t["prepared"],
                                         "native": bool(t.get("native")), "status": "ready"}))
        if not made:
            return "Nothing was left to post."
        self.state["last_post"] = post["id"]
        if post.get("when") and not any(j["native"] for j in made):
            note = self._auto_note()
            return f"Scheduled for {_when_words(post['when'])}: " + ", ".join(specs.LABEL[j["platform"]] for j in made) + ". This PC posts them then." + note
        return self._drive(post["id"])

    def _drive(self, pid):
        """Publish what is due for this post now, waiting for uploads and processing up to the budget, then report."""
        t0 = time.time()
        plats = self.platforms()
        while True:
            RN.run(self.db, plats, self.prep, only=pid)
            js = self.db.jobs(post_id=pid)
            busy = [j for j in js if j["status"] in ("processing", "uploading", "preparing", "ready")]
            if not busy or time.time() - t0 > self.budget:
                break
            nxt = min((j.get("next_try") or iso(now())) for j in busy)
            wait = max(0.0, (dt.datetime.fromisoformat(nxt) - now()).total_seconds())
            time.sleep(min(wait, 15))
        return self._report(pid)

    def _report(self, pid):
        post = self.db.post(pid)
        lines = []
        for j in sorted(self.db.jobs(post_id=pid), key=lambda j: specs.NAMES.index(j["platform"]) if j["platform"] in specs.NAMES else 99):
            label = f"{specs.LABEL.get(j['platform'], j['platform'])} {specs.FORMAT_WORDS.get(j.get('format'), j.get('format') or '')}".strip()
            r = j.get("remote") or {}
            s = j["status"]
            if s == "published":
                lines.append(f"- {label}: published{' (checked)' if r.get('verified') else ''} {r.get('permalink') or r.get('id') or ''}".rstrip()
                             + ("; " + "; ".join(j.get("notes") or []) if j.get("notes") else ""))
            elif s == "scheduled":
                lines.append(f"- {label}: scheduled on {specs.LABEL[j['platform']]} for {_when_words(r.get('publish_at') or post['when'])} (it publishes it, even if this PC is off)")
            elif s in ("processing", "uploading", "ready", "retry"):
                lines.append(f"- {label}: still going ({s}{': ' + j['error'] if j.get('error') else ''}); the background runner finishes it")
            elif s == "needs_signin":
                lines.append(f"- {label}: needs you to connect again ({j.get('error')})")
            elif s == "pending":
                lines.append(f"- {label}: waits for {_when_words(post['when'])}")
            else:
                lines.append(f"- {label}: {s.upper()}: {j.get('error')}")
        open_ = any(j["status"] in ("pending", "processing", "retry", "ready", "uploading") for j in self.db.jobs(post_id=pid))
        return "\n".join(lines) + (self._auto_note() if open_ else "")

    def _auto_note(self):
        if self._platforms is not None:  # tests
            return ""
        try:
            on = RN.task_installed()
        except Exception:  # noqa: BLE001
            on = False
        return "" if on else "\nAutomatic posting is off, so scheduled posts go out only while a chat runs. Say 'turn on automatic posting' (Windows runs the poster every 5 minutes, hidden)."

    # ---------------------------------------------------------------- the queue
    def op_queue(self, op):
        ps = self.db.posts(status=["queued", "scheduled", "publishing", "partial"], limit=30)
        if not ps:
            return "Nothing is scheduled."
        lines = []
        for p in sorted(ps, key=lambda p: p.get("when") or ""):
            js = self.db.jobs(post_id=p["id"])
            lines.append(f"- {_when_words(p['when']) if p.get('when') else 'now'}: \"{(p.get('text') or '')[:60]}\" -> " +
                         ", ".join(f"{specs.LABEL.get(j['platform'], j['platform'])} ({j['status']})" for j in js))
        return "Scheduled and going:\n" + "\n".join(lines)

    def _target_jobs(self, op, states):
        pid = self.state.get("last_post")
        js = self.db.jobs(post_id=pid) if pid else []
        if op.get("platforms"):
            js = [j for j in js if j["platform"] in op["platforms"]]
        return [j for j in js if j["status"] in states]

    def op_cancel(self, op):
        js = self._target_jobs(op, ("pending", "ready", "retry", "scheduled", "needs_signin", "processing"))
        if not js:
            return "Nothing of the last post is waiting to be cancelled."
        native = [j for j in js if j["status"] == "scheduled"]
        self.state["pending"] = {"op": "cancel", "jobs": [j["id"] for j in js]}
        return f"Ready to cancel: " + ", ".join(specs.LABEL[j["platform"]] for j in js) + \
            (" (already uploaded and scheduled there: it is deleted from the platform)" if native else "") + ". Say 'yes' to cancel it."

    def do_cancel(self, pend):
        out = []
        for jid in pend["jobs"]:
            j = self.db.job(jid)
            if j["status"] == "scheduled":
                try:
                    self.platforms()[j["platform"]].delete(j)
                except SocialError as e:
                    out.append(f"{specs.LABEL[j['platform']]}: could not delete the scheduled post ({e})")
                    continue
            self.db.update_job(jid, status="cancelled")
            self.db.log(jid, "cancelled", "by the person")
            out.append(f"{specs.LABEL[j['platform']]}: cancelled")
        RN._post_status(self.db, self.db.job(pend["jobs"][0])["post_id"])
        return "; ".join(out) + "."

    def op_delete(self, op):
        js = self._target_jobs(op, ("published",))
        if not js:
            return "No published post to delete (I can delete the last post this chat published)."
        self.state["pending"] = {"op": "delete", "jobs": [j["id"] for j in js]}
        return "Ready to DELETE from " + ", ".join(f"{specs.LABEL[j['platform']]} ({(j.get('remote') or {}).get('permalink') or ''})" for j in js) + \
            ". This cannot be undone. Say 'yes' to delete."

    def do_delete(self, pend):
        out = []
        for jid in pend["jobs"]:
            j = self.db.job(jid)
            try:
                self.platforms()[j["platform"]].delete(j)
                self.db.update_job(jid, status="deleted")
                self.db.log(jid, "deleted", "by the person")
                out.append(f"{specs.LABEL[j['platform']]}: deleted")
            except SocialError as e:
                out.append(f"{specs.LABEL[j['platform']]}: {e}")
        return "; ".join(out) + "."

    def op_retry(self, op):
        js = [j for j in self.db.jobs(status=["failed", "needs_signin", "retry"]) if not op.get("platforms") or j["platform"] in op["platforms"]]
        if not js:
            return "Nothing failed."
        for j in js:
            self.db.update_job(j["id"], status="ready" if j.get("prepared") else "pending", next_try=None, attempts=0, error=None)
        pids = sorted({j["post_id"] for j in js})
        return "\n".join(self._drive(pid) for pid in pids)

    def op_edit(self, op):
        pid = self.state.get("last_post")
        js = [j for j in self.db.jobs(post_id=pid) if j["status"] in ("pending", "ready", "retry")] if pid else []
        if not js:
            return "Only a post still waiting can be changed (one already scheduled on a platform must be cancelled and posted again)."
        post = self.db.post(pid)
        upd = {}
        if op.get("text"):
            upd["text"] = op["text"]
        if op.get("title"):
            upd["title"] = op["title"]
        if op.get("time"):
            day = op.get("day") or (dt.datetime.fromisoformat(post["when"]).date().isoformat() if post.get("when") else dt.date.today().isoformat())
            upd["when"] = iso(dt.datetime.fromisoformat(f"{day}T{op['time']}").astimezone())
        self.db.update_post(pid, **upd)
        for j in js:
            self.db.update_job(j["id"], prepared=None, status="pending")
        p = self.db.post(pid)
        return "Changed" + (f"; it now goes at {_when_words(p['when'])}" if p.get("when") else "") + ". The versions are prepared again when it goes."

    # ---------------------------------------------------------------- results and comments
    def op_results(self, op):
        days = op.get("days") or 7
        since = iso(now() - dt.timedelta(days=days))
        js = [j for j in self.db.jobs(status=["published"]) if (j.get("published_at") or "") >= since and (not op.get("platforms") or j["platform"] in op["platforms"])]
        if not js:
            return f"No posts published in the last {days} days."
        plats = self.platforms()
        rows = []
        for j in js:
            m = {}
            if j["platform"] in plats:
                try:
                    m = plats[j["platform"]].metrics(j) or {}
                    self.db.snapshot(j["id"], m)
                except SocialError as e:
                    m = {"error": str(e)}
            rows.append((j, m))
        rows.sort(key=lambda r: -(r[1].get("views") or 0))
        lines = []
        tot = {}
        for j, m in rows:
            p = self.db.post(j["post_id"])
            for k in ("views", "likes", "comments", "shares", "saves"):
                tot[k] = tot.get(k, 0) + (m.get(k) or 0)
            lines.append(f"- {specs.LABEL[j['platform']]} {specs.FORMAT_WORDS.get(j.get('format'), '')}, \"{(p.get('text') or '')[:40]}\": " +
                         (", ".join(f"{m[k]} {k}" for k in ("views", "likes", "comments", "shares", "saves") if m.get(k) is not None) or m.get("error", "no numbers yet")))
        head = f"Last {days} days, {len(rows)} posts: " + ", ".join(f"{v} {k}" for k, v in tot.items() if v) + "."
        out = head + "\n" + "\n".join(lines[:15])
        if op.get("report"):
            from .report import excel
            path = excel(rows, self.db, self.folder / f"social_results_{dt.date.today():%Y%m%d}.xlsx")
            out += f"\nReport: {path}"
        return out

    def op_comments(self, op):
        plats = self.platforms()
        since = iso(now() - dt.timedelta(days=30))
        new = 0
        for j in self.db.jobs(status=["published"]):
            if (j.get("published_at") or "") < since or j["platform"] not in plats or (op.get("platforms") and j["platform"] not in op["platforms"]):
                continue
            try:
                for cm in plats[j["platform"]].comments(j) or []:
                    new += self.db.comment(j["platform"], cm["id"], j["id"], cm.get("created") or "", cm.get("author") or "", cm.get("text") or "", cm)
            except SocialError as e:
                self.db.log(j["id"], "comments", str(e))
        cs = self.db.comments(state="new", limit=20)
        self.state["comments"] = [(c["platform"], c["id"], c["job_id"]) for c in cs]
        if not cs:
            return "No new comments."
        return f"New comments ({len(cs)}):\n" + "\n".join(f"{i}. {specs.LABEL[c['platform']]}, {c['author']}: {c['text'][:200]}" for i, c in enumerate(cs, 1)) + \
            "\nSay 'reply to 2: thank you!' or 'hide 3'."

    def _comment(self, ref):
        cs = self.state.get("comments") or []
        if str(ref) == "last" and cs:
            return cs[-1]
        if str(ref).isdigit() and 1 <= int(ref) <= len(cs):
            return cs[int(ref) - 1]
        for c in self.db.comments(limit=100):
            if c["author"].lower().lstrip("@") == str(ref).lower():
                return (c["platform"], c["id"], c["job_id"])
        return None

    def op_reply(self, op):
        c = self._comment(op["to"])
        if not c:
            return "Which comment? Say 'any new comments?' first, then 'reply to 2: ...'."
        self.state["pending"] = {"op": "reply", "c": c, "text": op["text"]}
        return f"Ready to reply on {specs.LABEL[c[0]]} (everyone can see it): \"{op['text']}\". Say 'yes' to send."

    def do_reply(self, pend):
        platform, cid, jid = pend["c"]
        r = self.platforms()[platform].reply(self.db.job(jid), cid, pend["text"])
        self.db.mark_comment(platform, cid, "replied")
        self.db.log(jid, "reply", f"{cid}: {pend['text']}")
        return f"Replied on {specs.LABEL[platform]}" + (" (checked)." if r.get("verified") else ".")

    def op_hide(self, op):
        c = self._comment(op["to"])
        if not c:
            return "Which comment? Say 'any new comments?' first."
        self.state["pending"] = {"op": "hide", "c": c}
        return f"Ready to hide that comment on {specs.LABEL[c[0]]} (only its writer and their friends still see it). Say 'yes'."

    def do_hide(self, pend):
        platform, cid, jid = pend["c"]
        self.platforms()[platform].hide(self.db.job(jid), cid, True)
        self.db.mark_comment(platform, cid, "hidden")
        return f"Hidden on {specs.LABEL[platform]}."

    def op_connected(self, op):
        plats = self.platforms()
        have = []
        for n, p in plats.items():
            try:
                w = p.whoami()
                have.append(f"{specs.LABEL[n]}: {w.get('who')} ({w.get('where')})")
            except SocialError as e:
                have.append(f"{specs.LABEL[n]}: NOT working ({e})")
        missing = [specs.LABEL[n] for n in specs.NAMES if n not in plats]
        return "Connected: " + ("; ".join(have) or "nothing yet") + "." + (f" Not yet: {', '.join(missing)} ('social.py steps <name>')." if missing else "")

    def op_auto(self, op):
        if op["on"]:
            self.state["pending"] = {"op": "auto_on"}
            return ("Ready to turn on automatic posting: Windows Task Scheduler runs this PC's poster every 5 minutes, hidden, while you are signed in, "
                    "so scheduled posts go out on time. Say 'yes' to turn it on.")
        ok = RN.remove_task()
        return "Automatic posting is off." if ok else "Automatic posting was not on."

    def do_auto_on(self, pend):
        try:
            RN.install_task()
        except RuntimeError as e:
            return f"Couldn't: {e}"
        return "Automatic posting is on (every 5 minutes; 'turn off automatic posting' stops it)."

    def op_best_time(self, op):
        from .report import best_times
        r = best_times(self.db, op.get("platforms"))
        return r
