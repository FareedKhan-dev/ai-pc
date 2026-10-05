"""Spotify (Web API) with your own Spotify app (developer.spotify.com, free; sign-in once with PKCE, no secret): a playlist
made from song names (each found by title and artist, added, and the playlist read back), what is playing now, and your
top tracks. Playlists are made private.

  "spotify playlist 'Road trip': Blinding Lights by The Weeknd; Shape of You by Ed Sheeran; Tum Hi Ho by Arijit Singh"
  "what's playing on spotify"   'my top spotify songs'
"""
import base64
import hashlib
import http.server
import re
import secrets
import threading
import time
import urllib.parse
import webbrowser

from ..hub import vault
from ..hub.http import Api, HubError

NAME, LABEL = "spotify", "Spotify: playlists from song names, now playing, top tracks"
EXAMPLES = ["spotify playlist 'Road trip': Blinding Lights by The Weeknd; Shape of You by Ed Sheeran", "what's playing on spotify"]
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private user-read-currently-playing user-top-read"
APP = {"label": "Spotify", "fields": [("client_id", "Client ID of your Spotify app", False)],
       "steps": ["developer.spotify.com/dashboard > Create app: any name, Redirect URI http://127.0.0.1:8888/callback, tick Web API; Save.",
                 "Copy the Client ID (no secret is needed), run 'apps.py connect spotify' and allow the app in the browser."],
       "notes": "A Spotify app in development mode works for you (and up to 25 people you add); Spotify accepts 127.0.0.1, not 'localhost', as the address."}


def _token(form, transport=None):
    try:
        return Api("https://accounts.spotify.com", service="spotify sign-in", transport=transport).request(
            "POST", "api/token", data=urllib.parse.urlencode(form).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, retries=1)
    except HubError as e:
        raise RuntimeError(f"Spotify refused the sign-in ({e}); run 'apps.py connect spotify' again") from e


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport = creds, transport

    def token(self):
        c = self.c
        if c.get("access_token") and c.get("expires_at", 0) > time.time() + 60:
            return c["access_token"]
        tok = _token({"grant_type": "refresh_token", "refresh_token": c["refresh_token"], "client_id": c["client_id"]}, self.transport)
        c.update(access_token=tok["access_token"], refresh_token=tok.get("refresh_token") or c["refresh_token"], expires_at=time.time() + int(tok.get("expires_in", 3600)))
        if self.transport is None:
            vault.put(NAME, {k: c[k] for k in ("access_token", "refresh_token", "expires_at")})
        return c["access_token"]

    def call(self, method, path, body=None, params=None):
        try:
            return Api("https://api.spotify.com/v1", headers={"Authorization": f"Bearer {self.token()}"}, service="spotify", transport=self.transport).request(
                method, path, json_body=body, params=params, retries=0 if method == "POST" else 3)
        except HubError as e:
            raise RuntimeError(f"Spotify: {e}") from e

    def find(self, song):
        m = re.match(r"(.+?)\s+by\s+(.+)$", song, re.I)
        q = f"track:{m.group(1)} artist:{m.group(2)}" if m else song
        items = self.call("GET", "search", params={"q": q, "type": "track", "limit": 1}).get("tracks", {}).get("items") or []
        return items[0] if items else None

    def playlist(self, name, songs):
        me = self.call("GET", "me")["id"]
        found = [(s, self.find(s)) for s in songs]
        uris = [t["uri"] for _, t in found if t]
        p = self.call("POST", f"users/{me}/playlists", {"name": name, "public": False, "description": "Made by AI PC"})
        if uris:
            self.call("POST", f"playlists/{p['id']}/tracks", {"uris": uris})
        total = self.call("GET", f"playlists/{p['id']}/tracks", params={"fields": "total"}).get("total")
        return p, found, total

    def now(self):
        r = self.call("GET", "me/player/currently-playing")
        return r.get("item") if r else None

    def top(self):
        return self.call("GET", "me/top/tracks", params={"limit": 10, "time_range": "short_term"}).get("items") or []


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Spotify is not connected: 'apps.py steps spotify' shows how")
    return Client(c)


def connect(values, transport=None, store=None, open_url=webbrowser.open, show=print, timeout=300):
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, got = secrets.token_urlsafe(16), {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            got.update({k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Signed in to Spotify. You can close this tab.</h2>")

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
    srv.timeout = 0.5
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({"client_id": values["client_id"], "response_type": "code", "redirect_uri": REDIRECT,
                                                                             "scope": SCOPES, "state": state, "code_challenge_method": "S256",
                                                                             "code_challenge": challenge})
    show(f"Allow the app in Spotify (opening it; or paste this link):\n{url}")
    threading.Thread(target=lambda: open_url(url), daemon=True).start()
    t0 = time.time()
    while "code" not in got and "error" not in got and time.time() - t0 < timeout:
        srv.handle_request()
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError(f"Spotify sign-in did not finish ({got.get('error', 'timed out')})")
    tok = _token({"grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT, "client_id": values["client_id"], "code_verifier": verifier},
                 transport)
    creds = {"client_id": values["client_id"], "access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
             "expires_at": time.time() + int(tok.get("expires_in", 3600))}
    (store or (lambda v: vault.put(NAME, v)))(creds)
    return {"who": Client(creds, transport).call("GET", "me").get("display_name"), "where": "Spotify"}


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bspotify\b", c):
        return None
    m = re.search(r"\bspotify\s+playlist\s+['\"]([^'\"]+)['\"]\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        return {"op": "playlist", "name": m.group(1), "songs": [s.strip() for s in re.split(r";|\n", m.group(2)) if s.strip()]}
    if re.search(r"\b(?:playing|listening)\b", c):
        return {"op": "now"}
    if re.search(r"\btop\b", c):
        return {"op": "top"}
    return None


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "now":
        t = c.now()
        return f"Playing on Spotify: {t['name']} by {', '.join(a['name'] for a in t['artists'])}." if t else "Nothing is playing on Spotify right now."
    if op["op"] == "top":
        ts = c.top()
        return "Your top songs lately:\n" + "\n".join(f"{i}. {t['name']} by {', '.join(a['name'] for a in t['artists'])}" for i, t in enumerate(ts, 1)) if ts else "No top songs yet."
    p, found, total = c.playlist(op["name"], op["songs"])
    missing = [s for s, t in found if not t]
    ok = total == len(found) - len(missing)
    return (f"Spotify playlist '{op['name']}' (private): {len(found) - len(missing)} of {len(found)} songs added" +
            (f"; not found: {', '.join(missing)}" if missing else "") + f" ({'read back: ' + str(total) + ' songs' if ok else 'NOT as asked when read back'}). "
            f"{(p.get('external_urls') or {}).get('spotify', '')}")
