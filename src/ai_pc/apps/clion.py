"""C++ projects for CLion, Visual Studio and VS Code (all open a CMake folder as is), built here for real: CMake 4.4.4
(tools/cmake; its SHA-256 list GPG-signed by Kitware, cmake.exe Kitware-signed) with Ninja 1.13.2 (tools/ninja) and the
LLVM-MinGW 20260922 toolchain (tools/llvm-mingw: clang++, lld, libc++ for Windows; GitHub SHA-256), on the hidden desktop.

A project from words (C++20: an inventory library, a program, tests run by CTest, CMakePresets.json) is configured,
built, tested and run; the program is linked statically, so the one .exe runs on any Windows PC (checked by reading its
imports: no compiler DLLs). A CMakeLists.txt given is built and tested the same way, every compile error with its file
and line.

  "clion c++ project called 'Shop'"   'c++ app called Stock'   'cmake build C:\\code\\game\\CMakeLists.txt'
"""

import os
import re
import shutil
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = (
    "clion",
    "C++ (CLion, Visual Studio, VS Code): CMake projects built with clang, tested by CTest, one standalone .exe; build any CMakeLists.txt",
)
EXAMPLES = ["clion c++ project called 'Shop'", "c++ app called Stock", "cmake build CMakeLists.txt"]
TOOLS = ROOT / "tools"
CLANG = TOOLS / "llvm-mingw" / "bin"
CMAKE = TOOLS / "cmake" / "bin" / "cmake.exe"
CTEST = TOOLS / "cmake" / "bin" / "ctest.exe"
NINJA = TOOLS / "ninja" / "ninja.exe"

CMAKELISTS = """cmake_minimum_required(VERSION 3.24)
project({name} VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(MINGW)
  add_link_options(-static)  # one .exe that runs on any Windows PC
endif()

add_library(inventory src/inventory.cpp)
target_include_directories(inventory PUBLIC include)
if(MSVC)
  target_compile_options(inventory PRIVATE /W4)
else()
  target_compile_options(inventory PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable({exe} src/main.cpp)
target_link_libraries({exe} PRIVATE inventory)

enable_testing()
add_executable(inventory_tests tests/inventory_tests.cpp)
target_link_libraries(inventory_tests PRIVATE inventory)
add_test(NAME inventory_tests COMMAND inventory_tests)
"""
PRESETS = """{{
  "version": 6,
  "configurePresets": [
    {{
      "name": "debug",
      "displayName": "Debug (Ninja)",
      "generator": "Ninja",
      "binaryDir": "${{sourceDir}}/build/${{presetName}}",
      "cacheVariables": {{ "CMAKE_BUILD_TYPE": "Debug" }}
    }},
    {{
      "name": "release",
      "inherits": "debug",
      "displayName": "Release (Ninja)",
      "cacheVariables": {{ "CMAKE_BUILD_TYPE": "Release" }}
    }}
  ],
  "buildPresets": [{{ "name": "debug", "configurePreset": "debug" }}, {{ "name": "release", "configurePreset": "release" }}],
  "testPresets": [{{ "name": "debug", "configurePreset": "debug", "output": {{ "outputOnFailure": true }} }}]
}}
"""
HEADER = """#pragma once
#include <cstdint>
#include <string>
#include <vector>

/// A product line in stock.
struct Product {
    std::string name;
    std::int64_t price = 0;
    int quantity = 0;
    std::int64_t value() const { return price * quantity; }
};

/// What the shop holds: add stock, sell it, its value, what is running low.
class Inventory {
public:
    void add(const Product& p);  // throws std::invalid_argument for a blank name or negative numbers
    bool sell(const std::string& name, int quantity);
    std::int64_t total_value() const;
    std::vector<Product> low_stock(int below) const;
    const std::vector<Product>& items() const { return items_; }

private:
    std::vector<Product> items_;  // in the order first added
    Product* find(const std::string& name);
};

/// 22000 -> "22,000"
std::string with_commas(std::int64_t n);
"""
SOURCE = """#include "inventory.hpp"

#include <algorithm>
#include <cctype>
#include <iterator>
#include <stdexcept>

namespace {
std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}
bool blank(const std::string& s) {
    return std::all_of(s.begin(), s.end(), [](unsigned char c) { return std::isspace(c) != 0; });
}
}  // namespace

Product* Inventory::find(const std::string& name) {
    const std::string key = lower(name);
    for (auto& p : items_)
        if (lower(p.name) == key) return &p;
    return nullptr;
}

void Inventory::add(const Product& p) {
    if (blank(p.name)) throw std::invalid_argument("A product needs a name.");
    if (p.price < 0 || p.quantity < 0) throw std::invalid_argument("Price and quantity cannot be negative.");
    if (Product* old = find(p.name)) {
        old->price = p.price;
        old->quantity += p.quantity;
    } else {
        items_.push_back(p);
    }
}

bool Inventory::sell(const std::string& name, int quantity) {
    Product* p = find(name);
    if (p == nullptr || quantity <= 0 || p->quantity < quantity) return false;
    p->quantity -= quantity;
    return true;
}

std::int64_t Inventory::total_value() const {
    std::int64_t sum = 0;
    for (const auto& p : items_) sum += p.value();
    return sum;
}

std::vector<Product> Inventory::low_stock(int below) const {
    std::vector<Product> out;
    std::copy_if(items_.begin(), items_.end(), std::back_inserter(out), [below](const Product& p) { return p.quantity < below; });
    std::stable_sort(out.begin(), out.end(), [](const Product& a, const Product& b) { return a.quantity < b.quantity; });
    return out;
}

std::string with_commas(std::int64_t n) {
    std::string digits = std::to_string(n < 0 ? -n : n), out;
    for (std::size_t i = 0; i < digits.size(); ++i) {
        if (i > 0 && (digits.size() - i) % 3 == 0) out += ',';
        out += digits[i];
    }
    return n < 0 ? "-" + out : out;
}
"""
MAIN = """#include <cstdio>

#include "inventory.hpp"

int main() {
    Inventory inv;
    inv.add({"Ceiling fan", 4500, 3});
    inv.add({"Steam iron", 3200, 2});
    inv.add({"Kettle", 2100, 5});
    inv.sell("Kettle", 4);
    for (const auto& p : inv.items())
        std::printf("%-12s %3d x Rs %s\\n", p.name.c_str(), p.quantity, with_commas(p.price).c_str());
    std::printf("Total value: Rs %s\\n", with_commas(inv.total_value()).c_str());
    std::string low;
    for (const auto& p : inv.low_stock(3)) low += (low.empty() ? "" : ", ") + p.name;
    std::printf("Low stock: %s\\n", low.c_str());
    return 0;
}
"""
TESTS = """// Plain C++ tests run by CTest: no test library to download.
#include <cstdio>
#include <functional>
#include <stdexcept>

#include "inventory.hpp"

static int run = 0, failed = 0;

#define CHECK(cond)                                                               \\
    do {                                                                          \\
        if (!(cond)) {                                                            \\
            std::printf("  check failed at %s:%d: %s\\n", __FILE__, __LINE__, #cond); \\
            ++failed;                                                             \\
            return;                                                               \\
        }                                                                         \\
    } while (0)

static void test(const char* name, const std::function<void()>& body) {
    ++run;
    const int before = failed;
    body();
    std::printf("%s %s\\n", failed == before ? "ok  " : "FAIL", name);
}

int main() {
    test("adding the same product adds to its stock", [] {
        Inventory inv;
        inv.add({"Fan", 4500, 3});
        inv.add({"fan", 4600, 2});
        CHECK(inv.items().size() == 1);
        CHECK(inv.items()[0].quantity == 5);
        CHECK(inv.items()[0].price == 4600);
    });
    test("negative quantities are refused", [] {
        Inventory inv;
        bool threw = false;
        try {
            inv.add({"Iron", 3200, -1});
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        CHECK(threw);
    });
    test("selling more than in stock fails", [] {
        Inventory inv;
        inv.add({"Kettle", 2100, 2});
        CHECK(!inv.sell("Kettle", 3));
        CHECK(inv.sell("Kettle", 2));
        CHECK(inv.items()[0].quantity == 0);
    });
    test("total value is price times quantity", [] {
        Inventory inv;
        inv.add({"Fan", 4500, 3});
        inv.add({"Iron", 3200, 2});
        CHECK(inv.total_value() == 19900);
        CHECK(with_commas(inv.total_value()) == "19,900");
    });
    test("low stock lists the scarcest first", [] {
        Inventory inv;
        inv.add({"A", 1, 5});
        inv.add({"B", 1, 1});
        inv.add({"C", 1, 9});
        auto low = inv.low_stock(6);
        CHECK(low.size() == 2);
        CHECK(low[0].name == "B" && low[1].name == "A");
    });
    std::printf("%d of %d tests passed\\n", run - failed, run);
    return failed == 0 ? 0 : 1;
}
"""


def ready():
    return CMAKE.exists() and NINJA.exists() and (CLANG / "clang++.exe").exists()


def env():
    return dict(
        os.environ,
        PATH=os.pathsep.join([str(CLANG), str(CMAKE.parent), str(NINJA.parent), os.environ["PATH"]]),
        CMAKE_GENERATOR="Ninja",
        CC=str(CLANG / "clang.exe"),
        CXX=str(CLANG / "clang++.exe"),
    )


def sh(*args, cwd, timeout=900):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run([str(a) for a in args], timeout=timeout, cwd=str(cwd), env=env())
    return rc == 0 and not timed_out, out + err


def compile_errors(text):
    out = []
    for m in re.finditer(r"^(?:[A-Za-z]:)?[^\s:]*?([^\\/\s:]+\.(?:cpp|cc|cxx|c|hpp|h|hh)):(\d+):(?:\d+:)?\s*(?:fatal )?error:\s*(.+)$", text, re.M):
        e = f"{m.group(1)}:{m.group(2)} {m.group(3).strip()}"
        if e not in out:
            out.append(e)
    for m in re.finditer(r"CMake Error at ([^\s:]+):(\d+)", text):
        e = f"{Path(m.group(1)).name}:{m.group(2)} CMake error"
        if e not in out:
            out.append(e)
    return out


def build(folder, build_dir):
    """Configure, build and test a CMake folder: (ok, log, errors, ctest summary)."""
    ok, log = sh(CMAKE, "-S", folder, "-B", build_dir, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Debug", f"-DCMAKE_MAKE_PROGRAM={NINJA}", cwd=folder)
    if ok:
        ok, more = sh(CMAKE, "--build", build_dir, cwd=folder)
        log += more
    tests = ""
    if ok:
        ok_t, tests = sh(CTEST, "--test-dir", build_dir, "-V", "--output-on-failure", cwd=folder)
        ok = ok and ok_t
    return ok, log + tests, compile_errors(log), tests


def imports(exe):
    """The DLLs an .exe needs, read by llvm-objdump."""
    from ai_pc.core import hidden_desktop

    rc, out, err, _ = hidden_desktop.run([str(CLANG / "llvm-objdump.exe"), "-p", str(exe)], timeout=60, env=env())
    return sorted({m.lower() for m in re.findall(r"DLL Name:\s*(\S+)", out)})


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if not re.search(r"c\+\+|\bcpp\b|\bcmake\b|\bclion\b|code::blocks|\bdev-c\+\+|\bcmakelists\b", c):
        return None
    f = find_file(text, ctx, {".txt"})
    if f and Path(f).name.lower() == "cmakelists.txt":
        return {"op": "build", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bprogram\b|\bapplication\b", c) else None


def run(op, ctx):
    if not ready():
        return "CMake, Ninja and LLVM-MinGW are not in tools/cmake, tools/ninja and tools/llvm-mingw."
    if op["op"] == "build":
        folder = Path(op["file"]).resolve().parent
        ok, log, errs, tests = build(folder, folder / "build" / "aipc")
        m = re.search(r"(\d+)% tests passed, (\d+) tests? failed out of (\d+)", tests)
        if not ok:
            return (
                f"CMake build of {folder.name} FAILED"
                + (
                    f" with {len(errs)} error(s): " + "; ".join(errs[:8])
                    if errs
                    else (f": {m.group(2)} of {m.group(3)} tests failed" if m and m.group(2) != "0" else ": " + log.strip()[-300:])
                )
                + "."
            )
        exes = [p.name for p in (folder / "build" / "aipc").glob("*.exe")]
        return f"{folder.name} builds with CMake + clang: " + (f"CTest {m.group(0)}; " if m else "no tests; ") + "programs: " + ", ".join(exes) + "."
    name = op["name"]
    exe = re.sub(r"[^a-z0-9_]", "", name.lower()) or "app"
    out = (Path(ctx["out"]) / "clion" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    files = {
        "CMakeLists.txt": CMAKELISTS.format(name=re.sub(r"[^A-Za-z0-9_]", "_", name), exe=exe),
        "CMakePresets.json": PRESETS,
        "include/inventory.hpp": HEADER,
        "src/inventory.cpp": SOURCE,
        "src/main.cpp": MAIN,
        "tests/inventory_tests.cpp": TESTS,
        ".gitignore": "build/\n.idea/\n.vs/\ncmake-build-*/\n",
        ".clang-format": "BasedOnStyle: Google\nColumnLimit: 120\n",
    }
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text, encoding="utf-8")
    bdir = out / "build" / "debug"
    ok, log, errs, tests = build(out, bdir)
    program = bdir / f"{exe}.exe"
    from ai_pc.core import hidden_desktop

    rc, ran, _, _ = hidden_desktop.run([str(program)], timeout=60) if program.exists() else (None, "", "", False)
    dlls = imports(program) if program.exists() else []
    foreign = [d for d in dlls if re.search(r"c\+\+|unwind|winpthread|gcc|stdc", d)]
    checks = [
        (
            "CMake configured it and clang++ built it (C++20, -Wall -Wextra -Wpedantic), no errors or warnings",
            ok and not errs and "warning:" not in log,
        ),
        ("CTest ran the tests: 5 of 5 passed", "5 of 5 tests passed" in tests and "100% tests passed" in tests),
        (f"{exe}.exe runs and prints the stock's value (Rs 22,000)", rc == 0 and "Total value: Rs 22,000" in ran),
        (
            f"the .exe stands alone: it needs only Windows' own DLLs ({', '.join(dlls[:3])}{'...' if len(dlls) > 3 else ''})",
            bool(dlls) and not foreign,
        ),
        ("compile_commands.json is there for IDEs and clangd", (bdir / "compile_commands.json").exists()),
    ]
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad = [w for w, good in checks if not good]
    return (
        (
            f"C++ project {out} (CMake: CMakeLists.txt + CMakePresets.json, include/, src/, tests/; open the folder in CLion, Visual Studio or VS Code). "
            f"Program: {program} ({program.stat().st_size / 1024:,.0f} KB)"
            if program.exists()
            else f"C++ project {out}"
        )
        + (f". Output: {' | '.join(ln.strip() for ln in ran.strip().splitlines()[-2:])}. " if ran else ". ")
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad
            else "NOT right: " + "; ".join(bad) + ". " + "; ".join(errs[:5]) + " " + (tests.strip()[-300:] if not errs else "")
        )
    )
