"""Power BI reports as a Power BI Project (PBIP, the format Power BI Desktop saves for Git): a CSV/Excel sheet becomes a
semantic model (model.bim: a table with typed columns loaded by a Power Query from a copy of the sheet, DAX measures:
a total per number column and a row count) and a report page (a card with the first total, a column chart of it by the
first text column, a table of everything) in the PBIR folder format. Power BI Desktop is not installed here (it cannot
be unpacked portably), so the files are checked otherwise: every report file validates against Microsoft's published
JSON schemas (github.com/microsoft/json-schemas, cached in tools/powerbi/schemas), every field a visual uses exists in
the model, and the totals the card will show are worked out from the sheet. Open the .pbip in Power BI Desktop.

  'power bi report from sales.xlsx'   'powerbi dashboard from orders.csv'
"""
import json
import re
import shutil
import urllib.request
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "powerbi", "Power BI: a sheet into a Power BI Project (model, DAX measures, a report page), checked against Microsoft's schemas"
EXAMPLES = ["power bi report from sales.xlsx", "powerbi dashboard from orders.csv"]
MS = "https://developer.microsoft.com/json-schemas/fabric/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/fabric/"
CACHE = ROOT / "tools" / "powerbi" / "schemas"
SCHEMAS = {"pbip": MS + "pbip/pbipProperties/1.0.0/schema.json", "pbir": MS + "item/report/definitionProperties/2.0.0/schema.json",
           "pbism": MS + "item/semanticModel/definitionProperties/1.0.0/schema.json", "version": MS + "item/report/definition/versionMetadata/1.0.0/schema.json",
           "report": MS + "item/report/definition/report/3.3.0/schema.json", "pages": MS + "item/report/definition/pagesMetadata/1.1.0/schema.json",
           "page": MS + "item/report/definition/page/2.1.0/schema.json", "visual": MS + "item/report/definition/visualContainer/2.12.0/schema.json"}
TYPES = {"bigint": ("int64", "Int64.Type", "#,0"), "numeric": ("double", "type number", "#,0.00"), "timestamp": ("dateTime", "type datetime", "General Date"),
         "text": ("string", "type text", None)}


def schema(uri):
    """A published schema, fetched once from Microsoft's GitHub repository and kept in tools/powerbi/schemas."""
    rel = uri.split("/json-schemas/fabric/", 1)[1].split("#")[0]
    path = CACHE / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(RAW + rel, headers={"User-Agent": "Mozilla/5.0"})
        path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return json.loads(path.read_text(encoding="utf-8"))


def validate(doc):
    """[problems] of a JSON document against the schema its $schema names (its $refs fetched the same way)."""
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7
    registry = Registry(retrieve=lambda uri: Resource.from_contents(schema(uri), default_specification=DRAFT7))
    s = schema(doc["$schema"])
    cls = jsonschema.validators.validator_for(s, default=jsonschema.Draft7Validator)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message[:120]}" for e in cls(s, registry=registry).iter_errors(doc)]


def field(kind, table, name):
    return {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def projection(kind, table, name):
    return {"field": field(kind, table, name), "queryRef": f"{table}.{name}", "nativeQueryRef": name}


def visual(name, vtype, roles, x, y, w, h, z):
    return {"$schema": SCHEMAS["visual"], "name": name, "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": z},
            "visual": {"visualType": vtype, "query": {"queryState": {role: {"projections": projs} for role, projs in roles.items()}},
                       "drillFilterOtherVisuals": True}}


def m_query(path, table_cols, sheet_kind):
    types = ", ".join('{"' + c + '", ' + TYPES[k][1] + "}" for c, k in table_cols)
    p = str(path).replace('"', '""')
    if sheet_kind == "csv":
        src = f'Csv.Document(File.Contents("{p}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv])'
    else:
        src = f'Excel.Workbook(File.Contents("{p}"), null, true){{0}}[Data]'
    return ["let", f"    Source = {src},", "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
            f"    Typed = Table.TransformColumnTypes(Promoted, {{{types}}})", "in", "    Typed"]


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bpower\s?bi\b|\.pbip\b", c):
        return None
    f = find_file(text, ctx, {".csv", ".xlsx"})
    return {"op": "report", "file": f} if f else None


def run(op, ctx):
    from . import stats
    from .postgres import infer
    src = Path(op["file"]).resolve()
    data = stats.sheet(src)
    if not data:
        return f"No columns found in {src.name}."
    name = re.sub(r"[^A-Za-z0-9]+", " ", src.stem).title().replace(" ", "") or "Report"
    table = name
    out = (Path(ctx["out"]) / "powerbi" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    (out / "Data").mkdir(parents=True)
    copy = out / "Data" / src.name
    shutil.copyfile(src, copy)
    cols = [(c, infer([None if v is None else str(v) for v in vals])) for c, vals in data.items()]
    numbers = sorted((c for c, k in cols if k in ("bigint", "numeric")),  # money-like columns first: the card shows the first
                     key=lambda c: 0 if re.search(r"amount|sales|revenue|total|price|value|profit|cost", c, re.I) else 1)
    texts = [c for c, k in cols if k == "text"]
    measures = [{"name": f"Total {c}", "expression": f"SUM('{table}'[{c}])", "formatString": "#,0"} for c in numbers] + \
               [{"name": "Rows", "expression": f"COUNTROWS('{table}')", "formatString": "#,0"}]
    model = {"name": name, "compatibilityLevel": 1567,
             "model": {"culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3", "sourceQueryCulture": "en-US",
                       "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
                       "tables": [{"name": table,
                                   "columns": [dict({"name": c, "dataType": TYPES[k][0], "sourceColumn": c, "summarizeBy": "none" if k != "bigint" and k != "numeric" else "sum"},
                                                    **({"formatString": TYPES[k][2]} if TYPES[k][2] else {})) for c, k in cols],
                                   "partitions": [{"name": table, "mode": "import", "source": {"type": "m", "expression": m_query(copy, cols, "csv" if src.suffix.lower() == ".csv" else "xlsx")}}],
                                   "measures": measures}],
                       "annotations": [{"name": "PBI_QueryOrder", "value": json.dumps([table])}]}}
    sm, rp = out / f"{name}.SemanticModel", out / f"{name}.Report"
    first = measures[0]["name"]
    visuals = [visual("card1", "card", {"Values": [projection("Measure", table, first)]}, 40, 40, 360, 160, 0)]
    if texts and numbers:
        visuals.append(visual("chart1", "clusteredColumnChart", {"Category": [projection("Column", table, texts[0])], "Y": [projection("Measure", table, first)]},
                              440, 40, 800, 320, 1000))
    visuals.append(visual("table1", "tableEx", {"Values": [projection("Column", table, c) for c, _ in cols]}, 40, 400, 1200, 300, 2000))
    files = {out / f"{name}.pbip": {"$schema": SCHEMAS["pbip"], "version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}],
                                    "settings": {"enableAutoRecovery": True}},
             rp / "definition.pbir": {"$schema": SCHEMAS["pbir"], "version": "4.0", "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}},
             rp / "definition" / "version.json": {"$schema": SCHEMAS["version"], "version": "2.0.0"},
             rp / "definition" / "report.json": {"$schema": SCHEMAS["report"], "themeCollection": {}},
             rp / "definition" / "pages" / "pages.json": {"$schema": SCHEMAS["pages"], "pageOrder": ["page1"], "activePageName": "page1"},
             rp / "definition" / "pages" / "page1" / "page.json": {"$schema": SCHEMAS["page"], "name": "page1", "displayName": name,
                                                                   "displayOption": "FitToPage", "height": 720, "width": 1280},
             sm / "definition.pbism": {"$schema": SCHEMAS["pbism"], "version": "1.0", "settings": {}}}
    for v in visuals:
        files[rp / "definition" / "pages" / "page1" / "visuals" / v["name"] / "visual.json"] = v
    for path, doc in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (sm / "model.bim").write_text(json.dumps(model, indent=2), encoding="utf-8")
    (out / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    problems = []
    for path, doc in files.items():
        problems += [f"{path.relative_to(out)}: {p}" for p in validate(json.loads(path.read_text(encoding="utf-8")))]
    known = {("Column", table, c) for c, _ in cols} | {("Measure", table, m["name"]) for m in measures}
    used = [(k, f[k]["Expression"]["SourceRef"]["Entity"], f[k]["Property"]) for v in visuals for role in v["visual"]["query"]["queryState"].values()
            for p in role["projections"] for f in [p["field"]] for k in f]
    missing = [u for u in used if u not in known]
    totals = {c: sum(float(str(v).replace(",", "")) for v in data[c] if v not in (None, "")) for c in numbers}
    checks = [(f"all {len(files)} report and project files validate against Microsoft's published schemas", not problems),
              (f"every field the {len(visuals)} visuals use ({len(used)}) is a column or measure of the model", not missing),
              (f"the model has {len(cols)} typed columns and {len(measures)} DAX measures, loaded from {copy.name} by Power Query", bool(cols))]
    bad = [w for w, good in checks if not good]
    card = f"the card will show {first} = {totals[numbers[0]]:,.0f}" if numbers else f"the card will show Rows = {len(next(iter(data.values())))}"
    return (f"Power BI Project {out / (name + '.pbip')} (open it in Power BI Desktop; the data is a copy in Data/, refresh after changing it): "
            f"model {name} with " + ", ".join(m["name"] for m in measures) + f"; a page with a card, " + ("a column chart by " + texts[0] + ", " if texts and numbers else "") +
            f"a table; {card}. " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " +
                                    "; ".join((problems + [str(m) for m in missing])[:5])))
