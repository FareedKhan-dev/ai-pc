"""Export a JianYing 5.9 project to out/video/<name>.mp4 (see harness/jy_export.py for how).

  .venv\\Scripts\\python.exe jianying_export.py <draft name> [--start] [--trace-hang]

--start       start JianYing first if it is closed (without taking focus, behind other windows)
--trace-hang  debugging: print every thread's stack if the run is still going after 45 s

JianYing is driven with UI Automation and window messages only: the user's mouse and keyboard are never touched.
Kill switch: Ctrl+Alt+Q.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):  # item names are often Chinese: never crash on the console's code page
    _stream.reconfigure(encoding="utf-8", errors="replace")
from harness.jy_export import GUARD, export  # noqa: E402

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--trace-hang" in sys.argv:
        import faulthandler
        faulthandler.dump_traceback_later(45, exit=True)
    t0 = time.perf_counter()
    r = export(args[0] if args else "agent_jy_test", log=lambda m: print(m, flush=True), start="--start" in sys.argv)
    if r["ok"]:
        print(f"EXPORTED in {r['seconds']:.1f} s -> {r['path']}\n  {r['info']}")
    else:
        print(f"export stopped after {r['seconds']:.1f} s: {r['error']}")
        if r["login"] and len(r["used"]) == 1:
            print(f"  recorded: {r['used'][0]} needs a JianYing account to export")
    if GUARD.dismissed:
        print("pop-ups dismissed:", GUARD.dismissed)
