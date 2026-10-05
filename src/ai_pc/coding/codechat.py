"""A conversation that writes code. Each request becomes a version (a git commit) that was checked: the files compile,
the project's own tests pass, the program runs (or the web page loads with no console errors). When a check fails, the
errors go back to the model and it repairs its work (up to three rounds). Code that could harm the PC (deleting
outside its folder, running other programs, the network, the registry) is shown and runs only after your yes.

  c = CodeChat.start()
  c.say("make a python script that counts words, lines and characters in a text file")   -> files, tests 4/4, the run's output
  c.say("add an option to show the 10 most common words")    -> an edit, tested; c.say("run it")  /  c.say("open it in VS Code")
  c.say("build a one-page website for Khan Electronics with our products and a contact form")  -> loads with no console errors
  c.say("undo") / c.say("history") / c.say("what changed?") / c.say("explain the code") / c.say("open project word_counter")
  c.say("make a website from https://www.figma.com/design/KEY/Shop?node-id=1-2")   -> HTML and CSS from the Figma frame, measured against it
  c.say("turn my Canva design 'Eid sale' into a web page")   -> the same from Canva (its PowerPoint export); "does it still match the design?"
"""

import datetime as dt
import json
import re
import time
from pathlib import Path

from ai_pc.coding import verify as V
from ai_pc.coding.project import Project, ProjectError
from ai_pc.coding.repomap import relevant, repomap
from ai_pc.core.config import ROOT
from ai_pc.hub.http import HubError

PROJECTS = ROOT / "out" / "code" / "projects"
CHATS = ROOT / "out" / "code" / "chats"
YES = re.compile(r"^\s*(?:yes|yeah|ok|okay|sure|go ahead|run it anyway|do it|allow it|confirm)\b[\s.!]*$", re.I)
NO = re.compile(r"^\s*(?:no|nope|cancel|stop|don'?t)\b", re.I)
FIGMA_LINK = re.compile(r"https?://(?:www\.)?figma\.com/(?:file|design|proto|board)/[A-Za-z0-9]{10,}[^\s\"'<>]*", re.I)
DESIGN_WORDS = r"\b(?:make|build|turn|convert|code|create|generate|develop)\b|\b(?:website|web ?page|html|landing page|site|code)\b"

NEW_SYSTEM = """You write small, complete, working programs for a person on Windows. Reply ONLY with blocks in this exact format:
=== META ===
name: short_snake_case_name
kind: python | web | node
run: the command that runs it (e.g. python main.py sample.txt, or node index.js, or index.html for a web page)
about: one sentence
=== END ===
=== FILE: relative/path.ext ===
(the whole file)
=== END ===
Rules:
- python: main.py with functions, a main() and if __name__ == "__main__": main(); standard library only; argparse for inputs; test_main.py with
  unittest tests that import the functions from main and test them (not the command line); if the program reads a file, include a small sample
  file and use it in the run command. The run command must finish by itself (no waiting for keyboard input).
- web: index.html, style.css, script.js; nothing from the internet (no CDN, fonts, images or libraries); semantic HTML; works on phones; plain JavaScript.
- node: index.js with Node's built-in modules only; package.json with "scripts": {"test": "node --test"}; tests in test/main.test.js with node:test.
- Never delete files, start other programs, use the network or touch anything outside the project folder unless the person asked for exactly that.
- Never invent real-looking business details (prices, phone numbers, addresses, emails, names): use the person's own, or obvious placeholders
  they will change, like "Rs 00,000", "0300-0000000", "your@email.com". Prices are in Pakistani rupees (Rs) unless the person says otherwise.
- Short, readable code with brief comments. English only."""

EDIT_SYSTEM = """You change an existing project exactly as asked. Reply ONLY with search/replace blocks:
FILE: relative/path.ext
<<<<<<< SEARCH
lines copied exactly from the file (enough of them to be unique)
=======
the new lines
>>>>>>> REPLACE
A new file: an empty SEARCH part. Several blocks are fine. Change only what is needed; keep the existing tests passing and add a unittest test
for new behaviour in Python projects. If the way to run it changes, end with one line: RUN: <command>. Standard library only; no network,
no deleting files, no other programs unless asked. English only."""

FIX_SYSTEM = """The project below fails its checks. Fix the code (not the tests, unless a test itself is wrong) with search/replace blocks only:
FILE: relative/path.ext
<<<<<<< SEARCH
lines copied exactly from the file
=======
the fixed lines
>>>>>>> REPLACE
If the run command itself is wrong, end with one line: RUN: <command>."""


def _when():
    return dt.datetime.now().isoformat(timespec="seconds")


def parse_files(text):
    """META and FILE blocks from the model's answer (code fences forgiven)."""
    text = re.sub(r"```[a-zA-Z0-9]*\n?", "", text)
    meta = {}
    m = re.search(r"=== META ===\s*\n(.*?)\n=== END ===", text, re.S)
    if m:
        for ln in m.group(1).splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    files = {}
    for fm in re.finditer(r"=== FILE:\s*(.+?)\s*===\s*\n(.*?)\n=== END ===", text, re.S):
        files[fm.group(1).strip().strip("`'\"")] = fm.group(2)
    return meta, files


def run_line(text):
    m = re.search(r"^RUN:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "project").lower()).strip("_")[:40] or "project"


class CodeChat:
    def __init__(self, state, planner=None, projects_dir=None, connectors=None):
        self.state, self.planner = state, planner
        self.connectors = connectors or {}  # tests: fake Figma / Canva connectors
        self.folder = Path(state["folder"])
        self.projects_dir = Path(projects_dir or state.get("projects_dir") or PROJECTS)
        self.last_turn = None

    @classmethod
    def start(cls, planner=None, chats_dir=None, projects_dir=None, connectors=None):
        cid = f"code_{time.strftime('%Y%m%d_%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        st = {
            "id": cid,
            "folder": str(folder),
            "project": None,
            "run": None,
            "turns": [],
            "pending": None,
            "projects_dir": str(projects_dir or PROJECTS),
        }
        return cls(st, planner, projects_dir, connectors)

    def _conn(self, name):
        if name in self.connectors:
            return self.connectors[name]
        from ai_pc.hub import services

        return services.connector(name)

    def project(self):
        return Project(self.state["project"]) if self.state.get("project") else None

    def save(self):
        (self.folder / "chat.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def ask(self, system, user):
        if self.planner is None:
            raise ProjectError("writing code needs the model (it is off)")
        self._turn["llm"] = True
        r = self.planner._call("fast", [{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.text

    # ---------------------------------------------------------------- a message
    def say(self, message):
        t0 = time.perf_counter()
        turn = {"user": message, "intents": [], "llm": False}
        self._turn = turn
        try:
            reply = self._route(message.strip())
        except ProjectError as e:
            reply = f"Couldn't: {e}"
        turn.update(reply=reply, seconds=round(time.perf_counter() - t0, 2), project=self.state.get("project"))
        self.state["turns"].append(turn)
        self.last_turn = turn
        self.save()
        return reply

    def _route(self, msg):
        c = " ".join(msg.lower().split())
        p = self.state.get("pending")
        if p and YES.search(msg):
            self.state["pending"] = None
            self.state["allowed"] = True
            self._turn["intents"].append("allow")
            return self._checked(self.project(), p["what"], allow=True)
        if p and NO.search(msg):
            self.state["pending"] = None
            return "Not run. The code is saved; say 'undo' to take it back, or ask for a change."
        self.state["pending"] = None
        intents = [
            (r"^\s*undo\b", self.undo),
            (r"^\s*redo\b", self.redo),
            (r"^\s*(?:history|versions|log)\b", self.history),
            (r"\bwhat changed\b|\bshow (?:me )?the (?:diff|changes)\b", self.what_changed),
            (r"\b(?:list|show) (?:my |the )?projects\b", self.list_projects),
            (r"\bopen (?:it |this |the project )?(?:in )?(?:vs ?code|vscode|the editor)\b|\bshow (?:it|me) in vs ?code\b", self.open_vscode),
            (r"\b(?:run|check) (?:the )?tests?\b|^\s*test it\b", self.test),
            (r"^\s*run(?: it| the (?:program|app|script|code))?(?:\s+with\s+(.+))?\s*$", self.run),
            (r"\bexplain\b|\bhow does (?:it|this|the code) work\b", self.explain),
            (r"\bshow (?:me )?(?:the )?(?:code|files?)\b|^\s*show\s+\S+\.\w+\s*$", self.show),
        ]
        m = re.search(r"\b(?:open|work on|switch to|use) (?:the )?(?:project|folder)\s+(.+)$", msg, re.I)
        if m:
            self._turn["intents"].append("open_project")
            return self.open_project(m.group(1).strip().strip("\"'"))
        link = FIGMA_LINK.search(msg)
        if link or (re.search(r"\bfigma\b", c) and re.search(DESIGN_WORDS, c)):
            self._turn["intents"].append("from_figma")
            return self.from_design("figma", msg, link.group(0) if link else None)
        if re.search(r"\bcanva\b", c) and re.search(DESIGN_WORDS, c):
            self._turn["intents"].append("from_canva")
            return self.from_design("canva", msg)
        if re.search(r"\b(?:match(?:es)?|look(?:s)? like|compare[sd]?|check(?:ed)?|measure[sd]?)\b.*\b(?:the )?design\b", c) and self.state.get(
            "project"
        ):
            self._turn["intents"].append("design_check")
            return self.design_check()
        for rx, fn in intents:
            mm = re.search(rx, c)
            if mm:
                self._turn["intents"].append(fn.__name__)
                return fn(mm.group(1) if mm.lastindex else None) if fn in (self.run,) else fn()
        thing = (
            r"\b(?:script|program|app|application|tool|website|web ?page|site|landing page|game|bot|api|cli|calculator|converter|tracker|dashboard|"
            r"portfolio|utility)\b"
        )
        new = re.search(r"\b(?:make|create|build|write|generate|code|develop)\b.*" + thing, c) and (
            not self.state.get("project") or re.search(r"\b(?:make|create|build|write|generate|develop)\s+(?:me\s+)?(?:a|an|new|another)\b", c)
        )
        if new:
            self._turn["intents"].append("new")
            return self.new(msg)
        if self.state.get("project"):
            self._turn["intents"].append("edit")
            return self.edit(msg)
        return "Tell me what to build, e.g. 'make a python script that renames photos by date' or 'build a one-page website for my shop'."

    # ---------------------------------------------------------------- building
    def new(self, request):
        kind_hint = (
            "web"
            if re.search(r"\bwebsite|web ?page|\bsite\b|landing page|portfolio|html|in the browser|browser game", request, re.I)
            else "node"
            if re.search(r"\bnode\b|\bjavascript\b(?!.*\bweb)|\bexpress\b", request, re.I)
            else "python"
        )
        ans = self.ask(NEW_SYSTEM, f"Make this ({kind_hint} unless the request says otherwise): {request}")
        meta, files = parse_files(ans)
        if not files:
            raise ProjectError("the model did not return any files; try rewording the request")
        name = slug(meta.get("name") or request[:40])
        folder = self.projects_dir / name
        k = 2
        while folder.exists():
            folder = self.projects_dir / f"{name}_{k}"
            k += 1
        kind = meta.get("kind", kind_hint).split()[0].strip().lower()
        if kind not in ("python", "web", "node"):
            kind = kind_hint
        proj = Project.create(folder, kind)
        proj.write(files)
        self.state.update(project=str(proj.folder), run=meta.get("run"), about=meta.get("about"))
        return self._checked(proj, f"first version: {request[:80]}", new=True)

    def edit(self, request):
        proj = self.project()
        ctx = (
            f"PROJECT ({proj.kind}), files and what is in them:\n{repomap(proj)}\n\nRUN COMMAND: {self.state.get('run')}\n\n"
            f"FILES:\n{relevant(proj, request)}\n\nCHANGE TO MAKE: {request}"
        )
        ans = self.ask(EDIT_SYSTEM, ctx)
        changed, problems = self._apply(proj, ans)
        if not changed:
            return "The model's change did not fit the files (" + "; ".join(problems[:2]) + "). Try saying it more exactly, or name the file."
        return self._checked(proj, request[:80], changed=changed, problems=problems)

    def _apply(self, proj, ans):
        changed, problems = proj.apply_edits(ans)
        meta, files = parse_files(ans)
        if files:  # whole files are fine too
            proj.write(files)
            changed = sorted(set(changed) | set(files))
        r = run_line(ans) or meta.get("run")
        if r:
            self.state["run"] = r
        return changed, problems

    def _run_cmd(self, proj):
        r = (self.state.get("run") or "").strip()
        if not r or proj.kind == "web" or r.endswith((".html", ".htm")):
            return None
        return r.split()

    def _checked(self, proj, what, new=False, changed=None, problems=None, allow=False):
        """Risks first, then checks, then repairs (up to three rounds), then a version."""
        hits = V.risks(proj)
        if hits and not allow:
            sha = proj.commit(f"{what} (not run yet)")
            self.state["pending"] = {"what": what}
            lines = "\n".join(f"  {h['file']}:{h['line']}  {h['what']}: {h['code']}" for h in hits[:8])
            return (
                f"Saved ({sha}), but not run: this code could change things on your PC:\n{lines}\n"
                f"Say 'yes' to run its checks anyway, 'no' to leave it, or ask me to remove those parts."
            )
        checks = V.check(proj, self._run_cmd(proj))
        rounds = 0
        while any(not c["ok"] and c["level"] == "fail" for c in checks) and rounds < 3 and self.planner is not None:
            rounds += 1
            errors = "\n\n".join(f"CHECK FAILED: {c['what']}\n{c['detail']}" for c in checks if not c["ok"])
            ans = self.ask(
                FIX_SYSTEM,
                f"PROJECT ({proj.kind}):\n{repomap(proj)}\nRUN COMMAND: {self.state.get('run')}\n\n{errors[:6000]}\n\n"
                f"FILES:\n{relevant(proj, errors + ' ' + what)}",
            )
            self._apply(proj, ans)
            if V.risks(proj) and not allow:
                return self._checked(proj, what)
            checks = V.check(proj, self._run_cmd(proj))
        sha = proj.commit(what)
        bad = [c for c in checks if not c["ok"] and c["level"] == "fail"]
        self.state["last_checks"] = checks
        ran = next((c for c in checks if c["what"].startswith("runs:")), None)
        tests = next((c for c in checks if c["what"].startswith("tests:")), None)
        shot = next((c for c in checks if c["what"].startswith("screenshot")), None)
        files = proj.files()
        head = (
            f"Made {proj.folder.name} ({proj.kind}): {', '.join(f for f in files if not f.startswith('.'))[:300]}."
            if new
            else f"Changed {', '.join(changed or [])}."
        )
        body = []
        if tests:
            body.append(tests["what"].capitalize())
        if ran:
            out = ran["detail"].strip().splitlines()
            body.append(f"ran `{' '.join(self._run_cmd(proj) or [])}`" + (f": {' / '.join(out[:4])[:300]}" if out else ""))
        for c in checks:
            if c["what"].endswith("console") or "loads with content" in c["what"] or c["what"].startswith("design:"):
                body.append(c["what"])
        if shot:
            body.append(shot["what"])
        if rounds:
            body.append(f"repaired in {rounds} round(s)")
        verdict = (
            "all checks pass"
            if not bad
            else "NOT right yet: "
            + "; ".join(f"{c['what']} ({c['detail'].strip().splitlines()[-1][:160] if c['detail'].strip() else ''})" for c in bad[:2])
        )
        tail = f" Version {sha}." if sha else ""
        tip = f" Folder: {proj.folder}. Say 'open it in VS Code' to see it, or ask for a change." if new else ""
        return (
            f"{head} " + "; ".join(body) + (". " if body else "") + verdict + "." + tail + tip + (f" ({'; '.join(problems[:1])})" if problems else "")
        )

    # ---------------------------------------------------------------- from a design (Figma, Canva)
    def from_design(self, source, msg, link=None):
        from ai_pc.coding import fromdesign as FD

        quoted = re.findall(r"[\"“”']([^\"“”']{2,80})[\"“”']", msg)
        try:
            if source == "figma":
                link = link or self.state.get("figma_link")
                if not link:
                    return "Paste the Figma link of the frame (in Figma: right-click the frame > Copy/Paste as > Copy link to selection)."
                m = re.search(
                    r"\bframe\s+(?:called\s+|named\s+)?([\w][\w &/-]{0,40}?)(?:\s+(?:from|in|into|of|as)\b|[.,!?]|$)", msg, re.I
                ) or re.search(r"\bthe\s+([\w][\w &/-]{0,40}?)\s+frame\b", msg, re.I)
                frame = quoted[0] if quoted else (m.group(1).strip() if m else None)
                r = FD.from_figma(self._conn("figma"), link, frame, self.projects_dir)
                self.state["figma_link"] = link
            else:
                m = re.search(
                    r"\bcanva design\s+(?:called\s+|named\s+)?([\w][\w &'-]{0,60}?)(?:\s+(?:into|to|as|in)\b|[.,!?]|$)", msg, re.I
                ) or re.search(r"\bmy\s+([\w][\w &'-]{0,60}?)\s+(?:canva\s+)?design\b", msg, re.I)
                name = quoted[0] if quoted else (m.group(1).strip() if m else None)
                pm = re.search(r"\bpages?\s+(\d+)(?:\s*(?:-|to|and)\s*(\d+))?", msg, re.I)
                pages = list(range(int(pm.group(1)), int(pm.group(2) or pm.group(1)) + 1)) if pm else None
                r = FD.from_canva(self._conn("canva"), name, pages, bool(re.search(r"\bemail\b|\bnewsletter\b", msg, re.I)), self.projects_dir)
        except HubError as e:
            return f"Couldn't: {e}"
        except (ValueError, KeyError) as e:
            return f"Couldn't read that design: {e}"
        proj = r["project"]
        self.state.update(
            project=str(proj.folder),
            run="index.html",
            about=f"made from the {source.title()} design '{r['name']}'",
            design={"source": source, "name": r["name"]},
        )
        self.state["last_checks"] = r["web"]
        return FD.summary(r)

    def design_check(self):
        from ai_pc.coding import designcheck as DC

        proj = self._need()
        if not (proj.folder / "design" / "design.json").exists():
            return "This project was not made from a design, so there is nothing to compare it with."
        r = DC.check(proj.folder, shot=(proj.folder / "design" / "reference.png").exists())
        return (
            ("Matches the design: " if r["ok"] else "Differs from the design: ")
            + "; ".join(r["lines"])
            + "."
            + (" The side-by-side picture is .out/compare.png in the project." if r.get("picture") else "")
        )

    # ---------------------------------------------------------------- the rest
    def run(self, args=None):
        proj = self._need()
        cmd = self._run_cmd(proj)
        if proj.kind == "web":
            res = V.web(proj, "index.html" if "index.html" in proj.files() else next(f for f in proj.files() if f.endswith(".html")))
            return "; ".join(c["what"] for c in res) + "."
        if not cmd:
            return "I don't know how to run it yet; say e.g. 'run it with python main.py'."
        if args:
            cmd = cmd[:2] + args.split() if cmd[0] in ("python", "node") else cmd + args.split()
        if V.risks(proj) and not self.state.get("allowed"):
            return "This code can change things on your PC; I ran it only after your yes before. Say 'yes' to allow it."
        r = proj.run(cmd, timeout=120)
        return f"`{' '.join(cmd)}` exit {r['code']} in {r['seconds']} s:\n{(r['out'] or '').strip()[-1500:]}" + (
            f"\n{r['err'].strip()[-800:]}" if r["err"].strip() else ""
        )

    def test(self):
        proj = self._need()
        checks = V.check(proj, None)
        return "; ".join(("ok " if c["ok"] else "NOT ") + c["what"] for c in checks if c["level"] != "info") + "."

    def explain(self):
        proj = self._need()
        ans = self.ask(
            "Explain this project to someone who does not code: what it does, how to use it, and which file does what. 5-8 short lines. English.",
            f"{repomap(proj)}\n\n{relevant(proj, 'main', 9000)}",
        )
        return ans.strip()

    def show(self):
        proj = self._need()
        files = [f for f in proj.files() if not f.startswith(".")]
        main = next((f for f in ("main.py", "index.html", "index.js") if f in files), files[0] if files else None)
        return f"{proj.folder.name}: {', '.join(files)}\n\n=== {main} ===\n{(proj.read(main) or '')[:3000]}" if main else "No files yet."

    def open_vscode(self):
        proj = self._need()
        main = next((f for f in ("main.py", "index.html", "index.js") if f in proj.files()), None)
        proj.open_in_vscode(main)
        return (
            f"Opened {proj.folder.name} in VS Code" + (f" at {main}" if main else "") + ". Its Run and Test tasks are set up (Terminal > Run Task)."
        )

    def undo(self):
        proj = self._need()
        c = proj.undo()
        return f"Took back: {c['what']} (now at {proj.log(1)[0]['id']}). 'redo' brings it back."

    def redo(self):
        proj = self._need()
        c = proj.redo()
        return f"Back to {c['id']}: {c['what']}."

    def history(self):
        proj = self._need()
        return "\n".join(f"{x['id']}  {x['when']}  {x['what']}" for x in proj.log())

    def what_changed(self):
        proj = self._need()
        d = proj.diff()
        stat = "\n".join(ln for ln in d.splitlines() if "|" in ln and ("+" in ln or "-" in ln))[:1500]
        return f"Last change ({proj.log(1)[0]['what']}):\n{stat or d[:1500]}"

    def list_projects(self):
        ps = sorted(p for p in self.projects_dir.glob("*") if (p / ".git").exists()) if self.projects_dir.exists() else []
        return ("Projects: " + ", ".join(p.name for p in ps) + ".") if ps else "No projects yet."

    def open_project(self, name):
        p = Path(name)
        folder = p if p.is_absolute() else self.projects_dir / name
        if not folder.is_dir():
            raise ProjectError(f"no project folder {folder}")
        proj = Project.open(folder)
        run = "python main.py" if (folder / "main.py").exists() else "node index.js" if (folder / "index.js").exists() else None
        self.state.update(project=str(proj.folder), run=self.state.get("run") if self.state.get("project") == str(proj.folder) else run)
        return f"Working on {proj.folder.name} ({proj.kind}, {len(proj.files())} files, {len(proj.log())} version(s))."

    def _need(self):
        proj = self.project()
        if not proj:
            raise ProjectError("no project yet: ask me to build one, or 'open project <name or folder>'")
        return proj
