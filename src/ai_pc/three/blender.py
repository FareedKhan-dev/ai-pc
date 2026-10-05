"""Blender, run in the background from the project (tools/blender, the portable build checked against blender.org's
SHA-256 and signed by the Blender Foundation; its settings stay in its own 'portable' folder, never in AppData).
A scene script gets a JSON spec and writes a JSON result; its PROGRESS lines are passed on.

  r = run("house_scene.py", spec, folder, log=print)     -> the script's result (raises BlenderError with the reason)
"""

import json
import re
import subprocess
import threading
import time
from pathlib import Path

from ai_pc.core.config import ROOT

NO_WINDOW = 0x08000000
BL = Path(__file__).resolve().parent / "bl"


class BlenderError(RuntimeError):
    pass


def exe():
    found = sorted((ROOT / "tools" / "blender").glob("blender-*-windows-x64/blender.exe"))
    if not found:
        raise BlenderError("Blender is not installed in tools/blender")
    return found[-1]


def run(script, spec, folder, log=None, timeout=1800, name="job"):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    spec_path, out_path = folder / f"{name}_spec.json", folder / f"{name}_result.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    out_path.unlink(missing_ok=True)
    cmd = [str(exe()), "-b", "--factory-startup", "--python-exit-code", "1", "-P", str(BL / script), "--", str(spec_path), str(out_path)]
    p = subprocess.Popen(cmd, cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    lines = []
    dog = threading.Timer(timeout, p.kill)
    dog.start()
    t0, shown = time.time(), -1
    try:
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            lines.append(line)
            m = re.match(r"PROGRESS (\d+) ?(.*)", line)
            if m and log and time.time() - t0 > 8 and int(m.group(1)) - shown >= 20:
                shown = int(m.group(1))
                log(f"  3D {shown}% {m.group(2)}".rstrip())
        p.wait()
    finally:
        dog.cancel()
    if p.returncode or not out_path.exists():
        errs = [x for x in lines if re.search(r"Error|Traceback|error:|Exception", x)]
        tail = " | ".join((errs or lines)[-4:])[:400]
        raise BlenderError(f"Blender stopped ({p.returncode}): {tail or 'no reason given'}")
    res = json.loads(out_path.read_text(encoding="utf-8"))
    res["_seconds"] = round(time.time() - t0, 1)
    return res
