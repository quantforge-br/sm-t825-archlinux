#!/usr/bin/env bash
# Launch the minimal pre-supervisor kexec proof once the installed system is
# reachable. If the operator leaves the tablet in fastboot, this wrapper only
# issues `fastboot reboot`; it never flashes or changes a boot file.
set -euo pipefail
export LC_ALL=C

# Gate the wrapper too: it must not reboot a tablet out of fastboot before
# discovering that the experimental kexec runner cannot safely execute.
require_preentry_recovery() {
	printf '%s\n' 'BLOCKED_PREENTRY_RECOVERY: kexec execution is disabled until independent pre-entry recovery is hardware-validated. See docs/unattended-recovery-audit.md.' >&2
	return 2
}
require_preentry_recovery

root=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
serial=${T825_SERIAL:-957be8c9}
target=${T825_SSH_TARGET:-tabs3}
bundle=${1:-$root/artifacts/roadmap-7.3/kexec-proof-candidate-20261110b}
out=${2:-$root/artifacts/roadmap-7.3/kexec-proof-cycle-$(date -u +%Y%m%dT%H%M%SZ)}
runner=${T825_KEXEC_RUNNER:-$root/tools/t825-kexec-cycle.sh}
wait_s=${T825_KEXEC_PROOF_START_WAIT_SECONDS:-300}

case "$wait_s" in ''|*[!0-9]*) echo 'start wait must be an integer' >&2; exit 2 ;; esac
[ "$wait_s" -ge 30 ] && [ "$wait_s" -le 900 ] || {
	echo 'start wait outside 30..900 seconds' >&2
	exit 2
}
[ -f "$runner" ] || { echo "missing runner: $runner" >&2; exit 2; }
[ -f "$bundle/vmlinuz" ] && [ -f "$bundle/initramfs" ] && [ -f "$bundle/t825.dtb" ] || {
	echo "invalid proof bundle: $bundle" >&2
	exit 2
}
[ ! -e "$out" ] || { echo "report already exists: $out" >&2; exit 2; }
mkdir -p "$out"
chmod 700 "$out"
printf '%s\n' "target=$target" "serial=$serial" "bundle=$bundle" > "$out/identity.txt"

fastboot_ready() {
	timeout 5 fastboot devices | awk -v serial="$serial" \
		'$1 == serial && $2 == "fastboot" { found=1 } END { exit !found }'
}
ssh_ready() {
	timeout --kill-after=3s 10 ssh -o BatchMode=yes -o ConnectTimeout=3 \
		-o ServerAliveInterval=2 -o ServerAliveCountMax=1 "$target" true >/dev/null 2>&1
}

if fastboot_ready; then
	printf '%s\n' 'fastboot detected; issuing fastboot reboot' > "$out/fastboot-reboot.txt"
	timeout 30 fastboot -s "$serial" reboot >> "$out/fastboot-reboot.txt" 2>&1
fi

deadline=$((SECONDS + wait_s))
while [ "$SECONDS" -lt "$deadline" ]; do
	if ssh_ready; then
		printf '%s\n' 'installed SSH reachable; launching detached kexec runner' > "$out/launch.txt"
		setsid env T825_SOURCE_ROOT="$root" T825_SSH_TARGET="$target" T825_SERIAL="$serial" \
			T825_KEXEC_WAIT_SECONDS="${T825_KEXEC_WAIT_SECONDS:-180}" \
			bash "$runner" "$bundle" "$out/report" > "$out/host.log" 2>&1 < /dev/null &
		pid=$!
		printf '%s\n' "$pid" > "$out/host.pid"
		printf '%s\n' "pid=$pid" "report=$out/report"
		exit 0
	fi
	sleep 3
done
printf '%s\n' 'no installed SSH route appeared before the deadline; no kexec was attempted' > "$out/launch.txt"
printf '%s\n' 'FAIL_NO_INSTALLED_SSH'
exit 1
