"""3D jobs, from start to checked result.

  house(lay, folder, name, views, ...)   a plan (src/ai_pc/cad) -> measured boxes (house.py) -> Blender (bl/house_scene.py):
                                         3D floor plan, top view, front, aerial, a turn-around video; the 3D model checked
                                         against the plan (a floor for every room, glass in every window, stairs that reach
                                         the next floor, every name placed) and every render checked (checks.py)
  text(params, folder, name)             a 3D title (and logo) that comes in and holds: a video and its last frame
  mockup(params, folder, name)           the person's picture on a box, cards, a laptop, a phone, a mug or a poster
  model(params, folder, name)            someone's 3D file measured, pictured, converted and opened again
Each returns {"outputs": {...}, "checks": [...], "notes": [...], "seconds", "engine", ...}.
"""

import shutil
import time
from pathlib import Path

from ai_pc.three import blender as B
from ai_pc.three import checks as K
from ai_pc.three.house import CLEAR_H, SLAB, house_spec

VIEW_WORDS = {"plan3d": "3D floor plan", "top": "top view", "front": "front view", "aerial": "view from above", "orbit": "turn-around video"}
MOCK_ANGLE = {"box": -30, "card": -15, "phone": -10, "laptop": -25, "mug": -20, "poster": -12}


def _sizes(kind, W, D, big=False):
    k = 1.5 if big else 1.0
    if kind == "top":
        return (int(1000 * k), int(1500 * k)) if D > W * 1.15 else (int(1500 * k), int(1000 * k))
    if kind == "plan3d":
        return (int(1600 * k), int(1200 * k))
    if kind == "orbit":
        return (1280, 720)
    return (int(1920 * k), int(1080 * k))


def _tidy(folder, name, masks=()):
    for f in (f"{name}_spec.json", f"{name}_result.json"):
        (folder / f).unlink(missing_ok=True)
    for m in masks:
        Path(m).unlink(missing_ok=True)


def _video_from(frames_dir, mp4, frames, fps, dark_ok=False):
    try:
        K.encode(frames_dir, mp4, fps)
        shutil.rmtree(frames_dir, ignore_errors=True)
        return K.video(mp4, frames, fps, dark_ok=dark_ok)
    except RuntimeError as ex:
        return [{"what": "video", "ok": False, "level": "fail", "detail": str(ex)}]


def _frames_dir(folder, name):
    fdir = folder / f"{name}_frames"
    shutil.rmtree(fdir, ignore_errors=True)
    fdir.mkdir()
    return fdir


# ---------------------------------------------------------------- houses
def house(
    lay,
    folder,
    name,
    views=("plan3d", "front"),
    style="modern",
    storey="ground",
    furniture=True,
    labels=True,
    quality="normal",
    colors=None,
    log=print,
    seconds=6,
    big=False,
):
    t0 = time.time()
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    W, D = lay["plot"]
    if storey == "first" and not lay.get("upper"):
        storey = "ground"
    spec = house_spec(lay, style=style, view="all", floor=storey, furniture=furniture, labels=labels, colors=colors)
    vs = []
    for kind in views:
        w, h = _sizes(kind, W, D, big)
        v = {"name": kind, "kind": kind, "w": w, "h": h, "path": str(folder / f"{name}_{kind}.png"), "mask": str(folder / f"{name}_{kind}_mask.png")}
        if quality == "high" and kind != "orbit":
            v.update(engine="cycles", samples=128)
        if kind == "orbit":
            v.update(frames=int(seconds * 30), fps=30, frames_dir=str(_frames_dir(folder, name)), samples=16)
        vs.append(v)
    spec.update(views=vs, storey=storey, blend=str(folder / f"{name}.blend"))
    res = B.run("house_scene.py", spec, folder, log=log, name=name)
    outputs, checks = {}, model_checks(spec, lay, res)
    for v in vs:
        e = res["views"].get(v["name"], {})
        if v["kind"] == "orbit":
            mp4 = folder / f"{name}_orbit.mp4"
            checks += _video_from(v["frames_dir"], mp4, v["frames"], v["fps"])
            if mp4.exists():
                outputs["orbit"] = str(mp4)
            checks += [c for c in K.view_checks("turn-around (first frame)", e, v["mask"], v["mask"]) if "whole subject" in c["what"]]
        else:
            checks += K.view_checks(VIEW_WORDS[v["kind"]], e, v["path"], v["mask"], cut_ok=("bottom",) if v["kind"] == "front" else ())
            outputs[v["kind"]] = v["path"]
    _tidy(folder, name, [v["mask"] for v in vs])
    eng = sorted({e.get("engine", "") for e in res["views"].values()})
    return {
        "outputs": outputs,
        "checks": checks,
        "notes": [],
        "seconds": round(time.time() - t0, 1),
        "engine": ", ".join(eng),
        "blend": spec["blend"],
        "storey": storey,
        "render_s": {k: v.get("render_s") for k, v in res["views"].items()},
    }


def model_checks(spec, lay, res):
    """The 3D model against the plan it came from."""
    out = []
    boxes = spec["boxes"]

    def ck(what, ok, detail="", level="fail"):
        out.append({"what": what, "ok": bool(ok), "level": "info" if ok else level, "detail": detail})

    storeys = [("ground", lay)] + ([("first", lay["upper"])] if lay.get("upper") else [])
    for nm, fl in storeys:
        floors = {b["n"] for b in boxes if b["c"] == f"out_{nm}_floors" and "_bath" not in b["n"]}
        ck(f"3D: every room on the {nm} floor has its floor", len(floors) == len(fl["rooms"]), f"{len(floors)} of {len(fl['rooms'])}")
        glass = sum(1 for b in boxes if b["c"] == f"out_{nm}_glass")
        ck(f"3D: glass in every {nm}-floor window", glass == len(fl.get("windows", [])), f"{glass} of {len(fl.get('windows', []))}")
        steps = [b for b in boxes if b["c"] == f"out_{nm}_stairs" and "_step" in b["n"]]
        if steps:
            top = max(b["b"][5] for b in steps) - min(b["b"][2] for b in steps)
            ck(f"3D: the {nm}-floor stairs reach the next floor", abs(top - (CLEAR_H + SLAB)) < 0.5, f"{top / 12:.1f} ft")
    ck("3D: the front door is in", any(b["c"] == "out_ground_doors" for b in boxes))
    want = len(spec.get("labels", []))
    ck("3D: every room's name placed", res.get("labels", 0) == want, f"{res.get('labels', 0)} of {want}", "warn")
    return out


# ---------------------------------------------------------------- 3D titles
def text(p, folder, name, log=print):
    t0 = time.time()
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    big = p.get("big")
    spec = {
        "text": p["text"],
        "sub": p.get("sub"),
        "material": p.get("material", "gold"),
        "background": p.get("background", "dark"),
        "anim": p.get("anim", "dolly"),
        "seconds": float(p.get("seconds", 5)),
        "fps": 30,
        "w": 2560 if big else 1920,
        "h": 1440 if big else 1080,
        "logo": p.get("logo"),
        "frames_dir": str(_frames_dir(folder, name)),
        "still": str(folder / f"{name}_title.png"),
        "mask": str(folder / f"{name}_title_mask.png"),
        "samples": 64 if p.get("quality") == "high" else 24,
    }
    res = B.run("text_scene.py", spec, folder, log=log, name=name)
    mp4 = folder / f"{name}_intro.mp4"
    checks = _video_from(
        spec["frames_dir"],
        mp4,
        res["frames"],
        res["fps"],
        dark_ok=spec["background"] in ("dark", "black", "navy", "blue", "red", "green", "purple", "gradient"),
    )
    checks += [
        c
        for c in K.view_checks("last frame", res, spec["still"], spec["mask"])
        if not (c["what"].endswith("exposure") and spec["background"] != "white")
    ]
    pc = K.picture(spec["still"])
    checks.append(
        {
            "what": "the title is lit",
            "ok": pc["clip_hi"] + pc["std"] > 0.06,
            "level": "info" if pc["clip_hi"] + pc["std"] > 0.06 else "warn",
            "detail": f"contrast {pc['std']:.2f}",
        }
    )
    s = K.silhouette(spec["mask"])
    if s["bbox"]:
        cx, wide = (s["bbox"][0] + s["bbox"][2]) / 2, s["bbox"][2] - s["bbox"][0]
        checks.append(
            {
                "what": "the title is in the middle",
                "ok": abs(cx - 0.5) < 0.08,
                "level": "info" if abs(cx - 0.5) < 0.08 else "warn",
                "detail": f"its centre {cx:.2f} across",
            }
        )
        checks.append(
            {
                "what": "the title is big enough to read",
                "ok": wide > 0.35,
                "level": "info" if wide > 0.35 else "warn",
                "detail": f"{wide:.0%} of the width",
            }
        )
    _tidy(folder, name, [spec["mask"]])
    return {
        "outputs": {"video": str(mp4), "still": spec["still"]},
        "checks": checks,
        "notes": [],
        "seconds": round(time.time() - t0, 1),
        "engine": "EEVEE",
        "font": res.get("font"),
    }


# ---------------------------------------------------------------- mockups
def _region_colour(png, quad):
    """The mean colour, its spread and the share of the frame inside a quad (0-1 frame coordinates, y up)."""
    import numpy as np
    from PIL import Image, ImageDraw

    im = Image.open(png).convert("RGB")
    w, h = im.size
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon([(x * w, (1 - y) * h) for x, y in quad], fill=255)
    a = np.asarray(im).astype(np.float32) / 255
    sel = np.asarray(m) > 0
    if sel.sum() < 50:
        return None, 0.0, 0.0
    px = a[sel]
    return px.mean(axis=0), float(px.std()), float(sel.mean())


def picture_match(render_png, quad, source_png, u_range=(0.0, 1.0), v_range=(0.0, 1.0)):
    """How well the picture's face in the render matches the picture: the face straightened (a perspective warp from
    its four corners) and compared, edges against edges, with the picture and with the picture mirrored.
    -> (match, match_if_mirrored); None when the picture is too plain to tell."""
    import cv2
    import numpy as np

    src = cv2.imread(str(source_png), cv2.IMREAD_GRAYSCALE)
    img = cv2.imread(str(render_png), cv2.IMREAD_GRAYSCALE)
    if src is None or img is None:
        return None
    h0, w0 = src.shape  # the part of the picture the face shows (v runs up, image rows down)
    src = src[
        int(h0 * (1 - v_range[1])) : max(int(h0 * (1 - v_range[1])) + 2, int(h0 * (1 - v_range[0]))),
        int(w0 * u_range[0]) : max(int(w0 * u_range[0]) + 2, int(w0 * u_range[1])),
    ]
    w, h = 192, max(16, int(192 * src.shape[0] / max(src.shape[1], 1)))
    src = cv2.resize(src, (w, h), interpolation=cv2.INTER_AREA)
    H, W = img.shape
    corners = np.float32([(x * W, (1 - y) * H) for x, y in quad])  # bottom-left, bottom-right, top-right, top-left of the picture
    M = cv2.getPerspectiveTransform(corners, np.float32([(0, h - 1), (w - 1, h - 1), (w - 1, 0), (0, 0)]))
    face = cv2.warpPerspective(img, M, (w, h))

    def edges(a):
        a = cv2.GaussianBlur(a.astype(np.float32), (3, 3), 0)
        return np.hypot(cv2.Sobel(a, cv2.CV_32F, 1, 0), cv2.Sobel(a, cv2.CV_32F, 0, 1))

    def ncc(a, b):
        a, b = a - a.mean(), b - b.mean()
        d = float(np.sqrt((a * a).sum() * (b * b).sum()))
        return float((a * b).sum() / d) if d > 1e-6 else 0.0

    es = edges(src)
    if es.std() < 2.0:
        return None
    ef = edges(face)
    return ncc(ef, es), ncc(ef, es[:, ::-1])


def mockup(p, folder, name, log=print):
    """The person's picture on a product, checked: it faces the camera, takes a fair part of the frame, and the colour
    balance seen there is the picture's (light changes brightness, not balance)."""
    import numpy as np
    from PIL import Image

    t0 = time.time()
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    big = p.get("big")
    spec = {
        "kind": p["kind"],
        "images": [str(Path(x).resolve()) for x in p.get("images") or []],
        "size": p.get("size"),
        "still": str(folder / f"{name}_{p['kind']}.png"),
        "mask": str(folder / f"{name}_{p['kind']}_mask.png"),
        "w": 2400 if big else 1600,
        "h": 1800 if big else 1200,
        "engine": "cycles" if p.get("quality") == "high" else "eevee",
        "samples": 128 if p.get("quality") == "high" else 64,
    }
    if p.get("turn"):
        spec["az"] = MOCK_ANGLE[p["kind"]] + p["turn"]
    res = B.run("mockup_scene.py", spec, folder, log=log, name=name)
    checks = [c for c in K.view_checks(f"{p['kind']} mockup", res, spec["still"], spec["mask"]) if not c["what"].endswith("exposure")]
    quad = res.get("picture_quad")
    if spec["images"] and quad:
        facing = res.get("facing") or 0
        checks.append(
            {"what": "the picture faces the camera", "ok": facing > 0.15, "level": "info" if facing > 0.15 else "fail", "detail": f"{facing:.2f}"}
        )
        mean, spread, share = _region_colour(spec["still"], quad)
        if mean is not None:  # the print keeps its own tones: compared with the same part of the picture, not with a fixed range
            lum = float(mean @ np.array([0.2126, 0.7152, 0.0722]))
            ur, vr = res.get("u_range", (0.0, 1.0)), res.get("v_range", (0.0, 1.0))
            sim = np.asarray(Image.open(spec["images"][0]).convert("RGB")).astype(np.float32) / 255
            hh_, ww_ = sim.shape[:2]
            part = sim[
                int(hh_ * (1 - vr[1])) : max(int(hh_ * (1 - vr[1])) + 1, int(hh_ * (1 - vr[0]))),
                int(ww_ * ur[0]) : max(int(ww_ * ur[0]) + 1, int(ww_ * ur[1])),
            ]
            own = float(part.reshape(-1, 3).mean(axis=0) @ np.array([0.2126, 0.7152, 0.0722]))
            fine = abs(lum - own) < 0.22 or (own > 0.85 and lum > 0.75)
            checks.append(
                {
                    "what": "the picture is well lit",
                    "ok": fine,
                    "level": "info" if fine else "warn",
                    "detail": f"brightness {lum:.2f} on it (the picture itself {own:.2f})",
                }
            )
            src = np.asarray(Image.open(spec["images"][0]).convert("RGB").resize((64, 64))).astype(np.float32) / 255
            want = src.reshape(-1, 3).mean(axis=0)
            gap = float(np.abs(mean / max(float(mean.mean()), 1e-3) - want / max(float(want.mean()), 1e-3)).max())
            ok = share >= 0.03 and gap < 0.6 and (spread > 0.02 or float(src.std()) < 0.03)
            checks.append(
                {
                    "what": "the picture shows on it",
                    "ok": ok,
                    "level": "info" if ok else "fail",
                    "detail": f"{share:.0%} of the frame, colour balance off by {gap:.2f}",
                }
            )
        m = picture_match(spec["still"], quad, spec["images"][0], res.get("u_range", (0.0, 1.0)), res.get("v_range", (0.0, 1.0)))
        if m:
            same, mirrored = m
            good = same >= 0.3 and same > mirrored + 0.03
            checks.append(
                {
                    "what": "the picture is the right way round and matches",
                    "ok": good,
                    "level": "info" if good else "fail",
                    "detail": f"match {same:.2f}, mirrored {mirrored:.2f}",
                }
            )
    _tidy(folder, name, [spec["mask"]])
    return {
        "outputs": {p["kind"]: spec["still"]},
        "checks": checks,
        "notes": [],
        "seconds": round(time.time() - t0, 1),
        "engine": "Cycles" if spec["engine"] == "cycles" else "EEVEE",
        "quad": quad,
        "u_range": res.get("u_range"),
        "v_range": res.get("v_range"),
    }


# ---------------------------------------------------------------- 3D files
def model(p, folder, name, log=print):
    t0 = time.time()
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    views = []
    for kind in p.get("views") or ["three_quarter"]:
        v = {
            "name": kind,
            "kind": kind,
            "w": 1600,
            "h": 1200,
            "path": str(folder / f"{name}_{kind}.png"),
            "mask": str(folder / f"{name}_{kind}_mask.png"),
        }
        if kind == "orbit":
            v.update(w=1280, h=960, frames=int(float(p.get("seconds", 5)) * 30), fps=30, frames_dir=str(_frames_dir(folder, name)), samples=24)
        views.append(v)
    spec = {"file": str(Path(p["file"]).resolve()), "views": views if p.get("render", True) else [], "turn": p.get("turn", 0)}
    if p.get("export"):
        spec["export"] = {"fmt": p["export"], "path": str(folder / f"{name}_{Path(p['file']).stem}.{p['export']}")}
    res = B.run("model_scene.py", spec, folder, log=log, name=name, timeout=1200)
    checks, outputs = [], {}
    for v in spec["views"]:
        e = res["views"].get(v["name"], {})
        if v["kind"] == "orbit":
            mp4 = folder / f"{name}_turn.mp4"
            checks += _video_from(v["frames_dir"], mp4, v["frames"], v["fps"])
            outputs["orbit"] = str(mp4)
        else:
            checks += K.view_checks(v["kind"].replace("_", " "), e, v["path"], v["mask"], cut_ok=("bottom",))
            outputs[v["kind"]] = v["path"]
    st = res["stats"]
    if res.get("export"):
        st2 = res["export"]["stats"]
        same = abs(st2["triangles"] - st["triangles"]) <= max(2, st["triangles"] * 0.01)
        ratio = max(st2["size_m"]) / max(max(st["size_m"]), 1e-9)
        checks.append(
            {
                "what": f"saved as {p['export'].upper()} and opened again: same shape",
                "ok": same,
                "level": "info" if same else "fail",
                "detail": f"{st2['triangles']:,} triangles (was {st['triangles']:,})",
            }
        )
        checks.append(
            {
                "what": f"saved as {p['export'].upper()}: same size",
                "ok": 0.98 < ratio < 1.02,
                "level": "info" if 0.98 < ratio < 1.02 else "warn",
                "detail": f"x{ratio:.3g}",
            }
        )
        outputs["export"] = res["export"]["path"]
    _tidy(folder, name, [v["mask"] for v in spec["views"]])
    return {"outputs": outputs, "checks": checks, "stats": st, "notes": [], "seconds": round(time.time() - t0, 1), "engine": "EEVEE"}
