#!/bin/bash
# Write an image file to one partition of the tablet's eMMC through the postmarketOS initramfs
# debug shell (USB network 172.16.42.1, telnet on port 23).
#
# Boot the shell first, from lk2nd's fastboot:
#   fastboot boot release/boot-debug-shell-6.19.5-r8.img
# then:
#   install/flash-partition.sh out/arch-gts3llte-root.ext4 system
#   install/flash-partition.sh out/arch-boot-cache.ext2 cache
#
# The shell looks the partition up by name (PARTNAME in sysfs), refuses images larger than the
# partition and compares the SHA-256 of what landed on the eMMC with the image. Only partitions
# this install replaces are accepted.
set -euo pipefail
img=${1:?usage: flash-partition.sh <image> <system|cache|userdata|hidden>}
part=${2:?partition name}
host=${T825_HOST:-172.16.42.1}
port=5557
case "$part" in system|cache|userdata|hidden) ;; *) echo "refusing to write '$part'" >&2; exit 1 ;; esac
size=$(stat -c %s "$img")
want=$(sha256sum "$img" | cut -d' ' -f1)
log=$(mktemp)
fifo=$(mktemp -u)
mkfifo "$fifo"
ncpid=
cleanup() {
	{ printf 'exit\n' >&3; exec 3>&-; } 2>/dev/null || true
	[ -z "$ncpid" ] || kill "$ncpid" 2>/dev/null || true
	rm -f "$log" "$fifo"
}
trap cleanup EXIT

# Runs in busybox sh on the tablet. The markers are split with '' so that the telnet echo of
# this command line never matches them.
remote="dev=; for u in /sys/class/block/mmcblk0p*/uevent; do grep -qx PARTNAME=$part \$u && dev=/dev/\$(basename \$(dirname \$u)); done; \
[ -n \"\$dev\" ] || { echo NO_''PARTITION; exit; }; \
psize=\$(( \$(cat /sys/class/block/\$(basename \$dev)/size) * 512 )); echo TAR''GET \$dev \$psize; \
[ $size -le \$psize ] || { echo TOO_''BIG; exit; }; echo REA''DY; \
nc -l -p $port < /dev/null | gzip -dc > \$dev; echo WRITE_''RC \$?; sync; \
echo HASH_''IS \$(head -c $size \$dev | sha256sum | cut -d' ' -f1); echo HASH_''DONE"

# The telnet session reads from a FIFO held open on fd 3 until cleanup.
nc "$host" 23 < "$fifo" > "$log" 2>&1 &
ncpid=$!
exec 3> "$fifo"
printf '%s\n' "$remote" >&3
for _ in $(seq 1 60); do grep -qE 'READY|NO_PARTITION|TOO_BIG' "$log" && break; sleep 0.5; done
grep -E '^TARGET ' "$log" || true
if ! grep -q READY "$log"; then echo "tablet side not ready:"; cat "$log"; exit 1; fi
sleep 1

start=$(date +%s)
echo "sending $img ($size bytes) to $part"
gzip -1 -c "$img" | nc -N "$host" "$port"
for _ in $(seq 1 720); do grep -q HASH_DONE "$log" && break; sleep 5; done
echo "elapsed: $(( $(date +%s) - start )) s"
grep -E 'WRITE_RC [0-9]' "$log" || true
got=$(grep -oE 'HASH_IS [0-9a-f]{64}' "$log" | cut -d' ' -f2 || true)
echo "image:     $want"
echo "partition: $got"
[ "$got" = "$want" ] && echo FLASH_OK || { echo "MISMATCH"; exit 1; }
