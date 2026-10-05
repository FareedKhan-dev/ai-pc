"""Every module of the package imports (a smoke test for missing dependencies and broken imports)."""

import importlib
import pkgutil

import pytest

import ai_pc

SKIP = {"ai_pc.__main__"}  # runs the command line when imported
MODULES = sorted(m.name for m in pkgutil.walk_packages(ai_pc.__path__, "ai_pc.") if m.name not in SKIP and ".three.bl" not in m.name)


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
