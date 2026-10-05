"""The AI PC command bar, tested without touching your screen, keyboard, microphone or clipboard: the bar itself runs on
the hidden desktop (its window, its global key combo, its conversation), driven by Windows messages and its own events;
a recorded voice note stands in for the microphone; Slack is a fake.

Checked: the key combo (parsing; registered with Windows; a press shows the bar; holding it records and sends a voice
note), the files selected in File Explorer coming along ('make it brighter' edits the selected photo), the reply with
the picture and its file, 'send it to slack' waiting for Yes and the Yes sending the edited photo, files dropped on the
bar, Esc, a second start showing the running bar, New chat, one copy running, the agent's rules for selected files, and
pictures of the bar (out/_tests/bar/ui/*.png) to look at.

  .venv\\Scripts\\python.exe tests\\integration\\test_bar.py
"""
import ctypes
import json
import shutil
import struct
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_pc.assistant import shell as S  # noqa: E402
from ai_pc.assistant.agent import Agent, split_reply  # noqa: E402

OUT = ROOT / "out" / "_tests" / "bar"
PHOTO_SRC = ROOT / "media" / "josh-berquist-_4sWbzH5fp8-unsplash.jpg"
COMBO = "ctrl+alt+shift+f24"  # a combo no keyboard has, so a test never takes one you use
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"\n     why: {str(detail)[:600]}"), flush=True)


def fresh(name):
    d = OUT / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------- pieces
def t_pieces():
    from ai_pc.assistant import mic
    from ai_pc.assistant.bar import palette, shown_text
    check("combo: 'ctrl+alt+space' is Ctrl+Alt with the space bar", S.parse_hotkey("ctrl+alt+space") == (0x3, 0x20, "Ctrl+Alt+Space"))
    check("combo: 'Win + Shift + A' and F-keys are understood", S.parse_hotkey("Win + Shift + A")[1:] == (ord("A"), "Shift+Win+A")
          and S.parse_hotkey(COMBO)[1] == 0x87)
    bad = []
    for t in ("space", "ctrl+alt", "ctrl+a+b", "ctrl+banana"):
        try:
            S.parse_hotkey(t)
            bad.append(t)
        except ValueError:
            pass
    check("combo: a combo with no modifier, no key, two keys or an unknown key is refused", not bad, bad)
    b = S.dropfiles([r"C:\a b\x.mp4", r"C:\y.png"])
    head = struct.unpack("<IiiII", b[:20])
    names = b[20:].decode("utf-16-le")
    check("copy: the clipboard bytes for files are Windows' file-list format", head == (20, 0, 0, 0, 1) and names.startswith("C:\\a b\\x.mp4\0C:\\y.png\0\0"),
          (head, names))
    parts = split_reply("[Photos] Brighter: v2.png\n[Slack, Teams] Ready to post v2.png to #team. Say 'yes'")
    check("reply: each program's part is shown under its own name", [p[0] for p in parts] == ["Photos", "Slack, Teams"] and parts[1][1].startswith("Ready"),
          parts)
    check("reply: a long path is shown as just the file name", shown_text(r"Edited: C:\Users\me\out\video\agent_x.mp4 (6 of 9 checks)") ==
          "Edited: agent_x.mp4 (6 of 9 checks)")
    dark, light = palette(True, "#0050a0"), palette(False, "#99ddff")
    from ai_pc.assistant.bar import lum
    check("look: the accent stays readable on a dark and on a light bar", lum(dark["accent"]) >= 0.42 and lum(light["accent"]) <= 0.45, (dark, light))
    import math
    tone = struct.pack("<1600h", *[int(9000 * math.sin(i / 8)) for i in range(1600)])
    check("microphone: silence reads 0, speech-like sound reads clearly", mic.level(b"\0" * 3200) == 0.0 and mic.level(tone) > 0.5, mic.level(tone))
    d = fresh("pieces")
    w = mic.write_wav(d / "t.wav", [tone, tone], 16000, 1)
    import wave
    with wave.open(str(w)) as f:
        ok = (f.getframerate(), f.getnchannels(), f.getnframes()) == (16000, 1, 3200)
    check("microphone: what is heard is saved as a 16 kHz WAV", ok)
    check("microphone: Windows' recording devices are counted without opening one", isinstance(mic.microphones(), int))
    cmd = S.launch_command(ROOT, executable=str(ROOT / ".venv" / "Scripts" / "python.exe"))
    check("start: the bar starts with pythonw (no window of its own) as 'ai-pc bar'", "pythonw.exe" in cmd and cmd.endswith("-m ai_pc bar"), cmd)


def t_shell():
    got, ev = [], threading.Event()

    def on(kind, d):
        got.append((kind, d))
        if kind == "hotkey_up" or kind == "show":
            ev.set()
    fake_fg = {"hwnd": 0, "class": "CabinetWClass", "title": "Pictures", "pid": 0}
    sh = S.Shell(on, {"bar": COMBO}, name="AIPC_Shell_unit", tray=False, key_state=lambda vk: False, front=lambda: fake_fg)
    sh.start()
    sh.ready.wait(5)
    check("combo: Windows takes the combo for the bar (RegisterHotKey, no keyboard hook)", sh.registered.get("bar") == "Ctrl+Alt+Shift+F24",
          (sh.registered, sh.failed))
    S.user32.PostMessageW(sh.hwnd, S.WM_HOTKEY, 1, 0)
    ev.wait(5)
    kinds = [k for k, _ in got]
    check("combo: a press is reported with the window in front, then its release", kinds[:2] == ["hotkey", "hotkey_up"]
          and got[0][1]["fg"]["class"] == "CabinetWClass", got)
    name = f"Local\\AIPC_Bar_test_{int(time.time())}"
    first = S.single_instance(name)
    second = S.single_instance(name)
    check("one copy: a second start knows the bar is already running", first is not None and second is None)
    S.kernel32.CloseHandle(first)
    ev.clear()
    got.clear()
    check("one copy: a second start asks the running bar to show itself", S.poke_running("AIPC_Shell_unit") and ev.wait(5) and got[0][0] == "show", got)
    sh.stop()
    sh.join(5)
    check("combo: given back to Windows when the bar quits", not sh.is_alive())


def t_agent():
    from test_aipc import slack_with_uploads  # noqa: F401 - the same fakes the chat tests use
    d = fresh("agent")
    photo, photo2 = d / "car.jpg", d / "bike.jpg"
    shutil.copy(PHOTO_SRC, photo)
    shutil.copy(PHOTO_SRC, photo2)
    events, done = [], threading.Event()

    def on(kind, data):
        events.append((kind, data))
        if kind in ("reply", "newchat"):
            done.set()
    ag = Agent(on, chats_dir=d / "chats", planner=None, options={"chats_root": d / "lanes"}, resume_hours=0, warm=False)
    ag.ready.wait(30)
    calls = []
    real = ag.chat.say
    ag.chat.say = lambda message="", files=(), voice=None: (calls.append((message, list(files))), real(message, files=files, voice=voice))[1]
    done.clear()
    ag.send("make it brighter", context=[str(photo)], where="File Explorer")
    done.wait(120)
    r = next((x for k, x in events if k == "reply"), {})
    kinds = [k for k, _ in events]
    check("agent: a selected photo is 'it': 'make it brighter' edits it", r.get("text", "").startswith("[Photos]") and "Brighter" in r.get("text", "")
          and len(r.get("files", [])) == 1, r)
    check("agent: the selected photo is learned, not forced on the request", calls and calls[-1][1] == [] and
          any(a["path"].lower() == str(photo).lower() and "File Explorer" in a.get("note", "") for a in ag.chat.arts.items), (calls, ag.chat.arts.items))
    check("agent: the bar hears which program works (live) before the reply", "lane" in kinds and kinds.index("lane") < kinds.index("reply")
          and next(x for k, x in events if k == "lane")["label"] == "Photos", kinds)
    events.clear()
    done.clear()
    ag.send("make these black and white", context=[str(photo), str(photo2)], where="File Explorer")
    done.wait(120)
    check("agent: several selected files go with 'these'", calls[-1][1] == [str(photo), str(photo2)], calls[-1])
    old = ag.chat.state["id"]
    done.clear()
    events.clear()
    ag.new_chat()
    done.wait(30)
    check("agent: New chat starts a new conversation (the old one stays saved)", ag.chat.state["id"] != old
          and (d / "chats" / old / "chat.json").is_file(), events)
    ag.stop()
    import os
    ag2 = Agent(lambda k, x: None, chats_dir=d / "chats", planner=None, options={"chats_root": d / "lanes"}, resume_hours=6, warm=False)
    ag2.ready.wait(30)
    same = ag2.chat.state["id"] == ag.chat.state["id"]
    ag2.stop()
    f = d / "chats" / ag.chat.state["id"] / "chat.json"
    t = time.time() - 7 * 3600
    for c in (d / "chats").glob("*/chat.json"):
        os.utime(c, (t, t))
    ag3 = Agent(lambda k, x: None, chats_dir=d / "chats", planner=None, options={"chats_root": d / "lanes"}, resume_hours=6, warm=False)
    ag3.ready.wait(30)
    check("agent: the bar carries on today's chat, and starts afresh after 6 hours", same and ag3.chat.state["id"] != ag.chat.state["id"] and f.is_file())
    ag3.stop()


# ---------------------------------------------------------------- the bar itself, on the hidden desktop
def snap(hwnd, path):
    """A picture of the bar's window (PrintWindow: the window draws itself into a picture; nothing on screen is read)."""
    import win32gui
    import win32ui
    from PIL import Image
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    img = Image.frombuffer("RGB", (w, h), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    img.save(path)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    return bool(ok) and img.convert("L").getextrema()[1] > 40


def hdrop(paths):
    """A real 'files dropped' handle, as File Explorer makes when you drop files on a window."""
    k = ctypes.WinDLL("kernel32")
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    data = S.dropfiles(paths)
    h = k.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
    ctypes.memmove(k.GlobalLock(h), data, len(data))
    k.GlobalUnlock(h)
    return h


def pill_texts(w):
    """The words on every chip inside a widget (the conversation's file chips, Yes / No ...)."""
    out = [w.text] if hasattr(w, "text") and hasattr(w, "enabled") else []
    for c in w.winfo_children():
        out += pill_texts(c)
    return out


def ui_child(out, wav, photo):
    """Runs on the hidden desktop: the real bar, driven step by step; writes what it saw to results.json."""
    out = Path(out)
    from test_aipc import TH, slack_with_uploads

    from ai_pc.assistant import bar as B
    S.dpi_aware()
    res = {"checks": [], "errors": [], "log": [], "timings": {}}
    tr, got = slack_with_uploads()
    held = {"until": 0.0}

    class FakeRec:
        level = 0.6

        def start(self):
            self.t0 = time.monotonic()
            return self

        def seconds(self):
            return time.monotonic() - self.t0

        def stop(self, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(wav, path)
            return path

        def cancel(self):
            pass
    front = {"fg": {"hwnd": 1, "class": "CabinetWClass", "title": "Pictures", "pid": 0}}
    import os
    bar = B.Bar(cfg={"hotkey": COMBO, "fallbacks": [], "resume_hours": 0, "theme": os.environ.get("AIPC_TEST_THEME", "auto")},
                agent_kw={"chats_dir": out / "chats", "planner": None,
                          "options": {"chats_root": out / "lanes", "hub": {"transports": tr, "creds": TH.CREDS}}},
                shell_kw={"name": "AIPC_Shell_uitest", "tray": False, "key_state": lambda vk: time.monotonic() < held["until"],
                          "front": lambda: front["fg"]},
                recorder=FakeRec, context=lambda fg: [str(photo)] if fg.get("class") == "CabinetWClass" else [], clipboard=lambda d: [],
                log=lambda *a: res["log"].append(" ".join(map(str, a))))

    def ck(name, ok, detail=""):
        res["checks"].append([name, bool(ok), str(detail)[:400]])

    def text():
        return bar.convo.get("1.0", "end")

    def press(hold=0.0):
        held["until"] = time.monotonic() + hold
        S.user32.PostMessageW(bar.shell.hwnd, S.WM_HOTKEY, 1, 0)

    def script():
        ok = yield (lambda: bar.ready_info is not None, 30)
        ck("bar: the chat is loaded in the background", ok)
        ck("bar: the combo is registered with Windows", bar.combo == "Ctrl+Alt+Shift+F24", bar.shell.failed)
        t0 = time.perf_counter()
        press()
        ok = yield (lambda: bar.visible and bar.root.winfo_ismapped(), 5)
        res["timings"]["combo_to_shown_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        res["timings"].update(bar.timings)
        ck("bar: pressing the combo shows the bar", ok)
        ok = yield (lambda: bar.context == [str(photo)] and bar.chips.winfo_manager(), 5)
        ck("bar: the photo selected in File Explorer comes along (a chip 'From File Explorer')", ok and bar.where == "File Explorer", (bar.context, bar.where))
        ck("bar: suggestions for a photo are offered", bar.sugg.winfo_manager() and getattr(bar, "_sugg_key", None) == "image")
        order = bar.card.pack_slaves()
        ck("bar: the files coming along are shown above the suggestions", order.index(bar.chips) < order.index(bar.sugg), order)
        yield 0.4
        res["snap_open"] = snap(bar.hwnd, out / "1_open.png")
        bar.input.focus_force()
        bar.input.insert("1.0", "make it brighter")
        bar._changed()
        bar.input.event_generate("<Return>")
        ok = yield (lambda: "Brighter" in text() and not bar.busy, 90)
        ck("bar: Enter sends; the reply comes back under the program's name", ok and "PHOTOS" in text(), text()[-600:])
        ck("bar: the edited picture and its file are shown", len(bar.imgs) >= 1 and "v" in text(), len(bar.imgs))
        ck("bar: the selected photo was used once (the next request does not carry it)", bar.context == [] and not bar.chips.winfo_manager())
        names = pill_texts(bar.convo)
        ck("bar: the edited photo is offered as car_edited.png (not the program's v1.png)", "car_edited.png" in names, names)
        yield 0.5
        res["snap_reply"] = snap(bar.hwnd, out / "2_reply.png")
        # hold the combo and talk
        press(hold=1.6)
        ok = yield (lambda: bar.rec is not None, 3)
        ck("bar: holding the combo starts listening", ok)
        yield 0.4
        res["snap_listen"] = snap(bar.hwnd, out / "3_listening.png")
        ok = yield (lambda: bar.rec is None and bar.busy, 5)
        ck("bar: letting go sends the voice note", ok)
        ok = yield (lambda: not bar.busy and "black" in text().lower(), 120)
        ck("bar: the voice note is heard and done ('make it black and white')", ok, text()[-500:])
        # outward: waits for Yes
        bar.input.insert("1.0", "send it to slack #general")
        bar.send()
        ok = yield (lambda: not bar.busy and bar.pending, 60)
        ck("bar: 'send it to slack' waits, showing Yes and No", ok and len(bar.rows[-1]) == 2, text()[-400:])
        yield 0.4
        res["snap_confirm"] = snap(bar.hwnd, out / "4_confirm.png")
        yes = bar.rows[-1][0]
        yes.event_generate("<Button-1>", x=8, y=8)
        ok = yield (lambda: not bar.busy and "Uploaded" in text(), 60)
        ck("bar: clicking Yes sends the edited photo", ok and got.get("data") is not None and got["data"] != Path(photo).read_bytes(), text()[-300:])
        ck("bar: the answered Yes / No can no longer be clicked", not yes.enabled)
        # files dropped on the bar
        drop = out / "dropped.jpg"
        shutil.copy(photo, drop)
        S.user32.PostMessageW(bar.hwnd, 0x0233, hdrop([str(drop)]), 0)
        ok = yield (lambda: bar.attach == [str(drop)], 5)
        ck("bar: a file dropped on the bar is attached", ok and getattr(bar, "drop_ok", False), bar.attach)
        bar._chips()
        yield 0.3
        res["snap_drop"] = snap(bar.hwnd, out / "5_dropped.png")
        bar.attach = []
        bar._chips()
        bar.input.event_generate("<Escape>")
        ok = yield (lambda: not bar.visible and bar.root.state() == "withdrawn", 3)
        ck("bar: Esc hides it", ok)
        S.poke_running("AIPC_Shell_uitest")
        ok = yield (lambda: bar.visible, 5)
        ck("bar: starting it again shows the bar that is running", ok)
        old = bar.agent.chat.state["id"]
        bar.input.event_generate("<Control-n>")
        ok = yield (lambda: bar.agent.chat is not None and bar.agent.chat.state["id"] != old and bar.convo.index("end-1c") == "1.0", 10)
        ck("bar: Ctrl+N starts a new chat", ok)
        press()
        yield 0.5
        ck("bar: pressing the combo while the bar is in front hides it (a tap)", not bar.visible or bar.focused() is False,
           (bar.visible, bar.focused()))

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
                bar.root.after(40, poll)
        bar.root.after(10, poll)

    def finish():
        res["errors"] += [line for line in res["log"] if "Traceback" in line or "Error" in line]  # the bar's log also says what it did
        (out / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        bar.quit()
    bar.root.after(200, step)
    bar.run()


def t_ui():
    from ai_pc.core import hidden_desktop
    from ai_pc.sound.tts import speak
    d = fresh("ui")
    photo = d / "car.jpg"
    shutil.copy(PHOTO_SRC, photo)
    wav = d / "voice.wav"
    speak("Make it black and white.", str(wav))
    rc, out, err, timed_out = hidden_desktop.run([sys.executable, str(Path(__file__).resolve()), "--ui-child", str(d), str(wav), str(photo)],
                                                 timeout=400, cwd=ROOT)
    rf = d / "results.json"
    if not rf.is_file():
        check("ui: the bar ran on the hidden desktop", False, f"rc={rc} timed_out={timed_out}\n{out[-1500:]}\n{err[-2500:]}")
        return
    res = json.loads(rf.read_text(encoding="utf-8"))
    for name, ok, detail in res["checks"]:
        check(name, ok, detail)
    check("ui: no errors inside the bar", not res["errors"], "\n".join(res["errors"])[-1500:])
    t = res["timings"]
    check(f"ui: the bar is up within 150 ms of the combo (took {t.get('combo_to_shown_ms')} ms)", t.get("combo_to_shown_ms", 9999) < 150, t)
    snaps = {k: v for k, v in res.items() if k.startswith("snap_")}
    check("ui: pictures of the bar were taken (out/_tests/bar/ui/*.png)", snaps and all(snaps.values()), snaps)


def _read(p):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _wait(fn, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.2)
    return bool(fn())


def t_launch():
    """ai-pc bar started the way the shortcut and Start with Windows start it (pythonw), on the hidden desktop, with its own
    settings (another combo, no tray icon): it starts again as python.exe with a console that has no window, takes its combo, and a
    second start asks it to show itself instead of starting another copy."""
    import os

    from ai_pc.core import hidden_desktop
    home = fresh("launch")
    (home / "bar.json").write_text(json.dumps({"hotkey": "ctrl+alt+shift+f23", "fallbacks": [], "tray": False, "notify": False,
                                               "name": "AIPCTEST", "resume_hours": 0}), encoding="utf-8")
    env = dict(os.environ, AIPC_BAR_HOME=str(home))
    pyw = str(Path(sys.executable).with_name("pythonw.exe"))
    log = home / "bar.log"
    first = hidden_desktop.start([pyw, "-m", "ai_pc", "bar", "--offline"], cwd=ROOT, env=env)
    try:
        ok = _wait(lambda: "combo Ctrl+Alt+Shift+F23" in _read(log), 90)
        text = _read(log)
        check("start: started like the shortcut (pythonw), the bar runs from python.exe with a console that has no window",
              "python.exe, console with no window" in text, text[-800:])
        check("start: it takes its combo and waits in the background", ok, text[-800:])
        hidden_desktop.run([pyw, "-m", "ai_pc", "bar", "--offline"], cwd=ROOT, env=env, timeout=60)
        ok = _wait(lambda: "asked by a second start" in _read(log), 30)
        check("start: a second start shows the running bar instead of starting another copy",
              ok and _read(log).count("start (offline") == 1, _read(log)[-800:])
    finally:
        first.stop()


def t_shortcut():
    import pythoncom
    from PIL import Image
    from win32com.shell import shell

    from ai_pc.assistant.bar import make_icon
    d = fresh("shortcut")
    icon = make_icon()
    with Image.open(icon) as im:
        sizes = set(im.info.get("sizes") or [])
    check("icon: the AI PC icon has the sizes the tray and Start use", {(16, 16), (32, 32), (256, 256)} <= sizes, sizes)
    lnk = d / "AI PC.lnk"
    made = S.make_shortcut(lnk, S.launch_command(ROOT), icon=icon, workdir=ROOT)
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(lnk))
    target, args = link.GetPath(shell.SLGP_RAWPATH)[0], link.GetArguments()
    check("shortcut: 'AI PC.lnk' starts the bar with pythonw (to pin to Start or the taskbar)", made and target.lower().endswith("pythonw.exe")
          and args.endswith("-m ai_pc bar"), (target, args))
    check("start with Windows: the sign-in command starts the bar quietly", S.launch_command(ROOT, startup=True).endswith("bar --startup"))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--ui-child":
        ui_child(*sys.argv[2:5])
        return
    t0 = time.time()
    for t in (t_pieces, t_shell, t_agent, t_shortcut, t_launch, t_ui):
        try:
            t()
        except Exception:  # noqa: BLE001 - one part failing does not hide the others
            import traceback
            check(f"{t.__name__}: ran without an error", False, traceback.format_exc()[-1500:])
    bad = [n for n, ok in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not bad else f'{len(bad)} FAILED'}  ({len(RESULTS) - len(bad)}/{len(RESULTS)}, {time.time() - t0:.0f} s)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
