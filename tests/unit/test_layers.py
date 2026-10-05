"""The package's layers only depend downwards (see docs/architecture.md):

  cli  ->  assistant  ->  programs (video, office, photo, ... apps, desktop)  ->  llm, media  ->  core
"""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "ai_pc"
PROGRAMS = {"accounts", "apps", "cad", "coding", "convert", "design", "desktop", "hub", "office", "photo", "social", "sound", "three", "video",
            "windows"}
# what each layer may import from the package (besides itself)
ALLOWED = {"core": set(), "llm": {"core"}, "media": {"core"}}
ALLOWED.update({p: {"core", "llm", "media"} | PROGRAMS for p in PROGRAMS})
ALLOWED["assistant"] = {"core", "llm", "media"} | PROGRAMS


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("ai_pc."):
            yield n.module.split(".")[1], n.lineno
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("ai_pc."):
                    yield a.name.split(".")[1], n.lineno


@pytest.mark.parametrize("layer", sorted(ALLOWED))
def test_a_layer_imports_only_what_is_below_it(layer):
    bad = []
    for f in (SRC / layer).rglob("*.py"):
        for target, line in imports_of(f):
            if target != layer and target not in ALLOWED[layer]:
                bad.append(f"{f.relative_to(SRC)}:{line} imports ai_pc.{target}")
    assert not bad, "\n".join(bad)


def test_relative_imports_are_not_used():
    rel = [f"{f.relative_to(SRC)}:{n.lineno}" for f in SRC.rglob("*.py") if "bl" not in f.parts
           for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))) if isinstance(n, ast.ImportFrom) and n.level]
    assert not rel, rel
