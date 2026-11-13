"""The app's languages: Polish (the source texts) and English.

t("Polski tekst {x}", x=...) gives the text in the chosen language. The choice is kept in
settings.json in the user's config folder; the first time, the system's language decides
(Polish on a Polish system, English otherwise).
"""
import json
import locale
import os

LANGS = {"pl": "Polski", "en": "English"}
_lang = None


def _config_file():
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or \
        os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "xiegu-multi-patcher", "settings.json")


def _system_lang():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v:
            return "pl" if v.lower().startswith("pl") else "en"
    try:
        loc = locale.getlocale()[0] or ""
    except Exception:
        loc = ""
    if not loc:
        try:     # macOS and Windows apps often have no LANG
            import subprocess
            import sys
            if sys.platform == "darwin":
                out = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True,
                                     text=True, timeout=3).stdout
                loc = out.strip()
            elif sys.platform.startswith("win"):
                import ctypes
                lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                loc = "pl" if (lcid & 0x3FF) == 0x15 else "en"
        except Exception:
            loc = ""
    return "pl" if loc.lower().startswith("pl") or "polish" in loc.lower() else "en"


def lang():
    global _lang
    if _lang is None:
        try:
            with open(_config_file()) as f:
                _lang = json.load(f).get("lang")
        except (OSError, ValueError):
            _lang = None
        if _lang not in LANGS:
            _lang = _system_lang()
    return _lang


def set_lang(code):
    global _lang
    if code not in LANGS:
        return
    _lang = code
    path = _config_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
        data["lang"] = code
        with open(path, "w") as f:
            json.dump(data, f)
    except (OSError, ValueError):
        pass


def t(text, **kw):
    s = EN.get(text, text) if lang() == "en" else text
    return s.format(**kw) if kw else s


EN = {
    # main window
    "aplikacja: SQ6RT": "app by SQ6RT",
    "Kilka systemów na jednej karcie SD dla Xiegu X6100: przy włączaniu radia menu na ekranie, wybór klawiszem F1–F5.":
        "Several systems on one SD card for the Xiegu X6100: a menu on the radio's screen at power-on, "
        "choose with the F1–F5 keys.",
    "Język:": "Language:",
    "1. Systemy w menu": "1. Systems in the menu",
    "Klawisz": "Key",
    "Nazwa w menu": "Name in the menu",
    "Zawartość": "Contents",
    "+ Z internetu…": "+ From the internet…",
    "+ Obraz karty…": "+ Card image…",
    "+ Xiegu z eMMC": "+ Xiegu from eMMC",
    "Zmień nazwę": "Rename",
    "W górę": "Up",
    "W dół": "Down",
    "Domyślny": "Default",
    "Logo…": "Logo…",
    "Podgląd menu": "Menu preview",
    "Usuń": "Remove",
    "2. Ustawienia menu": "2. Menu settings",
    "Czas na wybór (s):": "Time to choose (s):",
    "DATA w pliku .img (MB):": "DATA in an .img file (MB):",
    "(na karcie DATA zajmuje całe wolne miejsce)": "(on a card DATA takes all the free space)",
    "Partycja DATA:": "DATA partition:",
    "wspólna dla wszystkich systemów": "shared by all systems",
    "osobna dla każdego systemu (własne ustawienia i logi)": "one per system (own settings and logs)",
    "Zaawansowane: start systemu Xiegu z eMMC": "Advanced: starting Xiegu's system from the eMMC",
    "Urządzenie mmc": "mmc device",
    "Partycja": "Partition",
    "Jądro": "Kernel",
    "Plik .dtb": ".dtb file",
    "3. Zapis": "3. Write",
    "Karta SD:": "SD card:",
    "Odśwież": "Refresh",
    "Wgraj na kartę": "Write to the card",
    "Zapisz jako plik .img…": "Save as an .img file…",
    "Dodaj obraz karty systemu (.img, .img.zip lub .img.xz), np. OpenX6X00.":
        "Add a system's card image (.img, .img.zip or .img.xz), e.g. OpenX6X00.",
    "system Xiegu z pamięci wewnętrznej radia (nic tam nie jest zmieniane)":
        "Xiegu's system from the radio's internal memory (nothing there is changed)",
    "klasyczny Doom (Freedoom), z jądrem pierwszego systemu z obrazu na liście":
        "classic Doom (Freedoom), with the kernel of the first system from an image on the list",
    "Menu ma najwyżej {n} pozycji (F1–F{n}).": "The menu has at most {n} entries (F1–F{n}).",
    "Obraz karty systemu (.img, .img.zip, .img.xz)": "A system's card image (.img, .img.zip, .img.xz)",
    "Obrazy kart": "Card images",
    "Analiza obrazu…": "Looking at the image…",
    "Klasyczny Doom na radiu (Freedoom). Gałka VFO obraca, F1 lub PTT strzela, F2 otwiera drzwi, GEN to menu gry.":
        "Classic Doom on the radio (Freedoom). The VFO knob turns, F1 or PTT fires, F2 opens doors, "
        "GEN is the game's menu.",
    "Przeczytaj najpierw": "Read first",
    "Doom uruchamia się z jądrem systemu z obrazu (np. OpenX6X00). Dodaj najpierw taki system, potem Dooma.":
        "Doom starts with the kernel of a system from an image (e.g. OpenX6X00). Add such a system first, "
        "then Doom.",
    "Nazwa w menu (litery bez polskich znaków, do 28):": "Name in the menu (plain letters, up to 28):",
    "Zaznacz system na liście, potem Logo…": "Select a system on the list, then Logo…",
    "Logo dla {name}": "Logo for {name}",
    "Obrazki": "Pictures",
    "Nie da się wczytać obrazka: {e}": "Cannot read the picture: {e}",
    "Najpierw dodaj systemy.": "Add systems first.",
    "Podgląd wymaga biblioteki Pillow (jest w gotowych aplikacjach).":
        "The preview needs the Pillow library (the ready-made apps have it).",
    "Podgląd menu na ekranie radia (800×480)": "The menu on the radio's screen (800×480)",
    "Na radiu w drugim wierszu odlicza się czas do startu domyślnego systemu.":
        "On the radio the second line counts down to the default system's start.",
    "Nie udało się odczytać listy kart: {e}": "Could not list the cards: {e}",
    "brak karty SD — włóż kartę i kliknij Odśwież": "no SD card: put one in and click Refresh",
    "Czas i rozmiar DATA muszą być liczbami": "The time and the DATA size must be numbers",
    "Zapisz obraz karty": "Save the card image",
    "Obraz karty": "Card image",
    "Zapis obrazu…": "Writing the image…",
    "Zapisano {path} ({mb} MB). Można go wgrać balenaEtcherem.":
        "Saved {path} ({mb} MB). It can be written with balenaEtcher.",
    "Nie wybrano karty SD.": "No SD card chosen.",
    "Karta: {card}\n\nWSZYSTKO na tej karcie zostanie usunięte.\n\nMenu:\n{lines}\n\nDATA: {mb} MB\n\nWgrać?":
        "Card: {card}\n\nEVERYTHING on this card will be erased.\n\nMenu:\n{lines}\n\nDATA: {mb} MB\n\nWrite it?",
    "Zapis na kartę…": "Writing the card…",
    "Zapis na kartę (uprawnienia administratora)…": "Writing the card (administrator rights)…",
    "Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia.":
        "The card is ready and checked. Take it out and put it in the radio.",
    "Zapis przerwany (odmowa uprawnień administratora?)": "Writing stopped (administrator rights refused?)",
    "Program zapisujący nie wystartował (odmowa uprawnień?)": "The writer did not start (rights refused?)",
    "Błąd: ": "Error: ",
    "Dodano {name}: {summary}": "Added {name}: {summary}",
    "Pobieranie": "Downloading",
    "Przygotowanie karty": "Preparing the card",
    "Zapis": "Writing",
    "Opróżnianie bufora karty": "Flushing the card's cache",
    "Weryfikacja": "Checking",
    "Rozpakowywanie": "Unpacking",
    "Gotowe": "Done",
    "Wszystkie pliki": "All files",
    # the online dialog
    "Pobierz system z internetu": "Get a system from the internet",
    "Wybierz system i wersję. Najnowsza jest na górze listy.":
        "Choose a system and a version. The newest is at the top of the list.",
    "sprawdzam…": "checking…",
    "Dodaj": "Add",
    "Obrazy pobierane są z wydań projektów na GitHubie i zostają w pamięci podręcznej aplikacji.":
        "The images come from the projects' releases on GitHub and stay in the app's cache.",
    "brak obrazów X6100 w wydaniach": "no X6100 images in the releases",
    "błąd: ": "error: ",
    "Pobieranie {name} {tag}…": "Downloading {name} {tag}…",
    # the catalog
    "Guru-RF: nowe GUI, aktualizacje przez sieć, Wavelog, FT8/JS8":
        "Guru-RF: a new GUI, updates over the network, Wavelog, FT8/JS8",
    "następca R1CBU, rozwijany przez społeczność OpenX6100": "R1CBU's successor, by the OpenX6100 community",
    "CX8ANM: wydania 1.1.x (na bazie OpenX6X00) i wcześniejsze 1.0.x":
        "CX8ANM: the 1.1.x releases (based on OpenX6X00) and the earlier 1.0.x",
    "1KO125 (na bazie OpenX6100): WEFAX, SSTV, NAVTEX, DSC, FT8 CB; na razie wersje testowe":
        "1KO125 (based on OpenX6100): WEFAX, SSTV, NAVTEX, DSC, FT8 CB; test releases so far",
    "IU1WXY (X6100 Link): oprogramowanie zamknięte, na warunkach autora (LICENSE w jego repo)":
        "IU1WXY (X6100 Link): closed software, on its author's terms (LICENSE in its repository)",
    "klasyczne oprogramowanie R1CBU (gdyuldin)": "the classic R1CBU software (gdyuldin)",
    "GitHub chwilowo ogranicza zapytania (limit na godzinę). Spróbuj za kilka minut.":
        "GitHub is limiting requests for now (an hourly limit). Try again in a few minutes.",
    "brak połączenia z GitHubem: {e}": "no connection to GitHub: {e}",
    "nieoczekiwana odpowiedź GitHuba": "an unexpected answer from GitHub",
    "pobieranie przerwane: {e}": "download interrupted: {e}",
    "pobrany plik ma inny rozmiar niż na GitHubie (przerwane pobieranie?)":
        "the downloaded file's size is not GitHub's (an interrupted download?)",
    "suma kontrolna pobranego pliku się nie zgadza": "the downloaded file's checksum does not match",
    # images
    "to obraz instalacyjny Xiegu (wgrywa system do eMMC radia), nie system do uruchamiania z karty. Dodaj pozycję \"Xiegu z eMMC\".":
        "this is Xiegu's installer image (it writes the system to the radio's eMMC), not a system to run "
        "from the card. Add the \"Xiegu from eMMC\" entry.",
    "to już karta multiboot (z tej aplikacji); dodaj obrazy pojedynczych systemów":
        "this is already a multiboot card (made by this app); add the single systems' images",
    "Doom potrzebuje na karcie także systemu z obrazu (np. OpenX6X00): uruchamia się z jego jądrem":
        "Doom needs a system from an image on the card too (e.g. OpenX6X00): it starts with its kernel",
    "rootfs {mb} MB, jądro z: {name}": "rootfs {mb} MB, kernel from: {name}",
    "ta wersja aplikacji nie ma w sobie Dooma": "this build of the app has no Doom in it",
    # the card
    "Start F${bm_default} za ${bm_left} s": "Start F${bm_default} in ${bm_left} s",
    "# Doom: glosnosc efektow i muzyki 0..200 (%)": "# Doom: effects and music volume 0..200 (%)",
    "# Glosnosc radia (AF) 0..55, ustawiana przy starcie Dooma; usun # zeby wlaczyc":
        "# The radio's (AF) volume 0..55, set when Doom starts; remove the # to use it",
    "# Bluetooth: mysz i klawiatura sparowane w systemie, z ktorego Doom bierze jadro (0: wylaczony)":
        "# Bluetooth: mouse and keyboard paired in the system Doom takes its kernel from (0: off)",
    "macOS nie dał dostępu do karty": "macOS did not give access to the card",
    " (odmowa hasła administratora?)": " (administrator password refused?)",
    "domyslny": "default",
    # the Read first window
    "Doom: przeczytaj najpierw": "Doom: read first",
}

DOOM_README = {
    "pl": """Doom na X6100

Doom uruchamia się z jądrem PIERWSZEGO systemu z obrazu na liście (np. OpenX6X00). Kolejność
zmienisz przyciskami W górę / W dół.

Sterowanie radiem
  Gałka VFO: obrót    Gałka VOL: przód/tył, w menu góra/dół    Gałka MFK: broń
  BAND ▲/▼: przód/tył    F1 lub PTT: strzał    F2: drzwi i przełączniki    F3: Enter
  F4/F5: krok w bok    GEN: menu gry    APP: mapa    KEY/MSG: tak/nie    AM: bieg
  POWER: wyłączenie radia. Wyjście z gry wraca do menu startowego.

Mysz i klawiatura USB
  Podłącz do gniazda HOST radia (tego co klawiaturę w OpenX6X00). Obie naraz: przez mały hub
  USB albo jeden odbiornik bezprzewodowy zestawu klawiatura+mysz. Niczego nie trzeba włączać.
  Mysz: lewo/prawo obraca, lewy przycisk strzela, prawy otwiera, kółko zmienia broń.
  Klawiatura: strzałki chodzą i obracają, Ctrl strzela, spacja otwiera, Esc menu, F2/F3 zapis/odczyt.

Mysz i klawiatura Bluetooth
  1. Uruchom na radiu ten pierwszy system z listy (np. OpenX6X00) i sparuj w nim mysz
     i klawiaturę (OpenX6X00: Settings > Bluetooth > DEVICES).
  2. Wyłącz radio normalnie, uruchom Dooma.
  3. Rusz myszą albo naciśnij klawisz: połączą się same po kilku sekundach.
  Doom korzysta z Bluetooth tamtego systemu i jego zapisanych parowań, niczego w nim nie zmieniając.
  Działa z OpenX6X00, CX8ANM, OpenX6100 i 1KO125. Z klasycznym R1CBU działa tylko USB.

Dźwięk
  Efekty i muzyka. Plik doom.txt na partycji BOOT karty: volume= i music= (0–200 %),
  rxvol=20 (po usunięciu #) gdyby nic nie było słychać, bluetooth=0 wyłącza Bluetooth.
""",
    "en": """Doom on the X6100

Doom starts with the kernel of the FIRST system from an image on the list (e.g. OpenX6X00). Change
the order with Up / Down.

The radio's controls
  VFO knob: turn    VOL knob: forward/back, up/down in the menus    MFK knob: weapon
  BAND ▲/▼: forward/back    F1 or PTT: fire    F2: doors and switches    F3: Enter
  F4/F5: strafe    GEN: the game's menu    APP: map    KEY/MSG: yes/no    AM: run
  POWER: switches the radio off. Leaving the game goes back to the boot menu.

USB mouse and keyboard
  Plug them into the radio's HOST port (where a keyboard goes in OpenX6X00). Both at once: through
  a small USB hub, or one wireless receiver of a keyboard+mouse set. Nothing to switch on.
  Mouse: left/right turns, the left button fires, the right one opens, the wheel picks the weapon.
  Keyboard: the arrows walk and turn, Ctrl fires, Space opens, Esc menu, F2/F3 save/load.

Bluetooth mouse and keyboard
  1. Start that first system of the list on the radio (e.g. OpenX6X00) and pair the mouse and the
     keyboard there (OpenX6X00: Settings > Bluetooth > DEVICES).
  2. Switch the radio off normally, start Doom.
  3. Move the mouse or press a key: they connect by themselves after a few seconds.
  Doom uses that system's Bluetooth and its saved pairings, changing nothing in it.
  Works with OpenX6X00, CX8ANM, OpenX6100 and 1KO125. With the classic R1CBU only USB works.

Sound
  Effects and music. The doom.txt file on the card's BOOT partition: volume= and music= (0–200 %),
  rxvol=20 (without the #) if nothing can be heard, bluetooth=0 switches Bluetooth off.
""",
}
