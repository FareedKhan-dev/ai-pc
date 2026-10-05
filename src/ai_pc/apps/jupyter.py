"""Jupyter notebooks by code: an analysis notebook made from an Excel or CSV file (load it, a first look, summary
statistics, a total by group, and a chart), then run cell by cell here (pandas and matplotlib in the project's own
Python; each cell's printout, table and chart saved into the notebook as Jupyter would), so it opens finished in
Jupyter, VS Code or Google Colab. Checked: every cell ran without an error and the chart is in the notebook.

  'jupyter notebook from sales.xlsx'   'notebook analysing sales.csv: total Amount by Customer'
"""

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

from ai_pc.core.config import STATE

NAME, LABEL = "jupyter", "Jupyter notebooks: an analysis of a sheet, run with its tables and charts"
EXAMPLES = ["jupyter notebook from sales.xlsx", "notebook analysing sales.csv: total Amount by Customer"]
RUNNER = r"""
import ast, base64, contextlib, io, json, os, sys, traceback
os.environ.setdefault("MPLCONFIGDIR", sys.argv[2])
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
path = sys.argv[1]
nb = json.load(open(path, encoding="utf-8"))
ns, n = {"__name__": "__main__"}, 0
for cell in nb["cells"]:
    if cell["cell_type"] != "code":
        continue
    n += 1
    src, outputs, buf = "".join(cell["source"]), [], io.StringIO()
    try:
        tree = ast.parse(src)
        last = tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        with contextlib.redirect_stdout(buf):
            exec(compile(ast.Module(tree.body[:-1] if last else tree.body, []), f"<cell {n}>", "exec"), ns)
            val = eval(compile(ast.Expression(last.value), f"<cell {n}>", "eval"), ns) if last else None
        if buf.getvalue():
            outputs.append({"output_type": "stream", "name": "stdout", "text": buf.getvalue()})
        for num in plt.get_fignums():
            b = io.BytesIO()
            plt.figure(num).savefig(b, format="png", dpi=100, bbox_inches="tight")
            outputs.append({"output_type": "display_data", "data": {"image/png": base64.b64encode(b.getvalue()).decode(), "text/plain": "<Figure>"}, "metadata": {}})
        plt.close("all")
        if val is not None and not type(val).__module__.startswith("matplotlib"):
            data = {"text/plain": repr(val)}
            if hasattr(val, "_repr_html_"):
                data["text/html"] = val._repr_html_()
            outputs.append({"output_type": "execute_result", "execution_count": n, "data": data, "metadata": {}})
    except Exception as e:
        outputs.append({"output_type": "error", "ename": type(e).__name__, "evalue": str(e), "traceback": traceback.format_exc().splitlines()})
    cell["outputs"], cell["execution_count"] = outputs, n
json.dump(nb, open(path, "w", encoding="utf-8"), indent=1)
"""


def _cell(kind, text):
    c = {"cell_type": kind, "id": uuid.uuid4().hex[:8], "metadata": {}, "source": text.splitlines(keepends=True)}
    if kind == "code":
        c.update(outputs=[], execution_count=None)
    return c


def notebook(data_file, value=None, group=None):
    p = Path(data_file).resolve()
    read = f'pd.read_excel(r"{p}")' if p.suffix.lower() in (".xlsx", ".xls") else f'pd.read_csv(r"{p}")'
    cells = [
        _cell("markdown", f"# Analysis of {p.name}\n\nMade by AI PC: run all cells to refresh."),
        _cell(
            "code",
            f'import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = {read}\nprint(f"{{len(df)}} rows, {{len(df.columns)}} columns")\ndf.head()',
        ),
        _cell("markdown", "## Summary statistics"),
        _cell("code", "df.describe(include='all').T"),
    ]
    pick = (
        f"value = {value!r}\ngroup = {group!r}"
        if value and group
        else "value = next(c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]))\n"
        "group = next((c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])), None)"
    )
    cells += [
        _cell("markdown", "## Total by group"),
        _cell("code", pick + "\ntotals = df.groupby(group)[value].sum().sort_values(ascending=False)\ntotals.to_frame(f'Total {value}')"),
        _cell("markdown", "## Chart"),
        _cell(
            "code",
            "ax = totals.plot(kind='bar', title=f'Total {value} by {group}', color='#1a73e8')\nax.set_ylabel(value)\nplt.tight_layout()\nplt.show()",
        ),
    ]
    return {
        "cells": cells,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def execute(path, timeout=300):
    mpl = STATE / "matplotlib"
    mpl.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, "-c", RUNNER, str(path), str(mpl)],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if r.returncode:
        raise RuntimeError(f"the notebook runner failed: {r.stderr.strip()[-300:]}")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check(nb):
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    errors = [o for c in code for o in c["outputs"] if o["output_type"] == "error"]
    charts = [o for c in code for o in c["outputs"] if "image/png" in o.get("data", {})]
    return [
        ("every cell ran without an error", not errors and all(c["execution_count"] for c in code)),
        ("the chart is in the notebook", bool(charts)),
    ], errors


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    if not re.search(r"\b(?:jupyter|notebook|ipynb|colab)\b", text, re.I):
        return None
    f = find_file(text, ctx, {".xlsx", ".csv", ".xls"})
    if not f:
        return None
    m = re.search(r"\btotal\s+(\w+)\s+by\s+(\w+)", text, re.I)
    return {"op": "notebook", "file": f, "value": m.group(1) if m else None, "group": m.group(2) if m else None}


def run(op, ctx):
    out = Path(ctx["out"]) / "notebooks"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{Path(op['file']).stem}_analysis.ipynb"
    dest.write_text(json.dumps(notebook(op["file"], op.get("value"), op.get("group")), indent=1), encoding="utf-8")
    nb = execute(dest)
    checks, errors = check(nb)
    bad = [w for w, ok in checks if not ok]
    return f"Notebook {dest} ({len(nb['cells'])} cells, run here with pandas and matplotlib; opens finished in Jupyter, VS Code or Colab). " + (
        "Checked: " + "; ".join(w for w, _ in checks) + "."
        if not bad
        else "NOT right: " + "; ".join(bad) + "".join(f" ({e['ename']}: {e['evalue']})" for e in errors[:2])
    )
