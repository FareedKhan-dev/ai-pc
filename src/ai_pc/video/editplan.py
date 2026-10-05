"""Edit plans (schema v2): what the planner writes, and how a plan is checked and resolved before anything is built.

A plan is JSON: a canvas, the main-track clips (played back to back), overlay layers, and a flat list of edits. Each
edit has an id and an "expect": what a viewer should see or hear if it worked. The verifier checks exactly that, at
exactly that moment of the export.

resolve() turns a plan into a resolved plan, which is the only thing the builder (jybuild.py) ever sees:
  - every catalogue name is checked against the knowledge base (free items only). A wrong, invented or VIP name is
    replaced by the closest free item, or dropped with a note;
  - every time is made absolute and clamped to the media and the timeline ("on": <clip id> makes times relative);
  - macros are expanded: speed ramps (split clips), reverse and freeze frames (derived files made with ffmpeg), camera
    shake and zoom punches (keyframes on top of the clip's framing), beat snapping, music ducking under speech;
  - reframing to the canvas is computed from the analysed face positions (the subject stays in view);
  - character effects are checked against where faces actually are, and text is kept inside the platform's safe zone;
  - every problem and every fix is written to notes.
"""

import difflib
import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.video import kb

MEDIA = ROOT / "media"
DERIVED = MEDIA / "derived"
NO_WINDOW = 0x08000000

ASPECTS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "3:4": (1080, 1440),
    "4:3": (1440, 1080),
    "21:9": (2520, 1080),
}
# where the app's own buttons and captions cover the picture (fractions of the frame), and other platform facts
PLATFORMS = {
    "instagram_reels": {"aspect": "9:16", "max_s": 90, "safe": {"top": 0.13, "bottom": 0.22, "left": 0.05, "right": 0.12}},
    "tiktok": {"aspect": "9:16", "max_s": 180, "safe": {"top": 0.10, "bottom": 0.20, "left": 0.05, "right": 0.14}},
    "youtube_shorts": {"aspect": "9:16", "max_s": 60, "safe": {"top": 0.10, "bottom": 0.18, "left": 0.05, "right": 0.12}},
    "instagram_feed": {"aspect": "4:5", "max_s": 60, "safe": {"top": 0.05, "bottom": 0.08, "left": 0.04, "right": 0.04}},
    "youtube": {"aspect": "16:9", "max_s": None, "safe": {"top": 0.05, "bottom": 0.08, "left": 0.04, "right": 0.04}},
    "square": {"aspect": "1:1", "max_s": None, "safe": {"top": 0.05, "bottom": 0.08, "left": 0.04, "right": 0.04}},
}
DEFAULT_SAFE = {"top": 0.05, "bottom": 0.08, "left": 0.04, "right": 0.04}

EFFECT_CATS = ("scene_effect", "character_effect")
# recipe / camera-move names a planner sometimes writes as an effect name: done as the move itself
MOVE_NAMES = {
    "zoom punch": "zoom",
    "punch zoom": "zoom",
    "punch in": "zoom",
    "zoom hit": "zoom",
    "punch in zoom": "zoom",
    "camera shake": "shake",
    "shake hit": "shake",
    "screen shake": "shake",
    "shake": "shake",
}
CLIP_ANIM = {"intro": "clip_intro", "outro": "clip_outro", "combo": "clip_combo"}
TEXT_ANIM = {"intro": "text_intro", "outro": "text_outro", "loop": "text_loop"}
AUDIO_FX = ("audio_effect", "voice", "speech_to_song")
MASKS = {"linear": "线性", "mirror": "镜面", "circle": "圆形", "rectangle": "矩形", "rect": "矩形", "heart": "爱心", "star": "星形"}
BLENDS = {
    "multiply": "正片叠底",
    "color dodge": "颜色减淡",
    "color burn": "颜色加深",
    "linear burn": "线性加深",
    "soft light": "柔光",
    "hard light": "强光",
    "screen": "滤色",
    "overlay": "叠加",
    "lighten": "变亮",
    "darken": "变暗",
}
# edit types the planner may write -> (our type, animation kind)
TYPE_ALIASES = {
    "character_effect": ("effect", None),
    "scene_effect": ("effect", None),
    "effects": ("effect", None),
    "video_effect": ("effect", None),
    "fx": ("effect", None),
    "filters": ("filter", None),
    "look": ("filter", None),
    "color_grade": ("filter", None),
    "transitions": ("transition", None),
    "clip_intro": ("animation", "intro"),
    "clip_outro": ("animation", "outro"),
    "clip_combo": ("animation", "combo"),
    "text_intro": ("animation", "intro"),
    "text_outro": ("animation", "outro"),
    "text_loop": ("animation", "loop"),
    "anim": ("animation", None),
    "animations": ("animation", None),
    "camera_shake": ("shake", None),
    "zoom_punch": ("zoom", None),
    "punch_in": ("zoom", None),
    "push_in": ("zoom", None),
    "keyframe": ("keyframes", None),
    "title": ("text", None),
    "label": ("text", None),
    "titles": ("text", None),
    "subtitle": ("captions", None),
    "subtitles": ("captions", None),
    "caption": ("captions", None),
    "music": ("audio", None),
    "sound": ("audio", None),
    "voiceover": ("audio", None),
    "sound_effect": ("sfx", None),
    "sound_fx": ("sfx", None),
    "sfx": ("sfx", None),
}
SFX_ALIASES = {
    "boom": "impact",
    "bass_hit": "hit",
    "punch": "hit",
    "kick": "hit",
    "swish": "swoosh",
    "rise": "riser",
    "build_up": "riser",
    "buildup": "riser",
    "uplifter": "riser",
    "drop": "sub_drop",
    "bass_drop": "sub_drop",
    "lightning": "thunder",
    "crack": "thunder",
    "digital": "glitch",
    "stutter": "glitch",
    "woosh": "whoosh",
}
KF_PROPS = {
    "scale": "scale",
    "zoom": "scale",
    "x": "x",
    "position_x": "x",
    "y": "y",
    "position_y": "y",
    "rotation": "rotation",
    "rotate": "rotation",
    "opacity": "alpha",
    "alpha": "alpha",
    "brightness": "brightness",
    "contrast": "contrast",
    "saturation": "saturation",
    "volume": "volume",
}
MAX_SCALE = 5.0  # JianYing caps clip scale at 500%: keyframes above it are flattened (measured: x1.4 zoom on a 506% clip = no zoom)
KF_RANGE = {
    "scale": (0.05, 10),
    "x": (-3, 3),
    "y": (-3, 3),
    "rotation": (-3600, 3600),
    "alpha": (0, 1),
    "brightness": (-1, 1),
    "contrast": (-1, 1),
    "saturation": (-1, 1),
    "volume": (0, 4),
}


def _n(v, lo, hi, d):
    try:
        x = float(v)
        if math.isnan(x):
            return d
    except (TypeError, ValueError):
        return d
    return min(max(x, lo), hi)


def _hex(v, d=None):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?", str(v or "").strip())
    return "#" + m.group(1).upper() if m else d


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(round(int(h[i : i + 2], 16) / 255, 4) for i in (0, 2, 4))


# ------------------------------------------------------------------------------------------------ catalogue lookups
# when an item of these kinds fails here, any working one is a fine stand-in (a font, a grade, a transition, a text
# animation); a failed effect is only replaced by a working effect that does something related, else dropped
ANY_KNOWN_OK = {"font", "filter", "transition", "text_intro", "text_outro", "text_loop", "clip_intro", "clip_outro", "clip_combo"}


class Catalog:
    """Name -> knowledge-base item, free items only. Accepts the original name, the English name, or a description."""

    _shared = None

    def __init__(self, engine="jianying"):
        from ai_pc.video import jyres

        self.index = kb.Index(engine)
        self.engine = engine
        st = jyres.states() if engine == "jianying" else {}
        self.missing = {k for k, v in st.items() if v in ("missing", "login", "invisible")}  # does not work here: never chosen
        self.boost = {k: {"exported": 1.35, "ok": 1.2}[v] for k, v in st.items() if v in ("exported", "ok")}
        if engine == "jianying":  # how often an item was actually SEEN in checked exports: one that rarely reads ranks lower
            for k, r in jyres.load().items():
                seen, unseen = r.get("visible", 0), r.get("not_visible", 0)
                if k in self.boost and seen + unseen >= 4:
                    self.boost[k] = round(self.boost[k] * (0.5 + 0.5 * seen / (seen + unseen)), 3)
        # ranking = works here x not used in the last videos (each video should look like itself, not like the last one)
        self.recent = jyres.recency() if engine == "jianying" else {}
        self.rank = {k: self.boost.get(k, 1.0) * self.recent.get(k, 1.0) for k in set(self.boost) | set(self.recent)}
        self.by_name, self.by_en = {}, {}
        for key, it in self.index.items.items():
            self.by_name.setdefault((it["category"], it["name"].lower()), key)
            en = (self.index.notes.get(key, {}).get("en") or "").lower()
            if en:
                self.by_en.setdefault((it["category"], en), key)

    @classmethod
    def shared(cls):
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def item(self, key):
        return self.index.items[key]

    def card(self, key):
        return self.index.card(key)

    def enum(self, key):
        import pyJianYingDraft as jy

        it = self.index.items[key]
        return getattr(getattr(jy, kb.CATEGORIES[it["category"]][0]), it["name"])

    def resolve(self, categories, wanted, notes, where=""):
        """Key of the free item meant by `wanted` within `categories`, or None (with a note saying why)."""
        if not wanted:
            return None
        w = str(wanted).strip()
        w = re.sub(r"\s*[(\[（].*?[)\]）]\s*$", "", w) or w  # "拽酷红眼 (Cool Red Eyes)" -> "拽酷红眼"
        cats = [categories] if isinstance(categories, str) else list(categories)
        pro_hit = None
        for c in cats:
            for table, k in ((self.by_name, (c, w.lower())), (self.by_en, (c, w.lower())), (self.by_name, (c, w.lower().replace(" ", "_")))):
                key = table.get(k)
                if key:
                    if not self.index.items[key]["pro"] and key not in self.missing:
                        return key
                    pro_hit = pro_hit or key
        if not pro_hit:
            other = [k for k in self.exact(w) if self.index.items[k]["category"] not in cats]
            if other:  # it is a real item of ANOTHER kind (a text animation written as an effect...): never guess a stand-in
                notes.append(
                    f"{where}'{w}' is a {self.index.items[other[0]]['category'].replace('_', ' ')}, not a "
                    f"{'/'.join(c.replace('_', ' ') for c in cats)}; dropped"
                )
                return None
        if pro_hit:
            # a VIP item: its own words are the best query for a free look-alike; its own category first
            n = self.index.notes.get(pro_hit, {})
            f"{n.get('en', '')} {n.get('desc', '')} {' '.join(n.get('tags', []))} {n.get('target', '')}"
            own = self.index.items[pro_hit]["category"]
            why = (
                "is VIP-only"
                if pro_hit not in self.missing
                else {"login": "needs a JianYing account to export", "invisible": "did not render in earlier exports"}.get(
                    jyres_state(pro_hit), "does not download here"
                )
            )
            for cs in ([own], cats):
                key = self.lookalike(pro_hit, cs)
                if key:
                    notes.append(f"{where}'{w}' {why}; using '{self.index.items[key]['name']}' ({self.index.notes.get(key, {}).get('en')})")
                    return key
            if pro_hit in self.missing and own in ANY_KNOWN_OK:  # no working stand-in: do not gamble on another untried one
                notes.append(f"{where}'{w}' {why} and nothing known to work here is like it; dropped")
                return None
        # close spelling of an original name (e.g. a dropped "_II")
        for c in cats:
            names = [
                n
                for (cc, n) in self.by_name
                if cc == c and not self.index.items[self.by_name[(cc, n)]]["pro"] and self.by_name[(cc, n)] not in self.missing
            ]
            best = difflib.get_close_matches(w.lower(), names, n=1, cutoff=0.8)
            if best:
                key = self.by_name[(c, best[0])]
                notes.append(f"{where}'{w}' read as '{self.index.items[key]['name']}'")
                return key
        # meaning: search the descriptions
        hits = self.index.search(w, categories=cats, free_only=True, k=1, exclude=self.missing, boost=self.boost)
        if hits and hits[0].get("score", 0) >= 4:
            key = f"{hits[0]['category']}:{hits[0]['name']}"
            notes.append(f"{where}'{w}' is not in the catalogue; using free '{hits[0]['name']}' ({hits[0].get('en')})")
            return key
        notes.append(f"{where}no free item matches '{w}' in {'/'.join(cats)}; dropped")
        return None

    def _function_words(self, key):
        """What an item DOES (motion, look, target, use), as search tokens."""
        n = self.index.notes.get(key, {})
        use = n.get("use") if isinstance(n.get("use"), list) else [n.get("use") or ""]
        return set(kb._toks(" ".join([str(n.get("motion") or ""), str(n.get("look") or ""), str(n.get("target") or ""), *map(str, use)])))

    def lookalike(self, key, categories):
        """The free, available item most like `key` (a VIP or missing item): what it does counts more than its style."""
        n = self.index.notes.get(key, {})
        query = f"{n.get('en', '')} {n.get('desc', '')} {' '.join(n.get('tags', []))} {n.get('motion', '')} {n.get('target', '')}"
        sib = re.sub(r"_(i{1,3}|iv|v|\d+)$", "", self.index.items[key]["name"].lower())  # 电视故障_I missing -> _II likely too
        hits = self.index.search(query, categories=categories, free_only=True, k=15, exclude=self.missing | {key}, boost=self.boost)
        hits = [h for h in hits if re.sub(r"_(i{1,3}|iv|v|\d+)$", "", h["name"].lower()) != sib] or hits
        if not hits:
            return None
        if key in self.missing:  # replacing an item that failed here: only an item known to work (another untried one
            # fails as often as not, and every failed export costs ~40 s)
            proven = [h for h in hits if self.boost.get(f"{h['category']}:{h['name']}", 1) > 1.0 and h["score"] >= 0.35 * hits[0]["score"]]
            if not proven and self.index.items[key]["category"] in ANY_KNOWN_OK:
                alt = self.known_like(query, categories, exclude={key})
                return alt[0] if alt else None
            hits = proven or hits  # an effect: a related untried one is still worth a try (an unrelated one is not)
        func = self._function_words(key) - {"in", "out", "the", "a"}
        tags = {t for tag in n.get("tags", []) for t in kb._toks(tag)}
        top = hits[0]["score"] or 1
        best, best_s = None, -1
        for h in hits:
            hk = f"{h['category']}:{h['name']}"
            hn = self.index.notes.get(hk, {})
            htags = {t for tag in hn.get("tags", []) for t in kb._toks(tag)}
            known = {1.35: 0.6, 1.2: 0.35}.get(self.boost.get(hk), 0.0)  # a replacement must above all work here
            sc = 1.0 * h["score"] / top + 0.9 * len(func & self._function_words(hk)) + 0.25 * len(tags & htags) + known
            if sc > best_s:
                best, best_s = hk, sc
        return best if hits[0]["score"] >= 4 else None

    def known_like(self, query, categories, exclude=(), related_only=False):
        """Items of `categories` known to work here (exported first, then downloaded), the ones most like `query`
        first; then (unless related_only) the remaining known ones, most proven first."""
        cats = [categories] if isinstance(categories, str) else list(categories)
        known = {
            k: f
            for k, f in self.boost.items()
            if k.split(":", 1)[0] in cats and k not in self.missing and k not in exclude and k in self.index.items and not self.index.items[k]["pro"]
        }
        if not known:
            return []
        hits = self.index.search(query, categories=cats, free_only=True, k=400, exclude=self.missing | set(exclude), boost=self.rank)
        ranked = [f"{h['category']}:{h['name']}" for h in hits if f"{h['category']}:{h['name']}" in known]
        return ranked if related_only else ranked + sorted((k for k in known if k not in ranked), key=lambda k: -self.rank.get(k, known[k]))

    def exact(self, wanted):
        """Every item (any category, free or VIP) whose original or English name is exactly `wanted`."""
        w = re.sub(r"\s*[(\[（].*?[)\]）]\s*$", "", str(wanted or "").strip()).lower()
        return [k for (c, n), k in list(self.by_name.items()) + list(self.by_en.items()) if n == w]

    def param_list(self, key, params, notes, where=""):
        """Effect params {name: 0-100} -> the engine's positional list (None = default)."""
        if not isinstance(params, dict) or not params:
            return None
        names = [p["name"] for p in self.index.items[key].get("params", [])]
        out = [None] * len(names)
        for k, v in params.items():
            kk = str(k) if str(k) in names else next((n for n in names if n.endswith(str(k).lower().replace(" ", "_"))), None)
            if kk is None:
                notes.append(f"{where}unknown parameter '{k}' (has: {', '.join(names) or 'none'})")
                continue
            out[names.index(kk)] = _n(v, 0, 100, None)
        return out if any(v is not None for v in out) else None


# ------------------------------------------------------------------------------------------------ derived media
def jyres_state(key):
    from ai_pc.video import jyres

    return jyres.states().get(key)


def _derived(name):
    DERIVED.mkdir(parents=True, exist_ok=True)
    return DERIVED / name


def reversed_clip(path, start, span):
    """The [start, start+span] part of a video, played backwards (made once with ffmpeg, then reused)."""
    tag = hashlib.sha1(f"{Path(path).name}|{start:.3f}|{span:.3f}".encode()).hexdigest()[:10]
    out = _derived(f"{Path(path).stem[:30]}_rev_{tag}.mp4")
    if not out.exists():
        r = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{span:.3f}",
                "-i",
                str(path),
                "-vf",
                "reverse",
                "-af",
                "areverse",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "16",
                "-c:a",
                "aac",
                str(out),
            ],
            capture_output=True,
            creationflags=NO_WINDOW,
        )
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("reverse failed: " + r.stderr.decode("utf-8", "ignore")[-200:])
    return out


def still_frame(path, t):
    """One frame of a video as a PNG (for freeze frames)."""
    out = _derived(f"{Path(path).stem[:30]}_still_{t:.2f}.png".replace(":", "_"))
    if not out.exists():
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(path), "-frames:v", "1", str(out)],
            capture_output=True,
            creationflags=NO_WINDOW,
        )
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("still frame failed: " + r.stderr.decode("utf-8", "ignore")[-200:])
    return out


# ------------------------------------------------------------------------------------------------ framing
def framing(src_w, src_h, W, H, mode, focus=None, target=(0.5, 0.5), zoom=1.0):
    """Clip settings that place a w x h source on a W x H canvas.
    fit = whole picture visible (bars filled by the background); otherwise the canvas is covered and `focus` (a point of
    the source, 0-1) is moved as close to `target` (a point of the canvas) as the picture allows."""
    s_fit = min(W / src_w, H / src_h)
    if mode == "fit":
        return {"scale": round(zoom, 4), "x": 0.0, "y": 0.0}
    cover = max(W / (src_w * s_fit), H / (src_h * s_fit))
    k = cover * max(1.0, zoom)
    dw, dh = src_w * s_fit * k, src_h * s_fit * k
    fx, fy = focus or (0.5, 0.5)
    tx, ty = target
    sx = (tx - 0.5) * W - (fx - 0.5) * dw
    sy = (ty - 0.5) * H - (fy - 0.5) * dh  # pixels, y down
    mx, my = max(0.0, (dw - W) / 2), max(0.0, (dh - H) / 2)
    sx, sy = min(max(sx, -mx), mx), min(max(sy, -my), my)
    return {"scale": round(k, 4), "x": round(sx / (W / 2), 4), "y": round(-sy / (H / 2), 4)}


def visible_box(src_w, src_h, W, H, st):
    """Which part of the source (x, y, w, h as 0-1, y down) is visible on the canvas with clip settings `st`."""
    s = min(W / src_w, H / src_h) * st["scale"]
    dw, dh = src_w * s, src_h * s
    cx, cy = W / 2 + st["x"] * W / 2, H / 2 - st["y"] * H / 2  # where the clip's centre lands on the canvas
    x0, y0 = (0 - (cx - dw / 2)) / dw, (0 - (cy - dh / 2)) / dh
    return [round(x0, 4), round(y0, 4), round(W / dw, 4), round(H / dh, 4)]


# ------------------------------------------------------------------------------------------------ keyframe signals
def _shake_offsets(t, dur, amp, seed):
    """Camera-shake offset (dx, dy) at t within a shake of length dur: a few detuned sines, fading out."""
    if t < 0 or t > dur:
        return 0.0, 0.0
    env = (1 - t / dur) ** 0.7 if dur > 0 else 0
    a = math.sin(2 * math.pi * 7.3 * t + seed) * 0.6 + math.sin(2 * math.pi * 12.1 * t + 2 * seed) * 0.4
    b = math.sin(2 * math.pi * 6.1 * t + 3 * seed) * 0.6 + math.sin(2 * math.pi * 10.7 * t + seed) * 0.4
    return amp * env * a, amp * env * b * 0.8


def _zoom_factor(t, dur, to, back):
    if t <= 0:
        return 1.0
    if not back:
        u = min(1.0, t / dur) if dur > 0 else 1.0
        return 1 + (to - 1) * (1 - (1 - u) ** 2)  # ease out, then hold
    if t >= dur:
        return 1.0
    rise = max(0.06, min(0.15, dur * 0.25))
    if t <= rise:
        return 1 + (to - 1) * (t / rise)
    u = (t - rise) / max(1e-6, dur - rise)
    return 1 + (to - 1) * (1 - u) ** 2


# ------------------------------------------------------------------------------------------------ resolve
MAX_CLIPS, MAX_EDITS = 600, 3000


class Resolver:
    def __init__(self, plan, analyses, catalog=None, platform=None):
        self.p = plan if isinstance(plan, dict) else {}
        self.an = analyses
        self.cat = catalog or Catalog.shared()
        self.notes = []
        plat = platform or self.p.get("platform")
        self.platform = plat if plat in PLATFORMS else None
        aspect = str(self.p.get("canvas") or (PLATFORMS[self.platform]["aspect"] if self.platform else "16:9"))
        if aspect not in ASPECTS:
            self.notes.append(f"canvas '{aspect}' unknown; using 16:9")
            aspect = "16:9"
        self.aspect = aspect
        self.W, self.H = ASPECTS[aspect]
        self.safe = PLATFORMS[self.platform]["safe"] if self.platform else DEFAULT_SAFE
        self.ids = set()

    # -------------------------------------------------------------- helpers
    def _id(self, want, prefix):
        i = str(want or "").strip() or prefix
        if i in self.ids or not want:
            n = 1
            while f"{prefix}{n}" in self.ids:
                n += 1
            if want and i in self.ids:
                self.notes.append(f"duplicate id '{i}' renamed to '{prefix}{n}'")
            i = f"{prefix}{n}"
        self.ids.add(i)
        return i

    def _media(self, name, kinds):
        want = Path(str(name or "")).name.lower()
        for a in self.an.values():
            if a.get("file", "").lower() == want and a.get("kind") in kinds:
                return a
        stem = Path(want).stem
        for a in self.an.values():  # forgiving: extension or case differences
            if Path(a.get("file", "")).stem.lower() == stem and a.get("kind") in kinds:
                return a
        return None

    def _focus(self, a, t0, t1):
        """The point of a source worth keeping in view over [t0, t1]: the main face, else the centre."""
        if a["kind"] == "image":
            f = a.get("faces") or []
            return (
                ((f[0]["box"][0] + f[0]["box"][2] / 2, f[0]["box"][1] + f[0]["box"][3] / 2), True)
                if f and f[0]["box"][2] * f[0]["box"][3] > 0.002
                else ((0.5, 0.5), False)
            )
        pts = [
            x["faces"][0]
            for x in a.get("faces", [])
            if t0 - 0.3 <= x["t"] <= t1 + 0.3 and x["faces"] and x["faces"][0]["box"][2] * x["faces"][0]["box"][3] > 0.0015
        ]
        if len(pts) >= 2:
            xs = sorted(f["box"][0] + f["box"][2] / 2 for f in pts)
            ys = sorted(f["box"][1] + f["box"][3] / 2 for f in pts)
            return (xs[len(xs) // 2], ys[len(ys) // 2]), True
        return (0.5, 0.5), False

    def _face_share(self, a, t0, t1):
        if a["kind"] == "image":
            return 1.0 if a.get("faces") else 0.0
        ts = [x for x in a.get("times", []) if t0 <= x <= t1]
        if not ts:
            return 0.0
        with_face = {x["t"] for x in a.get("faces", []) if t0 <= x["t"] <= t1 and x["faces"] and x["faces"][0]["box"][2] > 0.03}
        return len(with_face) / len(ts)

    # -------------------------------------------------------------- clips
    def _clip(self, c, where, overlay=False, at=0.0):
        a = self._media(c.get("file"), {"video", "image"})
        if not a:
            self.notes.append(f"{where}: '{c.get('file')}' is not an available video or photo; skipped")
            return None
        cid = self._id(c.get("id"), "o" if overlay else "c")
        out = {"id": cid, "file": a["file"], "path": a["path"], "kind": a["kind"], "overlay": overlay}
        src_len = max(0.0, (a.get("seconds") or 0) - 0.05)  # ffprobe and the engine can disagree by a few ms
        if a["kind"] == "video":
            sw, sh = a["width"], a["height"]
        else:
            sw, sh = a.get("width") or 1080, a.get("height") or 1080
        out["src_size"] = [sw, sh]
        pieces = []
        dur_req = _n(c.get("duration"), 0.066, 600, None)  # 2 frames: template flash cuts are that short
        if a["kind"] == "image":
            dur = dur_req or 3.0
            pieces.append({"path": a["path"], "kind": "image", "src_from": 0.0, "src_span": dur, "speed": 1.0, "dur": dur})
            win = (0.0, 0.0)
        elif c.get("freeze") is not None:
            t = _n(c.get("freeze"), 0, max(0, src_len - 0.05), 0)
            dur = dur_req or 1.5
            pieces.append(
                {"path": str(still_frame(a["path"], t)), "kind": "image", "src_from": 0.0, "src_span": dur, "speed": 1.0, "dur": dur, "freeze_of": t}
            )
            win = (t, t)
        else:
            src_from = _n(c.get("from"), 0, max(0, src_len - 0.2), 0)
            ramp = c.get("ramp") if isinstance(c.get("ramp"), list) else None
            if ramp:
                # [[seconds of the file after 'from', speed], ...]: each speed holds until the next point. The planned
                # timeline "duration" wins over "to" (models often get the arithmetic of slowed parts wrong): the last
                # speed simply continues, or the ramp ends early, so the clip lasts what the plan says.
                pts = sorted((_n(p[0], 0, src_len, 0), _n(p[1], 0.1, 10, 1)) for p in ramp if isinstance(p, (list, tuple)) and len(p) >= 2)
                if not pts or pts[0][0] > 0.01:
                    pts = [(0.0, pts[0][1] if pts else 1.0)] + pts
                to = _n(c.get("to"), src_from + 0.3, src_len, None)
                limit = src_len if dur_req else (to if to is not None else min(src_len, src_from + pts[-1][0] + 1.0))
                acc = 0.0
                for i, (off, sp) in enumerate(pts):
                    s0 = src_from + off
                    if s0 >= limit - 0.05:
                        break
                    s1 = min(src_from + pts[i + 1][0] if i + 1 < len(pts) else limit, limit)
                    span = s1 - s0 if not dur_req else min(s1 - s0, (dur_req - acc) * sp)
                    if span < 0.05:
                        continue
                    pieces.append({"path": a["path"], "kind": "video", "src_from": s0, "src_span": span, "speed": sp, "dur": span / sp})
                    acc += span / sp
                    if dur_req and acc >= dur_req - 1e-6:
                        break
                if not pieces:
                    pieces.append(
                        {
                            "path": a["path"],
                            "kind": "video",
                            "src_from": src_from,
                            "src_span": min(1.0, src_len - src_from),
                            "speed": 1.0,
                            "dur": min(1.0, src_len - src_from),
                        }
                    )
                end_src = pieces[-1]["src_from"] + pieces[-1]["src_span"]
                if dur_req and acc < dur_req - 0.1:
                    self.notes.append(f"{where}: the file ends before the planned {dur_req:.1f} s; the ramp lasts {acc:.1f} s")
                elif dur_req and to is not None and abs(end_src - to) > 0.3:
                    self.notes.append(
                        f"{where}: the ramp reaches {end_src:.1f} s of the file (not 'to' {to:.1f}) to last the planned {dur_req:.1f} s"
                    )
                win = (src_from, end_src)
            else:
                speed = _n(c.get("speed"), 0.1, 10, 1.0)
                dur = dur_req or min(5.0, (src_len - src_from) / speed)
                span = dur * speed
                if src_from + span > src_len + 0.01:
                    span = max(0.2, src_len - src_from)
                    self.notes.append(f"{where}: shortened to {span / speed:.2f} s (the file is {src_len:.2f} s long)")
                pieces.append({"path": a["path"], "kind": "video", "src_from": src_from, "src_span": span, "speed": speed, "dur": span / speed})
                win = (src_from, src_from + span)
            if c.get("reverse"):
                try:
                    rp = reversed_clip(a["path"], win[0], win[1] - win[0])
                    total = win[1] - win[0]
                    for pc in pieces:  # the reversed file starts at the old end
                        pc["path"], pc["src_from"] = str(rp), total - (pc["src_from"] - win[0]) - pc["src_span"]
                    pieces.reverse()
                    out["reversed"] = True
                except Exception as e:  # noqa: BLE001
                    self.notes.append(f"{where}: could not reverse ({e}); kept forward")
        out["window"] = [round(win[0], 3), round(win[1], 3)]
        out["pieces"] = pieces
        out["dur"] = round(sum(p["dur"] for p in pieces), 3)
        out["volume"] = _n(c.get("volume"), 0, 4, 1.0)
        out["pitch_with_speed"] = bool(c.get("pitch_with_speed"))  # True: sped-up / slowed sound changes pitch (chipmunk)
        sx = c.get("stretch")
        if isinstance(sx, (list, tuple)) and len(sx) == 2:
            out["stretch"] = [_n(sx[0], 0.2, 5, 1.0), _n(sx[1], 0.2, 5, 1.0)]
        out["fade_in"], out["fade_out"] = _n(c.get("fade_in"), 0, 10, 0), _n(c.get("fade_out"), 0, 10, 0)
        # framing on the canvas
        same_shape = abs(sw / sh - self.W / self.H) < 0.02
        rf = c.get("reframe", "center" if same_shape else "subject")
        zoom = 1.0
        if isinstance(rf, dict):
            focus, has_face = (_n(rf.get("x"), 0, 1, 0.5), _n(rf.get("y"), 0, 1, 0.5)), False
            zoom, mode = _n(rf.get("zoom"), 1, 10, 1.0), "cover"
        else:
            mode = "fit" if str(rf).lower() in ("fit", "contain", "letterbox") else "cover"
            focus, has_face = self._focus(a, *win) if str(rf).lower() in ("subject", "face", "auto") else ((0.5, 0.5), False)
        portrait = self.H > self.W
        target = (0.5, 0.40) if has_face and portrait else (0.5, 0.45) if has_face else (0.5, 0.5)
        if overlay and c.get("reframe"):  # a full-frame overlay (b-roll): framed like a main clip
            st = framing(sw, sh, self.W, self.H, mode, focus, target, zoom)
        elif overlay:
            st = {"scale": _n(c.get("scale"), 0.05, 10, 1.0), "x": 0.0, "y": 0.0}
            pos = self._pos(c.get("position"), default=(0.0, 0.0), text=False)
            st["x"], st["y"] = pos
        else:
            st = framing(sw, sh, self.W, self.H, mode, focus, target, zoom)
        st.update(
            rotation=_n(c.get("rotation"), -360, 360, 0.0),
            alpha=_n(c.get("opacity", c.get("alpha")), 0, 1, 1.0),
            flip_h="h" in str(c.get("flip") or "").lower(),
            flip_v="v" in str(c.get("flip") or "").lower(),
        )
        out["settings"] = st
        out["focus"] = [round(focus[0], 3), round(focus[1], 3)] if has_face else None
        out["aim"] = [[round(focus[0], 3), round(focus[1], 3)], list(target), mode]  # how the framing was chosen
        out["visible"] = visible_box(sw, sh, self.W, self.H, st)
        out["background"] = None
        bg = c.get("background")
        if not overlay and (mode == "fit" or bg):
            levels = {"light": 0.0625, "medium": 0.375, "strong": 0.75, "max": 1.0}
            if isinstance(bg, dict):  # {"blur": "light|medium|strong|max"} or {"color": "#RRGGBB"}
                out["background"] = _hex(bg.get("color")) or ("blur", levels.get(str(bg.get("blur", "medium")), 0.375))
            else:
                out["background"] = ("blur", 0.375) if (bg in (None, "", "blur") or mode == "fit" and not _hex(bg)) else (_hex(bg) or ("blur", 0.375))
        cr = c.get("crop")
        if isinstance(cr, dict) and any(_n(cr.get(k), 0, 0.9, 0) for k in ("left", "right", "top", "bottom")):
            out["crop"] = {k: _n(cr.get(k), 0, 0.9, 0) for k in ("left", "right", "top", "bottom")}
        ch = c.get("chroma")
        if ch:
            color = None
            if isinstance(ch, dict):
                color = _hex(ch.get("color"))
            if not color or ch == "auto" or (isinstance(ch, dict) and str(ch.get("color", "")).lower() == "auto"):
                color = (a.get("screen") or {}).get("color")
            if color:
                d = ch if isinstance(ch, dict) else {}
                out["chroma"] = {
                    "color": color,
                    "intensity": _n(d.get("intensity"), 0, 100, 30),
                    "shadow": _n(d.get("shadow"), 0, 100, 0),
                    "edge_smooth": _n(d.get("edge_smooth"), 0, 100, 0),
                    "spill": _n(d.get("spill"), 0, 100, 0),
                }
                if isinstance(out.get("background"), (list, tuple)) or out.get("background") in ("blur", None):
                    # a blur fill is the UN-keyed clip blurred: the screen colour would show through. A dark colour instead.
                    if out.get("background") is not None:
                        self.notes.append(f"{where}: a blurred background would show the removed screen; using a dark colour behind it")
                    out["background"] = "#0A0A12"
            else:
                self.notes.append(f"{where}: chroma asked but no screen colour known; skipped")
        m = c.get("mask")
        if isinstance(m, dict) and m.get("type"):
            mt = MASKS.get(str(m["type"]).lower(), str(m["type"]))
            if mt in MASKS.values():
                out["mask"] = {
                    "type": mt,
                    "x": _n(m.get("x"), 0, 1, 0.5),
                    "y": _n(m.get("y"), 0, 1, 0.5),
                    "size": _n(m.get("size"), 0.02, 3, 0.5),
                    "rotation": _n(m.get("rotation"), -360, 360, 0),
                    "feather": _n(m.get("feather"), 0, 100, 0),
                    "invert": bool(m.get("invert")),
                    "width": _n(m.get("width"), 0.02, 3, None),
                    "round": _n(m.get("round"), 0, 100, None),
                }
            else:
                self.notes.append(f"{where}: unknown mask '{m['type']}'")
        if c.get("blend"):
            bm = BLENDS.get(str(c["blend"]).lower(), str(c["blend"]))
            if bm in BLENDS.values():
                out["blend"] = bm
            else:
                self.notes.append(f"{where}: unknown blend '{c['blend']}'")
        if overlay:
            out["start"] = _n(at, 0, 3600, 0)
        return out

    def _pos(self, v, default=(0.0, 0.0), text=True):
        """Canvas position in engine units (x right, y up, -1..1 = canvas edges) from a name or [x, y]."""
        top, bottom = 1 - 2 * self.safe["top"], -1 + 2 * self.safe["bottom"]
        portrait = self.H > self.W
        names = {
            "top": (0, top - (0.12 if portrait else 0.15)),
            "upper": (0, 0.45 if portrait else 0.5),
            "center": (0, 0),
            "middle": (0, 0),
            "lower": (0, bottom + (0.25 if portrait else 0.2)),
            "bottom": (0, bottom + (0.1 if portrait else 0.12)),
            "top_left": (-0.55, top - 0.12),
            "top_right": (0.45, top - 0.12),
            "bottom_left": (-0.55, bottom + 0.12),
            "bottom_right": (0.45, bottom + 0.12),
        }
        if isinstance(v, str) and v.lower().replace(" ", "_") in names:
            return names[v.lower().replace(" ", "_")]
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return _n(v[0], -1.5, 1.5, default[0]), _n(v[1], -1.5, 1.5, default[1])
        if isinstance(v, dict) and v.get("name"):
            bx, by = names.get(str(v["name"]).lower().replace(" ", "_"), default)
            return _n(bx + float(v.get("dx") or 0), -1.5, 1.5, bx), _n(by + float(v.get("dy") or 0), -1.5, 1.5, by)
        if isinstance(v, dict):
            return _n(v.get("x"), -1.5, 1.5, default[0]), _n(v.get("y"), -1.5, 1.5, default[1])
        return default

    # -------------------------------------------------------------- the whole plan
    def resolve(self):
        p = self.p
        out = {
            "name": str(p.get("name") or "edit")[:40],
            "aspect": self.aspect,
            "canvas": [self.W, self.H],
            "fps": 30,
            "platform": self.platform,
            "safe": self.safe,
            "notes": self.notes,
        }
        if isinstance(p.get("template"), dict) and p["template"].get("draft"):
            out["template"] = self._template(p["template"])
        clips = []
        # caps against runaway plans, far above real edits (a 1-minute cut at 140 BPM on every beat is 140 clips); hitting
        # one is reported, never silent (a silent cap once cut the last 11 s off a faster-paced edit)
        if len(p.get("clips") or []) > MAX_CLIPS:
            self.notes.append(f"the plan has {len(p['clips'])} clips; only the first {MAX_CLIPS} are used")
        for i, c in enumerate((p.get("clips") or [])[:MAX_CLIPS]):
            if isinstance(c, dict):
                r = self._clip(c, f"clip {c.get('id') or i + 1}")
                if r:
                    clips.append(r)
        if not clips and not out.get("template"):
            raise ValueError("the plan has no usable clips: " + "; ".join(self.notes[:6]))
        t = 0.0
        for c in clips:  # microsecond precision: beat-grid lengths (0.428571 s) must add up exactly
            c["dur"] = round(sum(p["dur"] for p in c["pieces"]), 6)
            c["start"] = round(t, 6)
            t += c["dur"]
            c["end"] = round(t, 6)
            tt = c["start"]
            for pc in c["pieces"]:
                pc["start"] = round(tt, 6)
                tt += pc["dur"]
        layers = []
        for i, c in enumerate((p.get("layers") or [])[:20]):
            if isinstance(c, dict):
                r = self._clip(c, f"layer {c.get('id') or i + 1}", overlay=True, at=c.get("at", 0))
                if r:
                    tt = r["start"]
                    for pc in r["pieces"]:
                        pc["start"] = round(tt, 3)
                        tt += pc["dur"]
                    r["end"] = round(r["start"] + r["dur"], 3)
                    layers.append(r)
        out["clips"], out["layers"] = clips, layers
        items = {c["id"]: c for c in clips + layers}
        edits_in = [e for e in (p.get("edits") or []) if isinstance(e, dict)]
        if len(edits_in) > MAX_EDITS:
            self.notes.append(f"the plan has {len(edits_in)} edits; only the first {MAX_EDITS} are used")
            edits_in = edits_in[:MAX_EDITS]
        # beat snapping happens before anything is placed relative to clips
        music = [e for e in edits_in if str(e.get("type")).lower() == "audio"]
        if p.get("beat_sync") and music:
            self._snap(clips, music[0])
        base_end = clips[-1]["end"] if clips else (out.get("template") or {}).get("seconds", 0.0)
        out["end"] = base_end
        texts = {}
        edits = []
        # texts first, so animations / keyframes can point at them
        order = sorted(
            edits_in,
            key=lambda e: (
                0 if TYPE_ALIASES.get(str(e.get("type")).lower(), (str(e.get("type")).lower(),))[0] in ("text", "captions") or e.get("text") else 1
            ),
        )
        for e in order:
            typ = str(e.get("type") or "").lower().strip().replace(" ", "_").replace("-", "_")
            if typ in TYPE_ALIASES:
                typ, kind = TYPE_ALIASES[typ]
                if kind and not e.get("kind"):
                    e = {**e, "kind": kind}
            if typ == "animation" and e.get("text") and e.get("on") not in texts:
                # a title written as one "text_intro" edit with its words: the text, with that animation
                k = str(e.get("kind") or "intro").lower()
                e = {
                    **{x: v for x, v in e.items() if x not in ("type", "name", "kind")},
                    "type": "text",
                    (k if k in ("intro", "outro", "loop") else "intro"): e.get("name"),
                }
                typ = "text"
            where = f"edit {e.get('id') or typ}"
            fn = getattr(self, f"_e_{typ}", None)
            if not fn:
                self.notes.append(f"{where}: unknown edit type '{typ}'; skipped")
                continue
            try:
                r = fn(e, where, items, texts, out)
            except Exception as ex:  # noqa: BLE001  (one bad edit must not sink the plan)
                self.notes.append(f"{where}: {type(ex).__name__}: {str(ex)[:120]}")
                r = None
            for x in r if isinstance(r, list) else [r] if r else []:
                if x["type"] == "text":
                    texts[x["id"]] = x
                edits.append(x)
        out["edits"] = edits
        self._clear_subtitles(edits)
        self._type_system(edits)
        self._headroom(clips + layers, edits)
        out["end"] = max([base_end] + [l["end"] for l in layers])
        if self.platform and PLATFORMS[self.platform]["max_s"] and out["end"] > PLATFORMS[self.platform]["max_s"]:
            self.notes.append(f"the edit is {out['end']:.1f} s; {self.platform} allows {PLATFORMS[self.platform]['max_s']} s")
        return out

    def _clear_subtitles(self, edits):
        """Subtitles own their band: a title or label that would sit on them at the same time moves to the top of the
        frame (seen: a section label written over the narration line)."""
        caps = [e for e in edits if e["type"] == "captions" and e.get("position")]
        top = 1 - 2 * self.safe["top"] - 0.12
        for t in edits:
            if t["type"] != "text" or str(t["id"]).startswith("kt"):
                continue
            for c in caps:
                same_time = t["window"][0] < c["window"][1] and c["window"][0] < t["window"][1]
                if same_time and abs(t["position"][1] - c["position"][1]) < 0.25:
                    t["position"] = [t["position"][0], round(top, 3)]
                    t["box"] = self.frame_box(t["position"], t["text"], t["style"])
                    self.notes.append(f"text {t['id']}: moved to the top, clear of the subtitles")
                    break

    def _type_system(self, edits):
        """One font per role in a video, like a designer's type system: every label (small text) in one face, every
        title in one face (the most used of each). Mixed faces for the same kind of text look accidental."""
        roles = {"label": [], "title": []}
        for e in edits:
            if e["type"] == "text" and e["style"].get("font"):
                roles["label" if e["style"]["size"] <= 11 else "title"].append(e)
        for role, ts in roles.items():
            fonts = Counter(t["style"]["font"] for t in ts)
            if len(fonts) > 1:
                asked = [t["style"]["font"] for t in ts if t["style"].get("asked")]
                main = asked[-1] if asked else fonts.most_common(1)[0][0]  # a face the client chose wins
                for t in ts:
                    t["style"]["font"] = main
                self.notes.append(f"{role}s: one font for all ({self.cat.item(main)['name']})")

    def _headroom(self, clips, edits):
        """Zooms, shakes and scale keyframes multiply a clip's scale; JianYing stops at 500%. Lower the clip's own zoom
        (keeping its focus point) so the biggest planned scale fits."""
        for c in clips:
            peak = 1.0
            for e in edits:
                if e.get("on") != c["id"]:
                    continue
                if e["type"] == "zoom":
                    peak = max(peak, e["to"] * (1.09 if any(x["type"] == "shake" and x.get("on") == c["id"] for x in edits) else 1.0))
                elif e["type"] == "shake":
                    peak = max(peak, 1 + 0.05 * e["strength"] + 0.04)
                elif e["type"] == "keyframes" and e["property"] == "scale":
                    peak = max(peak, max(v for _, v in e["points"]))
            st = c["settings"]
            if st["scale"] * peak <= MAX_SCALE + 1e-6:
                continue
            new_scale = MAX_SCALE / peak
            if c.get("overlay"):
                st["scale"] = round(new_scale, 4)
            else:
                sw, sh = c["src_size"]
                cover = framing(sw, sh, self.W, self.H, "cover")["scale"]
                focus, target, _ = c.get("aim") or [(0.5, 0.5), (0.5, 0.5), "cover"]
                st.update(framing(sw, sh, self.W, self.H, "cover", tuple(focus), tuple(target), zoom=max(1.0, new_scale / cover)))
                if st["scale"] * peak > MAX_SCALE + 1e-6:  # even the plain cover is too big for this zoom: zoom less
                    for e in edits:
                        if e.get("on") == c["id"] and e["type"] == "zoom":
                            e["to"] = round(max(1.05, MAX_SCALE / st["scale"] / (1.09 if peak > e["to"] else 1.0)), 3)
            c["visible"] = visible_box(*c["src_size"], self.W, self.H, st) if not c.get("overlay") else c.get("visible")
            self.notes.append(f"clip {c['id']}: framing zoom lowered to {st['scale'] * 100:.0f}% so its zoom/shake fits JianYing's 500% limit")

    def _template(self, t):
        """Template mode: an existing JianYing project is copied, its media replaced by name and its texts rewritten;
        the plan's own clips and edits are added on top as new tracks."""
        media = {}
        for old_name, f in (t.get("media") or {}).items():
            a = self._media(f, {"video", "image", "audio"})
            if a:
                media[str(old_name)] = a["path"]
            else:
                self.notes.append(f"template: '{f}' is not an available file; '{old_name}' kept")
        texts = [
            {"track": x.get("track", 0), "index": int(_n(x.get("index"), 0, 999, 0)), "text": str(x.get("text") or "")[:400]}
            for x in (t.get("texts") or [])
            if isinstance(x, dict) and x.get("text")
        ]
        seconds = 0.0
        try:  # the template's own length, so edits on top of it can be placed and clamped
            from ai_pc.video.jybuild import DRAFTS

            d = json.loads((DRAFTS / str(t["draft"]) / "draft_content.json").read_text(encoding="utf-8"))
            seconds = d.get("duration", 0) / 1e6
        except Exception as e:  # noqa: BLE001
            self.notes.append(f"template: cannot read '{t['draft']}' ({type(e).__name__})")
        return {"draft": str(t["draft"]), "media": media, "texts": texts, "seconds": round(seconds, 3)}

    def _snap(self, clips, music):
        a = self._media(music.get("file"), {"audio", "video"})
        snd = (a or {}).get("sound") or {}
        beats = snd.get("beats") or []
        if not beats:
            self.notes.append("beat_sync: the music has no clear beat; cuts left as planned")
            return
        at, src_from = _n(music.get("at"), 0, 3600, 0), _n(music.get("from"), 0, 3600, 0)
        grid = [b - src_from + at for b in beats if b >= src_from]
        t, moved = 0.0, 0
        for c in clips[:-1]:
            if len(c["pieces"]) != 1:
                t += c["dur"]
                continue
            end = t + c["dur"]
            near = min(grid, key=lambda g: abs(g - end), default=None)
            pc = c["pieces"][0]
            if near is not None and abs(near - end) <= 0.35 and near - t >= 0.4:
                new_dur = near - t
                a2 = self._media(c["file"], {"video", "image"})
                max_dur = (a2["seconds"] - pc["src_from"]) / pc["speed"] if a2 and a2["kind"] == "video" else 600
                if new_dur <= max_dur:
                    pc["dur"], pc["src_span"] = new_dur, new_dur * pc["speed"]
                    c["dur"] = round(new_dur, 3)
                    c["window"][1] = round(pc["src_from"] + pc["src_span"], 3)
                    moved += 1
            t += c["dur"]
        tt = 0.0
        for c in clips:
            c["start"] = round(tt, 3)
            for pc in c["pieces"]:
                pc["start"] = round(tt, 3)
                tt += pc["dur"]
            c["end"] = round(tt, 3)
        self.notes.append(f"beat_sync: {moved} cut(s) moved onto beats")

    # -------------------------------------------------------------- time windows
    def _window(self, e, items, texts, default_dur=2.0):
        on = e.get("on")
        tgt = items.get(on) or texts.get(on) if on else None
        if on and not tgt:
            self.notes.append(f"edit {e.get('id')}: 'on' refers to unknown '{on}'; times read as absolute")
        if tgt:
            base, length = tgt["start"], tgt.get("dur", tgt.get("duration", default_dur))
            s = _n(e.get("start"), 0, length, 0)
            d = _n(e.get("duration"), 0.05, 3600, length - s)
            s0, s1 = base + s, base + min(length, s + d)
        else:
            s0 = _n(e.get("start", e.get("at")), 0, 3600, 0)
            s1 = s0 + _n(e.get("duration"), 0.05, 3600, default_dur)
        return round(s0, 3), round(s1, 3), tgt

    def _clip_at(self, t, items):
        for c in items.values():
            if not c.get("overlay") and c["start"] <= t < c["end"]:
                return c
        return None

    def src_time(self, clip, t):
        """Source time in clip's file shown at timeline time t (None for stills)."""
        for pc in clip["pieces"]:
            if pc["start"] <= t <= pc["start"] + pc["dur"] + 1e-6:
                if pc["kind"] == "image":
                    return None
                return pc["src_from"] + (t - pc["start"]) * pc["speed"]
        return None

    def _faces_in_window(self, t0, t1, items):
        """Share of the window's analysed samples with a clear face, across the clips under it."""
        shares = []
        for c in items.values():
            if c.get("overlay") or c["end"] <= t0 or c["start"] >= t1:
                continue
            a = self._media(c["file"], {"video", "image"})
            if not a:
                continue
            a0, a1 = self.src_time(c, max(t0, c["start"])), self.src_time(c, min(t1, c["end"]) - 1e-3)
            if a["kind"] == "image" or a0 is None:
                shares.append(self._face_share(a, 0, 0))
            else:
                lo, hi = sorted((a0, a1 if a1 is not None else a0))
                shares.append(self._face_share(a, lo, hi))
        return max(shares) if shares else 0.0

    # -------------------------------------------------------------- edit types
    def _base(self, e, typ, prefix):
        return {"id": self._id(e.get("id"), prefix), "type": typ, "expect": str(e.get("expect") or "")[:200]}

    def _e_transition(self, e, where, items, texts, out):
        after = items.get(e.get("after") or e.get("on"))
        clips = out["clips"]
        if not after or after.get("overlay") or not clips or after is clips[-1]:
            self.notes.append(f"{where}: transitions go between two main clips ('after' must be a clip that is not the last); skipped")
            return None
        nxt = clips[clips.index(after) + 1]
        key = self.cat.resolve("transition", e.get("name"), self.notes, where + ": ")
        if not key:
            return None
        it = self.cat.item(key)
        dur = _n(e.get("duration"), 0.1, 3, it.get("default_duration_s") or 0.5)
        shorter = min(after["pieces"][-1]["dur"], nxt["pieces"][0]["dur"])
        limit = shorter / 2  # JianYing's own limit
        if dur > limit:
            self.notes.append(f"{where}: transition shortened to {limit:.2f} s (half the shorter clip)")
            dur = limit
        craft = max(0.3, 0.2 * min(after["dur"], nxt["dur"]))  # longer and the edit is mostly double exposures
        if dur > craft + 1e-3:
            dur = round(craft, 3)
        r = self._base(e, "transition", "tr")
        r.update(
            item=key,
            after=after["id"],
            before=nxt["id"],
            duration=round(dur, 3),
            window=[round(after["end"] - dur / 2, 3), round(after["end"] + dur / 2, 3)],
            cut=after["end"],
        )
        r["expect"] = r["expect"] or f"{self.cat.card(key).get('en')}: {self.cat.card(key).get('desc')}"
        return r

    def _rescue(self, e, typ, where, items, texts, out):
        """A name that exactly belongs to another kind of item (a filter written as an effect, ...): build that kind.
        Never when the name also exists in the asked kind (some names are both a filter and an effect)."""
        keys = self.cat.exact(e.get("name"))
        own = EFFECT_CATS if typ == "effect" else ("filter",)
        if any(self.cat.item(k)["category"] in own for k in keys) or e.get("_rescued"):
            return False
        e = {**e, "_rescued": True}
        move = MOVE_NAMES.get(re.sub(r"[\s_-]+", " ", str(e.get("name") or "").strip().lower()))
        if typ == "effect" and move and not keys:  # a camera move written as an effect ("zoom_punch"): do the move
            p = e.get("params") if isinstance(e.get("params"), dict) else {}
            amt = p.get("strength", p.get("intensity", e.get("strength")))
            try:
                amt = float(amt)
            except (TypeError, ValueError):
                amt = None
            self.notes.append(f"{where}: '{e.get('name')}' is a camera move, not an effect; done as a {move}")
            if move == "zoom":
                to = 1.25 if amt is None else 1 + amt / 250 if amt > 4 else amt  # 0-100 strength or a factor
                return self._e_zoom({**e, "to": min(1.6, max(1.05, to)), "back": True}, where, items, texts, out)
            return self._e_shake({**e, "strength": 0.6 if amt is None else amt / 100 if amt > 1 else amt}, where, items, texts, out)
        for key in keys:
            cat = self.cat.item(key)["category"]
            if typ == "effect" and cat == "filter":
                self.notes.append(f"{where}: '{e.get('name')}' is a filter; applied as a filter")
                return self._e_filter(e, where, items, texts, out)
            if typ == "effect" and cat in ("clip_intro", "clip_outro", "clip_combo"):  # e.g. a fade-out written as an effect
                t0, t1, tgt = self._window(e, items, texts, default_dur=0.6)
                c = tgt if tgt is not None and tgt.get("pieces") is not None else self._clip_at(min(max(0.0, t0), out["end"] - 0.05), items)
                if c is not None:
                    self.notes.append(f"{where}: '{e.get('name')}' is a clip {cat.split('_')[1]} animation; applied to {c['id']}")
                    return self._e_animation(
                        {**e, "on": c["id"], "kind": cat.split("_")[1], "duration": min(1.0, max(0.3, t1 - t0))}, where, items, texts, out
                    )
            if typ == "filter" and cat in EFFECT_CATS:
                self.notes.append(f"{where}: '{e.get('name')}' is an effect; applied as an effect")
                return self._e_effect(e, where, items, texts, out)
        return False

    def _e_effect(self, e, where, items, texts, out):
        r = self._rescue(e, "effect", where, items, texts, out)
        if r is not False:
            return r
        key = self.cat.resolve(EFFECT_CATS, e.get("name"), self.notes, where + ": ")
        if not key:
            return None
        it, card = self.cat.item(key), self.cat.card(key)
        t0, t1, tgt = self._window(e, items, texts, default_dur=it.get("default_duration_s") or 2.0)
        t0, t1 = max(0.0, t0), min(out["end"], t1)
        if t1 - t0 < 0.1:
            self.notes.append(f"{where}: window {t0:.2f}-{t1:.2f} s is outside the edit; skipped")
            return None
        r = self._base(e, "effect", "fx")
        if e.get("layer") in ("texture", "accent"):
            r["layer"] = e["layer"]  # texture = over the whole video (grain, vignette, bars); accent = a quick hit (flash, blur)
        r.update(
            item=key,
            category=it["category"],
            window=[t0, t1],
            params=self.cat.param_list(key, e.get("params"), self.notes, where + ": "),
            target=card.get("target"),
            moves_image=bool(card.get("moves_image")),
            over_text=bool(e.get("over_text")),
        )
        whole = tgt is not None and tgt.get("pieces") is not None and abs(t0 - tgt["start"]) < 0.05 and abs(t1 - tgt["end"]) < 0.05
        r["mode"] = "segment" if whole else "track"
        r["on"] = tgt["id"] if tgt is not None and tgt.get("pieces") is not None else None
        if it["category"] == "character_effect":
            share = self._faces_in_window(t0, t1, items)
            r["face_share"] = round(share, 2)
            if share < 0.3:
                self.notes.append(
                    f"{where}: '{it['name']}' follows a person, but a clear face is visible in only "
                    f"{share * 100:.0f}% of {t0:.1f}-{t1:.1f} s; it may show little"
                )
        r["expect"] = r["expect"] or f"{card.get('en')}: {card.get('desc')}"
        return r

    def _e_filter(self, e, where, items, texts, out):
        r = self._rescue(e, "filter", where, items, texts, out)
        if r is not False:
            return r
        key = self.cat.resolve("filter", e.get("name"), self.notes, where + ": ")
        if not key:
            return None
        t0, t1, tgt = self._window(e, items, texts, default_dur=out["end"])
        t0, t1 = max(0.0, t0), min(out["end"], t1)
        if t1 - t0 < 0.1:
            return None
        card = self.cat.card(key)
        r = self._base(e, "filter", "fl")
        whole = tgt is not None and tgt.get("pieces") is not None and abs(t0 - tgt["start"]) < 0.05 and abs(t1 - tgt["end"]) < 0.05
        r.update(
            item=key,
            window=[t0, t1],
            strength=_n(e.get("strength", e.get("intensity")), 0, 100, 80),
            mode="segment" if whole else "track",
            on=tgt["id"] if whole else None,
        )
        r["expect"] = r["expect"] or f"{card.get('en')} look: {card.get('look') or card.get('desc')}"
        return r

    def _e_animation(self, e, where, items, texts, out):
        on = e.get("on")
        tgt_clip, tgt_text = items.get(on), texts.get(on)
        if not tgt_clip and not tgt_text:
            self.notes.append(f"{where}: animations need 'on' = a clip, layer or text id; skipped")
            return None
        cats = {self.cat.item(k)["category"] for k in self.cat.exact(e.get("name"))}
        if tgt_clip and cats and not cats & set(CLIP_ANIM.values()):
            # meant for something else on that shot: a text animation goes to the text shown on the shot (its label
            # or title), a transition to the cut into it
            if cats & set(TEXT_ANIM.values()):
                over = [t for t in texts.values() if t["window"][0] < tgt_clip["end"] - 0.05 and tgt_clip["start"] < t["window"][1] - 0.05]
                if over:
                    t = min(over, key=lambda x: abs(x["window"][0] - tgt_clip["start"]))
                    self.notes.append(f"{where}: '{e.get('name')}' is a text animation; applied to the text '{t['text'][:24]}' on {on}")
                    kind = next(k for k, v in TEXT_ANIM.items() if v in cats)
                    return self._e_animation({**e, "on": t["id"], "kind": kind}, where, items, texts, out)
            if "transition" in cats:
                prev = next((c for c in items.values() if not c.get("overlay") and abs(c["end"] - tgt_clip["start"]) < 1e-3), None)
                if prev is not None:
                    self.notes.append(f"{where}: '{e.get('name')}' is a transition; placed at the cut into {on}")
                    return self._e_transition({**e, "after": prev["id"]}, where, items, texts, out)
        table = TEXT_ANIM if tgt_text else CLIP_ANIM
        kind = str(e.get("kind") or "").lower()
        cats = [table[kind]] if kind in table else list(table.values())
        key = self.cat.resolve(cats, e.get("name"), self.notes, where + ": ")
        if not key:
            return None
        it = self.cat.item(key)
        kind = next(k for k, v in table.items() if v == it["category"])
        tgt = tgt_text or tgt_clip
        length = tgt.get("dur") or tgt.get("duration")
        dur = _n(e.get("duration"), 0.1, length, min(it.get("default_duration_s") or 0.5, length))
        if kind == "combo":
            dur = length
        t0 = tgt["start"] if kind in ("intro", "combo", "loop") else tgt["start"] + length - dur
        r = self._base(e, "animation", "an")
        r.update(item=key, kind=kind, on=tgt["id"], on_text=bool(tgt_text), duration=round(dur, 3), window=[round(t0, 3), round(t0 + dur, 3)])
        if tgt_text and tgt_text.get("box"):
            r["box"] = tgt_text["box"]
        card = self.cat.card(key)
        r["expect"] = r["expect"] or f"{'text' if tgt_text else 'clip'} {kind}: {card.get('en')} ({card.get('motion') or card.get('desc')})"
        return r

    def _e_keyframes(self, e, where, items, texts, out):
        on = e.get("on")
        tgt = items.get(on) or texts.get(on)
        prop = KF_PROPS.get(str(e.get("property") or "").lower())
        if not tgt or not prop:
            self.notes.append(f"{where}: keyframes need 'on' (clip, layer or text id) and a known property; skipped")
            return None
        if prop == "volume" and tgt.get("type") == "text":
            return None
        length = tgt.get("dur") or tgt.get("duration")
        lo, hi = KF_RANGE[prop]
        pts = []
        for pnt in (e.get("points") or [])[:40]:
            if isinstance(pnt, dict):
                pnt = [pnt.get("at", pnt.get("t")), pnt.get("value", pnt.get("v"))]
            if isinstance(pnt, (list, tuple)) and len(pnt) >= 2:
                pts.append([round(_n(pnt[0], 0, length, 0), 3), _n(pnt[1], lo, hi, (lo + hi) / 2)])
        if len(pts) < 2:
            self.notes.append(f"{where}: keyframes need at least two points; skipped")
            return None
        pts.sort()
        r = self._base(e, "keyframes", "kf")
        r.update(on=tgt["id"], property=prop, points=pts, window=[round(tgt["start"] + pts[0][0], 3), round(tgt["start"] + pts[-1][0], 3)])
        if e.get("adjust"):
            r["adjust"] = True  # part of the grade (e.g. exposure matching), not a move to look for
        r["expect"] = r["expect"] or f"{prop} changes from {pts[0][1]} to {pts[-1][1]}"
        return r

    def _e_shake(self, e, where, items, texts, out):
        t0, t1, tgt = self._window(e, items, texts, default_dur=0.6)
        if tgt is None or tgt.get("pieces") is None:
            tgt = self._clip_at(t0, items)
            if not tgt:
                return None
        t1 = min(t1, tgt["end"])
        r = self._base(e, "shake", "sh")
        r.update(on=tgt["id"], window=[t0, t1], strength=_n(e.get("strength"), 0.05, 1, 0.5))
        r["expect"] = r["expect"] or "the picture shakes like a camera hit by an impact"
        return r

    def _e_zoom(self, e, where, items, texts, out):
        t0, t1, tgt = self._window(e, items, texts, default_dur=0.5)
        if tgt is None or tgt.get("pieces") is None:
            tgt = self._clip_at(t0, items)
            if not tgt:
                return None
        t1 = min(t1, tgt["end"])
        r = self._base(e, "zoom", "zm")
        r.update(on=tgt["id"], window=[t0, t1], to=_n(e.get("to"), 0.3, 4, 1.25), back=bool(e.get("back", True)))
        r["expect"] = r["expect"] or ("a quick punch-in zoom" if r["back"] else "a smooth zoom")
        return r

    def _style(self, e, where):
        """Text look shared by titles and captions."""
        font = self.cat.resolve("font", e.get("font"), self.notes, where + ": ") if e.get("font") else None
        # fonts: only ones known to download here (a miss costs an export), unless the client asked for this face
        if font and font not in self.cat.boost and not e.get("font_asked"):
            n = self.cat.index.notes.get(font, {})
            alt = self.cat.known_like(f"{self.cat.item(font)['name']} {n.get('en', '')} {n.get('desc', '')} {' '.join(n.get('tags', []))}", ["font"])
            words = str(e.get("text") or " ".join(str(x.get("text", "")) for x in e.get("lines") or [] if isinstance(x, dict)))
            if sum(ch.isascii() for ch in words) >= 0.8 * max(1, len(words)):  # English text: a font designed for Latin letters
                alt.sort(key=lambda k: self.cat.index.notes.get(k, {}).get("script") != "latin")  # (CJK fonts' Latin glyphs look off)
            if alt:
                self.notes.append(
                    f"{where}: font '{self.cat.item(font)['name']}' is untried here; using '{self.cat.item(alt[0])['name']}', known to work"
                )
                font = alt[0]
        if font and e.get("font_asked") and font not in self.cat.boost:
            self.notes.append(f"{where}: font '{self.cat.item(font)['name']}' was asked for; first use here (checked at export)")
        st = {
            "font": font,
            "asked": bool(e.get("font_asked")),
            "size": _n(e.get("size"), 2, 40, 10),
            "color": _hex(e.get("color"), "#FFFFFF"),
            "bold": bool(e.get("bold", True)),
            "italic": bool(e.get("italic")),
            "underline": bool(e.get("underline")),
            "align": {"left": 0, "center": 1, "right": 2}.get(str(e.get("align", "center")).lower(), 1),
            "letter_spacing": int(_n(e.get("letter_spacing"), -20, 100, 0)),
            "line_spacing": int(_n(e.get("line_spacing"), -20, 100, 0)),
            "alpha": _n(e.get("opacity", e.get("alpha")), 0, 1, 1.0),
            "scale": _n(e.get("scale"), 0.1, 10, 1.0),
            "rotation": _n(e.get("rotation"), -360, 360, 0),
            "vertical": bool(e.get("vertical")),
            "max_width": _n(e.get("max_width"), 0.1, 1.0, 0.82),
        }
        ol = e.get("outline")
        if ol is True or (ol is None and not e.get("background")):
            ol = {"color": "#000000", "width": 40}
        if isinstance(ol, dict):
            st["outline"] = {
                "color": _hex(ol.get("color"), "#000000"),
                "width": _n(ol.get("width"), 0, 100, 40),
                "alpha": _n(ol.get("alpha"), 0, 1, 1),
            }
        sh = e.get("shadow")
        if sh:
            sh = sh if isinstance(sh, dict) else {}
            st["shadow"] = {
                "color": _hex(sh.get("color"), "#000000"),
                "alpha": _n(sh.get("alpha"), 0, 1, 0.7),
                "diffuse": _n(sh.get("diffuse"), 0, 100, 15),
                "distance": _n(sh.get("distance"), 0, 100, 5),
                "angle": _n(sh.get("angle"), -180, 180, -45),
            }
        bg = e.get("background")
        if isinstance(bg, dict) or (isinstance(bg, str) and _hex(bg)):
            bg = bg if isinstance(bg, dict) else {"color": bg}
            st["background"] = {
                "color": _hex(bg.get("color"), "#000000"),
                "alpha": _n(bg.get("alpha"), 0, 1, 0.6),
                "round": _n(bg.get("round", bg.get("round_radius")), 0, 1, 0.2),
                "style": 2 if str(bg.get("style")) == "2" else 1,
                "height": _n(bg.get("height"), 0, 1, 0.14),
                "width": _n(bg.get("width"), 0, 1, 0.14),
                "x_offset": _n(bg.get("x_offset"), 0, 1, 0.5),
                "y_offset": _n(bg.get("y_offset"), 0, 1, 0.5),
            }
        return st

    def _e_text(self, e, where, items, texts, out):
        txt = str(e.get("text") or "").strip()[:400]
        if not txt:
            return None
        t0, t1, _ = self._window(e, items, texts, default_dur=3.0)
        if t0 >= out["end"] - 0.3:  # planned past the end (the clips came out shorter): show it at the end
            d = min(max(1.2, t1 - t0), 2.5, out["end"])
            self.notes.append(
                f"{where}: text planned at {t0:.1f} s, after the video ends ({out['end']:.1f} s); moved to {out['end'] - d:.1f}-{out['end']:.1f} s"
            )
            t0, t1 = out["end"] - d, out["end"]
        t1 = min(t1, out["end"])
        if not str(e.get("id") or "").startswith(("kt", "lb")):  # kinetic words are short by design; labels belong to their shot
            need = min(3.0, max(1.2, 0.5 + 0.3 * len(txt.split())))  # time to read it: ~0.5 s to notice + 0.3 s a word
            if t1 - t0 < need - 0.05 and out["end"] >= need:
                t1 = min(out["end"], t0 + need)
                t0 = max(0.0, min(t0, t1 - need))
                self.notes.append(f"{where}: kept on screen {t1 - t0:.1f} s so it can be read")
        r = self._base(e, "text", "tx")
        st = self._style(e, where)
        lim = self.fit_size(txt, st)
        if st["size"] > lim:
            self.notes.append(f"{where}: size {st['size']:.0f} -> {lim:.0f} so '{txt[:24]}' fits the frame")
            st["size"] = lim
        txt = self.wrap_words(txt, st)
        pos = self._pos(e.get("position"), default=(0, 0))
        r.update(
            text=txt, start=t0, duration=round(t1 - t0, 3), window=[t0, round(t1, 3)], style=st, position=list(self._safe_pos(pos, txt, st, where))
        )
        r["box"] = self.frame_box(r["position"], txt, st)
        for k in ("intro", "outro", "loop"):  # inline animations become animation edits
            if e.get(k):
                r.setdefault("_anims", []).append({"on": r["id"], "kind": k, "name": e[k], "duration": e.get(f"{k}_duration")})
        r["expect"] = r["expect"] or f'the text "{txt[:60]}" is visible and readable'
        res = [r]
        for a in r.pop("_anims", []):
            x = self._e_animation(a, f"{where} {a['kind']}", items, {**texts, r["id"]: r}, out)
            if x:
                res.append(x)
        return res

    def wrap_words(self, txt, st):
        """Line breaks between words, placed by us: JianYing wraps by character (as for Chinese), so a long Latin title
        breaks mid-word ("ROAD TRIP 2 / 026"). Text that already has line breaks, or no spaces, is left alone."""
        if "\n" in txt or " " not in txt.strip() or not all(ord(ch) < 0x2E80 for ch in txt):
            return txt
        unit = 0.72 * 5.6 * st["scale"] * st["size"] * min(self.W, self.H) / 1080
        cap = max(4, int(st.get("max_width", 0.82) * self.W / max(1e-6, unit)))
        if len(txt) <= cap:
            return txt
        lines, cur = [], ""
        for w in txt.split():
            if cur and len(cur) + 1 + len(w) > cap:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        lines.append(cur)
        return "\n".join(lines)

    def fit_size(self, txt, st):
        """The largest size at which every word fits on a line and the text takes at most 2 lines (3 when long), by the
        same measurements as text_box: a word broken across lines, or a title wider than the frame, looks broken."""
        # px of one character per size unit, for wide bold display faces (0.72 of the line height; the 0.6 that text_box
        # measured on the default font broke "2026" across two lines in a bold title)
        unit = 0.72 * 5.6 * st["scale"] * min(self.W, self.H) / 1080
        width = st.get("max_width", 0.82) * self.W
        words = str(txt).split() or [str(txt)]
        lines = 2 if len(words) <= 4 else 3
        lim = min(width / (max(len(w) for w in words) * unit), lines * width / (max(1, len(str(txt))) * unit))
        return round(max(4.0, lim), 1)

    def text_box(self, txt, st):
        """Rough size of a text on the canvas, (width, height) in engine units (2 = the whole canvas side).
        Measured on JianYing 5.9 exports (1080x1920): a line is ~5.6 px per size unit tall, a character ~0.6 of that
        wide; lines wrap at 82% of the canvas width."""
        px = 5.6 * st["size"] * st["scale"] * min(self.W, self.H) / 1080
        char_w = 0.6 * px
        paras = str(txt).splitlines() or [""]
        rows = sum(max(1, math.ceil(len(p) * char_w / (0.82 * self.W))) for p in paras)
        width = min(0.82 * self.W, max(len(p) for p in paras) * char_w)
        return 2 * width / self.W, 2 * rows * px * 1.2 / self.H

    def frame_box(self, pos, txt, st):
        """Where a text sits in the frame: [x0, y0, x1, y1] as fractions (y down), for the verifier."""
        w, h = self.text_box(txt, st)
        cx, cy = (pos[0] + 1) / 2, (1 - pos[1]) / 2
        return [round(max(0.0, cx - w / 4), 3), round(max(0.0, cy - h / 4), 3), round(min(1.0, cx + w / 4), 3), round(min(1.0, cy + h / 4), 3)]

    def _safe_pos(self, pos, txt, st, where):
        """Keep a text inside the platform's safe zone."""
        w, h = self.text_box(txt, st)
        top, bottom = 1 - 2 * self.safe["top"], -1 + 2 * self.safe["bottom"]
        left, right = -1 + 2 * self.safe["left"], 1 - 2 * self.safe["right"]
        x, y = pos
        y2 = min(max(y, bottom + h / 2), top - h / 2) if top - bottom > h else (top + bottom) / 2
        x2 = min(max(x, left + w / 2), right - w / 2) if right - left > w else (left + right) / 2
        if abs(y2 - y) > 0.08 or abs(x2 - x) > 0.08:
            self.notes.append(f"{where}: moved into the safe zone ({x:.2f}, {y:.2f}) -> ({x2:.2f}, {y2:.2f})")
        return round(x2, 3), round(y2, 3)

    def _e_captions(self, e, where, items, texts, out):
        lines = [l for l in (e.get("lines") or e.get("items") or []) if isinstance(l, dict) and str(l.get("text") or "").strip()][:200]
        if not lines:
            return None
        r = self._base(e, "captions", "cap")
        st = self._style({"size": 7, **e}, where)
        pos = self._pos(e.get("position", "lower"), default=(0, -0.5))
        res = []
        for l in sorted(lines, key=lambda l: _n(l.get("start"), 0, 3600, 0)):
            a = _n(l.get("start"), 0, out["end"], 0)
            b = min(out["end"], max(a + 0.2, _n(l.get("end"), 0, 3600, a + 2)))
            if b - a >= 0.15:
                res.append({"text": str(l["text"]).strip()[:200], "start": round(a, 3), "end": round(b, 3)})
        r.update(
            lines=res,
            style=st,
            position=list(self._safe_pos(pos, max((x["text"] for x in res), key=len), st, where)),
            window=[res[0]["start"], res[-1]["end"]] if res else [0, 0],
            intro=None,
        )
        if e.get("intro"):
            r["intro"] = self.cat.resolve("text_intro", e.get("intro"), self.notes, where + ": ")
        r["expect"] = r["expect"] or "captions are visible, readable and match the words"
        return r

    def _e_audio(self, e, where, items, texts, out):
        a = self._media(e.get("file"), {"audio", "video"})
        if not a or (a["kind"] == "video" and not a.get("sound")):
            self.notes.append(f"{where}: '{e.get('file')}' is not an available sound file; skipped")
            return None
        src_len = max(0.0, (a.get("seconds") or (a.get("sound") or {}).get("seconds") or 0) - 0.05)
        at = _n(e.get("at", e.get("start")), 0, 3600, 0)
        src_from = _n(e.get("from"), 0, max(0, src_len - 0.3), 0)
        speed = _n(e.get("speed"), 0.25, 4, 1.0)
        dur = _n(e.get("duration"), 0.2, 3600, min(src_len - src_from, out["end"] - at) / speed)
        dur = min(dur, (src_len - src_from) / speed, max(0.2, out["end"] - at))
        if dur < 0.2:
            return None
        r = self._base(e, "audio", "au")
        r.update(
            file=a["file"],
            path=a["path"],
            at=round(at, 3),
            src_from=round(src_from, 3),
            duration=round(dur, 3),
            speed=speed,
            window=[round(at, 3), round(at + dur, 3)],
            volume=_n(e.get("volume"), 0, 4, 1.0),
            fade_in=_n(e.get("fade_in"), 0, 20, 0),
            fade_out=_n(e.get("fade_out"), 0, 20, 0),
            pitch_with_speed=bool(e.get("pitch_with_speed")),
        )
        if e.get("effect"):
            r["effect"] = self.cat.resolve(AUDIO_FX, e.get("effect"), self.notes, where + ": ")
            r["effect_params"] = self.cat.param_list(r["effect"], e.get("params"), self.notes, where + ": ") if r["effect"] else None
        pts = []
        for pnt in (e.get("keyframes") or [])[:40]:
            if isinstance(pnt, dict):
                pnt = [pnt.get("at"), pnt.get("value")]
            if isinstance(pnt, (list, tuple)) and len(pnt) >= 2:
                pts.append([round(_n(pnt[0], 0, dur, 0), 3), _n(pnt[1], 0, 4, 1)])
        if e.get("duck_under_speech"):
            pts = self._duck(r, out, pts)
        r["keyframes"] = sorted(pts)
        r["expect"] = r["expect"] or f"{a['file']} is audible from {at:.1f} s"
        return r

    def _e_sfx(self, e, where, items, texts, out):
        """A synthesised sound effect (sfx.py) at a moment: impacts start there, risers end there."""
        from ai_pc.media import sfx

        kind = str(e.get("sound") or e.get("name") or "").lower().strip().replace(" ", "_").replace("-", "_")
        kind = SFX_ALIASES.get(kind, kind)
        if kind not in sfx.KINDS:
            self.notes.append(f"{where}: unknown sound '{kind}' (known: {', '.join(sfx.KINDS)}); skipped")
            return None
        p, dur = sfx.path(kind), sfx.seconds(kind)
        t0, _, _ = self._window(e, items, texts, default_dur=dur)
        at = max(0.0, t0 - dur) if kind in sfx.ENDS_AT_MOMENT else t0
        dur = min(dur, out["end"] - at)
        if dur < 0.1:
            self.notes.append(f"{where}: {kind} at {t0:.1f} s is after the end; skipped")
            return None
        r = self._base(e, "audio", "sfx")
        r.update(
            file=p.name,
            path=str(p),
            at=round(at, 3),
            src_from=0.0,
            duration=round(dur, 3),
            speed=1.0,
            sfx=kind,
            window=[round(at, 3), round(at + dur, 3)],
            volume=_n(e.get("volume"), 0, 2, 0.9),
            keyframes=[],
            fade_in=0.0,
            fade_out=round(min(0.3, dur / 3), 3) if kind in ("impact", "thunder", "sub_drop") else 0.0,
        )
        r["expect"] = r["expect"] or f"a {kind.replace('_', ' ')} sound at {t0:.1f} s"
        return r

    def _duck(self, r, out, pts):
        """Volume keyframes that lower this track to 30% wherever a main clip's own sound is speech."""
        speech = []
        for c in out["clips"]:
            a = self._media(c["file"], {"video"})
            snd = (a or {}).get("sound") or {}
            if snd.get("kind") != "speech" or c["volume"] < 0.05:
                continue
            for pc in c["pieces"]:
                if pc["kind"] != "video":
                    continue
                quiet = snd.get("quiet", [])
                s0, s1 = pc["src_from"], pc["src_from"] + pc["src_span"]
                # talking = the piece minus the pauses
                segs, cur = [], s0
                for q0, q1 in quiet:
                    if q1 <= s0 or q0 >= s1:
                        continue
                    if q0 > cur:
                        segs.append((cur, q0))
                    cur = max(cur, q1)
                if cur < s1:
                    segs.append((cur, s1))
                for a0, a1 in segs:
                    speech.append((pc["start"] + (a0 - s0) / pc["speed"], pc["start"] + (a1 - s0) / pc["speed"]))
        if not speech:
            self.notes.append(f"edit {r['id']}: duck_under_speech: no speech in the clips; volume left as planned")
            return pts
        _v, low = r["volume"], 0.3
        for a0, a1 in speech:
            x0, x1 = a0 - r["at"], a1 - r["at"]
            if x1 <= 0 or x0 >= r["duration"]:
                continue
            for t, val in ((x0 - 0.25, 1.0), (x0, low), (x1, low), (x1 + 0.35, 1.0)):
                if 0 <= t <= r["duration"]:
                    pts.append([round(t, 3), round(val, 3)])
        r["ducked"] = len(speech)
        return pts


def resolve(plan, analyses, platform=None, catalog=None):
    return Resolver(plan, analyses, catalog, platform).resolve()


# keyframe signals used by the builder ---------------------------------------------------------------
def motion_keyframes(clip, edits, piece):
    """{property: [(seconds into the piece, value), ...]} for one piece of a clip: its base framing with every shake,
    zoom and keyframe edit on that clip folded in (scale multiplies, position adds), sampled where it changes."""
    st = clip["settings"]
    p0, p1 = piece["start"], piece["start"] + piece["dur"]
    mine = [
        e
        for e in edits
        if e.get("on") == clip["id"] and e["type"] in ("shake", "zoom", "keyframes") and e["window"][1] >= p0 - 1e-6 and e["window"][0] <= p1 + 1e-6
    ]
    if not mine:
        return {}
    times = {p0, p1}
    for e in mine:
        a, b = max(p0, e["window"][0]), min(p1, e["window"][1])
        if e["type"] == "shake":
            n = max(2, int((b - a) * 15))
            times.update(a + (b - a) * i / n for i in range(n + 1))
            times.update({max(p0, a - 0.04), min(p1, b + 0.04)})
        elif e["type"] == "zoom":
            n = max(3, int((b - a) * 8))
            times.update(a + (b - a) * i / n for i in range(n + 1))
            times.update({max(p0, a - 0.02)})
        else:
            times.update(clip["start"] + t for t, _ in e["points"] if p0 <= clip["start"] + t <= p1)
    times = sorted(t for t in times if p0 - 1e-6 <= t <= p1 + 1e-6)

    def kf_value(e, t):
        pts = e["points"]
        rel = t - clip["start"]
        if rel <= pts[0][0]:
            return pts[0][1]
        if rel >= pts[-1][0]:
            return pts[-1][1]
        for (ta, va), (tb, vb) in zip(pts, pts[1:]):
            if ta <= rel <= tb:
                return va + (vb - va) * (rel - ta) / max(1e-6, tb - ta)
        return pts[-1][1]

    props = {}
    used = {
        "scale": False,
        "x": False,
        "y": False,
        "rotation": False,
        "alpha": False,
        "brightness": False,
        "contrast": False,
        "saturation": False,
        "volume": False,
    }
    for e in mine:
        if e["type"] in ("shake", "zoom"):
            used["scale"] = True
            if e["type"] == "shake":
                used["x"] = used["y"] = True
        else:
            used[e["property"]] = True
    seed = (sum(ord(ch) for ch in clip["id"]) % 7) + 1
    for prop, on in used.items():
        if not on:
            continue
        vals = []
        for t in times:
            if prop == "scale":
                v = st["scale"]
                for e in mine:
                    if e["type"] == "zoom" and e["window"][0] - 1e-6 <= t:
                        v *= _zoom_factor(t - e["window"][0], e["window"][1] - e["window"][0], e["to"], e["back"])
                    elif e["type"] == "shake" and e["window"][0] - 0.04 <= t <= e["window"][1] + 0.04:
                        v *= 1 + 0.05 * e["strength"] + 0.04  # room to move without showing the edges
                    elif e["type"] == "keyframes" and e["property"] == "scale":
                        v *= kf_value(e, t)
            elif prop in ("x", "y"):
                v = st[prop]
                for e in mine:
                    if e["type"] == "shake":
                        dx, dy = _shake_offsets(t - e["window"][0], e["window"][1] - e["window"][0], 0.035 * e["strength"] + 0.01, seed)
                        v += dx if prop == "x" else dy
                    elif e["type"] == "keyframes" and e["property"] == prop:
                        v += kf_value(e, t)
            elif prop == "rotation":
                v = st["rotation"] + sum(kf_value(e, t) for e in mine if e["type"] == "keyframes" and e["property"] == "rotation")
            elif prop == "alpha":
                v = st["alpha"]
                for e in mine:
                    if e["type"] == "keyframes" and e["property"] == "alpha":
                        v = kf_value(e, t)
            elif prop == "volume":
                v = clip["volume"]
                for e in mine:
                    if e["type"] == "keyframes" and e["property"] == "volume":
                        v = clip["volume"] * kf_value(e, t)
            else:
                v = sum(kf_value(e, t) for e in mine if e["type"] == "keyframes" and e["property"] == prop)
            vals.append((round(t - p0, 4), round(v, 4)))
        props[prop] = vals
    return props
