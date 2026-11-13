"""Writing a Plan to an image file or straight to a card, then reading it back to check it."""
import hashlib
import json
import os
import sys
import time

from . import devices


class WriteError(Exception):
    pass


class Progress:
    """Calls back (phase, done, total); optionally mirrors to a JSON file for another process"""

    def __init__(self, callback=None, file=None):
        self.cb = callback
        self.file = file
        self.last = 0

    def __call__(self, phase, done, total, msg=""):
        if self.cb:
            self.cb(phase, done, total, msg)
        if self.file and (time.time() - self.last > 0.3 or done >= total or phase in ("done", "error")):
            self.last = time.time()
            tmp = self.file + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"phase": phase, "done": done, "total": total, "msg": msg}, f)
            os.replace(tmp, self.file)


def write_image_file(plan, path, progress=None):
    """A sparse image file: only the pieces are written"""
    progress = progress or Progress()
    total = plan.written_bytes()
    done = 0
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.truncate(plan.size)
        for off, piece in plan.pieces:
            f.seek(off)
            for c in piece.chunks():
                f.write(c)
                done += len(c)
                progress("write", done, total)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:             # Windows: a failed flush reads as "Bad file descriptor"; verified below
            pass
    os.replace(tmp, path)
    verify(plan, path, progress)
    progress("done", total, total)


def write_device(plan, dev, progress=None, allow_file=False):
    """Every piece onto the card dev, synced, then read back"""
    progress = progress or Progress()
    total = plan.written_bytes()
    progress("prepare", 0, total, f"preparing {dev}")
    if allow_file and os.path.isfile(dev):
        size = plan.size
    else:
        size = devices.prepare_for_write(dev)
    if plan.size > size:
        raise WriteError(f"the image ({plan.size // 2**20} MB) is bigger than the card ({size // 2**20} MB)")
    done = 0
    first = None        # the partition table: written last, see below
    fd = devices.open_for_write(dev)
    try:
        for off, piece in plan.pieces:
            pos = off
            for c in piece.chunks():
                if pos == 0:
                    # As soon as a partition table is on the card Windows mounts its partitions and
                    # refuses writes inside them; so sector 0 goes last, after everything else
                    first = c[:512]
                    if len(c) > 512:
                        devices.pwrite(fd, c[512:], 512)
                else:
                    devices.pwrite(fd, c, pos)
                pos += len(c)
                done += len(c)
                progress("write", done, total)
        if first is not None:
            devices.pwrite(fd, first, 0)
        progress("sync", done, total, "flushing the card's cache")
        devices.sync(fd)
        devices.drop_cache(fd)
        verify(plan, dev, progress, fd=fd)
    finally:
        devices.close(fd)
    devices.after_write(dev)
    progress("done", total, total)


def verify(plan, target, progress=None, fd=None):
    """Reads every piece back; fd: an open descriptor to read through (kept open)"""
    progress = progress or Progress()
    total = plan.written_bytes()
    done = 0
    own = fd is None
    if own:
        fd = devices.open_for_read(target)
    try:
        for off, piece in plan.pieces:
            pos = off
            for c in piece.chunks():
                got = devices.pread(fd, len(c), pos)
                if got != c:
                    raise WriteError(f"read-back differs at byte {pos}: the card did not keep what was written "
                                     "(a fake or worn card?)")
                pos += len(c)
                done += len(c)
                progress("verify", done, total)
    finally:
        if own:
            devices.close(fd)


def main_write_plan(argv):
    """python -m x6100mb write-plan PLAN.json DEVICE PROGRESS.json  (the elevated helper)"""
    from .extents import Plan
    plan_path, dev, prog_file = argv[:3]
    allow_file = "--allow-file" in argv
    progress = Progress(file=prog_file)
    try:
        plan = Plan.load(plan_path)
        write_device(plan, dev, progress, allow_file=allow_file)
        return 0
    except Exception as e:      # reported to the GUI through the progress file
        from .backup import log_error
        log_error("write-plan " + dev)
        progress("error", 0, 1, str(e))
        print(f"error: {e}", file=sys.stderr)
        return 1
