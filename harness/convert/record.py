"""The screen recorded by FFmpeg in the background (Windows Desktop Duplication; encoded on the Intel GPU when it can,
else on the processor): one screen, 30 fps, the mouse pointer drawn as it is, the microphone when asked. Nothing is
clicked or moved. A recording runs for a set time or until it is stopped; it is written as MKV (safe even if FFmpeg is
cut off) and turned into an MP4 at the end, then checked.

  r = start(folder, seconds=None, mic=False, screen=1)   -> {"pid", "mkv", "started", ...}  (kept in the chat's state)
  path = stop(r)                                        -> the finished MP4
  mics()                                                -> microphone names (DirectShow)
"""
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from . import media as MD

NO_WINDOW = 0x08000000
_PROCS = {}  # pid -> Popen, for recordings started by this process (stopped cleanly with 'q')


class RecordError(RuntimeError):
    pass


def mics():
    _, _, err = MD.run(["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], timeout=30)
    return re.findall(r'"([^"]+)"\s*\(audio\)', err)


def start(folder, seconds=None, mic=False, screen=1, fps=30, gpu=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    mkv = folder / f"recording_{time.strftime('%Y%m%d_%H%M%S')}.mkv"
    grab = f"ddagrab=output_idx={max(0, int(screen) - 1)}:framerate={int(fps)}:draw_mouse=1"
    args = ["ffmpeg", "-hide_banner", "-y", "-v", "error"]
    mic_name = None
    if mic:
        names = mics()
        mic_name = next((n for n in names if re.search(r"microphone|mic", n, re.I)), names[0] if names else None)
        if mic_name:
            args += ["-f", "dshow", "-i", f"audio={mic_name}"]
    vf = f"{grab},hwmap=derive_device=qsv,format=qsv" if gpu else f"{grab},hwdownload,format=bgra"
    args += ["-filter_complex", f"{vf}[v]", "-map", "[v]"] + (["-map", "0:a"] if mic_name else [])
    args += (["-c:v", "h264_qsv", "-global_quality", "25", "-look_ahead", "0"] if gpu else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                                                                              "-pix_fmt", "yuv420p"])
    args += (["-c:a", "aac", "-b:a", "128k"] if mic_name else []) + ["-t", str(int(seconds) if seconds else 4 * 3600), str(mkv)]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    time.sleep(1.5)
    if p.poll() is not None:  # FFmpeg stopped at once: try the processor's encoder before giving up
        err = p.stderr.read().decode("utf-8", "replace")[-300:]
        if gpu:
            return start(folder, seconds, mic, screen, fps, gpu=False)
        raise RecordError(f"the screen could not be recorded: {err.strip() or 'no reason given'}")
    _PROCS[p.pid] = p
    return {"pid": p.pid, "mkv": str(mkv), "started": time.time(), "seconds": seconds, "mic": mic_name, "screen": int(screen), "gpu": gpu}


def running(rec):
    p = _PROCS.get(rec.get("pid"))
    if p is not None:
        return p.poll() is None
    try:  # started by another run of the program: is the process still there?
        out = subprocess.run(["tasklist", "/FI", f"PID eq {rec['pid']}", "/NH"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
        return "ffmpeg" in out.lower()
    except OSError:
        return False


def stop(rec, wait=True):
    """End a recording ('q' to FFmpeg; the process ended outright if it was started by another run) and give back the
    finished MP4, checked."""
    p = _PROCS.pop(rec.get("pid"), None)
    if p is not None:
        if p.poll() is None:
            try:
                p.stdin.write(b"q")
                p.stdin.flush()
            except OSError:
                pass
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
    elif running(rec):
        try:
            os.kill(int(rec["pid"]), signal.SIGTERM)
        except OSError:
            pass
        time.sleep(1.0)
    mkv = Path(rec["mkv"])
    if not mkv.exists() or mkv.stat().st_size < 1000:
        raise RecordError("nothing was recorded")
    mp4 = mkv.with_suffix(".mp4")
    code, _, err = MD.run(["ffmpeg", "-hide_banner", "-y", "-v", "error", "-i", str(mkv), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(mp4)],
                          timeout=600)
    if code or not mp4.exists():
        raise RecordError(f"the recording could not be finished: {err.strip()[-200:]}")
    p = MD.probe(mp4)
    if p["duration"] < 0.5 or not p.get("video"):
        raise RecordError("the recording is empty")
    mkv.unlink(missing_ok=True)
    return str(mp4)


def wait_for(rec):
    """A timed recording: wait for it to end by itself, then finish it."""
    p = _PROCS.get(rec.get("pid"))
    if p is not None and rec.get("seconds"):
        try:
            p.wait(timeout=float(rec["seconds"]) + 30)
        except subprocess.TimeoutExpired:
            pass
    return stop(rec)
