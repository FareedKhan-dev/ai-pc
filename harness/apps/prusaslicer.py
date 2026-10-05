"""3D printing with PrusaSlicer (2.9.6 in tools/prusaslicer, Prusa-signed; Bambu Studio and OrcaSlicer are built on
it): a model given (.stl, .3mf, .obj) or a simple shape from words (cube, box, cylinder) sliced to G-code for a popular
printer (Creality Ender-3 / V2 / S1, Prusa MK4S, Prusa CORE One) with the quality, material, infill, supports, brim and
copies asked; also saved as a .3mf project that Bambu Studio, OrcaSlicer, Cura and PrusaSlicer open. Checked: the model is
watertight, the G-code is for that printer with those settings, every printed line is on the bed, and the print is as
tall as the model. Says the print time and filament.

  'slice cube 20 mm for ender 3 in pla, 20% infill'   '3d print bracket.stl on a prusa mk4s, petg, supports, fine'
"""
import re
import shutil
import struct
import subprocess
import zipfile
from math import cos, pi, sin
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "prusaslicer", "3D printing: PrusaSlicer G-code for Ender-3 / Prusa MK4S / CORE One (+ .3mf for Bambu, Orca, Cura)"
EXAMPLES = ["slice cube 20 mm for ender 3 in pla, 20% infill", "3d print bracket.stl on a prusa mk4s, petg, supports, fine"]
HOME = ROOT / "tools" / "prusaslicer"
APP = HOME / "PrusaSlicer-2.9.6"
EXE = APP / "prusa-slicer-console.exe"
DATA = HOME / "data"
CREALITY = {"draft": "0.28 mm SUPERDRAFT (0.4 mm nozzle) @CREALITY", "normal": "0.20 mm NORMAL (0.4 mm nozzle) @CREALITY",
            "fine": "0.12 mm DETAIL (0.4 mm nozzle) @CREALITY"}
# words -> (vendor bundle, model id, printer profile, print profile per quality, material profile pattern)
PRINTERS = {
    "Ender-3 V2": ("Creality", "ENDER3V2", "Creality Ender-3 V2 (0.4 mm nozzle)", CREALITY, "Generic {m} @CREALITY"),
    "Ender-3 S1": ("Creality", "ENDER3S1", "Creality Ender-3 S1 (0.4 mm nozzle)", CREALITY, "Generic {m} @CREALITY"),
    "Ender-3": ("Creality", "ENDER3", "Creality Ender-3 (0.4 mm nozzle)", CREALITY, "Generic {m} @CREALITY"),
    "Prusa MK4S": ("PrusaResearch", "MK4S", "Original Prusa MK4S 0.4 nozzle",
                   {"draft": "0.20mm SPEED @MK4S 0.4", "normal": "0.20mm STRUCTURAL @MK4S 0.4", "fine": "0.10mm FAST DETAIL @MK4S 0.4"}, "Generic {m} @PG"),
    "Prusa CORE One": ("PrusaResearch", "COREONE", "Prusa CORE One 0.4 nozzle",
                       {"draft": "0.20mm SPEED @COREONE 0.4", "normal": "0.20mm BALANCED @COREONE 0.4", "fine": "0.10mm FAST DETAIL @COREONE 0.4"},
                       "Generic {m} @COREONE"),
}
WORDS = {"Ender-3 V2": r"ender[- ]?3\s*v2", "Ender-3 S1": r"ender[- ]?3\s*s1", "Ender-3": r"ender[- ]?3|ender\b|creality",
         "Prusa MK4S": r"mk4s?\b|prusa\s+mk4", "Prusa CORE One": r"core\s*one"}
MODELS = {".stl", ".3mf", ".obj"}


def setup():
    """PrusaSlicer's settings folder inside the project: the vendor printer bundles and the printers offered here."""
    (DATA / "vendor").mkdir(parents=True, exist_ok=True)
    for vendor in {p[0] for p in PRINTERS.values()}:
        dest = DATA / "vendor" / f"{vendor}.ini"
        if not dest.exists():
            shutil.copy2(APP / "resources" / "profiles" / f"{vendor}.ini", dest)
    want = "".join(f"[vendor:{v}]\n" + "".join(f"model:{p[1]} = 0.4\n" for p in PRINTERS.values() if p[0] == v) + "\n"
                   for v in sorted({p[0] for p in PRINTERS.values()}))
    ini = DATA / "PrusaSlicer.ini"
    if not ini.exists() or ini.read_text(encoding="utf-8") != want:
        ini.write_text(want, encoding="utf-8")


def stl(path, tris):
    """Binary STL with real face normals (readers that guess binary-or-text from the bytes after the header need them)."""
    with open(path, "wb") as f:
        f.write(b"AI PC binary STL".ljust(80, b"\0") + struct.pack("<I", len(tris)))
        for a, b, c in tris:
            u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            k = sum(x * x for x in n) ** 0.5 or 1.0
            f.write(struct.pack("<3f", *(x / k for x in n)) + b"".join(struct.pack("<3f", *p) for p in (a, b, c)) + b"\0\0")


def box(x, y, z):
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [tuple(v[i] for i in t) for t in f]


def cylinder(d, h, n=96):
    r = d / 2
    ring = [(r + r * cos(2 * pi * k / n), r + r * sin(2 * pi * k / n)) for k in range(n)]
    tris = []
    for k in range(n):
        (x0, y0), (x1, y1) = ring[k], ring[(k + 1) % n]
        tris += [((r, r, 0), (x1, y1, 0), (x0, y0, 0)), ((r, r, h), (x0, y0, h), (x1, y1, h)),
                 ((x0, y0, 0), (x1, y1, 0), (x1, y1, h)), ((x0, y0, 0), (x1, y1, h), (x0, y0, h))]
    return tris


def shape(c):
    m = re.search(r"\bcube\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*mm\b", c)
    if m:
        s = float(m.group(1))
        return f"cube_{m.group(1)}mm", box(s, s, s), s
    m = re.search(r"\bbox\s+(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm\b", c)
    if m:
        a, b, h = (float(g) for g in m.groups())
        return f"box_{m.group(1)}x{m.group(2)}x{m.group(3)}mm", box(a, b, h), h
    m = re.search(r"\bcylinder\s+(\d+(?:\.\d+)?)\s*mm\s+(?:wide|diameter|across)(?:\s+(?:and|by|x))?\s+(\d+(?:\.\d+)?)\s*mm\s+(?:tall|high)", c)
    if m:
        d, h = float(m.group(1)), float(m.group(2))
        return f"cylinder_{m.group(1)}x{m.group(2)}mm", cylinder(d, h), h
    return None


def cli(*args, timeout=600):
    return subprocess.run([str(EXE), "--datadir", str(DATA), *args], capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def info(model):
    r = cli("--info", str(model), timeout=120)
    return {k: v.strip() for k, v in re.findall(r"^(\w+) = (.+)$", r.stdout, re.M)}


def gcode_facts(path):
    """Settings comments, and where the nozzle really extruded (X/Y/Z bounds of printing moves)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    facts = dict(re.findall(r"^; ([\w \[\]()]+?) = (.*)$", text, re.M))
    x = y = z = 0.0
    e_rel, last_e = True, 0.0
    lo, hi = [1e9, 1e9], [-1e9, -1e9]
    top, layers = 0.0, set()
    kind = "Custom"
    for line in text.splitlines():
        if line.startswith(";TYPE:"):  # the printer's own start/end code (purge lines) is 'Custom'; the rest is the print
            kind = line[6:].strip()
        elif line.startswith("M83"):
            e_rel = True
        elif line.startswith("M82"):
            e_rel = False
        elif line.startswith(("G92", )) and " E" in line:
            last_e = 0.0
        elif line.startswith(("G1 ", "G0 ", "G2 ", "G3 ")):
            vals = dict(re.findall(r"([XYZE])(-?\d*\.?\d+)", line.split(";")[0]))
            x, y, z = float(vals.get("X", x)), float(vals.get("Y", y)), float(vals.get("Z", z))
            if "E" in vals:
                e = float(vals["E"])
                printing = e > 0 if e_rel else e > last_e
                last_e = e if not e_rel else last_e
                if printing and kind != "Custom" and ("X" in vals or "Y" in vals):
                    lo, hi = [min(lo[0], x), min(lo[1], y)], [max(hi[0], x), max(hi[1], y)]
                    top = max(top, z)
                    layers.add(round(z, 3))
    return facts, lo, hi, top, len(layers)


def check(facts, lo, hi, top, height, op, printer, model_info, three_mf):
    bed = [tuple(float(v) for v in p.split("x")) for p in facts.get("bed_shape", "0x0").split(",")]
    bx = (min(p[0] for p in bed), max(p[0] for p in bed))
    by = (min(p[1] for p in bed), max(p[1] for p in bed))
    layer = float(facts.get("layer_height", 0.2))
    out = [("the model is watertight (manifold), so it slices cleanly", model_info.get("manifold") == "yes"),
           (f"the G-code is for the {printer}", facts.get("printer_settings_id", "").strip('"') == PRINTERS[printer][2]),
           ("every printed line is on the bed and under the printer's height limit",
            bx[0] - 0.01 <= lo[0] and hi[0] <= bx[1] + 0.01 and by[0] - 0.01 <= lo[1] and hi[1] <= by[1] + 0.01 and top <= float(facts.get("max_print_height", 1e9))),
           (f"{op['infill']}% infill, supports {'on' if op['supports'] else 'off'}" + (", a brim" if op["brim"] else ""),
            facts.get("fill_density") == f"{op['infill']}%" and facts.get("support_material") == str(int(op["supports"])) and
            (float(facts.get("brim_width", 0)) > 0) == op["brim"]),
           (".3mf project made (opens in Bambu Studio, OrcaSlicer, Cura, PrusaSlicer)", zipfile.is_zipfile(three_mf) and
            "3D/3dmodel.model" in zipfile.ZipFile(three_mf).namelist())]
    if height:
        out.insert(3, (f"the print is as tall as the model ({height:g} mm)", abs(top - height) <= layer + 0.05))
    return out


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\b3d[- ]?print|\bslice\b|\bslicer\b|\bprusa\s*slicer\b|\bprusaslicer\b|\bg-?code\b|\bcura\b|\bbambu\b|\borca\s*slicer\b", c):
        return None
    printer = next((p for p, w in WORDS.items() if re.search(r"\b(?:" + w + r")", c)), "Ender-3")
    f = find_file(text, ctx, MODELS)
    s = None if f else shape(c)
    last = (ctx.get("memo") or {}).get("model3d")  # a part just made in this chat (FreeCAD): 'slice it'
    if not f and not s and last and Path(last).exists() and re.search(r"\b(?:it|this|that|the\s+part|the\s+model)\b", c):
        f = last
    if not f and not s:
        return None
    infill = re.search(r"\b(\d{1,3})\s*%\s*infill\b|\binfill\s*(?:of\s*)?(\d{1,3})\s*%", c)
    copies = re.search(r"\b(\d{1,2})\s*(?:copies|pieces|pcs|of them)\b", c)
    scale = re.search(r"\bscale(?:d)?\s*(?:to|by)?\s*(\d{1,4})\s*%", c)
    return {"op": "slice", "file": f, "shape": s[0] if s else None, "words": c, "printer": printer,
            "quality": "draft" if re.search(r"\b(?:draft|fast|quick)\b", c) else "fine" if re.search(r"\b(?:fine|detail(?:ed)?|high quality|smooth)\b", c) else "normal",
            "material": next((m for m in ("PETG", "ABS", "PLA") if re.search(rf"\b{m.lower()}\b", c)), "PLA"),
            "infill": max(0, min(100, int(infill.group(1) or infill.group(2)))) if infill else 15,
            "supports": bool(re.search(r"\bsupports?\b", c)) and not re.search(r"\bno\s+supports?\b|\bwithout\s+supports?\b", c),
            "brim": bool(re.search(r"\bbrim\b", c)) and not re.search(r"\bno\s+brim\b", c),
            "copies": int(copies.group(1)) if copies else 1, "scale": int(scale.group(1)) if scale else 100,
            "bambu": bool(re.search(r"\bbambu\b|\bcura\b|\borca", c))}


def run(op, ctx):
    if not EXE.exists():
        return "PrusaSlicer is not in tools/prusaslicer."
    setup()
    vendor, _, printer_profile, prints, material_pat = PRINTERS[op["printer"]]
    material = material_pat.format(m=op["material"])
    bundle = (DATA / "vendor" / f"{vendor}.ini").read_text(encoding="utf-8", errors="replace")
    if f"[filament:{material}]" not in bundle:
        return f"No {op['material']} profile for the {op['printer']} in PrusaSlicer; try PLA or PETG."
    out = Path(ctx["out"]) / "prusaslicer"
    out.mkdir(parents=True, exist_ok=True)
    height = None
    if op.get("file"):
        model = Path(op["file"])
    else:
        name, tris, height = shape(op["words"])
        model = out / f"{name}.stl"
        stl(model, tris)
    mi = info(model)
    if not height and mi.get("size_z"):
        height = float(mi["size_z"])
    if height:
        height = height * op["scale"] / 100
    stem = re.sub(r"[^\w-]+", "_", f"{model.stem}_{op['printer']}_{op['material']}").strip("_")
    common = ["--printer-profile", printer_profile, "--print-profile", prints[op["quality"]], "--material-profile", material,
              "--fill-density", f"{op['infill']}%", "--support-material" if op["supports"] else "--no-support-material",
              "--brim-width", "5" if op["brim"] else "0", "--no-binary-gcode"]
    if op["scale"] != 100:
        common += ["--scale", f"{op['scale']}%"]
    if op["copies"] > 1:
        common += ["--duplicate", str(op["copies"])]
    gcode, three_mf = out / f"{stem}.gcode", out / f"{stem}.3mf"
    r = cli(*common, "--export-gcode", str(model), "-o", str(gcode))
    if r.returncode != 0 or not gcode.exists():
        why = (r.stderr or r.stdout).strip()[-400:]
        if "outside of the print volume" in why:
            return f"It is too big for the {op['printer']}'s bed (PrusaSlicer: {why}). Say it again with 'scale 50%', or pick a bigger printer."
        return f"PrusaSlicer couldn't slice it: {why}"
    cli(*common, "--export-3mf", str(model), "-o", str(three_mf))
    facts, lo, hi, top, layers = gcode_facts(gcode)
    checks = check(facts, lo, hi, top, height, op, op["printer"], mi, three_mf)
    bad = [w for w, ok in checks if not ok]
    t = facts.get("estimated printing time (normal mode)", "?")
    grams = facts.get("total filament used [g]", "?")
    metres = float(facts.get("filament used [mm]", 0) or 0) / 1000
    extras = (", supports" if op["supports"] else "") + (", brim" if op["brim"] else "") + (f", {op['copies']} copies" if op["copies"] > 1 else "")
    return (f"Sliced {model.name} for the {op['printer']} ({op['quality']} {facts.get('layer_height', '?')} mm layers, {op['material']}, {op['infill']}% infill"
            f"{extras}): "
            f"about {t}, {grams} g of filament ({metres:.2f} m), {layers} layers. G-code: {gcode} (copy it to the printer's SD card or USB). "
            f"Project: {three_mf.name}" + (" (open it in Bambu Studio or Cura to slice for that printer)" if op.get("bambu") else "") + ". " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + "."))
