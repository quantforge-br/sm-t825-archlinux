#!/bin/sh
# Collect a redacted, non-destructive compatibility report from an SM-T825.
# This is the fast front door to ROADMAP.md. It does not enable the modem,
# write partitions, or save camera/microphone samples. Use --backup-dir only
# when an explicit private backup of modem calibration is intended.
# shellcheck disable=SC2016,SC2094
set -eu

usage() {
	cat <<'EOF'
Usage: tools/t825-check.sh [options]

Options:
  --output DIR       new report directory (default: ~/t825-runs/check-UTC)
  --backup-dir DIR   copy efs/modemst1/modemst2/fsg/fsc into DIR (private)
  --suspend          record the suspend follow-up requirement
  --help             show this help

The script is read-only unless --backup-dir is supplied. It uses sudo -n for
kernel logs and partition reads, so an interactive password prompt is never
started accidentally.
EOF
}

out=${HOME}/t825-runs/check-$(date -u +%Y%m%dT%H%M%SZ)
backup=
do_suspend=0
while [ "$#" -gt 0 ]; do
	case $1 in
		--output) [ "$#" -ge 2 ] || { echo "--output needs a directory" >&2; exit 2; }; out=$2; shift 2 ;;
		--backup-dir) [ "$#" -ge 2 ] || { echo "--backup-dir needs a directory" >&2; exit 2; }; backup=$2; shift 2 ;;
		--suspend) do_suspend=1; shift ;;
		--help) usage; exit 0 ;;
		*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

case "$(id -u)" in
	0) priv= ;;
	*) priv="sudo -n" ;;
esac
umask 077
mkdir -m 700 -- "$out"

run() {
	name=$1
	shift
	if timeout --kill-after=2s 30s "$@" >"$out/$name" 2>&1; then
		printf '%s\tPASS\n' "$name"
	else
		rc=$?
		case $rc in
			77) printf '%s\tBLOCKED(%s)\n' "$name" "$rc" ;;
			126|127) printf '%s\tUNAVAILABLE(%s)\n' "$name" "$rc" ;;
			124|137) printf '%s\tTIMEOUT(%s)\n' "$name" "$rc" ;;
			*) printf '%s\tFAIL(%s)\n' "$name" "$rc" ;;
		esac
	fi
}

audio_status() {
	if ! command -v wpctl >/dev/null 2>&1; then
		printf '%s\n' 'wpctl unavailable; run the baseline collector on the tablet image.' >&2
		return 127
	fi
	if [ -z "${XDG_RUNTIME_DIR:-}" ] || {
		[ ! -S "$XDG_RUNTIME_DIR/pipewire-0" ] &&
		[ ! -S "$XDG_RUNTIME_DIR/pulse/native" ];
	}; then
		printf '%s\n' 'PipeWire user session unavailable; run this check as the graphical desktop user.' >&2
		return 77
	fi
	wpctl status
}

redact() {
	sed -E 's/[0-9A-Fa-f]{14,}/<redacted>/g; s/\+?[0-9][0-9 -]{8,}[0-9]/<redacted>/g'
}

run uname.txt uname -a
run version.txt cat /proc/version
run cmdline.txt cat /proc/cmdline
run compatible.txt sh -c 'tr "\0" "\n" </proc/device-tree/compatible'
run model.txt sh -c 'tr "\0" "\n" </proc/device-tree/model'
run release.txt uname -r
run config.txt sh -c 'if [ -r /proc/config.gz ]; then gzip -dc /proc/config.gz; elif [ -r /boot/config-$(uname -r) ]; then cat /boot/config-$(uname -r); else exit 77; fi'
run remoteproc.txt sh -c 'for d in /sys/class/remoteproc/remoteproc*; do [ -e "$d/name" ] || continue; printf "[%s] " "$d"; cat "$d/name"; for a in state firmware; do [ -r "$d/$a" ] && printf "%s=" "$a" && cat "$d/$a"; done; done'
run network.txt ip -brief address
run wireless.txt iw dev
run bluetooth.txt bluetoothctl show
run audio.txt audio_status
run cameras.txt cam -l
run power.txt sh -c 'cat /sys/power/mem_sleep; for d in /sys/class/power_supply/*; do printf "[%s] " "$d"; for a in type status capacity online; do [ -r "$d/$a" ] && printf "%s=" "$a" && cat "$d/$a"; done; done'
run services.txt systemctl --no-pager --plain --type=service --state=running
run dmesg.txt sh -c "$priv dmesg"

if command -v qrtr-lookup >/dev/null 2>&1; then
	qrtr-lookup >"$out/qrtr-services.txt" 2>&1 || true
else
	printf '%s\n' 'qrtr-lookup unavailable' >"$out/qrtr-services.txt"
fi
redact <"$out/dmesg.txt" >"$out/dmesg-redacted.txt" || true

compatible=$(tr '\0' '\n' </proc/device-tree/compatible 2>/dev/null || true)
if printf '%s\n' "$compatible" | grep -qx 'samsung,gts3llte'; then
	printf 'device_tree=PASS\n'
else
	printf 'device_tree=FAIL\n'
fi

if [ -e /sys/bus/platform/devices/2080000.remoteproc ]; then
	printf 'mss=AVAILABLE\n'
else
	printf 'mss=DISABLED_OR_MISSING\n'
fi >"$out/status.txt"

if [ -n "$backup" ]; then
	mkdir -p -- "$backup"
	chmod 700 -- "$backup"
	for part in efs modemst1 modemst2 fsg fsc; do
		dev=/dev/disk/by-partlabel/$part
		if [ ! -e "$dev" ]; then
			printf '%s\tMISSING\n' "$part" >>"$out/backup.tsv"
			continue
		fi
		if $priv dd if="$dev" of="$backup/$part.img" bs=4M status=none; then
			sha256sum "$backup/$part.img" >>"$backup/SHA256SUMS"
			printf '%s\tCOPIED\n' "$part" >>"$out/backup.tsv"
		else
			printf '%s\tERROR\n' "$part" >>"$out/backup.tsv"
		fi
	done
	printf '%s\n' 'Calibration partitions are private; keep backup outside the repository.' \
		>"$out/backup-warning.txt"
else
	printf '%s\n' 'No calibration backup requested.' >"$out/backup.tsv"
fi

if [ "$do_suspend" = 1 ]; then
	printf '%s\n' 'Use tools/t825-validate.py suspend with an explicit Wi-Fi peer for a bounded check.' \
		>"$out/suspend.txt"
fi

(cd "$out" && find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)
printf 'Report: %s\n' "$out"
