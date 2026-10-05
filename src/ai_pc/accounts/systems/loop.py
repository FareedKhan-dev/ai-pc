"""A sign-in's way back to this PC at http://localhost:PORT/path, listened for on both 127.0.0.1 and ::1 (a browser may
send 'localhost' to either), for services that refuse 127.0.0.1 (Xero)."""
import http.server
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser

from ai_pc.accounts.systems import SyncError


class _V6(http.server.HTTPServer):
    address_family = socket.AF_INET6


def loopback_localhost(build_url, port, path, show=print, open_url=webbrowser.open, timeout=300, who="the service"):
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            if u.path.rstrip("/") != path.rstrip("/"):
                self.send_response(404)
                self.end_headers()
                return
            got.update({k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in got and got.get("state") == state
            self.wfile.write(("<h2>Signed in. You can close this tab and go back to the AI PC.</h2>" if ok else
                              "<h2>Sign-in did not finish. Go back to the AI PC and try again.</h2>").encode())

        def log_message(self, *a):
            pass
    servers = []
    for cls, host in ((http.server.HTTPServer, "127.0.0.1"), (_V6, "::1")):
        try:
            s = cls((host, port), Handler)
            s.timeout = 0.5
            servers.append(s)
        except OSError:
            continue
    if not servers:
        raise SyncError(f"port {port} on this PC is busy; close what uses it and try again", "auth")
    redirect = f"http://localhost:{port}{path}"
    url = build_url(redirect, state)
    show(f"Sign in to {who} in your browser (opening it now). If it does not open, paste this link into it:\n{url}")
    threading.Thread(target=lambda: open_url(url), daemon=True).start()
    t0 = time.time()
    while "code" not in got and "error" not in got and time.time() - t0 < timeout:
        for s in servers:
            s.handle_request()
    for s in servers:
        s.server_close()
    if got.get("error") or "code" not in got:
        raise SyncError(f"{who} sign-in did not finish ({got.get('error_description') or got.get('error', 'timed out')})", "auth")
    if got.get("state") != state:
        raise SyncError(f"{who} sign-in answered with the wrong state; try again", "auth")
    return got, redirect
