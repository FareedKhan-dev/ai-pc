"""Cut engine: shot wishes -> clips cut exactly on the beat, from the best moments of the footage.

The planner says WHAT each shot is (section, file, roughly where, how many beats, normal / slow / fast / velocity /
freeze); this module decides the exact source window and timeline length:
  - every shot lasts a whole number of beats, so cuts land on the music; the first DROP shot starts exactly on the drop;
  - without a hint, the window is the best-scoring stretch of the file (highlight score of the analysed moments, face
    size when the shot wants a person, motion when it wants action), never crossing a camera cut, never reused;
  - velocity = the classic speed ramp: fast (1.8x) -> slow (0.35x) on the key moment -> fast again.
Returns plan clips (schema v2) and the timeline (id, start, end, section).
"""

import bisect
import math
from collections import Counter

SPEEDS = {"normal": 1.0, "slow": 0.4, "fast": 1.8, "freeze": 0.0}
VEL = (1.8, 0.35, 1.8)  # velocity ramp speeds
VEL_SPLIT = (0.35, 0.40, 0.25)  # share of the shot's timeline length in each part
FACE_WORDS = ("face", "eye", "close", "person", "man", "woman", "him", "her", "boss", "look", "stare", "portrait", "smile")
ACTION_WORDS = ("walk", "run", "action", "move", "jump", "fast", "drive", "dance", "fight", "enter", "stride", "spin")


def _series(a):
    """Per analysed sample: (t, score parts) -> highlight, face size, motion (each 0-1)."""
    times = a.get("times") or []
    motion = a.get("motion") or [0.0] * len(times)
    faces = {round(x["t"], 2): x["faces"][0]["box"][2] * x["faces"][0]["box"][3] for x in a.get("faces", []) if x["faces"]}
    moments = sorted((m["t"], float(m.get("highlight") or 5)) for m in a.get("moments", []))
    mt = [m[0] for m in moments]
    mx = max(motion) or 1.0
    fx = max(faces.values(), default=0.0) or 1.0
    out = []
    for i, t in enumerate(times):
        hl = 0.5
        if moments:
            j = bisect.bisect_left(mt, t)
            near = min((moments[k] for k in (j - 1, j) if 0 <= k < len(moments)), key=lambda m: abs(m[0] - t))
            hl = near[1] / 10
        out.append((t, hl, faces.get(round(t, 2), 0.0) / fx, motion[i] / mx))
    return out


def _cuts(a):
    return [s["start"] for s in a.get("shots", [])[1:]]


def best_window(a, span, want="", used=(), around=None, key_at=0.4):
    """Start time in file `a` for a window of `span` source seconds."""
    length = float(a.get("seconds") or 0.0)
    if length <= span + 0.05:
        return 0.0
    if around is not None:
        return min(max(0.0, float(around) - key_at * span), length - span - 0.02)
    s = _series(a)
    if not s:
        return 0.0
    w = want.lower()
    wf = 1.0 if any(k in w for k in FACE_WORDS) else 0.3
    wm = 1.0 if any(k in w for k in ACTION_WORDS) else 0.4
    cuts = _cuts(a)
    best, best_score = 0.0, -1e9
    step = 0.25
    t0 = 0.0
    while t0 + span <= length - 0.02:
        inside = [x for x in s if t0 <= x[0] <= t0 + span]
        if inside:
            sc = sum(0.5 * x[1] + wf * x[2] + wm * x[3] for x in inside) / len(inside)
            if any(t0 + 0.1 < c < t0 + span - 0.1 for c in cuts):
                sc -= 1.0  # a camera cut inside one of our shots looks like a mistake
            over = sum(max(0.0, min(u1, t0 + span) - max(u0, t0)) for u0, u1 in used)
            if over > 0:
                sc -= 2.0 + 3.0 * over / span  # already shown: the less of it repeats, the better
            if sc > best_score:
                best, best_score = t0, sc
        t0 += step
    return round(best, 3)


def _beats(s, bps):
    n = s.get("beats") or bps.get(s.get("section") or "drop", 2)
    try:
        return max(1, int(round(float(n))))
    except (TypeError, ValueError):
        return 2


def shot_lengths(shots, beat, bps, drop_at=None):
    """Timeline seconds of every shot: whole beats. When the music fixes the drop, the shot before the first drop
    stretches to reach it; otherwise every new section starts on a bar (a multiple of 4 beats), like real music."""
    out = [_beats(s, bps) * beat for s in shots]
    first_drop = next((i for i, s in enumerate(shots) if s.get("section") == "drop"), None)
    if drop_at is not None and first_drop:
        gap = drop_at - sum(out[:first_drop])
        if abs(gap) > 1e-3:
            out[first_drop - 1] = max(beat, out[first_drop - 1] + round(gap / beat) * beat)
    else:
        acc = 0.0
        for i, s in enumerate(shots):
            if i and s.get("section") != shots[i - 1].get("section"):
                off = round(acc / beat) % 4
                if off:
                    out[i - 1] += (4 - off) * beat
                    acc += (4 - off) * beat
            acc += out[i]
    return out


def held(shots, i, keep=()):
    """Shots an editor would not shorten, drop or re-source: the opening, the climax (the first drop shot), the last
    shot, freezes, shots marked "hold" and shots that hand-placed extras point at."""
    s = shots[i]
    first_drop = next((j for j, x in enumerate(shots) if x.get("section") == "drop"), None)
    return i in (0, first_drop, len(shots) - 1) or bool(s.get("hold")) or str(s.get("speed")) == "freeze" or s.get("id") in keep


def fit(shots, beat, bps, target, drop_at=None, keep=(), drop_by=None):
    """The shot list adjusted to last `target` seconds (within 3%, at least a beat). Too long: ordinary shots longer
    than their section's norm lose beats, then ordinary shots are dropped (labelled story beats only when nothing
    else is left; never the opening, the climax or the ending). Too short: a longer ending, then extra shots at the
    end of sections (their files are chosen by spread_files). Each step takes the change that lands closest.
    drop_by: the share of the length by which the first drop should land (the build-up is never grown past it)."""
    if not target or not shots:
        return shots
    tol = max(beat * 1.01, 0.03 * target)
    cur = [dict(s) for s in shots]
    lo = 0
    if drop_at is not None:  # the music fixes everything up to the drop
        fd = next((i for i, s in enumerate(cur) if s.get("section") == "drop"), None)
        lo = fd + 1 if fd is not None else 0

    def total(ss):
        return sum(shot_lengths(ss, beat, bps, drop_at))

    def raw(ss):  # without the bar padding: a step that the padding hides still moves the edit the right way
        return sum(_beats(x, bps) for x in ss)

    added, best_seen, grown = 0, (abs(total(cur) - target), cur), Counter()
    if (
        total(cur) < 0.6 * target
        and sum(1 for i, x in enumerate(cur) if x.get("section") == "drop" and (i == 0 or cur[i - 1].get("section") != "drop")) < 2
    ):
        # far too short for one act: a second act like a real 1-minute edit (break -> build -> drop) before the ending
        at = next((i for i, x in enumerate(cur) if x.get("section") == "outro"), len(cur))
        act = (
            [{"section": "break", "beats": bps.get("break", 4), "speed": "slow"} for _ in range(2)]
            + [{"section": "build", "beats": bps.get("build", 2)} for _ in range(4)]
            + [{"section": "drop", "beats": bps.get("drop", 2)} for _ in range(8)]
        )
        cur = cur[:at] + [{**x, "id": f"act{k + 1}", "file": None, "cutaway": True} for k, x in enumerate(act)] + cur[at:]
    for _ in range(200):
        t = total(cur)
        if abs(t - target) <= tol:
            break
        ops, n = [], len(cur)
        fd0 = next((i for i, x in enumerate(cur) if x.get("section") == "drop"), None)
        for i in range(lo, n):
            s = cur[i]
            b, norm, h = _beats(s, bps), bps.get(s.get("section") or "drop", 2), held(cur, i, keep)
            if t > target:
                if b > (max(norm, math.ceil(1.6 / beat)) if s.get("label") else 1):  # a label must stay readable
                    ops.append((0 if not h and b > norm else 2 if not h else 4, cur[:i] + [{**s, "beats": b - 1}] + cur[i + 1 :]))
                if not h and n > 4:
                    ops.append((3 if s.get("label") else 1, cur[:i] + cur[i + 1 :]))
            else:
                if i == n - 1 and b < 8:
                    ops.append((0, cur[:i] + [{**s, "beats": b + 1}]))
                elif not h and b < 2 * norm:
                    ops.append((2, cur[:i] + [{**s, "beats": b + 1}] + cur[i + 1 :]))
                sec = s.get("section") or "drop"
                if i < n - 1 and cur[i + 1].get("section") != sec and sec not in ("intro", "outro"):
                    # spread over the sections (the drop and the build first), not all into the first one
                    # a whole bar at a time (2 shots of 2 beats...), so the bar padding never hides the step
                    # and after the first drop first: a long wait for the drop loses the viewer
                    pri = 1 + 0.15 * grown[sec] - {"drop": 0.1, "build": 0.05}.get(sec, 0) + (0.45 if fd0 is not None and i < fd0 else 0)
                    if drop_by and fd0 is not None and i < fd0 and sum(shot_lengths(cur, beat, bps, drop_at)[:fd0]) + 4 * beat > drop_by * target:
                        continue  # the build-up is long enough: the extra time goes after the drop
                    new = [
                        {
                            "id": f"x{added + 1}" if j == 0 else f"x{added + 1}_{j + 1}",
                            "section": sec,
                            "file": None,
                            "beats": norm,
                            "cutaway": True,
                            "want": s.get("want", ""),
                        }
                        for j in range(max(1, 4 // max(1, norm)))
                    ]
                    ops.append((pri, cur[: i + 1] + new + cur[i + 1 :]))
        best, r0 = None, raw(cur)
        for pri, cand in ops:
            t2 = total(cand)
            closer = abs(t2 - target) < abs(t - target) - 1e-6
            hidden = abs(t2 - t) < 1e-6 and (raw(cand) - r0) * (target - t) > 0
            if not (closer or hidden):
                continue
            key = (abs(t2 - target) > tol, not closer, pri, abs(t2 - target))
            if best is None or key < best[0]:
                best = (key, cand)
        if best is None:
            break
        if len(best[1]) > len(cur):
            added += 1
            new = next((x for x in best[1] if x.get("id") == f"x{added}"), None)
            if new:
                grown[new.get("section")] += 1
        cur = best[1]
        if abs(total(cur) - target) < best_seen[0]:
            best_seen = (abs(total(cur) - target), cur)
    return cur if abs(total(cur) - target) <= tol else best_seen[1]


def spread_files(shots, analyses, keep=(), avoid=(), less=()):
    """Footage spread the way an editor would: shots without a file (cutaways) get the least-used file that is not
    next to them, and ordinary shots (no label, not held) move to the least-used other file when their file carries
    more than ~1.8x its fair share of the edit. Only files the planner chose are used (it read every file's captions:
    one it left out is usually off-topic, like a kickboxer in a football reel). Shots of the same file in a row stay
    (the planner's sequence of one place; the cut engine never repeats a moment)."""
    vids = {
        a["file"].lower(): a for a in analyses.values() if a.get("kind") in ("video", "image") and a["file"] not in avoid
    }  # off-brief footage (a white car in an ad for the red one) is never used
    if not vids:
        return shots
    cur = [dict(s) for s in shots]
    stems = {f.rsplit(".", 1)[0]: f for f in vids}
    for s in cur:  # forgiving names: a missing extension or a path still means that file
        f = str(s.get("file") or "").lower().replace("\\", "/").split("/")[-1]
        if f and f not in vids and f.rsplit(".", 1)[0] in stems:
            s["file"] = vids[stems[f.rsplit(".", 1)[0]]]["file"]
    chosen = {str(s.get("file") or "").lower() for s in cur if not s.get("cutaway")} & set(vids)
    if len(chosen) >= 2:
        vids = {f: a for f, a in vids.items() if f in chosen}
    uses = Counter(str(s.get("file") or "").lower() for s in cur if str(s.get("file") or "").lower() in vids)
    cap = max(2, math.ceil(1.8 * len(cur) / len(vids)))
    quality = {f: sum(float(m.get("highlight") or 5) for m in a.get("moments", [])) / max(1, len(a.get("moments", []))) for f, a in vids.items()}

    planned = Counter(str(s.get("file") or "").lower() for s in cur if not s.get("cutaway"))

    def pick(exclude):  # in proportion to how much the planner used each file (one it used once stays minor)
        opts = [f for f in vids if f not in exclude and f not in less] or [f for f in vids if f not in exclude]
        return min(opts, key=lambda f: (uses[f] / (planned[f] + 0.5), -quality.get(f, 5))) if opts else None

    for i, s in enumerate(cur):
        f = str(s.get("file") or "").lower()
        prev = str(cur[i - 1].get("file") or "").lower() if i else ""
        nxt = str(cur[i + 1].get("file") or "").lower() if i + 1 < len(cur) else ""
        movable = not s.get("label") and not held(cur, i, keep)
        if f not in vids:
            why = "none"
        elif movable and f in less and s.get("cutaway") is not False and not s.get("hold"):
            why = "overuse"  # the client wants less of this file: ordinary shots of it go to other files
        elif movable and uses[f] > cap:
            why = "overuse"
        else:
            continue
        alt = pick({f, prev, nxt}) or (pick({prev}) if why == "none" else None)
        if alt is None or why == "overuse" and uses[alt] >= uses[f] - 1:
            continue
        if f in vids:
            uses[f] -= 1
        uses[alt] += 1
        s["file"], s["around"] = vids[alt]["file"], None
    return cur


# a re-used file looks like a new shot when it is framed differently (what editors do with limited footage):
# another part of a wide picture on a tall canvas, else a punch-in on another spot. (x, y, zoom) of the framing.
VARY_PAN = [(0.5, 0.5, 1.0), (0.3, 0.5, 1.0), (0.7, 0.5, 1.0), (0.4, 0.5, 1.12), (0.6, 0.5, 1.12)]
VARY_PUNCH = [(0.5, 0.5, 1.0), (0.42, 0.45, 1.18), (0.58, 0.5, 1.18), (0.5, 0.42, 1.28)]
VARY_CENTRED = [(0.5, 0.5, 1.0), (0.5, 0.45, 1.15), (0.5, 0.5, 1.25)]


def _faces_between(a, t0, t1):
    return any(x["faces"] and x["faces"][0]["box"][2] > 0.05 for x in a.get("faces", []) if t0 - 0.2 <= x["t"] <= t1 + 0.2)


PERSON_WORDS = (
    "man",
    "woman",
    "person",
    "people",
    "girl",
    "boy",
    "player",
    "athlete",
    "chef",
    "couple",
    "bride",
    "groom",
    "dancer",
    "crowd",
    "rider",
    "driver",
    "child",
    "he ",
    "she ",
    "his ",
    "her ",
    "someone",
    "hands",
)


def _has_person(a):
    """Whether the analysis captions describe a person (dark or small faces often escape the face detector)."""
    text = " ".join([str(a.get("summary") or "")] + [str(m.get("subject") or "") for m in a.get("moments", [])]).lower()
    return any(w in f" {text} " for w in PERSON_WORDS)


def _vary(a, k, canvas, t0, t1):
    """Framing for the k-th re-use of file `a` (k >= 1), or None (a face to keep framed, or nothing to vary).
    With a person in the footage only centred punch-ins are used: panning a tall crop sideways can lose them."""
    if k < 1 or _faces_between(a, t0, t1):
        return None
    if _has_person(a):
        x, y, z = VARY_CENTRED[k % len(VARY_CENTRED)]
        return None if z == 1.0 else {"x": x, "y": y, "zoom": z}
    try:
        cw, ch = (float(v) for v in str(canvas or "16:9").split(":"))
    except ValueError:
        cw, ch = 16.0, 9.0
    w, h = a.get("width") or 0, a.get("height") or 0
    table = VARY_PAN if w and h and w / h > cw / ch + 0.15 else VARY_PUNCH
    x, y, z = table[k % len(table)]
    return None if (x, y, z) == (0.5, 0.5, 1.0) else {"x": x, "y": y, "zoom": z}


def cut(shots, analyses, beat, style_cfg=None, drop_at=None, canvas=None):
    """(clips, timeline, drop time) from shot wishes. `beat` = seconds per beat (music or the style's tempo)."""
    style_cfg = style_cfg or {}
    bps = style_cfg.get("beats_per_shot") or {}
    by_name = {a["file"].lower(): a for a in analyses.values()}
    clips, timeline, used = [], [], {}
    t = 0.0
    shots = [s for s in shots if isinstance(s, dict)]
    lengths = shot_lengths(shots, beat, bps, drop_at)
    for i, s in enumerate(shots):
        a = by_name.get(str(s.get("file", "")).lower())
        if not a:
            continue
        dur = lengths[i]
        sid = str(s.get("id") or f"s{i + 1}")
        sec = s.get("section") or "drop"
        speed = str(s.get("speed") or (style_cfg.get("speed") or {}).get(sec, "normal")).lower()
        clip = {"id": sid, "file": a["file"], "duration": round(dur, 4)}
        for k in ("reframe", "chroma", "background", "volume", "mask", "blend", "crop", "flip", "stretch"):
            if s.get(k) is not None:
                clip[k] = s[k]
        if a.get("kind") == "image":
            pass
        elif speed == "freeze":
            span = 0.04
            st = best_window(a, 0.5, s.get("want", ""), used.get(a["file"], ()), s.get("around"), 0.5)
            clip["freeze"] = round(st + 0.25, 3)
        elif speed == "velocity":
            d1, d2, d3 = (dur * f for f in VEL_SPLIT)
            span = VEL[0] * d1 + VEL[1] * d2 + VEL[2] * d3
            key = (VEL[0] * d1 + VEL[1] * d2 * 0.5) / span  # the key moment sits in the middle of the slow part
            st = best_window(a, span, s.get("want", ""), used.get(a["file"], ()), s.get("around"), key)
            clip["from"] = st
            clip["ramp"] = [[0, VEL[0]], [round(VEL[0] * d1, 3), VEL[1]], [round(VEL[0] * d1 + VEL[1] * d2, 3), VEL[2]]]
            used.setdefault(a["file"], []).append((st, st + span))
        else:
            sp = SPEEDS.get(speed, 1.0) or 1.0
            span = dur * sp
            if span > (a.get("seconds") or 0) - 0.05:  # not enough footage at this speed: slow it down to fit
                sp = max(0.25, ((a.get("seconds") or 0) - 0.1) / dur)
                span = dur * sp
            st = best_window(a, span, s.get("want", ""), used.get(a["file"], ()), s.get("around"))
            clip["from"], clip["speed"] = st, round(sp, 3)
            used.setdefault(a["file"], []).append((st, st + span))
        if a.get("kind") == "video" and s.get("reframe") is None and "from" in clip:
            v = _vary(a, len(used.get(a["file"], [])) - 1, canvas, clip["from"], clip["from"] + span)
            if v:
                clip["reframe"] = v
        clips.append(clip)
        timeline.append(
            {
                "id": sid,
                "start": round(t, 4),
                "end": round(t + dur, 4),
                "section": sec,
                "speed": speed,
                "kind": a.get("kind"),
                "want": s.get("want", ""),
                "label": s.get("label"),
                "file": a["file"],
            }
        )
        t += dur
    drop = next((x["start"] for x in timeline if x["section"] == "drop"), None)
    return clips, timeline, drop
