"""Making a card, without a window: the plan, the old card's settings carried over, writing to the
card (here, or through the helper with administrator rights) or to an .img file. Used by the app's
window (gui.py) and by its accessible mode (access.py), so both write cards the same way.

A job runs in a thread of its own: nothing here touches a window. progress(phase, done, total, msg)
is called as it goes."""
import json
import os
import shutil
import tempfile
import threading
import time

from . import backup, devices
from .compose import compose, resolve_extras
from .i18n import t
from .writer import Progress, write_device, write_image_file


def card_request(req, progress=None):
    """A cardata request: here when the app may read the card itself, else through the helper with
    administrator rights"""
    from . import cardata
    if devices.is_admin() or devices.MAC or os.path.isfile(req["dev"]):
        return cardata.run(req, progress)
    tmp = tempfile.mkdtemp(prefix="x6100mb-")
    try:
        os.chmod(tmp, 0o777)
        rq, rs = os.path.join(tmp, "request.json"), os.path.join(tmp, "result.json")
        with open(rq, "w") as f:
            json.dump(req, f)
        os.chmod(rq, 0o666)
        proc = devices.run_elevated(["card-data", rq, rs])
        started = time.time()
        while not os.path.exists(rs):
            time.sleep(0.3)
            if proc is not None and proc.poll() is not None:
                time.sleep(0.5)
                if not os.path.exists(rs):
                    raise RuntimeError(t("Odczyt karty przerwany (odmowa uprawnień administratora?)"))
            if proc is None and time.time() - started > 600:
                raise RuntimeError(t("Odczyt karty przerwany (odmowa uprawnień administratora?)"))
        with open(rs) as f:
            out = json.load(f)
        if "error" in out:
            raise RuntimeError(out["error"])
        return out["ok"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ready(check):
    return t("Karta gotowa i sprawdzona. Wyjmij ją i włóż do radia.") if check else \
        t("Karta zapisana (bez sprawdzenia). Wyjmij ją i włóż do radia.")


class CardMaker:
    """settings: (timeout, data_mb, xiegu, data_mode, wait), taken where the user set them"""

    def __init__(self, progress):
        self.progress = progress
        self.skip = threading.Event()          # the read-back of the card left off
        self.skip_file = None                  # the elevated helper's flag for the same

    def skip_check(self):
        self.skip.set()
        if self.skip_file:
            try:
                open(self.skip_file, "w").close()
            except OSError:
                pass

    def plan(self, entries, default, settings, card_bytes=None, data_files=None):
        from .image import bundled_uboot_path
        if bundled_uboot_path() is None:
            # Without the menu's own U-Boot the card would take the first image's: no picture on the
            # screen and no F keys, only the default system after the countdown (issue #6)
            raise ValueError(t("Ta kopia aplikacji nie ma w sobie U-Boota menu (x6100mb/data/u-boot-x6100-menu.bin), "
                               "więc menu na radiu nie miałoby obrazu ani klawiszy F1–F5. Pobierz aplikację z "
                               "zakładki Releases na GitHubie (plik .zip dla swojego komputera) i uruchom ją stamtąd."))
        timeout, data_mb, xiegu, data_mode, wait = settings
        ents = resolve_extras([dict(e) for e in entries])
        return compose(ents, default=default, timeout_s=timeout, data_mb=data_mb, card_bytes=card_bytes,
                       xiegu=xiegu, data_mode=data_mode, wait=wait, data_files=data_files)

    def take_data(self, entries, tmp, card=None, keep=False, data_src=None, data_vol=None):
        """Before the card is erased: its settings copied aside and kept as .zip files on the computer.
        Returns (what compose takes as data_files, a line for the user about it), or (None, None).

        A card made here with a DATA per system: every system's DATA, each to the system of the same
        name (else of the same project) on the new card, wherever it now stands in the menu. Any other
        card: the DATA the computer shows, to the default system."""
        if not keep:
            return None, None
        if data_src:                              # the user's own copy goes before the old card's
            files = backup.from_copy(data_src, os.path.join(tmp, "DATA"))
            return files, t("Ustawienia: {n} plików wgranych na kartę; kopia: {zip}", n=len(files), zip=data_src)
        from . import cardata
        if card is not None:
            try:
                os.makedirs(backup.backups_dir(), exist_ok=True)
                areas = card_request({"op": "dump_all", "dev": card["path"], "dir": backup.backups_dir()},
                                     self.progress)["areas"]
            except Exception:
                backup.log_error("settings of each system")
                areas = []
            areas = [a for a in areas if a.get("zip") and a.get("files")]
            if areas:
                new = [(i, e["name"]) for i, e in enumerate(entries) if e["kind"] == "sd"]
                hit = cardata.match(areas, [n for _i, n in new])
                data, lines = {}, []
                for k, a in hit.items():
                    i, name = new[k]
                    data[i] = backup.from_copy(a["zip"], os.path.join(tmp, "DATA%d" % i))
                    lines.append("  %s  ←  %s (%d)" % (name, " + ".join(a["names"]), len(data[i])))
                left = [a for a in areas if all(a is not h for h in hit.values())]
                text = t("Ustawienia przeniesione (nowy system ← stara karta, liczba plików):") + "\n" + "\n".join(lines) \
                    if lines else t("Żaden system ze starej karty nie ma odpowiednika na nowej: ustawień nie przeniesiono.")
                if left:
                    text += "\n" + t("Bez odpowiednika na nowej karcie (kopia została na komputerze): {names}",
                                     names=", ".join(" + ".join(a["names"]) for a in left))
                text += "\n" + t("Kopie: {dir}", dir=backup.backups_dir())
                return (data or None), text
        if not (data_vol and os.path.isdir(data_vol)):
            return None, None
        files = backup.snapshot(data_vol, os.path.join(tmp, "DATA"), self.progress)
        zip_path = backup.save_zip(os.path.join(tmp, "DATA"))
        return files, t("Ustawienia: {n} plików wgranych na kartę; kopia: {zip}", n=len(files), zip=zip_path)

    def save_job(self, entries, default, plan, path, settings, card=None, keep=False, data_src=None, data_vol=None):
        tmp = tempfile.mkdtemp(prefix="x6100mb-data-")
        try:
            files, note = self.take_data(entries, tmp, card, keep, data_src, data_vol)
            if files is not None:
                plan = self.plan(entries, default, settings, data_files=files)
            write_image_file(plan, path, Progress(self.progress))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        msg = t("Zapisano {path} ({mb} MB). Można go wgrać balenaEtcherem.", path=path, mb=plan.size // 2**20)
        if note:
            msg += "\n\n" + note
        return ("msg", msg)

    def card_job(self, entries, default, plan, card, inproc, settings, check=True, keep=False,
                 data_src=None, data_vol=None):
        self.skip.clear()
        self.skip_file = None
        tmp = tempfile.mkdtemp(prefix="x6100mb-data-")
        os.chmod(tmp, 0o755)
        try:
            files, note = self.take_data(entries, tmp, card, keep, data_src, data_vol)
            if files is not None:
                plan = self.plan(entries, default, settings, card_bytes=card["size"], data_files=files)
            for dirpath, _dirs, names in os.walk(tmp):       # the writer may run with other rights
                os.chmod(dirpath, 0o755)
                for f in names:
                    os.chmod(os.path.join(dirpath, f), 0o644)
            result = (self._inproc if inproc else self._elevated)(plan, card["path"], check)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if note:
            result = (result[0], result[1] + "\n\n" + note)
        return result

    def _inproc(self, plan, dev, check=True):
        checked = write_device(plan, dev, Progress(self.progress), check=check, skip=self.skip.is_set)
        return ("msg", ready(checked))

    def _elevated(self, plan, dev, check=True):
        tmp = tempfile.mkdtemp(prefix="x6100mb-")
        try:
            plan_file = os.path.join(tmp, "plan.json")
            prog = os.path.join(tmp, "progress.json")
            plan.save(plan_file, os.path.join(tmp, "blobs"))
            # The elevated helper (another user on macOS/Linux) must read the plan and write progress
            for dirpath, _dirs, files in os.walk(tmp):
                os.chmod(dirpath, 0o777)
                for f in files:
                    os.chmod(os.path.join(dirpath, f), 0o666)
            self.skip_file = prog + ".skip"           # made when the read-back is to be skipped
            proc = devices.run_elevated(["write-plan", plan_file, dev, prog] + ([] if check else ["--no-verify"]))
            started = time.time()
            while True:
                time.sleep(0.3)
                st = None
                if os.path.exists(prog):
                    try:
                        with open(prog) as f:
                            st = json.load(f)
                    except (OSError, ValueError):
                        st = None
                if st:
                    if st["phase"] == "error":
                        raise RuntimeError(st["msg"])
                    if st["phase"] == "done":
                        return ("msg", ready(st.get("msg") != "unchecked"))
                    self.progress(st["phase"], st["done"], st["total"], st.get("msg", ""))
                if proc is not None and proc.poll() is not None and not (st and st["phase"] == "done"):
                    time.sleep(0.5)
                    if os.path.exists(prog):
                        with open(prog) as f:
                            st = json.load(f)
                        if st["phase"] == "done":
                            return ("msg", ready(st.get("msg") != "unchecked"))
                        if st["phase"] == "error":
                            raise RuntimeError(st["msg"])
                    raise RuntimeError(t("Zapis przerwany (odmowa uprawnień administratora?)"))
                if proc is None and st is None and time.time() - started > 120:
                    raise RuntimeError(t("Program zapisujący nie wystartował (odmowa uprawnień?)"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
