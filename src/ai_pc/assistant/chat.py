"""The one AI PC chat: everything this PC can do, from one conversation, typed or as a voice note.

Each message goes to the program it is for (video editing, Office, photos, sound, design, CAD, 3D, converter, Windows,
coding, accounts, work apps like Slack and Gmail, social media, and 88 more programs by name). The chat remembers every
file sent and made, so 'it', 'this video', 'the pdf' or 'the original' are real files handed from one program to the
next; a request in several steps ("add a glow to my video, then send it to Slack #team") runs step by step. Each
program keeps its own rules: checks, 'yes' before anything others will see, versions and undo ('undo' goes to the
program in use).

  c = AIPCChat.start()
  c.say("add a glow effect to my video", files=["me.mp4"])      -> the edited video (made by the video agent)
  c.say("send it to slack #team")                                 -> "Ready to post <edited>.mp4 to #team on Slack. Say 'yes' ..."
  c.say("yes")                                                    -> posted, checked
  c.say(voice="note.ogg")                                         -> what it heard, then the same as typing it
"""

import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path

from ai_pc.assistant import router
from ai_pc.assistant.artifacts import KINDS, Artifacts
from ai_pc.assistant.lanes import LANE_CLASSES, dedupe, files_said
from ai_pc.core.config import ROOT

CHATS = ROOT / "out" / "aipc" / "chats"
YES = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|y|ok|okay|sure|go ahead|do it|send(?: it)?|post(?: it)?|confirm(?:ed)?|approved?|please do|haan|ji)\b[\s.!]*$", re.I
)
NO = re.compile(r"^\s*(?:no|nope|n|cancel|stop|don'?t|drop it|never ?mind|forget it|leave it)\b", re.I)
HELP = re.compile(r"^\s*(?:help|menu|commands|what can you do|what all can you do|what do you do|what can i ask)\b|\bwhat can you do\b", re.I)
MADE_Q = re.compile(r"\bwhat (?:have you|did you) (?:make|made|do|done)\b|\b(?:list|show)(?: me)? (?:the |my |all )?files\b|\bwhat files\b", re.I)
GREET = re.compile(r"^\s*(?:hi|hello|hey|salam|assalam[ou] ?alaikum|aoa|good (?:morning|afternoon|evening))\b[\s!.,]*(?:there)?[\s!.]*$", re.I)
THANKS = re.compile(r"^\s*(?:thanks?|thank you|shukriya|great|nice|perfect|good job|well done|awesome)\b[\s!.]*(?:a lot|so much)?[\s!.]*$", re.I)
QUESTION = re.compile(r"\?\s*$|^\s*(?:what|how|why|who|when|where|which|is|are|can|could|should|explain|tell me)\b", re.I)
PICK = re.compile(r"^\s*(?:(?:number|no\.?|#)\s*)?(\d{1,2})\b|^\s*(?:the\s+)?(first|second|third|fourth|fifth|last)\b", re.I)
ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
NAME_LANES = {"hub", "social", "apps"}  # programs whose rules look files up by name in the message
DELIVER = {"hub", "social", "apps"}  # programs that send, post or pack what others made: edit follow-ups stay with the maker
REF = re.compile(
    r"\b(?:the (?:edited |new |final |latest |same |original |last )?(?:video|clip|reel|photo|picture|pic|image|file|pdf|document|doc|"
    r"report|sheet|spreadsheet|deck|presentation|slides|audio|song|recording|plan|drawing|model|result|output|one|invoice|card|post|"
    r"thumbnail|design|archive|zip)s?|it|this|that|them)\b",
    re.I,
)
PLACES = ["Desktop", "Downloads", "Videos", "Pictures", "Music", "Documents"]


def spoken_channels(text):
    """A channel said aloud ('Slack, general channel', 'the sales channel', 'channel general') written as #general."""
    if "#" in text:
        return text
    t = re.sub(r"\b(?:the\s+)?([A-Za-z][\w-]*)\s+channel\b", lambda m: "#" + m.group(1).lower(), text, count=1, flags=re.I)
    if t == text:
        t = re.sub(r"\bchannel\s+(?:called\s+|named\s+)?([A-Za-z][\w-]*)\b", lambda m: "#" + m.group(1).lower(), text, count=1, flags=re.I)
    return t


class Reply(str):
    """The reply text, with .files (made this turn) and .heard (what a voice note said)."""

    files: list
    heard: str


def _reply(text, files=(), heard=None):
    r = Reply(text)
    r.files, r.heard = list(files), heard
    return r


class AIPCChat:
    def __init__(self, state, planner=None, options=None, log=print):
        self.state, self.planner, self.options, self.log = state, planner, options or {}, log
        self.folder = Path(state["folder"])
        self.arts = Artifacts(state.setdefault("artifacts", []))
        self.lanes = {c.key: c(self) for c in LANE_CLASSES}
        self.sessions = {}
        self._mods = None

    @classmethod
    def start(cls, chats_dir=None, planner=None, options=None, log=print):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        cid, n = f"aipc_{stamp}", 2
        while (Path(chats_dir or CHATS) / cid).exists():  # two chats in the same second (New chat, New chat) stay two
            cid, n = f"aipc_{stamp}_{n}", n + 1
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        st = {
            "id": cid,
            "folder": str(folder),
            "turns": [],
            "artifacts": [],
            "active": None,
            "pending": None,
            "queue": [],
            "choice": None,
            "sessions": {},
        }
        c = cls(st, planner, options, log)
        c.save()
        return c

    @classmethod
    def load(cls, cid=None, chats_dir=None, planner=None, options=None, log=print):
        root = Path(chats_dir or CHATS)
        if cid is None:
            found = sorted(root.glob("aipc_*/chat.json"), key=lambda p: p.stat().st_mtime)
            if not found:
                return None
            f = found[-1]
        else:
            f = root / cid / "chat.json"
        st = json.loads(f.read_text(encoding="utf-8"))
        return cls(st, planner, options, log)

    def save(self):
        from ai_pc.apps.appschat import redact

        (self.folder / "chat.json").write_text(json.dumps(redact(self.state), ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # ---------------------------------------------------------------- helpers
    def catalogue(self):
        return "\n".join(f"{l.key}: {l.label}: {l.blurb}" for l in self.lanes.values())

    def apps_claim(self, message, files):
        """The program module that would take this message by its own rules (as the programs chat routes)."""
        if self._mods is None:
            from ai_pc.apps import all_modules

            self._mods = all_modules()
        known = {} if files else {Path(a["path"]).name.lower(): a["path"] for a in self.arts.alive()}  # 'it' -> just that file
        known.update({Path(f).name.lower(): str(f) for f in files})
        s = self.sessions.get("apps")
        ctx = {"files": known, "out": self.folder / "probe", "now": dt.datetime.now(), "memo": (s.state.get("memo") if s else None) or {}}
        for m in self._mods:
            try:
                if m.parse(message, ctx):
                    return m.NAME
            except Exception:  # noqa: BLE001 - a module's rules failing on odd words is not a claim
                continue
        return None

    def session(self, key):
        s = self.sessions.get(key)
        if s is None and key in self.state["sessions"]:
            s = self.lanes[key].reopen(self.state["sessions"][key]) if hasattr(self.lanes[key], "reopen") else None
            if s is not None:
                self.sessions[key] = s
        return s

    def find_on_pc(self, kinds, text):
        """The person's newest files of these kinds in their usual folders, best name match first (for 'my video' with no file sent)."""
        exts = set().union(*(KINDS[k] for k in kinds if k in KINDS))
        words = {w for w in re.findall(r"[a-z0-9]{3,}", text.lower())} - {
            "the",
            "and",
            "add",
            "make",
            "with",
            "video",
            "photo",
            "picture",
            "my",
            "this",
            "that",
            "for",
            "effect",
            "please",
            "can",
            "you",
            "image",
            "song",
            "audio",
        }
        found = []
        home = Path(self.options.get("home") or Path.home())  # tests give a made-up home
        for place in PLACES:
            d = home / place
            if not d.is_dir():
                continue
            for p in list(d.iterdir())[:2000]:
                if p.is_file() and p.suffix.lower() in exts:
                    found.append(p)
        found.sort(key=lambda p: (-sum(w in p.stem.lower() for w in words), -p.stat().st_mtime))
        return [str(p) for p in found[:5]]

    def help_text(self):
        lines = ["I can do all of this from this one chat (type, or send a voice note; send files with your message):"]
        for l in self.lanes.values():
            lines.append(f"- {l.label}: {l.blurb.split(';')[0]}. e.g. '{l.examples[0]}'")
        lines.append(
            "Say 'undo' to go back a step in what we were doing; 'what have you made?' lists the files; anything others will see waits for your 'yes'."
        )
        return "\n".join(lines)

    # ---------------------------------------------------------------- a message
    def say(self, message="", files=(), voice=None):
        t0 = time.perf_counter()
        turn_no = len(self.state["turns"]) + 1
        heard = None
        if voice:
            from ai_pc.assistant.voice import transcribe

            heard = transcribe(voice)
            message = f"{message} {heard}".strip() if heard else message
            if not heard and not message:
                return self._done(turn_no, t0, "", "I could not hear any words in that voice note. Try again, a little louder or closer.", [], None)
        sent = []
        for f in files:
            a = self.arts.add(f, "you", turn_no, note="sent")
            sent.append(a["path"])
        message = (message or "").strip()
        if not message:
            if sent:
                return self._done(turn_no, t0, "", f"Got {', '.join(Path(p).name for p in sent)}. What should I do with it?", [], heard)
            return self._done(turn_no, t0, "", "Say what to do (or 'what can you do?').", [], heard)
        try:
            reply, made = self._handle(message, sent, turn_no)
        except Exception as e:  # noqa: BLE001 - a program's failure is said, not raised
            if type(e).__name__ == "PlannerError":
                reply = (
                    "The AI model is not answering right now (the provider is slow or down), and this request needs it. "
                    "Nothing was changed; try again in a few minutes."
                )
            else:
                reply = f"Couldn't: {type(e).__name__}: {e}"
            made = []
        return self._done(turn_no, t0, message, reply, made, heard)

    def _done(self, turn_no, t0, message, reply, made, heard):
        self.state["turns"].append(
            {
                "n": turn_no,
                "user": message,
                "heard": heard,
                "reply": reply,
                "made": made,
                "lane": self.state.get("active"),
                "seconds": round(time.perf_counter() - t0, 2),
            }
        )
        self.save()
        return _reply(reply, made, heard)

    def _handle(self, message, sent, turn_no):
        # a program waiting for a yes or a no gets it
        p = self.state.get("pending")
        if p and (YES.search(message) or NO.search(message)):
            out, made = self._step(p, message, [], turn_no, as_is=True)
            if NO.search(message):
                self.state["queue"] = []
            parts, made_all = [out], list(made)
            while self.state["queue"] and not self.state.get("pending"):
                nxt = self.state["queue"].pop(0)
                o, m = self._route_and_run(nxt, [], turn_no)
                parts.append(o)
                made_all += m
            return "\n".join(parts), made_all
        # an answer to 'which file?'
        ch = self.state.get("choice")
        if ch:
            m = PICK.search(message)
            n = None
            if m:
                n = int(m.group(1)) if m.group(1) else (len(ch["options"]) if m.group(2).lower() == "last" else ORDINAL[m.group(2).lower()])
            elif YES.search(message) and len(ch["options"]) == 1:
                n = 1
            self.state["choice"] = None
            if n and 1 <= n <= len(ch["options"]):
                f = ch["options"][n - 1]
                self.arts.add(f, "you", turn_no, note="chosen")
                return self._step(ch["lane"], ch["text"], [f], turn_no)
        if HELP.search(message):
            return self.help_text(), []
        if GREET.search(message):
            return (
                "Hi! Send a file, a voice note, or tell me what to do: e.g. 'add a glow effect to my video', 'make my photo brighter', "
                "'send it to slack #team', 'write a 2 page report on ...'. Say 'what can you do?' for everything.",
                [],
            )
        if THANKS.search(message):
            return "Glad to help. Anything else?", []
        if MADE_Q.search(message):
            items = self.arts.describe(20)
            return ("Files in this chat (newest last):\n" + "\n".join(items)) if items else "Nothing yet: send a file or ask for something.", []
        steps = router.split(message)
        parts, made_all = [], []
        for i, text in enumerate(steps):
            o, m = self._route_and_run(text, sent if i == 0 else [], turn_no)
            parts.append(o)
            made_all += m
            if self.state.get("pending") or self.state.get("choice"):
                self.state["queue"] = steps[i + 1 :]
                break
        return "\n".join(parts), made_all

    def _route_and_run(self, text, files, turn_no):
        refs = [a["path"] for a in self.arts.resolve(text)] if not files else []
        lane, why, ask = router.pick(
            text,
            files,
            self.state.get("active"),
            self.apps_claim,
            self.planner,
            self.catalogue(),
            "; ".join(self.arts.describe()),
            refs=refs,
            editing=self.state.get("editing"),
            known={a["kind"] for a in self.arts.alive()},
        )
        if not lane or lane not in self.lanes:
            if self.planner is not None and QUESTION.search(text):
                return self._answer(text), []
            return ask or "I am not sure which program that is for. Say 'what can you do?' for the list.", []
        return self._step(lane, text, files, turn_no)

    def _answer(self, text):
        """A question no program is for: a short answer from the model (it sees the question only, never files or keys)."""
        try:
            r = self.planner._call(
                "fast",
                [
                    {
                        "role": "system",
                        "content": "Answer in 1-4 short sentences, plainly. If it is something this PC's programs could do, say so in one line.",
                    },
                    {"role": "user", "content": text},
                ],
            )
            return r.text.strip() or "I don't know."
        except Exception:  # noqa: BLE001
            return "The AI model is not answering right now; try again in a few minutes."

    def _step(self, key, text, files, turn_no, as_is=False):
        lane = self.lanes[key]
        if self.options.get("on_lane"):
            self.options["on_lane"](lane.label)  # a front end showing live which program is at work
        s = self.session(key)
        subject = list(files)
        if not as_is and not subject:
            hits = self.arts.resolve(text, want=lane.works_on if lane.needs_file and s is None else None)
            subject = [a["path"] for a in hits if a["from"] != key]  # a program's own results go on in its own conversation
        if key in NAME_LANES and subject:
            subject = self._handoff(subject)
        if not as_is and lane.needs_file and s is None and not lane.subject(subject):
            kinds = list(lane.works_on)
            options = self.find_on_pc(kinds, text)
            if options:
                self.state["choice"] = {"lane": key, "text": text, "options": options}
                return "Which one? " + "  ".join(f"{i}) {o}" for i, o in enumerate(options, 1)) + "  (or send the file)", []
            return f"Send the {kinds[0]} (or tell me its name) and I'll do it.", []
        if s is None or (subject and lane.fresh(s, subject)):
            s = lane.open(subject)
            if s is None:
                return f"Send the {lane.works_on[0] if lane.works_on else 'file'} first.", []
            self.sessions[key] = s
            self.state.setdefault("subjects", {})[key] = Path(lane.subject(subject)[0]).name if lane.subject(subject) else None
        elif subject:
            lane.add(s, subject)
        msg = text if as_is else self._name_files(text, subject, key)
        if key == "hub" and not as_is:
            msg = spoken_channels(msg)
        before = {p: Path(p).stat().st_mtime for p in lane.results(s) if Path(p).exists()}
        reply = lane.say(s, msg, subject)
        made, yours = [], {a["path"].lower() for a in self.arts.items if a["from"] == "you"}
        for p in dedupe(lane.results(s) + files_said(reply)):
            if p.lower() in yours or not Path(p).exists():
                continue  # a reply naming the person's own file has not made it
            if p not in before or Path(p).stat().st_mtime > before[p]:
                made.append(p)
                a = self.arts.add(p, key, turn_no, note=text[:80])
                a["source"] = (self.state.get("subjects") or {}).get(key)
        self.state["active"] = key
        if key not in DELIVER:
            self.state["editing"] = key
        self.state["pending"] = key if lane.pending(s) else None
        sid = (getattr(s, "state", None) or {}).get("id") if isinstance(getattr(s, "state", None), dict) else None
        self.state["sessions"][key] = {"id": sid, **({"draft": s.draft, "export": s.export} if key == "video" else {})}
        return f"[{lane.label}] {reply}", made

    def _handoff(self, paths):
        """Files going to other people get a clear name: a program's internal version file (v3.png) goes as a copy named
        after what it was made from (car_edited.png)."""
        out = []
        for p in paths:
            a = next((x for x in self.arts.items if x["path"].lower() == str(p).lower()), None)
            if a and a["from"] != "you" and re.match(r"^(?:v\d+|agent_\w+)\.\w+$", Path(p).name, re.I):  # version files, video drafts
                stem = Path(a.get("source") or a["from"]).stem
                dst = self.folder / "handoff" / f"{stem}_edited{Path(p).suffix}"
                n = 2
                while dst.exists() and dst.stat().st_size != Path(p).stat().st_size:
                    dst = self.folder / "handoff" / f"{stem}_edited_{n}{Path(p).suffix}"
                    n += 1
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(p, dst)
                out.append(str(dst))
            else:
                out.append(p)
        return out

    @staticmethod
    def _name_files(text, paths, key):
        """For programs that look files up by name: 'send it to slack' -> 'send <edited>.mp4 to slack'."""
        if key not in NAME_LANES or not paths:
            return text
        names = [Path(p).name for p in paths]
        if any(n.lower() in text.lower() for n in names):
            return text
        joined = " and ".join(names)
        new, n = REF.subn(joined, text, count=1)
        if n:
            return new
        m = re.match(r"^\s*(\w+)\b(.*)$", text)
        return f"{m.group(1)} {joined}{m.group(2)}" if m else f"{text} {joined}"
