"""OBS Studio (the most used recording and streaming app) through obs-websocket, built into OBS 28 and later (Tools >
WebSocket Server Settings > Enable; port 4455 and a password): scenes listed, made and switched, recording started and
stopped (with the saved file named), streaming started and stopped after a yes (it goes live), text and picture sources
added to a scene, and a screenshot of what OBS shows. Every change is read back from OBS.

  'obs scenes'   'switch obs to scene Gaming'   "add text 'Live now' to obs scene Main"   'add image logo.png to obs scene Main'
  'start recording in obs'   'stop recording in obs'   'start streaming in obs'   'obs screenshot'
"""
import base64
import hashlib
import itertools
import json
import re
import time
from pathlib import Path

from ai_pc.apps.ws import WebSocket, WSError
from ai_pc.core import vault

NAME, LABEL = "obs", "OBS Studio: scenes, sources, recording, streaming, screenshots (obs-websocket)"
EXAMPLES = ["obs scenes", "switch obs to scene Gaming", "start recording in obs", "add text 'Live now' to obs scene Main"]
OUTWARD = {"stream_start"}
APP = {"label": "OBS Studio", "fields": [("password", "obs-websocket password", True), ("port", "Port (4455)", False)],
       "steps": ["Install OBS Studio (say 'install obs studio' to the apps chat, or obsproject.com) and open it.",
                 "Tools > WebSocket Server Settings: tick 'Enable WebSocket server', keep port 4455, 'Show Connect Info' to copy the password.",
                 "Run 'ai-pc apps connect obs' and paste the password (kept encrypted)."]}
_ids = itertools.count(1)


class Client:
    def __init__(self, password="", host="127.0.0.1", port=4455):
        self.host, self.port, self.password = host, int(port or 4455), password
        self.ws = None

    def connect(self):
        try:
            self.ws = WebSocket(f"ws://{self.host}:{self.port}", timeout=10)
        except (OSError, WSError) as e:
            raise RuntimeError(f"OBS is not answering on port {self.port}: open OBS and enable Tools > WebSocket Server Settings ({e})") from e
        hello = json.loads(self.ws.recv())["d"]
        ident = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = hello.get("authentication")
        if auth:
            secret = base64.b64encode(hashlib.sha256((self.password + auth["salt"]).encode()).digest()).decode()
            ident["authentication"] = base64.b64encode(hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
        self.ws.send(json.dumps({"op": 1, "d": ident}))
        try:
            msg = json.loads(self.ws.recv())
        except WSError as e:
            raise RuntimeError("OBS refused the password (Tools > WebSocket Server Settings > Show Connect Info)") from e
        if msg.get("op") != 2:
            raise RuntimeError("OBS did not accept the connection")
        return hello.get("obsWebSocketVersion")

    def req(self, kind, data=None):
        if self.ws is None:
            self.connect()
        rid = str(next(_ids))
        self.ws.send(json.dumps({"op": 6, "d": {"requestType": kind, "requestId": rid, "requestData": data or {}}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("op") == 7 and m["d"].get("requestId") == rid:
                st = m["d"]["requestStatus"]
                if not st.get("result"):
                    raise RuntimeError(f"OBS: {kind} failed ({st.get('code')}: {st.get('comment', '')})")
                return m["d"].get("responseData") or {}

    def close(self):
        if self.ws:
            self.ws.close()
            self.ws = None


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME) or {}
    return Client(c.get("password", ""), c.get("host", "127.0.0.1"), c.get("port", 4455))


def connect(values, store=None):
    c = Client(values.get("password", ""), port=values.get("port") or 4455)
    v = c.connect()
    c.close()
    (store or (lambda x: vault.put(NAME, x)))({"password": values.get("password", ""), "port": int(values.get("port") or 4455)})
    return {"who": f"obs-websocket {v}", "where": "OBS Studio"}


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower().strip(" .?!")
    if not re.search(r"\bobs\b", c):
        return None
    if re.search(r"\bstart\b.*\brecord", c):
        return {"op": "record_start"}
    if re.search(r"\bstop\b.*\brecord", c):
        return {"op": "record_stop"}
    if re.search(r"\b(?:start|go)\b.*\b(?:stream|live)", c):
        return {"op": "stream_start"}
    if re.search(r"\bstop\b.*\b(?:stream|live)", c):
        return {"op": "stream_stop"}
    if re.search(r"\bscreenshot\b", c):
        return {"op": "shot"}
    m = re.search(r"\b(?:switch|change|go)\s+(?:obs\s+)?to\s+(?:the\s+)?scene\s+['\"]?(.+?)['\"]?$", text, re.I)
    if m:
        return {"op": "switch", "scene": m.group(1).strip()}
    m = re.search(r"\b(?:make|create|new)\s+(?:an?\s+)?(?:obs\s+)?scene\s+['\"]?(.+?)['\"]?(?:\s+in\s+obs)?$", text, re.I)
    if m:
        return {"op": "scene_new", "scene": m.group(1).strip()}
    m = re.search(r"\badd\s+text\s+['\"]([^'\"]+)['\"]\s+to\s+obs(?:\s+scene\s+['\"]?(.+?)['\"]?)?$", text, re.I)
    if m:
        return {"op": "text", "text": m.group(1), "scene": (m.group(2) or "").strip() or None}
    m = re.search(r"\badd\s+(?:image|picture|logo)\s+(\S+\.(?:png|jpe?g|gif|webp))\s+to\s+obs(?:\s+scene\s+['\"]?(.+?)['\"]?)?$", text, re.I)
    if m:
        f = find_file(m.group(1), ctx) or (m.group(1) if Path(m.group(1)).exists() else None)
        return {"op": "image", "file": f, "scene": (m.group(2) or "").strip() or None} if f else None
    if re.search(r"\bscenes?\b", c):
        return {"op": "scenes"}
    return None


def preview(op, ctx):
    return "Ready to START STREAMING in OBS to the service set in OBS (Settings > Stream): you go live."


def run(op, ctx):
    k = op["op"]
    if k == "stream_start" and not op.get("confirmed"):
        return preview(op, ctx)
    c = client(ctx)
    try:
        if k == "scenes":
            s = c.req("GetSceneList")
            return f"OBS scenes: {', '.join(x['sceneName'] for x in reversed(s['scenes']))}; showing now: {s['currentProgramSceneName']}."
        if k in ("switch", "scene_new"):
            if k == "scene_new":
                c.req("CreateScene", {"sceneName": op["scene"]})
            c.req("SetCurrentProgramScene", {"sceneName": op["scene"]})
            now = c.req("GetCurrentProgramScene")
            return f"OBS now shows scene '{now.get('currentProgramSceneName') or now.get('sceneName')}'" + (" (made new)" if k == "scene_new" else "") + "."
        if k in ("text", "image"):
            scene = op.get("scene") or c.req("GetCurrentProgramScene").get("currentProgramSceneName")
            name = f"AI PC {'Text' if k == 'text' else Path(op['file']).stem} {int(time.time()) % 10000}"
            kind, settings = (("text_gdiplus_v3", {"text": op["text"], "font": {"face": "Arial", "size": 96, "style": "Bold"}}) if k == "text"
                              else ("image_source", {"file": str(Path(op["file"]).resolve())}))
            c.req("CreateInput", {"sceneName": scene, "inputName": name, "inputKind": kind, "inputSettings": settings, "sceneItemEnabled": True})
            got = c.req("GetInputSettings", {"inputName": name})["inputSettings"]
            ok = (got.get("text") == op["text"]) if k == "text" else (Path(got.get("file", "")).name == Path(op["file"]).name)
            return f"Added '{name}' to OBS scene '{scene}' ({'read back from OBS' if ok else 'NOT the same when read back'})."
        if k == "record_start":
            c.req("StartRecord")
            st = c.req("GetRecordStatus")
            return "OBS is recording." if st.get("outputActive") else "OBS did not start recording."
        if k == "record_stop":
            r = c.req("StopRecord")
            path = r.get("outputPath")
            return f"Recording saved: {path}" + (" (the file is there)" if path and Path(path).exists() else "") + "."
        if k == "stream_start":
            c.req("StartStream")
            st = c.req("GetStreamStatus")
            return "OBS is LIVE." if st.get("outputActive") else "OBS did not go live (check Settings > Stream)."
        if k == "stream_stop":
            c.req("StopStream")
            return "Streaming stopped."
        out = Path(ctx["out"]) / "obs"
        out.mkdir(parents=True, exist_ok=True)
        scene = c.req("GetCurrentProgramScene").get("currentProgramSceneName")
        dest = out / f"obs_{int(time.time())}.png"
        c.req("SaveSourceScreenshot", {"sourceName": scene, "imageFormat": "png", "imageFilePath": str(dest.resolve()), "imageWidth": 1280})
        return f"Screenshot of OBS scene '{scene}': {dest}" + (" (saved)" if dest.exists() else " (OBS did not save it)") + "."
    finally:
        if (ctx.get("clients") or {}).get(NAME) is None:
            c.close()
