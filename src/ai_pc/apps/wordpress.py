"""WordPress (REST API): blog posts written as drafts (with a featured picture uploaded to the media library), your
latest posts listed, and a draft published after a yes. Signs in with an Application Password (Users > Profile >
Application Passwords), which WordPress offers on HTTPS sites. Creating and publishing are shown first.

  "wordpress draft 'New lawn collection': Our summer lawn is here. Prices from Rs 2,500. with lawn.jpg"
  'wordpress posts'   'publish wordpress post 101'
"""
import base64
import html
import mimetypes
import re
from pathlib import Path

from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

NAME, LABEL = "wordpress", "WordPress: draft posts with pictures, list, publish"
EXAMPLES = ["wordpress draft 'New lawn collection': Our summer lawn is here.", "wordpress posts", "publish wordpress post 101"]
OUTWARD = {"draft", "publish"}
APP = {"label": "WordPress",
       "fields": [("url", "Your site's address (https://...)", False), ("user", "Your WordPress username", False),
                  ("app_password", "Application password (24 letters)", True)],
       "steps": ["In WordPress admin: Users > Profile > Application Passwords: type 'AI PC', click Add New Application Password, copy it (shown once).",
                 "Run 'ai-pc apps connect wordpress' with your site's https:// address, your username and that password."],
       "notes": "Application passwords work on HTTPS sites. Posts are made as drafts; publishing is a separate yes."}


class Client:
    def __init__(self, creds, transport=None):
        if not str(creds.get("url", "")).startswith("https://"):
            raise RuntimeError("WordPress application passwords are sent only to an https:// site")
        self.c, self.transport = creds, transport
        auth = base64.b64encode(f"{creds['user']}:{creds['app_password'].replace(' ', '')}".encode()).decode()
        self.api = Api(creds["url"].rstrip("/") + "/wp-json/wp/v2", headers={"Authorization": f"Basic {auth}"}, service="wordpress", transport=transport)

    def call(self, method, path, **kw):
        try:
            return self.api.request(method, path, retries=0 if method == "POST" else 3, **kw)
        except HubError as e:
            b = e.body if isinstance(e.body, dict) else {}
            raise RuntimeError(f"WordPress: {b.get('message') or e}") from e

    def upload(self, path):
        p = Path(path)
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        r = self.call("POST", "media", data=p.read_bytes(), headers={"Content-Type": mime, "Content-Disposition": f'attachment; filename="{p.name}"'})
        return r["id"], r.get("source_url")

    def draft(self, title, text, image=None):
        body = {"title": title, "content": "".join(f"<p>{html.escape(par.strip())}</p>" for par in re.split(r"\n\s*\n", text) if par.strip()), "status": "draft"}
        if image:
            body["featured_media"] = self.upload(image)[0]
        return self.call("POST", "posts", json_body=body)

    def posts(self):
        return self.call("GET", "posts", params={"context": "edit", "status": "draft,publish", "per_page": 10})

    def publish(self, pid):
        return self.call("POST", f"posts/{pid}", json_body={"status": "publish"})


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("WordPress is not connected: 'ai-pc apps steps wordpress' shows how")
    return Client(c)


def connect(values, transport=None, store=None):
    c = Client(dict(values), transport)
    me = c.call("GET", "users/me", params={"context": "edit"})
    (store or (lambda v: vault.put(NAME, v)))(dict(values))
    return {"who": me.get("name"), "where": f"WordPress at {values['url']}"}


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bwordpress\b|\bwp\b|\bblog\b", c):
        return None
    m = re.match(r"^\s*(?:wordpress|blog|wp)\s+(?:draft|post)\s*(?:'([^']+)'|\"([^\"]+)\")\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        body = m.group(3)
        img = find_file(text, ctx, {".jpg", ".jpeg", ".png", ".webp", ".gif"}) if re.search(r"\bwith\s+\S+\.(?:jpe?g|png|webp|gif)\b", body, re.I) else None
        body = re.sub(r"\s*\bwith\s+\S+\.(?:jpe?g|png|webp|gif)\s*$", "", body, flags=re.I)
        return {"op": "draft", "title": m.group(1) or m.group(2), "text": body.strip(), "image": img}
    m = re.search(r"\bpublish\s+(?:wordpress\s+|blog\s+)?post\s+(\d+)", c)
    if m:
        return {"op": "publish", "id": int(m.group(1))}
    if re.search(r"\b(?:wordpress|blog)\s+posts\b|\bmy\s+(?:blog|wordpress)\s+posts\b", c):
        return {"op": "posts"}
    return None


def preview(op, ctx):
    if op["op"] == "draft":
        return f"Ready to save a draft on WordPress: '{op['title']}' ({len(op['text'].split())} words)" + (f" with {Path(op['image']).name} as its picture" if op.get("image")
                                                                                                         else "") + " (a draft: not public)."
    return f"Ready to publish WordPress post {op['id']} (it goes public)."


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "posts":
        ps = c.posts()
        return "\n".join(f"- {p['id']}: {html.unescape((p.get('title') or {}).get('raw') or (p.get('title') or {}).get('rendered') or '')} ({p.get('status')})"
                         for p in ps) or "No posts yet."
    if not op.get("confirmed"):
        return preview(op, ctx)
    if op["op"] == "draft":
        p = c.draft(op["title"], op["text"], op.get("image"))
        back = c.call("GET", f"posts/{p['id']}", params={"context": "edit"})
        ok = back.get("status") == "draft" and (back.get("title") or {}).get("raw") == op["title"]
        return f"Draft {p['id']} saved on WordPress ({'read back: a draft, the same title' if ok else 'NOT as asked'})" + \
            (", with its picture" if back.get("featured_media") else "") + f". Say 'publish wordpress post {p['id']}' to put it live."
    p = c.publish(op["id"])
    return f"Post {op['id']} is {p.get('status')}: {p.get('link')}"
