"""What every platform connector offers, and the errors they raise.

A publish is a small state machine: each call carries a job as far as it can within a time budget, saves every step the
platform confirms (store.checkpoint: a container id, an upload session, the bytes sent), and returns one of
  {"status": "published", "id", "permalink"}   done and read back
  {"status": "scheduled", "id", "publish_at"}   the platform itself will publish it at that time
  {"status": "processing", "wait": seconds}     the platform is still working: call again later
so a crash, a lost connection or a closed laptop never loses work and never posts twice.

Errors say what to do next: SocialError(kind=...) with kind
  "retry"   a passing problem (network, 5xx): try again after a short wait
  "limit"   a rate or quota limit: try again after retry_after seconds
  "auth"    the sign-in has expired or was taken back: connect the platform again
  "invalid" the post itself is not acceptable (too long, wrong media): fix the post
  "policy"  the platform will not allow it for this account (an unaudited app, a missing permission)
"""
from ai_pc.hub.http import Api, HubError


class SocialError(Exception):
    def __init__(self, kind, message, retry_after=None, code=None, detail=None):
        super().__init__(message)
        self.kind, self.retry_after, self.code, self.detail = kind, retry_after, code, detail


class Platform:
    name = ""
    label = ""
    formats = ()                 # the kinds of post it takes: "post", "photo", "carousel", "video", "reel", "story", "short", "text"
    native_schedule = False      # it can publish at a set time by itself (the PC may be off)
    can_delete = True
    vault_key = None             # which keys in the vault it uses (defaults to name)

    def __init__(self, creds=None, transport=None, store=None, pause=None):
        from ai_pc.core import vault
        self.creds = creds if creds is not None else (vault.get(self.vault_key or self.name) or {})
        self.transport, self.store = transport, store
        import time
        self.pause = pause or time.sleep

    # ---------------------------------------------------------------- helpers for connectors
    def api(self, base, headers=None, timeout=60):
        return Api(base, headers=headers or {}, service=self.name, timeout=timeout, transport=self.transport)

    def need(self, *keys):
        missing = [k for k in keys if not self.creds.get(k)]
        if missing:
            raise SocialError("auth", f"{self.label} is not connected: run 'ai-pc social connect {self.name}' (steps: 'ai-pc social steps {self.name}')")

    def call(self, fn, *a, **kw):
        """An API call with the platform's errors turned into SocialError kinds."""
        try:
            return fn(*a, **kw)
        except HubError as e:
            raise self.classify(e) from e

    def classify(self, e):
        status = getattr(e, "status", None)
        if status in (401,):
            return SocialError("auth", f"{self.label}: the sign-in has expired or was withdrawn; connect again", code=status, detail=e.body)
        if status == 429:
            return SocialError("limit", f"{self.label}: too many requests for now", retry_after=60, code=status, detail=e.body)
        if status and status >= 500:
            return SocialError("retry", f"{self.label}: the service had a problem ({status})", code=status, detail=e.body)
        if status is None:
            return SocialError("retry", f"{self.label}: no connection ({e})")
        return SocialError("invalid", f"{self.label}: {e}", code=status, detail=e.body)

    def checkpoint(self, job, **kv):
        job.setdefault("remote", {}).update(kv)
        if self.store is not None:
            self.store.checkpoint(job["id"], **kv)

    def ready(self):
        """Its keys are in the vault (a shared vault entry may hold one platform's keys and not another's)."""
        return bool(self.creds)

    # ---------------------------------------------------------------- what each connector provides
    def whoami(self):
        raise NotImplementedError

    def publish(self, job, post, prepared, budget=120):
        raise NotImplementedError

    def status(self, job):
        """Where a published or scheduled post stands now (read back from the platform)."""
        raise NotImplementedError

    def delete(self, job):
        raise SocialError("policy", f"{self.label} does not let apps delete posts; delete it in the app")

    def metrics(self, job):
        return {}

    def comments(self, job, since=None):
        return []

    def reply(self, job, comment_id, text):
        raise SocialError("policy", f"{self.label}: replying to comments is not available through its API")

    def hide(self, job, comment_id, hidden=True):
        raise SocialError("policy", f"{self.label}: hiding comments is not available through its API")

    def limits(self):
        return {}
