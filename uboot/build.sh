#!/bin/bash
# Builds the menu's U-Boot for the X6100: mainline v2026.07 (as OpenX6X00 uses), the X6100's
# device tree and defconfig, plus the ST7701S panel set-up (0001-*.patch) so the menu shows
# on the radio's screen. Result: uboot/out/u-boot-x6100-menu.bin
#
# Needs: gcc-arm-linux-gnueabihf bison flex swig python3-dev python3-setuptools
#        python3-pyelftools libssl-dev libgnutls28-dev device-tree-compiler bc git
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
VER=v2026.07
W=$HERE/work
rm -rf "$W" && mkdir -p "$W" "$HERE/out"
git clone -q --depth 1 --branch $VER https://github.com/u-boot/u-boot "$W/u-boot"
cd "$W/u-boot"
git apply "$HERE"/0001-*.patch
cp "$HERE/sun8i-r16-x6100.dts" "$HERE/sun8i-r16-x6100-u-boot.dtsi" arch/arm/dts/
sed -i 's/\tsun8i-r16-parrot.dtb/\tsun8i-r16-parrot.dtb \\\n\tsun8i-r16-x6100.dtb/' arch/arm/dts/Makefile
grep -q sun8i-r16-x6100.dtb arch/arm/dts/Makefile
# The panel timings as the X6100's Linux driver has them (vertical back porch 17)
sed 's/^CONFIG_VIDEO_LCD_MODE=.*/CONFIG_VIDEO_LCD_MODE="x:480,y:800,depth:18,pclk_khz:27500,le:12,ri:38,up:17,lo:18,hs:12,vs:8,sync:3,vmode:0"/' \
    "$HERE/x6100_defconfig" > configs/x6100_menu_defconfig
cat "$HERE/menu.config" >> configs/x6100_menu_defconfig
export CROSS_COMPILE=arm-linux-gnueabihf-
make -s x6100_menu_defconfig
for o in VIDEO_LCD_ST7701S_X6100 CONSOLE_ROTATION VIDEO_FONT_16X32 CMD_GPIO; do
    grep -q "^CONFIG_$o=y" .config || { echo "CONFIG_$o not set"; exit 1; }
done
make -s -j"$(nproc)"
cp u-boot-sunxi-with-spl.bin "$HERE/out/u-boot-x6100-menu.bin"
strings "$HERE/out/u-boot-x6100-menu.bin" | grep -m1 "U-Boot SPL"
ls -la "$HERE/out"
