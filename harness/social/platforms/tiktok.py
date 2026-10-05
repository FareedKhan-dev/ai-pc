"""TikTok through its Content Posting API (Login Kit for Desktop, PKCE, open.tiktokapis.com), as TikTok allows it for a
personal tool in 2026. TikTok audits apps before they may post publicly and does not audit tools for one's own account,
so this connector:
  - sends a video to your TikTok inbox as a draft by default (you open TikTok, adjust and post it publicly yourself), or
  - posts it directly as private ("only me") when asked: TikTok then requires the account itself to be private;
  - turns pictures into a short slideshow video (TikTok takes photo posts only from a web address on a verified domain).
It asks TikTok what the creator may post first (creator_info: nickname, longest video, privacy choices), uploads in the
chunks TikTok asks for (5-64 MB, the remainder in the last), resumes after a break, and polls until TikTok confirms.
TikTok cannot delete or edit posts through its API, does not give comments, and gives numbers only for public videos.
"""
import math
from pathlib import Path

from ..base import Platform, SocialError

API = "https://open.tiktokapis.com"
MB = 1024 * 1024
FAILS = {"file_format_check_failed": "TikTok did not accept the file's format", "duration_check_failed": "the video is too long or too short for this account",
         "frame_rate_check_failed": "TikTok wants 23-60 frames a second", "picture_size_check_failed": "the frame size is outside 360-4096 px",
         "spam_risk_too_many_posts": "TikTok's daily posting limit for this account is reached", "spam_risk_user_banned_from_posting": "TikTok has stopped this account posting",
         "spam_risk_text": "TikTok flagged the caption as spam", "spam_risk": "TikTok flagged this as spam", "auth_removed": "the TikTok sign-in was withdrawn",
         "publish_cancelled": "the post was cancelled"}


PREF = 10 * MB


def chunk_plan(size, pref=None):
    """(chunk_size, count) as TikTok requires: a small file (up to two chunks' worth) in one piece; otherwise chunks of 5-64 MB
    with the remainder joined to the last (up to 128 MB); count = floor(size / chunk_size), 1-1000."""
    pref = pref or PREF
    if size <= 2 * pref:
        return size, 1
    cs = min(max(pref, 5 * MB), 64 * MB) if pref >= 5 * MB else pref
    while size // cs > 1000:
        cs = min(cs * 2, 64 * MB)
    return cs, size // cs


def ranges(size, cs, n):
    out = []
    for i in range(n):
        a = i * cs
        b = size - 1 if i == n - 1 else (i + 1) * cs - 1
        out.append((a, b))
    return out


class TikTok(Platform):
    name, label = "tiktok", "TikTok"
    formats = ("video", "photo")
    native_schedule = False
    can_delete = False

    def token(self):
        self.need("access_token")
        from .. import auth
        return auth.fresh_token(self) if not self.transport else self.creds["access_token"]

    def tapi(self, timeout=60):
        return self.api(API, {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json; charset=UTF-8"}, timeout)

    def _post(self, path, body, query=None):
        js = self.call(self.tapi().request, "POST", path, params=query, json_body=body)
        err = js.get("error") or {}
        code = err.get("code")
        if code not in (None, "ok"):
            raise self._err(code, err.get("message"))
        return js.get("data") or {}

    def classify(self, e):
        """TikTok's own error envelope ({"error": {"code", "message", "log_id"}}) read even when it comes with an HTTP error status."""
        body = e.body if isinstance(getattr(e, "body", None), dict) else {}
        err = body.get("error")
        if isinstance(err, dict) and err.get("code") not in (None, "ok"):
            return self._err(err["code"], err.get("message"))
        if isinstance(err, str) and body.get("error_description"):  # the sign-in endpoints' flat shape
            return SocialError("auth", f"TikTok: {err}: {body['error_description']}")
        return super().classify(e)

    def _err(self, code, msg=""):
        if code in ("access_token_invalid", "scope_not_authorized"):
            return SocialError("auth", f"TikTok: the sign-in has expired or lacks a permission ({code}); connect again")
        if code == "rate_limit_exceeded":
            return SocialError("limit", "TikTok: too many requests this minute", retry_after=60)
        if code in ("spam_risk_too_many_posts", "spam_risk_too_many_pending_share", "reached_active_user_cap"):
            return SocialError("limit", f"TikTok: {FAILS.get(code, code)} (try tomorrow)", retry_after=6 * 3600)
        if code == "unaudited_client_can_only_post_to_private_accounts":
            return SocialError("policy", "TikTok lets this app post directly only while your account is private (TikTok audits apps before public "
                                         "posting and does not audit personal tools); send it as a draft instead, or make the account private for the post")
        if code == "internal_error":
            return SocialError("retry", "TikTok had a problem; trying again")
        return SocialError("invalid", f"TikTok: {code} {msg or ''}".strip())

    # ---------------------------------------------------------------- who and what
    def whoami(self):
        js = self.call(self.tapi().get, "v2/user/info/", params={"fields": "open_id,display_name,username"})
        u = (js.get("data") or {}).get("user") or {}
        return {"who": u.get("display_name"), "where": f"TikTok @{u.get('username')}" if u.get("username") else "TikTok", "id": u.get("open_id")}

    def creator(self):
        return self._post("v2/post/publish/creator_info/query/", {})

    def warnings(self, post, target):
        draft = (post.get("privacy") or "draft") not in ("private",)
        w = ["goes to your TikTok inbox as a draft: open TikTok to post it publicly (TikTok lets personal tools post publicly only that way)" if draft else
             "posts as private ('only me'); TikTok requires your account to be private while it posts, and you make the video public in the app"]
        w.append("By posting, you agree to TikTok's Music Usage Confirmation")
        return w

    # ---------------------------------------------------------------- publishing
    def publish(self, job, post, prepared, budget=120):
        import time
        r = job.get("remote") or {}
        media = prepared.get("media") or []
        if not media:
            raise SocialError("invalid", "TikTok needs a video")
        path = Path(media[0])
        size = path.stat().st_size
        direct = (post.get("privacy") or "draft") == "private"
        if not r.get("publish_id"):
            info = self.creator()
            if info.get("max_video_post_duration_sec") and prepared.get("duration") and prepared["duration"] > info["max_video_post_duration_sec"]:
                raise SocialError("invalid", f"TikTok lets this account post videos up to {info['max_video_post_duration_sec']} s")
            if direct and "SELF_ONLY" not in (info.get("privacy_level_options") or ["SELF_ONLY"]):
                raise SocialError("policy", "TikTok does not offer 'only me' for this account now")
            cs, n = chunk_plan(size)
            src = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": cs, "total_chunk_count": n}
            if direct:
                body = {"post_info": {"title": (prepared.get("text") or "")[:2200], "privacy_level": "SELF_ONLY", "disable_comment": False,
                                      "disable_duet": False, "disable_stitch": False, "brand_content_toggle": False, "brand_organic_toggle": False,
                                      "is_aigc": bool(post.get("ai"))}, "source_info": src}
                d = self._post("v2/post/publish/video/init/", body)
            else:
                d = self._post("v2/post/publish/inbox/video/init/", {"source_info": src})
            self.checkpoint(job, publish_id=d["publish_id"], upload_url=d["upload_url"], upload_at=time.time(), chunk_size=cs, chunks=n, sent=0,
                            draft=not direct, creator=info.get("creator_nickname"))
            r = job["remote"]
        if r.get("sent", 0) < r["chunks"]:
            if time.time() - r.get("upload_at", 0) > 3500:  # TikTok's upload address lasts an hour: start again with a fresh one
                self.checkpoint(job, publish_id=None, upload_url=None, sent=0)
                raise SocialError("retry", "TikTok's upload address expired; starting the upload again")
            up = self.api("https://open-upload.tiktokapis.com", timeout=300)
            with path.open("rb") as f:
                for i, (a, b) in enumerate(ranges(size, r["chunk_size"], r["chunks"])):
                    if i < r.get("sent", 0):
                        continue
                    f.seek(a)
                    data = f.read(b - a + 1)
                    status, _, content = up.request("PUT", r["upload_url"], data=data, raw=True, retries=2,
                                                    headers={"Content-Type": "video/mp4", "Content-Length": str(len(data)), "Content-Range": f"bytes {a}-{b}/{size}"})
                    if status in (201, 206):
                        self.checkpoint(job, sent=i + 1)
                        continue
                    if status in (403, 404):
                        self.checkpoint(job, publish_id=None, upload_url=None, sent=0)
                        raise SocialError("retry", f"TikTok's upload address stopped working ({status}); starting again")
                    if status >= 500 or status == 416:
                        raise SocialError("retry", f"TikTok's upload answered {status}; resuming from chunk {i + 1}")
                    raise SocialError("invalid", f"TikTok refused the upload ({status}: {content[:200]!r})")
        t0 = time.time()
        while True:
            d = self._post("v2/post/publish/status/fetch/", {"publish_id": r["publish_id"]})
            st = d.get("status")
            if st in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
                ids = d.get("publicaly_available_post_id") or []  # (TikTok's spelling) filled only for public posts
                if ids:
                    self.checkpoint(job, video_id=str(ids[0]))
                return {"status": "published", "id": str(ids[0]) if ids else r["publish_id"], "permalink": None, "verified": True,
                        "notes": ["in your TikTok inbox: open TikTok to post it" if r.get("draft") else "posted as private ('only me')"]}
            if st == "FAILED":
                why = d.get("fail_reason") or "unknown"
                self.checkpoint(job, publish_id=None, upload_url=None, sent=0)
                if why == "internal":
                    raise SocialError("retry", "TikTok failed inside; trying again")
                raise SocialError("invalid", f"TikTok: {FAILS.get(why, why)}")
            if time.time() - t0 > min(budget, 60):
                return {"status": "processing", "wait": 20, "detail": st}
            self.pause(5)

    def status(self, job):
        return {"status": "published"}

    def metrics(self, job):
        vid = (job.get("remote") or {}).get("video_id")
        if not vid:
            return {}  # drafts and private videos have no numbers in TikTok's API
        js = self.call(self.tapi().request, "POST", "v2/video/query/", params={"fields": "id,view_count,like_count,comment_count,share_count,share_url"},
                       json_body={"filters": {"video_ids": [vid]}})
        vs = (js.get("data") or {}).get("videos") or []
        if not vs:
            return {}
        v = vs[0]
        return {"views": v.get("view_count"), "likes": v.get("like_count"), "comments": v.get("comment_count"), "shares": v.get("share_count"),
                "url": v.get("share_url")}
