"""API keys for the model provider and other services, never printed, logged or sent to a model.

A key is looked up in this order:
  1. the environment                       NEBIUS_API_KEY=...
  2. a .env file in the project folder     NEBIUS_API_KEY=...   (git-ignored; see .env.example)
  3. this PC's encrypted vault             ai-pc keys set NEBIUS_API_KEY   (Windows DPAPI, this Windows user only)
  4. a legacy key file in the project      my_nebius.txt        (git-ignored; prefer 2 or 3)
"""

import os
from pathlib import Path

from ai_pc.core.paths import ROOT

VAULT_ENTRY = "keys"  # the vault entry that holds API keys by their environment name


def dotenv(path: Path | None = None) -> dict[str, str]:
    """KEY=value pairs from a .env file (comments, blank lines and 'export ' allowed; quotes stripped)."""
    path = path or ROOT / ".env"
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def from_vault(env_name: str) -> str:
    try:
        from ai_pc.core import vault

        return ((vault.get(VAULT_ENTRY) or {}).get(env_name) or "").strip()
    except Exception:  # noqa: BLE001 - no vault on this PC (or not readable by this user): look elsewhere
        return ""


def get_key(env_name: str = "NEBIUS_API_KEY", filename: str | None = "my_nebius.txt") -> str:
    k = os.environ.get(env_name, "").strip() or dotenv().get(env_name, "").strip() or from_vault(env_name)
    if not k and filename:
        path = ROOT / filename
        if path.is_file():
            k = path.read_text(encoding="utf-8").strip()
    if not k:
        raise RuntimeError(f"no API key: set {env_name} in the environment or in .env, or run 'ai-pc keys set {env_name}'")
    return k
