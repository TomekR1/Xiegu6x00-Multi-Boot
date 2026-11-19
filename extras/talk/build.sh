#!/bin/bash
# The talking boot menu (Extras): Jim Ruiz's talkmenu (X6100 Talking MultiBoot, GPL-2.0-or-later) as
# /sbin/init of a tiny root filesystem, started like Doom with the first system's kernel; and its voice
# (RHVoice Lyubov) as short recordings the app joins into each card's prompts.
#   extras/talk/build.sh  ->  out/talk-x6100-rootfs.ext4.xz, out/talk-voice.zip
# Needs: gcc-arm-linux-gnueabihf, e2fsprogs, xz-utils, git, rhvoice + rhvoice-english.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
W=$HERE/work
OUT=$HERE/out
TALK_REPO=https://github.com/Jimr9/X6100-Talking-MultiBoot
TALK_COMMIT=c3a86c4      # "Talking menu: mark the choice, then switch the radio off and ask for the power key"
rm -rf "$W" && mkdir -p "$W" "$OUT"
git clone -q "$TALK_REPO" "$W/src"
git -C "$W/src" checkout -q "$TALK_COMMIT"
arm-linux-gnueabihf-gcc -O2 -Wall -Wno-unused-result -static -s -o "$W/talkmenu" "$W/src/talkmenu.c"
R=$W/root
mkdir -p "$R/sbin" "$R/dev" "$R/proc" "$R/sys" "$R/boot" "$R/tmp" "$R/donor" "$R/usr/share/doc/talkmenu"
cp "$W/talkmenu" "$R/sbin/init"
cp "$W/src/LICENSE" "$R/usr/share/doc/talkmenu/LICENSE"
printf 'talkmenu: Jim Ruiz, X6100 Talking MultiBoot, %s (commit %s), GPL-2.0-or-later\n' "$TALK_REPO" "$TALK_COMMIT" \
    > "$R/usr/share/doc/talkmenu/SOURCE"
rm -f "$OUT/talk-x6100-rootfs.ext4"
mke2fs -q -t ext4 -L TALK -O ^metadata_csum_seed -E root_owner=0:0 -d "$R" "$OUT/talk-x6100-rootfs.ext4" 8M
e2fsck -n -f "$OUT/talk-x6100-rootfs.ext4" >/dev/null
xz -T0 -9 -f "$OUT/talk-x6100-rootfs.ext4"
python3 "$HERE/voice.py" "$OUT/talk-voice.zip"
ls -la "$OUT"
