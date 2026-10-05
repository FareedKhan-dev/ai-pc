"""Design systems for documents: what a professional designer fixes once and applies everywhere, so every page is
consistent. Sizes in points, colours as hex RGB, margins in cm.

  body / head     the two font families (installed on this PC; a missing one falls back to Calibri)
  size, line      body size and line spacing (1.15 business, 1.5 for university work)
  after           space after a paragraph; headings get more space above than below (they belong to what follows)
  title, h1-h3    the type scale: each level clearly smaller than the one above
  accent          the one colour that carries the design (headings, table headers, charts, rules)
  justify         justified body text (academic), else ragged right (easier to read)
  numbered        "1 / 1.1 / 1.1.1" heading numbers (academic, contracts)
  table           header fill and text, row stripes, border colour, table text size
"""

import copy
import re
import winreg

THEMES = {
    "corporate": {
        "body": "Calibri",
        "head": "Calibri",
        "size": 11,
        "line": 1.15,
        "after": 6,
        "accent": "1F3864",
        "accent2": "2E75B6",
        "head_color": "1F3864",
        "muted": "595959",
        "title": 28,
        "h1": 16,
        "h2": 13,
        "h3": 11.5,
        "justify": False,
        "numbered": False,
        "margins": 2.5,
        "rule": True,
        "table": {"header_fill": "1F3864", "header_text": "FFFFFF", "stripe": "EEF3FA", "border": "BFC9D9", "size": 10},
        "chart": ["1F3864", "2E75B6", "9DC3E6", "F4B183", "A9D18E", "FFD966"],
    },
    "academic": {
        "body": "Times New Roman",
        "head": "Times New Roman",
        "size": 12,
        "line": 1.5,
        "after": 6,
        "accent": "000000",
        "accent2": "404040",
        "head_color": "000000",
        "muted": "404040",
        "title": 20,
        "h1": 14,
        "h2": 12,
        "h3": 12,
        "justify": True,
        "numbered": True,
        "margins": 2.54,
        "rule": False,
        "table": {"header_fill": "D9D9D9", "header_text": "000000", "stripe": None, "border": "000000", "size": 10.5},
        "chart": ["404040", "7F7F7F", "A6A6A6", "262626", "BFBFBF", "595959"],
    },
    "modern": {
        "body": "Segoe UI",
        "head": "Segoe UI Semibold",
        "size": 10.5,
        "line": 1.2,
        "after": 8,
        "accent": "0F766E",
        "accent2": "14B8A6",
        "head_color": "0F766E",
        "muted": "5F6B6A",
        "title": 30,
        "h1": 17,
        "h2": 13.5,
        "h3": 11,
        "justify": False,
        "numbered": False,
        "margins": 2.2,
        "rule": False,
        "table": {"header_fill": "0F766E", "header_text": "FFFFFF", "stripe": "ECFDF8", "border": "CFDCDA", "size": 9.5},
        "chart": ["0F766E", "14B8A6", "99F6E4", "F59E0B", "64748B", "FB7185"],
    },
    "elegant": {
        "body": "Georgia",
        "head": "Georgia",
        "size": 11,
        "line": 1.2,
        "after": 8,
        "accent": "7B2D26",
        "accent2": "A0522D",
        "head_color": "7B2D26",
        "muted": "5A5A5A",
        "title": 28,
        "h1": 16,
        "h2": 13,
        "h3": 11.5,
        "justify": False,
        "numbered": False,
        "margins": 2.5,
        "rule": True,
        "table": {"header_fill": "7B2D26", "header_text": "FFFFFF", "stripe": "F8F1EF", "border": "D9C5C1", "size": 10},
        "chart": ["7B2D26", "A0522D", "D6A99A", "5A5A5A", "C9B79C", "8C6A5D"],
    },
    "minimal": {
        "body": "Arial",
        "head": "Arial",
        "size": 10.5,
        "line": 1.2,
        "after": 6,
        "accent": "222222",
        "accent2": "555555",
        "head_color": "111111",
        "muted": "666666",
        "title": 24,
        "h1": 15,
        "h2": 12.5,
        "h3": 11,
        "justify": False,
        "numbered": False,
        "margins": 2.5,
        "rule": False,
        "table": {"header_fill": "F2F2F2", "header_text": "111111", "stripe": None, "border": "BFBFBF", "size": 9.5},
        "chart": ["222222", "666666", "999999", "C00000", "BBBBBB", "444444"],
    },
    "warm": {
        "body": "Cambria",
        "head": "Calibri",
        "size": 11,
        "line": 1.15,
        "after": 6,
        "accent": "B45309",
        "accent2": "D97706",
        "head_color": "92400E",
        "muted": "5C4A3A",
        "title": 28,
        "h1": 16,
        "h2": 13,
        "h3": 11.5,
        "justify": False,
        "numbered": False,
        "margins": 2.5,
        "rule": True,
        "table": {"header_fill": "B45309", "header_text": "FFFFFF", "stripe": "FEF6E7", "border": "E8CFA9", "size": 10},
        "chart": ["B45309", "D97706", "FCD34D", "78716C", "65A30D", "0E7490"],
    },
}

DEFAULT_FOR = {
    "report": "corporate",
    "proposal": "corporate",
    "business_plan": "corporate",
    "manual": "corporate",
    "invoice": "corporate",
    "quotation": "corporate",
    "assignment": "academic",
    "essay": "academic",
    "thesis": "academic",
    "research": "academic",
    "letter": "elegant",
    "application": "elegant",
    "certificate": "elegant",
    "cv": "modern",
    "newsletter": "modern",
    "minutes": "minimal",
    "memo": "minimal",
    "notice": "minimal",
    "contract": "minimal",
    "agenda": "minimal",
    "other": "corporate",
}

COLOUR_WORDS = {
    "blue": "1F4E79",
    "navy": "1F3864",
    "green": "2E7D32",
    "teal": "0F766E",
    "red": "B71C1C",
    "maroon": "7B2D26",
    "purple": "5B2C83",
    "orange": "C2410C",
    "gold": "B8860B",
    "brown": "6D4C41",
    "black": "111111",
    "grey": "555555",
    "gray": "555555",
    "pink": "BE185D",
    "dark green": "1B5E20",
    "sky blue": "0277BD",
    "olive": "556B2F",
}

_FONTS = None


def installed_fonts():
    """Font family names installed on this PC (from the Windows font registry)."""
    global _FONTS
    if _FONTS is None:
        names = set()
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts", 0, winreg.KEY_READ) as k:
                    i = 0
                    while True:
                        try:
                            n = winreg.EnumValue(k, i)[0]
                        except OSError:
                            break
                        i += 1
                        for part in n.split("&"):
                            names.add(re.sub(r"\s*\((?:TrueType|OpenType|All res)\)\s*$", "", part.strip(), flags=re.I).lower())
            except OSError:
                continue
        _FONTS = names
    return _FONTS


def has_font(name):
    fonts = installed_fonts()
    n = str(name or "").lower()
    return n in fonts or any(f.startswith(n + " ") for f in fonts)


def get(name=None, accent=None, doctype=None):
    """A copy of a theme (by name, else the default for the document type), with an accent colour if asked and
    every font checked against the fonts installed here."""
    name = name if name in THEMES else DEFAULT_FOR.get(doctype or "other", "corporate")
    th = copy.deepcopy(THEMES[name])
    th["name"] = name
    if accent:
        a = str(accent).strip().lower()
        hx = COLOUR_WORDS.get(a) or (a.lstrip("#").upper() if re.fullmatch(r"#?[0-9a-fA-F]{6}", a) else None)
        if hx:
            th["accent"] = th["head_color"] = hx
            if th["table"]["header_fill"] not in ("D9D9D9", "F2F2F2"):
                th["table"]["header_fill"] = hx
            th["chart"] = [hx] + [c for c in th["chart"] if c != hx]
    for k in ("body", "head"):
        if not has_font(th[k]):
            th[k] = "Calibri" if has_font("Calibri") else "Arial"
    return th
