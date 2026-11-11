#!/usr/bin/env bash
# Exercise T825 UCM playback/capture routes without saving audio samples.
# Remote ALSA state is restored after every cycle; the host runner is detached.
set -euo pipefail
HERE=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
cd "$HERE"
out=${T825_AUDIO_REPORT_DIR:-artifacts/roadmap-7.3/audio-routes-$(date -u +%Y%m%dT%H%M%SZ)}
target=${T825_SSH_TARGET:-tabs3}
cycles=${T825_AUDIO_CYCLES:-20}
wait_s=${T825_AUDIO_WAIT_SECONDS:-30}
umask 077
mkdir -p "$out"
if [ "${T825_RUNNER_SNAPSHOT:-0}" != 1 ]; then
	mkdir -p "$out/runner"
	cp "$HERE/tools/t825-audio-route-cycle.sh" "$out/runner/t825-audio-route-cycle.sh"
	sha256sum "$out/runner/t825-audio-route-cycle.sh" > "$out/runner.sha256"
	exec env T825_SOURCE_ROOT="$HERE" T825_RUNNER_SNAPSHOT=1 T825_AUDIO_REPORT_DIR="$out" \
		bash "$out/runner/t825-audio-route-cycle.sh" "$@"
fi
exec 9>artifacts/roadmap-7.3/tablet-test.lock
flock -n 9 || { echo 'Another hardware test holds the tablet lock' >&2; exit 2; }
case "$cycles:$wait_s" in *[!0-9:]*|:*|*:) exit 2 ;; esac
[ "$cycles" -gt 0 ] && [ "$cycles" -le 20 ] && [ "$wait_s" -ge 10 ] && [ "$wait_s" -le 120 ] || exit 2
printf '%s\n' "target=$target" "cycles=$cycles" "wait_seconds=$wait_s" > "$out/identity.txt"
printf 'cycle\tspeaker\theadphones\tmicrophone\tkernel_faults\telapsed_seconds\n' > "$out/results.tsv"
printf '%s\n' "$$" > "$out/host.pid"
remote_cycle() {
	timeout "$wait_s" ssh -o BatchMode=yes -o ConnectTimeout=5 -o ConnectionAttempts=1 "$target" 'sh -s' <<'REMOTE'
set -eu
state=/tmp/t825-audio-state.$$
log=/tmp/t825-audio-dmesg.$$
start=/tmp/t825-audio-start.$$
cleanup() {
	if [ -s "$state" ]; then sudo -n alsactl -f "$state" restore 0 >/dev/null 2>&1 || true; fi
	sudo -n rm -f "$state" "$log" "$start" /tmp/t825-audio-*.txt
}
trap cleanup EXIT
sudo -n alsactl -f "$state" store 0
sudo -n dmesg | tail -1 | sed -n 's/^\[[[:space:]]*\([0-9.]*\)\].*/\1/p' > "$start"
run_ucm() { printf '%s\n' "$@" | alsaucm -c hw:0 -b -; }
speaker=FAIL
headphones=FAIL
microphone=FAIL
run_ucm 'set _verb HiFi' 'set _enadev Speaker' >/tmp/t825-audio-speaker.txt 2>&1 && \
	timeout 12 speaker-test -D hw:0,0 -c 2 -t sine -l 1 >/tmp/t825-audio-speaker-run.txt 2>&1 && speaker=PASS || true
run_ucm 'set _verb HiFi' 'set _enadev Headphones' >/tmp/t825-audio-headphones.txt 2>&1 && \
	timeout 12 speaker-test -D hw:0,1 -c 2 -t sine -l 1 >/tmp/t825-audio-headphones-run.txt 2>&1 && headphones=PASS || true
run_ucm 'set _verb HiFi' 'set _enadev Mic' >/tmp/t825-audio-mic.txt 2>&1 && \
	timeout 12 arecord -D hw:0,2 -f S16_LE -r 48000 -c 2 -d 1 -t raw /dev/null >/tmp/t825-audio-mic-run.txt 2>&1 && microphone=PASS || true
sudo -n dmesg > "$log"
start_ts=$(cat "$start")
awk -v start="$start_ts" '/^\[[[:space:]]*[0-9.]+\]/ { line=$0; x=$0; sub(/^\[[[:space:]]*/,"",x); sub(/\].*/,"",x); if ((x+0) > (start+0)) print line }' "$log" | grep -Ei 'wcd9335|overflow|slim|tdm|aif|micbias|snd|audio' | tail -120 > /tmp/t825-audio-new-kernel.txt || true
faults=0
if grep -Eiq 'wcd9335.*overflow|Internal error|kernel panic|oops|slim.*(error|fail)|tdm.*(error|fail)|aif.*(error|fail)' /tmp/t825-audio-new-kernel.txt; then faults=1; fi
printf 'speaker=%s\nheadphones=%s\nmicrophone=%s\nkernel_faults=%s\n' "$speaker" "$headphones" "$microphone" "$faults"
printf '%s\n' '--- speaker route ---'; cat /tmp/t825-audio-speaker.txt /tmp/t825-audio-speaker-run.txt 2>/dev/null || true
printf '%s\n' '--- headphones route ---'; cat /tmp/t825-audio-headphones.txt /tmp/t825-audio-headphones-run.txt 2>/dev/null || true
printf '%s\n' '--- microphone route ---'; cat /tmp/t825-audio-mic.txt /tmp/t825-audio-mic-run.txt 2>/dev/null || true
printf '%s\n' '--- new audio kernel lines ---'; cat /tmp/t825-audio-new-kernel.txt
REMOTE
}
result=0
for cycle in $(seq 1 "$cycles"); do
	started=$SECONDS
	log="$out/cycle-$cycle.txt"
	if remote_cycle > "$log" 2>&1; then
		speaker=$(sed -n 's/^speaker=//p' "$log" | head -1)
		headphones=$(sed -n 's/^headphones=//p' "$log" | head -1)
		microphone=$(sed -n 's/^microphone=//p' "$log" | head -1)
		faults=$(sed -n 's/^kernel_faults=//p' "$log" | head -1)
	else
		speaker=TIMEOUT; headphones=TIMEOUT; microphone=TIMEOUT; faults=UNKNOWN
	fi
	[ "$speaker" = PASS ] && [ "$headphones" = PASS ] && [ "$microphone" = PASS ] && [ "$faults" = 0 ] || result=1
	printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$cycle" "$speaker" "$headphones" "$microphone" "$faults" "$((SECONDS-started))" >> "$out/results.tsv"
	echo "cycle $cycle/$cycles: speaker=$speaker headphones=$headphones microphone=$microphone kernel_faults=$faults"
done
(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + | sort > .SHA256SUMS.new && mv .SHA256SUMS.new SHA256SUMS)
echo "Report: $out"
exit "$result"
