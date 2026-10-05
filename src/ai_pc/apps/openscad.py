"""OpenSCAD (the makers' code-first 3D modeller; 2026.10.03 snapshot in tools/openscad, checked against its published
SHA-256): printable objects from words written as parametric .scad files (the sizes are Customizer variables at the top,
so they can be changed in OpenSCAD), rendered headless to STL and a PNG preview: a box with a snug lid, a name tag or
keychain, a phone stand, a spur gear with involute teeth; or a .scad given. Checked: OpenSCAD reports one manifold solid
with no errors, and the STL is the size asked. 'slice it' then sends it to PrusaSlicer.

  'openscad box with lid 80x60x40 mm, 2 mm walls'   "openscad name tag 'ALI' 60x20 mm"   'openscad gear 20 teeth module 2'
  'openscad phone stand 70 degrees'   'openscad render bracket.scad'
"""
import os
import re
import struct
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "openscad", "OpenSCAD: parametric printable objects (boxes, tags, stands, gears) to STL + preview"
EXAMPLES = ["openscad box with lid 80x60x40 mm, 2 mm walls", "openscad name tag 'ALI' 60x20 mm", "openscad gear 20 teeth module 2",
            "openscad phone stand 70 degrees"]
HOME = ROOT / "tools" / "openscad"

BOX = """// Box with a snug lid (made by AI PC). Change the numbers below in OpenSCAD's Customizer.
inner_length = {L};  // mm inside
inner_width = {W};
inner_height = {H};
wall = {t};
clearance = 0.3;     // so the lid slides on
lip = 6;

module box() {{
  difference() {{
    cube([inner_length + 2*wall, inner_width + 2*wall, inner_height + wall]);
    translate([wall, wall, wall]) cube([inner_length, inner_width, inner_height + 1]);
  }}
}}
module lid() {{
  difference() {{
    cube([inner_length + 4*wall + 2*clearance, inner_width + 4*wall + 2*clearance, lip + wall]);
    translate([wall, wall, wall]) cube([inner_length + 2*wall + 2*clearance, inner_width + 2*wall + 2*clearance, lip + 1]);
  }}
}}
box();
translate([inner_length + 2*wall + 10, 0, 0]) lid();
"""
TAG = """// Name tag / keychain (made by AI PC).
label = "{text}";
length = {L};
height = {H};
plate = 2;        // mm
letters = 1.2;    // raised by
hole = {hole};    // 0 = no keyring hole
corner = 3;

difference() {{
  hull() for (x = [corner, length - corner], y = [corner, height - corner]) translate([x, y, 0]) cylinder(r = corner, h = plate, $fn = 32);
  if (hole > 0) translate([corner + hole / 2 + 1, height / 2, -1]) cylinder(d = hole, h = plate + 2, $fn = 32);
}}
translate([(length + (hole > 0 ? hole + 2 : 0)) / 2, height / 2, plate])
  linear_extrude(letters) text(label, size = height * 0.45, halign = "center", valign = "center", font = "Liberation Sans:style=Bold");
"""
STAND = """// Phone stand (made by AI PC).
angle = {angle};    // degrees from the desk
width = {W};
base = 80;
back = 90;
thick = 5;
lip = 12;

cube([base, width, thick]);                                   // foot
translate([base - thick, 0, 0]) rotate([0, -(90 - angle), 0]) cube([thick, width, back]);  // back rest
translate([0, 0, 0]) cube([thick, width, lip]);               // front lip that holds the phone
"""
GEAR = """// Spur gear with involute teeth (made by AI PC).
teeth = {n};
module_mm = {m};
thickness = {T};
bore = {bore};
pressure_angle = 20;

pitch_r = teeth * module_mm / 2;
base_r = pitch_r * cos(pressure_angle);
outer_r = pitch_r + module_mm;
root_r = pitch_r - 1.25 * module_mm;
function inv(r) = sqrt(max(0, (r / base_r) * (r / base_r) - 1));          // involute parameter at radius r (radians)
function pt(t) = base_r * [cos(t * 180 / PI) + t * sin(t * 180 / PI), sin(t * 180 / PI) - t * cos(t * 180 / PI)];
function ang(p) = atan2(p[1], p[0]);
half = 90 / teeth + (tan(pressure_angle) - pressure_angle * PI / 180) * 180 / PI;  // half the tooth's angle at the base circle
flank = [for (i = [0:12]) let(r = max(base_r, root_r) + (outer_r - max(base_r, root_r)) * i / 12) pt(inv(r))];
module tooth() {{
  polygon(concat([[0, 0]],
                 [for (p = flank) let(a = ang(p) - half) norm(p) * [cos(a), sin(a)]],
                 [for (i = [12:-1:0]) let(p = flank[i], a = half - ang(p)) norm(p) * [cos(a), sin(a)]]));
}}
linear_extrude(thickness) difference() {{
  union() {{
    circle(r = root_r, $fn = teeth * 4);
    for (k = [0:teeth - 1]) rotate(k * 360 / teeth) tooth();
  }}
  circle(d = bore, $fn = 48);
}}
"""


def openscad_exe():
    hits = sorted(HOME.rglob("openscad.com")) if HOME.exists() else []
    return hits[0] if hits else None


def env():
    home = (HOME / "home").resolve()
    (home / "fontcache").mkdir(parents=True, exist_ok=True)
    conf = home / "fonts.conf"
    fonts = openscad_exe().parent / "fonts"
    text = ('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
            f"  <dir>{fonts.as_posix()}</dir>\n  <dir>C:/Windows/Fonts</dir>\n  <cachedir>{(home / 'fontcache').as_posix()}</cachedir>\n</fontconfig>\n")
    if not conf.exists() or conf.read_text(encoding="utf-8") != text:
        conf.write_text(text, encoding="utf-8")
    return dict(os.environ, FONTCONFIG_FILE=str(conf))


def run_scad(scad, out, extra=()):
    from ai_pc.core import hidden_desktop
    return hidden_desktop.run([str(openscad_exe()), "-o", str(out), *extra, str(scad)], timeout=300, env=env())


def stl_box(path):
    """(size x, y, z) of an STL (ASCII or binary)."""
    data = Path(path).read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        pts = [tuple(map(float, m)) for m in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)]
    else:
        n = struct.unpack("<I", data[80:84])[0]
        pts = [struct.unpack("<3f", data[84 + i * 50 + 12 + k * 12: 84 + i * 50 + 24 + k * 12]) for i in range(n) for k in range(3)]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return [round(hi[i] - lo[i], 2) for i in range(3)]


def design(c):
    num = r"(\d+(?:\.\d+)?)"
    if re.search(r"\bbox\b", c):
        m = re.search(num + r"\s*[x×]\s*" + num + r"\s*[x×]\s*" + num, c)
        L, W, H = (float(v) for v in m.groups()) if m else (80.0, 60.0, 40.0)
        t = float((re.search(num + r"\s*mm\s+walls?", c) or [None, 2])[1])
        return "box", BOX.format(L=L, W=W, H=H, t=t), [L + 2 * t + 10 + L + 4 * t + 0.6, W + 4 * t + 0.6, H + t], f"box {L:g} x {W:g} x {H:g} mm inside with a lid, {t:g} mm walls"
    if re.search(r"\b(?:name\s*tag|tag|keychain|key\s*ring)\b", c):
        text = re.search(r"['\"]([^'\"]{1,20})['\"]", c)
        m = re.search(num + r"\s*[x×]\s*" + num, c)
        L, H = (float(v) for v in m.groups()) if m else (60.0, 20.0)
        hole = 0 if re.search(r"\bno\s+hole\b", c) or (re.search(r"\bname\s*tag\b", c) and not re.search(r"\bkey", c)) else 4
        return "tag", TAG.format(text=(text.group(1) if text else "NAME").upper(), L=L, H=H, hole=hole), [L, H, 3.2], \
            f"{'keychain' if hole else 'name tag'} '{(text.group(1) if text else 'NAME').upper()}' {L:g} x {H:g} mm"
    if re.search(r"\bphone\s*stand\b|\bstand\b", c):
        a = float((re.search(num + r"\s*(?:deg|degrees|°)", c) or [None, 70])[1])
        W = float((re.search(num + r"\s*mm\s+wide", c) or [None, 70])[1])
        return "stand", STAND.format(angle=a, W=W), None, f"phone stand at {a:g} degrees, {W:g} mm wide"
    if re.search(r"\bgear\b", c):
        n = int((re.search(r"(\d+)\s*teeth", c) or [None, 20])[1])
        m = float((re.search(r"\bmodule\s*" + num, c) or [None, 2])[1])
        T = float((re.search(num + r"\s*mm\s+thick", c) or [None, 6])[1])
        bore = float((re.search(r"\bbore\s*" + num + r"|" + num + r"\s*mm\s+bore", c) or [None, 5, None])[1] or 5)
        return "gear", GEAR.format(n=n, m=m, T=T, bore=bore), [(n + 2) * m, (n + 2) * m, T], f"spur gear, {n} teeth, module {m:g} ({(n + 2) * m:g} mm across)"
    return None


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bopenscad\b|\.scad\b", c):
        return None
    f = find_file(text, ctx, {".scad"})
    if f:
        return {"op": "render", "file": f}
    return {"op": "make", "words": c} if design(c) else None


def run(op, ctx):
    if not openscad_exe():
        return "OpenSCAD is not in tools/openscad."
    out = Path(ctx["out"]) / "openscad"
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "render":
        scad = Path(op["file"]).resolve()
        kind, want, what = "file", None, scad.name
    else:
        kind, code, want, what = design(op["words"])
        scad = (out / (re.sub(r"[^\w-]+", "_", what).strip("_")[:60] + ".scad")).resolve()
        scad.write_text(code, encoding="utf-8")
    stl, png = (out / (scad.stem + ".stl")).resolve(), (out / (scad.stem + ".png")).resolve()
    for p in (stl, png):
        p.unlink(missing_ok=True)
    rc, so, se, timed_out = run_scad(scad, stl)
    report = so + se
    run_scad(scad, png, ["--render", "--imgsize=1000,750", "--viewall", "--autocenter", "--colorscheme=Tomorrow"])
    problems = [ln for ln in report.splitlines() if re.match(r"\s*(ERROR|WARNING):", ln) and "Fontconfig" not in ln]
    manifold = bool(re.search(r"3D object \(manifold\)", report) and re.search(r"Status:\s+NoError", report))
    if not manifold and stl.exists() and re.search(r"3D object \(PolySet\)", report):  # a plain extrusion skips OpenSCAD's own solid check
        from ai_pc.apps import prusaslicer
        if prusaslicer.EXE.exists():
            manifold = prusaslicer.info(stl).get("manifold") == "yes"  # PrusaSlicer's check of the same STL
    checks = [("one watertight (manifold) solid with no errors or warnings", rc == 0 and stl.exists() and manifold and not problems),
              ("a PNG preview was rendered", png.exists())]
    size = stl_box(stl) if stl.exists() else None
    if want and size:
        checks.append((f"the STL is the size asked ({' x '.join(f'{v:g}' for v in want)} mm)", all(abs(a - b) <= 0.15 + 0.01 * b for a, b in zip(size, want))))
    bad = [w for w, ok in checks if not ok]
    ctx.setdefault("memo", {})["model3d"] = str(stl)
    return (f"OpenSCAD {what}: {scad.name} (parametric: change the numbers at the top in OpenSCAD), {stl} " +
            (f"({' x '.join(f'{v:g}' for v in size)} mm)" if size else "") + f", {png.name}. Say 'slice it for ender 3' to print it. " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + "; ".join(problems[:3])))
