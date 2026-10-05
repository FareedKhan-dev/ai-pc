"""LaTeX (the way papers and theses are written; Tectonic 0.17 in tools/tectonic, a complete TeX engine that fetches only the
packages a document needs, cached in tools/tectonic/cache): a .tex given compiled to PDF (problems reported with their
line), or an article / thesis made from Markdown or Word (headings, lists, bold/italic, maths, tables, [@citations] with a
.bib from the citations program). Checked: it compiles with no errors, the PDF has its pages, title and every heading,
and no reference or citation is left unresolved ('??' or '[?]').

  'latex compile paper.tex'   "latex paper from notes.md titled 'Solar Pumps in Punjab' by Ali Khan with refs.bib"
  "latex thesis from chapters.docx titled 'Water Use in Sindh' by Sara"
"""
import os
import re
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "latex", "LaTeX (Tectonic): compile .tex, or papers/theses from Markdown/Word with maths, tables, citations"
EXAMPLES = ["latex compile paper.tex", "latex paper from notes.md titled 'Solar Pumps in Punjab' by Ali Khan with refs.bib"]
HOME = ROOT / "tools" / "tectonic"
EXE = HOME / "tectonic.exe"
SPECIAL = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def esc(text):
    """Plain text made safe for LaTeX, keeping $...$ maths as it is."""
    parts = re.split(r"(\$\$.*?\$\$|\$(?=\S)[^$]*?(?<=\S)\$(?!\d))", text)  # pandoc's rule: maths $ hugs its content, so '$5' stays money
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(p)
            continue
        p = "".join(r"\textbackslash{}" if ch == "\\" else SPECIAL.get(ch, ch) for ch in p)  # one pass, so no brace is escaped twice
        p = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\\emph{\1}", p)
        p = re.sub(r"\[@([\w:-]+(?:;\s*@[\w:-]+)*)\]", lambda m: r"\cite{" + ",".join(k.strip().lstrip("@") for k in m.group(1).split(";")) + "}", p)
        out.append(p)
    return "".join(out)


def blocks_from_markdown(text):
    """[(kind, payload)]: heading (level, text), para, list (items), equation, table (rows)."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.+)$", ln)
        if m:
            out.append(("heading", (len(m.group(1)), m.group(2).strip())))
            i += 1
        elif ln.strip().startswith("$$") and "$$" in ln.strip()[2:]:  # $$ ... $$ on one line
            out.append(("equation", ln.strip()[2:].split("$$")[0].strip()))
            i += 1
        elif ln.strip().startswith("$$"):
            body = [ln.strip()[2:]]
            i += 1
            while i < len(lines) and "$$" not in lines[i]:
                body.append(lines[i])
                i += 1
            if i < len(lines):
                body.append(lines[i].replace("$$", ""))
                i += 1
            out.append(("equation", " ".join(b.strip() for b in body if b.strip())))
        elif re.match(r"^\s*[-*+]\s+", ln) or re.match(r"^\s*\d+[.)]\s+", ln):
            ordered = bool(re.match(r"^\s*\d+[.)]\s+", ln))
            items = []
            while i < len(lines) and (re.match(r"^\s*[-*+]\s+", lines[i]) or re.match(r"^\s*\d+[.)]\s+", lines[i])):
                items.append(re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", lines[i]).strip())
                i += 1
            out.append(("list", (ordered, items)))
        elif ln.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append(("table", rows))
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,3}\s|\s*[-*+]\s|\s*\d+[.)]\s|\$\$|\|)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(("para", " ".join(para)))
    return out


def blocks_from_docx(path):
    from docx import Document
    out = []
    for p in Document(str(path)).paragraphs:
        t = p.text.strip()
        if not t:
            continue
        style = (p.style.name or "").lower()
        m = re.match(r"heading\s*(\d)", style)
        if m:
            out.append(("heading", (min(3, int(m.group(1))), t)))
        elif "list" in style:
            if out and out[-1][0] == "list":
                out[-1][1][1].append(t)
            else:
                out.append(("list", ("number" in style, [t])))
        elif style == "title":
            continue
        else:
            out.append(("para", t))
    return out


def tex_document(blocks, title, author, kind="article", bib=None):
    cls = "report" if kind == "thesis" else "article"
    names = (["chapter", "section", "subsection"] if kind == "thesis" else ["section", "subsection", "subsubsection"])
    body = []
    for k, v in blocks:
        if k == "heading":
            body.append(f"\\{names[v[0] - 1]}{{{esc(v[1])}}}")
        elif k == "para":
            body.append(esc(v))
        elif k == "list":
            env = "enumerate" if v[0] else "itemize"
            body.append(f"\\begin{{{env}}}\n" + "\n".join(f"  \\item {esc(it)}" for it in v[1]) + f"\n\\end{{{env}}}")
        elif k == "equation":
            body.append(f"\\begin{{equation}}\n  {v}\n\\end{{equation}}")
        elif k == "table" and v:
            cols = max(len(r) for r in v)
            rows = [" & ".join(esc(c) for c in r + [""] * (cols - len(r))) + r" \\" for r in v]
            body.append("\\begin{table}[h]\n\\centering\n\\begin{tabular}{" + "l" * cols + "}\n\\toprule\n" + rows[0] + "\n\\midrule\n" +
                        "\n".join(rows[1:]) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}")
    refs = f"\n\\bibliographystyle{{plain}}\n\\bibliography{{{Path(bib).stem}}}\n" if bib else ""
    return (f"\\documentclass[11pt]{{{cls}}}\n\\usepackage[margin=2.5cm]{{geometry}}\n\\usepackage{{amsmath,amssymb,booktabs}}\n\\usepackage{{hyperref}}\n"
            f"\\title{{{esc(title)}}}\n\\author{{{esc(author)}}}\n\\date{{\\today}}\n\\begin{{document}}\n\\maketitle\n" +
            ("\\tableofcontents\n" if kind == "thesis" else "") + "\n\n".join(body) + "\n" + refs + "\\end{document}\n")


def compile_tex(tex, outdir):
    from ai_pc.core import hidden_desktop
    cache = HOME / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    rc, out, err, timed_out = hidden_desktop.run([str(EXE), "-X", "compile", str(tex), "--outdir", str(outdir)], timeout=900,
                                                 env=dict(os.environ, TECTONIC_CACHE_DIR=str(cache.resolve())), cwd=str(Path(tex).parent))
    text = out + err
    problems = [ln.strip() for ln in text.splitlines() if re.search(r"^\s*error:|\.tex:\d+:", ln)]
    return rc == 0 and not timed_out, problems, text


def check(pdf, title, headings, problems):
    from pypdf import PdfReader
    pages = PdfReader(str(pdf)).pages if pdf.exists() else []
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pages))
    flat = re.sub(r"[^a-z0-9]+", "", text.lower())
    missing = [h for h in headings if re.sub(r"[^a-z0-9]+", "", h.lower()) not in flat]
    return [("it compiles with no errors", pdf.exists() and not problems),
            (f"the PDF has {len(pages)} page(s) with the title", bool(pages) and (not title or re.sub(r"[^a-z0-9]+", "", title.lower()) in flat)),
            (f"every heading is there ({len(headings) - len(missing)} of {len(headings)})", not missing),
            ("no unresolved reference or citation ('??' or '[?]')", "??" not in text and "[?]" not in text)]


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\blatex\b|\btex\b|\boverleaf\b|\.tex\b", c):
        return None
    tex = find_file(text, ctx, {".tex"})
    if tex:
        return {"op": "compile", "file": tex}
    src = find_file(text, ctx, {".md", ".markdown", ".docx", ".txt"})
    if not src:
        return None
    title = re.search(r"\btitled?\s+['\"]([^'\"]+)['\"]", text, re.I)
    author = re.search(r"\bby\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,3})", text)
    bib = find_file(text, ctx, {".bib"}) if re.search(r"\.bib\b|\breferences?\b|\bbibliograph", c) else None
    return {"op": "make", "file": src, "kind": "thesis" if re.search(r"\bthesis\b|\breport\b|\bdissertation\b", c) else "article",
            "title": title.group(1) if title else Path(src).stem.replace("_", " ").title(), "author": author.group(1) if author else "", "bib": bib}


def run(op, ctx):
    if not EXE.exists():
        return "Tectonic (LaTeX) is not in tools/tectonic."
    out = (Path(ctx["out"]) / "latex").resolve()
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "compile":
        tex = Path(op["file"]).resolve()
        work = out / tex.stem
        work.mkdir(exist_ok=True)
        for f in tex.parent.iterdir():  # the .tex with its .bib and pictures, so the original folder is not written to
            if f.is_file() and f.suffix.lower() in (".tex", ".bib", ".png", ".jpg", ".jpeg", ".pdf", ".cls", ".sty", ".bst") and f.stat().st_size < 50_000_000:
                (work / f.name).write_bytes(f.read_bytes())
        src = work / tex.name
        title, headings = None, re.findall(r"\\(?:chapter|section|subsection)\*?\{([^}]*)\}", src.read_text(encoding="utf-8", errors="replace"))
    else:
        srcfile = Path(op["file"])
        blocks = blocks_from_docx(srcfile) if srcfile.suffix.lower() == ".docx" else blocks_from_markdown(srcfile.read_text(encoding="utf-8-sig"))
        work = out / re.sub(r"[^\w-]+", "_", op["title"]).strip("_")
        work.mkdir(exist_ok=True)
        if op.get("bib"):
            (work / Path(op["bib"]).name).write_bytes(Path(op["bib"]).read_bytes())
        src = work / "main.tex"
        src.write_text(tex_document(blocks, op["title"], op["author"], op["kind"], op.get("bib")), encoding="utf-8")
        title, headings = op["title"], [v[1] for k, v in blocks if k == "heading"]
    ok, problems, log = compile_tex(src, work)
    pdf = work / (src.stem + ".pdf")
    checks = check(pdf, title, [re.sub(r"\\\w+\{([^}]*)\}", r"\1", h) for h in headings], problems)
    bad = [w for w, good in checks if not good]
    ctx.setdefault("memo", {})["latex"] = {"tex": str(src), "pdf": str(pdf)}
    return (f"LaTeX {'compiled' if op['op'] == 'compile' else ('thesis' if op.get('kind') == 'thesis' else 'paper') + ' made'}: {pdf} (source {src.name}" +
            (", opens in Overleaf, TeXstudio or any LaTeX editor" if op["op"] == "make" else "") + "). " +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + " | ".join(problems[:4])))
