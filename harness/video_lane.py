"""Video lane: an edit request in plain words -> a checked JSON edit plan -> a CapCut project written by pyCapCut.

The edit itself needs no clicking, and no model-written code is ever run:
  1. plan   one fast model call turns the request into a JSON plan (format in PLAN_SYSTEM), given the media files
            that are available and the free catalogue items that load in this CapCut (the English-named ones);
  2. check  every field is validated here (files, names, numbers); anything unknown is dropped with a note;
  3. build  only this module calls pyCapCut. Projects are written as CapCut drafts named agent_<name>.

Safety (pyCapCut's create_draft(allow_replace=True) deletes a same-named folder and does not sanitise the name):
names are reduced to agent_[a-z0-9_-] (no path separators), and only folders whose name starts with agent_ are ever
replaced. Media files are only read, and only from MEDIA_DIRS. Plans and logs stay inside this project.
"""
import difflib
import json
import os
import re
import time
from pathlib import Path

import pycapcut as cc
from pycapcut import SEC, trange

from .config import ROOT

DRAFTS = Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
MEDIA_DIRS = [ROOT / "media"]  # only files the user put in the project's media folder are visible (and sent to the planner)
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".png", ".jpg", ".jpeg", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
CANVAS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
POSITION = {"top": 0.75, "upper": 0.4, "center": 0.0, "middle": 0.0, "lower": -0.4, "bottom": -0.75}


def _free_english(enum):
    """Free (non-Pro) catalogue items with English names: in CapCut 9.5 these loaded; Chinese-named animations
    from pyCapCut's JianYing-derived catalogue showed 'Animation loss'."""
    return {m.name: m for m in enum if not getattr(m.value, "is_vip", False) and m.name.isascii()
            and m.name.lower() != "undefined"}


CATALOG = {"filter": _free_english(cc.FilterType), "transition": _free_english(cc.TransitionType),
           "effect": _free_english(cc.VideoSceneEffectType), "font": _free_english(cc.FontType)}


def _key(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def match(kind, wanted):
    """Closest free catalogue item for a wanted name ('retro', 'white flash'); (member or None, note)."""
    if not wanted:
        return None, ""
    items = CATALOG[kind]
    by_key = {_key(n): n for n in items}
    k = _key(wanted)
    if k in by_key:
        return items[by_key[k]], ""
    sub = [n for kk, n in by_key.items() if k and (k in kk or kk in k)]
    best = sub[0] if sub else (difflib.get_close_matches(k, list(by_key), n=1, cutoff=0.55) or [None])[0]
    if best is None:
        return None, f"no free {kind} like {wanted!r}; skipped"
    name = best if best in items else by_key[best]
    return items[name], f"{kind} {wanted!r} -> {name}"


def media_files():
    """The media the planner may use: name, kind, duration, size. Read-only."""
    out = []
    for d in MEDIA_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            ext = p.suffix.lower()
            if not p.is_file() or ext not in VIDEO_EXT | AUDIO_EXT:
                continue
            try:
                if ext in AUDIO_EXT:
                    m = cc.AudioMaterial(str(p))
                    out.append({"file": p.name, "kind": "audio", "seconds": round(m.duration / SEC, 1), "path": str(p)})
                else:
                    m = cc.VideoMaterial(str(p))
                    kind = "image" if ext in {".png", ".jpg", ".jpeg"} else "video"
                    out.append({"file": p.name, "kind": kind,
                                "seconds": 5.0 if kind == "image" else round(m.duration / SEC, 1),
                                "size": f"{m.width}x{m.height}", "path": str(p)})
            except Exception:  # noqa: BLE001  (unreadable or odd media is simply not offered)
                continue
    return out


def _resolve(name, kinds, files):
    """A plan's file reference -> an allowed, existing media entry (by bare name; paths must be inside MEDIA_DIRS)."""
    want = Path(str(name)).name.lower()
    for f in files:
        if f["file"].lower() == want and f["kind"] in kinds:
            p = Path(f["path"]).resolve()
            if any(str(p).lower().startswith(str(d.resolve()).lower() + os.sep) for d in MEDIA_DIRS):
                return f
    return None


def _num(v, lo, hi, default):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(x, lo), hi)


def _color(v, default=(1.0, 1.0, 1.0)):
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(v or "").strip())
    if not m:
        return default
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def draft_name(name):
    """agent_<word>_<HHMMSS>: short and unique, because CapCut cuts long names in its project list, and two names with
    the same beginning ('agent_youtube_intro', 'agent_youtube_intro_eclosion') look identical there to a click model."""
    word = re.sub(r"[^a-z0-9]+", "", str(name or "").lower().removeprefix("agent_").split("_")[0])[:10] or "edit"
    return f"agent_{word}_{time.strftime('%H%M%S')}"


def build(plan, files=None):
    """Validate a plan and write it as a CapCut draft. Returns {draft, path, seconds, notes, ms}. Raises ValueError
    when nothing usable is left."""
    t0 = time.perf_counter()
    files = files if files is not None else media_files()
    notes = []
    name = draft_name(plan.get("name"))
    target = DRAFTS / name
    if target.exists() and not name.startswith("agent_"):  # cannot happen (draft_name forces the prefix); belt and braces
        raise ValueError(f"refusing to replace {name}")
    w, h = CANVAS.get(str(plan.get("canvas", "16:9")), CANVAS["16:9"])

    clips = []
    for i, c in enumerate((plan.get("clips") or [])[:20]):
        f = _resolve(c.get("file"), {"video", "image"}, files)
        if not f:
            notes.append(f"clip {i + 1}: file {c.get('file')!r} is not an available media file; skipped")
            continue
        total = f["seconds"]
        start = _num(c.get("from"), 0, max(0, total - 0.5), 0)
        speed = _num(c.get("speed"), 0.25, 4.0, 1.0)
        dur = _num(c.get("duration"), 0.5, 600, min(5.0, total - start))
        if f["kind"] == "video" and start + dur * speed > total:
            dur = max(0.5, (total - start) / speed)
            notes.append(f"clip {i + 1}: shortened to {dur:.1f} s (the file is {total:.1f} s long)")
        clips.append((c, f, start, dur, speed))
    if not clips:
        raise ValueError("the plan has no usable clips: " + "; ".join(notes))

    folder = cc.DraftFolder(str(DRAFTS))
    script = folder.create_draft(name, w, h, allow_replace=name.startswith("agent_"))
    script.add_track(cc.TrackType.video).add_track(cc.TrackType.text)
    cursor = 0
    segs = []
    for i, (c, f, start, dur, speed) in enumerate(clips):
        mat = cc.VideoMaterial(f["path"])
        if f["kind"] == "image":
            seg = cc.VideoSegment(mat, trange(cursor, round(dur * SEC)))
        else:
            seg = cc.VideoSegment(mat, trange(cursor, round(dur * SEC)), source_timerange=trange(round(start * SEC), round(dur * speed * SEC)),
                                  speed=speed, volume=_num(c.get("volume"), 0, 2, 1.0))
        flt, n = match("filter", c.get("filter"))
        notes += [n] if n else []
        if flt:
            seg.add_filter(flt, _num(c.get("filter_strength"), 0, 100, 80))
        eff, n = match("effect", c.get("effect"))
        notes += [n] if n else []
        if eff:
            seg.add_effect(eff)
        zoom = str(c.get("zoom") or "").lower()
        if zoom in ("in", "out"):
            a, b = (1.0, 1.15) if zoom == "in" else (1.15, 1.0)
            seg.add_keyframe(cc.KeyframeProperty.uniform_scale, 0, a)
            seg.add_keyframe(cc.KeyframeProperty.uniform_scale, seg.target_timerange.duration, b)
        if str(c.get("fill") or "").lower() == "blur" and f.get("size"):
            fw, fh = (int(x) for x in f["size"].split("x"))
            if abs(fw / fh - w / h) > 0.02:
                seg.add_background_filling("blur", 0.0625)
        if i < len(clips) - 1 and c.get("transition"):
            tr, n = match("transition", c.get("transition"))
            notes += [n] if n else []
            if tr:
                td = _num(c.get("transition_duration"), 0.2, 2.0, 0.5)
                td = min(td, dur / 2, clips[i + 1][3] / 2)
                seg.add_transition(tr, duration=round(td * SEC))
        segs.append(seg)
        cursor = seg.target_timerange.start + seg.target_timerange.duration
    for seg in segs:
        script.add_segment(seg)
    total_us = cursor

    for j, t in enumerate((plan.get("texts") or [])[:10]):
        text = str(t.get("text") or "").strip()[:200]
        if not text:
            continue
        st = round(_num(t.get("start"), 0, max(0, total_us / SEC - 0.5), 0) * SEC)
        du = round(_num(t.get("duration"), 0.5, 600, 3) * SEC)
        du = max(int(0.5 * SEC), min(du, total_us - st))
        font, n = match("font", t.get("font"))
        notes += [n] if n else []
        style = cc.TextStyle(size=_num(t.get("size"), 4, 20, 8), bold=bool(t.get("bold")), color=_color(t.get("color")),
                             align=1, auto_wrapping=True)
        pos = POSITION.get(str(t.get("position") or "bottom").lower(), -0.75)
        seg = cc.TextSegment(text, trange(st, du), font=font, style=style, clip_settings=cc.ClipSettings(transform_y=pos))
        script.add_segment(seg)

    mu = plan.get("music")
    if isinstance(mu, dict) and mu.get("file"):
        f = _resolve(mu.get("file"), {"audio", "video"}, files)
        if not f:
            notes.append(f"music: {mu.get('file')!r} is not an available audio file; skipped")
        else:
            try:
                start = _num(mu.get("from"), 0, max(0, f["seconds"] - 1), 0)
                du = min(total_us, round((f["seconds"] - start) * SEC))
                aseg = cc.AudioSegment(f["path"], trange(0, du), source_timerange=trange(round(start * SEC), du),
                                       volume=_num(mu.get("volume"), 0, 2, 0.6))
                aseg.add_fade(round(_num(mu.get("fade_in"), 0, 5, 0) * SEC), round(_num(mu.get("fade_out"), 0, 5, 1) * SEC))
                script.add_track(cc.TrackType.audio)
                script.add_segment(aseg)
            except Exception as e:  # noqa: BLE001  (e.g. a video file without an audio stream)
                notes.append(f"music: could not use {f['file']!r} ({type(e).__name__}); skipped")

    script.save()
    return {"draft": name, "path": str(target), "seconds": round(total_us / SEC, 2), "notes": notes,
            "ms": round((time.perf_counter() - t0) * 1000)}


PLAN_SYSTEM = """You plan video edits for CapCut. You never write code: you output ONE JSON object (the edit plan) and nothing else.

Plan format:
{"name": "short_snake_case_name",
 "canvas": "16:9" | "9:16" | "1:1" | "4:5",
 "clips": [{"file": "<one of AVAILABLE MEDIA>", "from": <start second in the source>, "duration": <seconds on the timeline>,
            "speed": 1.0, "volume": 1.0, "filter": "<FILTERS name or null>", "filter_strength": 80,
            "effect": "<EFFECTS name or null>", "zoom": "in" | "out" | null, "fill": "blur" | null,
            "transition": "<TRANSITIONS name or null: into the NEXT clip>", "transition_duration": 0.5}],
 "texts": [{"text": "...", "start": <second on the timeline>, "duration": <seconds>, "position": "top"|"center"|"bottom",
            "size": 8, "color": "#RRGGBB", "bold": true, "font": "<FONTS name or null>"}],
 "music": {"file": "<an audio file from AVAILABLE MEDIA>", "from": 0, "volume": 0.6, "fade_in": 1, "fade_out": 2} | null}

Rules:
- Clips play one after another in the listed order. Keep "from" + duration*speed within the file's length.
- Use only files from AVAILABLE MEDIA and only names from the lists below (they are the free items that work).
- "fill": "blur" fills the empty sides when a clip's shape differs from the canvas.
- If the request asks for something these tools cannot do, do the closest thing and keep going."""


def plan_prompt(request, files):
    media = "\n".join(f"- {f['file']} ({f['kind']}, {f['seconds']} s{', ' + f['size'] if f.get('size') else ''})" for f in files)
    lists = {
        "FILTERS": sorted(CATALOG["filter"]), "TRANSITIONS": sorted(CATALOG["transition"]),
        "EFFECTS": sorted(CATALOG["effect"]),
        "FONTS": sorted(CATALOG["font"])[:60],
    }
    cat = "\n".join(f"{k}: {', '.join(v)}" for k, v in lists.items())
    return f"REQUEST: {request}\n\nAVAILABLE MEDIA:\n{media}\n\n{cat}\n\nReply with the plan JSON only."


def make_plan(request, planner, files=None):
    """One model call (fast tier, hedged) -> plan dict. `planner` is a ChatPlanner."""
    from .planner import PlannerError
    from .util import parse_json
    files = files if files is not None else media_files()
    msgs = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": plan_prompt(request, files)}]
    t0 = time.perf_counter()
    r = planner._call("fast", msgs)
    plan = parse_json(r.text)
    if plan is None:
        msgs += [{"role": "assistant", "content": r.text[:2000]},
                 {"role": "user", "content": "That was not valid JSON. Reply with the plan JSON object only."}]
        r = planner._call("fast", msgs)
        plan = parse_json(r.text)
    if not isinstance(plan, dict):
        raise PlannerError("the planner did not return a JSON plan")
    return plan, round((time.perf_counter() - t0) * 1000)


def save_plan(request, plan, result):
    """Keep every plan and result inside the project (out/video/plans) for review and later learning."""
    d = ROOT / "out" / "video" / "plans"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{time.strftime('%Y%m%d-%H%M%S')}_{result.get('draft', 'plan')}.json"
    p.write_text(json.dumps({"request": request, "plan": plan, "result": result}, indent=1, ensure_ascii=False), encoding="utf-8")
    return p
