#!/usr/bin/env bash
# Build a RAM-only reset proof. No root filesystem, modem, or partitions are used.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: make-recovery-proof-image.sh OUTPUT_DIRECTORY}
: "${T825_KERNEL:?set T825_KERNEL to the diagnostic Image.gz}"
: "${T825_DTB_DIR:?set T825_DTB_DIR to a directory containing qcom/*.dtb}"
: "${T825_BUILD_ROOT:?set T825_BUILD_ROOT to the prepared aarch64 rootfs}"
mode=${T825_PROOF_MODE:-timeout}
case "$mode" in timeout|handoff) ;; *) echo 'invalid proof mode' >&2; exit 2 ;; esac
[ ! -e "$out/root" ] || { echo 'use a fresh proof output directory' >&2; exit 2; }
mkdir -p "$out/root/bin" "$out/root/lib" "$out/root/proc" "$out/root/sys" \
    "$out/root/dev" "$out/root/run"
"$here/tools/build-t825-recovery-supervisor.sh" "$out/root/bin/t825-recovery"
cp "$T825_BUILD_ROOT/usr/bin/busybox" "$out/root/bin/busybox"
cp -L "$T825_BUILD_ROOT/lib/ld-musl-aarch64.so.1" "$out/root/lib/ld-musl-aarch64.so.1"
ln -sfn ld-musl-aarch64.so.1 "$out/root/lib/libc.musl-aarch64.so.1"
cat > "$out/root/init" <<'INIT'
#!/bin/busybox ash
export PATH=/bin
/bin/busybox --install -s /bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mount -t tmpfs tmpfs /run
mkdir -p /run/t825-recovery
echo 'T825 recovery-only proof: no partitions mounted; reset in 30 seconds'
/bin/t825-recovery 30 /run/t825-recovery &
echo "$!" > /run/t825-recovery/supervisor.pid
sleep 1
kill -0 "$(cat /run/t825-recovery/supervisor.pid)" || exit 1
if [ -x /handoff ]; then
    exec /handoff
fi
while :; do sleep 1; done
INIT
if [ "$mode" = handoff ]; then
    cat > "$out/root/handoff" <<'HANDOFF'
#!/bin/busybox ash
set -eu
mkdir /newroot
mount -t tmpfs tmpfs /newroot
mkdir -p /newroot/bin /newroot/sbin /newroot/lib /newroot/run /newroot/proc /newroot/sys /newroot/dev
cp /bin/busybox /newroot/bin/busybox
cp -L /lib/ld-musl-aarch64.so.1 /newroot/lib/ld-musl-aarch64.so.1
ln -s ld-musl-aarch64.so.1 /newroot/lib/libc.musl-aarch64.so.1
cp /second-init /newroot/sbin/init
mount --move /run /newroot/run
# Match the pmOS shell cleanup that killed earlier shell-based watchdogs.
for pid in $(pidof sh); do
    [ "$pid" = 1 ] || kill -9 "$pid"
done
mount --move /proc /newroot/proc
mount --move /sys /newroot/sys
mount --move /dev /newroot/dev
exec switch_root /newroot /sbin/init
HANDOFF
    cat > "$out/root/second-init" <<'SECOND'
#!/bin/busybox ash
set -eu
export PATH=/bin
/bin/busybox --install -s /bin
# A lease is issued only after a real switch_root, deletion of the old binary,
# transfer of /run, and survival of the original supervisor process.
[ "$$" = 1 ]
[ ! -e /bin/t825-recovery ]
kill -0 "$(cat /run/t825-recovery/supervisor.pid)"
grep -q 'armed at' /run/t825-recovery/supervisor.log
read -r uptime rest < /proc/uptime
printf '%s\n' "$(( ${uptime%.*} + 60 ))" > /run/t825-recovery/lease
echo 'switch_root passed: original supervisor owns recovery; lease extended 60s'
while :; do sleep 1; done
SECOND
    chmod +x "$out/root/handoff" "$out/root/second-init"
fi
chmod +x "$out/root/init"
(cd "$out/root"; find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --owner=0:0 2>/dev/null) |
    zstd -q -T1 -o "$out/initramfs" -f
KERNEL="$T825_KERNEL" INITRAMFS="$out/initramfs" DTB_DIR="$T825_DTB_DIR" \
    "$here/install/make-boot-image.sh" "$out/recovery-proof.img"
sha256sum "$out/recovery-proof.img" "$out/initramfs" "$out/root/bin/t825-recovery" > "$out/SHA256SUMS"
