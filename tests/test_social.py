"""Social media lane: the parts every platform shares, then each platform against a fake server built from its API docs.

  .venv\\Scripts\\python.exe tests\\test_social.py
Nothing here needs keys or the network; everything is written under out\\_tests\\social.
"""
import datetime as dt
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness.social import runner as RN  # noqa: E402
from harness.social import text as TX  # noqa: E402
from harness.social.base import Platform, SocialError  # noqa: E402
from harness.social.store import Store, iso  # noqa: E402

OUT = ROOT / "out" / "_tests" / "social"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not detail else f"\n     why: {str(detail)[:600]}"))


# ---------------------------------------------------------------- words
def words():
    check("text: X counts a link as 23 whatever its length", TX.x_length("see https://example.com/a/very/long/path?with=query&and=more") == 4 + 23)
    check("text: X counts an emoji (even a joined family) as 2", TX.x_length("hi \U0001F468‍\U0001F469‍\U0001F467") == 3 + 2)
    check("text: X counts Urdu letters as 1 each", TX.x_length("سلام") == 4)
    check("text: X counts Chinese characters as 2 each", TX.x_length("你好") == 4)
    long = " ".join(f"Sentence number {i} says something useful about our Eid sale." for i in range(1, 15))
    parts = TX.split_thread(long, 280)
    check("text: a long post becomes a numbered thread, every part within 280", len(parts) >= 3 and all(TX.x_length(p) <= 280 for p in parts)
          and parts[0].endswith(f"(1/{len(parts)})") and " ".join(p.rsplit(" (", 1)[0] for p in parts) == long, [TX.x_length(p) for p in parts])
    check("text: LinkedIn's reserved characters are escaped, a #hashtag stays one", TX.linkedin_escape("Sale (50%) #eid @ali [new] a#b") ==
          "Sale \\(50%\\) #eid \\@ali \\[new\\] a\\#b")
    check("text: Threads counts an emoji as its UTF-8 bytes", TX.count("hi \U0001F44D", "threads") == 7)
    t = TX.add_utm("Shop now: https://khanelectronics.pk/sale?ref=1. Follow https://instagram.com/khan", "instagram", "eid")
    check("text: your own links are tagged for tracking, social links are not", "https://khanelectronics.pk/sale?ref=1&utm_source=instagram&utm_medium=social"
          "&utm_campaign=eid." in t and "https://instagram.com/khan" in t and t.count("utm_") == 3, t)
    lim = {"label": "Instagram", "chars": 2200, "hashtags": 5, "links": "dead", "how": "utf16"}
    r = TX.fit("New stock " + " ".join(f"#tag{i}" for i in range(7)) + " https://x.pk", "instagram", "photo", lim)
    check("text: too many hashtags is a problem, a dead link a note", any("7 hashtags" in p for p in r["problems"]) and any("not make links" in n for n in r["notes"]), r)
    r = TX.fit("A" * 300, "x", "post", {"label": "X", "chars": 280, "how": "x", "thread": True})
    check("text: too long for X goes as a thread, not cut", r["parts"] and not r["problems"], r)
    r = TX.fit("B" * 3100, "linkedin", "post", {"label": "LinkedIn", "chars": 3000})
    check("text: too long where threads do not exist is a problem to fix, not a silent cut", r["problems"] and r["text"] == "B" * 3100)
    r = TX.fit("Our biggest Eid sale ever is live now in all branches across Lahore, Karachi and Islamabad with prices you will not believe\nmore",
               "youtube", "video", {"label": "YouTube", "chars": 5000, "how": "bytes", "needs_title": True, "title_chars": 100})
    check("text: a title made from the first line, shortened at a word", r["title"].endswith("…") and len(r["title"]) <= 100, r["title"])


# ---------------------------------------------------------------- the runner
class Scripted(Platform):
    """A platform that answers from a script, to test the runner's handling of every outcome."""
    name, label, native_schedule = "fake", "Fake", True

    def __init__(self, script, store):
        super().__init__(creds={"token": "x"}, store=store)
        self.script, self.calls = list(script), []

    def publish(self, job, post, prepared, budget=120):
        self.calls.append(dict(job.get("remote") or {}))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if step.get("checkpoint"):
            self.checkpoint(job, **step["checkpoint"])
        return step["result"]

    def status(self, job):
        return {"status": "published", "permalink": "https://fake/p/9"}


def runner():
    db_path = OUT / "runner.db"
    db_path.unlink(missing_ok=True)
    st = Store(db_path)
    prep = lambda post, job: {"media": [], "text": post["text"], "problems": [], "notes": []}  # noqa: E731
    t0 = dt.datetime(2026, 10, 5, 12, 0).astimezone()

    def new(text, when=None, native=False):
        p = st.add_post({"text": text, "when": iso(when) if when else None, "status": "queued"})
        j = st.add_job({"post_id": p["id"], "platform": "fake", "format": "post", "native": native})
        return p, j
    # processing, then published; the container made in the first call is reused, not made again
    p, j = new("hello")
    f = Scripted([{"result": {"status": "processing", "wait": 30}, "checkpoint": {"container": "C1"}},
                  {"result": {"status": "published", "id": "P1", "permalink": "https://fake/p/1"}}], st)
    RN.run(st, {"fake": f}, prep, at=t0)
    check("runner: a post still processing waits and is asked again", st.job(j["id"])["status"] == "processing" and st.job(j["id"])["next_try"] > iso(t0))
    RN.run(st, {"fake": f}, prep, at=t0 + dt.timedelta(seconds=10))
    check("runner: not asked again before its time", len(f.calls) == 1)
    RN.run(st, {"fake": f}, prep, at=t0 + dt.timedelta(seconds=40))
    jj = st.job(j["id"])
    check("runner: then published, with its link, attempted once (polls are not attempts)", jj["status"] == "published" and
          jj["remote"]["permalink"] == "https://fake/p/1" and jj["attempts"] == 1, jj)
    check("runner: the second call saw the first call's container (no double post)", f.calls[1].get("container") == "C1", f.calls)
    check("runner: the post is marked published", st.post(p["id"])["status"] == "published")
    # a passing failure waits 1 minute, then 5; an expired sign-in waits for the person; a refused post fails with its reason
    p, j = new("retry me")
    f = Scripted([SocialError("retry", "network down"), SocialError("retry", "still down"), {"result": {"status": "published", "id": "P2"}}], st)
    RN.run(st, {"fake": f}, prep, at=t0)
    a = st.job(j["id"])
    RN.run(st, {"fake": f}, prep, at=t0 + dt.timedelta(seconds=61))
    b = st.job(j["id"])
    RN.run(st, {"fake": f}, prep, at=t0 + dt.timedelta(seconds=61 + 301))
    check("runner: failures wait 1 then 5 minutes, then it goes out", a["status"] == "retry" and a["next_try"] == iso(t0 + dt.timedelta(seconds=60))
          and b["next_try"] == iso(t0 + dt.timedelta(seconds=61 + 300)) and st.job(j["id"])["status"] == "published", (a["next_try"], b["next_try"]))
    p, j = new("rate limited")
    RN.run(st, {"fake": Scripted([SocialError("limit", "slow down", retry_after=900)], st)}, prep, at=t0)
    check("runner: a rate limit waits as long as the platform asks", st.job(j["id"])["next_try"] == iso(t0 + dt.timedelta(seconds=900)))
    p, j = new("expired")
    RN.run(st, {"fake": Scripted([SocialError("auth", "token expired")], st)}, prep, at=t0)
    check("runner: an expired sign-in waits for you (not retried)", st.job(j["id"])["status"] == "needs_signin" and not st.due(t0 + dt.timedelta(days=1))
          or all(x["id"] != j["id"] for x in st.due(t0 + dt.timedelta(days=1))))
    p, j = new("refused")
    RN.run(st, {"fake": Scripted([SocialError("invalid", "caption too long")], st)}, prep, at=t0)
    check("runner: a refused post fails with the reason", st.job(j["id"])["status"] == "failed" and "caption too long" in st.job(j["id"])["error"])
    p, j = new("crash")
    RN.run(st, {"fake": Scripted([ZeroDivisionError("bug")], st)}, prep, at=t0)
    check("runner: an unforeseen error is kept and retried, its trace logged", st.job(j["id"])["status"] == "retry" and
          any(e["kind"] == "error" and "ZeroDivisionError" in e["detail"] for e in st.events(j["id"])))
    # scheduled: waits for its time; a native one is uploaded at once and the platform publishes it
    p, j = new("later", when=t0 + dt.timedelta(hours=3))
    f = Scripted([{"result": {"status": "published", "id": "P3"}}], st)
    RN.run(st, {"fake": f}, prep, at=t0)
    check("runner: a scheduled post waits for its time", st.job(j["id"])["status"] == "pending" and not f.calls)
    RN.run(st, {"fake": f}, prep, at=t0 + dt.timedelta(hours=3, minutes=1))
    check("runner: and goes out when it comes", st.job(j["id"])["status"] == "published")
    p, j = new("native", when=t0 + dt.timedelta(days=1), native=True)
    f = Scripted([{"result": {"status": "scheduled", "id": "S1", "publish_at": iso(t0 + dt.timedelta(days=1))}}], st)
    RN.run(st, {"fake": f}, prep, at=t0)
    check("runner: a post the platform can schedule is uploaded at once and scheduled there", st.job(j["id"])["status"] == "scheduled" and
          st.post(p["id"])["status"] == "scheduled")
    RN.refresh(st, {"fake": f}, at=t0 + dt.timedelta(hours=2))
    check("runner: not checked before its time", st.job(j["id"])["status"] == "scheduled")
    RN.refresh(st, {"fake": f}, at=t0 + dt.timedelta(days=1, minutes=5))
    check("runner: after its time it is confirmed published, with its link", st.job(j["id"])["status"] == "published" and
          st.job(j["id"])["remote"]["permalink"] == "https://fake/p/9")
    # a post that cannot be prepared fails before anything is uploaded
    p, j = new("bad media")
    bad = lambda post, job: {"problems": ["the video is 18:00; Reels takes up to 15:00"]}  # noqa: E731
    f = Scripted([{"result": {"status": "published"}}], st)
    RN.run(st, {"fake": f}, bad, at=t0)
    check("runner: media a platform cannot take stops the job before uploading", st.job(j["id"])["status"] == "failed" and not f.calls and
          "15:00" in st.job(j["id"])["error"])
    # one runner at a time
    lock = OUT / "run.lock"
    lock.unlink(missing_ok=True)
    with RN.Lock(lock):
        try:
            with RN.Lock(lock):
                check("runner: a second runner is refused while one works", False)
        except RN.Busy:
            check("runner: a second runner is refused while one works", True)
    check("runner: the lock is released afterwards", not lock.exists())
    st.close()


def main():
    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    words()
    runner()
    from social_fixture import make
    from social_suite import run_all
    run_all(check, make(ROOT / "out" / "_tests" / "social_media"), OUT)
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not bad else f'{len(bad)} FAILED'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)}, {time.time() - t0:.0f} s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
