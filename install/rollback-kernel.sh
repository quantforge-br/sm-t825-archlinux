#!/bin/bash
# Restore the previous Image.gz/initramfs and, for same-release installs, modules.
# Cross-release installs leave the old modules in place, so no archive is needed.
# Use the same ROOT as update-kernel.sh for an offline root.
set -euo pipefail
KVER=${KVER:-7.3.1-t825}
ROOT=${ROOT:-}
ROOT=${ROOT%/}
S=$ROOT/var/tmp/t825-kernel
mountpoint -q "$ROOT/boot" || { echo "$ROOT/boot is not mounted" >&2; exit 1; }
for f in "$ROOT/boot/vmlinuz-t825.prev" "$ROOT/boot/initramfs-t825.prev"; do
    test -s "$f" || { echo "missing or empty: $f" >&2; exit 1; }
done
if [ -f "$S/modules-prev.tar" ]; then
    # Metadata avoids guessing the release, including after a future upgrade.
    # KVER remains the fallback for backups created by the old script.
    if [ -f "$S/modules-version" ]; then
        KVER=$(cat "$S/modules-version")
    fi
    case "$KVER" in ''|.|..|*/*) echo "invalid backup KVER" >&2; exit 1;; esac
    tar -tf "$S/modules-prev.tar" | grep -Fx "$KVER/modules.dep" >/dev/null
    rm -rf "$ROOT/usr/lib/modules/$KVER"
    tar -C "$ROOT/usr/lib/modules" -xf "$S/modules-prev.tar"
    depmod -b "${ROOT:-/}" -a "$KVER"
fi
cp -a "$ROOT/boot/vmlinuz-t825.prev" "$ROOT/boot/vmlinuz-t825"
cp -a "$ROOT/boot/initramfs-t825.prev" "$ROOT/boot/initramfs-t825"
sync
echo "previous kernel restored; reboot"
