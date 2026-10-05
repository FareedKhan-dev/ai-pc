"""Conversations that make web projects from designs and then change them with the cheap model, each turn checked on
the files it left (not on what it said): a Figma landing page whose button is recoloured and heading reworded, measured
against the design again and undone; a Canva sale page whose button text is changed.

  .venv\\Scripts\\python.exe tests\\integration\\design2code_conversations.py [--offline]
About two minutes. The Figma and Canva servers are the test suite's fakes (no account needed); the model is real.
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_design2code as TD  # noqa: E402
from design_fixture import landing, pictures  # noqa: E402
from pptx_fixture import make as make_pptx  # noqa: E402

from ai_pc.coding import fromdesign as FD  # noqa: E402
from ai_pc.coding.codechat import CodeChat  # noqa: E402
from ai_pc.hub.services import canva as CV  # noqa: E402
from ai_pc.hub.services import figma as FG  # noqa: E402

OUT = ROOT / "out" / "_tests" / "design2code" / "conv"
RESULTS = []


def rule(proj, cls):
    css = (Path(proj) / "styles.css").read_text(encoding="utf-8")
    m = re.search(r"(?:^|\n)[^{}]*\." + re.escape(cls) + r"(?![\w-])[^{}]*\{([^{}]*)\}", css)
    return m.group(1) if m else ""


def greenish(text):
    if re.search(r"\bgreen\b|\blime\b|\bseagreen\b|\bforestgreen\b|\bdarkgreen\b", text, re.I):
        return True
    for h in re.findall(r"#([0-9a-fA-F]{6})\b", text):
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        if g > r + 40 and g > b + 20:
            return True
    for r, g, b in re.findall(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text):
        if int(g) > int(r) + 40 and int(g) > int(b) + 20:
            return True
    return False


def loads(c):
    return not [x for x in c.state.get("last_checks") or [] if not x["ok"] and x["level"] == "fail"]


def run(name, c, turns):
    print(f"\n== {name}")
    for msg, test in turns:
        t0 = time.perf_counter()
        reply = c.say(msg)
        try:
            good, why = test(c, reply)
        except Exception as e:  # noqa: BLE001
            good, why = False, f"{type(e).__name__}: {e}"
        RESULTS.append((name, msg, good))
        llm = " [model]" if (c.last_turn or {}).get("llm") else ""
        print(f"{'ok  ' if good else 'FAIL'} > {msg}{llm}  ({time.perf_counter() - t0:.0f} s)")
        for line in reply.splitlines()[:3]:
            print(f"       {line[:200]}")
        if not good:
            print(f"     why: {why}")


def main():
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    TD.rmtree(OUT)
    OUT.mkdir(parents=True)
    olds = (FG.CACHE, CV.EXPORTS, FD.WORK)
    FG.CACHE, CV.EXPORTS, FD.WORK = OUT / "figma_cache", OUT / "canva_exports", OUT / "work"
    CV.Canva.pause = staticmethod(lambda s: None)
    t0 = time.time()
    try:
        # the design's own picture (for the Figma fake) and the Canva design's PowerPoint and pages
        from ai_pc.coding import design2code as D
        from ai_pc.coding import designcheck as DC
        from ai_pc.office import render
        doc, nid = landing()
        imgs = pictures(OUT / "pics")
        ref_proj = OUT / "reference_page"
        page = D.build(doc, nid, imgs)
        page.write(ref_proj, D.google_fonts(page.fonts, ref_proj)[0])
        DC.check(ref_proj)
        figma_png = (ref_proj / ".out" / "page.png").read_bytes()
        deck = make_pptx(OUT / "sale.pptx", imgs["hero-photo"])
        (OUT / "ref").mkdir()
        render.office({"app": "powerpoint", "src": str(deck.resolve()), "png_dir": str((OUT / "ref").resolve()), "png_width": 1920}, timeout=180)
        refs = {i: str(OUT / "ref" / f"slide{i:03d}.png") for i in (1, 2)}
        f = FG.Figma(creds={"token": "figd_TEST"}, transport=TD.figma_fake(doc, figma_png, ["2001"]))
        cv = CV.Canva(creds={"access_token": "CANVA_TEST"}, transport=TD.canva_fake(deck, refs))
        link = f"https://www.figma.com/design/{TD.KEY}/Khan-Electronics?node-id=0-1"

        c = CodeChat.start(planner=planner, chats_dir=OUT / "chats", projects_dir=OUT / "projects", connectors={"figma": f, "canva": cv})

        def made(c, r):
            p = c.state.get("project")
            return bool(p) and (Path(p) / "index.html").exists() and "37/37 elements" in r and loads(c), r[:200]

        def green(c, r):
            body = rule(c.state["project"], "call-button")
            return greenish(body) and "#2563eb" not in body.lower() and loads(c), body.strip()[:300]

        def heading(c, r):
            h = (Path(c.state["project"]) / "index.html").read_text(encoding="utf-8")
            return "Lowest prices in Lahore" in h and "Best prices in town" not in h and loads(c), re.findall(r"<h1[^>]*>.*?</h1>", h)

        def measured(c, r):
            return r.startswith("Differs from the design") and "Title" in r, r[:300]

        def undone(c, r):
            h = (Path(c.state["project"]) / "index.html").read_text(encoding="utf-8")
            return "Best prices in town" in h and "Took back" in r, r[:200]
        run("a Figma landing page, then changes", c, [
            (f"make a website from this figma design {link}", made),
            ("make the call now button green", green),
            ("change the main heading to 'Lowest prices in Lahore'", heading),
            ("does it still match the design?", measured),
            ("undo", undone),
        ])

        c = CodeChat.start(planner=planner, chats_dir=OUT / "chats", projects_dir=OUT / "projects", connectors={"figma": f, "canva": cv})

        def canva_made(c, r):
            p = c.state.get("project")
            return bool(p) and "from the Canva design 'Eid sale'" in r and "elements where the design puts them" in r and loads(c), r[:200]

        def order_now(c, r):
            h = (Path(c.state["project"]) / "index.html").read_text(encoding="utf-8")
            return "Order now" in h and "Shop now" not in h and loads(c), re.findall(r"<span[^>]*>[^<]*now[^<]*</span>", h, re.I)
        run("a Canva sale page, then a change", c, [
            ("turn my canva design 'Eid sale' into a web page", canva_made),
            ("make the shop now button say 'Order now'", order_now),
        ])
    finally:
        FG.CACHE, CV.EXPORTS, FD.WORK = olds
    ok = sum(1 for *_, g in RESULTS if g)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{ok}/{len(RESULTS)} turns right in {time.time() - t0:.0f} s; model ${usd:.4f}")
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
