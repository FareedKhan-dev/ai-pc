"""Helpers that run INSIDE Blender (bpy, the standard library, nothing else): an empty scene, materials, boxes and
ramps from measured specs, text, sun and sky, cameras that frame what they are given, render settings for EEVEE,
Cycles on the Intel GPU (oneAPI) or Workbench, stills, flat silhouette masks for checks, and frame sequences.

A scene script is run as:  blender -b --factory-startup --python-exit-code 1 -P <script> -- <spec.json> <result.json>
"""
import json
import math
import sys
import time

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

# key: colour (linear), roughness, metal, and a pattern drawn in metres on world coordinates (one object per material
# holds every box, so the pattern runs on across them): (kind, size, second colour, joint colour, facade)
# kinds: noise (plaster), tiles (square, grouted), bricks, stone (long courses), planks (wood), grass, grain
MATS = {
    "plaster_white": ((0.86, 0.85, 0.82), 0.85, 0.0, ("noise", 6.0, None, None, False)),
    "plaster_cream": ((0.86, 0.78, 0.62), 0.85, 0.0, ("noise", 6.0, None, None, False)),
    "plaster_grey": ((0.20, 0.205, 0.21), 0.85, 0.0, ("noise", 6.0, None, None, False)),
    "plaster_inside": ((0.88, 0.87, 0.84), 0.9, 0.0, None),
    "stone_grey": ((0.30, 0.29, 0.27), 0.75, 0.0, ("stone", 0.45, (0.20, 0.19, 0.18), (0.06, 0.06, 0.06), True)),
    "wood_light": ((0.45, 0.27, 0.13), 0.55, 0.0, ("planks", 0.15, (0.32, 0.18, 0.08), (0.10, 0.06, 0.03), True)),
    "wood_dark": ((0.16, 0.09, 0.05), 0.5, 0.0, ("grain", 8.0, (0.10, 0.055, 0.03), None, False)),
    "wood_furn": ((0.33, 0.20, 0.11), 0.5, 0.0, ("grain", 8.0, (0.24, 0.14, 0.07), None, False)),
    "wood_floor": ((0.42, 0.26, 0.14), 0.45, 0.0, ("planks", 0.18, (0.30, 0.17, 0.08), (0.12, 0.07, 0.035), False)),
    "brick_red": ((0.40, 0.12, 0.07), 0.9, 0.0, ("bricks", 0.23, (0.33, 0.09, 0.05), (0.45, 0.43, 0.40), True)),
    "frame_black": ((0.03, 0.03, 0.03), 0.4, 0.3, None), "frame_brown": ((0.14, 0.07, 0.03), 0.5, 0.0, None),
    "frame_white": ((0.85, 0.85, 0.85), 0.4, 0.0, None),
    "marble": ((0.80, 0.77, 0.71), 0.15, 0.0, ("tiles", 0.6, (0.74, 0.71, 0.66), (0.62, 0.60, 0.56), False)),
    "tiles_grey": ((0.55, 0.56, 0.57), 0.3, 0.0, ("tiles", 0.3, (0.50, 0.51, 0.52), (0.30, 0.30, 0.30), False)),
    "tiles_bath": ((0.62, 0.72, 0.77), 0.25, 0.0, ("tiles", 0.2, (0.58, 0.68, 0.73), (0.85, 0.85, 0.85), False)),
    "tiles_terrace": ((0.50, 0.33, 0.24), 0.6, 0.0, ("tiles", 0.3, (0.44, 0.29, 0.21), (0.30, 0.28, 0.26), False)),
    "concrete": ((0.42, 0.42, 0.40), 0.9, 0.0, ("noise", 3.0, None, None, False)),
    "concrete_slab": ((0.62, 0.61, 0.58), 0.9, 0.0, ("noise", 3.0, None, None, False)),
    "plinth": ((0.27, 0.26, 0.25), 0.9, 0.0, ("noise", 3.0, None, None, False)),
    "yard_tiles": ((0.50, 0.47, 0.42), 0.8, 0.0, ("tiles", 0.45, (0.45, 0.42, 0.37), (0.28, 0.27, 0.25), False)),
    "site": ((0.42, 0.39, 0.34), 0.95, 0.0, ("noise", 1.5, None, None, False)),
    "asphalt": ((0.05, 0.05, 0.055), 0.95, 0.0, ("noise", 20.0, None, None, False)),
    "sidewalk": ((0.44, 0.42, 0.39), 0.9, 0.0, ("tiles", 0.6, (0.40, 0.38, 0.35), (0.25, 0.24, 0.22), False)),
    "grass": ((0.08, 0.20, 0.05), 0.95, 0.0, ("grass", 12.0, (0.05, 0.14, 0.03), None, False)),
    "gate_metal": ((0.04, 0.04, 0.04), 0.35, 0.8, None), "wall_cap": ((0.10, 0.10, 0.10), 0.9, 0.0, None),
    "fabric_white": ((0.82, 0.82, 0.80), 0.9, 0.0, None), "fabric_accent": ((0.14, 0.25, 0.37), 0.9, 0.0, None),
    "fabric_sofa": ((0.52, 0.44, 0.34), 0.95, 0.0, ("noise", 40.0, None, None, False)), "screen": ((0.01, 0.01, 0.012), 0.1, 0.0, None),
    "ceramic": ((0.90, 0.90, 0.90), 0.1, 0.0, None), "steel": ((0.65, 0.65, 0.67), 0.3, 1.0, None),
    "counter": ((0.14, 0.14, 0.16), 0.25, 0.0, ("noise", 30.0, None, None, False)), "car_paint": ((0.52, 0.53, 0.55), 0.22, 0.7, None),
    "car_glass": ((0.03, 0.04, 0.05), 0.05, 0.0, None), "tyre": ((0.015, 0.015, 0.015), 0.8, 0.0, None), "label": ((0.06, 0.06, 0.06), 0.8, 0.0, None),
}
GLASS = {"glass": ((0.55, 0.70, 0.78), 0.05, 0.28)}


def args():
    a = sys.argv[sys.argv.index("--") + 1:]
    with open(a[0], encoding="utf-8") as f:
        return json.load(f), a[1]


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def progress(pct, what=""):
    print(f"PROGRESS {int(pct)} {what}", flush=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    return scene


def _set(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return True
    return False


def material(name, color, rough=0.5, metal=0.0, alpha=1.0, emit=None, emit_strength=0.0, image=None, transmission=0.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:  # noqa: BLE001  (always on in newer versions)
        pass
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    _set(bsdf, ["Base Color"], (*color, 1.0))
    _set(bsdf, ["Roughness"], rough)
    _set(bsdf, ["Metallic"], metal)
    if transmission:
        _set(bsdf, ["Transmission Weight", "Transmission"], transmission)
    if emit:
        _set(bsdf, ["Emission Color", "Emission"], (*emit, 1.0))
        _set(bsdf, ["Emission Strength"], emit_strength)
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(image, check_existing=True)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if image.lower().endswith(".png"):
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            alpha = min(alpha, 0.999)
    if alpha < 1.0:
        _set(bsdf, ["Alpha"], alpha) if not image else None
        for attr, val in (("surface_render_method", "DITHERED"), ("blend_method", "HASHED")):
            try:
                setattr(m, attr, val)
                break
            except Exception:  # noqa: BLE001
                continue
    m.diffuse_color = (*color, 1.0)  # what Workbench shows
    return m


def lib_material(key):
    if key in GLASS:
        c, r, a = GLASS[key]
        return material(key, c, r, alpha=a)
    c, r, mt, pat = MATS.get(key, ((0.6, 0.6, 0.6), 0.6, 0.0, None))
    m = material(key, c, r, mt)
    if pat:
        try:
            _pattern(m, c, *pat)
        except Exception as e:  # noqa: BLE001  (a pattern is a nicety: the plain colour stays)
            print(f"pattern for {key} skipped: {e}")
    return m


def _pattern(m, c1, kind, size, c2, joint, facade):
    """Draw a pattern into a material's base colour (with a little relief where joints are): world coordinates in
    metres, turned upright for facades so courses run across and up the wall."""
    nt = m.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    tc = nodes.new("ShaderNodeTexCoord")
    mp = nodes.new("ShaderNodeMapping")
    if facade:
        mp.inputs["Rotation"].default_value = (1.5708, 0, 0)  # x stays across; z (up the wall) becomes y
    links.new(tc.outputs["Object"], mp.inputs["Vector"])
    c2 = c2 or tuple(v * 0.9 for v in c1)
    if kind in ("noise", "grass", "grain"):
        tx = nodes.new("ShaderNodeTexNoise")
        tx.inputs["Scale"].default_value = size
        if kind == "grain":
            tx.inputs["Detail"].default_value = 6
            mp.inputs["Scale"].default_value = (1, 12, 1)  # stretched along y: grain
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        links.new(mp.outputs["Vector"], tx.inputs["Vector"])
        mix.inputs[6].default_value = (*(v * (0.93 if kind == "noise" else 1.0) for v in c1), 1)
        mix.inputs[7].default_value = (*(c2 if kind != "noise" else tuple(min(1.0, v * 1.06) for v in c1)), 1)
        links.new(tx.outputs["Fac"], mix.inputs[0])
        links.new(mix.outputs[2], bsdf.inputs["Base Color"])
        return
    br = nodes.new("ShaderNodeTexBrick")
    links.new(mp.outputs["Vector"], br.inputs["Vector"])
    br.inputs["Color1"].default_value = (*c1, 1)
    br.inputs["Color2"].default_value = (*c2, 1)
    br.inputs["Mortar"].default_value = (*(joint or (0.3, 0.3, 0.3)), 1)
    br.inputs["Scale"].default_value = 1.0
    shapes = {"tiles": (size, size, 0.004, 0.0), "bricks": (size, 0.076, 0.010, 0.5), "stone": (size, size * 0.42, 0.008, 0.5),
              "planks": (size * 8, size, 0.002, 0.33)}
    bw, rh, mortar, offset = shapes.get(kind, (size, size, 0.004, 0.0))
    br.inputs["Brick Width"].default_value = bw
    br.inputs["Row Height"].default_value = rh
    br.inputs["Mortar Size"].default_value = mortar
    br.offset = offset
    links.new(br.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.35
    links.new(br.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def collection(name):
    c = bpy.data.collections.get(name)
    if not c:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


BOX_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 4, 7, 3), (1, 2, 6, 5)]
RAMP_FACES = [(0, 3, 2, 1), (2, 3, 4, 5), (0, 1, 5, 4), (0, 4, 3), (1, 2, 5)]


def add_boxes(boxes, unit=0.0254, bevel=(), mats=None):
    """Boxes ({"n", "c", "m", "b": [x0, y0, z0, x1, y1, z1]}) and ramps ({"w": [...]}: rising along +y) as one mesh
    per collection and material. Returns {collection: [objects]}."""
    groups = {}
    for b in boxes:
        groups.setdefault((b["c"], b["m"]), []).append(b)
    made = {}
    for (cname, mname), items in groups.items():
        verts, faces = [], []
        for it in items:
            if "b" in it:
                x0, y0, z0, x1, y1, z1 = (v * unit for v in it["b"])
                k = len(verts)
                verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
                faces += [tuple(k + i for i in f) for f in BOX_FACES]
            elif "w" in it:
                x0, y0, z0, x1, y1, z1 = (v * unit for v in it["w"])
                k = len(verts)
                verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)]
                faces += [tuple(k + i for i in f) for f in RAMP_FACES]
        mesh = bpy.data.meshes.new(f"{cname}__{mname}")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(f"{cname}__{mname}", mesh)
        collection(cname).objects.link(obj)
        obj.data.materials.append((mats or {}).get(mname) or lib_material(mname))
        if any(cname.endswith(s) for s in bevel):
            mod = obj.modifiers.new("soft edges", "BEVEL")
            mod.width, mod.segments, mod.limit_method = 0.012, 2, "ANGLE"
        made.setdefault(cname, []).append(obj)
    return made


def add_text(text, size, loc, coll="labels", mat="label", align="CENTER", extrude=0.0005, rot=(0, 0, 0), font=None, bevel=0.0):
    cu = bpy.data.curves.new(f"text_{text[:12]}", type="FONT")
    cu.body = text
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.extrude = extrude
    cu.bevel_depth = bevel
    if font:
        try:
            cu.font = bpy.data.fonts.load(font, check_existing=True)
        except Exception:  # noqa: BLE001
            pass
    ob = bpy.data.objects.new(f"text_{text[:12]}", cu)
    ob.location = loc
    ob.rotation_euler = rot
    collection(coll).objects.link(ob)
    ob.data.materials.append(lib_material(mat) if isinstance(mat, str) else mat)
    return ob


def world(color=(0.62, 0.72, 0.86), strength=1.0):
    w = bpy.data.worlds.new("world")
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:  # noqa: BLE001
        pass
    bg = next((n for n in w.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs["Color"].default_value = (*color, 1.0)
        bg.inputs["Strength"].default_value = strength
    w.color = color
    return w


def studio_world(background, strength=1.6, floor=0.03, band=1.0, top=0.25):
    """What the camera sees is the background colour; what reflections and light see is a studio: a bright band all
    round at eye level (softboxes), a dimmer ceiling, a dark floor, so metal and glass have something to show."""
    w = bpy.data.worlds.new("studio")
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:  # noqa: BLE001
        pass
    nt = w.node_tree
    nodes, links = nt.nodes, nt.links
    for n in list(nodes):
        nodes.remove(n)
    out = nodes.new("ShaderNodeOutputWorld")
    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")  # by height of the direction: floor, band, ceiling
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.40, (floor, floor, floor, 1)
    cr.elements[1].position, cr.elements[1].color = 0.62, (top, top, top, 1)
    e = cr.elements.new(0.50)
    e.color = (band, band, band, 1)
    fac = nodes.new("ShaderNodeMath")  # the direction's height, -1..1, as 0..1 for the ramp
    fac.operation = "MULTIPLY_ADD"
    fac.inputs[1].default_value, fac.inputs[2].default_value = 0.5, 0.5
    links.new(sep.outputs["Z"], fac.inputs[0])
    links.new(fac.outputs["Value"], ramp.inputs["Fac"])
    env = nodes.new("ShaderNodeBackground")
    links.new(ramp.outputs["Color"], env.inputs["Color"])
    env.inputs["Strength"].default_value = strength
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (*background, 1)
    lp = nodes.new("ShaderNodeLightPath")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    links.new(env.outputs["Background"], mix.inputs[1])
    links.new(bg.outputs["Background"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    w.color = background
    return w


def sun(elevation=50, azimuth=-35, strength=3.5, angle=2.0):
    """Sun light coming from the front-left (azimuth measured from the -y axis, the road side) at an elevation."""
    d = bpy.data.lights.new("sun", type="SUN")
    d.energy = strength
    d.angle = math.radians(angle)
    ob = bpy.data.objects.new("sun", d)
    bpy.context.scene.collection.objects.link(ob)
    ob.rotation_euler = (math.radians(90 - elevation), 0, math.radians(azimuth))
    return ob


def bounds(objs):
    pts = []
    for ob in objs:
        if ob.type in ("MESH", "FONT", "CURVE"):
            pts += [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    if not pts:
        return Vector((0, 0, 0)), Vector((1, 1, 1)), []
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi, pts


def camera(name="cam", lens=35.0, ortho=None):
    c = bpy.data.cameras.new(name)
    c.lens = lens
    c.clip_start, c.clip_end = 0.05, 2000
    if ortho:
        c.type = "ORTHO"
        c.ortho_scale = ortho
    ob = bpy.data.objects.new(name, c)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def look(ob, target, frm):
    ob.location = Vector(frm)
    d = Vector(target) - Vector(frm)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def fit(cam, pts, margin=0.06):
    """Frame the points: a perspective camera is moved (Blender's own fit for its direction, then pulled back for the
    margin); an orthographic one is re-centred and scaled. Returns where the points land (0-1 across and up)."""
    scene = bpy.context.scene
    bpy.context.view_layer.update()
    if cam.data.type == "ORTHO":
        for _ in range(3):
            fr = framing(cam, pts)
            aspect = scene.render.resolution_y / scene.render.resolution_x
            w = cam.data.ortho_scale if aspect <= 1 else cam.data.ortho_scale / aspect
            h = w * aspect
            q = cam.matrix_world.to_quaternion()
            cam.location += q @ Vector((((fr["x0"] + fr["x1"]) / 2 - 0.5) * w, ((fr["y0"] + fr["y1"]) / 2 - 0.5) * h, 0))
            cam.data.ortho_scale *= max(fr["x1"] - fr["x0"], fr["y1"] - fr["y0"]) / (1 - 2 * margin)
            bpy.context.view_layer.update()
        return framing(cam, pts)
    dg = bpy.context.evaluated_depsgraph_get()
    co, _ = cam.camera_fit_coords(dg, [c for p in pts for c in p])
    cam.location = co
    bpy.context.view_layer.update()
    fwd = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    dist = (Vector(_centre(pts)) - cam.location).dot(fwd)
    cam.location -= fwd * dist * (1 / (1 - 2 * margin) - 1)
    bpy.context.view_layer.update()
    return framing(cam, pts)


def _centre(pts):
    n = len(pts) or 1
    return (sum(p.x for p in pts) / n, sum(p.y for p in pts) / n, sum(p.z for p in pts) / n)


def framing(cam, pts):
    scene = bpy.context.scene
    co = [world_to_camera_view(scene, cam, p) for p in pts]
    behind = sum(1 for c in co if c.z <= 0)
    xs, ys = [c.x for c in co if c.z > 0], [c.y for c in co if c.z > 0]
    if not xs:
        return {"x0": 0, "x1": 1, "y0": 0, "y1": 1, "behind": behind}
    return {"x0": round(min(xs), 4), "x1": round(max(xs), 4), "y0": round(min(ys), 4), "y1": round(max(ys), 4), "behind": behind}


def engine(kind="eevee", w=1920, h=1080, samples=None, transparent=False):
    scene = bpy.context.scene
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = int(w), int(h), 100
    r.film_transparent = transparent
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA" if transparent else "RGB"
    if kind == "cycles":
        r.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        gpu = False
        try:
            prefs.compute_device_type = "ONEAPI"
            prefs.get_devices()
            for d in prefs.devices:
                d.use = d.type == "ONEAPI"
                gpu = gpu or d.type == "ONEAPI"
        except Exception:  # noqa: BLE001
            gpu = False
        scene.cycles.device = "GPU" if gpu else "CPU"
        scene.cycles.samples = samples or 128
        scene.cycles.use_denoising = True
        return "Cycles on the " + ("Intel GPU" if gpu else "processor")
    if kind == "workbench":
        r.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light = "FLAT"
        sh.color_type = "SINGLE"
        sh.single_color = (1, 1, 1)
        scene.display.render_aa = "OFF"
        return "Workbench"
    r.engine = "BLENDER_EEVEE"
    ee = scene.eevee
    for attr, val in (("taa_render_samples", samples or 48), ("use_raytracing", True), ("use_shadows", True), ("use_gtao", True)):
        try:
            setattr(ee, attr, val)
        except Exception:  # noqa: BLE001
            pass
    try:
        scene.view_settings.view_transform = "AgX"
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:  # noqa: BLE001
        pass
    return "EEVEE"


def still(path):
    t0 = time.time()
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return round(time.time() - t0, 2)


def mask(path, w=480, h=None):
    """A flat white silhouette on a clear background (Workbench, seconds): what the camera sees of the scene, for checks."""
    scene = bpy.context.scene
    keep = (scene.render.engine, scene.render.resolution_x, scene.render.resolution_y, scene.render.film_transparent,
            scene.render.image_settings.color_mode)
    h = h or int(w * keep[2] / keep[1])
    engine("workbench", w, h, transparent=True)
    t = still(path)
    r = scene.render
    r.engine, r.resolution_x, r.resolution_y, r.film_transparent = keep[0], keep[1], keep[2], keep[3]
    r.image_settings.color_mode = keep[4]
    return t


def frames(folder, start, end, fps=30):
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = start, end
    scene.render.fps = fps
    scene.render.filepath = folder.rstrip("/\\") + "/frame_####"
    t0 = time.time()
    bpy.ops.render.render(animation=True)
    return round(time.time() - t0, 2)
