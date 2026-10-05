"""Stress test: ten one-minute edits in ten genres, each from several clips (media/stock/<genre>/), run back to back.

  .venv\\Scripts\\python.exe -u scripts/stress_video_batch.py [genre ...]

Each job is a normal agent run (studio.Studio.new) with one fix round; logs go to out/video/batch/<genre>.log and a
summary to out/video/batch/summary.json (time, AI cost, checks, asked-vs-delivered, video and report paths).
"""

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

JOBS = {
    "travel": "Make a 1-minute Instagram travel reel from my road trip clips: open with a sweeping landscape shot, show each place "
    "with its name, upbeat music, smooth zoom transitions, a warm golden look, the best shot on the drop, and end on the "
    "sunset with the title ROAD TRIP 2026.",
    "gym": "1 minute gym motivation edit for TikTok: aggressive phonk beat, fast cuts on every beat, speed ramps, shake on the hits, "
    "dark gritty grade, and the motivational texts NO EXCUSES and DISCIPLINE OVER MOTIVATION.",
    "cooking": "Create a 1-minute recipe video for Instagram from my cooking clips: label each step (Step 1, Step 2...), cozy music, "
    "zoom in on the sizzling moments, a warm food look, and end with the dish served and the title Easy Stir Fry.",
    "realestate": "Make a 1 minute luxury property tour video for YouTube in 16:9: cinematic slow pans, label each area, elegant calm "
    "music, smooth dissolves, the title Coastal Living at the start and a closing card Book a viewing.",
    "car": "Make a 1-minute car commercial in 16:9 for the red sports car: dramatic intro, slow-motion details, fast cuts on the beat "
    "when it accelerates, flashes, the title UNLEASHED and an end card with the price $89,900.",
    "wedding": "Edit a 1 minute wedding highlight film in 16:9: romantic and emotional, slow motion, soft dissolves, a warm film look, "
    "elegant titles with the couple's names Sara & Adam, the rings close-up at the climax, and end with Forever begins today.",
    "tech": "Make a 1-minute product ad for our new smart app in 16:9: modern and clean, cuts on the beat, feature callouts Fast, Secure "
    "and Smart, techy glitch transitions, and an end card Download now.",
    "sports": "Make a 1-minute football highlights reel for TikTok: hype music, speed ramps on the shots, a freeze frame on the goal with "
    "the label GOAL!, the score 2 - 1, and flashes on the big plays.",
    "nature": "Make a 1-minute nature documentary teaser in 16:9 using this narration: slow cinematic shots that match what is said, "
    "subtitles, soft music under the voice, and the title The Two Seasons.",
    "party": "Make a 1-minute party recap for Instagram: colorful, energetic dance music, cuts and flashes on every beat, RGB glitch hits, "
    "the text SATURDAY NIGHT at the drop, and end with see you next week.",
}

if __name__ == "__main__":
    from ai_pc.llm.planner import ChatPlanner
    from ai_pc.video import studio

    out = ROOT / "out" / "video" / "batch"
    out.mkdir(parents=True, exist_ok=True)
    sp = out / "summary.json"
    summary = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    for genre in sys.argv[1:] or list(JOBS):
        files = sorted(str(p) for p in (ROOT / "media" / "stock" / genre).glob("*") if p.suffix.lower() in (".mp4", ".mp3", ".wav", ".m4a"))
        logf = open(out / f"{genre}.log", "w", encoding="utf-8")

        def log(m, **_):
            logf.write(str(m) + "\n")
            logf.flush()

        t0 = time.perf_counter()
        print(f"=== {genre}: {len(files)} files", flush=True)
        try:
            sess = studio.Studio(planner=ChatPlanner(), log=log, fix_rounds=1).new(JOBS[genre], files)
            a = sess.get("assessment") or {}
            c = (sess.get("report") or {}).get("counts") or {}
            row = {
                "ok": bool((sess.get("export") or {}).get("ok")),
                "draft": sess["map"]["draft"],
                "video": (sess.get("export") or {}).get("path"),
                "seconds": sess["map"]["seconds"],
                "shots": len(sess["resolved"]["clips"]),
                "edits": len(sess["resolved"]["edits"]),
                "checks": c,
                "asks": [(q["ask"], q["status"]) for q in a.get("scorecard", [])],
                "time_s": round(time.perf_counter() - t0, 1),
                "ai_usd": sess.get("ai_usd"),
                "style": sess["plan"].get("style"),
                "rhythm": sess["plan"].get("_rhythm"),
                "report": f"out/video/reports/{sess['map']['draft']}.md",
            }
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            row = {"ok": False, "error": f"{type(e).__name__}: {e}", "time_s": round(time.perf_counter() - t0, 1)}
        logf.close()
        summary[genre] = row
        sp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    {json.dumps(row, ensure_ascii=False)[:400]}", flush=True)
    print("all done", flush=True)
