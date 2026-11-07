#!/bin/bash
# Install modules, Image.gz and initramfs; preserve the previous boot files for rollback.
# Different kernel releases keep separate module directories. Same-release reinstalls
# also save the modules they replace in /var/tmp/t825-kernel/modules-prev.tar.
#   sudo install/update-kernel.sh <modules.tar> <vmlinuz> <initramfs>
# modules.tar: "tar -C <package>/lib/modules -cf modules.tar 7.3.1-t825"
# ROOT may point at an offline root with its boot partition mounted (also useful for tests).
set -euo pipefail
mods=${1:?modules tar}; kernel=${2:?vmlinuz}; initramfs=${3:?initramfs}
KVER=${KVER:-7.3.1-t825}
ROOT=${ROOT:-}
ROOT=${ROOT%/}
S=$ROOT/var/tmp/t825-kernel
case "$KVER" in ''|.|..|*/*) echo "invalid KVER" >&2; exit 1;; esac
mountpoint -q "$ROOT/boot" || { echo "$ROOT/boot is not mounted" >&2; exit 1; }
# Read the full listing: grep -q could SIGPIPE tar under pipefail.
tar -tf "$mods" | grep -Fx "$KVER/modules.dep" >/dev/null || { echo "$mods has no $KVER/modules.dep" >&2; exit 1; }
for f in "$kernel" "$initramfs" "$ROOT/boot/vmlinuz-t825" "$ROOT/boot/initramfs-t825"; do
    test -s "$f" || { echo "missing or empty: $f" >&2; exit 1; }
done
mkdir -p "$S" "$ROOT/usr/lib/modules"
if [ -d "$ROOT/usr/lib/modules/$KVER" ]; then
    tar -C "$ROOT/usr/lib/modules" -cf "$S/modules-prev.tar" "$KVER"
else
    # First install of this release: the previous release's modules stay in place.
    # Discard an archive left by a previous, unrelated same-release reinstall.
    rm -f "$S/modules-prev.tar"
fi
printf '%s\n' "$KVER" > "$S/modules-version"
cp -a "$ROOT/boot/vmlinuz-t825" "$ROOT/boot/vmlinuz-t825.prev"
cp -a "$ROOT/boot/initramfs-t825" "$ROOT/boot/initramfs-t825.prev"
rm -rf "$ROOT/usr/lib/modules/$KVER"
tar -C "$ROOT/usr/lib/modules" --no-same-owner -xf "$mods"
depmod -b "${ROOT:-/}" -a "$KVER"
install -m644 "$kernel" "$ROOT/boot/vmlinuz-t825"
install -m644 "$initramfs" "$ROOT/boot/initramfs-t825"
sync
sha256sum "$ROOT/boot/vmlinuz-t825" "$ROOT/boot/initramfs-t825"
echo "installed; reboot. To go back: install/rollback-kernel.sh"
