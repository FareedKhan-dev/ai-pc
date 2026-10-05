"""Check that every program, model, environment and Python package AI PC uses is present on this PC.

  ai-pc doctor            a table: present or missing, version, and what uses it
  ai-pc doctor --json     the same as JSON, with the path of each

Each program is found the way the code that uses it finds it (the same constant or function), so the check matches
what will really run. Nothing that could open a window is started: versions come from the files themselves, and only
plain command-line tools are run (hidden, with --version). Exit code 1 when something required is missing.
"""

import argparse
import importlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import winreg
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement

from ai_pc.core.paths import MODELS, ROOT, TOOLS

NO_WINDOW = 0x08000000


@dataclass
class Tool:
    name: str
    group: str
    used_by: str
    find: Callable[[], object]
    version: Callable[[Path], str] = field(default=lambda p: file_version(p))
    optional: bool = False  # only one extra feature needs it
    packages: Callable[[], list[str]] | None = None  # for an environment: the requirements its Python must meet


@dataclass
class Result:
    tool: Tool
    path: Path | None
    version: str
    source: bool  # a SOURCE.txt records where it was downloaded from and how it was checked
    problems: list[str] = field(default_factory=list)  # packages missing or at a version outside the range

    @property
    def ok(self) -> bool:
        return self.path is not None and self.path.exists() and not self.problems


# ---------------------------------------------------------------- finding things
def attr(module: str, name: str, *parts: str) -> Callable[[], object]:
    def find() -> object:
        value = getattr(importlib.import_module(module), name)
        return Path(value).joinpath(*parts) if value is not None else None

    return find


def call(module: str, function: str, *parts: str) -> Callable[[], object]:
    def find() -> object:
        value = getattr(importlib.import_module(module), function)()
        return Path(value).joinpath(*parts) if value is not None else None

    return find


def which(command: str) -> Callable[[], object]:
    return lambda: shutil.which(command)


def under(folder: Path, pattern: str) -> Callable[[], object]:
    return lambda: next(iter(sorted(folder.glob(pattern), reverse=True)), None) if folder.exists() else None


def office(exe: str) -> Callable[[], object]:
    """An Office program from Windows' App Paths list (where Click-to-Run Office registers itself)."""

    def find() -> object:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                    return winreg.QueryValue(k, None)
            except OSError:
                continue
        return None

    return find


def com_class(progid: str) -> Callable[[], object]:
    """A COM class's server file (for programs used only through COM, like Access's database engine)."""

    def find() -> object:
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\CLSID") as k:
                clsid = winreg.QueryValue(k, None)
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\InprocServer32", 0, winreg.KEY_READ | view) as k:
                        return os.path.expandvars(winreg.QueryValue(k, None))
                except OSError:
                    continue
        except OSError:
            return None
        return None

    return find


def vocaela_file(flag: str | None) -> Callable[[], object]:
    """The click-model server (flag None) or the file given after a flag in its command line."""

    def find() -> object:
        cmd: list[str] = importlib.import_module("ai_pc.core.config").VOCAELA_CMD
        return cmd[0] if flag is None else cmd[cmd.index(flag) + 1]

    return find


def venv_python(folder: str) -> Callable[[], object]:
    return lambda: ROOT / folder / "Scripts" / "python.exe"


# ---------------------------------------------------------------- versions
def file_version(path: Path) -> str:
    """The version stored in a Windows program file (nothing is started)."""
    import win32api

    try:
        lang, codepage = win32api.GetFileVersionInfo(str(path), "\\VarFileInfo\\Translation")[0]
        text = win32api.GetFileVersionInfo(str(path), f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\ProductVersion")
        if text and str(text).strip():
            return str(text).strip()
    except Exception:  # noqa: BLE001 - not every file carries a version
        pass
    try:
        info = win32api.GetFileVersionInfo(str(path), "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001
        return ""


def run_version(*args: str, pattern: str = r"\d+\.\d+[\w.+-]*", env: Callable[[], dict[str, str]] | None = None) -> Callable[[Path], str]:
    """Run a command-line tool (hidden) to print its version; env keeps a tool's settings in the project."""

    def get(path: Path) -> str:
        try:
            p = subprocess.run(
                [str(path), *args],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=NO_WINDOW,
                cwd=str(ROOT),
                env=env() if env else None,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        m = re.search(pattern, (p.stdout or "") + (p.stderr or ""))
        return (m.group(1) if m.groups() else m.group(0)) if m else ""

    return get


def folder_version(pattern: str = r"\d+(?:\.\d+)+") -> Callable[[Path], str]:
    """The version written in the folder names on the path (gradle-9.8.0, QGIS 4.2.3)."""

    def get(path: Path) -> str:
        for part in reversed(path.parts):
            m = re.search(pattern, part)
            if m:
                return m.group(0)
        return ""

    return get


def text_version(relative: str, pattern: str) -> Callable[[Path], str]:
    """A version read from a text file near the program (source.properties, flutter.version.json)."""

    def get(path: Path) -> str:
        for base in (path, *path.parents):
            f = base / relative
            if f.is_file():
                m = re.search(pattern, f.read_text(encoding="utf-8", errors="replace"))
                return m.group(1) if m else ""
        return ""

    return get


def sibling_version(name: str) -> Callable[[Path], str]:
    return lambda p: file_version(p.with_name(name)) if p.with_name(name).exists() else file_version(p)


def registry_version(key: str, name: str) -> Callable[[Path], str]:
    """A version Windows keeps in the registry (Windows PowerShell's engine version, 5.1)."""

    def get(path: Path) -> str:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            return str(winreg.QueryValueEx(k, name)[0])

    return get


def newest_version_folder(path: Path) -> str:
    """CapCut keeps each version in a folder named after it, next to its launcher."""
    names = [d.name for d in path.parent.iterdir() if d.is_dir() and re.fullmatch(r"\d+(?:\.\d+)+", d.name)]
    return max(names, key=lambda n: tuple(int(x) for x in n.split("."))) if names else ""


def size(path: Path) -> str:
    """For models: how big the file (or folder) is."""
    n = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else path.stat().st_size
    return f"{n / 2**20:,.0f} MB" if n >= 2**20 else f"{n / 2**10:,.0f} KB"


def source_version(path: Path, tools: Path | None = None) -> str:
    """The version in the download address recorded in the tool folder's SOURCE.txt."""
    tools = tools or TOOLS
    if tools not in path.parents:
        return ""
    f = tools / path.relative_to(tools).parts[0] / "SOURCE.txt"
    words = f.read_text(encoding="utf-8", errors="replace").split() if f.is_file() else []
    if not words:
        return ""
    number = r"(?<![\w.])v?(\d+(?:\.\d+)+)"
    m = re.search(number, Path(words[0]).name.replace("_", "-")) or re.search(number, words[0])
    return m.group(1) if m else ""


def tidy(version: str) -> str:
    """A plain dotted version where there is one (PrusaSlicer-2.9.6 -> 2.9.6, 3,7,9,0 -> 3.7.9.0); other text as it is."""
    v = version.replace(",", ".").strip()
    if re.fullmatch(r"0(?:\.0)*", v):
        return ""
    m = re.search(r"\d+(?:\.\d+)+", v)
    return m.group(0) if m else v


# ---------------------------------------------------------------- Python packages
def requirements(source: str) -> Callable[[], list[str]]:
    """Requirement lines: pyproject.toml's dependencies or one of its dependency groups, or a requirements file."""

    def get() -> list[str]:
        if source.endswith(".txt"):
            lines = (ROOT / source).read_text(encoding="utf-8").splitlines()
            return [s for s in (line.split("#")[0].strip() for line in lines) if s and not s.startswith("-")]
        pyproject = ROOT / "pyproject.toml"
        if source == "dependencies" and not pyproject.is_file():  # installed from a wheel: its metadata has the list
            return [r for r in importlib.metadata.requires("ai-pc") or [] if "extra ==" not in r]
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return list(data["project"]["dependencies"] if source == "dependencies" else data["dependency-groups"][source])

    return get


# run by the environment's own Python: the installed version of each package named on the command line
INSTALLED = """
import importlib.metadata as m, json, sys
found = {}
for name in sys.argv[1:]:
    try:
        found[name] = m.version(name)
    except m.PackageNotFoundError:
        found[name] = None
print(json.dumps(found))
"""


def package_problems(python: Path, wanted: list[str]) -> tuple[int, list[str]]:
    """How many requirements apply here, and the ones the environment does not meet (missing, or outside the range)."""
    reqs = [r for r in map(Requirement, wanted) if r.marker is None or r.marker.evaluate()]
    p = subprocess.run(
        [str(python), "-c", INSTALLED, *(r.name for r in reqs)],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=NO_WINDOW,
        cwd=str(ROOT),
        check=True,
    )
    installed: dict[str, str | None] = json.loads(p.stdout)
    problems = []
    for r in reqs:
        have = installed.get(r.name)
        if have is None:
            problems.append(f"{r.name}{r.specifier} is not installed")
        elif not r.specifier.contains(have, prereleases=True):
            problems.append(f"{r.name}{r.specifier}: {have} is installed")
    return len(reqs), problems


# ---------------------------------------------------------------- what AI PC uses
P, W, M, E, PK = "Programs in tools/", "Installed on Windows", "Models", "Environments and developer tools", "Python packages"
GROUPS = (P, W, M, E, PK)
TOOL_LIST = [
    # programs kept in the project's tools/ folder
    Tool("7-Zip", P, "apps: 7-Zip archives", attr("ai_pc.apps.sevenzip", "SEVEN")),
    Tool(
        "Android SDK (adb)",
        P,
        "apps: Android Studio",
        attr("ai_pc.apps.androidstudio", "SDK", "platform-tools", "adb.exe"),
        text_version("source.properties", r"Pkg\.Revision=([\d.]+)"),
    ),
    Tool("Gradle", P, "apps: Android Studio", attr("ai_pc.apps.androidstudio", "GRADLE"), folder_version()),
    Tool("Java JDK", P, "apps: Android Studio, IntelliJ", attr("ai_pc.apps.androidstudio", "JDK", "bin", "java.exe")),
    Tool("Maven", P, "apps: IntelliJ", attr("ai_pc.apps.intellij", "MVN"), folder_version()),
    Tool("Arduino CLI", P, "apps: Arduino", attr("ai_pc.apps.arduino", "CLI")),
    Tool("Audacity", P, "apps: Audacity", attr("ai_pc.apps.audacity", "EXE")),
    Tool("AutoHotkey", P, "apps: AutoHotkey", attr("ai_pc.apps.autohotkey", "EXE")),
    Tool("Blender", P, "3D", call("ai_pc.three.blender", "exe")),
    Tool("Calibre", P, "apps: ebooks", attr("ai_pc.apps.calibre", "BIN", "ebook-convert.exe")),
    Tool("CMake", P, "apps: CLion (C++)", attr("ai_pc.apps.clion", "CMAKE")),
    Tool("Ninja", P, "apps: CLion (C++)", attr("ai_pc.apps.clion", "NINJA"), run_version("--version")),
    Tool("LLVM-MinGW (clang)", P, "apps: CLion, RustRover", attr("ai_pc.apps.clion", "CLANG", "clang++.exe"), run_version("--version")),
    Tool("draw.io", P, "apps: diagrams", call("ai_pc.apps.drawio", "exe")),
    Tool(
        ".NET SDK",
        P,
        "apps: Visual Studio (C#)",
        attr("ai_pc.apps.visualstudio", "DOTNET"),
        lambda p: next((d.name for d in sorted((p.parent / "sdk").glob("*"), reverse=True) if d.is_dir()), ""),
    ),
    Tool(
        "Flutter",
        P,
        "apps: Flutter",
        attr("ai_pc.apps.flutter", "FLUTTER"),
        text_version("bin/cache/flutter.version.json", r'"frameworkVersion"\s*:\s*"([^"]+)"'),
    ),
    Tool("FreeCAD", P, "apps: FreeCAD", call("ai_pc.apps.freecad", "cmd")),
    Tool("GIMP", P, "apps: GIMP", call("ai_pc.apps.gimp", "console")),
    Tool("Go", P, "apps: GoLand", attr("ai_pc.apps.goland", "GO"), run_version("version", pattern=r"go\d+\.\d+[\w.]*")),
    Tool("Godot", P, "apps: Godot", attr("ai_pc.apps.godot", "GODOT")),
    Tool("HandBrake CLI", P, "apps: HandBrake", attr("ai_pc.apps.handbrake", "EXE")),
    Tool("JianYing 5.9", P, "video", attr("ai_pc.video.jy_export", "JIANYING")),
    Tool("KeePassXC CLI", P, "apps: KeePassXC", attr("ai_pc.apps.keepassxc", "CLI")),
    Tool("KiCad", P, "apps: KiCad", attr("ai_pc.apps.kicad", "CLI")),
    Tool("Krita", P, "apps: Krita", call("ai_pc.apps.krita", "exe")),
    Tool("LibreOffice", P, "apps: LibreOffice", call("ai_pc.apps.libreoffice", "soffice"), sibling_version("soffice.exe")),
    Tool("llama.cpp server", P, "desktop agent: Vocaela click model", vocaela_file(None), run_version("--version", pattern=r"version: (\d+[^\n]*)")),
    Tool("LMMS", P, "apps: LMMS", attr("ai_pc.apps.lmms", "EXE")),
    Tool("GNU Octave", P, "apps: MATLAB / Octave", call("ai_pc.apps.matlab", "octave")),
    Tool("MongoDB", P, "apps: MongoDB", attr("ai_pc.apps.mongodb", "MONGOD"), run_version("--version")),
    Tool("MuseScore", P, "apps: MuseScore", attr("ai_pc.apps.musescore", "EXE")),
    Tool("MySQL", P, "apps: MySQL", call("ai_pc.apps.mysql", "bin_dir", "mysqld.exe")),
    Tool("OpenSCAD", P, "apps: OpenSCAD", call("ai_pc.apps.openscad", "openscad_exe"), sibling_version("openscad.exe")),
    Tool("PHP", P, "apps: PHP", attr("ai_pc.apps.php", "PHP")),
    Tool("PostgreSQL", P, "apps: PostgreSQL", call("ai_pc.apps.postgres", "bin_dir", "pg_ctl.exe")),
    Tool("PrusaSlicer", P, "apps: PrusaSlicer", attr("ai_pc.apps.prusaslicer", "EXE")),
    Tool("Python 3.11 (projects)", P, "apps: PyCharm", attr("ai_pc.apps.pycharm", "PYTHON")),
    Tool("QGIS", P, "apps: QGIS", attr("ai_pc.apps.qgis", "QROOT", "bin", "qgis_process-qgis.bat"), folder_version()),
    Tool("RawTherapee CLI", P, "apps: RawTherapee, Lightroom", attr("ai_pc.apps.rawtherapee", "CLI")),
    Tool("R", P, "apps: R statistics", call("ai_pc.apps.rstats", "rscript"), folder_version()),
    Tool(
        "Rust (cargo)",
        P,
        "apps: RustRover",
        attr("ai_pc.apps.rustrover", "CARGO"),
        run_version("--version", env=lambda: importlib.import_module("ai_pc.apps.rustrover").env()),
    ),
    Tool("Shotcut (melt)", P, "apps: Shotcut", call("ai_pc.apps.shotcut", "melt"), sibling_version("shotcut.exe")),
    Tool("Tectonic (LaTeX)", P, "apps: LaTeX", attr("ai_pc.apps.latex", "EXE"), run_version("--version")),
    Tool("Lottie player", P, "apps: After Effects", attr("ai_pc.apps.aftereffects", "LOTTIE_JS"), text_version("lottie.min.js", r"(\d+\.\d+\.\d+)")),
    Tool("Power BI schemas", P, "apps: Power BI", attr("ai_pc.apps.powerbi", "CACHE"), lambda p: f"{sum(1 for _ in p.rglob('*.json'))} schema files"),
    Tool(
        "cloudflared",
        P,
        "social media: sharing local files by link",
        attr("ai_pc.social.mediahost", "CLOUDFLARED"),
        run_version("--version"),
        optional=True,
    ),
    # installed on Windows the usual way
    Tool("Microsoft Word", W, "office", office("WINWORD.EXE")),
    Tool("Microsoft Excel", W, "office", office("EXCEL.EXE")),
    Tool("Microsoft PowerPoint", W, "office", office("POWERPNT.EXE")),
    Tool("Access database engine (DAO)", W, "apps: databases (.accdb)", com_class("DAO.DBEngine.120")),
    Tool(
        "CapCut",
        W,
        "video (CapCut drafts)",
        lambda: Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut" / "Apps" / "CapCut.exe",
        newest_version_folder,
    ),
    Tool("Chrome or Edge", W, "design, documents, web pages (headless)", call("ai_pc.core.headless", "browser")),
    Tool("FFmpeg", W, "video, sound, converter", which("ffmpeg"), run_version("-version", pattern=r"ffmpeg version (\S+)")),
    Tool("FFprobe", W, "video, sound, converter", which("ffprobe"), run_version("-version", pattern=r"ffprobe version (\S+)")),
    Tool("Git", W, "coding (versions of each project)", which("git"), run_version("--version")),
    Tool("Node.js", W, "coding, apps: Node.js, After Effects", call("ai_pc.apps.nodejs", "node_exe")),
    Tool(
        "Visual Studio Code",
        W,
        "apps: VS Code",
        attr("ai_pc.apps.vscode", "CODE"),
        lambda p: file_version(p.parents[1] / "Code.exe") if (p.parents[1] / "Code.exe").exists() else "",
    ),
    Tool("Windows Package Manager (winget)", W, "apps: PC care", which("winget"), run_version("--version")),
    Tool(
        "Windows PowerShell",
        W,
        "apps: OCR, PC care",
        which("powershell"),
        registry_version(r"SOFTWARE\Microsoft\PowerShell\3\PowerShellEngine", "PowerShellVersion"),
    ),
    Tool("Unity", W, "apps: Unity (building the game)", call("ai_pc.apps.unity", "editor"), optional=True),
    Tool("Docker", W, "apps: Docker (building the image)", which("docker"), run_version("--version"), optional=True),
    # local models
    Tool("Whisper base", M, "speech, voice notes, captions", attr("ai_pc.media.speech", "MODEL_DIR", "model.bin"), size),
    Tool("YuNet face detector", M, "photos, video framing", attr("ai_pc.media.frames", "YUNET"), size),
    Tool("Vocaela click model", M, "desktop agent (vision)", vocaela_file("-m"), size),
    Tool("Vocaela image projector", M, "desktop agent (vision)", vocaela_file("--mmproj"), size),
    Tool("Vocaela prompt", M, "desktop agent (vision)", attr("ai_pc.desktop.vocaela", "SYSTEM_FILE"), size),
    Tool("TinyClick", M, "desktop agent (vision, alternative)", under(MODELS, "tinyclick"), size, optional=True),
    Tool(
        "TinyClick download",
        M,
        "the source services/tinyclick/convert.py reads",
        under(MODELS / "hf" / "hub", "models--*TinyClick*"),
        size,
        optional=True,
    ),
    # environments and developer tools
    Tool("Python environment (.venv)", E, "everything", venv_python(".venv"), run_version("--version")),
    Tool(
        "TinyClick environment (.venv-xpu)", E, "desktop agent (TinyClick server)", venv_python(".venv-xpu"), run_version("--version"), optional=True
    ),
    Tool("uv", E, "installing and locking packages", which("uv"), run_version("--version")),
    Tool(
        "GitHub CLI",
        E,
        "GitHub (repository, CI)",
        lambda: TOOLS / "gh" / "bin" / "gh.exe",
        run_version("--version", env=lambda: dict(os.environ, GH_CONFIG_DIR=str(TOOLS / "gh" / "config"))),
        optional=True,
    ),
    Tool(
        "gitleaks", E, "secret scanning", lambda: TOOLS / "gitleaks" / "gitleaks.exe", run_version("version", pattern=r"\d+\.\d+\.\d+"), optional=True
    ),
    # the Python packages each environment needs, at the versions asked for
    Tool("Dependencies (.venv)", PK, "everything", venv_python(".venv"), packages=requirements("dependencies")),
    Tool("Dev dependencies (.venv)", PK, "tests, lint, type checks, pre-commit", venv_python(".venv"), packages=requirements("dev"), optional=True),
    Tool(
        "TinyClick dependencies (.venv-xpu)",
        PK,
        "desktop agent (TinyClick server)",
        venv_python(".venv-xpu"),
        packages=requirements("services/tinyclick/requirements.txt"),
        optional=True,
    ),
]
# tools/ folders that hold helpers rather than programs the code runs
HELPERS = {
    "flutter_home": "Flutter's settings and caches",
    "gnupg": "keys for checking download signatures",
    "hf-cache": "download cache for Hugging Face models",
    "innoextract": "unpacks Inno Setup installers without running them",
    "review": "wheels downloaded and checked before installing",
    "uv-cache": "uv's package cache",
}


def check(tools: list[Tool] | None = None) -> list[Result]:
    results: list[Result] = []
    for t in TOOL_LIST if tools is None else tools:
        try:
            found = t.find()
            path = Path(str(found)) if found else None
        except Exception:  # noqa: BLE001 - a module that cannot find its program says so by raising
            path = None
        version = ""
        problems: list[str] = []
        if path is not None and path.exists():
            if t.packages is not None:
                try:
                    count, problems = package_problems(path, t.packages())
                    version = f"{count - len(problems)} of {count}"
                except Exception as e:  # noqa: BLE001 - reported as the problem
                    problems = [f"could not list the packages: {e}"]
            else:
                try:
                    version = t.version(path)
                except Exception:  # noqa: BLE001 - a missing version is not a missing program
                    version = ""
                if t.group != M:
                    version = tidy(version) or source_version(path)
        source = False
        if path is not None and TOOLS in path.parents:
            source = (TOOLS / path.relative_to(TOOLS).parts[0] / "SOURCE.txt").is_file()
        results.append(Result(t, path, version, source, problems))
    return results


def unused_tool_folders(results: list[Result], tools: Path | None = None) -> list[str]:
    """Folders in tools/ that no result points into, and are not helpers."""
    tools = tools or TOOLS
    if not tools.exists():
        return []
    used = {r.path.relative_to(tools).parts[0] for r in results if r.path is not None and tools in r.path.parents}
    return sorted(d.name for d in tools.iterdir() if d.is_dir() and d.name not in used and d.name not in HELPERS)


def language_model() -> dict[str, Any]:
    """The provider and model the requests that need a model will use, and whether its key is here (never the key)."""
    from ai_pc.llm import providers

    try:
        return providers.describe()
    except ValueError as e:  # an unknown provider named in the environment or the settings
        return {"name": "(not set up)", "problem": str(e), "key_status": "missing"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ai-pc doctor", description="check that every program, model and environment AI PC uses is present")
    ap.add_argument("--json", action="store_true", help="print the results as JSON, with paths")
    a = ap.parse_args(argv)
    results = check()
    spare = unused_tool_folders(results)
    required = [r for r in results if not r.tool.optional]
    extras = [r for r in results if r.tool.optional]
    lm = language_model()
    if a.json:
        rows = [
            {
                "name": r.tool.name,
                "group": r.tool.group,
                "ok": r.ok,
                "optional": r.tool.optional,
                "version": r.version,
                "used_by": r.tool.used_by,
                "path": str(r.path) if r.path else None,
                "source_recorded": r.source,
                "problems": r.problems,
            }
            for r in results
        ]
        print(json.dumps({"results": rows, "unused_tool_folders": spare, "language_model": lm}, indent=1))
    else:
        width = max(len(r.tool.name) for r in results)
        for group in GROUPS:
            print(f"\n{group}")
            for r in (x for x in results if x.tool.group == group):
                state = "ok" if r.ok else ("not here" if r.tool.optional else "MISSING")
                note = " (optional)" if r.tool.optional else ""
                print(f"  {state:<9} {r.tool.name:<{width}}  {r.version[:22]:<22}  {r.tool.used_by}{note}")
                for problem in r.problems:
                    print(f"  {'':<9} {'':<{width}}  {problem}")
        if spare:
            print(f"\nFolders in tools/ that no code uses: {', '.join(spare)}")
        if lm.get("problem"):
            print(f"\nLanguage model: {lm['name']}: {lm['problem']}")
        else:
            print(f"\nLanguage model: {lm['name']}, {lm['models']['fast']}, key {lm['key_status']} (change it with 'ai-pc models use ...')")
        print(f"\n{sum(r.ok for r in required)} of {len(required)} required present; {sum(r.ok for r in extras)} of {len(extras)} optional present.")
    return 0 if all(r.ok for r in required) else 1


if __name__ == "__main__":
    sys.exit(main())
