"""S-expressions as KiCad writes them (.kicad_sym, .kicad_sch, netlists): read into nested lists, written back."""

import re

TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')


class Str(str):
    """A string that was quoted in the file (written back with quotes)."""


def parse(text):
    stack, cur, pos = [], [], 0
    while True:
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group(1):
            stack.append(cur)
            cur = []
        elif m.group(2):
            done, cur = cur, stack.pop()
            cur.append(done)
        elif m.group(3) is not None:
            cur.append(Str(m.group(3).replace('\\"', '"').replace("\\\\", "\\")))
        else:
            cur.append(m.group(4))
    return cur[0] if len(cur) == 1 else cur


def dump(x, indent=0):
    if isinstance(x, list):
        if not x:
            return "()"
        simple = all(not isinstance(i, list) for i in x)
        if simple or len(x) <= 2 and all(not isinstance(i, list) or len(i) <= 3 for i in x):
            return "(" + " ".join(dump(i, indent) for i in x) + ")"
        head = [dump(i, indent) for i in x if not isinstance(i, list)]
        body = [i for i in x if isinstance(i, list)]
        first = "(" + " ".join(head)
        return first + "".join("\n" + "  " * (indent + 1) + dump(i, indent + 1) for i in body) + ")"
    if isinstance(x, Str):
        return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(x, float):
        return f"{x:.4f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))
    return str(x)


def find(x, key):
    """Every sub-list whose head is key (one level down)."""
    return [i for i in x if isinstance(i, list) and i and i[0] == key]


def first(x, key, default=None):
    hits = find(x, key)
    return hits[0] if hits else default


def walk(x, key):
    """Every sub-list whose head is key, at any depth."""
    if isinstance(x, list):
        if x and x[0] == key:
            yield x
        for i in x:
            yield from walk(i, key)
