#!/usr/bin/env bash
# Safely probe the installed tablet's legacy ARM64 kexec route.
# This deliberately loads and unloads a candidate; it never executes it.
set -euo pipefail
export LC_ALL=C
root=$(cd "$(dirname "$0")/.." && pwd)
target=${T825_SSH_TARGET:-tabs3}
bundle=${1:?usage: t825-kexec-load-audit.sh CANDIDATE_BUNDLE REPORT_DIR}
out=${2:?report directory required}
kexec_bin=${T825_KEXEC_BIN:-$root/artifacts/roadmap-7.3/kexec-route-audit-20261110/pkgroot/usr/bin/kexec}
for path in "$bundle/vmlinuz" "$bundle/initramfs" "$bundle/t825.dtb" "$kexec_bin"; do
    [ -f "$path" ] || { echo "missing input: $path" >&2; exit 2; }
done
mkdir -p "$out"; out=$(realpath "$out")
exec 9>"$root/artifacts/roadmap-7.3/tablet-test.lock"
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }
sha256sum "$bundle/vmlinuz" "$bundle/initramfs" "$bundle/t825.dtb" "$kexec_bin" > "$out/inputs.sha256"
printf '%s\n' "target=$target" "bundle=$(realpath "$bundle")" > "$out/identity.txt"
remote=/tmp/t825-kexec-probe-$(date -u +%Y%m%dT%H%M%SZ)
cat > "$out/remote.sh" <<'REMOTE'
#!/bin/sh
set -eu
remote=${1:?remote directory}; cmd=${2:?command line file}
mkdir -m700 "$remote" 2>/dev/null || test -d "$remote"
cleanup() {
    rc=$?; set +e
    "$remote/kexec" -c -u >"$remote/unload.txt" 2>&1
    printf '%s\n' "$?" >"$remote/unload.rc"
    cat /sys/kernel/kexec/loaded >"$remote/loaded.after" 2>&1
    dmesg --ctime >"$remote/dmesg.after" 2>&1
    printf '%s\n' "$rc" >"$remote/probe.rc"
    exit "$rc"
}
trap cleanup EXIT INT TERM HUP
printf '%s\n' "$(cat /sys/kernel/kexec/loaded)" >"$remote/loaded.before"
dmesg --ctime >"$remote/dmesg.before"
set +e
timeout --kill-after=5s 90 "$remote/kexec" -d -c -l "$remote/vmlinuz" \
    --initrd="$remote/initramfs" --dtb="$remote/t825.dtb" \
    --append="$(cat "$cmd")" >"$remote/load.txt" 2>&1
load_rc=$?; set -e
printf '%s\n' "$load_rc" >"$remote/load.rc"
cat /sys/kernel/kexec/loaded >"$remote/loaded.after-load"
dmesg --ctime >"$remote/dmesg.after-load"
[ "$load_rc" -eq 0 ] || exit "$load_rc"
test "$(cat /sys/kernel/kexec/loaded)" = 1
REMOTE
chmod 755 "$out/remote.sh"
cat > "$out/cmdline" <<'CMD'
console=tty0 clk_ignore_unused pd_ignore_unused sysctl.kernel.firmware_config.ignore_sysfs_fallback=1 t825.ramdiag t825.direct-init panic=10 pmos.debug-shell pmos_root_uuid=bd56cedb-62b6-40a0-b478-b658293d65c0 pmos_rootfsopts=subvol=/@,noatime,compress=zstd:1
CMD
sha256sum "$out/remote.sh" "$out/cmdline" > "$out/runner.sha256"
ssh_run() { timeout --kill-after=5s 120 ssh -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$target" "$@"; }
ssh_run "mkdir -m700 '$remote'"
ssh_run "cat > '$remote/remote.sh'" < "$out/remote.sh"
ssh_run "cat > '$remote/cmdline'" < "$out/cmdline"
ssh_run "cat > '$remote/kexec'" < "$kexec_bin"
ssh_run "cat > '$remote/vmlinuz'" < "$bundle/vmlinuz"
ssh_run "cat > '$remote/initramfs'" < "$bundle/initramfs"
ssh_run "cat > '$remote/t825.dtb'" < "$bundle/t825.dtb"
ssh_run "chmod 700 '$remote' '$remote/remote.sh' '$remote/kexec' '$remote/vmlinuz' '$remote/initramfs' '$remote/t825.dtb'"
set +e
ssh_run "sudo -n sh '$remote/remote.sh' '$remote' '$remote/cmdline'" > "$out/remote-run.txt" 2>&1
run_rc=$?; set -e
printf '%s\n' "$run_rc" > "$out/remote-run.rc"
if [ "$run_rc" -eq 0 ]; then
    ssh_run "sudo -n tar -C '$remote' -cf - ." > "$out/remote.tar"
    mkdir -p "$out/remote"; tar -xf "$out/remote.tar" -C "$out/remote"
    [ "$(cat "$out/remote/load.rc")" = 0 ]
    [ "$(cat "$out/remote/unload.rc")" = 0 ]
    [ "$(cat "$out/remote/loaded.before")" = 0 ]
    [ "$(cat "$out/remote/loaded.after-load")" = 1 ]
    [ "$(cat "$out/remote/loaded.after")" = 0 ]
    ssh_run "find '$remote' -mindepth 1 -delete; rmdir '$remote'"
else
    echo 'kexec load/unload probe failed; no execution was attempted' >&2
    exit "$run_rc"
fi
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS.tmp && mv SHA256SUMS.tmp SHA256SUMS)
printf '%s\n' "PASS: kexec load/unload completed; kexec -e was never called"
