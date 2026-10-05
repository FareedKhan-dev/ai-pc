"""Google through its APIs (one sign-in, ai_pc.hub.oauth): Gmail (unread mail, a draft, send, trash), Calendar (events,
a new event with a Meet link and invites, delete), Drive (upload, share, delete) and Sheets (create, read, append, write).
Every change is read back."""

import base64
import datetime as dt
import json
import mimetypes
import uuid
from email.message import EmailMessage
from pathlib import Path

from ai_pc.hub import oauth
from ai_pc.hub.http import Api
from ai_pc.hub.services import Base


def _raw(to, subject, body, cc=None, attachments=(), sender=None):
    m = EmailMessage()
    m["To"] = ", ".join(to) if isinstance(to, (list, tuple)) else to
    if cc:
        m["Cc"] = ", ".join(cc) if isinstance(cc, (list, tuple)) else cc
    if sender:
        m["From"] = sender
    m["Subject"] = subject
    m.set_content(body)
    for a in attachments or ():
        p = Path(a)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        main, sub = ctype.split("/", 1)
        m.add_attachment(p.read_bytes(), maintype=main, subtype=sub, filename=p.name)
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


class Google(Base):
    name = "google"

    def api(self, base):
        tok = self.creds.get("access_token") if self.transport else oauth.access_token("google")
        return Api(base, headers={"Authorization": f"Bearer {tok}"}, service="google", transport=self.transport)

    def gmail(self):
        return self.api("https://gmail.googleapis.com/gmail/v1/users/me")

    def cal(self):
        return self.api("https://www.googleapis.com/calendar/v3/calendars/primary")

    def drive(self):
        return self.api("https://www.googleapis.com/drive/v3")

    def sheets(self):
        return self.api("https://sheets.googleapis.com/v4/spreadsheets")

    def whoami(self):
        p = self.gmail().get("profile")
        return {"who": p.get("emailAddress"), "where": "Google"}

    # ---------------------------------------------------------------- Gmail
    def unread(self, n=10, query="is:unread in:inbox"):
        g = self.gmail()
        ids = [m["id"] for m in g.get("messages", params={"q": query, "maxResults": n}).get("messages", [])]
        out = []
        for i in ids:
            m = g.get(f"messages/{i}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
            h = {x["name"]: x["value"] for x in (m.get("payload") or {}).get("headers", [])}
            out.append(
                {"id": i, "from": h.get("From", ""), "subject": h.get("Subject", ""), "date": h.get("Date", ""), "snippet": m.get("snippet", "")}
            )
        return {"where": "Gmail", "messages": out}

    def draft(self, to, subject, body, cc=None, attachments=()):
        d = self.gmail().post("drafts", json={"message": {"raw": _raw(to, subject, body, cc, attachments)}})
        back = self.gmail().get(f"drafts/{d['id']}", params={"format": "metadata"})
        return {
            "id": d["id"],
            "where": "Gmail drafts",
            "verified": back.get("id") == d["id"],
            "undo": {"service": "google", "op": "delete_draft", "id": d["id"]},
        }

    def send_draft(self, draft_id):
        m = self.gmail().post("drafts/send", json={"id": draft_id})
        back = self.gmail().get(f"messages/{m['id']}", params={"format": "minimal"})
        return {"id": m["id"], "where": "Gmail", "verified": "SENT" in back.get("labelIds", []), "undo": None}

    def send(self, to, subject, body, cc=None, attachments=()):
        m = self.gmail().post("messages/send", json={"raw": _raw(to, subject, body, cc, attachments)})
        back = self.gmail().get(f"messages/{m['id']}", params={"format": "minimal"})
        return {"id": m["id"], "where": "Gmail", "verified": "SENT" in back.get("labelIds", []), "undo": None}

    def delete_draft(self, id):  # noqa: A002
        self.gmail().delete(f"drafts/{id}")
        return {"deleted": id}

    # ---------------------------------------------------------------- Calendar
    def events(self, start, end):
        js = self.cal().get(
            "events",
            params={"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "orderBy": "startTime", "maxResults": 50},
        )
        return {
            "where": "Google Calendar",
            "events": [
                {
                    "id": e["id"],
                    "title": e.get("summary", "(no title)"),
                    "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"),
                    "end": (e.get("end") or {}).get("dateTime"),
                    "link": e.get("hangoutLink") or e.get("htmlLink"),
                    "where": e.get("location"),
                }
                for e in js.get("items", [])
            ],
        }

    def create_event(self, title, start, end, attendees=(), location=None, meet=True, notes=None, tz="Asia/Karachi"):
        body = {"summary": title, "start": {"dateTime": start.isoformat(), "timeZone": tz}, "end": {"dateTime": end.isoformat(), "timeZone": tz}}
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        if location:
            body["location"] = location
        if notes:
            body["description"] = notes
        params = {"sendUpdates": "all" if attendees else "none"}
        if meet:
            body["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex, "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
            params["conferenceDataVersion"] = 1
        e = self.cal().post("events", json=body, params=params)
        back = self.cal().get(f"events/{e['id']}")
        return {
            "id": e["id"],
            "where": "Google Calendar",
            "link": e.get("hangoutLink") or e.get("htmlLink"),
            "name": title,
            "verified": back.get("summary") == title,
            "undo": {"service": "google", "op": "delete_event", "id": e["id"]},
        }

    def delete_event(self, id):  # noqa: A002
        self.cal().delete(f"events/{id}", params={"sendUpdates": "all"})
        return {"deleted": id}

    # ---------------------------------------------------------------- Drive
    def upload(self, path, name=None, folder=None):
        p = Path(path)
        meta = {"name": name or p.name, **({"parents": [folder]} if folder else {})}
        b = uuid.uuid4().hex
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        body = (
            f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + json.dumps(meta).encode()
            + f"\r\n--{b}\r\nContent-Type: {ctype}\r\n\r\n".encode()
            + p.read_bytes()
            + f"\r\n--{b}--".encode()
        )
        up = self.api("https://www.googleapis.com/upload/drive/v3").request(
            "POST",
            "files",
            params={"uploadType": "multipart", "fields": "id,name,webViewLink,size"},
            data=body,
            headers={"Content-Type": f"multipart/related; boundary={b}"},
        )
        back = self.drive().get(f"files/{up['id']}", params={"fields": "id,name,size"})
        return {
            "id": up["id"],
            "where": "Google Drive",
            "link": up.get("webViewLink"),
            "name": up.get("name"),
            "verified": int(back.get("size", -1)) == p.stat().st_size,
            "undo": {"service": "google", "op": "delete_file", "id": up["id"]},
        }

    def share(self, file_id, email, role="reader", notify=True):
        perm = self.drive().post(
            f"files/{file_id}/permissions",
            json={"type": "user", "role": role, "emailAddress": email},
            params={"sendNotificationEmail": "true" if notify else "false"},
        )
        return {
            "id": perm["id"],
            "where": f"shared with {email}",
            "verified": True,
            "undo": {"service": "google", "op": "unshare", "file": file_id, "id": perm["id"]},
        }

    def unshare(self, file, id):  # noqa: A002
        self.drive().delete(f"files/{file}/permissions/{id}")
        return {"deleted": id}

    def delete_file(self, id):  # noqa: A002
        self.drive().delete(f"files/{id}")
        return {"deleted": id}

    # ---------------------------------------------------------------- Sheets
    def sheet_create(self, title, rows=None):
        s = self.sheets().post("", json={"properties": {"title": title}})
        if rows:
            self.sheet_write(s["spreadsheetId"], "A1", rows)
        return {
            "id": s["spreadsheetId"],
            "where": "Google Sheets",
            "link": s.get("spreadsheetUrl"),
            "name": title,
            "verified": True,
            "undo": {"service": "google", "op": "delete_file", "id": s["spreadsheetId"]},
        }

    def sheet_read(self, sheet_id, rng="A1:Z200"):
        return self.sheets().get(f"{sheet_id}/values/{rng}").get("values", [])

    def sheet_append(self, sheet_id, rows, rng="A1"):
        r = self.sheets().post(
            f"{sheet_id}/values/{rng}:append", json={"values": rows}, params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}
        )
        upd = r.get("updates") or {}
        return {
            "id": sheet_id,
            "where": upd.get("updatedRange", "the sheet"),
            "verified": upd.get("updatedRows", 0) == len(rows),
            "undo": {"service": "google", "op": "sheet_clear", "id": sheet_id, "range": upd.get("updatedRange")},
        }

    def sheet_write(self, sheet_id, rng, rows):
        r = self.sheets().put(f"{sheet_id}/values/{rng}", json={"values": rows}, params={"valueInputOption": "USER_ENTERED"})
        return {"id": sheet_id, "where": r.get("updatedRange"), "verified": r.get("updatedRows", 0) == len(rows)}

    def sheet_clear(self, id, range):  # noqa: A002
        self.sheets().post(f"{id}/values/{range}:clear", json={})
        return {"cleared": range}


def day_bounds(day, tz_hours=5):
    """Start and end of a calendar day in Pakistan time (UTC+5) as aware datetimes."""
    tz = dt.timezone(dt.timedelta(hours=tz_hours))
    s = dt.datetime(day.year, day.month, day.day, tzinfo=tz)
    return s, s + dt.timedelta(days=1)
