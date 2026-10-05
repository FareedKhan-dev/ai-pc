# Windows: files, folders and settings

## Windows itself: files, folders and settings (programmatic)

```
ai-pc windows                                     a conversation about your own Downloads, Documents, Desktop, Pictures, Videos, Music, OneDrive
ai-pc windows --look                              looking only: answers and plans, nothing changes (a safe first run)
ai-pc windows -m "clean up my downloads" -m yes -m "find my CV and move it to documents" -m "make the second one my wallpaper" -m undo
ai-pc windows --resume                            the last chat again, its undo history too
ai-pc windows --sandbox                           made-up folders inside the project and a test branch of the registry
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
| [tests/integration/test_win.py](../../tests/integration/test_win.py): the guard, scanning, dates, duplicates, plans, the Recycle Bin round trip, zip safety, pictures, PDFs, sound, Word to PDF, settings, 42 phrasings | 38/38 | 9 s | none |
| [tests/integration/win_conversations.py](../../tests/integration/win_conversations.py): a 37-turn conversation, each turn checked on the disk; the Recycle Bin left clean | 37/37 | 63 s in all (35 turns by rules in 7 s; 2 by the model, ~20 s each) | $0.0007 |

A looking-only run on a real Downloads folder (899 files, 4.8 GB) found what the made-up folders could not. Clean-up had
treated identical files inside two unzipped asset packs as copies, and would have counted any old .exe as an installer.
It now keeps to the folder's own loose files: 11 items, 427 MB. The 125 identical files inside sub-folders are left
alone, and the reply says so.
