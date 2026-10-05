"""Editing conversations: ~110 turns over the 10 one-minute batch edits, the way clients really talk to an editor.

Questions in the middle of revisions, compound asks, typos and chat shorthand, Roman Urdu, undo / redo / "go back to v2",
one element back from an earlier version ("the old music was better", "the previous title FONT was nicer"), picking
from offered options ("try the first one", "1 and 3"), finishing a half-answered ask, vague asks, impossible asks.
Every turn is checked twice: the kind of turn the system took (intent) and what really changed on the new timeline
(or what the answer says).

  .venv\\Scripts\\python.exe tests\\conversations.py              rules + the cheap model for what they do not cover
  .venv\\Scripts\\python.exe tests\\conversations.py --offline    rules only (no model calls)
  .venv\\Scripts\\python.exe tests\\conversations.py road gym     only some conversations
Drafts go to a scratch folder (not JianYing's project list); nothing is exported. Results: out/video/chats/test_report.json
"""
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from harness import quick_edits as QE  # noqa: E402
from harness.conversation import Conversation  # noqa: E402

SCRATCH = ROOT / "out" / "video" / "chats" / "test_drafts"   # JianYing drafts of every test version (wiped at each run)
TEST_CHATS = ROOT / "out" / "video" / "chats" / "test"           # the test conversations' saved state (wiped at each run)
RED, YELLOW, GOLD, WHITE = "#E53935", "#FFD600", "#E8C547", "#FFFFFF"


# ------------------------------------------------------------------------------------------------ evidence of one turn
class X:
    def __init__(self, c, v0, v1, R0, R1, reply, turn):
        self.c, self.v0, self.v1, self.R0, self.R1, self.reply, self.turn = c, v0, v1, R0, R1, reply, turn

    def plan(self, after=True):
        return self.c.state["versions"][self.v1 if after else self.v0]["plan"]

    def texts(self, who=None, after=True):
        R = self.R1 if after else self.R0
        es = [e for e in R["edits"] if e["type"] in ("text", "captions")]
        if who is None:
            return es
        ids = {e["id"] for e in QE.pick_texts(self.plan(after), who)}
        return [e for e in es if e["id"] in ids]

    def says(self, *words):
        return all(w.lower() in self.reply.lower() for w in words)

    def ops(self, kind=None):
        return [o for o in self.turn.get("ops") or [] if kind is None or o.get("op") == kind]

    def new_version(self):
        return self.v1 != self.v0


def by_text(R, words):
    w = " ".join(words.lower().split())
    return [e for e in R["edits"] if e["type"] == "text" and w in " ".join(e["text"].lower().split())]


def music(R):
    return next((e for e in R["edits"] if e["id"] == "music"), {})


def genre(R):
    f = str(music(R).get("file", ""))
    return f.split("_")[1] if f.startswith("music_") else None


def filters(R):
    return sorted(e["item"] for e in R["edits"] if e["type"] == "filter")


def trans(R):
    return [e for e in R["edits"] if e["type"] == "transition"]


def avg(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def fx(R, kind):
    if kind in ("shake", "zoom"):
        return [e for e in R["edits"] if e["type"] == kind]
    return [e for e in R["edits"] if e["type"] == "effect" and kind in QE._kinds_R(e)]


def items(R):
    return {e.get("item") for e in R["edits"] if e.get("item")}


def sfx(R):
    return [e for e in R["edits"] if e.get("sfx")]


def files(R):
    return {c["file"].lower() for c in R["clips"]}


def font(es):
    return sorted({e["style"].get("font") for e in es})


TITLE, LABELS, CAPS = {"role": "title"}, {"role": "label"}, {"role": "caption"}

# ------------------------------------------------------------------------------------------------ the conversations
# (message, intents the turn must include (None = any), check(x) -> bool)
CONVERSATIONS = {
    "road": ("agent_road_195510", [  # travel reel, 9:16
        ("hey what font did you use for the title?", "question", lambda x: x.says("thunder")),
        ("make it red and a bit bigger", "change", lambda x: x.texts(TITLE) and all(e["style"]["color"] == RED for e in x.texts(TITLE))
         and avg(e["style"]["size"] for e in x.texts(TITLE)) > avg(e["style"]["size"] for e in x.texts(TITLE, False))),
        ("hmm actually go back", "undo", lambda x: x.v1 == 0),
        ("make the place names yellow instead", "change", lambda x: x.texts(LABELS) and all(e["style"]["color"] == YELLOW for e in x.texts(LABELS))),
        ("what song is that?", "question", lambda x: x.says("pop")),
        ("can u make the musci a bit lowder", "change", lambda x: music(x.R1)["volume"] > music(x.R0)["volume"]),
        ("cut it down to 30 secs for tiktok", "change", lambda x: abs(x.R1["end"] - 30) <= 2.0),
        ("how long is it now?", "question", lambda x: re.search(r"\b(2[89]|3[0-2])\.\d s\b", x.reply)),
        ("can you add a sun emoji sticker at the end?", "impossible", lambda x: not x.new_version() and x.says("sticker")),
        ("the colors look dull, make them pop more", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("the old look was better", "restore", lambda x: filters(x.R1) == filters(x.c.resolved(0))),
        ("perfect, export it", "export", lambda x: x.says("export")),
    ]),
    "gym": ("agent_no_180359", [  # gym motivation, phonk, 9:16
        ("too many effects, it hurts my eyes", "change", lambda x: len(fx(x.R1, "flash")) + len(fx(x.R1, "glitch")) < len(fx(x.R0, "flash")) + len(fx(x.R0, "glitch"))),
        ("keep the shakes though", "restore", lambda x: len(fx(x.R1, "shake")) > len(fx(x.R0, "shake"))),
        ("what's the bpm of the music?", "question", lambda x: x.says("140")),
        ("make the cuts even faster on the drop", "change", lambda x: len(x.R1["clips"]) > len(x.R0["clips"])),
        ("title ko bara karo aur laal", "change", lambda x: x.texts(TITLE) and all(e["style"]["color"] == RED for e in x.texts(TITLE))
         and avg(e["style"]["size"] for e in x.texts(TITLE)) > avg(e["style"]["size"] for e in x.texts(TITLE, False))),
        ("is the music too loud?", "question", lambda x: x.c.state.get("pending") is not None and not x.new_version()),
        ("yes", "option", lambda x: music(x.R1)["volume"] < music(x.R0)["volume"]),
        ("add a freeze frame at the end", "change", lambda x: len([o for o in x.ops("shot") if o.get("value") == "freeze"]) == 1),
        ("remove the discipline over motivation text", "change", lambda x: by_text(x.R0, "discipline") and not by_text(x.R1, "discipline")
         and by_text(x.R1, "no excuses")),
        ("use a drake song instead", "impossible", lambda x: not x.new_version()),
        ("what did you change?", "history", lambda x: x.says("v")),
    ]),
    "cooking": ("agent_easystirfr_183910", [  # recipe video, 4:5
        ("the step labels are too small", "change", lambda x: avg(e["style"]["size"] for e in x.texts(LABELS)) > avg(e["style"]["size"] for e in x.texts(LABELS, False))),
        ("and put them at the top", "change", lambda x: x.texts(LABELS) and all(e["position"][1] > 0.25 for e in x.texts(LABELS))),
        ("what transitions are in it?", "question", lambda x: x.says("transition")),
        ("use smooth dissolves instead", "change", lambda x: {e["item"] for e in trans(x.R1)} != {e["item"] for e in trans(x.R0)}),
        ("add a sizzle sound when the bacon is frying", "ask", lambda x: not x.new_version() and x.says("sizzle")),
        ("1", "option", lambda x: x.new_version()),
        ("make it warmer and cozier", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("end with 'Save this recipe!' in yellow", "change", lambda x: any(e["style"]["color"] == YELLOW for e in by_text(x.R1, "save this recipe"))),
        ("how many steps are there?", "question", lambda x: re.search(r"\b\d+ texts\b", x.reply)),
        ("what colour are the labels? make them white", ["question", "change"], lambda x: all(e["style"]["color"] == WHITE for e in x.texts(LABELS))),
        ("can you remove the logo in the background", "impossible", lambda x: not x.new_version()),
        ("make the video 45 seconds", "change", lambda x: abs(x.R1["end"] - 45) <= 2.5),
        ("go back to version 2", "goto", lambda x: x.v1 == 2),
    ]),
    "realestate": ("agent_coastal_180718", [  # property tour, 16:9
        ("what's the title font?", "question", lambda x: x.says("font")),
        ("what elegant fonts do you have?", "catalog", lambda x: len((x.c.state.get("pending") or {}).get("options") or []) >= 2),
        ("try the second one", "option", lambda x: font(x.texts(TITLE)) != font(x.texts(TITLE, False))),
        ("can you make the transitions longer and softer", "change", lambda x: avg(e["duration"] for e in trans(x.R1)) > avg(e["duration"] for e in trans(x.R0))),
        ("remove the grain", "change", lambda x: len(fx(x.R1, "grain")) < len(fx(x.R0, "grain"))),
        ("add the text 'Book a viewing: 555-0123' at the end", "change", lambda x: by_text(x.R1, "555-0123") and not by_text(x.R1, "book a viewing")
         or (by_text(x.R1, "555-0123") and len(by_text(x.R1, "book a viewing")) == 1)),
        ("the music should be more relaxing", "change", lambda x: genre(x.R1) == "chill"),
        ("why did you pick that look?", "question", lambda x: x.says("look")),
        ("add a shot of a dog running on the beach", "impossible", lambda x: x.says("dog") and not x.new_version()),
        ("make it a square version for instagram feed", "change", lambda x: x.R1["canvas"][0] == x.R1["canvas"][1]),
        ("what format is it now?", "question", lambda x: re.search(r"(\d+)x\1", x.reply)),
        ("go back to the original", "reset", lambda x: x.v1 == 0),
    ]),
    "car": ("agent_unleashed_181048", [  # car commercial, 16:9
        ("slow motion please", "ask", lambda x: (x.c.state.get("pending") or {}).get("template")),
        ("the wheel and the taillight", "option", lambda x: len([o for o in x.ops("shot") if o.get("value") == "slow"]) >= 2),
        ("what's happening at 0:15?", "question", lambda x: x.says("0:15")),
        ("add lightning when it accelerates", "change", lambda x: "scene_effect:闪电" in items(x.R1)),
        ("the price text should be bigger and gold", "change", lambda x: by_text(x.R1, "89,900") and all(e["style"]["color"] == GOLD for e in by_text(x.R1, "89,900"))),
        ("make a vertical version for reels", "change", lambda x: x.R1["canvas"][1] > x.R1["canvas"][0]),
        ("why did you use those colourful flashes?", "question", lambda x: x.says("flash")),
        ("no more glitch effects pls", "change", lambda x: len(fx(x.R1, "glitch")) < len(fx(x.R0, "glitch")) and len(fx(x.R1, "zoom")) == len(fx(x.R0, "zoom"))),
        ("make it 4k at 60fps", "impossible", lambda x: x.says("1080")),
        ("make the ending more dramatic", None, lambda x: x.new_version() or "?" in x.reply),
        ("undo that", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
    ]),
    "wedding": ("agent_saraadamfo_181609", [  # wedding film, 16:9
        ("I love it! can the names be in a handwritten font?", "change", lambda x: font(x.texts(TITLE)) != font(x.texts(TITLE, False))),
        ("slow motion on the rings", "change", lambda x: any(o.get("value") == "slow" for o in x.ops("shot"))),
        ("what music is this?", "question", lambda x: x.says("cinematic")),
        ("make the music softer at the start", "change", lambda x: (music(x.R1).get("fade_in") or 0) > (music(x.R0).get("fade_in") or 0)),
        ("add 'Forever & Always' at the end instead of 'Forever begins today'", "change",
         lambda x: by_text(x.R1, "forever & always") and not by_text(x.R1, "forever begins today")),
        ("the dissolves feel too long", "change", lambda x: avg(e["duration"] for e in trans(x.R1)) < avg(e["duration"] for e in trans(x.R0))),
        ("can you add some sparkles on the kiss", "change", lambda x: len(items(x.R1) - items(x.R0)) >= 1),
        ("hmm remove those", "change", lambda x: not (items(x.R0) - items(x.R1)) == set() and len(x.R1["edits"]) < len(x.R0["edits"])),
        ("can you make them smile more", "impossible", lambda x: not x.new_version()),
        ("the previous title font was nicer", "restore", lambda x: font(x.texts(TITLE)) == font([e for e in x.c.resolved(0)["edits"] if e["type"] == "text" and "sara" in e["text"].lower()])
         and by_text(x.R1, "forever & always")),
        ("how many versions did we make?", "versions", lambda x: x.says("versions")),
    ]),
    "tech": ("agent_smart_181728", [  # app ad, 16:9
        ("the glitch transitions are too much", "change", lambda x: len(trans(x.R1)) < len(trans(x.R0))),
        ("what other glitch transitions do you have?", "catalog", lambda x: x.says("vip")),
        ("ok then use a blur one", "change", lambda x: all("blur" in QE.item_words(e["item"]) for e in trans(x.R1)) and trans(x.R1)),
        ("try the first one", "ask", lambda x: not x.new_version()),
        ("make the feature callouts appear one word at a time", "change", lambda x: any((o.get("set") or {}).get("intro_words") for o in x.ops("text"))
         and {e.get("item") for e in x.R1["edits"] if e["type"] == "animation" and e.get("on") in {t["id"] for t in x.texts(LABELS)}}
         != {e.get("item") for e in x.R0["edits"] if e["type"] == "animation" and e.get("on") in {t["id"] for t in x.texts(LABELS, False)}}),
        ("Download now should say 'Get the app'", "change", lambda x: by_text(x.R1, "get the app") and not by_text(x.R1, "download now")),
        ("make it cooler, more blue", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("louder music and add an impact on the drop", "change", lambda x: music(x.R1)["volume"] > music(x.R0)["volume"] and len(sfx(x.R1)) > len(sfx(x.R0))),
        ("what's at 26 seconds", "question", lambda x: x.says("0:26")),
        ("remove the matrix code shots", "change", lambda x: len(files(x.R1)) < len(files(x.R0))),
        ("bring them back", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
        ("post it on instagram for me", "impossible", lambda x: not x.new_version()),
        ("make it more professional", "ask", lambda x: len((x.c.state.get("pending") or {}).get("options") or []) >= 3),
        ("1 and 3", "option", lambda x: x.new_version()),
    ]),
    "sports": ("agent_match_195204", [  # football highlights, 9:16
        ("the GOAL text should be bigger and shake more", "change", lambda x: avg(e["style"]["size"] for e in by_text(x.R1, "goal!")) > avg(e["style"]["size"] for e in by_text(x.R0, "goal!"))
         and any(e["type"] == "animation" and e.get("kind") == "loop" and e.get("on") in {t["id"] for t in by_text(x.R1, "goal!")} for e in x.R1["edits"])),
        ("and make the score yellow", "change", lambda x: by_text(x.R1, "2 - 1") and all(e["style"]["color"] == YELLOW for e in by_text(x.R1, "2 - 1"))),
        ("what's the title?", "question", lambda x: x.says("the title is", "match")),
        ("change it to 'DERBY DAY'", "change", lambda x: by_text(x.R1, "derby day") and not by_text(x.R1, "highlights")),
        ("add an impact sound on the goal", "change", lambda x: len(sfx(x.R1)) > len(sfx(x.R0))),
        ("is there a replay effect?", "catalog", lambda x: not x.says("40 effects")),
        ("make the intro shorter, people scroll away", "change", lambda x: x.R1["end"] < x.R0["end"] - 0.5),
        ("speed ramp on the penalty", "change", lambda x: any(o.get("value") == "velocity" for o in x.ops("shot"))),
        ("add a voiceover saying what a goal", "impossible", lambda x: not x.new_version()),
        ("what did you change?", "history", lambda x: x.says("v")),
        ("export", "export", lambda x: x.says("export")),
    ]),
    "nature": ("agent_thetwoseas_200445", [  # documentary teaser with narration, 16:9
        ("can the subtitles be bigger", "change", lambda x: avg(e["style"]["size"] for e in x.texts(CAPS)) > avg(e["style"]["size"] for e in x.texts(CAPS, False))),
        ("and move them a bit higher", "change", lambda x: avg(e["position"][1] for e in x.texts(CAPS)) > avg(e["position"][1] for e in x.texts(CAPS, False))),
        ("what's the narration about?", "question", lambda x: x.says("narration")),
        ("make the music quieter under the voice", "change", lambda x: music(x.R1)["volume"] < music(x.R0)["volume"]),
        ("remove the black bars", "change", lambda x: len(fx(x.R1, "letterbox")) < len(fx(x.R0, "letterbox"))),
        ("add a slow zoom on the waterfall", "change", lambda x: len(x.ops("push_add")) == 1),
        ("what's the look called?", "question", lambda x: len(x.reply) > 10),
        ("remove the people in the background", "impossible", lambda x: not x.new_version()),
        ("make it look more like golden hour", "change", lambda x: filters(x.R1) != filters(x.R0)),
        ("I prefer the first version's colours", "restore", lambda x: filters(x.R1) == filters(x.c.resolved(0))),
        ("thanks that's perfect", "ack", lambda x: not x.new_version()),
    ]),
    "party": ("agent_saturday_200044", [  # party recap, 9:16
        ("SATURDAY NIGHT should come in with a glitch", "change", lambda x: any("glitch" in str((o.get("set") or {}).get("intro_words")) for o in x.ops("text"))
         and any(e["type"] == "animation" and e.get("kind") == "intro" and "glitch" in QE.item_words(e.get("item")) for e in x.R1["edits"])),
        ("the flashes are too much, maybe only on the drop", "change", lambda x: len(fx(x.R1, "flash")) < len(fx(x.R0, "flash"))),
        ("how many flashes are there now?", "question", lambda x: re.search(r"\b\d+ flash", x.reply)),
        ("add confetti at the end", "change", lambda x: any("confetti" in QE.item_words(k) for k in items(x.R1) - items(x.R0))),
        ("the music needs more bass", "change", lambda x: genre(x.R1) == "phonk"),
        ("add a dancing emoji", "impossible", lambda x: not x.new_version()),
        ("make it 30 seconds and vertical", "change", lambda x: abs(x.R1["end"] - 30) <= 2.0 and x.R1["canvas"][1] > x.R1["canvas"][0]),
        ("what did you change?", "history", lambda x: x.says("30")),
        ("undo", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
        ("undo again", "undo", lambda x: x.v1 == x.c.state["versions"][x.v0]["parent"]),
        ("redo", "redo", lambda x: x.v1 != x.v0),
    ]),
}


def invariants(x):
    """What must hold after any turn: the music stays unless removed, there is a picture, no new item or file goes missing,
    nothing points at a shot that is gone, and a question or an impossible ask changes nothing."""
    out = []
    if not x.R1["clips"]:
        out.append("no clips")
    asked_music_off = any(o.get("op") == "audio" and o.get("who") == "music" and o.get("remove") for o in x.ops())
    if music(x.R0) and not music(x.R1) and not asked_music_off:
        out.append("the music disappeared")
    new_notes = [n for n in x.R1.get("notes") or [] if n not in (x.R0.get("notes") or [])]
    bad = [n for n in new_notes if re.search(r"not an available|refers to unknown|need 'on'|unknown parameter", n)]
    if bad:
        out.append("new problem notes: " + " | ".join(b[:80] for b in bad[:2]))
    kinds = set(x.turn.get("intents") or [])
    if kinds and kinds <= {"question", "catalog", "capability", "help", "impossible", "ack", "history", "versions", "compare", "context", "ask"} and x.new_version():
        out.append("a question changed the edit")
    return out


def _wipe(folder):
    """Empty a test output folder (only the two test folders above are ever wiped)."""
    import shutil
    assert folder in (SCRATCH, TEST_CHATS)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)


def run(names, planner):
    _wipe(SCRATCH)
    _wipe(TEST_CHATS)
    rows, t_all = [], time.perf_counter()
    for name in names:
        draft, turns = CONVERSATIONS[name]
        c = Conversation.start(draft, planner=planner, drafts=str(SCRATCH), log=lambda *a: None, chats_dir=TEST_CHATS)
        print(f"\n=== {name} ({draft})")
        for msg, want, check in turns:
            v0 = c.state["cur"]
            R0 = c.resolved()
            t = time.perf_counter()
            err = None
            try:
                reply = c.say(msg)
            except Exception as e:  # noqa: BLE001  (a crash is a failed turn, the conversation goes on)
                import traceback
                err = f"{type(e).__name__}: {e}"
                traceback.print_exc()
                reply = ""
                c.last_turn = {"intents": ["crash"], "ops": []}
            secs = time.perf_counter() - t
            v1 = c.state["cur"]
            turn = c.last_turn
            x = X(c, v0, v1, R0, c.resolved(), reply, turn)
            wants = [want] if isinstance(want, str) else (want or [])
            intent_ok = all(w in turn.get("intents", []) for w in wants)
            broken = invariants(x)
            if broken and not err:
                err = "invariant: " + "; ".join(broken)
            try:
                check_ok = bool(check(x))
            except Exception as e:  # noqa: BLE001
                check_ok, err = False, err or f"check {type(e).__name__}: {e}"
            ok = intent_ok and check_ok and not err
            rows.append({"chat": name, "msg": msg, "want": wants, "intents": turn.get("intents"), "intent_ok": intent_ok, "check_ok": check_ok,
                         "ok": ok, "seconds": round(secs, 2), "llm": bool(turn.get("llm")), "v": f"{v0}->{v1}", "reply": reply[:400], "error": err})
            mark = "OK " if ok else "BAD"
            print(f"{mark} [{','.join(turn.get('intents') or [])}{'+llm' if turn.get('llm') else ''}] v{v0}->v{v1} {secs:5.2f}s  {msg}")
            if not ok:
                print(f"      want {wants} intent_ok={intent_ok} check_ok={check_ok} {err or ''}")
                print("      " + reply.replace("\n", "\n      ")[:700])
    n = len(rows)
    ok = sum(r["ok"] for r in rows)
    usd = planner.cost()[1] if planner is not None else 0.0
    summary = {"turns": n, "ok": ok, "intent_ok": sum(r["intent_ok"] for r in rows), "check_ok": sum(r["check_ok"] for r in rows),
               "llm_turns": sum(r["llm"] for r in rows), "seconds_total": round(time.perf_counter() - t_all, 1),
               "seconds_per_turn": round(avg(r["seconds"] for r in rows), 2), "usd": usd}
    print(f"\n{ok}/{n} turns OK (intent {summary['intent_ok']}/{n}, timeline/answer check {summary['check_ok']}/{n}); "
          f"{summary['llm_turns']} turns used the model; {summary['seconds_per_turn']} s per turn; ${usd:.4f}")
    out = ROOT / "out" / "video" / "chats" / "test_report.json"
    out.write_text(json.dumps({"summary": summary, "turns": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary, rows


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    planner = None
    if "--offline" not in sys.argv:
        from harness.planner import ChatPlanner
        planner = ChatPlanner()
    run(args or list(CONVERSATIONS), planner)
