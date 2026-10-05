"""KiCad (10.0.6 in tools/kicad, signed by KiCad Services Corp.; unpacked by 7-Zip without the 3D models): circuits from
words (an LED with its resistor, a voltage divider, a 555 blinker; values worked out by harness/apps/circuits.py) written
as a real KiCad project (.kicad_pro + .kicad_sch, KiCad's own library symbols embedded), then checked and exported by
kicad-cli: the Electrical Rules Check, the netlist KiCad reads from the drawing, a bill of materials (CSV) and a PDF.
Checked: ERC finds no errors, and KiCad's netlist joins exactly the pins the circuit says, part for part.
Also, for a board someone made: Gerbers and drill files zipped for a PCB maker, after KiCad's Design Rules Check.

  'kicad schematic red led on 5v'   'kicad voltage divider 12v to 5v'   'kicad 555 blinker 2 hz on 9v'   'kicad gerbers for board.kicad_pcb'
"""
import copy
import csv
import json
import os
import re
import uuid
import zipfile
from pathlib import Path

from ..config import ROOT
from . import circuits
from . import sexpr as S

NAME, LABEL = "kicad", "KiCad: schematics from words (LED, divider, 555) with ERC, netlist, BOM, PDF; Gerbers for boards"
EXAMPLES = ["kicad schematic red led on 5v", "kicad voltage divider 12v to 5v", "kicad 555 blinker 2 hz on 9v", "kicad gerbers for board.kicad_pcb"]
HOME = ROOT / "tools" / "kicad"
CLI = HOME / "bin" / "kicad-cli.exe"
SYMBOLS = HOME / "share" / "kicad" / "symbols"
_LIBS = {}


def env():
    home = HOME / "home"
    for p in ("config", "documents", "cache"):
        (home / p).mkdir(parents=True, exist_ok=True)
    cfg = home / "config" / "10.0"
    cfg.mkdir(parents=True, exist_ok=True)
    for table in ("sym-lib-table", "fp-lib-table"):  # KiCad's own default library tables (they point at its bundled libraries)
        if not (cfg / table).exists():
            (cfg / table).write_bytes((HOME / "share" / "kicad" / "template" / table).read_bytes())
    return dict(os.environ, KICAD_CONFIG_HOME=str(home / "config"), KICAD_DOCUMENTS_HOME=str(home / "documents"), KICAD_CACHE_HOME=str(home / "cache"),
                KICAD10_SYMBOL_DIR=str(SYMBOLS), KICAD10_FOOTPRINT_DIR=str(HOME / "share" / "kicad" / "footprints"))


def cli(*args, timeout=180):
    from .. import hidden_desktop
    return hidden_desktop.run([str(CLI), *map(str, args)], timeout=timeout, env=env())


def lib_symbol(lib_id):
    """KiCad's own symbol, flattened (a derived symbol takes its parent's drawing and pins) and named 'Lib:Name'."""
    lib, name = lib_id.split(":")
    if lib not in _LIBS:
        _LIBS[lib] = S.parse((SYMBOLS / f"{lib}.kicad_sym").read_text(encoding="utf-8"))
    syms = {s[1]: s for s in S.find(_LIBS[lib], "symbol")}
    sym = copy.deepcopy(syms[name])
    ext = S.first(sym, "extends")
    if ext:
        parent = copy.deepcopy(syms[ext[1]])
        own = {p[1]: p for p in S.find(sym, "property")}
        body = [i for i in parent if not (isinstance(i, list) and i and i[0] == "property")]
        props = [own.get(p[1], p) for p in S.find(parent, "property")] + [p for k, p in own.items() if k not in {q[1] for q in S.find(parent, "property")}]
        sym = body[:2] + [i for i in body[2:] if not (isinstance(i, list) and i[0] == "symbol")] + props + \
            [i for i in body if isinstance(i, list) and i and i[0] == "symbol"]
        for sub in S.find(sym, "symbol"):
            sub[1] = S.Str(str(sub[1]).replace(ext[1] + "_", name + "_", 1))
    sym[1] = S.Str(lib_id)
    return sym


def pins(sym):
    """{pin number: (x, y, angle)} in the symbol's own coordinates (y up); the angle points from the pin's end into the body."""
    out = {}
    for p in S.walk(sym, "pin"):
        num = S.first(p, "number")
        at = S.first(p, "at")
        if num and at:
            out[str(num[1])] = (float(at[1]), float(at[2]), int(float(at[3])) if len(at) > 3 else 0)
    return out


OUTWARD = {0: (-1, 0, 180, "right"), 180: (1, 0, 0, "left"), 90: (0, 1, 270, "right"), 270: (0, -1, 90, "left")}  # sheet dx, dy, label angle, justify
STUB = 5.08


def _u():
    return S.Str(str(uuid.uuid4()))


def _prop(name, value, x, y, hide=False, angle=0):
    eff = ["effects", ["font", ["size", 1.27, 1.27]]] + ([["justify", "left"]] if not hide else []) + ([["hide", "yes"]] if hide else [])
    return ["property", S.Str(name), S.Str(value), ["at", round(x, 2), round(y, 2), angle], eff]


def schematic(circ, project):
    """A .kicad_sch tree: symbols placed on KiCad's grid, every pin joined to its net by a label at the pin's end."""
    sheet = _u()
    parts = list(circ["parts"]) + [(f"#FLG0{i + 1}", "power:PWR_FLAG", "PWR_FLAG", "", {"1": net}) for i, net in enumerate(circ.get("power_flags", []))]
    libs, placed, labels = {}, [], []
    x, flag_x = 25.4, 25.4
    for ref, lib_id, value, foot, conns in parts:
        if lib_id not in libs:
            libs[lib_id] = lib_symbol(lib_id)
        sym = libs[lib_id]
        pp = pins(sym)
        width = max([abs(px) for px, _, _ in pp.values()] + [5.08])
        virtual = ref.startswith("#")
        if virtual:  # power flags in a row under the circuit
            flag_x += 15.24
            px0, y = flag_x, 127.0
        else:
            x += width + STUB + 22.86
            x = round(x / 2.54) * 2.54
            px0, y = x, 88.9
            x += width + STUB
        x0 = px0
        top = max([py for _, py, _ in pp.values()] + [3.81])
        node = ["symbol", ["lib_id", S.Str(lib_id)], ["at", x0, y, 0], ["unit", 1], ["exclude_from_sim", "no"], ["in_bom", "no" if virtual else "yes"],
                ["on_board", "no" if virtual else "yes"], ["dnp", "no"], ["uuid", _u()],
                _prop("Reference", ref, x0 + 2.54, y - top - 5.08, hide=virtual), _prop("Value", value, x0 + 2.54, y - top - 2.54),
                _prop("Footprint", foot, x0, y, hide=True), _prop("Datasheet", "~", x0, y, hide=True)]
        node += [["pin", S.Str(n), ["uuid", _u()]] for n in pp]
        node.append(["instances", ["project", S.Str(project), ["path", S.Str("/" + sheet), ["reference", S.Str(ref)], ["unit", 1]]]])
        placed.append(node)
        for num, net in conns.items():  # a short wire out of the pin, the net's label at its far end
            px, py, ang = pp[num]
            dx, dy, lang, just = OUTWARD.get(ang % 360, (0, 1, 270, "right"))
            ex, ey = round(x0 + px, 2), round(y - py, 2)
            lx, ly = round(ex + dx * STUB, 2), round(ey + dy * STUB, 2)
            labels.append(["wire", ["pts", ["xy", ex, ey], ["xy", lx, ly]], ["stroke", ["width", 0], ["type", "default"]], ["uuid", _u()]])
            labels.append(["label", S.Str(net), ["at", lx, ly, lang], ["fields_autoplaced", "yes"],
                           ["effects", ["font", ["size", 1.27, 1.27]], ["justify", just, "bottom"]], ["uuid", _u()]])
    title = ["title_block", ["title", S.Str(circ["title"])], ["company", S.Str("AI PC")]] + \
        [["comment", i + 1, S.Str(n)] for i, n in enumerate(circ.get("notes", [])[:4])]
    return ["kicad_sch", ["version", 20250114], ["generator", S.Str("eeschema")], ["generator_version", S.Str("9.0")], ["uuid", S.Str(sheet)],
            ["paper", S.Str("A4")], title, ["lib_symbols"] + list(libs.values())] + placed + labels + \
        [["sheet_instances", ["path", S.Str("/"), ["page", S.Str("1")]]], ["embedded_fonts", "no"]]


def netlist_nets(path):
    """{net name: {(ref, pin)}} from KiCad's own netlist."""
    tree = S.parse(Path(path).read_text(encoding="utf-8"))
    out = {}
    for net in S.walk(tree, "net"):
        name = S.first(net, "name")
        nodes = {(str(S.first(n, "ref")[1]), str(S.first(n, "pin")[1])) for n in S.find(net, "node")}
        if name and nodes:
            out[str(name[1]).lstrip("/")] = nodes
    return out


def check_schematic(circ, folder, stem):
    sch = folder / f"{stem}.kicad_sch"
    erc_file, net_file, bom_file, pdf_file = (folder / f"{stem}{x}" for x in ("_erc.json", ".net", "_bom.csv", ".pdf"))
    cli("sch", "erc", "--format", "json", "--severity-all", "-o", erc_file, sch)
    cli("sch", "export", "netlist", "--format", "kicadsexpr", "-o", net_file, sch)
    cli("sch", "export", "bom", "-o", bom_file, sch)
    cli("sch", "export", "pdf", "-o", pdf_file, sch)
    problems = {"error": [], "warning": []}
    if erc_file.exists():
        rep = json.loads(erc_file.read_text(encoding="utf-8"))
        for sheet in rep.get("sheets", []):
            for v in sheet.get("violations", []):
                problems.setdefault(v.get("severity", "error"), []).append(v.get("description", v.get("type", "?")))
    want = {}
    for ref, _, _, _, conns in circ["parts"]:
        for num, net in conns.items():
            want.setdefault(net, set()).add((ref, num))
    got = {k: {n for n in v if not n[0].startswith("#")} for k, v in (netlist_nets(net_file).items() if net_file.exists() else [])}
    got = {k: v for k, v in got.items() if v}
    bom = list(csv.DictReader(bom_file.read_text(encoding="utf-8").splitlines())) if bom_file.exists() else []
    refs_in_bom = {r.strip() for row in bom for r in (row.get("Refs") or row.get("Reference") or "").split(",") if r.strip()}
    from pypdf import PdfReader
    pdf_pages = len(PdfReader(str(pdf_file)).pages) if pdf_file.exists() else 0
    checks = [("KiCad's Electrical Rules Check finds no errors" + (f" ({len(problems['warning'])} warnings)" if problems["warning"] else ""),
               erc_file.exists() and not problems["error"]),
              ("KiCad's netlist joins exactly the pins the circuit says (" + ", ".join(f"{k}: {len(v)} pins" for k, v in sorted(want.items())) + ")",
               {k: v for k, v in got.items()} == want),
              ("the bill of materials lists every part", refs_in_bom >= {p[0] for p in circ["parts"]}),
              ("the PDF schematic was made", pdf_pages >= 1)]
    return checks, problems, (erc_file, net_file, bom_file, pdf_file)


def gerbers(board, folder):
    """DRC, then Gerbers + drill files zipped for a PCB maker."""
    board = Path(board).resolve()
    out = folder / f"{board.stem}_gerbers"
    out.mkdir(parents=True, exist_ok=True)
    drc = folder / f"{board.stem}_drc.json"
    cli("pcb", "drc", "--format", "json", "--severity-error", "-o", drc, board)
    cli("pcb", "export", "gerbers", "-o", str(out) + os.sep, board)
    cli("pcb", "export", "drill", "-o", str(out) + os.sep, board)
    errors = []
    if drc.exists():
        rep = json.loads(drc.read_text(encoding="utf-8"))
        errors = [v.get("description", "?") for v in rep.get("violations", []) + rep.get("unconnected_items", [])]
    files = sorted(p for p in out.iterdir() if p.is_file())
    zpath = folder / f"{board.stem}_gerbers.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.name)
    return files, errors, zpath


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bkicad\b|\bschematic\b|\bgerbers?\b|\bpcb\b", c):
        return None
    board = find_file(text, ctx, {".kicad_pcb"})
    if board:
        return {"op": "gerbers", "board": board}
    circ = circuits.from_words(c)
    return {"op": "schematic", "words": c} if circ else None


def run(op, ctx):
    if not CLI.exists():
        return "KiCad is not in tools/kicad."
    out = Path(ctx["out"]) / "kicad"
    out.mkdir(parents=True, exist_ok=True)
    if op["op"] == "gerbers":
        files, errors, zpath = gerbers(op["board"], out)
        names = {p.name.lower() for p in files}
        need = {"top copper": ("-f_cu", ".gtl"), "bottom copper": ("-b_cu", ".gbl"), "solder mask": ("_mask", ".gts"), "board outline": ("edge_cuts", ".gm1"),
                "drill holes": (".drl",)}
        have = [k for k, keys in need.items() if any(any(key in n for key in keys) for n in names)]
        missing = [k for k in need if k not in have]
        return (f"Gerbers and drill files for {Path(op['board']).name}: {zpath} ({len(files)} files; {', '.join(have)}), ready to upload to a PCB maker. " +
                ("KiCad's Design Rules Check found no errors." if not errors else f"KiCad's DRC found {len(errors)} problem(s): {'; '.join(errors[:3])} - fix them in KiCad first.") +
                (f" NOT right: missing {', '.join(missing)}." if missing else " Checked: every layer a maker needs is in the zip."))
    circ = circuits.from_words(op["words"])
    stem = re.sub(r"[^\w-]+", "_", circ["title"]).strip("_")
    folder = out / stem
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.kicad_pro").write_text(json.dumps({"meta": {"filename": f"{stem}.kicad_pro", "version": 1}}, indent=2), encoding="utf-8")
    (folder / f"{stem}.kicad_sch").write_text(S.dump(schematic(circ, stem)) + "\n", encoding="utf-8")
    checks, problems, files = check_schematic(circ, folder, stem)
    bad = [w for w, ok in checks if not ok]
    parts = ", ".join(f"{p[0]} {p[2]}" for p in circ["parts"])
    return (f"KiCad project '{circ['title']}': {folder / (stem + '.kicad_pro')} (open it in KiCad). Parts: {parts}. " + " ".join(n + "." for n in circ["notes"]) +
            f" Files: schematic PDF, netlist, BOM CSV, ERC report. " +
            ("Checked by kicad-cli: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + f" (ERC errors: {problems['error'][:3]})."))
