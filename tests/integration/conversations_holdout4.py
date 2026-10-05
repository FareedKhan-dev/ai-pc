"""Fourth held-out set: 30 turns written after round 14 of fixes, run once to measure generalisation honestly.
  .venv\\Scripts\\python.exe tests\\integration\\conversations_holdout4.py [--offline] [names...]
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


def bpm(R):
    f = str(music(R).get("file", ""))
    return int(f.split("_")[2]) if f.startswith("music_") else 0


def texts(R):
    return [e for e in R["edits"] if e["type"] == "text"]


HOLDOUT4 = {
    "party4": ("agent_saturday_200044", [
        ("can the whole thing feel more like a music video?", None, lambda x: x.new_version() or "?" in x.reply),
        ("put the jumping girls right at the drop", "change", lambda x: any("jumping" in c["file"] and c["start"] - 0.1 <= (x.plan().get("_rhythm") or {}).get("drop", -9) < c["end"]
                                                                           for c in x.R1["clips"])),
        ("what happens right after the drop?", "question", lambda x: x.says("drop")),
        ("add a glitch transition there", None, lambda x: len(x.reply) > 5),
        ("the see you next week text is boring, make it neon pink", "change", lambda x: by_text(x.R1, "see you next week") and
         all(e["style"]["color"] in ("#FF4FA3", "#FF1F8E") for e in by_text(x.R1, "see you next week"))),
        ("can I get a version without any text?", "change", lambda x: not texts(x.R1)),
        ("hmm actually bring the text back", None, lambda x: len(texts(x.R1)) >= 2),
        ("how many clips from the dj are in it?", "question", lambda x: re.search(r"\b\d+\b", x.reply) and not x.new_version()),
        ("speed up the music a little", "change", lambda x: bpm(x.R1) > bpm(x.R0)),
        ("perfect, ship it", "export", lambda x: x.says("export")),
    ]),
    "estate4": ("agent_coastal_180718", [
        ("the title should say 'Villa Azul' and use a classy serif", "change", lambda x: by_text(x.R1, "villa azul") and T.font(by_text(x.R1, "villa azul")) != T.font(by_text(x.R0, "coastal living"))),
        ("what's the second shot?", "question", lambda x: len(x.reply) > 10 and not x.new_version()),
        ("drop the horse shots", "change", lambda x: len(T.files(x.R1)) < len(T.files(x.R0))),
        ("make the music swell at the end", None, lambda x: x.new_version() or "?" in x.reply),
        ("add 'Price on request' under the title", "change", lambda x: by_text(x.R1, "price on request")),
        ("can the labels sit a little lower", "change", lambda x: avg(e["position"][1] for e in x.texts(LABELS)) < avg(e["position"][1] for e in x.texts(LABELS, False))),
        ("use a warmer, sunset grade but keep it subtle", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("show me the version history", "versions", lambda x: x.says("v0")),
        ("I liked v1's title better", "restore", lambda x: by_text(x.R1, "villa azul")),
        ("ok good, export the 16:9 one", "export", lambda x: x.says("export")),
    ]),
    "cooking4": ("agent_easystirfr_183910", [
        ("make the steps appear with a typewriter effect", "change", lambda x: {e.get("item") for e in x.R1["edits"] if e["type"] == "animation" and e.get("on") in {t["id"] for t in x.texts(LABELS)}}
         != {e.get("item") for e in x.R0["edits"] if e["type"] == "animation" and e.get("on") in {t["id"] for t in x.texts(LABELS, False)}}),
        ("can the eggs part be faster?", None, lambda x: x.new_version() or "?" in x.reply),
        ("what's the ending text?", "question", lambda x: x.says("save this recipe") or x.says("easy stir fry")),
        ("swap the order of step 2 and step 3", None, lambda x: x.new_version() or "?" in x.reply),
        ("the music is too sleepy", "change", lambda x: genre(x.R1) not in (None, "chill") or music(x.R1).get("file") != music(x.R0).get("file")),
        ("add a little zoom when the fries go in", "change", lambda x: len(fx(x.R1, "zoom")) > len(fx(x.R0, "zoom"))),
        ("make the cta bigger", "change", lambda x: avg(e["style"]["size"] for e in by_text(x.R1, "save this recipe")) > avg(e["style"]["size"] for e in by_text(x.R0, "save this recipe"))),
        ("what did I ask for so far?", None, lambda x: len(x.reply) > 10 and not x.new_version()),
        ("undo the last 3 changes", "undo", lambda x: x.v1 == x.c.state["versions"][x.c.state["versions"][x.c.state["versions"][x.v0]["parent"]]["parent"]]["parent"]),
        ("thanks!", "ack", lambda x: not x.new_version()),
    ]),
}

if __name__ == "__main__":
    T.CONVERSATIONS = HOLDOUT4
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    summary, rows = T.run(args or list(HOLDOUT4), planner)
    (T.ROOT / "out" / "video" / "chats" / "holdout4_report.json").write_text(json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
