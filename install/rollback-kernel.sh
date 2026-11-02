#!/bin/bash
# Undo install/update-kernel.sh: previous modules, Image.gz and initramfs.
set -euo pipefail
KVER=${KVER:-6.19.5-t825}
S=/var/tmp/t825-kernel
[ -e $S/modules-prev.tar ] && [ -e /boot/vmlinuz-t825.prev ] && [ -e /boot/initramfs-t825.prev ]
rm -rf "/usr/lib/modules/$KVER"
tar -C /usr/lib/modules -xf $S/modules-prev.tar
depmod -a "$KVER"
cp -a /boot/vmlinuz-t825.prev /boot/vmlinuz-t825
cp -a /boot/initramfs-t825.prev /boot/initramfs-t825
sync
echo "previous kernel restored; reboot"
