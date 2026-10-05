"""A house plan from the CAD lane (src/ai_pc/cad/floorplan.py) turned into 3D, as boxes measured in inches: the walls cut
around every door and window (disjoint blocks, so no two faces fight for the same place), lintels over the openings,
sills, glass and frames in the windows, sunshades over the outside windows, floors by room (marble, wood, tiles,
concrete), the stairs as real steps up to the next floor, the furniture where the drawing puts it, slabs, a parapet on
the roof, the boundary wall with a gate across the car porch, the road and the yard. Everything here is plain Python:
Blender only builds and renders the boxes (src/ai_pc/three/bl/house_scene.py).

  spec = house_spec(lay, style)    -> {"boxes": [...], "labels": [...], "views": {...}, "expect": {...}}
  a box: {"n": name, "c": collection, "m": material, "b": [x0, y0, z0, x1, y1, z1]} (inches; x across the plot, y from the
  road to the back, z up)
"""

from ai_pc.cad import draft as DR
from ai_pc.cad.floorplan import INNER, OUTER

CLEAR_H = 126.0  # 10'-6" floor to ceiling, as Pakistani houses are built
SLAB = 6.0  # roof / floor slab
PLINTH = 18.0  # the ground floor stands 1'-6" above the road
DOOR_H = 84.0  # 7'-0" doors and window heads
SILL = 36.0  # 3'-0" window sills
VENT = (78.0, 96.0)  # bath ventilators: high up
PARAPET = 36.0
BOUNDARY_H = 72.0
STYLES = {
    "modern": {"wall": "plaster_white", "accent": "stone_grey", "frame": "frame_black", "door": "wood_dark", "parapet": "plaster_white"},
    "warm": {"wall": "plaster_cream", "accent": "wood_light", "frame": "frame_brown", "door": "wood_dark", "parapet": "plaster_cream"},
    "grey": {"wall": "plaster_grey", "accent": "wood_light", "frame": "frame_black", "door": "wood_dark", "parapet": "plaster_grey"},
    "classic": {"wall": "plaster_cream", "accent": "brick_red", "frame": "frame_white", "door": "wood_dark", "parapet": "brick_red"},
}
FLOORS = {
    "porch": "concrete",
    "terrace": "tiles_terrace",
    "kitchen": "tiles_grey",
    "store": "tiles_grey",
    "powder": "tiles_grey",
    "stairs": "marble",
    "bedroom": "wood_floor",
    "drawing": "marble",
    "guest": "wood_floor",
    "lounge": "marble",
    "family": "marble",
    "dining": "marble",
    "servant": "tiles_grey",
    "passage": "marble",
    "bath": "tiles_bath",
}


def _rect_minus(cells_rects, holes):
    """The area of the rectangles less the holes, as DISJOINT rectangles (the plane cut at every edge, filled cells
    merged into runs along x, runs with the same x span merged along y)."""
    xs = sorted({v for r in list(cells_rects) + list(holes) for v in (r[0], r[2])})
    ys = sorted({v for r in list(cells_rects) + list(holes) for v in (r[1], r[3])})
    filled = {}
    for i in range(len(xs) - 1):
        cx = (xs[i] + xs[i + 1]) / 2
        for j in range(len(ys) - 1):
            cy = (ys[j] + ys[j + 1]) / 2
            if any(r[0] < cx < r[2] and r[1] < cy < r[3] for r in cells_rects) and not any(h[0] < cx < h[2] and h[1] < cy < h[3] for h in holes):
                filled[(i, j)] = True
    runs = []  # (j, i0, i1): a row of filled cells
    for j in range(len(ys) - 1):
        i = 0
        while i < len(xs) - 1:
            if filled.get((i, j)):
                i0 = i
                while filled.get((i + 1, j)):
                    i += 1
                runs.append((j, i0, i))
            i += 1
    out, _used = [], set()
    by = {}
    for r in runs:
        by.setdefault((r[1], r[2]), []).append(r[0])
    for (i0, i1), js in by.items():
        js.sort()
        k = 0
        while k < len(js):
            j0 = js[k]
            while k + 1 < len(js) and js[k + 1] == js[k] + 1:
                k += 1
            out.append((xs[i0], ys[j0], xs[i1 + 1], ys[js[k] + 1]))
            k += 1
    return out


def _box(boxes, n, c, m, x0, y0, z0, x1, y1, z1):
    if x1 - x0 > 0.05 and y1 - y0 > 0.05 and z1 - z0 > 0.05:
        boxes.append({"n": n, "c": c, "m": m, "b": [round(x0, 3), round(y0, 3), round(z0, 3), round(x1, 3), round(y1, 3), round(z1, 3)]})


class _Rec:
    """Stands in for the DXF model space: records the furniture the drawing would insert, so 3D puts it in the same place."""

    def __init__(self):
        self.blocks, self.polys = [], []

    def add_blockref(self, name, insert, dxfattribs=None):
        a = dxfattribs or {}
        self.blocks.append({"name": name, "x": insert[0], "y": insert[1], "rot": a.get("rotation", 0), "s": a.get("xscale", 1.0)})

    def add_lwpolyline(self, pts, close=False, dxfattribs=None):
        self.polys.append([tuple(p[:2]) for p in pts])


# furniture in each block's own frame (the DXF block's origin and axes), as boxes (x0, y0, z0, x1, y1, z1, material)
FURNITURE = {
    "BED_DOUBLE": [
        (0, 0, 0, 60, 78, 14, "wood_furn"),
        (2, 2, 14, 58, 76, 22, "fabric_white"),
        (4, 4, 22, 28, 18, 26, "fabric_white"),
        (32, 4, 22, 56, 18, 26, "fabric_white"),
        (2, 34, 22, 58, 76, 23, "fabric_accent"),
        (0, -3, 0, 60, 0, 40, "wood_furn"),
    ],
    "SOFA3": [
        (0, 0, 0, 78, 33, 16, "fabric_sofa"),
        (0, 0, 16, 78, 9, 32, "fabric_sofa"),
        (0, 0, 16, 6, 33, 24, "fabric_sofa"),
        (72, 0, 16, 78, 33, 24, "fabric_sofa"),
    ],
    "COFFEE": [(0, 0, 14, 40, 22, 17, "wood_furn"), (2, 2, 0, 38, 20, 14, "wood_dark")],
    "TV_UNIT": [(0, 0, 0, 60, 16, 20, "wood_furn"), (8, 4, 20, 52, 6, 46, "screen")],
    "DINING4": [(0, 0, 28, 48, 32, 30, "wood_furn"), (20, 12, 0, 28, 20, 28, "wood_dark")]
    + [(cx - 9, -20, 0, cx + 9, -4, 17, "wood_dark") for cx in (12, 36)]
    + [(cx - 9, 36, 0, cx + 9, 52, 17, "wood_dark") for cx in (12, 36)],
    "DINING6": [(0, 0, 28, 72, 38, 30, "wood_furn"), (30, 14, 0, 42, 24, 28, "wood_dark")]
    + [(cx - 9, -20, 0, cx + 9, -4, 17, "wood_dark") for cx in (12, 36, 60)]
    + [(cx - 9, 42, 0, cx + 9, 58, 17, "wood_dark") for cx in (12, 36, 60)],
    "WC": [(2, 0, 0, 18, 8, 30, "ceramic"), (3, 8, 0, 17, 30, 15, "ceramic")],
    "BASIN": [(0, 0, 30, 22, 17, 34, "ceramic"), (8, 0, 0, 14, 6, 30, "ceramic")],
    "CAR": [
        (0, 10, 6, 72, 158, 30, "car_paint"),
        (8, 34, 30, 64, 130, 52, "car_glass"),
        (10, 40, 30, 62, 124, 53, "car_paint"),
        (-2, 24, 0, 6, 52, 22, "tyre"),
        (66, 24, 0, 74, 52, 22, "tyre"),
        (-2, 116, 0, 6, 144, 22, "tyre"),
        (66, 116, 0, 74, 144, 22, "tyre"),
    ],
    "STOVE": [(0, 0, 36, 24, 20, 37, "steel")],
    "SINK": [(0, 0, 35, 30, 18, 36.5, "steel")],
}


def _place(local, ins):
    """A local box through the block's insertion (x, y, rotation in degrees, scale) -> a world box."""
    x0, y0, z0, x1, y1, z1 = local[:6]
    s = ins.get("s", 1.0) or 1.0
    rot = int(round(ins["rot"])) % 360
    pts = [(x0 * s, y0 * s), (x1 * s, y1 * s)]
    if rot == 90:
        pts = [(-y, x) for x, y in pts]
    elif rot == 180:
        pts = [(-x, -y) for x, y in pts]
    elif rot == 270:
        pts = [(y, -x) for x, y in pts]
    xs = [ins["x"] + p[0] for p in pts]
    ys = [ins["y"] + p[1] for p in pts]
    return min(xs), min(ys), z0, max(xs), max(ys), z1


def _floor(fl, z, boxes, style, name, cut=None, with_furniture=True, th=0.0):
    """One storey at height z (the top of its floor): walls with their openings, floors, stairs, furniture."""
    H = CLEAR_H
    top = z + H if cut is None else z + min(H, cut)
    walls = DR._wall_rects(fl)
    env = fl["envelope"]
    opens = []
    for d in fl["doors"]:
        opens.append((DR._opening(fl, d), "door", d))
    for w in fl.get("windows", []):
        opens.append((DR._opening(fl, w), w.get("kind", "window"), w))
    holes = [o[0] for o in opens]
    outer = lambda r: r[0] <= env[0] + 0.1 or r[1] <= env[1] + 0.1 or r[2] >= env[2] - 0.1 or r[3] >= env[3] - 0.1  # noqa: E731
    pieces = _rect_minus(walls, holes)
    for k, r in enumerate(pieces):
        _box(boxes, f"{name}_wall{k}", f"{name}_walls", style["wall"] if outer(r) else "plaster_inside", r[0], r[1], z, r[2], r[3], top)
    if cut is not None:  # the cut tops of the walls (and of the lintels over the doors) dark, the way 3D plans show them
        lint = [o[0] for o in opens if (DOOR_H if o[1] in ("door", "window") else VENT[1]) < cut]
        for k, r in enumerate(_rect_minus(pieces + lint, [])):
            _box(boxes, f"{name}_cap{k}", f"{name}_caps", "wall_cap", r[0], r[1], top, r[2], r[3], top + 0.6)
    for k, (r, kind, o) in enumerate(opens):  # lintels, sills, glass, frames, leaves
        x0, y0, x1, y1 = r
        head = DOOR_H if kind in ("door", "window") else VENT[1]
        base = 0.0 if kind == "door" else SILL if kind == "window" else VENT[0]
        if z + head < top:
            _box(boxes, f"{name}_lintel{k}", f"{name}_walls", style["wall"] if outer(r) else "plaster_inside", x0, y0, z + head, x1, y1, top)
        if base > 0:
            _box(
                boxes, f"{name}_sill{k}", f"{name}_walls", style["wall"] if outer(r) else "plaster_inside", x0, y0, z, x1, y1, z + min(base, top - z)
            )
        if kind != "door" and z + base < top:  # glass in the middle of the wall, a frame round it
            mid = (o["at"],)
            zt = z + min(head, top - z)
            if o["wall"] == "h":
                _box(boxes, f"{name}_glass{k}", f"{name}_glass", "glass", x0, mid[0] - 0.5, z + base, x1, mid[0] + 0.5, zt)
                for fx in ((x0, x0 + 2), (x1 - 2, x1)):
                    _box(boxes, f"{name}_frame{k}", f"{name}_frames", style["frame"], fx[0], mid[0] - 1.5, z + base, fx[1], mid[0] + 1.5, zt)
                for fz in ((z + base, z + base + 2), (zt - 2, zt)):
                    if fz[1] <= zt:
                        _box(boxes, f"{name}_frame{k}h", f"{name}_frames", style["frame"], x0 + 2, mid[0] - 1.5, fz[0], x1 - 2, mid[0] + 1.5, fz[1])
                if (x1 - x0) > 40:  # a mullion down the middle of a wide window
                    cx = (x0 + x1) / 2
                    _box(
                        boxes, f"{name}_frame{k}m", f"{name}_frames", style["frame"], cx - 1, mid[0] - 1.5, z + base + 2, cx + 1, mid[0] + 1.5, zt - 2
                    )
                if outer(r) and o.get("side") in ("front", "rear") and z + head + 4 <= top and kind == "window":  # a sunshade (chajja) over it
                    out = -1 if o.get("side") == "front" else 1
                    yy = (y0, y0 - 18) if out < 0 else (y1, y1 + 18)
                    _box(boxes, f"{name}_chajja{k}", f"{name}_walls", style["accent"], x0 - 6, min(yy), z + head, x1 + 6, max(yy), z + head + 4)
            else:
                _box(boxes, f"{name}_glass{k}", f"{name}_glass", "glass", mid[0] - 0.5, y0, z + base, mid[0] + 0.5, y1, zt)
                for fy in ((y0, y0 + 2), (y1 - 2, y1)):
                    _box(boxes, f"{name}_frame{k}", f"{name}_frames", style["frame"], mid[0] - 1.5, fy[0], z + base, mid[0] + 1.5, fy[1], zt)
                for fz in ((z + base, z + base + 2), (zt - 2, zt)):
                    _box(boxes, f"{name}_frame{k}h", f"{name}_frames", style["frame"], mid[0] - 1.5, y0 + 2, fz[0], mid[0] + 1.5, y1 - 2, fz[1])
        elif kind == "door" and o.get("kind") == "main" and cut is None:  # the front door, closed
            if o["wall"] == "h":
                _box(boxes, f"{name}_door{k}", f"{name}_doors", style["door"], x0, o["at"] - 1, z, x1, o["at"] + 1, z + DOOR_H)
            else:
                _box(boxes, f"{name}_door{k}", f"{name}_doors", style["door"], o["at"] - 1, y0, z, o["at"] + 1, y1, z + DOOR_H)
    for r in fl["rooms"]:  # floors
        mat = FLOORS.get(r["kind"], "marble")
        _box(boxes, f"{name}_floor_{r['id']}", f"{name}_floors", mat, r["x0"], r["y0"], z - 1, r["x1"], r["y1"], z)
        bt = r.get("bath")
        if isinstance(bt, dict):
            _box(boxes, f"{name}_floor_{r['id']}_bath", f"{name}_floors", FLOORS["bath"], bt["x0"], bt["y0"], z - 0.9, bt["x1"], bt["y1"], z + 0.05)
        if r["kind"] == "stairs":
            _stairs(boxes, r, z, H + SLAB, name)
    if with_furniture:
        rec = _Rec()
        DR._furnish(rec, fl, th)  # with the names' places kept clear, as on the drawing
        for k, b in enumerate(rec.blocks):
            for j, lb in enumerate(FURNITURE.get(b["name"], [])):
                x0, y0, z0, x1, y1, z1 = _place(lb, b)
                _box(boxes, f"{name}_furn{k}_{b['name']}_{j}", f"{name}_furniture", lb[6], x0, y0, z + z0, x1, y1, z + z1)
        for k, poly in enumerate(rec.polys):  # the L-shaped kitchen counter, as two boxes
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)
            _box(boxes, f"{name}_counter{k}a", f"{name}_furniture", "counter", X0, Y1 - 24, z, X1, Y1, z + 35)
            _box(boxes, f"{name}_counter{k}b", f"{name}_furniture", "counter", X0, Y0 + 12, z, X0 + 24, Y1 - 24, z + 35)
    return walls, opens


def _stairs(boxes, r, z, rise_total, name):
    """Steps rising rise_total from z, sized like built stairs: treads up to 11 in, risers near 7 in (steeper only when
    the room is short). A straight flight from the front; or a dog-leg: up one half to a landing at the back, then up the
    other half towards the front, its last step level with the next floor."""
    x0, y0, x1, y1 = r["x0"], r["y0"], r["x1"], r["y1"]
    if r.get("stair") == "straight" or (x1 - x0) < 70:
        n = max(2, min(round(rise_total / 7.0), int((y1 - y0 - 12) // 9) + 1))
        riser, tread = rise_total / n, min(11.0, (y1 - y0 - 12) / (n - 1))
        for k in range(n):  # the last step is the floor above's edge: it runs on to the back of the room
            ye = y1 if k == n - 1 else y0 + (k + 1) * tread
            _box(boxes, f"{name}_step{k}", f"{name}_stairs", "marble", x0, y0 + k * tread, z, x1, ye, z + (k + 1) * riser)
        return
    n = max(4, round(rise_total / 7.0))
    first = n - n // 2  # the flight up to the landing takes the extra step, so the way back ends inside the room
    second = n - first
    land_min = 36.0
    tread = min(11.0, (y1 - y0 - land_min) / first)
    riser = rise_total / n
    mid = (x0 + x1) / 2
    yl = y0 + first * tread  # where the landing starts; it runs to the back wall
    for k in range(first):
        _box(boxes, f"{name}_step{k}", f"{name}_stairs", "marble", x0, y0 + k * tread, z, mid - 1, y0 + (k + 1) * tread, z + (k + 1) * riser)
    _box(boxes, f"{name}_landing", f"{name}_stairs", "marble", x0, yl, z, x1, y1, z + first * riser)
    for k in range(second):
        ya = yl - (k + 1) * tread
        _box(boxes, f"{name}_step{first + k}", f"{name}_stairs", "marble", mid + 1, ya, z, x1, ya + tread, z + (first + k + 1) * riser)
    _box(boxes, f"{name}_stairwall", f"{name}_stairs", "plaster_inside", mid - 1, y0, z, mid + 1, yl, z + rise_total)


def _facade(boxes, lay, storeys, st):
    """The front made to look designed, the way modern Pakistani elevations are: a cladding panel (stone or wood, by
    style) round each front window, standing 1.5 in proud of the wall, cut round the window, from the floor to the slab."""
    env = lay["envelope"]
    for nm, fl, zf in storeys:
        for k, w in enumerate(x for x in fl.get("windows", []) if x.get("side") == "front" and x.get("kind") == "window"):
            px0, px1 = max(env[0] + 6, w["a"] - 18), min(env[2] - 6, w["b"] + 18)
            hole = (w["a"] - 0.5, zf + SILL - 0.5, w["b"] + 0.5, zf + DOOR_H + 4.5)  # in the facade's plane: x across, z up
            for j, r in enumerate(_rect_minus([(px0, zf, px1, zf + CLEAR_H)], [hole])):
                _box(boxes, f"out_{nm}_clad{k}_{j}", "out_cladding", st["accent"], r[0], env[1] - 1.5, r[1], r[2], env[1], r[3])


def _outline_band(rects, t):
    """A band t wide along the inside of the outline of a union of rectangles (a parapet), as disjoint rectangles."""
    band = []
    for loop in DR.union(rects):
        n = len(loop)
        for i in range(n):
            (ax, ay), (bx, by) = loop[i], loop[(i + 1) % n]
            if ay == by:  # the filled side is on the left of the way round: above for +x, below for -x
                y0, y1 = (ay, ay + t) if bx > ax else (ay - t, ay)
                band.append((min(ax, bx), y0, max(ax, bx), y1))
            else:  # left of +y is -x
                x0, x1 = (ax - t, ax) if by > ay else (ax, ax + t)
                band.append((x0, min(ay, by), x1, max(ay, by)))
    return _rect_minus(band, [])


def house_spec(lay, style="modern", view="all", floor="ground", furniture=True, labels=True, colors=None):
    """Boxes for the house. view: 'outside' (the whole building, roof and parapet), 'inside' (one storey cut at 8 ft,
    seen from above, with furniture and labels), or 'all' (both kinds of box, tagged by collection)."""
    st = dict(STYLES.get(style, STYLES["modern"]), **(colors or {}))
    boxes, labs = [], []
    W, D = lay["plot"]
    env = lay["envelope"]
    floors = [("ground", lay)] + ([("first", lay["upper"])] if lay.get("upper") else [])
    z = PLINTH
    storeys = []
    for k, (nm, fl) in enumerate(floors):
        storeys.append((nm, fl, z))
        z += CLEAR_H + SLAB
    # ---- outside: every storey full height, slabs, parapet, porch, boundary, ground
    if view in ("outside", "all"):
        for k, (nm, fl, zf) in enumerate(storeys):
            _floor(fl, zf, boxes, st, f"out_{nm}", cut=None, with_furniture=False)
            open_sky = [(r["x0"] - INNER, r["y0"] - OUTER, r["x1"] + INNER, r["y1"]) for r in fl["rooms"] if r["kind"] == "terrace"]
            roof = _rect_minus([tuple(env)], open_sky)  # a terrace has no slab over it
            for j, r in enumerate(roof):
                _box(boxes, f"out_{nm}_slab{j}", "out_slabs", "concrete_slab", r[0], r[1], zf + CLEAR_H, r[2], r[3], zf + CLEAR_H + SLAB)
            for j, r in enumerate(fl["rooms"]):
                if r["kind"] == "terrace":  # a railing wall along its open front
                    _box(boxes, f"out_{nm}_rail{j}", "out_parapet", st["parapet"], r["x0"], env[1], zf, r["x1"], env[1] + INNER, zf + PARAPET)
            if k == len(storeys) - 1:  # the parapet round the roof, following its outline
                top = zf + CLEAR_H + SLAB
                for j, r in enumerate(_outline_band(roof, INNER)):
                    _box(boxes, f"out_parapet{j}", "out_parapet", st["parapet"], r[0], r[1], top, r[2], r[3], top + PARAPET)
        porch = next((r for r in lay["rooms"] if r["kind"] == "porch"), None)
        if porch:  # columns at the porch's open front corners, the gate between them, a ramp up from the road
            for cx in (porch["x0"], porch["x1"] - 12):
                _box(boxes, "out_porch_col", "out_walls", st["accent"], cx, env[1], PLINTH, cx + 12, env[1] + 12, PLINTH + CLEAR_H)
            _box(
                boxes,
                "out_gate",
                "out_gate",
                "gate_metal",
                porch["x0"] + 12,
                env[1] + 3,
                PLINTH,
                porch["x1"] - 12,
                env[1] + 5,
                PLINTH + BOUNDARY_H - 12,
            )
            boxes.append({"n": "out_ramp", "c": "out_site", "m": "concrete", "w": [porch["x0"], -40, 2, porch["x1"], 0, PLINTH]})
        _box(boxes, "out_plinth", "out_site", "plinth", env[0] - 2, env[1] - 2, 0, env[2] + 2, env[3] + 2, PLINTH)
        if D > env[3] + 1:  # the open yard behind, walled
            _box(boxes, "out_yard", "out_site", "yard_tiles", 0, env[3], 0, W, D, 1)
            _box(boxes, "out_bwall_rear", "out_boundary", st["wall"], 0, D - INNER, 0, W, D, BOUNDARY_H)
            _box(boxes, "out_bwall_left", "out_boundary", st["wall"], 0, env[3], 0, INNER, D - INNER, BOUNDARY_H)
            _box(boxes, "out_bwall_right", "out_boundary", st["wall"], W - INNER, env[3], 0, W, D - INNER, BOUNDARY_H)
        _box(boxes, "out_road", "out_site", "asphalt", -480, -300, -1, W + 480, -60, 0)
        _box(boxes, "out_walk", "out_site", "sidewalk", -480, -60, -1, W + 480, 0, 2)
        _box(boxes, "out_land", "out_site", "site", -480, 0, -2, W + 480, D + 480, -1)
        _facade(boxes, lay, storeys, st)
    # ---- inside: one storey cut at 8 ft, with furniture and its rooms' names
    if view in ("inside", "all"):
        nm, fl, zf = next(((n, f, zz) for n, f, zz in storeys if n == floor), storeys[0])
        th = max(8.0, min(14.0, min(W, D) / 28))  # letters for the rooms' names, inches tall
        _floor(fl, zf, boxes, st, f"in_{nm}", cut=72.0, with_furniture=furniture, th=th if labels else 0.0)
        _box(boxes, f"in_{nm}_base", f"in_{nm}_base", "plinth", env[0] - 2, env[1] - 2, zf - SLAB - 1, env[2] + 2, env[3] + 2, zf - 1)
        if labels:  # each room's name and size where the drawing puts them: clear of doors, the bath and the counter
            for r in fl["rooms"]:
                if r["kind"] == "passage":
                    continue
                lb = DR._label_layout(r, th, DR._swing_zones(fl))
                cx, cy = lb["at"]
                text = "\n".join(x.title().replace("Tv ", "TV ") for x in lb["lines"])
                bw = lb["box"][2] - lb["box"][0] - 4  # the width the drawing keeps free for the words
                labs.append(
                    {"text": text, "x": cx, "y": cy + lb["h"] * 0.35, "z": zf + 0.5, "size": lb["h"] * 1.35, "floor": nm, "room": r["id"], "w": bw}
                )
                if lb.get("size_h"):
                    labs.append(
                        {
                            "text": lb["size"],
                            "x": cx,
                            "y": cy - lb["h"] * (0.75 + 0.55 * (len(lb["lines"]) - 1)),
                            "z": zf + 0.5,
                            "size": lb["size_h"] * 1.25,
                            "floor": nm,
                            "room": r["id"],
                            "kind": "size",
                            "w": bw,
                        }
                    )
    expect = {
        "doors": sum(len(f["doors"]) for _, f, _ in storeys),
        "windows": sum(len(f.get("windows", [])) for _, f, _ in storeys),
        "rooms": {nm: {r["id"]: round((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) / 144, 1) for r in f["rooms"]} for nm, f, _ in storeys},
        "height": storeys[-1][2] + CLEAR_H + SLAB + PARAPET,
        "storeys": len(storeys),
        "plot": [W, D],
        "envelope": env,
    }
    return {"boxes": boxes, "labels": labs, "expect": expect, "style": st, "unit": 0.0254, "floors": [n for n, _, _ in storeys]}
