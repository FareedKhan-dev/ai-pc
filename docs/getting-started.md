# Getting started

## What you need

- Windows 11 (64-bit). AI PC drives Windows programs, so it runs on Windows only.
- [uv](https://docs.astral.sh/uv/) (it installs the right Python, 3.12, by itself) and Git.
- An API key for the language model provider (Nebius Token Factory). Most requests are handled by rules and never
  call the model; the key is needed for the rest.

## Set up

```powershell
git clone https://github.com/FareedKhan-dev/ai-pc.git
cd ai-pc
uv sync                                   # .venv with the exact versions in uv.lock, plus the dev tools
uv run ai-pc --help                       # the commands
```

Give it your model key, in one of these ways (see [configuration](configuration.md)):

```powershell
uv run ai-pc keys set NEBIUS_API_KEY      # typed at a hidden prompt, kept in this PC's encrypted vault
copy .env.example .env                    # or: put NEBIUS_API_KEY=... in .env (git-ignored)
```

## First steps

```powershell
uv run ai-pc chat                                     # talk to the one AI PC chat
uv run ai-pc chat -m "make my photo brighter" --file car.jpg
uv run ai-pc bar --shortcut                           # makes 'AI PC.lnk' here: pin it to Start
uv run ai-pc bar                                      # then press Ctrl+Alt+Space anywhere
```

Each program also has its own command (`ai-pc video`, `ai-pc office`, `ai-pc photo` ...); `ai-pc <command> --help`
shows its options.

## The programs it drives

Programs like the video editor, Office, Blender or GIMP must be on the PC. Office and JianYing are installed the usual
way. The others are portable copies in the project's `tools/` folder, downloaded from their publishers and checked
(SHA-256 against the published value, signatures where the publisher signs) before they are unpacked; see
[tools](tools.md). A program that is missing makes only its own requests fail, with a message that says what is missing.
`uv run ai-pc doctor` shows which programs are here.

Local models (Whisper for speech, the click models for the desktop agent) live in `models/`.

## Check the set-up

```powershell
uv run ai-pc doctor               # every program, model and package it uses: present or missing, with versions
uv run pytest                     # fast unit tests (about 15 s, nothing installed needed)
uv run pytest -m integration      # the full suites: real programs, files and media on this PC (slow)
```
