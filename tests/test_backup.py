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

    def test_windows_drive_root(self):
        """A drive's root already ends in a backslash: the check that a file stays on the card
        must still let the card's own files through"""
        root = ntpath.realpath("I:\\")
        target = ntpath.join("I:\\", "backups", "wifi.conf")
        self.assertEqual(ntpath.commonpath([root, target]), root)


if __name__ == "__main__":
    unittest.main()
