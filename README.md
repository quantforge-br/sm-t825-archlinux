# Arch Linux ARM on the Samsung Galaxy Tab S3 LTE (SM-T825)

Native Arch Linux ARM (aarch64) on the Galaxy Tab S3 LTE, codename **gts3llte**, with a mainline
6.19 kernel. The tablet boots on its own without a PC: Samsung's S-Boot starts
[lk2nd](https://github.com/msm8916-mainline/lk2nd), lk2nd boots Linux from an extlinux.conf, and
Arch comes up with Wi-Fi, Bluetooth, audio, cameras, sensors and an optional Hyprland desktop.

The kernel work comes from [wh1ter0z3/gts3lwifi-mainline](https://github.com/wh1ter0z3/gts3lwifi-mainline),
a postmarketOS port that targets mostly the Wi-Fi model (SM-T820). This repository shows how to run
Arch Linux ARM on the LTE model instead, and holds what that takes beyond upstream: scripts, a few
kernel changes, configuration and the tested lk2nd image.

> Everything here was tested on one SM-T825 with bootloader **T825UBU3CUF1**. Read the warnings
> before you start: this replaces Android.

## Contents

- [What works](#what-works)
- [How it boots](#how-it-boots)
- [Differences from upstream](#differences-from-upstream)
- [Warnings](#warnings)
- [What you need](#what-you-need)
- [Installation](#installation)
- [After the installation](#after-the-installation)
- [Release files](#release-files)
- [Repository layout](#repository-layout)
- [Credits](#credits)

## What works

Display and GPU (Adreno 530, freedreno), touchscreen, S-Pen, power/volume/Home keys, Wi-Fi,
Bluetooth, all four speakers, both microphones, front and rear cameras (libcamera), hardware video
decode/encode (Venus), accelerometer/gyroscope/magnetometer/light sensor (auto-rotation), battery and
charging, microSD, USB networking. The LTE modem, SIM and GPS do not work. Details and the list of
harmless boot messages: [docs/hardware.md](docs/hardware.md).

## How it boots

```
S-Boot (Samsung, unlocked)
  └─ boot     (mmcblk0p28)  lk2nd                          written once
       └─ cache    (mmcblk0p45)  ext2: /extlinux/extlinux.conf, vmlinuz-t825,
            │                        initramfs-t825, dtbs/qcom/msm8996-samsung-gts3llte.dtb
            └─ postmarketOS initramfs: finds the root by UUID (pmos_root_uuid=...)
                 └─ Arch Linux ARM, systemd
                      root: system (mmcblk0p44, ext4)  or, optionally,
                            btrfs over userdata (p47) + system (p44), 28.3 GiB
```

- The Samsung partition table cannot be changed (the GPT sectors are write-protected, the PIT is
  signed), so the install reuses Android's partitions: [docs/partitions.md](docs/partitions.md).
- The kernel, initramfs and device tree live in `/boot`, which is Android's `cache` partition
  reformatted as plain ext2, the format lk2nd can read. A kernel update means copying files; the
  `boot` partition (lk2nd) is written only once.
- The initramfs is postmarketOS' (`mkinitfs`). It mounts the root and hands over to Arch's systemd.
- Recovery (TWRP) stays where it is and keeps working for adb.

## Differences from upstream

Upstream: [wh1ter0z3/gts3lwifi-mainline](https://github.com/wh1ter0z3/gts3lwifi-mainline), commit
`363ed94` (2026-11-01, kernel r8), which this work is based on.

| | Upstream | This repository |
|---|---|---|
| Distribution | postmarketOS (KDE Plasma) | Arch Linux ARM; postmarketOS only builds the kernel and the initramfs |
| Boot | pmOS boot.img stored behind lk2nd in `boot` | extlinux.conf on `cache` as ext2; kernels are files in `/boot` |
| Root file system | pmOS install on `userdata` | ext4 on `system`, optionally btrfs over `userdata` + `system` (28.3 GiB) |
| lk2nd for gts3llte | built, "not tested on hardware" | the image used here, tested on an SM-T825 ([docs/lk2nd.md](docs/lk2nd.md)) |
| Kernel | r8 | r13 = r8 + Landlock, connmark, RFCOMM/BNEP, MGLRU, THP madvise, `-t825` release suffix, upstream's shared-buffer GPU fix, GPU hang accounting ([docs/kernel.md](docs/kernel.md)) |
| Top speakers on the SM-T825 | left out "until checked" | enabled (patch 0114); all four speakers play |
| Firmware | `gts3-firmware` copies it from Android at every boot | extracted once from your partition dumps into the image and the initramfs (Android is gone) |
| Accelerometer mount matrix (SM-T825) | `1,0,0; 0,-1,0; 0,0,-1`, for KWin's panel orientation handling | `0,-1,0; -1,0,0; 0,0,1` for Hyprland and `t825-autorotate` |
| Bluetooth address helper | `gts3-bdaddr` | same, plus a retry that rebinds the UART driver when hci0 does not come up |
| Desktop | KDE Plasma (patched KWin) | optional Hyprland 0.57 + Dux Shell (DankMaterialShell), auto-rotation daemon, power-key panel toggle |
| Low-RAM tuning | defaults | zram the size of RAM, swappiness 180, MGLRU `min_ttl_ms`, earlyoom |
| GPU hangs from browsers | (Plasma) | Chromium-based browsers rasterize on the CPU; another process's GPU hang is no longer a reset for the compositor (patch 0201) |
| Fastboot from a running system | erase the image behind lk2nd | `t825-reboot-fastboot` hides extlinux.conf for one boot |

Upstream has continued since r8 (Book Cover Keyboard hot-plug, sensor timestamps, GPU fault fixes,
display resume). Of those, only the GPU fault fix (0122-0123) is in this kernel.

## Warnings

- **Android is erased.** `system` and `cache` are overwritten; the optional btrfs step also erases
  `userdata`. Back up first (step 2). An Odin firmware flash brings Android back, because the
  partition table never changes.
- **Unlocking the bootloader trips Knox** (warranty bit 0x1) for good. Samsung Pay, Secure Folder and
  similar features stop working, also after a return to stock.
- **Firmware and calibration are yours.** The Samsung-signed firmware, the Wi-Fi board file and the
  sensor registry come from your own tablet and cannot be redistributed. The images you build
  contain them, so do not publish your initramfs, boot images or rootfs image.
- Do not use TWRP's Wipe/Format actions afterwards: they erase `/boot` or the root
  ([docs/troubleshooting.md](docs/troubleshooting.md)).
- Never write `efs`, `modemst1/2`, `persist`, `param` or the bootloader partitions.

## What you need

- A Galaxy Tab S3 **SM-T825** with the bootloader unlocked and **TWRP** in the recovery partition,
  plus a USB-C data cable.
- An x86_64 Linux host. Tested on Arch Linux with: `android-tools` (adb, fastboot, mkbootimg),
  `pmbootstrap` 3.x, `arch-install-scripts`, `qemu-user-static`, `qemu-user-static-binfmt`,
  `openbsd-netcat` (needs `nc -N`), `e2fsprogs`, `rsync`, `git`, `python`, `openssl`, `gnupg`.
  About 15 GB of free disk space, sudo.
- This repository and its [release files](#release-files) (at least the lk2nd image).

## Installation

All commands run on the host from the root of this repository unless stated otherwise. `out/` and
`backup/` are created here and are ignored by git.

### 1. Unlock the bootloader and install TWRP

This is the usual Samsung procedure and nothing in it is specific to this guide: enable "OEM
unlocking" in the developer options, unlock from Download mode (Power + Volume Down + Home), then flash
TWRP for gts3llte to `recovery` (Odin, or `heimdall flash --RECOVERY twrp.img --no-reboot`) and
start it right away with Power + Volume Up + Home, before stock Android can replace it.

### 2. Back up your partitions

Start TWRP and plug the tablet in (`adb devices` shows `recovery`):

```sh
install/backup-partitions.sh backup/
```

It streams `efs modemst1 modemst2 persist param boot recovery apnhlos modem dsp system` with
`adb exec-out` and checks each copy against a SHA-256 taken on the tablet. Keep `backup/` private and
safe: EFS holds your IMEI and calibration.

### 3. Install lk2nd

Still in TWRP:

```sh
(cd release && sha256sum -c --ignore-missing SHA256SUMS)
adb push release/lk2nd-gts3llte-23.1-fd380ac6.img /tmp/lk2nd.img
adb shell 'dd if=/tmp/lk2nd.img of=/dev/block/bootdevice/by-name/boot && sync'
adb shell 'head -c 2379792 /dev/block/bootdevice/by-name/boot | sha256sum'   # 436ba23f...ce96a
adb reboot
```

The tablet now starts lk2nd, finds nothing to boot and stays in fastboot (`fastboot devices`).
To build lk2nd yourself, see [docs/lk2nd.md](docs/lk2nd.md).

### 4. Build the kernel and the postmarketOS chroot

```sh
git clone https://gitlab.postmarketos.org/postmarketOS/pmaports.git ~/pmaports-t825
git -C ~/pmaports-t825 reset --hard 367abb3e17df1299380271c9e52c0824fc7378d3
rm -rf ~/pmaports-t825/device/testing/linux-postmarketos-qcom-msm8996
cp -r pmaports/linux-postmarketos-qcom-msm8996 pmaports/device-samsung-gts3lwifi \
    ~/pmaports-t825/device/testing/

pmbootstrap -p ~/pmaports-t825 init
#   channel: edge, vendor: samsung, device: gts3lwifi (covers the SM-T825 too),
#   user interface: console, init system: systemd
pmbootstrap config aports          # must print ~/pmaports-t825
pmbootstrap build --force linux-postmarketos-qcom-msm8996
pmbootstrap install --no-image     # fills chroot_rootfs_samsung-gts3lwifi; asks for a password
```

`install --no-image` leaves the postmarketOS root in `$(pmbootstrap config work)/chroot_rootfs_samsung-gts3lwifi`.
The build uses it for the kernel modules, the device files and the redistributable firmware
(Adreno, QCA Bluetooth, ath10k). The password only applies to that chroot, which is never flashed.

### 5. Extract your firmware

```sh
sudo install/extract-firmware.sh backup/ firmware/
```

It mounts the dumps read-only and collects, as postmarketOS' `gts3-firmware` does:

| From | Files | Used for |
|---|---|---|
| `apnhlos` | `image/a530_zap.*`, `venus.*`, `slpi.*` | GPU, video codec, sensor hub |
| `modem` | `image/adsp.*` | audio DSP |
| `system` | `bdwlan30.bin` → `ath10k/QCA6174/hw3.0/board.bin` | Wi-Fi |
| `efs` | `FactoryApp/sensors/sns.reg` → `qcom/sensors/sns.reg-samsung,gts3llte` | sensor calibration |

Samsung's Wi-Fi board file says country GB, and the radio never goes beyond the rules of that
country. Put your own country in it now (ISO 3166-1 numeric code: 76 Brazil, 840 United States,
276 Germany, ...); see [docs/hardware.md](docs/hardware.md#wi-fi-country):

```sh
sudo python3 tools/ath10k-board-country.py firmware/ath10k/QCA6174/hw3.0/board.bin \
    firmware/ath10k/QCA6174/hw3.0/board.bin 76
```

### 6. Build the initramfs and a debug-shell boot image

```sh
FIRMWARE_DIR=firmware install/make-initramfs.sh out/boot
KERNEL=out/boot/vmlinuz INITRAMFS=out/boot/initramfs DTB_DIR=out/boot/dtbs \
    CMDLINE_EXTRA=pmos.debug-shell install/make-boot-image.sh out/boot-debug-shell.img
```

The firmware goes into the initramfs because the audio DSP, sensor hub and video drivers load before
the root is mounted.

### 7. Build the Arch Linux ARM root

```sh
mkdir -p dl && cd dl
curl -LO http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz
curl -LO http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz.md5
curl -LO http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz.sig
gpg --recv-keys 68B3537F39A313B3E574D06777193F152BDBE6A6
gpg --verify ArchLinuxARM-aarch64-latest.tar.gz.sig
cd ..
openssl passwd -6 > pwhash          # password of your user on the tablet

sudo env PMOS_ROOTFS="$(pmbootstrap config work)/chroot_rootfs_samsung-gts3lwifi" \
    FIRMWARE_DIR=firmware SSH_PUBKEY="$HOME/.ssh/id_ed25519.pub" PWHASH_FILE=pwhash \
    ALARM_TARBALL=dl/ArchLinuxARM-aarch64-latest.tar.gz OUT_DIR=out \
    USERNAME=tab HOSTNAME_=tabs3 TIMEZONE=UTC LOCALE=en_US.UTF-8 KEYMAP=us \
    rootfs/build-arch-rootfs.sh
rm pwhash
```

[rootfs/build-arch-rootfs.sh](rootfs/build-arch-rootfs.sh) makes a 4194304000-byte ext4 image (the
size of `system`) with a fixed UUID, unpacks Arch Linux ARM, runs
[rootfs/chroot-setup.sh](rootfs/chroot-setup.sh) under qemu (removes the generic kernel, installs
NetworkManager, BlueZ, PipeWire, iio-sensor-proxy, mesa, zram; creates the user with sudo; sets up
the USB network) and adds modules, firmware and the device files. Set `SUDO_NOPASSWD=1` for
passwordless sudo. The image is `out/arch-gts3llte-root.ext4`.

### 8. Build the boot file system

```sh
sudo env KERNEL=out/boot/vmlinuz INITRAMFS=out/boot/initramfs DTB_DIR=out/boot/dtbs \
    install/make-boot-partition.sh out/arch-boot-cache.ext2
```

A 200 MiB ext2 (label `arch_boot`) with `vmlinuz-t825`, `initramfs-t825`, the gts3llte device tree and
an extlinux.conf that names the root UUID of step 7.

### 9. Flash

Put the tablet in lk2nd fastboot (after step 3 it already is; otherwise hold Volume Down while it
starts) and boot the debug shell from RAM:

```sh
fastboot boot out/boot-debug-shell.img
# wait until the USB network is up: the host gets 172.16.42.2 by DHCP, telnet answers on 172.16.42.1
install/flash-partition.sh out/arch-gts3llte-root.ext4 system    # about 3 minutes
install/flash-partition.sh out/arch-boot-cache.ext2 cache
printf 'sync; reboot -f\n' | nc -N 172.16.42.1 23
```

[install/flash-partition.sh](install/flash-partition.sh) looks the partition up by name on the
tablet, refuses anything other than `system`, `cache`, `userdata` or `hidden`, streams the image
gzip-compressed over the USB network and compares the SHA-256 of what landed on the eMMC.

### 10. First boot

lk2nd boots the extlinux entry and Arch starts (first boot about 30 s). Over USB:

```sh
ssh tab@172.16.42.1
nmcli device wifi connect <SSID> --ask
sudo pacman -Syu
```

The tablet runs a DHCP server on its USB interface (systemd-networkd, `172.16.42.1/24`, no gateway),
so the host gets an address in that range. Wi-Fi is `wlp1s0` (NetworkManager).

## After the installation

- **More space:** move the root to btrfs over `userdata` + `system`: [docs/btrfs.md](docs/btrfs.md).
- **Desktop:** on the tablet, run `dms setup` once (Hyprland, systemd), then
  [desktop/install.sh](desktop/install.sh). It sets up Hyprland + Dux Shell with touch and S-Pen
  mapped to the panel, Home opening the launcher, a short press on Power to switch the panel off,
  auto-rotation (`t825-autorotate`, `t825-rotation-lock on|off|toggle`), autologin on tty1 and the
  low-RAM tuning (`desktop/tuning/`, skip it with `--no-tuning`).
- **Kernel updates and rollback:** [docs/kernel.md](docs/kernel.md).
- **Getting to fastboot from the running system:** `sudo t825-reboot-fastboot`.
- **Never install** `linux-aarch64` or `linux-firmware`: the kernel and firmware come from this
  setup, and pacman would only fail on file conflicts or fill `/boot`.
- Something broke: [docs/troubleshooting.md](docs/troubleshooting.md).

## Release files

Binaries are assets of the [GitHub releases](https://github.com/quantforge-br/sm-t825-archlinux/releases),
not files in git. Download them into `release/` and check them against
[release/SHA256SUMS](release/SHA256SUMS):

```sh
gh release download --repo quantforge-br/sm-t825-archlinux --dir release --clobber
(cd release && sha256sum -c SHA256SUMS)
```

| File | SHA-256 | What |
|---|---|---|
| `lk2nd-gts3llte-23.1-fd380ac6.img` | `436ba23f...ce96a` | lk2nd for the SM-T825, tested |
| `linux-postmarketos-qcom-msm8996-6.19.5-r13.apk` | `43cf1ac7...b882c` | kernel package r13 (modules, vmlinuz, device trees) |
| `vmlinuz-6.19.5-t825-r13` | `a304d67e...` | the kernel from that package |
| `msm8996-samsung-gts3llte.dtb` | `b1f1bd62...` | SM-T825 device tree with the top speakers |
| `apq8096-samsung-gts3lwifi.dtb` | `fd727baa...` | SM-T820 device tree, appended next to the SM-T825 one in boot images |

Not published, because they contain the firmware and calibration of the tablet they were made on:
initramfs, boot images, the boot file system and the rootfs image. Steps 5-8 make yours.

## Repository layout

| Path | Contents |
|---|---|
| `pmaports/` | kernel and device packages to copy into pmaports at `367abb3e` |
| `rootfs/` | Arch root builder, chroot setup, device files that go into the image |
| `install/` | backup, firmware extraction, initramfs, boot image, boot fs, flashing, btrfs, kernel update scripts |
| `desktop/` | Hyprland + Dux Shell setup, auto-rotation, low-RAM tuning, browser flags |
| `docs/` | partitions, lk2nd, kernel, btrfs, hardware status, troubleshooting |
| `tools/` | `gpuhang.c` (GPU hang test), `ath10k-board-country.py` (Wi-Fi country in the board file) |
| `release/` | release binaries, downloaded from the GitHub release (git keeps only `SHA256SUMS`) |

## Credits

- [wh1ter0z3/gts3lwifi-mainline](https://github.com/wh1ter0z3/gts3lwifi-mainline): the Galaxy Tab S3
  mainline port (device trees, panel, audio, power and camera drivers, lk2nd device files and packing).
- [postmarketOS](https://postmarketos.org) (pmaports, pmbootstrap, mkinitfs) and the msm8996
  mainline kernel maintainers.
- [lk2nd](https://github.com/msm8916-mainline/lk2nd).
- [Arch Linux ARM](https://archlinuxarm.org).

## License

- Scripts, tools, desktop files and documentation: MIT, see [LICENSE](LICENSE).
- Kernel patches in `pmaports/linux-postmarketos-qcom-msm8996/`, including ours (0114, 0201):
  GPL-2.0, like the Linux kernel. Device tree changes follow the SPDX headers of the files they patch.
- Everything else that comes from postmarketOS pmaports or from wh1ter0z3/gts3lwifi-mainline (the
  APKBUILDs, the device package, the device files in `rootfs/files/` taken from it) keeps the
  license of its source.
- Release binaries: the kernel package and `vmlinuz` are GPL-2.0; their sources are `pmaports/`
  plus the kernel tarball named in the APKBUILD. lk2nd is under the licenses of
  [its repository](https://github.com/msm8916-mainline/lk2nd).
