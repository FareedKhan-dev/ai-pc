"""Notes and to-dos as plain Markdown files in a folder (Obsidian, VS Code and Notepad open them; state/notes unless you
name your own folder, e.g. your Obsidian vault): quick notes and to-dos go into today's note, named notes get their
own file, tasks are '- [ ]' lines found across every note and ticked off by their words, and every note is searchable.

  'note: call the supplier about the TV order'   'todo: pay the electricity bill by Friday'   'my tasks'   'done: pay the electricity bill'
  "new note 'Meeting with Ali': prices agreed at 84,000"   'find notes about tax'   'notes folder is D:\\Obsidian\\Vault'
"""

import datetime as dt
import json
import re
from pathlib import Path

from ai_pc.core.config import STATE

NAME, LABEL = "notes", "Notes and to-dos (Markdown, Obsidian-compatible)"
EXAMPLES = ["note: call the supplier about the TV order", "todo: pay the electricity bill by Friday", "my tasks", "find notes about tax"]
SETTINGS = STATE / "apps" / "notes.json"


def vault(ctx=None):
    if ctx and ctx.get("notes_dir"):
        return Path(ctx["notes_dir"])
    if SETTINGS.exists():
        return Path(json.loads(SETTINGS.read_text(encoding="utf-8"))["folder"])
    return STATE / "notes"


def _safe(name):
    return re.sub(r'[<>:"/\\|?*]+', "-", name).strip(" .")[:120] or "note"


def daily(v, now):
    p = v / f"{now:%Y-%m-%d}.md"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {now:%A %d %B %Y}\n\n", encoding="utf-8")
    return p


def tasks(v):
    out = []
    for f in sorted(v.rglob("*.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines()):
            m = re.match(r"^\s*[-*] \[( |x|X)\] (.+)$", line)
            if m:
                out.append({"file": f, "line": i, "done": m.group(1) != " ", "text": m.group(2).strip()})
    return out


def parse(text, ctx):
    raw = text.strip()
    c = raw.lower()
    m = re.match(r"^\s*(?:my\s+)?notes? folder is\s+(.+)$", raw, re.I)
    if m:
        return {"op": "folder", "path": m.group(1).strip(" '\"")}
    m = re.match(r"^\s*(?:note|remember|jot down)\s*:\s*(.+)$", raw, re.I | re.S)
    if m:
        return {"op": "note", "text": m.group(1).strip()}
    m = re.match(r"^\s*(?:to-?do|task|add task)\s*:\s*(.+)$", raw, re.I | re.S)
    if m:
        return {"op": "todo", "text": m.group(1).strip()}
    m = re.match(r"^\s*new note\s*(?:'([^']+)'|\"([^\"]+)\"|([^:]+))\s*:\s*(.+)$", raw, re.I | re.S)
    if m:
        return {"op": "new", "title": (m.group(1) or m.group(2) or m.group(3)).strip(), "text": m.group(4).strip()}
    if re.search(r"^\s*(?:my\s+)?(?:tasks|to-?dos?|to-?do list)\s*\??$|\bwhat(?:'s| is) (?:on )?my to-?do", c):
        return {"op": "tasks"}
    m = re.match(r"^\s*(?:done|finished|completed|tick off)\s*:?\s+(.+)$", raw, re.I)
    if m:
        return {"op": "done", "text": m.group(1).strip()}
    m = re.match(r"^\s*(?:find|search)\s+(?:my\s+)?notes?\s+(?:about|for|with)\s+(.+?)\s*\??$", raw, re.I)
    if m:
        return {"op": "find", "words": m.group(1).strip()}
    m = re.match(r"^\s*(?:show|open|read)\s+(?:the\s+)?note\s+(.+)$", raw, re.I)
    if m:
        return {"op": "show", "title": m.group(1).strip(" '\"")}
    return None


def run(op, ctx):
    v = vault(ctx)
    v.mkdir(parents=True, exist_ok=True)
    now = ctx.get("now") or dt.datetime.now()
    k = op["op"]
    if k == "folder":
        p = Path(op["path"])
        if not p.exists():
            return f"{p} does not exist."
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps({"folder": str(p)}), encoding="utf-8")
        return f"Notes now go to {p} ({len(list(p.rglob('*.md')))} notes there)."
    if k in ("note", "todo"):
        f = daily(v, now)
        line = f"- [ ] {op['text']}" if k == "todo" else f"- {now:%H:%M} {op['text']}"
        with f.open("a", encoding="utf-8") as h:
            h.write(line + "\n")
        ok = line in f.read_text(encoding="utf-8")
        return f"{'To-do' if k == 'todo' else 'Note'} added to {f.name} ({'checked' if ok else 'NOT found when read back'})."
    if k == "new":
        f = v / f"{_safe(op['title'])}.md"
        if f.exists():
            with f.open("a", encoding="utf-8") as h:
                h.write(f"\n{op['text']}\n")
            return f"Added to the note {f.name}."
        f.write_text(f"# {op['title']}\n\n_{now:%d %B %Y %H:%M}_\n\n{op['text']}\n", encoding="utf-8")
        return f"Note saved: {f}."
    if k == "tasks":
        open_ = [t for t in tasks(v) if not t["done"]]
        return "No open to-dos." if not open_ else f"{len(open_)} to-dos:\n" + "\n".join(f"- {t['text']} ({t['file'].stem})" for t in open_)
    if k == "done":
        w = op["text"].lower()
        hits = [t for t in tasks(v) if not t["done"] and (w in t["text"].lower() or all(x in t["text"].lower() for x in w.split()))]
        if not hits:
            return f"No open to-do matches '{op['text']}'."
        if len(hits) > 1 and not any(t["text"].lower() == w for t in hits):
            return "Which one? " + "; ".join(t["text"] for t in hits[:5])
        t = next((t for t in hits if t["text"].lower() == w), hits[0])
        lines = t["file"].read_text(encoding="utf-8").splitlines()
        lines[t["line"]] = re.sub(r"\[ \]", "[x]", lines[t["line"]], count=1) + f" (done {now:%d %b %H:%M})"
        t["file"].write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f"Ticked off: {t['text']}."
    if k == "find":
        words = [w for w in re.split(r"\s+", op["words"].lower()) if w]
        found = []
        for f in sorted(v.rglob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            if all(w in text.lower() for w in words):
                line = next((ln for ln in text.splitlines() if any(w in ln.lower() for w in words)), "")
                found.append(f"{f.stem}: {line.strip()[:120]}")
        return "Nothing found." if not found else f"{len(found)} notes:\n" + "\n".join(found[:15])
    if k == "show":
        f = next((x for x in v.rglob("*.md") if x.stem.lower() == op["title"].lower()), None) or next(
            (x for x in v.rglob("*.md") if op["title"].lower() in x.stem.lower()), None
        )
        return f"No note called '{op['title']}'." if not f else f.read_text(encoding="utf-8")[:3000]
    return "?"
