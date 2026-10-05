"""Google Workspace by its APIs (the hub's Google sign-in: 'hub.py connect google'): Google Docs written (a title, headings
and paragraphs), Google Slides decks built (a title slide and a slide per point list), and Google Forms quizzes made
from plain words (multiple choice, true/false and short answers, each with its right answer and a point, so Forms marks
them). Each is read back from Google and its link given; all are private to you until you share them.

  "google doc 'Meeting notes': # Decisions\\nPrices stay the same.\\n# Next steps\\nCall Haier on Monday."
  "google slides 'Sales update': Q3: sales up 12%; 40 new customers | Q4 plan: open a second shop; hire two people"
  "google form quiz 'Science test': 1. What is H2O? a) Water* b) Salt 2. The sun is a star. True* 3. Capital of Pakistan? answer: Islamabad"
"""
import re

from ..hub.http import Api, HubError

NAME, LABEL = "gworkspace", "Google Docs, Slides and Forms (quizzes) through Google's APIs"
EXAMPLES = ["google doc 'Meeting notes': # Decisions\nPrices stay the same.", "google slides 'Sales update': Q3: sales up 12%; 40 new customers",
            "google form quiz 'Science test': 1. What is H2O? a) Water* b) Salt"]


class Client:
    def __init__(self, token=None, transport=None):
        self.transport, self._token = transport, token

    def api(self, base):
        tok = self._token
        if not tok:
            from ..hub.oauth import access_token
            tok = access_token("google")
        return Api(base, headers={"Authorization": f"Bearer {tok}"}, service="google", transport=self.transport)

    def call(self, base, method, path, body=None):
        try:
            return self.api(base).request(method, path, json_body=body, retries=0 if method == "POST" else 3)
        except HubError as e:
            if e.status == 403 and "scope" in str(e).lower():
                raise RuntimeError("Google needs your permission for Docs, Slides and Forms: run 'hub.py connect google' again") from e
            raise RuntimeError(f"Google: {e}") from e

    # ---------------------------------------------------------------- Docs
    def doc(self, title, text):
        d = self.call("https://docs.googleapis.com/v1", "POST", "documents", {"title": title})
        did = d["documentId"]
        reqs, idx, styles = [], 1, []
        for line in text.split("\n"):
            head = re.match(r"^\s*(#{1,3})\s+(.+)$", line)
            body = (head.group(2) if head else line) + "\n"
            reqs.append({"insertText": {"location": {"index": idx}, "text": body}})
            if head:
                styles.append({"updateParagraphStyle": {"range": {"startIndex": idx, "endIndex": idx + len(body)},
                                                        "paragraphStyle": {"namedStyleType": f"HEADING_{len(head.group(1))}"}, "fields": "namedStyleType"}})
            idx += len(body)
        if reqs:
            self.call("https://docs.googleapis.com/v1", "POST", f"documents/{did}:batchUpdate", {"requests": reqs + styles})
        back = self.call("https://docs.googleapis.com/v1", "GET", f"documents/{did}")
        got = "".join(r.get("textRun", {}).get("content", "") for el in back.get("body", {}).get("content", []) for r in (el.get("paragraph") or {}).get("elements", []))
        return did, f"https://docs.google.com/document/d/{did}/edit", got

    # ---------------------------------------------------------------- Slides
    def slides(self, title, sections):
        p = self.call("https://slides.googleapis.com/v1", "POST", "presentations", {"title": title})
        pid = p["presentationId"]
        reqs = []
        first = (p.get("slides") or [{}])[0]
        for el in first.get("pageElements", []):  # the deck's own title slide gets the title
            ph = ((el.get("shape") or {}).get("placeholder") or {}).get("type")
            if ph in ("CENTERED_TITLE", "TITLE"):
                reqs.append({"insertText": {"objectId": el["objectId"], "text": title}})
        for i, (head, points) in enumerate(sections, 1):
            sid, tid, bid = f"aipc_s{i}", f"aipc_t{i}", f"aipc_b{i}"
            reqs.append({"createSlide": {"objectId": sid, "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                                         "placeholderIdMappings": [{"layoutPlaceholder": {"type": "TITLE"}, "objectId": tid},
                                                                   {"layoutPlaceholder": {"type": "BODY"}, "objectId": bid}]}})
            reqs.append({"insertText": {"objectId": tid, "text": head}})
            if points:
                reqs.append({"insertText": {"objectId": bid, "text": "\n".join(points)}})
        self.call("https://slides.googleapis.com/v1", "POST", f"presentations/{pid}:batchUpdate", {"requests": reqs})
        back = self.call("https://slides.googleapis.com/v1", "GET", f"presentations/{pid}")
        return pid, f"https://docs.google.com/presentation/d/{pid}/edit", len(back.get("slides", []))

    # ---------------------------------------------------------------- Forms
    def quiz(self, title, questions):
        f = self.call("https://forms.googleapis.com/v1", "POST", "forms", {"info": {"title": title, "documentTitle": title}})
        fid = f["formId"]
        reqs = [{"updateSettings": {"settings": {"quizSettings": {"isQuiz": True}}, "updateMask": "quizSettings.isQuiz"}}]
        for i, q in enumerate(questions):
            right = [o for o, r in q["options"] if r] if q["kind"] != "short" else [q["answer"]]
            question = {"required": True, "grading": {"pointValue": 1, "correctAnswers": {"answers": [{"value": a} for a in right]}}}
            if q["kind"] == "short":
                question["textQuestion"] = {"paragraph": False}
            else:
                question["choiceQuestion"] = {"type": "CHECKBOX" if len(right) > 1 else "RADIO", "options": [{"value": o} for o, _ in q["options"]]}
            reqs.append({"createItem": {"item": {"title": q["q"], "questionItem": {"question": question}}, "location": {"index": i}}})
        self.call("https://forms.googleapis.com/v1", "POST", f"forms/{fid}:batchUpdate", {"requests": reqs})
        back = self.call("https://forms.googleapis.com/v1", "GET", f"forms/{fid}")
        return fid, back.get("responderUri") or f"https://docs.google.com/forms/d/{fid}/viewform", len(back.get("items", [])), \
            (back.get("settings") or {}).get("quizSettings", {}).get("isQuiz")


def client(ctx):
    return (ctx.get("clients") or {}).get(NAME) or Client()


def parse(text, ctx):
    m = re.match(r"^\s*(?:make\s+(?:a\s+)?)?google\s+(doc|docs|document|slides|slide deck|presentation|form(?:\s+quiz)?|quiz)\s*(?:'([^']+)'|\"([^\"]+)\")?\s*:\s*(.+)$",
                 text, re.I | re.S)
    if not m:
        return None
    kind = m.group(1).lower()
    title = m.group(2) or m.group(3) or "Untitled"
    body = m.group(4).replace("\\n", "\n")
    if kind.startswith("doc"):
        return {"op": "doc", "title": title, "text": body}
    if kind.startswith(("slide", "presentation")):
        secs = []
        for part in body.split("|"):
            head, _, pts = part.partition(":")
            secs.append((head.strip(), [p.strip() for p in pts.split(";") if p.strip()]))
        return {"op": "slides", "title": title, "sections": secs}
    return {"op": "form", "title": title, "spec": body}


def run(op, ctx):
    c = client(ctx)
    if op["op"] == "doc":
        did, url, got = c.doc(op["title"], op["text"])
        lines = [re.sub(r"^\s*#{1,3}\s+", "", ln) for ln in op["text"].split("\n") if ln.strip()]
        ok = all(ln in got for ln in lines)
        return f"Google Doc '{op['title']}': {url} ({'read back: every line is there' if ok else 'NOT all there when read back'}; headings set)."
    if op["op"] == "slides":
        pid, url, n = c.slides(op["title"], op["sections"])
        return f"Google Slides '{op['title']}': {url} ({n} slides read back: a title slide and {n - 1} for your points)."
    from .quiz import read
    qs = read(op["spec"])
    if not qs:
        return "No questions found: number them '1. ...' and mark right answers with *."
    fid, url, n, is_quiz = c.quiz(op["title"], qs)
    return (f"Google Form quiz '{op['title']}': {n} questions read back" + (", marked as a quiz with each right answer worth a point" if is_quiz else "") +
            f". Send people this link: {url} (edit it at https://docs.google.com/forms/d/{fid}/edit).")
