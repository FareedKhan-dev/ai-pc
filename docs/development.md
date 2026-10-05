# Development

## Set up

```powershell
uv sync                          # the locked environment, including the dev tools (pytest, ruff)
uv run pre-commit install        # optional: lint, format and secret checks before each commit
```

## Tests

| Command | What runs |
|---|---|
| `uv run pytest` | unit tests: fast, no programs, models or media needed (this is what CI runs) |
| `uv run pytest -m integration` | the integration suites: real programs on the hidden desktop, real files and media (slow) |
| `uv run pytest -m integration -k "aipc or bar"` | some suites |
| `uv run pytest -m live` | suites that need API keys, online accounts or a program on the visible desktop |
| `uv run python tests/integration/test_photo.py` | one suite on its own, with every check it makes |

Integration suites are scripts: each prints an `ok` / `FAIL` line per check and exits non-zero on a failure; pytest
runs each in its own process ([tests/integration/conftest.py](../tests/integration/conftest.py)). They never use the
real Desktop, Documents or AppData: everything they make goes under `out/_tests/`.

## Code style

- `uv run ruff check .` and `uv run ruff format .` (settings in `pyproject.toml`); CI fails on either.
- Absolute imports from `ai_pc`; the layers in [architecture](architecture.md) are enforced by a test.
- A broad `except Exception` carries its reason: `# noqa: BLE001 - the server is not running`.
- Comments and docstrings say what something does for the user, in plain words.

## Adding a program

1. **Prefer the program's own files or official interface.** Write its document format or call its command line or
   API; let the program render. Run it on the hidden desktop (`ai_pc.core.hidden_desktop`).
2. **A smaller program** is one module in `src/ai_pc/apps/` with `NAME`, `LABEL`, `EXAMPLES`, `parse(text, ctx)` and
   `run(op, ctx)`; set `OUTWARD = True` for anything others will see. It is found by name automatically.
3. **A larger program** is a package with a parser (rules), a chat (versions, undo, checks) and a command module in
   `src/ai_pc/cli/` registered in `cli/main.py`; add its adapter to `assistant/lanes.py`.
4. **Tests:** unit tests for its rules in `tests/unit/`, a suite in `tests/integration/` for the real program, and a
   routing case in `tests/unit/test_routing.py`.
5. **Installing a program** goes into `tools/<name>/`, downloaded from the publisher and verified first; Python
   wheels go through `scripts/safe_wheels.py` (PyPI hash check, then a scan of the contents, then an offline install).

## Dependencies

`pyproject.toml` lists what the code imports directly; `uv.lock` pins every version. To change one:
`uv add <package>` (or edit `pyproject.toml`), then `uv lock`, run the tests, and commit both files. Dependabot
proposes updates weekly.

## Releases

Versions follow [Semantic Versioning](https://semver.org); the version lives in `src/ai_pc/__init__.py`.

1. Move the `[Unreleased]` notes in [CHANGELOG.md](../CHANGELOG.md) under the new version and date.
2. Update `__version__`, commit, and tag: `git tag -a v0.2.0 -m "v0.2.0"`, then `git push --tags`.
3. The release workflow checks the tag against the version, builds the wheel and source archive, and publishes a
   GitHub release with that CHANGELOG section.

## Commits

Small, focused commits with [Conventional Commits](https://www.conventionalcommits.org) messages (`feat:`, `fix:`,
`refactor:`, `test:`, `docs:`, `build:`, `ci:`, `chore:`). Large formatting-only commits go in
`.git-blame-ignore-revs`.
