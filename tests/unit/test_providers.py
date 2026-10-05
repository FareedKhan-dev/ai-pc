"""Model providers: the presets, which provider and model each role uses, keys, and the OpenAI-compatible requests
(against a small server on 127.0.0.1 that stands in for a provider)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_pc.cli import models as cli
from ai_pc.core.config import MODELS
from ai_pc.llm import providers as P
from ai_pc.llm.client import Chat, LLMError


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    """No saved choice, no provider variables from this PC, and no keys from its vault or .env."""
    monkeypatch.setattr(P, "SETTINGS", tmp_path / "models.json")
    for v in ("AI_PC_PROVIDER", "AI_PC_MODEL", "AI_PC_BASE_URL", "AI_PC_API_KEY", *(f"AI_PC_MODEL_{r.upper()}" for r in MODELS)):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr("ai_pc.core.keys.from_vault", lambda name: "")
    monkeypatch.setattr("ai_pc.core.keys.dotenv", lambda path=None: {})


def test_every_preset_is_complete():
    assert len(P.PRESETS) == len(P.PROVIDERS)  # ids are unique
    for p in P.PRESETS:
        if p.id == "custom":
            continue
        assert p.base_url.startswith("http://127.0.0.1:" if p.local else "https://"), p.id
        assert not p.base_url.endswith("/") and "/chat/completions" not in p.base_url, p.id
        assert (p.key is None) == p.local, p.id
        assert p.docs.startswith("https://"), p.id


def test_nebius_is_the_default_and_keeps_its_tuned_settings():
    assert P.active().id == "nebius"
    fast = P.role("fast")
    assert fast["model"] == MODELS["fast"]["model"] and fast["extra"] == MODELS["fast"]["extra"]
    assert fast["max_tokens"] == MODELS["fast"]["max_tokens"]


def test_a_provider_chosen_in_the_environment_gets_its_own_model_and_no_nebius_switches(monkeypatch):
    monkeypatch.setenv("AI_PC_PROVIDER", "groq")
    r = P.role("vision")
    assert r["model"] == P.PROVIDERS["groq"].model and r["extra"] == {}
    assert r["deadline_s"] == MODELS["vision"]["deadline_s"]  # the limits stay


def test_models_can_be_set_for_all_roles_or_one(monkeypatch):
    monkeypatch.setenv("AI_PC_PROVIDER", "openrouter")
    monkeypatch.setenv("AI_PC_MODEL", "some/model")
    monkeypatch.setenv("AI_PC_MODEL_DEEP", "big/model")
    assert P.model("fast") == "some/model" and P.model("deep") == "big/model"


def test_a_saved_choice_is_used_and_the_environment_wins(monkeypatch):
    assert cli.main(["use", "ollama", "--model", "gemma3", "--base-url", "http://127.0.0.1:11500/v1"]) == 0
    assert P.active().id == "ollama" and P.model("docs") == "gemma3" and P.base_url() == "http://127.0.0.1:11500/v1"
    monkeypatch.setenv("AI_PC_PROVIDER", "mistral")
    assert P.active().id == "mistral" and P.model("docs") == P.PROVIDERS["mistral"].model  # the saved model was for Ollama
    monkeypatch.delenv("AI_PC_PROVIDER")
    assert cli.main(["reset"]) == 0 and P.active().id == "nebius"


def test_unknown_providers_and_missing_choices_are_explained(monkeypatch, capsys):
    monkeypatch.setenv("AI_PC_PROVIDER", "nope")
    with pytest.raises(ValueError, match="choose one of"):
        P.active()
    monkeypatch.setenv("AI_PC_PROVIDER", "custom")
    with pytest.raises(ValueError, match="AI_PC_BASE_URL"):
        P.base_url()
    monkeypatch.delenv("AI_PC_PROVIDER")
    assert cli.main(["use", "vllm"]) == 2 and "--model" in capsys.readouterr().err
    assert cli.main(["use", "nope"]) == 2


def test_key_status_never_shows_the_key(monkeypatch, capsys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret-123")
    assert P.key_status(P.PROVIDERS["groq"]) == "set"
    assert P.key_status(P.PROVIDERS["xai"]) == "missing"
    assert P.key_status(P.PROVIDERS["ollama"]) == "not needed"
    monkeypatch.setenv("AI_PC_PROVIDER", "groq")
    assert cli.main([]) == 0 and cli.main(["show"]) == 0
    out = capsys.readouterr().out
    assert "gsk-secret-123" not in out and "GROQ_API_KEY (set)" in out


def test_a_saved_price_counts_in_the_cost(monkeypatch):
    assert cli.main(["use", "openrouter", "--model", "a/b", "--price", "0.2,0.8"]) == 0
    assert P.price("a/b") == (0.2, 0.8) and P.price("c/d") is None


def test_a_providers_own_switches_go_with_its_requests(monkeypatch):
    monkeypatch.setenv("AI_PC_PROVIDER", "deepseek")
    assert P.role("fast")["extra"] == {"thinking": {"type": "disabled"}}
    monkeypatch.setenv("AI_PC_PROVIDER", "openai")
    openai = P.PROVIDERS["openai"]
    assert P.role("fast")["extra"] == {"reasoning_effort": "low"}
    assert "temperature" in openai.skip and openai.max_tokens_field == "max_completion_tokens"


# ---------------------------------------------------------------- the requests themselves
class Fake(BaseHTTPRequestHandler):
    seen: list = []
    refuse = set()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "title": self.headers.get("X-Title"), "body": body})
        bad = [k for k in Fake.refuse if k in body]
        if bad:
            said = {"max_tokens": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}
            msg = json.dumps({"error": {"message": said.get(bad[0], f"Unrecognized request argument supplied: {bad[0]}")}}).encode()
            self.send_response(400)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        chunks = [{"choices": [{"delta": {"content": "O"}}]}, {"choices": [{"delta": {"content": "K"}, "finish_reason": "stop"}]}]
        if "stream_options" in body:
            chunks.append({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}})
        data = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        raw = data.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    Fake.seen, Fake.refuse = [], set()
    s = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}/v1"
    s.shutdown()


def test_a_request_goes_to_the_providers_address_with_its_key(server):
    r = Chat("test-key", server, headers={"X-Title": "AI PC"}).complete("m1", [{"role": "user", "content": "hi"}], max_tokens=5)
    assert r.text == "OK" and r.usage == {"prompt_tokens": 7, "completion_tokens": 2}
    s = Fake.seen[0]
    assert s["path"] == "/v1/chat/completions" and s["auth"] == "Bearer test-key" and s["title"] == "AI PC"
    assert s["body"]["model"] == "m1" and s["body"]["stream"] is True


def test_a_local_server_gets_no_key(server, monkeypatch):
    monkeypatch.setenv("AI_PC_PROVIDER", "llamacpp")
    monkeypatch.setenv("AI_PC_BASE_URL", server)
    r = P.chat().complete(P.model("fast"), [{"role": "user", "content": "hi"}], max_tokens=5)
    assert r.text == "OK" and Fake.seen[0]["auth"] is None


def test_fields_a_provider_refuses_are_dropped_once_and_for_all(server):
    Fake.refuse = {"stream_options", "response_format"}
    c = Chat("k", server)
    r = c.complete("m", [{"role": "user", "content": "hi"}], json_mode=True, max_tokens=5)
    assert r.text == "OK"
    assert "stream_options" not in Fake.seen[-1]["body"] and "response_format" not in Fake.seen[-1]["body"]
    n = len(Fake.seen)
    c.complete("m", [{"role": "user", "content": "again"}], json_mode=True, max_tokens=5)
    assert len(Fake.seen) == n + 1  # straight through: no refused request first


def test_newer_openai_models_get_max_completion_tokens_and_no_temperature(server):
    Chat("k", server, skip=("temperature",), max_tokens_field="max_completion_tokens").complete(
        "m", [{"role": "user", "content": "hi"}], max_tokens=7
    )
    b = Fake.seen[-1]["body"]
    assert b["max_completion_tokens"] == 7 and "max_tokens" not in b and "temperature" not in b


def test_an_endpoint_that_asks_for_max_completion_tokens_or_refuses_a_temperature_gets_its_way(server):
    Fake.refuse = {"max_tokens", "temperature"}
    c = Chat("k", server)
    assert c.complete("m", [{"role": "user", "content": "hi"}], max_tokens=9).text == "OK"
    b = Fake.seen[-1]["body"]
    assert b["max_completion_tokens"] == 9 and "temperature" not in b


def test_other_errors_still_fail_with_the_providers_message(server):
    Fake.refuse = {"model"}
    with pytest.raises(LLMError, match="HTTP 400"):
        Chat("k", server).complete("m", [{"role": "user", "content": "hi"}], max_tokens=5, retries=1)
