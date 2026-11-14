"""Okno programu: lista systemów, menu, zapis do pliku .img albo na kartę SD."""
import json
import os
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import backup, devices, i18n
from .compose import DOOM_LOGO, DOOM_NAME, MAX_ENTRIES, MAX_SECS, XIEGU_DEFAULTS, compose, resolve_extras
from .i18n import t
from .image import SourceSystem, cache_dir, open_source
from .writer import Progress, write_device, write_image_file

APP = "Xiegu Multi Patcher"


def app_version():
    """This computer's app version, from assets/versions.json (each system numbered on its own)"""
    import sys
    key = "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "versions.json")) as f:
            return json.load(f).get(key, "")
    except (OSError, ValueError):
        return ""
AUTHOR_URL = "https://www.qrz.com/db/SQ6RT"
HEAD_BG, HEAD_FG, HEAD_SUB, LINK = "#0f2742", "#ffffff", "#a9bcd3", "#8fc3ff"
# Colours of the light and the dark theme; _apply_colours() sets the module's names from one
THEMES = {
    "light": {"HINT": "#5b6573", "ACCENT": "#0067c0", "BADGE_FG": "#ffffff", "PAGE_BG": "#fafafa",
              "TEXT_FG": "#1c1c1c", "WARN": "#b45309", "H1": "#c62828", "H2": "#0f2742", "TREE_BG": (255, 255, 255)},
    "dark": {"HINT": "#9aa3ad", "ACCENT": "#57c8ff", "BADGE_FG": "#0b1a2a", "PAGE_BG": "#1c1c1c",
             "TEXT_FG": "#e6e6e6", "WARN": "#ffb454", "H1": "#ff6b6b", "H2": "#8fc3ff", "TREE_BG": (28, 28, 28)},
}
THEME_NAMES = {"light": "Jasny", "dark": "Ciemny"}
HINT = "#5b6573"
BADGE_FG, H1, H2, TREE_BG = "#ffffff", "#c62828", "#0f2742", (255, 255, 255)
SCREEN_W, SCREEN_H = 640, 384          # the radio's 800x480 to start with; it grows with the window
RED, RED_HOVER = "#d32f2f", "#ef4444"
GREEN = "#1e8e3e"
ACCENT = "#0067c0"
PAGE_BG, TEXT_FG, WARN = "#fafafa", "#1c1c1c", "#b45309"


def _theme_name():
    name = i18n.setting("theme", "light")
    return name if name in THEMES else "light"


def _apply_colours(name):
    globals().update(THEMES[name])
PHASES = {"download": "Pobieranie", "prepare": "Przygotowanie karty", "write": "Zapis",
          "sync": "Opróżnianie bufora karty",
          "verify": "Weryfikacja", "unzip": "Rozpakowywanie", "done": "Gotowe",
          "backup": "Zrzut DATA", "restore": "Przywracanie DATA"}


def _gb(n):
    return f"{n / 1e9:.1f} GB"


# Colours of the app's own buttons: (normal, under the pointer)
BTN = {
    "blue": ("#1f6fd1", "#3a86e8"), "teal": ("#0f8b8d", "#17a7aa"), "orange": ("#d9822b", "#eb9845"),
    "doom": ("#8e1b1b", "#ad2626"), "green": ("#2e9d4f", "#39b95f"), "slate": ("#55707d", "#68848f"),
    "red": ("#d32f2f", "#ef4444"),
}


class ColorButton(tk.Canvas):
    """A rounded coloured button that looks the same on Windows, macOS and Linux (themed buttons take
    no colour on every system); state(["disabled"]) and state(["!disabled"]) as a ttk button"""

    def __init__(self, parent, text, colour, command, image=None, font=None, padx=18, pady=11, radius=12,
                 width=None):
        import tkinter.font as tkfont
        self._c, self._h = BTN[colour]
        self._cmd, self._on, self._hover = command, True, False
        self._text, self._image, self._r = text, image, radius
        self._font = font or _font(11, "bold")
        f = tkfont.Font(font=self._font)
        tw, th = f.measure(text), f.metrics("linespace")
        iw = image.width() + 10 if image is not None else 0
        ih = image.height() if image is not None else 0
        w = max(tw + iw + 2 * padx, (width or 0) * f.measure("0"))
        h = max(th, ih) + 2 * pady
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, bg=PAGE_BG, cursor="hand2")
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self._on and self._cmd())
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), int(self["width"])), max(self.winfo_height(), int(self["height"]))
        if self.winfo_ismapped():
            w, h = self.winfo_width(), self.winfo_height()
        r = min(self._r, h // 2)
        fill = (self._h if self._hover else self._c) if self._on else "#a7adb3"
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, fill=fill, outline="")
        if self._image is not None:
            import tkinter.font as tkfont
            tw = tkfont.Font(font=self._font).measure(self._text)
            x0 = (w - (self._image.width() + 10 + tw)) // 2
            self.create_image(x0, h // 2, image=self._image, anchor="w")
            self.create_text(x0 + self._image.width() + 10, h // 2, text=self._text, fill="#ffffff",
                             font=self._font, anchor="w")
        else:
            self.create_text(w // 2, h // 2, text=self._text, fill="#ffffff", font=self._font)

    def state(self, flags):
        on = "!disabled" in flags
        if "disabled" in flags or on:
            self._on = on
            self.configure(cursor="hand2" if on else "arrow")
            self._draw()


class BigBar(tk.Canvas):
    """A thick rounded progress bar; moving() makes a block run along it while there is no count"""

    def __init__(self, parent, width=520, height=24):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=PAGE_BG)
        self.w, self.h, self.frac, self.run, self.pos = width, height, 0.0, False, 0.0
        self.colour = "#2e9d4f"
        self.bind("<Configure>", self._resized)
        self._draw()

    def _resized(self, ev):
        if ev.width > 10 and ev.width != self.w:
            self.w = ev.width
            self._draw()

    def _round(self, x0, x1, fill):
        h, r = self.h, self.h // 2
        if x1 - x0 < 2 * r:
            x1 = x0 + 2 * r
        pts = [x0 + r, 0, x1 - r, 0, x1, 0, x1, r, x1, h - r, x1, h, x1 - r, h, x0 + r, h, x0, h, x0, h - r,
               x0, r, x0, 0]
        self.create_polygon(pts, smooth=True, fill=fill, outline="")

    def _draw(self):
        self.delete("all")
        self._round(0, self.w, "#d7dde3" if PAGE_BG.lower() > "#888888" else "#3a3f45")
        if self.run:
            x0 = (self.w + 160) * self.pos - 160
            self._round(max(0, x0), min(self.w, x0 + 160), ACCENT)
        elif self.frac > 0:
            self._round(0, max(self.h, int(self.w * self.frac)), self.colour)

    def set(self, frac):
        self.run, self.frac = False, max(0.0, min(1.0, frac))
        self._draw()

    def moving(self):
        if self.run:
            return
        self.run = True
        self._tick()

    def idle(self):
        self.run, self.frac = False, 0.0
        self._draw()

    def _tick(self):
        if not self.run or not self.winfo_exists():
            return
        self.pos = (self.pos + 0.012) % 1.0
        self._draw()
        self.after(20, self._tick)


class ProgressPanel(ttk.Frame):
    """What the app is doing, at the bottom of its window (always in sight, nothing pops up): the
    job and its stage ("stage 2 of 4"), a big bar, the per cent, how much, how fast and how long
    still; the bar moves by itself while there is no count yet, so it never looks frozen. At rest:
    the last result or a hint what to do next."""

    def __init__(self, parent, status):
        super().__init__(parent, style="Card.TFrame", padding=(16, 8))
        self.status = status                       # the app's status line (a StringVar), shown at rest
        top = ttk.Frame(self, style="Card.TFrame")
        top.pack(fill="x")
        self.title = ttk.Label(top, text="", font=_font(13, "bold"))
        self.title.pack(side="left")
        self.pct = ttk.Label(top, text="", font=_font(16, "bold"), foreground=ACCENT)
        self.pct.pack(side="right")
        self.bar = BigBar(self, width=600, height=18)          # shown while a job runs
        low = self.low = ttk.Frame(self, style="Card.TFrame")
        low.pack(fill="x", pady=(2, 0))
        self.skip = ttk.Button(low, text=t("Pomiń sprawdzanie karty"), command=self._skip)
        self.detail = ttk.Label(low, textvariable=status, foreground=HINT, wraplength=900, justify="left")
        self.detail.pack(side="left", fill="x", expand=True, anchor="w")
        self.bind("<Configure>", lambda e: self.detail.configure(wraplength=max(300, e.width - 260)))
        self.on_skip = None           # set by a card write: the read-back may be skipped
        self.steps, self.job = [], ""
        self.moving, self.phase, self.t0, self.d0 = False, None, time.time(), 0
        self.rest(t("Gotowa do pracy"))

    def rest(self, title, colour=None):
        """Nothing running: a title (ready, done, an error) over the status line"""
        self.bar.idle()
        self.bar.pack_forget()
        self.moving, self.phase, self.on_skip = False, None, None
        self.title.configure(text=title, foreground=colour or TEXT_FG)
        self.pct.configure(text="")
        self.skip.pack_forget()

    def start(self, text, steps=None):
        self.job, self.steps = text, list(steps or [])
        self.phase, self.t0, self.d0, self.on_skip = None, time.time(), 0, None
        self.title.configure(text=text, foreground=TEXT_FG)
        self.pct.configure(text="")
        self.status.set(t("Łączenie…") if "download" in self.steps else t("Pracuję…"))
        self.bar.colour = "#2e9d4f"
        self.bar.pack(fill="x", pady=(6, 4), before=self.low)
        self.bar.moving()
        self.moving = True
        self.skip.pack_forget()

    def _skip(self):
        if self.on_skip:
            self.on_skip()
        self.skip.state(["disabled"])

    def update(self, phase, done, total, msg=""):
        if phase != self.phase:                       # a new stage: its own speed and time
            self.phase, self.t0, self.d0 = phase, time.time(), done
            name = t(PHASES.get(phase, phase))
            if phase in self.steps and len(self.steps) > 1:
                name = t("Etap {k} z {n}: {name}", k=self.steps.index(phase) + 1, n=len(self.steps), name=name)
            self.title.configure(text="%s  ·  %s" % (self.job, name))
            if phase == "verify" and self.on_skip:
                self.skip.state(["!disabled"])
                self.skip.pack(side="right", padx=(10, 0))
            else:
                self.skip.pack_forget()
        if total <= 0:
            if not self.moving:
                self.bar.moving()
                self.moving = True
            self.pct.configure(text="")
            txt = "%d MB" % (done >> 20) if done else t("Pracuję…")
        else:
            self.moving = False
            self.bar.set(done / total)
            self.pct.configure(text="%d%%" % (done * 100 // total))
            dt = time.time() - self.t0
            speed = (done - self.d0) / dt if dt > 0.5 else 0
            left = (total - done) / speed if speed > 0 else None
            txt = "%d / %d MB" % (done >> 20, total >> 20) if total >= 4 << 20 else "%d / %d" % (done, total)
            if speed and total >= 4 << 20:
                txt += "   ·   %.1f MB/s" % (speed / 1e6)
            if left is not None and done < total:
                txt += "   ·   " + t("zostało {t}", t="%d:%02d" % (left // 60, left % 60))
        self.status.set(txt + ("   ·   " + msg if msg and msg != "unchecked" else ""))


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP + (" " + app_version() if app_version() else ""))
        root.minsize(760, 420)
        self.entries = []                 # {"kind", "name", "sys"?}
        self.default = 0
        self.q = queue.Queue()
        self.busy = False
        self.cards = []
        self.tiles = {}                   # key -> what the radio's screen shows for an entry
        self._tile_jobs = set()
        self.data_src = None              # the user's own copy of DATA (.zip or folder) for the new card
        self._skip, self._skip_file = threading.Event(), None
        self._build_all()
        self.refresh_cards()
        self.root.after(100, self._poll)

    # ---------------------------------------------------------------- layout
    def _build_all(self, keep=None):
        # Everything under the header scrolls when the window is lower than its contents (a small
        # or scaled laptop screen): a canvas holding the body, a scrollbar shown only when needed
        # What the app is doing: docked at the bottom of the window, outside what scrolls
        self.status = tk.StringVar(value=t("Zacznij od „+ Z internetu…”: wybierz system, a aplikacja sama go pobierze."))
        self.panel = ProgressPanel(self.root, self.status)
        self.panel.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.top = ttk.Frame(self.root)
        self.top.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._scroll = tk.Canvas(self.top, highlightthickness=0, bg=PAGE_BG, width=900, height=400)
        self._sbar = ttk.Scrollbar(self.top, orient="vertical", command=self._scroll.yview)
        self._scroll.configure(yscrollcommand=self._sbar.set)
        self._scroll.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self._scroll)
        self._body_id = self._scroll.create_window(0, 0, window=self.body, anchor="nw")
        self._build(self.body)
        self._columns(False)
        self._scroll.bind("<Configure>", lambda e: self._fit_body())
        self.body.bind("<Configure>", lambda e: self._fit_body())
        self.root.bind_all("<MouseWheel>", self._wheel)
        self.root.bind_all("<Button-4>", self._wheel)
        self.root.bind_all("<Button-5>", self._wheel)
        if keep:
            for name, value in keep.items():
                getattr(self, name).set(value)
            self._toggle_adv()
            self.timeout_box.state(["disabled"] if self.wait.get() else ["!disabled"])
        self._redraw()

    def _columns(self, wide):
        if wide == self._wide:
            return
        self._wide = wide
        b = self.body
        for c in (self.colA, self.colB):
            c.grid_forget()
        for i in range(2):
            b.columnconfigure(i, weight=0, minsize=0)
            b.rowconfigure(i, weight=0)
        if wide:
            self.colA.grid(row=0, column=0, sticky="nsew")
            self.colB.grid(row=0, column=1, sticky="new", padx=(12, 0))
            b.columnconfigure(0, weight=1)
            b.rowconfigure(0, weight=1)
        else:
            self.colA.grid(row=0, column=0, sticky="nsew")
            self.colB.grid(row=1, column=0, sticky="new")
            b.columnconfigure(0, weight=1)
            b.rowconfigure(0, weight=1)

    def _wide_width(self):
        """The window's inner width from which both columns fit side by side"""
        return self.colA.winfo_reqwidth() + self.colB.winfo_reqwidth() + 12

    def _fit_body(self):
        """The body as wide as the window and at least as high; lower than its contents: scrolling.
        Wide enough for both columns: side by side."""
        c = self._scroll
        w, h = c.winfo_width(), c.winfo_height()
        if w < 2 or h < 2:
            return
        self._columns(w >= self._wide_width())
        self.body.update_idletasks()
        need = self.body.winfo_reqheight()
        size = (w, max(h, need))
        if size != getattr(self, "_body_size", None):
            self._body_size = size
            c.itemconfigure(self._body_id, width=size[0], height=size[1])
            c.configure(scrollregion=(0, 0, size[0], size[1]))
        scroll = need > h + 1
        if scroll and not self._sbar.winfo_ismapped():
            self._sbar.pack(side="right", fill="y")
        elif not scroll and self._sbar.winfo_ismapped():
            self._sbar.pack_forget()
            c.yview_moveto(0)

    def _wheel(self, ev):
        """The mouse wheel scrolls the main window (not a list or a text of another window)"""
        try:
            if ev.widget.winfo_toplevel() is not self.root or not self._sbar.winfo_ismapped():
                return
            if isinstance(ev.widget, (ttk.Combobox, ttk.Spinbox, tk.Text, tk.Listbox)):
                return
        except (AttributeError, tk.TclError):
            return
        if getattr(ev, "num", 0) in (4, 5):
            step = -1 if ev.num == 4 else 1
        else:
            step = -1 if ev.delta > 0 else 1
        self._scroll.yview_scroll(step * 3, "units")

    def switch_theme(self, name):
        if name == _theme_name() or self.busy:
            self.theme_var.set(t(THEME_NAMES[_theme_name()]))
            return
        i18n.set_setting("theme", name)
        _theme(self.root)
        self._rebuild()

    def switch_lang(self, code):
        """The window again in the other language, with everything set so far"""
        if code == i18n.lang() or self.busy:
            self.lang_var.set(i18n.LANGS[i18n.lang()])
            return
        i18n.set_lang(code)
        self._rebuild()

    def _rebuild(self):
        keep = {n: getattr(self, n).get() for n in ("timeout", "data_mb", "data_mode", "show_adv", "wait", "status")}
        xiegu = {k: v.get() for k, v in self.xiegu_vars.items()}
        card = self.card_box.current()
        self.top.destroy()
        self.panel.destroy()
        self._head.destroy()
        self._build_all(keep)
        for k, v in xiegu.items():
            self.xiegu_vars[k].set(v)
        self._redraw()
        self.refresh_cards()
        if 0 <= card < len(self.cards):
            self.card_box.current(card)

    def _build(self, top):
        pad = {"padx": 8, "pady": 4}

        head = tk.Frame(self.root, bg=HEAD_BG)
        head.pack(fill="x", before=self.top)
        self._head = head
        inner = tk.Frame(head, bg=HEAD_BG)
        inner.pack(fill="x", padx=16, pady=6)
        icon = _icon_image(self.root, 48)
        if icon is not None:
            tk.Label(inner, image=icon, bg=HEAD_BG).pack(side="left", padx=(0, 12))
        titles = tk.Frame(inner, bg=HEAD_BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text=APP + (" " + app_version() if app_version() else ""), bg=HEAD_BG, fg=HEAD_FG, font=_font(18, "bold")).pack(anchor="w")
        tk.Label(titles, text=t("Kilka systemów na jednej karcie SD dla Xiegu X6100: przy włączaniu radia menu na "
                                "ekranie, wybór klawiszem F1–F5."), bg=HEAD_BG, fg=HEAD_SUB,
                 font=_font(10), wraplength=560, justify="left").pack(anchor="w")
        side = tk.Frame(inner, bg=HEAD_BG)
        side.pack(side="right", anchor="n")
        self.lang_var = tk.StringVar(value=i18n.LANGS[i18n.lang()])
        pick = tk.Frame(side, bg=HEAD_BG)
        pick.pack(anchor="e")
        langs = ttk.Combobox(pick, textvariable=self.lang_var, values=list(i18n.LANGS.values()),
                             state="readonly", width=8)
        langs.pack(side="right")
        langs.bind("<<ComboboxSelected>>", lambda e: self.switch_lang(
            next(k for k, v in i18n.LANGS.items() if v == self.lang_var.get())))
        self.theme_var = tk.StringVar(value=t(THEME_NAMES[_theme_name()]))
        themes = ttk.Combobox(pick, textvariable=self.theme_var, values=[t(v) for v in THEME_NAMES.values()],
                              state="readonly", width=8)
        themes.pack(side="right", padx=(0, 8))
        themes.bind("<<ComboboxSelected>>", lambda e: self.switch_theme(
            next(k for k, v in THEME_NAMES.items() if t(v) == self.theme_var.get())))
        author = tk.Label(side, text=t("aplikacja: SQ6RT"), bg=HEAD_BG, fg=LINK, cursor="hand2",
                          font=_font(10, "underline"))
        author.pack(anchor="e", pady=(6, 0))
        author.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_URL))
        tk.Frame(head, bg=ACCENT, height=3).pack(fill="x", side="bottom")

        # Two columns side by side on a wide window (the menu left, the settings and the writing right:
        # everything in sight), one under the other on a narrow one; _fit_body chooses
        self.colA, self.colB = ttk.Frame(top), ttk.Frame(top)
        self._wide = None
        box = self._section(self.colA, 1, t("Menu na ekranie radia"), expand=True)
        btns = ttk.Frame(box)
        btns.pack(side="right", fill="y", padx=(12, 2), pady=2)
        for text, cmd, colour in (("+ Z internetu…", self.add_online, "blue"), ("+ Obraz karty…", self.add_image, "teal"),
                                  ("+ Xiegu z eMMC", self.add_xiegu, "orange")):
            ColorButton(btns, t(text), colour, cmd, width=17).pack(fill="x", pady=4)
        self._build_extras(btns)
        left = ttk.Frame(box)
        left.pack(side="left", fill="both", expand=True)
        self.sw, self.sh, self.sox, self.soy = SCREEN_W, SCREEN_H, 0, 0
        self.screen = tk.Canvas(left, width=SCREEN_W * 5 // 8, height=SCREEN_H * 5 // 8, bg=PAGE_BG, highlightthickness=0,
                                cursor="hand2")
        self.screen.pack(side="top", fill="both", expand=True)
        self.screen.bind("<Configure>", self._screen_resized)
        self.screen.bind("<Button-1>", self._screen_click)
        self.screen.bind("<Double-1>", lambda e: (self._screen_click(e), self.rename()))
        self.info = ttk.Label(left, text="", foreground=HINT, wraplength=SCREEN_W * 5 // 8, justify="left")
        tools = ttk.Frame(left)
        tools.pack(side="bottom", fill="x", pady=(6, 0))
        self.info.pack(side="bottom", anchor="w", pady=(6, 0))
        self.screen.pack_forget()
        self.screen.pack(side="top", fill="both", expand=True)
        self.tile_tools = []
        for text, cmd in (("←", lambda: self.move(-1)), ("→", lambda: self.move(1)),
                          ("★  " + t("Domyślny"), self.set_default), ("✎  " + t("Zmień nazwę"), self.rename),
                          ("▣  " + t("Logo…"), self.choose_logo)):
            b_ = ttk.Button(tools, text=text, command=cmd, width=3 if len(text) == 1 else 0)
            b_.pack(side="left", padx=(0, 6))
            self.tile_tools.append(b_)
        b_ = ttk.Button(tools, text="✕  " + t("Usuń"), command=self.remove)
        b_.pack(side="left", padx=(12, 0))
        self.tile_tools.append(b_)
        self.selected = None


        opts = self._section(self.colB, 2, t("Ustawienia menu"))
        ttk.Label(opts, text=t("Czas na wybór (s):")).grid(row=0, column=0, sticky="w", **pad)
        self.timeout = tk.StringVar(value="5")
        self.timeout.trace_add("write", lambda *a: self._render() if hasattr(self, "screen") else None)
        self.timeout_box = ttk.Spinbox(opts, from_=0, to=MAX_SECS, textvariable=self.timeout, width=6)
        self.timeout_box.grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text=t("DATA w pliku .img (MB):")).grid(row=0, column=2, sticky="w", **pad)
        self.data_mb = tk.StringVar(value="1024")
        ttk.Spinbox(opts, from_=128, to=32768, increment=128, textvariable=self.data_mb, width=8).grid(
            row=0, column=3, sticky="w")
        ttk.Label(opts, text=t("(na karcie DATA zajmuje całe wolne miejsce)"), foreground=HINT).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=8)
        ttk.Label(opts, text=t("Partycja DATA:")).grid(row=2, column=0, sticky="nw", **pad)
        self.data_mode = tk.StringVar(value="separate")      # each system its own settings
        dm = ttk.Frame(opts)
        dm.grid(row=2, column=1, columnspan=3, sticky="w", pady=(2, 0))
        ttk.Radiobutton(dm, text=t("osobna dla każdego systemu (zalecane)"), value="separate",
                        variable=self.data_mode).pack(anchor="w")
        ttk.Radiobutton(dm, text=t("wspólna dla wszystkich systemów"), value="shared",
                        variable=self.data_mode).pack(anchor="w")
        self.wait = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text=t("Bez automatycznego startu (czekaj na klawisz F)"), variable=self.wait,
                        command=self._wait_changed).grid(row=3, column=0, columnspan=4, sticky="w", **pad)
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text=t("Zaawansowane: start systemu Xiegu z eMMC"), variable=self.show_adv,
                        command=self._toggle_adv).grid(row=4, column=0, columnspan=4, sticky="w", **pad)
        self.adv = ttk.Frame(opts)
        self.xiegu_vars = {}
        labels = {"xiegu_dev": "Urządzenie mmc", "xiegu_part": "Partycja", "xiegu_kernel": "Jądro",
                  "xiegu_fdt": "Plik .dtb", "xiegu_args": "bootargs"}
        for i, (k, v) in enumerate(XIEGU_DEFAULTS.items()):
            ttk.Label(self.adv, text=(t(labels[k]) if k != "xiegu_args" else labels[k]) + ":").grid(row=i, column=0, sticky="w", padx=8, pady=1)
            var = tk.StringVar(value=v)
            ttk.Entry(self.adv, textvariable=var, width=52 if k == "xiegu_args" else 24).grid(
                row=i, column=1, sticky="w", pady=1)
            self.xiegu_vars[k] = var

        out = self._section(self.colB, 3, t("Zapis karty"))
        ttk.Label(out, text=t("Karta SD:")).grid(row=0, column=0, sticky="w", **pad)
        self.card = tk.StringVar()
        self.card_box = ttk.Combobox(out, textvariable=self.card, state="readonly", width=30)
        self.card_box.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(out, text=t("Odśwież"), command=self.refresh_cards).grid(row=0, column=2, **pad)
        out.columnconfigure(1, weight=1)
        # The settings of the card in the reader (its DATA partition) onto the new one
        self.keep_data = tk.BooleanVar(value=True)
        self.keep_box = ttk.Checkbutton(out, variable=self.keep_data, text="")
        self.keep_box.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))
        self.check_card = tk.BooleanVar(value=getattr(self, "_check_card", True))
        ttk.Checkbutton(out, variable=self.check_card, text=t("Sprawdź kartę po zapisie (zalecane)"),
                        command=lambda: setattr(self, "_check_card", self.check_card.get())).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 2))
        b = ttk.Frame(out)
        b.grid(row=3, column=0, columnspan=3, sticky="we", padx=8, pady=(6, 8))
        self.btn_card = ColorButton(b, "⬇  " + t("Wgraj na kartę"), "green", self.write_card, font=_font(14, "bold"),
                                    padx=26, pady=12)
        self.btn_card.pack(side="right", fill="x", expand=True, padx=(8, 0))
        self.btn_img = ColorButton(b, t("Zapisz jako plik .img…"), "slate", self.save_image, font=_font(12, "bold"),
                                   padx=18, pady=12)
        self.btn_img.pack(side="right")
        # The settings' copies (DATA), at the very bottom: of the card in the reader, of each system
        # on it, and an own copy for the new card
        cop = self._section(self.colB, 4, t("Kopie ustawień (DATA)"))
        buttons = ((t("Kopie DATA karty w czytniku…"), "teal", self.card_data,
                    t("zrób kopię ustawień na komputerze albo przywróć je na kartę; osobno dla każdego systemu")),
                   (t("Własna kopia DATA dla nowej karty…"), "blue", self.choose_copy,
                    t("wskaż kopię (plik .zip albo folder), która trafi na nowo zapisywaną kartę")))
        for k, (text, colour, cmd, hint) in enumerate(buttons):
            btn = ColorButton(cop, text, colour, cmd, font=_font(11, "bold"), padx=10, pady=11)
            btn.grid(row=1, column=k, sticky="we", padx=(8 if k == 0 else 4, 8 if k == 1 else 4), pady=(6, 2))
            ttk.Label(cop, text=hint, foreground=HINT, wraplength=300, justify="left").grid(
                row=2, column=k, sticky="nw", padx=(10 if k == 0 else 6, 8), pady=(0, 8))
            cop.columnconfigure(k, weight=1, uniform="copies")
        self.own_btn = btn
        own = ttk.Frame(cop)
        own.grid(row=3, column=0, columnspan=2, sticky="we", padx=8, pady=(0, 8))
        self.own_info = ttk.Label(own, text="", wraplength=520, justify="left")
        self.own_info.pack(side="left")
        self.own_clear = ttk.Button(own, text=t("Usuń wybór"), command=lambda: self._use_copy(None))


    def _section(self, top, number, title, expand=False):
        """A titled card: a round number badge, the title, the card the section's widgets go in"""
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(8, 3))
        c = tk.Canvas(row, width=24, height=24, highlightthickness=0, bg=PAGE_BG)
        c.create_oval(1, 1, 23, 23, fill=ACCENT, outline="")
        c.create_text(12, 12, text=str(number), fill=BADGE_FG, font=_font(11, "bold"))
        c.pack(side="left", padx=(2, 8))
        ttk.Label(row, text=title, font=_font(13, "bold")).pack(side="left")
        card = ttk.Frame(top, style="Card.TFrame", padding=(10, 6))
        card.pack(fill="both" if expand else "x", expand=expand)
        return card

    def _wait_changed(self):
        self.timeout_box.state(["disabled"] if self.wait.get() else ["!disabled"])
        self._render()

    def _toggle_adv(self):
        if self.show_adv.get():
            self.adv.grid(row=5, column=0, columnspan=4, sticky="w", pady=(0, 6))
        else:
            self.adv.grid_forget()

    # ---------------------------------------------------------------- the screen
    def _redraw(self, select=None):
        if select is not None:
            self.selected = select
        if self.selected is not None and not 0 <= self.selected < len(self.entries):
            self.selected = len(self.entries) - 1 if self.entries else None
        if self.selected is None and self.entries:
            self.selected = 0
        self._render()
        self._show_info()
        if hasattr(self, "btn_card"):
            self._actions()

    def _entry_info(self, e):
        if e["kind"] == "xiegu":
            return t("system Xiegu z pamięci wewnętrznej radia (nic tam nie jest zmieniane)")
        if e["kind"] == "doom":
            donor = next((x for x in self.entries if x["kind"] == "sd"), None)
            return (t("klasyczny Doom (Freedoom); jądro i parowania Bluetooth z: {name}", name=donor["name"])
                    if donor else t("klasyczny Doom (Freedoom), z jądrem pierwszego systemu z obrazu na liście"))
        info = e["sys"].summary()
        if e["sys"].warnings:
            info += "  ⚠ " + "; ".join(e["sys"].warnings)
        return info

    def _show_info(self):
        i = self.selected
        if i is None:
            self.info.configure(text=t("Kliknij kafelek, żeby go zaznaczyć; dwuklik zmienia nazwę."))
            return
        e = self.entries[i]
        text = "F%d  %s%s  ·  %s" % (i + 1, e["name"], "  ★" if i == self.default else "", self._entry_info(e))
        if e.get("logo"):
            text += "  ·  logo: " + os.path.basename(e["logo"])
        self.info.configure(text=text)

    def _tile_key(self, e):
        return (e["kind"], e["name"], e.get("logo"))

    def _tile(self, e):
        """What the radio shows for an entry; the project's logo is fetched in the background once"""
        key = self._tile_key(e)
        if key in self.tiles:
            return self.tiles[key]
        if key not in self._tile_jobs:
            self._tile_jobs.add(key)
            threading.Thread(target=self._tile_job, args=(dict(e), key), daemon=True).start()
        return {"name": e["name"], "logo": e.get("logo") or (DOOM_LOGO if e["kind"] == "doom" else None)}

    def _tile_job(self, e, key):
        from .compose import tile
        try:
            self.q.put(("tile", key, tile(e)))
        except Exception:
            self.q.put(("tile", key, {"name": e["name"], "logo": None}))

    def _screen_resized(self, ev):
        """The radio's 5:3 screen as large as the room allows, centred"""
        w, h = max(ev.width, 200), max(ev.height, 120)
        sw = min(w, h * 5 // 3)
        sh = sw * 3 // 5
        if (sw, sh) != (self.sw, self.sh) or (self.sox, self.soy) != ((w - sw) // 2, 0):
            self.sw, self.sh, self.sox, self.soy = sw, sh, (w - sw) // 2, 0
            self.info.configure(wraplength=max(300, w - 10))
            self._render()

    def _render(self):
        from . import menu_gfx
        c = self.screen
        c.delete("all")
        SCREEN_W, SCREEN_H = self.sw, self.sh
        sx, sy = SCREEN_W / menu_gfx.W, SCREEN_H / menu_gfx.H
        c.create_rectangle(self.sox - 2, self.soy, self.sox + SCREEN_W + 1, self.soy + SCREEN_H + 2,
                           fill="#000000", outline="#3a3a3a", width=2)
        if menu_gfx.HAVE_PIL:
            from PIL import Image
            img = menu_gfx.render_menu([self._tile(e) for e in self.entries],
                                       None if self.wait.get() else min(self.default, max(len(self.entries) - 1, 0)))
            self._screen_img = self._photo(img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS))
            c.create_image(self.sox, self.soy + 1, image=self._screen_img, anchor="nw")
        else:                               # no Pillow (running from source): names in boxes
            for i, e in enumerate(self.entries):
                cx = (menu_gfx.COL_W * i + menu_gfx.COL_W // 2) * sx
                c.create_rectangle(cx - 72 * sx, 76 * sy, cx + 72 * sx, 372 * sy, outline="#3a4560", width=2,
                                   tags="over")
                c.create_text(cx, 220 * sy, text=e["name"], fill="#ffffff", width=130 * sx, tags="over")
                c.create_text(cx, 435 * sy, text="F%d" % (i + 1), fill="#ffffff", font=_font(14, "bold"),
                              tags="over")
        if self.entries:                    # what U-Boot writes in the second row, in its 16x32 font
            try:
                secs = max(0, min(MAX_SECS, int(float(self.timeout.get().replace(",", ".")))))
            except (ValueError, AttributeError):
                secs = 5
            from .compose import COUNTDOWN, WAITING
            if self.wait.get():
                text = t(WAITING).format(n=len(self.entries))
            else:
                text = t(COUNTDOWN).replace("${bm_default}", str(self.default + 1)).replace("${bm_left}", str(secs))
            c.create_text(16 * sx, 48 * sy, text=text, anchor="w", fill="#d0d0d0", tags="over",
                          font=("Courier", max(9, int(19 * sy)), "bold"))
        if not self.entries:
            c.create_text(SCREEN_W // 2, SCREEN_H // 2, fill="#9aa3ad", width=SCREEN_W - 80, justify="center",
                          tags="over", font=_font(13), text=t("Tu zobaczysz menu dokładnie tak, jak pokaże je radio. Zacznij od "
                                                 "„+ Z internetu…”: wybierz system, a aplikacja sama go pobierze."))
        if self.selected is not None:
            cx = menu_gfx.COL_W * self.selected + menu_gfx.COL_W // 2
            c.create_rectangle((cx - 78) * sx, 70 * sy, (cx + 78) * sx, 472 * sy, outline=ACCENT, width=3,
                               dash=(6, 4), tags="over")
        c.move("over", self.sox, self.soy + 1)

    def _screen_click(self, ev):
        from . import menu_gfx
        if not (self.soy <= ev.y <= self.soy + self.sh):
            return
        i = int((ev.x - self.sox) / (self.sw / menu_gfx.W) // menu_gfx.COL_W) if ev.x >= self.sox else -1
        if 0 <= i < len(self.entries):
            self.selected = i
            self._render()
            self._show_info()

    def _photo(self, pil_img):
        import base64
        import io
        buf = io.BytesIO()
        pil_img.save(buf, "PNG")
        return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))

    def _sel(self):
        return self.selected

    def add_image(self):
        if self.busy:
            return
        if len(self.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES))
            return
        path = filedialog.askopenfilename(title=t("Obraz karty systemu (.img, .img.zip, .img.xz)"),
                                          **_filetypes([(t("Obrazy kart"), "*.img *.zip *.xz")]))
        if not path:
            return
        self._job(t("Analiza obrazu"), self._analyse, path, steps=["unzip"])

    def _analyse(self, path, name=None):
        def unzip(done, total):
            self.q.put(("progress", "unzip", done, total, ""))
        raw = open_source(path, cache_dir(), unzip)
        s = SourceSystem(path, raw)
        if name:
            s.name = name
        return ("added", s)

    def add_online(self):
        if self.busy:
            return
        if len(self.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES))
            return
        self._single("online", lambda: OnlineDialog(self))

    def _fetch_and_add(self, source, rel):
        from . import catalog

        def prog(done, total):
            self.q.put(("progress", "download", done, total, rel["asset"]))
        path = catalog.download(source, rel, cache_dir(), prog)
        return self._analyse(path, catalog.label(source, rel))

    def _build_extras(self, col):
        """Extras: Doom, the easter egg (a tile of its own, not among the systems to fetch)"""
        ttk.Separator(col).pack(fill="x", pady=(10, 6))
        ttk.Label(col, text="★  Extras", font=_font(11, "bold")).pack(anchor="w", pady=(0, 4))
        self._doom_img = None
        try:
            from . import menu_gfx
            if menu_gfx.HAVE_PIL:
                c = BTN["doom"][0]
                self._doom_img = self._photo(menu_gfx.load_logo(
                    DOOM_LOGO, size=40, bg=tuple(int(c[k:k + 2], 16) for k in (1, 3, 5))))
        except Exception:
            self._doom_img = None
        ColorButton(col, "+ Doom", "doom", self.add_doom, image=self._doom_img, font=_font(13, "bold"),
                    pady=6).pack(fill="x")
        ColorButton(col, "⚠  " + t("Przeczytaj najpierw"), "red", self.doom_readme,
                    font=_font(12, "bold")).pack(fill="x", pady=(8, 0))

    def add_doom(self):
        if any(e["kind"] == "doom" for e in self.entries):
            return
        if len(self.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES))
            return
        if not any(e["kind"] == "sd" for e in self.entries):
            messagebox.showinfo(APP, t("Doom uruchamia się z jądrem systemu z obrazu (np. OpenX6X00). "
                                       "Dodaj najpierw taki system, potem Dooma."))
            return
        self.entries.append({"kind": "doom", "name": DOOM_NAME})
        self._redraw(len(self.entries) - 1)

    def doom_readme(self):
        old = getattr(self, "_readme", None)
        try:
            if old is not None and old.winfo_exists():
                old.lift()
                old.focus_force()
                return
        except tk.TclError:
            pass
        win = self._readme = tk.Toplevel(self.root)
        win.title(t("Doom: przeczytaj najpierw"))
        win.transient(self.root)
        txt = tk.Text(win, wrap="word", width=96, height=34, padx=16, pady=12, relief="flat",
                      font=_font(11), bg=PAGE_BG, fg=TEXT_FG, highlightthickness=0,
                      insertbackground=TEXT_FG)
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        body = i18n.DOOM_README[i18n.lang()]
        title, rest = body.split("\n", 1)
        txt.insert("end", title + "\n", "h1")
        lines = rest.split("\n")
        for k, line in enumerate(lines):
            heading = line and not line.startswith(" ") and k + 1 < len(lines) and lines[k + 1].startswith(" ")
            txt.insert("end", line + "\n", "h2" if heading else ())
        txt.tag_configure("h1", font=_font(16, "bold"), foreground=H1)
        txt.tag_configure("h2", font=_font(12, "bold"), foreground=H2, spacing1=8)
        txt.configure(state="disabled")
        ttk.Button(win, text="OK", command=win.destroy, style="Accent.TButton", width=12).pack(side="bottom", pady=10)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

    def add_xiegu(self):
        if any(e["kind"] == "xiegu" for e in self.entries):
            return
        if len(self.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES))
            return
        self.entries.append({"kind": "xiegu", "name": "Xiegu (eMMC)"})
        self._redraw(len(self.entries) - 1)

    def rename(self):
        i = self._sel()
        if i is None:
            return
        n = simpledialog.askstring(APP, t("Nazwa w menu (litery bez polskich znaków, do 28):"),
                                   initialvalue=self.entries[i]["name"], parent=self.root)
        if n:
            self.entries[i]["name"] = n.strip()[:28]
            self._redraw(i)

    def move(self, d):
        i = self._sel()
        if i is None or not 0 <= i + d < len(self.entries):
            return
        e = self.entries
        e[i], e[i + d] = e[i + d], e[i]
        if self.default == i:
            self.default = i + d
        elif self.default == i + d:
            self.default = i
        self._redraw(i + d)

    def set_default(self):
        i = self._sel()
        if i is not None:
            self.default = i
            self._redraw(i)

    def remove(self):
        i = self._sel()
        if i is None:
            return
        del self.entries[i]
        if self.default >= len(self.entries) or self.default == i:
            self.default = 0
        elif self.default > i:
            self.default -= 1
        self._redraw()

    def choose_logo(self):
        i = self._sel()
        if i is None:
            messagebox.showinfo(APP, t("Zaznacz system na liście, potem Logo…"))
            return
        path = filedialog.askopenfilename(title=t("Logo dla {name}", name=self.entries[i]["name"]),
                                          **_filetypes([(t("Obrazki"), "*.png *.jpg *.jpeg *.bmp *.gif")]))
        if not path:
            return
        try:
            from . import menu_gfx
            menu_gfx.load_logo(path)
        except Exception as e:
            messagebox.showerror(APP, t("Nie da się wczytać obrazka: {e}", e=e))
            return
        self.entries[i]["logo"] = path
        self._redraw(i)

    # ---------------------------------------------------------------- cards
    def refresh_cards(self):
        try:
            self.cards = devices.list_cards()
        except Exception as e:
            self.cards = []
            self.status.set(t("Nie udało się odczytać listy kart: {e}", e=e))
        self._find_data()
        vals = [f"{c['name']}  —  {_gb(c['size'])}  ({c['path']})" for c in self.cards]
        self.card_box["values"] = vals
        if vals:
            self.card_box.current(0)
        else:
            self.card.set("")
            self.card_box.set(t("brak karty SD — włóż kartę i kliknij Odśwież"))

    def _find_data(self):
        """The DATA partition of a card in the reader, mounted by the computer"""

        try:
            vols = backup.find_data_volumes()
        except Exception:
            vols = []
        self.data_vol = vols[0]["path"] if vols else None
        if self.data_src and not os.path.exists(self.data_src):
            self.data_src = None
        if self.data_src:
            self.keep_box.configure(text=t("Wgraj ustawienia z własnej kopii: {p}", p=os.path.basename(
                self.data_src.rstrip("/\\")) or self.data_src), state="normal")
        else:
            self.keep_box.configure(text=t("Przenieś ustawienia ze starej karty (każdego systemu osobno)"),
                                    state="normal")
        if hasattr(self, "own_info"):
            self._show_own()

    def choose_copy(self):
        """The user's own copy of DATA for the new card: a backup .zip or a folder with the files"""
        self._single("picker", lambda: CopyPicker(
            self, t("Własna kopia DATA"), t("Ta kopia zostanie wgrana na nową kartę przy „Wgraj na kartę” albo "
                                            "„Zapisz jako plik .img…”."),
            t("Użyj tej kopii"), self._use_copy, start=self.data_src))

    def _use_copy(self, path):
        self.data_src = path
        if path:
            self.keep_data.set(True)
        self._find_data()

    def _show_own(self):
        """The standing line in section 4: which own copy is chosen, where it is, what is in it"""
        if not self.data_src:
            self.own_info.configure(text=t("Własna kopia dla nowej karty: nie wybrano."), foreground=HINT)
            self.own_clear.pack_forget()
            return
        try:
            d = backup.describe(self.data_src)
            text = t("Własna kopia dla nowej karty: {p}  ·  {n} plików, {mb} MB", p=self.data_src, n=d["files"],
                     mb="%.1f" % (d["bytes"] / 2**20))
            if not d["data"]:
                text += "\n⚠ " + t("To nie wygląda na DATA z radia (brak bazy ustawień). Sprawdź, czy to właściwa kopia.")
            self.own_info.configure(text=text, foreground=WARN if not d["data"] else TEXT_FG)
        except Exception as e:
            self.own_info.configure(text=t("Nie da się odczytać kopii: {e}", e=e), foreground=WARN)
        self.own_clear.pack(side="right", padx=(8, 0))

    def _card_in_reader(self):
        """The card in the reader: the one chosen in the list, else the one whose DATA the computer
        has mounted (a card the list does not show); None when there is neither"""
        idx = self.card_box.current()
        if 0 <= idx < len(self.cards):
            return self.cards[idx]
        if self.data_vol:
            dev = devices.device_of(self.data_vol)
            if dev:
                return {"path": dev, "name": "DATA", "size": 0, "mounts": [self.data_vol]}
        return None

    def _single(self, key, make):
        """One window of a kind at a time: asked for again, the open one comes to the front"""
        wins = self.__dict__.setdefault("_wins", {})
        w = wins.get(key)
        try:
            if w is not None and w.win.winfo_exists():
                w.win.deiconify()
                w.win.lift()
                w.win.focus_force()
                return w
        except tk.TclError:
            pass
        wins[key] = make()
        return wins[key]

    def card_data(self):
        """The DATA of the card in the reader: saved to the computer and put back, each system's own"""
        if self.busy:
            return
        self._find_data()
        card = self._card_in_reader()
        if card is None and not self.data_vol:
            messagebox.showinfo(APP, t("Nie widać karty ani partycji DATA. Włóż kartę z radia do czytnika, poczekaj, "
                                       "aż komputer ją pokaże, i kliknij Odśwież."))
            return
        self._single("card_data", lambda: CardDataDialog(self, card))

    def _card_request(self, req, progress=None):
        """A cardata request: here when the app may read the card itself, else through the helper
        with administrator rights"""
        from . import cardata
        if devices.is_admin() or devices.MAC or os.path.isfile(req["dev"]):
            return cardata.run(req, progress)
        tmp = tempfile.mkdtemp(prefix="x6100mb-")
        try:
            os.chmod(tmp, 0o777)
            rq, rs = os.path.join(tmp, "request.json"), os.path.join(tmp, "result.json")
            with open(rq, "w") as f:
                json.dump(req, f)
            os.chmod(rq, 0o666)
            proc = devices.run_elevated(["card-data", rq, rs])
            started = time.time()
            while not os.path.exists(rs):
                time.sleep(0.3)
                if proc is not None and proc.poll() is not None:
                    time.sleep(0.5)
                    if not os.path.exists(rs):
                        raise RuntimeError(t("Odczyt karty przerwany (odmowa uprawnień administratora?)"))
                if proc is None and time.time() - started > 600:
                    raise RuntimeError(t("Odczyt karty przerwany (odmowa uprawnień administratora?)"))
            with open(rs) as f:
                out = json.load(f)
            if "error" in out:
                raise RuntimeError(out["error"])
            return out["ok"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _take_data(self, tmp, card=None):
        """Before the card is erased: its settings copied aside and kept as .zip files on the computer.
        Returns (what compose takes as data_files, a line for the user about it), or (None, None).

        A card made here with a DATA per system: every system's DATA, each to the system of the same
        name (else of the same project) on the new card, wherever it now stands in the menu. Any other
        card: the DATA the computer shows, to the default system."""
        if not self.keep_data.get():
            return None, None
        if self.data_src:                         # the user's own copy goes before the old card's
            files = backup.from_copy(self.data_src, os.path.join(tmp, "DATA"))
            return files, t("Ustawienia: {n} plików wgranych na kartę; kopia: {zip}", n=len(files), zip=self.data_src)
        from . import cardata
        if card is not None:
            try:
                os.makedirs(backup.backups_dir(), exist_ok=True)
                areas = self._card_request({"op": "dump_all", "dev": card["path"], "dir": backup.backups_dir()},
                                           self._progress_cb)["areas"]
            except Exception:
                backup.log_error("settings of each system")
                areas = []
            areas = [a for a in areas if a.get("zip") and a.get("files")]
            if areas:
                new = [(i, e["name"]) for i, e in enumerate(self.entries) if e["kind"] == "sd"]
                hit = cardata.match(areas, [n for _i, n in new])
                data, lines = {}, []
                for k, a in hit.items():
                    i, name = new[k]
                    data[i] = backup.from_copy(a["zip"], os.path.join(tmp, "DATA%d" % i))
                    lines.append("  %s  ←  %s (%d)" % (name, " + ".join(a["names"]), len(data[i])))
                left = [a for a in areas if all(a is not h for h in hit.values())]
                text = t("Ustawienia przeniesione (nowy system ← stara karta, liczba plików):") + "\n" + "\n".join(lines) \
                    if lines else t("Żaden system ze starej karty nie ma odpowiednika na nowej: ustawień nie przeniesiono.")
                if left:
                    text += "\n" + t("Bez odpowiednika na nowej karcie (kopia została na komputerze): {names}",
                                     names=", ".join(" + ".join(a["names"]) for a in left))
                text += "\n" + t("Kopie: {dir}", dir=backup.backups_dir())
                return (data or None), text
        if not (self.data_vol and os.path.isdir(self.data_vol)):
            return None, None
        files = backup.snapshot(self.data_vol, os.path.join(tmp, "DATA"), self._progress_cb)
        zip_path = backup.save_zip(os.path.join(tmp, "DATA"))
        return files, t("Ustawienia: {n} plików wgranych na kartę; kopia: {zip}", n=len(files), zip=zip_path)

    # ---------------------------------------------------------------- building
    def _settings(self):
        try:
            timeout = max(0, min(MAX_SECS, int(float(self.timeout.get().replace(",", ".")))))
            data_mb = int(self.data_mb.get())
        except ValueError:
            raise ValueError(t("Czas i rozmiar DATA muszą być liczbami"))
        xiegu = {k: v.get().strip() for k, v in self.xiegu_vars.items()}
        return timeout, data_mb, xiegu

    def _plan(self, card_bytes=None, data_files=None, settings=None):
        """The card; settings (taken on Tk's thread) let a job build it in its own thread"""
        timeout, data_mb, xiegu, data_mode, wait = settings or self._all_settings()
        ents = resolve_extras([dict(e) for e in self.entries])
        return compose(ents, default=self.default, timeout_s=timeout, data_mb=data_mb, card_bytes=card_bytes,
                       xiegu=xiegu, data_mode=data_mode, wait=wait, data_files=data_files)

    def _all_settings(self):
        return self._settings() + (self.data_mode.get(), self.wait.get())

    def save_image(self):
        if self.busy:
            return
        try:
            plan = self._plan()
        except Exception as e:
            messagebox.showerror(APP, str(e))
            return
        path = filedialog.asksaveasfilename(title=t("Zapisz obraz karty"), defaultextension=".img",
                                            initialfile="X6100-multiboot.img",
                                            **({} if devices.MAC else {"filetypes": [(t("Obraz karty"), "*.img")]}))
        if not path:
            return
        self._job(t("Zapis obrazu"), self._save_job, plan, path, self._all_settings(), self._card_in_reader(),
                  steps=(["backup"] if self.keep_data.get() else []) + ["write", "verify"])

    def _save_job(self, plan, path, settings, card=None):
        tmp = tempfile.mkdtemp(prefix="x6100mb-data-")
        try:
            files, note = self._take_data(tmp, card)
            if files is not None:
                plan = self._plan(data_files=files, settings=settings)
            write_image_file(plan, path, Progress(self._progress_cb))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        msg = t("Zapisano {path} ({mb} MB). Można go wgrać balenaEtcherem.", path=path, mb=plan.size // 2**20)
        if note:
            msg += "\n\n" + note
        return ("msg", msg)

    def write_card(self):
        if self.busy:
            return
        idx = self.card_box.current()
        if idx < 0 or idx >= len(self.cards):
            messagebox.showwarning(APP, t("Nie wybrano karty SD."))
            return
        card = self.cards[idx]
        try:
            plan = self._plan(card_bytes=card["size"])
        except Exception as e:
            messagebox.showerror(APP, str(e))
            return
        lines = [f"{x['key']}  {x['name']}" for x in plan.info["entries"]]
        text = t("Karta: {card}\n\nWSZYSTKO na tej karcie zostanie usunięte.\n\nMenu:\n{lines}\n\nDATA: {mb} MB\n\nWgrać?",
                 card=f"{card['name']} {_gb(card['size'])} ({card['path']})", lines="\n".join(lines),
                 mb=plan.info["data_mb"])
        if self.keep_data.get() and self.data_src:
            text += "\n\n" + t("Ustawienia z własnej kopii ({p}) zostaną wgrane na nową kartę.", p=self.data_src)
        elif self.keep_data.get():
            text += "\n\n" + t("Ustawienia każdego systemu z tej karty zostaną najpierw skopiowane na komputer i "
                                "przeniesione do tego samego systemu na nowej karcie.")
        if not messagebox.askyesno(APP, text, icon="warning"):
            return
        inproc = devices.is_admin() or devices.MAC   # macOS: the app writes itself, through authopen
        self._skip.clear()
        self._skip_file = None
        self._job(t("Zapis na kartę") if inproc else t("Zapis na kartę (uprawnienia administratora)"),
                  self._card_job, plan, card, inproc, self._all_settings(), self.check_card.get(),
                  steps=(["backup"] if self.keep_data.get() else []) + ["prepare", "write", "sync"] +
                  (["verify"] if self.check_card.get() else []))
        self.panel.on_skip = self._skip_check

    def _skip_check(self):
        """The read-back of the card left off where it is (the button in the progress window)"""
        self._skip.set()
        if self._skip_file:
            try:
                open(self._skip_file, "w").close()
            except OSError:
                pass

    def _card_job(self, plan, card, inproc, settings, check=True):
        tmp = tempfile.mkdtemp(prefix="x6100mb-data-")
        os.chmod(tmp, 0o755)
        try:
            files, note = self._take_data(tmp, card)
            if files is not None:
                plan = self._plan(card_bytes=card["size"], data_files=files, settings=settings)
            for dirpath, _dirs, names in os.walk(tmp):       # the writer may run with other rights
                os.chmod(dirpath, 0o755)
                for f in names:
                    os.chmod(os.path.join(dirpath, f), 0o644)
            result = (self._card_job_inproc if inproc else self._card_job_elevated)(plan, card["path"], check)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if note:
            result = (result[0], result[1] + "\n\n" + note)
        return result

    def _ready(self, check):
        return t("Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia.") if check else \
            t("Karta zapisana (bez sprawdzenia). Wyjmij ją i włóż do radia.")

    def _card_job_inproc(self, plan, dev, check=True):
        checked = write_device(plan, dev, Progress(self._progress_cb), check=check, skip=self._skip.is_set)
        return ("msg", self._ready(checked))

    def _card_job_elevated(self, plan, dev, check=True):
        tmp = tempfile.mkdtemp(prefix="x6100mb-")
        try:
            plan_file = os.path.join(tmp, "plan.json")
            prog = os.path.join(tmp, "progress.json")
            plan.save(plan_file, os.path.join(tmp, "blobs"))
            # The elevated helper (another user on macOS/Linux) must read the plan and write progress
            for dirpath, _dirs, files in os.walk(tmp):
                os.chmod(dirpath, 0o777)
                for f in files:
                    os.chmod(os.path.join(dirpath, f), 0o666)
            self._skip_file = prog + ".skip"          # made when the read-back is to be skipped
            proc = devices.run_elevated(["write-plan", plan_file, dev, prog] + ([] if check else ["--no-verify"]))
            started = time.time()
            while True:
                time.sleep(0.3)
                st = None
                if os.path.exists(prog):
                    try:
                        with open(prog) as f:
                            st = json.load(f)
                    except (OSError, ValueError):
                        st = None
                if st:
                    if st["phase"] == "error":
                        raise RuntimeError(st["msg"])
                    if st["phase"] == "done":
                        return ("msg", self._ready(st.get("msg") != "unchecked"))
                    self.q.put(("progress", st["phase"], st["done"], st["total"], st.get("msg", "")))
                if proc is not None and proc.poll() is not None and not (st and st["phase"] == "done"):
                    time.sleep(0.5)
                    if os.path.exists(prog):
                        with open(prog) as f:
                            st = json.load(f)
                        if st["phase"] == "done":
                            return ("msg", self._ready(st.get("msg") != "unchecked"))
                        if st["phase"] == "error":
                            raise RuntimeError(st["msg"])
                    raise RuntimeError(t("Zapis przerwany (odmowa uprawnień administratora?)"))
                if proc is None and st is None and time.time() - started > 120:
                    raise RuntimeError(t("Program zapisujący nie wystartował (odmowa uprawnień?)"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------------------------------------------------------------- background jobs
    def _progress_cb(self, phase, done, total, msg=""):
        self.q.put(("progress", phase, done, total, msg))

    def _job(self, text, fn, *args, steps=None):
        """fn(*args) in a thread, its progress in the panel at the bottom; steps: the stages it goes
        through (their names in PHASES), for the "stage 2 of 4" line"""
        self.busy = True
        self._actions()
        self.panel.start(text, steps)

        def run():
            try:
                self.q.put(("result", fn(*args)))
            except Exception as e:
                log = backup.log_error(text)
                self.q.put(("error", str(e) + ("\n\n" + t("Szczegóły: {p}", p=log) if log else "")))

        threading.Thread(target=run, daemon=True).start()

    def _actions(self):
        """The buttons that need something to work on, on or off: writing needs a system in the menu
        and no job running; the tools under the screen need a tile"""
        ready = bool(self.entries) and not self.busy
        for b in (self.btn_card, self.btn_img):
            b.state(["!disabled"] if ready else ["disabled"])
        for b in getattr(self, "tile_tools", []):
            b.state(["!disabled"] if self.entries else ["disabled"])

    def _poll(self):
        """What the jobs' threads sent; whatever goes wrong with one message, the next poll still comes
        (else the window stayed "busy" for good)"""
        try:
            self._poll_once()
        except queue.Empty:
            pass
        except Exception:
            backup.log_error("poll")
        finally:
            self.root.after(100, self._poll)

    def _poll_once(self):
        while True:
            m = self.q.get_nowait()
            if m[0] == "call":                  # from a thread: Tk only on its own thread
                m[1](*m[2:])
            elif m[0] == "tile":
                self.tiles[m[1]] = m[2]
                self._render()
            elif m[0] == "progress":
                _, phase, done, total, msg = m
                if self.busy:
                    self.panel.update(phase, done, total, msg)
            elif m[0] in ("result", "error"):
                self.busy = False
                self._actions()
                if m[0] == "error":
                    self.panel.rest("✕  " + t("Nie udało się"), RED)
                    self.status.set(m[1].split("\n")[0])
                    messagebox.showerror(APP, m[1])
                elif m[1][0] == "added":
                    sy = m[1][1]
                    self.entries.append({"kind": "sd", "name": sy.name[:28], "sys": sy})
                    self._redraw(len(self.entries) - 1)
                    self.panel.rest("✓  " + t("Dodano {name}", name=sy.name), GREEN)
                    self.status.set(sy.summary() + "   ·   " + t("Dodaj kolejny system albo przejdź do „Zapis karty”."))
                else:
                    self.panel.rest("✓  " + t("Gotowe"), GREEN)
                    self.status.set(m[1][1].split("\n")[0])
                    messagebox.showinfo(APP, m[1][1])


class OnlineDialog:
    """The systems the app knows, each with its releases on GitHub: pick one, it is fetched and added"""

    def __init__(self, app):
        from . import catalog
        self.app, self.cat = app, catalog
        self.win = tk.Toplevel(app.root)
        self.win.title(t("Pobierz system z internetu"))
        self.win.transient(app.root)
        self.rels = {}
        f = ttk.Frame(self.win)
        f.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(f, text=t("Wybierz system i wersję. Najnowsza jest na górze listy."),
                  font=_font(12, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.vars, self.boxes = {}, {}
        for i, src in enumerate(catalog.SOURCES):
            r = i + 1
            ttk.Label(f, text=src["name"], font=_font(11, "bold")).grid(row=2 * r - 1, column=0, sticky="w")
            ttk.Label(f, text=t(src["about"]), foreground=HINT).grid(row=2 * r, column=0, columnspan=3, sticky="w", pady=(0, 8))
            v = tk.StringVar(value=t("sprawdzam…"))
            box = ttk.Combobox(f, textvariable=v, state="disabled", width=38)
            box.grid(row=2 * r - 1, column=1, sticky="w", padx=8)
            btn = ttk.Button(f, text=t("Dodaj"), state="disabled", command=lambda s=src: self.add(s))
            btn.grid(row=2 * r - 1, column=2, sticky="w")
            self.vars[src["id"]], self.boxes[src["id"]] = v, (box, btn)
            threading.Thread(target=self._load, args=(src,), daemon=True).start()
        ttk.Label(f, text=t("Obrazy pobierane są z wydań projektów na GitHubie. Lista wersji jest odświeżana "
                            "co 30 minut."), foreground=HINT, wraplength=560).grid(row=99, column=0, columnspan=4,
                                                                                  sticky="w", pady=(8, 0))
        # An optional GitHub token: 5000 questions an hour instead of 60 (for many tries in a row)
        tk_row = ttk.Frame(f)
        tk_row.grid(row=100, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(tk_row, text=t("Token GitHub (opcjonalnie):"), foreground=HINT).pack(side="left")
        self.token = tk.StringVar(value=i18n.setting("github_token") or "")
        ttk.Entry(tk_row, textvariable=self.token, show="•", width=30).pack(side="left", padx=6)
        ttk.Button(tk_row, text=t("Zapisz"), command=self._save_token).pack(side="left")
        ttk.Label(tk_row, text=t("podnosi limit GitHuba z 60 do 5000 zapytań na godzinę"),
                  foreground=HINT).pack(side="left", padx=(8, 0))

    def _save_token(self):
        i18n.set_setting("github_token", self.token.get().strip())
        messagebox.showinfo(APP, t("Token zapisany na tym komputerze.") if self.token.get().strip()
                            else t("Token usunięty."), parent=self.win)

    def _load(self, src):
        try:
            rels = self.cat.releases(src)
            err = None if rels else t("brak obrazów X6100 w wydaniach")
            since = self.cat.kept_since(src)
            if since and rels:
                rels[0] = dict(rels[0], kept=time.strftime("%H:%M", time.localtime(since)))
        except Exception as e:
            rels, err = [], str(e)
        self.app.q.put(("call", self._loaded, src, rels, err))

    def _loaded(self, src, rels, err):
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        box, btn = self.boxes[src["id"]]
        if err:
            self.vars[src["id"]].set(t("błąd: ") + err)
            return
        self.rels[src["id"]] = rels
        vals = ["%s  (%s%s, %d MB)" % (r["tag"], r["date"], ", test" if r["prerelease"] else "", r["size"] >> 20)
                for r in rels]
        box["values"] = vals
        box.state(["!disabled", "readonly"])
        stable = next((k for k, r in enumerate(rels) if not r["prerelease"]), 0)
        box.current(stable)
        if rels and rels[0].get("kept"):
            ttk.Label(box.master, text=t("lista z {t} (GitHub nie odpowiada)", t=rels[0]["kept"]),
                      foreground=WARN).grid(row=box.grid_info()["row"], column=3, sticky="w", padx=(8, 0))
        btn.state(["!disabled"])

    def add(self, src):
        if self.app.busy:
            return
        if len(self.app.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES), parent=self.win)
            return
        box, _ = self.boxes[src["id"]]
        rel = self.rels[src["id"]][box.current()]
        self.win.destroy()          # first: the progress window then comes up over the main window
        app, text = self.app, t("Pobieranie {name} {tag}", name=src["name"], tag=rel["tag"])
        app.root.after(50, lambda: app._job(text, app._fetch_and_add, src, rel, steps=["download", "unzip"]))


class CardDataDialog:
    """The DATA of the card in the reader: Save (a .zip on the computer) and Restore (from a .zip or
    a folder). A card made here: each system's own DATA, whichever of them ran last. Any other card
    (a system's own card, straight from its project), or one that cannot be read directly: the DATA
    the computer shows as a drive."""

    def __init__(self, app, card):
        self.app, self.card = app, card
        self.win = tk.Toplevel(app.root)
        self.win.title(t("Kopie DATA karty w czytniku"))
        self.win.transient(app.root)
        self.box = ttk.Frame(self.win)
        self.box.pack(fill="both", expand=True, padx=16, pady=14)
        head = t("Karta: {card}", card="%s  %s  (%s)" % (card["name"], _gb(card["size"]), card["path"])) if card \
            else t("Kopie DATA karty w czytniku")
        ttk.Label(self.box, text=head, font=_font(12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.note = ttk.Label(self.box, text=t("Czytam kartę…"), foreground=HINT, wraplength=640, justify="left")
        self.note.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        if card:
            threading.Thread(target=self._scan, daemon=True).start()
        else:
            self._scanned([], "no card")

    def _scan(self):
        try:
            areas, err = self.app._card_request({"op": "scan", "dev": self.card["path"]})["areas"], None
        except Exception as e:
            backup.log_error("card-data scan")
            areas, err = [], str(e)
        self.app.q.put(("call", self._scanned, areas, err))

    def _row(self, r, title, sub, dump, restore):
        ttk.Label(self.box, text=title, font=_font(11, "bold")).grid(row=2 + 2 * r, column=0, sticky="w", padx=(0, 18))
        ttk.Label(self.box, text=sub, foreground=HINT).grid(row=3 + 2 * r, column=0, sticky="w", pady=(0, 10))
        ColorButton(self.box, t("Kopia na komputer…"), "teal", dump, font=_font(11, "bold"), padx=14, pady=8).grid(
            row=2 + 2 * r, column=1, rowspan=2, padx=(0, 8), pady=(0, 8))
        ColorButton(self.box, t("Przywróć z kopii…"), "orange", restore, font=_font(11, "bold"), padx=14, pady=8).grid(
            row=2 + 2 * r, column=2, rowspan=2, pady=(0, 8))

    def _scanned(self, areas, err):
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        if err:
            # Not a card made here, or no direct access to it: the DATA the computer shows as a drive
            try:
                vols = backup.find_data_volumes()
            except Exception:
                vols = []
            if not vols:
                self.note.configure(text=t("Nie da się odczytać karty: {e}", e=err) if self.card else
                                    t("Nie widać partycji DATA."))
                return
            why = "" if not self.card else "\n" + t("Osobnych DATA systemów nie udało się odczytać z karty: {e}", e=err)
            self.note.configure(text=t("DATA tej karty, tak jak pokazuje ją komputer.") + why,
                                foreground=WARN if why else HINT)
            for r, v in enumerate(vols):
                self._row(r, "DATA  (%s)" % v["path"], t("partycja widoczna jako dysk"),
                          lambda v=v: self.dump_volume(v), lambda v=v: self.restore_volume(v))
            return
        self.note.configure(text=t("Każdy wiersz to osobna DATA. Kopia trafia do pliku .zip, przywracanie zastępuje "
                                   "jej zawartość plikami z wybranej kopii.") if len(areas) > 1 else
                            t("Ta karta ma jedną, wspólną DATA dla wszystkich systemów. Osobną DATA dla każdego systemu "
                              "ma karta zapisana z ustawieniem „Partycja DATA: osobna dla każdego systemu” (sekcja 2)."))
        if len(areas) > 1:
            ColorButton(self.box, t("Kopia wszystkich systemów na komputer"), "blue", self.dump_all,
                        font=_font(11, "bold"), padx=14, pady=8).grid(row=2 + 2 * len(areas), column=0, columnspan=3,
                                                                     sticky="we", pady=(6, 0))
        for r, a in enumerate(areas):
            who = "  ·  ".join("%s %s" % (k, n) for k, n in zip(a["keys"], a["names"]))
            self._row(r, who, "%d MB%s" % (a["sectors"] * 512 // 2**20, "  ·  " + t("ostatnio uruchomiony")
                                           if a["active"] and len(areas) > 1 else ""),
                      lambda a=a: self.dump(a), lambda a=a: self.restore(a))

    def _save_as(self, title, name):
        os.makedirs(backup.backups_dir(), exist_ok=True)
        return filedialog.asksaveasfilename(parent=self.win, title=title, initialdir=backup.backups_dir(),
                                            initialfile=name, defaultextension=".zip",
                                            **({} if devices.MAC else {"filetypes": [(t("Kopie DATA"), "*.zip")]}))

    def dump_volume(self, v):
        if self.app.busy:
            return
        path = self._save_as(t("Kopia DATA na komputer"), time.strftime("DATA-%Y-%m-%d_%H-%M.zip"))
        if not path:
            return

        def job():
            backup.save_zip(v["path"], path, self.app._progress_cb)
            return ("msg", t("Kopia ustawień zapisana:\n{path}", path=path))
        self.app._job(t("Kopia DATA na komputer"), job)

    def restore_volume(self, v):
        if self.app.busy:
            return
        app = self.app

        def go(path):
            def job():
                backup.clear_volume(v["path"])
                n = backup.restore_copy(path, v["path"], app._progress_cb)
                return ("msg", t("Przywrócono {n} plików na {vol}. Wysuń kartę bezpiecznie i włóż ją do radia.",
                                 n=n, vol=v["path"]))
            app._job(t("Przywróć DATA na kartę"), job)
        app._single("picker", lambda: CopyPicker(
            app, t("Przywróć DATA na kartę"),
            t("Kopia zostanie wgrana na kartę w czytniku: {vol}. Obecna zawartość tej DATA zostanie zastąpiona.",
              vol=v["path"]), t("Wgraj tę kopię na kartę"), go, parent=self.win))

    def _label(self, a):
        return " + ".join(a["names"])

    def dump_all(self):
        if self.app.busy:
            return
        app, dev = self.app, self.card["path"]
        os.makedirs(backup.backups_dir(), exist_ok=True)

        def job():
            areas = app._card_request({"op": "dump_all", "dev": dev, "dir": backup.backups_dir()}, app._progress_cb)["areas"]
            lines = ["  %s: %s" % (" + ".join(a["names"]), os.path.basename(a["zip"]) if a.get("zip") else
                                   t("nie da się odczytać")) for a in areas]
            return ("msg", t("Kopie DATA każdego systemu zapisane w\n{dir}", dir=backup.backups_dir()) + "\n\n" +
                    "\n".join(lines))
        app._job(t("Kopia wszystkich systemów na komputer"), job)

    def dump(self, a):
        if self.app.busy:
            return
        name = "DATA-%s-%s-%s.zip" % (a["keys"][0], "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in a["names"][0]),
                                      time.strftime("%Y-%m-%d_%H-%M"))
        path = self._save_as(t("Zrzut DATA: {name}", name=self._label(a)), name)
        if not path:
            return
        app, dev = self.app, self.card["path"]

        def job():
            n = app._card_request({"op": "dump", "dev": dev, "area": a, "zip": path}, app._progress_cb)["files"]
            return ("msg", t("DATA systemu {name}: {n} plików zapisanych w\n{path}", name=self._label(a), n=n, path=path))
        app._job(t("Zrzut DATA: {name}", name=self._label(a)), job)

    def restore(self, a):
        if self.app.busy:
            return
        app, dev = self.app, self.card["path"]

        def go(path):
            def job():
                # Windows keeps the DATA it shows as a drive to itself: that one through the drive
                vols = backup.find_data_volumes() if devices.WIN and a["active"] else []
                if vols:
                    backup.clear_volume(vols[0]["path"])       # replaced, as when the card is written directly
                    n = backup.restore_copy(path, vols[0]["path"], app._progress_cb)
                else:
                    n = app._card_request({"op": "restore", "dev": dev, "area": a, "zip": path}, app._progress_cb)["files"]
                return ("msg", t("DATA systemu {name}: przywrócono {n} plików. Wysuń kartę bezpiecznie i włóż ją do radia.",
                                 name=self._label(a), n=n))
            app._job(t("Przywracanie DATA: {name}", name=self._label(a)), job)
        app._single("picker", lambda: CopyPicker(
            app, t("Kopia DATA dla: {name}", name=self._label(a)),
            t("Obecna zawartość DATA systemu {name} zostanie zastąpiona tą kopią.", name=self._label(a)),
            t("Wgraj tę kopię na kartę"), go, parent=self.win, expect=a))


class CopyPicker:
    """Choosing a copy of DATA: a backup .zip or a folder with the files loose. Shows which one was
    chosen (its whole path), how much is in it and whether it looks like a radio's DATA; only the
    button at the bottom acts on it."""

    def __init__(self, app, title, note, ok_text, on_ok, start=None, parent=None, expect=None):
        self.app, self.on_ok, self.path = app, on_ok, None
        self.expect, self.other = expect, None       # the DATA area the copy is for (its systems)
        self.win = tk.Toplevel(parent or app.root)
        self.win.title(title)
        self.win.transient(parent or app.root)
        self.win.resizable(False, False)
        f = ttk.Frame(self.win, padding=(18, 14))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=title, font=_font(14, "bold")).pack(anchor="w")
        ttk.Label(f, text=note, foreground=HINT, wraplength=600, justify="left").pack(anchor="w", pady=(4, 10))
        row = ttk.Frame(f)
        row.pack(fill="x")
        ColorButton(row, t("Wybierz plik .zip…"), "blue", lambda: self.pick("zip"), font=_font(11, "bold"),
                    padx=14, pady=9).pack(side="left")
        ColorButton(row, t("Wybierz folder z plikami…"), "teal", lambda: self.pick("dir"), font=_font(11, "bold"),
                    padx=14, pady=9).pack(side="left", padx=(8, 0))
        box = ttk.Frame(f, style="Card.TFrame", padding=(12, 10))
        box.pack(fill="x", pady=(12, 12))
        ttk.Label(box, text=t("Wybrana kopia:"), foreground=HINT).pack(anchor="w")
        self.name = ttk.Label(box, text=t("nie wybrano"), font=_font(12, "bold"), wraplength=580, justify="left")
        self.name.pack(anchor="w")
        self.where = ttk.Label(box, text="", foreground=HINT, wraplength=580, justify="left")
        self.where.pack(anchor="w")
        self.what = ttk.Label(box, text="", wraplength=580, justify="left")
        self.what.pack(anchor="w", pady=(4, 0))
        bottom = ttk.Frame(f)
        bottom.pack(fill="x")
        self.ok = ColorButton(bottom, ok_text, "green", self.accept, font=_font(12, "bold"), padx=20, pady=10)
        self.ok.pack(side="right")
        ttk.Button(bottom, text=t("Anuluj"), command=self.win.destroy).pack(side="right", padx=(0, 8))
        self.ok.state(["disabled"])
        if start and os.path.exists(start):
            self.show(start)
        self.win.update_idletasks()
        r = app.root
        self.win.geometry("+%d+%d" % (max(r.winfo_rootx() + (r.winfo_width() - self.win.winfo_reqwidth()) // 2, 0),
                                      max(r.winfo_rooty() + 120, 0)))

    def pick(self, kind):
        start = backup.backups_dir() if os.path.isdir(backup.backups_dir()) else os.path.expanduser("~")
        if kind == "zip":
            path = filedialog.askopenfilename(parent=self.win, title=t("Kopia DATA (.zip)"), initialdir=start,
                                              **_filetypes([(t("Kopie DATA"), "*.zip")]))
        else:
            path = filedialog.askdirectory(parent=self.win, title=t("Folder z plikami DATA"), initialdir=start)
        if path:
            self.show(path)

    def show(self, path):
        self.path = None
        self.ok.state(["disabled"])
        self.name.configure(text=os.path.basename(path.rstrip("/\\")) or path)
        self.where.configure(text=path)
        try:
            d = backup.describe(path)
        except Exception as e:
            self.what.configure(text="✕ " + t("Nie da się odczytać kopii: {e}", e=e), foreground=WARN)
            return
        if not d["files"]:
            self.what.configure(text="✕ " + t("W tej kopii nie ma żadnych plików."), foreground=WARN)
            return
        text = t("{n} plików, {mb} MB", n=d["files"], mb="%.1f" % (d["bytes"] / 2**20)) + ":  " + ", ".join(d["names"]) + \
            (" …" if d["files"] > len(d["names"]) else "")
        self.other = None
        who = d.get("whose")
        if who and who.get("names"):
            text += "\n" + t("Kopia systemu: {name}", name=" + ".join(who["names"]))
            if self.expect and not (set(who.get("ids", [])) & set(self.expect.get("ids", [])) or
                                    set(who["names"]) & set(self.expect["names"])):
                self.other = " + ".join(who["names"])
                text += "\n⚠ " + t("To kopia innego systemu niż ten, do którego ją przywracasz ({name}).",
                                   name=" + ".join(self.expect["names"]))
        if d.get("inner"):
            text += "\n" + t("Pliki są w tej kopii w folderze „{f}”: na kartę trafi jego zawartość, bez tego folderu.",
                             f=d["inner"])
        if d["data"]:
            self.what.configure(text="✓ " + t("Wygląda na DATA z radia.") + "  " + text,
                                foreground=WARN if self.other else TEXT_FG)
        else:
            self.what.configure(text="⚠ " + t("To nie wygląda na DATA z radia (brak bazy ustawień). Sprawdź, czy to "
                                              "właściwa kopia.") + "\n" + text, foreground=WARN)
        self.path = path
        self.ok.state(["!disabled"])

    def accept(self):
        if not self.path:
            return
        path = self.path
        if self.other and not messagebox.askyesno(
                APP, t("To kopia systemu {a}, a przywracasz ją do systemu {b}. Wgrać mimo to?", a=self.other,
                       b=" + ".join(self.expect["names"])), icon="warning", parent=self.win):
            return
        try:
            if not backup.describe(path)["data"] and not messagebox.askyesno(
                    APP, t("Ta kopia nie wygląda na DATA z radia. Użyć jej mimo to?"), icon="warning", parent=self.win):
                return
        except Exception:
            return
        self.win.destroy()
        self.on_ok(path)


def _filetypes(types):
    """Tk on macOS crashes on some file filters (patterns with two dots, '*'): none there"""
    if devices.MAC:
        return {}
    return {"filetypes": types + [(t("Wszystkie pliki"), "*.*")]}


UI_FAMILY = None


def _font(size, *style):
    """The app's font, a size larger than Tk's small default (2 points up)"""
    fam = UI_FAMILY or ("Segoe UI" if devices.WIN else ("Helvetica Neue" if devices.MAC else "TkDefaultFont"))
    return (fam, size + 2) + style


def _setup_fonts(root):
    """The theme asks for "Segoe UI Variable", which Windows 10, macOS and Linux lack: Tk then fell
    back to a small, poor font. Each system's own good font instead, in the theme's named fonts too"""
    global UI_FAMILY
    import tkinter.font as tkfont
    have = set(tkfont.families(root))
    if devices.WIN:
        cands = ["Segoe UI Variable Text", "Segoe UI"]
    elif devices.MAC:
        cands = [tkfont.nametofont("TkDefaultFont").actual()["family"], "Helvetica Neue"]
    else:
        cands = ["Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"]
    UI_FAMILY = next((f for f in cands if f in have), tkfont.nametofont("TkDefaultFont").actual()["family"])
    sizes = {"TkDefaultFont": 12, "TkTextFont": 12, "TkMenuFont": 12, "TkHeadingFont": 12, "TkCaptionFont": 12,
             "SunValleyCaptionFont": 11, "SunValleyBodyFont": 12, "SunValleyBodyStrongFont": 12,
             "SunValleyBodyLargeFont": 14, "SunValleySubtitleFont": 16, "SunValleyTitleFont": 21}
    for name, size in sizes.items():
        try:
            f = tkfont.nametofont(name)
            f.configure(family=UI_FAMILY, size=size)
            if name in ("SunValleyBodyStrongFont", "SunValleySubtitleFont", "SunValleyTitleFont"):
                f.configure(weight="bold")
        except tk.TclError:
            pass


def _tree_bg():
    """The list's background, for the logos' corners"""
    try:
        c = ttk.Style().lookup("Treeview", "background") or PAGE_BG
        if c.startswith("#") and len(c) == 7:
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    except tk.TclError:
        pass
    return TREE_BG


def _icon_image(root, size):
    """The app's icon for the header, kept on the root so Tk does not drop it"""
    try:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
        from . import menu_gfx
        if menu_gfx.HAVE_PIL:
            from PIL import Image
            import base64
            import io
            img = Image.open(here).convert("RGBA").resize((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        else:
            photo = tk.PhotoImage(file=here)
        root._head_icon = photo
        return photo
    except Exception:
        return None


def _theme(root):
    """Sun Valley (sv-ttk, MIT), light or dark: a modern look on all three systems; plain ttk without it"""
    name = _theme_name()
    _apply_colours(name)
    try:
        import sv_ttk
        sv_ttk.set_theme(name, root)
    except Exception:
        try:
            ttk.Style().theme_use("clam" if not devices.WIN else "vista")
        except tk.TclError:
            pass
    _setup_fonts(root)
    st = ttk.Style()
    st.configure("TButton", padding=(12, 6))
    st.configure("Systems.Treeview", rowheight=50)
    st.configure("Big.Accent.TButton", font=_font(12, "bold"), padding=(22, 8))
    st.configure("Big.TButton", padding=(16, 8))
    st.configure("TLabelframe.Label", font=_font(11, "bold"))
    root.configure(bg=PAGE_BG)


def _set_icon(root):
    try:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
        if os.path.isfile(here):
            img = tk.PhotoImage(file=here)
            root.iconphoto(True, img)
            root._icon = img
    except tk.TclError:
        pass


def _fit_screen(root, app=None):
    """The window as large as its contents ask, at whatever size the system draws them (125 %,
    200 %...), but never larger than the screen (then it scrolls): both columns side by side when the
    screen is wide enough, else one under the other"""
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if app is None:
        w, h = min(max(root.winfo_reqwidth(), 1120), sw - 40), min(1040, sh - 110)
    else:
        pad = 44                                   # the margins and the scrollbar
        wide, narrow = app._wide_width() + pad, max(app.colA.winfo_reqwidth(), app.colB.winfo_reqwidth()) + pad
        is_wide = wide <= sw - 60
        w = min(wide if is_wide else narrow, sw - 40)
        root.geometry("%dx%d" % (w, min(700, sh - 110)))        # the width first: it decides the columns
        root.update()
        need = app._head.winfo_reqheight() + app.panel.winfo_reqheight() + app.body.winfo_reqheight() + 40
        h = min(need, sh - 110)                    # room for the title bar and the taskbar
        root.minsize(min(narrow, sw - 40), min(420, sh - 110))
    root.geometry("%dx%d+%d+%d" % (w, h, max((sw - w) // 2, 0), max((sh - 80 - h) // 2, 0)))


def main():
    root = tk.Tk()
    _set_icon(root)
    _theme(root)
    app = App(root)
    _fit_screen(root, app)

    def close():
        # What was fetched and unpacked goes with the window: the next start takes the systems fresh
        # from their projects, never an older one left here (not in the middle of writing a card:
        # the writer still reads them)
        if not app.busy:
            from .image import clear_cache
            clear_cache()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    return 0
