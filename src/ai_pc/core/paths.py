"""Where AI PC keeps things on this PC.

Everything lives inside the project folder (the checkout): the portable programs it drives (tools/), local models,
test media, outputs, learned state and the video knowledge base. None of it is in the repository (see .gitignore).
Set AI_PC_HOME to use another folder.

  ROOT     the project folder                  TOOLS    portable programs (verified downloads)
  MODELS   local models (Whisper, YuNet ...)   MEDIA    sample and test media
  OUT      everything the programs make        STATE    learned state, caches and the encrypted key vault
  RUNS     desktop-agent run logs              KB       the video knowledge base (built on this PC)
"""
import os
from pathlib import Path


def _find_root():
    env = os.environ.get("AI_PC_HOME")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "ai_pc").is_dir():
            return parent
    return Path.cwd()


ROOT = _find_root()
TOOLS = ROOT / "tools"
MODELS = ROOT / "models"
MEDIA = ROOT / "media"
OUT = ROOT / "out"
STATE = ROOT / "state"
RUNS = ROOT / "runs"
KB = ROOT / "kb"
