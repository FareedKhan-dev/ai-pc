"""Inside Blender: a house from its measured boxes (harness/three/house.py), lit, framed and rendered. Views:
  plan3d   one storey cut at 6 ft, from above at an angle, with furniture and the rooms' names (a 3D floor plan)
  top      the same straight down (orthographic, the road at the bottom like the drawing)
  front    the building from the road
  aerial   the building from above the road, at an angle
  orbit    a turn around the building (frames, made into a video by the host)
Each view also gets a flat silhouette (Workbench, transparent) and the place the building lands in the frame, for the
host's checks. Spec in, result out (JSON).
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
unit = spec["unit"]
made = C.add_boxes(spec["boxes"], unit, bevel=("furniture",))
labels_made = 0
for lab in spec.get("labels", []):
    ob = C.add_text(lab["text"], lab["size"] * unit, (lab["x"] * unit, lab["y"] * unit, lab["z"] * unit + 0.003), coll=f"labels_{lab['floor']}")
    bpy.context.view_layer.update()
    if lab.get("w") and ob.dimensions.x > lab["w"] * unit > 0:  # this font runs wider than the drawing's: shrink to the free width
        k = lab["w"] * unit / ob.dimensions.x
        ob.scale = (k, k, 1)
    labels_made += 1
C.world(tuple(spec.get("sky", (0.62, 0.72, 0.86))), spec.get("sky_strength", 1.0))
C.sun(elevation=spec.get("sun_elevation", 52), azimuth=spec.get("sun_azimuth", -38), strength=spec.get("sun_strength", 3.1))
C.progress(5, "built")


def show(prefixes):
    for c in bpy.data.collections:
        c.hide_render = not any(c.name.startswith(p) for p in prefixes)


def objs(prefixes, skip=()):
    out = []
    for c in bpy.data.collections:
        if any(c.name.startswith(p) for p in prefixes) and not any(s in c.name for s in skip):
            out += list(c.objects)
    return out


def subject_mask(path):
    """The silhouette of the building alone: the road, the land and the yard hidden for it."""
    hidden = [c for c in bpy.data.collections if c.name in ("out_site",) and not c.hide_render]
    for c in hidden:
        c.hide_render = True
    t = C.mask(path, 480)
    for c in hidden:
        c.hide_render = False
    return t


def place(cam, centre, az, el, dist):
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    C.look(cam, centre, centre + d * dist)


result = {"views": {}, "version": bpy.app.version_string}
storey = spec.get("storey", "ground")
inside = [f"in_{storey}", f"labels_{storey}"]
outside = ["out_"]
views = spec["views"]
for i, v in enumerate(views):
    kind = v["kind"]
    if kind in ("plan3d", "top"):
        show(inside)
        target = objs([f"in_{storey}"], skip=("_base",))
    else:
        show(outside)
        target = objs(["out_"], skip=("out_site",))
    lo, hi, pts = C.bounds(target)
    centre = (lo + hi) / 2
    diag = (hi - lo).length
    eng = C.engine(v.get("engine", "eevee"), v["w"], v["h"], v.get("samples"))
    if kind == "top":
        cam = C.camera(f"cam_{kind}", ortho=max(hi.x - lo.x, hi.y - lo.y) * 1.2)
        cam.location = (centre.x, centre.y, hi.z + 20)
        cam.rotation_euler = (0, 0, 0)
    else:
        lens, az, el = {"plan3d": (35, -22, 64), "front": (26, -18, 6), "aerial": (32, -34, 28), "orbit": (32, 0, 38)}[kind]
        cam = C.camera(f"cam_{kind}", lens=v.get("lens", lens))
        if kind == "front":  # eye height across the road, looking at the middle of the facade
            look_at = Vector((centre.x, lo.y + (hi.y - lo.y) * 0.25, lo.z + (hi.z - lo.z) * 0.42))
            place(cam, look_at, v.get("az", az), v.get("el", el), diag * 1.4)
        else:
            place(cam, centre, v.get("az", az), v.get("el", el), diag * 1.5)
    fr = C.fit(cam, pts, margin=v.get("margin", 0.05))
    entry = {"kind": kind, "engine": eng, "framing": fr, "w": v["w"], "h": v["h"]}
    if kind == "orbit":
        # the widest distance any side needs, so the whole building stays in the frame all the way round
        dist = 0.0
        for k in range(8):
            place(cam, centre, k * 45, v.get("el", el), diag * 1.5)
            C.fit(cam, pts, margin=v.get("margin", 0.09))
            dist = max(dist, (cam.location - centre).length * 1.04)
        pivot = bpy.data.objects.new("pivot", None)
        scene.collection.objects.link(pivot)
        pivot.location = centre
        e = math.radians(v.get("el", el))
        cam.location = Vector((0, -math.cos(e) * dist, math.sin(e) * dist))
        cam.rotation_euler = (math.radians(90) - e, 0, 0)
        cam.parent = pivot
        n = int(v.get("frames", 180))
        pivot.rotation_euler = (0, 0, 0)
        pivot.keyframe_insert("rotation_euler", index=2, frame=1)
        pivot.rotation_euler = (0, 0, math.radians(-360 * n / (n + 1)))  # a seamless loop: the last frame stops one step short
        pivot.keyframe_insert("rotation_euler", index=2, frame=n)
        try:
            for fc in pivot.animation_data.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
        except Exception:  # noqa: BLE001  (newer animation data layouts)
            try:
                for layer in pivot.animation_data.action.layers:
                    for strip in layer.strips:
                        for bag in strip.channelbags:
                            for fc in bag.fcurves:
                                for kp in fc.keyframe_points:
                                    kp.interpolation = "LINEAR"
            except Exception:  # noqa: BLE001
                pass
        bpy.context.view_layer.update()
        scene.frame_set(1)
        worst = None
        for f in (1, n // 4, n // 2, 3 * n // 4, n):  # where the building lands on the way round
            scene.frame_set(f)
            bpy.context.view_layer.update()
            fr_k = C.framing(cam, pts)
            worst = fr_k if worst is None else {"x0": min(worst["x0"], fr_k["x0"]), "x1": max(worst["x1"], fr_k["x1"]),
                                                "y0": min(worst["y0"], fr_k["y0"]), "y1": max(worst["y1"], fr_k["y1"]),
                                                "behind": max(worst["behind"], fr_k["behind"])}
        entry["framing"] = worst
        scene.frame_set(1)
        entry["mask_s"] = subject_mask(v["mask"])
        C.engine(v.get("engine", "eevee"), v["w"], v["h"], v.get("samples"))
        entry["render_s"] = C.frames(v["frames_dir"], 1, n, int(v.get("fps", 30)))
        entry["frames"] = n
    else:
        entry["mask_s"] = subject_mask(v["mask"])
        C.engine(v.get("engine", "eevee"), v["w"], v["h"], v.get("samples"))
        entry["render_s"] = C.still(v["path"])
    result["views"][v["name"]] = entry
    C.progress(10 + 90 * (i + 1) / len(views), kind)
result["objects"] = len(bpy.data.objects)
result["labels"] = labels_made
result["collections"] = {c.name: sum(len(o.data.polygons) // 6 for o in c.objects if o.type == "MESH") for c in bpy.data.collections}
if spec.get("blend"):
    show(["in_", "out_", "labels_"])
    bpy.ops.wm.save_as_mainfile(filepath=spec["blend"], compress=True)
C.write(out_path, result)
