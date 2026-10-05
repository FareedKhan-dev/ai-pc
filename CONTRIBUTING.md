# Contributing

This is a private repository. Thank you for helping; please read this first.

## Workflow

1. Create a branch from `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`.
2. Make small, focused commits with [Conventional Commits](https://www.conventionalcommits.org) messages.
3. Run the checks below, then open a pull request and fill in its template. CI must pass and a code owner reviews.

## Checks

```powershell
uv sync
uv run ruff check . ; uv run ruff format --check .
uv run pytest                                  # unit tests
uv run pytest -m integration -k <area>         # the suites for the parts you changed
```

## Rules for every change

- **Nothing on the user's screen.** Programs run on the hidden desktop; never move the mouse, type, or open windows.
- **A yes before anything others will see**: posting, sending, uploading, emailing.
- **No secrets in the repository**: keys belong in the environment, `.env` or the vault. Use fakes in tests.
- **Everything stays in the project folder**: downloads are verified first (see [docs/tools.md](docs/tools.md)).
- **Tests with the change**: unit tests for rules and logic, an integration check for the real program.

More detail: [docs/development.md](docs/development.md) and [docs/architecture.md](docs/architecture.md).
