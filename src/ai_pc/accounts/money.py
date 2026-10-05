"""Money kept exact: whole paisa (integers) everywhere, rates as decimals, rounding half up to the paisa once per line,
amounts in words the Pakistani way (lakh and crore).

  to_paisa("1,97,200.50") -> 19720050      rs(19720050) -> "Rs 197,200.50"      words(19720050) -> "Rupees One Lakh Ninety-Seven
  Thousand Two Hundred and Fifty Paisa Only"      pct(85000_00, "18") -> 15300_00
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ONES = [
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


class MoneyError(ValueError):
    pass


def to_paisa(v):
    """'85,000', 'Rs 1,97,200.50', '2.5 lakh', '1 crore', 85000, Decimal('85000') -> whole paisa."""
    if isinstance(v, int):
        return v * 100
    if isinstance(v, Decimal):
        return int((v * 100).quantize(Decimal("1"), ROUND_HALF_UP))
    if isinstance(v, float):
        return int((Decimal(repr(v)) * 100).quantize(Decimal("1"), ROUND_HALF_UP))
    s = str(v or "").strip().lower().replace("rs.", "").replace("rs", "").replace("pkr", "").replace(",", "").replace("/-", "").strip()
    mult = Decimal(1)
    for word, k in (
        ("crore", 10_000_000),
        ("lakh", 100_000),
        ("lac", 100_000),
        ("thousand", 1000),
        ("k", 1000),
        ("million", 1_000_000),
        ("m", 1_000_000),
    ):
        if re.search(rf"\d\s*{word}$", s):
            s = re.sub(rf"\s*{word}$", "", s)
            mult = Decimal(k)
            break
    try:
        d = Decimal(s) * mult
    except InvalidOperation as e:
        raise MoneyError(f"'{v}' is not an amount") from e
    return int((d * 100).quantize(Decimal("1"), ROUND_HALF_UP))


def rupees(paisa):
    return Decimal(paisa) / 100


def pct(paisa, rate):
    """rate per cent of an amount, rounded half up to the paisa."""
    return int((Decimal(paisa) * Decimal(str(rate)) / 100).quantize(Decimal("1"), ROUND_HALF_UP))


def mul(paisa, qty):
    """An amount times a quantity (quantities may have decimals: 2.5 kg)."""
    return int((Decimal(paisa) * Decimal(str(qty))).quantize(Decimal("1"), ROUND_HALF_UP))


def rs(paisa, symbol="Rs ", grouping="international"):
    neg = paisa < 0
    p = abs(int(paisa))
    whole, fr = divmod(p, 100)
    if grouping == "lakh":
        s = str(whole)
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        body = ",".join(groups + [tail]) if groups else tail
    else:
        body = f"{whole:,}"
    out = f"{symbol}{body}" + (f".{fr:02d}" if fr else "")
    return f"-{out}" if neg else out


def _below_hundred(n):
    return ONES[n] if n < 20 else TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")


def _below_thousand(n):
    h, r = divmod(n, 100)
    parts = []
    if h:
        parts.append(ONES[h] + " Hundred")
    if r:
        parts.append(_below_hundred(r))
    return " ".join(parts)


def _words(n):
    if n == 0:
        return "Zero"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if n >= size:
            q, n = divmod(n, size)
            parts.append((_words(q) if q >= 100 and size == 10_000_000 else _below_thousand(q) if q >= 100 else _below_hundred(q)) + " " + name)
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def words(paisa):
    """'Rupees One Lakh Ninety-Seven Thousand Two Hundred Only' (lakh and crore, as Pakistani invoices write it)."""
    whole, fr = divmod(abs(int(paisa)), 100)
    s = "Rupees " + _words(whole)
    if fr:
        s += " and " + _below_hundred(fr) + " Paisa"
    return s + " Only"
