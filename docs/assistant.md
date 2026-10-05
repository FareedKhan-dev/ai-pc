# The one AI PC chat and the command bar

## The one AI PC chat: everything from one conversation, typed or a voice note

```
ai-pc chat                                  talk here (a line that is a file path sends it; 'voice <file>' sends a voice note)
ai-pc chat -m "add a glow effect to my video" --file me.mp4 -m "send it to slack #team" -m yes
ai-pc chat --voice note.m4a                 a voice note from your phone or a recorder
ai-pc chat --resume                         carry on the last chat ('it' still means what it meant)
ai-pc telegram                              your phone as the remote: messages, voice notes, photos, videos and documents
                                              you send your own Telegram bot come here, and the replies and files go back
ai-pc web                                   the chat as a page in your browser on this PC: type, attach, hold the mic to talk
ai-pc bar                                   the AI PC in the background: Ctrl+Alt+Space anywhere opens the command bar
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
| Which program ([src/ai_pc/assistant/router.py](../src/ai_pc/assistant/router.py)) | Rules first: words that name a program or its work, the kinds of the files sent, what the 88 program modules recognise by their own rules, and the conversation in progress ("make it stronger" stays with the video; after a Slack send, "make it darker" goes back to the photo). The cheap model is asked only when the rules cannot tell. A request in steps ("add a glow to my video, then send it to Slack") runs step by step. |
| 'it', 'this video', 'the original' ([src/ai_pc/assistant/artifacts.py](../src/ai_pc/assistant/artifacts.py)) | Every file sent and every file a program made is remembered with its kind: 'it' is the newest thing made, 'the video' the edited one, 'the original video' the one you sent, 'the plan' its PDF, a file's name finds it. A program's internal version file (v3.png) goes to other people as a copy with a clear name (car_edited.png). With no file sent, 'my car photo' is looked for in your Desktop, Downloads, Pictures, Videos, Music and Documents and offered as a numbered choice. |
| The programs ([src/ai_pc/assistant/lanes.py](../src/ai_pc/assistant/lanes.py)) | Each keeps its own conversation and its own rules: checks at every step, 'yes' before anything others will see (the 'yes' goes back to the program that asked, and the remaining steps then run), versions and undo ('undo' goes to the program in use). |
| Voice notes ([src/ai_pc/assistant/voice.py](../src/ai_pc/assistant/voice.py)) | Heard by the local Whisper (models/whisper/base, nothing leaves the PC); speech in another language comes back in English. Channel names said aloud ("Slack, general channel") are written #general. |
| Your phone ([src/ai_pc/assistant/telegram.py](../src/ai_pc/assistant/telegram.py)) | Your Telegram bot (set up once with 'ai-pc hub connect telegram'): only your own chat is listened to, strangers are ignored, messages from before the start are skipped, 'typing...' shows while work runs, and the files made come back (up to Telegram's 50 MB; larger ones are named with their place on the PC). |
| The page ([src/ai_pc/assistant/web.py](../src/ai_pc/assistant/web.py)) | Served on 127.0.0.1 only (no firewall question); each run has a secret the page sends with every request, so another web page cannot drive the chat; only the chat's own files can be opened through it; the microphone button records a voice note in the browser. |
| Safety | Passwords typed in requests, secret fields and generated passwords are hidden in the saved chats; keys never reach the model; nothing is posted, sent or shared without your 'yes'. If the AI model is not answering, the chat says so plainly and changes nothing. |

Measured (2026-10-05): [tests/integration/test_aipc.py](../tests/integration/test_aipc.py) 30/30 offline in 36 s (45 requests to the right program, steps,
references, photo -> Slack with the edited photo uploaded byte for byte, 'no' drops a send, a TTS voice note heard by Whisper,
the Telegram bridge end to end with a photo, a voice note and 'yes', a stranger ignored, a saved chat picked up, secrets hidden,
the page: served with its secret, a photo request done, its file opened, other files refused). Live, the request "hey can you create
a simple glow effect on my video" (a 16 s clip) was edited by the video agent through JianYing in about 4 minutes, and "please send
it to slack" then offered that edited video (not the original) and waited for a yes ($0.004 of AI).

### The command bar: Ctrl+Alt+Space anywhere

Double-click AI PC.lnk (or run `ai-pc bar`) once. Nothing opens: the AI PC waits in the background with an icon in
the tray. Then, in any program:

- Ctrl+Alt+Space opens the bar in the middle of the screen you are working on, ready to type. Enter sends, Esc (or a
  click elsewhere) hides it, Ctrl+Alt+Space again closes it. The conversation is the same one chat as above.
- Hold Ctrl+Alt+Space and talk; let go to send (or click the mic, Ctrl+M). Whisper on this PC hears it.
- What you are looking at comes along: Files selected in the File Explorer window in front (or on the desktop), or
  the document open in Word, Excel or PowerPoint in front, appear as chips ("From File Explorer: clip.mp4") and are
  'it' / 'this video' for the request, so selecting a video and saying "add a glow effect" just works. A request about
  something else ("turn on dark mode") is not handed them; several selected files go with "these" / "them" / "all".
  Files can also be dropped on the bar, attached (Ctrl+O), or pasted (Ctrl+V pastes copied files or a copied picture).
- While it works a thin line moves under the box and the bottom line says which program is busy and what it is
  doing ("Photos · Brighter ... · 0:04"). Close the bar and keep working: a notification says when it is done.
- Results come with a picture (photos, a frame of a video) and their files: click to open, show in the folder, or
  copy to paste anywhere (WhatsApp, an email, Explorer). Files leave with clear names (car_edited.png, not v3.png).
- Anything others will see waits for Yes: Yes / No buttons (Alt+Y / Alt+N). Ctrl+N starts a new chat; the bar
  carries on today's chat and starts afresh after 6 hours. Up recalls what you sent before. The pin keeps it open.
- Tray icon menu: Open, New chat, Start with Windows (off until you turn it on), Open the chats folder, Quit.

How it stays fast and safe ([src/ai_pc/assistant/bar.py](../src/ai_pc/assistant/bar.py), [shell.py](../src/ai_pc/assistant/shell.py),
[agent.py](../src/ai_pc/assistant/agent.py), [mic.py](../src/ai_pc/assistant/mic.py)):

| | |
|---|---|
| Fast | Everything is loaded before you ask (the chat, the 88 programs' rules, ~0.7 s at start); the bar is built once and only shown, measured 58-86 ms from the combo to the bar on screen; requests run one at a time on a worker so the bar never freezes; Whisper loads while you are still talking. |
| The combo | A Windows hotkey (RegisterHotKey): no keyboard hook, nothing watches your typing; 'still held?' is read only while the combo is down. If another program has Ctrl+Alt+Space, it uses Ctrl+Alt+A (then Ctrl+Alt+Q) and says so. Change it in out/aipc/bar.json ("hotkey": "ctrl+alt+space"). |
| Your screen | It never moves the mouse or types for you; it takes the keyboard only when you press the combo. What is selected in Explorer or open in Office is read, never changed. Started from the shortcut it runs from python.exe with a console that has no window, so the programs it runs (FFmpeg, Git, compilers) never flash a black window. One copy runs: starting it again just shows the bar. |
| The microphone | Opened only while you hold the combo or the mic is on (Windows' own recorder, 16 kHz, nothing installed); recordings stay in the chat's folder. |
| Look | Windows 11 style: rounded corners, follows your light / dark setting and accent colour ("theme": "light" / "dark" to fix one), sharp on high-DPI screens. |

Measured (2026-10-05): [tests/integration/test_bar.py](../tests/integration/test_bar.py) 52/52 in 25 s, with the real bar running on the hidden desktop
(never on your screen): the combo registered and pressed (a Windows message), the photo selected in Explorer brightened as 'it',
the reply with its picture and car_edited.png, holding the combo recording a voice note ("make it black and white", heard by
Whisper and done), 'send it to slack' waiting for Yes and the Yes uploading the edited photo, a file dropped on the bar, Esc, a
second start showing the running bar, New chat; the shortcut's start (pythonw -> python.exe with no console window) and one copy
running; pictures of the bar in out/_tests/bar/ui/. Not tested here, because they would show on your screen, use your microphone
or change your clipboard: the real Ctrl+Alt+Space on your desktop, the tray icon and its notifications, the microphone itself,
and Copy.
