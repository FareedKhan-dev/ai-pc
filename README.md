# AI PC

[![CI](https://github.com/FareedKhan-dev/ai-pc/actions/workflows/ci.yml/badge.svg)](https://github.com/FareedKhan-dev/ai-pc/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Windows 11](https://img.shields.io/badge/platform-Windows%2011-0078d4)

An assistant for Windows that does real work in desktop programs, by code. Ask in one chat (typed, spoken, from a
Ctrl+Alt+Space command bar, the browser or Telegram) and it edits the video in JianYing, writes the Word report,
fixes the photo, draws the house plan, posts to Slack after your yes, and works with 100+ more programs.

- **One conversation for everything.** "Add a glow effect to my video", then "send it to Slack #team": 'it' is the
  edited video, handed from one program to the next.
- **Code, not clicks.** Each program writes the application's own files or calls its official interface, and the
  application only renders. Nothing appears on your screen; the mouse and keyboard are never touched.
- **Checked, versioned, undoable.** Every change is measured on the result; 'undo' goes back a step; anything others
  will see waits for your yes.
- **Fast and cheap.** Requests are read by rules first; a low-cost model is asked only when the rules cannot tell.

## Quick start

```powershell
git clone https://github.com/FareedKhan-dev/ai-pc.git
cd ai-pc
uv sync                                     # Python 3.12 and the locked dependencies
uv run ai-pc keys set NEBIUS_API_KEY        # your model key, kept in the encrypted vault
uv run ai-pc chat                           # talk to it
uv run ai-pc bar                            # or press Ctrl+Alt+Space anywhere
```

Full set-up, including the programs it drives: [docs/getting-started.md](docs/getting-started.md).

## Commands

| Command | What it does |
|---|---|
| `ai-pc chat` | the one AI PC chat: type requests, send files and voice notes |
| `ai-pc bar` | the Ctrl+Alt+Space command bar (waits in the background; hold the combo to talk) |
| `ai-pc web`, `ai-pc telegram` | the chat in your browser (this PC only), or from your phone through your Telegram bot |
| `ai-pc video`, `office`, `photo`, `sound`, `design`, `cad`, `3d`, `convert`, `windows`, `code`, `accounts`, `hub`, `social`, `apps` | each program on its own |
| `ai-pc agent` | operate any desktop program through its user interface |
| `ai-pc keys` | API keys in this PC's encrypted vault |

`ai-pc --help` lists them all; `ai-pc <command> --help` shows a command's options.

## Documentation

- [Getting started](docs/getting-started.md) and [configuration](docs/configuration.md)
- [Architecture](docs/architecture.md): how the pieces fit, the repository layout
- [The chat and the command bar](docs/assistant.md), [the desktop agent](docs/desktop-agent.md), [safety](docs/safety.md)
- [Every program](docs/README.md#the-programs) and [the portable programs it drives](docs/tools.md)
- [Development](docs/development.md): tests, code style, adding a program, releases

## Development

```powershell
uv run pytest                    # unit tests (CI)
uv run pytest -m integration     # the suites that drive real programs on this PC
uv run ruff check . ; uv run ruff format --check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md).

## Security

Keys stay in the environment, a git-ignored `.env`, or the DPAPI-encrypted vault; they are never logged or sent to a
model. Local servers listen on 127.0.0.1 only. Report problems privately: [SECURITY.md](SECURITY.md).

## Licence

Copyright (c) 2026 FareedKhan-dev. All rights reserved; see [LICENSE](LICENSE). Third-party components keep their own
licences.
