#!/bin/bash
# Step 2 of the move to btrfs: point lk2nd's extlinux.conf at the btrfs root that
# install/btrfs-migrate.sh created. The previous file stays as extlinux.conf.pre-btrfs, so the ext4
# root on "system" can still be booted (copy it back from a debug shell or a "fastboot boot" image)
# until install/btrfs-add-system.sh takes that partition. Run as root on the tablet.
set -euo pipefail
OPTS=noatime,compress=zstd:1
uuid=${1:-$(cat /root/t825-btrfs-uuid)}
conf=/boot/extlinux/extlinux.conf
mountpoint -q /boot || { echo "/boot is not mounted" >&2; exit 1; }
[ "$(blkid -s TYPE -o value "$(blkid --uuid "$uuid")")" = btrfs ] || { echo "$uuid is not a btrfs" >&2; exit 1; }
[ -e "$conf.pre-btrfs" ] || cp -a "$conf" "$conf.pre-btrfs"
sed -i -E "s#pmos_root_uuid=[^ ]+ pmos_rootfsopts=[^ ]+#pmos_root_uuid=$uuid pmos_rootfsopts=subvol=/@,$OPTS#" "$conf"
grep -E '^\s*append' "$conf"
grep -q "pmos_root_uuid=$uuid pmos_rootfsopts=subvol=/@" "$conf" || { echo "extlinux.conf not updated" >&2; exit 1; }
sync
echo "extlinux.conf now boots btrfs $uuid; reboot"
