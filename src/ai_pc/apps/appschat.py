"""One conversation for the many small programs (src/ai_pc/apps): each request goes to the first module whose rules read
it; ops that change the PC or reach outside it are shown first and done after a yes; files named in a request are
found among the ones given (--with) or by path.

  c = AppsChat.start(files=["receipt.jpg"]); c.say("read the text in receipt.jpg")
"""
import datetime as dt
import json
import re
import time
from pathlib import Path

from ai_pc.apps import all_modules
from ai_pc.core.config import ROOT

CHATS = ROOT / "out" / "apps" / "chats"
YES = re.compile(r"^\s*(?:yes|yeah|yep|y|ok|okay|sure|go|go ahead|do it|confirm|install it|print it)\b(?:[\s,]+(?:it|please|now|ahead|thanks))*[\s.!]*$", re.I)
NO = re.compile(r"^\s*(?:no|nope|n|stop|cancel|don'?t|never mind|forget it)\b", re.I)


class AppsChat:
    def __init__(self, state, modules=None):
        self.state = state
        self.folder = Path(state["folder"])
        self.modules = modules or all_modules()

    @classmethod
    def start(cls, files=(), chats_dir=None, modules=None, extra=None):
        cid = f"apps_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        st = {"id": cid, "folder": str(folder), "turns": [], "pending": None, "files": {Path(f).name.lower(): str(Path(f).resolve()) for f in files},
              "extra": dict(extra or {})}
        return cls(st, modules)

    def ctx(self):
        # memo: what a program remembers across the turns of this chat (the last campaign sent, the last post made)
        return dict(self.state.get("extra") or {}, files=self.state["files"], out=self.folder, now=dt.datetime.now(), memo=self.state.setdefault("memo", {}))

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(redact(self.state), ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def _module(self, name):
        return next(m for m in self.modules if m.NAME == name)

    def say(self, message):
        t0 = time.perf_counter()
        p = self.state.get("pending")
        turn = {"user": message}
        try:
            if p and YES.search(message):
                self.state["pending"] = None
                reply = self._module(p["module"]).run(dict(p["op"], confirmed=True), self.ctx())
            elif p and NO.search(message):
                self.state["pending"] = None
                reply = "Dropped; nothing was done."
            else:
                self.state["pending"] = None
                reply = self.route(message)
        except Exception as e:  # noqa: BLE001 - a program's failure is said, not raised
            reply = f"Couldn't: {type(e).__name__}: {e}"
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2))
        self.state["turns"].append(turn)
        self.save()
        return reply

    def route(self, message):
        ctx = self.ctx()
        for m in self.modules:
            op = m.parse(message, ctx)
            if op:
                self.state["turns"].append({"module": m.NAME, "op": op})
                if op.get("op") in getattr(m, "OUTWARD", ()) and not op.get("confirmed"):
                    text = m.preview(op, ctx)
                    if op.get("blocked"):  # nothing to confirm yet: the preview says what is missing
                        return text
                    self.state["pending"] = {"module": m.NAME, "op": op}
                    return text + " Say 'yes' to go ahead."
                return m.run(op, ctx)
        return "Programs I can drive: " + "; ".join(f"{m.LABEL} (e.g. '{m.EXAMPLES[0]}')" for m in self.modules) + "."


SECRET_KEYS = {"password", "master", "secret", "token", "api_key", "passphrase"}
SECRET_TEXT = [re.compile(r"(?i)(\b(?:master\s+)?pass(?:word|phrase|code)\b\s*(?:is\s*)?[:=]?\s*)(\S+)"), re.compile(r"(Password from KeePassXC: )(\S+)")]


def redact(value):
    """A copy for the chat log on disk: passwords typed in requests, secret fields of ops and generated passwords hidden."""
    if isinstance(value, dict):
        return {k: ("[hidden]" if k.lower() in SECRET_KEYS and v else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pat in SECRET_TEXT:
            value = pat.sub(r"\1[hidden]", value)
    return value


def find_file(text, ctx, exts=None):
    """A file the request names: one given to the chat, or a full path in the request."""
    low = text.lower()
    for name, path in ctx.get("files", {}).items():
        if name in low or Path(name).stem in low:
            if not exts or Path(path).suffix.lower() in exts:
                return path
    m = re.search(r"([a-z]:\\[^\"<>|?*\n]+?\.[a-z0-9]{2,5})\b", text, re.I) or re.search(r'"([^"]+\.[a-z0-9]{2,5})"', text, re.I)
    if m and Path(m.group(1)).exists() and (not exts or Path(m.group(1)).suffix.lower() in exts):
        return m.group(1)
    if len(ctx.get("files", {})) == 1:
        path = next(iter(ctx["files"].values()))
        if not exts or Path(path).suffix.lower() in exts:
            return path
    return None
