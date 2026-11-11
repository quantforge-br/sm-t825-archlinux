#!/usr/bin/env bash
# Host-side one-shot controller rebind trace; never reboot or flash the tablet.
set -euo pipefail
export LC_ALL=C
root=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$root"
target=${T825_SSH_TARGET:-tabs3}
out=${T825_BT_TRACE_REPORT:-artifacts/roadmap-7.3/bluetooth-hci-trace-$(date -u +%Y%m%dT%H%M%SZ)}
umask 077
mkdir -p "$out"
out=$(realpath "$out")
if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
    mkdir -p "$out/runner"
    cp tools/t825-bluetooth-trace{,-remote}.sh tools/t825-bluetooth-trace-evidence.py tools/t825-bluetooth-ibs-sample.py tools/t825-validate.py "$out/runner/"
    sha256sum "$out/runner/"* > "$out/runner.sha256"
    exec env T825_SOURCE_ROOT="$root" T825_RUNNER_SNAPSHOT=1 T825_BT_TRACE_REPORT="$out" bash "$out/runner/t825-bluetooth-trace.sh"
fi
exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }
printf '%s\n' "$$" > "$out/host.pid"
stamp=$(date -u +%Y%m%d%H%M%S)
remote=/run/t825-bt-trace-$stamp
unit=t825-bt-trace-$stamp
ssh_run() { timeout --kill-after=2s 12 ssh -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$target" "$@"; }
armed=0
finished=0
healthy=0
archive_status=not_attempted
timer_stopped=0
expected_address=''
finalize() {
    status=$?
    trap - EXIT
    set +e
    if [ "$armed" = 1 ]; then
        # These steps must still execute when collection or archive retrieval
        # fails. Never cancel the independent timer on a partial health result.
        ssh_run "sudo -n /bin/bash '$remote/runner.sh' restore '$remote'" > "$out/restore-request.txt" 2>&1
        timeout --kill-after=2s 20 ssh -o BatchMode=yes -o ConnectTimeout=5 "$target" "sudo -n tar -C '$remote' -cf - ." > "$out/remote.tar" 2> "$out/archive.stderr"
        archive_status=$?
        mkdir -p "$out/remote"
        if [ "$archive_status" = 0 ]; then
            tar -xf "$out/remote.tar" -C "$out/remote"
            archive_status=$?
        fi
        for _attempt in $(seq 1 20); do
            if ssh_run 'systemctl is-active bluetooth.service && btmgmt info && bluetoothctl show' > "$out/final-state.txt" 2>&1 &&
                grep -Fqi "Controller $expected_address " "$out/final-state.txt" &&
                grep -q '^hci0:.*Primary controller' "$out/final-state.txt" &&
                awk -v want="$expected_address" '$1 == "addr" && toupper($2) == toupper(want) { found=1 } END {exit !found}' "$out/final-state.txt"; then
                healthy=1
                break
            fi
            sleep 2
        done
        # The collector must be terminal: it must not unbind again after the
        # last health probe and after independent restoration was cancelled.
        if [ "$healthy:$finished" = 1:1 ]; then
            if ssh_run "sudo -n systemctl stop '$unit-recover.timer'" > "$out/timer-stop.txt" 2>&1; then timer_stopped=1; fi
        fi
    fi
    collection_status=missing
    classification=missing
    if [ -f "$out/remote/collection.status" ]; then collection_status=$(cat "$out/remote/collection.status"); fi
    if [ -f "$out/remote/classification" ]; then classification=$(cat "$out/remote/classification"); fi
    if [ "$finished:$healthy:$archive_status:$timer_stopped:$collection_status:$classification" != 1:1:0:1:0:no_new_hci_reset_timeout ]; then status=1; fi
    printf '%s\n' "finished=$finished" "controller_restored=$healthy" \
        "archive_status=$archive_status" "recovery_timer_stopped=$timer_stopped" \
        "collection_status=$collection_status" "classification=$classification" "exit_status=$status" > "$out/result.txt"
    # The manifest is explicitly excluded from its own input.
    # shellcheck disable=SC2094
    (cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS ! -name host.log -exec sha256sum {} + > SHA256SUMS)
    echo "Report: $out"
    exit "$status"
}
trap finalize EXIT
printf '%s\n' "target=$target" "remote=$remote" "unit=$unit" > "$out/identity.txt"
ssh_run 'systemctl is-system-running || true; uname -a; btmgmt info; bluetoothctl show' > "$out/baseline.txt"
expected_address=$(awk '/^Controller / {print $2; exit}' "$out/baseline.txt")
[[ "$expected_address" =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]]
ssh_run "sudo -n mkdir -m700 '$remote'"
ssh_run "sudo -n tee '$remote/runner.sh' >/dev/null" < "$out/runner/t825-bluetooth-trace-remote.sh"
for file in t825-bluetooth-trace-evidence.py t825-bluetooth-ibs-sample.py t825-validate.py; do
    ssh_run "sudo -n tee '$remote/$file' >/dev/null" < "$out/runner/$file"
done
# Arm a separate restoration timer before any controller state is changed.
armed=1
ssh_run "sudo -n systemd-run --unit=$unit-recover --on-active=140s --timer-property=AccuracySec=1s --property=RuntimeMaxSec=30 --property=TimeoutStopSec=5 /bin/bash '$remote/runner.sh' restore '$remote'"
ssh_run "sudo -n systemd-run --unit=$unit --property=RuntimeMaxSec=120 --property=TimeoutStopSec=5 --property=KillMode=control-group --property='ExecStopPost=/bin/bash $remote/runner.sh restore $remote' /bin/bash '$remote/runner.sh' collect '$remote'"
deadline=$((SECONDS+175))
while [ "$SECONDS" -lt "$deadline" ]; do
    if ssh_run "systemctl show '$unit.service' -p ActiveState --value" > "$out/unit-state.txt" 2>/dev/null; then
        if grep -Eq '^(inactive|failed)$' "$out/unit-state.txt"; then finished=1; break; fi
    fi
    sleep 3
done
# EXIT always restores, archives, checks health and records a final decision.
[ "$finished" = 1 ]
