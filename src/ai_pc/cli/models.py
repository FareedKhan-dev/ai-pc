"""Choose the language-model provider and model.

  ai-pc models                          the providers, their default models and whether their key is here
  ai-pc models show                     the provider and the model each role uses now
  ai-pc models use groq                 use Groq from now on (its key: ai-pc keys set GROQ_API_KEY)
  ai-pc models use openrouter --model qwen/qwen3-vl-30b-a3b-instruct --price 0.15,0.6
  ai-pc models use ollama --model gemma3 --base-url http://127.0.0.1:11434/v1
  ai-pc models list [provider]          the models the provider offers (asks the provider)
  ai-pc models test [provider]          one short request: does it answer, and how fast
  ai-pc models reset                    back to the default (Nebius Token Factory)

The choice is saved in state/models.json; AI_PC_PROVIDER, AI_PC_MODEL and AI_PC_BASE_URL in the environment win over it.
Keys are never printed: only whether one is set.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

from ai_pc.llm import providers as P
from ai_pc.llm.client import LLMError


def _table() -> int:
    try:
        now = P.active().id
    except ValueError:
        now = ""
    w = max(len(p.id) for p in P.PRESETS)
    print(f"  {'':2}{'provider':<{w}}  {'name':<30} {'default model':<46} key")
    for p in P.PRESETS:
        mark = "* " if p.id == now else "  "
        key = "not needed" if p.key is None else f"{p.key} ({P.key_status(p)})"
        model = p.model or "(choose one)"
        print(f"  {mark}{p.id:<{w}}  {p.name:<30} {model[:45]:<46} {key}")
    print("\n* in use. Change it with 'ai-pc models use <provider>'; any OpenAI-compatible server works as 'custom'.")
    return 0


def _show() -> int:
    d = P.describe()
    print(f"Provider: {d['name']} ({d['provider']})")
    if d.get("problem"):
        print(f"  {d['problem']}")
        return 1
    print(f"Address:  {d['base_url']}")
    print(f"Key:      {d['key'] or '(none)'}: {d['key_status']}")
    for role, m in d["models"].items():
        print(f"  {role:<9} {m}")
    return 0


def _use(a: argparse.Namespace) -> int:
    if a.provider not in P.PROVIDERS:
        print(f"Unknown provider '{a.provider}'. Choose one of: {', '.join(P.PROVIDERS)}", file=sys.stderr)
        return 2
    p = P.PROVIDERS[a.provider]
    s: dict[str, Any] = {"provider": p.id}
    if a.model:
        s["model"] = a.model
    if a.base_url:
        s["base_url"] = a.base_url
    old = P.settings()
    prices = dict(old.get("prices") or {})
    if a.price:
        try:
            pin, pout = (float(x) for x in a.price.split(","))
        except ValueError:
            print("--price takes input and output prices in USD per million tokens, e.g. 0.15,0.6", file=sys.stderr)
            return 2
        prices[a.model or p.model] = [pin, pout]
    if prices:
        s["prices"] = prices
    if not (a.model or p.model):
        print(f"{p.name} has no default model: add --model <id> ('ai-pc models list {p.id}' shows them).", file=sys.stderr)
        return 2
    if not (a.base_url or p.base_url):
        print(f"{p.name} needs --base-url <address of its OpenAI-compatible API>.", file=sys.stderr)
        return 2
    P.save_settings(s)
    print(f"Using {p.name}, model {a.model or p.model}.")
    if p.key and P.key_status(p) == "missing":
        print(f"Its key is not set yet: ai-pc keys set {p.key}")
    if not p.vision and not a.model:
        print("Its default model does not read images: the desktop agent's vision and the picture checks need one that does.")
    return 0


def _get_models(p: P.Provider) -> list[str]:
    req = urllib.request.Request(P.base_url(p) + "/models", headers={"User-Agent": "ai-pc/0.1", **dict(p.headers)})
    key = P.api_key(p)
    if key:
        req.add_header("Authorization", "Bearer " + key)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    items = d.get("data") if isinstance(d, dict) else d
    return sorted(str(m.get("id")) for m in items or [] if isinstance(m, dict) and m.get("id"))


def _list(a: argparse.Namespace) -> int:
    p = P.PROVIDERS[a.provider] if a.provider else P.active()
    try:
        names = _get_models(p)
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
        print(f"{p.name}: could not list its models ({type(e).__name__}: {str(e)[:200]})", file=sys.stderr)
        return 1
    for n in names:
        print(n)
    print(f"({len(names)} models from {p.name})")
    return 0


def _test(a: argparse.Namespace) -> int:
    p = P.PROVIDERS[a.provider] if a.provider else P.active()
    try:
        cfg = P.role("fast", p)  # the same model and switches a real request uses (a reasoning model needs room to think)
        msgs = [{"role": "user", "content": "Reply with the single word OK."}]
        r = P.chat(p, timeout=60, deadline=90).complete(cfg["model"], msgs, max_tokens=400, extra=cfg["extra"] or None, retries=1)
    except (LLMError, ValueError, RuntimeError) as e:
        print(f"{p.name} did not answer: {str(e)[:300]}", file=sys.stderr)
        return 1
    said = r.text.strip()[:40] or ("(only reasoning, no answer)" if r.reasoning else "(empty)")
    print(f"{p.name}, {cfg['model']}: '{said}' in {r.total_ms / 1000:.1f} s (first token {r.ttft_ms / 1000:.1f} s)")
    return 0 if r.text.strip() else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ai-pc models", description="choose the language-model provider and model")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("show", help="the provider and the model each role uses now")
    u = sub.add_parser("use", help="use a provider (and optionally a model, an address and a price)")
    u.add_argument("provider")
    u.add_argument("--model", help="the model id for every role")
    u.add_argument("--base-url", help="the address of its OpenAI-compatible API (for local or custom servers)")
    u.add_argument("--price", help="USD per million tokens, input,output (for the cost line of each reply)")
    li = sub.add_parser("list", help="the models a provider offers")
    li.add_argument("provider", nargs="?")
    t = sub.add_parser("test", help="one short request to a provider")
    t.add_argument("provider", nargs="?")
    sub.add_parser("reset", help="back to the default provider")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        return _show()
    if a.cmd == "use":
        return _use(a)
    if a.cmd == "list":
        return _list(a)
    if a.cmd == "test":
        return _test(a)
    if a.cmd == "reset":
        P.SETTINGS.unlink(missing_ok=True)
        print(f"Back to {P.PROVIDERS[P.DEFAULT].name}.")
        return 0
    return _table()


if __name__ == "__main__":
    sys.exit(main())
