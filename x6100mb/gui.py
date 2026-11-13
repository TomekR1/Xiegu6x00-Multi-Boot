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
from .compose import DOOM_NAME, KEYS, MAX_ENTRIES, XIEGU_DEFAULTS, compose, resolve_extras
from .i18n import t
from .image import SourceSystem, cache_dir, open_source
from .writer import Progress, write_device, write_image_file

APP = "Xiegu Multi Patcher"
AUTHOR_URL = "https://www.qrz.com/db/SQ6RT"
PHASES = {"download": "Pobieranie", "prepare": "Przygotowanie karty", "write": "Zapis",
          "sync": "Opróżnianie bufora karty",
          "verify": "Weryfikacja", "unzip": "Rozpakowywanie", "done": "Gotowe"}


def _gb(n):
    return f"{n / 1e9:.1f} GB"


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.minsize(800, 680)
        self.entries = []                 # {"kind", "name", "sys"?}
        self.default = 0
        self.q = queue.Queue()
        self.busy = False
        self.cards = []
        self._build_all()
        self.refresh_cards()
        self.root.after(100, self._poll)

    # ---------------------------------------------------------------- layout
    def _build_all(self, keep=None):
        self.top = ttk.Frame(self.root)
        self.top.pack(fill="both", expand=True, padx=10, pady=10)
        self._build(self.top)
        if keep:
            for name, value in keep.items():
                getattr(self, name).set(value)
            self._toggle_adv()

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
        self._build_all(keep)
        for k, v in xiegu.items():
            self.xiegu_vars[k].set(v)
        self._redraw()
        self.refresh_cards()
        if 0 <= card < len(self.cards):
            self.card_box.current(card)

    def _build(self, top):
        pad = {"padx": 8, "pady": 4}

        head = ttk.Frame(top)
        head.pack(fill="x")
        ttk.Label(head, text=APP, font=("TkDefaultFont", 15, "bold")).pack(side="left")
        self.lang_var = tk.StringVar(value=i18n.LANGS[i18n.lang()])
        langs = ttk.Combobox(head, textvariable=self.lang_var, values=list(i18n.LANGS.values()),
                             state="readonly", width=8)
        langs.pack(side="right", padx=(12, 0))
        langs.bind("<<ComboboxSelected>>", lambda e: self.switch_lang(
            next(k for k, v in i18n.LANGS.items() if v == self.lang_var.get())))
        ttk.Label(head, text=t("Język:")).pack(side="right", padx=(12, 4))
        author = tk.Label(head, text=t("aplikacja: SQ6RT"), fg="#1f6fd1", cursor="hand2",
                          font=("TkDefaultFont", 10, "underline"))
        author.pack(side="right")
        author.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_URL))
        ttk.Label(top, text=t("Kilka systemów na jednej karcie SD dla Xiegu X6100: przy włączaniu radia menu na "
                              "ekranie, wybór klawiszem F1–F5.")).pack(anchor="w", pady=(0, 8))

        box = ttk.LabelFrame(top, text=t("1. Systemy w menu"))
        box.pack(fill="both", expand=True)
        cols = ("key", "name", "info")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=6, selectmode="browse")
        for c, h, w in (("key", "Klawisz", 70), ("name", "Nazwa w menu", 180), ("info", "Zawartość", 330)):
            self.tree.heading(c, text=t(h))
            self.tree.column(c, width=w, stretch=(c == "info"))
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", lambda e: self.rename())
        btns = ttk.Frame(box)
        btns.pack(side="right", fill="y", padx=8, pady=8)
        for text, cmd in (("+ Z internetu…", self.add_online), ("+ Obraz karty…", self.add_image),
                          ("+ Xiegu z eMMC", self.add_xiegu),
                          ("Zmień nazwę", self.rename), ("W górę", lambda: self.move(-1)),
                          ("W dół", lambda: self.move(1)), ("Domyślny", self.set_default),
                          ("Logo…", self.choose_logo), ("Podgląd menu", self.preview), ("Usuń", self.remove)):
            ttk.Button(btns, text=t(text), command=cmd, width=17).pack(fill="x", pady=2)

        self._build_extras(top)

        opts = ttk.LabelFrame(top, text=t("2. Ustawienia menu"))
        opts.pack(fill="x", pady=(8, 0))
        ttk.Label(opts, text=t("Czas na wybór (s):")).grid(row=0, column=0, sticky="w", **pad)
        self.timeout = tk.StringVar(value="5")
        ttk.Spinbox(opts, from_=0, to=9, textvariable=self.timeout, width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text=t("DATA w pliku .img (MB):")).grid(row=0, column=2, sticky="w", **pad)
        self.data_mb = tk.StringVar(value="1024")
        ttk.Spinbox(opts, from_=128, to=32768, increment=128, textvariable=self.data_mb, width=8).grid(
            row=0, column=3, sticky="w")
        ttk.Label(opts, text=t("(na karcie DATA zajmuje całe wolne miejsce)")).grid(row=0, column=4, sticky="w", **pad)
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

        out = ttk.LabelFrame(top, text=t("3. Zapis"))
        out.pack(fill="x", pady=(8, 0))
        ttk.Label(out, text=t("Karta SD:")).grid(row=0, column=0, sticky="w", **pad)
        self.card = tk.StringVar()
        self.card_box = ttk.Combobox(out, textvariable=self.card, state="readonly", width=60)
        self.card_box.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(out, text=t("Odśwież"), command=self.refresh_cards).grid(row=0, column=2, **pad)
        out.columnconfigure(1, weight=1)
        b = ttk.Frame(out)
        b.grid(row=1, column=0, columnspan=3, sticky="we", padx=8, pady=(4, 8))
        self.btn_card = ttk.Button(b, text=t("Wgraj na kartę"), command=self.write_card)
        self.btn_card.pack(side="right", padx=(8, 0))
        self.btn_img = ttk.Button(b, text=t("Zapisz jako plik .img…"), command=self.save_image)
        self.btn_img.pack(side="right")

        self.status = tk.StringVar(value=t("Dodaj obraz karty systemu (.img, .img.zip lub .img.xz), np. OpenX6X00."))
        self.bar = ttk.Progressbar(top, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", pady=(10, 2))
        ttk.Label(top, textvariable=self.status, wraplength=720).pack(anchor="w")

    def _toggle_adv(self):
        if self.show_adv.get():
            self.adv.grid(row=3, column=0, columnspan=5, sticky="w", pady=(0, 6))
        else:
            self.adv.grid_forget()

    # ---------------------------------------------------------------- list
    def _redraw(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.entries):
            key = KEYS[i][0] + ("  ★" if i == self.default else "")
            if e["kind"] == "xiegu":
                info = t("system Xiegu z pamięci wewnętrznej radia (nic tam nie jest zmieniane)")
            elif e["kind"] == "doom":
                info = t("klasyczny Doom (Freedoom), z jądrem pierwszego systemu z obrazu na liście")
            else:
                info = e["sys"].summary()
                if e["sys"].warnings:
                    info += "  ⚠ " + "; ".join(e["sys"].warnings)
            if e.get("logo"):
                info = "[logo: %s]  %s" % (os.path.basename(e["logo"]), info)
            self.tree.insert("", "end", iid=str(i), values=(key, e["name"], info))
        if select is not None and 0 <= select < len(self.entries):
            self.tree.selection_set(str(select))

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

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

    def _build_extras(self, top):
        """Extras: Doom, the easter egg (a tile of its own, not among the systems to fetch)"""
        box = ttk.LabelFrame(top, text="Extras")
        box.pack(fill="x", pady=(8, 0))
        self._doom_img = None
        try:
            from . import menu_gfx
            if menu_gfx.HAVE_PIL:
                import base64
                import io
                buf = io.BytesIO()
                menu_gfx.default_logo(DOOM_NAME, size=56, bg=(220, 220, 220)).save(buf, "PNG")
                self._doom_img = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        except Exception:
            self._doom_img = None
        b = ttk.Button(box, text="  Doom", image=self._doom_img, compound="left", command=self.add_doom)
        b.pack(side="left", padx=8, pady=6)
        ttk.Button(box, text=t("Przeczytaj najpierw"), command=self.doom_readme).pack(side="left", padx=(0, 8))
        ttk.Label(box, text=t("Klasyczny Doom na radiu (Freedoom). Gałka VFO obraca, F1 lub PTT strzela, "
                              "F2 otwiera drzwi, GEN to menu gry."), wraplength=440,
                  foreground="#555").pack(side="left", padx=4)

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
        txt = tk.Text(win, wrap="word", width=96, height=34, padx=12, pady=10, relief="flat",
                      font=("TkDefaultFont", 11))
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        body = i18n.DOOM_README[i18n.lang()]
        title, rest = body.split("\n", 1)
        txt.insert("end", title + "\n", "h1")
        lines = rest.split("\n")
        for k, line in enumerate(lines):
            heading = line and not line.startswith(" ") and k + 1 < len(lines) and lines[k + 1].startswith(" ")
            txt.insert("end", line + "\n", "h2" if heading else ())
        txt.tag_configure("h1", font=("TkDefaultFont", 15, "bold"))
        txt.tag_configure("h2", font=("TkDefaultFont", 11, "bold"), spacing1=6)
        txt.configure(state="disabled")
        ttk.Button(win, text="OK", command=win.destroy).pack(side="bottom", pady=8)
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

    def preview(self):
        from . import menu_gfx
        if not self.entries:
            messagebox.showinfo(APP, t("Najpierw dodaj systemy."))
            return
        if not menu_gfx.HAVE_PIL:
            messagebox.showinfo(APP, t("Podgląd wymaga biblioteki Pillow (jest w gotowych aplikacjach)."))
            return
        import base64
        import io
        from .compose import tile
        tiles = [tile(e) for e in self.entries]
        img = menu_gfx.render_menu(tiles, min(self.default, len(tiles) - 1))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        win = tk.Toplevel(self.root)
        win.title(t("Podgląd menu na ekranie radia (800×480)"))
        photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        lbl = ttk.Label(win, image=photo)
        lbl.image = photo
        lbl.pack(padx=8, pady=8)
        ttk.Label(win, text=t("Na radiu w drugim wierszu odlicza się czas do startu domyślnego systemu.")).pack(pady=(0, 8))

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
                if m[0] == "progress":
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
                  font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.vars, self.boxes = {}, {}
        for i, src in enumerate(catalog.SOURCES):
            r = i + 1
            ttk.Label(f, text=src["name"], font=("TkDefaultFont", 10, "bold")).grid(row=2 * r - 1, column=0, sticky="w")
            ttk.Label(f, text=t(src["about"]), foreground="#666").grid(row=2 * r, column=0, columnspan=3, sticky="w", pady=(0, 8))
            v = tk.StringVar(value=t("sprawdzam…"))
            box = ttk.Combobox(f, textvariable=v, state="disabled", width=38)
            box.grid(row=2 * r - 1, column=1, sticky="w", padx=8)
            btn = ttk.Button(f, text=t("Dodaj"), state="disabled", command=lambda s=src: self.add(s))
            btn.grid(row=2 * r - 1, column=2, sticky="w")
            self.vars[src["id"]], self.boxes[src["id"]] = v, (box, btn)
            threading.Thread(target=self._load, args=(src,), daemon=True).start()
        ttk.Label(f, text=t("Obrazy pobierane są z wydań projektów na GitHubie i zostają w pamięci podręcznej "
                            "aplikacji."), foreground="#666", wraplength=560).grid(row=99, column=0, columnspan=4,
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
    try:
        ttk.Style().theme_use("clam" if not devices.WIN else "vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0
