# Xiegu Multi Patcher

Kilka systemów na jednej karcie SD dla **Xiegu X6100**. Przy włączaniu radia na ekranie
pojawia się menu z logo każdego systemu, a system wybierasz klawiszem **F1–F5** pod ekranem.
Bez wciśnięcia klawisza po kilku sekundach startuje system domyślny. W menu może być też
oryginalny **system Xiegu z pamięci radia (eMMC)**; aplikacja niczego w eMMC nie zmienia.

Autor aplikacji: [SQ6RT](https://www.qrz.com/db/SQ6RT)

## Pobieranie

Najnowsza wersja jest w zakładce **[Releases](../../releases/latest)**:

| Plik | System |
|---|---|
| `Xiegu-Multi-Patcher.exe` | Windows 10/11 |
| `Xiegu-Multi-Patcher-macOS.zip` | macOS: rozpakuj, przy pierwszym uruchomieniu prawy klik → **Otwórz** |
| `Xiegu-Multi-Patcher-Linux` | Linux x86-64: `chmod +x Xiegu-Multi-Patcher-Linux`; do zapisu karty potrzebny `pkexec` |

Nic nie trzeba instalować. Systemów radia nie ma w wydaniu: wybierasz je i pobierasz
w aplikacji, prosto z wydań ich autorów.

## Jak przygotować kartę

1. **+ Z internetu…**: wybierz system i wersję (najnowsza jest zaznaczona) i kliknij **Dodaj**.
   Aplikacja pobierze obraz i sprawdzi go. Możesz dodać do 5 pozycji.
   Obraz z dysku dodasz przyciskiem **+ Obraz karty…** (`.img`, `.img.zip`, `.img.xz`).
2. **+ Xiegu z eMMC**: pozycja w menu, która uruchamia oryginalny system radia.
3. Ustaw kolejność (**W górę / W dół**), nazwy (dwuklik na liście) i system domyślny
   (**Domyślny**, ★). **Logo…** podmienia logo na własny obrazek PNG/JPG.
   **Podgląd menu** pokazuje, jak menu będzie wyglądać na ekranie radia.
4. Wybierz **czas na wybór** (0–9 s) i **partycję DATA** (patrz niżej).
5. Włóż kartę SD do komputera, wybierz ją na liście i kliknij **Wgraj na kartę**.
   System poprosi o hasło administratora; po zapisie aplikacja sprawdza, czy wszystko się zgadza.
   Zamiast tego możesz kliknąć **Zapisz jako plik .img…** i wgrać plik balenaEtcherem.

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

Działa też **myszka USB** (ruch w lewo/prawo obraca, lewy przycisk strzela, prawy otwiera drzwi,
kółko zmienia broń) i **klawiatura USB** (strzałki: do przodu/do tyłu i obrót, Ctrl strzela, spacja
otwiera, Esc to menu, F2/F3 zapis i wczytanie gry). Podłącza się je do gniazda **HOST** radia
(tego samego co klawiaturę w OpenX6X00), obie naraz przez mały hub USB albo jeden odbiornik
bezprzewodowy zestawu klawiatura+mysz. Niczego nie trzeba włączać w menu radia: Doom sam ładuje
sterownik gniazda HOST z systemu, z którego bierze jądro. Działają też podłączone w trakcie gry.

**Mysz i klawiatura Bluetooth:** sparuj je raz w systemie, z którego Doom bierze jądro (np. OpenX6X00:
Settings > Bluetooth > DEVICES). W Doomie łączą się same: Doom uruchamia obsługę Bluetooth tamtego
systemu (z jego zapisanymi parowaniami z partycji DATA), niczego w nim nie zmieniając. Przy
osobnych partycjach DATA Doom korzysta z DATA tego systemu. `bluetooth=0` w `doom.txt` wyłącza
Bluetooth w Doomie.

Dźwięk: efekty i **muzyka** (syntezator OPL3, jak karta AdLib/Sound Blaster, emulowany przez
Nuked OPL3). Na partycji `BOOT` karty jest plik `doom.txt`: `volume=` i `music=` to głośność
efektów i muzyki (0–200 %), a `rxvol=` (po usunięciu `#`) ustawia przy starcie Dooma głośność
radia (0–55), gdyby nic nie było słychać.

Wyjście z gry wraca do menu startowego.

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

## Partycja DATA: wspólna albo osobna

DATA to partycja z ustawieniami i logami systemów.

- **Wspólna:** jedna DATA dla wszystkich systemów.
- **Osobna:** każdy system ma własne ustawienia i logi. Na komputerze widać DATA systemu,
  który był uruchomiony ostatnio.

## Zmiany bez ponownego wgrywania karty

Na partycji `BOOT` karty jest plik `bootmenu.env`. Można go zmienić na komputerze:

```
bm_default=1
bm_secs=5
```

`bm_default` to klawisz systemu domyślnego (1 = F1), `bm_secs` to czas na wybór w sekundach
(0–9). Nie dopisuj komentarzy na końcu linii.

## Aktualizacje systemów

Systemy aktualizowane z poziomu radia (np. OpenX6X00: Settings → Info → Update) zmieniają
tylko swoje pliki, więc menu zostaje. Nową wersję, która wymaga nowego obrazu karty,
dodajesz w aplikacji i wgrywasz kartę od nowa.

## Problemy i uwagi

Zgłaszaj je w zakładce **[Issues](../../issues)**. Pomaga:

- system komputera (Windows / macOS / Linux) i zrzut ekranu z błędem;
- zdjęcie ekranu radia, jeśli coś dzieje się przy starcie;
- które systemy były na karcie i który klawisz został wciśnięty.

Jeśli system Xiegu z eMMC się nie uruchomi, menu pokaże na ekranie zawartość eMMC:
zrób zdjęcie i dołącz je do zgłoszenia.

## Licencja

Aplikacja: **GPL-3.0** ([LICENSE](LICENSE)), © SQ6RT. Poprawka U-Boot w `uboot/` (inicjalizacja
ekranu przeniesiona ze sterownika Linuksa X6100) jest, jak U-Boot, na licencji GPL-2.0-or-later.
Systemy radia i ich loga należą do ich autorów; aplikacja pobiera je z ich wydań i repozytoriów.

---

## Dla programistów

### Uruchamianie ze źródeł

Python 3.9+ i Tk (na Linuksie pakiet `python3-tk`), opcjonalnie Pillow (menu graficzne) i certifi:

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

### Budowanie

`.github/workflows/build.yml`: testy, U-Boot, aplikacje (PyInstaller) na Windows, macOS
i Linux oraz sprawdzenie na żywo (aplikacja pobiera najnowsze systemy i składa z nich kartę).
Wydanie powstaje z tagu `v*`. Ikonę rysuje `tools/make_icon.py`.
