"""Small circuits worked out from words, as parts and the nets joining their pins (used by the KiCad program): an LED with
its resistor, a voltage divider, a 555 blinker. Values come from the standard E12/E24 series and every choice is
explained (current, power, real output voltage, real frequency)."""

import math
import re

E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
VF = {"red": 2.0, "orange": 2.0, "yellow": 2.1, "green": 2.2, "blue": 3.0, "white": 3.0}
FOOT = {
    "R": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
    "LED": "LED_THT:LED_D5.0mm",
    "C": "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
    "CP": "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm",
    "555": "Package_DIP:DIP-8_W7.62mm",
    "J": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
}


def series(value, table, up=False):
    """The nearest (or next larger) standard value."""
    if value <= 0:
        return table[0]
    exp = math.floor(math.log10(value))
    options = [v * 10**e for e in (exp - 1, exp, exp + 1) for v in table]
    if up:
        return min(v for v in options if v >= value * 0.999)
    return min(options, key=lambda v: abs(math.log(v / value)))


def ohms(v):
    for unit, k in (("M", 1e6), ("k", 1e3)):
        if v >= k:
            s = f"{v / k:.3g}"
            return s.replace(".", unit) if "." in s else s + unit
    return f"{v:.3g}"


def farads(v):
    for unit, k in (("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if v >= k * 0.999:
            s = f"{v / k:.3g}"
            return s + unit
    return f"{v:g}"


def value(s):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([pnumkM]?)", s.strip())
    return float(m.group(1)) * {"": 1, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}[m.group(2)] if m else None


def led(supply=5.0, colour="red", current=0.015):
    vf = VF.get(colour, 2.0)
    r = series((supply - vf) / current, E12, up=True)
    i = (supply - vf) / r
    p = i * i * r
    parts = [
        ("J1", "Connector_Generic:Conn_01x02", f"{supply:g}V in", FOOT["J"], {"1": "VCC", "2": "GND"}),
        ("R1", "Device:R", ohms(r), FOOT["R"], {"1": "VCC", "2": "LED_A"}),
        ("D1", "Device:LED", f"{colour} LED", FOOT["LED"], {"2": "LED_A", "1": "GND"}),
    ]
    notes = [
        f"R1 = ({supply:g} V - {vf:g} V LED) / {current * 1000:g} mA = {(supply - vf) / current:.0f} ohm -> {ohms(r)} (E12, next up)",
        f"LED current {i * 1000:.1f} mA",
        f"R1 heats {p * 1000:.0f} mW ({'a 1/4 W resistor is fine' if p < 0.125 else 'use a 1/2 W resistor'})",
    ]
    return {"title": f"{colour.title()} LED on {supply:g} V", "parts": parts, "notes": notes, "facts": {"current_mA": i * 1000, "R": r, "power_W": p}}


def divider(vin=12.0, vout=5.0):
    r1 = 10e3
    r2 = series(r1 * vout / (vin - vout), E24)
    real = vin * r2 / (r1 + r2)
    parts = [
        ("J1", "Connector_Generic:Conn_01x02", f"{vin:g}V in", FOOT["J"], {"1": "VIN", "2": "GND"}),
        ("R1", "Device:R", ohms(r1), FOOT["R"], {"1": "VIN", "2": "VOUT"}),
        ("R2", "Device:R", ohms(r2), FOOT["R"], {"1": "VOUT", "2": "GND"}),
        ("J2", "Connector_Generic:Conn_01x02", f"{vout:g}V out", FOOT["J"], {"1": "VOUT", "2": "GND"}),
    ]
    notes = [
        f"Vout = {vin:g} V x R2 / (R1 + R2) = {real:.2f} V with R1 {ohms(r1)}, R2 {ohms(r2)} (E24)",
        f"current through the divider {vin / (r1 + r2) * 1000:.2f} mA (light loads only)",
    ]
    return {"title": f"Voltage divider {vin:g} V to {vout:g} V", "parts": parts, "notes": notes, "facts": {"vout": real, "R1": r1, "R2": r2}}


def blinker(freq=1.0, supply=9.0):
    c = 10e-6 if freq < 20 else 100e-9
    r1 = 1e3
    r2 = series(max(1e3, (1.44 / (freq * c) - r1) / 2), E24)
    real = 1.44 / ((r1 + 2 * r2) * c)
    duty = (r1 + r2) / (r1 + 2 * r2)
    r3 = series((supply - 2.0) / 0.015, E12, up=True)
    led_ma = (supply - 2.0 - 1.5) / r3 * 1000  # the 555's output sits about 1.5 V under the supply
    parts = [
        ("J1", "Connector_Generic:Conn_01x02", f"{supply:g}V in", FOOT["J"], {"1": "VCC", "2": "GND"}),
        (
            "U1",
            "Timer:NE555P",
            "NE555P",
            FOOT["555"],
            {"1": "GND", "2": "TRIG", "3": "OUT", "4": "VCC", "5": "CTRL", "6": "TRIG", "7": "DIS", "8": "VCC"},
        ),
        ("R1", "Device:R", ohms(r1), FOOT["R"], {"1": "VCC", "2": "DIS"}),
        ("R2", "Device:R", ohms(r2), FOOT["R"], {"1": "DIS", "2": "TRIG"}),
        ("C1", "Device:C_Polarized", farads(c) + "F", FOOT["CP"] if c >= 1e-6 else FOOT["C"], {"1": "TRIG", "2": "GND"}),
        ("C2", "Device:C", "10nF", FOOT["C"], {"1": "CTRL", "2": "GND"}),
        ("R3", "Device:R", ohms(r3), FOOT["R"], {"1": "OUT", "2": "LED_A"}),
        ("D1", "Device:LED", "red LED", FOOT["LED"], {"2": "LED_A", "1": "GND"}),
    ]
    notes = [
        f"f = 1.44 / ((R1 + 2 R2) C1) = {real:.2f} Hz with R1 {ohms(r1)}, R2 {ohms(r2)}, C1 {farads(c)}F",
        f"on {duty:.0%} of the time",
        f"R3 {ohms(r3)} sets the LED to about {led_ma:.0f} mA",
    ]
    return {
        "title": f"555 LED blinker {freq:g} Hz",
        "parts": parts,
        "notes": notes,
        "facts": {"freq": real, "duty": duty, "R2": r2, "C": c},
        "power_flags": ["VCC", "GND"],
    }


def from_words(text):
    c = text.lower()
    volts = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*v\b", c)]
    if re.search(r"\b555\b|\bblink", c):
        f = re.search(r"(\d+(?:\.\d+)?)\s*hz\b", c)
        return blinker(float(f.group(1)) if f else 1.0, volts[0] if volts else 9.0)
    if re.search(r"\bdivider\b", c):
        if len(volts) >= 2:
            return divider(max(volts[:2]), min(volts[:2]))
        return divider()
    if re.search(r"\bled\b", c):
        colour = next((k for k in VF if re.search(rf"\b{k}\b", c)), "red")
        ma = re.search(r"(\d+(?:\.\d+)?)\s*ma\b", c)
        return led(volts[0] if volts else 5.0, colour, float(ma.group(1)) / 1000 if ma else 0.015)
    return None
