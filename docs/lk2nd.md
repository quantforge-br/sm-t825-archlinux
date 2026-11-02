# lk2nd on the SM-T825

[lk2nd](https://github.com/msm8916-mainline/lk2nd) runs as a "kernel" that Samsung's S-Boot loads
from the `boot` partition. It then offers fastboot over USB and boots Linux from an extlinux.conf.

## The image in the release

`lk2nd-gts3llte-23.1-fd380ac6.img` (2379792 bytes, SHA-256 `436ba23f...ce96a`, see
`release/SHA256SUMS`) is the image that runs on the tablet this guide comes from:

    (bootloader) lk2nd:version:23.1-next-fd380ac6-20261020-dirty
    (bootloader) lk2nd:model:Samsung Galaxy Tab S3 (LTE)
    (bootloader) lk2nd:compatible:samsung,gts3llte
    (bootloader) lk2nd:panel:ss_dsi_panel_ANA38401_AMS968HH01_QXGA
    (bootloader) lk2nd:bootloader:T825UBU3CUF1

Sources: lk2nd commit `fd380ac6` plus the Galaxy Tab S3 device trees
(`lk2nd/msm8996-samsung-gts3llte.dts`, `lk2nd/rules.mk.diff`) from
[wh1ter0z3/gts3lwifi-mainline](https://github.com/wh1ter0z3/gts3lwifi-mainline). It was packed with
that repository's `scripts/pack-lk2nd-samsung.sh`, which merges the lk2nd node into the four stock
Samsung device trees of a gts3llte boot image (here an Android 14 / LineageOS 21 one), uses the
stock load addresses and adds the `SEANDROIDENFORCE` trailer that S-Boot expects. lk2nd reserves the
first 4 MiB of `boot` for itself.

At the time of writing, upstream's own gts3llte image (`8276c5cd...`) is listed as not tested on
hardware. The image here is tested on an SM-T825 with bootloader T825UBU3CUF1.

### Building it yourself

    git clone https://github.com/msm8916-mainline/lk2nd ~/samsung/lk2nd
    git -C ~/samsung/lk2nd checkout fd380ac6
    git clone https://github.com/wh1ter0z3/gts3lwifi-mainline
    cp gts3lwifi-mainline/lk2nd/msm8996-samsung-gts3l*.dts ~/samsung/lk2nd/lk2nd/device/dts/msm8996/
    git -C ~/samsung/lk2nd apply "$PWD/gts3lwifi-mainline/lk2nd/rules.mk.diff"
    # needs arm-none-eabi-gcc, dtc, python
    LK2ND_DTB=msm8996-samsung-gts3llte gts3lwifi-mainline/scripts/pack-lk2nd-samsung.sh \
        <a gts3llte boot.img> lk2nd-gts3llte.img

Any boot image made for the SM-T825 works as the donor (stock, LineageOS, TWRP's backup of `boot`);
only its device trees, command line and OS version are taken.

## Installing it (once)

From TWRP, with the tablet on USB (`adb devices` shows `recovery`):

    adb push lk2nd-gts3llte-23.1-fd380ac6.img /tmp/lk2nd.img
    adb shell 'dd if=/tmp/lk2nd.img of=/dev/block/bootdevice/by-name/boot && sync'
    adb shell 'head -c 2379792 /dev/block/bootdevice/by-name/boot | sha256sum'   # must be 436ba23f...
    adb reboot

The screen shows the lk2nd menu (nothing to boot yet) and `fastboot devices` lists the tablet
(USB ID `18d1:d00d`). Heimdall from Download mode works too: `heimdall flash --BOOT lk2nd.img`.

## Using it

- **Boot order.** lk2nd looks through every partition of at least 16 MiB with its ext2 driver and
  boots the first `/extlinux/extlinux.conf` it finds; here that is `cache`. Only the `default` label
  is booted (there is no menu) and lines starting with `#` are skipped.
- **The boot file system must be plain ext2.** lk2nd's driver handles the `sparse_super` and
  `large_file` features only; an ext4 with extents is not readable. `install/make-boot-partition.sh`
  creates it with the right options.
- **Fastboot.** Hold Volume Down while the tablet starts. From a running system,
  `t825-reboot-fastboot` (installed by the rootfs build) hides extlinux.conf and reboots, so lk2nd
  stays in fastboot; `t825-extlinux-restore.service` puts the file back on the next boot of the
  system, normal or through `fastboot boot`. `systemctl reboot --reboot-argument=bootloader` lands in
  Samsung's Download mode instead, because S-Boot reads the reboot reason first.
- **Testing kernels.** `fastboot boot image.img` runs an Android boot image from RAM without writing
  anything (`install/make-boot-image.sh`). Do not use `fastboot flash boot`: it writes an OS image
  behind lk2nd, which this setup does not use.
- **Recovery and Download mode.** Power + Volume Up + Home opens TWRP. Power + Volume Down + Home
  opens Download mode. lk2nd's own "Recovery" menu entry only reboots.
