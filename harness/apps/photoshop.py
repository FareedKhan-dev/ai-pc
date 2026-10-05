"""Photoshop by its own file format: layered PSD files written by code (each part of a design is a separate, named,
movable layer with transparency, plus the flattened picture Photoshop shows at once), opened by Photoshop, GIMP,
Photopea, Affinity and Krita. A poster or post is put together from a background picture, a logo and text lines;
any pictures can also be stacked as layers. Checked by reading the PSD back with Pillow's own PSD reader: the layer
names, their places and the flattened picture.

  "photoshop file 1080x1080: background shop.jpg; logo logo.png top-left; title 'Eid Sale' white; subtitle '20% off everything' yellow"
  'psd with layers bg.png, product.png, badge.png'
"""
import re
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NAME, LABEL = "photoshop", "Photoshop: layered PSD files (posters, posts, stacked pictures)"
EXAMPLES = ["photoshop file 1080x1080: background shop.jpg; logo logo.png top-left; title 'Eid Sale' white; subtitle '20% off' yellow",
            "psd with layers bg.png, product.png, badge.png"]
COLORS = {"white": (255, 255, 255), "black": (0, 0, 0), "red": (229, 57, 53), "yellow": (253, 216, 53), "gold": (255, 193, 7), "green": (67, 160, 71),
          "blue": (30, 136, 229), "orange": (251, 140, 0), "pink": (216, 27, 96), "purple": (142, 36, 170), "grey": (158, 158, 158)}


def _pascal(name):
    b = name.encode("latin-1", "replace")[:255]
    s = bytes([len(b)]) + b
    return s + b"\0" * (-len(s) % 4)


def _unicode_block(name):
    data = struct.pack(">I", len(name)) + name.encode("utf-16-be")
    data += b"\0" * (len(data) % 2)
    return b"8BIM" + b"luni" + struct.pack(">I", len(data)) + data


def write_psd(path, size, layers):
    """layers: [(name, RGBA image, (left, top))], bottom first. Writes an 8-bit RGB PSD with the flattened picture."""
    w, h = size
    canvas = Image.new("RGBA", size, (255, 255, 255, 255))
    records, channel_data = b"", b""
    for name, im, (left, top) in layers:
        im = im.convert("RGBA")
        canvas.alpha_composite(im, (max(0, left), max(0, top)), (max(0, -left), max(0, -top)))
        lw, lh = im.size
        r, g, b, a = im.split()
        chans = [(-1, a), (0, r), (1, g), (2, b)]
        rec = struct.pack(">iiiiH", top, left, top + lh, left + lw, 4)
        for cid, _ in chans:
            rec += struct.pack(">hI", cid, 2 + lw * lh)
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + _pascal(name) + _unicode_block(name)
        rec += b"8BIMnorm" + bytes([255, 0, 0, 0]) + struct.pack(">I", len(extra)) + extra
        records += rec
        for _, ch in chans:
            channel_data += struct.pack(">H", 0) + ch.tobytes()
    info = struct.pack(">h", len(layers)) + records + channel_data
    info += b"\0" * (len(info) % 2)
    layer_info = struct.pack(">I", len(info)) + info
    lmi = layer_info + struct.pack(">I", 0)
    flat = canvas.convert("RGB")
    data = b"8BPS" + struct.pack(">H6sHIIHH", 1, b"\0" * 6, 3, h, w, 8, 3)
    data += struct.pack(">I", 0) + struct.pack(">I", 0) + struct.pack(">I", len(lmi)) + lmi
    data += struct.pack(">H", 0) + b"".join(c.tobytes() for c in flat.split())
    Path(path).write_bytes(data)
    return flat


def _font(size, bold=True):
    for f in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_layer(text, size, color, max_w):
    f = _font(size)
    while f.getlength(text) > max_w and size > 12:
        size -= 2
        f = _font(size)
    box = f.getbbox(text)
    im = Image.new("RGBA", (box[2] + 12, box[3] + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((6, 6), text, font=f, fill=color + (255,), stroke_width=max(1, size // 30), stroke_fill=(0, 0, 0, 160))
    return im


def cover(im, size):
    im = im.convert("RGBA")
    k = max(size[0] / im.width, size[1] / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    x, y = (im.width - size[0]) // 2, (im.height - size[1]) // 2
    return im.crop((x, y, x + size[0], y + size[1]))


def poster(size, background=None, logo=None, logo_at="top-left", texts=()):
    w, h = size
    layers = [("Background", cover(Image.open(background), size) if background else Image.new("RGBA", size, (33, 33, 33, 255)), (0, 0))]
    if logo:
        lg = Image.open(logo).convert("RGBA")
        k = min(w * 0.22 / lg.width, h * 0.22 / lg.height)
        lg = lg.resize((max(1, round(lg.width * k)), max(1, round(lg.height * k))), Image.LANCZOS)
        m = round(w * 0.04)
        x = m if "left" in logo_at else w - lg.width - m if "right" in logo_at else (w - lg.width) // 2
        y = m if "top" in logo_at else h - lg.height - m
        layers.append(("Logo", lg, (x, y)))
    y = round(h * 0.55)
    for i, (label, text, color) in enumerate(texts):
        im = text_layer(text, round(h * (0.11 if i == 0 else 0.055)), color, w * 0.9)
        layers.append((label, im, ((w - im.width) // 2, y)))
        y += im.height + round(h * 0.02)
    return layers


def check(path, layers, flat):
    """Read back with Pillow's PSD reader: the layer names and places, and the flattened picture."""
    im = Image.open(path)
    names = [x[0] for x in im.layers]
    boxes = [x[2] for x in im.layers]
    want = [(left, top, left + l.width, top + l.height) for _, l, (left, top) in layers]
    same = list(im.convert("RGB").getdata()) == list(flat.getdata())
    return [("Pillow reads every layer by name, in its place", names == [n for n, _, _ in layers] and [tuple(b) for b in boxes] == want),
            ("the flattened picture is the layers stacked", same)]


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bphotoshop\b|\bpsd\b", c):
        return None
    m = re.search(r"\b(\d{3,5})\s*[x×]\s*(\d{3,5})\b", c)
    size = (int(m.group(1)), int(m.group(2))) if m else (1080, 1080)
    m = re.search(r"\blayers?\s+(.+)$", text, re.I)
    if m and "background" not in c:
        files = [find_file(p.strip(), ctx, {".png", ".jpg", ".jpeg", ".webp"}) for p in re.split(r",|\band\b", m.group(1)) if p.strip()]
        files = [f for f in files if f]
        if files:
            return {"op": "stack", "files": files}
    bg = re.search(r"\bbackground\s+(\S+\.(?:jpe?g|png|webp))", text, re.I)
    lg = re.search(r"\blogo\s+(\S+\.(?:png|jpe?g|webp))(?:\s+(?:at\s+)?((?:top|bottom)-?(?:left|right)?|center))?", text, re.I)
    texts = []
    for label in ("title", "subtitle", "text", "tagline"):
        mm = re.search(rf"\b{label}\s+['\"]([^'\"]+)['\"](?:\s+(?:in\s+)?({'|'.join(COLORS)}))?", text, re.I)
        if mm:
            texts.append((label.title(), mm.group(1), COLORS[(mm.group(2) or ("white" if label == "title" else "yellow")).lower()]))
    if not (bg or lg or texts):
        return None
    return {"op": "poster", "size": size, "background": find_file(bg.group(1), ctx) if bg else None, "logo": find_file(lg.group(1), ctx) if lg else None,
            "logo_at": (lg.group(2) or "top-left").lower() if lg else "top-left", "texts": texts}


def run(op, ctx):
    out = Path(ctx["out"]) / "psd"
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "stack":
        ims = [Image.open(f).convert("RGBA") for f in op["files"]]
        size = (max(i.width for i in ims), max(i.height for i in ims))
        layers = [(Path(f).stem, i, ((size[0] - i.width) // 2, (size[1] - i.height) // 2)) for f, i in zip(op["files"], ims)]
        dest = out / "layers.psd"
    else:
        layers = poster(op["size"], op.get("background"), op.get("logo"), op.get("logo_at", "top-left"), op.get("texts", []))
        size = op["size"]
        dest = out / ((re.sub(r"[^\w-]+", "_", op["texts"][0][1]) if op.get("texts") else "poster") + ".psd")
    flat = write_psd(dest, size, layers)
    flat.save(dest.with_suffix(".png"))
    checks = check(dest, layers, flat)
    bad = [w for w, ok in checks if not ok]
    return (f"PSD with {len(layers)} layers ({', '.join(n for n, _, _ in layers)}), {size[0]}x{size[1]}: {dest} (and a PNG preview). Opens in Photoshop, GIMP, Photopea "
            "and Affinity with every layer movable. " + ("Checked: " + "; ".join(w for w, _ in checks) if not bad else "NOT right: " + "; ".join(bad)) + ".")
