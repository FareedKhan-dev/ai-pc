"""Where a file is going and what it must be there: the containers and the codecs each one takes, the targets (WhatsApp,
email, Discord, Telegram, Instagram, TikTok, YouTube, a TV, an iPhone, PowerPoint, a website, editing, keeping) with
their limits, the quality knob of each encoder, and the reasons a file would not play or send well on a target.

Limits checked on 2026-10-04: WhatsApp (faq.whatsapp.com): videos up to 100 MB at 720p (64 MB / 480p on slow
connections), documents up to 2 GB; Discord free accounts 10 MB; Telegram bots 50 MB; Gmail 25 MB per email, Outlook
20-35 MB depending on the version.
"""
from ai_pc.convert.media import CODEC_WORDS, human

CONTAINERS = {
    "mp4": {"video": {"h264", "hevc", "av1", "vp9", "mpeg4"}, "audio": {"aac", "mp3", "opus", "ac3", "eac3", "alac", "flac"}, "default": ("h264", "aac"), "mux": "mp4"},
    "mov": {"video": {"h264", "hevc", "prores", "mjpeg"}, "audio": {"aac", "pcm_s16le", "pcm_s24le", "alac", "mp3"}, "default": ("h264", "aac"), "mux": "mov"},
    "mkv": {"video": {"h264", "hevc", "av1", "vp9", "vp8", "mpeg4", "mpeg2video", "prores", "ffv1", "mjpeg", "theora"},
            "audio": {"aac", "mp3", "opus", "vorbis", "ac3", "eac3", "dts", "flac", "truehd", "pcm_s16le", "pcm_s24le", "alac", "mp2"}, "default": ("h264", "aac"),
            "mux": "matroska"},
    "webm": {"video": {"vp9", "av1", "vp8"}, "audio": {"opus", "vorbis"}, "default": ("vp9", "opus"), "mux": "webm"},
    "avi": {"video": {"mpeg4", "h264", "mjpeg"}, "audio": {"mp3", "ac3", "pcm_s16le"}, "default": ("mpeg4", "mp3"), "mux": "avi"},
    "gif": {"video": {"gif"}, "audio": set(), "default": ("gif", None), "mux": "gif"},
    "webp": {"video": {"webp"}, "audio": set(), "default": ("webp", None), "mux": "webp"},
    "mp3": {"video": set(), "audio": {"mp3"}, "default": (None, "mp3"), "mux": "mp3"},
    "m4a": {"video": set(), "audio": {"aac", "alac"}, "default": (None, "aac"), "mux": "ipod"},
    "aac": {"video": set(), "audio": {"aac"}, "default": (None, "aac"), "mux": "adts"},
    "wav": {"video": set(), "audio": {"pcm_s16le", "pcm_s24le", "pcm_f32le"}, "default": (None, "pcm_s16le"), "mux": "wav"},
    "flac": {"video": set(), "audio": {"flac"}, "default": (None, "flac"), "mux": "flac"},
    "ogg": {"video": set(), "audio": {"opus", "vorbis"}, "default": (None, "opus"), "mux": "ogg"},
    "opus": {"video": set(), "audio": {"opus"}, "default": (None, "opus"), "mux": "opus"},
}
AUDIO_ONLY = {k for k, c in CONTAINERS.items() if not c["video"]}
VIDEO_CONTAINERS = {"mp4", "mov", "mkv", "webm", "avi"}

# encoders per picture codec: (hardware on this PC's Intel GPU, software)
# (VP9 on the Intel GPU ignores its quality knob - 0.55 Mbps whatever it is set to - so VP9 is always made by software)
ENCODERS = {"h264": ("h264_qsv", "libx264"), "av1": ("av1_qsv", "libsvtav1"), "vp9": (None, "libvpx-vp9"), "hevc": (None, "libx265"),
            "prores": (None, "prores_ks"), "mpeg4": (None, "mpeg4"), "gif": (None, "gif"), "webp": (None, "libwebp_anim")}
# picture megapixels encoded per second on this PC (measured 2026-10-04, 1080p60 into each encoder)
MPX_PER_S = {"libx264": 170, "h264_qsv": 420, "libsvtav1": 180, "av1_qsv": 470, "libvpx-vp9": 45, "libx265": 60, "prores_ks": 300,
             "mpeg4": 400, "gif": 60, "libwebp_anim": 30}
# the quality knob per encoder for each level (lower = better), calibrated on 2026-10-04 against VMAF on 1080p nature
# footage and a screen recording: best ~96, high ~95, good ~93, small ~89, tiny ~84. On this PC the GPU's H.264 beat
# x264 'medium' at the same size (93.0 at 1.54 Mbps against 89.9 at 1.47 Mbps) and is 2-3x faster, so it is the default.
# "same" searches the knob by measuring instead.
QUALITY = {
    "libx264": {"best": 17, "high": 20, "good": 22, "small": 26, "tiny": 30, "range": (14, 34)},
    "h264_qsv": {"best": 18, "high": 21, "good": 23, "small": 27, "tiny": 31, "range": (14, 38)},
    "libx265": {"best": 18, "high": 20, "good": 22, "small": 26, "tiny": 30, "range": (14, 36)},
    "libsvtav1": {"best": 20, "high": 24, "good": 28, "small": 36, "tiny": 44, "range": (16, 55)},
    "av1_qsv": {"best": 17, "high": 20, "good": 23, "small": 27, "tiny": 31, "range": (12, 40)},
    "libvpx-vp9": {"best": 20, "high": 26, "good": 31, "small": 37, "tiny": 43, "range": (16, 50)},
    "mpeg4": {"best": 2, "high": 3, "good": 4, "small": 6, "tiny": 9, "range": (2, 12)},
}
# bits per pixel per frame a codec needs to look fine (used to pick the size when a file must fit a limit)
BPP = {"h264": 0.055, "hevc": 0.035, "av1": 0.03, "vp9": 0.035, "mpeg4": 0.08}
LEVELS = ("best", "high", "good", "small", "tiny")

PLAYS = {"containers_ok": {"mp4", "mov", "m4v"}, "vcodecs_ok": {"h264"}, "acodecs_ok": {"aac", "mp3"}, "bits8": True}
PRESETS = {
    "everywhere": dict(label="every phone, PC and TV", container="mp4", vcodec="h264", acodec="aac", max_long=1920, max_fps=60, faststart=True,
                       bake_rotation=True, **PLAYS),
    "whatsapp": dict(label="WhatsApp", container="mp4", vcodec="h264", acodec="aac", max_long=1280, max_fps=30, max_mb=64, quality="high", faststart=True,
                     **PLAYS,
                     note="WhatsApp sends videos up to 100 MB at 720p (64 MB on slow connections) and squeezes bigger ones; sent as a document "
                          "a file keeps its full quality (up to 2 GB)."),
    "email": dict(label="email", container="mp4", vcodec="h264", acodec="aac", max_mb=18, faststart=True, **PLAYS,
                  note="Gmail takes 25 MB per email and Outlook 20-25 MB, so it is kept under 18 MB."),
    "discord": dict(label="Discord", container="mp4", vcodec="h264", acodec="aac", max_mb=10, faststart=True, **PLAYS,
                    note="Discord's free accounts take files up to 10 MB."),
    "telegram": dict(label="Telegram", container="mp4", vcodec="h264", acodec="aac", max_mb=50, faststart=True, **PLAYS,
                     note="Telegram bots (and this PC's Telegram connection) send files up to 50 MB; the Telegram app itself takes up to 2 GB."),
    "slack": dict(label="Slack", container="mp4", vcodec="h264", acodec="aac", faststart=True, max_long=1920, **PLAYS),
    "instagram": dict(label="Instagram Reels", container="mp4", vcodec="h264", acodec="aac", aspect="9:16", size=(1080, 1920), max_fps=60, quality="good",
                      faststart=True, **PLAYS),
    "instagram_post": dict(label="an Instagram feed post", container="mp4", vcodec="h264", acodec="aac", aspect="4:5", size=(1080, 1350), max_fps=60,
                           quality="good", faststart=True, **PLAYS),
    "instagram_story": dict(label="an Instagram story", container="mp4", vcodec="h264", acodec="aac", aspect="9:16", size=(1080, 1920), max_fps=60,
                            quality="good", faststart=True, **PLAYS),
    "tiktok": dict(label="TikTok", container="mp4", vcodec="h264", acodec="aac", aspect="9:16", size=(1080, 1920), max_fps=60, quality="good",
                   faststart=True, **PLAYS),
    "youtube_shorts": dict(label="YouTube Shorts", container="mp4", vcodec="h264", acodec="aac", aspect="9:16", size=(1080, 1920), max_fps=60,
                           quality="good", faststart=True, **PLAYS),
    "youtube": dict(label="YouTube", container="mp4", vcodec="h264", acodec="aac", quality="high", max_fps=60, faststart=True, **PLAYS),
    "facebook": dict(label="Facebook", container="mp4", vcodec="h264", acodec="aac", quality="high", max_long=1920, max_fps=60, faststart=True, **PLAYS),
    "linkedin": dict(label="LinkedIn", container="mp4", vcodec="h264", acodec="aac", quality="high", max_long=1920, max_fps=60, faststart=True, **PLAYS),
    "x": dict(label="X (Twitter)", container="mp4", vcodec="h264", acodec="aac", quality="high", max_long=1920, max_fps=60, faststart=True, **PLAYS),
    "web": dict(label="a website", container="mp4", vcodec="h264", acodec="aac", max_long=1920, max_fps=60, faststart=True, **PLAYS),
    "iphone": dict(label="an iPhone", container="mp4", vcodec="h264", acodec="aac", faststart=True, containers_ok={"mp4", "mov", "m4v"},
                   vcodecs_ok={"h264", "hevc"}, acodecs_ok={"aac", "mp3", "alac"}, bits8=False),
    "android": dict(label="Android phones", container="mp4", vcodec="h264", acodec="aac", faststart=True, **PLAYS),
    "tv": dict(label="a TV or USB player", container="mp4", vcodec="h264", acodec="aac", max_long=1920, max_fps=60, bake_rotation=True,
               containers_ok={"mp4", "mkv", "mov"}, vcodecs_ok={"h264"}, acodecs_ok={"aac", "mp3", "ac3"}, bits8=True),
    "powerpoint": dict(label="PowerPoint", container="mp4", vcodec="h264", acodec="aac", max_long=1920, max_fps=60, faststart=True, bake_rotation=True, **PLAYS),
    "editing": dict(label="editing (Premiere, DaVinci, CapCut)", container="mov", vcodec="prores", acodec="pcm_s16le", cfr=True, quality="best",
                    bake_rotation=True, containers_ok={"mov", "mp4", "mkv"}, vcodecs_ok={"prores", "h264", "dnxhd"}, acodecs_ok={"aac", "pcm_s16le", "pcm_s24le"},
                    bits8=False, note="ProRes plays smoothly while editing but is big (about 1 GB per 10 minutes of 1080p)."),
    "archive": dict(label="keeping (smallest at the same look)", container="mp4", vcodec="av1", acodec="aac", quality="same",
                    containers_ok={"mp4", "mkv", "webm"}, vcodecs_ok={"av1", "hevc", "vp9"}, acodecs_ok={"aac", "opus"}, bits8=False,
                    note="AV1 plays on Windows 10/11, recent phones and browsers; older TVs and phones may not play it."),
}
SAME_VMAF = 94.0  # 'the same look': VMAF this high is hard to tell apart from the original at normal viewing


def ratio(aspect):
    a, b = (float(x) for x in str(aspect).split(":"))
    return a / b


def shape(w, h):
    r = w / h if h else 1
    return "square" if abs(r - 1) < 0.03 else "vertical" if r < 1 else "landscape"


def issues(p, key):
    """Why the file may not play or send well on a target: [{"why", "level": "fix" | "minor"}] (empty = fine as it is)."""
    t = PRESETS[key]
    v, a = p.get("video"), p.get("audio")
    out = []

    def add(why, level="fix"):
        out.append({"why": why, "level": level})
    if p["container"] not in t.get("containers_ok", {t["container"]}):
        add(f"it is {p['container'].upper()}; {t['label']} wants {t['container'].upper()}")
    if v and not v.get("image"):
        if v["codec"] not in t.get("vcodecs_ok", {t["vcodec"]}):
            name = CODEC_WORDS.get(v["codec"], v["codec"])
            why = {"hevc": "which many phones, PCs and TVs still can't play", "av1": "which older phones, PCs and TVs can't play",
                   "vp9": "which iPhones and many TVs can't play", "prores": "a very big editing format most phones can't play",
                   "h264": "which is fine for playing but slow to edit (ProRes plays smoothly)"}.get(v["codec"], "an old format many phones can't play")
            if key == "editing" and v["codec"] in ("hevc", "av1", "vp9"):
                why = "which editors play slowly or not at all (ProRes plays smoothly)"
            add(f"its picture is {name}, {why}")
        if t.get("bits8") and (v["bits"] > 8 or v["chroma"] != "420"):
            add(f"its {v['bits']}-bit {v['chroma']} colour does not play on many phones and TVs")
        if v["hdr"] and t.get("bits8"):
            add("its HDR colours look washed out on most phones and players")
        if t.get("max_long") and max(v["w"], v["h"]) > t["max_long"]:
            add(f"{v['w']}x{v['h']} is more than {t['label']} shows ({min(t['max_long'], 1920) * 9 // 16}p); it would be squeezed", "minor"
                if key in ("everywhere", "tv", "powerpoint", "web") else "fix")
        if t.get("max_fps") and v["fps"] > t["max_fps"] + 0.5:
            add(f"{v['fps']:g} fps is more than {t['label']} keeps ({t['max_fps']})", "minor")
        if t.get("aspect") and abs(v["w"] / v["h"] - ratio(t["aspect"])) > 0.03:
            add(f"it is {shape(v['w'], v['h'])} ({v['w']}x{v['h']}); {t['label']} fills the screen with {t['aspect']}")
        if v["w"] % 2 or v["h"] % 2:
            add("its width or height is an odd number, which many players refuse")
        if t.get("cfr") and v["vfr"]:
            add("its frame rate varies (as phone recordings do), so editors can drift out of sync")
        if v["interlaced"]:
            add("it is interlaced (comb lines on movement)")
        if t.get("bake_rotation") and v["rotation"]:
            add("it relies on a turn flag that many TVs and programs ignore (it would show sideways)")
    if a and a["codec"] not in t.get("acodecs_ok", {t["acodec"]}):
        add(f"its sound is {CODEC_WORDS.get(a['codec'], a['codec'])}, which many phones and players can't play")
    if t.get("max_mb") and p["size"] > t["max_mb"] * 1e6:
        add(f"{human(p['size'])} is over the {t['max_mb']} MB {t['label']} takes")
    if key == "web" and p.get("faststart") is False:  # only a page streaming it waits for the whole file
        add("it cannot start playing on a page until it has fully downloaded (its index is at the end)", "minor")
    return out
