"""Offline checks of the video agent's planning layer: resolve + build, no JianYing, no network, no mouse.

  .venv\\Scripts\\python.exe tests\\test_video_offline.py

Covers the lessons learned from real exports: keyframes in file time, the 500% scale cap, ramps that must last their
planned duration, titles planned past the end, edit-type aliases, VIP / unavailable items replaced by meaning,
safe-zone text placement, and a full build into a temporary drafts folder.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness import analyze as AN  # noqa: E402
from harness import editplan as EP  # noqa: E402
from harness import jybuild as JB  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def main():
    media = ["mixkit_28287.mp4", "mixkit_47518.mp4", "mixkit_4832.mp4", "openrouter-audio-output.mp3",
             "josh-berquist-_4sWbzH5fp8-unsplash.jpg", "pexels-berna-elif-359546580-26628374.jpg"]
    files = [str(ROOT / "media" / f) for f in media if (ROOT / "media" / f).exists()]
    if len(files) < 3:
        print("skipped: the test media are not in media/")
        return 0
    an = AN.analyze(files, planner=None, log=lambda *a: None)

    # 1. the feature plan resolves and builds
    plan = json.loads((ROOT / "tests" / "plans" / "feature_test.json").read_text(encoding="utf-8"))
    R = EP.resolve(plan, an)
    check("feature plan resolves to 12-14 s", 12 <= R["end"] <= 14, R["end"])
    check("every edit window lies inside the video", all(0 <= e["window"][0] <= e["window"][1] <= R["end"] + 1e-6 for e in R["edits"] if e.get("window")))
    tmp = Path(tempfile.mkdtemp(prefix="drafts_"))
    try:
        M = JB.build(R, drafts=tmp)
        check("build writes a draft", (tmp / M["draft"] / "draft_content.json").exists())
        check("build has no feature errors", not [n for n in M["notes"] if n not in R["notes"]], M["notes"])
        check("chroma, mask, blend, transition, keyframes built", all(M["stats"].get(k) for k in ("chroma", "mask", "blend", "transition", "keyframes")), M["stats"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2. keyframes are written at FILE time (source start + seconds x speed); stills at clip time
    check("keyframe time on a trimmed, slowed clip", abs(JB.kf_time({"kind": "video", "src_from": 5.0, "speed": 0.5}, 1.0) - 5.5) < 1e-9)
    check("keyframe time on a still", JB.kf_time({"kind": "image"}, 1.0) == 1.0)

    base = {"canvas": "9:16", "platform": "instagram_reels"}
    # 3. a ramp lasts its planned duration even when 'to' disagrees
    R = EP.resolve({**base, "clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 6.0, "duration": 10.25, "ramp": [[0, 1], [1.5, 0.4], [3, 1]], "to": 8.5}]}, an)
    check("ramp duration wins over 'to'", abs(R["clips"][0]["dur"] - 10.25) < 0.05, R["clips"][0]["dur"])

    # 4. zoom headroom: base x zoom stays under JianYing's 500% cap
    R = EP.resolve({**base, "clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 2, "duration": 3, "reframe": {"x": 0.5, "y": 0.3, "zoom": 1.6}}],
                    "edits": [{"id": "z", "type": "zoom", "on": "c1", "start": 0.5, "duration": 0.8, "to": 1.4}]}, an)
    kf = EP.motion_keyframes(R["clips"][0], R["edits"], R["clips"][0]["pieces"][0])
    check("zoom keyframes stay under 500%", max(v for _, v in kf["scale"]) <= EP.MAX_SCALE + 1e-6, max(v for _, v in kf["scale"]))

    # 5. titles planned after the end are moved in, not dropped; aliases; VIP / missing items replaced by meaning
    R = EP.resolve({**base, "clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 0, "duration": 4}],
                    "edits": [{"id": "t", "type": "title", "text": "LATE TITLE", "start": 9, "duration": 2},
                              {"id": "x", "type": "character_effect", "name": "闪电眼", "on": "c1"}]}, an)
    t = next((e for e in R["edits"] if e["id"] == "t"), None)
    check("late title kept inside the video", t is not None and t["window"][1] <= 4.0 + 1e-6 and t["window"][0] >= 0, t and t["window"])
    x = next((e for e in R["edits"] if e["id"] == "x"), None)
    check("type alias + VIP item -> a free effect", x is not None and x["type"] == "effect" and not EP.Catalog.shared().item(x["item"])["pro"], x and x.get("item"))

    # 6. text stays inside Instagram's safe zone
    R = EP.resolve({**base, "clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 0, "duration": 4}],
                    "edits": [{"id": "t", "type": "text", "text": "TOP OF THE SCREEN", "start": 0, "duration": 2, "position": [0, 0.98], "size": 16}]}, an)
    t = R["edits"][0]
    check("text moved below the app's top bar", t["box"][1] >= R["safe"]["top"] - 0.01, t["box"])

    # 7. sound design: a riser ends on its moment, an impact starts there; stretch keeps x / y scale apart
    R = EP.resolve({**base, "clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 2, "duration": 4, "stretch": [1.2, 1.0]}],
                    "edits": [{"id": "r", "type": "sfx", "sound": "riser", "at": 3.0}, {"id": "b", "type": "sound_effect", "sound": "boom", "at": 3.0}]}, an)
    w = {e["id"]: e["window"] for e in R["edits"]}
    check("riser ends on the moment", abs(w["r"][1] - 3.0) < 1e-6, w.get("r"))
    check("impact (alias boom) starts on the moment", abs(w["b"][0] - 3.0) < 1e-6, w.get("b"))
    check("stretch kept", R["clips"][0].get("stretch") == [1.2, 1.0])

    # 8. a removed green screen never sits on a blurred copy of itself (the un-keyed clip would show through)
    R = EP.resolve({**base, "clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 2, "duration": 3, "chroma": "auto", "background": {"blur": "strong"}}]}, an)
    check("chroma + blur background -> dark colour", R["clips"][0]["background"] == "#0A0A12", R["clips"][0]["background"])

    # 9. the critic's patch operations; a sound effect written as 'audio' without a file becomes a synthesised one
    from harness import critic as CR
    p0 = {"clips": [{"id": "c1", "file": "mixkit_28287.mp4", "from": 0, "duration": 4}],
          "edits": [{"id": "s", "type": "shake", "on": "c1", "start": 1, "duration": 0.5}, {"id": "t", "type": "text", "text": "X", "start": 0, "duration": 2}]}
    p1, done = CR.apply_patch(p0, [{"op": "add", "edit": {"id": "k", "type": "audio", "sound": "impact", "at": 1.0}},
                                   {"op": "move", "id": "t", "at": 2.0}, {"op": "set", "id": "s", "field": "strength", "value": 0.9},
                                   {"op": "remove", "id": "nope"}, {"op": "set", "id": "s", "field": "id", "value": "hack"}])
    k = next((e for e in p1["edits"] if e["id"] == "k"), {})
    check("critic: sfx add normalised", k.get("type") == "sfx" and k.get("sound") == "impact", k)
    check("critic: move and set applied, unsafe set ignored", len(done) == 3 and p1["edits"][0]["strength"] == 0.9 and p1["edits"][0]["id"] == "s", done)
    R1 = EP.resolve(p1, an)
    check("critic: shake now has its impact sound", not [i for i in CR.lint(R1, p1, {}) if "no impact sound" in i["issue"]])

    # 10. a designed hype edit on a 140 BPM grid: every piece lands on the main track, end to end
    from harness import recipes as RC
    design = {"style": "hype", "canvas": "9:16", "music": {"generate": "hype", "bpm": 140},
              "shots": [{"id": "a", "section": "intro", "file": "mixkit_4832.mp4", "beats": 4},
                        {"id": "b", "section": "drop", "file": "mixkit_47518.mp4", "beats": 6, "speed": "velocity"},
                        {"id": "c", "section": "drop", "file": "mixkit_28287.mp4", "beats": 2, "chroma": "auto"},
                        {"id": "d", "section": "outro", "file": "mixkit_28287.mp4", "beats": 4, "speed": "freeze", "chroma": "auto"}],
              "recipes": [{"use": "kinetic_title", "text": "BOSS MODE", "at": "drop"}]}
    v2 = RC.compose(design, an, EP.Catalog.shared(), log=lambda *a: None)
    R = EP.resolve(v2, an)
    tmp = Path(tempfile.mkdtemp(prefix="drafts_"))
    try:
        M = JB.build(R, drafts=tmp)
        d = json.loads((tmp / M["draft"] / "draft_content.json").read_text(encoding="utf-8"))
        main = next(t for t in d["tracks"] if t["type"] == "video" and t["name"] == "main")
        segs = [(x["target_timerange"]["start"], x["target_timerange"]["duration"]) for x in main["segments"]]
        gaps = [segs[i + 1][0] - sum(segs[i]) for i in range(len(segs) - 1)]
        check("beat-grid build: every piece on the main track", len(segs) == sum(len(c["pieces"]) for c in R["clips"]), (len(segs), M["notes"][:2]))
        check("beat-grid build: no gaps, no overlaps", all(g == 0 for g in gaps), gaps)
        check("velocity climax kept whole (one ramp)", sum(1 for c in R["clips"] if c["id"].startswith("b")) == 1, [c["id"] for c in R["clips"]])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 11. pacing like an editor: a long ordinary one-take shot alternates with cutaways; the length fits the target
    from harness import cutting as CU
    from harness.styles import STYLES
    long_design = {"style": "montage", "canvas": "9:16", "music": {"generate": "pop", "bpm": 120}, "target_seconds": 30,
                   "shots": [{"id": "a", "section": "intro", "file": "mixkit_4832.mp4", "beats": 4},
                             {"id": "b", "section": "verse", "file": "mixkit_47518.mp4", "beats": 8},
                             {"id": "c", "section": "verse", "file": "mixkit_28287.mp4", "beats": 4, "label": "Second place"},
                             {"id": "d", "section": "drop", "file": "mixkit_4832.mp4", "beats": 8, "speed": "slow"},
                             {"id": "e", "section": "outro", "file": "mixkit_47518.mp4", "beats": 4}],
                   "edits": [{"id": "s1", "type": "sfx", "sound": "impact", "at": 3.0, "expect": "an impact exactly on the drop"},
                             {"id": "t1", "type": "text", "text": "Second place", "on": "c", "start": 0.2, "duration": 1.5, "size": 12},
                             {"id": "t2", "type": "text", "text": "Motorcycle Journey", "on": "e", "start": 0.2, "duration": 1.5, "size": 44}]}
    paced = RC.enforce_pacing(long_design["shots"], STYLES["montage"], long_design, an)
    parts = [s for s in paced if str(s["id"]).startswith("b")]
    check("pacing: one long take alternates with a cutaway", len(parts) == 4 and parts[1].get("file") is None and parts[2]["file"] == "mixkit_47518.mp4", parts)
    check("pacing: the climax and the labelled shot stay whole", [s["beats"] for s in paced if s["id"] in ("c", "d")] == [4, 8])
    spread = CU.spread_files(paced, an)
    check("spread: every cutaway gets a file that is not its neighbour", all(s.get("file") for s in spread) and
          all(not s.get("cutaway") or (s["file"] != spread[i - 1]["file"] and s["file"] != spread[i + 1]["file"]) for i, s in enumerate(spread)), spread)
    fitted = CU.fit(spread, 0.5, STYLES["montage"]["beats_per_shot"], 30)
    tot = sum(CU.shot_lengths(fitted, 0.5, STYLES["montage"]["beats_per_shot"]))
    check("fit: the cut lasts the target (30 s +-3%)", abs(tot - 30) <= 0.9, tot)
    v3 = RC.compose(long_design, an, EP.Catalog.shared(), log=lambda *a: None)
    R3 = EP.resolve(v3, an)
    check("compose: length fitted end to end", abs(R3["end"] - 30) <= 0.9, R3["end"])
    imp = next((e for e in R3["edits"] if e["id"] == "s1"), {})
    check("extras: an sfx meant for the drop lands on it", abs(imp.get("at", -1) - v3["_rhythm"]["drop"]) < 0.01, (imp.get("at"), v3["_rhythm"]["drop"]))
    twins = [e for e in R3["edits"] if e["type"] == "text" and e["text"] == "Second place"]
    check("labels: no twin of a planner's own text", len(twins) == 1, [e["id"] for e in twins])
    big = next((e for e in R3["edits"] if e["id"] == "t2"), {})
    check("text: a giant title is shrunk so its longest word fits a line", big and 20 < big["style"]["size"] <= 27, big.get("style", {}).get("size"))
    xs = RC.Ctx([{"id": "a", "start": 0, "end": 30, "section": "drop"}], [0, 0.5], [0], 0, [{"name": "drop", "start": 0, "end": 30}],
                STYLES["hype"], EP.Catalog.shared(), 30)
    xs.request = "1-minute football highlights reel"
    vg = xs.pick(["scene_effect"], "vignette dark edges", plain=True)
    check("themed looks: no heart vignette in a football reel", vg and "爱心" not in vg, vg)
    ex = [{"type": "text", "text": "SATURDAY NIGHT", "start": 0, "duration": 4}, {"type": "text", "text": "see you next week", "start": 0, "duration": 4}]
    RC.place_by_request(ex, "colourful, the text SATURDAY NIGHT at the drop, and end with see you next week.", 15.0, 60.0)
    check("texts go where the request says (drop / end)", ex[0]["start"] == 15.0 and ex[1]["start"] > 50, [e["start"] for e in ex])
    rz = EP.Resolver({"canvas": "9:16", "clips": []}, an)
    wrapped = rz.wrap_words("ROAD TRIP 2026", {"size": 20.0, "scale": 1.0, "max_width": 0.82})
    check("long titles break between words, never inside one", wrapped == "ROAD TRIP\n2026", wrapped)
    sd = {"style": "hype", "shots": [{"id": "a", "section": "climax", "file": "mixkit_4832.mp4", "beats": 12, "hold": True}], "target_seconds": 10}
    try:
        RC.compose(sd, an, EP.Catalog.shared(), log=lambda *a: None)
        check("unknown section names are mapped (no crash)", sd["shots"][0]["section"] == "drop", sd["shots"][0]["section"])
    except Exception as err:  # noqa: BLE001
        check("unknown section names are mapped (no crash)", False, f"{type(err).__name__}: {err}")
    # 12. the front door: questions are routed and answered from the catalogue; edit types; sample styles
    from harness import catalog_qa as CQ, router as RT, taxonomy as TXN, reference as RF
    sp = CQ.parse("hey what are eye filters available?")
    check("catalogue: 'eye filters' are face effects on the eyes", sp["kinds"] == ["character_effect"] and sp["target"] == "eyes", sp)
    ans = CQ.ask("do you have glitch transitions?")
    check("catalogue: glitch transitions found, the working one first", ans["items"] and ans["items"][0]["state"] == "ready"
          and "glitch" in ans["items"][0]["en"].lower(), [i["en"] for i in ans["items"][:3]])
    calm = CQ.ask("which transition is best for a calm wedding film?")
    check("catalogue: a calm wedding gets dissolves, not film-strip effects", any("Dissolve" in i["en"] for i in calm["items"][:3]),
          [i["en"] for i in calm["items"][:3]])
    sup = CQ.ask("hey how many eyes filters available is there any superpowers eye effect i can apply?")
    check("catalogue: 'superpowers' means laser / lightning / electric eyes, answered first",
          sup["spec"]["target"] == "eyes" and "many" not in sup["spec"]["words"] and "Yes, superpower-style" in sup["text"]
          and "Lightning Eyes" in sup["text"].split("All of them")[0], sup["text"][:300])
    routes = {"what are eye filters available?": "catalog", "can you remove the green screen?": "capability",
              "what can you do?": "help", "make the lightning stronger": "revise"}
    got = {m: RT.route(m, (), last_draft="agent_x")["intent"] for m in routes}
    check("router: questions, capabilities, help and follow-ups", got == routes, got)
    check("router: 'like sample.mp4' is a style reference", RT.route("make a reel like sample.mp4", ("a.mp4",))["references"] == ["sample.mp4"])
    cap = RT.capability("can you add lightning to my eyes?")
    check("capability: VIP exact look named, working stand-ins offered", "VIP" in cap and "Cool Red Eyes" in cap, cap)
    kinds = {r: TXN.classify(r)["type"] for r in ("cut this podcast episode into a short", "wedding highlight film for Sara & Adam",
                                                 "1 minute gym motivation edit", "recipe video with step labels")}
    check("edit types from the request", list(kinds.values()) == ["podcast_clip", "wedding_film", "gym_motivation", "recipe"], kinds)
    fast = {"file": "a.mp4", "seconds": 30, "cuts_per_min": 50, "shot_median": 0.8, "shot_p25": 0.5, "shot_p75": 1.2, "flashes_per_min": 6,
            "dissolves_per_min": 0, "punches_per_min": 8, "shakes_per_min": 4, "slow_push_share": 0.1, "brightness": 0.25, "contrast": 0.5,
            "saturation": 0.3, "warmth": -0.05, "letterbox": 0, "vignette": 0.7, "grain": 3.0, "speech": False, "bpm": 140, "portrait": True}
    slow = {**fast, "cuts_per_min": 9, "shot_median": 5.5, "shot_p25": 4.0, "shot_p75": 7.0, "flashes_per_min": 0, "dissolves_per_min": 6,
            "punches_per_min": 0, "shakes_per_min": 0, "slow_push_share": 0.5, "brightness": 0.5, "bpm": 80, "letterbox": 0.2}
    pf, ps = RF.profile(fast), RF.profile(slow)
    check("sample style: a fast dark edit -> hype, 1-2 beats per shot", pf["style"] == "hype" and pf["beats_per_shot"]["drop"] <= 2, pf["beats_per_shot"])
    check("sample style: a slow edit with dissolves -> cinematic, long shots, dissolves",
          ps["style"] == "cinematic" and ps["beats_per_shot"]["verse"] >= 6 and any(r.get("family") == "dissolve" for r in ps["recipes"]), ps)
    from harness.awareness import off_brief
    fake = {f"f{i}": {"kind": "video", "file": f"f{i}.mp4", "summary": s} for i, s in
            enumerate(["A luxury white sports car on a highway", "A red sports car parked", "Close-up of a red sports car door", "A dashboard"])}
    ob = off_brief("a 1-minute ad for the red sports car", fake)
    check("off-brief footage: a white car in an ad for the red one", list(ob) == ["f0.mp4"], ob)
    wide = {"kind": "video", "width": 1280, "height": 720, "faces": []}
    v1, v2 = CU._vary(wide, 1, "9:16", 0, 2), CU._vary(wide, 2, "9:16", 0, 2)
    face = {**wide, "faces": [{"t": 1.0, "faces": [{"box": [0.4, 0.2, 0.2, 0.3]}]}]}
    check("re-used footage is framed differently (not over a face)", v1 and v2 and v1 != v2 and CU._vary(face, 1, "9:16", 0, 2) is None, (v1, v2))
    x = RC.Ctx([{"id": "a", "start": 0, "end": 30, "section": "drop"}], [i * 0.25 for i in range(120)], [i * 1.0 for i in range(30)], 0.0,
               [{"name": "drop", "start": 0, "end": 30}], STYLES["hype"], EP.Catalog.shared(), 30)
    fl = RC.r_flash(x, {"on": "beats"})
    gaps = [b["start"] - a["start"] for a, b in zip(fl, fl[1:])]
    check("flash: never a strobe (on bars, >= 1.5 s apart)", fl and min(gaps) >= RC.FLASH_GAP - 0.03, min(gaps) if gaps else None)

    print(f"\n{'all passed' if not FAILS else str(len(FAILS)) + ' failed: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
