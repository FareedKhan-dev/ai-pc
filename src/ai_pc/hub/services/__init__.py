"""One connector per service, all on ai_pc.hub.http.Api (tests pass a FakeTransport). connector("slack") -> Slack()."""

import importlib

from ai_pc.core import vault
from ai_pc.hub.http import HubError

MODULES = {
    "slack": "slack",
    "telegram": "telegram",
    "trello": "trello",
    "notion": "notion",
    "google": "google",
    "microsoft": "microsoft",
    "hubspot": "hubspot",
    "asana": "asana",
    "jira": "jira",
    "zoom": "zoom",
    "whatsapp": "whatsapp",
    "figma": "figma",
    "canva": "canva",
}


class Base:
    name = ""

    def __init__(self, creds=None, transport=None):
        self.creds = creds if creds is not None else (vault.get(self.name) or {})
        self.transport = transport

    def need(self, *keys):
        missing = [k for k in keys if not self.creds.get(k)]
        if missing:
            raise HubError(f"{self.name.title()} is not connected: run ai-pc hub connect {self.name}")


def connector(name, creds=None, transport=None):
    mod = importlib.import_module(f".{MODULES[name]}", __name__)
    cls = next(v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Base) and v is not Base and v.name == name)
    return cls(creds, transport)


def connected():
    """The services that have keys in the vault."""
    return [n for n in vault.names() if n in MODULES]


def norm(s):
    return " ".join(str(s or "").lower().replace("#", "").replace("@", "").split())


def pick(items, want, key="name"):
    """The item whose name matches: exact, then starting with, then containing (case-insensitive)."""
    w = norm(want)
    names = [(norm(i.get(key)), i) for i in items]
    for test in (lambda n: n == w, lambda n: n.startswith(w), lambda n: w in n):
        hits = [i for n, i in names if test(n)]
        if hits:
            return hits[0]
    return None
