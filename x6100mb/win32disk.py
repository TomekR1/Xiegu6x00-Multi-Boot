"""Windows disks through the system's own calls (kernel32 DeviceIoControl), no helper programs.

Asking PowerShell, diskpart and the like from a packed app looked to Windows Defender like a program
running an attacker's commands; these calls are what any disk tool makes itself.
"""
import ctypes
import string
import struct
from ctypes import wintypes

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
SHARE_RW, OPEN_EXISTING = 3, 3
IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
IOCTL_DISK_GET_LENGTH_INFO = 0x7405C
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x560000
IOCTL_DISK_UPDATE_PROPERTIES = 0x70140
FSCTL_LOCK_VOLUME, FSCTL_UNLOCK_VOLUME, FSCTL_DISMOUNT_VOLUME = 0x90018, 0x9001C, 0x90020
BUS = {7: "USB", 12: "SD", 13: "MMC"}            # the buses a card sits on
INVALID = ctypes.c_void_p(-1).value

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileW.restype = wintypes.HANDLE
_k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                           wintypes.DWORD, wintypes.HANDLE]
_k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k.CloseHandle.argtypes = [wintypes.HANDLE]


def _open(path, access=0):
    h = _k.CreateFileW(path, access, SHARE_RW, None, OPEN_EXISTING, 0, None)
    return None if h in (None, INVALID) else h


def _ioctl(h, code, inbuf=b"", outsize=0):
    """The answer's bytes, or None when the call fails"""
    inb = ctypes.create_string_buffer(inbuf, len(inbuf)) if inbuf else None
    out = ctypes.create_string_buffer(outsize) if outsize else None
    got = wintypes.DWORD(0)
    ok = _k.DeviceIoControl(h, code, inb, len(inbuf), out, outsize, ctypes.byref(got), None)
    return (out.raw[:got.value] if out is not None else b"") if ok else None


def _disks_of_volume(letter):
    """The disk numbers a drive letter lies on"""
    h = _open("\\\\.\\%s:" % letter)
    if not h:
        return []
    try:
        raw = _ioctl(h, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, outsize=8 + 24 * 8)
    finally:
        _k.CloseHandle(h)
    if not raw:
        return []
    n = struct.unpack_from("<I", raw, 0)[0]
    return [struct.unpack_from("<I", raw, 8 + 24 * i)[0] for i in range(min(n, 8))]


def letters():
    """The drive letters in use"""
    mask = _k.GetLogicalDrives()
    return [c for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]


def system_disks():
    """The disks the system drive (and so Windows itself) lies on"""
    import os
    sysdrive = (os.environ.get("SystemDrive") or "C:")[0]
    return set(_disks_of_volume(sysdrive))


def describe(n):
    """{"number", "name", "size", "bus", "removable"} of PhysicalDriveN, or None"""
    h = _open("\\\\.\\PhysicalDrive%d" % n)
    if not h:
        return None
    try:
        raw = _ioctl(h, IOCTL_STORAGE_QUERY_PROPERTY, struct.pack("<II4x", 0, 0), 1024)
        size = _ioctl(h, IOCTL_DISK_GET_LENGTH_INFO, outsize=8)
    finally:
        _k.CloseHandle(h)
    if not raw or len(raw) < 32:
        return None

    def text(off):
        if not off or off >= len(raw):
            return ""
        return raw[off:raw.index(b"\0", off) if b"\0" in raw[off:] else len(raw)].decode("latin-1").strip()
    removable = raw[10] != 0
    vendor, product = text(struct.unpack_from("<I", raw, 12)[0]), text(struct.unpack_from("<I", raw, 16)[0])
    bus = struct.unpack_from("<I", raw, 28)[0]
    return {"number": n, "name": " ".join(x for x in (vendor, product) if x) or "Disk %d" % n,
            "size": struct.unpack("<q", size)[0] if size else 0, "bus": BUS.get(bus, str(bus)),
            "removable": removable or bus in BUS}


def list_disks(max_card):
    out, skip = [], system_disks()
    for n in range(32):
        if n in skip:
            continue
        d = describe(n)
        if not d or not d["removable"] or not d["size"] or d["size"] > max_card:
            continue
        d["path"] = "\\\\.\\PhysicalDrive%d" % n
        d["mounts"] = [c + ":\\" for c in letters() if n in _disks_of_volume(c)]
        out.append(d)
    return out


def disk_of_letter(letter):
    disks = _disks_of_volume(letter)
    return disks[0] if disks else None


_held = []          # the locked volumes of the card being written, let go after it


def release(number=None):
    """The card's volumes let go and Windows asked to read its new partition table"""
    while _held:
        h = _held.pop()
        _ioctl(h, FSCTL_UNLOCK_VOLUME)
        _k.CloseHandle(h)
    if number is not None:
        h = _open("\\\\.\\PhysicalDrive%d" % number, GENERIC_READ | GENERIC_WRITE)
        if h:
            _ioctl(h, IOCTL_DISK_UPDATE_PROPERTIES)
            _k.CloseHandle(h)


def take(number):
    """Every volume of disk `number` locked and dismounted (Windows then lets the whole disk be
    written, and opens no window for it) until release(); its size in bytes"""
    import time
    release()
    for c in letters():
        if number not in _disks_of_volume(c):
            continue
        h = _open("\\\\.\\%s:" % c, GENERIC_READ | GENERIC_WRITE)
        if not h:
            raise OSError("the card's drive %s: cannot be opened (is a file on it open?)" % c)
        for _ in range(20):
            if _ioctl(h, FSCTL_LOCK_VOLUME) is not None:
                break
            time.sleep(0.25)
        else:
            _k.CloseHandle(h)
            release()
            raise OSError("the card's drive %s: is in use (close what has a file open on it)" % c)
        _ioctl(h, FSCTL_DISMOUNT_VOLUME)
        _held.append(h)
    d = describe(number)
    return d["size"] if d else 0
