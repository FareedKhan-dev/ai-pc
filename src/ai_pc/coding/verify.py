"""Checks after every change to a project:

  risks(project)         lines that could harm this PC if run (deleting outside the project, running other programs or
                         shell commands, the registry, the network, eval of strings): shown before anything runs
  check(project, run)    every file compiles (Python) or parses (JavaScript); the tests pass (unittest, or npm test);
                         the program runs and exits cleanly; a web page loads in headless Chrome with no console errors;
                         a page made from a design (design/design.json) is measured against the design (for information:
                         changes asked for after it was made are meant to differ)
                         -> [{"ok", "what", "level", "detail"}]
"""
import re
from pathlib import Path

RISKS = {
    "deletes files": r"\bshutil\.rmtree\(|\bos\.(?:remove|unlink|rmdir|removedirs)\(|\.unlink\(|\.rmdir\(|\brm\s+-rf\b|\bdel\s+/[sfq]|\bfs\.(?:rm|rmdir|unlink)(?:Sync)?\(",
    "runs other programs": r"\bsubprocess\b|\bos\.system\(|\bos\.popen\(|\bos\.exec\w*\(|\bos\.spawn\w*\(|\bchild_process\b|\bexecSync\(|\bspawnSync\(|\bShellExecute",
    "uses the network": r"\brequests\.\w+\(|\burllib\.request\b|\bhttp\.client\b|\bsocket\.\w+\(|\bfetch\(\s*['\"]https?://|\baxios\b|\bhttpx\b|\bsmtplib\b|\bftplib\b",
    "changes Windows settings": r"\bwinreg\b|\breg\s+(?:add|delete)\b|\bSet-ItemProperty\b|\bctypes\.windll\b",
    "runs text as code": r"(?<![\w.])eval\(|(?<![\w.])exec\(|\bnew Function\(|\bcompile\(.*['\"]exec['\"]",
    "writes outside its folder": r"['\"](?:[A-Za-z]:\\\\|[A-Za-z]:/|/etc/|/usr/|~[/\\]|%APPDATA%|%USERPROFILE%)",
}


def risks(project):
    hits = []
    for rel in project.files():
        if not rel.endswith((".py", ".js", ".mjs", ".cjs", ".ts", ".html", ".bat", ".ps1", ".sh")):
            continue
        for i, line in enumerate((project.read(rel) or "").splitlines(), 1):
            if line.strip().startswith(("#", "//")):
                continue
            for what, rx in RISKS.items():
                if re.search(rx, line):
                    hits.append({"file": rel, "line": i, "what": what, "code": line.strip()[:120]})
    return hits


def _c(ok, what, level="fail", detail=""):
    return {"ok": bool(ok), "what": what, "level": level, "detail": detail}


def tests_summary(text):
    m = re.search(r"Ran (\d+) tests? in", text)
    ran = int(m.group(1)) if m else 0
    bad = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?", text)
    failed = (int(bad.group(1) or 0) + int(bad.group(2) or 0)) if bad else 0
    return ran, failed


def check(project, run=None, sample_input=None, timeout=60, design=True):
    out = []
    files = project.files()
    py = [f for f in files if f.endswith(".py")]
    js = [f for f in files if f.endswith((".js", ".mjs", ".cjs"))]
    if py:
        r = project.run(["python", "-m", "py_compile", *py], timeout=timeout)
        out.append(_c(r["code"] == 0, f"{len(py)} Python file(s) compile", detail=(r["err"] or r["out"]).strip()[-1500:]))
    for f in js:
        r = project.run(["node", "--check", f], timeout=timeout)
        out.append(_c(r["code"] == 0, f"{f} parses", detail=(r["err"] or "").strip()[-800:]))
    tests = [f for f in py if Path(f).name.startswith("test_")]
    if tests and all(c["ok"] for c in out):
        r = project.run(["python", "-m", "unittest", "-v"], timeout=timeout)
        ran, failed = tests_summary(r["err"] + r["out"])
        out.append(_c(r["code"] == 0 and ran > 0 and not failed, f"tests: {ran - failed}/{ran} pass", detail=(r["err"] or r["out"])[-2500:]))
    pkg = project.read("package.json")
    if pkg and '"test"' in pkg and "no test specified" not in pkg:
        r = project.run(["cmd", "/c", "npm", "test", "--silent"], timeout=timeout)
        out.append(_c(r["code"] == 0, "npm test passes", detail=(r["err"] + r["out"])[-2500:]))
    if run and all(c["ok"] for c in out):
        r = project.run(run, timeout=timeout, stdin=sample_input)
        out.append(_c(r["code"] == 0, f"runs: {' '.join(run)} (exit {r['code']}, {r['seconds']} s)", detail=((r["out"] or "") + ("\n" + r["err"] if r["err"] else "")).strip()[-2000:]))
    html = [f for f in files if f.endswith((".html", ".htm"))]
    if html:
        out += web(project, "index.html" if "index.html" in html else html[0])
    if design and (project.folder / "design" / "design.json").exists():
        out += design_match(project)
    if not out:
        out.append(_c(bool(files), f"{len(files)} file(s) written"))
    return out


def design_match(project):
    """The page against the design it was made from (designcheck.py)."""
    from ai_pc.coding import designcheck
    try:
        r = designcheck.check(project.folder, shot=(project.folder / "design" / "reference.png").exists())
    except Exception as e:  # noqa: BLE001
        return [_c(False, "design: the page could not be measured", "info", str(e)[:500])]
    return [_c(r["ok"], "design: " + "; ".join(r["lines"][:2]) + (f"; {r['lines'][-1]}" if r.get("picture") else ""), "info", "\n".join(r["lines"]))]


def web(project, page):
    """The page in headless Chrome (its own profile, nothing shown): it loads, has content, and logs no errors."""
    from ai_pc.core import headless
    p = project.inside(page)
    try:
        out, err, secs = headless._run(["--dump-dom", "--enable-logging=stderr", "--v=0", "--virtual-time-budget=3000"], p.as_uri(), 60, "code")
    except headless.RenderError as e:
        return [_c(False, f"{page} opens in a browser", detail=str(e))]
    errors = [ln for ln in err.splitlines() if ("CONSOLE" in ln and re.search(r"Uncaught|Error|error|Failed", ln))
              or "Failed to load resource" in ln or "net::ERR_FILE_NOT_FOUND" in ln]
    src = project.read(page) or ""
    links = [u for u in re.findall(r'(?:src|href)\s*=\s*["\']([^"\'#?]+)', src, re.I)
             if not re.match(r"[a-z]+:|//|#|mailto:|tel:", u, re.I) and not u.startswith("data:")]
    gone = [u for u in links if not (p.parent / u).exists()]  # the browser stays quiet about a missing local file: look ourselves
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", out, flags=re.S)
    words = len(text.split())
    shot = project.folder / ".out" / f"{Path(page).stem}.png"
    try:
        headless.png(p, shot, (1280, 900), wait_ms=2500, lane="code")
    except headless.RenderError:
        shot = None
    return [_c(words >= 3, f"{page} loads with content ({words} words)", detail=out[:500]),
            _c(not gone, f"{page}: every file it links to is there" + (f" (missing: {', '.join(gone[:4])})" if gone else ""),
               detail="missing files the page links to: " + ", ".join(gone)),
            _c(not errors, f"{page}: no errors in the browser console" + (f" ({len(errors)})" if errors else ""), detail="\n".join(errors)[:1500])] + \
        ([_c(True, f"screenshot {shot.relative_to(project.folder).as_posix()}", "info")] if shot else [])
