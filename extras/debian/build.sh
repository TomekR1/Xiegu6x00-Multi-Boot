#!/bin/bash
# Debian for the Xiegu X6100, as an extra of the multiboot card: a root filesystem only. It starts
# with the kernel and device tree of the first system from an image on the card (its kernel is the
# community's open one, with the screen's driver) and takes that kernel's modules from there
# (x6100-donor.service). Debian's packages are fetched from Debian's mirrors when this is built.
#
#   sudo extras/debian/build.sh     ->  extras/debian/out/debian-x6100-rootfs.ext4.xz
#
# Needs: mmdebstrap, debian-archive-keyring, qemu-user-static with binfmt for armhf, e2fsprogs, xz.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/out
SUITE=${SUITE:-trixie}
MIRROR=${MIRROR:-http://deb.debian.org/debian}
ROOT=$OUT/rootfs
mkdir -p "$OUT"
rm -rf "$ROOT"

PKGS=(
  systemd-sysv udev dbus login libpam-systemd netbase tzdata bash-completion kmod procps psmisc less nano sudo ca-certificates curl htop
  iproute2 iputils-ping network-manager wpasupplicant iw wireless-regdb rfkill
  openssh-server avahi-daemon libnss-mdns
  bluez alsa-utils
  console-setup kbd
  firmware-realtek
  libhamlib-utils i2c-tools gpiod evtest usbutils e2fsprogs
  systemd-timesyncd
)
mmdebstrap --arch=armhf --keyring=/usr/share/keyrings/debian-archive-keyring.gpg --variant=apt --components=main,non-free-firmware \
  --include="$(IFS=,; echo "${PKGS[*]}")" \
  --aptopt='APT::Install-Recommends "false"' \
  --dpkgopt='path-exclude=/usr/share/doc/*' --dpkgopt='path-include=/usr/share/doc/*/copyright' \
  --dpkgopt='path-exclude=/usr/share/man/*' --dpkgopt='path-exclude=/usr/share/locale/*' \
  "$SUITE" "$ROOT" "$MIRROR"

cp -a "$HERE/overlay/." "$ROOT/"
cat > "$ROOT/tmp/setup.sh" <<'SETUP'
set -e
echo x6100-debian > /etc/hostname
printf '127.0.0.1\tlocalhost\n127.0.1.1\tx6100-debian\n' > /etc/hosts
printf '/dev/root\t/\text4\tdefaults,noatime,commit=60\t0\t0\n' > /etc/fstab
# The user: radio / radio, a new password asked at the first login (on the screen or over ssh)
useradd -m -s /bin/bash -G sudo,audio,video,input,dialout,netdev,bluetooth,plugdev radio
echo radio:radio | chpasswd
chage -d 0 radio
passwd -l root
# Generated on the radio at the first start, each card its own
rm -f /etc/ssh/ssh_host_* /etc/machine-id /var/lib/dbus/machine-id
: > /etc/machine-id
mkdir -p /usr/lib/modules
systemctl enable x6100-donor.service x6100-firstboot.service NetworkManager ssh avahi-daemon bluetooth
systemctl mask systemd-firstboot.service
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /tmp/setup.sh
SETUP
chroot "$ROOT" /bin/bash /tmp/setup.sh

# The filesystem: what is used plus room; the first start grows it to its partition
used=$(du -sm "$ROOT" | cut -f1)
size=$(( used + used / 5 + 128 ))
rm -f "$OUT/debian-x6100-rootfs.ext4"
mke2fs -q -t ext4 -L debian -O ^metadata_csum_seed -E root_owner=0:0 -d "$ROOT" \
  "$OUT/debian-x6100-rootfs.ext4" "${size}M"
e2fsck -fy "$OUT/debian-x6100-rootfs.ext4" >/dev/null || true
xz -T0 -6 -f -k "$OUT/debian-x6100-rootfs.ext4"
ls -la "$OUT"/debian-x6100-rootfs.ext4*
