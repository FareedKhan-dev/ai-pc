"""MuseScore Studio (4.7.5 Portable in tools/musescore-portable, unpacked by 7-Zip, signed by MuseScore's company): a melody
from words ('C4 D4 E4/8 ... at 90 bpm on violin'), a MusicXML or MIDI file, or the melody just made in this chat, turned
into MuseScore's own .mscz, sheet music as PDF and PNG, and an MP3 played by MuseScore's instruments. MuseScore runs on a
hidden desktop (src/ai_pc/core/hidden_desktop.py): nothing appears on the screen, and its settings stay in its own folder.
Checked by MuseScore's own report on the score (notes, measures, length), the PDF's pages and title, and the MP3's length.

  'musescore: C4 D4 E4 F4 G4/2 G4/2 at 100 bpm on piano'   'sheet music pdf of song.musicxml'   'musescore it'
"""

import json
import re
import subprocess
import zipfile
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "musescore", "MuseScore: sheet music PDF/PNG, .mscz and MP3 from melodies, MusicXML or MIDI (runs hidden)"
EXAMPLES = ["musescore 'Little Song': C4 D4 E4 F4 G4/2 G4/2 at 100 bpm on piano", "sheet music pdf of song.musicxml", "musescore it"]
HOME = ROOT / "tools" / "musescore-portable"
EXE = HOME / "App" / "MuseScore" / "bin" / "MuseScore4.exe"
SCORES = {".musicxml", ".mxl", ".xml", ".mid", ".midi", ".mscz"}
USER_DIRS = {
    "myPlugins": "Plugins",
    "mySoundfonts": "SoundFonts",
    "myStyles": "Styles",
    "myTemplates": "Templates",
    "myScores": "Scores",
    "myMusicFonts": "MusicFonts",
    "myVSTs": "VST",
    "userInstruments": "Instruments",
}


def setup():
    """MuseScore's user folders (normally in Documents\\MuseScore4) kept inside its own portable folder."""
    user = HOME / "Data" / "user"
    ini = HOME / "Data" / "settings" / "MuseScore" / "MuseScore4.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[application]"] + [f"paths\\{k}={(user / v).resolve().as_posix()}" for k, v in USER_DIRS.items()]
    for v in USER_DIRS.values():
        (user / v).mkdir(parents=True, exist_ok=True)
    text = ini.read_text(encoding="utf-8") if ini.exists() else ""
    if any(ln not in text for ln in lines):
        ini.write_text("\n".join(lines) + "\n", encoding="utf-8")


def musescore(*args, timeout=180):
    from ai_pc.core import hidden_desktop

    setup()
    return hidden_desktop.run([str(EXE), *map(str, args)], timeout=timeout)


def mp3_seconds(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bmuse\s*score\b|\bsheet\s+music\b|\bnotation\b", c):
        return None
    f = find_file(text, ctx, SCORES)
    if f:
        return {"op": "score", "file": f}
    m = re.match(r"^\s*(?:muse\s*score|sheet\s+music)\s*(?:'([^']*)')?\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        from ai_pc.apps import music

        op = music.parse(f"melody{(' ' + repr(m.group(1))) if m.group(1) else ''}: {m.group(2)}", ctx)
        if op:
            return {"op": "score", "melody": op}
    last = (ctx.get("memo") or {}).get("music")
    if last and re.search(r"\b(?:it|this|that|the\s+melody|the\s+song|the\s+tune)\b", c):
        return {"op": "score", "file": last["musicxml"], "bpm": last["bpm"], "notes": last["notes"]}
    return None


def run(op, ctx):
    if not EXE.exists():
        return "MuseScore Portable is not in tools/musescore-portable."
    out = Path(ctx["out"]) / "musescore"
    out.mkdir(parents=True, exist_ok=True)
    want_secs = want_notes = None
    if op.get("melody"):
        from ai_pc.apps import music

        mel = op["melody"]
        notes = music.read(mel["notes"])
        inst = mel["instrument"] if mel["instrument"] in music.PROGRAMS else "piano"
        stem = re.sub(r"[^\w-]+", "_", mel["title"])
        src = out / f"{stem}.musicxml"
        src.write_text(music.musicxml(notes, mel["title"], mel["bpm"], inst), encoding="utf-8")
        want_notes = len([n for n in notes if n[0] is not None])
        want_secs = sum(q for _, q, _ in notes) * 60 / mel["bpm"]
        title = mel["title"]
    else:
        src = Path(op["file"]).resolve()
        stem = re.sub(r"[^\w-]+", "_", src.stem)
        title = src.stem
        if op.get("notes"):
            want_notes, want_secs = op["notes"], None
    src = src.resolve()
    files = {ext: (out / f"{stem}.{ext}").resolve() for ext in ("mscz", "pdf", "mp3", "png")}
    for p in list(files.values()) + list(out.glob(f"{stem}-*.png")):
        p.unlink(missing_ok=True)
    problems = []
    job = out / f"{stem}.job.json"  # one MuseScore start makes the score, PDF and PNG; the MP3 gets its own (in a batch job MP3 export crashed)
    job.write_text(json.dumps([{"in": src.as_posix(), "out": [files[e].as_posix() for e in ("mscz", "pdf", "png")]}]), encoding="utf-8")
    for what, args in (("score, PDF and PNG", ("-r", "200", "-j", job.resolve())), ("MP3", ("-o", files["mp3"], src))):
        rc, so, se, timed_out = musescore(*args, timeout=300)
        if timed_out or rc != 0:
            problems.append(f"{what}: {'timed out' if timed_out else f'exit {rc}'} {(se or so).strip()[-200:]}")
    job.unlink(missing_ok=True)
    rc, meta_out, _, _ = musescore("--score-meta", files["mscz"], timeout=120)
    try:
        meta = json.loads(meta_out[meta_out.find("{") :]) if "{" in meta_out else {}
    except ValueError:
        meta = {}
    meta = meta.get("metadata", meta)
    pngs = sorted(out.glob(f"{stem}-*.png")) or ([files["png"]] if files["png"].exists() else [])
    from pypdf import PdfReader

    pdf_pages = len(PdfReader(str(files["pdf"])).pages) if files["pdf"].exists() else 0
    pdf_text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in PdfReader(str(files["pdf"])).pages)) if pdf_pages else ""
    secs = mp3_seconds(files["mp3"]) if files["mp3"].exists() else None
    notes_in_score = None
    if files["mscz"].exists():
        with zipfile.ZipFile(files["mscz"]) as z:
            mscx = next((n for n in z.namelist() if n.endswith(".mscx")), None)
            notes_in_score = z.read(mscx).decode("utf-8", "replace").count("<Note>") if mscx else None
    checks = [
        (
            "MuseScore made all four files (.mscz, PDF, MP3, PNG), unseen",
            not problems and all(p.exists() for p in (files["mscz"], files["pdf"], files["mp3"])) and bool(pngs),
        ),
        ("the sheet music PDF has its pages and the title", pdf_pages >= 1 and (title.lower() in pdf_text.lower() if op.get("melody") else True)),
    ]
    if want_notes is not None:
        checks.append((f"MuseScore's score holds all {want_notes} notes", notes_in_score == want_notes))
    if want_secs:
        checks.append((f"the MP3 lasts as long as the music ({want_secs:.1f} s)", secs is not None and want_secs - 0.5 <= secs <= want_secs + 3.5))
    bad = [w for w, ok in checks if not ok]
    memo = ctx.setdefault("memo", {})
    memo["musescore"] = {"mscz": str(files["mscz"]), "pdf": str(files["pdf"]), "mp3": str(files["mp3"])}
    info = []
    if meta:
        info.append(
            f"{meta.get('measures', '?')} measures, {meta.get('pages', pdf_pages)} page(s)"
            + (f", {meta['duration']} s by MuseScore" if meta.get("duration") else "")
        )
    return (
        (
            f"MuseScore score '{title}': {files['mscz'].name} (opens in MuseScore), {files['pdf'].name} (sheet music, {pdf_pages} page(s)), "
            f"{files['mp3'].name} ({secs:.1f} s)"
            if secs
            else f"MuseScore score '{title}': {files['mscz'].name}, {files['pdf'].name}"
        )
        + (f", {len(pngs)} PNG page(s)" if pngs else "")
        + f" in {out}. "
        + (" ".join(info) + ". " if info else "")
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad
            else "NOT right: " + "; ".join(bad) + (" " + "; ".join(problems) if problems else "") + "."
        )
    )
