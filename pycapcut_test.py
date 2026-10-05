"""Generate a tiny text-only draft with pyCapCut into a PROJECT-LOCAL folder (never CapCut's own).

Then compare its structure with the draft CapCut 9.5 wrote itself.
"""
import json
import os
import shutil

import pycapcut as cc

OUT = os.path.join(os.path.dirname(__file__), "out", "drafts")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)

folder = cc.DraftFolder(OUT)
script = folder.create_draft("pycapcut_test", 1920, 1080)
script.add_track(cc.TrackType.text)
script.add_segment(cc.TextSegment("Hello from pyCapCut", cc.trange("0s", "3s")))
script.save()

draft_dir = os.path.join(OUT, "pycapcut_test")
print("files written by pyCapCut:")
for root, _, files in os.walk(draft_dir):
    for f in files:
        p = os.path.join(root, f)
        print("  ", os.path.relpath(p, draft_dir), os.path.getsize(p), "bytes")

d = json.load(open(os.path.join(draft_dir, "draft_content.json"), encoding="utf-8"))
print("version:", d.get("version"), "| new_version:", d.get("new_version"), "| tracks:", len(d["tracks"]),
      "| texts:", len(d["materials"]["texts"]), "| duration(us):", d.get("duration"))
print("top-level keys:", len(d), "| materials categories:", len(d["materials"]))
