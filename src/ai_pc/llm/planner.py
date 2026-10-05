"""Planners turn (goal, observation, history[, screenshot]) into the next actions.

ChatPlanner     real model calls through the OpenAI-compatible API (Nebius): fast / vision / deep tiers (see config.MODELS)
ScriptedPlanner deterministic test double (used by the test-suite to exercise the loop without a network)
FilePlanner     requests are written to files and answered by a person or an assistant (demonstration / debugging)
"""

import base64
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field

from ai_pc.core.config import MODELS, PRICES, RUNS
from ai_pc.core.keys import get_key
from ai_pc.core.util import parse_json
from ai_pc.llm import prompts
from ai_pc.llm.client import Chat, LLMError


class PlannerError(Exception):
    pass


@dataclass
class Plan:
    thought: str = ""
    risk: str = "low"
    confidence: object = None
    actions: list = field(default_factory=list)
    done: bool = False
    success: object = None
    answer: object = None
    skill: object = None
    evidence: object = None
    raw: str = ""
    model: str = ""
    ms: float = 0.0
    tokens: tuple = (0, 0)


def to_plan(d, raw="", model="", ms=0.0, usage=None):
    acts = [a for a in (d.get("actions") or []) if isinstance(a, dict) and a.get("op")]
    try:
        conf = float(d["confidence"]) if d.get("confidence") is not None else None  # None = the planner did not say
    except (TypeError, ValueError):
        conf = None
    u = usage or {}
    return Plan(
        thought=str(d.get("thought", ""))[:300],
        risk=str(d.get("risk", "low")).lower(),
        confidence=conf,
        actions=acts[:6],
        done=bool(d.get("done")),
        success=d.get("success"),
        answer=d.get("answer"),
        skill=d.get("skill") if isinstance(d.get("skill"), dict) else None,
        evidence=d.get("evidence"),
        raw=raw,
        model=model,
        ms=ms,
        tokens=(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)),
    )


class ChatPlanner:
    def __init__(self, chat=None):
        self.chat = chat or Chat(get_key())
        # persistent workers keep their keep-alive connections (a fresh TLS handshake to the EU costs ~0.3-0.5 s)
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="planner")
        self.hedges = 0
        self.usage = {}  # model -> {"calls", "in", "out", "hedged"}: what this planner has spent
        self._ulock = threading.Lock()

    def _count(self, model, r, hedged):
        u = r.usage or {}
        with self._ulock:
            x = self.usage.setdefault(model, {"calls": 0, "in": 0, "out": 0, "hedged": 0})
            x["calls"] += 1
            x["in"] += int(u.get("prompt_tokens") or 0)
            x["out"] += int(u.get("completion_tokens") or 0)
            x["hedged"] += int(hedged)  # a hedged call ran twice: the backup is billed too (counted below)

    def cost(self):
        """{model: {..., "usd"}} and the total, from config.PRICES (USD per million tokens, input / output)."""
        out, total = {}, 0.0
        for m, x in self.usage.items():
            pin, pout = PRICES.get(m, (0.0, 0.0))
            factor = 1 + x["hedged"] / max(1, x["calls"])  # assume the losing backup cost as much as the winner
            usd = (x["in"] * pin + x["out"] * pout) / 1e6 * factor
            out[m] = {**x, "usd": round(usd, 5)}
            total += usd
        return out, round(total, 5)

    def _call(self, tier, messages):
        """One model call. If it is slower than the tier's hedge_s, an identical backup request is sent and the first
        answer wins: cheap insurance against provider latency spikes (seen: 14-64 s for a normally 2-4 s call)."""
        cfg = MODELS[tier]

        def go():
            return self.chat.complete_with_fallback(cfg["model"], messages, [cfg["extra"] or {}, {}], max_tokens=cfg["max_tokens"])

        futs = [self._pool.submit(go)]
        if cfg.get("hedge_s"):
            done, _ = wait(futs, timeout=cfg["hedge_s"])
            if not done:
                futs.append(self._pool.submit(go))
                self.hedges += 1
        err = None
        try:  # a hard deadline per call: a stalled answer must never freeze the run (seen: 1 h on a stuck stream)
            for f in as_completed(futs, timeout=cfg.get("deadline_s", 120)):
                try:
                    r = f.result()
                    r.hedged = len(futs) > 1
                    self._count(cfg["model"], r, r.hedged)
                    return r
                except LLMError as e:
                    err = e
        except FuturesTimeout:
            raise PlannerError(f"{tier}: no answer within {cfg.get('deadline_s', 120)} s") from None
        raise PlannerError(str(err))

    def next(self, goal, observation, history=None, image_jpeg=None, subgoal=None, note=None, tier="fast"):
        text = prompts.user_message(goal, observation, history, subgoal, note)
        if image_jpeg:
            tier = "vision"
            content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode()}},
            ]
        else:
            content = text
        messages = [{"role": "system", "content": prompts.PLANNER_SYSTEM}, {"role": "user", "content": content}]
        r = self._call(tier, messages)
        d = parse_json(r.text)
        if d is None:  # one repair attempt
            messages += [
                {"role": "assistant", "content": r.text[:1500]},
                {"role": "user", "content": "That was not valid JSON. Reply with the single JSON object only."},
            ]
            r2 = self._call(tier, messages)
            d, r = parse_json(r2.text), r2
        if d is None:
            raise PlannerError("planner returned no valid JSON")
        return to_plan(d, r.text, MODELS[tier]["model"] + (" (hedged)" if getattr(r, "hedged", False) else ""), r.total_ms, r.usage)

    def deep_plan(self, goal, context):
        messages = [
            {"role": "system", "content": prompts.DEEP_SYSTEM},
            {"role": "user", "content": f"GOAL: {goal}\n\nCONTEXT:\n{context}\n\nProduce the plan JSON."},
        ]
        r = self._call("deep", messages)
        d = parse_json(r.text)
        if d is None:
            raise PlannerError("deep planner returned no valid JSON")
        d["_ms"] = r.total_ms
        return d


class ScriptedPlanner:
    """fn(goal, observation, history) -> dict in the planner JSON format. For tests."""

    def __init__(self, fn, deep=None):
        self.fn, self.deep, self.calls = fn, deep, 0

    def next(self, goal, observation, history=None, image_jpeg=None, subgoal=None, note=None, tier="fast"):
        self.calls += 1
        return to_plan(self.fn(goal, observation, history or []), model="scripted")

    def deep_plan(self, goal, context):
        self.calls += 1
        return self.deep(goal, context) if self.deep else {"approach": "scripted", "subgoals": []}


class FilePlanner:
    """Writes planner requests to runs/planner/req_N.json and waits for res_N.json (a person or an assistant answers)."""

    def __init__(self, directory=None, timeout=900):
        self.dir = directory or (RUNS / "planner")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.timeout, self.n = timeout, 0

    def _ask(self, kind, payload, image_jpeg=None):
        self.n += 1
        if image_jpeg:
            (self.dir / f"req_{self.n}.jpg").write_bytes(image_jpeg)
            payload["image"] = f"req_{self.n}.jpg"
        (self.dir / f"req_{self.n}.json").write_text(json.dumps({"kind": kind, **payload}, indent=1), encoding="utf-8")
        res = self.dir / f"res_{self.n}.json"
        t0 = time.time()
        while time.time() - t0 < self.timeout:
            if res.exists():
                try:
                    return json.loads(res.read_text(encoding="utf-8")), (time.time() - t0) * 1000
                except json.JSONDecodeError:
                    pass
            time.sleep(0.2)
        raise PlannerError(f"no answer for request {self.n} within {self.timeout}s")

    def next(self, goal, observation, history=None, image_jpeg=None, subgoal=None, note=None, tier="fast"):
        d, ms = self._ask("next", {"goal": goal, "subgoal": subgoal, "note": note, "history": history or [], "observation": observation}, image_jpeg)
        return to_plan(d, json.dumps(d), "file", ms)

    def deep_plan(self, goal, context):
        d, ms = self._ask("deep", {"goal": goal, "context": context})
        d["_ms"] = ms
        return d
