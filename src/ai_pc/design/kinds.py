"""What can be made, at what size, and the palettes and type that dress it.

Sizes: print kinds in millimetres with a 3 mm bleed and a 3 mm safe margin inside the trim (what print shops ask
for); screen kinds in pixels with the margins the apps' own buttons and captions leave free.
"""

KINDS = {
    "card": {
        "label": "visiting card",
        "w": 88.9,
        "h": 50.8,
        "unit": "mm",
        "bleed": 3.0,
        "safe": 3.5,
        "pages": 2,
        "styles": ["modern", "classic", "bold"],
    },
    "post": {"label": "square post", "w": 1080, "h": 1080, "unit": "px", "safe": 60, "styles": ["headline", "photo", "split"]},
    "portrait": {"label": "portrait post", "w": 1080, "h": 1350, "unit": "px", "safe": 70, "styles": ["headline", "photo", "split"]},
    "story": {"label": "story", "w": 1080, "h": 1920, "unit": "px", "safe": 80, "safe_top": 260, "safe_bottom": 360, "styles": ["headline", "photo"]},
    "thumbnail": {"label": "YouTube thumbnail", "w": 1280, "h": 720, "unit": "px", "safe": 40, "safe_br": (300, 110), "styles": ["face", "center"]},
    "flyer": {"label": "flyer", "w": 148.0, "h": 210.0, "unit": "mm", "bleed": 3.0, "safe": 6.0, "pages": 1, "styles": ["sale", "event"]},
    "poster": {"label": "poster", "w": 297.0, "h": 420.0, "unit": "mm", "bleed": 3.0, "safe": 10.0, "pages": 1, "styles": ["sale", "event"]},
    "certificate": {
        "label": "certificate",
        "w": 297.0,
        "h": 210.0,
        "unit": "mm",
        "bleed": 0.0,
        "safe": 10.0,
        "pages": 1,
        "styles": ["classic", "modern"],
    },
    "invitation": {
        "label": "invitation",
        "w": 127.0,
        "h": 177.8,
        "unit": "mm",
        "bleed": 3.0,
        "safe": 6.0,
        "pages": 1,
        "styles": ["elegant", "modern"],
    },
}
SIZES = {"a4": (210.0, 297.0), "a5": (148.0, 210.0), "a3": (297.0, 420.0), "a6": (105.0, 148.0), "letter": (215.9, 279.4)}

PALETTES = {
    "navy": {"bg": "#0F1E3D", "fg": "#FFFFFF", "accent": "#F2B705", "muted": "#AEB9CC", "light": "#F4F6FA", "ink": "#0F1E3D"},
    "emerald": {"bg": "#0B3D2E", "fg": "#F4F1E8", "accent": "#E0B84C", "muted": "#A9C4B9", "light": "#F3F7F4", "ink": "#0B3D2E"},
    "maroon": {"bg": "#5A0F1E", "fg": "#FFF7EE", "accent": "#E8B75C", "muted": "#DDBDB5", "light": "#FBF4F1", "ink": "#5A0F1E"},
    "charcoal": {"bg": "#1E1F24", "fg": "#FFFFFF", "accent": "#FF5A36", "muted": "#A6A9B3", "light": "#F5F5F6", "ink": "#1E1F24"},
    "blue": {"bg": "#1F4FD8", "fg": "#FFFFFF", "accent": "#FFD23F", "muted": "#C9D6FF", "light": "#F2F5FF", "ink": "#13286B"},
    "green": {"bg": "#1E7A46", "fg": "#FFFFFF", "accent": "#FFE066", "muted": "#C3E6D1", "light": "#F1F8F3", "ink": "#12372A"},
    "black": {"bg": "#0A0A0A", "fg": "#F5F5F5", "accent": "#D4AF37", "muted": "#A3A3A3", "light": "#F7F5EF", "ink": "#111111"},
    "purple": {"bg": "#2D1B69", "fg": "#FFFFFF", "accent": "#FFD23F", "muted": "#C7BDF2", "light": "#F5F2FF", "ink": "#2D1B69"},
    "red": {"bg": "#B3102A", "fg": "#FFFFFF", "accent": "#FFD100", "muted": "#FAD7DC", "light": "#FFF3F4", "ink": "#7A0A1C"},
    "orange": {"bg": "#E8590C", "fg": "#FFFFFF", "accent": "#1B1B1B", "muted": "#FFD8C2", "light": "#FFF5EE", "ink": "#7A2E06"},
    "teal": {"bg": "#0E6E6E", "fg": "#FFFFFF", "accent": "#FFB703", "muted": "#B8E0DF", "light": "#F0F8F8", "ink": "#083F3F"},
    "cream": {"bg": "#FBF6EC", "fg": "#2B2118", "accent": "#B8860B", "muted": "#7A6A58", "light": "#FBF6EC", "ink": "#2B2118"},
    "white": {"bg": "#FFFFFF", "fg": "#1B2333", "accent": "#1F6FEB", "muted": "#5B6577", "light": "#FFFFFF", "ink": "#1B2333"},
    "pink": {"bg": "#D6336C", "fg": "#FFFFFF", "accent": "#FFE3EC", "muted": "#FFC9DA", "light": "#FFF0F5", "ink": "#7A1238"},
    "gold": {"bg": "#1A1A1A", "fg": "#FFFFFF", "accent": "#E6B422", "muted": "#BFBFBF", "light": "#FAF6EA", "ink": "#1A1A1A"},
}
GRADIENTS = {
    "sunset": ("#FF5F6D", "#FFC371"),
    "ocean": ("#1D6FA3", "#58C6E8"),
    "night": ("#141E30", "#243B55"),
    "royal": ("#2D1B69", "#7B2FF7"),
    "fire": ("#C31432", "#F37335"),
    "forest": ("#0B3D2E", "#2E8B57"),
    "gold": ("#8E6E1E", "#E6B422"),
}
COLOR_WORDS = {
    "navy": "navy",
    "dark blue": "navy",
    "blue": "blue",
    "green": "green",
    "dark green": "emerald",
    "emerald": "emerald",
    "maroon": "maroon",
    "red": "red",
    "black": "black",
    "dark": "charcoal",
    "grey": "charcoal",
    "gray": "charcoal",
    "charcoal": "charcoal",
    "purple": "purple",
    "orange": "orange",
    "teal": "teal",
    "cream": "cream",
    "beige": "cream",
    "white": "white",
    "pink": "pink",
    "gold": "gold",
    "golden": "gold",
}

# type pairs from the fonts every Windows PC has (no downloads): heading, body, and a script for names on certificates
FONTS = {
    "modern": ("Bahnschrift", "Segoe UI"),
    "classic": ("Bodoni MT", "Palatino Linotype"),
    "bold": ("Segoe UI Black", "Segoe UI"),
    "elegant": ("Bodoni MT", "Georgia"),
    "headline": ("Segoe UI Black", "Segoe UI"),
    "photo": ("Bahnschrift", "Segoe UI"),
    "split": ("Rockwell", "Segoe UI"),
    "face": ("Impact", "Segoe UI"),
    "center": ("Segoe UI Black", "Segoe UI"),
    "sale": ("Segoe UI Black", "Segoe UI"),
    "event": ("Bahnschrift", "Segoe UI"),
}
SCRIPT_FONT = "Segoe Script"
DEFAULT_PALETTE = {
    "card": "navy",
    "post": "blue",
    "portrait": "blue",
    "story": "purple",
    "thumbnail": "red",
    "flyer": "red",
    "poster": "red",
    "certificate": "navy",
    "invitation": "cream",
}


def size_of(spec):
    """(w, h, unit, bleed, safe) for a spec, with a paper size or orientation asked for."""
    k = KINDS[spec["kind"]]
    w, h = k["w"], k["h"]
    if spec.get("paper") in SIZES and k["unit"] == "mm":
        w, h = SIZES[spec["paper"]]
        if spec["kind"] == "certificate":
            w, h = max(w, h), min(w, h)
    if spec.get("orientation") == "landscape" and h > w or spec.get("orientation") == "portrait" and w > h:
        w, h = h, w
    return w, h, k["unit"], k.get("bleed", 0.0), k["safe"]


def _lum(hexc):
    h = hexc.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _darken(hexc, k=0.45):
    h = hexc.lstrip("#")
    return "#" + "".join(f"{int(int(h[i : i + 2], 16) * (1 - k)):02X}" for i in (0, 2, 4))


def palette(spec):
    p = dict(PALETTES.get(spec.get("palette") or DEFAULT_PALETTE[spec["kind"]], PALETTES["navy"]))
    g = spec.get("gradient")
    if g in GRADIENTS:  # words on a gradient take their colour from how light it is (white on a pale sunset cannot be read)
        a, b = GRADIENTS[g]
        ground = a if _lum(a) > _lum(b) else b  # the lighter end decides
        if _contrast(p["fg"], ground) < 4.5:
            p.update(fg="#1C1A22", muted="#3D3946")
        t = p["accent"]
        while _contrast(t, ground) < 4.5 and _lum(t) > 0.01:  # accent-coloured words get as much darker as the ground needs;
            t = _darken(t, 0.2)  # badges and buttons keep the accent itself
        p["accent_text"] = t
    p.update({k: v for k, v in (spec.get("colors") or {}).items() if v})
    return p
