#!/bin/bash
# Build an Arch Linux ARM (aarch64) root filesystem image for the Galaxy Tab S3 LTE (SM-T825).
#
# The image is an ext4 file sized for Android's "system" partition (mmcblk0p44). Kernel modules,
# Alpine's linux-firmware files and the device files come from the postmarketOS rootfs chroot that
# "pmbootstrap install" leaves behind; Samsung's signed firmware comes from FIRMWARE_DIR, which
# install/extract-firmware.sh fills from your own tablet's partitions. Nothing here downloads them.
#
# Usage (as root, umask 022):
#   PMOS_ROOTFS=$(pmbootstrap config work)/chroot_rootfs_samsung-gts3lwifi \
#   FIRMWARE_DIR=./firmware SSH_PUBKEY=~/.ssh/id_ed25519.pub PWHASH_FILE=./pwhash \
#   ALARM_TARBALL=./ArchLinuxARM-aarch64-latest.tar.gz \
#   bash rootfs/build-arch-rootfs.sh
set -euo pipefail
umask 022

HERE=$(cd "$(dirname "$0")" && pwd)
: "${PMOS_ROOTFS:?set PMOS_ROOTFS to the pmbootstrap rootfs chroot (chroot_rootfs_samsung-gts3lwifi)}"
: "${FIRMWARE_DIR:?set FIRMWARE_DIR to the output of install/extract-firmware.sh}"
: "${SSH_PUBKEY:?set SSH_PUBKEY to the public key that may log in}"
: "${PWHASH_FILE:?set PWHASH_FILE to a file with a SHA-512 crypt hash (openssl passwd -6)}"
ALARM_TARBALL=${ALARM_TARBALL:-$HERE/ArchLinuxARM-aarch64-latest.tar.gz}
OUT_DIR=${OUT_DIR:-$HERE/out}
IMG=${IMG:-$OUT_DIR/arch-gts3llte-root.ext4}
# Fixed so that boot images and extlinux entries can name the root before it exists.
ROOT_UUID=${ROOT_UUID:-3c1b2d91-6191-410b-8f7d-4d7cd5a21b26}
# UUID of the ext2 boot file system that install/make-boot-partition.sh creates on "cache".
BOOT_UUID=${BOOT_UUID:-c5e5c7d5-7019-4c4e-ba93-af3c61a96e1b}
# Size of the SM-T825 "system" partition.
IMG_SIZE=${IMG_SIZE:-4194304000}
KVER=${KVER:-7.3.1-t825}
USERNAME=${USERNAME:-tab}
HOSTNAME_=${HOSTNAME_:-tabs3}
LOCALE=${LOCALE:-en_US.UTF-8}
KEYMAP=${KEYMAP:-us}
TIMEZONE=${TIMEZONE:-UTC}
FILES=$HERE/files
MNT=$OUT_DIR/mnt

cleanup() {
  sync
  if mountpoint -q "$MNT"; then umount -R "$MNT" || umount -l "$MNT"; fi
}
trap cleanup EXIT

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -d "$PMOS_ROOTFS/lib/modules/$KVER" ] || { echo "no $KVER modules in $PMOS_ROOTFS" >&2; exit 1; }
for f in qcom/msm8996/samsung/gts3/adsp.mdt qcom/msm8996/samsung/gts3/slpi.mdt \
         qcom/msm8996/samsung/gts3/venus.mdt qcom/msm8996/samsung/gts3/a530_zap.mdt \
         ath10k/QCA6174/hw3.0/board.bin "qcom/sensors/sns.reg-samsung,gts3llte"; do
  [ -e "$FIRMWARE_DIR/$f" ] || { echo "FIRMWARE_DIR lacks $f (run install/extract-firmware.sh)" >&2; exit 1; }
done

echo "### verify tarball checksum"
if [ -e "$ALARM_TARBALL.md5" ]; then
  (cd "$(dirname "$ALARM_TARBALL")" && md5sum -c "$(basename "$ALARM_TARBALL").md5")
else
  echo "no $ALARM_TARBALL.md5 next to the tarball, skipping" >&2
fi

echo "### create ext4 image"
mkdir -p "$OUT_DIR"
rm -f "$IMG"
truncate -s "$IMG_SIZE" "$IMG"
mkfs.ext4 -F -q -L arch_root -U "$ROOT_UUID" -m 1 "$IMG"
mkdir -p "$MNT"
mount -o loop "$IMG" "$MNT"

echo "### extract Arch Linux ARM"
bsdtar -xpf "$ALARM_TARBALL" -C "$MNT"

echo "### kernel modules from the postmarketOS kernel package"
mkdir -p "$MNT/usr/lib/modules"
cp -a "$PMOS_ROOTFS/lib/modules/$KVER" "$MNT/usr/lib/modules/"

echo "### USB network gadget"
install -Dm755 "$FILES/t825-usb-gadget" "$MNT/usr/local/sbin/t825-usb-gadget"
install -Dm644 "$FILES/t825-usb-gadget.service" "$MNT/etc/systemd/system/t825-usb-gadget.service"

echo "### reboot to lk2nd fastboot without writing the boot partition"
install -Dm755 "$FILES/t825-reboot-fastboot" "$MNT/usr/local/sbin/t825-reboot-fastboot"
install -Dm644 "$FILES/t825-extlinux-restore.service" "$MNT/etc/systemd/system/t825-extlinux-restore.service"

echo "### staging for chroot"
install -Dm600 "$SSH_PUBKEY" "$MNT/var/tmp/authorized_keys"
install -Dm755 "$HERE/chroot-setup.sh" "$MNT/var/tmp/chroot-setup.sh"

echo "### chroot setup"
PWHASH=$(cat "$PWHASH_FILE")
arch-chroot "$MNT" /usr/bin/env PWHASH="$PWHASH" USERNAME="$USERNAME" HOSTNAME_="$HOSTNAME_" \
  LOCALE="$LOCALE" KEYMAP="$KEYMAP" TIMEZONE="$TIMEZONE" ROOT_UUID="$ROOT_UUID" BOOT_UUID="$BOOT_UUID" KVER="$KVER" SUDO_NOPASSWD="${SUDO_NOPASSWD:-0}" \
  /bin/bash /var/tmp/chroot-setup.sh
rm -f "$MNT/var/tmp/chroot-setup.sh" "$MNT/var/tmp/authorized_keys"

echo "### firmware: Alpine linux-firmware files from the pmOS rootfs, then this tablet's own blobs"
rsync -a --ignore-existing "$PMOS_ROOTFS/lib/firmware/" "$MNT/usr/lib/firmware/"
rsync -a "$FIRMWARE_DIR/" "$MNT/usr/lib/firmware/"

echo "### device files"
copy_dev() { if [ -e "$MNT/$2" ]; then echo "overwriting packaged $2"; fi; install -Dm"$3" "$PMOS_ROOTFS/$1" "$MNT/$2"; }
copy_dev etc/machine-info etc/machine-info 644
copy_dev usr/lib/modules-load.d/00-device-samsung-gts3lwifi.conf usr/lib/modules-load.d/00-device-samsung-gts3lwifi.conf 644
copy_dev usr/lib/systemd/system/gts3-bdaddr.service usr/lib/systemd/system/gts3-bdaddr.service 644
copy_dev usr/lib/udev/rules.d/90-gts3-bdaddr.rules usr/lib/udev/rules.d/90-gts3-bdaddr.rules 644
copy_dev usr/lib/udev/rules.d/61-gts3-accel.rules usr/lib/udev/rules.d/61-gts3-accel.rules 644
# Keep this repo's Hyprland orientation matrix; both copies request 12 Hz.
# /etc overrides /usr/lib, including its sampling-frequency rule.
install -Dm644 "$FILES/61-gts3-accel.rules" "$MNT/etc/udev/rules.d/61-gts3-accel.rules"
install -Dm755 "$FILES/gts3-bdaddr" "$MNT/usr/local/sbin/gts3-bdaddr"
sed -i "s|/usr/sbin/gts3-bdaddr|/usr/local/sbin/gts3-bdaddr|" "$MNT/usr/lib/systemd/system/gts3-bdaddr.service"
# Fixed HiFi verb: routes the top speakers (QUAT TDM) only when the device tree has them.
install -Dm644 "$FILES/ucm-HiFi.conf" "$MNT/usr/share/alsa/ucm2/Samsung/gts3lwifi/HiFi.conf"
copy_dev usr/share/alsa/ucm2/Samsung/gts3lwifi/gts3lwifi.conf usr/share/alsa/ucm2/Samsung/gts3lwifi/gts3lwifi.conf 644
copy_dev "usr/share/alsa/ucm2/conf.d/apq8096/Galaxy Tab S3.conf" "usr/share/alsa/ucm2/conf.d/apq8096/Galaxy Tab S3.conf" 644
copy_dev usr/share/wireplumber/wireplumber.conf.d/51-gts3lwifi-audio.conf etc/wireplumber/wireplumber.conf.d/51-gts3lwifi-audio.conf 644
install -Dm644 "$FILES/50-udmabuf.rules" "$MNT/etc/udev/rules.d/50-udmabuf.rules"
install -Dm644 "$FILES/52-bluez-no-seat.conf" "$MNT/etc/wireplumber/wireplumber.conf.d/52-bluez-no-seat.conf"

echo "### sanity checks"
chroot "$MNT" /usr/bin/readlink -f /sbin/init
test -s "$MNT/usr/lib/modules/$KVER/modules.dep"
for f in qcom/msm8996/samsung/gts3/adsp.mdt qcom/msm8996/samsung/gts3/slpi.mdt qcom/msm8996/samsung/gts3/venus.mdt \
         qcom/msm8996/samsung/gts3/a530_zap.mdt qcom/a530_pm4.fw ath10k/QCA6174/hw3.0/board.bin \
         "qcom/sensors/sns.reg-samsung,gts3llte"; do
  if test -e "$MNT/usr/lib/firmware/$f"; then
    echo "fw ok: $f"
  else
    echo "fw MISSING: $f"
    exit 1
  fi
done
ls "$MNT"/usr/lib/firmware/qca/*00440302*
grep -E "^($USERNAME|root):" "$MNT/etc/passwd"
cat "$MNT/etc/fstab"
df -h "$MNT"

cleanup
trap - EXIT
e2fsck -fn "$IMG"
sha256sum "$IMG" | tee "$IMG.sha256"
echo BUILD_OK
