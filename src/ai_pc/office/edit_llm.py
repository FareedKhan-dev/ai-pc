"""The cheap model's part in editing a document: new wording, never structure. Code decides where text goes and keeps
every style; the model only returns text (with **bold** / *italic* marks) or plan blocks.

  rewrite(planner, paragraphs, instruction, keep_count=True)   -> [paragraph md]   (one for one when keep_count)
  translate(planner, paragraphs, language)                     -> [paragraph md]   (one for one)
  write_blocks(planner, about, context, words)                 -> [plan blocks]    (a new section, a summary...)
  key_terms(planner, text, n)                                  -> [terms]
Long inputs go in batches, in parallel.
"""

from concurrent.futures import ThreadPoolExecutor

from ai_pc.core.util import parse_json

REWRITE_SYSTEM = """You edit paragraphs of a client's document. You get numbered paragraphs (with **bold** / *italic* marks) and an
instruction. Reply with ONE JSON object: {"paragraphs": ["...", ...]}.
- Follow the instruction exactly. Keep facts, names, numbers and meaning unless the instruction changes them.
- Keep each paragraph in its own language (an Urdu paragraph stays Urdu) unless the instruction is to translate.
- When a word count is given, keep to it closely.
- Keep **bold** / *italic* around terms that should stay emphasised. No headings, no numbering, no commentary.
- ONE_FOR_ONE: return exactly as many paragraphs as you got, in the same order (paragraph n becomes paragraph n).
- FREE: return as many paragraphs as the result needs (fewer when shortening, more when expanding)."""

BLOCKS_SYSTEM = """You write new content for a client's existing document (its outline is given, so you match its subject, tone and
terms and do not repeat what is there). Reply with ONE JSON object: {"blocks": [...]}. Block types:
  {"type": "heading", "text": "...", "level": 1|2}    (only when asked to add a section: its heading first)
  {"type": "paragraph", "text": "..."}   (**bold** / *italic* allowed)
  {"type": "bullets", "items": ["...", ...], "numbered": false}
  {"type": "table", "columns": [...], "rows": [[...]], "caption": "...", "total": false}
  {"type": "callout", "title": "...", "text": "..."}
Rules: specific and concrete; the client's own facts and numbers exactly; never invent statistics, studies, authors or
links (approximate figures labelled as approximate); no filler. Write in the document's language."""

TERMS_SYSTEM = """Pick the key terms of a text that a reader should see in bold: names of concepts, important figures, conclusions.
Reply with ONE JSON object: {"terms": ["...", ...]} using exact substrings of the text, at most N terms, no whole sentences."""


def _ask(planner, system, user, tier="docs"):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    r = planner._call(tier, msgs)
    d = parse_json(r.text)
    if d is None:
        r = planner._call(
            tier,
            msgs + [{"role": "assistant", "content": (r.text or "")[:3000]}, {"role": "user", "content": "Reply with the single JSON object only."}],
        )
        d = parse_json(r.text)
    return d if isinstance(d, dict) else {}


def rewrite(planner, paragraphs, instruction, keep_count=True, title="", context="", batch=14):
    """New wording for the paragraphs. keep_count: one paragraph back for each given (long lists go in parallel
    batches); else the whole set at once and any number back. A batch that comes back wrong keeps its old text."""
    paragraphs = list(paragraphs)
    if not paragraphs:
        return []

    def one(chunk):
        numbered = "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(chunk))
        mode = "ONE_FOR_ONE" if keep_count else "FREE"
        d = _ask(planner, REWRITE_SYSTEM, f"DOCUMENT: {title}\n{context}\nINSTRUCTION: {instruction}\nMODE: {mode}\nPARAGRAPHS:\n{numbered}")
        out = [str(x) for x in d.get("paragraphs") or [] if str(x).strip()]
        if keep_count and len(out) != len(chunk):
            return None
        return out or None

    if not keep_count:
        return one(paragraphs) or paragraphs
    chunks = [paragraphs[i : i + batch] for i in range(0, len(paragraphs), batch)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, chunks))
    out = []
    for chunk, res in zip(chunks, results):
        out += res if res else chunk
    return out


LANG = {
    "ur": "Urdu (in Urdu script)",
    "urdu": "Urdu (in Urdu script)",
    "en": "English",
    "english": "English",
    "ar": "Arabic",
    "arabic": "Arabic",
    "fr": "French",
    "french": "French",
    "de": "German",
    "german": "German",
    "es": "Spanish",
    "spanish": "Spanish",
    "zh": "Chinese",
    "chinese": "Chinese",
    "hi": "Hindi",
    "hindi": "Hindi",
    "pa": "Punjabi",
    "punjabi": "Punjabi",
    "tr": "Turkish",
    "turkish": "Turkish",
}


def translate(planner, paragraphs, language, title=""):
    lang = LANG.get(str(language).lower(), str(language))
    return rewrite(planner, paragraphs, f"Translate into {lang}. Natural, correct {lang}; keep names, numbers and **marks**.", True, title)


def write_blocks(planner, about, context, words=200, heading=None, kinds=None):
    want = (
        f"Write: {about}. About {int(words)} words."
        + (f" Start with a heading block '{heading}' (level 1)." if heading else " No heading block.")
        + (f" Use: {', '.join(kinds)}." if kinds else "")
    )
    d = _ask(planner, BLOCKS_SYSTEM, f"{context}\n\n{want}")
    return [b for b in d.get("blocks") or [] if isinstance(b, dict) and b.get("type")]


def key_terms(planner, text, n=8):
    d = _ask(planner, TERMS_SYSTEM.replace("N terms", f"{n} terms"), str(text)[:9000], tier="fast")
    return [str(t) for t in d.get("terms") or [] if str(t).strip() and str(t) in text][:n]
