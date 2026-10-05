"""Conversations with the social lane in everyday words, each turn checked on what it did (versions shown, jobs made,
posts published, replies sent), with the cheap model reading what the rules cannot. The platforms are the test suite's
fake servers (no accounts, nothing really posted); the model is real.

  .venv\\Scripts\\python.exe tests\\integration\\social_conversations.py [--offline]
"""

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from social_fakes import LinkedInFake, MetaFake, XFake, YouTubeFake  # noqa: E402
from social_fixture import make  # noqa: E402
from social_suite import host_factory  # noqa: E402

from ai_pc.social.platforms import linkedin as LI  # noqa: E402
from ai_pc.social.platforms import meta as ME  # noqa: E402
from ai_pc.social.platforms import threads as TH  # noqa: E402
from ai_pc.social.platforms import xcom as XC  # noqa: E402
from ai_pc.social.platforms import youtube as YT  # noqa: E402
from ai_pc.social.socialchat import SocialChat  # noqa: E402
from ai_pc.social.store import Store  # noqa: E402

OUT = ROOT / "out" / "_tests" / "social_conv"
RESULTS = []


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
        for line in reply.splitlines()[:4]:
            print(f"       {line[:180]}")
        if not good:
            print(f"     why: {why}")


def main():
    planner = None
    if "--offline" not in sys.argv:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    m = make(ROOT / "out" / "_tests" / "social_media")
    for k in ("vertical.mp4", "square.jpg"):
        shutil.copyfile(m[k], OUT / k)
    t0 = time.time()
    st = Store(OUT / "social.db")
    mf, yf, lf, xf = MetaFake(), YouTubeFake(), LinkedInFake(), XFake()
    creds = {
        "page_id": "PAGE1",
        "page_token": "EAAPAGE",
        "user_token": "EAAUSER",
        "app_id": "APP1",
        "ig_id": "IG1",
        "ig_mode": "facebook",
        "live": True,
    }
    ig = ME.Instagram(creds=dict(creds), transport=mf.transport(), store=st, pause=lambda s: None)
    th = TH.Threads(creds={"access_token": "TH"}, transport=mf.transport(), store=st, pause=lambda s: None)
    ig._host_factory = th._host_factory = host_factory
    plats = {
        "facebook": ME.Facebook(creds=dict(creds), transport=mf.transport(), store=st, pause=lambda s: None),
        "instagram": ig,
        "threads": th,
        "youtube": YT.YouTube(creds={"access_token": "ya29"}, transport=yf.transport(), store=st, pause=lambda s: None),
        "linkedin": LI.LinkedIn(creds={"access_token": "AQ"}, transport=lf.transport(), store=st, pause=lambda s: None),
        "x": XC.X(creds={"access_token": "x"}, transport=xf.transport(), store=st, pause=lambda s: None),
    }
    c = SocialChat.start(
        planner=planner, chats_dir=OUT / "chats", platforms=plats, store=st, files=[OUT / "vertical.mp4", OUT / "square.jpg"], budget=20
    )

    def versions(*want):
        def t(c, r):
            return all(w in r for w in want) and r.startswith(("Ready to post", "Ready to schedule")), r[:300]

        return t

    def published(*want):
        def t(c, r):
            return all(w in r for w in want) and "CANNOT" not in r, r[:300]

        return t

    def short_title(c, r):
        p = c.state.get("pending") or {}
        post = p.get("post") or {}
        return "YouTube Short" in r and (post.get("title") or "").lower().startswith("eid sale 2026"), (post.get("title"), r[:200])

    def scheduled_two(c, r):
        p = c.state.get("pending") or {}
        return {t["platform"] for t in p.get("targets") or []} == {"linkedin", "threads"} and bool(
            (p.get("post") or {}).get("when")
        ) and "New stock arrived" in (p.get("post") or {}).get("text", ""), r[:300]

    def numbers(c, r):
        return "views" in r and "Last 7 days" in r, r[:300]

    def listed(c, r):
        return "New comments" in r and "1. " in r, r[:300]

    def reply_ready(c, r):
        p = c.state.get("pending") or {}
        return r.startswith("Ready to reply") and "thanks" in (p.get("text") or "").lower(), (p, r[:200])

    def replied(c, r):
        return r.startswith("Replied on"), r[:200]

    def delete_ready(c, r):
        return r.startswith("Ready to DELETE") and "Facebook" in r, r[:200]

    run(
        "a shop's week on social media",
        c,
        [
            (
                "can you put my new reel on insta and fb? the file is vertical.mp4, caption: Eid Mubarak from Khan Electronics",
                versions("Instagram reel", "Facebook reel"),
            ),
            ("yes", published("Instagram reel: published", "Facebook reel: published")),
            ("make my eid video vertical.mp4 a youtube short titled 'Eid Sale 2026'", short_title),
            ("yes", published("YouTube Short: published")),
            ("share square.jpg on linkedin and threads tomorrow 9am with the text 'New stock arrived'", scheduled_two),
            ("no", lambda c, r: (r.startswith("Dropped"), r)),
            ("tweet 'Shop open till 10 pm tonight'", versions("X post", "X charges $0.015")),
            ("yes", published("X post: published")),
            ("how are my posts doing this week", numbers),
            ("show me the comments", listed),
            ("reply to the first one saying thanks a lot, see you at the shop", reply_ready),
            ("yes", replied),
        ],
    )
    ok = sum(1 for *_, g in RESULTS if g)
    usd = planner.cost()[1] if planner is not None else 0.0
    print(f"\n{ok}/{len(RESULTS)} turns right in {time.time() - t0:.0f} s; model ${usd:.4f}")
    st.close()
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
