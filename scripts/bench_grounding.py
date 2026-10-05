"""Side-by-side grounding test on real CapCut screenshots: Vocaela-2-500M-1024R2 (GGUF, llama.cpp) vs TinyClick.

  .venv\\Scripts\\python.exe ground_compare.py            # Vocaela on the Arc GPU (Vulkan) + TinyClick
  .venv\\Scripts\\python.exe ground_compare.py --cpu      # Vocaela on the CPU instead

A query is a HIT when the predicted click point lands inside the hand-measured box of the right element.
Everything (llama.cpp build, GGUF weights, demo prompt) lives inside this project folder.
"""

import ast
import base64
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from ai_pc.desktop.grounder import Grounder  # noqa: E402

LLAMA = os.path.join(ROOT, "tools", "llama.cpp", "llama-server.exe")
MODEL_DIR = os.path.join(ROOT, "models", "vocaela")
GGUF = os.path.join(MODEL_DIR, "Vocaela-2-500M-1024R2-Q8_0.gguf")
MMPROJ = os.path.join(MODEL_DIR, "mmproj-Vocaela-2-500M-1024R2-Q8_0.gguf")
DEMO = os.path.join(MODEL_DIR, "screenshot_play.py")
DEMO_URL = "https://raw.githubusercontent.com/vocaela/vocaela-500m-demo/main/screenshot_play.py"
PORT = 8091

# (instruction, true box x0,y0,x1,y1 in image pixels, measured on a zoomed grid)
HOME = (
    "shots/state4.png",
    [  # CapCut home page, 1920x1140 (same 12 queries TinyClick scored 9/12 on earlier)
        ("click the Create project button", (300, 55, 1845, 235)),
        ("click Sign in", (37, 62, 233, 106)),
        ("click Join Pro", (37, 115, 233, 145)),
        ("click Home in the sidebar", (25, 187, 245, 227)),
        ("click Templates in the sidebar", (25, 240, 245, 285)),
        ("click Video Studio in the sidebar", (25, 370, 245, 414)),
        ("click Library in the sidebar", (25, 722, 245, 762)),
        ("click the search icon", (1531, 853, 1560, 881)),
        ("click Trash", (1631, 853, 1710, 881)),
        ("click Project sync", (1721, 853, 1845, 881)),
        ("click the settings gear icon at the top right", (1722, 17, 1752, 47)),
        ("click the 0921 project", (306, 903, 461, 1057)),
    ],
)
EDITOR = (
    "runs/20261001-125345_open-capcut-add-the-video-qwen/shot_7.jpg",
    [  # editor with the Import menu open, 1280x760
        ("click the Import button in the media panel", (192, 170, 262, 194)),
        ("click From device", (152, 200, 298, 222)),
        ("click From library", (152, 223, 298, 245)),
        ("click Import in the left sidebar", (14, 77, 100, 97)),
        ("click the Export button", (1125, 5, 1182, 24)),
        ("click the Share button", (1067, 5, 1120, 24)),
        ("click the Effects tab", (174, 33, 208, 62)),
        ("click the Captions tab", (263, 33, 302, 62)),
        ("click the Text tab", (95, 33, 124, 62)),
        ("click the Menu button", (70, 5, 117, 24)),
        ("click the play button", (643, 391, 664, 411)),
        ("click the undo button", (102, 428, 122, 448)),
        ("click the delete icon in the timeline toolbar", (252, 428, 273, 448)),
        ("click the zoom in icon in the timeline toolbar", (1249, 428, 1269, 448)),
        ("click the Modify button", (1202, 395, 1263, 413)),
        ("click Record", (266, 343, 334, 410)),
        ("click AI avatars", (192, 343, 260, 410)),
        ("click the microphone icon", (905, 428, 923, 448)),
    ],
)


def system_message():
    """The exact computer-use system message the model was trained with, taken from the authors' demo script."""
    if not os.path.exists(DEMO):
        urllib.request.urlretrieve(DEMO_URL, DEMO)
    tree = ast.parse(open(DEMO, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "Vocaela_2_Computer_Use_System_Message":
            return ast.literal_eval(node.value)
    raise RuntimeError("system message not found in demo script")


MARKER = "<__media__>"  # replaced by the server's own (randomised) marker from /props


def prompt(sys_msg, instruction):
    # chat_template.jinja of the model, rendered by hand (llama.cpp can't render it); <image> -> llama.cpp media marker
    return f"<|im_start|>System: {sys_msg}<end_of_utterance>\nUser:{MARKER}{instruction}<end_of_utterance>\nAssistant:<|reserved_special_token_50|>"


def post(path, payload, timeout=300):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def start_server(cpu):
    args = [
        LLAMA,
        "-m",
        GGUF,
        "--mmproj",
        MMPROJ,
        "--port",
        str(PORT),
        "-c",
        "8192",
        "-t",
        "8",
        "-np",
        "1",
        "-ngl",
        "0" if cpu else "99",
        "--no-webui",
    ]  # one slot: every query on a screenshot reuses its cached image
    if cpu:
        args += ["--no-mmproj-offload"]
    log = open(os.path.join(ROOT, "runs", "llama_server.log"), "wb")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, creationflags=0x08000000)  # no console window
    global MARKER
    for _ in range(240):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                if json.loads(r.read()).get("status") == "ok":
                    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/props", timeout=5) as p:
                        MARKER = json.loads(p.read()).get("media_marker") or MARKER
                    return proc
        except Exception:
            pass
        if proc.poll() is not None:
            raise RuntimeError("llama-server exited; see runs/llama_server.log")
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("llama-server did not become healthy")


def vocaela_point(sys_msg, b64, w, h, instruction):
    payload = {
        "prompt": {"prompt_string": prompt(sys_msg, instruction[0].upper() + instruction[1:]), "multimodal_data": [b64]},
        "temperature": 0.0,
        "n_predict": 64,
        "stop": ["</Action>"],
        "cache_prompt": True,
    }
    t = time.perf_counter()
    r = post("/completion", payload)
    ms = (time.perf_counter() - t) * 1000
    text = r.get("content", "")
    pt = None
    m = re.search(r"\[\s*\{.*\}\s*\]", text, re.S)
    try:
        acts = json.loads(m.group(0)) if m else []
        for a in acts:
            if isinstance(a, dict) and a.get("coordinate"):
                x, y = a["coordinate"][:2]
                pt = (round(float(x) * w), round(float(y) * h))
                break
    except (ValueError, TypeError):
        pass
    tm = r.get("timings", {})
    return pt, ms, text.strip()[:90], tm.get("prompt_n"), tm.get("prompt_ms")


def inside(pt, box):
    return bool(pt) and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def main():
    cpu = "--cpu" in sys.argv
    sys_msg = system_message()
    print(f"starting llama-server ({'CPU' if cpu else 'Arc 140T GPU via Vulkan'}) ...", flush=True)
    t0 = time.time()
    proc = start_server(cpu)
    print(f"  ready in {time.time() - t0:.1f} s", flush=True)
    g = Grounder()
    have_tc = "--no-tc" not in sys.argv
    try:
        have_tc and g.ensure()
    except Exception as e:  # noqa: BLE001
        have_tc = False
        print(f"  TinyClick server unavailable ({e}); running Vocaela only")
    totals = {"voc": 0, "tc": 0, "n": 0}
    lat = {"voc_first": [], "voc_next": [], "tc_first": [], "tc_next": []}
    try:
        for path, queries in (HOME, EDITOR):
            img = Image.open(os.path.join(ROOT, path)).convert("RGB")
            w, h = img.size
            buf = io.BytesIO()
            img.save(buf, "PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            overlay = img.copy()
            d = ImageDraw.Draw(overlay)
            print(f"\n== {path} ({w}x{h})")
            print(f"   {'query':48s} {'Vocaela':>22s}  {'TinyClick':>22s}")
            for i, (cmd, box) in enumerate(queries):
                vpt, vms, vraw, pn, pms = vocaela_point(sys_msg, b64, w, h, cmd)
                vhit = inside(vpt, box)
                lat["voc_first" if i == 0 else "voc_next"].append(vms)
                tpt, thit, tms = None, False, 0.0
                if have_tc:
                    try:
                        r = g.ground(img, cmd)
                        tpt, tms = r["point"], r["ms"]
                        thit = inside(tpt, box)
                    except Exception as e:  # noqa: BLE001
                        tpt = f"err {e}"[:20]
                    lat["tc_first" if i == 0 else "tc_next"].append(tms)
                totals["voc"] += vhit
                totals["tc"] += thit
                totals["n"] += 1
                print(
                    f"   {cmd[:48]:48s} {('HIT ' if vhit else 'MISS') + ' ' + str(vpt):>16s} {vms:5.0f}ms"
                    f"  {('HIT ' if thit else 'MISS') + ' ' + str(tpt):>16s} {tms:5.0f}ms",
                    flush=True,
                )
                if not vpt:
                    print(f"      vocaela raw: {vraw!r}")
                if i == 0:
                    print(f"      (new screenshot: {pn} prompt tokens processed in {pms or 0:.0f} ms)")
                d.rectangle(box, outline=(0, 200, 0), width=2)
                for pt, col in ((vpt, (255, 60, 60)), (tpt if isinstance(tpt, tuple) else None, (60, 140, 255))):
                    if pt:
                        d.ellipse((pt[0] - 7, pt[1] - 7, pt[0] + 7, pt[1] + 7), outline=col, width=3)
                        d.text((pt[0] + 9, pt[1] - 8), str(i + 1), fill=col)
            name = os.path.splitext(os.path.basename(path))[0]
            overlay.save(os.path.join(ROOT, "shots", f"compare_{name}.png"))
    finally:
        proc.kill()
    n = totals["n"]
    med = lambda xs: f"{statistics.median(xs):.0f} ms" if xs else "-"  # noqa: E731
    print(f"\nACCURACY  Vocaela {totals['voc']}/{n}   TinyClick {totals['tc']}/{n}")
    print(f"LATENCY   Vocaela: new screenshot {med(lat['voc_first'])}, same screenshot {med(lat['voc_next'])} ({'CPU' if cpu else 'Arc GPU'})")
    print(f"          TinyClick: new screenshot {med(lat['tc_first'])}, same screenshot {med(lat['tc_next'])} (Arc GPU)")
    print("overlays: shots/compare_state4.png, shots/compare_shot_7.png  (green = true box, red = Vocaela, blue = TinyClick)")


if __name__ == "__main__":
    main()
