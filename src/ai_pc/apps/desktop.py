"""Small desktop jobs by code: a screenshot of every screen saved as a picture, text put on or read from the clipboard,
and a file, folder or web address opened in the program Windows uses for it. Nothing moves the mouse or types.

  'take a screenshot'   "copy 'Meezan Bank PK36MEZN0001234567890123' to the clipboard"   "what's in my clipboard?"   'open D:\\Shop\\prices.xlsx'
"""

import datetime as dt
import os
import re
from pathlib import Path

NAME, LABEL = "desktop", "Desktop: screenshots, clipboard, open files and web pages"
EXAMPLES = ["take a screenshot", "copy 'Meezan Bank PK36MEZN0001234567890123' to the clipboard", "open D:\\Shop\\prices.xlsx"]


def screenshot(dest):
    from PIL import ImageGrab

    im = ImageGrab.grab(all_screens=True)
    im.save(dest)
    return im.size


def clip_get():
    import win32clipboard as cb

    cb.OpenClipboard()
    try:
        return cb.GetClipboardData(cb.CF_UNICODETEXT) if cb.IsClipboardFormatAvailable(cb.CF_UNICODETEXT) else None
    finally:
        cb.CloseClipboard()


def clip_set(text):
    import win32clipboard as cb

    cb.OpenClipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(cb.CF_UNICODETEXT, text)
    finally:
        cb.CloseClipboard()


def parse(text, ctx):
    c = text.lower().strip(" ?.!")
    if re.search(r"\b(?:take|grab|capture)\b.*\bscreenshot\b|^screenshot$|\bscreen ?shot of (?:my|the) screen\b", c):
        return {"op": "shot"}
    m = re.match(r"^\s*copy\s+(?:'([^']*)'|\"([^\"]*)\")\s+(?:to|on|into)\s+(?:the\s+)?clipboard\s*$", text, re.I)
    if m:
        return {"op": "clip_set", "text": m.group(1) if m.group(1) is not None else m.group(2)}
    if re.search(r"\bwhat(?:'s| is) (?:in|on) (?:my |the )?clipboard\b|\bread (?:my |the )?clipboard\b", c):
        return {"op": "clip_get"}
    m = re.match(r"^\s*open\s+(.+?)\s*$", text, re.I)
    if m:
        target = m.group(1).strip(" '\"")
        if re.match(r"https?://", target) or Path(target).exists():
            return {"op": "open", "target": target}
    return None


def run(op, ctx):
    if op["op"] == "shot":
        out = Path(ctx["out"]) / "screenshots"
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"screen_{dt.datetime.now():%Y-%m-%d_%H%M%S}.png"
        w, h = screenshot(dest)
        return f"Screenshot of every screen ({w} x {h}): {dest}."
    if op["op"] == "clip_set":
        clip_set(op["text"])
        ok = clip_get() == op["text"]
        return f"On the clipboard ({'checked' if ok else 'NOT there when read back'}): paste it with Ctrl+V."
    if op["op"] == "clip_get":
        t = clip_get()
        return "The clipboard holds no text." if t is None else f"The clipboard holds ({len(t)} characters): {t[:500]}"
    os.startfile(op["target"])  # noqa: S606 - the person asked to open it
    return f"Opened {op['target']}."
