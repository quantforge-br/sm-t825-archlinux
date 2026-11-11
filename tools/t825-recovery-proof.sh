#!/usr/bin/env bash
# Prove two automatic RAM-boot/reset cycles before enabling modem tests.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$HERE/artifacts/roadmap-7.3"
exec 9>"$HERE/artifacts/roadmap-7.3/tablet-test.lock"
flock -n 9 || { echo 'Another hardware test holds the tablet lock'; exit 2; }
image=${1:?usage: t825-recovery-proof.sh IMAGE REPORT_DIRECTORY}
out=${2:?report directory required}
minimum=${T825_PROOF_MIN_SECONDS:-0}
case "$minimum" in ''|*[!0-9]*) exit 2 ;; esac
[ "$minimum" -lt 150 ] || exit 2
umask 077
mkdir -p "$out"
exec > >(tee -a "$out/host.log") 2>&1
printf '%s\n' "started=$(date -u +%FT%TZ)"
sha256sum "$image" > "$out/image.sha256"
mapfile -t devices < <(timeout 5 fastboot devices | awk '$2 == "fastboot" { print $1 }')
[ "${#devices[@]}" -eq 1 ] || { echo 'Require exactly one fastboot device'; exit 2; }
serial=${devices[0]}
timeout 5 fastboot -s "$serial" getvar lk2nd:compatible 2> "$out/identity.txt"
grep -q 'lk2nd:compatible: samsung,gts3llte' "$out/identity.txt" || exit 2
printf 'cycle\telapsed_seconds\tresult\n' > "$out/results.tsv"
for cycle in 1 2; do
    start=$SECONDS
    timeout 20 fastboot -s "$serial" boot "$image" > "$out/boot-$cycle.txt" 2>&1
    echo "cycle $cycle: RAM image accepted; waiting for autonomous reset"
    disconnected=0
    recovered=0
    while [ "$((SECONDS - start))" -lt 150 ]; do
        if timeout 3 fastboot devices | awk -v serial="$serial" '$1 == serial && $2 == "fastboot" { yes=1 } END {exit !yes}'; then
            if [ "$disconnected" -eq 1 ]; then recovered=1; break; fi
        else
            disconnected=1
        fi
        sleep 2
    done
    elapsed=$((SECONDS - start))
    if [ "$recovered" -ne 1 ] || [ "$elapsed" -lt "$minimum" ]; then
        printf '%s\t%s\tFAIL_RECOVERY_GATE\n' "$cycle" "$elapsed" >> "$out/results.tsv"
        timeout 5 lsusb > "$out/usb-final.txt" 2>&1 || true
        timeout 5 adb devices > "$out/adb-final.txt" 2>&1 || true
        echo 'Recovery gate failed; no further boots will be launched.'
        exit 1
    fi
    printf '%s\t%s\tPASS_FASTBOOT_RETURN\n' "$cycle" "$elapsed" >> "$out/results.tsv"
    echo "cycle $cycle: returned to fastboot automatically after ${elapsed}s"
done
printf '%s\n' 'PASS: two autonomous reset cycles; device left in fastboot'
