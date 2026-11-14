"""Each system's own DATA on a card made here: found, saved to a .zip, put back, one by one.

With "one DATA per system" only the running system's DATA is in the partition table (the systems
look for it in one fixed place), so the computer shows one and the others cannot be reached as
drives. Here the card is read as it is: the BOOT partition says which systems are on it and where
each one's DATA lies (MENU/CARD.JSON; on cards made before that file, each system's own partition
table in SYSn/MBR.BIN and the names in boot.cmd), and each DATA is read with the FAT reader.
Putting one back builds that DATA anew from the .zip: what was in it is replaced.
"""
import json
import os
import re
import shutil
import struct
import tempfile
import zipfile

from . import devices
from .fat import Fat32Builder, FatError, FatReader
from .image import SECTOR, read_mbr

MANIFEST = "MENU/CARD.JSON"


class CardDataError(Exception):
    pass


class RawDev:
    """A card (or an image file) read like a file; whole sectors only go to the device, as Windows
    and macOS want of a raw disk"""

    def __init__(self, dev, write=False):
        self.is_file = os.path.isfile(dev)
        if self.is_file:
            self.fd = os.open(dev, (os.O_RDWR if write else os.O_RDONLY) | getattr(os, "O_BINARY", 0))
        else:
            self.fd = devices.open_for_write(dev) if write else devices.open_for_read(dev)
        self.pos = 0

    def seek(self, pos):
        self.pos = pos

    def read(self, n):
        start = self.pos // SECTOR * SECTOR
        end = (self.pos + n + SECTOR - 1) // SECTOR * SECTOR
        data = devices.pread(self.fd, end - start, start)
        out = data[self.pos - start:self.pos - start + n]
        self.pos += len(out)
        return out

    def write_at(self, pos, data):
        devices.pwrite(self.fd, data, pos)

    def close(self):
        try:
            if not self.is_file:
                devices.sync(self.fd)
        except OSError:
            pass
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _third(mbr):
    """(lba, sectors) of a partition table's third entry: where the systems look for DATA"""
    e = mbr[446 + 32:446 + 48]
    start, count = struct.unpack_from("<II", e, 8)
    return (start, count) if e[4] and count else None


def scan(f):
    """The DATA areas of the card f: [{"keys": ["F1"], "names": [...], "lba", "sectors", "active"}];
    one area with every system when the card has one shared DATA"""
    try:
        parts = read_mbr(f)
    except Exception as e:
        raise CardDataError(str(e))
    p1 = next((p for p in parts if p[0] == 1), None)
    f.seek(0)
    active = _third(f.read(SECTOR))
    if p1 is None or active is None:
        raise CardDataError("this is not a card made by Xiegu Multi Patcher (no BOOT and DATA partitions)")
    try:
        boot = FatReader(f, p1[2] * SECTOR)
    except FatError as e:
        raise CardDataError("the card's BOOT partition cannot be read: %s" % e)
    systems = None
    try:
        systems = json.loads(boot.read_file(MANIFEST).decode())["systems"]
    except Exception:
        systems = None
    if systems is None:                    # a card made before the manifest
        try:
            cmd = boot.read_file("boot.cmd").decode(errors="replace")
        except FatError:
            raise CardDataError("this is not a card made by Xiegu Multi Patcher (no boot.cmd)")
        names = {int(n): name for n, name in re.findall(r"setenv bm_boot(\d) '.*?echo \"([^\"]+?) did not start\"", cmd)}
        tables = dict(re.findall(r"setenv bm_boot(\d) '.*?fatload mmc 0:1 0x45100000 (\S+?);", cmd))
        systems = []
        for n in sorted(names):
            area = active
            if str(n) in tables:
                try:
                    area = _third(boot.read_file(tables[str(n)])) or active
                except FatError:
                    pass
            systems.append({"key": "F%d" % n, "name": names[n], "data_lba": area[0], "data_sectors": area[1]})
    areas = {}
    for s in systems:
        if not s.get("data_lba"):
            continue
        a = areas.setdefault(s["data_lba"], {"keys": [], "names": [], "lba": s["data_lba"],
                                             "sectors": s["data_sectors"], "active": s["data_lba"] == active[0]})
        a["keys"].append(s["key"])
        a["names"].append(s["name"])
    if not areas:
        raise CardDataError("no system with DATA on this card")
    return [areas[k] for k in sorted(areas)]


def _walk(fat, cluster=None, prefix=""):
    for name, is_dir, first, size in fat.listdir(cluster):
        if name.lower() in ("system volume information", "$recycle.bin", ".trashes", ".spotlight-v100",
                            ".fseventsd", ".temporaryitems") or name.startswith("._"):
            continue
        if is_dir:
            yield from _walk(fat, first, prefix + name + "/")
        else:
            yield prefix + name, first, size


def _file_bytes(fat, first, size):
    buf = bytearray()
    for c in fat._chain(first):
        if len(buf) >= size:
            break
        buf += fat._read(fat._cluster_off(c), fat.csize)
    return bytes(buf[:size])


def dump(f, area, zip_path, progress=None):
    """The files of the DATA at area into zip_path; how many"""
    try:
        fat = FatReader(f, area["lba"] * SECTOR)
    except FatError as e:
        raise CardDataError("this DATA cannot be read (never used, or damaged): %s" % e)
    files = list(_walk(fat))
    total = sum(size for _n, _c, size in files) or 1
    done = 0
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    tmp = zip_path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, first, size in files:
            z.writestr(name, _file_bytes(fat, first, size) if size else b"")
            done += size
            if progress:
                progress("backup", done, total, name)
    os.replace(tmp, zip_path)
    try:                                   # made by a helper with other rights: the folder's owner's
        st = os.stat(os.path.dirname(os.path.abspath(zip_path)))
        os.chown(zip_path, st.st_uid, st.st_gid)
    except (OSError, AttributeError):
        pass
    return len(files)


def restore(dev, area, zip_path, progress=None):
    """The DATA at area built anew from zip_path (what was in it is replaced); how many files"""
    tmp = tempfile.mkdtemp(prefix="x6100mb-restore-")
    try:
        from .backup import from_copy
        files = from_copy(zip_path, os.path.join(tmp, "DATA"))        # a .zip or a folder
        if not files:
            raise CardDataError("there are no files in this copy")
        size = area["sectors"] * SECTOR
        fat = Fat32Builder(size, area["lba"], label="DATA")
        for rel, path, n in files:
            fat.add_file(rel, src=(path, 0, n))
        try:
            pieces = list(fat.extents())
        except FatError as e:
            raise CardDataError("the copy does not fit this DATA: %s" % e)
        total = sum(p.length for _o, p in pieces) or 1
        done = 0
        if not os.path.isfile(dev):
            devices.unmount(dev)
        with RawDev(dev, write=True) as d:
            for off, piece in pieces:
                pos = area["lba"] * SECTOR + off
                for c in piece.chunks():
                    d.write_at(pos, c)
                    pos += len(c)
                    done += len(c)
                    if progress:
                        progress("restore", done, total, "")
        return len(files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(req, progress=None):
    """One request, as the window or its helper with admin rights makes it:
    {"op": "scan" | "dump" | "restore", "dev", "area"?, "zip"?} -> a result for JSON"""
    op, dev = req["op"], req["dev"]
    if op == "restore":
        return {"files": restore(dev, req["area"], req["zip"], progress)}
    with RawDev(dev) as f:
        if op == "scan":
            return {"areas": scan(f)}
        if op == "dump":
            return {"files": dump(f, req["area"], req["zip"], progress)}
    raise CardDataError("unknown request")


def main_card_data(argv):
    """python -m x6100mb card-data REQUEST.json RESULT.json  (the helper with admin rights)"""
    req_file, res_file = argv[:2]
    try:
        with open(req_file) as f:
            req = json.load(f)
        out = {"ok": run(req)}
    except Exception as e:
        from .backup import log_error
        log_error("card-data")
        out = {"error": str(e)}
    tmp = res_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, res_file)
    return 0 if "ok" in out else 1
