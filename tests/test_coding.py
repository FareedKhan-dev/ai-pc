"""Coding agent tests with a scripted model (no network): a first version with a bug repaired from its own test
failure, an edit by search/replace blocks, an edit that does not fit reported, risky code held back until a yes,
undo and redo through git, paths outside the project refused, VS Code's workspace files, and web pages checked in
headless Chrome (a page with a script error fails, a clean one passes).

  .venv\\Scripts\\python.exe tests\\test_coding.py
About half a minute (it makes real virtual environments and runs real tests).
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from harness.coding import verify as V  # noqa: E402
from harness.coding.codechat import CodeChat, parse_files  # noqa: E402
from harness.coding.project import Project, ProjectError  # noqa: E402

OUT = ROOT / "out" / "_tests" / "code" / "engine"
FAILS = []


def check(name, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    if not ok:
        FAILS.append(name)


class Script:
    """A model that answers from a list, and records what it was asked."""

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def _call(self, tier, messages):
        self.asked.append(messages[-1]["content"])

        class R:
            pass
        r = R()
        r.text = self.answers.pop(0) if self.answers else ""
        return r

    def cost(self):
        return 0, 0.0


BUGGY = """=== META ===
name: temp_converter
kind: python
run: python main.py 100
about: Converts Celsius to Fahrenheit
=== END ===
```python
=== FILE: main.py ===
import argparse


def c_to_f(c):
    return c * 9 / 5 + 23  # wrong: should be + 32


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("celsius", type=float)
    a = ap.parse_args()
    print(f"{a.celsius} C = {c_to_f(a.celsius)} F")


if __name__ == "__main__":
    main()
=== END ===
```
=== FILE: test_main.py ===
import unittest
from main import c_to_f


class T(unittest.TestCase):
    def test_freezing(self):
        self.assertEqual(c_to_f(0), 32)

    def test_boiling(self):
        self.assertEqual(c_to_f(100), 212)


if __name__ == "__main__":
    unittest.main()
=== END ==="""
FIX = """FILE: main.py
<<<<<<< SEARCH
    return c * 9 / 5 + 23  # wrong: should be + 32
=======
    return c * 9 / 5 + 32
>>>>>>> REPLACE"""
EDIT = """FILE: main.py
<<<<<<< SEARCH
def main():
=======
def f_to_c(f):
    return (f - 32) * 5 / 9


def main():
>>>>>>> REPLACE
FILE: test_main.py
<<<<<<< SEARCH
from main import c_to_f
=======
from main import c_to_f, f_to_c
>>>>>>> REPLACE
FILE: test_main.py
<<<<<<< SEARCH
    def test_boiling(self):
=======
    def test_back(self):
        self.assertAlmostEqual(f_to_c(212), 100)

    def test_boiling(self):
>>>>>>> REPLACE"""
BAD_EDIT = """FILE: main.py
<<<<<<< SEARCH
this text is not in the file
=======
anything
>>>>>>> REPLACE"""
RISKY = """=== META ===
name: cleaner
kind: python
run: python main.py
about: deletes temp files
=== END ===
=== FILE: main.py ===
import os
import shutil


def main():
    shutil.rmtree("C:/Users/Public/Temp")


if __name__ == "__main__":
    main()
=== END ==="""


def chat_flow():
    pl = Script([BUGGY, FIX, EDIT, BAD_EDIT])
    c = CodeChat.start(planner=pl, chats_dir=OUT / "chats", projects_dir=OUT / "projects")
    r = c.say("make a python script that converts celsius to fahrenheit")
    proj = c.project()
    check("new project: the test failure went back to the model and was repaired", "repaired in 1 round" in r and "tests: 2/2 pass" in r.lower(), r)
    check("new project: it ran and printed the right answer", "100.0 C = 212.0 F" in r, r)
    check("new project: the model saw the failing test's output", "CHECK FAILED: tests" in pl.asked[1] and "AssertionError" in pl.asked[1], pl.asked[1][:300])
    check("new project: one version in git, its own .venv, code fences forgiven", len(proj.log()) == 1 and (proj.folder / ".venv" / "Scripts" / "python.exe").exists()
          and proj.read("main.py").startswith("import argparse"))
    vs = json.loads((proj.folder / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    check("VS Code: Run and Test tasks and the project's interpreter are set up", [t["label"] for t in vs["tasks"]] == ["Run", "Test"] and
          ".venv" in (proj.folder / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    r = c.say("add fahrenheit to celsius as well")
    check("edit: search/replace blocks applied, tests 3/3, a second version", "Changed main.py, test_main.py" in r and "tests: 3/3 pass" in r.lower()
          and len(proj.log()) == 2, r)
    check("edit: the model was given the files and their functions", "def c_to_f(c)" in pl.asked[2] and "=== FILE: main.py ===" in pl.asked[2])
    r = c.say("rename everything")
    check("edit: a change that does not fit the files is reported, nothing committed", "did not fit" in r and len(proj.log()) == 2, r)
    r = c.say("undo")
    check("undo: back one version through git", "Took back" in r and len(proj.log()) == 1 and "f_to_c" not in proj.read("main.py"), r)
    r = c.say("redo")
    check("redo: forward again", "f_to_c" in proj.read("main.py"), r)
    r = c.say("run it with 37")
    check("run: with other arguments", "37.0 C = 98.6" in r, r)
    r = c.say("history")
    check("history: the versions with what each did", r.count("\n") >= 1 and "first version" in r, r)


def risky():
    pl = Script([RISKY])
    c = CodeChat.start(planner=pl, chats_dir=OUT / "chats", projects_dir=OUT / "projects")
    r = c.say("make a python script that cleans my temp folder")
    check("risky code is saved but not run, and the line is shown", "not run" in r and "deletes files" in r and "rmtree" in r and c.state["pending"], r)
    r = c.say("no")
    check("'no' leaves it unrun", "Not run" in r and not c.state["pending"], r)


def project_rules():
    p = Project.create(OUT / "projects" / "rules", "python")
    try:
        p.write({"../escape.py": "print(1)"})
        check("a path outside the project is refused", False)
    except ProjectError:
        check("a path outside the project is refused", True)
    p.write({"a.py": "x = 1\n"})
    ch, probs = p.apply_edits("FILE: a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE")
    check("search/replace changes exactly the matched text", ch == ["a.py"] and p.read("a.py").strip() == "x = 2")
    ch, probs = p.apply_edits("FILE: new/b.py\n<<<<<<< SEARCH\n=======\ny = 3\n>>>>>>> REPLACE")
    check("an empty search makes a new file", ch == ["new/b.py"] and p.read("new/b.py").strip() == "y = 3")
    hits = V.risks(type("P", (), {"files": lambda self: ["m.py"], "read": lambda self, f: "import subprocess\nsubprocess.run(['format','C:'])\n# os.remove('x')\n"})())
    check("risk scan: running other programs is flagged, commented lines are not", {h["what"] for h in hits} == {"runs other programs"}
          and all(h["line"] != 3 for h in hits), str(hits))
    meta, files = parse_files("```\n=== META ===\nname: x\n=== END ===\n=== FILE: main.py ===\nprint('hi')\n=== END ===\n```")
    check("model answers: META and FILE blocks read through code fences", meta == {"name": "x"} and files == {"main.py": "print('hi')"})


def web():
    good = Project.create(OUT / "projects" / "web_good", "web")
    good.write({"index.html": "<!doctype html><html><head><link rel='stylesheet' href='style.css'></head><body><h1>Khan Electronics</h1>"
                              "<p>Quality appliances in Lahore since 1998.</p><script src='script.js'></script></body></html>",
                "style.css": "body{font-family:Segoe UI}", "script.js": "document.querySelector('h1').textContent += '!';"})
    res = V.web(good, "index.html")
    check("web: a clean page loads with content and no console errors", all(c["ok"] for c in res), str([(c["what"], c["detail"][:100]) for c in res if not c["ok"]]))
    bad = Project.create(OUT / "projects" / "web_bad", "web")
    bad.write({"index.html": "<!doctype html><html><body><h1>Broken page here</h1><p>some words for the check</p><script>notAFunction();</script></body></html>"})
    res = V.web(bad, "index.html")
    check("web: a page with a script error fails the console check", any(not c["ok"] and "console" in c["what"] for c in res), str(res)[:300])
    missing = Project.create(OUT / "projects" / "web_missing", "web")
    missing.write({"index.html": "<!doctype html><html><body><h1>Shop</h1><p>Words enough to count here</p><script src='nope.js'></script></body></html>"})
    res = V.web(missing, "index.html")
    check("web: a missing script file fails the 'every file it links to' check", any(not c["ok"] and "links to" in c["what"] for c in res), str(res)[:300])


if __name__ == "__main__":
    t0 = time.perf_counter()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    chat_flow()
    risky()
    project_rules()
    web()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}  ({time.perf_counter() - t0:.0f} s)")
    sys.exit(1 if FAILS else 0)
