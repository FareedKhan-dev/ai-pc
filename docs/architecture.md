# Architecture

## Overview

```
 entry points    ai-pc chat | Ctrl+Alt+Space bar | web page | Telegram        ai-pc <program>
                        \            |             /                               |
 the chat              assistant: route the request, resolve "it" to a file        |
                                     |                                             |
 programs        video  office  photo  sound  design  cad  three  convert  windows  coding
                 accounts  hub  social  apps (88 small programs)  desktop (UI agent)
                                     |
 shared          llm (model client, planners)   media (audio, speech, frames)   core
                                     |
 on the PC       JianYing, Office, Blender, GIMP, ... (tools/), run on a hidden desktop
```

A request comes in through one of the entry points. The assistant decides which program it is for, using rules first
and the language model only when the rules cannot tell. It also works out which file "it" or "this video" refers to.
The program then does the work by writing the application's own files or calling its official interface, checks the
result, and saves a new version that can be undone.

## Design rules

The reasons behind these are in the [decision records](adr/README.md).

1. Drive programs through their files and official interfaces. The desktop agent, which works through the user
   interface, is only for programs that offer nothing else.
2. Check every result: measure the exported video at the edit points, read back the rendered PDF, compare the photo
   before and after. A failed check is reported, not hidden.
3. Keep versions, so "undo" works in every program.
4. Ask before anything that other people will see: posts, messages, emails, uploads.
5. Never use the user's screen, mouse or keyboard. Programs run on a separate hidden desktop.
6. Keep everything in the project folder, and verify every download ([configuration](configuration.md)).

## Repository layout

```
ai-pc/
├── src/ai_pc/
│   ├── cli/            the ai-pc command, one module per subcommand
│   ├── assistant/      the chat, routing, file references, the bar, the web page, Telegram, voice notes
│   ├── video/ office/ photo/ sound/ design/ cad/ three/ convert/ windows/ coding/ accounts/ hub/ social/
│   │                   one package per program: request rules, a chat with versions, checks
│   ├── apps/           88 smaller programs, one module each, found by name
│   ├── desktop/        the UI agent: UI Automation, skills, safety checks, click models
│   ├── llm/            model client, planners, prompts
│   ├── media/          audio, speech (local Whisper), frames, generated music and sound effects
│   └── core/           configuration, paths, keys and the vault, the hidden desktop, headless browser
├── tests/
│   ├── unit/           fast tests that need none of the programs or media
│   └── integration/    suites that run the real programs (pytest -m integration)
├── services/tinyclick/ the TinyClick click-model server, in its own GPU environment
├── scripts/            benchmarks, test media download, wheel review, stress runs
├── docs/
├── pyproject.toml
└── uv.lock
```

## Layers

Imports only go down this list. `tests/unit/test_layers.py` fails if one goes up.

| Package | Can import |
|---|---|
| `cli` | anything |
| `assistant` | the programs, `llm`, `media`, `core` |
| the programs, `apps`, `desktop` | each other, `llm`, `media`, `core` |
| `llm`, `media` | `core` |
| `core` | nothing else in the package |

All imports are absolute, for example `from ai_pc.core.config import ROOT`.

## The chat

The code is in [src/ai_pc/assistant/](../src/ai_pc/assistant/):

| Module | Job |
|---|---|
| `chat.py` | The conversation: files sent and made, multi-step requests, pending confirmations, saving |
| `router.py` | Picks the program for a message from its words, the kinds of files, each program's rules and the conversation so far |
| `artifacts.py` | Resolves "it", "this video", "the original", "the plan" and file names to real files |
| `lanes.py` | One adapter per program: start its conversation, pass the message, list the files it made |
| `agent.py`, `bar.py`, `shell.py`, `mic.py` | The bar: worker thread, window, global hotkey and tray icon, microphone |
| `web.py`, `telegram.py`, `voice.py` | The local web page, the Telegram bridge, voice note transcription |

[docs/development.md](development.md) describes how to add a program.
