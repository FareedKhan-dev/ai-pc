"""Telegram through the Bot API: messages and files to you (or a group the bot is in), and what was sent to the bot.
The person's own chat is learned the first time they message the bot."""

from pathlib import Path

from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError, multipart
from ai_pc.hub.services import Base


class Telegram(Base):
    name = "telegram"

    def api(self):
        self.need("bot_token")
        return Api(f"https://api.telegram.org/bot{self.creds['bot_token']}", service="telegram", transport=self.transport)

    def call(self, method, **kw):
        js = self.api().post(method, json=kw)
        if not js.get("ok"):
            raise HubError(f"telegram: {method} said {js.get('description', 'not ok')}")
        return js["result"]

    def whoami(self):
        r = self.call("getMe")
        return {"who": f"@{r.get('username')}", "where": r.get("first_name")}

    def updates(self):
        return [u for u in self.call("getUpdates", timeout=0) if u.get("message")]

    def my_chat(self):
        """The chat to message by default: saved, or the latest private chat that wrote to the bot."""
        if self.creds.get("chat_id"):
            return self.creds["chat_id"]
        ups = [u["message"]["chat"] for u in self.updates() if u["message"]["chat"].get("type") == "private"]
        if not ups:
            raise HubError("telegram: open your bot in Telegram and send it any message first (so it may write to you)")
        cid = ups[-1]["id"]
        if not self.transport:
            vault.put("telegram", {"chat_id": cid})
        self.creds["chat_id"] = cid
        return cid

    def send(self, text, chat=None):
        cid = chat or self.my_chat()
        r = self.call("sendMessage", chat_id=cid, text=text)
        return {
            "id": r["message_id"],
            "chat": cid,
            "where": "Telegram",
            "verified": r.get("text") == text,
            "undo": {"service": "telegram", "op": "delete", "chat": cid, "message_id": r["message_id"]},
        }

    def send_file(self, path, caption=None, chat=None):
        cid = chat or self.my_chat()
        p = Path(path)
        kind = "photo" if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.stat().st_size < 10 * 1024 * 1024 else "document"
        body, ctype = multipart(
            {"chat_id": str(cid), **({"caption": caption} if caption else {})}, {kind: (p.name, p.read_bytes(), "application/octet-stream")}
        )
        js = self.api().request("POST", "sendPhoto" if kind == "photo" else "sendDocument", data=body, headers={"Content-Type": ctype})
        if not js.get("ok"):
            raise HubError(f"telegram: could not send {p.name} ({js.get('description')})")
        r = js["result"]
        return {
            "id": r["message_id"],
            "chat": cid,
            "where": "Telegram",
            "name": p.name,
            "verified": bool(r.get("photo") or r.get("document")),
            "undo": {"service": "telegram", "op": "delete", "chat": cid, "message_id": r["message_id"]},
        }

    def delete(self, chat, message_id):
        self.call("deleteMessage", chat_id=chat, message_id=message_id)
        return {"deleted": message_id}

    def read(self, n=20):
        return {
            "where": "Telegram",
            "messages": [
                {
                    "who": (u["message"].get("from") or {}).get("first_name", "?"),
                    "text": u["message"].get("text", ""),
                    "date": u["message"].get("date"),
                }
                for u in self.updates()[-n:]
            ],
        }
