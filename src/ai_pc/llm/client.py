"""Tiny OpenAI-compatible chat client with streaming (stdlib only). Measures time-to-first-token and total time."""
import http.client
import json
import random
import socket
import ssl
import threading
import time
import urllib.parse
from dataclasses import dataclass, field

NEBIUS_BASE = "https://api.tokenfactory.nebius.com/v1"


class LLMError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


@dataclass
class LLMResult:
    text: str = ""
    reasoning: str = ""
    ttft_ms: float = 0.0           # time to first visible OR reasoning token
    first_text_ms: float = 0.0     # time to first visible (answer) token
    total_ms: float = 0.0
    usage: dict = field(default_factory=dict)
    finish: str = ""
    model: str = ""
    extras_used: dict = field(default_factory=dict)


class _Status(Exception):
    """A non-200 HTTP answer."""

    def __init__(self, code, headers, body):
        super().__init__(f"HTTP {code}")
        self.code, self.headers, self.body = code, headers, body


class _HTTPSConn(http.client.HTTPSConnection):
    """Keep-alive HTTPS connection that remembers the server's last good address: if DNS fails later (flaky router DNS),
    it connects to that address directly. TLS still verifies the certificate against the real hostname."""

    def __init__(self, host, port, timeout, context, ip_cache):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip_cache = ip_cache

    def connect(self):
        try:
            addr = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)[0][4][0]
            self._ip_cache["ip"] = addr
        except socket.gaierror:
            addr = self._ip_cache.get("ip")
            if not addr:
                raise
        sock = socket.create_connection((addr, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class Chat:
    RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}

    def __init__(self, api_key, base_url=NEBIUS_BASE, timeout=90, deadline=240):
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout    # idle seconds on the socket
        self.deadline = deadline  # whole answer, per attempt
        u = urllib.parse.urlparse(self.base_url)
        self._scheme, self._host = u.scheme, u.hostname
        self._port = u.port or (443 if u.scheme == "https" else 80)
        self._prefix = u.path.rstrip("/")
        self._ctx = ssl.create_default_context()
        self._ip_cache = {}
        self._local = threading.local()  # one keep-alive connection per thread

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            if self._scheme == "https":
                c = _HTTPSConn(self._host, self._port, self.timeout, self._ctx, self._ip_cache)
            else:
                c = http.client.HTTPConnection(self._host, self._port, timeout=self.timeout)
            self._local.conn = c
        return c

    def _drop(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self._local.conn = None

    def complete(self, model, messages, *, max_tokens=800, temperature=0.0, json_mode=False, extra=None, retries=5):
        """One chat completion over a reused connection. Transient failures (DNS/connection errors, dropped keep-alive
        connections, timeouts, 429 and 5xx) are retried with exponential backoff and jitter; other 4xx are raised."""
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                "stream": True, "stream_options": {"include_usage": True}}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if extra:
            body.update(extra)
        data = json.dumps(body).encode()
        for attempt in range(retries + 1):
            delay = (0.05 if attempt == 0 else min(8.0, 0.5 * 2 ** attempt)) + random.uniform(0, 0.25)
            try:
                return self._once(model, data, extra)
            except _Status as e:
                if e.code in self.RETRY_STATUS and attempt < retries:
                    ra = e.headers.get("retry-after") if e.headers else None
                    time.sleep(float(ra) if ra and ra.replace(".", "", 1).isdigit() else delay)
                    continue
                raise LLMError(f"HTTP {e.code}: {e.body[:300].decode('utf-8', 'replace')}", e.code) from None
            except (OSError, http.client.HTTPException) as e:  # DNS, reset, timeout, TLS, stale keep-alive
                self._drop()
                if attempt < retries:
                    time.sleep(delay)
                    continue
                raise LLMError(f"{type(e).__name__}: {e}") from None
        raise LLMError("unreachable")

    def _once(self, model, data, extra):
        conn = self._conn()
        hdrs = {"Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                "Accept": "text/event-stream", "User-Agent": "ai-pc/0.1"}
        res = LLMResult(model=model, extras_used=dict(extra or {}))
        t0 = time.perf_counter()
        conn.request("POST", self._prefix + "/chat/completions", body=data, headers=hdrs)
        resp = conn.getresponse()
        if resp.status != 200:
            raise _Status(resp.status, resp.headers, resp.read())
        for raw in resp:
            if time.perf_counter() - t0 > self.deadline:  # a stream that trickles forever never trips the idle timeout
                self._drop()
                raise LLMError(f"no complete answer after {self.deadline:.0f} s (stream stalled)")  # not retried
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if ev.get("usage"):
                res.usage = ev["usage"]
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                now = (time.perf_counter() - t0) * 1000
                rc = d.get("reasoning_content") or d.get("reasoning")
                if rc:
                    res.reasoning += rc
                    res.ttft_ms = res.ttft_ms or now
                c = d.get("content")
                if c:
                    res.text += c
                    res.ttft_ms = res.ttft_ms or now
                    res.first_text_ms = res.first_text_ms or now
                if ch.get("finish_reason"):
                    res.finish = ch["finish_reason"]
        resp.read()  # drain, so the connection can be reused
        res.total_ms = (time.perf_counter() - t0) * 1000
        return res

    def complete_with_fallback(self, model, messages, extras_chain, **kw):
        """Try provider-specific 'no/low thinking' switches in order until one is accepted (HTTP 200)."""
        last = None
        for extra in extras_chain:
            try:
                return self.complete(model, messages, extra=extra, **kw)
            except LLMError as e:
                last = e
                if e.status not in (400, 422):
                    raise
        raise last
