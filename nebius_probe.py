"""List the models available on the user's Nebius account. The key is read from the environment or my_nebius.txt
and is never printed."""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_key():
    k = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not k:
        k = open(os.path.join(ROOT, "my_nebius.txt"), encoding="utf-8").read().strip()
    return k


KEY = load_key()
BASES = ["https://api.tokenfactory.nebius.com/v1", "https://api.studio.nebius.com/v1"]


def get(base, path):
    req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + KEY, "Accept": "application/json", "User-Agent": "computer-use-harness/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


good = None
for base in BASES:
    status, body = get(base, "/models")
    n = len(body.get("data", [])) if isinstance(body, dict) else "-"
    print(f"{base:48s} -> HTTP {status}, models: {n}")
    if status == 200 and good is None:
        good = (base, body)
    elif status != 200:
        print("   ", str(body)[:200])

if not good:
    sys.exit("no working endpoint")
base, body = good
status, verbose = get(base, "/models?verbose=true")
data = verbose["data"] if status == 200 and isinstance(verbose, dict) else body["data"]
print(f"\nusing {base} | verbose listing: HTTP {status} | {len(data)} models")
print("fields per model:", sorted({k for m in data for k in m}))
json.dump(data, open(os.path.join(ROOT, "out", "nebius_models.json"), "w"), indent=1)
for m in sorted(data, key=lambda m: m["id"].lower()):
    extras = {k: v for k, v in m.items() if k not in ("id", "object", "created", "owned_by", "name")}
    print(f"  {m['id']:62s} {json.dumps(extras)[:150] if extras else ''}")
