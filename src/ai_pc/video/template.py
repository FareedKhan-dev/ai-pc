"""Templates: copy a finished edit's exact timing and moves onto new footage (what CapCut templates do).

A template here is LEARNED from a video of it (a CapCut template preview, a trending edit, one of our own exports):

  tpl = learn(path, planner, name="glowup")   frame-accurate cuts (hard, under a flash, dissolve / motion transitions),
                                              flashes, zoom punches and shakes, each slot's shot size (faces), motion,
                                              brightness / colour (black-and-white slots), the beat grid and the drop;
                                              with a planner one vision call reads each slot's text and what it shows.
                                              Saved in state/templates/<name>.json: learned once, reused by name.
  plan, info = fill(tpl, analyses, request)   a plan (editplan schema) with the template's slots as the clips: every
                                              slot gets the best moment of the client's footage for it (shot size,
                                              motion, highlight, content, variety, no moment twice), the template's
                                              transitions, flashes, zooms, shakes, per-slot looks and texts at the
                                              same times, and music at the template's tempo with its drop in place
                                              (the template's own song is not reused: it is licensed inside CapCut).
  match(tpl, video)                           after export: the new video's cuts against the template's.

Template effects are mapped to items that work here (CapCut-only effects cannot be loaded by JianYing); what could
only be approximated is listed in info["approximations"].
"""
import hashlib
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from ai_pc.core.config import ROOT
from ai_pc.media import audio as AU
from ai_pc.media import frames as F

STORE = ROOT / "state" / "templates"
FPS_MAX = 30.0

SLOT_SYSTEM = """You read the frames of a video template for an editor who will copy it with other footage. Each cell is
the middle frame of one slot (shot), labelled #n. Reply with ONE JSON object:
{"slots": [{"n": <slot number>, "text": "<on-screen words exactly, or empty>", "text_position": "top|upper|center|lower|bottom|none",
            "text_size": "small|medium|large|huge|none", "text_colour": "<colour or none>", "text_style": "<bold sans, script, serif, outline, box...>",
            "shows": "<what the shot shows in a few words: shot size, subject, action>", "shot": "close-up|medium|wide|extreme wide|detail"}],
 "theme": "<what the template is about, a few words>", "text_font_style": "<the template's main font style>"}
Copy on-screen text exactly (keep its case). Captions burned into the picture count as text."""


# ------------------------------------------------------------------------------------------------ learning
def _key(path):
    p = Path(path)
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]


def _local_median(x, half):
    n = len(x)
    out = np.zeros(n, np.float32)
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        w = np.concatenate([x[a:i], x[i + 1:b]]) if b - a > 1 else x[a:b]
        out[i] = float(np.median(w)) if len(w) else 0.0
    return out


def _hists(frames):
    out = []
    for f in frames:
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256])
        cv2.normalize(h, h)
        out.append(h)
    return out


def _bd(a, b):
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


_ORB = None


def _orb():
    global _ORB
    if _ORB is None:
        _ORB = cv2.ORB_create(400, fastThreshold=10, edgeThreshold=12)
    return _ORB


def same_scene(ga, gb):
    """Whether two grey frames show the same shot (after a zoom, shake, flash or overlay effect): enough ORB features
    match under one homography. True / False, or None when the frames have too little texture to tell."""
    ka, da = _orb().detectAndCompute(ga, None)
    kb, db = _orb().detectAndCompute(gb, None)
    if da is None or db is None or len(ka) < 25 or len(kb) < 25:
        return None
    m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    good = [x for x in m if x.distance < 48]
    if len(good) < 10:
        return False
    src = np.float32([ka[x.queryIdx].pt for x in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[x.trainIdx].pt for x in good]).reshape(-1, 1, 2)
    Hm, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    inl = int(mask.sum()) if mask is not None else 0
    return inl >= max(14, 0.12 * min(len(ka), len(kb)))


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum())) or 1.0
    return float((a * b).sum() / den)


def decode_gray(path, seconds, fps, width=200):
    """Every frame in grey at `width` px (for the scene test): one ffmpeg pass, ~70 KB a frame."""
    import subprocess
    info = F.probe(str(path))
    height = int(round(width * info["height"] / info["width"] / 2) * 2)
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-t", f"{seconds:.3f}", "-an", "-vf", f"fps={fps},scale={width}:{height}",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    k = len(r.stdout) // (width * height)
    return np.frombuffer(r.stdout, np.uint8)[:k * width * height].reshape(k, height, width)


def detect_cuts(fr, fps, gray_big=None, beats=None):
    """Shot changes in a frame sequence: [{"t", "frame", "kind": cut|flash|dissolve|motion, "dur"}], the flashes, and
    per-frame signals. `fr`: small colour frames; `gray_big`: the same frames in grey at ~200 px for the scene test.

    Candidates are generous (cheap signals):
      hard cut   one frame carries a big change in colour, pixels or structure that its neighbours do not;
      flash      a white, flat burst that comes back down: a cut is hidden under it when the shot changes;
      transition the picture 0.4 s or 1 s apart differs, and the change rises and settles (dissolve, blur, zoom, whip).
    Then each one is verified the way an editor would look: frames just outside the change (bounded by the neighbouring
    candidates, so a quick cut never compares with the shot after next) are matched with ORB features. If any pair is
    the same scene under one homography, it was a zoom, a shake, a glitch, a light leak or a strobe, not a cut. Frames
    too dark or flat to match fall back to the colour mix of several frames on each side.

    beats (the music's beat times, when it has a steady beat): templates cut on the beat, so a candidate on a beat (or
    half beat) needs the normal evidence, one off the beat strong evidence, and accepted cuts snap to the beat."""
    n = len(fr)
    grid = None
    step = None
    if beats is not None and len(beats) >= 8:
        step = float(np.median(np.diff(np.asarray(beats, np.float32))))
        step = step if 0.2 < step < 1.5 else None

    def off_beat(frame, slack=0.0):
        if grid is None:
            return 0.0
        return float(np.min(np.abs(grid - frame / fps))) - slack
    gray = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in fr]).astype(np.float32)
    if gray_big is None or len(gray_big) < n:
        gray_big = [cv2.resize(g.astype(np.uint8), (200, max(8, round(g.shape[0] * 200 / g.shape[1])))) for g in gray]
    hsv = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2HSV) for f in fr]).astype(np.float32) / 255.0
    bright = hsv[..., 2].mean(axis=(1, 2))
    sat = hsv[..., 1].mean(axis=(1, 2))
    vstd = hsv[..., 2].std(axis=(1, 2))
    H = _hists(fr)
    Hm = np.stack([h.flatten() for h in H])
    thumbs = [cv2.resize(g, (24, max(8, round(g.shape[0] * 24 / g.shape[1]))), interpolation=cv2.INTER_AREA) for g in gray]
    d1 = np.zeros(n, np.float32)
    h1 = np.zeros(n, np.float32)
    n1 = np.zeros(n, np.float32)
    for i in range(1, n):
        d1[i] = float(np.mean(np.abs(thumbs[i] - thumbs[i - 1]))) / 255.0
        h1[i] = _bd(H[i - 1], H[i])
        n1[i] = max(0.0, 1.0 - _ncc(thumbs[i], thumbs[i - 1]))
    c = np.maximum.reduce([h1, 1.6 * d1, 0.9 * n1])  # colour, pixels, structure: a cut between look-alike shots shows in one
    base = _local_median(c, int(fps * 0.6))
    scene_cache = {}

    def scene(i, j):
        i, j = max(0, min(n - 1, i)), max(0, min(n - 1, j))
        if (i, j) not in scene_cache:
            scene_cache[(i, j)] = same_scene(gray_big[i], gray_big[j])
        return scene_cache[(i, j)]

    def wide_colour(a0, a1, b0, b1):
        """Colour mix of frames [a0, a1) against [b0, b1) (robust to one-frame strobes and glitches)."""
        a0, a1, b0, b1 = max(0, a0), max(1, min(n, a1)), max(0, b0), max(1, min(n, b1))
        if a1 <= a0 or b1 <= b0:
            return 0.0
        ha = Hm[a0:a1].mean(axis=0).reshape(H[0].shape).astype(np.float32)
        hb = Hm[b0:b1].mean(axis=0).reshape(H[0].shape).astype(np.float32)
        return _bd(ha, hb)

    def is_cut(lo, hi, prev_b, next_b, strict=False):
        """Whether the shot before frame lo and the shot after frame hi differ. prev_b / next_b: the neighbouring
        candidates' frames, so the comparison stays inside these two shots. strict (no one-frame jump to go on): two
        frame pairs must differ, or one pair and a clear change of colour mix."""
        room_b, room_a = max(1, lo - prev_b - 1), max(1, next_b - hi - 1)
        pairs = []
        for o in (2, 5, 9):
            a, b = lo - min(o, room_b), hi + min(o - 1, room_a)
            if (a, b) not in pairs:
                pairs.append((a, b))
        same = diff = 0
        for a, b in pairs:
            s = scene(a, b)
            if s is True:
                same += 1
            elif s is False:
                diff += 1
        if same and same >= diff:
            return False
        if diff >= 2 or (diff == 1 and not same):
            wc = wide_colour(lo - min(8, room_b), lo - 1, hi + 2, hi + 2 + min(8, room_a))
            if strict:
                return (diff >= 2 and wc > 0.04) or wc > 0.12
            return diff >= 2 or wc > 0.05
        wc = wide_colour(lo - min(8, room_b), lo - 1, hi + 2, hi + 2 + min(8, room_a))
        return wc > 0.22  # too dark or flat to match features: only a clear change of colour mix counts

    # flashes: a white, flat, short burst that comes back down (club lights are coloured, patchy and do not return cleanly)
    flashes = []
    i = 1
    while i < n:
        pre = float(np.median(bright[max(0, i - 4):i]))
        pre_s = float(np.median(sat[max(0, i - 4):i]))
        if bright[i] - pre > 0.14 and bright[i] > 0.6:
            j = i
            while j + 1 < n and j - i < int(fps * 0.7) and bright[j + 1] - pre > 0.06:
                j += 1
            back = j + 1 < n and bright[j + 1] - pre <= 0.06 or j + 1 >= n
            peak = i + int(np.argmax(bright[i:j + 1]))
            white = sat[peak] < max(0.12, 0.6 * pre_s) or vstd[peak] < 0.6 * float(np.median(vstd[max(0, i - 4):i]) or 1)
            if back and j - i < int(fps * 0.7) and white:
                flashes.append({"t": round(peak / fps, 3), "frame": peak, "lo": i, "hi": j, "start": round(i / fps, 3), "end": round((j + 1) / fps, 3)})
                i = j + 2
                continue
        i += 1
    flash_frames = {x for f in flashes for x in range(f["lo"] - 1, f["hi"] + 3)}
    # candidates (generous)
    cands = []
    for i in range(1, n - 1):
        if i in flash_frames:
            continue
        nb = max(c[max(1, i - 2):i].max(initial=0), c[i + 1:min(n, i + 3)].max(initial=0))
        if c[i] > max(0.06, 2.6 * base[i]) and c[i] >= nb * 1.3 and c[i] == c[max(1, i - 2):min(n, i + 3)].max():
            cands.append({"frame": i, "lo": i, "hi": i, "kind": "cut", "score": float(c[i] / max(base[i], 0.01))})
    for f in flashes:
        cands.append({"frame": f["frame"], "lo": f["lo"], "hi": f["hi"], "kind": "flash", "score": 5.0, "flash": f})
    for secs in (0.2, 0.5):  # transitions at two scales: quick ones and long cinematic dissolves
        k = max(3, int(round(fps * secs)))
        D = np.zeros(n, np.float32)
        for i in range(k, n - k):
            D[i] = max(0.6 * _bd(H[i - k], H[i + k]) + 0.4 * 3 * float(np.mean(np.abs(thumbs[i - k] - thumbs[i + k]))) / 255,
                       0.9 * (1 - _ncc(thumbs[i - k], thumbs[i + k])))
        Dbase = _local_median(D, int(fps * 1.5))
        for i in range(k, n - k):
            if D[i] < max(0.22, 1.6 * Dbase[i]) or D[i] < D[max(0, i - k):i + k + 1].max():
                continue
            left = D[max(0, i - 3 * k):i - k // 2 + 1].min(initial=D[i])
            right = D[i + k // 2:min(n, i + 3 * k + 1)].min(initial=D[i])
            if D[i] < 1.25 * max(left, right, 0.04):
                continue
            lo, hi = i, i
            while lo > 1 and c[lo - 1] > max(0.035, 1.4 * base[lo - 1]) and i - lo < 1.2 * fps:
                lo -= 1
            while hi < n - 1 and c[hi + 1] > max(0.035, 1.4 * base[hi + 1]) and hi - i < 1.2 * fps:
                hi += 1
            if hi - lo < 2:  # a transition takes several frames; a one-frame change is the hard-cut candidate's
                lo, hi = i - max(1, k // 2), i + max(1, k // 2)
            cands.append({"frame": i, "lo": lo, "hi": hi, "kind": "soft", "score": float(D[i] / max(Dbase[i], 0.02))})
    if SEGMENT_MERGE:
        return _segment_merge(cands, flashes, n, fps, c, base, gray, scene, wide_colour, step, bright, sat, d1)
    # one candidate per shot change: overlapping candidates keep the hard cut, else the strongest
    cands.sort(key=lambda x: x["frame"])
    groups = []
    for x in cands:
        if groups and (x["lo"] <= groups[-1][-1]["hi"] + 2 or x["frame"] - groups[-1][-1]["frame"] <= max(3, int(fps * 0.15))):
            groups[-1].append(x)
        else:
            groups.append([x])
    picked = []
    for g in groups:
        hard = [x for x in g if x["kind"] == "cut"]
        fl = [x for x in g if x["kind"] == "flash"]
        best = max(fl or hard or g, key=lambda x: x["score"])
        lo, hi = min(x["lo"] for x in g), max(x["hi"] for x in g)
        if best["kind"] == "cut" and best["score"] >= 4:
            lo = hi = best["frame"]
        picked.append({**best, "lo": lo, "hi": hi})
    if step:  # the beat grid: the music's tempo, phased by where the clear cuts really fall (frame-exact, unlike audio beats)
        strong = []
        for k_, x in enumerate(picked):
            if x["kind"] == "cut" and x["score"] >= 6:
                pb = picked[k_ - 1]["hi"] if k_ else 0
                nb = picked[k_ + 1]["lo"] if k_ + 1 < len(picked) else n - 1
                if is_cut(x["frame"] - 1, x["frame"] + 1, pb, nb):
                    strong.append(x["frame"] / fps)
        half = step / 2
        if len(strong) >= 5:
            ang = np.array(strong) / half * 2 * np.pi
            z = np.exp(1j * ang).mean()
            if abs(z) >= 0.6:  # the clear cuts sit on a regular half-beat grid
                phase = (np.angle(z) % (2 * np.pi)) / (2 * np.pi) * half
                grid = phase + half * np.arange(0, int(n / fps / half) + 2)
    cuts, rejected = [], []
    for k_, x in enumerate(picked):
        prev_b = picked[k_ - 1]["hi"] if k_ else -10 ** 6
        next_b = picked[k_ + 1]["lo"] if k_ + 1 < len(picked) else 10 ** 6
        prev_b = max(prev_b, (cuts[-1]["frame"] if cuts else -10 ** 6))
        lo, hi = (x["lo"], x["hi"]) if x["kind"] != "cut" else (x["frame"], x["frame"])
        # off the beat (when the music has one): only strong evidence makes it a cut
        slack = (x["hi"] - x["lo"]) / 2 / fps if x["kind"] != "cut" else 0.0
        offb = off_beat(x["frame"], slack) > 0.09
        ok = is_cut(lo - (1 if x["kind"] == "cut" else 0), hi + (1 if x["kind"] == "cut" else 0), max(prev_b, 0), min(next_b, n - 1),
                    strict=x["kind"] == "soft" or (offb and not (x["kind"] == "cut" and x["score"] >= 6)))
        if x["kind"] == "flash":
            x["flash"]["hides_cut"] = bool(ok)
        if not ok:  # kept: when the template's page says how many clips it has, the strongest of these may be cuts after all
            rejected.append({"frame": int(x["frame"]), "kind": x["kind"], "score": round(float(x["score"]), 3),
                             "dur": round((x["hi"] - x["lo"] + 1) / fps, 3) if x["kind"] != "cut" else 0.0})
            continue
        sc = round(float(x["score"]), 3)
        if x["kind"] == "soft":
            mid = (x["lo"] + x["hi"]) // 2
            sharp = [cv2.Laplacian(gray[j], cv2.CV_32F).var() for j in (max(0, x["lo"] - 3), mid, min(n - 1, x["hi"] + 3))]
            kind = "motion" if sharp[1] < 0.45 * min(sharp[0], sharp[2]) else "dissolve"
            cuts.append({"frame": int(x["frame"]), "kind": kind, "dur": round((x["hi"] - x["lo"] + 1) / fps, 3), "score": sc})
        elif x["kind"] == "flash":
            cuts.append({"frame": int(x["frame"]), "kind": "flash", "dur": round((x["hi"] - x["lo"] + 1) / fps, 3), "score": sc})
        else:
            cuts.append({"frame": int(x["frame"]), "kind": "cut", "dur": 0.0, "score": sc})
    # two "cuts" under 0.3 s apart with no steady picture between them are the two ends of one transition (a glitch
    # or colour-flash transition jumps when it starts and when it ends): one cut in the middle. A real quick shot
    # between them is steady (its one-frame changes stay near the shots' own motion) and stays two cuts.
    out = []
    for x in cuts:
        if out and x["frame"] - out[-1]["frame"] <= int(fps * 0.3):
            a, b = out[-1]["frame"], x["frame"]
            mid = c[a + 2:b - 1] if b - a > 3 else np.array([1.0])
            steady = len(mid) >= 3 and float(np.median(mid)) < max(0.05, 2.0 * float(np.median(base[a:b + 1])))
            if not steady:
                kind = out[-1]["kind"] if out[-1]["kind"] in ("flash", "dissolve", "motion") else ("motion" if x["kind"] == "cut" else x["kind"])
                out[-1] = {"frame": (a + b) // 2, "kind": kind, "dur": round(max(out[-1]["dur"], x["dur"], (b - a + 1) / fps), 3),
                           "score": max(out[-1].get("score", 0), x.get("score", 0))}
                continue
        out.append(x)
    cuts = out
    # last look: the steadiest frame of the shot before and after each cut (an effect in the middle of a shot leaves
    # the same scene on both sides; checking steady frames, not the effect's own distorted ones)
    effects = []

    def steady(a, b):
        inner = range(a + 1, b) if b - a >= 2 else range(a, b + 1)
        return min(inner, key=lambda i: c[i] + (0.5 if i in flash_frames else 0)) if len(inner) else a
    k_ = 0
    while k_ < len(cuts):
        x = cuts[k_]
        a0 = cuts[k_ - 1]["frame"] + 1 if k_ else 0
        b1 = cuts[k_ + 1]["frame"] - 1 if k_ + 1 < len(cuts) else n - 1
        half = max(1, int(round(x["dur"] * fps / 2))) if x["kind"] != "cut" else 1
        left, right = (a0, x["frame"] - half), (x["frame"] + half, b1)
        s = None
        if left[1] - left[0] >= 3 and right[1] - right[0] >= 3:
            s = scene(steady(*left), steady(*right))
            if s is True:
                effects.append({"t": round(x["frame"] / fps, 3), "kind": x["kind"]})
                rejected.append({"frame": int(x["frame"]), "kind": x["kind"], "score": x.get("score", 0), "dur": x["dur"], "same_scene": True})
                del cuts[k_]
                continue
        # how sure: the two shots' steady frames do not match, their colour mixes differ, the change itself was strong
        wc = wide_colour(max(left[0], left[1] - 10), left[1] + 1, right[0], min(right[1], right[0] + 10) + 1)
        own = min(1.0, x.get("score", 0) / 12) if x["kind"] == "cut" else 0.7 if x["kind"] == "flash" else min(1.0, x.get("score", 0) / 3)
        x["conf"] = round((1.0 if s is False else 0.4) + min(1.0, wc / 0.25) + own, 3)
        x["evidence"] = {"orb_differs": s is False, "colour": round(float(wc), 3), "own": round(float(own), 3),
                         "gap": round(min(x["frame"] - a0 + 1, b1 - x["frame"] + 1) / fps, 3)}
        k_ += 1
    if grid is not None:  # on the beat: snap to it (the exact frame a template's cut sits on)
        for x in cuts:
            j = int(np.argmin(np.abs(grid - x["frame"] / fps)))
            if abs(grid[j] - x["frame"] / fps) <= max(2.0 / fps, x.get("dur", 0) / 2):
                x["frame"] = int(round(grid[j] * fps))
                x["on_beat"] = True
    for f in flashes:
        f.setdefault("hides_cut", False)
        f.pop("lo", None)
        f.pop("hi", None)
    for x in cuts:
        x["t"] = round(x["frame"] / fps, 3)
    for x in rejected:
        x["t"] = round(x["frame"] / fps, 3)
    return cuts, flashes, {"bright": bright, "sat": sat, "d1": d1, "c": c, "gray": gray, "effects": effects, "rejected": rejected,
                           "grid": grid, "step": step}


def constrain_cuts(cuts, want, rejected, n, fps, beats=None, split=True):
    """Exactly `want` cuts when the template's page says how many clips it has (want = clips - 1). Returns (cuts, notes).
    Too many: the least sure go (an effect, a strobe or a camera move taken for a cut).
    Too few: the strongest rejected hard cuts come back (cuts between look-alike shots); then, with split, the longest
    slot is cut on the beat nearest its middle, marked "guessed" (the preview does not show where that cut is)."""
    cuts = sorted((dict(c) for c in cuts), key=lambda c: c["frame"])
    notes = []
    if want is None or want < 0:
        return cuts, notes
    if len(cuts) > want:
        extra = len(cuts) - want
        weak = {id(c) for c in sorted(cuts, key=lambda c: c.get("conf", 2.0))[:extra]}
        cuts = [c for c in cuts if id(c) not in weak]
        notes.append(f"{extra} weak cut(s) left out: the template's page says {want + 1} clips")
    gap = max(2, int(round(0.25 * fps)))
    if len(cuts) < want:
        back = 0
        for r in sorted(rejected, key=lambda r: -r["score"]):
            if len(cuts) >= want:
                break
            if r.get("same_scene") or r["kind"] not in ("cut", "flash") or r["score"] < 5:
                continue
            f = int(r["frame"])
            if f < gap or f > n - gap or any(abs(f - c["frame"]) < gap for c in cuts):
                continue
            cuts.append({"frame": f, "t": round(f / fps, 3), "kind": r["kind"], "dur": r.get("dur", 0.0), "score": r["score"], "conf": 0.0,
                         "restored": True})
            back += 1
        cuts.sort(key=lambda c: c["frame"])
        if back:
            notes.append(f"{back} cut(s) between look-alike shots taken back: the page says {want + 1} clips")
    guessed = 0
    while split and len(cuts) < want:
        b = [0] + [c["frame"] for c in cuts] + [n]
        k = max(range(len(b) - 1), key=lambda i: b[i + 1] - b[i])
        a, z = b[k], b[k + 1]
        if z - a < 2 * gap:
            break
        mid = (a + z) / 2
        cand = [round(t * fps) for t in (beats or []) if a + gap <= round(t * fps) <= z - gap]
        f = int(min(cand, key=lambda x: abs(x - mid)) if cand else round(mid))
        cuts.append({"frame": f, "t": round(f / fps, 3), "kind": "cut", "dur": 0.0, "score": 0.0, "conf": 0.0, "guessed": True})
        cuts.sort(key=lambda c: c["frame"])
        guessed += 1
    if guessed:
        notes.append(f"{guessed} cut(s) not visible in the preview: placed on the beat in the middle of the longest shot(s)")
    return cuts, notes


SEGMENT_MERGE = False


def _segment_merge(cands, flashes, n, fps, c, base, gray, scene, wide_colour, step, bright, sat, d1):
    """Shots the way an editor finds them: cut the video at every candidate (generous), take each piece's steadiest
    frame, then join neighbouring pieces that show the same scene. A glitch, colour flash, zoom punch or strobe in the
    middle of a shot splits it into pieces of one scene, which join again (and are kept as effects); a real cut,
    hidden or not, separates two scenes. Transition frames (the span of a dissolve, blur or flash) belong to no piece."""
    spans = sorted([[x["lo"], x["hi"], x] for x in cands], key=lambda s: s[0])
    merged = []
    for lo, hi, x in spans:  # overlapping candidate spans are one boundary
        if merged and lo <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], hi)
            merged[-1][2].append(x)
        else:
            merged.append([lo, hi, [x]])
    # pieces between boundaries (a piece under 2 frames is part of the boundary around it)
    bounds, pieces = [], []
    cur = 0
    for lo, hi, xs in merged:
        if lo - cur >= 2:
            pieces.append([cur, lo - 1])
            bounds.append([lo, hi, xs])
        elif bounds:
            bounds[-1][1] = hi
            bounds[-1][2] += xs
        else:
            bounds.append([lo, hi, xs]) if pieces else None
        cur = hi + 1
    if n - cur >= 2:
        pieces.append([cur, n - 1])
    else:
        bounds = bounds[:len(pieces) - 1] if pieces else []
    if len(bounds) >= len(pieces):
        bounds = bounds[:max(0, len(pieces) - 1)]

    def rep(p):
        a, b = p
        inner = range(a + 1, b) if b - a >= 2 else range(a, b + 1)
        return min(inner, key=lambda i: c[i] + (0.5 if abs(bright[i] - np.median(bright[a:b + 1])) > 0.15 else 0))

    def same(p, q, between):
        s = scene(rep(p), rep(q))
        if s is not None:
            return s
        # too dark or flat for features: the colour mix of the steady frames on each side
        return wide_colour(max(p[0], p[1] - 7), p[1] + 1, q[0], min(q[1], q[0] + 7) + 1) < 0.15

    cuts, effects = [], []
    k = 0
    while k < len(bounds):
        lo, hi, xs = bounds[k]
        p, q = pieces[k], pieces[k + 1]
        if same(p, q, (lo, hi)):  # one scene on both sides: an effect, not a cut; the two pieces become one
            effects.append({"t": round((lo + hi) / 2 / fps, 3), "dur": round((hi - lo + 1) / fps, 3),
                            "kinds": sorted({x["kind"] for x in xs})})
            pieces[k] = [p[0], q[1]]
            del pieces[k + 1]
            del bounds[k]
            continue
        fl = [x for x in xs if x["kind"] == "flash"]
        hard = [x for x in xs if x["kind"] == "cut"]
        if fl:
            fl[0]["flash"]["hides_cut"] = True
            cuts.append({"frame": int(fl[0]["frame"]), "kind": "flash", "dur": round((hi - lo + 1) / fps, 3)})
        elif hi - lo <= 1 or (hard and max(h["score"] for h in hard) >= 6 and hi - lo <= 3):
            f = max(hard, key=lambda h: h["score"])["frame"] if hard else lo
            cuts.append({"frame": int(f), "kind": "cut", "dur": 0.0})
        else:
            mid = (lo + hi) // 2
            sharp = [cv2.Laplacian(gray[j], cv2.CV_32F).var() for j in (max(0, lo - 2), mid, min(n - 1, hi + 2))]
            kind = "motion" if sharp[1] < 0.45 * min(sharp[0], sharp[2]) else "dissolve"
            cuts.append({"frame": int(mid), "kind": kind, "dur": round((hi - lo + 1) / fps, 3)})
        k += 1
    grid = None
    if step:  # snap to the beat grid phased by the clear hard cuts (frame-exact)
        strong = [x["frame"] / fps for x in cuts if x["kind"] == "cut"]
        half = step / 2
        if len(strong) >= 5:
            z = np.exp(1j * np.array(strong) / half * 2 * np.pi).mean()
            if abs(z) >= 0.6:
                phase = (np.angle(z) % (2 * np.pi)) / (2 * np.pi) * half
                grid = phase + half * np.arange(0, int(n / fps / half) + 2)
        if grid is not None:
            for x in cuts:
                j = int(np.argmin(np.abs(grid - x["frame"] / fps)))
                if abs(grid[j] - x["frame"] / fps) <= max(2.0 / fps, x.get("dur", 0) / 2):
                    x["frame"] = int(round(grid[j] * fps))
                    x["on_beat"] = True
    for f in flashes:
        f.setdefault("hides_cut", False)
        f.pop("lo", None)
        f.pop("hi", None)
    for x in cuts:
        x["t"] = round(x["frame"] / fps, 3)
    sig = {"bright": bright, "sat": sat, "d1": d1, "c": c, "gray": gray, "effects": effects}
    return cuts, flashes, sig


def _moves(gray, cuts, flashes, fps):
    """Zoom punches (a burst of expansion or contraction) and shakes (a burst of jitter) inside the slots."""
    n = len(gray)
    small = [cv2.resize(g, (80, max(8, round(g.shape[0] * 80 / g.shape[1]))), interpolation=cv2.INTER_AREA) for g in gray]
    near = {c["frame"] + o for c in cuts for o in range(-3, 4)} | {f["frame"] + o for f in flashes for o in range(-3, 4)}
    div = np.zeros(n, np.float32)
    sx = np.zeros(n, np.float32)
    sy = np.zeros(n, np.float32)
    for i in range(1, n):
        if i in near:
            continue
        flow = cv2.calcOpticalFlowFarneback(small[i - 1].astype(np.uint8), small[i].astype(np.uint8), None, 0.5, 2, 9, 2, 5, 1.1, 0)
        div[i] = float(np.mean(np.gradient(flow[..., 0], axis=1) + np.gradient(flow[..., 1], axis=0)))
        sx[i], sy[i] = float(np.median(flow[..., 0])), float(np.median(flow[..., 1]))
    zt = max(0.035, float(np.percentile(np.abs(div), 90)) * 2.5)
    punches, i = [], 1
    while i < n:
        if abs(div[i]) > zt:
            j = i
            while j < n and abs(div[j]) > zt * 0.4:
                j += 1
            if j - i <= fps * 0.6:
                punches.append({"t": round(i / fps, 3), "dur": round(max(1, j - i) / fps, 3), "dir": "in" if div[i] > 0 else "out"})
            i = j + 1
        else:
            i += 1
    jit = np.abs(np.diff(sx, 2, prepend=0, append=0))[:n] + np.abs(np.diff(sy, 2, prepend=0, append=0))[:n]
    jt = max(0.6, float(np.percentile(jit, 90)) * 3)
    shakes, i = [], 1
    while i < n:
        if jit[i] > jt:
            j = i
            while j < n and jit[j] > jt * 0.4:
                j += 1
            if j - i >= max(3, fps * 0.12):
                shakes.append({"t": round(i / fps, 3), "dur": round((j - i) / fps, 3)})
            i = j + 1
        else:
            i += 1
    return punches, shakes, div


def _drop(snd, slots, seconds):
    """Where the template's drop (the high point it builds to) lands: the biggest sustained rise of loudness, where the
    cutting also gets faster (between 10% and 80% of the video); None when nothing rises."""
    if not slots or seconds < 6:
        return None
    energy = np.asarray((snd or {}).get("energy_db") or [], np.float32)
    best, best_t = 0.0, None
    for s in slots[1:]:
        t = s["start"]
        if not 0.1 * seconds <= t <= 0.8 * seconds:
            continue
        rise = 0.0
        if len(energy) > 4:
            a, b = int(t), int(t)
            before = energy[max(0, a - 4):a]
            after = energy[b:min(len(energy), b + 4)]
            if len(before) and len(after):
                rise = float(after.mean() - before.mean()) / 6.0  # dB: 6 dB louder counts as 1
        dens_b = sum(1 for x in slots if t - 4 <= x["start"] < t) / 4.0
        dens_a = sum(1 for x in slots if t <= x["start"] < t + 4) / 4.0
        score = rise + 0.5 * (dens_a - dens_b)
        if score > best:
            best, best_t = score, t
    return round(best_t, 3) if best_t is not None and best >= 0.6 else None


def learn(path, planner=None, name=None, log=print, use_cache=True, meta=None):
    """A template from a video: the exact slots and what happens in and between them. Cached and saved by name.
    meta (what the template's page says, template_meta): its number of clips makes the slots exactly that many (weak
    cuts dropped, missed ones taken back), its length trims an end card, its title and hashtags add the techniques the
    frames cannot show (slow motion, the occasion's look)."""
    path = Path(path)
    STORE.mkdir(parents=True, exist_ok=True)
    clips = int((meta or {}).get("clips") or 0)
    cp = STORE / f"_{path.stem[:40]}_{_key(path)}{f'_c{clips}' if clips else ''}.json"
    if use_cache and cp.exists():
        tpl = json.loads(cp.read_text(encoding="utf-8"))
        if tpl.get("vision") or planner is None:
            if meta:
                tpl = _with_meta(tpl, meta, planner)
            if name:
                save(tpl, name)
            return tpl
    t0 = time.perf_counter()
    info = F.probe(str(path))
    dur = float(info.get("seconds") or 0)
    fps = min(FPS_MAX, float(info.get("fps") or 30) or 30)
    if dur < 1.5:
        raise ValueError(f"{path.name}: too short to be a template")
    fr = F.window(str(path), 0, dur, fps=fps, width=112)
    snd = AU.analyze(str(path)) if info.get("has_audio") else None
    beats = (snd or {}).get("beats") or []
    bpm = (snd or {}).get("bpm")
    steady_beat = beats if (snd or {}).get("beat_confidence", 0) > 0.12 else None
    cuts, flashes, sig = detect_cuts(fr, fps, decode_gray(path, dur, fps), steady_beat)
    notes = []
    page_s = float((meta or {}).get("seconds") or 0)
    if page_s and len(fr) / fps > page_s + 0.4:  # a preview with an end card (a logo, a watermark): the template ends earlier
        keep = int(round(page_s * fps))
        fr = fr[:keep]
        cuts = [c for c in cuts if c["frame"] < keep - 2]
        flashes = [f for f in flashes if f["frame"] < keep]
        sig = {**sig, "gray": sig["gray"][:keep], "d1": sig["d1"][:keep], "bright": sig["bright"][:keep], "sat": sig["sat"][:keep],
               "rejected": [r for r in sig.get("rejected") or [] if r["frame"] < keep - 2]}
        notes.append(f"the preview runs {dur:.1f} s; the template is {page_s:.1f} s (an end card was left out)")
    n = len(fr)
    if clips:
        cuts, cn = constrain_cuts(cuts, clips - 1, sig.get("rejected") or [], n, fps, steady_beat)
        notes += cn
        for f in flashes:  # a flash whose cut was left out is a flash inside a shot again
            f["hides_cut"] = any(abs(c["frame"] - f["frame"]) <= 2 for c in cuts if c["kind"] == "flash")
    punches, shakes, div = _moves(sig["gray"], cuts, flashes, fps)
    bt = np.array(beats) if beats else None
    times = [0.0] + [c["t"] for c in cuts] + [round(n / fps, 3)]
    slots = []
    for k in range(len(times) - 1):
        a, b = times[k], times[k + 1]
        ia, ib = int(round(a * fps)), int(round(b * fps))
        inner = list(range(min(n - 1, ia + 2), max(ia + 3, ib - 2)))
        inner = [i for i in inner if 0 <= i < n] or [min(n - 1, ia)]
        s = {"n": k + 1, "start": round(a, 3), "end": round(b, 3), "dur": round(b - a, 3),
             "motion": round(float(np.mean(sig["d1"][inner])), 4), "brightness": round(float(np.mean(sig["bright"][inner])), 3),
             "saturation": round(float(np.mean(sig["sat"][inner])), 3),
             "zoom": round(float(np.mean(div[inner])), 4),
             "into": cuts[k - 1]["kind"] if k else "start", "into_dur": cuts[k - 1]["dur"] if k else 0.0}
        if k and cuts[k - 1].get("guessed"):
            s["guessed"] = True  # the preview does not show this cut: placed on a beat
        if bt is not None and len(bt):
            s["on_beat"] = bool(np.min(np.abs(bt - a)) <= 0.07) if k else True
        s["punches"] = [p for p in punches if a <= p["t"] < b]
        s["shakes"] = [x for x in shakes if a <= x["t"] < b]
        s["flashes"] = [f for f in flashes if a <= f["t"] < b and not f["hides_cut"]]
        slots.append(s)
    # shot size from faces in each slot's middle frame (a bigger frame for the detector)
    mids = [round((s["start"] + s["end"]) / 2, 3) for s in slots]
    big = F.frames_at(str(path), mids, width=480)
    for s, fimg in zip(slots, big):
        fc = F.faces(fimg) if fimg is not None else []
        area = max((f["box"][2] * f["box"][3] for f in fc), default=0.0)
        s["face"] = round(area, 4)
        s["size"] = "close-up" if area >= 0.06 else "medium" if area >= 0.015 else "wide-person" if area >= 0.002 else "no-face"
    sat_all = float(np.median([s["saturation"] for s in slots])) if slots else 0
    for s in slots:
        s["bw"] = bool(s["saturation"] < 0.06 and sat_all > 0.12)
    cpm = len(cuts) / max(1e-3, n / fps / 60)
    if bpm and bpm < 95 and cpm > 0.45 * bpm:  # cutting that fast means the beat was heard at half tempo
        bpm = round(bpm * 2, 1)
    drop = _drop(snd, slots, n / fps)
    for s in slots:
        s["section"] = "drop" if drop is not None and s["start"] >= drop - 0.05 else ("intro" if s["n"] == 1 else "verse")
    on_beat = [s.get("on_beat") for s in slots[1:] if s.get("on_beat") is not None]
    tpl = {"name": name or path.stem[:40], "source": str(path), "seconds": round(n / fps, 3), "fps": fps,
           "aspect": f"{info.get('width')}x{info.get('height')}", "portrait": (info.get("height") or 0) > (info.get("width") or 0),
           "bpm": bpm, "beats": [round(x, 3) for x in beats[:600]], "drop": drop,
           "cuts_on_beat": round(sum(on_beat) / len(on_beat), 2) if on_beat else None,
           "slots": slots, "flashes": flashes, "punches": punches, "shakes": shakes, "accents": sig.get("effects") or [],
           "counts": {"slots": len(slots), "cuts": sum(1 for c in cuts if c["kind"] == "cut"), "flash_cuts": sum(1 for c in cuts if c["kind"] == "flash"),
                      "dissolves": sum(1 for c in cuts if c["kind"] == "dissolve"), "motion_transitions": sum(1 for c in cuts if c["kind"] == "motion"),
                      "flashes": len(flashes), "punches": len(punches), "shakes": len(shakes)}}
    from ai_pc.video import reference as RF  # the overall look: grade, letterbox, grain, vignette
    try:
        fp = RF.fingerprint(path, None, lambda *a: None)
        tpl["look"] = {k: fp.get(k) for k in ("brightness", "contrast", "saturation", "warmth", "letterbox", "vignette", "grain")}
        tpl["look_words"] = RF.look_words(fp)
    except Exception:  # noqa: BLE001
        tpl["look"], tpl["look_words"] = {}, "natural"
    if planner is not None:
        tpl["vision"] = _read_slots(path, slots, planner, log)
    tpl["exact"] = True
    tpl["notes"] = notes
    tpl["learned_s"] = round(time.perf_counter() - t0, 1)
    cp.write_text(json.dumps(tpl, ensure_ascii=False, indent=1), encoding="utf-8")
    if meta:
        tpl = _with_meta(tpl, meta, planner)
    if name:
        save(tpl, name)
    log(f"  template {tpl['name']}: {len(slots)} slots in {tpl['seconds']} s ({tpl['counts']}), {bpm} BPM, learned in {tpl['learned_s']} s"
        + (f"; {'; '.join(notes)}" if notes else ""))
    return tpl


def _with_meta(tpl, meta, planner=None):
    """A learned template with what its page says: the page's fields and the techniques of its title and hashtags."""
    from ai_pc.video import trends as TR
    tpl = {**tpl, "meta": meta}
    tpl["techniques"] = TR.techniques(meta.get("title") or "", meta.get("tags") or [], planner=planner)
    if meta.get("title") and tpl.get("vision") is not None:
        tpl["vision"] = {**tpl["vision"], "theme": tpl["vision"].get("theme") or meta["title"]}
    return tpl


def _slug(text, fallback="template"):
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:30] or fallback


def from_meta(meta, name=None, planner=None, log=print):
    """A template from what its page says, when there is no video of it: the number of clips, the length, the format,
    and what its title and hashtags ask for (trends.techniques: slow motion, ramps, the look, B&W reveals, pushes,
    punches, shakes, the kind of cut). The slots are as even as the beat allows, in whole beats; the moves follow the
    techniques. Not exact: the template's own cut frames, texts and effects are unknown until a video of it is learned
    (template add <link> --video <preview>)."""
    from ai_pc.video import trends as TR
    tech = TR.techniques(meta.get("title") or "", meta.get("tags") or [], planner=planner)
    st = tech["settings"]
    bpm = float(st.get("bpm") or 120)
    beat = 60.0 / bpm
    per = 4 if bpm < 110 else 2  # beats per shot when the page does not say how many clips
    n = int(meta.get("clips") or 0) or max(3, min(30, round(float(meta.get("seconds") or 15.0) / (beat * per))))
    seconds = float(meta.get("seconds") or 0) or round(n * beat * per, 2)
    if seconds < 1.5:
        raise ValueError("the template is too short")
    unit = beat
    while seconds / unit < n and unit > 0.1:  # more clips than beats: half beats
        unit /= 2
    total = max(n, int(round(seconds / unit)))
    base_u, spare = divmod(total, n)
    lens = [base_u] * n
    order = ([0, n - 1] + list(range(1, n - 1))) if n > 1 else [0]
    for i in range(spare):  # spare beats: a longer opening and a held last shot first
        lens[order[i % len(order)]] += 1
    starts = [0.0]
    for x in lens[:-1]:
        starts.append(starts[-1] + x * unit)
    energetic = bool(st.get("punch") or st.get("shake") or st.get("ramp") or st.get("bw_until_drop") or st.get("cut") == "flash")
    drop_k = None
    if n >= 3 and energetic:
        target = seconds * (0.5 if st.get("bw_until_drop") else 0.35)
        drop_k = min(range(1, n), key=lambda i: abs(starts[i] - target))
    drop = round(starts[drop_k], 3) if drop_k is not None else None
    cut_kind = {"flash": ("flash", 0.3), "dissolve": ("dissolve", 0.6), "blur": ("motion", 0.4), "glitch": ("glitch", 0.35)}.get(st.get("cut"))
    slow = (st.get("speed") or 1.0) < 0.9 or bool(st.get("ramp"))
    slots, punches, shakes = [], [], []
    for k in range(n):
        a = round(starts[k], 3)
        b = round(starts[k] + lens[k] * unit, 3) if k < n - 1 else round(seconds, 3)
        s = {"n": k + 1, "start": a, "end": b, "dur": round(b - a, 3), "motion": None, "brightness": None, "saturation": None, "zoom": 0.0,
             "into": "start" if k == 0 else (cut_kind[0] if cut_kind else "cut"),
             "into_dur": 0.0 if k == 0 or not cut_kind else round(min(cut_kind[1], (b - a) / 3, (starts[k] - starts[k - 1]) / 3), 3),
             "on_beat": True, "punches": [], "shakes": [], "flashes": [], "face": None, "size": None,
             "section": "drop" if drop is not None and a >= drop - 0.05 else ("intro" if k == 0 else "verse")}
        after_drop = drop is None or a >= drop - 0.05
        if st.get("punch") and after_drop and (k or drop is not None):
            s["punches"].append({"t": a, "dur": 0.12, "dir": "in"})
        if st.get("shake") and after_drop and k and (drop_k is None or (k - drop_k) % 2 == 0):
            s["shakes"].append({"t": a, "dur": 0.4})
        if st.get("push") and not s["punches"]:
            s["push"] = float(st["push"])
        s["bw"] = bool(st.get("bw")) or bool(st.get("bw_until_drop") and not after_drop)
        if st.get("speed") and not st.get("ramp"):
            s["speed"] = float(st["speed"])
        if st.get("ramp"):
            s["ramp"] = st["ramp"]
        if slow:
            s["want_motion"] = 0.75  # slow motion shows movement best: hair, water, a turn, a jump
        punches += s["punches"]
        shakes += s["shakes"]
        slots.append(s)
    aspect = meta.get("aspect") or "9:16"
    size = meta.get("size") or {"9:16": [720, 1280], "16:9": [1280, 720], "1:1": [1080, 1080], "4:5": [1080, 1350]}.get(aspect, [720, 1280])
    look_words = st.get("look") or "natural"
    fallback = f"capcut_{meta['id']}" if meta.get("id") else _slug(" ".join((meta.get("tags") or [])[:3]) + f" {n} clips", f"template_{n}_clips")
    tpl = {"name": name or _slug(meta.get("title"), fallback), "source": meta.get("url") or meta.get("image") or "text",
           "exact": False, "meta": meta, "techniques": tech, "seconds": round(seconds, 3), "fps": 30.0, "aspect": f"{size[0]}x{size[1]}",
           "portrait": size[1] > size[0], "bpm": round(bpm, 1), "beats": [round(i * beat, 3) for i in range(int(seconds / beat) + 1)],
           "drop": drop, "cuts_on_beat": 1.0, "slots": slots, "flashes": [], "punches": punches, "shakes": shakes, "accents": [],
           "counts": {"slots": n, "cuts": (n - 1) if not cut_kind else 0, "flash_cuts": (n - 1) if cut_kind and cut_kind[0] == "flash" else 0,
                      "dissolves": (n - 1) if cut_kind and cut_kind[0] == "dissolve" else 0,
                      "motion_transitions": (n - 1) if cut_kind and cut_kind[0] in ("motion", "glitch") else 0,
                      "flashes": 0, "punches": len(punches), "shakes": len(shakes)},
           "look": {"letterbox": bool(st.get("letterbox")), "grain": 3.0 if st.get("grain") else 0.0, "vignette": 1.0},
           "look_words": look_words, "vision": {"slots": {}, "theme": meta.get("shows") or meta.get("title")},
           "notes": [f"made from the template's page ({n} clips, {seconds:.1f} s{', ' + ' '.join('#' + t for t in meta.get('tags') or []) if meta.get('tags') else ''}): "
                     f"even slots on a {bpm:.0f} BPM beat, not the template's own frames"]}
    save(tpl, tpl["name"])
    log(f"  template {tpl['name']} (from its page): {n} slots in {tpl['seconds']} s at {bpm:.0f} BPM; {TR.explain(tech)}")
    return tpl


def find(meta_id):
    """The library's template for a CapCut template id, preferring one learned from a video (exact)."""
    hits = [t for t in (load(nm) for nm in library()) if t and str((t.get("meta") or {}).get("id") or "") == str(meta_id)]
    return max(hits, key=lambda t: bool(t.get("exact", True)), default=None)


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def resolve(src, planner=None, log=print, name=None):
    """A template from whatever the client gave: a library name, a video of it, a CapCut link, a screenshot of its page,
    or words ("SLOWMO HDR, 4 clips, 15 s, #slowmo #eid")."""
    from ai_pc.video import template_meta as TM
    s = str(src).strip()
    t = load(s)
    if t:
        return t
    p = Path(s)
    if p.is_file():
        if p.suffix.lower() in IMAGE_EXT:
            if planner is None:
                raise ValueError("reading a screenshot needs the vision model")
            meta = TM.from_image(p, planner)
            return find(meta.get("id")) if meta.get("id") and find(meta.get("id")) else from_meta(meta, name, planner, log)
        return learn(p, planner, name=name or p.stem[:30], log=log)
    if re.match(r"https?://", s, re.I):
        tid, _ = TM.clean_url(s)
        known = find(tid)
        if known:
            return known
        return from_meta(TM.from_link(s), name, planner, log)
    meta = TM.from_text(s)
    if meta.get("clips") or meta.get("seconds") or meta.get("tags"):
        same = load(_slug(meta.get("title"))) if meta.get("title") else None
        if same and not name:  # the library has it (maybe from its page, with more detail): reuse it rather than overwrite
            if not meta.get("clips") or len(same.get("slots") or []) == meta["clips"]:
                return same
            name = f"{_slug(meta.get('title'))}_{meta['clips']}clips"
        return from_meta(meta, name, planner, log)
    raise ValueError(f"no template '{s}' in the library ({', '.join(library()) or 'empty'}), and it is not a video, a link, "
                     "a screenshot or a description (\"4 clips, 15 s, #slowmo\")")


def _read_slots(path, slots, planner, log):
    """One vision call per 20 slots: each slot's on-screen text (exact words, place, size, colour) and what it shows."""
    from ai_pc.llm.vlm import ask
    out = {"slots": {}}
    for g in range(0, len(slots), 20):
        group = slots[g:g + 20]
        imgs = F.frames_at(str(path), [round((s["start"] + s["end"]) / 2, 3) for s in group], width=360)
        cells = [(s, im) for s, im in zip(group, imgs) if im is not None]
        if not cells:
            continue
        sheet = F.sheet([im for _, im in cells], [f"#{s['n']} {s['start']:.1f}s" for s, _ in cells], cols=5, cell_w=240)
        try:
            d, _ = ask(planner, SLOT_SYSTEM, f"Slots {group[0]['n']}-{group[-1]['n']} of a {len(slots)}-slot template.", [sheet], tier="caption")
        except Exception as e:  # noqa: BLE001  (the numbers alone still make a template)
            log(f"  template vision read failed: {type(e).__name__}: {e}")
            continue
        if isinstance(d, dict):
            for x in d.get("slots") or []:
                try:
                    out["slots"][int(x.get("n"))] = x
                except (TypeError, ValueError):
                    continue
            out.setdefault("theme", d.get("theme"))
            out.setdefault("font_style", d.get("text_font_style"))
    return out


def save(tpl, name):
    STORE.mkdir(parents=True, exist_ok=True)
    tpl = {**tpl, "name": name}
    (STORE / f"{re.sub(r'[^a-z0-9_-]+', '_', name.lower())}.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=1), encoding="utf-8")
    return tpl


def load(name):
    p = STORE / f"{re.sub(r'[^a-z0-9_-]+', '_', str(name).lower())}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def library():
    return sorted(p.stem for p in STORE.glob("*.json") if not p.stem.startswith("_")) if STORE.exists() else []


# ------------------------------------------------------------------------------------------------ filling a template
SIZES = ["no-face", "wide-person", "medium", "close-up"]
STOPW = set("a an the of and with in on at to from by for into over under near is are his her their its this that shot video "
            "frame scene close up wide medium shows showing".split())


def _size_of(area):
    return "close-up" if area >= 0.06 else "medium" if area >= 0.015 else "wide-person" if area >= 0.002 else "no-face"


def _words(text):
    return {w for w in re.findall(r"[a-z]+", str(text or "").lower()) if len(w) > 2 and w not in STOPW}


class _Footage:
    """The client's footage as candidate moments for the slots: for a window of a file, the biggest face, the motion,
    the highlight of the nearest captioned moment, its words, and whether a camera cut inside the file falls in it."""

    def __init__(self, analyses):
        self.files = [a for a in analyses.values() if a.get("kind") in ("video", "image") and not str(a.get("file", "")).startswith(("music_", "sfx_"))]
        mots = [m for a in self.files for m in (a.get("motion") or [])]
        self.mrank = np.sort(np.asarray(mots, np.float32)) if mots else np.zeros(1, np.float32)
        self._cache = {}

    def mpct(self, v):
        return float(np.searchsorted(self.mrank, v)) / max(1, len(self.mrank))

    def windows(self, a, need):
        """Start times worth trying in file a for a slot of `need` seconds."""
        if a.get("kind") == "image":
            return [0.0]
        dur = float(a.get("seconds") or 0)
        if dur < 0.2:
            return []
        if need >= dur - 0.05:
            return [0.0]
        return [round(t, 2) for t in np.arange(0.0, dur - need - 0.05, 0.5)] + [round(max(0.0, dur - need - 0.06), 2)]

    def feat(self, a, t0, need):
        key = (a["file"], t0, round(need, 1))
        if key in self._cache:
            return self._cache[key]
        if a.get("kind") == "image":
            f = (a.get("faces") or [])
            area = max((x["box"][2] * x["box"][3] for x in f), default=0.0)
            cap = a.get("caption") or {}
            out = {"face": area, "motion": 0.0, "mp": 0.0, "highlight": float(cap.get("highlight") or 5), "cut_inside": False,
                   "words": _words(" ".join(str(cap.get(k) or "") for k in ("shot", "subject", "action", "setting"))),
                   "brightness": 0.5, "shot": cap.get("shot")}
            self._cache[key] = out
            return out
        t1 = t0 + need
        faces = [max((x["box"][2] * x["box"][3] for x in fr["faces"]), default=0.0) for fr in a.get("faces") or [] if t0 - 0.1 <= fr["t"] <= t1 + 0.1]
        times, mot = a.get("times") or [], a.get("motion") or []
        ms = [m for t, m in zip(times, mot) if t0 <= t <= t1]
        motion = float(np.mean(ms)) if ms else 0.0
        moms = [m for m in a.get("moments") or [] if t0 - 1.5 <= m["t"] <= t1 + 1.5]
        near = min(moms, key=lambda m: abs(m["t"] - (t0 + t1) / 2)) if moms else None
        hl = max((float(m.get("highlight") or 5) for m in moms), default=5.0)
        cuts = [s["start"] for s in a.get("shots") or []][1:]
        shot = next((s for s in a.get("shots") or [] if s["start"] <= (t0 + t1) / 2 < s["end"]), {})
        out = {"face": max(faces, default=0.0), "motion": motion, "mp": self.mpct(motion), "highlight": hl,
               "cut_inside": any(t0 + 0.08 < c_ < t1 - 0.08 for c_ in cuts),
               "words": _words(" ".join(str((near or {}).get(k) or "") for k in ("shot", "subject", "action", "setting")) + " " + str(a.get("summary") or "")),
               "brightness": float((shot.get("look") or {}).get("brightness", 0.5)), "shot": (near or {}).get("shot")}
        self._cache[key] = out
        return out


def _hero_slots(tpl):
    """The slots an editor fills first: the one the drop lands in, the longest after the first third, the opening."""
    slots = tpl["slots"]
    out = []
    drop = tpl.get("drop")
    if drop is not None:
        s = next((s for s in slots if s["start"] - 0.05 <= drop < s["end"]), None)
        if s:
            out.append(s["n"])
    later = [s for s in slots if s["start"] >= tpl["seconds"] / 3]
    if later:
        out.append(max(later, key=lambda s: s["dur"])["n"])
    out.append(slots[0]["n"])
    return list(dict.fromkeys(out))


def assign(tpl, analyses, pins=None, avoid=(), log=print):
    """Each slot -> (file, start in the file, score, why). Hero slots first, then the longest; a moment is never used
    twice; the same file twice in a row only when nothing else fits."""
    foot = _Footage(analyses)
    files = [a for a in foot.files if a["file"].lower() not in {str(f).lower() for f in avoid}] or foot.files
    if not files:
        raise ValueError("no usable video or photo for the template")
    slots = tpl["slots"]
    vis = (tpl.get("vision") or {}).get("slots") or {}
    tm = np.sort(np.asarray([s["motion"] for s in slots if s.get("motion") is not None] or [0.0], np.float32))
    heroes = set(_hero_slots(tpl))
    order = sorted(slots, key=lambda s: (s["n"] not in heroes, -s["dur"]))
    used, uses, out = {}, {}, {}
    pins = {int(k): v for k, v in (pins or {}).items()}
    for s in order:
        # footage the slot plays: slow motion needs less of the file, a speed ramp more (src_factor, set by fill)
        need = max(0.15, (s["dur"] + (s.get("into_dur") or 0) * 0.5) * float(s.get("src_factor") or 1.0))
        # a slot learned from a video has a shot size, motion and brightness to match; one made from a template's page
        # has none (only, for slow motion, a wish for movement)
        slot_mp = float(np.searchsorted(tm, s["motion"])) / max(1, len(tm)) if s.get("motion") is not None else s.get("want_motion")
        sw = _words((vis.get(s["n"]) or vis.get(str(s["n"])) or {}).get("shows"))
        si = SIZES.index(s["size"]) if s.get("size") in SIZES else None
        best = None
        pool = [a for a in files if a["file"] == pins[s["n"]]] if s["n"] in pins else files
        for a in pool:
            for t0 in foot.windows(a, need):
                if any(t0 < u0 + un - 0.05 and u0 < t0 + need - 0.05 for u0, un in used.get(a["file"], [])):
                    continue  # that moment (or part of it) is already in the edit
                f = foot.feat(a, t0, need)
                ci = SIZES.index(_size_of(f["face"]))
                sc = 0.15 * f["highlight"] * (2.0 if s["n"] in heroes else 0.6)
                if si is not None:
                    sc -= 0.8 * abs(si - ci)
                if slot_mp is not None:
                    sc -= 1.2 * abs(slot_mp - f["mp"])
                if sw and f["words"]:
                    sc += 1.5 * len(sw & f["words"]) / max(1, len(sw))
                if f["cut_inside"]:
                    sc -= 3.0
                if s.get("brightness") is not None:
                    sc -= 0.5 * abs(s["brightness"] - f["brightness"])
                sc -= 0.25 * uses.get(a["file"], 0)
                for nb in (s["n"] - 1, s["n"] + 1):  # the same file next to itself looks like a jump cut
                    if out.get(nb, (None,))[0] == a["file"]:
                        sc -= 1.0
                if best is None or sc > best[2]:
                    why = ", ".join(x for x in (f"{SIZES[ci]} for {SIZES[si]}" if si is not None else None,
                                                f"motion {f['mp']:.0%} for {slot_mp:.0%}" if slot_mp is not None else None,
                                                f"highlight {f['highlight']:.0f}") if x)
                    best = (a["file"], t0, sc, why)
        if best is None:  # every moment used: the longest file again from its start
            a = max(files, key=lambda a: float(a.get("seconds") or 0))
            best = (a["file"], 0.0, -9.0, "no unused moment left: re-used")
        out[s["n"]] = best
        used.setdefault(best[0], []).append((best[1], need))
        uses[best[0]] = uses.get(best[0], 0) + 1
    return out


def _music_for(tpl, analyses, request, plan_music):
    """(music edit, analysis entries to add, info): the client's song, or a bed at the template's tempo with its drop
    where the template's is and its beats lined up with the template's cuts."""
    from ai_pc.media import music as MU
    from ai_pc.video import analyze as AN
    total = float(tpl["seconds"])
    if plan_music == "none":
        return None, {}, "no music (asked)"
    if isinstance(plan_music, dict) and plan_music.get("file"):
        a = next((a for a in analyses.values() if a.get("file", "").lower() == str(plan_music["file"]).lower()), None)
        if a:
            return {"id": "music", "type": "audio", "file": a["file"], "at": 0, "from": float(plan_music.get("from", 0) or 0), "duration": total,
                    "volume": 0.85, "fade_out": 1.0, "expect": "the client's music under the template"}, {}, f"your music {a['file']}"
    cpm = (len(tpl["slots"]) - 1) / max(1e-3, total / 60)
    req = str(request or "").lower()
    from ai_pc.video.quick_edits import GENRE_RE
    genre = next((g for g, p in GENRE_RE.items() if p.search(req)), None) if req else None
    if isinstance(plan_music, dict) and plan_music.get("generate"):
        genre = plan_music["generate"]
    genre = genre or ("hype" if cpm >= 42 else "pop" if cpm >= 16 else "cinematic")
    bpm = tpl.get("bpm") or (140 if cpm >= 35 else 118 if cpm >= 18 else 84)
    if isinstance(plan_music, dict) and plan_music.get("bpm"):
        bpm = plan_music["bpm"]
    bpm = int(round(bpm))
    beat = 60.0 / bpm
    drop = tpl.get("drop")
    path, grid = MU.bed(genre, total + beat, bpm=bpm, drop_at=drop if drop is not None else None)
    cuts = [s["start"] for s in tpl["slots"][1:]]  # the phase of the template's cuts on the beat grid
    off = 0.0
    if cuts:
        z = np.exp(1j * np.array(cuts) / beat * 2 * np.pi).mean()
        if abs(z) > 0.5:
            phase = (np.angle(z) % (2 * np.pi)) / (2 * np.pi) * beat
            off = round((beat - phase) % beat, 4)
    AN.analyze([str(path)], planner=None, log=lambda *a: None)
    entry = {path.name: {"file": path.name, "path": str(path), "kind": "audio", "seconds": total + beat,
                         "sound": {"kind": "music", "bpm": grid["bpm"], "beats": grid["beats"], "drop": grid["drop"]}}}
    return ({"id": "music", "type": "audio", "file": path.name, "at": 0, "from": off, "duration": total, "volume": 0.85, "fade_out": 1.0,
             "expect": f"a generated {genre} beat at {bpm} BPM, its beats on the template's cuts"}, entry,
            f"generated {genre} at {bpm} BPM (a template's own song is licensed inside CapCut)")


def settings(tpl, request=""):
    """The template's trend settings (from its title and hashtags, trends.techniques) with what the client's words
    change: slow motion or a speed ramp asked for or refused, the occasion's greeting asked for or refused."""
    st = dict(((tpl.get("techniques") or {}).get("settings")) or {})
    req = str(request or "").lower()
    if re.search(r"\b(?:no|without|skip|not in)\s+(?:the\s+|any\s+)?(?:slow ?-?mo(?:tion)?|speed ?ramps?|ramps?)\b|\bnormal speed\b|\breal ?-?time\b", req):
        st["normal_speed"] = True
    elif re.search(r"\bvelocity\b|\bspeed ?ramps?\b", req):
        st["speed_override"] = "ramp"
    elif re.search(r"\bslow ?-?mo(?:tion)?\b|\bslow(?:ed)? down\b|\bin slow\b", req) and not st.get("ramp"):
        st["speed_override"] = min(float(st.get("speed") or 1.0), 0.5)
    if re.search(r"\b(?:no|without|skip)\s+(?:the\s+|any\s+)?(?:greeting|text|words|title)\b", req):
        st.pop("greeting", None)
    elif re.search(r"greeting|\bwish(?:es)?\b|mubarak|happy birthday|\bhbd\b|(?:add|put|with)\s+(?:the\s+|a\s+)?(?:text|title|greeting)", req):
        st["greeting_asked"] = True
        if not st.get("greeting"):  # the client's own occasion ("eid mubarak" on a template without that tag)
            from ai_pc.video import trends as TR
            g = TR.techniques("", (), request)["settings"].get("greeting")
            if g:
                st["greeting"] = g
    return st


def _slot_speed(s, st):
    """(speed, ramp) for a slot: what the client asked for (normal speed, slow motion, ramps), else the slot's own, else
    the template's techniques."""
    if st.get("normal_speed"):
        return 1.0, None
    o = st.get("speed_override")
    if o is not None:
        return (1.0, "fast-slow-fast") if o == "ramp" else (float(o), None)
    ramp = s.get("ramp") or st.get("ramp")
    if ramp:
        return 1.0, ramp
    return float(s.get("speed") or st.get("speed") or 1.0), None


def fill(tpl, analyses, request="", music=None, canvas=None, pins=None, avoid=(), texts=None, log=print, speed=None, chat=False):
    """The template's slots filled with the client's footage, as a plan (editplan schema) + info.
    speed: the client's choice from a chat ("normal", "ramp" or a factor), over the template's. chat: a re-fill during a
    chat, where speed and greetings come only as explicit changes (the words of earlier turns are not read again)."""
    from ai_pc.video import trends as TR
    from ai_pc.video.cutting import VEL, VEL_SPLIT
    from ai_pc.video.quick_edits import COLOURS, _effect_key, _font_for, _intro_for, _look_for, _texture_item, _transition_for
    ramp_factor = sum(v * f for v, f in zip(VEL, VEL_SPLIT))  # a fast-slow-fast ramp plays ~1.2x its length of the file
    st = settings(tpl, "" if chat else request)
    if speed == "normal":
        st["normal_speed"] = True
    elif speed is not None:
        st.pop("normal_speed", None)
        st["speed_override"] = speed if speed == "ramp" else float(speed)
    if music is None and st.get("music"):
        music = {"generate": st["music"]}
    slots = [dict(s) for s in tpl["slots"]]
    if not slots:
        raise ValueError("the template has no slots")
    merged = []  # a sliver under 0.2 s next to a soft transition is part of that transition, not a shot of its own
    for k, s in enumerate(slots):
        nxt = slots[k + 1] if k + 1 < len(slots) else None
        soft = s.get("into") in ("dissolve", "motion") or (nxt is not None and nxt.get("into") in ("dissolve", "motion"))
        if merged and s["dur"] < 0.2 and soft:
            merged[-1]["end"] = s["end"]
            merged[-1]["dur"] = round(merged[-1]["end"] - merged[-1]["start"], 3)
            continue
        merged.append(s)
    slots = merged
    for s in slots:
        sp, ramp = _slot_speed(s, st)
        s["src_factor"] = ramp_factor if ramp else sp
    tpl = {**tpl, "slots": slots}
    picks = assign(tpl, analyses, pins, avoid, log)
    byfile = {a["file"]: a for a in analyses.values() if a.get("file")}
    clips, edits, approx, offers = [], [], [], []
    speeds = {}
    for s in slots:
        f, t0, sc, why = picks[s["n"]]
        a = byfile.get(f, {})
        c = {"id": f"t{s['n']}", "file": f, "from": round(t0, 3), "duration": round(s["dur"], 3), "reframe": "subject"}
        if a.get("kind") == "image":
            c.pop("from")
        elif a.get("kind") == "video":
            sp, ramp = _slot_speed(s, st)
            left = float(a.get("seconds") or 0) - t0 - 0.05
            if ramp and left >= s["dur"] * ramp_factor:
                d1, d2 = s["dur"] * VEL_SPLIT[0], s["dur"] * VEL_SPLIT[1]
                c["ramp"] = [[0, VEL[0]], [round(VEL[0] * d1, 3), VEL[1]], [round(VEL[0] * d1 + VEL[1] * d2, 3), VEL[2]]]
                speeds[c["id"]] = "ramp"
            else:
                if ramp:
                    approx.append(f"slot {s['n']}: {f} is too short for a speed ramp; plain speed")
                if left < s["dur"] * sp - 0.01:  # the file ends first: slow the slot down to fill it (the template's timing stays)
                    fit = max(0.25, left / s["dur"])
                    if fit < sp:
                        approx.append(f"slot {s['n']}: {f} is short, played at {fit:.2f}x to fill the slot")
                        sp = fit
                if abs(sp - 1.0) > 0.01:
                    c["speed"] = round(sp, 3)
                    speeds[c["id"]] = round(sp, 3)
        if s.get("size") == "close-up":  # the template is close here: frame the face closer when the footage is wider
            ff = [fr for fr in a.get("faces") or [] if t0 <= fr["t"] <= t0 + s["dur"] and fr["faces"]]
            if ff:
                fb = max(ff, key=lambda fr: fr["faces"][0]["box"][2] * fr["faces"][0]["box"][3])["faces"][0]["box"]
                area = fb[2] * fb[3]
                if 0.002 < area < 0.04:
                    c["reframe"] = {"x": round(fb[0] + fb[2] / 2, 3), "y": round(fb[1] + fb[3] / 2, 3), "zoom": round(min(2.2, (0.06 / area) ** 0.5), 2)}
        clips.append(c)
    names = {}
    for k, s in enumerate(slots[1:], start=1):  # transitions at the template's cuts
        prev = f"t{slots[k - 1]['n']}"
        kind, dur = s.get("into"), float(s.get("into_dur") or 0)
        fam = {"dissolve": "dissolve", "motion": "blur", "flash": "flash", "glitch": "glitch"}.get(kind)
        if not fam:
            continue
        if fam not in names:
            names[fam] = _transition_for(fam)
        name, d0 = names[fam]
        if not name:
            approx.append(f"no free {fam} transition works here: hard cut at {s['start']:.1f} s")
            continue
        edits.append({"id": f"tt{s['n']}", "type": "transition", "after": prev, "name": name,
                      "duration": round(min(1.2, max(0.2, dur or d0)), 2), "expect": f"a {fam} transition into slot {s['n']}"})
    wf = _effect_key("white flash", "flash")
    bw = None
    for s in slots:
        cid = f"t{s['n']}"
        for p in s.get("punches") or []:
            edits.append({"id": f"tz{len(edits)}", "type": "zoom", "on": cid, "start": round(max(0.0, p["t"] - s["start"]), 3),
                          "duration": round(min(0.6, max(0.2, p["dur"] * 2)), 3), "to": 1.18 if p.get("dir") == "in" else 1.12, "back": True,
                          "expect": "a zoom punch where the template has one"})
        for x in s.get("shakes") or []:
            edits.append({"id": f"ts{len(edits)}", "type": "shake", "on": cid, "start": round(max(0.0, x["t"] - s["start"]), 3),
                          "duration": round(min(1.2, max(0.25, x["dur"])), 3), "strength": 0.5, "expect": "the picture shakes where the template does"})
        for fl in s.get("flashes") or []:
            if wf:
                edits.append({"id": f"tf{len(edits)}", "type": "effect", "name": wf.split(":", 1)[1], "start": round(max(0.0, fl["start"]), 3),
                              "duration": round(max(0.15, fl["end"] - fl["start"]), 3), "expect": "a white flash where the template has one"})
        if s.get("bw"):
            bw = bw or _look_for("black and white monochrome gray classic")
            if bw:
                edits.append({"id": f"tb{s['n']}", "type": "filter", "name": bw, "on": cid, "strength": 100, "expect": "this slot in black and white, as in the template"})
        # a slow push-in: the template's (3D zoom, photo dumps), or on a photo that would otherwise stand still
        image = byfile.get(picks[s["n"]][0], {}).get("kind") == "image"
        push = s.get("push") or (st.get("push") if image else None) or (1.06 if image and s["dur"] >= 1.0 else None)
        if push and not s.get("punches") and not s.get("shakes"):
            edits.append({"id": f"tk{s['n']}", "type": "keyframes", "on": cid, "property": "scale", "points": [[0, 1.0], [round(s["dur"], 3), round(float(push), 3)]],
                          "expect": "the shot slowly pushes in"})
    look_words = tpl.get("look_words") or "natural"
    if st.get("look") and tpl.get("exact", True) and st["look"] not in look_words:  # the title's look (HDR, Eid...) with the measured one
        look_words = f"{st['look']} {look_words}"
    look = _look_for(look_words)  # the look over the whole video
    if look and not all(s.get("bw") for s in slots):
        edits.append({"id": "tgrade", "type": "filter", "name": look, "start": 0, "duration": round(tpl["seconds"], 3), "strength": 60,
                      "expect": f"the template's look ({look_words})"})
    lk = tpl.get("look") or {}
    for what, on in (("letterbox", bool(lk.get("letterbox") or st.get("letterbox"))), ("grain", (lk.get("grain") or 0) >= 2.5 or bool(st.get("grain"))),
                     ("vignette", (lk.get("vignette") or 1) < 0.8)):
        if on:
            it = _texture_item(what)
            if it:
                edits.append({"id": f"tx_{what}", "type": "effect", "name": it, "start": 0, "duration": round(tpl["seconds"], 3), "layer": "texture",
                              "expect": f"{what} as in the template"})
    vis = (tpl.get("vision") or {}).get("slots") or {}  # texts where the template has them (its words, or the client's)
    runs = []
    for s in slots:
        v = vis.get(s["n"]) or vis.get(str(s["n"])) or {}
        t = str(v.get("text") or "").strip()
        if not t:
            continue
        if runs and runs[-1]["text"].lower() == t.lower() and runs[-1]["end_n"] == s["n"] - 1:
            runs[-1].update(end=s["end"], end_n=s["n"])
        else:
            runs.append({"text": t, "start": s["start"], "end": s["end"], "end_n": s["n"], "v": v})
    own = list(texts or []) or [a or b for a, b in re.findall(r'"([^"]+)"|(?<![A-Za-z])\'([^\']+)\'(?![A-Za-z])', str(request or ""))]
    portrait = bool(tpl.get("portrait"))
    font = _font_for((tpl.get("vision") or {}).get("font_style") or "bold sans") if runs else None
    for k, r in enumerate(runs):
        v = r["v"]
        size = {"small": 8, "medium": 11, "large": 15, "huge": 20}.get(str(v.get("text_size") or "medium"), 11) * (1.0 if portrait else 0.75)
        col = str(v.get("text_colour") or "white").lower()
        hexc = next((h for name, h in COLOURS.items() if name in col), "#FFFFFF")
        words = own[k] if k < len(own) else r["text"]
        pos = str(v.get("text_position") or "center")
        edits.append({"id": f"tw{k + 1}", "type": "text", "text": words, "start": round(r["start"], 3), "duration": round(max(0.6, r["end"] - r["start"]), 3),
                      "position": pos if pos in ("top", "upper", "center", "lower", "bottom") else "center", "size": round(size, 1),
                      "font": font, "color": hexc, "bold": True, "outline": {"color": "#000000", "width": 50},
                      "expect": f"the text '{words[:30]}' where the template shows '{r['text'][:30]}'"})
    if runs and not own:
        approx.append(f"the template's own words were kept ({', '.join(repr(r['text'][:20]) for r in runs[:3])}); give yours in quotes to replace them")
    if own and not runs:  # the client's words, and the template shows none (or is not known to): a title over the opening
        s0 = slots[0]
        edits.append({"id": "tw1", "type": "text", "text": own[0], "start": round(min(0.2, s0["dur"] / 5), 3),
                      "duration": round(max(1.2, min(s0["dur"] - 0.2, 3.5)), 3), "position": "center",
                      "size": round(12 * (1.0 if portrait else 0.75), 1), "font": _font_for((tpl.get("vision") or {}).get("font_style") or "bold sans"),
                      "color": "#FFFFFF", "bold": True, "outline": {"color": "#000000", "width": 50}, "intro": _intro_for("pop in"),
                      "expect": f"the text '{own[0][:30]}' over the opening"})
    g = st.get("greeting")
    if g and not runs and not (own and own[0].lower() == g.lower()):  # the occasion's greeting (#eid -> Eid Mubarak): only when asked for
        if st.get("greeting_asked"):
            s0 = slots[0] if not own else slots[-1]  # the client's title has the opening: the greeting closes
            festive = not re.search(r"birthday", g, re.I)
            edits.append({"id": "tgreet", "type": "text", "text": g, "start": round(s0["start"] + min(0.3, s0["dur"] / 4), 3),
                          "duration": round(max(1.0, min(tpl["seconds"] - s0["start"] - 0.3, max(s0["dur"] - 0.3, 2.5))), 3),
                          "position": "lower", "size": round(13 * (1.0 if tpl.get("portrait") else 0.75), 1),
                          "font": _font_for("elegant script" if festive else "playful rounded bold"),
                          "color": "#F7D774" if festive else "#FFFFFF", "bold": not festive,
                          "shadow": {"color": "#000000", "alpha": 0.7, "diffuse": 20}, "intro": _intro_for("fade in soft"),
                          "expect": f"the greeting '{g}' over the opening"})
        elif not chat:
            offers.append(f"its tags suggest the greeting '{g}': say \"add {g}\" to put it on")
    m, entry, minfo = _music_for(tpl, analyses, request, music)
    analyses.update(entry)
    if m:
        edits.insert(0, m)
    exact = tpl.get("exact", True)
    if not exact:
        approx.insert(0, "made from the template's page, not its video: the slot count and length are the template's, the cut frames are even "
                         "beats and the moves come from its title and tags; give a video of it for an exact copy")
    reqs = [{"ask": f"follow the template '{tpl.get('name')}'",
             "how": f"{len(slots)} slots " + ("on its exact cut frames" if exact else "on the beat, as its page describes") + ", filled with your footage",
             "edits": ["template_match"], "confidence": "high" if exact else "medium"}]  # evidence: the export's cuts against the plan's
    if speeds:
        kinds = sorted({str(v) for v in speeds.values()})
        reqs.append({"ask": "slow motion" if "ramp" not in kinds else "speed ramps",
                     "how": "fast-slow-fast ramps" if kinds == ["ramp"] else f"slots at {', '.join(k + ('x' if k != 'ramp' else '') for k in kinds)}",
                     "edits": [f"{cid}:speed" for cid in list(speeds)[:12]], "confidence": "high"})
    if st.get("look") and any(e["id"] == "tgrade" for e in edits):
        reqs.append({"ask": f"the look its title and tags ask for ({st['look']})", "how": f"filter {look}", "edits": ["tgrade"], "confidence": "medium"})
    if any(e["id"] == "tgreet" for e in edits):
        reqs.append({"ask": f"the greeting '{g}'", "how": "over the opening", "edits": ["tgreet"], "confidence": "high"})
    moves = [e["id"] for e in edits if e["type"] in ("transition", "zoom", "shake") or str(e["id"]).startswith("tf")]
    if moves:
        reqs.append({"ask": "the template's transitions, flashes and moves", "how": "the same kinds at the same frames", "edits": moves[:12],
                     "confidence": "medium"})
    tws = [e["id"] for e in edits if e["type"] == "text"]
    if own and tws:
        reqs.append({"ask": f"text {', '.join(repr(x) for x in own[:3])}", "how": "where the template has its text", "edits": tws, "confidence": "high"})
    if m:
        reqs.append({"ask": "music", "how": minfo, "edits": ["music"], "confidence": "high"})
    plan = {"name": f"tpl_{tpl.get('name', 'template')}"[:40], "canvas": canvas or ("9:16" if portrait else "16:9"),
            "platform": None, "clips": clips, "layers": [], "edits": edits,
            "think": {"concept": f"the template '{tpl.get('name')}' with the client's footage", "requirements": reqs},
            "_template": {"name": tpl.get("name"), "slots": len(slots), "cuts": [s["start"] for s in slots[1:]], "exact": exact,
                          "techniques": TR.explain(tpl.get("techniques") or {})},
            "_rhythm": {"bpm": tpl.get("bpm"), "drop": tpl.get("drop"), "source": "template", "shots": len(slots),
                        "sections": [{"name": "drop" if tpl.get("drop") is not None and s["start"] >= tpl["drop"] else "verse",
                                      "start": s["start"], "end": s["end"]} for s in slots]}}
    info = {"template": tpl.get("name"), "slots": len(slots), "music": minfo, "approximations": approx, "offers": offers, "exact": exact,
            "techniques": TR.explain(tpl.get("techniques") or {}), "notes": list(tpl.get("notes") or []),
            "assignments": [{"slot": n, "file": picks[n][0], "from": picks[n][1], "score": round(picks[n][2], 2), "why": picks[n][3]}
                            for n in sorted(picks)]}
    log(f"template {tpl.get('name')}: {len(slots)} slots filled from {len({p[0] for p in picks.values()})} files; music: {minfo}"
        + (f"; approximations: {len(approx)}" if approx else ""))
    return plan, info


def suggest(request="", analyses=None, k=3):
    """The library's templates that fit a request and the footage, best first: [{name, score, why, clips, seconds,
    exact}]. What counts: the trends the request names (slow motion, eid, glow-up...) against the template's title and
    tags, other shared words, the number of clips asked for, the length asked for, the format, whether there is enough
    footage for its slots, a video-learned (exact) copy over one made from a page, and a little for popularity."""
    from ai_pc.video import trends as TR
    req = str(request or "")
    want = {m[1] for m in TR.techniques("", (), req)["matched"]}
    rw = _words(req) - {"template", "templates", "edit", "video", "clips", "clip", "seconds", "make", "want", "any", "use", "like"}
    m = re.search(r"\b(\d{1,2})\s*(?:clips?|photos?|videos?|slots?|shots?|pics?|pictures?)\b", req, re.I)
    asked_clips = int(m.group(1)) if m else None
    m = re.search(r"\b(\d{1,3})\s*(?:s|sec|secs|seconds?)\b", req, re.I)
    asked_s = float(m.group(1)) if m else None
    portrait = True if re.search(r"\b(?:9:16|tiktok|reels?|shorts|vertical|portrait|status)\b", req, re.I) else \
        False if re.search(r"\b(?:16:9|youtube|horizontal|landscape)\b", req, re.I) else None
    moments = None
    if analyses:
        vids = [a for a in analyses.values() if a.get("kind") in ("video", "image") and not str(a.get("file", "")).startswith(("music_", "sfx_"))]
        moments = sum(1 if a.get("kind") == "image" else max(1, int(float(a.get("seconds") or 0) // 1.5)) for a in vids)
    out = []
    for name in library():
        t = load(name)
        if not t or not t.get("slots"):
            continue
        meta = t.get("meta") or {}
        tech = t.get("techniques") or TR.techniques(meta.get("title") or t["name"].replace("_", " "), meta.get("tags") or [])
        has = {x[1] for x in tech.get("matched") or []}
        words = _words(" ".join([t["name"].replace("_", " "), str(meta.get("title") or ""), " ".join(meta.get("tags") or []),
                                 str((t.get("vision") or {}).get("theme") or "")]))
        n = len(t["slots"])
        sc, why = 0.0, []
        if want & has:
            sc += 2.0 * len(want & has)
            why.append("has " + ", ".join(sorted(want & has)))
        if want - has:
            sc -= 0.5 * len(want - has)
        shared = {w for w in rw & words if w not in want & has}  # "eid" counted once, as the trend
        if shared:
            sc += min(3, len(shared)) * 0.8
            why.append("matches " + ", ".join(sorted(shared)[:3]))
        if asked_clips:
            sc -= 0.6 * abs(n - asked_clips)
            if n == asked_clips:
                why.append(f"{n} clips")
        if asked_s:
            sc -= abs(float(t["seconds"]) - asked_s) / 5.0
        if portrait is not None and bool(t.get("portrait")) != portrait:
            sc -= 1.0
        if moments is not None and n > 1.5 * moments:  # a few moments again (with another crop) is fine; most of them is not
            sc -= 1.0
            why.append(f"needs {n} moments, the footage has ~{moments}")
        if t.get("exact", True):
            sc += 0.5
        uses = int(meta.get("uses") or 0)
        if uses:
            sc += 0.1 * np.log10(uses + 1)
        out.append({"name": name, "score": round(sc, 2), "why": "; ".join(why) or "no strong match", "clips": n,
                    "seconds": t.get("seconds"), "exact": bool(t.get("exact", True)), "title": meta.get("title"), "uses": uses or None})
    out.sort(key=lambda x: -x["score"])
    return out[:k]


def match(tpl, video, cuts_planned=None):
    """How exactly an exported video follows the template: its cuts (found the same way) against the template's."""
    info = F.probe(str(video))
    fps = min(FPS_MAX, float(info.get("fps") or 30) or 30)
    fr = F.window(str(video), 0, float(info["seconds"]), fps=fps, width=112)
    gb = decode_gray(video, float(info["seconds"]), fps)
    cuts, _, _ = detect_cuts(fr, fps, gb)
    want = cuts_planned if cuts_planned is not None else [s["start"] for s in tpl["slots"][1:]]
    got = [c["t"] for c in cuts]
    used, hits = set(), 0
    for w in want:
        j = min((j for j in range(len(got)) if j not in used and abs(got[j] - w) <= 2.5 / fps), key=lambda j: abs(got[j] - w), default=None)
        if j is not None:
            used.add(j)
            hits += 1
    return {"template_cuts": len(want), "found_on_time": hits, "extra": len(got) - len(used),
            "rhythm_match": round(hits / max(1, len(want)), 3), "length": round(float(info["seconds"]), 2), "template_length": tpl.get("seconds")}


# ------------------------------------------------------------------------------------------------ follow-ups on a template edit
def apply_design(d, ops, ctx=None):
    """Structural follow-ups on a template edit: footage choices, music, format. Timing and pacing belong to the
    template. Returns (design, done, failed)."""
    import copy

    from ai_pc.video.quick_edits import describe
    d = copy.deepcopy(d)
    tpl = load(d["template"]) or {}
    slots = tpl.get("slots") or []
    pins = {str(k): v for k, v in (d.get("pins") or {}).items()}
    done, failed = [], []
    for op in ops:
        k = op.get("op")
        if k == "avoid_file":
            d["avoid_files"] = sorted(set(d.get("avoid_files") or []) | {op["file"]})
            pins = {n: f for n, f in pins.items() if f.lower() != op["file"].lower()}
            done.append(f"not using {op['file']}")
        elif k == "unavoid_file":
            d["avoid_files"] = [f for f in d.get("avoid_files") or [] if f.lower() != op["file"].lower()]
            done.append(f"{op['file']} is back in")
        elif k == "music":
            if "set" in op:
                d["music"] = op["set"]
            elif op.get("file"):
                d["music"] = {"file": op["file"]}
            elif op.get("generate"):
                d["music"] = {"generate": op["generate"] if op["generate"] != "_next" else "pop"}
            elif op.get("bpm_mul"):
                d["music"] = {**(d.get("music") if isinstance(d.get("music"), dict) else {}), "bpm": round(float(tpl.get("bpm") or 120) * op["bpm_mul"])}
            done.append(f"music: {op.get('generate') or op.get('file') or ('tempo x%.2f' % op['bpm_mul'] if op.get('bpm_mul') else 'as before')}")
        elif k == "canvas":
            d["canvas"] = op["value"]
            done.append(f"format {op['value']}")
        elif k == "tpl_speed" or k == "speed_reset" or (k == "shot" and op.get("field") == "speed" and op.get("value") in ("slow", "velocity")):
            # the slots keep their length; slow motion, ramps or normal speed change how much of each moment plays
            v = op["value"] if k == "tpl_speed" else "normal" if k == "speed_reset" else ("ramp" if op["value"] == "velocity" else 0.5)
            if d.get("speed") == v:
                failed.append(f"{describe({'op': 'tpl_speed', 'value': v})}: already so")
                continue
            d["speed"] = v
            done.append(describe({"op": "tpl_speed", "value": v}))
        elif k in ("shot_move", "more_of") and op.get("file") and slots:
            drop = tpl.get("drop")
            if k == "more_of":
                free = [s for s in sorted(slots, key=lambda s: -s["dur"]) if str(s["n"]) not in pins][:int(op.get("n") or 2)]
                for s in free:
                    pins[str(s["n"])] = op["file"]
                done.append(f"more of {op['file']} ({len(free)} slot(s))")
                continue
            to = op.get("to")
            n = slots[0]["n"] if to == "first" else slots[-1]["n"] if to == "last" else \
                next((s["n"] for s in slots if drop is not None and s["start"] - 0.05 <= drop < s["end"]), slots[len(slots) // 2]["n"])
            pins[str(n)] = op["file"]
            done.append(f"{op['file']} in slot {n} ({to})")
        else:
            failed.append(f"{describe(op)}: this edit follows the template's timing (its length and pacing come from the template)")
    d["pins"] = pins
    return d, done, failed


def refill(d, analyses, request="", log=print, chat=False, with_info=False):
    """The plan again for a template edit's design (after a follow-up)."""
    tpl = load(d["template"])
    if tpl is None:
        raise ValueError(f"the template '{d['template']}' is not in the library any more")
    plan, info = fill(tpl, analyses, request, music=d.get("music"), canvas=d.get("canvas"), pins=d.get("pins"),
                      avoid=d.get("avoid_files") or (), texts=d.get("texts"), log=log, speed=d.get("speed"), chat=chat)
    return (plan, info) if with_info else plan
