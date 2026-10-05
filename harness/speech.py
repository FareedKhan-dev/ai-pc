"""Speech: what is said and when (local Whisper, faster-whisper "base", CPU int8, ~10-20x real time), for the edits
YouTube and talking-head videos need: captions word by word, jump cuts that drop pauses and filler words, zooms and
sound on the words that matter.

  transcribe(path) -> {"language", "text", "words": [{"w", "start", "end", "prob"}], "segments": [...]}   (cached)
  speech_runs(words, max_pause=0.35, drop_fillers=True) -> [[start, end], ...]   the parts worth keeping
  chunks(words, n=3) -> caption lines of 1-3 words (Hormozi style), never across a pause
  keywords(words, k) -> the words to emphasise (long / rare / numbers), when the planner names none
Model and cache stay inside the project (models/whisper/base, state/media/*.asr.json).
"""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from .config import ROOT, STATE

MODEL_DIR = ROOT / "models" / "whisper" / "base"
CACHE = STATE / "media"
FILLERS = {"um", "uh", "erm", "uhm", "hmm", "mm", "ah", "eh", "uh-huh"}
_model, _lock = None, threading.Lock()


def available():
    return (MODEL_DIR / "model.bin").exists()


def _load():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8", cpu_threads=8)
    return _model


def _key(path):
    st = Path(path).stat()
    return hashlib.sha1(f"{Path(path).name}|{st.st_size}|{st.st_mtime_ns}|asr1".encode()).hexdigest()[:12]


def transcribe(path, language=None, log=print):
    """Words with timestamps for a video or audio file (None when the model is missing or there is no speech)."""
    if not available():
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    cp = CACHE / f"{Path(path).stem[:40]}_{_key(path)}.asr.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    from .audio import load
    samples = load(path, sr=16000)  # our own ffmpeg decode (faster-whisper's PyAV path breaks on newer PyAV)
    if len(samples) < 16000 * 0.3:
        return None
    segs, info = _load().transcribe(samples, language=language, word_timestamps=True, vad_filter=True, beam_size=5,
                                    condition_on_previous_text=False)
    words, segments = [], []
    for s in segs:
        segments.append({"start": round(float(s.start), 3), "end": round(float(s.end), 3), "text": s.text.strip()})
        for w in s.words or []:
            words.append({"w": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3), "prob": round(float(w.probability), 3)})
    out = {"language": info.language, "duration": round(info.duration, 2), "text": " ".join(s["text"] for s in segments),
           "words": words, "segments": segments, "seconds": round(time.perf_counter() - t0, 2)}
    cp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log(f"  transcribed {Path(path).name}: {len(words)} words ({info.language}) in {out['seconds']} s")
    return out


def _norm(w):
    return re.sub(r"[^\w'-]", "", w.lower())


def speech_runs(words, max_pause=0.35, drop_fillers=True, pad=0.06, min_len=0.25):
    """Stretches of speech to keep: pauses longer than max_pause and filler words are cut out."""
    keep = [w for w in words if not (drop_fillers and _norm(w["w"]) in FILLERS)]
    runs = []
    for w in keep:
        a, b = max(0.0, w["start"] - pad), w["end"] + pad
        if runs and a - runs[-1][1] <= max_pause:
            runs[-1][1] = b
        else:
            runs.append([a, b])
    return [[round(float(a), 3), round(float(b), 3)] for a, b in runs if b - a >= min_len]


def chunks(words, n=3, max_gap=0.3, max_chars=18):
    """Caption lines of up to n words that never span a pause; each line: {"start", "end", "text", "words"}."""
    out, cur = [], []
    for w in words:
        if _norm(w["w"]) in FILLERS:
            continue
        if cur and (len(cur) >= n or w["start"] - cur[-1]["end"] > max_gap or len(" ".join(x["w"] for x in cur + [w])) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [{"start": c[0]["start"], "end": c[-1]["end"], "text": " ".join(x["w"] for x in c).strip(), "words": [x["w"] for x in c]} for c in out]


def keywords(words, k=4):
    """Words worth a zoom or a colour: numbers, money, long rare words (no stop words)."""
    stop = {"the", "and", "that", "this", "with", "have", "from", "your", "what", "when", "they", "there", "about", "would",
            "could", "should", "their", "which", "were", "been", "just", "like", "really", "because", "going", "into"}
    scored = []
    for i, w in enumerate(words):
        t = _norm(w["w"])
        if not t or t in stop or t in FILLERS:
            continue
        sc = len(t) + (6 if re.search(r"\d", t) else 0) + (5 if t.startswith("$") or t in ("money", "million", "free", "never", "secret") else 0)
        scored.append((sc, i))
    picked = sorted(i for _, i in sorted(scored, reverse=True)[:k])
    return [words[i] for i in picked]


def cached(path):
    """The transcript if it was already made (no model call)."""
    try:
        cp = CACHE / f"{Path(path).stem[:40]}_{_key(path)}.asr.json"
        return json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else None
    except OSError:
        return None
