# Development

## Setup

```powershell
uv sync
uv run pre-commit install        # optional: runs lint, format and a secret scan before each commit
```

Two optional developer tools live in `tools/` like the programs: the GitHub CLI (`tools/gh/`) and gitleaks
(`tools/gitleaks/`, the same secret scan CI runs: `tools\gitleaks\gitleaks.exe git .`). `uv run ai-pc doctor` lists
them with everything else.

## Tests

| Command | Runs |
|---|---|
| `uv run pytest` | Unit tests. Fast, and they need none of the programs, models or media. CI runs these. |
| `uv run pytest -m integration` | Integration suites. They drive the real programs on the hidden desktop and use real media. Slow. |
| `uv run pytest -m integration -k "aipc or bar"` | Selected suites |
| `uv run pytest -m live` | Suites that need API keys, online accounts, or a program on the visible desktop |
| `uv run python tests/integration/test_photo.py` | One suite on its own, printing every check |

The integration suites are scripts: each prints an `ok` or `FAIL` line per check and exits with an error code when
something fails. pytest runs each one in its own process ([tests/integration/conftest.py](../tests/integration/conftest.py)).
They write only under `out/_tests/` and never touch the real Desktop, Documents or AppData.

## Code style

- `uv run ruff check .` and `uv run ruff format .`; settings are in `pyproject.toml`. CI fails on lint or format errors.
- `uv run mypy` type-checks the modules listed under `[tool.mypy]`. New modules should be typed and added there.
- Absolute imports from `ai_pc`, and the layer rules in [architecture](architecture.md).
- A broad `except Exception` states its reason: `# noqa: BLE001 - the server is not running`.

## Adding a program

1. Drive it through its own files or official interface where possible, and run it on the hidden desktop
   (`ai_pc.core.hidden_desktop`).
2. A small program is one module in `src/ai_pc/apps/` with `NAME`, `LABEL`, `EXAMPLES`, `parse(text, ctx)` and
   `run(op, ctx)`. Set `OUTWARD = True` if its results are seen by other people. The chat finds it by name.
3. A larger program is its own package: request rules, a chat with versions and undo, and checks. Add its command in
   `src/ai_pc/cli/`, register it in `cli/main.py`, and add an adapter in `assistant/lanes.py`.
4. Add unit tests for its rules in `tests/unit/`, an integration suite in `tests/integration/`, and a routing case in
   `tests/unit/test_routing.py`.
5. Put its executable in `tools/<name>/`. Download it from the publisher and check the hash (and signature, if there
   is one) before unpacking. Python wheels go through `scripts/safe_wheels.py`.

## Dependencies

Direct dependencies are listed in `pyproject.toml`, and `uv.lock` pins every version. To change one, run
`uv add <package>` (or edit `pyproject.toml` and run `uv lock`), run the tests, and commit both files. Dependabot
opens pull requests for updates every week.

## Releases

The project uses [semantic versioning](https://semver.org). The version is set in `src/ai_pc/__init__.py`.

1. Move the notes under `[Unreleased]` in [CHANGELOG.md](../CHANGELOG.md) to a new version heading with today's date.
2. Update `__version__`, commit, then tag and push: `git tag -a v0.2.0 -m "v0.2.0"` and `git push --tags`.
3. The release workflow checks that the tag matches the version, builds the wheel and source archive, and creates a
   GitHub release with that part of the changelog.

## Commits

Small commits with [Conventional Commits](https://www.conventionalcommits.org) messages (`feat:`, `fix:`, `refactor:`,
`test:`, `docs:`, `build:`, `ci:`, `chore:`). Commits that only reformat code are listed in `.git-blame-ignore-revs`.

## Known gaps

- Some modules are very large (`video/quick_edits.py` is about 4,100 lines) and should be split.
- Most code has no type hints yet; mypy only covers the modules listed in `pyproject.toml`.
- Progress is reported through `log` callbacks and `print` rather than the `logging` module.
- The integration suites are scripts with their own check helper, not native pytest tests.
- The programs in `tools/` are set up by hand on each PC (`ai-pc doctor` shows which are present); there is no
  installer for them yet.
