# Changelog

All notable changes to this project are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org).

## [Unreleased]

### Added

- `ai-pc doctor`: checks that every program, model, environment and Python package AI PC uses is on this PC, shows
  their versions, and names folders in `tools/` that no code uses. `--json` gives the same with paths.
- Language models from any OpenAI-compatible provider: 25 presets (Nebius, OpenAI, Google Gemini, Mistral, Groq,
  Together, Fireworks, DeepInfra, OpenRouter, Hugging Face, DeepSeek, Alibaba Qwen, Z.ai, Moonshot, xAI, Cerebras,
  SambaNova, NVIDIA NIM, Novita, Cohere, SiliconFlow, and Ollama, LM Studio, llama.cpp and vLLM on the PC) plus any
  other address. `ai-pc models` lists, chooses (`use`), shows, tests and resets them; a model per role, keys from the
  usual places, and a price for the cost line. Nebius with GLM-5.3-Flash stays the default
  ([decision record 0005](docs/adr/0005-any-openai-compatible-provider.md)).
- The model client leaves out optional fields a provider does not take (streaming usage counts, JSON mode,
  temperature), sends `max_completion_tokens` where a provider wants it, and needs no key for local servers.
- `ai-pc doctor` shows the language model in use and whether its key is set.
- The command bar shows the first page of a document, deck or drawing it made, as it already did for photos and videos.
- `scripts/readme_assets.py` builds the README's hero (light and dark), the logo tiles and the gallery cards;
  `scripts/readme_demos.py` takes the gallery's command bar pictures on the hidden desktop.

### Changed

- The README is a full product page: every supported model provider and all 118 programs and services at the top,
  a gallery of the command bar at work in nine programs, how requests become files and API calls, why AI PC does not
  drive programs through screenshots (with the research and our own CapCut run), eleven diagrams, and the measured
  results.
- Under the README's title, a short table compares vision agents with AI PC on model calls, speed and cost, each
  figure linked to its source or to our own runs.
- `THIRD_PARTY_NOTICES.md` says where the logos in `docs/assets/` come from.
- `packaging` is a direct dependency (the doctor compares installed versions with the requirements); it was already
  installed through matplotlib.
- The TinyClick server runs on transformers 5.10.1 (was 4.45.2), which fixes the 18 security advisories GitHub listed
  for the old version. TinyClick now loads through the Florence-2 code built into transformers:
  `services/tinyclick/convert.py` converts the downloaded weights once, so no code from the model's repository runs.
  It gives the same 12 test clicks, point for point, and the GPU path answers about three times faster. `timm` and
  `einops` are no longer needed.

### Fixed

- CI's secret scan failed on every pull request: it needs permission to read the request's commits.
- On a PC with no default printer (or with the print spooler off), "print it" went to the Office program instead of
  printing. Printing now takes it and names the printers to choose from; CI caught this on GitHub's Windows runner.

## [0.1.0] - 2026-10-05

### Added

- The one AI PC chat: one conversation for every program, with requests in several steps, 'it' / 'this video' /
  'the original' resolved to real files, voice notes (local Whisper), the browser page and the Telegram bridge.
- The command bar: Ctrl+Alt+Space anywhere, hold to talk, files selected in File Explorer or open in Office come
  along, live progress, results with open / show / copy, Yes / No for anything others will see, tray icon.
- Programs: video (JianYing / CapCut), Word / PowerPoint / Excel / PDF, photos, sound, design, CAD, 3D (Blender),
  converter, Windows files and settings, coding, designs to code, accounts, work apps, social media, and 88 more
  programs; the desktop agent for any program's user interface.
- The `ai-pc` command, with a subcommand per program, and `ai-pc keys` for the encrypted key vault; options with no
  command go to the chat (`ai-pc -m "make my photo brighter" --file car.jpg`).
- Keys from the environment, a `.env` file or the vault; all data paths in one place with `AI_PC_HOME`.
- Packaging (`pyproject.toml`, `uv.lock`), pytest (unit and integration suites), ruff, mypy (strict for the typed
  core), pre-commit, GitHub Actions (lint, type check, tests, gitleaks secret scan, build, releases), Dependabot,
  documentation in `docs/` with architecture decision records, and `THIRD_PARTY_NOTICES.md`.

### Changed

- The code moved from the `harness` package and root scripts into the `src/ai_pc` package, grouped by domain
  (`core`, `llm`, `media`, `desktop`, `video`, `assistant` and one package per program), with absolute imports.

### Fixed

- The desktop agent and the CapCut export could not reach app discovery (its module was hidden by the `apps`
  package of the same name).
- Two chats started in the same second shared one folder.
- The Vocaela click model's prompt was read when the module was imported, so the package failed to import on a PC
  without the model.
- `scripts/safe_wheels.py` refused stable-ABI wheels (for example `cp39-abi3`) that work on this Python.

[Unreleased]: https://github.com/FareedKhan-dev/ai-pc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/FareedKhan-dev/ai-pc/releases/tag/v0.1.0
