"""Workbooks as clients send them: a title above the table, dates typed as text in three styles, prices with 'Rs' and
commas, city names in four spellings, a duplicated order, an empty row inside the data, a price list on another sheet.
Written with openpyxl (that is the client's tool here; the agent edits them only through Excel)."""

import datetime as dt
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ORDERS = [  # id, date, customer, city, product, qty, unit price, status, due date
    ("SO-1001", "03/01/2026", "Ali Traders", "Lahore", "Solar Panel 550W", 4, "Rs 42,000", "Paid", dt.datetime(2026, 1, 20)),
    ("SO-1002", "07/01/2026", "  Noor Electric", "lahore", "Inverter 6kW", 1, "185,000", "Paid", dt.datetime(2026, 1, 25)),
    ("SO-1003", "12-01-2026", "Karachi Power House", "Karachi", "Battery 200Ah", 6, "52,500", "Pending", dt.datetime(2026, 2, 1)),
    ("SO-1004", "2026-01-19", "Bilal & Sons", " LAHORE", "Solar Panel 550W", 10, 41500, "Paid", dt.datetime(2026, 2, 5)),
    ("SO-1005", "25 Jan 2026", "Capital Solar", "Islamabad", "Inverter 10kW", 2, "Rs 310,000", "Pending", dt.datetime(2026, 2, 10)),
    ("SO-1006", dt.datetime(2026, 2, 2), "Ali Traders", "Lahore", "Mounting Kit", 8, "6,800", "paid", dt.datetime(2026, 2, 18)),
    ("SO-1007", "05/02/2026", "Sea View Homes", "karachi ", "Solar Panel 550W", 12, "41,000", "Cancelled", dt.datetime(2026, 2, 22)),
    ("SO-1008", "09/02/2026", "Capital Solar", "Islamabad ", "Battery 200Ah", 4, "53,000", "Paid", dt.datetime(2026, 2, 26)),
    ("SO-1009", "14-02-2026", "Noor Electric", "Lahore", "Solar Panel 550W", 20, "40,500", "Pending", dt.datetime(2026, 3, 3)),
    ("SO-1010", "2026-02-21", "Karachi Power House", "KARACHI", "Inverter 6kW", 3, "184,000", "Paid", dt.datetime(2026, 3, 8)),
    ("SO-1011", "28 Feb 2026", "Margalla Builders", "Islamabad", "Mounting Kit", 15, "6,500", "Pending", dt.datetime(2026, 3, 15)),
    ("SO-1012", "04/03/2026", "Bilal & Sons", "Lahore", "Battery 200Ah", 8, "52,000", "Paid", dt.datetime(2026, 3, 20)),
    None,  # an empty row inside the data
    ("SO-1013", "11/03/2026", "Sea View Homes", "Karachi", "Inverter 10kW", 1, "Rs 315,000", "Pending", dt.datetime(2026, 3, 28)),
    ("SO-1014", "18-03-2026", "Ali Traders", "lahore", "Solar Panel 550W", 16, "40,800", "Paid", dt.datetime(2026, 4, 2)),
    ("SO-1015", "2026-03-24", "Capital Solar", "Islamabad", "Mounting Kit", 10, "6,600", "Pending", dt.datetime(2026, 4, 9)),
    ("SO-1015", "2026-03-24", "Capital Solar", "Islamabad", "Mounting Kit", 10, "6,600", "Pending", dt.datetime(2026, 4, 9)),  # typed twice
    ("SO-1016", "30 Mar 2026", "Margalla Builders", "Islamabad", "Battery 200Ah", 5, "52,800", "Paid", dt.datetime(2026, 4, 14)),
]
PRODUCTS = [
    ("Solar Panel 550W", "Panels", 34000),
    ("Inverter 6kW", "Inverters", 150000),
    ("Inverter 10kW", "Inverters", 255000),
    ("Battery 200Ah", "Storage", 43000),
    ("Mounting Kit", "Accessories", 4200),
]


def sales_book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws["A1"] = "Northwind Solar - Orders Q1 2026"
    ws["A1"].font = Font(bold=True, size=14)
    heads = ["Order ID", "Date", "Customer", "City", "Product", "Qty", "Unit Price", "Status", "Due Date"]
    for j, h in enumerate(heads, start=1):
        c = ws.cell(3, j, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5597")
    r = 4
    for row in ORDERS:
        if row is not None:
            for j, v in enumerate(row, start=1):
                c = ws.cell(r, j, v)
                if isinstance(v, dt.datetime):
                    c.number_format = "dd-mmm-yyyy"
        r += 1
    for col, w in zip("ABCDEFGHI", (10, 12, 22, 12, 18, 6, 12, 11, 12)):
        ws.column_dimensions[col].width = w
    p = wb.create_sheet("Products")
    for j, h in enumerate(["Product", "Category", "Cost"], start=1):
        p.cell(1, j, h).font = Font(bold=True)
    for i, row in enumerate(PRODUCTS, start=2):
        for j, v in enumerate(row, start=1):
            p.cell(i, j, v)
    n = wb.create_sheet("Notes")
    n["A1"] = "Prices are per unit, before tax. Due dates are 15 days after the order unless agreed otherwise."
    wb.save(str(path))
    return Path(path)


if __name__ == "__main__":
    print(sales_book(Path(__file__).resolve().parents[2] / "out/docs/_tests/sales_messy.xlsx"))
