"""Fakes for tests/test_popular.py: an OBS Studio obs-websocket v5 server (a real local WebSocket: handshake, Hello with a
password challenge, requests and answers)."""
import base64
import hashlib
import json
import socket
import struct
import threading
from pathlib import Path

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeObs:
    def __init__(self, password="obs-pass", folder="."):
        self.password, self.folder = password, Path(folder)
        self.scenes, self.current, self.inputs = ["Main", "Gaming"], "Main", {}
        self.recording = self.streaming = False
        self.requests = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    @staticmethod
    def _send(conn, obj):
        data = json.dumps(obj).encode()
        n = len(data)
        head = b"\x81" + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n))
        conn.sendall(head + data)

    @staticmethod
    def _recv(conn, buf):
        def read(k):
            while len(buf[0]) < k:
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError
                buf[0] += chunk
            out, buf[0] = buf[0][:k], buf[0][k:]
            return out
        b1, b2 = read(2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", read(2))[0]
        mask = read(4)
        data = bytes(x ^ mask[i % 4] for i, x in enumerate(read(n)))
        return b1 & 0x0F, data

    def _handle(self, conn):
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(4096)
        head, rest = head.split(b"\r\n\r\n", 1)
        key = next(ln.split(":", 1)[1].strip() for ln in head.decode().split("\r\n") if ln.lower().startswith("sec-websocket-key"))
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        conn.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n"
                     "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n".encode())
        buf = [rest]
        salt, challenge = "s4lt", "ch4llenge"
        self._send(conn, {"op": 0, "d": {"obsWebSocketVersion": "5.5.6", "rpcVersion": 1, "authentication": {"challenge": challenge, "salt": salt}}})
        try:
            _, data = self._recv(conn, buf)
            ident = json.loads(data)["d"]
            secret = base64.b64encode(hashlib.sha256((self.password + salt).encode()).digest()).decode()
            want = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
            if ident.get("authentication") != want:
                conn.sendall(b"\x88\x02" + struct.pack(">H", 4009))  # close: authentication failed
                conn.close()
                return
            self._send(conn, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
            while True:
                op, data = self._recv(conn, buf)
                if op == 8:
                    conn.close()
                    return
                d = json.loads(data)["d"]
                self.requests.append(d["requestType"])
                ok, res = self._answer(d["requestType"], d.get("requestData") or {})
                self._send(conn, {"op": 7, "d": {"requestType": d["requestType"], "requestId": d["requestId"],
                                                 "requestStatus": {"result": ok, "code": 100 if ok else 600, "comment": "" if ok else "not found"}, "responseData": res}})
        except (ConnectionError, OSError):
            conn.close()

    def _answer(self, kind, d):
        if kind == "GetSceneList":
            return True, {"currentProgramSceneName": self.current, "scenes": [{"sceneName": s, "sceneIndex": i} for i, s in enumerate(reversed(self.scenes))]}
        if kind == "GetCurrentProgramScene":
            return True, {"currentProgramSceneName": self.current, "sceneName": self.current}
        if kind == "SetCurrentProgramScene":
            if d["sceneName"] not in self.scenes:
                return False, {}
            self.current = d["sceneName"]
            return True, {}
        if kind == "CreateScene":
            self.scenes.append(d["sceneName"])
            return True, {"sceneUuid": "x"}
        if kind == "CreateInput":
            if d["sceneName"] not in self.scenes:
                return False, {}
            self.inputs[d["inputName"]] = dict(d)
            return True, {"sceneItemId": len(self.inputs)}
        if kind == "GetInputSettings":
            return True, {"inputSettings": self.inputs[d["inputName"]]["inputSettings"], "inputKind": self.inputs[d["inputName"]]["inputKind"]}
        if kind == "StartRecord":
            self.recording = True
            return True, {}
        if kind == "GetRecordStatus":
            return True, {"outputActive": self.recording}
        if kind == "StopRecord":
            self.recording = False
            p = self.folder / "2026-10-04 17-30-00.mkv"
            p.write_bytes(b"\x1aE\xdf\xa3 fake recording")
            return True, {"outputPath": str(p)}
        if kind in ("StartStream", "StopStream"):
            self.streaming = kind == "StartStream"
            return True, {}
        if kind == "GetStreamStatus":
            return True, {"outputActive": self.streaming}
        if kind == "SaveSourceScreenshot":
            from PIL import Image
            Image.new("RGB", (1280, 720), "black").save(d["imageFilePath"])
            return True, {}
        return False, {}


class FakeGoogle:
    """Google Docs, Slides and Forms APIs: create, batchUpdate (the requests applied), get."""

    def __init__(self):
        self.sent, self.docs, self.decks, self.forms, self.n = [], {}, {}, {}, 0

    @staticmethod
    def js(status, body):
        return status, {"Content-Type": "application/json"}, json.dumps(body).encode()

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url})
        if headers.get("Authorization") != "Bearer g-token":
            return self.js(401, {"error": {"code": 401, "message": "Request had invalid authentication credentials."}})
        b = json.loads(data) if data else {}
        path = url.split("googleapis.com/v1/", 1)[1]
        self.n += 1
        if url.startswith("https://docs."):
            if path == "documents":
                did = f"doc{self.n}"
                self.docs[did] = {"title": b["title"], "text": "\n", "styles": []}
                return self.js(200, {"documentId": did, "title": b["title"]})
            did, _, act = path.partition(":")
            did = did.split("/")[1]
            if act == "batchUpdate":
                d = self.docs[did]
                for r in b["requests"]:
                    if "insertText" in r:
                        i = r["insertText"]["location"]["index"] - 1
                        d["text"] = d["text"][:i] + r["insertText"]["text"] + d["text"][i:]
                    else:
                        d["styles"].append(r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"])
                return self.js(200, {"replies": [{} for _ in b["requests"]]})
            d = self.docs[did]
            return self.js(200, {"documentId": did, "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": ln + "\n"}}]}}
                                                                         for ln in d["text"].split("\n")]}})
        if url.startswith("https://slides."):
            if path == "presentations":
                pid = f"deck{self.n}"
                self.decks[pid] = {"title": b["title"], "slides": [{"objectId": "p", "pageElements": [
                    {"objectId": "t0", "shape": {"placeholder": {"type": "CENTERED_TITLE"}}}, {"objectId": "s0", "shape": {"placeholder": {"type": "SUBTITLE"}}}]}],
                    "texts": {}}
                return self.js(200, dict(presentationId=pid, **self.decks[pid]))
            pid, _, act = path.partition(":")
            pid = pid.split("/")[1]
            deck = self.decks[pid]
            if act == "batchUpdate":
                ids = {e["objectId"] for s in deck["slides"] for e in s["pageElements"]}
                for r in b["requests"]:
                    if "createSlide" in r:
                        cs = r["createSlide"]
                        deck["slides"].append({"objectId": cs["objectId"], "pageElements": [{"objectId": m["objectId"]} for m in cs["placeholderIdMappings"]]})
                        ids |= {m["objectId"] for m in cs["placeholderIdMappings"]}
                    elif "insertText" in r:
                        if r["insertText"]["objectId"] not in ids:
                            return self.js(400, {"error": {"code": 400, "message": "The object could not be found."}})
                        deck["texts"][r["insertText"]["objectId"]] = r["insertText"]["text"]
                return self.js(200, {"replies": []})
            return self.js(200, dict(presentationId=pid, **deck))
        if path == "forms":
            fid = f"form{self.n}"
            self.forms[fid] = {"formId": fid, "info": b["info"], "items": [], "settings": {}, "responderUri": f"https://docs.google.com/forms/d/e/{fid}/viewform"}
            return self.js(200, {"formId": fid, "info": b["info"], "responderUri": self.forms[fid]["responderUri"]})
        fid, _, act = path.partition(":")
        fid = fid.split("/")[1]
        f = self.forms[fid]
        if act == "batchUpdate":
            for r in b["requests"]:
                if "updateSettings" in r:
                    f["settings"].update(r["updateSettings"]["settings"])
                else:
                    q = r["createItem"]["item"]["questionItem"]["question"]
                    if not q.get("grading", {}).get("correctAnswers", {}).get("answers"):
                        return self.js(400, {"error": {"code": 400, "message": "A graded question needs a correct answer."}})
                    f["items"].insert(r["createItem"]["location"]["index"], r["createItem"]["item"])
            return self.js(200, {"replies": []})
        return self.js(200, f)


class FakeGitHub:
    """GitHub's REST API: the user, repositories (each backed by a real local bare git repository, so a push really
    happens), the latest commit of a branch, issues."""

    def __init__(self, folder):
        self.folder, self.sent, self.repos, self.issues = Path(folder), [], {}, {}

    @staticmethod
    def js(status, body):
        return status, {"Content-Type": "application/json"}, json.dumps(body).encode()

    def send(self, method, url, headers, data, timeout):
        import re
        import subprocess
        self.sent.append({"method": method, "url": url})
        if headers.get("Authorization") != "Bearer gh-token":
            return self.js(401, {"message": "Bad credentials"})
        path = url.split("api.github.com/", 1)[1].split("?")[0]
        b = json.loads(data) if data else {}
        if path == "user":
            return self.js(200, {"login": "ayesha"})
        if path == "user/repos" and method == "GET":
            return self.js(200, list(self.repos.values()))
        if path == "user/repos":
            if b["name"] in self.repos:
                return self.js(422, {"message": "Repository creation failed.", "errors": [{"message": "name already exists on this account"}]})
            bare = self.folder / f"{b['name']}.git"
            subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.repos[b["name"]] = {"name": b["name"], "full_name": f"ayesha/{b['name']}", "private": b["private"], "html_url": f"https://github.com/ayesha/{b['name']}",
                                     "clone_url": str(bare), "updated_at": "2026-10-04T12:00:00Z"}
            return self.js(201, self.repos[b["name"]])
        m = re.fullmatch(r"repos/ayesha/([\w.-]+)(?:/(commits|issues)(?:/(.+))?)?", path)
        if not m or m.group(1) not in self.repos:
            return self.js(404, {"message": "Not Found"})
        r = self.repos[m.group(1)]
        if not m.group(2):
            return self.js(200, r)
        if m.group(2) == "commits":
            p = subprocess.run(["git", "--git-dir", r["clone_url"], "rev-parse", f"refs/heads/{m.group(3)}"], capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return self.js(200, {"sha": p.stdout.strip()}) if p.returncode == 0 else self.js(404, {"message": "No commit found"})
        lst = self.issues.setdefault(m.group(1), [])
        if method == "POST":
            lst.append({"number": len(lst) + 1, "title": b["title"], "body": b.get("body"), "html_url": f"{r['html_url']}/issues/{len(lst) + 1}"})
            return self.js(201, lst[-1])
        return self.js(200, lst)


def _js(status, body):
    return status, {"Content-Type": "application/json"}, json.dumps(body).encode()


class FakeSpotify:
    """Spotify Web API: search, the user, playlists and their tracks, now playing, top tracks."""
    CATALOG = {("blinding lights", "the weeknd"): "0VjIjW4GlUZAMYd2vXMi3b", ("shape of you", "ed sheeran"): "7qiZfU4dY1lWllzX7mPBI3"}

    def __init__(self):
        self.sent, self.playlists = [], {}

    def send(self, method, url, headers, data, timeout):
        import urllib.parse as up
        self.sent.append({"method": method, "url": url})
        if headers.get("Authorization") != "Bearer sp-token":
            return _js(401, {"error": {"status": 401, "message": "Invalid access token"}})
        u = up.urlparse(url)
        q = {k: v[0] for k, v in up.parse_qs(u.query).items()}
        path = u.path.split("/v1/", 1)[1]
        b = json.loads(data) if data else {}
        if path == "me":
            return _js(200, {"id": "ayesha", "display_name": "Ayesha"})
        if path == "search":
            import re
            m = re.match(r"track:(.+) artist:(.+)", q["q"])
            key = (m.group(1).lower(), m.group(2).lower()) if m else None
            tid = self.CATALOG.get(key)
            items = [{"uri": f"spotify:track:{tid}", "name": key[0].title(), "artists": [{"name": key[1].title()}]}] if tid else []
            return _js(200, {"tracks": {"items": items}})
        if path == "users/ayesha/playlists":
            pid = f"pl{len(self.playlists) + 1}"
            self.playlists[pid] = {"id": pid, "name": b["name"], "public": b["public"], "uris": [], "external_urls": {"spotify": f"https://open.spotify.com/playlist/{pid}"}}
            return _js(201, self.playlists[pid])
        if path.startswith("playlists/") and path.endswith("/tracks"):
            p = self.playlists[path.split("/")[1]]
            if method == "POST":
                p["uris"] += b["uris"]
                return _js(201, {"snapshot_id": "s1"})
            return _js(200, {"total": len(p["uris"])})
        if path == "me/player/currently-playing":
            return 204, {}, b""
        if path == "me/top/tracks":
            return _js(200, {"items": [{"name": "Blinding Lights", "artists": [{"name": "The Weeknd"}]}]})
        return _js(404, {"error": {"status": 404, "message": "not found"}})


class FakeSalesforce:
    INSTANCE = "https://khan.my.salesforce.com"

    def __init__(self):
        self.sent, self.leads = [], {}
        self.session = "sf-token"

    def send(self, method, url, headers, data, timeout):
        import urllib.parse as up
        self.sent.append({"method": method, "url": url})
        if url.startswith("https://login.salesforce.com/services/oauth2/token"):
            self.session = "sf-token-2"
            return _js(200, {"access_token": self.session, "instance_url": self.INSTANCE})
        if headers.get("Authorization") != f"Bearer {self.session}":
            return _js(401, [{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}])
        u = up.urlparse(url)
        path = u.path
        if path == "/services/data/":
            return _js(200, [{"version": "61.0", "url": "/services/data/v61.0"}, {"version": "65.0", "url": "/services/data/v65.0"}])
        if not path.startswith("/services/data/v65.0/"):
            return _js(404, [{"message": "wrong version", "errorCode": "NOT_FOUND"}])
        rest = path.split("/v65.0/", 1)[1]
        if rest == "sobjects/Lead" and method == "POST":
            b = json.loads(data)
            if not b.get("LastName") or not b.get("Company"):
                return _js(400, [{"message": "Required fields are missing: [LastName, Company]", "errorCode": "REQUIRED_FIELD_MISSING"}])
            lid = f"00Q{len(self.leads) + 1:012d}"
            self.leads[lid] = dict(b, Id=lid, Status="Open - Not Contacted", Name=f"{b.get('FirstName', '')} {b['LastName']}".strip())
            return _js(201, {"id": lid, "success": True, "errors": []})
        if rest.startswith("sobjects/Lead/"):
            return _js(200, self.leads[rest.rsplit("/", 1)[1]])
        if rest == "query":
            soql = up.parse_qs(u.query)["q"][0]
            if "GROUP BY Status" in soql:
                counts = {}
                for x in self.leads.values():
                    counts[x["Status"]] = counts.get(x["Status"], 0) + 1
                return _js(200, {"records": [{"Status": k, "n": v} for k, v in counts.items()]})
            if "FROM Lead" in soql:
                return _js(200, {"records": list(self.leads.values())})
            return _js(200, {"records": [{"Name": "Ali Traders - 20 TVs", "StageName": "Proposal", "Amount": 1700000, "CloseDate": "2026-10-31"}]})
        return _js(404, [{"message": "not found", "errorCode": "NOT_FOUND"}])


class FakeGraph:
    """Microsoft Graph: To Do lists and tasks, OneNote sections and pages."""

    def __init__(self):
        self.sent, self.tasks, self.pages = [], {}, []

    def send(self, method, url, headers, data, timeout):
        self.sent.append({"method": method, "url": url, "headers": headers})
        if headers.get("Authorization") != "Bearer ms-token":
            return _js(401, {"error": {"code": "InvalidAuthenticationToken"}})
        path = url.split("/v1.0/", 1)[1].split("?")[0]
        if path == "me/todo/lists":
            return _js(200, {"value": [{"id": "L1", "displayName": "Tasks", "wellknownListName": "defaultList"}, {"id": "L2", "displayName": "Shop", "wellknownListName": "none"}]})
        if path == "me/todo/lists/L1/tasks" and method == "POST":
            b = json.loads(data)
            tid = f"T{len(self.tasks) + 1}"
            self.tasks[tid] = dict(b, id=tid, status="notStarted")
            return _js(201, self.tasks[tid])
        if path == "me/todo/lists/L1/tasks":
            return _js(200, {"value": list(self.tasks.values())})
        if path.startswith("me/todo/lists/L1/tasks/"):
            t = self.tasks[path.rsplit("/", 1)[1]]
            if method == "PATCH":
                t.update(json.loads(data))
            return _js(200, t)
        if path == "me/onenote/sections":
            return _js(200, {"value": [{"id": "S1", "displayName": "Work"}, {"id": "S2", "displayName": "Home"}]})
        if path == "me/onenote/sections/S1/pages":
            if headers.get("Content-Type") != "text/html" or b"<title>" not in data:
                return _js(400, {"error": {"code": "20112", "message": "Invalid page HTML"}})
            self.pages.append(data.decode())
            return _js(201, {"id": "P1", "links": {"oneNoteWebUrl": {"href": "https://onenote.example/P1"}}})
        return _js(404, {"error": {"code": "itemNotFound"}})
