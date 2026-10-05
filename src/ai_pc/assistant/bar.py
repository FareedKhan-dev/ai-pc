"""The AI PC command bar: press Ctrl+Alt+Space anywhere and say what you want (type it, or hold the combo and talk).

It is the one AI PC chat (the same conversation ai-pc, the web page and Telegram use) in a small window that appears
over whatever you are doing and goes away when you click elsewhere or press Esc. Files selected in the File Explorer
window in front (or the document open in Word, Excel or PowerPoint) come along as 'this', so "add a glow effect" with a
video selected just works. The work runs in the background: the bar shows which program is busy and what it is doing,
the files made (open, show in folder, copy to paste anywhere), and Yes / No when a program asks before sending anything.
A notification says when a long job finishes while the bar is hidden. The tray icon's menu has New chat, Start with
Windows (off until you turn it on) and Quit.

  ai-pc bar                 start it (nothing shows until you press the combo)
  ai-pc bar --shortcut      make 'AI PC.lnk' here, to pin to Start or the taskbar
  out/aipc/bar.json           the combo and other settings
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import font as tkfont

from ai_pc.assistant import shell as S
from ai_pc.assistant.agent import Agent, split_reply
from ai_pc.assistant.artifacts import kind_of
from ai_pc.assistant.lanes import PATHS
from ai_pc.core.config import ROOT

HOME = ROOT / "out" / "aipc"
CONFIG, ICON, LOG = HOME / "bar.json", HOME / "aipc.ico", HOME / "bar.log"
DEFAULTS = {
    "hotkey": "ctrl+alt+space",
    "fallbacks": ["ctrl+alt+a", "ctrl+alt+q"],
    "hold_to_talk": 0.35,
    "resume_hours": 6,
    "notify": True,
    "width": 700,
    "theme": "auto",
    "tray": True,
    "name": "AIPC",
}
CREATE_NO_WINDOW = 0x08000000
# Segoe Fluent Icons / Segoe MDL2 Assets
G = {
    "logo": "",
    "mic": "",
    "send": "",
    "attach": "",
    "close": "",
    "folder": "",
    "copy": "",
    "video": "",
    "image": "",
    "audio": "",
    "music": "",
    "document": "",
    "pdf": "",
    "file": "",
    "archive": "",
    "check": "",
    "pin": "",
    "pinned": "",
    "new": "",
    "warn": "",
    "folder2": "",
}
KIND_ICON = {
    "video": G["video"],
    "image": G["image"],
    "audio": G["audio"],
    "music": G["music"],
    "pdf": G["pdf"],
    "document": G["document"],
    "slides": G["document"],
    "sheet": G["document"],
    "archive": G["archive"],
    "folder": G["folder2"],
}
SUGGEST = {
    "video": ["add a glow effect", "add word by word captions", "make it ready for whatsapp", "send it to slack"],
    "image": ["remove the background", "make it brighter", "make a passport photo", "send it to slack"],
    "audio": ["clean up this recording", "convert it to mp3", "send it to slack"],
    "pdf": ["compress this pdf", "convert it to word", "send it to slack"],
    "document": ["make the title bigger", "convert it to pdf", "print it"],
    "slides": ["convert it to pdf", "print it", "send it to slack"],
    "sheet": ["make a chart from it", "convert it to pdf", "send it to slack"],
    None: ["what can you do?", "make an instagram post for our Eid sale", "write a 1 page letter to the bank", "clean up my downloads"],
}
ABS = re.compile(r"[A-Za-z]:\\[^\r\n\"'<>|*?]*?\.[A-Za-z0-9]{1,5}(?![\w.])")


# ---------------------------------------------------------------- look
def _rgb(h):
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def mix(a, b, t):
    return _hex([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def lum(h):
    r, g, b = (v / 255 for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def palette(dark, accent=None):
    if dark:
        p = {
            "bg": "#202020",
            "field": "#2c2c2c",
            "chip": "#333333",
            "chip_hi": "#3d3d3d",
            "line": "#3b3b3b",
            "text": "#f3f3f3",
            "muted": "#a8a8a8",
            "faint": "#6e6e6e",
            "danger": "#ff6b6b",
            "ok": "#6ccb5f",
        }
        acc = accent or "#4cc2ff"
        while lum(acc) < 0.42:
            acc = mix(acc, "#ffffff", 0.25)
    else:
        p = {
            "bg": "#f3f3f3",
            "field": "#ffffff",
            "chip": "#e6e6e6",
            "chip_hi": "#dadada",
            "line": "#d5d5d5",
            "text": "#1b1b1b",
            "muted": "#5c5c5c",
            "faint": "#9a9a9a",
            "danger": "#c42b1c",
            "ok": "#0f7b0f",
        }
        acc = accent or "#005fb8"
        while lum(acc) > 0.45:
            acc = mix(acc, "#000000", 0.2)
    p["accent"], p["accent_hi"] = acc, mix(acc, "#ffffff" if not dark else "#000000", 0.15)
    p["on_accent"] = "#000000" if lum(acc) > 0.5 else "#ffffff"
    p["ctx"], p["ctx_hi"] = mix(p["chip"], acc, 0.18), mix(p["chip_hi"], acc, 0.25)
    return p


def make_fonts(root):
    fams = set(tkfont.families(root))

    def pick(*names):
        return next((n for n in names if n in fams), "Segoe UI")

    text, disp = pick("Segoe UI Variable Text", "Segoe UI"), pick("Segoe UI Variable Display", "Segoe UI")
    semi = pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold")
    icons = pick("Segoe Fluent Icons", "Segoe MDL2 Assets")
    F = lambda fam, size, **kw: tkfont.Font(root=root, family=fam, size=size, **kw)  # noqa: E731
    return {
        "input": F(disp, 14),
        "body": F(text, 10),
        "small": F(text, 9),
        "badge": F(semi, 9),
        "who": F(semi, 9),
        "icon": F(icons, 12),
        "icon_s": F(icons, 10),
        "icon_xs": F(icons, 8),
        "icon_l": F(icons, 15),
    }


def elide(text, f, maxpx):
    if not text or f.measure(text) <= maxpx:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if f.measure(text[:mid] + "…") <= maxpx:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


def shown_text(text):
    """A reply as shown: file paths become just their names (the files are right below it)."""
    t = ABS.sub(lambda m: Path(m.group(0)).name, text or "")
    return PATHS.sub(lambda m: Path(m.group(0)).name, t)


def first_page_jpg(pdf, out, width=640):
    """Page 1 of a PDF as a JPEG about `width` pixels wide: the picture for a document, deck or drawing result."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        page = doc[0]
        im = page.render(scale=width / page.get_width()).to_pil().convert("RGB")
    finally:
        doc.close()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=88)
    return out


def spark_image(size, color, bg):
    """The AI PC spark (the tray icon's shape), drawn smooth at any size."""
    from PIL import Image, ImageDraw, ImageTk

    n = size * 4
    im = Image.new("RGB", (n, n), bg)
    c, R, r = n / 2, n * 0.46, n * 0.11
    ImageDraw.Draw(im).polygon(
        [(c, c - R), (c + r, c - r), (c + R, c), (c + r, c + r), (c, c + R), (c - r, c + r), (c - R, c), (c - r, c - r)], fill=color
    )
    return ImageTk.PhotoImage(im.resize((size, size), Image.LANCZOS))


class Shapes:
    """Smooth rounded rectangles as images (Tk draws jagged corners itself)."""

    def __init__(self):
        self.cache = {}

    def rect(self, w, h, r, fill, bg, outline=None):
        key = (w, h, r, fill, bg, outline)
        img = self.cache.get(key)
        if img is None:
            from PIL import Image, ImageDraw, ImageTk

            k = 4
            im = Image.new("RGB", (max(1, w) * k, max(1, h) * k), bg)
            ImageDraw.Draw(im).rounded_rectangle(
                (0, 0, max(1, w) * k - 1, max(1, h) * k - 1), radius=max(0, r * k), fill=fill, outline=outline, width=k if outline else 0
            )
            if len(self.cache) > 400:
                self.cache.clear()
            img = self.cache[key] = ImageTk.PhotoImage(im.resize((max(1, w), max(1, h)), Image.LANCZOS))
        return img


class Pill(tk.Canvas):
    """A rounded chip or button: [icon] text [x]."""

    def __init__(self, master, bar, text="", icon=None, style="chip", command=None, on_close=None, maxw=250, h=28, bg=None):
        P, s = bar.P, bar.s
        bg = bg or P["bg"]
        self.fill_n, self.fill_h, fg = {
            "chip": (P["chip"], P["chip_hi"], P["text"]),
            "context": (P["ctx"], P["ctx_hi"], P["text"]),
            "accent": (P["accent"], P["accent_hi"], P["on_accent"]),
            "outline": (bg, P["chip"], P["text"]),
            "ghost": (bg, P["chip"], P["muted"]),
        }[style]
        self.outline = P["line"] if style in ("outline", "ghost") else None
        f, fi, fx = bar.f["body"], bar.f["icon_s"], bar.f["icon_xs"]
        H, pad, gap = round(h * s), round(11 * s), round(6 * s)
        text = elide(text, f, round(maxw * s))
        tw, iw, cw = (f.measure(text) if text else 0), (fi.measure(icon) if icon else 0), (fx.measure(G["close"]) if on_close else 0)
        W = pad + ((iw + (gap if text else 0)) if icon else 0) + tw + ((gap + cw) if on_close else 0) + pad
        super().__init__(master, width=W, height=H, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.bar, self.command, self.on_close, self.enabled, self.W, self.H, self.bgc, self.text = bar, command, on_close, True, W, H, bg, text
        self.bg_id = self.create_image(0, 0, anchor="nw", image=bar.shapes.rect(W, H, H // 2, self.fill_n, bg, self.outline))
        x, self.items = pad, []
        if icon:
            self.items.append(self.create_text(x, H // 2, text=icon, font=fi, fill=fg, anchor="w"))
            x += iw + (gap if text else 0)
        if text:
            self.items.append(self.create_text(x, H // 2, text=text, font=f, fill=fg, anchor="w"))
            x += tw
        self.close_x = None
        if on_close:
            self.close_x = x + gap // 2
            self.create_text(x + gap, H // 2, text=G["close"], font=fx, fill=P["muted"], anchor="w")
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<Button-1>", self._click)
        self.bind("<MouseWheel>", bar.wheel)

    def _hover(self, on):
        if self.enabled:
            self.itemconfigure(
                self.bg_id, image=self.bar.shapes.rect(self.W, self.H, self.H // 2, self.fill_h if on else self.fill_n, self.bgc, self.outline)
            )

    def _click(self, e):
        if not self.enabled:
            return
        if self.on_close and self.close_x is not None and e.x >= self.close_x:
            self.on_close()
        elif self.command:
            self.command()

    def disable(self):
        self.enabled = False
        self.configure(cursor="arrow")
        for i in self.items:
            self.itemconfigure(i, fill=self.bar.P["faint"])
        self.itemconfigure(self.bg_id, image=self.bar.shapes.rect(self.W, self.H, self.H // 2, self.bgc, self.bgc, self.bar.P["line"]))


class IconButton(tk.Canvas):
    def __init__(self, master, bar, glyph, command, size=34, bg=None, tip="", font="icon"):
        S_ = round(size * bar.s)
        super().__init__(master, width=S_, height=S_, bg=bg or bar.P["bg"], highlightthickness=0, bd=0, cursor="hand2")
        self.bar, self.command, self.S, self.bgc, self.tip, self.style, self.hover, self.glow = (
            bar,
            command,
            S_,
            bg or bar.P["bg"],
            tip,
            "ghost",
            False,
            0.0,
        )
        self.bg_id = self.create_image(0, 0, anchor="nw")
        self.g_id = self.create_text(S_ // 2, S_ // 2, text=glyph, font=bar.f[font])
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self.paint()

    def _hov(self, on):
        self.hover = on
        self.bar.tip(self.tip if on else "")
        self.paint()

    def set(self, glyph=None, style=None, glow=None):
        if glyph is not None:
            self.itemconfigure(self.g_id, text=glyph)
        if style is not None:
            self.style = style
        if glow is not None:
            self.glow = glow
        self.paint()

    def paint(self):
        P = self.bar.P
        fill, fg = {
            "ghost": (P["chip"] if self.hover else self.bgc, P["text"] if self.hover else P["muted"]),
            "accent": (P["accent_hi"] if self.hover else P["accent"], P["on_accent"]),
            "danger": (mix(P["danger"], "#ffffff", 0.45 * self.glow), "#ffffff"),
            "off": (self.bgc, P["faint"]),
        }[self.style]
        self.itemconfigure(self.bg_id, image=self.bar.shapes.rect(self.S, self.S, self.S // 2, fill, self.bgc))
        self.itemconfigure(self.g_id, fill=fg)


class ThinScroll(tk.Canvas):
    def __init__(self, master, bar, target):
        self.w = max(6, round(8 * bar.s))
        super().__init__(master, width=self.w, bg=bar.P["bg"], highlightthickness=0, bd=0)
        self.bar, self.target, self.lo, self.hi = bar, target, 0.0, 1.0
        self.thumb = self.create_rectangle(0, 0, 0, 0, fill=bar.P["faint"], width=0)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<MouseWheel>", bar.wheel)

    def set(self, lo, hi):
        self.lo, self.hi = float(lo), float(hi)
        self._draw()

    def _draw(self):
        h = self.winfo_height()
        if self.hi - self.lo >= 0.999 or h < 10:
            self.coords(self.thumb, 0, 0, 0, 0)
            return
        y0, y1 = self.lo * h, max(self.lo * h + 24, self.hi * h)
        x0 = self.w - max(3, round(4 * self.bar.s))
        self.coords(self.thumb, x0, y0 + 2, self.w - 1, y1 - 2)

    def _press(self, e):
        self._y, self._lo = e.y, self.lo

    def _drag(self, e):
        self.target.yview_moveto(self._lo + (e.y - self._y) / max(1, self.winfo_height()))


# ---------------------------------------------------------------- the bar
class Bar:
    def __init__(self, cfg=None, agent_kw=None, shell_kw=None, recorder=None, context=None, clipboard=None, log=None):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.logf = log or (lambda *a: None)
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("AI PC")
        self.root.overrideredirect(True)
        self.root.attributes("-toolwindow", True)
        self.root.attributes("-topmost", True)
        self.root.report_callback_exception = self._tk_error
        th = S.theme()
        self.dark = th["dark"] if self.cfg.get("theme", "auto") == "auto" else self.cfg["theme"] == "dark"
        self.P = palette(self.dark, th["accent"])
        self.s = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.f, self.shapes = make_fonts(self.root), Shapes()
        self.attach, self.context, self.where = [], [], ""
        self.sent, self.hpos = [], None
        self.busy, self.waiting, self.job_t0, self.lane, self.note, self.job_id = False, 0, None, "", "", None
        self.pinned = self.visible = self.styled = self.dialog = False
        self.rec, self.rec_how, self.press, self.swallow_until = None, None, None, 0.0
        self.show_n, self.shown_at, self.had_focus, self.hwnd = 0, 0.0, False, 0
        self.voice_tags, self.rows, self.imgs, self.pending, self.ready_info = {}, [], [], False, None
        self.x = self.y = 0
        self.maxh = 600
        self.timings = {}
        self.recorder_factory = recorder
        self.context_fn = context or S.context_files
        self.clipboard_fn = clipboard or S.clipboard_files_or_image
        self._build()
        self.agent = Agent(events=lambda k, d: self.q.put(("agent", k, d)), resume_hours=self.cfg["resume_hours"], **(agent_kw or {}))
        skw = {"name": "AIPC_Shell", "tray": True, "icon": ICON if ICON.is_file() else None, "menu": self._menu, "fallbacks": self.cfg["fallbacks"]}
        skw.update(shell_kw or {})
        self.shell = S.Shell(lambda k, d: self.q.put(("shell", k, d)), {"bar": self.cfg["hotkey"]}, **skw)
        self.shell.start()
        self.shell.ready.wait(5)
        self.combo = self.shell.registered.get("bar", "")
        self._hints()
        self.root.after(16, self._tick)

    # ---------------------------------------------------------------- building
    def _build(self):
        P, s, r = self.P, self.s, self.root
        self.W = round(self.cfg["width"] * s)
        pad = round(14 * s)
        self.inner = self.W - 2 * pad
        r.configure(bg=P["bg"])
        self.card = tk.Frame(r, bg=P["bg"], padx=pad, pady=pad)
        self.card.pack(fill="both", expand=True)
        # the box to type in
        self.line = self.f["input"].metrics("linespace")
        self.fh = round(52 * s)
        self.field = tk.Canvas(self.card, width=self.inner, height=self.fh, bg=P["bg"], highlightthickness=0, bd=0)
        self.field.pack(fill="x")
        self.field_bg = self.field.create_image(0, 0, anchor="nw")
        self.spark = spark_image(round(20 * s), P["accent"], P["field"])
        self.logo = self.field.create_image(round(24 * s), self.fh // 2, image=self.spark)
        self.input = tk.Text(
            self.field,
            height=1,
            wrap="word",
            bd=0,
            highlightthickness=0,
            bg=P["field"],
            fg=P["text"],
            insertbackground=P["text"],
            insertwidth=max(1, round(1.5 * s)),
            font=self.f["input"],
            undo=True,
            padx=0,
            pady=0,
            selectbackground=P["accent"],
            selectforeground=P["on_accent"],
            relief="flat",
        )
        self.tx = round(48 * s)
        self.btn_w = round(3 * 36 * s + 8 * s)
        self.input_win = self.field.create_window(
            self.tx, self.fh // 2, window=self.input, anchor="w", width=self.inner - self.tx - self.btn_w, height=self.line
        )
        self.ph = tk.Label(self.field, text="", bg=P["field"], fg=P["faint"], font=self.f["input"], anchor="w", cursor="xterm")
        self.ph_win = self.field.create_window(self.tx + round(3 * s), self.fh // 2, window=self.ph, anchor="w")
        self.ph.bind("<Button-1>", lambda e: self.input.focus_set())
        self.field.bind("<Button-1>", lambda e: self.input.focus_set())
        self.b_attach = IconButton(self.field, self, G["attach"], self.pick_files, bg=P["field"], tip="Attach files (Ctrl+O), or drop them here")
        self.b_mic = IconButton(self.field, self, G["mic"], self.mic_click, bg=P["field"], tip="Talk (Ctrl+M), or hold the combo")
        self.b_send = IconButton(self.field, self, G["send"], self.send, bg=P["field"], tip="Send (Enter)")
        self.btn_ids = [self.field.create_window(0, 0, window=b, anchor="e") for b in (self.b_attach, self.b_mic, self.b_send)]
        # a thin line that moves while a program works
        self.bar_h = max(2, round(2 * s))
        self.prog = tk.Canvas(self.card, width=self.inner, height=self.bar_h, bg=P["bg"], highlightthickness=0, bd=0)
        self.prog.pack(fill="x", pady=(round(4 * s), 0))
        self.prog_seg = self.prog.create_rectangle(0, 0, 0, 0, fill=P["accent"], width=0)
        # files coming along
        self.chips = tk.Frame(self.card, bg=P["bg"])
        self.sugg = tk.Frame(self.card, bg=P["bg"])
        # the conversation
        self.convo_box = tk.Frame(self.card, bg=P["bg"], height=1)
        self.convo_box.pack_propagate(False)
        self.convo = tk.Text(
            self.convo_box,
            wrap="word",
            bd=0,
            highlightthickness=0,
            bg=P["bg"],
            fg=P["text"],
            font=self.f["body"],
            padx=round(2 * s),
            pady=round(4 * s),
            cursor="arrow",
            relief="flat",
            selectbackground=P["accent"],
            selectforeground=P["on_accent"],
            spacing1=round(1 * s),
            spacing3=round(1 * s),
        )
        self.scroll = ThinScroll(self.convo_box, self, self.convo)
        self.convo.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.convo.pack(side="left", fill="both", expand=True)
        self.convo.bind("<MouseWheel>", self.wheel)
        self.convo.bind("<Key>", self._convo_key)  # read only (copy works); typing there goes to the box
        T = self.convo
        T.tag_configure("who", font=self.f["who"], foreground=P["muted"], spacing1=round(12 * s))
        T.tag_configure("time", font=self.f["small"], foreground=P["faint"])
        T.tag_configure("you", font=self.f["body"], foreground=P["text"], spacing3=round(2 * s))
        T.tag_configure("badge", font=self.f["badge"], foreground=P["accent"], spacing1=round(8 * s))
        T.tag_configure("ai", font=self.f["body"], foreground=P["text"], spacing1=round(2 * s), spacing3=round(2 * s), lmargin1=0, lmargin2=0)
        T.tag_configure("err", font=self.f["body"], foreground=P["danger"])
        T.tag_configure("meta", font=self.f["small"], foreground=P["faint"], spacing1=round(2 * s))
        T.tag_configure("icon", font=self.f["icon_s"], foreground=P["accent"])
        T.tag_configure("icon_m", font=self.f["icon_xs"], foreground=P["muted"])
        T.tag_configure("muted", font=self.f["small"], foreground=P["muted"])
        T.tag_configure("heard", font=self.f["body"], foreground=P["muted"])
        T.configure(state="disabled")
        self.sep = tk.Frame(self.card, bg=P["line"], height=1)
        # the line at the bottom
        self.foot = tk.Frame(self.card, bg=P["bg"])
        self.foot.pack(fill="x", pady=(round(8 * s), 0))
        self.status = tk.Label(self.foot, text="", bg=P["bg"], fg=P["muted"], font=self.f["small"], anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.b_new = IconButton(self.foot, self, G["new"], self.new_chat, size=26, tip="New chat (Ctrl+N)", font="icon_s")
        self.b_pin = IconButton(self.foot, self, G["pin"], self.toggle_pin, size=26, tip="Keep the bar open while you work elsewhere", font="icon_s")
        self.b_new.pack(side="right")
        self.b_pin.pack(side="right", padx=(round(4 * s), round(2 * s)))
        self.hint = tk.Label(self.foot, text="", bg=P["bg"], fg=P["faint"], font=self.f["small"], anchor="e")
        self.hint.pack(side="right", padx=(0, round(8 * s)))
        for w in (self.foot, self.status, self.hint):  # drag the bar by its bottom line
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        # keys
        i = self.input
        i.bind("<Return>", lambda e: (self.send(), "break")[1])
        i.bind("<Shift-Return>", lambda e: None)
        i.bind("<Up>", self._hist_up)
        i.bind("<Down>", self._hist_down)
        i.bind("<BackSpace>", self._backspace)
        i.bind("<Control-v>", self._paste)
        i.bind("<Key>", self._key, add="+")
        i.bind("<KeyRelease>", lambda e: self._changed())
        keys = (
            ("<Escape>", lambda e: self._escape()),
            ("<Control-n>", lambda e: self.new_chat()),
            ("<Control-o>", lambda e: self.pick_files()),
            ("<Control-m>", lambda e: self.mic_click()),
            ("<Alt-y>", lambda e: self.answer("yes")),
            ("<Alt-n>", lambda e: self.answer("no")),
        )
        for w in (self.input, self.convo, r):
            for k, fn in keys:
                w.bind(k, lambda e, fn=fn: (fn(e), "break")[1])
        self._layout_field(1)
        self._placeholder()
        self._suggest()

    def _convo_key(self, e):
        if e.state & 0x4:  # Ctrl+C / Ctrl+A on the conversation
            return None if e.keysym.lower() in ("c", "a") else "break"
        if e.keysym in ("Prior", "Next", "Up", "Down", "Home", "End"):
            return None
        if e.char and e.char.isprintable():
            self.input.focus_set()
            self.input.insert("insert", e.char)
            self._changed()
        return "break"

    def wheel(self, e):
        self.convo.yview_scroll(int(-e.delta / 120), "units")
        return "break"

    def tip(self, text):
        self.hint.configure(text=text or self._hint_text)

    def _hints(self):
        combo = self.combo or "the tray icon"
        self._hint_text = "Enter send · Esc hide · Ctrl+N new chat"
        self.hint.configure(text=self._hint_text)
        self._ph_text = f"Ask your PC to do anything…  (hold {combo} to talk)" if self.combo else "Ask your PC to do anything…"
        self._placeholder()
        self._status_idle()

    # ---------------------------------------------------------------- the box to type in
    def _layout_field(self, lines):
        s, P = self.s, self.P
        th = self.line * lines
        self.fh = max(round(52 * s), th + round(26 * s))
        self.field.configure(height=self.fh)
        self.field.itemconfigure(self.field_bg, image=self.shapes.rect(self.inner, self.fh, round(12 * s), P["field"], P["bg"], P["line"]))
        top = (self.fh - th) // 2 if lines == 1 else round(13 * s)
        self.field.coords(self.input_win, self.tx, top)
        self.field.itemconfigure(self.input_win, anchor="nw", height=th)
        self.field.coords(self.ph_win, self.tx + round(3 * s), self.fh // 2 if lines == 1 else top + self.line // 2)
        cy = self.fh // 2 if lines == 1 else self.fh - round(26 * s)
        self.field.coords(self.logo, round(24 * s), self.fh // 2 if lines == 1 else round(26 * s))
        x = self.inner - round(8 * s)
        for wid, b in zip(reversed(self.btn_ids), (self.b_send, self.b_mic, self.b_attach)):
            self.field.coords(wid, x, cy)
            x -= b.S + round(2 * s)
        self._lines = lines

    def _changed(self):
        t = self.input.get("1.0", "end-1c")
        try:
            n = self.input.count("1.0", "end", "displaylines")
            n = (n[0] if isinstance(n, tuple) else n) or 1
        except tk.TclError:
            n = t.count("\n") + 1
        n = max(1, min(5, n))
        if n != getattr(self, "_lines", 1):
            self._layout_field(n)
            self._fit()
        self._placeholder()
        self.b_send.set(style="accent" if (t.strip() or self.attach) else "ghost")
        self._suggest()

    def _placeholder(self):
        empty = not self.input.get("1.0", "end-1c")
        text = "Listening… let go to send  (Esc cancels)" if self.rec else getattr(self, "_ph_text", "")
        self.ph.configure(text=text, fg=self.P["danger"] if self.rec else self.P["faint"])
        self.field.itemconfigure(self.ph_win, state="normal" if empty else "hidden")

    def _key(self, e):
        if self.press or time.monotonic() < self.swallow_until:
            return "break"  # the combo's own key held down must not type spaces
        return None

    def _hist_up(self, e):
        if not self.sent or "\n" in self.input.get("1.0", "end-1c"):
            return None
        self.hpos = len(self.sent) - 1 if self.hpos is None else max(0, self.hpos - 1)
        self._set_input(self.sent[self.hpos])
        return "break"

    def _hist_down(self, e):
        if self.hpos is None:
            return None
        self.hpos += 1
        if self.hpos >= len(self.sent):
            self.hpos = None
            self._set_input("")
        else:
            self._set_input(self.sent[self.hpos])
        return "break"

    def _set_input(self, text):
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self.input.mark_set("insert", "end")
        self._changed()

    def _backspace(self, e):
        if self.input.get("1.0", "end-1c") == "" and (self.attach or self.context):
            (self.attach or self.context).pop()
            self._chips()
            return "break"
        return None

    def _paste(self, e):
        folder = Path(self.agent.chat.folder) / "pasted" if self.agent.chat is not None else HOME / "pasted"
        files = self.clipboard_fn(folder)
        if files:
            self.add_files(files)
            return "break"
        return None  # plain text: the box pastes it

    def add_files(self, paths):
        for p in paths:
            if p not in self.attach:
                self.attach.append(str(p))
        self._chips()
        self._changed()

    def pick_files(self):
        from tkinter import filedialog

        self.dialog = True
        try:
            got = filedialog.askopenfilenames(parent=self.root, title="Files for AI PC")
        finally:
            self.dialog = False
        if got:
            self.add_files([str(Path(p)) for p in got])
        self.input.focus_force()

    # ---------------------------------------------------------------- chips and suggestions
    def _chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        s = self.s
        items = [(p, True) for p in self.context] + [(p, False) for p in self.attach]
        if not items:
            self.chips.pack_forget()
        else:
            if self.context:
                tk.Label(
                    self.chips, text=f"From {self.where}:" if self.where else "Using:", bg=self.P["bg"], fg=self.P["muted"], font=self.f["small"]
                ).pack(side="left", padx=(round(4 * s), round(6 * s)))
            shown = 0
            for p, ctx in items:
                if shown == 4:
                    tk.Label(self.chips, text=f"+{len(items) - 4} more", bg=self.P["bg"], fg=self.P["muted"], font=self.f["small"]).pack(side="left")
                    break
                lst = self.context if ctx else self.attach
                Pill(
                    self.chips,
                    self,
                    Path(p).name,
                    icon=KIND_ICON.get(kind_of(p), G["file"]),
                    style="context" if ctx else "chip",
                    maxw=170,
                    on_close=lambda p=p, lst=lst: (lst.remove(p), self._chips(), self._changed()),
                ).pack(side="left", padx=(0, round(6 * s)))
                shown += 1
            if not self.chips.winfo_manager():
                self.chips.pack(fill="x", pady=(round(8 * s), 0), after=self.prog)
        self._suggest()
        self._fit()

    def _suggest(self):
        want = not self.input.get("1.0", "end-1c").strip() and not self.pending and not self.rec
        kinds = [kind_of(p) for p in self.context + self.attach]
        key = next((k for k in kinds if k in SUGGEST), None)
        if not want or (key is None and self.convo.index("end-1c") != "1.0"):
            if self.sugg.winfo_manager():
                self.sugg.pack_forget()
                self._fit()
            return
        if getattr(self, "_sugg_key", "x") != key or not self.sugg.winfo_children():
            for w in self.sugg.winfo_children():
                w.destroy()
            for text in SUGGEST[key]:
                Pill(self.sugg, self, text, style="outline", h=26, command=lambda t=text: (self._set_input(t), self.input.focus_set())).pack(
                    side="left", padx=(0, round(6 * self.s))
                )
            self._sugg_key = key
        if not self.sugg.winfo_manager():
            self.sugg.pack(fill="x", pady=(round(8 * self.s), 0), after=self.chips if self.chips.winfo_manager() else self.prog)
            self._fit()

    # ---------------------------------------------------------------- showing and hiding
    def _toplevel(self):
        return int(S.user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id())

    def focused(self):
        return self.visible and self.hwnd and int(S.user32.GetForegroundWindow() or 0) == self.hwnd

    def show(self, fg=None):
        t0 = time.perf_counter()
        self.show_n += 1
        if fg and fg.get("hwnd") and not S.is_ours(fg["hwnd"]):
            self.context, self.where = [], ""
            self._chips()
            n = self.show_n
            threading.Thread(target=lambda: self.q.put(("ctx", n, self.context_fn(fg), S.where_from(fg))), daemon=True, name="aipc-ctx").start()
        if not self.visible:
            left, top, right, bottom = S.work_area(fg["hwnd"] if fg and fg.get("hwnd") else None)
            self.x, self.y = left + ((right - left) - self.W) // 2, top + round((bottom - top) * 0.16)
            self.maxh = round((bottom - top) * 0.78)
            self.root.geometry(f"{self.W}x{max(10, self.card.winfo_reqheight())}+{self.x}+{self.y}")
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.visible, self.shown_at, self.had_focus = True, time.monotonic(), False
            self.root.update_idletasks()
            self.hwnd = self._toplevel()
            if not self.styled:
                S.style_window(self.hwnd, self.dark, self.P["line"])
                self._enable_drop()
                self.styled = True
        S.bring_to_front(self.hwnd)
        self.input.focus_force()
        self._fit()
        self.timings["show_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    def hide(self):
        if self.rec is not None:
            self._stop_rec(send=False)
        if self.visible:
            self.root.withdraw()
            self.visible = False

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.b_pin.set(glyph=G["pinned"] if self.pinned else G["pin"], style="accent" if self.pinned else "ghost")
        self.b_pin.tip = "Pinned: stays open (click to let it hide again)" if self.pinned else "Keep the bar open while you work elsewhere"

    def _escape(self, e=None):
        if self.rec is not None:
            self._stop_rec(send=False)
            self._status_idle()
        else:
            self.hide()

    def _drag_start(self, e):
        self._drag = (e.x_root - self.x, e.y_root - self.y)

    def _drag_move(self, e):
        dx, dy = self._drag
        self.x, self.y = e.x_root - dx, e.y_root - dy
        self.root.geometry(f"+{self.x}+{self.y}")

    def _fit(self, scroll=False):
        if not self.visible:
            return
        self.root.update_idletasks()
        T = self.convo
        if T.index("end-1c") != "1.0":
            try:
                n = T.count("1.0", "end", "update", "ypixels")  # 'update': measured now, not estimated
                n = (n[0] if isinstance(n, tuple) else n) or 0
            except tk.TclError:
                n = 10**4
            other = self.card.winfo_reqheight() - (self.convo_box.winfo_reqheight() if self.convo_box.winfo_manager() else 0)
            h = max(round(60 * self.s), min(n + round(10 * self.s), self.maxh - other, round(520 * self.s)))
            if not self.convo_box.winfo_manager():
                self.sep.pack(fill="x", pady=(round(10 * self.s), 0), before=self.foot)
                self.convo_box.pack(fill="x", before=self.foot)
            self.convo_box.configure(height=h)
        elif self.convo_box.winfo_manager():
            self.convo_box.pack_forget()
            self.sep.pack_forget()
        self.root.update_idletasks()
        self.root.geometry(f"{self.W}x{self.card.winfo_reqheight()}+{self.x}+{self.y}")
        if scroll:
            T.see("end")

    def _enable_drop(self):
        """Files dragged from File Explorer onto the bar are attached (WM_DROPFILES on the bar's window)."""
        import ctypes
        from ctypes import wintypes

        try:
            shell32, u = ctypes.WinDLL("shell32"), S.user32
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            u.SetWindowLongPtrW.restype = ctypes.c_void_p
            u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            u.CallWindowProcW.restype = ctypes.c_ssize_t
            u.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragFinish.argtypes = [wintypes.HANDLE]
            shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

            def proc(hwnd, msg, wp, lp):
                if msg == 0x0233:  # WM_DROPFILES
                    try:
                        n = shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                        files = []
                        for k in range(min(n, 50)):
                            ln = shell32.DragQueryFileW(wp, k, None, 0) + 1
                            buf = ctypes.create_unicode_buffer(ln)
                            shell32.DragQueryFileW(wp, k, buf, ln)
                            files.append(buf.value)
                        self.q.put(("drop", files))
                    finally:
                        shell32.DragFinish(wp)
                    return 0
                return u.CallWindowProcW(self._old_proc, hwnd, msg, wp, lp)

            self._proc = WNDPROC(proc)  # kept: Windows calls it for as long as the window lives
            self._old_proc = u.SetWindowLongPtrW(self.hwnd, -4, ctypes.cast(self._proc, ctypes.c_void_p))  # GWLP_WNDPROC
            shell32.DragAcceptFiles(self.hwnd, True)
            self.drop_ok = bool(self._old_proc)
        except Exception as e:  # noqa: BLE001 - dropping files is a convenience; attach still works
            self.drop_ok = False
            self.logf(f"drop: {e!r}")

    # ---------------------------------------------------------------- talking
    def mic_click(self):
        if self.rec is not None:
            self._stop_rec(send=True)
        else:
            if not self.visible:
                self.show()
            self._start_rec("click")

    def _start_rec(self, how):
        if self.rec is not None:
            return
        try:
            if self.recorder_factory is not None:
                rec = self.recorder_factory()
            else:
                from ai_pc.assistant.mic import Recorder

                rec = Recorder()
            rec.start()
        except Exception as e:  # noqa: BLE001 - said in the bar
            self._say_status(f"{e}", warn=True)
            return
        self.rec, self.rec_how = rec, how

        def preload():
            try:
                from ai_pc.media import speech

                if speech.available():
                    speech._load()
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=preload, daemon=True, name="aipc-whisper").start()
        self.b_mic.set(style="danger")
        self._placeholder()
        self._suggest()

    def _stop_rec(self, send=True):
        rec, self.rec = self.rec, None
        self.b_mic.set(style="ghost", glow=0.0)
        self._placeholder()
        if rec is None:
            return
        if not send:
            rec.cancel()
            self._say_status("Cancelled.")
            return
        folder = (Path(self.agent.chat.folder) if self.agent.chat is not None else HOME) / "voice"
        path = rec.stop(folder / f"note_{time.strftime('%Y%m%d_%H%M%S')}.wav")
        if path:
            self.send(voice=str(path))
        else:
            self._say_status("I did not catch that: keep holding the keys while you talk.", warn=True)
        self._suggest()

    def _on_hotkey(self, d):
        now = time.monotonic()
        was = bool(self.focused())
        self.press = {"t": now, "was": was}
        self.swallow_until = now + 120
        if not was:
            self.show(d.get("fg"))
        p = self.press
        self.root.after(int(self.cfg["hold_to_talk"] * 1000), lambda: self._hold_check(p))

    def _hold_check(self, p):
        if self.press is p and self.rec is None:
            self._start_rec("hold")

    def _on_hotkey_up(self, d):
        p, self.press = self.press, None
        self.swallow_until = time.monotonic() + 0.15
        if self.rec is not None and self.rec_how == "hold":
            self._stop_rec(send=True)
        elif p and p["was"] and d.get("held", 0) < self.cfg["hold_to_talk"]:
            self.hide()

    # ---------------------------------------------------------------- sending and the conversation
    def send(self, text=None, voice=None):
        if text is None:
            text = self.input.get("1.0", "end-1c").strip()
        if not text and not voice and not self.attach:
            return None
        files, ctx = list(self.attach), list(self.context)
        jid = self.agent.send(text, files=files, context=ctx, voice=voice, where=self.where)
        if text and (not self.sent or self.sent[-1] != text):
            self.sent.append(text)
        self.hpos = None
        self.input.delete("1.0", "end")
        self.attach, self.context = [], []
        for row in self.rows:
            for w in row:
                w.disable()
        self.rows, self.pending = [], False
        self.tip("")
        self._add_user(jid, text, bool(voice), files + ctx)
        self._chips()
        self._changed()
        return jid

    def answer(self, word):
        if self.pending:
            self.send(word)

    def _add_user(self, jid, text, voice, files):
        T = self.convo
        T.configure(state="normal")
        T.insert("end", "You", "who")
        T.insert("end", "   " + time.strftime("%I:%M %p").lstrip("0"), "time")
        T.insert("end", "\n")
        if voice:
            T.insert("end", G["mic"] + "  ", "icon")
            tag = f"voice{jid}"
            T.insert("end", "(voice note)" + (f" {text}" if text else ""), ("heard", tag))
            self.voice_tags[jid] = (tag, text)
        else:
            T.insert("end", text or "", "you")
        if files:
            T.insert("end", "\n" + G["attach"] + "  ", "icon_m")
            T.insert("end", ", ".join(Path(p).name for p in files), "muted")
        T.insert("end", "\n")
        T.configure(state="disabled")
        self._fit(scroll=True)

    def _add_reply(self, d):
        T, s, P = self.convo, self.s, self.P
        T.configure(state="normal")
        tag, typed = self.voice_tags.pop(d.get("id"), (None, ""))
        if tag and d.get("heard"):
            rng = T.tag_ranges(tag)
            if rng:
                T.delete(rng[0], rng[1])
                T.insert(rng[0], f"{typed} {d['heard']}".strip(), ("you", tag))
        for label, body in d.get("parts") or [(None, d.get("text", ""))]:
            if label:
                T.insert("end", label.upper(), "badge")
                T.insert("end", "\n")
            T.insert("end", shown_text(body).strip() + "\n", "err" if d.get("failed") else "ai")
        files = d.get("files") or []
        pics = [p for p in files if kind_of(p) == "image" and Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")]
        if pics:
            self._picture(pics[-1])
        vids = [p for p in files if kind_of(p) == "video"]
        if vids and not pics:
            self._video_still(vids[-1])
        pdfs = [p for p in files if Path(p).suffix.lower() == ".pdf"]
        if pdfs and not pics and not vids:
            self._page_still(pdfs[-1])
        if files:
            row = tk.Frame(T, bg=P["bg"])
            for p in files[:6]:
                self._file_chip(row, p).pack(side="left", padx=(0, round(10 * s)), pady=round(3 * s))
            T.window_create("end", window=row)
            T.insert("end", "\n")
        if d.get("pending"):
            row = tk.Frame(T, bg=P["bg"])
            yes = Pill(row, self, "Yes, go ahead", icon=G["check"], style="accent", command=lambda: self.answer("yes"), h=30)
            no = Pill(row, self, "No", style="outline", command=lambda: self.answer("no"), h=30)
            yes.pack(side="left", padx=(0, round(8 * s)), pady=round(4 * s))
            no.pack(side="left", pady=round(4 * s))
            T.window_create("end", window=row)
            T.insert("end", "\n")
            self.rows.append([yes, no])
            self.pending = True
            self.hint.configure(text="Alt+Y yes · Alt+N no · Esc hide")
        if d.get("choice"):
            row = tk.Frame(T, bg=P["bg"])
            pills = []
            for k, p in enumerate(d["choice"][:5], 1):
                pl = Pill(
                    row,
                    self,
                    f"{k}  {Path(p).name}",
                    icon=KIND_ICON.get(kind_of(p), G["file"]),
                    style="chip",
                    maxw=200,
                    command=lambda k=k: self.send(str(k)),
                )
                pl.pack(side="left", padx=(0, round(6 * s)), pady=round(4 * s))
                pills.append(pl)
            T.window_create("end", window=row)
            T.insert("end", "\n")
            self.rows.append(pills)
        if d.get("seconds", 0) >= 1 or d.get("usd"):
            meta = f"{d.get('seconds', 0):.1f} s" + (f" · AI ${d['usd']:.4f}" if d.get("usd") else "")
            T.insert("end", meta + "\n", "meta")
        T.configure(state="disabled")
        self._suggest()
        self._fit(scroll=True)

    def _file_chip(self, master, p):
        f = tk.Frame(master, bg=self.P["bg"])
        Pill(f, self, self.agent.nice_name(p), icon=KIND_ICON.get(kind_of(p), G["file"]), style="chip", maxw=220, command=lambda: self._open(p)).pack(
            side="left"
        )
        IconButton(f, self, G["folder"], lambda: self._reveal(self.agent.nice_file(p)), size=28, tip="Show in folder", font="icon_s").pack(
            side="left", padx=(round(2 * self.s), 0)
        )
        IconButton(
            f,
            self,
            G["copy"],
            lambda: self._copy(self.agent.nice_file(p)),
            size=28,
            tip="Copy the file (then paste it anywhere: Ctrl+V)",
            font="icon_s",
        ).pack(side="left")
        return f

    def _open(self, p):
        try:
            S.open_file(p)
        except OSError as e:
            self._say_status(f"Could not open it: {e}", warn=True)

    def _reveal(self, p):
        try:
            S.show_in_folder(p)
        except OSError as e:
            self._say_status(f"Could not show it: {e}", warn=True)

    def _copy(self, p):
        try:
            S.copy_files([p])
            self._say_status(f"Copied {Path(p).name}: paste it anywhere with Ctrl+V.")
        except Exception as e:  # noqa: BLE001
            self._say_status(f"Could not copy it: {e}", warn=True)

    def _rounded_photo(self, im, box=(320, 180)):
        from PIL import Image, ImageDraw, ImageTk

        s = self.s
        im = im.convert("RGB")
        im.thumbnail((round(box[0] * s), round(box[1] * s)))
        k, (w, h) = 4, im.size
        mask = Image.new("L", (w * k, h * k), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=round(8 * s) * k, fill=255)
        bg = Image.new("RGB", (w, h), self.P["bg"])
        bg.paste(im, (0, 0), mask.resize((w, h), Image.LANCZOS))
        ph = ImageTk.PhotoImage(bg)
        self.imgs.append(ph)
        return ph

    def _picture(self, p):
        try:
            from PIL import Image

            with Image.open(p) as im:
                ph = self._rounded_photo(im)
        except Exception:  # noqa: BLE001
            return
        lab = tk.Label(self.convo, image=ph, bg=self.P["bg"], bd=0, cursor="hand2")
        lab.bind("<Button-1>", lambda e: self._open(p))
        lab.bind("<MouseWheel>", self.wheel)
        self.convo.window_create("end", window=lab, pady=round(4 * self.s))
        self.convo.insert("end", "\n")

    def _video_still(self, p):
        holder = tk.Frame(self.convo, bg=self.P["bg"])
        self.convo.window_create("end", window=holder)
        self.convo.insert("end", "\n")
        out = HOME / "stills" / (Path(p).stem + ".jpg")

        def grab():
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(p), "-frames:v", "1", "-vf", "scale=640:-2", str(out)],
                    capture_output=True,
                    timeout=30,
                    creationflags=CREATE_NO_WINDOW,
                )
                if out.is_file():
                    self.q.put(("still", holder, str(out), p))
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=grab, daemon=True, name="aipc-still").start()

    def _page_still(self, p):
        """A document, deck or drawing shows its first page, drawn in the background (the file chip is below it)."""
        holder = tk.Frame(self.convo, bg=self.P["bg"])
        self.convo.window_create("end", window=holder)
        self.convo.insert("end", "\n")
        out = HOME / "stills" / (Path(p).stem + "_p1.jpg")

        def draw():
            try:
                first_page_jpg(p, out)
                self.q.put(("still", holder, str(out), p))
            except Exception:  # noqa: BLE001 - the picture is a nicety; the file is still there to open
                pass

        threading.Thread(target=draw, daemon=True, name="aipc-page").start()

    def _show_still(self, holder, img_path, video):
        try:
            from PIL import Image

            with Image.open(img_path) as im:  # a page is shown taller, so a portrait page is still readable at a glance
                ph = self._rounded_photo(im, (320, 260) if str(video).lower().endswith(".pdf") else (320, 180))
        except Exception:  # noqa: BLE001
            return
        lab = tk.Label(holder, image=ph, bg=self.P["bg"], bd=0, cursor="hand2")
        lab.pack(pady=round(4 * self.s), anchor="w")
        lab.bind("<Button-1>", lambda e: self._open(video))
        lab.bind("<MouseWheel>", self.wheel)
        self._fit(scroll=True)

    def _history(self, turns):
        T = self.convo
        for t in turns[-6:]:
            T.configure(state="normal")
            said = t.get("user") or t.get("heard") or ""
            if said:
                T.insert("end", "You\n", "who")
                T.insert("end", said + "\n", "you")
            for label, body in split_reply(t.get("reply", "")):
                if label:
                    T.insert("end", label.upper() + "\n", "badge")
                T.insert("end", shown_text(body).strip() + "\n", "ai")
            if t.get("made"):
                row = tk.Frame(T, bg=self.P["bg"])
                for p in t["made"][:4]:
                    self._file_chip(row, p).pack(side="left", padx=(0, round(10 * self.s)), pady=round(3 * self.s))
                T.window_create("end", window=row)
                T.insert("end", "\n")
            T.configure(state="disabled")
        if turns:
            T.configure(state="normal")
            T.insert("end", "(earlier in this chat · Ctrl+N starts a new one)\n", "meta")
            T.configure(state="disabled")
        self._suggest()
        self._fit(scroll=True)

    def new_chat(self):
        self.agent.new_chat()

    # ---------------------------------------------------------------- status line
    def _status_idle(self):
        if self.busy:
            return
        txt = f"Ready · {self.combo} opens this from anywhere" if self.combo else "Ready"
        self.status.configure(text=txt, fg=self.P["muted"])

    def _say_status(self, text, warn=False):
        self.status.configure(text=text, fg=self.P["danger"] if warn else self.P["muted"])
        self._status_until = time.monotonic() + 6

    def _status_busy(self):
        el = int(time.monotonic() - (self.job_t0 or time.monotonic()))
        parts = [self.lane or "Working", (self.note or "working on it…")[:90], f"{el // 60}:{el % 60:02d}"]
        if self.waiting:
            parts.append(f"{self.waiting} waiting")
        self.status.configure(text="  ·  ".join(parts), fg=self.P["text"])

    def _menu(self):
        combo = f"\t{self.combo}" if self.combo else ""
        return [
            (1, f"Open AI PC{combo}", False),
            (2, "New chat", False),
            None,
            (3, "Start with Windows", S.starts_with_windows()),
            (4, "Open the chats folder", False),
            None,
            (9, "Quit AI PC", False),
        ]

    def _menu_pick(self, mid):
        if mid == 1:
            self.show()
        elif mid == 2:
            self.new_chat()
            self.show()
        elif mid == 3:
            on = not S.starts_with_windows()
            S.set_starts_with_windows(on, S.launch_command(ROOT, startup=True))
            self.shell.notify("AI PC", "AI PC will start when you sign in to Windows." if on else "AI PC will no longer start with Windows.")
        elif mid == 4:
            folder = Path(self.agent.chat.folder).parent if self.agent.chat is not None else HOME
            S.open_file(folder)
        elif mid == 9:
            self.quit()

    def quit(self):
        try:
            if self.rec is not None:
                self.rec.cancel()
            self.agent.stop()
            self.shell.stop()
        finally:
            self.root.after(50, self.root.destroy)

    # ---------------------------------------------------------------- the loop
    def _tick(self):
        try:
            while True:
                item = self.q.get_nowait()
                self._handle(item)
        except queue.Empty:
            pass
        now = time.monotonic()
        if self.busy:
            w = self.inner
            seg = w // 4
            x = ((now * 0.8) % 1.0) * (w + seg) - seg
            self.prog.coords(self.prog_seg, x, 0, x + seg, self.bar_h)
            if now - getattr(self, "_st_t", 0) > 0.25:
                self._st_t = now
                self._status_busy()
        if self.rec is not None:
            lvl = round(getattr(self.rec, "level", 0.0) or 0.0, 1)  # ten steps are enough for the eye
            if lvl != self.b_mic.glow:
                self.b_mic.set(glow=lvl)
            if now - getattr(self, "_rec_t", 0) > 0.25:
                self._rec_t = now
                sec = self.rec.seconds() if hasattr(self.rec, "seconds") else 0
                how = f"let go of {self.combo} to send" if self.rec_how == "hold" else "click the mic (or Ctrl+M) to send"
                self.status.configure(text=f"Listening {int(sec)}s · {how} · Esc cancels", fg=self.P["danger"])
        elif not self.busy and getattr(self, "_status_until", 0) and now > self._status_until:
            self._status_until = 0
            self._status_idle()
        if self.visible and not self.pinned and not self.dialog and self.rec is None and now - self.shown_at > 0.4:
            fg = int(S.user32.GetForegroundWindow() or 0)
            if fg and S.is_ours(fg):
                self.had_focus = True
            elif fg and self.had_focus and self.press is None:
                self.hide()  # clicked somewhere else
        self.root.after(16, self._tick)

    def _handle(self, item):
        src = item[0]
        if src == "shell":
            kind, d = item[1], item[2]
            if kind == "hotkey":
                self._on_hotkey(d)
            elif kind == "hotkey_up":
                self._on_hotkey_up(d)
            elif kind in ("show", "tray"):
                self.logf(f"{kind}: {d.get('click') or 'asked by a second start'}")
                if self.visible and kind == "tray" and d.get("click") == "left":
                    self.hide()
                else:
                    self.show(d.get("fg") if kind == "show" else None)
            elif kind == "menu":
                self._menu_pick(d.get("id"))
        elif src == "agent":
            kind, d = item[1], item[2]
            if kind == "ready":
                self.ready_info = d
                self._history(d.get("turns") or [])
            elif kind == "start":
                self.busy, self.job_t0, self.lane, self.note, self.job_id = True, time.monotonic(), "", "", d["id"]
                self._status_busy()
            elif kind == "queued":
                self.waiting = d.get("waiting", 0)
            elif kind == "lane":
                self.lane = d["label"]
            elif kind == "progress":
                self.note = d["line"]
            elif kind == "reply":
                self.waiting = d.get("waiting", 0)
                self.busy = self.waiting > 0
                if not self.busy:
                    self.prog.coords(self.prog_seg, 0, 0, 0, 0)
                    self._say_status(("Done" if not d.get("failed") else "Failed") + f" in {d.get('seconds', 0):.1f} s")
                self._add_reply(d)
                if not self.visible and self.cfg.get("notify"):
                    first = shown_text(d["parts"][0][1] if d.get("parts") else d.get("text", "")).strip().splitlines()
                    self.shell.notify("AI PC" + (": waiting for your yes" if d.get("pending") else ""), (first[0] if first else "Done")[:200])
            elif kind == "newchat":
                self.convo.configure(state="normal")
                self.convo.delete("1.0", "end")
                self.convo.configure(state="disabled")
                self.rows, self.pending, self.imgs, self.voice_tags = [], False, [], {}
                self._say_status("New chat: 'it' and 'this' start afresh.")
                self._suggest()
                self._fit()
            elif kind == "error":
                self._say_status(d.get("text", "error"), warn=True)
                self.logf(d.get("trace") or d.get("text"))
        elif src == "ctx":
            _, n, files, where = item
            if n == self.show_n and files:
                self.context, self.where = files, where
                self._chips()
        elif src == "drop":
            self.add_files(item[1])
            self.show()
        elif src == "still":
            self._show_still(item[1], item[2], item[3])

    def _tk_error(self, exc, val, tb):
        if exc is KeyboardInterrupt:
            self.quit()
            return
        self.logf("".join(traceback.format_exception(exc, val, tb)))
        try:
            self._say_status(f"Something went wrong ({exc.__name__}); see out/aipc/bar.log", warn=True)
        except Exception:  # noqa: BLE001
            pass

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- the icon, settings, starting
def make_icon(path=ICON):
    """The AI PC icon (a rounded square with a spark), for the tray and the shortcut."""
    path = Path(path)
    if path.is_file():
        return path
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    grad = Image.new("RGBA", (n, n))
    for y in range(n):
        t = y / (n - 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip((76, 194, 255), (0, 95, 184)))
        ImageDraw.Draw(grad).line([(0, y), (n, y)], fill=c + (255,))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((8, 8, n - 9, n - 9), radius=56, fill=255)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    cx, cy, R, r = n // 2, n // 2, 84, 18  # a four-point spark
    d.polygon(
        [(cx, cy - R), (cx + r, cy - r), (cx + R, cy), (cx + r, cy + r), (cx, cy + R), (cx - r, cy + r), (cx - R, cy), (cx - r, cy - r)],
        fill=(255, 255, 255, 255),
    )
    d.ellipse((cx + 50, cy - 86, cx + 82, cy - 54), fill=(255, 255, 255, 230))
    im.save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def places():
    """(settings file, log file): out/aipc, or the folder in AIPC_BAR_HOME (the tests' own, so they never touch yours)."""
    home = Path(os.environ.get("AIPC_BAR_HOME") or HOME)
    return home / "bar.json", home / "bar.log"


def load_config(path=None):
    path = Path(path or places()[0])
    cfg = dict(DEFAULTS)
    try:
        if path.is_file():
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(DEFAULTS, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return cfg


def _logger(path=None):
    path = Path(path or places()[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size > 2_000_000:
        path.write_text("", encoding="utf-8")

    def log(*a):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
        except OSError:
            pass

    return log


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(prog="ai-pc bar", description="the AI PC command bar (press the combo anywhere)")
    ap.add_argument("--offline", action="store_true", help="rules only, no AI model")
    ap.add_argument("--shortcut", action="store_true", help="make 'AI PC.lnk' in the project folder, to pin to Start or the taskbar")
    ap.add_argument("--startup", action="store_true", help="started with Windows: no 'ready' notification")
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    make_icon()
    if a.shortcut:
        lnk = ROOT / "AI PC.lnk"
        ok = S.make_shortcut(lnk, S.launch_command(ROOT), icon=ICON, workdir=ROOT)
        print(f"{'made' if ok else 'could not make'} {lnk}")
        return
    cfg_path, log_path = places()
    cfg = load_config(cfg_path)
    if not a.child and not S.has_console():
        h = S.single_instance(f"Local\\{cfg['name']}_Bar")
        if h is None:  # already running (a second click on the shortcut): show it
            S.poke_running(f"{cfg['name']}_Shell")
            return
        S.kernel32.CloseHandle(h)
        # started with no console (pythonw: the shortcut, Start with Windows): run the bar from python.exe with a console that has no
        # window, so the programs it runs (FFmpeg, Git, compilers) never flash a black window
        exe = Path(sys.executable).with_name("python.exe")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path.with_name("bar.out.txt"), "wb") as out:  # what programs print; its own file (the log is written by lines)
            subprocess.Popen(
                [str(exe), "-m", "ai_pc", "bar", "--child"] + (["--offline"] if a.offline else []) + (["--startup"] if a.startup else []),
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
        return
    log = _logger(log_path)
    mutex = S.single_instance(f"Local\\{cfg['name']}_Bar")
    if mutex is None:
        S.poke_running(f"{cfg['name']}_Shell")
        log("a second start: the running bar was asked to show itself")
        print("AI PC is already running: it is showing its bar.")
        return
    S.dpi_aware()
    planner = None
    if not a.offline:
        from ai_pc.llm.planner import ChatPlanner

        planner = ChatPlanner()
    windowless = not S.kernel32.GetConsoleWindow() and bool(S.kernel32.GetConsoleCP())  # a console (for the programs it runs), no window
    log(f"start (offline={a.offline}, {Path(sys.executable).name}, {'console with no window' if windowless else 'console window'})")
    bar = Bar(cfg, agent_kw={"planner": planner}, shell_kw={"name": f"{cfg['name']}_Shell", "tray": bool(cfg.get("tray", True))}, log=log)
    if not bar.combo:
        log(f"no combo could be registered: {bar.shell.failed}")
    else:
        log(f"combo {bar.combo}")
    print(f"AI PC is running: press {bar.combo or '(no combo free; click the tray icon)'} anywhere. Quit from the tray icon.", flush=True)
    try:
        wanted = S.parse_hotkey(cfg["hotkey"])[2]
    except ValueError:
        wanted = cfg["hotkey"]
    if not bar.combo:
        bar.shell.notify(
            "AI PC",
            f"{wanted} and the other combos AI PC tries are taken by other programs. Click this icon to open AI PC, "
            f"or put another combo in {cfg_path}.",
        )
    elif bar.combo != wanted:
        bar.shell.notify("AI PC", f"{wanted} is taken by another program, so AI PC opens with {bar.combo}.")
    elif not a.startup:
        bar.shell.notify("AI PC is ready", f"Press {bar.combo} anywhere and ask. Hold it to talk.")
    bar.run()
    log("quit")
