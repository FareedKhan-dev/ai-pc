"""A conversation about the PC's files and settings.

  c = WinChat.start()                       the user's own folders (Downloads, Documents, Desktop, Pictures, Videos, Music)
  c.say("what's in my downloads?")
  c.say("clean up my downloads")            -> a plan (what goes to the Recycle Bin, and why); nothing happens until "yes"
  c.say("yes")
  c.say("find my CV and move it to documents")  /  c.say("make the second one my wallpaper")  /  c.say("undo")
  c.say("turn on light mode")  /  c.say("stop Teams from starting with Windows")  /  c.say("what's in the recycle bin?")
  c = WinChat.load()                        the last chat again, with its journal ('undo' still works)

What changes many files or removes anything is shown first and done on "yes". Everything done is journaled: "undo"
puts it back exactly (moves reversed, the Recycle Bin restored, settings set back), "redo" does it again. Every step is
checked on the disk; a batch that moves files also counts that nothing went missing. Nothing is ever deleted for good,
the Recycle Bin is never emptied, and system folders are never touched.
"""
import datetime as dt
import json
import os
import re
import shutil
import time
from collections import Counter
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.core.util import parse_json
from ai_pc.windows import fs
from ai_pc.windows.settings import SettingError, Settings
from ai_pc.windows.winparse import _no, _yes, parse, what_in

CHATS = ROOT / "out" / "win" / "chats"
UNDO = re.compile(r"^\s*(?:undo|revert|put (?:it|them|everything) back|take (?:that|it) back|reverse (?:that|it)|undo (?:that|it|the last (?:change|one)))\b", re.I)
REDO = re.compile(r"^\s*redo\b|\bdo it again\b", re.I)
HISTORY = re.compile(r"\bwhat (?:did you|have you) (?:just )?(?:do|done|change|changed)\b|^\s*(?:history|show (?:me )?(?:the )?history|what changed)\b", re.I)
BARE = re.compile(r"^\s*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|do it|no|nope|cancel)\s*[.!]*\s*$", re.I)
HELP = re.compile(r"^\s*(?:help|what can you do|how do i use you)\b", re.I)
VERBS = (r"(?:move|copy|zip|unzip|rename|delete|remove|trash|resize|convert|merge|combine|open|find|search|show|list|turn|set|make|put|organi[sz]e|sort|"
         r"clean|extract|compress|send|restore|stop|change|switch|what|how|which|where|tell)")
SPLIT = re.compile(r"(?<=[.!?;])\s+|,?\s+(?:and then|then|and also|also|after that)\s+|,?\s+and\s+(?=" + VERBS + r"\b)|,\s+(?=" + VERBS + r"\b)", re.I)
ALL = re.compile(r"\b(?:everything|all|whole|entire|every file|the files|files|stuff|things)\b", re.I)
CONFIRM_OVER = 15  # more moves or renames than this are shown first
OFFICE = (".doc", ".docx", ".rtf", ".odt", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsm")
KIND_LABEL = {"photo": ("photo", "photos"), "video": ("video", "videos"), "audio": ("audio file", "audio files"), "document": ("document", "documents"),
              "pdf": ("PDF", "PDFs"), "spreadsheet": ("spreadsheet", "spreadsheets"), "presentation": ("presentation", "presentations"),
              "archive": ("archive", "archives"), "installer": ("installer", "installers"), "partial": ("unfinished download", "unfinished downloads"),
              "code": ("code file", "code files"), "font": ("font", "fonts"), "design": ("design file", "design files"), "ebook": ("e-book", "e-books"),
              "torrent": ("torrent", "torrents"), "model3d": ("3D model", "3D models"), "folder": ("folder", "folders"), "other": ("other file", "other files")}
TRASH_LABEL = {"partial": ("unfinished download", "unfinished downloads"), "installer": ("old installer", "old installers"), "copy": ("copy", "copies"),
               "empty": ("empty folder", "empty folders"), "asked": ("item", "items")}
HELP_TEXT = ("I look after your files and settings, by code: 'what's in my downloads?', 'what's taking space?', 'find my CV', 'move it to documents', "
             "'clean up my downloads', 'organize my downloads', 'rename the photos by the date taken', 'zip the PDFs folder', 'convert the word files to pdf', "
             "'merge the pdfs', 'resize them to 1600 wide', 'what's in the recycle bin?', 'turn on dark mode', 'stop Teams from starting with Windows'. "
             "Big changes are shown first; 'undo' puts anything back; nothing is deleted for good.")

WIN_SYSTEM = """You turn a person's request about the files and settings on their Windows PC into operations for a program. Reply with ONE
JSON object: {"ops": [...]} or {"ask": "<short question back>"}. A file set W is {"where": "<folder path or downloads|documents|desktop|
pictures|videos|music>", "kind": "photo|video|audio|document|pdf|spreadsheet|presentation|archive|installer|partial", "words": ["name words"],
"names": ["exact file names"], "dirs": ["<a folder itself>"], "since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "field": "mtime|ctime|taken",
"larger": bytes, "smaller": bytes, "focus": true (the files talked about last), "pick": 2 (the 2nd of them; -1 the last)}. Operations:
 {"op": "find", "what": W, "sort": "newest|oldest|largest|smallest", "limit": 15}  {"op": "summary", "where": F}  {"op": "space"}  {"op": "find_dupes", "where": F}
 {"op": "organize", "where": F, "by": "kind|date|ext"}  {"op": "cleanup", "where": F}  {"op": "dedupe", "where": F}  {"op": "mkdir", "name": "...", "where": F}
 {"op": "move", "what": W, "to": "<folder path or place>"}  {"op": "copy", "what": W, "to": "..."}  {"op": "trash", "what": W}  {"op": "open", "what": W}
 {"op": "rename", "what": W, "pattern": "<'{taken:%Y-%m-%d} {n:03}', 'Trip {n:03}', '{date:%Y-%m-%d} {name}'>"}  {"op": "rename", "what": W, "to": "new name"}
 {"op": "zip", "what": W, "name": "..."}  {"op": "zip", "folder": "<path>"}  {"op": "unzip", "what": W}  {"op": "convert", "what": W, "to": "pdf|jpg|png|webp"}
 {"op": "resize", "what": W, "width": 1600}  {"op": "merge_pdfs", "what": W, "name": "..."}  {"op": "audio", "what": W}
 {"op": "bin_list"}  {"op": "bin_restore", "what": W}  (the Recycle Bin is never emptied; nothing is deleted for good)
 {"op": "setting", "name": "dark_mode|transparency|file_extensions|hidden_files|taskbar_left", "value": true|false}
 {"op": "setting", "name": "power_plan", "value": "balanced|high performance|power saver"}  {"op": "setting", "name": "default_printer", "value": "<printer>"}
 {"op": "wallpaper", "what": W}  {"op": "startup", "app": "<name>", "on": false}  {"op": "startup_list"}  {"op": "setting_get", "name": "..."}
Only folders under the person's own folders. Do only what was asked."""
KNOWN_OPS = {"find", "summary", "space", "find_dupes", "organize", "cleanup", "dedupe", "mkdir", "move", "copy", "trash", "open", "rename", "zip", "unzip",
             "convert", "resize", "merge_pdfs", "audio", "bin_list", "bin_restore", "setting", "wallpaper", "startup", "startup_list", "setting_get"}


class Which(Exception):
    """The request needs the person to say which (file, folder, one of a list): the message is the question back."""


def _n(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _when(iso):
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d %b %Y")
    except Exception:  # noqa: BLE001
        return "?"


def _ago(iso):
    d = dt.datetime.fromisoformat(iso)
    days = (dt.date.today() - d.date()).days
    return f"today {d:%H:%M}" if days == 0 else "yesterday" if days == 1 else f"{days} days ago" if days < 7 else f"on {d:%d %b %Y}"


def _shift_year(iso, years):
    d = dt.datetime.fromisoformat(iso)
    return d.replace(year=d.year + years).isoformat()


def _specific(what):
    return any((what or {}).get(k) for k in ("focus", "names", "dirs", "words", "kind", "since", "until", "larger", "smaller"))


def _dir_size(p):
    n = 0
    for dp, _, fn in os.walk(p):
        for f in fn:
            try:
                n += os.path.getsize(os.path.join(dp, f))
            except OSError:
                continue
    return n


def _nice(what):
    """A setting's read-back said the everyday way ('dark mode: off' -> 'light mode on')."""
    if what.startswith("dark mode: off"):
        return "light mode on (dark mode off)" + what[len("dark mode: off"):]
    return what.replace(": on", " on").replace(": off", " off")


def _name(s):
    return Path(str(s.get("src") or s.get("dst") or s.get("name") or "")).name


class WinChat:
    def __init__(self, state, planner=None, settings=None, server=None, log=print, read_only=False):
        self.state, self.planner, self.log, self.read_only = state, planner, log, read_only
        self.places = {k: Path(v) for k, v in state["places"].items()}
        self.guard = fs.Guard(state["roots"])
        self.settings = settings or Settings()
        self.server = server
        self.folder = Path(state["folder"])
        self._cache, self._notes, self._taken, self._guessed = {}, [], {}, False
        self.last_turn = None

    @classmethod
    def start(cls, places=None, roots=None, chats_dir=None, **kw):
        places = {k: str(v) for k, v in (places or fs.known_folders()).items() if v}
        roots = [str(r) for r in (roots or places.values())]
        cid = f"win_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        state = {"id": cid, "folder": str(folder), "places": places, "roots": roots, "journal": [], "redo": [], "pending": None, "focus": [],
                 "turns": []}
        c = cls(state, **kw)
        c.save()
        return c

    @classmethod
    def load(cls, cid=None, chats_dir=None, **kw):
        """A saved chat, with its journal (so 'undo' still works); the latest one when no id is given."""
        base = Path(chats_dir or CHATS)
        if cid:
            f = base / cid / "chat.json"
        else:
            found = sorted(base.glob("win_*/chat.json"), key=lambda p: p.stat().st_mtime)
            if not found:
                raise FileNotFoundError(f"no saved chat in {base}")
            f = found[-1]
        state = json.loads(f.read_text(encoding="utf-8"))
        state["pending"] = None
        state.setdefault("redo", [])
        return cls(state, **kw)

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def close(self):
        if self.server is not None:
            try:
                self.server.close()
            except Exception:  # noqa: BLE001
                pass
            self.server = None

    # ---------------------------------------------------------------- finding the files a request means
    def _scan(self, folder, recursive=True):
        key = (str(folder), recursive)
        if key not in self._cache:
            self._cache[key] = fs.scan(folder, recursive=recursive, budget_s=15)
        return self._cache[key]

    def _place(self, where):
        if not where:
            return None
        w = str(where)
        if w.lower() in self.places:
            return self.places[w.lower()]
        head, _, rest = w.replace("/", "\\").partition("\\")
        if head.lower() in self.places and rest and not Path(w).is_absolute():
            return self.places[head.lower()] / rest
        return Path(w)

    def _mine(self, p):
        try:
            self.guard.check(p)
            return True
        except fs.FsError:
            return False

    def _taken_of(self, f):
        k = (f["path"], f["mtime"])
        if k not in self._taken:
            self._taken[k] = fs.taken(f["path"]) or f["mtime"]
        return self._taken[k]

    def _match(self, recs, what):
        since = dt.datetime.fromisoformat(what["since"]) if what.get("since") else None
        until = dt.datetime.fromisoformat(what["until"]) if what.get("until") else None
        field = what.get("field") or "mtime"
        hits = fs.find(recs, kind=what.get("kind"), words=what.get("words"), larger=what.get("larger"), smaller=what.get("smaller"),
                       since=None if field == "taken" else since, until=None if field == "taken" else until, field=field)
        if field == "taken" and (since or until):  # a photo's own date (EXIF, else the date in its name), else the file's
            out = []
            for f in hits:
                t = self._taken_of(f) if f["kind"] == "photo" else f["mtime"]
                d = dt.datetime.fromisoformat(t)
                if (not since or d >= since) and (not until or d < until):
                    out.append(dict(f, taken=t))
            hits = out
        return hits

    def files(self, what, said=""):
        """The records a file set means: the ones talked about last ('them'; 'it' must be one; 'the second one'), a folder
        itself, exact names, or a search in one folder or in all of the person's folders. A month said without a year
        that has nothing is looked for in earlier years."""
        what = what or {}
        focus = self.state.get("focus") or []
        if what.get("missing_folder"):
            raise Which(f"There is no folder called '{what['missing_folder']}' in your folders" +
                        (f" (one by that name is in the Recycle Bin: say 'restore {what['missing_folder']}')" if any(
                            it["dir"] and it["name"].lower() == what["missing_folder"].lower() for it in fs.bin_items() if self._mine(it["orig"])) else "") + ".")
        if what.get("focus"):
            if what.get("pick"):
                k = what["pick"]
                if k == 0 or abs(k) > len(focus):
                    raise Which(f"The list has {_n(len(focus), 'item')}; which one?")
                p = focus[k - 1] if k > 0 else focus[k]
                if not Path(p).exists():
                    raise Which(f"{Path(p).name} is not there any more.")
                return [fs.record(p)]
            recs = [fs.record(p) for p in focus if Path(p).exists()]
            if not recs:
                raise Which("The files we talked about are not where they were any more. Which files do you mean?")
            if what.get("one") and len(recs) > 1:
                raise Which("Which one? " + "; ".join(f"{i + 1}. {r['name']}" for i, r in enumerate(recs[:8])) + (" ..." if len(recs) > 8 else "") +
                            " (say e.g. 'the second one').")
            return recs
        if what.get("dirs"):
            return [fs.record(self.guard.check(d, must_exist=True)) for d in what["dirs"]]
        if not _specific(what):
            if what.get("where") and ALL.search(said or ""):  # 'everything in Downloads': what sits in it, folders as a whole
                folder = self._where(what["where"])
                return [fs.record(p) for p in sorted(folder.iterdir(), key=lambda q: q.name.lower()) if p.name.lower() not in ("desktop.ini", "thumbs.db")]
            raise Which("Which files? e.g. 'the PDFs in Downloads', 'my CV', 'the photos from August', or 'everything in Downloads'.")
        folder = self._place(what.get("where"))
        pools = [folder] if folder else list(self.places.values())
        recs, seen = [], set()
        for p in pools:
            if p and p.exists():
                for f in self._scan(p)["files"]:
                    if f["path"] not in seen:
                        seen.add(f["path"])
                        recs.append(f)
        if what.get("names"):
            out = []
            for n in what["names"]:
                ws = n.split()
                for i in range(len(ws)):  # 'unzip photos.zip' -> 'photos.zip': the longest tail that is a real name
                    cand = " ".join(ws[i:]).lower()
                    hit = [f for f in recs if f["name"].lower() == cand]
                    if hit:
                        out += [h for h in hit if h not in out]
                        break
            return out
        hits = self._match(recs, what)
        if not hits and folder is not None and getattr(self, "_guessed", False):  # the model guessed the folder: look in all of them
            pool = [f for p in self.places.values() if p.exists() for f in self._scan(p)["files"]]
            hits = self._match(pool, what)
            if hits:
                self._notes.append(f"(Not in {folder.name}; found in {', '.join(sorted({Path(f['folder']).name for f in hits}))}.)")
        if not hits and what.get("any_year") and what.get("since"):
            d0 = dt.datetime.fromisoformat(what["since"])
            for back in range(1, 11):
                w2 = dict(what, since=_shift_year(what["since"], -back), until=_shift_year(what["until"], -back) if what.get("until") else None)
                hits = self._match(recs, w2)
                if hits:
                    self._notes.append(f"(Nothing from {d0:%B %Y}, so these are from {d0:%B} {d0.year - back}.)")
                    break
        return hits

    def _where(self, where, default="downloads"):
        p = self._place(where) or self.places.get(default)
        if p is None or not p.exists():
            raise fs.FsError(f"no folder {where or default}")
        return self.guard.check(p)

    def _dest(self, to):
        p = self._place(to)
        if p is None or not p.is_absolute():
            raise Which("Move them where? e.g. 'to Documents' or 'to a folder called Invoices in Documents'.")
        return self.guard.check(p)

    def _focus_folder(self):
        foc = [Path(p) for p in self.state.get("focus") or [] if Path(p).exists()]
        if len(foc) == 1 and foc[0].is_dir():
            return str(foc[0])
        if foc:
            try:
                return os.path.commonpath([str(p.parent) for p in foc])
            except ValueError:
                return None
        return None

    def _not_places(self, files, verb):
        """Never the person's Downloads / Documents ... folders themselves (what is inside them, yes)."""
        tops = {fs._key(p) for p in self.places.values()} | {fs._key(r) for r in self.guard.roots}
        for f in files:
            if fs._key(f["path"]) in tops:
                raise Which(f"I don't {verb} your {Path(f['path']).name} folder itself; I can work on what is inside it.")

    def _room(self, files, dest, copy):
        """Copies (and moves to another drive) need room there."""
        need = sum((_dir_size(f["path"]) if f.get("dir") else f["size"]) for f in files if copy or Path(f["path"]).drive.lower() != dest.drive.lower())
        if not need:
            return
        anchor = next((p for p in [dest, *dest.parents] if p.exists()), None)
        free = shutil.disk_usage(anchor).free if anchor else 0
        if need > free - 200e6:
            raise fs.FsError(f"not enough space on {dest.drive}: this needs {fs.human(need)} and {fs.human(free)} is free")

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        self._cache, self._notes = {}, []
        turn = {"user": message, "intents": [], "llm": False}
        self._turn = turn
        low = message.strip().lower()
        pend = self.state.get("pending")
        out = []
        if pend and _yes(low):
            turn["intents"].append("confirm")
            self.state["pending"] = None
            out.append(self._run(pend["steps"], pend["said"], pend.get("after"), pend.get("notes")))
        elif pend and _no(low):
            turn["intents"].append("cancel")
            self.state["pending"] = None
            out.append("Cancelled: nothing changed.")
        elif not pend and BARE.search(low):
            turn["intents"].append("nothing")
            out.append("There is nothing waiting for a yes or no right now.")
        elif UNDO.search(low):
            turn["intents"].append("undo")
            n = 2 if re.search(r"\b(?:two|2|last two|both)\b", low) else 3 if re.search(r"\b(?:three|3)\b", low) else 1
            out.append(self.undo(n))
        elif REDO.search(low):
            turn["intents"].append("redo")
            out.append(self.redo())
        elif HISTORY.search(low):
            turn["intents"].append("history")
            out.append(self.history())
        elif HELP.search(low):
            turn["intents"].append("help")
            out.append(HELP_TEXT)
        else:
            if pend:
                self.state["pending"] = None  # a new request instead of an answer: the plan waiting is dropped
                self._notes.append("(The plan that was waiting for a yes was dropped.)")
            clauses = [x.strip(" ,") for x in SPLIT.split(message) if x and x.strip(" ,")]
            for cl in clauses or [message]:
                r = parse(cl, self.places, self.state.get("focus"), raw=cl)
                ops = r.get("ops") or []
                used_llm = False
                if not ops and not r.get("ask"):
                    r = self._llm(cl, message)
                    ops = r.get("ops") or []
                    used_llm = self.planner is not None
                if not ops:
                    out.append(r.get("ask") or f"I could not read '{cl}'. Try e.g. 'find my CV', 'organize my downloads', or 'help'.")
                    turn["intents"].append("ask")
                    break  # what comes after may say 'them' about what was not understood: stop here
                stop = False
                self._guessed = used_llm  # folders the model names are guesses
                turn.setdefault("ops", []).extend(json.loads(json.dumps(ops, default=str)))
                for op in ops:
                    turn["intents"].append(op.get("op", "?"))
                    try:
                        out.append(self.do(op, cl))
                    except Which as e:
                        out.append(str(e))
                        turn["intents"].append("ask")
                        stop = True
                    except (fs.FsError, SettingError) as e:
                        out.append(f"Couldn't: {e}.")
                        stop = True
                    except (KeyError, TypeError, ValueError, AttributeError) as e:  # a malformed operation (from the model)
                        out.append(f"I could not do that ({type(e).__name__}: {e}).")
                        stop = True
                    else:
                        stop = bool(self.state.get("pending"))
                    if stop:
                        break
                if stop:
                    break  # a question back, a plan waiting for a yes, or a failure: the rest waits
        reply = "\n".join(x for x in out if x).strip() or "Tell me what to do with your files, e.g. 'what's in my downloads?' or 'organize my downloads'."
        if self._notes:
            reply += " " + " ".join(self._notes)
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2))
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _llm(self, clause, message):
        if self.planner is None:
            return {"ask": f"I could not read '{clause}'. Try e.g. 'find my CV', 'organize my downloads', 'turn on dark mode', or 'help'."}
        self._turn["llm"] = True
        foc = [Path(p).name for p in (self.state.get("focus") or [])[:10]]
        user = (f"FOLDERS: {json.dumps({k: str(v) for k, v in self.places.items()})}\nFILES TALKED ABOUT LAST (focus): {json.dumps(foc)}\n"
                f"Use focus only when the person points back at those files (it, them, those). When they name something else (the screenshot, my CV), "
                f"describe it with words and kind instead.\nMESSAGE: {message}\nREQUEST: {clause}")
        try:
            r = self.planner._call("fast", [{"role": "system", "content": WIN_SYSTEM}, {"role": "user", "content": user}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ask": f"I could not work that out ({type(e).__name__})."}
        ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op") in KNOWN_OPS]
        return {"ops": ops, "ask": d.get("ask") if not ops else None}

    # ---------------------------------------------------------------- one operation
    def do(self, op, said):
        k = op["op"]
        if k == "say":
            return op.get("text") or ""
        if k == "summary":
            where = op.get("where") or (self._focus_folder() if op.get("focus") else None)
            return self.summary(self._where(where))
        if k == "space":
            return self.space()
        if k == "find":
            return self.find(op, said)
        if k == "find_dupes":
            where = self._where(op.get("where"))
            groups = fs.duplicates(self._scan(where)["files"])
            if not groups:
                return f"No repeated files in {where.name}."
            keep = [fs._keeper(g) for g in groups]
            self.state["focus"] = [f["path"] for g, kp in zip(groups, keep) for f in g if f is not kp]
            return (f"{_n(len(groups), 'set')} of identical files in {where.name}: " + "; ".join(" = ".join(f["name"] for f in g) for g in groups[:8]) +
                    f". Say 'delete them' to send the {_n(len(self.state['focus']), 'copy', 'copies')} to the Recycle Bin (the first of each stays).")
        if k == "bin_list":
            return self.bin_list()
        if k == "bin_restore":
            return self.bin_restore(op, said)
        if k == "setting":
            return self._run([{"do": "setting", "name": op["name"], "value": op["value"]}], said)
        if k == "setting_get":
            v = self.settings.get(op["name"])
            nice = {"dark_mode": "Dark mode is " + ("on" if v else "off (light mode)"), "wallpaper": f"The wallpaper is {Path(str(v)).name}",
                    "power_plan": f"The power plan is {v}", "default_printer": f"The default printer is {v}",
                    "file_extensions": "File extensions are " + ("shown" if v else "hidden")}.get(op["name"], f"{op['name']}: {v}")
            return nice + "."
        if k == "startup_list":
            items = self.settings.startup()
            on = [x for x in items if x["on"]]
            off = [x for x in items if not x["on"]]
            return (f"{_n(len(on), 'app')} start with Windows: " + ", ".join(x["label"] for x in on) + (f"; turned off: {', '.join(x['label'] for x in off)}" if off else "") +
                    ". Say e.g. 'stop Teams from starting with Windows'.")
        if k == "startup":
            return self._run([{"do": "startup", "name": op["app"], "value": bool(op.get("on"))}], said)
        if k == "wallpaper":
            fl = [f for f in self.files(op.get("what"), said) if f["kind"] == "photo"]
            if not fl:
                return "Which picture? e.g. 'set IMG_1234.jpg as my wallpaper', or find some and say 'make the first one my wallpaper'."
            if len(fl) > 1:
                self.state["focus"] = [f["path"] for f in fl]
                raise Which("Which one? " + "; ".join(f"{i + 1}. {f['name']}" for i, f in enumerate(fl[:8])) + " (say e.g. 'the second one').")
            return self._run([{"do": "setting", "name": "wallpaper", "value": fl[0]["path"]}], said)
        if k == "mkdir":
            base = self._where(op.get("where"), "documents")
            return self._run([{"do": "mkdir", "dst": str(base / op["name"])}], said, after=[str(base / op["name"])])
        if k == "organize":
            where = self._where(op.get("where"))
            idx = self._scan(where)
            loose = [f for f in idx["files"] if Path(f["folder"]).resolve() == where.resolve() and (not op.get("kind") or f["kind"] == op["kind"])]
            pool = [f for f in loose if not fs.in_progress(f)]
            notes = [f"{f['name']} (may still be downloading)" for f in loose if fs.in_progress(f)]
            if not pool:
                return f"There are no loose files to sort in {where.name} (folders stay as they are)."
            by = op.get("by") or "kind"
            steps = fs.plan_organize(idx, by=by, files=pool, field="taken" if op.get("taken") and by == "date" else "mtime")
            return self._maybe(steps, said, f"sort {_n(len(pool), 'file')} in {where.name} into folders by {'month' if by == 'date' else by}", notes=notes)
        if k == "cleanup":
            where = self._where(op.get("where"))
            notes = []
            steps = fs.plan_cleanup(self._scan(where), notes=notes)
            if not steps:
                return f"{where.name} is already tidy: no old unfinished downloads, old installers, copies or empty folders." + \
                    (" Left alone: " + "; ".join(notes) + "." if notes else "")
            return self._confirm(steps, said, f"clean up {where.name}", notes=notes)
        if k == "dedupe":
            where = self._where(op.get("where"))
            idx = self._scan(where)
            steps = fs.plan_dedupe(fs.top_level(idx))
            inner = len(fs.plan_dedupe(idx["files"])) - len(steps)
            notes = [f"{_n(inner, 'more identical file')} inside sub-folders (they may belong to those folders; say 'find duplicates' to see them)"] if inner > 0 else None
            if not steps:
                return f"No repeated loose files in {where.name}." + (" Left alone: " + notes[0] + "." if notes else "")
            return self._confirm(steps, said, f"remove repeated files in {where.name} (one of each stays)", notes=notes)
        if k == "zip" and op.get("folder"):
            src = self.guard.check(op["folder"], must_exist=True)
            self._not_places([fs.record(src)], "zip up")
            dst = src.parent / f"{op.get('name') or src.name}.zip"
            return self._run(fs.plan_zip([str(src)], dst), said)
        files = self.files(op.get("what"), said)
        fit = {"convert": lambda f: f["kind"] == "photo" or f["ext"] in OFFICE, "resize": lambda f: f["kind"] == "photo", "audio": lambda f: f["kind"] == "video",
               "merge_pdfs": lambda f: f["ext"] == ".pdf", "unzip": lambda f: f["ext"] == ".zip"}.get(k)
        if fit and self._guessed and (op.get("what") or {}).get("focus") and not any(fit(f) for f in files):
            try:  # the model pointed at the last files, but none of them can be used for this: take what the words name
                alt = what_in(said.lower(), said, self.places, None)
                files = self.files(alt, said) if _specific(alt) else files
            except Which:
                pass
        if not files:
            w = op.get("what") or {}
            if w.get("names"):
                return f"There is no file called {w['names'][0]} in " + (Path(str(self._place(w['where']))).name if w.get("where") else "your folders") + "."
            return "I found no such files" + (f" in {Path(str(self._place(w['where']))).name}" if w.get("where") else "") + ". Try 'find ...' first, or name the folder."
        if k in ("move", "copy"):
            if not op.get("to"):
                raise Which(f"{k.capitalize()} {'it' if len(files) == 1 else 'them'} where? e.g. 'to Documents'.")
            dest = self._dest(op["to"])
            if k == "move":
                self._not_places(files, "move")
            for f in files:
                if f.get("dir") and (dest == Path(f["path"]).resolve() or Path(f["path"]).resolve() in dest.parents):
                    raise Which(f"{f['name']} cannot go inside itself.")
            self._room(files, dest, copy=k == "copy")
            steps = fs.plan_move(files, dest, copy=k == "copy")
            if not [s for s in steps if s["do"] != "mkdir"]:
                return f"{'They are' if len(files) > 1 else 'It is'} already in {dest.name}."
            return self._maybe(steps, said, f"{k} {_n(len(files), 'item')} to {dest.name}")
        if k == "trash":
            self._not_places(files, "remove")
            steps = [{"do": "trash", "src": f["path"], "why": "asked", "cat": "asked", "size": _dir_size(f["path"]) if f.get("dir") else f["size"]} for f in files]
            note = " (I never delete for good: it goes to the Recycle Bin, and 'undo' brings it back.)" if op.get("forever") else ""
            if len(steps) == 1 and not (files[0].get("dir") and any(Path(files[0]["path"]).iterdir())):
                return self._run(steps, said) + note
            what = f"send {_n(len(steps), 'item')} to the Recycle Bin" + (f" (the {files[0]['name']} folder and everything in it)" if len(files) == 1 else "")
            return self._confirm(steps, said, what) + note
        if k == "open":
            if len(files) > 3:
                self.state["focus"] = [f["path"] for f in files]
                raise Which(f"That is {_n(len(files), 'file')}; open which one? " + "; ".join(f"{i + 1}. {f['name']}" for i, f in enumerate(files[:6])))
            for f in files:
                os.startfile(self.guard.check(f["path"], must_exist=True))
            self.state["focus"] = [f["path"] for f in files]
            return "Opened " + ", ".join(f["name"] for f in files) + " in its own app."
        if k == "rename":
            self._not_places(files, "rename")
            if op.get("to"):
                to = op["to"].strip().strip("'\"")
                if len(files) == 1 and files[0].get("dir"):
                    steps = [{"do": "move", "src": files[0]["path"], "dst": str(fs.unique(Path(files[0]["path"]).with_name(to)))}]
                else:
                    if Path(to).suffix.lower() and Path(to).suffix.lower() == files[0]["ext"]:
                        to = Path(to).stem  # 'rename it to beach.jpg': the extension stays as it is
                    steps = fs.plan_rename(files, pattern=to if len(files) == 1 else f"{to} {{n:03}}")
            else:
                steps = fs.plan_rename(files, pattern=op.get("pattern"), replace=op.get("replace"), case=op.get("case"))
            if not steps:
                return "The names already read that way."
            return self._maybe(steps, said, f"rename {_n(len(steps), 'item')}")
        if k == "zip":
            base = Path(files[0]["folder"])
            dst = base / f"{op.get('name') or (base.name if len(files) > 1 else Path(files[0]['name']).stem)}.zip"
            return self._run(fs.plan_zip(files, dst), said)
        if k == "unzip":
            steps = [s for f in files if f["ext"] == ".zip" for s in fs.plan_unzip(f["path"])]
            if not steps:
                return "Only .zip files can be opened here (no .rar or .7z yet)."
            return self._run(steps, said)
        if k == "convert":
            to = op.get("to") or "pdf"
            if to == "pdf":
                office = [f for f in files if f["ext"] in OFFICE]
                if not office:
                    return "Only Word, PowerPoint and Excel files are turned into PDFs here."
                if self.server is None:
                    from ai_pc.office import render as RN
                    self.server = RN.Server()
                return self._run([{"do": "office_pdf", "src": f["path"]} for f in office], said)
            photos = [f for f in files if f["kind"] == "photo" and f["ext"].lstrip(".").replace("jpeg", "jpg") != to]
            if not photos:
                return "Only pictures are converted to JPG / PNG / WebP" + (" (they already are)." if any(f["kind"] == "photo" for f in files) else ".")
            return self._run([{"do": "image", "src": f["path"], "format": to} for f in photos], said)
        if k == "resize":
            photos = [f for f in files if f["kind"] == "photo"]
            if not photos:
                return "Only pictures can be resized."
            steps = []
            made = set()
            for f in photos:
                d = Path(f["folder"]) / "Resized"
                if not d.exists() and str(d) not in made:
                    steps.append({"do": "mkdir", "dst": str(d)})
                    made.add(str(d))
                steps.append({"do": "image", "src": f["path"], "dst": str(d / f["name"]), "width": op.get("width"), "height": op.get("height")})
            return self._run(steps, said)
        if k == "merge_pdfs":
            pdfs = [f for f in files if f["ext"] == ".pdf"]
            if len(pdfs) < 2:
                return "Merging needs two PDFs or more."
            dst = Path(pdfs[0]["folder"]) / f"{op.get('name') or 'Merged'}.pdf"
            return self._run([{"do": "pdf_merge", "srcs": [f["path"] for f in sorted(pdfs, key=lambda x: x['name'].lower())], "dst": str(dst)}], said)
        if k == "audio":
            vids = [f for f in files if f["kind"] == "video"]
            if not vids:
                return "Which video? The sound comes out of a video file."
            return self._run([{"do": "audio", "src": f["path"]} for f in vids], said)
        return f"I don't do '{k}' yet."

    # ---------------------------------------------------------------- answers
    def summary(self, where):
        idx = self._scan(where)
        top = [f for f in idx["files"] if Path(f["folder"]).resolve() == where.resolve()]
        subs = [d for d in idx["dirs"] if Path(d).parent.resolve() == where.resolve()]
        empty = [d for d in subs if not any(Path(d).iterdir())]
        inside = len(idx["files"]) - len(top)
        parts = ", ".join(f"{_n(n, *KIND_LABEL.get(kind, (kind, kind + 's')))} ({fs.human(s)})" for kind, n, s in fs.summary(idx))
        big = sorted(idx["files"], key=lambda f: -f["size"])[:3]
        self.state["focus"] = [f["path"] for f in top] or [f["path"] for f in idx["files"]]
        txt = f"{where.name}: {_n(len(idx['files']), 'file')}, {fs.human(idx['bytes'])}"
        if subs:
            bits = [f"{len(top)} loose"] + ([f"{inside} in {_n(len(subs) - len(empty), 'folder')}"] if inside else []) + \
                   ([_n(len(empty), "empty folder")] if empty else [])
            txt += " (" + ", ".join(bits) + ")"
        if not idx["files"]:
            return txt + "."
        txt += f": {parts}. Biggest: " + ", ".join(f"{f['name']} ({fs.human(f['size'])})" for f in big) + "."
        if idx.get("truncated"):
            txt += " (A very big folder: I looked through as much as I could in 15 seconds.)"
        return txt

    def space(self):
        import win32api
        import win32file
        out = []
        for d in win32api.GetLogicalDriveStrings().split("\0"):
            if d and win32file.GetDriveType(d) == win32file.DRIVE_FIXED:
                u = shutil.disk_usage(d)
                out.append(f"{d[:2]} {fs.human(u.free)} free of {fs.human(u.total)} ({u.used / u.total:.0%} used)")
        return "Disk space: " + "; ".join(out) + "."

    def find(self, op, said=""):
        what = op.get("what") or {}
        lim = op.get("limit") or 15
        if what.get("missing_folder"):
            return self.files(what, said)  # says there is no such folder
        if not _specific(what):  # looking is harmless: no file set named means every file there (or in all the folders)
            pools = [self._where(what["where"])] if what.get("where") else [p for p in self.places.values() if p.exists()]
            hits = [f for p in pools for f in self._scan(p)["files"]]
            if op.get("sort") == "largest" and not what.get("where"):  # 'what's taking space?': each folder, then the biggest files
                sizes = sorted(((p.name, self._scan(p)["bytes"]) for p in pools), key=lambda x: -x[1])
                big = fs.find(hits, sort="largest")[:lim]
                self.state["focus"] = [f["path"] for f in big]
                return ("Your folders: " + ", ".join(f"{n} {fs.human(b)}" for n, b in sizes) + ". Biggest files:\n" +
                        "\n".join(f"{i + 1}. {f['name']} ({Path(f['folder']).name}, {fs.human(f['size'])})" for i, f in enumerate(big)))
        else:
            hits = self.files(what, said)
        sort = op.get("sort") or "newest"
        field = "taken" if what.get("field") == "taken" else "mtime"
        hits = fs.find(hits, sort=sort, field=field) if sort else hits
        if not hits:
            return "Nothing matches" + (f" in {Path(str(self._place(what['where']))).name}" if what.get("where") else " in your folders") + "."
        self.state["focus"] = [f["path"] for f in hits]
        if op.get("count"):
            return f"{_n(len(hits), 'file')}, {fs.human(sum(f['size'] for f in hits))}."
        lines =[f"{i + 1}. {f['name']} ({Path(f['folder']).name}, {fs.human(f['size'])}, {_when(f.get('taken') or f['mtime'])})" for i, f in enumerate(hits[:lim])]
        more = f"\n... and {len(hits) - lim} more" if len(hits) > lim else ""
        return f"{len(hits)} found" + (f", {fs.human(sum(f['size'] for f in hits))} in all" if len(hits) > 1 else "") + ":\n" + "\n".join(lines) + more

    def bin_list(self):
        items = fs.bin_items()
        mine = [it for it in items if self._mine(it["orig"])]
        if not mine:
            return "Nothing from your folders is in the Recycle Bin."
        total = sum(it["size"] for it in mine)
        self.state["bin_list"] = [it["orig"] for it in mine[:10]]
        lines = [f"{i + 1}. {it['name']} (from {Path(it['orig']).parent.name}, deleted {_ago(it['deleted'])}, {fs.human(it['size'])})" for i, it in enumerate(mine[:10])]
        return (f"The Recycle Bin holds {_n(len(mine), 'item')} from your folders ({fs.human(total)}), newest first:\n" + "\n".join(lines) +
                (f"\n... and {len(mine) - 10} more" if len(mine) > 10 else "") + "\nSay e.g. 'restore the first one'. I never empty it.")

    def bin_restore(self, op, said):
        items = [it for it in fs.bin_items() if self._mine(it["orig"])]
        w = op.get("what") or {}
        if op.get("pick"):
            lst = self.state.get("bin_list") or [it["orig"] for it in items[:10]]
            k = op["pick"]
            if k == 0 or abs(k) > len(lst):
                raise Which("Which one? Say 'what's in the recycle bin?' to see the list.")
            want = fs._key(lst[k - 1] if k > 0 else lst[k])
            hits = [it for it in items if fs._key(it["orig"]) == want][:1]
        else:
            text = " ".join((op.get("text") or "").lower().split())
            named = [it for it in items if text and it["name"].lower() in (text, re.sub(r"^(?:the|my)\s+", "", text))]
            if named:  # 'restore New folder': its exact name
                w = {"names": [named[0]["name"]]}
            if not (w.get("names") or w.get("words") or w.get("kind")):
                raise Which("Restore which? Say 'what's in the recycle bin?' to see what is there.")
            hits = []
            for it in items:
                nm = it["name"].lower()
                if w.get("names") and not any(nm == " ".join(n.split()[i:]).lower() for n in w["names"] for i in range(len(n.split()))):
                    continue
                if w.get("words") and not all(re.search(r"(?<![a-z0-9])" + re.escape(x.lower()), re.sub(r"[_\-.]+", " ", nm)) for x in w["words"]):
                    continue
                if w.get("kind") and fs.kind_of(nm) != w["kind"]:
                    continue
                hits.append(it)
        seen, uniq = set(), []
        for it in hits:  # newest first: the latest deletion of each path
            if fs._key(it["orig"]) not in seen:
                seen.add(fs._key(it["orig"]))
                uniq.append(it)
        if not uniq:
            return "Nothing like that is in the Recycle Bin (from your folders)."
        plural = bool(re.search(r"\b(?:all|both|them|those|these|everything)\b", said.lower())) or \
            any(re.search(r"\b" + re.escape(x.lower()) + r"e?s\b", said.lower()) for x in (w.get("words") or []))
        if len(uniq) > 1 and not plural:
            self.state["bin_list"] = [it["orig"] for it in uniq[:8]]
            raise Which("Which one? " + "; ".join(f"{i + 1}. {it['name']} (from {Path(it['orig']).parent.name}, deleted {_ago(it['deleted'])})"
                                                  for i, it in enumerate(uniq[:8])) + " (say e.g. 'restore the first one').")
        return self._run([{"do": "restore", "src": it["orig"], "size": it["size"]} for it in uniq[:100]], said)

    # ---------------------------------------------------------------- doing; shown first when it is big or removes anything
    @staticmethod
    def _trash_name(s):
        n = Path(s["src"]).name
        if s.get("keep"):
            return f"{n} (= {Path(s['keep']).name})"
        if s.get("cat") == "installer":
            return f"{n} ({s['why'].replace('an installer from ', '')})"
        return n

    def _describe(self, steps, full=True):
        moves = [s for s in steps if s["do"] in ("move", "copy")]
        trash = [s for s in steps if s["do"] == "trash"]
        back = [s for s in steps if s["do"] == "restore"]
        bits = []
        if moves:
            verb = moves[0]["do"]
            if all(Path(s["src"]).parent == Path(s["dst"]).parent for s in moves):
                if full or len(moves) == 1:
                    bits.append(f"rename {_n(len(moves), 'item')}: " + "; ".join(f"{Path(s['src']).name} -> {Path(s['dst']).name}" for s in moves[:6]) +
                                (f"; and {len(moves) - 6} more" if len(moves) > 6 else ""))
                else:
                    bits.append(f"rename {_n(len(moves), 'item')} (e.g. {Path(moves[0]['src']).name} -> {Path(moves[0]['dst']).name})")
            else:
                dests = Counter(s.get("group") or Path(s["dst"]).parent.name for s in moves)
                if len(moves) <= 3 and len(dests) == 1:
                    bits.append(f"{verb} " + ", ".join(Path(s["src"]).name for s in moves) + f" to {next(iter(dests))}")
                elif len(dests) == 1:
                    bits.append(f"{verb} {_n(len(moves), 'item')} to {next(iter(dests))}")
                else:
                    bits.append(f"{verb} {_n(len(moves), 'item')} into " + ", ".join(f"{g} ({n})" for g, n in dests.most_common(10)))
        if trash:
            size = sum(s.get("size") or 0 for s in trash)
            by = {}
            for s in trash:
                by.setdefault(s.get("cat") or "asked", []).append(s)
            if full:
                parts = []
                for cat, ss in by.items():
                    names = ", ".join(self._trash_name(s) for s in ss[:8]) + (f" and {len(ss) - 8} more" if len(ss) > 8 else "")
                    parts.append(names if cat == "asked" else f"{_n(len(ss), *TRASH_LABEL[cat])}: {names}")
                bits.append(f"{_n(len(trash), 'item')} to the Recycle Bin" + (f" ({fs.human(size)})" if size else "") + ": " + "; ".join(parts))
            elif len(trash) <= 3:
                bits.append(", ".join(Path(s["src"]).name for s in trash) + " to the Recycle Bin")
            else:
                bits.append(f"{_n(len(trash), 'item')} to the Recycle Bin (" + ", ".join(_n(len(ss), *TRASH_LABEL[cat]) for cat, ss in by.items()) + ")")
        if back:
            bits.append(", ".join(Path(s["src"]).name for s in back[:6]) + (f" and {len(back) - 6} more" if len(back) > 6 else "") + " back from the Recycle Bin")
        return "; ".join(bits)

    def _confirm(self, steps, said, what, notes=None):
        self.state["pending"] = {"steps": steps, "said": said, "notes": notes}
        return (f"Plan ({what}): {self._describe(steps)}." + (" Left alone: " + "; ".join(notes) + "." if notes else "") +
                " Nothing is deleted for good and 'undo' puts it all back. Say 'yes' to go ahead or 'no' to cancel.")

    def _maybe(self, steps, said, what, notes=None):
        big = sum(1 for s in steps if s["do"] in ("move", "copy")) > CONFIRM_OVER
        if big and not re.search(r"\bwithout asking\b|\bjust do it\b|\bgo ahead\b", said.lower()):
            return self._confirm(steps, said, what, notes)
        return self._run(steps, said, notes=notes)

    def _exec(self, steps):
        """Steps done in order (settings by the settings backend, files by fs, the Recycle Bin ones together), each
        checked. A step that fails is reported and the others still run. Returns done, checks, inverse (the undo plan),
        errors [(step, why)], the folders made, and the outputs (moved, copied or made files) in order."""
        done, checks, inverse, errors, made, outs = [], [], [], [], [], []
        i = 0
        while i < len(steps):
            if steps[i]["do"] in ("setting", "startup"):
                s = steps[i]
                try:
                    r = self.settings.apply(s)
                    results = [(s, {"ok": r["ok"], "what": r["what"]}, r["undo"], None)]
                except (SettingError, OSError) as e:
                    results = [(s, None, None, str(e))]
                i += 1
            else:
                j = i
                while j < len(steps) and steps[j]["do"] not in ("setting", "startup"):
                    j += 1
                results = fs.run_batch(steps[i:j], self.guard, self.server)
                i = j
            for s, res, inv, err in results:
                if err:
                    errors.append((s, err))
                    continue
                done.append(s)
                checks.append(res)
                if inv:
                    inverse.insert(0, inv)
                    if s["do"] == "mkdir":
                        made.append(s["dst"])
                    elif inv["do"] == "move":
                        outs.append(inv["src"])
                    elif inv["do"] == "trash" and s["do"] != "restore":
                        outs.append(inv["src"])
                    elif s["do"] == "restore":
                        outs.append(s["src"])
        return done, checks, inverse, errors, made, outs

    def _run(self, steps, said, after=None, notes=None, redo=False):
        if self.read_only:  # looking only: say what would be done
            def one(s):
                if s["do"] == "startup":
                    return f"{'let' if s['value'] else 'stop'} {s['name']} {'start' if s['value'] else 'from starting'} with Windows"
                if s["do"] == "setting":
                    v = s["value"]
                    return f"turn {s['name'].replace('_', ' ')} {'on' if v else 'off'}" if isinstance(v, bool) else f"set the {s['name'].replace('_', ' ')} to {Path(str(v)).name}"
                return f"{s['do']} {_name(s)}"
            what = self._describe(steps) or "; ".join(one(s) for s in steps[:8])
            return f"Would do: {what}. (Looking only: nothing changed.)"
        moves = [s for s in steps if s["do"] == "move"]
        count = bool(moves) and all(s["do"] in ("move", "mkdir") for s in steps)
        parents = sorted({str(Path(s[k]).parent) for s in moves for k in ("src", "dst")}) if count else []
        before = fs.entries(parents) if count else 0
        done, checks, inverse, errors, made, outs = self._exec(steps)
        if count and done:  # every file and folder is still somewhere: the same count, new folders aside
            n_after = fs.entries(parents) - sum(1 for d in made if str(Path(d).parent) in parents)
            checks.append({"ok": n_after == before, "what": f"nothing lost: {before} before, {n_after} after", "count": True})
        if done:
            self.state["journal"].append({"n": len(self.state["journal"]) + 1, "said": said, "steps": done, "undo": inverse, "checks": checks,
                                          "errors": [f"{_name(s)}: {e}" for s, e in errors], "undone": False,
                                          "when": dt.datetime.now().isoformat(timespec="seconds")})
            if not redo:
                self.state["redo"] = []
            if any(s["do"] in ("trash", "restore") for s in done):
                self.state["bin_list"] = None  # 'restore the first one' now means the newest in the bin
            focus = [p for p in (after or outs) if p and Path(p).exists()]
            gone = {fs._key(s["src"]) for s in done if s["do"] == "trash"}
            self.state["focus"] = focus or [p for p in self.state.get("focus") or [] if fs._key(p) not in gone]
        self._cache = {}
        return self._report(done, checks, errors, notes)

    def _report(self, done, checks, errors, notes=None):
        bad = [c for c in checks if not c["ok"]]
        skipped = f" Skipped {len(errors)}: " + "; ".join(f"{_name(s)} ({e})" for s, e in errors[:4]) + "." if errors else ""
        if not done:
            return "Nothing changed." + skipped
        if all(s["do"] in ("setting", "startup") for s in done):
            msg = "Done: " + "; ".join(_nice(c["what"]) for c in checks) + "." + (" Checked: read back from Windows." if not bad else "")
        elif any(s["do"] in ("image", "office_pdf", "pdf_merge", "audio", "zip", "unzip") for s in done):
            made = [c["what"] for c in checks if not c.get("count") and not c["what"].startswith("folder ")]
            msg = "Done: " + "; ".join(made[:8]) + (f"; and {len(made) - 8} more" if len(made) > 8 else "") + f". Checked: {len(checks) - len(bad)}/{len(checks)} OK."
        else:
            cnt = next((c for c in checks if c.get("count")), None)
            msg = f"Done: {self._describe(done, full=False)}. Checked: {len(checks) - len(bad)}/{len(checks)} OK" + \
                (f" ({cnt['what']})" if cnt and cnt["ok"] else "") + "."
            freed = sum(s.get("size") or 0 for s in done if s["do"] == "trash")
            if freed:
                msg += f" {fs.human(freed)} is in the Recycle Bin (the space comes back when it is emptied)."
        if bad:
            msg += " Not right: " + "; ".join(c["what"] for c in bad[:3]) + "."
        msg += skipped
        if notes:
            msg += " Left alone: " + "; ".join(notes) + "."
        return msg + " Say 'undo' to put it back."

    # ---------------------------------------------------------------- the journal
    def undo(self, n=1):
        outs = []
        for _ in range(n):
            b = next((x for x in reversed(self.state["journal"]) if not x["undone"]), None)
            if b is None:
                outs.append("Nothing (more) to undo.")
                break
            done, checks, inverse, errors, made, back = self._exec(b["undo"])
            b["undone"] = True if not errors else "partly"
            if any(s["do"] in ("trash", "restore") for s in done):
                self.state["bin_list"] = None
            self.state["redo"].append(b["n"])
            moved_back = [s["dst"] for s in done if s["do"] == "move"] + [s["src"] for s in done if s["do"] == "restore"]
            if moved_back:
                self.state["focus"] = [p for p in moved_back if Path(p).exists()]
            bad = [c for c in checks if not c["ok"]]
            what = "; ".join(_nice(c["what"]) for c in checks) if all(s["do"] in ("setting", "startup") for s in done) and done else \
                self._describe(done, full=False) or "; ".join(c["what"] for c in checks[:3])
            outs.append(f"Undone ('{b['said'][:60]}'): {what or 'nothing to reverse'}. Checked: {len(checks) - len(bad)}/{len(checks)} OK." +
                        (" Couldn't put back: " + "; ".join(f"{_name(s)} ({e})" for s, e in errors[:4]) + "." if errors else ""))
        self._cache = {}
        return " ".join(outs)

    def redo(self):
        while self.state.get("redo"):
            n = self.state["redo"].pop()
            b = next((x for x in self.state["journal"] if x["n"] == n), None)
            if b and b["undone"] is True:
                b["undone"] = "redone"  # done again as a new entry; this one stays in the history
                return self._run(b["steps"], b["said"] + " (again)", redo=True)
        return "Nothing to redo."

    def _short(self, b):
        """One line for the history: what a batch did."""
        st = b["steps"]
        if all(s["do"] in ("setting", "startup") for s in st):
            return "; ".join(_nice(c["what"]) for c in b["checks"])
        made = Counter(s["do"] for s in st)
        names = lambda k: ", ".join(Path(str(s.get("dst") or s.get("src") or "")).name for s in st if s["do"] == k)  # noqa: E731
        bits = [self._describe(st, full=False)] if made.keys() & {"move", "copy", "trash", "restore"} else []
        if made["image"]:
            im = [s for s in st if s["do"] == "image"]
            how = f"resized to {im[0]['width']} wide" if im[0].get("width") else "made smaller" if im[0].get("height") else f"converted to {str(im[0].get('format')).upper()}"
            bits.append(f"{_n(len(im), 'picture')} {how}")
        if made["office_pdf"]:
            bits.append(f"{_n(made['office_pdf'], 'PDF')} made from " + ", ".join(Path(s["src"]).name for s in st if s["do"] == "office_pdf"))
        if made["pdf_merge"]:
            bits.append("merged into " + names("pdf_merge"))
        if made["audio"]:
            bits.append("the sound saved from " + ", ".join(Path(s["src"]).name for s in st if s["do"] == "audio"))
        if made["zip"]:
            bits.append("zipped into " + names("zip"))
        if made["unzip"]:
            bits.append("unzipped " + ", ".join(Path(s["src"]).name for s in st if s["do"] == "unzip"))
        if made["mkdir"] and not bits:
            bits.append("made the folder " + names("mkdir"))
        return "; ".join(b_ for b_ in bits if b_) or "; ".join(c["what"] for c in b["checks"][:3] if not c.get("count"))

    def history(self):
        js = self.state["journal"]
        if not js:
            return "Nothing changed yet."
        flag = {True: " (undone)", "partly": " (partly undone)", "redone": " (undone, then done again)"}
        head = f"({len(js) - 20} earlier changes not shown)\n" if len(js) > 20 else ""
        return head + "\n".join(f"{b['n']}. {b['when'][11:16]} '{b['said'][:50]}': {self._short(b)}{flag.get(b['undone'], '')}" for b in js[-20:])
