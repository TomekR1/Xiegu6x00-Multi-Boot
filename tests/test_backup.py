import ntpath
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from x6100mb import backup  # noqa: E402


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_backup_and_restore(self):
        src, dst = os.path.join(self.d, "src"), os.path.join(self.d, "dst")
        os.makedirs(os.path.join(src, "backups"))
        os.makedirs(dst)
        for rel, text in (("x6100.db", "db"), ("backups/wifi.conf", "wifi"), ("._junk", "mac")):
            with open(os.path.join(src, *rel.split("/")), "w") as f:
                f.write(text)
        z = backup.save_zip(src, os.path.join(self.d, "b.zip"))
        with zipfile.ZipFile(z, "a") as zz:
            zz.writestr("../outside.txt", "x")          # never outside the card
        self.assertEqual(backup.restore_zip(z, dst), 2)
        with open(os.path.join(dst, "backups", "wifi.conf")) as f:
            self.assertEqual(f.read(), "wifi")
        self.assertFalse(os.path.exists(os.path.join(self.d, "outside.txt")))
        self.assertFalse(os.path.exists(os.path.join(dst, "._junk")))

    def test_copy_from_a_folder_and_what_it_holds(self):
        src, dst, other = (os.path.join(self.d, n) for n in ("src", "dst", "other"))
        os.makedirs(os.path.join(src, "backups"))
        os.makedirs(dst)
        os.makedirs(other)
        for rel in ("params.db", "backups/wifi.conf"):
            with open(os.path.join(src, *rel.split("/")), "w") as f:
                f.write(rel)
        with open(os.path.join(other, "holiday.jpg"), "w") as f:
            f.write("x")
        d = backup.describe(src)
        self.assertEqual((d["files"], d["data"]), (2, True))
        self.assertFalse(backup.describe(other)["data"])          # files, but not a radio's DATA
        z = backup.save_zip(src, os.path.join(self.d, "b.zip"))
        self.assertEqual((backup.describe(z)["files"], backup.describe(z)["data"]), (2, True))
        self.assertEqual(backup.restore_copy(src, dst), 2)         # loose files in a folder
        with open(os.path.join(dst, "backups", "wifi.conf")) as f:
            self.assertEqual(f.read(), "backups/wifi.conf")

    def test_copy_wrapped_in_a_folder(self):
        """A copy zipped as a folder, or unpacked into one: its files go on the card's DATA itself,
        not into a folder on it (there the radio finds no settings)"""
        self.assertEqual(backup.data_root(["params.db", "backups/wifi.conf"]), "")
        self.assertEqual(backup.data_root(["DATA-1/params.db", "DATA-1/backups/wifi.conf"]), "DATA-1/")
        self.assertEqual(backup.data_root(["a/DATA/params.db", "a/DATA/backups/x", "a/readme.txt"]), "a/DATA/")
        self.assertEqual(backup.data_root(["only/one.txt", "only/two.txt"]), "only/")
        self.assertEqual(backup.data_root(["backups/wifi.conf"]), "")
        self.assertEqual(backup.data_root(["one.txt", "dir/two.txt"]), "")
        z = os.path.join(self.d, "wrapped.zip")
        with zipfile.ZipFile(z, "w") as zz:
            zz.writestr("DATA-2026/params.db", "db")
            zz.writestr("DATA-2026/backups/wifi.conf", "wifi")
        folder = os.path.join(self.d, "unpacked")
        os.makedirs(os.path.join(folder, "DATA-2026", "backups"))
        for rel in ("params.db", "backups/wifi.conf"):
            with open(os.path.join(folder, "DATA-2026", *rel.split("/")), "w") as f:
                f.write(rel)
        for k, src in enumerate((z, folder)):
            self.assertEqual(backup.describe(src)["inner"], "DATA-2026")
            dst = os.path.join(self.d, "card%d" % k)
            os.makedirs(dst)
            self.assertEqual(backup.restore_copy(src, dst), 2)
            self.assertEqual(sorted(os.listdir(dst)), ["backups", "params.db"])
            lay = os.path.join(self.d, "new%d" % k)
            self.assertEqual(sorted(r for r, _p, _s in backup.from_copy(src, lay)), ["backups/wifi.conf", "params.db"])

    def test_windows_drive_root(self):
        """A drive's root already ends in a backslash: the check that a file stays on the card
        must still let the card's own files through"""
        root = ntpath.realpath("I:\\")
        target = ntpath.join("I:\\", "backups", "wifi.conf")
        self.assertEqual(ntpath.commonpath([root, target]), root)


if __name__ == "__main__":
    unittest.main()
