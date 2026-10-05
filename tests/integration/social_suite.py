"""The platform half of tests/integration/test_social.py: media fitted with real files, every connector against its fake server,
sign-ins, the temporary media host, posts never sent twice, the tunnel installer's checks, and the chat end to end."""

import base64
import datetime as dt
import hashlib
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image
from social_fakes import LinkedInFake, MetaFake, TikTokFake, XFake, YouTubeFake

from ai_pc.convert import media as MD
from ai_pc.social import auth as AU
from ai_pc.social import runner as RN
from ai_pc.social.base import SocialError
from ai_pc.social.mediahost import MediaHost
from ai_pc.social.platforms import linkedin as LI
from ai_pc.social.platforms import meta as ME
from ai_pc.social.platforms import threads as TH
from ai_pc.social.platforms import tiktok as TT
from ai_pc.social.platforms import xcom as XC
from ai_pc.social.platforms import youtube as YT
from ai_pc.social.prepare import prepare
from ai_pc.social.store import Store, iso, now

NOPAUSE = staticmethod(lambda s: None)


class _Proc:
    def terminate(self):
        pass


def fake_launcher(local):
    """Cloudflare's tunnel stood in for: the 'public' address is the local server itself (so the fakes can really fetch it)."""
    return _Proc(), local


def host_factory():
    return MediaHost(mode="tunnel", launcher=fake_launcher)


# ---------------------------------------------------------------- media fitted for real
def media(check, m, out):
    W = out / "prep"

    def prep(platform, fmt, files, **post):
        return prepare(dict({"text": "Eid sale is live! #eid", "media": [m[f] for f in files]}, **post), {"platform": platform, "format": fmt}, W)

    r = prep("instagram", "reel", ["vertical.mp4"])
    check("prepare: a vertical H.264 video already fits Instagram Reels: used as it is", r["media"] == [m["vertical.mp4"]] and not r["problems"], r)
    r = prep("instagram", "reel", ["landscape.mp4"])
    v = MD.probe(r["media"][0])["video"] if r["media"] else {}
    check(
        "prepare: a landscape video becomes a 9:16 Reel (1080x1920), whole on a blurred fill",
        (v.get("w"), v.get("h")) == (1080, 1920) and any("9:16" in n for n in r["notes"]) and not r["problems"],
        (v, r["notes"], r["problems"]),
    )
    check("prepare: and its checks pass (codec, shape, length, size)", r["checks"] and all(c["ok"] for c in r["checks"]), r["checks"])
    r = prep("instagram", "reel", ["tiny.mp4"])
    check(
        "prepare: a 2-second clip is refused for Reels (3 s at least)",
        any("at least 3 s" in p for p in r["problems"]) and not r["media"],
        r["problems"],
    )
    r = prep("instagram", "reel", ["long.mp4"])
    check(
        "prepare: a 16-minute video is refused for Reels (15:00 at most), not cut silently", any("15:00" in p for p in r["problems"]), r["problems"]
    )
    r = prep("facebook", "reel", ["long.mp4"], trim=True)
    d = MD.probe(r["media"][0])["duration"] if r["media"] else 0
    check(
        "prepare: cut only when asked: a Facebook Reel made of the first 90 s",
        89.0 <= d <= 90.5 and any("first 90" in n for n in r["notes"]),
        (d, r["notes"]),
    )
    r = prep("x", "post", ["landscape.mp4"])
    v = MD.probe(r["media"][0])["video"] if r["media"] else {}
    check("prepare: X gets the video at 1280 on its long side", max(v.get("w", 0), v.get("h", 0)) == 1280, v)
    r = prep("instagram", "photo", ["panorama.jpg"])
    w, h = Image.open(r["media"][0]).size
    check(
        "prepare: a 3:1 panorama is cropped to Instagram's widest (1.91:1)",
        abs(w / h - 1.91) < 0.02 and any("cropped" in n for n in r["notes"]),
        (w, h),
    )
    r = prep("instagram", "photo", ["tall.jpg"], fill="fit")
    w, h = Image.open(r["media"][0]).size
    check(
        "prepare: 'don't crop' fits a tall photo whole into 4:5 on a blurred fill",
        abs(w / h - 0.8) < 0.01 and any("whole" in n for n in r["notes"]),
        (w, h),
    )
    r = prep("instagram", "photo", ["gps.jpg"])
    ex = Image.open(r["media"][0]).getexif()
    check("prepare: location and camera data are removed from pictures", 0x8825 not in ex and 0x0110 not in ex, dict(ex))
    r = prep("instagram", "photo", ["logo.png"])
    im = Image.open(r["media"][0])
    check(
        "prepare: a see-through PNG becomes a JPEG on white",
        im.format == "JPEG" and im.getpixel((5, 5)) == (255, 255, 255),
        (im.format, im.getpixel((5, 5))),
    )
    r = prep("instagram", "carousel", ["square.jpg", "wide.jpg", "vertical.mp4"])
    shapes = [Image.open(f).size if k == "image" else (MD.probe(f)["video"]["w"], MD.probe(f)["video"]["h"]) for f, k in zip(r["media"], r["kinds"])]
    check("prepare: a carousel's slides all made 4:5, the video too", len(shapes) == 3 and all(abs(a / b - 0.8) < 0.01 for a, b in shapes), shapes)
    r = prep("tiktok", "photo", ["square.jpg", "wide.jpg"])
    p = MD.probe(r["media"][0]) if r["media"] else {}
    check(
        "prepare: pictures for TikTok become a slideshow video (TikTok takes photos only from a web address)",
        r["kinds"] == ["video"] and (p.get("video") or {}).get("w") == 1080 and 5.5 <= p.get("duration", 0) <= 7,
        (r["kinds"], p.get("duration")),
    )
    r = prep("x", "post", ["square.jpg", "vertical.mp4"])
    check("prepare: X takes pictures or one video, not both", any("not both" in x for x in r["problems"]), r["problems"])
    r = prep("instagram", "photo", [])
    check("prepare: an Instagram post needs a picture", any("needs a picture" in x for x in r["problems"]), r["problems"])
    r = prepare({"text": "x" * 600, "media": []}, {"platform": "threads", "format": "text"}, W)
    check("prepare: 600 characters is too long for Threads (500)", any("500" in x for x in r["problems"]), r["problems"])
    r = prepare({"text": "Come in!", "media": [m["vertical.mp4"]]}, {"platform": "instagram", "format": "story"}, W)
    check("prepare: a story takes no words (said, not silently dropped)", r["text"] == "" and any("caption" in n for n in r["notes"]), r)


# ---------------------------------------------------------------- each platform against its fake
def _job(st, platform, fmt, prepared, post=None):
    p = st.add_post(dict({"text": prepared.get("text", ""), "status": "queued"}, **(post or {})))
    return st.add_job({"post_id": p["id"], "platform": platform, "format": fmt, "prepared": prepared, "status": "ready"}), p


def youtube(check, m, out, st):
    f = YouTubeFake(drop_on_chunk=2)
    yt = YT.YouTube(creds={"access_token": "ya29.TEST"}, transport=f.transport(), store=st, pause=lambda s: None)
    check("youtube: who is connected (the channel)", yt.whoami()["who"] == "Khan Electronics")
    prep = prepare(
        {"text": "Our Eid sale tour #eid #sale\nAll branches, all brands.", "media": [m["landscape.mp4"]], "title": "Eid sale tour"},
        {"platform": "youtube", "format": "video"},
        out / "prep",
    )
    job, post = _job(st, "youtube", "video", prep)
    RN.work(st, job, yt, None, budget=5)
    j = st.job(job["id"])
    check("youtube: a connection lost mid-upload is a retry, its place kept", j["status"] == "retry" and j["remote"].get("interrupted"), j["status"])
    RN.work(st, st.update_job(j["id"], next_try=None), yt, None, budget=5)
    j = st.job(job["id"])
    size = Path(prep["media"][0]).stat().st_size
    check(
        "youtube: it resumed from what YouTube confirmed and finished (every byte once)",
        bytes(f.received) == Path(prep["media"][0]).read_bytes() and len(f.received) == size,
        (len(f.received), size),
    )
    check(
        "youtube: title, description, tags and privacy sent; subscribers notified",
        f.meta["snippet"]["title"] == "Eid sale tour"
        and f.meta["status"]["privacyStatus"] == "public"
        and set(f.meta["snippet"]["tags"]) == {"eid", "sale"}
        and f.notify == "true",
        f.meta,
    )
    check("youtube: processing followed, then published with its link", j["status"] in ("published", "processing"), j["status"])
    if j["status"] == "processing":
        RN.work(st, st.update_job(j["id"], next_try=None), yt, None, budget=5)
        j = st.job(job["id"])
    check("youtube: published, link read back", j["status"] == "published" and j["remote"]["permalink"] == "https://youtu.be/VID1", j.get("remote"))
    check("youtube: the upload counted against today's allowance", yt.limits()["uploads_left"] == 99, yt.limits())
    check("youtube: numbers from the video's statistics", yt.metrics(j) == {"views": 1530, "likes": 88, "comments": 12})
    cs = yt.comments(j)
    r = yt.reply(j, cs[0]["id"], "Rs 00,000 at all branches")
    yt.hide(j, cs[0]["id"])
    check(
        "youtube: comments read, answered and held for review",
        cs[0]["author"] == "Ali" and r["verified"] and f.moderated[0]["moderationStatus"] == "heldForReview",
    )
    yt.delete(j)
    check("youtube: deleted", f.deleted == "VID1")
    # a video uploaded through an unaudited project comes back private: said plainly
    f2 = YouTubeFake(lock_private=True)
    yt2 = YT.YouTube(creds={"access_token": "ya29.TEST"}, transport=f2.transport(), store=st, pause=lambda s: None)
    job2, _ = _job(
        st, "youtube", "short", prepare({"text": "Short", "media": [m["vertical.mp4"]]}, {"platform": "youtube", "format": "short"}, out / "prep")
    )
    for _ in range(3):
        RN.work(st, st.update_job(job2["id"], next_try=None), yt2, None, budget=5)
    j2 = st.job(job2["id"])
    check(
        "youtube: an upload YouTube locked private (unaudited project) is reported, not passed off as public",
        j2["status"] == "published"
        and any("PRIVATE" in n for n in j2.get("notes") or [])
        and j2["remote"]["permalink"].startswith("https://www.youtube.com/shorts/"),
        j2.get("notes"),
    )
    # scheduled by YouTube itself
    f3 = YouTubeFake()
    yt3 = YT.YouTube(creds={"access_token": "ya29.TEST"}, transport=f3.transport(), store=st, pause=lambda s: None)
    when = iso(now() + dt.timedelta(days=2))
    p3 = st.add_post({"text": "Later", "when": when, "status": "queued"})
    job3 = st.add_job(
        {
            "post_id": p3["id"],
            "platform": "youtube",
            "format": "video",
            "native": True,
            "status": "ready",
            "prepared": prepare(
                {"text": "Later", "media": [m["vertical.mp4"]], "title": "Later"}, {"platform": "youtube", "format": "video"}, out / "prep"
            ),
        }
    )
    for _ in range(3):
        RN.work(st, st.update_job(job3["id"], next_try=None), yt3, None, budget=5)
    j3 = st.job(job3["id"])
    check(
        "youtube: a scheduled video is uploaded private with publishAt (YouTube publishes it)",
        j3["status"] == "scheduled"
        and f3.meta["status"]["privacyStatus"] == "private"
        and f3.meta["status"]["publishAt"].endswith("Z")
        and f3.notify == "false",
        (j3["status"], f3.meta["status"]),
    )
    # quota exceeded: waits until midnight Pacific
    from ai_pc.hub.http import HubError

    e = yt.classify(HubError("x", 403, {"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}}))
    check(
        "youtube: an exhausted allowance waits until it renews (midnight Pacific)",
        e.kind == "limit" and 60 <= e.retry_after <= 25 * 3600,
        e.retry_after,
    )
    day, off = YT.pacific_day(dt.datetime(2026, 7, 1, 6, 30, tzinfo=dt.UTC))
    day2, off2 = YT.pacific_day(dt.datetime(2026, 12, 1, 7, 30, tzinfo=dt.UTC))
    check("youtube: Pacific time with and without daylight saving", (day, off, day2, off2) == ("2026-06-30", -7, "2026-11-30", -8))


def tiktok(check, m, out, st):
    old = TT.PREF
    TT.PREF = 1024 * 1024  # small chunks, so a test file goes in several
    try:
        f = TikTokFake()
        tk = TT.TikTok(creds={"access_token": "act.TEST"}, transport=f.transport(), store=st, pause=lambda s: None)
        check("tiktok: who is connected", tk.whoami()["where"] == "TikTok @khan_pk")
        prep = prepare({"text": "Eid sale #eid", "media": [m["landscape.mp4"]]}, {"platform": "tiktok", "format": "video"}, out / "prep")
        job, post = _job(st, "tiktok", "video", prep)
        for _ in range(2):
            RN.work(st, st.update_job(job["id"], next_try=None), tk, None, budget=5)
        j = st.job(job["id"])
        data = Path(prep["media"][0]).read_bytes()
        check(
            "tiktok: sent as a draft to your TikTok inbox (the way TikTok allows personal tools)",
            f.inits[0][0] == "inbox" and j["status"] == "published" and j["remote"].get("draft") and "inbox" in " ".join(j.get("notes") or []),
            (f.inits[0][0], j["status"], j.get("notes")),
        )
        cs, n = TT.chunk_plan(len(data))
        check(
            "tiktok: uploaded in TikTok's chunks, in order, each range right, the remainder in the last, nothing missing",
            bytes(f.received) == data
            and n >= 2
            and len(f.puts) == n
            and f.puts[0][0] == 0
            and f.puts[-1][1] == len(data) - 1
            and all(p[1] - p[0] + 1 == cs for p in f.puts[:-1]),
            f.puts,
        )
        check("tiktok: no key sent to the upload address", not any(p[3] for p in f.puts))
        f2 = TikTokFake(public_account=True)
        tk2 = TT.TikTok(creds={"access_token": "act.TEST"}, transport=f2.transport(), store=st, pause=lambda s: None)
        job2, _ = _job(st, "tiktok", "video", prep, {"privacy": "private"})
        RN.work(st, job2, tk2, None, budget=5)
        j2 = st.job(job2["id"])
        check(
            "tiktok: posting privately while the account is public is explained (TikTok's rule for unaudited apps)",
            j2["status"] == "failed" and "account is private" in j2["error"],
            j2.get("error"),
        )
        check(
            "tiktok: the creator's settings are asked first; a private post asks for 'only me'",
            f2.inits[0][0] == "direct"
            and f2.inits[0][1]["post_info"]["privacy_level"] == "SELF_ONLY"
            and f2.inits[0][1]["post_info"]["brand_content_toggle"] is False,
        )
        w = tk.warnings({"text": "x"}, {})
        check("tiktok: the preview carries TikTok's required music-usage line", any("Music Usage Confirmation" in x for x in w), w)
        try:
            tk.delete(j)
            check("tiktok: deleting is refused with the reason (TikTok's API cannot)", False)
        except SocialError as e:
            check("tiktok: deleting is refused with the reason (TikTok's API cannot)", e.kind == "policy")
    finally:
        TT.PREF = old


def linkedin(check, m, out, st):
    f = LinkedInFake()
    li = LI.LinkedIn(creds={"access_token": "AQ.TEST"}, transport=f.transport(), store=st, pause=lambda s: None)
    check("linkedin: who is connected", li.whoami()["who"] == "Fareed Khan")
    prep = prepare(
        {"text": "New stock (55 inch TVs) #eid @everyone", "media": [m["square.jpg"], m["wide.jpg"]]},
        {"platform": "linkedin", "format": "carousel"},
        out / "prep",
    )
    job, post = _job(st, "linkedin", "carousel", prep)
    RN.work(st, job, li, None)
    j = st.job(job["id"])
    body = f.posts[0]
    check(
        "linkedin: two images uploaded and posted as one multi-image post on your profile",
        j["status"] == "published"
        and [i["id"] for i in body["content"]["multiImage"]["images"]] == ["urn:li:image:IMG1", "urn:li:image:IMG2"]
        and body["author"] == "urn:li:person:abc123",
    )
    check(
        "linkedin: the words escaped for LinkedIn, the hashtag kept",
        body["commentary"] == "New stock \\(55 inch TVs\\) #eid \\@everyone",
        body["commentary"],
    )
    check(
        "linkedin: the post's id from the x-restli-id header and its link",
        j["remote"]["post_urn"] == "urn:li:share:7001" and j["remote"]["permalink"] == "https://www.linkedin.com/feed/update/urn:li:share:7001/",
    )
    vp = prepare({"text": "Tour", "media": [m["vertical.mp4"]]}, {"platform": "linkedin", "format": "video"}, out / "prep")
    job2, _ = _job(st, "linkedin", "video", vp)
    RN.work(st, job2, li, None)
    check(
        "linkedin: a video in LinkedIn's parts (no key sent to its upload addresses), ETags kept in order, finalized, posted",
        st.job(job2["id"])["status"] == "published"
        and len(f.parts) == 2
        and not any(a for a, _ in f.parts)
        and f.finalized["uploadedPartIds"] == ["etag-1", "etag-2"]
        and f.posts[-1]["content"]["media"]["id"] == "urn:li:video:VID1",
    )
    li.delete(st.job(job["id"]))
    check("linkedin: deleted with Rest.li's DELETE method", f.deleted[0] == ("urn:li:share:7001", "DELETE"), f.deleted)
    # a post whose answer was lost is not sent again
    job3, _ = _job(st, "linkedin", "post", {"text": "Lost answer", "media": [], "kinds": []})
    st.checkpoint(job3["id"], posting=True)
    RN.work(st, st.job(job3["id"]), li, None)
    j3 = st.job(job3["id"])
    check(
        "linkedin: a post whose answer was lost is never resent blindly (you are asked to look)",
        j3["status"] == "failed" and "look at your profile" in j3["error"] and len(f.posts) == 2,
    )


def xcom(check, m, out, st):
    old_seg = XC.SEG
    XC.SEG = 1024 * 1024  # small segments, so the test video goes in several
    try:
        _xcom(check, m, out, st)
    finally:
        XC.SEG = old_seg


def _xcom(check, m, out, st):
    f = XFake()
    x = XC.X(creds={"access_token": "x.TEST"}, transport=f.transport(), store=st, pause=lambda s: None)
    check("x: who is connected", x.whoami()["where"] == "X @khan_pk")
    long = " ".join(f"Point {i}: our Eid prices beat every other shop in Lahore this week." for i in range(1, 9))
    prep = prepare({"text": long, "media": [m["vertical.mp4"]], "alt": ["A TV on a stand"]}, {"platform": "x", "format": "post"}, out / "prep")
    job, post = _job(st, "x", "post", prep, {"alt": ["A TV on a stand"]})
    for _ in range(2):
        RN.work(st, st.update_job(job["id"], next_try=None), x, None, budget=5)
    j = st.job(job["id"])
    n = len(prep["parts"])
    check(
        "x: a long post goes as a thread, each part a reply to the one before",
        j["status"] == "published" and len(f.tweets) == n >= 2 and f.tweets[1]["body"]["reply"]["in_reply_to_tweet_id"] == "T1",
        [t["body"].get("reply") for t in f.tweets],
    )
    segs = -(-Path(prep["media"][0]).stat().st_size // XC.SEG)
    check(
        "x: the video uploaded in segments, waited on, attached to the first post only",
        segs >= 2
        and f.appends == list(range(segs))
        and f.status_calls >= 2
        and f.tweets[0]["body"]["media"]["media_ids"] == ["MV1"]
        and "media" not in f.tweets[1]["body"],
        (f.appends, f.status_calls),
    )
    check("x: alt text set on the video", f.alt and f.alt[0]["metadata"]["alt_text"]["text"] == "A TV on a stand")
    check(
        "x: the cost shown before posting",
        "X charges $" in XC.X(creds={}).warnings({"text": "hi https://x.pk"}, {"prepared": {"text": "hi https://x.pk"}})[0]
        and XC.cost(["a", "b https://x.pk"]) == 0.215,
    )
    check(
        "x: numbers (views, likes, replies, reposts, saves)",
        x.metrics(j) == {"views": 2150, "likes": 40, "comments": 4, "shares": 7, "saves": 3, "clicks": 37},
    )
    cs = x.comments(j)
    check("x: replies to the post found", cs and cs[0]["author"] == "@sara")
    # the answer to a post is lost (X posted it): looked for, not posted again
    f2 = XFake(lose_first_answer=True)
    x2 = XC.X(creds={"access_token": "x.TEST"}, transport=f2.transport(), store=st, pause=lambda s: None)
    job2, _ = _job(st, "x", "post", {"text": "Shop open till 10 pm", "media": [], "kinds": []})
    RN.work(st, job2, x2, None)
    a = st.job(job2["id"])["status"]
    RN.work(st, st.update_job(job2["id"], next_try=None), x2, None)
    j2 = st.job(job2["id"])
    check(
        "x: a post whose answer was lost is found among your latest posts, NOT posted twice",
        a == "retry" and j2["status"] == "published" and len(f2.tweets) == 1 and j2["remote"]["ids"] == ["T1"],
        (a, j2["status"], len(f2.tweets)),
    )
    x.delete(j)
    check("x: a thread is deleted part by part, last first", f.deleted == [f"T{k}" for k in range(n, 0, -1)], f.deleted)


def meta(check, m, out, st):
    f = MetaFake()
    creds = {
        "page_id": "PAGE1",
        "page_token": "EAAPAGE",
        "user_token": "EAAUSER",
        "app_id": "APP1",
        "ig_id": "IG1",
        "ig_mode": "facebook",
        "live": True,
    }
    fb = ME.Facebook(creds=dict(creds), transport=f.transport(), store=st, pause=lambda s: None)
    ig = ME.Instagram(creds=dict(creds), transport=f.transport(), store=st, pause=lambda s: None)
    ig._host_factory = host_factory
    check("facebook: who is connected (the Page)", fb.whoami()["who"] == "Khan Electronics")
    check("instagram: who is connected", ig.whoami()["who"] == "@khan_pk")
    # Facebook: two photos in one post
    prep = prepare({"text": "New arrivals", "media": [m["square.jpg"], m["wide.jpg"]]}, {"platform": "facebook", "format": "carousel"}, out / "prep")
    job, post = _job(st, "facebook", "carousel", prep)
    RN.work(st, job, fb, None)
    j = st.job(job["id"])
    feed = [b for k, b in f.feed if k == "feed"][-1]
    check(
        "facebook: two photos uploaded unpublished, then one post with both attached",
        j["status"] == "published"
        and [p["published"] for p in f.photos[:2]] == ["false", "false"]
        and feed["attached_media"] == [{"media_fbid": "PH1"}, {"media_fbid": "PH2"}],
    )
    check("facebook: its link read back", j["remote"]["permalink"].startswith("https://www.facebook.com/khan/posts/"), j["remote"])
    # Facebook: a Reel through rupload, and a scheduled text post
    rp = prepare({"text": "Reel", "media": [m["vertical.mp4"]]}, {"platform": "facebook", "format": "reel"}, out / "prep")
    job2, _ = _job(st, "facebook", "reel", rp)
    for _ in range(3):
        RN.work(st, st.update_job(job2["id"], next_try=None), fb, None, budget=5)
    j2 = st.job(job2["id"])
    fin = [b for k, b in f.feed if k == "reel_finish"][-1]
    check(
        "facebook: a Reel started, uploaded to rupload (OAuth header, offset, size), finished as PUBLISHED, processing followed",
        j2["status"] == "published" and ("fb", Path(rp["media"][0]).stat().st_size) in f.rupload and fin["video_state"] == "PUBLISHED",
        (j2["status"], fin),
    )
    when = iso(now() + dt.timedelta(days=1))
    job3, p3 = _job(st, "facebook", "post", {"text": "Tomorrow's offer", "media": [], "kinds": []}, {"when": when})
    st.update_job(job3["id"], native=True)
    RN.work(st, st.job(job3["id"]), fb, None)
    sent = [b for k, b in f.feed if k == "feed"][-1]
    check(
        "facebook: a scheduled post is handed to Facebook (published=false + scheduled_publish_time)",
        st.job(job3["id"])["status"] == "scheduled"
        and sent["published"] == "false"
        and int(sent["scheduled_publish_time"]) == int(dt.datetime.fromisoformat(when).timestamp()),
    )
    check(
        "facebook: post numbers (reactions, comments, shares; 2026 view metrics)",
        fb.metrics(j) == {"likes": 210, "comments": 17, "shares": 9, "views": 4300, "reach": 3100},
        fb.metrics(j),
    )
    cs = fb.comments(j)
    check("facebook: comments read and answered", cs[0]["author"] == "Sana" and fb.reply(j, "FC1", "Thank you!")["verified"])
    fb.delete(j)
    check("facebook: deleted", any(d.startswith("PAGE1_") for d in f.deleted), f.deleted)
    # Instagram: a Reel uploaded from this PC (resumable), a photo through the temporary web address
    rp = prepare({"text": "Eid reel #eid", "media": [m["vertical.mp4"]]}, {"platform": "instagram", "format": "reel"}, out / "prep")
    job4, _ = _job(st, "instagram", "reel", rp)
    for _ in range(3):
        RN.work(st, st.update_job(job4["id"], next_try=None), ig, None, budget=5)
    j4 = st.job(job4["id"])
    c1 = f.ig_containers.get("IGC1") or {}
    check(
        "instagram: a Reel's container made for resumable upload, the bytes sent from this PC, waited on, published",
        j4["status"] == "published"
        and c1.get("upload_type") == "resumable"
        and c1.get("media_type") == "REELS"
        and ("ig", Path(rp["media"][0]).stat().st_size) in f.rupload
        and ("ig", "IGC1") in f.published,
        (j4["status"], c1),
    )
    check("instagram: its link read back", j4["remote"]["permalink"] == "https://www.instagram.com/reel/IGM1/")
    pp = prepare({"text": "New stock", "media": [m["gps.jpg"]]}, {"platform": "instagram", "format": "photo"}, out / "prep")
    job5, _ = _job(st, "instagram", "photo", pp, {"alt": ["A shop shelf"]})
    RN.work(st, job5, ig, None, budget=30)
    cid = [k for k, v in f.ig_containers.items() if v.get("image_url")][-1]
    check(
        "instagram: a picture lent a temporary web address: Instagram fetched exactly the prepared file",
        f.ig_fetched.get(cid) == Path(pp["media"][0]).read_bytes() and f.ig_containers[cid].get("alt_text") == "A shop shelf",
    )
    try:
        urllib.request.urlopen(f.ig_containers[cid]["image_url"], timeout=3)
        closed = False
    except Exception:  # noqa: BLE001
        closed = True
    check("instagram: the temporary address is closed afterwards", closed)
    check(
        "instagram: numbers from media insights (views, reach, likes, comments, shares, saves)",
        ig.metrics(j4) == {"views": 8200, "reach": 5100, "likes": 640, "comments": 41, "shares": 77, "saves": 120},
    )
    check("instagram: the 24-hour publishing limit read", ig.limits()["posts_left"] == 47)
    ic = ig.comments(j4)
    check("instagram: comments read and answered", ic[0]["author"] == "@bilal" and ig.reply(j4, "IC1", "Yes, all over Pakistan")["verified"])
    ig.delete(j4)
    check("instagram: deleted (Graph API, December 2025)", "IGM1" in f.deleted)
    # Threads: text, and an image through the temporary address
    th = TH.Threads(creds={"access_token": "THTOKEN"}, transport=f.transport(), store=st, pause=lambda s: None)
    th._host_factory = host_factory
    job6, _ = _job(
        st, "threads", "text", prepare({"text": "Open till 10 pm tonight", "media": []}, {"platform": "threads", "format": "text"}, out / "prep")
    )
    RN.work(st, job6, th, None)
    tp = prepare({"text": "New arrivals", "media": [m["square.jpg"]]}, {"platform": "threads", "format": "image"}, out / "prep")
    job7, _ = _job(st, "threads", "image", tp)
    RN.work(st, job7, th, None)
    check(
        "threads: a text post and a picture post published, links read back",
        st.job(job6["id"])["status"] == st.job(job7["id"])["status"] == "published"
        and f.th_containers["THC1"]["media_type"] == "TEXT"
        and f.th_fetched.get("THC2") == Path(tp["media"][0]).read_bytes(),
    )


def auth(check, out):
    from ai_pc.core import vault as V

    old = (V.FILE, dict(AU.PROVIDERS["tiktok"]), dict(AU.PROVIDERS["youtube"]))
    V.FILE = out / "vault_test.bin"
    V.FILE.unlink(missing_ok=True)
    AU.PROVIDERS["tiktok"]["port"] = 0
    seen = {}

    def browser(url):
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        seen["q"] = q
        back = q["redirect_uri"] + ("&" if "?" in q["redirect_uri"] else "?") + urllib.parse.urlencode({"code": "C%2F1", "state": q["state"]})
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=10).read(), daemon=True).start()

    from ai_pc.hub.http import FakeTransport

    def token(req):
        seen["form"] = dict(urllib.parse.parse_qsl(req["body"].decode()))
        return 200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 86400, "refresh_expires_in": 31536000, "open_id": "O1"}

    fake = FakeTransport({("POST", "oauth"): token, ("POST", "v2/oauth/token"): token})
    try:
        AU.signin("tiktok", {"client_key": "CK", "client_secret": "CS"}, open_url=browser, show=lambda s: None, timeout=20, transport=fake)
        q, form = seen["q"], seen["form"]
        check(
            "sign-in: TikTok's challenge is the HEX SHA-256 of the verifier, its client is a client_key, scopes comma-separated",
            q["code_challenge"] == hashlib.sha256(form["code_verifier"].encode()).hexdigest()
            and q["client_key"] == "CK"
            and "," in q["scope"]
            and q["redirect_uri"].endswith("/callback/"),
        )
        check(
            "sign-in: TikTok's code is URL-decoded before the exchange; the tokens kept",
            form["code"] == "C/1" and V.get("tiktok")["refresh_token"] == "RT",
        )
        AU.signin("youtube", {"client_id": "GID", "client_secret": "GS"}, open_url=browser, show=lambda s: None, timeout=20, transport=fake)
        q, form = seen["q"], seen["form"]
        s256 = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        check(
            "sign-in: Google's challenge is base64url SHA-256, offline access asked, YouTube scopes",
            q["code_challenge"] == s256 and q["access_type"] == "offline" and "youtube.force-ssl" in q["scope"],
        )
        # Threads: a long-lived token renewed a week before it runs out (and only after a day)
        calls = []
        fk = FakeTransport(
            {("GET", "refresh_access_token"): lambda req: calls.append(req["url"]) or (200, {"access_token": "TH2", "expires_in": 5184000})}
        )
        th = TH.Threads(creds={"access_token": "TH1", "expires_at": time.time() + 3 * 86400, "issued_at": time.time() - 2 * 86400}, transport=fk)
        tok = AU.fresh_token(th)
        check(
            "sign-in: Threads' token renewed a week early (th_refresh_token), the new one kept",
            tok == "TH2" and "th_refresh_token" in calls[0] and V.get("threads")["access_token"] == "TH2",
        )
        fresh = TH.Threads(creds={"access_token": "TH1", "expires_at": time.time() + 3 * 86400, "issued_at": time.time() - 3600}, transport=fk)
        check("sign-in: a token less than a day old is not renewed yet (Meta's rule)", AU.fresh_token(fresh) == "TH1" and len(calls) == 1)
        li = LI.LinkedIn(creds={"access_token": "OLD", "expires_at": time.time() - 10})
        try:
            AU.fresh_token(li)
            check("sign-in: LinkedIn has no renewal: an expired sign-in asks you to connect again", False)
        except SocialError as e:
            check("sign-in: LinkedIn has no renewal: an expired sign-in asks you to connect again", e.kind == "auth" and "connect linkedin" in str(e))
        # Meta: the pasted token made long-lived, the Page's own token taken
        mf = FakeTransport(
            {
                ("GET", "oauth/access_token"): (200, {"access_token": "EAALONG", "expires_in": 5183944}),
                ("GET", "me/accounts"): (
                    200,
                    {
                        "data": [
                            {
                                "id": "PAGE1",
                                "name": "Khan Electronics",
                                "access_token": "EAAPAGE",
                                "instagram_business_account": {"id": "IG1", "username": "khan_pk"},
                            }
                        ]
                    },
                ),
            }
        )
        who = AU.meta_connect({"app_id": "APP1", "app_secret": "SEC", "user_token": "EAASHORT"}, transport=mf)
        v = V.get("meta")
        check(
            "sign-in: Meta's token made long-lived (fb_exchange_token); the Page token and Instagram id kept",
            v["user_token"] == "EAALONG" and v["page_token"] == "EAAPAGE" and v["ig_id"] == "IG1" and "Instagram @khan_pk" in who["where"],
        )
        check("sign-in: the person is told to switch the Meta app to Live", any("Live" in w for w in who["warnings"]))
    finally:
        V.FILE.unlink(missing_ok=True)
        V.FILE = old[0]
        AU.PROVIDERS["tiktok"], AU.PROVIDERS["youtube"] = old[1], old[2]


def tunnel(check, out):
    from ai_pc.social import tunnel_setup as TS

    good = b"MZ fake cloudflared"
    sha = hashlib.sha256(good).hexdigest()
    rel = {
        "tag_name": "2026.9.1",
        "body": f"SHA256 Checksums:\n```\ncloudflared-windows-amd64.exe: {sha}\n```",
        "assets": [
            {"name": "cloudflared-windows-amd64.exe", "size": len(good), "browser_download_url": "https://github.com/x/cloudflared-windows-amd64.exe"}
        ],
    }

    def fetch(payload):
        return lambda url: json.dumps(rel).encode() if "api.github.com" in url else payload

    dest = out / "tools" / "cloudflared.exe"
    r = TS.install(fetch(good), lambda p: ("Valid", "CN=Cloudflare, Inc."), dest, say=lambda s: None)
    check(
        "tunnel setup: installed only when its SHA-256 matches Cloudflare's published one and its signature is Cloudflare's",
        dest.exists() and r["sha256"] == sha and (dest.parent / "SOURCE.txt").exists(),
    )
    dest.unlink()
    for name, payload, sig in (
        ("a changed file", b"MZ tampered", ("Valid", "CN=Cloudflare, Inc.")),
        ("a bad signature", good, ("HashMismatch", "")),
        ("someone else's signature", good, ("Valid", "CN=Someone Else")),
    ):
        try:
            TS.install(fetch(payload), lambda p, s=sig: s, dest, say=lambda s: None)
            check(f"tunnel setup: {name} is refused and not kept", False)
        except RuntimeError:
            check(f"tunnel setup: {name} is refused and not kept", not dest.exists() and not dest.with_suffix(".download").exists())


def chat(check, m, out):
    from ai_pc.social.socialchat import SocialChat

    f = MetaFake()
    yf = YouTubeFake()
    creds = {
        "page_id": "PAGE1",
        "page_token": "EAAPAGE",
        "user_token": "EAAUSER",
        "app_id": "APP1",
        "ig_id": "IG1",
        "ig_mode": "facebook",
        "live": True,
    }
    st = Store(out / "chat.db")
    ig = ME.Instagram(creds=dict(creds), transport=f.transport(), store=st, pause=lambda s: None)
    ig._host_factory = host_factory
    plats = {
        "facebook": ME.Facebook(creds=dict(creds), transport=f.transport(), store=st, pause=lambda s: None),
        "instagram": ig,
        "youtube": YT.YouTube(creds={"access_token": "ya29.TEST"}, transport=yf.transport(), store=st, pause=lambda s: None),
    }
    sc = SocialChat.start(chats_dir=out / "chats", platforms=plats, store=st, files=[m["vertical.mp4"], m["square.jpg"]], budget=20)
    r = sc.say("post vertical.mp4 to instagram and youtube saying 'Eid sale is live! #eid'")
    check(
        "chat: each platform's version shown first (an Instagram reel, a YouTube Short), nothing posted yet",
        "Instagram reel" in r and "YouTube Short" in r and r.startswith("Ready to post") and not f.published,
        r,
    )
    check("chat: the YouTube privacy lock warned about up front", "audit" in r, r)
    r = sc.say("yes")
    check(
        "chat: after 'yes' both are published, with their links",
        "Instagram reel: published (checked) https://www.instagram.com/reel/IGM1/" in r and "YouTube Short: published" in r,
        r,
    )
    r = sc.say("post vertical.mp4 to tiktok")
    check("chat: a platform that is not connected is said so", "TikTok is not connected" in r, r)
    r = sc.say("post square.jpg to facebook tomorrow at 7 pm saying 'Tomorrow only: 20% off'")
    check("chat: a scheduled Facebook post says Facebook publishes it, the PC may be off", "the platform publishes it, this PC may be off" in r, r)
    r = sc.say("yes")
    check("chat: then it is scheduled on Facebook", "scheduled on Facebook for" in r, r)
    r = sc.say("what's scheduled?")
    check("chat: the queue lists it", "Tomorrow only" in r and "Facebook (scheduled)" in r, r)
    r = sc.say("how did my posts do this week?")
    check("chat: results gathered from the platforms", "views" in r and "8200 views" in r, r)
    r = sc.say("any new comments?")
    check("chat: new comments listed, numbered", "1. " in r and ("bilal" in r or "Ali" in r), r)
    r = sc.say("reply to 1: thank you!")
    check("chat: a reply is shown first (everyone can see it)", r.startswith("Ready to reply"), r)
    r = sc.say("yes")
    check("chat: then sent and checked", r.startswith("Replied on") and "checked" in r, r)
    st.close()


PHRASES = [
    (
        "post eid.mp4 to instagram and tiktok saying 'Eid sale is live!'",
        lambda o: (
            o[0]["op"] == "compose"
            and o[0]["platforms"] == ["instagram", "tiktok"]
            and o[0]["text"] == "Eid sale is live!"
            and o[0]["media"] == ["eid.mp4"]
        ),
    ),
    ("put eid.mp4 on insta as a story", lambda o: o[0]["formats"] == {"instagram": "story"}),
    (
        "upload eid.mp4 to youtube shorts titled 'Eid Sale 2026'",
        lambda o: o[0]["formats"] == {"youtube": "short"} and o[0]["title"] == "Eid Sale 2026",
    ),
    (
        "post poster.jpg everywhere tomorrow at 7 pm",
        lambda o: set(o[0]["platforms"]) == {"facebook", "instagram"} and o[0]["when"]["time"] == "19:00:00",
    ),
    ("share poster.jpg on linkedin, don't crop it", lambda o: o[0]["fill"] == "fit"),
    ("post long.mp4 to facebook reels and cut it to fit", lambda o: o[0]["trim"] is True and o[0]["formats"] == {"facebook": "reel"}),
    ("tweet 'Open till 10 pm'", lambda o: o[0]["platforms"] == ["x"] and o[0]["text"] == "Open till 10 pm"),
    ("post eid.mp4 to tiktok as private", lambda o: o[0]["privacy"] == "private"),
    ("what's scheduled?", lambda o: o[0]["op"] == "queue"),
    ("cancel the tiktok one", lambda o: o[0] == {"op": "cancel", "platforms": ["tiktok"], "which": "last"}),
    ("delete that post from facebook", lambda o: o[0] == {"op": "delete", "platforms": ["facebook"], "which": "last"}),
    ("how did my posts do this week?", lambda o: o[0]["op"] == "results" and o[0]["days"] == 7),
    ("make a report of last month's results in excel", lambda o: o[0]["op"] == "results" and o[0]["days"] == 30 and o[0]["report"]),
    ("any new comments?", lambda o: o[0]["op"] == "comments"),
    ("reply to the first one saying thanks a lot", lambda o: o[0] == {"op": "reply", "to": "1", "text": "thanks a lot"}),
    ("answer the last comment with: we are open till 10", lambda o: o[0] == {"op": "reply", "to": "last", "text": "we are open till 10"}),
    ("hide 3", lambda o: o[0] == {"op": "hide", "to": "3"}),
    ("when should I post?", lambda o: o[0]["op"] == "best_time"),
    ("turn on automatic posting", lambda o: o[0] == {"op": "auto", "on": True}),
    ("what's connected?", lambda o: o[0] == {"op": "connected"}),
]


def phrases(check):
    import datetime as _dt

    from ai_pc.social.socialparse import parse

    ctx = {"connected": ["facebook", "instagram"], "files": {}, "now": _dt.datetime(2026, 10, 4, 12, 0)}
    bad = []
    for text, ok in PHRASES:
        o = parse(text, ctx)["ops"]
        try:
            good = bool(o) and ok(o)
        except Exception:  # noqa: BLE001
            good = False
        if not good:
            bad.append((text, o))
    check(f"rules: {len(PHRASES) - len(bad)}/{len(PHRASES)} everyday phrasings read without the model", not bad, bad)


def run_all(check, m, out):
    phrases(check)
    st = Store(out / "platforms.db")
    media(check, m, out)
    youtube(check, m, out, st)
    tiktok(check, m, out, st)
    linkedin(check, m, out, st)
    xcom(check, m, out, st)
    meta(check, m, out, st)
    auth(check, out)
    tunnel(check, out)
    chat(check, m, out)
    st.close()
