#!/usr/bin/env bash
# Prepare a private, non-persistent MSS/GNSS RAM boot for the SM-T825.
#
# This script deliberately refuses to run without the private firmware and
# calibration backup.  It copies the calibration images to /run at boot and
# points rmtfs there, so rmtfs cannot modify the tablet's real EFS/modem
# partitions during a diagnostic session. The daemons are included in and
# started from initramfs because the installed root may not contain them.
#
# Usage:
#   PMBOOTSTRAP_CONFIG=... FIRMWARE_DIR=... BACKUP_DIR=... \
#     install/make-gnss-ram-boot.sh out/gnss-ram
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: make-gnss-ram-boot.sh <output dir>}
: "${FIRMWARE_DIR:?set FIRMWARE_DIR to private EXTRACT_MSS=1 output}"
: "${BACKUP_DIR:?set BACKUP_DIR to private partition backup}"
: "${PMBOOTSTRAP_CONFIG:?set PMBOOTSTRAP_CONFIG to the diagnostic pmbootstrap config}"
PMB=${PMB:-pmbootstrap}
recovery_only=${T825_RECOVERY_ONLY:-0}
case "$recovery_only" in 0|1) ;; *) echo 'invalid T825_RECOVERY_ONLY' >&2; exit 2 ;; esac
direct_init=${T825_DIRECT_INIT:-0}
case "$direct_init" in 0|1) ;; *) echo 'invalid T825_DIRECT_INIT' >&2; exit 2 ;; esac
keep_ncm=${T825_KEEP_NCM:-0}
case "$keep_ncm" in 0|1) ;; *) echo 'invalid T825_KEEP_NCM' >&2; exit 2 ;; esac
trace_handoff=${T825_TRACE_HANDOFF:-0}
case "$trace_handoff" in 0|1) ;; *) echo 'invalid T825_TRACE_HANDOFF' >&2; exit 2 ;; esac

# The stock initramfs tears down unudhcpd immediately before switch_root. A
# diagnostic boot needs that daemon to keep the host lease while systemd and
# sshd start in the installed root. Patch only the transient build input and
# restore the shared pmbootstrap tree on every exit.
init2_backup=$(mktemp)
init2_backup_ready=0
init2_path=
init_functions_backup=$(mktemp)
init_functions_backup_ready=0
init_functions_path=
restore_init2() {
	if [ "$init2_backup_ready" = 1 ] && [ -n "$init2_path" ]; then
		sudo cp "$init2_backup" "$init2_path" || true
	fi
	rm -f "$init2_backup"
	if [ "$init_functions_backup_ready" = 1 ] && [ -n "$init_functions_path" ]; then
		sudo cp "$init_functions_backup" "$init_functions_path" || true
	fi
	rm -f "$init_functions_backup"
}
trap restore_init2 EXIT

mkdir -p "$out"
"$HERE/tools/t825-gnss-preflight.sh" \
	--firmware "$FIRMWARE_DIR" --backup "$BACKUP_DIR" \
	--report "$out/preflight.txt"

work=$($PMB -c "$PMBOOTSTRAP_CONFIG" config work)
rootfs=$work/chroot_rootfs_samsung-gts3lwifi
[ -d "$rootfs/etc" ] || {
	echo "missing $rootfs; run pmbootstrap install --no-image first" >&2
	exit 1
}

init2_path=$rootfs/usr/share/initramfs/init_2nd.sh
init_functions_path=$rootfs/usr/share/initramfs/init_functions.sh
if sudo test -f "$init2_path"; then
	sudo cp "$init2_path" "$init2_backup"
	init2_backup_ready=1
	if sudo grep -Fq 'killall udevd syslogd unudhcpd' "$init2_path"; then
		sudo sed -i 's/killall udevd syslogd unudhcpd/killall udevd syslogd/' "$init2_path"
	fi
	if [ "$direct_init" = 1 ]; then
		sudo python3 - "$init2_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
needle = 'init="/sbin/init"\n'
replacement = needle + '''case " $(cat /proc/cmdline) " in
*" t825.direct-init "*) init=/run/t825-recovery/postpivot-init ;;
esac
'''
if 't825.direct-init' not in text:
    if text.count(needle) != 1:
        raise SystemExit('init path anchor changed; refusing direct-init image')
    path.write_text(text.replace(needle, replacement, 1))
PY
	fi
fi
if sudo test -f "$init_functions_path"; then
	sudo cp "$init_functions_path" "$init_functions_backup"
	init_functions_backup_ready=1
fi

"$HERE/install/prepare-t825-recovery.sh" "$rootfs"

if [ "$keep_ncm" = 1 ]; then
	sudo python3 - "$init_functions_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '''\tif [ -n "$have_udc" ]; then
\t\tsetup_usb_acm_configfs
\telse
\t\tstart_unudhcpd
\tfi
'''
new = '''\tif [ -n "$have_udc" ]; then
\t\tcase " $(cat /proc/cmdline) " in
\t\t*" t825.keep-ncm "*|*" t825.direct-init "*) start_unudhcpd ;;
\t\t*) setup_usb_acm_configfs ;;
\t\tesac
\telse
\t\tstart_unudhcpd
\tfi
'''
if 't825.keep-ncm' not in text:
    if text.count(old) != 1:
        raise SystemExit('debug_shell USB branch changed; refusing keep-NCM image')
    text = text.replace(old, new, 1)
cleanup_old = '''\t# Remove the ACM/mass storage gadget devices
\t# FIXME: would be nice to have a way to keep this on and
\t# pipe kernel/init logs to it.
\trm -f $CONFIGFS/g1/configs/c.1/"$CONFIGFS_ACM_FUNCTION"
\trmdir $CONFIGFS/g1/functions/"$CONFIGFS_ACM_FUNCTION"
\trm -f "$CONFIGFS/g1/configs/c.1/$CONFIGFS_MASS_STORAGE_FUNCTION"
\trmdir "$CONFIGFS/g1/functions/$CONFIGFS_MASS_STORAGE_FUNCTION"
\tsetup_usb_configfs_udc
'''
cleanup_actual = '''\t# Remove the ACM/mass storage gadget devices
\t# FIXME: would be nice to keep this on and pipe kernel/init logs to it.
\trm -f $CONFIGFS/g1/configs/c.1/"$CONFIGFS_ACM_FUNCTION"
\trmdir $CONFIGFS/g1/functions/"$CONFIGFS_ACM_FUNCTION"
\trm -f "$CONFIGFS/g1/configs/c.1/$CONFIGFS_MASS_STORAGE_FUNCTION"
\trmdir "$CONFIGFS/g1/functions/$CONFIGFS_MASS_STORAGE_FUNCTION"
\tsetup_usb_configfs_udc
'''
cleanup_new = '''\tcase " $(cat /proc/cmdline) " in
\t*" t825.keep-ncm "*|*" t825.direct-init "*)
\t\t# Keep the active NCM/ACM composite gadget; clearing and rebinding UDC
\t\t# here disconnects the host immediately before switch_root.
\t\t: ;;
\t*)
''' + cleanup_actual + '''\t\t;;
\tesac
'''
if cleanup_old in text:
    text = text.replace(cleanup_old, cleanup_new, 1)
elif cleanup_actual in text:
    text = text.replace(cleanup_actual, cleanup_new, 1)
else:
    raise SystemExit('debug_shell cleanup block changed; refusing keep-NCM image')
path.write_text(text)
PY
fi
if [ "$direct_init" = 1 ]; then
	sudo python3 - "$init_functions_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '\ttouch /tmp/continue_boot\n\tpkill -f telnetd.*:23\n'
new = '''\ttouch /tmp/continue_boot
\tcase " $(cat /proc/cmdline) " in
\t*" t825.direct-init "*) pkill -f telnetd.*:23; exit 0 ;;
\t*) pkill -f telnetd.*:23 ;;
\tesac
'''
if 'exit 0' not in text:
    if text.count(old) != 1:
        raise SystemExit('pmos_continue_boot anchor changed; refusing direct-init trace')
    path.write_text(text.replace(old, new, 1))
PY
fi
if [ "$trace_handoff" = 1 ]; then
	sudo python3 "$HERE/install/trace-t825-handoff.py" "$init2_path"
fi
if [ "$direct_init" = 1 ]; then
	sudo python3 - "$init2_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = 'check_keys\n\n# If running from initramfs-extra'
new = '''case " $(cat /proc/cmdline) " in
	*" t825.direct-init "*) : ;;
*) check_keys ;;
esac

# If running from initramfs-extra'''
if old in text:
    text = text.replace(old, new, 1)
else:
    # An earlier direct-init experiment inserted `exit 0` here.  Accept that
    # stale transient build input and normalize it instead of silently
    # producing an image that never reaches mount_root/switch_root.
    bad = '''case " $(cat /proc/cmdline) " in
	*" t825.direct-init "*) exit 0 ;;
*) check_keys ;;
esac

# If running from initramfs-extra'''
    if bad in text:
        text = text.replace(bad, new, 1)
    elif new not in text:
        raise SystemExit('check_keys anchor changed; refusing direct-init bypass')
path.write_text(text)
PY
fi

# A RAM boot must never run the pmOS installer's deletion/resize routines.
# Direct-init diagnosis also has no reason to mount the installed root writable.
sudo python3 "$HERE/install/guard-t825-diagnostic-root.py" \
	"$init2_path" "$init_functions_path" "$direct_init"

kernel_release=$(sudo chroot "$rootfs" uname -r 2>/dev/null || true)
if [ "$kernel_release" != 7.3.1-t825-mssdiag ]; then
	# The release is recorded in the module directory, without executing a
	# target binary in the host chroot.
	if ! sudo test -d "$rootfs/usr/lib/modules/7.3.1-t825-mssdiag"; then
		echo "rootfs does not contain the MSS diagnostic kernel modules" >&2
		exit 1
	fi
fi

modem_src=$FIRMWARE_DIR/qcom/msm8996/samsung/gts3
[ -f "$modem_src/mba.mbn" ] && [ -f "$modem_src/modem.mdt" ] || {
	echo "MSS firmware is incomplete" >&2
	exit 1
}

# Keep the firmware in the path named by the DT.  The copy is private to the
# diagnostic rootfs and is included in its initramfs below.
sudo install -d -m 755 "$rootfs/lib/firmware/qcom/msm8996/samsung"
sudo cp -a "$modem_src" "$rootfs/lib/firmware/qcom/msm8996/samsung/"
sudo install -d -m 755 "$rootfs/lib/firmware/qcom/sensors"
sudo install -m 600 "$FIRMWARE_DIR/qcom/sensors/sns.reg-samsung,gts3llte" \
	"$rootfs/lib/firmware/qcom/sensors/sns.reg-samsung,gts3llte"
sudo install -d -m 755 "$rootfs/lib/firmware/ath10k/QCA6174/hw3.0"
sudo install -m 600 "$FIRMWARE_DIR/ath10k/QCA6174/hw3.0/board.bin" \
	"$rootfs/lib/firmware/ath10k/QCA6174/hw3.0/board.bin"

# rmtfs exposes these names to the modem firmware.  They are copied from the
# immutable private input into a tmpfs directory at boot; no source image is
# ever opened by rmtfs after the initramfs has pivoted to the tablet rootfs.
diag_dir="$rootfs/usr/lib/t825-mss-diag"
sudo install -d -m 700 "$diag_dir"
sudo install -m 600 "$BACKUP_DIR/modemst1.img" "$diag_dir/modem_fs1"
sudo install -m 600 "$BACKUP_DIR/modemst2.img" "$diag_dir/modem_fs2"
sudo install -m 600 "$BACKUP_DIR/fsg.img" "$diag_dir/modem_fsg"
sudo install -m 600 "$BACKUP_DIR/fsc.img" "$diag_dir/modem_fsc"

sudo install -d -m 755 "$rootfs/usr/local/libexec"
sudo install -m 755 "$HERE/install/t825-prepare-rmtfs-calibration.sh" \
	"$rootfs/usr/local/libexec/t825-mss-diag-prepare"

# The tablet's installed rootfs is not replaced by a fastboot RAM boot.  The
# modem partition is mounted read-only by an initramfs hook below; this avoids
# putting roughly 58 MiB of modem segments into the lk2nd-limited initramfs.
# The firmware tree remains mounted into the real root after the pivot.
sudo install -d -m 755 "$rootfs/etc/mkinitfs/hooks-extra" \
	"$rootfs/etc/mkinitfs/hooks-cleanup" \
	"$rootfs/etc/mkinitfs/modules-extra"
sudo install -m 755 /dev/stdin \
	"$rootfs/etc/mkinitfs/hooks-extra/90-t825-mssdiag-modem.sh" <<'EOF'
#!/bin/ash
set -eu

dev=/dev/disk/by-partlabel/modem
mountpoint=/run/t825-modem
target=/lib/firmware/qcom/msm8996/samsung/gts3
mkdir -p "$mountpoint" "$target"

# Older initramfs images may expose Samsung partitions through by-name only.
if [ ! -e "$dev" ] && [ -e /dev/block/by-name/modem ]; then
	dev=/dev/block/by-name/modem
fi

i=0
while [ ! -e "$dev" ] && [ "$i" -lt 100 ]; do
	sleep 0.1
	i=$((i + 1))
done
if [ ! -e "$dev" ]; then
	echo "t825-mssdiag: modem partition not present; MSS remains offline" >&2
	exit 0
fi

if ! mount -o ro,nosuid,nodev,noexec "$dev" "$mountpoint"; then
	echo "t825-mssdiag: could not mount modem partition read-only" >&2
	exit 0
fi
if [ ! -d "$mountpoint/image" ]; then
	echo "t825-mssdiag: modem partition has no image directory" >&2
	exit 0
fi

# The stock modem partition is the tablet's signed firmware source.  Bind only
# its image directory over the firmware path; no partition is opened writable.
mount --bind "$mountpoint/image" "$target"
EOF
sudo install -m 755 /dev/stdin \
	"$rootfs/etc/mkinitfs/hooks-extra/91-t825-mssdiag-start.sh" <<'EOF'
#!/bin/ash
set -eu
src=/usr/lib/t825-mss-diag
dst=/run/rmtfs
mkdir -p "$dst"
chmod 700 "$dst"
for spec in modemst1:modem_fs1 modemst2:modem_fs2 fsg:modem_fsg fsc:modem_fsc; do
	name=${spec%%:*}
	source_name=${spec#*:}
	cp "$src/$source_name" "$dst/$name"
	chmod 600 "$dst/$name"
done
EOF
sudo install -m 755 /dev/stdin \
	"$rootfs/etc/mkinitfs/hooks-extra/92-t825-mssdiag-services.sh" <<'EOF'
#!/bin/ash
set -eu

# The tablet's persistent root predates the MSS diagnostic packages. Start the
# QRTR services from initramfs, where their binaries and private calibration
# are available, before switching to that root.
mkdir -p /run/t825-mssdiag /run/rmtfs /run/tqftpserv /var/lib
chmod 700 /run/t825-mssdiag /run/rmtfs
if [ ! -e /var/lib/tqftpserv ]; then
	ln -s /run/tqftpserv /var/lib/tqftpserv
fi

# Publish the hold marker before starting remoteproc or any QRTR/QMI probe.
# Those operations can block on firmware or a missing service; the operator
# must still be able to distinguish the hold shell and inspect the partial
# state before deciding whether to release the pivot.
case " $(cat /proc/cmdline) " in
*" t825.mssdiag.hold "*)
	echo "diagnostic hold: inspect /run/t825-mssdiag and create continue-pivot" \
		> /run/t825-mssdiag/hold.log
	;;
esac

# Start only the MSS node. slpi/adsp are part of the normal baseline and must
# not be reset by this diagnostic boot.
for node in /sys/class/remoteproc/remoteproc*; do
	[ -r "$node/name" ] || continue
	[ "$(cat "$node/name")" = "2080000.remoteproc" ] || continue
	[ -w "$node/state" ] || continue
	echo start > "$node/state" 2>/run/t825-mssdiag/remoteproc.log || true
done

# The rmtfs memory device is created by the MSS remoteproc. Start tqftpserv
# first, then wait for the memory device; this matches the dependency used by
# the systemd units and prevents rmtfs from racing its QRTR TFTP endpoint.
if [ -x /usr/bin/tqftpserv ]; then
	/usr/bin/tqftpserv > /run/t825-mssdiag/tqftpserv.log 2>&1 &
	echo "$!" > /run/t825-mssdiag/tqftpserv.pid
fi

# Launching rmtfs before this point leaves calibration offline for the whole
# boot.
i=0
while [ ! -e /dev/qcom_rmtfs_mem1 ] && [ "$i" -lt 100 ]; do
	sleep 0.1
	i=$((i + 1))
done
if [ -e /dev/qcom_rmtfs_mem1 ] && [ -x /usr/bin/rmtfs ]; then
	/usr/bin/rmtfs -r -P -s -o /run/rmtfs \
		> /run/t825-mssdiag/rmtfs.log 2>&1 &
	echo "$!" > /run/t825-mssdiag/rmtfs.pid
else
	echo "rmtfs memory device unavailable" > /run/t825-mssdiag/rmtfs.log
fi

# Probe QRTR/QMI while the diagnostic binaries are still in initramfs.  Keep
# each probe bounded: a missing QRTR endpoint must not strand the hold hook
# before it can reopen the inspection shell.
# The output is kept under /run, which the cleanup hook moves into the new
# root.
sleep 5
{
	echo '--- qrtr ---'
	/usr/bin/busybox timeout 5 qrtr-lookup 2>&1 || true
	echo '--- qmi loc noop ---'
	/usr/bin/busybox timeout 5 qmicli --device=qrtr://0 --loc-noop 2>&1 || true
	echo '--- qmi operation mode ---'
	/usr/bin/busybox timeout 5 qmicli --device=qrtr://0 --loc-get-operation-mode 2>&1 || true
} > /run/t825-mssdiag/qmi.log

case " $(cat /proc/cmdline) " in
*" t825.mssdiag.hold "*)
	# Keep the stock debug-shell listener alive.  Killing it here races with
	# pmos_continue_boot: some boots lose the only reachable shell before the
	# fallback telnetd can bind (the BusyBox build may lack that applet).
	# A second listener is attempted only when telnetd is available and the
	# original listener is no longer present.
	if busybox telnetd --help >/dev/null 2>&1; then
		busybox telnetd -b 172.16.42.1:23 -l /bin/sh \
			>/run/t825-mssdiag/telnet.log 2>&1 &
	fi
	# Recovery was armed by /init before udev, modem startup and this hold.
	# pmos_continue_boot creates /tmp/continue_boot before it waits. Accept
	# that marker as the release request as well; requiring a separate marker
	# races with initramfs cleanup, which can kill the telnet shell between the
	# two commands sent by the host.
	case " $(cat /proc/cmdline) " in
	*" t825.mssdiag.inspect "*)
		while [ ! -e /run/t825-mssdiag/continue-pivot ]; do
			sleep 1
		done
		;;
	*)
		while [ ! -e /run/t825-mssdiag/continue-pivot ] &&
			[ ! -e /tmp/continue_boot ]; do
			sleep 1
		done
		;;
	esac
	;;
esac
EOF
sudo install -m 755 /dev/stdin \
	"$rootfs/etc/mkinitfs/hooks-cleanup/91-t825-mssdiag-firmware.sh" <<'EOF'
#!/bin/ash
set -eu
# Keep initramfs firmware visible after switch_root.  Bind the modem image
# directly as well because a plain parent bind does not carry nested mounts.
if [ -d /sysroot/lib/firmware ] && [ -d /lib/firmware ]; then
	mount --bind /lib/firmware /sysroot/lib/firmware
fi
if [ -d /run/t825-modem/image ] &&
	[ -d /sysroot/lib/firmware/qcom/msm8996/samsung/gts3 ]; then
	mount --bind /run/t825-modem/image \
		/sysroot/lib/firmware/qcom/msm8996/samsung/gts3
fi
# Preserve diagnostic daemons, calibration and logs across switch_root.
if [ -d /run/tqftpserv ] && [ -d /sysroot/var/lib/tqftpserv ]; then
	mount --bind /run/tqftpserv /sysroot/var/lib/tqftpserv
fi
if [ -d /sysroot/run ]; then
	if ! mount --move /run /sysroot/run; then
		echo 't825-mssdiag: /run move failed; trying bind handoff' >&2
		mount --bind /run /sysroot/run || true
	fi
fi
EOF
sudo install -m 644 /dev/stdin \
	"$rootfs/etc/mkinitfs/modules-extra/91-t825-mssdiag.modules" <<'EOF'
rmtfs_mem
qrtr
qrtr-smd
qcom_q6v5
qcom_q6v5_mss
qcom_q6v5_pas
qcom_sysmon
EOF

sudo install -d -m 755 "$rootfs/usr/lib/systemd/system" \
	"$rootfs/usr/lib/systemd/system/rmtfs.service.d"
sudo install -m 644 /dev/stdin \
	"$rootfs/usr/lib/systemd/system/t825-mss-diag-prepare.service" <<'EOF'
[Unit]
Description=Prepare in-memory T825 modem calibration for diagnostics
Before=rmtfs.service
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/libexec/t825-mss-diag-prepare
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 644 /dev/stdin \
	"$rootfs/usr/lib/systemd/system/rmtfs.service.d/10-t825-mssdiag.conf" <<'EOF'
[Unit]
Requires=t825-mss-diag-prepare.service
After=t825-mss-diag-prepare.service tqftpserv.service

[Service]
ExecStart=
ExecStart=/usr/bin/rmtfs -r -P -s -o /run/rmtfs
EOF
sudo install -d -m 755 \
	"$rootfs/usr/lib/systemd/system/tqftpserv.service.d"
sudo install -m 644 /dev/stdin \
	"$rootfs/usr/lib/systemd/system/tqftpserv.service.d/10-t825-mssdiag.conf" <<'EOF'
[Unit]
Requires=t825-mss-diag-prepare.service
After=t825-mss-diag-prepare.service
Before=rmtfs.service
EOF

# The production helper mounts Android partitions and can start every
# remoteproc as soon as firmware changes.  A diagnostic rootfs already has
# private firmware and must not touch those partitions.
sudo systemctl --root="$rootfs" disable gts3-firmware.service >/dev/null 2>&1 || true

# The initramfs already creates the USB NCM gadget and the debug shell uses it
# for the hand-off.  Re-running the persistent gadget service during
# switch_root briefly unbinds the UDC; on this tablet that can leave the
# controller disconnected and make the post-pivot services unreachable.  Keep
# the inherited gadget for the diagnostic boot and let systemd-networkd bind
# the existing usb0 interface instead.
sudo systemctl --root="$rootfs" disable t825-usb-gadget.service >/dev/null 2>&1 || true

# Units packaged in initramfs disappear at switch_root. Stage the USB helper
# and its unit in the /run tmpfs before the later firmware hook moves it.
sudo install -Dm755 "$HERE/rootfs/files/t825-usb-gadget" \
	"$rootfs/usr/local/sbin/t825-usb-gadget"
sudo install -Dm644 "$HERE/rootfs/files/t825-usb-gadget.service" \
	"$rootfs/usr/lib/systemd/system/t825-usb-gadget.service"
sudo install -m755 /dev/stdin \
	"$rootfs/etc/mkinitfs/hooks-cleanup/90-t825-recovery-runtime.sh" <<'EOF'
#!/bin/ash
set -eu
mkdir -p /run/t825-recovery /run/systemd/system
cp /usr/local/sbin/t825-usb-gadget /run/t825-recovery/usb-gadget
EOF
if [ "$direct_init" = 1 ]; then
	sudo install -Dm755 "$HERE/rootfs/files/t825-direct-init" \
		"$rootfs/usr/local/libexec/t825-direct-init"
	public_key=${T825_DIAGNOSTIC_SSH_PUBLIC_KEY:-$HOME/.ssh/id_ed25519.pub}
	ssh-keygen -l -f "$public_key" >/dev/null
	sudo install -Dm644 "$public_key" "$rootfs/usr/lib/t825-diagnostic/authorized_keys"
	sudo install -m755 /dev/stdin \
		"$rootfs/etc/mkinitfs/hooks-cleanup/90-t825-recovery-direct-init.sh" <<'EOF'
#!/bin/ash
set -eu
mkdir -p /run/t825-recovery
cp /usr/local/libexec/t825-direct-init /run/t825-recovery/postpivot-init
cp /usr/lib/t825-diagnostic/authorized_keys /run/t825-recovery/authorized_keys
# Keep an independent inspection endpoint on a separate port while the
# handoff is being diagnosed.  The original debug-shell telnet session is
# killed during initramfs cleanup; this listener uses a shell staged in /run,
# which is moved into the installed root before switch_root.
cat > /run/t825-recovery/postpivot-shell <<'SHELL'
#!/bin/sh
exec /bin/sh -l
SHELL
chmod 755 /run/t825-recovery/postpivot-shell
telnetd_cmd=''
if busybox-extras telnetd --help >/dev/null 2>&1; then
	telnetd_cmd='busybox-extras telnetd'
elif busybox telnetd --help >/dev/null 2>&1; then
	telnetd_cmd='busybox telnetd'
fi
if [ -n "$telnetd_cmd" ]; then
	$telnetd_cmd -F -b 172.16.42.1:2323 -l /run/t825-recovery/postpivot-shell \
		>/run/t825-recovery/postpivot-telnet.log 2>&1 &
	echo "$!" > /run/t825-recovery/postpivot-telnet.pid
fi
EOF
fi
sudo install -m755 /dev/stdin \
	"$rootfs/etc/mkinitfs/hooks-cleanup/90-t825-recovery-runtime.sh" <<'EOF'
#!/bin/ash
set -eu
mkdir -p /run/t825-recovery /run/systemd/system
cp /usr/local/sbin/t825-usb-gadget /run/t825-recovery/usb-gadget
sed 's|ExecStart=/usr/local/sbin/t825-usb-gadget|ExecStart=/bin/sh /run/t825-recovery/usb-gadget|' \
	/usr/lib/systemd/system/t825-usb-gadget.service \
	> /run/systemd/system/t825-usb-gadget.service
# systemd.wants= is handled by the generator, but a direct runtime wants link
# also makes the unit available when the host manager starts after switch_root.
mkdir -p /run/systemd/system/sysinit.target.wants
ln -sf ../t825-usb-gadget.service \
	/run/systemd/system/sysinit.target.wants/t825-usb-gadget.service
# The persistent image does not enable sshd. Enable a transient instance so
# post-pivot validation can use the preserved USB address without modifying
# the installed system.
mkdir -p /run/systemd/system/multi-user.target.wants
ln -sf /usr/lib/systemd/system/sshdgenkeys.service \
	/run/systemd/system/multi-user.target.wants/sshdgenkeys.service
ln -sf /usr/lib/systemd/system/sshd.service \
	/run/systemd/system/multi-user.target.wants/sshd.service
# /etc has priority over /run/systemd/system. The extlinux restore mask is
# requested through systemd.mask=, which uses generator.early priority.
echo 'runtime USB unit staged before switch_root' > /run/t825-recovery/handoff.log
EOF

# Remove obsolete build-root files so mkinitfs cannot include the ineffective
# shell watchdog or a stale extlinux override from an earlier preparation.
sudo rm -f \
	"$rootfs/usr/local/libexec/t825-mssdiag-postpivot-watchdog" \
	"$rootfs/usr/lib/systemd/system/t825-mssdiag-postpivot-watchdog.service" \
	"$rootfs/usr/lib/systemd/system/multi-user.target.wants/t825-mssdiag-postpivot-watchdog.service" \
	"$rootfs/usr/lib/systemd/system/multi-user.target.wants/t825-usb-gadget.service" \
	"$rootfs/etc/systemd/system/t825-extlinux-restore.service"

sudo install -d -m 755 "$rootfs/etc/mkinitfs/files-extra"
sudo install -m 644 /dev/stdin \
	"$rootfs/etc/mkinitfs/files-extra/91-t825-mssdiag.files" <<'EOF'
/lib/firmware/qcom/sensors/sns.reg-samsung,gts3llte
/lib/firmware/ath10k/QCA6174/hw3.0/board.bin
/usr/lib/t825-mss-diag
/usr/local/libexec/t825-mss-diag-prepare
/usr/lib/libzstd.so.1
/usr/lib/libzstd.so.1.5.7
/usr/lib/systemd/system/t825-mss-diag-prepare.service
/usr/lib/systemd/system/rmtfs.service.d/10-t825-mssdiag.conf
/usr/lib/systemd/system/tqftpserv.service.d/10-t825-mssdiag.conf
/usr/local/sbin/t825-usb-gadget
/usr/lib/systemd/system/t825-usb-gadget.service
/usr/bin/rmtfs
/usr/bin/tqftpserv
/usr/bin/qrtr-lookup
/usr/bin/qmicli
/usr/lib/ld-musl-aarch64.so.1
/usr/lib/libc.musl-aarch64.so.1
/usr/lib/libblkid.so.1.1.0
/usr/lib/libeconf.so.0.8.4
/usr/lib/libffi.so.8.5.0
/usr/lib/libgio-2.0.so.0.9000.0
/usr/lib/libglib-2.0.so.0.9000.0
/usr/lib/libgmodule-2.0.so.0.9000.0
/usr/lib/libgobject-2.0.so.0.9000.0
/usr/lib/libintl.so.8.4.6
/usr/lib/libmbim-glib.so.4.10.0
/usr/lib/libmount.so.1.1.0
/usr/lib/libpcre2-8.so.0.16.1
/usr/lib/libqmi-glib.so.5.12.0
/usr/lib/libqrtr-glib.so.0.0.1
/usr/lib/libqrtr.so.1.2
/usr/lib/libucontext.so.1
/usr/lib/libudev.so.1.7.15
/usr/lib/libz.so.1.4
/usr/lib/libblkid.so.1
/usr/lib/libeconf.so.0
/usr/lib/libffi.so.8
/usr/lib/libgio-2.0.so.0
/usr/lib/libglib-2.0.so.0
/usr/lib/libgmodule-2.0.so.0
/usr/lib/libgobject-2.0.so.0
/usr/lib/libintl.so.8
/usr/lib/libmbim-glib.so.4
/usr/lib/libmount.so.1
/usr/lib/libpcre2-8.so.0
/usr/lib/libqmi-glib.so.5
/usr/lib/libqrtr-glib.so.0
/usr/lib/libqrtr.so.1
/usr/lib/libucontext.so.1
/usr/lib/libudev.so.1
/usr/lib/libz.so.1
EOF
if [ "$direct_init" = 1 ]; then
	echo '/usr/local/libexec/t825-direct-init' | sudo tee -a \
		"$rootfs/etc/mkinitfs/files-extra/91-t825-mssdiag.files" >/dev/null
	echo '/usr/lib/t825-diagnostic/authorized_keys' | sudo tee -a \
		"$rootfs/etc/mkinitfs/files-extra/91-t825-mssdiag.files" >/dev/null
fi

if [ "$recovery_only" = 1 ]; then
	# Exercise the real pmOS/systemd handoff with recovery armed, before exposing
	# it to modem startup. The normal generator recreates these hooks next time.
	for name in 90-t825-mssdiag-modem 91-t825-mssdiag-start 92-t825-mssdiag-services; do
		sudo install -m755 /dev/stdin "$rootfs/etc/mkinitfs/hooks-extra/$name.sh" <<'EOF'
#!/bin/ash
echo 'Recovery-only acceptance image: modem hooks intentionally skipped'
EOF
	done
fi

"$PMB" -c "$PMBOOTSTRAP_CONFIG" chroot -r -- mkinitfs

# Refuse an image that cannot fit lk2nd's 50 MiB boot pool.  The diagnostic
# modem firmware is mounted read-only precisely so this check remains true.
boot_mem=${LK2ND_BOOT_MEM_SIZE:-52428800}
kernel_offset=32768
tags_size=2097152
ramdisk_size=$(stat -Lc %s "$rootfs/boot/initramfs")
kernel_size=$(gzip -dc "$rootfs/boot/vmlinuz" | wc -c)
budget=$(( (boot_mem - ramdisk_size) / 4096 * 4096 - tags_size - kernel_offset ))
if [ "$ramdisk_size" -ge "$boot_mem" ] || [ "$budget" -le 0 ] || [ "$kernel_size" -gt "$budget" ]; then
	echo "lk2nd budget refused: initramfs=$ramdisk_size boot_mem=$boot_mem budget=$budget kernel=$kernel_size" >&2
	exit 1
fi
echo "lk2nd budget: initramfs=$ramdisk_size boot_mem=$boot_mem budget=$budget kernel=$kernel_size margin=$((budget - kernel_size))"

mkdir -p "$out/dtbs"
sudo cp "$rootfs/boot/vmlinuz" "$out/vmlinuz"
sudo cp "$rootfs/boot/initramfs" "$out/initramfs"
sudo cp "$rootfs/boot/msm8996-samsung-gts3llte.dtb" "$out/dtbs/"
sudo cp "$rootfs/boot/apq8096-samsung-gts3lwifi.dtb" "$out/dtbs/"
if [ "$recovery_only" = 1 ]; then
	# Also prevent any possible remoteproc auto-start while testing recovery.
	sudo fdtput -t s "$out/dtbs/msm8996-samsung-gts3llte.dtb" \
		/soc/remoteproc@2080000 status disabled
	printf '%s\n' 'MSS disabled; recovery/systemd acceptance only' > "$out/RECOVERY_ONLY"
fi

sha256sum "$out/vmlinuz" "$out/initramfs" "$out/dtbs"/*.dtb \
	| tee "$out/SHA256SUMS"

echo "Prepared private diagnostic files in $out; nothing was installed on the tablet."
