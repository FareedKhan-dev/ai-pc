"""Client for the Vocaela-2-500M-1024R2 click model (GGUF, run by llama.cpp's llama-server on the Intel Arc GPU via Vulkan).

Measured on 30 CapCut targets (ground_compare.py): 29/30 clicks inside the right element, vs 18/30 for TinyClick.
Cost on the Arc 140T: ~1.6-2.5 s to read a NEW screenshot (~870 image tokens), then ~0.6 s per question about it.
`prefetch()` reads the screenshot in the background while the planner is thinking, so a click usually costs ~0.6 s.

Same interface as grounder.Grounder (alive / ensure / prefetch / load / find / ground). Points are in the pixels of
the image that was passed in. Weights are CC BY-NC-SA 4.0: non-commercial use only.
"""
import base64
import functools
import io
import json
import re
import subprocess
import threading
import time
import urllib.request

from PIL import Image

from ai_pc.core.config import ROOT, VOCAELA_CMD, VOCAELA_URL
from ai_pc.desktop.grounder import GrounderError

SYSTEM_FILE = ROOT / "models" / "vocaela" / "system_prompt.txt"  # the exact training prompt, read when first needed


@functools.cache
def system_prompt():
    return SYSTEM_FILE.read_text(encoding="utf-8")
_VERB = re.compile(r"(?i)^(click|double[- ]click|right[- ]click|tap|press|select|open|choose)\b")
_ACTIONS = re.compile(r"\[\s*\{.*\}\s*\]", re.S)


class VocaelaGrounder:
    name = "vocaela"

    def __init__(self, url=VOCAELA_URL, autostart=True, max_side=1280):
        self.url = url.rstrip("/")
        self.autostart = autostart
        self.max_side = max_side  # the model reads at most 1024 px on the long side; 1280 is what was measured
        self.marker = None        # llama-server's per-process media marker (from /props)
        self._pre = None          # (image object, thread, holder) of a background prefetch
        self._cur = None          # (base64 jpeg, (width, height)) of the screenshot questions refer to

    # ------------------------------------------------------------------ server
    def _get(self, path, timeout=3):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.loads(r.read())

    def _post(self, payload, timeout=90):
        req = urllib.request.Request(self.url + "/completion", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def alive(self):
        try:
            if self._get("/health", 2).get("status") != "ok":
                return False
            if not self.marker:
                self.marker = self._get("/props", 5).get("media_marker") or "<__media__>"
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure(self, timeout=90):
        if self.alive():
            return True
        if not self.autostart:
            raise GrounderError("Vocaela server is not running (see config.VOCAELA_CMD)")
        log = open(ROOT / "runs" / "vocaela_server.log", "ab")
        subprocess.Popen(VOCAELA_CMD, cwd=str(ROOT), stdout=log, stderr=log,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.alive():
                return True
            time.sleep(0.25)
        raise GrounderError("Vocaela server did not start in time (runs/vocaela_server.log)")

    # ------------------------------------------------------------------ images
    def _encode(self, img):
        w, h = img.size
        s = min(1.0, self.max_side / max(w, h))
        im = img if s >= 1.0 else img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode(), (w, h)

    def _prompt(self, instruction=None):
        # the model's chat_template.jinja, rendered by hand (llama.cpp cannot render it); the image comes first, so a
        # prefetch request (system + image) is an exact prefix of every question and its KV cache is reused
        p = f"<|im_start|>System: {system_prompt()}<end_of_utterance>\nUser:{self.marker}"
        if instruction is None:
            return p
        return p + f"{instruction}<end_of_utterance>\nAssistant:<|reserved_special_token_50|>"

    def prefetch(self, img):
        """Read the screenshot on the GPU in the background (call while the planner is thinking)."""
        holder = {}

        def work():
            try:
                holder["enc"] = enc = self._encode(img)
                if self.alive():
                    self._post({"prompt": {"prompt_string": self._prompt(), "multimodal_data": [enc[0]]},
                                "n_predict": 0, "cache_prompt": True, "id_slot": 0})
            except Exception as e:  # noqa: BLE001
                holder["error"] = e

        th = threading.Thread(target=work, daemon=True)
        th.start()
        self._pre = (img, th, holder)

    def load(self, img):
        """Make `img` the screenshot that questions refer to. Returns the ms spent waiting here."""
        t = time.perf_counter()
        if self._pre and self._pre[0] is img:
            self._pre[1].join(timeout=90)
            if "enc" in self._pre[2]:
                self._cur = self._pre[2]["enc"]
                return (time.perf_counter() - t) * 1000
        self._cur = self._encode(img)
        return (time.perf_counter() - t) * 1000

    # ------------------------------------------------------------------ questions
    def find(self, target, beams=None, slot=0):
        """Where is `target` on the loaded screenshot? Returns {'point': (x, y), 'find_ms': ..., 'raw': ...}."""
        if self._cur is None:
            raise GrounderError("no screenshot loaded")
        if not self.marker and not self.alive():
            raise GrounderError("Vocaela server is not running")
        cmd = " ".join(str(target).split())
        if not _VERB.match(cmd):
            cmd = "Click " + cmd
        cmd = cmd[0].upper() + cmd[1:]
        b64, (w, h) = self._cur
        t = time.perf_counter()
        r = self._post({"prompt": {"prompt_string": self._prompt(cmd), "multimodal_data": [b64]},
                        "temperature": 0.0, "n_predict": 64, "stop": ["</Action>"], "cache_prompt": True, "id_slot": slot})
        text = str(r.get("content", ""))
        m = _ACTIONS.search(text)
        try:
            acts = json.loads(m.group(0)) if m else []
        except ValueError:
            acts = []
        for a in acts:
            c = a.get("coordinate") if isinstance(a, dict) else None
            if isinstance(c, list) and len(c) >= 2:
                x = min(max(float(c[0]), 0.0), 0.999) * w
                y = min(max(float(c[1]), 0.0), 0.999) * h
                return {"point": (round(x), round(y)), "find_ms": (time.perf_counter() - t) * 1000, "raw": text[:120]}
        raise GrounderError(f"no click point returned for {target!r}: {text[:80]!r}")

    def ground(self, img, target, beams=None):
        """Return {'point': (x, y) in img pixels, 'ms': ..., 'load_ms': ...} for a plain-words target."""
        t0 = time.perf_counter()
        load_ms = self.load(img)
        r = self.find(target)
        return {**r, "load_ms": load_ms, "ms": (time.perf_counter() - t0) * 1000}

    def ground_zoom(self, img, target, near=None, frac=0.4):
        """Coarse-to-fine for small or crowded targets: take the planner's rough position (or find the rough spot on the
        whole screenshot), then ask again on a crop around it, where small labels become legible. The model reads every
        image at ~1024 px, so a 1920-px window's 9-px tab labels shrink to ~5 px; a crop of 40% gets them back to full
        size. Measured on CapCut: tabs that the whole-screen pass confused were all hit after zooming. Costs ~3 s."""
        t0 = time.perf_counter()
        if near is None:
            self.load(img)
            near = self.find(target)["point"]
        w, h = img.size
        cw, ch = max(64, int(w * frac)), max(64, int(h * frac))
        x0 = int(min(max(0, near[0] - cw / 2), w - cw))
        y0 = int(min(max(0, near[1] - ch / 2), h - ch))
        whole = self._cur
        self._cur = self._encode(img.crop((x0, y0, x0 + cw, y0 + ch)))
        try:
            p = self.find(target, slot=1)["point"]  # slot 1: the whole screenshot stays cached in slot 0
        finally:
            self._cur = whole
        return {"point": (x0 + p[0], y0 + p[1]), "coarse": tuple(near), "ms": (time.perf_counter() - t0) * 1000, "zoom": True}
