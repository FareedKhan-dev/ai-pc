"""Export a JianYing 5.9 project to out/video/<name>.mp4 (see src/ai_pc/video/jy_export.py for how).

  ai-pc jianying-export <draft name> [--start] [--trace-hang]

--start       start JianYing first if it is closed (without taking focus, behind other windows)
--trace-hang  debugging: print every thread's stack if the run is still going after 45 s

JianYing is driven with UI Automation and window messages only: the user's mouse and keyboard are never touched.
Kill switch: Ctrl+Alt+Q.
"""

import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):  # item names are often Chinese: never crash on the console's code page
        stream.reconfigure(encoding="utf-8", errors="replace")
    from ai_pc.video.jy_export import GUARD, export

    args = [a for a in argv if not a.startswith("--")]
    if "--trace-hang" in argv:
        import faulthandler

        faulthandler.dump_traceback_later(45, exit=True)
    r = export(args[0] if args else "agent_jy_test", log=lambda m: print(m, flush=True), start="--start" in argv)
    if r["ok"]:
        print(f"EXPORTED in {r['seconds']:.1f} s -> {r['path']}\n  {r['info']}")
    else:
        print(f"export stopped after {r['seconds']:.1f} s: {r['error']}")
        if r["login"] and len(r["used"]) == 1:
            print(f"  recorded: {r['used'][0]} needs a JianYing account to export")
    if GUARD.dismissed:
        print("pop-ups dismissed:", GUARD.dismissed)
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
