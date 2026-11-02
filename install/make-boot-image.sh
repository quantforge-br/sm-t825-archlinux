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
CMDLINE="console=tty0 clk_ignore_unused pd_ignore_unused sysctl.kernel.firmware_config.ignore_sysfs_fallback=1 ${CMDLINE_EXTRA:-}"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
cat "$KERNEL" "$DTB_DIR/qcom/msm8996-samsung-gts3llte.dtb" "$DTB_DIR/qcom/apq8096-samsung-gts3lwifi.dtb" > "$tmp"
mkbootimg --header_version 0 --kernel "$tmp" --ramdisk "$INITRAMFS" --pagesize 0x00001000 \
	--base 0x00000000 --kernel_offset 0x80008000 --ramdisk_offset 0x82200000 --second_offset 0x00000000 \
	--tags_offset 0x82000000 --board '' --cmdline "$CMDLINE" -o "$out"
sha256sum "$out"
