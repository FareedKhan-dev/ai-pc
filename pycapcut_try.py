"""Try pyCapCut (GitHub main) on a real edit and save it into CapCut's own projects folder.

  .venv\\Scripts\\python.exe pycapcut_try.py

Uses only free (non-Pro) catalogue items so the result can be exported without a Pro account.
"""
import os
import time
from pathlib import Path

import pycapcut as cc
from pycapcut import tim, trange

DRAFTS = Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
DL = Path(os.environ["USERPROFILE"]) / "Downloads"
NAME = "pycapcut_demo"


def free(enum, prefer=None):
    """First free (non-Pro) member of a catalogue enum; `prefer` = substrings to look for first."""
    items = [m for m in enum if not getattr(m.value, "is_vip", False)]
    for p in prefer or []:
        for m in items:
            if p.lower() in m.name.lower():
                return m
    return items[0]


t0 = time.perf_counter()
folder = cc.DraftFolder(str(DRAFTS))
script = folder.create_draft(NAME, 1920, 1080, allow_replace=True)
script.add_track(cc.TrackType.video).add_track(cc.TrackType.text)

flt = free(cc.FilterType, ["vintage", "retro", "film", "warm"])
tr = free(cc.TransitionType, ["white_flash", "flash", "dissolve", "fade"])
intro = free(cc.IntroType)
tintro = free(cc.TextIntro)
font = free(cc.FontType, ["Poppins", "Montserrat", "Roboto"])

clip1 = cc.VideoSegment(str(DL / "eclosion.mp4"), trange("0s", "6s"))  # first 6 s of the square clip
clip1.add_filter(flt, 80)                                               # filter at 80% strength
clip1.add_background_filling("blur", 0.0625)                            # blurred fill for the 1:1 clip on 16:9
clip1.add_keyframe(cc.KeyframeProperty.uniform_scale, tim("0s"), 1.0)   # slow zoom in
clip1.add_keyframe(cc.KeyframeProperty.uniform_scale, tim("6s"), 1.15)
clip1.add_transition(tr)                                                # transition into the next clip

clip2 = cc.VideoSegment(str(DL / "astra-demo.mp4"), trange("6s", "6s"),  # 6 s on the timeline...
                        source_timerange=trange("10s", "6s"))            # ...taken from 10-16 s of the source
clip2.add_animation(intro)

title = cc.TextSegment("Made by an AI agent with pyCapCut", trange("0s", "4s"), font=font,
                       style=cc.TextStyle(size=9.0, color=(1.0, 0.85, 0.1), bold=True),
                       clip_settings=cc.ClipSettings(transform_y=-0.75))
title.add_animation(tintro)

script.add_segment(clip1).add_segment(clip2).add_segment(title)
script.save()
took = (time.perf_counter() - t0) * 1000

print(f"built and saved in {took:.0f} ms -> {DRAFTS / NAME}")
print(f"filter={flt.name} transition={tr.name} clip intro={intro.name} text intro={tintro.name} font={font.name}")
print(f"timeline length {script.duration / 1e6:.1f} s")
for p in sorted((DRAFTS / NAME).rglob("*")):
    if p.is_file():
        print(f"   {p.relative_to(DRAFTS / NAME)}  {p.stat().st_size} bytes")
