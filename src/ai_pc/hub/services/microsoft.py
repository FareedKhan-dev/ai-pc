"""Microsoft 365 through Microsoft Graph (one device-code sign-in, ai_pc.hub.oauth): Outlook mail (unread, a draft,
send), Outlook calendar (events, a new event, with a Teams link for work accounts), OneDrive (upload, share link) and
Teams (post in a channel or a chat; work or school accounts only). Every change is read back."""
import base64
import json
from pathlib import Path

from ai_pc.hub import oauth
from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base, pick


def _recips(to):
    to = [to] if isinstance(to, str) else list(to or [])
    return [{"emailAddress": {"address": a.strip()}} for a in to if a.strip()]


class Microsoft(Base):
    name = "microsoft"

    def api(self):
        tok = self.creds.get("access_token") if self.transport else oauth.access_token("microsoft")
        return Api("https://graph.microsoft.com/v1.0", headers={"Authorization": f"Bearer {tok}"}, service="microsoft", transport=self.transport)

    def whoami(self):
        me = self.api().get("me", params={"$select": "displayName,mail,userPrincipalName"})
        return {"who": me.get("mail") or me.get("userPrincipalName"), "where": me.get("displayName") or "Microsoft"}

    # ---------------------------------------------------------------- Outlook mail
    def unread(self, n=10):
        js = self.api().get("me/mailFolders/inbox/messages", params={"$filter": "isRead eq false", "$top": n,
                                                                      "$select": "subject,from,receivedDateTime,bodyPreview", "$orderby": "receivedDateTime desc"})
        return {"where": "Outlook", "messages": [{"id": m["id"], "from": ((m.get("from") or {}).get("emailAddress") or {}).get("address", ""),
                                                  "subject": m.get("subject", ""), "date": m.get("receivedDateTime"), "snippet": m.get("bodyPreview", "")}
                                                 for m in js.get("value", [])]}

    def draft(self, to, subject, body, cc=None, attachments=()):
        msg = {"subject": subject, "body": {"contentType": "Text", "content": body}, "toRecipients": _recips(to)}
        if cc:
            msg["ccRecipients"] = _recips(cc)
        m = self.api().post("me/messages", json=msg)
        for a in attachments or ():
            p = Path(a)
            self.api().post(f"me/messages/{m['id']}/attachments", json={"@odata.type": "#microsoft.graph.fileAttachment", "name": p.name,
                                                                        "contentBytes": base64.b64encode(p.read_bytes()).decode()})
        back = self.api().get(f"me/messages/{m['id']}", params={"$select": "subject,isDraft"})
        return {"id": m["id"], "where": "Outlook drafts", "verified": back.get("isDraft") and back.get("subject") == subject,
                "undo": {"service": "microsoft", "op": "delete_message", "id": m["id"]}}

    def send_draft(self, draft_id):
        self.api().post(f"me/messages/{draft_id}/send", json={})
        return {"id": draft_id, "where": "Outlook", "verified": True, "undo": None}

    def send(self, to, subject, body, cc=None, attachments=()):
        d = self.draft(to, subject, body, cc, attachments)
        return self.send_draft(d["id"])

    def delete_message(self, id):  # noqa: A002
        self.api().delete(f"me/messages/{id}")
        return {"deleted": id}

    # ---------------------------------------------------------------- Outlook calendar
    def events(self, start, end):
        js = self.api().get("me/calendarView", params={"startDateTime": start.isoformat(), "endDateTime": end.isoformat(), "$orderby": "start/dateTime",
                                                        "$select": "subject,start,end,location,onlineMeeting,webLink", "$top": 50},
                            headers={"Prefer": 'outlook.timezone="Pakistan Standard Time"'})
        return {"where": "Outlook calendar", "events": [{"id": e["id"], "title": e.get("subject"), "start": (e.get("start") or {}).get("dateTime"),
                                                         "end": (e.get("end") or {}).get("dateTime"), "where": (e.get("location") or {}).get("displayName"),
                                                         "link": (e.get("onlineMeeting") or {}).get("joinUrl") or e.get("webLink")} for e in js.get("value", [])]}

    def create_event(self, title, start, end, attendees=(), location=None, meet=True, notes=None, tz="Pakistan Standard Time"):
        body = {"subject": title, "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz},
                "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tz}}
        if attendees:
            body["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
        if location:
            body["location"] = {"displayName": location}
        if notes:
            body["body"] = {"contentType": "Text", "content": notes}
        if meet:
            body.update(isOnlineMeeting=True, onlineMeetingProvider="teamsForBusiness")
        try:
            e = self.api().post("me/events", json=body)
        except HubError:
            if not meet:
                raise
            body.pop("isOnlineMeeting", None)  # personal accounts cannot make Teams meetings: the event without one
            body.pop("onlineMeetingProvider", None)
            e = self.api().post("me/events", json=body)
        back = self.api().get(f"me/events/{e['id']}", params={"$select": "subject"})
        return {"id": e["id"], "where": "Outlook calendar", "link": (e.get("onlineMeeting") or {}).get("joinUrl") or e.get("webLink"), "name": title,
                "verified": back.get("subject") == title, "undo": {"service": "microsoft", "op": "delete_event", "id": e["id"]}}

    def delete_event(self, id):  # noqa: A002
        self.api().delete(f"me/events/{id}")
        return {"deleted": id}

    # ---------------------------------------------------------------- OneDrive
    def upload(self, path, folder="AI PC"):
        p = Path(path)
        if p.stat().st_size > 4 * 1024 * 1024:
            raise HubError("onedrive: files over 4 MB need an upload session (not built yet)")
        st, _, content = self.api().request("PUT", f"me/drive/root:/{folder}/{p.name}:/content", data=p.read_bytes(),
                                            headers={"Content-Type": "application/octet-stream"}, raw=True)
        item = json.loads(content.decode("utf-8"))
        if st >= 400:
            raise HubError(f"onedrive: upload refused ({st} {item.get('error', {}).get('message', '')})")
        return {"id": item["id"], "where": f"OneDrive/{folder}", "link": item.get("webUrl"), "name": p.name, "verified": item.get("size") == p.stat().st_size,
                "undo": {"service": "microsoft", "op": "delete_item", "id": item["id"]}}

    def share_link(self, item_id, scope="anonymous"):
        js = self.api().post(f"me/drive/items/{item_id}/createLink", json={"type": "view", "scope": scope})
        return {"id": (js.get("link") or {}).get("webUrl"), "where": "a view link", "link": (js.get("link") or {}).get("webUrl"), "verified": True}

    def delete_item(self, id):  # noqa: A002
        self.api().delete(f"me/drive/items/{id}")
        return {"deleted": id}

    # ---------------------------------------------------------------- Teams (work or school accounts)
    def teams(self):
        return [{"id": t["id"], "name": t["displayName"]} for t in self.api().get("me/joinedTeams").get("value", [])]

    def channels(self, team):
        t = pick(self.teams(), team)
        if not t:
            raise HubError(f"teams: you are not in a team called {team}")
        return t, [{"id": c["id"], "name": c["displayName"]} for c in self.api().get(f"teams/{t['id']}/channels").get("value", [])]

    def post_channel(self, team, channel, text):
        t, chs = self.channels(team)
        c = pick(chs, channel)
        if not c:
            raise HubError(f"teams: no channel {channel} in {t['name']}")
        m = self.api().post(f"teams/{t['id']}/channels/{c['id']}/messages", json={"body": {"contentType": "text", "content": text}})
        return {"id": m["id"], "where": f"{t['name']} / {c['name']}", "link": m.get("webUrl"), "verified": ((m.get("body") or {}).get("content") or "") == text,
                "undo": {"service": "microsoft", "op": "softdelete_channel_message", "team": t["id"], "channel": c["id"], "id": m["id"]}}

    def softdelete_channel_message(self, team, channel, id):  # noqa: A002
        self.api().post(f"teams/{team}/channels/{channel}/messages/{id}/softDelete", json={})
        return {"deleted": id}
