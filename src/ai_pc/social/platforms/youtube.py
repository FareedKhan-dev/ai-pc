"""YouTube through the YouTube Data API v3 (OAuth for desktop apps): videos and Shorts uploaded with the resumable
protocol (8 MiB chunks, a multiple of 256 KiB; every confirmed byte saved, so a lost connection resumes where it stopped;
an expired session starts again), scheduled by YouTube itself (publishAt), thumbnails and captions added, processing
followed to the end, then read back. Comments read, answered and held for review; numbers from the video's statistics.

2026 rules this follows: uploads have their own allowance of 100 a day; everything else shares 10,000 units a day
(videos.update / delete / thumbnails / comments.insert 50 each, captions 400, lists 1), reset at midnight Pacific time.
Videos uploaded through an unaudited Google project are kept PRIVATE by YouTube: when a public or scheduled video comes
back private, that lock is reported plainly (YouTube gives no flag for it). Vertical or square videos up to 3 minutes
become Shorts by themselves.
"""

import datetime as dt
import json
import uuid
from pathlib import Path

from ai_pc.social.base import Platform, SocialError

API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
CHUNK = 32 * 256 * 1024  # 8 MiB
COST = {
    "videos.list": 1,
    "commentThreads.list": 1,
    "channels.list": 1,
    "videos.update": 50,
    "videos.delete": 50,
    "thumbnails.set": 50,
    "comments.insert": 50,
    "comments.setModerationStatus": 50,
    "captions.insert": 400,
}


def pacific_day(now=None):
    """The quota day: YouTube resets at midnight Pacific time (DST from the 2nd Sunday of March to the 1st Sunday of November)."""
    u = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    y = u.year
    mar = dt.datetime(y, 3, 8, 10, tzinfo=dt.UTC)  # 2 am PST = 10:00 UTC, on the 2nd Sunday
    mar += dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.datetime(y, 11, 1, 9, tzinfo=dt.UTC)  # 2 am PDT = 09:00 UTC, on the 1st Sunday
    nov += dt.timedelta(days=(6 - nov.weekday()) % 7)
    off = -7 if mar <= u < nov else -8
    return (u + dt.timedelta(hours=off)).date().isoformat(), off


def seconds_to_reset(now=None):
    u = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    day, off = pacific_day(u)
    midnight = dt.datetime.fromisoformat(day) + dt.timedelta(days=1) - dt.timedelta(hours=off)
    return max(60, int((midnight.replace(tzinfo=dt.UTC) - u).total_seconds()))


class YouTube(Platform):
    name, label = "youtube", "YouTube"
    formats = ("video", "short")
    native_schedule = True

    def token(self):
        self.need("access_token")
        from ai_pc.social import auth

        return auth.fresh_token(self) if not self.transport else self.creds["access_token"]

    def yapi(self, base=API, timeout=60):
        return self.api(base, {"Authorization": f"Bearer {self.token()}"}, timeout)

    def _use(self, what, n=1):
        if self.store is not None:
            day = pacific_day()[0]
            self.store.add_usage("youtube:uploads" if what == "videos.insert" else "youtube:units", COST.get(what, 1) * n, day)

    def classify(self, e):
        body = e.body if isinstance(getattr(e, "body", None), dict) else {}
        errs = (body.get("error") or {}).get("errors") or [{}]
        reason = errs[0].get("reason") if errs else None
        if reason == "quotaExceeded":
            return SocialError(
                "limit", "YouTube: today's API allowance is used up (it renews at midnight Pacific time)", retry_after=seconds_to_reset()
            )
        if reason == "uploadLimitExceeded":
            return SocialError("limit", "YouTube: this channel's daily upload limit is reached", retry_after=seconds_to_reset())
        if reason == "youtubeSignupRequired":
            return SocialError("policy", "YouTube: this Google account has no channel yet (create one at youtube.com)")
        if reason == "insufficientPermissions":
            return SocialError("auth", "YouTube: the sign-in lacks a permission; connect again and allow everything asked")
        if reason == "forbidden" and e.status == 403:
            return SocialError("policy", f"YouTube: not allowed ({(body.get('error') or {}).get('message', '')})")
        if reason and reason.startswith("invalid"):
            return SocialError("invalid", f"YouTube: {reason}: {(body.get('error') or {}).get('message', '')}")
        return super().classify(e)

    # ---------------------------------------------------------------- who
    def whoami(self):
        js = self.call(self.yapi().get, "channels", params={"part": "snippet,statistics", "mine": "true"})
        self._use("channels.list")
        items = js.get("items") or []
        if not items:
            raise SocialError("policy", "YouTube: this Google account has no channel yet")
        ch = items[0]
        subs = (ch.get("statistics") or {}).get("subscriberCount")
        return {"who": ch["snippet"]["title"], "where": "YouTube" + (f", {subs} subscribers" if subs else ""), "id": ch["id"]}

    def warnings(self, post, target):
        w = []
        if (post.get("privacy") or "public") != "private" and not self.creds.get("audited"):
            w.append("YouTube keeps uploads from an unaudited Google project private; if it comes back private, the project needs YouTube's audit")
        return w

    def limits(self):
        if self.store is None:
            return {}
        day = pacific_day()[0]
        up, units = self.store.usage("youtube:uploads", day), self.store.usage("youtube:units", day)
        return {"uploads_left": 100 - up, "units_left": 10000 - units, "words": f"{100 - up} uploads and {10000 - units} units left today"}

    # ---------------------------------------------------------------- publishing
    def _resource(self, post, prepared, fmt):
        priv = post.get("privacy") or "public"
        status = {
            "privacyStatus": priv,
            "selfDeclaredMadeForKids": bool(post.get("kids")),
            "containsSyntheticMedia": bool(post.get("ai")),
            "embeddable": True,
        }
        if post.get("when"):
            t = dt.datetime.fromisoformat(post["when"]).astimezone(dt.UTC)
            status.update(privacyStatus="private", publishAt=t.strftime("%Y-%m-%dT%H:%M:%SZ"))
        tags = [t for t in (prepared.get("tags") or [])][:30]
        return {
            "snippet": {
                "title": prepared.get("title") or "Video",
                "description": prepared.get("text") or "",
                "tags": tags,
                "categoryId": str(post.get("category") or 22),
            },
            "status": status,
        }

    def publish(self, job, post, prepared, budget=120):
        import time

        r = job.get("remote") or {}
        media = prepared.get("media") or []
        if not media:
            raise SocialError("invalid", "YouTube needs a video")
        path = Path(media[0])
        total = path.stat().st_size
        if not r.get("video_id"):
            if not r.get("session"):
                res = self._resource(post, prepared, job.get("format"))
                body = json.dumps(res).encode("utf-8")
                st, h, content = self.yapi(UPLOAD).request(
                    "POST",
                    "videos",
                    params={"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "true" if not post.get("when") else "false"},
                    data=body,
                    raw=True,
                    headers={
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Length": str(total),
                        "X-Upload-Content-Type": "video/mp4",
                    },
                )
                if st >= 400:
                    raise self._raw_error(st, content)
                loc = (h or {}).get("Location") or (h or {}).get("location")
                if not loc:
                    raise SocialError("retry", "YouTube did not open an upload session")
                self._use("videos.insert")
                self.checkpoint(
                    job,
                    session=loc,
                    sent=0,
                    requested=res["status"].get("publishAt") and "scheduled" or res["status"]["privacyStatus"],
                    publish_at=res["status"].get("publishAt"),
                )
                r = job["remote"]
            up = self.api(UPLOAD, {"Authorization": f"Bearer {self.token()}"}, 300)
            sent = r.get("sent", 0)
            if r.get("interrupted"):  # ask YouTube how much it really has
                sent = self._offset(up, r["session"], total)
                self.checkpoint(job, sent=sent, interrupted=False)
            with path.open("rb") as f:
                while sent < total:
                    f.seek(sent)
                    data = f.read(CHUNK)
                    last = sent + len(data) - 1
                    try:
                        st, h, content = up.request(
                            "PUT",
                            r["session"],
                            data=data,
                            raw=True,
                            retries=0,
                            headers={"Content-Type": "video/mp4", "Content-Range": f"bytes {sent}-{last}/{total}"},
                        )
                    except Exception as e:  # noqa: BLE001  (a dropped connection: resume from what YouTube confirms)
                        self.checkpoint(job, interrupted=True)
                        raise SocialError("retry", f"YouTube upload interrupted at {sent // 1048576} MB ({type(e).__name__}); it resumes") from e
                    if st == 308:
                        rng = (h or {}).get("Range") or (h or {}).get("range")
                        sent = int(rng.split("-")[1]) + 1 if rng else 0
                        self.checkpoint(job, sent=sent)
                        continue
                    if st in (200, 201):
                        vid = json.loads(content.decode("utf-8"))["id"]
                        self.checkpoint(job, video_id=vid, sent=total, session=None)
                        r = job["remote"]
                        break
                    if st == 404:
                        self.checkpoint(job, session=None, sent=0)
                        raise SocialError("retry", "YouTube's upload session expired; starting the upload again")
                    if st >= 500 or st == 429:
                        self.checkpoint(job, interrupted=True)
                        raise SocialError("retry", f"YouTube answered {st} during the upload; it resumes")
                    raise self._raw_error(st, content)
            self._extras(job, post, prepared)
        # processing, then the result read back
        t0 = time.time()
        while True:
            v = self._video(r["video_id"], "status,processingDetails")
            s = v.get("status") or {}
            up_st = s.get("uploadStatus")
            if up_st in ("failed", "rejected", "deleted"):
                why = s.get("failureReason") or s.get("rejectionReason") or up_st
                raise SocialError("invalid", f"YouTube {up_st} the video ({why})")
            if up_st == "processed":
                break
            if time.time() - t0 > min(budget, 90):
                return {"status": "processing", "wait": 30, "detail": (v.get("processingDetails") or {}).get("processingStatus") or up_st}
            self.pause(10)
        vid = r["video_id"]
        link = f"https://www.youtube.com/shorts/{vid}" if job.get("format") == "short" else f"https://youtu.be/{vid}"
        wanted = r.get("requested")
        notes = []
        if wanted in ("public", "unlisted", "scheduled") and s.get("privacyStatus") == "private" and not s.get("publishAt"):
            notes.append(
                "YouTube kept it PRIVATE: uploads from an unaudited Google project are locked private until the project passes YouTube's "
                "API audit (https://support.google.com/youtube/contact/yt_api_form)"
            )
        if s.get("publishAt") and not notes:
            return {"status": "scheduled", "id": vid, "publish_at": r.get("publish_at"), "permalink": link}
        return {"status": "published", "id": vid, "permalink": link, "verified": True, "notes": notes + (r.get("extras_notes") or [])}

    def _offset(self, up, session, total):
        st, h, _ = up.request("PUT", session, data=b"", raw=True, retries=1, headers={"Content-Range": f"bytes */{total}", "Content-Length": "0"})
        if st == 308:
            rng = (h or {}).get("Range") or (h or {}).get("range")
            return int(rng.split("-")[1]) + 1 if rng else 0
        if st in (200, 201):
            return total
        raise SocialError("retry", f"YouTube could not say how much was uploaded ({st})")

    def _raw_error(self, status, content):
        from ai_pc.hub.http import HubError

        try:
            body = json.loads(content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            body = {}
        return self.classify(HubError(f"youtube: {status}", status, body))

    def _video(self, vid, part):
        js = self.call(self.yapi().get, "videos", params={"part": part, "id": vid})
        self._use("videos.list")
        items = js.get("items") or []
        if not items:
            raise SocialError("invalid", "YouTube no longer has the video")
        return items[0]

    def _extras(self, job, post, prepared):
        """A custom thumbnail and captions, after the upload (each optional: a refusal is a note, not a failure)."""
        notes = []
        vid = job["remote"]["video_id"]
        if prepared.get("cover") and job.get("format") != "short":
            try:
                data = Path(prepared["cover"]).read_bytes()
                self.call(
                    self.yapi(UPLOAD).request, "POST", "thumbnails/set", params={"videoId": vid}, data=data, headers={"Content-Type": "image/jpeg"}
                )
                self._use("thumbnails.set")
            except SocialError as e:
                notes.append(
                    "the custom thumbnail was refused (YouTube needs the channel's phone verified)"
                    if "forbidden" in str(e).lower() or "not allowed" in str(e).lower()
                    else f"the thumbnail was not set ({e})"
                )
        if post.get("captions") and Path(post["captions"]).exists():
            try:
                b = uuid.uuid4().hex
                meta = json.dumps({"snippet": {"videoId": vid, "language": post.get("language") or "en", "name": "Captions", "isDraft": False}})
                body = (
                    (
                        f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n--{b}\r\nContent-Type: application/octet-stream\r\n\r\n"
                    ).encode()
                    + Path(post["captions"]).read_bytes()
                    + f"\r\n--{b}--".encode()
                )
                self.call(
                    self.yapi(UPLOAD).request,
                    "POST",
                    "captions",
                    params={"part": "snippet", "uploadType": "multipart"},
                    data=body,
                    headers={"Content-Type": f"multipart/related; boundary={b}"},
                )
                self._use("captions.insert")
            except SocialError as e:
                notes.append(f"the captions were not added ({e})")
        self.checkpoint(job, extras_notes=notes)

    def status(self, job):
        vid = (job.get("remote") or {}).get("video_id")
        v = self._video(vid, "status")
        s = v.get("status") or {}
        if s.get("privacyStatus") == "public":
            return {"status": "published", "permalink": (job.get("remote") or {}).get("permalink") or f"https://youtu.be/{vid}"}
        return {"status": "scheduled" if s.get("publishAt") else "private"}

    def delete(self, job):
        vid = (job.get("remote") or {}).get("video_id") or (job.get("remote") or {}).get("id")
        self.call(self.yapi().request, "DELETE", "videos", params={"id": vid})
        self._use("videos.delete")
        return {"deleted": vid}

    def metrics(self, job):
        vid = (job.get("remote") or {}).get("video_id") or (job.get("remote") or {}).get("id")
        st = self._video(vid, "statistics").get("statistics") or {}
        return {k: int(st[s]) for k, s in (("views", "viewCount"), ("likes", "likeCount"), ("comments", "commentCount")) if s in st}

    def comments(self, job, since=None):
        vid = (job.get("remote") or {}).get("video_id")
        js = self.call(self.yapi().get, "commentThreads", params={"part": "snippet", "videoId": vid, "maxResults": 50, "order": "time"})
        self._use("commentThreads.list")
        out = []
        for t in js.get("items") or []:
            c = t["snippet"]["topLevelComment"]
            sn = c["snippet"]
            out.append(
                {
                    "id": c["id"],
                    "author": sn.get("authorDisplayName"),
                    "text": sn.get("textOriginal") or sn.get("textDisplay"),
                    "created": sn.get("publishedAt"),
                }
            )
        return out

    def reply(self, job, comment_id, text):
        js = self.call(
            self.yapi().post, "comments", params={"part": "snippet"}, json={"snippet": {"parentId": comment_id, "textOriginal": text}}, retries=0
        )
        self._use("comments.insert")
        return {"id": js.get("id"), "verified": (js.get("snippet") or {}).get("textOriginal") == text}

    def hide(self, job, comment_id, hidden=True):
        self.call(
            self.yapi().request,
            "POST",
            "comments/setModerationStatus",
            params={"id": comment_id, "moderationStatus": "heldForReview" if hidden else "published"},
        )
        self._use("comments.setModerationStatus")
        return {"hidden": hidden}
