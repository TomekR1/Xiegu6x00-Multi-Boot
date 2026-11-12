# Xiegu6x00 Multi-Boot: Xiegu Multi Patcher

## Pobieranie

Gotowe pliki są w zakładce **[Releases](../../releases)**:

| Plik | Dla |
|---|---|
| `Xiegu-Multi-Patcher.exe` | Windows 10/11 (poprosi o uprawnienia administratora) |
| `Xiegu-Multi-Patcher-macOS.zip` | macOS (rozpakuj; za pierwszym razem prawy klik > Otwórz) |
| `Xiegu-Multi-Patcher-Linux` | Linux x86-64 (`chmod +x`; do zapisu karty potrzebny `pkexec`) |
| `X6100-multiboot-TEST.img.xz` | karta testowa: F1 OpenX6X00 v0.3.9, F2 R1CBU v0.28.0, F3 Xiegu z eMMC |
| `X6100-multiboot-TEST-mini.img.xz` | mniejsza karta testowa: F1 OpenX6X00 v0.3.9, F2 Xiegu z eMMC |
| `u-boot-x6100-menu.bin` | sam U-Boot menu z obsługą ekranu |

Instalacja Pythona nie jest potrzebna. Pliki buduje GitHub Actions (`.github/workflows/build.yml`)
przy każdej zmianie na gałęzi `main` i przy każdym tagu `v*`.


Program w stylu balenaEtchera dla **Xiegu X6100**: dodajesz obrazy kart kilku systemów
(np. OpenX6X00 w dwóch wersjach) i program składa z nich **jedną kartę SD z menu startowym**.
Przy włączaniu radia na ekranie pojawia się menu, a system wybierasz klawiszem **F1–F5**.
Opcjonalnie w menu jest też **system Xiegu z pamięci wewnętrznej (eMMC)**, który pozostaje
nietknięty.

> **Status: wersja testowa.** Karta jest sprawdzana narzędziami (`fsck.fat`, `e2fsck`, `blkid`,
> `sfdisk`), ale menu nie było jeszcze uruchomione na radiu.

## Jak używać

1. Uruchom program:
   - najprościej: plik z [Releases](../../releases) dla Twojego systemu, albo ze źródeł:
   - Windows: `uruchom-windows.bat` (potrzebny [Python 3.9+](https://www.python.org/downloads/),
     przy instalacji zaznacz *Add python.exe to PATH*). Gotowy `Xiegu-Multi-Patcher.exe` powstaje w
     GitHub Actions (patrz niżej).
   - macOS: `uruchom-mac.command`.
   - Linux: `./uruchom-linux.sh` (pakiety `python3-tk`, do zapisu na kartę `pkexec`).
2. **+ Obraz karty…**: wybierz `.img` albo `.img.zip`, np. `OpenX6X00-x6100-v0.3.9-sdcard.img.zip`.
   Kolejne obrazy dodajesz tak samo, łącznie do 5 pozycji.
3. **+ Xiegu z eMMC**: pozycja menu, która uruchamia oryginalny system radia.
4. Ustaw kolejność (**W górę / W dół**), nazwy (dwuklik) i system domyślny (**Domyślny**, ★).
5. **Wgraj na kartę** (program poprosi o uprawnienia administratora i na koniec sprawdzi zapis)
   albo **Zapisz jako plik .img…** i wgraj go balenaEtcherem.

## Co jest na karcie

| Miejsce | Zawartość |
|---|---|
| 8 KiB | U-Boot menu (mainline 2026.07 z obsługą ekranu X6100, `uboot/`) |
| p1 `BOOT` (FAT32) | `boot.scr` z menu, `boot.cmd` (to samo tekstem), `bootmenu.env`, `menu.txt`, `SYS1/`…`SYS5/` z jądrem i `.dtb` każdego systemu |
| p2 | system plików systemu 1, kopia bajt w bajt |
| p5, p6, … (w p4) | systemy plików kolejnych systemów |
| p3 `DATA` (FAT32) | ustawienia i logi; na karcie zajmuje całe wolne miejsce |

Każdy system startuje z `root=/dev/mmcblk0pN` swojej partycji. OpenX6X00 znajduje DATA po
etykiecie, a jego aktualizacje (Settings > Info > Update) zmieniają tylko pliki systemu, więc menu
zostaje. **Wszystkie systemy dzielą jedną partycję DATA**, czyli także ustawienia (`params.db`).

Bez ponownego wgrywania karty można na komputerze zmienić plik `bootmenu.env` na partycji BOOT:

```
bm_default=1
bm_timeout=50
xiegu_dev=1
xiegu_part=1
xiegu_kernel=zImage
xiegu_fdt=sun8i-r16-x6100.dtb
xiegu_args=console=ttyS0,115200 root=/dev/mmcblk2p2 rootwait panic=10 fbcon=rotate:3 video=VGA:480x800
```

`bm_default` to numer klawisza (1 = F1), `bm_timeout` to czas w dziesiątych częściach sekundy
(50 = 5 s), `xiegu_dev=1` to eMMC widziane przez U-Boot jako `mmc 1`. W tym pliku nie wolno
dopisywać komentarzy na końcu linii, bo U-Boot wczyta je jako część wartości.

Parametry `xiegu_*` odpowiadają temu, co instalator Xiegu (obraz `sdcard.img` z aktualizacji
V1.1.9, skrypty `install_emmc.sh`/`fmt_emmc.sh`) zapisuje do eMMC: p1 FAT z `zImage`,
`sun8i-r16-x6100.dtb` i `boot.scr`, p2 ext4, `root=/dev/mmcblk2p2`, a w U-Boot eMMC to `mmc 1`.
Jeśli system Xiegu się nie uruchomi, menu pokaże na ekranie partycje i pliki eMMC (zrób zdjęcie),
a po 60 s uruchomi system domyślny.

**Obrazu aktualizacji Xiegu nie dodaje się jako systemu na karcie.** Ten obraz to instalator:
po uruchomieniu nadpisuje eMMC. Program rozpoznaje go (plik `rootfs.tar` na trzeciej partycji)
i odmawia. System Xiegu dodajesz pozycją **+ Xiegu z eMMC**.

## Wiersz poleceń

```
python x6100_multiboot.py info OBRAZ...
python x6100_multiboot.py build -o karta.img --xiegu --names "OpenX6X00 0.3.9,OpenX6X00 0.3.8" A.img.zip B.img.zip
python x6100_multiboot.py list
python -m unittest discover -s tests
```

## Jak to działa w U-Boot

Menu to zwykły skrypt U-Boot (`boot.scr`), działający z U-Boot, który już jest w obrazie OpenX6X00.
Klawisze są odczytywane z matrycy GPIO panelu (według device tree X6100) tak samo jak w
multiboot projektu [x6100-fw-mangler](https://github.com/j0ju/x6100-fw-mangler): wiersz w stan
niski (`gpio clear PG6`), odczyt kolumn (`gpio input PE16`, 0 = wciśnięty). F1/F2/F3 = kolumny
PE16/PE17/PE11 w wierszu PG6, F4/F5 = PE16/PE17 w wierszu PG8.
Napisy idą na ekran przez `vidconsole` U-Boota (patrz niżej: U-Boot z obsługą ekranu).

## Pobieranie systemów z internetu

**+ Z internetu…** pokazuje znane systemy z listą ich wydań z GitHuba (najnowsza wersja jest
zaznaczona). Po kliknięciu **Dodaj** aplikacja pobiera obraz, sprawdza rozmiar i sumę SHA-256
(jeśli GitHub ją podaje) i dodaje go do menu. Obrazy zostają w pamięci podręcznej.

| System | Źródło |
|---|---|
| OpenX6X00 | [Guru-RF/OpenX6X00](https://github.com/Guru-RF/OpenX6X00) |
| OpenX6100 (następca R1CBU) | [OpenX6100/x6100_gui](https://github.com/OpenX6100/x6100_gui) |
| R1CBU (klasyczny) | [gdyuldin/x6100_gui](https://github.com/gdyuldin/x6100_gui) |

W wierszu poleceń zamiast pliku można podać `openx6x00@latest`, `openx6100@v1.2.0` itd.;
`catalog` wypisuje dostępne wersje. Obraz Xiegu nie jest pobierany: system Xiegu startuje
z pamięci radia (pozycja **+ Xiegu z eMMC**).

## Menu na ekranie radia

- **Graficzne:** kafelek z logo dla każdego systemu, ustawiony nad jego fizycznym przyciskiem
  F1–F5, system domyślny podświetlony, po wybraniu kafelek robi się zielony („START”).
  Logo można wskazać w aplikacji (**Logo…**, dowolny PNG/JPG). Bez tego aplikacja rysuje
  kafelek z nazwą w kolorach systemu. **Podgląd menu** pokazuje ekran przed zapisem.
- **Odliczanie** do startu systemu domyślnego (0–9 s, `bm_secs` w `bootmenu.env`).
- Jeśli obrazek się nie wczyta, menu pokazuje się jako kolorowy tekst.

## Partycja DATA: wspólna albo osobna

- **Wspólna:** jedna DATA (ustawienia, logi) dla wszystkich systemów.
- **Osobna:** każdy system ma swoją DATA. W tablicy partycji jest zawsze tylko DATA systemu,
  który ostatnio startował, jako trzecia partycja z etykietą `DATA`, więc systemy nie wymagają
  zmian. Przed startem innego systemu U-Boot zapisuje sektor 0 karty z jego tablicą
  (`SYSn/MBR.BIN` na BOOT), ale tylko wtedy, gdy się zmienia. Na komputerze widać tylko DATA
  ostatnio uruchomionego systemu.

## U-Boot z obsługą ekranu (`uboot/`)

Ekran X6100 (kontroler Sitronix ST7701S, panel JLT4013A 480×800) trzeba najpierw zainicjować
sekwencją poleceń przez SPI. Robi to dopiero sterownik w Linuksie, dlatego z U-Boot z obrazów
systemów ekran pozostaje czarny i menu jest niewidoczne (sprawdzone na radiu: menu działało
na ślepo, F2 uruchomił R1CBU). Katalog `uboot/` buduje U-Boot v2026.07 z:

- inicjalizacją ST7701S przeniesioną ze sterownika Linuksa (`panel-jinglitai-jlt4013a.c`,
  GPL-2.0), wysyłaną programowym SPI na pinach PL7 (CS), PL8 (MOSI), PL9 (SCK), PL10 (D/C);
- konsolą obróconą o 270° (jak `fbcon=rotate:3`) i czcionką 16×32.

`uboot/build.sh` uruchamia GitHub Actions, a gotowy `u-boot-x6100-menu.bin` trafia do aplikacji
i jest domyślnie wgrywany na kartę. `--uboot image` wgrywa zamiast niego U-Boot z pierwszego
obrazu (wtedy menu działa bez ekranu).

## Do zrobienia

- Test na radiu: menu, klawisze, start obu systemów, start Xiegu (układ eMMC).
- Menu graficzne (BMP) wymaga U-Boot z `CONFIG_CMD_BMP`.
- Osobne partycje DATA dla każdego systemu (opcja).
