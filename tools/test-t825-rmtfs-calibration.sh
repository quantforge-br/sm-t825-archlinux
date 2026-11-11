#!/bin/sh
# Regression test for the private T825 rmtfs filename adapter.
set -eu

runtime_root=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
root=$(mktemp -d "$runtime_root/t825-rmtfs-test.XXXXXX")
trap 'chmod -R u+rwx "$root" 2>/dev/null || true; rm -rf "$root"' EXIT
src=$root/src
dst=$root/run-rmtfs
mkdir -p "$src" "$dst"
chmod 700 "$src" "$dst"
for name in modem_fs1 modem_fs2 modem_fsg modem_fsc; do
	printf '%s\n' "$name" >"$src/$name"
	chmod 600 "$src/$name"
done

T825_MSS_CALIBRATION_DIR="$src" T825_RMTFS_DIR="$dst" \
	install/t825-prepare-rmtfs-calibration.sh

for name in modemst1 modemst2 fsg fsc; do
	test -f "$dst/$name"
	case "$name" in
		modemst1) expected=modem_fs1 ;;
		modemst2) expected=modem_fs2 ;;
		fsg) expected=modem_fsg ;;
		fsc) expected=modem_fsc ;;
	esac
	test "$(cat "$dst/$name")" = "$expected"
	test "$(stat -c '%a' "$dst/$name")" = 600
done
test ! -e "$dst/modem_fs1"
echo 'T825 rmtfs calibration mapping checks passed'
