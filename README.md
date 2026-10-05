# AI PC

[![CI](https://github.com/FareedKhan-dev/ai-pc/actions/workflows/ci.yml/badge.svg)](https://github.com/FareedKhan-dev/ai-pc/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Windows 11](https://img.shields.io/badge/platform-Windows%2011-0078d4)

AI PC is a Windows assistant that does work in desktop programs through code. You ask for something in a chat (in the
terminal, in a pop-up bar opened with Ctrl+Alt+Space, on a local web page or from Telegram) and it hands the request
to the program that can do it: JianYing for video, Word, PowerPoint and Excel for documents, Blender for 3D, and about
a hundred others.

Programs are driven through their own file formats and official interfaces rather than by clicking on the screen, and
they run on a hidden desktop, so you can keep using the PC. Each result is checked after it is made. Anything that
other people will see (a Slack message, an email, a social media post) is shown to you first and waits for a yes.

## Requirements

- Windows 11, 64-bit
- [uv](https://docs.astral.sh/uv/) and Git
- A Nebius API key for the requests that need a language model (most are handled by rules)
- The programs you want it to drive; see [docs/tools.md](docs/tools.md)

## Install

```powershell
git clone https://github.com/FareedKhan-dev/ai-pc.git
cd ai-pc
uv sync
uv run ai-pc keys set NEBIUS_API_KEY
```

`uv sync` creates `.venv` with Python 3.12 and the exact versions in `uv.lock`. The key goes into an encrypted vault
on this PC; a `.env` file works too (see [docs/configuration.md](docs/configuration.md)).

## Usage

```powershell
uv run ai-pc chat                                           # interactive chat
uv run ai-pc chat -m "make my photo brighter" --file car.jpg
uv run ai-pc bar                                            # background bar, opened with Ctrl+Alt+Space
uv run ai-pc video --help                                   # each program also has its own command
```

| Command | Purpose |
|---|---|
| `ai-pc chat` | The chat: requests, files and voice notes |
| `ai-pc bar` | The Ctrl+Alt+Space bar (hold the keys to talk) |
| `ai-pc web`, `ai-pc telegram` | The chat in a browser on this PC, or through your own Telegram bot |
| `ai-pc video`, `office`, `photo`, `sound`, `design`, `cad`, `3d`, `convert`, `windows`, `code`, `accounts`, `hub`, `social`, `apps` | One program at a time |
| `ai-pc agent` | The desktop agent, for programs that can only be used through their interface |
| `ai-pc keys` | API keys in the encrypted vault |

## Documentation

Start with [getting started](docs/getting-started.md) and [configuration](docs/configuration.md). The
[architecture](docs/architecture.md) page explains how the code is organised, and [docs/README.md](docs/README.md)
lists a page for each program.

## Development

```powershell
uv run pytest                     # unit tests, about 15 s
uv run pytest -m integration      # suites that drive the real programs (slow)
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md).

## Security

Please report security problems privately; see [SECURITY.md](SECURITY.md).

## License

Copyright (c) 2026 FareedKhan-dev. All rights reserved. See [LICENSE](LICENSE). Third-party components are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
