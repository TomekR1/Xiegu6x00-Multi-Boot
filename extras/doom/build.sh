#!/bin/bash
# Builds the Doom easter egg for the X6100: doomgeneric with the X6100 layer (doomgeneric_x6100.c),
# static, as /sbin/init of a small ext4 root filesystem with Freedoom phase 1. The kernel comes
# from a system already on the card. Result: extras/doom/out/doom-x6100-rootfs.ext4.xz
#
# Needs: gcc-arm-linux-gnueabihf, e2fsprogs (mke2fs -d), git, curl, unzip, xz; gcc for the PC test.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
W=$HERE/work
OUT=$HERE/out
DG_COMMIT=e257a09527062bfb986b6e5e0780839b6cbd5b71
TA_COMMIT=1c5fb68ced57d838f2b7ecd0c00bc1fefc9ab60d   # tinyalsa v2.0.0 (BSD-3-Clause)
CD_COMMIT=539ef367c9982c5945f8608b63d2236eaecc929a   # chocolate-doom-3.0.1 (GPL-2.0): the OPL music
FD_VER=0.13.0
FD_SHA=7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d   # freedoom1.wad
rm -rf "$W" && mkdir -p "$W" "$OUT"

git clone -q https://github.com/ozkl/doomgeneric "$W/doomgeneric"
git -C "$W/doomgeneric" checkout -q $DG_COMMIT
# The mouse's motion summed until the next tic (Doom keeps only the last event's: a USB mouse
# sends many small ones a tic, and turning was too slow to notice)
sed -i 's/\tmousex = ev->data2\*/\tmousex += ev->data2*/; s/\tmousey = ev->data3\*/\tmousey += ev->data3*/' \
    "$W/doomgeneric/doomgeneric/g_game.c"
grep -q 'mousex += ev->data2' "$W/doomgeneric/doomgeneric/g_game.c"
git clone -q https://github.com/tinyalsa/tinyalsa "$W/tinyalsa"
git -C "$W/tinyalsa" checkout -q $TA_COMMIT
TA=$W/tinyalsa
git clone -q --depth 1 --branch chocolate-doom-3.0.1 https://github.com/chocolate-doom/chocolate-doom "$W/chocolate"
test "$(git -C "$W/chocolate" rev-parse HEAD)" = $CD_COMMIT
CD=$W/chocolate
# The player's two files on their own, so they take doomgeneric's headers, not Chocolate Doom's
mkdir -p "$W/midi" && cp "$CD/src/midifile.h" "$CD/src/midifile.c" "$CD/src/i_oplmusic.c" "$W/midi/"
# i_sound.c includes SDL_mixer.h when sound is on; nothing of it is used
mkdir -p "$W/sdlstub" && : > "$W/sdlstub/SDL_mixer.h"
D=$W/doomgeneric/doomgeneric
SRC="dummy am_map doomdef doomstat dstrings d_event d_items d_iwad d_loop d_main d_mode d_net f_finale
 f_wipe g_game hu_lib hu_stuff info i_cdmus i_endoom i_joystick i_scale i_sound i_system i_timer memio
 m_argv m_bbox m_cheat m_config m_controls m_fixed m_menu m_misc m_random p_ceilng p_doors p_enemy
 p_floor p_inter p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg p_setup p_sight p_spec p_switch
 p_telept p_tick p_user r_bsp r_data r_draw r_main r_plane r_segs r_sky r_things sha1 sounds statdump
 st_lib st_stuff s_sound tables v_video wi_stuff w_checksum w_file w_main w_wad z_zone w_file_stdc
 i_input i_video doomgeneric mus2mid"
DEFS="-DNORMALUNIX -DLINUX -D_DEFAULT_SOURCE -DDOOMGENERIC_RESX=320 -DDOOMGENERIC_RESY=200 -DFEATURE_SOUND"

build() {   # build CC OUTDIR EXTRA_FLAGS...
    local cc=$1 out=$2; shift 2
    mkdir -p "$out"
    for f in $SRC; do $cc -O2 $DEFS -w -I"$D" -I"$W/sdlstub" "$@" -c "$D/$f.c" -o "$out/$f.o"; done
    for f in pcm pcm_hw mixer mixer_hw limits snd_card_plugin; do
        $cc -O2 -w -I"$TA/include" "$@" -c "$TA/src/$f.c" -o "$out/ta_$f.o"
    done
    $cc -O2 $DEFS -Wall -Wno-unused -I"$D" "$@" -c "$HERE/doomgeneric_x6100.c" -o "$out/x6100.o"
    $cc -O2 $DEFS -Wall -Wno-unused -I"$D" -I"$TA/include" "$@" -c "$HERE/x6100_sound.c" -o "$out/x6100_sound.o"
    # The music: Chocolate Doom's OPL player, the Nuked OPL3 emulator, our output for it
    local inc="-I$D -I$CD/opl -I$W/midi -I$HERE/sdl_stub"
    for f in opl opl3 opl_queue; do
        $cc -O2 $DEFS -w $inc "$@" -c "$CD/opl/$f.c" -o "$out/cd_$f.o"
    done
    $cc -O2 $DEFS -w $inc -include "$HERE/sdl_stub/SDL.h" -include "$HERE/opl_compat.h" "$@" -c "$W/midi/midifile.c" -o "$out/cd_midifile.o"
    $cc -O2 $DEFS -w $inc -include "$HERE/opl_compat.h" -Dmusic_opl_module=DG_music_module "$@" \
        -c "$W/midi/i_oplmusic.c" -o "$out/cd_i_oplmusic.o"
    $cc -O2 $DEFS -w $inc "$@" -c "$HERE/opl_x6100.c" -o "$out/opl_x6100.o"
}

# The radio's: ARMv7, hard float, one static binary
build arm-linux-gnueabihf-gcc "$W/arm" -march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard
arm-linux-gnueabihf-gcc -static -s -o "$W/doom" "$W"/arm/*.o -lm -lpthread

# Freedoom (BSD licence)
curl -sSfL -o "$W/fd.zip" https://github.com/freedoom/freedoom/releases/download/v$FD_VER/freedoom-$FD_VER.zip
unzip -q -o "$W/fd.zip" -d "$W/fd"
echo "$FD_SHA  $W/fd/freedoom-$FD_VER/freedoom1.wad" | sha256sum -c -

# A PC test: 400 frames of the demo, drawn into memory, must come out
if command -v gcc >/dev/null; then
    build gcc "$W/pc"
    gcc -o "$W/doom-pc" "$W"/pc/*.o -lm -lpthread
    (cd "$W" && DOOM_TEST_FB=480x800 DOOM_TEST_FRAMES=400 DOOM_TEST_OUT=frame.raw \
        DOOM_TEST_PCM=sound.raw timeout 120 ./doom-pc -iwad "$W/fd/freedoom-$FD_VER/freedoom1.wad" > pc-test.log 2>&1)
    test "$(stat -c %s "$W/frame.raw")" = 1536000
    # the sound of those frames (48 kHz stereo s16): music and effects, not silence
    python3 - "$W/sound.raw" <<'PY'
import struct, sys
d = open(sys.argv[1], "rb").read()
n = len(d) // 2
s = struct.unpack("<%dh" % n, d[:n * 2])
loud = sum(1 for v in s if abs(v) > 500)
print("PC test sound: %.1f s, %d%% of samples above -36 dBFS" % (n / 2 / 48000, 100 * loud // max(n, 1)))
assert n > 48000 and loud > n // 20, "no sound came out"
PY
    cp "$W/frame.raw" "$OUT/test-frame-480x800-bgrx.raw"
fi

# The root filesystem
R=$W/root
mkdir -p "$R/sbin" "$R/doom" "$R/dev" "$R/proc" "$R/sys" "$R/tmp"
cp "$W/doom" "$R/sbin/init"
cp "$W/fd/freedoom-$FD_VER/freedoom1.wad" "$R/doom/"
cp "$W/fd/freedoom-$FD_VER/COPYING.txt" "$R/doom/FREEDOOM-COPYING.txt"
cp "$W/doomgeneric/LICENSE" "$R/doom/DOOMGENERIC-LICENSE.txt"
cp "$TA/NOTICE" "$R/doom/TINYALSA-NOTICE.txt"
cp "$CD/COPYING" "$R/doom/CHOCOLATE-DOOM-COPYING.txt"
cat > "$R/doom/README.txt" <<'TXT'
Doom on the Xiegu X6100 (an easter egg of Xiegu Multi Patcher, by SQ6RT).
Engine: doomgeneric (GPL-2.0) with an X6100 layer, sound through tinyalsa (BSD-3-Clause), music
with Chocolate Doom's OPL player and the Nuked OPL3 emulator (GPL-2.0 / LGPL-2.1).
Game data: Freedoom phase 1 (BSD).
A doom.wad / doom2.wad / doom1.wad of your own put here is played instead.
TXT
rm -f "$OUT/doom-x6100-rootfs.ext4"
mke2fs -q -t ext4 -L DOOM -O ^metadata_csum_seed -d "$R" "$OUT/doom-x6100-rootfs.ext4" 64M
e2fsck -n -f "$OUT/doom-x6100-rootfs.ext4"
xz -T0 -9 -f "$OUT/doom-x6100-rootfs.ext4"
sha256sum "$OUT/doom-x6100-rootfs.ext4.xz" > "$OUT/doom-x6100-rootfs.ext4.xz.sha256"
ls -la "$OUT"
