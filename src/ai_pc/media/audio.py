"""Audio analysis with numpy only (no extra packages): loudness envelope, strong hits (onsets), tempo and beat grid,
the biggest energy rise ("drop"), quiet ranges and a rough speech / music guess. ~0.1-0.3 s for a minute of audio.
Used to cut on beats, place impacts on hits, duck music under speech and check audio edits after export.
"""
import subprocess

import numpy as np

SR = 22050
HOP = 512                  # 23 ms per analysis frame
N_FFT = 2048
NO_WINDOW = 0x08000000


def load(path, start=0.0, dur=None, sr=SR):
    """Mono float32 samples of a file's audio (empty if it has none)."""
    args = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}"] + (["-t", f"{dur:.3f}"] if dur else []) + \
           ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
    return np.frombuffer(r.stdout, np.float32)


def _frames(y, n, hop):
    if len(y) < n:
        y = np.pad(y, (0, n - len(y)))
    count = 1 + (len(y) - n) // hop
    return np.lib.stride_tricks.as_strided(y, (count, n), (y.strides[0] * hop, y.strides[0]), writeable=False)


def _db(x):
    return 20 * np.log10(np.maximum(x, 1e-6))


def envelope(y, hop=HOP):
    """RMS level per analysis frame, in dBFS."""
    return _db(np.sqrt(np.mean(_frames(y, N_FFT, hop) ** 2, axis=1)))


def onset_strength(y):
    """Spectral flux of the log spectrum: high where something new starts (a hit, a note, a cut in the sound)."""
    fr = _frames(y, N_FFT, HOP) * np.hanning(N_FFT).astype(np.float32)
    mag = np.log1p(100 * np.abs(np.fft.rfft(fr, axis=1)))
    flux = np.maximum(0, np.diff(mag, axis=0)).mean(axis=1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(9) / 9, mode="same")  # remove slow trends
    return np.maximum(flux, 0)


def peaks(env, fps, min_gap=0.12, k=1.5):
    """Local maxima of an onset envelope that stand out from their neighbourhood. [(time, strength 0-1)]."""
    w = max(1, int(0.07 * fps))
    n = len(env)
    out = []
    win = int(1.5 * fps)
    for i in range(1, n - 1):
        lo, hi = max(0, i - w), min(n, i + w + 1)
        if env[i] < env[lo:hi].max() or env[i] <= 0:
            continue
        a, b = max(0, i - win), min(n, i + win)
        if env[i] > env[a:b].mean() + k * env[a:b].std():
            if out and (i - out[-1][0]) / fps < min_gap:
                if env[i] > env[out[-1][0]]:
                    out[-1] = (i, env[i])
                continue
            out.append((i, env[i]))
    top = max((v for _, v in out), default=1) or 1
    return [(i / fps, float(v / top)) for i, v in out]


def tempo(env, fps, lo_bpm=60, hi_bpm=190):
    """(bpm, confidence 0-1, phase offset in s) from the autocorrelation of the onset envelope."""
    x = env - env.mean()
    if len(x) < fps * 4 or not x.any():
        return 0.0, 0.0, 0.0
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    ac /= ac[0] + 1e-9
    lags = np.arange(int(fps * 60 / hi_bpm), min(len(ac) - 1, int(fps * 60 / lo_bpm)) + 1)
    if not len(lags):
        return 0.0, 0.0, 0.0
    bpms = 60 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpms / 120) / 0.9) ** 2)  # favour 80-180 BPM like most music
    best = lags[np.argmax(ac[lags] * prior)]
    conf = float(max(0.0, ac[best]))
    period = best
    phases = [env[p::period].sum() for p in range(period)]
    return float(60 * fps / period), round(conf, 3), float(np.argmax(phases) / fps)


def analyze(path, seconds=None):
    """Everything the planner and the verifier need to know about a file's sound. None when there is none."""
    y = load(path)
    if len(y) < SR * 0.3:
        return None
    fps = SR / HOP
    dur = len(y) / SR
    rms = envelope(y)
    env = onset_strength(y)
    hits = peaks(env, fps)
    bpm, conf, phase = tempo(env, fps)
    beats = []
    if bpm and conf > 0.12:
        step = 60 / bpm
        t = phase
        while t < dur:
            # snap each grid beat to the strongest onset within +-8% of a beat
            i0, i1 = int(max(0, t - 0.08 * step) * fps), int(min(dur, t + 0.08 * step) * fps) + 1
            j = i0 + int(np.argmax(env[i0:i1])) if i1 > i0 else int(t * fps)
            beats.append(round(j / fps, 3))
            t += step
    # loudness per second and the biggest sustained rise (a "drop" or the moment things kick in)
    per_s = [float(np.mean(rms[int(i * fps):int((i + 1) * fps)])) for i in range(int(np.ceil(dur)))]
    smooth = np.convolve(per_s, np.ones(2) / 2, mode="same") if len(per_s) > 2 else np.array(per_s)
    rise = np.diff(smooth) if len(smooth) > 1 else np.array([0.0])
    drop = float(np.argmax(rise) + 1) if len(rise) and rise.max() > 6 else None
    # quiet ranges (pauses): 0.5 s or longer, 30 dB under the loud parts
    loud = float(np.percentile(rms, 95))
    quiet_mask = rms < max(-55, loud - 30)
    quiet, start = [], None
    for i, q in enumerate(np.append(quiet_mask, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) / fps >= 0.5:
                quiet.append([round(start / fps, 2), round(i / fps, 2)])
            start = None
    # speech vs music (rough): speech has a 2-8 Hz syllable rhythm with pauses and no steady beat
    lin = 10 ** (rms / 20)
    lin = lin - lin.mean()
    spec = np.abs(np.fft.rfft(lin * np.hanning(len(lin)))) if len(lin) > 16 else np.zeros(2)
    freqs = np.fft.rfftfreq(len(lin), 1 / fps) if len(lin) > 16 else np.zeros(2)
    syll = float(spec[(freqs > 2) & (freqs < 8)].sum() / (spec[(freqs > 0.2) & (freqs < 20)].sum() + 1e-9))
    pause_frac = float(quiet_mask.mean())
    if conf > 0.3 and pause_frac < 0.1:
        kind = "music"
    elif syll > 0.4 and (pause_frac > 0.04 or conf < 0.2):
        kind = "speech"
    elif loud < -45:
        kind = "silent"
    else:
        kind = "mixed/ambient"
    top = sorted(hits, key=lambda h: -h[1])[:24]
    return {"seconds": round(dur, 2), "loudness_db": round(float(np.mean(rms[rms > loud - 40])) if (rms > loud - 40).any() else loud, 1),
            "peak_db": round(float(_db(np.abs(y).max())), 1), "kind": kind, "syllabic": round(syll, 2),
            "bpm": round(bpm, 1) if beats else None, "beat_confidence": conf, "beats": beats[:400],
            "hits": [{"t": round(t, 2), "strength": round(s, 2)} for t, s in sorted(top)],
            "drop": drop, "quiet": quiet[:40], "energy_db": [round(v, 1) for v in per_s]}


def window_level(path, t0, t1):
    """Mean and max level (dBFS) of [t0, t1]: for checking music, ducking and fades after export."""
    y = load(path, t0, max(0.05, t1 - t0))
    if not len(y):
        return None
    rms = envelope(y, hop=256)
    return {"mean_db": round(float(np.mean(rms)), 1), "max_db": round(float(np.max(rms)), 1),
            "start_db": round(float(np.mean(rms[:max(1, len(rms) // 5)])), 1), "end_db": round(float(np.mean(rms[-max(1, len(rms) // 5):])), 1)}
