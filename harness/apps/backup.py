"""Backups that are checked: a folder copied into a dated zip with a list of every file and its SHA-256 inside, then the
zip read back and every file's hash compared; an old backup can be verified again or restored into a new folder
(never over the original). Zip archives too: files zipped, archives listed and unzipped safely (no path may escape
the folder it is unzipped into).

  'back up D:\\Shop\\Accounts to E:\\Backups'   'verify E:\\Backups\\Accounts_2026-10-04.zip'   'unzip photos.zip'   'zip D:\\Shop\\Invoices'
"""
import datetime as dt
import hashlib
import json
import re
import zipfile
from pathlib import Path

NAME, LABEL = "backup", "Backups and zip archives (checked with SHA-256)"
EXAMPLES = ["back up D:\\Shop\\Accounts to E:\\Backups", "verify E:\\Backups\\Accounts_2026-10-04.zip", "unzip photos.zip"]
MANIFEST = "BACKUP-MANIFEST.json"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def backup(folder, dest_dir, name=None):
    src = Path(folder)
    if not src.is_dir():
        raise ValueError(f"{src} is not a folder")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name or src.name}_{dt.datetime.now():%Y-%m-%d_%H%M}.zip"
    files = sorted(p for p in src.rglob("*") if p.is_file())
    manifest = {"source": str(src), "made": dt.datetime.now().isoformat(timespec="seconds"), "files": {}}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for p in files:
            rel = p.relative_to(src).as_posix()
            manifest["files"][rel] = {"sha256": sha(p), "bytes": p.stat().st_size}
            z.write(p, rel)
        z.writestr(MANIFEST, json.dumps(manifest, indent=1))
    return dest, manifest


def verify(zpath):
    """[(file, ok)] by reading every file back out of the zip and hashing it."""
    out = []
    with zipfile.ZipFile(zpath) as z:
        man = json.loads(z.read(MANIFEST)) if MANIFEST in z.namelist() else None
        for info in z.infolist():
            if info.filename == MANIFEST or info.is_dir():
                continue
            h = hashlib.sha256()
            with z.open(info) as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            out.append((info.filename, man is None or (man["files"].get(info.filename) or {}).get("sha256") == h.hexdigest()))
        if man:
            missing = set(man["files"]) - {i.filename for i in z.infolist()}
            out += [(m, False) for m in missing]
    return out


def safe_unzip(zpath, dest):
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if dest not in target.parents and target != dest:
                raise ValueError(f"{info.filename} would land outside {dest}: refused (a zip-slip trick)")
        z.extractall(dest)
        return [i.filename for i in z.infolist() if not i.is_dir()]


def parse(text, ctx):
    from .appschat import find_file
    m = re.match(r"^\s*back\s*up\s+(.+?)\s+(?:to|into|on)\s+(.+?)\s*$", text, re.I)
    if m:
        return {"op": "backup", "folder": m.group(1).strip(" '\""), "to": m.group(2).strip(" '\"")}
    m = re.match(r"^\s*(?:verify|check)\s+(?:the\s+)?(?:backup\s+)?(.+\.zip)\s*$", text, re.I)
    if m:
        return {"op": "verify", "file": find_file(text, ctx, {".zip"}) or m.group(1).strip(" '\"")}
    m = re.match(r"^\s*(?:unzip|extract)\s+(.+?)(?:\s+(?:to|into)\s+(.+))?\s*$", text, re.I)
    if m and m.group(1).lower().endswith(".zip"):
        return {"op": "unzip", "file": find_file(m.group(1), ctx, {".zip"}) or m.group(1).strip(" '\""), "to": (m.group(2) or "").strip(" '\"") or None}
    m = re.match(r"^\s*zip\s+(?:up\s+)?(.+?)\s*$", text, re.I)
    if m and Path(m.group(1).strip(" '\"")).is_dir():
        return {"op": "zip", "folder": m.group(1).strip(" '\"")}
    return None


def run(op, ctx):
    out = Path(ctx["out"])
    if op["op"] in ("backup", "zip"):
        dest, man = backup(op["folder"], op.get("to") or out / "zips")
        res = verify(dest)
        bad = [f for f, ok in res if not ok]
        size = sum(v["bytes"] for v in man["files"].values())
        return (f"{'Backed up' if op['op'] == 'backup' else 'Zipped'} {len(man['files'])} files ({size / 1e6:.1f} MB) into {dest} ({dest.stat().st_size / 1e6:.1f} MB); " +
                ("read back and every file's SHA-256 matches." if not bad and len(res) == len(man["files"]) else f"NOT right: {bad[:5]}"))
    if op["op"] == "verify":
        res = verify(op["file"])
        bad = [f for f, ok in res if not ok]
        return f"{Path(op['file']).name}: {len(res)} files, " + ("all match their SHA-256: the backup is good." if not bad else f"{len(bad)} DAMAGED or missing: {bad[:5]}")
    dest = Path(op.get("to") or out / "unzipped" / Path(op["file"]).stem)
    files = safe_unzip(op["file"], dest)
    return f"Unzipped {len(files)} files into {dest}."
