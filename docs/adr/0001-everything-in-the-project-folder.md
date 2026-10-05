# 0001. Keep programs, models and data inside the project folder; verify every download

- Status: accepted
- Date: 2026-09-30

## Context

AI PC drives dozens of programs and uses local models. Installing them system-wide would spread files and settings
across Program Files, AppData and the registry, mix them with the user's own installations, and make the PC hard to
clean up. Each download is also a chance to run something unsafe.

## Decision

Portable copies of programs live in `tools/`, models in `models/`, everything made in `out/`, and learned state in
`state/`, all inside the project folder (`AI_PC_HOME` can move it). Each program's settings are redirected into its
own folder so nothing is written to AppData. Every download is checked before use: the publisher's SHA-256, a
signature where the publisher signs, and for Python wheels a scan of their contents (`scripts/safe_wheels.py`).
Installers are unpacked, not run, where possible.

## Consequences

- Removing the folder removes everything; the user's own programs and settings are untouched.
- These folders are large and stay out of the repository; a new PC fetches them again.
- Some programs need extra work to stay portable (redirected settings folders, environment variables).
