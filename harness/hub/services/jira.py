"""Jira Cloud through its REST API v3 (email and API token): projects, issues by JQL, create an issue, move it through its
workflow, comment. Every issue made is read back."""
import base64

from ..http import Api, HubError
from . import Base, norm


def adf(text):
    """Plain text as Atlassian Document Format (one paragraph per line)."""
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": ln}] if ln else []}
                                                     for ln in (text or "").split("\n")]}


class Jira(Base):
    name = "jira"

    def api(self):
        self.need("site", "email", "token")
        site = self.creds["site"].replace("https://", "").replace("http://", "").strip("/")
        basic = base64.b64encode(f"{self.creds['email']}:{self.creds['token']}".encode()).decode()
        self.site = site
        return Api(f"https://{site}/rest/api/3", headers={"Authorization": f"Basic {basic}"}, service="jira", transport=self.transport)

    def whoami(self):
        me = self.api().get("myself")
        return {"who": me.get("displayName"), "where": self.site}

    def projects(self):
        return [{"id": p["id"], "key": p["key"], "name": p["name"]} for p in self.api().get("project/search", params={"maxResults": 50}).get("values", [])]

    def project(self, name=None):
        ps = self.projects()
        if not ps:
            raise HubError("jira: no projects")
        if not name:
            return ps[0]
        hit = next((p for p in ps if norm(p["key"]) == norm(name) or norm(p["name"]) == norm(name)), None) or \
            next((p for p in ps if norm(name) in norm(p["name"])), None)
        if not hit:
            raise HubError(f"jira: no project {name} (projects: {', '.join(p['key'] for p in ps[:8])})")
        return hit

    def search(self, jql="assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC", n=20):
        js = self.api().post("search/jql", json={"jql": jql, "maxResults": n, "fields": ["summary", "status", "priority", "duedate", "assignee"]})
        return {"where": "Jira", "issues": [{"key": i["key"], "summary": i["fields"].get("summary"), "status": (i["fields"].get("status") or {}).get("name"),
                                             "url": f"https://{self.site}/browse/{i['key']}"} for i in js.get("issues", [])]}

    def create(self, summary, project=None, kind="Task", description=None):
        p = self.project(project)
        fields = {"project": {"key": p["key"]}, "summary": summary, "issuetype": {"name": kind}}
        if description:
            fields["description"] = adf(description)
        try:
            i = self.api().post("issue", json={"fields": fields})
        except HubError as e:
            if kind != "Task" and "issuetype" in str(e.body):
                fields["issuetype"] = {"name": "Task"}
                i = self.api().post("issue", json={"fields": fields})
            else:
                raise
        back = self.api().get(f"issue/{i['key']}", params={"fields": "summary"})
        return {"id": i["key"], "where": p["name"], "url": f"https://{self.site}/browse/{i['key']}", "name": summary,
                "verified": (back.get("fields") or {}).get("summary") == summary, "undo": {"service": "jira", "op": "delete", "id": i["key"]}}

    def move(self, key, to_status):
        ts = self.api().get(f"issue/{key}/transitions").get("transitions", [])
        t = next((x for x in ts if norm(x["name"]) == norm(to_status) or norm((x.get("to") or {}).get("name")) == norm(to_status)), None)
        if not t:
            raise HubError(f"jira: {key} cannot go to {to_status} (can go to: {', '.join(x['name'] for x in ts)})")
        before = (self.api().get(f"issue/{key}", params={"fields": "status"}).get("fields") or {}).get("status", {}).get("name")
        self.api().post(f"issue/{key}/transitions", json={"transition": {"id": t["id"]}})
        after = (self.api().get(f"issue/{key}", params={"fields": "status"}).get("fields") or {}).get("status", {}).get("name")
        return {"id": key, "where": f"{before} -> {after}", "url": f"https://{self.site}/browse/{key}", "verified": norm(after) != norm(before),
                "undo": {"service": "jira", "op": "move", "key": key, "to_status": before}}

    def comment(self, key, text):
        c = self.api().post(f"issue/{key}/comment", json={"body": adf(text)})
        return {"id": c["id"], "where": key, "url": f"https://{self.site}/browse/{key}", "verified": True,
                "undo": {"service": "jira", "op": "delete_comment", "key": key, "id": c["id"]}}

    def delete_comment(self, key, id):  # noqa: A002
        self.api().delete(f"issue/{key}/comment/{id}")
        return {"deleted": id}

    def delete(self, id):  # noqa: A002
        self.api().delete(f"issue/{id}")
        return {"deleted": id}
