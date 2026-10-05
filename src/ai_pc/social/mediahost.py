"""A file on this PC made reachable at a public HTTPS address for a few minutes, because Instagram (pictures) and Threads
(all media) fetch media from a web address and have no upload. Two ways, both closed again as soon as the platform has
the file:

  tunnel      a one-file web server on 127.0.0.1 behind Cloudflare's free quick tunnel (cloudflared, no account): the
              address is random (https://<words>.trycloudflare.com/<32 random characters>/<file>); every other path is
              refused; it stops when the platform has fetched the file
  page_photo  the picture uploaded to your Facebook Page as an unpublished, temporary photo; its own address is given
              (Meta deletes temporary photos after 24 hours). Not documented by Meta for this use: the tunnel is preferred.

  host = MediaHost(mode=None, facebook=connector)   url = host.open(path)   ...   host.close()
"""
import http.server
import mimetypes
import re
import secrets
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from ai_pc.core.config import ROOT
from ai_pc.social.base import SocialError

CLOUDFLARED = ROOT / "tools" / "cloudflared" / "cloudflared.exe"
NO_WINDOW = 0x08000000


class _OneFile(http.server.BaseHTTPRequestHandler):
    files = {}  # secret path -> local file

    def do_GET(self):  # noqa: N802
        p = self.files.get(self.path.split("?")[0])
        if not p:
            self.send_response(404)
            self.end_headers()
            return
        data = Path(p).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(p)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self):  # noqa: N802
        p = self.files.get(self.path.split("?")[0])
        self.send_response(200 if p else 404)
        if p:
            self.send_header("Content-Length", str(Path(p).stat().st_size))
        self.end_headers()

    def log_message(self, *a):
        pass


class MediaHost:
    def __init__(self, mode=None, facebook=None, cloudflared=CLOUDFLARED, launcher=None, check=True):
        self.facebook, self.cloudflared = facebook, Path(cloudflared)
        self.mode = mode or ("tunnel" if self.cloudflared.exists() or launcher else "page_photo" if facebook else None)
        self.launcher = launcher  # tests: a stand-in for cloudflared -> (process-like, public base url)
        self.check = check
        self.srv = self.proc = self.base = None
        self.handler = type("OneFile", (_OneFile,), {"files": {}})
        self.temp_photos = []

    def open(self, path):
        if self.mode is None:
            raise SocialError("policy", "Instagram and Threads take pictures only from a web address: run 'ai-pc social setup-tunnel' once "
                                        "(Cloudflare's free tunnel tool), or connect your Facebook Page")
        if self.mode == "page_photo":
            return self._page_photo(path)
        if self.srv is None:
            self._start()
        key = "/" + secrets.token_urlsafe(24) + "/" + re.sub(r"[^\w.-]", "_", Path(path).name)
        self.handler.files[key] = str(path)
        url = self.base + key
        if self.check:
            self._reachable(url)
        return url

    def _start(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        local = f"http://127.0.0.1:{self.srv.server_port}"
        if self.launcher:
            self.proc, self.base = self.launcher(local)
            return
        self.proc = subprocess.Popen([str(self.cloudflared), "tunnel", "--no-autoupdate", "--url", local], stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW)
        t0 = time.time()
        while time.time() - t0 < 40:
            line = self.proc.stdout.readline()
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line or "")
            if m:
                self.base = m.group(0)
                threading.Thread(target=lambda: [None for _ in self.proc.stdout], daemon=True).start()  # keep its output drained
                return
            if self.proc.poll() is not None:
                break
        self.close()
        raise SocialError("retry", "Cloudflare's tunnel did not start (no internet, or Cloudflare is busy); trying again later")

    def _reachable(self, url, tries=10):
        for _ in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=10) as r:
                    if r.status == 200:
                        return True
            except Exception:  # noqa: BLE001  (a new tunnel takes a few seconds to answer)
                time.sleep(2)
        raise SocialError("retry", "the temporary web address for the picture did not answer; trying again later")

    def _page_photo(self, path):
        if not self.facebook:
            raise SocialError("policy", "no Facebook Page connected to lend a picture address")
        r = self.facebook.temp_photo(path)
        self.temp_photos.append(r["id"])
        return r["url"]

    def close(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            self.proc = None
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None
        self.handler.files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
