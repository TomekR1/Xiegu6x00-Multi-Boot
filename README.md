# Xiegu Multi Patcher

Kilka systemów na jednej karcie SD dla **Xiegu X6100**. Przy włączaniu radia na ekranie
pojawia się menu z logo każdego systemu, a system wybierasz klawiszem **F1–F5** pod ekranem.
Bez wciśnięcia klawisza po kilku sekundach startuje system domyślny, a klawisz **POWER** w menu
wyłącza radio. W menu może być też
oryginalny **system Xiegu z pamięci radia (eMMC)**; aplikacja niczego w eMMC nie zmienia.

Autor aplikacji: [SQ6RT](https://www.qrz.com/db/SQ6RT) · [English below](#english)

## Pobieranie

Najnowsza wersja jest w zakładce **[Releases](../../releases/latest)**:

| Plik | System |
|---|---|
| `Xiegu-Multi-Patcher-Windows.zip` | Windows 10/11: rozpakuj (prawy przycisk → Wyodrębnij wszystkie) i uruchom `Xiegu Multi Patcher.exe` z folderu |
| `Xiegu-Multi-Patcher-macOS.zip` | macOS: rozpakuj, przenieś do Programów; za pierwszym razem macOS ją zablokuje: **Ustawienia systemowe → Prywatność i ochrona → Otwórz mimo to** (albo w Terminalu `xattr -dr com.apple.quarantine "/Applications/Xiegu Multi Patcher.app"`) |
| `Xiegu-Multi-Patcher-Linux.zip` | Linux x86-64: rozpakuj i uruchom `Xiegu Multi Patcher` z folderu; do zapisu karty potrzebny `pkexec` |

**Instrukcja krok po kroku:** [INSTRUKCJA.html](INSTRUKCJA.html) (polski) i [INSTRUCTIONS.html](INSTRUCTIONS.html) (English). Oba pliki są też w każdej paczce z aplikacją; otwierasz je w przeglądarce.

Każda wersja aplikacji ma swój numer (Windows, macOS i Linux osobno, w tytule okna aplikacji i w nazwie wydania): poprawka tylko pod Windows podnosi tylko numer Windows.

Nic nie trzeba instalować. Aplikacja jest po polsku i po angielsku (wybór języka w prawym górnym
rogu okna). Systemów radia nie ma w wydaniu: wybierasz je i pobierasz
w aplikacji, prosto z wydań ich autorów.

## Jak przygotować kartę

1. **+ Z internetu…**: wybierz system i wersję (najnowsza jest zaznaczona) i kliknij **Dodaj**.
   Aplikacja pobierze obraz i sprawdzi go. Możesz dodać do 5 pozycji.
   Obraz z dysku dodasz przyciskiem **+ Obraz karty…** (`.img`, `.img.zip`, `.img.xz`).
   **Zaawansowane:** na dole tego okna możesz dopisać **własne repozytorium GitHub** (np. fork albo
   system spoza listy): wpisz `właściciel/repozytorium` albo adres z github.com. Aplikacja pokaże obrazy kart
   X6100 z jego wydań (`.img`, `.img.zip`, `.img.xz`; obrazy dla X6200 pomija) i pobierze je jak pozostałe
   systemy, ze sprawdzeniem rozmiaru i sumy SHA-256. Lista zostaje zapisana na komputerze; **Usuń z listy**
   ją skraca. Dodawaj tylko repozytoria, którym ufasz.
2. **+ Xiegu z eMMC**: pozycja w menu, która uruchamia oryginalny system radia.
3. Aplikacja od razu pokazuje menu dokładnie tak, jak wyświetli je radio. Kliknij kafelek, żeby go
   zaznaczyć: strzałkami **← →** zmienisz kolejność, **★ Domyślny** ustawia system startujący sam,
   dwuklik albo **Zmień nazwę** zmienia napis, a **Logo…** podmienia logo na własny obrazek PNG/JPG.
4. Wybierz **czas na wybór** (0–15 s) i **partycję DATA** (patrz niżej). Opcja **Bez automatycznego
   startu** wyłącza odliczanie: radio czeka, aż wciśniesz klawisz F wybranego systemu.
5. Włóż kartę SD do komputera, wybierz ją na liście i kliknij **Wgraj na kartę**.
   System poprosi o hasło administratora; po zapisie aplikacja sprawdza, czy wszystko się zgadza.
   Sprawdzanie można wyłączyć (**Sprawdź kartę po zapisie**) albo przerwać w trakcie przyciskiem
   **Pomiń sprawdzanie karty**; wtedy uszkodzona karta nie zostanie wykryta.
   Zamiast tego możesz kliknąć **Zapisz jako plik .img…** i wgrać plik balenaEtcherem.

Co aplikacja robi i ile jeszcze potrwa, widać cały czas na dole okna: nazwa operacji, etap
(„Etap 2 z 4”), pasek, procenty, prędkość i pozostały czas.

**Ustawienia ze starej karty.** Ustawienia radia (baza ustawień, log QSO, logi, a w OpenX6X00 także
sieci WiFi, klucze SSH i parowania Bluetooth) są na partycji **DATA**. Zaznaczone **Przenieś ustawienia
ze starej karty** robi przed skasowaniem karty kopię DATA każdego systemu (pliki `.zip` w folderze
`Dokumenty/Xiegu Multi Patcher/DATA`) i wgrywa ją na nowej karcie do tego samego systemu, bez względu na
jego miejsce w menu i numer wersji. Po zapisie aplikacja wypisuje, co trafiło gdzie.

**Kopie ustawień (DATA)**, na dole okna:

- **Kopie DATA karty w czytniku…**: lista systemów na karcie, przy każdym **Kopia na komputer…**
  i **Przywróć z kopii…**, do tego **Kopia wszystkich systemów na komputer**. Kopia pamięta, z którego
  systemu pochodzi; przy przywracaniu do innego aplikacja ostrzega. Przywracanie zastępuje zawartość DATA.
- **Własna kopia DATA dla nowej karty…**: wskazana kopia trafi na nowo zapisywaną kartę.

Kopią może być plik `.zip` albo folder z plikami luzem. Aplikacja pokazuje nazwę, położenie i zawartość
wybranej kopii, sprawdza, czy wygląda na DATA z radia, i wgrywa ją dopiero po zatwierdzeniu. Kopię
spakowaną razem z folderem („folder w folderze”) rozpoznaje i wgrywa samą zawartość.

Zapis kasuje całą zawartość wybranej karty. Aplikacja pokazuje tylko karty wymienne
i nigdy dysku systemowego, ale sprawdź nazwę i rozmiar karty przed potwierdzeniem.

## Extras: Doom

W sekcji **Extras** jest kafelek **Doom**: klasyczny Doom na X6100, z darmowymi mapami i grafiką
[Freedoom](https://freedoom.github.io/). Dodaje się go do menu jak system (potrzebny jest na
karcie co najmniej jeden system z obrazu, bo Doom uruchamia się z jego jądrem).

| Na radiu | W grze |
|---|---|
| gałka VFO | obrót |
| gałka VOL | do przodu / do tyłu, w menu góra / dół |
| gałka MFK | zmiana broni |
| BAND ▲ / ▼ | do przodu / do tyłu |
| F1 albo PTT | strzał |
| F2 | użyj (drzwi, przełączniki) |
| F3 | Enter |
| F4 / F5 | krok w bok |
| GEN | menu gry |
| APP | mapa |
| KEY / MSG | tak / nie |
| AM | bieg |
| POWER | wyłączenie radia |

Działa też **myszka** (lewo/prawo obraca, góra/dół idzie do przodu i do tyłu, lewy przycisk strzela,
prawy otwiera drzwi, kółko zmienia broń) i **klawiatura** (W/S do przodu i do tyłu, A/D krok w bok,
strzałki chodzą i obracają, Ctrl strzela, spacja otwiera, Esc to menu, F2/F3 zapis i wczytanie gry). Podłącza się je do gniazda **HOST** radia
(tego samego co klawiaturę w OpenX6X00), obie naraz przez mały hub USB albo jeden odbiornik
bezprzewodowy zestawu klawiatura+mysz. Niczego nie trzeba włączać w menu radia: Doom sam ładuje
sterownik gniazda HOST z systemu, z którego bierze jądro. Działają też podłączone w trakcie gry.

**Mysz i klawiatura Bluetooth:** Doom bierze jądro z **pierwszego systemu z obrazu na liście**
i to w nim trzeba je raz sparować (np. OpenX6X00: Settings > Bluetooth > DEVICES). Potem wyłącz
radio, uruchom Dooma i rusz myszą albo naciśnij klawisz: połączą się same w ciągu około minuty. Doom
uruchamia obsługę Bluetooth tamtego systemu z jego zapisanymi parowaniami, niczego w nim nie
zmieniając. Działa z OpenX6X00, CX8ANM, OpenX6100 i 1KO125; z klasycznym R1CBU działa tylko USB.
`bluetooth=0` w `doom.txt` wyłącza Bluetooth w Doomie. To samo opisuje w aplikacji przycisk
**Przeczytaj najpierw** obok kafelka Dooma.

Dźwięk: efekty i **muzyka** (syntezator OPL3, jak karta AdLib/Sound Blaster, emulowany przez
Nuked OPL3), na głośniku radia. Na partycji `BOOT` karty jest plik `doom.txt`: `volume=`
i `music=` to głośność efektów i muzyki (0–200 %), `rxvol=` głośność głośnika radia (0–55,
domyślnie 45), `headphone=` poziom wyjścia dźwięku do płyty radia (0–63; przy trzeszczeniu mniej),
`rxmute=1` przycisza odbiornik radia na czas gry (bez szumu w tle). Doom zapisuje też na tej
partycji dziennik `doom-log.txt`: co znalazł (dźwięk, USB, Bluetooth), przydatny przy zgłaszaniu problemu.

Wyjście z gry **wyłącza radio**: X6100 nie umie zrestartować się z Linuksa, więc nie wraca samo do menu
startowego. Inny system wybierzesz po włączeniu radia klawiszem POWER.

## Extras: emulator NES

Kafelek **+ Emulator NES** dodaje do menu radia emulator NES/Famicom (rdzeń
[FCEUmm](https://github.com/libretro/libretro-fceumm), obsługuje też kartridże z Pegasusa).
Uruchamia się, jak Doom, z jądrem pierwszego systemu z obrazu na liście.

**Gry:** aplikacja nie zawiera żadnej gry. Własne (`.nes`, `.fds`, `.unf`, `.nsf`, także w `.zip`)
dodajesz przyciskiem **Gry NES…** przy tworzeniu karty albo później: kopiujesz je do folderu `NES`
na partycji `BOOT` karty (widać ją na każdym komputerze). Podfoldery działają. Zapisy gier
(baterie i stany) trafiają do `NES/SAVES`, gry z dyskietek FDS potrzebują `NES/BIOS/disksys.rom`.

**Sterowanie radiem (gracz 1):** BAND ▲/▼, DFN i DFL to krzyżak, F1 lub PTT to A, F2 to B,
F3 Select, F4 Start, F5 A turbo. Gałka VFO lewo/prawo, gałka VOL to głośnik radia.
Wciśnięty MFK albo GEN otwiera w grze menu (po menu chodzi się gałką MFK): powrót do gry, gra od nowa,
rozmiar obrazu, zapis i odczyt stanu, wyjście do listy gier, wyłączenie radia. Menu główne emulatora to kafelki: lista gier
(obok obrazek gry, jeśli jest plik `.png`/`.jpg`/`.bmp` o nazwie gry obok niej albo w `NES/IMG`), sterowanie
(klawisze i własny układ przycisków pada), Bluetooth, wyłączenie radia. W długiej liście gier przytrzymany
kierunek przewija coraz szybciej, lewo/prawo skacze do następnej litery, gałka VFO o stronę.

**WiFi, strona z grami, aktualizacja:** kafelek **WiFi** łączy radio z siecią (hasło na klawiaturze
ekranowej albo z klawiatury USB/Bluetooth; sieć zapamiętuje się jako klucz PSK, bez hasła). Po połączeniu
radio wystawia stronę `http://<adres radia>/`, na której z przeglądarki w tej samej sieci wgrywasz i
usuwasz gry z folderu `NES` (strona nie ma hasła: każdy w tej sieci ją widzi). W menu WiFi jest też
**Aktualizacja emulatora**: pobiera najnowszy obraz emulatora z wydań na GitHubie, sprawdza sumę SHA-256,
zapisuje go na partycję emulatora i wyłącza radio. Nie wyłączaj radia w trakcie zapisu. Do tego wszystkiego
emulator używa programów systemu OpenX6X00 z karty (wpa_supplicant, Python). POWER wyłącza radio.

**Klawiatura, mysz, pady (USB i Bluetooth):** klawiatura: strzałki lub WASD, X/K = A, Z/J = B,
Enter = Start, Shift lub spacja = Select, C/V = turbo, Esc = menu, F2/F4 = szybki zapis/odczyt.
Mysz to pistolet Zapper w grach, które go używają (np. Duck Hunt). Pady: pierwszy to gracz 1,
drugi gracz 2, menu przyciskiem Home albo Select+Start razem. Działają pady HID (8BitDo w trybie
D-input lub Switch, PS4 i Xbox przez Bluetooth, zwykłe pady USB); przewodowe pady Xbox 360 nie,
bo jądro radia nie ma ich sterownika. Inny układ przycisków ustawisz w menu: **Przyciski pada**
(zapisuje się w `NES/pads.txt`). Menu **Bluetooth** w emulatorze: parowanie padów, klawiatur i myszy
(szuka na żywo, kod do wpisania pokazuje na ekranie), lista sparowanych (połącz, rozłącz, usuń),
wł./wył. Bluetooth.

Wyjście z gry zapamiętuje miejsce (przy następnym uruchomieniu „Kontynuuj od miejsca wyjścia”),
lista gier zaczyna od ostatnio granej, a menu w grze ma ekran „Sterowanie” ze ściągą klawiszy.

Ustawienia: plik `nes.txt` na partycji `BOOT` (`volume=`, `rxvol=`, `aspect=2x` albo `4:3`,
`mouse=` szybkość Zappera, `bluetooth=`, `lang=`). Dziennik: `nes-log.txt`.

## Extras: menu mówione (alfa)

Dla niewidomych operatorów: **+ Menu mówione (alfa)** dodaje do menu radia pozycję, która czyta wybór na
głos przez głośnik radia. Gdy przy włączaniu nikt nie wciśnie klawisza na ekranie (czas warto ustawić na 3 s),
menu mówi: „Boot menu. Press F1 for …”. Po wciśnięciu F1–F5 radio się wyłącza i prosi o klawisz POWER
(X6100 nie umie zrestartować się z Linuksa), a po włączeniu od razu startuje wybrany system. Bez wyboru po
30 s startuje system z ★. Ustawienia: `talkmenu.txt` na partycji BOOT.

Program menu to **talkmenu** z projektu [X6100 Talking MultiBoot](https://github.com/Jimr9/X6100-Talking-MultiBoot)
Jima Ruiza (GPL-2.0-or-later), a głos to **RHVoice Lyubov** (Artem Plaksin, Sergey Parshakov, Beka Gozalishvili,
Lyubov Sablina; CC BY-NC-ND 4.0, użycie niekomercyjne). Aplikacja składa nagrania dla każdej karty z krótkich
fragmentów tego głosu: nazwy systemów, numery wersji, klawisze. Uruchamia się jak Doom, z jądrem pierwszego
systemu z obrazu (np. OpenX6X00), i odtwarza dźwięk jego programami (`aplay`, `amixer`).

## Systemy do pobrania w aplikacji

| System | Źródło |
|---|---|
| OpenX6X00 | [Guru-RF/OpenX6X00](https://github.com/Guru-RF/OpenX6X00) |
| OpenX6100 (następca R1CBU) | [OpenX6100/x6100_gui](https://github.com/OpenX6100/x6100_gui) |
| CX8ANM | [condoruy/OpenX6X00-CX8ANM](https://github.com/condoruy/OpenX6X00-CX8ANM) (1.1.x, na bazie OpenX6X00 i z jego wyglądem), [condoruy/X6100-CX8ANM](https://github.com/condoruy/X6100-CX8ANM) (1.0.x) |
| 1KO125 | [TheMurusTeam/x6100_gui](https://github.com/TheMurusTeam/x6100_gui) |
| IU1WXY (X6100 Link) | [IU1WXY/X6100-IU1WXY](https://github.com/IU1WXY/X6100-IU1WXY): oprogramowanie zamknięte; aplikacja pobiera obraz z wydań autora i kopiuje go na kartę bez zmian, zgodnie z jego [warunkami](https://github.com/IU1WXY/X6100-IU1WXY/blob/main/LICENSE) |
| R1CBU (klasyczny) | [gdyuldin/x6100_gui](https://github.com/gdyuldin/x6100_gui) |

Logo w menu każdy system dostaje ze swojego repozytorium. Systemy bez logo do pobrania
(i IU1WXY, którego grafiki aplikacja nie używa) mają kafelek z nazwą.

## Partycja DATA: osobna albo wspólna

DATA to partycja z ustawieniami i logami systemów.

- **Osobna (domyślnie):** każdy system ma własne ustawienia i logi. Komputer pokazuje jako dysk tylko
  DATA systemu uruchomionego ostatnio; do pozostałych sięga aplikacja (**Kopie DATA karty w czytniku…**).
- **Wspólna:** jedna DATA dla wszystkich systemów.

Doom i Xiegu z pamięci radia nie mają własnej DATA.

## Zmiany bez ponownego wgrywania karty

Na partycji `BOOT` karty jest plik `bootmenu.env`. Można go zmienić na komputerze:

```
bm_default=1
bm_secs=5
bm_wait=0
```

`bm_default` to klawisz systemu domyślnego (1 = F1), `bm_secs` to czas na wybór w sekundach
(0–15), a `bm_wait=1` wyłącza automatyczny start (menu czeka na klawisz). Nie dopisuj komentarzy na końcu linii.

## Aktualizacje systemów

Systemy aktualizowane z poziomu radia (np. OpenX6X00: Settings → Info → Update) zmieniają
tylko swoje pliki, więc menu zostaje. Nową wersję, która wymaga nowego obrazu karty,
dodajesz w aplikacji i wgrywasz kartę od nowa.

## Problemy i uwagi

Zgłaszaj je w zakładce **[Issues](../../issues)**. Pomaga:

- system komputera (Windows / macOS / Linux) i zrzut ekranu z błędem;
- plik `Dokumenty/Xiegu Multi Patcher/log.txt` z komputera;
- zdjęcie ekranu radia, jeśli coś dzieje się przy starcie;
- które systemy były na karcie i który klawisz został wciśnięty.

Jeśli system Xiegu z eMMC się nie uruchomi, menu pokaże na ekranie zawartość eMMC:
zrób zdjęcie i dołącz je do zgłoszenia.

**Windows Defender albo SmartScreen ostrzega przed aplikacją.** Aplikacja nie jest podpisana certyfikatem
(płatnym), więc Windows jej „nie zna”. Od wersji z folderem w `.zip` aplikacja nie zmienia ustawień
systemu ani nie zamyka okien innych programów; kartę przygotowuje systemowym `diskpart`. Jeśli mimo to
Defender ją zatrzyma, zgłoś fałszywy alarm na https://www.microsoft.com/wdsi/filesubmission (plik `.exe`
z folderu).

## English

Several systems on one SD card for the **Xiegu X6100**: at power-on the radio shows a menu with
each system's logo, and you choose with the **F1–F5** keys under the screen. Without a key the
default system starts after a few seconds. The menu can also start Xiegu's original system from
the radio's internal memory (eMMC); the app changes nothing there.

The app (Windows, macOS, Linux; from **[Releases](../../releases/latest)**, nothing to install;
on Windows unpack `Xiegu-Multi-Patcher-Windows.zip` and run `Xiegu Multi Patcher.exe` from the folder)

**Step-by-step guide:** [INSTRUCTIONS.html](INSTRUCTIONS.html) (English) and [INSTRUKCJA.html](INSTRUKCJA.html) (Polish), also in every app package
speaks English and Polish: pick the language at the top right of its window.

1. **+ From the internet…** fetches a system's image straight from its authors' GitHub releases
   (OpenX6X00, OpenX6100, CX8ANM, 1KO125, IU1WXY, R1CBU); **+ Card image…** adds one from disk.
   Advanced: at the bottom of that window you can add **your own GitHub repository** (owner/repo or its
   github.com address); the X6100 card images in its releases are listed and fetched like the others.
2. **+ Xiegu from eMMC** adds the radio's own system.
3. The app shows the menu just as the radio will: click a tile, then move it (**← →**), make it
   the default (★), rename it (double-click) or give it a logo of your own.
4. Choose the time to choose (0–15 s) or **no automatic start** (the radio waits for an F key),
   and a **per-system** (the default) or **shared DATA** partition.
5. **Write to the card** (it asks for the administrator password, then checks what it wrote; the
   check can be left out or skipped while it runs), or **Save as an .img file…** for balenaEtcher.
   Writing erases the whole card. What the app is doing, and how long it still takes, is shown at
   the bottom of its window.

**Settings (DATA).** Each system keeps its settings on its own DATA. **Carry the settings over from
the old card** copies each system's DATA to the computer before the card is erased and puts it back
into the same system on the new card, wherever it now stands in the menu. **DATA copies of the card
in the reader…** saves or restores each system's DATA on its own; **Own DATA copy for the new card…**
puts a copy of your own (a `.zip` or a folder) on the card being written.

**Extras: Doom.** Classic Doom with [Freedoom](https://freedoom.github.io/)'s maps, sound and OPL3
music, on the radio's knobs and keys, a USB mouse and keyboard on the HOST port, or Bluetooth ones
paired in the first image-based system of the list. The **Read first** button next to the Doom
tile explains the controls and the pairing; `doom.txt` on the card's BOOT partition sets the volume.

**Extras: NES emulator.** The [FCEUmm](https://github.com/libretro/libretro-fceumm) core with an
X6100 front end. No game comes with it: add your own (`.nes`, `.fds`, `.unf`, `.nsf`, or `.zip`s of
them) with **NES games…**, or later in the `NES` folder of the card's BOOT partition. The radio's
keys and knobs, USB and Bluetooth keyboards, mice (the Zapper) and HID pads for two players; pads
are paired and their buttons set in the emulator's own menu (GEN). Settings: `nes.txt`.

## Licencja

Aplikacja: **GPL-3.0** ([LICENSE](LICENSE)), © SQ6RT. Poprawka U-Boot w `uboot/` (inicjalizacja
ekranu przeniesiona ze sterownika Linuksa X6100) jest, jak U-Boot, na licencji GPL-2.0-or-later.
Systemy radia i ich loga należą do ich autorów; aplikacja pobiera je z ich wydań i repozytoriów.
Wygląd okna: motyw [Sun Valley](https://github.com/rdbende/Sun-Valley-ttk-theme) (sv-ttk, licencja MIT).
Ikona Dooma jest narysowana dla tej aplikacji (napis czcionką Inter, licencja SIL OFL), ikona
emulatora NES też (`tools/make_nes_icon.py`). Emulator NES: rdzeń FCEUmm (GPL-2.0), menu czcionką
Inter (SIL OFL 1.1, wypalaną przy budowaniu przez `extras/nes/make_font.py`).

---

## Dla programistów

### Uruchamianie ze źródeł

Python 3.9+ i Tk (na Linuksie pakiet `python3-tk`), opcjonalnie Pillow (menu graficzne), certifi
i sv-ttk (wygląd okna):

```
python x6100_multiboot.py                        # okno
python x6100_multiboot.py catalog                # systemy do pobrania i ich wersje
python x6100_multiboot.py build -o karta.img --xiegu --data separate openx6x00@latest cx8anm@latest
python x6100_multiboot.py info OBRAZ...
python -m unittest discover -s tests
```

### Układ karty

| Miejsce | Zawartość |
|---|---|
| 8 KiB | U-Boot menu (`uboot/`) |
| p1 `BOOT` (FAT32) | `boot.scr` (menu), `boot.cmd` (to samo tekstem), `bootmenu.env`, `menu.txt`, `MENU/*.BMP`, `SYS1/`…`SYS5/` z jądrem, `.dtb` i (przy osobnej DATA) `MBR.BIN` |
| p2 | system plików systemu 1, kopia bajt w bajt |
| p5, p6, … (w p4) | systemy plików kolejnych systemów |
| p3 `DATA` (FAT32) | DATA (przy osobnej: DATA ostatnio uruchomionego systemu; pozostałe leżą za nią) |

Każdy system startuje z `root=/dev/mmcblk0pN` swojej partycji. Przy osobnej DATA U-Boot przed
startem systemu zapisuje sektor 0 karty z jego tablicą partycji (`SYSn/MBR.BIN`), ale tylko
wtedy, gdy się zmienia; systemy widzą swoją DATA jako trzecią partycję z etykietą `DATA`.

Pozycja Xiegu wczytuje `zImage` i `sun8i-r16-x6100.dtb` z `mmc 1:1` z
`root=/dev/mmcblk2p2`, tak jak zapisuje je instalator Xiegu; parametry są w `bootmenu.env`
(`xiegu_*`). Obraz aktualizacji Xiegu (instalator eMMC) aplikacja rozpoznaje i odrzuca.

### Menu w U-Boot

Menu to skrypt U-Boot (`boot.scr`). Klawisze są odczytywane z matrycy GPIO panelu, tak jak
w multiboot projektu [x6100-fw-mangler](https://github.com/j0ju/x6100-fw-mangler): wiersz
w stan niski (`gpio clear PG6`), odczyt kolumn (`gpio input PE16`, 0 = wciśnięty).
F1/F2/F3 = kolumny PE16/PE17/PE11 w wierszu PG6, F4/F5 = PE16/PE17 w wierszu PG8.
Obraz menu (8-bit BMP, obrócony do układu ekranu) rysuje `bmp display`, odliczanie
i teksty idą przez `vidconsole` z kodami ANSI.

### U-Boot z obsługą ekranu (`uboot/`)

Ekran X6100 (kontroler Sitronix ST7701S, panel JLT4013A 480×800) trzeba zainicjować sekwencją
poleceń przez SPI, czego U-Boot z obrazów systemów nie robi. `uboot/build.sh` buduje U-Boot
v2026.07 z:

- inicjalizacją ST7701S przeniesioną ze sterownika Linuksa (`panel-jinglitai-jlt4013a.c`,
  GPL-2.0), wysyłaną programowym SPI na pinach PL7 (CS), PL8 (MOSI), PL9 (SCK), PL10 (D/C);
- konsolą obróconą o 270° (jak `fbcon=rotate:3`), czcionką 16×32, kolorami ANSI i `bmp display`.

### Doom (`extras/doom/`)

`doomgeneric_x6100.c` to warstwa [doomgeneric](https://github.com/ozkl/doomgeneric) dla radia,
(`x6100_sound.c`: efekty przez tinyalsa, muzyka z odtwarzacza OPL [Chocolate Doom](https://github.com/chocolate-doom/chocolate-doom)
z emulatorem Nuked OPL3, `opl_x6100.c`),
uruchamiana jako `/sbin/init` własnego, małego systemu plików: obraz 320×200 skalowany do 640×480
na obróconym framebufferze, klawisze i gałki z `/dev/input`. `build.sh` buduje ją statycznie na
ARM, dokłada Freedoom i składa partycję ext4; aplikacja ma ją w sobie i uruchamia z jądrem
pierwszego systemu z obrazu na karcie (wszystkie potrzebne sterowniki są w nim wbudowane).

### Emulator NES (`extras/nes/`)

`nes_x6100.c` to mała nakładka libretro z rdzeniem FCEUmm wlinkowanym statycznie, też jako
`/sbin/init` własnego systemu plików: menu gier i ustawień rysowane na framebufferze, obraz
256×224 w 2× (albo 4:3), dźwięk przez tinyalsa (gra trzyma tempo bufora karty dźwiękowej),
wejście z `/dev/input` (klawisze radia, klawiatury, myszy, pady HID), Bluetooth z systemu,
z którego pochodzi jądro, w chroot (parowanie padów w menu, zapisywane na partycji emulatora).
Bluetooth prowadzi rozmowę z `bluetoothctl` systemu, z którego pochodzi jądro, na pseudoterminalu:
czyta każdą linię i sam odpowiada na pytania o potwierdzenie, kod i PIN.
`build.sh` buduje rdzeń i nakładkę na ARM i na PC i sprawdza na PC: własny testowy kartridż
(niebieski ekran i ton 440 Hz: obraz i dźwięk), Bluetooth z udawanym `bluetoothctl`
(`test/fake_bluetoothctl.py`: parowanie z potwierdzeniem i z kodem klawiatury, łączenie) oraz
wejście z potoków (`test/drive_input.py`: pad, klawiatura, mysz, nauka przycisków). Potem składa
partycję ext4 (bez żadnej gry).

### Budowanie

`.github/workflows/build.yml`: testy, U-Boot, aplikacje (PyInstaller) na Windows, macOS
i Linux oraz sprawdzenie na żywo (aplikacja pobiera najnowsze systemy i składa z nich kartę).
Wydanie powstaje z tagu `v*`. Ikonę rysuje `tools/make_icon.py`.
