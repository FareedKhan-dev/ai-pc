"""HTTPS for the hub's connectors: JSON in and out, a timeout on every call, polite retries on 429 and 5xx (Retry-After
honoured), secrets never written to a log, and a transport that tests replace with canned answers.

  api = Api("https://slack.com/api", headers={"Authorization": "Bearer ..."}, service="slack")
  api.post("chat.postMessage", json={...}) -> dict      api.get("conversations.list", params={...})
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from ai_pc.core import vault


class HubError(Exception):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


class UrllibTransport:
    """The real network (HTTPS with certificate checks, the standard library's)."""

    def send(self, method, url, headers, data, timeout):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read()


class FakeTransport:
    """Canned answers for tests: routes {(METHOD, url-substring): (status, json or bytes[, headers]) or callable(req) -> the same};
    every request is recorded (secrets and all, in memory only) so tests can check what was sent."""

    def __init__(self, routes):
        self.routes, self.sent = routes, []

    def send(self, method, url, headers, data, timeout):
        body = None
        if data:
            try:
                body = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                body = data
        req = {"method": method, "url": url, "headers": headers, "body": body}
        self.sent.append(req)
        for (m, frag), ans in self.routes.items():
            if m == method and frag in url:
                res = ans(req) if callable(ans) else ans
                status, js = res[0], res[1]
                extra = dict(res[2]) if len(res) > 2 and res[2] else {}  # headers the answer carries (Location, Range, ETag...)
                if isinstance(js, (bytes, bytearray)):  # a file (a download), or an empty body
                    return status, {"Content-Type": "application/octet-stream", **extra}, bytes(js)
                return status, {"Content-Type": "application/json", **extra}, json.dumps(js).encode()
        return 404, {}, json.dumps({"error": f"no fake route for {method} {url}"}).encode()


TRANSPORT = UrllibTransport()


class Api:
    def __init__(self, base, headers=None, service=None, timeout=30, transport=None):
        self.base, self.headers, self.service, self.timeout = base.rstrip("/"), dict(headers or {}), service, timeout
        self.transport = transport

    def request(self, method, path, params=None, json_body=None, data=None, headers=None, raw=False, retries=3):
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        h = {"Accept": "application/json", "User-Agent": "AI-PC-hub/1.0", **self.headers, **(headers or {})}
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            h.setdefault("Content-Type", "application/json; charset=utf-8")
        tr = self.transport or TRANSPORT
        for attempt in range(retries + 1):
            try:
                status, rh, content = tr.send(method, url, h, body, self.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise HubError(f"{self.service or 'service'}: no connection ({vault.redact(e)})")
            if status == 429 or status >= 500:
                if attempt < retries:
                    wait = float((rh or {}).get("Retry-After") or (rh or {}).get("retry-after") or 2 * (attempt + 1))
                    time.sleep(min(wait, 30))
                    continue
            if raw:
                return status, rh, content
            try:
                js = json.loads(content.decode("utf-8")) if content else {}
            except (ValueError, UnicodeDecodeError):
                js = {"_text": content[:500].decode("utf-8", "replace")}
            if status >= 400:
                first = js[0] if isinstance(js, list) and js else js  # Salesforce answers errors as a list
                msg = (
                    (first.get("error_description") or first.get("message") or first.get("error") or first.get("errorMessages") or str(js)[:200])
                    if isinstance(first, dict)
                    else str(js)[:200]
                )
                if isinstance(msg, dict):
                    msg = msg.get("message") or str(msg)[:200]
                raise HubError(f"{self.service or 'service'}: {status} {vault.redact(msg)}", status, js)
            return js
        raise HubError(f"{self.service or 'service'}: gave up after {retries + 1} tries")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        if "json" in kw:
            kw["json_body"] = kw.pop("json")
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        if "json" in kw:
            kw["json_body"] = kw.pop("json")
        return self.request("PUT", path, **kw)

    def patch(self, path, **kw):
        if "json" in kw:
            kw["json_body"] = kw.pop("json")
        return self.request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


def multipart(fields, files):
    """A multipart/form-data body: fields {name: str}, files {name: (filename, bytes, mime)} -> (body, content type)."""
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fn, content, mime) in files.items():
        out.append(
            f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: {mime}\r\n\r\n'.encode() + content + b"\r\n"
        )
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"
