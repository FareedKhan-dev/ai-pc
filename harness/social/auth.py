"""Signing in to each platform once, from this PC, and keeping the sign-in fresh. Every platform uses OAuth 2.0 with a
loopback address (http://127.0.0.1:PORT, only this PC can reach it); each has its own rules, all from its docs:
  YouTube (Google)  any port; PKCE S256 (base64url); refresh tokens kept (a project left in 'Testing' loses them after 7 days)
  TikTok            fixed address http://127.0.0.1:3005/callback/; PKCE with a HEX SHA-256 challenge; refresh token for 365 days
  LinkedIn          fixed address http://127.0.0.1:3006/callback; no PKCE for self-serve apps; no refresh: 60 days, then sign in again
  X                 fixed address http://127.0.0.1:3007/callback (127.0.0.1, not localhost); public client with PKCE; refresh
                    tokens used once each (the new one is kept)
  Meta (Facebook + Instagram) and Threads: see META below.
Keys are typed at a hidden prompt and kept DPAPI-encrypted in the vault; tokens are never printed or logged.

  connect(name, values) -> {"who", "where", "warnings"}     fresh_token(platform) -> a valid access token
"""
import base64
import hashlib
import secrets
import time
import urllib.parse
import webbrowser

from ..hub import vault
from ..hub.http import Api, HubError
from ..hub.oauth import _form, _loopback
from .base import SocialError


def _verifier():
    return secrets.token_urlsafe(64)[:96]


def _s256(v):
    return base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def _hex256(v):
    return hashlib.sha256(v.encode()).hexdigest()  # TikTok's own variant


def _token(url, form, transport=None, basic=None):
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    if basic:
        h["Authorization"] = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
    try:
        return Api(url, service="sign-in", transport=transport).request("POST", url, data=_form(form), headers=h)
    except HubError as e:
        raise SocialError("auth", f"the sign-in was refused ({e})") from e


# ---------------------------------------------------------------- the platforms' sign-in rules
PROVIDERS = {
    "youtube": {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token", "port": 0, "path": "/",
                "scopes": ["https://www.googleapis.com/auth/youtube.force-ssl", "https://www.googleapis.com/auth/youtube.readonly",
                           "https://www.googleapis.com/auth/yt-analytics.readonly"], "sep": " ", "pkce": "s256", "id": "client_id",
                "extra": {"access_type": "offline", "prompt": "consent"}, "secret_in_body": True},
    "tiktok": {"auth": "https://www.tiktok.com/v2/auth/authorize/", "token": "https://open.tiktokapis.com/v2/oauth/token/", "port": 3005, "path": "/callback/",
               "scopes": ["user.info.basic", "user.info.profile", "user.info.stats", "video.upload", "video.publish", "video.list"], "sep": ",",
               "pkce": "hex", "id": "client_key", "secret_in_body": True},
    "linkedin": {"auth": "https://www.linkedin.com/oauth/v2/authorization", "token": "https://www.linkedin.com/oauth/v2/accessToken", "port": 3006,
                 "path": "/callback", "scopes": ["openid", "profile", "email", "w_member_social"], "sep": " ", "pkce": None, "id": "client_id",
                 "secret_in_body": True, "no_refresh": True},
    "x": {"auth": "https://x.com/i/oauth2/authorize", "token": "https://api.x.com/2/oauth2/token", "port": 3007, "path": "/callback",
          "scopes": ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access"], "sep": " ", "pkce": "s256", "id": "client_id",
          "public": True},
}


def signin(name, values, open_url=webbrowser.open, show=print, timeout=300, transport=None):
    """The browser sign-in: the platform sends the browser back to this PC with a code, exchanged for tokens here."""
    p = PROVIDERS[name]
    cid = values.get(p["id"]) or values.get("client_id")
    verifier = _verifier()

    def build(redirect, state):
        q = {"response_type": "code", "redirect_uri": redirect, "state": state, "scope": p["sep"].join(p["scopes"]), p["id"]: cid}
        if p["pkce"] == "s256":
            q.update(code_challenge=_s256(verifier), code_challenge_method="S256")
        elif p["pkce"] == "hex":
            q.update(code_challenge=_hex256(verifier), code_challenge_method="S256")
        q.update(p.get("extra") or {})
        return p["auth"] + "?" + urllib.parse.urlencode(q)
    try:
        got, redirect = _loopback(build, "127.0.0.1", p["port"], p["path"], show=show, open_url=open_url, timeout=timeout, who=name.title())
    except HubError as e:
        raise SocialError("auth", str(e)) from e
    form = {"grant_type": "authorization_code", "code": urllib.parse.unquote(got["code"]), "redirect_uri": redirect, p["id"]: cid}
    if p["pkce"]:
        form["code_verifier"] = verifier
    if p.get("secret_in_body") and values.get("client_secret"):
        form["client_secret"] = values["client_secret"]
    tok = _token(p["token"], form, transport)
    if not tok.get("access_token"):
        raise SocialError("auth", f"{name}: no token came back ({tok.get('error_description') or tok.get('error') or 'unknown'})")
    save(name, values, tok)
    return tok


def save(name, values, tok):
    upd = dict(values)
    upd.update(access_token=tok["access_token"], expires_at=time.time() + int(tok.get("expires_in") or 3600) - 60)
    if tok.get("refresh_token"):
        upd["refresh_token"] = tok["refresh_token"]
    if tok.get("refresh_expires_in"):
        upd["refresh_expires_at"] = time.time() + int(tok["refresh_expires_in"])
    for k in ("open_id", "scope", "id_token"):
        if tok.get(k):
            upd[k] = tok[k]
    vault.put(name, upd)
    return upd


def refresh(name, creds, transport=None):
    p = PROVIDERS[name]
    if p.get("no_refresh") or not creds.get("refresh_token"):
        raise SocialError("auth", f"{name.title()}: the sign-in has expired; run 'social.py connect {name}' (one click if you are still signed in)")
    form = {"grant_type": "refresh_token", "refresh_token": creds["refresh_token"], p["id"]: creds.get(p["id"]) or creds.get("client_id")}
    if p.get("secret_in_body") and creds.get("client_secret"):
        form["client_secret"] = creds["client_secret"]
    tok = _token(p["token"], form, transport)
    if not tok.get("access_token"):
        raise SocialError("auth", f"{name.title()}: the sign-in could not be renewed; run 'social.py connect {name}'")
    return save(name, {}, tok)


def fresh_token(plat):
    """A valid access token for a connector, renewed (and the renewal kept) when it is about to run out."""
    key = plat.vault_key or plat.name
    c = plat.creds
    early = RENEW_EARLY.get(key, 0) if time.time() - c.get("issued_at", time.time()) > 86400 else 0
    if c.get("access_token") and c.get("expires_at", 0) > time.time() + 60 + early:
        return c["access_token"]
    if key in PROVIDERS:
        upd = refresh(key, c, plat.transport)
    else:
        upd = META_REFRESH[key](c, plat.transport)
    plat.creds.update(upd)
    return plat.creds["access_token"]


# ---------------------------------------------------------------- Meta (Facebook Pages + Instagram) and Threads
# Meta's documented desktop sign-in is an embedded browser, and Threads refuses loopback and plain-http addresses, so the
# person makes a token in Meta's Graph API Explorer (documented for Page and Threads tokens) and pastes it here:
#   Facebook + Instagram: the user token is made long-lived (60 days, fb_exchange_token with the app secret); the Page's
#     own token from /me/accounts made with it never expires; Instagram uses the user token (Meta asks again every 60 days)
#   Threads: made long-lived (th_exchange_token), then renewed by itself (th_refresh_token) before its 60 days run out
#   Instagram with Instagram login (no Facebook Page): the dashboard's 'Generate token' (60 days), renewed by ig_refresh_token
GRAPH = "https://graph.facebook.com/v26.0"


def _meta_get(url, params, transport=None):
    try:
        return Api(url, service="meta sign-in", transport=transport).get(url, params=params)
    except HubError as e:
        raise SocialError("auth", f"Meta refused the token ({e})") from e


def meta_connect(values, open_url=None, show=print, transport=None):
    """values: app_id, app_secret, user_token (from Graph API Explorer), optional page (a name, when you run several Pages)."""
    long = _meta_get(f"{GRAPH}/oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": values["app_id"],
                                                     "client_secret": values["app_secret"], "fb_exchange_token": values["user_token"]}, transport)
    utok = long["access_token"]
    pages = _meta_get(f"{GRAPH}/me/accounts", {"fields": "id,name,access_token,tasks,instagram_business_account{id,username}", "access_token": utok},
                      transport).get("data") or []
    if not pages:
        raise SocialError("auth", "this Facebook account manages no Page (or the token lacks pages_show_list)")
    want = (values.get("page") or "").strip().lower()
    page = next((p for p in pages if want and want in p["name"].lower()), pages[0])
    ig = page.get("instagram_business_account") or {}
    upd = {"app_id": values["app_id"], "app_secret": values["app_secret"], "user_token": utok,
           "user_expires_at": time.time() + int(long.get("expires_in") or 60 * 86400), "page_id": page["id"], "page_name": page["name"],
           "page_token": page["access_token"], "ig_id": ig.get("id"), "ig_username": ig.get("username"), "ig_mode": "facebook",
           "pages": [{"id": p["id"], "name": p["name"]} for p in pages]}
    vault.put("meta", upd)
    warn = [f"Page '{page['name']}'" + (f" and Instagram @{ig.get('username')}" if ig else " (no Instagram professional account is linked to it)"),
            "Meta asks you to renew the Instagram sign-in every 60 days ('social.py connect instagram'); the Page's own token does not expire",
            "switch the Meta app to Live (App settings: privacy policy address, then App Mode: Live), or only you can see the Page posts"]
    if len(pages) > 1:
        warn.append("other Pages you manage: " + ", ".join(p["name"] for p in pages if p["id"] != page["id"]) + " (connect again with 'page' to switch)")
    return {"who": page["name"], "where": "Facebook Page" + (f" + Instagram @{ig.get('username')}" if ig else ""), "warnings": warn}


def threads_connect(values, open_url=None, show=print, transport=None):
    """values: app_secret (the Threads app secret), token (a Threads token from Graph API Explorer)."""
    long = _meta_get("https://graph.threads.net/access_token", {"grant_type": "th_exchange_token", "client_secret": values["app_secret"],
                                                                 "access_token": values["token"]}, transport)
    vault.put("threads", {"access_token": long["access_token"], "expires_at": time.time() + int(long.get("expires_in") or 60 * 86400) - 60,
                          "issued_at": time.time()})
    me = _meta_get("https://graph.threads.net/v1.0/me", {"fields": "id,username", "access_token": long["access_token"]}, transport)
    vault.put("threads", {"user_id": me.get("id")})
    return {"who": "@" + (me.get("username") or "?"), "where": "Threads", "warnings": ["the token renews itself before its 60 days run out"]}


def instagram_login_connect(values, open_url=None, show=print, transport=None):
    """Instagram without a Facebook Page: values: token (the dashboard's 'Generate token', already long-lived)."""
    me = _meta_get("https://graph.instagram.com/v26.0/me", {"fields": "user_id,username", "access_token": values["token"]}, transport)
    vault.put("meta", {"ig_mode": "instagram", "access_token": values["token"], "expires_at": time.time() + 59 * 86400, "issued_at": time.time(),
                       "ig_id": me.get("user_id") or me.get("id"), "ig_username": me.get("username")})
    return {"who": "@" + (me.get("username") or "?"), "where": "Instagram (Instagram login)",
            "warnings": ["with Instagram login, Meta allows no deleting and no video upload from this PC (videos go by a temporary web address)"]}


def _threads_refresh(c, transport=None):
    """Threads' long-lived token renewed (it must be at least a day old and not yet expired)."""
    if c.get("expires_at", 0) <= time.time():
        raise SocialError("auth", "the Threads token ran out; run 'social.py connect threads'")
    js = _meta_get("https://graph.threads.net/refresh_access_token", {"grant_type": "th_refresh_token", "access_token": c["access_token"]}, transport)
    upd = {"access_token": js["access_token"], "expires_at": time.time() + int(js.get("expires_in") or 60 * 86400) - 60, "issued_at": time.time()}
    vault.put("threads", upd)
    return upd


def _meta_refresh(c, transport=None):
    if c.get("ig_mode") == "instagram":
        if c.get("expires_at", 0) <= time.time():
            raise SocialError("auth", "the Instagram token ran out; run 'social.py connect instagram'")
        js = _meta_get("https://graph.instagram.com/refresh_access_token", {"grant_type": "ig_refresh_token", "access_token": c["access_token"]}, transport)
        upd = {"access_token": js["access_token"], "expires_at": time.time() + int(js.get("expires_in") or 60 * 86400) - 60, "issued_at": time.time()}
        vault.put("meta", upd)
        return upd
    raise SocialError("auth", "the Meta sign-in for Instagram has run out (Meta asks every 60 days): run 'social.py connect instagram'")


META_REFRESH = {"threads": _threads_refresh, "meta": _meta_refresh}
RENEW_EARLY = {"threads": 7 * 86400, "meta": 7 * 86400}  # long-lived tokens are renewed a week before they run out (after a day)


# ---------------------------------------------------------------- what the person does on each platform's site (social.py steps)
APPS = {
    "youtube": {
        "label": "YouTube", "fields": [("client_id", "OAuth client ID (....apps.googleusercontent.com)", False), ("client_secret", "OAuth client secret", True)],
        "steps": ["Open https://console.cloud.google.com and create a project named 'AI PC social'.",
                  "APIs & Services > Library: enable 'YouTube Data API v3' and 'YouTube Analytics API'.",
                  "Google Auth Platform > Branding: name AI PC and your email. Audience: External; add the Google account that owns your channel as a "
                  "test user, then press 'Publish app' (In production) so the sign-in does not expire every 7 days. Google will show 'Google hasn't "
                  "verified this app' when you sign in: press Advanced > Go to AI PC (it is your own app).",
                  "Google Auth Platform > Clients > Create client > Desktop app; copy the Client ID and Client secret.",
                  "Run 'social.py connect youtube' and paste them; a Google sign-in page opens once (choose the channel's account)."],
        "notes": "Free: 100 uploads a day. YouTube keeps videos uploaded through a new, unaudited Google project PRIVATE (they cannot be made "
                 "public); to post publicly, apply for YouTube's free API audit at https://support.google.com/youtube/contact/yt_api_form "
                 "(it asks for a privacy policy page). Until then uploads are private videos you can check."},
    "tiktok": {
        "label": "TikTok", "fields": [("client_key", "Client key", False), ("client_secret", "Client secret", True)],
        "steps": ["Open https://developers.tiktok.com, log in, then Manage apps > Connect an app; name it AI PC, pick a category, platform Desktop "
                  "(TikTok asks for a website address, a terms page and a privacy page: a free GitHub Pages site works).",
                  "Add the products Login Kit (Desktop redirect URI: http://127.0.0.1:3005/callback/) and Content Posting API (turn on Direct Post).",
                  "Scopes: user.info.basic, user.info.profile, user.info.stats, video.upload, video.publish, video.list.",
                  "Sandbox: create a sandbox and add your own TikTok account as a target user (no review needed).",
                  "Content Posting API asks you to verify the website address (a DNS record or a file) before it works.",
                  "Copy the Client key and Client secret, then run 'social.py connect tiktok'."],
        "notes": "TikTok audits apps before they may post publicly and does not audit personal tools, so the AI PC sends videos to your TikTok "
                 "inbox as drafts (you post them from the app in one tap) or posts them as private 'only me'. It cannot delete posts."},
    "linkedin": {
        "label": "LinkedIn", "fields": [("client_id", "Client ID", False), ("client_secret", "Primary Client Secret", True)],
        "steps": ["Open https://www.linkedin.com/developers/apps and click Create app (LinkedIn links every app to a LinkedIn Page: pick your "
                  "business page, or create one first); add a logo and agree.",
                  "Products: add 'Share on LinkedIn' and 'Sign In with LinkedIn using OpenID Connect' (granted at once, no review).",
                  "Auth: under Authorized redirect URLs add http://127.0.0.1:3006/callback; copy the Client ID and Primary Client Secret.",
                  "Run 'social.py connect linkedin' and paste them; a LinkedIn sign-in page opens once."],
        "notes": "Free. Posts go to your own profile (a company Page needs LinkedIn's Community Management API, which is for registered "
                 "businesses). The sign-in lasts 60 days, then one click renews it. LinkedIn gives personal apps no post statistics."},
    "facebook": {
        "label": "Facebook Page (and Instagram)", "fields": [("app_id", "Meta App ID", False), ("app_secret", "Meta App secret", True),
                                                             ("user_token", "User token from Graph API Explorer", True)],
        "steps": ["Open https://developers.facebook.com/apps and click Create app; name it AI PC; use cases: 'Manage everything on your Page' and "
                  "'Manage messaging & content on Instagram' (choose 'API setup with Facebook login').",
                  "App settings > Basic: copy the App ID and App secret; add a privacy policy address (any page of yours, e.g. a free GitHub Pages "
                  "page), then switch App Mode to Live (in Development mode only you can see the Page posts). You are the app's admin, so "
                  "no App Review is needed.",
                  "Open https://developers.facebook.com/tools/explorer, pick the AI PC app, and add the permissions pages_show_list, "
                  "pages_read_engagement, pages_manage_posts, pages_manage_engagement, pages_read_user_content, read_insights, "
                  "business_management, instagram_basic, instagram_content_publish, instagram_manage_comments, instagram_manage_insights, "
                  "instagram_manage_contents; click Generate Access Token and allow your Page (and its Instagram account).",
                  "Copy the token, then run 'social.py connect facebook' and paste the App ID, App secret and token. The token is made long-lived "
                  "here and the Page's own token (which does not expire) is taken from it."],
        "notes": "Free. Instagram needs a professional (business or creator) account linked to the Page. Instagram takes pictures only from a "
                 "web address: run 'social.py setup-tunnel' once (Cloudflare's free tunnel tool) so the AI PC can lend it one for a minute."},
    "instagram": {
        "label": "Instagram", "fields": [("app_id", "Meta App ID", False), ("app_secret", "Meta App secret", True),
                                         ("user_token", "User token from Graph API Explorer", True)],
        "steps": ["Instagram comes with Facebook: do 'social.py steps facebook' (one Meta app, one token covers both), then "
                  "'social.py connect instagram' with the same App ID, App secret and a fresh token.",
                  "Meta asks for a fresh token every 60 days for Instagram; the AI PC tells you a week before."],
        "notes": "Instagram allows 50 API posts in 24 hours. Pictures need 'social.py setup-tunnel' once (see Facebook's note)."},
    "threads": {
        "label": "Threads", "fields": [("app_secret", "Threads app secret", True), ("token", "Threads token from Graph API Explorer", True)],
        "steps": ["In your Meta app (https://developers.facebook.com/apps) add the use case 'Access the Threads API' with threads_basic, "
                  "threads_content_publish, threads_read_replies, threads_manage_replies, threads_manage_insights, threads_delete.",
                  "Use case settings: add your Threads profile as a Threads Tester, then accept it in Threads (Settings > Account > Website "
                  "permissions > Invites). Copy the Threads app secret.",
                  "In https://developers.facebook.com/tools/explorer switch to threads.net, pick the app and generate a Threads token.",
                  "Run 'social.py connect threads' and paste the Threads app secret and the token."],
        "notes": "Free; 250 posts in 24 hours. Threads takes media only from a web address: run 'social.py setup-tunnel' once. The token "
                 "renews itself."},
    "x": {
        "label": "X", "fields": [("client_id", "OAuth 2.0 Client ID", False)],
        "steps": ["Open https://console.x.com, sign in with your X account and create a Project and an App.",
                  "App > User authentication settings: App permissions 'Read and write'; Type of App 'Native App'; Callback URI "
                  "http://127.0.0.1:3007/callback; Website URL: any page of yours.",
                  "Copy the OAuth 2.0 Client ID (no secret is needed for a Native App).",
                  "Billing: X has no free tier since February 2026: add a card or credits (new accounts get $20 in credits for adding a card).",
                  "Run 'social.py connect x'; an X sign-in page opens once."],
        "notes": "Paid per use: $0.015 a post, $0.20 when the post has a link, $0.005 to delete. The AI PC shows the cost before posting."},
}


def connect(name, values, open_url=webbrowser.open, show=print, transport=None):
    from .platforms import connector
    if name in META_CONNECT:
        return META_CONNECT[name](values, open_url, show, transport)
    signin(name, values, open_url, show, transport=transport)
    plat = connector(name)
    who = plat.whoami()
    who["warnings"] = [APPS[name]["notes"]]
    return who


META_CONNECT = {"facebook": meta_connect, "instagram": lambda v, *a, **k: (instagram_login_connect if v.get("token") else meta_connect)(v, *a, **k),
                "threads": threads_connect}
