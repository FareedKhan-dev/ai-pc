"""The queue worker. Every due job is prepared (text and media fitted to its platform), published, read back and recorded.
A failure waits and tries again on a growing schedule (1, 5, 15, 60, 240 minutes), a rate limit waits as long as the
platform asks, an expired sign-in waits for the person, and a post the platform refuses is reported with the reason.
A post a platform can schedule by itself is uploaded at once and the platform publishes it on time, even with this PC off.

  run(store, platforms, prepare, now=None) -> [{"job", "platform", "status", "detail"}]
  refresh(store, platforms)   natively scheduled posts whose time has come: confirmed published, with their links
  install_task() / remove_task() / task_installed()   Windows Task Scheduler runs 'ai-pc social run' every 5 minutes,
                                                      hidden (pythonw), only after the person's yes
"""
import datetime as dt
import os
import subprocess
import time
import traceback
from pathlib import Path

from ai_pc.core.config import ROOT, STATE
from ai_pc.social.base import SocialError
from ai_pc.social.store import iso, now

BACKOFF = [60, 300, 900, 3600, 4 * 3600]
MAX_ATTEMPTS = 6
LOCK = STATE / "social" / "run.lock"
TASK = "AI PC social posts"
NO_WINDOW = 0x08000000


def _later(seconds, at=None):
    return iso((at or now()) + dt.timedelta(seconds=int(seconds)))


def _post_status(store, pid):
    js = store.jobs(post_id=pid)
    st = {j["status"] for j in js}
    if not js:
        return "draft"
    if st <= {"published"}:
        s = "published"
    elif st <= {"published", "scheduled"}:
        s = "scheduled"
    elif st & {"pending", "preparing", "ready", "uploading", "processing", "retry"}:
        s = "publishing" if st & {"published", "uploading", "processing"} else "queued"
    elif st <= {"cancelled", "deleted"}:
        s = "cancelled"
    elif "failed" in st or "needs_signin" in st:
        s = "partial" if st & {"published", "scheduled"} else "failed"
    else:
        s = "partial"
    store.update_post(pid, status=s)
    return s


def work(store, job, platform, prepare, budget=120, at=None):
    """One job, as far as it can go now -> its new status."""
    at = at or now()
    post = store.post(job["post_id"])
    polling = job["status"] == "processing"
    try:
        if not job.get("prepared"):
            store.update_job(job["id"], status="preparing")
            prep = prepare(post, job)
            if prep.get("problems"):
                raise SocialError("invalid", "; ".join(prep["problems"]))
            job = store.update_job(job["id"], prepared=prep, status="ready")
            store.log(job["id"], "prepared", "; ".join(prep.get("notes") or []) or "ready as it was")
        if not polling:
            job = store.update_job(job["id"], status="uploading", attempts=job.get("attempts", 0) + 1)
            store.log(job["id"], "publish", f"attempt {job['attempts']}")
        r = platform.publish(job, post, job["prepared"], budget=budget)
        job = store.job(job["id"])  # checkpoints written by the connector
        if r["status"] == "processing":
            store.update_job(job["id"], status="processing", next_try=_later(r.get("wait", 30), at))
            store.log(job["id"], "processing", r.get("detail", ""))
        elif r["status"] == "scheduled":
            store.update_job(job["id"], status="scheduled", next_try=None, error=None, remote=dict(job.get("remote", {}), id=r.get("id"),
                                                                                                       scheduled=True, publish_at=r.get("publish_at")))
            store.log(job["id"], "scheduled", f"{platform.label} publishes it at {r.get('publish_at')}")
        else:
            store.update_job(job["id"], status="published", next_try=None, error=None, published_at=iso(now()), notes=r.get("notes"),
                             remote=dict(job.get("remote", {}), id=r.get("id"), permalink=r.get("permalink"), verified=r.get("verified")))
            store.log(job["id"], "published", r.get("permalink") or r.get("id") or "")
    except SocialError as e:
        job = store.job(job["id"])
        n = job.get("attempts", 0)
        if e.kind in ("retry", "limit") and n < MAX_ATTEMPTS:
            wait = e.retry_after if e.kind == "limit" and e.retry_after else BACKOFF[min(max(n - 1, 0), len(BACKOFF) - 1)]
            store.update_job(job["id"], status="retry", next_try=_later(wait, at), error=str(e))
            store.log(job["id"], e.kind, f"{e} (again in {wait // 60 or 1} min)")
        elif e.kind == "auth":
            store.update_job(job["id"], status="needs_signin", error=str(e))
            store.log(job["id"], "auth", str(e))
        else:
            store.update_job(job["id"], status="failed", error=str(e))
            store.log(job["id"], "failed", str(e))
    except Exception as e:  # noqa: BLE001  (a bug or something unforeseen: kept, retried, and the trace logged)
        job = store.job(job["id"])
        n = job.get("attempts", 0)
        if n < MAX_ATTEMPTS:
            store.update_job(job["id"], status="retry", next_try=_later(BACKOFF[min(max(n - 1, 0), len(BACKOFF) - 1)], at),
                             error=f"{type(e).__name__}: {e}")
        else:
            store.update_job(job["id"], status="failed", error=f"{type(e).__name__}: {e}")
        store.log(job["id"], "error", traceback.format_exc()[-1500:])
    _post_status(store, job["post_id"])
    return store.job(job["id"])["status"]


def run(store, platforms, prepare, at=None, budget=120, only=None):
    """Every due job once. platforms: {name: connector}. only: a post id to limit the run to."""
    out = []
    for job in store.due(at):
        if only and job["post_id"] != only:
            continue
        plat = platforms.get(job["platform"])
        if plat is None:
            store.update_job(job["id"], status="needs_signin", error=f"{job['platform']} is not connected")
            out.append({"job": job["id"], "platform": job["platform"], "status": "needs_signin", "detail": "not connected"})
            continue
        st = work(store, job, plat, prepare, budget, at)
        j = store.job(job["id"])
        out.append({"job": j["id"], "platform": j["platform"], "status": st, "detail": j.get("error") or (j.get("remote") or {}).get("permalink")})
    return out


def refresh(store, platforms, at=None):
    """Natively scheduled posts whose time has passed: asked whether they went out, and their links saved."""
    at_s = iso(at or now())
    out = []
    for j in store.jobs(status=["scheduled"]):
        pa = (j.get("remote") or {}).get("publish_at")
        plat = platforms.get(j["platform"])
        if not plat or (pa and pa > at_s):
            continue
        try:
            r = plat.status(j)
        except SocialError as e:
            store.log(j["id"], "refresh", str(e))
            continue
        if r.get("status") == "published":
            store.update_job(j["id"], status="published", published_at=r.get("published_at") or pa,
                             remote=dict(j.get("remote", {}), permalink=r.get("permalink"), verified=True))
            store.log(j["id"], "published", r.get("permalink") or "")
            _post_status(store, j["post_id"])
        out.append({"job": j["id"], "platform": j["platform"], "status": r.get("status")})
    return out


# ---------------------------------------------------------------- one runner at a time
class Busy(Exception):
    pass


class Lock:
    """Only one runner works the queue at a time (a scheduled run and a chat must not both publish a job)."""

    def __init__(self, path=LOCK, stale=1800):
        self.path, self.stale = Path(path), stale

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.time() - self.path.stat().st_mtime > self.stale:  # a runner that died long ago
                self.path.unlink(missing_ok=True)
                return self.__enter__()
            raise Busy("another run is working on the queue") from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *a):
        self.path.unlink(missing_ok=True)


# ---------------------------------------------------------------- Windows Task Scheduler
def _pythonw():
    p = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return str(p) if p.exists() else str(ROOT / ".venv" / "Scripts" / "python.exe")


def task_installed():
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def install_task(minutes=5):
    """Every few minutes, hidden, while you are signed in to Windows: 'ai-pc social run' publishes what is due."""
    cmd = f'"{_pythonw()}" -m ai_pc social run --quiet'
    r = subprocess.run(["schtasks", "/Create", "/TN", TASK, "/TR", cmd, "/SC", "MINUTE", "/MO", str(int(minutes)), "/F"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(f"Task Scheduler refused: {(r.stderr or r.stdout).strip()[:300]}")
    return task_installed()


def remove_task():
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.returncode == 0
