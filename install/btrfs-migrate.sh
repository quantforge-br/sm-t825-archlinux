#!/bin/bash
# Step 1 of the move to btrfs: copy the running Arch root from the ext4 on "system" (mmcblk0p44,
# 3.9 GiB) to a new btrfs on "userdata" (mmcblk0p47, 24.4 GiB) with subvolumes @ (/) and @home,
# and write the new fstab there. Nothing else changes: lk2nd keeps booting the ext4 root until
# install/btrfs-switch-boot.sh. Run as root on the tablet, booted from the ext4 root.
# Next: test the btrfs root from RAM (docs/btrfs.md), then btrfs-switch-boot.sh, then btrfs-add-system.sh.
set -euo pipefail
export LANG=C
D=/dev/mmcblk0p47
BTR=/run/t825-btr
NEW=/run/t825-new
OPTS=noatime,compress=zstd:1
log() { echo "== $(date +%T) $*"; }

[ "$(lsblk -no PARTLABEL $D)" = userdata ] || { echo "$D is not userdata" >&2; exit 1; }
[ "$(lsblk -no PARTLABEL "$(findmnt -no SOURCE /)")" = system ] || { echo "/ is not on system" >&2; exit 1; }
[ "$(findmnt -no FSTYPE /)" = ext4 ] || { echo "/ is not ext4" >&2; exit 1; }
mountpoint -q /boot || { echo "/boot (cache) is not mounted" >&2; exit 1; }
if findmnt -S $D >/dev/null; then echo "$D is mounted" >&2; exit 1; fi
OLD_UUID=$(findmnt -no UUID /)

log "installing btrfs-progs"
pacman -S --noconfirm --needed btrfs-progs >/dev/null

log "mkfs.btrfs on $D (this erases userdata)"
wipefs -aq $D
mkfs.btrfs -q -f -L arch_root -m dup -d single $D
udevadm settle
NEW_UUID=$(blkid -s UUID -o value $D)
echo "btrfs UUID: $NEW_UUID"

mkdir -p $BTR $NEW
mount -o $OPTS $D $BTR
btrfs -q subvolume create $BTR/@
btrfs -q subvolume create $BTR/@home
btrfs subvolume set-default $BTR/@
mount -o subvol=/@,$OPTS $D $NEW
mkdir -p $NEW/home
mount -o subvol=/@home,$OPTS $D $NEW/home

log "rsync pass 1 (live)"
rsync -aHAXx --numeric-ids --info=stats1 / $NEW/ | grep -E 'Number of files|Total file size' || true

log "rsync pass 2 (root frozen)"
sync
trap 'fsfreeze -u / 2>/dev/null || true' EXIT
fsfreeze -f /
rc=0
rsync -aHAXx --numeric-ids --delete --stats / $NEW/ > /dev/shm/t825-rsync2.log 2>&1 || rc=$?
fsfreeze -u /
trap - EXIT
log "root unfrozen (rsync rc=$rc)"
[ $rc -eq 0 ] || { tail -20 /dev/shm/t825-rsync2.log; exit 1; }

log "fstab"
sed -i "s|^UUID=$OLD_UUID / ext4 .*|UUID=$NEW_UUID / btrfs subvol=/@,$OPTS 0 0\nUUID=$NEW_UUID /home btrfs subvol=/@home,$OPTS 0 0|" $NEW/etc/fstab
grep -v '^#' $NEW/etc/fstab | grep -v '^$'
[ "$(grep -c "$NEW_UUID" $NEW/etc/fstab)" = 2 ] || { echo "fstab not updated" >&2; exit 1; }
chattr +C $NEW/var/log/journal 2>/dev/null || true
test -e $NEW/usr/lib/os-release
umount $NEW/home $NEW $BTR
rmdir $BTR $NEW

echo "$NEW_UUID" > /root/t825-btrfs-uuid
sync
log "done: btrfs UUID $NEW_UUID (also in /root/t825-btrfs-uuid); test it before switching lk2nd to it"
