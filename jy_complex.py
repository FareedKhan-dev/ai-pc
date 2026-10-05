"""A complex edit, code only (no export): request in plain words -> one model call -> checked plan -> JianYing project.

  .venv\\Scripts\\python.exe jy_complex.py ["your own request"]
"""
import json
import sys
import time

from harness import jy_lane as jl
from harness.planner import ChatPlanner

BRIEF = """Edit a 45-second cinematic AI-tech teaser, 16:9.
1. Cold open, 0-6 s: the eclosion clip from second 10 in slow motion (0.5x) with blurred background fill, a fade-in intro
   animation, a warm vintage filter at 70% and a slow push-in (scale keyframes 1.0 to 1.2). Centre title 'THE NEXT WAVE':
   bold, white, black outline, soft shadow, typewriter-style entrance, a gentle breathing loop and a fade-out exit; it
   grows slowly from scale 1.0 to 1.15 over its 4 seconds.
2. Montage, 6-30 s: at least 8 fast cuts of 2-3 seconds alternating between kimiK3, qwen_3.8_max_v2 and astra-demo (a
   different source moment each time), a mix of 1x and 2x speed, a different transition between every pair of cuts, a
   cool cinematic filter on the kimi and qwen shots, and a glitch-style effect on two of the cuts. Mute the clips' sound.
3. Picture-in-picture, 12-26 s: an overlay of the astra demo in the top-right corner at 30% size inside a rounded
   rectangle mask with feathered edges, screen blend; it slides in from the right edge at the start (x keyframes) and
   fades out at the end (alpha keyframes).
4. Photo moment, 30-38 s: the two photos, 4 seconds each, Ken Burns style (the first slowly zooms in, the second pans
   left with x keyframes), with a soft light-leak effect over the whole section on the effect track.
5. Ending, 38-45 s: back to the eclosion clip at the butterfly emerging (around second 25), a dreamy filter over the last
   7 seconds on the filter track, end title 'COMING 2026' with a dark rounded background box, pop-in entrance and
   slide-out exit, plus a small 'subscribe for more' lower-left label with a bouncing loop.
Subtitles at the bottom throughout: 6 short narration lines spread across the 45 seconds.
Music: loop the openrouter audio as background music to cover all 45 seconds at 60% volume, fade in 1 s at the start and
fade out 2 s at the end; duck it to 30% during the opening title with volume keyframes; add a robot-voice tone effect on
the second loop just for fun."""


def main():
    req = sys.argv[1] if len(sys.argv) > 1 else BRIEF
    print("REQUEST:\n" + req + "\n", flush=True)
    t0 = time.perf_counter()
    files = jl.media_files()
    t_media = time.perf_counter() - t0
    plan, plan_ms, usage = jl.make_plan(req, ChatPlanner(), files)
    print(f"plan: {plan_ms / 1000:.1f} s ({usage.get('prompt_tokens')} tokens in, {usage.get('completion_tokens')} out)", flush=True)
    res = jl.build(plan, files)
    p = jl.save(req, plan, res)
    total = time.perf_counter() - t0
    st = res["stats"]
    print(f"build: {res['ms'] / 1000:.2f} s -> {res['draft']} ({res['seconds']} s, {res['tracks']} tracks)")
    print("BUILT: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in st.items() if v))
    if res["notes"]:
        print(f"NOTES ({len(res['notes'])}):")
        for n in res["notes"][:25]:
            print("   -", n)
    print(f"\nTIME: media scan {t_media:.2f} s + plan {plan_ms / 1000:.1f} s + build {res['ms'] / 1000:.2f} s = {total:.1f} s total")
    print(f"plan saved: {p}")


if __name__ == "__main__":
    main()
