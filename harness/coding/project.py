"""A code project on disk: its files, a git history (every change a commit, so undo and history come free), a virtual
environment of its own for Python (made by uv inside the project), VS Code's workspace files (interpreter, run and test
tasks, debug configurations), and running commands in it with a time limit.

  p = Project.create(ROOT/"out"/"code"/"projects"/"word_counter", kind="python")
  p.write({"main.py": "...", "test_main.py": "..."})   p.commit("first version")
  p.run(["python", "main.py", "sample.txt"]) -> {"code", "out", "err", "seconds"}
  p.undo() / p.log() / p.diff()   p.apply_edits(text)  (search/replace blocks)   p.open_in_vscode("main.py", 12)
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

NO_WINDOW = 0x08000000
IGNORE = {".git", ".venv", "node_modules", "__pycache__", ".vscode", ".pytest_cache", "dist", "build", ".idea"}
TEXT_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".html", ".htm", ".css", ".md", ".txt", ".csv", ".toml", ".yaml", ".yml", ".ini",
            ".cfg", ".sql", ".sh", ".bat", ".ps1", ".xml", ".svg", ".env.example"}


class ProjectError(Exception):
    pass


def _git(cwd, *args, check=True):
    r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.name=AI PC", "-c", "user.email=ai-pc@localhost", *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if check and r.returncode:
        raise ProjectError(f"git {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
    return r.stdout


def edit_blocks(text):
    """Search/replace blocks as models really write them -> [(file or None, search, replace)]. The file is named on the line
    just before a block ('FILE: x', 'File x', '**x**', '`x`' or just 'x'); code fences and a repeated SEARCH marker are forgiven."""
    text = re.sub(r"(?m)^```[\w+-]*\s*$\n?", "", text.replace("\r\n", "\n"))
    out, pos = [], 0
    for m in re.finditer(r"<<<<<<< SEARCH\n(.*?)\n?=======\n(.*?)\n?>>>>>>> REPLACE", text, re.S):
        old, new = m.group(1), m.group(2)
        head = text[pos:m.start()]
        if "<<<<<<< SEARCH\n" in old:  # a stray marker: the search is what follows the last one
            pre, old = old.rsplit("<<<<<<< SEARCH\n", 1)
            head += "\n" + pre
        rel = None
        lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
        if lines:
            cand = re.sub(r"^(?:#+|\*+|>|-)?\s*(?:file(?:name)?\s*:?\s*)?[`'\"*]*|[`'\"*:]*$", "", lines[-1], flags=re.I).strip()
            if re.fullmatch(r"[\w./\\-]+\.\w{1,8}", cand):
                rel = cand.replace("\\", "/")
        out.append((rel, old, new))
        pos = m.end()
    return out


class Project:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        if not self.folder.is_dir():
            raise ProjectError(f"no folder {self.folder}")
        self.kind = self.detect()

    # ---------------------------------------------------------------- making one
    @classmethod
    def create(cls, folder, kind="python"):
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / ".git").exists():
            _git(folder, "init", "-q", "-b", "main")
        (folder / ".gitignore").write_text(".venv/\n__pycache__/\nnode_modules/\n*.pyc\n.out/\n", encoding="utf-8")
        p = cls(folder)
        p.kind = kind
        if kind == "python":
            p.ensure_venv()
        p.vscode()
        return p

    @classmethod
    def open(cls, folder):
        p = cls(folder)
        if not (p.folder / ".git").exists():  # someone else's folder: a history starts now, nothing of theirs is changed
            _git(p.folder, "init", "-q", "-b", "main")
            _git(p.folder, "add", "-A")
            _git(p.folder, "commit", "-q", "--allow-empty", "-m", "Before the AI PC changed anything")
        return p

    def detect(self):
        f = self.folder
        if (f / "package.json").exists() or any(f.glob("*.js")) and not any(f.glob("*.py")):
            return "node"
        if any(f.glob("*.html")) and not any(f.glob("*.py")):
            return "web"
        return "python"

    def ensure_venv(self):
        """A virtual environment inside the project (uv; the Python is the one uv already has, nothing downloaded)."""
        if (self.folder / ".venv" / "Scripts" / "python.exe").exists():
            return
        r = subprocess.run(["uv", "venv", "--quiet", "--python", "3.12", str(self.folder / ".venv")], capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode:
            raise ProjectError(f"could not make the virtual environment: {r.stderr.strip()[:200]}")

    def python(self):
        exe = self.folder / ".venv" / "Scripts" / "python.exe"
        return str(exe) if exe.exists() else "python"

    def vscode(self):
        """VS Code's workspace files, written like a CapCut draft: the interpreter, Run and Test tasks, a debug setup."""
        v = self.folder / ".vscode"
        v.mkdir(exist_ok=True)
        if self.kind == "python":
            settings = {"python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe", "python.testing.unittestEnabled": True,
                        "python.testing.unittestArgs": ["-v", "-s", ".", "-p", "test_*.py"], "editor.formatOnSave": False, "files.eol": "\n"}
            tasks = [{"label": "Run", "type": "shell", "command": "${workspaceFolder}/.venv/Scripts/python.exe", "args": ["main.py"], "group": "build"},
                     {"label": "Test", "type": "shell", "command": "${workspaceFolder}/.venv/Scripts/python.exe", "args": ["-m", "unittest", "-v"],
                      "group": {"kind": "test", "isDefault": True}}]
            launch = [{"name": "Run main.py", "type": "debugpy", "request": "launch", "program": "${workspaceFolder}/main.py", "console": "integratedTerminal"},
                      {"name": "Current file", "type": "debugpy", "request": "launch", "program": "${file}", "console": "integratedTerminal"}]
            ext = ["ms-python.python", "ms-python.debugpy"]
        elif self.kind == "node":
            settings = {"files.eol": "\n"}
            tasks = [{"label": "Run", "type": "shell", "command": "node", "args": ["index.js"], "group": "build"},
                     {"label": "Test", "type": "shell", "command": "npm", "args": ["test"], "group": {"kind": "test", "isDefault": True}}]
            launch = [{"name": "Run index.js", "type": "node", "request": "launch", "program": "${workspaceFolder}/index.js"}]
            ext = ["dbaeumer.vscode-eslint"]
        else:
            settings = {"files.eol": "\n"}
            tasks = [{"label": "Open in browser", "type": "shell", "command": "start", "args": ["index.html"], "group": "build"}]
            launch = []
            ext = ["ritwickdey.LiveServer"]
        (v / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        (v / "tasks.json").write_text(json.dumps({"version": "2.0.0", "tasks": tasks}, indent=2), encoding="utf-8")
        (v / "launch.json").write_text(json.dumps({"version": "0.2.0", "configurations": launch}, indent=2), encoding="utf-8")
        (v / "extensions.json").write_text(json.dumps({"recommendations": ext}, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- files
    def files(self):
        out = []
        for root, dirs, fs in os.walk(self.folder):
            dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith(".")]
            for f in fs:
                p = Path(root) / f
                if p.suffix.lower() in TEXT_EXT or f in ("Dockerfile", "Makefile", "requirements.txt", ".gitignore"):
                    out.append(p.relative_to(self.folder).as_posix())
        return sorted(out)

    def read(self, rel):
        p = self.inside(rel)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    def inside(self, rel):
        """The path, refused if it leaves the project (no '..', no other drive)."""
        p = (self.folder / rel).resolve()
        if self.folder not in p.parents and p != self.folder:
            raise ProjectError(f"{rel} is outside the project")
        return p

    def write(self, files):
        for rel, content in files.items():
            p = self.inside(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8", newline="\n")
        return list(files)

    def delete(self, rels):
        for rel in rels:
            p = self.inside(rel)
            if p.is_file():
                p.unlink()

    def apply_edits(self, text):
        """Search/replace blocks (FILE: path, <<<<<<< SEARCH, =======, >>>>>>> REPLACE); an empty SEARCH makes the file.
        Each SEARCH must match the file exactly once (spacing at line ends forgiven). A block without its FILE line goes to
        the one file that holds its SEARCH text. Code fences around blocks are ignored. Returns (changed files, problems)."""
        changed, problems = [], []
        for rel, old, new in edit_blocks(text):
            if not rel:
                homes = [f for f in self.files() if old.strip() and old in (self.read(f) or "")]
                if len(homes) != 1:
                    problems.append(f"a change without its file name: its text is in {len(homes)} files ({old.strip()[:60]!r})")
                    continue
                rel = homes[0]
            p = self.inside(rel)
            cur = p.read_text(encoding="utf-8") if p.exists() else ""
            if not old.strip():
                if p.exists() and cur.strip():
                    problems.append(f"{rel}: already exists (an empty SEARCH only makes new files)")
                    continue
                self.write({rel: new})
                changed.append(rel)
                continue
            n = cur.count(old)
            if n == 1:
                cur = cur.replace(old, new, 1)
            else:
                norm = lambda s: "\n".join(ln.rstrip() for ln in s.split("\n"))  # noqa: E731
                if norm(cur).count(norm(old)) == 1:
                    cur = norm(cur).replace(norm(old), new, 1)
                else:
                    problems.append(f"{rel}: the text to replace was found {n} times (needs exactly once): {old.strip()[:60]!r}")
                    continue
            p.write_text(cur, encoding="utf-8", newline="\n")
            changed.append(rel)
        return sorted(set(changed)), problems

    # ---------------------------------------------------------------- history (git)
    def commit(self, message):
        _git(self.folder, "add", "-A")
        st = _git(self.folder, "status", "--porcelain")
        if not st.strip():
            return None
        _git(self.folder, "commit", "-q", "-m", message[:200])
        return _git(self.folder, "rev-parse", "--short", "HEAD").strip()

    def log(self, n=20):
        out = _git(self.folder, "log", f"-{n}", "--pretty=format:%h|%ad|%s", "--date=format:%d %b %H:%M", check=False)
        return [dict(zip(("id", "when", "what"), ln.split("|", 2))) for ln in out.splitlines() if ln]

    def undo(self):
        """Back to the commit before the last (the last change is kept in git's reflog, so even this can be undone)."""
        commits = self.log(2)
        if len(commits) < 2:
            raise ProjectError("nothing to undo")
        _git(self.folder, "reset", "-q", "--hard", "HEAD~1")
        return commits[0]

    def redo(self):
        ref = _git(self.folder, "reflog", "-n", "2", "--pretty=format:%h", check=False).split()
        if len(ref) < 2:
            raise ProjectError("nothing to redo")
        _git(self.folder, "reset", "-q", "--hard", ref[1])
        return self.log(1)[0]

    def diff(self, against="HEAD~1"):
        return _git(self.folder, "diff", against, "--stat", "--patch", "--no-color", check=False)

    def uncommitted(self):
        return _git(self.folder, "status", "--porcelain", check=False).strip()

    # ---------------------------------------------------------------- running
    def run(self, cmd, timeout=60, stdin=None):
        """A command in the project folder, with a time limit; python means the project's own python."""
        cmd = [self.python() if c == "python" else c for c in cmd]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        t0 = time.perf_counter()
        try:
            r = subprocess.run(cmd, cwd=str(self.folder), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                               input=stdin, env=env, creationflags=NO_WINDOW, shell=False)
            return {"code": r.returncode, "out": r.stdout[-6000:], "err": r.stderr[-6000:], "seconds": round(time.perf_counter() - t0, 2)}
        except subprocess.TimeoutExpired as e:
            return {"code": -1, "out": (e.stdout or "")[-3000:] if isinstance(e.stdout, str) else "", "err": f"stopped after {timeout} s (it did not finish)",
                    "seconds": timeout}
        except FileNotFoundError as e:
            return {"code": -2, "out": "", "err": f"not found: {e}", "seconds": 0}

    def open_in_vscode(self, rel=None, line=None):
        """VS Code shows the project (and a file at a line). Only when the person asks: it opens a window."""
        args = ["code", str(self.folder)]
        if rel:
            args += ["-g", f"{self.inside(rel)}:{line or 1}"]
        subprocess.Popen(args, shell=True, creationflags=NO_WINDOW)
        return True

    def remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)
