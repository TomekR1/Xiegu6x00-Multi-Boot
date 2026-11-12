# X6100 Multiboot

Program w stylu balenaEtchera dla **Xiegu X6100**: dodajesz obrazy kart kilku systemów
(np. OpenX6X00 w dwóch wersjach) i program składa z nich **jedną kartę SD z menu startowym**.
Przy włączaniu radia na ekranie pojawia się menu, a system wybierasz klawiszem **F1–F5**.
Opcjonalnie w menu jest też **system Xiegu z pamięci wewnętrznej (eMMC)**, który pozostaje
nietknięty.

> **Status: wersja testowa.** Karta jest sprawdzana narzędziami (`fsck.fat`, `e2fsck`, `blkid`,
> `sfdisk`), ale menu nie było jeszcze uruchomione na radiu.

## Jak używać

1. Uruchom program:
   - Windows: `uruchom-windows.bat` (potrzebny [Python 3.9+](https://www.python.org/downloads/),
     przy instalacji zaznacz *Add python.exe to PATH*). Gotowy `X6100-Multiboot.exe` powstaje w
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
| 8 KiB | U-Boot z pierwszego obrazu (OpenX6X00: mainline 2026.07) |
| p1 `BOOT` (FAT32) | `boot.scr` z menu, `boot.cmd` (to samo tekstem), `bootmenu.env`, `menu.txt`, `SYS1/`…`SYS5/` z jądrem i `.dtb` każdego systemu |
| p2 | system plików systemu 1, kopia bajt w bajt |
| p5, p6, … (w p4) | systemy plików kolejnych systemów |
| p3 `DATA` (FAT32) | ustawienia i logi; na karcie zajmuje całe wolne miejsce |

Każdy system startuje z `root=/dev/mmcblk0pN` swojej partycji. OpenX6X00 znajduje DATA po
etykiecie, a jego aktualizacje (Settings > Info > Update) zmieniają tylko pliki systemu, więc menu
zostaje. **Wszystkie systemy dzielą jedną partycję DATA**, czyli także ustawienia (`params.db`).

Bez komputera na karcie można zmienić plik `bootmenu.env` na partycji BOOT:

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

Jeśli system Xiegu się nie uruchomi, menu pokaże na ekranie partycje i pliki eMMC (zrób zdjęcie),
a po 60 s uruchomi system domyślny. Parametry `xiegu_*` są wpisane na podstawie przypuszczeń,
zanim poznamy układ eMMC.

## Wiersz poleceń

```
python x6100_multiboot.py info OBRAZ...
python x6100_multiboot.py build -o karta.img --xiegu --names "OpenX6X00 0.3.9,OpenX6X00 0.3.8" A.img.zip B.img.zip
python x6100_multiboot.py list
python -m unittest discover -s tests
```

## Jak to działa w U-Boot

Menu to zwykły skrypt U-Boot (`boot.scr`), działający z U-Boot, który już jest w obrazie OpenX6X00.
Klawisze są odczytywane z matrycy GPIO panelu (wiersze PG6–PG10, kolumny PE11–PE17, według
device tree X6100): F1/F2/F3 = kolumny PE16/PE17/PE11 i wiersz PG6, F4/F5 = PE16/PE17 i wiersz PG8.
Napisy idą na ekran przez `vidconsole` U-Boota i mogą być obrócone o 90°.

## Do zrobienia

- Test na radiu: menu, klawisze, start obu systemów, start Xiegu (układ eMMC).
- Menu graficzne (BMP) wymaga U-Boot z `CONFIG_CMD_BMP`.
- Osobne partycje DATA dla każdego systemu (opcja).
