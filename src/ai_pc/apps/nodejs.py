"""Node.js / TypeScript projects for WebStorm and VS Code, with the Node.js already on this PC (24+ runs TypeScript files
itself): package.json, tsconfig.json, a TypeScript module, tests for Node's own test runner and a program; nothing is
downloaded (no npm install). Tested and run on the hidden desktop; a project given (package.json) is tested the same
way, each failure with its file and line.

  "webstorm typescript project called 'Shop'"   'node app called Stock'   'node test package.json'
"""

import json
import os
import re
import shutil
from pathlib import Path

NAME, LABEL = (
    "nodejs",
    "Node.js / TypeScript (WebStorm, VS Code): projects tested by Node's own runner and run, no npm downloads; test any package.json",
)
EXAMPLES = ["webstorm typescript project called 'Shop'", "node app called Stock", "node test package.json"]

PACKAGE = {
    "name": "",
    "version": "1.0.0",
    "private": True,
    "type": "module",
    "scripts": {"start": "node src/main.ts", "test": 'node --test "test/**/*.test.ts"'},
    "engines": {"node": ">=22.18"},
}
TSCONFIG = {
    "compilerOptions": {
        "target": "es2024",
        "module": "nodenext",
        "moduleResolution": "nodenext",
        "allowImportingTsExtensions": True,
        "noEmit": True,
        "strict": True,
        "erasableSyntaxOnly": True,
        "verbatimModuleSyntax": True,
        "skipLibCheck": True,
    },
    "include": ["src", "test"],
}
INVENTORY = """/** A product line in stock. */
export interface Product {
  name: string;
  price: number;
  quantity: number;
}

/** What the shop holds: add stock, sell it, its value, what is running low. */
export class Inventory {
  #items = new Map<string, Product>();

  /** Puts stock in; the same name (in any case) adds to its quantity and takes the new price. */
  add(p: Product): void {
    if (!p.name.trim()) throw new Error("A product needs a name.");
    if (p.price < 0 || p.quantity < 0) throw new Error("Price and quantity cannot be negative.");
    const old = this.#items.get(p.name.toLowerCase());
    if (old) {
      old.price = p.price;
      old.quantity += p.quantity;
    } else {
      this.#items.set(p.name.toLowerCase(), { ...p });
    }
  }

  /** Takes quantity out; false if there is not that much. */
  sell(name: string, quantity: number): boolean {
    const p = this.#items.get(name.toLowerCase());
    if (!p || quantity <= 0 || p.quantity < quantity) return false;
    p.quantity -= quantity;
    return true;
  }

  get items(): Product[] {
    return [...this.#items.values()];
  }

  totalValue(): number {
    let sum = 0;
    for (const p of this.#items.values()) sum += p.price * p.quantity;
    return sum;
  }

  /** The products with fewer than `below` in stock, scarcest first. */
  lowStock(below: number): Product[] {
    return this.items.filter((p) => p.quantity < below).sort((a, b) => a.quantity - b.quantity);
  }
}

/** 22000 -> "22,000" */
export function withCommas(n: number): string {
  return n.toLocaleString("en-US");
}
"""
MAIN = """import { Inventory, withCommas } from "./inventory.ts";

const inv = new Inventory();
const stock: [string, number, number][] = [["Ceiling fan", 4500, 3], ["Steam iron", 3200, 2], ["Kettle", 2100, 5]];
for (const [name, price, quantity] of stock) inv.add({ name, price, quantity });
inv.sell("Kettle", 4);
for (const p of inv.items) console.log(`${p.name.padEnd(12)} ${String(p.quantity).padStart(3)} x Rs ${withCommas(p.price)}`);
console.log(`Total value: Rs ${withCommas(inv.totalValue())}`);
console.log(`Low stock: ${inv.lowStock(3).map((p) => p.name).join(", ")}`);
"""
TESTS = """import { test } from "node:test";
import assert from "node:assert/strict";
import { Inventory, withCommas } from "../src/inventory.ts";

test("adding the same product adds to its stock", () => {
  const inv = new Inventory();
  inv.add({ name: "Fan", price: 4500, quantity: 3 });
  inv.add({ name: "fan", price: 4600, quantity: 2 });
  assert.equal(inv.items.length, 1);
  assert.deepEqual([inv.items[0].quantity, inv.items[0].price], [5, 4600]);
});

test("negative quantities are refused", () => {
  assert.throws(() => new Inventory().add({ name: "Iron", price: 3200, quantity: -1 }));
});

test("selling more than in stock fails", () => {
  const inv = new Inventory();
  inv.add({ name: "Kettle", price: 2100, quantity: 2 });
  assert.equal(inv.sell("Kettle", 3), false);
  assert.equal(inv.sell("Kettle", 2), true);
  assert.equal(inv.items[0].quantity, 0);
});

test("total value is price times quantity", () => {
  const inv = new Inventory();
  inv.add({ name: "Fan", price: 4500, quantity: 3 });
  inv.add({ name: "Iron", price: 3200, quantity: 2 });
  assert.equal(inv.totalValue(), 19900);
  assert.equal(withCommas(inv.totalValue()), "19,900");
});

test("low stock lists the scarcest first", () => {
  const inv = new Inventory();
  for (const [name, quantity] of [["A", 5], ["B", 1], ["C", 9]] as [string, number][]) inv.add({ name, price: 1, quantity });
  assert.deepEqual(inv.lowStock(6).map((p) => p.name), ["B", "A"]);
});
"""


def node_exe():
    return shutil.which("node")


def node(*args, cwd, timeout=300):
    from ai_pc.core import hidden_desktop

    env = {k: v for k, v in os.environ.items() if k.upper() not in ("NODE_OPTIONS",)}
    env["NO_COLOR"] = "1"
    rc, out, err, timed_out = hidden_desktop.run([node_exe(), *map(str, args)], timeout=timeout, cwd=str(cwd), env=env)
    return rc == 0 and not timed_out, out + err


def results(text):
    """(passed, failed) from Node's test runner report."""
    p = re.search(r"^[#ℹ]\s*pass (\d+)", text, re.M)
    f = re.search(r"^[#ℹ]\s*fail (\d+)", text, re.M)
    return (int(p.group(1)) if p else 0), (int(f.group(1)) if f else 0)


def problems(text):
    out = []
    for m in re.finditer(r"file:///([^\s:]+\.(?:ts|js|mjs|cjs|mts|cts)):(\d+)", text):
        out.append(f"{Path(m.group(1)).name}:{m.group(2)}")
    for m in re.finditer(r"^not ok \d+ - (.+)$|^\s*✖ (.+?) \(\d[\d.]*m?s\)", text, re.M):  # TAP or Node's spec report
        out.append(f"failed: {(m.group(1) or m.group(2)).strip()}")
    for m in re.finditer(r"^(\w*Error): (.+)$", text, re.M):
        out.append(f"{m.group(1)}: {m.group(2).strip()}")
    return list(dict.fromkeys(out))


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(
        r"\bnode(?:\.?js)?\s+(?:project|app|program|test|run|cli|api)\b|\bnodejs\b|\btypescript\b|\bwebstorm\b|\bjavascript\s+(?:project|app|program)\b|\bpackage\.json\b",
        c,
    ):
        return None
    f = find_file(text, ctx, {".json"})
    if f and Path(f).name.lower() == "package.json":
        return {"op": "test", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9_-]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bprogram\b|\bcli\b|\bapi\b", c) else None


def run(op, ctx):
    if not node_exe():
        return "Node.js is not on this PC."
    if op["op"] == "test":
        folder = Path(op["file"]).resolve().parent
        pkg = json.loads(Path(op["file"]).read_text(encoding="utf-8"))
        tests = sorted(
            str(p.relative_to(folder))
            for pat in ("test/**/*.test.*", "tests/**/*.test.*", "src/**/*.test.*")
            for p in folder.glob(pat)
            if "node_modules" not in p.parts
        )
        ok, out = node("--test", *tests, cwd=folder) if tests else node("--test", cwd=folder)
        passed, failed = results(out)
        if not ok:
            return f"Tests of {pkg.get('name') or folder.name} FAILED ({failed} failed, {passed} passed): " + "; ".join(problems(out)[:8]) + "."
        return f"{pkg.get('name') or folder.name}: {passed} tests passed with Node's test runner."
    name = op["name"]
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-") or "app"
    out = (Path(ctx["out"]) / "nodejs" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    files = {
        "package.json": json.dumps(dict(PACKAGE, name=slug), indent=2) + "\n",
        "tsconfig.json": json.dumps(TSCONFIG, indent=2) + "\n",
        "src/inventory.ts": INVENTORY,
        "src/main.ts": MAIN,
        "test/inventory.test.ts": TESTS,
        ".gitignore": "node_modules/\n.idea/\n",
    }
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text, encoding="utf-8", newline="\n")
    ok_v, version = node("--version", cwd=out)
    ok_t, tests = node("--test", "test/inventory.test.ts", cwd=out)
    ok_r, ran = node("src/main.ts", cwd=out)
    passed, failed = results(tests)
    checks = [
        (f"Node.js {version.strip()} runs the TypeScript itself (no build step, nothing downloaded)", ok_v and ok_r),
        (f"node --test: {passed} of 5 tests passed", ok_t and passed == 5 and failed == 0),
        ("src/main.ts prints the stock's value (Rs 22,000)", "Total value: Rs 22,000" in ran),
    ]
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad = [w for w, good in checks if not good]
    return (
        f"TypeScript project {out} (package.json, tsconfig.json, src/, test/; open the folder in WebStorm or VS Code; npm test / npm start). "
        + (f"Output: {' | '.join(ln.strip() for ln in ran.strip().splitlines() if ln.startswith(('Total', 'Low')))}. " if ran else "")
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad
            else "NOT right: " + "; ".join(bad) + ". " + "; ".join(problems(tests + ran)[:5])
        )
    )
