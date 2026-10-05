"""Second held-out set: 50 turns written after round 6 of fixes, run once to measure generalisation honestly.
  .venv\\Scripts\\python.exe tests\\conversations_holdout2.py [--offline] [names...]
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
TITLE, LABELS, CAPS = T.TITLE, T.LABELS, T.CAPS


def clip_time(R, word):
    return sum(c["end"] - c["start"] for c in R["clips"] if word in c["file"].lower())


def voice(R):
    return next((e for e in R["edits"] if e["type"] == "audio" and "narration" in str(e.get("file", ""))), {})


HOLDOUT2 = {
    "cooking3": ("agent_easystirfr_183910", [
        ("can you tell me which music style you picked and why", "question", lambda x: x.says("chill")),
        ("honestly i'd prefer something more upbeat", "change", lambda x: genre(x.R1) not in (None, "chill")),
        ("the first step label comes in too late", None, lambda x: x.new_version() or "?" in x.reply),
        ("write 'Serves 2' in the bottom corner during the last step", "change", lambda x: by_text(x.R1, "serves 2")),
        ("the flames shot is my favourite, make it longer", "change", lambda x: clip_time(x.R1, "flame") + clip_time(x.R1, "asian") > clip_time(x.R0, "flame") + clip_time(x.R0, "asian")),
        ("what's the total duration now", "question", lambda x: re.search(r"\d+\.\d s", x.reply)),
        ("remove the swoosh sounds", "change", lambda x: len(sfx(x.R1)) < len(sfx(x.R0))),
        ("make all the text white with a black outline", "change", lambda x: all(e["style"]["color"] == "#FFFFFF" for e in x.R1["edits"] if e["type"] == "text")),
        ("go back two versions", "undo", lambda x: x.v1 == x.c.state["versions"][x.c.state["versions"][x.v0]["parent"]]["parent"]),
        ("that's good, render it", "export", lambda x: x.says("export")),
    ]),
    "estate3": ("agent_coastal_180718", [
        ("the aerial at the start is stunning but it's too short", "change", lambda x: x.R1["clips"][0]["end"] > x.R0["clips"][0]["end"] + 0.3),
        ("can you label the cabin shot 'Mountain Retreat'", "change", lambda x: by_text(x.R1, "mountain retreat")),
        ("what transition is used between the shots?", "question", lambda x: x.says("dissolve")),
        ("use a slower, softer one", "change", lambda x: avg(e["duration"] for e in trans(x.R1)) > avg(e["duration"] for e in trans(x.R0))),
        ("the gold text is hard to read on the bright sky", "change", lambda x: x.new_version()),
        ("add a soft vignette", "change", lambda x: len(fx(x.R1, "vignette")) > len(fx(x.R0, "vignette"))),
        ("make it 45 seconds for instagram", "change", lambda x: abs(x.R1["end"] - 45) <= 2.5),
        ("how many seconds is the terrace part?", "question", lambda x: not x.new_version() and len(x.reply) > 5),
        ("undo", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
        ("thanks, perfect", "ack", lambda x: not x.new_version()),
    ]),
    "car3": ("agent_unleashed_181048", [
        ("make the UNLEASHED title slam in harder", "change", lambda x: x.new_version() and by_text(x.R1, "unleashed")),
        ("add an engine roar sound when it accelerates", "ask", lambda x: not x.new_version() and x.says("can't")),
        ("ok raise the clip sound then", "change", lambda x: avg(c.get("volume", 1) for c in x.R1["clips"]) > avg(c.get("volume", 1) for c in x.R0["clips"])),
        ("what's on screen at 0:30", "question", lambda x: x.says("0:30")),
        ("the colour grade is too orange", "change", lambda x: filters(x.R1) != filters(x.R0) or x.new_version()),
        ("put the price on screen for the whole last shot", None, lambda x: x.new_version() or "?" in x.reply),
        ("replace the blur transitions with whip pans", "change", lambda x: {e["item"] for e in trans(x.R1)} != {e["item"] for e in trans(x.R0)}),
        ("and add whooshes on them", None, lambda x: len(x.reply) > 5),
        ("list the versions", "versions", lambda x: x.says("versions")),
        ("go back to v1", "goto", lambda x: x.v1 == 1),
    ]),
    "tech3": ("agent_smart_181728", [
        ("the hands typing shot is boring, cut it", "change", lambda x: clip_time(x.R1, "typing") < clip_time(x.R0, "typing")),
        ("what's the first thing people see?", "question", lambda x: x.says("0:00")),
        ("start with the futuristic devices animation instead", "change", lambda x: "futuristic" in x.R1["clips"][0]["file"]),
        ("make Fast, Secure and Smart appear bigger", "change", lambda x: avg(e["style"]["size"] for e in x.texts(LABELS)) > avg(e["style"]["size"] for e in x.texts(LABELS, False))),
        ("turn the music down when the callouts show", None, lambda x: x.new_version() or "?" in x.reply),
        ("add a glitch flash when each callout appears", None, lambda x: x.new_version() or "?" in x.reply),
        ("is the cta readable?", "question", lambda x: not x.new_version()),
        ("make it pop more at the end", "change", lambda x: x.new_version()),
        ("what changed since the beginning?", "compare", lambda x: x.says("v0")),
        ("export", "export", lambda x: x.says("export")),
    ]),
    "nature3": ("agent_thetwoseas_200445", [
        ("the narration is a bit quiet", "change", lambda x: voice(x.R1).get("volume", 1) > voice(x.R0).get("volume", 1)),
        ("and lower the music a touch more", "change", lambda x: music(x.R1)["volume"] < music(x.R0)["volume"]),
        ("what's the opening shot?", "question", lambda x: x.says("0:00")),
        ("use the sunflower field as the final image", "change", lambda x: "sunflower" in x.R1["clips"][-1]["file"]),
        ("subtitles in yellow please", "change", lambda x: all(e["style"]["color"] == T.YELLOW for e in x.texts(CAPS)) and x.texts(CAPS)),
        ("make the title appear later, around 3 seconds", "change", lambda x: min(e["window"][0] for e in x.texts(TITLE)) >= 2.5),
        ("add some floating dust particles over the waterfall", "change", lambda x: len(items(x.R1) - items(x.R0)) >= 1),
        ("is it too long for youtube shorts?", "question", lambda x: not x.new_version() and len(x.reply) > 5),
        ("make a 30 second cut for shorts", "change", lambda x: abs(x.R1["end"] - 30) <= 2.0 and x.R1["canvas"][1] > x.R1["canvas"][0]),
        ("the earlier subtitle colour was better", "restore", lambda x: all(e["style"]["color"] != T.YELLOW for e in x.texts(CAPS))),
    ]),
}

if __name__ == "__main__":
    T.CONVERSATIONS = HOLDOUT2
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    planner = None
    if "--offline" not in sys.argv:
        from harness.planner import ChatPlanner
        planner = ChatPlanner()
    summary, rows = T.run(args or list(HOLDOUT2), planner)
    (T.ROOT / "out" / "video" / "chats" / "holdout2_report.json").write_text(json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
