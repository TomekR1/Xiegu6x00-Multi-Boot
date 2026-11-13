"""The radio's settings across a new card: the DATA partition of the card in the reader.

The systems keep what the user set on the card's FAT32 partition labelled DATA (OpenX6X00: the
settings database, QSO log, app logs, and in backups/ the WiFi networks, SSH keys and Bluetooth
pairings it puts back itself on a new card). The computer mounts that partition by itself, so it is
read where the system mounted it, with no administrator rights: copied into a folder of the app's
before the card is erased, kept as a .zip on the computer, and put on the new card's DATA.
"""
import os
import shutil
import string
import sys
import time
import zipfile

# What the computer itself leaves on a FAT stick, not the radio's
SKIP = {"system volume information", "$recycle.bin", ".trashes", ".spotlight-v100", ".fseventsd",
        ".temporaryitems", "lost+found", ".ds_store"}


def _skip(name):
    n = name.lower()
    return n in SKIP or n.startswith("._")


def find_data_volumes():
    """[{"path", "label"}]: the mounted volumes labelled DATA (one card in the reader: one)"""
    found = []
    if sys.platform.startswith("win"):
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(1)        # an empty card reader: no "insert a disk" box
        buf = ctypes.create_unicode_buffer(64)
        for letter in string.ascii_uppercase:
            root = letter + ":\\"
            try:
                if ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 64, None, None, None, None, 0):
                    if buf.value.upper() == "DATA":
                        found.append({"path": root, "label": buf.value})
            except Exception:
                pass
    elif sys.platform == "darwin":
        for name in sorted(os.listdir("/Volumes")) if os.path.isdir("/Volumes") else []:
            if name.upper() == "DATA" or name.upper().startswith("DATA "):
                found.append({"path": os.path.join("/Volumes", name), "label": name})
    else:
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    dev, mnt, fstype = line.split()[:3]
                    mnt = mnt.replace("\\040", " ")
                    base = os.path.basename(mnt)
                    if fstype in ("vfat", "fat", "msdos", "exfat") and \
                            (base.upper() == "DATA" or base.upper().startswith("DATA")):
                        found.append({"path": mnt, "label": base})
        except OSError:
            pass
    return [v for v in found if os.path.isdir(v["path"])]


def files_in(src):
    """[(relative path with /, absolute path, size)] of what the radio keeps there"""
    out = []
    for dirpath, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not _skip(d))
        for name in sorted(files):
            if _skip(name):
                continue
            p = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            out.append((os.path.relpath(p, src).replace(os.sep, "/"), p, size))
    return out


def backups_dir():
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    return os.path.join(docs if os.path.isdir(docs) else home, "Xiegu Multi Patcher", "DATA")


def log_error(where):
    """The current exception's traceback appended to log.txt next to the backups; its path (or None)"""
    import traceback
    try:
        path = os.path.join(os.path.dirname(backups_dir()), "log.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + where + " (" + sys.platform + ")\n")
            f.write(traceback.format_exc() + "\n")
        return path
    except Exception:
        return None


def save_zip(src, zip_path=None):
    """The volume's files as a .zip on the computer; its path"""
    if zip_path is None:
        os.makedirs(backups_dir(), exist_ok=True)
        zip_path = os.path.join(backups_dir(), time.strftime("DATA-%Y-%m-%d_%H-%M-%S.zip"))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, path, _size in files_in(src):
            z.write(path, rel)
    return zip_path


def snapshot(src, dest):
    """The volume's files copied into dest (the card is erased next); [(relative, path, size)].
    Readable by everyone: on Linux and Windows the card is written by a helper with other rights."""
    copied = []
    for rel, path, size in files_in(src):
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
        copied.append((rel, target, size))
    for dirpath, dirs, files in os.walk(dest):
        os.chmod(dirpath, 0o755)
        for f in files:
            os.chmod(os.path.join(dirpath, f), 0o644)
    return copied



def restore_zip(zip_path, dest):
    """A backup .zip unpacked onto the DATA partition dest (files of the same name replaced); how many.
    Only plain relative paths: nothing outside dest."""
    n = 0
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/")
            target = os.path.realpath(os.path.join(dest, *rel.split("/")))
            if not target.startswith(root + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
    return n
