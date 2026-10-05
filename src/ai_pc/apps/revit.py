"""Revit (and ArchiCAD, Tekla, BIM viewers) by IFC, the building-model format they all open: a house planned by the CAD
lane (from words like '7 marla double story house with 3 bedrooms', or a saved .plan.json) written as a BIM model with
ifcopenshell: storeys, walls (cut round every door and window, with lintels and sills), doors, windows, floor slabs, and
every room as a named space with its floor area. Checked by opening the file again: the counts match the plan, the
geometry builds, and the IFC schema validator finds nothing wrong.

  'revit model of a 7 marla double story house with 3 bedrooms'   'ifc model from house.plan.json'
"""
import json
import re
from pathlib import Path

NAME, LABEL = "revit", "Revit / BIM: house plans as IFC models (walls, doors, windows, slabs, rooms with areas)"
EXAMPLES = ["revit model of a 7 marla double story house with 3 bedrooms", "ifc model from house.plan.json"]
M = 0.0254  # inches to metres
CLEAR_H, SLAB, DOOR_H, SILL = 126.0, 6.0, 84.0, 36.0
VENT = (78.0, 96.0)


def _box(x0, y0, z0, x1, y1, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    return [tuple(c * M for c in p) for p in v], [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]


def build(lay, path, title="House"):
    import ifcopenshell.api as api
    import ifcopenshell.api.aggregate  # noqa: F401  (each API part is its own module in 0.8+)
    import ifcopenshell.api.context  # noqa: F401
    import ifcopenshell.api.geometry  # noqa: F401
    import ifcopenshell.api.project  # noqa: F401
    import ifcopenshell.api.pset  # noqa: F401
    import ifcopenshell.api.root  # noqa: F401
    import ifcopenshell.api.spatial  # noqa: F401
    import ifcopenshell.api.unit  # noqa: F401
    import numpy as np

    from ai_pc.cad import draft as DR
    from ai_pc.three.house import _rect_minus
    f = api.project.create_file(version="IFC4")
    project = api.root.create_entity(f, ifc_class="IfcProject", name=title)
    api.unit.assign_unit(f, units=[api.unit.add_si_unit(f, unit_type="LENGTHUNIT"), api.unit.add_si_unit(f, unit_type="AREAUNIT"),
                                   api.unit.add_si_unit(f, unit_type="VOLUMEUNIT")])
    model = api.context.add_context(f, context_type="Model")
    body = api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
    site = api.root.create_entity(f, ifc_class="IfcSite", name="Plot")
    building = api.root.create_entity(f, ifc_class="IfcBuilding", name=title)
    api.aggregate.assign_object(f, products=[site], relating_object=project)
    api.aggregate.assign_object(f, products=[building], relating_object=site)

    def element(cls, name, storey, box, **attrs):
        e = api.root.create_entity(f, ifc_class=cls, name=name)
        for k, v in attrs.items():
            setattr(e, k, v)
        verts, faces = _box(*box)
        rep = api.geometry.add_mesh_representation(f, context=body, vertices=[verts], faces=[faces])
        api.geometry.assign_representation(f, product=e, representation=rep)
        api.geometry.edit_object_placement(f, product=e, matrix=np.eye(4))
        if cls == "IfcSpace":  # a room is part of the storey; walls, doors and slabs are contained in it
            api.aggregate.assign_object(f, products=[e], relating_object=storey)
        else:
            api.spatial.assign_container(f, products=[e], relating_structure=storey)
        return e

    floors = [("Ground floor", lay)] + ([("First floor", lay["upper"])] if lay.get("upper") else [])
    counts = {"walls": 0, "doors": 0, "windows": 0, "spaces": 0, "slabs": 0}
    rooms_out = []
    for n, (label, fl) in enumerate(floors):
        z = n * (CLEAR_H + SLAB)
        storey = api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=label)
        storey.Elevation = z * M
        api.aggregate.assign_object(f, products=[storey], relating_object=building)
        opens = [(DR._opening(fl, d), "door", d) for d in fl["doors"]] + [(DR._opening(fl, w), w.get("kind", "window"), w) for w in fl.get("windows", [])]
        for k, r in enumerate(_rect_minus(DR._wall_rects(fl), [o[0] for o in opens])):
            element("IfcWall", f"Wall {k + 1}", storey, (r[0], r[1], z, r[2], r[3], z + CLEAR_H))
            counts["walls"] += 1
        for k, (r, kind, o) in enumerate(opens):
            head = DOOR_H if kind in ("door", "window") else VENT[1]
            base = 0.0 if kind == "door" else SILL if kind == "window" else VENT[0]
            element("IfcWall", f"Lintel {k + 1}", storey, (r[0], r[1], z + head, r[2], r[3], z + CLEAR_H))
            if base:
                element("IfcWall", f"Sill {k + 1}", storey, (r[0], r[1], z, r[2], r[3], z + base))
            width = (o["b"] - o["a"]) * M
            if kind == "door":
                element("IfcDoor", f"Door {o.get('from', '')}-{o.get('to', '')}".strip("-") or f"Door {k + 1}", storey, (r[0], r[1], z + base, r[2], r[3], z + head),
                        OverallHeight=(head - base) * M, OverallWidth=width)
                counts["doors"] += 1
            else:
                element("IfcWindow", f"{'Ventilator' if kind != 'window' else 'Window'} {o.get('room', k + 1)}", storey,
                        (r[0], r[1], z + base, r[2], r[3], z + head), OverallHeight=(head - base) * M, OverallWidth=width)
                counts["windows"] += 1
        env = fl["envelope"]
        element("IfcSlab", f"{label} slab", storey, (env[0], env[1], z + CLEAR_H, env[2], env[3], z + CLEAR_H + SLAB), PredefinedType="FLOOR")
        counts["slabs"] += 1
        for r in fl["rooms"]:
            name = r.get("label") or r["kind"].replace("_", " ").title()
            sp = element("IfcSpace", name, storey, (r["x0"], r["y0"], z, r["x1"], r["y1"], z + CLEAR_H), LongName=name)
            area = (r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) * M * M
            q = api.pset.add_qto(f, product=sp, name="Qto_SpaceBaseQuantities")
            api.pset.edit_qto(f, qto=q, properties={"NetFloorArea": round(area, 3), "Height": round(CLEAR_H * M, 3)})
            counts["spaces"] += 1
            rooms_out.append((label, name, area))
    f.write(str(path))
    return counts, rooms_out


def check(path, counts, plot, floors):
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate
    f = ifcopenshell.open(str(path))
    got = {"walls": len(f.by_type("IfcWall")) - sum(1 for w in f.by_type("IfcWall") if w.Name.startswith(("Lintel", "Sill"))), "doors": len(f.by_type("IfcDoor")),
           "windows": len(f.by_type("IfcWindow")), "spaces": len(f.by_type("IfcSpace")), "slabs": len(f.by_type("IfcSlab"))}
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    lo, hi = [9e9] * 3, [-9e9] * 3
    for e in f.by_type("IfcWall") + f.by_type("IfcSlab"):  # every wall and slab really built by the geometry kernel
        v = ifcopenshell.geom.create_shape(settings, e).geometry.verts
        for i in range(3):
            lo[i], hi[i] = min(lo[i], *v[i::3]), max(hi[i], *v[i::3])
    top = floors * (CLEAR_H + SLAB) * M
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    return [("opened again: walls, doors, windows, rooms and slabs as planned", got == counts),
            ("every wall and slab builds as solid geometry, standing on the plot from the ground to the roof",
             lo[0] >= -0.01 and lo[1] >= -0.01 and hi[0] <= plot[0] * M + 0.01 and hi[1] <= plot[1] * M + 0.01 and abs(lo[2]) < 0.01 and abs(hi[2] - top) < 0.01),
            ("the IFC schema validator finds nothing wrong", not log.statements)], log.statements[:3]


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\brevit\b|\bifc\b|\bbim\b|\barchicad\b", c):
        return None
    f = find_file(text, ctx, {".json"})
    if f and f.endswith(".plan.json"):
        return {"op": "ifc", "plan": f, "words": None}
    if re.search(r"\b(?:house|home|marla|kanal|villa|bungalow)\b", c):
        return {"op": "ifc", "plan": None, "words": text}
    return None


def run(op, ctx):
    from ai_pc.cad import cadparse, floorplan
    if op.get("plan"):
        lay = json.loads(Path(op["plan"]).read_text(encoding="utf-8"))
        title = Path(op["plan"]).stem.replace(".plan", "")
    else:
        brief = cadparse.house_brief(op["words"].lower())
        lay = floorplan.plan(brief)
        title = f"{brief['plot'][0]}x{brief['plot'][1]} ft house"
    out = Path(ctx["out"]) / "bim"
    out.mkdir(parents=True, exist_ok=True)
    path = out / (re.sub(r"[^\w-]+", "_", title) + ".ifc")
    counts, rooms = build(lay, path, title)
    checks, problems = check(path, counts, lay["plot"], 2 if lay.get("upper") else 1)
    bad = [w for w, ok in checks if not ok]
    per = {}
    for storey, name, a in rooms:
        per.setdefault(storey, []).append(f"{name} {a * 10.7639:.0f} sq ft")
    return (f"BIM model {path}: {len(per)} storey(s), {counts['walls']} wall pieces, {counts['doors']} doors, {counts['windows']} windows, {counts['spaces']} rooms. " +
            " ".join(f"{s}: {', '.join(v)}." for s, v in per.items()) +
            " Revit: File > Open > IFC (or Insert > Link IFC); ArchiCAD: File > Open. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f" {problems}"))
