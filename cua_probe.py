"""Try Cua Driver (tools/cua-driver) the way an agent uses it: MCP over stdio. Times every call.

  .venv\\Scripts\\python.exe cua_probe.py calc      # 6 x 7 in Calculator, read the display (their tutorial task)
  .venv\\Scripts\\python.exe cua_probe.py capcut    # what does it see in CapCut (custom-drawn Qt UI)?

Telemetry and the update check are switched off through environment variables (nothing persisted outside the project).
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(ROOT, "tools", "cua-driver", "cua-driver-rs-0.31.0-windows-x86_64", "cua-driver.exe")
ENV = dict(os.environ, CUA_DRIVER_RS_TELEMETRY_ENABLED="false", CUA_DRIVER_RS_UPDATE_CHECK="false")


class MCP:
    def __init__(self):
        self.p = subprocess.Popen([EXE, "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env=ENV, creationflags=0x08000000)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "cua_probe", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, msg):
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()

    def rpc(self, method, params):
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("cua-driver exited")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def call(self, tool, args):
        t = time.perf_counter()
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        ms = (time.perf_counter() - t) * 1000
        text = " ".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        imgs = sum(1 for c in r.get("content", []) if c.get("type") == "image")
        return r.get("structuredContent") or {}, text, ms, imgs, bool(r.get("isError"))

    def close(self):
        self.p.kill()

    def shot(self, pid, wid, path):
        """Background capture of one window (it does not need to be in front) saved as a PNG; returns its size."""
        import base64
        r = self.rpc("tools/call", {"name": "get_window_state",
                                    "arguments": {"pid": pid, "window_id": wid, "include_accessibility_tree": False}})
        for c in r.get("content", []):
            if c.get("type") == "image":
                open(path, "wb").write(base64.b64decode(c["data"]))
                from PIL import Image
                return Image.open(path).size
        return None


def capcut_window(m):
    """(pid, window_id) of CapCut's largest window."""
    sc, *_ = m.call("list_windows", {})
    ws = [w for w in (sc.get("windows") or []) if "capcut" in str(w.get("app_name", "")).lower()]
    area = lambda w: (w.get("bounds") or {}).get("width", 0) * (w.get("bounds") or {}).get("height", 0)  # noqa: E731
    w = max(ws, key=area)
    return w.get("pid"), w.get("window_id")


def calc():
    m = MCP()
    total = time.perf_counter()
    sc, text, ms, _, err = m.call("launch_app", {"name": "Calculator"})
    pid = sc.get("pid")
    wins = sc.get("windows") or []
    print(f"launch_app            {ms:7.0f} ms  pid={pid} windows={len(wins)} error={err} {text[:120]!r}")
    wid = wins[0].get("window_id") if wins else None
    for _ in range(20):  # the window can appear a moment after the launch call returns
        if wid:
            break
        time.sleep(0.25)
        sc, text, ms, _, err = m.call("list_windows", {"pid": pid})
        ws = [w for w in (sc.get("windows") or []) if w.get("pid") == pid or not w.get("pid")]
        wid = ws[0].get("window_id") if ws else None
    sc, text, ms, imgs, err = m.call("get_window_state", {"pid": pid, "window_id": wid})
    els = sc.get("elements") or []
    print(f"get_window_state      {ms:7.0f} ms  elements={len(els)} screenshots={imgs} error={err}")
    if els:
        print("   element fields:", sorted(els[0].keys()))
        print("   sample:", json.dumps(els[min(5, len(els) - 1)])[:220])
    want = {"Six": None, "Multiply by": None, "Seven": None, "Equals": None}
    for e in els:
        if e.get("label") in want and want[e["label"]] is None:
            want[e["label"]] = e.get("element_token")
    for label, tok in want.items():
        sc, text, ms, _, err = m.call("click", {"pid": pid, "window_id": wid, "element_token": tok})
        print(f"click {label!r:14s}  {ms:7.0f} ms  error={err} {text[:90]!r}")
    sc, text, ms, _, err = m.call("get_window_state", {"pid": pid, "window_id": wid, "query": "Display is",
                                                        "include_screenshot": False})
    disp = [e.get("label") for e in (sc.get("elements") or []) if "Display is" in str(e.get("label"))]
    print(f"read display          {ms:7.0f} ms  -> {disp}")
    print(f"TOTAL {(time.perf_counter() - total) * 1000:.0f} ms (6 x 7 = 42 expected)")
    fg = __import__("ctypes").windll.user32.GetForegroundWindow()
    print("Calculator in the foreground?", fg == wid)
    m.call("kill_app", {"pid": pid})
    m.close()


def capcut():
    m = MCP()
    sc, text, ms, _, err = m.call("launch_app", {"name": "CapCut"})
    pid, wins = sc.get("pid"), sc.get("windows") or []
    print(f"launch_app            {ms:7.0f} ms  pid={pid} windows={len(wins)} error={err} {text[:120]!r}")
    time.sleep(8)  # CapCut shows a splash, then its home window
    sc, text, ms, _, err = m.call("list_windows", {"pid": pid})
    ws = sorted((w for w in (sc.get("windows") or [])), key=lambda w: -(w.get("bounds") or {}).get("width", 0) * (w.get("bounds") or {}).get("height", 0))
    wid = ws[0].get("window_id") if ws else None
    sc, text, ms, imgs, err = m.call("get_window_state", {"pid": pid, "window_id": wid})
    els = sc.get("elements") or []
    print(f"get_window_state      {ms:7.0f} ms  elements={len(els)} screenshots={imgs} error={err}")
    for e in els[:15]:
        print("   ", json.dumps({k: e.get(k) for k in ("element_index", "role", "label", "actions")})[:160])
    print("   (markdown head)", (sc.get("tree_markdown") or text)[:400].replace("\n", " | "))
    m.close()


if __name__ == "__main__":
    {"calc": calc, "capcut": capcut}[sys.argv[1] if len(sys.argv) > 1 else "calc"]()
