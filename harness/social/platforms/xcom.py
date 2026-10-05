"""X (Twitter) through API v2 with OAuth 2.0 PKCE (a Native App: no secret on this PC). Posts with up to 4 pictures or one
video; text too long for one post goes as a thread (each part a reply to the one before). Pictures: one-shot upload.
Videos and GIFs: chunked upload (initialize, append in 4 MB segments, finalize) and then waited on until X has processed
them. Alt text through the media metadata endpoint.

X is paid per use since February 2026 (no free tier): $0.015 a post, $0.20 when its text has a link, $0.005 a delete,
$0.001 per own-post read. The cost is shown before posting. X has no way to make a repeated post safe, so a post whose
answer was lost is looked for among your latest posts before anything is sent again.
"""
import re
from pathlib import Path

from ...hub.http import multipart
from ..base import Platform, SocialError

API = "https://api.x.com"
URL = re.compile(r"https?://\S+", re.I)
SEG = 4 * 1024 * 1024


def cost(parts):
    """What X charges for these posts (2026 pay-per-use prices)."""
    return round(sum(0.20 if URL.search(p) else 0.015 for p in parts), 3)


class X(Platform):
    name, label = "x", "X"
    formats = ("post",)
    native_schedule = False

    def token(self):
        self.need("access_token")
        from .. import auth
        return auth.fresh_token(self) if not self.transport else self.creds["access_token"]

    def xapi(self, timeout=60):
        return self.api(API, {"Authorization": f"Bearer {self.token()}"}, timeout)

    def classify(self, e):
        if e.status == 402:
            return SocialError("policy", "X: the account has no credit left for the API (add credit at console.x.com)")
        if e.status == 403:
            return SocialError("policy", f"X refused it ({e})")
        return super().classify(e)

    def whoami(self):
        u = (self.call(self.xapi().get, "2/users/me") or {}).get("data") or {}
        self.creds["user_id"], self.creds["username"] = u.get("id"), u.get("username")
        return {"who": u.get("name"), "where": f"X @{u.get('username')}", "id": u.get("id")}

    def warnings(self, post, target):
        parts = (target.get("prepared") or {}).get("parts") or [(target.get("prepared") or {}).get("text") or post.get("text") or ""]
        return [f"X charges ${cost(parts):.3f} for this ({len(parts)} post{'s' if len(parts) > 1 else ''}"
                + (", a link makes a post cost $0.20" if any(URL.search(p) for p in parts) else "") + ")"]

    # ---------------------------------------------------------------- media
    def _image(self, path):
        body, ctype = multipart({"media_category": "tweet_image"}, {"media": (Path(path).name, Path(path).read_bytes(), "image/jpeg")})
        js = self.call(self.xapi(300).request, "POST", "2/media/upload", data=body, headers={"Content-Type": ctype})
        return (js.get("data") or {}).get("id")

    def _video(self, path, job, budget):
        import time
        r = job.get("remote") or {}
        size = Path(path).stat().st_size
        if not r.get("media_id"):
            js = self.call(self.xapi().post, "2/media/upload/initialize",
                           json={"media_type": "video/mp4", "total_bytes": size, "media_category": "tweet_video"})
            self.checkpoint(job, media_id=(js.get("data") or {})["id"], segments=0)
            r = job["remote"]
        n = (size + SEG - 1) // SEG
        if r.get("segments", 0) < n:
            with Path(path).open("rb") as f:
                for i in range(r.get("segments", 0), n):
                    f.seek(i * SEG)
                    body, ctype = multipart({"segment_index": str(i)}, {"media": ("chunk", f.read(SEG), "application/octet-stream")})
                    self.call(self.xapi(300).request, "POST", f"2/media/upload/{r['media_id']}/append", data=body, headers={"Content-Type": ctype})
                    self.checkpoint(job, segments=i + 1)
        if not r.get("finalized"):
            js = self.call(self.xapi().post, f"2/media/upload/{r['media_id']}/finalize", json={})
            self.checkpoint(job, finalized=True, processing=(js.get("data") or {}).get("processing_info"))
        t0 = time.time()
        info = r.get("processing")
        while info and info.get("state") in ("pending", "in_progress"):
            if time.time() - t0 > min(budget, 90):
                return None
            self.pause(min(int(info.get("check_after_secs") or 2), 10))
            js = self.call(self.xapi().get, "2/media/upload", params={"command": "STATUS", "media_id": r["media_id"]})
            info = (js.get("data") or {}).get("processing_info")
            self.checkpoint(job, processing=info)
        if info and info.get("state") == "failed":
            self.checkpoint(job, media_id=None, segments=0, finalized=False, processing=None)
            raise SocialError("invalid", f"X could not process the video ({(info.get('error') or {}).get('message', 'unknown')})")
        return r["media_id"]

    # ---------------------------------------------------------------- publishing
    def _recent(self):
        if not self.creds.get("user_id"):
            self.whoami()
        js = self.call(self.xapi().get, f"2/users/{self.creds['user_id']}/tweets", params={"max_results": 5})
        return js.get("data") or []

    def publish(self, job, post, prepared, budget=120):
        r = job.get("remote") or {}
        media = prepared.get("media") or []
        kinds = prepared.get("kinds") or []
        mids = list(r.get("media_ids") or [])
        if media and not mids:
            if kinds[0] == "video":
                mid = self._video(media[0], job, budget)
                if mid is None:
                    return {"status": "processing", "wait": 15, "detail": "X is processing the video"}
                mids = [mid]
            else:
                for m in media[:4]:
                    mids.append(self._image(m))
            alts = post.get("alt") or []
            for i, mid in enumerate(mids):
                if i < len(alts) and alts[i]:
                    self.call(self.xapi().post, "2/media/metadata", json={"id": mid, "metadata": {"alt_text": {"text": alts[i][:1000]}}})
            self.checkpoint(job, media_ids=mids)
        parts = prepared.get("parts") or [prepared.get("text") or ""]
        ids = list(r.get("ids") or [])
        for i, text in enumerate(parts):
            if i < len(ids):
                continue
            if r.get("posting") == i:  # sent before but the answer was lost: is it already there?
                hit = next((t for t in self._recent() if t.get("text", "").strip() == text.strip()), None)
                if hit:
                    ids.append(hit["id"])
                    self.checkpoint(job, ids=ids, posting=None)
                    continue
            body = {"text": text}
            if i == 0 and mids:
                body["media"] = {"media_ids": mids}
            if i > 0:
                body["reply"] = {"in_reply_to_tweet_id": ids[-1]}
            self.checkpoint(job, posting=i)
            js = self.call(self.xapi().post, "2/tweets", json=body, retries=0)  # never resent blindly: a lost answer is looked for next time
            tid = (js.get("data") or {}).get("id")
            ids.append(tid)
            self.checkpoint(job, ids=ids, posting=None)
            r = job["remote"]
        user = self.creds.get("username") or "i"
        return {"status": "published", "id": ids[0], "permalink": f"https://x.com/{user}/status/{ids[0]}", "verified": bool(ids[0]),
                "notes": [f"a thread of {len(ids)}"] if len(ids) > 1 else []}

    def status(self, job):
        return {"status": "published"}

    def delete(self, job):
        ids = (job.get("remote") or {}).get("ids") or [(job.get("remote") or {}).get("id")]
        for tid in reversed(ids):
            js = self.call(self.xapi().request, "DELETE", f"2/tweets/{tid}")
            if not (js.get("data") or {}).get("deleted"):
                raise SocialError("invalid", f"X did not delete post {tid}")
        return {"deleted": ids}

    def metrics(self, job):
        tid = (job.get("remote") or {}).get("ids", [None])[0] or (job.get("remote") or {}).get("id")
        js = self.call(self.xapi().get, f"2/tweets/{tid}", params={"tweet.fields": "public_metrics,non_public_metrics,organic_metrics"})
        d = js.get("data") or {}
        pm, npm = d.get("public_metrics") or {}, d.get("non_public_metrics") or {}
        return {"views": npm.get("impression_count", pm.get("impression_count")), "likes": pm.get("like_count"), "comments": pm.get("reply_count"),
                "shares": (pm.get("retweet_count") or 0) + (pm.get("quote_count") or 0), "saves": pm.get("bookmark_count"),
                "clicks": npm.get("url_link_clicks")}

    def comments(self, job, since=None):
        tid = (job.get("remote") or {}).get("ids", [None])[0]
        js = self.call(self.xapi().get, "2/tweets/search/recent", params={"query": f"conversation_id:{tid}", "tweet.fields": "author_id,created_at",
                                                                          "expansions": "author_id", "user.fields": "username", "max_results": 25})
        users = {u["id"]: u.get("username") for u in (js.get("includes") or {}).get("users") or []}
        mine = set((job.get("remote") or {}).get("ids") or [])
        return [{"id": t["id"], "author": "@" + (users.get(t.get("author_id")) or "someone"), "text": t.get("text", ""), "created": t.get("created_at")}
                for t in js.get("data") or [] if t["id"] not in mine]

    def reply(self, job, comment_id, text):
        js = self.call(self.xapi().post, "2/tweets", json={"text": text, "reply": {"in_reply_to_tweet_id": comment_id}}, retries=0)
        d = js.get("data") or {}
        return {"id": d.get("id"), "verified": d.get("text", "").strip() == text.strip() or bool(d.get("id"))}
