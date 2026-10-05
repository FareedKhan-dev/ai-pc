"""Files and folders, done by code and checked on the disk.

  g = Guard([known("downloads"), known("documents")])          what may be changed (system folders and this project never)
  idx = scan(g.check(known("downloads")))                        {"root", "files": [record], "bytes", "truncated"}
  hits = find(idx["files"], kind="pdf", larger=10e6, sort="largest")
  steps = plan_organize(idx, by="kind")                          a plan: [{"do": "mkdir"|"move"|..., "src", "dst"}]
  res = execute(steps, g)                                        done, each step checked; res["undo"] reverses it exactly

Nothing is deleted for good: removing sends to the Recycle Bin, and undo restores from it.
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from ..config import ROOT as PROJECT

KINDS = {
    "photo": {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".raw", ".cr2", ".nef", ".arw", ".dng", ".jfif"},
    "video": {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".m4v", ".3gp", ".flv", ".mts"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".opus", ".amr"},
    "document": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages", ".inp"},
    "pdf": {".pdf"},
    "spreadsheet": {".xls", ".xlsx", ".xlsm", ".csv", ".ods", ".numbers"},
    "presentation": {".ppt", ".pptx", ".odp", ".key"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"},
    "installer": {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".apk", ".dmg", ".iso"},
    "code": {".py", ".js", ".ts", ".html", ".htm", ".css", ".json", ".xml", ".java", ".c", ".cpp", ".cs", ".ipynb", ".sql", ".php", ".sh", ".bat", ".ps1", ".yml", ".yaml"},
    "font": {".ttf", ".otf", ".woff", ".woff2"},
    "design": {".psd", ".ai", ".fig", ".sketch", ".xd", ".cdr", ".indd", ".svg", ".eps"},
    "ebook": {".epub", ".mobi", ".azw3"},
    "torrent": {".torrent"},
    "model3d": {".glb", ".gltf", ".fbx", ".obj", ".blend", ".stl", ".3ds", ".dae", ".usdz", ".3mf", ".ply"},
}
PARTIAL = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".!ut", ".tmp"}
FOLDER = {"photo": "Photos", "video": "Videos", "audio": "Music", "document": "Documents", "pdf": "PDFs", "spreadsheet": "Spreadsheets",
          "presentation": "Presentations", "archive": "Archives", "installer": "Installers", "code": "Code", "font": "Fonts", "design": "Design",
          "ebook": "Books", "torrent": "Torrents", "model3d": "3D models", "partial": "Unfinished downloads", "other": "Other"}
SKIP_DIRS = {"$recycle.bin", "system volume information", ".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".vs", "appdata"}


class FsError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ where
def known(name):
    """A known folder by its everyday name (downloads, documents, desktop, pictures, videos, music, onedrive)."""
    from win32com.shell import shell, shellcon
    ids = {"downloads": "FOLDERID_Downloads", "documents": "FOLDERID_Documents", "desktop": "FOLDERID_Desktop", "pictures": "FOLDERID_Pictures",
           "photos": "FOLDERID_Pictures", "videos": "FOLDERID_Videos", "music": "FOLDERID_Music"}
    n = str(name).lower().strip()
    if n == "onedrive":
        od = os.environ.get("OneDrive")
        return Path(od) if od else None
    if n in ids:
        return Path(shell.SHGetKnownFolderPath(getattr(shellcon, ids[n])))
    return None


def known_folders():
    out = {}
    for n in ("downloads", "documents", "desktop", "pictures", "videos", "music", "onedrive"):
        try:
            p = known(n)
            if p and p.exists():
                out[n] = p
        except Exception:  # noqa: BLE001
            continue
    return out


def _protected():
    env = os.environ
    ps = [env.get("SystemRoot", r"C:\Windows"), env.get("ProgramFiles", r"C:\Program Files"), env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          env.get("ProgramData", r"C:\ProgramData"), str(Path.home() / "AppData"), str(PROJECT)]
    return [Path(p).resolve() for p in ps if p]


class Guard:
    """What may be changed: inside the given roots (the user's own folders, or a test folder), never inside Windows,
    Program Files, AppData or this project (a test folder inside the project is allowed when it is a root itself)."""

    def __init__(self, roots):
        self.roots = [Path(r).resolve() for r in roots if r]
        self.protected = _protected()

    def _inside(self, p, base):
        return p == base or base in p.parents

    def check(self, p, must_exist=False):
        p = Path(p).resolve()
        root = next((r for r in self.roots if self._inside(p, r)), None)
        if root is None:
            raise FsError(f"{p} is outside the folders I may change ({', '.join(str(r) for r in self.roots)})")
        for q in self.protected:
            if self._inside(p, q) and not self._inside(root, q):  # a protected folder, unless the root itself was given inside it (a test folder)
                raise FsError(f"{p} is inside {q}, which I never change")
        if must_exist and not p.exists():
            raise FsError(f"{p} does not exist")
        return p

    def is_root(self, p):
        return Path(p).resolve() in self.roots


# ------------------------------------------------------------------------------------------------ what is there
def kind_of(name):
    ext = Path(str(name)).suffix.lower()
    if ext in PARTIAL:
        return "partial"
    for k, exts in KINDS.items():
        if ext in exts:
            return k
    return "other"


def _iso(t):
    return dt.datetime.fromtimestamp(t).isoformat(timespec="seconds")


def record(path, root=None):
    p = Path(path)
    st = p.stat()
    born = getattr(st, "st_birthtime", st.st_ctime)
    if os.path.isdir(p):
        return {"path": str(p), "name": p.name, "stem": p.name, "ext": "", "kind": "folder", "size": 0, "dir": True, "mtime": _iso(st.st_mtime),
                "ctime": _iso(born), "folder": str(p.parent), "rel": ""}
    return {"path": str(p), "name": p.name, "stem": p.stem, "ext": p.suffix.lower(), "kind": kind_of(p.name), "size": st.st_size,
            "mtime": _iso(st.st_mtime), "ctime": _iso(born), "folder": str(p.parent),
            "rel": str(p.parent.relative_to(root)) if root and Path(root) in p.parents else ""}


def scan(root, recursive=True, limit=150000, budget_s=20, hidden=False):
    """Every file under a folder (system and tool folders skipped), within a time budget."""
    root = Path(root)
    files, dirs, t0, truncated = [], [], time.perf_counter(), False
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if hidden or (d.lower() not in SKIP_DIRS and not d.startswith("."))]
        if Path(dp) != root:
            dirs.append(dp)
        for f in fn:
            if not hidden and (f.startswith("~$") or f.lower() in ("desktop.ini", "thumbs.db")):
                continue
            try:
                files.append(record(Path(dp) / f, root))
            except OSError:
                continue
            if len(files) >= limit:
                truncated = True
                break
        if truncated or not recursive or time.perf_counter() - t0 > budget_s:
            truncated = truncated or (recursive and time.perf_counter() - t0 > budget_s)
            if not recursive:
                dirs = [str(root / d) for d in dn]
            break
    return {"root": str(root), "files": files, "dirs": dirs, "bytes": sum(f["size"] for f in files), "truncated": truncated,
            "recursive": recursive}


NAME_DATES = [  # dates phones, cameras, WhatsApp and Windows write into file names
    re.compile(r"(?<!\d)(20\d\d|19\d\d)(\d\d)(\d\d)[_-](\d\d)(\d\d)(\d\d)"),                    # IMG_20240812_101500, PXL_20240812_101500123
    re.compile(r"(?<!\d)(20\d\d|19\d\d)-(\d\d)-(\d\d) at (\d\d?)\.(\d\d)\.(\d\d)"),              # WhatsApp Image 2024-08-25 at 20.11.03
    re.compile(r"(?<!\d)(20\d\d|19\d\d)-(\d\d)-(\d\d)[ _](\d\d)[.:]?(\d\d)[.:]?(\d\d)(?!\d)"),     # Screenshot 2026-09-12 104455
    re.compile(r"(?<!\d)(20\d\d|19\d\d)[-_.](\d\d)[-_.](\d\d)(?!\d)"),                               # a date alone: report 2024-08-01
]


def name_date(name):
    """The date (and time) written into a file's name, else None."""
    for rx in NAME_DATES:
        m = rx.search(str(name))
        if m:
            try:
                return dt.datetime(*[int(g) for g in m.groups()]).isoformat(timespec="seconds")
            except ValueError:
                continue
    return None


def taken(path):
    """When a photo was taken: its EXIF date, else the date in its name (WhatsApp strips EXIF but names the file by
    it), else None."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        if v:
            return dt.datetime.strptime(str(v).strip()[:19], "%Y:%m:%d %H:%M:%S").isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        pass
    return name_date(Path(path).name)


def in_progress(rec, hours=2):
    """An unfinished download that changed in the last hours may still be downloading: it is left alone."""
    return rec["kind"] == "partial" and (dt.datetime.now() - date_of(rec)).total_seconds() < hours * 3600


def entries(dirs):
    """How many files and folders sit directly in these folders (desktop.ini and thumbs.db aside)."""
    n = 0
    for d in dirs:
        try:
            n += sum(1 for e in os.scandir(d) if e.name.lower() not in ("desktop.ini", "thumbs.db"))
        except OSError:
            continue
    return n


def media_seconds(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return None


def sha1(path, first=None):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        if first:
            h.update(f.read(first))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def human(n):
    n = float(n or 0)
    for u in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "bytes" else f"{n:.1f} {u}"
        n /= 1024


def date_of(rec, field="mtime"):
    v = rec.get(field) or rec.get("mtime")
    return dt.datetime.fromisoformat(v) if v else None


# ------------------------------------------------------------------------------------------------ finding
def find(files, kind=None, exts=None, name=None, words=None, larger=None, smaller=None, since=None, until=None, field="mtime", folder=None,
         sort=None, limit=None):
    """Files by kind, extension, name (words, a pattern), size, date (modified, created or taken), folder; sorted."""
    out = []
    kinds = {kind} if isinstance(kind, str) else set(kind or [])
    for f in files:
        if kinds and f["kind"] not in kinds:
            continue
        if exts and f["ext"] not in {e if e.startswith(".") else "." + e for e in exts}:
            continue
        low = f["name"].lower()
        if name and not re.search(name, f["name"], re.I):
            continue
        if words and not all(re.search(r"(?<![a-z0-9])" + re.escape(w.lower()), re.sub(r"[_\-.]+", " ", low)) for w in words):
            continue
        if larger is not None and f["size"] <= larger:
            continue
        if smaller is not None and f["size"] >= smaller:
            continue
        if folder and Path(folder).resolve() != Path(f["folder"]).resolve() and Path(folder).resolve() not in Path(f["folder"]).resolve().parents:
            continue
        if since or until:
            d = date_of(f, field)
            if d is None or (since and d < since) or (until and d >= until):
                continue
        out.append(f)
    if sort == "largest":
        out.sort(key=lambda f: -f["size"])
    elif sort == "smallest":
        out.sort(key=lambda f: f["size"])
    elif sort == "newest":
        out.sort(key=lambda f: date_of(f, field) or dt.datetime.min, reverse=True)
    elif sort == "oldest":
        out.sort(key=lambda f: date_of(f, field) or dt.datetime.max)
    elif sort == "name":
        out.sort(key=lambda f: f["name"].lower())
    return out[:limit] if limit else out


def summary(idx):
    """What a folder holds, kind by kind (count and size), its biggest files."""
    by = {}
    for f in idx["files"]:
        b = by.setdefault(f["kind"], [0, 0])
        b[0] += 1
        b[1] += f["size"]
    return sorted(((k, n, s) for k, (n, s) in by.items()), key=lambda x: -x[2])


# ------------------------------------------------------------------------------------------------ plans
def unique(dst, taken_names=None):
    """A free name: 'report.pdf' -> 'report (2).pdf' when the name is taken (on the disk or earlier in the plan)."""
    dst = Path(dst)
    taken_names = taken_names if taken_names is not None else set()
    if not dst.exists() and str(dst).lower() not in taken_names:
        taken_names.add(str(dst).lower())
        return dst
    k = 2
    while True:
        cand = dst.with_name(f"{dst.stem} ({k}){dst.suffix}")
        if not cand.exists() and str(cand).lower() not in taken_names:
            taken_names.add(str(cand).lower())
            return cand
        k += 1


def plan_move(files, dest, copy=False):
    dest = Path(dest)
    steps, names = [], set()
    if not dest.exists():
        steps.append({"do": "mkdir", "dst": str(dest)})
    for f in files:
        src = Path(f["path"] if isinstance(f, dict) else f)
        if src.parent.resolve() == dest.resolve() and not copy:
            continue
        steps.append({"do": "copy" if copy else "move", "src": str(src), "dst": str(unique(dest / src.name, names))})
    return steps


def plan_organize(idx, by="kind", files=None, field="mtime"):
    """Loose files of a folder (top level only; folders stay as they are) into sub-folders by kind ('Photos', 'PDFs')
    or by month ('2026-10 October')."""
    root = Path(idx["root"])
    pool = files if files is not None else [f for f in idx["files"] if Path(f["folder"]).resolve() == root.resolve()]
    steps, names, made = [], set(), set()
    for f in sorted(pool, key=lambda x: x["name"].lower()):
        if by == "date":
            d = dt.datetime.fromisoformat(taken(f["path"]) or f.get(field) or f["mtime"]) if f["kind"] == "photo" and field == "taken" else date_of(f, field)
            sub = d.strftime("%Y-%m %B") if d else "Undated"
        elif by == "ext":
            sub = (f["ext"].lstrip(".").upper() or "No extension") + " files"
        else:
            sub = FOLDER.get(f["kind"], "Other")
        dest = root / sub
        if not dest.exists() and str(dest).lower() not in made:
            steps.append({"do": "mkdir", "dst": str(dest)})
            made.add(str(dest).lower())
        steps.append({"do": "move", "src": f["path"], "dst": str(unique(dest / f["name"], names)), "group": sub})
    return steps


TOKENS = re.compile(r"\{(name|stem|ext|n(?::0?(\d+))?|date(?::([^}]+))?|taken(?::([^}]+))?|created(?::([^}]+))?|folder)\}")


def plan_rename(files, pattern=None, replace=None, case=None, start=1):
    """New names from a pattern ('{taken:%Y-%m-%d} {n:03}', 'Lahore trip {n:03}'), a replacement (old -> new) or a
    case ('lower', 'title'); the extension stays."""
    steps, names = [], set()
    tk = {f["path"]: taken(f["path"]) or f["mtime"] for f in files} if pattern and "taken" in pattern else {}
    order = sorted(files, key=lambda x: (tk[x["path"]], bool(COPYISH.search(Path(x["name"]).stem)), x["name"].lower())) if tk else \
        sorted(files, key=lambda x: x["name"].lower())
    for i, f in enumerate(order):
        src = Path(f["path"])
        stem = src.stem
        if pattern:
            def tok(m):
                t = m.group(1)
                if t == "name" or t == "stem":
                    return stem
                if t == "ext":
                    return src.suffix.lstrip(".")
                if t == "folder":
                    return src.parent.name
                if t.startswith("n"):
                    return str(start + i).zfill(int(m.group(2) or 1))
                if t.startswith("taken"):
                    d = tk.get(f["path"]) or taken(f["path"]) or f["mtime"]
                    return dt.datetime.fromisoformat(d).strftime(m.group(4) or "%Y-%m-%d")
                if t.startswith("created"):
                    return dt.datetime.fromisoformat(f["ctime"]).strftime(m.group(5) or "%Y-%m-%d")
                return dt.datetime.fromisoformat(f["mtime"]).strftime(m.group(3) or "%Y-%m-%d")
            new = TOKENS.sub(tok, pattern)
        else:
            new = stem
        if replace:
            a, b = replace
            new = re.sub(re.escape(a), b, new, flags=re.I)
        if case == "lower":
            new = new.lower()
        elif case == "upper":
            new = new.upper()
        elif case == "title":
            new = re.sub(r"[A-Za-z]+", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), new)
        elif case == "underscores":
            new = re.sub(r"\s+", "_", new)
        elif case == "spaces":
            new = re.sub(r"[_]+", " ", new)
        new = re.sub(r'[<>:"/\\|?*]+', "-", new).strip(" .") or stem
        dst = src.with_name(new + src.suffix)
        if dst.name == src.name:
            continue
        steps.append({"do": "move", "src": str(src), "dst": str(unique(dst, names))})
    return steps


def duplicates(files):
    """Groups of files with the same content (same size, then the same first 64 KB, then the same SHA-1)."""
    by_size = {}
    for f in files:
        if f["size"] > 0:
            by_size.setdefault(f["size"], []).append(f)
    groups = []
    for same in by_size.values():
        if len(same) < 2:
            continue
        heads = {}
        for f in same:
            try:
                heads.setdefault(sha1(f["path"], first=65536), []).append(f)
            except OSError:
                continue
        for h in heads.values():
            if len(h) < 2:
                continue
            full = {}
            for f in h:
                try:
                    full.setdefault(sha1(f["path"]), []).append(f)
                except OSError:
                    continue
            groups += [g for g in full.values() if len(g) > 1]
    return groups


def _keeper(group):
    """Which copy stays: the one without ' (1)' / 'Copy of' / ' - Copy' in its name, then the oldest."""
    def score(f):
        n = f["name"].lower()
        copyish = bool(re.search(r"\(\d+\)|copy of|\s-\scopy|_copy\b|\scopy\b", n))
        return (copyish, f["mtime"], len(n))
    return min(group, key=score)


COPYISH = re.compile(r"\s*\(\d+\)$|^copy of\s+|\s+-\s+copy(?:\s*\(\d+\))?$|_copy$|\s+copy$", re.I)


def _base(stem):
    return COPYISH.sub("", COPYISH.sub("", stem)).strip().lower()


def plan_dedupe(files, copies_only=False):
    """Repeated files to the Recycle Bin, one of each kept. copies_only: only the obvious copies ('x (1).jpg', 'Copy of
    x', the same name in another folder), not files that merely have the same content under another name."""
    steps = []
    for g in duplicates(files):
        keep = _keeper(g)
        for f in g:
            if f is keep:
                continue
            if copies_only and _base(Path(f["name"]).stem) != _base(Path(keep["name"]).stem):
                continue
            steps.append({"do": "trash", "src": f["path"], "why": f"the same as {keep['name']}", "keep": keep["path"], "cat": "copy", "size": f["size"]})
    return steps


def top_level(idx):
    """The loose files of a scanned folder (not those inside its sub-folders)."""
    root = Path(idx["root"]).resolve()
    return [f for f in idx["files"] if Path(f["folder"]).resolve() == root]


def plan_cleanup(idx, old_days=30, notes=None):
    """What a downloads folder no longer needs: unfinished downloads (not one still downloading), installers older than
    a month, copies ('x (1).pdf' next to 'x.pdf'), empty folders. Only the folder's own loose files and its empty
    sub-folders: what is inside a sub-folder belongs to it (an unzipped app's .exe is the app, an asset pack's files
    repeat on purpose). Everything goes to the Recycle Bin. notes (a list) gets what was left alone and why."""
    now = dt.datetime.now()
    steps = []
    notes = notes if notes is not None else []
    root = Path(idx["root"]).resolve()
    top = top_level(idx)
    for f in top:
        if f["kind"] == "partial":
            if in_progress(f):
                notes.append(f"{f['name']} (may still be downloading)")
            else:
                steps.append({"do": "trash", "src": f["path"], "why": "an unfinished download", "cat": "partial", "size": f["size"]})
        elif f["kind"] == "installer":
            age = (now - date_of(f)).days
            if age > old_days:
                steps.append({"do": "trash", "src": f["path"], "why": f"an installer from {date_of(f):%d %b %Y}", "cat": "installer", "size": f["size"]})
            else:
                notes.append(f"{f['name']} (an installer from {'today' if age < 1 else f'{age} day(s) ago'}, maybe still needed)")
    gone = {s["src"] for s in steps}
    steps += [s for s in plan_dedupe([f for f in top if f["path"] not in gone and not in_progress(f)], copies_only=True)]
    for d in sorted(idx.get("dirs") or [], key=lambda x: x.lower()):
        try:
            if Path(d).parent.resolve() == root and not any(Path(d).iterdir()):
                steps.append({"do": "trash", "src": d, "why": "an empty folder", "cat": "empty", "size": 0})
        except OSError:
            continue
    return steps


def plan_zip(files, dst):
    return [{"do": "zip", "srcs": [f["path"] if isinstance(f, dict) else str(f) for f in files], "dst": str(unique(Path(dst)))}]


def plan_unzip(archive, dst=None):
    a = Path(archive)
    return [{"do": "unzip", "src": str(a), "dst": str(unique(Path(dst) if dst else a.with_suffix("")))}]


# ------------------------------------------------------------------------------------------------ doing, each step checked
def recycle(paths):
    """To the Recycle Bin (undo restores them): the Windows shell's own delete, with undo allowed."""
    from win32com.shell import shell, shellcon
    flags = shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI | shellcon.FOF_WANTNUKEWARNING
    paths = [str(Path(p).resolve()) for p in paths]
    if not paths:
        return True
    rc, aborted = shell.SHFileOperation((0, shellcon.FO_DELETE, "\0".join(paths), None, flags, None, None))
    return rc == 0 and not aborted


def _key(p):
    return os.path.normcase(os.path.abspath(str(p)))


def _bin_folder():
    from win32com.shell import shell, shellcon
    pidl = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_BITBUCKET)
    return pidl, shell.SHGetDesktopFolder().BindToObject(pidl, None, shell.IID_IShellFolder)


def bin_items(binf=None):
    """What the Recycle Bin holds, newest deletion first: [{"name", "orig", "deleted", "size", "dir", "pidl"}], read from
    each item's $I record (where it was, when it was deleted, its size)."""
    from win32com.shell import shellcon
    binf = binf or _bin_folder()[1]
    out = []
    for pidl in binf.EnumObjects(0, shellcon.SHCONTF_FOLDERS | shellcon.SHCONTF_NONFOLDERS | shellcon.SHCONTF_INCLUDEHIDDEN):
        try:
            rpath = Path(binf.GetDisplayNameOf(pidl, shellcon.SHGDN_FORPARSING))  # ...\$Recycle.Bin\<sid>\$Rxxxx.ext: its $I twin says where it was
            raw = rpath.with_name("$I" + rpath.name[2:]).read_bytes()
            if int.from_bytes(raw[:8], "little") >= 2:
                n = int.from_bytes(raw[24:28], "little")
                orig = raw[28:28 + 2 * n].decode("utf-16-le").rstrip("\0")
            else:  # the Windows Vista-8 layout: a fixed 520-byte path
                orig = raw[24:24 + 520].decode("utf-16-le").split("\0")[0]
            size = int.from_bytes(raw[8:16], "little")
            ft = int.from_bytes(raw[16:24], "little")
            deleted = dt.datetime.fromtimestamp((ft - 116444736000000000) / 1e7)
        except Exception:  # noqa: BLE001
            continue
        out.append({"name": Path(orig).name, "orig": orig, "deleted": deleted.isoformat(timespec="seconds"), "size": size, "dir": rpath.is_dir(),
                    "pidl": pidl})
    out.sort(key=lambda x: x["deleted"], reverse=True)
    return out


def restore(paths):
    """Items back from the Recycle Bin to where they were, all in one shell file operation (as dragging them out of
    the bin does; ~0.1 s an item, where the 'restore' verb takes ~0.9 s each). When a path was deleted more than once,
    the latest one comes back; nothing is restored over a file that is there now. Returns {path: restored?}."""
    import pythoncom
    from win32com.shell import shell, shellcon
    want = {_key(p): p for p in paths}
    out = {p: False for p in paths}
    if not paths:
        return out
    pidl_bin, binf = _bin_folder()
    picked = {}
    for it in bin_items(binf):  # newest first
        k = _key(it["orig"])
        if k in want and k not in picked and not os.path.lexists(it["orig"]):
            picked[k] = it
    if not picked:
        return out
    fo = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None, pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
    fo.SetOperationFlags(shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI | shellcon.FOF_NOCONFIRMMKDIR)
    for it in picked.values():
        orig = Path(it["orig"])
        orig.parent.mkdir(parents=True, exist_ok=True)  # the folder it was in may have gone too
        item = shell.SHCreateItemWithParent(pidl_bin, binf, it["pidl"], shell.IID_IShellItem)
        dest = shell.SHCreateItemFromParsingName(str(orig.parent), None, shell.IID_IShellItem)
        fo.MoveItem(item, dest, orig.name, None)
    fo.PerformOperations()
    for k, it in picked.items():
        out[want[k]] = Path(it["orig"]).exists()
    return out


def _check(cond, what):
    return {"ok": bool(cond), "what": what}


def run_step(s, guard, server=None):
    """One step done and checked; returns (result, inverse step for undo)."""
    k = s["do"]
    if k == "mkdir":
        dst = guard.check(s["dst"])
        existed = dst.exists()
        dst.mkdir(parents=True, exist_ok=True)
        return _check(dst.is_dir(), f"folder {dst.name}"), (None if existed else {"do": "rmdir", "dst": str(dst)})
    if k == "rmdir":
        dst = guard.check(s["dst"])
        if dst.exists() and not any(dst.iterdir()):
            dst.rmdir()
        return _check(not dst.exists() or any(dst.iterdir()), f"folder {dst.name} removed"), None
    if k == "move":
        src, dst = guard.check(s["src"], must_exist=True), guard.check(s["dst"])
        size = src.stat().st_size if src.is_file() else None
        if dst.exists():
            dst = unique(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        ok = dst.exists() and not src.exists() and (size is None or dst.stat().st_size == size)
        return _check(ok, f"{src.name} -> {dst.relative_to(dst.parent.parent) if dst.parent.parent != dst.parent else dst.name}"), \
            {"do": "move", "src": str(dst), "dst": str(src)}
    if k == "copy":
        src, dst = guard.check(s["src"], must_exist=True), guard.check(s["dst"])
        if dst.exists():
            dst = unique(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dst))
            ok = dst.is_dir()
        else:
            shutil.copy2(str(src), str(dst))
            ok = dst.stat().st_size == src.stat().st_size and (src.stat().st_size > 200e6 or sha1(src) == sha1(dst))
        return _check(ok, f"{src.name} copied (identical)"), {"do": "trash", "src": str(dst)}
    if k == "trash":
        src = guard.check(s["src"], must_exist=True)
        ok = recycle([src]) and not src.exists()
        return _check(ok, f"{src.name} to the Recycle Bin"), {"do": "restore", "src": str(src)}
    if k == "restore":
        src = guard.check(s["src"])
        got = restore([str(src)])
        return _check(all(got.values()), f"{src.name} back from the Recycle Bin"), {"do": "trash", "src": str(src)}
    if k == "zip":
        srcs = [guard.check(p, must_exist=True) for p in s["srcs"]]
        dst = guard.check(s["dst"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            for p in srcs:
                if p.is_dir():
                    for q in p.rglob("*"):
                        if q.is_file():
                            z.write(q, q.relative_to(p.parent))
                            n += 1
                else:
                    z.write(p, p.name)
                    n += 1
        with zipfile.ZipFile(dst) as z:
            ok = z.testzip() is None and len(z.namelist()) == n
        return _check(ok, f"{dst.name}: {n} file(s), {human(dst.stat().st_size)}, every file reads back"), {"do": "trash", "src": str(dst)}
    if k == "unzip":
        src, dst = guard.check(s["src"], must_exist=True), guard.check(s["dst"])
        dst.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            for n in z.namelist():  # nothing may land outside the folder (a name like ..\..\x)
                if not (dst / n).resolve().is_relative_to(dst.resolve()):
                    raise FsError(f"{src.name} holds a file that would land outside its folder ({n}); not unzipped")
            z.extractall(dst)
        ok = all((dst / n).exists() for n in names)
        return _check(ok, f"{src.name} unzipped: {len(names)} file(s) in {dst.name}"), {"do": "trash", "src": str(dst)}
    if k == "image":
        return _image(s, guard)
    if k == "office_pdf":
        return _office_pdf(s, guard, server)
    if k == "pdf_merge":
        return _pdf_merge(s, guard)
    if k == "audio":
        return _audio(s, guard)
    raise FsError(f"no step '{k}'")


def _image(s, guard):
    """A photo converted, resized or both (EXIF kept): checked by opening the result."""
    from PIL import Image, ImageOps
    src = guard.check(s["src"], must_exist=True)
    fmt = (s.get("format") or src.suffix.lstrip(".")).lower().replace("jpg", "jpeg")
    ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp", "gif": ".gif", "tiff": ".tif"}.get(fmt, src.suffix)
    dst = guard.check(s.get("dst") or src.with_suffix(ext))
    if dst.exists() and dst.resolve() != src.resolve():
        dst = unique(dst)
    with Image.open(src) as im:
        exif = im.info.get("exif")
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        tw, th = s.get("width"), s.get("height")
        if tw or th:
            r = min((tw or 10 ** 9) / w, (th or 10 ** 9) / h)
            if r < 1 or s.get("upscale"):
                im = im.resize((max(1, round(w * r)), max(1, round(h * r))), Image.LANCZOS)
        if fmt == "jpeg" and im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        kw = {"quality": int(s.get("quality") or 88)} if fmt in ("jpeg", "webp") else {}
        if exif and fmt in ("jpeg", "webp"):
            kw["exif"] = exif
        im.save(dst, fmt.upper(), **kw)
        size = im.size
    with Image.open(dst) as chk:
        ok = chk.size == size and chk.format.lower() == fmt
    inv = {"do": "trash", "src": str(dst)}
    return _check(ok, f"{dst.name}: {size[0]}x{size[1]} {fmt.upper()}, {human(dst.stat().st_size)}"), inv


def _office_pdf(s, guard, server):
    from ..office import render as RN
    src = guard.check(s["src"], must_exist=True)
    dst = guard.check(s.get("dst") or src.with_suffix(".pdf"))
    if dst.exists():
        dst = unique(dst)
    app = {".doc": "word", ".docx": "word", ".rtf": "word", ".odt": "word", ".ppt": "powerpoint", ".pptx": "powerpoint", ".xls": "excel", ".xlsx": "excel",
           ".xlsm": "excel"}.get(src.suffix.lower())
    if not app:
        raise FsError(f"{src.name} is not a Word, PowerPoint or Excel file")
    tmp = dst.with_name(f"_aipc_{src.name}")
    shutil.copy2(src, tmp)  # Office opens a copy: the original is never touched
    try:
        job = {"app": app, "src": str(tmp.resolve()), "pdf": str(dst.resolve())}
        r = server.run(job) if server is not None else RN.office(job)
    finally:
        tmp.unlink(missing_ok=True)
    pages = 0
    if dst.exists():
        from pypdf import PdfReader
        pages = len(PdfReader(str(dst)).pages)
    return _check(r.get("ok") and pages > 0, f"{dst.name}: {pages} page(s)"), {"do": "trash", "src": str(dst)}


def _pdf_merge(s, guard):
    import logging

    from pypdf import PdfReader, PdfWriter
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # 'Annotation sizes differ' and such: harmless
    srcs = [guard.check(p, must_exist=True) for p in s["srcs"]]
    dst = guard.check(s["dst"])
    if dst.exists():
        dst = unique(dst)
    w = PdfWriter()
    want = 0
    for p in srcs:
        w.append(str(p), outline_item=p.stem)
        want += len(PdfReader(str(p)).pages)
    with open(dst, "wb") as f:
        w.write(f)
    got = len(PdfReader(str(dst)).pages)
    return _check(got == want, f"{dst.name}: {got} pages from {len(srcs)} PDF(s), a bookmark each"), {"do": "trash", "src": str(dst)}


def _audio(s, guard):
    src = guard.check(s["src"], must_exist=True)
    dst = guard.check(s.get("dst") or src.with_suffix(".mp3"))
    if dst.exists():
        dst = unique(dst)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-acodec", "libmp3lame", "-q:a", "2", str(dst)], capture_output=True, text=True,
                       timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    a, b = media_seconds(src), media_seconds(dst) if dst.exists() else None
    ok = r.returncode == 0 and b is not None and (a is None or abs(a - b) < 1.0)
    return _check(ok, f"{dst.name}: {b or 0:.1f} s of sound" + (f" (the video is {a:.1f} s)" if a else "")), {"do": "trash", "src": str(dst)}


def _why(e):
    if isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32, 33):
        return "it is open in another app or not allowed"
    return str(e)


def _bin_group(kind, group, guard):
    """Several Recycle Bin steps in one shell call (one call for 50 files instead of 50), each checked after."""
    ok_steps = []
    for s in group:
        try:
            ok_steps.append((s, guard.check(s["src"], must_exist=kind == "trash")))
        except FsError as e:
            yield s, None, None, str(e)
    if not ok_steps:
        return
    if kind == "trash":
        recycle([p for _, p in ok_steps])
        for s, p in ok_steps:
            if not p.exists():
                yield s, _check(True, f"{p.name} to the Recycle Bin"), {"do": "restore", "src": str(p)}, None
            else:
                yield s, None, None, f"{p.name} is still there ({_why(PermissionError())})"
    else:
        there = [(s, p) for s, p in ok_steps if os.path.lexists(p)]
        for s, p in there:
            yield s, None, None, f"something called {p.name} is there now, so it stays in the Recycle Bin"
        ok_steps = [(s, p) for s, p in ok_steps if not os.path.lexists(p)]
        got = restore([str(p) for _, p in ok_steps])
        for s, p in ok_steps:
            if got.get(str(p)):
                yield s, _check(True, f"{p.name} back from the Recycle Bin"), {"do": "trash", "src": str(p)}, None
            else:
                yield s, None, None, f"{p.name} is no longer in the Recycle Bin"


def run_batch(steps, guard, server=None):
    """Steps done in order, each checked; Recycle Bin steps in a row go in one shell call. Yields (step, result,
    inverse, error) for every step: a step that fails (a file open in another app, gone meanwhile) is reported and
    the others still run."""
    i = 0
    while i < len(steps):
        s = steps[i]
        if s["do"] in ("trash", "restore") and "src" in s:
            j = i
            while j < len(steps) and steps[j]["do"] == s["do"] and "src" in steps[j]:
                j += 1
            yield from _bin_group(s["do"], steps[i:j], guard)
            i = j
            continue
        try:
            res, inv = run_step(s, guard, server)
            yield s, res, inv, None
        except (FsError, OSError, zipfile.BadZipFile) as e:
            yield s, None, None, _why(e)
        i += 1


def execute(steps, guard, server=None, log=None):
    """A plan done step by step, each checked. Returns {"done", "checks", "undo", "errors", "error"} where "undo" is the
    inverse plan (run it with execute to put everything back) and "errors" the steps that could not be done."""
    done, checks, inverse, errors = [], [], [], []
    for s, res, inv, err in run_batch(steps, guard, server):
        if err:
            errors.append(f"{s['do']} {Path(str(s.get('src') or s.get('dst') or '')).name}: {err}")
            continue
        done.append(s)
        checks.append(res)
        if inv:
            inverse.insert(0, inv)
        if log:
            log(res["what"])
    return {"done": done, "checks": checks, "undo": inverse, "errors": errors, "error": errors[0] if errors else None}
