"""Music beds, generated (numpy only): when the user gives no music, an edit still gets a rhythm to cut to.

  bed(style, seconds, bpm=None, drop_at=None) -> (wav path, grid)

Styles: hype (trap drums, 808, plucks), phonk (cowbell melody, 808), epic (trailer drums, braams, strings), pop
(four-on-the-floor, offbeat bass, plucks), chill (lo-fi drums, keys), cinematic (pads, soft pulses). Every bed has
an intro, a build with a snare roll and a riser, a DROP at `drop_at` (the edit's climax), and an outro; the grid
returned is exact (beats, downbeats, sections, drop), so cuts and effects land on the music frame-accurately.
Files: media/derived/music_<style>_<bpm>_<seconds>_<drop>.wav (made once).
"""

import json
import math
import wave

import numpy as np

from ai_pc.core.config import ROOT

SR = 44100
OUT = ROOT / "media" / "derived"
STYLES = {
    "hype": {"bpm": 140, "drums": "trap", "bass": "808", "lead": "pluck", "pad": "dark"},
    "phonk": {"bpm": 135, "drums": "phonk", "bass": "808", "lead": "cowbell", "pad": None},
    "epic": {"bpm": 100, "drums": "trailer", "bass": "braam", "lead": None, "pad": "strings"},
    "pop": {"bpm": 118, "drums": "four", "bass": "offbeat", "lead": "pluck", "pad": "bright"},
    "chill": {"bpm": 86, "drums": "lofi", "bass": "soft", "lead": "keys", "pad": "warm"},
    "cinematic": {"bpm": 84, "drums": "pulse", "bass": "soft", "lead": None, "pad": "strings"},
}
ALIASES = {
    "trap": "hype",
    "boss": "hype",
    "velocity": "hype",
    "drill": "hype",
    "trailer": "epic",
    "lofi": "chill",
    "lo-fi": "chill",
    "upbeat": "pop",
    "dance": "pop",
    "travel": "pop",
    "ambient": "cinematic",
    "emotional": "cinematic",
    "aesthetic": "chill",
}
MINOR = [0, 2, 3, 5, 7, 8, 10]
PROG = [(0, "m"), (5, "M"), (2, "M"), (6, "M")]  # i - VI - III - VII  (scale degrees)


def _t(sec):
    return np.arange(int(sec * SR)) / SR


def _lp_kernel(fc, taps=129):
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * fc / SR * n) * np.blackman(taps)
    return h / h.sum()


def _lp(x, fc, taps=129):
    return np.convolve(x, _lp_kernel(min(fc, SR / 2 - 100), taps), mode="same")


def _hp(x, fc, taps=129):
    return x - _lp(x, fc, taps)


def _env(n, a=0.002, d=0.2, sus=0.0, rel=None):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * (sus + (1 - sus) * np.exp(-t / d))
    if rel:
        k = int(rel * SR)
        if 0 < k < n:
            e[-k:] *= np.linspace(1, 0, k)
    return e


def _hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _saw(f, sec, detune=0.0):
    t = _t(sec)
    return 2 * ((t * f * (1 + detune)) % 1.0) - 1


# ------------------------------------------------------------------------------------------------ instruments
def kick(rng, punch=1.0):
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.28)
    click = _hp(rng.standard_normal(n), 3000) * np.exp(-t / 0.004) * 0.3
    return np.tanh(1.8 * punch * (body + click))


def snare(rng):
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    noise = _hp(rng.standard_normal(n), 1500) * np.exp(-t / 0.09)
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.05)
    return 0.7 * noise + 0.5 * tone


def clap(rng):
    n = int(0.35 * SR)
    x = np.zeros(n)
    for k, off in enumerate((0, 0.011, 0.022)):
        s = int(off * SR)
        m = n - s
        x[s:] += _hp(rng.standard_normal(m), 900) * np.exp(-np.arange(m) / SR / (0.012 if k < 2 else 0.12))
    return x * 0.8


def hat(rng, open_=False):
    n = int((0.25 if open_ else 0.06) * SR)
    t = np.arange(n) / SR
    return _hp(rng.standard_normal(n), 7000) * np.exp(-t / (0.09 if open_ else 0.018)) * 0.35


def cowbell(midi):
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    f = _hz(midi)
    x = np.sign(np.sin(2 * np.pi * f * t)) + np.sign(np.sin(2 * np.pi * f * 1.48 * t))
    return _lp(x, 3500) * np.exp(-t / 0.09) * 0.25


def bass808(midi, sec):
    n = int(sec * SR)
    t = np.arange(n) / SR
    f = _hz(midi) * (1 + 1.0 * np.exp(-t / 0.03))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.003, 0.9, 0.35, rel=0.05)
    return np.tanh(1.6 * x) * 0.9


def pluck(midi, sec, bright=1.0):
    n = int(sec * SR)
    x = _saw(_hz(midi), sec) + 0.5 * _saw(_hz(midi), sec, 0.004)
    x = _lp(x, 2200 * bright) * _env(n, 0.002, 0.16)
    return x * 0.22


def keys(midi, sec):
    t = _t(sec)
    f = _hz(midi)
    x = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    return x * _env(len(t), 0.005, 0.6, 0.15, rel=0.1) * 0.12


def pad(notes, sec, colour="dark"):
    cut = {"dark": 900, "warm": 1300, "bright": 2600, "strings": 1800}.get(colour, 1500)
    x = sum(_saw(_hz(m), sec, d) for m in notes for d in (-0.003, 0.0, 0.004))
    x = _lp(x, cut, 255) / (3 * len(notes))
    n = len(x)
    return x * _env(n, 0.35, 99, 1.0, rel=0.4) * (0.5 if colour == "strings" else 0.35)


def braam(midi, sec):
    n = int(sec * SR)
    x = _saw(_hz(midi), sec) + _saw(_hz(midi - 12), sec, 0.002) + 0.6 * np.sin(2 * np.pi * _hz(midi - 24) * _t(sec))
    return np.tanh(2.2 * _lp(x, 700, 255)) * _env(n, 0.04, 1.4, 0.2, rel=0.3) * 0.5


def riser(rng, sec):
    t = _t(sec)
    grow = (t / sec) ** 2
    noise = _hp(rng.standard_normal(len(t)), 600) * grow
    f = 300 + 2500 * grow
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * grow * 0.3
    return (0.5 * noise + tone) * 0.5


def impact(rng):
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    f = 34 + 70 * np.exp(-t / 0.15)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.55)
    crack = _hp(rng.standard_normal(n), 2000) * np.exp(-t / 0.03)
    return np.tanh(2 * boom + 0.6 * crack) * 0.9


# ------------------------------------------------------------------------------------------------ arrangement
def _put(buf, x, at, gain=1.0, pan=0.0):
    i = int(at * SR)
    if i >= buf.shape[0] or i < 0:
        return
    m = min(len(x), buf.shape[0] - i)
    buf[i : i + m, 0] += x[:m] * gain * math.sqrt(0.5 * (1 - pan))
    buf[i : i + m, 1] += x[:m] * gain * math.sqrt(0.5 * (1 + pan))


def _reverb(x, rng, sec=1.4, mix=0.25):
    n = int(sec * SR)
    ir = rng.standard_normal((n, 2)) * np.exp(-np.arange(n) / SR / (sec / 5))[:, None]
    ir[:, 0] = _lp(ir[:, 0], 6000)
    ir[:, 1] = _lp(ir[:, 1], 6000)
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    out = np.empty_like(x)
    for c in range(2):
        y = np.fft.irfft(np.fft.rfft(x[:, c], size) * np.fft.rfft(ir[:, c], size), size)[: len(x)]
        out[:, c] = y / (np.abs(ir[:, c]).sum() ** 0.5 + 1e-9)
    return x * (1 - mix) + out * mix * 0.5


ENERGY = {"intro": 0.3, "verse": 0.6, "build": 0.7, "drop": 1.0, "break": 0.35, "bridge": 0.45, "outro": 0.3}


def classic_sections(seconds, drop_at, bar):
    """intro - build - drop - outro around one drop (short edits)."""
    build_from = max(0.0, drop_at - bar)
    end_full = seconds - bar if seconds - drop_at > 2 * bar else seconds
    out = [
        {"name": "intro", "start": 0.0, "end": build_from},
        {"name": "build", "start": build_from, "end": drop_at},
        {"name": "drop", "start": drop_at, "end": end_full},
        {"name": "outro", "start": end_full, "end": seconds},
    ]
    return [x for x in out if x["end"] - x["start"] > 0.05]


def bed(style="hype", seconds=15.0, bpm=None, drop_at=None, seed=3, sections=None):
    """(path of the wav, grid). `sections` = the edit's own sections [{"name", "start", "end"}] (intro, verse, build, drop,
    break, bridge, outro): the music follows them, a build rises into every drop and every drop starts with an impact.
    Without sections: one drop at `drop_at` (intro - build - drop - outro)."""
    style = ALIASES.get(str(style).lower(), str(style).lower())
    if style not in STYLES:
        style = "hype"
    cfg = STYLES[style]
    bpm = int(bpm or cfg["bpm"])
    beat = 60.0 / bpm
    bar = 4 * beat
    seconds = float(seconds)
    if sections:
        secs = [{"name": s["name"] if s["name"] in ENERGY else "verse", "start": float(s["start"]), "end": float(s["end"])} for s in sections]
        secs[-1]["end"] = max(secs[-1]["end"], seconds)
    else:
        if drop_at is None:
            drop_at = min(seconds * 0.35, 4 * bar)
        drop_at = max(bar, round(drop_at / bar) * bar)  # the drop lands on a bar
        secs = classic_sections(seconds, drop_at, bar)
    drops = [s["start"] for s in secs if s["name"] == "drop"]
    sig = "_".join(f"{s['name'][0]}{s['start']:.2f}" for s in secs)
    tag = f"{style}_{bpm}_{seconds:.1f}_{abs(hash(sig)) % 10**8}_{seed}"
    path = OUT / f"music_{tag}.wav"
    grid_path = OUT / f"music_{tag}.json"
    if path.exists() and grid_path.exists():
        return path, json.loads(grid_path.read_text(encoding="utf-8"))
    rng = np.random.default_rng(seed)
    root = 45 + int(rng.integers(0, 7))  # A2..E3 roots
    total = seconds + 2.0
    dry = np.zeros((int(total * SR), 2))
    wet = np.zeros_like(dry)
    k, s, c, h, oh = kick(rng), snare(rng), clap(rng), hat(rng), hat(rng, True)
    n_beats = int(np.ceil(seconds / beat)) + 1

    def section_at(t):
        for x in secs:
            if x["start"] - 1e-6 <= t < x["end"]:
                return x
        return secs[-1]

    for i in range(n_beats):
        t = i * beat
        if t >= seconds:
            break
        sx = section_at(t)
        name = sx["name"]
        bar_i, pos = divmod(i, 4)
        chord_root, quality = PROG[(int(t // bar)) % len(PROG)]
        note = root + MINOR[chord_root]
        third = note + (3 if quality == "m" else 4)
        fifth = note + 7
        arp = [note + 12, third + 12, fifth + 12, third + 24]
        nxt_drop = next((d for d in drops if d > t), None)
        gap = nxt_drop is not None and nxt_drop - beat / 4 <= t + 1e-6 < nxt_drop  # a breath right before a drop
        if pos == 0 and cfg["pad"] and not gap:
            _put(wet, pad([note + 12, third + 12, fifth + 12], bar, cfg["pad"]), t, 0.6 if name == "drop" else 0.85)
        if name in ("intro", "outro"):
            if cfg["drums"] in ("trap", "phonk", "four", "lofi") and pos == 0:
                _put(dry, k, t, 0.55)
            if cfg["drums"] in ("trap", "four", "lofi"):
                _put(dry, h, t + beat / 2, 0.45)
            if cfg["drums"] == "pulse":
                _put(dry, k * 0.5, t, 0.5)
            continue
        if name in ("break", "bridge"):  # drums out, melody carries
            if cfg["lead"] in ("pluck", "keys") and pos in (0, 2):
                _put(wet, keys(arp[(i // 2) % 4], beat * 2) * 1.6, t, 0.9)
            elif cfg["lead"] == "cowbell" and pos == 0:
                _put(dry, cowbell(note + 24), t, 0.5)
            if name == "bridge" and pos == 0:
                _put(dry, k, t, 0.45)
            continue
        if name == "build":
            # snare roll that speeds up over the section, kick on the bar
            span = max(beat, sx["end"] - sx["start"])
            prog = (t - sx["start"]) / span
            div = 1 if prog < 0.5 else 2 if prog < 0.8 else 4
            for j in range(div):
                tt = t + j * beat / div
                if tt < sx["end"] - beat / 4:
                    _put(dry, s, tt, 0.2 + 0.65 * prog)
            if pos == 0:
                _put(dry, k, t, 0.7)
            continue
        # ---- verse (lighter) and drop (full)
        full = name == "drop"
        d = cfg["drums"]
        if d == "trap":
            if pos == 0 or (full and pos == 2 and bar_i % 2 == 1):
                _put(dry, k, t, 1.0 if full else 0.8)
            if pos in (1, 3):
                _put(dry, c, t, 0.8 if full else 0.55)
            for j in range(2 if (pos % 2 == 0 or not full) else 4):
                _put(dry, h, t + j * beat / (2 if (pos % 2 == 0 or not full) else 4), 0.45 if full else 0.35, pan=0.2)
        elif d == "phonk":
            if pos in (0, 2):
                _put(dry, k, t, 1.0 if full else 0.75)
            if pos in (1, 3):
                _put(dry, s, t, 0.7 if full else 0.45)
            for j in range(4 if full else 2):
                _put(dry, h, t + j * beat / (4 if full else 2), 0.3, pan=-0.2)
        elif d == "four":
            _put(dry, k, t, 1.0 if full else 0.75)
            if pos in (1, 3) and full:
                _put(dry, c, t, 0.7)
            _put(dry, oh, t + beat / 2, 0.35 if full else 0.25, pan=0.25)
        elif d == "lofi":
            if pos == 0 or (pos == 2 and bar_i % 2):
                _put(dry, k, t, 0.7)
            if pos in (1, 3):
                _put(dry, s, t + 0.012, 0.45 if full else 0.3)
            _put(dry, h, t + beat * 0.58, 0.3)
        elif d == "trailer":
            if pos in (0, 2):
                _put(dry, k, t, 1.0 if full else 0.7)
                if full:
                    _put(dry, k, t + beat * 0.75, 0.6)
            if pos == 3 and full:
                _put(dry, s, t, 0.8)
        elif d == "pulse":
            _put(dry, k * 0.6, t, 0.6 if full else 0.4)
        b = cfg["bass"]
        if b == "808" and pos in ((0, 2) if full else (0,)):
            _put(dry, bass808(note - 12, beat * (1.9 if full else 3.8)), t, 0.9 if full else 0.7)
        elif b == "offbeat":
            _put(dry, pluck(note - 12, beat / 2, 0.6) * 3, t + beat / 2, 0.8 if full else 0.55)
        elif b == "braam" and pos == 0 and full:
            _put(dry, braam(note, bar * 0.95), t, 0.9)
        elif b == "soft" and pos == 0:
            _put(dry, keys(note - 12, bar) * 2.5, t, 0.8)
        ld = cfg["lead"]
        if not full:
            continue  # the verse keeps the lead for the drops
        if ld == "pluck":
            for j in range(2):
                _put(wet, pluck(arp[(i * 2 + j) % 4] + 12, beat / 2), t + j * beat / 2, 0.8, pan=0.15 * (-1) ** j)
        elif ld == "cowbell":
            pattern = [0, 0, 3, 0, 5, 3, 0, 7]
            for j in range(2):
                _put(dry, cowbell(note + 24 + pattern[(i * 2 + j) % 8]), t + j * beat / 2, 0.8)
        elif ld == "keys" and pos in (0, 2):
            for m in (note + 12, third + 12, fifth + 12):
                _put(wet, keys(m, beat * 2), t + 0.01 * (m % 3), 1.0)
    for d0 in drops:  # a riser into every drop, an impact on it
        rs = min(bar, d0)
        if rs > beat:
            _put(wet, riser(rng, rs), d0 - rs, 0.7)
        _put(dry, impact(rng), d0, 0.9)
    if secs[-1]["name"] == "outro" and secs[-1]["start"] > 1:
        _put(dry, impact(rng) * 0.6, secs[-1]["start"], 0.6)
    mix = dry + _reverb(wet, rng, 1.6, 0.35)
    mix = mix[: int(seconds * SR)]
    fade = int(min(1.5, seconds * 0.06) * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None]
    mix = np.tanh(1.3 * mix / (np.percentile(np.abs(mix), 99.5) + 1e-9)) * 0.9  # soft limiter, ~ -1 dBFS peaks
    OUT.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    beats = [round(i * beat, 4) for i in range(int(seconds / beat) + 1) if i * beat < seconds]
    grid = {
        "source": "generated",
        "style": style,
        "bpm": bpm,
        "beat": round(beat, 5),
        "beats": beats,
        "downbeats": beats[::4],
        "drop": round(drops[0], 4) if drops else None,
        "drops": [round(d, 4) for d in drops],
        "seconds": seconds,
        "sections": [{"name": x["name"], "start": round(x["start"], 4), "end": round(x["end"], 4)} for x in secs],
    }
    grid_path.write_text(json.dumps(grid), encoding="utf-8")
    return path, grid
