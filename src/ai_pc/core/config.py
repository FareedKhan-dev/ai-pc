"""Central configuration: the models for each role, prices, limits and the programs the agent never controls.
Model choices come from the benchmark in scripts/bench_models.py (Nebius account). Where things live is in paths.py."""

import os

from ai_pc.core.paths import ROOT, RUNS, STATE  # noqa: F401 - RUNS is re-exported for the agent and planners

SKILLS_DIR = STATE / "skills"

# role -> model + the provider switch that turns hidden "thinking" off (measured: see scripts/bench_models.py results)
# hedge_s: if a call has not answered after this many seconds, an identical backup request is sent and the first
# answer wins (provider latency has long tails: DeepSeek-V4.1-Flash went from 2-3.5 s to a 39.8 s median on 2026-10-01)
# Every tier runs on GLM-5.3-Flash, the cheapest model on the account that also reads images (0.15 / 0.50 USD per
# million tokens; the user's choice on 2026-10-02). Earlier picks, faster but 3-20x dearer: fast + annotate =
# Qwen/Qwen3.8-27B (thinking off), deep = moonshotai/Kimi-K3. GLM needs reasoning_effort "low": "none" or thinking off
# made it ramble to the token limit (brief: 20-68 s instead of 6-10 s; tested 2026-10-02).
MODELS = {
    # the brief runs alongside media analysis (~20 s), so GLM's 6-10 s costs no wall time; the backup request waits
    # long enough that it only fires on a real stall (a backup is billed too)
    "fast": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 2500, "hedge_s": 15.0, "deadline_s": 90},
    # scripts/bench_models.py visionlat (2026-10-01, real CapCut screens): GLM-5.3-Flash 6/6 right, 1.6-2.7 s; DeepSeek 6/6, 3.9-64 s
    "vision": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 900, "hedge_s": 4.5, "deadline_s": 60},
    "deep": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 9000, "deadline_s": 300},
    # long structured outputs (a whole edit plan in one call); no hedging: a backup would double a long generation
    "video": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 9000, "deadline_s": 300},
    # batch descriptions for the knowledge base (kb.py): Chinese-reading, long JSON output
    # (Qwen3.8-27B did 30 items in 4.1 s vs GLM-5.3-Flash 11.7 s, with equal or better descriptions; tested 2026-10-02)
    "annotate": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 8000, "deadline_s": 300},
    # media analysis (analyze.py) and edit checks (verify.py): one contact sheet / before-after image per call
    "caption": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 3000, "hedge_s": 9.0, "deadline_s": 90},
    # documents (src/ai_pc/office): an outline, then each section written in parallel (a few thousand tokens each)
    "docs": {"model": "zai-org/GLM-5.3-Flash", "extra": {"reasoning_effort": "low"}, "max_tokens": 7000, "hedge_s": 40.0, "deadline_s": 180},
}

# USD per million tokens (input, output) on Nebius Token Factory, for the cost line of each run (from the account's
# /v1/models?verbose=true pricing, 2026-10-02; update when Nebius changes them)
PRICES = {
    "zai-org/GLM-5.3-Flash": (0.15, 0.50),
    "Qwen/Qwen3.8-27B": (0.45, 3.00),
    "moonshotai/Kimi-K3": (3.00, 15.00),
    "deepseek-ai/DeepSeek-V4.1-Flash": (0.30, 1.20),
}

GROUNDER_URL = "http://127.0.0.1:8765"  # TinyClick server (services/tinyclick/server.py) running on the Arc GPU
GROUNDER_CMD = [str(ROOT / ".venv-xpu" / "Scripts" / "python.exe"), "-u", str(ROOT / "services" / "tinyclick" / "server.py")]

# click model used by the vision lane: "vocaela" (29/30 on CapCut targets, non-commercial weights) or "tinyclick" (18/30, MIT)
GROUNDER = os.environ.get("CUA_GROUNDER", "vocaela")
_VOC = ROOT / "models" / "vocaela"
VOCAELA_URL = "http://127.0.0.1:8091"  # llama-server (llama.cpp, Vulkan) on the Arc GPU
VOCAELA_CMD = [
    str(ROOT / "tools" / "llama.cpp" / "llama-server.exe"),
    "-m",
    str(_VOC / "Vocaela-2-500M-1024R2-Q8_0.gguf"),
    "--mmproj",
    str(_VOC / "mmproj-Vocaela-2-500M-1024R2-Q8_0.gguf"),
    "--host",
    "127.0.0.1",
    "--port",
    "8091",
    "-c",
    "8192",
    "-np",
    "2",
    "-ngl",
    "99",
    "-t",
    "8",
    "--no-ui",
]
# slot 0 keeps the whole screenshot cached (prefetched while the planner thinks); slot 1 serves zoomed crops

LIMITS = {"max_steps": 30, "max_seconds": 180, "max_llm_calls": 14, "max_elements": 300, "stuck_after": 2}

# processes the agent will never control unless explicitly allowed (terminals and code editors run code; password
# managers and system tools hold what must never be typed into or changed)
BLOCKED_PROCS = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "wt.exe",
    "conhost.exe",
    "code.exe",
    "1password.exe",
    "bitwarden.exe",
    "keepass.exe",
    "keepassxc.exe",
    "regedit.exe",
    "mmc.exe",
}
