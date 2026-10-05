"""Slack through its Web API with a bot token: post (also in a thread, or later), read a channel, direct messages, edit,
delete, upload a file, react. Every post is read back from the channel's history."""

import re
import time
from pathlib import Path

from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base, pick


class Slack(Base):
    name = "slack"

    def api(self):
        self.need("bot_token")
        return Api("https://slack.com/api", headers={"Authorization": f"Bearer {self.creds['bot_token']}"}, service="slack", transport=self.transport)

    def call(self, method, http="POST", **kw):
        a = self.api()
        js = a.get(method, params=kw) if http == "GET" else a.post(method, json=kw)
        if not js.get("ok"):
            raise HubError(f"slack: {method} said {js.get('error', 'not ok')}" + (f" (needs {js['needed']})" if js.get("needed") else ""), body=js)
        return js

    def whoami(self):
        js = self.call("auth.test")
        return {"who": js.get("user"), "where": js.get("team"), "url": js.get("url")}

    # ---------------------------------------------------------------- channels and people
    def channels(self):
        out, cursor = [], None
        while True:
            js = self.call("conversations.list", "GET", types="public_channel,private_channel", exclude_archived="true", limit=200, cursor=cursor)
            out += [
                {"id": c["id"], "name": c["name"], "member": c.get("is_member", False), "private": c.get("is_private", False)} for c in js["channels"]
            ]
            cursor = (js.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return out

    def users(self):
        js = self.call("users.list", "GET", limit=500)
        return [
            {
                "id": u["id"],
                "name": u.get("name"),
                "real_name": u.get("real_name") or (u.get("profile") or {}).get("real_name"),
                "email": (u.get("profile") or {}).get("email"),
                "bot": u.get("is_bot", False),
            }
            for u in js["members"]
            if not u.get("deleted")
        ]

    def target(self, where):
        """'#general', 'general', 'C0123', '@ali', 'ali@x.com' -> (channel id, label)."""
        w = (where or "").strip()
        if w.startswith(("C", "G", "D")) and w[1:].isalnum() and w.upper() == w:
            return w, w
        if w.startswith("@") or "@" in w[1:]:
            us = self.users()
            u = next((x for x in us if x["email"] and x["email"].lower() == w.lower()), None) or pick(us, w, "name") or pick(us, w, "real_name")
            if not u:
                raise HubError(f"slack: no one called {w} in this workspace")
            ch = self.call("conversations.open", users=u["id"])["channel"]["id"]
            return ch, f"@{u['name']}"
        c = pick(self.channels(), w)
        if not c:
            raise HubError(f"slack: no channel {w}")
        return c["id"], f"#{c['name']}"

    # ---------------------------------------------------------------- messages
    def post(self, where, text, thread=None):
        ch, label = self.target(where)
        js = self.call("chat.postMessage", channel=ch, text=text, **({"thread_ts": thread} if thread else {}))
        ts = js["ts"]
        link = self.call("chat.getPermalink", "GET", channel=js["channel"], message_ts=ts).get("permalink")
        back = self.call("conversations.history", "GET", channel=js["channel"], latest=ts, inclusive="true", limit=1).get("messages", [])
        return {
            "id": ts,
            "channel": js["channel"],
            "where": label,
            "link": link,
            "verified": bool(back) and back[0].get("text") == text,
            "undo": {"service": "slack", "op": "delete", "channel": js["channel"], "ts": ts},
        }

    def schedule(self, where, text, at_unix):
        ch, label = self.target(where)
        js = self.call("chat.scheduleMessage", channel=ch, text=text, post_at=int(at_unix))
        return {
            "id": js["scheduled_message_id"],
            "channel": ch,
            "where": label,
            "at": int(at_unix),
            "undo": {"service": "slack", "op": "unschedule", "channel": ch, "id": js["scheduled_message_id"]},
        }

    def read(self, where, hours=24, limit=100):
        ch, label = self.target(where)
        js = self.call("conversations.history", "GET", channel=ch, oldest=f"{time.time() - hours * 3600:.0f}", limit=limit)
        names = {u["id"]: u["real_name"] or u["name"] for u in self.users()}
        skip = {"channel_join", "channel_leave", "group_join", "group_leave", "bot_add", "bot_remove", "channel_topic", "channel_purpose"}

        def words(t):  # <@U123> -> @Name, <#C1|general> -> #general, <https://x|x> -> x
            t = re.sub(r"<@(\w+)>", lambda m: "@" + names.get(m.group(1), m.group(1)), t or "")
            t = re.sub(r"<#\w+\|([^>]+)>", r"#\1", t)
            return re.sub(r"<(https?://[^|>]+)(?:\|[^>]+)?>", r"\1", t)

        msgs = [
            {
                "ts": m["ts"],
                "who": names.get(m.get("user"), m.get("username") or m.get("bot_id") or "?"),
                "text": words(m.get("text", "")),
                "replies": m.get("reply_count", 0),
            }
            for m in js.get("messages", [])
            if m.get("type") == "message" and m.get("subtype") not in skip
        ]
        return {"where": label, "messages": list(reversed(msgs))}

    def update(self, channel, ts, text):
        self.call("chat.update", channel=channel, ts=ts, text=text)
        return {"id": ts}

    def delete(self, channel, ts):
        self.call("chat.delete", channel=channel, ts=ts)
        return {"deleted": ts}

    def unschedule(self, channel, id):  # noqa: A002
        self.call("chat.deleteScheduledMessage", channel=channel, scheduled_message_id=id)
        return {"deleted": id}

    def react(self, channel, ts, emoji):
        self.call("reactions.add", channel=channel, timestamp=ts, name=emoji.strip(":"))
        return {"ok": True}

    def upload(self, where, path, comment=None):
        p = Path(path)
        data = p.read_bytes()
        ch, label = self.target(where)
        a = self.api()
        up = a.get("files.getUploadURLExternal", params={"filename": p.name, "length": len(data)})
        if not up.get("ok"):
            raise HubError(f"slack: files.getUploadURLExternal said {up.get('error')}")
        status, _, _ = a.request("POST", up["upload_url"], data=data, headers={"Content-Type": "application/octet-stream"}, raw=True)
        if status >= 400:
            raise HubError(f"slack: the upload was refused ({status})")
        done = self.call(
            "files.completeUploadExternal",
            files=[{"id": up["file_id"], "title": p.name}],
            channel_id=ch,
            **({"initial_comment": comment} if comment else {}),
        )
        f = (done.get("files") or [{}])[0]
        return {
            "id": up["file_id"],
            "where": label,
            "name": p.name,
            "link": f.get("permalink"),
            "verified": f.get("id") == up["file_id"],
            "undo": {"service": "slack", "op": "delete_file", "id": up["file_id"]},
        }

    def delete_file(self, id):  # noqa: A002
        self.call("files.delete", file=id)
        return {"deleted": id}
