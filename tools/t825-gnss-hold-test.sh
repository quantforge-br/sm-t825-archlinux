#!/usr/bin/env bash
# Collect a transient boot without cancelling its independent recovery deadline.
# shellcheck disable=SC2016 # Commands inside the remote shell must expand there.
set -euo pipefail
HERE=${T825_SOURCE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
runner=$(cd "$(dirname "$0")" && pwd)
image=${1:-$HERE/artifacts/roadmap-7.3/gnss-ram-20261108/v63-mss-loc-retry-ro/t825-v63.img}
out=${2:-$HERE/artifacts/roadmap-7.3/gnss-ram-20261108/hardware-v31-$(date -u +%Y%m%dT%H%M%SZ)}
serial=${T825_SERIAL:?run through t825-gnss-auto-cycle.sh or set verified T825_SERIAL}
[ -f "$image" ] || { echo "missing RAM image: $image" >&2; exit 2; }
umask 077
mkdir -p "$out"
sha256sum "$image" > "$out/image.sha256"
started=$SECONDS
# One absolute deadline includes probe time; failed SSH must not be a PASS.
limit=$((started + 220))
shell_limit=$((started + 90))
# shellcheck disable=SC2317
status() { printf '%s\n' "$*" > "$out/status.txt"; }
handoff_listener=
handoff_firewall=0
firewall_rule=(-s 172.16.42.1 -d 172.16.42.2 -p tcp --dport 2324 -m comment --comment t825-transient-handoff -j ACCEPT)
# shellcheck disable=SC2329 # Invoked by the EXIT trap.
cleanup() {
	if [ -n "$handoff_listener" ]; then
		kill "$handoff_listener" 2>/dev/null || true
		wait "$handoff_listener" 2>/dev/null || true
	fi
	if [ "$handoff_firewall" = 1 ]; then
		sudo -n iptables -w 3 -D INPUT "${firewall_rule[@]}" 2>/dev/null || true
	fi
	find "$out" -maxdepth 1 -type f ! -name SHA256SUMS -exec sha256sum {} + > "$out/SHA256SUMS"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT
timeout 20 fastboot -s "$serial" boot "$image" > "$out/fastboot.txt" 2>&1
disconnect_limit=$((SECONDS + 12))
while timeout 3 fastboot devices | awk -v serial="$serial" '$1 == serial && $2 == "fastboot" {found=1} END {exit !found}'; do
	[ "$SECONDS" -lt "$disconnect_limit" ] || { status 'FAIL: image accepted but fastboot never disconnected'; exit 1; }
	sleep 1
done
printf '%s\n' 'fastboot disappearance observed after RAM boot' > "$out/boot-disconnected"
ip -brief link > "$out/host-link-before-debug.txt" 2>&1 || true
lsusb > "$out/host-usb-before-debug.txt" 2>&1 || true
ready=0
while [ "$SECONDS" -lt "$shell_limit" ]; do
	probe=$(printf '%s\r\n' 'echo T825_DEBUG_READY' | timeout 3 nc -N 172.16.42.1 23 2>/dev/null || true)
	printf '%s\n' "$probe" > "$out/debug-probe.txt"
	if tr -d '\r' < "$out/debug-probe.txt" | grep -qx 'T825_DEBUG_READY'; then ready=1; break; fi
	sleep 1
done
[ "$ready" = 1 ] || { status 'FAIL: initial debug shell unavailable; recovery remains armed'; exit 1; }
# This shell is BEFORE hooks-extra: missing MSS here is not modem failure.
# shellcheck disable=SC2016
{
	printf '%s\n' 'echo --- initial-shell-before-hooks-extra ---' 'uname -a' 'cat /proc/cmdline'
	printf '%s\n' 'cat /run/t825-recovery/supervisor.log' 'cat /run/t825-recovery/supervisor.pid'
	printf '%s\n' 'tail -60 /pmOS_init.log'
} | timeout 15 python3 "$runner/t825-telnet.py" --host 172.16.42.1 --port 23 > "$out/pre-hooks.txt" 2>&1 || true
# Receive handoff-stage markers over the host side of the USB network.  The
# listener is independent of the telnet/SSH sessions, so it remains useful if
# those sessions are killed or reset during switch_root.
socat -u TCP-LISTEN:2324,bind=172.16.42.2,reuseaddr,fork - \
	>"$out/handoff-network.txt" 2>"$out/handoff-network.log" &
handoff_listener=$!
# The host firewall may drop incoming stage reports even though outbound
# telnet works. Add only a temporary rule for this USB peer and destination;
# cleanup removes it on every normal or failed collector exit.
# shellcheck disable=SC2024 # The report belongs to the host user, not root.
if sudo -n iptables -w 3 -I INPUT 1 "${firewall_rule[@]}" >"$out/handoff-firewall.log" 2>&1; then
	handoff_firewall=1
fi
# The native marker releases both the original shell and the later hold hook.
printf '%s\n' 'touch /tmp/continue_boot; echo T825_RELEASED' | timeout 10 python3 "$runner/t825-telnet.py" --host 172.16.42.1 --port 23 > "$out/release.txt" 2>&1 || true
ip -brief link > "$out/host-link-after-release.txt" 2>&1 || true
lsusb > "$out/host-usb-after-release.txt" 2>&1 || true
# In inspect mode the MSS hook intentionally remains in initramfs. Collect LOC
# while QRTR/qmicli are alive, then release the root handoff explicitly.
{
	printf '%s\n' 'sleep 5' \
		'for i in 1 2 3 4; do qmicli --device=qrtr://0 --loc-noop >/run/t825-mssdiag/loc-noop-$i.log 2>&1 && break; sleep 2; done' \
		'echo --- initramfs-gnss-position ---' \
		'/usr/bin/busybox timeout 25 qmicli --device=qrtr://0 --loc-get-position-report 2>&1 || true' \
		'echo --- initramfs-gnss-sv ---' \
		'/usr/bin/busybox timeout 25 qmicli --device=qrtr://0 --loc-get-gnss-sv-info 2>&1 || true'
} | timeout 60 python3 "$runner/t825-telnet.py" --host 172.16.42.1 --port 23 > "$out/initramfs-gnss.txt" 2>&1 || true
printf '%s\n' 'touch /run/t825-mssdiag/continue-pivot; echo T825_PIVOT_RELEASED' |
	timeout 10 python3 "$runner/t825-telnet.py" --host 172.16.42.1 --port 23 > "$out/pivot-release.txt" 2>&1 || true
# A lingering initramfs telnet listener distinguishes a failed switch_root
# from a post-pivot SSH failure. This probe is read-only and is not a success
# criterion.
{
	printf '%s\n' 'echo --- handoff-observation ---' 'cat /proc/1/cmdline'
	printf '%s\n' 'test -e /tmp/continue_boot; echo continue_boot=$?'
	printf '%s\n' 'test -e /run/t825-mssdiag/continue-pivot; echo continue_pivot=$?'
	printf '%s\n' 'cat /run/t825-recovery/handoff-stage 2>/dev/null || true'
	printf '%s\n' 'tail -80 /pmOS_init.log' 'dmesg | tail -60' 'cat /proc/1/wchan' 'ps -ef'
	printf '%s\n' 'echo --- bounded-gnss-position ---' \
		'/usr/bin/busybox timeout 20 qmicli --device=qrtr://0 --loc-get-position-report 2>&1 || true' \
		'echo --- bounded-gnss-sv ---' \
		'/usr/bin/busybox timeout 20 qmicli --device=qrtr://0 --loc-get-gnss-sv-info 2>&1 || true'
	} | timeout 55 python3 "$runner/t825-telnet.py" --host 172.16.42.1 --port 23 > "$out/handoff-telnet.txt" 2>&1 || true
# If the original debug shell disappeared during switch_root, query the
# independent port-2323 listener staged by direct-init.  This distinguishes a
# root handoff failure from an SSH-only failure without requiring a reboot.
{
	printf '%s\n' 'echo --- postpivot-inspection ---' 'cat /proc/1/cmdline'
	printf '%s\n' 'cat /run/t825-recovery/handoff-stage 2>/dev/null || true'
	printf '%s\n' 'cat /run/t825-recovery/direct-init.log 2>/dev/null || true'
	printf '%s\n' 'cat /run/t825-recovery/direct-sshd.log 2>/dev/null || true'
	printf '%s\n' 'ss -lnt 2>/dev/null || true'
} | timeout 10 python3 "$runner/t825-telnet.py" --host 172.16.42.1 --port 2323 > "$out/postpivot-telnet.txt" 2>&1 || true
while [ "$SECONDS" -lt "$limit" ]; do
	if timeout 4 fastboot devices | awk -v serial="$serial" '$1 == serial && $2 == "fastboot" {found=1} END {exit !found}'; then
		status 'FAIL: autonomous reset before post-pivot SSH; inspect initramfs evidence'
		exit 1
	fi
	if timeout 8 ssh -o ConnectTimeout=2 -o ConnectionAttempts=1 -o BatchMode=yes \
		"${T825_SSH_TARGET:-172.16.42.1}" 'sudo -n sh -s' > "$out/post-pivot.txt" 2>&1 <<'REMOTE'
set -eu
uname -r | grep -q '^7\.3\.1-t825-mssdiag$'
kill -0 "$(cat /run/t825-recovery/supervisor.pid)"
test -s /run/t825-recovery/handoff.log
case " $(cat /proc/cmdline) " in
    *" t825.direct-init "*)
        tr '\000' ' ' < /proc/1/cmdline | grep -q '/run/t825-recovery/postpivot-init'
        awk '$2 == "/" && $4 ~ /(^|,)ro(,|$)/ {found=1} END {exit !found}' /proc/mounts
        ;;
esac
echo T825_POSTPIVOT_READY
tr '\000' ' ' < /proc/1/cmdline; echo
cat /proc/mounts
uname -a
cat /proc/cmdline
cat /run/t825-recovery/supervisor.log /run/t825-recovery/handoff.log
systemctl --no-pager status t825-usb-gadget.service || true
for f in /run/t825-mssdiag/*.log; do
    [ ! -f "$f" ] || { echo "=== $f"; cat "$f"; }
done
REMOTE
	then
		grep -qx T825_POSTPIVOT_READY "$out/post-pivot.txt" || { status 'FAIL: missing verified handoff marker'; exit 1; }
		status 'PASS: post-pivot SSH and original supervisor verified; deadline remains armed'
		exit 0
	fi
	sleep 2
done
ip -brief link > "$out/host-link-final.txt" 2>&1 || true
lsusb > "$out/host-usb-final.txt" 2>&1 || true
status 'FAIL: post-pivot SSH unavailable; independent deadline remains armed'
exit 1
