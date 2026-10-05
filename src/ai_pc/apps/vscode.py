"""Visual Studio Code by its own files and command line (the VS Code installed on this PC). A project folder (Python,
Node/TypeScript, Go, Rust, C++/CMake, .NET, Java/Maven, Android/Gradle, PHP) is set up for VS Code: .vscode/tasks.json
with build and test tasks that use the toolchains in tools/ (their settings folders kept in the project, as here),
settings.json, launch.json for debugging and extensions.json with the recommended extensions. Checked by running the
same build and test commands VS Code will run, and every file is read back as JSON. The installed extensions are listed
from 'code --list-extensions'; installing an extension or opening a folder in VS Code (a window) waits for a yes.

  'vscode setup C:\\code\\shop'   'vscode set up the last project'   'which vscode extensions do I have'   'install the go extension in vscode'
  'open the last project in vscode'
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

NAME, LABEL = "vscode", "VS Code: projects set up with build/test tasks, debug and recommended extensions, all checked; extensions listed; install/open after a yes"
EXAMPLES = ["vscode setup the last project", "which vscode extensions do I have", "install the python extension in vscode", "open the last project in vscode"]
OUTWARD = {"install", "open"}
CODE = shutil.which("code") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd")
NOWIN = 0x08000000

RECOMMEND = {"python": ["ms-python.python"], "node": ["dbaeumer.vscode-eslint"], "go": ["golang.go"], "rust": ["rust-lang.rust-analyzer"],
             "cmake": ["ms-vscode.cmake-tools", "llvm-vs-code-extensions.vscode-clangd"], "dotnet": ["ms-dotnettools.csdevkit"],
             "maven": ["vscjava.vscode-java-pack"], "gradle": ["vscjava.vscode-java-pack", "vscjava.vscode-gradle"], "php": ["bmewburn.vscode-intelephense-client"]}
EXTENSIONS = {"python": "ms-python.python", "pylance": "ms-python.vscode-pylance", "jupyter": "ms-toolsai.jupyter", "go": "golang.go",
              "rust": "rust-lang.rust-analyzer", "c++": "ms-vscode.cpptools", "cpp": "ms-vscode.cpptools", "cmake": "ms-vscode.cmake-tools",
              "clangd": "llvm-vs-code-extensions.vscode-clangd", "java": "vscjava.vscode-java-pack", "gradle": "vscjava.vscode-gradle",
              "c#": "ms-dotnettools.csdevkit", "csharp": "ms-dotnettools.csdevkit", "php": "bmewburn.vscode-intelephense-client",
              "eslint": "dbaeumer.vscode-eslint", "prettier": "esbenp.prettier-vscode", "docker": "ms-azuretools.vscode-docker",
              "gitlens": "eamodio.gitlens", "live server": "ritwickdey.liveserver", "tailwind": "bradlc.vscode-tailwindcss",
              "markdown": "yzhang.markdown-all-in-one", "flutter": "dart-code.flutter", "dart": "dart-code.dart-code"}
MARKERS = [("Cargo.toml", "rust"), ("go.mod", "go"), ("CMakeLists.txt", "cmake"), ("pom.xml", "maven"), ("settings.gradle.kts", "gradle"),
           ("settings.gradle", "gradle"), ("package.json", "node"), ("composer.json", "php"), ("pyproject.toml", "python"),
           ("requirements.txt", "python"), ("setup.py", "python")]


def kind_of(folder):
    folder = Path(folder)
    for marker, kind in MARKERS:
        if (folder / marker).exists():
            return kind
    if any(folder.glob("*.slnx")) or any(folder.glob("*.sln")) or any(folder.glob("*.csproj")):
        return "dotnet"
    if any(folder.glob("*.py")):
        return "python"
    if any(folder.glob("*.php")) or any(folder.glob("public/*.php")):
        return "php"
    return None


def env_change(env):
    """What a module's env() changes, as VS Code task options: PATH as 'added dirs;${env:PATH}'."""
    out = {k: v for k, v in env.items() if os.environ.get(k) != v and k.upper() != "PATH"}
    path, base = env.get("PATH", ""), os.environ.get("PATH", "")
    if path != base and path.endswith(base):
        out["PATH"] = path[: len(path) - len(base)] + "${env:PATH}"
    return out


def plan(kind, folder):
    """{'env': full env, 'build': [cmd...], 'test': [cmd...], 'settings': {...}, 'launch': [...]} for this project, using tools/."""
    folder = Path(folder)
    if kind == "python":
        from ai_pc.apps.pycharm import venv_python
        py = venv_python(folder)
        pkg = next((p.parent.name for p in folder.glob("*/__main__.py") if p.parent.name not in ("tests", ".venv")), None)
        return {"env": dict(os.environ, PYTHONIOENCODING="utf-8"), "build": [[str(py), "-m", "compileall", "-q", "-x", r"[\\/]\.?venv[\\/]", "."]],
                "test": [str(py), "-m", "unittest", "discover", "-v"],
                "settings": {"python.defaultInterpreterPath": str(py), "python.testing.unittestEnabled": True,
                             "python.testing.unittestArgs": ["-v", "-s", ".", "-p", "test_*.py"]},
                "launch": [{"name": f"Run {pkg}", "type": "debugpy", "request": "launch", "module": pkg} if pkg else
                           {"name": "Run this file", "type": "debugpy", "request": "launch", "program": "${file}"}]}
    if kind == "node":
        from ai_pc.apps.nodejs import node_exe
        tests = sorted(str(p.relative_to(folder)).replace("\\", "/") for pat in ("test/**/*.test.*", "tests/**/*.test.*") for p in folder.glob(pat))
        main = next((m for m in ("src/main.ts", "src/index.ts", "src/main.js", "index.js") if (folder / m).exists()), None)
        return {"env": dict(os.environ, NO_COLOR="1"), "build": [], "test": [node_exe(), "--test", *tests],
                "settings": {"typescript.preferences.importModuleSpecifierEnding": "js"},
                "launch": [{"name": f"Run {main}", "type": "node", "request": "launch", "program": "${workspaceFolder}/" + main}] if main else []}
    if kind == "go":
        from ai_pc.apps import goland as g
        cmd = next((str(p.parent.relative_to(folder)).replace("\\", "/") for p in folder.glob("cmd/*/main.go")), ".")
        e = g.env()
        return {"env": e, "build": [[str(g.GO), "build", "./..."]], "test": [str(g.GO), "test", "./..."],
                "settings": {"go.goroot": str(g.GOROOT), "go.alternateTools": {"go": str(g.GO)},
                             "go.toolsEnvVars": {k: e[k] for k in ("GOPATH", "GOCACHE", "GOENV", "GOTOOLCHAIN", "GOFLAGS", "APPDATA", "LOCALAPPDATA")}},
                "launch": [{"name": "Run", "type": "go", "request": "launch", "mode": "auto", "program": "${workspaceFolder}/" + cmd}]}
    if kind == "rust":
        from ai_pc.apps import rustrover as r
        e = r.env()
        return {"env": e, "build": [[str(r.CARGO), "build"]], "test": [str(r.CARGO), "test"],
                "settings": {"rust-analyzer.server.path": str(r.TOOLCHAIN / "bin" / "rust-analyzer.exe"),
                             "rust-analyzer.server.extraEnv": {"CARGO_HOME": e["CARGO_HOME"], "CARGO": str(r.CARGO), "RUSTC": str(r.TOOLCHAIN / "bin" / "rustc.exe")}},
                "launch": []}
    if kind == "cmake":
        from ai_pc.apps import clion as c
        b = "build/vscode"
        return {"env": c.env(), "build": [[str(c.CMAKE), "-S", ".", "-B", b, "-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={c.NINJA}"], [str(c.CMAKE), "--build", b]],
                "test": [str(c.CTEST), "--test-dir", b, "--output-on-failure"],
                "settings": {"cmake.cmakePath": str(c.CMAKE), "cmake.generator": "Ninja", "cmake.buildDirectory": "${workspaceFolder}/build/vscode",
                             "cmake.configureSettings": {"CMAKE_MAKE_PROGRAM": str(c.NINJA), "CMAKE_CXX_COMPILER": str(c.CLANG / "clang++.exe")},
                             "clangd.path": str(c.CLANG / "clangd.exe"), "clangd.arguments": ["--compile-commands-dir=${workspaceFolder}/build/vscode"]},
                "launch": []}
    if kind == "dotnet":
        from ai_pc.apps import visualstudio as v
        sln = next(iter(sorted(folder.glob("*.slnx")) + sorted(folder.glob("*.sln")) + sorted(folder.glob("*.csproj"))), None)
        target = [sln.name] if sln else []
        return {"env": v.env(), "build": [[str(v.DOTNET), "build", *target]], "test": [str(v.DOTNET), "test", *target],
                "settings": {"dotnet.dotnetPath": str(v.HOME)}, "launch": []}
    if kind == "maven":
        from ai_pc.apps import intellij as j
        return {"env": j.env(), "build": [[str(j.MVN), "-q", "compile"]], "test": [str(j.MVN), "-q", "test"],
                "settings": {"java.jdt.ls.java.home": str(j.JDK), "maven.executable.path": str(j.MVN)}, "launch": []}
    if kind == "gradle":
        from ai_pc.apps import androidstudio as a
        return {"env": a.env(), "build": [[str(a.GRADLE), "--no-daemon", "assembleDebug"]], "test": [str(a.GRADLE), "--no-daemon", "testDebugUnitTest"],
                "settings": {"java.jdt.ls.java.home": str(a.JDK), "java.import.gradle.home": str(Path(a.GRADLE).parent.parent),
                             "java.import.gradle.java.home": str(a.JDK)}, "launch": []}
    if kind == "php":
        from ai_pc.apps import php as p
        return {"env": p.env(), "build": [[str(p.PHP), "-n", "-l", f] for f in p.php_files(folder)][:1], "test": [str(p.PHP), "-n", "tests/run.php"],
                "settings": {"php.validate.executablePath": str(p.PHP), "intelephense.environment.phpVersion": p.version()}, "launch": []}
    return None


def task(label, cmd, envc, group=None, depends=None):
    t = {"label": label, "type": "shell" if str(cmd[0]).lower().endswith((".cmd", ".bat")) else "process", "command": str(cmd[0]),
         "args": [str(a) for a in cmd[1:]], "options": {"cwd": "${workspaceFolder}", "env": envc}, "problemMatcher": []}
    if group:
        t["group"] = {"kind": group, "isDefault": True}
    if depends:
        t["dependsOn"] = depends
    return t


def execute(kind, cmd, env, cwd):
    """Run a task's command as VS Code would (same command, same environment), on the hidden desktop."""
    from ai_pc.core import hidden_desktop
    if kind == "dotnet":
        from ai_pc.apps.visualstudio import Session
        s = Session()
        try:
            return s.run(*cmd[1:], cwd=cwd)
        finally:
            s.close()
    line = ["cmd", "/c", *cmd] if str(cmd[0]).lower().endswith((".cmd", ".bat")) else cmd
    rc, out, err, timed_out = hidden_desktop.run([str(c) for c in line], timeout=1800, cwd=str(cwd), env=env)
    return rc == 0 and not timed_out, out + err


def extensions():
    from ai_pc.core import hidden_desktop
    rc, out, err, _ = hidden_desktop.run(["cmd", "/c", CODE, "--list-extensions", "--show-versions"], timeout=120)
    return [ln.strip() for ln in out.splitlines() if re.match(r"^[\w.-]+\.[\w.-]+@", ln.strip())]


def target_folder(text, ctx):
    from ai_pc.apps.appschat import find_file
    m = re.search(r"([a-z]:\\[^\"<>|?*\n]+)", text, re.I)
    if m and Path(m.group(1).strip().rstrip(".")).is_dir():
        return str(Path(m.group(1).strip().rstrip(".")))
    f = find_file(text, ctx)
    if f:
        return str(Path(f).parent)
    return (ctx.get("memo") or {}).get("project")


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bvs ?code\b|\bvisual studio code\b", c):
        return None
    m = re.search(r"\binstall\b(?:\s+the)?\s+(.+?)\s+extension\b|\bextension\s+([\w-]+\.[\w.-]+)", c)
    if m and re.search(r"\binstall\b", c):
        want = (m.group(1) or m.group(2) or "").strip()
        ext = EXTENSIONS.get(want) or (want if re.fullmatch(r"[\w-]+\.[\w.-]+", want) else None)
        return {"op": "install", "id": ext, "asked": want}
    if re.search(r"\bextensions?\b", c):
        return {"op": "extensions"}
    folder = target_folder(text, ctx)
    if re.search(r"\bopen\b", c):
        return {"op": "open", "folder": folder}
    if re.search(r"\bset ?up\b|\bconfigure\b|\btasks?\b|\bworkspace\b|\bprepare\b|\bready\b", c):
        return {"op": "setup", "folder": folder}
    return None


def preview(op, ctx):
    if op["op"] == "install":
        if not op.get("id"):
            op["blocked"] = True
            return f"I don't know a VS Code extension called '{op.get('asked')}'; give its id (publisher.name), e.g. ms-python.python."
        have = [e for e in extensions() if e.lower().startswith(op["id"].lower() + "@")]
        if have:
            op["blocked"] = True
            return f"VS Code already has {have[0]}: nothing to install."
        return f"Install the VS Code extension {op['id']} from the Visual Studio Marketplace into your VS Code."
    if not op.get("folder") or not Path(op["folder"]).is_dir():
        op["blocked"] = True
        return "Which folder? Give its full path, or make a project first (for example: python app called Shop)."
    return f"Open {op['folder']} in VS Code (a VS Code window opens on your screen)."


def run(op, ctx):
    if not Path(CODE).exists():
        return "VS Code is not installed on this PC (code.cmd not found)."
    if op["op"] == "extensions":
        exts = extensions()
        return f"VS Code has {len(exts)} extension(s): " + (", ".join(exts) if exts else "none") + "."
    if op["op"] == "install":
        from ai_pc.core import hidden_desktop
        rc, out, err, _ = hidden_desktop.run(["cmd", "/c", CODE, "--install-extension", op["id"]], timeout=600)
        there = any(e.lower().startswith(op["id"].lower() + "@") for e in extensions())
        return f"VS Code extension {op['id']}: " + ("installed. Checked: VS Code now lists it." if there else f"NOT installed: {(err or out).strip()[-300:]}")
    if op["op"] == "open":
        subprocess.Popen(["cmd", "/c", CODE, op["folder"]], creationflags=NOWIN)
        return f"Opening {op['folder']} in VS Code."
    folder = op.get("folder")
    if not folder or not Path(folder).is_dir():
        return "Which folder should VS Code get set up for? Give its full path, or make a project first (for example: python app called Shop)."
    folder = Path(folder).resolve()
    kind = kind_of(folder)
    p = plan(kind, folder) if kind else None
    if not p:
        return f"{folder.name}: no project VS Code tasks can be made for (no pyproject.toml, package.json, go.mod, Cargo.toml, CMakeLists.txt, .sln, pom.xml, Gradle or PHP files)."
    envc = env_change(p["env"])
    tasks = []
    for i, cmd in enumerate(p["build"]):  # steps run in order; the last is 'build' (Ctrl+Shift+B)
        label = "build" if i == len(p["build"]) - 1 else f"build step {i + 1}"
        tasks.append(task(label, cmd, envc, "build" if label == "build" else None, [tasks[-1]["label"]] if tasks else None))
    tasks.append(task("test", p["test"], envc, "test", ["build"] if p["build"] else None))
    files = {"tasks.json": {"version": "2.0.0", "tasks": tasks},
             "settings.json": {"editor.formatOnSave": True, "files.trimTrailingWhitespace": True, **p["settings"]},
             "extensions.json": {"recommendations": RECOMMEND.get(kind, [])}}
    if p["launch"]:
        files["launch.json"] = {"version": "0.2.0", "configurations": p["launch"]}
    vs = folder / ".vscode"
    vs.mkdir(exist_ok=True)
    for name, data in files.items():
        (vs / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    readable = all(json.loads((vs / n).read_text(encoding="utf-8")) == d for n, d in files.items())
    ok_b, log_b = True, ""
    for cmd in p["build"]:
        ok, log = execute(kind, cmd, p["env"], folder)
        ok_b, log_b = ok_b and ok, log_b + log
        if not ok:
            break
    ok_t, log_t = execute(kind, p["test"], p["env"], folder) if ok_b else (False, "")
    have = {e.split("@")[0].lower() for e in extensions()}
    missing = [e for e in RECOMMEND.get(kind, []) if e.lower() not in have]
    checks = [(f"{', '.join(files)} written and read back as JSON", readable),
              ("the build task's command runs clean" if p["build"] else "no build step needed", ok_b),
              ("the test task's command passes", ok_t)]
    bad = [w for w, good in checks if not good]
    ctx.setdefault("memo", {})["project"] = str(folder)
    return (f"VS Code set up for {folder} ({kind}): .vscode/ with tasks 'build' and 'test' (Ctrl+Shift+B builds), " +
            ("debug config, " if p["launch"] else "") + "settings and recommended extensions. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + (log_b + log_t).strip()[-400:]) +
            (f" Recommended extensions not installed yet: {', '.join(missing)} (say 'install the ... extension in vscode')." if missing else
             " Its recommended extensions are already installed."))
