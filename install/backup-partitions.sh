#!/bin/bash
# Raw dumps of the partitions to keep (and the ones the firmware comes from), taken with adb from
# TWRP before anything is written. Streams with "adb exec-out", so nothing has to fit in TWRP's
# RAM-backed /tmp. Compares a SHA-256 taken on the tablet with the local copy.
#   install/backup-partitions.sh <output dir>
# EFS, modemst1/2 and persist hold this unit's IMEI, calibration and keys: keep them safe and
# private. system is 4 GB; only bdwlan30.bin is used from it (install/extract-firmware.sh).
set -euo pipefail
out=${1:?output directory}
parts=${PARTS:-efs modemst1 modemst2 persist param boot recovery apnhlos modem dsp system}
mkdir -p "$out"
adb get-state >/dev/null
for p in $parts; do
	dev=/dev/block/bootdevice/by-name/$p
	adb shell "test -e $dev" || { echo "skip $p (no $dev)"; continue; }
	echo "== $p"
	adb exec-out "dd if=$dev bs=4194304 2>/dev/null" > "$out/$p.img"
	remote=$(adb shell "sha256sum $dev" | cut -d' ' -f1)
	local_=$(sha256sum "$out/$p.img" | cut -d' ' -f1)
	echo "$local_  $p.img" >> "$out/SHA256SUMS"
	[ "$remote" = "$local_" ] && echo "ok $p $(stat -c %s "$out/$p.img") bytes" || { echo "HASH MISMATCH $p"; exit 1; }
done
