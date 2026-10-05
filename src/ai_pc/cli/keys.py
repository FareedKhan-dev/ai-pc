"""API keys kept in this PC's encrypted vault (Windows DPAPI: readable only by this Windows user on this PC).

  ai-pc keys set NEBIUS_API_KEY       type the key at a hidden prompt
  ai-pc keys list                     the names stored (never the keys)
  ai-pc keys remove NEBIUS_API_KEY

The environment and a .env file in the project folder are read first (see src/ai_pc/core/keys.py).
"""
import argparse
import getpass
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ai-pc keys", description="API keys in this PC's encrypted vault")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help="store a key (typed at a hidden prompt)")
    s.add_argument("name", help="the key's environment name, e.g. NEBIUS_API_KEY")
    sub.add_parser("list", help="the names of the keys stored")
    r = sub.add_parser("remove", help="forget a key")
    r.add_argument("name")
    a = ap.parse_args(argv)
    from ai_pc.core import vault
    from ai_pc.core.keys import VAULT_ENTRY
    keys = vault.get(VAULT_ENTRY) or {}
    if a.cmd == "list":
        print("\n".join(sorted(keys)) if keys else "(no keys stored)")
        return 0
    name = a.name.strip().upper()
    if a.cmd == "set":
        value = getpass.getpass(f"{name} (hidden): ").strip()
        if not value:
            print("nothing typed: no change", file=sys.stderr)
            return 1
        vault.put(VAULT_ENTRY, {name: value})
        print(f"stored {name}")
        return 0
    if name not in keys:
        print(f"{name} is not stored", file=sys.stderr)
        return 1
    keys.pop(name)
    vault.remove(VAULT_ENTRY)
    if keys:
        vault.put(VAULT_ENTRY, keys)
    print(f"removed {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
