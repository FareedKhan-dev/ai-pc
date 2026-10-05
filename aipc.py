"""The AI PC chat: one conversation for everything this PC can do (video, photos, Office, sound, design, CAD, 3D,
converter, Windows, coding, accounts, Slack/Teams/Gmail and other work apps, social media, and 88 more programs).

  aipc.py                                    talk here: type requests; a line that is a file path sends that file;
                                             'voice <file>' sends a voice note; 'quit' to leave (the chat is kept)
  aipc.py -m "add a glow effect to my video" --file me.mp4 -m "send it to slack #team" -m yes
  aipc.py --voice note.m4a                   a voice note from your phone or recorder
  aipc.py --resume                           carry on the last chat ('it' still means what it meant)
  aipc.py telegram                           answer your own Telegram bot: messages, voice notes and files from your phone
  aipc.py web                                the chat as a page in your browser on this PC (type, attach, hold the mic)
  aipc.py bar                                the AI PC in the background: press Ctrl+Alt+Space anywhere to ask, hold it to talk
                                             (files selected in File Explorer come along; tray icon: New chat, Start with
                                             Windows, Quit); 'aipc.py bar --shortcut' makes 'AI PC.lnk' to pin to Start
  --offline                                  rules only, no AI model (programs that need the model will say so)
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _planner(offline):
    if offline:
        return None
    from harness.planner import ChatPlanner
    return ChatPlanner()


def _show(r):
    if getattr(r, "heard", None):
        print(f"(heard: \"{r.heard}\")")
    print(r)
    for f in getattr(r, "files", []) or []:
        print(f"  made: {f}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "bar":
        from harness.aipc.bar import main as bar
        return bar(sys.argv[2:])
    ap = argparse.ArgumentParser(description="the one AI PC chat")
    ap.add_argument("cmd", nargs="?", choices=["talk", "telegram", "web"], default="talk")
    ap.add_argument("--port", type=int, default=8770, help="web: the port on 127.0.0.1")
    ap.add_argument("-m", "--message", action="append", default=[], help="a message (repeat for a conversation)")
    ap.add_argument("--file", nargs="+", default=[], help="files sent with the first message")
    ap.add_argument("--voice", default=None, help="a voice note (its words are the message)")
    ap.add_argument("--resume", action="store_true", help="carry on the last chat")
    ap.add_argument("--offline", action="store_true", help="rules only, no AI model")
    a = ap.parse_args()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from harness.aipc.chat import AIPCChat
    planner = _planner(a.offline)
    chat = (AIPCChat.load(planner=planner) if a.resume else None) or AIPCChat.start(planner=planner)
    if a.cmd == "telegram":
        from harness.aipc.telegram import Bridge
        print(f"AI PC chat {chat.state['id']} is answering your Telegram bot (Ctrl+C to stop).")
        try:
            Bridge(chat).run()
        except KeyboardInterrupt:
            print("stopped")
        return
    if a.cmd == "web":
        from harness.aipc.web import serve
        print(f"AI PC chat {chat.state['id']}: opening http://127.0.0.1:{a.port}/ (this PC only; Ctrl+C to stop)")
        try:
            serve(chat, port=a.port, open_browser=True)
        except KeyboardInterrupt:
            print("stopped")
        return
    files = [str(Path(f).resolve()) for f in a.file]
    for f in files:
        if not Path(f).is_file():
            sys.exit(f"not a file: {f}")
    if a.message or a.voice:
        first = True
        for i, m in enumerate(a.message or [""]):
            r = chat.say(m, files=files if first else (), voice=a.voice if first else None)
            first = False
            print(f"> {m or '(voice note)'}")
            _show(r)
        usd = planner.cost()[1] if planner is not None else 0.0
        print(f"(chat {chat.state['id']}; AI ${usd:.4f})")
        return
    print(f"AI PC chat {chat.state['id']}. Type a request ('what can you do?' for the list); a file path sends that file; "
          f"'voice <file>' sends a voice note; 'quit' to leave.")
    pending_files = files
    while True:
        try:
            line = input("> ").strip().strip('"')
        except (EOFError, KeyboardInterrupt):
            break
        if line.lower() in ("quit", "exit", "q", "bye"):
            break
        if not line:
            continue
        if line.lower().startswith("voice "):
            _show(chat.say(files=pending_files, voice=line[6:].strip().strip('"')))
            pending_files = []
            continue
        if Path(line).is_file():
            pending_files.append(str(Path(line).resolve()))
            print(f"(got {Path(line).name}: now say what to do with it)")
            continue
        _show(chat.say(line, files=pending_files))
        pending_files = []
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"(chat saved: {chat.state['id']}; AI ${usd:.4f})")


if __name__ == "__main__":
    main()
