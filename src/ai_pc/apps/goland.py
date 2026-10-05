"""Go projects for GoLand and VS Code, built here for real with Go 1.27.1 (tools/go/go: Google's signed MSI, SHA-256 equal on
go.dev and golang.google.cn, unpacked only). Go's module cache, build cache, settings and telemetry are kept in
tools/go/home (APPDATA and LOCALAPPDATA pointed there for the go command, telemetry turned off), GOTOOLCHAIN=local so Go
never downloads another toolchain, and everything runs on the hidden desktop.

A project from words (a Go module: an inventory package with its tests, a command that prints the stock) is vetted,
tested, built to one .exe and run, and checked to be gofmt-clean; a go.mod given is built and tested the same way, every
compile error with its file and line.

  "goland go project called 'Shop'"   'go app called Stock'   'golang build C:\\code\\api\\go.mod'
"""

import os
import re
import shutil
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "goland", "Go (GoLand, VS Code): modules vetted, tested, built to one .exe and run; build any go.mod"
EXAMPLES = ["goland go project called 'Shop'", "go app called Stock", "golang build go.mod"]
GOROOT = ROOT / "tools" / "go" / "go"
GO = GOROOT / "bin" / "go.exe"

GO_MOD = """module example.com/{pkg}

go {version}
"""
INVENTORY = """// Package inventory holds what the shop has: add stock, sell it, its value, what is running low.
package inventory

import (
    "errors"
    "sort"
    "strconv"
    "strings"
)

// Product is a product line in stock.
type Product struct {
    Name     string
    Price    int64
    Quantity int
}

// Value is price times quantity.
func (p Product) Value() int64 { return p.Price * int64(p.Quantity) }

// Inventory keeps the products in the order first added.
type Inventory struct {
    items []Product
}

// ErrInvalid is returned for a blank name or a negative price or quantity.
var ErrInvalid = errors.New("a product needs a name, and price and quantity cannot be negative")

func (inv *Inventory) find(name string) int {
    for i, p := range inv.items {
        if strings.EqualFold(p.Name, name) {
            return i
        }
    }
    return -1
}

// Add puts stock in; the same name (in any case) adds to its quantity and takes the new price.
func (inv *Inventory) Add(p Product) error {
    if strings.TrimSpace(p.Name) == "" || p.Price < 0 || p.Quantity < 0 {
        return ErrInvalid
    }
    if i := inv.find(p.Name); i >= 0 {
        inv.items[i].Price = p.Price
        inv.items[i].Quantity += p.Quantity
        return nil
    }
    inv.items = append(inv.items, p)
    return nil
}

// Sell takes quantity out; false if there is not that much.
func (inv *Inventory) Sell(name string, quantity int) bool {
    i := inv.find(name)
    if i < 0 || quantity <= 0 || inv.items[i].Quantity < quantity {
        return false
    }
    inv.items[i].Quantity -= quantity
    return true
}

// Items lists the products.
func (inv *Inventory) Items() []Product { return append([]Product(nil), inv.items...) }

// TotalValue is the sum of every line's value.
func (inv *Inventory) TotalValue() int64 {
    var sum int64
    for _, p := range inv.items {
        sum += p.Value()
    }
    return sum
}

// LowStock lists the products with fewer than below in stock, scarcest first.
func (inv *Inventory) LowStock(below int) []Product {
    var out []Product
    for _, p := range inv.items {
        if p.Quantity < below {
            out = append(out, p)
        }
    }
    sort.SliceStable(out, func(a, b int) bool { return out[a].Quantity < out[b].Quantity })
    return out
}

// WithCommas writes 22000 as "22,000".
func WithCommas(n int64) string {
    s := strconv.FormatInt(n, 10)
    sign := ""
    if strings.HasPrefix(s, "-") {
        sign, s = "-", s[1:]
    }
    var b strings.Builder
    for i, r := range s {
        if i > 0 && (len(s)-i)%3 == 0 {
            b.WriteByte(',')
        }
        b.WriteRune(r)
    }
    return sign + b.String()
}
"""
TESTS = """package inventory

import (
    "errors"
    "reflect"
    "testing"
)

func TestAddingTheSameProductAddsToItsStock(t *testing.T) {
    var inv Inventory
    inv.Add(Product{"Fan", 4500, 3})
    inv.Add(Product{"fan", 4600, 2})
    items := inv.Items()
    if len(items) != 1 || items[0].Quantity != 5 || items[0].Price != 4600 {
        t.Fatalf("got %+v, want one Fan, 5 at 4600", items)
    }
}

func TestNegativeQuantitiesAreRefused(t *testing.T) {
    var inv Inventory
    if err := inv.Add(Product{"Iron", 3200, -1}); !errors.Is(err, ErrInvalid) {
        t.Fatalf("got %v, want ErrInvalid", err)
    }
}

func TestSellingMoreThanInStockFails(t *testing.T) {
    var inv Inventory
    inv.Add(Product{"Kettle", 2100, 2})
    if inv.Sell("Kettle", 3) {
        t.Fatal("sold 3 of 2")
    }
    if !inv.Sell("Kettle", 2) || inv.Items()[0].Quantity != 0 {
        t.Fatal("could not sell the 2 in stock")
    }
}

func TestTotalValueIsPriceTimesQuantity(t *testing.T) {
    var inv Inventory
    inv.Add(Product{"Fan", 4500, 3})
    inv.Add(Product{"Iron", 3200, 2})
    if got := inv.TotalValue(); got != 19900 || WithCommas(got) != "19,900" {
        t.Fatalf("got %d (%s), want 19900 (19,900)", got, WithCommas(got))
    }
}

func TestLowStockListsTheScarcestFirst(t *testing.T) {
    var inv Inventory
    inv.Add(Product{"A", 1, 5})
    inv.Add(Product{"B", 1, 1})
    inv.Add(Product{"C", 1, 9})
    var names []string
    for _, p := range inv.LowStock(6) {
        names = append(names, p.Name)
    }
    if !reflect.DeepEqual(names, []string{"B", "A"}) {
        t.Fatalf("got %v, want [B A]", names)
    }
}
"""
MAIN = """// Command {pkg} prints what the shop has in stock and what it is worth.
package main

import (
    "fmt"
    "log"
    "strings"

    "example.com/{pkg}/inventory"
)

func main() {{
    var inv inventory.Inventory
    for _, p := range []inventory.Product{{
        {{Name: "Ceiling fan", Price: 4500, Quantity: 3}},
        {{Name: "Steam iron", Price: 3200, Quantity: 2}},
        {{Name: "Kettle", Price: 2100, Quantity: 5}},
    }} {{
        if err := inv.Add(p); err != nil {{
            log.Fatal(err)
        }}
    }}
    inv.Sell("Kettle", 4)
    for _, p := range inv.Items() {{
        fmt.Printf("%-12s %3d x Rs %s\\n", p.Name, p.Quantity, inventory.WithCommas(p.Price))
    }}
    fmt.Printf("Total value: Rs %s\\n", inventory.WithCommas(inv.TotalValue()))
    var low []string
    for _, p := range inv.LowStock(3) {{
        low = append(low, p.Name)
    }}
    fmt.Println("Low stock: " + strings.Join(low, ", "))
}}
"""


def tabs(text):
    """The templates are written with 4 spaces; Go's own format indents with tabs."""
    return re.sub(r"(?m)^(?: {4})+", lambda m: "\t" * (len(m.group(0)) // 4), text)


def home():
    h = (ROOT / "tools" / "go" / "home").resolve()
    for d in ("gopath", "cache", "appdata", "localappdata", "tmp"):
        (h / d).mkdir(parents=True, exist_ok=True)
    return h


def env():
    h = home()
    e = {k: v for k, v in os.environ.items() if not k.upper().startswith("GO")}  # no GOROOT/GOPATH/GOFLAGS from elsewhere on the PC
    e.update(
        PATH=str(GOROOT / "bin") + os.pathsep + os.environ["PATH"],
        GOPATH=str(h / "gopath"),
        GOCACHE=str(h / "cache"),
        GOENV=str(h / "env"),
        GOTMPDIR=str(h / "tmp"),
        GOTOOLCHAIN="local",
        GOFLAGS="-modcacherw",
        CGO_ENABLED="0",
        APPDATA=str(h / "appdata"),
        LOCALAPPDATA=str(h / "localappdata"),
    )  # go's telemetry and config dirs follow these
    return e


def go(*args, cwd, timeout=600):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run([str(GO), *map(str, args)], timeout=timeout, cwd=str(cwd), env=env())
    return rc == 0 and not timed_out, out + err


def telemetry_off():
    mode = home() / "appdata" / "go" / "telemetry" / "mode"
    if not mode.exists() or "off" not in mode.read_text(encoding="utf-8", errors="replace"):
        go("telemetry", "off", cwd=home())


def compile_errors(text):
    out = []
    for m in re.finditer(r"^(?:\.[\\/])?([^\s:]*?\.go):(\d+):(?:\d+:)?\s*(.+)$", text, re.M):
        e = f"{Path(m.group(1)).name}:{m.group(2)} {m.group(3).strip()}"
        if e not in out:
            out.append(e)
    return out


def version():
    v = (GOROOT / "VERSION").read_text(encoding="utf-8").splitlines()[0]  # go1.27.1
    return ".".join(v[2:].split(".")[:2])


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(
        r"\bgolang\b|\bgoland\b|\bgo\.mod\b|\bgo\s+(?:project|app|program|module|cli|api|service|code)\b|\bin go\b(?!\s+(?:ahead|back|on|out|over|away|home|through))",
        c,
    ):
        return None
    f = find_file(text, ctx, {".mod"})
    if f and Path(f).name.lower() == "go.mod":
        return {"op": "build", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bprogram\b|\bmodule\b|\bcli\b", c) else None


def run(op, ctx):
    if not GO.exists():
        return "Go is not in tools/go."
    telemetry_off()
    if op["op"] == "build":
        folder = Path(op["file"]).resolve().parent
        ok_v, vet = go("vet", "./...", cwd=folder)
        ok_t, tests = go("test", "./...", cwd=folder)
        ok_b, built = go("build", "./...", cwd=folder)
        errs = compile_errors(vet + tests + built)
        if not (ok_v and ok_t and ok_b):
            failed = re.findall(r"^--- FAIL: (\S+)", tests, re.M)
            return (
                f"Go build of {folder.name} FAILED"
                + (
                    f" with {len(errs)} problem(s): " + "; ".join(errs[:8])
                    if errs
                    else (f": tests failed: {', '.join(failed[:6])}" if failed else ": " + (vet + tests + built).strip()[-300:])
                )
                + "."
            )
        return (
            f"{folder.name} builds with Go {version()}: go vet clean; "
            + "; ".join(ln.strip() for ln in tests.splitlines() if ln.startswith(("ok", "?")))
            + "."
        )
    name = op["name"]
    pkg = re.sub(r"[^a-z0-9]", "", name.lower()) or "app"
    out = (Path(ctx["out"]) / "goland" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    files = {
        "go.mod": GO_MOD.format(pkg=pkg, version=version()),
        "inventory/inventory.go": INVENTORY,
        "inventory/inventory_test.go": TESTS,
        f"cmd/{pkg}/main.go": MAIN.format(pkg=pkg),
        ".gitignore": f"/{pkg}.exe\n/.idea/\n",
    }
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(tabs(text), encoding="utf-8", newline="\n")  # gofmt wants LF line ends
    from ai_pc.core import hidden_desktop

    ok_v, vet = go("vet", "./...", cwd=out)
    ok_t, tests = go("test", "-v", "./...", cwd=out)
    exe = out / f"{pkg}.exe"
    ok_b, built = go("build", "-o", exe, f"./cmd/{pkg}", cwd=out)
    rc, ran, _, _ = hidden_desktop.run([str(exe)], timeout=60) if exe.exists() else (None, "", "", False)
    rc_f, unformatted, _, _ = hidden_desktop.run([str(GOROOT / "bin" / "gofmt.exe"), "-l", "."], timeout=60, cwd=str(out), env=env())
    passed = len(re.findall(r"^--- PASS:", tests, re.M))
    errs = compile_errors(vet + tests + built)
    checks = [
        ("go vet finds nothing", ok_v and not errs),
        (f"go test: {passed} of 5 tests passed", ok_t and passed == 5),
        (
            f"go build made {exe.name} ({exe.stat().st_size / 1024 / 1024:.1f} MB, one file, no C runtime needed) and it prints the stock's value (Rs 22,000)"
            if exe.exists()
            else "go build made the .exe",
            ok_b and rc == 0 and "Total value: Rs 22,000" in ran,
        ),
        ("gofmt finds every file formatted", rc_f == 0 and not unformatted.strip()),
    ]
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad = [w for w, good in checks if not good]
    return (
        f"Go module {out} (example.com/{pkg}: inventory package + tests, cmd/{pkg}; open the folder in GoLand or VS Code). "
        + (f"Output: {' | '.join(ln.strip() for ln in ran.strip().splitlines()[-2:])}. " if ran else "")
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad
            else "NOT right: "
            + "; ".join(bad)
            + ". "
            + "; ".join(errs[:5])
            + (" Not formatted: " + unformatted.strip()[:200] if unformatted.strip() else "")
        )
    )
