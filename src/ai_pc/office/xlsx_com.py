"""Edits on a real Excel workbook done by Excel itself, in the background worker (_com.py): Excel keeps everything a file
library would drop (charts, pivots, conditional formats, validation, defined names) and moves every reference when rows
and columns move. Each operation reads the table it works on again (find_table on what Excel reads), validates before it
changes anything (a refusal leaves the workbook as it was), and checks its own result against Python's: the values a new
column computes, a sort's order, the rows a filter shows, the cells a highlight colours (Excel's DisplayFormat), the totals
of a totals row, a summary's or a pivot's groups.

  run_ops(app, wb, ops) -> [{"op", "done", "ok", "what"} | {"op", "error", "dirty"?}]

Operations (sheet: a name, else the workbook's main table; col: a header name or a letter):
  add_column {name, formula "[Qty]*[Price]" | values [...] | running: col | rank: col, desc | share: col | series {start, step}
              | lookup {sheet, key, match, value}, after | before, format, total}
  delete_column {col, force}     rename_column {col, name}      move_column {col, after | before | to}     hide {cols | sheet_only, show}
  sort {by: [{col, desc}]}       filter {col, cmp, value | values, value2, clear}       freeze {rows, cols}
  number_format {cols, format}   conditional {col, rule, value, value2, color, rows, formula}     clear_highlights {col}
  total_row {fn, cols}           remove_duplicates {cols}       delete_rows {where: {col, op, value} | blank: true | rows}
  add_row {values: {col: v}}     clean_text {cols, how: trim|proper|upper|lower}      fill_blanks {col, how: above|value, value}
  to_number {cols}               to_date {col, order: dmy|mdy|ymd}     map_values {col, map {from: to} | auto: true}
  replace {find, with, col, whole}     rename_sheet {name}     add_sheet {name}     delete_sheet {force}
  chart {type, x, y: [...], title, place: below|beside|new_sheet}    summary {by, values, fn, name, chart, period: month|quarter|year}
  pivot {rows: [...], columns: [...], values: [...], fn, period, name}
  style {target: header|totals|table|<col>, set: {bold, italic, color, fill, font, size, wrap, align}}
  autofit {}     round {col, digits}     validation {col, list: [...]}     split_column {col, sep, names}
"""

import datetime as _dt
import re

from ai_pc.office.xlsx_map import calc, col_index, find_table, is_formula, is_num, letter, same, serial
from ai_pc.office.xlsx_map import col as find_col

XL_ERR = {
    -2146826281: "#DIV/0!",
    -2146826246: "#N/A",
    -2146826259: "#NAME?",
    -2146826288: "#NULL!",
    -2146826252: "#NUM!",
    -2146826265: "#REF!",
    -2146826273: "#VALUE!",
}
CHART_TYPES = {"column": 51, "bar": 57, "line": 65, "pie": 5, "doughnut": -4120, "area": 1, "scatter": -4169, "stacked": 52}
FN = {
    "sum": "SUM",
    "total": "SUM",
    "average": "AVERAGE",
    "avg": "AVERAGE",
    "mean": "AVERAGE",
    "count": "COUNT",
    "max": "MAX",
    "maximum": "MAX",
    "highest": "MAX",
    "min": "MIN",
    "minimum": "MIN",
    "lowest": "MIN",
    "median": "MEDIAN",
}
XL_FN = {"SUM": -4157, "AVERAGE": -4106, "COUNT": -4112, "MAX": -4136, "MIN": -4139}
FORMATS = {
    "money": "#,##0",
    "money2": "#,##0.00",
    "currency": "#,##0",
    "rs": '"Rs "#,##0',
    "rupees": '"Rs "#,##0',
    "pkr": '"PKR "#,##0',
    "usd": '"$"#,##0.00',
    "dollars": '"$"#,##0.00',
    "percent": "0%",
    "percent1": "0.0%",
    "percent2": "0.00%",
    "thousands": "#,##0",
    "comma": "#,##0",
    "decimals1": "0.0",
    "decimals2": "0.00",
    "integer": "0",
    "number": "#,##0.##",
    "date": "dd-mmm-yyyy",
    "short_date": "dd/mm/yyyy",
    "month": "mmm yyyy",
    "text": "@",
    "general": "General",
}
FILLS = {
    "green": "C6EFCE",
    "red": "FFC7CE",
    "yellow": "FFEB9C",
    "orange": "FCD5B4",
    "blue": "DDEBF7",
    "grey": "E7E6E6",
    "gray": "E7E6E6",
    "purple": "E4DFEC",
    "pink": "FADADD",
}
CELL_OP = {">": 5, "<": 6, ">=": 7, "<=": 8, "=": 3, "<>": 4, "between": 1}
PALETTE = ["1F4E79", "C55A11", "548235", "7030A0", "BF9000", "2E75B6", "7F7F7F", "9E480E"]


class OpError(Exception):
    pass


def bgr(hx):
    hx = str(hx).lstrip("#")
    return int(hx[0:2], 16) + int(hx[2:4], 16) * 256 + int(hx[4:6], 16) * 65536


def hexof(c):
    c = int(c)
    return f"{c & 255:02X}{(c >> 8) & 255:02X}{(c >> 16) & 255:02X}"


def _lum(hx):
    r, g, b = (int(hx[i : i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda x: x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _colour(v, fill=False):
    if not v:
        return None
    v = str(v).strip().lower()
    if re.fullmatch(r"#?[0-9a-f]{6}", v):
        return v.lstrip("#").upper()
    if fill and v in FILLS:
        return FILLS[v]
    from ai_pc.office.docx_ops import colour

    try:
        return colour(v)
    except Exception as e:  # noqa: BLE001
        from ai_pc.office.doc_parse import COLOURS

        if v in COLOURS:
            return COLOURS[v]
        raise OpError(str(e)) from None


def _say(v):
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if not v.is_integer() else f"{int(v):,}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%d %b %Y")
    return str(v)


def _py(v):
    if isinstance(v, _dt.datetime):
        return _dt.datetime(v.year, v.month, v.day, v.hour, v.minute, v.second)
    if isinstance(v, int) and not isinstance(v, bool) and v in XL_ERR:
        return XL_ERR[v]
    return v


def _rows(x):
    if not isinstance(x, tuple):
        return [[x]]
    return [list(r) if isinstance(r, tuple) else [r] for r in x]


def grid(ws):
    ur = ws.UsedRange
    r0, c0 = int(ur.Row), int(ur.Column)
    return _rows(ur.Formula), [[_py(v) for v in r] for r in _rows(ur.Value)], r0, c0


def table(ws, need=True):
    F, V, r0, c0 = grid(ws)
    t = find_table(F, V, None, r0, c0)
    if t:
        t = find_table(F, V, {c["idx"]: str(ws.Cells(t["first"], c["idx"]).NumberFormat) for c in t["cols"]}, r0, c0)
    if t is None and need:
        raise OpError(f"no table found on sheet '{ws.Name}'")
    if t:
        t["sheet"] = str(ws.Name)
        t["blank"] = [all(v is None or (isinstance(v, str) and not v.strip()) for v in r) for r in t["rows"]]
    return t


def get_ws(wb, name=None):
    if name:
        names = [str(w.Name) for w in wb.Worksheets]
        for n in names:
            if n.lower() == str(name).lower():
                return wb.Worksheets(n)
        for n in names:
            if n.lower().startswith(str(name).lower()) or str(name).lower() in n.lower():
                return wb.Worksheets(n)
        raise OpError(f"no sheet '{name}' (sheets: {', '.join(names)})")
    best, size = None, -1
    for w in wb.Worksheets:
        if int(w.PivotTables().Count):
            continue
        t = table(w, need=False)
        if t and len(t["rows"]) * len(t["cols"]) > size:
            best, size = w, len(t["rows"]) * len(t["cols"])
    return best or wb.Worksheets(1)


def get_col(t, name):
    c = find_col(None, {"table": t}, name)
    if c is None:
        raise OpError(f"no column '{name}' (columns: {', '.join(x['name'] for x in t['cols'])})")
    return c


def rng(ws, r1, c1, r2=None, c2=None):
    return ws.Range(ws.Cells(r1, c1), ws.Cells(r2 or r1, c2 or c1))


def col_range(ws, t, c):
    return rng(ws, t["first"], c["idx"], t["last"], c["idx"])


def col_values(ws, t, c):
    if t["last"] < t["first"]:
        return []
    return [_py(r[0]) for r in _rows(col_range(ws, t, c).Value)]


def records(t):
    return [{c["name"]: r[c["idx"] - t["c0"]] for c in t["cols"]} for r in t["rows"]]


def to_a1(expr, t, row):
    """'[Qty] * [Price]' -> '=C5*D5' for a row; Python-style operators turned into Excel's."""
    s = str(expr).strip()
    s = s[1:] if s.startswith("=") else s
    parts = re.split(r'("(?:[^"]|"")*")', s)
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(p)
            continue
        p = re.sub(r"\[([^\]]+)\]", lambda m: f"{get_col(t, m.group(1))['letter']}{row}", p)
        p = p.replace("==", "=").replace("!=", "<>").replace("**", "^")
        p = re.sub(r"\s*([-+*/^&=<>,()])\s*", r"\1", p)
        out.append(p)
    return "=" + "".join(out)


def _fmt_for(name, expr, t, values):
    if re.search(r"%|percent|share|ratio|rate\b|margin|growth|change", name, re.I) and "/" in str(expr or ""):
        return "0.0%"
    refs = [get_col(t, x) for x in re.findall(r"\[([^\]]+)\]", str(expr or ""))] if expr else []
    fm = {c["fmt"] for c in refs if c["fmt"] and c["fmt"] != "General"}
    nums = [v for v in values if is_num(v)]
    if values and all(isinstance(v, str) for v in values if v is not None):
        return "General"
    if len(fm) == 1 and re.fullmatch(r"[^*/]*", re.sub(r'"[^"]*"', "", str(expr or ""))):  # sums and differences keep their columns' format
        f = fm.pop()
        if "%" not in f or all(c["kind"] == "percent" for c in refs):
            return f
    if nums and all(float(v).is_integer() for v in nums):
        return "#,##0"
    if nums:
        return "#,##0.00"
    return "General"


def _print_setup(app, ws, landscape=True):
    try:
        app.PrintCommunication = False  # page setup talks to the printer on every property otherwise
    except Exception:  # noqa: BLE001
        pass
    try:
        ps = ws.PageSetup
        ps.Orientation = 2 if landscape else 1
        ps.Zoom = False
        ps.FitToPagesWide = 1
        ps.FitToPagesTall = False
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            app.PrintCommunication = True
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------------------------------------ columns
def op_add_column(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    name = str(op.get("name") or "").strip()
    if not name:
        raise OpError("the new column needs a name")
    if any(c["name"].lower() == name.lower() for c in t["cols"]):
        raise OpError(f"there is already a column '{name}'")
    recs, blank = records(t), t["blank"]
    expr, per_row, fmt, kind, tot_fn = op.get("formula"), None, None, "formula", None
    lk = op.get("lookup")
    if lk:  # a value looked up in another sheet's table by a key
        ws2 = get_ws(wb, lk.get("sheet"))
        t2 = table(ws2)
        key, match, val = get_col(t, lk.get("key")), get_col(t2, lk.get("match") or lk.get("key")), get_col(t2, lk.get("value") or name)
        sh = "'" + str(ws2.Name).replace("'", "''") + "'"
        expr = (
            f"IFERROR(INDEX({sh}!${val['letter']}${t2['first']}:${val['letter']}${t2['last']},MATCH([{key['name']}],"
            f'{sh}!${match["letter"]}${t2["first"]}:${match["letter"]}${t2["last"]},0)),"")'
        )
        found = {
            str(r[match["idx"] - t2["c0"]]).strip().lower(): r[val["idx"] - t2["c0"]]
            for r in t2["rows"]
            if r[match["idx"] - t2["c0"]] not in (None, "")
        }
        expect = [None if b else found.get(str(r[key["name"]]).strip().lower(), "") for r, b in zip(recs, blank)]
        missing = sum(1 for r, b in zip(recs, blank) if not b and str(r[key["name"]]).strip().lower() not in found)
        kind = f"looked up from '{ws2.Name}' by {key['name']}" + (f"; {missing} key(s) not found there (left blank)" if missing else "")
        fmt = str(ws2.Cells(t2["first"], val["idx"]).NumberFormat)
    elif op.get("running") or op.get("rank") or op.get("share"):
        src = get_col(t, op.get("running") or op.get("rank") or op.get("share"))
        vals = [r[src["name"]] for r in recs]
        nums = [float(v) for v in vals if is_num(v)]
        if not nums:
            raise OpError(f"{src['name']} has no numbers")
        if op.get("running"):
            acc, expect = 0.0, []
            for v, b in zip(vals, blank):
                acc += float(v) if is_num(v) else 0.0
                expect.append(None if b else acc)
            kind, fmt = f"running total of {src['name']}", src["fmt"] or "#,##0"

            def per_row(t1, row, n=src["name"]):
                L = get_col(t1, n)["letter"]
                return f"=SUM(${L}${t1['first']}:{L}{row})"
        elif op.get("rank"):
            desc = op.get("desc", True) is not False
            expect = [
                None if b or not is_num(v) else float(1 + sum(1 for x in nums if (x > float(v) if desc else x < float(v))))
                for v, b in zip(vals, blank)
            ]
            kind, fmt = f"rank by {src['name']} ({'highest' if desc else 'lowest'} = 1)", "0"

            def per_row(t1, row, n=src["name"], d=desc):
                L = get_col(t1, n)["letter"]
                return f'=IF(ISNUMBER({L}{row}),RANK.EQ({L}{row},${L}${t1["first"]}:${L}${t1["last"]},{0 if d else 1}),"")'
        else:
            total = sum(nums)
            expect = [None if b else (float(v) / total if is_num(v) and total else "") for v, b in zip(vals, blank)]
            kind, fmt, tot_fn = f"each row's share of the {src['name']} total", "0.0%", "SUM"

            def per_row(t1, row, n=src["name"]):
                L = get_col(t1, n)["letter"]
                return f'=IFERROR({L}{row}/SUM(${L}${t1["first"]}:${L}${t1["last"]}),"")'
    elif op.get("series"):
        sr = op["series"] if isinstance(op["series"], dict) else {}
        start, step = float(sr.get("start", 1)), float(sr.get("step", 1))
        expect, k = [], 0
        for b in blank:
            expect.append(None if b else start + step * k)
            k += 0 if b else 1
        kind, fmt = "numbered", "0"
    elif expr:
        for x in re.findall(r"\[([^\]]+)\]", str(expr)):
            get_col(t, x)  # a missing column is said before anything changes
        expect = [None if b else calc(expr, r) for r, b in zip(recs, blank)]
    elif op.get("values") is not None:
        vals = list(op["values"])
        expect = (vals + [None] * len(recs))[: len(recs)]
        kind = "values"
    else:
        expect = [None] * len(recs)
        kind = "empty"
    if expr and per_row is None:

        def per_row(t1, row, e=expr):
            return to_a1(e, t1, row)

    if op.get("after"):
        k = get_col(t, op["after"])["idx"] + 1
    elif op.get("before"):
        k = get_col(t, op["before"])["idx"]
    else:
        k = t["c1"] + 1
    filt = bool(ws.AutoFilterMode) and not bool(ws.FilterMode)
    rng(ws, 1, k, max(t["last"], t["total"] or 0) + 1, k).EntireColumn.Insert()  # the column on the left lends its formats
    t1 = table(ws)
    ws.Cells(t1["header"], k).Value = name
    sample = None
    if t1["rows"]:
        r = rng(ws, t1["first"], k, t1["last"], k)
        r.NumberFormat = "General"  # a text-formatted neighbour would make the formulas plain text
        if per_row is not None:
            r.Formula = tuple(("" if b else per_row(t1, t1["first"] + i),) for i, b in enumerate(t1["blank"]))
            sample = per_row(t1, t1["first"])
        elif kind in ("values", "numbered"):
            r.Value = tuple(("" if v is None else v,) for v in expect)
        else:
            r.ClearContents()
        fmt = (
            FORMATS.get(str(op.get("format") or "").lower())
            or op.get("format")
            or fmt
            or _fmt_for(name, expr, t, [v for v in expect if v is not None])
        )
        r.NumberFormat = fmt
    tot = ""
    no_total = bool(
        re.search(r"TODAY\(|NOW\(", str(expr or ""), re.I) or re.search(r"\bdays?\b|\bage\b|rank|rate\b|price|\bid\b|year|month", name, re.I)
    )
    if t1["total"] and per_row is not None and op.get("total") is not False and any(is_num(x) for x in expect) and (not no_total or op.get("total")):
        fn = FN.get(str(op.get("total") or "").lower()) or tot_fn
        if not fn and not (op.get("running") or op.get("rank")):
            have = [re.match(r"=\s*([A-Z]+)\(", str(c["total"] or "")) for c in t1["cols"] if c["idx"] != k]
            fns = [h.group(1) for h in have if h]
            fn = "AVERAGE" if "%" in str(fmt) else (max(set(fns), key=fns.count) if fns else "SUM")
        if fn:
            L = letter(k)
            ws.Cells(t1["total"], k).Formula = f"={fn}({L}{t1['first']}:{L}{t1['last']})"
            ws.Cells(t1["total"], k).NumberFormat = fmt or ws.Cells(t1["first"], k).NumberFormat
            tot = f"; its {fn.lower()} in the {str(t1['total_label'] or 'totals').lower()} row"
    if filt:  # a filter over the whole table grows with it
        ws.AutoFilterMode = False
        rng(ws, t1["header"], t1["c0"], t1["last"], t1["c1"]).AutoFilter()
    ws.Columns(k).AutoFit()
    if float(ws.Columns(k).ColumnWidth) < 9:
        ws.Columns(k).ColumnWidth = 9
    t2 = table(ws)
    got = col_values(ws, t2, get_col(t2, name))
    known = [(g, e) for g, e in zip(got, expect) if e is not None]
    bad = [(g, e) for g, e in known if not same(g, e)]
    errs = [g for g in got if isinstance(g, str) and g in XL_ERR.values()]
    what = f"{len(known) - len(bad)}/{len(known)} values match Python" if known else f"{len(got)} cells"
    if errs:
        what += f"; {len(errs)} Excel error(s) ({errs[0]})"
    say = f" ({sample} down the rows)" if sample else ""
    return {
        "done": f"column '{name}' added at {letter(k)}" + (f", {kind}" if kind not in ("formula", "values", "empty") else "") + say + tot,
        "ok": not bad and (not errs or all(e == "#DIV/0!" for e in errs) and any(x == "#DIV/0!" for x in expect)),
        "what": what + (f"; e.g. Excel {bad[0][0]} vs Python {bad[0][1]}" if bad else ""),
    }


REF = re.compile(r"(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?(\$?)([A-Z]{1,3})(\$?)(\d+)(?::(\$?)([A-Z]{1,3})(\$?)(\d+))?(?![\w(])")
COLREF = re.compile(r"(?:(?:'((?:[^']|'')+)'|([A-Za-z0-9_.]+))!)?\$?([A-Z]{1,3}):\$?([A-Z]{1,3})(?![\w(])")


def refs_in(formula, own_sheet):
    """(sheet, col1, col2, row1, row2) for each reference in a formula (text in quotes skipped)."""
    out = []
    for i, part in enumerate(re.split(r'("(?:[^"]|"")*")', str(formula))):
        if i % 2:
            continue
        for m in COLREF.finditer(part):
            sh = (m.group(1) or m.group(2) or own_sheet).replace("''", "'")
            out.append((sh, col_index(m.group(3)), col_index(m.group(4)), 1, 1048576))
        for m in REF.finditer(part):
            sh = (m.group(1) or m.group(2) or own_sheet).replace("''", "'")
            a, b = col_index(m.group(4)), col_index(m.group(8)) if m.group(8) else col_index(m.group(4))
            ra, rb = int(m.group(6)), int(m.group(10)) if m.group(10) else int(m.group(6))
            out.append((sh, min(a, b), max(a, b), min(ra, rb), max(ra, rb)))
    return out


def dependents(wb, sheet, c1, c2=None, skip_col=None):
    """Cells whose formulas would break if columns c1..c2 of a sheet went: references that lie wholly inside them."""
    c2 = c2 or c1
    out = []
    for w in wb.Worksheets:
        F, _, r0, cc0 = grid(w)
        for i, row in enumerate(F):
            for j, f in enumerate(row):
                if not is_formula(f):
                    continue
                if str(w.Name) == sheet and skip_col and cc0 + j in range(c1, c2 + 1):
                    continue  # the column's own formulas go with it
                for sh, a, b, _, _ in refs_in(f, str(w.Name)):
                    if sh.lower() == sheet.lower() and c1 <= a and b <= c2:
                        out.append(f"{w.Name}!{letter(cc0 + j)}{r0 + i}")
                        break
    return out


def op_delete_column(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    deps = dependents(wb, str(ws.Name), c["idx"], skip_col=True)
    if deps and not op.get("force"):
        raise OpError(
            f"{len(deps)} formula(s) use '{c['name']}' ({', '.join(deps[:4])}{'...' if len(deps) > 4 else ''}); deleting it would turn "
            f"them into #REF! errors. Say 'delete {c['name']} anyway' to keep those cells as their current values and delete it"
        )
    for d in deps:  # forced: the cells that used it keep the values they show now
        sh, cell = d.rsplit("!", 1)
        x = wb.Worksheets(sh).Range(cell)
        x.Value = x.Value
    filt = bool(ws.AutoFilterMode)
    ws.Columns(c["idx"]).Delete()
    t2 = table(ws)
    gone = all(x["name"].lower() != c["name"].lower() for x in t2["cols"])
    if filt and not ws.AutoFilterMode:
        rng(ws, t2["header"], t2["c0"], t2["last"], t2["c1"]).AutoFilter()
    return {
        "done": f"column '{c['name']}' ({c['letter']}) deleted" + (f"; {len(deps)} cell(s) that used it now hold values" if deps else ""),
        "ok": gone,
        "what": f"{len(t['cols'])} -> {len(t2['cols'])} columns",
    }


def op_rename_column(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    new = str(op.get("name") or "").strip()
    if not new:
        raise OpError("what should it be called?")
    ws.Cells(t["header"], c["idx"]).Value = new
    return {
        "done": f"column '{c['name']}' renamed '{new}'",
        "ok": str(ws.Cells(t["header"], c["idx"]).Value) == new,
        "what": f"{c['letter']}{t['header']} = '{new}'",
    }


def op_move_column(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    if op.get("after"):
        k = get_col(t, op["after"])["idx"] + 1
    elif op.get("before"):
        k = get_col(t, op["before"])["idx"]
    else:
        k = t["c0"] if op.get("to") in ("start", "first") else t["c1"] + 1
    if k in (c["idx"], c["idx"] + 1):
        raise OpError(f"'{c['name']}' is already there")
    ws.Columns(c["idx"]).Cut()
    ws.Columns(k).Insert()  # cut and insert: Excel moves the references with it
    t2 = table(ws)
    names = [x["name"] for x in t2["cols"]]
    return {
        "done": f"column '{c['name']}' moved (now {get_col(t2, c['name'])['letter']})",
        "ok": c["name"] in names and len(names) == len(t["cols"]),
        "what": " | ".join(names),
    }


def op_hide(app, wb, op):
    show = bool(op.get("show"))
    ws = get_ws(wb, op.get("sheet"))
    if op.get("sheet_only"):
        if not show and sum(1 for w in wb.Worksheets if int(w.Visible) == -1) < 2:
            raise OpError("the only visible sheet cannot be hidden")
        ws.Visible = -1 if show else 0
        return {
            "done": f"sheet '{ws.Name}' {'shown' if show else 'hidden'}",
            "ok": (int(ws.Visible) == -1) == show,
            "what": f"visible={int(ws.Visible)}",
        }
    t = table(ws)
    cols = [get_col(t, x) for x in (op.get("cols") or [op.get("col")]) if x]
    if not cols:
        raise OpError("which column?")
    for c in cols:
        ws.Columns(c["idx"]).Hidden = not show
    ok = all(bool(ws.Columns(c["idx"]).Hidden) == (not show) for c in cols)
    return {"done": f"{', '.join(c['name'] for c in cols)} {'shown' if show else 'hidden'}", "ok": ok, "what": f"{len(cols)} column(s)"}


# ------------------------------------------------------------------------------------------------ rows
def _key(v):
    if is_num(v):
        return float(v)
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()[:10]
    return " ".join(str(v or "").split()).lower()


def _sort_key(v):
    if v is None or v == "":
        return (2, 0)
    if is_num(v):
        return (0, float(v))
    if isinstance(v, (_dt.date, _dt.datetime)):
        return (0, serial(v))
    return (1, str(v).lower())


def op_sort(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    by = op.get("by") or []
    if isinstance(by, (str, dict)):
        by = [by]
    keys = []
    for b in by:
        b = b if isinstance(b, dict) else {"col": b}
        keys.append((get_col(t, b.get("col")), bool(b.get("desc"))))
    if not keys:
        raise OpError("sort by which column?")
    if len(t["rows"]) < 2:
        raise OpError("nothing to sort")
    srt = ws.Sort
    srt.SortFields.Clear()
    for c, desc in keys:
        srt.SortFields.Add(col_range(ws, t, c), 0, 2 if desc else 1)
    srt.SetRange(rng(ws, t["first"], t["c0"], t["last"], t["c1"]))
    srt.Header = 2
    srt.MatchCase = False
    srt.Orientation = 1
    srt.Apply()
    t2 = table(ws)
    rows = [r for r in zip(*[col_values(ws, t2, get_col(t2, c["name"])) for c, _ in keys]) if any(x not in (None, "") for x in r)]
    ok = True
    for a, b in zip(rows, rows[1:]):
        for (c, desc), x, y in zip(keys, a, b):
            kx, ky = _sort_key(x), _sort_key(y)
            if kx == ky:
                continue
            if kx[0] == ky[0] and (kx > ky) != desc:
                ok = False
            break

    def order(c, desc):
        if c["kind"] == "text":
            return "Z-A" if desc else "A-Z"
        if c["kind"] == "date":
            return "newest first" if desc else "oldest first"
        return "highest first" if desc else "lowest first"

    return {
        "done": "sorted by " + ", then ".join(f"{c['name']} ({order(c, desc)})" for c, desc in keys),
        "ok": ok,
        "what": f"{len(rows)} rows in order; first: {_say(rows[0][0]) if rows else '-'}",
    }


def _match(v, opn, val, val2=None):
    if opn in ("contains", "has"):
        return str(val).lower() in str(v or "").lower()
    if opn in ("starts", "begins"):
        return str(v or "").lower().startswith(str(val).lower())
    if opn == "blank":
        return v is None or str(v).strip() == ""
    if opn == "notblank":
        return not (v is None or str(v).strip() == "")
    if opn == "in":
        return _key(v) in {_key(x) for x in val}
    if isinstance(v, (_dt.date, _dt.datetime)):
        v = serial(v)
    if isinstance(val, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
        val = serial(_dt.datetime.strptime(val, "%Y-%m-%d"))
    if isinstance(val2, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", val2):
        val2 = serial(_dt.datetime.strptime(val2, "%Y-%m-%d"))
    if opn == "between":
        return is_num(v) and float(val) <= float(v) <= float(val2)
    if is_num(v) and is_num(val):
        a, b = float(v), float(val)
    elif is_num(val) and isinstance(v, str):
        return opn == "<>"
    else:
        a, b = _key(v), _key(val)
        if isinstance(a, float) != isinstance(b, float):
            return opn == "<>"
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b, "=": a == b, "<>": a != b}.get(opn, False)


def op_filter(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    if op.get("clear"):
        if ws.FilterMode:
            ws.ShowAllData()
        return {"done": "filter cleared: every row shows", "ok": not bool(ws.FilterMode), "what": f"{len(t['rows'])} rows show"}
    c = get_col(t, op.get("col"))
    field = c["idx"] - t["c0"] + 1
    whole = rng(ws, t["header"], t["c0"], t["last"], t["c1"])
    opn = str(op.get("cmp") or "=")
    val = op.get("value") if op.get("value") is not None else op.get("values")
    vals = col_values(ws, t, c)
    if ws.FilterMode:
        ws.ShowAllData()
    crit = lambda x: f"{serial(_dt.datetime.strptime(x, '%Y-%m-%d')):.0f}" if isinstance(x, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x) else x
    if opn == "in" or isinstance(val, list):
        import pythoncom
        from win32com.client import VARIANT

        items = [str(x) for x in (val if isinstance(val, list) else [val])]
        whole.AutoFilter(field, VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, items), 7)
        opn, val = "in", items
    elif opn in ("contains", "has"):
        whole.AutoFilter(field, f"=*{val}*")
    elif opn in ("starts", "begins"):
        whole.AutoFilter(field, f"={val}*")
    elif opn == "blank":
        whole.AutoFilter(field, "=")
    elif opn == "notblank":
        whole.AutoFilter(field, "<>")
    elif opn == "top":
        whole.AutoFilter(field, str(int(val or 10)), 3)  # xlTop10Items
    elif opn == "between":
        whole.AutoFilter(field, f">={crit(val)}", 1, f"<={crit(op.get('value2'))}")
    else:
        whole.AutoFilter(field, f"{opn}{crit(val)}")
    shown = sum(1 for i, r in enumerate(range(t["first"], t["last"] + 1)) if not ws.Rows(r).Hidden and not t["blank"][i])
    if opn == "top":
        nums = sorted((float(v) for v in vals if is_num(v)), reverse=True)
        cut = nums[min(len(nums), int(val or 10)) - 1] if nums else None
        want = sum(1 for v in vals if is_num(v) and cut is not None and float(v) >= cut)
    else:
        want = sum(1 for v, b in zip(vals, t["blank"]) if not b and _match(v, opn, val, op.get("value2")))
    total = sum(1 for b in t["blank"] if not b)
    return {
        "done": f"filter on {c['name']}: {opn} {_say(val) if not isinstance(val, list) else ', '.join(map(str, val))} ({shown} of {total} rows show)",
        "ok": shown == want,
        "what": f"{shown} rows show, Python counts {want}",
    }


def _delete_rows(ws, t, rows):
    for r in sorted(set(rows), reverse=True):  # only the table's cells move up: anything beside the table stays where it is
        rng(ws, r, t["c0"], r, t["c1"]).Delete(-4162)


def op_remove_duplicates(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    cols = [get_col(t, x) for x in (op.get("cols") or [])] or t["cols"]
    seen, dup = set(), []
    for i, r in enumerate(t["rows"]):
        if t["blank"][i]:
            continue
        k = tuple(_key(r[c["idx"] - t["c0"]]) for c in cols)
        if k in seen:
            dup.append(t["first"] + i)
        else:
            seen.add(k)
    if not dup:
        raise OpError("there are no duplicate rows" + (f" by {', '.join(c['name'] for c in cols)}" if op.get("cols") else ""))
    _delete_rows(ws, t, dup)
    t2 = table(ws)
    keys = [tuple(_key(r[c["idx"] - t2["c0"]]) for c in cols) for r, b in zip(t2["rows"], t2["blank"]) if not b]
    before = sum(1 for b in t["blank"] if not b)
    return {
        "done": f"{len(dup)} duplicate row(s) removed"
        + (f" (same {', '.join(c['name'] for c in cols)})" if op.get("cols") else " (every column the same)"),
        "ok": len(keys) == len(set(keys)) == before - len(dup),
        "what": f"{before} -> {len(keys)} rows, all unique",
    }


def op_delete_rows(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    w = op.get("where") or {}
    if op.get("blank"):
        hit = [t["first"] + i for i, b in enumerate(t["blank"]) if b]
        say = "empty row(s)"
    elif op.get("rows"):
        hit = [int(x) for x in op["rows"] if t["first"] <= int(x) <= t["last"]]
        say = f"row(s) {', '.join(map(str, hit))}"
    else:
        c = get_col(t, w.get("col"))
        hit = [
            t["first"] + i
            for i, r in enumerate(t["rows"])
            if not t["blank"][i] and _match(r[c["idx"] - t["c0"]], str(w.get("op") or "="), w.get("value"), w.get("value2"))
        ]
        say = f"row(s) where {c['name']} {w.get('op') or '='} {_say(w.get('value'))}"
    if not hit:
        raise OpError(f"there are no {say}")
    if len(hit) >= sum(1 for b in t["blank"] if not b) and not op.get("blank") and not op.get("force"):
        raise OpError(f"that would delete every row ({len(hit)})")
    _delete_rows(ws, t, hit)
    t2 = table(ws, need=False)
    left = len(t2["rows"]) if t2 else 0
    return {"done": f"{len(hit)} {say} deleted", "ok": left == len(t["rows"]) - len(hit), "what": f"{len(t['rows'])} -> {left} rows"}


def op_add_row(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    given = {get_col(t, k)["idx"]: v for k, v in (op.get("values") or {}).items()}
    if not given:
        raise OpError("what goes in the new row?")
    if not t["rows"]:
        raise OpError("the table has no rows to copy the layout from")
    last = t["last"]
    # cells inserted inside the table: every range over the rows (totals, summaries, charts) grows to take the new row
    rng(ws, last, t["c0"], last, t["c1"]).Insert(-4121)
    rng(ws, last + 1, t["c0"], last + 1, t["c1"]).Copy(rng(ws, last, t["c0"], last, t["c1"]))  # the old last row back in its place
    new = last + 1
    for c in t["cols"]:
        cell = ws.Cells(new, c["idx"])
        if c["idx"] in given:
            v = given[c["idx"]]
            if c["kind"] == "date" and isinstance(v, str):
                d = _parse_date(v, "dmy")
                v = serial(d) if d else v
                if d and not re.search(r"[dmy]", str(cell.NumberFormat), re.I):
                    cell.NumberFormat = FORMATS["date"]
            cell.Value = v
        elif not is_formula(str(cell.Formula)):
            cell.ClearContents()
    app.Calculate()
    t2 = table(ws)
    got = {c["name"]: _py(ws.Cells(new, c["idx"]).Value) for c in t2["cols"]}
    shown = {c["name"]: str(ws.Cells(new, c["idx"]).Text).strip() for c in t2["cols"]}

    def agrees(k, v):
        got_v = _py(ws.Cells(new, k).Value)
        if isinstance(v, str) and isinstance(got_v, (_dt.date, _dt.datetime)):
            d = _parse_date(v, "dmy")
            return d is not None and d.date() == got_v.date()
        return same(got_v, v) or (isinstance(v, str) and _key(got_v) == _key(v))

    bad = [k for k, v in given.items() if not agrees(k, v)]
    errs = [k for k, v in got.items() if isinstance(v, str) and v in XL_ERR.values()]
    more = f"; the {str(t2['total_label'] or 'totals').lower()} row now covers {len(t2['rows'])} rows" if t2["total"] else ""
    return {
        "done": "row added: " + ", ".join(f"{k} {shown.get(k) or _say(v)}" for k, v in got.items() if v not in (None, ""))[:220] + more,
        "ok": len(t2["rows"]) == len(t["rows"]) + 1 and not bad and not errs,
        "what": f"{len(t['rows'])} -> {len(t2['rows'])} rows" + (f"; errors in {errs}" if errs else ""),
    }


# ------------------------------------------------------------------------------------------------ totals, summaries, pivots, charts
def op_total_row(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    fn = FN.get(str(op.get("fn") or "sum").lower(), "SUM")
    rate = re.compile(r"price|rate|\bunit\b|rank|share|running|\bid\b|serial|\bno\.?$|year|month|\bday|age\b|%|percent", re.I)
    cols = [get_col(t, x) for x in (op.get("cols") or [])] or [
        c
        for c in t["cols"]
        if c["kind"] in ("number", "money", "percent")
        and c["idx"] != t["c0"]
        and not (fn == "SUM" and c["kind"] != "percent" and rate.search(c["name"]))
    ]
    if not cols:
        raise OpError("no number columns to total")
    tr = t["total"] or t["last"] + 1
    if not t["total"] and int(ws.Application.WorksheetFunction.CountA(rng(ws, tr, t["c0"], tr, t["c1"]))):
        rng(ws, tr, t["c0"], tr, t["c1"]).Insert(-4121)
    label_cell = ws.Cells(tr, t["c0"])
    label = {"SUM": "Total", "AVERAGE": "Average", "COUNT": "Count", "MAX": "Highest", "MIN": "Lowest", "MEDIAN": "Median"}[fn]
    if t["cols"][0]["kind"] == "text" and t["cols"][0] not in cols and not label_cell.HasFormula and (not t["total"] or not op.get("cols")):
        label_cell.Value = label  # a new totals row always says what it holds
    expect, said = {}, []
    for c in cols:
        L = letter(c["idx"])
        f = fn if not (fn == "SUM" and c["kind"] == "percent" and not op.get("cols")) else "AVERAGE"
        ws.Cells(tr, c["idx"]).Formula = f"={f}({L}{t['first']}:{L}{t['last']})"
        ws.Cells(tr, c["idx"]).NumberFormat = ws.Cells(t["first"], c["idx"]).NumberFormat
        xs = [float(v) for v in col_values(ws, t, c) if is_num(v)]
        expect[c["idx"]] = (
            sum(xs)
            if f == "SUM"
            else sum(xs) / len(xs)
            if f == "AVERAGE" and xs
            else len(xs)
            if f == "COUNT"
            else max(xs)
            if f == "MAX" and xs
            else min(xs)
            if f == "MIN" and xs
            else sorted(xs)[len(xs) // 2]
            if f == "MEDIAN" and xs
            else None
        )
        said.append(f"{c['name']} {f.lower()}")
    row = rng(ws, tr, t["c0"], tr, t["c1"])
    row.Font.Bold = True
    row.Borders(8).LineStyle = 1  # top: thin
    row.Borders(9).LineStyle = -4119  # bottom: double
    app.Calculate()
    bad = [c["name"] for c in cols if expect.get(c["idx"]) is not None and not same(ws.Cells(tr, c["idx"]).Value, expect[c["idx"]])]
    shown = ", ".join(f"{c['name']} {_say(_py(ws.Cells(tr, c['idx']).Value))}" for c in cols[:4])
    return {
        "done": f"{label.lower()} row {'updated' if t['total'] else 'added'} at row {tr} ({shown})",
        "ok": not bad,
        "what": f"{len(cols) - len(bad)}/{len(cols)} totals match Python" + (f"; wrong: {bad}" if bad else ""),
    }


def _new_sheet(wb, name):
    names = {str(w.Name).lower() for w in wb.Sheets}
    base = re.sub(r"[\[\]:*?/\\]", "", str(name))[:31].strip() or "Sheet"
    n, k = base, 2
    while n.lower() in names:
        n = f"{base[:28]} {k}"
        k += 1
    ws = wb.Worksheets.Add(None, wb.Sheets(wb.Sheets.Count))
    ws.Name = n
    return ws


def _look(wb, ws, t):
    """The workbook's own colours for a new chart: the table header's fill when it is a real colour, else the colour of a
    chart already in the workbook, else a dark blue; and the header's font."""
    accent, font = None, None
    try:
        h = ws.Cells(t["header"], t["c0"])
        font = str(h.Font.Name)
        if int(h.Interior.ColorIndex) != -4142:
            hx = hexof(h.Interior.Color)
            if 0.02 < _lum(hx) < 0.45:
                accent = hx
    except Exception:  # noqa: BLE001
        pass
    if not accent:
        for w in wb.Worksheets:
            for co in w.ChartObjects():
                try:
                    hx = hexof(co.Chart.SeriesCollection(1).Format.Fill.ForeColor.RGB)
                    if 0.02 < _lum(hx) < 0.6:
                        accent = hx
                        break
                except Exception:  # noqa: BLE001
                    continue
            if accent:
                break
    return accent or PALETTE[0], font


def _style_header(src, dst):
    try:
        dst.Font.Bold = True
        dst.Interior.Color = src.Interior.Color
        dst.Font.Color = src.Font.Color
        dst.Font.Name = src.Font.Name
    except Exception:  # noqa: BLE001
        dst.Font.Bold = True


def _add_chart(ws, kind, xr, yrs, names, title, left, top, look=(None, None), w=480, h=290):
    xt = CHART_TYPES.get(kind, 51)
    try:
        shp = ws.Shapes.AddChart2(-1, xt, left, top, w, h)
        ch = shp.Chart
    except Exception:  # noqa: BLE001  (Excel before 2013)
        ch = ws.ChartObjects().Add(left, top, w, h).Chart
        ch.ChartType = xt
    while int(ch.SeriesCollection().Count):  # Excel guesses a range from the selection: start empty
        ch.SeriesCollection(1).Delete()
    for yr, nm in zip(yrs, names):
        s = ch.SeriesCollection().NewSeries()
        s.Values = yr
        s.XValues = xr
        s.Name = "='" + str(nm.Worksheet.Name).replace("'", "''") + "'!" + str(nm.Address)
        if kind in ("pie", "doughnut"):
            break
    accent, font = look
    colours = [accent or PALETTE[0]] + [c for c in PALETTE if c != (accent or PALETTE[0])]
    try:
        if kind in ("pie", "doughnut"):
            s = ch.SeriesCollection(1)
            for k in range(1, int(s.Points().Count) + 1):
                s.Points(k).Format.Fill.ForeColor.RGB = bgr(colours[(k - 1) % len(colours)])
        else:
            for k in range(1, int(ch.SeriesCollection().Count) + 1):
                s = ch.SeriesCollection(k)
                if kind == "line":
                    s.Format.Line.ForeColor.RGB = bgr(colours[(k - 1) % len(colours)])
                    s.MarkerBackgroundColor = bgr(colours[(k - 1) % len(colours)])
                    s.MarkerForegroundColor = bgr(colours[(k - 1) % len(colours)])
                else:
                    s.Format.Fill.ForeColor.RGB = bgr(colours[(k - 1) % len(colours)])
        if font:
            ch.ChartArea.Font.Name = font
    except Exception:  # noqa: BLE001  (a look that does not apply is not worth failing the chart for)
        pass
    ch.HasTitle = True
    ch.ChartTitle.Text = title
    try:
        ch.ChartTitle.Font.Size = 13
        ch.ChartTitle.Font.Bold = True
    except Exception:  # noqa: BLE001
        pass
    if kind in ("pie", "doughnut"):
        s = ch.SeriesCollection(1)
        s.HasDataLabels = True
        s.DataLabels().ShowPercentage = True
        s.DataLabels().ShowValue = False
    elif len(yrs) == 1:
        ch.HasLegend = False
    return ch


def _free_spot(ws, left, top, w, h):
    """Below any chart that would sit under the new one."""
    moved = True
    while moved:
        moved = False
        for co in ws.ChartObjects():
            cl, ct, cw, chh = float(co.Left), float(co.Top), float(co.Width), float(co.Height)
            if cl < left + w and left < cl + cw and ct < top + h and top < ct + chh:
                top = ct + chh + 15
                moved = True
    return left, top


def _periods(vals, period):
    """Group keys for dates: (label, start, end) per month / quarter / year present in the data, in order."""
    ds = sorted({(v.year, v.month) for v in vals if isinstance(v, (_dt.date, _dt.datetime))})
    out, seen = [], set()
    for y, mo in ds:
        if period == "year":
            k, a, b, lab = (y,), _dt.datetime(y, 1, 1), _dt.datetime(y + 1, 1, 1), str(y)
        elif period == "quarter":
            q = (mo - 1) // 3
            k, a = (y, q), _dt.datetime(y, q * 3 + 1, 1)
            b, lab = (_dt.datetime(y + 1, 1, 1) if q == 3 else _dt.datetime(y, q * 3 + 4, 1)), f"Q{q + 1} {y}"
        else:
            k, a = (y, mo), _dt.datetime(y, mo, 1)
            b, lab = (_dt.datetime(y + 1, 1, 1) if mo == 12 else _dt.datetime(y, mo + 1, 1)), a.strftime("%b %Y")
        if k not in seen:
            seen.add(k)
            out.append((lab, a, b))
    return out


def op_summary(app, wb, op):
    """A summary sheet of live formulas (SUMIFS / AVERAGEIFS / COUNTIFS over the table): it follows the data as it changes."""
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    by = get_col(t, op.get("by"))
    fn = FN.get(str(op.get("fn") or "sum").lower(), "SUM")
    vals = [get_col(t, x) for x in (op.get("values") or [])]
    if not vals and fn != "COUNT":
        vals = [c for c in t["cols"] if c["kind"] in ("number", "money", "percent") and c["idx"] != by["idx"]][:1]
        if not vals:
            raise OpError("no number column to summarise; say which one, or ask for a count")
    recs = [r for r, b in zip(records(t), t["blank"]) if not b]
    period = op.get("period") or ("month" if by["kind"] == "date" else None)
    if period:
        groups = _periods([r[by["name"]] for r in recs], period)
        if not groups:
            raise OpError(f"{by['name']} has no dates")
    else:
        groups, seen = [], set()
        for r in recs:
            v = r[by["name"]]
            if v not in (None, "") and _key(v) not in seen:
                seen.add(_key(v))
                groups.append((v, None, None))
    name = op.get("name") or (f"{(vals[0]['name'] + ' ') if vals else 'Count '}by {period or by['name']}")
    s2 = _new_sheet(wb, name)
    sh = "'" + str(ws.Name).replace("'", "''") + "'"
    B = f"{sh}!${by['letter']}${t['first']}:${by['letter']}${t['last']}"
    heads = [by["name"] if not period else period.title()] + ([f"{fn.title()} of {c['name']}" for c in vals] if fn != "COUNT" else ["Count"])
    for j, h in enumerate(heads):
        s2.Cells(1, j + 1).Value = h
        _style_header(ws.Cells(t["header"], t["c0"]), s2.Cells(1, j + 1))
    expect = {}
    for i, (k, a, b) in enumerate(groups):
        r = i + 2
        if period == "month":
            s2.Cells(r, 1).Value = serial(a)
            s2.Cells(r, 1).NumberFormat = FORMATS["month"]
        else:
            s2.Cells(r, 1).Value = k
        cond = f'{B},">="&{serial(a):.0f},{B},"<"&{serial(b):.0f}' if period else f"{B},$A{r}"
        mine = [
            x
            for x in recs
            if (
                a <= x[by["name"]] < b
                if period and isinstance(x[by["name"]], (_dt.date, _dt.datetime))
                else (not period and _key(x[by["name"]]) == _key(k))
            )
        ]
        if fn == "COUNT":
            s2.Cells(r, 2).Formula = f"=COUNTIFS({cond})"
            expect[(r, 2)] = len(mine)
            continue
        for j, c in enumerate(vals):
            V = f"{sh}!${c['letter']}${t['first']}:${c['letter']}${t['last']}"
            f = {"SUM": "SUMIFS", "AVERAGE": "AVERAGEIFS", "MAX": "MAXIFS", "MIN": "MINIFS"}.get(fn, "SUMIFS")
            body = f"{f}({V},{cond})"
            s2.Cells(r, j + 2).Formula = f"={body}" if f == "SUMIFS" else f'=IFERROR({body},"")'  # a group left empty shows blank, not #DIV/0!
            s2.Cells(r, j + 2).NumberFormat = ws.Cells(t["first"], c["idx"]).NumberFormat
            xs = [float(x[c["name"]]) for x in mine if is_num(x[c["name"]])]
            expect[(r, j + 2)] = (
                sum(xs)
                if f == "SUMIFS"
                else sum(xs) / len(xs)
                if f == "AVERAGEIFS" and xs
                else max(xs)
                if f == "MAXIFS" and xs
                else min(xs)
                if xs
                else None
            )
    last = len(groups) + 1
    if fn in ("SUM", "COUNT"):
        s2.Cells(last + 1, 1).Value = "Total"
        for j in range(2, len(heads) + 1):
            L = letter(j)
            s2.Cells(last + 1, j).Formula = f"=SUM({L}2:{L}{last})"
            s2.Cells(last + 1, j).NumberFormat = s2.Cells(2, j).NumberFormat
        rng(s2, last + 1, 1, last + 1, len(heads)).Font.Bold = True
        rng(s2, last + 1, 1, last + 1, len(heads)).Borders(8).LineStyle = 1
    s2.Columns.AutoFit()
    _print_setup(app, s2)
    app.Calculate()
    bad = [(rc, s2.Cells(*rc).Value, e) for rc, e in expect.items() if e is not None and not same(s2.Cells(*rc).Value, e)]
    done = f"sheet '{s2.Name}': {fn.lower()} of {', '.join(c['name'] for c in vals) or 'rows'} by {period or by['name']} ({len(groups)} groups, live formulas)"
    if op.get("chart"):
        kind = str(op.get("chart") if isinstance(op.get("chart"), str) else ("line" if period else "column" if len(groups) <= 12 else "bar"))
        _add_chart(
            s2,
            kind,
            rng(s2, 2, 1, last, 1),
            [rng(s2, 2, 2, last, 2)],
            [s2.Cells(1, 2)],
            f"{heads[1]} by {heads[0]}",
            s2.Cells(1, len(heads) + 2).Left,
            s2.Cells(1, 1).Top,
            _look(wb, ws, t),
        )
        done += f" and a {kind} chart"
    return {
        "done": done,
        "ok": not bad,
        "what": f"{len(expect) - len(bad)}/{len(expect)} groups match Python" + (f"; e.g. {bad[0]}" if bad else ""),
        "sheet": str(s2.Name),
    }


def op_pivot(app, wb, op):
    """A real PivotTable on a new sheet (rows, optional columns, one or more values; dates grouped by month, quarter or
    year). Checked against Python: each row group (one row field, no columns) and the grand total."""
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    rows_f = [get_col(t, x) for x in (op.get("rows") or ([op["by"]] if op.get("by") else []))]
    cols_f = [get_col(t, x) for x in (op.get("columns") or [])]
    fn = FN.get(str(op.get("fn") or "sum").lower(), "SUM")
    vals = [get_col(t, x) for x in (op.get("values") or [])] or [
        c for c in t["cols"] if c["kind"] in ("number", "money") and c not in rows_f + cols_f
    ][:1]
    if not rows_f:
        raise OpError("a pivot by which column?")
    if not vals:
        raise OpError("a pivot of which number column?")
    if any(t["blank"]):
        raise OpError("the table has empty rows inside it; say 'delete the empty rows' first (a pivot would count them as (blank))")
    s2 = _new_sheet(wb, op.get("name") or f"Pivot by {rows_f[0]['name']}")
    src = rng(ws, t["header"], t["c0"], t["last"], t["c1"])
    pc = wb.PivotCaches().Create(1, src)  # xlDatabase
    tname = re.sub(r"\W", "", f"Pivot{rows_f[0]['name']}")[:28] or "Pivot1"
    pt = pc.CreatePivotTable(s2.Range("A3"), tname)
    pt.ManualUpdate = True
    for i, c in enumerate(rows_f):
        f = pt.PivotFields(c["name"])
        f.Orientation = 1
        f.Position = i + 1
    for i, c in enumerate(cols_f):
        f = pt.PivotFields(c["name"])
        f.Orientation = 2
        f.Position = i + 1
    for c in vals:
        df = pt.AddDataField(pt.PivotFields(c["name"]), f"{fn.title()} of {c['name']} ", XL_FN.get(fn, -4157))
        try:
            df.NumberFormat = str(ws.Cells(t["first"], c["idx"]).NumberFormat) if fn != "COUNT" else "#,##0"
        except Exception:  # noqa: BLE001
            pass
    pt.ManualUpdate = False
    period = op.get("period")
    for c in rows_f + cols_f:
        if c["kind"] == "date":
            per = period or "month"
            years = len({v.year for v in col_values(ws, t, c) if isinstance(v, (_dt.date, _dt.datetime))}) > 1
            p = [False, False, False, False, per == "month", per == "quarter", per == "year" or years]
            try:
                pt.PivotFields(c["name"]).DataRange.Cells(1).Group(Start=True, End=True, Periods=tuple(p))
            except Exception as e:  # noqa: BLE001
                raise OpError(f"Excel could not group {c['name']} by {per}: {e}") from None
    try:
        pt.RowAxisLayout(1)  # tabular: the field names head their columns
    except Exception:  # noqa: BLE001
        pass
    s2.Columns.AutoFit()
    _print_setup(app, s2)
    tr = _rows(pt.TableRange1.Value)
    recs = records(t)
    v0 = vals[0]
    xs = [float(r[v0["name"]]) for r in recs if is_num(r[v0["name"]])]
    grand = sum(xs) if fn == "SUM" else len([r for r in recs if r[v0["name"]] not in (None, "")]) if fn == "COUNT" else None
    got_grand = None
    for row in tr:
        if row and str(row[0]).strip().lower().startswith("grand total"):
            nums = [x for x in row[1:] if is_num(x)]
            got_grand = nums[-1] if nums else None
    ok, what = True, ""
    if len(rows_f) == 1 and not cols_f and rows_f[0]["kind"] != "date" and len(vals) == 1:
        want = {}
        for r in recs:
            k = _key(r[rows_f[0]["name"]])
            if r[v0["name"]] in (None, "") and fn != "COUNT":
                continue
            want.setdefault(k, []).append(float(r[v0["name"]]) if is_num(r[v0["name"]]) else 0.0)
        agg = {
            k: (sum(v) if fn == "SUM" else sum(v) / len(v) if fn == "AVERAGE" else len(v) if fn == "COUNT" else max(v) if fn == "MAX" else min(v))
            for k, v in want.items()
        }
        got = {
            _key(row[0]): row[1]
            for row in tr[1:]
            if row and row[0] not in (None, "") and not str(row[0]).lower().startswith(("grand total", "row labels"))
        }
        bad = [k for k in agg if k not in got or not same(got[k], agg[k])]
        ok = not bad and len(got) == len(agg)
        what = f"{len(agg) - len(bad)}/{len(agg)} groups match Python"
    if grand is not None:
        ok = ok and got_grand is not None and same(got_grand, grand)
        what += ("; " if what else "") + f"grand total {_say(got_grand)} vs Python {_say(grand)}"
    return {
        "done": f"pivot table on sheet '{s2.Name}': {fn.lower()} of {', '.join(c['name'] for c in vals)} by {', '.join(c['name'] for c in rows_f)}"
        + (f" across {', '.join(c['name'] for c in cols_f)}" if cols_f else "")
        + (f" (dates by {period or 'month'})" if any(c["kind"] == "date" for c in rows_f + cols_f) else ""),
        "ok": ok,
        "what": what or "pivot built",
        "sheet": str(s2.Name),
    }


def op_chart(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    kind = str(op.get("type") or "column").lower()
    if kind not in CHART_TYPES:
        kind = "column"
    x = get_col(t, op["x"]) if op.get("x") else next((c for c in t["cols"] if c["kind"] in ("text", "date")), t["cols"][0])
    ys = [get_col(t, y) for y in (op.get("y") or [])] or [
        c for c in t["cols"] if c["kind"] in ("number", "money", "percent") and c["idx"] != x["idx"]
    ][:1]
    if not ys:
        raise OpError("no number column to chart")
    if any(t["blank"]):
        raise OpError("the table has empty rows inside it; say 'delete the empty rows' first (they would show as gaps)")
    xs = [v for v in col_values(ws, t, x) if v not in (None, "")]
    distinct = {(_key(v) if x["kind"] != "date" else (v.year, v.month) if isinstance(v, (_dt.date, _dt.datetime)) else _key(v)) for v in xs}
    if len(distinct) < len(xs) and not op.get("rows"):
        if kind in ("pie", "doughnut") and len(distinct) > 12:
            raise OpError(f"{x['name']} has {len(distinct)} different values: too many slices for a pie; a column or bar chart reads better")
        name = f"{ys[0]['name']} by {'month' if x['kind'] == 'date' else x['name']}"
        r = op_summary(
            app,
            wb,
            {
                "sheet": str(ws.Name),
                "by": x["name"],
                "values": [y["name"] for y in ys],
                "fn": op.get("fn") or "sum",
                "chart": kind if not (x["kind"] == "date" and kind == "column") else "line" if len(distinct) > 6 else kind,
                "name": name,
                **({"period": "month"} if x["kind"] == "date" else {}),
            },
        )
        r["done"] = (
            f"{kind} chart of {' and '.join(y['name'] for y in ys)} by {'month' if x['kind'] == 'date' else x['name']}: {x['name']} repeats, so its totals"
            f" went on a new sheet '{r['sheet']}' (live formulas) with the chart beside them"
        )
        return r
    if kind in ("pie", "doughnut"):
        ys = ys[:1]
        if len(t["rows"]) > 12:
            raise OpError(f"a pie of {len(t['rows'])} slices cannot be read; ask for a summary by a column with fewer values and chart that")
    before = sum(int(w.ChartObjects().Count) for w in wb.Worksheets)
    title = op.get("title") or f"{' and '.join(c['name'] for c in ys)} by {x['name']}"
    place = op.get("place") or ("below" if len(t["rows"]) <= 30 else "new_sheet")
    w, h = 480, 290
    if place == "new_sheet":
        host = next((s for s in wb.Worksheets if str(s.Name).lower() == "charts"), None) or _new_sheet(wb, "Charts")
        left, top = _free_spot(host, host.Cells(2, 2).Left, host.Cells(2, 2).Top, w, h)
        _print_setup(app, host, landscape=False)
    elif place == "beside":
        host = ws
        left, top = _free_spot(ws, ws.Cells(t["header"], t["c1"] + 2).Left, ws.Cells(t["header"], t["c1"] + 2).Top, w, h)
    else:  # under the table and anything below it: the printout keeps its width
        host = ws
        ur = ws.UsedRange
        below = int(ur.Row) + int(ur.Rows.Count) + 1
        left, top = _free_spot(ws, ws.Cells(1, t["c0"]).Left, ws.Cells(max(below, (t["total"] or t["last"]) + 2), 1).Top, w, h)
    ch = _add_chart(
        host,
        kind,
        col_range(ws, t, x),
        [col_range(ws, t, y) for y in ys],
        [ws.Cells(t["header"], y["idx"]) for y in ys],
        title,
        left,
        top,
        _look(wb, ws, t),
        w,
        h,
    )
    after = sum(int(s.ChartObjects().Count) for s in wb.Worksheets)
    pts = int(ch.SeriesCollection(1).Points().Count)
    n = len(t["rows"])
    where = f"on sheet {host.Name}" if str(host.Name) != str(ws.Name) else ("under the table" if place == "below" else "beside the table")
    return {
        "done": f"{kind} chart '{title}' {where}",
        "ok": after == before + 1 and pts == n and int(ch.SeriesCollection().Count) == len(ys),
        "what": f"{int(ch.SeriesCollection().Count)} series of {pts} points ({n} rows)",
    }


# ------------------------------------------------------------------------------------------------ formats
def op_number_format(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    f = str(op.get("format") or "")
    code = FORMATS.get(f.lower(), f)
    if not code:
        raise OpError("which format?")
    cols = [get_col(t, x) for x in (op.get("cols") or [op.get("col")]) if x]
    if not cols:
        raise OpError("which column?")
    for c in cols:
        col_range(ws, t, c).NumberFormat = code
        if t["total"] and ws.Cells(t["total"], c["idx"]).HasFormula:
            ws.Cells(t["total"], c["idx"]).NumberFormat = code
        ws.Columns(c["idx"]).AutoFit()
    got = {str(ws.Cells(t["first"], c["idx"]).NumberFormat) for c in cols}
    shown = str(ws.Cells(t["first"], cols[0]["idx"]).Text)
    return {
        "done": f"{', '.join(c['name'] for c in cols)} shown as {f} (e.g. {shown})",
        "ok": got == {code} and "###" not in shown,
        "what": f"format {code}; first cell shows '{shown}'",
    }


def _select(ws, cell):
    try:
        ws.Activate()
        cell.Select()
    except Exception:  # noqa: BLE001
        pass


def op_conditional(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    rule = str(op.get("rule") or (">" if not op.get("formula") else "formula")).lower()
    if op.get("formula") and rule not in ("formula",):
        rule = "formula"
    c = get_col(t, op.get("col")) if op.get("col") else (t["cols"][0] if rule == "formula" else get_col(t, op.get("col")))
    v, v2 = op.get("value"), op.get("value2")
    whole_rows = bool(op.get("rows")) or rule == "formula"
    target = rng(ws, t["first"], t["c0"], t["last"], t["c1"]) if whole_rows else col_range(ws, t, c)
    fill = _colour(
        op.get("color")
        or (
            "green" if rule in (">", ">=", "top", "above") else "red" if rule in ("<", "<=", "bottom", "below", "duplicates", "formula") else "yellow"
        ),
        fill=True,
    )
    vals = col_values(ws, t, c)
    recs = records(t)
    n0 = int(target.FormatConditions.Count)
    lit = lambda x: str(x) if is_num(x) or re.fullmatch(r"-?\d+(?:\.\d+)?", str(x)) else '"' + str(x).replace('"', '""') + '"'
    L, r1 = c["letter"], t["first"]
    want = None
    if rule == "formula":  # any condition on a row: "[Due Date]<TODAY()" , 'AND([Status]<>"Paid",[Amount]>50000)'
        expr = op.get("formula")
        for x in re.findall(r"\[([^\]]+)\]", str(expr)):
            get_col(t, x)
        f1 = to_a1(expr, t, r1)
        f1 = re.sub(r"(?<![$A-Z])([A-Z]{1,3})(" + str(r1) + r")(?!\d)", r"$\1\2", f1)  # columns fixed, the row moves
        _select(ws, ws.Cells(t["first"], t["c0"]))
        fc = target.FormatConditions.Add(2, None, f1)
        res = [calc(expr, r) for r, b in zip(recs, t["blank"]) if not b]
        want = None if any(x is None for x in res) else sum(1 for x in res if (x is True or (is_num(x) and float(x) != 0)))
    elif whole_rows or rule in ("contains", "blank", "text"):
        if rule in CELL_OP and rule != "between":
            expr = f"=${L}{r1}{rule}{lit(v)}"
        elif rule == "between":
            expr = f"=AND(${L}{r1}>={lit(v)},${L}{r1}<={lit(v2)})"
        elif rule == "contains":
            expr = f"=ISNUMBER(SEARCH({lit(v)},${L}{r1}))"
        elif rule == "blank":
            expr = f"=LEN(TRIM(${L}{r1}))=0"
        else:
            raise OpError(f"whole rows cannot be highlighted by '{rule}'")
        _select(ws, ws.Cells(t["first"], t["c0"] if whole_rows else c["idx"]))  # relative references count from the selected cell
        fc = target.FormatConditions.Add(2, None, expr)
        want = sum(1 for x, b in zip(vals, t["blank"]) if not b and _match(x, {"contains": "contains", "blank": "blank"}.get(rule, rule), v, v2))
    elif rule in CELL_OP:
        fc = target.FormatConditions.Add(1, CELL_OP[rule], "=" + lit(v), ("=" + lit(v2)) if rule == "between" else None)
        want = sum(1 for x in vals if _match(x, rule, v, v2))
    elif rule in ("top", "bottom"):
        fc = target.FormatConditions.AddTop10()
        fc.TopBottom = 1 if rule == "top" else 0
        k = int(v or 3)
        pct = bool(op.get("percent"))
        fc.Rank = k
        fc.Percent = pct
        nums = sorted((float(x) for x in vals if is_num(x)), reverse=rule == "top")
        kk = max(1, int(len(nums) * k / 100)) if pct else k
        cut = nums[min(len(nums), kk) - 1] if nums else None
        want = sum(1 for x in vals if is_num(x) and cut is not None and (float(x) >= cut if rule == "top" else float(x) <= cut))
    elif rule in ("duplicates", "unique"):
        fc = target.FormatConditions.AddUniqueValues()
        fc.DupeUnique = 1 if rule == "duplicates" else 0
        from collections import Counter

        cnt = Counter(_key(x) for x in vals if x not in (None, ""))
        want = sum(1 for x in vals if x not in (None, "") and ((cnt[_key(x)] > 1) == (rule == "duplicates")))
    elif rule in ("above", "below"):
        fc = target.FormatConditions.AddAboveAverage()
        fc.AboveBelow = 0 if rule == "above" else 1
        nums = [float(x) for x in vals if is_num(x)]
        avg = sum(nums) / len(nums) if nums else 0
        want = sum(1 for x in nums if (x > avg if rule == "above" else x < avg))
    elif rule in ("scale", "heatmap", "colors", "colours"):
        target.FormatConditions.AddColorScale(3)
        return {
            "done": f"colour scale on {c['name']} (low red, high green)",
            "ok": int(target.FormatConditions.Count) == n0 + 1,
            "what": "rule added",
        }
    elif rule in ("bars", "databars"):
        target.FormatConditions.AddDatabar()
        return {"done": f"data bars on {c['name']}", "ok": int(target.FormatConditions.Count) == n0 + 1, "what": "rule added"}
    else:
        raise OpError(f"no highlight rule '{rule}'")
    fc.Interior.Color = bgr(fill)
    fc.StopIfTrue = False
    try:
        fc.SetFirstPriority()  # what was asked last shows where rules overlap
    except Exception:  # noqa: BLE001
        pass
    lit_cells = 0  # what Excel itself paints: DisplayFormat shows conditional formats as drawn
    for r in range(t["first"], min(t["last"], t["first"] + 800) + 1):
        try:
            if int(ws.Cells(r, c["idx"]).DisplayFormat.Interior.Color) == bgr(fill):
                lit_cells += 1
        except Exception:  # noqa: BLE001
            pass
    say = {
        "top": f"in the top {v or 3}",
        "bottom": f"in the bottom {v or 3}",
        "duplicates": "is a duplicate",
        "unique": "is unique",
        "above": "is above average",
        "below": "is below average",
        "contains": f"contains '{v}'",
        "blank": "is blank",
        "between": f"is between {_say(v)} and {_say(v2)}",
        "formula": f"{op.get('formula')}",
    }.get(rule, f"{rule} {_say(v)}")
    return {
        "done": (
            f"rows highlighted where {say}"
            if rule == "formula"
            else f"{'rows' if whole_rows else c['name'] + ' cells'} highlighted where {c['name']} {say}"
        )
        + f" ({lit_cells} now)",
        "ok": want is None or lit_cells == want,
        "what": f"Excel paints {lit_cells}" + (f", Python expects {want}" if want is not None else ""),
    }


def op_clear_highlights(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    target = col_range(ws, t, get_col(t, op["col"])) if op.get("col") else rng(ws, t["first"], t["c0"], t["last"], t["c1"])
    n = int(target.FormatConditions.Count)
    if not n:
        raise OpError("there are no highlights there")
    target.FormatConditions.Delete()
    return {
        "done": f"{n} highlight rule(s) removed from {op.get('col') or 'the table'}",
        "ok": int(target.FormatConditions.Count) == 0,
        "what": "none left",
    }


def op_freeze(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws, need=False)
    rows = op.get("rows")
    rows = (t["header"] if t else 1) if rows is None else int(rows)
    cols = int(op.get("cols") or 0)
    ws.Activate()
    w = wb.Windows(1)
    w.FreezePanes = False
    if rows or cols:
        w.ScrollRow, w.ScrollColumn = 1, 1
        w.SplitColumn = cols
        w.SplitRow = rows
        w.FreezePanes = True
    ok = (bool(w.FreezePanes) == bool(rows or cols)) and (not (rows or cols) or (int(w.SplitRow) == rows and int(w.SplitColumn) == cols))
    return {
        "done": (f"top {rows} row(s)" if rows else "")
        + (" and " if rows and cols else "")
        + (f"first {cols} column(s)" if cols else "")
        + (" frozen" if rows or cols else "panes unfrozen"),
        "ok": ok,
        "what": f"split at row {int(w.SplitRow)}, column {int(w.SplitColumn)}",
    }


def op_style(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    tg = str(op.get("target") or "header").lower()
    if tg in ("header", "headers", "header row", "titles"):
        r = rng(ws, t["header"], t["c0"], t["header"], t["c1"])
    elif tg in ("totals", "total", "total row"):
        if not t["total"]:
            raise OpError("the table has no totals row")
        r = rng(ws, t["total"], t["c0"], t["total"], t["c1"])
    elif tg in ("table", "all", "everything", "data"):
        r = rng(ws, t["header"], t["c0"], t["total"] or t["last"], t["c1"])
    else:
        c = get_col(t, tg)
        r = rng(ws, t["header"], c["idx"], t["total"] or t["last"], c["idx"])
    s = op.get("set") or {}
    if not s:
        raise OpError("nothing to change")
    if s.get("bold") is not None:
        r.Font.Bold = bool(s["bold"])
    if s.get("italic") is not None:
        r.Font.Italic = bool(s["italic"])
    if s.get("color"):
        r.Font.Color = bgr(_colour(s["color"]))
    if s.get("fill"):
        r.Interior.Color = bgr(_colour(s["fill"], fill=True))
    if s.get("font"):
        r.Font.Name = s["font"]
    if s.get("size"):
        cur = float(r.Font.Size) if r.Font.Size else 11.0
        sz = s["size"]
        r.Font.Size = cur + float(sz) if isinstance(sz, str) and sz[:1] in "+-" else float(sz)
    if s.get("wrap") is not None:
        r.WrapText = bool(s["wrap"])
    if s.get("align"):
        r.HorizontalAlignment = {"left": -4131, "center": -4108, "right": -4152}.get(str(s["align"]).lower(), -4108)
    if s.get("fill") and not s.get("color"):  # a dark fill under dark text: the text turns white
        fx = _colour(s["fill"], fill=True)
        try:
            if _lum(fx) < 0.18 and _lum(hexof(r.Font.Color or 0)) < 0.18:
                r.Font.Color = bgr("FFFFFF")
        except Exception:  # noqa: BLE001
            pass
    ok = True
    if s.get("bold") is not None:
        ok &= bool(r.Font.Bold) == bool(s["bold"])
    if s.get("fill"):
        ok &= int(r.Interior.Color) == bgr(_colour(s["fill"], fill=True))
    if s.get("color"):
        ok &= int(r.Font.Color) == bgr(_colour(s["color"]))
    return {"done": f"{tg} styled: " + ", ".join(f"{k} {v}" for k, v in s.items()), "ok": bool(ok), "what": f"{r.Address}"}


def op_autofit(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    ws.UsedRange.Columns.AutoFit()
    return {"done": f"columns on {ws.Name} sized to fit", "ok": True, "what": "autofit"}


def op_round(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    d = int(op.get("digits") if op.get("digits") is not None else 0)
    r = col_range(ws, t, c)
    F = [x[0] for x in _rows(r.Formula)]
    out = []
    for f in F:
        if is_formula(f):
            core = f[1:]
            mm = re.fullmatch(r"ROUND\((.*),\s*-?\d+\)", core, re.I)
            out.append(f"=ROUND({mm.group(1) if mm else core},{d})")
        elif is_num(f) or re.fullmatch(r"-?\d+(?:\.\d+)?", str(f or "")):
            out.append(round(float(f), d))
        else:
            out.append(f)
    r.Formula = tuple((x,) for x in out)
    r.NumberFormat = "#,##0" if d == 0 else "#,##0." + "0" * d
    vals = col_values(ws, t, c)
    ok = all(not is_num(v) or abs(round(float(v), d) - float(v)) < 1e-9 for v in vals)
    return {"done": f"{c['name']} rounded to {d} decimal(s)", "ok": ok, "what": f"{len(vals)} values with at most {d} decimals"}


def op_validation(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    items = [str(x).replace(",", " ").strip() for x in op.get("list") or [] if str(x).strip()]
    if not items:
        raise OpError("which values are allowed?")
    r = rng(ws, t["first"], c["idx"], t["last"] + 200, c["idx"])
    r.Validation.Delete()
    r.Validation.Add(3, 1, 1, ",".join(items))
    outside = [v for v in col_values(ws, t, c) if v not in (None, "") and str(v).strip().lower() not in {i.lower() for i in items}]
    return {
        "done": f"{c['name']} is now a dropdown: {', '.join(items)}"
        + (f" ({len(outside)} existing value(s) are not in the list, e.g. '{outside[0]}')" if outside else ""),
        "ok": int(ws.Cells(t["first"], c["idx"]).Validation.Type) == 3,
        "what": f"list validation on {r.Address}",
    }


# ------------------------------------------------------------------------------------------------ cleaning messy data
def _clean(v, how):
    if not isinstance(v, str):
        return v
    s = v
    if how in ("trim", "clean", "all"):
        s = " ".join(s.replace(" ", " ").split())
    if how == "proper":
        s = re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), " ".join(s.split()))
    elif how == "upper":
        s = " ".join(s.split()).upper()
    elif how == "lower":
        s = " ".join(s.split()).lower()
    return s


def _write_column(r, F, new):
    if new != F:
        r.Formula = tuple(("" if x is None else x,) for x in new)


def op_clean_text(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    how = str(op.get("how") or "trim").lower()
    cols = [get_col(t, x) for x in (op.get("cols") or [])] or [c for c in t["cols"] if c["kind"] == "text" and not c["formulas"]]
    changed = 0
    for c in cols:
        r = col_range(ws, t, c)
        F = [x[0] for x in _rows(r.Formula)]
        new = [f if is_formula(f) else _clean(f, how) for f in F]
        changed += sum(1 for a, b in zip(F, new) if a != b)
        _write_column(r, F, new)
    if not changed:
        raise OpError(f"{', '.join(c['name'] for c in cols)} already clean ({how})")
    t2 = table(ws)
    left = sum(1 for c in cols for v in col_values(ws, t2, get_col(t2, c["name"])) if isinstance(v, str) and v != _clean(v, how))
    return {
        "done": f"{changed} cell(s) cleaned ({how}) in {', '.join(c['name'] for c in cols)}",
        "ok": left == 0,
        "what": f"{left} cell(s) still need it",
    }


def op_fill_blanks(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    how = str(op.get("how") or "above").lower()
    r = col_range(ws, t, c)
    F = [x[0] for x in _rows(r.Formula)]
    out, prev, n = [], None, 0
    for f, b in zip(F, t["blank"]):
        if not b and (f in (None, "") or (isinstance(f, str) and not f.strip())):
            out.append(prev if how == "above" else op.get("value", 0))
            n += 1
        else:
            out.append(f)
            prev = None if is_formula(f) or b else f
    if not n:
        raise OpError(f"{c['name']} has no blank cells")
    _write_column(r, F, out)
    left = sum(1 for v, b in zip(col_values(ws, t, c), t["blank"]) if not b and v in (None, ""))
    return {
        "done": f"{n} blank cell(s) in {c['name']} filled ({'with the value above' if how == 'above' else repr(op.get('value', 0))})",
        "ok": left == 0 or how == "above",
        "what": f"{left} blank(s) left",
    }


MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "cr": 1e7}


def as_number(v):
    """'Rs 1,200', '(300)', '12%', '1.5 lakh', ' 45 ' -> numbers; None when it is not one."""
    if is_num(v):
        return float(v)
    if not isinstance(v, str) or not v.strip():
        return None
    x = v.strip().replace(" ", " ")
    neg = x.startswith("(") and x.endswith(")")
    x = x.strip("()").strip()
    x = re.sub(r"(?i)^(?:rs\.?|pkr|usd|inr|\$|€|£|₨)\s*|\s*(?:rs\.?|pkr|usd|/-)$", "", x)
    x = x.replace(",", "").replace(" ", "")
    pct = x.endswith("%")
    x = x.rstrip("%")
    m = re.fullmatch(r"([-+]?\d*\.?\d+)(k|m|mn|million|thousand|lakhs?|lac|crore|cr)?", x, re.I)
    if not m:
        return None
    n = float(m.group(1)) * MULT.get((m.group(2) or "").lower(), 1)
    n = n / 100 if pct else n
    return -n if neg else n


def op_to_number(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    cols = [get_col(t, x) for x in (op.get("cols") or [op.get("col")]) if x]
    if not cols:
        raise OpError("which column?")
    conv, stuck = 0, []
    for c in cols:
        r = col_range(ws, t, c)
        F = [x[0] for x in _rows(r.Formula)]
        new = []
        for f in F:
            if is_formula(f) or f in (None, "") or is_num(f):
                new.append(f)
                continue
            n = as_number(f)
            if n is None:
                stuck.append(str(f))
                new.append(f)
            else:
                new.append(n)
                conv += 1
        if new != F:
            r.NumberFormat = "General"
        _write_column(r, F, new)
        nums = [x for x in new if is_num(x)]
        if nums:
            r.NumberFormat = "#,##0" if all(float(x).is_integer() for x in nums) else "#,##0.00"
    if not conv:
        raise OpError(f"{', '.join(c['name'] for c in cols)} already hold numbers" + (f" (not numbers: {stuck[:3]})" if stuck else ""))
    t2 = table(ws)
    texts = sum(1 for c in cols for v in col_values(ws, t2, get_col(t2, c["name"])) if isinstance(v, str) and v.strip())
    return {
        "done": f"{conv} text value(s) in {', '.join(c['name'] for c in cols)} turned into numbers"
        + (f"; could not read {len(stuck)}: {stuck[:3]}" if stuck else ""),
        "ok": texts == len(stuck),
        "what": f"{texts} text cell(s) left",
    }


DATE_FMTS = {
    "dmy": ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"],
    "mdy": ["%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"],
    "ymd": ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"],
}
NAMED = ["%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%d %b, %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]


def _parse_date(s, order):
    s = " ".join(str(s).strip().split())
    for f in DATE_FMTS.get(order, []) + DATE_FMTS["ymd"] + NAMED:
        try:
            return _dt.datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _order_of(texts):
    """Day first or month first, from the values themselves (a first number over 12 is a day); else day first."""
    a = b = 0
    for s in texts:
        m = re.match(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}", s)
        if m:
            a += int(m.group(1)) > 12
            b += int(m.group(2)) > 12
    return "mdy" if b > a else "dmy"


def op_to_date(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    r = col_range(ws, t, c)
    F = [x[0] for x in _rows(r.Formula)]
    texts = [str(f) for f in F if isinstance(f, str) and f.strip() and not is_formula(f)]
    order = op.get("order") or _order_of(texts)
    new, conv, stuck = [], 0, []
    V = [_py(x[0]) for x in _rows(r.Value)]
    for f, v in zip(F, V):
        if isinstance(v, (_dt.date, _dt.datetime)):
            new.append(serial(v))
        elif is_num(v) and not isinstance(f, str):
            new.append(v)
        elif isinstance(f, str) and f.strip() and not is_formula(f):
            d = _parse_date(f, order)
            if d is None:
                stuck.append(f)
                new.append(f)
            else:
                new.append(serial(d))
                conv += 1
        else:
            new.append(f)
    if not conv:
        raise OpError(f"{c['name']} has no dates written as text" + (f" (could not read {stuck[:3]})" if stuck else ""))
    r.NumberFormat = "General"
    r.Formula = tuple(("" if x is None else x,) for x in new)
    r.NumberFormat = FORMATS["date"]
    vals = col_values(ws, t, c)
    dates = sum(1 for x in vals if isinstance(x, (_dt.date, _dt.datetime)))
    filled = sum(1 for x in vals if x not in (None, ""))
    return {
        "done": f"{conv} date(s) in {c['name']} read as {'day/month' if order == 'dmy' else 'month/day' if order == 'mdy' else 'year-month-day'} and made real dates"
        + (f"; could not read {len(stuck)}: {stuck[:3]}" if stuck else ""),
        "ok": dates == filled - len(stuck),
        "what": f"{dates}/{filled} cells are dates",
    }


def _norm_cat(v):
    return re.sub(r"[^0-9a-z]+", "", str(v).lower())


def op_map_values(app, wb, op):
    """One spelling per value: 'lahore', ' LAHORE ', 'Lahore' -> the most common written form (auto), or a given map."""
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    r = col_range(ws, t, c)
    F = [x[0] for x in _rows(r.Formula)]
    from collections import Counter

    texts = [" ".join(f.split()) for f in F if isinstance(f, str) and f.strip() and not is_formula(f)]
    mapping = {}
    if op.get("map"):
        mapping = {_norm_cat(k): str(v) for k, v in op["map"].items()}
    if op.get("auto") or not op.get("map"):
        groups = {}
        for s in texts:
            groups.setdefault(_norm_cat(s), Counter())[s] += 1
        for k, cnt in groups.items():
            if k in mapping:
                continue
            best = max(cnt.items(), key=lambda kv: (kv[1], kv[0] != kv[0].lower() and kv[0] != kv[0].upper(), kv[0][:1].isupper()))[0]
            mapping[k] = best
    new = [mapping.get(_norm_cat(f), f) if isinstance(f, str) and f.strip() and not is_formula(f) else f for f in F]
    changed = sum(1 for a, b in zip(F, new) if a != b)
    if not changed:
        raise OpError(f"{c['name']} already uses one spelling per value")
    _write_column(r, F, new)
    vals = [v for v in col_values(ws, t, c) if isinstance(v, str) and v.strip()]
    spell = {}
    for v in vals:
        spell.setdefault(_norm_cat(v), set()).add(v)
    multi = [k for k, s in spell.items() if len(s) > 1]
    kinds = sorted(set(vals))
    return {
        "done": f"{changed} cell(s) in {c['name']} made consistent: {', '.join(kinds[:8])}{'...' if len(kinds) > 8 else ''}",
        "ok": not multi,
        "what": f"{len(kinds)} distinct value(s)" + (f"; still mixed: {multi[:3]}" if multi else ""),
    }


def op_replace(app, wb, op):
    find, repl = str(op.get("find") or ""), str(op.get("with") if op.get("with") is not None else "")
    if not find:
        raise OpError("replace what?")
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws, need=False)
    if op.get("col") and t:
        c = get_col(t, op["col"])
        r = col_range(ws, t, c)
    else:
        r = ws.UsedRange
    whole = bool(op.get("whole"))
    vals = [_py(x) for row in _rows(r.Value) for x in row]
    n = sum(1 for v in vals if isinstance(v, str) and ((v.strip().lower() == find.lower()) if whole else (find.lower() in v.lower())))
    if not n:
        raise OpError(f"'{find}' is not in {'column ' + op['col'] if op.get('col') else ws.Name}")
    r.Replace(find, repl, 1 if whole else 2, 1, False)
    vals2 = [_py(x) for row in _rows(r.Value) for x in row]
    left = sum(1 for v in vals2 if isinstance(v, str) and ((v.strip().lower() == find.lower()) if whole else (find.lower() in v.lower())))
    return {"done": f"'{find}' replaced with '{repl}' in {n} cell(s)", "ok": left == 0 or find.lower() in repl.lower(), "what": f"{left} left"}


def op_split_column(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    t = table(ws)
    c = get_col(t, op.get("col"))
    names = [str(x) for x in op.get("names") or []] or [f"{c['name']} 1", f"{c['name']} 2"]
    for nm in names:
        if any(x["name"].lower() == nm.lower() for x in t["cols"]):
            raise OpError(f"there is already a column '{nm}'")
    sep = op.get("sep")
    vals = col_values(ws, t, c)
    parts = []
    for v in vals:
        s = str(v or "").strip()
        bits = s.split(sep, len(names) - 1) if sep else s.split(None, len(names) - 1)
        if not sep and len(names) == 2 and len(s.split()) > 2:  # "Muhammad Ali Khan": first name, then the rest
            bits = [s.split()[0], " ".join(s.split()[1:])]
        bits = [b.strip() for b in bits] + [""] * len(names)
        parts.append(bits[: len(names)])
    k = c["idx"] + 1
    rng(ws, 1, k, 1, k + len(names) - 1).EntireColumn.Insert()
    t1 = table(ws)
    for j, nm in enumerate(names):
        ws.Cells(t1["header"], k + j).Value = nm
        rng(ws, t1["first"], k + j, t1["last"], k + j).NumberFormat = "@"
        rng(ws, t1["first"], k + j, t1["last"], k + j).Value = tuple((p[j],) for p in parts)
        ws.Columns(k + j).AutoFit()
    ok = all(" ".join(x for x in p if x).split() == str(v or "").split() for p, v in zip(parts, vals)) if not sep else True
    return {"done": f"{c['name']} split into {', '.join(names)} (the original column stays)", "ok": ok, "what": f"{len(vals)} rows split"}


# ------------------------------------------------------------------------------------------------ sheets
def op_rename_sheet(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    old = str(ws.Name)
    new = re.sub(r"[\[\]:*?/\\]", "", str(op.get("name") or "")).strip()[:31]
    if not new:
        raise OpError("what should the sheet be called?")
    if new.lower() in {str(w.Name).lower() for w in wb.Sheets} and new.lower() != old.lower():
        raise OpError(f"there is already a sheet '{new}'")
    ws.Name = new
    return {
        "done": f"sheet '{old}' renamed '{new}' (formulas that point at it follow)",
        "ok": str(ws.Name) == new,
        "what": ", ".join(str(w.Name) for w in wb.Worksheets),
    }


def op_add_sheet(app, wb, op):
    ws = _new_sheet(wb, op.get("name") or "Sheet")
    return {"done": f"sheet '{ws.Name}' added", "ok": True, "what": ", ".join(str(w.Name) for w in wb.Worksheets)}


def op_delete_sheet(app, wb, op):
    ws = get_ws(wb, op.get("sheet"))
    name = str(ws.Name)
    if int(wb.Worksheets.Count) < 2:
        raise OpError("a workbook needs one sheet")
    users = []
    for w in wb.Worksheets:
        if str(w.Name) == name:
            continue
        F, _, r0, cc0 = grid(w)
        for i, row in enumerate(F):
            for j, f in enumerate(row):
                if is_formula(f) and any(sh.lower() == name.lower() for sh, *_ in refs_in(f, str(w.Name))):
                    users.append(f"{w.Name}!{letter(cc0 + j)}{r0 + i}")
    if users and not op.get("force"):
        raise OpError(
            f"{len(users)} formula(s) on other sheets use '{name}' ({', '.join(users[:3])}); say 'delete the {name} sheet anyway' to keep their values"
        )
    for u in users:
        sh, cell = u.rsplit("!", 1)
        x = wb.Worksheets(sh).Range(cell)
        x.Value = x.Value
    app.DisplayAlerts = False
    ws.Delete()
    return {
        "done": f"sheet '{name}' deleted" + (f"; {len(users)} cell(s) that used it keep their values" if users else ""),
        "ok": name not in [str(w.Name) for w in wb.Worksheets],
        "what": ", ".join(str(w.Name) for w in wb.Worksheets),
    }


OPS = {
    "add_column": op_add_column,
    "delete_column": op_delete_column,
    "rename_column": op_rename_column,
    "move_column": op_move_column,
    "hide": op_hide,
    "sort": op_sort,
    "filter": op_filter,
    "remove_duplicates": op_remove_duplicates,
    "delete_rows": op_delete_rows,
    "add_row": op_add_row,
    "total_row": op_total_row,
    "summary": op_summary,
    "pivot": op_pivot,
    "chart": op_chart,
    "number_format": op_number_format,
    "conditional": op_conditional,
    "clear_highlights": op_clear_highlights,
    "freeze": op_freeze,
    "style": op_style,
    "autofit": op_autofit,
    "round": op_round,
    "validation": op_validation,
    "clean_text": op_clean_text,
    "fill_blanks": op_fill_blanks,
    "to_number": op_to_number,
    "to_date": op_to_date,
    "map_values": op_map_values,
    "replace": op_replace,
    "split_column": op_split_column,
    "rename_sheet": op_rename_sheet,
    "add_sheet": op_add_sheet,
    "delete_sheet": op_delete_sheet,
}


def run_ops(app, wb, ops):
    out = []
    for op in ops:
        name = op.get("op")
        fn = OPS.get(name)
        if fn is None:
            out.append({"op": name, "error": f"no workbook operation '{name}'"})
            continue
        try:
            r = fn(app, wb, op)
            r["op"] = name
            out.append(r)
        except OpError as e:  # refused before anything changed
            out.append({"op": name, "error": str(e)})
        except Exception as e:  # noqa: BLE001  (Excel failed half way: the workbook may be half changed)
            msg = str(getattr(e, "excepinfo", None) and e.excepinfo[2] or e)
            out.append({"op": name, "error": f"Excel said: {type(e).__name__}: {msg[:200]}", "dirty": True})
    return out


# ------------------------------------------------------------------------------------------------ data for other files
def grab(app, wb, spec):
    """A table, a pivot or a range exactly as Excel shows it (each cell's displayed text) plus the values behind it, for a
    report or a deck: {"sheet", "kind", "header", "rows", "values", "total", "total_values", "address"}."""
    ws = get_ws(wb, spec.get("sheet"))
    what = spec.get("what") or ("pivot" if int(ws.PivotTables().Count) else "table")
    head_row = 0
    if what == "pivot":
        if not int(ws.PivotTables().Count):
            raise OpError(f"no pivot table on '{ws.Name}'")
        pt = ws.PivotTables(1)
        pt.RefreshTable()
        r = pt.TableRange1
        head_row = 1 if int(pt.ColumnFields.Count) else 0  # with column fields the first row only names the data field
    elif what == "range":
        r = ws.Range(spec["range"])
    else:
        t = table(ws)
        r = rng(ws, t["header"], t["c0"], t["total"] or t["last"], t["c1"])
    n_r, n_c = int(r.Rows.Count), int(r.Columns.Count)
    if n_r * n_c > 4000:
        raise OpError(f"that is {n_r} rows by {n_c} columns: too big to put on a page; ask for a summary or a pivot of it")
    vals = _rows(r.Value)
    try:
        r.Columns.AutoFit()  # a column too narrow shows "####" for a number (this copy is never saved)
    except Exception:  # noqa: BLE001
        pass

    def shown(i, j):
        cell = r.Cells(i + 1, j + 1)
        t = str(cell.Text).strip()
        if t and set(t) == {"#"}:  # still too narrow: Excel's own formatting of the value
            try:
                t = str(app.WorksheetFunction.Text(cell.Value, cell.NumberFormat)).strip()
            except Exception:  # noqa: BLE001
                t = str(cell.Value)
        return t

    texts = [[shown(i, j) for j in range(n_c)] for i in range(n_r)]
    texts, vals = texts[head_row:], vals[head_row:]
    keep = [j for j in range(n_c) if any(row[j] for row in texts)]  # columns that are empty all the way down go
    texts = [[row[j] for j in keep] for row in texts]
    vals = [[_py(row[j]) if j < len(row) else None for j in keep] for row in vals]
    header = [h.strip() or (f"Column {k + 1}") for k, h in enumerate(texts[0])]
    if what == "pivot" and header and header[0].lower() in ("row labels", ""):
        header[0] = str(pt.RowFields(1).Name) if int(pt.RowFields.Count) else header[0]
    header = [re.sub(r"\s+", " ", h).strip() for h in header]
    body, bvals = texts[1:], vals[1:]
    total = total_v = None
    if body and (re.match(r"^\s*(?:grand\s+)?total\b|^\s*(?:average|summary)\b", body[-1][0], re.I) or (what == "table" and table(ws)["total"])):
        total, total_v, body, bvals = body[-1], bvals[-1], body[:-1], bvals[:-1]
    for row in vals:
        for j, v in enumerate(row):
            if isinstance(v, (_dt.date, _dt.datetime)):
                row[j] = v.isoformat()[:10]
    return {
        "sheet": str(ws.Name),
        "kind": what,
        "header": header,
        "rows": body,
        "values": bvals,
        "total": total,
        "total_values": total_v,
        "address": str(r.Address),
        "number_formats": [str(r.Cells(2 + head_row, j + 1).NumberFormat) for j in keep] if n_r > 1 + head_row else [],
    }
