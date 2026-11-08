#!/bin/bash
# Install modules, Image.gz, initramfs and optionally the matching SM-T825 DTB.
# sudo install/update-kernel.sh <modules.tar> <vmlinuz> <initramfs> [gts3llte.dtb]
# modules.tar: "tar -C <package>/lib/modules -cf modules.tar 7.3.1-t825"
# ROOT redirects to an offline root with its boot partition mounted.
set -euo pipefail
for tool in grep tar depmod mountpoint mktemp cp chmod sync mv stat df tail rm mkdir cat gzip awk sha256sum wc head od; do
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
LK2ND_BOOT_MEM_SIZE=${LK2ND_BOOT_MEM_SIZE:-52428800}
if [[ ! "$LK2ND_BOOT_MEM_SIZE" =~ ^[1-9][0-9]{0,9}$ ]] ||
   ((LK2ND_BOOT_MEM_SIZE > 4294967295)); then
    echo "LK2ND_BOOT_MEM_SIZE must be a positive byte count <= 4294967295" >&2
    exit 1
fi
# lk2nd fd380ac6 extlinux.c:578-595 compares the decompressor's output
# count, not image_size. Validate the complete stream before reading its header.
# gzip -dc counts all members; lk2nd inflates only the first (conservative).
if ! kernel_size=$(gzip -dc -- "$kernel" | wc -c); then
    echo "cannot decompress $kernel to check the lk2nd size limit" >&2
    exit 1
fi
ramdisk_size=$(stat -Lc %s "$initramfs")
if ((ramdisk_size >= LK2ND_BOOT_MEM_SIZE)); then
    echo "lk2nd budget refused: initramfs=$ramdisk_size >= boot_mem=$LK2ND_BOOT_MEM_SIZE; rounddown($LK2ND_BOOT_MEM_SIZE - $ramdisk_size, 4096) - 2097152 - kernel_offset cannot yield a positive budget; refusing before any mutation" >&2
    exit 1
fi
# choose_addrs() in extlinux.c:489-535 uses the first 64-byte Image header.
# Drain the remainder after head so gzip cannot SIGPIPE under pipefail.
# Bytewise decoding avoids host endianness and unsigned 64-bit shell overflow.
if ! header_bytes=$(gzip -dc -- "$kernel" | { head -c 64 | od -An -v -tu1; cat >/dev/null; }); then
    echo "cannot decompress $kernel to read its lk2nd header" >&2
    exit 1
fi
header_bytes=${header_bytes//$'\n'/ }
read -r -a header <<< "$header_bytes"
if ((${#header[@]} != 64)); then
    echo "cannot read the first 64 bytes of the decompressed kernel" >&2
    exit 1
fi
text_offset=$((header[8] | (header[9] << 8) | (header[10] << 16)))
text_offset_high=0
image_size_nonzero=0
for ((i=0; i<8; i++)); do
    image_size_nonzero=$((image_size_nonzero | header[16+i]))
done
for ((i=11; i<16; i++)); do
    text_offset_high=$((text_offset_high | header[i]))
done
if ((header[56] == 65 && header[57] == 82 && header[58] == 77 && header[59] == 100)); then
    if ((image_size_nonzero != 0)); then
        kernel_offset=$text_offset
    else
        kernel_offset=$((0x80000))
    fi
    if ((text_offset_high != 0 || text_offset > 2 * 1024 * 1024)); then
        kernel_offset=0
    fi
else
    kernel_offset=$((0x8000))
fi
ramdisk_offset=$(((LK2ND_BOOT_MEM_SIZE - ramdisk_size) / 4096 * 4096))
tags_offset=$((ramdisk_offset - 2 * 1024 * 1024))
budget=$((tags_offset - kernel_offset))
if ((budget <= 0)); then
    echo "lk2nd budget refused: rounddown($LK2ND_BOOT_MEM_SIZE - $ramdisk_size, 4096) - 2097152 - $kernel_offset = $ramdisk_offset - 2097152 - $kernel_offset = $budget; refusing before any mutation" >&2
    exit 1
fi
effective=$budget
if [[ -n "${LK2ND_MAX_KERNEL_SIZE:-}" ]]; then
    if [[ ! "$LK2ND_MAX_KERNEL_SIZE" =~ ^[1-9][0-9]{0,9}$ ]] ||
       ((LK2ND_MAX_KERNEL_SIZE > 4294967295)); then
        echo "LK2ND_MAX_KERNEL_SIZE must be a positive byte count <= 4294967295" >&2
        exit 1
    fi
    if ((LK2ND_MAX_KERNEL_SIZE < effective)); then effective=$LK2ND_MAX_KERNEL_SIZE; fi
fi
echo "lk2nd budget: rounddown($LK2ND_BOOT_MEM_SIZE - $ramdisk_size, 4096) - 2097152 - $kernel_offset = $ramdisk_offset - 2097152 - $kernel_offset = $budget; cap=${LK2ND_MAX_KERNEL_SIZE:-none}; effective=$effective; kernel=$kernel_size" >&2
if ((kernel_size > effective)); then
    echo "kernel too big for lk2nd extlinux: $kernel_size decompressed bytes > effective limit $effective; refusing before any mutation" >&2
    exit 1
fi
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
# The DTB has its own fixed reservation; it does not reduce the kernel budget.
if [[ -n "$dtb" ]]; then
    dtb_size=$(stat -Lc %s "$dtb")
    if ((dtb_size >= 2097152)); then
        echo "DTB too big for lk2nd: $dtb_size bytes >= MAX_TAGS_SIZE=2097152; refusing before any mutation" >&2
        exit 1
    fi
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
    # Modules are already live; cleanup failure must not prevent publishing
    # their matching boot files. A leftover .old blocks the next swap.
    if ! rm -rf -- "$module_old"; then
        echo "warning: could not remove $module_old; continuing with matching boot files; inspect the leftover directory before another update or rollback" >&2
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
stage_modules "$mods"
mkdir -p "$S"
archive=
if [[ "$previous" == "$KVER" && -d "$ROOT/usr/lib/modules/$KVER" ]]; then
    # Stage the archive too: a failed tar must not truncate a valid backup.
    archive=$(mktemp "$S/modules-prev.tar.XXXXXX.tmp")
    temps+=("$archive")
    tar -C "$ROOT/usr/lib/modules" -cf "$archive" "$KVER"
    metadata=$(mktemp "$S/modules-version.XXXXXX.tmp")
    temps+=("$metadata")
    printf '%s\n' "$KVER" > "$metadata"
    binding=$(mktemp "$S/modules-binding.XXXXXX.tmp")
    temps+=("$binding")
    # Bind both artifacts so interruption between archive and metadata renames
    # cannot silently pair a new archive with an old generation marker.
    boot_hash=$(sha256sum "${temps[backups[0]]}")
    archive_hash=$(sha256sum "$archive")
    printf '%s\n%s\n%s\n' "$KVER" "${boot_hash%% *}" "${archive_hash%% *}" > "$binding"
fi
publish "${backups[@]}"
# Publish module backup state only after the matching boot backups. A failure
# publishing boot backups must not advance or discard the old module archive.
if [[ -n "$archive" ]]; then
    sync
    mv -fT -- "$archive" "$S/modules-prev.tar"
    mv -fT -- "$metadata" "$S/modules-version"
    mv -fT -- "$binding" "$S/modules-binding"
    sync
else
    # Staged new-release modules are a first install, not the previous kernel.
    rm -f "$S/modules-prev.tar" "$S/modules-version" "$S/modules-binding"
fi
# Without a DTB argument, the installed DTB stays in place. Drop an unrelated
# old backup so rollback cannot restore a DTB from an earlier update.
if [[ -z "$dtb" ]]; then rm -f "$D.prev"; fi
swap_modules
publish "${replacements[@]}"
sha256sum "${files[@]}"
echo "installed; reboot. To go back: install/rollback-kernel.sh"
