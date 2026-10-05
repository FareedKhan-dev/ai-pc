"""Lengths as builders in Pakistan say them: feet and inches (12'-6"), plots in marla and kanal, and metric for parts.

  ft_in(150) -> "12'-6\""          inches in, the architect's way out
  parse_len("12'6\"") -> 150.0     inches; also "12.5 ft", "12 ft 6 in", "3.5 m", "350 mm", "12 by 14" (feet)
  plot_of(5, "marla") -> (25, 45)  a typical plot (width x depth, feet) for that size
"""
import math
import re

MARLA_SQFT = 225.0  # most Lahore housing societies (LDA, DHA, Bahria); Islamabad / the revenue marla is 272.25
PLOTS = {  # marla (225 sq ft) -> typical width x depth in feet in Pakistani housing societies
    3: (20, 34), 4: (20, 45), 5: (25, 45), 6: (30, 45), 7: (30, 52), 8: (30, 60), 10: (35, 65), 12: (40, 68), 14: (40, 80),
    16: (45, 80), 20: (50, 90), 40: (75, 120)}
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
         "fourteen": 14, "sixteen": 16, "twenty": 20, "half": 0.5, "a": 1, "an": 1}


def ft_in(inches, zero_inches=True):
    """150 -> 12'-6"; to the nearest half inch."""
    v = round(abs(float(inches)) * 2) / 2
    ft = int(v // 12)
    inch = v - ft * 12
    s = f"{int(inch)}" if inch == int(inch) else f"{int(inch)}½"
    sign = "-" if inches < 0 else ""
    return f"{sign}{ft}'-{s}\"" if (inch or zero_inches) else f"{sign}{ft}'"


def sq_ft(area_in2):
    return area_in2 / 144.0


def parse_len(s, default="ft"):
    """A length in inches from what a person writes."""
    t = str(s).strip().lower().replace("’", "'").replace("”", '"').replace("″", '"').replace("′", "'")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:'|ft|feet|foot)\s*-?\s*(\d+(?:\.\d+)?)?\s*(?:\"|in|inch|inches)?", t)
    if m:
        return float(m.group(1)) * 12 + (float(m.group(2)) if m.group(2) else 0)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(\"|in|inch|inches|mm|cm|m|meters?|metres?)", t)
    if m:
        v, u = float(m.group(1)), m.group(2)
        return v if u in ('"', "in", "inch", "inches") else v / 25.4 if u == "mm" else v / 2.54 if u == "cm" else v / 0.0254
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", t)
    if m:
        v = float(m.group(1))
        return v * 12 if default == "ft" else v if default == "in" else v / 25.4 if default == "mm" else v / 0.0254
    raise ValueError(f"not a length: {s!r}")


def plot_of(n, unit="marla"):
    """A typical plot (width, depth in feet) for n marla or kanal; sizes between the standard ones are scaled."""
    marla = n * 20 if unit.startswith("kanal") else n
    if marla in PLOTS:
        return PLOTS[marla]
    near = min(PLOTS, key=lambda k: abs(k - marla))
    w, d = PLOTS[near]
    s = math.sqrt(marla / near)
    return round(w * s), round(d * s)


def marla_of(w_ft, d_ft):
    return w_ft * d_ft / MARLA_SQFT
