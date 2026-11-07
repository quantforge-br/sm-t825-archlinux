#!/bin/bash
# Install modules, Image.gz, initramfs and optionally the matching SM-T825 DTB.
# sudo install/update-kernel.sh <modules.tar> <vmlinuz> <initramfs> [gts3llte.dtb]
# modules.tar: "tar -C <package>/lib/modules -cf modules.tar 7.3.1-t825"
# ROOT redirects to an offline root with its boot partition mounted.
set -euo pipefail
for tool in grep tar depmod mountpoint mktemp cp chmod sync mv stat df tail rm mkdir cat gzip awk sha256sum; do
    command -v "$tool" >/dev/null || { echo "missing required command: $tool" >&2; exit 1; }
done
mods=${1:?modules tar}; kernel=${2:?vmlinuz}; initramfs=${3:?initramfs}; dtb=${4:-}
KVER=${KVER:-7.3.1-t825}
ROOT=${ROOT:-}
ROOT=${ROOT%/}
S=$ROOT/var/tmp/t825-kernel
D=$ROOT/boot/dtbs/qcom/msm8996-samsung-gts3llte.dtb
case "$KVER" in ''|.|..|*/*) echo "invalid KVER" >&2; exit 1;; esac
mountpoint -q "$ROOT/boot" || { echo "$ROOT/boot is not mounted" >&2; exit 1; }
# Consume the full streams: early exits could SIGPIPE gzip/tar under pipefail.
tar -tf "$mods" | grep -Fx "$KVER/modules.dep" >/dev/null || { echo "$mods has no $KVER/modules.dep" >&2; exit 1; }
release() {
    # grep scans binary data directly; binutils/strings is not required.
    # Do not use grep -m1: consume gzip fully so CRC/truncation errors propagate.
    LC_ALL=C gzip -dc -- "$1" | LC_ALL=C grep -ao 'Linux version [^[:space:][:cntrl:]]* ' | awk '
        !release {release=$3}
        END {if (release) print release; else exit 1}'
}
if ! incoming=$(release "$kernel") || [[ "$incoming" != "$KVER" ]]; then
    echo "$kernel does not contain Linux version $KVER" >&2
    exit 1
fi
# The installed kernel becomes .prev. Do not infer its release from staged
# modules or uname (which may identify a RAM test kernel or an offline host).
if ! previous=$(release "$ROOT/boot/vmlinuz-t825"); then
    echo "cannot identify release of $ROOT/boot/vmlinuz-t825" >&2
    exit 1
fi
files=("$ROOT/boot/vmlinuz-t825" "$ROOT/boot/initramfs-t825")
inputs=("$kernel" "$initramfs")
if [[ -n "$dtb" ]]; then
    files+=("$D")
    inputs+=("$dtb")
fi
for f in "${files[@]}" "${inputs[@]}"; do
    test -s "$f" || { echo "missing or empty: $f" >&2; exit 1; }
done
# Stage every copy before publishing any of them. Each rename stays on /boot.
# This protects individual files against failed copies, not a whole power-loss transaction.
temps=()
targets=()
cleanup() { if ((${#temps[@]})); then rm -f -- "${temps[@]}"; fi; }
trap cleanup EXIT
stage() {
    local tmp
    tmp=$(mktemp "$2.XXXXXX.tmp")
    temps+=("$tmp")
    targets+=("$2")
    cp -- "$1" "$tmp"
    chmod 644 "$tmp"
}
publish() {
    local index
    sync
    for index in "$@"; do
        mv -fT -- "${temps[index]}" "${targets[index]}"
    done
    sync
}
# Allow space for all staged files plus filesystem overhead, without relying on
# space reclaimed by replacing a previous backup. Fail before writing anything.
check_space() {
    local bytes=1048576 size file available block
    block=$(stat -f -c %S "$ROOT/boot")
    for file in "$@"; do
        size=$(stat -Lc %s "$file")
        bytes=$((bytes + (size + block - 1) / block * block))
    done
    available=$(df -B1 --output=avail "$ROOT/boot" | tail -n 1)
    if ((available < bytes)); then
        echo "not enough free space on $ROOT/boot: need $bytes bytes, available $available" >&2
        exit 1
    fi
}
check_space "${files[@]}" "${inputs[@]}"
# Backups first, then replacements; no destination changes until all copies succeed.
backups=()
replacements=()
for index in "${!files[@]}"; do
    backups+=("${#temps[@]}")
    stage "${files[index]}" "${files[index]}.prev"
    replacements+=("${#temps[@]}")
    stage "${inputs[index]}" "${files[index]}"
done
mkdir -p "$S" "$ROOT/usr/lib/modules"
if [[ "$previous" == "$KVER" && -d "$ROOT/usr/lib/modules/$KVER" ]]; then
    # Stage the archive too: a failed tar must not truncate a valid backup.
    archive=$(mktemp "$S/modules-prev.tar.XXXXXX.tmp")
    temps+=("$archive")
    tar -C "$ROOT/usr/lib/modules" -cf "$archive" "$KVER"
    sync
    mv -fT -- "$archive" "$S/modules-prev.tar"
    metadata=$(mktemp "$S/modules-version.XXXXXX.tmp")
    temps+=("$metadata")
    printf '%s\n' "$KVER" > "$metadata"
    sync
    mv -fT -- "$metadata" "$S/modules-version"
else
    # A staged new-release directory is still a first install. Old-release
    # modules stay in place, so neither archive nor release metadata is needed.
    rm -f "$S/modules-prev.tar" "$S/modules-version"
fi
publish "${backups[@]}"
# Without a DTB argument, the installed DTB stays in place. Drop an unrelated
# old backup so rollback cannot restore a DTB from an earlier update.
if [[ -z "$dtb" ]]; then rm -f "$D.prev"; fi
rm -rf "$ROOT/usr/lib/modules/$KVER"
tar -C "$ROOT/usr/lib/modules" --no-same-owner -xf "$mods"
depmod -b "${ROOT:-/}" -a "$KVER"
publish "${replacements[@]}"
sha256sum "${files[@]}"
echo "installed; reboot. To go back: install/rollback-kernel.sh"
