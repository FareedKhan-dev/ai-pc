"""Sound effects, synthesised (numpy only, nothing downloaded): the sound design an editor lays under impacts,
transitions and lightning. Each sound is made once into media/derived/sfx_<kind>.wav (48 kHz stereo) and reused.

  impact    deep boom with a sharp front (a hero landing, a punch-in)        ~1.6 s
  hit       short punchy kick + click (beat accents, text slams)              ~0.5 s
  whoosh    air rushing past, sweeping left to right (fast transitions)      ~0.7 s
  swoosh    a quick short whoosh                                              ~0.35 s
  riser     tension that builds and stops dead (into a climax: it ENDS at the moment)   ~2.0 s
  sub_drop  a falling sub-bass (after a riser, on a big reveal)               ~1.6 s
  thunder   a crack and a long rumble (with lightning)                         ~2.6 s
  glitch    digital stutter blips (glitch transitions / effects)              ~0.6 s
"""

import wave

import numpy as np

from ai_pc.core.config import ROOT

SR = 48000
OUT = ROOT / "media" / "derived"
KINDS = ("impact", "hit", "whoosh", "swoosh", "riser", "sub_drop", "thunder", "glitch")
ENDS_AT_MOMENT = {"riser"}  # placed so that they end on the moment instead of starting there


def _t(sec):
    return np.arange(int(sec * SR)) / SR


def _sweep(f0, f1, sec, curve=3.0):
    """Sine whose pitch glides from f0 to f1 (exponential glide)."""
    t = _t(sec)
    k = np.exp(-curve * t / sec)
    f = f1 + (f0 - f1) * k
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def _lowpass(x, cutoff):
    """One-pole low-pass; cutoff may change over time (array)."""
    cut = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = 1 - np.exp(-2 * np.pi * cut / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):  # a few seconds at 48 kHz: ~0.1 s in Python
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def _env(sec, attack=0.005, decay=0.5):
    t = _t(sec)
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / decay)


def _stereo(x, pan=None, width=0.0, seed=0):
    """Mono -> stereo with an optional pan curve (-1 left .. 1 right) and a little width."""
    pan = np.zeros_like(x) if pan is None else np.broadcast_to(pan, x.shape)
    left, right = x * np.sqrt(0.5 * (1 - pan)), x * np.sqrt(0.5 * (1 + pan))
    if width:
        d = int(0.012 * SR * width)
        right = np.concatenate([np.zeros(d), right[:-d]]) if d else right
    return np.stack([left, right], axis=1)


def synth(kind, seed=7):
    rng = np.random.default_rng(seed)
    if kind == "impact":
        sec = 1.6
        body = np.tanh(2.2 * _sweep(95, 34, sec, 4) * _env(sec, 0.002, 0.55))
        click = rng.standard_normal(len(body)) * _env(sec, 0.0005, 0.012)
        rumble = _lowpass(rng.standard_normal(len(body)), 180) * _env(sec, 0.01, 0.6) * 3
        x = 0.9 * body + 0.35 * click + 0.4 * rumble
        return _stereo(x, width=0.6)
    if kind == "hit":
        sec = 0.5
        x = np.tanh(3 * _sweep(160, 48, sec, 25) * _env(sec, 0.001, 0.13)) + 0.4 * rng.standard_normal(int(sec * SR)) * _env(sec, 0.0003, 0.006)
        return _stereo(x)
    if kind in ("whoosh", "swoosh"):
        sec = 0.7 if kind == "whoosh" else 0.35
        t = _t(sec)
        shape = np.sin(np.pi * t / sec) ** 2
        cut = 300 + 3800 * shape
        x = _lowpass(rng.standard_normal(len(t)), cut) * shape * 3.2
        x -= _lowpass(x, 120)  # no rumble
        return _stereo(x, pan=np.linspace(-0.8, 0.8, len(t)))
    if kind == "riser":
        sec = 2.0
        t = _t(sec)
        grow = (t / sec) ** 2.2
        noise = _lowpass(rng.standard_normal(len(t)), 400 + 6000 * grow) * 2.2
        tone = _sweep(180, 1600, sec, -2.0) * 0.35
        x = (noise + tone) * grow
        x[-int(0.004 * SR) :] *= np.linspace(1, 0, int(0.004 * SR))  # stops dead on the moment
        return _stereo(x, width=0.8)
    if kind == "sub_drop":
        sec = 1.6
        x = np.tanh(1.6 * _sweep(120, 28, sec, 2.0) * _env(sec, 0.004, 0.9))
        return _stereo(x)
    if kind == "thunder":
        sec = 2.6
        n = rng.standard_normal(int(sec * SR))
        crack = (n - _lowpass(n, 1500)) * _env(sec, 0.0005, 0.05) * 1.4
        rumble = _lowpass(n, 140 + 60 * np.sin(np.linspace(0, 9, len(n)))) * _env(sec, 0.03, 0.9) * 5
        return _stereo(crack + rumble, width=1.0)
    if kind == "glitch":
        sec = 0.6
        x = np.zeros(int(sec * SR))
        pos = 0
        while pos < len(x) - 400:
            n = int(rng.integers(300, 2600))
            f = float(rng.choice([180, 330, 700, 1400, 2900]))
            seg = np.sign(np.sin(2 * np.pi * f * np.arange(n) / SR)) * (0.5 if rng.random() < 0.7 else 0.0)
            x[pos : pos + n] = seg[: len(x) - pos]
            pos += n + int(rng.integers(0, 900))
        return _stereo(x * 0.6, pan=np.sign(np.sin(np.linspace(0, 23, len(x)))) * 0.5)
    raise ValueError(f"unknown sound {kind!r}; known: {', '.join(KINDS)}")


def path(kind):
    """The sound as a WAV file in media/derived (made once)."""
    if kind not in KINDS:
        raise ValueError(f"unknown sound {kind!r}; known: {', '.join(KINDS)}")
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"sfx_{kind}.wav"
    if not p.exists():
        x = synth(kind)
        x = x / max(1e-6, float(np.max(np.abs(x)))) * 0.89  # -1 dBFS peak
        pcm = (x * 32767).astype("<i2")
        with wave.open(str(p), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
    return p


def seconds(kind):
    with wave.open(str(path(kind)), "rb") as w:
        return w.getnframes() / w.getframerate()
