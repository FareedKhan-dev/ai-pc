"""Third held-out set: 40 turns written after round 9 of fixes, run once to measure generalisation honestly.
.venv\\Scripts\\python.exe tests\\integration\\conversations_holdout3.py [--offline] [names...]
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("conv_tests", HERE / "conversations.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
QE = T.QE
by_text, music, genre, filters, trans, avg, fx, items, sfx = T.by_text, T.music, T.genre, T.filters, T.trans, T.avg, T.fx, T.items, T.sfx
TITLE, LABELS = T.TITLE, T.LABELS


def clip_time(R, word):
    return sum(c["end"] - c["start"] for c in R["clips"] if word in c["file"].lower())


def outline(es):
    return avg(float((e["style"].get("outline") or {}).get("width") or 0) for e in es)


HOLDOUT3 = {
    "road3": (
        "agent_road_195510",
        [
            (
                "first impressions: love the vibe but the place names are kinda hard to see",
                "change",
                lambda x: (
                    avg(e["style"]["size"] for e in x.texts(LABELS)) > avg(e["style"]["size"] for e in x.texts(LABELS, False))
                    or outline(x.texts(LABELS)) > outline(x.texts(LABELS, False))
                ),
            ),
            ("also what filter is on it?", "question", lambda x: x.says("baking") or x.says("烘培")),
            ("try something less warm", "change", lambda x: filters(x.R1) != filters(x.R0)),
            ("hmm no, put the warm one back", "restore", lambda x: filters(x.R1) == filters(x.c.resolved(0))),
            (
                "can the drop hit with a white flash and a shake",
                "change",
                lambda x: len(fx(x.R1, "shake")) > len(fx(x.R0, "shake")) and len(items(x.R1) - items(x.R0)) >= 1,
            ),
            ("how many places are labelled?", "question", lambda x: re.search(r"\b\d+\b", x.reply) and not x.new_version()),
            ("remove the 'GOLDEN HOUR' label", "change", lambda x: by_text(x.R0, "golden hour") and not by_text(x.R1, "golden hour")),
            ("make the whole thing 45 seconds", "change", lambda x: abs(x.R1["end"] - 45) <= 2.5),
            ("and give it a vintage film look", "change", lambda x: filters(x.R1) != filters(x.R0)),
            ("great, that's the one", "ack", lambda x: not x.new_version()),
        ],
    ),
    "wedding3": (
        "agent_saraadamfo_181609",
        [
            (
                "the couple's names should be bigger and in white",
                "change",
                lambda x: (
                    by_text(x.R1, "sara")
                    and all(e["style"]["color"] == "#FFFFFF" for e in by_text(x.R1, "sara"))
                    and avg(e["style"]["size"] for e in by_text(x.R1, "sara")) > avg(e["style"]["size"] for e in by_text(x.R0, "sara"))
                ),
            ),
            ("what's happening around the 30 second mark?", "question", lambda x: x.says("0:30")),
            ("slow down the part where they walk", "change", lambda x: any(o.get("value") == "slow" for o in x.ops("shot"))),
            ("add soft sparkles over the rings", "change", lambda x: len(items(x.R1) - items(x.R0)) >= 1),
            ("the music is a little too loud during the vows", "change", lambda x: music(x.R1)["volume"] < music(x.R0)["volume"] or x.new_version()),
            ("use a cross dissolve between every shot", None, lambda x: len(trans(x.R1)) >= len(x.R1["clips"]) - 1 and x.says("already")),
            ("too many now, only between sections", "change", lambda x: len(trans(x.R1)) < len(trans(x.R0))),
            ("what did you just change?", "history", lambda x: x.says("v")),
            ("undo that", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
            ("export please", "export", lambda x: x.says("export")),
        ],
    ),
    "gym3": (
        "agent_no_180359",
        [
            ("more punch on every beat in the drop", "change", lambda x: len(fx(x.R1, "zoom")) > len(fx(x.R0, "zoom"))),
            ("lol that's insane, tone it down a bit", "change", lambda x: len(fx(x.R1, "zoom")) < len(fx(x.R0, "zoom")) or x.new_version()),
            ("use the sweat close-up as the opening shot", "change", lambda x: x.R1["clips"][0]["file"] != x.R0["clips"][0]["file"]),
            ("what's the title say?", "question", lambda x: x.says("no excuses")),
            ("make it say 'NO DAYS OFF' instead", "change", lambda x: by_text(x.R1, "no days off") and not by_text(x.R1, "no excuses")),
            ("music louder and more aggressive", "change", lambda x: music(x.R1)["volume"] > music(x.R0)["volume"] or genre(x.R1) != genre(x.R0)),
            ("kill all the flashes", "change", lambda x: len(fx(x.R1, "flash")) < len(fx(x.R0, "flash"))),
            ("is the video under 60 seconds?", "question", lambda x: re.search(r"\d+\.\d s", x.reply) and not x.new_version()),
            ("make it 9:16 if it isn't already", None, lambda x: not x.new_version() and x.says("already")),
            ("awesome thanks!", "ack", lambda x: not x.new_version()),
        ],
    ),
    "tech4": (
        "agent_smart_181728",
        [
            ("the code screens look cheap, use less of them", "change", lambda x: clip_time(x.R1, "code") < clip_time(x.R0, "code")),
            ("start on the woman's eye shot", "change", lambda x: "eye" in x.R1["clips"][0]["file"]),
            ("what's the bpm?", "question", lambda x: x.says("120")),
            ("can the 'Smart App' title glow", None, lambda x: x.new_version() or "?" in x.reply),
            (
                "put 'Available on iOS and Android' at the end",
                "change",
                lambda x: by_text(x.R1, "available on ios") and by_text(x.R1, "download now"),
            ),
            ("make the feature words cyan", "change", lambda x: x.texts(LABELS) and all(e["style"]["color"] == "#00E5FF" for e in x.texts(LABELS))),
            ("what does it look like at 10 seconds?", "question", lambda x: x.says("0:10")),
            (
                "switch to a more corporate font",
                "change",
                lambda x: T.font([e for e in x.R1["edits"] if e["type"] == "text"]) != T.font([e for e in x.R0["edits"] if e["type"] == "text"]),
            ),
            ("compare this with version 2", "compare", lambda x: x.says("v2")),
            ("go back to version 2", "goto", lambda x: x.v1 == 2),
        ],
    ),
}

if __name__ == "__main__":
    T.CONVERSATIONS = HOLDOUT3
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    summary, rows = T.run(args or list(HOLDOUT3), planner)
    (T.ROOT / "out" / "video" / "chats" / "holdout3_report.json").write_text(
        json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
