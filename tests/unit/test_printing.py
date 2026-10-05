"""Printing on a PC with no default printer, or with the print spooler off: requests are still read, and the answer
names the printers to choose from instead of failing."""

import pytest
import pywintypes
import win32print

from ai_pc.apps import printing


def _fails(*_args):
    raise pywintypes.error(1722, "EnumPrinters", "The RPC server is unavailable.")


def _no_default(*_args):
    raise RuntimeError("The default printer was not found.")  # what pywin32 raises when none is set


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "report.docx"
    path.write_bytes(b"not opened")
    return str(path)


@pytest.mark.parametrize("no_default", [_no_default, _fails])
def test_print_it_is_read_with_no_default_printer(monkeypatch, doc, no_default):
    monkeypatch.setattr(win32print, "GetDefaultPrinter", no_default)
    monkeypatch.setattr(win32print, "EnumPrinters", lambda *_args: [(0, "", "Microsoft Print to PDF", "")])
    op = printing.parse("print it", {"files": {"report.docx": doc}})
    assert op == {"op": "print", "file": doc, "printer": None, "copies": 1}
    text = printing.preview(op, {})
    assert op["blocked"]
    assert "no default printer" in text and "Microsoft Print to PDF" in text


def test_a_named_printer_is_used_with_no_default_printer(monkeypatch, doc):
    monkeypatch.setattr(win32print, "GetDefaultPrinter", _no_default)
    monkeypatch.setattr(win32print, "EnumPrinters", lambda *_args: [(0, "", "Microsoft Print to PDF", "")])
    op = printing.parse("print it on microsoft print to pdf, 2 copies", {"files": {"report.docx": doc}})
    assert op["printer"] == "Microsoft Print to PDF" and op["copies"] == 2
    assert printing.preview(op, {}).startswith("Ready to print report.docx, 2 copies")
    assert not op.get("blocked")


def test_with_the_spooler_off_there_are_no_printers(monkeypatch, doc):
    monkeypatch.setattr(win32print, "GetDefaultPrinter", _fails)
    monkeypatch.setattr(win32print, "EnumPrinters", _fails)
    assert printing.printers() == []
    op = printing.parse("print it", {"files": {"report.docx": doc}})
    assert printing.preview(op, {}) == "This PC has no printer, so there is nothing to print on."
    with pytest.raises(RuntimeError, match="no default printer"):
        printing.print_file(doc)
