"""Signing in to the services that use OAuth, and keeping the access token fresh (all tokens live in the vault):

  google_signin(client_id, client_secret)    the person signs in once in their browser; a loopback page on 127.0.0.1 takes
                                             the answer (PKCE, so the code is useless to anyone else); keeps a refresh token
  microsoft_signin(client_id, show)          a device code: the person opens microsoft.com/devicelogin and types the code shown
  canva_signin(client_id, client_secret)     like Google, on the fixed address the Canva integration lists (127.0.0.1:3001/oauth/redirect)
  access_token(service)                      a valid token for google / microsoft / zoom / canva, refreshed when it is about to expire
"""
import base64
import hashlib
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser

from . import vault
from .http import Api, HubError

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = ["openid", "email", "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar.events",
                 "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/spreadsheets",
                 "https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/presentations",
                 "https://www.googleapis.com/auth/forms.body"]  # Docs, Slides and Forms (apps lane)
MS_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0"
MS_SCOPES = ["User.Read", "Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "Tasks.ReadWrite", "Notes.ReadWrite", "offline_access"]
MS_TEAMS_SCOPES = ["Chat.ReadWrite", "ChannelMessage.Send", "Team.ReadBasic.All", "Channel.ReadBasic.All"]
ZOOM_TOKEN = "https://zoom.us/oauth/token"
CANVA_AUTH = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN = "https://api.canva.com/rest/v1/oauth/token"
CANVA_SCOPES = ["profile:read", "design:meta:read", "design:content:read", "design:content:write", "asset:read", "asset:write", "folder:read"]
CANVA_REDIRECT = ("127.0.0.1", 3001, "/oauth/redirect")  # what the integration's settings in the Canva Developer Portal must list


def _form(d):
    return urllib.parse.urlencode(d).encode()


def _token_call(url, form, transport=None):
    api = Api(url, service="sign-in", transport=transport)
    return api.request("POST", url, data=_form(form), headers={"Content-Type": "application/x-www-form-urlencoded"})


# ---------------------------------------------------------------- Google: loopback + PKCE
def google_signin(client_id, client_secret, scopes=None, open_url=webbrowser.open, show=print, timeout=300, transport=None):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in got and got.get("state") == state
            self.wfile.write(("<h2>Signed in. You can close this tab and go back to the AI PC.</h2>" if ok else
                              "<h2>Sign-in did not finish. Go back to the AI PC and try again.</h2>").encode())

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)  # only this PC can reach it
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = GOOGLE_AUTH + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(scopes or GOOGLE_SCOPES),
        "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent", "state": state})
    show(f"Sign in to Google in your browser (opening it now). If it does not open, paste this link into it:\n{url}")
    threading.Thread(target=lambda: open_url(url), daemon=True).start()
    srv.timeout = 1
    t0 = time.time()
    while "code" not in got and "error" not in got and time.time() - t0 < timeout:
        srv.handle_request()
    srv.server_close()
    if got.get("error") or "code" not in got:
        raise HubError(f"Google sign-in did not finish ({got.get('error', 'timed out')})")
    if got.get("state") != state:
        raise HubError("Google sign-in answered with the wrong state; try again")
    tok = _token_call(GOOGLE_TOKEN, {"code": got["code"], "client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect,
                                      "grant_type": "authorization_code", "code_verifier": verifier}, transport)
    vault.put("google", {"client_id": client_id, "client_secret": client_secret, "refresh_token": tok.get("refresh_token", ""),
                         "access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60})
    return tok


# ---------------------------------------------------------------- Canva: loopback + PKCE on a fixed address
def _loopback(build_url, host="127.0.0.1", port=0, path="/", show=print, open_url=webbrowser.open, timeout=300, who="the service"):
    """Open the sign-in page; a one-request server on this PC takes the answer. -> (query dict, redirect URL, state)."""
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
    srv = http.server.HTTPServer((host, port), Handler)  # only this PC can reach it
    redirect = f"http://{host}:{srv.server_port}{path}"
    url = build_url(redirect, state)
    show(f"Sign in to {who} in your browser (opening it now). If it does not open, paste this link into it:\n{url}")
    threading.Thread(target=lambda: open_url(url), daemon=True).start()
    srv.timeout = 1
    t0 = time.time()
    while "code" not in got and "error" not in got and time.time() - t0 < timeout:
        srv.handle_request()
    srv.server_close()
    if got.get("error") or "code" not in got:
        raise HubError(f"{who} sign-in did not finish ({got.get('error_description') or got.get('error', 'timed out')})")
    if got.get("state") != state:
        raise HubError(f"{who} sign-in answered with the wrong state; try again")
    return got, redirect


def canva_signin(client_id, client_secret, scopes=None, open_url=webbrowser.open, show=print, timeout=300, transport=None):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    host, port, path = CANVA_REDIRECT

    def build(redirect, state):
        return CANVA_AUTH + "?" + urllib.parse.urlencode({"client_id": client_id, "response_type": "code", "scope": " ".join(scopes or CANVA_SCOPES),
                                                          "code_challenge": challenge, "code_challenge_method": "s256", "state": state,
                                                          "redirect_uri": redirect})
    got, redirect = _loopback(build, host, port, path, show=show, open_url=open_url, timeout=timeout, who="Canva")
    tok = _canva_token({"grant_type": "authorization_code", "code": got["code"], "code_verifier": verifier, "redirect_uri": redirect},
                       client_id, client_secret, transport)
    vault.put("canva", {"client_id": client_id, "client_secret": client_secret, "refresh_token": tok.get("refresh_token", ""),
                        "access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in", 14400)) - 120})
    return tok


def _canva_token(form, client_id, client_secret, transport=None):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    api = Api(CANVA_TOKEN, service="sign-in", transport=transport)
    return api.request("POST", CANVA_TOKEN, data=_form(form), headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"})


# ---------------------------------------------------------------- Microsoft: device code
def microsoft_signin(client_id, teams=False, show=print, timeout=900, transport=None):
    scopes = MS_SCOPES + (MS_TEAMS_SCOPES if teams else [])
    dc = _token_call(f"{MS_BASE}/devicecode", {"client_id": client_id, "scope": " ".join(scopes)}, transport)
    show(dc.get("message") or f"Open {dc['verification_uri']} and type the code {dc['user_code']}")
    t0, every = time.time(), int(dc.get("interval", 5))
    while time.time() - t0 < min(timeout, int(dc.get("expires_in", 900))):
        time.sleep(every)
        try:
            tok = _token_call(f"{MS_BASE}/token", {"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": client_id,
                                                   "device_code": dc["device_code"]}, transport)
        except HubError as e:
            err = (e.body or {}).get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                every += 5
                continue
            raise HubError(f"Microsoft sign-in stopped: {err or e}")
        vault.put("microsoft", {"client_id": client_id, "refresh_token": tok.get("refresh_token", ""), "access_token": tok["access_token"],
                                "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60, "scopes": " ".join(scopes)})
        return tok
    raise HubError("Microsoft sign-in timed out")


# ---------------------------------------------------------------- fresh tokens
def access_token(service, transport=None):
    c = vault.get(service) or {}
    if service == "zoom":
        if c.get("access_token") and c.get("expires_at", 0) > time.time():
            return c["access_token"]
        if not (c.get("account_id") and c.get("client_id") and c.get("client_secret")):
            raise HubError("Zoom is not connected: run hub.py connect zoom")
        basic = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
        api = Api(ZOOM_TOKEN, service="zoom", transport=transport)
        tok = api.request("POST", f"{ZOOM_TOKEN}?grant_type=account_credentials&account_id={urllib.parse.quote(c['account_id'])}",
                          headers={"Authorization": f"Basic {basic}"})
        vault.put("zoom", {"access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60})
        return tok["access_token"]
    if c.get("access_token") and c.get("expires_at", 0) > time.time():
        return c["access_token"]
    if not c.get("refresh_token"):
        raise HubError(f"{service.title()} is not signed in: run hub.py connect {service}")
    if service == "google":
        tok = _token_call(GOOGLE_TOKEN, {"client_id": c["client_id"], "client_secret": c["client_secret"], "refresh_token": c["refresh_token"],
                                         "grant_type": "refresh_token"}, transport)
    elif service == "microsoft":
        tok = _token_call(f"{MS_BASE}/token", {"client_id": c["client_id"], "refresh_token": c["refresh_token"], "grant_type": "refresh_token",
                                               "scope": c.get("scopes") or " ".join(MS_SCOPES)}, transport)
    elif service == "canva":  # Canva's refresh tokens are used once: the new one is kept
        tok = _canva_token({"grant_type": "refresh_token", "refresh_token": c["refresh_token"]}, c["client_id"], c["client_secret"], transport)
    else:
        raise HubError(f"no sign-in for {service}")
    upd = {"access_token": tok["access_token"], "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60}
    if tok.get("refresh_token"):
        upd["refresh_token"] = tok["refresh_token"]
    vault.put(service, upd)
    return tok["access_token"]
