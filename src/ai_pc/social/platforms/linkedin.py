"""LinkedIn through its versioned REST API (Linkedin-Version 202609, Rest.li 2.0): text posts, an image, 2-20 images, or a
video on your own profile ('Share on LinkedIn', no review needed). Images: initializeUpload then a PUT of the bytes.
Videos: initializeUpload with the size, the 4 MiB parts LinkedIn lists PUT one by one (their ETags kept in order),
finalizeUpload, then waited on. Posts: POST /rest/posts; the new post's id comes back in the x-restli-id header.
Commentary is LinkedIn's 'little text' (reserved characters escaped, done in text.py).

What a personal app cannot do on LinkedIn (its rules, not ours): read posts back, see comments, or get statistics
(those need the Community Management API, for registered businesses). So a post whose answer was lost is never sent
again blindly: it is marked for you to look at your profile, and statistics say so instead of guessing.
"""
import urllib.parse
from pathlib import Path

from ai_pc.social.base import Platform, SocialError

API = "https://api.linkedin.com"
VERSION = "202609"


class LinkedIn(Platform):
    name, label = "linkedin", "LinkedIn"
    formats = ("post", "image", "carousel", "video")
    native_schedule = False

    def token(self):
        self.need("access_token")
        from ai_pc.social import auth
        return auth.fresh_token(self) if not self.transport else self.creds["access_token"]

    def lapi(self, versioned=True, timeout=60):
        h = {"Authorization": f"Bearer {self.token()}"}
        if versioned:
            h.update({"Linkedin-Version": VERSION, "X-Restli-Protocol-Version": "2.0.0"})
        return self.api(API, h, timeout)

    def whoami(self):
        u = self.call(self.lapi(False).get, "v2/userinfo")
        if u.get("sub") and self.creds.get("person") != u["sub"] and not self.transport:
            from ai_pc.core import vault
            vault.put("linkedin", {"person": u["sub"]})
        self.creds["person"] = u.get("sub")
        return {"who": u.get("name"), "where": f"LinkedIn ({u.get('email')})" if u.get("email") else "LinkedIn", "id": u.get("sub")}

    def urn(self):
        if not self.creds.get("person"):
            self.whoami()
        return f"urn:li:person:{self.creds['person']}"

    def warnings(self, post, target):
        return ["LinkedIn does not let personal apps read posts back or see their numbers; check the post on your profile"]

    # ---------------------------------------------------------------- media
    def _image(self, path):
        js = self.call(self.lapi().post, "rest/images", params={"action": "initializeUpload"},
                       json={"initializeUploadRequest": {"owner": self.urn()}})
        v = js.get("value") or {}
        up = self.api(API, {"Authorization": f"Bearer {self.token()}"}, 300)
        st, _, content = up.request("PUT", v["uploadUrl"], data=Path(path).read_bytes(), raw=True, headers={"Content-Type": "application/octet-stream"})
        if st not in (200, 201):
            raise SocialError("retry" if st >= 500 else "invalid", f"LinkedIn refused the picture upload ({st})")
        return v["image"]

    def _video(self, path, job):
        r = job.get("remote") or {}
        size = Path(path).stat().st_size
        if not r.get("video"):
            js = self.call(self.lapi().post, "rest/videos", params={"action": "initializeUpload"},
                           json={"initializeUploadRequest": {"owner": self.urn(), "fileSizeBytes": size, "uploadCaptions": False, "uploadThumbnail": False}})
            v = js.get("value") or {}
            parts = [{"url": i["uploadUrl"], "a": int(i["firstByte"]), "b": int(i["lastByte"])} for i in v.get("uploadInstructions") or []]
            self.checkpoint(job, video=v["video"], upload_token=v.get("uploadToken", ""), parts=parts, etags=[])
            r = job["remote"]
        if len(r.get("etags") or []) < len(r["parts"]):
            up = self.api(API, {}, 300)  # LinkedIn's upload addresses are signed: no key is sent to them
            etags = list(r.get("etags") or [])
            with Path(path).open("rb") as f:
                for i, part in enumerate(r["parts"]):
                    if i < len(etags):
                        continue
                    f.seek(part["a"])
                    data = f.read(part["b"] - part["a"] + 1)
                    st, h, _ = up.request("PUT", part["url"], data=data, raw=True, retries=2, headers={"Content-Type": "application/octet-stream"})
                    if st not in (200, 201):
                        raise SocialError("retry" if st >= 500 else "invalid", f"LinkedIn refused part {i + 1} of the video ({st})")
                    etags.append((h or {}).get("ETag") or (h or {}).get("etag"))
                    self.checkpoint(job, etags=etags)
        if not r.get("finalized"):
            self.call(self.lapi().post, "rest/videos", params={"action": "finalizeUpload"},
                      json={"finalizeUploadRequest": {"video": r["video"], "uploadToken": r.get("upload_token", ""), "uploadedPartIds": r["etags"]}})
            self.checkpoint(job, finalized=True)
        return r["video"]

    def _video_ready(self, urn):
        try:
            js = self.call(self.lapi().get, "rest/videos/" + urllib.parse.quote(urn, safe=""))
        except SocialError:
            return True  # personal apps may not be allowed to ask: post it and let LinkedIn finish processing
        st = js.get("status")
        if st == "PROCESSING_FAILED":
            raise SocialError("invalid", "LinkedIn could not process the video")
        return st in (None, "AVAILABLE")

    # ---------------------------------------------------------------- publishing
    def publish(self, job, post, prepared, budget=120):
        import time
        r = job.get("remote") or {}
        if r.get("post_urn"):
            return {"status": "published", "id": r["post_urn"], "permalink": self._link(r["post_urn"]), "verified": True}
        if r.get("posting"):  # the post was sent but its answer never came: LinkedIn cannot be asked, so it is not sent again
            raise SocialError("policy", "the LinkedIn post was sent but LinkedIn's answer was lost; look at your profile before posting it again "
                                        "(personal apps cannot read posts back)")
        media = prepared.get("media") or []
        kinds = prepared.get("kinds") or []
        content = None
        if media and kinds[0] == "video":
            urn = self._video(media[0], job)
            t0 = time.time()
            while not self._video_ready(urn):
                if time.time() - t0 > min(budget, 90):
                    return {"status": "processing", "wait": 20, "detail": "LinkedIn is processing the video"}
                self.pause(5)
            content = {"media": {"id": urn, "title": (post.get("title") or "")[:200]}}
        elif media:
            imgs = list(r.get("images") or [])
            for i, m in enumerate(media):
                if i < len(imgs):
                    continue
                imgs.append(self._image(m))
                self.checkpoint(job, images=imgs)
            alts = post.get("alt") or []
            if len(imgs) == 1:
                content = {"media": {"id": imgs[0], "altText": (alts[0] if alts else "")[:4086]}}
            else:
                content = {"multiImage": {"images": [{"id": u, "altText": (alts[i] if i < len(alts) else "")[:4086]} for i, u in enumerate(imgs)]}}
        body = {"author": self.urn(), "commentary": prepared.get("text") or "", "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        if content:
            body["content"] = content
        self.checkpoint(job, posting=True)
        try:
            st, h, out = self.lapi().request("POST", "rest/posts", json_body=body, raw=True, retries=0, headers={"Content-Type": "application/json"})
        except Exception as e:  # noqa: BLE001  (the answer was lost: LinkedIn cannot be asked, so 'posting' stays set and it is not resent)
            raise SocialError("retry", f"LinkedIn's answer was lost ({type(e).__name__})") from e
        if st == 201:
            urn = (h or {}).get("x-restli-id") or (h or {}).get("X-RestLi-Id") or (h or {}).get("x-linkedin-id")
            self.checkpoint(job, post_urn=urn, posting=False)
            return {"status": "published", "id": urn, "permalink": self._link(urn), "verified": bool(urn),
                    "notes": ["LinkedIn confirmed it (personal apps cannot read posts back)"]}
        self.checkpoint(job, posting=False)  # refused: nothing was posted, so it may be tried again
        import json as _json

        from ai_pc.hub.http import HubError
        try:
            body_js = _json.loads(out.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            body_js = {}
        raise self.classify(HubError(f"linkedin: {st} {body_js.get('message', '')}", st, body_js))

    @staticmethod
    def _link(urn):
        return f"https://www.linkedin.com/feed/update/{urn}/" if urn else None

    def status(self, job):
        return {"status": "published"}

    def delete(self, job):
        urn = (job.get("remote") or {}).get("post_urn") or (job.get("remote") or {}).get("id")
        st, _, _ = self.lapi().request("DELETE", "rest/posts/" + urllib.parse.quote(urn, safe=""), raw=True, headers={"X-RestLi-Method": "DELETE"})
        if st not in (200, 204):
            raise SocialError("retry" if st >= 500 else "invalid", f"LinkedIn did not delete it ({st})")
        return {"deleted": urn}

    def metrics(self, job):
        return {"note": "LinkedIn gives statistics only to approved business apps"}
