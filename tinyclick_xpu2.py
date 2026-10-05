"""Squeeze TinyClick latency on the Arc GPU: cached image features, text-only tokenisation, greedy decoding, short output."""
import re
import statistics as st
import time

import tinyclick_run as T  # sets HF_HOME first
from PIL import Image

torch, processor, model = T.load()
img = Image.open(T.IMAGE).convert("RGB")
DEV, DT = "xpu", torch.float16
model.to(DEV, DT)


def sync():
    torch.xpu.synchronize()


def parse(gen):
    m = re.search(r"</s><s>(<[^>]+>|[^<\s]+)\s*([^<]*?)(<loc_\d+>.*)", gen)
    pt = re.findall(r"<loc_(\d+)><loc_(\d+)>", gen)
    if not m or m.group(1) != "click" or not pt:
        return None
    return (round(int(pt[0][0]) / 1000 * img.size[0]), round(int(pt[0][1]) / 1000 * img.size[1]))


def prompt(cmd):
    return ("What to do to execute the command? " + cmd.strip()).lower()


# 1) one-time work per screenshot: preprocess + encode the image
enc0 = processor(images=img, text=prompt("x"), return_tensors="pt", do_resize=True)
pv = enc0["pixel_values"].to(DEV, DT)
with torch.inference_mode():
    model._encode_image(pv)
    sync()
    t = time.perf_counter()
    feats = model._encode_image(pv)
    sync()
print(f"one-time per screenshot: encode {(time.perf_counter() - t) * 1000:.0f} ms", flush=True)

# sanity: text-only tokenisation must equal what the processor builds
a = processor(images=img, text=prompt("click sign in"), return_tensors="pt", do_resize=True)["input_ids"]
b = processor.tokenizer(prompt("click sign in"), return_tensors="pt")["input_ids"]
print("text-only tokenisation identical to processor:", torch.equal(a, b), flush=True)

orig = model._encode_image


def query(cmd, **gen_kwargs):
    t0 = time.perf_counter()
    ids = processor.tokenizer(prompt(cmd), return_tensors="pt")["input_ids"].to(DEV)
    t1 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(input_ids=ids, pixel_values=pv, **gen_kwargs)
    sync()
    t2 = time.perf_counter()
    gen = processor.batch_decode(out.cpu(), skip_special_tokens=False)[0]
    return parse(gen), (t2 - t0) * 1000, (t2 - t1) * 1000


def evaluate(label, **gen_kwargs):
    model._encode_image = lambda x: feats  # reuse cached image features
    for _ in range(2):
        query(T.QUERIES[0][0], **gen_kwargs)
    hits, lat, pts = 0, [], []
    for cmd, box in T.QUERIES:
        pt, total, _ = query(cmd, **gen_kwargs)
        hits += bool(pt) and box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]
        lat.append(total)
        pts.append(pt)
    model._encode_image = orig
    print(f"[{label:34s}] hits {hits}/12 | median {st.median(lat):5.0f} ms (min {min(lat):.0f}, max {max(lat):.0f})", flush=True)
    return pts


print("default generation settings:", {k: getattr(model.generation_config, k, None) for k in ("num_beams", "max_new_tokens", "do_sample")})
base = evaluate("cached + default decoding")
greedy = evaluate("cached + greedy, max 12 tokens", num_beams=1, max_new_tokens=12, do_sample=False)
print(f"  greedy gives the same click as default on {sum(a == b for a, b in zip(base, greedy))}/12 queries")
