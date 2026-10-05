"""Docker by its files: a project folder looked at (Python with Flask, Django or FastAPI; Node; a plain website) and a
Dockerfile, .dockerignore and compose.yaml written for it (a pinned base image, dependencies first for fast rebuilds,
a non-root user, the right port), checked against the project, and built with Docker when Docker is installed.

  'dockerfile for D:\\Projects\\shop-site'   'docker build D:\\Projects\\shop-site'
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

NAME, LABEL = "docker", "Docker: Dockerfile, .dockerignore and compose.yaml for a project; build when Docker is installed"
EXAMPLES = ["dockerfile for D:\\Projects\\shop-site", "docker build D:\\Projects\\shop-site"]
IGNORE = ".git\n.venv\nvenv\n__pycache__\n*.pyc\nnode_modules\n.vscode\n.idea\n*.log\n.env\nDockerfile\ncompose.yaml\n"


def detect(folder):
    f = Path(folder)
    reqs = (f / "requirements.txt").read_text(encoding="utf-8", errors="replace").lower() if (f / "requirements.txt").exists() else ""
    if reqs or (f / "pyproject.toml").exists():
        entry = next((n for n in ("app.py", "main.py", "manage.py", "server.py", "run.py") if (f / n).exists()), None)
        if "django" in reqs or (f / "manage.py").exists():
            return {"kind": "python", "framework": "django", "port": 8000, "cmd": ["python", "manage.py", "runserver", "0.0.0.0:8000"]}
        if "fastapi" in reqs:
            mod = Path(entry or "main.py").stem
            return {"kind": "python", "framework": "fastapi", "port": 8000, "cmd": ["uvicorn", f"{mod}:app", "--host", "0.0.0.0", "--port", "8000"]}
        if "flask" in reqs:
            return {"kind": "python", "framework": "flask", "port": 5000, "cmd": ["flask", "--app", Path(entry or "app.py").stem, "run", "--host", "0.0.0.0", "--port", "5000"]}
        return {"kind": "python", "framework": None, "port": None, "cmd": ["python", entry or "main.py"]}
    if (f / "package.json").exists():
        pkg = json.loads((f / "package.json").read_text(encoding="utf-8"))
        scripts = pkg.get("scripts") or {}
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        if "build" in scripts and any(k in deps for k in ("vite", "react-scripts", "@angular/cli", "vue")) and "start" not in scripts:
            return {"kind": "node-static", "framework": "vite", "port": 80, "cmd": None}
        return {"kind": "node", "framework": "express" if "express" in deps else None, "port": 3000, "cmd": ["npm", "start"]}
    if (f / "index.html").exists():
        return {"kind": "static", "framework": None, "port": 80, "cmd": None}
    raise ValueError("no requirements.txt, pyproject.toml, package.json or index.html: what kind of project is it?")


def dockerfile(info):
    k = info["kind"]
    if k == "python":
        lines = ["FROM python:3.12-slim", "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1", "WORKDIR /app",
                 "COPY requirements.txt ./" if info.get("has_reqs", True) else "", "RUN pip install --no-cache-dir -r requirements.txt" if info.get("has_reqs", True) else "",
                 "COPY . .", "RUN useradd --create-home app && chown -R app /app", "USER app"]
        if info["port"]:
            lines.append(f"EXPOSE {info['port']}")
        lines.append("CMD " + json.dumps(info["cmd"]))
    elif k == "node":
        lines = ["FROM node:22-alpine", "WORKDIR /app", "COPY package*.json ./", "RUN npm ci --omit=dev", "COPY . .", "USER node", f"EXPOSE {info['port']}",
                 "CMD " + json.dumps(info["cmd"])]
    elif k == "node-static":
        lines = ["FROM node:22-alpine AS build", "WORKDIR /app", "COPY package*.json ./", "RUN npm ci", "COPY . .", "RUN npm run build", "",
                 "FROM nginx:1.27-alpine", "COPY --from=build /app/dist /usr/share/nginx/html", "EXPOSE 80"]
    else:
        lines = ["FROM nginx:1.27-alpine", "COPY . /usr/share/nginx/html", "EXPOSE 80"]
    return "\n".join(x for x in lines if x is not None) + "\n"


def compose(name, info):
    svc = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "app"
    ports = f"    ports:\n      - \"{8080 if info['port'] == 80 else info['port']}:{info['port']}\"\n" if info["port"] else ""
    return f"services:\n  {svc}:\n    build: .\n{ports}    restart: unless-stopped\n"


def check(folder, info):
    f = Path(folder)
    d = (f / "Dockerfile").read_text(encoding="utf-8")
    first = [ln for ln in d.splitlines() if ln.strip()][0]
    out = [("the Dockerfile starts FROM a pinned image (no 'latest')", first.startswith("FROM ") and ":" in first and ":latest" not in first)]
    if info["kind"] in ("python", "node"):
        out.append(("it runs as a non-root user", re.search(r"^USER (?!root)", d, re.M) is not None))
    for copied in re.findall(r"^COPY (?!--from)(\S+) ", d, re.M):
        if copied not in (".", "package*.json"):
            out.append((f"{copied} exists in the project", (f / copied).exists()))
    if info["port"]:
        c = (f / "compose.yaml").read_text(encoding="utf-8")
        out.append(("compose publishes the port the Dockerfile exposes", f":{info['port']}\"" in c and f"EXPOSE {info['port']}" in d))
    return out


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bdocker(?:file)?\b|\bcontaineri[sz]e\b|\bcompose\b", c):
        return None
    m = re.search(r"([a-z]:\\[^\"<>|?*\n]+?)\s*$", text, re.I)
    if not m:
        return None
    return {"op": "build" if re.search(r"\bdocker\s+build\b|\bbuild\b.*\bimage\b", c) else "files", "folder": m.group(1).strip(" '\"")}


def run(op, ctx):
    f = Path(op["folder"])
    if not f.is_dir():
        return f"{f} is not a folder."
    info = detect(f)
    info["has_reqs"] = (f / "requirements.txt").exists()
    written = []
    for name, text in (("Dockerfile", dockerfile(info)), (".dockerignore", IGNORE), ("compose.yaml", compose(f.name, info))):
        p = f / name
        if p.exists() and op["op"] == "files":
            p = f / f"{name}.aipc"  # never overwrite the project's own file
        p.write_text(text, encoding="utf-8", newline="\n")
        written.append(p.name)
    checks = check(f, info) if "Dockerfile" in written else []
    bad = [w for w, ok in checks if not ok]
    reply = (f"{f.name} is a {info['framework'] or info['kind']} project: wrote {', '.join(written)}" + (f" (port {info['port']})" if info["port"] else "") + ". " +
             ("Checked: " + "; ".join(w for w, _ in checks) + "." if checks and not bad else "NOT right: " + "; ".join(bad) + "." if bad else ""))
    if op["op"] == "build":
        docker = shutil.which("docker")
        if not docker:
            return reply + " Docker is not installed here (say 'install docker desktop')."
        r = subprocess.run([docker, "build", "-t", f"{re.sub(r'[^a-z0-9-]+', '-', f.name.lower())}:latest", str(f)], capture_output=True, text=True, timeout=1800,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        reply += " Image built." if r.returncode == 0 else f" The build failed: {(r.stderr or r.stdout).strip()[-300:]}"
    return reply
