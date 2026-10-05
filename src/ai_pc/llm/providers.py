"""The language-model providers AI PC can use: any service or local server that speaks the OpenAI Chat Completions API.

Each preset below gives a provider's address, the name of its key and a default model that also reads images (the
desktop agent and the checks send pictures). Pick one with `ai-pc models use <provider>` (saved in state/models.json)
or with the environment, which wins over the saved choice:

  AI_PC_PROVIDER        a preset's id (default: nebius)
  AI_PC_MODEL           the model for every role
  AI_PC_MODEL_<ROLE>    the model for one role: FAST, VISION, DEEP, VIDEO, ANNOTATE, CAPTION or DOCS
  AI_PC_BASE_URL        another address (a local server on another port, a company gateway)
  AI_PC_API_KEY         the key for the "custom" provider; the others use their own key name

Keys come from the usual places (core/keys.py): the environment, .env, then this PC's encrypted vault. A key is only
ever sent to its own provider's address.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, cast

from ai_pc.core.config import MODELS
from ai_pc.core.keys import get_key
from ai_pc.core.paths import STATE
from ai_pc.llm.client import Chat


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    key: str | None  # the key's environment name; None for a local server that needs none
    model: str  # the default model for every role ("" = it must be chosen)
    vision: bool = True  # the default model reads images
    local: bool = False
    docs: str = ""
    headers: tuple[tuple[str, str], ...] = ()  # extra request headers a provider asks for
    extra: dict[str, Any] = field(default_factory=dict)  # sent with every request: e.g. thinking turned off for speed
    skip: tuple[str, ...] = ()  # optional fields its API does not take (stream_options, temperature ...)
    max_tokens_field: str = "max_tokens"


# Checked against each provider's own documentation on 5 October 2026: the address, the key's name, and a current,
# low-cost default model that reads images (where the provider has one). Models change often: 'ai-pc models list <id>'
# shows what a provider offers today, and '--model' picks another.
NO_THINKING = {"thinking": {"type": "disabled"}}
PRESETS = [
    Provider("nebius", "Nebius Token Factory", "https://api.tokenfactory.nebius.com/v1", "NEBIUS_API_KEY", "zai-org/GLM-5.3-Flash",
             docs="https://docs.tokenfactory.nebius.com"),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-6-luna", docs="https://developers.openai.com/api/docs",
             extra={"reasoning_effort": "low"}, skip=("temperature",), max_tokens_field="max_completion_tokens"),
    Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-3.5-flash-lite",
             docs="https://ai.google.dev/gemini-api/docs/openai", extra={"reasoning_effort": "low"}),
    Provider("mistral", "Mistral AI", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "ministral-8b-latest", docs="https://docs.mistral.ai",
             skip=("stream_options",)),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "qwen/qwen3.8-27b", docs="https://console.groq.com/docs/openai"),
    Provider("together", "Together AI", "https://api.together.ai/v1", "TOGETHER_API_KEY", "Qwen/Qwen3.5-9B",
             docs="https://docs.together.ai/docs/openai-api-compatibility"),
    Provider("fireworks", "Fireworks AI", "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY", "accounts/fireworks/models/glm-5p3-flash",
             docs="https://docs.fireworks.ai/tools-sdks/openai-compatibility"),
    Provider("deepinfra", "DeepInfra", "https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY", "zai-org/GLM-5.3-Flash",
             docs="https://docs.deepinfra.com/chat/overview"),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "z-ai/glm-5.3-flash",
             docs="https://openrouter.ai/docs/quickstart", headers=(("X-OpenRouter-Title", "AI PC"),)),
    Provider("huggingface", "Hugging Face", "https://router.huggingface.co/v1", "HF_TOKEN", "Qwen/Qwen3.5-9B",
             docs="https://huggingface.co/docs/inference-providers/index"),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-flash", docs="https://api-docs.deepseek.com",
             extra=NO_THINKING),
    Provider("qwen", "Alibaba Cloud (Qwen)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY", "qwen3.7-flash",
             docs="https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions", extra={"enable_thinking": False}),
    Provider("zai", "Z.ai (GLM)", "https://api.z.ai/api/paas/v4", "ZAI_API_KEY", "glm-5.3-flash", docs="https://docs.z.ai/guides/develop/openai/python"),
    Provider("moonshot", "Moonshot AI (Kimi)", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY", "kimi-k2.6", docs="https://platform.kimi.ai/docs",
             extra=NO_THINKING, skip=("temperature",)),
    Provider("xai", "xAI (Grok)", "https://api.x.ai/v1", "XAI_API_KEY", "grok-4.3", docs="https://docs.x.ai/developers/quickstart"),
    Provider("cerebras", "Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "qwen-3.8-27b", docs="https://inference-docs.cerebras.ai/resources/openai"),
    Provider("sambanova", "SambaNova", "https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY", "gemma-4-31B-it",
             docs="https://docs.sambanova.ai/docs/en/get-started/api-keys-urls"),
    Provider("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "z-ai/glm-5.3-flash", docs="https://build.nvidia.com"),
    Provider("novita", "Novita AI", "https://api.novita.ai/openai/v1", "NOVITA_API_KEY", "google/gemma-4-26b-a4b-it",
             docs="https://docs.novita.ai/api-reference/model-apis-llm-create-chat-completion"),
    Provider("cohere", "Cohere", "https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY", "command-r7b-12-2024", vision=False,
             docs="https://docs.cohere.com/docs/compatibility-api"),
    Provider("siliconflow", "SiliconFlow", "https://api.siliconflow.com/v1", "SILICONFLOW_API_KEY", "Qwen/Qwen3-VL-8B-Instruct",
             docs="https://docs.siliconflow.com/en/userguide/quickstart"),
    Provider("ollama", "Ollama (on this PC)", "http://127.0.0.1:11434/v1", None, "qwen3-vl:8b", local=True, docs="https://docs.ollama.com/api/openai-compatibility"),
    Provider("lmstudio", "LM Studio (on this PC)", "http://127.0.0.1:1234/v1", None, "google/gemma-3-4b", local=True,
             docs="https://lmstudio.ai/docs/developer/openai-compat"),
    Provider("llamacpp", "llama.cpp server (on this PC)", "http://127.0.0.1:8080/v1", None, "local", local=True,
             docs="https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md"),
    Provider("vllm", "vLLM (on this PC)", "http://127.0.0.1:8000/v1", None, "", local=True,
             docs="https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/"),
    Provider("custom", "Any OpenAI-compatible server", "", "AI_PC_API_KEY", ""),
]  # fmt: skip
PROVIDERS = {p.id: p for p in PRESETS}
DEFAULT = "nebius"
SETTINGS = STATE / "models.json"


def settings() -> dict[str, Any]:
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d: dict[str, Any]) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(d, indent=1), encoding="utf-8")


def active() -> Provider:
    pid = (os.environ.get("AI_PC_PROVIDER") or settings().get("provider") or DEFAULT).strip().lower()
    if pid not in PROVIDERS:
        raise ValueError(f"unknown model provider '{pid}': choose one of {', '.join(PROVIDERS)}")
    return PROVIDERS[pid]


def _saved(p: Provider) -> dict[str, Any]:
    """The saved choices, if they were saved for this provider."""
    s = settings()
    return s if s.get("provider") == p.id else {}


def base_url(p: Provider | None = None) -> str:
    p = p or active()
    url = os.environ.get("AI_PC_BASE_URL") or _saved(p).get("base_url") or p.base_url
    if not url:
        raise ValueError(f"{p.name}: set its address with AI_PC_BASE_URL or 'ai-pc models use {p.id} --base-url ...'")
    return str(url).rstrip("/")


def model(role: str, p: Provider | None = None) -> str:
    p = p or active()
    s = _saved(p)
    m = (
        os.environ.get(f"AI_PC_MODEL_{role.upper()}")
        or os.environ.get("AI_PC_MODEL")
        or (s.get("models") or {}).get(role)
        or s.get("model")
        or (MODELS[role]["model"] if p.id == DEFAULT else p.model)
    )
    if not m:
        raise ValueError(f"{p.name}: choose a model with 'ai-pc models use {p.id} --model ...' or AI_PC_MODEL")
    return str(m)


def role(name: str, p: Provider | None = None) -> dict[str, Any]:
    """A role's settings for the active provider: the limits from config.MODELS, this provider's model, and the
    request extras that belong to that model (Nebius's GLM switches only go to GLM on Nebius)."""
    p = p or active()
    base: dict[str, Any] = dict(cast(dict[str, Any], MODELS[name]))
    m = model(name, p)
    if p.id == DEFAULT:  # the switches tuned for GLM on Nebius go only to that model
        extra = dict(base.get("extra") or {}) if m == base["model"] else {}
    else:
        extra = dict(p.extra)  # a provider's own switches; a model that refuses them is asked again without
    return {**base, "model": m, "extra": extra}


def api_key(p: Provider | None = None) -> str:
    p = p or active()
    if p.key is None:
        return os.environ.get("AI_PC_API_KEY", "")  # a local server may still be set up to want one
    return get_key(p.key, "my_nebius.txt" if p.id == DEFAULT else None)


def key_status(p: Provider | None = None) -> str:
    """'set', 'missing' or 'not needed' (never the key itself)."""
    p = p or active()
    if p.key is None:
        return "not needed"
    try:
        api_key(p)
        return "set"
    except RuntimeError:
        return "missing"


def chat(p: Provider | None = None, **kw: Any) -> Chat:
    p = p or active()
    return Chat(api_key(p), base_url(p), headers=dict(p.headers), skip=p.skip, max_tokens_field=p.max_tokens_field, **kw)


def price(m: str) -> tuple[float, float] | None:
    """USD per million tokens (input, output) saved with 'ai-pc models use ... --price', if any."""
    v = (settings().get("prices") or {}).get(m)
    return (float(v[0]), float(v[1])) if isinstance(v, list | tuple) and len(v) == 2 else None


def describe(p: Provider | None = None) -> dict[str, Any]:
    """What `ai-pc models show` and the doctor print: no key, only whether it is there."""
    p = p or active()
    out: dict[str, Any] = {"provider": p.id, "name": p.name, "key": p.key, "key_status": key_status(p), "local": p.local}
    try:
        out["base_url"] = base_url(p)
        out["models"] = {r: model(r, p) for r in MODELS}
    except ValueError as e:
        out["problem"] = str(e)
    return out
