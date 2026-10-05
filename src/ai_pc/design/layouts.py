"""Designs as HTML and CSS: each kind has a few layouts (styles); text sits in boxes that shrink it to fit, every piece
carries data-role so the page can measure itself (see render.MEASURE), and print kinds bleed past the trim.

  pages = build(spec)   -> [(name, html), ...]   one HTML page per printed side (a card has a front and a back)
"""
import html as H
import re
from pathlib import Path

from ai_pc.design.kinds import FONTS, GRADIENTS, KINDS, SCRIPT_FONT, palette, size_of

PX_PER_MM = 96 / 25.4
ICONS = {
    "phone": '<path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    "email": '<rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 7l9 6 9-6" fill="none" stroke="currentColor" stroke-width="2"/>',
    "web": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18" fill="none" stroke="currentColor" stroke-width="2"/>',
    "address": '<path d="M12 21s-7-6.8-7-12a7 7 0 0 1 14 0c0 5.2-7 12-7 12z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="9" r="2.5" fill="currentColor"/>',
    "time": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "date": '<rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 10h18M8 3v4M16 3v4" fill="none" stroke="currentColor" stroke-width="2"/>',
}


def esc(s):
    return H.escape(str(s or ""))


def icon(name, size="1em"):
    return f'<svg class="ic" viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true">{ICONS[name]}</svg>'


def initials(text):
    words = [w for w in re.findall(r"[A-Za-z]+", text or "") if w.lower() not in ("and", "of", "the", "&")]
    return ("".join(w[0] for w in words[:2]) or "AB").upper()


def monogram(text, fg, bg, shape="circle"):
    i = esc(initials(text))
    sh = '<circle cx="50" cy="50" r="48"' if shape == "circle" else '<rect x="2" y="2" width="96" height="96" rx="14"'
    return (f'<svg viewBox="0 0 100 100" class="mono" data-role="logo">{sh} fill="{bg}"/>'
            f'<text x="50" y="50" dy="0.35em" text-anchor="middle" font-family="Bahnschrift, Segoe UI" font-weight="700" font-size="{44 if len(i) > 1 else 52}" '
            f'fill="{fg}" letter-spacing="1">{i}</text></svg>')


def logo_html(spec, fg, bg, shape="circle"):
    if spec.get("logo"):
        return f'<img class="logo" data-role="logo" src="{Path(spec["logo"]).resolve().as_uri()}" alt="">'
    return monogram(spec["fields"].get("company") or spec["fields"].get("brand") or spec["fields"].get("name") or spec["fields"].get("org"), fg, bg, shape)


def qr_html(data, fg="#000000", bg="#FFFFFF"):
    import segno
    q = segno.make(data, error="m")
    svg = q.svg_inline(scale=1, border=2, dark=fg, light=bg, omitsize=True)
    return f'<div class="qr" data-role="qr" data-qr="{esc(data)}">{svg}</div>'


def T(role, text, cls="", fit=None, tag="div", style=""):
    """A text box: data-role for measuring, data-fit for the smallest size (px) it may shrink to."""
    if not text:
        return ""
    f = f' data-fit="{fit}"' if fit else ""
    s = f' style="{style}"' if style else ""
    return f'<{tag} class="t {cls}" data-role="{role}"{f}{s}>{esc(text)}</{tag}>'


def contact_rows(f, keys=("phone", "email", "web", "address"), cls="row", fit=None):
    out = []
    for k in keys:
        v = f.get(k)
        if v:
            out.append(f'<div class="{cls}">{icon(k)}<span class="t" data-role="{k}"{f" data-fit={chr(34)}{fit}{chr(34)}" if fit else ""}>{esc(v)}</span></div>')
    return "".join(out)


def bg_css(spec, p):
    g = spec.get("gradient")
    if g in GRADIENTS:
        a, b = GRADIENTS[g]
        return f"linear-gradient(135deg, {a} 0%, {b} 100%)"
    return p["bg"]


# ---------------------------------------------------------------- the page around a design
BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#fff}
body{-webkit-print-color-adjust:exact;print-color-adjust:exact;font-family:var(--body),'Segoe UI',Arial,sans-serif;color:var(--fg)}
.page{position:relative;overflow:hidden;width:var(--pw);height:var(--ph);background:var(--bg);page-break-after:always;break-after:page}
.page:last-child{page-break-after:auto;break-after:auto}
.t{overflow:clip;overflow-clip-margin:.3em}
.ic{flex:none;color:var(--accent-text)}
.row{display:flex;align-items:center;gap:.55em;white-space:nowrap}
.row .t{overflow:hidden;text-overflow:clip}
.qr svg{width:100%;height:100%;display:block}
.mono{display:block;width:100%;height:100%}
img.logo{display:block;width:100%;height:100%;object-fit:contain}
"""


def wrap(spec, inner, css, page_style=""):
    """One page of the design as a full HTML document (fonts, palette, the page box)."""
    w, h, unit, bleed, safe = size_of(spec)
    p = palette(spec)
    head, body = FONTS.get(spec.get("style"), FONTS["modern"])
    head = spec.get("font_head") or head
    body = spec.get("font_body") or body
    pw, ph = (f"{w + 2 * bleed:.3f}mm", f"{h + 2 * bleed:.3f}mm") if unit == "mm" else (f"{w}px", f"{h}px")
    page_rule = f"@page{{size:{pw} {ph};margin:0}}" if unit == "mm" else f"@page{{size:{w}px {h}px;margin:0}}"
    vars_ = (f":root{{--pw:{pw};--ph:{ph};--bg:{bg_css(spec, p)};--fg:{p['fg']};--accent:{p['accent']};--muted:{p['muted']};--light:{p['light']};"
             f"--ink:{p['ink']};--sub:color-mix(in srgb,{p['ink']} 68%,#ffffff);--accent-ink:color-mix(in srgb,{p['accent']} 55%,#000000);--accent-text:{p.get('accent_text', p['accent'])};--head:'{head}';--body:'{body}';--script:'{SCRIPT_FONT}';--bleed:{bleed}mm;--safe:{safe}{'mm' if unit == 'mm' else 'px'}}}")
    sizes = "".join(f'.page [data-role="{r}"]{{font-size:{px}px}}' for r, px in (spec.get("sizes") or {}).items())  # 'make the name bigger'
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(spec['kind'])}</title><style>{page_rule}{vars_}{BASE_CSS}{css}{sizes}</style></head>"
            f"<body><div class='page' style='{page_style}'>{inner}</div></body></html>")


# ---------------------------------------------------------------- visiting cards (88.9 x 50.8 mm + 3 mm bleed)
def card(spec):
    f, style, p = spec["fields"], spec.get("style", "modern"), palette(spec)
    b = KINDS["card"]["bleed"]
    s = b + KINDS["card"]["safe"]  # content starts inside the safe margin
    qr = f.get("qr") or (f.get("web") if spec.get("qr") else None)
    front_css = back_css = ""
    if style == "classic":
        front_css = f"""
.page{{background:var(--light);color:var(--ink)}}
.frame{{position:absolute;left:{b + 2.2}mm;top:{b + 2.2}mm;right:{b + 2.2}mm;bottom:{b + 2.2}mm;border:.25mm solid var(--accent)}}
.box{{position:absolute;left:{s + 1}mm;right:{s + 1}mm;top:{s + 1.5}mm;bottom:{s + 1}mm;display:flex;flex-direction:column;align-items:center;text-align:center}}
.company{{font-family:var(--head);font-size:7.5pt;letter-spacing:.32em;text-transform:uppercase;color:var(--accent-ink);width:100%;white-space:nowrap}}
.name{{font-family:var(--body);font-size:15pt;margin-top:3.2mm;width:100%;white-space:nowrap;line-height:1.15}}
.title{{font-family:var(--body);font-style:italic;font-size:8pt;color:var(--sub);width:100%;white-space:nowrap;margin-top:.6mm}}
.rule{{width:14mm;height:0;border-top:.3mm solid var(--accent);margin:2.4mm 0 2mm}}
.lines{{font-size:6.8pt;line-height:1.55;color:var(--ink);width:100%}}
.lines .row{{justify-content:center}}
.ic{{width:2.4mm;height:2.4mm}}"""
        front = (f"<div class='frame'></div><div class='box'>{T('company', f.get('company'), 'company', 6)}{T('name', f.get('name'), 'name', 9)}"
                 f"{T('title', f.get('title'), 'title', 6)}<div class='rule'></div><div class='lines'>{contact_rows(f, fit=6)}</div></div>")
    elif style == "bold":
        front_css = f"""
.page{{background:var(--bg);color:var(--fg)}}
.slash{{position:absolute;right:-6mm;top:-10mm;width:40mm;height:40mm;background:var(--accent);transform:rotate(35deg);opacity:.95}}
.box{{position:absolute;left:{s + .5}mm;top:{s + 1}mm;right:{s}mm;bottom:{s}mm;display:flex;flex-direction:column}}
.name{{font-family:var(--head);font-size:15pt;line-height:1.05;width:60mm;white-space:nowrap;letter-spacing:.01em}}
.title{{font-size:7pt;letter-spacing:.22em;text-transform:uppercase;color:var(--accent-text);width:60mm;white-space:nowrap;margin-top:1.3mm;font-weight:600}}
.company{{font-size:7pt;color:var(--muted);width:60mm;white-space:nowrap;margin-top:.8mm}}
.lines{{margin-top:auto;font-size:6.6pt;line-height:1.6;color:var(--fg);width:62mm}}
.ic{{width:2.3mm;height:2.3mm}}"""
        front = (f"<div class='slash'></div><div class='box'>{T('name', f.get('name'), 'name', 9)}{T('title', f.get('title'), 'title', 5.5)}"
                 f"{T('company', f.get('company'), 'company', 5.5)}<div class='lines'>{contact_rows(f, fit=5.8)}</div></div>")
    else:  # modern: white card, a colour band bleeding off the left, name and contacts on the right
        front_css = f"""
.page{{background:#FFFFFF;color:var(--ink)}}
.band{{position:absolute;left:0;top:0;bottom:0;width:{b + 24}mm;background:var(--bg)}}
.logo-box{{position:absolute;left:{b + 5}mm;top:50%;width:14mm;height:14mm;transform:translateY(-50%)}}
.box{{position:absolute;left:{b + 29}mm;right:{s}mm;top:{s + .8}mm;bottom:{s}mm;display:flex;flex-direction:column}}
.name{{font-family:var(--head);font-weight:600;font-size:13.5pt;line-height:1.1;color:var(--ink);width:100%;white-space:nowrap}}
.title{{font-size:7pt;letter-spacing:.12em;text-transform:uppercase;color:var(--sub);width:100%;white-space:nowrap;margin-top:.9mm}}
.rule{{width:10mm;border-top:.45mm solid var(--accent);margin:2.2mm 0 0}}
.company{{font-family:var(--head);font-size:7pt;font-weight:600;color:var(--ink);width:100%;white-space:nowrap;margin-top:1.6mm}}
.lines{{margin-top:auto;font-size:6.5pt;line-height:1.55;color:var(--ink);width:100%}}
.ic{{width:2.3mm;height:2.3mm;color:var(--bg)}}"""
        front = (f"<div class='band'></div><div class='logo-box'>{logo_html(spec, p['bg'], p['fg'])}</div><div class='box'>{T('name', f.get('name'), 'name', 9)}"
                 f"{T('title', f.get('title'), 'title', 5.5)}<div class='rule'></div>{T('company', f.get('company'), 'company', 5.5)}"
                 f"<div class='lines'>{contact_rows(f, fit=5.6)}</div></div>")
    back_css = f"""
.page{{background:var(--bg);color:var(--fg)}}
.bbox{{position:absolute;left:{s}mm;right:{s}mm;top:{s}mm;bottom:{s}mm;display:flex;align-items:center;justify-content:{'space-between' if qr else 'center'};gap:4mm}}
.brand{{display:flex;flex-direction:column;align-items:{'flex-start' if qr else 'center'};text-align:{'left' if qr else 'center'};max-width:{'52mm' if qr else '78mm'}}}
.blogo{{width:15mm;height:15mm;margin-bottom:2mm}}
.bco{{font-family:var(--head);font-weight:700;font-size:11pt;letter-spacing:.06em;text-transform:uppercase;width:{'52mm' if qr else '76mm'};white-space:nowrap;
      text-align:inherit}}
.tag{{font-size:6.8pt;color:var(--muted);margin-top:1.2mm;width:{'52mm' if qr else '76mm'};max-height:7mm;text-align:inherit}}
.qr{{width:19mm;height:19mm;background:#fff;padding:1mm;border-radius:1mm;flex:none}}"""
    back = (f"<div class='bbox'><div class='brand'><div class='blogo'>{logo_html(spec, p['bg'], p['accent'])}</div>"
            f"{T('company', f.get('company') or f.get('name'), 'bco', 7)}{T('tagline', f.get('tagline'), 'tag', 5.5)}</div>"
            + (qr_html(qr) if qr else "") + "</div>")
    return [("front", wrap(spec, front, front_css)), ("back", wrap(spec, back, back_css))]


# ---------------------------------------------------------------- posts, portrait posts, stories (px)
def post(spec):
    f, style, p = spec["fields"], spec.get("style", "headline"), palette(spec)
    w, h, _, _, safe = size_of(spec)
    k = KINDS[spec["kind"]]
    top, bottom = k.get("safe_top", safe), k.get("safe_bottom", safe)
    img = spec.get("image")
    head_px = int(min(w, h) * 0.105)
    contact = " · ".join(x for x in (f.get("phone"), f.get("web")) if x)
    if style == "photo" and img:
        text_top = spec.get("_text_at") == "top"
        grad = "to bottom" if text_top else "to top"
        css = f"""
.photo{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.shade{{position:absolute;left:0;right:0;{'top' if text_top else 'bottom'}:0;height:62%;background:linear-gradient({grad},rgba(0,0,0,.82) 0%,rgba(0,0,0,.55) 45%,rgba(0,0,0,0) 100%)}}
.brand{{position:absolute;left:{safe}px;{'bottom' if text_top else 'top'}:{bottom if text_top else top}px;display:flex;align-items:center;gap:16px;
        background:rgba(0,0,0,.45);padding:12px 22px 12px 12px;border-radius:999px}}
.brand .lg{{width:56px;height:56px}}
.bn{{font-family:var(--head);font-size:30px;color:#fff;letter-spacing:.04em;white-space:nowrap;max-width:{w - 2 * safe - 120}px}}
.box{{position:absolute;left:{safe}px;right:{safe}px;{'top' if text_top else 'bottom'}:{top if text_top else bottom}px;color:#fff}}
.hl{{font-family:var(--head);font-weight:700;font-size:{head_px}px;line-height:1.02;max-height:{int(h * 0.3)}px;text-shadow:0 2px 18px rgba(0,0,0,.35)}}
.sub{{font-size:{int(head_px * 0.36)}px;line-height:1.3;margin-top:22px;max-height:{int(head_px * 1.05)}px;color:#F1F1F1}}
.cta{{display:inline-block;margin-top:30px;background:var(--accent);color:var(--ink);font-weight:800;font-size:{int(head_px * 0.3)}px;padding:16px 30px;border-radius:12px;
      white-space:nowrap;max-width:100%}}
.ct{{font-size:{int(head_px * 0.26)}px;margin-top:20px;color:#EDEDED;white-space:nowrap}}
.dl{{display:flex;align-items:center;gap:12px;margin-top:18px;font-size:{int(head_px * 0.3)}px;font-weight:700;color:var(--accent-text);white-space:nowrap}}"""
        inner = (f"<img class='photo' data-role='image' src='{Path(img).resolve().as_uri()}'><div class='shade'></div>"
                 f"<div class='brand'><div class='lg'>{logo_html(spec, p['fg'], p['bg'])}</div>{T('brand', f.get('brand'), 'bn', 18)}</div>"
                 f"<div class='box'>{T('headline', f.get('headline'), 'hl', int(head_px * 0.5))}{T('sub', f.get('sub'), 'sub', 22)}"
                 + (f"<div class='dl'>{icon('date', '1em')}<span class='t' data-role='dates' data-fit='18'>{esc(f.get('dates'))}</span></div>" if f.get("dates") else "")
                 + (f"<div class='t cta' data-role='cta' data-fit='18'>{esc(f.get('cta') or f.get('offer'))}</div>" if (f.get('cta') or f.get('offer')) else "")
                 + T("contact", contact, "ct", 18) + "</div>")
        return [("post", wrap(spec, inner, css))]
    if style == "split" and img:
        tall = h > w
        css = f"""
.photo{{position:absolute;{'left:0;right:0;top:0;height:48%;width:100%' if tall else 'top:0;bottom:0;right:0;width:48%;height:100%'};object-fit:cover}}
.panel{{position:absolute;{'left:0;right:0;bottom:0;height:52%' if tall else 'top:0;bottom:0;left:0;width:52%'};background:var(--bg);
        padding:{max(safe, top if tall else safe)}px {safe}px {bottom}px {safe}px;display:flex;flex-direction:column}}
.bn{{font-family:var(--head);font-size:28px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent-text);white-space:nowrap}}
.hl{{font-family:var(--head);font-size:{int(head_px * 0.86)}px;line-height:1.04;margin-top:26px;max-height:{int(h * 0.27)}px;color:var(--fg)}}
.sub{{font-size:{int(head_px * 0.32)}px;line-height:1.35;margin-top:22px;max-height:{int(head_px * 1.3)}px;color:var(--muted)}}
.offer{{margin-top:auto;font-family:var(--head);font-size:{int(head_px * 0.62)}px;color:var(--accent-text);white-space:nowrap}}
.dl{{display:flex;align-items:center;gap:10px;margin-top:18px;font-size:{int(head_px * 0.27)}px;font-weight:700;color:var(--accent-text);white-space:nowrap}}
.cta{{align-self:flex-start;margin-top:16px;background:var(--accent);color:var(--ink);font-weight:800;font-size:{int(head_px * 0.26)}px;padding:12px 24px;
      border-radius:10px;white-space:nowrap;max-width:100%}}
.ct{{font-size:{int(head_px * 0.25)}px;margin-top:14px;color:var(--fg);white-space:nowrap}}"""
        inner = (f"<img class='photo' data-role='image' src='{Path(img).resolve().as_uri()}'><div class='panel'>{T('brand', f.get('brand'), 'bn', 16)}"
                 f"{T('headline', f.get('headline'), 'hl', int(head_px * 0.45))}{T('sub', f.get('sub'), 'sub', 20)}"
                 + (f"<div class='dl'>{icon('date', '1em')}<span class='t' data-role='dates' data-fit='16'>{esc(f.get('dates'))}</span></div>" if f.get("dates") else "")
                 + f"{T('offer', f.get('offer'), 'offer', 30)}{T('cta', f.get('cta'), 'cta', 16)}{T('contact', contact, 'ct', 16)}</div>")
        return [("post", wrap(spec, inner, css))]
    # headline: colour or gradient ground, a big headline, an offer badge, a call to action, the brand
    badge = f.get("offer")
    story = h > w * 1.3
    css = f"""
.deco{{position:absolute;right:-{int(w * 0.18)}px;bottom:-{int(w * 0.22)}px;width:{int(w * 0.75)}px;height:{int(w * 0.75)}px;border-radius:50%;
       background:rgba(255,255,255,.07)}}
.deco2{{position:absolute;left:-{int(w * 0.12)}px;top:{int(h * 0.42)}px;width:{int(w * 0.32)}px;height:{int(w * 0.32)}px;border-radius:50%;border:14px solid rgba(255,255,255,.08)}}
.top{{position:absolute;left:{safe}px;right:{safe}px;top:{top}px;display:flex;align-items:center;gap:18px}}
.top .lg{{width:64px;height:64px}}
.bn{{font-family:var(--head);font-size:30px;letter-spacing:.14em;text-transform:uppercase;white-space:nowrap;max-width:{w - 2 * safe - 90}px;color:var(--fg)}}
.box{{position:absolute;left:{safe}px;width:{int(w * (0.62 if badge and not story else 0.84))}px;top:{top + int(h * (0.17 if not story else 0.06))}px;
      {f'bottom:{bottom + 190}px;display:flex;flex-direction:column;justify-content:safe center' if story else ''}}}
.hl{{font-family:var(--head);font-size:{int(head_px * (1.0 if h <= w * 1.3 else 1.4))}px;line-height:1.0;max-height:{int(h * (0.36 if h <= w * 1.3 else 0.32))}px;flex:none;
      color:var(--fg);letter-spacing:-.01em}}
.sub{{font-size:{int(head_px * 0.36)}px;line-height:1.3;margin-top:28px;max-height:{int(head_px * 1.1)}px;color:var(--muted)}}
.dates{{display:inline-flex;align-items:center;gap:12px;margin-top:30px;font-size:{int(head_px * 0.3)}px;font-weight:700;color:var(--accent-text);white-space:nowrap}}
.badge{{position:{'relative' if story else 'absolute'};{'margin-top:70px' if story else f'right:{safe}px;top:{top + int(h * 0.15)}px'};width:{int(w * (0.3 if story else 0.28))}px;
        height:{int(w * (0.3 if story else 0.28))}px;flex:none;border-radius:50%;background:var(--accent);
        color:var(--ink);display:flex;align-items:center;justify-content:center;text-align:center;transform:rotate(-8deg);box-shadow:0 18px 40px rgba(0,0,0,.25)}}
.badge .t{{font-family:var(--head);font-size:{int(w * 0.07)}px;line-height:.95;width:78%;max-height:70%}}
.bar{{position:absolute;left:0;right:0;bottom:0;height:{bottom + 70}px;background:rgba(0,0,0,.28)}}
.foot{{position:absolute;left:{safe}px;right:{safe}px;bottom:{bottom}px;display:flex;align-items:center;justify-content:space-between;gap:24px}}
.cta{{background:var(--accent);color:var(--ink);font-weight:800;font-size:{int(head_px * 0.28)}px;padding:16px 28px;border-radius:12px;white-space:nowrap;max-width:55%}}
.ct{{font-size:{int(head_px * 0.25)}px;color:var(--fg);white-space:nowrap;text-align:right;max-width:{'44%' if (f.get('cta')) else '100%'}}}"""
    inner = (f"<div class='deco'></div><div class='deco2'></div><div class='top'><div class='lg'>{logo_html(spec, p['bg'], p['accent'])}</div>{T('brand', f.get('brand'), 'bn', 18)}</div>"
             f"<div class='box'>{T('headline', f.get('headline'), 'hl', int(head_px * 0.5))}{T('sub', f.get('sub'), 'sub', 22)}"
             + (f"<div class='dates'>{icon('date', '1em')}<span class='t' data-role='dates' data-fit='18'>{esc(f.get('dates'))}</span></div>" if f.get("dates") else "")
             + (f"<div class='badge'>{T('offer', badge, '', 28)}</div>" if badge and story else "") + "</div>"
             + (f"<div class='badge'>{T('offer', badge, '', 28)}</div>" if badge and not story else "")
             + "<div class='bar'></div><div class='foot'>" + (f"<div class='t cta' data-role='cta' data-fit='18'>{esc(f.get('cta'))}</div>" if f.get("cta") else "<div></div>")
             + T("contact", contact, "ct", 16) + "</div>")
    return [("post", wrap(spec, inner, css))]


# ---------------------------------------------------------------- YouTube thumbnails (1280 x 720)
def thumbnail(spec):
    f, style = spec["fields"], spec.get("style", "face")
    img = spec.get("image")
    words = (f.get("headline") or "").upper()
    if style == "center" or not img:
        css = """
.page{background:var(--bg)}
.photo{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:saturate(1.25) contrast(1.1)}
.vig{position:absolute;inset:0;background:radial-gradient(ellipse at center,rgba(0,0,0,.05) 30%,rgba(0,0,0,.7) 100%)}
.box{position:absolute;left:70px;right:70px;top:150px;bottom:170px;display:flex;align-items:center;justify-content:center}
.hl{font-family:var(--head);font-size:150px;line-height:.95;text-align:center;color:#fff;-webkit-text-stroke:7px #000;paint-order:stroke fill;
      text-shadow:0 8px 0 rgba(0,0,0,.6);max-height:100%;width:100%}
.tag{position:absolute;left:58px;top:58px;background:var(--accent);color:var(--ink);font-family:var(--head);font-size:48px;padding:8px 22px;transform:rotate(-3deg);
      white-space:nowrap;max-width:520px}"""
        inner = ((f"<img class='photo' data-role='image' src='{Path(img).resolve().as_uri()}'><div class='vig'></div>" if img else "")
                 + f"<div class='box'>{T('headline', words, 'hl', 70)}</div>{T('sub', (f.get('sub') or '').upper(), 'tag', 26)}")
        return [("thumbnail", wrap(spec, inner, css))]
    css = """
.page{background:linear-gradient(120deg,var(--bg) 0%,var(--ink) 100%)}
.photo{position:absolute;right:0;top:0;bottom:0;width:56%;height:100%;object-fit:cover;-webkit-mask-image:linear-gradient(to right,transparent 0%,#000 22%)}
.box{position:absolute;left:46px;top:60px;bottom:150px;width:640px;display:flex;align-items:center}
.hl{font-family:var(--head);font-size:136px;line-height:.98;color:#fff;-webkit-text-stroke:6px #000;paint-order:stroke fill;text-shadow:0 7px 0 rgba(0,0,0,.55);
      max-height:100%;width:100%}
.hl::first-line{color:var(--accent-text)}
.tag{position:absolute;left:46px;bottom:56px;background:var(--accent);color:var(--ink);font-family:var(--head);font-size:44px;padding:6px 20px;white-space:nowrap;
      max-width:600px}"""
    if spec.get("_cutout"):  # the person cut from their backdrop by the photo agent
        css += """
.cut{position:absolute;right:10px;bottom:0;height:100%;width:56%;object-fit:contain;object-position:right bottom;
     filter:drop-shadow(0 0 22px rgba(0,0,0,.55)) drop-shadow(8px 10px 0 rgba(0,0,0,.35))}
.glow{position:absolute;right:4%;bottom:-10%;width:52%;height:110%;border-radius:50%;background:radial-gradient(closest-side,rgba(255,255,255,.28),rgba(255,255,255,0))}"""
        photo = f"<div class='glow'></div><img class='cut' data-role='image' src='{Path(spec['_cutout']).resolve().as_uri()}'>"
    else:
        photo = f"<img class='photo' data-role='image' src='{Path(img).resolve().as_uri()}'>"
    inner = (f"{photo}<div class='box'>{T('headline', words, 'hl', 64)}</div>"
             f"{T('sub', (f.get('sub') or '').upper(), 'tag', 24)}")
    return [("thumbnail", wrap(spec, inner, css))]


# ---------------------------------------------------------------- flyers and posters (mm)
def flyer(spec):
    f, style, p = spec["fields"], spec.get("style", "sale"), palette(spec)
    w, h, _, b, safe = size_of(spec)
    s = b + safe
    scale = w / 148.0  # sizes grow with the paper
    items = f.get("items") or []
    qr = f.get("qr") or (f.get("web") if spec.get("qr") else None)
    if style == "event":
        css = f"""
.page{{background:var(--light);color:var(--ink)}}
.hero{{position:absolute;left:0;right:0;top:0;height:{b + h * 0.46}mm;background:var(--bg)}}
.hero img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:.55}}
.hbox{{position:absolute;left:{s}mm;right:{s}mm;top:{s + 4 * scale}mm;height:{h * 0.46 - safe - 8 * scale}mm;display:flex;flex-direction:column;justify-content:flex-end;color:var(--fg)}}
.bn{{font-family:var(--head);font-size:{9 * scale}pt;letter-spacing:.3em;text-transform:uppercase;color:var(--accent-text);white-space:nowrap}}
.hl{{font-family:var(--head);font-weight:700;font-size:{30 * scale}pt;line-height:1.02;margin-top:{3 * scale}mm;max-height:{h * 0.24}mm}}
.sub{{font-size:{11 * scale}pt;line-height:1.3;margin-top:{3 * scale}mm;max-height:{18 * scale}mm;color:var(--muted)}}
.info{{position:absolute;left:{s}mm;right:{s}mm;top:{b + h * 0.46 + 7 * scale}mm;display:grid;grid-template-columns:1fr 1fr;gap:{5 * scale}mm {6 * scale}mm}}
.cell{{display:flex;gap:{2.5 * scale}mm;align-items:flex-start}}
.cell .ic{{width:{6 * scale}mm;height:{6 * scale}mm;color:var(--bg)}}
.lab{{font-size:{7.5 * scale}pt;letter-spacing:.18em;text-transform:uppercase;color:var(--sub)}}
.val{{font-family:var(--head);font-size:{13 * scale}pt;font-weight:600;line-height:1.2;max-height:{13 * scale}mm;width:{(w - 2 * safe) / 2 - 12 * scale}mm}}
.body{{position:absolute;left:{s}mm;right:{s + (30 * scale if qr else 0)}mm;top:{b + h * 0.46 + 52 * scale}mm;font-size:{11 * scale}pt;line-height:1.5;
        max-height:{h * 0.54 - 52 * scale - safe - 4}mm;color:var(--ink)}}
.qr{{position:absolute;right:{s}mm;bottom:{s}mm;width:{25 * scale}mm;height:{25 * scale}mm;background:#fff;padding:{1 * scale}mm}}
.webl{{position:absolute;left:{s}mm;bottom:{s + 2 * scale}mm;right:{s + 30 * scale}mm;font-family:var(--head);font-weight:600;font-size:{12 * scale}pt;color:var(--ink);
       white-space:nowrap}}"""

        def cell(k, lab):
            return f"<div class='cell'>{icon(k)}<div><div class='lab'>{lab}</div>{T(k, f.get(k), 'val', 8)}</div></div>" if f.get(k) else ""
        inner = ((f"<div class='hero'><img data-role='image' src='{Path(spec['image']).resolve().as_uri()}'></div>" if spec.get("image") else "<div class='hero'></div>")
                 + f"<div class='hbox'>{T('brand', f.get('brand'), 'bn', 7)}{T('headline', f.get('headline'), 'hl', 16)}{T('sub', f.get('sub'), 'sub', 8)}</div>"
                 + f"<div class='info'>{cell('date', 'Date')}{cell('time', 'Time')}{cell('address', 'Venue')}{cell('phone', 'Contact')}</div>"
                 + T("body", f.get("body"), "body", 8) + T("web", f.get("web"), "webl", 7) + (qr_html(qr) if qr else ""))
        return [("flyer", wrap(spec, inner, css))]
    css = f"""
.page{{background:var(--bg);color:var(--fg)}}
.burst{{position:absolute;right:-{12 * scale}mm;top:-{12 * scale}mm;width:{90 * scale}mm;height:{90 * scale}mm;border-radius:50%;background:rgba(255,255,255,.08)}}
.col{{position:absolute;left:{s}mm;right:{s}mm;top:{s}mm;bottom:{b + safe + 28 * scale}mm;display:flex;flex-direction:column}}
.head{{display:flex;align-items:center;gap:{3 * scale}mm}}
.head .lg{{width:{12 * scale}mm;height:{12 * scale}mm}}
.bn{{font-family:var(--head);font-size:{11 * scale}pt;letter-spacing:.12em;text-transform:uppercase;white-space:nowrap;max-width:{w - 2 * safe - 20 * scale}mm}}
.hl{{font-family:var(--head);font-size:{44 * scale}pt;line-height:.98;max-height:{50 * scale}mm;margin-top:{9 * scale}mm;flex:none}}
.offer{{align-self:flex-start;margin:{7 * scale}mm 0 0 {1.5 * scale}mm;background:var(--accent);color:var(--ink);font-family:var(--head);font-size:{28 * scale}pt;
        padding:{2 * scale}mm {5 * scale}mm;transform:rotate(-2deg);white-space:nowrap;max-width:{w - 2 * safe}mm;flex:none}}
.sub{{font-size:{12 * scale}pt;line-height:1.35;max-height:{17 * scale}mm;color:var(--muted);margin-top:{6 * scale}mm;flex:none}}
.items{{margin-top:{7 * scale}mm;display:grid;grid-template-columns:1fr 1fr;align-content:start;gap:{2.6 * scale}mm {6 * scale}mm;flex:1;min-height:0;overflow:hidden}}
.it{{display:flex;justify-content:space-between;gap:{2 * scale}mm;border-bottom:.3mm dashed rgba(255,255,255,.35);padding-bottom:{1.2 * scale}mm;
     font-size:{11 * scale}pt;white-space:nowrap}}
.it .t{{overflow:hidden}}
.it .pr{{font-weight:800;color:var(--accent-text);flex:none}}
.foot{{position:absolute;left:0;right:0;bottom:0;height:{b + safe + 24 * scale}mm;background:rgba(0,0,0,.3)}}
.fbox{{position:absolute;left:{s}mm;right:{s + (26 * scale if qr else 0)}mm;bottom:{s}mm;height:{20 * scale}mm;display:flex;flex-direction:column;justify-content:center;
       font-size:{9 * scale}pt;line-height:1.5}}
.fbox .ic{{width:{3.6 * scale}mm;height:{3.6 * scale}mm}}
.dates{{font-weight:800;color:var(--accent-text);font-size:{10 * scale}pt;white-space:nowrap}}
.fcta{{position:absolute;right:{s + (24 * scale if qr else 0)}mm;bottom:{s + 7 * scale}mm;background:var(--accent);color:var(--ink);font-weight:800;font-size:{11 * scale}pt;
       padding:{1.6 * scale}mm {4 * scale}mm;border-radius:{1.5 * scale}mm;white-space:nowrap;max-width:{40 * scale}mm}}
.qr{{position:absolute;right:{s}mm;bottom:{s}mm;width:{20 * scale}mm;height:{20 * scale}mm;background:#fff;padding:{.8 * scale}mm}}"""
    rows = "".join(f"<div class='it'>{T('item', it.get('name'), '', 7, tag='span')}<span class='t pr' data-role='price'>{esc(it.get('price', ''))}</span></div>"
                   for it in items[:16])
    inner = (f"<div class='burst'></div><div class='col'><div class='head'><div class='lg'>{logo_html(spec, p['bg'], p['accent'])}</div>{T('brand', f.get('brand'), 'bn', 8)}</div>"
             f"{T('headline', f.get('headline'), 'hl', 18)}{T('offer', f.get('offer'), 'offer', 14)}{T('sub', f.get('sub'), 'sub', 8)}"
             f"<div class='items'>{rows}</div></div><div class='foot'></div><div class='fbox'>{T('dates', f.get('dates'), 'dates', 7)}"
             f"{contact_rows(f, ('phone', 'web', 'address'), fit=7)}</div>" + T("cta", f.get("cta"), "fcta", 8) + (qr_html(qr) if qr else ""))
    return [("flyer", wrap(spec, inner, css))]


# ---------------------------------------------------------------- certificates (A4 landscape)
def certificate(spec, recipient=None):
    f, style, p = spec["fields"], spec.get("style", "classic"), palette(spec)
    w, h, _, _, safe = size_of(spec)
    name = recipient or f.get("recipient") or "Recipient Name"
    title = f.get("title") or "Certificate of Achievement"
    words = title.split(" of ", 1) if " of " in title.lower() else [title, ""]
    t1, t2 = (words[0], "of " + words[1]) if len(words) == 2 and words[1] else (title, "")
    signers = [x for x in (f.get("signer1"), f.get("signer2")) if x]
    classic = style == "classic"
    css = f"""
.page{{background:{'var(--light)' if classic else '#FFFFFF'};color:var(--ink)}}
.f1{{position:absolute;inset:{safe * 0.6}mm;border:{2.2 if classic else 0}mm solid var(--bg)}}
.f2{{position:absolute;inset:{safe * 0.6 + 3.2}mm;border:.35mm solid var(--accent)}}
.side{{position:absolute;left:0;top:0;bottom:0;width:{0 if classic else 28}mm;background:var(--bg)}}
.side2{{position:absolute;left:{0 if classic else 28}mm;top:0;bottom:0;width:{0 if classic else 3}mm;background:var(--accent)}}
.corner{{position:absolute;width:16mm;height:16mm;border-color:var(--accent);border-style:solid;border-width:0}}
.c1{{left:{safe * 0.6 + 5}mm;top:{safe * 0.6 + 5}mm;border-left-width:.8mm;border-top-width:.8mm}}
.c2{{right:{safe * 0.6 + 5}mm;top:{safe * 0.6 + 5}mm;border-right-width:.8mm;border-top-width:.8mm}}
.c3{{left:{safe * 0.6 + 5}mm;bottom:{safe * 0.6 + 5}mm;border-left-width:.8mm;border-bottom-width:.8mm}}
.c4{{right:{safe * 0.6 + 5}mm;bottom:{safe * 0.6 + 5}mm;border-right-width:.8mm;border-bottom-width:.8mm}}
.box{{position:absolute;left:{safe + (12 if classic else 40)}mm;right:{safe + 12}mm;top:{safe + 9}mm;bottom:{safe + 8}mm;display:flex;flex-direction:column;
      align-items:center;text-align:center}}
.lg{{width:18mm;height:18mm;margin-bottom:3mm}}
.org{{font-size:12pt;letter-spacing:.3em;text-transform:uppercase;color:var(--sub);white-space:nowrap;width:100%}}
.t1{{font-family:var(--head);font-size:46pt;letter-spacing:.14em;text-transform:uppercase;color:var(--ink);margin-top:4mm;white-space:nowrap;width:100%;line-height:1.05}}
.t2{{font-family:var(--head);font-size:16pt;letter-spacing:.42em;text-transform:uppercase;color:var(--accent-ink);margin-top:2mm;white-space:nowrap;width:100%}}
.pre{{font-family:var(--body);font-style:italic;font-size:14pt;color:var(--sub);margin-top:9mm}}
.who{{font-family:var(--script);font-size:44pt;color:var(--bg);margin-top:3mm;white-space:nowrap;width:100%;line-height:1.25;padding-bottom:1mm}}
.line{{width:140mm;border-top:.35mm solid var(--accent);margin-top:1mm}}
.why{{font-family:var(--body);font-size:14pt;line-height:1.5;color:var(--ink);margin-top:6mm;width:200mm;max-height:22mm}}
.sig{{margin-top:auto;display:flex;justify-content:{'space-between' if len(signers) > 1 else 'center'};align-items:flex-end;width:{200 if len(signers) > 1 else 90}mm;gap:20mm}}
.s{{display:flex;flex-direction:column;align-items:center;width:70mm}}
.s .ln{{width:62mm;border-top:.3mm solid var(--ink);margin-bottom:1.6mm}}
.sn{{font-family:var(--head);font-size:12pt;white-space:nowrap;width:70mm}}
.st{{font-size:10pt;color:var(--sub);white-space:nowrap;width:70mm}}
.date{{font-size:11pt;color:var(--sub);white-space:nowrap;margin-top:3mm}}
.seal{{position:absolute;left:50%;bottom:{safe + 6}mm;transform:translateX(-50%);width:24mm;height:24mm;display:{'block' if len(signers) > 1 else 'none'}}}"""
    seal = ("<svg class='seal' viewBox='0 0 100 100'>" + "".join(
        f"<circle cx='{50 + 44 * __import__('math').cos(a * 0.2618)}' cy='{50 + 44 * __import__('math').sin(a * 0.2618)}' r='7' fill='{p['accent']}'/>" for a in range(24))
            + f"<circle cx='50' cy='50' r='42' fill='{p['accent']}'/><circle cx='50' cy='50' r='34' fill='none' stroke='#fff' stroke-width='1.5'/>"
            f"<text x='50' y='55' text-anchor='middle' font-family='Bodoni MT, Georgia' font-size='15' fill='#fff' letter-spacing='1'>AWARD</text></svg>")

    def sig(x):
        nm, _, tt = (x or "").partition(",")
        return f"<div class='s'><div class='ln'></div>{T('signer', nm.strip(), 'sn', 8)}{T('signer_title', tt.strip(), 'st', 7)}</div>"
    inner = ("<div class='side'></div><div class='side2'></div>" + ("<div class='f1'></div><div class='f2'></div>" + "".join(f"<div class='corner c{i}'></div>" for i in range(1, 5))
                                                                    if classic else "")
             + f"<div class='box'><div class='lg'>{logo_html(spec, p['fg'], p['bg'])}</div>{T('org', f.get('org'), 'org', 8)}{T('title', t1, 't1', 18)}"
             f"{T('title2', t2, 't2', 9)}<div class='pre'>This certificate is proudly presented to</div>{T('recipient', name, 'who', 20)}<div class='line'></div>"
             f"{T('reason', f.get('reason'), 'why', 9)}<div class='sig'>{''.join(sig(x) for x in signers)}</div>{T('date', f.get('date'), 'date', 8)}</div>"
             + seal)
    return [("certificate", wrap(spec, inner, css))]


# ---------------------------------------------------------------- invitations (5 x 7 in)
def invitation(spec):
    f, style, p = spec["fields"], spec.get("style", "elegant"), palette(spec)
    w, h, _, b, safe = size_of(spec)
    s = b + safe
    elegant = style == "elegant"
    css = f"""
.page{{background:{'var(--light)' if elegant else 'var(--bg)'};color:{'var(--ink)' if elegant else 'var(--fg)'}}}
.fr{{position:absolute;inset:{s - 1}mm;border:.4mm solid var(--accent)}}
.fr2{{position:absolute;inset:{s + 1}mm;border:.2mm solid var(--accent)}}
.box{{position:absolute;left:{s + 7}mm;right:{s + 7}mm;top:{s + 12}mm;bottom:{s + 10}mm;display:flex;flex-direction:column;align-items:center;text-align:center}}
.inv{{font-family:var(--script);font-size:24pt;color:var(--accent-ink);white-space:nowrap;width:100%;line-height:1.35}}
.host{{font-size:9pt;letter-spacing:.2em;text-transform:uppercase;margin-top:6mm;color:{'var(--muted)' if elegant else 'var(--muted)'};width:100%;max-height:12mm}}
.ev{{font-family:var(--head);font-size:27pt;line-height:1.12;margin-top:6mm;width:100%;max-height:38mm}}
.orn{{width:30mm;height:4mm;margin:6mm 0 5mm}}
.when{{font-family:var(--head);font-size:12pt;letter-spacing:.08em;width:100%;white-space:nowrap}}
.time{{font-size:10.5pt;margin-top:1.5mm;width:100%;white-space:nowrap;color:var(--muted)}}
.venue{{font-size:10.5pt;line-height:1.4;margin-top:5mm;width:100%;max-height:16mm}}
.note{{font-style:italic;font-size:9.5pt;margin-top:5mm;width:100%;max-height:12mm;color:var(--muted)}}
.rsvp{{margin-top:auto;font-size:8.5pt;letter-spacing:.15em;text-transform:uppercase;width:100%;white-space:nowrap}}"""
    orn = (f"<svg class='orn' viewBox='0 0 120 16'><path d='M0 8h48M72 8h48' stroke='{p['accent']}' stroke-width='1.2'/>"
           f"<path d='M60 1l7 7-7 7-7-7z' fill='{p['accent']}'/><circle cx='44' cy='8' r='2' fill='{p['accent']}'/><circle cx='76' cy='8' r='2' fill='{p['accent']}'/></svg>")
    inner = ("<div class='fr'></div><div class='fr2'></div>" + f"<div class='box'>{T('heading', f.get('heading') or 'You are invited', 'inv', 12)}"
             f"{T('host', f.get('host'), 'host', 6.5)}{T('event', f.get('event') or f.get('headline'), 'ev', 13)}{orn}{T('date', f.get('date'), 'when', 8)}"
             f"{T('time', f.get('time'), 'time', 7)}{T('address', f.get('address') or f.get('venue'), 'venue', 7)}{T('note', f.get('note'), 'note', 7)}"
             f"{T('rsvp', ('RSVP ' + f['rsvp']) if f.get('rsvp') else '', 'rsvp', 6.5)}</div>")
    return [("invitation", wrap(spec, inner, css))]


BUILDERS = {"card": card, "post": post, "portrait": post, "story": post, "thumbnail": thumbnail, "flyer": flyer, "poster": flyer,
            "certificate": certificate, "invitation": invitation}


def build(spec):
    return BUILDERS[spec["kind"]](spec)
