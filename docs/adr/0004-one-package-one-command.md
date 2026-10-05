# 0004. One installable package (`src/ai_pc`) and one command (`ai-pc`)

- Status: accepted
- Date: 2026-10-05

## Context

The prototype grew as a flat `harness` package with about sixty loose modules, thirty scripts in the project root
(products, benchmarks and experiments mixed together), script-style test suites that changed `sys.path` to import
the code, and one 1,300-line README. A module `harness/apps.py` was silently hidden by the package `harness/apps/`.

## Decision

- One package in the `src/` layout, `ai_pc`, grouped by domain: `core`, `llm`, `media`, `desktop`, `video`,
  `assistant`, and one package per program. Imports are absolute; dependencies only point downwards, enforced by
  `tests/unit/test_layers.py`.
- One command, `ai-pc <program>`, with each program's command line in `ai_pc/cli/` (loaded only when used).
- `pyproject.toml` with `uv.lock`; pytest with fast unit tests for CI and the integration suites as marked tests;
  ruff for lint and format; GitHub Actions; documentation in `docs/`.

## Consequences

- The package installs and imports like any other; tools, CI and editors understand its layout.
- The old root scripts are gone; their commands are `ai-pc <program>` (see the CHANGELOG for the mapping).
- Integration suites still print their own checks; converting them to native pytest tests can happen one at a time.
