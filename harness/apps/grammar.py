"""Grammar and spelling checks with LanguageTool's free public service (api.languagetool.org; the text is sent there,
so it is shown first and sent after a yes): a Word or text file checked paragraph by paragraph (within the free
service's limits: about 20 KB a request, 20 requests a minute), every issue listed with its suggestion, and a corrected
copy saved with the spelling and grammar fixes applied (style hints are listed, not applied). Paragraph styles are
kept; within a corrected paragraph, bold or italic words become plain.

  'check grammar in essay.docx'   'proofread letter.txt'
"""
import re
import time
import urllib.parse
from pathlib import Path

from ..hub.http import Api, HubError

NAME, LABEL = "grammar", "Grammar and spelling (LanguageTool): issues listed, a corrected copy"
EXAMPLES = ["check grammar in essay.docx", "proofread letter.txt"]
OUTWARD = {"check"}
URL = "https://api.languagetool.org/v2/check"
TRANSPORT = None  # tests put a fake here
APPLY = {"TYPOS", "GRAMMAR", "PUNCTUATION", "CASING", "CONFUSED_WORDS", "TYPOGRAPHY"}


def check_text(text, lang="en-US"):
    """[{offset, length, message, replacement, category}] for one piece of text."""
    try:
        r = Api(URL, service="languagetool", transport=TRANSPORT).request(
            "POST", URL, data=urllib.parse.urlencode({"text": text, "language": lang, "enabledOnly": "false"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
    except HubError as e:
        raise RuntimeError(f"LanguageTool: {e}") from e
    return [{"offset": m["offset"], "length": m["length"], "message": m["message"], "replacement": (m.get("replacements") or [{}])[0].get("value"),
             "category": ((m.get("rule") or {}).get("category") or {}).get("id", "")} for m in r.get("matches") or []]


def fix(text, issues):
    out = text
    for m in sorted(issues, key=lambda x: -x["offset"]):
        if m["replacement"] is not None and m["category"] in APPLY:
            out = out[:m["offset"]] + m["replacement"] + out[m["offset"] + m["length"]:]
    return out


def paragraphs(path):
    p = Path(path)
    if p.suffix.lower() == ".docx":
        from docx import Document
        return [x.text for x in Document(p).paragraphs]
    return p.read_text(encoding="utf-8", errors="replace").split("\n")


def parse(text, ctx):
    from .appschat import find_file
    if not re.search(r"\b(?:grammar|spelling|proof-?read|spell-?check)\b", text, re.I):
        return None
    f = find_file(text, ctx, {".docx", ".txt", ".md"})
    return {"op": "check", "file": f} if f else None


def preview(op, ctx):
    words = sum(len(x.split()) for x in paragraphs(op["file"]))
    return f"Ready to check {Path(op['file']).name} ({words} words): its text goes to LanguageTool's free public server (api.languagetool.org) to be checked."


def run(op, ctx):
    if not op.get("confirmed"):
        return preview(op, ctx)
    paras = paragraphs(op["file"])
    found, fixed = [], []
    batch, last = [], 0.0
    for i, para in enumerate(paras):
        if not para.strip():
            fixed.append(para)
            continue
        wait = 3.1 - (time.time() - last)  # the free service: 20 requests a minute
        if wait > 0 and TRANSPORT is None and last:
            time.sleep(wait)
        last = time.time()
        issues = check_text(para[:19000])
        found += [(i, m) for m in issues]
        fixed.append(fix(para, issues))
    p = Path(op["file"])
    out = Path(ctx["out"]) / "grammar"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{p.stem}.corrected{p.suffix}"
    if p.suffix.lower() == ".docx":
        from docx import Document
        d = Document(p)
        for para, new in zip(d.paragraphs, fixed):
            if para.text != new and para.runs:
                para.runs[0].text = new
                for r in para.runs[1:]:
                    r.text = ""
        d.save(dest)
    else:
        dest.write_text("\n".join(fixed), encoding="utf-8")
    applied = sum(1 for _, m in found if m["replacement"] is not None and m["category"] in APPLY)
    listed = "\n".join(f"- paragraph {i + 1}: {m['message']}" + (f" -> '{m['replacement']}'" if m["replacement"] is not None else "") for i, m in found[:20])
    return (f"{len(found)} issue(s) found, {applied} fixed in {dest}" + (f"; {len(found) - applied} style hint(s) listed, not applied" if len(found) > applied else "") +
            (f":\n{listed}" if found else ". No issues found."))
