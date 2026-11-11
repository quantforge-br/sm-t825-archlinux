#!/bin/sh
# Verify private inputs for an MSS/GNSS RAM boot without touching the tablet.
set -eu

usage() {
	cat <<'EOF'
Usage: tools/t825-gnss-preflight.sh --firmware DIR --backup DIR [--report FILE]

DIR must contain firmware extracted with EXTRACT_MSS=1 and a private backup
containing efs, modemst1, modemst2, fsg and fsc images. The report contains
paths, sizes and hashes, never firmware contents.
EOF
}

firmware=
backup=
report=
while [ "$#" -gt 0 ]; do
	case "$1" in
		--firmware) [ "$#" -ge 2 ] || { echo "--firmware needs a directory" >&2; exit 2; }; firmware=$2; shift 2 ;;
		--backup) [ "$#" -ge 2 ] || { echo "--backup needs a directory" >&2; exit 2; }; backup=$2; shift 2 ;;
		--report) [ "$#" -ge 2 ] || { echo "--report needs a file" >&2; exit 2; }; report=$2; shift 2 ;;
		--help) usage; exit 0 ;;
		*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done
[ -n "$firmware" ] && [ -n "$backup" ] || { usage >&2; exit 2; }
firmware=$(realpath -- "$firmware")
backup=$(realpath -- "$backup")
[ -d "$firmware" ] || { echo "firmware directory does not exist: $firmware" >&2; exit 1; }
[ -d "$backup" ] || { echo "backup directory does not exist: $backup" >&2; exit 1; }

if [ -z "$report" ]; then
	report=${TMPDIR:-/tmp}/t825-gnss-preflight-$(date -u +%Y%m%dT%H%M%SZ).txt
else
	report=$(realpath -m -- "$report")
fi
mkdir -p -- "$(dirname "$report")"
umask 077
: >"$report"
chmod 600 "$report"

pass=1
record() {
	status=$1
	label=$2
	detail=$3
	printf '%s\t%s\t%s\n' "$status" "$label" "$detail" >>"$report"
	[ "$status" = PASS ] || pass=0
}

private_path() {
	label=$1
	path=$2
	mode=$(stat -c '%a' "$path")
	if [ $((mode % 100)) -eq 0 ]; then
		record PASS "$label" "mode=$mode"
	else
		record BLOCKED "$label" "must-be-owner-only mode=$mode"
	fi
}

private_path firmware_root "$firmware"
private_path backup_root "$backup"
if find "$firmware" -type f -perm /077 -print -quit | grep -q .; then
	record BLOCKED firmware_permissions "a firmware file is group/world-readable"
else
	record PASS firmware_permissions "files have no group/world bits"
fi
if find "$firmware" -type l -print -quit | grep -q .; then
	record BLOCKED firmware_symlinks "symlinks are not allowed in the firmware tree"
else
	record PASS firmware_symlinks "no firmware symlinks"
fi
if find "$backup" -type f -perm /077 -print -quit | grep -q .; then
	record BLOCKED backup_permissions "a backup file is group/world-readable"
else
	record PASS backup_permissions "files have no group/world bits"
fi
if find "$backup" -type l -print -quit | grep -q .; then
	record BLOCKED backup_symlinks "symlinks are not allowed in the backup"
else
	record PASS backup_symlinks "no backup symlinks"
fi

check_file() {
	label=$1
	path=$2
	if [ -L "$path" ]; then
		record BLOCKED "$label" "symlink-not-allowed path=$path"
	elif [ -f "$path" ] && [ -s "$path" ]; then
		mode=$(stat -c '%a' "$path")
		hash=$(sha256sum "$path" | cut -d' ' -f1)
		if [ $((mode % 100)) -eq 0 ]; then
			record PASS "$label" "size=$(stat -c '%s' "$path") mode=$mode sha256=$hash"
		else
			record BLOCKED "$label" "must-be-owner-only mode=$mode"
		fi
	else
		record BLOCKED "$label" "missing-or-empty path=$path"
	fi
}

modem="$firmware/qcom/msm8996/samsung/gts3"
check_file mba "$modem/mba.mbn"
check_file modem_mdt "$modem/modem.mdt"
segments=$(find "$modem" -maxdepth 1 -type f -name 'modem.b[0-9]*' | sort)
if [ -n "$segments" ]; then
	count=$(printf '%s\n' "$segments" | awk 'NF { n++ } END { print n+0 }')
	bad=$(printf '%s\n' "$segments" | awk '$0 !~ /\/modem\.b[0-9]+$/ { n++ } END { print n+0 }')
	if [ "$bad" -eq 0 ]; then
		record PASS modem_segments "count=$count"
	else
		record BLOCKED modem_segments "invalid-segment-name"
	fi
else
	record BLOCKED modem_segments "no modem.b* files under $modem"
fi

modem_pr="$modem/modem_pr"
if [ -d "$modem_pr" ]; then
	count=$(find "$modem_pr" -type f | awk 'NF { n++ } END { print n+0 }')
	if [ "$count" -gt 0 ]; then
		record PASS modem_pr "files=$count"
	else
		record BLOCKED modem_pr "tree-is-empty"
	fi
else
	record BLOCKED modem_pr "directory-missing path=$modem_pr"
fi

for part in efs modemst1 modemst2 fsg fsc; do
	if [ -L "$backup/$part.img" ]; then
		record BLOCKED "backup_$part" "symlink-not-allowed path=$backup/$part.img"
	elif [ -f "$backup/$part.img" ] && [ -s "$backup/$part.img" ]; then
		mode=$(stat -c '%a' "$backup/$part.img")
		hash=$(sha256sum "$backup/$part.img" | cut -d' ' -f1)
		if [ $((mode % 100)) -eq 0 ]; then
			record PASS "backup_$part" "size=$(stat -c '%s' "$backup/$part.img") mode=$mode sha256=$hash"
		else
			record BLOCKED "backup_$part" "must-be-owner-only mode=$mode"
		fi
	else
		record BLOCKED "backup_$part" "missing-or-empty path=$backup/$part.img"
	fi
done

if [ -f "$backup/SHA256SUMS" ]; then
	if (cd "$backup" && sha256sum -c SHA256SUMS >/dev/null 2>&1); then
		record PASS backup_hashes "SHA256SUMS verified"
	else
		record BLOCKED backup_hashes "SHA256SUMS mismatch"
	fi
else
	record BLOCKED backup_hashes "SHA256SUMS missing"
fi

record PASS production_dt_unchanged "preflight does not alter or install a DTB"
printf '\nresult=%s\n' "$( [ "$pass" -eq 1 ] && printf READY || printf BLOCKED )" >>"$report"
printf 'Report: %s\n' "$report"
[ "$pass" -eq 1 ]
