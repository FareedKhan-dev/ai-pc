"""Postman by its files: an API collection (Postman's v2.1 format, with a {{baseUrl}} variable, an environment file and
a test on every request) that Postman imports (File > Import), and the collection run here like Postman's Newman: each
request sent, its status, time and size recorded and its test judged, with a report. GET requests run at once; a run
that would POST, PUT, PATCH or DELETE (it changes data on the server) is shown first and waits for a yes.

  'postman collection for https://jsonplaceholder.typicode.com: GET /posts/1, GET /users, POST /posts {"title": "Hello"}'
  'run the postman collection'
"""
import json
import re
import time
import uuid
from pathlib import Path

from ..hub.http import Api, HubError

NAME, LABEL = "postman", "Postman: API collections and environments, run like Newman with a report"
EXAMPLES = ['postman collection for https://jsonplaceholder.typicode.com: GET /posts/1, GET /users', "run the postman collection"]
OUTWARD = {"run_write"}
TRANSPORT = None  # tests put a fake here


def collection(name, base, requests):
    items = []
    for method, path, body in requests:
        req = {"method": method, "header": [{"key": "Accept", "value": "application/json"}],
               "url": {"raw": "{{baseUrl}}" + path, "host": ["{{baseUrl}}"], "path": [p for p in path.split("?")[0].split("/") if p]}}
        if body is not None:
            req["header"].append({"key": "Content-Type", "value": "application/json"})
            req["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2), "options": {"raw": {"language": "json"}}}
        items.append({"name": f"{method} {path}", "request": req, "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": [
            "pm.test('status is 2xx', function () { pm.response.to.be.success; });"]}}]})
    return {"info": {"_postman_id": str(uuid.uuid4()), "name": name, "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": items, "variable": [{"key": "baseUrl", "value": base}]}


def environment(name, base):
    return {"id": str(uuid.uuid4()), "name": f"{name} environment", "values": [{"key": "baseUrl", "value": base, "type": "default", "enabled": True}],
            "_postman_variable_scope": "environment"}


def run_collection(col):
    base = next(v["value"] for v in col["variable"] if v["key"] == "baseUrl")
    api = Api(base, service="postman run", transport=TRANSPORT, timeout=30)
    results = []
    for it in col["item"]:
        r = it["request"]
        path = r["url"]["raw"].replace("{{baseUrl}}", "")
        body = json.loads(r["body"]["raw"]) if r.get("body") else None
        t0 = time.perf_counter()
        try:
            status, headers, content = api.request(r["method"], base.rstrip("/") + path, json_body=body, raw=True, retries=0)
        except HubError as e:
            status, content = 0, str(e).encode()
        results.append({"name": it["name"], "status": status, "ms": round((time.perf_counter() - t0) * 1000), "bytes": len(content or b""),
                        "passed": 200 <= status < 300})
    return results


def parse(text, ctx):
    m = re.match(r"^\s*(?:make\s+(?:a\s+)?)?postman\s+collection\s+for\s+(https?://\S+?)\s*:\s*(.+)$", text, re.I | re.S)
    if m:
        reqs = []
        for part in re.findall(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S*)(?:\s+(\{.*?\}))?(?=\s*,\s*(?:GET|POST|PUT|PATCH|DELETE)\b|\s*$)", m.group(2), re.I | re.S):
            reqs.append((part[0].upper(), part[1], json.loads(part[2]) if part[2] else None))
        return {"op": "make", "base": m.group(1).rstrip("/"), "requests": reqs} if reqs else None
    if re.search(r"\brun\b.*\bpostman\b|\bpostman\b.*\brun\b|\bnewman\b", text, re.I):
        last = (ctx.get("memo") or {}).get("postman")
        if not last:
            return None
        col = json.loads(Path(last).read_text(encoding="utf-8"))
        writes = [i["name"] for i in col["item"] if i["request"]["method"] != "GET"]
        return {"op": "run_write" if writes else "run", "file": last, "writes": writes}
    return None


def preview(op, ctx):
    return f"Ready to run the collection: it sends {', '.join(op['writes'])}, which change data on the server."


def run(op, ctx):
    out = Path(ctx["out"]) / "postman"
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "make":
        host = re.sub(r"^https?://", "", op["base"]).split("/")[0]
        col = collection(host, op["base"], op["requests"])
        dest = out / f"{host}.postman_collection.json"
        dest.write_text(json.dumps(col, indent=2), encoding="utf-8")
        (out / f"{host}.postman_environment.json").write_text(json.dumps(environment(host, op["base"]), indent=2), encoding="utf-8")
        ctx.setdefault("memo", {})["postman"] = str(dest)
        back = json.loads(dest.read_text(encoding="utf-8"))
        ok = back["info"]["schema"].endswith("v2.1.0/collection.json") and len(back["item"]) == len(op["requests"])
        return (f"Postman collection with {len(op['requests'])} requests: {dest} and its environment (Postman: File > Import both) "
                f"({'checked: v2.1 format, every request in' if ok else 'NOT right'}). Say 'run the postman collection' to try them.")
    if op["op"] == "run_write" and not op.get("confirmed"):
        return preview(op, ctx)
    col = json.loads(Path(op["file"]).read_text(encoding="utf-8"))
    res = run_collection(col)
    (out / "run_report.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    passed = sum(r["passed"] for r in res)
    return f"Ran {len(res)} requests: {passed} passed, {len(res) - passed} failed.\n" + \
        "\n".join(f"- {r['name']}: {r['status']} in {r['ms']} ms, {r['bytes']} bytes, {'pass' if r['passed'] else 'FAIL'}" for r in res) + \
        f"\nReport: {out / 'run_report.json'}"
