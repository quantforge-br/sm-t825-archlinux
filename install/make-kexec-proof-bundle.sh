#!/usr/bin/env bash
# Build the smallest nonpersistent kexec candidate used to isolate the
# pre-supervisor handoff from the normal direct-root diagnostics.  The image
# mounts no persistent filesystem and arms the static supervisor as soon as
# the initramfs has proc/sys/dev/run available.
set -euo pipefail
export LC_ALL=C

out=${1:?usage: make-kexec-proof-bundle.sh OUTPUT_DIRECTORY}
kernel=${T825_KEXEC_PROOF_KERNEL:?set T825_KEXEC_PROOF_KERNEL to Image.gz}
dtb=${T825_KEXEC_PROOF_DTB:?set T825_KEXEC_PROOF_DTB to the LTE DTB}
busybox=${T825_KEXEC_PROOF_BUSYBOX:?set T825_KEXEC_PROOF_BUSYBOX to aarch64 busybox}
loader=${T825_KEXEC_PROOF_LOADER:?set T825_KEXEC_PROOF_LOADER to ld-musl-aarch64.so.1}
supervisor=${T825_KEXEC_PROOF_SUPERVISOR:?set T825_KEXEC_PROOF_SUPERVISOR to the static supervisor}
seconds=${T825_KEXEC_PROOF_SECONDS:-45}

case "$seconds" in ''|*[!0-9]*) echo 'seconds must be an integer' >&2; exit 2 ;; esac
[ "$seconds" -ge 5 ] && [ "$seconds" -le 300 ] || {
	echo 'seconds outside 5..300' >&2
	exit 2
}
[ -f "$kernel" ] && [ -f "$dtb" ] && [ -f "$busybox" ] && [ -f "$loader" ] && [ -f "$supervisor" ] || {
	echo 'missing kexec proof input' >&2
	exit 2
}
[ ! -e "$out" ] || { echo 'use a fresh output directory' >&2; exit 2; }

readelf -h "$supervisor" | grep -q 'AArch64' || { echo 'supervisor is not AArch64' >&2; exit 2; }
readelf -l "$supervisor" | grep -q INTERP && {
	echo 'supervisor must be static' >&2
	exit 2
}
file "$busybox" | grep -q 'aarch64' || { echo 'busybox is not AArch64' >&2; exit 2; }
file "$loader" | grep -q 'aarch64' || { echo 'loader is not AArch64' >&2; exit 2; }

mkdir -p "$out/root"/{bin,lib,proc,sys,dev,run}
cp "$busybox" "$out/root/bin/busybox"
cp "$loader" "$out/root/lib/ld-musl-aarch64.so.1"
cp "$supervisor" "$out/root/bin/t825-recovery"
cat > "$out/root/init" <<'INIT'
#!/bin/busybox ash
set -eu
export PATH=/bin
/bin/busybox --install -s /bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mount -t tmpfs tmpfs /run
mkdir -p /run/t825-recovery
/bin/t825-recovery __SECONDS__ /run/t825-recovery &
printf '%s\n' "$!" > /run/t825-recovery/supervisor.pid
kill -0 "$(cat /run/t825-recovery/supervisor.pid)"
# Keep PID 1 alive until the independent supervisor requests the reset.
while :; do sleep 1; done
INIT
sed -i "s/__SECONDS__/$seconds/" "$out/root/init"
chmod 0755 "$out/root/init" "$out/root/bin/t825-recovery"
# cpio's reproducible mode normalizes ownership/device fields but retains file
# mtimes. Normalize the complete initramfs tree so rebuilding the same inputs
# produces the same compressed bytes and hashes.
find "$out/root" -exec touch -h -d @0 {} +

(cd "$out/root"; find . -print0 | LC_ALL=C sort -z | \
	cpio --null --reproducible -o -H newc --owner=0:0 2>/dev/null) |
	zstd -q -T1 -o "$out/initramfs" -f
cp "$kernel" "$out/vmlinuz"
cp "$dtb" "$out/t825.dtb"
cat > "$out/README.md" <<EOF
# Minimal kexec proof candidate

This candidate contains only BusyBox, the static recovery supervisor and a
tmpfs-backed init. It does not mount a root, boot, modem or EFS partition. The
supervisor arms after proc/sys/dev/run mounts and requests the normal kernel
reset after ${seconds}s. A fastboot return alone establishes reset observation,
not entry into this initramfs: panic or an old-kernel reset can produce the same
host observation. Candidate execution requires a separate marker. This image
does not cover a failure before its supervisor starts and does not establish
the normal direct-root handoff.
EOF
printf '%s\n' "mode=pre-supervisor-proof" "seconds=$seconds" \
	"kernel=$(realpath "$kernel")" "dtb=$(realpath "$dtb")" \
	"busybox=$(realpath "$busybox")" "loader=$(realpath "$loader")" \
	"supervisor=$(realpath "$supervisor")" > "$out/manifest.txt"
(cd "$out" && sha256sum vmlinuz initramfs t825.dtb root/bin/t825-recovery manifest.txt README.md > SHA256SUMS)
printf '%s\n' "built=$out" "initramfs=$(stat -c %s "$out/initramfs")"
