"""Inside Blender: a product mockup with the person's picture on it, lit like a studio or a desk by a window:
  box     a package (w x h x d cm) with the picture on its front, the second on its side, its colour elsewhere
  card    two business cards on a desk, one face up, one showing its back (or the same picture)
  laptop  a laptop with the picture on its screen          phone   a phone with the picture on its screen
  mug     a mug with the picture round it                   poster  the picture framed on a wall
The picture is mapped exactly (UVs made here); where its face lands in the frame is reported for the host's check
that the picture really shows. Spec in, result out (JSON).
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
scene = C.reset()
kind = spec["kind"]
images = spec.get("images") or []


def img_mat(path, name, rough=0.35, gloss=False):
    m = C.material(name, (1, 1, 1), 0.12 if gloss else rough, image=path)
    return m


def avg_colour(path):
    im = bpy.data.images.load(path, check_existing=True)
    px = list(im.pixels[:])
    if not px:
        return (0.5, 0.5, 0.5)
    step = max(4, (len(px) // 4 // 4000) * 4)
    r = [px[i] for i in range(0, len(px), step)]
    g = [px[i + 1] for i in range(0, len(px) - 1, step)]
    b = [px[i + 2] for i in range(0, len(px) - 2, step)]
    return (sum(r) / len(r), sum(g) / len(g), sum(b) / len(b))


def aspect(path):
    im = bpy.data.images.load(path, check_existing=True)
    return im.size[0] / max(1, im.size[1])


def box(name, w, d, h, loc, face_mats, rest_mat):
    """A box w (x) by d (y) by h (z) metres, its faces' materials: {'front': mat, 'right': mat, 'top': mat, ...}, each face
    with UVs 0-1 across it, the picture the right way up. Returns the object and its faces' world corners."""
    bm = bmesh.new()
    x0, x1, y0, y1, z0, z1 = -w / 2, w / 2, -d / 2, d / 2, 0, h
    v = [bm.verts.new(p) for p in [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]]
    faces = {"bottom": (0, 3, 2, 1), "top": (4, 5, 6, 7), "front": (0, 1, 5, 4), "back": (2, 3, 7, 6), "left": (3, 0, 4, 7), "right": (1, 2, 6, 5)}
    mats = [rest_mat] + [m for m in face_mats.values()]
    slot = {k: (1 + list(face_mats).index(k)) if k in face_mats else 0 for k in faces}
    uv = bm.loops.layers.uv.new("UVMap")
    corners = {}
    for fname, idx in faces.items():
        f = bm.faces.new([v[i] for i in idx])
        f.material_index = slot[fname]
        for loop, (u, vv) in zip(f.loops, [(0, 0), (1, 0), (1, 1), (0, 1)]):
            loop[uv].uv = (u, vv)
        corners[fname] = [tuple(v[i].co) for i in idx]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    for m in mats:
        ob.data.materials.append(m)
    ob.location = loc
    bev = ob.modifiers.new("edges", "BEVEL")
    bev.width, bev.segments = min(w, d, h) * 0.02, 3
    return ob, corners


def world_of(ob, local_pts):
    bpy.context.view_layer.update()
    return [ob.matrix_world @ Vector(p) for p in local_pts]


def cylinder(name, r, h, loc, mat, segs=64):
    """An open-topped cylinder (a mug) with the picture wrapped once round its side (UVs made here)."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    bot = [bm.verts.new((r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs), 0)) for k in range(segs)]
    top = [bm.verts.new((r * math.cos(2 * math.pi * k / segs), r * math.sin(2 * math.pi * k / segs), h)) for k in range(segs)]
    for k in range(segs):
        a, b = k, (k + 1) % segs
        f = bm.faces.new([bot[a], bot[b], top[b], top[a]])
        u0 = k / segs - 0.25  # the picture's middle (u 0.5) at 270 degrees, facing -y; the handle at 0 degrees (+x)
        u1 = u0 + 1 / segs
        for loop, (u, vv) in zip(f.loops, [(u0, 0), (u1, 0), (u1, 1), (u0, 1)]):
            loop[uv].uv = (u % 1.0 if u0 >= 0 else u + 1.0, vv)
    base = bm.faces.new(list(reversed(bot)))
    base.material_index = 1
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.data.materials.append(mat)
    ob.data.materials.append(C.material("ceramic_in", (0.9, 0.9, 0.9), 0.1))
    sol = ob.modifiers.new("wall", "SOLIDIFY")
    sol.thickness = 0.004
    ob.location = loc
    return ob


# ---------------------------------------------------------------- the object
img0 = images[0] if images else None
faces = {}
subject = []
size = spec.get("size") or {}
if kind == "box":
    a = aspect(img0) if img0 else 1.0
    w = size.get("w", 20.0) / 100
    h = size.get("h", w * 100 / a) / 100 if size.get("h") else w / a
    d = size.get("d", w * 100 * 0.38) / 100 if size.get("d") else w * 0.38
    fm = {"front": img_mat(img0, "front", gloss=True)} if img0 else {}
    if len(images) > 1:
        fm["right"] = img_mat(images[1], "side", gloss=True)
    rest = C.material("box_rest", avg_colour(img0) if img0 else (0.6, 0.6, 0.6), 0.3)
    ob, loc_faces = box("box", w, d, h, (0, 0, 0), fm, rest)
    faces["picture"] = world_of(ob, loc_faces["front"])
    subject = [ob]
elif kind == "card":
    w, h, t = 0.089, 0.051, 0.0006
    if img0 and aspect(img0) < 1:
        w, h = h, w
    back = images[1] if len(images) > 1 else img0
    ob1, w1 = box("card_front", w, h, t, (-0.02, -0.01, 0), {"top": img_mat(img0, "card_a", 0.6)} if img0 else {}, C.material("card_edge", (0.9, 0.9, 0.9), 0.6))
    ob1.rotation_euler = (0, 0, math.radians(-8))
    ob2, w2 = box("card_back", w, h, t, (0.035, 0.03, 0.0), {"top": img_mat(back, "card_b", 0.6)} if back else {}, C.material("card_edge", (0.9, 0.9, 0.9), 0.6))
    ob2.rotation_euler = (math.radians(4), 0, math.radians(14))
    ob2.location.z = 0.006
    faces["picture"] = world_of(ob1, w1["top"])
    subject = [ob1, ob2]
elif kind in ("phone", "laptop"):
    a = aspect(img0) if img0 else (9 / 19.5 if kind == "phone" else 16 / 10)
    if kind == "phone":
        bw, bh = (0.0715, 0.147) if a <= 1 else (0.147, 0.0715)  # turned sideways for a wide picture
        gw, gh = bw - 0.006, bh - 0.006  # the glass
        sw, sh = (gw, gw / a) if gw / a <= gh else (gh * a, gh)  # the picture fitted inside the glass
        body, _ = box("phone", bw, bh, 0.008, (0, 0, 0), {}, C.material("phone_body", (0.02, 0.02, 0.025), 0.25, 0.6))
        glass, _ = box("glass", gw, gh, 0.0004, (0, 0, 0.008), {}, C.material("glass_black", (0.0, 0.0, 0.0), 0.05))
        screen, ws = box("screen", sw, sh, 0.0003, (0, 0, 0.0084), {"top": img_mat(img0, "screen_img", gloss=True)} if img0 else {},
                         C.material("glass_black", (0.0, 0.0, 0.0), 0.05))
        glass.parent = body
        screen.parent = body
        body.rotation_euler = (0, 0, math.radians(-14))
        subject = [body, glass, screen]
    else:
        sw = 0.30
        sh = sw / a
        base, _ = box("laptop_base", sw + 0.02, sh + 0.04, 0.012, (0, 0, 0), {}, C.material("aluminium", (0.55, 0.56, 0.58), 0.3, 1.0))
        lid, _ = box("laptop_lid", sw + 0.02, 0.006, sh + 0.02, (0, (sh + 0.04) / 2, 0.012), {}, C.material("aluminium", (0.55, 0.56, 0.58), 0.3, 1.0))
        lid.rotation_euler = (math.radians(-18), 0, 0)
        screen, ws = box("screen", sw, 0.0006, sh, (0, -0.0034, 0.01), {"front": img_mat(img0, "screen_img", gloss=True)} if img0 else {},
                         C.material("glass_black", (0.0, 0.0, 0.0), 0.05))
        screen.parent = lid
        subject = [base, lid, screen]
    faces["picture"] = world_of(screen, ws["top"] if kind == "phone" else [(-sw / 2, -0.0003, 0), (sw / 2, -0.0003, 0), (sw / 2, -0.0003, sh), (-sw / 2, -0.0003, sh)])
elif kind == "mug":
    mug = cylinder("mug", 0.041, 0.096, (0, 0, 0), img_mat(img0, "mug_img", 0.15) if img0 else C.material("mug_white", (0.9, 0.9, 0.9), 0.1))
    bpy.ops.mesh.primitive_torus_add(major_radius=0.028, minor_radius=0.006, location=(0.047, 0, 0.05), rotation=(math.radians(90), 0, 0))
    handle = bpy.context.object
    handle.data.materials.append(C.material("ceramic_in", (0.9, 0.9, 0.9), 0.1))
    handle.parent = mug
    mug.rotation_euler = (0, 0, math.radians(-12))  # the handle on the right, turned a little towards the camera
    subject = [mug, handle]
    r, hh = 0.041, 0.096
    th0, th1 = 2 * math.pi * (0.42 + 0.25), 2 * math.pi * (0.58 + 0.25)  # a nearly flat strip at the picture's middle (u 0.42-0.58)
    faces["picture"] = world_of(mug, [(r * math.cos(th0), r * math.sin(th0), hh * 0.25), (r * math.cos(th1), r * math.sin(th1), hh * 0.25),
                                      (r * math.cos(th1), r * math.sin(th1), hh * 0.75), (r * math.cos(th0), r * math.sin(th0), hh * 0.75)])  # anticlockwise: outward
elif kind == "poster":
    a = aspect(img0) if img0 else 0.7
    ph = 0.7
    pw = ph * a
    frame, _ = box("frame", pw + 0.06, 0.025, ph + 0.06, (0, -0.0125, -0.03), {}, C.material("frame_wood", (0.06, 0.04, 0.03), 0.4))
    art, wa = box("art", pw, 0.002, ph, (0, -0.026, 0), {"front": img_mat(img0, "art_img", 0.5)} if img0 else {}, C.material("paper", (0.9, 0.9, 0.88), 0.8))
    frame.location.z = 1.2 - 0.03
    art.location.z = 1.2
    subject = [frame, art]
    faces["picture"] = world_of(art, wa["front"])

# ---------------------------------------------------------------- the setting
setting = spec.get("setting") or ("desk" if kind in ("card", "phone", "laptop", "mug") else "wall" if kind == "poster" else "studio")
lo, hi, pts = C.bounds(subject)
size_m = max((hi - lo).length, 0.05)
if setting == "wall":
    wall, _ = box("wall", 6, 0.1, 3.2, (0, 0.06, 0), {}, C.material("wall_paint", (0.62, 0.58, 0.52), 0.9))
    floor, _ = box("floor", 6, 4, 0.02, (0, -1.9, -0.02), {}, C.lib_material("wood_floor"))
elif setting == "desk":
    desk, _ = box("desk", size_m * 8, size_m * 6, 0.03, (0, 0, -0.03), {}, C.lib_material("wood_furn"))
else:  # a studio sweep: the floor curving up into the back wall
    bpy.ops.mesh.primitive_plane_add(size=size_m * 12, location=(0, size_m * 2, 0))
    sweep = bpy.context.object
    sweep.data.materials.append(C.material("sweep", (0.72, 0.72, 0.74), 0.7))
C.world((0.55, 0.57, 0.6) if setting != "wall" else (0.5, 0.48, 0.45), 0.5)
key = bpy.data.lights.new("key", "AREA")
key.energy, key.size = 38.0 * size_m * 10, size_m * 2
ko = bpy.data.objects.new("key", key)
scene.collection.objects.link(ko)
C.look(ko, (lo + hi) / 2, (lo + hi) / 2 + Vector((-size_m * 2, -size_m * 2.5, size_m * 3)))
fill = bpy.data.lights.new("fill", "AREA")
fill.energy, fill.size = 12.0 * size_m * 10, size_m * 3
fo = bpy.data.objects.new("fill", fill)
scene.collection.objects.link(fo)
C.look(fo, (lo + hi) / 2, (lo + hi) / 2 + Vector((size_m * 3, -size_m * 2, size_m * 1.5)))
if setting == "desk":
    C.sun(elevation=55, azimuth=-60, strength=1.15, angle=4)

# ---------------------------------------------------------------- the camera and the pictures
C.engine(spec.get("engine", "eevee"), spec.get("w", 1600), spec.get("h", 1200), spec.get("samples", 64))
cam = C.camera("cam", lens=spec.get("lens", 50))
centre = (lo + hi) / 2
az = spec.get("az", {"box": -30, "card": -15, "phone": -10, "laptop": -25, "mug": -20, "poster": -12}[kind])
el = spec.get("el", {"box": 22, "card": 55, "phone": 58, "laptop": 24, "mug": 15, "poster": 5}[kind])
a_, e_ = math.radians(az), math.radians(el)
C.look(cam, centre, centre + Vector((math.sin(a_) * math.cos(e_), -math.cos(a_) * math.cos(e_), math.sin(e_))) * size_m * 4)
fr = C.fit(cam, pts, margin=spec.get("margin", 0.12))
pic = C.framing(cam, faces["picture"]) if faces.get("picture") else None
pic_pts = None
if faces.get("picture"):
    from bpy_extras.object_utils import world_to_camera_view
    pic_pts = [list(world_to_camera_view(scene, cam, p))[:2] for p in faces["picture"]]
facing = None
if faces.get("picture"):
    p0, p1, p2 = faces["picture"][0], faces["picture"][1], faces["picture"][2]
    normal = (p1 - p0).cross(p2 - p1).normalized()
    facing = round(normal.dot((cam.location - (p0 + p2) / 2).normalized()), 3)
result = {"framing": fr, "picture": pic, "picture_quad": pic_pts, "facing": facing, "kind": kind, "setting": setting, "version": bpy.app.version_string,
          "u_range": [0.42, 0.58] if kind == "mug" else [0.0, 1.0], "v_range": [0.25, 0.75] if kind == "mug" else [0.0, 1.0]}
for o in [o for o in scene.objects if o.type == "MESH" and o not in subject and o.parent not in subject]:
    o.hide_render = True
result["mask_s"] = C.mask(spec["mask"], 480)
for o in scene.objects:
    o.hide_render = False
C.engine(spec.get("engine", "eevee"), spec.get("w", 1600), spec.get("h", 1200), spec.get("samples", 64))
result["render_s"] = C.still(spec["still"])
C.write(out_path, result)
