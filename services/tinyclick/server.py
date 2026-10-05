"""Local test UI for TinyClick (runs on the Intel Arc GPU when available).

  .venv-xpu\\Scripts\\python.exe services/tinyclick/server.py        then open  http://127.0.0.1:8765

* Listens on 127.0.0.1 only. It never clicks or moves anything on your screen: it only *predicts* a click point.
* Uses only the Python standard library for the web part (no extra installs).
"""
import ctypes
import io
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # screen capture in physical pixels
except Exception:
    pass

import model as T  # sets HF_HOME to <project>/models/hf before transformers is imported
from PIL import Image, ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "shots")
PAGE = os.path.join(HERE, "ui.html")
PORT = 8765
MAX_BODY = 40 * 1024 * 1024

torch, processor, model = T.load()
if hasattr(torch, "xpu") and torch.xpu.is_available():
    DEV, DT = "xpu", torch.float16
    DEVNAME = torch.xpu.get_device_name(0)
else:
    DEV, DT, DEVNAME = "cpu", torch.float32, "CPU"
model.to(DEV, DT)
ORIG_ENCODE = model._encode_image
LOCK = threading.Lock()


class S:  # the currently loaded screenshot
    img = None
    png = b""
    pv = None
    feats = None
    id = 0


def sync():
    if DEV == "xpu":
        torch.xpu.synchronize()


def prompt(cmd):
    return ("What to do to execute the command? " + cmd.strip()).lower()


def set_image(img):
    """Preprocess + encode the screenshot once; every command on it then reuses the encoded image."""
    img = img.convert("RGB")
    if img.width * img.height > 40_000_000:
        raise ValueError("image too large")
    with LOCK:
        t0 = time.perf_counter()
        enc = processor(images=img, text=prompt("x"), return_tensors="pt", do_resize=True)
        pv = enc["pixel_values"].to(DEV, DT)
        t1 = time.perf_counter()
        with torch.inference_mode():
            feats = ORIG_ENCODE(pv)
        sync()
        t2 = time.perf_counter()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        S.img, S.png, S.pv, S.feats = img, buf.getvalue(), pv, feats
        S.id += 1
        return {"id": S.id, "width": img.width, "height": img.height,
                "preprocess_ms": round((t1 - t0) * 1000), "encode_ms": round((t2 - t1) * 1000)}


def find(cmd, beams):
    cmd = (cmd or "").strip()[:300]
    if not cmd:
        raise ValueError("empty command")
    with LOCK:
        if S.img is None:
            raise ValueError("load a screenshot first")
        feats = S.feats
        model._encode_image = lambda x: feats  # image already encoded
        try:
            t0 = time.perf_counter()
            ids = processor.tokenizer(prompt(cmd), return_tensors="pt")["input_ids"].to(DEV)
            t1 = time.perf_counter()
            with torch.inference_mode():
                out = model.generate(input_ids=ids, pixel_values=S.pv, num_beams=max(1, min(int(beams), 5)),
                                     max_new_tokens=16, do_sample=False)
            sync()
            t2 = time.perf_counter()
        finally:
            model._encode_image = ORIG_ENCODE
        raw = processor.batch_decode(out.cpu(), skip_special_tokens=False)[0]
        m = re.search(r"</s><s>(<[^>]+>|[^<\s]+)\s*([^<]*?)(<loc_\d+>.*)", raw)
        pt = re.findall(r"<loc_(\d+)><loc_(\d+)>", raw)
        res = {"ok": True, "prompt": prompt(cmd), "raw": raw, "ms": round((t2 - t0) * 1000),
               "decode_ms": round((t2 - t1) * 1000), "action": m.group(1) if m else None, "point": None}
        if m and m.group(1) == "click" and pt:
            nx, ny = int(pt[0][0]), int(pt[0][1])
            res["norm"] = [nx, ny]
            res["point"] = [round(nx / 1000 * S.img.width), round(ny / 1000 * S.img.height)]
        return res


def list_shots():
    if not os.path.isdir(SHOTS):
        return []
    files = [f for f in os.listdir(SHOTS) if re.fullmatch(r"[\w\-. ]+\.(png|jpe?g|webp|bmp)", f, re.I)]
    return sorted(files, key=lambda f: -os.path.getmtime(os.path.join(SHOTS, f)))


class Handler(BaseHTTPRequestHandler):
    server_version = "TinyClickUI"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n)

    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, open(PAGE, "rb").read(), "text/html; charset=utf-8")
        if path == "/api/info":
            return self._json({"device": DEVNAME, "dtype": str(DT).split(".")[-1],
                               "params_m": round(sum(p.numel() for p in model.parameters()) / 1e6),
                               "loaded": S.img is not None, "shots": list_shots()})
        if path == "/current.png" and S.png:
            return self._send(200, S.png, "image/png")
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/image":
                return self._json(set_image(Image.open(io.BytesIO(body))))
            data = json.loads(body or b"{}")
            if path == "/api/use_shot":
                name = os.path.basename(str(data.get("name", "")))
                if name not in list_shots():
                    raise ValueError("unknown screenshot")
                return self._json(set_image(Image.open(os.path.join(SHOTS, name))))
            if path == "/api/capture":
                time.sleep(max(0, min(float(data.get("delay", 5)), 15)))
                return self._json(set_image(ImageGrab.grab(all_screens=False)))
            if path == "/api/find":
                return self._json(find(data.get("command"), data.get("beams", 3)))
            self._json({"error": "not found"}, 404)
        except Exception as e:  # report the message only, never a traceback
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}, 400)


if __name__ == "__main__":
    # warm up the GPU kernels so the first real query is not slow
    set_image(Image.new("RGB", (1920, 1080), (30, 30, 30)))
    find("click ok", 3)
    S.img = None
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"READY http://127.0.0.1:{PORT}  (device: {DEVNAME}, {DT})", flush=True)
    srv.serve_forever()
