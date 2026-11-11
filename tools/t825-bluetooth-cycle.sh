#!/usr/bin/env bash
# Reboot a running SM-T825 repeatedly and collect Bluetooth bring-up evidence.
# This requests a normal userspace reboot and, if a failed boot exposes lk2nd
# fastboot, uses `fastboot reboot` as a reversible recovery step. It never
# enters Download mode or writes a partition.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
cd "$HERE"
mkdir -p artifacts/roadmap-7.3
exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock'; exit 2; }

target=${T825_SSH_TARGET:-tabs3}
cycles=${T825_BT_CYCLES:-20}
wait_s=${T825_BT_WAIT_SECONDS:-180}
out=${1:-artifacts/roadmap-7.3/bluetooth-${target}-$(date -u +%Y%m%dT%H%M%SZ)}
umask 077
mkdir -p -- "$out"
chmod 700 -- "$out"

case "$cycles" in ''|*[!0-9]*) echo 'T825_BT_CYCLES must be an integer' >&2; exit 2 ;; esac
[ "$cycles" -gt 0 ] || { echo 'T825_BT_CYCLES must be positive' >&2; exit 2; }
case "$wait_s" in ''|*[!0-9]*) echo 'T825_BT_WAIT_SECONDS must be an integer' >&2; exit 2 ;; esac
[ "$wait_s" -gt 0 ] || { echo 'T825_BT_WAIT_SECONDS must be positive' >&2; exit 2; }

ssh_run() {
	ssh -o BatchMode=yes -o ConnectTimeout=5 "$target" "$@"
}

boot_id() {
	ssh_run 'cat /proc/sys/kernel/random/boot_id'
}

adb_boot_id() {
	adb shell 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null | tr -d '\r'
}

fastboot_ready() {
	fastboot devices | awk '$2 == "fastboot" { found=1; exit } END { exit !found }'
}

recover_fastboot() {
	# A failed normal boot can still leave lk2nd fastboot reachable. Rebooting
	# from fastboot is reversible and keeps this cycle unattended; never flash.
	if [ "${fastboot_rebooted:-0}" -eq 0 ] && fastboot_ready; then
		echo "cycle $n: fastboot detected; requesting normal reboot" >&2
		fastboot reboot >/dev/null 2>&1 || true
		fastboot_rebooted=1
		return 0
	fi
	return 1
}

collect() {
	local n=$1
	ssh_run 'set +e
echo "--- boot_id ---"
cat /proc/sys/kernel/random/boot_id
echo "--- uname ---"
uname -a
echo "--- bluetoothctl ---"
bluetoothctl show
echo "--- btmgmt ---"
btmgmt info
echo "--- bdaddr service ---"
systemctl --no-pager --full status gts3-bdaddr.service
echo "--- bdaddr journal ---"
journalctl -b -u gts3-bdaddr.service --no-pager
echo "--- hci0 ---"
test -e /sys/class/bluetooth/hci0 && echo present || echo missing
echo "--- kernel bluetooth faults ---"
sudo -n dmesg | grep -E "Bluetooth|hci0|Opcode 0x0c03|Frame reassembly|qca.*(timeout|fail)|firmware.*(fail|timeout)" || true
' >"$out/boot-$n.txt" 2>&1
	local rc=$?
	[ "$rc" -eq 0 ] || return "$rc"
	grep -Eq '^Controller ([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2} ' "$out/boot-$n.txt" || return 1
	grep -q '^hci0:.*Primary controller' "$out/boot-$n.txt" || return 1
}

printf 'cycle\tboot_id_before\tboot_id_after\tstatus\n' >"$out/results.tsv"
for n in $(seq 1 "$cycles"); do
	before=$(boot_id)
	printf 'cycle %s/%s: rebooting (%s)\n' "$n" "$cycles" "$before"
	ssh_run 'sudo -n systemctl reboot' >/dev/null 2>&1 || true
	after=
	fastboot_rebooted=0
	i=0
	while [ "$i" -lt "$wait_s" ]; do
		sleep 1
		i=$((i + 1))
		candidate=$(boot_id 2>/dev/null || true)
		if [ -n "$candidate" ] && [ "$candidate" != "$before" ]; then
			after=$candidate
			break
		fi
		if adb devices 2>/dev/null | awk '$2 == "device" { found=1; exit } END { exit !found }'; then
			candidate=$(adb_boot_id || true)
			if [ -n "$candidate" ] && [ "$candidate" != "$before" ]; then
				after=$candidate
				break
			fi
		fi
		if recover_fastboot; then
			# Give lk2nd a chance to leave fastboot before polling again.
			sleep 3
		fi
	done
	if [ -z "$after" ]; then
		printf '%s\t%s\t%s\tTIMEOUT\n' "$n" "$before" "" >>"$out/results.tsv"
		echo "cycle $n did not observe a new boot_id" >&2
		exit 1
	fi
	collect_rc=0
	collect "$n" || collect_rc=$?
	if [ "$collect_rc" -ne 0 ]; then
		status=COLLECT_FAIL
	elif grep -Eq 'Opcode 0x0c03.*failed: -110|qca.*(timeout|fail)|firmware.*(fail|timeout)' "$out/boot-$n.txt"; then
		status=FAULT
	else
		status=PASS
	fi
	printf '%s\t%s\t%s\t%s\n' "$n" "$before" "$after" "$status" >>"$out/results.tsv"
	printf 'cycle %s/%s: %s\n' "$n" "$cycles" "$status"
done

(cd "$out"; manifest=$(mktemp); find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' | sort | xargs -r sha256sum >"$manifest"; mv "$manifest" SHA256SUMS)
printf 'Report: %s\n' "$out"
