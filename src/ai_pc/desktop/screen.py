"""Fast screen capture (mss) and cheap change detection."""

import threading

import mss
import numpy as np
from PIL import Image

_local = threading.local()


def _sct():
    s = getattr(_local, "sct", None)
    if s is None:
        s = _local.sct = mss.mss()
    return s


def grab(region=None):
    """Capture the primary monitor, or region=(left, top, right, bottom) in screen pixels, as an RGB image."""
    sct = _sct()
    if region:
        l, t, r, b = region
        mon = {"left": int(l), "top": int(t), "width": max(1, int(r - l)), "height": max(1, int(b - t))}
    else:
        mon = sct.monitors[1]
    shot = sct.grab(mon)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def signature(img):
    """160x90 grayscale thumbnail used to detect that something on screen changed."""
    return np.asarray(img.convert("L").resize((160, 90))).astype(np.int16)


def changed(a, b, level=10, min_pixels=8):
    """True if at least `min_pixels` thumbnail pixels changed noticeably: catches a short word typed into a small
    field (a mean-difference test misses it), while a blinking caret or anti-aliasing noise does not trigger it."""
    return int(np.count_nonzero(np.abs(a - b) > level)) >= min_pixels


def changed_frac(a, b, level=10):
    """Share of thumbnail pixels that changed noticeably (a loading screen giving way to the real UI is a big share;
    a progress bar or a blinking caret is a tiny one)."""
    return float(np.count_nonzero(np.abs(a - b) > level)) / a.size


def diff(a, b):
    """Mean absolute difference between two signatures, 0..1."""
    return float(np.abs(a - b).mean()) / 255.0


def thumb_jpeg(img, width=1280, quality=80):
    import io

    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
