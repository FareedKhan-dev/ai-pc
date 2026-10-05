"""QR codes and barcodes: QR codes for a link, text, a Wi-Fi network (phones join by scanning) or a phone number;
product barcodes in Code 128 (any text: SKUs) and EAN-13 (shop products, check digit worked out); a sheet of labels
as a PDF for printing on A4. QR codes are read back with OpenCV's detector; barcodes are checked against their own
encoding.

  'qr code for https://khanelectronics.pk'   'wifi qr for KhanShop password secret123'   'barcode LED-TV-55'   'ean13 barcode 896000123456'
  'barcode labels for TV55, MOUNT, CABLE'
"""
import re
from pathlib import Path

NAME, LABEL = "codes", "QR codes (links, Wi-Fi, text) and barcodes (Code 128, EAN-13), label sheets"
EXAMPLES = ["qr code for https://khanelectronics.pk", "wifi qr for KhanShop password secret123", "barcode LED-TV-55"]
C128 = ["212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213", "221312", "231212", "112232", "122132",
        "122231", "113222", "123122", "123221", "223211", "221132", "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212",
        "322112", "322211", "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313", "231113", "231311",
        "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131", "311123", "311321",
        "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
        "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111", "111242", "121142", "121241", "114212",
        "124112", "124211", "411212", "421112", "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113",
        "411311", "113141", "114131", "311141", "411131", "211412", "211214", "211232", "2331112"]
EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
EAN_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
EAN_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
EAN_FIRST = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def code128(text):
    """Code 128 B: the bar/space widths, start to stop, with the checksum."""
    if any(not 32 <= ord(ch) <= 126 for ch in text):
        raise ValueError("Code 128 here takes plain letters, digits and signs")
    vals = [104] + [ord(ch) - 32 for ch in text]
    check = (vals[0] + sum(v * i for i, v in enumerate(vals[1:], 1))) % 103
    return "".join(C128[v] for v in vals + [check, 106])


def decode128(bits):
    """The text back out of Code 128 B bars, the checksum checked (for the check, independent of the writer's tables order)."""
    runs, cur, n = [], bits[0], 0
    for b in bits:
        if b == cur:
            n += 1
        else:
            runs.append(n)
            cur, n = b, 1
    runs.append(n)
    w = "".join(str(r) for r in runs)
    syms = [C128.index(w[i:i + 6]) for i in range(0, len(w) - 7, 6)]
    if syms[0] != 104 or w[-7:] != C128[106] or (syms[0] + sum(v * i for i, v in enumerate(syms[1:-1], 1))) % 103 != syms[-1]:
        raise ValueError("bad start, stop or checksum")
    return "".join(chr(v + 32) for v in syms[1:-1])


def ean13(digits):
    d = re.sub(r"\D", "", digits)
    if len(d) == 12:
        d += str((10 - sum(int(x) * (3 if i % 2 else 1) for i, x in enumerate(d)) % 10) % 10)
    if len(d) != 13 or str((10 - sum(int(x) * (3 if i % 2 else 1) for i, x in enumerate(d[:12])) % 10) % 10) != d[12]:
        raise ValueError("EAN-13 needs 12 digits (the 13th is worked out) or 13 with the right check digit")
    pattern = EAN_FIRST[int(d[0])]
    bits = "101" + "".join((EAN_L if pattern[i] == "L" else EAN_G)[int(x)] for i, x in enumerate(d[1:7])) + "01010" + \
        "".join(EAN_R[int(x)] for x in d[7:]) + "101"
    return d, bits


def widths_to_bits(widths):
    out, bar = "", True
    for w in widths:
        out += ("1" if bar else "0") * int(w)
        bar = not bar
    return out


def svg_bars(bits, label, module=2, height=70):
    w = (len(bits) + 20) * module
    rects = []
    i = 0
    while i < len(bits):
        if bits[i] == "1":
            j = i
            while j < len(bits) and bits[j] == "1":
                j += 1
            rects.append(f'<rect x="{(i + 10) * module}" y="10" width="{(j - i) * module}" height="{height}" fill="#000"/>')
            i = j
        else:
            i += 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{height + 40}" viewBox="0 0 {w} {height + 40}"><rect width="100%" height="100%" '
            f'fill="#fff"/>{"".join(rects)}<text x="{w / 2}" y="{height + 32}" text-anchor="middle" font-family="Consolas, monospace" font-size="16">'
            f"{label}</text></svg>")


def png_bars(bits, label, path, module=3, height=110):
    from PIL import Image, ImageDraw, ImageFont
    w = (len(bits) + 20) * module
    im = Image.new("L", (w, height + 50), 255)
    d = ImageDraw.Draw(im)
    for i, b in enumerate(bits):
        if b == "1":
            d.rectangle([(i + 10) * module, 10, (i + 11) * module - 1, 10 + height], fill=0)
    f = ImageFont.truetype("consola.ttf", 22) if Path("C:/Windows/Fonts/consola.ttf").exists() else ImageFont.load_default()
    d.text((w / 2, height + 26), label, fill=0, font=f, anchor="mm")
    im.save(path)
    return path


def wifi_payload(ssid, password, kind="WPA"):
    def esc(s):
        return re.sub(r"([\\;,:\"])", r"\\\1", s)
    return f"WIFI:T:{kind};S:{esc(ssid)};P:{esc(password)};;"


def read_qr(path):
    import cv2
    data, pts, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imread(str(path)))
    return data


def decode_ean13(bits):
    """The 13 digits back out of EAN-13 bars: guards, each half's codes, the first digit from the left half's L/G
    parity, and the check digit (the reader side of the encoding, for the check)."""
    if len(bits) != 95 or bits[:3] != "101" or bits[45:50] != "01010" or bits[-3:] != "101":
        raise ValueError("bad guard bars")
    left, right, parity = [], [], ""
    for i in range(6):
        sym = bits[3 + 7 * i: 10 + 7 * i]
        if sym in EAN_L:
            left.append(EAN_L.index(sym))
            parity += "L"
        elif sym in EAN_G:
            left.append(EAN_G.index(sym))
            parity += "G"
        else:
            raise ValueError("a left-half code is not EAN")
    for i in range(6):
        right.append(EAN_R.index(bits[50 + 7 * i: 57 + 7 * i]))
    d = str(EAN_FIRST.index(parity)) + "".join(map(str, left + right))
    if str((10 - sum(int(x) * (3 if i % 2 else 1) for i, x in enumerate(d[:12])) % 10) % 10) != d[12]:
        raise ValueError("bad check digit")
    return d


def parse(text, ctx):
    c = text.lower()
    m = re.search(r"\bwi-?fi\s+qr\b.*?\bfor\s+(\S+)\s+(?:password|pass|pw)\s+(\S+)", text, re.I)
    if m:
        return {"op": "qr", "data": wifi_payload(m.group(1), m.group(2)), "label": f"Wi-Fi {m.group(1)}"}
    m = re.match(r"^\s*(?:make\s+(?:a\s+)?)?qr(?:\s+code)?\s+(?:for|of|with)\s+(.+)$", text, re.I)
    if m:
        return {"op": "qr", "data": m.group(1).strip(), "label": m.group(1).strip()[:40]}
    m = re.match(r"^\s*(?:make\s+)?(?:an?\s+)?ean-?13\s+(?:barcode\s+)?(?:for\s+)?([\d\s-]{12,17})\s*$", text, re.I)
    if m:
        return {"op": "ean13", "data": m.group(1)}
    m = re.match(r"^\s*(?:make\s+)?barcode\s+labels?\s+(?:for\s+)?(.+)$", text, re.I)
    if m:
        return {"op": "labels", "items": [x.strip() for x in m.group(1).split(",") if x.strip()]}
    m = re.match(r"^\s*(?:make\s+(?:a\s+)?)?barcode\s+(?:for\s+)?(\S.*)$", text, re.I)
    if m:
        return {"op": "code128", "data": m.group(1).strip()}
    return None


def run(op, ctx):
    out = Path(ctx["out"]) / "codes"
    out.mkdir(parents=True, exist_ok=True)
    k = op["op"]
    if k == "qr":
        import segno
        stem = re.sub(r"[^\w-]+", "_", op["label"])[:40] or "qr"
        png = out / f"{stem}.png"
        q = segno.make(op["data"], error="m")
        q.save(str(png), scale=10, border=3)
        q.save(str(out / f"{stem}.svg"), scale=4, border=3)
        ok = read_qr(png) == op["data"]
        return f"QR code ({op['label']}): {png} and .svg ({'read back by a scanner: same text' if ok else 'NOT read back the same'})."
    if k == "ean13":
        d, bits = ean13(op["data"])
        png = png_bars(bits, d, out / f"EAN13_{d}.png")
        (out / f"EAN13_{d}.svg").write_text(svg_bars(bits, d), encoding="utf-8")
        ok = decode_ean13(bits) == d
        return f"EAN-13 barcode {d} (check digit {d[-1]}): {png} and .svg (" + \
            ("decoded back from its bars: guards, parity and check digit right" if ok else "NOT right when decoded") + ")."
    if k == "code128":
        bits = widths_to_bits(code128(op["data"]))
        stem = re.sub(r"[^\w-]+", "_", op["data"])[:40]
        png = png_bars(bits, op["data"], out / f"C128_{stem}.png")
        (out / f"C128_{stem}.svg").write_text(svg_bars(bits, op["data"]), encoding="utf-8")
        ok = decode128(bits) == op["data"]
        return f"Code 128 barcode for '{op['data']}': {png} and .svg (" + ("decoded back from its bars with its checksum" if ok else "NOT right") + ")."
    # labels: a sheet of Code 128 labels on A4, 3 across
    cells = "".join(f'<div class="l">{svg_bars(widths_to_bits(code128(x)), x)}</div>' for x in op["items"])
    page = out / "labels.html"
    page.write_text("<!doctype html><html><head><meta charset='utf-8'><style>@page{size:A4;margin:10mm}body{margin:0;display:grid;"
                    "grid-template-columns:repeat(3,1fr);gap:6mm}.l{border:1px dashed #bbb;padding:3mm;text-align:center}.l svg{width:100%;height:auto}"
                    f"</style></head><body>{cells}</body></html>", encoding="utf-8")
    from .. import headless
    pdf = out / "labels.pdf"
    headless.pdf(page, pdf, wait_ms=300, lane="apps")
    from pypdf import PdfReader
    n = len(PdfReader(str(pdf)).pages)
    return f"{len(op['items'])} barcode labels on {n} A4 page(s): {pdf} (print with 'print labels.pdf')."
