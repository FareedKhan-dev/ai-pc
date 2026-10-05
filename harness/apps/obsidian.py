"""Obsidian vaults by their own files (Obsidian only shows them): a vault from words (a topic and its notes) or from an
outline (a Markdown or Word file, one note per heading). It holds a Home note (map of content) linking every note,
the notes with frontmatter (tags, date) and [[links]] to their neighbours, a daily note, a daily-note template, a
.canvas board with every note as a card, and .obsidian settings (core plugins, daily notes, templates). Checked: every
[[link]] and canvas card points at a note that exists, every settings and canvas file reads back as JSON.

  'obsidian vault for my exam prep with notes on Physics, Chemistry and Maths'   'obsidian vault from outline.md'
"""
import json
import re
from datetime import date
from pathlib import Path

NAME, LABEL = "obsidian", "Obsidian: vaults from words or an outline: linked notes, Home map, daily note, canvas board; every link checked"
EXAMPLES = ["obsidian vault for my exam prep with notes on Physics, Chemistry and Maths", "obsidian vault from outline.md"]
CORE = ["file-explorer", "global-search", "switcher", "graph", "backlink", "canvas", "outgoing-link", "tag-pane", "page-preview", "daily-notes",
        "templates", "note-composer", "command-palette", "editor-status", "bookmarks", "outline", "word-count", "file-recovery"]


def safe(name):
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", name)).strip() or "Note"


def tag(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "note"


def outline(path):
    """[(title, body)] from a Markdown or Word file: one note per heading."""
    p = Path(path)
    if p.suffix.lower() == ".docx":
        from docx import Document
        doc = Document(str(p))
        lines = []
        for para in doc.paragraphs:
            style = (para.style.name or "").lower()
            lines.append(("## " if style.startswith("heading") else "") + para.text)
    else:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    notes, title, body = [], None, []
    sections = any(re.match(r"^#{2,3}\s", ln) for ln in lines)  # with ## sections, a lone # title names the vault, not a note
    for ln in lines:
        m = re.match(r"^#{2,3}\s+(.+)$" if sections else r"^#{1,3}\s+(.+)$", ln)
        if m:
            if title:
                notes.append((title, "\n".join(body).strip()))
            title, body = m.group(1).strip(), []
        elif title:
            body.append(ln)
    if title:
        notes.append((title, "\n".join(body).strip()))
    return notes


def links(text):
    return [m.split("|")[0].split("#")[0].strip() for m in re.findall(r"\[\[([^\]]+)\]\]", text)]


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bobsidian\b", c):
        return None
    f = find_file(text, ctx, {".md", ".docx", ".txt"})
    if f and re.search(r"\bfrom\b|\boutline\b|\bimport\b", c):
        first = None if Path(f).suffix.lower() == ".docx" else next(
            (ln[2:].strip() for ln in Path(f).read_text(encoding="utf-8", errors="replace").splitlines() if ln.startswith("# ")), None)
        return {"op": "vault", "from": f, "topic": safe(first or Path(f).stem.replace("_", " ").title())}
    m = re.search(r"\bnotes?\s+(?:on|about|for|:)\s+(.+)$", text, re.I)
    notes = [safe(n) for n in re.split(r",|\band\b", m.group(1).strip(" .")) if n.strip()] if m else []
    t = re.search(r"\bvault\s+(?:for|about|on|called|named)\s+(?:my\s+|the\s+)?(.+?)(?:\s+with\b|$)", text, re.I)
    topic = safe(t.group(1).strip(" .'\"")).title() if t else "My vault"
    return {"op": "vault", "topic": topic, "notes": notes or ["Ideas", "Projects", "Reading list", "Meetings"]}


def run(op, ctx):
    topic = op["topic"]
    vault = (Path(ctx["out"]) / "obsidian" / topic).resolve()
    today = (ctx.get("now") or date.today()).strftime("%Y-%m-%d")
    if op.get("from"):
        pairs = outline(op["from"])
        if not pairs:
            return f"No headings found in {Path(op['from']).name}: an outline needs headings (# Title) to become notes."
    else:
        pairs = [(n, "") for n in op["notes"]]
    names = [safe(t) for t, _ in pairs]
    files = {}
    for i, (name, (title, body)) in enumerate(zip(names, pairs)):
        near = [names[j] for j in (i - 1, i + 1) if 0 <= j < len(names)]
        files[f"{name}.md"] = (f"---\ntags: [{tag(topic)}, {tag(name)}]\ncreated: {today}\n---\n# {title}\n\n" +
                               (body + "\n\n" if body else "## Summary\n\n- \n\n## Key points\n\n- \n\n## Questions\n\n- \n\n") +
                               f"## Related\n\n- Back to [[Home]]\n" + "".join(f"- [[{n}]]\n" for n in near))
    files["Home.md"] = (f"---\ntags: [{tag(topic)}, moc]\ncreated: {today}\n---\n# {topic}\n\nMap of this vault.\n\n" +
                        "".join(f"- [[{n}]]\n" for n in names) + f"\nToday: [[{today}]]\nBoard: [[{topic} board.canvas]]\n")
    files[f"Daily/{today}.md"] = f"---\ntags: [daily]\n---\n# {today}\n\n## Plan\n\n- [ ] \n\n## Notes\n\n- Worked on: [[Home]]\n"
    files["Templates/Daily.md"] = "---\ntags: [daily]\n---\n# {{date}}\n\n## Plan\n\n- [ ] \n\n## Notes\n\n- \n"
    cols = max(1, min(4, len(names)))
    nodes = [{"id": "home", "type": "file", "file": "Home.md", "x": -150, "y": -420, "width": 300, "height": 120}]
    nodes += [{"id": f"n{i}", "type": "file", "file": f"{n}.md", "x": (i % cols) * 340 - cols * 170, "y": (i // cols) * 260 - 180, "width": 300, "height": 200}
              for i, n in enumerate(names)]
    edges = [{"id": f"e{i}", "fromNode": "home", "fromSide": "bottom", "toNode": f"n{i}", "toSide": "top"} for i in range(len(names))]
    files[f"{topic} board.canvas"] = json.dumps({"nodes": nodes, "edges": edges}, indent=2)
    settings = {".obsidian/app.json": {"alwaysUpdateLinks": True, "newFileLocation": "root", "showLineNumber": True},
                ".obsidian/core-plugins.json": CORE,
                ".obsidian/daily-notes.json": {"folder": "Daily", "format": "YYYY-MM-DD", "template": "Templates/Daily"},
                ".obsidian/templates.json": {"folder": "Templates"}}
    for rel, data in settings.items():
        files[rel] = json.dumps(data, indent=2)
    for rel, text in files.items():
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
    known = {p.relative_to(vault).as_posix()[:-3].lower() for p in vault.rglob("*.md")} | {p.stem.lower() for p in vault.rglob("*.md")} | \
            {p.name.lower() for p in vault.rglob("*.canvas")}
    all_links = [(p.name, ln) for p in vault.rglob("*.md") if "Templates" not in p.parts for ln in links(p.read_text(encoding="utf-8"))]
    broken = [f"{src} -> [[{ln}]]" for src, ln in all_links if ln.lower() not in known]
    canvas = json.loads((vault / f"{topic} board.canvas").read_text(encoding="utf-8"))
    missing_cards = [n["file"] for n in canvas["nodes"] if not (vault / n["file"]).exists()]
    json_ok = all(json.loads((vault / rel).read_text(encoding="utf-8")) is not None for rel in settings)
    checks = [(f"all {len(all_links)} [[links]] point at notes that exist", not broken),
              (f"the canvas board's {len(canvas['nodes'])} cards are all real notes", not missing_cards),
              ("the .obsidian settings (core plugins, daily notes, templates) read back as JSON", json_ok)]
    bad = [w for w, good in checks if not good]
    return (f"Obsidian vault '{topic}' at {vault}: Home, {len(names)} notes ({', '.join(names[:6])}{'...' if len(names) > 6 else ''}), a daily note, "
            f"a template and a canvas board (in Obsidian: Open folder as vault). " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + "; ".join((broken + missing_cards)[:5])))
