"""Facebook Pages and Instagram through Meta's Graph API (v26.0), with one Meta app ('Manage everything on your Page' and
'Manage messaging & content on Instagram' with Facebook login) and a Page token that does not expire.

Facebook Page: text and link posts; one or several photos (uploaded from this PC; several are attached to one post);
videos through Meta's resumable upload (an upload session, the bytes, then the video published with its handle); Reels
and Stories (start, upload to rupload.facebook.com, finish); scheduling by Facebook itself (10 minutes to 30 days
ahead); permalinks read back; comments read, answered and hidden; post numbers (views, reach, reactions, comments,
shares; the 2025-26 metric names).

Instagram (professional account linked to the Page): containers made, waited on until FINISHED, then published (the
API's 50-posts-a-day limit asked first); Reels, Stories and carousel videos uploaded from this PC by resumable upload;
pictures given to Instagram at a temporary web address (Instagram takes pictures only from a URL: see mediahost.py);
permalink read back; delete (API since December 2025), comments, replies, hiding, media insights.
"""
import datetime as dt
import json
import time
from pathlib import Path

from ai_pc.hub.http import HubError, multipart
from ai_pc.social.base import Platform, SocialError

GRAPH = "https://graph.facebook.com/v26.0"
RUPLOAD_FB = "https://rupload.facebook.com/video-upload/v26.0"
RUPLOAD_IG = "https://rupload.facebook.com/ig-api-upload/v26.0"


def _meta_error(plat, e):
    err = (e.body or {}).get("error") if isinstance(getattr(e, "body", None), dict) else None
    if not isinstance(err, dict):  # not Meta's shape (a proxy page, an empty body): its words kept as the message
        err = {"message": str(err or e)}
    code, sub, msg = err.get("code"), err.get("error_subcode"), err.get("error_user_msg") or err.get("message") or str(e)
    if code == 190:
        return SocialError("auth", f"{plat.label}: the Meta sign-in has expired or was withdrawn (code 190/{sub}); run 'ai-pc social connect {plat.name}'")
    if code in (4, 17, 32, 613, 80001, 80002):
        return SocialError("limit", f"{plat.label}: Meta's rate limit for now ({msg})", retry_after=900)
    if code == 368:
        return SocialError("policy", f"{plat.label}: Meta has temporarily blocked this action ({msg})")
    if code == 506:
        return SocialError("invalid", f"{plat.label}: Meta refused it as a duplicate of a recent post")
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299):
        return SocialError("policy", f"{plat.label}: the app lacks a permission ({msg})")
    if sub in (2207042,):
        return SocialError("limit", "Instagram: the 24-hour publishing limit is reached", retry_after=3600)
    if sub in (2207052, 2207003):
        return SocialError("retry", "Instagram could not fetch the picture from its temporary address; trying again")
    if e.status and e.status >= 500 or err.get("is_transient"):
        return SocialError("retry", f"{plat.label}: Meta had a problem ({msg})")
    if e.status is None:
        return SocialError("retry", f"{plat.label}: no connection")
    return SocialError("invalid", f"{plat.label}: {msg}")


def _unix(iso):
    return int(dt.datetime.fromisoformat(iso).timestamp())


class _Meta(Platform):
    vault_key = "meta"

    def gapi(self, token, base=GRAPH, timeout=120):
        return self.api(base, {"Authorization": f"Bearer {token}"}, timeout)

    def classify(self, e):
        return _meta_error(self, e)

    def _wait_video(self, token, vid, budget, t0):
        """A Facebook video's processing, followed until ready (or the time budget runs out)."""
        while True:
            st = self.call(self.gapi(token).get, vid, params={"fields": "status"}).get("status") or {}
            vs = st.get("video_status")
            if vs == "error" or (st.get("processing_phase") or {}).get("status") == "error":
                raise SocialError("invalid", f"{self.label} could not process the video ({json.dumps(st)[:200]})")
            if vs in ("ready", "upload_complete", "published") or (st.get("processing_phase") or {}).get("status") == "complete":
                return True
            if time.time() - t0 > min(budget, 120):
                return False
            self.pause(5)

    def _rupload(self, base, ident, token, path):
        """Meta's resumable upload: the whole file (or what is left of it) to rupload.facebook.com, with its offset."""
        size = Path(path).stat().st_size
        up = self.api(base, {}, 600)
        st, h, content = up.request("POST", f"{base}/{ident}", data=Path(path).read_bytes(), raw=True, retries=2,
                                    headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size), "Content-Type": "application/octet-stream"})
        if st >= 400:
            try:
                body = json.loads(content.decode("utf-8"))
            except (ValueError, UnicodeDecodeError, AttributeError):
                body = {}
            raise self.classify(HubError(f"upload {st}", st, body))
        return True


class Facebook(_Meta):
    name, label = "facebook", "Facebook"
    formats = ("post", "photo", "carousel", "video", "reel", "story")
    native_schedule = True

    def ready(self):
        return bool(self.creds.get("page_token"))

    def page(self):
        self.need("page_token", "page_id")
        return self.creds["page_id"], self.creds["page_token"]

    def whoami(self):
        pid, tok = self.page()
        p = self.call(self.gapi(tok).get, pid, params={"fields": "name,followers_count,link"})
        return {"who": p.get("name"), "where": "Facebook Page" + (f", {p['followers_count']} followers" if p.get("followers_count") is not None else ""),
                "id": pid}

    def warnings(self, post, target):
        w = []
        if not self.creds.get("live"):
            w.append("if the Meta app is still in Development mode, only you can see Page posts: switch the app to Live (ai-pc social steps facebook)")
        return w

    def _schedule(self, post, body):
        if post.get("when"):
            ts = _unix(post["when"])
            if ts < time.time() + 600:
                return False
            if ts > time.time() + 30 * 86400:
                raise SocialError("invalid", "Facebook schedules posts up to 30 days ahead")
            body.update(published="false", scheduled_publish_time=str(ts))
            return True
        return False

    def _photo(self, tok, pid, path, extra, once=False):
        body, ctype = multipart({k: str(v) for k, v in extra.items()}, {"source": (Path(path).name, Path(path).read_bytes(), "image/jpeg")})
        return self.call(self.gapi(tok).request, "POST", f"{pid}/photos", data=body, headers={"Content-Type": ctype}, retries=0 if once else 3)

    def _recent(self, pid, tok, text):
        """The Page's latest posts searched for this exact text (after a post whose answer was lost)."""
        js = self.call(self.gapi(tok).get, f"{pid}/feed", params={"fields": "id,message,created_time", "limit": 5})
        return next((p["id"] for p in js.get("data") or [] if (p.get("message") or "").strip() == (text or "").strip()), None)

    def temp_photo(self, path):
        """An unpublished, temporary Page photo, for its public address (Meta deletes it after 24 hours)."""
        pid, tok = self.page()
        r = self._photo(tok, pid, path, {"published": "false", "temporary": "true"})
        imgs = self.call(self.gapi(tok).get, r["id"], params={"fields": "images"}).get("images") or []
        if not imgs:
            raise SocialError("retry", "Facebook gave no address for the picture")
        return {"id": r["id"], "url": max(imgs, key=lambda i: i.get("width", 0))["source"]}

    def publish(self, job, post, prepared, budget=120):
        pid, tok = self.page()
        r = job.get("remote") or {}
        fmt = job.get("format") or "post"
        text = prepared.get("text") or ""
        t0 = time.time()
        if r.get("post_id"):
            return self._done(job, post, tok, r["post_id"], r.get("video_id"))
        if r.get("posting") and fmt in ("post", "photo", "carousel"):  # sent before, answer lost: is it on the Page already?
            hit = self._recent(pid, tok, text)
            if hit:
                self.checkpoint(job, post_id=hit, posting=False)
                return self._done(job, post, tok, hit)
        if fmt in ("post", "photo", "carousel"):
            self.checkpoint(job, posting=True)
        if fmt == "post":
            body = {"message": text}
            if post.get("link"):
                body["link"] = post["link"]
            sched = self._schedule(post, body)
            res = self.call(self.gapi(tok).post, f"{pid}/feed", json=body, retries=0)
            self.checkpoint(job, post_id=res["id"], scheduled=sched)
        elif fmt in ("photo", "carousel") and len(prepared["media"]) == 1:
            extra = {"message": text}
            alts = post.get("alt") or []
            if alts:
                extra["alt_text_custom"] = alts[0]
            sched = self._schedule(post, extra)
            res = self._photo(tok, pid, prepared["media"][0], extra, once=True)
            self.checkpoint(job, post_id=res.get("post_id") or res["id"], scheduled=sched)
        elif fmt in ("photo", "carousel"):
            ids = list(r.get("photos") or [])
            body = {"message": text}
            sched = self._schedule(post, body)
            for i, m in enumerate(prepared["media"]):
                if i < len(ids):
                    continue
                extra = {"published": "false"}
                if sched:
                    extra["temporary"] = "true"
                alts = post.get("alt") or []
                if i < len(alts) and alts[i]:
                    extra["alt_text_custom"] = alts[i]
                ids.append(self._photo(tok, pid, m, extra)["id"])
                self.checkpoint(job, photos=ids)
            body["attached_media"] = [{"media_fbid": x} for x in ids]
            res = self.call(self.gapi(tok).post, f"{pid}/feed", json=body, retries=0)
            self.checkpoint(job, post_id=res["id"], scheduled=sched)
        elif fmt == "video":
            return self._video(job, post, prepared, pid, tok, budget, t0)
        elif fmt in ("reel", "story"):
            return self._reel(job, post, prepared, pid, tok, budget, t0, fmt)
        else:
            raise SocialError("invalid", f"Facebook has no '{fmt}' post")
        return self._done(job, post, tok, job["remote"]["post_id"])

    def _video(self, job, post, prepared, pid, tok, budget, t0):
        r = job.get("remote") or {}
        path = Path(prepared["media"][0])
        size = path.stat().st_size
        user = self.creds.get("user_token") or tok
        if not r.get("video_id"):
            if not r.get("upload"):
                s = self.call(self.gapi(user).post, f"{self.creds.get('app_id')}/uploads",
                              params={"file_name": path.name, "file_length": size, "file_type": "video/mp4"})
                self.checkpoint(job, upload=s["id"])
                r = job["remote"]
            if not r.get("handle"):
                st, h, content = self.api(GRAPH, {}, 600).request("POST", f"{GRAPH}/{r['upload']}", data=path.read_bytes(), raw=True, retries=2,
                                                                  headers={"Authorization": f"OAuth {user}", "file_offset": "0"})
                if st >= 400:
                    self.checkpoint(job, upload=None)
                    raise SocialError("retry" if st >= 500 else "invalid", f"Facebook refused the video upload ({st})")
                self.checkpoint(job, handle=json.loads(content.decode("utf-8"))["h"])
                r = job["remote"]
            body = {"title": (prepared.get("title") or post.get("title") or "")[:255], "description": prepared.get("text") or "",
                    "fbuploader_video_file_chunk": r["handle"]}
            sched = self._schedule(post, body)
            res = self.call(self.gapi(tok).post, f"{pid}/videos", json=body, retries=0)
            self.checkpoint(job, video_id=res["id"], post_id=res["id"], scheduled=sched)
            r = job["remote"]
        if not self._wait_video(tok, r["video_id"], budget, t0):
            return {"status": "processing", "wait": 30, "detail": "Facebook is processing the video"}
        return self._done(job, post, tok, r["post_id"], r["video_id"])

    def _reel(self, job, post, prepared, pid, tok, budget, t0, fmt):
        r = job.get("remote") or {}
        edge = "video_reels" if fmt == "reel" else "video_stories"
        kinds = prepared.get("kinds") or ["video"]
        if fmt == "story" and kinds[0] == "image":
            photo = r.get("photo") or self._photo(tok, pid, prepared["media"][0], {"published": "false"})["id"]
            self.checkpoint(job, photo=photo)
            res = self.call(self.gapi(tok).post, f"{pid}/photo_stories", json={"photo_id": photo})
            self.checkpoint(job, post_id=res.get("post_id") or res.get("id"))
            return self._done(job, post, tok, job["remote"]["post_id"])
        if not r.get("video_id"):
            res = self.call(self.gapi(tok).post, f"{pid}/{edge}", json={"upload_phase": "start"})
            self.checkpoint(job, video_id=res["video_id"], uploaded=False)
            r = job["remote"]
        if not r.get("uploaded"):
            self._rupload(RUPLOAD_FB, r["video_id"], tok, prepared["media"][0])
            self.checkpoint(job, uploaded=True)
        if not r.get("finished"):
            if not self._wait_upload(tok, r["video_id"], budget, t0):
                return {"status": "processing", "wait": 20, "detail": "Facebook is receiving the video"}
            body = {"upload_phase": "finish", "video_id": r["video_id"]}
            if fmt == "reel":
                body.update(video_state="PUBLISHED", description=prepared.get("text") or "")
                if post.get("when") and _unix(post["when"]) > time.time() + 600:
                    body.update(video_state="SCHEDULED", scheduled_publish_time=str(_unix(post["when"])))
                    self.checkpoint(job, scheduled=True)
            res = self.call(self.gapi(tok).post, f"{pid}/{edge}", json=body, retries=0)
            self.checkpoint(job, finished=True, post_id=res.get("post_id") or r["video_id"])
            r = job["remote"]
        if not self._wait_video(tok, r["video_id"], budget, t0):
            return {"status": "processing", "wait": 30, "detail": "Facebook is processing the reel"}
        return self._done(job, post, tok, r["post_id"], r["video_id"])

    def _wait_upload(self, tok, vid, budget, t0):
        while True:
            st = self.call(self.gapi(tok).get, vid, params={"fields": "status"}).get("status") or {}
            up = (st.get("uploading_phase") or {}).get("status")
            if up in ("complete", None):
                return True
            if up == "error":
                raise SocialError("invalid", "Facebook did not receive the video")
            if time.time() - t0 > min(budget, 60):
                return False
            self.pause(3)

    def _done(self, job, post, tok, post_id, video_id=None):
        r = job.get("remote") or {}
        if r.get("scheduled"):
            return {"status": "scheduled", "id": post_id, "publish_at": post.get("when")}
        got = self.call(self.gapi(tok).get, video_id or post_id, params={"fields": "permalink_url"})
        link = got.get("permalink_url")
        if link and link.startswith("/"):
            link = "https://www.facebook.com" + link
        return {"status": "published", "id": post_id, "permalink": link, "verified": bool(link)}

    def status(self, job):
        pid, tok = self.page()
        r = job.get("remote") or {}
        got = self.call(self.gapi(tok).get, r.get("video_id") or r.get("post_id"), params={"fields": "permalink_url,is_published"})
        if got.get("is_published") is False:
            return {"status": "scheduled"}
        link = got.get("permalink_url") or ""
        return {"status": "published", "permalink": ("https://www.facebook.com" + link) if link.startswith("/") else link}

    def delete(self, job):
        pid, tok = self.page()
        r = job.get("remote") or {}
        res = self.call(self.gapi(tok).request, "DELETE", r.get("post_id") or r.get("video_id"))
        if not res.get("success", True):
            raise SocialError("invalid", "Facebook did not delete it")
        return {"deleted": r.get("post_id")}

    def metrics(self, job):
        pid, tok = self.page()
        r = job.get("remote") or {}
        post_id = r.get("post_id")
        out = {}
        try:
            got = self.call(self.gapi(tok).get, post_id, params={"fields": "shares,reactions.summary(total_count),comments.summary(total_count)"})
            out["likes"] = ((got.get("reactions") or {}).get("summary") or {}).get("total_count")
            out["comments"] = ((got.get("comments") or {}).get("summary") or {}).get("total_count")
            out["shares"] = (got.get("shares") or {}).get("count", 0)
        except SocialError:
            pass
        try:
            ins = self.call(self.gapi(tok).get, f"{post_id}/insights", params={"metric": "post_media_view,post_total_media_view_unique"})
            vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in ins.get("data") or []}
            out["views"], out["reach"] = vals.get("post_media_view"), vals.get("post_total_media_view_unique")
        except SocialError:
            pass
        return {k: v for k, v in out.items() if v is not None}

    def comments(self, job, since=None):
        pid, tok = self.page()
        js = self.call(self.gapi(tok).get, f"{job['remote']['post_id']}/comments", params={"filter": "stream", "fields": "id,message,created_time,from"})
        return [{"id": c["id"], "author": (c.get("from") or {}).get("name") or "someone", "text": c.get("message", ""), "created": c.get("created_time")}
                for c in js.get("data") or []]

    def reply(self, job, comment_id, text):
        pid, tok = self.page()
        res = self.call(self.gapi(tok).post, f"{comment_id}/comments", json={"message": text}, retries=0)
        return {"id": res.get("id"), "verified": bool(res.get("id"))}

    def hide(self, job, comment_id, hidden=True):
        pid, tok = self.page()
        self.call(self.gapi(tok).post, comment_id, json={"is_hidden": "true" if hidden else "false"})
        return {"hidden": hidden}


class Instagram(_Meta):
    name, label = "instagram", "Instagram"
    formats = ("photo", "carousel", "reel", "story")
    native_schedule = False

    def ready(self):
        return bool(self.creds.get("ig_id"))

    def tok(self):
        self.need("ig_id")
        if self.creds.get("ig_mode") == "instagram":
            from ai_pc.social import auth
            return auth.fresh_token(self) if not self.transport else self.creds["access_token"]
        return self.creds.get("user_token") or self.creds.get("page_token")

    def base(self):
        return "https://graph.instagram.com/v26.0" if self.creds.get("ig_mode") == "instagram" else GRAPH

    def ig(self):
        return self.gapi(self.tok(), self.base())

    def whoami(self):
        u = self.call(self.ig().get, self.creds["ig_id"], params={"fields": "username,followers_count"})
        return {"who": "@" + (u.get("username") or "?"), "where": "Instagram" + (f", {u['followers_count']} followers" if u.get("followers_count") is not None else ""),
                "id": self.creds["ig_id"]}

    def limits(self):
        js = self.call(self.ig().get, f"{self.creds['ig_id']}/content_publishing_limit", params={"fields": "quota_usage,config"})
        d = (js.get("data") or [{}])[0]
        total = (d.get("config") or {}).get("quota_total") or 50
        left = total - (d.get("quota_usage") or 0)
        return {"posts_left": left, "words": f"{left} of {total} posts left in 24 hours"}

    def host(self):
        from ai_pc.social.mediahost import MediaHost
        fb = None
        if self.creds.get("page_token"):
            fb = Facebook(self.creds, self.transport, self.store, self.pause)
        return getattr(self, "_host_factory", lambda: MediaHost(facebook=fb))()

    def _container(self, params):
        return self.call(self.ig().post, f"{self.creds['ig_id']}/media", json=params)

    def _video_container(self, job, key, path, params):
        """A video container made for resumable upload, and its bytes sent from this PC (Facebook-login apps only)."""
        r = job.get("remote") or {}
        if self.creds.get("ig_mode") == "instagram":  # no resumable upload with Instagram login: the video goes by web address too
            return None
        c = (r.get(key) or {})
        if not c.get("id"):
            res = self._container(dict(params, upload_type="resumable"))
            c = {"id": res["id"], "sent": False}
            self.checkpoint(job, **{key: c})
        if not c.get("sent"):
            self._rupload(RUPLOAD_IG, c["id"], self.tok(), path)
            c["sent"] = True
            self.checkpoint(job, **{key: c})
        return c["id"]

    def _status(self, cid):
        js = self.call(self.ig().get, cid, params={"fields": "status_code,status"})
        return js.get("status_code"), js.get("status")

    def _wait(self, ids, budget, t0, every=10):
        while True:
            states = {i: self._status(i) for i in ids}
            bad = {i: s for i, s in states.items() if s[0] in ("ERROR", "EXPIRED")}
            if bad:
                i, (code, why) = next(iter(bad.items()))
                raise SocialError("invalid" if code == "ERROR" else "retry", f"Instagram could not use the media ({code}: {why or 'no reason given'})")
            if all(s[0] in ("FINISHED", "PUBLISHED") for s in states.values()):
                return True
            if time.time() - t0 > min(budget, 300):
                return False
            self.pause(every)

    def publish(self, job, post, prepared, budget=120):
        t0 = time.time()
        r = job.get("remote") or {}
        if r.get("media_id"):
            return self._done(job)
        lim = self.limits()
        if lim.get("posts_left", 1) <= 0:
            raise SocialError("limit", "Instagram: the 24-hour publishing limit is reached", retry_after=3600)
        fmt = job.get("format") or "photo"
        media, kinds = prepared.get("media") or [], prepared.get("kinds") or []
        caption = prepared.get("text") or ""
        alts = post.get("alt") or []
        host = None
        try:
            if not r.get("container"):
                if fmt in ("reel", "story") and kinds and kinds[0] == "video":
                    params = {"media_type": "REELS" if fmt == "reel" else "STORIES"}
                    if fmt == "reel":
                        params.update(caption=caption, share_to_feed="true")
                        if post.get("cover_at") is not None:
                            params["thumb_offset"] = str(int(post["cover_at"] * 1000))
                    cid = self._video_container(job, "main", media[0], params)
                    if cid is None:
                        host = self.host()
                        cid = self._container(dict(params, video_url=host.open(media[0])))["id"]
                elif fmt == "carousel":
                    kids = list(r.get("children") or [])
                    for i, (m, k) in enumerate(zip(media, kinds)):
                        if i < len(kids):
                            continue
                        if k == "video":
                            cid = self._video_container(job, f"child{i}", m, {"media_type": "VIDEO", "is_carousel_item": "true"})
                            if cid is None:
                                host = host or self.host()
                                cid = self._container({"media_type": "VIDEO", "is_carousel_item": "true", "video_url": host.open(m)})["id"]
                        else:
                            host = host or self.host()
                            p = {"image_url": host.open(m), "is_carousel_item": "true"}
                            if i < len(alts) and alts[i]:
                                p["alt_text"] = alts[i][:1000]
                            cid = self._container(p)["id"]
                        kids.append(cid)
                        self.checkpoint(job, children=kids)
                    if not self._wait(kids, budget, t0):
                        return {"status": "processing", "wait": 30, "detail": "Instagram is preparing the slides"}
                    cid = self._container({"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption})["id"]
                else:  # a feed picture, or a picture story
                    host = self.host()
                    p = {"image_url": host.open(media[0])}
                    if fmt == "story":
                        p["media_type"] = "STORIES"
                    else:
                        p["caption"] = caption
                        if alts and alts[0]:
                            p["alt_text"] = alts[0][:1000]
                    cid = self._container(p)["id"]
                self.checkpoint(job, container=cid)
                r = job["remote"]
            if not self._wait([r["container"]], budget, t0, every=10 if host is None else 3):
                return {"status": "processing", "wait": 60, "detail": "Instagram is preparing the post"}
        finally:
            if host is not None:
                host.close()
        if r.get("publishing"):  # sent before, answer lost: is it on the account already?
            js = self.call(self.ig().get, f"{self.creds['ig_id']}/media", params={"fields": "id,caption,timestamp", "limit": 5})
            hit = next((m["id"] for m in js.get("data") or [] if (m.get("caption") or "").strip() == (prepared.get("text") or "").strip()), None)
            if hit:
                self.checkpoint(job, media_id=hit, publishing=False)
                return self._done(job)
        self.checkpoint(job, publishing=True)
        res = self.call(self.ig().post, f"{self.creds['ig_id']}/media_publish", json={"creation_id": r["container"]}, retries=0)
        self.checkpoint(job, media_id=res["id"], publishing=False)
        return self._done(job)

    def _done(self, job):
        mid = job["remote"]["media_id"]
        got = self.call(self.ig().get, mid, params={"fields": "permalink,media_type"})
        return {"status": "published", "id": mid, "permalink": got.get("permalink"), "verified": bool(got.get("permalink"))}

    def status(self, job):
        return {"status": "published"}

    def delete(self, job):
        if self.creds.get("ig_mode") == "instagram":
            raise SocialError("policy", "Instagram lets apps delete posts only with Facebook login; delete it in the Instagram app")
        res = self.call(self.ig().request, "DELETE", job["remote"]["media_id"])
        if not res.get("success", True):
            raise SocialError("invalid", "Instagram did not delete it")
        return {"deleted": job["remote"]["media_id"]}

    def metrics(self, job):
        mid = job["remote"]["media_id"]
        fmt = job.get("format")
        metric = "views,reach,likes,comments,shares,saved" if fmt != "story" else "views,reach,replies"
        js = self.call(self.ig().get, f"{mid}/insights", params={"metric": metric})
        vals = {d["name"]: (d.get("values") or [{}])[0].get("value") for d in js.get("data") or []}
        return {"views": vals.get("views"), "reach": vals.get("reach"), "likes": vals.get("likes"), "comments": vals.get("comments"),
                "shares": vals.get("shares"), "saves": vals.get("saved")}

    def comments(self, job, since=None):
        js = self.call(self.ig().get, f"{job['remote']['media_id']}/comments", params={"fields": "id,text,timestamp,username"})
        return [{"id": c["id"], "author": "@" + (c.get("username") or "someone"), "text": c.get("text", ""), "created": c.get("timestamp")}
                for c in js.get("data") or []]

    def reply(self, job, comment_id, text):
        res = self.call(self.ig().post, f"{comment_id}/replies", json={"message": text}, retries=0)
        return {"id": res.get("id"), "verified": bool(res.get("id"))}

    def hide(self, job, comment_id, hidden=True):
        self.call(self.ig().post, comment_id, json={"hide": "true" if hidden else "false"})
        return {"hidden": hidden}
