"""JianYing lane: a complex edit request in plain words -> ONE model call -> a checked JSON plan -> a JianYing 5.9 project
written by pyJianYingDraft. No clicking, and no model-written code is ever run.

Covers what JianYing offers through pyJianYingDraft: several video tracks (picture-in-picture), speed, volume, position /
scale / rotation / opacity, keyframes, masks, blend modes, filters, effects, clip in/out/combo animations, transitions,
audio fades, separate filter and effect tracks, titles (font, outline, background, shadow, in/out/loop animations,
keyframes), subtitles, music with fades, volume keyframes and voice/scene effects. Free (non-VIP) items only.

Safety: same rules as the CapCut video lane (video_lane.py): files only from the project's media/ folder, every name
checked against the free catalogue, numbers clamped, projects written only as agent_<word>_<HHMMSS> drafts. Every
feature is applied in its own guard, so one bad item becomes a note instead of a failed build.
"""
import difflib
import json
import os
import re
import time
from pathlib import Path

import pyJianYingDraft as jy
from pyJianYingDraft import SEC, trange

from .config import ROOT

DRAFTS = Path(os.environ["LOCALAPPDATA"]) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
MEDIA = ROOT / "media"
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
CANVAS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
POS = {"top": (0, 0.75), "center": (0, 0), "middle": (0, 0), "bottom": (0, -0.8), "upper": (0, 0.45), "lower": (0, -0.45),
       "top_left": (-0.6, 0.75), "top_right": (0.6, 0.75), "bottom_left": (-0.6, -0.8), "bottom_right": (0.6, -0.8),
       "lower_left": (-0.55, -0.55), "lower_right": (0.55, -0.55)}
MASKS = {"linear": "线性", "mirror": "镜面", "circle": "圆形", "rectangle": "矩形", "rect": "矩形", "heart": "爱心", "star": "星形"}
BLENDS = {"multiply": "正片叠底", "color dodge": "颜色减淡", "color burn": "颜色加深", "linear burn": "线性加深",
          "soft light": "柔光", "hard light": "强光", "screen": "滤色", "overlay": "叠加", "lighten": "变亮", "darken": "变暗"}
KF = {"scale": "uniform_scale", "uniform_scale": "uniform_scale", "x": "position_x", "position_x": "position_x",
      "y": "position_y", "position_y": "position_y", "rotation": "rotation", "alpha": "alpha", "opacity": "alpha",
      "brightness": "brightness", "contrast": "contrast", "saturation": "saturation", "volume": "volume"}
KF_RANGE = {"uniform_scale": (0.05, 10), "position_x": (-3, 3), "position_y": (-3, 3), "rotation": (-3600, 3600),
            "alpha": (0, 1), "brightness": (-1, 1), "contrast": (-1, 1), "saturation": (-1, 1), "volume": (0, 2)}


def _free(enum):
    return {m.name: m for m in enum if not getattr(m.value, "is_vip", False) and m.name.lower() != "undefined"}


CAT = {"filter": _free(jy.FilterType), "transition": _free(jy.TransitionType), "scene_effect": _free(jy.VideoSceneEffectType),
       "character_effect": _free(jy.VideoCharacterEffectType), "intro": _free(jy.IntroType), "outro": _free(jy.OutroType),
       "combo": _free(jy.GroupAnimationType), "text_intro": _free(jy.TextIntro), "text_outro": _free(jy.TextOutro),
       "text_loop": _free(jy.TextLoopAnim), "font": _free(jy.FontType), "tone": _free(jy.ToneEffectType),
       "audio_scene": _free(jy.AudioSceneEffectType)}
# how many names of each kind the planner is shown (the whole free catalogue would be ~2,700 names)
SHOWN = {"filter": 60, "transition": 50, "scene_effect": 70, "intro": 40, "outro": 25, "combo": 30, "text_intro": 45,
         "text_outro": 35, "text_loop": 30, "font": 45, "tone": 14, "audio_scene": 12}


def _shown(kind):
    names = list(CAT[kind])
    n = SHOWN[kind]
    if kind == "font":  # prefer readable Latin fonts plus a few Chinese ones
        latin = [x for x in names if x.isascii()]
        return latin[:n - 10] + [x for x in names if not x.isascii()][:10]
    step = max(1, len(names) // n)
    return names[::step][:n]


def find(kind, wanted, notes, where=""):
    """Exact free catalogue member for a planner-chosen name (or the closest name of that kind)."""
    if not wanted:
        return None
    items = CAT[kind]
    w = str(wanted).strip()
    if w in items:
        return items[w]
    low = {k.lower(): k for k in items}
    if w.lower() in low:
        return items[low[w.lower()]]
    best = difflib.get_close_matches(w, list(items), n=1, cutoff=0.5)
    if best:
        notes.append(f"{where}{kind} {w!r} -> {best[0]!r}")
        return items[best[0]]
    notes.append(f"{where}no free {kind} named {w!r}; skipped")
    return None


def media_files():
    out = []
    for p in sorted(MEDIA.iterdir()) if MEDIA.is_dir() else []:
        ext = p.suffix.lower()
        try:
            if ext in VIDEO_EXT:
                m = jy.VideoMaterial(str(p))
                out.append({"file": p.name, "kind": "video", "seconds": round(m.duration / SEC, 1), "size": f"{m.width}x{m.height}", "path": str(p)})
            elif ext in IMAGE_EXT:
                m = jy.VideoMaterial(str(p))
                out.append({"file": p.name, "kind": "image", "seconds": None, "size": f"{m.width}x{m.height}", "path": str(p)})
            elif ext in AUDIO_EXT:
                m = jy.AudioMaterial(str(p))
                out.append({"file": p.name, "kind": "audio", "seconds": round(m.duration / SEC, 1), "path": str(p)})
        except Exception:  # noqa: BLE001
            continue
    return out


def _file(name, kinds, files):
    want = Path(str(name or "")).name.lower()
    return next((f for f in files if f["file"].lower() == want and f["kind"] in kinds), None)


def _n(v, lo, hi, d):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return min(max(x, lo), hi)


def _rgb(v, d=(1.0, 1.0, 1.0)):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(v or "").strip())
    return tuple(int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4)) if m else d


def _hex(v, d="#000000"):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(v or "").strip())
    return "#" + m.group(1).upper() if m else d


def _pos(v):
    if isinstance(v, str) and v.lower() in POS:
        return POS[v.lower()]
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return _n(v[0], -2, 2, 0), _n(v[1], -2, 2, 0)
    return None


def draft_name(name):
    word = re.sub(r"[^a-z0-9]+", "", str(name or "").lower().removeprefix("agent_").split("_")[0])[:10] or "edit"
    return f"agent_{word}_{time.strftime('%H%M%S')}"


def _guard(notes, label, fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001  (one bad feature must not sink the build)
        notes.append(f"{label}: {type(e).__name__}: {str(e)[:80]}")
        return None


def _keyframes(seg, kfs, dur_us, notes, where, stats):
    audio = isinstance(seg, jy.AudioSegment)  # audio clips only take volume keyframes: add_keyframe(time, volume)
    for k in (kfs or [])[:12]:
        prop = KF.get(str(k.get("property", "")).lower())
        if not prop or (audio and prop != "volume"):
            notes.append(f"{where}unknown keyframe property {k.get('property')!r}")
            continue
        lo, hi = KF_RANGE[prop]
        at = round(_n(k.get("at"), 0, dur_us / SEC, 0) * SEC)
        val = _n(k.get("value"), lo, hi, (lo + hi) / 2)
        args = (at, val) if audio else (getattr(jy.KeyframeProperty, prop), at, val)
        if _guard(notes, f"{where}keyframe", seg.add_keyframe, *args) is not None:
            stats["keyframes"] += 1


def _video_seg(s, start_us, f, notes, where, stats, canvas):
    speed = 1.0 if f["kind"] == "image" else _n(s.get("speed"), 0.25, 4.0, 1.0)
    src_from = 0 if f["kind"] == "image" else _n(s.get("from"), 0, max(0, f["seconds"] - 0.5), 0)
    dur = _n(s.get("duration"), 0.5, 120, 3)
    if f["kind"] == "video" and src_from + dur * speed > f["seconds"]:
        dur = max(0.5, (f["seconds"] - src_from) / speed)
        notes.append(f"{where}shortened to {dur:.1f} s (file length)")
    dur_us = round(dur * SEC)
    pos = _pos(s.get("position")) or (0, 0)
    sc = _n(s.get("scale"), 0.05, 10, 1.0)
    cs = jy.ClipSettings(transform_x=pos[0], transform_y=pos[1], scale_x=sc, scale_y=sc,
                         rotation=_n(s.get("rotation"), -360, 360, 0), alpha=_n(s.get("alpha"), 0, 1, 1))
    if f["kind"] == "image":
        seg = jy.VideoSegment(f["path"], trange(start_us, dur_us), clip_settings=cs)
    else:
        seg = jy.VideoSegment(f["path"], trange(start_us, dur_us), source_timerange=trange(round(src_from * SEC), round(dur * speed * SEC)),
                              speed=speed, volume=_n(s.get("volume"), 0, 2, 1.0), clip_settings=cs)
    flt = find("filter", s.get("filter"), notes, where)
    if flt and _guard(notes, f"{where}filter", seg.add_filter, flt, _n(s.get("filter_strength"), 0, 100, 80)) is not None:
        stats["filters"] += 1
    for e in (s.get("effects") or [])[:3]:
        eff = find("scene_effect", e, [], where) or find("character_effect", e, notes, where)
        if eff and _guard(notes, f"{where}effect", seg.add_effect, eff) is not None:
            stats["effects"] += 1
    for kind in ("intro", "outro", "combo"):
        a = find(kind, s.get(kind), notes, where)
        if a:
            d = s.get(f"{kind}_duration")
            if _guard(notes, f"{where}{kind}", seg.add_animation, a, round(_n(d, 0.1, dur, 0.5) * SEC) if d else None) is not None:
                stats["animations"] += 1
    m = s.get("mask")
    if isinstance(m, dict) and m.get("type"):
        mt = MASKS.get(str(m["type"]).lower(), m["type"])
        mask = next((x for x in jy.MaskType if x.name == mt), None)
        if mask:
            c = _pos(m.get("center")) or (0, 0)
            kw = dict(center_x=c[0], center_y=c[1], size=_n(m.get("size"), 0.05, 2, 0.5), rotation=_n(m.get("rotation"), -360, 360, 0),
                      feather=_n(m.get("feather"), 0, 100, 0), invert=bool(m.get("invert")))
            if mt == "矩形":
                kw.update(rect_width=_n(m.get("rect_width"), 0.05, 2, kw["size"]), round_corner=_n(m.get("round_corner"), 0, 100, 0))
            if _guard(notes, f"{where}mask", seg.add_mask, mask, **kw) is not None:
                stats["masks"] += 1
        else:
            notes.append(f"{where}unknown mask {m['type']!r}")
    if s.get("blend"):
        mm = BLENDS.get(str(s["blend"]).lower(), s["blend"])
        mode = next((x for x in jy.MixModeType if x.name == mm), None)
        if mode and _guard(notes, f"{where}blend", seg.set_mix_mode, mode) is not None:
            stats["blends"] += 1
    if str(s.get("fill") or "").lower() == "blur" and f.get("size"):
        fw, fh = (int(x) for x in f["size"].split("x"))
        if abs(fw / fh - canvas[0] / canvas[1]) > 0.02:
            _guard(notes, f"{where}fill", seg.add_background_filling, "blur", 0.0625)
    fi, fo = _n(s.get("fade_in"), 0, 5, 0), _n(s.get("fade_out"), 0, 5, 0)
    if (fi or fo) and f["kind"] == "video":
        _guard(notes, f"{where}audio fade", seg.add_fade, round(fi * SEC), round(fo * SEC))
    _keyframes(seg, s.get("keyframes"), dur_us, notes, where, stats)
    return seg, dur_us


def build(plan, files=None):
    t0 = time.perf_counter()
    files = files if files is not None else media_files()
    notes = []
    stats = dict.fromkeys(["video_segments", "transitions", "filters", "effects", "animations", "masks", "blends",
                           "keyframes", "texts", "text_animations", "subtitles", "audio_segments", "audio_effects",
                           "track_effects", "track_filters"], 0)
    name = draft_name(plan.get("name"))
    canvas = CANVAS.get(str(plan.get("canvas", "16:9")), CANVAS["16:9"])
    script = jy.DraftFolder(str(DRAFTS)).create_draft(name, canvas[0], canvas[1], 30, allow_replace=name.startswith("agent_"))
    tracks = []

    # ---- video tracks: the first is the main track (laid end to end, with transitions); the rest are overlays
    vtracks = [t for t in (plan.get("video_tracks") or []) if isinstance(t, dict)][:4]
    built_v = []
    end_us = 0
    for ti, t in enumerate(vtracks):
        tname = "main" if ti == 0 else f"overlay{ti}"
        segs, cursor, last_end = [], 0, 0
        for si, s in enumerate((t.get("segments") or [])[:40]):
            where = f"{tname} #{si + 1}: "
            f = _file(s.get("file"), {"video", "image"}, files)
            if not f:
                notes.append(f"{where}{s.get('file')!r} is not an available video/photo; skipped")
                continue
            start = cursor if ti == 0 else round(_n(s.get("at"), 0, 3600, 0) * SEC)
            if ti > 0 and start < last_end:
                if last_end - start < 0.5 * SEC:
                    start = last_end
                else:
                    notes.append(f"{where}overlaps the previous overlay clip; skipped")
                    continue
            seg_dur = _guard(notes, where.rstrip(": "), _video_seg, s, start, f, notes, where, stats, canvas)
            if not seg_dur:
                continue
            seg, dur_us = seg_dur
            segs.append((s, seg, dur_us))
            last_end = start + dur_us
            cursor = last_end
        if ti == 0:
            for i in range(len(segs) - 1):
                s, seg, dur_us = segs[i]
                tr = find("transition", s.get("transition"), notes, f"main #{i + 1}: ")
                if tr:
                    td = min(_n(s.get("transition_duration"), 0.1, 2, 0.5), dur_us / SEC / 2, segs[i + 1][2] / SEC / 2)
                    if _guard(notes, f"main #{i + 1}: transition", seg.add_transition, tr, duration=round(td * SEC)) is not None:
                        stats["transitions"] += 1
        built_v.append((tname, segs))
        end_us = max(end_us, last_end)
    if not built_v or not built_v[0][1]:
        raise ValueError("the plan has no usable main-track clips: " + "; ".join(notes[:5]))

    # ---- audio
    auds = []
    for ai, a in enumerate((plan.get("audio") or [])[:8]):
        where = f"audio #{ai + 1}: "
        f = _file(a.get("file"), {"audio"}, files)
        if not f:
            notes.append(f"{where}{a.get('file')!r} is not an available audio file; skipped")
            continue
        src_from = _n(a.get("from"), 0, max(0, f["seconds"] - 0.5), 0)
        dur = min(_n(a.get("duration"), 0.5, 600, f["seconds"]), f["seconds"] - src_from)
        at = round(_n(a.get("at"), 0, 3600, 0) * SEC)
        seg = _guard(notes, where.rstrip(": "), jy.AudioSegment, f["path"], trange(at, round(dur * SEC)),
                     source_timerange=trange(round(src_from * SEC), round(dur * SEC)), volume=_n(a.get("volume"), 0, 2, 0.6))
        if not seg:
            continue
        fi, fo = _n(a.get("fade_in"), 0, 10, 0), _n(a.get("fade_out"), 0, 10, 0)
        if fi or fo:
            _guard(notes, f"{where}fade", seg.add_fade, round(fi * SEC), round(fo * SEC))
        for kind, key in (("tone", "tone"), ("audio_scene", "scene_effect")):
            e = find(kind, a.get(key), notes, where)
            if e and _guard(notes, f"{where}{kind}", seg.add_effect, e) is not None:
                stats["audio_effects"] += 1
        _keyframes(seg, a.get("keyframes"), round(dur * SEC), notes, where, stats)
        auds.append((at, at + round(dur * SEC), seg))
    # audio clips that overlap go to separate tracks
    a_tracks = []
    for at, end, seg in sorted(auds, key=lambda x: x[0]):
        for tr in a_tracks:
            if tr[-1][1] <= at:
                tr.append((at, end, seg))
                break
        else:
            a_tracks.append([(at, end, seg)])

    # ---- tracks are created in drawing order: audio, video (main, overlays), filter, effect, titles, subtitles
    for i in range(len(a_tracks)):
        script.append_track(jy.TrackSpec(jy.TrackType.audio, f"audio{i + 1}"))
    for tname, _ in built_v:
        script.append_track(jy.TrackSpec(jy.TrackType.video, tname))
    for i, tr in enumerate(a_tracks):
        for _, _, seg in tr:
            if _guard(notes, f"audio track {i + 1}", script.add_segment, seg, f"audio{i + 1}") is not None:
                stats["audio_segments"] += 1
    for tname, segs in built_v:
        for s, seg, _ in segs:
            if _guard(notes, f"{tname} add", script.add_segment, seg, tname) is not None:
                stats["video_segments"] += 1

    looks = [x for x in (plan.get("filter_track") or []) if isinstance(x, dict)][:10]
    if looks:
        script.append_track(jy.TrackSpec(jy.TrackType.filter, "looks"))
        for i, x in enumerate(looks):
            flt = find("filter", x.get("name"), notes, f"filter track #{i + 1}: ")
            if flt:
                tr_ = trange(round(_n(x.get("start"), 0, 3600, 0) * SEC), round(_n(x.get("duration"), 0.3, 600, 2) * SEC))
                if _guard(notes, f"filter track #{i + 1}", script.add_filter, flt, tr_, "looks", _n(x.get("strength"), 0, 100, 80)) is not None:
                    stats["track_filters"] += 1
    fx = [x for x in (plan.get("effect_track") or []) if isinstance(x, dict)][:10]
    if fx:
        script.append_track(jy.TrackSpec(jy.TrackType.effect, "fx"))
        for i, x in enumerate(fx):
            e = find("scene_effect", x.get("name"), notes, f"effect track #{i + 1}: ")
            if e:
                tr_ = trange(round(_n(x.get("start"), 0, 3600, 0) * SEC), round(_n(x.get("duration"), 0.3, 600, 2) * SEC))
                if _guard(notes, f"effect track #{i + 1}", script.add_effect, e, tr_, "fx") is not None:
                    stats["track_effects"] += 1

    # ---- titles: texts that overlap in time go to separate text tracks
    texts = []
    for i, t in enumerate((plan.get("texts") or [])[:30]):
        where = f"text #{i + 1}: "
        txt = str(t.get("text") or "").strip()[:300]
        if not txt:
            continue
        st = round(_n(t.get("start"), 0, 3600, 0) * SEC)
        du = round(_n(t.get("duration"), 0.3, 600, 3) * SEC)
        pos = _pos(t.get("position")) or POS["bottom"]
        sc = _n(t.get("scale"), 0.1, 10, 1.0)
        style = jy.TextStyle(size=_n(t.get("size"), 2, 30, 8), bold=bool(t.get("bold")), italic=bool(t.get("italic")),
                             color=_rgb(t.get("color")), alpha=_n(t.get("alpha"), 0, 1, 1), align=1, auto_wrapping=True)
        b = t.get("outline")
        border = jy.TextBorder(color=_rgb(b.get("color"), (0, 0, 0)), width=_n(b.get("width"), 0, 100, 40)) if isinstance(b, dict) else None
        bg = t.get("background")
        background = jy.TextBackground(color=_hex(bg.get("color")), alpha=_n(bg.get("alpha"), 0, 1, 0.6),
                                       round_radius=_n(bg.get("round_radius"), 0, 1, 0.2)) if isinstance(bg, dict) else None
        shadow = jy.TextShadow(alpha=0.6) if t.get("shadow") else None
        seg = _guard(notes, where.rstrip(": "), jy.TextSegment, txt, trange(st, du), font=find("font", t.get("font"), notes, where),
                     style=style, clip_settings=jy.ClipSettings(transform_x=pos[0], transform_y=pos[1], scale_x=sc, scale_y=sc,
                                                                 rotation=_n(t.get("rotation"), -360, 360, 0)),
                     border=border, background=background, shadow=shadow)
        if not seg:
            continue
        for kind in ("text_intro", "text_outro", "text_loop"):
            key = {"text_intro": "intro", "text_outro": "outro", "text_loop": "loop"}[kind]
            a = find(kind, t.get(key), notes, where)
            if a:
                d = t.get(f"{key}_duration")
                if _guard(notes, f"{where}{key}", seg.add_animation, a, round(_n(d, 0.1, du / SEC, 0.6) * SEC) if d else None) is not None:
                    stats["text_animations"] += 1
        _keyframes(seg, t.get("keyframes"), du, notes, where, stats)
        texts.append((st, st + du, seg))
    t_tracks = []
    for st, en, seg in sorted(texts, key=lambda x: x[0]):
        for tr in t_tracks:
            if tr[-1][1] <= st:
                tr.append((st, en, seg))
                break
        else:
            t_tracks.append([(st, en, seg)])
    for i, tr in enumerate(t_tracks):
        script.append_track(jy.TrackSpec(jy.TrackType.text, f"titles{i + 1}"))
        for _, _, seg in tr:
            if _guard(notes, f"titles{i + 1}", script.add_segment, seg, f"titles{i + 1}") is not None:
                stats["texts"] += 1

    # ---- subtitles: written as an .srt inside the project, then imported
    subs = [s for s in (plan.get("subtitles") or []) if isinstance(s, dict) and str(s.get("text") or "").strip()][:80]
    if subs:
        def ts(x):
            ms = int(round(x * 1000))
            return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        lines = []
        for i, s in enumerate(sorted(subs, key=lambda s: _n(s.get("start"), 0, 3600, 0))):
            a = _n(s.get("start"), 0, 3600, 0)
            b = max(a + 0.3, _n(s.get("end"), 0, 3600, a + 2))
            lines += [str(i + 1), f"{ts(a)} --> {ts(b)}", str(s["text"]).strip()[:200], ""]
        srt = ROOT / "out" / "video" / "plans" / f"{name}.srt"
        srt.parent.mkdir(parents=True, exist_ok=True)
        srt.write_text("\n".join(lines), encoding="utf-8")
        script.append_track(jy.TrackSpec(jy.TrackType.text, "subtitles"))
        if _guard(notes, "subtitles", script.import_srt, str(srt), "subtitles",
                  text_style=jy.TextStyle(size=6, color=(1, 1, 1), align=1, auto_wrapping=True),
                  clip_settings=jy.ClipSettings(transform_y=-0.86)) is not None:
            stats["subtitles"] = len(subs)

    script.save()
    return {"draft": name, "path": str(DRAFTS / name), "seconds": round(script.duration / SEC, 2),
            "tracks": len(a_tracks) + len(built_v) + bool(looks) + bool(fx) + len(t_tracks) + bool(subs),
            "stats": stats, "notes": notes, "ms": round((time.perf_counter() - t0) * 1000)}


PLAN_SYSTEM = """You plan video edits for JianYing (CapCut's Chinese edition). You never write code: output ONE compact JSON object (the plan), nothing else.

Plan format (all times in seconds; positions are [x, y] with 0,0 = centre, x from -1 left to 1 right, y from -1 bottom to 1 top, or one of top/center/bottom/top_left/top_right/bottom_left/bottom_right/lower_left/lower_right):
{"name": "short_name", "canvas": "16:9"|"9:16"|"1:1"|"4:5",
 "video_tracks": [
   {"segments": [ MAIN TRACK: clips play back to back in order
      {"file": "<AVAILABLE MEDIA video or photo>", "from": <start in the source>, "duration": <seconds on the timeline>,
       "speed": 1.0, "volume": 1.0, "position": [0,0], "scale": 1.0, "rotation": 0, "alpha": 1.0,
       "filter": "<FILTERS>", "filter_strength": 80, "effects": ["<EFFECTS>"],
       "intro": "<CLIP INTROS>", "outro": "<CLIP OUTROS>", "combo": "<CLIP COMBOS>",
       "transition": "<TRANSITIONS: into the next clip>", "transition_duration": 0.5,
       "fill": "blur", "fade_in": 0, "fade_out": 0,
       "mask": {"type": "circle|rectangle|heart|star|linear|mirror", "center": [0,0], "size": 0.5, "feather": 20, "round_corner": 30, "rect_width": 0.5},
       "blend": "screen|multiply|overlay|soft light|hard light|lighten|darken|color dodge|color burn|linear burn",
       "keyframes": [{"property": "scale|x|y|rotation|alpha|brightness|contrast|saturation|volume", "at": <seconds into the clip>, "value": <number>}]}]},
   {"segments": [ OVERLAY TRACK (drawn on top, picture-in-picture): same fields plus "at": <start on the timeline>]}],
 "filter_track": [{"name": "<FILTERS>", "start": 0, "duration": 5, "strength": 80}],
 "effect_track": [{"name": "<EFFECTS>", "start": 0, "duration": 3}],
 "texts": [{"text": "...", "start": 0, "duration": 3, "position": "center", "size": 10, "color": "#FFFFFF", "bold": true,
            "font": "<FONTS>", "outline": {"color": "#000000", "width": 40}, "background": {"color": "#000000", "alpha": 0.5},
            "shadow": true, "intro": "<TEXT INTROS>", "outro": "<TEXT OUTROS>", "loop": "<TEXT LOOPS>", "keyframes": [...]}],
 "subtitles": [{"start": 0, "end": 2.5, "text": "..."}],
 "audio": [{"file": "<AVAILABLE MEDIA audio>", "at": 0, "from": 0, "duration": 10, "volume": 0.6, "fade_in": 1, "fade_out": 1,
            "tone": "<VOICE EFFECTS>", "scene_effect": "<AUDIO EFFECTS>", "keyframes": [{"property": "volume", "at": 0, "value": 0.3}]}]}

Rules: copy names EXACTLY from the lists (they are the free items). Keep "from" + duration*speed inside each video's length. Overlay clips should usually be scaled down (e.g. 0.3) and positioned. Scale keyframes are factors (1.0 = normal); position keyframes use the position units. Omit fields you do not need. Output compact JSON without comments."""


def plan_prompt(request, files):
    media = "\n".join(f"- {f['file']} ({f['kind']}" + (f", {f['seconds']} s" if f.get("seconds") else "") +
                      (f", {f['size']}" if f.get("size") else "") + ")" for f in files)
    labels = {"filter": "FILTERS", "transition": "TRANSITIONS", "scene_effect": "EFFECTS", "intro": "CLIP INTROS",
              "outro": "CLIP OUTROS", "combo": "CLIP COMBOS", "text_intro": "TEXT INTROS", "text_outro": "TEXT OUTROS",
              "text_loop": "TEXT LOOPS", "font": "FONTS", "tone": "VOICE EFFECTS", "audio_scene": "AUDIO EFFECTS"}
    cat = "\n".join(f"{labels[k]}: {', '.join(_shown(k))}" for k in labels)
    return f"REQUEST:\n{request}\n\nAVAILABLE MEDIA:\n{media}\n\n{cat}\n\nReply with the plan JSON only."


def make_plan(request, planner, files=None, tier="video"):
    from .planner import PlannerError
    from .util import parse_json
    files = files if files is not None else media_files()
    msgs = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": plan_prompt(request, files)}]
    t0 = time.perf_counter()
    r = planner._call(tier, msgs)
    plan = parse_json(r.text)
    if not isinstance(plan, dict):
        raise PlannerError(f"no JSON plan in the reply ({len(r.text)} chars)")
    return plan, round((time.perf_counter() - t0) * 1000), r.usage


def save(request, plan, result):
    d = ROOT / "out" / "video" / "plans"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{result.get('draft', 'plan')}.json"
    p.write_text(json.dumps({"request": request, "plan": plan, "result": result}, indent=1, ensure_ascii=False), encoding="utf-8")
    return p
