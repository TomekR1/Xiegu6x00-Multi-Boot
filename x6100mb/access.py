"""The accessible mode (alpha): the app for screen readers (NVDA, JAWS, Narrator, VoiceOver).

The app's own window is drawn with Tk, which tells screen readers next to nothing. This mode shows
the same card-making as a plain page of labelled controls (headings, a numbered list of the menu,
buttons named after what they do, fields with their labels), in a window of its own (pywebview,
the system's web view) or, without it, in the web browser. What happens is announced in a live
region: added, moved, the progress by stages and tens of per cent, the result.

The page talks to a small server on this computer only (127.0.0.1, a random port and a random
key in its address); making the card is the window's own code (jobs.CardMaker).
"""
import html
import json
import os
import secrets
import tempfile
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import backup, catalog, devices
from .compose import (DOOM_NAME, MAX_ENTRIES, MAX_SECS, NES_NAME, TALK_NAME, kernel_donor, name_entries)
from .i18n import LANGS, lang, set_lang, t

PHASES = {"download": "Pobieranie", "prepare": "Przygotowanie karty", "write": "Zapis",
          "sync": "Opróżnianie bufora karty", "verify": "Weryfikacja", "unzip": "Rozpakowywanie",
          "backup": "Zrzut DATA", "restore": "Przywracanie DATA"}


class Engine:
    """The card being made, and the job running (one at a time)"""

    def __init__(self):
        self.lock = threading.RLock()
        self.entries = []
        self.default = 0
        self.timeout, self.data_mode, self.keep, self.check, self.wait = 5, "separate", True, True, False
        self.cards, self.card = [], 0
        self.data_vol = None
        self.releases = {}                       # source id -> [release] (or an error text)
        self.messages = []                       # [{"id", "text", "level"}], announced once each
        self.busy = False
        self.job = None                          # {"title", "phase", "pct", "text"}
        self._last_said = (None, -1)
        self.confirm = None                      # the card write waiting for "yes"
        from .jobs import CardMaker
        self.maker = CardMaker(self._progress)
        self.refresh_cards(quiet=True)

    # ------------------------------------------------------------------ messages and progress
    def say(self, text, level="info"):
        with self.lock:
            self.messages.append({"id": len(self.messages) + 1, "text": text, "level": level})
            del self.messages[:-50]

    def _progress(self, phase, done, total, msg=""):
        pct = int(done * 100 / total) if total else 0
        name = t(PHASES.get(phase, phase))
        with self.lock:
            if self.job is not None:
                self.job.update(phase=name, pct=pct, text="%s %d%%" % (name, pct))
            # announced sparingly (a screen reader says every line): a new stage, then each quarter
            if phase == "done":
                return
            step = (phase, pct // 25)
            if step != self._last_said:
                first = self._last_said[0] != phase
                self._last_said = step
                self.say(name + "…" if first else t("{phase}: {pct} procent", phase=name, pct=pct // 25 * 25))

    def _run(self, title, fn, *args):
        with self.lock:
            if self.busy:
                raise ValueError(t("Trwa inna operacja, poczekaj na jej koniec."))
            self.busy, self.job, self._last_said = True, {"title": title, "phase": "", "pct": 0, "text": title}, (None, -1)
        self.say(title + "…")

        def work():
            try:
                result = fn(*args)
                if isinstance(result, tuple):           # the card maker's ("msg", text)
                    result = result[-1]
                if result:
                    self.say(result, "done")
            except Exception as e:
                log = backup.log_error(title)
                self.say(t("Nie udało się: {e}", e=str(e)) +
                         ("  " + t("Szczegóły: {p}", p=log) if log else ""), "error")
            finally:
                with self.lock:
                    self.busy, self.job = False, None
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ the state the page shows
    def state(self, since=0):
        with self.lock:
            donor = kernel_donor(self.entries)
            ents = []
            for i, e in enumerate(self.entries):
                what = {"sd": e.get("version") or t("system z obrazu"), "xiegu": t("system Xiegu z pamięci radia"),
                        "doom": t("Doom"), "nes": t("emulator NES"), "talk": t("menu mówione")}[e["kind"]]
                ents.append({"key": "F%d" % (i + 1), "name": e["name"], "what": what,
                             "default": i == self.default})
            return {"entries": ents, "max": MAX_ENTRIES, "donor": bool(donor),
                    "options": {"timeout": self.timeout, "data_mode": self.data_mode, "keep": self.keep,
                                "check": self.check, "wait": self.wait},
                    "cards": [card_label(c) for c in self.cards], "card": self.card,
                    "busy": self.busy, "job": dict(self.job) if self.job else None,
                    "confirm": self.confirm["text"] if self.confirm else None,
                    "messages": [m for m in self.messages if m["id"] > since],
                    "sources": [{"id": s["id"], "name": s["name"]} for s in catalog.SOURCES + catalog.own_sources()],
                    "releases": {k: v for k, v in self.releases.items()}, "lang": lang()}

    # ------------------------------------------------------------------ actions
    def load_releases(self, source):
        src = _source(source)
        if src["id"] in self.releases and isinstance(self.releases[src["id"]], list):
            return

        def fetch():
            try:
                rels = catalog.releases(src)
                self.releases[src["id"]] = [{"label": "%s (%s%s, %d MB)" % (r["tag"], r["date"],
                                             ", test" if r["prerelease"] else "", r["size"] >> 20)} for r in rels]
                self._rels_full = getattr(self, "_rels_full", {})
                self._rels_full[src["id"]] = rels
                self.say(t("{name}: wersji do wyboru: {n}", name=src["name"], n=len(rels)))
            except Exception as e:
                self.releases[src["id"]] = str(e)
                self.say(t("{name}: nie udało się pobrać listy wersji: {e}", name=src["name"], e=e), "error")
        threading.Thread(target=fetch, daemon=True).start()

    def add_online(self, source, release):
        src = _source(source)
        rels = getattr(self, "_rels_full", {}).get(src["id"])
        if not rels:
            raise ValueError(t("Lista wersji jeszcze się nie wczytała."))
        rel = rels[int(release)]
        self._room()

        def job():
            from .image import SourceSystem, cache_dir, open_source

            def prog(done, total):
                self._progress("download", done, total)
            path = catalog.download(src, rel, cache_dir(), prog)
            raw = open_source(path, cache_dir(), lambda d, n: self._progress("unzip", d, n))
            s = SourceSystem(path, raw)
            s.name, s.version = src["name"], catalog.version_of(rel)
            with self.lock:
                self.entries.append({"kind": "sd", "name": s.name[:28], "sys": s, "version": s.version,
                                     "base": s.name[:28]})
                name_entries(self.entries)
                key = len(self.entries)
            return t("Dodano {name} jako F{k}.", name=self.entries[-1]["name"], k=key)
        self._run(t("Pobieranie {name} {tag}", name=src["name"], tag=rel["tag"]), job)

    def add_image(self, path):
        self._room()

        def job():
            from .image import SourceSystem, cache_dir, open_source
            raw = open_source(path, cache_dir(), lambda d, n: self._progress("unzip", d, n))
            s = SourceSystem(path, raw)
            with self.lock:
                self.entries.append({"kind": "sd", "name": s.name[:28], "sys": s})
                key = len(self.entries)
            return t("Dodano {name} jako F{k}.", name=s.name[:28], k=key)
        self._run(t("Analiza obrazu"), job)

    def add_extra(self, kind):
        names = {"doom": DOOM_NAME, "nes": NES_NAME, "talk": TALK_NAME, "xiegu": "Xiegu (eMMC)"}
        if kind not in names:
            raise ValueError(kind)
        with self.lock:
            if any(e["kind"] == kind for e in self.entries):
                raise ValueError(t("{name} już jest w menu.", name=names[kind]))
            self._room()
            if kind != "xiegu" and kernel_donor(self.entries) is None:
                raise ValueError(t("Najpierw dodaj system z internetu (np. OpenX6X00): {name} uruchamia się z jego jądrem.",
                                   name=names[kind]))
            e = {"kind": kind, "name": names[kind]}
            if kind == "nes":
                e["games"] = []
            self.entries.append(e)
            self.say(t("Dodano {name} jako F{k}.", name=names[kind], k=len(self.entries)))
            if kind == "talk":
                self.say(t("Menu mówione: po wciśnięciu F1–F5 radio się wyłącza; gdy po kilku sekundach słychać "
                           "kliknięcie, wciśnij POWER i startuje wybrany system. Czas na ekranie warto ustawić na 3 s."))

    def _room(self):
        if len(self.entries) >= MAX_ENTRIES:
            raise ValueError(t("Menu ma najwyżej {n} pozycji (F1–F{n}).", n=MAX_ENTRIES))

    def move(self, i, d):
        with self.lock:
            i, j = int(i), int(i) + int(d)
            if not (0 <= i < len(self.entries) and 0 <= j < len(self.entries)):
                raise ValueError(t("Tej pozycji nie da się już przesunąć w tę stronę."))
            e = self.entries
            e[i], e[j] = e[j], e[i]
            if self.default == i:
                self.default = j
            elif self.default == j:
                self.default = i
            self.say(t("{name} jest teraz pod F{k}.", name=e[j]["name"], k=j + 1))

    def remove(self, i):
        with self.lock:
            e = self.entries.pop(int(i))
            if self.default >= len(self.entries):
                self.default = max(0, len(self.entries) - 1)
            elif self.default > int(i):
                self.default -= 1
            name_entries(self.entries)
            self.say(t("Usunięto {name}.", name=e["name"]))

    def set_default(self, i):
        with self.lock:
            self.default = int(i)
            self.say(t("{name} startuje domyślnie.", name=self.entries[self.default]["name"]))

    def rename(self, i, name):
        name = (name or "").strip()[:28]
        if not name:
            raise ValueError(t("Nazwa nie może być pusta."))
        with self.lock:
            self.entries[int(i)]["name"] = name
            self.say(t("Nowa nazwa F{k}: {name}.", k=int(i) + 1, name=name))

    def options(self, o):
        with self.lock:
            if "timeout" in o:
                self.timeout = max(0, min(MAX_SECS, int(o["timeout"])))
            if o.get("data_mode") in ("separate", "shared"):
                self.data_mode = o["data_mode"]
            for k in ("keep", "check", "wait"):
                if k in o:
                    setattr(self, k, bool(o[k]))

    def refresh_cards(self, quiet=False):
        try:
            self.cards = devices.list_cards()
        except Exception as e:
            self.cards = []
            if not quiet:
                self.say(t("Nie udało się odczytać listy kart: {e}", e=e), "error")
        try:
            vols = backup.find_data_volumes()
        except Exception:
            vols = []
        self.data_vol = vols[0]["path"] if vols else None
        self.card = 0
        if not quiet:
            self.say(t("Kart SD: {n}.", n=len(self.cards)) + (" " + card_label(self.cards[0]) if self.cards else
                     " " + t("Włóż kartę do czytnika i odśwież listę.")))

    def _settings(self):
        from .compose import XIEGU_DEFAULTS
        return (self.timeout, 1024, dict(XIEGU_DEFAULTS), self.data_mode, self.wait)

    def ask_write(self, card):
        """The first step of writing: what will happen, said; the second (confirm) writes"""
        with self.lock:
            if not self.cards:
                raise ValueError(t("Nie wybrano karty SD."))
            c = self.cards[int(card)]
            plan = self.maker.plan(self.entries, self.default, self._settings(), card_bytes=c["size"])
            lines = ", ".join("%s %s" % (x["key"], x["name"]) for x in plan.info["entries"])
            text = t("Karta {card}. WSZYSTKO na tej karcie zostanie usunięte. Menu: {lines}. Zapisać?",
                     card=card_label(c), lines=lines)
            self.confirm = {"card": c, "plan": plan, "text": text}
        return text

    def do_write(self, yes):
        with self.lock:
            c = self.confirm
            self.confirm = None
        if not c or not yes:
            self.say(t("Anulowano, karta nie została zmieniona."))
            return
        inproc = devices.is_admin() or devices.MAC
        self._run(t("Zapis na kartę"), self.maker.card_job, list(self.entries), self.default, c["plan"], c["card"],
                  inproc, self._settings(), self.check, self.keep, None, self.data_vol)

    def save_image(self):
        plan = self.maker.plan(self.entries, self.default, self._settings())
        folder = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.isdir(folder):
            folder = os.path.expanduser("~")
        path = os.path.join(folder, time.strftime("X6100-multiboot-%Y-%m-%d_%H-%M.img"))
        card = self.cards[self.card] if self.cards else None
        self._run(t("Zapis obrazu"), self.maker.save_job, list(self.entries), self.default, plan, path,
                  self._settings(), card, self.keep, None, self.data_vol)


def _source(sid):
    src = next((s for s in catalog.SOURCES + catalog.own_sources() if s["id"] == sid), None)
    if src is None:
        raise ValueError(sid)
    return src


def card_label(c):
    return "%s, %.1f GB, %s" % (c["name"], c["size"] / 1e9, c["path"])


# ---------------------------------------------------------------------- the server
class Handler(BaseHTTPRequestHandler):
    engine = None
    key = None
    stop = None

    def log_message(self, *a):
        pass

    def _ok(self, body, ctype="application/json; charset=utf-8", code=200):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _mine(self):
        u = urlparse(self.path)
        return u.path.startswith("/" + self.key + "/"), u

    def do_GET(self):
        mine, u = self._mine()
        if not mine:
            return self._ok("not here", "text/plain", 404)
        rest = u.path[len(self.key) + 2:]
        if rest == "":
            return self._ok(page(), "text/html; charset=utf-8")
        if rest == "api/state":
            since = int(parse_qs(u.query).get("since", ["0"])[0])
            return self._ok(json.dumps(self.engine.state(since)))
        self._ok("not here", "text/plain", 404)

    def do_POST(self):
        mine, u = self._mine()
        if not mine:
            return self._ok("not here", "text/plain", 404)
        rest = u.path[len(self.key) + 2:]
        n = int(self.headers.get("Content-Length") or 0)
        if rest == "api/upload":                 # a card image from the computer, sent by the page
            name = os.path.basename(parse_qs(u.query).get("name", ["image.img"])[0]) or "image.img"
            d = tempfile.mkdtemp(prefix="x6100mb-upload-")
            path = os.path.join(d, name)
            with open(path, "wb") as f:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            return self._call(lambda: self.engine.add_image(path))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        e = self.engine
        acts = {
            "releases": lambda: e.load_releases(body["source"]),
            "add_online": lambda: e.add_online(body["source"], body["release"]),
            "add_extra": lambda: e.add_extra(body["kind"]),
            "move": lambda: e.move(body["i"], body["d"]),
            "remove": lambda: e.remove(body["i"]),
            "default": lambda: e.set_default(body["i"]),
            "rename": lambda: e.rename(body["i"], body.get("name")),
            "options": lambda: e.options(body),
            "cards": lambda: e.refresh_cards(),
            "card": lambda: setattr(e, "card", int(body["card"])),
            "write": lambda: e.ask_write(body.get("card", e.card)),
            "confirm": lambda: e.do_write(bool(body.get("yes"))),
            "save_image": lambda: e.save_image(),
            "skip": lambda: e.maker.skip_check(),
            "lang": lambda: set_lang(body["lang"]),
            "quit": lambda: self.stop(),
        }
        if rest.startswith("api/") and rest[4:] in acts:
            return self._call(acts[rest[4:]])
        self._ok("not here", "text/plain", 404)

    def _call(self, fn):
        try:
            out = fn()
            self._ok(json.dumps({"ok": True, "text": out if isinstance(out, str) else None}))
        except Exception as ex:
            if not isinstance(ex, (ValueError, KeyError)):
                traceback.print_exc()
            msg = str(ex)
            self.engine.say(msg, "error")
            self._ok(json.dumps({"ok": False, "error": msg}))


def serve(engine=None):
    """The server on 127.0.0.1 (a random port and key): (url, server, an event set when it is closed)"""
    engine = engine or Engine()
    key = secrets.token_urlsafe(16)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    closed = threading.Event()

    def stop():
        closed.set()
        threading.Thread(target=srv.shutdown, daemon=True).start()
    Handler.engine, Handler.key, Handler.stop = engine, key, staticmethod(stop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d/%s/" % (srv.server_address[1], key), srv, closed


def screen_reader_running():
    """A screen reader on: Windows says so to every program (NVDA, JAWS and Narrator set it); macOS's
    VoiceOver from its setting. False elsewhere or when it cannot be told."""
    try:
        if devices.WIN:
            import ctypes
            flag = ctypes.c_int(0)
            ok = ctypes.windll.user32.SystemParametersInfoW(0x0046, 0, ctypes.byref(flag), 0)  # SPI_GETSCREENREADER
            return bool(ok and flag.value)
        if devices.MAC:
            import subprocess
            r = subprocess.run(["defaults", "read", "com.apple.universalaccess", "voiceOverOnOffKey"],
                               capture_output=True, text=True, timeout=5)
            return r.stdout.strip() == "1"
    except Exception:
        pass
    return False


def main():
    """The accessible mode: its own window (pywebview) when it can, else the web browser"""
    url, srv, closed = serve()
    title = "Xiegu Multi Patcher — " + t("tryb dostępny")
    try:
        import webview                                # pywebview: the system's web view in a window
    except Exception:
        webview = None
    if webview is not None:
        try:
            webview.create_window(title, url, width=900, height=900)
            webview.start()                           # until the window is closed
            srv.shutdown()
            return 0
        except Exception:
            pass                                      # no web view on this system: the browser
    print(t("Tryb dostępny: {url}", url=url), flush=True)
    webbrowser.open(url)
    try:
        closed.wait()                                 # until the page's Close button
    except KeyboardInterrupt:
        pass
    return 0


# ---------------------------------------------------------------------- the page
def page():
    L = {k: html.escape(t(v)) for k, v in {
        "title": "Xiegu Multi Patcher — tryb dostępny",
        "intro": "Kilka systemów na jednej karcie SD do Xiegu X6100. Przy włączaniu radia system wybierasz "
                 "klawiszem F1–F5. Ta strona ma te same funkcje co okno aplikacji, w formie czytelnej dla czytnika ekranu.",
        "menu": "Menu na karcie", "empty": "Menu jest puste. Dodaj system z internetu poniżej.",
        "add": "Dodaj system z internetu", "system": "System", "version": "Wersja", "add_btn": "Dodaj",
        "load": "Wczytaj wersje", "extras": "Dodatki", "doom": "Dodaj Dooma", "nes": "Dodaj emulator NES",
        "talk": "Dodaj menu mówione (alfa)", "xiegu": "Dodaj oryginalny system Xiegu z pamięci radia",
        "image": "Dodaj obraz karty z dysku", "image_btn": "Wyślij obraz",
        "settings": "Ustawienia menu", "timeout": "Czas na wybór na ekranie, w sekundach (0–15)",
        "data": "Partycja DATA", "sep": "osobna dla każdego systemu (zalecane)", "shared": "wspólna dla wszystkich",
        "keep": "Przenieś ustawienia ze starej karty", "check": "Sprawdź kartę po zapisie (zalecane)",
        "wait": "Bez automatycznego startu (czekaj na klawisz F)",
        "card": "Zapis karty", "cards": "Karta SD", "refresh": "Odśwież listę kart", "write": "Zapisz na kartę",
        "img": "Zapisz jako plik .img w Dokumentach", "skip": "Pomiń sprawdzanie karty",
        "confirm_h": "Potwierdzenie", "yes": "Tak, zapisz", "no": "Anuluj",
        "status": "Komunikaty", "close": "Zamknij tryb dostępny", "language": "Język",
        "up": "w górę", "down": "w dół", "def": "domyślny", "ren": "zmień nazwę", "del": "usuń",
        "is_def": "startuje domyślnie", "newname": "Nowa nazwa dla", "progress": "Postęp",
    }.items()}
    langs = "".join('<option value="%s">%s</option>' % (k, html.escape(v)) for k, v in LANGS.items())
    p = PAGE.replace("{{LANG}}", lang()).replace("{{LANGS}}", langs)
    p = p.replace("{{L}}", json.dumps({k: html.unescape(v) for k, v in L.items()}))
    for k, v in L.items():
        p = p.replace("{{T:%s}}" % k, v)
    return p


PAGE = r"""<!doctype html>
<html lang="{{LANG}}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{T:title}}</title>
<style>
:root { --bg:#ffffff; --fg:#111; --muted:#444; --line:#888; --accent:#0a4fa8; --err:#a40000; --ok:#0b6b2e; }
@media (prefers-color-scheme: dark) { :root { --bg:#111; --fg:#f2f2f2; --muted:#ccc; --line:#777; --accent:#7fb2ff; --err:#ff8a8a; --ok:#7ee2a0; } }
body { background:var(--bg); color:var(--fg); font:18px/1.5 system-ui, "Segoe UI", sans-serif; margin:0; }
main { max-width:860px; margin:0 auto; padding:16px; }
h1 { font-size:1.6em; } h2 { font-size:1.25em; margin-top:1.6em; border-bottom:1px solid var(--line); }
button, select, input { font:inherit; padding:6px 10px; margin:3px 4px 3px 0; }
button { border:2px solid var(--accent); background:transparent; color:var(--fg); border-radius:6px; cursor:pointer; }
button.main { background:var(--accent); color:var(--bg); font-weight:bold; }
:focus-visible { outline:3px solid var(--accent); outline-offset:2px; }
ol#menu li { margin:8px 0; padding:6px 0; border-bottom:1px solid var(--line); }
.what { color:var(--muted); }
#log p { margin:4px 0; } #log .error { color:var(--err); font-weight:bold; } #log .done { color:var(--ok); font-weight:bold; }
label { display:block; margin:6px 0; } fieldset { border:1px solid var(--line); margin:8px 0; }
.sr { position:absolute; left:-10000px; width:1px; height:1px; overflow:hidden; }
[hidden] { display:none !important; }
</style>
</head>
<body>
<main>
<h1>{{T:title}}</h1>
<p>{{T:intro}}</p>
<p><label>{{T:language}} <select id="lang">{{LANGS}}</select></label></p>

<div id="live" role="status" aria-live="polite" aria-atomic="false" class="sr"></div>
<div id="alert" role="alert" class="sr"></div>

<section aria-labelledby="h-menu">
<h2 id="h-menu">{{T:menu}}</h2>
<p id="empty">{{T:empty}}</p>
<ol id="menu"></ol>
</section>

<section aria-labelledby="h-add">
<h2 id="h-add">{{T:add}}</h2>
<label>{{T:system}} <select id="src"></select></label>
<button id="load">{{T:load}}</button>
<label>{{T:version}} <select id="rel"></select></label>
<button id="add">{{T:add_btn}}</button>
</section>

<section aria-labelledby="h-extras">
<h2 id="h-extras">{{T:extras}}</h2>
<button data-extra="xiegu">{{T:xiegu}}</button>
<button data-extra="talk">{{T:talk}}</button>
<button data-extra="doom">{{T:doom}}</button>
<button data-extra="nes">{{T:nes}}</button>
<p><label>{{T:image}} <input type="file" id="file" accept=".img,.zip,.xz"></label>
<button id="upload">{{T:image_btn}}</button></p>
</section>

<section aria-labelledby="h-set">
<h2 id="h-set">{{T:settings}}</h2>
<label>{{T:timeout}} <input type="number" id="timeout" min="0" max="15"></label>
<fieldset><legend>{{T:data}}</legend>
<label><input type="radio" name="data" value="separate"> {{T:sep}}</label>
<label><input type="radio" name="data" value="shared"> {{T:shared}}</label>
</fieldset>
<label><input type="checkbox" id="keep"> {{T:keep}}</label>
<label><input type="checkbox" id="check"> {{T:check}}</label>
<label><input type="checkbox" id="wait"> {{T:wait}}</label>
</section>

<section aria-labelledby="h-card">
<h2 id="h-card">{{T:card}}</h2>
<label>{{T:cards}} <select id="cards"></select></label>
<button id="refresh">{{T:refresh}}</button>
<p><button id="write" class="main">{{T:write}}</button>
<button id="img">{{T:img}}</button></p>
<div id="confirm" hidden role="group" aria-labelledby="h-confirm">
<h3 id="h-confirm" tabindex="-1">{{T:confirm_h}}</h3>
<p id="confirm-text"></p>
<button id="yes" class="main">{{T:yes}}</button> <button id="no">{{T:no}}</button>
</div>
<p><label>{{T:progress}} <progress id="prog" max="100" value="0"></progress></label> <span id="progtext"></span>
<button id="skip" hidden>{{T:skip}}</button></p>
</section>

<section aria-labelledby="h-log">
<h2 id="h-log">{{T:status}}</h2>
<div id="log"></div>
</section>

<p><button id="quit">{{T:close}}</button></p>
</main>
<script>
const L = {{L}};
const base = location.pathname;
let since = 0, st = null, lastMenu = "", lastRel = "";
const $ = id => document.getElementById(id);
async function api(name, body) {
  const r = await fetch(base + "api/" + name, {method: "POST", headers: {"Content-Type": "application/json"},
                                              body: JSON.stringify(body || {})});
  return r.json();
}
function announce(text, err) {
  const el = err ? $("alert") : $("live");
  el.textContent = ""; setTimeout(() => { el.textContent = text; }, 60);
}
function renderMenu() {
  const key = JSON.stringify(st.entries);
  if (key === lastMenu) return;
  const focus = document.activeElement && document.activeElement.dataset.focus;
  lastMenu = key;
  const ol = $("menu"); ol.textContent = "";
  $("empty").hidden = st.entries.length > 0;
  st.entries.forEach((e, i) => {
    const li = document.createElement("li");
    const head = document.createElement("span");
    head.textContent = e.key + ": " + e.name + (e.default ? ", " + L.is_def : "");
    const what = document.createElement("span"); what.className = "what"; what.textContent = " (" + e.what + ") ";
    li.append(head, what);
    const btn = (label, act, extra) => {
      const b = document.createElement("button");
      b.textContent = label; b.setAttribute("aria-label", label + ": " + e.key + " " + e.name);
      b.dataset.focus = act + ":" + i + (extra || "");
      b.onclick = act === "rename" ? async () => {
          const n = prompt(L.newname + " " + e.key + " " + e.name, e.name);
          if (n) await api("rename", {i, name: n}); poll();
        } : async () => { await api(act, Object.assign({i}, extra === "u" ? {d: -1} : extra === "d" ? {d: 1} : {})); poll(); };
      li.append(b); return b;
    };
    if (i > 0) btn(L.up, "move", "u");
    if (i < st.entries.length - 1) btn(L.down, "move", "d");
    if (!e.default) btn(L.def, "default");
    btn(L.ren, "rename"); btn(L.del, "remove");
    ol.append(li);
  });
  if (focus) {                                 // the focus stays where the action was (or the list)
    const [act, rest] = focus.split(":");
    let i = parseInt(rest), extra = rest.slice(String(i).length);
    if (act === "move") i = i + (extra === "u" ? -1 : 1);
    const same = document.querySelector('[data-focus="' + act + ":" + i + extra + '"]')
              || document.querySelector('[data-focus^="move:' + i + '"]') || $("h-menu");
    if (same === $("h-menu")) same.tabIndex = -1;
    same.focus();
  }
}
function renderSelects() {
  const src = $("src");
  if (!src.options.length) st.sources.forEach(s => src.add(new Option(s.name, s.id)));
  const rels = st.releases[src.value];
  const key = src.value + JSON.stringify(rels || null);
  if (key !== lastRel) {
    lastRel = key; const rel = $("rel"); rel.textContent = "";
    if (Array.isArray(rels)) rels.forEach((r, i) => rel.add(new Option(r.label, i)));
  }
  const cards = $("cards"), ck = JSON.stringify(st.cards);
  if (cards.dataset.k !== ck) { cards.dataset.k = ck; cards.textContent = "";
    st.cards.forEach((c, i) => cards.add(new Option(c, i))); cards.value = st.card; }
}
function renderOptions(first) {
  if (!first) return;
  $("timeout").value = st.options.timeout;
  document.querySelectorAll('input[name="data"]').forEach(r => r.checked = r.value === st.options.data_mode);
  ["keep", "check", "wait"].forEach(k => $(k).checked = st.options[k]);
  $("lang").value = st.lang;
}
let confirmShown = false;
function renderJob() {
  const j = st.job;
  $("prog").value = j ? j.pct : 0;
  $("progtext").textContent = j ? j.title + ": " + j.text : "";
  $("skip").hidden = !(j && /eryfik|erif/i.test(j.phase));
  document.querySelectorAll("main button:not(#quit):not(#no):not(#yes):not(#skip)").forEach(b => b.disabled = st.busy);
  const c = $("confirm");
  if (st.confirm && !confirmShown) { $("confirm-text").textContent = st.confirm; c.hidden = false; confirmShown = true;
    $("h-confirm").focus(); }
  if (!st.confirm && confirmShown) { c.hidden = true; confirmShown = false; $("write").focus(); }
}
function renderLog() {
  st.messages.forEach(m => {
    since = Math.max(since, m.id);
    const p = document.createElement("p"); p.className = m.level; p.textContent = m.text;
    $("log").prepend(p);
    announce(m.text, m.level === "error");
  });
}
let first = true;
async function poll() {
  try {
    const r = await fetch(base + "api/state?since=" + since); st = await r.json();
    renderMenu(); renderSelects(); renderOptions(first); renderJob(); renderLog(); first = false;
  } catch (e) {}
}
$("load").onclick = () => api("releases", {source: $("src").value});
$("src").onchange = () => api("releases", {source: $("src").value});
$("add").onclick = () => api("add_online", {source: $("src").value, release: $("rel").value || 0});
document.querySelectorAll("[data-extra]").forEach(b => b.onclick = () => api("add_extra", {kind: b.dataset.extra}).then(poll));
$("upload").onclick = async () => {
  const f = $("file").files[0]; if (!f) { $("file").focus(); return; }
  await fetch(base + "api/upload?name=" + encodeURIComponent(f.name), {method: "POST", body: f}); poll();
};
$("timeout").onchange = () => api("options", {timeout: parseInt($("timeout").value || "5")});
document.querySelectorAll('input[name="data"]').forEach(r => r.onchange = () => api("options", {data_mode: r.value}));
["keep", "check", "wait"].forEach(k => $(k).onchange = () => api("options", {[k]: $(k).checked}));
$("cards").onchange = () => api("card", {card: $("cards").value});
$("refresh").onclick = () => api("cards").then(poll);
$("write").onclick = () => api("write", {card: $("cards").value || 0}).then(poll);
$("yes").onclick = () => api("confirm", {yes: true}).then(poll);
$("no").onclick = () => api("confirm", {yes: false}).then(poll);
$("img").onclick = () => api("save_image").then(poll);
$("skip").onclick = () => api("skip");
$("lang").onchange = () => api("lang", {lang: $("lang").value}).then(() => location.reload());
$("quit").onclick = () => { api("quit"); document.body.textContent = ""; window.close(); };
poll(); setInterval(poll, 700);
api("releases", {source: "openx6x00"});
</script>
</body>
</html>
"""
