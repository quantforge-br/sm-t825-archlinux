#!/bin/sh
# Copy private T825 calibration images into the volatile rmtfs directory.
# This is deliberately narrower than msm-cros-efs-loader: it never reads
# boot0/EFS, creates zero-filled files, or removes a previous calibration.
# The private input keeps the source names modem_fs1/modem_fs2/modem_fsg/modem_fsc;
# rmtfs consumes the canonical volatile names modemst1/modemst2/fsg/fsc.
set -eu

src=${T825_MSS_CALIBRATION_DIR:-/usr/lib/t825-mss-diag}
dst=${T825_RMTFS_DIR:-/run/rmtfs}

case "$src" in
	/run/*|/usr/lib/t825-mss-diag) ;;
	*) echo "refusing non-private calibration source: $src" >&2; exit 1 ;;
esac
case "$dst" in
	/run/*) ;;
	*) echo "refusing non-volatile rmtfs destination: $dst" >&2; exit 1 ;;
esac
case "$src:$dst" in
	*..*) echo "refusing path traversal in calibration paths" >&2; exit 1 ;;
esac

[ -d "$src" ] || { echo "calibration source is missing: $src" >&2; exit 1; }
install -d -m 700 "$dst"
tmp="$dst/.t825-calibration.$$"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT INT TERM
install -d -m 700 "$tmp"

for spec in modemst1:modem_fs1 modemst2:modem_fs2 fsg:modem_fsg fsc:modem_fsc; do
	name=${spec%%:*}
	source_name=${spec#*:}
	file="$src/$source_name"
	[ -f "$file" ] || { echo "missing calibration image: $file" >&2; exit 1; }
	[ ! -L "$file" ] || { echo "symlink calibration image rejected: $file" >&2; exit 1; }
	mode=$(stat -c '%a' "$file")
	[ $((mode % 100)) -eq 0 ] || {
		echo "calibration image is not owner-only: $file mode=$mode" >&2
		exit 1
	}
	install -m 600 "$file" "$tmp/$name"
done

# Publish each complete file atomically. Existing files are replaced only after
# the private copy succeeds; no source partition is opened by this helper.
for name in modemst1 modemst2 fsg fsc; do
	mv -f "$tmp/$name" "$dst/$name"
done
trap - EXIT INT TERM
rm -rf "$tmp"
