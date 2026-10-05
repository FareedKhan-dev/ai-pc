"""A conversation about an Excel workbook (the Word chat's machinery: one version per message, undo / redo / go to vN /
versions / compare / export). Every edit is done by Excel itself in the background worker and checked against Python;
every question about the data is answered by computing it (the model may read an unusual question into a query, never
do the arithmetic).

  c = BookChat.start("sales.xlsx")
  c.say("clean up the data, then add a column Amount = Qty times Unit Price and a total row")
  c.say("which city sold the most?")
  c.say("make a pivot of amount by city and month, and highlight orders over 5 lakh in green")
"""
import datetime as _dt
import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path

from ai_pc.core.util import parse_json
from ai_pc.office import book_parse as BP
from ai_pc.office import render as RN
from ai_pc.office import xlsx_map as XM
from ai_pc.office.docchat import CHATS, POLITE, QUESTION, DocChat
from ai_pc.office.xlsx_com import OPS as XOPS
from ai_pc.office.xlsx_com import _match, _say

BOOK_SYSTEM = """You turn a client's request about their Excel workbook into operations for a program that drives Excel. Reply with
ONE JSON object: {"ops": [...], "ask": "<short question back, only if it cannot be done as asked>", "answer": "<only if it was a question>"}.
Use sheet and column names exactly as the WORKBOOK shows them. "sheet" may be left out for the main table. Operations:
 {"op": "add_column", "name": "...", "formula": "<Excel formula with [Column] names: [Qty]*[Unit Price], IF([Percentage]>=0.5,\\"Pass\\",\\"Fail\\"), ROUND([A]/[B],2)>", "after": "<column>"}
 {"op": "add_column", "name": "...", "lookup": {"sheet": "<other sheet>", "key": "<column here>", "match": "<column there>", "value": "<column there>"}}
 {"op": "add_column", "name": "...", "running": "<column>"} | {"op": "add_column", "name": "Rank", "rank": "<column>", "desc": true} | {"op": "add_column", "name": "...", "share": "<column>"}
 {"op": "delete_column", "col": C}  {"op": "rename_column", "col": C, "name": "..."}  {"op": "move_column", "col": C, "after": C2}  {"op": "hide", "cols": [C], "show": false}
 {"op": "sort", "by": [{"col": C, "desc": true}]}   {"op": "filter", "col": C, "cmp": "=|<>|>|<|>=|<=|contains|between|in|top", "value": V, "value2": V2}   {"op": "filter", "clear": true}
 {"op": "conditional", "col": C, "rule": ">|<|>=|<=|=|between|top|bottom|duplicates|above|below|contains|blank|bars|scale", "value": V, "color": "red|green|yellow", "rows": true}
 {"op": "conditional", "formula": "<condition with [Column] names, e.g. AND([Status]<>\\"Paid\\",[Due Date]<TODAY())>", "color": "red"}   {"op": "clear_highlights", "col": C}
 {"op": "total_row", "fn": "sum|average|count|max|min", "cols": [C]}   {"op": "remove_duplicates", "cols": [C]}   {"op": "delete_rows", "blank": true}
 {"op": "delete_rows", "where": {"col": C, "op": "=|<>|>|<|>=|<=|contains", "value": V}}   {"op": "add_row", "values": {"<column>": V}}
 {"op": "summary", "by": C, "values": [C], "fn": "sum|average|count", "period": "month|quarter|year", "chart": true}   {"op": "pivot", "rows": [C], "columns": [C], "values": [C], "fn": "sum"}
 {"op": "chart", "type": "column|bar|line|pie", "x": C, "y": [C]}   {"op": "number_format", "cols": [C], "format": "rs|pkr|usd|percent|percent1|thousands|decimals2|date"}
 {"op": "freeze", "rows": 1, "cols": 0}   {"op": "style", "target": "header|totals|<column>", "set": {"bold": true, "fill": "<colour>", "color": "<colour>"}}
 {"op": "clean_text", "cols": [C], "how": "trim|proper|upper|lower"}   {"op": "map_values", "col": C, "map": {"<written form>": "<one spelling>"}}   {"op": "map_values", "col": C, "auto": true}
 {"op": "to_number", "cols": [C]}   {"op": "to_date", "col": C}   {"op": "fill_blanks", "col": C, "how": "above|value", "value": V}   {"op": "replace", "find": "...", "with": "...", "col": C}
 {"op": "round", "col": C, "digits": 2}   {"op": "validation", "col": C, "list": [...]}   {"op": "split_column", "col": C, "names": [...], "sep": ","}
 {"op": "rename_sheet", "sheet": S, "name": "..."}   {"op": "add_sheet", "name": "..."}   {"op": "delete_sheet", "sheet": S}   {"op": "autofit"}
Dates as "YYYY-MM-DD"; percentages as fractions (50% = 0.5); money as plain numbers. Do only what was asked, with the fewest operations."""

QUERY_SYSTEM = """You turn a client's question about their spreadsheet into a query that a program computes exactly. Reply with ONE JSON object:
{"query": {"sheet": "<sheet>", "fn": "sum|average|count|max|min|distinct|argmax|argmin|top", "col": "<number column for sum/average/max/min/argmax/top, the column for distinct>",
 "where": [{"col": "<column>", "op": "=|<>|>|<|>=|<=|contains|between", "value": V, "value2": V2}], "by": "<column to group by, or omit>", "label": "<column that names a row, for argmax/top>",
 "n": 5, "desc": true}}
or {"answer": "<1-3 sentences>"} only when the question is not a calculation (what the sheet is for, what a column means).
Use column names exactly as the WORKBOOK shows them; dates as "YYYY-MM-DD"; percentages as fractions."""


def _date(v):
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", v):
        try:
            return _dt.datetime.fromisoformat(v[:19])
        except ValueError:
            return v
    return v


def _fmt(v, col=None):
    if v is None:
        return "-"
    if isinstance(v, float) and col is not None and col.get("kind") == "percent":
        return f"{v:.1%}"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        s = _say(float(v))
        if col is not None and re.search(r"Rs|PKR|₨", str(col.get("fmt") or "")):
            return "Rs " + s
        if col is not None and "$" in str(col.get("fmt") or ""):
            return "$" + s
        return s
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%d %b %Y")
    return str(v)


def _rows(s, where, product=None):
    t = s["table"]
    out = []
    for r in t["rows"]:
        if all(v in (None, "") for v in r):
            continue
        rec = {c["name"]: (_date(r[c["idx"] - t["c0"]]) if c["kind"] == "date" else r[c["idx"] - t["c0"]]) for c in t["cols"]}
        if product:  # money a table holds as quantity x unit price
            a, b = rec.get(product[0]), rec.get(product[1])
            rec[f"{product[0]} x {product[1]}"] = float(a) * float(b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        ok = True
        for w in where or []:
            col = XM.col(None, s, w.get("col"))
            if col is None:
                continue
            ok = ok and _match(rec.get(col["name"]), str(w.get("op") or "="), w.get("value"), w.get("value2"))
        if ok:
            out.append(rec)
    return out


def _agg(fn, xs):
    xs = [float(x) for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if fn == "count":
        return len(xs)
    if not xs:
        return None
    return sum(xs) if fn == "sum" else sum(xs) / len(xs) if fn == "average" else max(xs) if fn == "max" else min(xs)


def _where_text(where):
    if not where:
        return ""
    bits = []
    for w in where:
        v = w.get("value")
        if w.get("op") == "between" and isinstance(v, str) and re.match(r"\d{4}-\d{2}-01", v) and str(w.get("value2", "")).startswith(v[:7]):
            bits.append(f"in {_dt.datetime.fromisoformat(v).strftime('%B %Y')}")
        elif w.get("op") == "between":
            bits.append(f"{w['col']} between {_fmt(_date(v))} and {_fmt(_date(w.get('value2')))}")
        elif w.get("op") == "in":
            bits.append(f"{w['col']} in {', '.join(map(str, v))}")
        else:
            bits.append(f"{w['col']} {'' if w.get('op') == '=' else w.get('op') + ' '}{_fmt(_date(v))}")
    return " (" + "; ".join(bits) + ")"


def run_query(q, m, errors=None):
    """A query answered from the workbook's values (as Excel last computed them)."""
    ans = _run_query(q, m, errors)
    if q and q.get("product"):  # money a table holds as quantity x price: say so in words
        a, b = q["product"]
        ans = ans.replace(f"{a} x {b}", f"value ({a} x {b})")
    return ans


def _run_query(q, m, errors=None):
    fn = q.get("fn")
    if fn == "sheets":
        return "Sheets: " + "; ".join(f"{s['name']}" + (f" (table of {len(s['table']['rows'])} rows)" if s["table"] and s["kind"] != "pivot" else " (pivot table)" if s["kind"] == "pivot"
                                                        else " (summary)" if s["pairs"] else "") for s in m["sheets"]) + "."
    s = XM.sheet(m, q.get("sheet")) or XM.sheet(m)
    if not s or not s.get("table"):
        return "That sheet holds no table."
    t = s["table"]
    if fn == "columns":
        return f"{s['name']} has {len(t['cols'])} columns: " + ", ".join(f"{c['letter']} {c['name']}" + (" (formula)" if c["formula"] else "") for c in t["cols"]) + "."
    if fn == "errors":
        es = [e for e in errors or [] if e.get("sheet") == s["name"]] if errors is not None else []
        return f"No Excel errors on {s['name']}." if not es else f"{len(es)} Excel error(s) on {s['name']}: " + ", ".join(f"{e['error']} at {XM.letter(e['col'])}{e['row']}" for e in es[:6]) + "."
    if fn == "formula":
        c = XM.col(None, s, q.get("col"))
        return f"{c['name']} is typed in, not calculated." if c and not c["formula"] else (f"{c['name']} is calculated as {c['formula']} (row {t['first']}; the same down the rows)." if c else "No such column.")
    if fn == "blanks":
        bl = [(c["name"], c["blank"]) for c in t["cols"] if c["blank"]]
        return "No blank cells in the table." if not bl else "Blank cells: " + ", ".join(f"{n} {k}" for n, k in bl) + "."
    rows = _rows(s, q.get("where"), q.get("product"))
    wt = _where_text(q.get("where"))
    if fn == "duplicates":
        c = XM.col(None, s, q.get("col")) if q.get("col") else None
        keys = [str(r[c["name"]]).strip().lower() if c else tuple(str(v).strip().lower() for v in r.values()) for r in rows]
        cnt = Counter(keys)
        d = sum(n - 1 for n in cnt.values() if n > 1)
        return f"No duplicates{' in ' + c['name'] if c else ' (whole rows)'}." if not d else f"{d} duplicate(s){' in ' + c['name'] if c else ' (whole rows)'}: " + \
            ", ".join(str(k) for k, n in cnt.items() if n > 1)[:200] + "."
    if fn == "count" and not q.get("by"):
        return f"{len(rows)} row(s){wt}."
    label = XM.col(None, s, q.get("label")) if q.get("label") else next((c for c in t["cols"] if c["kind"] == "text"), t["cols"][0])
    by = XM.col(None, s, q.get("by")) if q.get("by") else None
    col = XM.col(None, s, q.get("col")) if q.get("col") else None
    if q.get("product"):
        pc = XM.col(None, s, q["product"][1])
        col = {"name": f"{q['product'][0]} x {q['product'][1]}", "kind": "money", "fmt": (pc or {}).get("fmt") or ""}
    if fn in ("argmax", "argmin") and label and col and not by:
        keys = [r[label["name"]] for r in rows]
        if len(set(map(str, keys))) < len(keys):  # a customer with several orders: their total
            by = label
    if by:
        groups = {}
        for r in rows:
            k = r[by["name"]]
            if by["kind"] == "date" and isinstance(k, _dt.datetime):
                k = k.strftime("%b %Y")
            groups.setdefault(k if k not in (None, "") else "(blank)", []).append(r)
        f2 = {"argmax": "sum", "argmin": "sum", "top": "sum"}.get(fn, fn)
        vals = {k: (len(v) if f2 == "count" else _agg(f2, [x[col["name"]] for x in v] if col else [])) for k, v in groups.items()}
        vals = {k: v for k, v in vals.items() if v is not None}
        if not vals:
            return "Nothing to count there."
        order = sorted(vals.items(), key=lambda kv: -kv[1])
        what = "rows" if f2 == "count" else f"{f2} of {col['name']}"
        if fn in ("argmax", "argmin"):
            if fn == "argmin":
                order = order[::-1]
            k, v = order[0]
            return f"{k}: {_fmt(v, col)} ({what}{wt}); " + ", ".join(f"{a} {_fmt(b, col)}" for a, b in order[:6]) + "."
        if fn == "top":
            n = int(q.get("n") or 5)
            pick = order[:n] if q.get("desc", True) else order[::-1][:n]
            return f"{'Top' if q.get('desc', True) else 'Bottom'} {len(pick)} by {what}{wt}: " + ", ".join(f"{a} {_fmt(b, col)}" for a, b in pick) + "."
        return f"{what.capitalize()} by {by['name']}{wt}: " + ", ".join(f"{a} {_fmt(b, col if f2 != 'count' else None)}" for a, b in order[:12]) + \
            (f" (and {len(order) - 12} more)" if len(order) > 12 else "") + "."
    if fn == "distinct" and col:
        vs = sorted({str(r[col["name"]]) for r in rows if r[col["name"]] not in (None, "")})
        return f"{len(vs)} different {col['name']} value(s){wt}: " + ", ".join(vs[:12]) + ("..." if len(vs) > 12 else "") + "."
    if not col:
        return "Which column? " + ", ".join(c["name"] for c in t["cols"] if c["kind"] in ("number", "money", "percent")) + "."
    if fn in ("argmax", "argmin", "top"):
        nums = [r for r in rows if isinstance(r[col["name"]], (int, float))]
        if not nums:
            return f"No numbers in {col['name']}{wt}."
        nums.sort(key=lambda r: float(r[col["name"]]), reverse=(fn != "argmin" and q.get("desc", True)))
        if fn == "top":
            n = int(q.get("n") or 5)
            return f"{'Top' if q.get('desc', True) else 'Bottom'} {min(n, len(nums))} by {col['name']}{wt}: " + \
                ", ".join(f"{r[label['name']]} {_fmt(r[col['name']], col)}" for r in nums[:n]) + "."
        r = nums[0]
        tie = [x for x in nums if float(x[col["name"]]) == float(r[col["name"]])]
        return f"{', '.join(str(x[label['name']]) for x in tie)}: {col['name']} {_fmt(r[col['name']], col)}{' (a tie)' if len(tie) > 1 else ''}{wt}."
    v = _agg(fn, [r[col["name"]] for r in rows])
    return f"{fn.capitalize() if fn != 'sum' else 'Total'} {col['name']}{wt}: {_fmt(v, col)} ({len(rows)} row(s))."


class BookChat(DocChat):
    @classmethod
    def start(cls, path, chats_dir=None, **kw):
        src = Path(path)
        if src.suffix.lower() not in (".xlsx", ".xlsm"):
            raise ValueError("BookChat edits Excel workbooks (.xlsx)")
        cid = f"book_{re.sub(r'[^a-z0-9]+', '', src.stem.lower())[:16] or 'book'}_{time.strftime('%H%M%S')}"
        folder = Path(chats_dir or CHATS) / cid
        folder.mkdir(parents=True, exist_ok=True)
        v0 = folder / f"v0{src.suffix.lower()}"
        shutil.copy(src, v0)
        state = {"id": cid, "kind": "xlsx", "base": str(src), "folder": str(folder), "cur": 0, "turns": [], "focus": None, "pending": None,
                 "versions": [{"v": 0, "parent": None, "file": str(v0), "said": None, "done": ["the original file"], "failed": [], "checks": [],
                               "errors": [], "pages": None, "pdf": None}]}
        kw.setdefault("render", True)
        c = cls(state, **kw)
        c._render(0)
        c.save()
        return c

    def _job(self, job, timeout=300):
        if self.server is not None:
            return self.server.run(job, timeout=timeout)
        return RN.office(job)

    def _render(self, v):
        """Excel opens the version, recalculates and saves it (so every formula's value is in the file for the map), and
        lists the cells that show an error."""
        ver = self.state["versions"][v]
        r = self._job({"app": "excel", "src": ver["file"], "save": True})
        ver["errors"], ver["render_ok"], ver["charts"] = r.get("errors") or [], bool(r.get("ok")), r.get("charts")
        self._maps.pop(v, None)
        return r

    def map(self, v=None):
        v = self.state["cur"] if v is None else v
        if v not in self._maps:
            self._maps[v] = XM.book_map(self.path(v))
        return self._maps[v]

    def _clause(self, c, raw, focus, carry=False):
        kind, payload = self._meta(c, raw)
        if kind:
            return kind, payload
        low = c.lower()
        if QUESTION.search(low) and not POLITE.match(raw) and not re.match(r"^\s*(?:show|list)\s+(?:me\s+)?only\b", low):
            return "question", self.answer(c)
        r = BP.parse_book(c, self.map(), focus, raw=raw, carry=carry)
        if r.get("ops"):
            return "change", r
        if r.get("ask"):
            return "ask", {"question": r["ask"], "template": None}
        return "unknown", c

    # ------------------------------------------------------------------ the model, for what the rules cannot read
    def _valid(self, op, m):
        """An operation the model wrote, checked against the workbook: its sheet and every column it names exist."""
        if op.get("op") not in XOPS:
            return f"no operation '{op.get('op')}'"
        s = XM.sheet(m, op.get("sheet")) if op.get("sheet") else XM.sheet(m)
        if op.get("sheet") and s is None:
            return f"no sheet '{op.get('sheet')}'"
        if op["op"] in ("add_sheet", "rename_sheet", "delete_sheet", "autofit"):
            return None
        if not s or not s.get("table"):
            return "no table there"
        names = []
        for k in ("col", "by", "x", "after", "before", "running", "rank", "share"):
            if isinstance(op.get(k), str):
                names.append(op[k])
        for k in ("cols", "values", "y", "rows", "columns"):
            if isinstance(op.get(k), list):
                names += [x for x in op[k] if isinstance(x, str)]
        if isinstance(op.get("by"), list):
            names += [b.get("col") if isinstance(b, dict) else b for b in op["by"]]
        if isinstance(op.get("where"), dict):
            names.append(op["where"].get("col"))
        for f in (op.get("formula"),):
            if f:
                names += re.findall(r"\[([^\]]+)\]", str(f))
        if op["op"] == "add_column" and isinstance(op.get("lookup"), dict):
            names.append(op["lookup"].get("key"))
        bad = [n for n in names if n and XM.col(None, s, n) is None]
        return f"no column {', '.join(repr(b) for b in bad)}" if bad else None

    def _llm(self, clauses, message, done_ops, focus):
        if self.planner is None:
            return {"ask": "I could not read: " + "; ".join(f"'{c}'" for c in clauses) + ". Try e.g. 'sort by amount, highest first' or 'add a column Total = Qty times Price'."}
        self._turn["llm"] = True
        m = self.map()
        user = (f"WORKBOOK:\n{XM.outline(m, rows=3)}\nMAIN TABLE: {m['main']}\nLAST TALKED ABOUT: {json.dumps(focus) if focus else 'none'}\n"
                f"ALREADY DONE IN THIS MESSAGE: {json.dumps(done_ops)[:600] if done_ops else 'nothing'}\nWHOLE MESSAGE: {message}\nREQUESTS: {clauses}")
        try:
            r = self.planner._call("docs", [{"role": "system", "content": BOOK_SYSTEM}, {"role": "user", "content": user}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return {"ask": f"I could not work that out ({type(e).__name__})."}
        ops, notes = [], []
        for o in d.get("ops") or []:
            if not isinstance(o, dict):
                continue
            why = self._valid(o, m)
            if why:
                notes.append(f"{o.get('op')}: {why}")
            else:
                ops.append(o)
        ask = d.get("ask") if not ops else None
        if notes and not ops:
            ask = (ask + " " if ask else "") + "I could not use: " + "; ".join(notes) + "."
        return {"ops": ops, "answer": d.get("answer"), "ask": ask}

    def _llm_answer(self, q):
        if self.planner is None:
            return "Ask me e.g. 'what is the total amount by city?', 'how many orders are pending?' or 'who has the highest total?'."
        self._turn["llm"] = True
        m = self.map()
        try:
            r = self.planner._call("fast", [{"role": "system", "content": QUERY_SYSTEM},
                                            {"role": "user", "content": f"WORKBOOK:\n{XM.outline(m, rows=4)}\nMAIN TABLE: {m['main']}\nQUESTION: {q}"}])
            d = parse_json(r.text) or {}
        except Exception as e:  # noqa: BLE001
            return f"I could not answer that just now ({type(e).__name__})."
        if isinstance(d.get("query"), dict):
            qq = d["query"]
            s = XM.sheet(m, qq.get("sheet")) or XM.sheet(m)
            names = [qq.get(k) for k in ("col", "by", "label") if qq.get(k)] + [w.get("col") for w in qq.get("where") or [] if isinstance(w, dict)]
            if s and s.get("table") and all(XM.col(None, s, n) for n in names):
                return run_query(qq, m, self.version.get("errors"))
            return "I could not match that question to the columns: " + ", ".join(c["name"] for c in (s or {}).get("table", {}).get("cols", [])) + "."
        return str(d.get("answer") or "I could not find that in the workbook.")[:600]

    def answer(self, q):
        m = self.map()
        parts = [p.strip() for p in re.split(r"\?\s*|\s+and\s+(?=(?:what|which|who|how|is|are|does|do)\b)|,\s*(?=(?:what|which|who|how)\b)", q) if p and p.strip()]
        outs, last = [], None
        for p in parts or [q]:
            qq = BP.question_query(p, m, self.state.get("focus"))
            if qq and last and not qq.get("where") and re.search(r"\b(?:their|those|them|these|they|its)\b", p) and last.get("where"):
                qq["where"] = last["where"]  # "how many are pending and what is their total": the same rows
            last = qq or last
            a = run_query(qq, m, self.version.get("errors")) if qq else self._llm_answer(p)
            if a and a not in outs:
                outs.append(a)
        return " ".join(outs)

    # ------------------------------------------------------------------ an edit is a new version
    @staticmethod
    def _resheet(ops):
        renamed, out = {}, []
        for op in ops:
            op = dict(op)
            if op.get("sheet") in renamed and op.get("op") != "rename_sheet":
                op["sheet"] = renamed[op["sheet"]]
            if op.get("op") == "rename_sheet" and op.get("sheet") and op.get("name"):
                renamed[op["sheet"]] = op["name"]
            out.append(op)
        return out, renamed

    def say(self, message, files=()):
        self._renamed = {}
        reply = super().say(message, files)
        f = self.state.get("focus")
        if self._renamed and isinstance(f, dict) and f.get("sheet") in self._renamed:  # the sheet talked about has a new name now
            self.state["focus"] = dict(f, sheet=self._renamed[f["sheet"]])
            self.save()
        return reply

    def _change(self, ops, said, turn):
        ops, renamed = self._resheet(ops)
        self._renamed = dict(getattr(self, "_renamed", {}) or {}, **renamed)
        v0 = self.state["cur"]
        n = len(self.state["versions"])
        dst = self.folder / f"v{n}{self.path(v0).suffix}"
        shutil.copy(self.path(v0), dst)
        r = self._job({"app": "excel", "src": str(dst), "save": True, "ops": ops})
        if not r.get("ok"):
            dst.unlink(missing_ok=True)
            return f"Excel could not do that: {str(r.get('error'))[:200]}"
        res = r.get("ops") or []
        if any(x.get("dirty") for x in res):  # Excel stopped half way through an edit: do the others again on a clean copy
            keep = [op for op, x in zip(ops, res) if not x.get("dirty")]
            dirty = [x for x in res if x.get("dirty")]
            shutil.copy(self.path(v0), dst)
            r = self._job({"app": "excel", "src": str(dst), "save": True, "ops": keep}) if keep else {"ok": True, "ops": [], "errors": self.version.get("errors")}
            res = (r.get("ops") or []) + dirty
            ops = keep
        done = [x["done"] for x in res if not x.get("error")]
        failed = [f"{str(x.get('op')).replace('_', ' ')}: {x['error']}" for x in res if x.get("error")]
        checks = [{"op": str(x["op"]).replace("_", " "), "ok": bool(x.get("ok")), "what": x.get("what", "")} for x in res if not x.get("error")]
        if not done:
            dst.unlink(missing_ok=True)
            return "Nothing changed: " + "; ".join(failed or ["that is already how it is"]) + "."
        before = Counter((e["sheet"], e["error"]) for e in self.version.get("errors") or [])
        after = Counter((e["sheet"], e["error"]) for e in r.get("errors") or [])
        new = after - before
        checks.append({"op": "no new Excel errors", "ok": not new, "what": ", ".join(f"{k[1]} x{c} on {k[0]}" for k, c in new.items()) if new else "none"})
        self.state["versions"].append({"v": n, "parent": v0, "file": str(dst), "said": said, "done": done, "failed": failed, "checks": checks,
                                       "errors": r.get("errors") or [], "charts": r.get("charts"), "print_fit": r.get("print_fit") or [], "pages": None, "pdf": None})
        self.state["cur"] = n
        turn["ops"] += ops
        bad = [c for c in checks if not c["ok"]]
        msg = f"v{n}: " + "; ".join(done) + "."
        if r.get("print_fit"):
            msg += f" ({', '.join(r['print_fit'])} now print{'s' if len(r['print_fit']) == 1 else ''} landscape, one page wide.)"
        if failed:
            msg += " Couldn't: " + "; ".join(failed) + "."
        msg += f" Checked: {len(checks) - len(bad)}/{len(checks)} OK" + (" (" + "; ".join(f"{c['op']}: {c['what']}" for c in bad[:3]) + ")" if bad else "") + "."
        return msg

    # ------------------------------------------------------------------ versions side by side, export
    def compare(self, text=""):
        nums = [int(x) for x in re.findall(r"\bv(?:ersion)?\s*(\d+)", text)]
        a = nums[0] if nums else (0 if not re.search(r"\blast\b|\bprevious\b", text) else (self.version.get("parent") or 0))
        b = nums[1] if len(nums) > 1 else self.state["cur"]
        ma, mb = self.map(a), self.map(b)
        out = []
        na, nb = [s["name"] for s in ma["sheets"]], [s["name"] for s in mb["sheets"]]
        renamed = {}  # a sheet that went and one that came with mostly the same columns: one sheet, renamed
        for old in [x for x in na if x not in nb]:
            so = XM.sheet(ma, old)
            co = {c["name"] for c in (so.get("table") or {}).get("cols", [])}
            for new in [x for x in nb if x not in na and x not in renamed.values()]:
                sn = XM.sheet(mb, new)
                cn = {c["name"] for c in (sn.get("table") or {}).get("cols", [])}
                if co and cn and len(co & cn) >= 0.5 * len(co):
                    renamed[old] = new
                    break
        if renamed:
            out.append("renamed: " + ", ".join(f"{a} -> {b}" for a, b in renamed.items()))
        if set(nb) - set(na) - set(renamed.values()):
            out.append("new sheets: " + ", ".join(x for x in nb if x not in na and x not in renamed.values()))
        if set(na) - set(nb) - set(renamed):
            out.append("gone: " + ", ".join(x for x in na if x not in nb and x not in renamed))
        back = {b: a for a, b in renamed.items()}
        for sb in mb["sheets"]:
            sa = next((x for x in ma["sheets"] if x["name"] == back.get(sb["name"], sb["name"])), None)
            if not sa or not sa.get("table") or not sb.get("table") or sb["kind"] == "pivot":
                continue
            ca, cb = [c["name"] for c in sa["table"]["cols"]], [c["name"] for c in sb["table"]["cols"]]
            bits = []
            if [c for c in cb if c not in ca]:
                bits.append("columns added: " + ", ".join(c for c in cb if c not in ca))
            if [c for c in ca if c not in cb]:
                bits.append("columns removed: " + ", ".join(c for c in ca if c not in cb))
            ra, rb = XM.records(sa), XM.records(sb)
            if len(ra) != len(rb):
                bits.append(f"rows {len(ra)} -> {len(rb)}")
            key = sa["table"]["cols"][0]["name"]
            ka = {str(r.get(key)): r for r in ra}
            if key in cb and len(ka) == len(ra):
                changed = sum(1 for r in rb for c in ca if c in cb and str(r.get(key)) in ka and str(ka[str(r.get(key))].get(c)) != str(r.get(c)))
            else:
                changed = sum(1 for x, y in zip(ra, rb) for c in ca if c in cb and str(x.get(c)) != str(y.get(c)))
            if changed:
                bits.append(f"{changed} cell(s) changed")
            if sa.get("cf") != sb.get("cf"):
                bits.append(f"highlight rules {sa.get('cf')} -> {sb.get('cf')}")
            if sa.get("charts") != sb.get("charts"):
                bits.append(f"charts {sa.get('charts')} -> {sb.get('charts')}")
            if bits:
                out.append(f"{sb['name']}: " + ", ".join(bits))
        return f"v{a} -> v{b}: " + ("; ".join(out) if out else "no differences in the data") + "."

    def export(self):
        v = self.version
        name = Path(self.state["base"]).stem
        out = self.folder / f"{name}_v{v['v']}{Path(v['file']).suffix}"
        shutil.copy(v["file"], out)
        pdf = self.folder / f"{name}_v{v['v']}.pdf"
        tmp = self.folder / f"_pdf_v{v['v']}{Path(v['file']).suffix}"
        shutil.copy(v["file"], tmp)
        r = self._job({"app": "excel", "src": str(tmp), "pdf": str(pdf)})
        tmp.unlink(missing_ok=True)
        return f"Saved: {out}" + (f" and {pdf}" if r.get("ok") and pdf.exists() else " (the PDF could not be made)") + "."
