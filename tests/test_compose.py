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


if __name__ == "__main__":
    unittest.main()
