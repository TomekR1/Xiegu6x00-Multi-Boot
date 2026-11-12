"""FAT: reading files from a FAT12/16/32 partition inside an image, and building a FAT32 one.

The reader takes long names (VFAT), so "sun8i-r16-x6100.dtb" is found as it is spelled. The
writer makes FAT32 with 8.3 names only (U-Boot and Linux read them, case does not matter), files
laid out contiguously: everything it produces is a list of extents (offset, bytes or a file
range), so a 32 GB DATA partition costs only its tables.
"""
import random
import struct
import time

from .extents import Data, FileRange, Zero

SECTOR = 512


class FatError(Exception):
    pass


# --------------------------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------------------------
class FatReader:
    def __init__(self, f, part_offset):
        self.f = f
        self.base = part_offset
        bs = self._read(0, SECTOR)
        if bs[510:512] != b"\x55\xaa":
            raise FatError("no FAT boot sector")
        self.bps, self.spc, self.rsv, self.nfats, self.root_ents, tot16, _media, fatsz16 = \
            struct.unpack_from("<HBHBHHBH", bs, 11)
        if self.bps not in (512, 1024, 2048, 4096) or self.spc == 0 or self.nfats == 0:
            raise FatError("not a FAT filesystem")
        tot32, = struct.unpack_from("<I", bs, 32)
        fatsz32, = struct.unpack_from("<I", bs, 36)
        self.fatsz = fatsz16 or fatsz32
        self.total = tot16 or tot32
        root_secs = (self.root_ents * 32 + self.bps - 1) // self.bps
        self.fat_start = self.rsv
        self.root_start = self.rsv + self.nfats * self.fatsz
        self.data_start = self.root_start + root_secs
        clusters = (self.total - self.data_start) // self.spc
        if clusters < 4085:
            self.kind = 12
        elif clusters < 65525:
            self.kind = 16
        else:
            self.kind = 32
        self.root_cluster = struct.unpack_from("<I", bs, 44)[0] if self.kind == 32 else 0
        self.csize = self.bps * self.spc
        self._fat = self._read(self.fat_start * self.bps, self.fatsz * self.bps)

    def _read(self, off, n):
        self.f.seek(self.base + off)
        d = self.f.read(n)
        if len(d) != n:
            raise FatError("image ends inside the FAT partition")
        return d

    def _next(self, c):
        if self.kind == 32:
            v = struct.unpack_from("<I", self._fat, c * 4)[0] & 0x0FFFFFFF
            return None if v >= 0x0FFFFFF8 else v
        if self.kind == 16:
            v = struct.unpack_from("<H", self._fat, c * 2)[0]
            return None if v >= 0xFFF8 else v
        o = c + c // 2
        v = struct.unpack_from("<H", self._fat, o)[0]
        v = v >> 4 if c & 1 else v & 0xFFF
        return None if v >= 0xFF8 else v

    def _chain(self, c):
        seen = 0
        while c is not None and c >= 2:
            yield c
            c = self._next(c)
            seen += 1
            if seen > 1 << 22:
                raise FatError("FAT chain loop")

    def _cluster_off(self, c):
        return (self.data_start + (c - 2) * self.spc) * self.bps

    def _dir_bytes(self, cluster):
        if cluster == 0:     # FAT12/16 fixed root
            return self._read(self.root_start * self.bps, self.root_ents * 32)
        return b"".join(self._read(self._cluster_off(c), self.csize) for c in self._chain(cluster))

    def listdir(self, cluster=None):
        """[(name, is_dir, first_cluster, size)] of a directory (the root by default)"""
        if cluster is None:
            cluster = self.root_cluster
        data = self._dir_bytes(cluster)
        out, lfn = [], {}
        for i in range(0, len(data), 32):
            e = data[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5:
                lfn = {}
                continue
            attr = e[11]
            if attr == 0x0F:
                seq = e[0] & 0x1F
                part = (e[1:11] + e[14:26] + e[28:32]).decode("utf-16-le", "replace")
                lfn[seq] = part.split("\x00")[0].replace("￿", "")
                continue
            if attr & 0x08:      # volume label
                lfn = {}
                continue
            short = e[0:8].decode("latin-1").rstrip()
            ext = e[8:11].decode("latin-1").rstrip()
            if e[12] & 0x08:
                short = short.lower()
            if e[12] & 0x10:
                ext = ext.lower()
            name = "".join(lfn[k] for k in sorted(lfn)) if lfn else (short + ("." + ext if ext else ""))
            lfn = {}
            if name in (".", ".."):
                continue
            hi, = struct.unpack_from("<H", e, 20)
            lo, = struct.unpack_from("<H", e, 26)
            size, = struct.unpack_from("<I", e, 28)
            out.append((name, bool(attr & 0x10), (hi << 16) | lo if self.kind == 32 else lo, size))
        return out

    def find(self, path):
        cluster = None
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        for i, p in enumerate(parts):
            hit = [e for e in self.listdir(cluster) if e[0].lower() == p.lower()]
            if not hit:
                return None
            if i == len(parts) - 1:
                return hit[0]
            if not hit[0][1]:
                return None
            cluster = hit[0][2]
        return None

    def read_file(self, path):
        e = self.find(path)
        if e is None or e[1]:
            raise FatError(f"{path}: not found")
        size = e[3]
        buf = bytearray()
        for c in self._chain(e[2]):
            buf += self._read(self._cluster_off(c), self.csize)
            if len(buf) >= size:
                break
        return bytes(buf[:size])


# --------------------------------------------------------------------------------------------
# Writer (FAT32)
# --------------------------------------------------------------------------------------------
def _short_name(name):
    if "." in name:
        base, ext = name.rsplit(".", 1)
    else:
        base, ext = name, ""
    base, ext = base.upper(), ext.upper()
    ok = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-~!#$%&'(){}^@`")
    if not base or len(base) > 8 or len(ext) > 3 or any(c not in ok for c in base + ext):
        raise FatError(f"{name}: needs an 8.3 name")
    return base.ljust(8).encode() + ext.ljust(3).encode()


def _dos_time(t):
    lt = time.localtime(t)
    d = ((max(lt.tm_year, 1980) - 1980) << 9) | (lt.tm_mon << 5) | lt.tm_mday
    tm = (lt.tm_hour << 11) | (lt.tm_min << 5) | (lt.tm_sec // 2)
    return tm, d


def _dirent(name11, attr, cluster, size, now):
    tm, d = _dos_time(now)
    return struct.pack("<11sBBBHHHHHHHI", name11, attr, 0, 0, tm, d, d, cluster >> 16, tm, d,
                       cluster & 0xFFFF, size)


def fat32_cluster_size(size_bytes):
    """Sectors per cluster for a FAT32 of this size: Windows' choices, smaller for a small one"""
    gb = 1 << 30
    if size_bytes <= 8 * gb:
        spc = 8
    elif size_bytes <= 16 * gb:
        spc = 16
    elif size_bytes <= 32 * gb:
        spc = 32
    else:
        spc = 64
    while spc > 1 and size_bytes // (spc * SECTOR) < 70000:
        spc //= 2
    if size_bytes // (spc * SECTOR) < 66000:
        raise FatError("too small for FAT32 (needs some 34 MB)")
    return spc


class Fat32Builder:
    """A FAT32 filesystem of size_bytes for a partition at start_lba; files from bytes or file ranges.

    add_file(path, data=bytes) or add_file(path, src=(filename, offset, length)); folders are
    made on the way. extents() gives [(offset in the partition, Data | FileRange | Zero)].
    """

    def __init__(self, size_bytes, start_lba, label="NO NAME", volume_id=None):
        self.total = size_bytes // SECTOR
        self.spc = fat32_cluster_size(size_bytes)
        self.csize = self.spc * SECTOR
        self.rsv = 32
        self.start_lba = start_lba
        self.label = label.upper()[:11].ljust(11).encode()
        self.volid = volume_id if volume_id is not None else random.getrandbits(32)
        # FAT size: Microsoft's formula
        tmp1 = self.total - self.rsv
        tmp2 = (256 * self.spc + 2) // 2
        self.fatsz = (tmp1 + tmp2 - 1) // tmp2
        self.data_start = self.rsv + 2 * self.fatsz
        self.nclusters = (self.total - self.data_start) // self.spc
        if self.nclusters < 65525:
            raise FatError("too few clusters for FAT32")
        self.now = time.time()
        self.root = {"entries": [], "children": {}}
        self.files = []

    def _dir(self, parts):
        d = self.root
        for p in parts:
            if p.upper() not in d["children"]:
                nd = {"entries": [], "children": {}, "name": p}
                d["children"][p.upper()] = nd
                d["entries"].append(("dir", p, nd))
            d = d["children"][p.upper()]
        return d

    def add_file(self, path, data=None, src=None):
        parts = [p for p in path.split("/") if p]
        d = self._dir(parts[:-1])
        size = len(data) if data is not None else src[2]
        f = {"name": parts[-1], "data": data, "src": src, "size": size}
        _short_name(parts[-1])
        d["entries"].append(("file", parts[-1], f))
        self.files.append(f)

    def _clusters_for(self, n):
        return max(1, (n + self.csize - 1) // self.csize)

    def extents(self):
        next_c = [2]

        def alloc(n):
            c = next_c[0]
            next_c[0] += n
            if next_c[0] - 2 > self.nclusters:
                raise FatError("the partition is too small for its files")
            return c

        fat = {}

        def chain(first, n):
            for i in range(n):
                fat[first + i] = first + i + 1 if i < n - 1 else 0x0FFFFFFF

        # Clusters: directories first (each sized for its entries), then files
        def size_dirs(d, is_root):
            n = len(d["entries"]) + (1 if is_root else 2)
            d["nclus"] = self._clusters_for(n * 32)
            d["cluster"] = alloc(d["nclus"])
            chain(d["cluster"], d["nclus"])
            for kind, _name, obj in d["entries"]:
                if kind == "dir":
                    size_dirs(obj, False)

        size_dirs(self.root, True)
        for f in self.files:
            if f["size"]:
                n = self._clusters_for(f["size"])
                f["cluster"] = alloc(n)
                chain(f["cluster"], n)
            else:
                f["cluster"] = 0

        out = []

        def dir_bytes(d, parent_cluster, is_root):
            buf = bytearray()
            if is_root:
                buf += _dirent(self.label, 0x08, 0, 0, self.now)
            else:
                buf += _dirent(b".          ", 0x10, d["cluster"], 0, self.now)
                buf += _dirent(b"..         ", 0x10, 0 if parent_cluster == 2 else parent_cluster, 0, self.now)
            for kind, name, obj in d["entries"]:
                if kind == "dir":
                    buf += _dirent(_short_name(name), 0x10, obj["cluster"], 0, self.now)
                else:
                    buf += _dirent(_short_name(name), 0x20, obj["cluster"], obj["size"], self.now)
            buf += b"\x00" * (d["nclus"] * self.csize - len(buf))
            out.append((self._coff(d["cluster"]), Data(buf)))
            for kind, _name, obj in d["entries"]:
                if kind == "dir":
                    dir_bytes(obj, d["cluster"], False)

        dir_bytes(self.root, 2, True)
        for f in self.files:
            if not f["size"]:
                continue
            off = self._coff(f["cluster"])
            pad = self._clusters_for(f["size"]) * self.csize - f["size"]
            if f["data"] is not None:
                out.append((off, Data(f["data"] + b"\x00" * pad)))
            else:
                # Whole sectors straight from the file, the last bit and the padding as data
                path, soff, size = f["src"]
                full = size // SECTOR * SECTOR
                if full:
                    out.append((off, FileRange(path, soff, full)))
                with open(path, "rb") as sf:
                    sf.seek(soff + full)
                    tail = sf.read(size - full)
                if len(tail) != size - full:
                    raise FatError(f"{path}: ends early")
                out.append((off + full, Data(tail + b"\x00" * pad)))

        used = next_c[0] - 2
        # Boot sector, FSInfo, their backups
        bs = bytearray(SECTOR)
        bs[0:3] = b"\xEB\x58\x90"
        bs[3:11] = b"X6MBOOT "
        struct.pack_into("<HBHBHHBHHHII", bs, 11, SECTOR, self.spc, self.rsv, 2, 0, 0, 0xF8, 0,
                         63, 255, self.start_lba, self.total)
        struct.pack_into("<IHHIHH", bs, 36, self.fatsz, 0, 0, 2, 1, 6)
        struct.pack_into("<BBBI11s8s", bs, 64, 0x80, 0, 0x29, self.volid, self.label, b"FAT32   ")
        bs[510:512] = b"\x55\xaa"
        fsi = bytearray(SECTOR)
        struct.pack_into("<I", fsi, 0, 0x41615252)
        struct.pack_into("<III", fsi, 484, 0x61417272, self.nclusters - used, next_c[0])
        struct.pack_into("<I", fsi, 508, 0xAA550000)
        third = bytearray(SECTOR)
        third[510:512] = b"\x55\xaa"
        boot = bytes(bs) + bytes(fsi) + bytes(third)
        reserved = bytearray(self.rsv * SECTOR)
        reserved[0:3 * SECTOR] = boot
        reserved[6 * SECTOR:9 * SECTOR] = boot
        out.append((0, Data(reserved)))

        # FATs: the used part written, the rest zeros (written too: the card may hold old data)
        fatbuf = bytearray((4 * next_c[0] + SECTOR - 1) // SECTOR * SECTOR)
        struct.pack_into("<II", fatbuf, 0, 0x0FFFFFF8, 0x0FFFFFFF)
        for c, v in fat.items():
            struct.pack_into("<I", fatbuf, c * 4, v)
        fatbytes = self.fatsz * SECTOR
        for i in range(2):
            base = (self.rsv + i * self.fatsz) * SECTOR
            out.append((base, Data(fatbuf)))
            rest = fatbytes - len(fatbuf)
            if rest:
                out.append((base + len(fatbuf), Zero(rest)))
        return out

    def _coff(self, c):
        return (self.data_start + (c - 2) * self.spc) * SECTOR
