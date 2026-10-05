"""Media and words fitted to one platform and format before anything is uploaded, so the platform never refuses a post:
pictures to an allowed shape (cropped around the subject, or fitted whole on a blurred fill), size and format (sRGB JPEG,
location and camera data removed), videos through the converter's preset for that platform (H.264/AAC, frame, fps,
size cap, faststart) only when they do not already fit, every result measured again. Lengths a platform cannot take are
reported, never cut silently (a video is shortened only when asked: post["trim"] = True).

  prepare(post, job) -> {"media": [files], "kinds": ["image"|"video"], "text", "title", "parts", "tags", "cover",
                         "notes": [...], "problems": [...], "checks": [...]}
"""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps

from ai_pc.core.config import STATE
from ai_pc.social import specs
from ai_pc.social.text import fit

WORK = STATE / "social" / "media"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".wmv", ".3gp", ".mts", ".m2ts", ".flv", ".mpg", ".mpeg", ".ts"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


def kind_of(path):
    s = Path(path).suffix.lower()
    return "video" if s in VIDEO_EXT else "image" if s in IMAGE_EXT else None


def _key(path, *extra):
    st = Path(path).stat()
    return hashlib.sha1(json.dumps([str(Path(path).resolve()).lower(), st.st_size, int(st.st_mtime), *extra], default=str).encode()).hexdigest()[:16]


def _ratio(s):
    if isinstance(s, (int, float)):
        return float(s)
    a, b = str(s).split(":")
    return float(a) / float(b)


def _nearest(r, lo, hi, prefer):
    """The allowed shape closest to r (prefer: the shapes the platform shows best, e.g. 4:5 and 1.91:1)."""
    cands = [p for p in prefer if lo - 1e-3 <= _ratio(p) <= hi + 1e-3] or [f"{lo}:1", f"{hi}:1"]
    return min(cands, key=lambda p: abs(_ratio(p) - r))


# ---------------------------------------------------------------- pictures
def fit_image(path, rule, fill="crop", out_dir=WORK):
    """A picture made acceptable: shape within rule["aspect"], width within min/max, JPEG under max_mb, sRGB, no metadata."""
    from ai_pc.photo import ops as PO

    notes = []
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    icc = im.info.get("icc_profile")
    if icc:
        try:
            import io

            from PIL import ImageCms

            im = ImageCms.profileToProfile(
                im.convert("RGB"), ImageCms.ImageCmsProfile(io.BytesIO(icc)), ImageCms.createProfile("sRGB"), outputMode="RGB"
            )
            notes.append("colours converted to sRGB")
        except Exception:  # noqa: BLE001
            pass
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    w, h = im.size
    r = w / h
    lo, hi = rule.get("aspect", (0.01, 100))
    if not (lo - 1e-3 <= r <= hi + 1e-3):
        target = _nearest(r, lo, hi, rule.get("prefer", ("1:1", "4:5", "16:9", "9:16", "1.91:1")))
        tr = _ratio(target)
        if fill == "fit":
            im, _ = PO.canvas(im, aspect=(tr, 1), fill="blur")
            im = im.convert("RGB")
            notes.append(f"fitted whole into {target} on a blurred fill")
        else:
            im, _ = PO.crop(im, aspect=(tr, 1))
            notes.append(f"cropped to {target} around the subject")
        w, h = im.size
    mx, mn = rule.get("max_w"), rule.get("min_w")
    if mx and w > mx:
        im = im.resize((mx, round(h * mx / w)), Image.LANCZOS)
        notes.append(f"resized to {mx} px wide")
    elif mn and w < mn:
        im = im.resize((mn, round(h * mn / w)), Image.LANCZOS)
        notes.append(f"enlarged to {mn} px wide (the platform's smallest)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{_key(path, rule, fill)}.jpg"
    cap = rule.get("max_mb", 8) * 1e6
    for q in (92, 88, 84, 80, 75, 70, 65):
        im.save(out, "JPEG", quality=q, optimize=True)  # baseline JPEG, no EXIF (no location, no camera data)
        if out.stat().st_size <= cap:
            break
    if out.stat().st_size > cap:
        raise ValueError(f"the picture cannot be made smaller than {cap / 1e6:.0f} MB")
    return str(out), notes


def check_image(path, rule):
    im = Image.open(path)
    w, h = im.size
    lo, hi = rule.get("aspect", (0.01, 100))
    out = [
        {"ok": lo - 1e-3 <= w / h <= hi + 1e-3, "what": f"shape {w}x{h} ({w / h:.2f}) within {lo:.2f}-{hi:.2f}"},
        {
            "ok": Path(path).stat().st_size <= rule.get("max_mb", 8) * 1e6,
            "what": f"{Path(path).stat().st_size / 1e6:.1f} MB within {rule.get('max_mb', 8)} MB",
        },
        {"ok": im.format in ("JPEG", "PNG") or im.format.lower() in rule.get("formats", ("jpeg",)), "what": f"format {im.format}"},
    ]
    if rule.get("min_w"):
        out.append({"ok": w >= rule["min_w"], "what": f"{w} px wide, at least {rule['min_w']}"})
    return out


# ---------------------------------------------------------------- videos
def fit_video(path, rule, fill="blur", trim=False, out_dir=WORK, log=None):
    """A video made acceptable: converted with the platform's preset only when it does not fit already."""
    from ai_pc.convert import encode as E
    from ai_pc.convert import media as MD
    from ai_pc.convert.presets import issues

    p = MD.probe(path)
    v = p.get("video") or {}
    notes, problems = [], []
    if not v:
        return None, notes, ["the file has no picture"]
    d = float(p.get("duration") or 0)
    lo_s, hi_s = rule.get("min_s", 0), rule.get("max_s")
    chain = [{"op": "target", "args": {"name": rule["preset"]}}]
    if d < lo_s - 0.05:
        problems.append(f"the video is {d:.1f} s; {rule['label']} needs at least {lo_s} s")
    if hi_s and d > hi_s + 0.05:
        if trim:
            chain.append({"op": "trim", "args": {"start": 0, "end": hi_s}})
            notes.append(f"shortened to the first {hi_s} s (as asked)")
        else:
            problems.append(
                f"the video is {MD.mmss(d)}; {rule['label']} takes up to {MD.mmss(hi_s)} (say 'cut it to {MD.mmss(hi_s)}', or choose another kind of post)"
            )
    if problems:
        return None, notes, problems
    w, h = v.get("w") or 1, v.get("h") or 1
    alo, ahi = rule.get("aspect", (0.01, 100))
    fix_shape = not (alo - 0.01 <= w / h <= ahi + 0.01)
    if fix_shape:
        target = _nearest(w / h, alo, ahi, rule.get("prefer", ("9:16", "16:9", "1:1", "4:5")))
        chain.append({"op": "aspect", "args": {"ratio": target, "fit": "crop" if fill == "crop" else "blur"}})
        notes.append(f"made {target} ({'cropped' if fill == 'crop' else 'whole, on a blurred copy of itself'})")
    fps = v.get("fps") or 30
    flo, fhi = rule.get("fps", (1, 120))
    if not flo <= fps <= fhi:
        chain.append({"op": "fps", "args": {"fps": max(flo, min(fhi, 30))}})
        notes.append(f"{fps:.0f} fps changed to {max(flo, min(fhi, 30))}")
    if rule.get("max_long") and max(w, h) > rule["max_long"]:
        chain.append({"op": "resize", "args": {"long": rule["max_long"]}})
        notes.append(f"made {rule['max_long']} px on its long side")
    cap = rule.get("max_mb")
    too_big = cap and p["size"] > cap * 1e6
    if too_big:
        chain.append({"op": "compress", "args": {"max_mb": cap * 0.95}})
    gaps = issues(p, rule["preset"])
    if not (fix_shape or too_big or len(chain) > 1 or gaps):
        return str(path), ["ready as it was"], []
    out_dir = Path(out_dir) / _key(path, rule, fill, trim)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = list(out_dir.glob("fit.*"))
    if done:
        return str(done[0]), notes + ["(made earlier)"], []
    r = E.render(chain, [p], out_dir, "fit", log=log or (lambda *a: None))
    if not r.get("outputs"):
        return None, notes, [f"the converter could not make it fit ({'; '.join(r.get('notes') or []) or r.get('status')})"]
    bad = [c for c in r.get("checks") or [] if not c.get("ok") and c.get("level") == "fail"]
    if bad:
        return None, notes, ["the converted video failed its checks: " + "; ".join(c["what"] for c in bad[:3])]
    notes += [g["why"] for g in gaps[:2]]
    return r["outputs"][0], notes, []


def check_video(path, rule):
    from ai_pc.convert import media as MD

    p = MD.probe(path)
    v = p.get("video") or {}
    a = (p.get("audio") or [{}])[0] if isinstance(p.get("audio"), list) else (p.get("audio") or {})
    w, h = v.get("w") or 1, v.get("h") or 1
    alo, ahi = rule.get("aspect", (0.01, 100))
    out = [
        {"ok": v.get("codec") in ("h264", "hevc"), "what": f"video {v.get('codec')}"},
        {"ok": alo - 0.01 <= w / h <= ahi + 0.01, "what": f"{w}x{h} ({w / h:.2f}) within {alo:.2f}-{ahi:.2f}"},
        {"ok": rule.get("min_s", 0) - 0.05 <= p["duration"] <= (rule.get("max_s") or 1e9) + 0.05, "what": f"{p['duration']:.1f} s"},
        {"ok": not rule.get("max_mb") or p["size"] <= rule["max_mb"] * 1e6, "what": f"{p['size'] / 1e6:.1f} MB"},
    ]
    if a:
        out.append({"ok": a.get("codec") in ("aac", "mp3", None), "what": f"sound {a.get('codec')}"})
    return out


# ---------------------------------------------------------------- pictures as a slideshow video
def slideshow(images, out_dir=WORK, seconds=3.0, size=(1080, 1920)):
    """Pictures as a vertical video (each whole on a blurred fill, a soft fade between them, silent sound): for platforms
    that take videos but not picture files (TikTok's API takes photo posts only from a web address)."""
    import subprocess

    from ai_pc.photo import ops as PO

    key = hashlib.sha1(json.dumps([_key(i) for i in images] + [seconds, size]).encode()).hexdigest()[:16]
    folder = Path(out_dir) / f"slides_{key}"
    out = folder / "slideshow.mp4"
    if out.exists():
        return str(out)
    folder.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, f in enumerate(images):
        im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        im, _ = PO.canvas(im, aspect=(size[0], size[1]), fill="blur")
        im = im.convert("RGB").resize(size, Image.LANCZOS)
        fp = folder / f"f{i:03d}.jpg"
        im.save(fp, quality=93)
        frames.append(fp)
    fade = 0.5
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for fp in frames:
        args += ["-loop", "1", "-t", f"{seconds + fade}", "-i", str(fp)]
    args += ["-f", "lavfi", "-t", f"{len(frames) * seconds + fade}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    chain, last = [], "[0:v]"
    for i in range(1, len(frames)):
        lab = f"[x{i}]"
        chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={fade}:offset={i * seconds - fade * (i - 1) - fade + fade * 0:.3f}{lab}")
        last = lab
    vf = (";".join(chain) + ";" if chain else "") + f"{last}fps=30,format=yuv420p[v]"
    args += [
        "-filter_complex",
        vf,
        "-map",
        "[v]",
        "-map",
        f"{len(frames)}:a",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    r = subprocess.run(args, capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode or not out.exists():
        raise ValueError(f"the slideshow could not be made ({r.stderr[-300:]})")
    return str(out)


# ---------------------------------------------------------------- one post for one platform
def prepare(post, job, out_dir=WORK, log=None):
    plat, fmt = job["platform"], job.get("format") or "post"
    rule = specs.media(plat, fmt)
    limits = specs.text(plat, fmt)
    words = fit(post.get("text", ""), plat, fmt, limits, title=post.get("title"), link=post.get("link"), utm=post.get("utm"))
    res = {
        "media": [],
        "kinds": [],
        "text": words["text"],
        "title": words["title"],
        "parts": words["parts"],
        "tags": words["tags"],
        "notes": list(words["notes"]),
        "problems": list(words["problems"]),
        "checks": [],
        "cover": None,
    }
    files = list(post.get("media") or [])
    if rule.get("pictures_as_video") and files and all(kind_of(f) == "image" for f in files if Path(f).exists()):
        try:
            files = [slideshow([f for f in files if Path(f).exists()][: rule.get("max_slides", 35)], out_dir)]
            res["notes"].append(
                f"{len(post['media'])} picture(s) made into a slideshow video ({rule['label']} takes picture posts only from a web address)"
            )
        except ValueError as e:
            res["problems"].append(str(e))
            return res
    lo, hi = rule.get("count", (0, 1))
    if len(files) < lo:
        res["problems"].append(f"{rule['label']} needs {'a picture or a video' if lo == 1 else f'at least {lo} pictures or videos'}")
    if len(files) > hi:
        res["problems"].append(f"{rule['label']} takes up to {hi} {'file' if hi == 1 else 'files'}; {len(files)} were given")
    for f in files[:hi]:
        if not Path(f).exists():
            res["problems"].append(f"no file {f}")
            continue
        k = kind_of(f)
        sub = rule.get(k) if k else None
        if not sub:
            res["problems"].append(f"{rule['label']} does not take {'that kind of file' if not k else k + 's'} ({Path(f).name})")
            continue
        sub = dict(sub, label=rule["label"])
        try:
            if k == "image":
                out, notes = fit_image(f, sub, post.get("fill") or sub.get("fill", "crop"), out_dir)
                checks = check_image(out, sub)
            else:
                out, notes, probs = fit_video(f, sub, post.get("fill") or sub.get("fill", "blur"), bool(post.get("trim")), out_dir, log)
                if probs:
                    res["problems"] += probs
                    continue
                checks = check_video(out, sub)
        except Exception as e:  # noqa: BLE001  (an unreadable file is a problem with the post, reported as such)
            res["problems"].append(f"{Path(f).name}: {e}")
            continue
        res["media"].append(out)
        res["kinds"].append(k)
        if k == "video" and "duration" not in res:
            from ai_pc.convert import media as MD

            res["duration"] = MD.probe(out)["duration"]
        res["notes"] += [f"{Path(f).name}: {n}" for n in notes if n != "ready as it was"]
        res["checks"] += [dict(c, file=Path(f).name) for c in checks]
    if rule.get("one_video") and "video" in res["kinds"] and len(res["kinds"]) > 1:
        res["problems"].append(f"{rule['label']} takes up to 4 pictures or one video, not both")
    if rule.get("kinds") and res["kinds"] and not set(res["kinds"]) <= set(rule["kinds"]):
        res["problems"].append(f"{rule['label']} takes {' or '.join(rule['kinds'])} only")
    bad = [c for c in res["checks"] if not c["ok"]]
    if bad:
        res["problems"] += [f"{c['file']}: {c['what']} is outside what {rule['label']} takes" for c in bad]
    if post.get("cover") and rule.get("cover"):
        try:
            cov, _ = fit_image(post["cover"], dict(rule["cover"], label=rule["label"]), "crop", out_dir)
            res["cover"] = cov
        except Exception as e:  # noqa: BLE001
            res["notes"].append(f"the cover picture was left out ({e})")
    return res
