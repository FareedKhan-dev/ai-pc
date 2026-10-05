# Security policy

## Reporting a problem

Do not open a public issue for a security problem. Contact the repository owner, @FareedKhan-dev, directly with a
description of the problem, the steps to reproduce it, and what it affects. You should get a reply within a week.

## Supported versions

Security fixes go into the latest version on `main`.

## How the project handles security

| Area | What the code does |
|---|---|
| API keys | Read from the environment, a git-ignored `.env`, or a vault encrypted with Windows DPAPI (readable only by the same Windows user). Keys are not printed, logged, saved in chat history or sent to the language model, and they are removed from error messages. |
| Outgoing actions | Posting, sending, uploading and emailing show a preview and wait for the user to confirm. |
| The user's screen | Programs run on a separate hidden desktop. The bar uses a Windows hotkey registration, not a keyboard hook, and code never moves the mouse or types into the user's windows. |
| Local servers | The web page and helper servers listen on 127.0.0.1 only. The web page also requires a per-run token. |
| Files | Results are written inside the project folder and the user's original files are not modified. Deletions ask first and go to the Recycle Bin. |
| Downloads | Programs and Python wheels are checked against the publisher's hash, and signature where one exists, before they are used. |
| Desktop agent | Terminals, code editors, password managers and system tools are on a block list, and every action is classified by a separate safety check. |
| Repository | Keys, personal files and local data are git-ignored. pre-commit and CI run a gitleaks secret scan. |
