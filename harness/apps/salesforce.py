"""Salesforce (the most used CRM) by its REST API: your latest leads and open opportunities, a lead added after a yes
(read back from Salesforce), and leads counted by status. Sign-in once through your own Salesforce app (an External
Client App or Connected App with OAuth, PKCE, callback http://localhost:1717/OauthRedirect); the newest API version
your org offers is used.

  'salesforce leads'   'add salesforce lead: Ali Raza, Ali Traders, ali@x.com, 0300-1234567'   'salesforce opportunities'
  'salesforce leads by status'
"""
import base64
import hashlib
import re
import secrets
import time
import urllib.parse
import webbrowser

from ..hub import vault
from ..hub.http import Api, HubError

NAME, LABEL = "salesforce", "Salesforce CRM: leads, opportunities, add a lead, counts by status"
EXAMPLES = ["salesforce leads", "add salesforce lead: Ali Raza, Ali Traders, ali@x.com, 0300-1234567"]
OUTWARD = {"add"}
CALLBACK = "http://localhost:1717/OauthRedirect"
APP = {"label": "Salesforce", "fields": [("client_id", "Consumer key of your Salesforce app", False), ("client_secret", "Consumer secret", True),
                                         ("login", "Login address (Enter for https://login.salesforce.com)", False)],
       "steps": ["Salesforce Setup > App Manager (or External Client App Manager) > New: enable OAuth, callback http://localhost:1717/OauthRedirect, "
                 "scopes 'api' and 'refresh_token, offline_access', require PKCE.",
                 "Copy the consumer key and secret, run 'apps.py connect salesforce' and log in when the browser opens.",
                 "A free Developer Edition org (developer.salesforce.com/signup) works for trying it."]}


def _token(login, form, transport=None):
    try:
        return Api(login, service="salesforce sign-in", transport=transport).request(
            "POST", "services/oauth2/token", data=urllib.parse.urlencode(form).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, retries=1)
    except HubError as e:
        raise RuntimeError(f"Salesforce refused the sign-in ({e})") from e


class Client:
    def __init__(self, creds, transport=None):
        self.c, self.transport, self._base = creds, transport, None

    def _refresh(self):
        c = self.c
        tok = _token(c.get("login", "https://login.salesforce.com"), {"grant_type": "refresh_token", "refresh_token": c["refresh_token"], "client_id": c["client_id"],
                                                                     "client_secret": c.get("client_secret", "")}, self.transport)
        c.update(access_token=tok["access_token"], instance_url=tok.get("instance_url", c["instance_url"]))
        if self.transport is None:
            vault.put(NAME, {"access_token": c["access_token"], "instance_url": c["instance_url"]})

    def call(self, method, path, body=None, params=None, again=True):
        api = Api(self.c["instance_url"], headers={"Authorization": f"Bearer {self.c['access_token']}"}, service="salesforce", transport=self.transport)
        try:
            return api.request(method, path, json_body=body, params=params, retries=0 if method == "POST" else 3)
        except HubError as e:
            if e.status == 401 and again and self.c.get("refresh_token"):  # the session ended: a new one from the refresh token
                self._refresh()
                return self.call(method, path, body, params, again=False)
            b = e.body if isinstance(e.body, list) and e.body else [{}]
            raise RuntimeError(f"Salesforce: {b[0].get('message') if isinstance(b[0], dict) else e}") from e

    def base(self):
        if not self._base:
            versions = self.call("GET", "services/data/")
            self._base = max(versions, key=lambda v: float(v["version"]))["url"].lstrip("/")
        return self._base

    def query(self, soql):
        return self.call("GET", f"{self.base()}/query", params={"q": soql}).get("records") or []

    def add_lead(self, lead):
        r = self.call("POST", f"{self.base()}/sobjects/Lead", lead)
        return r["id"], self.call("GET", f"{self.base()}/sobjects/Lead/{r['id']}")


def client(ctx):
    inj = (ctx.get("clients") or {}).get(NAME)
    if inj:
        return inj
    c = vault.get(NAME)
    if not c:
        raise RuntimeError("Salesforce is not connected: 'apps.py steps salesforce' shows how")
    return Client(c)


def connect(values, transport=None, store=None, open_url=webbrowser.open, show=print, timeout=300):
    from ..accounts.systems.loop import loopback_localhost
    login = (values.get("login") or "https://login.salesforce.com").rstrip("/")
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    def build(redirect, state):
        return f"{login}/services/oauth2/authorize?" + urllib.parse.urlencode({"response_type": "code", "client_id": values["client_id"], "redirect_uri": redirect,
                                                                               "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    got, redirect = loopback_localhost(build, 1717, "/OauthRedirect", show=show, open_url=open_url, timeout=timeout, who="Salesforce")
    tok = _token(login, {"grant_type": "authorization_code", "code": got["code"], "client_id": values["client_id"], "client_secret": values.get("client_secret", ""),
                         "redirect_uri": redirect, "code_verifier": verifier}, transport)
    creds = {"client_id": values["client_id"], "client_secret": values.get("client_secret", ""), "login": login, "access_token": tok["access_token"],
             "refresh_token": tok.get("refresh_token", ""), "instance_url": tok["instance_url"]}
    (store or (lambda v: vault.put(NAME, v)))(creds)
    return {"who": tok["instance_url"], "where": "Salesforce"}


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bsalesforce\b", c):
        return None
    m = re.search(r"\badd\s+(?:a\s+)?salesforce\s+lead\s*:?\s*(.+)$", text, re.I)
    if m:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        lead = {}
        first, _, last = parts[0].rpartition(" ")
        lead.update(FirstName=first or None, LastName=last or parts[0])
        for p in parts[1:]:
            if re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", p):
                lead["Email"] = p
            elif re.fullmatch(r"[+\d][\d\s-]{6,}", p):
                lead["Phone"] = p
            elif "Company" not in lead:
                lead["Company"] = p
        lead.setdefault("Company", lead["LastName"])  # Salesforce needs a company for a lead
        return {"op": "add", "lead": {k: v for k, v in lead.items() if v}}
    if re.search(r"\bleads?\s+by\s+status\b", c):
        return {"op": "by_status"}
    if re.search(r"\bopportunit", c):
        return {"op": "opps"}
    if re.search(r"\bleads?\b", c):
        return {"op": "leads"}
    return None


def preview(op, ctx):
    return "Ready to add a Salesforce lead: " + ", ".join(f"{k} {v}" for k, v in op["lead"].items()) + "."


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "leads":
        rs = c.query("SELECT Id, Name, Company, Status, Email FROM Lead ORDER BY CreatedDate DESC LIMIT 10")
        return "\n".join(f"- {r['Name']} ({r.get('Company')}): {r.get('Status')}" for r in rs) or "No leads yet."
    if op["op"] == "opps":
        rs = c.query("SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity WHERE IsClosed = false ORDER BY CloseDate LIMIT 10")
        return "\n".join(f"- {r['Name']}: {r.get('StageName')}, {r.get('Amount') or 0:,.0f}, closes {r.get('CloseDate')}" for r in rs) or "No open opportunities."
    if op["op"] == "by_status":
        rs = c.query("SELECT Status, COUNT(Id) n FROM Lead GROUP BY Status")
        return "Leads by status: " + ", ".join(f"{r['Status']} {r['n']}" for r in rs) + "."
    if not op.get("confirmed"):
        return preview(op, ctx)
    lid, back = c.add_lead(op["lead"])
    ok = all(back.get(k) == v for k, v in op["lead"].items())
    return f"Lead {lid} added to Salesforce ({'read back: the same details' if ok else 'NOT the same when read back'})."
