"""IntelliJ IDEA / Eclipse projects by their build tool: Java 25 (Eclipse Temurin JDK in tools/jdk; SHA-256, Adoptium GPG and
Eclipse Foundation signature checked) with Apache Maven 3.10 (tools/maven; Apache SHA-512 checked). A Maven project is made
(pom.xml, an inventory library, a runnable main, JUnit 5 tests), really built here: compiled, tested by Surefire, packaged
as a jar and run; or a pom.xml given is built and tested with every compile error's file and line. Opens in IntelliJ IDEA,
Eclipse and VS Code. Maven's local repository and settings stay in tools/maven/home (user.home pointed there).

  "intellij java project called 'Shop'"   'java maven app called Stock'   'intellij build and test C:\\code\\app\\pom.xml'
"""
import os
import re
import shutil
from pathlib import Path

from ..config import ROOT

NAME, LABEL = "intellij", "IntelliJ / Eclipse: Java 25 Maven projects with JUnit 5, built, tested, packaged and run; build any pom.xml"
EXAMPLES = ["intellij java project called 'Shop'", "java maven app called Stock", "intellij build and test pom.xml"]
JDK = next(iter(sorted((ROOT / "tools" / "jdk").glob("jdk-*"))), None) if (ROOT / "tools" / "jdk").exists() else None
MVN = next(iter(sorted((ROOT / "tools" / "maven").rglob("mvn.cmd"))), None) if (ROOT / "tools" / "maven").exists() else None

POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.{pkg}</groupId>
  <artifactId>{artifact}</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
  <name>{name}</name>
  <properties>
    <maven.compiler.release>25</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.11.4</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <finalName>{artifact}</finalName>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.13.0</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.5.2</version>
      </plugin>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-jar-plugin</artifactId>
        <version>3.4.2</version>
        <configuration>
          <archive><manifest><mainClass>com.{pkg}.App</mainClass></manifest></archive>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
"""
PRODUCT = """package com.{pkg};

/** A product line in stock. */
public record Product(String name, long price, int quantity) {{
    public long value() {{ return price * quantity; }}
}}
"""
INVENTORY = """package com.{pkg};

import java.util.*;
import java.util.stream.Collectors;

/** What the shop holds: add stock, sell it, its value, what is running low. */
public class Inventory {{
    private final Map<String, Product> items = new LinkedHashMap<>();

    public Collection<Product> items() {{ return Collections.unmodifiableCollection(items.values()); }}

    public void add(Product p) {{
        if (p.name() == null || p.name().isBlank()) throw new IllegalArgumentException("A product needs a name.");
        if (p.price() < 0 || p.quantity() < 0) throw new IllegalArgumentException("Price and quantity cannot be negative.");
        String key = p.name().toLowerCase(Locale.ROOT);
        Product old = items.get(key);
        items.put(key, old == null ? p : new Product(old.name(), p.price(), old.quantity() + p.quantity()));
    }}

    public boolean sell(String name, int quantity) {{
        String key = name.toLowerCase(Locale.ROOT);
        Product p = items.get(key);
        if (p == null || quantity <= 0 || p.quantity() < quantity) return false;
        items.put(key, new Product(p.name(), p.price(), p.quantity() - quantity));
        return true;
    }}

    public long totalValue() {{ return items.values().stream().mapToLong(Product::value).sum(); }}

    public List<Product> lowStock(int below) {{
        return items.values().stream().filter(p -> p.quantity() < below)
                .sorted(Comparator.comparingInt(Product::quantity)).collect(Collectors.toList());
    }}
}}
"""
APP = """package com.{pkg};

public class App {{
    public static void main(String[] args) {{
        Inventory inv = new Inventory();
        inv.add(new Product("Ceiling fan", 4500, 3));
        inv.add(new Product("Steam iron", 3200, 2));
        inv.add(new Product("Kettle", 2100, 5));
        inv.sell("Kettle", 4);
        for (Product p : inv.items())
            System.out.printf("%-12s %3d x Rs %,d%n", p.name(), p.quantity(), p.price());
        System.out.printf("Total value: Rs %,d%n", inv.totalValue());
        System.out.println("Low stock: " + String.join(", ", inv.lowStock(3).stream().map(Product::name).toList()));
    }}
}}
"""
TEST = """package com.{pkg};

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class InventoryTest {{
    @Test void addingTheSameProductAddsToItsStock() {{
        Inventory inv = new Inventory();
        inv.add(new Product("Fan", 4500, 3));
        inv.add(new Product("fan", 4600, 2));
        assertEquals(1, inv.items().size());
        Product fan = inv.items().iterator().next();
        assertEquals(5, fan.quantity());
        assertEquals(4600, fan.price());
    }}

    @Test void negativeQuantitiesAreRefused() {{
        assertThrows(IllegalArgumentException.class, () -> new Inventory().add(new Product("Iron", 3200, -1)));
    }}

    @Test void sellingMoreThanInStockFails() {{
        Inventory inv = new Inventory();
        inv.add(new Product("Kettle", 2100, 2));
        assertFalse(inv.sell("Kettle", 3));
        assertTrue(inv.sell("Kettle", 2));
        assertEquals(0, inv.items().iterator().next().quantity());
    }}

    @Test void totalValueIsPriceTimesQuantity() {{
        Inventory inv = new Inventory();
        inv.add(new Product("Fan", 4500, 3));
        inv.add(new Product("Iron", 3200, 2));
        assertEquals(19900, inv.totalValue());
    }}

    @Test void lowStockListsTheScarcestFirst() {{
        Inventory inv = new Inventory();
        inv.add(new Product("A", 1, 5));
        inv.add(new Product("B", 1, 1));
        inv.add(new Product("C", 1, 9));
        assertEquals(List.of("B", "A"), inv.lowStock(6).stream().map(Product::name).toList());
    }}
}}
"""


def env():
    home = (ROOT / "tools" / "maven" / "home").resolve()
    home.mkdir(parents=True, exist_ok=True)
    return dict(os.environ, JAVA_HOME=str(JDK.resolve()), PATH=str(JDK.resolve() / "bin") + os.pathsep + os.environ["PATH"],
                MAVEN_OPTS=f"-Duser.home={home} -Dmaven.repo.local={home / 'repository'}", MAVEN_ARGS="-B")


def mvn(*args, cwd, timeout=1200):
    from .. import hidden_desktop
    rc, out, err, timed_out = hidden_desktop.run(["cmd", "/c", str(MVN), *map(str, args)], timeout=timeout, cwd=str(cwd), env=env())
    return rc == 0 and not timed_out, out + err


def compile_errors(text):
    out = []
    for m in re.finditer(r"\[ERROR\]\s+(?:/)?([^\s\[\]]+\.java):\[(\d+),(\d+)\]\s+(.+)", text):
        e = f"{Path(m.group(1)).name}:{m.group(2)} {m.group(4).strip()}"
        if e not in out:
            out.append(e)
    return out


def surefire(folder):
    """(tests, failures + errors, skipped) from Surefire's reports."""
    run = bad = skip = 0
    for f in Path(folder).rglob("surefire-reports/*.txt"):
        m = re.search(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)", f.read_text(encoding="utf-8", errors="replace"))
        if m:
            run += int(m.group(1))
            bad += int(m.group(2)) + int(m.group(3))
            skip += int(m.group(4))
    return run, bad, skip


def parse(text, ctx):
    from .appschat import find_file
    c = text.lower()
    if not re.search(r"\bintellij\b|\beclipse\b|\bjava\b|\bmaven\b|\bpom\.xml\b", c):
        return None
    pom = find_file(text, ctx, {".xml"})
    if pom and Path(pom).name.lower() == "pom.xml":
        return {"op": "build", "file": pom}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bproject\b|\bapp\b|\bmaven\b|\bapplication\b", c) else None


def run(op, ctx):
    if not (JDK and MVN):
        return "The JDK and Maven are not in tools/jdk and tools/maven."
    from .. import hidden_desktop
    if op["op"] == "build":
        folder = Path(op["file"]).resolve().parent
        ok, txt = mvn("-q", "package", cwd=folder)
        errs = compile_errors(txt)
        tests, bad, skip = surefire(folder)
        if not ok:
            return (f"Maven build of {folder.name} FAILED" + (f" with {len(errs)} compile error(s): " + "; ".join(errs[:8]) if errs else
                    (f": {bad} of {tests} tests failed" if bad else ": " + txt.strip()[-300:])) + ".")
        return f"{folder.name} builds with Maven: {tests} tests, {bad} failed, {skip} skipped; jar(s): " + \
            ", ".join(p.name for p in (folder / "target").glob("*.jar")) + "."
    name = op["name"]
    pkg = re.sub(r"[^a-z0-9]", "", name.lower()) or "app"
    artifact = re.sub(r"[^a-z0-9-]", "-", name.lower())
    out = (Path(ctx["out"]) / "intellij" / name).resolve()
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    src = out / "src" / "main" / "java" / "com" / pkg
    test = out / "src" / "test" / "java" / "com" / pkg
    src.mkdir(parents=True)
    test.mkdir(parents=True)
    (out / "pom.xml").write_text(POM.format(pkg=pkg, artifact=artifact, name=name), encoding="utf-8")
    for f, t in (("Product.java", PRODUCT), ("Inventory.java", INVENTORY), ("App.java", APP)):
        (src / f).write_text(t.format(pkg=pkg), encoding="utf-8")
    (test / "InventoryTest.java").write_text(TEST.format(pkg=pkg), encoding="utf-8")
    (out / ".gitignore").write_text("target/\n.idea/\n*.iml\n", encoding="utf-8")
    ok, txt = mvn("-q", "package", cwd=out)
    errs = compile_errors(txt)
    tests, bad, skip = surefire(out)
    jar = out / "target" / f"{artifact}.jar"
    checks = [("Maven compiled it with Java 25, no errors", ok and not errs), (f"JUnit 5: {tests - bad} of {tests} tests passed", tests >= 5 and bad == 0),
              ("the jar was packaged", jar.exists())]
    ran = ""
    if jar.exists():
        rc, o, e, _ = hidden_desktop.run([str(JDK / "bin" / "java.exe"), "-jar", str(jar)], timeout=60, env=env())
        ran = o
        checks.append(("java -jar runs it and prints the stock's value (Rs 22,000)", "Total value: Rs 22,000" in o))
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad_checks = [w for w, good in checks if not good]
    return (f"Java project {out} (Maven: pom.xml, com.{pkg}.Inventory, App, JUnit tests; open the folder in IntelliJ IDEA, Eclipse or VS Code). " +
            (f"Output: {' | '.join(ln.strip() for ln in ran.strip().splitlines()[-2:])}. " if ran else "") +
            ("Checked: " + "; ".join(w for w, _ in checks) + "." if not bad_checks else "NOT right: " + "; ".join(bad_checks) + ". " + "; ".join(errs[:5])))
