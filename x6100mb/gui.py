"""Okno programu: lista systemów, menu, zapis do pliku .img albo na kartę SD."""
import json
import os
import queue
import shutil
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import devices
from .compose import KEYS, MAX_ENTRIES, XIEGU_DEFAULTS, compose
from .image import SourceSystem, cache_dir, open_source
from .writer import Progress, write_device, write_image_file

APP = "X6100 Multiboot"
PHASES = {"prepare": "Przygotowanie karty", "write": "Zapis", "sync": "Opróżnianie bufora karty",
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
        self._build()
        self.refresh_cards()
        self.root.after(100, self._poll)

    # ---------------------------------------------------------------- layout
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(top, text=APP, font=("TkDefaultFont", 15, "bold")).pack(anchor="w")
        ttk.Label(top, text="Kilka systemów na jednej karcie SD dla Xiegu X6100, wybór klawiszem F1–F5 "
                            "przy włączaniu radia.").pack(anchor="w", pady=(0, 8))

        box = ttk.LabelFrame(top, text="1. Systemy w menu")
        box.pack(fill="both", expand=True)
        cols = ("key", "name", "info")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=6, selectmode="browse")
        for c, t, w in (("key", "Klawisz", 70), ("name", "Nazwa w menu", 180), ("info", "Zawartość", 330)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=(c == "info"))
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", lambda e: self.rename())
        btns = ttk.Frame(box)
        btns.pack(side="right", fill="y", padx=8, pady=8)
        for text, cmd in (("+ Obraz karty…", self.add_image), ("+ Xiegu z eMMC", self.add_xiegu),
                          ("Zmień nazwę", self.rename), ("W górę", lambda: self.move(-1)),
                          ("W dół", lambda: self.move(1)), ("Domyślny", self.set_default),
                          ("Usuń", self.remove)):
            ttk.Button(btns, text=text, command=cmd, width=17).pack(fill="x", pady=2)

        opts = ttk.LabelFrame(top, text="2. Ustawienia menu")
        opts.pack(fill="x", pady=(8, 0))
        ttk.Label(opts, text="Czas na wybór (s):").grid(row=0, column=0, sticky="w", **pad)
        self.timeout = tk.StringVar(value="5")
        ttk.Spinbox(opts, from_=0, to=60, textvariable=self.timeout, width=6).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="DATA w pliku .img (MB):").grid(row=0, column=2, sticky="w", **pad)
        self.data_mb = tk.StringVar(value="1024")
        ttk.Spinbox(opts, from_=128, to=32768, increment=128, textvariable=self.data_mb, width=8).grid(
            row=0, column=3, sticky="w")
        ttk.Label(opts, text="(na karcie DATA zajmuje całe wolne miejsce)").grid(row=0, column=4, sticky="w", **pad)
        self.show_adv = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Zaawansowane: start systemu Xiegu z eMMC", variable=self.show_adv,
                        command=self._toggle_adv).grid(row=1, column=0, columnspan=5, sticky="w", **pad)
        self.adv = ttk.Frame(opts)
        self.xiegu_vars = {}
        labels = {"xiegu_dev": "Urządzenie mmc", "xiegu_part": "Partycja", "xiegu_kernel": "Jądro",
                  "xiegu_fdt": "Plik .dtb", "xiegu_args": "bootargs"}
        for i, (k, v) in enumerate(XIEGU_DEFAULTS.items()):
            ttk.Label(self.adv, text=labels[k] + ":").grid(row=i, column=0, sticky="w", padx=8, pady=1)
            var = tk.StringVar(value=v)
            ttk.Entry(self.adv, textvariable=var, width=90 if k == "xiegu_args" else 24).grid(
                row=i, column=1, sticky="w", pady=1)
            self.xiegu_vars[k] = var

        out = ttk.LabelFrame(top, text="3. Zapis")
        out.pack(fill="x", pady=(8, 0))
        ttk.Label(out, text="Karta SD:").grid(row=0, column=0, sticky="w", **pad)
        self.card = tk.StringVar()
        self.card_box = ttk.Combobox(out, textvariable=self.card, state="readonly", width=60)
        self.card_box.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(out, text="Odśwież", command=self.refresh_cards).grid(row=0, column=2, **pad)
        out.columnconfigure(1, weight=1)
        b = ttk.Frame(out)
        b.grid(row=1, column=0, columnspan=3, sticky="we", padx=8, pady=(4, 8))
        self.btn_card = ttk.Button(b, text="Wgraj na kartę", command=self.write_card)
        self.btn_card.pack(side="right", padx=(8, 0))
        self.btn_img = ttk.Button(b, text="Zapisz jako plik .img…", command=self.save_image)
        self.btn_img.pack(side="right")

        self.status = tk.StringVar(value="Dodaj obraz karty systemu (.img lub .img.zip), np. OpenX6X00.")
        self.bar = ttk.Progressbar(top, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", pady=(10, 2))
        ttk.Label(top, textvariable=self.status, wraplength=720).pack(anchor="w")

    def _toggle_adv(self):
        if self.show_adv.get():
            self.adv.grid(row=2, column=0, columnspan=5, sticky="w", pady=(0, 6))
        else:
            self.adv.grid_forget()

    # ---------------------------------------------------------------- list
    def _redraw(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.entries):
            key = KEYS[i][0] + ("  ★" if i == self.default else "")
            if e["kind"] == "xiegu":
                info = "system Xiegu z pamięci wewnętrznej radia (nic tam nie jest zmieniane)"
            else:
                info = e["sys"].summary()
                if e["sys"].warnings:
                    info += "  ⚠ " + "; ".join(e["sys"].warnings)
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
            messagebox.showwarning(APP, f"Menu ma najwyżej {MAX_ENTRIES} pozycji (F1–F{MAX_ENTRIES}).")
            return
        path = filedialog.askopenfilename(title="Obraz karty systemu",
                                          filetypes=[("Obrazy kart", "*.img *.zip *.img.zip"), ("Wszystkie", "*")])
        if not path:
            return
        self._job("Analiza obrazu…", self._analyse, path)

    def _analyse(self, path):
        def unzip(done, total):
            self.q.put(("progress", "unzip", done, total, ""))
        raw = open_source(path, cache_dir(), unzip)
        s = SourceSystem(path, raw)
        return ("added", s)

    def add_xiegu(self):
        if any(e["kind"] == "xiegu" for e in self.entries):
            return
        if len(self.entries) >= MAX_ENTRIES:
            messagebox.showwarning(APP, f"Menu ma najwyżej {MAX_ENTRIES} pozycji.")
            return
        self.entries.append({"kind": "xiegu", "name": "Xiegu (eMMC)"})
        self._redraw(len(self.entries) - 1)

    def rename(self):
        i = self._sel()
        if i is None:
            return
        n = simpledialog.askstring(APP, "Nazwa w menu (litery bez polskich znaków, do 28):",
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

    # ---------------------------------------------------------------- cards
    def refresh_cards(self):
        try:
            self.cards = devices.list_cards()
        except Exception as e:
            self.cards = []
            self.status.set(f"Nie udało się odczytać listy kart: {e}")
        vals = [f"{c['name']}  —  {_gb(c['size'])}  ({c['path']})" for c in self.cards]
        self.card_box["values"] = vals
        if vals:
            self.card_box.current(0)
        else:
            self.card.set("")
            self.card_box.set("brak karty SD — włóż kartę i kliknij Odśwież")

    # ---------------------------------------------------------------- building
    def _settings(self):
        try:
            timeout = float(self.timeout.get().replace(",", "."))
            data_mb = int(self.data_mb.get())
        except ValueError:
            raise ValueError("Czas i rozmiar DATA muszą być liczbami")
        xiegu = {k: v.get().strip() for k, v in self.xiegu_vars.items()}
        return timeout, data_mb, xiegu

    def _plan(self, card_bytes=None):
        timeout, data_mb, xiegu = self._settings()
        ents = [dict(e) for e in self.entries]
        return compose(ents, default=self.default, timeout_s=timeout, data_mb=data_mb,
                       card_bytes=card_bytes, xiegu=xiegu)

    def save_image(self):
        if self.busy:
            return
        try:
            plan = self._plan()
        except Exception as e:
            messagebox.showerror(APP, str(e))
            return
        path = filedialog.asksaveasfilename(title="Zapisz obraz karty", defaultextension=".img",
                                            initialfile="X6100-multiboot.img", filetypes=[("Obraz karty", "*.img")])
        if not path:
            return
        self._job("Zapis obrazu…", self._save_job, plan, path)

    def _save_job(self, plan, path):
        write_image_file(plan, path, Progress(self._progress_cb))
        return ("msg", f"Zapisano {path} ({plan.size // 2**20} MB). Można go wgrać balenaEtcherem.")

    def write_card(self):
        if self.busy:
            return
        idx = self.card_box.current()
        if idx < 0 or idx >= len(self.cards):
            messagebox.showwarning(APP, "Nie wybrano karty SD.")
            return
        card = self.cards[idx]
        try:
            plan = self._plan(card_bytes=card["size"])
        except Exception as e:
            messagebox.showerror(APP, str(e))
            return
        lines = [f"{x['key']}  {x['name']}" for x in plan.info["entries"]]
        if not messagebox.askyesno(APP, f"Karta: {card['name']} {_gb(card['size'])} ({card['path']})\n\n"
                                        f"WSZYSTKO na tej karcie zostanie usunięte.\n\nMenu:\n" + "\n".join(lines) +
                                   f"\n\nDATA: {plan.info['data_mb']} MB\n\nWgrać?", icon="warning"):
            return
        if devices.is_admin():
            self._job("Zapis na kartę…", self._card_job_inproc, plan, card["path"])
        else:
            self._job("Zapis na kartę (uprawnienia administratora)…", self._card_job_elevated, plan, card["path"])

    def _card_job_inproc(self, plan, dev):
        write_device(plan, dev, Progress(self._progress_cb))
        return ("msg", "Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia.")

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
                        return ("msg", "Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia.")
                    self.q.put(("progress", st["phase"], st["done"], st["total"], st.get("msg", "")))
                if proc is not None and proc.poll() is not None and not (st and st["phase"] == "done"):
                    time.sleep(0.5)
                    if os.path.exists(prog):
                        with open(prog) as f:
                            st = json.load(f)
                        if st["phase"] == "done":
                            return ("msg", "Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia.")
                        if st["phase"] == "error":
                            raise RuntimeError(st["msg"])
                    raise RuntimeError("Zapis przerwany (odmowa uprawnień administratora?)")
                if proc is None and st is None and time.time() - started > 120:
                    raise RuntimeError("Program zapisujący nie wystartował (odmowa uprawnień?)")
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
                    self.status.set(f"{PHASES.get(phase, phase)}: {done * 100 // max(total, 1)}%  "
                                    f"({done // 2**20} / {total // 2**20} MB)  {msg}")
                elif m[0] in ("result", "error"):
                    self.busy = False
                    self.btn_card.state(["!disabled"])
                    self.btn_img.state(["!disabled"])
                    if m[0] == "error":
                        self.bar["value"] = 0
                        self.status.set("Błąd: " + m[1])
                        messagebox.showerror(APP, m[1])
                    elif m[1][0] == "added":
                        s = m[1][1]
                        self.entries.append({"kind": "sd", "name": s.name[:28], "sys": s})
                        self._redraw(len(self.entries) - 1)
                        self.bar["value"] = 0
                        self.status.set(f"Dodano {s.name}: {s.summary()}")
                    else:
                        self.bar["value"] = 1000
                        self.status.set(m[1][1])
                        messagebox.showinfo(APP, m[1][1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam" if not devices.WIN else "vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0
