"""The README's command bar pictures: the real bar, on the hidden desktop, doing one request in each of seven programs.

  .venv\\Scripts\\python.exe scripts\\readme_demos.py [word powerpoint excel autocad blender design video]

Writes docs/assets/screens/demo-<name>.png; then `scripts/readme_assets.py gallery` puts each on a card. Nothing opens
on your screen: the bar runs on the hidden desktop with the integration tests' harmless key combo registered underneath,
and only the combo's name in the bar reads Ctrl+Alt+Space.

No live language model: a scripted stand-in answers the few model calls from scripts/readme_demos.json (the deck and
the workbook replay answers recorded from real runs; the letter's answer was written for the picture). The Office
visual check is itself a model call, so it is off here and every check in the pictures is one made by code. Slack is
the test suite's stand-in. The video demo needs media/mixkit_47518.mp4 (scripts/fetch_stock_media.py).
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from ai_pc.core.paths import MEDIA, ROOT

ANSWERS = json.loads((ROOT / "scripts" / "readme_demos.json").read_text(encoding="utf-8"))
SCREENS = ROOT / "docs" / "assets" / "screens"
# name -> (request, files selected in File Explorer, seconds to wait)
DEMOS = {
    "word": ("leave application to my principal for 3 days, fever, Fatima Noor class 9-B", [], 240),
    "powerpoint": ("a 10 slide presentation for homeowners on going solar", [], 300),
    "excel": ("marks sheet in Excel for 8 students with totals, grades and a class summary", [], 240),
    "autocad": ("a 10 marla house with 3 bedrooms", [], 120),
    "blender": ("a 3D intro for Khan Electronics in gold", [], 400),
    "design": ("an instagram post for Khan Motors 'Eid Sale' 20% off 1-15 June, shop now", [], 120),
    "video": ("make it under 5 MB for whatsapp", ["mixkit_47518.mp4"], 240),
}


class Rec:
    """No microphone in these pictures."""

    level = 0.0

    def start(self):
        return self

    def seconds(self):
        return 0.0

    def stop(self, path):
        return path

    def cancel(self):
        pass


class ScriptedModel:
    """Stands in for the language model: answers by the kind of request (its system prompt)."""

    def __init__(self):
        self.calls = []

    def _call(self, tier, messages):
        system = str(messages[0].get("content", ""))
        self.calls.append(system[:60])
        for marker, key in (("design an Excel workbook", "workbook"), ("presentation designer", "deck"), ("complete short document", "letter")):
            if marker in system:
                return SimpleNamespace(text=json.dumps(ANSWERS[key]), usage={}, total_ms=0.0, hedged=False, reasoning="")
        from ai_pc.llm.planner import PlannerError

        raise PlannerError("no scripted answer for this request")  # the router then decides by its rules alone

    def cost(self):
        return {}, 0.0


def child(out, names):
    sys.path.insert(0, str(ROOT / "tests" / "integration"))
    import test_bar
    from test_aipc import TH, slack_with_uploads

    from ai_pc.assistant import bar as B
    from ai_pc.assistant import shell as S
    from ai_pc.office import studio

    init = studio.DocStudio.__init__

    def no_look(self, planner=None, log=print, look=True, fix_rounds=2):
        init(self, planner, log, False, fix_rounds)

    studio.DocStudio.__init__ = no_look
    shown = B.Bar._hints

    def hints(self):
        if self.combo:
            self.combo = "Ctrl+Alt+Space"
        shown(self)

    B.Bar._hints = hints
    S.dpi_aware()
    tr, _ = slack_with_uploads()
    sel = {"files": []}
    res = {"done": [], "errors": []}
    bar = B.Bar(
        cfg={"hotkey": test_bar.COMBO, "fallbacks": [], "resume_hours": 0, "theme": os.environ.get("AIPC_TEST_THEME", "dark")},
        agent_kw={
            "chats_dir": out / "chats",
            "planner": ScriptedModel(),
            "options": {"chats_root": out / "lanes", "hub": {"transports": tr, "creds": TH.CREDS}},
        },
        shell_kw={
            "name": "AIPC_Shell_demos",
            "tray": False,
            "key_state": lambda vk: False,
            "front": lambda: {"hwnd": 1, "class": "CabinetWClass" if sel["files"] else "Progman", "title": "Videos", "pid": 0},
        },
        recorder=Rec,
        context=lambda fg: list(sel["files"]) if fg.get("class") == "CabinetWClass" else [],
        clipboard=lambda d: [],
        log=lambda *a: None,
    )

    def press():
        S.user32.PostMessageW(bar.shell.hwnd, S.WM_HOTKEY, 1, 0)

    def script():
        yield (lambda: bar.ready_info is not None, 60)
        for name in names:
            text, files, limit = DEMOS[name]
            folder = out / "media" / name
            folder.mkdir(parents=True, exist_ok=True)
            sel["files"] = []
            for f in files:
                shutil.copy(MEDIA / f, folder / f)
                sel["files"].append(str(folder / f))
            if not bar.visible:
                press()
                yield (lambda: bar.visible, 5)
            old = bar.agent.chat.state["id"] if bar.agent.chat else None
            bar.input.event_generate("<Control-n>")
            yield (lambda: bar.agent.chat is not None and bar.agent.chat.state["id"] != old, 15)
            if files:  # the files selected in File Explorer come along when the combo is pressed over it
                bar.input.event_generate("<Escape>")
                yield (lambda: not bar.visible, 5)
                press()
                yield (lambda: bar.visible and bar.context == sel["files"], 8)
            yield 0.3
            bar.input.focus_force()
            bar.input.insert("1.0", text)
            bar._changed()
            t0 = time.monotonic()
            bar.input.event_generate("<Return>")
            yield (lambda: bar.busy, 20)
            yield (lambda: not bar.busy, limit)
            yield 2.5  # the first page or the video's frame is drawn in the background
            test_bar.snap(bar.hwnd, out / f"{name}.png")
            res["done"].append({"name": name, "seconds": round(time.monotonic() - t0, 1)})

    gen = script()

    def step(value=None):
        try:
            cond = gen.send(value)
        except StopIteration:
            finish()
            return
        except Exception:  # noqa: BLE001
            import traceback

            res["errors"].append(traceback.format_exc())
            finish()
            return
        if isinstance(cond, (int, float)):
            end = time.monotonic() + cond
            fn, limit = (lambda: time.monotonic() >= end), cond + 5
        else:
            fn, limit = cond
        deadline = time.monotonic() + limit

        def poll():
            try:
                ok = bool(fn())
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                step(True)
            elif time.monotonic() > deadline:
                step(False)
            else:
                bar.root.after(60, poll)

        bar.root.after(10, poll)

    def finish():
        res["model_calls"] = getattr(bar.agent.planner, "calls", None)
        (out / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        bar.quit()

    bar.root.after(200, step)
    bar.run()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), sys.argv[3:])
        return
    from ai_pc.core import hidden_desktop

    names = sys.argv[1:] or list(DEMOS)
    out = ROOT / "out" / "readme_demos"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    env = dict(os.environ, AIPC_TEST_THEME="dark")
    rc, so, se, timed_out = hidden_desktop.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", str(out), *names], timeout=2400, cwd=ROOT, env=env
    )
    r = json.loads((out / "results.json").read_text(encoding="utf-8")) if (out / "results.json").is_file() else {}
    for d in r.get("done", []):
        shutil.copy(out / f"{d['name']}.png", SCREENS / f"demo-{d['name']}.png")
        print(f"docs/assets/screens/demo-{d['name']}.png  ({d['seconds']} s)")
    if rc or r.get("errors"):
        print("rc", rc, "timed out" if timed_out else "", (se or "")[-1500:], r.get("errors"))
        sys.exit(1)


if __name__ == "__main__":
    main()
