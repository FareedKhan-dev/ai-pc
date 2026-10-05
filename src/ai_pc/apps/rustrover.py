"""Rust projects for RustRover and VS Code (rust-analyzer), built here for real with Rust 1.99.0 (tools/rust/toolchain: the
standalone x86_64-pc-windows-gnu MSI, SHA-256 and the Rust release key's GPG signature checked, unpacked only; it brings
its own MinGW linker, so no Visual Studio is needed; cargo, clippy, rustfmt and rust-analyzer included). Cargo's home
(crate registry and caches) is tools/rust/home, never ~/.cargo; everything runs on the hidden desktop.

A project from words (a Cargo package: an inventory library with unit tests, a program) is formatted by rustfmt, linted
by clippy (warnings count as errors), tested, built in release mode and run; the .exe is checked to need only Windows'
own DLLs. A Cargo.toml given is built and tested the same way, every compile error with its file and line.

  "rustrover rust project called 'Shop'"   'rust app called Stock'   'cargo build C:\\code\\tool\\Cargo.toml'
"""

import os
import re
import shutil
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "rustrover", "Rust (RustRover, VS Code): Cargo packages formatted, clippy-linted, tested, built and run; build any Cargo.toml"
EXAMPLES = ["rustrover rust project called 'Shop'", "rust app called Stock", "cargo build Cargo.toml"]
TOOLCHAIN = ROOT / "tools" / "rust" / "toolchain"
CARGO = TOOLCHAIN / "bin" / "cargo.exe"
RESERVED = {
    "test",
    "std",
    "core",
    "alloc",
    "proc_macro",
    "self",
    "super",
    "crate",
    "type",
    "fn",
    "mod",
    "use",
    "impl",
    "trait",
    "struct",
    "enum",
    "match",
}

CARGO_TOML = """[package]
name = "__CRATE__"
version = "0.1.0"
edition = "2024"
rust-version = "1.87"

[dependencies]
"""
LIB = """//! What the shop holds: add stock, sell it, its value, what is running low.

use std::fmt;

/// A product line in stock.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Product {
    pub name: String,
    pub price: i64,
    pub quantity: i32,
}

impl Product {
    pub fn new(name: &str, price: i64, quantity: i32) -> Self {
        Product { name: name.to_string(), price, quantity }
    }

    /// Price times quantity.
    pub fn value(&self) -> i64 {
        self.price * i64::from(self.quantity)
    }
}

/// A product with no name, or a negative price or quantity.
#[derive(Debug, PartialEq, Eq)]
pub struct Invalid;

impl fmt::Display for Invalid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "a product needs a name, and price and quantity cannot be negative")
    }
}

impl std::error::Error for Invalid {}

/// The products, in the order first added.
#[derive(Debug, Default)]
pub struct Inventory {
    items: Vec<Product>,
}

impl Inventory {
    pub fn new() -> Self {
        Self::default()
    }

    fn position(&self, name: &str) -> Option<usize> {
        let key = name.to_lowercase();
        self.items.iter().position(|p| p.name.to_lowercase() == key)
    }

    /// Puts stock in; the same name (in any case) adds to its quantity and takes the new price.
    pub fn add(&mut self, p: Product) -> Result<(), Invalid> {
        if p.name.trim().is_empty() || p.price < 0 || p.quantity < 0 {
            return Err(Invalid);
        }
        if let Some(i) = self.position(&p.name) {
            let old = &mut self.items[i];
            old.price = p.price;
            old.quantity += p.quantity;
        } else {
            self.items.push(p);
        }
        Ok(())
    }

    /// Takes quantity out; false if there is not that much.
    pub fn sell(&mut self, name: &str, quantity: i32) -> bool {
        match self.position(name) {
            Some(i) if quantity > 0 && self.items[i].quantity >= quantity => {
                self.items[i].quantity -= quantity;
                true
            }
            _ => false,
        }
    }

    pub fn items(&self) -> &[Product] {
        &self.items
    }

    /// The sum of every line's value.
    pub fn total_value(&self) -> i64 {
        self.items.iter().map(Product::value).sum()
    }

    /// The products with fewer than `below` in stock, scarcest first.
    pub fn low_stock(&self, below: i32) -> Vec<&Product> {
        let mut out: Vec<&Product> = self.items.iter().filter(|p| p.quantity < below).collect();
        out.sort_by_key(|p| p.quantity);
        out
    }
}

/// Writes 22000 as "22,000".
pub fn with_commas(n: i64) -> String {
    let digits = n.unsigned_abs().to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    if n < 0 { format!("-{out}") } else { out }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adding_the_same_product_adds_to_its_stock() {
        let mut inv = Inventory::new();
        inv.add(Product::new("Fan", 4500, 3)).unwrap();
        inv.add(Product::new("fan", 4600, 2)).unwrap();
        assert_eq!(inv.items().len(), 1);
        assert_eq!(inv.items()[0].quantity, 5);
        assert_eq!(inv.items()[0].price, 4600);
    }

    #[test]
    fn negative_quantities_are_refused() {
        assert_eq!(Inventory::new().add(Product::new("Iron", 3200, -1)), Err(Invalid));
    }

    #[test]
    fn selling_more_than_in_stock_fails() {
        let mut inv = Inventory::new();
        inv.add(Product::new("Kettle", 2100, 2)).unwrap();
        assert!(!inv.sell("Kettle", 3));
        assert!(inv.sell("Kettle", 2));
        assert_eq!(inv.items()[0].quantity, 0);
    }

    #[test]
    fn total_value_is_price_times_quantity() {
        let mut inv = Inventory::new();
        inv.add(Product::new("Fan", 4500, 3)).unwrap();
        inv.add(Product::new("Iron", 3200, 2)).unwrap();
        assert_eq!(inv.total_value(), 19_900);
        assert_eq!(with_commas(inv.total_value()), "19,900");
    }

    #[test]
    fn low_stock_lists_the_scarcest_first() {
        let mut inv = Inventory::new();
        for (name, quantity) in [("A", 5), ("B", 1), ("C", 9)] {
            inv.add(Product::new(name, 1, quantity)).unwrap();
        }
        let names: Vec<&str> = inv.low_stock(6).iter().map(|p| p.name.as_str()).collect();
        assert_eq!(names, ["B", "A"]);
    }
}
"""
MAIN = """use __CRATE__::{Inventory, Product, with_commas};

fn main() {
    let mut inv = Inventory::new();
    for (name, price, quantity) in [("Ceiling fan", 4500, 3), ("Steam iron", 3200, 2), ("Kettle", 2100, 5)] {
        inv.add(Product::new(name, price, quantity)).expect("a valid product");
    }
    inv.sell("Kettle", 4);
    for p in inv.items() {
        println!("{:<12} {:>3} x Rs {}", p.name, p.quantity, with_commas(p.price));
    }
    println!("Total value: Rs {}", with_commas(inv.total_value()));
    let low: Vec<&str> = inv.low_stock(3).iter().map(|p| p.name.as_str()).collect();
    println!("Low stock: {}", low.join(", "));
}
"""


def home():
    h = (ROOT / "tools" / "rust" / "home").resolve()
    h.mkdir(parents=True, exist_ok=True)
    return h


def env():
    e = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CARGO", "RUSTUP", "RUSTC", "RUSTFLAGS", "RUSTDOC"))}
    e.update(PATH=str(TOOLCHAIN / "bin") + os.pathsep + os.environ["PATH"], CARGO_HOME=str(home()), CARGO_TERM_COLOR="never")
    return e


def cargo(*args, cwd, timeout=900):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run([str(CARGO), *map(str, args)], timeout=timeout, cwd=str(cwd), env=env())
    return rc == 0 and not timed_out, out + err


def compile_errors(text):
    out = []
    for m in re.finditer(r"^error(?:\[E\d+\])?: (.+?)\s*\n\s*--> ([^\s:]+):(\d+):\d+", text, re.M):
        e = f"{Path(m.group(2)).name}:{m.group(3)} {m.group(1).strip()}"
        if e not in out:
            out.append(e)
    return out


def imports(exe):
    """The DLLs an .exe needs, read by llvm-objdump (from tools/llvm-mingw), or None without it."""
    objdump = ROOT / "tools" / "llvm-mingw" / "bin" / "llvm-objdump.exe"
    if not objdump.exists():
        return None
    from ai_pc.core import hidden_desktop

    rc, out, err, _ = hidden_desktop.run([str(objdump), "-p", str(exe)], timeout=60)
    return sorted({m.lower() for m in re.findall(r"DLL Name:\s*(\S+)", out)})


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"\brust\b|\brustrover\b|\bcargo\.toml\b|\bcargo\s+(?:build|test|run|project|new)\b", c):
        return None
    f = find_file(text, ctx, {".toml"})
    if f and Path(f).name.lower() == "cargo.toml":
        return {"op": "build", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9_]*)['\"]?", text)
    return (
        {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bprogram\b|\bcrate\b|\bpackage\b|\bcli\b", c) else None
    )


def run(op, ctx):
    if not CARGO.exists():
        return "Rust is not in tools/rust/toolchain."
    if op["op"] == "build":
        folder = Path(op["file"]).resolve().parent
        ok_t, tests = cargo("test", cwd=folder)
        errs = compile_errors(tests)
        if not ok_t:
            failed = re.findall(r"^test (\S+) \.\.\. FAILED", tests, re.M)
            return (
                f"Cargo build of {folder.name} FAILED"
                + (
                    f" with {len(errs)} error(s): " + "; ".join(errs[:8])
                    if errs
                    else (f": tests failed: {', '.join(failed[:6])}" if failed else ": " + tests.strip()[-300:])
                )
                + "."
            )
        results = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed", tests)
        return f"{folder.name} builds with Cargo (Rust 1.99): {sum(int(p) for p, _ in results)} tests passed, none failed."
    name = op["name"]
    crate = re.sub(r"[^a-z0-9_]", "", name.lower()) or "app"
    if crate in RESERVED or crate[0].isdigit():
        crate = "app_" + crate
    out = (Path(ctx["out"]) / "rustrover" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    files = {"Cargo.toml": CARGO_TOML, "src/lib.rs": LIB, "src/main.rs": MAIN, ".gitignore": "/target\n/.idea/\n"}
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text.replace("__CRATE__", crate), encoding="utf-8", newline="\n")
    ok_f, fmt = cargo("fmt", cwd=out)
    ok_c, clippy = cargo("clippy", "--all-targets", "--", "-D", "warnings", cwd=out)
    ok_t, tests = cargo("test", cwd=out)
    ok_b, built = cargo("build", "--release", cwd=out)
    exe = out / "target" / "release" / f"{crate}.exe"
    from ai_pc.core import hidden_desktop

    rc, ran, _, _ = hidden_desktop.run([str(exe)], timeout=60) if exe.exists() else (None, "", "", False)
    dlls = imports(exe) if exe.exists() else None
    foreign = [d for d in (dlls or []) if re.search(r"gcc|stdc|winpthread|rust|std-", d)]
    passed = sum(int(p) for p in re.findall(r"test result: ok\. (\d+) passed", tests))
    errs = compile_errors(clippy + tests + built)
    checks = [
        ("rustfmt formatted it", ok_f),
        ("clippy finds nothing (warnings count as errors)", ok_c),
        (f"cargo test: {passed} of 5 unit tests passed", ok_t and passed == 5),
        (f"cargo build --release made {exe.name} and it prints the stock's value (Rs 22,000)", ok_b and rc == 0 and "Total value: Rs 22,000" in ran),
    ]
    if dlls is not None:
        checks.append((f"the .exe needs only Windows' own DLLs ({', '.join(dlls[:3])}{'...' if len(dlls) > 3 else ''})", bool(dlls) and not foreign))
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad = [w for w, good in checks if not good]
    size = f" ({exe.stat().st_size / 1024:,.0f} KB)" if exe.exists() else ""
    return (
        f"Rust package {out} (Cargo: src/lib.rs with unit tests, src/main.rs; open the folder in RustRover or VS Code, toolchain "
        f"{TOOLCHAIN / 'bin'}). Program: {exe}{size}. "
        + (f"Output: {' | '.join(ln.strip() for ln in ran.strip().splitlines()[-2:])}. " if ran else "")
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad
            else "NOT right: " + "; ".join(bad) + ". " + "; ".join(errs[:5]) + ("" if errs else " " + (clippy + tests).strip()[-300:])
        )
    )
