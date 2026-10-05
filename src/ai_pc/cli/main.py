"""ai-pc: one command for everything AI PC does.

Each command lives in its own module and is imported only when it runs, so the command line starts fast.
"""

import difflib
import importlib
import sys

from ai_pc import __version__

# command: (module, function, what it does)
COMMANDS = {
    "chat": ("ai_pc.cli.assistant", "chat", "the one AI PC chat: type requests, send files and voice notes"),
    "bar": ("ai_pc.assistant.bar", "main", "the Ctrl+Alt+Space command bar (waits in the background)"),
    "web": ("ai_pc.cli.assistant", "web", "the chat as a page in your browser on this PC"),
    "telegram": ("ai_pc.cli.assistant", "telegram", "answer your own Telegram bot from your phone"),
    "video": ("ai_pc.cli.video", "main", "edit videos from words (JianYing / CapCut, checked and exported)"),
    "jianying-export": ("ai_pc.cli.jianying_export", "main", "export a JianYing project to an mp4"),
    "office": ("ai_pc.cli.office", "main", "Word documents, PowerPoint decks and Excel workbooks from words"),
    "photo": ("ai_pc.cli.photo", "main", "edit photos, every change measured"),
    "sound": ("ai_pc.cli.sound", "main", "clean, level, cut, mix and caption recordings"),
    "design": ("ai_pc.cli.design", "main", "visiting cards, social posts, thumbnails, flyers"),
    "cad": ("ai_pc.cli.cad", "main", "house plans and engineering parts, drawn by code"),
    "3d": ("ai_pc.cli.three", "main", "3D houses from plans, 3D titles, product mockups (Blender)"),
    "convert": ("ai_pc.cli.convert", "main", "convert, shrink, cut and join videos and sound"),
    "windows": ("ai_pc.cli.windows", "main", "your files, folders and Windows settings"),
    "code": ("ai_pc.cli.code", "main", "projects written and changed by code, each version a git commit"),
    "accounts": ("ai_pc.cli.accounts", "main", "a small business's books: invoices, bills, stock, tax"),
    "hub": ("ai_pc.cli.hub", "main", "Slack, Teams, Outlook, Gmail, Trello, Notion and more"),
    "social": ("ai_pc.cli.social", "main", "Facebook, Instagram, Threads, YouTube, TikTok, LinkedIn and X"),
    "apps": ("ai_pc.cli.apps", "main", "88 more programs, a basic setup each, by conversation"),
    "agent": ("ai_pc.desktop.cli", "main", "operate any desktop program through its user interface"),
    "keys": ("ai_pc.cli.keys", "main", "API keys in this PC's encrypted vault"),
}
ALIASES = {"three": "3d", "win": "windows", "docs": "office", "coder": "code", "talk": "chat"}


def usage():
    width = max(map(len, COMMANDS))
    lines = [
        f"ai-pc {__version__}: the AI PC from the command line",
        "",
        "usage: ai-pc <command> [options]   (ai-pc <command> --help for its options)",
        "",
    ]
    lines += [f"  {name.ljust(width)}  {doc}" for name, (_, _, doc) in COMMANDS.items()]
    lines += ["", "With no command, 'ai-pc' starts the chat ('ai-pc -m \"...\"' sends it a message)."]
    return "\n".join(lines)


def _utf8_console():
    for stream in (sys.stdout, sys.stderr):  # replies carry names and symbols the console's code page may not have
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    _utf8_console()
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "-V", "--version")):
        argv = ["chat", *argv]  # 'ai-pc -m "..."' is the chat with a message
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-h", "--help", "help"):
        print(usage())
        return 0
    if cmd in ("-V", "--version", "version"):
        print(__version__)
        return 0
    cmd = ALIASES.get(cmd, cmd)
    if cmd not in COMMANDS:
        near = difflib.get_close_matches(cmd, COMMANDS, n=1)
        print(f"ai-pc: unknown command '{cmd}'" + (f" (did you mean '{near[0]}'?)" if near else ""), file=sys.stderr)
        print("run 'ai-pc --help' for the list", file=sys.stderr)
        return 2
    module, function, _ = COMMANDS[cmd]
    sys.argv = [f"ai-pc {cmd}", *rest]  # commands that read sys.argv themselves see only their own options
    result = getattr(importlib.import_module(module), function)(rest)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
