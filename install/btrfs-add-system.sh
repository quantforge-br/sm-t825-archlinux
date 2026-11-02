#!/bin/bash
# Second half of the btrfs move: once the tablet runs from the btrfs on userdata, add the old
# ext4 "system" partition (mmcblk0p44) as a second device (data single, metadata DUP).
# This destroys the ext4 root on p44 and so the way back through extlinux.conf.pre-btrfs.
set -euo pipefail
export LANG=C
P44=/dev/mmcblk0p44
[ "$(findmnt -no FSTYPE /)" = btrfs ] || { echo "/ is not btrfs" >&2; exit 1; }
[ "$(lsblk -no PARTLABEL $P44)" = system ] || { echo "$P44 is not system" >&2; exit 1; }
if findmnt -S $P44 >/dev/null; then echo "$P44 is mounted" >&2; exit 1; fi
wipefs -aq $P44
btrfs device add -f $P44 /
udevadm settle
btrfs filesystem show /
btrfs filesystem usage -T / | sed -n '1,12p'
