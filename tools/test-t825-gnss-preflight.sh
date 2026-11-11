#!/bin/sh
# Regression test for the GNSS input gate; uses synthetic files only.
set -eu

root=$(mktemp -d "${TMPDIR:-/tmp}/t825-preflight-test.XXXXXX")
trap 'chmod -R u+rwx "$root" 2>/dev/null || true; rm -rf "$root"' EXIT
firmware=$root/firmware
backup=$root/backup
modem=$firmware/qcom/msm8996/samsung/gts3
mkdir -p "$modem/modem_pr" "$backup"
chmod 700 "$firmware" "$backup" "$firmware/qcom" "$firmware/qcom/msm8996" \
	"$firmware/qcom/msm8996/samsung" "$modem" "$modem/modem_pr"
for f in mba.mbn modem.mdt modem.b00 modem.b01; do
	printf '%s\n' "$f" >"$modem/$f"
	done
printf '%s\n' mcfg >"$modem/modem_pr/mcfg.mbn"
for p in efs modemst1 modemst2 fsg fsc; do
	printf '%s\n' "$p" >"$backup/$p.img"
done
for f in "$modem"/*.mbn "$modem"/*.mdt "$modem"/*.b*; do
	chmod 600 "$f"
done
chmod 600 "$modem/modem_pr"/* "$backup"/*.img
find "$firmware" -type d -exec chmod 700 {} +
sha256sum "$backup"/*.img >"$backup/SHA256SUMS"
chmod 600 "$backup/SHA256SUMS"

report=$root/ready.txt
tools/t825-gnss-preflight.sh --firmware "$firmware" --backup "$backup" --report "$report"
grep -qx 'result=READY' "$report"

chmod 644 "$backup/fsg.img"
if tools/t825-gnss-preflight.sh --firmware "$firmware" --backup "$backup" --report "$root/blocked.txt"; then
	echo 'preflight accepted a world-readable calibration dump' >&2
	exit 1
fi
grep -qx 'result=BLOCKED' "$root/blocked.txt"
echo 'GNSS preflight regression checks passed'
