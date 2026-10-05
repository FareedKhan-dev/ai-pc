"""What each platform takes through its API (checked 2026-10-04 against the official API docs; where docs disagree the
safer number is used, and where they say nothing that is noted). Media rules drive prepare.py; text rules drive text.py.

  media(platform, fmt) -> {"label", "count": (min, max), "kinds", "image": {...}, "video": {...}, "cover": {...}}
  text(platform, fmt)  -> {"label", "chars", "how", "needs_title", "title_chars", "hashtags", "mentions", "links", "thread", ...}
Sources: developers.facebook.com (Instagram content publishing, ig-user/media, Reels publishing, Page photos, Page stories,
Threads posts), developers.google.com/youtube (videos, videos.insert, thumbnails.set), developers.tiktok.com (content
posting API, media transfer guide), learn.microsoft.com/linkedin (posts, images, videos APIs), docs.x.com (media, posts).
"""

NAMES = ["facebook", "instagram", "threads", "youtube", "tiktok", "linkedin", "x"]
LABEL = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "threads": "Threads",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "linkedin": "LinkedIn",
    "x": "X",
}
FORMAT_WORDS = {
    "post": "post",
    "photo": "photo",
    "image": "post",
    "carousel": "carousel",
    "video": "video",
    "reel": "reel",
    "story": "story",
    "short": "Short",
    "text": "post",
}

ANY = (0.01, 100.0)

# ---------------------------------------------------------------- pictures
IG_IMAGE = {"formats": ("jpeg",), "max_mb": 8, "aspect": (0.8, 1.91), "min_w": 320, "max_w": 1440, "prefer": ("1:1", "4:5", "1.91:1")}
IG_CAROUSEL_IMAGE = dict(IG_IMAGE, aspect=(0.8, 0.8), prefer=("4:5",))  # every slide shown in the first one's shape: all made 4:5
STORY_IMAGE = {"formats": ("jpeg",), "max_mb": 8, "aspect": (0.5625, 0.5625), "max_w": 1080, "prefer": ("9:16",), "fill": "fit"}
FB_IMAGE = {"formats": ("jpeg", "png"), "max_mb": 10, "aspect": (0.33, 3.0), "max_w": 2048, "prefer": ("1:1", "4:5", "16:9", "9:16")}
THREADS_IMAGE = {"formats": ("jpeg", "png"), "max_mb": 8, "aspect": (0.1, 10.0), "min_w": 320, "max_w": 1440}
LINKEDIN_IMAGE = {
    "formats": ("jpeg", "png"),
    "max_mb": 5,
    "aspect": (0.8, 3.0),
    "min_w": 552,
    "max_w": 2048,
    "prefer": ("1:1", "4:5", "1.91:1", "16:9"),
}
X_IMAGE = {"formats": ("jpeg", "png"), "max_mb": 5, "aspect": (0.33, 3.0), "max_w": 2048, "prefer": ("16:9", "1:1", "4:5")}
YT_COVER = {"formats": ("jpeg",), "max_mb": 2, "aspect": (1.7778, 1.7778), "min_w": 640, "max_w": 1920, "prefer": ("16:9",)}

# ---------------------------------------------------------------- videos (preset = the converter's preset of that name)
IG_REEL = {"preset": "instagram", "min_s": 3, "max_s": 900, "max_mb": 300, "aspect": ANY, "fps": (23, 60), "max_long": 1920}
IG_STORY = {"preset": "instagram_story", "min_s": 3, "max_s": 60, "max_mb": 100, "aspect": (0.1, 10.0), "fps": (23, 60)}
IG_CAROUSEL_VIDEO = {"preset": "instagram_post", "min_s": 3, "max_s": 60, "max_mb": 100, "aspect": (0.8, 0.8), "fps": (23, 60)}
FB_VIDEO = {"preset": "facebook", "min_s": 1, "max_s": 241 * 60, "max_mb": 4000, "aspect": ANY, "fps": (23, 60)}
FB_REEL = {"preset": "instagram", "min_s": 3, "max_s": 90, "max_mb": 1000, "aspect": (0.5625, 1.7778), "fps": (24, 60)}
FB_STORY = {"preset": "instagram_story", "min_s": 3, "max_s": 60, "max_mb": 1000, "aspect": (0.5625, 1.7778), "fps": (24, 60)}
THREADS_VIDEO = {"preset": "facebook", "min_s": 0.5, "max_s": 300, "max_mb": 1000, "aspect": (0.01, 10.0), "fps": (23, 60)}
YT_VIDEO = {"preset": "youtube", "min_s": 1, "max_s": 12 * 3600, "max_mb": 256000, "aspect": ANY, "fps": (1, 60)}
YT_SHORT = {"preset": "youtube_shorts", "min_s": 1, "max_s": 180, "max_mb": 256000, "aspect": (0.5625, 1.0), "fps": (1, 60)}
TIKTOK_VIDEO = {"preset": "tiktok", "min_s": 3, "max_s": 600, "max_mb": 4000, "aspect": ANY, "fps": (23, 60)}
LINKEDIN_VIDEO = {"preset": "linkedin", "min_s": 3, "max_s": 900, "max_mb": 500, "aspect": (0.4167, 2.4), "fps": (10, 30)}
X_VIDEO = {"preset": "x", "min_s": 0.5, "max_s": 1200, "max_mb": 1024, "aspect": (0.3333, 3.0), "fps": (1, 60), "max_long": 1280}

MEDIA = {
    ("facebook", "post"): {"count": (0, 0)},
    ("facebook", "photo"): {"count": (1, 10), "kinds": ("image",), "image": FB_IMAGE},
    ("facebook", "carousel"): {"count": (2, 10), "kinds": ("image",), "image": FB_IMAGE},
    ("facebook", "video"): {"count": (1, 1), "kinds": ("video",), "video": FB_VIDEO, "cover": dict(FB_IMAGE, max_mb=10)},
    ("facebook", "reel"): {"count": (1, 1), "kinds": ("video",), "video": FB_REEL},
    ("facebook", "story"): {"count": (1, 1), "image": dict(STORY_IMAGE, max_mb=10), "video": FB_STORY},
    ("instagram", "photo"): {"count": (1, 1), "kinds": ("image",), "image": IG_IMAGE},
    ("instagram", "carousel"): {"count": (2, 10), "image": IG_CAROUSEL_IMAGE, "video": IG_CAROUSEL_VIDEO},
    ("instagram", "reel"): {"count": (1, 1), "kinds": ("video",), "video": IG_REEL, "cover": dict(STORY_IMAGE, max_mb=8)},
    ("instagram", "story"): {"count": (1, 1), "image": STORY_IMAGE, "video": IG_STORY},
    ("threads", "text"): {"count": (0, 0)},
    ("threads", "image"): {"count": (1, 1), "kinds": ("image",), "image": THREADS_IMAGE},
    ("threads", "video"): {"count": (1, 1), "kinds": ("video",), "video": THREADS_VIDEO},
    ("threads", "carousel"): {"count": (2, 20), "image": THREADS_IMAGE, "video": THREADS_VIDEO},
    ("youtube", "video"): {"count": (1, 1), "kinds": ("video",), "video": YT_VIDEO, "cover": YT_COVER},
    ("youtube", "short"): {"count": (1, 1), "kinds": ("video",), "video": YT_SHORT},
    ("tiktok", "video"): {"count": (1, 1), "kinds": ("video",), "video": TIKTOK_VIDEO},
    ("tiktok", "photo"): {"count": (1, 35), "video": TIKTOK_VIDEO, "pictures_as_video": True, "max_slides": 35},
    ("linkedin", "post"): {"count": (0, 0)},
    ("linkedin", "image"): {"count": (1, 1), "kinds": ("image",), "image": LINKEDIN_IMAGE},
    ("linkedin", "carousel"): {"count": (2, 20), "kinds": ("image",), "image": LINKEDIN_IMAGE},
    ("linkedin", "video"): {"count": (1, 1), "kinds": ("video",), "video": LINKEDIN_VIDEO},
    ("x", "post"): {"count": (0, 4), "image": X_IMAGE, "video": X_VIDEO, "one_video": True},
}

# ---------------------------------------------------------------- words
TEXT = {
    "facebook": {"chars": 60000, "how": "chars", "links": "live"},
    "instagram": {"chars": 2200, "how": "utf16", "hashtags": 30, "mentions": 20, "links": "dead"},
    "threads": {"chars": 500, "how": "threads", "hashtags": 1, "max_links": 5, "links": "live"},
    "youtube": {
        "chars": 5000,
        "how": "bytes",
        "needs_title": True,
        "title_chars": 100,
        "tags_chars": 500,
        "hashtags": 60,
        "links": "live",
        "link_in_text": True,
    },
    "tiktok": {"chars": 2200, "how": "utf16", "links": "dead"},
    "linkedin": {"chars": 3000, "how": "chars", "escape": "linkedin", "links": "live"},
    "x": {"chars": 280, "how": "x", "thread": True, "links": "live"},
}
TEXT_BY_FORMAT = {
    ("instagram", "story"): {"chars": 0, "how": "chars", "note": "Instagram stories take no caption through the API"},
    ("facebook", "story"): {"chars": 0, "how": "chars", "note": "Facebook stories take no text through the API"},
    ("youtube", "short"): {"links": "dead"},
}

# ---------------------------------------------------------------- limits worth knowing before posting
DAILY = {
    "instagram": "50 posts in 24 hours (the API's own publishing limit)",
    "facebook": "30 reels a day per Page",
    "threads": "250 posts in 24 hours",
    "youtube": "100 uploads a day (the project's upload quota) and 10,000 other units",
    "tiktok": "about 15 posts a day per account; 5 drafts waiting at most",
    "linkedin": "about 150 posts a day per member",
    "x": "100 posts in 15 minutes; each post is paid ($0.015, or $0.20 when it has a link)",
}


def media(platform, fmt):
    m = MEDIA.get((platform, fmt))
    if m is None:
        raise KeyError(f"{LABEL.get(platform, platform)} has no '{fmt}' post through its API")
    return dict(m, label=f"{LABEL[platform]} {FORMAT_WORDS.get(fmt, fmt)}")


def text(platform, fmt):
    t = dict(TEXT[platform])
    t.update(TEXT_BY_FORMAT.get((platform, fmt), {}))
    t["label"] = LABEL[platform]
    return t


def formats(platform):
    return [f for (p, f) in MEDIA if p == platform]
