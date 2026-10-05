"""Engineering part drawings in millimetres: a plate (rectangle with rounded or chamfered corners, holes in patterns,
slots) and a flange (a ring with a bolt circle). A dimensioned drawing (front view, edge view with hidden lines,
centre lines, hole callouts, title block, standard scale) and a clean 1:1 cut file for a laser or CNC shop.

  spec = {"kind": "plate", "w": 200, "h": 100, "t": 10, "corner": {"r": 10}, "holes": [{"d": 12, "pattern": "corners", "e": 20}]}
  spec = {"kind": "flange", "od": 150, "id": 60, "pcd": 110, "n": 6, "hole_d": 14, "t": 12}
  doc, sheet = part_drawing(spec);  cut = cut_file(spec);  checks = part_checks(spec)
"""
import datetime as dt
import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

PAPER = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420)}
SCALES = [(5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20)]  # (paper, real)
MATERIALS = {"ms": "Mild steel (MS)", "mild steel": "Mild steel (MS)", "steel": "Mild steel (MS)", "ss": "Stainless steel 304", "stainless": "Stainless steel 304",
             "aluminium": "Aluminium 6061", "aluminum": "Aluminium 6061", "brass": "Brass", "acrylic": "Acrylic", "wood": "MDF / plywood", "mdf": "MDF"}


class PartError(Exception):
    pass


def holes_of(spec):
    """Every hole as {"x", "y", "d"} (mm from the part's bottom-left corner; a flange's from its centre)."""
    out = []
    if spec["kind"] == "flange":
        n, r = int(spec["n"]), spec["pcd"] / 2
        start = spec.get("start_deg", 90 if n % 2 == 0 else 90)
        for k in range(n):
            a = math.radians(start + 360 * k / n)
            out.append({"x": r * math.cos(a), "y": r * math.sin(a), "d": spec["hole_d"], "group": "bolt"})
        return out
    W, H = spec["w"], spec["h"]
    for g, h in enumerate(spec.get("holes", [])):
        d, p = h["d"], h.get("pattern", "at")
        if p == "corners":
            e = h.get("e", max(d * 1.5, 10))
            ex, ey = h.get("ex", e), h.get("ey", e)
            pts = [(ex, ey), (W - ex, ey), (W - ex, H - ey), (ex, H - ey)]
        elif p == "center":
            pts = [(W / 2, H / 2)]
        elif p == "grid":
            nx, ny = int(h.get("nx", 2)), int(h.get("ny", 2))
            ex, ey = h.get("ex", h.get("e", 20)), h.get("ey", h.get("e", 20))
            xs = [ex + (W - 2 * ex) * i / max(nx - 1, 1) for i in range(nx)] if nx > 1 else [W / 2]
            ys = [ey + (H - 2 * ey) * j / max(ny - 1, 1) for j in range(ny)] if ny > 1 else [H / 2]
            pts = [(x, y) for y in ys for x in xs]
        elif p == "row":
            n = int(h.get("n", 3))
            ex = h.get("ex", h.get("e", 20))
            y = h.get("y", H / 2)
            pts = [(ex + (W - 2 * ex) * i / max(n - 1, 1), y) for i in range(n)]
        else:
            pts = [(h["x"], h["y"])]
        out += [{"x": x, "y": y, "d": d, "group": g} for x, y in pts]
    return out


def _outline(msp, spec, ox, oy, layer):
    W, H = spec["w"], spec["h"]
    c = spec.get("corner") or {}
    if c.get("r"):
        r = min(c["r"], W / 2 - 0.1, H / 2 - 0.1)
        b = math.tan(math.radians(90) / 4)  # a quarter circle as a polyline bulge
        pts = [(ox + r, oy, 0, 0, 0), (ox + W - r, oy, 0, 0, b), (ox + W, oy + r, 0, 0, 0), (ox + W, oy + H - r, 0, 0, b), (ox + W - r, oy + H, 0, 0, 0),
               (ox + r, oy + H, 0, 0, b), (ox, oy + H - r, 0, 0, 0), (ox, oy + r, 0, 0, b)]
        msp.add_lwpolyline(pts, format="xyseb", close=True, dxfattribs={"layer": layer})
    elif c.get("c"):
        k = min(c["c"], W / 2 - 0.1, H / 2 - 0.1)
        msp.add_lwpolyline([(ox + k, oy), (ox + W - k, oy), (ox + W, oy + k), (ox + W, oy + H - k), (ox + W - k, oy + H), (ox + k, oy + H), (ox, oy + H - k), (ox, oy + k)],
                           close=True, dxfattribs={"layer": layer})
    else:
        msp.add_lwpolyline([(ox, oy), (ox + W, oy), (ox + W, oy + H), (ox, oy + H)], close=True, dxfattribs={"layer": layer})


def _new(scale_txt):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    doc.header["$MEASUREMENT"] = 1
    for name, color, lw in (("CUT", 7, 50), ("HIDDEN", 8, 25), ("CENTER", 1, 18), ("DIMS", 7, 18), ("TEXT", 7, 25), ("SHEET", 7, 35), ("TITLE", 7, 25)):
        doc.layers.add(name, color=color, lineweight=lw)
    doc.layers.get("HIDDEN").dxf.linetype = "DASHED"
    doc.layers.get("CENTER").dxf.linetype = "CENTER"
    doc.styles.add("ISO", font="arial.ttf")
    doc.styles.add("ISOB", font="arialbd.ttf")
    return doc


def _dimstyle(doc, k):
    """Dimension sizes for the paper at drawing scale k (paper mm per real mm)."""
    ds = doc.dimstyles.new(f"ISO{k:g}".replace(".", "_"))
    u = 1 / k
    ds.dxf.dimtxt = 3.0 * u
    ds.dxf.dimasz = 2.5 * u
    ds.dxf.dimexo = 1.0 * u
    ds.dxf.dimexe = 1.5 * u
    ds.dxf.dimgap = 0.8 * u
    ds.dxf.dimtad = 1
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimdec = 1
    ds.dxf.dimzin = 8  # no trailing zeros: 20 not 20.0
    ds.dxf.dimtxsty = "ISO"
    return ds.dxf.name


def _fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def part_drawing(spec, paper=None):
    W = spec["od"] if spec["kind"] == "flange" else spec["w"]
    H = spec["od"] if spec["kind"] == "flange" else spec["h"]
    t = spec["t"]
    paper = paper or "A4"
    pw, ph = PAPER[paper]
    area_w, area_h = pw - 20 - 10 - 20, ph - 20 - 32 - 30  # margins, the title block, room for dimensions
    for num, den in SCALES:
        k = num / den
        if (W + t + 40) * k <= area_w and (H + 20) * k <= area_h:
            break
    else:
        if paper != "A2":
            return part_drawing(spec, "A3" if paper == "A4" else "A2")
    u = 1 / k
    doc = _new(f"{num}:{den}")
    msp = doc.modelspace()
    style = _dimstyle(doc, k)
    gap0 = 25 * u
    cb = (-2 * 9 * u - 12 * u, -3.4 * 9 * u - 8 * u, W + gap0 + t + 12 * u, H + 16 * u)  # the views with their dimensions and labels
    fw, fh = (pw - 30) * u, (ph - 20) * u
    room_y0 = 32 * u + 4 * u  # above the title block
    fx0 = (cb[0] + cb[2]) / 2 - fw / 2
    fy0 = (cb[1] + cb[3]) / 2 - (room_y0 + fh) / 2
    frame = (fx0, fy0, fx0 + fw, fy0 + fh)
    # the front view at (0, 0); the edge view to its right (third-angle projection)
    gap = 25 * u
    if spec["kind"] == "flange":
        R, r_in = spec["od"] / 2, spec["id"] / 2
        cx, cy = R, R
        msp.add_circle((cx, cy), R, dxfattribs={"layer": "CUT"})
        msp.add_circle((cx, cy), r_in, dxfattribs={"layer": "CUT"})
        msp.add_circle((cx, cy), spec["pcd"] / 2, dxfattribs={"layer": "CENTER", "ltscale": u * 0.4})
        hs = [dict(h, x=h["x"] + cx, y=h["y"] + cy) for h in holes_of(spec)]
    else:
        _outline(msp, spec, 0, 0, "CUT")
        hs = holes_of(spec)
        cx, cy = W / 2, H / 2
    for h in hs:
        msp.add_circle((h["x"], h["y"]), h["d"] / 2, dxfattribs={"layer": "CUT"})
        ext = h["d"] / 2 + 2.5 * u
        msp.add_line((h["x"] - ext, h["y"]), (h["x"] + ext, h["y"]), dxfattribs={"layer": "CENTER", "ltscale": u * 0.25})
        msp.add_line((h["x"], h["y"] - ext), (h["x"], h["y"] + ext), dxfattribs={"layer": "CENTER", "ltscale": u * 0.25})
    for sl in spec.get("slots", []):
        x, y, ln, wd = sl["x"], sl["y"], sl["l"], sl["w"]
        b = 1.0
        msp.add_lwpolyline([(x - ln / 2 + wd / 2, y - wd / 2, 0, 0, 0), (x + ln / 2 - wd / 2, y - wd / 2, 0, 0, b), (x + ln / 2 - wd / 2, y + wd / 2, 0, 0, 0),
                            (x - ln / 2 + wd / 2, y + wd / 2, 0, 0, b)], format="xyseb", close=True, dxfattribs={"layer": "CUT"})
    ex = W + gap
    msp.add_lwpolyline([(ex, 0), (ex + t, 0), (ex + t, H), (ex, H)], close=True, dxfattribs={"layer": "CUT"})
    for yy in sorted({round(h["y"], 3) for h in hs}):  # holes seen edge-on: hidden lines
        d = next(h["d"] for h in hs if abs(h["y"] - yy) < 1e-3)
        for s in (-1, 1):
            msp.add_line((ex, yy + s * d / 2), (ex + t, yy + s * d / 2), dxfattribs={"layer": "HIDDEN", "ltscale": u * 0.2})
        msp.add_line((ex - 2 * u, yy), (ex + t + 2 * u, yy), dxfattribs={"layer": "CENTER", "ltscale": u * 0.2})
    if spec["kind"] == "flange":
        for s in (-1, 1):
            msp.add_line((ex, cy + s * spec["id"] / 2), (ex + t, cy + s * spec["id"] / 2), dxfattribs={"layer": "HIDDEN", "ltscale": u * 0.2})
    # dimensions
    off = 9 * u

    def lin(p1, p2, base, angle=0, text=None):
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=style, text=text or "<>", dxfattribs={"layer": "DIMS"})
        d.render()
    if spec["kind"] == "flange":
        lin((ex, 0), (ex + t, 0), (ex, -off))
        lin((0, cy), (W, cy), (0, -off), text=f"%%c{_fmt(spec['od'])}")
        msp.add_text(f"%%c{_fmt(spec['id'])} BORE", dxfattribs={"layer": "TEXT", "height": 3.0 * u, "style": "ISO"}).set_placement(
            (cx, cy - 4 * u), align=TextEntityAlignment.TOP_CENTER)
        hs[0]
        msp.add_text(f"{spec['n']}x %%c{_fmt(spec['hole_d'])} THRU ON %%c{_fmt(spec['pcd'])} PCD, EQUALLY SPACED",
                     dxfattribs={"layer": "TEXT", "height": 3.0 * u, "style": "ISO"}).set_placement((cx, H + 8 * u), align=TextEntityAlignment.BOTTOM_CENTER)
    else:
        lin((0, 0), (W, 0), (0, -off * 2))
        lin((0, 0), (0, H), (-off * 2, 0), angle=90)
        lin((ex, 0), (ex + t, 0), (ex, -off))
        xs = sorted({round(h["x"], 3) for h in hs})
        ys = sorted({round(h["y"], 3) for h in hs})
        chain_x = [0] + xs
        for a, b in zip(chain_x, chain_x[1:]):
            if b - a > 0.05:
                lin((a, 0), (b, 0), (0, -off))
        chain_y = [0] + ys
        for a, b in zip(chain_y, chain_y[1:]):
            if b - a > 0.05:
                lin((0, a), (0, b), (-off, 0), angle=90)
        groups = {}
        for h in hs:
            groups.setdefault((h["group"], h["d"]), []).append(h)
        for (g, dd), hh in groups.items():
            top = max(hh, key=lambda q: (q["y"], q["x"]))
            msp.add_text(f"{len(hh)}x %%c{_fmt(dd)} THRU" if len(hh) > 1 else f"%%c{_fmt(dd)} THRU", dxfattribs={"layer": "TEXT", "height": 3.0 * u, "style": "ISO"}).set_placement(
                (top["x"] + dd / 2 + 2 * u, top["y"] + dd / 2 + 2 * u), align=TextEntityAlignment.BOTTOM_LEFT)
        c = spec.get("corner") or {}
        if c.get("r"):
            msp.add_text(f"R{_fmt(c['r'])} TYP.", dxfattribs={"layer": "TEXT", "height": 3.0 * u, "style": "ISO"}).set_placement((W + 1.5 * u, -1.5 * u),
                                                                                                                        align=TextEntityAlignment.TOP_LEFT)
        elif c.get("c"):
            msp.add_text(f"{_fmt(c['c'])} x 45° CHAMFER TYP.", dxfattribs={"layer": "TEXT", "height": 3.0 * u, "style": "ISO"}).set_placement(
                (W + 1.5 * u, -1.5 * u), align=TextEntityAlignment.TOP_LEFT)
    msp.add_text("FRONT VIEW", dxfattribs={"layer": "TEXT", "height": 3.5 * u, "style": "ISOB"}).set_placement((W / 2, -off * 3.4), align=TextEntityAlignment.TOP_CENTER)
    msp.add_text("SIDE VIEW", dxfattribs={"layer": "TEXT", "height": 3.5 * u, "style": "ISOB"}).set_placement((ex + t / 2, -off * 3.4), align=TextEntityAlignment.TOP_CENTER)
    # sheet and title block
    msp.add_lwpolyline([(frame[0], frame[1]), (frame[2], frame[1]), (frame[2], frame[3]), (frame[0], frame[3])], close=True,
                       dxfattribs={"layer": "SHEET", "const_width": 0.5 * u})
    tw, th_ = 150 * u, 32 * u
    tx0, ty0 = frame[2] - tw, frame[1]
    msp.add_lwpolyline([(tx0, ty0), (frame[2], ty0), (frame[2], ty0 + th_), (tx0, ty0 + th_)], close=True, dxfattribs={"layer": "TITLE"})
    for yy in (8, 16, 24):
        msp.add_line((tx0, ty0 + yy * u), (frame[2], ty0 + yy * u), dxfattribs={"layer": "TITLE"})
    msp.add_line((tx0 + 75 * u, ty0), (tx0 + 75 * u, ty0 + 24 * u), dxfattribs={"layer": "TITLE"})
    mat = MATERIALS.get(str(spec.get("material", "ms")).lower(), str(spec.get("material", "Mild steel (MS)")))
    rows = [(spec.get("name") or ("FLANGE" if spec["kind"] == "flange" else "PLATE"), 4.0, tx0 + 3 * u, ty0 + 28 * u, True),
            (f"Material: {mat}", 2.6, tx0 + 3 * u, ty0 + 20 * u, False), (f"Thickness: {_fmt(t)} mm", 2.6, tx0 + 78 * u, ty0 + 20 * u, False),
            (f"Scale {num}:{den} on {paper}   Units: mm", 2.4, tx0 + 3 * u, ty0 + 12 * u, False),
            ("Tolerance unless stated: ±0.5 mm", 2.4, tx0 + 78 * u, ty0 + 12 * u, False),
            (f"Date {dt.date.today():%d %b %Y}", 2.2, tx0 + 3 * u, ty0 + 4 * u, False), ("Drawn by AI PC (ezdxf)", 2.2, tx0 + 78 * u, ty0 + 4 * u, False)]
    for text, hmm, x, y, bold in rows:
        msp.add_text(text, dxfattribs={"layer": "TITLE", "height": hmm * u, "style": "ISOB" if bold else "ISO"}).set_placement((x, y), align=TextEntityAlignment.MIDDLE_LEFT)
    return doc, {"paper": paper, "paper_mm": (pw, ph), "scale_ratio": (num, den), "scale": 25.4 / k, "frame": frame}


def cut_file(spec):
    """Only what a laser or CNC cuts, at 1:1 in millimetres: the outline and the holes (and slots) on layer CUT."""
    doc = _new("1:1")
    msp = doc.modelspace()
    if spec["kind"] == "flange":
        R = spec["od"] / 2
        msp.add_circle((R, R), R, dxfattribs={"layer": "CUT"})
        msp.add_circle((R, R), spec["id"] / 2, dxfattribs={"layer": "CUT"})
        for h in holes_of(spec):
            msp.add_circle((h["x"] + R, h["y"] + R), h["d"] / 2, dxfattribs={"layer": "CUT"})
    else:
        _outline(msp, spec, 0, 0, "CUT")
        for h in holes_of(spec):
            msp.add_circle((h["x"], h["y"]), h["d"] / 2, dxfattribs={"layer": "CUT"})
        for sl in spec.get("slots", []):
            x, y, ln, wd = sl["x"], sl["y"], sl["l"], sl["w"]
            msp.add_lwpolyline([(x - ln / 2 + wd / 2, y - wd / 2, 0, 0, 0), (x + ln / 2 - wd / 2, y - wd / 2, 0, 0, 1.0), (x + ln / 2 - wd / 2, y + wd / 2, 0, 0, 0),
                                (x - ln / 2 + wd / 2, y + wd / 2, 0, 0, 1.0)], format="xyseb", close=True, dxfattribs={"layer": "CUT"})
    return doc


def part_checks(spec):
    """Design rules for a cut part: holes inside the material with enough edge (at least the hole's diameter; 1.5x
    for steel is better), no two holes too close, a flange's bolt holes clear of its bore and rim."""
    out = []
    hs = holes_of(spec)
    if spec["kind"] == "flange":
        R, r_in, pr = spec["od"] / 2, spec["id"] / 2, spec["pcd"] / 2
        d = spec["hole_d"]
        rim = R - (pr + d / 2)
        web = (pr - d / 2) - r_in
        out.append({"ok": rim >= d * 0.75, "what": f"bolt holes {rim:.1f} mm from the rim", "level": "fail"})
        out.append({"ok": web >= d * 0.5, "what": f"bolt holes {web:.1f} mm clear of the bore", "level": "fail"})
        chord = 2 * pr * math.sin(math.pi / spec["n"]) - d
        out.append({"ok": chord >= d * 0.5, "what": f"{chord:.1f} mm of metal between neighbouring bolt holes", "level": "fail"})
        out.append({"ok": spec["id"] < spec["pcd"] < spec["od"], "what": "bore < bolt circle < outside diameter", "level": "fail"})
        return out
    W, H = spec["w"], spec["h"]
    edge = [min(h["x"], W - h["x"], h["y"], H - h["y"]) - h["d"] / 2 for h in hs]
    if hs:
        worst = min(range(len(hs)), key=lambda i: edge[i] / hs[i]["d"])
        e, d = edge[worst], hs[worst]["d"]
        out.append({"ok": e > 0, "what": f"every hole inside the plate (closest {e:.1f} mm of metal to an edge)", "level": "fail"})
        out.append({"ok": e >= d, "what": f"edge distance {e:.1f} mm for a {_fmt(d)} mm hole (rule: at least 1x the hole; 1.5x for steel is better)",
                    "level": "warn" if e > 0 else "fail"})
        gaps = [math.hypot(a["x"] - b["x"], a["y"] - b["y"]) - (a["d"] + b["d"]) / 2 for i, a in enumerate(hs) for b in hs[i + 1:]]
        if gaps:
            g = min(gaps)
            out.append({"ok": g >= 0.5 * min(h["d"] for h in hs), "what": f"holes {g:.1f} mm apart at the closest", "level": "fail"})
    c = spec.get("corner") or {}
    if c.get("r"):
        out.append({"ok": c["r"] < min(W, H) / 2, "what": f"corner radius R{_fmt(c['r'])} fits", "level": "fail"})
    out.append({"ok": spec["t"] > 0 and W > 0 and H > 0, "what": f"{_fmt(W)} x {_fmt(H)} x {_fmt(spec['t'])} mm", "level": "fail"})
    return out
