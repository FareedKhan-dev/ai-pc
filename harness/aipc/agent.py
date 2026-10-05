"""The AI PC agent behind the command bar: the one chat (the same one aipc.py, the web page and Telegram talk to), with
requests done one at a time on a worker thread so the bar never freezes, and what each program is doing reported live.

  ag = Agent(events=q.put)           # events(kind, data): ready, queued, start, lane, progress, reply, newchat, error
  ag.send("add a glow effect", context=[r"C:\\Users\\me\\Videos\\clip.mp4"], where="File Explorer")
  ag.send("yes")      ag.send(voice="note.wav")      ag.new_chat()      ag.stop()

Files the person was looking at when they pressed the combo (selected in File Explorer, open in Word) are 'context':
the chat learns them like files sent, so 'it', 'this video' or a program that needs a video finds them, but a request
that is about something else ('turn on dark mode') is not handed them. Several selected files go with a request that
says 'these', 'them', 'all' or names their kind in the plural.
"""
import queue
import re
import threading
import time
import traceback
from pathlib import Path

PLURAL = re.compile(r"\b(?:these|them|those|all|both|each|every|selected|files|photos|pictures|pics|images|videos|clips|songs|recordings|"
                    r"documents|docs|pdfs|sheets|slides)\b", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LABEL = re.compile(r"^\[([^\]\n]{1,60})\]\s*")
VERSION = re.compile(r"^(?:v\d+|agent_\w+)\.\w+$", re.I)  # a program's own name for a version (v3.png, agent_warm_1159.mp4)


def split_reply(text):
    """[(program label or None, text)] for a reply ('[Photos] Brighter ...\\n[Slack, Teams ...] Ready to post ...')."""
    out = []
    for block in re.split(r"\n(?=\[[^\]\n]{1,60}\] )", text or ""):
        m = LABEL.match(block)
        out.append((m.group(1), block[m.end():]) if m else (None, block))
    return out


class Agent:
    def __init__(self, events, chats_dir=None, planner=None, options=None, resume_hours=6.0, warm=True, chat_cls=None):
        self.events, self.chats_dir, self.planner = events, chats_dir, planner
        self.options = dict(options or {})
        self.options["progress"], self.options["on_lane"] = self._progress, self._lane
        self.resume_hours, self.warm = resume_hours, warm
        self.jobs, self.chat, self.busy, self.n = queue.Queue(), None, False, 0
        self.ready = threading.Event()
        self._chat_cls = chat_cls
        self._job, self._last_note = None, 0.0
        self.thread = threading.Thread(target=self._work, daemon=True, name="aipc-agent")
        self.thread.start()

    # ---------------------------------------------------------------- asked from the bar (any thread)
    def send(self, text="", files=(), context=(), voice=None, where=""):
        self.n += 1
        job = {"kind": "say", "id": self.n, "text": (text or "").strip(), "files": [str(f) for f in files], "context": [str(f) for f in context],
               "voice": str(voice) if voice else None, "where": where, "queued": time.time()}
        waiting = self.jobs.qsize() + (1 if self.busy else 0)
        self.jobs.put(job)
        self.events("queued", {"id": job["id"], "text": job["text"], "voice": bool(voice), "files": job["files"], "context": job["context"],
                               "waiting": waiting})
        return job["id"]

    def new_chat(self):
        self.jobs.put({"kind": "new"})

    def stop(self):
        self.jobs.put(None)

    def history(self, limit=30):
        """The conversation so far, for the bar to show: [{user, heard, reply, made}]."""
        c = self.chat
        if c is None:
            return []
        return [{"user": t.get("user", ""), "heard": t.get("heard"), "reply": t.get("reply", ""), "made": [p for p in t.get("made") or [] if Path(p).exists()]}
                for t in c.state.get("turns", [])[-limit:]]

    def nice_name(self, path):
        """The name a made file leaves the chat with: the photo program's v3.png is car_edited.png (as when it is sent to Slack)."""
        name = Path(path).name
        if self.chat is None or not VERSION.match(name):
            return name
        a = next((x for x in self.chat.arts.items if x["path"].lower() == str(path).lower()), None)
        if not a or a["from"] == "you":
            return name
        return f"{Path(a.get('source') or a['from']).stem}_edited{Path(path).suffix}"

    def nice_file(self, path):
        """A copy under that name (made once, in the chat's handoff folder) to copy or show in a folder."""
        try:
            return self.chat._handoff([str(path)])[0] if self.chat is not None else str(path)
        except Exception:  # noqa: BLE001 - the file itself still works
            return str(path)

    def cost(self):
        try:
            return float(self.planner.cost()[1]) if self.planner is not None else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    # ---------------------------------------------------------------- the worker
    def _open(self):
        cls = self._chat_cls
        if cls is None:
            from .chat import AIPCChat as cls
        c = None
        if self.resume_hours:
            c = cls.load(chats_dir=self.chats_dir, planner=self.planner, options=self.options, log=self._log)
            if c is not None and time.time() - (Path(c.folder) / "chat.json").stat().st_mtime > self.resume_hours * 3600:
                c = None  # an old conversation: start afresh (it stays saved)
        return c or cls.start(chats_dir=self.chats_dir, planner=self.planner, options=self.options, log=self._log)

    def _work(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()  # Word, Excel and Explorer are driven from this thread
        except Exception:  # noqa: BLE001
            pass
        try:
            self.chat = self._open()
            self.events("ready", {"chat": self.chat.state["id"], "turns": self.history()})
        except Exception as e:  # noqa: BLE001
            self.events("error", {"text": f"The chat could not start: {type(e).__name__}: {e}", "trace": traceback.format_exc()})
            return
        finally:
            self.ready.set()
        if self.warm:
            try:
                self.chat.apps_claim("warm up", [])  # the 88 programs' rules, loaded before the first request
            except Exception:  # noqa: BLE001
                pass
        while True:
            job = self.jobs.get()
            if job is None:
                break
            if job["kind"] == "new":
                try:
                    from .chat import AIPCChat
                    cls = self._chat_cls or AIPCChat
                    self.chat = cls.start(chats_dir=self.chats_dir, planner=self.planner, options=self.options, log=self._log)
                    self.events("newchat", {"chat": self.chat.state["id"]})
                except Exception as e:  # noqa: BLE001
                    self.events("error", {"text": f"A new chat could not start: {e}"})
                continue
            try:
                self._say(job)
            except Exception as e:  # noqa: BLE001 - one request failing never stops the next
                self.busy, self._job = False, None
                self._log(traceback.format_exc())
                self.events("reply", {"id": job.get("id"), "text": f"Something went wrong: {type(e).__name__}: {e}", "parts": [], "files": [],
                                      "heard": None, "pending": False, "choice": [], "seconds": 0, "usd": 0, "failed": True,
                                      "waiting": self.jobs.qsize()})

    def _say(self, job):
        self.busy, self._job = True, job
        t0, usd0 = time.time(), self.cost()
        self.events("start", {"id": job["id"], "text": job["text"], "voice": bool(job["voice"])})
        chat = self.chat
        files = list(job["files"])
        context = [p for p in job["context"] if Path(p).exists()]
        if context:
            turn = len(chat.state["turns"]) + 1
            where = job.get("where") or "the window in front"
            for p in context:
                chat.arts.add(p, "you", turn, note=f"selected in {where}")
            if len(context) > 1 and PLURAL.search(job["text"] or ""):
                files += [p for p in context if p not in files]
        try:
            r = chat.say(job["text"], files=files, voice=job["voice"])
            text, made, heard, failed = str(r), list(getattr(r, "files", []) or []), getattr(r, "heard", None), False
        except Exception as e:  # noqa: BLE001 - the chat says a program's failure itself; this is anything else
            text, made, heard, failed = f"Something went wrong: {type(e).__name__}: {e}", [], None, True
            self._log(traceback.format_exc())
        st = chat.state
        choice = (st.get("choice") or {}).get("options") or []
        self.busy, self._job = False, None
        self.events("reply", {"id": job["id"], "text": text, "parts": split_reply(text), "files": [p for p in made if Path(p).exists()],
                              "heard": heard, "pending": bool(st.get("pending")), "choice": list(choice), "seconds": round(time.time() - t0, 1),
                              "usd": round(max(0.0, self.cost() - usd0), 5), "failed": failed, "waiting": self.jobs.qsize()})

    # ---------------------------------------------------------------- live notes from the programs
    def _lane(self, label):
        if self._job:
            self.events("lane", {"id": self._job["id"], "label": label})

    def _progress(self, line):
        line = ANSI.sub("", str(line)).strip()
        now = time.monotonic()
        if not line or not self._job or now - self._last_note < 0.15:
            return
        self._last_note = now
        self.events("progress", {"id": self._job["id"], "line": line.splitlines()[-1][:160]})

    def _log(self, *a, **_k):
        if a:
            self._progress(" ".join(str(x) for x in a))
