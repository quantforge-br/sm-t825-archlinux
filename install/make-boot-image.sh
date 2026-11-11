#!/bin/bash
# Pack an Android boot image (header v0) that lk2nd can "fastboot boot" from RAM: Image.gz with
# both Galaxy Tab S3 device trees appended (lk2nd picks the matching one), the pmOS initramfs and
# the kernel command line. Same load addresses as the stock Samsung boot image.
#   KERNEL=.../vmlinuz INITRAMFS=.../initramfs DTB_DIR=.../dtbs \
#   CMDLINE_EXTRA="pmos_root_uuid=... pmos_rootfsopts=..." install/make-boot-image.sh out/test.img
# For the debug shell: CMDLINE_EXTRA="pmos.debug-shell".
set -euo pipefail
out=${1:?usage: make-boot-image.sh <output image>}
: "${KERNEL:?Image.gz}" "${INITRAMFS:?initramfs}" "${DTB_DIR:?dtbs directory}"
if [[ "${T825_MSS_DIAGNOSTIC_HOLD:-0}" == 1 ]]; then
	# Keep the diagnostic hold marker at the front and leave enough room in the
	# 512-byte Android cmdline field for all recovery masks and systemd wants.
	CMDLINE="console=tty0 clk_ignore_unused pd_ignore_unused t825.mssdiag.hold panic=10 pmos.debug-shell ${CMDLINE_EXTRA:-}"
else
	CMDLINE="console=tty0 clk_ignore_unused pd_ignore_unused sysctl.kernel.firmware_config.ignore_sysfs_fallback=1 ${CMDLINE_EXTRA:-}"
fi
if [[ -n "${PMOS_BOOT_UUID:-}" ]]; then
	CMDLINE+=" pmos_boot_uuid=${PMOS_BOOT_UUID}"
fi
if [[ "${T825_MSS_DIAGNOSTIC_BOOT:-0}" == 1 ]]; then
	# A RAM MSS/GNSS boot must not let the persistent root reconfigure the USB
	# gadget or copy firmware from writable Samsung partitions.  These masks
	# apply to this boot only and leave the installed system untouched.
	if [[ "${T825_KEEP_USB_SERVICE:-0}" != 1 ]]; then
		CMDLINE+=" systemd.mask=t825-usb-gadget.service"
	else
		# The cleanup hook transfers this unit to the new root through /run.
		CMDLINE+=" systemd.wants=t825-usb-gadget.service"
	fi
	if [[ "${T825_DIRECT_INIT:-0}" == 1 ]]; then
		CMDLINE+=" systemd.mask=t825-extlinux-restore.service"
	else
		CMDLINE+=" systemd.mask=t825-extlinux-restore.service systemd.mask=gts3-firmware.service systemd.mask=rmtfs.service systemd.mask=tqftpserv.service systemd.mask=tqftpserv-populate-readwrite.service systemd.mask=rmtfs-dir.service"
	fi
	if [[ "${T825_MASK_NETWORK:-0}" == 1 && "${T825_DIRECT_INIT:-0}" != 1 ]]; then
		CMDLINE+=" systemd.mask=NetworkManager.service systemd.mask=systemd-networkd.service systemd.mask=unudhcpd@usb0.service"
	fi
fi
# Refuse silent truncation of recovery flags by the legacy Android header.
if [ "${#CMDLINE}" -ge 512 ]; then
	echo "cmdline exceeds the legacy 511-byte limit: ${#CMDLINE}" >&2
	exit 1
fi
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
# Match deviceinfo_flash_* and mkinitfs: the wildcard DTB list is sorted, so
# the Wi-Fi blob precedes the LTE blob.  lk2nd selects the matching board-id.
cat "$KERNEL" "$DTB_DIR/qcom/apq8096-samsung-gts3lwifi.dtb" "$DTB_DIR/qcom/msm8996-samsung-gts3llte.dtb" > "$tmp"
mkbootimg --header_version 0 --kernel "$tmp" --ramdisk "$INITRAMFS" --pagesize 4096 \
	--base 0x80000000 --kernel_offset 0x00008000 --ramdisk_offset 0x02200000 --second_offset 0x00f00000 \
	--tags_offset 0x02000000 --board '' --cmdline "$CMDLINE" -o "$out"
# The Android mkbootimg shipped by some hosts writes second_addr=0 when the
# optional second payload is empty.  pmbootstrap/mkinitfs for this device keeps
# the lk2nd-compatible 0x80f00000 address even with second_size=0; preserve it
# so RAM boots have the same header as the generated production image.
python3 - "$out" <<'PY'
import struct
import sys

with open(sys.argv[1], "r+b") as stream:
    stream.seek(28)
    stream.write(struct.pack("<I", 0x80F00000))
PY
sha256sum "$out"
