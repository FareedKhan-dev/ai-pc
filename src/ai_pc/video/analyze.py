"""Media analyzer: what is in each file the user gives, where, and when. Fast, and cached until the file changes.

Video  frames sampled at up to 4 fps (frames.sample: B-frames skipped, 4 parallel chunks) -> faces and eyes (YuNet),
       motion, camera movement (phase correlation), colour, shots (cuts), subject approaching/leaving the camera,
       green/blue screen; key moments -> ONE contact sheet -> ONE vision-model call that captions every moment (shot
       size, subject, action, setting, camera, mood, highlight score); the file's own sound -> audio.analyze.
Photo  faces, colour and a caption (all photos share one contact sheet and one call).
Audio  audio.analyze: tempo and beat grid, strong hits, the drop, pauses, speech/music guess.

Results go to state/media/<name>_<key>.json (key = name, size, modification time, analyzer version).
describe() turns an analysis into the compact text the planner reads.
"""
import hashlib
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from ai_pc.core.config import STATE
from ai_pc.llm.vlm import ask
from ai_pc.media import audio as A
from ai_pc.media import frames as F

VERSION = 3
CACHE = STATE / "media"
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

CAPTION_SYSTEM = """You describe numbered frames (yellow labels: number and time) so a video editor can plan cuts and effects.
Reply with ONE JSON object:
{"frames": [{"i": <number>, "shot": "extreme close-up|close-up|medium|full|wide|extreme wide",
  "subject": "<who/what, <=8 words>", "action": "<<=8 words>", "setting": "<<=6 words>",
  "camera": "<angle and movement guess, <=5 words>", "mood": "<1-3 words>",
  "highlight": <0-10: how striking this moment is for a social-media edit>,
  "notes": "<face toward camera? eyes visible? text or logo on screen? green screen? <=12 words>"}],
 "summary": "<one sentence about the whole file>"}
Describe only what is visible. No other text."""


def kind_of(path):
    ext = Path(path).suffix.lower()
    return "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else "audio" if ext in AUDIO_EXT else None


def _key(path):
    st = Path(path).stat()
    return hashlib.sha1(f"{Path(path).name}|{st.st_size}|{st.st_mtime_ns}|v{VERSION}".encode()).hexdigest()[:12]


def _cache_path(path):
    return CACHE / f"{Path(path).stem[:40]}_{_key(path)}.json"


def _median(xs, d=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else d


# ------------------------------------------------------------------------------------------------ video
def _shots(times, hd, diffs):
    """Cut points from colour-histogram jumps between neighbouring samples (precision = the sample spacing)."""
    med = _median(hd[1:], 0.05)
    cuts = [0.0]
    for i in range(1, len(times)):
        if hd[i] > 0.5 or (hd[i] > 0.28 and diffs[i] > 0.1 and hd[i] > 4 * med):
            t = round((times[i - 1] + times[i]) / 2, 2)
            if t - cuts[-1] >= 0.5:
                cuts.append(t)
    return cuts


def _shot_stats(idx, times, faces, diffs, shifts, cols, cut_at):
    fs = [faces[i] for i in idx]
    with_face = [f for f in fs if f]
    areas = [f[0]["box"][2] * f[0]["box"][3] for f in with_face]
    centres = [(f[0]["box"][0] + f[0]["box"][2] / 2, f[0]["box"][1] + f[0]["box"][3] / 2) for f in with_face]
    out = {"face_share": round(len(with_face) / max(1, len(fs)), 2), "max_faces": max((len(f) for f in fs), default=0)}
    if with_face:
        out.update(face_size=round(_median(areas), 4), face_x=round(_median([c[0] for c in centres]), 3),
                   face_y=round(_median([c[1] for c in centres]), 3),
                   eyes_visible=round(sum(1 for f in with_face if f[0]["score"] > 0.75 and f[0]["box"][2] > 0.04) / max(1, len(fs)), 2))
        if len(areas) >= 4:
            k = max(1, len(areas) // 4)
            grow = _median(areas[-k:]) / max(1e-6, _median(areas[:k]))
            dx = _median([c[0] for c in centres[-k:]]) - _median([c[0] for c in centres[:k]])
            out["subject_motion"] = ("approaching the camera" if grow > 1.6 else "moving away" if grow < 0.6 else "") + \
                                    (" moving right" if dx > 0.15 else " moving left" if dx < -0.15 else "")
            out["subject_motion"] = out["subject_motion"].strip() or "staying in place"
    d = [diffs[i] for i in idx[1:] if i not in cut_at]
    m = _median(d)
    out["motion"] = "still" if m < 0.008 else "low" if m < 0.025 else "medium" if m < 0.06 else "high"
    sx = [shifts[i][0] for i in idx[1:] if i not in cut_at and shifts[i][2] > 0.15]
    sy = [shifts[i][1] for i in idx[1:] if i not in cut_at and shifts[i][2] > 0.15]
    if len(sx) >= 3:
        pan, tilt = sum(sx), sum(sy)
        jitter = float(np.std(np.diff(sx))) + float(np.std(np.diff(sy))) if len(sx) > 3 else 0
        cam = []
        if abs(pan) > 0.15:
            cam.append("pans " + ("left" if pan > 0 else "right"))  # content moving right = camera turning left
        if abs(tilt) > 0.15:
            cam.append("tilts " + ("up" if tilt > 0 else "down"))
        if jitter > 0.01:
            cam.append("handheld/shaky")
        out["camera"] = ", ".join(cam) or "steady"
    c = [cols[i] for i in idx if cols[i]]
    if c:
        out["look"] = {k: round(_median([x[k] for x in c]), 2) for k in ("brightness", "saturation", "warmth", "contrast")}
    return out


def _moments(shots, times, sharp, per_file=12):
    """Which samples get captioned: the sharpest frame near the middle of each shot, more for long shots."""
    picks = []
    for s in shots:
        idx = s["_idx"]
        if not idx:
            continue
        n = 1 if s["end"] - s["start"] <= 4 else min(4, int((s["end"] - s["start"]) / 3.5) + 1)
        for k in range(n):
            lo, hi = s["start"] + (s["end"] - s["start"]) * k / n, s["start"] + (s["end"] - s["start"]) * (k + 1) / n
            mid = (lo + hi) / 2
            cand = [i for i in idx if lo + 0.2 * (hi - lo) <= times[i] <= hi - 0.2 * (hi - lo)] or idx
            best = max(cand, key=lambda i: sharp[i] / (1 + 2 * abs(times[i] - mid)))
            picks.append(best)
    if len(picks) > per_file:
        step = len(picks) / per_file
        picks = [picks[int(i * step)] for i in range(per_file)]
    return sorted(set(picks))


def _video(path, info, planner, log):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(2) as ex:
        fa = ex.submit(A.analyze, path) if info.get("has_audio") else None
        times, fr = F.sample(path, fps=4, width=640)
        t_dec = time.perf_counter() - t0
        faces = F.faces_many(fr)
        grays = [F.gray_small(f) for f in fr]
        diffs = [0.0] + [F.diff(a, b) for a, b in zip(grays, grays[1:])]
        shifts = [(0.0, 0.0, 0.0)] + [F.shift(a, b) for a, b in zip(grays, grays[1:])]
        hists = [F.hist(f) for f in fr]
        hd = [0.0] + [float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA)) for a, b in zip(hists, hists[1:])]
        sharp = [F.sharpness(f) for f in fr]
        cols = [F.colour(f) if i % 2 == 0 else None for i, f in enumerate(fr)]
        snd = fa.result() if fa else None
    t_meas = time.perf_counter() - t0
    cuts = _shots(times, hd, diffs) + [info["seconds"]]
    cut_at = {i for i in range(1, len(times)) if any(times[i - 1] < c <= times[i] for c in cuts[1:-1])}
    shots = []
    for a, b in zip(cuts, cuts[1:]):
        idx = [i for i, t in enumerate(times) if a <= t < b]
        s = {"start": round(a, 2), "end": round(b, 2), "_idx": idx}
        s.update(_shot_stats(idx, times, faces, diffs, shifts, cols, cut_at))
        shots.append(s)
    screen = None
    if len(fr):
        votes = [F.screen_colour(fr[i]) for i in np.linspace(0, len(fr) - 1, min(5, len(fr))).astype(int)]
        votes = [v for v in votes if v]
        if len(votes) >= 3:
            screen = {"kind": votes[0][0], "color": votes[len(votes) // 2][1]}
    picks = _moments(shots, times, sharp)
    caps, summary, vlm_s = {}, "", 0.0
    if planner is not None and picks:
        img = F.sheet([fr[i] for i in picks], [f"#{k + 1} {times[i]:.1f}s" for k, i in enumerate(picks)], cols=4 if len(picks) > 6 else 3, cell_w=320)
        d, vlm_s = ask(planner, CAPTION_SYSTEM, f"{len(picks)} frames from the video '{Path(path).name}' ({info['seconds']:.1f} s).", [img])
        for c in (d or {}).get("frames", []) if isinstance(d, dict) else []:
            try:
                caps[int(c.get("i")) - 1] = c
            except (TypeError, ValueError):
                continue
        summary = str((d or {}).get("summary", "")) if isinstance(d, dict) else ""
    moments = []
    for k, i in enumerate(picks):
        m = {"t": round(times[i], 2)}
        c = caps.get(k)
        if c:
            m.update({x: c.get(x) for x in ("shot", "subject", "action", "setting", "camera", "mood", "highlight", "notes") if c.get(x) not in (None, "")})
        if faces[i]:
            m["face"] = faces[i][0]
        moments.append(m)
    for s in shots:
        s.pop("_idx")
    track = [{"t": round(t, 2), "faces": [{"box": f["box"], "right_eye": f["right_eye"], "left_eye": f["left_eye"], "score": f["score"]} for f in fs[:3]]}
             for t, fs in zip(times, faces) if fs]
    log(f"  {Path(path).name}: {len(times)} frames read in {t_dec:.1f} s, measured in {t_meas - t_dec:.1f} s, "
        f"{len(shots)} shot(s), {len(picks)} moments captioned in {vlm_s:.1f} s")
    return {"shots": shots, "moments": moments, "summary": summary, "screen": screen, "sound": snd, "faces": track,
            "motion": [round(x, 4) for x in diffs], "times": [round(t, 2) for t in times]}


# ------------------------------------------------------------------------------------------------ photos
def _photos(paths, planner, log):
    out = {}
    frs = {}
    for p in paths:
        fr = F.image(p, width=960)
        frs[p] = fr
        fc = F.faces(fr)
        out[p] = {"faces": [{"box": f["box"], "right_eye": f["right_eye"], "left_eye": f["left_eye"], "score": f["score"]} for f in fc[:3]],
                  "look": F.colour(fr), "screen": (lambda s: {"kind": s[0], "color": s[1]} if s else None)(F.screen_colour(fr))}
    if planner is not None and paths:
        for i in range(0, len(paths), 9):
            group = paths[i:i + 9]
            img = F.sheet([frs[p] for p in group], [f"#{k + 1}" for k in range(len(group))], cols=3, cell_w=320)
            d, s = ask(planner, CAPTION_SYSTEM, f"{len(group)} separate photos: " + ", ".join(f"#{k + 1} {Path(p).name}" for k, p in enumerate(group)), [img])
            for c in (d or {}).get("frames", []) if isinstance(d, dict) else []:
                try:
                    p = group[int(c.get("i")) - 1]
                except (TypeError, ValueError, IndexError):
                    continue
                out[p]["caption"] = {x: c.get(x) for x in ("shot", "subject", "action", "setting", "mood", "highlight", "notes") if c.get(x) not in (None, "")}
            log(f"  {len(group)} photo(s) captioned in {s:.1f} s")
    return out


# ------------------------------------------------------------------------------------------------ entry points
def analyze(paths, planner=None, log=print, use_cache=True):
    """{file name: analysis} for the given files, all analysed in parallel; cached results are reused."""
    t0 = time.perf_counter()
    CACHE.mkdir(parents=True, exist_ok=True)
    results, todo = {}, []
    for p in map(Path, paths):
        cp = _cache_path(p)
        if use_cache and cp.exists():
            results[p.name] = json.loads(cp.read_text(encoding="utf-8"))
        else:
            todo.append(p)
    photos = [p for p in todo if kind_of(p) == "image"]

    def one(p):
        k = kind_of(p)
        base = {"file": p.name, "path": str(p), "kind": k}
        if k == "video":
            info = F.probe(p)
            base.update(info)
            base.update(_video(p, info, planner, log))
        elif k == "audio":
            info = F.probe(p)
            base.update(seconds=round(info["seconds"], 2), sound=A.analyze(p))
        return base
    with ThreadPoolExecutor(4) as ex:
        futs = {p: ex.submit(one, p) for p in todo if kind_of(p) in ("video", "audio")}
        ph = ex.submit(_photos, photos, planner, log) if photos else None
        for p, f in futs.items():
            results[p.name] = f.result()
        if ph:
            for p, d in ph.result().items():
                info = F.probe(p)
                results[p.name] = {"file": p.name, "path": str(p), "kind": "image", "width": info.get("width"),
                                   "height": info.get("height"), **d}
    for p in todo:
        if p.name in results:
            _cache_path(p).write_text(json.dumps(results[p.name], ensure_ascii=False), encoding="utf-8")
    log(f"analysed {len(todo)} file(s), {len(paths) - len(todo)} from cache, in {time.perf_counter() - t0:.1f} s")
    return results


def _aspect(w, h):
    if not w or not h:
        return "?"
    r = w / h
    for name, v in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1), ("4:3", 4 / 3), ("3:4", 3 / 4), ("4:5", 0.8), ("21:9", 21 / 9)):
        if abs(r - v) < 0.03:
            return name
    return f"{r:.2f}:1"


def _sound_line(s):
    if not s:
        return "no sound"
    bits = [f"{s['kind']}, {s['loudness_db']} dB"]
    if s.get("bpm"):
        bits.append(f"{s['bpm']:.0f} BPM (beat confidence {s['beat_confidence']:.2f}), first beats {', '.join(f'{b:.2f}' for b in s['beats'][:4])} s")
    if s.get("drop") is not None:
        bits.append(f"energy jumps at {s['drop']:.0f} s")
    strong = [h for h in s.get("hits", []) if h["strength"] >= 0.6][:8]
    if strong:
        bits.append("strong hits at " + ", ".join(f"{h['t']:.1f}" for h in strong) + " s")
    if s.get("quiet"):
        bits.append("pauses " + ", ".join(f"{a:.1f}-{b:.1f}" for a, b in s["quiet"][:5]))
    return "; ".join(bits)


def describe(a):
    """Compact text for the planner."""
    k = a.get("kind")
    if k == "audio":
        return f"{a['file']}: audio {a.get('seconds', 0):.1f} s - {_sound_line(a.get('sound'))}"
    if k == "image":
        c = a.get("caption") or {}
        f = a.get("faces") or []
        face = f"; face at x {f[0]['box'][0] + f[0]['box'][2] / 2:.2f} y {f[0]['box'][1] + f[0]['box'][3] / 2:.2f}, {100 * f[0]['box'][2] * f[0]['box'][3]:.1f}% of the picture" if f else "; no face"
        return (f"{a['file']}: photo {a.get('width')}x{a.get('height')} ({_aspect(a.get('width'), a.get('height'))})"
                f" - {c.get('shot', '')} {c.get('subject', '')}, {c.get('setting', '')}; mood {c.get('mood', '?')}{face}")
    lines = [f"{a['file']}: video {a['seconds']:.1f} s, {a['width']}x{a['height']} ({_aspect(a['width'], a['height'])}), "
             f"{a['fps']:.0f} fps; sound: {_sound_line(a.get('sound'))}" + (f'. "{a["summary"]}"' if a.get("summary") else "")]
    if a.get("screen"):
        lines.append(f"  {a['screen']['kind']} screen behind the subject ({a['screen']['color']}): can be keyed out with chroma")
    for i, s in enumerate(a.get("shots", [])):
        bits = [f"  shot {i + 1} {s['start']:.1f}-{s['end']:.1f} s: motion {s['motion']}"]
        if s.get("camera"):
            bits.append(f"camera {s['camera']}")
        if s.get("face_share"):
            bits.append(f"face in {s['face_share'] * 100:.0f}% (at x {s['face_x']:.2f} y {s['face_y']:.2f}, {100 * s['face_size']:.1f}% of the frame"
                        + (", eyes visible" if s.get("eyes_visible", 0) > 0.5 else "") + ")")
            if s.get("subject_motion"):
                bits.append(f"subject {s['subject_motion']}")
        else:
            bits.append("no clear face")
        lines.append("; ".join(bits))
    try:
        from ai_pc.media.speech import cached
        tr = cached(a["path"]) if a.get("path") else None
    except Exception:  # noqa: BLE001
        tr = None
    if tr and tr.get("segments"):
        lines.append("  said: " + " ".join(f"[{s['start']:.1f}s] {s['text']}" for s in tr["segments"])[:900])
    for m in a.get("moments", []):
        if m.get("subject"):
            lines.append(f"    {m['t']:.1f}s [{m.get('shot', '?')}, highlight {m.get('highlight', '?')}] {m.get('subject', '')} - {m.get('action', '')}"
                         f"; {m.get('setting', '')}; {m.get('camera', '')}; {m.get('mood', '')}" + (f"; {m['notes']}" if m.get("notes") else ""))
    return "\n".join(lines)


def faces_near(a, t, within=0.3):
    """Faces in the analysed samples closest to time t of a video (empty if none within `within` s)."""
    best = min(a.get("faces", []), key=lambda x: abs(x["t"] - t), default=None)
    return best["faces"] if best and abs(best["t"] - t) <= within else []


def face_ranges(a, min_size=0.0, gap=0.6):
    """[[start, end], ...] where a face (of at least min_size of the frame) is visible."""
    ts = [x["t"] for x in a.get("faces", []) if x["faces"] and x["faces"][0]["box"][2] * x["faces"][0]["box"][3] >= min_size]
    out = []
    for t in ts:
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [[round(s, 2), round(e + 0.25, 2)] for s, e in out]
