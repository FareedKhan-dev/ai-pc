"""Microsoft Visio drawings (.vsdx) written by code: flowcharts, org charts and mind maps from words, laid out by the
diagrams program, then saved in Visio's own file format (Open Packaging zip with Visio 2013 XML: pages, shapes with
their geometry, connectors glued to the shapes, labels). Visio is not installed here, so the file is checked by another
program that reads Visio files: LibreOffice (in tools/libreoffice) opens it and turns it into a PDF, which must hold
every box label and line count.

  'visio flowchart: Start -> Take order -> Paid? -> Pack -> Ship -> End'   'visio org chart: CEO > CTO, CFO; CTO > Dev lead'
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

NAME, LABEL = "visio", "Microsoft Visio: flowcharts, org charts and mind maps written as .vsdx; read back by LibreOffice's Visio reader"
EXAMPLES = ["visio flowchart: Start -> Take order -> Paid? -> Pack -> Ship -> End", "visio org chart: CEO > CTO, CFO; CTO > Dev lead"]
NS = "http://schemas.microsoft.com/office/visio/2012/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PX = 96.0  # draw.io units per inch

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>
<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>
<Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>
<Override PartName="/visio/windows.xml" ContentType="application/vnd.ms-visio.windows+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""
DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/>
<Relationship Id="rId2" Type="http://schemas.microsoft.com/visio/2010/relationships/windows" Target="windows.xml"/>
</Relationships>"""
PAGES_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/>
</Relationships>"""
DOCUMENT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<VisioDocument xmlns="{NS}" xmlns:r="{REL}" xml:space="preserve">
<DocumentSettings TopPage="0" DefaultTextStyle="0" DefaultLineStyle="0" DefaultFillStyle="0" DefaultGuideStyle="0">
<GlueSettings>9</GlueSettings><SnapSettings>65847</SnapSettings><SnapExtensions>34</SnapExtensions><SnapAngles/><DynamicGridEnabled>1</DynamicGridEnabled>
<ProtectStyles>0</ProtectStyles><ProtectShapes>0</ProtectShapes><ProtectMasters>0</ProtectMasters><ProtectBkgnds>0</ProtectBkgnds>
</DocumentSettings>
<Colors><ColorEntry IX="0" RGB="#000000"/><ColorEntry IX="1" RGB="#FFFFFF"/></Colors>
<FaceNames><FaceName NameU="Calibri" UnicodeRanges="-536859905 -1073732485 9 0" CharSets="536871423 0" Panos="2 15 5 2 2 2 4 3 2 4" Flags="325"/></FaceNames>
<StyleSheets>
<StyleSheet ID="0" NameU="No Style" Name="No Style">
<Cell N="EnableLineProps" V="1"/><Cell N="EnableFillProps" V="1"/><Cell N="EnableTextProps" V="1"/><Cell N="HideForApply" V="0"/>
<Cell N="LineWeight" V="0.01388888888888889"/><Cell N="LineColor" V="0"/><Cell N="LinePattern" V="1"/><Cell N="Rounding" V="0"/>
<Cell N="BeginArrow" V="0"/><Cell N="EndArrow" V="0"/><Cell N="BeginArrowSize" V="2"/><Cell N="EndArrowSize" V="2"/><Cell N="LineCap" V="0"/>
<Cell N="FillForegnd" V="1"/><Cell N="FillBkgnd" V="0"/><Cell N="FillPattern" V="1"/><Cell N="ShdwPattern" V="0"/>
<Cell N="LeftMargin" V="0.05555555555555555"/><Cell N="RightMargin" V="0.05555555555555555"/><Cell N="TopMargin" V="0.05555555555555555"/>
<Cell N="BottomMargin" V="0.05555555555555555"/><Cell N="VerticalAlign" V="1"/><Cell N="TextBkgnd" V="0"/>
<Section N="Character"><Row IX="0"><Cell N="Font" V="Calibri"/><Cell N="Color" V="0"/><Cell N="Style" V="0"/><Cell N="Size" V="0.1388888888888889"/></Row></Section>
<Section N="Paragraph"><Row IX="0"><Cell N="HorzAlign" V="1"/></Row></Section>
</StyleSheet>
</StyleSheets>
</VisioDocument>"""
WINDOWS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Windows xmlns="{NS}" xmlns:r="{REL}" ClientWidth="1280" ClientHeight="800" xml:space="preserve">
<Window ID="0" WindowType="Drawing" WindowState="1073741824" ClientWidth="1280" ClientHeight="800" Page="0" ViewScale="-1" ViewCenterX="0" ViewCenterY="0"/>
</Windows>"""


def _num(v):
    return f"{v:.6f}".rstrip("0").rstrip(".") or "0"


def cell(n, v, f=None):
    return f'<Cell N="{n}" V="{_num(v) if isinstance(v, float) else v}"' + (f' F="{f}"' if f else "") + "/>"


def color(style, key, default):
    m = re.search(rf"{key}=(#[0-9A-Fa-f]{{6}})", style or "")
    return m.group(1).upper() if m else default


def read_drawio(path):
    """Vertices {id: (label, x, y, w, h, shape, fill, line)} and edges [(source, target, label, [(x, y) waypoints])] from a .drawio file."""
    root = ET.parse(path).getroot()
    vertices, edges = {}, []
    for c in root.iter("mxCell"):
        g = c.find("mxGeometry")
        label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c.get("value") or "")).strip()
        style = c.get("style") or ""
        if c.get("vertex") == "1" and g is not None:
            shape = "diamond" if "rhombus" in style else "ellipse" if "ellipse" in style else "rect"
            vertices[c.get("id")] = (
                label,
                float(g.get("x", 0)),
                float(g.get("y", 0)),
                float(g.get("width", 120)),
                float(g.get("height", 60)),
                shape,
                color(style, "fillColor", "#FFFFFF"),
                color(style, "strokeColor", "#333333"),
            )
        elif c.get("edge") == "1":
            pts = [(float(p.get("x", 0)), float(p.get("y", 0))) for p in (g.iter("mxPoint") if g is not None else []) if p.get("as") is None]
            edges.append((c.get("source"), c.get("target"), label, pts))
    return vertices, edges


def vsdx(vertices, edges, dest, title):
    xs = [v[1] for v in vertices.values()] + [v[1] + v[3] for v in vertices.values()]
    ys = [v[2] for v in vertices.values()] + [v[2] + v[4] for v in vertices.values()]
    x0, y0, x1, y1 = min(xs) - PX / 2, min(ys) - PX / 2, max(xs) + PX / 2, max(ys) + PX / 2
    width, height = (x1 - x0) / PX, (y1 - y0) / PX
    to_in = lambda x, y: ((x - x0) / PX, height - (y - y0) / PX)  # noqa: E731 (y grows down in draw.io, up in Visio)
    ids, shapes, connects = {}, [], []
    for n, (vid, (label, x, y, w, h, shape, fill, line)) in enumerate(vertices.items(), 1):
        ids[vid] = n
        cx, cy = to_in(x + w / 2, y + h / 2)
        W, H = w / PX, h / PX
        if shape == "ellipse":
            geo = (
                f'<Row T="Ellipse" IX="1">{cell("X", W / 2)}{cell("Y", H / 2)}{cell("A", W)}{cell("B", H / 2)}{cell("C", W / 2)}{cell("D", H)}</Row>'
            )
        else:
            pts = [(W / 2, 0), (W, H / 2), (W / 2, H), (0, H / 2), (W / 2, 0)] if shape == "diamond" else [(0, 0), (W, 0), (W, H), (0, H), (0, 0)]
            geo = "".join(
                f'<Row T="{"MoveTo" if i == 0 else "LineTo"}" IX="{i + 1}">{cell("X", px)}{cell("Y", py)}</Row>' for i, (px, py) in enumerate(pts)
            )
        shapes.append(
            f'<Shape ID="{n}" NameU="{shape.title()} {n}" Name="{shape.title()} {n}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">'
            f"{cell('PinX', cx)}{cell('PinY', cy)}{cell('Width', W)}{cell('Height', H)}{cell('LocPinX', W / 2, 'Width*0.5')}"
            f"{cell('LocPinY', H / 2, 'Height*0.5')}{cell('Angle', 0.0)}{cell('FillForegnd', fill)}{cell('LineColor', line)}"
            f'<Section N="Geometry" IX="0">{cell("NoFill", 0)}{cell("NoLine", 0)}{cell("NoShow", 0)}{geo}</Section>'
            f"<Text>{escape(label)}</Text></Shape>"
        )
    n = len(vertices)
    for src, dst, label, way in edges:
        if src not in vertices or dst not in vertices:
            continue
        n += 1
        a, b = vertices[src], vertices[dst]
        pts = [(a[1] + a[3] / 2, a[2] + a[4] / 2)] + way + [(b[1] + b[3] / 2, b[2] + b[4] / 2)]

        def edge_of(v, toward):  # where the line from the box centre toward a point leaves the box
            cx, cy, hw, hh = v[1] + v[3] / 2, v[2] + v[4] / 2, v[3] / 2, v[4] / 2
            dx, dy = toward[0] - cx, toward[1] - cy
            if dx == 0 and dy == 0:
                return cx, cy
            k = 1 / max(abs(dx) / hw if hw else 0, abs(dy) / hh if hh else 0)
            return cx + dx * k, cy + dy * k

        pts[0], pts[-1] = edge_of(a, pts[1]), edge_of(b, pts[-2])
        page = [to_in(*p) for p in pts]
        bx0, by0 = min(p[0] for p in page), min(p[1] for p in page)
        bw, bh = max(p[0] for p in page) - bx0, max(p[1] for p in page) - by0
        geo = "".join(
            f'<Row T="{"MoveTo" if i == 0 else "LineTo"}" IX="{i + 1}">{cell("X", px - bx0)}{cell("Y", py - by0)}</Row>'
            for i, (px, py) in enumerate(page)
        )
        shapes.append(
            f'<Shape ID="{n}" NameU="Connector {n}" Name="Connector {n}" Type="Shape" LineStyle="0" FillStyle="0" TextStyle="0">'
            f"{cell('PinX', bx0 + bw / 2)}{cell('PinY', by0 + bh / 2)}{cell('Width', bw)}{cell('Height', bh)}"
            f"{cell('LocPinX', bw / 2, 'Width*0.5')}{cell('LocPinY', bh / 2, 'Height*0.5')}"
            f"{cell('BeginX', page[0][0])}{cell('BeginY', page[0][1])}{cell('EndX', page[-1][0])}{cell('EndY', page[-1][1])}"
            f"{cell('ObjType', 2)}{cell('EndArrow', 13)}{cell('LineColor', '#333333')}"
            f'<Section N="Geometry" IX="0">{cell("NoFill", 1)}{cell("NoLine", 0)}{cell("NoShow", 0)}{geo}</Section>'
            + (f"<Text>{escape(label)}</Text>" if label else "")
            + "</Shape>"
        )
        connects += [
            f'<Connect FromSheet="{n}" FromCell="BeginX" FromPart="9" ToSheet="{ids[src]}" ToCell="PinX" ToPart="3"/>',
            f'<Connect FromSheet="{n}" FromCell="EndX" FromPart="12" ToSheet="{ids[dst]}" ToCell="PinX" ToPart="3"/>',
        ]
    page1 = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<PageContents xmlns="{NS}" xmlns:r="{REL}" xml:space="preserve">'
        f"<Shapes>{''.join(shapes)}</Shapes>" + (f"<Connects>{''.join(connects)}</Connects>" if connects else "") + "</PageContents>"
    )
    pages = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Pages xmlns="{NS}" xmlns:r="{REL}" xml:space="preserve">'
        f'<Page ID="0" NameU="{escape(title)}" Name="{escape(title)}" ViewScale="-1" ViewCenterX="{_num(width / 2)}" ViewCenterY="{_num(height / 2)}">'
        f'<PageSheet LineStyle="0" FillStyle="0" TextStyle="0">{cell("PageWidth", width)}{cell("PageHeight", height)}{cell("ShdwOffsetX", 0.125)}'
        f"{cell('ShdwOffsetY', -0.125)}{cell('PageScale', 1.0)}{cell('DrawingScale', 1.0)}{cell('DrawingSizeType', 0)}{cell('DrawingScaleType', 0)}"
        f"{cell('InhibitSnap', 0)}{cell('PageLockReplace', 0)}{cell('PageLockDuplicate', 0)}{cell('UIVisibility', 0)}{cell('ShdwType', 0)}"
        f'{cell("PrintPageOrientation", 2 if width > height else 1)}</PageSheet><Rel r:id="rId1"/></Page></Pages>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + escape(title) + "</dc:title><dc:creator>AI PC</dc:creator></cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>Microsoft Visio</Application><Template></Template></Properties>"
    )
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", ROOT_RELS),
            ("docProps/core.xml", core),
            ("docProps/app.xml", app),
            ("visio/document.xml", DOCUMENT),
            ("visio/_rels/document.xml.rels", DOC_RELS),
            ("visio/windows.xml", WINDOWS),
            ("visio/pages/pages.xml", pages),
            ("visio/pages/_rels/pages.xml.rels", PAGES_RELS),
            ("visio/pages/page1.xml", page1),
        ]:
            z.writestr(name, data)
    return len(vertices), sum(1 for s in shapes if "Connector" in s)


def parse(text, ctx):
    c = text.lower()
    if not re.search(r"\bvisio\b|\.vsdx\b", c):
        return None
    from ai_pc.apps import diagrams

    rest = re.sub(r"^\s*(?:ms\s+|microsoft\s+)?visio\s*|\s*(?:in|as|for)\s+(?:ms\s+|microsoft\s+)?visio\b", "", text, flags=re.I).strip()
    op = diagrams.parse(rest, ctx)
    return dict(op, op="visio") if op else None


def run(op, ctx):
    from ai_pc.apps import diagrams, libreoffice

    out = (Path(ctx["out"]) / "visio").resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = {"flow": "flowchart", "tree": "org_chart", "mind": "mind_map"}[op["kind"]]
    made = diagrams.make(op["kind"], op["spec"], out / "layout", name, op.get("title", ""))
    src = next(p for p in made["files"] if p.suffix == ".drawio")
    vertices, edges = read_drawio(src)
    dest = out / f"{name}.vsdx"
    shapes, lines = vsdx(vertices, edges, dest, op.get("title") or name.replace("_", " ").title())
    with zipfile.ZipFile(dest) as z:
        parts_ok = all(ET.fromstring(z.read(n)) is not None for n in z.namelist() if n.endswith((".xml", ".rels")))
    pdf = out / f"{name}.pdf"
    pdf.unlink(missing_ok=True)
    checks = [(f"the .vsdx holds {shapes} shapes and {lines} glued connectors, every part well-formed XML", parts_ok and shapes == len(vertices))]
    if libreoffice.soffice():
        libreoffice.convert(dest, "pdf", out)
        from pypdf import PdfReader

        words = re.sub(r"\s+", " ", " ".join(pg.extract_text() or "" for pg in PdfReader(str(pdf)).pages).lower()) if pdf.exists() else ""
        labels = [v[0] for v in vertices.values() if v[0]]
        found = sum(1 for lab in labels if re.sub(r"\s+", " ", lab.lower()) in words)
        checks.append(
            (f"LibreOffice's Visio reader opens it: its PDF shows {found} of {len(labels)} box labels", pdf.exists() and found == len(labels))
        )
    bad = [w for w, good in checks if not good]
    return (
        f"Visio drawing {dest} (a {name.replace('_', ' ')}; opens in Microsoft Visio, LibreOffice Draw and draw.io)"
        + (f", with a PDF of it {pdf.name}" if pdf.exists() else "")
        + ". "
        + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ".")
    )
