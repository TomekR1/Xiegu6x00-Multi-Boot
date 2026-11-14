"""Builds a small fake X6100 card image, composes a multi-boot card from it, reads that back.

    python -m unittest discover -s tests
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from x6100mb.compose import compose                       # noqa: E402
from x6100mb.extents import Plan                          # noqa: E402
from x6100mb.fat import Fat32Builder, FatReader           # noqa: E402
from x6100mb.image import (SECTOR, SourceSystem, make_mbr, make_script_image,  # noqa: E402
                           parse_script_image, read_mbr)
from x6100mb.writer import write_image_file               # noqa: E402

MIB = 1 << 20
SCRIPT = """echo "------------ X6100 boot script ------------"
setenv bootargs console=ttyS0,115200 root=/dev/mmcblk0p2 rootwait panic=10
fatload mmc 0:1 0x46000000 zImage
fatload mmc 0:1 0x49000000 ${fdtfile}
bootz 0x46000000 - 0x49000000
"""


def fake_card(path, kernel=b"K" * 3000, root_mb=8):
    boot_lba, boot_size = 2048, 40 * MIB
    root_lba = boot_lba + boot_size // SECTOR
    size = root_lba * SECTOR + root_mb * MIB
    plan = Plan(size)
    from x6100mb.extents import Data
    plan.add(0, Data(make_mbr([(0x0C, boot_lba, boot_size // SECTOR, True),
                               (0x83, root_lba, root_mb * MIB // SECTOR, False), None, None], 0x1234)))
    spl = bytearray(MIB - 8192)
    spl[4:12] = b"eGON.BT0"
    spl[100:130] = b"U-Boot SPL 2026.07 (test)\x00\x00\x00\x00\x00"
    plan.add(8192, Data(spl))
    fat = Fat32Builder(boot_size, boot_lba, label="BOOT")
    fat.add_file("zImage".upper(), kernel)
    fat.add_file("x6100.dtb".upper(), b"D" * 700)
    fat.add_file("boot.scr".upper(), make_script_image(SCRIPT))
    for off, p in fat.extents():
        plan.add(boot_lba * SECTOR + off, p)
    sb = bytearray(MIB)
    sb[1024 + 56:1024 + 58] = b"\x53\xef"
    sb[4096:4100] = b"ROOT"
    plan.add(root_lba * SECTOR, Data(sb))
    plan.check()
    write_image_file(plan, path)


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_script_roundtrip(self):
        self.assertEqual(parse_script_image(make_script_image(SCRIPT)).strip(), SCRIPT.strip())

    def test_two_systems_and_xiegu(self):
        a = os.path.join(self.tmp, "a.img")
        b = os.path.join(self.tmp, "b.img")
        fake_card(a, kernel=b"A" * 5000)
        fake_card(b, kernel=b"B" * 7000)
        sa, sb = SourceSystem(a, a), SourceSystem(b, b)
        self.assertEqual(sa.root_number, 2)
        self.assertEqual(sa.fdt_file.lower(), "x6100.dtb")    # ${fdtfile} missing: the only .dtb
        plan = compose([{"kind": "sd", "name": "A", "sys": sa}, {"kind": "sd", "name": "B", "sys": sb},
                        {"kind": "xiegu", "name": "Xiegu"}], default=1, timeout_s=3, data_mb=64)
        out = os.path.join(self.tmp, "out.img")
        write_image_file(plan, out)
        with open(out, "rb") as f:
            parts = {p[0]: p for p in read_mbr(f)}
            self.assertEqual(sorted(parts), [1, 2, 3, 5])
            boot = FatReader(f, parts[1][2] * SECTOR)
            self.assertEqual(boot.read_file("SYS1/ZIMAGE"), b"A" * 5000)
            self.assertEqual(boot.read_file("SYS2/ZIMAGE"), b"B" * 7000)
            script = parse_script_image(boot.read_file("boot.scr"))
            self.assertIn("root=/dev/mmcblk0p2", script)
            self.assertIn("root=/dev/mmcblk0p5", script)
            self.assertIn("setenv bm_default 2", script)
            self.assertIn("setenv bm_secs 3", script)
            self.assertIn("itest ${i} -ge ${bm_ticks}", script)
            data = FatReader(f, parts[3][2] * SECTOR)
            self.assertEqual(data.listdir(), [])
            f.seek(parts[3][2] * SECTOR + 71)
            self.assertEqual(f.read(11), b"DATA       ")
            f.seek(parts[5][2] * SECTOR + 4096)
            self.assertEqual(f.read(4), b"ROOT")
            f.seek(8192 + 4)
            self.assertEqual(f.read(8), b"eGON.BT0")


    def test_separate_data(self):
        a = os.path.join(self.tmp, "a.img")
        b = os.path.join(self.tmp, "b.img")
        fake_card(a)
        fake_card(b)
        sa, sb = SourceSystem(a, a), SourceSystem(b, b)
        plan = compose([{"kind": "sd", "name": "A", "sys": sa}, {"kind": "sd", "name": "B", "sys": sb}],
                       default=1, data_mb=40, data_mode="separate")
        out = os.path.join(self.tmp, "sep.img")
        write_image_file(plan, out)
        self.assertEqual(plan.info["data_partitions"], 2)
        with open(out, "rb") as f:
            parts = {p[0]: p for p in read_mbr(f)}
            boot = FatReader(f, parts[1][2] * SECTOR)
            m1 = boot.read_file("SYS1/MBR.BIN")
            m2 = boot.read_file("SYS2/MBR.BIN")
            p3 = lambda m: struct.unpack_from("<I", m, 446 + 32 + 8)[0]
            self.assertNotEqual(p3(m1), p3(m2))
            self.assertEqual(parts[3][2], p3(m2))          # the card starts on the default's DATA (B)
            for m in (m1, m2):
                f.seek(p3(m) * SECTOR + 71)
                self.assertEqual(f.read(11), b"DATA       ")
            script = parse_script_image(boot.read_file("boot.scr"))
            self.assertIn("SYS1/MBR.BIN", script)
            self.assertIn("mmc write 0x45100000 0 1", script)


    def test_each_systems_data_saved_and_restored(self):
        """One DATA per system: each found on the card, written from a .zip and read back, the other
        left as it was (the app's "DATA of each system")"""
        import zipfile
        from x6100mb import cardata
        a, b = os.path.join(self.tmp, "a.img"), os.path.join(self.tmp, "b.img")
        fake_card(a)
        fake_card(b)
        out = os.path.join(self.tmp, "out.img")
        plan = compose([{"kind": "sd", "name": "One", "sys": SourceSystem(a, a)},
                        {"kind": "sd", "name": "Two", "sys": SourceSystem(b, b)}],
                       default=1, data_mb=40, data_mode="separate")
        write_image_file(plan, out)
        areas = cardata.run({"op": "scan", "dev": out})["areas"]
        self.assertEqual([x["names"] for x in areas], [["One"], ["Two"]])
        self.assertEqual([x["active"] for x in areas], [False, True])
        for k, area in enumerate(areas):
            z = os.path.join(self.tmp, "in%d.zip" % k)
            with zipfile.ZipFile(z, "w") as zz:
                zz.writestr("settings.db", b"system %d" % k)
                zz.writestr("backups/a long file name.conf", b"x" * 5000)
            self.assertEqual(cardata.run({"op": "restore", "dev": out, "area": area, "zip": z})["files"], 2)
        for k, area in enumerate(areas):
            z = os.path.join(self.tmp, "out%d.zip" % k)
            self.assertEqual(cardata.run({"op": "dump", "dev": out, "area": area, "zip": z})["files"], 2)
            with zipfile.ZipFile(z) as zz:
                self.assertEqual(zz.read("settings.db"), b"system %d" % k)
                self.assertEqual(len(zz.read("backups/a long file name.conf")), 5000)

    def test_settings_follow_their_system_to_a_new_card(self):
        """A new card with the systems in another order and newer versions: each system's settings
        from the old card land in the same system's DATA, not in whatever stands at its old place"""
        import zipfile
        from x6100mb import backup, cardata
        a, b = os.path.join(self.tmp, "a.img"), os.path.join(self.tmp, "b.img")
        fake_card(a)
        fake_card(b)
        old = os.path.join(self.tmp, "old.img")
        write_image_file(compose([{"kind": "sd", "name": "OpenX6X00 v0.3.11", "sys": SourceSystem(a, a)},
                                  {"kind": "sd", "name": "R1CBU v0.29", "sys": SourceSystem(b, b)}],
                                 data_mb=40, data_mode="separate"), old)
        areas = cardata.run({"op": "scan", "dev": old})["areas"]
        self.assertEqual([x["ids"] for x in areas], [["openx6x00"], ["r1cbu"]])
        for area in areas:
            z = os.path.join(self.tmp, "in.zip")
            with zipfile.ZipFile(z, "w") as zz:
                zz.writestr("params.db", ("settings of " + area["ids"][0]).encode())
            cardata.run({"op": "restore", "dev": old, "area": area, "zip": z})
        # every system's DATA off the old card, each into a .zip that says whose it is
        copies = os.path.join(self.tmp, "copies")
        dumped = cardata.run({"op": "dump_all", "dev": old, "dir": copies})["areas"]
        self.assertEqual([x["files"] for x in dumped], [1, 1])
        self.assertEqual(cardata.copy_of(dumped[1]["zip"])["ids"], ["r1cbu"])
        self.assertEqual(backup.describe(dumped[0]["zip"])["whose"]["names"], ["OpenX6X00 v0.3.11"])
        # the new card: the other way round, newer versions, a third system that was not there
        names = ["R1CBU v0.30", "CX8ANM v1.1.5", "OpenX6X00 v0.3.12"]
        hit = cardata.match(dumped, names)
        self.assertEqual({k: v["ids"][0] for k, v in hit.items()}, {0: "r1cbu", 2: "openx6x00"})
        data = {i: backup.from_copy(ar["zip"], os.path.join(self.tmp, "lay%d" % i)) for i, ar in hit.items()}
        c = os.path.join(self.tmp, "c.img")
        fake_card(c)
        new = os.path.join(self.tmp, "new.img")
        plan = compose([{"kind": "sd", "name": n, "sys": SourceSystem(p, p)} for n, p in zip(names, (b, c, a))],
                       data_mb=40, data_mode="separate", data_files=data)
        self.assertEqual(plan.info["data_files"], 2)
        write_image_file(plan, new)
        got = {}
        for area in cardata.run({"op": "scan", "dev": new})["areas"]:
            z = os.path.join(self.tmp, "o.zip")
            n = cardata.run({"op": "dump", "dev": new, "area": area, "zip": z})["files"]
            with zipfile.ZipFile(z) as zz:
                got[area["names"][0]] = zz.read("params.db").decode() if n else None
        self.assertEqual(got, {"R1CBU v0.30": "settings of r1cbu", "CX8ANM v1.1.5": None,
                               "OpenX6X00 v0.3.12": "settings of openx6x00"})

    def test_doom_extra(self):
        import lzma
        from x6100mb.compose import resolve_extras
        a = os.path.join(self.tmp, "a.img")
        fake_card(a, kernel=b"K" * 4000)
        rootfs = os.path.join(self.tmp, "doom.ext4.xz")
        with lzma.open(rootfs, "wb") as f:
            f.write(b"D" * (2 << 20))
        sa = SourceSystem(a, a)
        ents = resolve_extras([{"kind": "sd", "name": "A", "sys": sa}, {"kind": "doom", "name": "DOOM"}], rootfs)
        plan = compose(ents, data_mb=40)
        out = os.path.join(self.tmp, "doom.img")
        write_image_file(plan, out)
        with open(out, "rb") as f:
            parts = {p[0]: p for p in read_mbr(f)}
            boot = FatReader(f, parts[1][2] * SECTOR)
            self.assertEqual(boot.read_file("SYS2/ZIMAGE"), b"K" * 4000)      # the donor's kernel
            script = parse_script_image(boot.read_file("boot.scr"))
            self.assertIn("root=/dev/mmcblk0p5", script)
            self.assertIn("doom_modules=/dev/mmcblk0p2", script)                  # the donor's modules
            self.assertIn(b"music=100", boot.read_file("doom.txt"))
            f.seek(parts[5][2] * SECTOR)
            self.assertEqual(f.read(4), b"DDDD")
        with self.assertRaises(Exception):                                 # no system to lend a kernel
            resolve_extras([{"kind": "doom", "name": "DOOM"}], rootfs)


    def test_doom_shares_donor_data(self):
        import lzma
        from x6100mb.compose import resolve_extras
        a, b = os.path.join(self.tmp, "a.img"), os.path.join(self.tmp, "b.img")
        fake_card(a)
        fake_card(b)
        rootfs = os.path.join(self.tmp, "doom.ext4.xz")
        with lzma.open(rootfs, "wb") as f:
            f.write(b"D" * (1 << 20))
        sa, sb = SourceSystem(a, a), SourceSystem(b, b)
        ents = resolve_extras([{"kind": "sd", "name": "A", "sys": sa}, {"kind": "sd", "name": "B", "sys": sb},
                               {"kind": "doom", "name": "DOOM"}], rootfs)
        plan = compose(ents, data_mb=40, data_mode="separate")
        self.assertEqual(plan.info["data_partitions"], 2)                   # A and B, not Doom
        script = plan.script
        self.assertIn("setenv bm_boot3 'mmc dev 0; mmc read 0x45000000 0 1; if fatload mmc 0:1 0x45100000 SYS1/MBR.BIN", script)

    def test_data_files_carried_over(self):
        a = os.path.join(self.tmp, "a.img")
        fake_card(a)
        sa = SourceSystem(a, a)
        src = os.path.join(self.tmp, "old")
        os.makedirs(os.path.join(src, "app_logs"))
        with open(os.path.join(src, "params.db"), "wb") as f:
            f.write(b"P" * 5000)
        with open(os.path.join(src, "app_logs", "x6100_log_2026-11-13_10-00.txt"), "wb") as f:
            f.write(b"log")
        from x6100mb import backup
        files = backup.snapshot(src, os.path.join(self.tmp, "copy"))
        plan = compose([{"kind": "sd", "name": "A", "sys": sa}], data_mb=64, data_files=files)
        out = os.path.join(self.tmp, "keep.img")
        write_image_file(plan, out)
        with open(out, "rb") as f:
            parts = {p[0]: p for p in read_mbr(f)}
            data = FatReader(f, parts[3][2] * SECTOR)
            self.assertEqual(data.read_file("params.db"), b"P" * 5000)
            self.assertEqual(data.read_file("app_logs/x6100_log_2026-11-13_10-00.txt"), b"log")
        z = backup.save_zip(src, os.path.join(self.tmp, "b.zip"))
        import zipfile
        self.assertEqual(sorted(zipfile.ZipFile(z).namelist()), ["app_logs/x6100_log_2026-11-13_10-00.txt", "params.db"])

    def test_long_timeout_and_wait(self):
        a = os.path.join(self.tmp, "a.img")
        fake_card(a)
        sa = SourceSystem(a, a)
        plan = compose([{"kind": "sd", "name": "A", "sys": sa}], timeout_s=12, data_mb=40)
        self.assertIn("setenv bm_secs 12", plan.script)
        self.assertIn("setenv bm_hex_12 'setenv bm_secs c'", plan.script)     # U-Boot counts in hex
        self.assertIn("setenv bm_dec_c 'setenv bm_left 12'", plan.script)     # and shows decimal
        self.assertIn("setenv bm_wait 0", plan.script)
        plan = compose([{"kind": "sd", "name": "A", "sys": sa}], timeout_s=99, wait=True, data_mb=40)
        self.assertIn("setenv bm_secs 15", plan.script)
        self.assertIn("setenv bm_wait 1", plan.script)
        self.assertTrue(plan.info["wait"])


if __name__ == "__main__":
    unittest.main()
