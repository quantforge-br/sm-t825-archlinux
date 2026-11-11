#!/bin/sh
# Read-only PM8994 PON snapshot for watchdog/reset attribution on an SM-T825.
# Reads only PON 0x800-0x80f and the PMIC watchdog block 0x854-0x858 through
# regmap debugfs at fixed offsets. It never writes a register, loads a driver
# or reboots. Usage on the host: ssh tabs3 sh -s < tools/t825-pmic-pon-snapshot.sh
set -eu
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
echo "kernel=$(uname -r)"
echo "utc=$(date -u +%FT%TZ)"
sudo -n sh -s <<'EOF'
set -eu
R=/sys/kernel/debug/regmap/0-00
[ "$(cat "$R/name")" = pmic-spmi ] || { echo "unexpected regmap $R" >&2; exit 2; }
# Each debugfs line is "rrrr: vv\n" (9 bytes) for this 0-ffff byte regmap.
[ "$(cat "$R/range")" = 0-ffff ] || { echo "unexpected regmap range" >&2; exit 2; }
echo "regmap=$R name=$(cat "$R/name") range=$(cat "$R/range")"
dd if="$R/registers" bs=9 skip=$((0x800)) count=16 2>/dev/null
dd if="$R/registers" bs=9 skip=$((0x854)) count=5 2>/dev/null
ls /dev/watchdog* 2>&1 || true
EOF
