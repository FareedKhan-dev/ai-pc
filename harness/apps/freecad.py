"""SolidWorks, Fusion 360, Inventor, CATIA, Creo (by STEP) and FreeCAD itself (1.1.4 in tools/freecad, run headless by
FreeCADCmd): a mechanical part from words (a plate with holes, an L-bracket, a flange with bolt holes, a spacer, an
enclosure) built from FreeCAD's parametric objects (open the .FCStd and change a length: it rebuilds), exported as STEP
(what every CAD program opens) and STL (for 3D printing: 'slice it for ender 3'), with a picture. Checked inside FreeCAD:
a valid solid of the asked size with the asked holes, and the STEP read back has the same volume and size. Says the
weight in the chosen material.

  'solidworks plate 100x60x5 mm with 4 holes 6 mm, rounded corners 5 mm, aluminium'
  'fusion flange 80 mm diameter 10 mm thick, 6 holes 8 mm on 60 mm circle, centre hole 30 mm'   'make the holes 8 mm'
"""
import json
import os
import re
import struct
import subprocess
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "freecad", "SolidWorks / Fusion / Inventor / FreeCAD: parametric parts as FreeCAD + STEP + STL"
EXAMPLES = ["solidworks plate 100x60x5 mm with 4 holes 6 mm, rounded corners 5 mm, aluminium",
            "fusion flange 80 mm diameter 10 mm thick, 6 holes 8 mm on 60 mm circle, centre hole 30 mm", "make the holes 8 mm"]
HOME = ROOT / "tools" / "freecad"
DENSITY = {"steel": 7.85, "aluminium": 2.70, "brass": 8.50, "pla": 1.24, "abs": 1.04, "petg": 1.27, "wood": 0.60, "nylon": 1.14}
KINDS = {"bracket": r"l[- ]?bracket|bracket|angle", "flange": r"flange|disc|disk", "spacer": r"spacer|bushing|bush|sleeve|tube|standoff",
         "enclosure": r"enclosure|housing|case|box", "plate": r"plate|block|base|mount"}
TRIGGER = r"\b(?:solid\s*works|fusion(?:\s*360)?|inventor|freecad|catia|creo|step\s+file|cad\s+part|\.step|\.stp)\b"

JOB = r'''
import json, os, sys, traceback
import FreeCAD as App, Part
job = json.load(open(os.environ["AIPC_JOB"], encoding="utf-8"))
report = {}
try:
    s = job["spec"]
    doc = App.newDocument(job["name"])
    def box(n, l, w, h, x=0, y=0, z=0):
        b = doc.addObject("Part::Box", n); b.Length, b.Width, b.Height = l, w, h; b.Placement.Base = App.Vector(x, y, z); return b
    def cyl(n, d, h, x=0, y=0, z=0):
        c = doc.addObject("Part::Cylinder", n); c.Radius, c.Height = d / 2.0, h; c.Placement.Base = App.Vector(x, y, z); return c
    def cut(n, base, tools):
        if not tools:
            return base
        if len(tools) > 1:
            f = doc.addObject("Part::MultiFuse", n + "Tools"); f.Shapes = tools; tool = f
        else:
            tool = tools[0]
        c = doc.addObject("Part::Cut", n); c.Base, c.Tool = base, tool; return c
    def round_vertical(n, obj, r):
        doc.recompute()
        if not r:
            return obj
        edges = [(i + 1, r, r) for i, e in enumerate(obj.Shape.Edges)
                 if len(e.Vertexes) == 2 and abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) > 1e-6
                 and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-6 and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-6]
        f = doc.addObject("Part::Fillet", n); f.Base = obj; f.Edges = edges; return f
    k = s["kind"]
    holes = []
    if k == "plate":
        L, W, T = s["size"]
        body = round_vertical("Rounded", box("Plate", L, W, T), s.get("fillet") or 0)
        m = s.get("margin") or max(s.get("hole") or 0, 4) * 1.5
        n = s.get("holes") or 0
        spots = {1: [(L / 2, W / 2)], 2: [(m, W / 2), (L - m, W / 2)], 4: [(m, m), (L - m, m), (m, W - m), (L - m, W - m)],
                 6: [(m, m), (L / 2, m), (L - m, m), (m, W - m), (L / 2, W - m), (L - m, W - m)]}.get(n, [(m + i * (L - 2 * m) / max(1, n - 1), W / 2) for i in range(n)])
        holes = [cyl(f"Hole{i + 1}", s["hole"], T + 2, x, y, -1) for i, (x, y) in enumerate(spots)]
        if s.get("centre"):
            holes.append(cyl("CentreHole", s["centre"], T + 2, L / 2, W / 2, -1))
        part = cut("Part", body, holes)
    elif k == "bracket":
        L, W, H = s["size"]
        t = s.get("thick") or 4
        f = doc.addObject("Part::MultiFuse", "Bracket"); f.Shapes = [box("Base", L, W, t), box("Upright", t, W, H)]
        n = s.get("holes") or 0
        d = s.get("hole") or 5
        per = max(1, n // 2) if n else 0
        ys = [W * (i + 1) / (per + 1) for i in range(per)]
        holes = [cyl(f"BaseHole{i + 1}", d, t + 2, t + (L - t) / 2, y, -1) for i, y in enumerate(ys)]
        for i, y in enumerate(ys):
            c = cyl(f"UprightHole{i + 1}", d, t + 2, -1, y, t + (H - t) / 2)
            c.Placement = App.Placement(App.Vector(-1, y, t + (H - t) / 2), App.Rotation(App.Vector(0, 1, 0), 90))
            holes.append(c)
        part = cut("Part", f, holes)
    elif k == "flange":
        D, T = s["diameter"], s.get("thick") or 10
        body = cyl("Disc", D, T, D / 2, D / 2, 0)
        import math
        n, pcd = s.get("holes") or 0, s.get("circle") or D * 0.75
        holes = [cyl(f"BoltHole{i + 1}", s.get("hole") or 8, T + 2, D / 2 + pcd / 2 * math.cos(2 * math.pi * i / n),
                     D / 2 + pcd / 2 * math.sin(2 * math.pi * i / n), -1) for i in range(n)]
        if s.get("centre"):
            holes.append(cyl("CentreHole", s["centre"], T + 2, D / 2, D / 2, -1))
        part = cut("Part", body, holes)
    elif k == "spacer":
        OD, ID, H = s["outside"], s["inside"], s["length"]
        holes = [cyl("Bore", ID, H + 2, OD / 2, OD / 2, -1)]
        part = cut("Part", cyl("Outer", OD, H, OD / 2, OD / 2, 0), holes)
    else:  # enclosure: an open-top box with walls
        L, W, H = s["size"]
        t = s.get("wall") or 2
        outer = round_vertical("Rounded", box("Outer", L, W, H), s.get("fillet") or 0)
        part = cut("Part", outer, [box("Inside", L - 2 * t, W - 2 * t, H, t, t, t)])
    part.Label = job["name"]
    doc.recompute()
    shape = part.Shape
    doc.saveAs(job["fcstd"])
    shape.exportStep(job["step"])
    import Mesh, MeshPart
    MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.05, AngularDeflection=0.2).write(job["stl"])
    back = Part.Shape(); back.read(job["step"])
    bb, bb2 = shape.optimalBoundingBox(False, False), back.optimalBoundingBox(False, False)  # exact, not from the triangulation
    holes = set()
    for face in shape.Faces:  # a hole: a cylindrical face whose outward normal points at its own axis (the material is around it)
        if face.Surface.__class__.__name__ != "Cylinder":
            continue
        u0, u1, v0, v1 = face.ParameterRange
        p, n = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2), face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        axis, centre = face.Surface.Axis, face.Surface.Center
        radial = p - centre
        radial = radial - axis * radial.dot(axis)
        if n.dot(radial) < 0:
            foot = centre - axis * centre.dot(axis)  # where the hole's axis line crosses the plane through the origin
            holes.add((round(face.Surface.Radius * 2, 3), round(foot.x, 2), round(foot.y, 2), round(foot.z, 2), round(abs(axis.x), 2), round(abs(axis.y), 2)))
    radii = {}
    for h in holes:
        radii[h[0]] = radii.get(h[0], 0) + 1
    report = {"valid": shape.isValid() and len(shape.Solids) == 1, "volume": shape.Volume, "size": [bb.XLength, bb.YLength, bb.ZLength],
              "step_volume": back.Volume, "step_size": [bb2.XLength, bb2.YLength, bb2.ZLength], "holes": radii,
              "objects": [o.TypeId.split("::")[-1] for o in doc.Objects], "errors": [o.Label for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]}
except Exception:
    report = {"error": traceback.format_exc()[-1500:]}
print("AIPC_REPORT " + json.dumps(report))
'''


def cmd():
    hits = sorted(HOME.rglob("FreeCADCmd.exe")) if HOME.exists() else []
    return hits[0] if hits else None


def read(c, last=None):
    s = dict(last or {})
    kind = next((k for k, p in KINDS.items() if re.search(r"\b(?:" + p + r")\b", c)), None)
    if kind and kind != s.get("kind"):
        s = {"kind": kind}
    num = r"(\d+(?:\.\d+)?)"
    m = re.search(num + r"\s*[x×]\s*" + num + r"\s*[x×]\s*" + num, c)
    if m:
        s["size"] = [float(g) for g in m.groups()]
    m = re.search(r"\b(\d+)\s+(?:bolt\s+|mounting\s+)?holes?\b(?:\s+(?:of\s+)?" + num + r"\s*mm)?", c)
    if m:
        s["holes"] = int(m.group(1))
        if m.group(2):
            s["hole"] = float(m.group(2))
    m = re.search(r"\bholes?\s+(?:to\s+|of\s+|=\s*)?" + num + r"\s*mm", c)
    if m:
        s["hole"] = float(m.group(1))
    m = re.search(r"\b(?:centre|center|middle)\s+hole\s+(?:of\s+)?" + num + r"|\bhole\s+" + num + r"\s*mm\s+in\s+the\s+(?:middle|centre|center)", c)
    if m:
        s["centre"] = float(m.group(1) or m.group(2))
    for key, pat in (("thick", num + r"\s*mm\s+thick"), ("wall", num + r"\s*mm\s+walls?"), ("diameter", num + r"\s*mm\s+(?:diameter|across|wide)"),
                     ("outside", num + r"\s*mm\s+(?:outside|outer|od)\b"), ("inside", num + r"\s*mm\s+(?:inside|inner|id|bore)\b"),
                     ("length", num + r"\s*mm\s+(?:long|length|tall|high)"), ("circle", r"on\s+(?:a\s+)?" + num + r"\s*mm\s+(?:circle|pcd|pitch)"),
                     ("fillet", r"(?:rounded\s+corners?|fillets?|radius)\s+(?:of\s+)?" + num)):
        m = re.search(pat, c)
        if m:
            s[key] = float(m.group(1))
    mat = next((k for k in DENSITY if re.search(rf"\b{k}\b", c)), "aluminum" if re.search(r"\baluminum\b", c) else None)
    if mat:
        s["material"] = "aluminium" if mat == "aluminum" else mat
    s.setdefault("material", "steel")
    if s.get("kind") == "plate":
        s.setdefault("size", [100.0, 60.0, 5.0])
        if s.get("holes"):
            s.setdefault("hole", 6.0)
    elif s.get("kind") == "bracket":
        s.setdefault("size", [50.0, 40.0, 40.0])
    elif s.get("kind") == "flange":
        s.setdefault("diameter", 80.0)
    elif s.get("kind") == "spacer":
        s.setdefault("outside", 20.0)
        s.setdefault("inside", 10.0)
        s.setdefault("length", 15.0)
    elif s.get("kind") == "enclosure":
        s.setdefault("size", [100.0, 60.0, 40.0])
    return s


def describe(s):
    k = s["kind"]
    if k == "spacer":
        d = f"spacer {s['outside']:g} mm outside, {s['inside']:g} mm bore, {s['length']:g} mm long"
    elif k == "flange":
        d = f"flange {s['diameter']:g} mm across, {s.get('thick') or 10:g} mm thick"
    else:
        d = f"{'L-bracket' if k == 'bracket' else k} {' x '.join(f'{v:g}' for v in s['size'])} mm"
        if k == "bracket":
            d += f", {s.get('thick') or 4:g} mm thick"
        if k == "enclosure":
            d += f", {s.get('wall') or 2:g} mm walls, open top"
    if s.get("holes"):
        d += f", {s['holes']} holes {s.get('hole') or (5 if k == 'bracket' else 8):g} mm" + (f" on a {s['circle']:g} mm circle" if s.get("circle") else "")
    if s.get("centre"):
        d += f", centre hole {s['centre']:g} mm"
    if s.get("fillet") and k in ("plate", "enclosure"):
        d += f", rounded corners {s['fillet']:g} mm"
    return d


def expected_size(s):
    k = s["kind"]
    if k == "spacer":
        return [s["outside"], s["outside"], s["length"]]
    if k == "flange":
        return [s["diameter"], s["diameter"], s.get("thick") or 10]
    return s["size"]


def holes_expected(s):
    want = {}
    k = s["kind"]
    if k == "spacer":
        want[round(s["inside"], 3)] = 1
    if s.get("holes") and k in ("plate", "flange", "bracket"):
        n = s["holes"] if k != "bracket" else 2 * max(1, s["holes"] // 2)
        d = round(s.get("hole") or (5 if k == "bracket" else 8 if k == "flange" else 6), 3)
        want[d] = want.get(d, 0) + n
    if s.get("centre") and k in ("plate", "flange"):
        want[round(s["centre"], 3)] = want.get(round(s["centre"], 3), 0) + 1
    return want


def preview(stl_path, png):
    """A shaded picture of the part from the STL (matplotlib, no window)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    data = Path(stl_path).read_bytes()
    n = struct.unpack("<I", data[80:84])[0]
    arr = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<3f4", (3,)), ("a", "<u2")]))
    tris = arr["v"]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-9
    light = np.clip(normals @ np.array([0.4, -0.5, 0.75]), 0.15, 1)
    fig = plt.figure(figsize=(6, 4.5), dpi=120)
    ax = fig.add_subplot(projection="3d")
    ax.add_collection3d(Poly3DCollection(tris, facecolors=plt.cm.Blues(0.35 + 0.6 * light), edgecolor="none"))
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    span = (hi - lo).max()
    mid = (hi + lo) / 2
    for setter, k in ((ax.set_xlim, 0), (ax.set_ylim, 1), (ax.set_zlim, 2)):
        setter(mid[k] - span / 2, mid[k] + span / 2)
    ax.view_init(elev=28, azim=-55)
    ax.set_axis_off()
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def parse(text, ctx):
    c = text.lower()
    last = (ctx.get("memo") or {}).get("freecad")
    named = re.search(TRIGGER, c)
    kind = next((k for k, p in KINDS.items() if re.search(r"\b(?:" + p + r")\b", c)), None)
    if named and kind:
        return {"op": "part", "spec": read(c)}
    if last and re.search(r"\b(?:make|change|set)\b.*\b(?:holes?|thick|walls?|corners?|diameter|long|bore|material|aluminium|steel|pla|\d+\s*x\s*\d+)", c) \
            and not re.search(r"\b(?:godot|unity|arduino|lightroom|photo|player|coin|led)\b", c):
        return {"op": "part", "spec": read(c, last["spec"]), "edit": True}
    return None


def run(op, ctx):
    exe = cmd()
    if not exe:
        return "FreeCAD is not in tools/freecad."
    s = op["spec"]
    out = Path(ctx["out"]) / "freecad"
    out.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w-]+", "_", describe(s).split(",")[0]).strip("_")
    job = {"spec": s, "name": name, "fcstd": str((out / f"{name}.FCStd").resolve()), "step": str((out / f"{name}.step").resolve()),
           "stl": str((out / f"{name}.stl").resolve())}
    jf = out / f"{name}.job.json"
    jf.write_text(json.dumps(job), encoding="utf-8")
    script = out / "aipc_freecad_job.py"
    script.write_text(JOB, encoding="utf-8")
    home = HOME / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, AIPC_JOB=str(jf.resolve()), FREECAD_USER_HOME=str(home), FREECAD_USER_DATA=str(home / "data"), FREECAD_USER_TEMP=str(home / "temp"))
    r = subprocess.run([str(exe), str(script.resolve())], capture_output=True, text=True, timeout=300, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    m = re.search(r"AIPC_REPORT (\{.*\})", r.stdout + r.stderr)
    rep = json.loads(m.group(1)) if m else {"error": (r.stderr or r.stdout)[-800:]}
    if rep.get("error"):
        return f"FreeCAD couldn't build it: {rep['error'][-500:]}"
    png = out / f"{name}.png"
    preview(job["stl"], png)
    size, want = rep["size"], expected_size(s)
    got_holes = {round(float(k), 3): v for k, v in rep["holes"].items()}
    want_holes = holes_expected(s)
    checks = [("a valid single solid, every feature rebuilt", rep["valid"] and not rep["errors"]),
              (f"the size asked ({' x '.join(f'{v:g}' for v in want)} mm)", all(abs(a - b) < 0.01 for a, b in zip(sorted(size), sorted(want)))),
              ("the holes asked (" + (", ".join(f"{v} x {k:g} mm" for k, v in want_holes.items()) or "none") + ")",
               all(got_holes.get(k, 0) == v for k, v in want_holes.items())),
              ("the STEP read back: same volume and size", abs(rep["step_volume"] - rep["volume"]) <= rep["volume"] * 1e-4 and
               all(abs(a - b) < 0.01 for a, b in zip(rep["step_size"], size)))]
    bad = [w for w, ok in checks if not ok]
    grams = rep["volume"] / 1000 * DENSITY[s["material"]]
    ctx.setdefault("memo", {})["freecad"] = {"spec": s, "stl": job["stl"]}
    ctx["memo"]["model3d"] = job["stl"]
    return (f"{'Changed' if op.get('edit') else 'Made'} the part: {describe(s)}; {s['material']} {grams:,.1f} g ({rep['volume'] / 1000:,.1f} cm3). "
            f"Files: {out / (name + '.step')} (SolidWorks, Fusion 360, Inventor, CATIA, Creo: File > Open), {name}.FCStd (FreeCAD, editable: "
            f"{', '.join(dict.fromkeys(rep['objects']))}), {name}.stl (3D printing: say 'slice it for ender 3'), {name}.png. " +
            ("Checked in FreeCAD: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f" (got {rep['holes']}, size {size})."))
