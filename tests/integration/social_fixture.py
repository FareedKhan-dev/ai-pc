"""Test media for the social lane, made with FFmpeg and Pillow: shapes and lengths every platform has rules about."""
import subprocess
from pathlib import Path

NO_WINDOW = 0x08000000


def _ff(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])


def make(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}

    def video(name, w, h, secs, fps=30, extra=()):
        p = folder / name
        if not p.exists():
            _ff(["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                 "-t", str(secs), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", *extra, str(p)])
        out[name] = str(p)
    video("landscape.mp4", 1920, 1080, 12)
    video("vertical.mp4", 1080, 1920, 8)
    video("tiny.mp4", 1080, 1920, 2)
    video("long.mp4", 320, 180, 16 * 60, fps=2, extra=("-crf", "40"))
    from PIL import Image, ImageDraw
    pics = {"panorama.jpg": (3000, 1000), "tall.jpg": (1000, 2500), "square.jpg": (1200, 1200), "wide.jpg": (2400, 1260)}
    for name, (w, h) in pics.items():
        p = folder / name
        if not p.exists():
            im = Image.new("RGB", (w, h), (30, 90, 160))
            d = ImageDraw.Draw(im)
            for i in range(0, w, 120):
                d.rectangle([i, h // 3, i + 60, 2 * h // 3], fill=(240, 200 - (i // 20) % 120, 60))
            d.ellipse([w // 2 - h // 6, h // 2 - h // 6, w // 2 + h // 6, h // 2 + h // 6], fill=(250, 250, 250))  # the subject, in the middle
            im.save(p, quality=92)
        out[name] = str(p)
    p = folder / "logo.png"
    if not p.exists():
        im = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([100, 100, 700, 700], fill=(220, 40, 40, 255))
        im.save(p)
    out["logo.png"] = str(p)
    p = folder / "gps.jpg"
    if not p.exists():  # a phone photo with its location in it
        im = Image.new("RGB", (1600, 1200), (120, 160, 90))
        exif = Image.Exif()
        exif[0x0110] = "Pixel 9"  # camera model
        gps = {1: "N", 2: (31.0, 31.0, 12.0), 3: "E", 4: (74.0, 21.0, 36.0)}  # Lahore
        exif[0x8825] = gps
        im.save(p, exif=exif, quality=90)
    out["gps.jpg"] = str(p)
    return out
