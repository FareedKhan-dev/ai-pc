"""Where do TinyClick's ~2 s go on this CPU? Can the image be encoded once and reused?"""
import os
import statistics as st
import time

import tinyclick_run as T  # sets HF_HOME to ./models/hf before anything else is imported
from PIL import Image

torch, processor, model = T.load()
img = Image.open(T.IMAGE).convert("RGB")
cmds = [c for c, _ in T.QUERIES]


def enc_for(cmd):
    text = ("What to do to execute the command? " + cmd).lower()
    return processor(images=img, text=text, return_tensors="pt", do_resize=True)


def timeit(fn, n=3):
    fn()  # warm-up
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return st.median(xs)


enc = enc_for(cmds[0])
with torch.inference_mode():
    t_img = timeit(lambda: model._encode_image(enc["pixel_values"]))
    t_all = timeit(lambda: model.generate(**enc))
print(f"image encoder alone : {t_img:6.0f} ms")
print(f"full generate       : {t_all:6.0f} ms  -> rest (text decode) ~ {t_all - t_img:.0f} ms", flush=True)

print("\nthread sweep (full generate, median of 3):")
for n in (4, 6, 8, 12, 16):
    torch.set_num_threads(n)
    with torch.inference_mode():
        print(f"  {n:2d} threads: {timeit(lambda: model.generate(**enc)):6.0f} ms", flush=True)
torch.set_num_threads(16)

# Cache the image features once, then answer all 12 queries without re-encoding the screenshot.
orig = model._encode_image
with torch.inference_mode():
    t = time.perf_counter()
    feats = orig(enc["pixel_values"])
    t_enc_once = (time.perf_counter() - t) * 1000
model._encode_image = lambda pv: feats
same, lat = 0, []
for cmd in cmds:
    pt_c, _, t_pre, t_gen = T.click_point(torch, processor, model, img, cmd)  # uses cached features
    model._encode_image = orig
    pt_f, _, _, _ = T.click_point(torch, processor, model, img, cmd)         # reference: full path
    model._encode_image = lambda pv: feats
    same += pt_c == pt_f
    lat.append(t_pre + t_gen)
model._encode_image = orig
print(f"\nencode screenshot once: {t_enc_once:.0f} ms")
print(f"cached-feature query  : median {st.median(lat):.0f} ms (min {min(lat):.0f}, max {max(lat):.0f}) over {len(lat)} queries")
print(f"same click as the full path: {same}/{len(cmds)}")
