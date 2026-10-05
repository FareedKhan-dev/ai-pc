"""Quizzes and tests from plain words: multiple choice (the right answer marked with *), true/false and short answers,
written as Moodle XML (imports into Moodle and most LMSs), GIFT, a Kahoot spreadsheet, and a printable Word paper with
a separate answer key. Checks: each file reads back with every question and the right answers.

  quiz 'Science test':
  1. What is H2O? a) Water* b) Salt c) Sugar d) Iron
  2. The sun is a star. True*
  3. Capital of Pakistan? answer: Islamabad
"""
import html
import re
from pathlib import Path

NAME, LABEL = "quiz", "Quizzes: Moodle XML, GIFT, Kahoot sheet, printable paper + answer key"
EXAMPLES = ["quiz 'Science test': 1. What is H2O? a) Water* b) Salt c) Sugar 2. The sun is a star. True* 3. Capital of Pakistan? answer: Islamabad"]


def read(spec):
    """'1. Q? a) x* b) y ...' -> [{"q", "kind": mc|tf|short, "options": [(text, right)], "answer"}]."""
    items = [x.strip() for x in re.split(r"(?:^|\s|\n)\d{1,3}[.)]\s+", "\n" + spec) if x.strip()]
    out = []
    for it in items:
        m = re.search(r"\banswer\s*:\s*(.+)$", it, re.I)
        if m:
            out.append({"q": it[:m.start()].strip(), "kind": "short", "answer": m.group(1).strip(" ."), "options": []})
            continue
        opts = re.split(r"\s+[a-hA-H][).]\s+", " " + it)
        if len(opts) > 2:
            q = opts[0].strip()
            options = [(o.strip(" *"), o.strip().endswith("*")) for o in opts[1:]]
            out.append({"q": q, "kind": "mc", "options": options, "answer": ", ".join(o for o, r in options if r)})
            continue
        m = re.search(r"\s(true|false)\s*\*?\s*(?:/\s*(?:true|false)\s*\*?)?\s*$", it, re.I)
        if m:
            tf = re.search(r"(true|false)\s*\*", it, re.I) or m
            out.append({"q": it[:m.start()].strip(), "kind": "tf", "answer": tf.group(1).title(), "options": [("True", tf.group(1).lower() == "true"),
                                                                                                            ("False", tf.group(1).lower() == "false")]})
    return [q for q in out if q["q"] and (q["kind"] != "mc" or any(r for _, r in q["options"]))]


def moodle(qs, title):
    x = ['<?xml version="1.0" encoding="UTF-8"?>', "<quiz>", f'<question type="category"><category><text>$course$/{html.escape(title)}</text></category></question>']
    for i, q in enumerate(qs, 1):
        name = f"<name><text>Q{i}</text></name><questiontext format=\"html\"><text><![CDATA[<p>{html.escape(q['q'])}</p>]]></text></questiontext>"
        if q["kind"] == "mc":
            right = sum(1 for _, r in q["options"] if r)
            x.append(f'<question type="multichoice">{name}<single>{"true" if right == 1 else "false"}</single><shuffleanswers>true</shuffleanswers>' +
                     "".join(f'<answer fraction="{(100 // right) if r else 0}"><text>{html.escape(o)}</text></answer>' for o, r in q["options"]) + "</question>")
        elif q["kind"] == "tf":
            x.append(f'<question type="truefalse">{name}<answer fraction="{100 if q["answer"] == "True" else 0}"><text>true</text></answer>'
                     f'<answer fraction="{100 if q["answer"] == "False" else 0}"><text>false</text></answer></question>')
        else:
            x.append(f'<question type="shortanswer">{name}<answer fraction="100"><text>{html.escape(q["answer"])}</text></answer></question>')
    return "\n".join(x + ["</quiz>"])


def gift(qs):
    def esc(s):
        return re.sub(r"([~=#{}:])", r"\\\1", s)
    out = []
    for i, q in enumerate(qs, 1):
        if q["kind"] == "mc":
            body = " ".join(("=" if r else "~") + esc(o) for o, r in q["options"])
        elif q["kind"] == "tf":
            body = "TRUE" if q["answer"] == "True" else "FALSE"
        else:
            body = "=" + esc(q["answer"])
        out.append(f"::Q{i}:: {esc(q['q'])} {{{body}}}")
    return "\n\n".join(out) + "\n"


def kahoot(qs, path):
    """Kahoot's spreadsheet import: question, up to 4 answers, time limit, correct answer number(s)."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Question - max 120 characters", "Answer 1 - max 75 characters", "Answer 2 - max 75 characters", "Answer 3 - max 75 characters",
               "Answer 4 - max 75 characters", "Time limit (sec) - 5, 10, 20, 30, 60, 90, 120, or 240 secs", "Correct answer(s) - choose at least one"])
    skipped = 0
    for q in qs:
        opts = q["options"] if q["kind"] != "short" else []
        if not opts or len(opts) > 4:
            skipped += 1
            continue
        ws.append([q["q"][:120]] + [o[:75] for o, _ in opts] + [""] * (4 - len(opts)) + [20, ",".join(str(i) for i, (_, r) in enumerate(opts, 1) if r)])
    wb.save(path)
    return skipped


def paper(qs, title, path, key=False):
    from docx import Document
    d = Document()
    d.add_heading(title + (" - Answer key" if key else ""), level=1)
    if not key:
        d.add_paragraph("Name: ____________________    Class: __________    Date: __________")
    for i, q in enumerate(qs, 1):
        d.add_paragraph(f"{i}. {q['q']}")
        if key:
            d.add_paragraph(f"Answer: {q['answer']}")
        elif q["kind"] == "mc":
            for letter, (o, _) in zip("abcdefgh", q["options"]):
                d.add_paragraph(f"    ({letter}) {o}")
        elif q["kind"] == "tf":
            d.add_paragraph("    True / False")
        else:
            d.add_paragraph("    ______________________________")
    d.save(path)


def make(spec, title, out):
    qs = read(spec)
    if not qs:
        raise ValueError("no questions found: number them '1. ...' and mark right answers with *")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w-]+", "_", title.strip()) or "quiz"
    files = {"moodle": out / f"{stem}.moodle.xml", "gift": out / f"{stem}.gift.txt", "kahoot": out / f"{stem}.kahoot.xlsx",
             "paper": out / f"{stem}.paper.docx", "key": out / f"{stem}.answer_key.docx"}
    files["moodle"].write_text(moodle(qs, title), encoding="utf-8")
    files["gift"].write_text(gift(qs), encoding="utf-8")
    skipped = kahoot(qs, files["kahoot"])
    paper(qs, title, files["paper"])
    paper(qs, title, files["key"], key=True)
    return qs, files, skipped


def check(qs, files):
    from lxml import etree
    from openpyxl import load_workbook
    from docx import Document
    out = []
    x = etree.parse(str(files["moodle"]))
    out.append(("Moodle XML reads back with every question", len(x.findall("question")) - 1 == len(qs)))
    out.append(("GIFT has every question", files["gift"].read_text(encoding="utf-8").count("::Q") == len(qs)))
    ws = load_workbook(files["kahoot"]).active
    out.append(("the Kahoot sheet's right answers are marked", all(r[6].value for r in ws.iter_rows(min_row=2))))
    key = "\n".join(p.text for p in Document(files["key"]).paragraphs)
    out.append(("the answer key has every answer", all(q["answer"] in key for q in qs)))
    return out


def parse(text, ctx):
    m = re.match(r"^\s*(?:make\s+(?:a\s+)?)?(?:quiz|test|exam|mcqs?)\s*(?:'([^']*)'|\"([^\"]*)\")?\s*:\s*(.+)$", text, re.I | re.S)
    if not m:
        return None
    return {"op": "quiz", "title": m.group(1) or m.group(2) or "Quiz", "spec": m.group(3)}


def run(op, ctx):
    qs, files, skipped = make(op["spec"], op["title"], Path(ctx["out"]) / "quizzes")
    checks = check(qs, files)
    bad = [w for w, ok in checks if not ok]
    kinds = {k: sum(1 for q in qs if q["kind"] == k) for k in ("mc", "tf", "short")}
    return (f"{len(qs)} questions ({kinds['mc']} multiple choice, {kinds['tf']} true/false, {kinds['short']} short answer): " +
            ", ".join(str(f) for f in files.values()) + (f". {skipped} short-answer question(s) left out of the Kahoot sheet (Kahoot needs choices)" if skipped else "") +
            (". Checked: " + ", ".join(w for w, _ in checks) if not bad else ". NOT right: " + ", ".join(bad)) + ".")
