# Security

## Reporting a problem

Please report security problems privately, not in a public issue: use GitHub's **Report a vulnerability** on the
repository's Security tab, or contact the owner, @FareedKhan-dev. Include what you found, how to reproduce it, and
what it could affect. You will get an answer within a week.

## Supported versions

Only the latest release on `main` receives security fixes.

## How AI PC protects you

| Area | Protection |
|---|---|
| API keys | read from the environment, a git-ignored `.env`, or a vault encrypted with Windows DPAPI (this Windows user only); never printed, logged, saved in chats or sent to a model; scrubbed from error messages |
| Actions others see | posting, sending, uploading and emailing are previewed and wait for the user's yes |
| The user's screen | programs run on a separate hidden desktop; the mouse and keyboard are never used; the command bar uses a Windows hotkey, not a keyboard hook |
| Local servers | the browser page and helper servers listen on 127.0.0.1 only, with a per-run secret for the page |
| Files | outputs stay in the project folder; the user's original files are never changed; risky file operations ask first and go to the Recycle Bin |
| Downloads | programs and Python wheels are checked against the publisher's hash (and signature where available) before use |
| The desktop agent | terminals, editors, password managers and system tools are never controlled; an independent check classifies every action |
| The repository | secrets and personal data are git-ignored; pre-commit runs a secret scan (gitleaks) before each commit |
