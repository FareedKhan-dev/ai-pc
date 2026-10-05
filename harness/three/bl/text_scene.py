"""Inside Blender: a 3D title (and a logo picture beside it) that comes in and holds: extruded, bevelled letters in a
chosen material, lit like a studio (soft panels the metal reflects, a rim light), the camera moving in or the letters
spinning, rising or dropping into place, a light sweeping across, a second line popping in. Frames out (the host makes
the video), the last frame as a picture, and the letters' silhouette at the end for the checks.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import common as C  # noqa: E402

spec, out_path = C.args()
scene = C.reset()
FINISH = {  # base colour (linear), roughness, metal
    "gold": ((1.0, 0.71, 0.29), 0.16, 1.0), "rose gold": ((0.92, 0.60, 0.55), 0.18, 1.0), "silver": ((0.95, 0.94, 0.90), 0.14, 1.0),
    "chrome": ((0.92, 0.92, 0.94), 0.03, 1.0), "copper": ((0.95, 0.64, 0.54), 0.2, 1.0), "bronze": ((0.71, 0.43, 0.18), 0.25, 1.0),
    "black": ((0.02, 0.02, 0.02), 0.25, 0.0), "white": ((0.85, 0.85, 0.85), 0.3, 0.0), "red": ((0.60, 0.02, 0.02), 0.3, 0.0),
    "blue": ((0.02, 0.12, 0.60), 0.3, 0.0), "green": ((0.02, 0.40, 0.08), 0.3, 0.0), "orange": ((0.85, 0.25, 0.01), 0.3, 0.0),
    "purple": ((0.25, 0.03, 0.50), 0.3, 0.0), "pink": ((0.85, 0.20, 0.40), 0.3, 0.0), "plastic": ((0.60, 0.02, 0.02), 0.3, 0.0),
    "wood": ((0.33, 0.20, 0.11), 0.5, 0.0), "marble": ((0.80, 0.78, 0.74), 0.15, 0.0),
}
BACK = {"dark": (0.006, 0.006, 0.008), "black": (0.0, 0.0, 0.0), "white": (0.8, 0.8, 0.8), "studio": (0.25, 0.25, 0.26), "blue": (0.004, 0.012, 0.05),
        "navy": (0.002, 0.006, 0.03), "red": (0.05, 0.003, 0.003), "green": (0.003, 0.03, 0.008), "purple": (0.02, 0.004, 0.05), "gradient": (0.01, 0.012, 0.03)}


def finish(name):
    if name == "glass":
        return C.material("text_glass", (0.9, 0.95, 1.0), 0.02, transmission=1.0)
    if name == "neon":
        col = spec.get("neon_color", (0.1, 0.85, 1.0))
        return C.material("text_neon", (0.02, 0.02, 0.02), 0.4, emit=col, emit_strength=6.0)
    col, rough, metal = FINISH.get(name, FINISH["gold"])
    m = C.material(f"text_{name}", col, rough, metal)
    try:
        bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        C._set(bsdf, ["Coat Weight", "Clearcoat"], 0.4 if metal == 0 else 0.0)
    except Exception:  # noqa: BLE001
        pass
    return m


font = next((f for f in (spec.get("font"), r"C:\Windows\Fonts\ariblk.ttf", r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf") if f and os.path.exists(f)), None)
mat = finish(spec.get("material", "gold"))
group = bpy.data.objects.new("title", None)
scene.collection.objects.link(group)
main = C.add_text(spec["text"], 1.0, (0, 0, 0), coll="title", mat=mat, extrude=0.12, rot=(math.radians(90), 0, 0), font=font, bevel=0.018)
main.data.bevel_resolution = 3
main.parent = group
subs = []
if spec.get("sub"):
    sub = C.add_text(spec["sub"], 0.30, (0, 0, -0.95), coll="title", mat=finish(spec.get("sub_material", "white" if spec.get("material") != "white" else "black")),
                     extrude=0.02, rot=(math.radians(90), 0, 0), font=font, bevel=0.004)
    sub.parent = group
    subs.append(sub)
logo = None
if spec.get("logo") and os.path.exists(spec["logo"]):
    img = bpy.data.images.load(spec["logo"], check_existing=True)
    aspect = img.size[0] / max(1, img.size[1])
    bpy.ops.mesh.primitive_plane_add(size=1.0)
    logo = bpy.context.object
    logo.scale = (1.2 * aspect, 1.2, 1)
    logo.rotation_euler = (math.radians(90), 0, 0)
    logo.data.materials.append(C.material("logo", (1, 1, 1), 0.5, image=spec["logo"]))
    logo.parent = group
bpy.context.view_layer.update()
# centre the title block on the origin (the logo to the left of the words)
lo, hi, _ = C.bounds([main] + subs)
if logo:
    logo.location = (lo.x - logo.scale[0] / 2 - 0.25, 0, (lo.z + hi.z) / 2)
    bpy.context.view_layer.update()
    lo, hi, _ = C.bounds([main] + subs + [logo])
shift = -(lo + hi) / 2
for ob in [main] + subs + ([logo] if logo else []):
    ob.location += Vector((shift.x, 0, shift.z))
bpy.context.view_layer.update()

# ---------------------------------------------------------------- light: studio panels the metal reflects, a rim, a sweep
bg = BACK.get(spec.get("background", "dark"), BACK["dark"])
C.studio_world(bg, strength=1.15)
lo, hi, _ = C.bounds([main] + subs + ([logo] if logo else []))
span = max(hi.x - lo.x, 1.0)


def panel(name, loc, rot, size, strength):
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=loc, rotation=rot)
    p = bpy.context.object
    p.name = name
    p.scale = (size[0], size[1], 1)
    p.data.materials.append(C.material(f"{name}_light", (0, 0, 0), 1.0, emit=(1, 1, 1), emit_strength=strength))
    p.visible_camera = False
    return p


panel("softbox_left", (-span * 0.8, -3.0, 2.5), (math.radians(60), 0, math.radians(-35)), (span * 0.8, 2.0), 6.0)
panel("softbox_right", (span * 0.8, -3.0, 2.0), (math.radians(65), 0, math.radians(35)), (span * 0.6, 1.6), 4.0)
panel("floor_bounce", (0, -2.0, -2.5), (math.radians(-60), 0, 0), (span * 1.2, 1.5), 1.5)
key = bpy.data.lights.new("key", "AREA")
key.energy, key.size = 900.0, 3.0
ko = bpy.data.objects.new("key", key)
scene.collection.objects.link(ko)
C.look(ko, (0, 0, 0), (-4, -6, 4))
rim = bpy.data.lights.new("rim", "AREA")
rim.energy, rim.size = 700.0, 4.0
ro = bpy.data.objects.new("rim", rim)
scene.collection.objects.link(ro)
C.look(ro, (0, 0, 0), (2, 5, 3))
sweep = panel("sweep", (-span * 1.6, -2.2, 1.6), (math.radians(70), 0, 0), (0.25, 3.0), 30.0)

# ---------------------------------------------------------------- motion
fps = int(spec.get("fps", 30))
n = max(30, int(spec.get("seconds", 5) * fps))
scene.frame_start, scene.frame_end = 1, n
scene.render.fps = fps
cam = C.camera("cam", lens=50)
C.look(cam, (0, 0, 0), (0, -8, 0.6))
C.engine("eevee", spec.get("w", 1920), spec.get("h", 1080), spec.get("samples", 32))
try:
    scene.view_settings.look = "AgX - Punchy"  # richer metal colours
except Exception:  # noqa: BLE001
    pass
lo, hi, pts = C.bounds([main] + subs + ([logo] if logo else []))
end_fr = C.fit(cam, pts, margin=spec.get("margin", 0.14))
end_loc = cam.location.copy()
fwd = (Vector((0, 0, 0)) - end_loc).normalized()
anim = spec.get("anim", "dolly")
settle = int(n * 0.62)
cam.location = end_loc - fwd * (end_loc.length * (0.9 if anim == "dolly" else 0.25)) + Vector((span * (0.35 if anim == "dolly" else 0.05), 0, 0.4))
cam.keyframe_insert("location", frame=1)
cam.location = end_loc
cam.keyframe_insert("location", frame=settle)
if anim == "spin":
    group.rotation_euler = (0, 0, math.radians(-100))
    group.keyframe_insert("rotation_euler", frame=1)
    group.rotation_euler = (0, 0, 0)
    group.keyframe_insert("rotation_euler", frame=settle)
elif anim in ("rise", "drop"):
    group.location = (0, 0, -2.5 if anim == "rise" else 3.0)
    group.keyframe_insert("location", frame=1)
    group.location = (0, 0, 0.12 if anim == "drop" else 0)
    group.keyframe_insert("location", frame=int(settle * 0.8))
    group.location = (0, 0, 0)
    group.keyframe_insert("location", frame=settle)
for s in subs:  # the second line pops in once the title has landed
    s.scale = (0.01, 0.01, 0.01)
    s.keyframe_insert("scale", frame=int(n * 0.45))
    s.scale = (1, 1, 1)
    s.keyframe_insert("scale", frame=int(n * 0.62))
sweep.location.x = -span * 1.6
sweep.keyframe_insert("location", index=0, frame=int(n * 0.45))
sweep.location.x = span * 1.6
sweep.keyframe_insert("location", index=0, frame=int(n * 0.92))
C.progress(10, "built")

# ---------------------------------------------------------------- the end frame: framing, silhouette, the picture; then every frame
scene.frame_set(n)
bpy.context.view_layer.update()
lo, hi, pts = C.bounds([main] + subs + ([logo] if logo else []))
result = {"framing": C.framing(cam, pts), "frames": n, "fps": fps, "version": bpy.app.version_string, "font": font}
hide = [o for o in scene.objects if o.type == "MESH" and o.name.startswith(("softbox", "floor_bounce", "sweep"))]
for o in hide:
    o.hide_render = True
result["mask_s"] = C.mask(spec["mask"], 480)
for o in hide:
    o.hide_render = False
C.engine("eevee", spec.get("w", 1920), spec.get("h", 1080), spec.get("still_samples", 64))
result["still_s"] = C.still(spec["still"])
C.engine("eevee", spec.get("w", 1920), spec.get("h", 1080), spec.get("samples", 32))
C.progress(20, "end frame")
if spec.get("frames_dir"):
    result["render_s"] = C.frames(spec["frames_dir"], 1, n, fps)
C.write(out_path, result)
