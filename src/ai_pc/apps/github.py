"""GitHub (REST API) with a fine-grained personal access token: your repositories listed, a new repository made (private
unless you say public), a project folder pushed to it with git (the token goes in a header for that one push, never
into the folder's git settings) and the push checked against GitHub's own copy, and issues listed and opened.
Making repositories, pushing and opening issues are shown first and done after a yes.

  'github repos'   "create github repo 'shop-site'"   'push D:\\Projects\\shop-site to github repo shop-site'
  'github issues in shop-site'   "open github issue in shop-site: 'Checkout button broken'"
"""
import base64
import re
import subprocess
from pathlib import Path

from ai_pc.core import vault
from ai_pc.hub.http import Api, HubError

NAME, LABEL = "github", "GitHub: repositories, push a project, issues"
EXAMPLES = ["github repos", "create github repo 'shop-site'", "push D:\\Projects\\shop-site to github repo shop-site"]
OUTWARD = {"create", "push", "issue"}
APP = {"label": "GitHub", "fields": [("token", "Fine-grained personal access token", True)],
       "steps": ["github.com > Settings > Developer settings > Personal access tokens > Fine-grained tokens > Generate new token.",
                 "Repository access: All repositories (or the ones you choose). Permissions: Administration (read and write, to create repositories), Contents "
                 "(read and write, to push), Issues (read and write), Metadata (read).",
                 "Run 'ai-pc apps connect github' and paste the token (kept encrypted)."]}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Client:
    def __init__(self, token, transport=None):
        self.token = token
        self.api = Api("https://api.github.com", headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                         "X-GitHub-Api-Version": "2022-11-28"}, service="github", transport=transport)
        self._me = None

    def call(self, method, path, body=None, **kw):
        try:
            return self.api.request(method, path, json_body=body, retries=0 if method == "POST" else 3, **kw)
        except HubError as e:
            b = e.body if isinstance(e.body, dict) else {}
            raise RuntimeError(f"GitHub: {b.get('message') or e}" + ("".join(f"; {x.get('message', x.get('code'))}" for x in b.get("errors") or []))) from e

    def me(self):
        if not self._me:
            self._me = self.call("GET", "user")["login"]
        return self._me

    def repos(self):
        return self.call("GET", "user/repos", params={"sort": "updated", "per_page": 30})

    def repo(self, name):
        return self.call("GET", f"repos/{self.me()}/{name}") if "/" not in name else self.call("GET", f"repos/{name}")

    def create(self, name, private=True, description=""):
        return self.call("POST", "user/repos", {"name": name, "private": private, "description": description, "auto_init": False})

    def push(self, folder, name, message="Pushed by AI PC"):
        folder = Path(folder)
        r = self.repo(name)
        git = ["git", "-C", str(folder)]

        def run(*args, check=True):
            p = subprocess.run(git + list(args), capture_output=True, text=True, creationflags=NOWIN)
            if check and p.returncode:
                raise RuntimeError(f"git {args[0]}: {(p.stderr or p.stdout).strip()[:300]}")
            return p.stdout.strip()
        if not (folder / ".git").exists():
            run("init", "-b", "main")
        run("add", "-A")
        if run("status", "--porcelain"):
            run("-c", "user.name=AI PC", "-c", f"user.email={self.me()}@users.noreply.github.com", "commit", "-m", message)
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        head = run("rev-parse", "HEAD")
        auth = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        run("-c", f"http.extraHeader=Authorization: Basic {auth}", "push", r["clone_url"], f"HEAD:refs/heads/{branch}")
        remote = self.call("GET", f"repos/{r['full_name']}/commits/{branch}")["sha"]
        return {"branch": branch, "head": head, "remote": remote, "url": r["html_url"]}

    def issues(self, name):
        return [i for i in self.call("GET", f"repos/{self.repo(name)['full_name']}/issues", params={"state": "open", "per_page": 30}) if "pull_request" not in i]

    def issue(self, name, title, body=""):
        return self.call("POST", f"repos/{self.repo(name)['full_name']}/issues", {"title": title, "body": body})


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("GitHub is not connected: 'ai-pc apps steps github' shows how")
    return Client(c["token"])


def connect(values, transport=None, store=None):
    who = Client(values["token"], transport).me()
    (store or (lambda v: vault.put(NAME, v)))({"token": values["token"]})
    return {"who": who, "where": "GitHub"}


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bgithub\b", c):
        return None
    m = re.search(r"\b(?:create|make|new)\s+(?:a\s+)?(?:(public|private)\s+)?github\s+repo(?:sitory)?\s+['\"]?([\w.-]+)['\"]?(?:\s+(public|private))?", text, re.I)
    if m:
        return {"op": "create", "name": m.group(2), "private": (m.group(1) or m.group(3) or "private").lower() != "public"}
    m = re.search(r"\bpush\s+(.+?)\s+to\s+github(?:\s+repo(?:sitory)?)?\s+['\"]?([\w./-]+)['\"]?\s*$", text, re.I)
    if m:
        return {"op": "push", "folder": m.group(1).strip(" '\""), "name": m.group(2)}
    m = re.search(r"\b(?:open|create|new|file)\s+(?:a\s+)?github\s+issue\s+(?:in|on|for)\s+([\w./-]+)\s*:\s*['\"]([^'\"]+)['\"](?:\s*[,:-]?\s*(.+))?$", text, re.I | re.S)
    if m:
        return {"op": "issue", "name": m.group(1), "title": m.group(2), "body": (m.group(3) or "").strip()}
    m = re.search(r"\bgithub\s+issues\s+(?:in|on|for)\s+([\w./-]+)", text, re.I)
    if m:
        return {"op": "issues", "name": m.group(1)}
    if re.search(r"\b(?:repos|repositories|projects)\b", c):
        return {"op": "repos"}
    return None


def preview(op, ctx):
    if op["op"] == "create":
        return f"Ready to create the {'private' if op['private'] else 'PUBLIC'} GitHub repository '{op['name']}'."
    if op["op"] == "push":
        files = sum(1 for p in Path(op["folder"]).rglob("*") if p.is_file() and ".git" not in p.parts) if Path(op["folder"]).exists() else 0
        return f"Ready to commit and push {op['folder']} ({files} files) to GitHub repository '{op['name']}'."
    return f"Ready to open an issue in '{op['name']}': '{op['title']}'."


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "repos":
        rs = c.repos()
        return "\n".join(f"- {r['full_name']} ({'private' if r['private'] else 'public'}), updated {r['updated_at'][:10]}" for r in rs) or "No repositories yet."
    if op["op"] == "issues":
        iss = c.issues(op["name"])
        return "\n".join(f"- #{i['number']} {i['title']}" for i in iss) or f"No open issues in {op['name']}."
    if not op.get("confirmed"):
        return preview(op, ctx)
    if op["op"] == "create":
        c.create(op["name"], op["private"])
        back = c.repo(op["name"])
        return f"Created {back['full_name']} ({'private' if back['private'] else 'public'}, read back): {back['html_url']}"
    if op["op"] == "push":
        if not Path(op["folder"]).is_dir():
            return f"{op['folder']} is not a folder."
        p = c.push(op["folder"], op["name"])
        return f"Pushed branch {p['branch']} to {p['url']} (" + ("checked: GitHub's latest commit is this folder's" if p["remote"] == p["head"] else
                                                               f"NOT the same: GitHub has {p['remote'][:7]}, the folder {p['head'][:7]}") + ")."
    i = c.issue(op["name"], op["title"], op.get("body", ""))
    return f"Opened issue #{i['number']}: {i['html_url']}"
