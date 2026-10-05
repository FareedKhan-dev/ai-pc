"""TinyClick on the Intel Arc GPU (torch XPU): accuracy + latency, fp32 vs fp16, with and without cached image features.

Run with the XPU venv:  .venv-xpu\\Scripts\\python.exe tinyclick_xpu.py [cpu|xpu]
"""
import os
import re
import statistics as st
import sys
import time

import tinyclick_run as T  # sets HF_HOME to ./models/hf first
from PIL import Image

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "xpu"
torch, processor, model = T.load()
img = Image.open(T.IMAGE).convert("RGB")


def sync():
    if DEVICE == "xpu":
        torch.xpu.synchronize()


def parse(gen):
    m = re.search(r"</s><s>(<[^>]+>|[^<\s]+)\s*([^<]*?)(<loc_\d+>.*)", gen)
    pt = re.findall(r"<loc_(\d+)><loc_(\d+)>", gen)
    if not m or m.group(1) != "click" or not pt:
        return None
    return (round(int(pt[0][0]) / 1000 * img.size[0]), round(int(pt[0][1]) / 1000 * img.size[1]))


def run_query(cmd, dtype, feats=None):
    t0 = time.perf_counter()
    text = ("What to do to execute the command? " + cmd.strip()).lower()
    enc = processor(images=img, text=text, return_tensors="pt", do_resize=True)
    enc = {k: (v.to(DEVICE, dtype) if v.is_floating_point() else v.to(DEVICE)) for k, v in enc.items()}
    sync()
    t1 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(**enc)
    sync()
    t2 = time.perf_counter()
    gen = processor.batch_decode(out.cpu(), skip_special_tokens=False)[0]
    return parse(gen), (t2 - t0) * 1000, (t2 - t1) * 1000


def evaluate(label, dtype, cached=False):
    model.to(DEVICE, dtype)
    orig = model._encode_image
    feats = None
    if cached:
        enc = processor(images=img, text="x", return_tensors="pt", do_resize=True)
        pv = enc["pixel_values"].to(DEVICE, dtype)
        with torch.inference_mode():
            orig(pv)  # warm-up
            sync()
            t = time.perf_counter()
            feats = orig(pv)
            sync()
        print(f"  [{label}] encode screenshot once: {(time.perf_counter() - t) * 1000:.0f} ms", flush=True)
        model._encode_image = lambda x: feats
    for _ in range(2):  # warm-up (kernel compilation on the GPU happens here)
        run_query(T.QUERIES[0][0], dtype)
    hits, lat, gen_lat, pts = 0, [], [], []
    for cmd, box in T.QUERIES:
        pt, total, gen = run_query(cmd, dtype)
        hits += bool(pt) and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]
        lat.append(total)
        gen_lat.append(gen)
        pts.append(pt)
    model._encode_image = orig
    print(f"[{label:28s}] hits {hits}/12 | per query: median {st.median(lat):6.0f} ms (min {min(lat):.0f}, max {max(lat):.0f}) | model-only median {st.median(gen_lat):.0f} ms", flush=True)
    return pts


print(f"device: {DEVICE}")
ref = evaluate(f"{DEVICE} fp32", torch.float32)
p16 = evaluate(f"{DEVICE} fp16", torch.float16)
print(f"  fp16 gives the same click point as fp32 on {sum(a == b for a, b in zip(ref, p16))}/12 queries")
evaluate(f"{DEVICE} fp16 + cached image", torch.float16, cached=True)
