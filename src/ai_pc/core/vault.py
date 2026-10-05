"""API keys kept on this PC, encrypted with Windows' own data protection (DPAPI, tied to this Windows user): another
user, or a copy of the file on another PC, cannot read them. Keys are typed by the person at a hidden prompt
(ai-pc hub connect <service>); they are never printed, logged or sent to the language model.

  put("slack", {"bot_token": "xoxb-..."})   get("slack") -> dict | None   names() -> ["slack", ...]   remove("slack")
"""

import json
import threading

from ai_pc.core.config import ROOT

FILE = ROOT / "state" / "hub" / "vault.bin"
_LOCK = threading.Lock()
_ENTROPY = b"aipc-hub-vault-v1"


def _load():
    if not FILE.exists():
        return {}
    import win32crypt

    raw = win32crypt.CryptUnprotectData(FILE.read_bytes(), _ENTROPY, None, None, 0)[1]
    return json.loads(raw.decode("utf-8"))


def _save(d):
    import win32crypt

    FILE.parent.mkdir(parents=True, exist_ok=True)
    blob = win32crypt.CryptProtectData(json.dumps(d).encode("utf-8"), "AI PC hub keys", _ENTROPY, None, None, 0)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(FILE)


def put(service, values):
    with _LOCK:
        d = _load()
        d[service] = {**d.get(service, {}), **values}
        _save(d)


def get(service):
    with _LOCK:
        return _load().get(service)


def names():
    with _LOCK:
        return sorted(_load())


def remove(service):
    with _LOCK:
        d = _load()
        if d.pop(service, None) is not None:
            _save(d)
            return True
        return False


def redact(text, service=None):
    """Any stored secret that appears in text, replaced by '***' (for logs and error messages)."""
    s = str(text)
    with _LOCK:
        d = _load()
    for svc, vals in d.items():
        if service and svc != service:
            continue
        for v in vals.values():
            if isinstance(v, str) and len(v) >= 8:
                s = s.replace(v, "***")
    return s
