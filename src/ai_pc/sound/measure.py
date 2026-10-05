"""What a recording is like, measured: loudness and true peak (EBU R128, by FFmpeg), the noise floor and the speech
level, mains hum (50 Hz in Pakistan, 60 Hz elsewhere), rumble, hiss, harsh 's' sounds, clipping, pauses, the pitch of
a voice, and the file's format. numpy only; FFmpeg decodes.

  m = describe(path)   -> {"duration", "lufs", "true_peak", "noise_db", "speech_db", "snr_db", "hum": {"hz", "db"}, ...}
"""
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

NO_WINDOW = 0x08000000
SR = 22050          # analysis rate: enough for hiss and 's' sounds (up to 11 kHz)
FRAME = 0.05        # 50 ms level frames


def run(args, timeout=600):
    """ffmpeg/ffprobe without a console window; (returncode, stdout bytes, stderr text)."""
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW, timeout=timeout)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")


def probe(path):
    """The file's container, length, size and its audio and video streams."""
    code, out, err = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if code:
        raise ValueError(f"cannot read {Path(path).name}: {err.strip()[:200]}")
    d = json.loads(out)
    fmt = d.get("format", {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    fr = (v or {}).get("avg_frame_rate") or (v or {}).get("r_frame_rate") or "0/1"
    num, den = (fr.split("/") + ["1"])[:2]
    return {"duration": float(fmt.get("duration") or (a or {}).get("duration") or 0), "size": int(fmt.get("size") or Path(path).stat().st_size),
            "format": fmt.get("format_name", ""), "bitrate": int(fmt.get("bit_rate") or 0),
            "audio": {"codec": a["codec_name"], "sr": int(a.get("sample_rate") or 0), "channels": int(a.get("channels") or 0),
                      "bitrate": int(a.get("bit_rate") or 0)} if a else None,
            "video": {"codec": v["codec_name"], "w": int(v["width"]), "h": int(v["height"]),
                      "fps": round(float(num) / float(den), 3) if float(den or 0) else 0} if v else None}


def load(path, sr=SR, channels=1, start=0.0, dur=None):
    """Float32 samples, mono by default (shape (n,)) or as (n, channels)."""
    args = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"] + (["-t", f"{dur:.3f}"] if dur else []) + \
        ["-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    code, out, err = run(args)
    y = np.frombuffer(out, np.float32)
    return y.reshape(-1, channels) if channels > 1 else y


def loudness(path):
    """Integrated loudness (LUFS), loudness range (LU) and true peak (dBTP), as FFmpeg's ebur128 measures them."""
    code, _, err = run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"])
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err

    def grab(rx):
        m = re.search(rx, tail)
        return float(m.group(1)) if m else None
    lufs = grab(r"I:\s+(-?[\d.]+|-inf) LUFS")
    return {"lufs": lufs if lufs is not None else -70.0, "lra": grab(r"LRA:\s+(-?[\d.]+) LU"), "true_peak": grab(r"Peak:\s+(-?[\d.]+|-inf) dBFS")}


def frames_db(y, sr=SR, win=FRAME):
    n = max(1, int(sr * win))
    k = len(y) // n
    if k == 0:
        return np.array([-120.0])
    f = y[:k * n].reshape(k, n)
    return 20 * np.log10(np.maximum(np.sqrt((f.astype(np.float64) ** 2).mean(axis=1)), 1e-6))


def psd(y, sr=SR, seg=None):
    """Welch power spectrum (freqs, power) averaged over Hann-windowed segments."""
    seg = seg or min(len(y), sr * 2)
    if len(y) < 256:
        return np.array([0.0]), np.array([1e-12])
    hop = seg // 2
    win = np.hanning(seg)
    starts = range(0, max(1, len(y) - seg + 1), hop)
    acc, cnt = None, 0
    for s in starts:
        x = y[s:s + seg]
        if len(x) < seg:
            break
        p = np.abs(np.fft.rfft(x * win)) ** 2
        acc = p if acc is None else acc + p
        cnt += 1
    return np.fft.rfftfreq(seg, 1 / sr), acc / max(cnt, 1)


def _band_db(freqs, p, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return 10 * math.log10(max(float(p[m].sum()), 1e-20))


def hum(y, sr=SR):
    """Mains hum: how far the 50 Hz (or 60 Hz) series stands above the spectrum around it, in dB."""
    freqs, p = psd(y, sr, seg=min(len(y), sr * 4))  # 0.25 Hz bins
    pdb = 10 * np.log10(np.maximum(p, 1e-20))
    best = {"hz": None, "db": 0.0}
    for f0 in (50, 60):
        proms = []
        for k in (1, 2, 3, 4):
            f = f0 * k
            on = (freqs > f - 1.0) & (freqs < f + 1.0)
            near = ((freqs > f - 12) & (freqs < f - 4)) | ((freqs > f + 4) & (freqs < f + 12))
            if on.any() and near.any():
                proms.append(float(pdb[on].max() - np.median(pdb[near])))
        prom = float(np.mean(sorted(proms, reverse=True)[:2])) if proms else 0.0
        if prom > best["db"]:
            best = {"hz": f0, "db": round(prom, 1)}
    if best["db"] < 10:
        best["hz"] = None
    return best


def pitch(y, sr=SR, db=None):
    """The median pitch of the voiced frames (Hz), by autocorrelation; None when there is no clear voice."""
    db = frames_db(y, sr) if db is None else db
    n = int(sr * FRAME)
    loud = np.where(db > np.percentile(db, 70))[0]
    f0s = []
    for i in loud[:: max(1, len(loud) // 200)]:
        x = y[i * n:(i + 2) * n].astype(np.float64)
        if len(x) < n * 2:
            continue
        x = x - x.mean()
        ac = np.correlate(x, x, "full")[len(x) - 1:]
        lo, hi = int(sr / 400), int(sr / 70)
        if hi >= len(ac) or ac[0] <= 0:
            continue
        j = lo + int(np.argmax(ac[lo:hi]))
        if ac[j] / ac[0] > 0.45:
            f0s.append(sr / j)
    return round(float(np.median(f0s)), 1) if len(f0s) >= 5 else None


def pauses(db, floor, speech, min_len=0.3, win=FRAME):
    """Quiet stretches between sounds: [[start, end], ...] in seconds, each at least min_len long."""
    thr = max(floor + 6, speech - 28)
    quiet = db < thr
    out, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * win >= min_len:
                out.append([round(start * win, 2), round(i * win, 2)])
            start = None
    return out


def clipping(path, native_sr):
    """The share of samples stuck at full scale (runs of 3+), at the file's own rate."""
    y = load(path, sr=native_sr or 44100)
    if not len(y):
        return 0.0
    a = np.abs(y) >= 0.985
    runs = a[:-2] & a[1:-1] & a[2:]
    return round(float(runs.mean()), 5)


def describe(path, deep=True):
    """Everything the agent checks: format, loudness, noise floor, speech level, hum, rumble, hiss, sibilance,
    clipping, pauses and pitch."""
    info = probe(path)
    if not info["audio"]:
        return dict(info, silent=True)
    y = load(path)
    db = frames_db(y)
    floor = float(np.percentile(db, 8))
    speech = float(np.percentile(db, 90))
    out = dict(info, silent=bool(speech < -60))
    out.update(loudness(path))
    out.update(noise_db=round(floor, 1), speech_db=round(speech, 1), snr_db=round(speech - floor, 1),
               peak_db=round(20 * math.log10(max(float(np.abs(y).max()) if len(y) else 0, 1e-6)), 1))
    if not deep:
        return out
    freqs, p = psd(y)
    voice = _band_db(freqs, p, 150, 4000)
    out["rumble_db"] = round(_band_db(freqs, p, 20, 70) - voice, 1)       # low-end energy against the voice band
    n = int(SR * FRAME)
    loud_idx = np.where(db >= np.percentile(db, 75))[0]
    quiet_idx = np.where(db <= np.percentile(db, 15))[0]

    def part(idx):
        if not len(idx):
            return np.zeros(1, np.float32)
        return np.concatenate([y[i * n:(i + 1) * n] for i in idx[:4000]])
    fl, pl = psd(part(loud_idx), seg=2048)
    out["sibilance_db"] = round(_band_db(fl, pl, 5000, 9000) - _band_db(fl, pl, 300, 3000), 1)  # harsh 's' in the loud parts
    out["presence_db"] = round(_band_db(fl, pl, 1000, 4000), 1)
    fq, pq = psd(part(quiet_idx), seg=2048)
    out["hiss_db"] = round(_band_db(fq, pq, 5000, 10000) - _band_db(fl, pl, 300, 3000), 1)       # hiss in the pauses against speech
    out["hum"] = hum(y)
    out["clipped"] = clipping(path, info["audio"]["sr"])
    out["pauses"] = pauses(db, floor, speech)
    out["longest_pause"] = round(max((b - a for a, b in out["pauses"]), default=0.0), 2)
    out["pitch_hz"] = pitch(y, db=db)
    out["telephone_db"] = round(max(_band_db(freqs, p, 20, 250), _band_db(freqs, p, 4000, 11000)) - _band_db(freqs, p, 300, 3400), 1)
    return out


def level_db(path, spans, sr=SR):
    """The mean level (dBFS RMS) of a file inside the given [start, end] spans (for ducking and fades)."""
    y = load(path, sr=sr)
    parts = [y[int(a * sr):int(b * sr)] for a, b in spans if b > a]
    x = np.concatenate(parts) if parts else np.zeros(1, np.float32)
    return round(20 * math.log10(max(float(np.sqrt((x.astype(np.float64) ** 2).mean())) if len(x) else 0, 1e-6)), 1)
