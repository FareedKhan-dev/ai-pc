"""Client for the TinyClick vision grounder (tinyclick_ui.py, running on the Intel Arc GPU).

Flow: upload the screenshot once (the server encodes it, ~120 ms), then each 'where is X?' question costs ~110 ms.
`prefetch()` uploads in the background while a planner is still thinking, so grounding is ready the moment it answers.
"""
import io
import json
import os
import subprocess
import threading
import time
import urllib.request

from .config import GROUNDER, GROUNDER_CMD, GROUNDER_URL, ROOT


class GrounderError(Exception):
    pass


def make_grounder(kind=None):
    """The configured click model: 'vocaela' (default) or 'tinyclick'."""
    if (kind or GROUNDER).lower() == "vocaela":
        from .vocaela import VocaelaGrounder
        return VocaelaGrounder()
    return Grounder()


class Grounder:
    def __init__(self, url=GROUNDER_URL, autostart=True):
        self.url = url.rstrip("/")
        self.autostart = autostart
        self._pre = None  # (image object, thread, info holder)

    def _req(self, path, data=None, raw=False, timeout=30):
        req = urllib.request.Request(self.url + path, data=data, method="POST" if data is not None else "GET",
                                     headers={"Content-Type": "application/octet-stream" if raw else "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def alive(self):
        try:
            self._req("/api/info", timeout=2)
            return True
        except Exception:
            return False

    def ensure(self, timeout=120):
        if self.alive():
            return True
        if not self.autostart:
            raise GrounderError("grounder server is not running (python tinyclick_ui.py)")
        env = dict(os.environ, HF_HOME=str(ROOT / "models" / "hf"))
        log = open(ROOT / "runs" / "grounder.log", "ab")
        subprocess.Popen(GROUNDER_CMD, cwd=str(ROOT), env=env, stdout=log, stderr=log,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.alive():
                return True
            time.sleep(1)
        raise GrounderError("grounder server did not start in time")

    def _upload(self, img):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        return self._req("/api/image", buf.getvalue(), raw=True)

    def prefetch(self, img):
        """Upload + encode in the background (call while the planner is thinking)."""
        holder = {}

        def work():
            try:
                holder["info"] = self._upload(img)
            except Exception as e:  # noqa: BLE001
                holder["error"] = e

        th = threading.Thread(target=work, daemon=True)
        th.start()
        self._pre = (img, th, holder)

    def load(self, img):
        """Make `img` the server's current screenshot (skips the upload if a prefetch already did it). Returns ms spent."""
        if self._pre and self._pre[0] is img:
            self._pre[1].join(timeout=30)
            if "error" in self._pre[2]:
                raise GrounderError(str(self._pre[2]["error"]))
            return 0.0
        t = time.perf_counter()
        self._upload(img)
        return (time.perf_counter() - t) * 1000

    def find(self, target, beams=3):
        """Where is `target` on the currently loaded screenshot? Returns {'point': (x, y), 'find_ms': ...}."""
        cmd = target if target.lower().startswith(("click", "tap", "press")) else f"click {target}"
        t = time.perf_counter()
        r = self._req("/api/find", json.dumps({"command": cmd, "beams": beams}).encode())
        if not r.get("point"):
            raise GrounderError(f"no click point returned for {target!r}")
        return {"point": tuple(r["point"]), "find_ms": (time.perf_counter() - t) * 1000, "raw": r.get("raw", "")}

    def ground(self, img, target, beams=3):
        """Return {'point': (x, y) in img pixels, 'ms': ..., 'load_ms': ...} for a plain-words target."""
        t0 = time.perf_counter()
        load_ms = self.load(img)
        r = self.find(target, beams)
        return {**r, "load_ms": load_ms, "ms": (time.perf_counter() - t0) * 1000}
