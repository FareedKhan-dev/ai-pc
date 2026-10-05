"""Android Studio projects built here for real: Google's Android SDK (tools/android/sdk: command-line tools checked against
developer.android.com's SHA-256, then platform 36, build-tools 37.0.0 and platform-tools fetched by Google's sdkmanager,
binaries Google-signed) with Gradle 9.8.0 (tools/gradle, gradle.org SHA-256) and the Android Gradle Plugin from Google's
Maven, on our JDK. Gradle runs on the hidden desktop with its caches in tools/gradle/home and the Android user folder in
tools/android/home, so ~/.gradle and ~/.android are never made.

A project from words (an Android app in Java: the shop inventory classes, a screen showing the stock and its value,
JUnit tests, the Gradle wrapper so Android Studio opens it as is) is built to a debug APK and checked: the unit tests'
own report, the APK's package, SDK levels and launcher activity read back by aapt2, its signature verified by apksigner,
and the app's classes found in its dex. A project folder given is built the same way, every compile error with its
file and line. 'install it on my phone' puts the last APK on a USB-connected phone (USB debugging on) after a yes.

  "android studio app called 'Shop'"   'android app called Stock'   'android build C:\\code\\MyApp\\settings.gradle.kts'   'install it on my phone'
"""

import os
import re
import shutil
import zipfile
from pathlib import Path

from ai_pc.apps.intellij import INVENTORY, PRODUCT
from ai_pc.core.config import ROOT

NAME, LABEL = (
    "androidstudio",
    "Android Studio: Android apps (Java) built to a real APK with Gradle, unit-tested, checked by aapt2/apksigner; install after a yes",
)
EXAMPLES = ["android studio app called 'Shop'", "android app called Stock", "android build settings.gradle.kts", "install it on my phone"]
OUTWARD = {"install"}
SDK = ROOT / "tools" / "android" / "sdk"
GRADLE = next(iter(sorted((ROOT / "tools" / "gradle").glob("gradle-*/bin/gradle.bat"))), None) if (ROOT / "tools" / "gradle").exists() else None
JDK = next(iter(sorted((ROOT / "tools" / "jdk").glob("jdk-*"))), None) if (ROOT / "tools" / "jdk").exists() else None
AGP, COMPILE_SDK, BUILD_TOOLS, MIN_SDK = "9.4.1", 36, "37.0.0", 24
GRADLE_SHA256 = "bafd5ce9cfaea0fbccfdc8439a1ac42fbd4cd9c89dc9a988228d8a2639a58e6c"  # gradle-9.8.0-bin.zip, services.gradle.org
JAVA_WORDS = {
    "abstract",
    "boolean",
    "break",
    "byte",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extends",
    "final",
    "finally",
    "float",
    "for",
    "goto",
    "if",
    "implements",
    "import",
    "instanceof",
    "int",
    "interface",
    "long",
    "native",
    "new",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "short",
    "static",
    "super",
    "switch",
    "synchronized",
    "this",
    "throw",
    "throws",
    "transient",
    "try",
    "void",
    "volatile",
    "while",
    "true",
    "false",
    "null",
    "var",
    "record",
    "yield",
}

SETTINGS = """pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}
dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}
rootProject.name = "{name}"
include(":app")
"""
ROOT_BUILD = """plugins {{
    id("com.android.application") version "{agp}" apply false
}}
"""
APP_BUILD = """plugins {{
    id("com.android.application")
}}

android {{
    namespace = "com.{pkg}"
    compileSdk = {sdk}
    buildToolsVersion = "{tools}"

    defaultConfig {{
        applicationId = "com.{pkg}"
        minSdk = {min_sdk}
        targetSdk = {sdk}
        versionCode = 1
        versionName = "1.0"
    }}
    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
}}

dependencies {{
    testImplementation("junit:junit:4.13.2")
}}
"""
MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application
        android:allowBackup="false"
        android:icon="@drawable/ic_launcher"
        android:label="@string/app_name"
        android:theme="@android:style/Theme.Material.Light.DarkActionBar">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
ACTIVITY = """package com.{pkg};

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
import java.util.Locale;

/** The first screen: what is in stock and what it is worth. */
public class MainActivity extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        Inventory inv = new Inventory();
        inv.add(new Product("Ceiling fan", 4500, 3));
        inv.add(new Product("Steam iron", 3200, 2));
        inv.add(new Product("Kettle", 2100, 5));
        inv.sell("Kettle", 4);
        StringBuilder lines = new StringBuilder();
        for (Product p : inv.items())
            lines.append(String.format(Locale.US, "%-12s %3d x Rs %,d%n", p.name(), p.quantity(), p.price()));
        ((TextView) findViewById(R.id.items)).setText(lines.toString());
        ((TextView) findViewById(R.id.total)).setText(getString(R.string.total, String.format(Locale.US, "%,d", inv.totalValue())));
    }}
}}
"""
LAYOUT = """<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:padding="24dp">

    <TextView
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="@string/heading"
        android:textSize="22sp"
        android:textStyle="bold" />

    <TextView
        android:id="@+id/items"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:layout_marginTop="16dp"
        android:fontFamily="monospace"
        android:textSize="16sp" />

    <TextView
        android:id="@+id/total"
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:layout_marginTop="16dp"
        android:textSize="18sp"
        android:textStyle="bold" />
</LinearLayout>
"""
STRINGS = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{name}</string>
    <string name="heading">In stock</string>
    <string name="total">Total value: Rs %1$s</string>
</resources>
"""
ICON = """<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="48dp" android:height="48dp" android:viewportWidth="48" android:viewportHeight="48">
    <path android:fillColor="#1E88E5" android:pathData="M24,2a22,22 0,1 1,0 44a22,22 0,1 1,0 -44z" />
    <path android:fillColor="#FFFFFF" android:pathData="M14,18h20l-2,16h-16z M18,18a6,6 0,0 1,12 0h-2a4,4 0,0 0,-8 0z" />
</vector>
"""
TEST = """package com.{pkg};

import static org.junit.Assert.*;

import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;
import org.junit.Test;

public class InventoryTest {{
    @Test public void addingTheSameProductAddsToItsStock() {{
        Inventory inv = new Inventory();
        inv.add(new Product("Fan", 4500, 3));
        inv.add(new Product("fan", 4600, 2));
        assertEquals(1, inv.items().size());
        Product fan = inv.items().iterator().next();
        assertEquals(5, fan.quantity());
        assertEquals(4600, fan.price());
    }}

    @Test public void negativeQuantitiesAreRefused() {{
        assertThrows(IllegalArgumentException.class, () -> new Inventory().add(new Product("Iron", 3200, -1)));
    }}

    @Test public void sellingMoreThanInStockFails() {{
        Inventory inv = new Inventory();
        inv.add(new Product("Kettle", 2100, 2));
        assertFalse(inv.sell("Kettle", 3));
        assertTrue(inv.sell("Kettle", 2));
        assertEquals(0, inv.items().iterator().next().quantity());
    }}

    @Test public void totalValueIsPriceTimesQuantity() {{
        Inventory inv = new Inventory();
        inv.add(new Product("Fan", 4500, 3));
        inv.add(new Product("Iron", 3200, 2));
        assertEquals(19900, inv.totalValue());
    }}

    @Test public void lowStockListsTheScarcestFirst() {{
        Inventory inv = new Inventory();
        inv.add(new Product("A", 1, 5));
        inv.add(new Product("B", 1, 1));
        inv.add(new Product("C", 1, 9));
        List<String> names = inv.lowStock(6).stream().map(Product::name).collect(Collectors.toList());
        assertEquals(Arrays.asList("B", "A"), names);
    }}
}}
"""


def home():
    h = (ROOT / "tools" / "android" / "home").resolve()
    (h / ".android").mkdir(parents=True, exist_ok=True)
    return h


def gradle_home():
    """Gradle's caches and the settings of its single-use build process (Gradle drops -Duser.home from these, so the
    Android settings folder is set by environment variable instead, which the build process does inherit)."""
    g = (ROOT / "tools" / "gradle" / "home").resolve()
    g.mkdir(parents=True, exist_ok=True)
    props = "org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8\norg.gradle.daemon=false\norg.gradle.welcome=never\nkotlin.compiler.execution.strategy=in-process\n"
    if not (g / "gradle.properties").exists() or (g / "gradle.properties").read_text(encoding="utf-8") != props:
        (g / "gradle.properties").write_text(props, encoding="utf-8")
    return g


def env():
    """ANDROID_PREFS_ROOT (not ANDROID_USER_HOME): Google's analytics library reads only ANDROID_PREFS_ROOT, ANDROID_SDK_HOME or
    user.home, and wrote ~/.android/analytics.settings when only ANDROID_USER_HOME was set; the Android tools refuse two
    settings that disagree, so this one alone points both at tools/android/home/.android."""
    h = home()
    return dict(
        os.environ,
        JAVA_HOME=str(JDK.resolve()),
        ANDROID_HOME=str(SDK.resolve()),
        ANDROID_SDK_ROOT=str(SDK.resolve()),
        ANDROID_PREFS_ROOT=str(h),
        GRADLE_USER_HOME=str(gradle_home()),
        GRADLE_OPTS=f"-Duser.home={h}",
        PATH=str(JDK.resolve() / "bin") + os.pathsep + os.environ["PATH"],
    )


def adb_env():
    """adb with its Wi-Fi phone discovery off (mDNS listens on every network, which makes Windows Firewall ask the user
    'Allow access?') and on its own port (5137), away from any other adb on this PC. adb keeps its key in ~/.android
    whatever is set: the phone remembers this computer by it."""
    return dict(env(), ADB_MDNS="0", ANDROID_ADB_SERVER_PORT="5137")


def gradle(*args, cwd, timeout=1800):
    from ai_pc.core import hidden_desktop

    rc, out, err, timed_out = hidden_desktop.run(
        ["cmd", "/c", str(GRADLE), "--no-daemon", "--console=plain", *map(str, args)], timeout=timeout, cwd=str(cwd), env=env()
    )
    return rc == 0 and not timed_out, out + err


def tool(*args, timeout=120):
    from ai_pc.core import hidden_desktop

    rc, out, err, _ = hidden_desktop.run(["cmd", "/c", *map(str, args)], timeout=timeout, env=env())
    return rc == 0, out + err


def compile_errors(text):
    out = []
    for m in re.finditer(r"([A-Za-z]:[\\/][^\s:]+?\.(?:java|kt|xml)):(\d+):(?:\d+:)?\s*error:\s*(.+)|e: file:///([^\s]+?\.kt):(\d+):\d+ (.+)", text):
        f, line, msg = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
        e = f"{Path(f).name}:{line} {msg.strip()}"
        if e not in out:
            out.append(e)
    return out


def unit_tests(project):
    """(tests, failures + errors) from the JUnit XML reports Gradle wrote."""
    run = bad = 0
    for f in Path(project).rglob("build/test-results/*/TEST-*.xml"):
        head = f.read_text(encoding="utf-8", errors="replace")[:600]
        m = re.search(r'tests="(\d+)".*?failures="(\d+)".*?errors="(\d+)"', head, re.S) or re.search(r'tests="(\d+)"', head)
        if m:
            run += int(m.group(1))
            bad += int(m.group(2)) + int(m.group(3)) if m.lastindex and m.lastindex >= 3 else 0
    return run, bad


def badging(apk):
    """aapt2's reading of the APK: package, version, SDK levels, launcher activity, label."""
    ok, txt = tool(SDK / "build-tools" / BUILD_TOOLS / "aapt2.exe", "dump", "badging", apk)
    get = lambda pat: (re.search(pat, txt) or [None, None])[1]  # noqa: E731
    return {
        "package": get(r"package: name='([^']+)'"),
        "version": get(r"versionName='([^']+)'"),
        "min": get(r"(?:minSdkVersion|sdkVersion):'(\d+)'"),
        "target": get(r"targetSdkVersion:'(\d+)'"),
        "activity": get(r"launchable-activity: name='([^']+)'"),
        "label": get(r"application-label:'([^']*)'"),
    }


def signed(apk):
    ok, txt = tool(SDK / "build-tools" / BUILD_TOOLS / "apksigner.bat", "verify", "--verbose", "--print-certs", apk)
    return ok and "Verified using v2 scheme (APK Signature Scheme v2): true" in txt, (re.search(r"certificate DN: (.+)", txt) or [None, ""])[
        1
    ].strip()


def dex_has(apk, classes):
    with zipfile.ZipFile(apk) as z:
        dex = b"".join(z.read(n) for n in z.namelist() if re.fullmatch(r"classes\d*\.dex", n))
    return all(f"L{c.replace('.', '/')};".encode() in dex for c in classes)


def adb(*args, timeout=120):
    from ai_pc.core import hidden_desktop

    rc, out, err, _ = hidden_desktop.run([str(SDK / "platform-tools" / "adb.exe"), *map(str, args)], timeout=timeout, env=adb_env())
    return rc == 0, out + err


def usb_phones():
    """Android phones plugged in with USB debugging on, from Windows' own device list: adb is not started to look."""
    import subprocess

    ps = (
        "Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'ADB' -or $_.Class -eq 'AndroidUsbDeviceClass' } "
        "| ForEach-Object { $_.FriendlyName }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, creationflags=0x08000000, timeout=90).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def devices(txt):
    """[(serial, model)] of the phones adb lists as ready ('device', not 'unauthorized')."""
    return [
        (m.group(1), (re.search(r"model:(\S+)", m.group(2)) or [None, "Android phone"])[1]) for m in re.finditer(r"^(\S+)\s+device\b(.*)$", txt, re.M)
    ]


def parse(text, ctx):
    from ai_pc.apps.appschat import find_file

    c = text.lower()
    if re.search(r"\b(?:install|put|run)\b.*\b(?:on|to)\s+(?:my\s+)?(?:phone|mobile|android|device)\b", c) and (
        re.search(r"\bandroid\b|\bapk\b", c) or (ctx.get("memo") or {}).get("android")
    ):
        f = find_file(text, ctx, {".apk"})
        return {"op": "install", "file": f}
    if not re.search(r"\bandroid\b|\bapk\b", c):
        return None
    f = find_file(text, ctx, {".kts", ".gradle"})
    if f:
        return {"op": "build", "file": f}
    m = re.search(r"\b(?:called|named)\s+['\"]?([A-Za-z][A-Za-z0-9]*)['\"]?", text)
    return {"op": "new", "name": m.group(1) if m else "Shop"} if re.search(r"\bapp\b|\bproject\b|\bapplication\b|\bapk\b", c) else None


def _apk(op, ctx):
    return op.get("file") or ((ctx.get("memo") or {}).get("android") or {}).get("apk")


def preview(op, ctx):
    apk = _apk(op, ctx)
    if not apk or not Path(apk).exists():
        op["blocked"] = True
        return "There is no APK to install yet: ask for an Android app first (for example: android app called Shop)."
    found = usb_phones()
    if not found:
        op["blocked"] = True
        return (
            "No Android phone is connected. On the phone: Settings > About phone > tap Build number 7 times, then Developer options > "
            "USB debugging on; connect it by USB; then ask again."
        )
    return (
        f"Install {Path(apk).name} on the phone ({found[0]}) over USB and open it. This starts Google's adb for the job only (this PC only, "
        "no Wi-Fi discovery); the phone asks once 'Allow USB debugging?', and adb keeps its key in your user folder (.android) so the phone "
        "remembers this PC."
    )


def run(op, ctx):
    if not (SDK.exists() and GRADLE and JDK):
        return "The Android SDK, Gradle and the JDK are not in tools/android, tools/gradle and tools/jdk."
    if op["op"] == "install":
        import socket
        import time

        from ai_pc.core import hidden_desktop

        apk = _apk(op, ctx)
        server = hidden_desktop.start(
            [str(SDK / "platform-tools" / "adb.exe"), "-L", "tcp:localhost:5137", "nodaemon", "server"], env=adb_env()
        )  # one adb server for the job, on this PC only, ended after
        try:
            end = time.monotonic() + 20
            while time.monotonic() < end:
                try:
                    socket.create_connection(("127.0.0.1", 5137), timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.3)
            found = []
            end = time.monotonic() + 60  # time to tap 'Allow' on the phone the first time
            while time.monotonic() < end and not found:
                found = devices(adb("devices", "-l")[1])
                if not found:
                    time.sleep(2)
            if not found:
                return "No phone answered over USB: unlock it, tap 'Allow' when it asks 'Allow USB debugging?', then ask again."
            serial, model = found[0]
            ok, txt = adb("-s", serial, "install", "-r", apk, timeout=300)
            info = badging(apk)
            if not (ok and "Success" in txt):
                return f"Install on {model} FAILED: {txt.strip()[-300:]}"
            adb("-s", serial, "shell", "am", "start", "-n", f"{info['package']}/{info['activity']}")
            ok_p, pid = adb("-s", serial, "shell", "pidof", info["package"])
            return f"Installed {Path(apk).name} on {model} ({serial}) and opened it. " + (
                "Checked: the app is running on the phone."
                if ok_p and pid.strip()
                else "It installed, but it is not running yet: open it from the phone."
            )
        finally:
            adb("kill-server")
            server.wait(10)
            server.stop()
    if op["op"] == "build":
        folder = Path(op["file"]).resolve().parent
        if (
            not (folder / "settings.gradle.kts").exists()
            and not (folder / "settings.gradle").exists()
            and (folder.parent / "settings.gradle.kts").exists()
        ):
            folder = folder.parent
        ok, txt = gradle("assembleDebug", "testDebugUnitTest", cwd=folder)
        errs = compile_errors(txt)
        tests, bad = unit_tests(folder)
        apks = sorted(folder.rglob("build/outputs/apk/debug/*.apk"))
        if not ok:
            return (
                f"Android build of {folder.name} FAILED"
                + (
                    f" with {len(errs)} compile error(s): " + "; ".join(errs[:8])
                    if errs
                    else (
                        f": {bad} of {tests} unit tests failed"
                        if bad
                        else ": " + " ".join(ln for ln in txt.strip().splitlines() if ln.startswith(("*", ">", "FAILURE", "What went wrong")))[-400:]
                    )
                )
                + "."
            )
        if apks:
            ctx.setdefault("memo", {})["android"] = {"apk": str(apks[0])}
        return f"{folder.name} builds with Gradle: {tests} unit tests, {bad} failed; APK: " + ", ".join(str(p) for p in apks) + "."
    name = op["name"]
    pkg = re.sub(r"[^a-z0-9]", "", name.lower()) or "app"
    if pkg in JAVA_WORDS or pkg[0].isdigit():
        pkg = "app" + pkg
    out = (Path(ctx["out"]) / "androidstudio" / name).resolve()
    if out.exists():  # the \\?\ form: Gradle's build folders go past Windows' 260-character path limit
        shutil.rmtree("\\\\?\\" + str(out), ignore_errors=True)
    app = out / "app" / "src"
    files = {
        out / "settings.gradle.kts": SETTINGS.format(name=name),
        out / "build.gradle.kts": ROOT_BUILD.format(agp=AGP),
        out / "gradle.properties": "org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\nandroid.nonTransitiveRClass=true\n"
        "# a Java-only app: no Kotlin standard library added to the APK\nandroid.builtInKotlin=false\n",
        out / "local.properties": "sdk.dir=" + str(SDK.resolve()).replace("\\", "\\\\").replace(":", "\\:") + "\n",
        out / ".gitignore": "/build\n/app/build\n.gradle/\nlocal.properties\n.idea/\n*.iml\n.kotlin/\n",
        out / "app" / "build.gradle.kts": APP_BUILD.format(pkg=pkg, sdk=COMPILE_SDK, tools=BUILD_TOOLS, min_sdk=MIN_SDK),
        app / "main" / "AndroidManifest.xml": MANIFEST,
        app / "main" / "java" / "com" / pkg / "MainActivity.java": ACTIVITY.format(pkg=pkg),
        app / "main" / "java" / "com" / pkg / "Product.java": PRODUCT.format(pkg=pkg),
        app / "main" / "java" / "com" / pkg / "Inventory.java": INVENTORY.format(pkg=pkg).replace("p.name().isBlank()", "p.name().trim().isEmpty()"),
        app / "main" / "res" / "layout" / "activity_main.xml": LAYOUT,
        app / "main" / "res" / "values" / "strings.xml": STRINGS.format(name=name),
        app / "main" / "res" / "drawable" / "ic_launcher.xml": ICON,
        app / "test" / "java" / "com" / pkg / "InventoryTest.java": TEST.format(pkg=pkg),
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    version = re.search(r"gradle-([\d.]+)", str(GRADLE)).group(1)
    ok, txt = gradle(
        "wrapper",
        "--gradle-version",
        version,
        "--distribution-type",
        "bin",
        "--gradle-distribution-sha256-sum",
        GRADLE_SHA256,
        "assembleDebug",
        "testDebugUnitTest",
        cwd=out,
    )
    errs = compile_errors(txt)
    tests, bad = unit_tests(out)
    apk = out / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    checks = [
        (
            "Gradle built it (Android Gradle Plugin " + AGP + ", Java 17 code, SDK " + str(COMPILE_SDK) + "), no errors",
            ok and not errs and apk.exists(),
        ),
        (f"JUnit: {tests - bad} of {tests} unit tests passed", tests >= 5 and bad == 0),
    ]
    if apk.exists():
        info = badging(apk)
        good_sig, dn = signed(apk)
        checks += [
            (
                f"aapt2 reads the APK: package com.{pkg}, version 1.0, min SDK {MIN_SDK} (Android 7), target SDK {COMPILE_SDK}, "
                f"launcher MainActivity, label '{name}'",
                info
                == {
                    "package": f"com.{pkg}",
                    "version": "1.0",
                    "min": str(MIN_SDK),
                    "target": str(COMPILE_SDK),
                    "activity": f"com.{pkg}.MainActivity",
                    "label": name,
                },
            ),
            (f"apksigner verifies its signature (v2, {dn or 'debug key'})", good_sig),
            (
                "its dex holds the app's classes (MainActivity, Inventory, Product)",
                dex_has(apk, [f"com.{pkg}.MainActivity", f"com.{pkg}.Inventory", f"com.{pkg}.Product"]),
            ),
        ]
        ctx.setdefault("memo", {})["android"] = {"apk": str(apk), "project": str(out)}
    checks.append(
        (
            "the Gradle wrapper is there (gradlew.bat, checks the Gradle download's SHA-256)",
            (out / "gradlew.bat").exists()
            and GRADLE_SHA256 in (out / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text(encoding="utf-8"),
        )
    )
    ctx.setdefault("memo", {})["project"] = str(out)  # for VS Code and the other tools
    bad_checks = [w for w, good in checks if not good]
    size = f" ({apk.stat().st_size / 1024:,.0f} KB)" if apk.exists() else ""
    return (
        f"Android app '{name}' {out} (open the folder in Android Studio; Java, com.{pkg}: MainActivity shows the stock and its value). "
        f"Debug APK: {apk}{size}; 'install it on my phone' puts it on a USB-connected phone after a yes. "
        + (
            "Checked: " + "; ".join(w for w, _ in checks) + "."
            if not bad_checks
            else "NOT right: "
            + "; ".join(bad_checks)
            + ". "
            + ("; ".join(errs[:5]) or " ".join(ln for ln in txt.strip().splitlines() if ln.startswith(("*", "FAILURE", ">")))[-500:])
        )
    )
