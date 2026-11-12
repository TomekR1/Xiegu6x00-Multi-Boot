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
import random
import re

from .extents import Data, FileRange, Plan, Zero
from .fat import Fat32Builder
from .image import SECTOR, UBOOT_END, UBOOT_OFFSET, make_ebr, make_mbr, make_script_image

MIB = 1024 * 1024
ALIGN = MIB // SECTOR

# Front-panel keys in U-Boot: the X6100 key matrix from the device tree. As in j0ju's
# x6100-fw-mangler multiboot (used on radios): the row is driven low, the column read (0 = pressed); F1..F5 from OpenX6X00's src/front_keys.c (BTN_TRIGGER_HAPPY13..15, 19, 20)
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


def menu_script(entries, default, timeout_s, title="X6100 MULTIBOOT", gfx=False, ansi=False):
    """entries: [{"kind": "sd", "name", "dir", "part", "sys", "mbr": file or None} | {"kind": "xiegu", "name"}]

    gfx: MENU/MENU.BMP and MENU/SELn.BMP are on BOOT (menu_gfx). ansi: the U-Boot reads ANSI
    colours (the bundled one). Numbers in U-Boot's setexpr/itest are hex: bm_secs (0..9) is the
    same in both, the tick counter stays hex throughout.
    """
    L = []
    a = L.append
    e_ = ESC if ansi else ""
    a('echo "------------ X6100 multiboot menu ------------"')
    a("# Made by x6100-multiboot. Settings: bootmenu.env on this partition (edit on a PC).")
    a("setenv bm_default %d" % (default + 1))
    a("setenv bm_secs %d" % max(0, min(9, int(timeout_s))))
    for k, v in XIEGU_DEFAULTS.items():
        a('setenv %s "%s"' % (k, v))
    a("if fatload mmc 0:1 ${scriptaddr} bootmenu.env; then env import -t ${scriptaddr} ${filesize}; fi")
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
            mark = ("  %s[36m<- domyslny" % ESC) if i == default else ""
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
    for t in text:
        a("    " + _shown(t))
    a("fi")
    a("")
    a("# Keys, with a countdown each second; gpio prints every pin it reads, hence serial only")
    a("setenv bm_choice")
    a("setenv i 0")
    a('while test -z "${bm_choice}"; do')
    a("    setexpr bm_r ${i} % a")
    a("    if itest ${bm_r} -eq 0; then")
    a("        setexpr bm_left ${bm_ticks} - ${i}")
    a("        setexpr bm_left ${bm_left} / a")
    a("        " + _shown("%s[%s%s[0;37;40mStart F${bm_default} za ${bm_left} s   " % (e_, count_row, e_) if ansi
                          else "Start F${bm_default} za ${bm_left} s\\n"))
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
    a('    if test -z "${bm_choice}"; then')
    a("        if itest ${i} -ge ${bm_ticks}; then setenv bm_choice ${bm_default}; else sleep 0.1; setexpr i ${i} + 1; fi")
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
                       "else mmc write 0x45100000 0 1; fi; fi; " % e["mbr"])
            loads = ["fatload mmc 0:1 %s %s/ZIMAGE" % (s_.kernel_addr, d)]
            if s_.fdt_file:
                loads.append("fatload mmc 0:1 %s %s/BOARD.DTB" % (s_.fdt_addr, d))
            if s_.initrd_file:
                loads.append("fatload mmc 0:1 %s %s/INITRD" % (s_.initrd_addr, d))
            boot = "%s %s %s %s" % (s_.boot_cmd, s_.kernel_addr, s_.initrd_addr or "-", s_.fdt_addr or "")
            cmd = (pre + 'setenv bootargs "%s"; ' % s_.bootargs_for(e["part"]) +
                   "".join("if %s; then " % l for l in loads) + boot.strip() + "; " +
                   "fi; " * len(loads) +
                   'setenv stdout serial,vidconsole; echo "%s did not start"; sleep 3; setenv stdout serial'
                   % _ascii(e["name"]))
        assert "'" not in cmd
        a("setenv bm_boot%d '%s'" % (n, cmd))
    a("")
    a("run bm_boot${bm_choice}")
    a('if test "${bm_choice}" != "${bm_default}"; then run bm_boot${bm_default}; fi')
    a("run bm_boot%d" % first_sd)
    return "\n".join(L) + "\n"


def env_file(default, timeout_s, xiegu=None):
    x = dict(XIEGU_DEFAULTS)
    x.update(xiegu or {})
    lines = ["bm_default=%d" % (default + 1), "bm_secs=%d" % max(0, min(9, int(timeout_s)))]
    lines += ["%s=%s" % (k, v) for k, v in x.items()]
    return ("\n".join(lines) + "\n").encode()


def compose(entries, default=0, timeout_s=5, data_mb=1024, card_bytes=None, uboot_from=None,
            xiegu=None, boot_extra_mb=32, data_mode="shared", graphics=True):
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
    for i, e in enumerate(sd):
        e["dir"] = "SYS%d" % (i + 1)
        e["part"] = 2 if i == 0 else 4 + i      # p2, then p5, p6, ...

    kernels = sum(sum(len(v) for v in e["sys"].files.values()) for e in sd)
    pictures = (len(entries) + 1) * 400 * 1024 if gfx else 0
    boot_size = _up(max(64 * MIB, kernels + pictures + boot_extra_mb * MIB + 4 * MIB) // SECTOR) * SECTOR

    lba = ALIGN                                       # 1 MiB
    boot_lba = lba
    lba += boot_size // SECTOR
    layout = []                                       # (entry, ebr_lba or None, lba, sectors)
    first = sd[0]
    s0 = first["sys"].root_size // SECTOR
    layout.append((first, None, lba, s0))
    lba = _up(lba + s0)
    ext_start = None
    if len(sd) > 1:
        ext_start = lba
        for e in sd[1:]:
            ebr = lba
            start = ebr + ALIGN
            n = e["sys"].root_size // SECTOR
            layout.append((e, ebr, start, n))
            lba = _up(start + n)
        ext_end = lba
    data_lba = lba
    n_data = len(sd) if data_mode == "separate" else 1
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
    def_sd = entries[default] if entries[default]["kind"] == "sd" else sd[0]
    active = data_areas[sd.index(def_sd)] if n_data > 1 else data_areas[0]

    # MBR, the gap up to U-Boot cleared (an old GPT header lives there), U-Boot
    def primary(data_at):
        return [(0x0C, boot_lba, boot_size // SECTOR, True),
                (first["sys"].root_type, layout[0][2], layout[0][3], False),
                (0x0C, data_at, data_sectors, False),
                (0x0F, ext_start, ext_end - ext_start, False) if ext_start else None]
    disk_id = random.getrandbits(32)
    plan.add(0, Data(make_mbr(primary(active), disk_id)))
    if n_data > 1:
        for k, e in enumerate(sd):
            e["mbr"] = e["dir"] + "/MBR.BIN"
            e["mbr_data"] = make_mbr(primary(data_areas[k]), disk_id)
    plan.add(SECTOR, Zero(UBOOT_OFFSET - SECTOR))
    plan.add(UBOOT_OFFSET, Data(ub.uboot))

    # Extended partition: each EBR points at its partition and the next EBR
    for k in range(1, len(layout)):
        e, ebr, start, n = layout[k]
        nxt = layout[k + 1] if k + 1 < len(layout) else None
        plan.add(ebr * SECTOR, Data(make_ebr(e["sys"].root_type, start - ebr, n,
                                             None if nxt is None else nxt[1] - ext_start,
                                             0 if nxt is None else (nxt[2] + nxt[3] - nxt[1]))))
        plan.add((ebr + 1) * SECTOR, Zero((start - ebr - 1) * SECTOR))

    # Root filesystems, byte for byte
    for e, _ebr, start, n in layout:
        s = e["sys"]
        plan.add(start * SECTOR, FileRange(s.raw, s.root_offset, s.root_size))

    # BOOT
    script = menu_script(entries, default, timeout_s, gfx=gfx, ansi=screen)
    fat = Fat32Builder(boot_size, boot_lba, label="BOOT")
    if gfx:
        from . import menu_gfx
        tiles = [{"name": e["name"], "logo": e.get("logo")} for e in entries]
        fat.add_file("MENU/MENU.BMP", menu_gfx.to_framebuffer_bmp(menu_gfx.render_menu(tiles, default)))
        for i in range(len(entries)):
            fat.add_file("MENU/SEL%d.BMP" % (i + 1),
                         menu_gfx.to_framebuffer_bmp(menu_gfx.render_menu(tiles, default, selected=i)))
    fat.add_file("boot.scr", make_script_image(script))
    fat.add_file("boot.cmd", script.encode())
    fat.add_file("bootmenu.env", env_file(default, timeout_s, xiegu))
    readme = ["x6100-multiboot card", ""]
    for i, e in enumerate(entries):
        where = (f"{e['dir']}, root /dev/mmcblk0p{e['part']}" if e["kind"] == "sd" else "eMMC")
        readme.append(f"F{i + 1}  {e['name']}  ({where})")
    fat.add_file("menu.txt", ("\r\n".join(readme) + "\r\n").encode())
    for e in sd:
        s = e["sys"]
        fat.add_file(e["dir"] + "/ZIMAGE", s.files["kernel"])
        if "fdt" in s.files:
            fat.add_file(e["dir"] + "/BOARD.DTB", s.files["fdt"])
        if "initrd" in s.files:
            fat.add_file(e["dir"] + "/INITRD", s.files["initrd"])
        if e.get("mbr"):
            fat.add_file(e["mbr"], e["mbr_data"])
    for off, piece in fat.extents():
        plan.add(boot_lba * SECTOR + off, piece)

    # DATA: empty FAT32s labelled DATA (OpenX6X00 looks for the label)
    for at in data_areas:
        data = Fat32Builder(data_sectors * SECTOR, at, label="DATA")
        for off, piece in data.extents():
            plan.add(at * SECTOR + off, piece)

    plan.check()
    plan.info = {
        "entries": [{"key": KEYS[i][0], "name": e["name"], "kind": e["kind"],
                     "partition": e.get("part")} for i, e in enumerate(entries)],
        "default": default, "timeout": timeout_s, "uboot": ub.uboot_version,
        "boot_mb": boot_size // MIB, "data_mb": data_sectors * SECTOR // MIB, "size": size,
        "data_mode": data_mode, "data_partitions": n_data, "screen": screen, "graphics": gfx,
    }
    plan.script = script
    return plan
