"""Flutter apps (Android Studio and VS Code open them) built here with the Flutter 3.47.6 SDK in tools/flutter (Google's zip,
SHA-256 equal to Google's release list). Flutter's package cache (PUB_CACHE), settings, analytics consent and analysis
caches live in tools/flutter_home (beside the SDK, which is a git checkout Flutter wants left as it is; APPDATA and LOCALAPPDATA pointed there for Flutter, analytics turned off), and every
step runs on the hidden desktop. A project from words (the shop app: an inventory class, a screen with the stock and its
value, unit and widget tests) is analysed, tested and built for the web; the web build is served on 127.0.0.1 only and
read back. A Flutter project given (pubspec.yaml) is analysed and tested, each problem with its file and line.

  "flutter app called 'Shop'"   'flutter test C:\\code\\myapp\\pubspec.yaml'
"""
import os
import re
import shutil
import threading
import urllib.request
from pathlib import Path

from ai_pc.core.config import ROOT

NAME, LABEL = "flutter", "Flutter: apps from words analysed, unit- and widget-tested and built for the web (served on this PC); test any pubspec.yaml"
EXAMPLES = ["flutter app called 'Shop'", "flutter test pubspec.yaml"]
SDK = ROOT / "tools" / "flutter"
FLUTTER = SDK / "bin" / "flutter.bat"

INVENTORY = """/// A product line in stock.
class Product {
  Product(this.name, this.price, this.quantity);

  final String name;
  int price;
  int quantity;

  int get value => price * quantity;
}

/// What the shop holds: add stock, sell it, its value, what is running low.
class Inventory {
  final Map<String, Product> _items = {};

  List<Product> get items => List.unmodifiable(_items.values);

  /// Puts stock in; the same name (in any case) adds to its quantity and takes the new price.
  void add(Product p) {
    if (p.name.trim().isEmpty) throw ArgumentError('A product needs a name.');
    if (p.price < 0 || p.quantity < 0) throw ArgumentError('Price and quantity cannot be negative.');
    final old = _items[p.name.toLowerCase()];
    if (old != null) {
      old.price = p.price;
      old.quantity += p.quantity;
    } else {
      _items[p.name.toLowerCase()] = Product(p.name, p.price, p.quantity);
    }
  }

  /// Takes quantity out; false if there is not that much.
  bool sell(String name, int quantity) {
    final p = _items[name.toLowerCase()];
    if (p == null || quantity <= 0 || p.quantity < quantity) return false;
    p.quantity -= quantity;
    return true;
  }

  int get totalValue => _items.values.fold(0, (sum, p) => sum + p.value);

  /// The products with fewer than [below] in stock, scarcest first.
  List<Product> lowStock(int below) => _items.values.where((p) => p.quantity < below).toList()..sort((a, b) => a.quantity.compareTo(b.quantity));
}

/// 22000 -> "22,000"
String withCommas(int n) => n.toString().replaceAllMapped(RegExp(r'(\\d)(?=(\\d{3})+$)'), (m) => '${m[1]},');
"""
MAIN = """import 'package:flutter/material.dart';

import 'inventory.dart';

void main() => runApp(const ShopApp());

Inventory sampleStock() {
  final inv = Inventory()
    ..add(Product('Ceiling fan', 4500, 3))
    ..add(Product('Steam iron', 3200, 2))
    ..add(Product('Kettle', 2100, 5));
  inv.sell('Kettle', 4);
  return inv;
}

class ShopApp extends StatelessWidget {
  const ShopApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '__TITLE__',
      theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
      home: StockPage(inventory: sampleStock()),
    );
  }
}

class StockPage extends StatelessWidget {
  const StockPage({super.key, required this.inventory});

  final Inventory inventory;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('In stock')),
      body: Column(
        children: [
          Expanded(
            child: ListView(
              children: [
                for (final p in inventory.items)
                  ListTile(title: Text(p.name), subtitle: Text('${p.quantity} x Rs ${withCommas(p.price)}'), trailing: Text('Rs ${withCommas(p.value)}')),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text('Total value: Rs ${withCommas(inventory.totalValue)}', style: Theme.of(context).textTheme.titleLarge),
          ),
        ],
      ),
    );
  }
}
"""
TESTS = """import 'package:flutter_test/flutter_test.dart';
import 'package:__PKG__/inventory.dart';
import 'package:__PKG__/main.dart';

void main() {
  test('adding the same product adds to its stock', () {
    final inv = Inventory()..add(Product('Fan', 4500, 3))..add(Product('fan', 4600, 2));
    expect(inv.items.length, 1);
    expect(inv.items.first.quantity, 5);
    expect(inv.items.first.price, 4600);
  });

  test('negative quantities are refused', () {
    expect(() => Inventory().add(Product('Iron', 3200, -1)), throwsArgumentError);
  });

  test('selling more than in stock fails', () {
    final inv = Inventory()..add(Product('Kettle', 2100, 2));
    expect(inv.sell('Kettle', 3), isFalse);
    expect(inv.sell('Kettle', 2), isTrue);
    expect(inv.items.first.quantity, 0);
  });

  test('total value is price times quantity', () {
    final inv = Inventory()..add(Product('Fan', 4500, 3))..add(Product('Iron', 3200, 2));
    expect(inv.totalValue, 19900);
    expect(withCommas(inv.totalValue), '19,900');
  });

  test('low stock lists the scarcest first', () {
    final inv = Inventory()..add(Product('A', 1, 5))..add(Product('B', 1, 1))..add(Product('C', 1, 9));
    expect(inv.lowStock(6).map((p) => p.name).toList(), ['B', 'A']);
  });

  testWidgets('the screen shows the stock and its value', (tester) async {
    await tester.pumpWidget(const ShopApp());
    expect(find.text('Ceiling fan'), findsOneWidget);
    expect(find.text('Total value: Rs 22,000'), findsOneWidget);
  });
}
"""


def home():
    h = (SDK.parent / "flutter_home").resolve()
    for d in ("pub-cache", "appdata", "localappdata"):
        (h / d).mkdir(parents=True, exist_ok=True)
    return h


def env():
    h = home()
    e = {k: v for k, v in os.environ.items() if not k.upper().startswith(("FLUTTER", "PUB_", "DART"))}
    e.update(FLUTTER_ROOT=str(SDK.resolve()), PUB_CACHE=str(h / "pub-cache"), APPDATA=str(h / "appdata"), LOCALAPPDATA=str(h / "localappdata"),
             FLUTTER_SUPPRESS_ANALYTICS="true", NO_COLOR="1", PATH=str(SDK.resolve() / "bin") + os.pathsep + os.environ["PATH"])
    return e


def flutter(*args, cwd, timeout=1800):
    from ai_pc.core import hidden_desktop
    rc, out, err, timed_out = hidden_desktop.run(["cmd", "/c", str(FLUTTER), *map(str, args)], timeout=timeout, cwd=str(cwd), env=env())
    return rc == 0 and not timed_out, out + err


def setup():
    """Analytics off once (the settings land in tools/flutter_home)."""
    mark = home() / "analytics_off"
    if not mark.exists():
        flutter("config", "--no-analytics", cwd=home())
        flutter("--disable-analytics", cwd=home())
        mark.write_text("flutter config --no-analytics and --disable-analytics ran\n", encoding="utf-8")


def problems(text):
    out = []
    for m in re.finditer(r"^\s*(?:error|warning|info)\s+-\s+(.+?)\s+-\s+(\S+?\.dart):(\d+):\d+", text, re.M):  # flutter analyze
        out.append(f"{Path(m.group(2)).name}:{m.group(3)} {m.group(1)}")
    for m in re.finditer(r"^(\S+?\.dart):(\d+):\d+: Error: (.+)$", text, re.M):  # compile errors in tests
        out.append(f"{Path(m.group(1)).name}:{m.group(2)} {m.group(3)}")
    return list(dict.fromkeys(out))


def tests_passed(text):
    m = re.findall(r"\+(\d+)(?: -(\d+))?: (?:All tests passed|Some tests failed)", text)
    return (int(m[-1][0]), int(m[-1][1] or 0)) if m else (0, 0)


def serve_and_fetch(folder):
    """Serve a web build on 127.0.0.1 (a free port) for a moment and read index.html and main.dart.js back."""
    import functools
    import http.server

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}/"
        page = urllib.request.urlopen(base, timeout=10).read().decode("utf-8", "replace")
        js = urllib.request.urlopen(base + "main.dart.js", timeout=10).read()
        return page, len(js)
    finally:
        srv.shutdown()
        srv.server_close()


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file
    c = text.lower()
    if not re.search(r"\bflutter\b|\bdart\b|\bpubspec\.yaml\b", c):
        return None
    f = find_file(text, ctx, {".yaml"})
    if f and Path(f).name.lower() == "pubspec.yaml":
        return {"op": "test", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9_]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bapp\b|\bproject\b|\bapplication\b", c) else None


def run(op, ctx):
    if not FLUTTER.exists():
        return "Flutter is not in tools/flutter."
    setup()
    if op["op"] == "test":
        folder = Path(op["file"]).resolve().parent
        flutter("pub", "get", cwd=folder)
        ok_a, an = flutter("analyze", "--no-fatal-infos", cwd=folder)
        ok_t, te = flutter("test", cwd=folder)
        passed, failed = tests_passed(te)
        if not (ok_a and ok_t):
            return f"Flutter project {folder.name} FAILED: " + "; ".join(problems(an + te)[:8] or [f"{failed} test(s) failed"]) + "."
        return f"Flutter project {folder.name}: flutter analyze finds no issues; {passed} tests passed."
    name = op["name"]
    pkg = re.sub(r"[^a-z0-9_]", "", name.lower()) or "app"
    if pkg[0].isdigit() or pkg in {"flutter", "test", "dart"}:
        pkg = "app_" + pkg
    parent = (Path(ctx["out"]) / "flutter").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    out = parent / name
    if out.exists():
        shutil.rmtree("\\\\?\\" + str(out), ignore_errors=True)
    ok_c, log_c = flutter("create", "--project-name", pkg, "--org", "com.aipc", "--platforms", "web,android", out.name, cwd=parent, timeout=1800)
    if not ok_c:
        return "flutter create FAILED: " + log_c.strip()[-400:]
    (out / "lib" / "inventory.dart").write_text(INVENTORY, encoding="utf-8", newline="\n")
    (out / "lib" / "main.dart").write_text(MAIN.replace("__TITLE__", name), encoding="utf-8", newline="\n")
    (out / "test" / "widget_test.dart").write_text(TESTS.replace("__PKG__", pkg), encoding="utf-8", newline="\n")
    ok_a, an = flutter("analyze", "--no-fatal-infos", cwd=out)
    ok_t, te = flutter("test", cwd=out)
    passed, failed = tests_passed(te)
    ok_w, log_w = flutter("build", "web", "--release", "--no-web-resources-cdn", cwd=out)
    web = out / "build" / "web"
    page, js = serve_and_fetch(web) if (web / "index.html").exists() else ("", 0)
    checks = [("flutter analyze finds no issues", ok_a and "No issues found" in an),
              (f"flutter test: {passed} of 6 tests passed (5 unit tests + a widget test that finds 'Total value: Rs 22,000' on the screen)", ok_t and passed == 6 and not failed),
              (f"flutter build web made the web app; served on 127.0.0.1 it answers with its page and main.dart.js ({js / 1024 / 1024:.1f} MB)",
               ok_w and "<html" in page.lower() and js > 100_000)]
    bad = [w for w, good in checks if not good]
    ctx.setdefault("memo", {})["project"] = str(out)
    return (f"Flutter app {out} (lib/inventory.dart, lib/main.dart, test/; android/ and web/ ready; open it in Android Studio or VS Code). "
            f"Web build: {web}. " + ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad else
                                     "NOT right: " + "; ".join(bad) + ". " + "; ".join(problems(an + te)[:5]) + " " + (log_w.strip()[-300:] if not ok_w else "")))
