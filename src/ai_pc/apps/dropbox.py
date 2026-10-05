"""Dropbox (API v2): files uploaded into an 'AI PC' folder (checked with Dropbox's own content hash), folders listed,
and a share link made after a yes (anyone with the link can open the file). Sign-in once with a code pasted from the
browser (PKCE, no secret, no web address of yours); the refresh token is kept encrypted.

  'upload invoice.pdf to dropbox'   'dropbox files'   'share link for /AI PC/invoice.pdf on dropbox'
"""

import base64
import hashlib
import json
import re
import secrets
import time
import urllib.parse
from pathlib import Path

from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

NAME, LABEL = "dropbox", "Dropbox: upload (hash-checked), list, share links"
EXAMPLES = ["upload invoice.pdf to dropbox", "dropbox files", "share link for /AI PC/invoice.pdf on dropbox"]
OUTWARD = {"upload", "share"}
APP = {
    "label": "Dropbox",
    "fields": [("client_id", "App key of your Dropbox app", False)],
    "steps": [
        "Open https://www.dropbox.com/developers/apps > Create app > Scoped access > App folder (or Full Dropbox) > name it.",
        "Permissions tab: tick files.content.write, files.content.read, sharing.write; Submit. Copy the App key (Settings).",
        "Run 'ai-pc apps connect dropbox': a Dropbox page opens; allow, copy the code it shows and paste it here.",
    ],
}


def content_hash(path):
    """Dropbox's content hash: SHA-256 of each 4 MB block, then SHA-256 of those digests."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(hashlib.sha256(block).digest())
    return h.hexdigest()


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport = creds, transport

    def token(self):
        c = self.c
        if c.get("access_token") and c.get("expires_at", 0) > time.time() + 120:
            return c["access_token"]
        r = Api("https://api.dropboxapi.com", service="dropbox sign-in", transport=self.transport).request(
            "POST",
            "oauth2/token",
            data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": c["refresh_token"], "client_id": c["client_id"]}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        c.update(access_token=r["access_token"], expires_at=time.time() + int(r.get("expires_in") or 14400))
        return c["access_token"]

    def rpc(self, path, body):
        try:
            return Api(
                "https://api.dropboxapi.com/2", headers={"Authorization": f"Bearer {self.token()}"}, service="dropbox", transport=self.transport
            ).request("POST", path, json_body=body, retries=0 if "create" in path else 3)
        except HubError as e:
            b = e.body if isinstance(e.body, dict) else {}
            raise RuntimeError(f"Dropbox: {b.get('error_summary') or e}") from e

    def upload(self, path, dest):
        p = Path(path)
        if p.stat().st_size > 150 * 1024 * 1024:
            raise RuntimeError("files over 150 MB need Dropbox's upload sessions (not set up here yet)")
        arg = json.dumps({"path": dest, "mode": "add", "autorename": True, "mute": False})
        try:
            return Api(
                "https://content.dropboxapi.com/2", headers={"Authorization": f"Bearer {self.token()}"}, service="dropbox", transport=self.transport
            ).request(
                "POST", "files/upload", data=p.read_bytes(), headers={"Dropbox-API-Arg": arg, "Content-Type": "application/octet-stream"}, retries=0
            )
        except HubError as e:
            b = e.body if isinstance(e.body, dict) else {}
            raise RuntimeError(f"Dropbox: {b.get('error_summary') or e}") from e

    def list(self, folder=""):
        return self.rpc("files/list_folder", {"path": folder}).get("entries") or []

    def share(self, path):
        try:
            return self.rpc("sharing/create_shared_link_with_settings", {"path": path, "settings": {"requested_visibility": "public"}})["url"]
        except RuntimeError as e:
            if "shared_link_already_exists" in str(e):
                return self.rpc("sharing/list_shared_links", {"path": path, "direct_only": True})["links"][0]["url"]
            raise


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Dropbox is not connected: 'ai-pc apps steps dropbox' shows how")
    return Client(c)


def connect(values, transport=None, store=None, open_url=None, ask=input, show=print):
    import webbrowser

    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = "https://www.dropbox.com/oauth2/authorize?" + urllib.parse.urlencode(
        {
            "client_id": values["client_id"],
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "token_access_type": "offline",
        }
    )
    show(f"Allow the app in Dropbox (opening it; or paste this link):\n{url}")
    (open_url or webbrowser.open)(url)
    code = ask("Paste the code Dropbox shows: ").strip()
    r = Api("https://api.dropboxapi.com", service="dropbox sign-in", transport=transport).request(
        "POST",
        "oauth2/token",
        data=urllib.parse.urlencode(
            {"code": code, "grant_type": "authorization_code", "code_verifier": verifier, "client_id": values["client_id"]}
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    creds = {
        "client_id": values["client_id"],
        "refresh_token": r["refresh_token"],
        "access_token": r["access_token"],
        "expires_at": time.time() + int(r.get("expires_in") or 14400),
    }
    (store or (lambda v: vault.put(NAME, v)))(creds)
    return {"who": r.get("account_id"), "where": "Dropbox"}


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bdropbox\b", c):
        return None
    m = re.match(r"^\s*(?:upload|put|save|send)\s+(.+?)\s+(?:to|on|in)\s+(?:my\s+)?dropbox(?:\s+(?:folder\s+)?(/\S.*))?\s*$", text, re.I)
    if m:
        f = find_file(m.group(1), ctx) or (m.group(1).strip(" '\"") if Path(m.group(1).strip(" '\"")).is_file() else None)
        return {"op": "upload", "file": f, "folder": (m.group(2) or "/AI PC").rstrip("/")} if f else None
    m = re.search(r"\bshare(?:d)?\s+link\s+(?:for|to|of)\s+(/.+?)\s+(?:on|in)\s+dropbox\b", text, re.I)
    if m:
        return {"op": "share", "path": m.group(1).strip()}
    if re.search(r"\bfiles\b|\blist\b|\bwhat(?:'s| is) (?:on|in)\b", c):
        m = re.search(r"\b(?:in|folder)\s+(/\S.*?)\s*$", text)
        return {"op": "list", "folder": m.group(1).rstrip("/") if m else ""}
    return None


def preview(op, ctx):
    if op["op"] == "upload":
        return f"Ready to upload {Path(op['file']).name} ({Path(op['file']).stat().st_size / 1e6:.2f} MB) to Dropbox folder {op['folder']}."
    return f"Ready to make a share link for {op['path']}: anyone with the link can open it."


def run(op, ctx):
    cl = client(ctx)
    if op["op"] == "list":
        es = cl.list(op.get("folder", ""))
        return (
            "\n".join(f"- {e['name']}" + ("/" if e.get(".tag") == "folder" else f" ({e.get('size', 0) / 1e6:.2f} MB)") for e in es)
            or "The folder is empty."
        )
    if not op.get("confirmed"):
        return preview(op, ctx)
    if op["op"] == "upload":
        meta = cl.upload(op["file"], f"{op['folder']}/{Path(op['file']).name}")
        ok = meta.get("content_hash") == content_hash(op["file"])
        return (
            f"Uploaded to Dropbox: {meta['path_display']} ({'checked: Dropbox holds the same bytes' if ok else 'NOT the same bytes: upload again'})."
        )
    return f"Share link: {cl.share(op['path'])}"
