"""The Windows agent, from the command line: your files, folders and settings, done by code and checked on the disk
(nothing moves the mouse or types; no window is opened unless you ask to open a file).

  ai-pc windows                           a conversation about your own folders (Downloads, Documents,
                                                            Desktop, Pictures, Videos, Music, OneDrive)
  ai-pc windows -m "what's in my downloads?" -m "what's taking space?"
  ai-pc windows --look                    looking only: answers and plans, nothing changes
  ai-pc windows --resume                  continue the last chat (its undo history too)
  ai-pc windows --sandbox                 a made-up Downloads / Documents / Pictures inside the project and a
                                                            test branch of the registry for settings: try anything safely
  ai-pc windows --offline                 rules only, no model

Things to say: 'clean up my downloads' (shown first; 'yes' does it), 'organize my downloads', 'find my CV and move it to
documents', 'rename the photos from august by the date taken', 'make the second one my wallpaper', 'zip the PDFs folder',
'convert the word files in documents to pdf', 'merge the pdfs', 'what's in the recycle bin?', 'restore the first one',
'turn on dark mode', 'stop Teams from starting with Windows', 'history', 'undo', 'redo'.
Safety: nothing is ever deleted for good (the Recycle Bin, and it is never emptied), Windows / Program Files / AppData and
this project are never touched, big or removing changes wait for 'yes', and 'undo' puts anything back.
"""

import argparse
import sys
from pathlib import Path

from ai_pc.core.paths import ROOT

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the Windows agent: files, folders and settings by code")
    ap.add_argument("-m", "--say", action="append", default=[], help="a message (repeat for several); without it the chat is interactive")
    ap.add_argument("--resume", nargs="?", const="", default=None, help="continue the last chat, or the one with this id")
    ap.add_argument("--look", action="store_true", help="looking only: answers and plans, nothing changes")
    ap.add_argument("--sandbox", action="store_true", help="made-up folders inside the project and test settings")
    ap.add_argument("--offline", action="store_true", help="rules only, no model")
    a = ap.parse_args(argv)

    from ai_pc.windows.settings import Fake, Settings
    from ai_pc.windows.winchat import CHATS, WinChat

    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    kw = {"planner": planner, "read_only": a.look}
    if a.sandbox:
        from ai_pc.windows import sandbox as win_sandbox

        base = ROOT / "out" / "win" / "sandbox"
        chats = ROOT / "out" / "win" / "sandbox_chats"
        kw["settings"] = Settings(Fake(folder=base / "startup"))
        if a.resume is not None:
            chat = WinChat.load(a.resume or None, chats_dir=chats, **kw)
        else:
            sb = win_sandbox.build(base / "folders")
            chat = WinChat.start(
                places={"downloads": sb["downloads"], "documents": sb["documents"], "pictures": sb["pictures"]},
                roots=[base / "folders"],
                chats_dir=chats,
                **kw,
            )
        print(f"Sandbox: made-up folders in {base / 'folders'}; settings go to a test branch of the registry.")
    else:
        if a.resume is not None:
            try:
                chat = WinChat.load(a.resume or None, chats_dir=CHATS, **kw)
            except FileNotFoundError as e:
                sys.exit(str(e))
        else:
            chat = WinChat.start(**kw)
    names = ", ".join(Path(p).name for p in chat.state["places"].values())
    print(f"Chat {chat.state['id']} about {names}" + (" (looking only)" if a.look else "") + ". 'help' for ideas, 'quit' to leave.")
    try:
        if a.say:
            for msg in a.say:
                print(f"> {msg}")
                print(chat.say(msg), flush=True)
        else:
            while True:
                try:
                    msg = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if msg.lower() in ("quit", "exit", "q", "bye"):
                    break
                if msg:
                    print(chat.say(msg), flush=True)
    finally:
        chat.close()
        if a.sandbox:
            Fake.wipe()
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"(chat {chat.state['id']}: {len(chat.state['journal'])} change(s) journaled; 'ai-pc windows --resume' continues it; AI ${usd:.4f})")


if __name__ == "__main__":
    main()
