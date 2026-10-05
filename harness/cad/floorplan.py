"""A house plan from a brief, the way plans are drawn for Pakistani plots: the road at the bottom, a car porch and the
drawing room at the front, the TV lounge, kitchen and stairs in the middle, bedrooms with attached baths at the back;
9" outer and 4.5" inner brick walls.

  brief = {"plot": [25, 45], "bedrooms": 2, "floors": 1}           feet; see BRIEF for every field
  lay = plan(brief)       -> {"rooms": [...], "doors": [...], "windows": [...], "notes": [...], ...}

The plan is searched, not templated. Rooms that may live in more than one band (stairs, store, powder, dining, servant,
guest) are placed where there is room; then the orders of the rooms in each band, the stair type (a dog-leg or a
straight flight), the side of each bath and a passage or not are tried, sized to the plot (minimums first, then
targets, then by weight) and scored on room sizes, proportions, the connections that need doors, and daylight. The
best layout wins. All lengths are inches; every room is a rectangle of clear floor (inside the walls); a bath sits in
the back corner of its bedroom.
"""
import itertools
import math

from .units import ft_in

OUTER, INNER = 9.0, 4.5
BRIEF = {"plot": [25, 45], "bedrooms": 2, "baths": "attached", "porch": True, "drawing": True, "dining": False, "store": False, "powder": False,
         "servant": False, "guest": False, "stairs": True, "floors": 1, "porch_side": None, "setbacks": None, "sizes": {}, "grow": {},
         "furniture": True, "name": "House", "client": "", "corner": False, "stair_type": None}
# kind: label, home band, min clear (w, d) feet, target area sq ft, weight (share of spare room), needs daylight
KINDS = {
    "porch": ("CAR PORCH", "front", (10.0, 15.0), 200, 1.0, False),
    "drawing": ("DRAWING ROOM", "front", (10.0, 10.5), 200, 2.2, True),
    "guest": ("GUEST ROOM", "front", (10.0, 10.0), 150, 1.6, True),
    "servant": ("SERVANT ROOM", "front", (8.0, 8.5), 80, 0.6, True),
    "lounge": ("TV LOUNGE", "middle", (10.0, 10.0), 260, 3.0, True),
    "dining": ("DINING", "middle", (9.0, 9.0), 140, 1.6, True),
    "kitchen": ("KITCHEN", "middle", (6.5, 8.0), 100, 1.2, True),
    "stairs": ("STAIRS", "middle", (6.5, 10.0), 70, 0.0, False),
    "store": ("STORE", "middle", (4.5, 5.0), 35, 0.3, False),
    "powder": ("POWDER", "middle", (4.0, 5.0), 25, 0.2, False),
    "bedroom": ("BED ROOM", "rear", (10.5, 11.0), 190, 2.6, True),
    "passage": ("PASSAGE", "passage", (3.5, 3.5), 0, 0.0, False),
    "terrace": ("TERRACE", "front", (8.0, 10.0), 150, 1.0, False),
    "family": ("FAMILY LOUNGE", "middle", (10.0, 10.0), 220, 3.0, True),
}
MOVABLE = {"stairs": ["middle", "front"], "store": ["middle", "front", "rear"], "powder": ["middle", "front"], "dining": ["middle", "front"],
           "servant": ["front", "rear"], "guest": ["front", "rear"]}
STAIRS = {"dogleg": (78, 120), "straight": (42, 150)}  # clear width, run (inches): two 3' flights and a landing, or one 3'-6" flight
BATH_MIN, BATH_TARGET = (60, 84), (66, 96)  # inches: a corner bath 5' x 7' at least, 5'-6" x 8' when there is room
MAX_W = {"porch": 13 * 12, "store": 7 * 12, "powder": 6 * 12, "kitchen": 13 * 12, "servant": 11 * 12}
DOOR = {"main": 42, "room": 36, "bath": 30, "store": 30, "open": 48}


class PlanError(Exception):
    pass


def _label(kind, n=None):
    return KINDS[kind][0] + (f" {n}" if n else "")


def program(brief):
    """The rooms the brief asks for: [{"id", "kind", "label", "bath"}], and the brief with defaults filled in."""
    b = dict(BRIEF, **{k: v for k, v in brief.items() if v is not None})
    W, D = b["plot"]
    rooms = []
    if b["porch"] and W >= 18:
        rooms.append({"id": "porch", "kind": "porch"})
    if b["drawing"]:
        rooms.append({"id": "drawing", "kind": "drawing"})
    if b["guest"]:
        rooms.append({"id": "guest", "kind": "guest"})
    if b["servant"]:
        rooms.append({"id": "servant", "kind": "servant"})
    rooms.append({"id": "lounge", "kind": "lounge"})
    if b["dining"]:
        rooms.append({"id": "dining", "kind": "dining"})
    rooms.append({"id": "kitchen", "kind": "kitchen"})
    if b["stairs"] or b["floors"] > 1:
        rooms.append({"id": "stairs", "kind": "stairs"})
    if b["store"]:
        rooms.append({"id": "store", "kind": "store"})
    if b["powder"]:
        rooms.append({"id": "powder", "kind": "powder"})
    n = int(b["bedrooms"])
    for i in range(1, n + 1):
        rooms.append({"id": f"bed{i}", "kind": "bedroom", "bath": b["baths"] in ("attached", True, "yes")})
    for r in rooms:
        r["label"] = _label(r["kind"], int(r["id"][3:]) if r["kind"] == "bedroom" and n > 1 else None)
    return rooms, b


class Item:
    def __init__(self, room, axis, brief, stair="dogleg"):
        k = KINDS[room["kind"]]
        grow = float(brief["grow"].get(room["id"], brief["grow"].get(room["kind"], 0)) or 0)
        want = brief["sizes"].get(room["id"]) or brief["sizes"].get(room["kind"])
        self.room = room
        self.min = k[2][0] * 12 if axis == "w" else k[2][1] * 12
        if room["kind"] == "stairs":
            self.min = STAIRS[stair][0] if axis == "w" else STAIRS[stair][1]
        if room["kind"] == "bedroom" and room.get("bath"):
            self.min = max(self.min, BATH_MIN[0] + 66) if axis == "w" else max(self.min, BATH_MIN[1] + 60)
        side = math.sqrt(k[3]) * 12
        self.target = max(self.min, side * (1 + 0.12 * grow)) if room["kind"] != "stairs" else self.min
        self.weight = k[4] * (1 + 0.35 * grow)
        self.max = MAX_W.get(room["kind"], 10 ** 6) if axis == "w" else 10 ** 6
        if room["kind"] == "stairs":
            self.max = self.min + 24 if axis == "w" else 10 ** 6
        if want:
            v = want[0] * 12 if axis == "w" else want[1] * 12
            self.min = self.target = v
            self.max = v + 0.5
            self.weight = 0.0
        i = 0 if axis == "w" else 1
        lo = (brief.get("min") or {}).get(room["id"]) or (brief.get("min") or {}).get(room["kind"])
        hi = (brief.get("max") or {}).get(room["id"]) or (brief.get("max") or {}).get(room["kind"])
        if lo and lo[i]:  # 'make the kitchen bigger': at least this much
            self.min = max(self.min, lo[i] * 12)
            self.target = max(self.target, self.min)
        if hi and hi[i]:  # 'make the drawing room smaller': at most this much, never under the room's minimum
            self.max = max(self.min, min(self.max, hi[i] * 12))
            self.target = min(self.target, self.max)


def split(total, items):
    """Clear sizes for items side by side in total inches (inner walls between them), or None when the minimums do not fit."""
    avail = total - INNER * (len(items) - 1)
    sizes = [i.min for i in items]
    if sum(sizes) > avail + 0.5:
        return None
    extra = avail - sum(sizes)
    need = [max(0.0, i.target - i.min) for i in items]
    if sum(need) > 0 and extra > 0:
        f = min(1.0, extra / sum(need))
        sizes = [s + n * f for s, n in zip(sizes, need)]
        extra = avail - sum(sizes)
    for _ in range(12):
        free = [j for j, i in enumerate(items) if sizes[j] < i.max - 0.5 and i.weight > 0]
        if extra <= 0.25 or not free:
            break
        tw = sum(items[j].weight for j in free)
        for j in free:
            sizes[j] = min(items[j].max, sizes[j] + extra * items[j].weight / tw)
        extra = avail - sum(sizes)
    if extra > 0.25:  # everyone is at their maximum: the most important room that may still grow takes the rest
        js = [j for j in range(len(items)) if items[j].max >= 10 ** 5] or list(range(len(items)))
        j = max(js, key=lambda j: (items[j].weight, -items[j].max))
        sizes[j] += extra
    out = [math.floor(s) for s in sizes]
    rest = round(avail - sum(out))  # the inches lost to rounding: to the most important room that has room for them
    js = [j for j in range(len(out)) if out[j] + rest <= items[j].max + 0.5] or list(range(len(out)))
    out[max(js, key=lambda j: items[j].weight)] += rest
    return out


def _shared(a, b):
    """Length of the wall two clear rectangles share (one inner wall apart), and the wall: (orientation, line, lo, hi)."""
    if abs(a["y1"] + INNER - b["y0"]) < 0.6 or abs(b["y1"] + INNER - a["y0"]) < 0.6:
        lo, hi = max(a["x0"], b["x0"]), min(a["x1"], b["x1"])
        y = (a["y1"] + b["y0"]) / 2 if a["y1"] < b["y0"] else (b["y1"] + a["y0"]) / 2
        return max(0.0, hi - lo), ("h", y, lo, hi)
    if abs(a["x1"] + INNER - b["x0"]) < 0.6 or abs(b["x1"] + INNER - a["x0"]) < 0.6:
        lo, hi = max(a["y0"], b["y0"]), min(a["y1"], b["y1"])
        x = (a["x1"] + b["x0"]) / 2 if a["x1"] < b["x0"] else (b["x1"] + a["x0"]) / 2
        return max(0.0, hi - lo), ("v", x, lo, hi)
    return 0.0, None


NEEDS = [("lounge", "kitchen", "room", 8), ("lounge", "stairs", "open", 5), ("lounge", "dining", "open", 3), ("dining", "kitchen", "room", 4),
         ("kitchen", "store", "store", 2), ("lounge", "powder", "bath", 2), ("drawing", "lounge", "room", 1.5), ("porch", "drawing", "room", 3),
         ("porch", "lounge", "main", 4), ("porch", "servant", "store", 2), ("lounge", "guest", "room", 2)]


def _reach(rooms, a, b, kind):
    ln, _ = _shared(rooms[a], rooms[b])
    return ln >= DOOR[kind] + 8


def _best_reach(rooms, rid, vias, kind="room"):
    return max([_shared(rooms[v], rooms[rid])[0] for v in vias if v in rooms] or [0.0])


def _score(lay):
    """Lower is better: size misses, awkward shapes, missing connections, rooms without daylight."""
    pen = 0.0
    rooms = {r["id"]: r for r in lay["rooms"]}
    for r in lay["rooms"]:
        k = KINDS[r["kind"]]
        if r["kind"] == "passage":
            continue
        w, d = (r["x1"] - r["x0"]) / 12, (r["y1"] - r["y0"]) / 12
        area = w * d - (r["bath"]["w"] * r["bath"]["d"] / 144 if r.get("bath") else 0)
        if k[3] and r["kind"] != "stairs":
            pen += abs(area - k[3]) / k[3] * (1.5 if k[4] >= 2 else 0.6)
        ratio = max(w, d) / max(min(w, d), 0.1)
        limit = 3.0 if r["kind"] in ("porch", "stairs", "store", "powder") else 1.9
        if ratio > limit:
            pen += (ratio - limit) * 4
        if k[5] and not r.get("outside"):
            pen += 0.8
    for a, b, kind, wgt in NEEDS:
        if a in rooms and b in rooms and not _reach(rooms, a, b, kind):
            pen += wgt
    if "stairs" in rooms and not any(o in rooms and _reach(rooms, o, "stairs", "open") for o in ("lounge", "passage", "porch", "dining")):
        pen += 30
    if "kitchen" in rooms and not any(o in rooms and _reach(rooms, o, "kitchen", "room") for o in ("lounge", "dining")):
        pen += 30
    for r in lay["rooms"]:  # every bedroom reaches the lounge, a passage or the dining, with room to spare for the door
        if r["kind"] == "bedroom" or r["id"] == "guest":
            ln = _best_reach(rooms, r["id"], ("lounge", "passage", "family", "dining"))
            if ln < DOOR["room"] + 8:
                pen += 50
            elif ln < DOOR["room"] + 24:
                pen += 1.0
    if "passage" in rooms:
        pen += 3.0
    pen += 0.5 * lay.get("rows", 1) - 0.5
    pen += 40 * len(unreachable(lay))
    return pen


def _bath(cell, side, end="rear"):
    """A bath in a corner of a bedroom: the corner on the outside wall (the back for the back rooms, the front for a
    front room) so it can have a vent; side 'left' or 'right'."""
    w = min(BATH_TARGET[0], max(BATH_MIN[0], (cell["x1"] - cell["x0"]) * 0.42))
    d = min(BATH_TARGET[1], max(BATH_MIN[1], (cell["y1"] - cell["y0"]) * 0.55))
    x0, x1 = (cell["x0"], cell["x0"] + w) if side == "left" else (cell["x1"] - w, cell["x1"])
    y0, y1 = (cell["y1"] - d, cell["y1"]) if end == "rear" else (cell["y0"], cell["y0"] + d)
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "w": w, "d": d, "side": side, "end": end}


def _setbacks(W, D):
    if W < 40 * 12:  # row houses: built to the front and the sides, a little open space at the back for light and air
        return {"front": 0, "rear": 36 if D <= 50 * 12 else 60, "left": 0, "right": 0}
    return {"front": 120 if D >= 80 * 12 else 60, "rear": 60, "left": 36, "right": 36}


def _assignments(by, clear_w, b):
    """Ways to place the movable rooms so that every band's minimum widths fit (the fewest moves first, at most four)."""
    def need(rs, stair):
        cols = _columns(rs, 10 ** 6, b, stair)
        return sum(_col_item(c, "w", b, stair).min for c in cols) + INNER * max(0, len(cols) - 1)
    out = []
    mv = dict(MOVABLE, kitchen=["middle", "rear"]) if b.get("_kitchen_rear") else MOVABLE  # small plots: the kitchen may go to the back
    movable = [r for band in ("middle", "front", "rear") for r in by[band] if r["kind"] in mv]
    for combo in itertools.product(*[mv[r["kind"]] for r in movable]) if movable else [()]:
        asg = {k: [r for r in v if r["kind"] not in mv] for k, v in by.items()}
        for r, band in zip(movable, combo):
            asg[band].append(r)
        stairs_ok = [s for s in STAIRS if all(need(asg[k], s) <= clear_w + 0.5 for k in asg)]
        if stairs_ok:
            moved = sum(1 for r, band in zip(movable, combo) if band != KINDS[r["kind"]][1])
            out.append((moved, asg, stairs_ok))
    out.sort(key=lambda x: x[0])
    return [(a, s) for _, a, s in out[:4]]


SMALL = {"store": ("kitchen", "dining", "stairs", "servant"), "powder": ("stairs", "dining", "kitchen", "drawing")}
ROW_MAX = 20 * 12  # a middle band deeper than this is better as two rows of rooms


def _columns(rs, depth, b, stair):
    """A band's rooms as columns, front to back: a store or powder room stacks behind a neighbour it belongs with
    (a store behind the kitchen, a powder room behind the stairs) when the band is deep enough for both."""
    cols = [[r] for r in rs]
    changed = True
    while changed:
        changed = False
        for j, col in enumerate(cols):
            if len(col) != 1 or col[0]["kind"] not in SMALL:
                continue
            small = col[0]
            for pk in SMALL[small["kind"]]:
                for k in (j - 1, j + 1):
                    if 0 <= k < len(cols) and len(cols[k]) == 1 and cols[k][0]["kind"] == pk:
                        need = Item(cols[k][0], "d", b, stair).min + INNER + Item(small, "d", b, stair).min
                        if depth >= need:
                            cols[k] = [cols[k][0], small]
                            del cols[j]
                            changed = True
                            break
                if changed:
                    break
            if changed:
                break
    return cols


def _col_item(col, axis, b, stair):
    it = Item(col[0], axis, b, stair)
    if len(col) > 1 and axis == "w":
        it.min = max(it.min, Item(col[1], "w", b, stair).min)
    if len(col) > 1 and axis == "d":
        it.min = it.min + INNER + Item(col[1], "d", b, stair).min
        it.target = it.target + INNER + Item(col[1], "d", b, stair).target
    return it


def plan(brief, budget_s=2.5):
    rooms, b = program(brief)
    W, D = (v * 12 for v in b["plot"])
    sb = dict(b["setbacks"] or _setbacks(W, D))
    ex0, ex1 = sb["left"], W - sb["right"]
    ey0, ey1 = sb["front"], D - sb["rear"]
    cx0, cx1, cy0, cy1 = ex0 + OUTER, ex1 - OUTER, ey0 + OUTER, ey1 - OUTER
    clear_w, clear_d = cx1 - cx0, cy1 - cy0
    by = {"front": [r for r in rooms if KINDS[r["kind"]][1] == "front"], "middle": [r for r in rooms if KINDS[r["kind"]][1] == "middle"],
          "rear": [r for r in rooms if KINDS[r["kind"]][1] == "rear"]}
    notes = []
    bed_min = Item({"id": "bed", "kind": "bedroom", "bath": b["baths"] in ("attached", True, "yes")}, "w", b).min
    fit = max(1, int((clear_w + INNER) // (bed_min + INNER)))
    while len(by["rear"]) > fit:  # bedrooms that cannot sit side by side at the back: the front band, or the next floor
        extra = by["rear"].pop()
        front_min = sum(Item(r, "w", b).min for r in by["front"]) + INNER * len(by["front"])
        if front_min + bed_min <= clear_w:
            by["front"].append(extra)
            notes.append(f"{extra['label']} is at the front: only {fit} bedroom(s) fit side by side at the back of a {b['plot'][0]}' wide plot")
        else:
            notes.append(f"{extra['label']} does not fit on the ground floor of a {b['plot'][0]}' wide plot" +
                         (" (it is on the first floor)" if b["floors"] > 1 else "; build a first floor for it, or take a wider plot"))
            rooms = [r for r in rooms if r["id"] != extra["id"]]
    asgs = _assignments(by, clear_w, b)
    dropped = []
    while not asgs:  # even the smallest sizes do not fit: optional rooms go first
        opt = next((r for r in rooms if r["kind"] in ("powder", "store", "servant", "dining", "guest")), None)
        if opt is None:
            break
        rooms = [r for r in rooms if r["id"] != opt["id"]]
        for k in by:
            by[k] = [r for r in by[k] if r["id"] != opt["id"]]
        dropped.append(opt["label"])
        asgs = _assignments(by, clear_w, b)
    if dropped:
        notes.append(f"left out to make it fit: {', '.join(dropped)}")
    best, tried = None, 0
    deadline = __import__("time").perf_counter() + budget_s
    porch_sides = [b["porch_side"]] if b["porch_side"] in ("left", "right") else ["left", "right"]
    env = (ex0, ey0, ex1, ey1)
    out_of_time = False
    for passage in (False, True):
        for asg, stair_types in asgs:
            if b.get("stair_type") in STAIRS:
                stair_types = [s for s in stair_types if s == b["stair_type"]] or stair_types
            for mo in _orders(asg["middle"], "middle", porch_sides):
                for rows in ([mo] + [[mo[:k], mo[k:]] for k in range(2, len(mo) - 1)] if len(mo) >= 4 else [mo]):
                    rows = rows if isinstance(rows[0], list) else [rows]
                    for fo in _orders(asg["front"], "front", porch_sides):
                        for ro in _orders(asg["rear"], "rear", porch_sides):
                            for stair in stair_types:
                                lay = _try(fo, rows, ro, passage, stair, b, cx0, cy0, clear_w, clear_d, env, sb)
                                tried += 1
                                if lay is not None:
                                    s = _score(lay)
                                    if best is None or s < best[0]:
                                        best = (s, lay)
                                if tried % 50 == 0 and __import__("time").perf_counter() > deadline:
                                    out_of_time = True
                                    break
                            if out_of_time:
                                break
                        if out_of_time:
                            break
                    if out_of_time:
                        break
                if out_of_time:
                    break
            if out_of_time:
                break
        if out_of_time or (best is not None and best[0] < 40):
            break
    if best is None:
        pw, pd = b["plot"]
        opt = next((k for k in ("powder", "store", "servant", "guest", "dining") if b.get(k)), None)
        if opt is not None:
            lay = plan({**brief, opt: False}, budget_s)  # an optional room that does not fit is left out, and said so
            lay["notes"].insert(0, f"no room for a {KINDS[opt][0].lower()} on a {pw:g}' x {pd:g}' plot with these rooms, so it is left out"
                                + (" (the space under the stairs is the usual store)" if opt == "store" and any(r["kind"] == "stairs" for r in lay["rooms"]) else ""))
            lay["dropped"] = [opt] + lay.get("dropped", [])
            return lay
        if not b.get("_kitchen_rear"):  # a small plot: the kitchen at the back, beside the bedroom
            return plan({**brief, "_kitchen_rear": True}, budget_s)
        for key, note in (("porch", f"no room for a car porch on a {pw:g}' x {pd:g}' plot with these rooms: the front door opens from the road"),
                          ("drawing", "no room for a separate drawing room: the TV lounge is the sitting room")):
            if b.get(key):
                lay = plan({**brief, key: False}, budget_s)
                lay["notes"].insert(0, note)
                lay["dropped"] = [key] + lay.get("dropped", [])
                return lay
        n = int(b["bedrooms"])
        if n > 1:  # the last bedroom does not fit on this floor
            lay = plan({**brief, "bedrooms": n - 1}, budget_s)
            lay["notes"].insert(0, f"BED ROOM {n} does not fit on the ground floor of a {pw:g}' x {pd:g}' plot")
            lay["dropped"] = [f"bed{n}"] + lay.get("dropped", [])
            return lay
        raise PlanError(f"these rooms do not fit a {pw:g}' x {pd:g}' plot even at their smallest; take out a room or use a bigger plot")
    lay = best[1]
    if best[0] >= 40:  # still a room without a door: the baths go the other way round (the door may then fit)
        pass
    for pat in ("outer",):  # baths back to back ('inner', one plumbing wall) or against the side walls: keep the better
        alt = _place_baths({**lay, "rooms": [dict(r) for r in lay["rooms"]]}, cx0 + clear_w / 2, pat)
        if _score(alt) < _score(lay) - 0.01:
            lay = alt
    if lay.get("lawn"):
        sb["rear"] += lay["lawn"]
        ey1 -= lay["lawn"]
        notes.append(f"the rooms are at full size, so {lay['lawn'] / 12:.0f}' more is left open at the back (a back lawn)")
    lay.update(score=round(_score(lay), 2), tried=tried, notes=notes, brief=b, plot=[W, D], setbacks=sb, envelope=[ex0, ey0, ex1, ey1],
               clear=[cx0, cy0, cx1, ey1 - OUTER], floor="GROUND FLOOR")
    _openings(lay)
    if b["floors"] > 1:
        lay["upper"] = upper(lay)
    return lay


def _orders(rs, band, porch_sides):
    """The orders worth trying for one band's rooms."""
    if not rs:
        return [[]]
    out = []
    for perm in itertools.permutations(rs):
        kinds = [r["kind"] for r in perm]
        if "porch" in kinds:
            pi = kinds.index("porch")
            if pi not in (0, len(perm) - 1) or ("left" if pi == 0 else "right") not in porch_sides:
                continue
        if band == "middle" and "stairs" in kinds and len(kinds) > 3 and kinds.index("stairs") not in (0, len(kinds) - 1):
            continue
        if band == "rear" and [r["id"] for r in perm if r["kind"] == "bedroom"] != sorted(r["id"] for r in perm if r["kind"] == "bedroom"):
            continue  # bedrooms keep their numbers left to right
        out.append(list(perm))
    return out or [list(rs)]


def _place_baths(lay, mid, pat):
    for c in lay["rooms"]:
        if c["kind"] == "bedroom" and c.get("bath"):
            towards_middle = "right" if (c["x0"] + c["x1"]) / 2 < mid else "left"
            side = towards_middle if pat == "inner" else ("left" if towards_middle == "right" else "right")
            end = "front" if c.get("band") == "front" else "rear"
            c["bath"] = _bath(c, side, end)
    lay["bath_pattern"] = pat
    return lay


def _try(fo, rows, ro, passage, stair, b, cx0, cy0, clear_w, clear_d, env, sb):
    """One candidate: bands front to back (the front rooms, one or two middle rows, a passage, the back rooms), each
    sized, its rooms in columns (a store or powder room stacked behind its neighbour)."""
    bands = [("front", fo)] + [("middle" if i == 0 else "middle2", r) for i, r in enumerate(rows)] + \
        ([("passage", [{"id": "passage", "kind": "passage", "label": "PASSAGE"}])] if passage else []) + [("rear", ro)]
    bands = [(n, rs) for n, rs in bands if rs]
    items = []
    for name, rs in bands:
        cols = _columns(rs, ROW_MAX * 1.2, b, stair)
        it = Item({"id": name, "kind": rs[0]["kind"]}, "d", b, stair)
        it.min = max(_col_item(c, "d", b, stair).min for c in cols)
        if name == "passage":
            it.min, it.target, it.max, it.weight = 42, 42, 43, 0
        else:
            it.target = max(it.min, max(_col_item(c, "d", b, stair).target for c in cols) * (0.95 if name.startswith("middle") else 1.0))
            it.weight = {"front": 1.0, "middle": 2.5, "middle2": 2.0, "rear": 1.6}[name]
            it.max = {"front": 21 * 12, "middle": ROW_MAX, "middle2": ROW_MAX, "rear": 16 * 12}[name]
            caps = [Item(c[0], "d", b, stair).max for c in cols if len(c) == 1]  # a room asked to be shallower caps its band
            it.max = max(it.min, min([it.max] + caps))
            it.target = min(it.target, it.max)
        items.append(it)
    lawn = 0
    room_for = sum(i.max for i in items) + INNER * (len(items) - 1)
    if clear_d > room_for + 24:  # more depth than the rooms can use: leave the rest open at the back
        lawn = clear_d - room_for
    ds = split(clear_d - lawn, items)
    if ds is None:
        return None
    cells, y = [], cy0
    for (name, rs), d in zip(bands, ds):
        if name == "passage":
            cells.append({"id": "passage", "kind": "passage", "label": "PASSAGE", "x0": cx0, "x1": cx0 + clear_w, "y0": y, "y1": y + d, "band": name})
        else:
            cols = _columns(rs, d, b, stair)
            ws = split(clear_w, [_col_item(c, "w", b, stair) for c in cols])
            if ws is None:
                return None
            x = cx0
            for col, w in zip(cols, ws):
                if len(col) == 1:
                    c = dict(col[0], x0=x, x1=x + w, y0=y, y1=y + d, band=name)
                    cells.append(c)
                else:  # main room at the front of the column, the small one behind it
                    main, small = col
                    sd = min(max(Item(small, "d", b, stair).target, Item(small, "d", b, stair).min), d - INNER - Item(main, "d", b, stair).min)
                    cells.append(dict(main, x0=x, x1=x + w, y0=y, y1=y + d - sd - INNER, band=name))
                    cells.append(dict(small, x0=x, x1=x + w, y0=y + d - sd, y1=y + d, band=name))
                x += w + INNER
        y += d + INNER
    for c in cells:
        if c["kind"] == "stairs":
            c["stair"] = stair
            if c["y1"] - c["y0"] < STAIRS[stair][1]:
                return None
    lay = {"rooms": cells, "bands": [(n, d) for (n, _), d in zip(bands, ds)], "passage": passage, "stair": stair, "rows": len(rows), "lawn": lawn}
    _place_baths(lay, cx0 + clear_w / 2, "inner")
    for c in cells:
        c["outside"] = []
        if abs(c["y0"] - (env[1] + OUTER)) < 0.6:
            c["outside"].append("front")
        if abs(c["y1"] - (env[3] - lawn - OUTER)) < 0.6:
            c["outside"].append("rear")
        if sb["left"] > 0 and abs(c["x0"] - (env[0] + OUTER)) < 0.6:
            c["outside"].append("left")
        if (sb["right"] > 0 or b.get("corner")) and abs(c["x1"] - (env[2] - OUTER)) < 0.6:
            c["outside"].append("right")
    return lay


def _doors(lay):
    """Doors on the walls rooms share: the main entrance from the porch, the drawing room, kitchen, stairs, dining,
    store and powder room to where they belong, each bedroom to the lounge or a passage, each bath into its bedroom.
    Returns (doors, notes)."""
    rooms = {r["id"]: r for r in lay["rooms"]}
    doors, notes = [], []

    def door(a, b, kind, into=None, prefer=None):
        if a not in rooms or b not in rooms:
            return False
        ln, wall = _shared(rooms[a], rooms[b])
        w = DOOR[kind]
        if wall is None or ln < w + 8:
            return False
        o, at, lo, hi = wall
        if kind == "open":
            w = min(ln - 12, max(w, ln * 0.5))
            s_ = lo + (ln - w) / 2
        elif prefer == "middle":
            s_ = lo + (ln - w) / 2
        else:
            used = [d for d in doors if d["wall"] == o and abs(d["at"] - at) < 1]
            s_ = lo + 6 if prefer != "hi" else hi - 6 - w
            if any(not (s_ + w <= d["a"] - 6 or s_ >= d["b"] + 6) for d in used):
                s_ = hi - 6 - w if prefer != "hi" else lo + 6
                if any(not (s_ + w <= d["a"] - 6 or s_ >= d["b"] + 6) for d in used):
                    return False
        doors.append({"wall": o, "at": at, "a": s_, "b": s_ + w, "kind": kind, "from": a, "to": b, "into": into or b,
                      "hinge": "a" if s_ - lo < hi - (s_ + w) else "b"})
        return True

    if "porch" not in rooms and lay.get("floor") != "FIRST FLOOR":  # no porch: the front door opens from the road into the room that leads in
        for rid in ("lounge", "drawing", "passage", "dining"):
            r = rooms.get(rid)
            if r and abs(r["y0"] - min(q["y0"] for q in lay["rooms"])) < 0.6 and r["x1"] - r["x0"] >= DOOR["main"] + 16:
                a0 = r["x0"] + 8
                doors.append({"wall": "h", "at": r["y0"] - OUTER / 2, "a": a0, "b": a0 + DOOR["main"], "kind": "main", "from": "outside", "to": rid,
                              "into": rid, "hinge": "a"})
                break
    if "porch" in rooms:
        if not door("porch", "lounge", "main", into="lounge"):
            if not door("porch", "drawing", "main", into="drawing") and not door("porch", "passage", "main", into="passage"):
                notes.append("no wall between the porch and the lounge for a main door")
        if "drawing" in rooms and not any(d["to"] == "drawing" for d in doors):
            door("porch", "drawing", "room", into="drawing")
    if not door("drawing", "lounge", "room", into="drawing"):  # the drawing room still needs a way into the house
        door("drawing", "dining", "room", into="drawing") or door("drawing", "passage", "room", into="drawing")
    if "kitchen" in rooms and not door("lounge", "kitchen", "room", into="kitchen") and not door("dining", "kitchen", "room", into="kitchen"):
        notes.append("the kitchen does not share a wall with the lounge or dining")
    if "stairs" in rooms and not (door("lounge", "stairs", "open", into="stairs") or door("passage", "stairs", "open", into="stairs")
                                  or door("porch", "stairs", "open", into="stairs") or door("family", "stairs", "open", into="stairs")
                                  or door("dining", "stairs", "open", into="stairs")):
        notes.append("the stairs are not reached from the lounge")
    door("lounge", "dining", "open", into="dining") or door("family", "dining", "open", into="dining")  # the first floor has a family lounge
    if "store" in rooms:
        any(door(v, "store", "store", into="store") for v in ("kitchen", "lounge", "family", "passage", "dining"))
    if "powder" in rooms:
        any(door(v, "powder", "bath", into="powder") for v in ("lounge", "family", "dining", "drawing", "passage"))
    if "servant" in rooms:
        door("porch", "servant", "store", into="servant") or any(door(v, "servant", "room", into="servant") for v in ("lounge", "family", "passage")) \
            or door("kitchen", "servant", "store", into="servant")
    if "passage" in rooms:
        door("lounge", "passage", "open", into="passage", prefer="middle") or door("family", "passage", "open", into="passage", prefer="middle") \
            or door("dining", "passage", "open", into="passage", prefer="middle")
    if "kitchenette" in rooms:  # the first floor
        door("family", "kitchenette", "room", into="kitchenette") or door("passage", "kitchenette", "room", into="kitchenette")
    if "terrace" in rooms:
        door("family", "terrace", "room", into="family") or any(door(r["id"], "terrace", "room", into=r["id"]) for r in lay["rooms"] if r["kind"] == "bedroom")
    linked = {d["from"] for d in doors} | {d["to"] for d in doors}
    for r in lay["rooms"]:  # a store or servant room nothing opens into: from any shared room beside it
        if r["id"] not in linked and r["kind"] in ("store", "servant", "powder"):
            any(door(p, r["id"], "bath" if r["kind"] == "powder" else "store", into=r["id"])
                for p in ("family", "lounge", "passage", "dining", "terrace", "porch", "kitchen", "kitchenette") if p in rooms)
    for r in lay["rooms"]:
        if r["kind"] == "bedroom" or r["id"] == "guest":
            if not any(door(via, r["id"], "room", into=r["id"], prefer="lo" if (r.get("bath") or {}).get("side") == "right" else "hi")
                       for via in ("passage", "lounge", "family", "dining", "porch")):
                notes.append(f"{r['label']} has no wall with the lounge or a passage for its door")
    for r in lay["rooms"]:  # a bath opens onto the open floor in front of it (its side stays free for the bed), at its inner corner
        bt = r.get("bath")
        if bt:
            y = bt["y0"] - INNER / 2 if bt.get("end", "rear") == "rear" else bt["y1"] + INNER / 2
            a0 = bt["x0"] + 4 if bt["side"] == "right" else bt["x1"] - 4 - DOOR["bath"]
            doors.append({"wall": "h", "at": y, "a": a0, "b": a0 + DOOR["bath"], "kind": "bath", "from": r["id"],
                          "to": r["id"] + "_bath", "into": r["id"] + "_bath", "hinge": "a" if bt["side"] == "right" else "b", "bath": True})
    return doors, notes


def unreachable(lay, doors=None):
    """Rooms that cannot be walked to from the entrance (the porch, else the front room) through the doors."""
    doors = doors if doors is not None else _doors(lay)[0]
    ids = [r["id"] for r in lay["rooms"]] + [r["id"] + "_bath" for r in lay["rooms"] if r.get("bath")]
    start = "porch" if any(r["id"] == "porch" for r in lay["rooms"]) else next((r["id"] for r in lay["rooms"] if "front" in r.get("outside", [])), ids[0])
    if any(d["from"] == "outside" for d in doors):
        ids, start = ids + ["outside"], "outside"
    if any(r["id"] == "terrace" for r in lay["rooms"]):
        start = "stairs" if any(r["id"] == "stairs" for r in lay["rooms"]) else start
    nb = {i: set() for i in ids}
    for d in doors:
        if d["from"] in nb and d["to"] in nb:
            nb[d["from"]].add(d["to"])
            nb[d["to"]].add(d["from"])
    seen, todo = {start}, [start]
    while todo:
        for n in nb[todo.pop()]:
            if n not in seen:
                seen.add(n)
                todo.append(n)
    return [i for i in ids if i not in seen and i != "outside"]


def _openings(lay):
    """Doors (see _doors) and windows on the outside walls, with notes on what is missing."""
    doors, notes = _doors(lay)
    windows = []
    env = lay["envelope"]
    widths = {"bedroom": 48, "drawing": 60, "guest": 48, "lounge": 60, "family": 60, "kitchen": 36, "dining": 48, "servant": 36, "stairs": 30}
    for r in lay["rooms"]:
        for side in r.get("outside", []):
            if r["kind"] in ("porch", "passage", "store", "powder", "terrace"):
                continue
            if side in ("front", "rear"):
                lo, hi = r["x0"], r["x1"]
                bt = r.get("bath")
                at = env[1] + OUTER / 2 if side == "front" else env[3] - OUTER / 2
                if bt and side == bt.get("end", "rear"):  # the bath has this corner: the room's window goes beside it, the bath gets a vent
                    lo, hi = (bt["x1"] + INNER, r["x1"]) if bt["side"] == "left" else (r["x0"], bt["x0"] - INNER)
                    windows.append({"wall": "h", "at": at, "a": (bt["x0"] + bt["x1"]) / 2 - 12, "b": (bt["x0"] + bt["x1"]) / 2 + 12,
                                    "room": r["id"] + "_bath", "kind": "vent", "side": side})
                for d in doors:  # the front door's part of the wall is not for the window
                    if d["wall"] == "h" and abs(d["at"] - at) < 1 and d["a"] < hi and d["b"] > lo:
                        lo, hi = (d["b"] + 12, hi) if hi - (d["b"] + 12) >= (d["a"] - 12) - lo else (lo, d["a"] - 12)
                w = min(widths.get(r["kind"], 36), (hi - lo) * 0.6)
                if w >= 18:
                    windows.append({"wall": "h", "at": at, "a": (lo + hi) / 2 - w / 2, "b": (lo + hi) / 2 + w / 2, "room": r["id"], "kind": "window", "side": side})
            else:
                lo, hi = r["y0"], r["y1"]
                w = min(widths.get(r["kind"], 36), (hi - lo) * 0.5)
                at = env[0] + OUTER / 2 if side == "left" else env[2] - OUTER / 2
                windows.append({"wall": "v", "at": at, "a": (lo + hi) / 2 - w / 2, "b": (lo + hi) / 2 + w / 2, "room": r["id"], "kind": "window", "side": side})
    for r in lay["rooms"]:
        if KINDS[r["kind"]][5] and not r.get("outside"):
            notes.append(f"{r['label']} has no outside wall: give it a skylight or a ventilator" + (" and an exhaust fan" if r["kind"] == "kitchen" else ""))
    for u in unreachable(lay, doors):
        notes.append(f"{u} cannot be reached from the entrance")
    lay["doors"], lay["windows"] = doors, windows
    lay["notes"] = lay.get("notes", []) + notes


def upper(lay):
    """The first floor over the same walls (the stairs and the structure line up): a terrace over the porch, a bedroom
    over the drawing room, a family lounge over the TV lounge, a kitchenette, and the bedrooms with their baths."""
    rooms = []
    beds = sum(1 for r in lay["rooms"] if r["kind"] == "bedroom")
    for r in lay["rooms"]:
        u = {k: v for k, v in r.items()}
        if r["kind"] == "porch":
            u.update(kind="terrace", id="terrace", label="TERRACE")
        elif r["kind"] in ("drawing", "guest"):
            beds += 1
            u.update(kind="bedroom", id=f"bed{beds}", label=f"BED ROOM {beds}", bath=True)  # with its own bath in the front corner
        elif r["kind"] == "lounge":
            u.update(kind="family", id="family", label="FAMILY LOUNGE")
        elif r["kind"] == "kitchen":
            u.update(kind="store", id="kitchenette", label="KITCHENETTE")
        elif r["kind"] == "dining":  # open to the family lounge, as the dining is to the TV lounge below
            u.update(label="SITTING AREA")
        elif r["kind"] == "servant":
            u.update(kind="store", label="STORE")
        rooms.append(u)
    up = {k: v for k, v in lay.items() if k not in ("upper", "doors", "windows", "notes")}
    up.update(rooms=rooms, floor="FIRST FLOOR", notes=[])
    cx0, _, cx1, _ = up["clear"]
    for r in rooms:  # baths for the new bedrooms (the ones over the ground floor's bedrooms keep theirs)
        if r["kind"] == "bedroom" and r.get("bath") is True:
            if (r["x1"] - r["x0"]) >= BATH_MIN[0] + 66 and (r["y1"] - r["y0"]) >= BATH_MIN[1] + 60:
                mid = (cx0 + cx1) / 2
                r["bath"] = _bath(r, "left" if (r["x0"] + r["x1"]) / 2 < mid else "right", "front" if r.get("band") == "front" else "rear")
            else:
                r["bath"] = None
    _openings(up)
    rm = {r["id"]: r for r in rooms}
    up["notes"] = [n for n in up["notes"] if "TERRACE" not in n]
    return up


def summary(lay):
    """Each room's clear size and area, the covered area, for answers and checks."""
    out = []
    for r in lay["rooms"]:
        w, d = r["x1"] - r["x0"], r["y1"] - r["y0"]
        bt = r.get("bath")
        area = w * d - ((bt["w"] + INNER) * (bt["d"] + INNER) if bt else 0)
        out.append({"id": r["id"], "label": r["label"], "w": w, "d": d, "size": f"{ft_in(w)} x {ft_in(d)}", "area_sqft": round(area / 144, 1)})
        if bt:
            n = r["label"].split()[-1] if r["label"].split()[-1].isdigit() else ""
            out.append({"id": r["id"] + "_bath", "label": f"BATH {n}".strip(), "w": bt["w"], "d": bt["d"], "size": f"{ft_in(bt['w'])} x {ft_in(bt['d'])}",
                        "area_sqft": round(bt["w"] * bt["d"] / 144, 1)})
    e = lay["envelope"]
    covered = (e[2] - e[0]) * (e[3] - e[1]) / 144
    return {"rooms": out, "covered_sqft": round(covered), "plot_sqft": round(lay["plot"][0] * lay["plot"][1] / 144)}
