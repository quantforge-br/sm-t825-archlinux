# Troubleshooting and recovery

These hardware observations come from the previous 6.19.5-r13 release. The 7.3.1
source package needs SM-T825 runtime validation; see [kernel notes](kernel.md).

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
For the 6.19.5-t825 → 7.3.1-t825 transition, leave the old module directory in place;
rollback can restore the boot files without `modules-prev.tar`. Same-release
reinstalls restore their saved modules too. Restore the previous DTB manually if
you replaced it; see [the update procedure](kernel.md#updating-and-rolling-back-on-the-tablet).
If extlinux.conf has a second label pointing at older files, change `default` to it.

## No sound / audio card missing

`wpctl status` should list "Speakers". If the card has only "off" and "pro-audio" profiles, the
UCM file may be an older version that routes audio to a missing back-end. The
current device UCM and `rootfs/files/ucm-HiFi.conf` both gate the top route on its
controls and include the new jack/headset support. Update the UCM and device
`51-gts3lwifi-audio.conf` together. The nodes can take a few seconds to appear after
PipeWire starts.

## The desktop restarts while a browser is open

Hyprland exits and the session starts again (autologin), usually soon after a Chromium-based browser
opens or while it loads a page. This is a GPU hang, not memory:

- `~/.cache/hyprland/hyprlandCrashReport<pid>.txt` shows signal 6 (ABRT) with
  `CHyprOpenGLImpl::begin` in the backtrace: Hyprland saw a GPU reset and gave up.
- `sudo dmesg | grep -E 'hangcheck|offending task'` shows `hangcheck recover!` and
  `offending task: brave (... --type=gpu-process)` (or chromium), sometimes followed by more
  hangs blamed on `qs` or Hyprland.
- `journalctl -u earlyoom` and `journalctl -k | grep -i 'out of memory'` show no kills.

Fixes, both in this repository:

1. Patch 0201 (tested on 6.19.5-r13, retained in 7.3.1-r0 but untested there): a hang in another process no longer counts as a reset for Hyprland
   ([kernel.md](kernel.md#gpu-hangs-and-the-compositor-patch-0201)).
2. `--disable-gpu-rasterization` for the browser (`desktop/install.sh` adds it to
   `~/.config/brave-origin-flags.conf`, `brave-flags.conf` and `chromium-flags.conf`).
   Restart the browser completely afterwards. In a test that opened a terminal and Brave with
   Wikipedia and YouTube, then rotated the screen 12 times, GPU rasterization hung the GPU in 3 runs
   out of 3; without it, 7 runs out of 7 had no hang.

## Rotation goes the wrong way

`monitor-sensor --accel` must print `normal` in portrait with Home at the bottom and `right-up` in
landscape with Home on the right. If not, `/etc/udev/rules.d/61-gts3-accel.rules` is missing or
another matrix wins (`udevadm info /sys/bus/iio/devices/iio:device1 | grep MOUNT`). Units may differ;
the matrix comes from each tablet's EFS sensor registry.

## TWRP

TWRP cannot mount the Linux partitions in a useful way. Its Wipe/Format actions erase `cache`
(/boot), `system` or `userdata` (root). Use it only for adb and dd.
