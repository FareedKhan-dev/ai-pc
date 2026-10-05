"""The ai-pc command line: help, version, aliases and mistakes."""
import sys
import types

import pytest

from ai_pc import __version__
from ai_pc.cli import main as cli


def test_help_lists_every_command(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for name in cli.COMMANDS:
        assert f"  {name} " in out


def test_version(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_options_without_a_command_go_to_the_chat(monkeypatch):
    seen = {}
    fake = types.ModuleType("fake_chat")
    fake.run = lambda argv: seen.update(argv=argv) or 0
    monkeypatch.setitem(sys.modules, "fake_chat", fake)
    monkeypatch.setitem(cli.COMMANDS, "chat", ("fake_chat", "run", "the chat"))
    assert cli.main(["-m", "hello", "--offline"]) == 0
    assert seen["argv"] == ["-m", "hello", "--offline"]


def test_an_unknown_command_suggests_the_nearest(capsys):
    assert cli.main(["vdeo"]) == 2
    err = capsys.readouterr().err
    assert "unknown command 'vdeo'" in err and "'video'" in err


@pytest.mark.parametrize("alias", sorted(cli.ALIASES))
def test_aliases_point_at_real_commands(alias):
    assert cli.ALIASES[alias] in cli.COMMANDS


def test_every_command_has_a_function_to_run():
    import importlib
    for module, function, doc in cli.COMMANDS.values():
        assert callable(getattr(importlib.import_module(module), function)), module
        assert doc
