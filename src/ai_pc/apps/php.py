"""PHP projects (what XAMPP, Laravel and WordPress run on) for VS Code and PhpStorm, with PHP 8.4 in tools/php (windows.php.net's
zip; SHA-256 equal on windows.php.net and in Scoop's manifest). A website from words: src/ classes, public/index.php,
plain PHP tests (no Composer or PHPUnit download), composer.json for later. Checked here: every file linted by php -l,
the tests run, and the page served by PHP's own web server on 127.0.0.1 only and read back over HTTP. A PHP project
given is linted and tested the same way, each problem with its file and line. php.ini is never read (-n).

  "php website called 'Shop'"   'xampp php project called Stock'   'php test C:\\code\\site\\composer.json'
"""

import os
import re
import shutil
import socket
import time
import urllib.request
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "php", "PHP (XAMPP, Laravel, VS Code): websites linted, tested and served on this PC only; test any PHP project"
EXAMPLES = ["php website called 'Shop'", "xampp php project called Stock", "php test composer.json"]
HOME = ROOT / "tools" / "php"
PHP = HOME / "php.exe"

COMPOSER = """{{
    "name": "local/{slug}",
    "description": "What the shop holds: stock, sales, value",
    "type": "project",
    "require": {{ "php": ">=8.2" }},
    "autoload": {{ "psr-4": {{ "Shop\\\\": "src/" }} }}
}}
"""
PRODUCT = """<?php
declare(strict_types=1);

namespace Shop;

/** A product line in stock. */
final class Product
{
    public function __construct(public string $name, public int $price, public int $quantity)
    {
    }

    public function value(): int
    {
        return $this->price * $this->quantity;
    }
}
"""
INVENTORY = """<?php
declare(strict_types=1);

namespace Shop;

/** What the shop holds: add stock, sell it, its value, what is running low. */
final class Inventory
{
    /** @var array<string, Product> */
    private array $items = [];

    /** Puts stock in; the same name (in any case) adds to its quantity and takes the new price. */
    public function add(Product $p): void
    {
        if (trim($p->name) === '') {
            throw new \\InvalidArgumentException('A product needs a name.');
        }
        if ($p->price < 0 || $p->quantity < 0) {
            throw new \\InvalidArgumentException('Price and quantity cannot be negative.');
        }
        $key = strtolower($p->name);
        if (isset($this->items[$key])) {
            $this->items[$key]->price = $p->price;
            $this->items[$key]->quantity += $p->quantity;
        } else {
            $this->items[$key] = new Product($p->name, $p->price, $p->quantity);
        }
    }

    /** Takes quantity out; false if there is not that much. */
    public function sell(string $name, int $quantity): bool
    {
        $p = $this->items[strtolower($name)] ?? null;
        if ($p === null || $quantity <= 0 || $p->quantity < $quantity) {
            return false;
        }
        $p->quantity -= $quantity;
        return true;
    }

    /** @return list<Product> */
    public function items(): array
    {
        return array_values($this->items);
    }

    public function totalValue(): int
    {
        return array_sum(array_map(fn (Product $p) => $p->value(), $this->items));
    }

    /** @return list<Product> the products with fewer than $below in stock, scarcest first */
    public function lowStock(int $below): array
    {
        $low = array_values(array_filter($this->items, fn (Product $p) => $p->quantity < $below));
        usort($low, fn (Product $a, Product $b) => $a->quantity <=> $b->quantity);
        return $low;
    }
}
"""
BOOTSTRAP = """<?php
declare(strict_types=1);

// Without Composer: load the classes (with Composer, vendor/autoload.php does this from composer.json).
require_once __DIR__ . '/Product.php';
require_once __DIR__ . '/Inventory.php';
"""
INDEX = """<?php
declare(strict_types=1);

require __DIR__ . '/../src/bootstrap.php';

use Shop\\Inventory;
use Shop\\Product;

$inv = new Inventory();
foreach ([['Ceiling fan', 4500, 3], ['Steam iron', 3200, 2], ['Kettle', 2100, 5]] as [$name, $price, $quantity]) {
    $inv->add(new Product($name, $price, $quantity));
}
$inv->sell('Kettle', 4);
$h = fn (string $s): string => htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__NAME__ stock</title>
<style>body { font-family: sans-serif; margin: 2rem; } td, th { padding: .3rem .8rem; text-align: left; }</style>
</head>
<body>
<h1>In stock</h1>
<table>
<tr><th>Product</th><th>Quantity</th><th>Price</th></tr>
<?php foreach ($inv->items() as $p): ?>
<tr><td><?= $h($p->name) ?></td><td><?= $p->quantity ?></td><td>Rs <?= number_format($p->price) ?></td></tr>
<?php endforeach; ?>
</table>
<p><strong>Total value: Rs <?= number_format($inv->totalValue()) ?></strong></p>
<p>Low stock: <?= $h(implode(', ', array_map(fn ($p) => $p->name, $inv->lowStock(3)))) ?></p>
</body>
</html>
"""
TESTS = """<?php
declare(strict_types=1);

// Plain PHP tests (no PHPUnit to download): php tests/run.php
require __DIR__ . '/../src/bootstrap.php';

use Shop\\Inventory;
use Shop\\Product;

$run = 0;
$failed = 0;

function check(string $name, callable $body): void
{
    global $run, $failed;
    $run++;
    try {
        $body();
        echo "ok   $name\\n";
    } catch (Throwable $e) {
        $failed++;
        echo "FAIL $name: {$e->getMessage()}\\n";
    }
}

function same(mixed $want, mixed $got): void
{
    if ($want !== $got) {
        $at = debug_backtrace(DEBUG_BACKTRACE_IGNORE_ARGS, 1)[0];
        throw new RuntimeException(sprintf('%s:%d expected %s, got %s', basename($at['file']), $at['line'], var_export($want, true), var_export($got, true)));
    }
}

check('adding the same product adds to its stock', function () {
    $inv = new Inventory();
    $inv->add(new Product('Fan', 4500, 3));
    $inv->add(new Product('fan', 4600, 2));
    same(1, count($inv->items()));
    same([5, 4600], [$inv->items()[0]->quantity, $inv->items()[0]->price]);
});
check('negative quantities are refused', function () {
    try {
        (new Inventory())->add(new Product('Iron', 3200, -1));
    } catch (InvalidArgumentException) {
        return;
    }
    throw new RuntimeException('no error for a negative quantity');
});
check('selling more than in stock fails', function () {
    $inv = new Inventory();
    $inv->add(new Product('Kettle', 2100, 2));
    same(false, $inv->sell('Kettle', 3));
    same(true, $inv->sell('Kettle', 2));
    same(0, $inv->items()[0]->quantity);
});
check('total value is price times quantity', function () {
    $inv = new Inventory();
    $inv->add(new Product('Fan', 4500, 3));
    $inv->add(new Product('Iron', 3200, 2));
    same(19900, $inv->totalValue());
});
check('low stock lists the scarcest first', function () {
    $inv = new Inventory();
    foreach ([['A', 5], ['B', 1], ['C', 9]] as [$name, $quantity]) {
        $inv->add(new Product($name, 1, $quantity));
    }
    same(['B', 'A'], array_map(fn (Product $p) => $p->name, $inv->lowStock(6)));
});

echo ($run - $failed) . " of $run tests passed\\n";
exit($failed === 0 ? 0 : 1);
"""


def env():
    return {k: v for k, v in os.environ.items() if k.upper() not in ("PHPRC", "PHP_INI_SCAN_DIR")}


def version():
    m = re.search(r"php-(\d+\.\d+\.\d+)", (HOME / "SOURCE.txt").read_text(encoding="utf-8")) if (HOME / "SOURCE.txt").exists() else None
    return m.group(1) if m else "8.4"


def php_files(folder):
    return [str(p.relative_to(folder)) for p in sorted(Path(folder).rglob("*.php")) if "vendor" not in p.parts]


def php(*args, cwd, timeout=300):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run([str(PHP), "-n", *map(str, args)], timeout=timeout, cwd=str(cwd), env=env())
    return rc == 0 and not timed_out, out + err


def lint(folder):
    """['file.php:12 syntax error, unexpected ...'] for every file PHP cannot parse."""
    bad = []
    for f in php_files(folder):
        ok, out = php("-l", f, cwd=folder)
        if not ok:
            m = re.search(r"(?:Parse|Fatal) error:\s*(.+?) in (.+?) on line (\d+)", out)
            bad.append(f"{Path(m.group(2)).name}:{m.group(3)} {m.group(1)}" if m else f"{f}: {out.strip()[-120:]}")
    return bad


def serve(folder, docroot="public"):
    """Start PHP's web server for the folder on 127.0.0.1 (a free port): (process, url) once it answers."""
    from ai_pc.core import hidden_desktop

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = hidden_desktop.start([str(PHP), "-n", "-S", f"127.0.0.1:{port}", "-t", docroot], cwd=str(folder), env=env())
    url = f"http://127.0.0.1:{port}/"
    end = time.monotonic() + 15
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                return proc, url, r.status, r.read().decode("utf-8", "replace")
        except OSError:
            time.sleep(0.3)
    return proc, url, None, ""


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\bphp\b|\bxampp\b|\blaravel\b|\bphpstorm\b|\bcomposer\.json\b", c):
        return None
    f = find_file(text, ctx, {".json", ".php"})
    if f and re.search(r"\btest\b|\bcheck\b|\blint\b|\bbuild\b", c):
        return {"op": "test", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9_-]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bwebsite\b|\bsite\b|\bpage\b", c) else None


def run(op, ctx):
    if not PHP.exists():
        return "PHP is not in tools/php."
    if op["op"] == "test":
        folder = Path(op["file"]).resolve().parent
        bad = lint(folder)
        tests = folder / "tests" / "run.php"
        unit = folder / "vendor" / "phpunit" / "phpunit" / "phpunit"
        ok_t, out = (
            php(str(tests.relative_to(folder)), cwd=folder)
            if tests.exists()
            else php(str(unit.relative_to(folder)), cwd=folder)
            if unit.exists()
            else (True, "")
        )
        fails = [ln.strip() for ln in out.splitlines() if ln.startswith("FAIL")]
        if bad or not ok_t:
            return f"PHP project {folder.name} FAILED: " + "; ".join((bad + fails)[:8] or [out.strip()[-300:]]) + "."
        summary = next((ln for ln in out.splitlines() if re.search(r"tests passed|OK \(", ln)), "no tests found")
        return f"PHP project {folder.name}: {len(php_files(folder))} files lint clean; {summary.strip()}."
    name = op["name"]
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-") or "site"
    out = (Path(ctx["out"]) / "php" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    files = {
        "composer.json": COMPOSER.format(slug=slug),
        "src/Product.php": PRODUCT,
        "src/Inventory.php": INVENTORY,
        "src/bootstrap.php": BOOTSTRAP,
        "public/index.php": INDEX.replace("__NAME__", name),
        "tests/run.php": TESTS,
        ".gitignore": "vendor/\n.idea/\n",
    }
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text, encoding="utf-8", newline="\n")
    bad = lint(out)
    ok_t, tests = php("tests/run.php", cwd=out)
    proc, url, status, page = serve(out)
    proc.stop()
    checks = [
        (f"php -l finds no syntax errors in its {len(php_files(out))} files", not bad),
        ("its tests: 5 of 5 passed", ok_t and "5 of 5 tests passed" in tests),
        (
            f"PHP's web server (127.0.0.1 only) serves the page (HTTP {status}) with the stock's value (Rs 22,000)",
            status == 200 and "Total value: Rs 22,000" in page and "Ceiling fan" in page,
        ),
    ]
    bad_checks = [w for w, good in checks if not good]
    ctx.setdefault("memo", {})["project"] = str(out)
    return (
        f"PHP {version()} website {out} (src/ classes, public/index.php, tests/run.php, composer.json; open the folder in VS Code or PhpStorm; "
        f"run it with php -S 127.0.0.1:8000 -t public, or put it in XAMPP's htdocs). "
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad_checks
            else "NOT right: " + "; ".join(bad_checks) + ". " + "; ".join(bad[:5]) + " " + tests.strip()[-300:]
        )
    )
