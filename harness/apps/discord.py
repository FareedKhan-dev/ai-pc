"""Discord through a channel's webhook (Server Settings > Integrations > Webhooks > New Webhook > Copy Webhook URL): a
message or a picture posted to that channel after a yes, read back from Discord's answer, and the last post deleted
again on request (a webhook may delete its own messages).

  'post to discord: New stock arrived! LED TV 55 now Rs 84,000'   'post photo.jpg to discord saying New arrivals'   'delete the last discord post'
"""
import json
import re
from pathlib import Path

from ..hub import vault
from ..hub.http import Api, HubError, multipart

NAME, LABEL = "discord", "Discord: post messages and pictures to a channel (webhook), delete"
EXAMPLES = ["post to discord: New stock arrived!", "post photo.jpg to discord saying New arrivals", "delete the last discord post"]
OUTWARD = {"post", "delete"}
APP = {"label": "Discord", "fields": [("webhook", "The channel's webhook URL", True)],
       "steps": ["In your Discord server: Server Settings > Integrations > Webhooks > New Webhook; pick the channel; Copy Webhook URL.",
                 "Run 'apps.py connect discord' and paste it (kept encrypted: anyone with it can post to that channel)."]}


class Client:
    def __init__(self, creds, transport=None):
        if not re.match(r"^https://(?:discord|discordapp)\.com/api/webhooks/\d+/[\w-]+$", creds.get("webhook", "")):
            raise RuntimeError("that is not a Discord webhook address")
        self.c, self.api = creds, Api(creds["webhook"], service="discord", transport=transport)

    def post(self, text, image=None):
        try:
            if image:
                body, ctype = multipart({"payload_json": json.dumps({"content": text})}, {"files[0]": (Path(image).name, Path(image).read_bytes(), "image/png" if
                                                                                                       image.lower().endswith(".png") else "image/jpeg")})
                return self.api.request("POST", self.c["webhook"], params={"wait": "true"}, data=body, headers={"Content-Type": ctype}, retries=0)
            return self.api.request("POST", self.c["webhook"], params={"wait": "true"}, json_body={"content": text}, retries=0)
        except HubError as e:
            raise RuntimeError(f"Discord: {e}") from e

    def delete(self, mid):
        try:
            self.api.request("DELETE", f"{self.c['webhook']}/messages/{mid}", raw=True)
        except HubError as e:
            raise RuntimeError(f"Discord: {e}") from e


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Discord is not connected: 'apps.py steps discord' shows how")
    return Client(c)


def connect(values, transport=None, store=None):
    Client(dict(values), transport)
    (store or (lambda v: vault.put(NAME, v)))(dict(values))
    return {"who": "webhook saved", "where": "Discord"}


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bdiscord\b", c):
        return None
    if re.search(r"\bdelete\b.*\blast\b", c):
        return {"op": "delete"}
    m = re.match(r"^\s*post\s+to\s+discord\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        return {"op": "post", "text": m.group(1).strip(), "image": None}
    m = re.match(r"^\s*post\s+(\S+\.(?:png|jpe?g|gif|webp))\s+to\s+discord(?:\s+saying\s+(.+))?$", text, re.I | re.S)
    if m:
        return {"op": "post", "text": (m.group(2) or "").strip(), "image": find_file(m.group(1), ctx)}
    return None


def preview(op, ctx):
    if op["op"] == "delete":
        return "Ready to delete the last post made here on Discord."
    return "Ready to post on Discord: " + (f"{Path(op['image']).name} with " if op.get("image") else "") + f"'{op['text'][:200]}'."


def run(op, ctx):
    if not op.get("confirmed"):
        return preview(op, ctx)
    cl = client(ctx)
    last = ctx["memo"].setdefault("discord", {})
    if op["op"] == "delete":
        mid = last.get("id") or (vault.get("discord_last") or {}).get("id")
        if not mid:
            return "No post made from here to delete."
        cl.delete(mid)
        return f"Deleted the Discord post {mid}."
    m = cl.post(op["text"], op.get("image"))
    last["id"] = m["id"]
    if ctx.get("clients") is None:
        vault.put("discord_last", {"id": m["id"]})
    ok = (m.get("content") or "") == op["text"] and (not op.get("image") or m.get("attachments"))
    return f"Posted on Discord (message {m['id']}; {'read back: the same text' if ok else 'NOT the same when read back'}" + \
        (", with the picture" if m.get("attachments") else "") + "). Say 'delete the last discord post' to take it back."
