"""Notion through its API (the integration sees only pages shared with it): find pages and databases, read a database,
add a row (a page) with a title, status and date, add text to a page, archive. Every page made is read back."""

from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base, norm

VERSION = "2022-06-28"


def _title(obj):
    props = obj.get("properties") or {}
    for p in props.values():
        if p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in p.get("title", []))
    t = obj.get("title")
    if isinstance(t, list):
        return "".join(x.get("plain_text", "") for x in t)
    return ""


class Notion(Base):
    name = "notion"

    def api(self):
        self.need("token")
        return Api(
            "https://api.notion.com/v1",
            headers={"Authorization": f"Bearer {self.creds['token']}", "Notion-Version": VERSION},
            service="notion",
            transport=self.transport,
        )

    def whoami(self):
        me = self.api().get("users/me")
        return {"who": me.get("name") or "integration", "where": (me.get("bot") or {}).get("workspace_name") or "Notion"}

    def search(self, query="", kind=None):
        body = {"query": query, "page_size": 50}
        if kind:
            body["filter"] = {"value": kind, "property": "object"}
        res = self.api().post("search", json=body).get("results", [])
        return [{"id": r["id"], "kind": r["object"], "title": _title(r) or "(untitled)", "url": r.get("url")} for r in res]

    def database(self, name):
        dbs = self.search(name, "database")
        hit = next((d for d in dbs if norm(d["title"]) == norm(name)), None) or (dbs[0] if dbs else None)
        if not hit:
            raise HubError(f"notion: no database called {name} is shared with the integration")
        schema = self.api().get(f"databases/{hit['id']}")
        return dict(
            hit,
            props={k: v["type"] for k, v in schema.get("properties", {}).items()},
            options={
                k: [o["name"] for o in (v.get(v["type"]) or {}).get("options", [])]
                for k, v in schema.get("properties", {}).items()
                if v["type"] in ("select", "status", "multi_select")
            },
        )

    def rows(self, db_name, limit=50):
        db = self.database(db_name)
        res = self.api().post(f"databases/{db['id']}/query", json={"page_size": limit}).get("results", [])
        out = []
        for r in res:
            row = {"id": r["id"], "title": _title(r), "url": r.get("url")}
            for k, v in (r.get("properties") or {}).items():
                t = v.get("type")
                if t in ("select", "status") and v.get(t):
                    row[k] = v[t]["name"]
                elif t == "date" and v.get("date"):
                    row[k] = v["date"].get("start")
            out.append(row)
        return {"where": db["title"], "rows": out}

    def add_row(self, db_name, title, status=None, date=None, note=None):
        db = self.database(db_name)
        tkey = next(k for k, t in db["props"].items() if t == "title")
        props = {tkey: {"title": [{"text": {"content": title}}]}}
        if status:
            sk = next((k for k, t in db["props"].items() if t in ("status", "select")), None)
            if sk:
                opts = db["options"].get(sk, [])
                val = next((o for o in opts if norm(o) == norm(status)), None) or next((o for o in opts if norm(status) in norm(o)), None)
                if val:
                    props[sk] = {db["props"][sk]: {"name": val}}
        if date:
            dk = next((k for k, t in db["props"].items() if t == "date"), None)
            if dk:
                props[dk] = {"date": {"start": date}}
        body = {"parent": {"database_id": db["id"]}, "properties": props}
        if note:
            body["children"] = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": note}}]}}]
        page = self.api().post("pages", json=body)
        back = self.api().get(f"pages/{page['id']}")
        return {
            "id": page["id"],
            "url": page.get("url"),
            "where": db["title"],
            "name": title,
            "verified": _title(back) == title,
            "undo": {"service": "notion", "op": "archive", "id": page["id"]},
        }

    def add_text(self, page_name, text):
        pages = self.search(page_name, "page")
        p = next((x for x in pages if norm(x["title"]) == norm(page_name)), None) or (pages[0] if pages else None)
        if not p:
            raise HubError(f"notion: no page called {page_name} is shared with the integration")
        res = self.api().patch(
            f"blocks/{p['id']}/children",
            json={"children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}]},
        )
        bid = (res.get("results") or [{}])[0].get("id")
        return {
            "id": bid,
            "url": p["url"],
            "where": p["title"],
            "verified": bool(bid),
            "undo": {"service": "notion", "op": "delete_block", "id": bid},
        }

    def archive(self, id):  # noqa: A002
        self.api().patch(f"pages/{id}", json={"archived": True})
        return {"archived": id}

    def delete_block(self, id):  # noqa: A002
        self.api().delete(f"blocks/{id}")
        return {"deleted": id}
