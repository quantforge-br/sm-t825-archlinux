#!/bin/bash
# Install a kernel built with pmbootstrap on the tablet: modules, Image.gz and initramfs.
# The release string stays 6.19.5-t825, so the modules directory is replaced and the boot files
# and modules must change together. The previous ones are kept for install/rollback-kernel.sh:
# /boot/vmlinuz-t825.prev, /boot/initramfs-t825.prev, /var/tmp/t825-kernel/modules-prev.tar.
#   sudo install/update-kernel.sh <modules.tar> <vmlinuz> <initramfs>
# modules.tar: "tar -C <package>/lib/modules -cf modules.tar 6.19.5-t825"
set -euo pipefail
mods=${1:?modules tar}; kernel=${2:?vmlinuz}; initramfs=${3:?initramfs}
KVER=${KVER:-6.19.5-t825}
S=/var/tmp/t825-kernel
mountpoint -q /boot || { echo "/boot is not mounted" >&2; exit 1; }
tar -tf "$mods" | grep -q "^$KVER/modules.dep$" || { echo "$mods has no $KVER/modules.dep" >&2; exit 1; }
mkdir -p $S
tar -C /usr/lib/modules -cf $S/modules-prev.tar "$KVER"
cp -a /boot/vmlinuz-t825 /boot/vmlinuz-t825.prev
cp -a /boot/initramfs-t825 /boot/initramfs-t825.prev
rm -rf "/usr/lib/modules/$KVER"
tar -C /usr/lib/modules --no-same-owner -xf "$mods"
depmod -a "$KVER"
install -m644 "$kernel" /boot/vmlinuz-t825
install -m644 "$initramfs" /boot/initramfs-t825
sync
sha256sum /boot/vmlinuz-t825 /boot/initramfs-t825
echo "installed; reboot. To go back: install/rollback-kernel.sh"
