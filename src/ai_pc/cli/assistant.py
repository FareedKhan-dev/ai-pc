"""The one AI PC chat from the command line, the web page and Telegram: one conversation for everything this PC can do
(video, photos, Office, sound, design, CAD, 3D, converter, Windows, coding, accounts, Slack/Teams/Gmail and other work
apps, social media, and 88 more programs).

  ai-pc chat                               talk here: type requests; a line that is a file path sends that file;
                                           'voice <file>' sends a voice note; 'quit' to leave (the chat is kept)
  ai-pc chat -m "add a glow effect to my video" --file me.mp4 -m "send it to slack #team" -m yes
  ai-pc chat --voice note.m4a              a voice note from your phone or recorder
  ai-pc chat --resume                      carry on the last chat ('it' still means what it meant)
  ai-pc telegram                           answer your own Telegram bot: messages, voice notes and files from your phone
  ai-pc web                                the chat as a page in your browser on this PC (type, attach, hold the mic)
  --offline                                rules only, no AI model (programs that need the model will say so)
"""
import argparse
import sys
from pathlib import Path


def _planner(offline):
    if offline:
        return None
    from ai_pc.llm.planner import ChatPlanner
    return ChatPlanner()


def _open(resume, offline):
    from ai_pc.assistant.chat import AIPCChat
    planner = _planner(offline)
    chat = (AIPCChat.load(planner=planner) if resume else None) or AIPCChat.start(planner=planner)
    return chat, planner


def _common(ap):
    ap.add_argument("--resume", action="store_true", help="carry on the last chat")
    ap.add_argument("--offline", action="store_true", help="rules only, no AI model")


def _show(r):
    if getattr(r, "heard", None):
        print(f"(heard: \"{r.heard}\")")
    print(r)
    for f in getattr(r, "files", []) or []:
        print(f"  made: {f}")


def _cost(planner):
    return planner.cost()[1] if planner is not None else 0.0


def chat(argv=None):
    ap = argparse.ArgumentParser(prog="ai-pc chat", description="the one AI PC chat")
    ap.add_argument("-m", "--message", action="append", default=[], help="a message (repeat for a conversation)")
    ap.add_argument("--file", nargs="+", default=[], help="files sent with the first message")
    ap.add_argument("--voice", default=None, help="a voice note (its words are the message)")
    _common(ap)
    a = ap.parse_args(argv)
    files = [str(Path(f).resolve()) for f in a.file]
    for f in files:
        if not Path(f).is_file():
            print(f"not a file: {f}", file=sys.stderr)
            return 2
    c, planner = _open(a.resume, a.offline)
    if a.message or a.voice:
        first = True
        for m in a.message or [""]:
            r = c.say(m, files=files if first else (), voice=a.voice if first else None)
            first = False
            print(f"> {m or '(voice note)'}")
            _show(r)
        print(f"(chat {c.state['id']}; AI ${_cost(planner):.4f})")
        return 0
    print(f"AI PC chat {c.state['id']}. Type a request ('what can you do?' for the list); a file path sends that file; "
          f"'voice <file>' sends a voice note; 'quit' to leave.")
    pending = files
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
            _show(c.say(files=pending, voice=line[6:].strip().strip('"')))
            pending = []
            continue
        if Path(line).is_file():
            pending.append(str(Path(line).resolve()))
            print(f"(got {Path(line).name}: now say what to do with it)")
            continue
        _show(c.say(line, files=pending))
        pending = []
    print(f"(chat saved: {c.state['id']}; AI ${_cost(planner):.4f})")
    return 0


def web(argv=None):
    ap = argparse.ArgumentParser(prog="ai-pc web", description="the chat as a page in your browser on this PC (127.0.0.1 only)")
    ap.add_argument("--port", type=int, default=8770, help="the port on 127.0.0.1")
    _common(ap)
    a = ap.parse_args(argv)
    from ai_pc.assistant.web import serve
    c, _ = _open(a.resume, a.offline)
    print(f"AI PC chat {c.state['id']}: opening http://127.0.0.1:{a.port}/ (this PC only; Ctrl+C to stop)")
    try:
        serve(c, port=a.port, open_browser=True)
    except KeyboardInterrupt:
        print("stopped")
    return 0


def telegram(argv=None):
    ap = argparse.ArgumentParser(prog="ai-pc telegram", description="answer your own Telegram bot (set up with 'ai-pc hub connect telegram')")
    _common(ap)
    a = ap.parse_args(argv)
    from ai_pc.assistant.telegram import Bridge
    c, _ = _open(a.resume, a.offline)
    print(f"AI PC chat {c.state['id']} is answering your Telegram bot (Ctrl+C to stop).")
    try:
        Bridge(c).run()
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(chat())
