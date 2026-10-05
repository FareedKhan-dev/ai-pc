"""Python projects for PyCharm and VS Code: a package, unittest tests, pyproject.toml and the project's own .venv (made by
the Python 3.11 kept in tools/python, without pip, so nothing is downloaded). Tested and run here on the hidden desktop;
a Python project given is tested the same way (pytest if its .venv has it, else unittest), each failure with its file
and line.

  "pycharm python project called 'Shop'"   'python app called Stock'   'pycharm test C:\\code\\tool\\pyproject.toml'
"""

import re
import shutil
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "pycharm", "Python (PyCharm, VS Code): projects with their own .venv and tests, tested and run; test any Python project"
EXAMPLES = ["pycharm python project called 'Shop'", "python app called Stock", "pycharm test pyproject.toml"]
PYTHON = next(iter(sorted((ROOT / "tools" / "python").glob("cpython-3*/python.exe"))), None) if (ROOT / "tools" / "python").exists() else None

PYPROJECT = """[project]
name = "{pkg}"
version = "0.1.0"
description = "What the shop holds: stock, sales, value"
requires-python = ">=3.11"

[project.scripts]
{pkg} = "{pkg}.__main__:main"
"""
INVENTORY = '''"""What the shop holds: add stock, sell it, its value, what is running low."""
from dataclasses import dataclass


@dataclass
class Product:
    name: str
    price: int
    quantity: int

    @property
    def value(self) -> int:
        return self.price * self.quantity


class Inventory:
    def __init__(self) -> None:
        self._items: dict[str, Product] = {}

    def add(self, p: Product) -> None:
        """Puts stock in; the same name (in any case) adds to its quantity and takes the new price."""
        if not p.name.strip():
            raise ValueError("A product needs a name.")
        if p.price < 0 or p.quantity < 0:
            raise ValueError("Price and quantity cannot be negative.")
        old = self._items.get(p.name.lower())
        if old:
            old.price = p.price
            old.quantity += p.quantity
        else:
            self._items[p.name.lower()] = Product(p.name, p.price, p.quantity)

    def sell(self, name: str, quantity: int) -> bool:
        """Takes quantity out; False if there is not that much."""
        p = self._items.get(name.lower())
        if p is None or quantity <= 0 or p.quantity < quantity:
            return False
        p.quantity -= quantity
        return True

    @property
    def items(self) -> list[Product]:
        return list(self._items.values())

    def total_value(self) -> int:
        return sum(p.value for p in self._items.values())

    def low_stock(self, below: int) -> list[Product]:
        """The products with fewer than below in stock, scarcest first."""
        return sorted((p for p in self._items.values() if p.quantity < below), key=lambda p: p.quantity)
'''
MAIN = """from .inventory import Inventory, Product


def main() -> None:
    inv = Inventory()
    for name, price, quantity in [("Ceiling fan", 4500, 3), ("Steam iron", 3200, 2), ("Kettle", 2100, 5)]:
        inv.add(Product(name, price, quantity))
    inv.sell("Kettle", 4)
    for p in inv.items:
        print(f"{p.name:<12} {p.quantity:>3} x Rs {p.price:,}")
    print(f"Total value: Rs {inv.total_value():,}")
    print("Low stock: " + ", ".join(p.name for p in inv.low_stock(3)))


if __name__ == "__main__":
    main()
"""
TESTS = """import unittest

from {pkg}.inventory import Inventory, Product


class InventoryTest(unittest.TestCase):
    def test_adding_the_same_product_adds_to_its_stock(self):
        inv = Inventory()
        inv.add(Product("Fan", 4500, 3))
        inv.add(Product("fan", 4600, 2))
        self.assertEqual(len(inv.items), 1)
        self.assertEqual((inv.items[0].quantity, inv.items[0].price), (5, 4600))

    def test_negative_quantities_are_refused(self):
        with self.assertRaises(ValueError):
            Inventory().add(Product("Iron", 3200, -1))

    def test_selling_more_than_in_stock_fails(self):
        inv = Inventory()
        inv.add(Product("Kettle", 2100, 2))
        self.assertFalse(inv.sell("Kettle", 3))
        self.assertTrue(inv.sell("Kettle", 2))
        self.assertEqual(inv.items[0].quantity, 0)

    def test_total_value_is_price_times_quantity(self):
        inv = Inventory()
        inv.add(Product("Fan", 4500, 3))
        inv.add(Product("Iron", 3200, 2))
        self.assertEqual(inv.total_value(), 19900)

    def test_low_stock_lists_the_scarcest_first(self):
        inv = Inventory()
        for name, quantity in [("A", 5), ("B", 1), ("C", 9)]:
            inv.add(Product(name, 1, quantity))
        self.assertEqual([p.name for p in inv.low_stock(6)], ["B", "A"])


if __name__ == "__main__":
    unittest.main()
"""


def run_py(python, *args, cwd, timeout=600):
    import os

    from ai_pc.core import hidden_desktop

    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    rc, out, err, timed_out = hidden_desktop.run([str(python), *map(str, args)], timeout=timeout, cwd=str(cwd), env=env)
    return rc == 0 and not timed_out, out + err


def venv_python(folder):
    for name in (".venv", "venv", "env"):
        p = Path(folder) / name / "Scripts" / "python.exe"
        if p.exists():
            return p
    return PYTHON


def failures(text):
    """'test_x: file.py:12 message' for each failed test, from unittest's or pytest's report."""
    out = []
    for m in re.finditer(
        r'^(?:FAIL|ERROR): (\w+).*?\n(?:.*\n)*?\s*File "([^"]+)", line (\d+).*\n(?:.*\n)*?(\w+(?:Error|Exception)?: .+)$', text, re.M
    ):
        out.append(f"{m.group(1)}: {Path(m.group(2)).name}:{m.group(3)} {m.group(4).strip()}")
    for m in re.finditer(r"^([^\s:]+\.py):(\d+): (\w+(?:Error|Exception))", text, re.M):  # pytest's short form
        out.append(f"{Path(m.group(1)).name}:{m.group(2)} {m.group(3)}")
    for m in re.finditer(r'File "([^"]+)", line (\d+)\n.*\n.*\n?SyntaxError: (.+)', text):
        out.append(f"{Path(m.group(1)).name}:{m.group(2)} SyntaxError: {m.group(3)}")
    return list(dict.fromkeys(out))


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bpycharm\b|\bpython\s+(?:project|app|program|package|cli)\b|\bpyproject\.toml\b", c):
        return None
    f = find_file(text, ctx, {".toml", ".py", ".txt"})
    if f and re.search(r"\btest\b|\bbuild\b|\bcheck\b|\brun\b", c):
        return {"op": "test", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9_]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bprogram\b|\bpackage\b|\bcli\b", c) else None


def run(op, ctx):
    if not PYTHON:
        return "Python is not in tools/python."
    if op["op"] == "test":
        folder = Path(op["file"]).resolve().parent
        py = venv_python(folder)
        has_pytest, _ = run_py(py, "-c", "import pytest", cwd=folder)
        ok, out = run_py(py, "-m", "pytest", "-q", cwd=folder) if has_pytest else run_py(py, "-m", "unittest", "discover", "-v", cwd=folder)
        ran = re.search(r"Ran (\d+) tests?|(\d+) passed", out)
        count = int(ran.group(1) or ran.group(2)) if ran else 0
        if not ok:
            bad = failures(out)
            return f"Tests of {folder.name} FAILED" + (": " + "; ".join(bad[:8]) if bad else ": " + out.strip()[-300:]) + "."
        return f"{folder.name}: {count} tests passed ({'pytest' if has_pytest else 'unittest'}, {py.parent.parent.name if py != PYTHON else 'Python 3.11'})."
    name = op["name"]
    pkg = re.sub(r"[^a-z0-9_]", "", name.lower()) or "app"
    if pkg[0].isdigit() or pkg in {"test", "tests", "unittest", "json", "os", "sys", "time", "random", "string", "types", "typing"}:
        pkg = "app_" + pkg
    out = (Path(ctx["out"]) / "pycharm" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    files = {
        "pyproject.toml": PYPROJECT.format(pkg=pkg),
        f"{pkg}/__init__.py": '"""Shop inventory."""\n',
        f"{pkg}/inventory.py": INVENTORY,
        f"{pkg}/__main__.py": MAIN,
        "tests/__init__.py": "",
        "tests/test_inventory.py": TESTS.format(pkg=pkg),
        ".gitignore": ".venv/\n__pycache__/\n.idea/\n*.egg-info/\n",
    }
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text, encoding="utf-8")
    ok_v, venv_log = run_py(PYTHON, "-m", "venv", "--without-pip", ".venv", cwd=out)
    py = out / ".venv" / "Scripts" / "python.exe"
    ok_t, tests = run_py(py, "-m", "unittest", "discover", "-v", cwd=out) if py.exists() else (False, venv_log)
    ok_r, ran = run_py(py, "-m", pkg, cwd=out) if py.exists() else (False, "")
    ok_c, comp = run_py(py, "-m", "compileall", "-q", pkg, "tests", cwd=out) if py.exists() else (False, "")
    count = int((re.search(r"Ran (\d+) tests?", tests) or [0, 0])[1])
    checks = [
        ("its own .venv was made (Python 3.11, from tools/python)", ok_v and py.exists()),
        (f"unittest: {count if ok_t else 0} of 5 tests passed", ok_t and count == 5),
        (f"python -m {pkg} runs and prints the stock's value (Rs 22,000)", ok_r and "Total value: Rs 22,000" in ran),
        ("every file compiles", ok_c),
    ]
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad = [w for w, good in checks if not good]
    return (
        f"Python project {out} ({pkg}/ package, tests/, pyproject.toml, .venv; open the folder in PyCharm or VS Code). "
        + (f"Output: {' | '.join(ln.strip() for ln in ran.strip().splitlines()[-2:])}. " if ran else "")
        + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + "; ".join(failures(tests)[:5]))
    )
