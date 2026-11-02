#!/bin/bash
# Collect the firmware this tablet needs and nobody may redistribute, from raw dumps of its own
# partitions (install/backup-partitions.sh), into a firmware tree for build-arch-rootfs.sh.
# Same selection as gts3-firmware in the pmaports device package:
#   apnhlos: GPU zap shader, Venus (video) and SLPI (sensor hub) firmware, Samsung-signed
#   modem:   ADSP (audio DSP) firmware, Samsung-signed
#   system:  Wi-Fi board data (Android's bdwlan30.bin -> ath10k board.bin)
#   efs:     sensor registry with this unit's factory calibration
# Run as root (loop mounts, all read-only; ext4 with noload so no journal is replayed):
#   install/extract-firmware.sh <dump dir with apnhlos.img modem.img system.img efs.img> <out dir>
set -euo pipefail
dumps=${1:?dump directory}
out=${2:?output directory}
model=${MODEL:-samsung,gts3llte}
fw=$out/qcom/msm8996/samsung/gts3
mnt=$(mktemp -d)
trap 'mountpoint -q "$mnt" && umount "$mnt"; rmdir "$mnt"' EXIT
mkdir -p "$fw"

mount -o loop,ro "$dumps/apnhlos.img" "$mnt"
cp -v "$mnt"/image/a530_zap.* "$mnt"/image/venus.* "$mnt"/image/slpi.* "$fw/"
umount "$mnt"

mount -o loop,ro "$dumps/modem.img" "$mnt"
cp -v "$mnt"/image/adsp.* "$fw/"
umount "$mnt"

mount -o loop,ro,noload "$dumps/system.img" "$mnt"
board=
# Stock Samsung firmware keeps it in etc/firmware; system-as-root ROMs (LineageOS and others)
# in system/vendor/firmware.
for f in etc/firmware vendor/firmware system/etc/firmware system/vendor/firmware; do
	[ -z "$board" ] && [ -f "$mnt/$f/bdwlan30.bin" ] && board=$mnt/$f/bdwlan30.bin
done
[ -n "$board" ] || { echo "bdwlan30.bin not found in system.img" >&2; exit 1; }
install -Dvm644 "$board" "$out/ath10k/QCA6174/hw3.0/board.bin"
umount "$mnt"

mount -o loop,ro,noload "$dumps/efs.img" "$mnt"
install -Dvm644 "$mnt/FactoryApp/sensors/sns.reg" "$out/qcom/sensors/sns.reg-$model"
umount "$mnt"

chmod 644 "$fw"/*
find "$out" -type f | sort | sed "s|^$out/||" > "$out/MANIFEST.txt"
echo "$(wc -l < "$out/MANIFEST.txt") files in $out (keep them private; they are not redistributable)"
