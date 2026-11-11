#!/usr/bin/env bash
# Capture pclk RCG state immediately before and after one bounded s2idle cycle.
# Historical runner: RTC wake is not independent recovery from suspend failure.
set -euo pipefail
require_suspend_recovery() {
    printf '%s\n' 'BLOCKED_SUSPEND_RECOVERY: this historical runner lacks independent recovery and verified suspend/log continuity. See docs/display-clock-7.3.md.' >&2
    return 2
}
require_suspend_recovery
HERE=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$HERE"
target=${T825_SSH_TARGET:-tabs3}
seconds=${T825_PCLK_SUSPEND_SECONDS:-15}
out=${T825_PCLK_REPORT_DIR:-artifacts/roadmap-7.3/pclk-suspend-$(date -u +%Y%m%dT%H%M%SZ)}
umask 077
mkdir -p "$out/runner"
case "$seconds" in ''|*[!0-9]*) exit 2 ;; esac
[ "$seconds" -ge 10 ] && [ "$seconds" -le 60 ] || exit 2
cp "$0" "$out/runner/t825-pclk-suspend-test.sh"
sha256sum "$out/runner/t825-pclk-suspend-test.sh" > "$out/runner.sha256"
printf '%s\n' "target=$target" "suspend_seconds=$seconds" "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$out/identity.txt"
printf '%s\n' "$$" > "$out/host.pid"
remote=$(cat <<'REMOTE'
set -eu
seconds=${T825_PCLK_SUSPEND_SECONDS:?}
base=/tmp/t825-pclk-$$
before_clk=$base.before.clk
before_dmesg=$base.before.dmesg
after_clk=$base.after.clk
after_dmesg=$base.after.dmesg
cleanup() { sudo -n rm -f "$before_clk" "$before_dmesg" "$after_clk" "$after_dmesg" /tmp/t825-pclk-rtcwake; }
trap cleanup EXIT
sudo -n sh -c "cat /sys/kernel/debug/clk/clk_summary > '$before_clk'; dmesg > '$before_dmesg'"
if ! sudo -n rtcwake -m mem -s "$seconds" >/tmp/t825-pclk-rtcwake 2>&1; then
  cat /tmp/t825-pclk-rtcwake
  exit 77
fi
sudo -n sh -c "cat /sys/kernel/debug/clk/clk_summary > '$after_clk'; dmesg > '$after_dmesg'"
printf '%s\n' '--- before pclk state ---'; grep -E 'pclk[01]_clk_src' "$before_clk" || true
printf '%s\n' '--- after pclk state ---'; grep -E 'pclk[01]_clk_src' "$after_clk" || true
printf '%s\n' '--- new pclk messages ---'
diff -u "$before_dmesg" "$after_dmesg" | grep -E '^\+.*(pclk[01]_clk_src|rcg.*update)' || true
printf '%s\n' '--- rtcwake ---'; cat /tmp/t825-pclk-rtcwake
REMOTE
)
if timeout --kill-after=10s 90 ssh -o BatchMode=yes -o ConnectTimeout=5 "$target" \
  "T825_PCLK_SUSPEND_SECONDS=$seconds sh -s" <<<"$remote" > "$out/remote.txt" 2>&1; then
  status=0
else
  status=$?
fi
printf '%s\n' "$status" > "$out/ssh-status.txt"
if [ "$status" -eq 0 ]; then
  printf '%s\n' 'PASS: captured clock state before and after bounded suspend.' > "$out/result.txt"
elif [ "$status" -eq 77 ]; then
  printf '%s\n' 'BLOCKED: rtcwake/s2idle was unavailable.' > "$out/result.txt"
else
  printf '%s\n' 'FAIL: SSH collection or suspend timed out.' > "$out/result.txt"
fi
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + | sort > .SHA256SUMS.new && mv .SHA256SUMS.new SHA256SUMS)
printf 'Report: %s\n' "$out"
exit "$status"
