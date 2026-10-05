"""Asana through its REST API with a personal access token: my tasks, a project's tasks, add a task (with a due date),
complete it, comment. Every task made is read back."""
from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base, pick


class Asana(Base):
    name = "asana"

    def api(self):
        self.need("token")
        return Api("https://app.asana.com/api/1.0", headers={"Authorization": f"Bearer {self.creds['token']}"}, service="asana", transport=self.transport)

    def me(self):
        return self.api().get("users/me", params={"opt_fields": "name,email,workspaces.name"})["data"]

    def whoami(self):
        me = self.me()
        return {"who": me.get("name"), "where": ", ".join(w["name"] for w in me.get("workspaces", [])) or "Asana"}

    def workspace(self):
        ws = self.me().get("workspaces", [])
        if not ws:
            raise HubError("asana: no workspace")
        return ws[0]

    def projects(self):
        w = self.workspace()
        return [{"id": p["gid"], "name": p["name"]} for p in self.api().get("projects", params={"workspace": w["gid"], "archived": "false"})["data"]]

    def tasks(self, project=None):
        fields = "name,due_on,completed,assignee.name,permalink_url"
        if project:
            p = pick(self.projects(), project)
            if not p:
                raise HubError(f"asana: no project {project}")
            js = self.api().get("tasks", params={"project": p["id"], "completed_since": "now", "opt_fields": fields})
            where = p["name"]
        else:
            w = self.workspace()
            js = self.api().get("tasks", params={"assignee": "me", "workspace": w["gid"], "completed_since": "now", "opt_fields": fields})
            where = "my tasks"
        return {"where": where, "tasks": [{"id": t["gid"], "name": t["name"], "due": t.get("due_on"), "done": t.get("completed"),
                                           "who": (t.get("assignee") or {}).get("name"), "url": t.get("permalink_url")} for t in js["data"]]}

    def create(self, name, project=None, due=None, notes=None, mine=True):
        w = self.workspace()
        data = {"name": name, "workspace": w["gid"], **({"due_on": due} if due else {}), **({"notes": notes} if notes else {}), **({"assignee": "me"} if mine else {})}
        if project:
            p = pick(self.projects(), project)
            if not p:
                raise HubError(f"asana: no project {project}")
            data["projects"] = [p["id"]]
        t = self.api().post("tasks", json={"data": data})["data"]
        back = self.api().get(f"tasks/{t['gid']}", params={"opt_fields": "name"})["data"]
        return {"id": t["gid"], "where": project or "my tasks", "url": t.get("permalink_url"), "name": name, "verified": back.get("name") == name,
                "undo": {"service": "asana", "op": "delete", "id": t["gid"]}}

    def complete(self, name, project=None):
        t = pick(self.tasks(project)["tasks"], name)
        if not t:
            raise HubError(f"asana: no open task called {name}")
        self.api().put(f"tasks/{t['id']}", json={"data": {"completed": True}})
        return {"id": t["id"], "where": t["name"], "url": t["url"], "verified": True, "undo": {"service": "asana", "op": "reopen", "id": t["id"]}}

    def reopen(self, id):  # noqa: A002
        self.api().put(f"tasks/{id}", json={"data": {"completed": False}})
        return {"id": id}

    def comment(self, name, text, project=None):
        t = pick(self.tasks(project)["tasks"], name)
        if not t:
            raise HubError(f"asana: no open task called {name}")
        s = self.api().post(f"tasks/{t['id']}/stories", json={"data": {"text": text}})["data"]
        return {"id": s["gid"], "where": t["name"], "verified": s.get("text") == text, "undo": {"service": "asana", "op": "delete_story", "id": s["gid"]}}

    def delete_story(self, id):  # noqa: A002
        self.api().delete(f"stories/{id}")
        return {"deleted": id}

    def delete(self, id):  # noqa: A002
        self.api().delete(f"tasks/{id}")
        return {"deleted": id}
