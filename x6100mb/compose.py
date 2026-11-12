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


def menu_script(entries, default, timeout_s, title="X6100 BOOT MENU"):
    """entries: [{"kind": "sd", "name", "dir", "part", "sys": SourceSystem} | {"kind": "xiegu", "name"}]"""
    L = []
    a = L.append
    a('echo "------------ X6100 multiboot menu ------------"')
    a("# Made by x6100-multiboot. Settings: bootmenu.env on this partition (edit on a PC).")
    a("setenv bm_default %d" % (default + 1))
    a("setenv bm_timeout %d" % max(0, int(timeout_s * 10)))
    for k, v in XIEGU_DEFAULTS.items():
        a('setenv %s "%s"' % (k, v))
    a("if fatload mmc 0:1 ${scriptaddr} bootmenu.env; then env import -t ${scriptaddr} ${filesize}; fi")
    a("")
    a("")
    a("cls")
    a('echo ""')
    a('echo "   ===== %s ====="' % title)
    a('echo ""')
    for i, e in enumerate(entries):
        a('echo "   %s  %s"' % (KEYS[i][0], _ascii(e["name"])))
    a('echo ""')
    a('echo "   default: F${bm_default}"')
    a('echo ""')
    a("")
    a("setenv bm_choice")
    a("setenv i 0")
    a('while test -z "${bm_choice}"; do')
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
    a("        if test ${i} -ge ${bm_timeout}; then setenv bm_choice ${bm_default}; else sleep 0.1; setexpr i ${i} + 1; fi")
    a("    fi")
    a("done")
    a('echo "   -> F${bm_choice}"')
    a("")
    # Each entry's start as a variable, so a failed one can fall back to the default
    first_sd = None
    for i, e in enumerate(entries):
        n = i + 1
        if e["kind"] == "xiegu":
            cmd = ('echo "   Xiegu: mmc ${xiegu_dev}:${xiegu_part}"; setenv bootargs ${xiegu_args}; '
                   'if fatload mmc ${xiegu_dev}:${xiegu_part} 0x46000000 ${xiegu_kernel}; then '
                   'if fatload mmc ${xiegu_dev}:${xiegu_part} 0x49000000 ${xiegu_fdt}; then '
                   'bootz 0x46000000 - 0x49000000; fi; fi; '
                   'echo "   Xiegu did not start. The eMMC holds:"; mmc list; mmc dev ${xiegu_dev}; mmc part; '
                   'fatls mmc ${xiegu_dev}:${xiegu_part}; echo "   (take a photo) default system in 60 s"; sleep 60')
        else:
            if first_sd is None:
                first_sd = n
            s_ = e["sys"]
            d = e["dir"]
            loads = ["fatload mmc 0:1 %s %s/ZIMAGE" % (s_.kernel_addr, d)]
            if s_.fdt_file:
                loads.append("fatload mmc 0:1 %s %s/BOARD.DTB" % (s_.fdt_addr, d))
            if s_.initrd_file:
                loads.append("fatload mmc 0:1 %s %s/INITRD" % (s_.initrd_addr, d))
            boot = "%s %s %s %s" % (s_.boot_cmd, s_.kernel_addr, s_.initrd_addr or "-", s_.fdt_addr or "")
            cmd = ('setenv bootargs "%s"; ' % s_.bootargs_for(e["part"]) +
                   "".join("if %s; then " % l for l in loads) + boot.strip() + "; " +
                   "fi; " * len(loads) + 'echo "   %s did not start"; sleep 3' % _ascii(e["name"]))
        assert "'" not in cmd
        a("setenv bm_boot%d '%s'" % (n, cmd))
    a("")
    a("run bm_boot${bm_choice}")
    a('if test "${bm_choice}" != "${bm_default}"; then echo "   -> default F${bm_default}"; run bm_boot${bm_default}; fi')
    a('echo "   -> F%d"' % first_sd)
    a("run bm_boot%d" % first_sd)
    return "\n".join(L) + "\n"


def env_file(default, timeout_s, xiegu=None):
    x = dict(XIEGU_DEFAULTS)
    x.update(xiegu or {})
    lines = ["bm_default=%d" % (default + 1), "bm_timeout=%d" % int(timeout_s * 10)]
    lines += ["%s=%s" % (k, v) for k, v in x.items()]
    return ("\n".join(lines) + "\n").encode()


def compose(entries, default=0, timeout_s=5, data_mb=1024, card_bytes=None, uboot_from=None,
            xiegu=None, boot_extra_mb=32):
    """A Plan for the card. entries as for menu_script, without "dir"/"part" (filled in here).

    card_bytes: writing to a card of that size, DATA fills the rest; else the image has
    data_mb of DATA. uboot_from: the SourceSystem whose U-Boot goes on the card.
    """
    sd = [e for e in entries if e["kind"] == "sd"]
    if not sd:
        raise ComposeError("add at least one card image (the menu needs a system on the card)")
    if len(entries) > MAX_ENTRIES:
        raise ComposeError(f"at most {MAX_ENTRIES} entries (keys F1..F{MAX_ENTRIES})")
    if not 0 <= default < len(entries):
        raise ComposeError("the default entry is not in the list")
    ub = uboot_from or next((e["sys"] for e in sd if e["sys"].has_uboot), None)
    if ub is None or not ub.has_uboot:
        raise ComposeError("none of the images carries an Allwinner U-Boot")

    # Partition numbers and directories
    for i, e in enumerate(sd):
        e["dir"] = "SYS%d" % (i + 1)
        e["part"] = 2 if i == 0 else 4 + i      # p2, then p5, p6, ...

    kernels = sum(sum(len(v) for v in e["sys"].files.values()) for e in sd)
    boot_size = _up(max(64 * MIB, kernels + boot_extra_mb * MIB + 4 * MIB) // SECTOR) * SECTOR

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
    if card_bytes:
        card_sectors = card_bytes // SECTOR
        data_sectors = (card_sectors - data_lba) // ALIGN * ALIGN
        if data_sectors * SECTOR < 64 * MIB:
            raise ComposeError("the card is too small for these systems (%d MB short)" %
                               ((data_lba * SECTOR + 64 * MIB - card_bytes) // MIB + 1))
        size = card_bytes
    else:
        data_sectors = data_mb * MIB // SECTOR
        size = (data_lba + data_sectors) * SECTOR
    plan = Plan(size)

    # MBR, the gap up to U-Boot cleared (an old GPT header lives there), U-Boot
    primary = [(0x0C, boot_lba, boot_size // SECTOR, True),
               (first["sys"].root_type, layout[0][2], layout[0][3], False),
               (0x0C, data_lba, data_sectors, False),
               (0x0F, ext_start, ext_end - ext_start, False) if ext_start else None]
    disk_id = random.getrandbits(32)
    plan.add(0, Data(make_mbr(primary, disk_id)))
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
    script = menu_script(entries, default, timeout_s)
    fat = Fat32Builder(boot_size, boot_lba, label="BOOT")
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
    for off, piece in fat.extents():
        plan.add(boot_lba * SECTOR + off, piece)

    # DATA: an empty FAT32 labelled DATA (OpenX6X00 looks for the label)
    data = Fat32Builder(data_sectors * SECTOR, data_lba, label="DATA")
    for off, piece in data.extents():
        plan.add(data_lba * SECTOR + off, piece)

    plan.check()
    plan.info = {
        "entries": [{"key": KEYS[i][0], "name": e["name"], "kind": e["kind"],
                     "partition": e.get("part")} for i, e in enumerate(entries)],
        "default": default, "timeout": timeout_s, "uboot": ub.uboot_version,
        "boot_mb": boot_size // MIB, "data_mb": data_sectors * SECTOR // MIB, "size": size,
    }
    plan.script = script
    return plan
