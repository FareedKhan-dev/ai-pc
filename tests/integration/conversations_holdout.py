"""Held-out editing conversations: 50 turns written AFTER the rules were tuned on tests/integration/conversations.py, in other words,
to measure how the chat generalises (not to tune on). Same checks and invariants as conversations.py.

  .venv\\Scripts\\python.exe tests\\integration\\conversations_holdout.py [--offline] [names...]
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("conv_tests", HERE / "conversations.py")
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
QE = T.QE
by_text, music, genre, filters, trans, avg, fx, items, sfx, files = T.by_text, T.music, T.genre, T.filters, T.trans, T.avg, T.fx, T.items, T.sfx, T.files
TITLE, LABELS = T.TITLE, T.LABELS


def anim(x, ids, kind="intro", after=True):
    R = x.R1 if after else x.R0
    return {e.get("item") for e in R["edits"] if e["type"] == "animation" and e.get("kind") == kind and e.get("on") in ids}


HOLDOUT = {
    "road2": ("agent_road_195510", [
        ("yo the opening feels slow, can we get to the good stuff faster?", "change", lambda x: x.R1["end"] < x.R0["end"] - 0.5
         or len(x.R1["clips"]) > len(x.R0["clips"])),
        ("what's the very first shot?", "question", lambda x: x.says("0:00")),
        ("swap the music for something more chill and lofi", "change", lambda x: genre(x.R1) == "chill"),
        ("nah that's too sleepy, go back to the previous song", "restore", lambda x: genre(x.R1) == "pop"),
        ("make every label pop in with a bounce", "change", lambda x: anim(x, {e["id"] for e in x.texts(LABELS)}) != anim(x, {e["id"] for e in x.texts(LABELS, False)}, after=False)),
        ("and make them a little smaller", "change", lambda x: avg(e["style"]["size"] for e in x.texts(LABELS)) < avg(e["style"]["size"] for e in x.texts(LABELS, False))),
        ("remove the light leaks", "change", lambda x: len(fx(x.R1, "leak")) < len(fx(x.R0, "leak"))),
        ("is the title readable on a phone?", "question", lambda x: not x.new_version() and len(x.reply) > 10),
        ("put 'SUMMER 2026' as the opening title", "change", lambda x: by_text(x.R1, "summer 2026") and by_text(x.R1, "summer 2026")[0]["window"][0] < 3),
        ("export the vertical one", "export", lambda x: x.says("export")),
    ]),
    "gym2": ("agent_no_180359", [
        ("the beat drop needs to hit harder", "change", lambda x: x.new_version()),
        ("what effects are on screen at 0:20?", "question", lambda x: x.says("0:20")),
        ("lose the chromatic stuff", "change", lambda x: len(fx(x.R1, "glitch")) < len(fx(x.R0, "glitch"))),
        ("speed up the whole thing a little", "change", lambda x: x.new_version()),
        ("the text at the end should say NEVER QUIT", "change", lambda x: by_text(x.R1, "never quit") and by_text(x.R1, "no excuses")),
        ("make the music 20% quieter", "change", lambda x: music(x.R1)["volume"] < music(x.R0)["volume"]),
        ("zyada shake daalo drop pe", "change", lambda x: len(fx(x.R1, "shake")) > len(fx(x.R0, "shake")) or
         avg(e.get("strength", 0) for e in fx(x.R1, "shake")) > avg(e.get("strength", 0) for e in fx(x.R0, "shake"))),
        ("why is it so dark?", "question", lambda x: x.says("look") and not x.new_version()),
        ("brighten it up a bit", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("compare with the first version", "compare", lambda x: x.says("v0")),
    ]),
    "wedding2": ("agent_saraadamfo_181609", [
        ("the intro title should fade in slowly", "change", lambda x: any("fade" in QE.item_words(e.get("item")) and e["window"][1] - e["window"][0] >= 1.0
                                                                             for e in x.R1["edits"] if e["type"] == "animation" and e.get("on") in {t["id"] for t in x.texts(TITLE)})),
        ("what's playing at the end?", "question", lambda x: len(x.reply) > 10 and not x.new_version()),
        ("add the date 12.06.2026 under the names", "change", lambda x: by_text(x.R1, "12.06.2026")),
        ("can we have more slow motion overall", "change", lambda x: x.new_version()),
        ("the ring shot should be the very last thing", "change", lambda x: "ring" in x.R1["clips"][-1]["file"]),
        ("use warmer, creamier tones", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("kill the grain please", "change", lambda x: len(fx(x.R1, "grain")) < len(fx(x.R0, "grain"))),
        ("what does the ending look like now?", "question", lambda x: not x.new_version() and len(x.reply) > 10),
        ("perfect!! thank you so much", "ack", lambda x: not x.new_version()),
        ("actually, one more: make the names gold", "change", lambda x: x.texts(TITLE) and all(e["style"]["color"] == T.GOLD for e in x.texts(TITLE))),
    ]),
    "sports2": ("agent_match_195204", [
        ("flash the screen white when the goal goes in", "change", lambda x: len(items(x.R1) - items(x.R0)) >= 1 or len(fx(x.R1, "flash")) > len(fx(x.R0, "flash"))),
        ("the score card at the end is too small", "change", lambda x: by_text(x.R1, "2 - 1") and max(e["style"]["size"] for e in by_text(x.R1, "2 - 1"))
         > max(e["style"]["size"] for e in by_text(x.R0, "2 - 1"))),
        ("show the penalty twice", "change", lambda x: any(str(c["id"]).startswith("mo") and "penalty" in c["file"] for c in x.R1["clips"])),
        ("make the transitions snappier", "change", lambda x: avg(e["duration"] for e in trans(x.R1)) < avg(e["duration"] for e in trans(x.R0))),
        ("how many shots are in it?", "question", lambda x: re.search(r"\b\d+ shots\b", x.reply)),
        ("drop the music volume during the replay", None, lambda x: x.new_version() or "?" in x.reply),
        ("add a riser before the goal", "change", lambda x: len(sfx(x.R1)) > len(sfx(x.R0))),
        ("undo the last two changes", "undo", lambda x: x.v1 == x.c.state["versions"][x.c.state["versions"][x.v0]["parent"]]["parent"]),
        ("what's different from the original?", "compare", lambda x: x.says("v0")),
        ("ok send it", "export", lambda x: x.says("export")),
    ]),
    "party2": ("agent_saturday_200044", [
        ("the DJ shots are the best, use more of those", "change", lambda x: sum("dj" in c["file"] for c in x.R1["clips"]) > sum("dj" in c["file"] for c in x.R0["clips"])),
        ("and start with the crowd jumping", "change", lambda x: "jump" in x.R1["clips"][0]["file"]),
        ("colors should feel neon", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("rgb hits on every beat in the drop", "change", lambda x: len(fx(x.R1, "glitch")) > len(fx(x.R0, "glitch"))),
        ("too much now, just on the downbeats", "change", lambda x: len(fx(x.R1, "glitch")) < len(fx(x.R0, "glitch"))),
        ("what's the font of 'see you next week'?", "question", lambda x: x.says("font")),
        ("make 'see you next week' bigger and pink", "change", lambda x: by_text(x.R1, "see you next week") and all(e["style"]["color"] == "#FF4FA3" for e in by_text(x.R1, "see you next week"))),
        ("remove the vignette and the grain", "change", lambda x: len(fx(x.R1, "vignette")) < len(fx(x.R0, "vignette")) and len(fx(x.R1, "grain")) < len(fx(x.R0, "grain"))),
        ("how long is the video?", "question", lambda x: re.search(r"\d+\.\d s", x.reply)),
        ("go back to v3", "goto", lambda x: x.v1 == 3),
    ]),
}

if __name__ == "__main__":
    T.CONVERSATIONS = HOLDOUT
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    summary, rows = T.run(args or list(HOLDOUT), planner)
    out = T.ROOT / "out" / "video" / "chats" / "holdout_report.json"
    import json
    out.write_text(json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
