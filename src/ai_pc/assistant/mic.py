"""The microphone, while the person holds the key combo (or the mic button) to talk: Windows' own recorder (winmm),
nothing to install, 16 kHz mono like the speech model wants, recording only between start() and stop().

  rec = Recorder(); rec.start()      ... rec.level (0..1, for the meter) ...      path = rec.stop("note.wav")  (None if too short)
"""
import array
import ctypes
import math
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path

WAVE_MAPPER = 0xFFFFFFFF  # the microphone chosen in Windows' sound settings
WHDR_DONE, WHDR_PREPARED = 0x1, 0x2
MMSYSERR = {1: "an error in the sound system", 2: "no microphone", 4: "the microphone is in use", 6: "no microphone",
            7: "no microphone driver", 32: "the microphone cannot record this format"}


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1  # mmsystem.h packs everything to bytes
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD), ("dwBytesRecorded", wintypes.DWORD),
                    ("dwUser", ctypes.c_size_t), ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
                    ("lpNext", ctypes.POINTER(WAVEHDR)), ("reserved", ctypes.c_size_t)]
_winmm = None


def _api():
    global _winmm
    if _winmm is None:
        w = ctypes.WinDLL("winmm")
        w.waveInOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX), ctypes.c_size_t, ctypes.c_size_t,
                                 wintypes.DWORD]
        for f in (w.waveInPrepareHeader, w.waveInUnprepareHeader, w.waveInAddBuffer):
            f.argtypes = [wintypes.HANDLE, ctypes.POINTER(WAVEHDR), wintypes.UINT]
        for f in (w.waveInStart, w.waveInStop, w.waveInReset, w.waveInClose):
            f.argtypes = [wintypes.HANDLE]
        for f in (w.waveInOpen, w.waveInPrepareHeader, w.waveInUnprepareHeader, w.waveInAddBuffer, w.waveInStart, w.waveInStop, w.waveInReset,
                  w.waveInClose):
            f.restype = wintypes.UINT
        _winmm = w
    return _winmm


class MicError(RuntimeError):
    pass


def microphones():
    """How many recording devices Windows has (looks only; does not open the microphone)."""
    try:
        return ctypes.WinDLL("winmm").waveInGetNumDevs()
    except OSError:
        return 0


def level(data, width=2):
    """Loudness 0..1 of a piece of 16-bit sound (for the meter that shows it hears you)."""
    if not data or width != 2:
        return 0.0
    a = array.array("h")
    a.frombytes(data[: len(data) - len(data) % 2])
    if not a:
        return 0.0
    rms = math.sqrt(sum(x * x for x in a) / len(a)) / 32768.0
    return min(1.0, math.log10(1 + 60 * rms) / math.log10(61)) if rms > 0 else 0.0  # a scale that moves for normal speech


def write_wav(path, chunks, rate, channels):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(chunks))
    return path


class Recorder:
    """Records from the default microphone between start() and stop() (at most max_seconds)."""
    FORMATS = ((16000, 1), (44100, 1), (48000, 2))

    def __init__(self, chunk_ms=100, buffers=8, max_seconds=120, min_seconds=0.35):
        self.chunk_ms, self.n, self.max_seconds, self.min_seconds = chunk_ms, buffers, max_seconds, min_seconds
        self.h, self.chunks, self.level, self.recording = None, [], 0.0, False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.rate = self.channels = None
        self.t0 = 0.0

    def start(self):
        w = _api()
        last = None
        for rate, ch in self.FORMATS:
            fmt = WAVEFORMATEX(1, ch, rate, rate * ch * 2, ch * 2, 16, 0)
            h = wintypes.HANDLE()
            last = w.waveInOpen(ctypes.byref(h), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0)  # CALLBACK_NULL: we look at the buffers
            if last == 0:
                self.h, self.rate, self.channels = h, rate, ch
                break
        if self.h is None:
            raise MicError(f"The microphone could not be opened: {MMSYSERR.get(last, f'code {last}')}. Check Settings > Privacy > Microphone.")
        size = self.rate * self.channels * 2 * self.chunk_ms // 1000
        self.bufs = [ctypes.create_string_buffer(size) for _ in range(self.n)]
        self.hdrs = [WAVEHDR() for _ in range(self.n)]
        for b, hd in zip(self.bufs, self.hdrs):
            hd.lpData, hd.dwBufferLength = ctypes.cast(b, ctypes.c_void_p), size
            w.waveInPrepareHeader(self.h, ctypes.byref(hd), ctypes.sizeof(WAVEHDR))
            w.waveInAddBuffer(self.h, ctypes.byref(hd), ctypes.sizeof(WAVEHDR))
        self.chunks, self._next = [], 0
        self._stop.clear()
        if w.waveInStart(self.h) != 0:
            self._close()
            raise MicError("The microphone would not start recording.")
        self.t0, self.recording = time.monotonic(), True
        self._pump = threading.Thread(target=self._run, daemon=True, name="aipc-mic")
        self._pump.start()
        return self

    def seconds(self):
        return time.monotonic() - self.t0 if self.recording else 0.0

    def _take(self, hd, again):
        if hd.dwFlags & WHDR_DONE:
            if hd.dwBytesRecorded:
                data = ctypes.string_at(hd.lpData, hd.dwBytesRecorded)
                self.chunks.append(data)
                self.level = level(data)
            hd.dwFlags &= ~WHDR_DONE
            hd.dwBytesRecorded = 0
            if again:
                _api().waveInAddBuffer(self.h, ctypes.byref(hd), ctypes.sizeof(WAVEHDR))
            return True
        return False

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                took = self._take(self.hdrs[self._next], again=True)
                if took:
                    self._next = (self._next + 1) % self.n
            if not took:
                time.sleep(0.01)
            if time.monotonic() - self.t0 > self.max_seconds:
                break

    def _close(self):
        w = _api()
        if self.h is not None:
            w.waveInReset(self.h)
            for hd in getattr(self, "hdrs", []):
                w.waveInUnprepareHeader(self.h, ctypes.byref(hd), ctypes.sizeof(WAVEHDR))
            w.waveInClose(self.h)
        self.h, self.recording = None, False

    def stop(self, path=None):
        """Stop and save what was said as a WAV at path; None when it was too short to be words (or no path)."""
        if self.h is None:
            return None
        self._stop.set()
        self._pump.join(2)
        w = _api()
        seconds = self.seconds()
        w.waveInStop(self.h)
        w.waveInReset(self.h)  # every buffer still out comes back, marked done
        with self._lock:
            for k in range(self.n):  # in the order they were filled
                self._take(self.hdrs[(self._next + k) % self.n], again=False)
        self._close()
        self.level = 0.0
        if path is None or seconds < self.min_seconds or not self.chunks:
            return None
        return write_wav(path, self.chunks, self.rate, self.channels)

    def cancel(self):
        self.stop(None)
