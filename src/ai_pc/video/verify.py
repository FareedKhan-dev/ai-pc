"""Verifier: checks an exported edit AT THE EDIT POINTS. Every edit in the edit map (jybuild.py) has a time window and
an "expect"; the verifier looks at exactly those moments of the export and decides pass / warn / fail with evidence.

  effect         frames inside the window vs the same shot without it (rendered just outside the window, or the source
                 frame framed the same way); character effects are judged on a crop of the eyes / face / person;
                 the vision model answers whether the expected effect is visible, plus a pixel-change measure
  shake / zoom / moving effects   camera motion measured over the window (phase correlation, ORB scale), vs the source
  filter         colour statistics vs the source at the same moments (vision model only when the change is small)
  transition     the frame at the cut must differ from both sides (a hard cut means the transition is missing)
  text           read back by the vision model (and where it is), checked against the platform's safe zone
  captions       a few lines read back
  animation      frames across the animation window: something must move / appear
  audio          loudness in the window, fades
  clips          the subject (face) is in the picture; a removed green screen is really gone
  global         duration, picture size, sound present, unexpected black frames

Checks run in parallel; frames for every check are saved as contact sheets in out/video/checks/<draft>/.
"""

import difflib
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from ai_pc.core.config import ROOT
from ai_pc.llm.vlm import ask
from ai_pc.media import audio as A
from ai_pc.media import frames as F

NO_WINDOW = 0x08000000
CHECKS = ROOT / "out" / "video" / "checks"
KB_SAMPLE = 5  # ken-burns push-ins checked per edit (spread over the timeline); the rest are the same recipe


def _interp(pts, t):
    """Value of keyframes [[t, v], ...] at t (linear, held at the ends)."""
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / max(1e-9, t1 - t0)
    return pts[-1][1]


EFFECT_SYSTEM = """You check one edit in an exported video. You get a contact sheet: A = the same shot WITHOUT the edit,
B1..Bn = moments where the edit should be visible. Judge only what you see. Reply with ONE JSON object:
{"visible": true|false, "best": "B1|B2|...|none", "strength": "none|weak|clear|strong",
 "seen": "<what differs from A, <=15 words>", "matches": true|false, "problem": "<if not visible or not matching: why, <=15 words>"}"""

TEXT_SYSTEM = """You read on-screen text in frames from a vertical or horizontal video. Reply with ONE JSON object:
{"frames": [{"label": "<the yellow label>", "text": "<all text you can read, exactly>", "box": [x0, y0, x1, y1] (where the
expected text is, as fractions 0-1 of the frame width/height; [] if absent), "readable": true|false,
"problem": "<cut off, covered, too small, low contrast... or empty>"}]}"""

MOTION_SYSTEM = """You check an animation in an exported video. The frames (yellow labels, in time order) span the moment
the animation should happen. Judge the MOVEMENT (appearing, sliding, popping, fading, typing, blurring...), not where on
the screen the item sits: direction words in an animation's name describe its motion. Reply with ONE JSON object:
{"animates": true|false, "seen": "<what changes across the frames, <=15 words>", "matches": true|false,
 "problem": "<if not: why, <=12 words>"}"""


def _norm(s):
    return re.sub(r"[^a-z0-9一-鿿]+", " ", str(s).lower()).strip()


def _similar(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class Verifier:
    def __init__(self, video, emap, planner=None, log=print, vlm=True):
        self.video, self.m, self.planner, self.log = str(video), emap, planner, log
        self.vlm = vlm and planner is not None
        self.info = F.probe(video)
        self.W, self.H = emap["canvas"]
        self.dir = CHECKS / emap["draft"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clips = {c["id"]: c for c in emap["clips"]}
        self._fcache = {}

    # ------------------------------------------------------------------ frames
    def out(self, t, width=540):
        t = round(min(max(0.0, t), max(0.0, self.info["seconds"] - 0.04)), 3)
        k = (t, width)
        if k not in self._fcache:
            self._fcache[k] = F.frame_at(self.video, t, width)
        return self._fcache[k]

    def outs(self, times, width=540):
        with ThreadPoolExecutor(6) as ex:
            return list(ex.map(lambda t: self.out(t, width), times))

    def clip_at(self, t, main=True):
        for c in self.m["clips"]:
            if c["start"] - 1e-6 <= t < c["end"] and (not main or not c.get("overlay")):
                return c
        return None

    @staticmethod
    def piece_at(clip, t):
        for pc in clip["pieces"]:
            if pc["start"] - 1e-6 <= t <= pc["start"] + pc["dur"] + 1e-6:
                return pc
        return clip["pieces"][-1]

    def base(self, clip, t, width=540):
        """The source picture at timeline time t, framed like the clip on the canvas (no effects, filters or text)."""
        pc = self.piece_at(clip, t)
        if pc["kind"] == "image":
            img = F.image(pc["path"], width=1280)
        else:
            img = F.frame_at(pc["path"], pc["src_from"] + (t - pc["start"]) * pc["speed"], 1280)
        return self._frame_like(clip, img, width)

    def _frame_like(self, clip, img, width=540):
        """A source picture cropped and scaled the way the clip shows it on the canvas."""
        if img is None:
            return None
        h, w = img.shape[:2]
        vx, vy, vw, vh = clip["visible"]
        x0, y0, x1, y1 = int(round(vx * w)), int(round(vy * h)), int(round((vx + vw) * w)), int(round((vy + vh) * h))
        pad = [max(0, -y0), max(0, y1 - h), max(0, -x0), max(0, x1 - w)]
        if any(pad):
            img = cv2.copyMakeBorder(img, *pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            x0, x1, y0, y1 = x0 + pad[2], x1 + pad[2], y0 + pad[0], y1 + pad[0]
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        return cv2.resize(crop, (width, round(width * self.H / self.W)), interpolation=cv2.INTER_AREA)

    def reference(self, e, width=540):
        """The same shot without edit e: rendered just outside the window when the clip continues there, else the
        framed source frame. Returns (frame, how)."""
        t0, t1 = e["window"]
        c = self.clip_at((t0 + t1) / 2)
        if c is None:
            return None, None
        busy = [x["window"] for x in self.m["edits"] if x["type"] in ("transition", "effect", "zoom", "shake") and x["id"] != e["id"]]
        for t in (t0 - 0.18, t1 + 0.18, t0 - 0.4, t1 + 0.4):
            if c["start"] + 0.05 <= t <= c["end"] - 0.05 and not any(a - 0.05 <= t <= b + 0.05 for a, b in busy):
                f = self.out(t, width)
                if f is not None:
                    return f, f"render at {t:.2f}s"
        f = self.base(c, (t0 + t1) / 2, width)
        return f, "source frame"

    def save(self, name, jpeg):
        p = self.dir / f"{name}.jpg"
        p.write_bytes(jpeg)
        return str(p.relative_to(ROOT))

    # ------------------------------------------------------------------ checks
    def check_global(self):
        ev, probs = {}, []
        want = self.m["seconds"]
        got = self.info["seconds"]
        ev["duration"] = [round(got, 2), round(want, 2)]
        if abs(got - want) > 0.3:
            probs.append(f"duration {got:.2f} s, planned {want:.2f} s")
        ev["size"] = [self.info.get("width"), self.info.get("height")]
        if [self.info.get("width"), self.info.get("height")] != list(self.m["canvas"]):
            probs.append(f"picture {self.info.get('width')}x{self.info.get('height')}, canvas {self.m['canvas'][0]}x{self.m['canvas'][1]}")
        wants_sound = any(e["type"] == "audio" for e in self.m["edits"])
        if wants_sound and not self.info.get("has_audio"):
            probs.append("no sound in the export")
        r = subprocess.run(
            ["ffmpeg", "-v", "info", "-nostats", "-i", self.video, "-an", "-vf", "scale=270:-2,blackdetect=d=0.25:pix_th=0.08", "-f", "null", "-"],
            capture_output=True,
            creationflags=NO_WINDOW,
        )
        blacks = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr.decode("utf-8", "ignore"))]
        ev["black"] = blacks
        for a, b in blacks:
            if not (a < 0.3 or b > got - 0.3):  # fades at the very start/end are normal
                probs.append(f"black picture {a:.1f}-{b:.1f} s")
        return {
            "id": "global",
            "type": "global",
            "status": "fail" if any("duration" in p or "no sound" in p for p in probs) else ("warn" if probs else "pass"),
            "why": "; ".join(probs) or "duration, size and picture as planned",
            "evidence": ev,
        }

    def check_clip(self, c):
        busy = [x["window"] for x in self.m["edits"] if x.get("on") == c["id"] and x["type"] in ("zoom", "shake", "keyframes")]
        span = c["end"] - c["start"]
        mid = next(
            (t for t in (c["start"] + span * k for k in (0.5, 0.3, 0.75, 0.15, 0.9)) if not any(a - 0.1 <= t <= b + 0.1 for a, b in busy)),
            c["start"] + span / 2,
        )
        f = self.out(mid, 540)
        if f is None:
            return {"id": c["id"], "type": "clip", "status": "fail", "why": "no frame at this time"}
        ev, probs = {}, []
        if c.get("focus"):
            fc = F.faces(f, 0.75)
            ev["face"] = fc[0]["box"] if fc else None
            if not fc:
                probs.append("the subject's face is not found in the frame")
            else:
                x, y, w, h = fc[0]["box"]
                safe = self.m.get("safe") or {}
                if y < safe.get("top", 0) * 0.5 or y + h > 1 - safe.get("bottom", 0) * 0.5 or x < 0.01 or x + w > 0.99:
                    probs.append("the face is at the edge of the picture")
        if c.get("chroma"):
            hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
            green = ((hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] > 110) & (hsv[..., 2] > 70)).mean()
            ev["screen_left"] = round(float(green), 3)
            if green > 0.04:
                probs.append(f"{green * 100:.0f}% of the picture is still screen colour")
        sheet = F.sheet([f], [f"{c['id']} {mid:.1f}s"], cols=1, cell_w=360)
        return {
            "id": c["id"],
            "type": "clip",
            "status": "warn" if probs else "pass",
            "why": "; ".join(probs) or "framing ok",
            "evidence": ev,
            "sheet": self.save(c["id"], sheet),
        }

    def check_speed(self, c):
        """Slow motion, fast motion and speed ramps really play: inside the clip the render shows the take's moment at
        the planned speed, not the moment at normal speed (2 s into a 0.45x slot is 0.9 s into the take, not 2 s)."""
        vids = [pc for pc in c["pieces"] if pc["kind"] == "video"]
        sp = sorted({round(pc["speed"], 2) for pc in vids})
        rid = f"{c['id']}:speed"
        what = "slow motion" if max(sp) < 1 else "fast motion" if min(sp) > 1 else "a speed ramp"
        busy = [x["window"] for x in self.m["edits"] if x["type"] in ("transition", "zoom", "shake", "effect") and x.get("on") in (None, c["id"])]
        span = c["end"] - c["start"]
        times = [t for t in (c["start"] + span * k for k in (0.3, 0.5, 0.7, 0.85)) if not any(a - 0.1 <= t <= b + 0.1 for a, b in busy)][:3]
        p0 = vids[0]

        def grey(im):
            g = cv2.cvtColor(cv2.resize(im, (96, max(8, round(96 * im.shape[0] / im.shape[1]))), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            g = cv2.GaussianBlur(g.astype(np.float32), (5, 5), 0)
            return (g - g.mean()) / (g.std() + 1e-6)

        votes, ev = [], []
        for t in times:
            out, right = self.out(t, 270), self.base(c, t, 270)
            wrong = self._frame_like(c, F.frame_at(p0["path"], p0["src_from"] + (t - c["start"]), 1280), 270)  # the take at 1x
            if out is None or right is None or wrong is None:
                continue
            o, r, w = grey(out), grey(right), grey(wrong)
            sr, sw, rw = float((o * r).mean()), float((o * w).mean()), float((r * w).mean())
            ev.append([round(t, 2), round(sr, 3), round(sw, 3), round(rw, 3)])
            if rw > 0.985:
                continue  # the take hardly changes between the two moments: the speed cannot be seen here
            votes.append(sr > sw + 0.01)
        sps = "/".join(f"{x:g}x" for x in sp)
        if not votes:
            return {
                "id": rid,
                "type": "speed",
                "status": "skip",
                "why": f"{what} ({sps}): the shot barely moves, so the speed cannot be measured",
                "evidence": {"samples [t, match planned, match 1x, planned~1x]": ev},
            }
        ok = sum(votes) * 2 > len(votes)
        return {
            "id": rid,
            "type": "speed",
            "status": "pass" if ok else "fail",
            "why": (
                f"{what} plays: the picture follows the take at {sps}"
                if ok
                else f"{what} ({sps}) planned, but the picture follows the take at normal speed"
            ),
            "evidence": {"samples [t, match planned, match 1x, planned~1x]": ev},
        }

    def _region(self, e, frames, ref):
        """Crop box (0-1) to judge a person-tracking effect on: eyes, face or upper body of the main face."""
        tgt = (e.get("target") or "").lower()
        if e.get("category") != "character_effect" or tgt in ("", "around person", "body", "outline", "hands"):
            if e.get("category") == "character_effect":
                for f in list(frames) + [ref]:
                    fc = F.faces(f, 0.5) if f is not None else []
                    if fc:
                        x, y, w, h = fc[0]["box"]
                        return [max(0, x - 1.6 * w), max(0, y - 0.8 * h), min(1, 4.2 * w), min(1, 5 * h)]
            return None
        for f in list(frames) + [ref]:
            fc = F.faces(f, 0.5) if f is not None else []
            if fc:
                if tgt == "eyes":
                    x, y, w, h = F.eye_region(fc[0], pad=1.0)
                    return [max(0, x - 0.3 * w), max(0, y - 0.6 * h), min(1, 1.6 * w), min(1, 2.2 * h)]
                x, y, w, h = fc[0]["box"]
                return [max(0, x - 0.45 * w), max(0, y - 0.45 * h), min(1, 1.9 * w), min(1, 1.9 * h)]
        return None

    def check_effect(self, e):
        if e.get("layer") == "texture":  # grain, vignette, bars over everything: subtle on purpose, judged by pixels only
            t = sum(e["window"]) / 2
            c = self.clip_at(t)
            o, b = self.out(t, 360), (self.base(c, t, 360) if c else None)
            ch = F.diff(F.gray_small(o, 160), F.gray_small(cv2.resize(b, (o.shape[1], o.shape[0])), 160)) if o is not None and b is not None else 0
            return {
                "id": e["id"],
                "type": "effect",
                "name": e.get("name"),
                "window": e["window"],
                "status": "pass",
                "why": f"texture layer (subtle by design); picture change {ch:.3f}",
                "evidence": {"pixel_change": round(ch, 3)},
            }
        t0, t1 = e["window"]
        if e.get("moves_image"):
            return self.check_motion(e, kind="shake")
        ref, how = self.reference(e, 720)
        # many effects flicker (bolts, flashes, sparks): scan the window and keep the frames that differ most
        n = min(14, max(6, int((t1 - t0) * 6)))
        scan_t = [t0 + (t1 - t0) * (i + 0.5) / n for i in range(n)]
        scan = self.outs(scan_t, 360)
        box = self._region(
            e, [f for f in scan[:3] if f is not None], cv2.resize(ref, (360, round(360 * ref.shape[0] / ref.shape[1]))) if ref is not None else None
        )
        if ref is not None:
            rs = F.gray_small(cv2.resize(F.crop(ref, box) if box else ref, (160, 160)), 160)
            score = [F.diff(rs, F.gray_small(cv2.resize(F.crop(f, box) if box else f, (160, 160)), 160)) if f is not None else -1 for f in scan]
            top = sorted(sorted(range(n), key=lambda i: -score[i])[:3] + [n // 2])
        else:
            top = [int(n * k) for k in (0.2, 0.45, 0.7, 0.92)]
        times = [scan_t[i] for i in dict.fromkeys(top)]
        frames = self.outs(times, 720)
        crops = [F.crop(f, box) if box else f for f in frames if f is not None]
        rcrop = (F.crop(ref, box) if box else ref) if ref is not None else None
        diffs = []
        if rcrop is not None:
            for c in crops:
                a = F.gray_small(cv2.resize(rcrop, (c.shape[1], c.shape[0])), 160)
                diffs.append(round(F.diff(a, F.gray_small(c, 160)), 3))
        labels = (["A (without)"] if rcrop is not None else []) + [f"B{i + 1} {t:.1f}s" for i, t in enumerate(times)]
        sheet = F.sheet(([rcrop] if rcrop is not None else []) + crops, labels, cols=5 if rcrop is not None else 4, cell_w=300)
        out = {
            "id": e["id"],
            "type": "effect",
            "name": e.get("name"),
            "window": e["window"],
            "evidence": {"pixel_change": diffs, "reference": how, "region": [round(v, 3) for v in box] if box else "full frame"},
            "sheet": self.save(e["id"], sheet),
        }
        if not self.vlm:
            ok = bool(diffs) and max(diffs) > 0.04
            out.update(status="pass" if ok else "warn", why=f"pixel change up to {max(diffs, default=0):.2f} (no vision check)")
            return out
        d, s = ask(
            self.planner,
            EFFECT_SYSTEM,
            f"Expected: {e.get('expect')}\nThe edit is the effect '{e.get('en')}': {e.get('desc')}"
            + (f" (it targets the {e.get('target')})" if e.get("target") else "")
            + "\n"
            + ("A is the same shot without the effect." if rcrop is not None else "There is no reference frame; judge B frames alone."),
            [sheet],
        )
        d = d if isinstance(d, dict) else {}
        out["evidence"].update(vision=d, vision_s=s)
        vis, strength, matches = bool(d.get("visible")), str(d.get("strength", "")).lower(), d.get("matches")
        if not vis or strength == "none":
            out.update(status="fail", why=f"not visible: {d.get('problem') or d.get('seen') or 'no difference seen'}")
        elif strength == "weak" or matches is False:
            out.update(
                status="warn",
                why=f"{'weak' if strength == 'weak' else 'visible but different from expected'}: {d.get('seen')}"
                + (f" ({d.get('problem')})" if d.get("problem") else ""),
            )
        else:
            out.update(status="pass", why=f"{strength}: {d.get('seen')}")
        return out

    def _motion(self, path, t0, t1, fps=30, width=320):
        frames = F.window(path, t0, t1, fps=fps, width=width)

        def inner(f):  # the middle of the picture: frame-edge overlays (film strips, bars, vignettes) never shake
            h, w = f.shape[:2]
            return f[int(0.15 * h) : int(0.85 * h), int(0.15 * w) : int(0.85 * w)]

        g = [F.gray_small(inner(f), 160) for f in frames]
        sh = [F.shift(a, b) for a, b in zip(g, g[1:])]
        dx = [x[0] for x in sh]
        dy = [x[1] for x in sh]
        if len(dx) < 3:
            return None
        jitter = float(np.std(np.diff(dx)) + np.std(np.diff(dy)))
        return {"jitter": round(jitter, 4), "travel": round(float(np.sum(np.abs(dx)) + np.sum(np.abs(dy))), 3), "frames": len(frames)}

    def _clear_span(self, e, a, b, kinds=("transition", "zoom", "shake")):
        """The longest part of [a, b] that no other edit of `kinds` touches, or None."""
        busy = sorted(
            (x["window"][0] - 0.05, x["window"][1] + 0.05)
            for x in self.m["edits"]
            if x["type"] in kinds and x["id"] != e["id"] and x.get("window") and x["window"][0] < b and a < x["window"][1]
        )
        free, cur = [], a
        for s0, s1 in busy:
            if s0 > cur:
                free.append((cur, min(s0, b)))
            cur = max(cur, s1)
        if cur < b:
            free.append((cur, b))
        return max(free, key=lambda f: f[1] - f[0], default=None)

    def _text_mask(self, frame, times):
        """A feature mask without the texts on screen at `times`: a title does not zoom with the picture, and its sharp
        letters out-vote the picture's features (seen: "Step 1" made a x1.25 punch measure x1.00)."""
        h, w = frame.shape[:2]
        mask = np.full((h, w), 255, np.uint8)
        for e in self.m["edits"]:
            if e["type"] not in ("text", "captions") or not e.get("window"):
                continue
            if not any(e["window"][0] - 0.05 <= t <= e["window"][1] + 0.05 for t in times):
                continue
            box = e.get("box")
            if not box:
                box = [0.05, 0.6, 0.95, 0.98] if e["type"] == "captions" else [0.0, 0.0, 0.0, 0.0]
            x0, y0, x1, y1 = box
            mx, my = 0.06, 0.05  # boxes are estimates: a margin around them
            mask[max(0, int((y0 - my) * h)) : min(h, int((y1 + my) * h)), max(0, int((x0 - mx) * w)) : min(w, int((x1 + mx) * w))] = 0
        return mask

    @staticmethod
    def _scale(a, b, mask=None):
        """Zoom factor from frame a to frame b (ORB features + similarity transform). None if unsure."""
        orb = cv2.ORB_create(800)
        ga, gb = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        ka, da = orb.detectAndCompute(ga, mask)
        kb, db = orb.detectAndCompute(gb, mask)
        if da is None or db is None or len(ka) < 20 or len(kb) < 20:
            return None
        m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db), key=lambda x: x.distance)[:200]
        if len(m) < 15:
            return None
        pa = np.float32([ka[x.queryIdx].pt for x in m])
        pb = np.float32([kb[x.trainIdx].pt for x in m])
        M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=4)
        if M is None or inl is None or inl.sum() < 12:
            return None
        return float(np.hypot(M[0, 0], M[1, 0]))

    def check_motion(self, e, kind=None):
        kind = kind or e["type"]
        t0, t1 = e["window"]
        t1 = min(t1, t0 + 2.0)
        clip = self.clip_at((t0 + t1) / 2)
        out = {"id": e["id"], "type": e["type"], "window": e["window"]}
        if kind in ("shake",):
            got = self._motion(self.video, t0, t1)
            ref = None
            if clip:
                pc = self.piece_at(clip, t0)
                if pc["kind"] == "video":
                    s0 = pc["src_from"] + (t0 - pc["start"]) * pc["speed"]
                    ref = self._motion(pc["path"], s0, s0 + (t1 - t0) * pc["speed"])
            out["evidence"] = {"export": got, "source": ref}
            if not got:
                out.update(status="fail", why="could not read the window")
            else:
                base = (ref or {}).get("jitter", 0.0)
                ok = got["jitter"] > max(0.004, 2.0 * base) or (got["jitter"] - base > 0.006 and got["jitter"] > 1.3 * base)
                out.update(
                    status="pass" if ok else "fail",
                    why=f"camera jitter {got['jitter']:.4f} vs {base:.4f} in the source" + ("" if ok else ": no shake seen"),
                )
            return out
        if kind == "zoom" or (kind == "keyframes" and e.get("property") == "scale"):
            if kind == "zoom":
                rise = max(0.06, min(0.15, (t1 - t0) * 0.25)) if e.get("back", True) else (t1 - t0)
                ta, tb, want = t0 + 0.01, t0 + rise, e.get("to", 1.25)
            else:  # compare the first keyframe with the one furthest from it (in-and-out zooms end where they began),
                # inside the part of the shot that no transition or zoom punch touches (they move the picture too)
                pts = e["points"]
                c = self.clips.get(e.get("on")) or clip
                far = max(pts[1:], key=lambda p: abs(p[1] / max(1e-6, pts[0][1]) - 1))
                span = self._clear_span(e, c["start"] + pts[0][0], c["start"] + far[0])
                if not span or span[1] - span[0] < 0.5:
                    out.update(status="skip", why="transitions or zoom punches cover most of this move")
                    return out
                ta, tb = span[0] + 0.01, span[1] - 0.01
                want = _interp(pts, tb - c["start"]) / max(1e-6, _interp(pts, ta - c["start"]))
                if abs(want - 1) < 0.03:
                    out.update(status="skip", why="the scale keyframes barely change", evidence={"wanted": round(want, 3)})
                    return out
            fa = self.out(ta, 720)
            peaks = [tb + d for d in (-0.05, 0.0, 0.05)]
            s, fb, how = None, None, None
            mask = self._text_mask(fa, [ta] + peaks) if fa is not None else None
            ca = F.faces(fa, 0.7) if fa is not None else []
            for tp in peaks:  # face size first: overlays (frame-edge effects, text) fool feature matching
                f2 = self.out(tp, 720)
                if f2 is None:
                    continue
                cb = F.faces(f2, 0.7) if ca else []
                big = ca and cb and min(ca[0]["box"][2], cb[0]["box"][2]) >= 0.06  # tiny faces give noisy ratios
                s2 = cb[0]["box"][2] / max(1e-6, ca[0]["box"][2]) if big else None
                h2 = "face size"
                if s2 is None:
                    s2, h2 = self._scale(fa, f2, mask) if fa is not None else None, "features"
                if s2 is not None and (s is None or abs(s2 - 1) > abs(s - 1)):
                    s, fb, tb, how = s2, f2, tp, h2
            sheet = F.sheet([f for f in (fa, fb) if f is not None], [f"{ta:.2f}s", f"{tb:.2f}s"], cols=2, cell_w=300)
            out["sheet"] = self.save(e["id"], sheet)
            s_src = None
            c = (self.clips.get(e.get("on")) if kind == "keyframes" else None) or clip
            if s is not None and how == "features" and c is not None:
                # the footage moves too (a drone flying forward zooms in by itself): measure the source over the same
                # moment, framed the same way, and keep only what the edit added
                ba, bb = self.base(c, ta, 720), self.base(c, tb, 720)
                s_src = self._scale(ba, bb, mask) if ba is not None and bb is not None else None
                if s_src:
                    s, how = s / s_src, "features, minus the footage's own zoom"
            out["evidence"] = {
                "scale": round(s, 3) if s else None,
                "wanted": round(want, 3),
                "measured_by": how,
                "footage_zoom": round(s_src, 3) if s_src else None,
            }
            if s is None:
                out.update(status="warn", why="could not measure the zoom")
            elif s_src and abs(s_src - 1) > max(0.06, 2 * abs(want - 1)):
                out.update(status="warn", why=f"the footage itself zooms x{s_src:.2f} here: too much own motion to measure a x{want:.2f} move")
            elif s > max(want, 1 / want) * 1.6 or s < min(want, 1 / want) / 1.6:
                out.update(status="warn", why=f"zoom measurement unreliable (x{s:.2f} vs x{want:.2f} planned)")
            else:
                ok = (s - 1) * (want - 1) > 0 and abs(s - 1) >= 0.4 * abs(want - 1)
                subtle = abs(want - 1) < 0.1 and abs(s - 1) < 0.04  # a slow push of a few % is lost in the footage's own motion
                out.update(
                    status="pass" if ok else "warn" if subtle else "fail",
                    why=f"zoom x{s:.2f} measured, x{want:.2f} planned" + ("" if ok or not subtle else " (too subtle to measure here)"),
                )
            return out
        # other keyframes (position / rotation / opacity / colour): frames at the first and last keyframe must differ
        return self.check_animation(e)

    def check_filter(self, e):
        t0, t1 = e["window"]
        times = [t0 + (t1 - t0) * k for k in (0.25, 0.5, 0.75)]
        outs = self.outs(times, 360)
        bases = []
        for t in times:
            c = self.clip_at(t)
            bases.append(self.base(c, t, 360) if c else None)
        deltas = []
        for o, b in zip(outs, bases):
            if o is None or b is None:
                continue
            co, cb = F.colour(o), F.colour(b)
            deltas.append({k: round(co[k] - cb[k], 3) for k in co})
        out = {"id": e["id"], "type": "filter", "name": e.get("name"), "window": e["window"], "evidence": {"colour_change": deltas}}
        pairs = [(b, o) for o, b in zip(outs, bases) if o is not None and b is not None]
        if pairs:
            out["sheet"] = self.save(
                e["id"],
                F.sheet(
                    [x for p in pairs[:2] for x in p],
                    [f"A{i // 2 + 1} source" if i % 2 == 0 else f"B{i // 2 + 1} export" for i in range(2 * min(2, len(pairs)))],
                    cols=4,
                    cell_w=240,
                ),
            )
        if not deltas:
            out.update(status="warn", why="could not compare colours")
            return out
        mag = max(max(abs(d["brightness"]), abs(d["saturation"]), abs(d["warmth"]) * 0.5, abs(d["tint"]) * 0.5, abs(d["contrast"])) for d in deltas)
        out["evidence"]["change"] = round(mag, 3)
        if mag >= 0.04:
            out.update(status="pass", why=f"colour clearly changed ({mag:.2f})")
        elif mag >= 0.015:
            out.update(status="warn", why=f"subtle colour change ({mag:.2f}); raise strength or pick a stronger look")
        else:
            out.update(status="fail", why=f"no colour change seen ({mag:.3f})")
        return out

    def check_transition(self, e):
        cut, d = e["cut"], e["duration"]
        ta, tb = cut - d / 2 - 0.15, cut + d / 2 + 0.15
        ts = [ta, cut - d / 4, cut, cut + d / 4, tb]
        fr = self.outs(ts, 360)
        if any(f is None for f in fr):
            return {"id": e["id"], "type": "transition", "status": "warn", "why": "could not read the frames"}
        g = [F.gray_small(f, 160) for f in fr]
        to_a = [F.diff(x, g[0]) for x in g[1:4]]
        to_b = [F.diff(x, g[4]) for x in g[1:4]]
        ab = F.diff(g[0], g[4])
        mid_unique = max(min(a, b) for a, b in zip(to_a, to_b))  # a hard cut: every middle frame equals one side
        out = {
            "id": e["id"],
            "type": "transition",
            "name": e.get("name"),
            "window": e["window"],
            "evidence": {"a_vs_b": round(ab, 3), "middle_vs_sides": round(mid_unique, 3)},
            "sheet": self.save(e["id"], F.sheet(fr, [f"{t:.2f}s" for t in ts], cols=5, cell_w=200)),
        }
        if mid_unique > max(0.035, 0.12 * ab):
            out.update(status="pass", why="the frames at the cut differ from both clips (a transition is visible)")
        else:
            out.update(status="fail", why="looks like a hard cut: no transition frames")
        return out

    def check_text(self, e, lines=None):
        """A title, or a few caption lines; animations on the text are judged from the same frames."""
        items = lines or [{"text": e["text"], "start": e["window"][0], "end": e["window"][1]}]
        frames, labels, want = [], [], []
        for i, l in enumerate(items):
            t = l["start"] + min(0.9, (l["end"] - l["start"]) * 0.55)
            f = self.out(t, 540)
            if f is not None:
                frames.append(f)
                labels.append(f"T{i + 1} {t:.1f}s")
                want.append(l["text"])
        out = {"id": e["id"], "type": e["type"], "window": e["window"]}
        if not frames:
            out.update(status="fail", why="no frames")
            return out
        out["sheet"] = self.save(e["id"], F.sheet(frames, labels, cols=min(3, len(frames)), cell_w=300))
        if not self.vlm:
            out.update(status="skip", why="needs the vision model")
            return out
        d, s = ask(
            self.planner,
            TEXT_SYSTEM,
            "Expected text per frame: " + "; ".join(f'{lab.split()[0]}: "{w}"' for lab, w in zip(labels, want)),
            [F.sheet(frames, labels, cols=min(3, len(frames)), cell_w=420)],
        )
        got = (d or {}).get("frames", []) if isinstance(d, dict) else []
        safe = self.m.get("safe") or {}
        probs, scores = [], []
        for i, w in enumerate(want):
            g = got[i] if i < len(got) and isinstance(got[i], dict) else {}
            sc = _similar(g.get("text", ""), w)
            scores.append(round(sc, 2))
            if sc < 0.75:
                probs.append(f'"{w[:30]}" read as "{str(g.get("text", ""))[:30]}"')
            elif g.get("readable") is False:
                probs.append(f'"{w[:30]}" hard to read: {g.get("problem")}')
            box = g.get("box") or []
            overlay_ui = self.m.get("platform") in ("tiktok", "instagram_reels", "youtube_shorts")  # apps drawn over the video
            if overlay_ui and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                x0, y0, x1, y1 = [v / 1000 if max(box) > 1.5 else v for v in box]
                if y0 < safe.get("top", 0) - 0.02 or y1 > 1 - safe.get("bottom", 0) + 0.02 or x1 > 1 - safe.get("right", 0) + 0.03:
                    probs.append(f'"{w[:20]}" sits where the app covers the picture')
        out["evidence"] = {"read": [g.get("text") if isinstance(g, dict) else None for g in got], "match": scores, "vision_s": s}
        bad = [p for p in probs if "read as" in p]
        out.update(status="fail" if bad else ("warn" if probs else "pass"), why="; ".join(probs) or "text present, readable, in the safe zone")
        return out

    def check_animation(self, e):
        t0, t1 = e["window"]
        dur = max(0.2, t1 - t0)
        ts = [t0 + 0.02, t0 + dur * 0.35, t0 + dur * 0.7, min(t1 + 0.12, self.info["seconds"] - 0.05)]
        if e.get("kind") == "outro":
            ts = [max(0, t0 - 0.12), t0 + dur * 0.3, t0 + dur * 0.65, t1 - 0.02]
        fr = self.outs(ts, 540)
        if any(f is None for f in fr):
            return {"id": e["id"], "type": e["type"], "status": "warn", "why": "could not read the frames"}
        box = None
        if e.get("on_text") and e.get("box"):  # a title is small: judge its own area (padded: it may slide in)
            x0, y0, x1, y1 = e["box"]
            pw, ph = (x1 - x0) * 0.35 + 0.05, (y1 - y0) * 0.8 + 0.04
            box = [max(0, x0 - pw), max(0, y0 - ph), min(1, x1 + pw) - max(0, x0 - pw), min(1, y1 + ph) - max(0, y0 - ph)]
            fr = [F.crop(f, box) for f in fr]
        g = [F.gray_small(cv2.resize(f, (192, max(2, round(192 * f.shape[0] / f.shape[1])))), 192) for f in fr]
        change = max(F.diff(g[0], x) for x in g[1:])
        sheet = F.sheet(fr, [f"{t:.2f}s" for t in ts], cols=4, cell_w=300)
        out = {
            "id": e["id"],
            "type": e["type"],
            "name": e.get("name"),
            "window": e["window"],
            "evidence": {"change": round(change, 3), "region": box or "full frame"},
            "sheet": self.save(e["id"], sheet),
        }
        if not self.vlm:
            out.update(status="pass" if change >= 0.02 else "warn", why=f"picture change {change:.3f} across the animation (no vision check)")
            return out
        target = "the text" if e.get("on_text") else "the clip"
        d, s = ask(
            self.planner, MOTION_SYSTEM, f"Expected: {e.get('expect')} ({target}; '{e.get('en')}': {e.get('motion') or e.get('desc')})", [sheet]
        )
        d = d if isinstance(d, dict) else {}
        out["evidence"].update(vision=d, vision_s=s)
        if d.get("animates") is False and change < 0.03:
            out.update(status="fail", why=f"no animation seen: {d.get('problem')}")
        elif d.get("animates") is False or d.get("matches") is False:
            out.update(status="warn", why=f"{'unclear' if d.get('animates') is False else 'animates, but differently'}: {d.get('seen')}")
        else:
            out.update(status="pass", why=str(d.get("seen") or "animates"))
        return out

    def check_audio(self, e):
        t0, t1 = e["window"]
        lv = A.window_level(self.video, t0, t1)
        out = {"id": e["id"], "type": "audio", "window": e["window"], "evidence": {"level": lv}}
        if not lv or lv["mean_db"] < -45:
            out.update(status="fail", why=f"silent in this window ({lv and lv['mean_db']} dB)")
            return out
        probs = []
        if e.get("fade_in", 0) >= 0.5:
            lv_in = A.window_level(self.video, t0, t0 + min(0.3, e["fade_in"] / 3))
            if lv_in and lv_in["mean_db"] > lv["mean_db"] - 2:
                probs.append("no fade-in heard")
        if e.get("fade_out", 0) >= 0.5:
            lv_out = A.window_level(self.video, t1 - min(0.3, e["fade_out"] / 3), t1)
            if lv_out and lv_out["mean_db"] > lv["mean_db"] - 2:
                probs.append("no fade-out heard")
        out.update(status="warn" if probs else "pass", why="; ".join(probs) or f"audible ({lv['mean_db']} dB)")
        return out

    # ------------------------------------------------------------------ run
    def run(self, only=None):
        t0 = time.perf_counter()
        jobs = [("global", self.check_global, ())]
        for c in self.m["clips"]:
            if (only is None or c["id"] in only) and not c.get("overlay") and (c.get("focus") or c.get("chroma")):
                jobs.append((c["id"], self.check_clip, (c,)))
            if (
                (only is None or c["id"] in only or f"{c['id']}:speed" in only)
                and c.get("end", 0) - c.get("start", 0) >= 0.8
                and any(pc["kind"] == "video" and abs(pc["speed"] - 1) > 0.05 for pc in c.get("pieces") or [])
            ):
                jobs.append((f"{c['id']}:speed", self.check_speed, (c,)))
        # slow push-ins the style adds to every shot (ken burns, "kb*") are texture, not asks: check a sample of them
        kb = [e["id"] for e in self.m["edits"] if e["type"] == "keyframes" and str(e["id"]).startswith("kb")]
        kb_skip = set(kb) - set(kb[:: max(1, len(kb) // KB_SAMPLE)][:KB_SAMPLE]) if only is None else set()
        for e in self.m["edits"]:
            if only is not None and e["id"] not in only or e["id"] in kb_skip:
                continue
            typ = e["type"]
            if typ == "effect":
                jobs.append((e["id"], self.check_effect, (e,)))
            elif typ in ("shake", "zoom"):
                jobs.append((e["id"], self.check_motion, (e,)))
            elif typ == "keyframes":
                pts = e.get("points") or []
                if e.get("adjust") or pts and all(p[1] == pts[0][1] for p in pts):
                    continue  # an adjustment (exposure / colour matching): part of the look rather than a move to see
                jobs.append((e["id"], self.check_motion, (e,)))
            elif typ == "filter":
                jobs.append((e["id"], self.check_filter, (e,)))
            elif typ == "transition":
                jobs.append((e["id"], self.check_transition, (e,)))
            elif typ == "text":
                jobs.append((e["id"], self.check_text, (e,)))
            elif typ == "captions":
                lines = e.get("lines") or []
                pick = [lines[i] for i in sorted({0, len(lines) // 2, len(lines) - 1}) if lines]
                jobs.append((e["id"], self.check_text, (e, pick)))
            elif typ == "animation":
                jobs.append((e["id"], self.check_animation, (e,)))
            elif typ == "audio":
                jobs.append((e["id"], self.check_audio, (e,)))
        results = []
        with ThreadPoolExecutor(8) as ex:
            futs = [(i, ex.submit(fn, *args)) for i, fn, args in jobs]
            for i, f in futs:
                try:
                    results.append(f.result())
                except Exception as err:  # noqa: BLE001
                    results.append({"id": i, "status": "warn", "why": f"check failed: {type(err).__name__}: {str(err)[:100]}"})
        order = {"fail": 0, "warn": 1, "pass": 2, "skip": 3}
        results.sort(key=lambda r: (order.get(r.get("status"), 9), str(r.get("id"))))
        counts = {k: sum(1 for r in results if r.get("status") == k) for k in order}
        rep = {
            "video": self.video,
            "draft": self.m["draft"],
            "checked": len(results),
            "counts": counts,
            "seconds": round(time.perf_counter() - t0, 1),
            "results": results,
        }
        (self.dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        self.log(f"verified {len(results)} edit points in {rep['seconds']} s: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail")
        return rep


def verify(video, emap, planner=None, log=print, only=None, vlm=True):
    return Verifier(video, emap, planner, log, vlm).run(only)


def summary(rep):
    lines = []
    for r in rep["results"]:
        mark = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}.get(r.get("status"), "?   ")
        win = r.get("window")
        lines.append(
            f"{mark} {r.get('id'):<8} {r.get('type', ''):<10} {('%.1f-%.1fs' % tuple(win)) if win else '':<11} "
            f"{(r.get('name') or '')[:10]:<10} {r.get('why', '')[:110]}"
        )
    return "\n".join(lines)
