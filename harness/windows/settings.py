"""Windows settings by code, each read back after it is set and undoable (the old value is kept):

  dark_mode (apps and Windows)   transparency   file_extensions (shown)   hidden_files (shown)   taskbar_left (Windows 11)
  wallpaper (a picture)          power_plan (balanced | high performance | power saver)       default_printer
  startup apps: listed from the Run keys and the Startup folder; turned off / on the way Task Manager does it

  s = Settings()                       the real ones (HKEY_CURRENT_USER, the shell, powercfg, the print spooler)
  s = Settings(Fake())                 for tests: a registry branch of its own and pretend wallpaper / printer / power plan
  r = s.set("dark_mode", True)        -> {"ok", "what", "undo": {"do": "setting", "name": "dark_mode", "value": False}}
"""
import ctypes
import datetime as dt
import os
import re
import subprocess
import winreg
from pathlib import Path

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_RUN = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
APPROVED_FOLDER = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
PLANS = {"balanced": "381b4222-f694-41f0-9685-ff5bb260df2e", "high performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
         "power saver": "a1841308-3541-4fab-bc81-f71556f20b4a"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SettingError(Exception):
    pass


class Real:
    """The machine's own settings."""
    prefix = None
    test = False

    def reg_get(self, path, name, default=None):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._p(path)) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return default

    def reg_set(self, path, name, value, kind=winreg.REG_DWORD):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self._p(path), 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, kind, value)

    def reg_values(self, path, hive=winreg.HKEY_CURRENT_USER):
        out = {}
        try:
            with winreg.OpenKey(hive, self._p(path) if hive == winreg.HKEY_CURRENT_USER else path) as k:
                i = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    out[n] = v
                    i += 1
        except OSError:
            pass
        return out

    def _p(self, path):
        return f"{self.prefix}\\{path}" if self.prefix else path

    def changed(self, area):
        """Tell open windows a setting changed (as Settings does), so they redraw in the new look."""
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x1A, 0x0002
        res = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, area, SMTO_ABORTIFHUNG, 2000, ctypes.byref(res))

    def wallpaper_get(self):
        buf = ctypes.create_unicode_buffer(520)
        ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0)  # SPI_GETDESKWALLPAPER
        return buf.value

    def wallpaper_set(self, path):
        if not ctypes.windll.user32.SystemParametersInfoW(0x0014, 0, str(path), 0x01 | 0x02):  # SPI_SETDESKWALLPAPER, update ini + send change
            raise SettingError("Windows did not take that picture")

    def power_get(self):
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})\s+\((.+?)\)", out, re.I)
        return (m.group(1).lower(), m.group(2)) if m else (None, None)

    def power_list(self):
        out = subprocess.run(["powercfg", "/list"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
        return [(g.lower(), n) for g, n in re.findall(r"([0-9a-f]{8}-[0-9a-f-]{27})\s+\((.+?)\)", out, re.I)]

    def power_set(self, guid):
        r = subprocess.run(["powercfg", "/setactive", guid], capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode:
            raise SettingError(r.stderr.strip() or r.stdout.strip() or "powercfg refused")

    def printers(self):
        import win32print
        return [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]

    def printer_get(self):
        import win32print
        try:
            return win32print.GetDefaultPrinter()
        except Exception:  # noqa: BLE001
            return None

    def printer_set(self, name):
        import win32print
        win32print.SetDefaultPrinter(name)

    def startup_folder(self):
        return Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"


class Fake(Real):
    """For tests: the registry under HKCU\\Software\\AIPC_Test (nothing real changes), and a pretend wallpaper, printer
    list and power plan."""
    test = True

    def __init__(self, folder=None):
        self.prefix = r"Software\AIPC_Test"
        self._wall = r"C:\Windows\Web\Wallpaper\Windows\img0.jpg"
        self._power = PLANS["balanced"]
        self._printers = ["Microsoft Print to PDF", "HP LaserJet Office"]
        self._printer = "Microsoft Print to PDF"
        self._startup = Path(folder) if folder else Path(__file__).resolve().parents[2] / "out" / "_tests" / "win" / "startup"  # inside the project
        for path, name, val in ((PERSONALIZE, "AppsUseLightTheme", 0), (PERSONALIZE, "SystemUsesLightTheme", 0), (PERSONALIZE, "EnableTransparency", 1),
                                (ADVANCED, "HideFileExt", 1), (ADVANCED, "Hidden", 2), (ADVANCED, "TaskbarAl", 1)):
            if self.reg_get(path, name) is None:
                self.reg_set(path, name, val)
        if not self.reg_values(RUN):
            self.reg_set(RUN, "OneDrive", r'"C:\Program Files\Microsoft OneDrive\OneDrive.exe" /background', winreg.REG_SZ)
            self.reg_set(RUN, "Spotify", r"C:\Users\me\AppData\Roaming\Spotify\Spotify.exe /minimized", winreg.REG_SZ)
            self.reg_set(RUN, "Discord", r"C:\Users\me\AppData\Local\Discord\Update.exe --processStart Discord.exe", winreg.REG_SZ)

    def reg_values(self, path, hive=winreg.HKEY_CURRENT_USER):
        return super().reg_values(path) if hive == winreg.HKEY_CURRENT_USER else {}

    def changed(self, area):
        pass

    def wallpaper_get(self):
        return self._wall

    def wallpaper_set(self, path):
        self._wall = str(path)

    def power_get(self):
        return self._power, next((n.title() for n, g in PLANS.items() if g == self._power), "?")

    def power_list(self):
        return [(g, n.title()) for n, g in PLANS.items()]

    def power_set(self, guid):
        self._power = guid

    def printers(self):
        return list(self._printers)

    def printer_get(self):
        return self._printer

    def printer_set(self, name):
        self._printer = name

    def startup_folder(self):
        return self._startup

    @staticmethod
    def wipe():
        def rm(k, sub):
            try:
                with winreg.OpenKey(k, sub, 0, winreg.KEY_ALL_ACCESS) as h:
                    while True:
                        try:
                            child = winreg.EnumKey(h, 0)
                        except OSError:
                            break
                        rm(h, child)
                winreg.DeleteKey(k, sub)
            except OSError:
                pass
        rm(winreg.HKEY_CURRENT_USER, r"Software\AIPC_Test")


APP_LABELS = {"microsoftedgeautolaunch": "Microsoft Edge", "securityhealth": "Windows Security (its tray icon)", "rtkauduservice": "Realtek Audio",
              "teams": "Microsoft Teams", "com.squirrel.teams.teams": "Microsoft Teams (classic)", "onedrive": "OneDrive", "googledrivefs": "Google Drive",
              "epicgameslauncher": "Epic Games Launcher", "steam": "Steam", "discord": "Discord", "spotify": "Spotify", "skype": "Skype",
              "msedge": "Microsoft Edge", "igfxtray": "Intel Graphics", "igcctray": "Intel Graphics Command Center", "zoom": "Zoom", "dropbox": "Dropbox"}


def app_label(name):
    """A start-up entry's name said plainly: 'MicrosoftEdgeAutoLaunch_7570...' -> 'Microsoft Edge', 'EpicGamesLauncher'
    -> 'Epic Games Launcher'."""
    n = re.sub(r"_[0-9A-Fa-f]{12,}$", "", str(name)).strip()
    if n.lower() in APP_LABELS:
        return APP_LABELS[n.lower()]
    if " " not in n and re.search(r"[a-z][A-Z]", n):
        n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
    return n


TOGGLES = {  # name: (key, value names, value when on, value when off, the window message area, what it is)
    "dark_mode": (PERSONALIZE, ("AppsUseLightTheme", "SystemUsesLightTheme"), 0, 1, "ImmersiveColorSet", "dark mode"),
    "transparency": (PERSONALIZE, ("EnableTransparency",), 1, 0, "ImmersiveColorSet", "transparency effects"),
    "file_extensions": (ADVANCED, ("HideFileExt",), 0, 1, "ShellState", "file extensions shown in Explorer"),
    "hidden_files": (ADVANCED, ("Hidden",), 1, 2, "ShellState", "hidden files shown in Explorer"),
    "taskbar_left": (ADVANCED, ("TaskbarAl",), 0, 1, "TraySettings", "the taskbar on the left"),
}


class Settings:
    def __init__(self, backend=None):
        self.b = backend or Real()

    # ---------------------------------------------------------------- reading
    def get(self, name):
        if name in TOGGLES:
            key, vals, on, off, _, _ = TOGGLES[name]
            return self.b.reg_get(key, vals[0], off) == on
        if name == "wallpaper":
            return self.b.wallpaper_get()
        if name == "power_plan":
            return self.b.power_get()[1]
        if name == "default_printer":
            return self.b.printer_get()
        raise SettingError(f"no setting '{name}'")

    def startup(self):
        """Apps that start with Windows: [{"name", "label", "command", "where", "on"}] (on: not turned off in Task Manager's
        list; label: the name said plainly)."""
        out = self._startup_raw()
        for x in out:
            x["label"] = app_label(x["name"])
        return out

    def _startup_raw(self):
        out = []
        approved = self.b.reg_values(APPROVED_RUN)
        for n, cmd in self.b.reg_values(RUN).items():
            st = approved.get(n)
            out.append({"name": n, "command": str(cmd), "where": "run", "on": not (isinstance(st, (bytes, bytearray)) and st[:1] == b"\x03")})
        for n, cmd in self.b.reg_values(RUN, winreg.HKEY_LOCAL_MACHINE).items():
            out.append({"name": n, "command": str(cmd), "where": "machine", "on": True})
        folder = self.b.startup_folder()
        if folder and folder.exists():
            approved_f = self.b.reg_values(APPROVED_FOLDER)
            for f in folder.iterdir():
                if f.suffix.lower() in (".lnk", ".url", ".exe", ".bat"):
                    st = approved_f.get(f.name)
                    out.append({"name": f.stem, "command": str(f), "where": "folder", "file": f.name,
                                "on": not (isinstance(st, (bytes, bytearray)) and st[:1] == b"\x03")})
        return out

    # ---------------------------------------------------------------- changing (each read back; the old value for undo)
    def set(self, name, value):
        if name in TOGGLES:
            key, vals, on, off, area, what = TOGGLES[name]
            old = self.get(name)
            for v in vals:
                self.b.reg_set(key, v, on if value else off)
            self.b.changed(area)
            ok = self.get(name) == bool(value)
            return {"ok": ok, "what": f"{what}: {'on' if value else 'off'}" + ("" if ok else " (Windows did not keep it)"),
                    "undo": {"do": "setting", "name": name, "value": old}, "changed": old != bool(value)}
        if name == "wallpaper":
            p = Path(str(value))
            if not p.exists() or p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                raise SettingError(f"no picture at {p}")
            old = self.b.wallpaper_get()
            self.b.wallpaper_set(str(p.resolve()))
            got = self.b.wallpaper_get()
            ok = Path(got).name.lower() == p.name.lower() or "transcoded" in got.lower()
            return {"ok": ok, "what": f"wallpaper: {p.name}", "undo": {"do": "setting", "name": "wallpaper", "value": old}, "changed": True}
        if name == "power_plan":
            plans = self.b.power_list()
            want = str(value).lower()
            guid = PLANS.get(want) if PLANS.get(want) in [g for g, _ in plans] else next((g for g, n in plans if want in n.lower()), None)
            if not guid:
                raise SettingError(f"no power plan '{value}' here (there are: {', '.join(n for _, n in plans)})")
            old_g, old_n = self.b.power_get()
            self.b.power_set(guid)
            now_g, now_n = self.b.power_get()
            return {"ok": now_g == guid, "what": f"power plan: {now_n}", "undo": {"do": "setting", "name": "power_plan", "value": old_n}, "changed": old_g != guid}
        if name == "default_printer":
            names = self.b.printers()
            want = next((n for n in names if n.lower() == str(value).lower()), None) or next((n for n in names if str(value).lower() in n.lower()), None)
            if not want:
                raise SettingError(f"no printer '{value}' (there are: {', '.join(names) or 'none'})")
            old = self.b.printer_get()
            self.b.printer_set(want)
            return {"ok": self.b.printer_get() == want, "what": f"default printer: {want}", "undo": {"do": "setting", "name": "default_printer", "value": old},
                    "changed": old != want}
        raise SettingError(f"no setting '{name}'")

    def set_startup(self, app, on):
        """An app turned off (or on) at start-up the way Task Manager does it: the entry stays, Windows skips it."""
        items = self.startup()
        a = str(app).lower().strip()
        it = next((x for x in items if a in (x["name"].lower(), x["label"].lower())), None) or \
            next((x for x in items if a in x["name"].lower() or a in x["label"].lower()), None)
        if it is None:
            raise SettingError(f"'{app}' does not start with Windows (these do: {', '.join(x['label'] for x in items) or 'nothing'})")
        if it["where"] == "machine":
            raise SettingError(f"{it['name']} is set for every user of this PC; turning it off needs an administrator (Task Manager > Startup apps)")
        key, vname = (APPROVED_RUN, it["name"]) if it["where"] == "run" else (APPROVED_FOLDER, it["file"])
        ft = int((dt.datetime.now(dt.timezone.utc) - dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)).total_seconds() * 10 ** 7)
        data = (b"\x02" + b"\x00" * 11) if on else (b"\x03\x00\x00\x00" + ft.to_bytes(8, "little"))
        was = it["on"]
        self.b.reg_set(key, vname, data, winreg.REG_BINARY)
        now = next(x for x in self.startup() if x["name"] == it["name"])
        return {"ok": now["on"] == bool(on), "what": f"{it['label']} {'starts' if on else 'no longer starts'} with Windows",
                "undo": {"do": "startup", "name": it["name"], "value": was}, "changed": was != bool(on)}

    def apply(self, step):
        """A journal step: {"do": "setting", "name", "value"} or {"do": "startup", "name", "value"}."""
        if step["do"] == "startup":
            return self.set_startup(step["name"], step["value"])
        return self.set(step["name"], step["value"])
