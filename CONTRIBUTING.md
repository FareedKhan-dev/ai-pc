# Contributing

This is a private repository. These notes are for people with access to it.

## Workflow

1. Branch from `main` (`feat/<topic>`, `fix/<topic>`, `docs/<topic>`).
2. Keep commits small and use [Conventional Commits](https://www.conventionalcommits.org) messages.
3. Run the checks below, open a pull request, and fill in the template. CI has to pass before merging.

## Checks

```powershell
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest                                  # unit tests
uv run pytest -m integration -k <area>         # integration suites for the code you changed
```

## Rules

- Programs run on the hidden desktop. Code must never move the mouse, type into other windows, or open windows on
  the user's screen.
- Anything that other people will see (posts, messages, emails, uploads) must be previewed and confirmed first.
- No keys or tokens in the repository. Use the environment, `.env` or the vault, and use fakes in tests.
- Keep downloads and data inside the project folder, and check every download before using it
  (see [docs/tools.md](docs/tools.md)).
- Include tests: unit tests for rules and logic, and an integration check against the real program.

More detail is in [docs/development.md](docs/development.md) and [docs/architecture.md](docs/architecture.md).
