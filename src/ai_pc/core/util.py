"""Small shared helpers."""

import json
import re
import time


def parse_json(text):
    """Extract the first JSON object from model output (tolerates code fences and <think> blocks)."""
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001 - not JSON as it stands: try the outermost braces next
        pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s : e + 1])
        except Exception:  # noqa: BLE001 - no JSON in the text
            return None
    return None


class Timer:
    def __init__(self):
        self.t0 = time.perf_counter()

    def ms(self):
        return (time.perf_counter() - self.t0) * 1000


def slug(text, n=40):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "task"
