#!/bin/bash
# Restore the previous kernel, initramfs, optional DTB and same-release modules.
# Cross-release installs leave old modules in place, so no archive is needed.
# Use the same ROOT as update-kernel.sh for an offline root.
set -euo pipefail
for tool in grep tar depmod mountpoint mktemp cp chmod sync mv stat df tail rm mkdir cat; do
    command -v "$tool" >/dev/null || { echo "missing required command: $tool" >&2; exit 1; }
done
KVER=${KVER:-7.3.1-t825}
ROOT=${ROOT:-}
ROOT=${ROOT%/}
S=$ROOT/var/tmp/t825-kernel
D=$ROOT/boot/dtbs/qcom/msm8996-samsung-gts3llte.dtb
mountpoint -q "$ROOT/boot" || { echo "$ROOT/boot is not mounted" >&2; exit 1; }
files=("$ROOT/boot/vmlinuz-t825" "$ROOT/boot/initramfs-t825")
if [[ -e "$D.prev" ]]; then files+=("$D"); fi
sources=()
for f in "${files[@]}"; do
    test -s "$f.prev" || { echo "missing or empty: $f.prev" >&2; exit 1; }
    sources+=("$f.prev")
done
if [ -f "$S/modules-prev.tar" ]; then
    # KVER is the fallback for backups created by the legacy script.
    if [ -f "$S/modules-version" ]; then KVER=$(cat "$S/modules-version"); fi
    case "$KVER" in ''|.|..|*/*) echo "invalid backup KVER" >&2; exit 1;; esac
    tar -tf "$S/modules-prev.tar" | grep -Fx "$KVER/modules.dep" >/dev/null || {
        echo "modules-prev.tar has no $KVER/modules.dep (set KVER=<previous-release> for a legacy backup)" >&2
        exit 1
    }
fi
# Stage every copy before publishing any of them. Each rename stays on /boot.
# This protects individual files against failed copies, not a whole power-loss transaction.
temps=()
targets=()
module_stage=
module_old=
module_live=
cleanup() {
    local result=$?
    # A failed/interrupted second rename must put the original directory back.
    if [[ -n "$module_old" && -d "$module_old" && ! -e "$module_live" ]]; then
        mv -T -- "$module_old" "$module_live" || {
            echo "restore $module_old to $module_live before rebooting" >&2
            result=1
        }
    fi
    if [[ -n "$module_stage" ]]; then rm -rf -- "$module_stage"; fi
    if ((${#temps[@]})); then rm -f -- "${temps[@]}"; fi
    return "$result"
}
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
# Keep staging and saved directories on the module filesystem. A private root
# layout lets depmod generate indexes before any installed modules are moved.
stage_modules() {
    local parent=$ROOT/usr/lib/modules candidate
    module_live=$parent/$KVER
    candidate=$parent/.$KVER.new
    if [[ -e "$candidate" || -L "$candidate" || -e "$parent/.$KVER.old" || -L "$parent/.$KVER.old" ]]; then
        echo "unfinished module swap: inspect $candidate and $parent/.$KVER.old before retrying" >&2
        exit 1
    fi
    mkdir -p "$parent"
    mkdir "$candidate"
    module_stage=$candidate
    mkdir -p "$module_stage/lib/modules"
    tar -C "$module_stage/lib/modules" --no-same-owner -xf "$1" "$KVER"
    depmod -b "$module_stage" -m /lib/modules -a "$KVER"
}
swap_modules() {
    module_old=$ROOT/usr/lib/modules/.$KVER.old
    if [[ -e "$module_live" ]]; then mv -T -- "$module_live" "$module_old"; fi
    # cleanup restores .old if this fails, including an EXIT after the first mv.
    mv -T -- "$module_stage/lib/modules/$KVER" "$module_live"
    rm -rf -- "$module_old"
}
check_space "${sources[@]}"
for index in "${!files[@]}"; do stage "${sources[index]}" "${files[index]}"; done
if [ -f "$S/modules-prev.tar" ]; then
    stage_modules "$S/modules-prev.tar"
    echo "restoring modules: KVER=$KVER path=$module_live"
    swap_modules
fi
publish "${!targets[@]}"
echo "previous kernel restored; reboot"
