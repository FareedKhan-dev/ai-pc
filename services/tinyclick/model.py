"""TinyClick (Florence-2-base fine-tuned to predict a click point) on a CapCut screenshot.

  python services/tinyclick/model.py --download-only   # fetch weights into ./models/hf (shows progress)
  python services/tinyclick/model.py                   # run the 12-query test, score hits, time it

Everything (weights, HF cache, remote code) stays inside this project folder.
Input/output format follows the authors' tinyclick_utils.py:
  prompt = ("what to do to execute the command? " + command).lower(); image resized to 768x768
  output = "click <loc_X><loc_Y>" with X,Y in 0..1000 (relative to the original image)
"""
import json
import os
import re
import sys
import time

ROOT = os.environ.get("AI_PC_HOME") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))  # the project folder
os.environ["HF_HOME"] = os.path.join(ROOT, "models", "hf")  # keep every cache inside the project
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

REPO = "Krystianz/TinyClick"  # community mirror of Samsung/TinyClick (the original repo is offline)
IMAGE = os.path.join(ROOT, "shots", "state4.png")  # clean CapCut home page, 1920x1140

# (command, ground-truth box x0,y0,x1,y1 in image pixels, measured by eye from the screenshot)
QUERIES = [
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
]


def download():
    from huggingface_hub import snapshot_download

    t = time.perf_counter()
    path = snapshot_download(REPO)
    print(f"downloaded to {path} in {time.perf_counter() - t:.0f}s", flush=True)
    for root, _, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            print(f"  {os.path.getsize(os.path.realpath(p)) / 1e6:9.1f} MB  {f}")


def load():
    from unittest.mock import patch

    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor
    from transformers.dynamic_module_utils import get_imports

    def no_flash(filename):  # Florence-2's remote code lists flash_attn, which is not installable on Windows
        return [i for i in get_imports(filename) if i != "flash_attn"]

    t = time.perf_counter()
    with patch("transformers.dynamic_module_utils.get_imports", no_flash):
        processor = AutoProcessor.from_pretrained(REPO, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(REPO, trust_remote_code=True).eval()
    print(f"model loaded in {time.perf_counter() - t:.1f}s | params: {sum(p.numel() for p in model.parameters()) / 1e6:.0f}M | threads: {torch.get_num_threads()}", flush=True)
    return torch, processor, model


def click_point(torch, processor, model, img, command):
    t0 = time.perf_counter()
    text = ("What to do to execute the command? " + command.strip()).lower()
    enc = processor(images=img, text=text, return_tensors="pt", do_resize=True)
    t1 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(**enc)
    t2 = time.perf_counter()
    gen = processor.batch_decode(out, skip_special_tokens=False)[0]
    m = re.search(r"</s><s>(<[^>]+>|[^<\s]+)\s*([^<]*?)(<loc_\d+>.*)", gen)
    pt = re.findall(r"<loc_(\d+)><loc_(\d+)>", gen)
    if not m or m.group(1) != "click" or not pt:
        return None, gen, (t1 - t0) * 1000, (t2 - t1) * 1000
    x, y = int(pt[0][0]) / 1000 * img.size[0], int(pt[0][1]) / 1000 * img.size[1]
    return (round(x), round(y)), gen, (t1 - t0) * 1000, (t2 - t1) * 1000


def main():
    if "--download-only" in sys.argv:
        download()
        return
    from PIL import Image, ImageDraw

    torch, processor, model = load()
    img = Image.open(IMAGE).convert("RGB")
    print(f"image {img.size}", flush=True)

    # warm-up (first call includes one-time costs), then measure
    click_point(torch, processor, model, img, QUERIES[0][0])

    rows, hits = [], 0
    overlay = img.copy()
    d = ImageDraw.Draw(overlay)
    for i, (cmd, box) in enumerate(QUERIES, 1):
        pt, raw, t_pre, t_gen = click_point(torch, processor, model, img, cmd)
        hit = bool(pt) and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]
        hits += hit
        rows.append({"command": cmd, "point": pt, "hit": hit, "preprocess_ms": round(t_pre), "generate_ms": round(t_gen), "raw": raw[-60:]})
        print(f"{i:2d}. {'HIT ' if hit else 'MISS'} {cmd:48s} -> {pt}  (box {box})  pre {t_pre:5.0f} ms + generate {t_gen:5.0f} ms", flush=True)
        d.rectangle(box, outline=(0, 200, 0), width=3)
        if pt:
            r = 14
            d.ellipse((pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r), outline=(255, 0, 0) if not hit else (255, 255, 0), width=4)
            d.text((pt[0] + r + 2, pt[1] - r), str(i), fill=(255, 255, 255))
    lat = sorted(r["preprocess_ms"] + r["generate_ms"] for r in rows)
    print(f"\naccuracy: {hits}/{len(QUERIES)} clicks inside the true element")
    print(f"latency per query (CPU, warm): median {lat[len(lat)//2]} ms, min {lat[0]} ms, max {lat[-1]} ms")
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    overlay.save(os.path.join(ROOT, "shots", "tinyclick_result.png"))
    json.dump(rows, open(os.path.join(ROOT, "out", "tinyclick_results.json"), "w"), indent=1)
    print("saved shots/tinyclick_result.png (green = true box, yellow circle = hit, red = miss) and out/tinyclick_results.json")


if __name__ == "__main__":
    main()
