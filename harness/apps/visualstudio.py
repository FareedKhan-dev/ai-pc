"""Visual Studio's engine, the .NET 10 SDK (tools/dotnet; SHA-512 from Microsoft's release metadata, dotnet.exe signed by
Microsoft): C# solutions made by the SDK's own templates and really built and tested here: a core library (an inventory:
products, stock, value, low stock) with xUnit tests, plus a console app (run, its output read), an ASP.NET Core web API
(started on 127.0.0.1 and called over HTTP), or a WinForms desktop app (opened on the hidden desktop, its window found);
a single-file .exe published on request; or a solution given, built and tested with every error's file and line.
The .slnx opens in Visual Studio 2022/2026, Rider and VS Code. SDK homes, NuGet packages and caches stay in tools/dotnet/home;
the NuGet.Config and marker folder NuGet always writes to AppData are removed after a run that made them.

  "visual studio web api called 'Shop' with tests"   'c# console app called Stock, publish an exe'   'dotnet winforms app called Till'
  'visual studio build and test C:\\code\\MyApp\\MyApp.sln'
"""
import json
import os
import re
import shutil
import socket
import time
import urllib.request
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "visualstudio", "Visual Studio / .NET: C# console, web API, WinForms solutions with xUnit tests, built + tested; build any .sln"
EXAMPLES = ["visual studio web api called 'Shop' with tests", "c# console app called Stock, publish an exe", "dotnet winforms app called Till"]
HOME = ROOT / "tools" / "dotnet"
DOTNET = HOME / "dotnet.exe"

CORE = """namespace {ns}.Core;

/// <summary>A product line in stock.</summary>
public record Product(string Name, decimal Price, int Quantity)
{{
    public decimal Value => Price * Quantity;
}}

/// <summary>What the shop holds: add stock, sell it, its value, what is running low.</summary>
public class Inventory
{{
    private readonly Dictionary<string, Product> _items = new(StringComparer.OrdinalIgnoreCase);

    public IReadOnlyCollection<Product> Items => _items.Values;

    public void Add(Product product)
    {{
        if (string.IsNullOrWhiteSpace(product.Name)) throw new ArgumentException("A product needs a name.");
        if (product.Price < 0 || product.Quantity < 0) throw new ArgumentException("Price and quantity cannot be negative.");
        _items[product.Name] = _items.TryGetValue(product.Name, out var old)
            ? old with {{ Quantity = old.Quantity + product.Quantity, Price = product.Price }}
            : product;
    }}

    public bool Sell(string name, int quantity)
    {{
        if (!_items.TryGetValue(name, out var p) || quantity <= 0 || p.Quantity < quantity) return false;
        _items[name] = p with {{ Quantity = p.Quantity - quantity }};
        return true;
    }}

    public decimal TotalValue => _items.Values.Sum(p => p.Value);

    public IEnumerable<Product> LowStock(int below) => _items.Values.Where(p => p.Quantity < below).OrderBy(p => p.Quantity);
}}
"""
TESTS = """using {ns}.Core;

namespace {ns}.Tests;

public class InventoryTests
{{
    [Fact]
    public void Adding_the_same_product_adds_to_its_stock()
    {{
        var inv = new Inventory();
        inv.Add(new Product("Fan", 4500m, 3));
        inv.Add(new Product("fan", 4600m, 2));
        var fan = Assert.Single(inv.Items);
        Assert.Equal(5, fan.Quantity);
        Assert.Equal(4600m, fan.Price);
    }}

    [Fact]
    public void Negative_quantities_are_refused() =>
        Assert.Throws<ArgumentException>(() => new Inventory().Add(new Product("Iron", 3200m, -1)));

    [Fact]
    public void Selling_more_than_in_stock_fails_and_changes_nothing()
    {{
        var inv = new Inventory();
        inv.Add(new Product("Kettle", 2100m, 2));
        Assert.False(inv.Sell("Kettle", 3));
        Assert.True(inv.Sell("Kettle", 2));
        Assert.Equal(0, inv.Items.Single().Quantity);
    }}

    [Fact]
    public void Total_value_is_price_times_quantity()
    {{
        var inv = new Inventory();
        inv.Add(new Product("Fan", 4500m, 3));
        inv.Add(new Product("Iron", 3200m, 2));
        Assert.Equal(19900m, inv.TotalValue);
    }}

    [Fact]
    public void Low_stock_lists_the_scarcest_first()
    {{
        var inv = new Inventory();
        inv.Add(new Product("A", 1m, 5));
        inv.Add(new Product("B", 1m, 1));
        inv.Add(new Product("C", 1m, 9));
        Assert.Equal(new[] {{ "B", "A" }}, inv.LowStock(6).Select(p => p.Name));
    }}
}}
"""
CONSOLE = """using System.Globalization;
using {ns}.Core;

var inv = new Inventory();
inv.Add(new Product("Ceiling fan", 4500m, 3));
inv.Add(new Product("Steam iron", 3200m, 2));
inv.Add(new Product("Kettle", 2100m, 5));
inv.Sell("Kettle", 4);
var pk = CultureInfo.GetCultureInfo("en-PK");
foreach (var p in inv.Items)
    Console.WriteLine($"{{p.Name,-12}} {{p.Quantity,3}} x Rs {{p.Price.ToString("N0", pk)}}");
Console.WriteLine($"Total value: Rs {{inv.TotalValue.ToString("N0", pk)}}");
Console.WriteLine($"Low stock: {{string.Join(", ", inv.LowStock(3).Select(p => p.Name))}}");
"""
API = """using {ns}.Core;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton<Inventory>();
var app = builder.Build();

app.MapGet("/products", (Inventory inv) => inv.Items);
app.MapPost("/products", (Product p, Inventory inv) =>
{{
    try {{ inv.Add(p); return Results.Created($"/products/{{p.Name}}", p); }}
    catch (ArgumentException e) {{ return Results.BadRequest(new {{ error = e.Message }}); }}
}});
app.MapPost("/products/{{name}}/sell/{{quantity:int}}", (string name, int quantity, Inventory inv) =>
    inv.Sell(name, quantity) ? Results.Ok() : Results.Conflict(new {{ error = "not enough stock" }}));
app.MapGet("/value", (Inventory inv) => new {{ total = inv.TotalValue }});
app.Run();
"""
FORM = """using {ns}.Core;

namespace {ns}.Desktop;

public class MainForm : Form
{{
    private readonly Inventory _inv = new();
    private readonly ListBox _list = new() {{ Dock = DockStyle.Fill, Font = new Font("Segoe UI", 11) }};
    private readonly Label _total = new() {{ Dock = DockStyle.Bottom, Height = 36, Font = new Font("Segoe UI", 12, FontStyle.Bold) }};

    public MainForm()
    {{
        Text = "{title}";
        Width = 520; Height = 380;
        Controls.Add(_list);
        Controls.Add(_total);
        _inv.Add(new Product("Ceiling fan", 4500m, 3));
        _inv.Add(new Product("Steam iron", 3200m, 2));
        foreach (var p in _inv.Items) _list.Items.Add($"{{p.Name}}  x{{p.Quantity}}  Rs {{p.Price:N0}}");
        _total.Text = $"Total value: Rs {{_inv.TotalValue:N0}}";
    }}
}}
"""
FORM_MAIN = """namespace {ns}.Desktop;

static class Program
{{
    [STAThread]
    static void Main()
    {{
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm());
    }}
}}
"""


def env():
    home = (HOME / "home").resolve()
    return dict(os.environ, DOTNET_ROOT=str(HOME.resolve()), DOTNET_CLI_HOME=str(home), NUGET_PACKAGES=str(home / "nuget-packages"),
                NUGET_HTTP_CACHE_PATH=str(home / "nuget-http-cache"), NUGET_PLUGINS_CACHE_PATH=str(home / "nuget-plugins"), DOTNET_CLI_TELEMETRY_OPTOUT="1",
                DOTNET_NOLOGO="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_ADD_GLOBAL_TOOLS_TO_PATH="0",
                MSBUILDDISABLENODEREUSE="1", DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER="1", UseSharedCompilation="false",
                PATH=str(HOME.resolve()) + os.pathsep + os.environ["PATH"])


class Session:
    """dotnet commands on the hidden desktop (each in a job, so build servers it starts end with it); NuGet's AppData leftovers removed."""

    def __init__(self):
        self.leftovers = [Path(os.environ["APPDATA"]) / "NuGet", Path(os.environ["LOCALAPPDATA"]) / "NuGet"]
        self.had = {p: p.exists() for p in self.leftovers}
        self.log = []

    def run(self, *args, cwd=None, timeout=900):
        from .. import hidden_desktop
        rc, out, err, timed_out = hidden_desktop.run([str(DOTNET), *map(str, args)], timeout=timeout, cwd=str(cwd) if cwd else None, env=env())
        self.log.append((" ".join(map(str, args)), rc, out + err))
        return rc == 0 and not timed_out, out + err

    def close(self):
        for p in self.leftovers:
            if not self.had[p] and p.exists():
                shutil.rmtree(p, ignore_errors=True)


def errors(text):
    """'file(line,col): error CS1002: ; expected' -> ['file:line  CS1002 ; expected']"""
    out = []
    for m in re.finditer(r"([^\s>]+\.cs)\((\d+),(\d+)\): error (\w+): ([^\[\r\n]+)", text):
        e = f"{Path(m.group(1)).name}:{m.group(2)} {m.group(4)} {m.group(5).strip()}"
        if e not in out:
            out.append(e)
    return out


def test_summary(text):
    m = re.findall(r"(Passed|Failed)!\s*-\s*Failed:\s*(\d+),\s*Passed:\s*(\d+),\s*Skipped:\s*(\d+),\s*Total:\s*(\d+)", text)
    failed = sum(int(x[1]) for x in m)
    passed = sum(int(x[2]) for x in m)
    total = sum(int(x[4]) for x in m)
    return passed, failed, total


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bvisual\s+studio\b|\bc#|\bcsharp\b|(?<!\w)\.net\b|\bdotnet\b|\basp\.?net\b|\bwinforms\b|\brider\b", c):
        return None
    sol = find_file(text, ctx, {".sln", ".slnx", ".csproj"})
    if sol:
        return {"op": "build", "file": sol}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9]*)['\"]?", text)
    kind = "api" if re.search(r"\bweb\s*api\b|\bapi\b|\basp\.?net\b|\brest\b", c) else "winforms" if re.search(r"\bwinforms\b|\bdesktop\b|\bwindows\s+(?:forms|app)\b", c) \
        else "console"
    return {"op": "new", "kind": kind, "name": m.group(1) if m else "Shop", "publish": bool(re.search(r"\bpublish\b|\bexe\b|\bsingle\s*file\b", c))}


def run(op, ctx):
    if not DOTNET.exists():
        return "The .NET SDK is not in tools/dotnet."
    s = Session()
    try:
        return _build_existing(op, s) if op["op"] == "build" else _new(op, ctx, s)
    finally:
        s.close()


def _build_existing(op, s):
    target = Path(op["file"]).resolve()
    ok, out = s.run("build", target, cwd=target.parent)
    errs = errors(out)
    warn = re.search(r"(\d+) Warning\(s\)", out)
    if not ok:
        return f"Build of {target.name} FAILED with {len(errs)} error(s): " + "; ".join(errs[:8]) + "."
    ok_t, out_t = s.run("test", target, "--no-build", cwd=target.parent)
    passed, failed, total = test_summary(out_t)
    return (f"{target.name} builds with 0 errors" + (f" ({warn.group(1)} warnings)" if warn else "") + ". " +
            (f"Tests: {passed} passed, {failed} failed of {total}." if total else "No test projects found."))


def _new(op, ctx, s):
    ns, kind = op["name"], op["kind"]
    out = (Path(ctx["out"]) / "visualstudio" / ns).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    app = {"console": f"{ns}.App", "api": f"{ns}.Api", "winforms": f"{ns}.Desktop"}[kind]
    template = {"console": "console", "api": "web", "winforms": "winforms"}[kind]
    for args in (("new", "sln", "-n", ns), ("new", "classlib", "-n", f"{ns}.Core"), ("new", template, "-n", app), ("new", "xunit", "-n", f"{ns}.Tests")):
        ok, txt = s.run(*args, cwd=out)
        if not ok:
            return f"dotnet {' '.join(args)} failed: {txt.strip()[-300:]}"
    (out / f"{ns}.Core" / "Class1.cs").unlink(missing_ok=True)
    (out / f"{ns}.Core" / "Inventory.cs").write_text(CORE.format(ns=ns), encoding="utf-8")
    for f in (out / f"{ns}.Tests").glob("UnitTest*.cs"):
        f.unlink()
    (out / f"{ns}.Tests" / "InventoryTests.cs").write_text(TESTS.format(ns=ns), encoding="utf-8")
    if kind == "console":
        (out / app / "Program.cs").write_text(CONSOLE.format(ns=ns), encoding="utf-8")
    elif kind == "api":
        (out / app / "Program.cs").write_text(API.format(ns=ns), encoding="utf-8")
    else:
        for f in (out / app).glob("Form1*.cs"):
            f.unlink()
        (out / app / "MainForm.cs").write_text(FORM.format(ns=ns, title=f"{ns} Inventory"), encoding="utf-8")
        (out / app / "Program.cs").write_text(FORM_MAIN.format(ns=ns), encoding="utf-8")
    sln = next(out.glob(f"{ns}.sln*"))
    for args in (("sln", sln.name, "add", f"{ns}.Core", app, f"{ns}.Tests"), ("add", app, "reference", f"{ns}.Core"), ("add", f"{ns}.Tests", "reference", f"{ns}.Core")):
        ok, txt = s.run(*args, cwd=out)
        if not ok:
            return f"dotnet {' '.join(args)} failed: {txt.strip()[-300:]}"
    ok, txt = s.run("build", sln.name, cwd=out)
    errs = errors(txt)
    checks = [("the solution builds with 0 errors", ok and not errs)]
    ok_t, txt_t = s.run("test", sln.name, "--no-build", cwd=out)
    passed, failed, total = test_summary(txt_t)
    checks.append((f"xUnit tests: {passed} of {total} passed", total >= 5 and failed == 0))
    extra = ""
    if kind == "console":
        ok_r, txt_r = s.run("run", "--project", app, "--no-build", cwd=out, timeout=120)
        checks.append(("the app runs and prints the stock's value (Rs 22,000)", ok_r and "Total value: Rs 22,000" in txt_r))
        extra = " Output: " + " | ".join(ln.strip() for ln in txt_r.strip().splitlines()[-3:])
        if op.get("publish"):
            pub = out / "publish"
            ok_p, txt_p = s.run("publish", app, "-c", "Release", "-r", "win-x64", "--self-contained", "true", "-p:PublishSingleFile=true", "-o", pub,
                                cwd=out, timeout=1200)
            exe = pub / f"{app}.exe"
            ran = ""
            if exe.exists():
                from .. import hidden_desktop
                rc, o, e, _ = hidden_desktop.run([str(exe)], timeout=60)
                ran = o
            checks.append((f"a single-file {exe.name} published ({exe.stat().st_size / 1e6:.0f} MB, runs without .NET installed) and it runs" if exe.exists()
                           else "a single-file exe published", exe.exists() and "Total value" in ran))
    elif kind == "api":
        from .. import hidden_desktop
        port = free_port()
        proc = hidden_desktop.start([str(DOTNET), "run", "--project", app, "--no-build", "--urls", f"http://127.0.0.1:{port}"], cwd=str(out), env=env())
        base, up = f"http://127.0.0.1:{port}", False
        try:
            end = time.monotonic() + 90
            while time.monotonic() < end and proc.alive():
                try:
                    up = http("GET", base + "/products")[0] == 200
                    if up:
                        break
                except OSError:
                    time.sleep(0.5)
            if up:
                st1, _ = http("POST", base + "/products", {"name": "Fan", "price": 4500, "quantity": 3})
                st2, _ = http("POST", base + "/products", {"name": "Iron", "price": 3200, "quantity": -2})
                st3, _ = http("POST", base + "/products/Fan/sell/5")
                st4, val = http("GET", base + "/value")
                st5, items = http("GET", base + "/products")
                checks.append(("the API runs: POST a product 201, a negative stock 400, overselling 409, value and list 200 with the right numbers",
                               (st1, st2, st3, st4, st5) == (201, 400, 409, 200, 200) and float(val["total"]) == 13500 and len(items) == 1))
                extra = f" Called it on {base}: /products, /value (13,500), /products/Fan/sell."
            else:
                checks.append(("the API started and answered", False))
        finally:
            proc.stop()
    else:
        from .. import hidden_desktop
        exe = next((out / app / "bin").rglob(f"{app}.exe"), None)
        seen = False
        if exe:
            proc = hidden_desktop.start([str(exe)], cwd=str(exe.parent), env=env())
            try:
                end = time.monotonic() + 30
                while time.monotonic() < end and not seen:
                    seen = any(w[0] == f"{ns} Inventory" for w in hidden_desktop.windows(proc.pi.dwProcessId))
                    time.sleep(0.5)
            finally:
                proc.stop()
        checks.append((f"the desktop app opens its window '{ns} Inventory' (on the hidden desktop)", seen))
    bad = [w for w, good in checks if not good]
    ctx.setdefault("memo", {})["project"] = str(Path(sln).parent)  # for VS Code and the other tools
    return (f"Visual Studio solution {sln} ({kind}: {ns}.Core with an inventory, {app}, {ns}.Tests with xUnit; opens in Visual Studio, Rider, VS Code)."
            + extra + " " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else "NOT right: " + "; ".join(bad) + ". " + "; ".join(errs[:5])))
