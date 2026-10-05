"""Resolved plan (editplan.resolve) -> JianYing 5.9 draft written by pyJianYingDraft, plus the EDIT MAP: where every
clip and edit sits on the timeline, what it is, and what it should look like. The verifier works from the edit map.

Track stack, bottom to top: main video, overlay layers, filter tracks, effect tracks, titles, captions, effects marked
over_text, then audio. Items that overlap in time get their own track. Every feature is applied in its own guard, so
one failure becomes a note in the edit map instead of a failed build. ~0.1-0.5 s per draft.
"""
import os
import re
import time
from pathlib import Path

import pyJianYingDraft as jy
from pyJianYingDraft import SEC, trange

from .editplan import Catalog, motion_keyframes

DRAFTS = Path(os.environ["LOCALAPPDATA"]) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
KFP = {"scale": "uniform_scale", "x": "position_x", "y": "position_y", "rotation": "rotation", "alpha": "alpha",
       "brightness": "brightness", "contrast": "contrast", "saturation": "saturation", "volume": "volume"}


def us(x):
    return int(round(float(x) * SEC))


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


_DUR = {}


def material_seconds(path, audio=False):
    """Length of a media file as the engine measures it (its checks are exact to the microsecond)."""
    if path not in _DUR:
        _DUR[path] = (jy.AudioMaterial(path) if audio else jy.VideoMaterial(path)).duration / SEC
    return _DUR[path]


def kf_time(pc, t):
    """JianYing places a keyframe at FILE time: the clip's source start + seconds into the clip x speed (measured on
    5.9 exports; pyJianYingDraft's docs suggest time from the clip start, which only holds for clips that start at 0)."""
    if pc.get("kind") == "image":
        return t
    return pc.get("src_from", 0.0) + t * pc.get("speed", 1.0)


def draft_name(name):
    word = re.sub(r"[^a-z0-9]+", "", str(name or "").lower().removeprefix("agent_").split("_")[0])[:10] or "edit"
    return f"agent_{word}_{time.strftime('%H%M%S')}"


def _lanes(items, key=lambda x: x["window"]):
    """Greedy split of time ranges into non-overlapping lanes (one track each)."""
    lanes = []
    for it in sorted(items, key=lambda x: key(x)[0]):
        for lane in lanes:
            if key(lane[-1])[1] <= key(it)[0] + 1e-6:
                lane.append(it)
                break
        else:
            lanes.append([it])
    return lanes


class Builder:
    def __init__(self, R, drafts=DRAFTS, name=None):
        self.R, self.cat = R, Catalog.shared()
        self.notes = list(R.get("notes", []))
        self.name = name or draft_name(R.get("name"))
        self.drafts = Path(drafts)
        self.stats = {}
        self.segs = {}       # clip id -> [VideoSegment per piece]
        self.tsegs = {}      # text id -> TextSegment
        self.edit_out = []

    def _ok(self, what, fn, *a, **k):
        try:
            r = fn(*a, **k)
            self.stats[what] = self.stats.get(what, 0) + 1
            return r if r is not None else True
        except Exception as e:  # noqa: BLE001  (one bad feature must not sink the build)
            self.notes.append(f"{what}: {type(e).__name__}: {str(e)[:120]}")
            return None

    # ------------------------------------------------------------------ video
    def _video_piece(self, clip, pc, start_us, first, last, main):
        st = clip["settings"]
        sx, sy = clip.get("stretch") or (1.0, 1.0)
        cs = jy.ClipSettings(alpha=st["alpha"], flip_horizontal=st["flip_h"], flip_vertical=st["flip_v"], rotation=st["rotation"],
                             scale_x=st["scale"] * sx, scale_y=st["scale"] * sy, transform_x=st["x"], transform_y=st["y"])
        mat = pc["path"]
        if clip.get("crop"):
            c = clip["crop"]
            mat = jy.VideoMaterial(pc["path"], crop_settings=jy.CropSettings(
                upper_left_x=c["left"], upper_left_y=c["top"], upper_right_x=1 - c["right"], upper_right_y=c["top"],
                lower_left_x=c["left"], lower_left_y=1 - c["bottom"], lower_right_x=1 - c["right"], lower_right_y=1 - c["bottom"]))
        if pc["kind"] == "image":
            seg = jy.VideoSegment(mat, trange(start_us, us(pc["dur"])), clip_settings=cs)
        else:
            span = min(pc["src_span"], material_seconds(pc["path"]) - pc["src_from"] - 0.001)
            seg = jy.VideoSegment(mat, trange(start_us, us(span / pc["speed"])), source_timerange=trange(us(pc["src_from"]), us(span)),
                                  speed=pc["speed"], volume=clip["volume"], change_pitch=clip.get("pitch_with_speed", False), clip_settings=cs)
        if clip.get("chroma"):
            ch = clip["chroma"]
            self._ok("chroma", seg.add_chroma, ch["color"] + "FF", ch["intensity"], ch["shadow"], ch["edge_smooth"], ch["spill"])
        if clip.get("mask"):
            m = clip["mask"]
            mt = jy.MaskType[m["type"]]
            mw, mh = seg.material_size
            kw = dict(center_x=(m["x"] - 0.5) * mw, center_y=(0.5 - m["y"]) * mh, size=m["size"], rotation=m["rotation"],
                      feather=m["feather"], invert=m["invert"])
            if m["type"] == "矩形":
                kw.update(rect_width=m["width"] or m["size"], round_corner=m["round"] or 0)
            self._ok("mask", seg.add_mask, mt, **kw)
        if clip.get("blend"):
            self._ok("blend", seg.set_mix_mode, jy.MixModeType[clip["blend"]])
        if main and clip.get("background"):
            bg = clip["background"]
            if isinstance(bg, (list, tuple)) or bg == "blur":
                self._ok("background", seg.add_background_filling, "blur", bg[1] if isinstance(bg, (list, tuple)) else 0.375)
            else:
                self._ok("background", seg.add_background_filling, "color", 0.0625, bg + "FF")
        if pc["kind"] == "video" and (clip["fade_in"] and first or clip["fade_out"] and last):
            self._ok("audio fade", seg.add_fade, us(clip["fade_in"] if first else 0), us(clip["fade_out"] if last else 0))
        for prop, pts in motion_keyframes(clip, self.R["edits"], {"start": start_us / SEC, "dur": pc["dur"]}).items():
            for t, v in pts:
                if prop == "volume" and pc["kind"] == "image":
                    continue
                if prop == "scale" and clip.get("stretch"):  # a stretched clip keeps its proportions while zooming
                    self._ok("keyframes", seg.add_keyframe, jy.KeyframeProperty.scale_x, us(kf_time(pc, t)), v * sx)
                    self._ok("keyframes", seg.add_keyframe, jy.KeyframeProperty.scale_y, us(kf_time(pc, t)), v * sy)
                    continue
                self._ok("keyframes", seg.add_keyframe, getattr(jy.KeyframeProperty, KFP[prop]), us(kf_time(pc, t)), v)
        return seg

    def _clips(self, clips, main):
        out = []
        cursor = None  # the main track is laid end to end: each clip starts exactly where the previous one ended
        for clip in clips:
            segs = []
            t = us(clip["start"])
            if main and cursor is not None and abs(t - cursor) < 20000:  # < 20 ms apart = meant to touch (rounding)
                t = cursor
            for i, pc in enumerate(clip["pieces"]):
                seg = self._ok("video piece", self._video_piece, clip, pc, t, i == 0, i == len(clip["pieces"]) - 1, main)
                if seg:
                    segs.append(seg)
                    t = seg.target_timerange.end  # chain on the real end (no 1 us gaps or overlaps)
            if main and segs:
                cursor = segs[-1].target_timerange.end
            self.segs[clip["id"]] = segs
            out.append(clip)
        return out

    # ------------------------------------------------------------------ edits on clips
    def _segment_edits(self):
        for e in self.R["edits"]:
            segs = self.segs.get(e.get("on")) if e.get("on") else None
            if e["type"] == "transition":
                a, b = self.segs.get(e["after"]), self.segs.get(e["before"])
                if a and b:
                    self._ok("transition", a[-1].add_transition, self.cat.enum(e["item"]), duration=us(e["duration"]))
            elif e["type"] == "effect" and e["mode"] == "segment" and segs:
                for s in segs:
                    self._ok("effect (clip)", s.add_effect, self.cat.enum(e["item"]), e.get("params"))
            elif e["type"] == "filter" and e["mode"] == "segment" and segs:
                for s in segs:
                    self._ok("filter (clip)", s.add_filter, self.cat.enum(e["item"]), e["strength"])
            elif e["type"] == "animation" and not e["on_text"] and segs:
                target = segs[-1] if e["kind"] == "outro" else segs[0]
                self._ok(f"clip {e['kind']}", target.add_animation, self.cat.enum(e["item"]), us(e["duration"]))

    # ------------------------------------------------------------------ texts
    def _from_template(self, folder, t):
        """A copy of an existing JianYing project with its media replaced by name and its texts rewritten."""
        script = folder.duplicate_as_template(t["draft"], self.name, allow_replace=self.name.startswith("agent_"))
        for old_name, path in t["media"].items():
            audio = path.lower().endswith((".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"))
            mat = jy.AudioMaterial(path) if audio else jy.VideoMaterial(path)
            self._ok("template media", script.replace_material_by_name, old_name, mat)
        for x in t["texts"]:
            tracks = script.list_imported_tracks(jy.TrackType.text)
            if isinstance(x["track"], str):
                tr = next((tk for tk in tracks if tk.name == x["track"]), None)
            else:
                tr = tracks[x["track"]] if 0 <= int(x["track"]) < len(tracks) else None
            if tr is None:
                self.notes.append(f"template: no text track {x['track']!r}")
                continue
            self._ok("template text", script.replace_text, tr, x["index"], x["text"])
        return script

    def _text_seg(self, text, start, dur, st, pos):
        style = jy.TextStyle(size=st["size"], bold=st["bold"], italic=st["italic"], underline=st["underline"], color=_rgb(st["color"]),
                             alpha=st["alpha"], align=st["align"], letter_spacing=st["letter_spacing"], line_spacing=st["line_spacing"],
                             vertical=st.get("vertical", False), auto_wrapping=True, max_line_width=st.get("max_width", 0.82))
        cs = jy.ClipSettings(transform_x=pos[0], transform_y=pos[1], scale_x=st["scale"], scale_y=st["scale"], rotation=st["rotation"])
        border = jy.TextBorder(alpha=st["outline"]["alpha"], color=_rgb(st["outline"]["color"]), width=st["outline"]["width"]) if st.get("outline") else None
        bg = st.get("background")
        background = jy.TextBackground(color=bg["color"], style=bg["style"], alpha=bg["alpha"], round_radius=bg["round"],
                                       height=bg.get("height", 0.14), width=bg.get("width", 0.14),
                                       horizontal_offset=bg.get("x_offset", 0.5), vertical_offset=bg.get("y_offset", 0.5)) if bg else None
        sh = st.get("shadow")
        shadow = jy.TextShadow(alpha=sh["alpha"], color=_rgb(sh["color"]), diffuse=sh["diffuse"], distance=sh["distance"], angle=sh["angle"]) if sh else None
        font = self.cat.enum(st["font"]) if st.get("font") else None
        return jy.TextSegment(text, trange(us(start), us(dur)), font=font, style=style, clip_settings=cs, border=border,
                              background=background, shadow=shadow)

    # ------------------------------------------------------------------ build
    def build(self):
        t0 = time.perf_counter()
        R = self.R
        W, H = R["canvas"]
        folder = jy.DraftFolder(str(self.drafts))
        if R.get("template"):
            script = self._from_template(folder, R["template"])
        else:
            script = folder.create_draft(self.name, W, H, R.get("fps", 30), allow_replace=self.name.startswith("agent_"))
        edits = R["edits"]
        # video: main track and overlay layers
        self._clips(R["clips"], True)
        layer_lanes = _lanes(R["layers"], key=lambda c: (c["start"], c["end"]))
        for c in R["layers"]:
            self._clips([c], False)
        self._segment_edits()
        # texts
        texts = [e for e in edits if e["type"] == "text"]
        for e in texts:
            seg = self._ok("text", self._text_seg, e["text"], e["start"], e["duration"], e["style"], e["position"])
            if seg:
                self.tsegs[e["id"]] = seg
        order = {"intro": 0, "outro": 1, "loop": 2}  # loops last: they fill the time the others leave
        for e in sorted([e for e in edits if e["type"] == "animation" and e["on_text"]], key=lambda e: order[e["kind"]]):
            seg = self.tsegs.get(e["on"])
            if seg:
                self._ok(f"text {e['kind']}", seg.add_animation, self.cat.enum(e["item"]), us(e["duration"]))
        for e in [e for e in edits if e["type"] == "keyframes" and e["on"] in self.tsegs]:
            tx = next(t for t in texts if t["id"] == e["on"])
            pseudo = {"id": tx["id"], "start": tx["start"], "volume": 1.0,
                      "settings": {"scale": tx["style"]["scale"], "x": tx["position"][0], "y": tx["position"][1], "rotation": tx["style"]["rotation"], "alpha": tx["style"]["alpha"]}}
            for prop, pts in motion_keyframes(pseudo, [e], {"start": tx["start"], "dur": tx["duration"]}).items():
                if prop in ("volume", "brightness", "contrast", "saturation"):
                    continue
                for t, v in pts:
                    self._ok("keyframes", self.tsegs[e["on"]].add_keyframe, getattr(jy.KeyframeProperty, KFP[prop]), us(t), v)
        # ---- tracks, bottom to top
        tracks = []
        if R["clips"]:
            script.append_track(jy.TrackSpec(jy.TrackType.video, "main"))
            tracks.append("main")
        for c in R["clips"]:
            for s in self.segs.get(c["id"], []):
                self._ok("add video", script.add_segment, s, "main")
        for i, lane in enumerate(layer_lanes):
            tn = f"layer{i + 1}"
            script.append_track(jy.TrackSpec(jy.TrackType.video, tn))
            tracks.append(tn)
            for c in lane:
                for s in self.segs.get(c["id"], []):
                    self._ok("add layer", script.add_segment, s, tn)
                c["track"] = tn
        for i, lane in enumerate(_lanes([e for e in edits if e["type"] == "filter" and e["mode"] == "track"])):
            tn = f"look{i + 1}"
            script.append_track(jy.TrackSpec(jy.TrackType.filter, tn))
            tracks.append(tn)
            for e in lane:
                a, b = e["window"]
                if self._ok("filter (track)", script.add_filter, self.cat.enum(e["item"]), trange(us(a), us(b - a)), tn, e["strength"]):
                    e["track"] = tn

        def fx_tracks(sel, prefix):
            for i, lane in enumerate(_lanes(sel)):
                tn = f"{prefix}{i + 1}"
                script.append_track(jy.TrackSpec(jy.TrackType.effect, tn))
                tracks.append(tn)
                for e in lane:
                    a, b = e["window"]
                    if self._ok("effect (track)", script.add_effect, self.cat.enum(e["item"]), trange(us(a), us(b - a)), tn, params=e.get("params")):
                        e["track"] = tn
        fx_tracks([e for e in edits if e["type"] == "effect" and e["mode"] == "track" and not e["over_text"]], "fx")
        for i, lane in enumerate(_lanes(texts)):
            tn = f"title{i + 1}"
            script.append_track(jy.TrackSpec(jy.TrackType.text, tn))
            tracks.append(tn)
            for e in lane:
                if e["id"] in self.tsegs and self._ok("add text", script.add_segment, self.tsegs[e["id"]], tn):
                    e["track"] = tn
        for k, cap in enumerate([e for e in edits if e["type"] == "captions"]):
            tn = f"captions{k + 1}"
            script.append_track(jy.TrackSpec(jy.TrackType.text, tn))
            tracks.append(tn)
            for line in cap["lines"]:
                seg = self._ok("caption", self._text_seg, line["text"], line["start"], line["end"] - line["start"], cap["style"], cap["position"])
                if seg:
                    if cap.get("intro"):
                        self._ok("caption intro", seg.add_animation, self.cat.enum(cap["intro"]), us(min(0.3, (line["end"] - line["start"]) / 3)))
                    self._ok("add caption", script.add_segment, seg, tn)
            cap["track"] = tn
        fx_tracks([e for e in edits if e["type"] == "effect" and e["mode"] == "track" and e["over_text"]], "fxtop")
        auds = [e for e in edits if e["type"] == "audio"]
        for i, lane in enumerate(_lanes(auds)):
            tn = f"audio{i + 1}"
            script.append_track(jy.TrackSpec(jy.TrackType.audio, tn))
            tracks.append(tn)
            for e in lane:
                span = min(e["duration"] * e["speed"], material_seconds(e["path"], audio=True) - e["src_from"] - 0.001)
                seg = self._ok("audio", jy.AudioSegment, e["path"], trange(us(e["at"]), us(span / e["speed"])),
                               source_timerange=trange(us(e["src_from"]), us(span)), speed=e["speed"], volume=e["volume"],
                               change_pitch=e.get("pitch_with_speed", False))
                if not seg:
                    continue
                if e["fade_in"] or e["fade_out"]:
                    self._ok("audio fade", seg.add_fade, us(min(e["fade_in"], e["duration"] / 2)), us(min(e["fade_out"], e["duration"] / 2)))
                if e.get("effect"):
                    self._ok("audio effect", seg.add_effect, self.cat.enum(e["effect"]), e.get("effect_params"))
                for t, v in e.get("keyframes", []):
                    self._ok("volume keyframe", seg.add_keyframe, us(e["src_from"] + t * e["speed"]), e["volume"] * v)
                if self._ok("add audio", script.add_segment, seg, tn):
                    e["track"] = tn
        script.save()
        return self._edit_map(script, tracks, time.perf_counter() - t0)

    def _edit_map(self, script, tracks, secs):
        R = self.R
        clips = []
        for c in R["clips"] + R["layers"]:
            clips.append({k: c.get(k) for k in ("id", "file", "path", "kind", "overlay", "start", "end", "dur", "pieces", "settings", "visible",
                                                "src_size", "focus", "window", "track", "reversed")} | {"chroma": bool(c.get("chroma")),
                                                                                                         "blend": c.get("blend"), "mask": c.get("mask")})
        edits = []
        for e in R["edits"]:
            x = {k: v for k, v in e.items() if not k.startswith("_")}
            if e.get("item"):
                card = self.cat.card(e["item"])
                x.update(name=card["name"], en=card.get("en"), desc=card.get("desc"), category=card["category"])
                for f in ("target", "moves_image", "look", "motion"):
                    if f in card:
                        x[f] = card[f]
            edits.append(x)
        return {"draft": self.name, "path": str(self.drafts / self.name), "canvas": R["canvas"], "aspect": R["aspect"], "fps": R.get("fps", 30),
                "platform": R.get("platform"), "safe": R.get("safe"), "seconds": round(script.duration / SEC, 3), "tracks": tracks,
                "clips": clips, "edits": edits, "stats": self.stats, "notes": self.notes, "build_ms": round(secs * 1000)}


def build(R, drafts=DRAFTS, name=None):
    return Builder(R, drafts, name).build()
