#!/bin/bash
# Kernel, device trees and initramfs for this tablet, from the postmarketOS rootfs chroot that
# "pmbootstrap install --no-image" leaves behind.
#
# The ADSP, SLPI and Venus drivers load while the initramfs still runs, and the kernel command
# line disables the sysfs firmware fallback, so their Samsung-signed firmware (and the sensor
# registry) must be inside the initramfs. They come from install/extract-firmware.sh; this script
# copies them into the chroot, lists them for mkinitfs and regenerates the initramfs.
# The result contains your tablet's firmware and calibration: do not publish it.
#   FIRMWARE_DIR=./firmware install/make-initramfs.sh out/boot
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: make-initramfs.sh <output dir>}
: "${FIRMWARE_DIR:?set FIRMWARE_DIR to the output of install/extract-firmware.sh}"
PMB=${PMB:-pmbootstrap}
work=$($PMB config work)
C=$work/chroot_rootfs_samsung-gts3lwifi
[ -d "$C/etc" ] || { echo "no $C: run 'pmbootstrap install --no-image' first" >&2; exit 1; }

sudo mkdir -p "$C/lib/firmware/qcom/msm8996/samsung/gts3" "$C/lib/firmware/qcom/sensors" "$C/lib/firmware/ath10k/QCA6174/hw3.0"
sudo cp "$FIRMWARE_DIR"/qcom/msm8996/samsung/gts3/* "$C/lib/firmware/qcom/msm8996/samsung/gts3/"
sudo cp "$FIRMWARE_DIR/qcom/sensors/sns.reg-samsung,gts3llte" "$C/lib/firmware/qcom/sensors/"
sudo cp "$FIRMWARE_DIR/ath10k/QCA6174/hw3.0/board.bin" "$C/lib/firmware/ath10k/QCA6174/hw3.0/board.bin"
sudo install -Dm644 "$HERE/rootfs/files/90-gts3-firmware.files" "$C/etc/mkinitfs/files-extra/90-gts3-firmware.files"

# "apk add -u" does not always rerun mkinitfs, so call it explicitly.
$PMB chroot -r -- sh -c 'apk add -u linux-postmarketos-qcom-msm8996 && mkinitfs'

mkdir -p "$out"
cp "$C/boot/vmlinuz" "$out/vmlinuz"
cp "$C/boot/initramfs" "$out/initramfs"
rm -rf "$out/dtbs"
cp -r "$C/boot/dtbs" "$out/dtbs"
ls "$C/lib/modules"
sha256sum "$out/vmlinuz" "$out/initramfs" "$out/dtbs/qcom/msm8996-samsung-gts3llte.dtb"
