"""What a 3D render shows, measured from the files (numpy + Pillow; FFmpeg for videos):
  silhouette(mask)  the subject's flat silhouette (Workbench, clear background, the ground hidden): how much of the
                    frame it covers and whether it touches an edge (cut off)
  picture(png)      the render itself: not blank, not too dark, not washed out
  video(mp4, ...)   length and frame rate as asked, it moves, no black frames
  view_checks(...)  all of these for one rendered view, as checks {"what", "ok", "level", "detail"}
"""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from ai_pc.convert import media as MD

NO_WINDOW = 0x08000000


def _check(what, ok, detail="", level="fail"):
    return {"what": what, "ok": bool(ok), "level": "info" if ok else level, "detail": detail}


def silhouette(path):
    a = np.asarray(Image.open(path).convert("RGBA"))[..., 3] > 16
    h, w = a.shape
    if not a.any():
        return {"coverage": 0.0, "bbox": None, "touches": []}
    ys, xs = np.nonzero(a)
    bb = (xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h)
    touches = [n for n, hit in (("left", xs.min() == 0), ("right", xs.max() == w - 1), ("top", ys.min() == 0), ("bottom", ys.max() == h - 1)) if hit]
    return {"coverage": float(a.mean()), "bbox": [round(v, 4) for v in bb], "touches": touches}


def picture(path):
    im = np.asarray(Image.open(path).convert("RGB")).astype(np.float32) / 255.0
    lum = im @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return {"mean": float(lum.mean()), "std": float(lum.std()), "clip_hi": float((lum > 0.985).mean()), "clip_lo": float((lum < 0.015).mean())}


def view_checks(name, entry, path, mask, cut_ok=()):
    """The checks for one still: the file, the subject in full view, a real picture."""
    out = []
    p = Path(path)
    if not p.exists() or p.stat().st_size < 1000:
        return [_check(f"{name}: rendered", False, "no picture was written")]
    s = silhouette(mask)
    out.append(_check(f"{name}: subject visible", s["coverage"] >= 0.03, f"covers {s['coverage']:.0%} of the frame"))
    edges = [t for t in s["touches"] if t not in cut_ok]
    out.append(_check(f"{name}: nothing cut off", not edges, f"touches the {', '.join(edges)} edge" if edges else "", "warn"))
    fr = entry.get("framing") or {}
    if fr:
        inside = fr.get("behind", 0) == 0 and fr["x0"] >= -0.001 and fr["y0"] >= -0.001 and fr["x1"] <= 1.001 and fr["y1"] <= 1.001
        out.append(_check(f"{name}: whole subject framed", inside, f"x {fr['x0']:.2f}-{fr['x1']:.2f}, y {fr['y0']:.2f}-{fr['y1']:.2f}", "warn"))
    pc = picture(p)
    out.append(_check(f"{name}: a real picture", pc["std"] > 0.03, f"contrast {pc['std']:.3f}"))
    out.append(_check(f"{name}: exposure", 0.2 <= pc["mean"] <= 0.88 and pc["clip_hi"] < 0.12, f"brightness {pc['mean']:.2f}, "
                      f"{pc['clip_hi']:.0%} washed out", "warn"))
    return out


def encode(frames_dir, out, fps=30, gpu=True):
    """PNG frames -> an MP4 (H.264, the Intel GPU when it works, else x264)."""
    pattern = str(Path(frames_dir) / "frame_%04d.png")
    for enc in ((["-c:v", "h264_qsv", "-global_quality", "21", "-pix_fmt", "nv12"] if gpu else []), ["-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p"]):
        if not enc:
            continue
        r = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-v", "error", "-framerate", str(fps), "-i", pattern] + enc + ["-movflags", "+faststart", str(out)],
                           capture_output=True, creationflags=NO_WINDOW, timeout=900)
        if r.returncode == 0 and Path(out).exists():
            return enc[1]
    raise RuntimeError("the frames could not be made into a video")


def video(path, frames, fps, dark_ok=False):
    out = []
    try:
        p = MD.probe(path)
    except MD.MediaError as e:
        return [_check("video: readable", False, str(e))]
    want = frames / fps
    out.append(_check("video: length", abs(p["duration"] - want) <= 2.0 / fps + 0.05, f"{p['duration']:.2f} s (expected {want:.2f} s)"))
    out.append(_check("video: frame rate", abs((p["video"] or {}).get("fps", 0) - fps) < 0.5, f"{(p['video'] or {}).get('fps')} fps"))
    errs = MD.decodes(path, p["duration"], (p["video"] or {}).get("w", 0) * (p["video"] or {}).get("h", 0))
    out.append(_check("video: plays through", not errs, "; ".join(errs[:2])))
    shots = []
    for t in (0.0, want * 0.33, want * 0.66, max(0.0, want - 0.1)):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, creationflags=NO_WINDOW, timeout=60)
        if len(r.stdout) == 160 * 90:
            shots.append(np.frombuffer(r.stdout, np.uint8).astype(np.float32) / 255)
    spread = max((float(s.std()) for s in shots), default=0.0)
    change = max((float(np.abs(shots[0] - s).mean()) for s in shots[1:]), default=0.0)
    out.append(_check("video: it moves", len(shots) >= 3 and change > max(0.004, 0.12 * spread), f"change {change:.3f}"))
    if dark_ok:  # a title on a dark background: each frame needs something on it, not brightness
        out.append(_check("video: no empty frames", bool(shots) and min(float(s.std()) for s in shots) > 0.01, ""))
    else:
        out.append(_check("video: no black frames", bool(shots) and min(float(s.mean()) for s in shots) > 0.05, ""))
    return out
