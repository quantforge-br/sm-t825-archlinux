#!/usr/bin/env bash
# Host wrapper: one microphone lifecycle probe with independent ALSA restoration.
set -euo pipefail
export LC_ALL=C
root=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$root"
target=${T825_SSH_TARGET:-tabs3}
out=${T825_MIC_REPORT:-artifacts/roadmap-7.3/audio-mic-phases-$(date -u +%Y%m%dT%H%M%SZ)}
umask 077
mkdir -p "$out"
out=$(realpath "$out")
if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
    mkdir -p "$out/runner"
    cp tools/t825-audio-mic-phases.{sh,py} tools/t825-audio-mic-restore.sh tools/t825-validate.py "$out/runner/"
    sha256sum "$out/runner/"* > "$out/runner.sha256"
    exec env T825_SOURCE_ROOT="$root" T825_RUNNER_SNAPSHOT=1 T825_MIC_REPORT="$out" bash "$out/runner/t825-audio-mic-phases.sh"
fi
exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }
printf '%s\n' "$$" > "$out/host.pid"
stamp=$(date -u +%Y%m%d%H%M%S)
remote=/run/t825-mic-phases-$stamp
unit=t825-mic-phases-$stamp
ssh_run() { timeout --kill-after=2s 12 ssh -o BatchMode=yes -o ConnectTimeout=5 -o ServerAliveInterval=3 -o ServerAliveCountMax=2 "$target" "$@"; }
armed=0
finished=0
restored=0
archive_status=not_attempted
timer_stopped=0
finalize() {
    status=$?
    trap - EXIT
    set +e
    if [ "$armed" = 1 ]; then
        # Restore after collection terminates. If the unit is still running,
        # leave its RuntimeMaxSec and independent timer responsible for cleanup.
        if [ "$finished" = 1 ]; then
            if timeout --kill-after=2s 35 ssh -o BatchMode=yes -o ConnectTimeout=5 "$target" "sudo -n /bin/bash '$remote/t825-audio-mic-restore.sh' '$remote'" > "$out/restore-request.txt" 2>&1; then restored=1; fi
        fi
        timeout --kill-after=2s 20 ssh -o BatchMode=yes -o ConnectTimeout=5 "$target" "sudo -n tar -C '$remote' -cf - ." > "$out/remote.tar" 2> "$out/archive.stderr"
        archive_status=$?
        mkdir -p "$out/remote"
        if [ "$archive_status" = 0 ]; then tar -xf "$out/remote.tar" -C "$out/remote"; archive_status=$?; fi
        if [ "$finished:$restored" = 1:1 ]; then
            if ssh_run "sudo -n systemctl stop '$unit-recover.timer'" > "$out/timer-stop.txt" 2>&1; then timer_stopped=1; fi
        fi
    fi
    if [ "$finished:$restored:$archive_status:$timer_stopped" != 1:1:0:1 ]; then status=1; fi
    if ! python3 - "$out/remote/decision.json" <<'PY'
import json
from pathlib import Path
import sys
try:
    decision = json.loads(Path(sys.argv[1]).read_text())
    passed = decision['status'] == 'PASS' and decision['boot_unchanged'] and decision['captures_completed'] == decision['requested'] == 1
except (OSError, ValueError, KeyError):
    passed = False
sys.exit(0 if passed else 1)
PY
    then status=1; fi
    printf '%s\n' "finished=$finished" "mixer_restored=$restored" "archive_status=$archive_status" \
        "recovery_timer_stopped=$timer_stopped" "exit_status=$status" > "$out/result.txt"
    # shellcheck disable=SC2094
    (cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS ! -name host.log -exec sha256sum {} + > SHA256SUMS)
    echo "Report: $out"
    exit "$status"
}
trap finalize EXIT
printf '%s\n' "target=$target" "unit=$unit" "remote=$remote" > "$out/identity.txt"
ssh_run 'systemctl is-system-running || true; uname -a; cat /proc/sys/kernel/random/boot_id' > "$out/baseline.txt"
ssh_run "sudo -n mkdir -m700 '$remote'"
for file in t825-audio-mic-phases.py t825-audio-mic-restore.sh t825-validate.py; do
    ssh_run "sudo -n tee '$remote/$file' >/dev/null" < "$out/runner/$file"
done
ssh_run "sudo -n timeout --kill-after=2s 8 alsactl -f '$remote/mixer-before.state' store 0"
# No UCM/PCM mutation until both the independent timer and its active state
# have been confirmed. The collector runs separately from the SSH connection.
armed=1
ssh_run "sudo -n systemd-run --unit=$unit-recover --on-active=120s --timer-property=AccuracySec=1s --property=RuntimeMaxSec=30 --property=TimeoutStopSec=5 /bin/bash '$remote/t825-audio-mic-restore.sh' '$remote'"
ssh_run "systemctl is-active '$unit-recover.timer' && sudo -n touch '$remote/restoration-armed'"
ssh_run "sudo -n systemd-run --unit=$unit --property=RuntimeMaxSec=75 --property=TimeoutStopSec=5 --property=KillMode=control-group --property='ExecStopPost=/bin/bash $remote/t825-audio-mic-restore.sh $remote' /usr/bin/python3 '$remote/t825-audio-mic-phases.py' --output '$remote'"
deadline=$((SECONDS+145))
while [ "$SECONDS" -lt "$deadline" ]; do
    if ssh_run "systemctl show '$unit.service' -p ActiveState -p Result" > "$out/unit-state.txt" 2>/dev/null && grep -Eq '^ActiveState=(inactive|failed)$' "$out/unit-state.txt"; then
        finished=1
        break
    fi
    sleep 2
done
[ "$finished" = 1 ] && grep -q '^Result=success$' "$out/unit-state.txt"
