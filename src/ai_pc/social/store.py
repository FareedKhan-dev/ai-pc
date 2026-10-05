"""Everything the social lane remembers, in one SQLite file (state/social/social.db): posts as composed, one job per
platform with its progress checkpoints (so a publish cut short by a crash or a lost connection carries on where it
stopped, never posting twice), metric snapshots, comments seen and answered, and an audit trail of every step.

  db = Store()                     db.add_post(post) / db.post(id) / db.posts(status=...)
  db.add_job(job) / db.job(id) / db.jobs(post_id=..., status=...) / db.update_job(id, **fields) / db.checkpoint(id, key, value)
  db.due(now) -> jobs to work on     db.snapshot(job_id, metrics)     db.comment(...)     db.log(job_id, kind, detail)
"""

import datetime as dt
import json
import sqlite3
import threading
import uuid
from pathlib import Path

from ai_pc.core.config import STATE

DB = STATE / "social" / "social.db"
OPEN = ("pending", "preparing", "ready", "uploading", "processing", "retry")  # still to be worked on
SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (id TEXT PRIMARY KEY, created TEXT, due TEXT, status TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, post_id TEXT, platform TEXT, format TEXT, account TEXT, status TEXT, attempts INTEGER,
                                 next_try TEXT, updated TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS jobs_post ON jobs(post_id);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, next_try);
CREATE TABLE IF NOT EXISTS metrics (job_id TEXT, at TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS metrics_job ON metrics(job_id, at);
CREATE TABLE IF NOT EXISTS comments (platform TEXT, remote_id TEXT, job_id TEXT, created TEXT, author TEXT, text TEXT, state TEXT, body TEXT,
                                     PRIMARY KEY (platform, remote_id));
CREATE TABLE IF NOT EXISTS events (ts TEXT, job_id TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS usage (platform TEXT, day TEXT, units INTEGER, PRIMARY KEY (platform, day));
"""


def now():
    return dt.datetime.now().astimezone()


def iso(t):
    return t.astimezone().isoformat(timespec="seconds") if isinstance(t, dt.datetime) else t


def new_id(prefix):
    return f"{prefix}_{dt.datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.cx = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)  # autocommit; transactions explicit
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.execute("PRAGMA busy_timeout=5000")
        self.cx.executescript(SCHEMA)

    def close(self):
        self.cx.close()

    # ---------------------------------------------------------------- posts
    def add_post(self, post):
        post.setdefault("id", new_id("post"))
        post.setdefault("created", iso(now()))
        post.setdefault("status", "draft")
        with self._lock:
            self.cx.execute(
                "INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?)",
                (post["id"], post["created"], post.get("when"), post["status"], json.dumps(post, ensure_ascii=False)),
            )
        return post

    def post(self, pid):
        r = self.cx.execute("SELECT body FROM posts WHERE id=?", (pid,)).fetchone()
        return json.loads(r[0]) if r else None

    def posts(self, status=None, limit=50):
        q, a = "SELECT body FROM posts", []
        if status:
            q += " WHERE status IN (%s)" % ",".join("?" * len(status))
            a = list(status)
        q += " ORDER BY created DESC LIMIT ?"
        return [json.loads(r[0]) for r in self.cx.execute(q, a + [limit])]

    def update_post(self, pid, **fields):
        with self._lock:
            p = self.post(pid)
            p.update(fields)
            self.cx.execute(
                "UPDATE posts SET due=?, status=?, body=? WHERE id=?", (p.get("when"), p["status"], json.dumps(p, ensure_ascii=False), pid)
            )
            return p

    # ---------------------------------------------------------------- jobs (one per platform)
    def add_job(self, job):
        job.setdefault("id", new_id("job"))
        job.setdefault("status", "pending")
        job.setdefault("attempts", 0)
        job.setdefault("remote", {})
        job["updated"] = iso(now())
        with self._lock:
            self.cx.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job["id"],
                    job["post_id"],
                    job["platform"],
                    job.get("format"),
                    job.get("account"),
                    job["status"],
                    job["attempts"],
                    job.get("next_try"),
                    job["updated"],
                    json.dumps(job, ensure_ascii=False),
                ),
            )
        return job

    def job(self, jid):
        r = self.cx.execute("SELECT body FROM jobs WHERE id=?", (jid,)).fetchone()
        return json.loads(r[0]) if r else None

    def jobs(self, post_id=None, status=None, platform=None, limit=500):
        q, a, w = "SELECT body FROM jobs", [], []
        if post_id:
            w.append("post_id=?")
            a.append(post_id)
        if platform:
            w.append("platform=?")
            a.append(platform)
        if status:
            w.append("status IN (%s)" % ",".join("?" * len(status)))
            a += list(status)
        if w:
            q += " WHERE " + " AND ".join(w)
        q += " ORDER BY updated DESC LIMIT ?"
        return [json.loads(r[0]) for r in self.cx.execute(q, a + [limit])]

    def update_job(self, jid, **fields):
        with self._lock:
            j = self.job(jid)
            j.update(fields)
            j["updated"] = iso(now())
            self.cx.execute(
                "UPDATE jobs SET status=?, attempts=?, next_try=?, updated=?, body=? WHERE id=?",
                (j["status"], j.get("attempts", 0), j.get("next_try"), j["updated"], json.dumps(j, ensure_ascii=False), jid),
            )
            return j

    def checkpoint(self, jid, **remote):
        """Progress the platform has confirmed (a container id, an upload session, bytes sent): saved at once, so a restart resumes."""
        with self._lock:
            j = self.job(jid)
            j.setdefault("remote", {}).update(remote)
            return self.update_job(jid, remote=j["remote"])

    def due(self, at=None):
        """Jobs to work on now: open ones whose post is due (or not scheduled) and whose retry time has come."""
        at = iso(at or now())
        out = []
        for j in self.jobs(status=list(OPEN)):
            p = self.post(j["post_id"]) or {}
            # a job the platform schedules itself is uploaded at once (then it is 'scheduled', no longer open); others wait for their time
            if not j.get("native") and p.get("when") and p["when"] > at:
                continue
            if j.get("next_try") and j["next_try"] > at:
                continue
            out.append(j)
        return sorted(out, key=lambda j: (j.get("next_try") or "", j["updated"]))

    # ---------------------------------------------------------------- metrics, comments, usage, audit
    def snapshot(self, jid, metrics, at=None):
        self.cx.execute("INSERT INTO metrics VALUES (?,?,?)", (jid, iso(at or now()), json.dumps(metrics)))

    def latest_metrics(self, jid):
        r = self.cx.execute("SELECT at, body FROM metrics WHERE job_id=? ORDER BY at DESC LIMIT 1", (jid,)).fetchone()
        return (r[0], json.loads(r[1])) if r else (None, None)

    def comment(self, platform, remote_id, job_id, created, author, text, body=None):
        """A comment, stored once; -> True when it is new."""
        cur = self.cx.execute(
            "INSERT OR IGNORE INTO comments VALUES (?,?,?,?,?,?,?,?)",
            (platform, remote_id, job_id, created, author, text, "new", json.dumps(body or {})),
        )
        return cur.rowcount == 1

    def comments(self, state=None, platform=None, limit=100):
        q, a, w = "SELECT platform, remote_id, job_id, created, author, text, state FROM comments", [], []
        if state:
            w.append("state=?")
            a.append(state)
        if platform:
            w.append("platform=?")
            a.append(platform)
        if w:
            q += " WHERE " + " AND ".join(w)
        q += " ORDER BY created DESC LIMIT ?"
        keys = ("platform", "id", "job_id", "created", "author", "text", "state")
        return [dict(zip(keys, r)) for r in self.cx.execute(q, a + [limit])]

    def mark_comment(self, platform, remote_id, state):
        self.cx.execute("UPDATE comments SET state=? WHERE platform=? AND remote_id=?", (state, platform, remote_id))

    def add_usage(self, platform, units, day=None):
        day = day or dt.date.today().isoformat()
        self.cx.execute(
            "INSERT INTO usage VALUES (?,?,?) ON CONFLICT(platform, day) DO UPDATE SET units = units + excluded.units", (platform, day, int(units))
        )

    def usage(self, platform, day=None):
        r = self.cx.execute("SELECT units FROM usage WHERE platform=? AND day=?", (platform, day or dt.date.today().isoformat())).fetchone()
        return r[0] if r else 0

    def log(self, jid, kind, detail=""):
        self.cx.execute("INSERT INTO events VALUES (?,?,?,?)", (iso(now()), jid, kind, str(detail)[:2000]))

    def events(self, jid=None, limit=200):
        q, a = "SELECT ts, job_id, kind, detail FROM events", []
        if jid:
            q += " WHERE job_id=?"
            a.append(jid)
        q += " ORDER BY ts DESC, rowid DESC LIMIT ?"
        return [dict(zip(("ts", "job_id", "kind", "detail"), r)) for r in self.cx.execute(q, a + [limit])]
