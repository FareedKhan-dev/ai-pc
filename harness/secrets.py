"""API key loading. Keys come from the environment or a git-ignored file in the project; they are never logged."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_key(env_name="NEBIUS_API_KEY", filename="my_nebius.txt"):
    k = os.environ.get(env_name, "").strip()
    if not k:
        path = os.path.join(ROOT, filename)
        if os.path.exists(path):
            k = open(path, encoding="utf-8").read().strip()
    if not k:
        raise RuntimeError(f"no API key: set {env_name} or put it in {filename}")
    return k
