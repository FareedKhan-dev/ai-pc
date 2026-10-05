"""Your phone as the AI PC's remote: what you send your own Telegram bot (messages, voice notes, photos, videos, documents)
reaches the AI PC chat, and its replies and the files it made come back to you there.

Only your own chat is listened to (the one saved when you connected Telegram: 'ai-pc hub connect telegram'); messages from
anyone else are ignored. Messages sent before the bridge started are skipped, so nothing old runs by surprise. Anything
others will see still waits for your 'yes'. Bots may download files up to 20 MB and send up to 50 MB.

  Bridge(AIPCChat.start()).run()        (ai-pc telegram)
"""

import threading
import time
from pathlib import Path

from ai_pc.hub.http import HubError

MAX_IN, MAX_OUT = 20 * 1024 * 1024, 48 * 1024 * 1024


class Bridge:
    def __init__(self, chat, tg=None, log=print, typing=True):
        if tg is None:
            from ai_pc.hub.services import connector

            tg = connector("telegram")
        self.chat, self.tg, self.log, self.typing = chat, tg, log, typing
        self.owner = tg.creds.get("chat_id")
        if not self.owner:
            raise HubError(
                "Telegram is not set up for you yet: open your bot in Telegram, send it any message, then run 'ai-pc hub connect telegram'"
            )
        self.inbox = Path(chat.folder) / "inbox"
        self.offset = chat.state.get("tg_offset")

    # ---------------------------------------------------------------- Telegram calls
    def updates(self, timeout=25):
        kw = {"timeout": timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            kw["offset"] = self.offset
        return self.tg.call("getUpdates", **kw)

    def skip_backlog(self):
        """Forget what was sent before the bridge started."""
        if self.offset is None:
            old = self.tg.call("getUpdates", offset=-1, timeout=0)
            self.offset = (old[-1]["update_id"] + 1) if old else 0
            self.chat.state["tg_offset"] = self.offset
            self.chat.save()

    def download(self, file_id, name):
        info = self.tg.call("getFile", file_id=file_id)
        if int(info.get("file_size") or 0) > MAX_IN:
            raise HubError("too big for a bot to download (20 MB)")
        url = f"https://api.telegram.org/file/bot{self.tg.creds['bot_token']}/{info['file_path']}"
        status, _, data = self.tg.api().request("GET", url, raw=True)
        if status >= 400 or not data:
            raise HubError(f"could not download {name} ({status})")
        self.inbox.mkdir(parents=True, exist_ok=True)
        dst = self.inbox / name
        n = 2
        while dst.exists() and dst.stat().st_size != len(data):
            dst = self.inbox / f"{Path(name).stem}_{n}{Path(name).suffix}"
            n += 1
        dst.write_bytes(data)
        return str(dst)

    def send_text(self, text):
        for i in range(0, len(text), 3900):
            self.tg.send(text[i : i + 3900], chat=self.owner)

    def _typing(self, stop):
        while not stop.is_set():
            try:
                self.tg.call("sendChatAction", chat_id=self.owner, action="typing")
            except Exception:  # noqa: BLE001 - only a courtesy
                pass
            stop.wait(4.5)

    # ---------------------------------------------------------------- one message from you
    def media(self, msg):
        """(files to attach, a voice note to hear) from a Telegram message."""
        files, voice = [], None
        uid = msg.get("message_id", int(time.time()))
        if msg.get("voice"):
            voice = self.download(msg["voice"]["file_id"], f"voice_{uid}.oga")
        if msg.get("photo"):
            best = max(msg["photo"], key=lambda p: p.get("file_size") or p.get("width", 0))
            files.append(self.download(best["file_id"], f"photo_{uid}.jpg"))
        for key, default in (
            ("video", f"video_{uid}.mp4"),
            ("document", f"file_{uid}"),
            ("audio", f"audio_{uid}.mp3"),
            ("video_note", f"videonote_{uid}.mp4"),
            ("animation", f"animation_{uid}.mp4"),
        ):
            if msg.get(key):
                d = msg[key]
                files.append(self.download(d["file_id"], d.get("file_name") or default))
        return files, voice

    def handle(self, update):
        msg = update.get("message") or {}
        if (msg.get("chat") or {}).get("id") != self.owner:
            return None  # not you: ignored
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if text in ("/start", "/help"):
            text = "what can you do?"
        try:
            files, voice = self.media(msg)
        except HubError as e:
            self.send_text(f"Couldn't take that file: {e}.")
            return None
        stop = threading.Event()
        t = None
        if self.typing:
            t = threading.Thread(target=self._typing, args=(stop,), daemon=True)
            t.start()
        try:
            reply = self.chat.say(text, files=files, voice=voice)
        finally:
            stop.set()
        out = (f'Heard: "{reply.heard}"\n' if reply.heard else "") + str(reply)
        self.send_text(out)
        for f in reply.files:
            p = Path(f)
            if p.is_file() and p.stat().st_size <= MAX_OUT:
                try:
                    self.tg.send_file(str(p), caption=p.name, chat=self.owner)
                except HubError as e:
                    self.send_text(f"Made {p.name} but could not send it here ({e}); it is on the PC: {p}")
            elif p.is_file():
                self.send_text(f"{p.name} is too big for Telegram ({p.stat().st_size // (1024 * 1024)} MB); it is on the PC: {p}")
        return reply

    def run(self, once=False):
        self.skip_backlog()
        if not once:
            self.send_text("AI PC chat is on. Send a message, a voice note or a file; 'what can you do?' for the list.")
        while True:
            try:
                ups = self.updates(timeout=0 if once else 25)
            except HubError as e:
                self.log(f"telegram: {e}; trying again in 10 s")
                if once:
                    return
                time.sleep(10)
                continue
            for u in ups:
                self.offset = u["update_id"] + 1
                self.chat.state["tg_offset"] = self.offset
                self.chat.save()
                try:
                    self.handle(u)
                except Exception as e:  # noqa: BLE001 - one bad message must not stop the bridge
                    self.log(f"telegram: {type(e).__name__}: {e}")
                    try:
                        self.send_text(f"Couldn't: {type(e).__name__}: {e}")
                    except Exception:  # noqa: BLE001
                        pass
            if once:
                return
