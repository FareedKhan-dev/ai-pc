"""A conversation with your work apps. Reading (a channel, your inbox, your calendar, your tasks) happens at once; anything
other people will see (a post, an email, an invite, a shared task, a CRM record, a shared file) is shown first and done
only after your yes. Every action is read back from the service, written to the audit log (state/hub/audit.jsonl), and
can be undone where the service allows it.

  hc = HubChat.start()
  hc.say("what's new in #general?")              -> the messages, summed up
  hc.say("post 'Meeting moved to 4 pm' to #general")   -> "Ready to post ... say yes"      hc.say("yes") -> posted, link, checked
  hc.say("draft an email to ali@x.com about the invoice saying it is paid")   -> a draft in Gmail; "send" sends it
  hc.say("brief me")  /  hc.say("undo")  /  hc.say("what did you do today?")
"""
import datetime as dt
import json
import re
import time
from pathlib import Path

from ..config import ROOT
from ..util import parse_json
from . import services as S
from .catalog import SERVICES
from .http import HubError
from .hubparse import parse

AUDIT = ROOT / "state" / "hub" / "audit.jsonl"
CHATS = ROOT / "out" / "hub" / "chats"
YES = re.compile(r"^\s*(?:yes|yeah|yep|y|ok|okay|sure|send(?: it)?|post(?: it)?|go(?: ahead)?|do it|confirm(?:ed)?|approved?|please do|create it|book it|add it)\b[\s.!]*$", re.I)
NO = re.compile(r"^\s*(?:no|nope|n|cancel|stop|don'?t|drop it|never mind|forget it|discard)\b", re.I)
EDIT = re.compile(r"^\s*(?:change|make)\s+(?:the\s+)?(?:text|message|it|body|wording)\s+(?:to|say)\s+(.+)$|^\s*(?:make it say|it should say)\s+(.+)$", re.I)
HUB_SYSTEM = """You turn a request about work apps into actions for a program. Reply with ONE JSON object: {"ops": [...]} or {"ask": "<short question>"}.
Actions (service is one of the connected ones given):
 {"op": "post", "service": "slack|microsoft|telegram|whatsapp", "to": "#channel | @person | me | phone", "text": "...", "team": "Teams team name (microsoft only)"}
 {"op": "read", "service": "slack", "where": "#channel", "hours": 24, "summarize": true}
 {"op": "email", "service": "google|microsoft", "to": ["a@b.com"], "subject": "...", "body": "...", "write": false}
 {"op": "inbox", "service": "google|microsoft", "summarize": true}
 {"op": "events", "service": "google|microsoft|zoom", "day": "YYYY-MM-DD"}
 {"op": "meeting", "service": "google|microsoft|zoom", "title": "...", "start": "YYYY-MM-DDTHH:MM", "minutes": 30, "with": ["a@b.com"]}
 {"op": "task", "service": "trello|asana|notion|jira", "title": "...", "where": "list / project / database", "due": "YYYY-MM-DD", "kind": "Task|Bug"}
 {"op": "tasks", "service": "...", "where": null}  {"op": "move", "service": "trello|jira", "item": "...", "to": "..."}
 {"op": "done", "service": "asana|trello|jira", "item": "..."}  {"op": "comment", "service": "...", "item": "...", "text": "..."}
 {"op": "contact", "service": "hubspot", "email": "...", "first": "...", "last": "...", "phone": "...", "company": "..."}
 {"op": "upload", "service": "google|microsoft|slack|telegram", "path": "...", "to": "#channel or me", "share_with": ["a@b.com"]}
 {"op": "designs", "service": "canva", "query": null}  {"op": "design", "service": "canva", "title": "...", "kind": "instagram post|presentation|..."}
 {"op": "export", "service": "canva", "design": "name", "format": "pdf|png|jpg|gif|mp4|pptx", "to": "desktop|downloads|documents|null"}
 {"op": "import", "service": "canva", "path": "file.pptx"}  {"op": "upload", "service": "canva", "path": "logo.png"}
 {"op": "frames|comments|tokens", "service": "figma", "link": "figma link"}  {"op": "comment", "service": "figma", "link": "...", "text": "..."}
 {"op": "export", "service": "figma", "link": "...", "frame": "name or null for all", "format": "png|svg|pdf|jpg", "to": "desktop|null"}
 {"op": "brief"}  {"op": "undo"}  {"op": "log"}
Use only the person's own words and details; never invent email addresses, phone numbers, amounts or names. Today is {today}."""


def _now():
    return dt.datetime.now()


def audit(entry):
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(entry, time=_now().isoformat(timespec="seconds")), ensure_ascii=False, default=str) + "\n")


class HubChat:
    def __init__(self, state, planner=None, transports=None, creds=None):
        self.state, self.planner = state, planner
        self.transports, self.creds = transports or {}, creds  # tests: fake transports and keys per service
        self.folder = Path(state["folder"])
        self.last_turn = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, files=None, transports=None, creds=None):
        cid = f"hub_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        st = {"id": cid, "folder": str(folder), "turns": [], "pending": None, "done": [], "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in (files or [])}}
        return cls(st, planner, transports, creds)

    def services(self):
        if self.creds is not None:
            return sorted(self.creds)
        return S.connected()

    def conn(self, name):
        if name not in self.services():
            raise HubError(f"{SERVICES.get(name, {}).get('label', name)} is not connected: run 'hub.py steps {name}' then 'hub.py connect {name}'")
        return S.connector(name, creds=(self.creds or {}).get(name) if self.creds is not None else None, transport=self.transports.get(name))

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "llm": False}
        self._turn = turn
        p = self.state["pending"]
        try:
            if p and YES.search(message):
                turn["intents"].append("confirm")
                self.state["pending"] = None
                reply = self.execute(p)
            elif p and NO.search(message):
                turn["intents"].append("cancel")
                self.state["pending"] = None
                reply = "Dropped; nothing was sent." if p["op"] != "send_draft" else "Not sent; the draft stays in your drafts."
            elif p and EDIT.search(message):
                m = EDIT.search(message)
                new = (m.group(1) or m.group(2)).strip().strip("\"“”'")
                key = "body" if p["op"] in ("email", "send_draft") else "text"
                p[key] = new
                if p["op"] == "send_draft":  # a changed email is a new draft
                    p = {"op": "email", "service": p["service"], "to": p["to"], "subject": p["subject"], "body": new}
                    self.state["pending"] = None
                    reply = self.run(p)
                else:
                    reply = self.preview(p)
            else:
                if p:
                    self.state["pending"] = None
                r = parse(message, {"services": self.services(), "files": self.state["files"], "now": _now(), "figma_link": self.state.get("figma_link")})
                if not r["ops"] and not r.get("ask"):
                    r = self._llm(message)
                if r.get("ask") and not r["ops"]:
                    reply = r["ask"]
                else:
                    reply = "\n".join(self.run(op) for op in r["ops"]) or "Tell me what to do, e.g. 'what's new in #general?' or 'brief me'."
                    if p and r["ops"]:
                        reply = "(The earlier draft was dropped.) " + reply
        except HubError as e:
            reply = f"Couldn't: {e}"
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2))
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, message):
        if self.planner is None:
            return {"ops": [], "ask": "I could not read that. Try e.g. 'post \"...\" to #general', 'check my email', 'brief me', "
                                      "'add a trello card \"...\" to To Do'."}
        self._turn["llm"] = True
        sys_ = HUB_SYSTEM.replace("{today}", _now().strftime("%A %d %B %Y, %H:%M"))
        try:
            r = self.planner._call("fast", [{"role": "system", "content": sys_},
                                            {"role": "user", "content": f"CONNECTED: {', '.join(self.services()) or 'none'}\nREQUEST: {message}"}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ops": [], "ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op")]
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- deciding
    @staticmethod
    def outward(op):
        k = op["op"]
        if k == "post":
            return op.get("to") != "me"
        if k == "send_draft":
            return True
        if k == "meeting":
            return bool(op.get("with"))
        if k in ("task", "move", "done", "comment", "contact", "deal"):
            return True
        if op.get("service") in ("canva", "figma"):  # your own Canva and Figma: only a Figma comment is seen by others
            return False
        if k == "upload":
            return bool(op.get("share_with")) or (op.get("service") == "slack")
        return False

    def run(self, op):
        self._turn["intents"].append(op["op"])
        if op["op"] == "email" and (op.get("write") or not op.get("body")):
            op = dict(op, body=self._write_email(op), write=False)
        if self.outward(op):
            self.state["pending"] = op
            return self.preview(op)
        return self.execute(op)

    def preview(self, op):
        k, svc = op["op"], SERVICES.get(op.get("service"), {}).get("label", op.get("service", ""))
        say = {
            "post": lambda: f"Ready to post to {op['to']} on {svc}: \"{op['text']}\"",
            "send_draft": lambda: f"Ready to send the email to {', '.join(op['to'])}: subject \"{op['subject']}\"",
            "meeting": lambda: f"Ready to book \"{op['title']}\" on {svc}, {self._when_words(op)}, inviting {', '.join(op['with'])}",
            "task": lambda: f"Ready to add \"{op['title']}\" to {svc}" + (f" ({op['where']})" if op.get("where") else "") + (f", due {op['due']}" if op.get("due") else ""),
            "move": lambda: f"Ready to move \"{op['item']}\" to {op['to']} on {svc}",
            "done": lambda: f"Ready to mark \"{op['item']}\" done on {svc}",
            "comment": lambda: (f"Ready to comment on the Figma file: \"{op['text']}\"" if op.get("service") == "figma" else
                                f"Ready to comment on \"{op['item']}\" ({svc}): \"{op['text']}\""),
            "contact": lambda: f"Ready to add {' '.join(x for x in (op.get('first'), op.get('last')) if x) or op.get('email')} to HubSpot"
                               + (f" ({op['email']})" if op.get("email") else ""),
            "deal": lambda: f"Ready to add the deal \"{op['name']}\" to HubSpot" + (f" worth {op['amount']}" if op.get("amount") else ""),
            "upload": lambda: f"Ready to {'share' if op.get('share_with') else 'post'} {Path(op['path']).name}"
                              + (f" with {', '.join(op['share_with'])}" if op.get("share_with") else f" to {op.get('to')}") + f" on {svc}",
        }.get(k, lambda: f"Ready to {k} on {svc}")()
        return say + ". Say 'yes' to go ahead, 'no' to drop it, or tell me what to change."

    @staticmethod
    def _when_words(op):
        s = dt.datetime.fromisoformat(op["start"])
        return s.strftime("%a %d %b, %I:%M %p").replace(" 0", " ") + f" for {op.get('minutes', 30)} min"

    def _write_email(self, op):
        if self.planner is None:
            return f"Hello,\n\nI am writing about {op.get('about') or op.get('subject') or 'this'}.\n\nBest regards"
        self._turn["llm"] = True
        r = self.planner._call("fast", [{"role": "user", "content": "Write a short, polite business email body (no subject line, no placeholders like [Name], "
                                                                  f"sign off with 'Best regards'). Topic: {op.get('about') or op.get('subject')}. To: {', '.join(op['to'])}. "
                                                                  "Use only facts in the topic; do not invent dates, amounts or names."}])
        return r.text.strip()

    # ---------------------------------------------------------------- doing
    def execute(self, op):
        k = op["op"]
        svc = op.get("service")
        if k == "undo":
            return self.undo()
        if k == "log":
            return self.log()
        if k == "services":
            return "Connected: " + (", ".join(SERVICES[s]["label"] for s in self.services()) or "nothing yet") + ". Not yet: " + \
                ", ".join(SERVICES[s]["label"] for s in SERVICES if s not in self.services()) + "."
        if k == "brief":
            return self.brief(op.get("send_to"))
        if not svc:
            raise HubError("no connected service can do that yet; see 'hub.py steps'")
        c = self.conn("microsoft" if svc == "teams" else svc)
        res, words = None, ""
        if k == "post":
            if svc == "slack":
                res = c.post(op["to"], op["text"])
            elif svc in ("microsoft", "teams"):
                res = c.post_channel(op.get("team") or "", op["to"], op["text"])
            elif svc == "telegram":
                res = c.send(op["text"], None if op["to"] == "me" else op["to"])
            elif svc == "whatsapp":
                try:
                    res = c.send(op["to"], op["text"])
                except HubError as e:
                    if "131047" in str(e.body) or "re-engagement" in str(e).lower():
                        raise HubError("WhatsApp only allows a template message to people who have not written to you in the last 24 hours "
                                       "(say 'send the hello_world template to ...')")
                    raise
            words = f"Posted to {res['where']}"
        elif k == "read":
            r = c.read(op["where"], hours=op.get("hours", 24))
            msgs = r["messages"]
            if not msgs:
                return f"Nothing new in {r['where']} in the last {op.get('hours', 24)} hours."
            lines = [f"{m['who']}: {m['text']}" for m in msgs[-40:]]
            if op.get("summarize") and self.planner is not None:
                return f"{r['where']}, {len(msgs)} message(s): " + self._summarize("\n".join(lines), f"the {r['where']} channel")
            return f"{r['where']}, last {len(msgs)} message(s):\n" + "\n".join(f"  {x[:200]}" for x in lines[-12:])
        elif k == "email":
            res = c.draft(op["to"], op.get("subject") or "Hello", op.get("body") or "", attachments=op.get("attach") or ())
            self.state["pending"] = {"op": "send_draft", "service": svc, "draft_id": res["id"], "to": op["to"], "subject": op.get("subject"), "body": op.get("body")}
            self._record(op, res)
            return (f"Draft saved in {res['where']} ({'checked' if res['verified'] else 'not checked'}):\nTo: {', '.join(op['to'])}\nSubject: {op.get('subject')}\n\n"
                    f"{op.get('body')}\n\nSay 'send' to send it, 'no' to keep it as a draft, or 'change the text to ...'.")
        elif k == "send_draft":
            res = c.send_draft(op["draft_id"])
            words = f"Sent the email to {', '.join(op['to'])}"
        elif k == "inbox":
            r = c.unread()
            if not r["messages"]:
                return f"No unread mail in {r['where']}."
            lines = [f"{m['from']}: {m['subject']} - {m['snippet'][:120]}" for m in r["messages"]]
            if op.get("summarize") and self.planner is not None:
                return f"{len(lines)} unread in {r['where']}: " + self._summarize("\n".join(lines), "these unread emails")
            return f"{len(lines)} unread in {r['where']}:\n" + "\n".join(f"  {x[:180]}" for x in lines)
        elif k == "events":
            day = dt.date.fromisoformat(op["day"])
            if svc == "zoom":
                ms = [m for m in c.meetings()["meetings"] if (m.get("start") or "").startswith(op["day"])]
                return (f"Zoom on {day:%a %d %b}: " + "; ".join(f"{m['title']} at {m['start'][11:16]} ({m['link']})" for m in ms)) if ms else f"No Zoom meetings on {day:%a %d %b}."
            from .services.google import day_bounds
            s, e = day_bounds(day)
            r = c.events(s, e)
            if not r["events"]:
                return f"Nothing on your calendar on {day:%a %d %b}."
            return f"{day:%a %d %b} ({r['where']}):\n" + "\n".join(f"  {str(ev['start'])[11:16] or 'all day'}  {ev['title']}" + (f"  ({ev['where']})" if ev.get("where") else "")
                                                                for ev in r["events"])
        elif k == "meeting":
            start = dt.datetime.fromisoformat(op["start"])
            end = start + dt.timedelta(minutes=int(op.get("minutes", 30)))
            if svc == "zoom":
                res = c.create(op["title"], start, op.get("minutes", 30))
            else:
                res = c.create_event(op["title"], start, end, attendees=op.get("with") or (), meet=op.get("online", True))
            words = f"Booked \"{op['title']}\" ({self._when_words(op)}) in {res['where']}" + (f", invites sent to {', '.join(op['with'])}" if op.get("with") else "")
        elif k == "task":
            if svc == "trello":
                res = c.create(op["title"], op.get("where"), op.get("board"), due=op.get("due"))
            elif svc == "asana":
                res = c.create(op["title"], op.get("where"), due=op.get("due"))
            elif svc == "notion":
                res = c.add_row(op.get("where") or "Tasks", op["title"], date=op.get("due"))
            elif svc == "jira":
                res = c.create(op["title"], op.get("where"), op.get("kind", "Task"))
            words = f"Added \"{op['title']}\" to {res['where']}"
        elif k == "tasks":
            if svc == "trello":
                cards = c.cards(op.get("where"))
                return "Trello: " + ("; ".join(f"{x['name']} [{x['list']}]" + (f" due {x['due'][:10]}" if x.get("due") else "") for x in cards[:25]) or "no cards") + "."
            if svc == "asana":
                r = c.tasks(op.get("where"))
                return f"Asana, {r['where']}: " + ("; ".join(f"{t['name']}" + (f" due {t['due']}" if t.get("due") else "") for t in r["tasks"][:25]) or "nothing open") + "."
            if svc == "jira":
                r = c.search()
                return "Jira, yours and open: " + ("; ".join(f"{i['key']} {i['summary']} [{i['status']}]" for i in r["issues"]) or "none") + "."
            if svc == "notion":
                r = c.rows(op.get("where") or "Tasks")
                return f"Notion, {r['where']}: " + ("; ".join(x["title"] for x in r["rows"][:25]) or "empty") + "."
        elif k == "move":
            res = c.move(op["item"], op["to"])
            words = f"Moved \"{op['item']}\" ({res['where']})"
        elif k == "done":
            if svc == "asana":
                res = c.complete(op["item"])
            elif svc == "trello":
                res = c.move(op["item"], "Done")
            else:
                res = c.move(op["item"], "Done")
            words = f"Marked \"{op['item']}\" done"
        elif k == "comment" and svc == "figma":
            from .services.figma import key_of
            key, node = key_of(op["link"])
            self.state["figma_link"] = op["link"]
            res = c.comment(key, op["text"], node)
            words = f"Commented on {res['where']}"
        elif k == "comment":
            res = c.comment(op["item"], op["text"])
            words = f"Commented on {res['where']}"
        elif k == "contact":
            res = c.add_contact(op.get("email"), op.get("first"), op.get("last"), op.get("phone"), op.get("company"))
            words = f"Added {res['name']} to HubSpot"
        elif k == "deal":
            res = c.add_deal(op["name"], op.get("amount"))
            words = f"Added the deal \"{op['name']}\" to HubSpot"
        elif svc == "figma" and k in ("frames", "export", "comments", "tokens"):
            return self._figma(c, op)
        elif svc == "canva" and k in ("designs", "design", "export", "import"):
            return self._canva(c, op)
        elif k == "upload" and svc == "canva":
            p = Path(op["path"])
            if not p.exists():
                raise HubError(f"no file {p.name} (give the full path, or start the chat with --with {p.name})")
            res = c.upload(p)
            words = f"Uploaded {p.name} to {res['where']}"
        elif k == "upload":
            p = Path(op["path"])
            if not p.exists():
                raise HubError(f"no file {p.name} (give the full path, or start the chat with --with {p.name})")
            if svc == "slack":
                res = c.upload(op.get("to") or "#general", p)
            elif svc == "telegram":
                res = c.send_file(p)
            else:
                res = c.upload(p)
                if op.get("share_with"):
                    for em in op["share_with"]:
                        (c.share(res["id"], em) if svc == "google" else c.share_link(res["id"]))
            words = f"Uploaded {p.name} to {res['where']}" + (f" and shared it with {', '.join(op['share_with'])}" if op.get("share_with") else "")
        else:
            raise HubError(f"I can't {k} yet")
        self._record(op, res)
        link = f" {res['link']}" if res.get("link") else ""
        check = "checked" if res.get("verified") else "NOT confirmed by the service: look before relying on it"
        return f"{words} ({check}).{link}" + ("" if res.get("undo") else " (The service cannot take this back.)")

    @staticmethod
    def _dest(where):
        if not where:
            return None
        from ..windows import fs as WF
        return WF.known({"download": "downloads", "downloads": "downloads", "document": "documents", "documents": "documents", "photos": "pictures",
                         "pictures": "pictures", "videos": "videos", "desktop": "desktop"}.get(where, where))

    def _figma(self, c, op):
        from .services.figma import key_of
        key, node = key_of(op["link"])
        self.state["figma_link"] = op["link"]
        k = op["op"]
        if k == "frames":
            fr = c.frames(key)
            data = c.file(key)
            return f"Figma, {data.get('name') or key}: {len(fr)} frame(s): " + "; ".join(f"{f['name']} ({f['w']}x{f['h']}, {f['page']})" for f in fr[:25]) + "."
        if k == "comments":
            cs = c.comments(key)
            open_ = [x for x in cs if not x["resolved"]]
            return f"Figma comments: {len(open_)} open of {len(cs)}" + (": " + "; ".join(f"{x['who']}: {x['text'][:120]}" for x in open_[:12]) if open_ else "") + "."
        if k == "tokens":
            t = c.tokens(key)
            cols = ", ".join(f"{x['hex']}" + (f" ({x['name']})" if x.get("name") else "") for x in t["colors"][:10])
            txt = ", ".join(f"{x['family']} {x['weight']} {x['size']}px" for x in t["text"][:8])
            return f"Colours (most used first): {cols or 'none'}. Text styles: {txt or 'none'}."
        # export: the frames named, or all of them, in one request
        fr = c.frames(key)
        if op.get("frame"):  # a frame named in the request wins over the one the link points at
            ids = [c.find_frame(key, op["frame"])["id"]]
        elif node:
            ids = [node]
        else:
            ids = [f["id"] for f in fr]
        names = {f["id"]: f["name"] for f in fr}
        dest = self._dest(op.get("to"))
        got = c.export(key, ids, op.get("format") or "png", folder=dest, names=names)
        ok = [g for g in got if g.get("path")]
        where = str(Path(ok[0]["path"]).parent) if ok else "nowhere"
        return f"Exported {len(ok)} of {len(ids)} frame(s) as {(op.get('format') or 'png').upper()} to {where}" + \
            (f": {', '.join(Path(g['path']).name for g in ok[:8])}" if ok else "") + "."

    def _canva(self, c, op):
        k = op["op"]
        if k == "designs":
            ds = c.designs(op.get("query"), 25)
            return (f"Canva designs" + (f" matching '{op['query']}'" if op.get("query") else "") + f": {len(ds)}: " +
                    "; ".join(f"{d['name']}" + (f" ({d['pages']} pages)" if (d.get("pages") or 0) > 1 else "") for d in ds) + ".") if ds else "No Canva designs found."
        if k == "design":
            res = c.create(op.get("title") or "Untitled design", op.get("kind"))
            self._record(op, res)
            return f"Made the Canva design \"{res['name']}\" ({'checked' if res.get('verified') else 'NOT confirmed by Canva'}). Open it: {res.get('link')}"
        if k == "import":
            p = Path(op["path"])
            if not p.exists():
                raise HubError(f"no file {p.name} (give the full path, or start the chat with --with {p.name})")
            res = c.import_file(p)
            self._record(op, res)
            return f"Imported {p.name} into Canva as \"{res['name']}\" ({'checked' if res.get('verified') else 'NOT confirmed by Canva'}). Open it: {res.get('link')}"
        res = c.export(op["design"], op.get("format") or "pdf", folder=self._dest(op.get("to")))
        return f"Saved \"{res['design']}\" as {res['format'].upper()}: " + ", ".join(res["files"][:6]) + (f" (+{len(res['files']) - 6} more)" if len(res["files"]) > 6 else "") + "."

    def _record(self, op, res):
        entry = {"service": op.get("service"), "op": op["op"], "where": res.get("where"), "id": res.get("id"), "link": res.get("link"),
                 "verified": res.get("verified"), "summary": (op.get("text") or op.get("title") or op.get("subject") or op.get("name")
                                                          or (Path(op["path"]).name if op.get("path") else ""))[:120],
                 "undo": res.get("undo")}
        self.state["done"].append(entry)
        if not self.transports:
            audit(entry)

    def _summarize(self, text, what):
        self._turn["llm"] = True
        r = self.planner._call("fast", [{"role": "user", "content": f"Sum up {what} for a busy person in 3-6 short bullet points: who needs what, decisions, "
                                                                  f"deadlines. Use only what is written; quote numbers exactly.\n\n{text[:6000]}"}])
        return "\n" + r.text.strip()

    # ---------------------------------------------------------------- history
    def undo(self):
        done = [d for d in self.state["done"] if not d.get("undone")]
        if not done:
            return "Nothing to undo in this chat."
        d = done[-1]
        u = d.get("undo")
        if not u:
            return f"The last action ({d['op']} on {d['service']}) cannot be taken back by the service" + (", so send a correction instead." if d["op"] in ("send_draft", "post") else ".")
        c = self.conn(u["service"])
        args = {k: v for k, v in u.items() if k not in ("service", "op")}
        getattr(c, u["op"])(**args)
        d["undone"] = True
        if not self.transports:
            audit({"service": u["service"], "op": f"undo {d['op']}", "where": d.get("where"), "id": d.get("id"), "summary": d.get("summary", "")})
        return f"Undone: {d['op']} \"{d['summary']}\" ({d.get('where')})."

    def log(self):
        today = _now().date().isoformat()
        rows = []
        if AUDIT.exists() and not self.transports:
            for ln in AUDIT.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                if e.get("time", "").startswith(today):
                    rows.append(e)
        rows = rows or [dict(d, time="") for d in self.state["done"]]
        if not rows:
            return "Nothing done today."
        return "Today:\n" + "\n".join(f"  {e.get('time', '')[11:16]} {e['service']}: {e['op']} \"{e.get('summary', '')}\" -> {e.get('where')}" for e in rows[-20:])

    # ---------------------------------------------------------------- the briefing
    def brief(self, send_to=None):
        have = self.services()
        parts, raw = [], []
        today = _now().date()
        for name in [s for s in ("google", "microsoft") if s in have]:
            try:
                c = self.conn(name)
                from .services.google import day_bounds
                s, e = day_bounds(today)
                ev = c.events(s, e)["events"]
                parts.append(f"Calendar ({SERVICES[name]['label'].split(' (')[0]}): " + ("; ".join(f"{str(x['start'])[11:16]} {x['title']}" for x in ev) or "nothing today"))
                mail = c.unread(8)["messages"]
                parts.append(f"Unread mail: {len(mail)}" + (" - " + "; ".join(f"{m['from'].split('<')[0].strip()}: {m['subject']}" for m in mail[:5]) if mail else ""))
                raw += [f"EMAIL {m['from']}: {m['subject']} - {m['snippet'][:150]}" for m in mail]
            except HubError as e:
                parts.append(f"{SERVICES[name]['label']}: could not read ({e})")
        if "slack" in have:
            try:
                c = self.conn("slack")
                mine = [ch for ch in c.channels() if ch["member"]][:6]
                counts = []
                for ch in mine:
                    r = c.read(ch["id"], hours=24, limit=60)
                    if r["messages"]:
                        counts.append(f"#{ch['name']} {len(r['messages'])}")
                        raw += [f"SLACK #{ch['name']} {m['who']}: {m['text'][:200]}" for m in r["messages"][-15:]]
                parts.append("Slack (last 24 h): " + (", ".join(counts) or "quiet"))
            except HubError as e:
                parts.append(f"Slack: could not read ({e})")
        for name in [s for s in ("trello", "asana", "jira") if s in have]:
            try:
                c = self.conn(name)
                if name == "trello":
                    due = [x for x in c.cards() if x.get("due") and x["due"][:10] <= today.isoformat() and not x.get("done")]
                    parts.append("Trello due or late: " + ("; ".join(f"{x['name']} ({x['due'][:10]})" for x in due[:8]) or "none"))
                elif name == "asana":
                    ts = [t for t in c.tasks()["tasks"] if t.get("due") and t["due"] <= today.isoformat()]
                    parts.append("Asana due or late: " + ("; ".join(f"{t['name']} ({t['due']})" for t in ts[:8]) or "none"))
                else:
                    iss = c.search()["issues"]
                    parts.append(f"Jira, open and yours: {len(iss)}" + (" - " + "; ".join(f"{i['key']} {i['summary']}" for i in iss[:5]) if iss else ""))
            except HubError as e:
                parts.append(f"{SERVICES[name]['label']}: could not read ({e})")
        if not parts:
            return "Nothing is connected yet: run 'hub.py steps' to see how, then 'hub.py connect slack' (or another)."
        text = f"Briefing for {today:%A %d %B}:\n" + "\n".join(f"- {p}" for p in parts)
        if raw and self.planner is not None:
            text += "\nWhat needs you:" + self._summarize("\n".join(raw), "today's messages and emails")
        if send_to == "telegram" and "telegram" in have:
            res = self.conn("telegram").send(text[:4000])
            self._record({"op": "post", "service": "telegram", "text": "the briefing"}, res)
            text += "\n(Sent to your Telegram.)"
        return text
