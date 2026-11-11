#!/bin/sh
set -eu
d=/dev/mmcblk0p45;m=/run/t825-extlinux-restore
case " $(cat /proc/cmdline) " in *' t825.ramdiag '*) ;; *) exit 10;; esac
[ "$(cat /proc/sys/kernel/random/boot_id)" = "$EXPECTED_BOOT_ID" ]
p=$(cat /run/t825-recovery/supervisor.pid);kill -0 "$p"
[ "$(sha256sum /proc/"$p"/exe|cut -d ' ' -f1)" = "$EXPECTED_SUPERVISOR" ]
grep -q ' /sysroot ' /proc/mounts && exit 1;grep -q ' /boot ' /proc/mounts && exit 1
grep -q "^$d " /proc/mounts && exit 1
[ "$(blkid -c /dev/null -s UUID -o value "$d")" = c5e5c7d5-7019-4c4e-ba93-af3c61a96e1b ]
[ "$(blkid -c /dev/null -s TYPE -o value "$d")" = ext2 ]
mkdir "$m";mount -t ext2 -o ro,nosuid,nodev,noexec "$d" "$m"
c=$m/extlinux/extlinux.conf;h=$c.fastboot
if [ -e "$h" ] && [ ! -e "$c" ]; then
  sha256sum "$h"|grep -q "$EXPECTED_SHA";mount -o remount,rw "$m";mv "$h" "$c";sync
  sha256sum "$c"|grep -q "$EXPECTED_SHA";mount -o remount,ro "$m"
elif [ -e "$c" ] && [ ! -e "$h" ]; then sha256sum "$c"|grep -q "$EXPECTED_SHA";else exit 1;fi
umount "$m";rmdir "$m"
printf 'T825_EXTLINUX_RESTORED=%s\n' "$EXPECTED_SHA"
