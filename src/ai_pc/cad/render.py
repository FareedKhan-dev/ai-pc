"""A DXF drawing made visible without a CAD program: ezdxf draws it as SVG at the sheet's paper size and scale, and a
headless browser prints that to a vector PDF (true scale: 1:100 measures 1:100 on paper) and a PNG preview.

  files = render(doc, sheet, out_stem)    -> {"svg", "pdf", "png", "seconds"}
"""
import time
from pathlib import Path

from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg

from ai_pc.core import headless


def to_svg(doc, sheet):
    msp = doc.modelspace()
    backend = svg.SVGBackend()
    cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE, color_policy=config.ColorPolicy.COLOR,
                               lineweight_policy=config.LineweightPolicy.ABSOLUTE, min_lineweight=0.12)
    Frontend(RenderContext(doc), backend, config=cfg).draw_layout(msp, finalize=True)
    pw, ph = sheet["paper_mm"]
    page = layout.Page(pw, ph, layout.Units.mm, margins=layout.Margins.all(0))
    settings = layout.Settings(fit_page=False, scale=25.4 / sheet["scale"])  # drawing inches to paper millimetres at 1:scale
    return backend.get_string(page, settings=settings)


def render(doc, sheet, out_stem, png=True, pdf=True):
    t0 = time.perf_counter()
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    s = to_svg(doc, sheet)
    svg_p = out_stem.with_suffix(".svg")
    svg_p.write_text(s, encoding="utf-8")
    pw, ph = sheet["paper_mm"]
    html = (f'<!doctype html><html><head><meta charset="utf-8"><style>@page{{size:{pw}mm {ph}mm;margin:0}}html,body{{margin:0;padding:0;'
            f'width:{pw}mm;height:{ph}mm;overflow:hidden;background:#fff}}svg{{display:block;width:{pw}mm;height:{ph}mm}}</style></head>'
            f'<body>{s[s.index("<svg"):]}</body></html>')
    html_p = out_stem.with_suffix(".html")
    html_p.write_text(html, encoding="utf-8")
    out = {"svg": str(svg_p)}
    if pdf:
        out["pdf"] = headless.pdf(html_p, out_stem.with_suffix(".pdf"))["path"]
    if png:
        px_w = round(pw / 25.4 * 96)
        out["png"] = headless.png(html_p, out_stem.with_suffix(".png"), (px_w, round(ph / 25.4 * 96)), scale=1.3)["path"]
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out
