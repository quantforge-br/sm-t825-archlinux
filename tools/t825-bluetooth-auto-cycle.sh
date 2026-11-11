#!/usr/bin/env bash
# Run bounded Bluetooth reboot cycles from a RAM boot image.
# Software reboots may return directly to extlinux or to lk2nd fastboot.
# The latter route uses the specified image in RAM, without persistent boot writes.
set -euo pipefail

# Historical runner: polling cannot recover an installed-kernel hang, and a
# direct-init RAM fallback cannot run its systemd/BlueZ acceptance workload.
# Keep the implementation for reference but fail before any device access or
# report creation. Re-enable only with validated independent recovery and a
# candidate-aware Bluetooth probe. There is no environment override.
printf '%s\n' 'BLOCKED_BLUETOOTH_RECOVERY: legacy reboot runner lacks independent recovery and a validated Bluetooth RAM handoff. See docs/bluetooth-7.3.md.' >&2
exit 2

HERE=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$HERE"
out=${T825_BT_REPORT_DIR:-artifacts/roadmap-7.3/bluetooth-auto-$(date -u +%Y%m%dT%H%M%SZ)}
umask 077
mkdir -p "$out"
if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
	mkdir -p "$out/runner"
	cp "$HERE/tools/t825-bluetooth-auto-cycle.sh" "$out/runner/t825-bluetooth-auto-cycle.sh"
	sha256sum "$out/runner/t825-bluetooth-auto-cycle.sh" > "$out/runner.sha256"
	exec env T825_SOURCE_ROOT="$HERE" T825_RUNNER_SNAPSHOT=1 T825_BT_REPORT_DIR="$out" \
		bash "$out/runner/t825-bluetooth-auto-cycle.sh" "$@"
fi

exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }

image=${1:?usage: t825-bluetooth-auto-cycle.sh <normal RAM boot image>}
image=$(realpath "$image")
[ -s "$image" ] || { echo "missing image: $image" >&2; exit 2; }
cycles=${T825_BT_CYCLES:-20}
wait_s=${T825_BT_WAIT_SECONDS:-180}
target=${T825_SSH_TARGET:-tabs3}
serial=${T825_SERIAL:-957be8c9}
expected_version=${T825_EXPECTED_UNAME_V:-}
require_ram=${T825_BT_REQUIRE_RAM_BOOT:-0}
case "$require_ram" in 0|1) ;; *) echo 'T825_BT_REQUIRE_RAM_BOOT must be 0 or 1' >&2; exit 2 ;; esac
case "$cycles:$wait_s" in *[!0-9:]*|:*|*:) exit 2 ;; esac
[ "$cycles" -gt 0 ] && [ "$cycles" -le 20 ] && [ "$wait_s" -ge 60 ] && [ "$wait_s" -le 600 ] || exit 2

printf '%s\n' "image=$image" "image_sha256=$(sha256sum "$image" | awk '{print $1}')" \
	"target=$target" "cycles=$cycles" "wait_seconds=$wait_s" \
	"require_ram_boot=$require_ram" "expected_uname_v=$expected_version" > "$out/identity.txt"
printf '%s\n' "$$" > "$out/host.pid"
printf 'cycle\tboot_id_before\tboot_id_after\tbluetooth\tfastboot\telapsed_seconds\n' > "$out/results.tsv"
result=0

ssh_run() { timeout --kill-after=2s 15 ssh -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 -o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$target" "$@"; }
boot_id() { ssh_run 'cat /proc/sys/kernel/random/boot_id' | grep -Ex '[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}'; }
fastboot_ready() { timeout 4 fastboot devices | awk -v serial="$serial" '$1 == serial && $2 == "fastboot" { found=1 } END { exit !found }'; }
payload_identity() {
	ssh_run 'sha256sum /usr/sbin/gts3-bdaddr /usr/lib/systemd/system/gts3-bdaddr.service /usr/lib/udev/rules.d/90-gts3-bdaddr.rules'
}
# Invoked by the EXIT trap, including preflight failures.
# shellcheck disable=SC2329
finish() {
	local status=$?
	trap - EXIT
	printf '%s\n' "$status" > "$out/exit-status.txt"
	boot_id > "$out/final-boot-id.txt" 2> "$out/final-ssh-error.txt" || true
	# Both manifest names are excluded from the input to find.
	# shellcheck disable=SC2094
	(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS ! -name .SHA256SUMS.new -exec sha256sum {} + | sort > .SHA256SUMS.new && mv .SHA256SUMS.new SHA256SUMS)
}
trap finish EXIT
payload_identity > "$out/payload-before.sha256" || { echo 'Cannot identify deployed Bluetooth payload' >&2; exit 1; }
ssh_run 'bluetoothctl show; btmgmt --index 0 info' > "$out/controller-before.txt"
expected_addr=$(sed -nE 's/^Controller (([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) .*/\1/p' "$out/controller-before.txt" | head -1)
[ -n "$expected_addr" ] || { echo 'No baseline controller; refusing a reboot gate' >&2; exit 1; }
grep -Eiq "^[[:space:]]*addr $expected_addr " "$out/controller-before.txt" || { echo 'HCI and BlueZ baseline addresses differ' >&2; exit 1; }
image_hash=$(sha256sum "$image" | awk '{print $1}')
identity_matches() {
	local phase=$1
	payload_identity > "$out/payload-$cycle-$phase.sha256" || return 1
	cmp -s "$out/payload-before.sha256" "$out/payload-$cycle-$phase.sha256"
}

boot_ram_image() {
	[ "$(sha256sum "$image" | awk '{print $1}')" = "$image_hash" ] || return 1
	timeout 30 fastboot -s "$serial" boot "$image" > "$out/fastboot-cycle-$cycle.txt" 2>&1 || return 1
	deadline=$((SECONDS + wait_s))
	while [ "$SECONDS" -lt "$deadline" ]; do
		if ssh_run 'printf READY' 2>/dev/null | grep -q READY; then return 0; fi
		sleep 1
	done
	return 1
}

collect() {
	local n=$1
	# Commands and kernel variables are evaluated by the remote shell.
	# shellcheck disable=SC2016
	ssh_run 'set +e
echo "--- boot_id ---"; cat /proc/sys/kernel/random/boot_id
echo "--- uname ---"; uname -a
echo "--- bluetoothctl ---"; bluetoothctl show
echo "--- btmgmt ---"; btmgmt info
echo "--- bdaddr service ---"; systemctl --no-pager --full status gts3-bdaddr.service
echo "--- bdaddr journal ---"; journalctl -b -u gts3-bdaddr.service --no-pager
echo "--- hci0 ---"; test -e /sys/class/bluetooth/hci0 && echo present || echo missing
echo "--- kernel bluetooth faults ---"
kernel=$(sudo -n dmesg) || exit 1
printf "%s\n" "$kernel" | grep -E "Bluetooth|hci0|Opcode 0x0c03|Frame reassembly|qca.*(timeout|fail)|firmware.*(fail|timeout)" || true
' > "$out/boot-$n.txt" 2>&1
}

wait_bluetooth() {
	local deadline=$((SECONDS + 45))
	local stable=0
	while [ "$SECONDS" -lt "$deadline" ]; do
		# systemctl expressions must expand on the tablet.
		# shellcheck disable=SC2016
		if ssh_run 'test "$(systemctl show gts3-bdaddr.service -p SubState --value)" = dead && test "$(systemctl show gts3-bdaddr.service -p Result --value)" = success && btmgmt --index 0 info && bluetoothctl show' > "$out/probe-$cycle.txt" 2>/dev/null &&
			grep -q '^hci0:.*Primary controller' "$out/probe-$cycle.txt" &&
			grep -Fqi "Controller $expected_addr " "$out/probe-$cycle.txt" &&
			grep -Eiq "^[[:space:]]*addr $expected_addr " "$out/probe-$cycle.txt"; then stable=$((stable+1)); else stable=0; fi
		[ "$stable" -lt 3 ] || return 0
		sleep 1
	done
	return 1
}

for cycle in $(seq 1 "$cycles"); do
	started=$SECONDS
	before=$(boot_id 2>/dev/null || true)
	[ -n "$before" ] || { echo "cycle $cycle: SSH unavailable before reboot" >&2; exit 1; }
	identity_matches preboot || { echo "cycle $cycle: deployed payload changed; stopping before reboot" >&2; exit 1; }
	echo "cycle $cycle/$cycles: rebooting $before"
	ssh_run 'sudo -n systemctl reboot' >/dev/null 2>&1 || true
	fastboot_seen=0
	direct_ready=0
	after=
	deadline=$((SECONDS + wait_s))
	while [ "$SECONDS" -lt "$deadline" ]; do
		candidate=$(boot_id 2>/dev/null || true)
		if [ -n "$candidate" ] && [ "$candidate" != "$before" ]; then
			after=$candidate
			direct_ready=1
			break
		fi
		if fastboot_ready; then fastboot_seen=1; break; fi
		sleep 1
	done
	bt=BOOT_TIMEOUT
	boot_route=UNOBSERVED
	if [ "$direct_ready" = 1 ]; then
		boot_route=DIRECT_REBOOT
		ready=0; wait_bluetooth && ready=1
		collected=0; collect "$cycle" && collected=1
		if [ "$ready:$collected" = 1:1 ] && grep -Eq '^Controller ([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2} ' "$out/boot-$cycle.txt" && \
			grep -q '^hci0:.*Primary controller' "$out/boot-$cycle.txt" && \
			! grep -Eq 'Opcode 0x0c03.*failed: -110|qca.*(timeout|fail)|firmware.*(fail|timeout)' "$out/boot-$cycle.txt"; then
			bt=PASS
		else
			bt=FAULT
		fi
	elif [ "$fastboot_seen" = 1 ] && boot_ram_image; then
		boot_route=FASTBOOT_RAM
		after=$(boot_id 2>/dev/null || true)
		ready=0; wait_bluetooth && ready=1
		collected=0; collect "$cycle" && collected=1
		if [ "$ready:$collected" = 1:1 ] && [ -n "$after" ] && [ "$after" != "$before" ] && grep -Eq '^Controller ([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2} ' "$out/boot-$cycle.txt" && \
			grep -q '^hci0:.*Primary controller' "$out/boot-$cycle.txt" && \
			! grep -Eq 'Opcode 0x0c03.*failed: -110|qca.*(timeout|fail)|firmware.*(fail|timeout)' "$out/boot-$cycle.txt"; then
			bt=PASS
		else
			bt=FAULT
		fi
	fi
	printf '%s\n' "$boot_route" > "$out/boot-route-$cycle.txt"
	# uname -r is identical for r1 and r2. Record uname -v and, when a
	# candidate identity is specified, require the complete build version.
	if [ -n "$after" ]; then
		if ! ssh_run 'uname -v' > "$out/kernel-version-$cycle.txt"; then
			bt=KERNEL_IDENTITY_UNAVAILABLE
		elif [ -n "$expected_version" ] && [ "$(cat "$out/kernel-version-$cycle.txt")" != "$expected_version" ]; then
			bt=KERNEL_IDENTITY_MISMATCH
		fi
	fi
	if [ "$require_ram" = 1 ] && [ "$direct_ready" = 1 ]; then bt=RAM_BOOT_NOT_USED; fi
	if [ -n "$after" ] && ! identity_matches postboot; then bt=IDENTITY_CHANGED; fi
	fastboot_after=NOT_REQUESTED
	if [ -n "$after" ]; then fastboot_after=RUNNING; elif fastboot_ready; then fastboot_after=FASTBOOT; else fastboot_after=UNKNOWN; fi
	# Keep the controller stable before the next reboot, while retaining any
	# transient failure in this cycle's evidence.
	if [ "$bt" = PASS ] && [ "$cycle" != "$cycles" ]; then sleep 5; fi
	printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$cycle" "$before" "$after" "$bt" "$fastboot_after" "$((SECONDS-started))" >> "$out/results.tsv"
	if [ "$bt" != PASS ]; then result=1; break; fi
done

echo "Report: $out"
exit "$result"
