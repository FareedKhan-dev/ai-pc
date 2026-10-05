"""After Effects by its two code routes: a title animation (a bar sweeps in, the title scales and fades in, the subtitle
rises in) written as a Lottie file (the Bodymovin format After Effects exports; websites, apps and Lottie players play
it) with a preview page, and an After Effects script (.jsx: File > Scripts > Run Script File) that builds the same
composition with keyframes inside After Effects. Checked by playing the Lottie file in headless Chrome with lottie-web
(the first frame shows no title, the last frame does) and by parsing the script with Node.

  "after effects title: 'Eid Sale' subtitle 'Up to 50% off' blue background, 4 seconds"
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "aftereffects", "After Effects: title animations (Lottie + .jsx script)"
EXAMPLES = ["after effects title: 'Eid Sale' subtitle 'Up to 50% off' blue background, 4 seconds"]
LOTTIE_JS = ROOT / "tools" / "js" / "lottie.min.js"
COLORS = {"blue": (0.09, 0.32, 0.62), "black": (0.07, 0.07, 0.09), "red": (0.72, 0.11, 0.11), "green": (0.11, 0.45, 0.24), "purple": (0.35, 0.16, 0.55),
          "white": (1, 1, 1), "gold": (1, 0.76, 0.03), "yellow": (0.99, 0.85, 0.21), "orange": (0.98, 0.55, 0.0), "pink": (0.85, 0.11, 0.38), "grey": (0.4, 0.4, 0.42)}


def _static(v):
    return {"a": 0, "k": v}


def _anim(*keys):
    """keys: (frame, value); eased."""
    out = []
    for i, (t, v) in enumerate(keys):
        k = {"t": t, "s": v if isinstance(v, list) else [v]}
        if i < len(keys) - 1:
            n = len(k["s"])
            k.update(i={"x": [0.2] * n, "y": [1] * n}, o={"x": [0.4] * n, "y": [0] * n})
        out.append(k)
    return {"a": 1, "k": out}


def _ks(p, o=None, s=None):
    return {"o": o or _static(100), "r": _static(0), "p": p, "a": _static([0, 0, 0]), "s": s or _static([100, 100, 100])}


def _text(idx, name, text, size, color, frames, p, o, s=None):
    return {"ddd": 0, "ind": idx, "ty": 5, "nm": name, "sr": 1, "ks": _ks(p, o, s), "ao": 0, "ip": 0, "op": frames, "st": 0, "bm": 0,
            "t": {"d": {"k": [{"s": {"s": size, "f": "Arial-Bold", "t": text, "j": 2, "tr": 0, "lh": size * 1.2, "ls": 0, "fc": list(color)}, "t": 0}]},
                  "p": {}, "m": {"g": 1, "a": _static([0, 0])}, "a": []}}


def lottie(title, subtitle="", bg="blue", seconds=4, fps=30, size=(1920, 1080), accent="gold"):
    w, h = size
    frames = int(seconds * fps)
    tc = (1, 1, 1) if bg not in ("white", "yellow", "gold") else (0.07, 0.07, 0.09)
    title_size = max(40, min(180, int(w * 0.9 / max(4, len(title)) * 1.6)))
    layers = [_text(1, "Title", title, title_size, tc, frames, _static([w / 2, h * 0.5, 0]), _anim((8, 0), (28, 100)), _anim((8, [80, 80, 100]), (28, [100, 100, 100])))]
    if subtitle:
        layers.append(_text(2, "Subtitle", subtitle, int(title_size * 0.42), COLORS.get(accent, COLORS["gold"]), frames,
                            _anim((22, [w / 2, h * 0.68, 0]), (42, [w / 2, h * 0.64, 0])), _anim((22, 0), (42, 100))))
    bar = {"ddd": 0, "ind": 3, "ty": 4, "nm": "Accent bar", "sr": 1, "ks": _ks(_static([w / 2, h * 0.56, 0]), None, _anim((0, [0, 100, 100]), (20, [100, 100, 100]))),
           "ao": 0, "ip": 0, "op": frames, "st": 0, "bm": 0,
           "shapes": [{"ty": "gr", "nm": "Bar", "it": [{"ty": "rc", "nm": "Rect", "s": _static([w * 0.5, h * 0.012]), "p": _static([0, 0]), "r": _static(6)},
                                                      {"ty": "fl", "nm": "Fill", "c": _static(list(COLORS.get(accent, COLORS["gold"])) + [1]), "o": _static(100), "r": 1},
                                                      {"ty": "tr", "p": _static([0, 0]), "a": _static([0, 0]), "s": _static([100, 100]), "r": _static(0), "o": _static(100)}]}]}
    r, g, b = COLORS.get(bg, COLORS["blue"])
    solid = {"ddd": 0, "ind": 4, "ty": 1, "nm": "Background", "sr": 1, "ks": _ks(_static([w / 2, h / 2, 0])), "ao": 0, "ip": 0, "op": frames, "st": 0, "bm": 0,
             "sw": w, "sh": h, "sc": "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))}
    solid["ks"]["a"] = _static([w / 2, h / 2, 0])
    return {"v": "5.12.0", "fr": fps, "ip": 0, "op": frames, "w": w, "h": h, "nm": title, "ddd": 0, "assets": [],
            "fonts": {"list": [{"fName": "Arial-Bold", "fFamily": "Arial", "fStyle": "Bold", "ascent": 71.6}]}, "layers": layers + [bar, solid]}


def jsx(title, subtitle="", bg="blue", seconds=4, fps=30, size=(1920, 1080), accent="gold"):
    w, h = size
    r, g, b = COLORS.get(bg, COLORS["blue"])
    ar, ag, ab = COLORS.get(accent, COLORS["gold"])
    tc = "[1, 1, 1]" if bg not in ("white", "yellow", "gold") else "[0.07, 0.07, 0.09]"
    q = json.dumps
    sub = ""
    if subtitle:
        sub = f"""
    var s = comp.layers.addText({q(subtitle)});
    var sd = s.property("ADBE Text Properties").property("ADBE Text Document");
    var st = sd.value; st.fontSize = 60; st.fillColor = [{ar}, {ag}, {ab}]; st.font = "Arial-BoldMT"; st.justification = ParagraphJustification.CENTER_JUSTIFY; sd.setValue(st);
    var sp = s.property("ADBE Transform Group").property("ADBE Position");
    sp.setValueAtTime(22 / fps, [{w / 2}, {h * 0.68}]); sp.setValueAtTime(42 / fps, [{w / 2}, {h * 0.64}]);
    var so = s.property("ADBE Transform Group").property("ADBE Opacity");
    so.setValueAtTime(22 / fps, 0); so.setValueAtTime(42 / fps, 100);"""
    return f"""// Made by AI PC: File > Scripts > Run Script File... in After Effects builds this title as a composition.
(function () {{
    var fps = {fps};
    app.beginUndoGroup("AI PC title");
    var comp = app.project.items.addComp({q(title)}, {w}, {h}, 1, {seconds}, fps);
    comp.layers.addSolid([{r}, {g}, {b}], "Background", {w}, {h}, 1);
    var bar = comp.layers.addShape();
    bar.name = "Accent bar";
    var group = bar.property("ADBE Root Vectors Group").addProperty("ADBE Vector Group");
    var rect = group.property("ADBE Vectors Group").addProperty("ADBE Vector Shape - Rect");
    rect.property("ADBE Vector Rect Size").setValue([{w * 0.5}, {h * 0.012}]);
    var fill = group.property("ADBE Vectors Group").addProperty("ADBE Vector Graphic - Fill");
    fill.property("ADBE Vector Fill Color").setValue([{ar}, {ag}, {ab}]);
    bar.property("ADBE Transform Group").property("ADBE Position").setValue([{w / 2}, {h * 0.56}]);
    var bs = bar.property("ADBE Transform Group").property("ADBE Scale");
    bs.setValueAtTime(0, [0, 100]); bs.setValueAtTime(20 / fps, [100, 100]);
    var t = comp.layers.addText({q(title)});
    var td = t.property("ADBE Text Properties").property("ADBE Text Document");
    var tv = td.value; tv.fontSize = 150; tv.fillColor = {tc}; tv.font = "Arial-BoldMT"; tv.justification = ParagraphJustification.CENTER_JUSTIFY; td.setValue(tv);
    t.property("ADBE Transform Group").property("ADBE Position").setValue([{w / 2}, {h * 0.5}]);
    var to = t.property("ADBE Transform Group").property("ADBE Opacity");
    to.setValueAtTime(8 / fps, 0); to.setValueAtTime(28 / fps, 100);
    var ts = t.property("ADBE Transform Group").property("ADBE Scale");
    ts.setValueAtTime(8 / fps, [80, 80]); ts.setValueAtTime(28 / fps, [100, 100]);{sub}
    comp.openInViewer();
    app.endUndoGroup();
}})();
"""


def make(title, out, subtitle="", bg="blue", seconds=4, accent="gold"):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", title)[:40] or "title"
    data = lottie(title, subtitle, bg, seconds, accent=accent)
    (out / f"{stem}.json").write_text(json.dumps(data), encoding="utf-8")
    (out / f"{stem}.jsx").write_text(jsx(title, subtitle, bg, seconds, accent=accent), encoding="utf-8")
    shutil.copyfile(LOTTIE_JS, out / "lottie.min.js")
    page = out / f"{stem}.preview.html"
    page.write_text("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;background:#000}#a{width:100vw;height:100vh}</style>"
                    "<script src='lottie.min.js'></script></head><body><div id='a'></div><script>"
                    f"var anim=lottie.loadAnimation({{container:document.getElementById('a'),renderer:'svg',loop:true,autoplay:!location.hash,animationData:{json.dumps(data)}}});"
                    "if(location.hash){anim.addEventListener('DOMLoaded',function(){anim.goToAndStop(parseInt(location.hash.slice(1)),true);});}"
                    "</script></body></html>", encoding="utf-8")
    return data, {"lottie": out / f"{stem}.json", "jsx": out / f"{stem}.jsx", "preview": page}


def check(data, files):
    from PIL import Image, ImageChops, ImageStat
    from .. import headless
    shots = []
    for f in (0, data["op"] - 1):
        p = files["preview"].with_name(files["preview"].stem + f".f{f}.png")
        headless.png(files["preview"].resolve().as_uri() + f"#{f}", p, size=(960, 540), wait_ms=1500, lane="apps")
        shots.append(Image.open(p).convert("RGB"))
    mid = lambda im: im.crop((im.width // 4, int(im.height * 0.38), im.width * 3 // 4, int(im.height * 0.58)))  # noqa: E731
    first, last = (ImageStat.Stat(mid(s).convert("L")).stddev[0] for s in shots)
    out = [("lottie-web plays it: no title on the first frame, the title on the last", first < 3 and last > 15)]
    out.append(("the animation moves (the first and last frames differ)", ImageChops.difference(*shots).getbbox() is not None))
    node = shutil.which("node")
    if node:  # Node parses ExtendScript's JavaScript; it only takes .js names
        tmp = files["jsx"].with_suffix(".check.js")
        shutil.copyfile(files["jsx"], tmp)
        r = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tmp.unlink(missing_ok=True)
        out.append(("the After Effects script parses", r.returncode == 0))
    return out


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bafter ?effects\b|\blottie\b|\bbodymovin\b", c):
        return None
    t = re.search(r"\btitle\s*:?\s*['\"]([^'\"]+)['\"]", text, re.I) or re.search(r"['\"]([^'\"]+)['\"]", text)
    if not t:
        return None
    s = re.search(r"\bsubtitle\s*:?\s*['\"]([^'\"]+)['\"]", text, re.I)
    bg = re.search(r"\b(" + "|".join(COLORS) + r")\s+background\b|\bbackground\s+(" + "|".join(COLORS) + r")\b", c)
    secs = re.search(r"\b(\d{1,2}(?:\.\d)?)\s*(?:seconds?|secs?|s)\b", c)
    return {"op": "title", "title": t.group(1), "subtitle": s.group(1) if s else "", "bg": (bg.group(1) or bg.group(2)) if bg else "blue",
            "seconds": float(secs.group(1)) if secs else 4}


def run(op, ctx):
    data, files = make(op["title"], Path(ctx["out"]) / "aftereffects", op.get("subtitle", ""), op.get("bg", "blue"), op.get("seconds", 4))
    checks = check(data, files)
    bad = [w for w, ok in checks if not ok]
    return (f"Title animation '{op['title']}' ({op.get('seconds', 4):g} s at 30 fps): Lottie {files['lottie']} (websites and apps play it; preview "
            f"{files['preview'].name}), After Effects script {files['jsx'].name} (File > Scripts > Run Script File builds the composition). " +
            ("Checked: " + "; ".join(w for w, _ in checks) if not bad else "NOT right: " + "; ".join(bad)) + ".")
