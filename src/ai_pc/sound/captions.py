"""Captions from speech: Whisper's words grouped into lines people can read, written as SRT, VTT or ASS, styled,
burned into a video by libass (FFmpeg), and checked.

  cues = make_cues(words, style)           style: {"kind": "clean" | "bold" | "karaoke" | "boxed", "color", "size", "position", ...}
  srt(cues) / vtt(cues) / ass(cues, style, w, h)
  check_cues(cues, words, style)           readable: line length, two lines at most, reading speed, no overlaps, every word
  check_burn(src_video, out_video, cues, style, timeline=None)   the words are on the frames while they are said, not after

Clean captions (YouTube, Facebook): up to 42 characters a line, two lines, a cue ends at a pause or a full stop and
lasts 1-7 s. Bold captions (Reels, TikTok, Shorts): 1-3 words, big, upper case, the word being said in colour.
Karaoke: a full line, each word lighting up as it is said. Boxed: white on a dark box.
"""

import re
import shutil
from pathlib import Path

import numpy as np

from ai_pc.sound import measure as M

COLORS = {
    "white": "FFFFFF",
    "yellow": "FFE135",
    "green": "39FF14",
    "red": "FF3B30",
    "blue": "2F80ED",
    "orange": "FF9500",
    "pink": "FF2D95",
    "cyan": "00E5FF",
    "black": "000000",
    "purple": "AF52DE",
    "gold": "FFC107",
}
FONT = "Arial"


def default_style(video=None):
    """Bold word-by-word captions for a tall (phone) video, clean lines otherwise."""
    tall = bool(video and video["h"] > video["w"])
    return {
        "kind": "bold" if tall else "clean",
        "color": "white",
        "highlight": "yellow",
        "size": 1.0,
        "position": "bottom",
        "font": None,
        "upper": tall,
    }


# ---------------------------------------------------------------- words -> cues
def _clean_word(w):
    return w.strip()


def _ends_sentence(w):
    return bool(re.search(r"[.?!۔؟]$", w))


def _balance(text, width=42):
    """One line if it fits, else two lines broken at the space nearest the middle (after a comma if close)."""
    if len(text) <= width:
        return [text]
    words = text.split(" ")
    best, cut = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if len(a) > width + 4 or len(b) > width + 4:
            continue
        score = abs(len(a) - len(b)) - (6 if re.search(r"[,;:،]$", words[i - 1]) else 0)
        if best is None or score < best:
            best, cut = score, i
    if cut is None:
        cut = max(1, len(words) // 2)
    return [" ".join(words[:cut]), " ".join(words[cut:])]


def make_cues(words, style=None):
    style = style or default_style()
    kind = style.get("kind", "clean")
    ws = [dict(w, w=_clean_word(w["w"])) for w in words if _clean_word(w["w"])]
    if not ws:
        return []
    cues = []
    if kind == "bold":  # 1-3 words, never across a pause
        cur = []
        for w in ws:
            if cur and (
                len(cur) >= 3 or w["start"] - cur[-1]["end"] > 0.3 or len(" ".join(x["w"] for x in cur + [w])) > 18 or _ends_sentence(cur[-1]["w"])
            ):
                cues.append(cur)
                cur = []
            cur.append(w)
        if cur:
            cues.append(cur)
    else:  # sentences and pauses end a cue; up to two 42-character lines and 6.5 s
        cur = []
        for w in ws:
            if cur:
                text = " ".join(x["w"] for x in cur + [w])
                long_ = len(text) > 80 or w["end"] - cur[0]["start"] > 6.5
                pause = w["start"] - cur[-1]["end"] > 0.5
                stop = _ends_sentence(cur[-1]["w"]) and len(" ".join(x["w"] for x in cur)) >= 18
                comma = re.search(r"[,;:،]$", cur[-1]["w"]) and len(" ".join(x["w"] for x in cur)) >= 50
                if long_ or pause or stop or comma:
                    cues.append(cur)
                    cur = []
            cur.append(w)
        if cur:
            cues.append(cur)
    out = []
    for i, c in enumerate(cues):
        start = c[0]["start"]
        end = c[-1]["end"] + (0.15 if kind == "bold" else 0.3)
        nxt = cues[i + 1][0]["start"] if i + 1 < len(cues) else None
        if nxt is not None:
            end = min(end, nxt - 0.04)
        mind = 0.35 if kind == "bold" else 1.0
        if end - start < mind:
            end = start + mind if nxt is None else min(start + mind, nxt - 0.04)
        text = " ".join(x["w"] for x in c)
        if style.get("upper"):
            text = text.upper()
        out.append(
            {
                "start": round(start, 3),
                "end": round(max(end, start + 0.2), 3),
                "text": text,
                "lines": [text] if kind == "bold" else _balance(text),
                "words": [{"w": (x["w"].upper() if style.get("upper") else x["w"]), "start": x["start"], "end": x["end"]} for x in c],
            }
        )
    return out


def remap(cues, keep, speed=1.0):
    """Cues after a cut: times through the kept [start, end] parts (and a speed change); words cut out go."""

    def tmap(t):
        acc = 0.0
        for a, b in keep:
            if a - 1e-3 <= t <= b + 1e-3:
                return (acc + (min(max(t, a), b) - a)) / speed
            acc += b - a
        return None

    out = []
    for c in cues:
        ws = []
        for w in c["words"]:
            s, e = tmap(w["start"]), tmap(w["end"])
            if s is not None and e is not None and e > s:
                ws.append(dict(w, start=round(s, 3), end=round(e, 3)))
        if not ws:
            continue
        text = " ".join(w["w"] for w in ws)
        s0, e0 = tmap(c["start"]), tmap(c["end"])
        start = ws[0]["start"] if s0 is None else min(s0, ws[0]["start"])
        end = max(ws[-1]["end"] + 0.1, e0 or 0)
        out.append(
            dict(
                c,
                start=round(start, 3),
                end=round(end, 3),
                text=text,
                words=ws,
                lines=_balance(text) if len(c.get("lines", [])) != 1 or len(text) > 42 else [text],
            )
        )
    for i in range(len(out) - 1):  # cuts may have pulled cues together
        if out[i]["end"] > out[i + 1]["start"] - 0.04:
            out[i]["end"] = round(max(out[i]["start"] + 0.2, out[i + 1]["start"] - 0.04), 3)
    return out


# ---------------------------------------------------------------- files
def _ts(t, sep=","):
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s - int(s)) * 1000)) % 1000:03d}"


def srt(cues):
    return "\n".join(f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n" + "\n".join(c["lines"]) + "\n" for i, c in enumerate(cues, 1))


def vtt(cues):
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}\n" + "\n".join(c["lines"]) + "\n" for c in cues)


def _ass_color(hexrgb, alpha=0):
    h = COLORS.get(str(hexrgb).lower(), str(hexrgb).lstrip("#")).upper()
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}"


def _ass_time(t):
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        s, cs = s + 1, 0
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def font_for(cues, style):
    return style.get("font") or FONT


def geometry(style, w, h):
    """Font size, outline and margins in pixels for a w x h frame."""
    kind = style.get("kind", "clean")
    base = min(w, h)
    size = base * (0.085 if kind == "bold" else 0.052) * float(style.get("size", 1.0))
    pos = style.get("position", "bottom")
    margin_v = int(h * (0.22 if kind == "bold" and pos == "bottom" else 0.07))
    return {
        "size": int(round(size)),
        "outline": max(2, int(round(size * (0.09 if kind != "boxed" else 0.25)))),
        "shadow": 0 if kind == "boxed" else max(1, int(size * 0.04)),
        "margin_v": margin_v,
        "margin_h": int(w * 0.06),
        "align": {"bottom": 2, "middle": 5, "top": 8}.get(pos, 2),
    }


def ass(cues, style, w, h):
    kind = style.get("kind", "clean")
    font = font_for(cues, style)
    g = geometry(dict(style, _sample=" ".join(c["text"] for c in cues[:5])), w, h)
    prim = _ass_color(style.get("color", "white"))
    hi = _ass_color(style.get("highlight", "yellow"))
    border = 3 if kind == "boxed" else 1
    back = _ass_color("000000", 0x60 if kind == "boxed" else 0x80)
    outline_c = _ass_color("000000", 0x40 if kind == "boxed" else 0)
    bold = -1 if kind in ("bold", "boxed") or style.get("bold") else 0
    # karaoke: \k fills from SecondaryColour to PrimaryColour as each word is said
    primary, secondary = (hi, prim) if kind == "karaoke" else (prim, hi)
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{g['size']},{primary},{secondary},{outline_c},{back},{bold},0,0,0,100,100,0,0,{border},{g['outline']},{g['shadow']},"
        f"{g['align']},{g['margin_h']},{g['margin_h']},{g['margin_v']},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for c in cues:
        if kind == "bold":  # the word being said in the highlight colour, popping in
            ws = c["words"]
            for j, w_ in enumerate(ws):
                s = w_["start"] if j else c["start"]
                e = ws[j + 1]["start"] if j + 1 < len(ws) else c["end"]
                if e - s < 0.02:
                    continue
                parts = [(f"{{\\c{hi}}}{x['w']}{{\\c{prim}}}" if k == j else x["w"]) for k, x in enumerate(ws)]
                pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}" if j == 0 else ""
                lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{pop}" + " ".join(parts))
        elif kind == "karaoke":
            ks, t = [], c["start"]
            for w_ in c["words"]:
                gap = max(0, int(round((w_["start"] - t) * 100)))
                dur = max(1, int(round((w_["end"] - max(t, w_["start"])) * 100)))
                ks.append((f"{{\\k{gap}}}" if gap else "") + f"{{\\k{dur}}}{w_['w']}")
                t = max(t, w_["end"])
            text = " ".join(ks)
            lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,,{text}")
        else:
            lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,," + "\\N".join(c["lines"]))
    return head + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- checks
def check_cues(cues, words, style):
    kind = style.get("kind", "clean")
    out = []
    if not cues:
        return [{"ok": False, "what": "no captions (no speech was heard)", "level": "fail"}]
    over = [i for i in range(len(cues) - 1) if cues[i]["end"] > cues[i + 1]["start"] + 0.001]
    out.append({"ok": not over, "what": f"{len(cues)} captions in order, none overlapping", "level": "fail"})
    if kind != "bold":
        longl = [ln for c in cues for ln in c["lines"] if len(ln) > 46]
        out.append(
            {
                "ok": not longl and all(len(c["lines"]) <= 2 for c in cues),
                "what": "lines of 42 characters or so, two at most" + (f" (not: {longl[0][:30]}...)" if longl else ""),
                "level": "fail",
            }
        )
        cps = [len(c["text"]) / max(0.1, c["end"] - c["start"]) for c in cues]
        fast = sum(1 for v in cps if v > 21)
        out.append(
            {
                "ok": fast <= max(0, len(cues) // 10),
                "what": f"easy to read: {max(cps):.0f} characters a second at the fastest" + (f" ({fast} too fast)" if fast else ""),
                "level": "warn",
            }
        )
        short = [c for c in cues if c["end"] - c["start"] < 0.7]
        out.append(
            {"ok": len(short) <= max(1, len(cues) // 10), "what": f"each caption stays up long enough ({len(short)} under 0.7 s)", "level": "warn"}
        )
    said = [re.sub(r"\W", "", w["w"].lower()) for w in words if re.sub(r"\W", "", w["w"])]
    shown = [re.sub(r"\W", "", w["w"].lower()) for c in cues for w in c["words"] if re.sub(r"\W", "", w["w"])]
    out.append(
        {
            "ok": len(shown) >= 0.97 * len(said) if said else bool(shown),
            "what": f"every word said is shown ({len(shown)} of {len(said)})",
            "level": "fail",
        }
    )
    if words:
        late = [c for c in cues if c["start"] > c["words"][0]["start"] + 0.05]
        out.append({"ok": not late, "what": "each caption appears as its first word is said", "level": "fail"})
    return out


def _frame(path, t, w=320):
    code, out, err = M.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{max(0, t):.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={w}:-2",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    )
    if not out:
        return None
    h = len(out) // w
    return np.frombuffer(out[: w * h], np.uint8).reshape(h, w).astype(np.int16)


def _band(img, style):
    h = img.shape[0]
    pos = style.get("position", "bottom")
    if pos == "top":
        return img[: int(h * 0.35)], img[int(h * 0.45) :]
    if pos == "middle":
        return img[int(h * 0.3) : int(h * 0.7)], np.concatenate([img[: int(h * 0.2)], img[int(h * 0.8) :]])
    return img[int(h * 0.55) :], img[: int(h * 0.45)]


def check_burn(src, out, cues, style, src_time=lambda t: t):
    """The burned captions are on the frames while they are said: the caption band changes at a cue's middle, the
    rest of the picture does not, and between cues the band is the picture again."""
    if not cues:
        return [{"ok": False, "what": "no captions to burn", "level": "fail"}]
    fps = (M.probe(src).get("video") or {}).get("fps") or 30

    def diff(t):
        """The caption band's change and the rest's against the nearest of three source frames (re-encoding and speed
        changes move frames by one)."""
        b = _frame(out, t)
        best = None
        for k in (-1, 0, 1):
            a = _frame(src, max(0.0, src_time(t) + k / fps))
            if a is None or b is None or a.shape != b.shape:
                continue
            band = float((np.abs(_band(a, style)[0] - _band(b, style)[0]) > 40).mean())
            rest = float(np.abs(_band(a, style)[1] - _band(b, style)[1]).mean())
            if best is None or band + rest / 100 < best[0] + best[1] / 100:
                best = (band, rest)
        return best

    picks = [cues[i] for i in sorted({0, len(cues) // 2, len(cues) - 1})]
    on = [d for d in (diff((c["start"] + c["end"]) / 2) for c in picks) if d]
    gaps = [(cues[i]["end"] + cues[i + 1]["start"]) / 2 for i in range(len(cues) - 1) if cues[i + 1]["start"] - cues[i]["end"] > 0.4][:2]
    off = [d for d in (diff(t) for t in gaps) if d]
    floor = max([d[0] for d in off], default=0.0)
    seen = sum(1 for d in on if d[0] > 0.004 and d[0] > 2 * floor)
    calm = sum(1 for d in on if d[1] < 6)
    weakest = min((d[0] for d in on), default=0.0)
    clear = sum(1 for d in off if d[0] < max(0.003, 0.35 * weakest))
    out_ = [
        {"ok": seen == len(picks), "what": f"the words are on the picture while they are said ({seen} of {len(picks)} looked at)", "level": "fail"},
        {"ok": calm == len(picks), "what": "the rest of the picture is unchanged", "level": "fail"},
    ]
    if gaps:
        out_.append(
            {"ok": clear == len(gaps), "what": f"no caption left on screen between lines ({clear} of {len(gaps)} gaps clear)", "level": "fail"}
        )
    return out_


def write(cues, style, folder, stem, video=None):
    """The caption files: SRT, VTT and (for burning) ASS sized to the video."""
    folder = Path(folder)
    files = {"srt": folder / f"{stem}.srt", "vtt": folder / f"{stem}.vtt"}
    files["srt"].write_text(srt(cues), encoding="utf-8")
    files["vtt"].write_text(vtt(cues), encoding="utf-8")
    w, h = (video["w"], video["h"]) if video else (1920, 1080)
    files["ass"] = folder / f"{stem}.ass"
    files["ass"].write_text(ass(cues, style, w, h), encoding="utf-8-sig")
    return {k: str(v) for k, v in files.items()}


def fonts_dir():
    from ai_pc.core.config import ROOT

    d = ROOT / "fonts"
    return d if d.exists() and any(d.glob("*.ttf")) else None


def copy_fonts(dst):
    d = fonts_dir()
    if d:
        for f in d.glob("*.ttf"):
            shutil.copy(f, Path(dst) / f.name)
