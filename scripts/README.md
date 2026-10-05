# Scripts

Maintenance and measurement scripts. They are not part of the `ai-pc` command. Run them from the project folder with
`uv run python scripts/<name>.py`.

| Script | What it does |
|---|---|
| `bench_models.py` | Benchmarks the Nebius models for each planner role (speed and accuracy) |
| `list_models.py` | Lists the models available on the Nebius account |
| `bench_grounding.py` | Compares the two click models (Vocaela and TinyClick) on saved CapCut screenshots |
| `fetch_stock_media.py` | Downloads free stock clips (Mixkit licence) into `media/stock/<genre>/` for the video tests |
| `stress_video_batch.py` | Runs ten one-minute edits in ten genres back to back |
| `safe_wheels.py` | Downloads exact wheels from PyPI, checks their hashes and lists what is inside, for offline installs |
| `third_party_notices.py` | Regenerates `THIRD_PARTY_NOTICES.md` from `uv.lock` |
| `readme_assets.py` | Rebuilds the README's hero picture (light and dark) and the logo tiles from `docs/assets/logos/` |
