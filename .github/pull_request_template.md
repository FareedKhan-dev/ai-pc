## What and why

<!-- What does this change, and why is it needed? Link the issue it closes (Closes #123). -->

## How it was checked

- [ ] `uv run pytest` (unit tests) passes
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] Integration suites for the parts touched pass (`uv run pytest -m integration -k <name>`)
- [ ] New behaviour has a test

## Safety

- [ ] Nothing others will see (posts, messages, emails, uploads) happens without the user's yes
- [ ] No keys, tokens or personal files are added; nothing is written outside the project folder
- [ ] Programs run on the hidden desktop: no window, mouse or keyboard use on the user's screen

## Notes for the changelog

<!-- One line for CHANGELOG.md under [Unreleased]. -->
