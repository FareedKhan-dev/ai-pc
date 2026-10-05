"""LMMS 1.3 (the free music studio, in tools/lmms; installer's GitHub SHA-256 checked, unpacked by 7-Zip, never run): songs
written as LMMS projects (.mmp: a melody on LMMS's TripleOscillator synth, a kick drum on every beat when asked) and
rendered by LMMS itself on the hidden desktop to WAV, MP3, OGG or FLAC. LMMS's settings come from tools/lmms/home (its
-c option), so nothing goes to the user folder. Checked by FFmpeg: the length, the loudness (no clipping), and every
melody note's pitch measured by FFT in a render with the drums muted. 'lmms it' takes the melody just written.

  'lmms song: A4 B4 C5 D5 E5/2 D5/2 at 120 bpm with drums'   'lmms it as mp3'   'lmms render C:\\music\\track.mmp to mp3'
"""
import math
import re
import shutil
import subprocess
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "lmms", "LMMS: songs (melody + drums) written as LMMS projects and rendered by LMMS to WAV/MP3/OGG/FLAC; every note's pitch checked"
EXAMPLES = ["lmms song: A4 B4 C5 D5 E5/2 D5/2 at 120 bpm with drums", "lmms it as mp3", "lmms render track.mmp to mp3"]
HOME = ROOT / "tools" / "lmms"
EXE = HOME / "lmms.exe"
NOWIN = 0x08000000
TICKS = 48  # LMMS ticks per quarter note


def config():
    """LMMS's settings file in tools/lmms/home (its working folder there too)."""
    home = (HOME / "home").resolve()
    (home / "work").mkdir(parents=True, exist_ok=True)
    cfg = home / "lmmsrc.xml"
    if not cfg.exists():
        cfg.write_text(f'<?xml version="1.0"?>\n<!DOCTYPE lmms-config-file>\n<lmms version="1.3.0-alpha.2">\n'
                       f'  <paths workingdir="{(home / "work").as_posix()}/"/>\n</lmms>\n', encoding="utf-8")
    return cfg


def project(notes, bpm, drums, mute_drums=False):
    """An LMMS project (1.2-style XML, which LMMS upgrades on load). notes: [(midi note or None, quarters)]."""
    pos, melody = 0, []
    for n, q in notes:
        ticks = max(1, round(q * TICKS))
        if n is not None:
            melody.append(f'<note pan="0" key="{n - 12}" vol="100" pos="{pos}" len="{ticks}"/>')  # LMMS key 57 is A4 (MIDI 69)
        pos += ticks
    bars = max(1, math.ceil(pos / (4 * TICKS)))
    kicks = "".join(f'<note pan="0" key="57" vol="100" pos="{p}" len="12"/>' for p in range(0, bars * 4 * TICKS, TICKS))
    drum_track = (f'<track type="0" name="Kick" muted="{1 if mute_drums else 0}" solo="0"><instrumenttrack vol="70" pan="0" fxch="0" pitch="0" basenote="57" pitchrange="1">'
                  f'<instrument name="kicker"><kicker/></instrument></instrumenttrack><pattern pos="0" muted="0" steps="16" name="Kick" type="1">{kicks}</pattern></track>'
                  if drums else "")
    return (f'<?xml version="1.0"?>\n<!DOCTYPE lmms-project>\n<lmms-project version="1.0" creator="LMMS" creatorversion="1.2.2" type="song">\n'
            f'<head bpm="{bpm}" timesig_numerator="4" timesig_denominator="4" mastervol="80" masterpitch="0"/>\n<song><trackcontainer type="song">'
            f'<track type="0" name="Melody" muted="0" solo="0"><instrumenttrack vol="45" pan="0" fxch="0" pitch="0" basenote="57" pitchrange="1">'
            f'<instrument name="tripleoscillator"><tripleoscillator/></instrument></instrumenttrack>'
            f'<pattern pos="0" muted="0" steps="16" name="Melody" type="1">{"".join(melody)}</pattern></track>{drum_track}'
            f'</trackcontainer><timeline lp0pos="0" lp1pos="{bars * 4 * TICKS}" lpstate="0"/></song>\n</lmms-project>\n'), bars


def render(mmp, dest, fmt):
    from ai_pc.core import hidden_desktop
    dest.unlink(missing_ok=True)
    rc, out, err, timed_out = hidden_desktop.run([str(EXE), "-c", str(config()), "render", str(mmp), "-o", str(dest), "-f", fmt], timeout=600)
    return dest.exists() and dest.stat().st_size > 1000, out + err


def note_pitches(wav, notes, bpm, work):
    """[(wanted Hz, measured Hz)] for each melody note, measured in the middle of the note."""
    from ai_pc.apps.audacity import pitch
    out, t = [], 0.0
    for n, q in notes:
        dur = q * 60 / bpm
        if n is not None and dur >= 0.2:
            seg = work / "_seg.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t + min(0.05, dur / 4):.3f}", "-i", str(wav), "-t", f"{min(0.4, dur * 0.7):.3f}", str(seg)],
                           creationflags=NOWIN)
            out.append((440 * 2 ** ((n - 69) / 12), pitch(seg) or 0.0))
        t += dur
    (work / "_seg.wav").unlink(missing_ok=True)
    return out


def same_note(want, got):
    """The same note name (LMMS's default synth also sounds an octave below, so octaves are not compared)."""
    if got <= 0:
        return False
    cents = (1200 * math.log2(got / want)) % 1200
    return min(cents, 1200 - cents) < 40


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\blmms\b", c):
        return None
    fmt = next((f for f in ("mp3", "ogg", "flac", "wav") if re.search(rf"\b{f}\b", c)), "wav")
    f = find_file(text, ctx, {".mmp", ".mmpz"})
    if f:
        return {"op": "render", "file": f, "format": fmt}
    m = re.search(r"\b(?:song|melody|tune|notes)\s*:\s*(.+?)(?:\s+at\s+(\d{2,3})\s*bpm)?(?:\s+with\s+(?:a\s+)?(?:drums?|beat|kick))?\s*$", text, re.I)
    drums = bool(re.search(r"\bdrums?\b|\bbeat\b|\bkick\b", c))
    if m:
        return {"op": "song", "notes": m.group(1), "bpm": int(m.group(2)) if m.group(2) else 120, "drums": drums, "format": fmt}
    if re.search(r"\blmms (?:it|this|that)\b|\bin lmms\b", c) and (ctx.get("memo") or {}).get("music"):
        return {"op": "song", "from_memo": True, "bpm": None, "drums": drums, "format": fmt}
    return None


def run(op, ctx):
    if not EXE.exists():
        return "LMMS is not in tools/lmms."
    from ai_pc.apps.audacity import measure
    out = (Path(ctx["out"]) / "lmms").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "render":
        src = Path(op["file"]).resolve()
        dest = out / f"{src.stem}.{op['format']}"
        ok, log = render(src, dest, op["format"])
        info = measure(dest) if ok else {}
        return (f"LMMS rendered {src.name} to {dest} ({info.get('seconds', 0):.1f} s). " +
                ("Checked: it has sound (loudness " + f"{info.get('lufs')} LUFS, peak {info.get('peak')} dB)." if ok and info.get("lufs") is not None and info["lufs"] > -60
                 else "NOT right: " + log.strip()[-300:]))
    from ai_pc.apps import music
    if op.get("from_memo"):
        memo = ctx["memo"]["music"]
        notes = music.read_midi(Path(memo["midi"]).read_bytes())
        bpm, title = op.get("bpm") or memo.get("bpm", 120), Path(memo["midi"]).stem
    else:
        notes = [(n, q) for n, q, _ in music.read(op["notes"])]
        bpm, title = op["bpm"], "song"
    if not any(n is not None for n, _ in notes):
        return "No notes to play: give them like 'lmms song: A4 B4 C5 D5 at 120 bpm'."
    text, bars = project(notes, bpm, op["drums"])
    mmp = out / f"{title}.mmp"
    mmp.write_text(text, encoding="utf-8")
    dest = out / f"{title}.{op['format']}"
    ok, log = render(mmp, dest, op["format"])
    info = measure(dest) if ok else {}
    check_dir = out / "_check"
    check_dir.mkdir(exist_ok=True)
    (check_dir / "melody.mmp").write_text(project(notes, bpm, op["drums"], mute_drums=True)[0], encoding="utf-8")
    ok_m, _ = render(check_dir / "melody.mmp", check_dir / "melody.wav", "wav")
    pitches = note_pitches(check_dir / "melody.wav", notes, bpm, check_dir) if ok_m else []
    right = sum(1 for w, g in pitches if same_note(w, g))
    shutil.rmtree(check_dir, ignore_errors=True)
    song_secs = bars * 4 * 60 / bpm
    checks = [(f"LMMS rendered it ({info.get('seconds', 0):.1f} s for {bars} bar(s) at {bpm} bpm)", ok and song_secs - 0.5 <= info.get("seconds", 0) <= song_secs + 4),
              (f"it has sound and does not clip (loudness {info.get('lufs')} LUFS, peak {info.get('peak')} dB)",
               ok and info.get("lufs") is not None and info["lufs"] > -40 and (info.get("peak") is not None and info["peak"] < -0.1)),
              (f"every melody note plays at its pitch ({right} of {len(pitches)} measured by FFT)", bool(pitches) and right == len(pitches))]
    bad = [w for w, good in checks if not good]
    return (f"LMMS song: {mmp} (opens in LMMS to edit: a TripleOscillator melody" + (" and a kick drum on every beat" if op["drums"] else "") +
            f") rendered by LMMS to {dest}. " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else
                                                 "NOT right: " + "; ".join(bad) + ". " + (log.strip()[-200:] if not ok else "")))
