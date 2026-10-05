"""Checks on a drawing, made apart from the code that drew it: the DXF read back and audited, its rooms, labels,
doors, windows and dimensions compared with the plan; the plan's design rules; the printed sheet.

  checks = check(dxf_path, lay, files)     [{"ok", "what", "level": "fail" | "warn"}]
"""
import re
from pathlib import Path

import ezdxf

from .floorplan import BATH_MIN, INNER, KINDS, OUTER, unreachable
from .units import parse_len


def _c(ok, what, level="fail"):
    return {"ok": bool(ok), "what": what, "level": level}


def _floors(lay):
    return [lay] + ([lay["upper"]] if lay.get("upper") else [])


def design(lay):
    """The plan's rules: everyone can get everywhere, no room under its minimum, nothing overlaps or leaves the
    building, rooms that need daylight have it, the stairs line up from floor to floor."""
    out = []
    for fl in _floors(lay):
        name = fl.get("floor", "plan").lower()
        un = unreachable(fl, fl["doors"])
        out.append(_c(not un, f"{name}: every room can be reached from the {'stairs' if fl.get('floor') == 'FIRST FLOOR' else 'entrance'}"
                      + (f" (not: {', '.join(un)})" if un else "")))
        small = []
        for r in fl["rooms"]:
            mn = KINDS[r["kind"]][2]
            w, d = (r["x1"] - r["x0"]) / 12, (r["y1"] - r["y0"]) / 12
            if r["kind"] in ("stairs", "passage", "terrace"):
                continue
            if min(w, d) + 0.05 < min(mn) or max(w, d) + 0.05 < max(mn) * 0.9:
                small.append(f"{r['label']} {w:.1f}' x {d:.1f}'")
            bt = r.get("bath")
            if bt and (bt["w"] + 0.5 < BATH_MIN[0] or bt["d"] + 0.5 < BATH_MIN[1]):
                small.append(f"{r['label']} bath")
        out.append(_c(not small, f"{name}: no room under its minimum size" + (f" ({'; '.join(small)})" if small else "")))
        rooms = fl["rooms"]
        over = [(a["label"], b["label"]) for i, a in enumerate(rooms) for b in rooms[i + 1:]
                if a["x0"] < b["x1"] - 0.5 and b["x0"] < a["x1"] - 0.5 and a["y0"] < b["y1"] - 0.5 and b["y0"] < a["y1"] - 0.5]
        out.append(_c(not over, f"{name}: no two rooms overlap" + (f" ({over[:2]})" if over else "")))
        ex0, ey0, ex1, ey1 = fl["envelope"]
        outside = [r["label"] for r in rooms if r["x0"] < ex0 + OUTER - 0.5 or r["x1"] > ex1 - OUTER + 0.5 or r["y0"] < ey0 + OUTER - 0.5 or r["y1"] > ey1 - OUTER + 0.5]
        out.append(_c(not outside, f"{name}: every room is inside the walls" + (f" ({outside})" if outside else "")))
        dark = [r["label"] for r in rooms if r["kind"] == "bedroom" and not any(w["room"] == r["id"] and w["kind"] == "window" for w in fl["windows"])]
        out.append(_c(not dark, f"{name}: every bedroom has a window" + (f" (not: {', '.join(dark)})" if dark else ""), "warn"))
    if lay.get("upper"):
        a = next((r for r in lay["rooms"] if r["kind"] == "stairs"), None)
        b = next((r for r in lay["upper"]["rooms"] if r["kind"] == "stairs"), None)
        out.append(_c(a and b and all(abs(a[k] - b[k]) < 0.5 for k in ("x0", "x1", "y0", "y1")), "the stairs are in the same place on both floors"))
    W, D = lay["plot"]
    ex0, ey0, ex1, ey1 = lay["envelope"]
    out.append(_c(0 <= ex0 and ex1 <= W and 0 <= ey0 and ey1 <= D, f"the building stays inside the plot ({W / 12:.0f}' x {D / 12:.0f}')"))
    return out


def dxf_file(path, lay, plans=None):
    """The DXF read back: it opens and audits clean, its layers, walls, room outlines, labels, doors, windows and
    dimensions match the plan."""
    out = []
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as e:  # noqa: BLE001
        return [_c(False, f"the DXF does not open: {e}")]
    aud = doc.audit()
    out.append(_c(not aud.has_errors, f"the DXF opens and audits clean ({len(aud.errors)} errors, {len(aud.fixes)} fixed)"))
    out.append(_c(doc.header.get("$INSUNITS") == 1, "drawing units are inches (AutoCAD reads the scale right)"))
    msp = doc.modelspace()
    layers = {l.dxf.name for l in doc.layers}
    need = {"A-WALL", "A-WALL-FILL", "A-DOOR", "A-GLAZ", "A-TEXT", "A-DIMS", "A-SHEET", "A-TITLE"}
    out.append(_c(need <= layers, f"layers: {', '.join(sorted(need & layers))}" + (f" (missing {need - layers})" if need - layers else "")))
    walls = [e for e in msp.query("LWPOLYLINE[layer=='A-WALL']") if e.closed]
    out.append(_c(len(walls) >= 1 and len(msp.query("HATCH[layer=='A-WALL-FILL']")) >= 1, f"walls: {len(walls)} closed outline(s), filled"))
    areas = sorted(float(abs(_area([(p[0], p[1]) for p in e.get_points("xy")]))) / 144 for e in msp.query("LWPOLYLINE[layer=='A-AREA']"))
    want = sorted((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) / 144 for fl in _floors(lay) for r in fl["rooms"])
    off = [(round(a, 1), round(b, 1)) for a, b in zip(areas, want) if abs(a - b) > 0.1]
    same = len(areas) == len(want) and not off
    out.append(_c(same, f"{len(areas)} room outline(s) with the planned areas" + ("" if same else f" ({len(areas)} vs {len(want)}; {off[:3]})")))
    texts = " ".join([e.dxf.text for e in msp.query("TEXT")] + [e.plain_text() for e in msp.query("MTEXT")]).upper()
    if plans:  # each room's name written inside that room (the schedule's list does not count)
        marks = []
        for e in msp.query("TEXT MTEXT"):
            if e.dxftype() == "MTEXT":
                marks.append(("".join(e.plain_text().upper().split()), e.dxf.insert[0], e.dxf.insert[1]))
            else:
                pt = e.dxf.align_point if e.dxf.hasattr("align_point") and e.dxf.halign else e.dxf.insert
                marks.append(("".join(e.dxf.text.upper().split()), pt[0], pt[1]))
        missing = [r["label"] for fl in plans for r in fl["rooms"] if r["kind"] != "stairs" and not any(
            t == "".join(r["label"].split()) and r["x0"] - 1 <= x <= r["x1"] + 1 and r["y0"] - 1 <= y <= r["y1"] + 1 for t, x, y in marks)]
    else:
        flat = "".join(texts.split())  # names may be written on two lines
        missing = [r["label"] for fl in _floors(lay) for r in fl["rooms"] if r["kind"] != "stairs" and "".join(r["label"].split()) not in flat]
    out.append(_c(not missing, "every room is named on the drawing" + (f" (not: {', '.join(missing)})" if missing else "")))
    swings = len(msp.query("ARC[layer=='A-DOOR']"))
    doors = sum(1 for fl in _floors(lay) for d in fl["doors"] if d["kind"] != "open")
    out.append(_c(swings == doors, f"{swings} door swing(s) for {doors} door(s)"))
    glaz = len(msp.query("LINE[layer=='A-GLAZ']"))
    wins = sum(len(fl["windows"]) for fl in _floors(lay))
    out.append(_c(glaz >= wins * 5, f"{wins} window(s) drawn"))
    bad, n = [], 0
    for dim in msp.query("DIMENSION"):
        t = dim.dxf.get("text", "")
        if not t or t == "<>":
            continue
        n += 1
        try:
            meas = dim.get_measurement()
            told = parse_len(t.replace("½", ".5"))
        except Exception:  # noqa: BLE001
            bad.append(t)
            continue
        if abs(abs(meas) - told) > 0.6:
            bad.append(f"{t} measures {meas:.1f}\"")
    out.append(_c(n > 0 and not bad, f"{n} dimension(s), each one's text equal to the distance it measures" + (f" (not: {bad[:3]})" if bad else "")))
    return out


def sheet(files, sheet_info):
    """The printed sheet: the PDF is the paper size, the preview is a drawing (not blank, not black)."""
    out = []
    if files.get("pdf"):
        from pypdf import PdfReader
        r = PdfReader(files["pdf"])
        box = r.pages[0].mediabox
        w, h = float(box.width) / 72 * 25.4, float(box.height) / 72 * 25.4
        pw, ph = sheet_info["paper_mm"]
        out.append(_c(abs(w - pw) < 1.5 and abs(h - ph) < 1.5 and len(r.pages) == 1, f"PDF: one page {w:.0f} x {h:.0f} mm ({sheet_info['paper']} at 1:{sheet_info['scale']})"))
    if files.get("png"):
        import numpy as np
        from PIL import Image
        g = np.asarray(Image.open(files["png"]).convert("L"), dtype=np.float32) / 255
        ink = float((g < 0.6).mean())
        out.append(_c(0.01 < ink < 0.35, f"preview: a drawing ({ink:.1%} ink)"))
    return out


def check(path, lay, files=None, sheet_info=None):
    out = design(lay) + dxf_file(path, lay, (sheet_info or {}).get("plans"))
    if files and sheet_info:
        out += sheet(files, sheet_info)
    return out


def _area(pts):
    return sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts))) / 2


def text_of(checks):
    bad = [c for c in checks if not c["ok"] and c["level"] == "fail"]
    warn = [c for c in checks if not c["ok"] and c["level"] == "warn"]
    return f"checked {len(checks) - len(bad) - len(warn)}/{len(checks)}" + (f"; not right: {'; '.join(c['what'] for c in bad[:3])}" if bad else "") + \
        (f"; to look at: {'; '.join(c['what'] for c in warn[:2])}" if warn else "")
