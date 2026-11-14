"""Removable cards on Windows, macOS and Linux: listing, unmounting, raw access, admin rights.

Only removable / USB / SD disks are offered; the system disk never is, nor anything over
MAX_CARD bytes (a USB hard disk is no SD card).
"""
import json
import os
from .i18n import t
import plistlib
import re
import subprocess
import sys

MAX_CARD = 256 * 10**9
WIN = sys.platform.startswith("win")
MAC = sys.platform == "darwin"


class DeviceError(Exception):
    pass


def _run(cmd, **kw):
    kw.setdefault("capture_output", True)
    if "input" not in kw:
        kw.setdefault("stdin", subprocess.DEVNULL)      # a windowed app has no console to inherit
    if WIN:
        kw.setdefault("creationflags", 0x08000000)       # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


# --------------------------------------------------------------------------------------------
# Listing: [{"path", "name", "size", "bus", "mounts"}]
# --------------------------------------------------------------------------------------------
def list_cards():
    if WIN:
        return _list_windows()
    if MAC:
        return _list_mac()
    return _list_linux()


def _list_linux():
    r = _run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,RM,HOTPLUG,TRAN,MODEL,VENDOR,TYPE,MOUNTPOINT,RO"])
    if r.returncode:
        raise DeviceError("lsblk failed: " + r.stderr.decode(errors="replace"))
    out = []
    for d in json.loads(r.stdout).get("blockdevices", []):
        if d.get("type") != "disk" or d.get("ro") in (True, "1"):
            continue
        mounts = []

        def walk(n):
            if n.get("mountpoint"):
                mounts.append(n["mountpoint"])
            for c in n.get("children", []) or []:
                walk(c)

        walk(d)
        if any(m in ("/", "/boot", "/boot/efi", "/usr", "/home", "[SWAP]") for m in mounts):
            continue
        removable = d.get("rm") in (True, "1") or d.get("hotplug") in (True, "1") or d.get("tran") in ("usb", "mmc")
        size = int(d.get("size") or 0)
        if not removable or not size or size > MAX_CARD:
            continue
        name = " ".join(x.strip() for x in (d.get("vendor") or "", d.get("model") or "") if x and x.strip())
        out.append({"path": d.get("path") or "/dev/" + d["name"], "name": name or d["name"], "size": size,
                    "bus": d.get("tran") or "", "mounts": mounts})
    return out


def _list_mac():
    # Every physical disk, not only the external ones: a Mac's built-in card reader is "internal"
    r = _run(["diskutil", "list", "-plist", "physical"])
    if r.returncode:
        raise DeviceError("diskutil list failed")
    out = []
    for disk in plistlib.loads(r.stdout).get("WholeDisks", []):
        i = _run(["diskutil", "info", "-plist", disk])
        if i.returncode:
            continue
        info = plistlib.loads(i.stdout)
        if info.get("VirtualOrPhysical") == "Virtual":
            continue
        card = str(info.get("BusProtocol") or "").lower() in ("secure digital", "sd", "mmc") or \
            info.get("RemovableMedia") or info.get("Removable") or info.get("Ejectable")
        if info.get("Internal") and not card:          # the Mac's own disk
            continue
        size = int(info.get("TotalSize") or info.get("Size") or 0)
        if not size or size > MAX_CARD:
            continue
        out.append({"path": "/dev/" + disk, "name": info.get("MediaName") or disk, "size": size,
                    "bus": info.get("BusProtocol") or "", "mounts": []})
    return out


def _ps(script):
    r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    if r.returncode:
        raise DeviceError("PowerShell: " + r.stderr.decode(errors="replace"))
    t = r.stdout.decode(errors="replace").strip()
    return json.loads(t) if t else []


def _list_windows():
    disks = _ps("Get-Disk | Select-Object Number,FriendlyName,Size,BusType,IsBoot,IsSystem | ConvertTo-Json")
    if isinstance(disks, dict):
        disks = [disks]
    out = []
    for d in disks:
        bus = str(d.get("BusType"))
        if d.get("IsBoot") or d.get("IsSystem"):
            continue
        if bus not in ("USB", "SD", "MMC", "7", "12", "13"):
            continue
        size = int(d.get("Size") or 0)
        if not size or size > MAX_CARD:
            continue
        out.append({"path": r"\\.\PhysicalDrive%d" % d["Number"], "name": d.get("FriendlyName") or "",
                    "size": size, "bus": bus, "mounts": [], "number": d["Number"]})
    return out


def device_of(mount):
    """The whole card a mounted volume lies on (/dev/disk4, /dev/sdb, PhysicalDrive2), or
    None: for a card the list above does not show but whose DATA the computer has mounted"""
    try:
        if WIN:
            n = _ps("(Get-Partition -DriveLetter '%s').DiskNumber" % mount[0])
            return r"\\.\PhysicalDrive%d" % int(n)
        if MAC:
            info = plistlib.loads(_run(["diskutil", "info", "-plist", mount]).stdout)
            whole = info.get("ParentWholeDisk")
            return "/dev/" + whole if whole else None
        r = _run(["findmnt", "-n", "-o", "SOURCE", mount])
        part = r.stdout.decode().strip()
        if not part:
            return None
        whole = _run(["lsblk", "-n", "-o", "PKNAME", part]).stdout.decode().strip().split("\n")[0]
        return "/dev/" + whole if whole else None
    except Exception:
        return None


def is_listed(path):
    return any(c["path"] == path for c in list_cards())


# --------------------------------------------------------------------------------------------
# Before and after writing
# --------------------------------------------------------------------------------------------
def prepare_for_write(dev):
    """Unmounts what is on dev (Windows: removes its partitions) and gives its size in bytes"""
    if not is_listed(dev):
        raise DeviceError(f"{dev} is not a removable card (or not plugged in)")
    if WIN:
        n = int(re.search(r"(\d+)$", dev).group(1))
        script = f"select disk {n}\nattributes disk clear readonly\nclean\nrescan\n"
        r = _run(["diskpart"], input=script.encode())
        if r.returncode:
            raise DeviceError("diskpart could not clear the card: " + r.stdout.decode(errors="replace")[-400:])
        size = int(_ps(f"(Get-Disk -Number {n}).Size"))
        return size
    if MAC:
        r = _run(["diskutil", "unmountDisk", "force", dev])
        if r.returncode:
            raise DeviceError("could not unmount the card: " + r.stderr.decode(errors="replace"))
        info = plistlib.loads(_run(["diskutil", "info", "-plist", dev]).stdout)
        return int(info.get("TotalSize") or info.get("Size"))
    for c in list_cards():
        if c["path"] == dev:
            for m in c["mounts"]:
                r = _run(["umount", m])
                if r.returncode:
                    raise DeviceError(f"could not unmount {m}: " + r.stderr.decode(errors="replace"))
    fd = os.open(dev, os.O_RDONLY)
    try:
        return os.lseek(fd, 0, os.SEEK_END)
    finally:
        os.close(fd)


def unmount(dev):
    """What the computer mounted of dev let go, the card itself left as it is (before writing one
    of its areas). Windows: nothing; it lets the areas outside the partition table be written."""
    if WIN:
        return
    if MAC:
        r = _run(["diskutil", "unmountDisk", "force", dev])
        if r.returncode:
            raise DeviceError("could not unmount the card: " + r.stderr.decode(errors="replace"))
        return
    for c in list_cards():
        if c["path"] == dev:
            for m in c["mounts"]:
                r = _run(["umount", m])
                if r.returncode:
                    raise DeviceError(f"could not unmount {m}: " + r.stderr.decode(errors="replace"))


def after_write(dev):
    if MAC:
        _run(["diskutil", "eject", dev])
    elif not WIN and os.path.exists(dev) and not os.path.isfile(dev):
        _run(["blockdev", "--rereadpt", dev])


# --------------------------------------------------------------------------------------------
# Raw access (whole 512-byte sectors only: Windows needs that)
# --------------------------------------------------------------------------------------------
def _raw(dev):
    if MAC and re.match(r"^/dev/disk\d+$", dev):
        return dev.replace("/dev/disk", "/dev/rdisk")
    return dev


def _authopen(path, flags):
    """macOS: the raw disk opened by /usr/libexec/authopen, which asks for the password itself and
    hands the open descriptor back over a socket. Even root gets 'Operation not permitted' opening
    /dev/rdiskN on recent macOS; authopen is the way the system offers (balenaEtcher's too)."""
    import socket
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        p = subprocess.Popen(["/usr/libexec/authopen", "-stdoutpipe", "-o", str(flags), path],
                             stdout=child, stderr=subprocess.PIPE)
        child.close()
        fds = []
        try:
            _msg, fds, _f, _a = socket.recv_fds(parent, 1024, 1)
        except OSError:
            pass
        err = p.communicate(timeout=300)[1].decode(errors="replace").strip()
    finally:
        parent.close()
    if not fds:
        raise DeviceError(t("macOS nie dał dostępu do karty") + (f" ({err})" if err else
                          t(" (odmowa hasła administratora?)")))
    fd = fds[0]
    try:
        import fcntl
        fcntl.fcntl(fd, 48, 1)     # F_NOCACHE: the read-back comes from the card, not the cache
    except OSError:
        pass
    return fd


def open_for_write(dev):
    """Read and write: the same descriptor serves the read-back (on macOS one password, not two)"""
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    if MAC and not os.path.isfile(dev):
        return _authopen(_raw(dev), os.O_RDWR)
    return os.open(_raw(dev), flags)


def drop_cache(fd):
    """Before a read-back: what Linux still caches of the card goes"""
    if hasattr(os, "posix_fadvise"):
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def open_for_read(dev):
    if MAC and not os.path.isfile(dev):
        return _authopen(_raw(dev), os.O_RDONLY)
    fd = os.open(_raw(dev), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    if hasattr(os, "posix_fadvise"):
        try:                       # read from the card, not from what Linux still caches of it
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass
    return fd


def pwrite(fd, data, pos):
    if hasattr(os, "pwrite"):
        n = os.pwrite(fd, data, pos)
    else:
        os.lseek(fd, pos, os.SEEK_SET)
        n = os.write(fd, data)
    if n != len(data):
        raise DeviceError(f"short write at {pos}")


def pread(fd, n, pos):
    if hasattr(os, "pread"):
        out = bytearray()
        while len(out) < n:
            d = os.pread(fd, n - len(out), pos + len(out))
            if not d:
                break
            out += d
        return bytes(out)
    os.lseek(fd, pos, os.SEEK_SET)
    return os.read(fd, n)


def sync(fd):
    if WIN:
        # os.fsync on a whole disk (\\.\PhysicalDriveN) fails as "[Errno 9] Bad file descriptor" when
        # Windows' flush of it fails; the disk is opened unbuffered anyway and the read-back checks it
        try:
            import ctypes
            import msvcrt
            ctypes.windll.kernel32.FlushFileBuffers(msvcrt.get_osfhandle(fd))
        except Exception:
            pass
        return
    os.fsync(fd)
    if not WIN and not MAC and hasattr(os, "posix_fadvise"):
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def close(fd):
    os.close(fd)


# --------------------------------------------------------------------------------------------
# Admin rights: the GUI stays a normal user, the writer runs elevated
# --------------------------------------------------------------------------------------------
def is_admin():
    if WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def helper_command(args):
    """The command that runs `x6100mb <args>`, frozen (PyInstaller) or from the sources"""
    if getattr(sys, "frozen", False):
        return [sys.executable] + args
    return [sys.executable, "-m", "x6100mb"] + args


def _src_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_elevated(args):
    """Starts the helper with admin rights; returns a Popen (or None on Windows, where it is detached)"""
    cmd = helper_command(args)
    if is_admin():
        null = subprocess.DEVNULL
        return subprocess.Popen(cmd, cwd=_src_dir(), stdin=null, stdout=null, stderr=null)
    if WIN:
        import ctypes
        params = subprocess.list2cmdline(cmd[1:])
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, _src_dir(), 0)
        if r <= 32:
            raise DeviceError("administrator rights were refused")
        return None
    if MAC:
        import shlex
        sh = "cd %s && %s" % (shlex.quote(_src_dir()), " ".join(shlex.quote(c) for c in cmd))
        osa = 'do shell script "%s" with administrator privileges' % sh.replace("\\", "\\\\").replace('"', '\\"')
        return subprocess.Popen(["osascript", "-e", osa], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for tool in ("pkexec",):
        if subprocess.run(["which", tool], capture_output=True).returncode == 0:
            return subprocess.Popen([tool, "env", "PYTHONPATH=" + _src_dir()] + cmd, cwd=_src_dir())
    raise DeviceError("no pkexec: start this program with sudo to write cards")


# --------------------------------------------------------------------------------------------
# Windows: no windows popping up while the card is written
# --------------------------------------------------------------------------------------------
class WindowsQuiet:
    """While the card is written and a while after: AutoPlay off (as the user had it afterwards), and
    the windows Windows itself opens for the card's new partitions closed: an Explorer window of a
    drive (DATA, BOOT: empty) and its "format the disk" question for the Linux partitions. Only windows
    that appear meanwhile are touched; anything open before is left alone. Elsewhere: nothing."""

    AFTER = 20          # seconds of watching once the writing is over

    def __init__(self):
        self.on = WIN
        self.stop_at = None

    def __enter__(self):
        if not self.on:
            return self
        import atexit
        import threading
        self._autoplay(True)
        atexit.register(self._autoplay, False)     # the app closed before the watching ended
        self.before = set(self._windows())
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        if self.on:
            import time
            self.stop_at = time.time() + self.AFTER
        return False

    # --- AutoPlay (Settings > Bluetooth & devices > AutoPlay), the user's own value put back
    def _autoplay(self, quiet):
        try:
            import winreg
            path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
                if quiet:
                    try:
                        self.saved = winreg.QueryValueEx(k, "DisableAutoplay")[0]
                    except OSError:
                        self.saved = None
                    winreg.SetValueEx(k, "DisableAutoplay", 0, winreg.REG_DWORD, 1)
                elif self.saved is None:
                    winreg.DeleteValue(k, "DisableAutoplay")
                else:
                    winreg.SetValueEx(k, "DisableAutoplay", 0, winreg.REG_DWORD, self.saved)
        except Exception:
            pass

    def _windows(self):
        """[(hwnd, class, title)] of the visible top-level windows"""
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        out = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def each(hwnd, _):
            if u.IsWindowVisible(hwnd):
                cls = ctypes.create_unicode_buffer(64)
                u.GetClassNameW(hwnd, cls, 64)
                n = u.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, title, n + 1)
                out.append((hwnd, cls.value, title.value))
            return True
        try:
            u.EnumWindows(each, 0)
        except Exception:
            pass
        return out

    def _watch(self):
        import ctypes
        import time
        WM_CLOSE = 0x0010
        drive = re.compile(r"\(([A-Z]):\)")             # "DATA (F:)", "DATA (F:) – Eksplorator plików"
        try:
            while self.stop_at is None or time.time() < self.stop_at:
                for w in self._windows():
                    if w in self.before:
                        continue
                    hwnd, cls, title = w
                    m = drive.search(title) if cls == "CabinetWClass" else None
                    # a card's drive only (removable), not a window of C: the user opens meanwhile
                    explorer_drive = bool(m) and ctypes.windll.kernel32.GetDriveTypeW(m.group(1) + ":\\") == 2
                    format_question = cls == "#32770" and title == "Microsoft Windows"
                    if explorer_drive or format_question:
                        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    self.before.add(w)
                time.sleep(0.3)
        except Exception:
            pass
        finally:
            self._autoplay(False)
