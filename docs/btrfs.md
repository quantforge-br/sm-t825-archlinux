# Optional: root on btrfs over userdata + system

The rootfs image is a 4 GB ext4 on `system`. The table cannot change (docs/partitions.md), but one
btrfs can span `userdata` (24.4 GiB) and `system` (3.9 GiB): 28.3 GiB, data `single`, metadata `DUP`,
subvolumes `@` (/) and `@home`, `noatime,compress=zstd:1`. The postmarketOS initramfs scans btrfs
devices and mounts the subvolume named in `pmos_rootfsopts`.

This erases `userdata` (Android data) and, in the last step, the ext4 root on `system`.

All steps run as root on the tablet, from a checkout of this repository (or copy `install/` over).

1. Copy the running system (about 2 minutes, the root is frozen for the second rsync pass):

       sudo install/btrfs-migrate.sh

   It prints the new UUID and keeps it in `/root/t825-btrfs-uuid`. lk2nd still boots ext4.

2. Test the btrfs root from RAM. On the host, build a boot image with the btrfs command line:

       KERNEL=out/boot/vmlinuz INITRAMFS=out/boot/initramfs DTB_DIR=out/boot/dtbs \
       CMDLINE_EXTRA="pmos_root_uuid=<uuid> pmos_rootfsopts=subvol=/@,noatime,compress=zstd:1" \
       install/make-boot-image.sh btrfs-test.img

   then `sudo t825-reboot-fastboot` on the tablet and `fastboot boot btrfs-test.img` on the host.
   `findmnt /` must show btrfs.

3. Point lk2nd at it and reboot:

       sudo install/btrfs-switch-boot.sh

   `extlinux.conf.pre-btrfs` keeps the old entry.

4. After a good reboot, add `system` as the second device (this destroys the ext4 root):

       sudo install/btrfs-add-system.sh

Checks: `btrfs filesystem usage -T /` shows two devices; `lsattr -d /var/log/journal` shows `C`
(no copy-on-write for the journal).
