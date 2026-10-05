# Configuration

## API keys

Keys are looked up in this order ([src/ai_pc/core/keys.py](../src/ai_pc/core/keys.py)):

1. the environment, e.g. `NEBIUS_API_KEY`
2. a `.env` file in the project folder (git-ignored; start from [.env.example](../.env.example))
3. this PC's encrypted vault: `ai-pc keys set NEBIUS_API_KEY` (Windows DPAPI: only this Windows user on this PC can
   read it; `ai-pc keys list` shows the names, never the keys)
4. a legacy `my_nebius.txt` in the project folder (git-ignored; prefer 2 or 3)

Keys are never printed, logged, saved in chats or sent to a model. Keys for work apps, social media and accounting
programs are added with each program's `connect` command (`ai-pc hub connect slack`, `ai-pc social connect facebook`,
`ai-pc accounts connect quickbooks`) and kept in the same vault.

## Where data lives

Everything stays inside the project folder ([src/ai_pc/core/paths.py](../src/ai_pc/core/paths.py)); none of it is in
the repository. Set `AI_PC_HOME` to keep it in another folder.

| Folder | What is in it |
|---|---|
| `tools/` | portable programs the agents drive ([tools](tools.md)) and reviewed downloads (`tools/review/`) |
| `models/` | local models: Whisper (speech), YuNet (faces), the click models, Hugging Face cache |
| `media/` | sample and test media |
| `out/` | everything the programs make, each in its own folder (`out/video`, `out/docs`, `out/aipc/chats` ...) |
| `state/` | learned skills, caches, the encrypted key vault (`state/hub/vault.bin`) and its audit log |
| `kb/` | the video knowledge base, built on this PC from the installed editors' catalogues |
| `runs/` | the desktop agent's run logs and screenshots |

## Settings files

| File | Settings |
|---|---|
| `out/aipc/bar.json` | the command bar: `hotkey` (default `ctrl+alt+space`), fallbacks, `theme` (`auto`, `light`, `dark`), `notify`, `resume_hours` |
| [src/ai_pc/core/config.py](../src/ai_pc/core/config.py) | the model for each role, prices, limits, the programs the desktop agent never controls |

## Models

Every role (fast replies, vision, planning, documents) uses `zai-org/GLM-5.3-Flash` on Nebius, the cheapest model on
the account that also reads images, with `reasoning_effort: low`. The choice and its measurements are in
`config.py`; `scripts/bench_models.py` re-runs the benchmark.

## Environment variables

| Variable | Effect |
|---|---|
| `NEBIUS_API_KEY` | the model provider's key |
| `AI_PC_HOME` | the folder that holds tools, models, media, outputs and state |
| `AI_PC_BAR_HOME` | another folder for the command bar's settings and log (used by tests) |
| `CUA_GROUNDER` | the desktop agent's click model: `vocaela` (default) or `tinyclick` |
