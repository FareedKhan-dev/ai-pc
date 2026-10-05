"""Safe installs: exact wheels from PyPI, checked against PyPI's published SHA-256, unpacked and read before anything runs.

  .venv\\Scripts\\python.exe scripts\\safe_wheels.py fetch tools\\review\\office lxml==6.1.3 pypdf==6.19.0 ...
  .venv\\Scripts\\python.exe scripts\\safe_wheels.py scan tools\\review\\office
  then install offline from exactly those files:
  uv pip install --python .venv\\Scripts\\python.exe --offline --no-index --find-links tools\\review\\office\\wheels <names>

fetch  for each name==version: PyPI's JSON for that release (over HTTPS), the wheel for this Python (the one running it, Windows
       x64) or a pure-Python one; refused if yanked, if there is no wheel (no setup.py ever runs), or if the downloaded
       bytes do not match PyPI's SHA-256. manifest.json records what was fetched.
scan   each wheel unpacked into unpacked/<name>/: every file checked against the wheel's own RECORD hashes; .pth files
       (run at every Python start), executables and native libraries listed; entry points, author, home page,
       licence; Python lines that run programs, open the network, decode or execute code are listed for reading.
Nothing is installed by this tool.
"""

import base64
import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

_V = f"{sys.version_info[0]}{sys.version_info[1]}"  # the Python running this tool: run it with the venv's Python
PY_TAGS = {"py3", "py2.py3", f"cp{_V}", f"py{_V}"}
ABI_TAGS = {"none", "abi3", f"cp{_V}"}
PLAT_TAGS = {"any", "win_amd64"}
RISKY = {
    "runs programs": r"\bsubprocess\b|\bos\.system\(|\bos\.popen\(|\bos\.exec\w*\(|\bos\.spawn\w*\(|\bShellExecute",
    "network": r"\bsocket\b|\burllib\.request\b|\bhttp\.client\b|\brequests\.\w+\(|\burlopen\(|\bhttpx\b|\baiohttp\b",
    "executes code": r"(?<![\w.])eval\(|(?<![\w.])exec\(|\bmarshal\.loads\(|\bcompile\(.*['\"]exec['\"]",
    "decodes blobs": r"\bbase64\.b(?:64|85|32)decode\(|\bzlib\.decompress\(\s*base64",
    "native calls": r"\bctypes\b|\bcffi\b",
    "writes startup hooks": r"\.pth['\"]|sitecustomize|usercustomize",
}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "safe_wheels/1.0 (personal project)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _fits(filename):
    m = re.match(r"^(?P<name>.+?)-(?P<ver>[^-]+)(?:-\d[^-]*)?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$", filename)
    if not m:
        return False
    py = set(m.group("py").split("."))
    return bool((py & PY_TAGS) or m.group("py") in PY_TAGS) and m.group("abi") in ABI_TAGS and any(p in PLAT_TAGS for p in m.group("plat").split("."))


def fetch(folder, specs, pure=False):
    """pure: a pure-Python wheel (none-any) when the release has one, so no native code is installed."""
    folder = Path(folder)
    wheels = folder / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    manifest_p = folder / "manifest.json"
    manifest = json.loads(manifest_p.read_text(encoding="utf-8")) if manifest_p.exists() else {}
    ok = True
    for spec in specs:
        name, _, ver = spec.partition("==")
        if not ver:
            print(f"REFUSED {spec}: give an exact version (name==version)")
            ok = False
            continue
        info = json.loads(_get(f"https://pypi.org/pypi/{name}/{ver}/json"))
        files = [u for u in info["urls"] if u["packagetype"] == "bdist_wheel" and _fits(u["filename"])]
        if not files:
            print(
                f"REFUSED {spec}: no wheel for Python {sys.version_info[0]}.{sys.version_info[1]} / Windows x64 (a source build would run setup code)"
            )
            ok = False
            continue
        if pure:
            u = sorted(files, key=lambda u: ("none-any" not in u["filename"], "win_amd64" not in u["filename"]))[0]
        else:
            u = sorted(files, key=lambda u: ("win_amd64" not in u["filename"], f"cp{_V}" not in u["filename"]))[0]
        if u.get("yanked"):
            print(f"REFUSED {spec}: this release is yanked ({u.get('yanked_reason')})")
            ok = False
            continue
        data = _get(u["url"], timeout=300)
        got = hashlib.sha256(data).hexdigest()
        if got != u["digests"]["sha256"]:
            print(f"REFUSED {spec}: SHA-256 mismatch (PyPI {u['digests']['sha256'][:16]}..., downloaded {got[:16]}...)")
            ok = False
            continue
        (wheels / u["filename"]).write_bytes(data)
        meta = info["info"]
        manifest[name.lower()] = {
            "version": ver,
            "file": u["filename"],
            "sha256": got,
            "size": len(data),
            "url": u["url"],
            "uploaded": u.get("upload_time_iso_8601"),
            "author": meta.get("author") or meta.get("author_email"),
            "home": meta.get("home_page") or (meta.get("project_urls") or {}).get("Homepage") or (meta.get("project_urls") or {}).get("Source"),
            "license": meta.get("license_expression") or meta.get("license"),
        }
        print(f"ok      {u['filename']}  {len(data) / 1e6:.2f} MB  sha256 {got[:16]}... matches PyPI")
    manifest_p.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return ok


def _record_ok(z):
    """Every file in the wheel matches the hash its RECORD lists (RECORD itself has none)."""
    rec = next((n for n in z.namelist() if n.endswith(".dist-info/RECORD")), None)
    if rec is None:
        return False, ["no RECORD"]
    bad = []
    listed = set()
    for row in csv.reader(io.StringIO(z.read(rec).decode("utf-8"))):
        if not row:
            continue
        path, h = row[0], row[1] if len(row) > 1 else ""
        listed.add(path)
        if not h:
            continue
        algo, _, want = h.partition("=")
        got = base64.urlsafe_b64encode(hashlib.new(algo, z.read(path)).digest()).rstrip(b"=").decode()
        if got != want:
            bad.append(path)
    unlisted = [n for n in z.namelist() if n not in listed and not n.endswith("/")]
    return not bad and not unlisted, bad + [f"not in RECORD: {n}" for n in unlisted]


def scan(folder):
    folder = Path(folder)
    out = []
    for whl in sorted((folder / "wheels").glob("*.whl")):
        with zipfile.ZipFile(whl) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            dest = folder / "unpacked" / whl.name[:-4]
            z.extractall(dest)
            rec_ok, rec_bad = _record_ok(z)
            meta_name = next((n for n in names if n.endswith(".dist-info/METADATA")), None)
            meta = z.read(meta_name).decode("utf-8", "replace") if meta_name else ""
            ep_name = next((n for n in names if n.endswith(".dist-info/entry_points.txt")), None)
            entry = z.read(ep_name).decode("utf-8", "replace").strip() if ep_name else ""

            def field(k):
                return [ln.split(":", 1)[1].strip() for ln in meta.splitlines() if ln.lower().startswith(k.lower() + ":")]

            kinds = {}
            for n in names:
                ext = Path(n).suffix.lower() or "(none)"
                kinds[ext] = kinds.get(ext, 0) + 1
            flags = {
                "pth": [n for n in names if n.lower().endswith(".pth")],
                "executables": [n for n in names if Path(n).suffix.lower() in (".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr")],
                "native": [n for n in names if Path(n).suffix.lower() in (".dll", ".pyd", ".so")],
            }
            hits = {k: [] for k in RISKY}
            for n in names:
                if not n.endswith(".py"):
                    continue
                for i, line in enumerate(z.read(n).decode("utf-8", "replace").splitlines(), 1):
                    s = line.strip()
                    if s.startswith("#"):
                        continue
                    for k, rx in RISKY.items():
                        if re.search(rx, line):
                            hits[k].append(f"{n}:{i}: {s[:110]}")
        row = {
            "wheel": whl.name,
            "record_ok": rec_ok,
            "record_problems": rec_bad[:5],
            "files": len(names),
            "kinds": kinds,
            "author": field("Author") + field("Author-email") + field("Maintainer-email"),
            "home": field("Home-page") + field("Project-URL"),
            "license": field("License-Expression") + field("License")[:1],
            "requires": field("Requires-Dist"),
            "entry_points": entry,
            "flags": flags,
            "risky_lines": {k: v for k, v in hits.items() if v},
        }
        out.append(row)
        print(f"\n== {whl.name}: {len(names)} files, RECORD {'ok' if rec_ok else 'PROBLEM ' + str(rec_bad[:3])}")
        print(f"   by {', '.join(row['author'])[:120] or '?'} | licence {', '.join(row['license'])[:60] or '?'}")
        print(f"   home {'; '.join(row['home'])[:200] or '?'}")
        print(f"   needs {', '.join(row['requires'])[:200] or 'nothing'}")
        print(
            f"   .pth {flags['pth'] or 'none'} | executables {flags['executables'] or 'none'} | native libs {len(flags['native'])}"
            + (f" ({', '.join(Path(x).name for x in flags['native'][:6])})" if flags["native"] else "")
        )
        if entry:
            print("   entry points: " + entry.replace("\n", " | ")[:200])
        for k, v in row["risky_lines"].items():
            print(f"   {k}: {len(v)} line(s)")
            for x in v[:4]:
                print(f"      {x}")
    (folder / "scan.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    pure = "--pure" in args
    cmd, folder, *rest = [a for a in args if a != "--pure"]
    if cmd == "fetch":
        sys.exit(0 if fetch(folder, rest, pure=pure) else 1)
    elif cmd == "scan":
        scan(folder)
    else:
        sys.exit("usage: safe_wheels.py fetch <folder> name==version ... | scan <folder>")
