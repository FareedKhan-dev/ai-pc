"""The programs the AI PC chat drives, each through its own conversation, which keeps its own rules: checks at every step,
'yes' before anything others will see, versions and undo. An adapter starts that conversation with the right files,
passes a message, says whether it waits for a yes, and lists the files it made (so the next program can be handed them).

  LANES["photo"].open([photo])    lane.say(session, "make it brighter", files)    lane.pending(session)    lane.results(session)
"""
import re
import shutil
from pathlib import Path

from ai_pc.assistant.artifacts import EXT, kind_of
from ai_pc.core.config import ROOT

DELIVER = set(EXT)
_EXTS = "|".join(sorted({e[1:] for e in DELIVER}, key=len, reverse=True))
PATHS = re.compile(r"(?:[A-Za-z]:\\|(?<![\w\\/])(?:out|media)[\\/])[^\r\n\"'<>|*?]*?\.(?:" + _EXTS + r")(?![\w])", re.I)
NEW_DOC = re.compile(r"\b(?:write|make|create|draft|prepare|generate|build|design|type)\b.*\b(?:report|letter|application|assignment|cv|resume|essay|"
                     r"notice|memo|proposal|quotation|presentation|slides?|deck|spreadsheet|workbook|excel|sheet|document|doc|agenda|minutes|"
                     r"timetable|marks? ?sheet|budget|brochure|handout)\b", re.I)


def files_in(value, base=None, depth=0):
    """Existing result files named anywhere inside a value of a program's state (strings, lists, dicts)."""
    out = []
    if depth > 6:
        return out
    if isinstance(value, str):
        if len(value) < 500 and re.search(r"\.[A-Za-z0-9]{1,6}$", value):
            p = Path(value) if Path(value).is_absolute() else (Path(base) / value if base else None)
            if p is not None and p.suffix.lower() in DELIVER and p.is_file():
                out.append(str(p.resolve()))
    elif isinstance(value, dict):
        for v in value.values():
            out += files_in(v, base, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out += files_in(v, base, depth + 1)
    return out


def files_said(reply):
    """Existing files a reply names: a program's own words for what it made."""
    out = []
    for m in PATHS.finditer(reply or ""):
        s = m.group(0).strip()
        p = Path(s) if re.match(r"[A-Za-z]:\\", s) else ROOT / s
        if p.is_file():
            out.append(str(p.resolve()))
    return out


def dedupe(paths):
    seen, out = set(), []
    for p in paths:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


class Lane:
    key = label = blurb = ""
    examples = ()
    works_on = ()   # kinds the program's work is about: a new file of these kinds starts a new conversation about it
    needs_file = False

    def __init__(self, chat):
        self.chat = chat  # the AI PC chat: planner, options, where test folders go

    def progress(self, *a, **_k):
        """A program's progress line, shown live by a front end that asks for it (the command bar); else nothing."""
        note = self.chat.options.get("progress")
        if note and a:
            try:
                note(" ".join(str(x) for x in a))
            except Exception:  # noqa: BLE001 - showing progress never breaks the work
                pass

    @property
    def planner(self):
        return self.chat.planner

    def opt(self, name, default=None):
        return (self.chat.options.get(self.key) or {}).get(name, default)

    def chats_dir(self):
        root = self.chat.options.get("chats_root")
        return Path(root) / self.key if root else None

    def subject(self, files):
        return [f for f in files if kind_of(f) in self.works_on]

    def open(self, files):
        raise NotImplementedError

    def say(self, s, message, files):
        return s.say(message)

    def fresh(self, s, files):
        """A new conversation is needed when new files of the kind this program works on arrive."""
        return s is None or bool(self.subject(files))

    def add(self, s, files):
        """Give an open conversation more files ({name: path} lists that its rules look names up in)."""
        st = getattr(s, "state", None)
        if isinstance(st, dict) and isinstance(st.get("files"), dict):
            for f in files:
                st["files"][Path(f).name.lower()] = str(Path(f).resolve())
            if files and "last_file" in st:
                st["last_file"] = str(Path(files[-1]).resolve())
            return True
        return False

    def pending(self, s):
        st = getattr(s, "state", None)
        return bool(isinstance(st, dict) and st.get("pending"))

    def reopen(self, info):
        """The conversation saved under info["id"], when the program can load one (else a new one starts when needed)."""
        import importlib
        mod, name = getattr(self, "module", ""), getattr(self, "cls_name", "")
        if not (mod and name and info and info.get("id")):
            return None
        cls = getattr(importlib.import_module(mod, "ai_pc"), name)
        if not hasattr(cls, "load"):
            return None
        kw = {"planner": self.planner}
        if self.chats_dir():
            kw["chats_dir"] = self.chats_dir()
        try:
            return cls.load(info["id"], **kw)
        except Exception:  # noqa: BLE001 - a missing or old chat: start afresh
            return None

    def results(self, s):
        """The files the conversation's current version and its saved exports are made of."""
        st = getattr(s, "state", None)
        if not isinstance(st, dict):
            return []
        base = st.get("folder")
        out = []
        vs, cur = st.get("versions"), st.get("cur")
        if isinstance(vs, list) and isinstance(cur, int) and 0 <= cur < len(vs) and isinstance(vs[cur], dict):
            out += files_in({k: v for k, v in vs[cur].items() if k not in ("checks", "steps", "said", "ops", "timeline", "spec", "info")}, base)
        for e in st.get("exports") or []:
            out += files_in(e, base)
        return dedupe(out)


# ---------------------------------------------------------------- the video agent (CapCut / JianYing)
class VideoSession:
    def __init__(self, files):
        self.files, self.draft, self.conv, self.export, self.state = list(files), None, None, None, {}


def to_media(files):
    """The video agent works on files inside media/: copies of the others go to media/aipc."""
    out, media = [], (ROOT / "media").resolve()
    for f in files:
        p = Path(f).resolve()
        if media in p.parents:
            out.append(str(p))
            continue
        dst = media / "aipc" / p.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_size != p.stat().st_size:
            shutil.copy2(p, dst)
        out.append(str(dst))
    return out


class VideoLane(Lane):
    key, label = "video", "Video editing (CapCut / JianYing)"
    blurb = "edits videos: effects, filters, transitions, slow motion, text, music, captions, reels and montages from clips; changes, undo, export"
    examples = ("add a glow effect to my video", "make a reel from these clips with music", "make the text bigger", "undo")
    works_on = ("video",)
    needs_file = True

    def open(self, files):
        return VideoSession(self.subject(files) + [f for f in files if kind_of(f) in ("image", "audio")])

    def fresh(self, s, files):
        return s is None or bool(self.subject(files))

    def reopen(self, info):
        if not (info and info.get("draft")):
            return None
        s = VideoSession([])
        s.draft, s.export = info["draft"], info.get("export")
        return s

    def say(self, s, message, files):
        if s.draft is None:
            media = [f for f in s.files if kind_of(f) in ("video", "image", "audio")]
            if not any(kind_of(f) == "video" for f in media) and not any(kind_of(f) == "image" for f in media):
                return "Which video? Send it (or name it) and say what to do."
            from ai_pc.video.studio import Studio
            sess = Studio(planner=self.planner, log=self.progress, export=True).new(message, to_media(media))
            s.draft = (sess.get("map") or {}).get("draft")
            exp = sess.get("export") or {}
            s.export = exp.get("path") if exp.get("ok") else None
            rep = sess.get("report") or {}
            res = rep.get("results") or []
            ok = sum(1 for r in res if r.get("status") == "pass")
            return (f"Edited: {s.export}" if s.export else "The edit is planned but the video could not be exported") + \
                (f" ({ok} of {len(res)} checks passed)" if res else "") + ". Ask for changes, or 'undo'."
        if s.conv is None:
            from ai_pc.video.conversation import Conversation
            s.conv = Conversation.latest(s.draft, planner=self.planner, log=self.progress, export=True) or \
                Conversation.start(s.draft, planner=self.planner, log=self.progress, export=True)
            s.state = s.conv.state
        extra = [f for f in files if kind_of(f) in ("image", "audio", "video")]
        reply = s.conv.say(message, files=to_media(extra)) if extra else s.conv.say(message)
        exp = s.conv.version.get("export")
        if exp and Path(exp).exists():
            s.export = exp
        return reply

    def pending(self, s):
        return bool(s.conv is not None and s.conv.state.get("pending"))

    def results(self, s):
        return [s.export] if s.export and Path(s.export).exists() else []


# ---------------------------------------------------------------- Office: Word, PowerPoint, Excel, PDF
class OfficeSession:
    def __init__(self):
        self.chat, self.made = None, []

    @property
    def state(self):
        return self.chat.state if self.chat is not None else {}


class OfficeLane(Lane):
    key, label = "office", "Word, PowerPoint, Excel and PDF"
    blurb = ("writes Word documents (reports, letters, applications, assignments, CVs), PowerPoint decks and Excel workbooks from words; "
             "edits an existing .docx/.pptx/.xlsx by conversation; several files together; PDFs packed, compressed, split, watermarked")
    examples = ("write a 3 page report on solar energy in Lahore", "make a 10 slide presentation on our sales", "make the title blue")
    works_on = ("document", "slides", "sheet", "pdf")

    def open(self, files):
        return OfficeSession()

    def fresh(self, s, files):
        return s is None or bool([f for f in files if Path(f).suffix.lower() in (".docx", ".pptx", ".xlsx", ".xlsm", ".pdf")])

    def _edit_chat(self, path):
        from ai_pc.office.bookchat import BookChat
        from ai_pc.office.deckchat import DeckChat
        from ai_pc.office.docchat import DocChat
        cls = {".docx": DocChat, ".pptx": DeckChat, ".xlsx": BookChat, ".xlsm": BookChat}[Path(path).suffix.lower()]
        kw = {"chats_dir": self.chats_dir()} if self.chats_dir() else {}
        return cls.start(path, planner=self.planner, **kw)

    def say(self, s, message, files):
        office = [f for f in files if Path(f).suffix.lower() in (".docx", ".pptx", ".xlsx", ".xlsm")]
        pdfs = [f for f in files if Path(f).suffix.lower() == ".pdf"]
        if NEW_DOC.search(message) or (s.chat is None and not office and not pdfs):
            return self._new(s, message, files)
        if pdfs or len(office) >= 2:
            from ai_pc.office.projectchat import ProjectChat
            s.chat = ProjectChat.start(office + pdfs, planner=self.planner, log=self.progress, **({"projects_dir": self.chats_dir()} if self.chats_dir() else {}))
            return s.chat.say(message)
        if office:
            s.chat = self._edit_chat(office[0])
            return s.chat.say(message)
        return s.chat.say(message)

    def _new(self, s, message, files):
        """A new Word document, deck or workbook from words (files sent are its material: data, pictures, a report to build from)."""
        from ai_pc.office.studio import DocStudio
        sess = DocStudio(planner=self.planner, log=self.progress).new(message, list(files))
        main = sess.get("pptx") or sess.get("xlsx") or sess.get("docx")
        s.made = dedupe([sess.get(k) for k in ("pptx", "xlsx", "docx", "pdf") if sess.get(k) and Path(sess[k]).exists()])
        if not main:
            return "The document could not be made."
        s.chat = self._edit_chat(main)  # follow-ups ("make the title bigger") edit what was just made
        return f"Made {main}" + (f" and its PDF {sess['pdf']}" if sess.get("pdf") else "") + ". Ask for changes, or 'undo'."

    def results(self, s):
        return dedupe(s.made + super().results(s))


# ---------------------------------------------------------------- the conversations that start the same way
class SimpleLane(Lane):
    """A program whose conversation starts with (planner, files) and has no single subject file."""
    module = cls_name = ""
    takes_files, has_log = True, True

    def open(self, files):
        import importlib
        cls = getattr(importlib.import_module(self.module, "ai_pc"), self.cls_name)
        kw = {"planner": self.planner}
        if self.chats_dir():
            kw["chats_dir"] = self.chats_dir()
        if self.takes_files:
            kw["files"] = list(files)
        if self.has_log:
            kw["log"] = self.progress  # its progress lines are not the chat's reply
        kw.update(self.extra())
        return cls.start(**kw)

    def extra(self):
        return {}

    def fresh(self, s, files):
        return s is None


class SubjectLane(Lane):
    """A program whose conversation is about one file (a photo, a sound, a video to convert)."""
    module = cls_name = ""
    src_kw = "src"
    extra_kw = "files"

    def open(self, files):
        import importlib
        cls = getattr(importlib.import_module(self.module, "ai_pc"), self.cls_name)
        subject = self.subject(files)
        kw = {"planner": self.planner, self.src_kw: subject[0] if subject else None}
        if self.extra_kw:
            kw[self.extra_kw] = [f for f in files if f not in subject[:1]]
        if self.chats_dir():
            kw["chats_dir"] = self.chats_dir()
        kw["log"] = self.progress
        return cls.start(**kw)


class PhotoLane(SubjectLane):
    key, label = "photo", "Photos"
    blurb = ("edits a photo: fix, brighten, crop, straighten, remove or change the background, passport photos, blur faces, text, watermark, "
             "filters, sizes for Instagram/WhatsApp; versions and undo")
    examples = ("make my photo brighter", "remove the background", "make a passport photo")
    works_on = ("image",)
    needs_file = True
    module, cls_name, extra_kw = ".photo.photochat", "PhotoChat", "extra"

    def open(self, files):
        if not self.subject(files):
            return None
        return super().open(files)


class SoundLane(SubjectLane):
    key, label = "sound", "Sound"
    blurb = ("cleans voice recordings (noise, hum, pauses, ums), loudness for YouTube/podcasts, word-by-word captions on talking videos, "
             "music under a voice, voice-overs read by Windows voices, transcripts")
    examples = ("clean up this recording", "add word by word captions", "voice-over: Welcome to Khan Electronics")
    works_on = ("audio", "video")
    module, cls_name = ".sound.soundchat", "SoundChat"


class ConvertLane(SubjectLane):
    key, label = "convert", "Converter"
    blurb = ("converts, compresses and fixes videos and sound: smaller files (under N MB), formats, WhatsApp/email ready, trims, GIFs, "
             "extract the audio, rotate, records the screen")
    examples = ("make it under 10 MB", "will it play on WhatsApp?", "make a gif of 0:05 to 0:08")
    works_on = ("video", "audio")
    module, cls_name = ".convert.convchat", "ConvertChat"


class WindowsLane(SimpleLane):
    key, label = "windows", "Windows files and settings"
    blurb = ("your folders (Downloads, Documents, Desktop, Pictures): find, clean up, sort, move, rename, duplicates, big files; "
             "wallpaper, dark mode, night light, power, start-up apps; everything undoable")
    examples = ("clean up my downloads", "find my CV and move it to documents", "turn on dark mode")
    module, cls_name, takes_files = ".windows.winchat", "WinChat", False


class CadLane(SimpleLane):
    key, label = "cad", "House plans and parts (CAD)"
    blurb = "house plans from marla/kanal and rooms (DXF for AutoCAD, PDF, PNG), plates, flanges and brackets with holes, laser-cut files"
    examples = ("a 5 marla house with 3 bedrooms", "a 200 x 100 plate with 4 holes", "export the pdf")
    module, cls_name, takes_files = ".cad.cadchat", "CadChat", False


class DesignLane(SimpleLane):
    key, label = "design", "Design"
    blurb = "visiting cards, Instagram posts and stories, YouTube thumbnails, flyers, posters, certificates, banners, invitations"
    examples = ("a visiting card for Ahmed Khan", "an instagram post for our Eid sale", "a youtube thumbnail with my photo")
    module, cls_name = ".design.designchat", "DesignChat"


class HubLane(SimpleLane):
    key, label = "hub", "Work apps"
    blurb = ("Slack, Microsoft Teams, Outlook mail and calendar, OneDrive, Gmail, Google Calendar and Drive, Trello, Asana, Notion, Jira, "
             "HubSpot, Zoom, Telegram, WhatsApp, Figma, Canva: post, send files, read, email, meetings, tasks; anything others see waits for a yes")
    examples = ("send it to slack #general", "what's new in #general?", "email it to ali@khan.pk", "brief me")
    module, cls_name = ".hub.hubchat", "HubChat"
    has_log = False

    def extra(self):
        return {k: v for k, v in (("transports", self.opt("transports")), ("creds", self.opt("creds"))) if v is not None}


class SocialLane(SimpleLane):
    key, label = "social", "Social media"
    blurb = "posts and schedules on Facebook, Instagram, Threads, YouTube, TikTok, LinkedIn and X; captions, hashtags, comments, results"
    examples = ("post it on instagram with a caption", "upload it to youtube as private", "schedule it for 6 pm on facebook")
    module, cls_name = ".social.socialchat", "SocialChat"
    has_log = False

    def extra(self):
        return {k: v for k, v in (("platforms", self.opt("platforms")), ("store", self.opt("store")), ("db", self.opt("db"))) if v is not None}


class CodeLane(SimpleLane):
    key, label = "coding", "Coding"
    blurb = "writes, runs and fixes programs and websites from words (Python, HTML/CSS/JS), versions and undo, opens them in VS Code; Figma/Canva designs to code"
    examples = ("make a python script that counts words in a file", "build a one-page website for my shop", "fix this error")
    module, cls_name, takes_files = ".coding.codechat", "CodeChat", False
    has_log = False

    def results(self, s):
        p = (getattr(s, "state", {}) or {}).get("project")
        return [str(Path(p).resolve())] if p and Path(p).exists() else []


class ThreeLane(SimpleLane):
    key, label = "three", "3D (Blender)"
    blurb = "3D houses from plans, 3D titles and intros, product mockups (a logo on a mug, box, laptop), 3D files viewed, checked and converted"
    examples = ("a 3D model of a 7 marla house", "a 3D intro for Khan Electronics in gold", "put my logo on a mug")
    module, cls_name = ".three.threechat", "ThreeChat"


class AccountsLane(SimpleLane):
    key, label = "accounts", "Accounts and invoices"
    blurb = "invoices, payments, who owes money, profit, sales tax; PDF invoices; sync to QuickBooks, TallyPrime, Xero, Zoho Books; FBR Digital Invoicing"
    examples = ("invoice for Ali Traders: 2 LED TV at 85,000 each, 18% tax", "who owes me money?", "send everything to tally")
    module, cls_name, takes_files = ".accounts.accountschat", "AccountsChat", False
    has_log = False

    def extra(self):
        return {k: v for k, v in (("db", self.opt("db")), ("connectors", self.opt("connectors"))) if v is not None}

    def results(self, s):
        return []  # its replies name the invoices it makes


class AppsLane(Lane):
    key, label = "apps", "Programs"
    blurb = ("88 more programs by name: Photoshop, Illustrator, After Effects, Premiere, Lightroom, GIMP, Krita, RawTherapee, Shotcut, HandBrake, "
             "Audacity, MuseScore, LMMS, OBS, Blender-free 3D (FreeCAD, OpenSCAD, PrusaSlicer), KiCad, Arduino, MATLAB, R, LaTeX, draw.io, Visio, "
             "LibreOffice, Calibre, Anki, QGIS, MS Project, Revit, Unity, Godot, Docker, Postman, Jupyter, VS Code, Python, Node, PHP, C++, Go, "
             "Rust, .NET, Java, Android, Flutter, PostgreSQL, MySQL, MongoDB, Power BI, 7-Zip, Obsidian, AutoHotkey, KeePassXC, Google Docs/Forms, "
             "GitHub, Spotify, Salesforce, Shopify, WooCommerce, Daraz, WordPress, Odoo, Mailchimp, Brevo, Dropbox, Discord, OCR, PC care, "
             "diagrams, citations, quizzes, ebooks, printing, maps, notes, backups, contacts, QR codes, music, calendar invites")
    examples = ("gimp make photo.jpg black and white", "7zip pack my reports with password X", "print it")

    def open(self, files):
        from ai_pc.apps.appschat import AppsChat
        kw = {"files": list(files)}
        if self.chats_dir():
            kw["chats_dir"] = self.chats_dir()
        if self.opt("extra") is not None:
            kw["extra"] = self.opt("extra")
        return AppsChat.start(**kw)

    def fresh(self, s, files):
        return s is None

    def results(self, s):
        return []  # its replies name what it made


LANE_CLASSES = [VideoLane, OfficeLane, WindowsLane, PhotoLane, CadLane, SoundLane, DesignLane, HubLane, SocialLane, CodeLane, ConvertLane,
                ThreeLane, AccountsLane, AppsLane]
