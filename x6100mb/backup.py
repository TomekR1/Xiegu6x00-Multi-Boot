"""The radio's settings across a new card: the DATA partition of the card in the reader.

The systems keep what the user set on the card's FAT32 partition labelled DATA (OpenX6X00: the
settings database, QSO log, app logs, and in backups/ the WiFi networks, SSH keys and Bluetooth
pairings it puts back itself on a new card). The computer mounts that partition by itself, so it is
read where the system mounted it, with no administrator rights: copied into a folder of the app's
before the card is erased, kept as a .zip on the computer, and put on the new card's DATA.
"""
import os
import re
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
        k = ctypes.windll.kernel32
        k.SetErrorMode(1)        # an empty card reader: no "insert a disk" box
        buf = ctypes.create_unicode_buffer(64)
        fs = ctypes.create_unicode_buffer(64)
        for letter in string.ascii_uppercase:
            root = letter + ":\\"
            try:
                # A card: a removable or fixed (some readers) FAT volume; not a hard disk's own
                # partition that happens to be called DATA (NTFS), nor a network or CD drive
                if k.GetDriveTypeW(root) not in (2, 3):
                    continue
                if k.GetVolumeInformationW(root, buf, 64, None, None, None, fs, 64):
                    if buf.value.upper() == "DATA" and fs.value.upper().startswith(("FAT", "EXFAT")):
                        found.append({"path": root, "label": buf.value})
            except Exception:
                pass
    elif sys.platform == "darwin":
        fat = None
        try:
            import subprocess
            out = subprocess.run(["mount"], capture_output=True, text=True, timeout=10).stdout
            fat = {m.group(1) for m in re.finditer(r" on (/Volumes/.+?) \((msdos|exfat)\b", out)}
        except Exception:
            pass
        for name in sorted(os.listdir("/Volumes")) if os.path.isdir("/Volumes") else []:
            path = os.path.join("/Volumes", name)
            if re.fullmatch(r"DATA( \d+)?", name, re.I) and (fat is None or path in fat):
                found.append({"path": path, "label": name})
    else:
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    dev, mnt, fstype = line.split()[:3]
                    mnt = mnt.replace("\\040", " ")
                    base = os.path.basename(mnt)
                    if fstype in ("vfat", "fat", "msdos", "exfat") and re.fullmatch(r"DATA\d*", base, re.I):
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



MARK_DIRS = ("backups", "logs", "log")


def _is_mark(parts):
    """Whether a path's last step says "a radio's DATA starts in my folder": its settings database
    or one of the folders the systems keep there"""
    return parts[-1].lower().endswith((".db", ".sqlite")) or parts[-1].lower() in MARK_DIRS


def data_root(names):
    """Where in a copy the DATA really starts: "" (at its top), or the folder it was wrapped in
    ("DATA-2026-11-14/", "my backup/DATA/"). A copy zipped as a folder, or unpacked into one, has
    everything one level down; put on the card like that the radio finds no settings (they would
    lie in a folder of the card, not on it). names: the copy's files, with /."""
    paths = [[x for x in n.split("/") if x] for n in names]
    paths = [p for p in paths if p]
    if not paths:
        return ""
    best = None
    for p in paths:                       # the shallowest folder holding a database or backups/
        for depth in range(len(p)):
            if _is_mark(p[:depth + 1]) and (depth < len(p) - 1 or p[depth].lower().endswith((".db", ".sqlite"))):
                if best is None or depth < len(best):
                    best = p[:depth]
                break
    if best is None:                      # no telling file: a single folder round everything goes
        best = []
        while all(len(p) > len(best) + 1 for p in paths) and len({p[len(best)] for p in paths}) == 1:
            best = paths[0][:len(best) + 1]
    return "/".join(best) + "/" if best else ""


def _zip_names(z):
    return [i.filename.replace("\\", "/") for i in z.infolist()
            if not i.is_dir() and not _skip(i.filename.replace("\\", "/").split("/")[-1])]


def _dir_root(src):
    """The folder inside src where its DATA starts (src itself when it is not wrapped)"""
    inner = data_root([rel for rel, _p, _s in files_in(src)])
    return os.path.join(src, *inner.strip("/").split("/")) if inner else src


def restore_zip(zip_path, dest):
    """A backup .zip unpacked onto the DATA partition dest (files of the same name replaced); how many.
    Only plain relative paths: nothing outside dest."""
    n = 0
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        inner = data_root(_zip_names(z))          # a copy zipped as a folder: from inside that folder
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/")
            if inner:
                if not rel.startswith(inner):
                    continue
                rel = rel[len(inner):]
            parts = [x for x in rel.split("/") if x not in ("", ".")]
            if not parts or ".." in parts or ":" in parts[0] or _skip(parts[-1]):
                continue
            target = os.path.realpath(os.path.join(dest, *parts))
            try:                    # "I:\\" + "\\" never matched: every file was skipped on Windows
                if os.path.commonpath([root, target]) != root:
                    continue
            except ValueError:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
    return n


def from_copy(src, dest):
    """The user's own copy of DATA (a backup .zip, or a folder holding the files) laid out in dest
    for a new card; [(relative, path, size)] as snapshot gives"""
    if os.path.isdir(src):
        return snapshot(_dir_root(src), dest)
    os.makedirs(dest, exist_ok=True)
    restore_zip(src, dest)
    for dirpath, _dirs, files in os.walk(dest):
        os.chmod(dirpath, 0o755)
        for f in files:
            os.chmod(os.path.join(dirpath, f), 0o644)
    return files_in(dest)


def restore_copy(src, dest):
    """A copy of DATA (a backup .zip, or a folder holding the files loose) onto the DATA partition
    dest; files of the same name are replaced; how many"""
    if not os.path.isdir(src):
        return restore_zip(src, dest)
    n = 0
    for rel, path, _size in files_in(_dir_root(src)):
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
        n += 1
    return n


def describe(src):
    """What a copy holds: {"files", "bytes", "data": whether it looks like a radio's DATA, "names",
    "inner": the folder inside the copy its DATA starts in ("" at its top)}.
    A radio's DATA has its settings in a database (params.db and the like), often a backups folder
    (WiFi, Bluetooth, SSH keys), logs: any of these says it is one."""
    if os.path.isdir(src):
        items = [(rel, size) for rel, _p, size in files_in(src)]
    else:
        with zipfile.ZipFile(src) as z:
            items = [(i.filename.replace("\\", "/"), i.file_size) for i in z.infolist()
                     if not i.is_dir() and not _skip(i.filename.replace("\\", "/").split("/")[-1])]
    inner = data_root([n for n, _s in items])     # wrapped in a folder: what counts is inside it
    items = [(n[len(inner):], sz) for n, sz in items if n.startswith(inner)]
    names = [n.lower() for n, _s in items]
    looks = any(n.endswith((".db", ".sqlite", ".adi", ".adif")) or n.split("/")[0] in ("backups", "logs", "log")
                or n.split("/")[-1] in ("params.db", "msg.db", "settings.json", "ft8.log", "wpa_supplicant.conf")
                for n in names)
    return {"files": len(items), "bytes": sum(sz for _n, sz in items), "data": looks,
            "names": [n for n, _s in items][:6], "inner": inner.rstrip("/")}
