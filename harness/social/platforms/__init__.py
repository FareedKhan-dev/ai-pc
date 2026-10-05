"""One connector per platform, all on harness.hub.http.Api (tests pass a fake transport).

  connector("youtube") -> YouTube()       connected(store) -> {name: connector} for the platforms with keys in the vault
"""
import importlib

from ..base import Platform

MODULES = {"facebook": "meta", "instagram": "meta", "threads": "threads", "youtube": "youtube", "tiktok": "tiktok", "linkedin": "linkedin", "x": "xcom"}


def _cls(name):
    mod = importlib.import_module(f".{MODULES[name]}", __name__)
    return next(v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Platform) and v is not Platform and v.name == name)


def connector(name, creds=None, transport=None, store=None):
    return _cls(name)(creds, transport, store)


def connected(store=None):
    from ...hub import vault
    have = set(vault.names())
    out = {}
    for n in MODULES:
        try:
            cls = _cls(n)
        except (ImportError, StopIteration):
            continue
        if (cls.vault_key or n) in have:
            p = cls(None, None, store)
            if p.ready():
                out[n] = p
    return out
