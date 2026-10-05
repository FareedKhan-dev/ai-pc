"""Integration suites: each test_*.py in this folder is a script that drives real programs (on a hidden desktop, never on
the screen) or works on real files and media from this PC. It prints an 'ok' / 'FAIL' line per check and exits
non-zero when any check fails.

pytest runs each suite as one test, in its own process, from the project folder:

  pytest -m integration                          every integration suite (slow; needs tools/, models/ and media/)
  pytest -m integration -k "aipc or bar"         some of them
  python tests/integration/test_photo.py         one suite on its own, with its full output

Suites marked 'live' need API keys, online accounts or a visible desktop program; they run only with -m live.
"""

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# need API keys, real online accounts, or drive a program on the visible desktop
LIVE = {"test_agent_llm", "test_agent_offline", "test_capcut_live", "test_charmap", "test_foundation", "test_settings"}
# minutes a suite may take before it counts as hung
TIMEOUT = {"test_popular": 60, "test_apps": 30, "test_three": 30, "test_video_offline": 30, "test_templates": 30, "test_docs": 30}


class SuiteFailed(Exception):
    pass


def pytest_pycollect_makemodule(module_path, parent):
    if module_path.parent == HERE and module_path.name.startswith("test_"):
        return SuiteFile.from_parent(parent, path=module_path)
    return None


class SuiteFile(pytest.File):
    def collect(self):
        yield SuiteItem.from_parent(self, name=self.path.stem)


class SuiteItem(pytest.Item):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.add_marker(pytest.mark.integration)
        if self.name in LIVE:
            self.add_marker(pytest.mark.live)

    def runtest(self):
        try:
            p = subprocess.run(
                [sys.executable, str(self.path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT.get(self.name, 15) * 60,
            )
        except subprocess.TimeoutExpired as e:
            raise SuiteFailed(f"no result after {e.timeout:.0f} s") from None
        output = (p.stdout or "") + (p.stderr or "")
        if p.returncode != 0:
            fails = [line for line in output.splitlines() if line.startswith(("FAIL", "     why:"))]
            tail = output.strip().splitlines()[-20:]
            raise SuiteFailed("\n".join(fails[:40] or tail))

    def repr_failure(self, excinfo, style=None):
        if isinstance(excinfo.value, SuiteFailed):
            return f"{self.name} failed:\n{excinfo.value}"
        return super().repr_failure(excinfo, style=style)

    def reportinfo(self):
        return self.path, None, f"suite {self.name}"
