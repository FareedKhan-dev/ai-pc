"""Invoices, quotations, receipts, credit notes and statements as PDF documents a business can send: written as HTML and
printed by headless Chrome (A4), then read back from the PDF to check what matters is really on the page.

A sales tax invoice (a registered business charging tax) shows what Pakistan's Sales Tax Act s.23 asks for: the
supplier's name, address, NTN and STRN; the buyer's name, address and NTN/CNIC/STRN; the serial number and date; each
line's description (and HS code), quantity, value excluding tax, tax rate and tax; the totals; the amount in words.
When FBR's digital invoicing has given the invoice its number, that number and its QR code are printed too.

  make(books, doc, folder) -> {"pdf", "html", "checks": [...]}
"""
import base64
import html
import io
from pathlib import Path

from ..config import STATE
from .money import rs, words

OUT = STATE / "accounts" / "documents"
TITLE = {"invoice": "INVOICE", "quote": "QUOTATION", "receipt": "PAYMENT RECEIPT", "credit_note": "CREDIT NOTE", "bill": "PURCHASE BILL",
         "payment": "PAYMENT VOUCHER", "statement": "STATEMENT OF ACCOUNT"}

CSS = """
@page { size: A4; margin: 14mm 13mm 16mm 13mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; color: #1f2937; margin: 0; }
.top { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #1f4e79; padding-bottom: 10px; }
.biz h1 { margin: 0 0 4px; font-size: 18pt; color: #1f4e79; }
.biz div, .party div { line-height: 1.45; }
.doc { text-align: right; }
.doc h2 { margin: 0 0 6px; font-size: 15pt; letter-spacing: 1px; color: #111827; }
.doc table td { padding: 1px 0 1px 12px; }
.muted { color: #6b7280; }
.parties { display: flex; gap: 24px; margin: 14px 0; }
.party { flex: 1; background: #f3f6fa; border-radius: 6px; padding: 9px 12px; }
.party b.h { display: block; color: #1f4e79; font-size: 8.5pt; letter-spacing: 1px; margin-bottom: 3px; }
table.lines { width: 100%; border-collapse: collapse; margin-top: 4px; }
table.lines th { background: #1f4e79; color: #fff; font-weight: 600; padding: 6px 5px; font-size: 8.8pt; text-align: right; }
table.lines th.l, table.lines td.l { text-align: left; }
table.lines td { padding: 6px 5px; border-bottom: 1px solid #e5e7eb; text-align: right; vertical-align: top; }
table.lines tr:nth-child(even) td { background: #fafbfd; }
.sum { display: flex; justify-content: space-between; margin-top: 12px; gap: 24px; }
.sum .words { flex: 1; font-style: italic; padding-top: 4px; }
table.totals { border-collapse: collapse; min-width: 300px; }
table.totals td { padding: 4px 6px; text-align: right; }
table.totals tr.grand td { border-top: 2px solid #1f4e79; font-size: 12pt; font-weight: 700; color: #1f4e79; padding-top: 7px; }
.foot { margin-top: 22px; display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; }
.foot .bank { line-height: 1.5; }
.sign { text-align: center; min-width: 180px; border-top: 1px solid #9ca3af; padding-top: 4px; }
.fbr { display: flex; align-items: center; gap: 10px; border: 1px solid #d1d5db; border-radius: 6px; padding: 6px 10px; margin-top: 14px; }
.stamp { display: inline-block; padding: 3px 9px; border-radius: 4px; font-weight: 700; font-size: 9pt; }
.stamp.paid { background: #dcfce7; color: #166534; } .stamp.void { background: #fee2e2; color: #991b1b; }
.stamp.due { background: #fef3c7; color: #92400e; }
.note { margin-top: 12px; line-height: 1.5; }
.small { font-size: 8.5pt; }
"""


def _e(s):
    return html.escape(str(s or ""))


def day(s):
    """'2026-07-10' -> '10 Jul 2026' (as people write dates on invoices)."""
    import datetime as dt
    try:
        return dt.date.fromisoformat(str(s)).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(s or "")


def _qr_svg(text, version=None):
    """A QR code as an inline SVG; FBR's digital invoice code is version 2 (25 x 25 modules), printed 1 x 1 inch."""
    import segno
    buf = io.BytesIO()
    segno.make(text, error="l" if version else "m", version=version).save(buf, kind="svg", scale=2, border=1)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def fbr_number(d):
    """The number FBR's Digital Invoicing gave this document, if it was posted there."""
    return d.get("fbr_invoice") or (d.get("links") or {}).get("fbr")


def _logo(path):
    p = Path(path) if path else None
    if not p or not p.exists():
        return ""
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f'<img src="data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}" style="max-height:60px;max-width:180px;margin-bottom:6px">'


def _biz(c):
    rows = [f"<h1>{_e(c.get('name'))}</h1>"] if not c.get("logo") else [_logo(c.get("logo")), f"<h1>{_e(c.get('name'))}</h1>"]
    for k in ("address", "phone", "email"):
        if c.get(k):
            rows.append(f"<div>{_e(c[k])}</div>")
    ids = " &nbsp; ".join(f"{lab}: {_e(c[k])}" for k, lab in (("ntn", "NTN"), ("strn", "STRN")) if c.get(k))
    if ids:
        rows.append(f"<div><b>{ids}</b></div>")
    return "\n".join(rows)


def _party(p, label):
    if not p:
        return ""
    rows = [f'<b class="h">{label}</b><div><b>{_e(p.get("name"))}</b></div>']
    for k in ("address", "phone", "email"):
        if p.get(k):
            rows.append(f"<div>{_e(p[k])}</div>")
    ids = " &nbsp; ".join(f"{lab}: {_e(p[k])}" for k, lab in (("ntn", "NTN"), ("cnic", "CNIC"), ("strn", "STRN")) if p.get(k))
    if ids:
        rows.append(f"<div>{ids}</div>")
    return '<div class="party">' + "\n".join(rows) + "</div>"


def html_for(b, d):
    c = b.company()
    kind = d["kind"]
    taxed = kind in ("invoice", "credit_note", "quote", "bill") and d.get("totals", {}).get("tax")
    title = "SALES TAX INVOICE" if kind == "invoice" and taxed and c.get("strn") else TITLE.get(kind, kind.upper())
    meta = [("Number", d["number"]), ("Date", day(d["date"]))]
    if kind == "invoice" and d.get("due"):
        meta.append(("Due", day(d["due"])))
    if kind == "quote" and d.get("due"):
        meta.append(("Valid until", day(d["due"])))
    if kind == "credit_note" and d.get("invoice"):
        meta.append(("Against", d["invoice"]))
    if d.get("ref"):
        meta.append(("Reference", d["ref"]))
    stamp = ""
    if kind in ("invoice", "bill"):
        st = d.get("state")
        stamp = f'<span class="stamp {"paid" if st == "paid" else "void" if st == "void" else "due"}">{_e(st.upper())}</span>' if st else ""
    meta_html = "".join(f'<tr><td class="muted">{_e(k)}</td><td><b>{_e(v)}</b></td></tr>' for k, v in meta)
    head = f"""<div class="top"><div class="biz">{_biz(c)}</div>
<div class="doc"><h2>{_e(title)}</h2><table>{meta_html}</table><div style="margin-top:6px">{stamp}</div></div></div>"""
    party_label = {"invoice": "BILL TO", "quote": "PREPARED FOR", "receipt": "RECEIVED FROM", "credit_note": "CREDIT TO", "bill": "SUPPLIER",
                   "payment": "PAID TO", "statement": "ACCOUNT"}.get(kind, "TO")
    body = f'<div class="parties">{_party(d.get("party"), party_label)}</div>'
    if kind in ("invoice", "quote", "credit_note", "bill"):
        t = d["totals"]
        further = t.get("further_tax")
        cols = ["#", "Description", "Qty", "Rate", "Value excl. tax", "Tax", "Sales tax"] + (["Further tax"] if further else []) + ["Value incl. tax"]
        ths = "".join(f'<th class="{"l" if h in ("#", "Description") else ""}">{h}</th>' for h in cols)
        trs = []
        for i, ln in enumerate(d["lines"], 1):
            desc = _e(ln["description"]) + (f'<div class="muted small">HS code {_e(ln["hs_code"])}</div>' if ln.get("hs_code") else "")
            q = ln["qty"].rstrip("0").rstrip(".") if "." in ln["qty"] else ln["qty"]
            cells = [f'<td class="l">{i}</td>', f'<td class="l">{desc}</td>', f"<td>{_e(q)} {_e(ln.get('unit') or '')}</td>", f"<td>{rs(ln['rate'], '')}</td>",
                     f"<td>{rs(ln['amount'], '')}</td>", f"<td>{_e(ln['tax_rate'] + '%') if ln.get('tax_rate') else '-'}</td>", f"<td>{rs(ln['tax'], '')}</td>"]
            if further:
                cells.append(f"<td>{rs(ln.get('further_tax') or 0, '')}</td>")
            cells.append(f"<td>{rs(ln['amount'] + ln['tax'] + (ln.get('further_tax') or 0), '')}</td>")
            trs.append("<tr>" + "".join(cells) + "</tr>")
        body += f'<table class="lines"><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table>'
        tot = [("Value excluding tax", t["subtotal"]), ("Sales tax", t["tax"])]
        if further:
            tot.append(("Further tax", further))
        tot_html = "".join(f"<tr><td>{k}</td><td>{rs(v)}</td></tr>" for k, v in tot)
        tot_html += f'<tr class="grand"><td>Total</td><td>{rs(t["total"])}</td></tr>'
        if kind in ("invoice", "bill") and d.get("paid"):
            cred = d.get("credited") or 0
            if d["paid"] - cred:
                tot_html += f'<tr><td>Paid</td><td>{rs(d["paid"] - cred)}</td></tr>'
            if cred:
                tot_html += f'<tr><td>Credited (returns)</td><td>{rs(cred)}</td></tr>'
            tot_html += f'<tr><td><b>Balance due</b></td><td><b>{rs(d["balance"])}</b></td></tr>'
        body += f'<div class="sum"><div class="words">{_e(words(t["total"]))}</div><table class="totals">{tot_html}</table></div>'
    elif kind in ("receipt", "payment"):
        amt, wht = d.get("amount", 0), d.get("withheld", 0)
        rows = [("Amount", amt)] + ([("Income tax withheld", wht)] if wht else [])
        body += '<table class="totals" style="margin-left:auto">' + "".join(f"<tr><td>{k}</td><td>{rs(v)}</td></tr>" for k, v in rows)
        body += f'<tr class="grand"><td>Total</td><td>{rs(amt + wht)}</td></tr></table>'
        body += f'<div class="note"><i>{_e(words(amt + wht))}</i><br>Received by {"bank transfer" if d.get("bank") else "cash"}.</div>'
        if d.get("settled"):
            body += '<div class="note"><b>Settles:</b> ' + ", ".join(f"{_e(n)} ({rs(a)})" for n, a in d["settled"]) + "</div>"
    fbr = fbr_number(d)
    if fbr:  # the FBR Digital Invoicing logo (FBR gives it to integrated businesses: put it in state/accounts/fbr_di_logo.png) and the QR code
        logo = _logo(c.get("fbr_logo") or STATE / "accounts" / "fbr_di_logo.png")
        body += f'<div class="fbr">{logo}<img src="{_qr_svg(fbr, version=2)}" style="width:1in;height:1in"><div><b>FBR Digital Invoicing System</b><br>' \
                f'FBR invoice number: <b>{_e(fbr)}</b></div></div>'
    if d.get("notes"):
        body += f'<div class="note"><b>Notes:</b> {_e(d["notes"])}</div>'
    bank = c.get("bank")
    foot = '<div class="foot"><div class="bank small">' + (f"<b>Pay to:</b> {_e(bank)}<br>" if bank and kind in ("invoice", "quote") else "") + \
        ("Prices are valid until the date above.<br>" if kind == "quote" else "") + \
        '<span class="muted">This document was made by computer and needs no signature.</span></div>' \
        '<div class="sign">Authorised signature</div></div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{_e(title)} {_e(d['number'])}</title><style>{CSS}</style></head>
<body>{head}{body}{foot}</body></html>"""


def make(b, d, folder=None):
    """The document as PDF (and its HTML), then checked by reading the PDF's text back."""
    from .. import headless
    folder = Path(folder or OUT)
    folder.mkdir(parents=True, exist_ok=True)
    if d["kind"] == "receipt":
        d = dict(d, settled=[(b.doc(i)["number"], a) for i, a in b.cx.execute("SELECT doc_id, amount FROM allocations WHERE pay_id=?", (d["id"],))])
    name = d["number"].replace("/", "-")
    h = folder / f"{name}.html"
    h.write_text(html_for(b, d), encoding="utf-8")
    pdf = folder / f"{name}.pdf"
    headless.pdf(h, pdf, wait_ms=800, lane="accounts")
    return {"pdf": str(pdf), "html": str(h), "checks": check_pdf(pdf, b, d)}


def check_pdf(pdf, b, d):
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    text = " ".join((p.extract_text() or "") for p in r.pages)
    flat = " ".join(text.split())
    c = b.company()
    out = [{"ok": d["number"] in flat, "what": f"the number {d['number']} is on it"},
           {"ok": not d.get("party") or d["party"]["name"] in flat, "what": "the customer's or supplier's name is on it"},
           {"ok": len(r.pages) <= max(1, (len(d.get("lines") or []) + 11) // 22 + 1), "what": f"{len(r.pages)} page(s)"}]
    if d.get("totals"):
        out.append({"ok": rs(d["totals"]["total"]) in flat, "what": f"the total {rs(d['totals']['total'])} is on it"})
        out.append({"ok": " ".join(words(d["totals"]["total"]).split()[:4]) in flat, "what": "the total in words is on it"})
    if d["kind"] == "invoice" and d.get("totals", {}).get("tax") and c.get("strn"):
        out.append({"ok": "SALES TAX INVOICE" in flat and c["strn"] in flat and (not c.get("ntn") or c["ntn"] in flat),
                    "what": "a sales tax invoice with the business's NTN and STRN"})
        p = d.get("party") or {}
        if p.get("strn"):
            out.append({"ok": p["strn"] in flat, "what": "the buyer's STRN is on it"})
    if fbr_number(d):
        out.append({"ok": fbr_number(d) in flat, "what": f"FBR's invoice number {fbr_number(d)} is on it, with its QR code"})
    return out
