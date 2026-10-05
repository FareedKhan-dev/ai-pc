"""The template explorer: reading a CapCut template's page politely, what its title and hashtags ask for, templates made
from a page, the clip count of a page constraining what is learned from a video, and suggestions.

  .venv\\Scripts\\python.exe tests\\test_template_explorer.py [--offline]
No network: CapCut's robots.txt and the SLOWMO HDR page are read from state/templates/pages (saved by `template add`).
--offline skips the one vision call (a screenshot of a template page, drawn here) and the learned-tag model call.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

from harness import analyze as AN  # noqa: E402
from harness import editplan as EP  # noqa: E402
from harness import template as TP  # noqa: E402
from harness import template_meta as TM  # noqa: E402
from harness import trends as TR  # noqa: E402

FAILS = []
TID = "7644532345902533908"
LINK = f"https://www.capcut.com/template-detail/{TID}"


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def no_network(*a, **k):
    raise OSError("the tests do not go online")


def page_rules():
    TM._get = no_network  # robots.txt and the page come from the saved copies
    check("a tracked share link is cleaned to the template's page",
          TM.clean_url(LINK + "?from_page=template_detail&enter_from=share&page=3") == (TID, LINK))
    check("a regional, slugged link is cleaned too", TM.clean_url(f"https://www.capcut.com/id-id/template-detail/slowmo-hdr/{TID}?x=1")[1] == LINK)
    for bad in ("https://www.capcut.com/templates/eid", "https://www.capcut.com/explore/all-template-CapCut/7497638645038794768?page=3",
                "https://www.capcut.com/t/Zs8abc/", "https://example.com/template-detail/123456789"):
        try:
            TM.clean_url(bad)
            check(f"refused: {bad[:60]}", False, "accepted")
        except TM.NotAllowed:
            check(f"refused: {bad[:60]}", True)
    check("robots.txt allows the clean page", TM.allowed(LINK))
    check("robots.txt refuses a page with tracking parameters", not TM.allowed(LINK + "?from_page=template_detail"))
    check("robots.txt refuses the /templates/ listing", not TM.allowed("https://www.capcut.com/templates/eid"))
    meta = TM.from_link(LINK + "?from_page=x", max_age_s=10 ** 9)
    check("the page's own record, not a related template's", meta.get("title", "").startswith("SLOWMO HDR"), meta.get("title"))
    check("clips, length, size and tags read", meta.get("clips") == 4 and abs((meta.get("seconds") or 0) - 14.58) < 0.05 and meta.get("aspect") == "9:16"
          and {"slowmo", "eid"} <= set(meta.get("tags") or []), str(meta))
    check("uses and author read", (meta.get("uses") or 0) >= 1_000_000 and "BxL" in str(meta.get("author")), str(meta.get("uses")))
    t = TM.from_text("SLOWMO HDR, 4 clips, 0:15, 9:16 #slowmo #eid")
    check("a typed description", t["clips"] == 4 and t["seconds"] == 15 and t["aspect"] == "9:16" and t["tags"] == ["eid", "slowmo"]
          and t["title"] == "SLOWMO HDR", str(t))
    return meta


def techniques(planner):
    t = TR.techniques("SLOWMO HDR ❤️‍🔥", ["bxl", "eid", "foryou", "slowmo"])
    st = t["settings"]
    check("slow motion from the title", st.get("speed") == 0.45)
    check("the title's look leads (HDR), the tag's is kept aside", "HDR" in st.get("look", "") and "festive" not in st["look"]
          and "festive" in st.get("look_also", ""), str(st))
    check("the occasion's greeting", st.get("greeting") == "Eid Mubarak")
    check("#foryou says nothing about the edit", "foryou" not in t["unknown"] and not any(m[0] == "foryou" for m in t["matched"]))
    check("3D zoom is a slow push, not punches", TR.techniques("3D zoom")["settings"] == {"push": 1.18})
    check("velocity is a speed ramp", TR.techniques("Velocity edit")["settings"].get("ramp") == "fast-slow-fast")
    check("a song title says nothing", TR.techniques("JANE TU KAHAN HAI", ["trending", "viral", "foryou"])["settings"] == {})

    class Fake:  # the model's answer for unknown tags: only known settings, in range, are kept
        def _call(self, tier, msgs):
            class R:
                text = '{"qqsparkle": {"look": "sparkly glow", "speed": 5, "bogus": 1, "cut": "explode"}, "qqhandle": {}}'
            return R()
    store = TR.STORE
    with tempfile.TemporaryDirectory() as d:
        TR.STORE = Path(d) / "trends.json"
        t2 = TR.techniques("x", ["qqsparkle", "qqhandle"], planner=Fake())
        check("a learned tag keeps only valid settings", t2["settings"] == {"look": "sparkly glow"} and not t2["unknown"], str(t2))
    TR.STORE = store
    if planner is not None:
        with tempfile.TemporaryDirectory() as d:
            TR.STORE = Path(d) / "trends.json"
            t3 = TR.techniques("x", ["hyperlapse"], planner=planner)
            TR.STORE = store
            check("the cheap model maps an unknown tag", not t3["unknown"], str(t3))


def from_page(meta, an):
    tpl = TP.from_meta(meta, name="test_explorer_slowmo", log=lambda *a: None)
    try:
        s = tpl["slots"]
        check("as many slots as the page says", len(s) == 4)
        check("the page's length", abs(tpl["seconds"] - 14.58) < 0.01)
        check("slots in whole beats at the style's tempo", all(abs(x["dur"] / (60 / tpl["bpm"]) - round(x["dur"] / (60 / tpl["bpm"]))) < 0.02 for x in s[:-1]),
              str([x["dur"] for x in s]))
        check("marked as not exact", tpl["exact"] is False and tpl["notes"])
        plan, info = TP.fill(tpl, dict(an), "make my eid video", log=lambda *a: None)
        sp = [c.get("speed") for c in plan["clips"]]
        check("every slot in slow motion", all(x == 0.45 for x in sp), str(sp))
        R = EP.resolve(plan, dict(an, **{k: v for k, v in an.items()}))
        check("the plan resolves to the template's length", abs(R["end"] - 14.58) < 0.05, f"{R['end']}")
        spans = {}
        for c in R["clips"]:
            for pc in c["pieces"]:
                spans.setdefault(pc["path"], []).append((pc["src_from"], pc["src_from"] + pc["src_span"]))
        overlap = any(a0 < b1 - 0.05 and b0 < a1 - 0.05 for v in spans.values() for i, (a0, a1) in enumerate(v) for (b0, b1) in v[i + 1:])
        check("no moment used twice (slow motion plays less of each file)", not overlap)
        check("slowed pieces play dur x 0.45 of the file", all(abs(pc["src_span"] - pc["dur"] * pc["speed"]) < 0.01 for c in R["clips"] for pc in c["pieces"]))
        grade = next((e for e in plan["edits"] if e["id"] == "tgrade"), {})
        check("the HDR look's filter", grade.get("name") == "高清明亮", grade.get("name"))
        check("the greeting is offered, not added", not any(e["id"] == "tgreet" for e in plan["edits"]) and info["offers"])
        plan2, _ = TP.fill(tpl, dict(an), "eid video, add the greeting", log=lambda *a: None)
        check("the greeting when asked", any(e.get("text") == "Eid Mubarak" for e in plan2["edits"]))
        plan3, _ = TP.fill(tpl, dict(an), "no slow motion please", log=lambda *a: None)
        check("normal speed when asked", all(c.get("speed") is None for c in plan3["clips"]))
        plan4, _ = TP.fill(tpl, dict(an), "", speed="ramp", log=lambda *a: None)
        check("speed ramps when chosen", all(len(c.get("ramp") or []) == 3 for c in plan4["clips"] if c.get("from") is not None))
        plan5, _ = TP.fill(tpl, dict(an), "title 'SARA & ADAM'", log=lambda *a: None)
        check("the client's title over the opening (the page shows no text)", any(e.get("text") == "SARA & ADAM" and e["start"] < 1 for e in plan5["edits"]))
    finally:
        p = TP.STORE / "test_explorer_slowmo.json"
        if p.exists():
            p.unlink()


def constrain():
    cuts = [{"frame": f, "t": f / 30, "kind": "cut", "dur": 0.0, "conf": c} for f, c in ((30, 2.9), (60, 1.1), (90, 2.8), (120, 2.7))]
    out, notes = TP.constrain_cuts(cuts, 3, [], 150, 30.0)
    check("too many cuts: the least sure goes", [c["frame"] for c in out] == [30, 90, 120] and notes)
    rej = [{"frame": 75, "kind": "cut", "score": 7.0}, {"frame": 100, "kind": "soft", "score": 9.0}, {"frame": 31, "kind": "cut", "score": 9.0}]
    out, notes = TP.constrain_cuts(cuts[:1] + cuts[2:3], 3, rej, 150, 30.0, beats=[i * 0.5 for i in range(11)])
    fr = [c["frame"] for c in out]
    check("too few: a strong rejected hard cut comes back (not a soft one, not one too close)", 75 in fr and 100 not in fr and 31 not in fr, str(fr))
    out, _ = TP.constrain_cuts([], 2, [], 150, 30.0, beats=[i * 0.5 for i in range(11)])
    check("none visible: the longest shot is cut on a beat, marked guessed", len(out) == 2 and all(c.get("guessed") for c in out)
          and all(c["frame"] % 15 == 0 for c in out), str([c["frame"] for c in out]))


def learn_with_count():
    v = ROOT / "out" / "video" / "agent_thetwoseas_200445.mp4"
    if not v.exists():
        print("skip learn with a clip count (no video)")
        return
    t = TP.learn(v, None, meta={"clips": 14, "title": "two seas", "tags": ["travel"]}, log=lambda *a: None)
    check("learned with the page's clip count: exactly that many slots", len(t["slots"]) == 14, f"{len(t['slots'])}")
    check("the page's techniques are attached", (t.get("techniques") or {}).get("settings", {}).get("look"))


def suggestions(an):
    s = TP.suggest("slow motion eid video, 4 clips", an)
    check("slow motion eid -> slowmo_hdr first", s and s[0]["name"] == "slowmo_hdr", str([(x["name"], x["score"]) for x in s]))
    s = TP.suggest("gym hype edit with fast cuts", an)
    check("gym hype -> gym_hype first", s and s[0]["name"] == "gym_hype", str([(x["name"], x["score"]) for x in s]))
    t = TP.resolve(LINK + "?from_page=abc", None, log=lambda *a: None)
    check("a link to a template in the library resolves offline", t["name"] == "slowmo_hdr")


def speed_check():
    """The verifier sees slow motion: a real 0.45x export passes; a 1x export whose map claims 0.45x fails."""
    import copy
    from harness import verify as V
    from harness.studio import load
    for draft, fake, want in (("agent_tpl_123913", False, "pass"), ("agent_road_195510", True, "fail")):
        try:
            s = load(draft)
        except Exception:  # noqa: BLE001
            s = None
        if not s or not Path(str((s.get("export") or {}).get("path"))).exists():
            print(f"skip speed check on {draft} (no export)")
            continue
        m = copy.deepcopy(s["map"])
        c = max((c for c in m["clips"] if not c.get("overlay") and all(pc["kind"] == "video" for pc in c["pieces"])), key=lambda c: c["end"] - c["start"])
        if fake:  # the map says 0.45x, the render played 1x
            for pc in c["pieces"]:
                pc["speed"] = 0.45
        r = V.Verifier(s["export"]["path"], m, None, lambda *a: None, vlm=False).check_speed(c)
        check(f"speed check: {want} on {'a 1x export claimed as 0.45x' if fake else 'the slow-motion export'}", r["status"] == want, f"{r['status']}: {r['why']}")


def screenshot(planner):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 700), (18, 18, 18))
    d = ImageDraw.Draw(img)
    big = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 44)
    mid = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 28)
    d.rectangle([40, 40, 380, 640], fill=(70, 60, 50))
    d.text((60, 600), "00:15", font=mid, fill=(255, 255, 255))
    d.text((420, 60), "SLOWMO HDR", font=big, fill=(255, 255, 255))
    d.text((420, 130), "BxL_Capcut", font=mid, fill=(200, 200, 200))
    d.text((420, 190), "#slowmo #eid #bxl #foryou", font=mid, fill=(120, 170, 255))
    d.text((420, 260), "4 clips   1.06M uses", font=mid, fill=(220, 220, 220))
    d.rounded_rectangle([420, 330, 800, 390], 20, fill=(0, 200, 230))
    d.text((470, 340), "Use template in CapCut", font=mid, fill=(0, 0, 0))
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "page.png"
        img.save(p)
        m = TM.from_image(p, planner)
    check("a screenshot read: title, clips, uses, tags", "SLOWMO" in str(m.get("title")).upper() and m.get("clips") == 4
          and (m.get("uses") or 0) >= 1_000_000 and {"slowmo", "eid"} <= set(m.get("tags") or []), str(m))


def main():
    offline = "--offline" in sys.argv
    planner = None
    if not offline:
        from harness.planner import ChatPlanner
        planner = ChatPlanner()
    meta = page_rules()
    techniques(planner)
    from harness.studio import load
    files = [f for f in load("agent_saraadamfo_181609")["files"] if "music_" not in f]
    an = AN.analyze(sorted(set(files)), planner=None, log=lambda *a: None)
    from_page(meta, an)
    constrain()
    learn_with_count()
    suggestions(an)
    speed_check()
    if planner is not None:
        screenshot(planner)
        print(f"AI cost ${planner.cost()[1]:.4f}")
    print(f"\n{'ALL OK' if not FAILS else f'{len(FAILS)} FAILED: ' + '; '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
