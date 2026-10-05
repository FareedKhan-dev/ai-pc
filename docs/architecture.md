# Architecture

## In one picture

```
   you:   ai-pc chat     Ctrl+Alt+Space bar     the web page      Telegram       ai-pc <program> ...
             |                  |                    |                |                 |
             +------------------+------ the one chat (assistant) -----+                 |
                                |   which program? (rules first, the model only when unsure)
                                |   'it', 'this video', 'the original' -> real files
                                v                                                       v
   programs:  video  office  photo  sound  design  cad  3d  convert  windows  coding  accounts  hub  social  apps (88)  desktop
                |  each writes the app's own files or calls its official interface; the app only renders
                |  every step checked; versions and undo; a yes before anything others will see
                v
   shared:    llm (the model client, planners)   media (audio, speech, frames)   core (config, paths, keys, hidden desktop)
                |
   on this PC: the programs themselves (Office, JianYing, Blender, GIMP ... in tools/), run on a hidden desktop
```

## Principles every program follows

The reasons behind these are in the [decision records](adr/README.md).

1. **Code first, not clicks.** A program writes the application's own file format (a JianYing draft, a .docx, a
   DXF, a Blender scene) or calls its official command line or API, then lets the application render. Driving a
   user interface is the last resort, used only by the desktop agent.
2. **Every step is checked.** Each change is measured on the result (the exported video at the edit points, the
   rendered PDF page, the photo's histogram), and a failed check is said, never hidden.
3. **Versions and undo.** Each program keeps its own conversation with versions; 'undo' goes back a step.
4. **A yes before anything others will see.** Posting, sending, uploading or emailing is previewed first and waits.
5. **Nothing on your screen.** Programs run on a hidden Windows desktop; the mouse and keyboard are never used.
6. **Rules first, the model when needed.** Requests are read by rules; the (cheap) model is asked only when the rules
   cannot tell, and never sees keys.
7. **Everything stays in the project folder.** Programs, models, outputs and state live inside it
   ([configuration](configuration.md)).

## Repository layout

```
ai-pc/
├── src/ai_pc/              the package (installed as `ai-pc`)
│   ├── cli/                the ai-pc command: one subcommand per program
│   ├── assistant/          the one chat: router, artifacts, program adapters, command bar, web page, Telegram, voice
│   ├── video/ office/ photo/ sound/ design/ cad/ three/ convert/ windows/ coding/ accounts/ hub/ social/
│   │                       one package per program, each with its parser (rules), chat (versions, undo) and checks
│   ├── apps/               88 smaller programs, one module each, found by name
│   ├── desktop/            the desktop agent: UI Automation, skills, safety, vision grounding
│   ├── llm/                the model client, planners, prompts
│   ├── media/              audio, speech (local Whisper), frames, music and sound effects
│   └── core/               configuration, paths, keys and the encrypted vault, the hidden desktop, headless browser
├── tests/
│   ├── unit/               fast tests, no programs or media needed (CI)
│   └── integration/        suites that drive real programs and media on this PC (pytest -m integration)
├── services/tinyclick/     the TinyClick click-model server (its own GPU environment)
├── scripts/                maintenance: model benchmarks, stock media, safe downloads, stress runs
├── docs/                   this documentation
├── pyproject.toml          package metadata, dependencies, tool settings
└── uv.lock                 the exact versions, for every machine and CI
```

## Layers

Dependencies only point downwards, and a unit test ([tests/unit/test_layers.py](../tests/unit/test_layers.py))
keeps it that way:

| Layer | May use |
|---|---|
| `cli` | everything |
| `assistant` | the programs, `llm`, `media`, `core` |
| programs (`video`, `office` ... `apps`, `desktop`) | each other, `llm`, `media`, `core` |
| `llm`, `media` | `core` |
| `core` | nothing else in the package |

Imports are absolute (`from ai_pc.core.config import ROOT`).

## The one chat

[src/ai_pc/assistant/](../src/ai_pc/assistant/) turns a message into work:

| Part | Role |
|---|---|
| `chat.py` | the conversation: files sent and made, steps, a pending yes, saved chats |
| `router.py` | which program a message is for: words, file kinds, the programs' own rules, the conversation in progress |
| `artifacts.py` | 'it', 'this video', 'the original', 'the plan' and file names, resolved to real files |
| `lanes.py` | an adapter per program: open its conversation, pass the message, list what it made |
| `agent.py`, `bar.py`, `shell.py`, `mic.py` | the command bar: the worker, the window, the global hotkey and tray, the microphone |
| `web.py`, `telegram.py`, `voice.py` | the browser page (127.0.0.1), the Telegram bridge, voice notes |

Adding a program: a package (or an `apps/` module whose `parse()` claims requests), an adapter in `lanes.py` if it
keeps its own conversation, routing words in `router.py`, and a routing case in
[tests/unit/test_routing.py](../tests/unit/test_routing.py). See [development](development.md).
