"""Printing by code: the printers on this PC, what is waiting in a queue, and PDFs, pictures and Office files printed
(shown first, printed after a yes; paper costs money). Office files become PDF first (Office in the background); each
PDF page is drawn at up to 300 dpi and sent through Windows' printing (GDI) fitted to the page. 'Microsoft Print to
PDF' writes its file without the Save dialog, which is how this is checked.

  'which printers do I have?'   'print invoice.pdf'   'print report.docx on HP LaserJet, 2 copies'   'print queue'
"""
import re
from pathlib import Path

NAME, LABEL = "printing", "Printing: printers, queues, print PDFs, pictures and Office files"
EXAMPLES = ["which printers do I have?", "print invoice.pdf", "print queue"]
OUTWARD = {"print"}
PICTURES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp"}
OFFICE = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".rtf", ".odt"}


def printers():
    import win32print
    default = win32print.GetDefaultPrinter()
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [{"name": p[2], "default": p[2] == default} for p in win32print.EnumPrinters(flags)]


def queue(printer=None):
    import win32print
    out = []
    for p in ([printer] if printer else [x["name"] for x in printers()]):
        h = win32print.OpenPrinter(p)
        try:
            for j in win32print.EnumJobs(h, 0, 50, 1):
                out.append({"printer": p, "document": j["pDocument"], "pages": j["TotalPages"], "status": j.get("pStatus") or j.get("Status")})
        finally:
            win32print.ClosePrinter(h)
    return out


def pages_of(path, work, dpi=300):
    """A file as page pictures: a PDF's pages, a picture, or an Office file made PDF first."""
    p = Path(path)
    if p.suffix.lower() in PICTURES:
        from PIL import Image
        return [Image.open(p).convert("RGB")]
    if p.suffix.lower() in OFFICE:
        from ai_pc.office import render
        work.mkdir(parents=True, exist_ok=True)
        pdf = work / f"{p.stem}.pdf"
        render.to_pdf(p, pdf)
        p = pdf
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(p))
    try:
        return [doc[i].render(scale=dpi / 72).to_pil().convert("RGB") for i in range(len(doc))]
    finally:
        doc.close()


def print_file(path, printer=None, copies=1, output=None, work=None):
    """Print through Windows (GDI), each page fitted to the printable area; `output` is the file a 'Print to PDF' printer
    writes (no Save dialog)."""
    import win32print
    import win32ui
    from PIL import ImageWin
    printer = printer or win32print.GetDefaultPrinter()
    imgs = pages_of(path, Path(work or Path(path).parent))
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer)
    pw, ph = hdc.GetDeviceCaps(8), hdc.GetDeviceCaps(10)  # HORZRES, VERTRES: the printable area in device pixels
    hdc.StartDoc(Path(path).name, str(output) if output else None)
    try:
        for _ in range(max(1, int(copies))):
            for im in imgs:
                hdc.StartPage()
                k = min(pw / im.width, ph / im.height)
                w, h = int(im.width * k), int(im.height * k)
                x, y = (pw - w) // 2, (ph - h) // 2
                ImageWin.Dib(im).draw(hdc.GetHandleOutput(), (x, y, x + w, y + h))
                hdc.EndPage()
        hdc.EndDoc()
    finally:
        hdc.DeleteDC()
    return len(imgs)


def parse(text, ctx):
    c = text.lower().strip(" ?.")
    if re.search(r"\b(?:which|what|list|show)\b.*\bprinters?\b|^printers$", c):
        return {"op": "printers"}
    if re.search(r"\bprint(?:ing)? queue\b|\bwhat(?:'s| is) printing\b", c):
        return {"op": "queue"}
    if re.match(r"^\s*print\b", c):
        from ai_pc.apps.appschat import find_file
        f = find_file(text, ctx, PICTURES | OFFICE | {".pdf"})
        if not f:
            return None
        names = [p["name"] for p in printers()]
        on = next((n for n in names if n.lower() in c), None)
        m = re.search(r"\b(\d+)\s+cop(?:y|ies)\b", c)
        return {"op": "print", "file": f, "printer": on, "copies": int(m.group(1)) if m else 1}
    return None


def preview(op, ctx):
    import win32print
    printer = op.get("printer") or win32print.GetDefaultPrinter()
    op["printer"] = printer
    return f"Ready to print {Path(op['file']).name}, {op.get('copies', 1)} cop{'y' if op.get('copies', 1) == 1 else 'ies'}, on {printer}" + \
        (" (it writes a PDF file, no paper)" if "pdf" in printer.lower() else "") + "."


def run(op, ctx):
    if op["op"] == "printers":
        ps = printers()
        return "Printers: " + "; ".join(p["name"] + (" (default)" if p["default"] else "") for p in ps) + "."
    if op["op"] == "queue":
        q = queue()
        return "Nothing is waiting to print." if not q else "; ".join(f"{j['document']} on {j['printer']} ({j['pages']} pages)" for j in q)
    if not op.get("confirmed"):
        return preview(op, ctx)
    out = Path(ctx["out"]) / "printed"
    out.mkdir(parents=True, exist_ok=True)
    to_pdf = "pdf" in (op.get("printer") or "").lower()
    dest = out / f"{Path(op['file']).stem}.printed.pdf" if to_pdf else None
    n = print_file(op["file"], op.get("printer"), op.get("copies", 1), dest, out / "work")
    if to_pdf:
        import time
        for _ in range(40):  # the spooler finishes the file a moment after
            if dest.exists() and dest.stat().st_size > 0:
                break
            time.sleep(0.25)
        from pypdf import PdfReader
        got = len(PdfReader(str(dest)).pages) if dest.exists() else 0
        return f"Printed {n} page(s) x {op.get('copies', 1)} to {dest} ({'checked: ' + str(got) + ' pages in the file' if got == n * op.get('copies', 1) else 'NOT right: ' + str(got) + ' pages'})."
    return f"Sent {n} page(s) x {op.get('copies', 1)} to {op['printer']}. Say 'print queue' to see it waiting."
