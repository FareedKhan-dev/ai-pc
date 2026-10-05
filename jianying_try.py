"""Build a JianYing 5.9 project with pyJianYingDraft that uses what CapCut 9.5 could not load (clip and text animations,
effects), plus filter, transition, font, zoom keyframes and music. Free (non-VIP) items only; media from media/.

  .venv-jy\\Scripts\\python.exe jianying_try.py
"""
import os
import time
from pathlib import Path

import pyJianYingDraft as jy
from pyJianYingDraft import tim, trange

ROOT = Path(__file__).resolve().parent
DRAFTS = Path(os.environ["LOCALAPPDATA"]) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
MEDIA = ROOT / "media"
NAME = "agent_jy_test"  # agent_ prefix: create_draft(allow_replace=True) may only ever replace our own drafts


def free(enum, prefer=()):
    items = [m for m in enum if not getattr(m.value, "is_vip", False)]
    for p in prefer:
        for m in items:
            if p in m.name:
                return m
    return items[0]


t0 = time.perf_counter()
folder = jy.DraftFolder(str(DRAFTS))
script = folder.create_draft(NAME, 1920, 1080, allow_replace=True)
for kind in (jy.TrackType.audio, jy.TrackType.video, jy.TrackType.text):  # 0.3.0 API: append_track(TrackSpec)
    script.append_track(jy.TrackSpec(kind))

flt = free(jy.FilterType, ["复古", "胶片"])          # retro / film look
tr = free(jy.TransitionType, ["叠化", "闪白"])       # dissolve / white flash
intro = free(jy.IntroType, ["渐显", "放大"])         # fade in / zoom in
eff = free(jy.VideoSceneEffectType, ["光", "胶片"])  # light / film effect
font = free(jy.FontType, ["悠然体", "新青年体"])      # one of the bundled fonts
t_in = free(jy.TextIntro, ["打字机", "渐显"])        # typewriter / fade in
t_loop = free(jy.TextLoopAnim, ["呼吸", "跳动"])     # breathe / bounce

clip1 = jy.VideoSegment(str(MEDIA / "eclosion.mp4"), trange("0s", "5s"), source_timerange=trange("5s", "5s"))
clip1.add_filter(flt, 80)
clip1.add_background_filling("blur", 0.0625)
clip1.add_keyframe(jy.KeyframeProperty.uniform_scale, tim("0s"), 1.0)
clip1.add_keyframe(jy.KeyframeProperty.uniform_scale, tim("5s"), 1.15)
clip1.add_transition(tr)

clip2 = jy.VideoSegment(str(MEDIA / "astra-demo.mp4"), trange("5s", "5s"), source_timerange=trange("12s", "5s"))
clip2.add_animation(intro)
clip2.add_effect(eff)

title = jy.TextSegment("Made by an AI agent with pyJianYingDraft", trange("0s", "4s"), font=font,
                       style=jy.TextStyle(size=8.0, color=(1.0, 0.85, 0.1), bold=True, align=1),
                       clip_settings=jy.ClipSettings(transform_y=-0.75))
title.add_animation(t_in)
title.add_animation(t_loop)

music = jy.AudioSegment(str(MEDIA / "openrouter-audio-output.mp3"), trange("0s", "10s"), volume=0.5)
music.add_fade("0.5s", "1s")

script.add_segment(music).add_segment(clip1).add_segment(clip2).add_segment(title)
script.save()
print(f"built and saved in {(time.perf_counter() - t0) * 1000:.0f} ms -> {DRAFTS / NAME}")
print(f"filter={flt.name} transition={tr.name} clip intro={intro.name} effect={eff.name}")
print(f"font={font.name} text intro={t_in.name} text loop={t_loop.name}; timeline {script.duration / 1e6:.1f} s")
