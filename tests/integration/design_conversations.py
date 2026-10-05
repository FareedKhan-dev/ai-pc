"""Conversations with the design agent, each turn checked on what it made (the design's own measurements, the files):
a visiting card restyled, enlarged, given a QR code and edited, then exported for print; an Instagram post that gets
a photo, becomes a story and changes style; a YouTube thumbnail whose presenter is cut from a green screen;
certificates for a list of names; and, with the model, requests written the way people talk.

  .venv\\Scripts\\python.exe tests\\integration\\design_conversations.py [--offline]
"""
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
from PIL import Image  # noqa: E402

from ai_pc.design.designchat import DesignChat  # noqa: E402

OUT = ROOT / "out" / "_tests" / "design" / "conv"
BMW = ROOT / "media/josh-berquist-_4sWbzH5fp8-unsplash.jpg"
GS = ROOT / "media/derived/mixkit_28287_still_7.50.png"
RESULTS = []


class Turn:
    def __init__(self, c, reply):
        self.c, self.reply = c, reply
        self.v = c.cur()

    def says(self, *rx):
        return all(re.search(r, self.reply, re.I) for r in rx)

    def ok(self):
        return self.v is not None and not [x for x in self.v["checks"] if not x["ok"] and x["level"] == "fail"]

    def f(self, k):
        return self.v["spec"]["fields"].get(k)

    def last_export(self):
        return Path(self.c.state["exports"][-1]["path"]) if self.c.state["exports"] else None


def run(name, c, turns):
    print(f"\n== {name}")
    for msg, test in turns:
        t0 = time.perf_counter()
        reply = c.say(msg)
        t = Turn(c, reply)
        try:
            good, why = test(t)
        except Exception as e:  # noqa: BLE001
            good, why = False, f"{type(e).__name__}: {e}"
        RESULTS.append((name, msg, good))
        print(f"{'ok  ' if good else 'FAIL'} [{time.perf_counter() - t0:4.1f}s] {msg[:100]}" + ("" if good else f"\n       why: {why}\n       reply: {reply[:400]}"))


def card(planner):
    c = DesignChat.start(chats_dir=OUT, planner=planner)
    st = {}

    def first(t):
        st["name_px"] = t.v["fitted"]["name"]
        return (t.ok() and t.v["spec"]["kind"] == "card" and t.f("name") == "Ahmed Khan" and t.f("phone") == "0300-1234567" and len(t.v["files"]["png"]) == 2, "")

    def bigger(t):
        return (t.ok() and t.v["fitted"]["name"] > st["name_px"] * 1.15, f"{st['name_px']} -> {t.v['fitted']['name']}")

    run("a visiting card", c, [
        ("make a visiting card for Ahmed Khan, Sales Manager at Khan Electronics, 0300-1234567, ahmed@khanelectronics.pk, khanelectronics.pk", first),
        ("classic style in maroon", lambda t: (t.ok() and t.v["spec"]["style"] == "classic" and t.v["spec"]["palette"] == "maroon", "")),
        ("make the name bigger", bigger),
        ("add a QR code", lambda t: (t.ok() and any("QR code scans" in x["what"] and x["ok"] for x in t.v["checks"]), "")),
        ("change the phone to 0333-7654321", lambda t: (t.ok() and t.f("phone") == "0333-7654321", "")),
        ("export the pdf for printing", lambda t: (t.last_export().suffix == ".pdf" and t.says(r"3 mm bleed"), "")),
        ("undo", lambda t: (t.f("phone") == "0300-1234567", "")),
    ])


def post(planner):
    c = DesignChat.start(chats_dir=OUT, planner=planner, files=[BMW])
    run("a social post", c, [
        ("an instagram post for Khan Electronics 'Mega Summer Sale' 'Up to 30% off on ACs and LED TVs' 30% off 1-15 June, shop now",
         lambda t: (t.ok() and t.v["spec"]["kind"] == "post" and t.f("offer") == "30% OFF", "")),
        (f"use {BMW.name}", lambda t: (t.ok() and t.v["spec"]["style"] == "photo" and Image.open(t.v["files"]["png"][0]).size == (1080, 1080), "")),
        ("make it a story", lambda t: (t.ok() and Image.open(t.v["files"]["png"][0]).size == (1080, 1920), "")),
        ("try another style", lambda t: (t.ok() and t.v["spec"]["style"] == "headline", "")),
        ("sunset gradient", lambda t: (t.ok() and t.v["spec"].get("gradient") == "sunset", "")),
        ("save the png for whatsapp", lambda t: (t.last_export().suffix == ".jpg", "")),
    ])


def thumbnail(planner):
    c = DesignChat.start(chats_dir=OUT, planner=planner, files=[GS])
    run("a YouTube thumbnail", c, [
        (f"a youtube thumbnail saying I tried every AI tool, with {GS.name}", lambda t: (t.ok() and t.says(r"cut from the green backdrop"), "")),
        ("make the headline smaller", lambda t: (t.ok() and t.v["spec"]["sizes"].get("headline"), "")),
        ("make it blue", lambda t: (t.ok() and t.v["spec"]["palette"] == "blue", "")),
    ])


def certificates(planner):
    c = DesignChat.start(chats_dir=OUT, planner=planner)
    run("certificates", c, [
        ("a certificate of participation from Green Valley School for Ali Raza for taking part in the Science Fair 2026, signed by Mrs. Nadia Hussain, Principal",
         lambda t: (t.ok() and t.f("recipient") == "Ali Raza" and t.f("signer1") == "Mrs. Nadia Hussain, Principal", str(t.v["spec"]["fields"]))),
        ("certificates for these names: Ali Raza, Sara Khan, Muhammad Hamza Qureshi Siddiqui and Ayesha Noor", lambda t: (t.says(r"4 certificates", r"checked 3/3"), "")),
        ("export the pdf", lambda t: (t.last_export().suffix == ".pdf" and "4 certificates" in t.last_export().name, "")),
    ])


def with_model(planner):
    c = DesignChat.start(chats_dir=OUT, planner=planner)
    run("read by the model", c, [
        ("my uncle runs a bakery called Sweet Treats in Gulberg Lahore, his name is Tariq Mehmood and his number is 0321-5550000, make him a visiting card",
         lambda t: (t.ok() and t.v["spec"]["kind"] == "card" and t.f("phone") == "0321-5550000" and "Sweet Treats" in (t.f("company") or ""), str(t.v["spec"]["fields"]) if t.v else "")),
        ("we're opening a new branch next friday, make a post announcing it with a big grand opening headline",
         lambda t: (t.ok() and t.v["spec"]["kind"] in ("post", "portrait") and "open" in (t.f("headline") or "").lower(), str(t.v["spec"]["fields"]) if t.v else "")),
    ])


if __name__ == "__main__":
    offline = "--offline" in sys.argv
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    planner = None
    if not offline:
        from ai_pc.llm.planner import ChatPlanner
        planner = ChatPlanner()
    t0 = time.perf_counter()
    card(planner)
    post(planner)
    thumbnail(planner)
    certificates(planner)
    if not offline:
        with_model(planner)
    bad = [(n, m) for n, m, g in RESULTS if not g]
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} turns right in {time.perf_counter() - t0:.0f} s (AI ${usd:.4f})" + ("" if not bad else "\nFAILED: " + "; ".join(f"{n}: {m[:60]}" for n, m in bad)))
    sys.exit(1 if bad else 0)
