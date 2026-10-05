"""Fake platform servers for the social lane, each built from its API docs (2026): they answer like the real ones, keep state,
and check what they are sent (headers, chunk ranges, tokens never sent to upload hosts)."""
import json
import re
import urllib.parse
import urllib.request

from harness.hub.http import FakeTransport


def _q(url):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}


def _range(h):
    m = re.match(r"bytes (\d+)-(\d+)/(\d+)", h or "")
    return tuple(int(x) for x in m.groups()) if m else None


class YouTubeFake:
    def __init__(self, lock_private=False, drop_on_chunk=None, thumb_forbidden=False):
        self.lock_private, self.drop_on_chunk, self.thumb_forbidden = lock_private, drop_on_chunk, thumb_forbidden
        self.received, self.total, self.meta, self.chunks, self.polls = bytearray(), None, None, 0, 0
        self.deleted = self.thumb = self.captions = None
        self.moderated = []

    def transport(self):
        return FakeTransport({
            ("POST", "upload/youtube/v3/videos"): self.start,
            ("PUT", "upload_id=SESSION1"): self.put,
            ("POST", "upload/youtube/v3/thumbnails/set"): self.thumbnail,
            ("POST", "upload/youtube/v3/captions"): self.caption,
            ("GET", "youtube/v3/channels"): (200, {"items": [{"id": "UC1", "snippet": {"title": "Khan Electronics"}, "statistics": {"subscriberCount": "1200"}}]}),
            ("GET", "youtube/v3/videos"): self.video,
            ("DELETE", "youtube/v3/videos"): self.delete,
            ("GET", "youtube/v3/commentThreads"): (200, {"items": [{"snippet": {"topLevelComment": {"id": "YC1", "snippet": {
                "authorDisplayName": "Ali", "textOriginal": "Price of the 55 inch?", "publishedAt": "2026-10-05T10:00:00Z"}}}}]}),
            ("POST", "youtube/v3/comments/setModerationStatus"): self.moderate,
            ("POST", "youtube/v3/comments"): lambda req: (200, {"id": "YR1", "snippet": dict(req["body"]["snippet"])}),
        })

    def start(self, req):
        self.meta = req["body"]
        self.total = int(req["headers"]["X-Upload-Content-Length"])
        self.notify = _q(req["url"]).get("notifySubscribers")
        return 200, b"", {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=SESSION1"}

    def put(self, req):
        cr = req["headers"].get("Content-Range", "")
        if cr.startswith("bytes */"):  # how much do you have?
            if len(self.received) >= self.total:
                return 201, self._resource()
            return (308, b"", {"Range": f"bytes=0-{len(self.received) - 1}"}) if self.received else (308, b"")
        a, b, total = _range(cr)
        data = req["body"] if isinstance(req["body"], (bytes, bytearray)) else json.dumps(req["body"]).encode()
        assert a == len(self.received), f"chunk starts at {a}, server has {len(self.received)}"
        assert b - a + 1 == len(data) and total == self.total
        assert (len(data) % (256 * 1024) == 0) or b == total - 1, "chunks must be multiples of 256 KiB"
        self.chunks += 1
        if self.drop_on_chunk == self.chunks:  # the connection drops half way through this chunk
            self.received += data[: len(data) // 2]
            self.drop_on_chunk = None
            raise OSError("connection reset by peer")
        self.received += data
        if b == total - 1:
            return 201, self._resource()
        return 308, b"", {"Range": f"bytes=0-{b}"}

    def _resource(self):
        return {"id": "VID1", "snippet": self.meta["snippet"], "status": dict(self.meta["status"], uploadStatus="uploaded")}

    def video(self, req):
        q = _q(req["url"])
        if "statistics" in q.get("part", ""):
            return 200, {"items": [{"id": "VID1", "statistics": {"viewCount": "1530", "likeCount": "88", "commentCount": "12"}}]}
        self.polls += 1
        st = dict(self.meta["status"])
        st["uploadStatus"] = "uploaded" if self.polls == 1 else "processed"
        if self.lock_private:
            st["privacyStatus"] = "private"
            st.pop("publishAt", None)
        return 200, {"items": [{"id": "VID1", "status": st, "processingDetails": {"processingStatus": "processing" if self.polls == 1 else "succeeded"}}]}

    def thumbnail(self, req):
        if self.thumb_forbidden:
            return 403, {"error": {"code": 403, "message": "The authenticated user doesnt have permissions to upload and set custom video thumbnails.",
                                   "errors": [{"reason": "forbidden", "domain": "youtube.thumbnail"}]}}
        self.thumb = req["body"]
        return 200, {"items": [{"default": {"url": "https://i.ytimg.com/vi/VID1/default.jpg"}}]}

    def caption(self, req):
        self.captions = req["body"]
        return 200, {"id": "CAP1"}

    def delete(self, req):
        self.deleted = _q(req["url"]).get("id")
        return 204, b""

    def moderate(self, req):
        self.moderated.append(_q(req["url"]))
        return 204, b""


class TikTokFake:
    def __init__(self, public_account=False):
        self.public_account = public_account
        self.received, self.inits, self.status_calls, self.puts = bytearray(), [], 0, []

    def ok(self, data):
        return 200, {"data": data, "error": {"code": "ok", "message": "", "log_id": "L1"}}

    def transport(self):
        return FakeTransport({
            ("GET", "v2/user/info"): self.ok({"user": {"open_id": "O1", "display_name": "Khan Electronics", "username": "khan_pk"}}),
            ("POST", "creator_info/query"): self.ok({"creator_nickname": "Khan Electronics", "creator_username": "khan_pk",
                                                     "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
                                                     "comment_disabled": False, "duet_disabled": False, "stitch_disabled": False,
                                                     "max_video_post_duration_sec": 600}),
            ("POST", "inbox/video/init"): self.init,
            ("POST", "post/publish/video/init"): self.direct,
            ("PUT", "open-upload.tiktokapis.com/video"): self.put,
            ("POST", "post/publish/status/fetch"): self.status,
            ("POST", "v2/video/query"): self.ok({"videos": [{"id": "7300000000000000001", "view_count": 5400, "like_count": 410, "comment_count": 33,
                                                             "share_count": 21, "share_url": "https://www.tiktok.com/@khan_pk/video/7300000000000000001"}]}),
        })

    def init(self, req):
        s = req["body"]["source_info"]
        self.inits.append(("inbox", req["body"]))
        assert s["source"] == "FILE_UPLOAD" and s["total_chunk_count"] == max(1, s["video_size"] // s["chunk_size"])
        self.size = s["video_size"]
        return self.ok({"publish_id": "v_inbox_file~v2.P1", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=U1&upload_token=T1"})

    def direct(self, req):
        self.inits.append(("direct", req["body"]))
        if self.public_account:
            return 403, {"data": {}, "error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "", "log_id": "L2"}}
        self.size = req["body"]["source_info"]["video_size"]
        return self.ok({"publish_id": "v_pub_file~v2.P2", "upload_url": "https://open-upload.tiktokapis.com/video/?upload_id=U2&upload_token=T2"})

    def put(self, req):
        a, b, total = _range(req["headers"]["Content-Range"])
        self.puts.append((a, b, total, "Authorization" in req["headers"]))
        assert a == len(self.received) and total == self.size
        self.received += req["body"]
        return (201, b"") if b == total - 1 else (206, b"")

    def status(self, req):
        self.status_calls += 1
        direct = req["body"]["publish_id"].startswith("v_pub")
        if self.status_calls == 1:
            return self.ok({"status": "PROCESSING_UPLOAD", "uploaded_bytes": len(self.received)})
        return self.ok({"status": "PUBLISH_COMPLETE" if direct else "SEND_TO_USER_INBOX"})


class LinkedInFake:
    def __init__(self):
        self.posts, self.deleted, self.parts, self.images = [], [], [], {}

    def transport(self):
        return FakeTransport({
            ("GET", "v2/userinfo"): (200, {"sub": "abc123", "name": "Fareed Khan", "email": "fareed@example.com"}),
            ("POST", "rest/images?action=initializeUpload"): lambda req: (200, {"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/IMG1?ca=x",
                                                                                         "image": f"urn:li:image:IMG{len(self.images) + 1}"}}),
            ("PUT", "dms-uploads/IMG"): self.put_image,
            ("POST", "rest/videos?action=initializeUpload"): self.init_video,
            ("PUT", "dms-uploads/VID1-part"): self.put_part,
            ("POST", "rest/videos?action=finalizeUpload"): self.finalize,
            ("GET", "rest/videos/"): (200, {"status": "AVAILABLE"}),
            ("POST", "rest/posts"): self.post,
            ("DELETE", "rest/posts/"): self.delete,
        })

    def put_image(self, req):
        assert req["headers"].get("Authorization", "").startswith("Bearer ")
        self.images[f"urn:li:image:IMG{len(self.images) + 1}"] = len(req["body"])
        return 201, b""

    def init_video(self, req):
        n = req["body"]["initializeUploadRequest"]["fileSizeBytes"]
        half = n // 2
        self.video_size = n
        return 200, {"value": {"video": "urn:li:video:VID1", "uploadToken": "TOK", "uploadInstructions": [
            {"uploadUrl": "https://www.linkedin.com/dms-uploads/VID1-part1", "firstByte": 0, "lastByte": half - 1},
            {"uploadUrl": "https://www.linkedin.com/dms-uploads/VID1-part2", "firstByte": half, "lastByte": n - 1}]}}

    def put_part(self, req):
        self.parts.append(("Authorization" in req["headers"], len(req["body"])))
        return 200, b"", {"ETag": f"etag-{len(self.parts)}"}

    def finalize(self, req):
        self.finalized = req["body"]["finalizeUploadRequest"]
        return 200, {}

    def post(self, req):
        h = req["headers"]
        assert h.get("Linkedin-Version") == "202609" and h.get("X-Restli-Protocol-Version") == "2.0.0"
        self.posts.append(req["body"])
        return 201, b"", {"x-restli-id": f"urn:li:share:{7000 + len(self.posts)}"}

    def delete(self, req):
        self.deleted.append((urllib.parse.unquote(req["url"].rsplit("/", 1)[1]), req["headers"].get("X-RestLi-Method")))
        return 204, b""


class XFake:
    def __init__(self, lose_first_answer=False):
        self.lose_first_answer = lose_first_answer
        self.tweets, self.appends, self.status_calls, self.deleted, self.alt = [], [], 0, [], []

    def transport(self):
        return FakeTransport({
            ("GET", "2/users/me"): (200, {"data": {"id": "U1", "name": "Khan Electronics", "username": "khan_pk"}}),
            ("POST", "2/media/upload/initialize"): lambda req: (200, {"data": {"id": "MV1", "expires_after_secs": 86400}}),
            ("POST", "2/media/upload/MV1/append"): self.append,
            ("POST", "2/media/upload/MV1/finalize"): (200, {"data": {"id": "MV1", "processing_info": {"state": "pending", "check_after_secs": 1}}}),
            ("GET", "2/media/upload?command=STATUS"): self.status,
            ("POST", "2/media/upload"): (200, {"data": {"id": "MI1", "media_key": "3_MI1"}}),
            ("POST", "2/media/metadata"): lambda req: (self.alt.append(req["body"]) or (200, {"data": {"associated_metadata": True}})),
            ("GET", "2/users/U1/tweets"): lambda req: (200, {"data": [{"id": t["id"], "text": t["text"]} for t in reversed(self.tweets)][:5]}),
            ("POST", "2/tweets"): self.tweet,
            ("DELETE", "2/tweets/"): lambda req: (self.deleted.append(req["url"].rsplit("/", 1)[1]) or (200, {"data": {"deleted": True}})),
            ("GET", "2/tweets/search/recent"): (200, {"data": [{"id": "R9", "text": "@khan_pk is it in stock?", "author_id": "U9",
                                                                "created_at": "2026-10-05T09:00:00Z"}], "includes": {"users": [{"id": "U9", "username": "sara"}]}}),
            ("GET", "2/tweets/"): (200, {"data": {"id": "T1", "public_metrics": {"like_count": 40, "reply_count": 4, "retweet_count": 6, "quote_count": 1,
                                                                                 "bookmark_count": 3, "impression_count": 2100},
                                                  "non_public_metrics": {"impression_count": 2150, "url_link_clicks": 37}}}),
        })

    def append(self, req):
        body = req["body"] if isinstance(req["body"], (bytes, bytearray)) else b""
        m = re.search(rb'name="segment_index"\r\n\r\n(\d+)', body)
        self.appends.append(int(m.group(1)) if m else -1)
        return 200, {}

    def status(self, req):
        self.status_calls += 1
        st = "in_progress" if self.status_calls == 1 else "succeeded"
        return 200, {"data": {"id": "MV1", "processing_info": {"state": st, "check_after_secs": 1, "progress_percent": 50 if st == "in_progress" else 100}}}

    def tweet(self, req):
        tid = f"T{len(self.tweets) + 1}"
        self.tweets.append({"id": tid, "text": req["body"]["text"], "body": req["body"]})
        if self.lose_first_answer:
            self.lose_first_answer = False
            raise OSError("the answer was lost")  # posted on X's side, but the reply never arrived
        return 201, {"data": {"id": tid, "text": req["body"]["text"]}}


class MetaFake:
    """Facebook Page PAGE1 (app APP1), Instagram IG1, Threads TH1 - one stateful fake for Graph and Threads."""

    def __init__(self):
        self.feed, self.photos, self.ig_containers, self.ig_fetched, self.th_containers, self.th_fetched = [], [], {}, {}, {}, {}
        self.deleted, self.rupload, self.video_status_calls, self.ig_status_calls = [], [], {}, {}
        self.published = []

    def transport(self):
        g = "graph.facebook.com/v26.0/"
        t = "graph.threads.net/v1.0/"
        return FakeTransport({
            # ---------------- Threads
            ("GET", t + "me"): (200, {"id": "TH1", "username": "khan_pk", "name": "Khan Electronics"}),
            ("GET", t + "TH1/threads_publishing_limit"): (200, {"data": [{"quota_usage": 10, "config": {"quota_total": 250}}]}),
            ("POST", t + "TH1/threads_publish"): self.th_publish,
            ("POST", t + "TH1/threads"): self.th_container,
            ("GET", t + "THC"): self.th_status,
            ("GET", t + "THM"): (200, {"permalink": "https://www.threads.net/@khan_pk/post/ABC", "id": "THM1"}),
            # ---------------- Instagram
            ("GET", g + "IG1/content_publishing_limit"): (200, {"data": [{"quota_usage": 3, "config": {"quota_total": 50, "quota_duration": 86400}}]}),
            ("POST", g + "IG1/media_publish"): self.ig_publish,
            ("POST", g + "IG1/media"): self.ig_container,
            ("POST", "rupload.facebook.com/ig-api-upload/"): self.ig_rupload,
            ("GET", g + "IGC"): self.ig_status,
            ("GET", g + "IGM1/insights"): (200, {"data": [{"name": n, "values": [{"value": v}]} for n, v in
                                                         (("views", 8200), ("reach", 5100), ("likes", 640), ("comments", 41), ("shares", 77), ("saved", 120))]}),
            ("GET", g + "IGM1/comments"): (200, {"data": [{"id": "IC1", "text": "Do you deliver to Multan?", "username": "bilal", "timestamp": "2026-10-05T08:00:00+0000"}]}),
            ("POST", g + "IC1/replies"): (200, {"id": "IC1R"}),
            ("GET", g + "IGM1"): (200, {"permalink": "https://www.instagram.com/reel/IGM1/", "media_type": "VIDEO"}),
            ("DELETE", g + "IGM1"): lambda req: (self.deleted.append("IGM1") or (200, {"success": True, "deleted_id": "IGM1"})),
            ("GET", g + "IG1?"): (200, {"username": "khan_pk", "followers_count": 5400}),
            # ---------------- Facebook Page
            ("GET", g + "PAGE1?"): (200, {"name": "Khan Electronics", "followers_count": 12000, "link": "https://facebook.com/khan"}),
            ("POST", g + "PAGE1/feed"): self.fb_feed,
            ("POST", g + "PAGE1/photos"): self.fb_photo,
            ("POST", g + "PAGE1/photo_stories"): lambda req: (200, {"success": True, "post_id": "PAGE1_ST1"}),
            ("POST", g + "APP1/uploads"): (200, {"id": "upload:SID1"}),
            ("POST", g + "upload:SID1"): self.fb_upload,
            ("POST", g + "PAGE1/videos"): lambda req: (self.feed.append(("video", req["body"])) or (200, {"id": "VID9"})),
            ("POST", g + "PAGE1/video_reels"): self.fb_reel,
            ("POST", g + "PAGE1/video_stories"): self.fb_reel,
            ("POST", "rupload.facebook.com/video-upload/"): self.fb_rupload,
            ("GET", g + "TMP1?fields=images"): (200, {"images": [{"source": "https://scontent.xx.fbcdn.net/tmp1.jpg", "width": 1080}]}),
            ("GET", "fields=status"): self.fb_video_status,
            ("GET", "fields=permalink_url,is_published"): (200, {"is_published": True, "permalink_url": "/khan/posts/1"}),
            ("GET", "fields=permalink_url"): lambda req: (200, {"permalink_url": "/khan/posts/" + req["url"].split(g)[1].split("?")[0]}),
            ("GET", "/comments?"): (200, {"data": [{"id": "FC1", "message": "Nice prices!", "created_time": "2026-10-05T07:00:00+0000", "from": {"name": "Sana"}}]}),
            ("POST", g + "FC1/comments"): (200, {"id": "FC1R"}),
            ("POST", g + "FC2"): (200, {"success": True}),
            ("GET", "shares%2Creactions"): (200, {"shares": {"count": 9}, "reactions": {"summary": {"total_count": 210}}, "comments": {"summary": {"total_count": 17}}}),
            ("GET", "/insights?metric=post_media_view"): (200, {"data": [{"name": "post_media_view", "values": [{"value": 4300}]},
                                                                         {"name": "post_total_media_view_unique", "values": [{"value": 3100}]}]}),
            ("DELETE", g): lambda req: (self.deleted.append(req["url"].split(g)[1]) or (200, {"success": True})),
        })

    # ---------------- Facebook
    def fb_feed(self, req):
        self.feed.append(("feed", req["body"]))
        return 200, {"id": f"PAGE1_{len(self.feed)}"}

    def fb_photo(self, req):
        body = req["body"] if isinstance(req["body"], (bytes, bytearray)) else b""
        fields = dict(re.findall(rb'name="(\w+)"\r\n\r\n([^\r]*)', body))
        self.photos.append({k.decode(): v.decode() for k, v in fields.items()})
        n = len(self.photos)
        if fields.get(b"temporary") == b"true" and fields.get(b"published") == b"false" and b"message" not in fields:
            return 200, {"id": "TMP1"}
        if fields.get(b"published") == b"false":
            return 200, {"id": f"PH{n}"}
        return 200, {"id": f"PH{n}", "post_id": f"PAGE1_PH{n}"}

    def fb_upload(self, req):
        assert req["headers"].get("Authorization", "").startswith("OAuth ") and req["headers"].get("file_offset") == "0"
        self.uploaded = len(req["body"])
        return 200, {"h": "HANDLE1"}

    def fb_reel(self, req):
        b = req["body"]
        if b.get("upload_phase") == "start":
            return 200, {"video_id": "R1", "upload_url": "https://rupload.facebook.com/video-upload/v26.0/R1"}
        self.feed.append(("reel_finish", b))
        return 200, {"success": True, "post_id": "PAGE1_R1"}

    def fb_rupload(self, req):
        h = req["headers"]
        assert h.get("Authorization", "").startswith("OAuth ") and h.get("offset") == "0" and int(h.get("file_size")) == len(req["body"])
        self.rupload.append(("fb", len(req["body"])))
        return 200, {"success": True}

    def fb_video_status(self, req):
        vid = req["url"].split("v26.0/")[1].split("?")[0]
        n = self.video_status_calls[vid] = self.video_status_calls.get(vid, 0) + 1
        if n == 1:
            return 200, {"status": {"video_status": "processing", "uploading_phase": {"status": "complete"}, "processing_phase": {"status": "in_progress"}}}
        return 200, {"status": {"video_status": "ready", "uploading_phase": {"status": "complete"}, "processing_phase": {"status": "complete"}}}

    # ---------------- Instagram
    def ig_container(self, req):
        b = req["body"]
        cid = f"IGC{len(self.ig_containers) + 1}"
        if b.get("image_url") or b.get("video_url"):  # Instagram fetches the media from the address, as the real one does
            url = b.get("image_url") or b.get("video_url")
            if "fbcdn.net" not in url:
                with urllib.request.urlopen(url, timeout=20) as r:
                    self.ig_fetched[cid] = r.read()
        self.ig_containers[cid] = b
        out = {"id": cid}
        if b.get("upload_type") == "resumable":
            out["uri"] = f"https://rupload.facebook.com/ig-api-upload/v26.0/{cid}"
        return 200, out

    def ig_rupload(self, req):
        h = req["headers"]
        assert h.get("Authorization", "").startswith("OAuth ") and h.get("offset") == "0"
        self.rupload.append(("ig", len(req["body"])))
        return 200, {"success": True}

    def ig_status(self, req):
        cid = req["url"].split("v26.0/")[1].split("?")[0]
        n = self.ig_status_calls[cid] = self.ig_status_calls.get(cid, 0) + 1
        return 200, {"status_code": "IN_PROGRESS" if n == 1 else "FINISHED", "id": cid}

    def ig_publish(self, req):
        self.published.append(("ig", req["body"]["creation_id"]))
        return 200, {"id": "IGM1"}

    # ---------------- Threads
    def th_container(self, req):
        b = req["body"]
        cid = f"THC{len(self.th_containers) + 1}"
        url = b.get("image_url") or b.get("video_url")
        if url:
            with urllib.request.urlopen(url, timeout=20) as r:
                self.th_fetched[cid] = r.read()
        self.th_containers[cid] = b
        return 200, {"id": cid}

    def th_status(self, req):
        return 200, {"status": "FINISHED"}

    def th_publish(self, req):
        self.published.append(("threads", req["body"]["creation_id"]))
        return 200, {"id": "THM1"}
