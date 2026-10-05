# Changelog

All notable changes to this project are written down here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org).

## [Unreleased]

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
- Packaging (`pyproject.toml`, `uv.lock`), pytest (unit and integration suites), ruff, pre-commit, GitHub Actions
  (lint, tests, build, releases), Dependabot, documentation in `docs/`.

### Changed

- The code moved from the `harness` package and root scripts into the `src/ai_pc` package, grouped by domain
  (`core`, `llm`, `media`, `desktop`, `video`, `assistant` and one package per program), with absolute imports.

### Fixed

- The desktop agent and the CapCut export could not reach app discovery (its module was hidden by the `apps`
  package of the same name).
- Two chats started in the same second shared one folder.
- The Vocaela click model's prompt was read when the module was imported, so the package failed to import on a PC
  without the model.

[Unreleased]: https://github.com/FareedKhan-dev/ai-pc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/FareedKhan-dev/ai-pc/releases/tag/v0.1.0
