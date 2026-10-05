"""One helper for vision-model questions that must come back as JSON (media captions, edit checks)."""
import base64
import time

from ai_pc.core.util import parse_json


def ask(planner, system, text, images=(), tier="caption"):
    """(parsed JSON or None, seconds). Images are JPEG bytes, sent in order after the text."""
    content = [{"type": "text", "text": text}] + [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(im).decode()}} for im in images]
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    t0 = time.perf_counter()
    r = planner._call(tier, msgs)
    d = parse_json(r.text)
    if d is None:  # one repair attempt, text only
        r = planner._call(tier, msgs + [{"role": "assistant", "content": r.text[:2000]},
                                        {"role": "user", "content": "Reply with the single JSON object only."}])
        d = parse_json(r.text)
    return d, round(time.perf_counter() - t0, 2)
