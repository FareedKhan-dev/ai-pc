"""Fast frame access and the image measurements shared by the media analyzer (analyze.py) and the edit verifier
(verify.py): probing, sampling a whole video quickly, frames at exact times, faces and eyes (YuNet, ~5 ms per frame),
global camera shift (phase correlation), colour statistics and labelled contact sheets for the vision model.

Speed: sampling skips B-frames (they are most of the decoding work) and runs 4 ffmpeg processes on time chunks;
if a file has so few non-B frames that sampling gets sparse, those chunks are decoded fully instead.
"""
import io
import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ai_pc.core.config import ROOT

cv2.ocl.setUseOpenCL(False)  # CPU only: OpenCL adds nothing at these sizes and crashes at interpreter exit
YUNET = ROOT / "models" / "yunet" / "face_detection_yunet_2023mar.onnx"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no console flashes for the many short ffmpeg runs
_PTS = re.compile(r"pts_time:\s*([-0-9.]+)")


def _run(args, binary=True):
    return subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, text=not binary)


def probe(path):
    """Duration, size, frame rate, rotation and streams of a media file (ffprobe)."""
    r = _run(["ffprobe", "-v", "error", "-show_entries",
              "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:"
              "stream_side_data=rotation:stream_tags=rotate", "-of", "json", str(path)], binary=False)
    d = json.loads(r.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    out = {"seconds": float(d.get("format", {}).get("duration") or 0), "has_audio": a is not None, "has_video": v is not None}
    if v:
        num, den = (v.get("r_frame_rate") or "0/1").split("/")
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            rot = int(sd.get("rotation", 0) or 0)
        rot = rot or int((v.get("tags") or {}).get("rotate", 0) or 0)
        w, h = v.get("width", 0), v.get("height", 0)
        if abs(rot) in (90, 270):  # phone videos: stored landscape, shown portrait
            w, h = h, w
        out.update(width=w, height=h, fps=round(float(num) / float(den or 1), 3), codec=v.get("codec_name"), rotation=rot)
    if a:
        out.update(audio_codec=a.get("codec_name"), sample_rate=int(a.get("sample_rate") or 0), channels=a.get("channels"))
    return out


def _decode(path, start, dur, fps, width, skip_b):
    """Frames of one time chunk with their exact times (showinfo), at most `fps` per second."""
    sel = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{1 / fps - 0.004:.4f})',scale={width}:-2,showinfo"
    args = ["ffmpeg", "-v", "info", "-nostats"] + (["-skip_frame", "bidir"] if skip_b else []) + \
           ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path), "-an", "-vf", sel, "-fps_mode", "passthrough",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    r = _run(args)
    times = [start + float(x) for x in _PTS.findall(r.stderr.decode("utf-8", "ignore"))]
    return times, r.stdout


def sample(path, fps=4.0, width=640, start=0.0, end=None, chunks=4):
    """(times, frames[N,H,W,3] BGR) sampled over [start, end] at up to `fps` frames per second."""
    info = probe(path)
    end = min(end or info["seconds"], info["seconds"])
    height = int(round(width * info["height"] / info["width"] / 2) * 2)
    n = max(1, min(chunks, int((end - start) // 2) or 1))
    edges = [start + (end - start) * i / n for i in range(n + 1)]

    def one(i):
        a, b = edges[i], edges[i + 1]
        times, raw = _decode(path, a, b - a, fps, width, True)
        if len(times) < 0.5 * (b - a) * min(fps, 2):  # B-frame-heavy file: too sparse without them
            times, raw = _decode(path, a, b - a, fps, width, False)
        k = len(raw) // (width * height * 3)
        return times[:k], np.frombuffer(raw, np.uint8)[:k * width * height * 3].reshape(k, height, width, 3)
    with ThreadPoolExecutor(n) as ex:
        parts = list(ex.map(one, range(n)))
    times = [t for p in parts for t in p[0]]
    frames = np.concatenate([p[1] for p in parts]) if parts and sum(len(p[0]) for p in parts) else np.zeros((0, height, width, 3), np.uint8)
    return times, frames


def frame_at(path, t, width=None):
    """One frame (BGR) at time t, accurately seeked. None past the end."""
    vf = ["-vf", f"scale={width}:-2"] if width else []
    r = _run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1", *vf,
              "-f", "image2pipe", "-vcodec", "png", "-"])
    if not r.stdout:
        return None
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)


def frames_at(path, times, width=None, workers=8):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda t: frame_at(path, t, width), times))


def window(path, t0, t1, fps=15, width=480):
    """All frames of [t0, t1] at `fps` (full decode of just that window): for motion checks."""
    info = probe(path)
    height = int(round(width * info["height"] / info["width"] / 2) * 2)
    r = _run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{max(0.05, t1 - t0):.3f}", "-i", str(path),
              "-an", "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"])
    k = len(r.stdout) // (width * height * 3)
    return np.frombuffer(r.stdout, np.uint8)[:k * width * height * 3].reshape(k, height, width, 3)


def image(path, width=None):
    """A photo as BGR (any format PIL reads), optionally resized to `width`."""
    im = Image.open(path)
    im = im.convert("RGB")
    if width and im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


# ------------------------------------------------------------------------------------------------ faces and eyes
_tls = threading.local()


def faces(frame, min_score=0.6):
    """Faces in a BGR frame, biggest first: {box: [x, y, w, h], right_eye, left_eye, nose, score}, all 0-1 of the frame.
    One detector per thread, so many frames can be checked in parallel."""
    h, w = frame.shape[:2]
    d = getattr(_tls, "yunet", None)
    if d is None:
        d = _tls.yunet = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), min_score, 0.3, 50)
    d.setInputSize((w, h))
    d.setScoreThreshold(min_score)
    _, found = d.detect(frame)
    out = []
    for f in (found if found is not None else []):
        x, y, fw, fh = (float(v) for v in f[:4])
        out.append({"box": [x / w, y / h, fw / w, fh / h], "right_eye": [f[4] / w, f[5] / h], "left_eye": [f[6] / w, f[7] / h],
                    "nose": [f[8] / w, f[9] / h], "score": round(float(f[14]), 3)})
    for o in out:
        o.update({k: [round(float(v), 4) for v in o[k]] for k in ("box", "right_eye", "left_eye", "nose")})
    return sorted(out, key=lambda o: -o["box"][2] * o["box"][3])


def faces_many(frames, workers=6, min_score=0.6):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda f: faces(f, min_score), frames))


def eye_region(face, pad=0.6):
    """Box [x, y, w, h] (0-1) around both eyes of a face, padded by `pad` x the eye distance."""
    (rx, ry), (lx, ly) = face["right_eye"], face["left_eye"]
    d = max(abs(lx - rx), face["box"][2] * 0.3)
    x0, x1 = min(rx, lx) - pad * d, max(rx, lx) + pad * d
    y0, y1 = min(ry, ly) - pad * d * 0.8, max(ry, ly) + pad * d * 0.8
    return [max(0, x0), max(0, y0), min(1, x1) - max(0, x0), min(1, y1) - max(0, y0)]


def crop(frame, box, min_px=32):
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    x0, y0 = int(max(0, x * w)), int(max(0, y * h))
    x1, y1 = int(min(w, (x + bw) * w)), int(min(h, (y + bh) * h))
    if x1 - x0 < min_px or y1 - y0 < min_px:
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        x0, x1 = max(0, cx - min_px // 2), min(w, cx + min_px // 2)
        y0, y1 = max(0, cy - min_px // 2), min(h, cy + min_px // 2)
    return frame[y0:y1, x0:x1]


# ------------------------------------------------------------------------------------------------ motion and colour
def gray_small(frame, width=192):
    h, w = frame.shape[:2]
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return cv2.resize(g, (width, max(2, round(h * width / w))), interpolation=cv2.INTER_AREA).astype(np.float32)


_win = {}


def shift(a, b):
    """Global displacement from small gray frame a to b, as fractions of the frame width/height, and its confidence."""
    key = a.shape
    if key not in _win:
        _win[key] = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(a, b, _win[key])
    return dx / a.shape[1], dy / a.shape[0], float(resp)


def diff(a, b):
    """Mean absolute difference of two small gray frames, 0-1."""
    return float(np.mean(np.abs(a - b)) / 255.0)


def colour(frame):
    """Brightness, saturation, warmth (b* of Lab), contrast: rough look of a frame, each 0-1 except warmth (-1..1)."""
    small = cv2.resize(frame, (160, max(2, round(frame.shape[0] * 160 / frame.shape[1]))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    return {"brightness": round(float(hsv[..., 2].mean() / 255), 3), "saturation": round(float(hsv[..., 1].mean() / 255), 3),
            "warmth": round(float((lab[..., 2].mean() - 128) / 64), 3), "tint": round(float((lab[..., 1].mean() - 128) / 64), 3),
            "contrast": round(float(lab[..., 0].std() / 128), 3)}


def hist(frame):
    small = cv2.resize(frame, (96, max(2, round(frame.shape[0] * 96 / frame.shape[1]))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def sharpness(frame):
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def screen_colour(frame):
    """If the frame's border is mostly one saturated green or blue (a chroma-key screen), its colour as #RRGGBB."""
    h, w = frame.shape[:2]
    b = max(2, min(h, w) // 12)
    border = np.concatenate([frame[:b].reshape(-1, 3), frame[-b:].reshape(-1, 3), frame[:, :b].reshape(-1, 3), frame[:, -b:].reshape(-1, 3)])
    hsv = cv2.cvtColor(border.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    for name, lo, hi in (("green", 35, 85), ("blue", 95, 130)):
        m = (hsv[:, 0] >= lo) & (hsv[:, 0] <= hi) & (hsv[:, 1] > 90) & (hsv[:, 2] > 60)
        if m.mean() > 0.6:
            c = np.median(border[m], axis=0).astype(int)  # BGR
            return name, f"#{c[2]:02X}{c[1]:02X}{c[0]:02X}"
    return None


# ------------------------------------------------------------------------------------------------ images for the model
def jpeg(frame, width=None, quality=85):
    if width and frame.shape[1] != width:
        frame = cv2.resize(frame, (width, max(2, round(frame.shape[0] * width / frame.shape[1]))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


def _font(size):
    for f in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def sheet(frames, labels, cols=4, cell_w=384):
    """Contact sheet: frames in a grid, each with its label (e.g. '#3 12.5s') in a corner. Returns JPEG bytes."""
    cells = []
    for f in frames:
        h = round(f.shape[0] * cell_w / f.shape[1])
        cells.append(Image.fromarray(cv2.cvtColor(cv2.resize(f, (cell_w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)))
    cell_h = max(c.height for c in cells)
    rows = (len(cells) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell_w + (cols - 1) * 4, rows * cell_h + (rows - 1) * 4), (255, 255, 255))
    draw, font = ImageDraw.Draw(canvas), _font(max(14, cell_w // 16))
    for i, (c, lab) in enumerate(zip(cells, labels)):
        x, y = (i % cols) * (cell_w + 4), (i // cols) * (cell_h + 4)
        canvas.paste(c, (x, y))
        tw = draw.textlength(lab, font=font)
        draw.rectangle([x, y, x + tw + 10, y + font.size + 8], fill=(0, 0, 0))
        draw.text((x + 5, y + 3), lab, fill=(255, 255, 0), font=font)
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def side_by_side(a, b, labels=("A", "B"), height=360):
    """Two frames next to each other (each labelled), as JPEG bytes: before/after comparisons for the model."""
    out = []
    for f in (a, b):
        w = round(f.shape[1] * height / f.shape[0])
        out.append(cv2.resize(f, (w, height), interpolation=cv2.INTER_AREA))
    return sheet(out, list(labels), cols=2, cell_w=max(o.shape[1] for o in out))


def load_jpeg(data):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def save_jpeg(frame, path, width=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(jpeg(frame, width))
    return path
