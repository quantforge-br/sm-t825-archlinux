#!/usr/bin/env bash
# Execute one bounded, nonpersistent kexec handoff and recover to the
# installed system. This runner never flashes a partition or changes a boot
# file. The candidate initramfs must carry its own recovery supervisor.
# shellcheck disable=SC2016 # Single-quoted blocks intentionally expand remotely.
set -euo pipefail
export LC_ALL=C

# No pre-entry recovery backend has passed hardware validation. Keep the
# experimental implementation below for review, but do not contact the tablet,
# load a kernel, or tear down USB. A candidate's supervisor starts too late to
# protect device_shutdown, CPU teardown or relocation. There is deliberately
# no environment-variable override for this gate.
require_preentry_recovery() {
	printf '%s\n' 'BLOCKED_PREENTRY_RECOVERY: kexec execution is disabled until independent pre-entry recovery is hardware-validated. See docs/unattended-recovery-audit.md.' >&2
	return 2
}
require_preentry_recovery

root=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
target=${T825_SSH_TARGET:-tabs3}
serial=${T825_SERIAL:-957be8c9}
bundle=${1:?usage: t825-kexec-cycle.sh CANDIDATE_BUNDLE REPORT_DIR}
out=${2:?report directory required}
kexec_bin=${T825_KEXEC_BIN:-$root/artifacts/roadmap-7.3/kexec-route-audit-20261110/pkgroot/usr/bin/kexec}
wait_s=${T825_KEXEC_WAIT_SECONDS:-360}
restore_wait_s=${T825_KEXEC_RESTORE_WAIT_SECONDS:-180}

case "$wait_s" in ''|*[!0-9]*) echo 'wait timeout must be a positive integer' >&2; exit 2 ;; esac
case "$restore_wait_s" in ''|*[!0-9]*) echo 'restore timeout must be a positive integer' >&2; exit 2 ;; esac
[ "$wait_s" -ge 120 ] && [ "$wait_s" -le 900 ] || { echo 'wait timeout outside 120..900 seconds' >&2; exit 2; }
[ "$restore_wait_s" -ge 30 ] && [ "$restore_wait_s" -le 600 ] || { echo 'restore timeout outside 30..600 seconds' >&2; exit 2; }

bundle=$(realpath "$bundle")
out=$(realpath -m "$out")
for path in "$bundle/vmlinuz" "$bundle/initramfs" "$bundle/t825.dtb" "$kexec_bin"; do
	[ -f "$path" ] || { echo "missing input: $path" >&2; exit 2; }
done

candidate_mode=normal
if [ -f "$bundle/manifest.txt" ] && grep -qx 'mode=pre-supervisor-proof' "$bundle/manifest.txt"; then
	candidate_mode=pre-supervisor-proof
fi
cmdline=${T825_KEXEC_CMDLINE:-'console=tty0 clk_ignore_unused pd_ignore_unused sysctl.kernel.firmware_config.ignore_sysfs_fallback=1 t825.ramdiag t825.direct-init panic=10 pmos.debug-shell pmos_root_uuid=bd56cedb-62b6-40a0-b478-b658293d65c0 pmos_rootfsopts=subvol=/@,noatime,compress=zstd:1'}
if [ "$candidate_mode" = pre-supervisor-proof ]; then
	case " $cmdline " in *' panic=10 '*) ;; *) echo 'proof candidate command line lacks panic=10' >&2; exit 2 ;; esac
else
	for required in t825.ramdiag t825.direct-init panic=10; do
		case " $cmdline " in *" $required "*) ;; *) echo "candidate command line lacks $required" >&2; exit 2 ;; esac
	done
fi
case " $cmdline " in *' rw '*|*' rootflags=rw '*|*' mount_boot_partition'*) echo 'unsafe writable/boot-mount command line' >&2; exit 2 ;; esac

umask 077
mkdir -p "$out"
chmod 700 "$out"
if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
	mkdir -p "$out/runner"
	cp "$0" "$out/runner/t825-kexec-cycle.sh"
	sha256sum "$out/runner/t825-kexec-cycle.sh" > "$out/runner.sha256"
	exec env T825_SOURCE_ROOT="$root" T825_RUNNER_SNAPSHOT=1 \
		T825_KEXEC_BIN="$kexec_bin" T825_SSH_TARGET="$target" T825_SERIAL="$serial" \
		T825_KEXEC_WAIT_SECONDS="$wait_s" T825_KEXEC_RESTORE_WAIT_SECONDS="$restore_wait_s" \
		T825_KEXEC_CMDLINE="$cmdline" bash "$out/runner/t825-kexec-cycle.sh" "$bundle" "$out"
fi
exec 9>"$root/artifacts/roadmap-7.3/tablet-test.lock"
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }

sha256sum "$bundle/vmlinuz" "$bundle/initramfs" "$bundle/t825.dtb" "$kexec_bin" > "$out/inputs.sha256"
[ ! -f "$bundle/manifest.txt" ] || sha256sum "$bundle/manifest.txt" >> "$out/inputs.sha256"
printf '%s\n' "target=$target" "serial=$serial" "bundle=$bundle" \
	"candidate_mode=$candidate_mode" \
	"wait_seconds=$wait_s" "restore_wait_seconds=$restore_wait_s" "cmdline=$cmdline" > "$out/identity.txt"
printf '%s\n' "$$" > "$out/host.pid"

ssh_run() {
	timeout --kill-after=5s 20 ssh -o BatchMode=yes -o ConnectTimeout=5 \
		-o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$target" "$@"
}
boot_id() {
	local value
	for _attempt in 1 2 3; do
		value=$(ssh_run 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null | tr -d '\r\n' || true)
		if printf '%s\n' "$value" | grep -Eq '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$'; then
			printf '%s\n' "$value"
			return 0
		fi
		sleep 1
	done
	return 1
}
fastboot_ready() {
	timeout 5 fastboot devices | awk -v serial="$serial" '$1 == serial && $2 == "fastboot" { found=1 } END { exit !found }'
}

cleanup_remote() {
	set +e
	if [ -n "${remote:-}" ]; then
		ssh_run "sudo -n find '$remote' -mindepth 1 -delete; sudo -n rmdir '$remote'" >/dev/null 2>&1
	fi
}
trap cleanup_remote EXIT

before=$(boot_id)
printf '%s\n' "$before" > "$out/boot-id.before"
ssh_run 'uname -a; cat /proc/cmdline; cat /sys/kernel/kexec/loaded' > "$out/baseline.txt"
grep -qx '0' <(tail -1 "$out/baseline.txt") || { echo 'kexec slot is already loaded' >&2; exit 2; }

stamp=$(date -u +%Y%m%dT%H%M%SZ)
remote=/run/t825-kexec-$stamp
ssh_run "sudo -n mkdir -m700 '$remote'"
for file in vmlinuz initramfs t825.dtb; do
	ssh_run "sudo -n tee '$remote/$file' >/dev/null" < "$bundle/$file"
done
ssh_run "sudo -n tee '$remote/kexec' >/dev/null" < "$kexec_bin"
ssh_run "sudo -n chmod 700 '$remote' '$remote/kexec' '$remote/vmlinuz' '$remote/initramfs' '$remote/t825.dtb'"
ssh_run "sudo -n sha256sum '$remote/kexec' '$remote/vmlinuz' '$remote/initramfs' '$remote/t825.dtb'" > "$out/remote-inputs.sha256"

ssh_run "sudo -n timeout --kill-after=5s 90 '$remote/kexec' -d -c -l '$remote/vmlinuz' --initrd='$remote/initramfs' --dtb='$remote/t825.dtb' --append=$(printf '%q' "$cmdline")" > "$out/load.txt" 2>&1
ssh_run "sudo -n cat /sys/kernel/kexec/loaded" > "$out/loaded.after-load"
grep -qx '1' "$out/loaded.after-load" || { echo 'kexec load did not set loaded=1' >&2; exit 1; }

# A kexec handoff skips the normal systemd shutdown path. Stop the installed
# USB gadget immediately before execution so the new kernel does not inherit a
# UDC function with a stale carrier. The diagnostic initramfs creates its own
# transient gadget.
ssh_run 'set +e
sudo -n systemctl stop t825-usb-gadget.service unudhcpd@usb0.service 2>/dev/null || true
for iface in usb0 enp120s0u1; do sudo -n ip link set "$iface" down 2>/dev/null || true; done
if [ -e /sys/kernel/config/usb_gadget/g1/UDC ]; then
    printf "\\n" | sudo -n tee /sys/kernel/config/usb_gadget/g1/UDC >/dev/null 2>&1 || true
fi
sleep 2
sudo -n systemctl is-active t825-usb-gadget.service 2>/dev/null || true' > "$out/pre-kexec-usb.txt"

printf '%s\n' "executing=$stamp" > "$out/execute.txt"
set +e
ssh_run "sudo -n '$remote/kexec' -e" > "$out/execute.log" 2>&1
execute_rc=$?
set -e
printf '%s\n' "$execute_rc" > "$out/execute.rc"

after=''
fastboot_seen=0
deadline=$((SECONDS + wait_s))
while [ "$SECONDS" -lt "$deadline" ]; do
	if candidate=$(boot_id 2>/dev/null) && [ "$candidate" != "$before" ]; then
		after=$candidate
		break
	fi
	if fastboot_ready; then
		fastboot_seen=1
		break
	fi
	sleep 2
done

printf '%s\n' "$after" > "$out/boot-id.after"
printf '%s\n' "$fastboot_seen" > "$out/fastboot.seen"

diagnostic_pass=0
if [ -n "$after" ]; then
	if ssh_run 'grep -qw t825.ramdiag /proc/cmdline && grep -E "[[:space:]]/[[:space:]].*ro[,)]|[[:space:]]/[[:space:]].*rescue=nologreplay" /proc/mounts && test -x /usr/local/libexec/t825-recovery-supervisor' > "$out/diagnostic-check.txt" 2>&1; then
		diagnostic_pass=1
	fi
elif [ "$fastboot_seen" = 1 ]; then
	printf '%s\n' 'fastboot returned before SSH; the candidate supervisor may have reset early' > "$out/diagnostic-check.txt"
fi
printf '%s\n' "$diagnostic_pass" > "$out/diagnostic-pass"

# A diagnostic SSH session is only an intermediate check. Keep observing the
# same detached host process until the independent supervisor returns fastboot.
# This prevents a successful handoff from being reported while leaving the
# tablet in the candidate kernel.
if [ "$diagnostic_pass" = 1 ] && [ "$fastboot_seen" = 0 ]; then
	while [ "$SECONDS" -lt "$deadline" ]; do
		if fastboot_ready; then
			fastboot_seen=1
			printf '%s\n' 1 > "$out/fastboot.seen"
			break
		fi
		sleep 2
	done
fi

restore_pass=0
if [ "$fastboot_seen" = 1 ]; then
	if timeout 30 fastboot -s "$serial" reboot > "$out/fastboot-reboot.txt" 2>&1; then
		restore_deadline=$((SECONDS + restore_wait_s))
		while [ "$SECONDS" -lt "$restore_deadline" ]; do
			if restored=$(boot_id 2>/dev/null) && [ "$restored" != "$before" ] && [ "$restored" != "$after" ]; then
				printf '%s\n' "$restored" > "$out/boot-id.restored"
				restore_pass=1
				break
			fi
			sleep 2
		done
	fi
fi
printf '%s\n' "$restore_pass" > "$out/restore-pass"

if [ "$candidate_mode" = pre-supervisor-proof ] && [ "$fastboot_seen" = 1 ] && [ "$restore_pass" = 1 ]; then
	# A panic or an old-kernel reset can also return fastboot. Without a
	# candidate execution marker this proves only observed reset/restoration.
	status=RECOVERY_PASS_PROOF_UNOBSERVED
elif [ "$diagnostic_pass" = 1 ] && [ "$restore_pass" = 1 ]; then
	status=PASS
elif [ "$fastboot_seen" = 1 ] && [ "$restore_pass" = 1 ]; then
	status=RECOVERY_PASS_DIAGNOSTIC_UNOBSERVED
else
	status=FAIL
fi
printf '%s\n' "$status" > "$out/status.txt"
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + | sort > .SHA256SUMS.tmp && mv .SHA256SUMS.tmp SHA256SUMS)
printf 'status=%s\n' "$status"
[ "$status" != FAIL ]
