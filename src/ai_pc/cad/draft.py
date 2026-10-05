"""A house plan drawn as DXF the way an architect's office would: walls as one filled outline with openings cut, doors
with their swing, windows, stairs, furniture as blocks, room names with clear sizes, chain dimensions in feet and
inches, the plot line and the road, a north arrow, a room schedule, a title block and an A3 sheet at a set scale.

  doc, sheet = drawing(lay)        lay from floorplan.plan(); a second floor is drawn beside the first
  doc.saveas("plan.dxf")           AutoCAD, BricsCAD, LibreCAD and DraftSight open it; 1 drawing unit = 1 inch
"""
import datetime as dt
import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ai_pc.cad.floorplan import INNER, OUTER, summary
from ai_pc.cad.units import ft_in, marla_of

LAYERS = {"A-WALL": (7, 0.50), "A-WALL-FILL": (8, 0.13), "A-DOOR": (1, 0.25), "A-GLAZ": (5, 0.25), "A-FURN": (8, 0.13), "A-STAIR": (7, 0.25),
          "A-TEXT": (7, 0.25), "A-DIMS": (7, 0.18), "A-PLOT": (3, 0.25), "A-SHEET": (7, 0.35), "A-TITLE": (7, 0.25), "A-AREA": (9, 0.0)}
SCALES = [50, 75, 100, 125, 150, 200, 250, 300]
PAPER = {"A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A4": (297, 210)}


def _mm(scale):
    """Drawing units (inches) per millimetre of paper at 1:scale."""
    return scale / 25.4


def _new():
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 1  # inches
    doc.header["$MEASUREMENT"] = 0
    doc.header["$LUNITS"] = 4  # architectural
    for name, (color, lw) in LAYERS.items():
        doc.layers.add(name, color=color, lineweight=int(lw * 100) if lw else -3)
    doc.layers.get("A-AREA").off()  # room outlines for software, not for the print
    doc.styles.add("ARCH", font="arial.ttf")
    doc.styles.add("ARCHB", font="arialbd.ttf")
    _blocks(doc)
    return doc


# ------------------------------------------------------------------------------------------------ walls: one outline
def union(rects, holes=()):
    """The outline of a union of axis-aligned rectangles minus holes, as closed loops of points (exact: the plane is cut
    at every rectangle edge and the filled cells' borders are traced)."""
    xs = sorted({v for r in list(rects) + list(holes) for v in (r[0], r[2])})
    ys = sorted({v for r in list(rects) + list(holes) for v in (r[1], r[3])})
    nx, ny = len(xs) - 1, len(ys) - 1
    fill = [[False] * ny for _ in range(nx)]
    for i in range(nx):
        cx = (xs[i] + xs[i + 1]) / 2
        for j in range(ny):
            cy = (ys[j] + ys[j + 1]) / 2
            if any(r[0] < cx < r[2] and r[1] < cy < r[3] for r in rects) and not any(h[0] < cx < h[2] and h[1] < cy < h[3] for h in holes):
                fill[i][j] = True

    def f(i, j):
        return 0 <= i < nx and 0 <= j < ny and fill[i][j]
    edges = {}
    for i in range(nx):
        for j in range(ny):
            if not fill[i][j]:
                continue
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            if not f(i, j - 1):
                edges.setdefault((x0, y0), []).append((x1, y0))
            if not f(i + 1, j):
                edges.setdefault((x1, y0), []).append((x1, y1))
            if not f(i, j + 1):
                edges.setdefault((x1, y1), []).append((x0, y1))
            if not f(i - 1, j):
                edges.setdefault((x0, y1), []).append((x0, y0))
    loops = []
    while edges:
        start = next(iter(edges))
        loop, p = [start], start
        while True:
            nxt = edges[p].pop()
            if not edges[p]:
                del edges[p]
            if nxt == start:
                break
            loop.append(nxt)
            p = nxt
            if p not in edges:
                break
        pts = []
        n = len(loop)
        for k in range(n):  # drop points in the middle of a straight run
            a, b, c = loop[k - 1], loop[k], loop[(k + 1) % n]
            if not ((a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1])):
                pts.append(b)
        if len(pts) >= 4:
            loops.append(pts)
    return loops


def _area(pts):
    return sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts))) / 2


def _wall_rects(lay):
    """Every piece of wall as a rectangle: the outside walls, the walls between bands, between rooms, around baths."""
    ex0, ey0, ex1, ey1 = lay["envelope"]
    rooms = lay["rooms"]
    front = [(ex0, ey0, ex1, ey0 + OUTER)]
    for r in rooms:  # a car porch (or a terrace) is open at the front: the front wall stops at its sides
        if r["kind"] in ("porch", "terrace") and "front" in r.get("outside", []):
            cut = []
            for f in front:
                if f[2] <= r["x0"] or f[0] >= r["x1"]:
                    cut.append(f)
                    continue
                if f[0] < r["x0"]:
                    cut.append((f[0], f[1], r["x0"], f[3]))
                if f[2] > r["x1"]:
                    cut.append((r["x1"], f[1], f[2], f[3]))
            front = cut
    rects = front + [(ex0, ey1 - OUTER, ex1, ey1), (ex0, ey0, ex0 + OUTER, ey1), (ex1 - OUTER, ey0, ex1, ey1)]
    for a in rooms:
        for b in rooms:
            if a is b:
                continue
            if abs(a["x1"] + INNER - b["x0"]) < 0.6:  # side by side: the wall between them over their common height
                lo, hi = max(a["y0"], b["y0"]), min(a["y1"], b["y1"])
                if hi > lo:
                    rects.append((a["x1"], lo - INNER, b["x0"], hi + INNER))
            if abs(a["y1"] + INNER - b["y0"]) < 0.6:  # one behind the other
                lo, hi = max(a["x0"], b["x0"]), min(a["x1"], b["x1"])
                if hi > lo:
                    rects.append((lo - INNER, a["y1"], hi + INNER, b["y0"]))
    for r in rooms:
        bt = r.get("bath")
        if bt:
            if bt["side"] == "right":
                rects.append((bt["x0"] - INNER, bt["y0"] - (INNER if bt["end"] == "rear" else 0), bt["x0"], bt["y1"] + (INNER if bt["end"] == "front" else 0)))
            else:
                rects.append((bt["x1"], bt["y0"] - (INNER if bt["end"] == "rear" else 0), bt["x1"] + INNER, bt["y1"] + (INNER if bt["end"] == "front" else 0)))
            if bt["end"] == "rear":
                rects.append((bt["x0"] - (INNER if bt["side"] == "right" else 0), bt["y0"] - INNER, bt["x1"] + (INNER if bt["side"] == "left" else 0), bt["y0"]))
            else:
                rects.append((bt["x0"] - (INNER if bt["side"] == "right" else 0), bt["y1"], bt["x1"] + (INNER if bt["side"] == "left" else 0), bt["y1"] + INNER))
    cx0, cy0, cx1, cy1 = lay["clear"]
    out = []
    for r in rects:  # clip inner walls to the building
        x0, y0, x1, y1 = max(r[0], ex0), max(r[1], ey0), min(r[2], ex1), min(r[3], ey1)
        if x1 > x0 and y1 > y0:
            out.append((x0, y0, x1, y1))
    return out


def _thick(lay, o, at):
    ex0, ey0, ex1, ey1 = lay["envelope"]
    edge = (abs(at - (ey0 + OUTER / 2)) < 1 or abs(at - (ey1 - OUTER / 2)) < 1) if o == "h" else (abs(at - (ex0 + OUTER / 2)) < 1 or abs(at - (ex1 - OUTER / 2)) < 1)
    return OUTER if edge else INNER


def _opening(lay, d):
    t = _thick(lay, d["wall"], d["at"]) + 0.02
    if d["wall"] == "h":
        return (d["a"], d["at"] - t / 2, d["b"], d["at"] + t / 2)
    return (d["at"] - t / 2, d["a"], d["at"] + t / 2, d["b"])


# ------------------------------------------------------------------------------------------------ furniture blocks
def _blocks(doc):
    def blk(name):
        return doc.blocks.new(name)
    b = blk("BED_DOUBLE")  # 5' x 6'-6", headboard at y=0
    b.add_lwpolyline([(0, 0), (60, 0), (60, 78), (0, 78)], close=True)
    b.add_lwpolyline([(4, 4), (28, 4), (28, 18), (4, 18)], close=True)
    b.add_lwpolyline([(32, 4), (56, 4), (56, 18), (32, 18)], close=True)
    b.add_line((0, 26), (60, 26))
    b = blk("SIDE_TABLE")
    b.add_lwpolyline([(0, 0), (18, 0), (18, 16), (0, 16)], close=True)
    b = blk("SOFA3")  # 6'-6" x 2'-9", back at y=0
    b.add_lwpolyline([(0, 0), (78, 0), (78, 33), (0, 33)], close=True)
    b.add_lwpolyline([(6, 8), (72, 8), (72, 33), (6, 33)], close=True)
    for x in (28, 50):
        b.add_line((x, 8), (x, 33))
    b = blk("CHAIR_ARM")
    b.add_lwpolyline([(0, 0), (30, 0), (30, 30), (0, 30)], close=True)
    b.add_lwpolyline([(5, 7), (25, 7), (25, 30), (5, 30)], close=True)
    b = blk("COFFEE")
    b.add_lwpolyline([(0, 0), (40, 0), (40, 22), (0, 22)], close=True)
    b = blk("TV_UNIT")
    b.add_lwpolyline([(0, 0), (60, 0), (60, 16), (0, 16)], close=True)
    b.add_lwpolyline([(8, 2), (52, 2), (52, 5), (8, 5)], close=True)
    for name, (tw, td, seats) in {"DINING4": (48, 32, 4), "DINING6": (72, 38, 6)}.items():
        b = blk(name)
        b.add_lwpolyline([(0, 0), (tw, 0), (tw, td), (0, td)], close=True)
        per = seats // 2
        for k in range(per):
            cx = tw * (k + 0.5) / per
            b.add_lwpolyline([(cx - 9, -20), (cx + 9, -20), (cx + 9, -4), (cx - 9, -4)], close=True)
            b.add_lwpolyline([(cx - 9, td + 4), (cx + 9, td + 4), (cx + 9, td + 20), (cx - 9, td + 20)], close=True)
    b = blk("WC")  # tank against the wall at y=0
    b.add_lwpolyline([(0, 0), (20, 0), (20, 8), (0, 8)], close=True)
    b.add_ellipse((10, 19), major_axis=(0, 11), ratio=0.73)
    b = blk("BASIN")
    b.add_lwpolyline([(0, 0), (22, 0), (22, 17), (0, 17)], close=True)
    b.add_ellipse((11, 9), major_axis=(8, 0), ratio=0.7)
    b = blk("SHOWER")
    b.add_lwpolyline([(0, 0), (32, 0), (32, 32), (0, 32)], close=True)
    b.add_line((0, 0), (32, 32))
    b.add_line((32, 0), (0, 32))
    b.add_circle((16, 16), 2)
    b = blk("CAR")  # 6' x 14', front at y=0
    b.add_lwpolyline([(8, 0), (64, 0), (72, 10), (72, 158), (64, 168), (8, 168), (0, 158), (0, 10)], close=True)
    for yy in (40, 120):  # wheel arches
        b.add_line((0, yy - 12), (-3, yy - 12))
        b.add_line((72, yy - 12), (75, yy - 12))
    b.add_lwpolyline([(8, 34), (64, 34), (60, 58), (12, 58)], close=True)
    b.add_lwpolyline([(10, 128), (62, 128), (58, 146), (14, 146)], close=True)
    b = blk("STOVE")
    b.add_lwpolyline([(0, 0), (24, 0), (24, 20), (0, 20)], close=True)
    for cx, cy in ((7, 6), (17, 6), (7, 14), (17, 14)):
        b.add_circle((cx, cy), 3.2)
    b = blk("SINK")
    b.add_lwpolyline([(0, 0), (30, 0), (30, 18), (0, 18)], close=True)
    b.add_lwpolyline([(3, 3), (27, 3), (27, 15), (3, 15)], close=True)
    b.add_circle((15, 9), 1.2)
    b = blk("NORTH")
    b.add_circle((0, 0), 10)
    b.add_lwpolyline([(0, 12), (5, -7), (0, -3), (-5, -7)], close=True)
    b.add_solid([(0, 12), (5, -7), (0, -3)])


def _ins(msp, name, x, y, rot=0, sx=1.0):
    msp.add_blockref(name, (x, y), dxfattribs={"layer": "A-FURN", "rotation": rot, "xscale": sx, "yscale": sx})


def _main_rect(r):
    """The biggest open rectangle of a room (a bedroom less its corner bath)."""
    bt = r.get("bath")
    if not bt:
        return r["x0"], r["y0"], r["x1"], r["y1"]
    a = (r["x0"], r["y0"], r["x1"], bt["y0"] - INNER) if bt["end"] == "rear" else (r["x0"], bt["y1"] + INNER, r["x1"], r["y1"])
    b = (bt["x1"] + INNER, r["y0"], r["x1"], r["y1"]) if bt["side"] == "left" else (r["x0"], r["y0"], bt["x0"] - INNER, r["y1"])
    area = lambda q: (q[2] - q[0]) * (q[3] - q[1])  # noqa: E731
    return a if area(a) >= area(b) else b


def _label_rect(r, text_w, name_h):
    """Where a room's name goes: the open part of the room the words fit across (a bedroom's space in front of its
    bath rather than the strip beside it), else the biggest open part."""
    bt = r.get("bath")
    if not bt:
        return r["x0"], r["y0"], r["x1"], r["y1"]
    cands = [(r["x0"], r["y0"], r["x1"], bt["y0"] - INNER) if bt["end"] == "rear" else (r["x0"], bt["y1"] + INNER, r["x1"], r["y1"]),
             (bt["x1"] + INNER, r["y0"], r["x1"], r["y1"]) if bt["side"] == "left" else (r["x0"], r["y0"], bt["x0"] - INNER, r["y1"])]
    fit = [q for q in cands if (q[2] - q[0]) >= text_w + 4 and (q[3] - q[1]) >= name_h * 3]
    pool = fit or cands
    return max(pool, key=lambda q: (q[2] - q[0]) * (q[3] - q[1]))


def _clear_zones(lay, r):
    """What furniture must keep clear of in a room: the square each door swings through (and the floor in front of
    every opening), and the room's bath."""
    zones = []
    for d in lay["doors"]:
        w = d["b"] - d["a"]
        for side in (1, -1):  # the floor on both sides of a door stays free for a door's width
            if d["wall"] == "h":
                z = (d["a"] - 4, d["at"], d["b"] + 4, d["at"] + side * (w + 6))
            else:
                z = (d["at"], d["a"] - 4, d["at"] + side * (w + 6), d["b"] + 4)
            zones.append((min(z[0], z[2]), min(z[1], z[3]), max(z[0], z[2]), max(z[1], z[3])))
    bt = r.get("bath")
    if bt:
        zones.append((bt["x0"] - INNER, bt["y0"] - INNER, bt["x1"] + INNER, bt["y1"] + INNER))
    return zones


def _swing_zones(lay):
    """The square each door leaf sweeps, on both sides of its wall (words keep out of them)."""
    out = []
    for d in lay["doors"]:
        if d["kind"] == "open":
            continue
        w = d["b"] - d["a"]
        out += [(d["a"], d["at"] - w, d["b"], d["at"] + w)] if d["wall"] == "h" else [(d["at"] - w, d["a"], d["at"] + w, d["b"])]
    return out


def _hits(box, zones):
    return any(not (box[2] <= z[0] or box[0] >= z[2] or box[3] <= z[1] or box[1] >= z[3]) for z in zones)


BOLD, REG = 0.86, 0.62  # text width per character, as a share of its height: ARCHB capitals, ARCH sizes


def _label_layout(r, th, zones=()):
    """How a room's name and size go on the drawing: across on one line, across on two lines ('DRAWING' over
    'ROOM'), a little smaller, or written up a narrow room. {"at", "lines", "h", "up", "size", "size_h", "box"}."""
    lab, size_txt = r["label"], f"{ft_in(r['x1'] - r['x0'])} x {ft_in(r['y1'] - r['y0'])}"
    x0, y0, x1, y1 = _label_rect(r, max(len(lab) * th * BOLD, len(size_txt) * th * 0.75 * REG), th)
    aw, ah = x1 - x0 - 8, y1 - y0 - 8
    words = lab.split(" ")
    options = [[lab]] + ([[" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))] if len(words) > 1 else [])
    best = None
    for lines in options:  # the biggest text that fits across: one line at full size wins, then two lines, then smaller
        need = max(len(x) for x in lines) * BOLD
        h = min(th, aw / need, ah / (len(lines) * 1.5 + 1.2))
        if h >= th * 0.65 and (best is None or h > best[1] + 0.01 * th):
            best = (lines, h)
    size_h = th * 0.75
    if best is None:  # written up the room
        h = max(th * 0.4, min(th, (x1 - x0) * 0.45, ah / (len(lab) * BOLD)))
        bw = h * 1.2
        return {"at": ((x0 + x1) / 2, (y0 + y1) / 2), "lines": [lab], "h": h, "up": True, "size": size_txt, "size_h": 0,
                "box": ((x0 + x1) / 2 - bw / 2, (y0 + y1) / 2 - len(lab) * BOLD * h / 2, (x0 + x1) / 2 + bw / 2, (y0 + y1) / 2 + len(lab) * BOLD * h / 2)}
    lines, h = best
    size_h = min(size_h, aw / (len(size_txt) * REG)) if r["kind"] != "passage" else 0
    size_h = size_h if size_h >= th * 0.45 else 0
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    bt = r.get("bath")
    zones = list(zones) + ([(r["x0"], r["y0"], r["x0"] + 26, r["y1"]), (r["x0"], r["y1"] - 26, r["x1"], r["y1"])] if r["kind"] == "kitchen" else [])         + ([(bt["x0"] - INNER, bt["y0"] - INNER, bt["x1"] + INNER, bt["y1"] + INNER)] if bt else [])
    rx0, ry0, rx1, ry1 = r["x0"], r["y0"], r["x1"], r["y1"]  # anywhere in the room outside its bath
    for k in (1.0, 0.9):  # clear of door swings, the bath and the kitchen counter: nearest the middle, then a little smaller
        hk, sk = h * k, size_h * k
        half = max(max(len(x) for x in lines) * BOLD * hk, len(size_txt) * REG * sk) / 2 + 3
        up_ = hk * (0.9 if len(lines) == 1 else 1.4) + hk * 0.8
        down_ = hk * 0.6 + (hk * 0.5 if len(lines) > 1 else 0) + max(sk, hk * 0.5) * 0.7
        xs = [mx + f * (x1 - x0) for f in (0, -0.15, 0.15, -0.3, 0.3)] + [v for z in zones for v in (z[2] + half + 0.5, z[0] - half - 0.5)]
        ys = [my + f * (y1 - y0) for f in (0, -0.12, 0.12, -0.24, 0.24)] + [v for z in zones for v in (z[3] + down_ + 0.5, z[1] - up_ - 0.5)]
        spots = sorted(((cx, cy) for cx in xs for cy in ys), key=lambda p: abs(p[0] - mx) / max(x1 - x0, 1) + abs(p[1] - my) / max(y1 - y0, 1))
        hit = next(((cx, cy) for cx, cy in spots if cx - half >= rx0 and cx + half <= rx1 and cy - down_ >= ry0 and cy + up_ <= ry1
                    and not _hits((cx - half, cy - down_, cx + half, cy + up_), zones)), None)
        if hit:
            cx, cy = hit
            return {"at": (cx, cy), "lines": lines, "h": hk, "up": False, "size": size_txt, "size_h": sk, "box": (cx - half, cy - down_, cx + half, cy + up_)}
    half = max(max(len(x) for x in lines) * BOLD * h, len(size_txt) * REG * size_h) / 2 + 3
    up_ = h * (0.9 if len(lines) == 1 else 1.4) + h * 0.8
    down_ = h * 0.6 + (h * 0.5 if len(lines) > 1 else 0) + max(size_h, h * 0.5) * 0.7
    return {"at": (mx, my), "lines": lines, "h": h, "up": False, "size": size_txt, "size_h": size_h, "box": (mx - half, my - down_, mx + half, my + up_)}


def _label_zone(r, th, zones=()):
    """The box a room's name and size take on the drawing (furniture keeps out of it)."""
    return _label_layout(r, th, zones)["box"]


def _skylight_box(r, th):
    """Where a room without an outside wall gets its skylight: (frame box, with its word under it) or None."""
    from ai_pc.cad.floorplan import KINDS as _K
    if not (_K[r["kind"]][5] and not r.get("outside")):
        return None
    x0, y0, x1, y1 = _main_rect(r)
    sw, sh = min(48, (x1 - x0) * 0.4), min(36, (y1 - y0) * 0.3)
    cx, cy = (x0 + x1) / 2, y0 + (y1 - y0) * 0.28
    return (cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2), (cx - sw / 2 - 2, cy - sh / 2 - th * 1.0, cx + sw / 2 + 2, cy + sh / 2 + 2)


def _free_box(rect, bw, bh, avoid):
    """A bw x bh box inside rect clear of the zones, as near the middle of the room as it can be (a grid of places
    tried nearest first)."""
    x0, y0, x1, y1 = rect
    lo_x, hi_x, lo_y, hi_y = x0 + 4 + bw / 2, x1 - 4 - bw / 2, y0 + 4 + bh / 2, y1 - 4 - bh / 2
    if lo_x > hi_x or lo_y > hi_y:
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pts = [(lo_x + (hi_x - lo_x) * i / 12, lo_y + (hi_y - lo_y) * j / 6) for i in range(13) for j in range(7)]
    for px, py in sorted(pts, key=lambda p: (abs(p[1] - cy) / max(y1 - y0, 1) * 1.5 + abs(p[0] - cx) / max(x1 - x0, 1))):
        box = (px - bw / 2, py - bh / 2, px + bw / 2, py + bh / 2)
        if not _hits(box, avoid):
            return box
    return None


def _in_front(spot, bw, bh, gap=12):
    """A bw x bh box in front of the furniture at spot (a coffee table before a sofa), and whether it turns 90°."""
    wall, (bx0, by0, bx1, by1) = spot
    mx, my = (bx0 + bx1) / 2, (by0 + by1) / 2
    if wall == "top":
        return (mx - bw / 2, by0 - gap - bh, mx + bw / 2, by0 - gap), False
    if wall == "bottom":
        return (mx - bw / 2, by1 + gap, mx + bw / 2, by1 + gap + bh), False
    if wall == "left":
        return (bx1 + gap, my - bw / 2, bx1 + gap + bh, my + bw / 2), True
    return (bx0 - gap - bh, my - bw / 2, bx0 - gap, my + bw / 2), True


def _against_wall(rect, width, depth, zones):
    """A place for something width x depth with its back to a wall of rect, clear of the zones: the back wall first,
    then the sides, then the front. Returns (wall, box)."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cands = []
    for off in (0, -1, 1):
        if x1 - x0 >= width + 4:
            bx = min(max(cx + off * ((x1 - x0) - width) / 2 - width / 2, x0 + 2), x1 - 2 - width)
            cands.append(("top", (bx, y1 - 2 - depth, bx + width, y1 - 2)))
    for off in (0, -1, 1):
        if y1 - y0 >= width + 4:
            by = min(max(cy + off * ((y1 - y0) - width) / 2 - width / 2, y0 + 2), y1 - 2 - width)
            cands.append(("left", (x0 + 2, by, x0 + 2 + depth, by + width)))
            cands.append(("right", (x1 - 2 - depth, by, x1 - 2, by + width)))
    for off in (0, -1, 1):
        if x1 - x0 >= width + 4:
            bx = min(max(cx + off * ((x1 - x0) - width) / 2 - width / 2, x0 + 2), x1 - 2 - width)
            cands.append(("bottom", (bx, y0 + 2, bx + width, y0 + 2 + depth)))
    for wall, box in cands:
        if box[0] >= x0 - 0.5 and box[2] <= x1 + 0.5 and box[1] >= y0 - 0.5 and box[3] <= y1 + 0.5 and not _hits(box, zones):
            return wall, box
    return None


def _bed_insert(spot):
    """The BED_DOUBLE block (head at y=0, 60 x 78) placed into a box with its head on the given wall."""
    wall, (bx0, by0, bx1, by1) = spot
    return {"top": (bx1, by1, 180), "bottom": (bx0, by0, 0), "left": (bx0, by1, -90), "right": (bx1, by0, 90)}[wall]


def _sofa_insert(spot):
    """The SOFA3 block (back at y=0, 78 x 33) placed into a box with its back on the given wall."""
    wall, (bx0, by0, bx1, by1) = spot
    return {"top": (bx1, by1, 180), "bottom": (bx0, by0, 0), "left": (bx0, by1, -90), "right": (bx1, by0, 90)}[wall]


def _furnish(msp, lay, th=0.0):
    """Furniture as blocks, each against a wall: a bed with its head on the back wall, sofas with a coffee table in
    front, a TV unit, a dining table, an L-shaped kitchen counter with stove and sink, a car in the porch, a WC and a
    basin in each bath; clear of door swings, the room's name and its skylight."""
    for r in lay["rooms"]:
        x0, y0, x1, y1 = _main_rect(r)
        w, d = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        k = r["kind"]
        clear = _clear_zones(lay, r)
        sky = _skylight_box(r, th)
        avoid = clear + ([_label_zone(r, th, _swing_zones(lay))] if th else []) + ([sky[1]] if sky else [])
        if k == "bedroom" and w >= 66 and d >= 84:
            spot = _against_wall((x0, y0, x1, y1), 60, 80, avoid) or _against_wall((x0, y0, x1, y1), 60, 80, clear)  # a double bed, head to a wall,
            if spot:  # clear of door swings (and of the room's name when there is room for both)
                _ins(msp, "BED_DOUBLE", *_bed_insert(spot))
        elif k in ("drawing", "guest") and w >= 90 and d >= 90:
            spot = _against_wall((x0, y0, x1, y1), 78, 35, avoid) or _against_wall((x0, y0, x1, y1), 78, 35, clear)
            if spot:
                _ins(msp, "SOFA3", *_sofa_insert(spot))
                box, turned = _in_front(spot, 40, 22)
                if not _hits(box, avoid) and x0 <= box[0] and box[2] <= x1 and y0 <= box[1] and box[3] <= y1:
                    _ins(msp, "COFFEE", *((box[2], box[1], 90) if turned else (box[0], box[1])))
        elif k in ("lounge", "family") and w >= 100 and d >= 100:
            spot = _against_wall((x0, y0, x1, y1), 78, 35, avoid) or _against_wall((x0, y0, x1, y1), 78, 35, clear)
            if spot:
                _ins(msp, "SOFA3", *_sofa_insert(spot))
                facing = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}[spot[0]]
                tv = _against_wall((x0, y0, x1, y1), 60, 18, clear + [spot[1]])
                if tv and tv[0] == facing:
                    _ins(msp, "TV_UNIT", *_sofa_insert(tv))
                avoid += [spot[1]] + ([tv[1]] if tv else [])
            if not any(rr["kind"] == "dining" for rr in lay["rooms"]) and w * d > 200 * 144 and d >= 150 and w >= 130:
                box = _free_box((x0, y0, x1, y1), 48, 72, avoid)  # the table and its chairs
                if box:
                    _ins(msp, "DINING4", box[0], box[1] + 20)
        elif k == "dining" and r["label"] == "SITTING AREA" and w >= 90 and d >= 90:  # over the dining room, upstairs
            spot = _against_wall((x0, y0, x1, y1), 78, 35, avoid) or _against_wall((x0, y0, x1, y1), 78, 35, clear)
            if spot:
                _ins(msp, "SOFA3", *_sofa_insert(spot))
        elif k == "dining" and w >= 100 and d >= 90:
            box = _free_box((x0, y0, x1, y1), 72, 78, avoid)  # the table and its chairs
            if box:
                _ins(msp, "DINING6", box[0], box[1] + 20)
        elif k == "kitchen" and w >= 66 and d >= 66:
            msp.add_lwpolyline([(x0, y1), (x1, y1), (x1, y1 - 24), (x0 + 24, y1 - 24), (x0 + 24, y0 + 12), (x0, y0 + 12)], close=True,
                               dxfattribs={"layer": "A-FURN"})
            _ins(msp, "STOVE", cx, y1 - 22)
            _ins(msp, "SINK", x0 + 3, cy + 15, -90)
        elif k == "porch" and w >= 84 and d >= 176:
            _ins(msp, "CAR", cx - 36, y0 + 6)
        bt = r.get("bath")
        if bt:
            bx0, by0, bx1, by1 = bt["x0"], bt["y0"], bt["x1"], bt["y1"]
            if bt["end"] == "rear":  # WC tank on the back wall, basin on the side wall near the door
                _ins(msp, "WC", (bx1 - 6) if bt["side"] == "right" else (bx0 + 26), by1, 180)
                if bt["side"] == "right":
                    _ins(msp, "BASIN", bx1 - 2, by0 + 6, 90)
                else:
                    _ins(msp, "BASIN", bx0 + 2, by0 + 28, -90)
            else:
                _ins(msp, "WC", (bx1 - 26) if bt["side"] == "right" else (bx0 + 6), by0, 0)
                if bt["side"] == "right":
                    _ins(msp, "BASIN", bx1 - 2, by1 - 28, 90)
                else:
                    _ins(msp, "BASIN", bx0 + 2, by1 - 6, -90)


# ------------------------------------------------------------------------------------------------ doors, windows, stairs
def _door(msp, lay, d):
    rooms = {r["id"]: r for r in lay["rooms"]}
    t = _thick(lay, d["wall"], d["at"])
    w = d["b"] - d["a"]
    if d["kind"] == "open":
        if d["wall"] == "h":
            msp.add_line((d["a"], d["at"] - t / 2), (d["b"], d["at"] - t / 2), dxfattribs={"layer": "A-DOOR", "linetype": "DASHED", "ltscale": 0.4})
        else:
            msp.add_line((d["at"] - t / 2, d["a"]), (d["at"] - t / 2, d["b"]), dxfattribs={"layer": "A-DOOR", "linetype": "DASHED", "ltscale": 0.4})
        return
    into = d.get("into")
    if into and into.endswith("_bath"):
        host = rooms.get(into[:-5])
        bt = host["bath"] if host else None
        tgt = (bt["x0"] + bt["x1"]) / 2 if d["wall"] == "v" else (bt["y0"] + bt["y1"]) / 2
    else:
        r = rooms.get(into) or rooms.get(d["to"])
        tgt = ((r["x0"] + r["x1"]) / 2 if d["wall"] == "v" else (r["y0"] + r["y1"]) / 2) if r else d["at"] + 1
    sgn = 1 if tgt > d["at"] else -1
    face = d["at"] + sgn * t / 2
    hinge = d["a"] if d.get("hinge", "a") == "a" else d["b"]
    other = d["b"] if hinge == d["a"] else d["a"]
    if d["wall"] == "h":
        hp, leaf_end = (hinge, face), (hinge, face + sgn * w)
        a0 = math.degrees(math.atan2(leaf_end[1] - face, 0))
        a1 = math.degrees(math.atan2(0, other - hinge))
    else:
        hp, leaf_end = (face, hinge), (face + sgn * w, hinge)
        a0 = math.degrees(math.atan2(0, leaf_end[0] - face))
        a1 = math.degrees(math.atan2(other - hinge, 0))
    msp.add_line(hp, leaf_end, dxfattribs={"layer": "A-DOOR"})
    s, e = (a0, a1) if (a1 - a0) % 360 <= 180 else (a1, a0)
    msp.add_arc(hp, w, s, e, dxfattribs={"layer": "A-DOOR"})


def _window(msp, lay, wdw):
    t = OUTER
    a, b, at = wdw["a"], wdw["b"], wdw["at"]
    for off in (-t / 2, 0, t / 2):
        if wdw["wall"] == "h":
            msp.add_line((a, at + off), (b, at + off), dxfattribs={"layer": "A-GLAZ"})
        else:
            msp.add_line((at + off, a), (at + off, b), dxfattribs={"layer": "A-GLAZ"})
    if wdw["wall"] == "h":
        msp.add_line((a, at - t / 2), (a, at + t / 2), dxfattribs={"layer": "A-GLAZ"})
        msp.add_line((b, at - t / 2), (b, at + t / 2), dxfattribs={"layer": "A-GLAZ"})
    else:
        msp.add_line((at - t / 2, a), (at + t / 2, a), dxfattribs={"layer": "A-GLAZ"})
        msp.add_line((at - t / 2, b), (at + t / 2, b), dxfattribs={"layer": "A-GLAZ"})


def _stairs(msp, r, th):
    x0, y0, x1, y1 = r["x0"], r["y0"], r["x1"], r["y1"]
    tread = 10
    att = {"layer": "A-STAIR"}
    if r.get("stair") == "straight" or (x1 - x0) < 70:
        n = int((y1 - y0 - 36) // tread)
        for k in range(1, n + 1):
            y = y0 + k * tread
            msp.add_line((x0, y), (x1, y), dxfattribs=att)
        cx = (x0 + x1) / 2
        msp.add_line((cx, y0 + 6), (cx, y0 + n * tread + 8), dxfattribs=att)
        msp.add_lwpolyline([(cx - 4, y0 + n * tread), (cx, y0 + n * tread + 8), (cx + 4, y0 + n * tread)], dxfattribs=att)
        y0 + 8
    else:
        mid = (x0 + x1) / 2
        land = 40
        n = int((y1 - y0 - land) // tread)
        for k in range(1, n + 1):
            y = y0 + k * tread
            msp.add_line((x0, y), (mid - 1, y), dxfattribs=att)
            msp.add_line((mid + 1, y), (x1, y), dxfattribs=att)
        msp.add_line((mid, y0), (mid, y0 + n * tread), dxfattribs=att)
        ca, cb = (x0 + mid) / 2, (mid + x1) / 2
        top = y0 + n * tread + land / 2
        msp.add_lwpolyline([(ca, y0 + 6), (ca, top), (cb, top), (cb, y0 + n * tread * 0.55)], dxfattribs=att)
        msp.add_lwpolyline([(cb - 4, y0 + n * tread * 0.55 + 8), (cb, y0 + n * tread * 0.55), (cb + 4, y0 + n * tread * 0.55 + 8)], dxfattribs=att)
        msp.add_line((x0, y0 + n * tread * 0.45), (mid, y0 + n * tread * 0.62), dxfattribs=att)  # the cut line of the floor above
        y0 + 8
    ux = (r["x0"] + r["x1"]) / 2 if (r.get("stair") == "straight" or (r["x1"] - r["x0"]) < 70) else (r["x0"] + (r["x0"] + r["x1"]) / 2) / 2
    msp.add_text("UP", dxfattribs={"layer": "A-TEXT", "height": th * 0.8, "style": "ARCHB"}).set_placement((ux, r["y0"] + th * 1.3),
                                                                                                    align=TextEntityAlignment.MIDDLE_CENTER)


# ------------------------------------------------------------------------------------------------ the drawing
def _dimstyle(doc, scale):
    u = _mm(scale)
    ds = doc.dimstyles.new(f"ARCH{scale}")
    ds.dxf.dimtxt = 2.0 * u
    ds.dxf.dimasz = 0
    ds.dxf.dimtsz = 1.1 * u  # architectural ticks, not arrows
    ds.dxf.dimexo = 1.2 * u
    ds.dxf.dimexe = 1.2 * u
    ds.dxf.dimgap = 0.6 * u
    ds.dxf.dimtad = 1
    ds.dxf.dimtih = 0
    ds.dxf.dimtoh = 0
    ds.dxf.dimtxsty = "ARCH"
    ds.dxf.dimdle = 1.0 * u
    return ds.dxf.name


def _chain(msp, style, pts, base, axis, u, origin):
    """Chain dimensions between consecutive points along x (axis 'x': the dimension line at y=base, extension lines
    from y=origin) or along y; the text is the distance in feet and inches."""
    pts = sorted(set(round(p, 3) for p in pts))
    for a, b in zip(pts, pts[1:]):
        if b - a < 6:
            continue
        if axis == "x":
            dim = msp.add_linear_dim(base=(a, base), p1=(a, origin), p2=(b, origin), dimstyle=style, text=ft_in(b - a), dxfattribs={"layer": "A-DIMS"})
        else:
            dim = msp.add_linear_dim(base=(base, a), p1=(origin, a), p2=(origin, b), angle=90, dimstyle=style, text=ft_in(b - a), dxfattribs={"layer": "A-DIMS"})
        dim.render()


def _plan(msp, lay, ox, oy, scale, style, title):
    """One floor at an offset (ox, oy)."""
    u = _mm(scale)
    th = 2.6 * u
    moved = _offset(lay, ox, oy)
    holes = [_opening(moved, d) for d in moved["doors"]] + [_opening(moved, w) for w in moved["windows"]]
    loops = union(_wall_rects(moved), holes)
    hatch = msp.add_hatch(color=8, dxfattribs={"layer": "A-WALL-FILL"})
    hatch.set_solid_fill(color=8)
    for pts in loops:
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-WALL"})
        hatch.paths.add_polyline_path(pts, is_closed=True)
    for d in moved["doors"]:
        _door(msp, moved, d)
    for w in moved["windows"]:
        _window(msp, moved, w)
    if moved["brief"].get("furniture", True):
        _furnish(msp, moved, th)
    W, D = moved["plot"]
    px0, py0 = ox, oy
    msp.add_lwpolyline([(px0, py0), (px0 + W, py0), (px0 + W, py0 + D), (px0, py0 + D)], close=True,
                       dxfattribs={"layer": "A-PLOT", "linetype": "DASHDOT", "ltscale": scale / 25})
    for r in moved["rooms"]:
        msp.add_lwpolyline([(r["x0"], r["y0"]), (r["x1"], r["y0"]), (r["x1"], r["y1"]), (r["x0"], r["y1"])], close=True, dxfattribs={"layer": "A-AREA"})
        if r["kind"] == "stairs":
            _stairs(msp, r, th)
        if r["kind"] == "stairs":  # the treads and UP say what it is
            continue
        lb = _label_layout(r, th, _swing_zones(moved))
        cx, cy = lb["at"]
        if not lb["up"]:
            mt = msp.add_mtext("\\P".join(lb["lines"]), dxfattribs={"layer": "A-TEXT", "char_height": lb["h"], "style": "ARCHB", "attachment_point": 5})
            mt.set_location((cx, cy + lb["h"] * (0.9 if len(lb["lines"]) == 1 else 1.4)))
            if lb["size_h"]:
                msp.add_text(lb["size"], dxfattribs={"layer": "A-TEXT", "height": lb["size_h"], "style": "ARCH"}).set_placement(
                    (cx, cy - lb["h"] * 0.6 - (lb["h"] * 0.5 if len(lb["lines"]) > 1 else 0)), align=TextEntityAlignment.MIDDLE_CENTER)
        else:  # too narrow for the words across (a store): written up the room
            msp.add_text(lb["lines"][0], dxfattribs={"layer": "A-TEXT", "height": lb["h"], "style": "ARCHB", "rotation": 90}).set_placement(
                (cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
        bt = r.get("bath")
        if bt:
            bsz = f"{ft_in(bt['w'])} x {ft_in(bt['d'])}"
            fits = bt["w"] >= len(bsz) * th * 0.5 * 0.6 + 4
            msp.add_text("BATH", dxfattribs={"layer": "A-TEXT", "height": th * 0.7, "style": "ARCHB"}).set_placement(
                ((bt["x0"] + bt["x1"]) / 2, (bt["y0"] + bt["y1"]) / 2 + (th * 0.4 if fits else 0)), align=TextEntityAlignment.MIDDLE_CENTER)
            if fits:
                msp.add_text(bsz, dxfattribs={"layer": "A-TEXT", "height": th * 0.5, "style": "ARCH"}).set_placement(
                    ((bt["x0"] + bt["x1"]) / 2, (bt["y0"] + bt["y1"]) / 2 - th * 0.6), align=TextEntityAlignment.MIDDLE_CENTER)
    for r in moved["rooms"]:  # a room with no outside wall gets a skylight (dashed: it is overhead)
        sky = _skylight_box(r, th)
        if sky:
            (sx0, sy0, sx1, sy1), _ = sky
            sw, sh, cx, cy = sx1 - sx0, sy1 - sy0, (sx0 + sx1) / 2, (sy0 + sy1) / 2
            msp.add_lwpolyline([(cx - sw / 2, cy - sh / 2), (cx + sw / 2, cy - sh / 2), (cx + sw / 2, cy + sh / 2), (cx - sw / 2, cy + sh / 2)], close=True,
                               dxfattribs={"layer": "A-GLAZ", "linetype": "DASHED", "ltscale": scale / 60})
            msp.add_line((cx - sw / 2, cy - sh / 2), (cx + sw / 2, cy + sh / 2), dxfattribs={"layer": "A-GLAZ", "linetype": "DASHED", "ltscale": scale / 60})
            msp.add_text("SKYLIGHT", dxfattribs={"layer": "A-TEXT", "height": th * 0.5, "style": "ARCH"}).set_placement(
                (cx, cy - sh / 2 - th * 0.6), align=TextEntityAlignment.MIDDLE_CENTER)
    ex0_, ey0_, ex1_, ey1_ = moved["envelope"]
    if moved["plot"][1] + oy - ey1_ >= 24:  # the open space at the back, named between the dimension lines that cross it
        xs = sorted({ex0_, ex1_} | {v for r in moved["rooms"] if abs(r["y1"] - (ey1_ - OUTER)) < 1
                                    for v, ok in ((r["x0"] - INNER / 2, r["x0"] > ex0_ + OUTER + 1), (r["x1"] + INNER / 2, r["x1"] < ex1_ - OUTER - 1)) if ok})
        a, b = max(zip(xs, xs[1:]), key=lambda p: p[1] - p[0])
        txt = f"OPEN SPACE {ft_in(moved['plot'][1] + oy - ey1_)}"
        msp.add_text(txt, dxfattribs={"layer": "A-TEXT", "height": min(th * 0.7, (b - a - 8) / (len(txt) * REG)), "style": "ARCH"}).set_placement(
            ((a + b) / 2, (ey1_ + moved["plot"][1] + oy) / 2), align=TextEntityAlignment.MIDDLE_CENTER)
    for r in moved["rooms"]:  # the gate: the porch opens onto the road
        if r["kind"] == "porch" and "front" in r.get("outside", []):
            msp.add_line((r["x0"], ey0_ + 1), (r["x1"], ey0_ + 1), dxfattribs={"layer": "A-DOOR", "linetype": "DASHED", "ltscale": scale / 60})
            msp.add_text("GATE", dxfattribs={"layer": "A-TEXT", "height": th * 0.55, "style": "ARCH"}).set_placement(
                ((r["x0"] + r["x1"]) / 2, ey0_ + th * 0.9), align=TextEntityAlignment.MIDDLE_CENTER)
    for w in moved["windows"]:
        if w["kind"] == "vent":
            y = w["at"] + (OUTER / 2 + 2.2 * u if w.get("side") == "rear" else -OUTER / 2 - 2.2 * u)
            msp.add_text("V", dxfattribs={"layer": "A-TEXT", "height": th * 0.6, "style": "ARCH"}).set_placement(((w["a"] + w["b"]) / 2, y),
                                                                                                               align=TextEntityAlignment.MIDDLE_CENTER)
    ex0, ey0, ex1, ey1 = moved["envelope"]
    gap = 9 * u
    def inner_x(r):
        return [v for v, ok in ((r["x0"] - INNER / 2, r["x0"] > ex0 + OUTER + 1), (r["x1"] + INNER / 2, r["x1"] < ex1 - OUTER - 1)) if ok]
    xs = [ex0, ex1] + [v for r in moved["rooms"] if abs(r["y0"] - (ey0 + OUTER)) < 1 for v in inner_x(r)]
    _chain(msp, style, [v for v in xs if ex0 <= v <= ex1], py0 - gap, "x", u, ey0)
    _chain(msp, style, [px0, px0 + W], py0 - gap * 2, "x", u, py0)
    ys = [ey0, ey1] + [r["y1"] + INNER / 2 for r in moved["rooms"] if abs(r["x0"] - (ex0 + OUTER)) < 1 and r["y1"] < ey1 - OUTER - 1]
    _chain(msp, style, ys, px0 - gap, "y", u, ex0)
    _chain(msp, style, [py0, py0 + D], px0 - gap * 2, "y", u, px0)
    xs_rear = [ex0, ex1] + [v for r in moved["rooms"] if abs(r["y1"] - (ey1 - OUTER)) < 1 for v in inner_x(r)]
    _chain(msp, style, [v for v in xs_rear if ex0 <= v <= ex1], py0 + D + gap, "x", u, ey1)
    msp.add_text("ROAD", dxfattribs={"layer": "A-TEXT", "height": th * 1.2, "style": "ARCHB"}).set_placement((px0 + W / 2, py0 - gap * 3.2),
                                                                                                         align=TextEntityAlignment.MIDDLE_CENTER)
    mt = msp.add_mtext(f"{title}", dxfattribs={"layer": "A-TITLE", "char_height": th * 1.5, "style": "ARCHB", "attachment_point": 2})
    mt.set_location((px0 + W / 2, py0 + D + gap * 3.2))
    return moved


def _offset(lay, ox, oy):
    """The layout moved by (ox, oy) (a second floor drawn beside the first)."""
    import copy
    m = copy.deepcopy({k: v for k, v in lay.items() if k != "upper"})
    for r in m["rooms"]:
        for k in ("x0", "x1"):
            r[k] += ox
        for k in ("y0", "y1"):
            r[k] += oy
        if r.get("bath"):
            for k in ("x0", "x1"):
                r["bath"][k] += ox
            for k in ("y0", "y1"):
                r["bath"][k] += oy
    for d in m["doors"] + m["windows"]:
        if d["wall"] == "h":
            d["at"] += oy
            d["a"] += ox
            d["b"] += ox
        else:
            d["at"] += ox
            d["a"] += oy
            d["b"] += oy
    e = m["envelope"]
    m["envelope"] = [e[0] + ox, e[1] + oy, e[2] + ox, e[3] + oy]
    c = m["clear"]
    m["clear"] = [c[0] + ox, c[1] + oy, c[2] + ox, c[3] + oy]
    return m


def drawing(lay, paper=None, scale=None, project=None, client=None):
    """The DXF (ezdxf document) and the sheet: {"paper", "scale", "frame": (x0, y0, x1, y1) in drawing units, "floors"}."""
    floors = [lay] + ([lay["upper"]] if lay.get("upper") else [])
    W, D = lay["plot"]
    margin = 30  # mm of paper around each plan for its dimensions and title
    paper_name = paper or ("A3" if len(floors) == 1 or W * 2 < D * 1.6 else "A2")
    pw, ph = PAPER[paper_name]
    tb_h = 46  # title block strip height, mm
    usable_w, usable_h = pw - 20 - 10, ph - 10 - 10 - tb_h
    if scale is None:
        for s in SCALES:
            need_w = (W * len(floors)) / _mm(s) + margin * 2 * len(floors)
            need_h = D / _mm(s) + margin * 2
            if need_w <= usable_w and need_h <= usable_h:
                scale = s
                break
        else:
            if paper is None and paper_name != "A1":
                return drawing(lay, "A2" if paper_name == "A3" else "A1", None, project, client)
            scale = SCALES[-1]
    if paper is None and scale > 150 and paper_name != "A1":  # smaller than 1:150 is hard to build from: a bigger sheet
        return drawing(lay, "A2" if paper_name == "A3" else "A1", None, project, client)
    need_w = (W * len(floors)) / _mm(scale) + margin * 2 * len(floors)
    need_h = D / _mm(scale) + margin * 2
    if need_w > usable_w + 1 or need_h > usable_h + 1:  # a scale asked for that the sheet cannot hold
        fit = next((s for s in SCALES if (W * len(floors)) / _mm(s) + margin * 2 * len(floors) <= usable_w and D / _mm(s) + margin * 2 <= usable_h), None)
        raise ValueError(f"at 1:{scale} the plan{'s need' if len(floors) > 1 else ' needs'} {need_w:.0f} x {need_h:.0f} mm and {paper_name} has room for "
                         f"{usable_w:.0f} x {usable_h:.0f}" + (f"; 1:{fit} fits {paper_name}" if fit else "") + ", or ask for a bigger sheet")
    u = _mm(scale)
    doc = _new()
    msp = doc.modelspace()
    style = _dimstyle(doc, scale)
    fx0, fy0 = -(20 + margin) * u, -(10 + tb_h + margin) * u  # the frame's corner in drawing units, so the first plot sits at (0, 0)
    fw, fh = (pw - 30) * u, (ph - 20) * u
    slot = (fw - 0) / len(floors)
    names = {"GROUND FLOOR": "GROUND FLOOR PLAN", "FIRST FLOOR": "FIRST FLOOR PLAN"}
    plans = []
    for i, fl in enumerate(floors):
        ox = fx0 + slot * i + (slot - W) / 2
        oy = fy0 + tb_h * u + (fh - tb_h * u - D) / 2
        plans.append(_plan(msp, fl, ox, oy, scale, style, names.get(fl.get("floor"), "PLAN")))
    frame = (fx0, fy0, fx0 + fw, fy0 + fh)
    msp.add_lwpolyline([(frame[0], frame[1]), (frame[2], frame[1]), (frame[2], frame[3]), (frame[0], frame[3])], close=True,
                       dxfattribs={"layer": "A-SHEET", "const_width": 0.5 * u})
    sheet = (frame[0] - 20 * u, frame[1] - 10 * u, frame[2] + 10 * u, frame[3] + 10 * u)
    _title(msp, lay, frame, scale, paper_name, project, client)
    _schedule(msp, lay, frame, scale)
    _north(msp, lay, frame, scale)
    return doc, {"paper": paper_name, "paper_mm": (pw, ph), "scale": scale, "frame": frame, "sheet": sheet, "floors": len(floors), "plans": plans}


def _title(msp, lay, frame, scale, paper, project, client):
    u = _mm(scale)
    b = lay["brief"]
    x1, y0 = frame[2], frame[1]
    w, h = 170 * u, 40 * u
    x0, y1 = x1 - w, y0 + h
    att = {"layer": "A-TITLE"}
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs=att)
    for yy in (y0 + 10 * u, y0 + 20 * u, y0 + 30 * u):
        msp.add_line((x0, yy), (x1, yy), dxfattribs=att)
    msp.add_line((x0 + 85 * u, y0), (x0 + 85 * u, y0 + 30 * u), dxfattribs=att)
    s = summary(lay)
    W, D = (v / 12 for v in lay["plot"])
    covered = s["covered_sqft"] + (summary(lay["upper"])["covered_sqft"] if lay.get("upper") else 0)
    rows = [(project or b.get("name") or "House", 4.5, x0 + 3 * u, y0 + 35 * u, True),
            (f"Plot {W:.0f}' x {D:.0f}' ({marla_of(W, D):.1f} marla, {W * D:.0f} sq ft)", 2.6, x0 + 3 * u, y0 + 25 * u, False),
            (f"Covered area {covered:,} sq ft" + (" on 2 floors" if lay.get("upper") else ""), 2.6, x0 + 88 * u, y0 + 25 * u, False),
            (("Client: " + client) if client else "Client: -", 2.4, x0 + 3 * u, y0 + 15 * u, False),
            (f"Scale 1:{scale} on {paper}   Units: feet-inches", 2.4, x0 + 88 * u, y0 + 15 * u, False),
            (f"Date {dt.date.today():%d %b %Y}   Drawn by AI PC (ezdxf)", 2.2, x0 + 3 * u, y0 + 5 * u, False),
            ("Walls 9\" outer, 4.5\" inner. Check every size on site.", 2.2, x0 + 88 * u, y0 + 5 * u, False)]
    for text, hmm, x, y, bold in rows:
        msp.add_text(text, dxfattribs={"layer": "A-TITLE", "height": hmm * u, "style": "ARCHB" if bold else "ARCH"}).set_placement(
            (x, y), align=TextEntityAlignment.MIDDLE_LEFT)


def _schedule(msp, lay, frame, scale):
    """A room schedule beside the title block: each room's clear size and area."""
    u = _mm(scale)
    summary(lay)["rooms"]
    x0 = frame[0] + 3 * u
    y = frame[1] + 40 * u - 4 * u
    msp.add_text("ROOM SCHEDULE (clear sizes)", dxfattribs={"layer": "A-TITLE", "height": 2.4 * u, "style": "ARCHB"}).set_placement(
        (x0, y), align=TextEntityAlignment.MIDDLE_LEFT)
    blocks = []
    for fl, head in ((lay, "Ground floor"), (lay.get("upper"), "First floor")):
        if not fl:
            continue
        rows = [(head.upper(), None, True)] if lay.get("upper") else []
        rows += [(r["label"].title()[:16], f"{r['size']}  {r['area_sqft']:.0f} sq ft", False) for r in summary(fl)["rooms"] if r["label"] != "PASSAGE"]
        blocks.append(rows)
    room_w = (frame[2] - 170 * u - 4 * u) - x0  # up to the title block
    name_c = max(len(n) for b in blocks for n, _, _ in b)
    rest_c = max(len(r or "") for b in blocks for _, r, _ in b)
    # the biggest text whose columns fit beside the title block; each floor starts a column when that fits too
    for h, per, split in ((2.0, 7, True), (1.8, 8, True), (1.7, 9, True), (1.8, 8, False), (1.6, 9, False), (1.4, 10, False)):
        name_w = name_c * h * 0.75 + 3  # mixed-case names run wider than the digits of the sizes
        col_w = name_w + rest_c * h * 0.62 + 6
        cols = sum(-(-len(b) // per) for b in blocks) if split else -(-sum(len(b) for b in blocks) // per)
        if cols * col_w * u <= room_w:
            break
    step = min(4.2, 30.0 / per)
    places, col = [], 0
    for b in (blocks if split else [[r for blk in blocks for r in blk]]):
        for i, row in enumerate(b):
            places.append((col + i // per, i % per, row))
        col += -(-len(b) // per)
    for c, i, (name, rest, head) in places:
        cx = x0 + c * col_w * u
        cy = y - (i + 1) * step * u
        msp.add_text(name, dxfattribs={"layer": "A-TITLE", "height": h * u, "style": "ARCHB" if head else "ARCH"}).set_placement(
            (cx, cy), align=TextEntityAlignment.MIDDLE_LEFT)
        if rest:
            msp.add_text(rest, dxfattribs={"layer": "A-TITLE", "height": h * u, "style": "ARCH"}).set_placement(
                (cx + name_w * u, cy), align=TextEntityAlignment.MIDDLE_LEFT)


def _north(msp, lay, frame, scale):
    u = _mm(scale)
    facing = (lay["brief"].get("facing") or "south").lower()  # the side the road is on
    rot = {"south": 0, "north": 180, "east": 90, "west": -90}.get(facing, 0)
    x, y = frame[2] - 15 * u, frame[3] - 18 * u
    msp.add_blockref("NORTH", (x, y), dxfattribs={"layer": "A-TITLE", "xscale": u, "yscale": u, "rotation": rot})
    msp.add_text("N", dxfattribs={"layer": "A-TITLE", "height": 3 * u, "style": "ARCHB"}).set_placement(
        (x + 14 * u * math.sin(math.radians(-rot)), y + 14 * u * math.cos(math.radians(rot))), align=TextEntityAlignment.MIDDLE_CENTER)
