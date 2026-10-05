"""ai-pc doctor: finding programs, reading their versions, checking packages, and the report."""

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from ai_pc.cli import doctor


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("PrusaSlicer-2.9.6", "2.9.6"),
        ("3,7,9,0", "3.7.9.0"),
        ("2.55.0.windows.5", "2.55.0"),
        ("go1.27.1", "1.27.1"),
        ("0.0.0.0", ""),
        ("10 schema files", "10 schema files"),
        ("", ""),
    ],
)
def test_tidy_keeps_the_dotted_version(raw, clean):
    assert doctor.tidy(raw) == clean


@pytest.mark.parametrize(
    ("first_line", "version"),
    [
        ("https://github.com/LMMS/lmms/releases/download/v1.3.0/lmms-1.3.0-win64.exe", "1.3.0"),
        ("https://downloads.arduino.cc/arduino-cli/arduino-cli_1.5.1_Windows_64bit.zip", "1.5.1"),
        ("", ""),
    ],
)
def test_version_from_the_recorded_download(tmp_path, first_line, version):
    tools = tmp_path / "tools"
    (tools / "app" / "bin").mkdir(parents=True)
    (tools / "app" / "SOURCE.txt").write_text(first_line + "\nsha256 checked\n" if first_line else "", encoding="utf-8")
    assert doctor.source_version(tools / "app" / "bin" / "app.exe", tools) == version
    assert doctor.source_version(tmp_path / "elsewhere" / "app.exe", tools) == ""


def test_versions_from_folder_names_and_text_files(tmp_path):
    assert doctor.folder_version()(tmp_path / "gradle-9.8.0" / "bin" / "gradle.bat") == "9.8.0"
    tools = tmp_path / "android" / "platform-tools"
    tools.mkdir(parents=True)
    (tools / "source.properties").write_text("Pkg.Revision=37.0.1\n", encoding="utf-8")
    assert doctor.text_version("source.properties", r"Pkg\.Revision=([\d.]+)")(tools / "adb.exe") == "37.0.1"


def test_capcut_version_is_its_newest_version_folder(tmp_path):
    for name in ("9.5.0.4050", "10.1.0.12", "logs"):
        (tmp_path / name).mkdir()
    assert doctor.newest_version_folder(tmp_path / "CapCut.exe") == "10.1.0.12"


def test_model_size(tmp_path):
    (tmp_path / "model.bin").write_bytes(bytes(3 * 2**20))
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "modeling.py").write_bytes(bytes(2048))
    assert doctor.size(tmp_path / "model.bin") == "3 MB"
    assert doctor.size(tmp_path / "code") == "2 KB"


def test_package_problems_names_missing_and_out_of_range_packages():
    wanted = ["pytest>=1", "pytest>=9999", "no-such-package-for-ai-pc>=1", "pywin32>=1; sys_platform == 'linux'"]
    count, problems = doctor.package_problems(Path(sys.executable), wanted)
    assert count == 3  # the linux-only line does not apply here
    assert problems[0].startswith("pytest>=9999: ") and problems[0].endswith(" is installed")
    assert problems[1] == "no-such-package-for-ai-pc>=1 is not installed"


def test_an_environment_missing_a_package_is_not_ok():
    t = doctor.Tool("Deps", doctor.PK, "everything", lambda: Path(sys.executable), packages=lambda: ["pytest>=1", "no-such-package-for-ai-pc"])
    [r] = doctor.check([t])
    assert not r.ok
    assert r.version == "1 of 2"
    assert r.problems == ["no-such-package-for-ai-pc is not installed"]


@pytest.fixture
def fake_pc(tmp_path, monkeypatch):
    """A tools/ folder with one program and one leftover folder, and a list of four things to look for."""
    tools = tmp_path / "tools"
    program = tools / "thing" / "thing.exe"
    program.parent.mkdir(parents=True)
    program.write_bytes(b"")  # no version inside, so the version comes from SOURCE.txt
    (tools / "thing" / "SOURCE.txt").write_text("https://example.org/thing-2.4.1.zip\n", encoding="utf-8")
    (tools / "leftover").mkdir()

    def broken() -> object:
        raise RuntimeError("not set up")

    monkeypatch.setattr(doctor, "TOOLS", tools)
    monkeypatch.setattr(
        doctor,
        "TOOL_LIST",
        [
            doctor.Tool("Thing", doctor.P, "apps: thing", lambda: program),
            doctor.Tool("Gone", doctor.W, "apps: gone", lambda: None),
            doctor.Tool("Extra", doctor.W, "apps: extra", lambda: tmp_path / "nowhere.exe", optional=True),
            doctor.Tool("Broken", doctor.W, "apps: broken", broken, optional=True),
        ],
    )
    return tools


def test_report_lists_each_thing_and_fails_when_a_required_one_is_missing(fake_pc, capsys):
    assert doctor.main([]) == 1
    out = capsys.readouterr().out
    assert "  ok        Thing " in out and " 2.4.1 " in out
    assert "  MISSING   Gone " in out
    assert "  not here  Extra " in out and "apps: extra (optional)" in out
    assert "  not here  Broken " in out
    assert "Folders in tools/ that no code uses: leftover" in out
    assert "1 of 2 required present; 0 of 2 optional present." in out


def test_json_report(fake_pc, capsys):
    doctor.main(["--json"])
    data = json.loads(capsys.readouterr().out)
    rows = {r["name"]: r for r in data["results"]}
    assert rows["Thing"]["ok"] and rows["Thing"]["version"] == "2.4.1" and rows["Thing"]["source_recorded"]
    assert rows["Gone"] == {**rows["Gone"], "ok": False, "path": None, "optional": False}
    assert data["unused_tool_folders"] == ["leftover"]


def test_missing_optional_things_do_not_fail_the_check(fake_pc, monkeypatch):
    monkeypatch.setattr(doctor, "TOOL_LIST", [t for t in doctor.TOOL_LIST if t.name != "Gone"])
    assert doctor.main([]) == 0


def test_the_list_has_unique_names_and_known_groups():
    names = [t.name for t in doctor.TOOL_LIST]
    assert len(names) == len(set(names))
    assert {t.group for t in doctor.TOOL_LIST} <= set(doctor.GROUPS)


def test_every_module_constant_and_function_it_names_exists():
    """A renamed constant would make the doctor report a program as missing."""
    for t in doctor.TOOL_LIST:
        names = inspect.getclosurevars(t.find).nonlocals
        if "module" in names:
            module = importlib.import_module(names["module"])
            assert hasattr(module, names.get("name") or names["function"]), t.name
