"""Regression tests for IU1WXY 0.2.2+ A/B boot script parsing."""
import unittest

from x6100mb.image import DEFAULT_FDTFILE


IU1WXY_SCRIPT = r"""
setenv slot a
setenv other b
setenv rootp 2

if load mmc 0:1 0x44000000 ab.env; then
    env import -t 0x44000000 ${filesize} slot prev trial count lastfail bad ktry zend
fi

for s in ${slot} ${other}; do
    if test "${s}" = b; then setenv rootp 4; else setenv rootp 2; fi
    setenv bootargs console=ttyS0,115200 root=/dev/mmcblk0p${rootp} rootwait panic=5
    if ext4load mmc 0:${rootp} 0x46000000 /boot/zImage; then
        if ext4load mmc 0:${rootp} 0x49000000 /boot/sun8i-r16-x6100.dtb; then
            bootz 0x46000000 - 0x49000000
        fi
    fi
done
"""


class IU1WXYScriptTest(unittest.TestCase):
    def test_expected_ab_markers(self):
        self.assertIn("ab.env", IU1WXY_SCRIPT)
        self.assertIn("${rootp}", IU1WXY_SCRIPT)
        self.assertIn("ext4load mmc 0:${rootp} 0x46000000 /boot/zImage", IU1WXY_SCRIPT)
        self.assertIn("ext4load mmc 0:${rootp} 0x49000000 /boot/" + DEFAULT_FDTFILE, IU1WXY_SCRIPT)
        self.assertIn("bootz 0x46000000 - 0x49000000", IU1WXY_SCRIPT)


if __name__ == "__main__":
    unittest.main()
