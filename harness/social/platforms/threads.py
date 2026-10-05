"""Threads through Meta's Threads API (graph.threads.net v1.0): text posts, a picture, a video, or a carousel of 2-20,
each made as a container, waited on, then published (the 250-posts-a-day limit asked first); pictures and videos given at
a temporary web address (Threads has no upload; see mediahost.py); permalink read back; replies read, answered and
hidden; post insights (views, likes, replies, reposts, quotes, shares); deleting. The long-lived token (60 days) is
renewed automatically before it runs out.
"""
import time

from ..base import Platform, SocialError
from .meta import _meta_error

API = "https://graph.threads.net/v1.0"


class Threads(Platform):
    name, label = "threads", "Threads"
    formats = ("text", "image", "video", "carousel")
    native_schedule = False

    def ready(self):
        return bool(self.creds.get("access_token"))

    def token(self):
        self.need("access_token")
        from .. import auth
        return auth.fresh_token(self) if not self.transport else self.creds["access_token"]

    def tapi(self, timeout=120):
        return self.api(API, {"Authorization": f"Bearer {self.token()}"}, timeout)

    def classify(self, e):
        return _meta_error(self, e)

    def uid(self):
        if not self.creds.get("user_id"):
            self.whoami()
        return self.creds["user_id"]

    def whoami(self):
        u = self.call(self.tapi().get, "me", params={"fields": "id,username,name"})
        self.creds["user_id"] = u.get("id")
        return {"who": "@" + (u.get("username") or "?"), "where": "Threads", "id": u.get("id")}

    def limits(self):
        js = self.call(self.tapi().get, f"{self.uid()}/threads_publishing_limit", params={"fields": "quota_usage,config"})
        d = (js.get("data") or [{}])[0]
        total = (d.get("config") or {}).get("quota_total") or 250
        left = total - (d.get("quota_usage") or 0)
        return {"posts_left": left, "words": f"{left} of {total} posts left in 24 hours"}

    def host(self):
        from ..mediahost import MediaHost
        return getattr(self, "_host_factory", lambda: MediaHost())()

    def _status(self, cid):
        js = self.call(self.tapi().get, cid, params={"fields": "status,error_message"})
        return js.get("status"), js.get("error_message")

    def _wait(self, ids, budget, t0):
        while True:
            st = {i: self._status(i) for i in ids}
            bad = [(i, s) for i, s in st.items() if s[0] in ("ERROR", "EXPIRED")]
            if bad:
                raise SocialError("invalid", f"Threads could not use the media ({bad[0][1][0]}: {bad[0][1][1] or 'no reason given'})")
            if all(s[0] in ("FINISHED", "PUBLISHED") for s in st.values()):
                return True
            if time.time() - t0 > min(budget, 300):
                return False
            self.pause(5)

    def publish(self, job, post, prepared, budget=120):
        t0 = time.time()
        r = job.get("remote") or {}
        if r.get("media_id"):
            return self._done(job)
        if self.limits().get("posts_left", 1) <= 0:
            raise SocialError("limit", "Threads: the 24-hour posting limit is reached", retry_after=3600)
        media, kinds = prepared.get("media") or [], prepared.get("kinds") or []
        text = prepared.get("text") or ""
        alts = post.get("alt") or []
        host = None
        try:
            if not r.get("container"):
                uid = self.uid()
                if not media:
                    cid = self.call(self.tapi().post, f"{uid}/threads", json={"media_type": "TEXT", "text": text})["id"]
                elif len(media) == 1:
                    host = self.host()
                    p = {"text": text}
                    if kinds[0] == "video":
                        p.update(media_type="VIDEO", video_url=host.open(media[0]))
                    else:
                        p.update(media_type="IMAGE", image_url=host.open(media[0]))
                        if alts and alts[0]:
                            p["alt_text"] = alts[0][:1000]
                    cid = self.call(self.tapi().post, f"{uid}/threads", json=p)["id"]
                else:
                    host = self.host()
                    kids = []
                    for i, (m, k) in enumerate(zip(media, kinds)):
                        p = {"is_carousel_item": "true"}
                        if k == "video":
                            p.update(media_type="VIDEO", video_url=host.open(m))
                        else:
                            p.update(media_type="IMAGE", image_url=host.open(m))
                            if i < len(alts) and alts[i]:
                                p["alt_text"] = alts[i][:1000]
                        kids.append(self.call(self.tapi().post, f"{uid}/threads", json=p)["id"])
                    if not self._wait(kids, budget, t0):
                        raise SocialError("retry", "Threads took too long to fetch the slides; trying again")
                    cid = self.call(self.tapi().post, f"{uid}/threads", json={"media_type": "CAROUSEL", "children": ",".join(kids), "text": text})["id"]
                self.checkpoint(job, container=cid)
                r = job["remote"]
            if not self._wait([r["container"]], budget, t0):
                return {"status": "processing", "wait": 30, "detail": "Threads is preparing the post"}
        finally:
            if host is not None:
                host.close()
        if r.get("publishing"):  # sent before, answer lost: is it on the profile already?
            js = self.call(self.tapi().get, f"{self.uid()}/threads", params={"fields": "id,text,timestamp", "limit": 5})
            hit = next((m["id"] for m in js.get("data") or [] if (m.get("text") or "").strip() == (prepared.get("text") or "").strip()), None)
            if hit:
                self.checkpoint(job, media_id=hit, publishing=False)
                return self._done(job)
        self.checkpoint(job, publishing=True)
        res = self.call(self.tapi().post, f"{self.uid()}/threads_publish", json={"creation_id": r["container"]}, retries=0)
        self.checkpoint(job, media_id=res["id"], publishing=False)
        return self._done(job)

    def _done(self, job):
        mid = job["remote"]["media_id"]
        got = self.call(self.tapi().get, mid, params={"fields": "permalink"})
        return {"status": "published", "id": mid, "permalink": got.get("permalink"), "verified": bool(got.get("permalink"))}

    def status(self, job):
        return {"status": "published"}

    def delete(self, job):
        res = self.call(self.tapi().request, "DELETE", job["remote"]["media_id"])
        if not res.get("success", True):
            raise SocialError("invalid", "Threads did not delete it")
        return {"deleted": job["remote"]["media_id"]}

    def metrics(self, job):
        js = self.call(self.tapi().get, f"{job['remote']['media_id']}/insights", params={"metric": "views,likes,replies,reposts,quotes,shares"})
        v = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in js.get("data") or []}
        return {"views": v.get("views"), "likes": v.get("likes"), "comments": v.get("replies"),
                "shares": (v.get("reposts") or 0) + (v.get("quotes") or 0) + (v.get("shares") or 0)}

    def comments(self, job, since=None):
        js = self.call(self.tapi().get, f"{job['remote']['media_id']}/replies", params={"fields": "id,text,username,timestamp"})
        return [{"id": c["id"], "author": "@" + (c.get("username") or "someone"), "text": c.get("text", ""), "created": c.get("timestamp")}
                for c in js.get("data") or []]

    def reply(self, job, comment_id, text):
        uid = self.uid()
        cid = self.call(self.tapi().post, f"{uid}/threads", json={"media_type": "TEXT", "text": text, "reply_to_id": comment_id})["id"]
        res = self.call(self.tapi().post, f"{uid}/threads_publish", json={"creation_id": cid}, retries=0)
        return {"id": res.get("id"), "verified": bool(res.get("id"))}

    def hide(self, job, comment_id, hidden=True):
        self.call(self.tapi().post, f"{comment_id}/manage_reply", json={"hide": "true" if hidden else "false"})
        return {"hidden": hidden}
