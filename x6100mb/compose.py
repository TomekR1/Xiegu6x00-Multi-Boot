"""One card from several systems: U-Boot, a BOOT partition with each kernel and the menu, each
system's root filesystem, and a DATA partition.

Layout (MBR):
    8 KiB            U-Boot (from the first system, or the one chosen)
    p1  BOOT  FAT32  boot.scr (the menu), bootmenu.env, SYS1/ ... SYS5/ (kernel, dtb)
    p2  rootfs of system 1
    p4  extended:  p5, p6, ... rootfs of systems 2..5
    p3  DATA  FAT32, labelled DATA, at the end (fills the card when written to one)

OpenX6X00 finds DATA by its label and mounts the third partition in fstab: both hold. Every
system gets root=/dev/mmcblk0pN for its own partition.
"""
import os
from .i18n import lang, t
import random
import re

from .extents import Data, FileRange, Plan, Zero
from .fat import Fat32Builder
from .image import SECTOR, UBOOT_OFFSET, make_ebr, make_mbr, make_script_image

MIB = 1024 * 1024
ALIGN = MIB // SECTOR

# Front-panel keys in U-Boot: the X6100 key matrix from the device tree. As in j0ju's
# x6100-fw-mangler multiboot (used on radios): the row is driven low, the column read (0 = pressed); F1..F5 from OpenX6X00's src/front_keys.c (BTN_TRIGGER_HAPPY13..15, 19, 20)
COUNTDOWN = "Start F${bm_default} za ${bm_left} s"
WAITING = "Wybierz system klawiszem F1-F{n}"
MAX_SECS = 15
POWERING_OFF = "Wylaczanie radia..."

KEYS = [("F1", "PE16", "PG6"), ("F2", "PE17", "PG6"), ("F3", "PE11", "PG6"),
        ("F4", "PE16", "PG8"), ("F5", "PE17", "PG8")]
MAX_ENTRIES = len(KEYS)

XIEGU_DEFAULTS = {
    "xiegu_dev": "1",
    "xiegu_part": "1",
    "xiegu_kernel": "zImage",
    "xiegu_fdt": "sun8i-r16-x6100.dtb",
    "xiegu_args": "console=ttyS0,115200 root=/dev/mmcblk2p2 rootwait panic=10 fbcon=rotate:3 video=VGA:480x800",
}


class ComposeError(Exception):
    pass


def project_logo(entry):
    """The logo the system's own project publishes (fetched once, cached), or None"""
    if entry["kind"] != "sd":
        return None
    from . import catalog
    from .image import cache_dir
    return catalog.fetch_logo(catalog.source_for(entry["name"]), cache_dir())


DOOM_NAME = "DOOM"
# Our own icon for the Doom tile (fire-coloured lettering, drawn for this app)
# The menu's moving rail: its pictures' places in memory (clear of the kernel's and the script's)
# and where on the panel they go (the rail's rows are the framebuffer's columns)
ANIM_FRAMES, ANIM_ADDR, ANIM_STEP, ANIM_X = 16, 0x44000000, 0x10000, 376
DOOM_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "doom.png")
NES_NAME = "NES"
NES_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "nes.png")
# The app's extras: their root filesystem (bundled in the app) and their tile's icon
EXTRAS = {"doom": ("doom-x6100-rootfs.ext4.xz", DOOM_LOGO), "nes": ("nes-x6100-rootfs.ext4.xz", NES_LOGO)}
# The NES emulator's games: what it plays, in the NES folder of the card's BOOT partition
NES_GAMES = (".nes", ".fds", ".unf", ".unif", ".nsf")
NES_ROOM_MB = 64          # room on BOOT for the games added later and the saves


def name_entries(entries):
    """The menu's names without version numbers (a system updates itself from the radio, and the menu
    would keep saying the old one): an entry fetched from a project is called by the project; when two
    of them would share a name, both get their version. Names the user typed stay as they are."""
    def auto(e):
        base, ver = e.get("base"), e.get("version")
        return base and e.get("name") in (base, "%s %s" % (base, ver) if ver else base)
    groups = {}
    for e in entries:
        if auto(e):
            groups.setdefault(e["base"].lower(), []).append(e)
    for same in groups.values():
        for e in same:
            twin = len(same) > 1 and e.get("version")
            e["name"] = ("%s %s" % (e["base"], e["version"]) if twin else e["base"])[:28]
    return entries


def kernel_donor(entries, key="sys"):
    """The system the extras start with: the first from an image whose kernel is on its BOOT
    partition (IU1WXY 0.2.2+ keeps its kernel inside its A/B slots: issue #8), or None"""
    for e in entries:
        s = e.get(key)
        if e.get("kind") == "sd" and s is not None and not getattr(s, "is_ab", False) \
                and "kernel" in (getattr(s, "files", None) or {}):
            return s
    return None


def resolve_extras(entries, rootfs_xz=None):
    """The app's extras (Doom, the NES emulator) as systems of their own: their root filesystem,
    booted with the kernel and device tree of the first system from an image on the list.
    rootfs_xz: {kind: a root filesystem's .ext4.xz} instead of the bundled ones (a path: Doom's)"""
    if not any(e["kind"] in EXTRAS for e in entries):
        return entries
    if isinstance(rootfs_xz, str):
        rootfs_xz = {"doom": rootfs_xz}
    rootfs_xz = rootfs_xz or {}
    from .image import ExtraSystem, cache_dir, extra_rootfs
    donor = kernel_donor(entries)
    out = []
    for e in entries:
        if e["kind"] in EXTRAS:
            kind = e["kind"]
            rootfs = extra_rootfs(cache_dir(), rootfs_xz.get(kind), name=EXTRAS[kind][0])
            e = dict(e, kind="sd", extra=kind, sys=ExtraSystem(e["name"], rootfs, donor, extra=kind))
        out.append(e)
    return out


def extra_of(entry):
    """Which extra an entry is ("doom", "nes"), or None"""
    if entry.get("kind") in EXTRAS:
        return entry["kind"]
    return entry.get("extra") or getattr(entry.get("sys"), "extra", None)


NES_PICTURES = (".png", ".jpg", ".jpeg", ".bmp")


def _nes_files(paths):
    """The paths, a folder given standing for the games, archives and pictures in it (subfolders too)"""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                out += [os.path.join(root, f) for f in sorted(files)
                        if not f.startswith(".") and f.lower().endswith(NES_GAMES + NES_PICTURES + (".zip",))]
        else:
            out.append(p)
    return out


def nes_pictures(paths):
    """The games' pictures, shown beside the list on the radio: a file of the game's name with
    .png/.jpg/.bmp beside it (or in its .zip). For NES/IMG: [(stem + extension, bytes or path)]"""
    import zipfile
    out, seen = [], set()
    paths = _nes_files(paths)

    def add(stem, ext, data):
        if stem.lower() not in seen:
            seen.add(stem.lower())
            out.append((stem + ext.lower(), data))

    for p in paths:
        if p.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(p) as z:
                    files = [i for i in z.infolist() if not i.is_dir()]
                    stems = [os.path.splitext(os.path.basename(i.filename))[0] for i in files
                             if i.filename.lower().endswith(NES_GAMES)]
                    pics = [i for i in files if i.filename.lower().endswith(NES_PICTURES) and i.file_size < 8 << 20]
                    for i in pics:
                        stem, ext = os.path.splitext(os.path.basename(i.filename))
                        if stem.lower() in (s.lower() for s in stems):
                            add(stem, ext, z.read(i))
                    if len(stems) == 1 and pics and stems[0].lower() not in seen:   # one game, its picture
                        add(stems[0], os.path.splitext(pics[0].filename)[1], z.read(pics[0]))
            except (zipfile.BadZipFile, OSError):
                pass
        elif p.lower().endswith(NES_PICTURES) and os.path.getsize(p) < 8 << 20:   # chosen on its own
            stem, ext = os.path.splitext(os.path.basename(p))
            add(stem, ext, p)
        elif p.lower().endswith(NES_GAMES):
            stem = os.path.splitext(p)[0]
            for ext in NES_PICTURES + tuple(e.upper() for e in NES_PICTURES):
                if os.path.isfile(stem + ext) and os.path.getsize(stem + ext) < 8 << 20:
                    add(os.path.basename(stem), ext, stem + ext)
                    break
    return out


def nes_games(paths):
    """The NES games to put on the card, from files, .zip archives and folders of them:
    [(file name, bytes or path)]"""
    import zipfile
    out, seen = [], set()
    paths = _nes_files(paths)
    for p in paths:
        if p.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(p) as z:
                    for info in z.infolist():
                        name = os.path.basename(info.filename)
                        if not info.is_dir() and name.lower().endswith(NES_GAMES) and info.file_size < 16 << 20:
                            if name.lower() not in seen:
                                seen.add(name.lower())
                                out.append((name, z.read(info)))
            except (zipfile.BadZipFile, OSError) as e:
                raise ComposeError("%s: %s" % (os.path.basename(p), e))
        elif p.lower().endswith(NES_GAMES):
            name = os.path.basename(p)
            if name.lower() not in seen:
                seen.add(name.lower())
                out.append((name, p))
    return out


def tile(entry):
    """What the graphic menu shows for an entry: its name, a logo of one's own, else the project's"""
    if entry.get("logo"):
        return {"name": entry["name"], "logo": entry["logo"]}
    extra = extra_of(entry)
    if extra or getattr(entry.get("sys"), "donor", None) is not None:
        return {"name": entry["name"], "logo": EXTRAS.get(extra or "doom")[1]}
    logo = project_logo(entry)
    crop = None
    if logo:
        from . import catalog
        src = catalog.source_for(entry["name"]) or {}
        crop = src.get("crop") if logo and src.get("logo") else None
    return {"name": entry["name"], "logo": logo, "crop": crop}


def _ascii(s, n=28):
    s = re.sub(r"[^A-Za-z0-9 .,_+()/:-]", "", s)
    return s[:n] or "system"


def _up(n, a=ALIGN):
    return (n + a - 1) // a * a


ESC = "\x1b"


def _shown(text):
    """A line of text for the screen only now: the console is the serial port's otherwise.
    A text ending in \\n is a whole line (U-Boot's echo knows no escapes)."""
    if text.endswith("\\n"):
        return 'setenv stdout serial,vidconsole; echo "%s"; setenv stdout serial' % text[:-2]
    return 'setenv stdout serial,vidconsole; echo -n "%s"; setenv stdout serial' % text


def menu_script(entries, default, timeout_s, title="X6100 MULTIBOOT", gfx=False, ansi=False, wait=False):
    """entries: [{"kind": "sd", "name", "dir", "part", "sys", "mbr": file or None} | {"kind": "xiegu", "name"}]

    gfx: MENU/MENU.BMP and MENU/SELn.BMP are on BOOT (menu_gfx). ansi: the U-Boot reads ANSI
    colours (the bundled one). Numbers in U-Boot's setexpr/itest are hex: bm_secs (0..15, decimal in
    bootmenu.env) goes through a table to hex, the seconds left through one back to decimal (any
    U-Boot, no setexpr fmt). wait (bm_wait=1): no default, the menu waits for a key.
    """
    L = []
    a = L.append
    e_ = ESC if ansi else ""
    a('echo "------------ X6100 multiboot menu ------------"')
    a("# Made by x6100-multiboot. Settings: bootmenu.env on this partition (edit on a PC).")
    a("setenv bm_default %d" % (default + 1))
    a("setenv bm_secs %d" % _secs(timeout_s))
    a("setenv bm_wait %d" % (1 if wait else 0))
    a("setenv bm_anim 1")                  # the moving rail; bm_anim=0 in bootmenu.env: a still menu
    for n in range(MAX_SECS + 1):           # decimal -> hex, hex -> decimal
        a("setenv bm_hex_%d 'setenv bm_secs %x'" % (n, n))
        a("setenv bm_dec_%x 'setenv bm_left %d'" % (n, n))
    for k, v in XIEGU_DEFAULTS.items():
        a('setenv %s "%s"' % (k, v))
    a("if fatload mmc 0:1 ${scriptaddr} bootmenu.env; then env import -t ${scriptaddr} ${filesize}; fi")
    a("run bm_hex_${bm_secs}")
    a("setexpr bm_ticks ${bm_secs} * a")
    a("")
    a("# The menu: the picture when there is one, else text")
    a("setenv bm_gfx 0")
    if gfx:
        a("if fatload mmc 0:1 ${kernel_addr_r} MENU/MENU.BMP; then setenv bm_gfx 1; fi")
    if ansi:
        a('echo -n "%s[0;37;40m%s[2J%s[1;1H"' % (ESC, ESC, ESC))
    else:
        a("cls")
    a("setenv stdout serial")
    if gfx:
        a("if itest ${bm_gfx} -eq 1; then if bmp display ${kernel_addr_r} 0 0; then setenv bm_gfx 1; else setenv bm_gfx 0; fi; fi")
    count_row = "2;2H" if gfx else "%d;3H" % (len(entries) + 6)
    # The text menu (also under a picture that did not load)
    text = []
    if ansi:
        text.append("%s[1;1H%s[30;46m  %s%s%s[0;37;40m" % (ESC, ESC, title, " " * (47 - len(title)), ESC))
        for i, e in enumerate(entries):
            mark = ("  %s[36m<- %s" % (ESC, t("domyslny"))) if i == default and not wait else ""
            text.append("%s[%d;3H%s[1;33m%s%s[0;37;40m   %s%s%s[0;37;40m" % (
                ESC, i + 3, ESC, KEYS[i][0], ESC, _ascii(e["name"]), mark, ESC))
        for i, e in enumerate(entries):
            label = _ascii(e["name"], 7)
            text.append("%s[15;%dH%s[30;47m F%d %s%s[0;37;40m" % (ESC, 10 * i + 1, ESC, i + 1, label.ljust(7)[:5], ESC))
    else:
        text.append("  %s\\n" % title)
        for i, e in enumerate(entries):
            text.append("  %s   %s\\n" % (KEYS[i][0], _ascii(e["name"])))
    a("if itest ${bm_gfx} -eq 0; then")
    for line in text:
        a("    " + _shown(line))
    a("fi")
    a("")
    if gfx:
        # The rail's pictures into memory once (small: nothing is read from the card while the menu
        # runs), drawn in turn over the rail, one each tenth of a second; any of them missing: still
        a("if itest ${bm_gfx} -eq 0; then setenv bm_anim 0; fi")
        a("if itest ${bm_anim} -eq 1; then")
        for k in range(ANIM_FRAMES):
            addr = ANIM_ADDR + k * ANIM_STEP
            a("    if fatload mmc 0:1 0x%x MENU/A%02d.BMP; then setenv bm_fr_%x 'bmp display 0x%x %d 0'; "
              "else setenv bm_anim 0; fi" % (addr, k, k, addr, ANIM_X))
        a("fi")
    else:
        a("setenv bm_anim 0")
    a("")
    a("# Keys, with a countdown each second; gpio prints every pin it reads, hence serial only")
    a("setenv bm_choice")
    a("setenv i 0")
    a("pek clear")                          # the press that switched the radio on (menu's U-Boot only)
    a('while test -z "${bm_choice}"; do')
    a("    if itest ${bm_anim} -eq 1; then setexpr bm_f ${i} %% %x; run bm_fr_${bm_f}; fi" % ANIM_FRAMES)
    a("    setexpr bm_r ${i} % a")
    a("    if itest ${bm_r} -eq 0; then")
    a("        setexpr bm_left ${bm_ticks} - ${i}")
    a("        setexpr bm_left ${bm_left} / a")
    a("        run bm_dec_${bm_left}")
    waiting = t(WAITING).format(n=len(entries))
    a("        if itest ${bm_wait} -eq 1; then")
    a("            " + _shown("%s[%s%s[0;37;40m%s   " % (e_, count_row, e_, waiting) if ansi else waiting + "\\n"))
    a("        else")
    a("            " + _shown("%s[%s%s[0;37;40m%s   " % (e_, count_row, e_, t(COUNTDOWN)) if ansi
                              else t(COUNTDOWN) + "\\n"))
    a("        fi")
    a("    fi")
    rows = []
    for i in range(len(entries)):
        if KEYS[i][2] not in rows:
            rows.append(KEYS[i][2])
    for row in rows:
        a("    gpio clear %s" % row)
        for i in range(len(entries)):
            _key, col, r = KEYS[i]
            if r == row:
                a("    if gpio input %s; then setenv bm_choice %d; fi" % (col, i + 1))
        a("    gpio input %s" % row)
    # POWER switches the radio off here too (the menu's U-Boot: pek; boff, the base board's power-off)
    a("    if pek; then " + _shown(("%s[%s%s[1;31m%s          %s[0;37;40m" % (ESC, count_row, ESC, t(POWERING_OFF), ESC))
                              if ansi else t(POWERING_OFF) + "\\n") +
      # the base board cuts the power (it holds it: the PMIC's power-off alone left the radio on);
      # the PMIC's after it, for a U-Boot without boff
      "; boff; sleep 1; poweroff; fi")
    a('    if test -z "${bm_choice}"; then')
    a("        if itest ${bm_wait} -eq 1; then sleep 0.1; setexpr i ${i} + 1; setexpr i ${i} % a0")
    a("        elif itest ${i} -ge ${bm_ticks}; then setenv bm_choice ${bm_default}; else sleep 0.1; setexpr i ${i} + 1; fi")
    a("    fi")
    a("done")
    a("")
    a("# The choice shown: its tile lit, or a line of text")
    a("setenv bm_shown 0")
    if gfx:
        a("if itest ${bm_gfx} -eq 1; then")
        a("    if fatload mmc 0:1 ${kernel_addr_r} MENU/SEL${bm_choice}.BMP; then bmp display ${kernel_addr_r} 0 0; setenv bm_shown 1; fi")
        a("fi")
    a("if itest ${bm_shown} -eq 0; then " + _shown(("%s[%s%s[1;32mStart: F${bm_choice} ...          %s[0;37;40m" % (ESC, count_row, ESC, ESC)) if ansi else "Start: F${bm_choice} ...\\n") + "; fi")
    a("")
    # Each entry's start as a variable, so a failed one can fall back to the default
    first_sd = None
    for i, e in enumerate(entries):
        n = i + 1
        if e["kind"] == "xiegu":
            cmd = ('setenv stdout serial,vidconsole; setenv bootargs ${xiegu_args}; '
                   'if fatload mmc ${xiegu_dev}:${xiegu_part} 0x46000000 ${xiegu_kernel}; then '
                   'if fatload mmc ${xiegu_dev}:${xiegu_part} 0x49000000 ${xiegu_fdt}; then '
                   'setenv stdout serial; bootz 0x46000000 - 0x49000000; fi; fi; setenv stdout serial,vidconsole; '
                   'echo "Xiegu did not start. The eMMC holds:"; mmc list; mmc dev ${xiegu_dev}; mmc part; '
                   'fatls mmc ${xiegu_dev}:${xiegu_part}; echo "(take a photo) default system in 60 s"; sleep 60; '
                   'setenv stdout serial')
        else:
            if first_sd is None:
                first_sd = n
            s_ = e["sys"]
            d = e["dir"]
            pre = ""
            if e.get("mbr"):
                # This system's own DATA: the partition table's third entry pointed at it
                # (written only when it changes)
                pre = ("mmc dev 0; mmc read 0x45000000 0 1; "
                       "if fatload mmc 0:1 0x45100000 %s; then "
                       "if cmp.b 0x45000000 0x45100000 200; then setenv bm_same 1; "
                       "else mmc write 0x45100000 0 1; fi; fi; mmc rescan; " % e["mbr"])
            if getattr(s_, "is_ab", False):
                cmd = (
                    pre +
                    "if fatload mmc 0:1 ${scriptaddr} %s/IU1WXY.SCR; then "
                    "source ${scriptaddr}; fi; "
                    "setenv stdout serial,vidconsole; "
                    "echo \"%s did not start\"; sleep 3; setenv stdout serial"
                    % (d, _ascii(e["name"]))
                )
            else:
                loads = ["fatload mmc 0:1 %s %s/ZIMAGE" % (s_.kernel_addr, d)]
                if s_.fdt_file:
                    loads.append("fatload mmc 0:1 %s %s/BOARD.DTB" % (s_.fdt_addr, d))
                if s_.initrd_file:
                    loads.append("fatload mmc 0:1 %s %s/INITRD" % (s_.initrd_addr, d))
                boot = "%s %s %s %s" % (
                    s_.boot_cmd,
                    s_.kernel_addr,
                    s_.initrd_addr or "-",
                    s_.fdt_addr or "",
                )
                cmd = (
                    pre +
                    'setenv bootargs "%s"; ' % s_.bootargs_for(e["part"]) +
                    "".join("if %s; then " % load for load in loads) +
                    boot.strip() + "; " +
                    "fi; " * len(loads) +
                    'setenv stdout serial,vidconsole; echo "%s did not start"; sleep 3; setenv stdout serial'
                    % _ascii(e["name"])
                )
        assert "'" not in cmd
        a("setenv bm_boot%d '%s'" % (n, cmd))
    a("")
    a("run bm_boot${bm_choice}")
    a('if test "${bm_choice}" != "${bm_default}"; then run bm_boot${bm_default}; fi')
    a("run bm_boot%d" % first_sd)
    return "\n".join(L) + "\n"


def _secs(timeout_s):
    return max(0, min(MAX_SECS, int(timeout_s)))


def env_file(default, timeout_s, xiegu=None, wait=False):
    x = dict(XIEGU_DEFAULTS)
    x.update(xiegu or {})
    lines = ["bm_default=%d" % (default + 1), "bm_secs=%d" % _secs(timeout_s), "bm_wait=%d" % (1 if wait else 0)]
    lines += ["%s=%s" % (k, v) for k, v in x.items()]
    return ("\n".join(lines) + "\n").encode()


def compose(entries, default=0, timeout_s=5, data_mb=1024, card_bytes=None, uboot_from=None,
            xiegu=None, boot_extra_mb=32, data_mode="shared", graphics=True, wait=False, data_files=None):
    """A Plan for the card. entries as for menu_script, without "dir"/"part" (filled in here);
    an entry may name a "logo" picture for the graphic menu.

    card_bytes: writing to a card of that size, DATA fills the rest; else the image has
    data_mb of DATA (per system when separate). uboot_from: the U-Boot to use (image.UBoot or
    a SourceSystem); by default the bundled menu U-Boot (it lights the screen), else the first
    image's. data_mode: "shared" (one DATA for every system) or "separate" (each system its
    own: U-Boot points the partition table's third entry at it before starting it).
    """
    if data_mode not in ("shared", "separate"):
        raise ComposeError("data_mode: shared or separate")
    sd = [e for e in entries if e["kind"] == "sd"]
    if not sd:
        raise ComposeError("add at least one card image (the menu needs a system on the card)")
    if len(entries) > MAX_ENTRIES:
        raise ComposeError(f"at most {MAX_ENTRIES} entries (keys F1..F{MAX_ENTRIES})")
    if not 0 <= default < len(entries):
        raise ComposeError("the default entry is not in the list")
    if sum(1 for e in sd if getattr(e["sys"], "is_ab", False)) > 1:
        # IU1WXY 0.2.2+ keeps its A/B state in ab.env at the top of BOOT: two would share it
        raise ComposeError(t("Na karcie może być tylko jedna wersja IU1WXY 0.2.2 lub nowsza (z partycjami A/B): "
                             "obie trzymają stan w tym samym pliku ab.env."))
    if uboot_from is None:
        from .image import UBoot, bundled_uboot_path
        p = bundled_uboot_path()
        uboot_from = UBoot(p) if p else None
    ub = uboot_from or next((e["sys"] for e in sd if e["sys"].has_uboot), None)
    if ub is None or not ub.has_uboot:
        raise ComposeError("none of the images carries an Allwinner U-Boot")
    # A U-Boot that lights the X6100's screen (uboot/): colours, and the picture when Pillow is here
    screen = b"st7701s-cs" in ub.uboot
    gfx = False
    if screen and graphics:
        from . import menu_gfx
        gfx = menu_gfx.HAVE_PIL

    # Partition numbers and directories
    physical_index = 0
    for i, e in enumerate(sd):
        e["dir"] = "SYS%d" % (i + 1)
        # The first physical root is p2; following roots are p5, p6, ...
        # An IU1WXY A/B entry consumes two physical root areas.
        e["part"] = 2 if physical_index == 0 else 4 + physical_index
        physical_index += 2 if getattr(e["sys"], "is_ab", False) else 1
    for e in sd:                                # an extra (Doom) learns where its kernel's system is
        donor = getattr(e["sys"], "donor", None)
        if donor is not None:
            e["sys"].donor_part = next((x["part"] for x in sd if x["sys"] is donor), None)

    kernels = sum(sum(len(v) for v in e["sys"].files.values()) for e in sd if not getattr(e["sys"], "is_ab", False))
    # the NES emulator's games go on BOOT (any computer sees it), with room for more and the saves
    nes = [e for e in sd if extra_of(e) == "nes"]
    games = nes_games([g for e in nes for g in e.get("games", [])])
    pics = nes_pictures([g for e in nes for g in e.get("games", [])])
    if nes:
        kernels += sum(len(g) if isinstance(g, bytes) else os.path.getsize(g) for _n, g in games + pics)
        kernels += NES_ROOM_MB * MIB
    pictures = (len(entries) + 1) * 400 * 1024 if gfx else 0
    boot_size = _up(max(64 * MIB, kernels + pictures + boot_extra_mb * MIB + 4 * MIB) // SECTOR) * SECTOR

    lba = ALIGN                                       # 1 MiB
    boot_lba = lba
    lba += boot_size // SECTOR
    # Physical root filesystem areas. Ordinary systems have one area.
    # IU1WXY 0.2.2+ keeps two complete A/B root slots while remaining one
    # menu entry. Slot A may occupy the primary p2 area when IU1WXY is first;
    # all following areas are placed behind the extended partition.
    #
    # Tuple: (entry, slot name or None, ebr_lba or None, start_lba, sectors)
    layout = []
    first = sd[0]

    def root_areas(entry):
        system = entry["sys"]
        if getattr(system, "is_ab", False):
            return [
                ("a", system.ab_slots["a"]["size"] // SECTOR),
                ("b", system.ab_slots["b"]["size"] // SECTOR),
            ]
        return [(None, system.root_size // SECTOR)]

    physical = []
    for entry in sd:
        for slot, sectors in root_areas(entry):
            physical.append((entry, slot, sectors))

    first_entry, first_slot, first_sectors = physical[0]
    layout.append((first_entry, first_slot, None, lba, first_sectors))
    lba = _up(lba + first_sectors)

    ext_start = None
    if len(physical) > 1:
        ext_start = lba
        for entry, slot, sectors in physical[1:]:
            ebr = lba
            start = ebr + ALIGN
            layout.append((entry, slot, ebr, start, sectors))
            lba = _up(start + sectors)
        ext_end = lba

    for entry, slot, _ebr, start, sectors in layout:
        if slot is not None:
            entry.setdefault("ab_physical", {})[slot] = {
                "start": start,
                "sectors": sectors,
                "type": entry["sys"].ab_slots[slot]["type"],
            }

    data_lba = lba
    # Extras (Doom) have no DATA of their own: they see their donor's (its Bluetooth pairings)
    owners = [e for e in sd if getattr(e["sys"], "donor", None) is None]
    n_data = len(owners) if data_mode == "separate" else 1
    if card_bytes:
        card_sectors = card_bytes // SECTOR
        data_sectors = (card_sectors - data_lba) // n_data // ALIGN * ALIGN
        if data_sectors * SECTOR < 64 * MIB:
            raise ComposeError("the card is too small for these systems (%d MB short)" %
                               ((data_lba * SECTOR + n_data * 64 * MIB - card_bytes) // MIB + 1))
        size = card_bytes
    else:
        data_sectors = data_mb * MIB // SECTOR
        size = (data_lba + n_data * data_sectors) * SECTOR
    plan = Plan(size)
    # The DATA areas: one, or one per system on the card (only the running one is in the table)
    data_areas = [data_lba + k * data_sectors for k in range(n_data)]
    def owner(e):
        donor = getattr(e["sys"], "donor", None)
        return next((x for x in owners if x["sys"] is donor), owners[0]) if donor is not None else e
    def_sd = entries[default] if entries[default]["kind"] == "sd" else sd[0]
    active = data_areas[owners.index(owner(def_sd))] if n_data > 1 else data_areas[0]

    # MBR, the gap up to U-Boot cleared (an old GPT header lives there), U-Boot
    def primary(data_at):
        return [(0x0C, boot_lba, boot_size // SECTOR, True),
                (first["sys"].root_type, layout[0][3], layout[0][4], False),
                (0x0C, data_at, data_sectors, False),
                (0x0F, ext_start, ext_end - ext_start, False) if ext_start else None]
    disk_id = random.getrandbits(32)
    normal_mbr = make_mbr(primary(active), disk_id)
    plan.add(0, Data(normal_mbr))

    def ab_table(e, data_at):
        """IU1WXY A/B's own table: its slots A and B as p2 and p4 (its boot script loads from
        there), wherever they lie on the card, and its DATA as p3"""
        a = e["ab_physical"]["a"]
        b = e["ab_physical"]["b"]
        return make_mbr([
            (0x0C, boot_lba, boot_size // SECTOR, True),
            (a["type"], a["start"], a["sectors"], False),
            (0x0C, data_at, data_sectors, False),
            (b["type"], b["start"], b["sectors"], False),
        ], disk_id)

    for e in sd:
        e["mbr"] = e["dir"] + "/MBR.BIN"
        e["mbr_data"] = ab_table(e, active) if getattr(e["sys"], "is_ab", False) else normal_mbr

    if n_data > 1:
        for k, e in enumerate(owners):
            e["mbr"] = e["dir"] + "/MBR.BIN"
            # each system its own DATA; IU1WXY A/B keeps its own table with its slots (issue #8:
            # the plain one put the first system's root on p2, and IU1WXY started that system)
            e["mbr_data"] = (ab_table(e, data_areas[k]) if getattr(e["sys"], "is_ab", False)
                             else make_mbr(primary(data_areas[k]), disk_id))
        for e in sd:
            if e not in owners:
                e["mbr"] = owner(e)["mbr"]      # the donor's table: its DATA
                # its file is the donor's: written once, by the donor (a second SYSn/MBR.BIN broke the
                # folder, and when the extra came first in the menu the donor read the extra's table)
                e.pop("mbr_data", None)
    plan.add(SECTOR, Zero(UBOOT_OFFSET - SECTOR))
    plan.add(UBOOT_OFFSET, Data(ub.uboot))

    # Extended partition: each EBR points at its partition and the next EBR
    for k in range(1, len(layout)):
        e, slot, ebr, start, n = layout[k]
        nxt = layout[k + 1] if k + 1 < len(layout) else None
        part_type = (
            e["sys"].ab_slots[slot]["type"]
            if slot is not None
            else e["sys"].root_type
        )
        plan.add(
            ebr * SECTOR,
            Data(
                make_ebr(
                    part_type,
                    start - ebr,
                    n,
                    None if nxt is None else nxt[2] - ext_start,
                    0 if nxt is None else (nxt[3] + nxt[4] - nxt[2]),
                )
            ),
        )
        plan.add((ebr + 1) * SECTOR, Zero((start - ebr - 1) * SECTOR))

    # Root filesystems, byte for byte. IU1WXY contributes both A and B.
    for e, slot, _ebr, start, n in layout:
        system = e["sys"]
        if slot is not None:
            source = system.ab_slots[slot]
            plan.add(
                start * SECTOR,
                FileRange(system.raw, source["offset"], source["size"]),
            )
        else:
            plan.add(
                start * SECTOR,
                FileRange(system.raw, system.root_offset, system.root_size),
            )

    # BOOT
    script = menu_script(entries, default, timeout_s, gfx=gfx, ansi=screen, wait=wait)
    fat = Fat32Builder(boot_size, boot_lba, label="BOOT")
    if gfx:
        from . import menu_gfx
        tiles = [tile(e) for e in entries]
        fat.add_file("MENU/MENU.BMP", menu_gfx.to_framebuffer_bmp(menu_gfx.render_menu(tiles, None if wait else default)))
        for k, strip in enumerate(menu_gfx.rail_frames(tiles, None if wait else default)):
            fat.add_file("MENU/A%02d.BMP" % k, menu_gfx.to_framebuffer_bmp(strip))
        for i in range(len(entries)):
            fat.add_file("MENU/SEL%d.BMP" % (i + 1),
                         menu_gfx.to_framebuffer_bmp(menu_gfx.render_menu(tiles, None if wait else default, selected=i)))
    # What is on the card and where each system's DATA lies: for the app, to save and put back
    # one system's DATA (cardata.py)
    import json
    systems = []
    for i, e in enumerate(entries):
        if e["kind"] != "sd":
            continue
        at = data_areas[owners.index(owner(e))] if n_data > 1 else data_areas[0]
        extra = getattr(e["sys"], "donor", None) is not None
        from .cardata import system_id
        systems.append({"key": KEYS[i][0], "name": e["name"], "id": system_id(e["name"]),
                        "kind": "extra" if extra else "sd", "data_lba": at, "data_sectors": data_sectors})
    fat.add_file("MENU/CARD.JSON", json.dumps({"data_mode": data_mode, "systems": systems}, indent=1).encode())
    fat.add_file("boot.scr", make_script_image(script))
    fat.add_file("boot.cmd", script.encode())
    fat.add_file("bootmenu.env", env_file(default, timeout_s, xiegu, wait))
    readme = ["x6100-multiboot card", ""]
    for i, e in enumerate(entries):
        where = (f"{e['dir']}, root /dev/mmcblk0p{e['part']}" if e["kind"] == "sd" else "eMMC")
        readme.append(f"F{i + 1}  {e['name']}  ({where})")
    fat.add_file("menu.txt", ("\r\n".join(readme) + "\r\n").encode())
    if nes:
        # The emulator's settings, read at its start (extras/nes/nes_x6100.c), and the games
        fat.add_file("nes.txt", (
            t("# Emulator NES: glosnosc gry 0..300 (%)") + "\r\nvolume=100\r\n" +
            t("# Glosnosc (AF) 0..55, galka VOL") + "\r\nrxvol=40\r\n" +
            t("# Wycisz odbiornik radia (szum w tle); 0: zostaw jak byl") + "\r\nrxmute=0\r\n" +
            t("# Wyjscie dzwieku procesora do plyty radia 0..63") + "\r\nheadphone=47\r\n" +
            t("# Tryb odtwarzania plyty radia (jak OpenX6X00); 0: wylaczony") + "\r\nrecord=1\r\n" +
            t("# Obraz: 2x (ostry, 512x448), 4:3 (640x480) albo full (caly ekran)") + "\r\naspect=2x\r\n" +
            t("# Szybkosc myszy jako pistoletu Zapper 10..500 (%)") + "\r\nmouse=100\r\n" +
            t("# Bluetooth: pady, klawiatury i myszy (0: wylaczony)") + "\r\nbluetooth=1\r\n" +
            t("# Jezyk menu emulatora: pl albo en") + "\r\nlang=" + lang() + "\r\n" +
            t("# Gry: folder NES na tej partycji (.nes, .fds, .unf, .nsf); zapisy: NES/SAVES; "
              "BIOS FDS: NES/BIOS/disksys.rom; dziennik: nes-log.txt") + "\r\n").encode())
        fat.add_file("NES/" + t("WGRAJ-TU-GRY.txt"), (
            t("Wgraj tu swoje gry NES (.nes, .fds, .unf, .nsf). Emulator pokaze je na liscie.") + "\r\n" +
            t("Podfoldery tez dzialaja. Zapisy gier: folder SAVES. BIOS do gier FDS: BIOS/disksys.rom.") +
            "\r\n" + t("Obrazek gry (.png, .jpg, .bmp) o nazwie gry obok niej albo w folderze IMG: widac go przy liscie.") +
            "\r\n").encode())
        for folder, files in (("NES/", games), ("NES/IMG/", pics)):
            for name, g in files:
                if isinstance(g, bytes):
                    fat.add_file(folder + name, g)
                else:
                    fat.add_file(folder + name, src=(g, 0, os.path.getsize(g)))
    if any(extra_of(e) == "doom" or (getattr(e.get("sys"), "donor", None) is not None and not extra_of(e))
           for e in sd):
        # Doom's settings, read at its start (extras/doom/x6100_sound.c)
        fat.add_file("doom.txt", (
            t("# Doom: glosnosc efektow i muzyki 0..200 (%)") + "\r\nvolume=100\r\nmusic=100\r\n" +
            t("# Glosnosc glosnika radia (AF) 0..55, ustawiana przy starcie Dooma") + "\r\n"
            "rxvol=20\r\n" +
            t("# Wycisz odbiornik radia w Doomie (szum w tle); 0: zostaw jak byl") + "\r\nrxmute=0\r\n" +
            t("# Wyjscie dzwieku procesora do plyty radia 0..63") + "\r\nheadphone=47\r\n" +
            t("# Tryb odtwarzania plyty radia (jak OpenX6X00); 0: wylaczony") + "\r\nrecord=1\r\n" +
            t("# Dziennik startu Dooma: doom-log.txt na tej partycji") + "\r\n" +
            t("# Bluetooth: mysz i klawiatura sparowane w systemie, z ktorego Doom bierze jadro (0: wylaczony)") +
            "\r\nbluetooth=1\r\n").encode())
    for e in sd:
        s = e["sys"]
        if getattr(s, "is_ab", False):
            fat.add_file("ab.env", s.ab_env)
            fat.add_file("ab.bak", s.ab_bak)
            fat.add_file(e["dir"] + "/IU1WXY.SCR", s.ab_script)
        else:
            fat.add_file(e["dir"] + "/ZIMAGE", s.files["kernel"])
            if "fdt" in s.files:
                fat.add_file(e["dir"] + "/BOARD.DTB", s.files["fdt"])
            if "initrd" in s.files:
                fat.add_file(e["dir"] + "/INITRD", s.files["initrd"])
        if e.get("mbr_data"):
            fat.add_file(e["mbr"], e["mbr_data"])
    for off, piece in fat.extents():
        plan.add(boot_lba * SECTOR + off, piece)

    # DATA: FAT32s labelled DATA (OpenX6X00 looks for the label); the settings kept from the old card
    # (data_files: [(relative path, file, size)]) on the one the card starts with
    for at in data_areas:
        data = Fat32Builder(data_sectors * SECTOR, at, label="DATA")
        if isinstance(data_files, dict):
            # each system's own settings: {index among entries: files}; one shared DATA takes the
            # default system's (else whichever there is)
            if n_data > 1:
                own = owners[data_areas.index(at)]
                mine = data_files.get(next(i for i, e in enumerate(entries) if e is own))
            else:
                first_owner = owner(def_sd)
                mine = data_files.get(next(i for i, e in enumerate(entries) if e is first_owner)) or \
                    next(iter(data_files.values()), None)
        else:
            mine = data_files if data_files and at == active else None
        if mine:
            for rel, path, size in mine:
                data.add_file(rel, src=(path, 0, size))
        for off, piece in data.extents():
            plan.add(at * SECTOR + off, piece)

    plan.check()
    plan.info = {
        "entries": [{"key": KEYS[i][0], "name": e["name"], "kind": e["kind"],
                     "partition": e.get("part")} for i, e in enumerate(entries)],
        "default": default, "timeout": timeout_s, "wait": wait, "uboot": ub.uboot_version,
        "boot_mb": boot_size // MIB, "data_mb": data_sectors * SECTOR // MIB, "size": size,
        "data_mode": data_mode, "data_partitions": n_data, "screen": screen, "graphics": gfx,
        "data_files": sum(len(v) for v in data_files.values()) if isinstance(data_files, dict) else len(data_files or ()),
    }
    plan.script = script
    return plan
