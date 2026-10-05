# Fast computer-use agent harness (Windows)

An agent that operates Windows apps it has never seen, and gets **faster every time it repeats a task**.
It does not try to make "thinking" fast. It makes thinking **rare**: once a task succeeds, the agent turns it
into a skill and replays it in milliseconds, with no model call at all.

## The one AI PC chat: everything from one conversation, typed or a voice note

```
aipc.py                                       talk here (a line that is a file path sends it; 'voice <file>' sends a voice note)
aipc.py -m "add a glow effect to my video" --file me.mp4 -m "send it to slack #team" -m yes
aipc.py --voice note.m4a                      a voice note from your phone or a recorder
aipc.py --resume                              carry on the last chat ('it' still means what it meant)
aipc.py telegram                              your phone as the remote: messages, voice notes, photos, videos and documents
                                              you send your own Telegram bot come here, and the replies and files go back
aipc.py web                                   the chat as a page in your browser on this PC: type, attach, hold the mic to talk
aipc.py bar                                   the AI PC in the background: Ctrl+Alt+Space anywhere opens the command bar
                                              (or double-click 'AI PC.lnk' in this folder; pin it to Start or the taskbar)
```

One chat drives every program on this PC. Each message goes to the program it is for: the video agent (CapCut /
JianYing), Word / PowerPoint / Excel / PDF, photos, sound, design, house plans and parts (CAD), 3D (Blender), the
converter, Windows files and settings, coding, accounts and invoices (QuickBooks, Tally, Xero, Zoho, FBR), work apps
(Slack, Teams, Outlook, Gmail, Calendar, Drive, Trello, Asana, Notion, Jira, HubSpot, Zoom, Telegram, WhatsApp, Figma,
Canva), social media (Facebook, Instagram, Threads, YouTube, TikTok, LinkedIn, X), and the 88 programs of the apps lane
by name (Photoshop, GIMP, Krita, OBS, MuseScore, KiCad, VS Code, Flutter, PostgreSQL, MongoDB, Power BI, 7-Zip ...).

| Part | What it does |
|---|---|
| Which program ([harness/aipc/router.py](harness/aipc/router.py)) | Rules first: words that name a program or its work, the kinds of the files sent, what the 88 program modules recognise by their own rules, and the conversation in progress ("make it stronger" stays with the video; after a Slack send, "make it darker" goes back to the photo). The cheap model is asked only when the rules cannot tell. A request in steps ("add a glow to my video, then send it to Slack") runs step by step. |
| 'it', 'this video', 'the original' ([harness/aipc/artifacts.py](harness/aipc/artifacts.py)) | Every file sent and every file a program made is remembered with its kind: 'it' is the newest thing made, 'the video' the edited one, 'the original video' the one you sent, 'the plan' its PDF, a file's name finds it. A program's internal version file (v3.png) goes to other people as a copy with a clear name (car_edited.png). With no file sent, 'my car photo' is looked for in your Desktop, Downloads, Pictures, Videos, Music and Documents and offered as a numbered choice. |
| The programs ([harness/aipc/lanes.py](harness/aipc/lanes.py)) | Each keeps its own conversation and its own rules: checks at every step, 'yes' before anything others will see (the 'yes' goes back to the program that asked, and the remaining steps then run), versions and undo ('undo' goes to the program in use). |
| Voice notes ([harness/aipc/voice.py](harness/aipc/voice.py)) | Heard by the local Whisper (models/whisper/base, nothing leaves the PC); speech in another language comes back in English. Channel names said aloud ("Slack, general channel") are written #general. |
| Your phone ([harness/aipc/telegram.py](harness/aipc/telegram.py)) | Your Telegram bot (set up once with 'hub.py connect telegram'): only your own chat is listened to, strangers are ignored, messages from before the start are skipped, 'typing...' shows while work runs, and the files made come back (up to Telegram's 50 MB; larger ones are named with their place on the PC). |
| The page ([harness/aipc/web.py](harness/aipc/web.py)) | Served on 127.0.0.1 only (no firewall question); each run has a secret the page sends with every request, so another web page cannot drive the chat; only the chat's own files can be opened through it; the microphone button records a voice note in the browser. |
| Safety | Passwords typed in requests, secret fields and generated passwords are hidden in the saved chats; keys never reach the model; nothing is posted, sent or shared without your 'yes'. If the AI model is not answering, the chat says so plainly and changes nothing. |

Measured (2026-10-05): [tests/test_aipc.py](tests/test_aipc.py) 30/30 offline in 36 s (45 requests to the right program, steps,
references, photo -> Slack with the edited photo uploaded byte for byte, 'no' drops a send, a TTS voice note heard by Whisper,
the Telegram bridge end to end with a photo, a voice note and 'yes', a stranger ignored, a saved chat picked up, secrets hidden,
the page: served with its secret, a photo request done, its file opened, other files refused). Live, the request "hey can you create
a simple glow effect on my video" (a 16 s clip) was edited by the video agent through JianYing in about 4 minutes, and "please send
it to slack" then offered that edited video (not the original) and waited for a yes ($0.004 of AI).

### The command bar: Ctrl+Alt+Space anywhere

Double-click **AI PC.lnk** (or run `aipc.py bar`) once. Nothing opens: the AI PC waits in the background with an icon in
the tray. Then, in any program:

- **Ctrl+Alt+Space** opens the bar in the middle of the screen you are working on, ready to type. Enter sends, Esc (or a
  click elsewhere) hides it, Ctrl+Alt+Space again closes it. The conversation is the same one chat as above.
- **Hold Ctrl+Alt+Space and talk**; let go to send (or click the mic, Ctrl+M). Whisper on this PC hears it.
- **What you are looking at comes along.** Files selected in the File Explorer window in front (or on the desktop), or
  the document open in Word, Excel or PowerPoint in front, appear as chips ("From File Explorer: clip.mp4") and are
  'it' / 'this video' for the request, so selecting a video and saying "add a glow effect" just works. A request about
  something else ("turn on dark mode") is not handed them; several selected files go with "these" / "them" / "all".
  Files can also be dropped on the bar, attached (Ctrl+O), or pasted (Ctrl+V pastes copied files or a copied picture).
- **While it works** a thin line moves under the box and the bottom line says which program is busy and what it is
  doing ("Photos · Brighter ... · 0:04"). Close the bar and keep working: a notification says when it is done.
- **Results** come with a picture (photos, a frame of a video) and their files: click to open, show in the folder, or
  copy to paste anywhere (WhatsApp, an email, Explorer). Files leave with clear names (car_edited.png, not v3.png).
- **Anything others will see waits for Yes**: Yes / No buttons (Alt+Y / Alt+N). Ctrl+N starts a new chat; the bar
  carries on today's chat and starts afresh after 6 hours. Up recalls what you sent before. The pin keeps it open.
- **Tray icon menu**: Open, New chat, Start with Windows (off until you turn it on), Open the chats folder, Quit.

How it stays fast and safe ([harness/aipc/bar.py](harness/aipc/bar.py), [shell.py](harness/aipc/shell.py),
[agent.py](harness/aipc/agent.py), [mic.py](harness/aipc/mic.py)):

| | |
|---|---|
| Fast | Everything is loaded before you ask (the chat, the 88 programs' rules, ~0.7 s at start); the bar is built once and only shown, measured 58-86 ms from the combo to the bar on screen; requests run one at a time on a worker so the bar never freezes; Whisper loads while you are still talking. |
| The combo | A Windows hotkey (RegisterHotKey): no keyboard hook, nothing watches your typing; 'still held?' is read only while the combo is down. If another program has Ctrl+Alt+Space, it uses Ctrl+Alt+A (then Ctrl+Alt+Q) and says so. Change it in out/aipc/bar.json ("hotkey": "ctrl+alt+space"). |
| Your screen | It never moves the mouse or types for you; it takes the keyboard only when you press the combo. What is selected in Explorer or open in Office is read, never changed. Started from the shortcut it runs from python.exe with a console that has no window, so the programs it runs (FFmpeg, Git, compilers) never flash a black window. One copy runs: starting it again just shows the bar. |
| The microphone | Opened only while you hold the combo or the mic is on (Windows' own recorder, 16 kHz, nothing installed); recordings stay in the chat's folder. |
| Look | Windows 11 style: rounded corners, follows your light / dark setting and accent colour ("theme": "light" / "dark" to fix one), sharp on high-DPI screens. |

Measured (2026-10-05): [tests/test_bar.py](tests/test_bar.py) 52/52 in 25 s, with the real bar running on the hidden desktop
(never on your screen): the combo registered and pressed (a Windows message), the photo selected in Explorer brightened as 'it',
the reply with its picture and car_edited.png, holding the combo recording a voice note ("make it black and white", heard by
Whisper and done), 'send it to slack' waiting for Yes and the Yes uploading the edited photo, a file dropped on the bar, Esc, a
second start showing the running bar, New chat; the shortcut's start (pythonw -> python.exe with no console window) and one copy
running; pictures of the bar in out/_tests/bar/ui/. Not tested here, because they would show on your screen, use your microphone
or change your clipboard: the real Ctrl+Alt+Space on your desktop, the tray icon and its notifications, the microphone itself,
and Copy.

## How it works

```
goal ─► skill for this goal and this starting screen?
          │ yes ─► REFLEX: replay saved steps through UI Automation          ~60 ms – 1 s, 0 model calls
          │ no
          ▼
        QUICK PLANNER loop (Qwen3.8-27B, ~1 s per call)
          observe (UI tree, ~50–100 ms) → plan a batch → safety check → act (~5–10 ms per action)
          → verify (wait only until the UI reacts) → observe again ...
          • UI tree too thin (custom-drawn app)? → screenshot to a VISION planner (DeepSeek-V4.1-Flash)
            + TinyClick click-grounding on the Intel Arc GPU
          • stuck or unsure? → DEEP THINKER (Kimi-K3) writes a plan once, the quick planner follows it
          ▼
        success and a clean run → compiled into a skill (semantic steps, start-state precondition,
                                  typed parameters) → next time it takes the reflex path
```

| Lane | What it uses | Speed measured on this PC |
|---|---|---|
| Reflex (skill replay) | UI Automation patterns, keyboard | **56–64 ms** for 6 steps + reading the result (Calculator); 0.3 s from the command line; ~1 s when the app's own animations must play |
| Quick planner | Nebius `Qwen/Qwen3.8-27B` (thinking off) | ~0.9–1.1 s per model call; a new 4-step task takes ~5.5–6.6 s |
| Vision | `deepseek-ai/DeepSeek-V4.1-Flash` + TinyClick (0.23B) on the Arc 140T GPU | planner ~2–4 s; each vision click ~0.5–0.8 s |
| Deep thinker | `moonshotai/Kimi-K3` | ~10–26 s, used only when the quick planner is stuck or unsure |

The model choices come from `bench_models.py`, which benchmarks the planner prompt on your Nebius account. On 6
realistic cases × 3 runs, Qwen3.8-27B scored 18/18 correct with a ~1 s median. The other candidates scored 10–16/18 and were 1.5–3 s.

## Run it

```powershell
# dry run (default): plans and prints, touches nothing
.venv\Scripts\python.exe -m harness run "calculate 25 * 4 and tell me the result" --app Calculator

# act for real; risky steps are refused unless you approve them (--confirm ask prompts you)
.venv\Scripts\python.exe -m harness run "calculate 25 * 4 and tell me the result" --app Calculator --live

.venv\Scripts\python.exe -m harness skills            # learned skills (list | show NAME | delete NAME)
.venv\Scripts\python.exe -m harness apps calc         # installed apps, discovered at runtime
.venv\Scripts\python.exe -m harness probe --app Calc  # what the planner would see for a window (read-only)
.venv\Scripts\python.exe -m harness grounder start    # start the TinyClick vision server (auto-started when needed)
```

Options: `--planner file` routes planning through `runs/planner/req_N.json` files that a person or an assistant
answers. `--deep` makes it think first. `--param k=v` fills skill parameters. `--allow-app proc.exe` permits an
app on the blocked list.

The Nebius key is read from the `NEBIUS_API_KEY` environment variable, or from `my_nebius.txt`. It is never printed or logged.

## Unknown software

- **Finding apps:** installed apps are found at runtime (`Get-StartApps`), so something installed a minute ago can be opened by name.
- **Seeing the window:** every window is read through Windows UI Automation in one cached cross-process call. The planner
  sees each control's role, name, automation id, current value, on/off state and what it can do. It does not need to know the app.
- **Custom-drawn apps** (like CapCut) have no UI tree. For those the planner gets a screenshot, and TinyClick finds the
  click point. When a vision click lands on something UI Automation *can* name, the skill records that, and later
  replays use the fast lane instead of vision.
- **Tested on apps it had never seen:**
  - **Calculator:** switch to Scientific mode and take √144. Learned 3/3 times in 5.5–6.6 s; replays correct 3/3.
  - **Character Map** (classic Win32): find the copyright symbol's code. Learned in 5.4 s; replay 1.0 s including app start.

## Safety

- **Dry run by default.** Use `--live` to act.
- **Independent action check.** Every action is classified by the harness itself, not by the model. Delete, empty, send, buy,
  install, reset and similar actions are high risk and need confirmation. Close, cancel, sign in and similar are medium risk and are
  allowed only if your goal asked for it. In unattended mode, anything that needs confirmation is refused.
- **Pointer check on vision clicks.** The element actually under the predicted point is checked. Is it risky ("Close")?
  Is it plausibly the thing that was asked for ("Maximise Calculator" is not "the 7 button")? If not, the agent re-aims
  once on a settled screenshot, then refuses and tells the planner. If several batched targets collapse onto one spot,
  that grounding is discarded.
- **Blocked apps.** Terminals, VS Code, password managers, regedit and mmc are never controlled. Text is
  never typed into password fields.
- **Keystrokes only reach the target window.** If focus moves elsewhere, the agent refuses instead of typing into another app.
- **Screen text is data.** On-screen text that tries to give orders is ignored, and that is tested with a prompt-injection case.
- **Answers must be grounded.** If an answer is not visible on screen, the planner is asked to point at it.
- **Kill switch:** **Ctrl+Alt+Q** aborts a live run. Every step is logged with timings in `runs/<time>_<goal>/trace.jsonl`.

## Tests

| Command | What it proves |
|---|---|
| `python tests/test_foundation.py` | app discovery, launch, snapshot speed (2.5× faster than a naive walk), ~7.6 ms per press |
| `python tests/test_agent_offline.py` | loop mechanics with a deterministic model stand-in: learning, 0-call replay, typed parameters, safety (including a deliberately mis-grounded vision click), dry run, vision lane. **27/27** |
| `python tests/test_agent_llm.py trials` | real models: learn the unknown Calculator task from scratch 3 times, then replay. **3/3 / 3/3 / 3/3** |
| `python tests/test_charmap.py` | real models on a classic Win32 app it has never seen, then replay |
| `python bench_models.py fast\|vision\|deep` | re-benchmark Nebius models for each planner role |
| `python tests/test_aipc.py` | the one AI PC chat offline: routing, references, steps, voice, Telegram, the page. **30/30** |
| `python tests/test_bar.py` | the Ctrl+Alt+Space command bar, run for real on the hidden desktop (combo, Explorer selection, voice, Yes, drop, start-up). **52/52** |

## Limits

- **First-time tasks take seconds, not milliseconds.** Each model call costs ~1 s, mostly network distance to Nebius in
  the EU. The speed comes from not calling the model on repeats.
- **Skills are learned only from clean runs:** no failed actions, no stuck periods, no corrections. A messy success is
  re-planned the next time, and the cleaner run is learned then.
- **Skills replay only from a similar starting screen**, compared by the set of controls (Jaccard similarity ≥ 0.8). A different starting state means planning again, which learns a second variant.
- **Vision is the slow and weaker lane.** About 0.5–0.8 s per click, and weak on icon-only buttons (TinyClick scored 9/12 on CapCut's home screen).
- **Budgets:** 30 steps, 14 model calls and 180 s per run (`harness/config.py`).
- **Not yet built:**
  - a browser lane (DOM via Playwright or CDP);
  - consolidating messy runs into clean skills (a deep model rewriting the trace, then verifying it);
  - a local small planner to remove network latency.
- **Not yet tested:** Office apps, Electron apps with very large trees, and live CapCut.

## Video agent (JianYing 5.9, code-first)

Video editing does not go through the screen. The agent writes the JianYing project as code (pyJianYingDraft), lets
JianYing render it in the background, and then checks the export **at each edit's own moment**.

```powershell
.venv\Scripts\python.exe studio.py new "edit this for instagram: lightning on my eye, shaky boss entrance" --media media\clip1.mp4 media\clip2.mp4
.venv\Scripts\python.exe studio.py revise <draft> "make the lightning stronger and end with a slow zoom"
.venv\Scripts\python.exe studio.py verify <draft>
```

```
request + media ─► analyse media (faces/eyes, shots, motion, green screen, beats; 1 vision call per file; cached)
               └─► brief (fast model, in parallel): platform, length, mood, story, every idea as a "need"
               ─► knowledge-base search: free catalogue items per need (body-part targets first, proven items ranked up)
               ─► plan (video model): clips + edits, each edit with an id and an "expect"
               ─► resolve: names checked (VIP / undownloadable / login-only / never-rendering items replaced by meaning),
                  times made absolute, macros expanded (speed ramps, reverse, freeze, shake, zoom punch, beat sync,
                  music ducking), reframing from face positions, text kept in the platform's safe zone
               ─► build the draft (~0.5 s) ─► export in the background (no mouse; downloads checked first)
               ─► verify at the edit points ─► fix what failed ─► rebuild / re-export / re-check what changed
```

| Step | Measured (this PC, 15 s Instagram reel, 3 source clips) |
|---|---|
| media analysis (first time / cached) | 4–9 s / 0 s |
| brief + plan | 1.5 s + 8–15 s |
| resolve + build | 0.4–1 s |
| export (JianYing behind other windows) | 25–40 s (render ~15–25 s) |
| verification of ~25 edit points | 12–15 s |
| whole run incl. 2 fix rounds | 125–190 s |

Knowledge (`kb/jianying/`): 4,541 catalogue items with English descriptions, 40 parameters, 70 API functions, and
`availability.json`. That file is learned from real exports: proven, downloaded, missing, needs-login, or invisible.

`kb/capcut/` holds pyCapCut's 4,957 items, all described, for reference:
- 294 are the same resources as JianYing's.
- 1,500 more have a same-name JianYing equivalent.
- 3,163 are CapCut-only. JianYing cannot fetch them (0 of 19 downloaded in a probe, `harness/ccbridge.py`), so they need the CapCut app.

Beyond the catalogue:
- **Sound design** (`harness/sfx.py`): impact, hit, whoosh, swoosh, riser, sub-drop, thunder and glitch, synthesised into `media/derived/`. A riser ends on its moment; the others start there.
- **Template mode**: copy an existing JianYing project, replace its media by name, rewrite its texts, and add edits on top.
- **Clip and text options**: stretch (x≠y), pitch-with-speed, blur strength, vertical text, line width, and text-background size and offset.
- **Revisions** (`studio.py revise`): the model sees the edit as an absolute timeline, so "when his eyes light up" lands on the right second.

Measured runs:

| Run | Time | Edit points |
|---|---|---|
| Revision | 49–66 s | changed points only, all passing |
| Calm 12-s "Golden Hour" reel | 59 s | 13 of 14 passing |

### Editor's Mind: think before rendering, reflect after

1. **Awareness** (`harness/awareness.py`, ~20 ms) works out what is possible for this request, right now:
   - each need is direct, approximate, built-in, or not possible (with what to do instead);
   - how reliable each catalogue item is here;
   - where the usable faces are, whether there is music or speech, and the hard limits.
2. **Treatment.** The plan opens with a `think` section: concept, hook, arc, climax, pacing, look, sound, and a requirement map (each ask → technique → edit ids → confidence → fallback).
3. **Critic** (`harness/critic.py`, ~1.5–3 s) runs before any render:
   - ~15 rule checks, plus one fast model review of the absolute timeline;
   - its patch operations are applied only if the checks don't get worse;
   - a render costs ~30 s, so catching a mistake here is ~10× cheaper.
4. **Render, verify, repair**, as described above.
5. **Report** (`harness/report.py` → `out/video/reports/<draft>.md`):
   - asked vs delivered, with the verifier's evidence;
   - what was substituted and why, quality, remaining flags;
   - the best next improvements.
6. **Lessons** (`harness/lessons.py` → `kb/jianying/lessons.json`): repairs and the user's follow-ups become rules that the planner and critic read on the next run.

Exports run **off-screen**: JianYing's windows are parked beyond your monitors and put back afterwards, and JianYing pre-starts while the plan is written.

### Editing like a pro: design → rhythm → recipes

The planner no longer hand-writes every edit. It **designs**:
- a style: hype/velocity, cinematic, montage, talking-head, meme or product;
- music: a given file, or a generated bed (hype, phonk, epic, pop, chill or cinematic, built with intro, build, drop and outro);
- a shot list in beats (normal / slow / fast / velocity / freeze);
- recipes, plus a few hand-placed extras (e.g. the eye effect on the close-up).

Code then writes the dense, frame-accurate timeline:

| Module | Job |
|---|---|
| `music.py` | music beds in 1–1.5 s, with an exact beat grid |
| `cutting.py` | every shot a whole number of beats; best moments by highlight, face and motion; no repeats; velocity ramps (1.8×→0.35×→1.8×) on the key moment; long shots split to the style's pacing |
| `recipes.py` | zoom punches, shakes, flashes, RGB hits, transitions, Ken Burns, grade (+ grain, vignette, letterbox, light leaks), hook, kinetic titles, captions, sound design, jump-cut zooms, meme face punches |
| `styles.py` | pacing, default recipes, transitions, type, look and music per style |
| `speech.py` | local Whisper (`models/whisper/base`, ~2 s per 12 s of speech); see below |

Talking-head edits built on `speech.py`:
- jump cuts that drop pauses and filler words;
- 1–3-word captions that never cross a cut, with key-word lines in the accent colour;
- punch-ins and pops on key words;
- b-roll when a word is spoken;
- music ducked under the voice.

Measured, live:

| Request | Points checked | Pass | Time | AI cost |
|---|---|---|---|---|
| "Lightning on my eye, boss entrance" (hype) | 55 | 52 (0 fail) | — | — |
| "Phonk velocity edit, zooms on beats, flashes on the drop, NO DAYS OFF slamming, freeze ending" | 46 | 46 | 61 s | $0.009 |
| "YouTube Short: cut pauses, word captions, zoom key words, b-roll on 'evening', quiet music" | — | — | — | — |

The YouTube Short request went through: 28 words, 1.8 s of pauses removed, b-roll and captions verified.

Measured on the lightning/boss request: 24 of 24 edit points pass after one critic patch. All 6 asks are reported "met", with evidence. One plan + critic + export + verify pass is ~100 s and $0.008; a re-render pass is ~45 s and $0.0007.

Facts found by checking exports (all handled in code):
- JianYing places keyframes at **file time**: source start + seconds × speed.
- Scale is capped at **500%**.
- Some free catalogue items never download, need an account, or never render here.
- The export dialog's drop-downs need the real mouse, so the remembered settings are used.
- UI Automation calls from two threads of one process deadlock.

Offline check: `python tests\test_video_offline.py` (46 checks).

### Understanding the request: edit types, sample styles, questions

```
studio.py ask "what eye filters are available?"            # catalogue questions, answered in ~1 ms
studio.py ask "can you add lightning to my eyes?"           # what is possible, and the closest working stand-in
studio.py chat "what kind of video should these become?" --media media\clips\*.mp4
studio.py new "a 30 s travel reel like this one" --media media\trip\*.mp4 --like media\sample.mp4
```

| Module | Job |
|---|---|
| `router.py` | the front door: catalogue question, capability, "what kind of video", sample style, new edit, revision, help; rules first, the model only when unclear |
| `catalog_qa.py` | catalogue answers grouped by ready here / free but untried / VIP (free in CapCut?) / not working here. It maps loose words to the right kind: eye "filters" are face effects; "calm wedding" means dissolves and soft fades. Recommendations come only from items that work here. |
| `taxonomy.py` | 27 edit types (travel reel, gym motivation, wedding film, recipe, podcast clip, product ad, documentary…), each with its grammar: structure, pacing, look, type, sound, what to avoid. Classified from the request, the footage, speech or narration, the brief's own vote and a sample's rhythm. |
| `reference.py` | measures a sample edit and makes the new edit match it. It reads shot changes (including ones hidden under flashes, glitches or dissolves), shot lengths, cuts on the beat, tempo, zoom punches, shakes, flashes, dissolves, brightness, contrast, saturation, warmth, letterbox and grain; one vision call reads the typography. |

When a sample is given:
- It decides the style: rhythm, grade, music tempo and effects.
- The edit type decides the structure and content (labels, story).
- Exposure is matched shot by shot with a dimming layer. JianYing ignores brightness keyframes written without its adjust material.

Measured on the travel footage cut "like" the gym video:

| | Cuts/min | Brightness | Tempo |
|---|---|---|---|
| Gym sample | 48 | 0.279 | 140 BPM |
| Travel matched to the sample | 55 | 0.278 | 140 BPM |
| Travel in its own style | 35 | 0.496 | 118 BPM |

Edit-type accuracy:
- 10 of 10 genre requests;
- 8 of 10 from footage alone, and the 2 others are fair readings (landscape stock read as nature; a narration track read as documentary).

### Conversations: editing over many turns

```
studio.py talk agent_road_195510           # an interactive chat about an edit; "export" renders the version you are on
studio.py chat "make the title red and the music a bit quieter"   # one message to the chat about the last edit
```

A message is split into its asks; each one is a question about the edit, a question about what is possible, a change,
a version command, or an answer to an option the editor offered. All changes in one message become one new version.
Every version is also a JianYing draft (`agent_<word><time>_v<n>`).

| Module | Job |
|---|---|
| `conversation.py` | versions and undo/redo/"go back to v2"/"start over"; one element back from an earlier version ("the old music was better", "the previous title FONT was nicer" keeps the new words); options to pick from ("try the second one", "1 and 3"); half-answered asks ("slow motion please" → "which moment?" → "the wheel"); vague asks get concrete directions; impossible asks get the closest alternative; the cheap model handles what the rules do not, answering in the same operations, which are then checked like any other |
| `quick_edits.py` | plain words to operations, with no model call. It handles typos, chat shorthand and Roman Urdu ("title ko bara karo aur laal"); several asks in one sentence; "it", "them" and "those" referring to the last thing discussed; texts named by their words ("the price text", "SATURDAY NIGHT"); shots by what they show ("the sunset shot", "when it accelerates"); and, after a re-cut, earlier changes applied again |
| `explain.py` | answers about the current edit from its own record: fonts, music and BPM, transitions, effects, the look, "what's at 0:12?", "why the shake?", how long, how many shots or flashes, the narration |

How changes are made:
- Structural changes go into the design, and the cut engine re-cuts on the beat. Structural means length, pacing, shot order, music, format, slow motion and footage choices.
- A re-cut keeps the effects, filters, transitions and fonts the edit already uses.
- Text, colour and effect changes go into the plan as a list of overrides. The list is applied again after any re-cut, so "title red" survives a later "make it 30 s".
- Each change is checked on the new timeline before the reply. The reply says what was done, what wasn't, and why.

Measured (2026-10-03): 287 conversation turns over the 10 batch edits, about 0.5–1.2 s per turn, $0.0016 per 50 turns.
- `tests/conversations.py`: 117 turns, the set the rules were tuned on.
- `tests/conversations_holdout*.py`: 4 further sets, each written after a round of fixes and first run untouched:

| Set | First run, unseen | After fixes |
|---|---|---|
| holdout (50 turns) | 66% | 100% |
| holdout2 (50 turns) | 84% | 100% |
| holdout3 (40 turns) | 75% | 100% |
| holdout4 (30 turns) | 83% | 100% |

The first-run column is the honest estimate for new phrasing: about 75–85% of turns fully right. Each turn checks:
- the kind of turn taken;
- the change on the new timeline, or the answer;
- invariants: the music never disappears unless asked, no missing items or broken shot references appear, and a question never changes the edit.

### Templates: a finished edit's exact timing on new footage

```
studio.py template learn media/glowup.mp4 --name glowup     # learn once: a CapCut template preview, a trending edit, one of ours
studio.py template list | show glowup
studio.py new "my trip in this template, title 'BALI 2026'" --media media\trip\*.mp4 --template glowup
studio.py talk <the new draft>                               # follow-ups: footage, music, texts, format (the timing stays the template's)
```

[template.py](harness/template.py) has three steps.

**Learn.** It reads the video frame by frame:
- cuts, typed as hard cut, cut under a flash, dissolve, or motion transition;
- flashes, zoom punches and shakes;
- each slot's shot size (faces), motion, colour, and whether it is black and white;
- the tempo and the drop;
- with the model, one look per 20 slots for each slot's on-screen text and what it shows.

How cuts are found:
- Candidates come from colour, structure and pixel change, plus a 0.4 s and a 1 s comparison for transitions.
- Each candidate is verified with ORB feature matching on frames just outside the change. A zoom, shake, glitch, light leak or strobe leaves the same scene on both sides, so it is not a cut.
- Two "cuts" with no steady picture between them are the two ends of one transition.

Templates are saved in `state/templates/`.

**Fill.** Each slot gets the best unused moment of your footage:
- matched on shot size, motion, highlight and what it shows;
- hero slots (the drop, the longest late slot, the opening) are filled first;
- no moment is used twice, and the same file rarely appears twice in a row.

On top of that, the template is rebuilt from items that work here: its transitions, flashes, zooms, shakes, black-and-white slots, grade, grain or letterbox, and texts. Your words in quotes replace the template's. The music is generated at the template's tempo, its drop is placed where the template's is, and its beats are shifted onto the template's cuts. The template's own song is licensed inside CapCut, so it is never reused.

**Check.** The usual edit-point checks and fix rounds run. In a template edit the fixer never changes the template's transition lengths. Then the exported video's cuts are detected again and compared with the plan's.

Measured (2026-10-03):

| Test | Result |
|---|---|
| Cut detection on 10 edits with known timelines (`tests/template_cuts_eval.py`) | 87% of cuts found, 75% precision, F1 80%. Without the strobe-lit party edit: 92% found, 82% precision |
| Fill (`tests/test_templates.py`, offline) | every cut on the template's frame (0 ms drift); same length; no moment reused; follow-ups pin or avoid footage and refuse timing changes |
| Live run: gym edit as template, travel footage | 53 slots, exported in 177 s with 2 fix rounds. Checks: 29 pass, 6 warn, 1 fail. Re-detected cuts: 45 of 52 on the template's frames (86%; all 52 are exact in the project, the scan misses look-alike shots). AI: $0.0002, plus $0.004 to learn the template once |
| Chat about a template edit (`tests/conversations_template.py`) | 9/9 |

### Template explorer: a CapCut link, a screenshot or words

```
studio.py template add "https://www.capcut.com/template-detail/7644532345902533908"   # a link you paste (tracking parameters are dropped)
studio.py template add media/page.png                                                # a screenshot of a template's page
studio.py template add "SLOWMO HDR, 4 clips, 15s, #slowmo #eid"                      # or the words
studio.py template add <link> --video media/preview.mp4                              # plus a video of it: its exact cut frames
studio.py template suggest "slow motion eid video, 4 clips" --media media\eid\*.mp4  # the library, best fit first
studio.py new "my eid video, add the greeting" --media media\eid\*.mp4 --template <link | name | screenshot | words>
```

What a template's page gives ([template_meta.py](harness/template_meta.py)): the title, author, number of clips, length, format, uses, likes and hashtags. What the title and hashtags ask for ([trends.py](harness/trends.py)) becomes settings the filler applies:
- `#slowmo` gives every slot slow motion (0.45x), with moments full of movement picked for it;
- `velocity` gives fast-slow-fast speed ramps, and `3D zoom` slow push-ins;
- `HDR` gives a high-clarity look (the title's look leads; a hashtag's look is used only when the title has none);
- `glowup` gives black and white until the drop, and `#eid` the greeting "Eid Mubarak", offered and added only when asked;
- about 30 such trends in all. Tags like `#fyp` and `#foryou` are ignored.

A tag the dictionary does not know is mapped once by the cheap model. Only known settings, in range, are kept, and the result is remembered in `state/trends.json`. For example, `#bxl` is the creator's handle, so it maps to nothing.

Without a video of the template, the slots are even and on the beat, so the result is not exact (marked "from its page"). With a video, the page's clip count makes the learned slots exactly that many: the least sure extra cuts are left out, missed cuts between look-alike shots are taken back, and a cut the preview does not show is put on a beat and marked "guessed".

**Staying within CapCut's rules** (robots.txt and llms.txt, checked 2026-10-03):
- only a page you point at is read, never listings like /templates/ or /explore/;
- the link is cleaned to `/template-detail/<id>` (CapCut asks agents not to fetch links with tracking parameters) and checked against robots.txt;
- the page is fetched once and cached for a day;
- there is no login, and no template media or song is downloaded.

In a chat:
- "any template for eid with 4 clips?" lists the library's best fits as options;
- "use the 1st", "use the slowmo hdr template" or a pasted link recuts the edit on that template. The footage, avoided files and main title stay; "... and make the title gold" is applied in the same version;
- "no slow motion", "more slow motion" and "speed ramps" change every slot's speed and keep the timing;
- "add the greeting" adds the occasion's greeting;
- "is this good for my clips? <link>" describes the template and offers the recut.

Measured (2026-10-03):

| Test | Result |
|---|---|
| Explorer (`tests/test_template_explorer.py`) | all pass: link cleaning and refusals, robots.txt, the page's own record (not a related template's), techniques, a 4-slot slow-motion template from the page (no moment reused at 0.45x), greeting only when asked, normal speed and ramps on request, the clip-count constraint, suggestions, and a screenshot read by the vision model ($0.0003) |
| Clip count known (`tests/template_cuts_eval.py --count`) | cut detection precision 74.5% → 83.0%, F1 80.1% → 83.0% |
| Chat (`tests/conversations_explorer.py`) | 15/15; all 296 earlier chat turns still pass |
| Live: `new --template <SLOWMO HDR link>` with 7 wedding clips | 4 slots at 0.45x, HDR filter, Eid Mubarak, 100 BPM bed; 14.61 s for 14.58 s; 3/3 cuts on the planned frames; checks 12 pass, 1 warn (a face near the edge), 0 fail; all 5 asks met; 31 s with JianYing warm (72 s cold); AI $0.0002 |

The verifier now checks speed too. Inside a slowed slot, the render must show the take's moment at the planned speed (2 s into a 0.45x slot is 0.9 s into the take), not the 1x moment. On the live export the render matched the 0.45x moment at a correlation of about 0.98, against 0.0–0.74 for the 1x moment. A 1x export whose map claims 0.45x fails this check.

## Office documents: Word, PowerPoint, Excel (programmatic)

The CapCut recipe applied to Office. Code writes the `.docx`, `.pptx` and `.xlsx` files itself (python-docx, python-pptx, openpyxl). The real Office app only renders them, hidden in the background, the way JianYing only exported videos. Every element is then checked on what the app produced.

```
docs.py new "a 5 page report on rooftop solar for homes in Lahore with a cost table and a chart, for Green Future Consulting"
docs.py new "Assignment: 4 pages on the causes of inflation in Pakistan, ECON-201, submitted to Dr. Sana Malik, by Ahmed Raza"
docs.py new "leave application to my principal for 3 days, fever, Fatima Noor class 9-B"
docs.py new "invoice for Ali Traders: logo design 1 x Rs 25,000, 10 posts at Rs 2,500, add 18% sales tax"
docs.py new "a 10 slide presentation for homeowners on going solar"            (PowerPoint)
docs.py new "marks sheet in Excel for 8 students with totals, grades and a class summary"   (Excel)
docs.py new "..." --files media\docs\data.xlsx notes.txt   --theme academic   --pages 6
docs.py check some.docx                                                        (render and check any Word document)
```

| Step | Video (JianYing) | Documents (Office) |
|---|---|---|
| Write | the director plans the edit | [designer.py](harness/office/designer.py): an outline, then all sections in parallel (Word); one call for a deck or a workbook |
| Build | pyJianYingDraft writes the draft | [docx_build.py](harness/office/docx_build.py), [pptx_build.py](harness/office/pptx_build.py), [xlsx_build.py](harness/office/xlsx_build.py) |
| Render | JianYing exports in the background | [render.py](harness/office/render.py): Word, PowerPoint or Excel by COM in a child process, in a new instance of its own (open documents are never touched; a stuck one is stopped) |
| Check | frames at every edit point | [verify.py](harness/office/verify.py): every element on the rendered pages |
| Fix | fix rounds | length, a heading alone at a page's foot, an almost-empty last page, a table too wide, slide text overflowing |

**What code guarantees (never left to the model):**
- Invoice and table totals are computed by code.
- Spreadsheet formulas are written by code. The model names columns (`[Qty] * [Price]`) and code writes `=B2*C2`, SUMIFS summaries and totals.
- Table and figure numbering, academic heading numbers (1, 1.1), and restarted numbered lists.
- Words per page come from the theme (Times 12 pt at 1.5 lines holds about 270, Calibri 11 pt about 420).

**Professional defaults:**
- real Word styles, so the navigation pane and contents page work;
- headings kept with their text;
- table header rows repeated on every page, numbers right-aligned, rows never split;
- native, editable charts in Word as well, by attaching python-pptx's chart XML to the document;
- covers and contents pages for long work, and "Page X of Y" footers;
- letters, applications, CVs, invoices, notices and certificates laid out the way they are expected to look;
- slides drawn on blank 16:9 pages with text sized to fit and message-style titles;
- workbooks with frozen headers, filters, dropdowns, highlights, summaries and charts.

**What is checked:**

| Format | Checks |
|---|---|
| Word | pages against the length asked (the cover and contents page are not counted); page size; blank pages; every glyph in the theme's fonts, read per character from the PDF; no field errors; contents page numbers equal the headings' real pages; no heading alone at a page's foot; tables inside the margins with the header repeated; charts drawn; every paragraph present; the client's figures on the pages |
| PowerPoint | PowerPoint's own measurement of every text box after layout (overflow); every title and bullet on its slide; charts drawn; fonts |
| Excel | Excel recalculates the workbook; no error cells; every total, metric and group Excel computes equals the same number computed in Python; charts present |
| All | one cheap vision look at the pages or slides, on a time budget, so a slow model never holds up a run |

Measured (2026-10-03, GLM-5.3-Flash for all model calls):

| Run | Result |
|---|---|
| Offline engine tests (`tests/test_docs.py`, no model) | 23/23: totals, a 70-row table repeating its header, contents page numbers, native charts, list numbering, fonts, academic numbering, one-page fitting, deck rendering and overflow, Excel formulas and values |
| 5-page solar report (cover, contents, table, chart) | 5 body pages for 5 asked; 14/14 checks; the vision look found no problems; about 45 s; $0.009 |
| University assignment, leave application, invoice, CV, notice | 63 s, 12 s, 11 s, 13 s, 16 s; $0.0004–0.005 each. The invoice arithmetic was exact. A CV that spilled onto a second page is now tightened onto one |
| 10-slide deck from one request | 22 s; 11/11 slide checks; $0.0018 |
| Excel sales workbook | 15/15 values Excel computed equal Python's; no error cells; 2 charts |

The renders take 6–8 s each, mostly Word or PowerPoint starting. Writing takes 2 s for a letter, about 10 s for a deck and about 20 s for a long report. Model latency spikes happen (one reply took 86 s on 2026-10-03), so the vision look runs on a time budget.

### Editing existing files by conversation

```
docs.py talk report.docx                                   (interactive)
docs.py talk deck.pptx -m "delete slide 4, move slide 9 to the start and make the titles dark blue"
docs.py talk sales.xlsx -m "clean up the data" -m "add a column Amount = Qty x Unit Price and a total row" -m "which customer bought the most?" -m export
docs.py talk --chat book_sales_163841                      (continue a saved chat)
```

Each message makes one version; v0 is a copy of the client's file, which is never changed. Undo, redo, "go back to v2", "compare v0 with the current version", "what did you change?" and "export" (the file plus a PDF) work the same way in all three.

| Step | Word | PowerPoint | Excel |
|---|---|---|---|
| Read the file | [docmap.py](harness/office/docmap.py): sections, headings (also bold lines that only look like headings), tables, contents page, header and footer | [pptx_ops.py](harness/office/pptx_ops.py): slides, titles, texts, notes, charts, tables, which slide is the cover | [xlsx_map.py](harness/office/xlsx_map.py): each sheet's table (header row, data rows, totals row, column kinds and formulas), summaries, pivots, charts |
| Understand | [doc_parse.py](harness/office/doc_parse.py): rules first, including some Roman Urdu | [deckchat.py](harness/office/deckchat.py) | [book_parse.py](harness/office/book_parse.py): rules first; data questions become queries that code computes |
| The model | only for what the rules cannot read; it returns the same operations, which are validated against the file | same | same; for a question it may only return a query, never do the arithmetic |
| Edit | python-docx in place (parts it does not know are kept) | python-pptx in place (masters, layouts and animations are kept) | [xlsx_com.py](harness/office/xlsx_com.py): Excel itself, in the background worker. Charts, pivots, validation and highlights are kept, and references follow moved rows and columns |
| Check | each edit on the document before and after; Word renders it; fonts drawn, contents page filled, page numbers on the pages | PowerPoint measures the changed slides. Text too big for its box is shrunk by that measure and measured again, up to three rounds; a number goes onto one line and is sized by its width rather than breaking. Text contrast is checked against what is behind it | each result against Python: a new column's values, a sort's order, the rows a filter shows, the cells Excel paints (DisplayFormat), totals, summary and pivot groups; no new error cells |

**Edits it understands (examples):**
- **Word (29 operations):** styles and themes; page setup and page numbers; header and footer; contents page and cover; heading numbers; lists; find and replace across formatted runs; bolding the key terms; deleting or moving sections; inserting sections the model writes in the document's own style; rewriting, shortening or translating (Urdu is set right to left); summaries; table sort, rows, columns, formulas and totals; native charts; images.
- **PowerPoint (15):** slides:
  - delete, move, swap or duplicate a slide;
  - add a slide about a topic (the model writes it; it is drawn in the deck's own look).

  Text:
  - set titles;
  - replace words across slides, tables and notes;
  - rewrite, shorten or translate;
  - write speaker notes, also "only for the slides that have none";
  - add or delete bullets.

  Look:
  - styles for titles, body text or table text;
  - backgrounds (text that would no longer read is recoloured; cards and charts follow);
  - shrink text to fit, by PowerPoint's own measurement.
- **Excel (32):** clean-up:
  - "clean up the data" in one request: dates typed as text in any style, prices written as "Rs 42,000", one city spelled four ways, extra spaces, empty rows, repeated rows.

  Formula columns from words:
  - "Qty times Unit Price", "17% of Amount", "Big if Amount is above 5 lakh else Small", "average of Maths, English, Science and Urdu";
  - running totals, ranks, share of the total;
  - lookups from another sheet (INDEX/MATCH).

  Sorting, filtering and highlights:
  - sort and filter;
  - highlights by value, top N, duplicates, whole rows, or any condition ("overdue and unpaid");
  - data bars and colour scales.

  Summaries and charts:
  - totals rows;
  - live summary sheets (SUMIFS; by month, quarter or year);
  - real pivot tables;
  - charts in the workbook's own colours (a chart of a column whose values repeat totals it first).

  Structure and formats:
  - number formats (Rs, %, dates);
  - freeze panes, dropdowns, hiding, renaming, moving and splitting columns;
  - sheets.

**Guard rails:**
- Excel will not delete a column or sheet that other formulas use. It names those cells, and deletes only on "… anyway", keeping those cells as their current values.
- Slide numbers in one message mean the deck as the client saw it, even after earlier deletions and moves in the same message.
- A colour request that makes text unreadable is done but flagged ("hard to read: … on slide 7").
- New decks are drawn readable too: a theme colour on a card, a step circle or a section panel is darkened just enough to reach 3:1 contrast, keeping its hue. The deck check now flags any text under 3:1.
- A sheet that an edit made wider than a page is set to print landscape, one page wide.
- "Which customer bought the most?" on a sheet with quantities and unit prices but no amount column is answered from Qty × Unit Price, never from a sum of prices.

Measured (2026-10-03, GLM-5.3-Flash):

| Suite | Turns OK | Requests the model had to read | Time per turn | Model cost |
|---|---|---|---|---|
| Word chats ([tests/doc_conversations.py](tests/doc_conversations.py): a report, an assignment, a hand-typed messy essay) | 38/38 | 1 | 2.5 s | $0.0023 |
| PowerPoint chats ([tests/deck_conversations.py](tests/deck_conversations.py): the agent's deck, a client deck in PowerPoint's default template) | 36/36 | 1 | 2.1 s | $0.0009 |
| Excel chats ([tests/book_conversations.py](tests/book_conversations.py): a messy client sales workbook, the class marks workbook) | 33/33 | 2 | 1.3 s | $0.0006 |
| Excel operations alone on the messy workbook (one Excel job each) | 30/30, every result equal to Python's | none | 0.5–3.6 s | none |

### Projects: several files together, data flowing between them

```
docs.py project sales.xlsx -m "clean up the data and add a column Amount = Qty x Unit Price with a total row"
   -m "write a two page report on Q1 sales for the management team from the workbook"
   -m "put the amount by city into the report after the introduction, with a pie chart of it"
   -m "make a 5 slide deck from the report for the board"
   -m "in the workbook, delete the cancelled orders"          (the reply names the copies now out of date)
   -m "refresh everything"
   -m "export the report and the deck as one pdf with a cover called Q1 Sales Pack, page numbers and a DRAFT watermark"
docs.py project --load proj_q1sales_172815                   (continue a saved project)
```

[projectchat.py](harness/office/projectchat.py) keeps a chat per file and adds what spans files:

| Piece | What it does |
|---|---|
| Routing | Each part of a message goes to the file it is about. A file can be named ("in the workbook", "the deck's titles") or recognised by its own words: sheets, columns and the data's values; section titles; slide titles. Otherwise it goes to the file last talked about. "in the workbook," on its own steers the requests after it. |
| Data links | Excel hands over a table or a pivot exactly as it shows it. Pivots are refreshed first, and narrow columns widened so no "####" is read. It goes into Word as a native table or chart, or into PowerPoint as a native chart or table slide, with an invisible link back: a Word bookmark or a PowerPoint shape tag. If no sheet holds the figures asked for ("amount by city and month"), a pivot is made in the workbook first. |
| Out of date | After a workbook edit that changes the data, the reply names each copy that is now out of date. It also names each figure a report or deck quotes in its text ("the text says 5,634,700 for total Amount, now 5,142,700"); a report keeps the list of figures it was written from, and a deck made from it inherits that list. "refresh" writes the tables and charts again in place and replaces the old figures in the text. Caption, numbering and chart type are kept; a slide table with a different number of rows is redrawn with its title and notes. Each cell is checked against Excel. |
| Made from other files | A report written from the workbook's figures: computed by code and quoted exactly, with no model arithmetic. A deck made from a report: its charts are drawn again from the workbook, not retyped. A handout: PowerPoint draws each slide, with its speaker notes under it. |
| PDFs | A pack with a cover (drawn by Word), bookmarks and a watermark (a transparent layer drawn by PowerPoint). "Page i of N" goes where each page has room, never over the page's own footer or slide number. Also compress, split by bookmarks, and select, delete or rotate pages. Every result is checked on the PDF; the watermark is checked by rendering the pages. |
| History | One history for the whole project: undo, redo and "go back to v2" move every file together. Files made later are set aside, not deleted. |

Measured (2026-10-03, GLM-5.3-Flash):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_links.py](tests/test_links.py): the Excel grab, linked Word tables and charts, PowerPoint data slides and copies, PDF pack, compress, split and pages (no model) | 24/24 | about a minute | none |
| [tests/project_conversations.py](tests/project_conversations.py): a messy workbook, then a report, a deck, links, a change, a refresh, a PDF pack and a handout, with undo and go back (19 turns) | 19/19 | 100 s in all; about 30 s each to write the report and the deck | $0.005 |

Problems these tests found and fixed along the way (all would have hit real clients):
- After a slide was deleted, python-pptx gave a new slide the name of a slide still there. The two parts with one name made files PowerPoint could not open.
- Inserted sections were tracked by recycled object ids, which could leave them at the end of the document.
- Excel reports "####" as the text of a number whose column is too narrow.
- A duplicated chart slide lost its colours and labels.
- Word moves the body font into the document defaults when it refreshes a contents page.

## Windows itself: files, folders and settings (programmatic)

```
win.py                                     a conversation about your own Downloads, Documents, Desktop, Pictures, Videos, Music, OneDrive
win.py --look                              looking only: answers and plans, nothing changes (a safe first run)
win.py -m "clean up my downloads" -m yes -m "find my CV and move it to documents" -m "make the second one my wallpaper" -m undo
win.py --resume                            the last chat again, its undo history too
win.py --sandbox                           made-up folders inside the project and a test branch of the registry
```

Everything is done by code: Python for files, the Windows shell's own Recycle Bin, the registry and system calls for
settings, Office in the background for Word-to-PDF. No window opens and nothing moves the mouse. Every step is checked on
the disk afterwards and journaled, so "undo" puts it back exactly.

| Area | What it does |
|---|---|
| Questions | What a folder holds, by kind and size; what takes space, across all folders; disk space; find by name words, kind, size or date. "photos from August" uses the date each photo was *taken*: the EXIF date, else the date in its name (WhatsApp strips EXIF but names files by date). A month with no year that finds nothing is looked for in earlier years, and the reply says so. |
| Tidying | Clean-up removes unfinished downloads, installers older than a month, "x (1).pdf" copies and empty folders. A download changed in the last two hours is left alone (it may still be downloading), and so are installers from the last month. Only the folder's own loose files count: an unzipped app's .exe is the app, and an asset pack repeats files on purpose. Organize sorts into Photos, PDFs, Installers... (Pictures and Videos by month). Duplicates are found by size, then the first 64 KB, then SHA-1; the original stays. |
| Doing | Move, copy (checked byte for byte, room on the drive checked first), rename (pattern, date taken, replace, case), zip and unzip (a zip that would write outside its folder is refused), resize and convert pictures (EXIF kept), merge PDFs (a bookmark each), Word / PowerPoint / Excel to PDF, the sound out of a video. Folders too: "move the Taxes folder to documents". |
| Talking | "it" must be one file (else "Which one? 1. ... 2. ..."), "them" is the list, "the second one" is one of it. "find my CV and move it to documents" is two steps. A folder named that does not exist is said back, never guessed; if it is in the Recycle Bin, the reply says so. When one part of a message is not understood, the parts after it wait. |
| The Recycle Bin | Removing always goes to the Recycle Bin. "what's in the recycle bin?" lists what came from your folders; "restore the first one" or "restore notes.txt" brings it back. Restores go through one shell operation (0.1 s an item, where the shell's restore verb takes 0.9 s), never over a file that is there now. It is never emptied. |
| Settings | Dark or light mode, transparency, file extensions, hidden files, taskbar alignment, wallpaper, power plan, default printer. Start-up apps are turned off the way Task Manager does it, and shown by plain names ("Microsoft Edge", not "MicrosoftEdgeAutoLaunch_7570..."). Each setting is read back after it is set. |
| Safety | Windows, Program Files, ProgramData, AppData and this project are never touched, nor the Downloads / Documents ... folders themselves. Removing more than one item, or moving more than 15, waits for "yes". Nothing is deleted for good. Undo, redo and the history cover files and settings alike. |

Measured (2026-10-03; the conversation's two hardest phrasings go to GLM-5.3-Flash, everything else is read by rules):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_win.py](tests/test_win.py): the guard, scanning, dates, duplicates, plans, the Recycle Bin round trip, zip safety, pictures, PDFs, sound, Word to PDF, settings, 42 phrasings | 38/38 | 9 s | none |
| [tests/win_conversations.py](tests/win_conversations.py): a 37-turn conversation, each turn checked on the disk; the Recycle Bin left clean | 37/37 | 63 s in all (35 turns by rules in 7 s; 2 by the model, ~20 s each) | $0.0007 |

A looking-only run on a real Downloads folder (899 files, 4.8 GB) found what the made-up folders could not. Clean-up had
treated identical files inside two unzipped asset packs as copies, and would have counted any old .exe as an installer.
It now keeps to the folder's own loose files: 11 items, 427 MB. The 125 identical files inside sub-folders are left
alone, and the reply says so.

## Photos (programmatic)

```
photo.py talk car.jpg -m "it's too dark, fix it" -m "crop to the car" -m "add 'FOR SALE' at the top in red" -m "make the text bigger"
   -m "watermark '© Fareed Motors'" -m "compare with the original" -m "save it for instagram under 300 kb"
photo.py talk presenter.png -m "remove the background" -m "make a passport photo for the US" -m "print 6 of them on a 4x6 sheet"
photo.py talk party.jpg -m "blur all the faces" -m "crop it to 4:5" -m "pixelate the faces instead"    (the crop is redone after the swap)
photo.py batch "C:\Users\me\Pictures\Trip" -m "fix it" -m "watermark '© Me'" --save "for instagram under 500 kb"
photo.py look car.jpg                       what it is like, and where, when and with what it was taken
```

Pillow, numpy and OpenCV do the edits (no new download: faces come from the YuNet model already in `models/`, which is
checked by SHA-256). Windows Photos, or any viewer, only shows the result. The original is never changed: each message
makes a version in the chat's folder, and saved copies go to its `exports`.

| Area | What it does |
|---|---|
| Measuring | Exposure, contrast, colour cast, saturation, noise, sharpness (of the strongest edges, so a sky does not make a photo "blurry"), faces, a green or blue screen or plain backdrop, the main subject, the lean of a horizon, a page's corners, and where it is quiet enough for text. |
| Fix it | Auto-enhance decides from those measures and says why: colour cast, tonal range, exposure (a night scene is lifted, not turned into day, unless the person says it is too dark), flatness, dull colour, grain and softness. Contrast lost by brightening is given back by deepening the darks, which blows no highlights. A green-screen shot is left for keying. |
| Edits | Brightness by a tone curve, contrast, colour, vibrance, warmth, shadows, highlights, white balance, clarity. Looks: B&W, sepia, vintage, cinematic, dramatic, film noir, sketch, cartoon, painting and more. |
| Shape | Crop to a shape with the face kept near the top third. "Crop to the car" snaps to the nearest pleasing shape around the subject. Fit a story without cropping (the sides filled with a blurred copy, or kept transparent for a cut-out). Straighten from the horizon. Rotate, resize, border, polaroid, vignette. |
| People | Blur or pixelate every face. Portrait-mode background blur, background removal, and a new background (a colour or another photo): green and blue screens are keyed with the spill taken off, plain backdrops are cut, anything else goes through GrabCut from the faces. Also skin smoothing and lifting dark faces. |
| Words | Text placed in the calmest band and never over a face, white or near-black by what is behind it, outlined when a colour asked for would not read. Short words come out big. Memes, banners, and watermarks (a corner, or tiled across). |
| Documents and IDs | A photographed page is found, flattened, its shading divided out and the paper made white, then saved as a PDF. Passport photos: the head sized to each standard (35x45 mm, US 2x2, UK, UAE, Saudi, Canada, China) at 300 dpi on a plain background, and copies on a 4x6, 5x7 or A4 print. The reply says when fewer copies fit than were asked for. |
| Conversation | "it" is the photo. "move the text to the bottom", "make the text yellow and bigger" and "change the text to ..." change words already written. "sepia instead" and "pixelate the faces instead" swap the earlier edit of that kind and redo everything after it, because each version keeps its edits and can replay them. A crop or turn made after a border goes in before the border, so the frame stays on the outside. Also undo, redo, "go back to v2", "compare with the original" (side by side, with the numbers that changed), and "add beach.jpg" for collages and new backgrounds. |
| Saving | JPG, PNG, WebP or PDF. Social and print sizes: Instagram post, portrait and story, YouTube thumbnail, Facebook, LinkedIn, X, WhatsApp, 4x6, A4. "Under 300 KB" searches for the best quality that fits, then shrinks if it must. The GPS location is taken out of every saved copy unless asked otherwise ("where was this taken?" shows it). Each saved file is opened again and checked. |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_photo.py](tests/test_photo.py): measures; 49 edits on real and made-up photos (a leaning horizon, a photographed page, a date stamp, grain), each passing its own check; saving with size limits and location removed; 52 phrasings | all pass | 38 s | none |
| [tests/photo_conversations.py](tests/photo_conversations.py): 8 conversations, 38 turns, each checked on the image it made | 38/38 | 32 s in all (36 turns by rules in 25 s; 2 by GLM-5.3-Flash, ~2 s each) | $0.0002 |
| `photo.py batch ... -m "fix it"` on 12 varied photos (dark garage, concert, gym, DJ booth, sunset, sports, landscape) | 12/12 pass every check | 22 s | none |

The checks caught real faults while it was being built:
- Auto-enhance on a green-screen frame darkened the subject's face.
- Brightening a concert photo flattened it. The first fix for that then blew out the stage lights.
- Text written on a transparent cut-out was invisible.
- A story-sized cut-out had its sides filled with blurred green.
- Passport crops above the frame came out black.
- Straightening turned the photo the wrong way.

## House plans and engineering parts (CAD, programmatic)

```
cad.py talk -m "a 5 marla house with 3 bedrooms" -m "make it double story" -m "make the lounge bigger" -m "call it Ahmed House"
   -m "export the pdf" -m "give me the dwg"
cad.py talk -m "make a 10 marla house plan with 4 bedrooms and a dining room" -m "make bedroom 2 11 x 14" -m "straight stairs" -m "on A2"
cad.py draw "a 200 x 100 x 10 plate with 4 holes of 12 mm 20 mm from the corners and a 30 mm hole in the centre"
cad.py talk -m "a flange OD 150 ID 60, 4 holes of 14 on a 110 PCD, 12 thick" -m "8 holes" -m "give me the laser cut file"
```

Code writes AutoCAD DXF files with ezdxf 1.4.4. ezdxf is pure Python; its wheels were checked by SHA-256 against PyPI
and scanned before install. Headless Chrome prints each sheet to PDF at its true paper size and scale, plus a PNG
preview. Chrome runs with its own profile inside the project. AutoCAD is not needed: the DXF opens in AutoCAD,
BricsCAD, DraftSight and LibreCAD. A DWG would need the separate ODA converter, which is not installed. The chat says
so and gives the DXF instead.

| Area | What it does |
|---|---|
| Plots and conventions | Marla (225 sq ft) and kanal plots: 3 marla 20x34 up to 2 kanal 75x120, or any "30 x 60" or "40 feet wide and 80 feet deep". Pakistani conventions: road at the bottom, car porch open to the road with a gate, drawing room at the front, TV lounge, kitchen and stairs in the middle, bedrooms with attached baths at the back. Walls are 9" outer and 4.5" inner. Setbacks follow the plot size. |
| Planning (searched, not templated) | Bands from front to back: front, one or two middle rows, an optional passage, and the back. Stairs, store, powder room, dining, servant and guest rooms may change band. A store or powder room stacks behind its partner. Each candidate is scored on sizes, proportions, the doors that rooms need, and daylight. It is also walked through its actual doors from the porch or the road; a room nobody can reach costs heavily. Baths go in the bedroom's outside corner with a vent. Rooms with no outside wall get a skylight. The first floor sits over the same walls: terrace over the porch, a bedroom over the drawing room, family lounge, kitchenette. |
| When it does not fit | It says what gave way. A store is left out, with a note that the space under the stairs is the usual store. A third bedroom goes to the front or the first floor. On 3 marla the kitchen moves to the back, the porch is dropped and the front door opens from the road. |
| Drawing | Exact wall outlines with every opening cut, and solid fill. Doors are drawn with swings, windows with glass lines, vents and skylights. Furniture is kept clear of door swings and room names. Chain dimensions are in feet and inches. Room names fit or wrap ("DRAWING / ROOM") and slide off door swings. The sheet carries a title block, a room schedule for both floors and a north arrow turned to the road. The sheet is A3 unless that would need a scale smaller than 1:150; then A2 at 1:100. |
| Conversation | "Bigger" and "smaller" search for the largest step (1 ft, then 6") that keeps every door and minimum size, and the least change to the other rooms. If none exists, it says why: "in width, Bed Room 1 would lose its door". The chat refuses any change that would break a working plan or drop a room nobody asked to drop. Answers questions: the covered area, the room list, how big a room is, "can I fit 4 bedrooms?" (trying a first floor too), and "any problems?". Also undo, redo, go back to a version, history, paper, scale (it refuses one the sheet cannot hold), name and client. |
| Parts (mm) | Plates (corner, centre, row and grid holes; radius or chamfer corners) and flanges (OD, bore, bolt circle). Front and side views with hidden and centre lines, hole callouts ("4x Ø12 THRU"), an ISO scale and a title block. A 1:1 cut file holds only the CUT layer for a laser or CNC cutter. Rules checked: edge distance (at least 1x the hole, 1.5x better for steel), hole spacing, bolt holes clear of the bore and rim, corner radius. |
| Checks on every version | Plan rules: everyone can reach every room, no room under its minimum, nothing overlaps or leaves the walls, stairs line up between floors. The DXF is read back: it audits clean, units are inches, walls are closed and filled, room outlines carry the planned areas, each room's name sits inside that room, there is one door swing per door, every window has glass, and each dimension's text equals the distance it measures. The sheet: a one-page PDF of the right paper size, and a preview that is a drawing (not blank). |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_cad.py](tests/test_cad.py): units; 11 briefs from 3 marla to 2 kanal; size limits; 3 sheets read back and printed; 13 deliberately spoiled drawings and plans, each tripping its check; plates, a flange and their cut files; 5 broken part designs; 30 phrasings | all pass | 15 s | none |
| [tests/cad_conversations.py](tests/cad_conversations.py): 5 conversations, 44 turns, each checked on the drawing it made | 44/44 | 50 s (42 turns by rules; 2 by GLM-5.3-Flash) | $0.0003 |

Building it, the checks and visual reviews caught real faults:
- Making the kitchen 2" bigger cost Bedroom 1 its door.
- An impossible bedroom size made the planner silently drop five rooms. The chat now refuses such changes.
- The room name check passed even with a room's label deleted, because the schedule listed the room. The check now looks inside each room.
- The flange "150 od 60 bore" was read as OD 60.
- The two-floor schedule ran into the title block.
- Bold room names overflowed narrow rooms at 1:200.
- A dining table was drawn on top of its label.
- An upstairs room over a servant quarter had no door.

## Sound: voice clean-up, cuts, music and captions (programmatic)

```
sound.py talk interview.wav -m "is it noisy?" -m "clean it up" -m "remove the long pauses" -m "cut the ums and uhs"
   -m "normalize for youtube instead" -m "save as mp3 under 5 MB"
sound.py talk talk.mp4 --with music.mp3 -m "add word by word captions" -m "change 'open router' to 'OpenRouter'"
   -m "add music.mp3 under my voice" -m "make the music quieter" -m "speed it up 1.25x" -m "export the video"
sound.py talk -m "voice-over: Welcome to Khan Electronics. We are open nine to nine." -m "make the voice deeper" -m "save it for whatsapp"
sound.py look voice.wav                      loudness, noise, hum, rumble, clipping, pauses, pitch
sound.py batch "C:\Users\me\Recordings" -m "clean it up" --save mp3
```

FFmpeg 9 (already installed) does every change. faster-whisper (base model, already in `models/whisper`) hears the
words. Windows' own voices read voice-overs. Nothing new was downloaded. The original is never changed: each message
makes a version in the chat's folder.

| Area | What it does |
|---|---|
| Measuring | Loudness and true peak (EBU R128, by FFmpeg). The noise floor and the voice's level (SNR). Mains hum at 50 or 60 Hz (how far the harmonics stand out). Rumble, hiss, harsh "s" sounds, clipping, pauses, the voice's pitch, the format. |
| Clean-up | "Clean it up" picks the steps a recording needs from its measures and says why: cut rumble, notch out the hum, repair clipping, reduce noise, soften the "s" sounds, even out the level, set the loudness. Each step is checked. Noise reduction sets FFmpeg's noise floor just above the measured one. Hum and rumble are taken out first, because people call them noise too. |
| Levels | Platform loudness in two passes, ending within 1 LU of target: YouTube, Spotify, TikTok and Instagram -14; podcasts, Apple and WhatsApp -16; audiobooks -19; broadcast -23. Louder or quieter with a limiter, so nothing clips. |
| Time | Trim, cut ranges ("remove 1:20 to 1:45"), keep a range, fades. Shorten long pauses. Cut "um" and "uh": Whisper is prompted to write them down, then they are cut without touching the next word. Speed up or slow down with the pitch kept, or change the pitch with the length kept. |
| Mixing and effects | Music under the voice: set 18 dB under it, dipping while the voice talks (sidechain), looped to length, faded in and out. "Make the music quieter" redoes only that step. Intros and outros, with a crossfade if asked. Echo, reverb, telephone/radio voice, mono and stereo. |
| Video | A video's sound is edited, and the picture is cut and sped up the same way at export, so removing pauses makes jump cuts. Captions move with every cut. |
| Captions | Whisper's words grouped into readable cues: at most 42 characters a line and two lines, about 17 characters a second, a cue ending at a full stop or a pause. Styles: clean, word by word (the spoken word highlighted, popping in), karaoke and boxed. Colour, size and position can be set, and wrong words corrected ("change X to Y"). Saved as SRT, VTT or ASS, or burned into the video by libass. A transcript can be saved as TXT or a Word document. |
| Conversation | Versions with undo, redo, go back and history. "... instead" swaps the earlier change of that kind and redoes only what came after it, starting from the last version that still holds the unchanged steps. Questions: how loud, is it noisy, how long, what does it say, compare with the original. |
| Checks | Every change is measured again. Noise must drop while the voice keeps its level; hum must be gone; loudness must hit the target; a sped-up voice must keep its pitch. Pauses are measured against the same threshold before and after. Music must sit at least 10 dB under the voice and dip at least 5 dB while it talks. Burned captions must be on the frames while the words are said, absent between lines, with the rest of the picture unchanged. Saved files are read back for length and size. |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_sound.py](tests/test_sound.py): measures on made-up recordings (a Windows voice plus hum, rumble, noise, hiss and clipping); 31 changes each passing its own check; 13 deliberately spoiled results, each tripping its check; captions in 4 styles, files, re-timing after cuts and speed, burning; the video timeline; 43 phrasings | 108/108 | 91 s | none |
| [tests/sound_conversations.py](tests/sound_conversations.py): 4 conversations, 29 turns (a spoiled voice recording, a talking video, a voice-over, requests only the model can read), each checked on what it made | 29/29 | 92 s | $0.0002 |

Building it, the checks caught real faults:
- Noise reduction with noise tracking turned on took out under 1 dB. A fixed floor just above the measured one takes out 16-26 dB.
- "Remove the noise" on a hummy recording failed until hum and rumble were taken out first.
- A music file name was read as a second recording to join.
- "Make the music quieter" also turned the voice down.
- Pause checks drifted, because levelling moves the automatic threshold.
- The burned-caption check misread a moving head as a caption after a speed change. It now compares the nearest of three frames.

## Design: cards, posts, thumbnails, flyers, certificates (programmatic)

```
design.py talk -m "a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567, ahmed@khan.pk, khanelectronics.pk"
   -m "classic style in maroon" -m "make the name bigger" -m "add a QR code" -m "export the pdf for printing"
design.py talk --with car.jpg -m "an instagram post for Khan Motors 'Eid Sale' 20% off 1-15 June, shop now" -m "use car.jpg" -m "make it a story"
design.py talk --with me.png -m "a youtube thumbnail saying I tried every AI tool, with me.png"
design.py talk --with names.xlsx -m "a certificate of participation from Green Valley School for taking part in the Science Fair"
   -m "certificates for the names in names.xlsx" -m "export the pdf"
design.py make "an invitation for the grand opening of Khan Electronics on Friday 9 October at 6 pm at Shop 12, Hall Road, Lahore"
```

The design is written as HTML and CSS. A hidden Chrome renders it, with a profile of its own inside the project, to
PNG and to a vector print PDF. The PDF is at the exact size with 3 mm bleed. Fonts are the ones every Windows PC has:
Bahnschrift, Segoe UI, Bodoni, Palatino, Rockwell, Impact and Segoe Script. The one new package is `segno`, which
makes QR codes. It is pure Python, was checked by SHA-256 against PyPI, and was scanned before an offline install.

| Area | What it does |
|---|---|
| Kinds | Visiting cards: 3.5 x 2 in, front and back, modern, classic or bold. Square and portrait posts and stories: headline, photo or split. YouTube thumbnails, with a face or centred. Flyers (A5) and posters (A3): sale, with a price list, or event. Certificates (A4 landscape), classic or modern. Invitations (5 x 7 in). Fifteen palettes, seven gradients, any paper size. |
| Layout | Text sits in boxes that shrink it to fit, never below a readable floor. Print designs bleed past the trim and keep words 3 mm inside it. Screen designs keep clear of the apps' own buttons: a story's top 260 px and bottom 360 px. Contact rows carry drawn icons. A monogram stands in for a missing logo. |
| Photos | The photo agent does the photo work. A thumbnail's presenter is cut from a green, blue or plain backdrop and placed with a glow. On a photo post, faces are found and the words go to the other end of the picture. |
| Conversation | "classic style in green", "try another style", "make the name bigger", "change the phone to ...", "remove the address", "add a QR code for ...", "use photo.jpg", "make it a story", "sunset gradient", "export the pdf for printing", "save the png for whatsapp", undo, redo, go back, history. A thinly worded request ("my uncle runs a bakery called ... make him a card") is read by the cheap model, which is told never to invent numbers, prices or names. |
| Certificates for many people | Names come from the chat, a TXT/CSV or an Excel file. They render as one multi-page PDF in a single browser pass. Each name is checked to be printed once, spelled as given, and fitting its line; long names are set smaller and the reply says so. |
| Checks | The page measures itself after rendering: each piece's box, where its letters actually are, type size, colour, outline, and overflow. A second render with the words hidden shows what each word sits on. From these: every detail asked for is on the design; no text runs out of its box; type is at least 5.5 pt in print, or 16 px on screen; everything is inside the safe area; nothing overlaps; WCAG contrast is met against the real background; photos print at 150 dpi or more; the QR code is decoded back to its link with OpenCV; no words cover a face; the fonts are installed; the PDF has one page per side at the exact size; screen designs are their exact pixel size. |
| Speed | All sides go in one document, and four hidden browsers (measure, picture, words hidden, print) run side by side, each with its own profile. A two-sided card takes about 3 s, a post 2-4 s. |

Measured (2026-10-03):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_design.py](tests/test_design.py): 16 designs across every kind and style passing every check; 11 designs spoiled on purpose, each tripping its check (an overlong name, text the colour of the ground, a name past the trim, a QR code read as the wrong link, a missing phone, wrong PDF and picture sizes, a missing font, words over a face, a 90 px photo on an A3 poster); certificate batches; 22 phrasings | 52/52 | 51 s | none |
| [tests/design_conversations.py](tests/design_conversations.py): 5 conversations, 21 turns (a card, a post that becomes a story, a cut-out thumbnail, certificates for four names, requests only the model can read) | 21/21 | 41 s | $0.0003 |

Building it, the checks and visual reviews caught real faults:
- Tight line heights made Chrome report every headline as overflowing, so all of them shrank to their floor.
- Grey and gold text on light paper failed WCAG contrast. Gold text is now darkened only as much as the background needs, while badges keep the true accent.
- White text on a pale sunset gradient read at 1.5:1. Text colours now follow how light the ground is.
- The photo and split posts silently dropped the dates and the call to action.
- An A3 poster built on a 1280 x 720 video still would have printed at 93 dpi.
- A story's headline spilled into the brand line.
- "Dr." in "signed by Dr. Imran Ali" cut the signer's name.

## Business hub: Slack, Teams, Outlook, Gmail, Trello, Notion, Jira and more (official APIs)

```
hub.py steps                 how to make each free key (hub.py steps slack for one)
hub.py connect slack         you paste the key at a hidden prompt; it is checked with Slack at once
hub.py status                what is connected, checked live
hub.py talk -m "what's new in #sales?" -m "post 'Meeting moved to 4 pm' to #general" -m "yes"
hub.py talk -m "draft an email to ali@khan.pk about invoice 1042 saying it has been paid" -m "send"
hub.py talk -m "schedule a meeting with ali@khan.pk tomorrow at 3 pm about the budget" -m "yes" -m "brief me"
```

Every service is driven through its official API: no desktop app is clicked and no web page is scraped. Keys are
typed by you at a hidden prompt and stored encrypted with Windows DPAPI in `state/hub/vault.bin`, so only this
Windows user can read them. They are kept out of addresses and logs, scrubbed from error messages, and never sent to
the language model. Google signs in once in your browser, through a loopback page on 127.0.0.1 with PKCE. Microsoft
signs in with a device code.

| Service | What it can do |
|---|---|
| Slack | Post (to a channel, a person, a thread, or later), read a channel, edit, delete, upload a file, react. Every post is read back from the channel's history. |
| Microsoft 365 | Outlook mail (unread, draft, send), Outlook calendar (events; new events with a Teams link on work accounts), OneDrive (upload, share link), Teams channel posts (work or school accounts). |
| Google | Gmail (unread, a MIME draft with attachments, send, checked in Sent), Calendar (events; new events with a Meet link and invites), Drive (upload, share), Sheets (create, read, append, write). |
| Trello, Asana, Notion, Jira | Cards, tasks and issues: add (with due dates), move through lists or workflows, complete, comment, list what is open or due. |
| HubSpot | Contacts (checked for duplicates first), deals, updates. |
| Zoom | Upcoming meetings, and new ones with join links. |
| Telegram | Messages and files to you: alerts and briefings on your phone. |
| WhatsApp Business | Texts and approved templates through the Cloud API's free test number. A personal WhatsApp account has no API. |
| Figma, Canva | See [Designs to code](#designs-to-code-figma-and-canva-official-apis-into-coding-projects): frames, colours, exports and comments; designs, imports, exports and uploads. |

How it behaves:
- **Reads run at once:** a channel, your inbox, your calendar, your tasks.
- **Anything other people will see waits for your yes:** a post, an email, an invite, a shared task, a CRM record, a shared file. The preview says exactly what will go where. "Change the text to ..." edits the draft; "no" drops it.
- **Emails are drafts first.** "Send" sends the draft.
- **Every action is read back from the service**, written to `state/hub/audit.jsonl`, and can be undone where the service allows it: a post deleted, a card moved back, a task reopened, an event deleted. Sent emails and WhatsApp messages cannot be unsent, and the reply says so.
- **"Brief me"** gathers today's calendar, unread mail, the last 24 hours of the Slack channels the bot is in, and late cards and tasks. The cheap model sums up what needs you, and the briefing can go to your Telegram. This sends message text to the model provider; use `--offline` to keep it on the PC.

Measured (2026-10-04): [tests/test_hub.py](tests/test_hub.py) runs with no network and no keys, against canned answers for 8 services, in 0.2 s, and passes 58/58. It covers:
- the exact requests sent, with secrets never in addresses;
- nothing outward without a yes, and "no" sends nothing;
- drafts then sends, read-backs, undo, the briefing and a day's log;
- vault encryption and scrubbing;
- 18 phrasings.

Live tests need your keys.

## Coding: projects written, run and checked by code (VS Code shows them)

```
coder.py talk -m "make a python script that counts words, lines and characters in a text file" -m "run it"
   -m "add an option to list the 5 most common words" -m "undo"
coder.py talk -m "build a one-page website for Khan Electronics with our products and a contact form" -m "make the header dark blue" -m "open it in VS Code"
coder.py talk -m "open project word_counter" -m "fix this error: <paste the traceback>" -m "what changed?"
```

This lane works on code the way the video lane works on CapCut: code writes the project's files, and VS Code only
shows them. VS Code is set up by writing its workspace files (the project's interpreter, Run and Test tasks, debug
configurations, recommended extensions), the way a CapCut draft is written. The window opens only when you ask.

| Part | What it does |
|---|---|
| Projects | Each project gets a folder in `out/code/projects`, its own `.venv` made by uv (no download), a git history, and a `.vscode` setup. Python, web (HTML/CSS/JS) and Node projects. Standard library only unless you ask, so nothing is downloaded. |
| Writing | The cheap model writes a new project as whole files, and changes an existing one with exact search/replace blocks, never blind rewrites. It sees a map of every file's functions and the files the request is about. It is told to use your real details, or obvious placeholders ("Rs 00,000", "0300-0000000"), and never invent prices, numbers or names. |
| Checks on every version | Every file compiles (Python) or parses (JavaScript). The project's own unittest or `node --test` tests pass. The program runs and exits cleanly. A web page loads in headless Chrome, with a profile of its own, with content, no console errors, and every linked file present; a screenshot is saved. |
| Repair | A failed check's exact output goes back to the model, which fixes its own work, for up to three rounds. The reply says how many rounds it took. |
| Safety | Before anything runs, the code is scanned for things that could change your PC: deleting files, starting other programs, the network, the registry, running strings as code, paths outside the folder. Such code is saved but runs only after your yes. Paths outside the project are refused. |
| Conversation | New projects, changes, "fix this error: ...", run (with other arguments), run the tests, show or explain the code, what changed, undo and redo (git), history, list and open projects (also your own folders, whose current state is kept as the first version). |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_coding.py](tests/test_coding.py): a scripted model; a first version with a bug repaired from its own failing test; edits by search/replace; an edit that does not fit reported; risky code held back; undo and redo; paths outside refused; VS Code tasks; web pages (clean, script error, missing file) in headless Chrome | 22/22 | 13 s | none |
| Live, GLM-5.3-Flash. A word counter: repaired in 1 round, tests 3/3, right output. Then "top 5 words": tests 5/5. A shop website: no console errors, then restyled. A temp-file deleter: held back at `f.unlink()`. | all as intended | 6-14 s a step | $0.0008 for the counter session |

## Designs to code: Figma and Canva (official APIs) into coding projects

```
hub.py connect figma         a personal access token (hub.py steps figma)
hub.py connect canva         your own Canva integration, signed in once in the browser (hub.py steps canva)
coder.py talk -m "make a website from https://www.figma.com/design/KEY/Shop?node-id=1-2" -m "make the call now button green" -m "does it still match the design?"
coder.py talk -m "turn my Canva design 'Eid sale' into a web page" -m "make the shop now button say 'Order now'"
hub.py talk -m "what frames are in https://www.figma.com/design/KEY/Shop" -m "export the 'Home' frame from figma as png to my downloads"
hub.py talk -m "list my canva designs" -m "export my canva design \"Eid sale\" as a pdf to my desktop" -m "upload logo.png to canva"
```

Both tools are driven only through their official APIs: Figma's REST API with a personal access token, and Canva's
Connect API through your own integration (PKCE sign-in on 127.0.0.1:3001; Canva's single-use refresh tokens are kept
in the vault). A design becomes a normal coding project, so the coding lane's versions, undo, VS Code setup and model
edits all apply to it.

| Part | What it does |
|---|---|
| Figma frame to code | Figma's own description of the frame becomes HTML and CSS. Auto layout becomes flexbox: direction, gaps, padding, alignment, wrapping, and each child fixed, hugging or filling. Everything else sits exactly where the design puts it, rotations and flips kept. Texts stay real text: fonts, sizes, weights, line heights, letter spacing, colours, mixed styles, links, lists, truncation. Fills cover colours, gradients and pictures; also borders, corners, shadows, blurs, opacity, blend modes, clipping and masks. Icons are SVG drawn from Figma's own outlines. Each layer gets one CSS class named after it. The HTML is indented, with landmarks (nav, header, section, footer), headings by size, and buttons and links where the layers say so. |
| Canva design to code | Canva's Connect API cannot read a design's elements from outside Canva, so the design is exported as PowerPoint and read with python-pptx. Text boxes, pictures (crops applied), shapes, freeforms, groups, bullets and links come out in the same shape as Figma's, and the same converter writes the page. Anything with no web equivalent, such as a chart or table, is cut from Canva's own picture of the page. Several pages become sections of one page. Email designs can come as Canva's own HTML. |
| Fonts | The free Google fonts a design uses are saved into the project (latin subsets, SIL Open Font License or Apache 2.0), so the page looks the same offline. A paid font is named, and a stand-in is used. |
| Checks on every version | The page is opened in headless Chrome at the design's size and measured from inside. Every element's box is compared with the design's box, within 3 px, and the worst misses are named. Every text must be present, and none may spill out of its box. Every font must actually load. A screenshot is compared with the design's own picture (Figma's PNG of the frame, or Canva's PNG pages) for shape similarity (SSIM) and colour, cell by cell, and the least alike part is named with the layers near it. `.out/compare.png` shows the design, the page and their differences side by side. After you ask for changes, the comparison is reported but no longer enforced, because changes are meant to differ. |
| Hub | Figma: a file's frames, its colours and text styles, frames exported in one request (PNG, SVG, PDF, JPG), comments read, and comments posted after your yes, read back and undoable. Canva: designs listed and found by name, new designs (presets or named sizes), files imported as editable designs, exports saved to your folders (PDF, PNG, JPG, GIF, MP4, PowerPoint), and pictures uploaded and undoable. |
| Limits respected | Figma's View and Collab seats allow about 20 file reads a month. A file is read once, kept on this PC, and read again only when Figma's cheap version check says it changed. Pictures are fetched once (their names are content hashes), and all frames export in one request. Canva's export jobs are polled with growing waits, and its download links are fetched at once, never with your key. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_design2code.py](tests/test_design2code.py): a landing page in Figma's exact JSON with every box worked out by hand (37/37 elements in place, 17/17 texts, the HTML and CSS Figma's rules call for); a spoiled copy caught (a moved title named, a changed text found); the picture comparison finding a changed region; fonts; Canva's route on a PowerPoint file with PowerPoint's own pictures as the reference (page 1 similarity >= 0.9, the chart page >= 0.95, two pages as two sections); both connectors against fake servers (caching, exports, downloads without the key, polled jobs, explained errors, comments and uploads taken back, PKCE sign-in and refresh); the coding chat and the hub end to end | 96/96 | 38 s | none |
| [tests/design2code_conversations.py](tests/design2code_conversations.py), GLM-5.3-Flash: a Figma landing page made, its button turned green and its heading reworded by the model, measured again and undone; a Canva sale page whose button text is changed | 7/7 turns (twice) | 39 s | $0.0021 |

Live tests need your Figma token and Canva integration (`hub.py steps figma`, `hub.py steps canva`).

## Social media: Facebook, Instagram, Threads, YouTube, TikTok, LinkedIn and X (official APIs)

```
social.py steps                    how to make each platform's free developer app (social.py steps instagram for one)
social.py connect youtube          sign in once; keys and tokens kept encrypted on this PC
social.py talk --with eid.mp4 -m "post eid.mp4 to instagram reels, facebook and youtube shorts saying 'Eid sale is live!'" -m "yes"
social.py talk -m "post poster.jpg to facebook tomorrow at 7 pm saying 'Tomorrow only: 20% off'" -m "yes" -m "what's scheduled?"
social.py talk -m "how did my posts do this week?" -m "make a report" -m "any new comments?" -m "reply to the first one saying thank you!" -m "yes"
social.py run                      publish what is due (Windows Task Scheduler runs it every 5 minutes once automatic posting is on)
social.py setup-tunnel             once, for Instagram pictures and Threads media (see below)
```

Every platform is used only through its official API. The current rules (checked 2026-10-04 against each platform's
developer docs) are written into the code with their sources. A post is composed once. Each platform gets its own version:
its kind of post, its words and its media, converted and measured. That version is shown before anything goes out, and
nothing is published without your yes. Each post is then read back from the platform.

| Platform | What it posts | Scheduling | After posting | Rules set by the platform |
|---|---|---|---|---|
| Facebook Page | text and links, 1-10 photos, videos, Reels, Stories | by Facebook itself (10 minutes to 30 days ahead, PC may be off) | link, numbers (views, reach, reactions, comments, shares), comments answered and hidden, delete | the Meta app must be switched to Live (else only you see the posts); 30 Reels a day |
| Instagram (professional account linked to the Page) | photos, carousels of 2-10, Reels, Stories | by this PC | link, insights, comments answered and hidden, delete | 50 API posts in 24 hours; pictures only from a web address (lent for a minute, below); sign in again every 60 days |
| Threads | text, a picture, a video, carousels of 2-20 | by this PC | link, insights, replies answered and hidden, delete | 250 posts a day; media only from a web address; 500 characters, 5 links, 1 topic tag |
| YouTube | videos and Shorts (vertical, 3 minutes or less), thumbnail, captions | by YouTube itself (publishAt) | link, statistics, comments answered and held for review, delete | 100 uploads a day; uploads from an unaudited Google project stay PRIVATE until YouTube's free API audit |
| TikTok | videos (pictures become a slideshow video) | by this PC | numbers for public videos | personal tools are not audited for public posting, so videos go to your TikTok inbox as drafts (you post them in the app) or post as private; no deleting |
| LinkedIn | text, 1-20 images, a video, on your profile | by this PC | link, delete | personal apps get no statistics and cannot read posts back; the sign-in lasts 60 days |
| X | text (long text as a thread), 4 pictures or a video | by this PC | link, numbers, replies answered, delete | paid per use: $0.015 a post, $0.20 with a link (shown before posting) |

| Part | What it does |
|---|---|
| Words | Lengths are counted the way each platform counts them. X counts links as 23 and emoji as 2; Threads counts emoji by their UTF-8 bytes; YouTube's description limit is in bytes. Hashtag and mention limits are checked, LinkedIn's reserved characters are escaped (hashtags kept), and YouTube titles are made from the first line. Text too long for X becomes a numbered thread; elsewhere it is reported, never cut. Your own links can be tagged for tracking (`utm_source`). |
| Media | Pictures are cropped around the subject to an allowed shape, or fitted whole on a blurred fill when asked. They are saved as sRGB JPEGs, with location and camera data removed, within each platform's size. Videos go through the converter's preset for the platform only when they do not fit already (codec, frame, fps, size, the 1280 px cap for X), and are measured again. Too short or too long is reported. A video is cut only when you ask. |
| Publishing | Each platform's job is a resumable state machine saved in SQLite (`state/social/social.db`). YouTube uploads in 8 MiB chunks and resumes from the byte YouTube confirms. TikTok uses its chunks, LinkedIn its signed parts with ETags, X its segments, and Meta its rupload sessions. The engine waits while each platform processes. A request that creates a public post is never resent blindly: after a lost answer, the latest posts are searched for it (on LinkedIn, which cannot be read back, you are asked to check). |
| Failures | Passing problems wait 1, 5, 15, 60, then 240 minutes; rate limits and quotas wait as long as the platform says (YouTube's renews at midnight Pacific time). An expired sign-in waits for you. A refused post is reported with the platform's reason. Only one runner works the queue at a time. |
| Sign-in | OAuth with a loopback address and PKCE where each platform supports it (TikTok's hex variant included). Meta and Threads tokens are pasted from Meta's Graph API Explorer, because Meta's desktop sign-in is an embedded browser and Threads refuses loopback addresses; they are made long-lived, the Page token never expires, and Threads renews itself a week early. All keys are DPAPI-encrypted and never printed, logged or sent to the model. |
| Temporary web address | Instagram (pictures) and Threads (all media) fetch media from a URL. `social.py setup-tunnel` installs Cloudflare's cloudflared into `tools/cloudflared`, checked against Cloudflare's published SHA-256 and its Windows signature. A one-file server is then exposed for a minute at a random address under a 32-character secret path, and closed once the platform has the file. |
| Conversation | Compose, preview, yes or no, a new caption, "yes but not on tiktok". Also the queue, cancel, delete, results (with an Excel report), new comments, reply by number or "the first one", hide, retry, edit a waiting post, the best times to post (from your own numbers only), and automatic posting on or off (a hidden Windows task, added only after your yes). The cheap model reads only what the rules cannot. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_social.py](tests/test_social.py), no network and no keys: words; the runner (processing, native scheduling, retries, limits, expired sign-ins, refusals, crashes, one runner at a time); real media through each platform's rules (Reels, panoramas, carousels, GPS removed, slideshows, X's 1280 px cap, cut only when asked); every connector against a fake server built from its docs; a YouTube upload that loses its connection mid-file and resumes byte-exact; Instagram fetching the exact prepared file from the temporary address, which is then closed; X and LinkedIn posts whose answers were lost not posted twice; sign-ins (TikTok's hex PKCE, Google's S256, Meta's long-lived and Page tokens, Threads' early renewal); the tunnel installer refusing a changed file or a wrong signature; 20 everyday phrasings; the chat end to end | 127/127 | 70 s | none |
| [tests/social_conversations.py](tests/social_conversations.py), GLM-5.3-Flash with the fake platforms: a reel to Instagram and Facebook, a YouTube Short asked for in other words, a scheduled LinkedIn and Threads post dropped, a tweet with its cost, the week's numbers, comments, a reply to "the first one" | 12/12 turns | 3 s | $0.0001 |

Live tests need your developer apps and keys (`social.py steps <platform>`).

## Converter: videos and sound converted, shrunk, cut and fixed (programmatic)

```
convert.py talk holiday.mov -m "will it play on whatsapp?" -m "make it ready for whatsapp" -m "save it to my desktop"
convert.py talk clip.mp4 -m "cut the first 5 seconds and make it under 10 MB" -m "make a gif of 0:05 to 0:08" -m "undo"
convert.py look holiday.mov        convert.py batch "C:\Users\me\Videos" -m "for email"        convert.py record --seconds 20 --mic
```

What Format Factory and HandBrake do, done by code: FFmpeg makes every file, on the Intel GPU when that helps. Every
result is read back and checked, and its look is measured against the original.

| Part | What it does |
|---|---|
| Reading files | Container, length, size; the picture as it is shown (phone turn flags and odd pixel shapes applied), frame rate and whether it varies, bit depth, HDR, interlacing; sound tracks; subtitles; whether an MP4 starts playing before it has downloaded. "Will it play on WhatsApp / my TV / an iPhone?" is answered from these, with the reasons. |
| Targets | WhatsApp, email, Discord, Telegram, Slack, Instagram (Reels, posts, stories), TikTok, YouTube and Shorts, Facebook, LinkedIn, X, a website, iPhone, Android, a TV or USB player, PowerPoint, editing (ProRes), keeping (AV1), every device. Limits checked on 2026-10-04: WhatsApp's FAQ says 100 MB at 720p (64 MB on slow connections), Discord's free limit is 10 MB, Telegram bots send up to 50 MB, and email is kept under 18 MB for Gmail and Outlook. |
| One encode, from the original | Every version is made from the original files, so nothing is compressed twice. The picture is copied, not re-encoded, whenever nothing about it changes: a new container, a cut on keyframes, a file that already fits, a change to the sound only. A cut between keyframes is re-encoded to the exact frame, unless "without re-encoding" is asked or re-encoding would take long. |
| Size limits | "Under 10 MB": the bitrate comes from the length, and a sample of this very video shows how many kbps it needs, so the biggest frame and frame rate that fit are chosen (a still screen recording keeps 1080p where busy footage drops to 540p). A file still over the limit is made again, smaller. An impossible limit is refused with the ways out (split into parts, cut it shorter, save the sound only). |
| Smaller at the same look | The quality setting is searched on samples (VMAF 94 or more) and the smallest that still looks the same is used. A file that is already as small as it goes at the same look is left alone, and it says so. |
| Encoders (measured here) | H.264 on the Intel GPU is the default: on this PC it was 2-3x faster than x264 and as good per byte (VMAF 93.0 at 1.54 Mbps, against 89.9 at 1.47). AV1 on the GPU for keeping. HEVC is made by x265, because the GPU's HEVC encoder fails here; VP9 by libvpx, because the GPU's ignores its quality setting. If the GPU encoder fails, the processor makes the file. |
| Changes | Format, codec, quality, size; 720p and other sizes; frame rate; 9:16, 1:1 or 4:5 with a blurred fill, black bars or a crop; turns and mirrors; black bars cut off; trims and cuts, speed (pitch kept; smooth slow motion), joins (clips of another shape fitted with blurred sides); mute, replace or add sound, volume, loudness levelled (two passes), sound moved into sync; stabilise (two passes), deinterlace, denoise, sharpen, black and white, fades, a logo, subtitles burned in or as a track (they follow cuts); a GIF or animated WebP under a size; pictures at given times, every N seconds, a thumbnail or a contact sheet; splits into N parts, every N seconds, or under a size each. |
| Checks on every version | It plays through (decoded); its length, frame size, frame rate, codecs and sound are what was asked; it fits the size limit; an MP4 starts playing before it has downloaded; and its look is measured against the original with VMAF. The output and the reference are put on one frame clock first: frames paired half a frame apart scored 58-78 instead of 96 on the same file. |
| Conversation | Versions, undo, redo, "go back to v2", history, compare, "how good is it?", "where is it?", and saving to your Desktop, Downloads, Videos or next to the original (never over a file). If a request needs something only the video has ("for TikTok", "720p") while the current version is a GIF or sound file made from it, it builds on that video. The cheap model reads only what the rules cannot. |
| Screen recording | The screen recorded in the background by FFmpeg (Windows Desktop Duplication, on the GPU's encoder), with the microphone when asked, for a set time or until "stop recording". The recording becomes the chat's file. Nothing is clicked or moved. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_convert.py](tests/test_convert.py): clips made for the test, every change measured independently of the converter's own checks: lengths, sizes, frames, pixels (blurred fill, logo corner, burned subtitles after a cut, fades, black and white), loudness, where a beep lands after a sync fix, pitch after a speed-up. Also keyframe copies, refused limits, splits, joins, screen recording (`--record`), checks failing on spoiled files, and the rules. | 92/92 | 136 s | none |
| [tests/convert_conversations.py](tests/convert_conversations.py), GLM-5.3-Flash on real clips: a 96 MB HEVC screen recording for WhatsApp (11.8 MB, looks 96/100), under 8 MB, then under 15 instead, undo, compare. A square clip to TikTok (1080x1920, blurred fill), a cover picture, music removed, a GIF under 3 MB. A talking video's sound moved 0.2 s, the voice as MP3, then the video at 720p. Two clips joined under a narration, for YouTube. Everyday words: "my uncle's old tv won't open this, sort it". | 19/19 turns | 164 s | $0.0001 |

## 3D: houses from plans, 3D titles, product mockups, 3D files (programmatic, Blender)

```
three.py talk -m "a 3D model of a 7 marla double story house with 3 bedrooms" -m "show it from the street" -m "make a video going round it"
three.py talk -m "make my house plan 3D" -m "grey walls with wood panels" -m "make the kitchen bigger" -m "the first floor"
three.py talk -m "a 3D intro for Khan Electronics in gold" -m "add the tagline Best prices in town"
three.py talk --with card.png -m "put card.png on a box" -m "now a mug" -m "on a laptop instead"
three.py talk -m "show me chair.glb" -m "is it ready for 3D printing?" -m "convert it to stl"
```

Blender 5.2.2 LTS runs in the background from `tools/blender`, as CapCut does for video. It was downloaded from
blender.org, checked against blender.org's own SHA-256 (`3849d17a...6b535`) and its program signatures (Blender
Foundation, valid), and it keeps its settings in its own `portable` folder, never in AppData. Code builds every scene;
Blender only renders it.

| Part | What it does |
|---|---|
| Houses | A plan from the CAD lane becomes 3D. Walls are cut round every door and window as blocks that never overlap. Lintels, sills, framed glass, sunshades and stone, wood or brick cladding round the front windows. Floors by room: marble, wood planks, tiles, a tiled bath. Stairs built like real ones (treads up to 11 in, risers near 7 in) up to the next floor. The furniture sits exactly where the drawing puts it. Slabs, an open terrace, a parapet that follows the roof's outline, a porch with columns, a gate and a ramp, then the road. "Make the kitchen bigger" goes to the CAD lane, and the 3D follows the new plan. |
| Views | A 3D floor plan (one storey cut at 6 ft, from above at an angle, furniture, every room's name and size placed clear of doors and furniture), a top view, the front from the street, a view from above, and a turn-around video. Each camera frames the building itself. Normal renders use EEVEE (seconds); "high quality" uses Cycles on the Intel Arc GPU (oneAPI). |
| 3D titles | Extruded, bevelled letters in gold, silver, chrome, copper, glass, neon or a colour, with a second line and a logo. The reflections see a studio while the camera sees a plain background, so metal looks like metal. A light sweeps across the letters while the camera moves in, or the title spins, rises or drops into place. |
| Mockups | Your picture on a box, two business cards on a desk, a laptop, a phone, a mug (handle on the right, picture the right way round) or a framed poster, mapped exactly. |
| 3D files | GLB, glTF, OBJ, FBX, STL, PLY and USD files opened and measured: size, triangles, materials, and for 3D printing, open edges, watertightness and volume. They are pictured in a studio or turned round in a video, then converted to another format and opened again. |
| Checks on every version | **The model against the plan:** a floor for every room, glass in every window, stairs reaching the next floor, the front door, every name placed. **Every picture:** a flat silhouette of the subject alone shows it in view and not cut off; the camera's framing is reported; it is not blank, too dark or washed out. **Videos:** length, frame rate, movement, no empty frames. **Titles:** centred and readable. **Mockups:** the picture faces the camera, keeps its colour balance and brightness, and its face, straightened out of the render, matches your picture shape for shape and not mirrored (a mirrored print is caught). **3D files:** the converted file opened again has the same triangles and size. |
| Conversation | Versions, undo, redo, history, "go back to v1", saving to your folders, and questions ("how big is it?", "is it ready for 3D printing?"). The cheap model reads only what the rules cannot. |

Measured (2026-10-04):

| Suite | Result | Time | Model cost |
|---|---|---|---|
| [tests/test_three.py](tests/test_three.py): house geometry for 5 marla, 7 marla and 1 kanal plans; 1- and 2-storey houses rendered with a video; spoiled pictures and a still video that must fail their checks; a gold title; all six mockups; mirrored prints caught; a closed cube and a box with no lid measured and converted; rules; chats through the CAD lane | 68/68 | 336 s | none |
| [tests/three_conversations.py](tests/three_conversations.py), GLM-5.3-Flash: a house described in everyday words, seen from the street, repainted beige with wooden texture, turned round in a video, its lounge enlarged; a chrome logo animation with a tagline; a visiting card on a mug and a laptop; a 3D file asked about for printing and converted to STL | 12/12 turns | 775 s | $0.0003 |

## Accounts: invoices, books, sales tax; QuickBooks, TallyPrime, Xero, Zoho Books and FBR (programmatic, official APIs)

```
accounts.py talk -m "invoice for Ali Traders: 2 LED TV 55 at 85,000 each, 18% tax, due in 15 days" -m "yes"
accounts.py talk -m "Ali Traders paid 1.5 lakh by bank and deducted 4,000 tax" -m "yes" -m "who owes me money?" -m "profit this month"
accounts.py talk -m "send everything to tally" -m "yes"         (or quickbooks, xero, zoho)
accounts.py talk -m "post invoice 3 to FBR" -m "yes"            (FBR Digital Invoicing: validated first, then FBR's number and QR code on the PDF)
accounts.py steps xero | connect xero                           (steps quickbooks / tally / zoho / fbr)
```

The books on this PC are the record (double entry in SQLite, exact paisa, Pakistan's July-June year, 18% sales tax per
line, 4% further tax for buyers without an STRN, income tax withheld, stock at average cost, gapless numbers, voids by
reversing entries, sales tax invoices as PDF, every change checked). The accounting software people already use gets a
copy: each document goes once and is read back total for total; every part (a payment per invoice, an allocation) is
remembered the moment it exists and looked for before a new try, so a lost answer never makes a duplicate; a document
cancelled here is cancelled there.

| System | How | Notes |
|---|---|---|
| Xero | Accounting API, PKCE app (no secret), http://localhost:3009/callback | Free Starter developer tier (1,000 calls a day); Idempotency-Key on every create; tax rate 'Sales Tax 18%' made once |
| Zoho Books | API v3, Self Client code pasted once | Free plan 1,000 calls a day; further tax as a tax group; no idempotency key, so nothing is retried blindly |
| QuickBooks Online | Accounting API v75, OAuth with client secret | Sandbox signs in on localhost; production needs an HTTPS redirect (paste the address); requestid on every write; tax codes under agency FBR |
| TallyPrime | XML gateway on port 9000, UTF-16, no key | Masters made only when missing (never alters yours); REMOTEID makes a resend an update; item invoices for stock |
| FBR Digital Invoicing | PRAL DI API v1.12, Bearer token | Validated first, posted on yes, never posted twice blindly; needs 1-3 fixed IPs approved by PRAL |

Measured (2026-10-04): [tests/test_accounts.py](tests/test_accounts.py) 52/52 (books, documents, rules, chat);
[tests/accounts_conversations.py](tests/accounts_conversations.py) 11/11 turns ($0.0005);
[tests/test_accounts_systems.py](tests/test_accounts_systems.py) 81/81 against fakes of each API
([tests/accounts_fakes.py](tests/accounts_fakes.py)): lost answers, a failure part-way, expired sign-ins, limits, voids. Live use waits on your keys.

## Many programs, a basic setup each (programmatic)

```
apps.py talk --with receipt.jpg -m "what is the total on receipt.jpg?"
apps.py talk -m "which apps can be updated?" -m "update vlc" -m "yes"
apps.py talk -m "flowchart: Start -> Take order -> In stock? -yes-> Pack -> End; In stock? -no-> Order -> Pack"
apps.py talk -m "cite 10.1038/nature14539 and isbn 9780262035613 in apa"
apps.py list
```

| Program | Driven by | What it does |
|---|---|---|
| Text from pictures (OCR) | Windows' own OCR engine (Windows.Media.Ocr), no install | Pictures and scanned PDFs to text or Word; receipt total, date, NTN, phone picked out |
| PC care | winget, psutil, Defender cmdlets, netsh | Apps to update, install, update, remove (shown first, done on yes); disk space; antivirus status and quick scan; Wi-Fi; battery |
| Diagrams | own layout, SVG, headless Chrome | Flowcharts (decisions, loops, arrows in their own lanes), org charts, mind maps as PNG, PDF, SVG and an editable draw.io file |
| References | Crossref (DOI) and Open Library (ISBN), free | APA 7, MLA 9, Harvard, IEEE, Chicago in Word (hanging indent, italics) plus BibTeX and RIS |
| Quizzes | own writers | Moodle XML, GIFT, Kahoot sheet, printable paper and answer key |
| Ebooks | own EPUB 3 writer | Word, Markdown or text to EPUB with chapters, contents, cover |
| Music and video | ffprobe, VLC | Playlists (.m3u8, .xspf) in natural order or shuffled, with total length; played in VLC |
| Printing | pywin32 (GDI), Office in the background | Printers and queues; PDFs, pictures and Office files printed fitted to the page (shown first) |
| Maps | OpenStreetMap Nominatim, free | Places to KML, GPX, GeoJSON; distances; a Google Maps route link |
| Notes and to-dos | Markdown files (Obsidian-compatible) | Quick notes, to-dos in today's note, tasks across notes ticked off, search |
| Databases | DAO (Access's own engine, no window), SQLite | Excel/CSV to Access .accdb or SQLite, one table per sheet; read-only SQL questions answered to Excel |
| Backups and zips | zipfile + SHA-256 | Dated backups with a manifest, verified file by file; damage caught; safe unzip (no zip-slip) |
| Contact cards | vCard 3.0 | From words or an Excel list, numbers in +92 form, a QR of the card |
| QR codes and barcodes | segno, own Code 128 and EAN-13 | Links, Wi-Fi and text QR codes read back by a QR reader; barcodes decoded back from their bars; A4 label sheets |
| Music | own MIDI and MusicXML writers | Melodies in letters to MIDI (any player) and sheet music (MuseScore), read back note by note |
| Calendar | .ics (Asia/Karachi) | Meetings and reminders from words, with length, place, repeats and an alarm; Outlook and Google Calendar import them |
| Shopify | Admin GraphQL 2026-10; Dev Dashboard app, 24-hour client-credentials token | Products, add (SKU checked first), price and stock by SKU (idempotency key), new orders, fulfil with tracking |
| WooCommerce | REST v3 over HTTPS, consumer key/secret | Same, variations included; shipping = a customer note with the tracking, then completed |
| Daraz | Open Platform, every call signed (HMAC-SHA256) | Products, price and stock by seller SKU, pending orders, pack and ready-to-ship (Daraz gives the tracking) |
| WordPress | REST with an Application Password | Draft posts with a featured picture, list, publish after a yes |
| Odoo | JSON-RPC (Odoo 18 and 19) with an API key | Products, orders to invoice, draft customer invoices (customer and products found or added) |
| Web pages | headless Chrome (the page's scripts run, nothing on screen) | Readable text to Markdown (menus and footers left out), tables to Excel with numbers as numbers, links, PDF, full-page picture |
| Desktop | Pillow, the Windows clipboard, the default programs | Screenshots of every screen, text on and off the clipboard, files and web pages opened |
| Email campaigns | Mailchimp Marketing API 3.0, Brevo API v3 | Audiences, contacts from Excel (bad addresses left out), a campaign shown first with how many it reaches, reports |
| Dropbox | API v2, PKCE code pasted once | Uploads checked with Dropbox's own content hash, folders listed, share links after a yes |
| Discord | a channel's webhook | Messages and pictures posted after a yes, read back, the last post deleted on request |
| Statistics (like SPSS) | numpy plus its own t, F and chi-square distributions | Descriptives, t-test (Student and Welch, Cohen's d), ANOVA, crosstab with chi-square, correlation, regression, Cronbach's alpha; APA sentences and tables in Word |
| Grammar and spelling | LanguageTool's free public service (after a yes: the text leaves the PC) | Issues listed with suggestions; spelling and grammar fixed in a copy, style hints listed |

Store and website changes are shown first and done after a yes, then read back from the shop. `apps.py steps shopify` (or
woocommerce, daraz, wordpress, odoo) shows how to get the keys; `apps.py connect shopify` keeps them encrypted.

Measured (2026-10-04): [tests/test_apps.py](tests/test_apps.py) 103/103 in 27 s (29 programs; statistics checked against textbook p-values and hand-worked tests) (each program's main path, by function and by chat;
printing checked through 'Microsoft Print to PDF'; web services are fakes from their documentation in
[tests/stores_fakes.py](tests/stores_fakes.py); Daraz's signature checked against Daraz's own test vector).

## The world's most popular apps, a basic feature set each (programmatic)

```
apps.py talk -m "unity game: coin collector called 'Coin Run', 12 coins, red player, speed 7"
apps.py talk --with intro.mp4 main.mp4 song.mp3 -m "premiere timeline: intro.mp4 0-5, main.mp4 10-40; music song.mp3"
apps.py talk -m "after effects title: 'Eid Sale' subtitle 'Up to 50% off'"      apps.py talk -m "obs scenes" -m "start recording in obs"
apps.py talk -m "google form quiz 'Science test': 1. What is H2O? a) Water* b) Salt"    apps.py steps github | spotify | salesforce | obs
```

| Category | App | Driven by | Basic features |
|---|---|---|---|
| Game engines | Unity | a project written as files: C# scripts + an editor script that builds the scene inside Unity; batch-mode build when Unity is installed | A playable 3D coin-collector (move, jump, follow camera, score, timer, win/lose), changed by words |
| Pro video | Premiere Pro, DaVinci Resolve, Final Cut Pro | their timeline files: Premiere XML, FCPXML 1.10, CMX 3600 EDL, OpenTimelineIO | Clips with in/out points and a music bed at the first clip's frame rate and size |
| Images | Photoshop (and GIMP, Photopea, Affinity) | layered PSD written by code | Posters and posts as named, movable layers; pictures stacked as layers |
| Motion | After Effects | Lottie (Bodymovin) JSON + an ExtendScript .jsx | Title animations played and checked with lottie-web; the .jsx builds the composition in After Effects |
| Streaming | OBS Studio | obs-websocket v5 (own RFC 6455 client) | Scenes, sources (text, pictures), recording, streaming after a yes, screenshots |
| Google Workspace | Docs, Slides, Forms | Google's APIs through the hub's sign-in | Docs with headings, slide decks, marked quizzes in Forms |
| Developers | GitHub | REST API + git (token only in a header for one push) | Repositories, push a project (checked against GitHub's latest commit), issues |
| Developers | Jupyter | .ipynb written and run here (pandas, matplotlib) | An analysis notebook with tables and a chart, opened finished |
| Developers | Docker | Dockerfile, .dockerignore, compose.yaml | Matched to the project (Flask, Django, FastAPI, Node, static), checked; built when Docker is installed |
| Developers | Postman | collection v2.1 + environment; a Newman-like runner | API collections imported by Postman; runs with a report (writes after a yes) |
| Music | Spotify | Web API, PKCE | Playlists from song names, now playing, top tracks |
| CRM | Salesforce | REST API, PKCE app | Leads, opportunities, add a lead (after a yes), counts by status |
| Microsoft 365 | To Do, OneNote | Microsoft Graph through the hub's sign-in | Tasks with due dates, tick off, OneNote pages |
| Game engines | Godot 4.7.2 (in tools/godot) | project files + GDScript; the game is played headless here | A 2D platformer (platforms, coins, score, win), checked by really playing it: lands, moves, jumps |
| Vector design | Illustrator (and Inkscape, Affinity, Figma) | layered SVG + print PDF | Posters and logos with named layers and editable text |
| BIM | Revit, ArchiCAD (IFC) | IFC4 written with ifcopenshell | House plans from the CAD lane as storeys, walls cut round doors and windows, slabs, rooms with areas; reopened, geometry built, schema-validated |

### Desktop apps (the app is the real thing, not a web service)

```
apps.py talk --with beach.jpg -m "lightroom preset 'Warm Film': warm vintage, exposure +0.3, vignette -20 for beach.jpg"
apps.py talk -m "anki deck 'Capitals': France = Paris; Japan = Tokyo, both ways"   apps.py talk -m "arduino traffic light on a nano"
apps.py talk -m "project plan 'House build' starting 2 november: foundation 10 days; walls 15 days after foundation; roof 7 days after walls"
apps.py talk -m "slice cube 20 mm for ender 3 in pla, 20% infill"
apps.py talk -m "solidworks plate 100x60x5 mm with 4 holes 6 mm, aluminium" -m "slice it for ender 3"
apps.py talk -m "matlab fft of 50 Hz and 120 Hz"      apps.py talk -m "musescore 'Little Song': C4 D4 E4 F4 G4/2 G4/2 at 100 bpm on piano"
apps.py talk --with interview.wav -m "audacity podcast cleanup interview.wav" -m "make it 10% slower"
apps.py talk --with garden.docx -m "calibre convert garden.docx to epub and kindle"     apps.py talk -m "kicad 555 blinker 2 hz on 9v"
apps.py talk -m "krita canvas 3000x2000 with layers sketch, ink, colours"      apps.py talk -m "openscad gear 20 teeth module 2"
apps.py talk --with invoice.xlsx -m "libreoffice recalculate invoice.xlsx"     apps.py talk --with photo.jpg -m "gimp enhance photo.jpg"
```

| Category | App | Driven by | Basic features |
|---|---|---|---|
| Photos | Lightroom Classic, Lightroom, Camera Raw | .xmp develop presets (+ sidecars for RAW) | Looks from words or sliders; the same look applied here so finished JPEGs come out, each checked (brighter, warmer, grey, darker corners) |
| Study | Anki | .apkg decks written with genanki | Cards from words, notes, CSV/Excel, cloze; both ways; read back from the package's own database |
| Electronics | Arduino IDE | arduino-cli 1.5.1 + AVR core in tools/arduino | Sketches from words (blink, traffic light, button, knob, ultrasonic, LM35, PIR) really compiled for Uno/Nano/Mega with wiring; upload after a yes |
| Projects | Microsoft Project, ProjectLibre | MSPDI XML in the schema's element order + Excel Gantt | Plans from words or Excel on working days, critical path and slack, loops refused, read back and rescheduled |
| 3D printing | PrusaSlicer 2.9.6 (in tools/prusaslicer; Bambu Studio, OrcaSlicer, Cura open the .3mf) | its command line with its own printer profiles | Models or shapes sliced for Ender-3/V2/S1, Prusa MK4S, CORE One: quality, material, infill, supports, brim, copies; time and filament; checked on the bed and to height |
| Mechanical CAD | SolidWorks, Fusion 360, Inventor, CATIA, Creo (STEP); FreeCAD 1.1.4 itself (in tools/freecad) | FreeCADCmd headless: parametric Part objects -> .FCStd, STEP, STL | Plates with holes, L-brackets, flanges with bolt circles, spacers, enclosures; changed by words; weight by material; holes counted, STEP read back with the same volume; 'slice it' sends the part to PrusaSlicer |
| Engineering maths | MATLAB (GNU Octave 11.3 runs the same .m in tools/octave) | plain MATLAB scripts run by octave-cli, no window | Function plots, linear equations, FFT, RC circuits by ode45, matrix inverse/eigenvalues/determinant, a .m given; every printed number re-checked in Python |
| Sheet music | MuseScore Studio 4.7.5 Portable (tools/musescore-portable) | its command line on a hidden desktop ([harness/hidden_desktop.py](harness/hidden_desktop.py)) | Melodies, MusicXML or MIDI to .mscz, PDF, PNG and MP3; 'musescore it' takes the melody just made; checked by MuseScore's own score report, the PDF title, the note count and the MP3 length |
| Electronics (PCB) | KiCad 10.0.6 (tools/kicad, unpacked by 7-Zip without its 3D models) | .kicad_pro + .kicad_sch written with KiCad's own library symbols ([harness/apps/sexpr.py](harness/apps/sexpr.py), [harness/apps/circuits.py](harness/apps/circuits.py)); kicad-cli on the hidden desktop | An LED with its resistor, a voltage divider, a 555 blinker (E12/E24 values explained); ERC clean, KiCad's netlist exactly as meant, BOM CSV, PDF; Gerbers + drill zipped for a PCB maker after DRC |
| Digital painting | Krita 6.0.4 portable (tools/krita, KDE-signed) | OpenRaster (.ora) written here; Krita on the hidden desktop makes its own .kra and renders it | Posters and stacked pictures (the Photoshop program's words), painters' canvases with named layers; Krita's render identical to the layers. Krita has no portable mode: a kritarc pointing its 97 MB of resources into tools/krita/home exists only while it runs |
| Maps & GIS | QGIS 4.2.3 (tools/qgis from its OSGeo-signed MSI) | QGIS's own Python and qgis_process on the hidden desktop (offscreen Qt, QT_QPA_FONTDIR), profile and cache in tools/qgis/home | Maps of places from CSV/Excel/GeoJSON over QGIS's bundled Natural Earth world map: .qgz project, PNG, PDF layout (title, legend, scale bar), markers counted and labels read back by Windows OCR; buffers in metres (UTM) checked as pi r^2; GeoJSON/KML/Shapefile/GeoPackage conversion |
| Photo editing | GIMP 3.2.6 (PortableApps.com build in tools/gimp-portable, unpacked by 7-Zip) | its Python batch mode (python-fu-eval) on the hidden desktop; GIMP3_DIRECTORY/CACHEDIR/TEMPDIR and HOME in tools/gimp-portable/home | Enhance (auto contrast + unsharp mask), black and white, resize, rotate, square crop, format change; layered posters as .xcf reopened by GIMP; every result measured (contrast range, sharpness, greyness, size) |
| Maker 3D | OpenSCAD 2026.10.03 (tools/openscad) | parametric .scad (Customizer variables) rendered headless | Box with lid, name tag / keychain, phone stand, involute spur gear, a .scad given; manifold (PrusaSlicer double-checks extrusions), the size asked; 'slice it' prints it |
| Free office suite | LibreOffice 26.8.1 (tools/libreoffice from its MSI; GPG + Authenticode checked) | soffice --headless on the hidden desktop, its profile in tools/libreoffice/home | DOCX/ODT/PDF/RTF/TXT, XLSX/ODS/CSV, PPTX/ODP conversions carrying the original's words; spreadsheets saved by code recalculated by Calc (every formula gets its value, none an error) |
| RAW photos | RawTherapee 5.13 (tools/rawtherapee; GitHub SHA-256; its installer is a newer Inno Setup that innoextract and 7-Zip cannot open, so the zip) | rawtherapee-cli on the hidden desktop with a .pp3 profile written from words on top of its default profile; RT_SETTINGS/RT_CACHE in tools/rawtherapee/home | RAW (CR2, CR3, NEF, ARW, DNG ...) and JPEG/TIFF/PNG developed: brighter, darker, auto levels, black and white, vivid, warmer, cooler, sharpen, less noise; to JPEG, TIFF or PNG; each change measured against the original (brightness, colour, warmth, detail), same size |
| Video editing (free) | Shotcut 26.9.27 portable (tools/shotcut, Meltytech-signed) | Shotcut .mlt projects (the Premiere program's timeline words + a title) rendered by its engine melt on the hidden desktop | Cuts, music bed faded out, a title; 10 s test edit renders in ~6 s; checked: length, sound, each cut shows the right moment (correlation vs the source, better than a second off), title read by Windows OCR |
| Video compression | HandBrake (HandBrakeCLI 1.11.2 in tools/handbrake; digest + HandBrake Team GPG checked) | its official presets on the hidden desktop | Discord (10 MB) / Gmail (25 MB) presets picked by the video's length, phones, YouTube, 480p-4K, H.265; checked: same length, size limit kept, preset's picture size, sound kept. Its Intel QSV preset fails on this Arc iGPU (low-power H.265), so it falls back to software H.265 and says so |
| Diagrams | draw.io desktop 31.7.0 (tools/drawio, draw.io Ltd-signed) | draw.io's own export (--export, --crop) on the hidden desktop, settings in tools/drawio/home, no update check | Flowcharts, org charts, mind maps from words (laid out by the diagrams program; side branches leave a diamond's side and keep their own lane) or any .drawio, to PDF, PNG, SVG; OCR reads every box label |
| Statistics | R 4.6.1 (tools/r: CRAN's installer, MD5- and signature-checked, unpacked by innoextract (GPG-checked), never run); the scripts open in RStudio | base-R scripts run by Rscript --vanilla on the hidden desktop, R_USER/HOME/R_LIBS_USER in tools/r/home | Describe, t-test (+ Welch), ANOVA, correlation, chi-square, regression with plots; every number cross-checked against the statistics program's own sums |
| Papers & theses | LaTeX via Tectonic 0.17 (tools/tectonic; packages fetched once into tools/tectonic/cache); the .tex opens in Overleaf, TeXstudio, MiKTeX | Tectonic on the hidden desktop | A .tex compiled (problems with their line), or articles/theses from Markdown or Word: sections/chapters, lists, equations, tables, [@citations] with a .bib; checked for pages, title, every heading, no '??' or '[?]' |
| Ebooks | Calibre 9.15 (tools/calibre, unpacked from its MSI) | ebook-convert and ebook-meta on the hidden desktop, settings in tools/calibre/home | EPUB, Kindle AZW3, MOBI, PDF, DOCX, TXT, FB2 from Word, EPUB, PDF, HTML, Markdown; title, author, cover; book details read and changed (on a copy); each result opens as its format and holds the original's words |
| Audio editing | Audacity 3.7.9 (tools/audacity; 4.x dropped scripting) | the real Audacity on a hidden desktop, told what to do through its own scripting pipe (mod-script-pipe) | Podcast cleanup (pauses cut, compressor, loudness, limiter, fades), clips, tempo, pitch, peak normalize, WAV/MP3/FLAC/OGG/AIFF; 'make it 10% slower' works on the last result; measured by FFmpeg (EBU R128 loudness, pauses, length, peak, pitch by FFT) |
| Code editor | Visual Studio Code (the one installed on this PC) | its own files (.vscode/tasks.json, settings.json, launch.json, extensions.json) and its command line (code --list-extensions / --install-extension) | Any project here (Python, Node/TypeScript, Go, Rust, C++/CMake, .NET, Java, Android, PHP) set up for VS Code: build and test tasks that use the toolchains in tools/ (their settings folders kept in the project), debug configs, recommended extensions; checked by running the same build and test commands and reading every file back as JSON. Extensions listed; installing one or opening a folder waits for a yes |
| Python | PyCharm, VS Code; Python 3.11 in tools/python | its own .venv (made without pip, nothing downloaded) and unittest on the hidden desktop | A package, tests and pyproject.toml from words: .venv made, 5 tests passed, `python -m shop` run (Rs 22,000), every file compiles; any Python project tested (pytest if its .venv has it), each failure with file and line |
| Node.js / TypeScript | WebStorm, VS Code; the Node.js 24 on this PC (runs TypeScript itself) | node --test and node on the hidden desktop, no npm install | package.json, tsconfig.json, a TypeScript module, tests and a program: 5 tests passed, main.ts run (Rs 22,000); any package.json tested, failing tests named |
| PHP | XAMPP, Laravel, VS Code, PhpStorm; PHP 8.4.26 in tools/php (windows.php.net zip, SHA-256 equal on windows.php.net and in Scoop) | php -l, plain PHP tests and PHP's own web server on 127.0.0.1 only, php.ini never read | A website from words (classes, public/index.php, tests, composer.json): every file linted, 5 tests passed, the page served and read back over HTTP (Rs 22,000); any PHP project linted and tested with file and line |
| Archives | 7-Zip 26.03 (tools/7zip, from its signed MSI) | 7z.exe on the hidden desktop | Files and folders into .7z (AES-256 with a password, file names hidden too) or .zip; any archive tested or unpacked; checked: archive tests clean, every file with its size, unreadable without the password; the password never appears in a reply |
| Notes | Obsidian (its vaults are plain files) | Markdown notes, [[links]], a .canvas board and .obsidian settings written by code | A vault from words or from an outline (Markdown/Word, one note per heading): Home map, linked notes with tags, a daily note and template, a canvas board; every [[link]] and canvas card resolves |
| Music making | LMMS 1.3 (tools/lmms; GitHub SHA-256, unpacked by 7-Zip) | LMMS projects (.mmp) written by code, rendered by `lmms render` on the hidden desktop with its settings file in tools/lmms/home (-c), so nothing in the user folder | Songs from notes (TripleOscillator melody, kick drum on every beat) or 'lmms it' for the melody just written, to WAV/MP3/OGG/FLAC; checked by FFmpeg: length, no clipping, every note's pitch by FFT |
| Diagrams (Visio) | Microsoft Visio (not installed; the files open in Visio, LibreOffice Draw, draw.io) | .vsdx written by code (Visio 2013 XML: shapes, glued connectors, labels) from the diagrams program's layout; draw.io's CLI cannot write .vsdx | Flowcharts, org charts, mind maps as .vsdx; checked: well-formed parts, every shape and connector, and LibreOffice's Visio reader turns it into a PDF with every box label |
| Passwords | KeePassXC 2.7.12 portable (tools/keepassxc: SHA-256 = GitHub's and its .DIGEST, GPG-signed by the KeePassXC release key, Authenticode-signed) | keepassxc-cli with every password sent through a pipe (never on a command line, in a file or in a reply; the chat log on disk hides typed passwords) | Encrypted vaults (.kdbx, AES-256, unlocking tuned to ~1 s of work) with a master password, filled from a browser's password export (empty passwords get generated ones); strong passwords generated; checked by KeePassXC: every entry with its user name and password, a wrong master password refused |
| Automation | AutoHotkey v2.0.29 (tools/autohotkey; GitHub's and Scoop's SHA-256 agree) | .ahk scripts written by code, checked with AutoHotkey's /validate (loads, never runs) | Text expansions ('brb -> be right back') and hotkeys ('ctrl+alt+n opens notepad', 'win+shift+d types the date') from words; errors with their line; starting a script (live hotkeys on the user's keyboard) waits for a yes, 'autohotkey stop' ends it |
| C++ | CLion, Visual Studio, VS Code (they open a CMake folder as is); CMake 4.4.4 (tools/cmake: SHA-256 list GPG-signed by Kitware, cmake.exe Kitware-signed), Ninja 1.13.2 and LLVM-MinGW 20260922 (clang++, lld, libc++; GitHub SHA-256, Ninja's also equal to Scoop's) | cmake / ninja / ctest on the hidden desktop | A C++20 project from words (inventory library, a program, tests run by CTest, CMakePresets.json, compile_commands.json) configured, built with -Wall -Wextra -Wpedantic, tested and run; linked statically, so the .exe runs on any Windows PC (its imports read: Windows' own DLLs only); a CMakeLists.txt given is built with each error's file and line |
| Go | GoLand, VS Code; Go 1.27.1 in tools/go (Google's signed MSI, SHA-256 equal on go.dev and golang.google.cn, unpacked by msiexec /a) | go vet / test / build on the hidden desktop; module and build caches, settings and telemetry (turned off) in tools/go/home, GOTOOLCHAIN=local so no other Go is ever downloaded | A Go module from words (inventory package with tests, a command) vetted, 5 tests run, built to one .exe and run (Rs 22,000), gofmt-clean; a go.mod given is built with each error's file and line |
| Rust | RustRover, VS Code (rust-analyzer); Rust 1.99.0 in tools/rust/toolchain (the standalone windows-gnu MSI: SHA-256 and the Rust release key's GPG signature checked, unpacked by msiexec /a; rustup is not used because it adds itself to Windows' programs list; its own MinGW linker, so no Visual Studio) | cargo fmt / clippy / test / build on the hidden desktop, Cargo's home in tools/rust/home | A Cargo package from words (library with 5 unit tests, a program) formatted by rustfmt, clippy-clean with warnings as errors, tested, built in release mode and run (Rs 22,000); the .exe needs only Windows' own DLLs; a Cargo.toml given is built with each error's file and line |
| C# / .NET | Visual Studio 2026, Rider (they open the .slnx); .NET SDK 10.0.401 itself in tools/dotnet (SHA-512 from Microsoft's release metadata) | dotnet new / build / test / run / publish on the hidden desktop; DOTNET_CLI_HOME, NuGet packages and caches in tools/dotnet/home, telemetry and first-run off | A solution from words: class library + xUnit tests + a console app, an ASP.NET Core web API or a WinForms app; built, the 5 tests run, the console's total checked, the API called over HTTP (201/400/409/200), the WinForms window found by title; a single-file .exe on request; a broken solution answers with each error's file and line |
| Java | IntelliJ IDEA, Eclipse, NetBeans (they open pom.xml); Temurin JDK 25.0.4.1 (Adoptium SHA-256 + GPG) and Maven 3.10.0 (Apache SHA-512) in tools/ | mvn package on the hidden desktop, its local repository in tools/maven/home | A Maven project from words: classes, JUnit 5 tests, a runnable jar; checked by Maven's own test report (5 passed) and by running the jar; a broken project answers with the file and line |
| Flutter | Android Studio, VS Code; Flutter 3.47.6 SDK in tools/flutter (Google's zip, SHA-256 equal to Google's release list) | flutter create / analyze / test / build web on the hidden desktop; pub cache, settings, analytics (off) in tools/flutter_home (APPDATA/LOCALAPPDATA/PUB_CACHE pointed there) | The shop app from words: inventory class, a screen with the stock and its value, 5 unit tests + a widget test that finds 'Total value: Rs 22,000' on the screen; analysed clean; built for the web and served on 127.0.0.1; any pubspec.yaml analysed and tested with file and line |
| Android apps | Android Studio (opens the project as is); Google's Android SDK in tools/android/sdk (command-line tools SHA-256 = developer.android.com; platform 36, build-tools 37.0.0, platform-tools fetched by Google's sdkmanager, binaries Google-signed; only the Android SDK licence accepted, text in tools/android) + Gradle 9.8.0 (tools/gradle, gradle.org SHA-256) + the Android Gradle Plugin 9.4.1 | Gradle on the hidden desktop, caches in tools/gradle/home; ANDROID_PREFS_ROOT keeps Android's settings, debug key and analytics file in tools/android/home | An Android app from words (Java, the shop classes, a screen with the stock and its value, JUnit tests, the Gradle wrapper) built to a debug APK: unit tests from Gradle's report, package/version/SDK levels/launcher read back by aapt2, signature verified by apksigner, the classes found in its dex; a project given is built with each compile error's file and line. 'install it on my phone' looks for a USB phone in Windows' device list, then after a yes runs adb (this PC only, Wi-Fi discovery off) |
| Business intelligence | Power BI Desktop (not installed: it cannot be unpacked portably; the project opens in it) | a Power BI Project (PBIP) written by code: model.bim (typed columns, Power Query load of a copy of the sheet, DAX measures) and a PBIR report page | A CSV/Excel sheet into a model with a total per number column and a row count, and a page with a card, a column chart and a table; every report file validated against Microsoft's published JSON schemas (jsonschema, PyPI SHA-256 checked); every field a visual uses exists in the model; the card's value worked out from the sheet |
| Databases | PostgreSQL 18.6 (tools/postgres: EDB's zip, unsigned, so its bin/ was checked byte for byte against Maven Central's package); pgAdmin, DBeaver and DataGrip connect to it | a real server on 127.0.0.1 (a free port), data in tools/postgres/data, started for the job and stopped after; psql and pg_dump | A shop database from words (customers, products, orders, order items with keys and checks), sample rows, a sales report and a backup; CSV/Excel sheets imported with their types worked out; .sql files run. Checked by the database itself: the keys are there, wrong rows are refused, the report's sums equal Python's. A user's .sql file runs in psql's restricted mode, so its `\!` shell commands are refused |
| Databases | MySQL 9.7.2 LTS (tools/mysql: Oracle's MSI from cdn.mysql.com, SHA-256 = Scoop's manifest, MSI and programs Oracle-signed, no custom actions, unpacked by msiexec /a); MySQL Workbench, DBeaver, HeidiSQL open the scripts and backups | mysqld on 127.0.0.1 (a free port) with no option files, no X Protocol port and no binary log, data in tools/mysql/data, shut down after the job; mysql and mysqldump | The same shop database (with an ENUM status), sheet imports (datetime, bigint, decimal worked out) and .sql runs. Checked by the server: keys, wrong customer/price/status refused, report sums equal Python's. A .sql file goes in on the client's input with its local commands off (MySQL 9's default), so a `system` line cannot run anything |
| Databases | MongoDB Community Server 9.0.2 (tools/mongodb: MongoDB's signed MSI, SHA-256 = its .sha256, only a set-property custom action, unpacked by msiexec /a, debug symbols left out; the zip's programs are unsigned); PyMongo 4.18.2 (PyPI SHA-256, scanned); MongoDB Compass connects while it runs | mongod on 127.0.0.1 (a free port), data in tools/mongodb/data, shut down after the job | A shop database the MongoDB way (orders hold their items) with the server's own JSON-schema validators and a unique product name; CSV/Excel/JSON imports with numbers and dates typed. Checked by the server: negative price, duplicate name and wrong status refused; the aggregation report equals Python's sums; an Extended JSON backup reads back whole |

Apps that open a window even on their command line (MuseScore does) run on a separate Windows desktop that is never shown:
[harness/hidden_desktop.py](harness/hidden_desktop.py) starts them there inside a job object (on a timeout everything they started is ended), so no
window, splash or error box can reach the user's screen. A self-check, `where_am_i()`, starts a tiny program there that only prints the
desktop it runs on (`AIPC_Hidden`). MuseScore's settings and user folders are pointed into its portable folder, so nothing goes to
Documents or AppData (checked by the test).

Measured (2026-10-05): [tests/test_popular.py](tests/test_popular.py) 172/172 in 1048 s, then KeePassXC (3), Power BI (2) and Flutter (3) checks added and passed on their own; tests/test_apps.py 103/103 (OBS over a real local WebSocket, GitHub with
real git pushes into local stand-in repositories, the other services as fakes in [tests/popular_fakes.py](tests/popular_fakes.py);
Godot, arduino-cli, PrusaSlicer, FreeCAD, Octave, MuseScore, Audacity, Calibre, KiCad, Krita, OpenSCAD, LibreOffice, GIMP, QGIS, Shotcut, Tectonic, R, draw.io,
HandBrake, VS Code, Python, Node.js, PHP, 7-Zip, LMMS, LibreOffice's Visio reader, AutoHotkey, KeePassXC, CMake with clang, Go, Rust, the .NET SDK, the JDK with Maven, Gradle with the Android SDK, PostgreSQL, MySQL, MongoDB and RawTherapee really run).
pandas 3.0.6, matplotlib 3.11.2, ifcopenshell 0.9.0 and genanki 0.13.1 were added to the venv through tools/safe_wheels.py (PyPI
SHA-256 checked, scanned); lottie-web 5.13.0 is in tools/js (npm SHA-512 checked); Godot, arduino-cli, PrusaSlicer and FreeCAD were checked
against their release hashes (PrusaSlicer, Godot and FreeCAD are also code-signed; arduino-cli.exe is not signed); Octave against John W. Eaton's GPG signature.

## Files

```
harness/   agent.py (loop, lanes, verification, learning)   uia.py (fast UI Automation)   inputs.py (SendInput, focus)
           planner.py + prompts.py + llm.py (models)        skills.py (store, parameters, preconditions)
           safety.py   grounder.py (TinyClick client)   screen.py   apps.py   observe.py   cli.py   config.py
tests/     test_foundation.py  test_agent_offline.py  test_agent_llm.py  test_charmap.py  test_settings.py
           video agent: studio.py (orchestrator)  director.py (brief, search, plan)  editplan.py (resolve)
           jybuild.py (draft + edit map)  jy_export.py + jianying_driver.py (background export)  verify.py  fixer.py
           analyze.py + frames.py + audio.py (media)  kb.py (knowledge base)  jyres.py (what works here)  vlm.py
           conversation.py + quick_edits.py + explain.py (chat)  template.py (learn / fill templates)
           template_meta.py (a template's page, screenshot or words)  trends.py (title and hashtags -> techniques)
           office/: render.py + _com.py (Office in the background) themes.py docplan.py docx_build.py charts.py pptx_build.py
                    xlsx_build.py verify.py designer.py studio.py
                    editing chats: docchat.py (versions, undo, compare; Word) docmap.py docx_ops.py doc_parse.py edit_llm.py
                                   deckchat.py + pptx_ops.py (PowerPoint)   bookchat.py + book_parse.py + xlsx_map.py + xlsx_com.py (Excel)
                    projects: projectchat.py (several files, routing, data links, one history)   docx_data.py (linked tables / charts)   pdf_ops.py
tests/     office: test_docs.py  test_links.py  doc_conversations.py  deck_conversations.py  book_conversations.py  project_conversations.py  messy_books.py
harness/windows/   fs.py (scan, find, plans, the Recycle Bin, every step checked)   settings.py (registry, power, printer, start-up apps)
                   winparse.py (requests read by rules)   winchat.py (the conversation, journal, undo)
tests/     windows: test_win.py  win_conversations.py  win_sandbox.py (made-up folders)
harness/photo/     analyze.py (measures, faces, backdrop, subject, tilt, page corners)   ops.py (51 edits, each with its check)
                   photoparse.py (requests read by rules)   photochat.py (versions, replay for 'instead', compare, saving)
tests/     photos: test_photo.py  photo_conversations.py
harness/cad/       floorplan.py (the planner: bands, search, doors, reachability, first floor)   draft.py (the DXF: walls, doors, windows, furniture,
                   dimensions, labels, title block, schedule)   render.py (SVG -> headless Chrome PDF and PNG)   check.py (plan rules, DXF read back, sheet)
                   parts.py (plates, flanges, cut files, part rules)   units.py (feet-inches, marla, kanal)   cadparse.py   cadchat.py
harness/headless.py   headless Chrome (own profile in out\chrome_profile): print to PDF, screenshot, DOM
harness/hidden_desktop.py   run a program on a never-shown Windows desktop inside a job object (no window can reach the screen)
tests/     cad: test_cad.py  cad_conversations.py
harness/sound/     measure.py (loudness, noise, hum, rumble, clipping, pauses, pitch)   ops.py (31 changes, each with its check)
                   captions.py (cues, SRT/VTT/ASS, styles, burn-in check)   tts.py (Windows voices)   soundparse.py   soundchat.py
tests/     sound: test_sound.py  sound_conversations.py
harness/design/    kinds.py (sizes, palettes, type)   layouts.py (HTML/CSS for every kind and style)   render.py (prepare photos, render, self-measure)
                   check.py (details, overflow, safe area, overlaps, contrast, dpi, QR, faces, sizes)   designparse.py   designchat.py
tests/     design: test_design.py  design_conversations.py
harness/hub/       vault.py (DPAPI keys)   http.py (HTTPS, retries, fake transport)   oauth.py (Google PKCE, Microsoft device code, Zoom, Canva PKCE)
                   catalog.py (services and key steps)   services/ (slack, telegram, trello, notion, google, microsoft, hubspot, asana, jira,
                   zoom, whatsapp, figma, canva)   hubparse.py   hubchat.py (confirm before sending, read-backs, audit, undo, briefing)
tests/     hub: test_hub.py
harness/coding/    project.py (files, git, .venv, .vscode, running, edit blocks)   verify.py (risk scan, compile, tests, run, web in headless Chrome)
                   repomap.py (files and their functions for the model)   codechat.py (build, check, repair, versions, designs)
                   design2code.py (Figma's description -> HTML/CSS, fonts)   pptxtree.py (Canva's PowerPoint -> the same shape)
                   designcheck.py (measured against the design, pictures compared)   fromdesign.py (Figma / Canva -> a checked project)
tests/     coding: test_coding.py   designs to code: test_design2code.py  design2code_conversations.py  design_fixture.py  pptx_fixture.py
harness/social/    store.py (SQLite: posts, jobs, checkpoints, metrics, comments, audit)   runner.py (the queue, retries, the Windows task)
                   base.py (the connector contract, error kinds)   specs.py (each platform's rules)   text.py   prepare.py (media fitted)
                   mediahost.py (a temporary web address)   auth.py (sign-ins, renewals, setup steps)   tunnel_setup.py   report.py
                   socialparse.py   socialchat.py   platforms/ (meta: Facebook and Instagram, threads, youtube, tiktok, linkedin, xcom)
tests/     social: test_social.py  social_suite.py  social_fakes.py  social_fixture.py  social_conversations.py
harness/accounts/  money.py (paisa, lakh, words)   ledger.py (double entry, documents, stock, numbering)   reports.py (TB, P&L, BS, ageing, tax, verify)
                   documents.py (PDF invoices, FBR QR)   accountsparse.py   accountschat.py   fbr.py (FBR Digital Invoicing)
                   systems/ (sync engine; quickbooks, tally, xero, zoho; loop.py: localhost sign-in)
tests/     accounts: test_accounts.py  accounts_conversations.py  test_accounts_systems.py  accounts_fakes.py
harness/aipc/      THE ONE CHAT: chat.py (routing every message, steps, 'yes' handling, hand-offs, saved chats)   router.py (which program)
                   artifacts.py ('it', 'this video', 'the original')   lanes.py (the 14 programs' conversations)   voice.py (voice notes, Whisper)
                   telegram.py (your phone through your Telegram bot)
tests/     the one chat: test_aipc.py
harness/apps/      one module per program (ocr, pccare, diagrams, cite, quiz, ebook, media, printing, maps, notes)   appschat.py   ps/ocr.ps1
                   popular apps: unity, godot, premiere, photoshop, illustrator, aftereffects, obs (+ ws.py), gworkspace, github, spotify,
                   salesforce, mstodo, jupyter, docker, postman, revit; desktop apps: lightroom, anki, arduino, msproject, prusaslicer, freecad, matlab, musescore, audacity, calibre, kicad (+ sexpr, circuits), krita, openscad, libreoffice, gimp, qgis, shotcut, latex, rstats, drawio, visio, handbrake, rawtherapee, sevenzip, obsidian, lmms, autohotkey, keepassxc; coding: vscode, pycharm (Python), nodejs, php, clion (C++), goland (Go), rustrover (Rust), visualstudio (.NET), androidstudio, flutter, intellij (Java), postgres, mysql, mongodb, powerbi
tests/     apps: test_apps.py   popular: test_popular.py  popular_fakes.py
tools/     godot/  arduino/ (arduino-cli + AVR core, arduino-cli.yaml)  prusaslicer/ (app + data/ settings)  freecad/ (+ home/)  octave/ (+ home/)  gnupg/  7zip/  musescore-portable/  audacity/ (Portable Settings, temp)  calibre/ (+ home/)  kicad/ (+ home/)  krita/ (+ home/resources)  openscad/  libreoffice/ (+ home/)  gimp-portable/ (+ home/)  qgis/ (+ home/)  shotcut/  tectonic/ (+ cache/)  r/ (+ home/)  innoextract/  drawio/ (+ home/)  handbrake/  php/  autohotkey/  keepassxc/  llvm-mingw/  cmake/  ninja/  go/ (go/, home/)  rust/ (toolchain/, home/)  flutter/ + flutter_home/  powerbi/ (schemas/)  dotnet/ (+ home/)  jdk/  maven/ (+ home/)  android/ (sdk/, home/)  gradle/ (+ home/)  postgres/ (+ data/, home/)  mysql/ (+ data/, home/)  mongodb/ (+ data/, home/)  rawtherapee/ (+ home/)  lmms/ (+ home/)  ltspice/ (parked)  js/
harness/convert/   media.py (probe, describe, keyframes, black bars, interlacing, play-through)   presets.py (containers, targets and limits, encoders,
                   quality, why it won't play)   plan.py (timeline, copy or encode, sizes for limits, the filter graph)   encode.py (runs, samples,
                   quality search, retries, splitting, checks, VMAF)   record.py (the screen)   convparse.py   convchat.py
tests/     converter: test_convert.py  convert_conversations.py
harness/three/     house.py (CAD plan -> measured boxes)   make.py (jobs and checks: houses, titles, mockups, 3D files)   checks.py (silhouettes,
                   pictures, videos)   blender.py (portable Blender in the background)   threeparse.py   threechat.py (versions, the CAD lane for plans)
                   bl/ (inside Blender): common.py (materials and patterns, cameras that frame, engines, masks)   house_scene.py   text_scene.py
                   mockup_scene.py   model_scene.py
tests/     3D: test_three.py  three_conversations.py
aipc.py           THE ONE AI PC CHAT (talk, -m, --file, --voice, --resume, telegram)
studio.py         video agent CLI                 docs.py   documents CLI (Word, PowerPoint, Excel)     win.py   Windows files and settings CLI
photo.py          photo agent CLI (talk, batch, look)          cad.py   house plans and parts CLI (talk, draw)
sound.py          sound agent CLI (talk, look, batch)
design.py         design agent CLI (talk, make)
hub.py            business hub CLI (steps, connect, status, forget, talk)
social.py         social media CLI (steps, connect, status, queue, run, setup-tunnel, talk)
coder.py          coding agent CLI (talk)
convert.py        converter CLI (talk, look, batch, record)
three.py          3D lane CLI (talk)                tools/blender/   Blender 5.2.2 LTS (portable, SHA-256 checked)
jianying_export.py   export one draft           tools/safe_wheels.py   checked package downloads (SHA-256 vs PyPI, scan)
tinyclick_ui.py   TinyClick server and browser tester (http://127.0.0.1:8765), runs in .venv-xpu on the Arc GPU
bench_models.py   Nebius model benchmark          state/skills/   learned skills          runs/   traces and screenshots
```
