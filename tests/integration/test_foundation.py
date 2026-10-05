"""Foundation test on Calculator: app discovery, launch, UIA snapshot speed (vs naive walk), invoke speed, cleanup."""
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_pc import apps
from ai_pc.desktop import inputs, observe, uia  # noqa: E402

ms = lambda t: (time.perf_counter() - t) * 1000  # noqa: E731

if apps.find_window(title_substr="Calculator"):
    sys.exit("A Calculator window is already open; close it first so I don't touch yours.")

t = time.perf_counter()
lst = apps.installed_apps(refresh=True)
print(f"[apps] discovered {len(lst)} installed apps in {ms(t):.0f} ms (e.g. {[a['name'] for a in lst[:4]]})")

t = time.perf_counter()
app = apps.find_app("calculator")
print(f"[apps] fuzzy match 'calculator' -> {app['name'] if app else None} ({ms(t):.1f} ms)")

t = time.perf_counter()
hwnd, name = apps.launch("calculator")
print(f"[launch] {name!r} window ready in {ms(t):.0f} ms (hwnd {hwnd})")
time.sleep(1.0)

try:
    # --- snapshot speed: ours vs the naive per-element walk with the 'uiautomation' package
    times = []
    for _ in range(8):
        t = time.perf_counter()
        snap = uia.snapshot(hwnd)
        times.append(ms(t))
    print(f"[uia] cached snapshot: {len(snap.els)} elements ({snap.found} found, richness {snap.richness}): "
          f"median {st.median(times):.0f} ms, min {min(times):.0f} ms, max {max(times):.0f} ms")
    import uiautomation as auto

    ctl = auto.ControlFromHandle(hwnd)
    t = time.perf_counter()
    cnt = [0]

    def walk(c, d=0):
        cnt[0] += 1
        if d < 12:
            for ch in c.GetChildren():
                walk(ch, d + 1)

    walk(ctl)
    naive = ms(t)
    print(f"[uia] naive element-by-element walk: {cnt[0]} controls in {naive:.0f} ms  -> ours is {naive / st.median(times):.1f}x faster")

    # --- observation text the planner will read
    obs = observe.render(snap)
    print("[observe] first lines:\n  " + "\n  ".join(obs.splitlines()[:8]))

    # --- acting: press 1 2 + 3 0 = and read the display
    by_aid = {e.aid: e for e in snap.els if e.aid}
    disp = by_aid["CalculatorResults"]
    seq = ["num1Button", "num2Button", "plusButton", "num3Button", "num0Button", "equalButton"]
    lat = []
    t_all = time.perf_counter()
    for aid in seq:
        t = time.perf_counter()
        ok, how = uia.invoke(by_aid[aid])
        lat.append(ms(t))
        assert ok, (aid, how)
    total = ms(t_all)
    t = time.perf_counter()
    result = uia.live_name(disp)
    print(f"[act] 6 invokes in {total:.1f} ms total (per action median {st.median(lat):.1f} ms, max {max(lat):.1f}); display read in {ms(t):.1f} ms -> {result!r}")
    assert "42" in (result or ""), "wrong result"

    # --- repeat to get a stable per-action figure
    uia.invoke(by_aid["clearButton"])
    lat = []
    for _ in range(25):
        for aid in ("num7Button", "num8Button", "num9Button", "num4Button"):
            t = time.perf_counter()
            uia.invoke(by_aid[aid])
            lat.append(ms(t))
    lat.sort()
    print(f"[act] steady state over {len(lat)} invokes: median {st.median(lat):.1f} ms, p95 {lat[int(len(lat) * .95)]:.1f} ms")
finally:
    inputs.close_window(hwnd)
    for _ in range(40):
        time.sleep(0.1)
        if not apps.find_window(title_substr="Calculator"):
            break
    print("[cleanup] calculator closed:", not apps.find_window(title_substr="Calculator"))
