"""Music from notes written as letters: a melody becomes a MIDI file (any player, DAW or phone) and MusicXML (MuseScore,
Sibelius, Finale and Dorico open it as sheet music), at a tempo and on an instrument (General MIDI). Notes: C D E F G
A B with # or b, an octave number (C5), and a length after a slash (/2 half, /4 quarter, /8 eighth; quarter if not
said); R is a rest. Checks: the MIDI file read back has every note, at the right pitch and length.

  'melody: C4 D4 E4 F4 G4/2 G4/2 A4 A4 A4 A4 G4/1 at 100 bpm on piano'   'tune: E5 D#5 E5 D#5 E5 B4 D5 C5 A4/2 on flute'
"""
import re
import struct
from pathlib import Path

NAME, LABEL = "music", "Music: melodies to MIDI and MusicXML sheet music"
EXAMPLES = ["melody: C4 D4 E4 F4 G4/2 G4/2 A4 A4 A4 A4 G4/1 at 100 bpm on piano"]
STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
PROGRAMS = {"piano": 0, "harmonium": 20, "organ": 19, "guitar": 24, "bass": 32, "violin": 40, "strings": 48, "flute": 73, "trumpet": 56, "sitar": 104,
            "shehnai": 111, "harp": 46, "choir": 52, "marimba": 12}
TPQ = 480  # ticks per quarter note


def read(spec):
    """'C4 D#4/8 R/2' -> [(midi number or None for a rest, quarters, name)]."""
    out = []
    for tok in spec.split():
        m = re.fullmatch(r"([A-Ga-g]|[Rr])([#b]?)(\d)?(?:/(\d+)(\.)?)?", tok)
        if not m:
            raise ValueError(f"'{tok}' is not a note (e.g. C4, F#4/8, R/2)")
        q = 4 / int(m.group(4) or 4) * (1.5 if m.group(5) else 1)
        if m.group(1).upper() == "R":
            out.append((None, q, "R"))
            continue
        octave = int(m.group(3) or 4)
        n = 12 * (octave + 1) + STEPS[m.group(1).upper()] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
        out.append((n, q, tok))
    return out


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def midi(notes, bpm=100, program=0):
    ev = b"\x00\xff\x51\x03" + (60_000_000 // bpm).to_bytes(3, "big") + b"\x00\xc0" + bytes([program])
    wait = 0
    for n, q, _ in notes:
        ticks = int(q * TPQ)
        if n is None:
            wait += ticks
            continue
        ev += _vlq(wait) + bytes([0x90, n, 90]) + _vlq(ticks) + bytes([0x80, n, 0])
        wait = 0
    ev += _vlq(wait) + b"\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, TPQ) + b"MTrk" + struct.pack(">I", len(ev)) + ev


def read_midi(data):
    """[(note, quarters)] from a single-track file written above (for the check)."""
    assert data[:4] == b"MThd"
    tpq = struct.unpack(">H", data[12:14])[0]
    i = 22
    end = 22 + struct.unpack(">I", data[18:22])[0]
    t, on, out, status = 0, {}, [], 0

    def vlq(i):
        n = 0
        while True:
            b = data[i]
            i += 1
            n = (n << 7) | (b & 0x7F)
            if not b & 0x80:
                return n, i
    while i < end:
        d, i = vlq(i)
        t += d
        b = data[i]
        if b == 0xFF:
            ln, j = vlq(i + 2)
            i = j + ln
            continue
        status, i = (b, i + 1) if b & 0x80 else (status, i)
        if status & 0xF0 == 0xC0:
            i += 1
        elif status & 0xF0 == 0x90 and data[i + 1] > 0:
            on[data[i]] = t
            i += 2
        elif status & 0xF0 in (0x80, 0x90):
            out.append((data[i], (t - on.pop(data[i])) / tpq))
            i += 2
        else:
            i += 2
    return out


def musicxml(notes, title, bpm, instrument):
    types = {4.0: "whole", 2.0: "half", 1.0: "quarter", 0.5: "eighth", 0.25: "16th", 3.0: "half", 1.5: "quarter", 0.75: "eighth"}
    names = {0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("E", -1), 4: ("E", 0), 5: ("F", 0), 6: ("F", 1), 7: ("G", 0), 8: ("A", -1), 9: ("A", 0), 10: ("B", -1), 11: ("B", 0)}
    measures, cur, beats = [], [], 0.0
    for n, q, _ in notes:
        if n is None:
            x = f"<note><rest/><duration>{int(q * 4)}</duration><type>{types.get(q, 'quarter')}</type></note>"
        else:
            step, alter = names[n % 12]
            x = (f"<note><pitch><step>{step}</step>" + (f"<alter>{alter}</alter>" if alter else "") + f"<octave>{n // 12 - 1}</octave></pitch>"
                 f"<duration>{int(q * 4)}</duration><type>{types.get(q, 'quarter')}</type>" + ("<dot/>" if q in (3.0, 1.5, 0.75) else "") + "</note>")
        cur.append(x)
        beats += q
        if beats >= 4:
            measures.append(cur)
            cur, beats = [], 0.0
    if cur:
        measures.append(cur)
    body = ""
    for i, m in enumerate(measures, 1):
        attrs = ("<attributes><divisions>4</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>"
                 f"<clef><sign>G</sign><line>2</line></clef></attributes><direction placement='above'><sound tempo='{bpm}'/></direction>") if i == 1 else ""
        body += f'<measure number="{i}">{attrs}{"".join(m)}</measure>'
    return ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd"><score-partwise version="4.0">'
            f"<work><work-title>{title}</work-title></work><movement-title>{title}</movement-title><part-list><score-part id='P1'><part-name>{instrument.title()}</part-name></score-part></part-list>"
            f"<part id='P1'>{body}</part></score-partwise>")


def parse(text, ctx):
    m = re.match(r"^\s*(?:melody|tune|notes|music)\s*(?:'([^']*)')?\s*:\s*(.+)$", text, re.I | re.S)
    if not m:
        return None
    rest = m.group(2)
    bpm = re.search(r"\bat\s+(\d{2,3})\s*bpm\b", rest, re.I)
    inst = re.search(r"\bon\s+(?:a\s+|the\s+)?(\w+)\s*$", rest, re.I)
    notes = re.sub(r"\bat\s+\d{2,3}\s*bpm\b|\bon\s+(?:a\s+|the\s+)?\w+\s*$", "", rest, flags=re.I).strip()
    return {"op": "melody", "notes": notes, "bpm": int(bpm.group(1)) if bpm else 100, "instrument": (inst.group(1).lower() if inst else "piano"),
            "title": m.group(1) or "Melody"}


def run(op, ctx):
    notes = read(op["notes"])
    inst = op["instrument"] if op["instrument"] in PROGRAMS else "piano"
    out = Path(ctx["out"]) / "music"
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", op["title"])
    mid = out / f"{stem}.mid"
    mid.write_bytes(midi(notes, op["bpm"], PROGRAMS[inst]))
    xml = out / f"{stem}.musicxml"
    xml.write_text(musicxml(notes, op["title"], op["bpm"], inst), encoding="utf-8")
    back = read_midi(mid.read_bytes())
    ok = back == [(n, q) for n, q, _ in notes if n is not None]
    secs = sum(q for _, q, _ in notes) * 60 / op["bpm"]
    ctx.setdefault("memo", {})["music"] = {"musicxml": str(xml), "midi": str(mid), "bpm": op["bpm"],  # 'musescore it' picks it up
                                           "notes": len([n for n in notes if n[0] is not None])}
    return (f"{len([n for n in notes if n[0] is not None])} notes, {secs:.0f} s at {op['bpm']} bpm on {inst}: {mid} (plays in any player) and {xml} "
            f"(opens as sheet music in MuseScore) ({'checked: every note read back at its pitch and length' if ok else 'NOT the same when read back'}).")
