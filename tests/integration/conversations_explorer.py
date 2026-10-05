"""Templates in a chat: which saved templates fit ("any template for eid with 4 clips?"), recutting an edit on one
("use the 1st", "use the slowmo hdr template", a pasted CapCut link), what the template's tags change (slow motion, the
greeting), and what stays the template's (its timing). Runs on the wedding edit of the 10-genre batch.

  .venv\\Scripts\\python.exe tests\\integration\\conversations_explorer.py [--offline]
Needs the templates slowmo_hdr (ai-pc video template add <its link>) and gym_hype in the library.
"""

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("conv_tests", HERE / "conversations.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
by_text = T.by_text

LINK = "https://www.capcut.com/template-detail/7644532345902533908"


def speeds(R):
    return [round(pc["speed"], 3) for c in R["clips"] for pc in c.get("pieces") or [] if pc.get("kind") == "video"]


def durations(R):
    return [round(c["end"] - c["start"], 3) for c in R["clips"]]


def slowmo(R):
    return len(R["clips"]) == 4 and abs(R["end"] - 14.58) < 0.1


TURNS = [
    (
        "any template for eid with 4 clips?",
        "catalog",
        lambda x: not x.new_version() and "slowmo_hdr" in x.reply and x.reply.index("slowmo_hdr") < x.reply.index("gym_hype"),
    ),
    (
        "use the 1st",
        "option",
        lambda x: slowmo(x.R1) and speeds(x.R1) and all(s < 0.6 for s in speeds(x.R1)) and by_text(x.R1, "sara & adam") and x.says("slowmo_hdr"),
    ),
    ("what template is this?", "question", lambda x: not x.new_version() and x.says("slowmo_hdr", "from its page")),
    ("add the greeting", "change", lambda x: by_text(x.R1, "eid mubarak") and durations(x.R1) == durations(x.R0)),
    (
        "no slow motion",
        "change",
        lambda x: all(abs(s - 1) < 0.01 for s in speeds(x.R1)) and durations(x.R1) == durations(x.R0) and by_text(x.R1, "eid mubarak"),
    ),
    ("more slow motion please", "change", lambda x: all(s < 0.6 for s in speeds(x.R1)) and durations(x.R1) == durations(x.R0)),
    ("make it 30 seconds", None, lambda x: not x.new_version() and x.says("template")),
    ("use the gym hype template", "change", lambda x: len(x.R1["clips"]) >= 40 and abs(x.R1["end"] - 58.3) < 0.5),
    ("undo", "undo", lambda x: slowmo(x.R1) and by_text(x.R1, "eid mubarak")),
    (f"{LINK} is this good for my clips?", "question", lambda x: not x.new_version() and x.says("SLOWMO HDR", "4 clips", "recut")),
    ("use the banana template", "ask", lambda x: not x.new_version() and x.says("no template called", "slowmo_hdr")),
    ("use the second template", "change", lambda x: len(x.R1["clips"]) >= 40),
    ("https://www.capcut.com/templates/eid-xyz", "impossible", lambda x: not x.new_version() and x.says("can't read that link")),
    (
        "switch to the gym hype template and make the title gold",
        "change",
        lambda x: len(x.R1["clips"]) >= 40 and any(e["style"]["color"] == T.GOLD for e in by_text(x.R1, "sara & adam")),
    ),
    (f"use this template {LINK}", "change", lambda x: slowmo(x.R1) and by_text(x.R1, "sara & adam")),
]

if __name__ == "__main__":
    T.CONVERSATIONS = {"explorer": ("agent_saraadamfo_181609", TURNS)}
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    summary, rows = T.run(["explorer"], planner)
    (T.ROOT / "out" / "video" / "chats" / "explorer_chat_report.json").write_text(
        json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
