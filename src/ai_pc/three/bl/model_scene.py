"""Inside Blender: someone's 3D file opened, measured, pictured and converted.
  measure  size (metres and millimetres), objects, vertices, triangles, materials; for 3D printing: open edges and
           edges shared by more than two faces (not watertight), the volume when it is closed
  views    studio pictures (front, three-quarter, top) and a turn around (frames for the host), with silhouettes
  export   the file saved as another kind (glb, gltf, obj, fbx, stl, ply, usd), then opened again and measured, so
           nothing was lost on the way
Spec in, result out (JSON).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import common as C  # noqa: E402

spec, out_path = C.args()
IMPORT = {
    ".glb": lambda p: bpy.ops.import_scene.gltf(filepath=p), ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".obj": lambda p: bpy.ops.wm.obj_import(filepath=p), ".fbx": lambda p: bpy.ops.import_scene.fbx(filepath=p),
    ".stl": lambda p: bpy.ops.wm.stl_import(filepath=p), ".ply": lambda p: bpy.ops.wm.ply_import(filepath=p),
    ".usd": lambda p: bpy.ops.wm.usd_import(filepath=p), ".usdz": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usda": lambda p: bpy.ops.wm.usd_import(filepath=p), ".usdc": lambda p: bpy.ops.wm.usd_import(filepath=p),
}
EXPORT = {
    "glb": lambda p: bpy.ops.export_scene.gltf(filepath=p, export_format="GLB"),
    "gltf": lambda p: bpy.ops.export_scene.gltf(filepath=p, export_format="GLTF_SEPARATE"),
    "obj": lambda p: bpy.ops.wm.obj_export(filepath=p), "fbx": lambda p: bpy.ops.export_scene.fbx(filepath=p),
    "stl": lambda p: bpy.ops.wm.stl_export(filepath=p), "ply": lambda p: bpy.ops.wm.ply_export(filepath=p),
    "usd": lambda p: bpy.ops.wm.usd_export(filepath=p), "usdz": lambda p: bpy.ops.wm.usd_export(filepath=p),
}


def load(path):
    C.reset()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".blend":
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for ob in dst.objects:
            if ob is not None:
                bpy.context.scene.collection.objects.link(ob)
    elif ext in IMPORT:
        IMPORT[ext](path)
    else:
        raise SystemExit(f"cannot open {ext} files")
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def measure(meshes):
    dg = bpy.context.evaluated_depsgraph_get()
    verts = tris = open_edges = many = 0
    volume, closed = 0.0, True
    mats = set()
    for ob in meshes:
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        verts += len(me.vertices)
        tris += len(me.loop_triangles)
        mats |= {m.name for m in ob.data.materials if m}
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(ob.matrix_world)
        for e in bm.edges:
            n = len(e.link_faces)
            open_edges += n < 2
            many += n > 2
        if any(len(e.link_faces) != 2 for e in bm.edges):
            closed = False
        else:
            volume += abs(bm.calc_volume(signed=True))
        bm.free()
        ev.to_mesh_clear()
    lo, hi, pts = C.bounds(meshes)
    size = hi - lo
    return {"objects": len(meshes), "vertices": verts, "triangles": tris, "materials": len(mats), "size_m": [round(v, 5) for v in size],
            "open_edges": open_edges, "many_faced_edges": many, "watertight": closed and many == 0, "volume_m3": round(volume, 9) if closed else None}, pts


meshes = load(spec["file"])
if not meshes:
    raise SystemExit("there is no 3D shape in the file")
stats, pts = measure(meshes)
result = {"stats": stats, "views": {}, "version": bpy.app.version_string}
# ---------------------------------------------------------------- saved as another kind (from the clean scene), opened again, measured again
ex = spec.get("export")
if ex:
    if ex["fmt"] not in EXPORT:
        raise SystemExit(f"cannot save {ex['fmt']} files")
    EXPORT[ex["fmt"]](ex["path"])
    again = load(ex["path"])
    st2, _ = measure(again)
    result["export"] = {"path": ex["path"], "stats": st2}
    meshes = load(spec["file"])
    stats, pts = measure(meshes)
C.progress(10, "measured")
# ---------------------------------------------------------------- pictures in a studio (the model stays where it is)
if spec.get("views"):
    scene = bpy.context.scene
    lo, hi, _ = C.bounds(meshes)
    centre, size = (lo + hi) / 2, max((hi - lo).length, 1e-4)
    bpy.ops.mesh.primitive_plane_add(size=size * 40, location=(centre.x, centre.y, lo.z))
    floor = bpy.context.object
    floor.data.materials.append(C.material("studio_floor", (0.75, 0.75, 0.77), 0.6))
    C.world((0.6, 0.62, 0.66), 0.8)
    for nm, off, energy in (("key", (-2.0, -2.5, 3.0), 80.0), ("fill", (3.0, -2.0, 1.5), 30.0), ("rim", (1.0, 3.0, 2.5), 50.0)):
        L = bpy.data.lights.new(nm, "AREA")
        L.energy, L.size = energy * size * size * 4, size * 1.5
        lo_ = bpy.data.objects.new(nm, L)
        scene.collection.objects.link(lo_)
        C.look(lo_, centre, centre + Vector(off) * size)
    for i, v in enumerate(spec["views"]):
        C.engine(v.get("engine", "eevee"), v["w"], v["h"], v.get("samples", 48))
        cam = C.camera(f"cam_{v['name']}", lens=50, ortho=size * 1.4 if v["kind"] == "top" else None)
        az, el = {"front": (0, 8), "three_quarter": (-35, 22), "top": (0, 89.9), "side": (-90, 8), "orbit": (0, 22)}.get(v["kind"], (-35, 22))
        az += spec.get("turn", 0)
        a_, e_ = math.radians(az), math.radians(el)
        C.look(cam, centre, centre + Vector((math.sin(a_) * math.cos(e_), -math.cos(a_) * math.cos(e_), math.sin(e_))) * size * 3)
        fr = C.fit(cam, pts, margin=0.1)
        entry = {"kind": v["kind"], "framing": fr}
        floor.hide_render = True
        entry["mask_s"] = C.mask(v["mask"], 480)
        floor.hide_render = False
        C.engine(v.get("engine", "eevee"), v["w"], v["h"], v.get("samples", 48))
        if v["kind"] == "orbit":
            pivot = bpy.data.objects.new("pivot", None)
            scene.collection.objects.link(pivot)
            pivot.location = centre
            dist = (cam.location - centre).length
            cam.location = Vector((0, -math.cos(e_) * dist, math.sin(e_) * dist))
            cam.rotation_euler = (math.radians(90) - e_, 0, 0)
            cam.parent = pivot
            n = int(v.get("frames", 120))
            pivot.keyframe_insert("rotation_euler", index=2, frame=1)
            pivot.rotation_euler = (0, 0, math.radians(360 * n / (n + 1)))
            pivot.keyframe_insert("rotation_euler", index=2, frame=n)
            try:
                for fc in pivot.animation_data.action.fcurves:
                    for kp in fc.keyframe_points:
                        kp.interpolation = "LINEAR"
            except Exception:  # noqa: BLE001
                pass
            entry["render_s"] = C.frames(v["frames_dir"], 1, n, int(v.get("fps", 30)))
            entry["frames"] = n
        else:
            entry["render_s"] = C.still(v["path"])
        result["views"][v["name"]] = entry
        C.progress(10 + 70 * (i + 1) / len(spec["views"]), v["kind"])
C.write(out_path, result)
