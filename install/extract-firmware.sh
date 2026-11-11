#!/bin/bash
# Collect the firmware this tablet needs and nobody may redistribute, from raw dumps of its own
# partitions (install/backup-partitions.sh), into a firmware tree for build-arch-rootfs.sh.
# Same selection as gts3-firmware in the pmaports device package:
#   apnhlos: GPU zap shader, Venus (video) and SLPI (sensor hub) firmware, Samsung-signed
#   modem:   ADSP (audio DSP) firmware, Samsung-signed; with EXTRACT_MSS=1,
#            the MSS MBA/modem image and modem_pr tree for a diagnostic GNSS
#            build (never enabled by the production DTB)
#   system:  Wi-Fi board data (Android's bdwlan30.bin -> ath10k board.bin)
#   efs:     sensor registry with this unit's factory calibration
# Run as root (loop mounts, all read-only; ext4 with noload so no journal is replayed):
#   install/extract-firmware.sh <dump dir with apnhlos.img modem.img system.img efs.img> <out dir>
set -euo pipefail
umask 077
dumps=${1:?dump directory}
out=${2:?output directory}
model=${MODEL:-samsung,gts3llte}
extract_mss=${EXTRACT_MSS:-0}
case "$extract_mss" in
	0|1) ;;
	*) echo "EXTRACT_MSS must be 0 or 1" >&2; exit 2 ;;
esac
fw=$out/qcom/msm8996/samsung/gts3
mnt=$(mktemp -d)
trap 'mountpoint -q "$mnt" && umount "$mnt"; rmdir "$mnt"' EXIT
mkdir -p "$fw"

mount -o loop,ro "$dumps/apnhlos.img" "$mnt"
for stem in a530_zap venus slpi; do
	for f in "$mnt"/image/"$stem".*; do
		[ -f "$f" ] || continue
		install -Dvm600 "$f" "$fw/${f##*/}"
	done
done
umount "$mnt"

mount -o loop,ro "$dumps/modem.img" "$mnt"
for f in "$mnt"/image/adsp.*; do
	[ -f "$f" ] || continue
	install -Dvm600 "$f" "$fw/${f##*/}"
done
if [[ "$extract_mss" == 1 ]]; then
	# The MSS firmware is Samsung-signed and must stay private.  Keep the
	# paths relative to image/: the DT requests modem.mdt and the remoteproc
	# loader follows the accompanying modem.b* segments.  modem_pr is served
	# over QRTR TFTP by tqftpserv after rmtfs has started the DSP.
	[[ -f "$mnt/image/mba.mbn" ]] || { echo "MSS firmware missing: mba.mbn" >&2; exit 1; }
	[[ -f "$mnt/image/modem.mdt" ]] || { echo "MSS firmware missing: modem.mdt" >&2; exit 1; }
	shopt -s nullglob
	modem_segments=("$mnt"/image/modem.b*)
	(( ${#modem_segments[@]} > 0 )) || { echo "MSS firmware missing: modem.b*" >&2; exit 1; }
	[[ -d "$mnt/image/modem_pr" ]] || { echo "MSS firmware missing: modem_pr/" >&2; exit 1; }
	for f in "$mnt"/image/mba.mbn "$mnt"/image/modem.*; do
		[[ -f "$f" ]] && install -Dvm600 "$f" "$fw/${f##*/}"
	done
	# `find` emits absolute paths here because the image is mounted at a
	# temporary directory. Strip that prefix before constructing the output
	# path; otherwise the absolute name would be concatenated below $fw and
	# the modem_pr tree would never be served at its expected relative path.
	while IFS= read -r -d '' f; do
		rel=${f#"$mnt/image/"}
		dest=$fw/$rel
		install -d -m755 "$(dirname "$dest")"
		install -m600 "$f" "$dest"
	done < <(find "$mnt/image/modem_pr" -type f -print0 2>/dev/null)
fi
umount "$mnt"

mount -o loop,ro,noload "$dumps/system.img" "$mnt"
board=
# Stock Samsung firmware keeps it in etc/firmware; system-as-root ROMs (LineageOS and others)
# in system/vendor/firmware.
for f in etc/firmware vendor/firmware system/etc/firmware system/vendor/firmware; do
	[ -z "$board" ] && [ -f "$mnt/$f/bdwlan30.bin" ] && board=$mnt/$f/bdwlan30.bin
done
[ -n "$board" ] || { echo "bdwlan30.bin not found in system.img" >&2; exit 1; }
install -Dvm600 "$board" "$out/ath10k/QCA6174/hw3.0/board.bin"
umount "$mnt"

mount -o loop,ro,noload "$dumps/efs.img" "$mnt"
install -Dvm600 "$mnt/FactoryApp/sensors/sns.reg" "$out/qcom/sensors/sns.reg-$model"
umount "$mnt"

# Keep this tree private: it contains Samsung firmware and unit calibration.
# Directory traversal is available to the owner, while firmware files are
# readable only by the owner until the image builder installs them in a rootfs.
find "$out" -type d -exec chmod 700 {} +
find "$out" -type f -exec chmod 600 {} +
find "$out" -type f | sort | sed "s|^$out/||" > "$out/MANIFEST.txt"
echo "$(wc -l < "$out/MANIFEST.txt") files in $out (keep them private; they are not redistributable)"
