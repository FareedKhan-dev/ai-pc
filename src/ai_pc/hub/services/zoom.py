"""Zoom through its API with a Server-to-Server OAuth app: upcoming meetings, schedule one (with its join link), delete."""
from ai_pc.hub import oauth
from ai_pc.hub.http import Api
from ai_pc.hub.services import Base


class Zoom(Base):
    name = "zoom"

    def api(self):
        tok = self.creds.get("access_token") if self.transport else oauth.access_token("zoom")
        return Api("https://api.zoom.us/v2", headers={"Authorization": f"Bearer {tok}"}, service="zoom", transport=self.transport)

    def whoami(self):
        me = self.api().get("users/me")
        return {"who": me.get("email"), "where": f"Zoom ({me.get('first_name', '')} {me.get('last_name', '')})".strip()}

    def meetings(self):
        js = self.api().get("users/me/meetings", params={"type": "upcoming", "page_size": 30})
        return {"where": "Zoom", "meetings": [{"id": m["id"], "title": m.get("topic"), "start": m.get("start_time"), "link": m.get("join_url")}
                                              for m in js.get("meetings", [])]}

    def create(self, title, start, minutes=30, agenda=None, tz="Asia/Karachi"):
        body = {"topic": title, "type": 2, "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"), "duration": int(minutes), "timezone": tz,
                **({"agenda": agenda} if agenda else {}), "settings": {"join_before_host": False, "waiting_room": True}}
        m = self.api().post("users/me/meetings", json=body)
        back = self.api().get(f"meetings/{m['id']}")
        return {"id": m["id"], "where": "Zoom", "link": m.get("join_url"), "name": title, "verified": back.get("topic") == title,
                "undo": {"service": "zoom", "op": "delete", "id": m["id"]}}

    def delete(self, id):  # noqa: A002
        self.api().delete(f"meetings/{id}")
        return {"deleted": id}
