"""Learn an editing style from sample videos ("make it like this one").

An editor studies a reference edit for its rhythm (how often it cuts, how long shots last, whether cuts sit on the
beat), its moves (punch zooms, shakes, speed), its light (flashes, light leaks), its transitions (hard cuts, dissolves,
whips), its look (brightness, contrast, colour temperature, saturation, letterbox bars, grain) and its typography.
fingerprint() measures all of that from the video itself (12 fps, small frames, ~2-4 s for a minute) plus its sound,
and, with a planner, one vision call reads the text style off a contact sheet. profile() turns the numbers into the
cut engine's settings (beats per shot by section, which recipes and how often, the grade, the music tempo), and
describe() writes the designer's sheet. Fingerprints are cached per file.

  fp = fingerprint(path, planner)   prof = profile(fp)   text = describe(fp, prof)
  merge([fp1, fp2]) for several samples of one style.
"""

import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np

from ai_pc.core.config import ROOT
from ai_pc.media import audio as AU
from ai_pc.media import frames as F

CACHE = ROOT / "state" / "media"
FPS = 12.0

TEXT_SYSTEM = """You study a short-form or YouTube edit for an editor who must copy its style. You get a contact sheet of
frames from it (in time order). Reply with ONE JSON object:
{"text": {"present": true|false, "case": "upper|title|lower|mixed", "weight": "bold|regular|thin", "font_style": "<e.g.
condensed sans, script, serif, rounded, distressed>", "position": "center|upper|lower|top|bottom|varies", "size":
"small|medium|large|huge", "colour": "<main text colour>", "extras": "<outline, box, glow, emoji, captions...>"},
 "effects": ["<visible effects: flash, glitch, rgb split, light leak, grain, vignette, letterbox, zoom blur, shake...>"],
 "look": "<the colour grade in a few words>", "content": "<what the video shows, a few words>",
 "summary": "<the style in one line, as an editor would say it>"}"""


def _key(path):
    p = Path(path)
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]


def _robust_threshold(x, k, floor):
    x = np.asarray(x, np.float32)
    if not len(x):
        return floor
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) or 1e-3
    return max(floor, med + k * mad)


def fingerprint(path, planner=None, log=print, use_cache=True):
    """The measured style of one edited video (dict). With a planner, the text/effect style is read from frames too."""
    path = Path(path)
    cp = CACHE / f"{path.stem}_{_key(path)}.ref.json"
    if use_cache and cp.exists():
        fp = json.loads(cp.read_text(encoding="utf-8"))
        if fp.get("vision") or planner is None:
            return fp
    t0 = time.perf_counter()
    info = F.probe(str(path))
    dur = float(info.get("seconds") or 0)
    fr = F.window(str(path), 0, dur, fps=FPS, width=160)
    n = len(fr)
    if n < 6:
        raise ValueError(f"{path.name}: too short to read a style from")
    hsv = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2HSV) for f in fr]).astype(np.float32) / 255.0
    gray = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in fr]).astype(np.float32)
    bright = hsv[..., 2].mean(axis=(1, 2))
    # letterbox: rows that stay near black in almost every frame, from the top and from the bottom
    rows = (hsv[..., 2].mean(axis=2) < 0.08).mean(axis=0)
    top = int(np.argmax(rows < 0.8)) if rows[0] >= 0.8 else 0
    bot = int(np.argmax(rows[::-1] < 0.8)) if rows[-1] >= 0.8 else 0
    bars = (top + bot) / rows.shape[0]
    y0, y1 = top, rows.shape[0] - bot  # the picture area, for everything below
    pic = gray[:, y0:y1] if y1 - y0 > 8 else gray
    # cuts, flashes, dissolves from frame-to-frame change
    d1 = np.array([0.0] + [float(np.mean(np.abs(pic[i] - pic[i - 1]))) / 255 for i in range(1, n)])
    hist = [cv2.calcHist([p.astype(np.uint8)], [0], None, [32], [0, 256]) for p in pic]
    for h in hist:
        cv2.normalize(h, h)
    hd = np.array([0.0] + [float(cv2.compareHist(hist[i - 1], hist[i], cv2.HISTCMP_BHATTACHARYYA)) for i in range(1, n)])
    td = _robust_threshold(d1[1:], 6, 0.07)
    flashes = []
    for i in range(1, n):
        prev = float(np.median(bright[max(0, i - 4) : i]))
        if bright[i] - prev > 0.22 and any(bright[j] - prev < 0.12 for j in range(i + 1, min(n, i + 5))):
            flashes.append(i)  # a short brightness spike that comes back down
    # shot changes: the content half a second apart differs (whatever hides the cut: a flash, a glitch, a dissolve).
    # Colour distribution (robust to camera moves) is the main signal, a tiny thumbnail the second one.
    hsvs = [cv2.cvtColor(f[y0:y1] if y1 - y0 > 8 else f, cv2.COLOR_BGR2HSV) for f in fr]
    hh = []
    for x in hsvs:
        h = cv2.calcHist([x], [0, 1], None, [16, 4], [0, 180, 0, 256])
        cv2.normalize(h, h)
        hh.append(h)
    thumbs = [cv2.resize(p, (32, 18), interpolation=cv2.INTER_AREA) for p in pic]
    w = 3
    D = np.zeros(n)
    for i in range(w, n - w):
        a, b = i - w, i + w
        D[i] = 0.65 * float(cv2.compareHist(hh[a], hh[b], cv2.HISTCMP_BHATTACHARYYA)) + 0.35 * float(np.mean(np.abs(thumbs[a] - thumbs[b]))) / 255 * 3
    base = np.array([np.percentile(D[max(0, i - 18) : i + 18], 30) for i in range(n)])
    hd = np.array([0.0] + [float(cv2.compareHist(hh[i - 1], hh[i], cv2.HISTCMP_BHATTACHARYYA)) for i in range(1, n)])
    th = _robust_threshold(hd[1:], 6, 0.12)
    near_flash = {f + o for f in flashes for o in (-1, 0, 1)}
    hard = []  # 1. hard cuts: one frame carries the change (not a flash frame)
    for i in range(1, n):
        if d1[i] > td and hd[i] > th and i not in near_flash and (not hard or i - hard[-1] >= 2):
            hard.append(i)
    soft = []  # 2. changes hidden by a transition: content differs half a second apart, no hard cut nearby
    for i in range(w, n - w):
        if D[i] < max(0.28, 2.0 * base[i]) or D[i] < D[max(0, i - 2) : i + 3].max():
            continue
        around = [D[j] for j in (i - 7, i + 7) if 0 <= j < n]
        if around and D[i] < 1.6 * max(around):  # a transition comes and goes within ~0.5 s; a slow pan or glide does not
            continue
        if any(abs(i - h) <= 0.3 * FPS for h in hard) or (soft and i - soft[-1] < 0.25 * FPS):
            continue
        soft.append(i)
    cuts = sorted(hard + soft)
    kinds = []
    for i in cuts:
        if any(abs(f - i) <= w for f in flashes):
            kinds.append("flash")
        elif i in hard:
            kinds.append("cut")
        else:
            kinds.append("dissolve")
    dissolves = kinds.count("dissolve")
    flash_cuts = kinds.count("flash")
    bounds = [0] + cuts + [n]
    shots = [(bounds[k + 1] - bounds[k]) / FPS for k in range(len(bounds) - 1) if bounds[k + 1] > bounds[k]]
    # moves inside shots: zoom (flow divergence) and shake (jitter of the global shift)
    small = [cv2.resize(p, (96, max(8, round(p.shape[0] * 96 / p.shape[1]))), interpolation=cv2.INTER_AREA) for p in pic]
    cutset = {c + o for c in cuts for o in range(-w, w + 1)} | set(flashes)
    div, jit = [], []
    shifts = []
    for k in range(1, n):
        if k in cutset:
            div.append(0.0)
            shifts.append((0.0, 0.0))
            continue
        flow = cv2.calcOpticalFlowFarneback(small[k - 1].astype(np.uint8), small[k].astype(np.uint8), None, 0.5, 2, 9, 2, 5, 1.1, 0)
        du = np.gradient(flow[..., 0], axis=1)
        dv = np.gradient(flow[..., 1], axis=0)
        div.append(float(np.mean(du + dv)))
        sx, sy, _ = F.shift(F.gray_small(pic[k - 1], 96), F.gray_small(pic[k], 96))
        shifts.append((sx, sy))
    div = np.array(div)
    sx = np.array([s[0] for s in shifts])
    sy = np.array([s[1] for s in shifts])
    jit = np.abs(np.diff(sx, 2, prepend=0, append=0))[: len(sx)] + np.abs(np.diff(sy, 2, prepend=0, append=0))[: len(sy)]
    zt = _robust_threshold(np.abs(div), 8, 0.035)
    punches, k = 0, 0
    while k < len(div):  # a burst of strong expansion or contraction lasting under half a second
        if abs(div[k]) > zt:
            j = k
            while j < len(div) and abs(div[j]) > zt * 0.5:
                j += 1
            if j - k <= 0.5 * FPS:
                punches += 1
            k = j + 1
        else:
            k += 1
    jt = _robust_threshold(jit, 10, 0.045)  # handheld footage jitters all the time: a shake is a burst well above it
    shakes, k = 0, 0
    while k < len(jit):
        if jit[k] > jt:
            j = k
            while j < len(jit) and jit[j] > jt * 0.5:
                j += 1
            if j - k >= 3:
                shakes += 1
            k = j + 1
        else:
            k += 1
    slow_push = float(np.mean((np.abs(div) > 0.004) & (np.abs(div) < zt)))
    # look of the picture area
    lab = [cv2.cvtColor(f[y0:y1] if y1 - y0 > 8 else f, cv2.COLOR_BGR2LAB).astype(np.float32) for f in fr[::3]]
    warmth = float(np.mean([(x[..., 2].mean() - 128) / 64 for x in lab]))
    contrast = float(np.mean([x[..., 0].std() / 128 for x in lab]))
    sat = float(hsv[:, y0:y1, :, 1].mean())
    blacks = float(np.mean([np.percentile(x[..., 0], 5) / 255 for x in lab]))
    h_, w_ = pic.shape[1:]
    centre = pic[:, h_ // 4 : 3 * h_ // 4, w_ // 4 : 3 * w_ // 4].mean()
    corners = np.mean(
        [
            pic[:, : h_ // 6, : w_ // 6].mean(),
            pic[:, : h_ // 6, -w_ // 6 :].mean(),
            pic[:, -h_ // 6 :, : w_ // 6].mean(),
            pic[:, -h_ // 6 :, -w_ // 6 :].mean(),
        ]
    )
    vignette = float(corners / max(1e-3, centre))
    noise = float(np.mean([np.std(p.astype(np.float32) - cv2.GaussianBlur(p, (3, 3), 0)) for p in pic[::6]]))
    # sound: music or speech, tempo, and whether the cuts land on its beats
    snd = AU.analyze(str(path)) if info.get("has_audio") else None
    beats = (snd or {}).get("beats") or []
    on_beat = None
    if beats and cuts:
        bt = np.array(beats)
        on_beat = float(np.mean([np.min(np.abs(bt - c / FPS)) <= 0.08 for c in cuts]))
    mins = max(dur / 60.0, 1e-3)
    bpm = (snd or {}).get("bpm")
    if bpm and bpm < 95 and len(cuts) / mins > 0.45 * bpm:  # cutting that fast means the beat was heard at half tempo
        bpm = round(bpm * 2, 1)
    fp = {
        "file": path.name,
        "seconds": round(dur, 2),
        "aspect": f"{info.get('width')}x{info.get('height')}",
        "portrait": (info.get("height") or 0) > (info.get("width") or 0),
        "cuts": len(cuts),
        "cuts_per_min": round(len(cuts) / mins, 1),
        "shot_median": round(float(np.median(shots)), 2) if shots else dur,
        "shot_p25": round(float(np.percentile(shots, 25)), 2) if shots else dur,
        "shot_p75": round(float(np.percentile(shots, 75)), 2) if shots else dur,
        "flashes_per_min": round(len(flashes) / mins, 1),
        "dissolves_per_min": round(dissolves / mins, 1),
        "punches_per_min": round(punches / mins, 1),
        "shakes_per_min": round(shakes / mins, 1),
        "slow_push_share": round(slow_push, 2),
        "brightness": round(float(bright.mean()), 3),
        "contrast": round(contrast, 3),
        "saturation": round(sat, 3),
        "warmth": round(warmth, 3),
        "blacks": round(blacks, 3),
        "letterbox": round(bars, 3) if bars > 0.04 else 0.0,
        "vignette": round(vignette, 2),
        "grain": round(noise, 2),
        "sound": (snd or {}).get("kind"),
        "speech": (snd or {}).get("kind") == "speech",
        "bpm": bpm,
        "flash_cuts": flash_cuts,
        "cuts_on_beat": round(on_beat, 2) if on_beat is not None else None,
        "measured_s": round(time.perf_counter() - t0, 1),
    }
    if planner is not None:  # one look at the frames for what numbers cannot say: the typography and the effects
        try:
            from ai_pc.llm.vlm import ask

            idx = np.linspace(0, n - 1, 12).astype(int)
            full = F.frames_at(str(path), [i / FPS for i in idx], width=360)
            sheet = F.sheet([f for f in full if f is not None], [f"{i / FPS:.1f}s" for i, f in zip(idx, full) if f is not None], cols=4, cell_w=240)
            d, s = ask(
                planner, TEXT_SYSTEM, f"A {fp['seconds']} s edit, {fp['aspect']}, {fp['cuts_per_min']} cuts per minute.", [sheet], tier="caption"
            )
            fp["vision"] = d if isinstance(d, dict) else None
        except Exception as e:  # noqa: BLE001  (the measured numbers already describe most of the style)
            log(f"  reference vision read failed: {type(e).__name__}: {e}")
    CACHE.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(fp, ensure_ascii=False, indent=1), encoding="utf-8")
    log(
        f"  reference {path.name}: {fp['cuts_per_min']} cuts/min, median shot {fp['shot_median']} s, "
        f"{fp['punches_per_min']} zooms/min, {fp['flashes_per_min']} flashes/min ({fp['measured_s']} s)"
    )
    return fp


def merge(fps):
    """One fingerprint from several samples of the same style (numbers averaged, vision readings kept)."""
    fps = [f for f in fps if f]
    if len(fps) <= 1:
        return fps[0] if fps else None
    out = dict(fps[0])
    for k, v in fps[0].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals = [f.get(k) for f in fps if isinstance(f.get(k), (int, float))]
            out[k] = round(float(np.mean(vals)), 3) if vals else v
    out["file"] = " + ".join(f["file"] for f in fps)
    out["speech"] = sum(bool(f.get("speech")) for f in fps) > len(fps) / 2
    out["portrait"] = sum(bool(f.get("portrait")) for f in fps) > len(fps) / 2
    return out


def look_words(fp):
    """The grade in words the catalogue search understands."""
    w = []
    w.append("dark moody" if fp["brightness"] < 0.3 else "bright airy" if fp["brightness"] > 0.55 else "")
    w.append("high contrast" if fp["contrast"] > 0.42 else "soft contrast" if fp["contrast"] < 0.25 else "")
    w.append("warm golden" if fp["warmth"] > 0.06 else "cool teal blue" if fp["warmth"] < -0.03 else "")
    w.append("vivid saturated" if fp["saturation"] > 0.5 else "muted desaturated" if fp["saturation"] < 0.22 else "")
    w.append("cinematic film" if fp["letterbox"] else "")
    return " ".join(x for x in w if x) or "natural"


def profile(fp):
    """The cut engine's settings that reproduce the measured style."""
    bpm = fp.get("bpm") or (140 if fp["cuts_per_min"] >= 35 else 118 if fp["cuts_per_min"] >= 18 else 84)
    beat = 60.0 / bpm

    def beats(sec):
        return int(max(1, min(8, round(sec / beat))))

    if fp.get("speech"):
        style = "talking"
    elif fp["cuts_per_min"] >= 42 or (
        fp["cuts_per_min"] >= 25 and (fp["flashes_per_min"] >= 3 or fp["punches_per_min"] >= 6 or fp["brightness"] < 0.32)
    ):
        style = "hype"
    elif fp["cuts_per_min"] >= 16:
        style = "montage"
    elif fp["brightness"] > 0.5 and not fp["letterbox"] and fp["grain"] < 2.0:
        style = "tour"
    else:
        style = "cinematic"
    recipes = []
    if fp["punches_per_min"] >= 3:
        recipes.append(
            {
                "use": "zoom_punch",
                "on": "beats",
                "every": max(1, round(60.0 / max(fp["punches_per_min"], 1) / beat)),
                "sections": ["build", "drop"],
                "strength": 1.15,
                "blur": fp["punches_per_min"] >= 8,
            }
        )
    else:
        recipes.append({"use": "zoom_punch", "off": True})
    if fp["shakes_per_min"] >= 2:
        recipes.append({"use": "shake", "on": "downbeats", "sections": ["drop"], "strength": 0.5})
    else:
        recipes.append({"use": "shake", "off": True})
    if fp["flashes_per_min"] >= 1:
        recipes.append({"use": "flash", "on": "downbeats", "every": max(1, round(4 / max(1.0, fp["flashes_per_min"] / 2))), "sections": ["drop"]})
    else:
        recipes.append({"use": "flash", "off": True})
    if fp["slow_push_share"] >= 0.25:
        recipes.append({"use": "ken_burns", "amount": 1.06})
    trans = {"use": "transitions", "off": True}
    if fp["dissolves_per_min"] >= 2:
        trans = {"use": "transitions", "family": "dissolve", "at": "every", "every": 2}
    elif fp["flashes_per_min"] >= 3:
        trans = {"use": "transitions", "family": "flash", "at": "sections"}
    recipes.append(trans)
    recipes.append(
        {"use": "grade", "look": look_words(fp), "grain": fp["grain"] >= 2.5, "vignette": fp["vignette"] < 0.8, "letterbox": bool(fp["letterbox"])}
    )
    # the sample's AVERAGE shot length sets the pace (percentiles over-react to a few flash-cut frames); sections
    # breathe around it the way a real edit does: tighter in the build and drop, longer in the intro, break and outro
    avg = 60.0 / max(1.0, fp["cuts_per_min"]) if fp["cuts_per_min"] else fp["shot_median"]
    bps = {
        "intro": beats(avg * 1.5),
        "verse": beats(avg),
        "build": beats(avg * 0.85),
        "drop": beats(avg * 0.8),
        "break": beats(avg * 1.6),
        "outro": beats(avg * 1.6),
    }
    vis = fp.get("vision") or {}
    music = (
        None
        if fp.get("speech")
        else {"generate": {"hype": "hype", "montage": "pop", "cinematic": "cinematic", "tour": "cinematic"}.get(style, "pop"), "bpm": int(round(bpm))}
    )
    return {
        "style": style,
        "beats_per_shot": bps,
        "recipes": recipes,
        "music": music,
        "canvas": "9:16" if fp.get("portrait") else "16:9",
        "text": vis.get("text"),
        "effects": vis.get("effects"),
        "summary": vis.get("summary"),
        "look": look_words(fp),
        "target_look": {"brightness": fp["brightness"], "contrast": fp["contrast"], "saturation": fp["saturation"]},
    }


def describe(fp, prof):
    """The designer's sheet: match this style."""
    t = prof.get("text") or {}
    lines = [
        f"REFERENCE STYLE (the client's sample {fp['file']}, {fp['seconds']} s; MATCH ITS RHYTHM AND LOOK):",
        f"  rhythm: {fp['cuts_per_min']} cuts/min (shots: median {fp['shot_median']} s, short {fp['shot_p25']} s, long {fp['shot_p75']} s)"
        + (f", {fp['cuts_on_beat'] * 100:.0f}% of cuts on the beat" if fp.get("cuts_on_beat") is not None else "")
        + (f", music at {fp['bpm']} BPM" if fp.get("bpm") else ""),
        f"  moves: {fp['punches_per_min']} zoom punches/min, {fp['shakes_per_min']} shakes/min, slow push on "
        f"{fp['slow_push_share'] * 100:.0f}% of frames",
        f"  light and transitions: {fp['flashes_per_min']} flashes/min, {fp['dissolves_per_min']} dissolves/min"
        + ("; otherwise hard cuts" if fp["dissolves_per_min"] < 2 else ""),
        f"  look: {prof['look']}"
        + (", letterbox bars" if fp["letterbox"] else "")
        + (", grain" if fp["grain"] >= 2.5 else "")
        + (", vignette" if fp["vignette"] < 0.8 else ""),
    ]
    if t:
        lines.append(
            f"  text: {t.get('case', '')} {t.get('weight', '')} {t.get('font_style', '')}, {t.get('size', '')}, "
            f"{t.get('position', '')}" + (f", {t.get('extras')}" if t.get("extras") else "")
        )
    if prof.get("effects"):
        lines.append(f"  visible effects: {', '.join(map(str, prof['effects'][:8]))}")
    if prof.get("summary"):
        lines.append(f"  in one line: {prof['summary']}")
    lines.append(f"  -> style {prof['style']}, beats per shot {prof['beats_per_shot']}, music {prof['music']}")
    return "\n".join(lines)
