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

from . import devices, i18n
from .compose import DOOM_LOGO, DOOM_NAME, MAX_ENTRIES, XIEGU_DEFAULTS, compose, resolve_extras
from .i18n import t
from .image import SourceSystem, cache_dir, open_source
from .writer import Progress, write_device, write_image_file

APP = "Xiegu Multi Patcher"
AUTHOR_URL = "https://www.qrz.com/db/SQ6RT"
HEAD_BG, HEAD_FG, HEAD_SUB, LINK = "#0f2742", "#ffffff", "#a9bcd3", "#8fc3ff"
HINT = "#9aa3ad"
SCREEN_W, SCREEN_H = 600, 360          # the radio's 800x480, at 3/4
RED, RED_HOVER = "#d32f2f", "#ef4444"
ACCENT = "#57c8ff"
PAGE_BG, TEXT_FG = "#1c1c1c", "#e6e6e6"
PHASES = {"download": "Pobieranie", "prepare": "Przygotowanie karty", "write": "Zapis",
          "sync": "Opróżnianie bufora karty",
          "verify": "Weryfikacja", "unzip": "Rozpakowywanie", "done": "Gotowe"}


def _gb(n):
    return f"{n / 1e9:.1f} GB"


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.minsize(880, 720)
        self.entries = []                 # {"kind", "name", "sys"?}
        self.default = 0
        self.q = queue.Queue()
        self.busy = False
        self.cards = []
        self.tiles = {}                   # key -> what the radio's screen shows for an entry
        self._tile_jobs = set()
        self._build_all()
        self.refresh_cards()
        self.root.after(100, self._poll)

    # ---------------------------------------------------------------- layout
    def _build_all(self, keep=None):
        self.top = ttk.Frame(self.root)
        self.top.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._build(self.top)
        if keep:
            for name, value in keep.items():
                getattr(self, name).set(value)
            self._toggle_adv()
        self._redraw()

    def switch_lang(self, code):
        """The window again in the other language, with everything set so far"""
        if code == i18n.lang() or self.busy:
            self.lang_var.set(i18n.LANGS[i18n.lang()])
            return
        i18n.set_lang(code)
        keep = {n: getattr(self, n).get() for n in ("timeout", "data_mb", "data_mode", "show_adv", "status")}
        xiegu = {k: v.get() for k, v in self.xiegu_vars.items()}
        card = self.card_box.current()
        self.top.destroy()
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
        head.pack(fill="x", before=top)
        self._head = head
        inner = tk.Frame(head, bg=HEAD_BG)
        inner.pack(fill="x", padx=16, pady=9)
        icon = _icon_image(self.root, 48)
        if icon is not None:
            tk.Label(inner, image=icon, bg=HEAD_BG).pack(side="left", padx=(0, 12))
        titles = tk.Frame(inner, bg=HEAD_BG)
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text=APP, bg=HEAD_BG, fg=HEAD_FG, font=_font(18, "bold")).pack(anchor="w")
        tk.Label(titles, text=t("Kilka systemów na jednej karcie SD dla Xiegu X6100: przy włączaniu radia menu na "
                                "ekranie, wybór klawiszem F1–F5."), bg=HEAD_BG, fg=HEAD_SUB,
                 font=_font(10), wraplength=560, justify="left").pack(anchor="w")
        side = tk.Frame(inner, bg=HEAD_BG)
        side.pack(side="right", anchor="n")
        self.lang_var = tk.StringVar(value=i18n.LANGS[i18n.lang()])
        langs = ttk.Combobox(side, textvariable=self.lang_var, values=list(i18n.LANGS.values()),
                             state="readonly", width=8)
        langs.pack(anchor="e")
        langs.bind("<<ComboboxSelected>>", lambda e: self.switch_lang(
            next(k for k, v in i18n.LANGS.items() if v == self.lang_var.get())))
        author = tk.Label(side, text=t("aplikacja: SQ6RT"), bg=HEAD_BG, fg=LINK, cursor="hand2",
                          font=_font(10, "underline"))
        author.pack(anchor="e", pady=(6, 0))
        author.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_URL))
        tk.Frame(head, bg=ACCENT, height=3).pack(fill="x", side="bottom")

        box = self._section(top, 1, t("Menu na ekranie radia"), expand=True)
        btns = ttk.Frame(box)
        btns.pack(side="right", fill="y", padx=(12, 2), pady=2)
        for text, cmd, accent in (("+ Z internetu…", self.add_online, True), ("+ Obraz karty…", self.add_image, False),
                                  ("+ Xiegu z eMMC", self.add_xiegu, False)):
            ttk.Button(btns, text=t(text), command=cmd, width=18,
                       style="Accent.TButton" if accent else "TButton").pack(fill="x", pady=2)
        self._build_extras(btns)
        left = ttk.Frame(box)
        left.pack(side="left", fill="both", expand=True)
        self.screen = tk.Canvas(left, width=SCREEN_W, height=SCREEN_H, bg="#000000", highlightthickness=2,
                                highlightbackground="#3a3a3a", cursor="hand2")
        self.screen.pack(side="top", anchor="w")
        self.screen.bind("<Button-1>", self._screen_click)
        self.screen.bind("<Double-1>", lambda e: (self._screen_click(e), self.rename()))
        self.info = ttk.Label(left, text="", foreground=HINT, wraplength=SCREEN_W, justify="left")
        self.info.pack(side="top", anchor="w", pady=(6, 0))
        tools = ttk.Frame(left)
        tools.pack(side="top", fill="x", pady=(6, 0))
        for text, cmd in (("←", lambda: self.move(-1)), ("→", lambda: self.move(1)),
                          ("★  " + t("Domyślny"), self.set_default), ("✎  " + t("Zmień nazwę"), self.rename),
                          ("▣  " + t("Logo…"), self.choose_logo)):
            ttk.Button(tools, text=text, command=cmd, width=3 if len(text) == 1 else 0).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="✕  " + t("Usuń"), command=self.remove).pack(side="left", padx=(12, 0))
        self.selected = None


        opts = self._section(top, 2, t("Ustawienia menu"))
        ttk.Label(opts, text=t("Czas na wybór (s):")).grid(row=0, column=0, sticky="w", **pad)
        self.timeout = tk.StringVar(value="5")
        self.timeout.trace_add("write", lambda *a: self._render() if hasattr(self, "screen") else None)
        ttk.Spinbox(opts, from_=0, to=9, textvariable=self.timeout, width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text=t("DATA w pliku .img (MB):")).grid(row=0, column=2, sticky="w", **pad)
        self.data_mb = tk.StringVar(value="1024")
        ttk.Spinbox(opts, from_=128, to=32768, increment=128, textvariable=self.data_mb, width=8).grid(
            row=0, column=3, sticky="w")
        ttk.Label(opts, text=t("(na karcie DATA zajmuje całe wolne miejsce)"), foreground=HINT,
                  wraplength=190).grid(row=0, column=4, sticky="w", **pad)
        ttk.Label(opts, text=t("Partycja DATA:")).grid(row=1, column=0, sticky="w", **pad)
        self.data_mode = tk.StringVar(value="shared")
        dm = ttk.Frame(opts)
        dm.grid(row=1, column=1, columnspan=4, sticky="w")
        ttk.Radiobutton(dm, text=t("wspólna dla wszystkich systemów"), value="shared",
                        variable=self.data_mode).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(dm, text=t("osobna dla każdego systemu (własne ustawienia i logi)"), value="separate",
                        variable=self.data_mode).pack(side="left")
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text=t("Zaawansowane: start systemu Xiegu z eMMC"), variable=self.show_adv,
                        command=self._toggle_adv).grid(row=2, column=0, columnspan=5, sticky="w", **pad)
        self.adv = ttk.Frame(opts)
        self.xiegu_vars = {}
        labels = {"xiegu_dev": "Urządzenie mmc", "xiegu_part": "Partycja", "xiegu_kernel": "Jądro",
                  "xiegu_fdt": "Plik .dtb", "xiegu_args": "bootargs"}
        for i, (k, v) in enumerate(XIEGU_DEFAULTS.items()):
            ttk.Label(self.adv, text=(t(labels[k]) if k != "xiegu_args" else labels[k]) + ":").grid(row=i, column=0, sticky="w", padx=8, pady=1)
            var = tk.StringVar(value=v)
            ttk.Entry(self.adv, textvariable=var, width=90 if k == "xiegu_args" else 24).grid(
                row=i, column=1, sticky="w", pady=1)
            self.xiegu_vars[k] = var

        out = self._section(top, 3, t("Zapis karty"))
        ttk.Label(out, text=t("Karta SD:")).grid(row=0, column=0, sticky="w", **pad)
        self.card = tk.StringVar()
        self.card_box = ttk.Combobox(out, textvariable=self.card, state="readonly", width=34)
        self.card_box.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(out, text=t("Odśwież"), command=self.refresh_cards).grid(row=0, column=2, **pad)
        out.columnconfigure(1, weight=1)
        b = ttk.Frame(out)
        b.grid(row=0, column=3, sticky="e", padx=(8, 4))
        self.btn_card = ttk.Button(b, text="⬇  " + t("Wgraj na kartę"), command=self.write_card, style="Big.Accent.TButton")
        self.btn_card.pack(side="right", padx=(8, 0))
        self.btn_img = ttk.Button(b, text=t("Zapisz jako plik .img…"), command=self.save_image, style="Big.TButton")
        self.btn_img.pack(side="right")

        self.status = tk.StringVar(value=t("Dodaj obraz karty systemu (.img, .img.zip lub .img.xz), np. OpenX6X00."))
        foot = ttk.Frame(top, style="Card.TFrame", padding=(12, 8))
        foot.pack(fill="x", pady=(8, 0))
        self.bar = ttk.Progressbar(foot, mode="determinate", maximum=1000)
        self.bar.pack(fill="x")
        ttk.Label(foot, textvariable=self.status, wraplength=820, foreground=HINT).pack(anchor="w", pady=(6, 0))

    def _section(self, top, number, title, expand=False):
        """A titled card: a round number badge, the title, the card the section's widgets go in"""
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(8, 3))
        c = tk.Canvas(row, width=24, height=24, highlightthickness=0, bg=PAGE_BG)
        c.create_oval(1, 1, 23, 23, fill=ACCENT, outline="")
        c.create_text(12, 12, text=str(number), fill="#0b1a2a", font=_font(11, "bold"))
        c.pack(side="left", padx=(2, 8))
        ttk.Label(row, text=title, font=_font(13, "bold")).pack(side="left")
        card = ttk.Frame(top, style="Card.TFrame", padding=(10, 6))
        card.pack(fill="both" if expand else "x", expand=expand)
        return card

    def _toggle_adv(self):
        if self.show_adv.get():
            self.adv.grid(row=3, column=0, columnspan=5, sticky="w", pady=(0, 6))
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

    def _render(self):
        from . import menu_gfx
        c = self.screen
        c.delete("all")
        sx, sy = SCREEN_W / menu_gfx.W, SCREEN_H / menu_gfx.H
        if menu_gfx.HAVE_PIL:
            from PIL import Image
            img = menu_gfx.render_menu([self._tile(e) for e in self.entries],
                                       min(self.default, max(len(self.entries) - 1, 0)))
            self._screen_img = self._photo(img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS))
            c.create_image(0, 0, image=self._screen_img, anchor="nw")
        else:                               # no Pillow (running from source): names in boxes
            for i, e in enumerate(self.entries):
                cx = (menu_gfx.COL_W * i + menu_gfx.COL_W // 2) * sx
                c.create_rectangle(cx - 72 * sx, 76 * sy, cx + 72 * sx, 372 * sy, outline="#3a4560", width=2)
                c.create_text(cx, 220 * sy, text=e["name"], fill="#ffffff", width=130 * sx)
                c.create_text(cx, 435 * sy, text="F%d" % (i + 1), fill="#ffffff", font=_font(14, "bold"))
        if self.entries:                    # what U-Boot writes in the second row, in its 16x32 font
            try:
                secs = max(0, min(9, int(float(self.timeout.get().replace(",", ".")))))
            except (ValueError, AttributeError):
                secs = 5
            from .compose import COUNTDOWN
            text = t(COUNTDOWN).replace("${bm_default}", str(self.default + 1)).replace("${bm_left}", str(secs))
            c.create_text(16 * sx, 48 * sy, text=text, anchor="w", fill="#d0d0d0", font=("Courier", 13, "bold"))
        if not self.entries:
            c.create_text(SCREEN_W // 2, SCREEN_H // 2, fill="#9aa3ad", width=SCREEN_W - 80, justify="center",
                          font=_font(12), text=t("Tu zobaczysz menu dokładnie tak, jak pokaże je radio. Zacznij od "
                                                 "„+ Z internetu…”: wybierz system, a aplikacja sama go pobierze."))
        if self.selected is not None:
            cx = menu_gfx.COL_W * self.selected + menu_gfx.COL_W // 2
            c.create_rectangle((cx - 78) * sx, 70 * sy, (cx + 78) * sx, 472 * sy, outline=ACCENT, width=3,
                               dash=(6, 4))

    def _screen_click(self, ev):
        from . import menu_gfx
        i = int(ev.x / (SCREEN_W / menu_gfx.W) // menu_gfx.COL_W)
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
        self._job(t("Analiza obrazu…"), self._analyse, path)

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
        OnlineDialog(self)

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
                self._doom_img = self._photo(menu_gfx.load_logo(DOOM_LOGO, size=44, bg=_tree_bg()))
        except Exception:
            self._doom_img = None
        ttk.Button(col, text="  + Doom", image=self._doom_img, compound="left", command=self.add_doom).pack(fill="x")
        read = tk.Label(col, text="⚠  " + t("Przeczytaj najpierw"), bg=RED, fg="#ffffff", cursor="hand2",
                        font=_font(12, "bold"), padx=10, pady=9)
        read.pack(fill="x", pady=(6, 0))
        read.bind("<Button-1>", lambda e: self.doom_readme())
        read.bind("<Enter>", lambda e: read.configure(bg=RED_HOVER))
        read.bind("<Leave>", lambda e: read.configure(bg=RED))

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
        win = tk.Toplevel(self.root)
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
        txt.tag_configure("h1", font=_font(16, "bold"), foreground="#ff6b6b")
        txt.tag_configure("h2", font=_font(12, "bold"), foreground=LINK, spacing1=8)
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
        vals = [f"{c['name']}  —  {_gb(c['size'])}  ({c['path']})" for c in self.cards]
        self.card_box["values"] = vals
        if vals:
            self.card_box.current(0)
        else:
            self.card.set("")
            self.card_box.set(t("brak karty SD — włóż kartę i kliknij Odśwież"))

    # ---------------------------------------------------------------- building
    def _settings(self):
        try:
            timeout = max(0, min(9, int(float(self.timeout.get().replace(",", ".")))))
            data_mb = int(self.data_mb.get())
        except ValueError:
            raise ValueError(t("Czas i rozmiar DATA muszą być liczbami"))
        xiegu = {k: v.get().strip() for k, v in self.xiegu_vars.items()}
        return timeout, data_mb, xiegu

    def _plan(self, card_bytes=None):
        timeout, data_mb, xiegu = self._settings()
        ents = resolve_extras([dict(e) for e in self.entries])
        return compose(ents, default=self.default, timeout_s=timeout, data_mb=data_mb,
                       card_bytes=card_bytes, xiegu=xiegu, data_mode=self.data_mode.get())

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
        self._job(t("Zapis obrazu…"), self._save_job, plan, path)

    def _save_job(self, plan, path):
        write_image_file(plan, path, Progress(self._progress_cb))
        return ("msg", t("Zapisano {path} ({mb} MB). Można go wgrać balenaEtcherem.", path=path, mb=plan.size // 2**20))

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
        if not messagebox.askyesno(APP, text, icon="warning"):
            return
        if devices.is_admin() or devices.MAC:
            # macOS: the app writes itself, through authopen (it asks for the password)
            self._job(t("Zapis na kartę…"), self._card_job_inproc, plan, card["path"])
        else:
            self._job(t("Zapis na kartę (uprawnienia administratora)…"), self._card_job_elevated, plan, card["path"])

    def _card_job_inproc(self, plan, dev):
        write_device(plan, dev, Progress(self._progress_cb))
        return ("msg", t("Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia."))

    def _card_job_elevated(self, plan, dev):
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
            proc = devices.run_elevated(["write-plan", plan_file, dev, prog])
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
                        return ("msg", t("Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia."))
                    self.q.put(("progress", st["phase"], st["done"], st["total"], st.get("msg", "")))
                if proc is not None and proc.poll() is not None and not (st and st["phase"] == "done"):
                    time.sleep(0.5)
                    if os.path.exists(prog):
                        with open(prog) as f:
                            st = json.load(f)
                        if st["phase"] == "done":
                            return ("msg", t("Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia."))
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

    def _job(self, text, fn, *args):
        self.busy = True
        self.btn_card.state(["disabled"])
        self.btn_img.state(["disabled"])
        self.status.set(text)
        self.bar["value"] = 0

        def run():
            try:
                self.q.put(("result", fn(*args)))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "tile":
                    self.tiles[m[1]] = m[2]
                    self._render()
                elif m[0] == "progress":
                    _, phase, done, total, msg = m
                    self.bar["value"] = 1000 * done // max(total, 1)
                    self.status.set(f"{t(PHASES.get(phase, phase))}: {done * 100 // max(total, 1)}%  "
                                    f"({done // 2**20} / {total // 2**20} MB)  {msg}")
                elif m[0] in ("result", "error"):
                    self.busy = False
                    self.btn_card.state(["!disabled"])
                    self.btn_img.state(["!disabled"])
                    if m[0] == "error":
                        self.bar["value"] = 0
                        self.status.set(t("Błąd: ") + m[1])
                        messagebox.showerror(APP, m[1])
                    elif m[1][0] == "added":
                        s = m[1][1]
                        self.entries.append({"kind": "sd", "name": s.name[:28], "sys": s})
                        self._redraw(len(self.entries) - 1)
                        self.bar["value"] = 0
                        self.status.set(t("Dodano {name}: {summary}", name=s.name, summary=s.summary()))
                    else:
                        self.bar["value"] = 1000
                        self.status.set(m[1][1])
                        messagebox.showinfo(APP, m[1][1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


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
        ttk.Label(f, text=t("Obrazy pobierane są z wydań projektów na GitHubie i zostają w pamięci podręcznej "
                            "aplikacji."), foreground=HINT, wraplength=560).grid(row=99, column=0, columnspan=4,
                                                                                sticky="w", pady=(8, 0))

    def _load(self, src):
        try:
            rels = self.cat.releases(src)
            err = None if rels else t("brak obrazów X6100 w wydaniach")
        except Exception as e:
            rels, err = [], str(e)
        self.app.root.after(0, self._loaded, src, rels, err)

    def _loaded(self, src, rels, err):
        if not self.win.winfo_exists():
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
        btn.state(["!disabled"])

    def add(self, src):
        if self.app.busy:
            return
        if len(self.app.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES), parent=self.win)
            return
        box, _ = self.boxes[src["id"]]
        rel = self.rels[src["id"]][box.current()]
        self.app._job(t("Pobieranie {name} {tag}…", name=src["name"], tag=rel["tag"]), self.app._fetch_and_add, src, rel)
        self.win.destroy()


def _filetypes(types):
    """Tk on macOS crashes on some file filters (patterns with two dots, '*'): none there"""
    if devices.MAC:
        return {}
    return {"filetypes": types + [(t("Wszystkie pliki"), "*.*")]}


def _font(size, *style):
    fam = "Segoe UI" if devices.WIN else ("Helvetica Neue" if devices.MAC else "TkDefaultFont")
    return (fam, size) + style


def _tree_bg():
    """The list's background, for the logos' corners"""
    try:
        c = ttk.Style().lookup("Treeview", "background") or PAGE_BG
        if c.startswith("#") and len(c) == 7:
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    except tk.TclError:
        pass
    return (28, 28, 28)


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
    """Sun Valley (sv-ttk, MIT), dark: a modern look on all three systems; plain ttk without it"""
    try:
        import sv_ttk
        sv_ttk.set_theme("dark", root)
    except Exception:
        try:
            ttk.Style().theme_use("clam" if not devices.WIN else "vista")
        except tk.TclError:
            pass
    st = ttk.Style()
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


def main():
    root = tk.Tk()
    _set_icon(root)
    _theme(root)
    App(root)
    root.mainloop()
    return 0
