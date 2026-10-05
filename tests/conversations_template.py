"""A chat about a TEMPLATE edit: footage, music, texts and format change; the template's timing never does, and
asks to change it (length, pacing) are refused with the reason.

  .venv\\Scripts\\python.exe tests\\conversations_template.py <session draft of a template edit> [--offline]
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("conv_tests", HERE / "conversations.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
music, genre = T.music, T.genre


def durations(R):
    return [round(c["end"] - c["start"], 3) for c in R["clips"]]


def same_timing(x):
    return durations(x.R1) == durations(x.R0)


TURNS = [
    ("what template is this?", "question", lambda x: x.says("template") and not x.new_version()),
    ("start with the sunset", "change", lambda x: "sunset" in x.R1["clips"][0]["file"] and same_timing(x)),
    ("no motorcycle shots", "change", lambda x: not any("motorcycle" in c["file"] for c in x.R1["clips"]) and same_timing(x)),
    ("chill music instead", "change", lambda x: genre(x.R1) == "chill" and same_timing(x)),
    ("make it 30 seconds", None, lambda x: not x.new_version() and x.says("template")),
    ("faster cuts please", None, lambda x: not x.new_version() and x.says("template")),
    ("make the title gold", "change", lambda x: any(e["style"]["color"] == T.GOLD for e in x.R1["edits"] if e["type"] == "text") and same_timing(x)),
    ("how long is it?", "question", lambda x: x.says("58")),
    ("undo", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
]

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("give the draft of a template edit (studio.py new ... --template NAME makes one)")
    T.CONVERSATIONS = {"template": (args[0], TURNS)}
    planner = None
    if "--offline" not in sys.argv:
        from harness.planner import ChatPlanner
        planner = ChatPlanner()
    summary, rows = T.run(["template"], planner)
    (T.ROOT / "out" / "video" / "chats" / "template_chat_report.json").write_text(json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1),
                                                                               encoding="utf-8")
