"""The coding agent, from the command line: projects written and changed by code, each version a git commit that was
checked (it compiles, its tests pass, it runs; a web page loads with no console errors), repaired by the model when a
check fails, and opened in VS Code only when you ask. Code that could change things on your PC runs only after a yes.

  ai-pc code talk                        a conversation ('quit' to leave)
  ai-pc code talk -m "make a python script that counts words, lines and characters in a text file" -m "run it"
  ai-pc code talk -m "open project word_counter" -m "add an option to list the 10 most common words"
  ai-pc code talk -m "build a one-page website for Khan Electronics with products and a contact form" -m "open it in VS Code"

Things to say: 'make a ... script / app / website', 'add ...', 'fix this error: <paste>', 'run it', 'run it with <args>', 'run the tests',
'open it in VS Code', 'show the code', 'explain the code', 'what changed?', 'undo', 'redo', 'history', 'list projects',
'open project <name or folder>'. Projects live in out\\code\\projects (each with its own .venv, git history and .vscode setup).
"""

import argparse
import sys

for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="the coding agent: projects written by code, each version checked")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("talk", help="a conversation about a project")
    t.add_argument("-m", "--say", action="append", default=[])
    a = ap.parse_args(argv)
    from ai_pc.coding.codechat import CodeChat
    from ai_pc.llm.planner import ChatPlanner

    planner = ChatPlanner()
    c = CodeChat.start(planner=planner)
    print(f"Coding chat {c.state['id']}. 'quit' to leave.")
    if a.say:
        for m in a.say:
            print(f"> {m}")
            print(c.say(m), flush=True)
    else:
        while True:
            try:
                m = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if m.lower() in ("quit", "exit", "q", "bye"):
                break
            if m:
                print(c.say(m), flush=True)
    print(f"(AI ${planner.cost()[1]:.4f})")


if __name__ == "__main__":
    main()
