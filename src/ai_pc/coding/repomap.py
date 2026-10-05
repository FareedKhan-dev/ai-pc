"""What a project holds, short enough to give the model: every file, and for code the classes and functions with
their arguments (Python by its syntax tree, JavaScript by pattern), plus the files a request is about in full."""

import ast
import re


def symbols(project, rel):
    src = project.read(rel) or ""
    if rel.endswith(".py"):
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            return [f"(does not compile: line {e.lineno})"]
        out = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(f"def {n.name}({', '.join(a.arg for a in n.args.args)})")
            elif isinstance(n, ast.ClassDef):
                out.append(f"class {n.name}: " + ", ".join(m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))))
        return out
    if rel.endswith((".js", ".mjs", ".cjs", ".ts")):
        return [
            m.group(0).strip()[:80]
            for m in re.finditer(
                r"^(?:export\s+)?(?:async\s+)?function\s+\w+\s*\([^)]*\)|^(?:export\s+)?class\s+\w+|"
                r"^(?:export\s+)?const\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
                src,
                re.M,
            )
        ]
    if rel.endswith((".html", ".htm")):
        ids = re.findall(r'id="([^"]+)"', src)
        return [f"ids: {', '.join(ids[:20])}"] if ids else []
    return []


def repomap(project, limit=60):
    lines = []
    for rel in project.files()[:limit]:
        syms = symbols(project, rel)
        size = len(project.read(rel) or "")
        lines.append(f"{rel} ({size} chars)" + ("".join(f"\n    {s}" for s in syms[:15])))
    return "\n".join(lines)


STOP = {
    "make",
    "made",
    "change",
    "please",
    "should",
    "would",
    "want",
    "need",
    "them",
    "this",
    "that",
    "with",
    "from",
    "into",
    "more",
    "less",
    "bigger",
    "smaller",
    "larger",
    "colour",
    "color",
    "also",
    "some",
    "have",
    "they",
    "there",
    "their",
    "page",
    "site",
    "website",
}


def css_excerpt(css, request, html=""):
    """From a stylesheet too long to send whole: the rules for the elements a request names (by their class, or by the
    words they show on the page), copied exactly, so search/replace edits still match the file."""
    words = {w for w in re.findall(r"[a-z]{3,}", request.lower()) if w not in STOP}
    classes = set()
    for m in re.finditer(r'class="([^"]+)"[^>]*>([^<]{0,200})', html or ""):
        cls, shown = m.group(1), m.group(2).lower()
        if any(w in cls or re.search(r"\b" + w, shown) for w in words):
            classes.update(cls.split())
    keep = []
    for block in re.findall(r"[^{}]+\{[^{}]*\}", css):
        sel = block.split("{")[0].strip().lower()
        if any(re.search(r"\." + re.escape(c) + r"(?![\w-])", sel) for c in classes) or any(w in sel for w in words):
            keep.append(block.strip())
    return "\n\n".join(keep)


def relevant(project, request, budget=14000):
    """The files a request is about, in full, within a budget: named ones, ones named in an error, then the main files.
    A stylesheet too long to fit is sent as the rules the request is about. A design's own record (design/) is not code."""
    files = [f for f in project.files() if not f.startswith(("design/", ".vscode/")) and f != ".gitignore"]
    text = request.lower()
    named = [f for f in files if f.lower() in text or f.split("/")[-1].lower() in text]
    for m in re.finditer(r'File "([^"]+)", line \d+', request):
        tail = m.group(1).replace("\\", "/").split("/")[-1]
        named += [f for f in files if f.endswith(tail)]
    words = set(re.findall(r"[a-z_]{4,}", text))
    scored = sorted(files, key=lambda f: -sum(w in (project.read(f) or "").lower() for w in words))
    main = ("main.py", "app.py", "index.html", "index.js", "script.js", "style.css", "styles.css")
    order = list(dict.fromkeys(named + [f for f in main if f in files] + scored))
    out, used, left = [], 0, []
    for f in order:
        src = project.read(f) or ""
        if f.endswith((".png", ".jpg")):
            continue
        if used + len(src) > budget:
            left.append((f, src))
            continue
        out.append(f"=== FILE: {f} ===\n{src}\n=== END ===")
        used += len(src)
    page = project.read("index.html") or ""
    for f, src in left:
        if f.endswith(".css"):
            ex = css_excerpt(src, request, page)
            if ex and used + len(ex) <= budget + 6000:
                out.append(f"=== FILE: {f} (only the rules this request is about; the rest of the file stays as it is) ===\n{ex}\n=== END ===")
                used += len(ex)
    return "\n".join(out)
