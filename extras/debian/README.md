# Debian dla X6100 (Extras, wersja robocza)

Zwykły Debian 13 (trixie, armhf) jako kolejna pozycja w menu karty multiboot. Tak jak Doom
uruchamia się z jądrem **pierwszego systemu z obrazu na liście** (np. OpenX6X00): to otwarte
jądro społeczności, z obsługą ekranu X6100. Moduły tego jądra (WiFi, USB HOST, Bluetooth)
Debian bierze z partycji tamtego systemu, montowanej tylko do odczytu, niczego w niej nie zmieniając.
W obrazie nie ma żadnych plików Xiegu ani zamkniętego oprogramowania.

## Co jest w środku (v1)

- konsola na ekranie radia (czcionka Terminus), logowanie: **radio / radio**,
  przy pierwszym logowaniu system każe ustawić nowe hasło; `sudo` dla użytkownika radio
- WiFi i Bluetooth: NetworkManager (`nmtui`), sterowniki RTL8723BU z pakietu firmware-realtek
- SSH (`ssh radio@x6100-debian.local`, adres IP jest też na ekranie logowania)
- Hamlib (`rigctld`), `i2c-tools`, `gpiod`, `evtest`, `alsa-utils`
- klawisz POWER radia wyłącza system (logind)
- przy pierwszym starcie system powiększa się na całą swoją partycję (+2 GB wolnego miejsca)
  i tworzy własne klucze SSH

## Budowanie

```
sudo extras/debian/build.sh      # mmdebstrap, qemu-user-static (binfmt armhf), debian-archive-keyring
```

Wynik: `extras/debian/out/debian-x6100-rootfs.ext4.xz` (ok. 60 MB). Pakiety pobierane są
z serwerów Debiana; ich licencje są w `/usr/share/doc/*/copyright` w obrazie.

Karta z linii poleceń:

```
python3 -m x6100mb build -o karta.img --debian --debian-rootfs extras/debian/out/debian-x6100-rootfs.ext4.xz \
    --xiegu openx6x00@latest
```

## Dalej (do zrobienia)

- sterowanie radiem z Debiana: biblioteka X6100Control (LGPL, OpenX6100): PTT, wybór źródła
  audio do nadawania, głośność; demon CAT dla rigctld
- nadawanie audio z Debiana (czego brakowało w x6100-armbian), odbiór przez ALSA
- lekki pulpit na ekranie radia (mysz i klawiatura USB/BT) i programy (WSJT-X, fldigi) jako opcja
- logo: Debian Open Use Logo, (c) Software in the Public Interest, LGPL-3+ / CC-BY-SA 3.0.
  To nieoficjalna kompilacja Debiana, nie wydanie projektu Debian.
