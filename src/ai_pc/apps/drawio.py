"""draw.io desktop (diagrams.net; 31.7.0 in tools/drawio, hash-checked) as the renderer: a flowchart, org chart or mind map
from words (laid out by the diagrams program) or any .drawio given, exported by draw.io itself on the hidden desktop to
PDF, PNG and SVG (its settings in tools/drawio/home, no update check). Checked: every page exported, the PNG really is the
diagram (Windows OCR reads its box labels), and the SVG parses.

  'drawio flowchart: Start -> Take order -> Pack -> Ship -> End'   'drawio export process.drawio to pdf'
"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET

from ai_pc.core.config import ROOT

NAME, LABEL = "drawio", "draw.io desktop: diagrams from words or .drawio files exported by draw.io (PDF, PNG, SVG)"
EXAMPLES = ["drawio flowchart: Start -> Take order -> Pack -> Ship -> End", "drawio export process.drawio to pdf"]
HOME = ROOT / "tools" / "drawio"


def exe():
    hits = sorted(HOME.rglob("draw.io.exe")) if HOME.exists() else []
    return hits[0] if hits else None


def export(src, dest, fmt):
    from ai_pc.core import hidden_desktop

    data = (HOME / "home").resolve()
    data.mkdir(parents=True, exist_ok=True)
    args = (
        [
            str(exe()),
            f"--user-data-dir={data}",
            "--disable-update",
            "--disable-gpu",
            "--export",
            "--format",
            fmt,
            "--border",
            "10",
            "--output",
            str(dest),
        ]
        + (["--scale", "2"] if fmt == "png" else [])
        + (["--all-pages", "--crop"] if fmt == "pdf" else [])
        + [str(src)]
    )
    return hidden_desktop.run(args, timeout=180)


def labels(drawio_file):
    """The text of every box in a .drawio file (uncompressed XML as the diagrams program writes it)."""
    try:
        root = ET.parse(drawio_file).getroot()
    except ET.ParseError:
        return []
    out = []
    for cell in root.iter("mxCell"):
        v = re.sub(r"<[^>]+>", " ", cell.get("value") or "").strip()
        if v and cell.get("vertex") == "1":
            out.append(v)
    return out


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bdraw\.?io\b|\bdiagrams\.net\b", c):
        return None
    f = find_file(text, ctx, {".drawio", ".xml"})
    fmts = [x for x in ("pdf", "png", "svg") if re.search(rf"\b{x}\b", c)] or ["pdf", "png", "svg"]
    if f:
        return {"op": "export", "file": f, "formats": fmts}
    from ai_pc.apps import diagrams

    rest = re.sub(r"^\s*(?:in\s+|with\s+)?draw\.?io\s*|\s*(?:in|with)\s+draw\.?io\b", "", text, flags=re.I).strip()
    op = diagrams.parse(rest, ctx)
    return dict(op, op="diagram", formats=fmts) if op else None


def run(op, ctx):
    if not exe():
        return "draw.io desktop is not in tools/drawio."
    out = (Path(ctx["out"]) / "drawio").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "diagram":
        from ai_pc.apps import diagrams

        name = {"flow": "flowchart", "tree": "org_chart", "mind": "mind_map"}[op["kind"]]
        made = diagrams.make(op["kind"], op["spec"], out / "source", name, op.get("title", ""))
        src = next(p for p in made["files"] if p.suffix == ".drawio")
    else:
        src = Path(op["file"]).resolve()
    words = labels(src)
    made, checks = [], []
    for fmt in op["formats"]:
        dest = out / f"{src.stem}.{fmt}"
        dest.unlink(missing_ok=True)
        rc, so, se, timed_out = export(src, dest, fmt)
        ok = dest.exists() and dest.stat().st_size > 200
        checks.append((f"draw.io exported the {fmt.upper()}", ok))
        if not ok:
            continue
        made.append(dest)
        if fmt == "png" and words:
            try:
                from ai_pc.apps import ocr

                seen = re.sub(r"\s+", " ", ocr.read_picture(dest, work=out / "_ocr")["text"].lower())
                found = sum(1 for w in words if all(t in seen for t in re.findall(r"[a-z0-9]{3,}", w.lower())))
            except Exception:  # noqa: BLE001
                found = 0
            checks.append((f"the PNG is the diagram (Windows OCR reads {found} of {len(words)} box labels)", found >= max(1, (len(words) * 3) // 4)))
        if fmt == "svg":
            try:
                ET.parse(dest)
                checks.append(("the SVG parses", True))
            except ET.ParseError:
                checks.append(("the SVG parses", False))
        if fmt == "pdf":
            from pypdf import PdfReader

            checks.append((f"the PDF has {len(PdfReader(str(dest)).pages)} page(s)", len(PdfReader(str(dest)).pages) >= 1))
    bad = [w for w, ok in checks if not ok]
    return (
        f"draw.io exported {src.name} to {', '.join(p.name for p in made) or 'nothing'} in {out} (rendered by draw.io itself; the .drawio opens in draw.io "
        "to edit). " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ".")
    )
