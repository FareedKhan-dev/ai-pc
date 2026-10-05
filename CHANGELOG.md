# Changelog

All notable changes to this project are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org).

## [Unreleased]

### Added

- `ai-pc doctor`: checks that every program, model, environment and Python package AI PC uses is on this PC, shows
  their versions, and names folders in `tools/` that no code uses. `--json` gives the same with paths.
- `scripts/readme_assets.py` builds the README's hero picture (light and dark) and the logo tiles from
  `docs/assets/logos/`, with the hidden headless browser.

### Changed

- The README is a full product page: how requests become files and API calls, why AI PC does not drive programs
  through screenshots (with the research and our own CapCut run), eleven diagrams, every program with its logo, the
  command bar's own screenshots, and the measured results.
- `THIRD_PARTY_NOTICES.md` says where the logos in `docs/assets/` come from.

- `packaging` is a direct dependency (the doctor compares installed versions with the requirements); it was already
  installed through matplotlib.

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
