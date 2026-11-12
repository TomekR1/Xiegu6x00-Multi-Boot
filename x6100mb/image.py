"""Source card images: what is on them (MBR, Allwinner U-Boot, the boot script, kernel, rootfs)."""
import os
import re
import shutil
import struct
import tempfile
import time
import zipfile
import zlib

from .fat import FatError, FatReader

SECTOR = 512
UBOOT_OFFSET = 8 * 1024          # Allwinner's boot ROM reads the SPL from here
UBOOT_END = 1024 * 1024          # first partitions start at 1 MiB
FAT_TYPES = (0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E)
EXTENDED = (0x05, 0x0F, 0x85)
DEFAULT_FDTFILE = "sun8i-r16-x6100.dtb"   # U-Boot's ${fdtfile} on the X6100


class ImageError(Exception):
    pass


# --------------------------------------------------------------------------------------------
# MBR
# --------------------------------------------------------------------------------------------
def read_mbr(f):
    """[(number, type, start_lba, sectors, bootable)] with logical partitions numbered from 5"""
    f.seek(0)
    mbr = f.read(SECTOR)
    if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xaa":
        raise ImageError("no MBR partition table (is this a card image?)")
    parts = []
    for i in range(4):
        e = mbr[446 + 16 * i:462 + 16 * i]
        boot, ptype = e[0], e[4]
        start, count = struct.unpack_from("<II", e, 8)
        if ptype == 0 or count == 0:
            continue
        if ptype == 0xEE:
            raise ImageError("GPT images are not supported")
        if ptype in EXTENDED:
            n = 5
            ebr_lba = start
            for _ in range(128):
                f.seek(ebr_lba * SECTOR)
                ebr = f.read(SECTOR)
                if ebr[510:512] != b"\x55\xaa":
                    break
                t1 = ebr[446 + 4]
                s1, c1 = struct.unpack_from("<II", ebr, 446 + 8)
                if t1 and c1:
                    parts.append((n, t1, ebr_lba + s1, c1, False))
                    n += 1
                t2 = ebr[462 + 4]
                s2, _ = struct.unpack_from("<II", ebr, 462 + 8)
                if not t2:
                    break
                ebr_lba = start + s2
            continue
        parts.append((i + 1, ptype, start, count, boot == 0x80))
    return parts


def _entry(ptype, start, count, boot=False):
    return struct.pack("<B3sB3sII", 0x80 if boot else 0, b"\xfe\xff\xff", ptype, b"\xfe\xff\xff", start, count)


def make_mbr(primary, disk_id):
    """primary: up to 4 (type, start_lba, sectors, bootable) or None"""
    mbr = bytearray(SECTOR)
    struct.pack_into("<I", mbr, 440, disk_id)
    for i, p in enumerate(primary):
        if p:
            mbr[446 + 16 * i:462 + 16 * i] = _entry(p[0], p[1], p[2], p[3])
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def make_ebr(part_type, rel_start, count, next_rel=None, next_count=0):
    ebr = bytearray(SECTOR)
    ebr[446:462] = _entry(part_type, rel_start, count)
    if next_rel is not None:
        ebr[462:478] = _entry(0x05, next_rel, next_count)
    ebr[510:512] = b"\x55\xaa"
    return bytes(ebr)


# --------------------------------------------------------------------------------------------
# U-Boot legacy script images (mkimage -T script)
# --------------------------------------------------------------------------------------------
IH_MAGIC = 0x27051956


def parse_script_image(data):
    if len(data) < 64:
        raise ImageError("boot.scr too short")
    magic, _hcrc, _time, size, _load, _ep, _dcrc, _os, _arch, itype, _comp = \
        struct.unpack_from(">IIIIIIIBBBB", data, 0)
    if magic != IH_MAGIC:
        # A plain text script (some images keep boot.cmd only)
        return data.decode("utf-8", "replace")
    if itype != 6:
        raise ImageError("boot.scr is not a script image")
    body = data[64:64 + size]
    # Multi-file layout: lengths, a zero, then the first file (the script)
    first, = struct.unpack_from(">I", body, 0)
    off = 4
    while struct.unpack_from(">I", body, off - 4)[0] != 0:
        off += 4
    text = body[off:off + first]
    return text.decode("utf-8", "replace").rstrip("\x00")


def make_script_image(text, name="X6100 boot menu"):
    payload = text.encode("utf-8")
    body = struct.pack(">II", len(payload), 0) + payload
    hdr = bytearray(struct.pack(">IIIIIIIBBBB32s", IH_MAGIC, 0, int(time.time()), len(body), 0, 0,
                                zlib.crc32(body) & 0xFFFFFFFF, 5, 2, 6, 0, name.encode()[:31]))
    struct.pack_into(">I", hdr, 4, zlib.crc32(bytes(hdr)) & 0xFFFFFFFF)
    return bytes(hdr) + body


# --------------------------------------------------------------------------------------------
# A source image
# --------------------------------------------------------------------------------------------
def open_source(path, cache_dir, progress=None):
    """The raw image's path: a .zip is unpacked into cache_dir first (once)"""
    if not zipfile.is_zipfile(path):
        return path
    with zipfile.ZipFile(path) as z:
        imgs = [i for i in z.infolist() if i.filename.lower().endswith((".img", ".bin", ".raw"))]
        if len(imgs) != 1:
            raise ImageError(f"{os.path.basename(path)}: expected one .img inside the zip, found {len(imgs)}")
        info = imgs[0]
        os.makedirs(cache_dir, exist_ok=True)
        st = os.stat(path)
        out = os.path.join(cache_dir, f"{os.path.basename(info.filename)}.{int(st.st_mtime)}.{st.st_size}")
        if os.path.exists(out) and os.path.getsize(out) == info.file_size:
            return out
        tmp = out + ".part"
        done = 0
        with z.open(info) as src, open(tmp, "wb") as dst:
            while True:
                d = src.read(4 << 20)
                if not d:
                    break
                dst.write(d)
                done += len(d)
                if progress:
                    progress(done, info.file_size)
        os.replace(tmp, out)
        return out


class SourceSystem:
    """One system from a card image: its kernel, device tree, boot arguments and root filesystem"""

    def __init__(self, path, raw_path):
        self.path = path
        self.raw = raw_path
        self.name = re.sub(r"(-sdcard)?\.img(\.zip)?$", "", os.path.basename(path), flags=re.I)
        if self.name.lower() in ("sdcard", "image", "disk", ""):
            self.name = os.path.basename(os.path.dirname(os.path.abspath(path))) or self.name
        self.warnings = []
        with open(raw_path, "rb") as f:
            self.parts = read_mbr(f)
            f.seek(UBOOT_OFFSET)
            spl = f.read(UBOOT_END - UBOOT_OFFSET)
            self.has_uboot = spl[4:12] == b"eGON.BT0"
            m = re.search(rb"U-Boot SPL (\d{4}\.\d{2}[^ ]*)", spl)
            self.uboot_version = m.group(1).decode() if m else None
            self.uboot = spl if self.has_uboot else None

            boots = [p for p in self.parts if p[1] in FAT_TYPES]
            if not boots:
                raise ImageError("no FAT boot partition")
            self.boot_part = boots[0]
            # Xiegu's update card: booting it flashes the radio's eMMC. Never a menu entry.
            for p in boots[1:]:
                try:
                    if FatReader(f, p[2] * SECTOR).find("rootfs.tar"):
                        raise ImageError("to obraz instalacyjny Xiegu (wgrywa system do eMMC radia), nie system "
                                         "do uruchamiania z karty. Dodaj pozycję \"Xiegu z eMMC\".")
                except FatError:
                    pass
            fat = FatReader(f, self.boot_part[2] * SECTOR)
            self.boot_files = [e[0] for e in fat.listdir()]
            script = None
            for cand in ("boot.scr", "boot.cmd"):
                if fat.find(cand):
                    script = parse_script_image(fat.read_file(cand))
                    break
            if script is None:
                raise ImageError("no boot.scr on the boot partition (extlinux / uEnv not supported)")
            self.script = script
            self._parse_script(fat)

        root_parts = [p for p in self.parts if p[0] == self.root_number]
        if not root_parts:
            raise ImageError(f"the boot script boots partition {self.root_number}, which the image has not")
        rp = root_parts[0]
        self.root_offset = rp[2] * SECTOR
        self.root_size = rp[3] * SECTOR
        self.root_type = rp[1]
        if os.path.getsize(raw_path) < self.root_offset + self.root_size:
            raise ImageError("the image ends before its root partition does")
        with open(raw_path, "rb") as f:
            f.seek(self.root_offset + 1024)
            sb = f.read(1024)
        self.root_is_ext = sb[56:58] == b"\x53\xef"
        if not self.root_is_ext:
            self.warnings.append("root partition is not ext2/3/4")
        self.os_release = None

    def _parse_script(self, fat):
        text = self.script
        text = re.sub(r"\\\s*\n", " ", text)      # lines continued with a backslash
        lines = [l.strip() for l in text.splitlines()]
        args = None
        loads = {}
        boot = None
        env = {"fdtfile": DEFAULT_FDTFILE}
        for l in lines:
            if not l or l.startswith("#"):
                continue
            m = re.match(r"setenv\s+bootargs\s+(.*)$", l)
            if m:
                args = m.group(1).strip().strip('"').strip("'")
                continue
            m = re.match(r"setenv\s+(\w+)\s+(\S+)$", l)
            if m:
                env[m.group(1)] = m.group(2).strip('"')
            m = re.match(r"(?:fat|ext[24])?load\s+mmc\s+\S+\s+(\S+)\s+(\S+)", l)
            if m:
                loads[m.group(1)] = m.group(2)
                continue
            m = re.match(r"(bootz|bootm)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?", l)
            if m:
                boot = m.groups()
        if args is None:
            raise ImageError("the boot script sets no bootargs")
        if boot is None:
            raise ImageError("the boot script has no bootz/bootm")

        def resolve(name):
            return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: env.get(m.group(1) or m.group(2), ""), name)

        cmd, kaddr, raddr, faddr = boot
        if kaddr not in loads:
            raise ImageError(f"the boot script boots {kaddr}, which it loads nothing to")
        self.boot_cmd = cmd
        self.kernel_addr, self.kernel_file = kaddr, resolve(loads[kaddr])
        self.initrd_addr = raddr if raddr and raddr != "-" else None
        self.initrd_file = resolve(loads[raddr]) if self.initrd_addr in loads else None
        self.fdt_addr = faddr
        self.fdt_file = resolve(loads[faddr]) if faddr in loads else None
        if self.fdt_file and not fat.find(self.fdt_file):
            dtbs = [n for n in self.boot_files if n.lower().endswith(".dtb")]
            if len(dtbs) == 1:
                self.fdt_file = dtbs[0]
        self.files = {}
        for key, fname in (("kernel", self.kernel_file), ("initrd", self.initrd_file), ("fdt", self.fdt_file)):
            if fname:
                e = fat.find(fname)
                if not e or e[1]:
                    raise ImageError(f"{fname} (in the boot script) is not on the boot partition")
                self.files[key] = fat.read_file(fname)
        m = re.search(r"\broot=(\S+)", args)
        if not m:
            raise ImageError("bootargs have no root=")
        mm = re.match(r"/dev/mmcblk0p(\d+)$", m.group(1))
        if not mm:
            raise ImageError(f"root={m.group(1)}: only /dev/mmcblk0pN is supported")
        self.root_number = int(mm.group(1))
        self.bootargs = args

    def bootargs_for(self, partition_number):
        return re.sub(r"\broot=\S+", f"root=/dev/mmcblk0p{partition_number}", self.bootargs)

    def summary(self):
        mb = 1024 * 1024
        return (f"kernel {self.kernel_file} ({len(self.files['kernel']) // 1024} KB), "
                f"dtb {self.fdt_file}, rootfs {self.root_size // mb} MB, "
                f"U-Boot {self.uboot_version or ('yes' if self.has_uboot else 'none')}")


def bundled_uboot_path():
    """The menu's own U-Boot (uboot/build.sh: sets up the X6100 screen), if this build carries it"""
    import sys
    bases = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")]
    if hasattr(sys, "_MEIPASS"):
        bases.insert(0, os.path.join(sys._MEIPASS, "x6100mb", "data"))
    for b in bases:
        p = os.path.join(b, "u-boot-x6100-menu.bin")
        if os.path.isfile(p):
            return p
    return None


class UBoot:
    """A U-Boot from a file (the bundled one, or one given): what compose() puts at 8 KiB"""

    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        if data[4:12] != b"eGON.BT0":
            raise ImageError(f"{os.path.basename(path)}: not an Allwinner U-Boot (no eGON header)")
        if len(data) > UBOOT_END - UBOOT_OFFSET:
            raise ImageError(f"{os.path.basename(path)}: U-Boot larger than {UBOOT_END - UBOOT_OFFSET} bytes")
        self.uboot = data + b"\x00" * ((-len(data)) % SECTOR)
        self.has_uboot = True
        m = re.search(rb"U-Boot SPL (\d{4}\.\d{2}[^ ]*)", data)
        self.uboot_version = (m.group(1).decode() if m else "?") + " (menu, ekran)"
        self.path = path


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "x6100-multiboot")


def clear_cache():
    shutil.rmtree(cache_dir(), ignore_errors=True)


def temp_dir():
    return tempfile.mkdtemp(prefix="x6100mb-")
