#!/usr/bin/env bash
# Run bounded RAM boots from an existing fastboot session, with no boot-file edits.
# Launch detached: nohup setsid tools/t825-gnss-auto-cycle.sh IMAGE > LOG 2>&1 < /dev/null &
set -euo pipefail
HERE=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$HERE"
out=${T825_REPORT_DIR:-artifacts/roadmap-7.3/gnss-ram-20261108/auto-$(date -u +%Y%m%dT%H%M%SZ)}
umask 077
mkdir -p "$out"
out=$(realpath "$out")
# Bash reads scripts incrementally. Freeze the entire runner before booting,
# so editing the development sources cannot corrupt an in-flight collector.
if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
	mkdir "$out/runner"
	for source in t825-gnss-auto-cycle.sh t825-gnss-hold-test.sh t825-telnet.py test-t825-gnss-ram-image.py; do
		cp "$HERE/tools/$source" "$out/runner/$source"
	done
	sha256sum "$out/runner/"* > "$out/runner.sha256"
	exec env T825_SOURCE_ROOT="$HERE" T825_RUNNER_SNAPSHOT=1 T825_REPORT_DIR="$out" \
		bash "$out/runner/t825-gnss-auto-cycle.sh" "$@"
fi
runner=$(cd "$(dirname "$0")" && pwd)
mkdir -p artifacts/roadmap-7.3
exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock'; exit 2; }
image=${1:-artifacts/roadmap-7.3/gnss-ram-20261108/v63-mss-loc-retry-ro/t825-v63.img}
image=$(realpath "$image")
cycles=${T825_AUTO_CYCLES:-1}
wait_s=${T825_WAIT_SECONDS:-300}
case "$cycles:$wait_s" in *[!0-9:]*|:*|*:) exit 2 ;; esac
[ "$cycles" -gt 0 ] && [ "$cycles" -le 20 ] && [ "$wait_s" -ge 260 ] && [ "$wait_s" -le 600 ] || exit 2
printf '%s\n' "$$" > "$out/host.pid"
exec > >(tee -a "$out/host.log") 2>&1
# Validate the actual paired archive before exposing hardware to modem startup.
T825_RAM_IMAGE="$image" T825_RAM_BUNDLE="$(dirname "$image")" python3 "$runner/test-t825-gnss-ram-image.py"
mapfile -t devices < <(timeout 5 fastboot devices | awk '$2 == "fastboot" {print $1}')
[ "${#devices[@]}" = 1 ] || { echo 'Require exactly one tablet already in fastboot; no persistent boot files will be renamed.'; exit 2; }
serial=${devices[0]}
timeout 5 fastboot -s "$serial" getvar lk2nd:compatible 2> "$out/identity.txt"
grep -q 'lk2nd:compatible: samsung,gts3llte' "$out/identity.txt" || exit 2
printf 'cycle\tdiagnostic_status\trecovery\telapsed_seconds\n' > "$out/results.tsv"
result=0
# lk2nd can briefly expose its generic Android USB product while the fastboot
# client has a stale handle. Reset only that exact bootloader device and retry;
# never touch a running Linux/NCM device or any other USB endpoint.
usb_bootloader_recover() {
	local node product
	for node in /dev/bus/usb/*/*; do
		[ -e "$node" ] || continue
		product=$(udevadm info -q property -n "$node" 2>/dev/null |
			awk -F= '$1 == "PRODUCT" {print $2; exit}')
		[ "$product" = '18d1/d00d/100' ] || continue
		if command -v usbreset >/dev/null 2>&1; then
			usbreset "$node" >"$out/usbreset.log" 2>&1 || true
		fi
		return 0
	done
	return 1
}
for ((cycle=1; cycle<=cycles; cycle++)); do
	started=$SECONDS
	echo "Starting RAM diagnostic cycle $cycle/$cycles"
	rc=0
	T825_SERIAL="$serial" bash "$runner/t825-gnss-hold-test.sh" "$image" "$out/cycle-$cycle" || rc=$?
	[ "$rc" = 0 ] || result=1
	if [ ! -f "$out/cycle-$cycle/boot-disconnected" ]; then
		printf '%s\t%s\tNOT_STARTED\t%s\n' "$cycle" "$rc" "$((SECONDS-started))" >> "$out/results.tsv"
		echo 'FAIL: no observed RAM-boot transition; stopping further boots.'
		exit 1
	fi
	# Include the final cycle: never leave recovery unobserved on collector exit.
	recovered=0
	while [ "$((SECONDS - started))" -lt "$wait_s" ]; do
		if timeout 3 fastboot devices | awk -v serial="$serial" '$1 == serial && $2 == "fastboot" {found=1} END {exit !found}'; then recovered=1; break; fi
		usb_bootloader_recover || true
		sleep 2
	done
	printf '%s\t%s\t%s\t%s\n' "$cycle" "$rc" "$recovered" "$((SECONDS-started))" >> "$out/results.tsv"
	if [ "$recovered" != 1 ]; then
		timeout 5 lsusb > "$out/usb-final.txt" 2>&1 || true
		timeout 5 adb devices > "$out/adb-final.txt" 2>&1 || true
		echo 'FAIL: no fastboot return; stopping further boots. See USB evidence.'
		exit 1
	fi
	echo "Autonomous fastboot return confirmed for cycle $cycle"
	# A failed diagnostic is evidence to inspect, not a reason to repeat blindly.
	[ "$rc" = 0 ] || break
done
echo "Finished: result=$result; tablet left in fastboot"
exit "$result"
