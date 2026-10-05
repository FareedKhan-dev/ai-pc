"""What the AI PC chat has seen and made: every file the person sent and every file a program produced, with its kind,
so words like 'it', 'this video', 'the pdf', 'the original', 'the edited one' or a file's name resolve to a real file
that can be handed to the next program ("add an effect to my video" ... "send it to Slack").

  arts = Artifacts(state_list)
  arts.add("media/me.mp4", "you")            arts.add("out/video/x.mp4", "video", note="glow effect")
  arts.resolve("send it to slack")  -> [the edited video]      arts.resolve("the original video") -> [me.mp4]
"""
import re
import time
from pathlib import Path

KINDS = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".3gp", ".mpg", ".mpeg"},
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".svg", ".psd", ".xcf", ".kra", ".ora", ".ico"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".wma", ".aiff", ".aif"},
    "pdf": {".pdf"},
    "document": {".docx", ".doc", ".odt", ".rtf", ".md", ".txt", ".tex", ".html", ".htm", ".epub", ".azw3", ".mobi"},
    "sheet": {".xlsx", ".xlsm", ".xls", ".csv", ".ods", ".tsv"},
    "slides": {".pptx", ".ppt", ".odp"},
    "drawing": {".dxf", ".dwg", ".vsdx", ".drawio"},
    "model": {".glb", ".gltf", ".stl", ".obj", ".fbx", ".3mf", ".step", ".stp", ".blend", ".ifc", ".fcstd", ".scad", ".gcode"},
    "archive": {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"},
    "subtitles": {".srt", ".vtt", ".ass"},
    "music": {".mid", ".midi", ".musicxml", ".mxl", ".mscz", ".mmp"},
    "app": {".apk", ".exe", ".jar", ".msi"},
    "code": {".py", ".js", ".ts", ".php", ".go", ".rs", ".cs", ".java", ".cpp", ".c", ".dart", ".ipynb", ".sql"},
    "data": {".json", ".xml", ".kdbx", ".ics", ".vcf", ".kml", ".gpx", ".geojson", ".bib", ".ris", ".apkg", ".ahk", ".pbip", ".mpp"},
}
EXT = {e: k for k, exts in KINDS.items() for e in exts}
# what people call each kind
WORDS = {
    "video": r"videos?|clips?|reels?|movies?|footage|vlogs?|shorts?",
    "image": r"photos?|pictures?|pics?|images?|thumbnails?|posters?|screenshots?|logos?|(?:visiting |business )?cards?|flyers?|banners?|"
             r"stor(?:y|ies)|certificates?|selfies?|wallpapers?|artwork|mock-?ups?|renders?",
    "audio": r"audios?|sounds?|songs?|music|voice(?:[- ]?(?:notes?|overs?|recordings?))?|podcasts?|mp3s?|tracks?|recordings?",
    "pdf": r"pdfs?|invoices?|receipts?|quotations?|quotes?",
    "document": r"docs?|documents?|reports?|letters?|cvs?|resumes?|essays?|assignments?|applications?|word files?|ebooks?|notes?|proposals?",
    "sheet": r"sheets?|spreadsheets?|excel(?: files?)?|workbooks?|csvs?|tables?",
    "slides": r"slides?|decks?|presentations?|ppts?|powerpoints?",
    "drawing": r"(?:house |floor )?plans?|drawings?|dxfs?|blueprints?|diagrams?|flowcharts?|naksha",
    "model": r"3d(?: models?)?|models?|stls?|meshes|3d files?",
    "archive": r"zips?|archives?|7z|backups?",
    "subtitles": r"subtitles?|captions?|srts?",
    "music": r"melod(?:y|ies)|midi|sheet music|scores?",
    "app": r"apks?|installers?|exes?",
    "code": r"code|scripts?|programs?|projects?|websites?|apps?",
}
RANK = {"video": 9, "image": 8, "audio": 8, "pdf": 7, "slides": 6, "sheet": 6, "document": 5, "drawing": 5, "model": 5, "music": 4,
        "archive": 4, "app": 4, "subtitles": 3, "folder": 3, "code": 2, "data": 2, "file": 1}
PREFER = {"pdf": [".pdf"], "drawing": [".pdf", ".png", ".dxf"], "model": [".glb", ".stl", ".png", ".mp4"]}  # the kind word's best file
ORIGINAL = re.compile(r"\b(?:original|my own|the one i (?:sent|gave|shared|uploaded)|unedited|raw)\b", re.I)
MADE = re.compile(r"\b(?:edited|new|result|output|final|finished|latest|converted|compressed|cleaned|fixed|you made|that you made|made|done)\b", re.I)
POINTER = re.compile(r"\b(?:it|this|that|them|these|those|the (?:file|result|output|same|one|last one|latest))\b", re.I)


def kind_of(path):
    p = Path(path)
    return "folder" if p.is_dir() else EXT.get(p.suffix.lower(), "file")


def kind_words(text):
    """The kinds a message names ('the video' -> ['video'])."""
    out = []
    for k, pat in WORDS.items():
        if re.search(rf"\b(?:{pat})\b", text, re.I):
            out.append(k)
    return out


class Artifacts:
    """A list of {"id", "path", "name", "kind", "from", "turn", "note", "time"} kept in the chat's state."""

    def __init__(self, items=None):
        self.items = items if items is not None else []

    def add(self, path, origin, turn=0, note=""):
        p = Path(path).resolve()
        for a in self.items:
            if a["path"].lower() == str(p).lower():  # the same file again: it is now the latest
                a.update(turn=turn, time=time.time(), note=note or a.get("note", ""), **({"from": origin} if origin != "you" else {}))
                return a
        a = {"id": len(self.items) + 1, "path": str(p), "name": p.name, "kind": kind_of(p), "from": origin, "turn": turn, "note": note,
             "time": time.time()}
        self.items.append(a)
        return a

    def alive(self):
        return [a for a in self.items if Path(a["path"]).exists()]

    def latest(self, kinds=None, origin=None, made=None):
        """The newest artifact (optionally of these kinds, from this origin, or only made by programs / only the person's)."""
        pool = [a for a in self.alive() if (not kinds or a["kind"] in kinds) and (origin is None or a["from"] == origin)
                and (made is None or (a["from"] != "you") == made)]
        return max(pool, key=lambda a: (a["turn"], a["time"])) if pool else None

    def named(self, text):
        low = text.lower()
        hits = []
        for a in self.alive():
            name, stem = a["name"].lower(), Path(a["name"]).stem.lower()
            if name in low:
                hits.append(a)
            elif len(stem) >= 4 and not any(re.fullmatch(pat, stem) for pat in WORDS.values()) and \
                    re.search(rf"(?<![\w-]){re.escape(stem)}(?![\w-])", low):
                hits.append(a)
        best = {}
        for a in hits:  # the same name in several formats: the most shareable one
            k = Path(a["name"]).stem.lower() if a["name"].lower() not in low else a["name"].lower()
            if k not in best or RANK.get(a["kind"], 0) > RANK.get(best[k]["kind"], 0):
                best[k] = a
        return list(best.values())

    def resolve(self, text, want=None):
        """The artifacts a message points at. want: kinds the receiving program works on (used when the words name none)."""
        hits = self.named(text)
        if hits:
            return hits
        kinds = kind_words(text)
        original = bool(ORIGINAL.search(text))
        if kinds:
            for k in kinds:
                prefer = PREFER.get(k)
                if original:
                    a = self.latest([k], origin="you")
                else:
                    a = self.latest([k], made=True) if MADE.search(text) else None
                    a = a or self.latest([k])
                if a and prefer:  # 'the plan' -> its PDF when one was made with it
                    sib = [b for b in self.alive() if b["turn"] == a["turn"] and b["from"] == a["from"] and Path(b["path"]).suffix.lower() in prefer]
                    if sib:
                        a = min(sib, key=lambda b: prefer.index(Path(b["path"]).suffix.lower()))
                if a:
                    return [a]
        if POINTER.search(text) or want:
            a = self.latest(want, origin="you" if original else None) if want else None
            a = a or (self.latest(origin="you") if original else self.latest())
            return [a] if a else []
        return []

    def describe(self, limit=12):
        """A short list for the model and for 'what have you made?'."""
        return [f"#{a['id']} {a['name']} ({a['kind']}, {'you sent it' if a['from'] == 'you' else 'made by ' + a['from']})"
                for a in sorted(self.alive(), key=lambda a: (a["turn"], a["time"]))[-limit:]]
