"""Paths and API keys."""

import pytest

from ai_pc.core import keys, paths


def test_the_project_folder_is_found_from_the_package(monkeypatch):
    monkeypatch.delenv("AI_PC_HOME", raising=False)
    root = paths._find_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "ai_pc").is_dir()
    assert paths.TOOLS == paths.ROOT / "tools"


def test_ai_pc_home_moves_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_PC_HOME", str(tmp_path))
    assert paths._find_root() == tmp_path.resolve()


def test_dotenv_reads_keys_comments_quotes_and_export(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nNEBIUS_API_KEY=\"abc\"\nexport OTHER='x y'\nBROKEN LINE\nEMPTY=\n", encoding="utf-8")
    assert keys.dotenv(env) == {"NEBIUS_API_KEY": "abc", "OTHER": "x y", "EMPTY": ""}


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Keys looked up in a made-up project folder, with no vault."""
    monkeypatch.setattr(keys, "ROOT", tmp_path)
    monkeypatch.setattr(keys, "from_vault", lambda name: "")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    return tmp_path


def test_the_environment_wins(isolated, monkeypatch):
    (isolated / ".env").write_text("NEBIUS_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("NEBIUS_API_KEY", "from-env")
    assert keys.get_key() == "from-env"


def test_then_dotenv_then_the_vault_then_the_old_key_file(isolated, monkeypatch):
    (isolated / "my_nebius.txt").write_text("from-file\n", encoding="utf-8")
    assert keys.get_key() == "from-file"
    monkeypatch.setattr(keys, "from_vault", lambda name: "from-vault")
    assert keys.get_key() == "from-vault"
    (isolated / ".env").write_text("NEBIUS_API_KEY=from-dotenv\n", encoding="utf-8")
    assert keys.get_key() == "from-dotenv"


def test_no_key_says_how_to_add_one(isolated):
    with pytest.raises(RuntimeError, match="ai-pc keys set NEBIUS_API_KEY"):
        keys.get_key()
