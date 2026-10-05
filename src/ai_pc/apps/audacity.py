"""Audacity (3.7.9 in tools/audacity, signed by Muse Group) driven by its own scripting module, mod-script-pipe: the real
Audacity runs on a hidden desktop (src/ai_pc/core/hidden_desktop.py; nothing appears on the screen), with its settings in its
"Portable Settings" folder, and is told what to do through its named pipes, the way Audacity's own scripting examples do.
Basic jobs: clean up a voice recording for a podcast (long pauses cut, compressed, loudness to -16 LUFS, limited, faded),
make a clip (a time range with fades), change tempo (length, same pitch) or pitch (same length), normalize the peak level,
convert between WAV, MP3, FLAC, OGG and AIFF. Checked by measuring the result with FFmpeg: loudness (EBU R128), pauses
left, length, peak level, and the pitch by FFT.

  'audacity podcast cleanup interview.wav'   'audacity clip song.mp3 0:30 to 1:00'   'audacity tempo +10% of talk.mp3'
  'audacity pitch up 2 semitones of tune.wav'   'audacity normalize song.wav to -1 db'   'audacity convert talk.wav to flac'   'make it 10% slower'
"""

import datetime as dt
import re
import shutil
import subprocess
import time
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "audacity", "Audacity: podcast cleanup, clips, tempo/pitch, normalize, format conversion (the real app, hidden)"
EXAMPLES = [
    "audacity podcast cleanup interview.wav",
    "audacity clip song.mp3 0:30 to 1:00",
    "audacity tempo +10% of talk.mp3",
    "audacity pitch up 2 semitones of tune.wav",
    "audacity convert talk.wav to flac",
]
FORMATS = ("mp3", "wav", "flac", "ogg", "aiff")
HOME = ROOT / "tools" / "audacity" / "audacity-win-3.7.9-64bit"
EXE = HOME / "Audacity.exe"
SETTINGS = HOME / "Portable Settings"
AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif", ".opus", ".wma"}
TO_PIPE, FROM_PIPE = r"\\.\pipe\ToSrvPipe", r"\\.\pipe\FromSrvPipe"


def _wx(path):
    return str(Path(path).resolve()).replace("\\", "\\\\")  # Audacity's settings file escapes backslashes


def setup():
    """Audacity's settings beside it ('Portable Settings'): scripting on, the cloud modules off, no splash, no update check,
    its session files inside the project. Merged into the settings file Audacity keeps, the way it writes them."""
    SETTINGS.mkdir(exist_ok=True)
    temp = HOME.parent / "temp" / "SessionData"
    temp.mkdir(parents=True, exist_ok=True)
    cfg = SETTINGS / "audacity.cfg"
    sections, order = {"": {}}, [""]
    sec = ""
    for line in cfg.read_text(encoding="utf-8").splitlines() if cfg.exists() else ["PrefsVersion=1.1.1r1"]:
        m = re.fullmatch(r"\[(.+)\]", line.strip())
        if m:
            sec = m.group(1)
            if sec not in sections:
                sections[sec] = {}
                order.append(sec)
        elif "=" in line:
            k, v = line.split("=", 1)
            sections[sec][k] = v
    want = {
        "[root]": {"PrefsVersion": "1.1.1r1", "WantAssociateFiles": "0"},  # no 'associate .aup3 files?' question (it would change the registry)
        "GUI": {"ShowSplashScreen": "0"},
        "Update": {"DefaultUpdatesChecking": "0", "UpdateNoticeShown": "1"},
        "Directories": {"TempDir": _wx(temp)},
        "Warnings": {"FirstProjectSave": "0", "MixMono": "0", "MixStereo": "0", "MixUnknownChannels": "0"},
    }
    for name in ("mod-script-pipe", "mod-cloud-audiocom", "mod-musehub-ui"):
        dll = HOME / "modules" / f"{name}.dll"
        if dll.exists():
            want.setdefault("Module", {})[name] = "1" if name == "mod-script-pipe" else "0"  # nothing here goes online
            want.setdefault("ModulePath", {})[name] = _wx(dll)
            want.setdefault("ModuleDateTime", {})[name] = dt.datetime.fromtimestamp(dll.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    for s, kv in want.items():
        s = "" if s == "[root]" else s
        if s not in sections:
            sections[s] = {}
            order.append(s)
        sections[s].update(kv)
    lines = []
    for s in order:
        lines += ([f"[{s}]"] if s else []) + [f"{k}={v}" for k, v in sections[s].items()]
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for d in temp.iterdir():  # left-over autosaves would bring up a recovery dialog
        shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink(missing_ok=True)


class Session:
    """Audacity running hidden, talked to through its script pipes."""

    def __init__(self, timeout=60):
        import os
        import threading

        from ai_pc.core import hidden_desktop

        setup()
        self.user_dirs = [Path(os.environ.get(v, "")) / "audacity" for v in ("APPDATA", "LOCALAPPDATA")] + [Path.home() / "Documents" / "Audacity"]
        self.had = {p: p.exists() for p in self.user_dirs}
        self.proc = hidden_desktop.start([str(EXE)], cwd=str(HOME))
        end = time.monotonic() + timeout
        self.to = self.frm = None
        while time.monotonic() < end:  # the pipe serves one connection, so it is opened once and kept
            try:
                self.to = open(TO_PIPE, "wb", buffering=0)
                self.frm = open(FROM_PIPE, "rb", buffering=0)
                break
            except OSError:
                if not self.proc.alive():
                    break
                time.sleep(0.5)
        if not self.frm:
            code, out, err = self.proc.stop()
            raise RuntimeError(f"Audacity's script pipe did not open (exit {code}) {err[-300:]}")
        import queue

        self.answers = queue.Queue()

        def reader():  # the answer comes as pipe messages, some empty (which Python reads as b'')
            while True:
                try:
                    self.answers.put(self.frm.read(65536))
                except (OSError, ValueError):
                    self.answers.put(None)
                    return

        threading.Thread(target=reader, daemon=True).start()
        # the pipe opens before Audacity's window is ready; a command sent then gets an empty answer
        while time.monotonic() < end and not any(
            w[0] == "Audacity" and "Top Panel" in w[3] for w in hidden_desktop.windows(self.proc.pi.dwProcessId)
        ):
            if not self.proc.alive():
                raise RuntimeError("Audacity closed while starting")
            time.sleep(0.25)
        stuck = [w for w in hidden_desktop.windows(self.proc.pi.dwProcessId) if w[1] == "#32770"]
        if stuck:
            self.close()
            raise RuntimeError(f"Audacity is asking something on its hidden desktop: {stuck[0][0]} {stuck[0][3]}")

    def do(self, command, timeout=300):
        """Send one scripting command; (ok, Audacity's answer). As Audacity's own pipe_test.py: a command ends with CR LF NUL;
        the answer ends with 'BatchCommand finished: ...' and an empty line."""
        import queue

        self.to.write((command + "\r\n\0").encode("utf-8"))
        data, end = b"", time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                chunk = self.answers.get(timeout=0.5)
            except queue.Empty:
                if not self.proc.alive():
                    break
                continue
            if chunk is None:
                break
            data += chunk
            if b"BatchCommand finished" in data and data.endswith(b"\n\n"):
                break
        text = data.decode("utf-8", "replace").strip()
        return "BatchCommand finished: OK" in text, text

    def close(self):
        try:
            self.do("SelectAll:", 30)
            self.do("RemoveTracks:", 30)
            self.to.write(b"Exit:\r\n\0")
        except OSError:
            pass
        for f in (self.to, self.frm):
            try:
                f.close()
            except OSError:
                pass
        exited = self.proc.wait(15)
        self.proc.stop()
        for p in self.user_dirs:  # a user folder Audacity made empty (Windows gives it AppData\Local whatever the settings say)
            if not self.had[p] and p.exists() and not any(f.is_file() for f in p.rglob("*")):
                shutil.rmtree(p, ignore_errors=True)
        return exited


NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def measure(path):
    """FFmpeg's view of an audio file: seconds, channels, codec, integrated loudness (LUFS), peak (dBFS), pauses > 1.2 s."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=channels,codec_name", "-of", "default=nw=1", str(path)],
        capture_output=True,
        text=True,
        creationflags=NOWIN,
    )
    info = dict(ln.split("=", 1) for ln in r.stdout.splitlines() if "=" in ln)
    a = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "ebur128=framelog=quiet,volumedetect,silencedetect=noise=-45dB:d=1.2",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        creationflags=NOWIN,
    ).stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", a)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", a)
    return {
        "seconds": float(info.get("duration", 0) or 0),
        "channels": int(info.get("channels", 0) or 0),
        "codec": info.get("codec_name", "?"),
        "lufs": float(lufs[-1]) if lufs else None,
        "peak": float(peak.group(1)) if peak else None,
        "pauses": a.count("silence_start"),
    }


def pitch(path):
    """The strongest frequency (Hz) in the audio, from an FFT of the decoded samples."""
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "44100", "-f", "f32le", "-"], capture_output=True, creationflags=NOWIN
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < 4096:
        return None
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spec[1:]) + 1) * 44100 / len(x)


def seconds(t):
    """'1:05' / '65' / '65s' / '1m5s' -> seconds."""
    t = t.strip().lower()
    if ":" in t:
        parts = [float(p) for p in t.split(":")]
        return sum(v * 60**i for i, v in enumerate(reversed(parts)))
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*m(?:in)?)?\s*(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?)?", t)
    if m and (m.group(1) or m.group(2)):
        return float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return float(t)


def steps(op, length):
    """Audacity scripting commands for the job (after Import2 and before Export2)."""
    k = op["job"]
    if k == "cleanup":
        return [
            "SelectAll:",
            'TruncateSilence: Threshold=-40 Action="Truncate Detected Silence" Minimum=1 Truncate=0.5',
            "Compressor: thresholdDb=-20 makeupGainDb=0 kneeWidthDb=5 compressionRatio=3 lookaheadMs=1 attackMs=30 releaseMs=150",
            "LoudnessNormalization: LUFSLevel=-16 NormalizeTo=0 StereoIndependent=False DualMono=True",
            "Limiter: thresholdDb=-1 makeupTargetDb=-1 kneeWidthDb=2 lookaheadMs=1 releaseMs=20",
            "FADES",
        ]
    if k == "clip":
        return [
            f"Select: Start={op['end']} End={length + 1} RelativeTo=ProjectStart",
            "Delete:",
            f"Select: Start=0 End={op['start']} RelativeTo=ProjectStart",
            "Delete:",
            "FADES",
        ]
    if k == "tempo":
        return ["SelectAll:", f"ChangeTempo: Percentage={op['percent']} SBSMS=False"]
    if k == "pitch":
        return ["SelectAll:", f"ChangePitch: Percentage={op['percent']:.4f} SBSMS=False"]
    if k == "normalize":
        return ["SelectAll:", f"Normalize: PeakLevel={op['peak']} ApplyVolume=True RemoveDcOffset=True StereoIndependent=False"]
    return ["SelectAll:"]  # convert


def check(op, before, after, out, src_pitch=None):
    k = op["job"]
    c = [(f"the {out.suffix[1:].upper()} file was written and reads back", after["seconds"] > 0)]
    if k == "cleanup":
        # -16 LUFS for stereo; Audacity measures mono as dual mono, so a mono file reads -19 LUFS to FFmpeg (the podcast standard for mono)
        target = -16 if after["channels"] >= 2 else -19
        c += [
            (
                f"loudness {target} LUFS {'stereo' if target == -16 else 'mono (= -16 LUFS as dual mono)'}, the podcast standard (within 1)",
                after["lufs"] is not None and abs(after["lufs"] - target) <= 1.0,
            ),
            ("no pause over 1.2 s left", after["pauses"] == 0),
            ("peaks under -0.9 dBFS (no clipping)", after["peak"] is not None and after["peak"] <= -0.9),
            (f"shorter: {before['seconds']:.1f} s -> {after['seconds']:.1f} s", after["seconds"] < before["seconds"]),
        ]
    elif k == "clip":
        want = op["end"] - op["start"]
        c.append((f"exactly the {want:g} s asked", abs(after["seconds"] - want) <= 0.1))
    elif k == "tempo":
        want = before["seconds"] / (1 + op["percent"] / 100)
        c.append(
            (
                f"{'faster' if op['percent'] > 0 else 'slower'}: {before['seconds']:.1f} s -> {after['seconds']:.1f} s",
                abs(after["seconds"] - want) <= want * 0.02,
            )
        )
    elif k == "pitch":
        c.append(("same length", abs(after["seconds"] - before["seconds"]) <= before["seconds"] * 0.02))
        got = pitch(out)
        if src_pitch and got:
            want = src_pitch * (1 + op["percent"] / 100)
            c.append((f"pitch {src_pitch:.0f} Hz -> {got:.0f} Hz (asked {want:.0f})", abs(got - want) <= want * 0.02))
    elif k == "normalize":
        c.append((f"peak at {op['peak']:g} dBFS", after["peak"] is not None and abs(after["peak"] - op["peak"]) <= 0.3))
    else:
        c.append(("same length as the original", abs(after["seconds"] - before["seconds"]) <= 0.1))
    return c


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    last = (ctx.get("memo") or {}).get("audacity")
    named = re.search(r"\baudacity\b", c)
    if not named and not (
        last and re.search(r"\b(?:it|this|that)\b", c) and re.search(r"\b(?:faster|slower|tempo|pitch|louder|normali[sz]e|clip|cut)\b", c)
    ):
        return None
    named_file = any(n.lower() in c or Path(n).stem.lower() in c for n in (ctx.get("files") or {})) or re.search(
        r"[a-z]:\\|\.(?:wav|mp3|flac|ogg|m4a)\b", c
    )
    if last and re.search(r"\b(?:it|this|that)\b", c) and not named_file:
        f = last["out"]  # 'make it 10% slower': the result just made
    else:
        f = find_file(text, ctx, AUDIO)
    if not f:
        return None
    fmt = re.search(r"\b(?:to|as|in(?:to)?)\s+(" + "|".join(FORMATS) + r")\b", c)
    op = {"op": "edit", "file": f, "format": fmt.group(1) if fmt else None}
    m = re.search(r"\b(\d[\d:.]*\s*(?:s|sec|seconds?|m|min)?)\s*(?:to|-|until)\s*(\d[\d:.]*\s*(?:s|sec|seconds?|m|min)?)", c)
    pct = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", c)
    semis = re.search(r"\b(up|down)?\s*([+-]?\d+(?:\.\d+)?)\s*semitones?\b", c)
    if re.search(r"\bpodcast\b|\bclean\s*up\b|\bcleanup\b|\bvoice\b", c):
        op["job"] = "cleanup"
    elif re.search(r"\bclip\b|\bcut\b|\bexcerpt\b|\btrim\b", c) and m:
        op.update(job="clip", start=seconds(m.group(1)), end=seconds(m.group(2)))
    elif re.search(r"\btempo\b|\bfaster\b|\bslower\b|\bspeed\b", c) and pct:
        p = abs(float(pct.group(1)))
        op.update(job="tempo", percent=-p if re.search(r"\bslower\b", c) or pct.group(1).startswith("-") else p)
    elif re.search(r"\bpitch\b|\bsemitones?\b", c) and (semis or pct):
        if semis:
            n = float(semis.group(2)) * (-1 if semis.group(1) == "down" else 1)
            op.update(job="pitch", percent=(2 ** (n / 12) - 1) * 100, semitones=n)
        else:
            op.update(job="pitch", percent=float(pct.group(1)) * (-1 if re.search(r"\bdown\b", c) else 1))
    elif re.search(r"\bnormali[sz]e\b|\bpeak\b", c):
        db = re.search(r"(-?\d+(?:\.\d+)?)\s*db\b", c)
        op.update(job="normalize", peak=-abs(float(db.group(1))) if db else -1.0)
    elif re.search(r"\bconvert\b|\bexport\b|\bsave\b", c) and fmt:
        op["job"] = "convert"
    else:
        return None
    return op


def run(op, ctx):
    if not EXE.exists():
        return "Audacity is not in tools/audacity."
    src = Path(op["file"]).resolve()
    before = measure(src)
    if not before["seconds"]:
        return f"{src.name} is not audio FFmpeg can read."
    fmt = op["format"] or ("mp3" if op["job"] == "cleanup" else src.suffix[1:].lower() if src.suffix[1:].lower() in FORMATS else "wav")
    out = Path(ctx["out"]) / "audacity"
    out.mkdir(parents=True, exist_ok=True)
    tag = {
        "cleanup": "podcast",
        "clip": f"clip_{op.get('start', 0):g}-{op.get('end', 0):g}s",
        "tempo": f"tempo{op.get('percent', 0):+g}",
        "pitch": f"pitch{op.get('semitones', op.get('percent', 0)):+g}",
        "normalize": f"peak{op.get('peak', 0):g}dB",
        "convert": "converted",
    }[op["job"]]
    dest = (out / f"{src.stem}_{tag}.{fmt}").resolve()
    dest.unlink(missing_ok=True)
    if op["job"] == "clip" and not (0 <= op["start"] < op["end"] <= before["seconds"] + 0.01):
        return f"The clip {op['start']:g}-{op['end']:g} s is outside {src.name} ({before['seconds']:.1f} s long)."
    src_pitch = pitch(src) if op["job"] == "pitch" else None
    s = Session()
    log = []
    try:
        ok, ans = s.do(f'Import2: Filename="{src.as_posix()}"')
        log.append(("Import2", ok, ans))
        length = before["seconds"] if op["job"] != "clip" else before["seconds"]
        for cmd in steps(op, length):
            if cmd == "FADES":  # half a second in and out, measured from the project as it is now
                ok, ans = s.do("GetInfo: Type=Tracks Format=JSON")
                end = max((t.get("end", 0) for t in __import__("json").loads(ans.split("BatchCommand")[0] or "[]")), default=0)
                for c2 in (
                    "Select: Start=0 End=0.5 RelativeTo=ProjectStart",
                    "FadeIn:",
                    f"Select: Start={max(0, end - 0.5)} End={end} RelativeTo=ProjectStart",
                    "FadeOut:",
                ):
                    ok, ans = s.do(c2)
                    log.append((c2, ok, ans))
                continue
            ok, ans = s.do(cmd)
            log.append((cmd, ok, ans))
        s.do("SelectAll:")  # Export2 writes the selection, so all of it is selected first
        ok, ans = s.do(f'Export2: Filename="{dest.as_posix()}" NumChannels={max(1, before["channels"] or 1)}')
        log.append(("Export2", ok, ans))
    finally:
        s.close()
    failed = [(cmd, ans) for cmd, ok, ans in log if not ok]
    if failed or not dest.exists():
        return f"Audacity did not finish: {failed[0][0] if failed else 'Export2'} -> {(failed[0][1] if failed else 'no file')[:300]}"
    after = measure(dest)
    checks = check(op, before, after, dest, src_pitch)
    bad = [w for w, ok in checks if not ok]
    ctx.setdefault("memo", {})["audacity"] = {"out": str(dest)}
    done = {
        "cleanup": "cleaned up for a podcast (long pauses cut, compressed, -16 LUFS, limited, faded)",
        "clip": "clipped (with fades)",
        "tempo": f"tempo {op.get('percent', 0):+g}% (same pitch)",
        "pitch": f"pitch {op.get('semitones', 0):+g} semitones (same length)" if op.get("semitones") else f"pitch {op.get('percent', 0):+g}%",
        "normalize": f"peak normalized to {op.get('peak', 0):g} dB",
        "convert": f"converted to {fmt.upper()}",
    }[op["job"]]
    loud = f", {after['lufs']:.1f} LUFS" if after["lufs"] is not None else ""
    return (
        f"Audacity {done}: {dest} ({after['seconds']:.1f} s{loud}, peak {after['peak']:.1f} dB). Done by Audacity itself through its scripting pipe, "
        "on a hidden desktop. "
        + ("Checked with FFmpeg: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ".")
    )
