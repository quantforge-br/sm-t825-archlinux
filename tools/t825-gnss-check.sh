#!/bin/sh
# shellcheck disable=SC2016
# Collect bounded MSS/QRTR/QMI-LOC evidence on an SM-T825 diagnostic boot.
# Default mode is read-only: no modem data, EFS, boot0 or calibration writes.
set -eu

usage() {
	cat <<'EOF'
Usage: tools/t825-gnss-check.sh [options]

Options:
  --output DIR       private report directory (default: ~/t825-runs/gnss-UTC)
  --device URI       QMI device, usually qrtr://<node>
  --start-loc        start a GNSS LOC session, then collect reports
  --timeout SECONDS  qmicli LOC timeout (default: 30)
  --help             show this help

Without --start-loc the script only probes LOC and reads current reports. It
never invokes NAS/WDS/UIM operations. Keep output private: reports may contain
coordinates.
EOF
}

out=${HOME}/t825-runs/gnss-$(date -u +%Y%m%dT%H%M%SZ)
device=
start_loc=0
timeout_s=30
while [ "$#" -gt 0 ]; do
	case "$1" in
		--output) [ "$#" -ge 2 ] || { echo "--output needs a directory" >&2; exit 2; }; out=$2; shift 2 ;;
		--device) [ "$#" -ge 2 ] || { echo "--device needs a URI" >&2; exit 2; }; device=$2; shift 2 ;;
		--start-loc) start_loc=1; shift ;;
		--timeout) [ "$#" -ge 2 ] || { echo "--timeout needs seconds" >&2; exit 2; }; timeout_s=$2; shift 2 ;;
		--help) usage; exit 0 ;;
		*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

case "$timeout_s" in
	''|*[!0-9]*) echo "--timeout must be a positive integer" >&2; exit 2 ;;
esac
[ "$timeout_s" -gt 0 ] || { echo "--timeout must be greater than zero" >&2; exit 2; }

umask 077
mkdir -m 700 -- "$out"
priv=
[ "$(id -u)" -eq 0 ] || priv="sudo -n"

run() {
	name=$1
	shift
	if timeout --kill-after=2s 45s "$@" >"$out/$name" 2>&1; then
		printf '%s\tPASS\n' "$name" >>"$out/status.tsv"
	else
		rc=$?
		printf '%s\tFAIL(%s)\n' "$name" "$rc" >>"$out/status.tsv"
	fi
}

run uname.txt uname -a
run cmdline.txt sh -c 'cat /proc/cmdline'
run model.txt sh -c 'tr "\\0" "\\n" </proc/device-tree/model'
run compatible.txt sh -c 'tr "\\0" "\\n" </proc/device-tree/compatible'
run remoteproc.txt sh -c '
	for d in /sys/class/remoteproc/remoteproc*; do
		[ -e "$d/name" ] || continue
		printf "[%s] " "$d"
		for attr in name state firmware; do
			[ -r "$d/$attr" ] || continue
			printf "%s=" "$attr"; cat "$d/$attr"
		done
	done
'
run rmtfs-service.txt systemctl --no-pager --full status rmtfs.service
run tqftpserv-service.txt systemctl --no-pager --full status tqftpserv.service
run qrtr-services.txt sh -c 'if command -v qrtr-lookup >/dev/null 2>&1; then qrtr-lookup; else exit 127; fi'
run kernel-dmesg.txt sh -c "$priv dmesg"

if [ -z "$device" ]; then
	printf '%s\n' 'No --device supplied; QMI probe skipped.' >"$out/qmi.txt"
	printf '%s\tBLOCKED(no-device)\n' qmi >>"$out/status.tsv"
elif ! command -v qmicli >/dev/null 2>&1; then
	printf '%s\n' 'qmicli unavailable' >"$out/qmi.txt"
	printf '%s\tUNAVAILABLE\n' qmi >>"$out/status.tsv"
else
	qmi_rc=0
	{
		printf 'device=%s\n' "$device"
		printf '\n--- LOC noop ---\n'; qmicli --device="$device" --loc-noop
		printf '\n--- LOC operation mode ---\n'; qmicli --device="$device" --loc-get-operation-mode
		printf '\n--- LOC NMEA types ---\n'; qmicli --device="$device" --loc-get-nmea-types
		printf '\n--- LOC position report ---\n'; qmicli --device="$device" --loc-timeout="$timeout_s" --loc-get-position-report
		printf '\n--- LOC GNSS SV info ---\n'; qmicli --device="$device" --loc-timeout="$timeout_s" --loc-get-gnss-sv-info
		if [ "$start_loc" -eq 1 ]; then
			printf '\n--- LOC start ---\n'; qmicli --device="$device" --loc-start
			printf '\n--- LOC position after start ---\n'; qmicli --device="$device" --loc-timeout="$timeout_s" --loc-get-position-report
			printf '\n--- LOC GNSS SV info after start ---\n'; qmicli --device="$device" --loc-timeout="$timeout_s" --loc-get-gnss-sv-info
			printf '\n--- LOC stop ---\n'; qmicli --device="$device" --loc-stop
		fi
	} >"$out/qmi.txt" 2>&1 || qmi_rc=$?
	if [ "$qmi_rc" -eq 0 ]; then
		printf '%s\tPASS\n' qmi >>"$out/status.tsv"
	else
		printf '%s\tFAIL(%s)\n' qmi "$qmi_rc" >>"$out/status.tsv"
	fi
fi

run kernel-dmesg-after.txt sh -c "$priv dmesg"
(manifest=$(mktemp)
	find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\n' |
		sort | xargs -r sha256sum >"$manifest"
	mv "$manifest" SHA256SUMS)
printf 'Report: %s\n' "$out"
