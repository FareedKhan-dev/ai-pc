"""Microsoft To Do and OneNote through Microsoft Graph (the hub's Microsoft sign-in: 'ai-pc hub connect microsoft'): tasks
added (with a due date) to your To Do list, open tasks listed, a task ticked off; and a OneNote page written into a
notebook section. Each is read back from Microsoft.

  'todo: call Haier about the TV order by Friday'   'my microsoft tasks'   'complete microsoft task call Haier'
  "onenote page 'Meeting with Ali' in Work: prices agreed at 84,000"
"""

import datetime as dt
import html
import re

from ai_pc.hub.http import Api, HubError
from ai_pc.hub.hubparse import when

NAME, LABEL = "mstodo", "Microsoft To Do and OneNote (Microsoft Graph)"
EXAMPLES = ["microsoft todo: call Haier about the TV order by Friday", "my microsoft tasks", "onenote page 'Meeting with Ali' in Work: prices agreed"]
GRAPH = "https://graph.microsoft.com/v1.0"


class Client:
    def __init__(self, token=None, transport=None):
        self._token, self.transport = token, transport

    def call(self, method, path, body=None, params=None, data=None, headers=None):
        tok = self._token
        if not tok:
            from ai_pc.hub.oauth import access_token

            tok = access_token("microsoft")
        try:
            return Api(GRAPH, headers={"Authorization": f"Bearer {tok}"}, service="microsoft", transport=self.transport).request(
                method, path, json_body=body, params=params, data=data, headers=headers, retries=0 if method in ("POST", "PATCH") else 3
            )
        except HubError as e:
            if e.status == 403:
                raise RuntimeError("Microsoft needs your permission for To Do and OneNote: run 'ai-pc hub connect microsoft' again") from e
            raise RuntimeError(f"Microsoft: {e}") from e

    def default_list(self):
        lists = self.call("GET", "me/todo/lists").get("value") or []
        return next((x for x in lists if x.get("wellknownListName") == "defaultList"), lists[0] if lists else None)

    def add(self, title, due=None):
        lst = self.default_list()
        body = {"title": title}
        if due:
            body["dueDateTime"] = {"dateTime": f"{due.isoformat()}T09:00:00", "timeZone": "Pakistan Standard Time"}
        t = self.call("POST", f"me/todo/lists/{lst['id']}/tasks", body)
        return lst, t, self.call("GET", f"me/todo/lists/{lst['id']}/tasks/{t['id']}")

    def open_tasks(self):
        lst = self.default_list()
        return lst, [t for t in self.call("GET", f"me/todo/lists/{lst['id']}/tasks").get("value") or [] if t.get("status") != "completed"]

    def complete(self, words):
        lst, ts = self.open_tasks()
        hits = [t for t in ts if words.lower() in t["title"].lower()]
        if len(hits) != 1:
            return None, hits
        self.call("PATCH", f"me/todo/lists/{lst['id']}/tasks/{hits[0]['id']}", {"status": "completed"})
        return self.call("GET", f"me/todo/lists/{lst['id']}/tasks/{hits[0]['id']}"), hits

    def page(self, section, title, text):
        secs = self.call("GET", "me/onenote/sections").get("value") or []
        s = next((x for x in secs if x["displayName"].lower() == (section or "").lower()), secs[0] if secs else None)
        if not s:
            raise RuntimeError("no OneNote section to write into: make a notebook in OneNote first")
        body = (
            f"<!DOCTYPE html><html><head><title>{html.escape(title)}</title><meta name='created' content='{dt.datetime.now().isoformat(timespec='seconds')}'/>"
            "</head><body>" + "".join(f"<p>{html.escape(p)}</p>" for p in text.split("\n") if p.strip()) + "</body></html>"
        )
        p = self.call("POST", f"me/onenote/sections/{s['id']}/pages", data=body.encode("utf-8"), headers={"Content-Type": "text/html"})
        return s, p


def client(ctx):
    return (ctx.get("clients") or {}).get(NAME) or Client()


def parse(text, ctx):
    c = text.lower()
    m = re.match(r"^\s*onenote\s+page\s+['\"]([^'\"]+)['\"](?:\s+in\s+([\w ]+?))?\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        return {"op": "page", "title": m.group(1), "section": (m.group(2) or "").strip() or None, "text": m.group(3)}
    if not re.search(r"\bmicrosoft\b|\bms\s*to\s*do\b|\bto do app\b", c):
        return None
    m = re.match(r"^\s*(?:microsoft|ms)\s+to-?\s*do\s*:\s*(.+)$", text, re.I)
    if m:
        task = m.group(1).strip()
        day, _ = when(task.lower(), ctx.get("now") or dt.datetime.now())
        title = re.sub(r"\s+\b(?:by|on|due)\b\s+.*$", "", task, flags=re.I).strip() if day else task
        return {"op": "add", "title": title, "due": day.isoformat() if day else None}
    m = re.match(r"^\s*(?:complete|done|tick off)\s+(?:microsoft|ms)\s+task\s+(.+)$", text, re.I)
    if m:
        return {"op": "complete", "words": m.group(1).strip()}
    if re.search(r"\btasks?\b|\bto-?dos?\b", c):
        return {"op": "list"}
    return None


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "add":
        due = dt.date.fromisoformat(op["due"]) if op.get("due") else None
        lst, t, back = c.add(op["title"], due)
        ok = back.get("title") == op["title"] and (not due or (back.get("dueDateTime") or {}).get("dateTime", "").startswith(due.isoformat()))
        return (
            f"Added to Microsoft To Do ({lst['displayName']}): '{op['title']}'"
            + (f", due {due:%a %d %b}" if due else "")
            + (" (read back)." if ok else " (NOT the same when read back).")
        )
    if op["op"] == "list":
        lst, ts = c.open_tasks()
        return f"{len(ts)} open tasks in {lst['displayName']}:\n" + "\n".join(f"- {t['title']}" for t in ts) if ts else "No open tasks."
    if op["op"] == "complete":
        done, hits = c.complete(op["words"])
        if done is None:
            return "Which one? " + "; ".join(t["title"] for t in hits[:5]) if hits else f"No open task matches '{op['words']}'."
        return f"Ticked off '{done['title']}' ({done.get('status')})."
    s, p = c.page(op.get("section"), op["title"], op["text"])
    return f"OneNote page '{op['title']}' written in section {s['displayName']}: {(p.get('links') or {}).get('oneNoteWebUrl', {}).get('href', p.get('id'))}"
