# Troubleshooting and recovery

## Key combinations

| Keys (hold while powering on) | Result |
|---|---|
| Power + Volume Down, 7-10 s | forced restart (also when frozen) |
| Volume Down while lk2nd starts | lk2nd fastboot |
| Power + Volume Up + Home | TWRP |
| Power + Volume Down + Home | Samsung Download mode (Odin/Heimdall) |

## The tablet stays in lk2nd fastboot

lk2nd found no `extlinux/extlinux.conf`. Either `t825-reboot-fastboot` was used (the file is
`extlinux.conf.fastboot` until the next Linux boot) or `cache` was wiped. `fastboot boot` any
working image (the debug shell or a test image with your root UUID); the restore service fixes the
first case. For the second, flash `cache` again (`install/flash-partition.sh`).

## Getting a shell without a working root

`fastboot boot boot-debug-shell.img` (built with `CMDLINE_EXTRA=pmos.debug-shell`) starts the
postmarketOS initramfs with a telnet server: `telnet 172.16.42.1` (host side: the USB network
interface gets an address by DHCP, or set `172.16.42.2/24` by hand). From there you can mount
partitions, fix extlinux.conf or rewrite a partition with `install/flash-partition.sh`.

## Kernel update went wrong

Boot the previous kernel from RAM with `fastboot boot`, then `sudo install/rollback-kernel.sh`.
If extlinux.conf has a second label pointing at older files, change `default` to it.

## No sound / audio card missing

`wpctl status` should list "Speakers". If the card has only "off" and "pro-audio" profiles, the
UCM file is the pmaports one that routes audio to a back-end that does not exist on this device
tree; `rootfs/files/ucm-HiFi.conf` fixes that. The nodes can take a few seconds to appear after
PipeWire starts.

## Rotation goes the wrong way

`monitor-sensor --accel` must print `normal` in portrait with Home at the bottom and `right-up` in
landscape with Home on the right. If not, `/etc/udev/rules.d/61-gts3-accel.rules` is missing or
another matrix wins (`udevadm info /sys/bus/iio/devices/iio:device1 | grep MOUNT`). Units may differ;
the matrix comes from each tablet's EFS sensor registry.

## TWRP

TWRP cannot mount the Linux partitions in a useful way. Its Wipe/Format actions erase `cache`
(/boot), `system` or `userdata` (root). Use it only for adb and dd.
