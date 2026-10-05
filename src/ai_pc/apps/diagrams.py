"""Diagrams from words: flowcharts, org charts and mind maps, laid out by code and drawn as SVG, then PNG and PDF by
headless Chrome, plus a .drawio file that opens for editing in draw.io (diagrams.net, desktop or web).

  'flowchart: Start -> Take order -> In stock? -yes-> Pack -> Ship -> End; In stock? -no-> Order from supplier -> Pack'
  'org chart: CEO > Sales Manager, Accounts Manager; Sales Manager > Ali, Sara'
  'mind map: Marketing: Social media (Facebook, Instagram, TikTok), Ads, SEO, Email'
Checks: every name is drawn, no two boxes overlap, every arrow joins two boxes, the picture is not blank, and the
draw.io file reads back with the same boxes and arrows.
"""
import html
import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET

NAME, LABEL = "diagrams", "Diagrams: flowcharts, org charts, mind maps (SVG, PNG, PDF, draw.io)"
EXAMPLES = ["flowchart: Start -> Take order -> In stock? -yes-> Pack -> Ship -> End; In stock? -no-> Order from supplier -> Pack",
            "org chart: CEO > Sales Manager, Accounts Manager; Sales Manager > Ali, Sara", "mind map: Marketing: Social media (Facebook, Instagram), Ads, SEO"]
FONT, CHAR = 15, 8.2  # px; average width of a character of Segoe UI at 15 px
W_MAX, PAD, GAP_X, GAP_Y = 190, 14, 46, 64
COLORS = {"box": "#e8f0fe", "edge": "#1a73e8", "decision": "#fef7e0", "end": "#e6f4ea", "text": "#1f2937", "root": "#1a73e8"}


def wrap(text, width=W_MAX - 2 * PAD):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur + " " + w) * CHAR > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return lines + [cur] if cur else lines or [""]


def box_size(text, shape):
    lines = wrap(text)
    w = max(110, min(W_MAX, max(len(x) for x in lines) * CHAR + 2 * PAD))
    h = len(lines) * (FONT + 5) + 2 * PAD - 5
    if shape == "diamond":
        w, h = w * 1.45, h * 1.6
    return w, h, lines


# ---------------------------------------------------------------- reading the words
def read_flow(spec):
    nodes, edges = {}, []
    for chain in re.split(r";|\n", spec):
        parts = re.split(r"\s*(?:-(?!>)\s*([^>]+?)\s*->|->)\s*", chain.strip())  # 'A -> B' and 'A -yes-> B'
        names, labels = parts[0::2], parts[1::2]
        names = [n.strip(" .") for n in names if n is not None]
        for n in names:
            if n and n not in nodes:
                low = n.lower()
                nodes[n] = "diamond" if n.endswith("?") else "terminal" if low in ("start", "end", "begin", "finish", "stop", "done") else "box"
        for i in range(len(names) - 1):
            if names[i] and names[i + 1]:
                edges.append((names[i], names[i + 1], (labels[i] or "").strip() if i < len(labels) else ""))
    return nodes, edges


def read_tree(spec):
    nodes, edges = {}, []
    for part in re.split(r";|\n", spec):
        if ">" not in part:
            continue
        boss, team = part.split(">", 1)
        boss = boss.strip(" .")
        nodes.setdefault(boss, "box")
        for t in team.split(","):
            t = t.strip(" .")
            if t:
                nodes.setdefault(t, "box")
                edges.append((boss, t, ""))
    return nodes, edges


def read_mind(spec):
    m = re.match(r"\s*([^:]+):\s*(.+)$", spec, re.S)
    if not m:
        return {}, []
    root = m.group(1).strip()
    nodes, edges = {root: "root"}, []
    for branch in re.findall(r"[^,(]+(?:\([^)]*\))?", m.group(2)):
        b = branch.strip(" ,.")
        if not b:
            continue
        leaves = re.search(r"\(([^)]*)\)", b)
        name = re.sub(r"\s*\(.*\)", "", b).strip()
        nodes[name] = "branch"
        edges.append((root, name, ""))
        for leaf in (leaves.group(1).split(",") if leaves else []):
            leaf = leaf.strip()
            if leaf:
                nodes[f"{leaf}"] = "leaf"
                edges.append((name, leaf, ""))
    return nodes, edges


# ---------------------------------------------------------------- laying out
def layout_layers(nodes, edges):
    """Top to bottom: each box one layer below the furthest box that leads to it (loops ignored), boxes in a layer
    ordered by where their parents are."""
    order = list(nodes)
    succ = {n: [b for a, b, _ in edges if a == n] for n in nodes}
    back, state = set(), {}

    def walk(n):  # a link to a box still being walked is a loop back
        state[n] = 1
        for m in succ[n]:
            if state.get(m) == 1:
                back.add((n, m))
            elif m not in state:
                walk(m)
        state[n] = 2
    for n in order:
        if n not in state:
            walk(n)
    preds = {n: [a for a, b, _ in edges if b == n and (a, b) not in back] for n in nodes}
    layer = {}

    def depth(n, seen=()):
        if n not in layer:
            layer[n] = max((depth(p, seen + (n,)) + 1 for p in preds[n] if p not in seen), default=0)
        return layer[n]
    for n in order:
        depth(n)
    sizes = {n: box_size(n, nodes[n] if nodes[n] == "diamond" else "box") for n in nodes}
    # an arrow across several rows gets a waypoint in each row between, so it runs in its own lane, not through a box
    chain, up = {}, {n: list(preds[n]) for n in nodes}
    for i, (a, b, _) in enumerate(edges):
        if (a, b) in back or layer[b] - layer[a] < 2:
            continue
        prev, pts = a, []
        for li in range(layer[a] + 1, layer[b]):
            v = f"\x00{i}:{li}"
            layer[v], sizes[v], up[v] = li, (26, 10, []), [prev]
            pts.append(v)
            prev = v
        up[b] = [prev if p == a else p for p in up[b]]
        chain[(a, b)] = pts
    rows = {}
    for n in list(order) + [v for pts in chain.values() for v in pts]:
        rows.setdefault(layer[n], []).append(n)
    pos, y = {}, 30
    for li in sorted(rows):
        row = rows[li]
        if li:
            row.sort(key=lambda n: sum(pos[p][0] for p in up[n] if p in pos) / max(1, len([p for p in up[n] if p in pos])))
        total = sum(sizes[n][0] for n in row) + GAP_X * (len(row) - 1)
        x = -total / 2
        h = max(sizes[n][1] for n in row)
        for n in row:
            w = sizes[n][0]
            pos[n] = (x + w / 2, y + h / 2)
            x += w + GAP_X
        y += h + GAP_Y
    via = {k: [pos.pop(v) for v in pts] for k, pts in chain.items()}
    for pts in chain.values():
        for v in pts:
            sizes.pop(v)
    return pos, sizes, via


def layout_tree(nodes, edges):
    kids = {n: [] for n in nodes}
    has_parent = set()
    for a, b, _ in edges:
        kids[a].append(b)
        has_parent.add(b)
    roots = [n for n in nodes if n not in has_parent] or list(nodes)[:1]
    sizes = {n: box_size(n, "box") for n in nodes}
    pos, cursor = {}, [0.0]
    depth_h = {}

    def depth(n, d):
        depth_h[d] = max(depth_h.get(d, 0), sizes[n][1])
        for k in kids[n]:
            depth(k, d + 1)

    for r in roots:
        depth(r, 0)
    ys = {0: 30 + depth_h[0] / 2}
    for d in range(1, len(depth_h)):
        ys[d] = ys[d - 1] + depth_h[d - 1] / 2 + GAP_Y + depth_h[d] / 2

    level = {}

    def place(n, d):
        level[n] = d
        if not kids[n]:
            w = sizes[n][0]
            pos[n] = (cursor[0] + w / 2, ys[d])
            cursor[0] += w + GAP_X
        else:
            for k in kids[n]:
                place(k, d + 1)
            xs = [pos[k][0] for k in kids[n]]
            pos[n] = ((min(xs) + max(xs)) / 2, ys[d])
    for r in roots:
        place(r, 0)

    def subtree(n):
        yield n
        for k in kids[n]:
            yield from subtree(k)
    for d in sorted(set(level.values())):  # a wide parent over narrow children: move it (and all under it) right
        row = sorted((n for n in level if level[n] == d), key=lambda n: pos[n][0])
        for a, b in zip(row, row[1:]):
            need = (pos[a][0] + sizes[a][0] / 2 + GAP_X) - (pos[b][0] - sizes[b][0] / 2)
            if need > 0:
                for s in subtree(b):
                    pos[s] = (pos[s][0] + need, pos[s][1])
                for c in row[row.index(b) + 1:]:
                    if c not in set(subtree(b)):
                        for s in subtree(c):
                            pos[s] = (pos[s][0] + need, pos[s][1])
    return pos, sizes


def layout_mind(nodes, edges):
    root = next(n for n, k in nodes.items() if k == "root")
    branches = [b for a, b, _ in edges if a == root]
    leaves = {b: [l for a, l, _ in edges if a == b] for b in branches}
    sizes = {n: box_size(n, "box") for n in nodes}
    pos = {root: (0.0, 0.0)}
    weights = [max(1, len(leaves[b])) for b in branches]
    total = sum(weights) or 1
    ang = -math.pi / 2
    r1 = 230 + 12 * len(branches)
    for b, wgt in zip(branches, weights):
        span = 2 * math.pi * wgt / total
        mid = ang + span / 2
        pos[b] = (r1 * math.cos(mid) * 1.35, r1 * math.sin(mid))
        n = len(leaves[b])
        for i, leaf in enumerate(leaves[b]):
            a = ang + span * (i + 0.5) / n
            r2 = r1 + 190
            pos[leaf] = (r2 * math.cos(a) * 1.45, r2 * math.sin(a) * 1.05)
        ang += span
    return pos, sizes


def overlaps(pos, sizes, margin=4):
    names = list(pos)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            (ax, ay), (bx, by) = pos[a], pos[b]
            if abs(ax - bx) * 2 < sizes[a][0] + sizes[b][0] + margin and abs(ay - by) * 2 < sizes[a][1] + sizes[b][1] + margin:
                out.append((a, b))
    return out


def spread(pos, sizes, rounds=60):
    """Push apart boxes that overlap (a mind map's leaves on a crowded side)."""
    for _ in range(rounds):
        bad = overlaps(pos, sizes, 12)
        if not bad:
            return pos
        for a, b in bad:
            (ax, ay), (bx, by) = pos[a], pos[b]
            dx, dy = bx - ax or 1, by - ay or 1
            d = math.hypot(dx, dy)
            pos[b] = (bx + dx / d * 18, by + dy / d * 18)
            pos[a] = (ax - dx / d * 18, ay - dy / d * 18)
    return pos


# ---------------------------------------------------------------- drawing
def svg(kind, nodes, edges, pos, sizes, title="", via=None):
    via = via or {}
    xs = [pos[n][0] - sizes[n][0] / 2 for n in nodes] + [pos[n][0] + sizes[n][0] / 2 for n in nodes]
    ys = [pos[n][1] - sizes[n][1] / 2 for n in nodes] + [pos[n][1] + sizes[n][1] / 2 for n in nodes]
    loops = kind != "mind" and any(pos[b][1] <= pos[a][1] for a, b, _ in edges)
    x0, y0 = min(xs) - 40, min(ys) - (70 if title else 40)
    w, h = max(xs) - x0 + (90 if loops else 40), max(ys) - y0 + 40
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
           'font-family="Segoe UI, Arial, sans-serif">', f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{COLORS["edge"]}"/></marker></defs>']
    if title:
        out.append(f'<text x="{x0 + w / 2:.0f}" y="{y0 + 38:.0f}" text-anchor="middle" font-size="22" font-weight="700" fill="{COLORS["text"]}">'
                   f'{html.escape(title)}</text>')
    for a, b, label in edges:
        (ax, ay), (bx, by) = pos[a], pos[b]
        if kind == "mind":
            out.append(f'<path d="M{ax:.1f},{ay:.1f} C{(ax + bx) / 2:.1f},{ay:.1f} {(ax + bx) / 2:.1f},{by:.1f} {bx:.1f},{by:.1f}" stroke="{COLORS["edge"]}" '
                       'stroke-width="2.5" fill="none" opacity="0.7"/>')
            continue
        sy, ty = ay + sizes[a][1] / 2, by - sizes[b][1] / 2
        if (a, b) in via:  # through its waypoints, in its own lane
            pts = [(ax, sy)] + via[(a, b)] + [(bx, ty)]
            d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f} " + " ".join(
                f"C{p[0]:.1f},{(p[1] + q[1]) / 2:.1f} {q[0]:.1f},{(p[1] + q[1]) / 2:.1f} {q[0]:.1f},{q[1]:.1f}" for p, q in zip(pts, pts[1:]))
            out.append(f'<path d="{d}" stroke="{COLORS["edge"]}" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
            if label:
                out.append(f'<text x="{(pts[0][0] + pts[1][0]) / 2 + 8:.1f}" y="{(pts[0][1] + pts[1][1]) / 2:.1f}" font-size="13" fill="{COLORS["edge"]}" '
                           f'font-weight="600">{html.escape(label)}</text>')
            continue
        if by <= ay:  # a loop back up: round the side
            side = max(pos[a][0] + sizes[a][0] / 2, pos[b][0] + sizes[b][0] / 2) + 40
            d = f"M{ax + sizes[a][0] / 2:.1f},{ay:.1f} H{side:.1f} V{by:.1f} H{bx + sizes[b][0] / 2:.1f}"
        elif kind == "tree":
            mid = (sy + ty) / 2
            d = f"M{ax:.1f},{sy:.1f} V{mid:.1f} H{bx:.1f} V{ty:.1f}"
        else:
            d = f"M{ax:.1f},{sy:.1f} C{ax:.1f},{(sy + ty) / 2:.1f} {bx:.1f},{(sy + ty) / 2:.1f} {bx:.1f},{ty:.1f}"
        out.append(f'<path d="{d}" stroke="{COLORS["edge"]}" stroke-width="2" fill="none" marker-end="url(#arrow)"/>')
        if label:
            lx, ly = (ax + bx) / 2 + 8, (sy + ty) / 2
            out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="13" fill="{COLORS["edge"]}" font-weight="600">{html.escape(label)}</text>')
    for n, shape in nodes.items():
        x, y = pos[n]
        w, h, lines = sizes[n]
        fill = COLORS["decision"] if shape == "diamond" else COLORS["end"] if shape == "terminal" else COLORS["root"] if shape == "root" else COLORS["box"]
        color = "#ffffff" if shape == "root" else COLORS["text"]
        if shape == "diamond":
            out.append(f'<polygon data-name="{html.escape(n)}" points="{x:.1f},{y - h / 2:.1f} {x + w / 2:.1f},{y:.1f} {x:.1f},{y + h / 2:.1f} {x - w / 2:.1f},{y:.1f}" '
                       f'fill="{fill}" stroke="#c9a227" stroke-width="2"/>')
        else:
            rx = h / 2 if shape in ("terminal", "root", "leaf") else 10
            out.append(f'<rect data-name="{html.escape(n)}" x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx:.1f}" fill="{fill}" '
                       f'stroke="{COLORS["edge"] if shape != "leaf" else "#9aa0a6"}" stroke-width="{2 if shape != "leaf" else 1.2}"/>')
        top = y - (len(lines) - 1) * (FONT + 5) / 2 + FONT / 3
        for i, line in enumerate(lines):
            out.append(f'<text x="{x:.1f}" y="{top + i * (FONT + 5):.1f}" text-anchor="middle" font-size="{FONT + (3 if shape == "root" else 0)}" '
                       f'font-weight="{700 if shape in ("root", "branch") else 500}" fill="{color}">{html.escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def drawio(kind, nodes, edges, pos, sizes, via=None):
    """The same diagram as draw.io's file (mxGraphModel), to open and edit in draw.io; an arrow routed round boxes keeps its
    waypoints, so draw.io draws it in the same lane."""
    via = via or {}
    root = ET.Element("mxfile", host="AI PC")
    diag = ET.SubElement(root, "diagram", name="Page-1", id="aipc")
    model = ET.SubElement(diag, "mxGraphModel", grid="1", page="1")
    cells = ET.SubElement(model, "root")
    ET.SubElement(cells, "mxCell", id="0")
    ET.SubElement(cells, "mxCell", id="1", parent="0")
    ids = {}
    style = {"diamond": "rhombus;whiteSpace=wrap;html=1;fillColor=#fef7e0;strokeColor=#c9a227;",
             "terminal": "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#e6f4ea;strokeColor=#1a73e8;",
             "root": "ellipse;whiteSpace=wrap;html=1;fillColor=#1a73e8;fontColor=#ffffff;fontStyle=1;",
             "leaf": "rounded=1;arcSize=50;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#9aa0a6;"}
    for i, (n, shape) in enumerate(nodes.items(), 2):
        ids[n] = str(i)
        x, y = pos[n]
        w, h, _ = sizes[n]
        c = ET.SubElement(cells, "mxCell", id=ids[n], value=n, style=style.get(shape, "rounded=1;whiteSpace=wrap;html=1;fillColor=#e8f0fe;strokeColor=#1a73e8;"),
                          vertex="1", parent="1")
        ET.SubElement(c, "mxGeometry", x=f"{x - w / 2:.0f}", y=f"{y - h / 2:.0f}", width=f"{w:.0f}", height=f"{h:.0f}", **{"as": "geometry"})
    for j, (a, b, label) in enumerate(edges):
        st = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;" if kind != "mind" else "curved=1;endArrow=none;html=1;"
        lane = None
        if (a, b) in via and via[(a, b)]:  # out of the side, down its own lane, into the target's same side: never across a box
            lane = via[(a, b)][0][0]
            side = 1 if lane >= pos[a][0] else 0
            st += f"exitX={side};exitY=0.5;exitDx=0;exitDy=0;entryX={side};entryY=0.5;entryDx=0;entryDy=0;"
        c = ET.SubElement(cells, "mxCell", id=f"e{j}", value=label, style=st, edge="1", parent="1", source=ids[a], target=ids[b])
        g = ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})
        if lane is not None:
            arr = ET.SubElement(g, "Array", **{"as": "points"})
            for y in (pos[a][1], pos[b][1]):
                ET.SubElement(arr, "mxPoint", x=f"{lane:.0f}", y=f"{y:.0f}")
    return ET.tostring(root, encoding="unicode")


def make(kind, spec, out, name="diagram", title=""):
    nodes, edges = {"flow": read_flow, "tree": read_tree, "mind": read_mind}[kind](spec)
    if not nodes:
        raise ValueError("no boxes found in the words")
    got = {"flow": layout_layers, "tree": layout_tree, "mind": layout_mind}[kind](nodes, edges)
    pos, sizes, via = got if len(got) == 3 else (*got, {})
    if kind == "mind":
        pos = spread(pos, sizes)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    s = svg(kind, nodes, edges, pos, sizes, title, via)
    (out / f"{name}.svg").write_text(s, encoding="utf-8")
    page = out / f"{name}.html"
    vb = re.search(r'width="(\d+)" height="(\d+)"', s)
    w, h = int(vb.group(1)), int(vb.group(2))
    page.write_text(f"<!doctype html><html><head><meta charset='utf-8'><style>@page{{size:{w}px {h}px;margin:0}}html,body{{margin:0;background:#fff}}"
                    f"</style></head><body>{s}</body></html>", encoding="utf-8")
    from ai_pc.core import headless
    headless.png(page, out / f"{name}.png", size=(w, h), wait_ms=400, lane="apps")
    headless.pdf(page, out / f"{name}.pdf", wait_ms=400, lane="apps")
    (out / f"{name}.drawio").write_text(drawio(kind, nodes, edges, pos, sizes, via), encoding="utf-8")
    return {"nodes": nodes, "edges": edges, "pos": pos, "sizes": sizes, "files": [out / f"{name}.{e}" for e in ("png", "pdf", "svg", "drawio")]}


def check(r):
    out = []
    svg_text = Path(r["files"][2]).read_text(encoding="utf-8")
    drawn = set(re.findall(r'data-name="([^"]*)"', svg_text))
    out.append(("every name drawn", all(html.escape(n) in drawn for n in r["nodes"])))
    out.append(("no boxes overlap", not overlaps(r["pos"], r["sizes"])))
    out.append(("every arrow joins two boxes", all(a in r["pos"] and b in r["pos"] for a, b, _ in r["edges"])))
    from PIL import Image, ImageStat
    im = Image.open(r["files"][0]).convert("L")
    out.append(("the picture is not blank", ImageStat.Stat(im).stddev[0] > 8))
    x = ET.parse(r["files"][3]).getroot()
    out.append(("the draw.io file reads back", len(x.findall(".//mxCell[@vertex='1']")) == len(r["nodes"]) and
                len(x.findall(".//mxCell[@edge='1']")) == len(r["edges"])))
    return out


def parse(text, ctx):
    m = re.match(r"^\s*(?:make|draw|create)?\s*(?:a|an|the)?\s*(flow ?chart|process diagram|org(?:anisation|anization)? ?chart|mind ?map)\s*(?:of|for)?\s*"
                 r"(?:'([^']*)'|\"([^\"]*)\")?\s*:\s*(.+)$", text, re.I | re.S)
    if not m:
        return None
    word = m.group(1).lower().replace(" ", "")
    kind = "flow" if word.startswith(("flow", "process")) else "tree" if word.startswith("org") else "mind"
    return {"op": "diagram", "kind": kind, "spec": m.group(4), "title": m.group(2) or m.group(3) or ""}


def run(op, ctx):
    name = {"flow": "flowchart", "tree": "org_chart", "mind": "mind_map"}[op["kind"]]
    r = make(op["kind"], op["spec"], Path(ctx["out"]) / "diagrams", name, op.get("title", ""))
    checks = check(r)
    bad = [w for w, ok in checks if not ok]
    return (f"{name.replace('_', ' ').title()} with {len(r['nodes'])} boxes and {len(r['edges'])} links: " + ", ".join(str(f) for f in r["files"]) +
            (". Checked: " + ", ".join(w for w, _ in checks) if not bad else ". NOT right: " + ", ".join(bad)) +
            ". The .drawio file opens for editing in draw.io (app.diagrams.net).")
