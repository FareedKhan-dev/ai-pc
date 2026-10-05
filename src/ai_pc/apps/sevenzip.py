"""7-Zip (tools/7zip, from 7-Zip's signed MSI): files and folders packed into .7z (best compression; with a password they
are AES-256 encrypted, file names too) or .zip, and any archive 7-Zip reads (.7z, .zip, .rar, .tar, .gz, .iso ...) tested or
unpacked. Checked by 7-Zip itself: the archive tests clean, it lists every file packed with the same sizes, and a
password-protected one cannot even be listed without the password. The password is never written into a reply or a file.

  '7zip compress report.docx and data.xlsx with password Lahore123'   '7zip pack C:\\work\\photos'   '7zip extract backup.7z password Lahore123'
"""

import re
import shutil
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "sevenzip", "7-Zip: .7z/.zip archives (AES-256 with a password), any archive tested or unpacked, all checked by 7-Zip"
EXAMPLES = ["7zip compress report.docx with password Lahore123", "7zip pack C:\\work\\photos", "7zip extract backup.7z"]
SEVEN = ROOT / "tools" / "7zip" / "Files" / "7-Zip" / "7z.exe"
ARCHIVES = {".7z", ".zip", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso", ".cab", ".wim", ".zst"}


def z(*args, cwd=None, timeout=1800):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run([str(SEVEN), *map(str, args)], timeout=timeout, cwd=str(cwd) if cwd else None)
    return rc == 0 and not timed_out, out + err


def pw_args(password):
    return [f"-p{password}"] if password else []  # a bare -p would make 7-Zip ask for one


def listing(archive, password=None):
    """{path: size} of the files in an archive, or None if 7-Zip cannot list it."""
    ok, out = z("l", "-slt", "-ba", *pw_args(password), archive)
    if not ok:
        return None
    files = {}
    for block in out.replace("\r\n", "\n").split("\n\n"):
        path = re.search(r"^Path = (.+)$", block, re.M)
        size = re.search(r"^Size = (\d+)$", block, re.M)
        folder = re.search(r"^Folder = \+$", block, re.M) or re.search(r"^Attributes = D", block, re.M)
        if path and size and not folder:
            files[path.group(1).strip().replace("\\", "/")] = int(size.group(1))
    return files


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\b7-?zip\b|\b\.7z\b|\b7z\b", c):
        return None
    pw = re.search(r"\bpassword(?:\s+is)?\s*[:=]?\s*(\S+)", text, re.I)
    password = pw.group(1).strip("'\".,") if pw else None
    archive = find_file(text, ctx, ARCHIVES)
    if archive and re.search(r"\bextract\b|\bunpack\b|\bunzip\b|\bopen\b", c):
        return {"op": "extract", "file": archive, "password": password}
    if archive and re.search(r"\btest\b|\bcheck\b|\bverify\b", c):
        return {"op": "test", "file": archive, "password": password}
    items = [p for p in (ctx.get("files") or {}).values() if Path(p).suffix.lower() not in ARCHIVES or not archive]
    m = re.search(r"([a-z]:\\[^\"<>|?*\n]+)", text, re.I)
    if m:
        cand = Path(re.sub(r"\s+(?:with|password)\b.*$", "", m.group(1).strip(), flags=re.I).rstrip(".,"))
        if cand.exists():
            items = [str(cand)]
    if items and re.search(r"\bcompress\b|\bpack\b|\barchive\b|\bzip\b|\bmake\b", c):
        return {"op": "pack", "items": items, "password": password, "zip": bool(re.search(r"\bas (?:a )?zip\b|\bto zip\b|\.zip\b", c))}
    return None


def run(op, ctx):
    if not SEVEN.exists():
        return "7-Zip is not in tools/7zip."
    out = (Path(ctx["out"]) / "7zip").resolve()
    out.mkdir(parents=True, exist_ok=True)
    pw = op.get("password")
    if op["op"] in ("test", "extract"):
        src = Path(op["file"]).resolve()
        files = listing(src, pw)
        if files is None:
            return f"7-Zip cannot read {src.name}" + (" with that password." if pw else " (it may need a password: add 'password ...').")
        ok_t, log = z("t", *pw_args(pw), src)
        if op["op"] == "test":
            return f"7-Zip tested {src.name}: {len(files)} file(s), {sum(files.values()):,} bytes. " + (
                "Checked: everything is OK." if ok_t else "NOT right: " + log.strip()[-300:]
            )
        dest = out / src.stem
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        ok_x, log_x = z("x", "-y", *pw_args(pw), f"-o{dest}", src)
        got = {str(p.relative_to(dest)).replace("\\", "/"): p.stat().st_size for p in dest.rglob("*") if p.is_file()}
        checks = [
            ("7-Zip tests the archive clean", ok_t),
            (f"all {len(files)} file(s) unpacked with the sizes the archive lists", ok_x and got == files),
        ]
        bad = [w for w, good in checks if not good]
        return f"Unpacked {src.name} into {dest}. " + (
            "Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + log_x.strip()[-200:]
        )
    items = [Path(p).resolve() for p in op["items"]]
    stem = items[0].stem if len(items) == 1 else "archive"
    archive = out / f"{stem}.{'zip' if op.get('zip') else '7z'}"
    archive.unlink(missing_ok=True)
    args = ["a", "-tzip" if op.get("zip") else "-t7z", "-mx=9", "-y"]
    if pw:
        args += [f"-p{pw}"] + (["-mem=AES256"] if op.get("zip") else ["-mhe=on"])
    ok_a, log = z(*args, archive, *items)
    want = {}
    for it in items:
        if it.is_dir():
            want.update({str(p.relative_to(it.parent)).replace("\\", "/"): p.stat().st_size for p in it.rglob("*") if p.is_file()})
        else:
            want[it.name] = it.stat().st_size
    files = listing(archive, pw) if archive.exists() else None
    ok_t, _ = z("t", *pw_args(pw), archive) if archive.exists() else (False, "")
    checks = [("7-Zip tests the archive clean", ok_a and ok_t), (f"it holds all {len(want)} file(s) with their sizes", files == want)]
    if pw:
        hidden = listing(archive, "not-the-password") is None if not op.get("zip") else not z("t", "-pnot-the-password", archive)[0]
        checks.append(("without the password it cannot be opened" + ("" if op.get("zip") else ", not even its file names"), hidden))
    bad = [w for w, good in checks if not good]
    size_in, size_out = sum(want.values()), archive.stat().st_size if archive.exists() else 0
    return (
        f"7-Zip made {archive} ({size_out:,} bytes from {size_in:,}, {100 - 100 * size_out / max(1, size_in):.0f}% smaller"
        + (", AES-256 with the password you gave" if pw else "")
        + "). "
        + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + log.strip()[-200:])
    )
