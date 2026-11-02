#!/bin/bash
# Build the image of the boot file system that lk2nd reads: Android's "cache" partition
# (200 MiB on the SM-T825) as plain ext2 with kernel, initramfs, device tree and extlinux.conf.
#
# lk2nd's ext2 driver accepts only the sparse_super/large_file ro_compat features and no
# extents, hence mkfs.ext2 with these options. Run as root:
#   KERNEL=.../vmlinuz INITRAMFS=.../initramfs DTB_DIR=.../dtbs \
#   install/make-boot-partition.sh out/arch-boot-cache.ext2
set -euo pipefail
out=${1:?usage: make-boot-partition.sh <output image>}
: "${KERNEL:?Image.gz of linux-postmarketos-qcom-msm8996 (boot/vmlinuz in the package)}"
: "${INITRAMFS:?initramfs made by mkinitfs in the pmOS rootfs chroot}"
: "${DTB_DIR:?directory that holds qcom/msm8996-samsung-gts3llte.dtb}"
SIZE=${SIZE:-209715200}
BOOT_UUID=${BOOT_UUID:-c5e5c7d5-7019-4c4e-ba93-af3c61a96e1b}
ROOT_UUID=${ROOT_UUID:-3c1b2d91-6191-410b-8f7d-4d7cd5a21b26}
ROOTFSOPTS=${ROOTFSOPTS:-defaults}
CMDLINE="console=tty0 clk_ignore_unused pd_ignore_unused sysctl.kernel.firmware_config.ignore_sysfs_fallback=1"
mnt=$(mktemp -d)
trap 'mountpoint -q "$mnt" && umount "$mnt"; rmdir "$mnt"' EXIT

rm -f "$out"
truncate -s "$SIZE" "$out"
mkfs.ext2 -F -q -L arch_boot -U "$BOOT_UUID" -b 4096 -O ^dir_index -m 0 "$out"
mount -o loop "$out" "$mnt"
install -Dm644 "$KERNEL" "$mnt/vmlinuz-t825"
install -Dm644 "$INITRAMFS" "$mnt/initramfs-t825"
install -Dm644 "$DTB_DIR/qcom/msm8996-samsung-gts3llte.dtb" "$mnt/dtbs/qcom/msm8996-samsung-gts3llte.dtb"
mkdir -p "$mnt/extlinux"
cat > "$mnt/extlinux/extlinux.conf" <<EOF
default arch

# lk2nd boots only the default label; it skips comment lines.
label arch
	kernel /vmlinuz-t825
	fdt /dtbs/qcom/msm8996-samsung-gts3llte.dtb
	initrd /initramfs-t825
	append $CMDLINE pmos_root_uuid=$ROOT_UUID pmos_rootfsopts=$ROOTFSOPTS
EOF
cat "$mnt/extlinux/extlinux.conf"
umount "$mnt"
dumpe2fs -h "$out" 2>/dev/null | grep -E 'features|UUID'
sha256sum "$out"
