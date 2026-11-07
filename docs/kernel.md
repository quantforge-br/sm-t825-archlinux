# Kernel

The source package is `linux-postmarketos-qcom-msm8996` **7.3.1-r0**, with release
string **7.3.1-t825** and modules in `/usr/lib/modules/7.3.1-t825` on Arch
(`/lib/modules/7.3.1-t825` inside the APK). It replaces the previous 6.19.5-r13
source package. The files in `release/` remain the previous 6.19.5 release.

## Sources and relation to upstream

The baseline is [wh1ter0z3/gts3lwifi-mainline at 9f81231ac11893d46d4b6a8af7abe8e3c863ad05](https://github.com/wh1ter0z3/gts3lwifi-mainline/tree/9f81231ac11893d46d4b6a8af7abe8e3c863ad05).
All 194 upstream patches are byte-identical: 70 `m001`–`m071` patches (no m056),
and 124 numbered patches from `0001` through `0182`, with upstream's gaps and
APKBUILD order. The package uses the kernel.org 7.3.1 tarball; msm8996-mainline's
last base tag was 6.19.5. Upstream's `APKBUILD.pmaports` is named `APKBUILD` here,
with our pkgrel reset to 0, config checksum and two appended local patches.
No a5xx hangcheck backport is included.

Copy the complete directories in `pmaports/` to `device/testing/` in a pmaports
checkout at **367abb3e17df1299380271c9e52c0824fc7378d3**. This base still provides
the package build dependencies and device packaging used here; both packages are
built against it. `pmaports/pmaports-367abb3e-kernel.diff` records only APKBUILD
and config against that base; use the complete package directory for the patches.

### Package revisions and retained deltas

Revision numbers restart for 7.3.1; “r9–r13” below refers to 6.19.5 history.

| Package | Revision | Contents |
|---|---|---|
| Kernel 7.3.1 | r0 | Upstream 9f81231 series, retained config below, unchanged 0201 and rebased 0202 |
| Device 1 | r6 | Upstream headset microphone, jack controls and WirePlumber ACP/jack setup |
| Device 1 | r7 | Upstream accelerometer matrix and 12 Hz request, enabled by kernel patch 0143 |

| Origin | Retained in 7.3.1-r0 | Purpose |
|---|---|---|
| r9 | `CONFIG_LOCALVERSION="-t825"` | Separate release/module directory |
| r9 | `CONFIG_SECURITY_LANDLOCK=y`; `landlock` first in `CONFIG_LSM` | pacman download sandbox |
| r9 | `CONFIG_NETFILTER_XT_CONNMARK=m`, `CONFIG_NETFILTER_XT_MATCH_CONNMARK=m`, `CONFIG_NETFILTER_XT_TARGET_CONNMARK=m` | Tailscale connmark support |
| r10 | `CONFIG_BT_RFCOMM=m`, `CONFIG_BT_RFCOMM_TTY=y`, `CONFIG_BT_BNEP=m`, `CONFIG_BT_BNEP_MC_FILTER=y`, `CONFIG_BT_BNEP_PROTO_FILTER=y` | Bluetooth RFCOMM/PAN |
| r10 | `# CONFIG_SECURITY_SELINUX is not set` | Explicit noninteractive configuration |
| r11 | `CONFIG_LRU_GEN=y`, `CONFIG_LRU_GEN_ENABLED=y` | Multi-Gen LRU |
| r11 | `CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y`; ALWAYS disabled | Huge pages on request |
| r11 | 0114 → 0202 | SM-T825 top speakers |
| r12 | Upstream 0122 and 0123 | Shared-buffer GPU mappings; these remain upstream patches |
| r13 | 0201 | Shared-VM GPU hang accounting |

The normalized config also records the build toolchain (Alpine clang 23.1.5),
Landlock's selected SECURITY_NETWORK/PATH and logging default, and the MGLRU
WALKS_MMU selection (STATS remains off). These are consequences of the requested
config and `olddefconfig`, not extra tuning. Upstream disables CRYPTO_DEV_QCE
because 7.3 marks it BROKEN on ARCH_QCOM; CPU crypto extensions remain available.

### Patch accounting

Source: [upstream migration notes at the pinned commit](https://github.com/wh1ter0z3/gts3lwifi-mainline/blob/9f81231/docs/kernel-7.3.md).
The commit IDs below were checked in mainline history as ancestors of v7.3
(and the eight SLIMbus fixes as ancestors of v7.1), hence included in 7.3.1.
A reverse-apply failure alone is not evidence that a patch is absent.

| Was | Mainline | Subject |
|---|---|---|
| 0056 | 185cd1d8cb | dt-bindings: Input: Add Wacom W9000-series penabled touchscreens |
| 0057 | acaefbacc9 | Input: Add support for Wacom W9000-series penabled touchscreens |
| 0064 | 9a29ee801f | Input: rmi4 - use platform data instead of query, when available |
| 0086 | ec35c19696 | usb: gadget: f_ncm: Fix net_device lifecycle with device_move |
| 0087 | e002e92e88 | usb: gadget: u_ether: Fix NULL pointer deref in eth_get_drvinfo |
| 0105 | 120134fe75 | slimbus: qcom-ngd-ctrl: fix OF node refcount |
| 0106 | 8663e8334d | slimbus: qcom-ngd-ctrl: Fix up platform_driver registration |
| 0107 | 2c22ff152d | slimbus: qcom-ngd-ctrl: Fix probe error path ordering |
| 0108 | 960b53a3f7 | slimbus: qcom-ngd-ctrl: Correct PDR and SSR cleanup ownership |
| 0109 | 2a9d50e9ea | slimbus: qcom-ngd-ctrl: Register callbacks after creating the ngd |
| 0110 | 07c564ea5f | slimbus: qcom-ngd-ctrl: Initialize controller resources in controller |
| 0111 | 6a003446b7 | slimbus: qcom-ngd-ctrl: Balance pm_runtime enablement for NGD |
| 0112 | 55f2ea9ff8 | slimbus: qcom-ngd-ctrl: Avoid ABBA on tx_lock/ctrl->lock |
| 0113 | 8a066a81ee | ASoC: qcom: q6asm: drop DSP responses for closed data streams |
| msm8996 SSR-notifier patch | no one-to-one commit | slimbus: qcom-ngd-ctrl: Register SSR notifier after all initialization steps: 7.3.1 registers it at the end of probe |
| old 0011 | cee3e63e71 | Stopped-stream handling is in mainline; replaced by upstream’s reduced `0011-asoc-qcom-q6asm-dai-reset-queue-ptr-on-prepare.patch`, not dropped wholesale |
| our 0114 | not in mainline | Renamed and rebased as 0202; upstream now uses 0114 for the I2C hot-plug binding |

Upstream's migration document counts the earlier 0001–0148 snapshot (112 patches);
9f81231 contains 124 numbered patches, including touch keys, headset detection,
GPU memory OPPs and Venus crop handling through 0182. Patches 0122/0123 are still
needed: mainline 00dfa76bdfc2 supplies their 7.3 API context, not their fixes.

### Top speakers (patch 0202)

Our former 0114 is now `0202-arm64-dts-qcom-gts3llte-top-speakers.patch`.
It removes the LTE overrides that reserve TLMM 58–61 and delete the top-speaker
link. The LTE tree inherits the quaternary TDM pinctrl/link and RT5508 amplifiers
at 0x34 and 0x35 from the Wi-Fi tree; TLMM 25–28 stay reserved. Both SPI/I2C
controllers sharing the quaternary pins remain disabled. Decompiled package DTBs
verify this layout. All four speakers played on this repo's 6.19.5 build (top left,
bottom right in landscape with Home on the right); 7.3.1 on the SM-T825 is untested
here and must repeat that check.

### GPU hangs and the compositor (patch 0201)

The Adreno 530 has no per-process page tables: every process shares one GPU address space. When a
process hangs the GPU, the kernel resets it, blames the submit that hung and replays the others.
Before 0201 it also counted the hang on the shared address space, so the fault counter that Mesa
reads (`MSM_PARAM_FAULTS`) changed for every process. freedreno turns that into
`GL_INNOCENT_CONTEXT_RESET` for every context that asked for reset notification, and Hyprland
0.57 aborts on any reset ("glGetGraphicsResetStatus returned ... Cannot continue until proper GPU
reset handling is implemented"). A browser hanging the GPU therefore restarted the whole desktop.

0201 does not count hangs on the shared address space. The process that hung the GPU still reads
`GL_GUILTY_CONTEXT_RESET` (from its submit queue), and the others see no reset, which is
what GPUs with per-process page tables already do. Tested on 6.19.5 with `tools/gpuhang.c`, a shader
that never ends: with r12 Hyprland restarted at the first hang, with r13 it kept running.

What 0201 cannot fix: the A530 does not always come back cleanly from a reset. Sometimes the next
submits hang as well (the kernel log shows "ME master split" and another "hangcheck detected gpu
lockup"), and if one of them is Hyprland's, Hyprland is the guilty one and still exits. So the
browser flag in `desktop/browser/chromium-flags.conf` matters more: it removes the hangs.

The patch is retained unchanged and compiles on 7.3.1. Its runtime behavior must
be rechecked on the SM-T825; the earlier r13 result is not a 7.3.1 test.

## Device files

The headset UCM and `51-gts3lwifi-audio.conf` match upstream 9f81231. The Arch
`rootfs/files/ucm-HiFi.conf` is identical to the device UCM; routing the top pair
remains conditional on its controls. The device accelerometer rule matches
upstream, including `in_accel_sampling_frequency="12"` (about 12.5 Hz).
Arch's `/etc` override retains this repo's Hyprland matrix and repeats the same
rate rule, because `/etc` replaces the entire `/usr/lib` rule of the same name.
The rootfs builder already copies the device's WirePlumber audio config into
`/etc/wireplumber/wireplumber.conf.d/51-gts3lwifi-audio.conf`.

Upstream's newer GNSS services/dependencies, TrustZone firmware extraction and
KDE key mappings are not needed for this SM-T825 kernel migration and are not
imported. The LTE modem DSP is still disabled in this tree; GNSS/LTE enablement
is a separate task. Arch retains its firmware extraction and desktop key policy.

## Build and validation

Configure pmbootstrap with the pinned pmaports checkout, then build both packages:

```sh
pmbootstrap build --force linux-postmarketos-qcom-msm8996
pmbootstrap build --force device-samsung-gts3lwifi
```

The APKs land in `$(pmbootstrap config work)/packages/edge/aarch64/`. Inspect
`boot/vmlinuz` (gzip-decompress it before `strings`), both DTBs under `boot/dtbs/qcom/`,
and the build's `.config` or the embedded IKCONFIG with Linux's
`scripts/extract-ikconfig`. The expected version is `Linux version 7.3.1-t825`.
Check all retained config symbols above and decompile the LTE DTB with `dtc -I dtb -O dts`.
Build and static checks are host evidence; they do not validate tablet hardware.

## Updating and rolling back on the tablet

The kernel lives in `/boot` (ext2 on `cache`), which pacman never touches.
Keep a known-good 6.19.5 test image and its device tree for recovery.
**7.3.1 requires its matching DTB. Do not use the 6.19.5 DTB with it:** the
ADSP/GPU/SLPI/Venus reserved-memory addresses and board definitions changed,
including cdc_reset_active, the MultiMedia4 headset link, touch keys and jack support.

1. Build both packages and refresh your pmbootstrap rootfs/initramfs. With your
   own isolated config, use a wrapper as `PMB` for `install/make-initramfs.sh`
   (the wrapper must pass `--config /path/to/pmbootstrap.cfg`). Run
   `PMB=/path/to/wrapper FIRMWARE_DIR=... install/make-initramfs.sh /var/tmp/t825-boot`.
   Copy the new modules to the tablet's `/usr/lib/modules/7.3.1-t825` before the
   RAM test; leave `/usr/lib/modules/6.19.5-t825` intact. Userspace may need modules
   not in the initramfs during the RAM boot.
2. **Test from RAM first.** On the tablet run `t825-reboot-fastboot`; on the host:

   ```sh
   KERNEL=/var/tmp/t825-boot/vmlinuz INITRAMFS=/var/tmp/t825-boot/initramfs \
     DTB_DIR=/var/tmp/t825-boot/dtbs \
     CMDLINE_EXTRA="pmos_root_uuid=<root uuid> pmos_rootfsopts=<options>" \
     install/make-boot-image.sh /var/tmp/t825-test.img
   fastboot boot /var/tmp/t825-test.img
   ```

   Use the `append` line of your extlinux.conf for the root values. Check Hyprland
   and `tools/gpuhang.c`, all four speakers, headset insertion/removal and mic,
   repeated suspend plus Wi-Fi after resume, sensors/rotation, both cameras,
   Venus decode/encode, S Pen, touch and charging. These are pending human tests.
3. After the RAM test passes, boot the old installed kernel before updating.
   Make the archive with `tar -C <extracted-apk>/lib/modules -cf modules.tar 7.3.1-t825`.
   Copy it, vmlinuz, initramfs and the new `msm8996-samsung-gts3llte.dtb` to the tablet.
   Install them together, passing the DTB as the fourth argument:

   ```sh
   sudo install/update-kernel.sh modules.tar vmlinuz initramfs msm8996-samsung-gts3llte.dtb
   ```

   The script backs up the installed kernel, initramfs and DTB as `.prev`, then
   installs the new files. Reboot and verify the installed kernel.
4. To roll back, boot the known-good RAM image if necessary, then run
   `sudo install/rollback-kernel.sh` and reboot. Rollback restores the kernel,
   initramfs and the DTB `.prev` when present. During the 6.19.5 → 7.3.1 transition,
   the old modules remain in place and no modules archive is needed.

Update validates the incoming gzip kernel's release against `KVER` before writing
anything to `/boot`. To decide whether to archive modules, it reads the release
from the **installed kernel that will become `.prev`**. This also works after a
RAM test or with an offline root; the host's running kernel is irrelevant.
When that release equals `KVER` and its module directory exists, update saves
`/var/tmp/t825-kernel/modules-prev.tar` and writes `modules-version`. Rollback
restores the archive using that recorded release.

On a release transition, even when `/usr/lib/modules/7.3.1-t825` was staged for
the RAM test, update treats it as a fresh install: it removes any stale archive
and `modules-version`, leaves the 6.19.5 modules intact, and installs the new
modules. A legacy 6.19.5 archive without metadata needs
`sudo KVER=6.19.5-t825 install/rollback-kernel.sh`; a mismatched archive produces
an explicit error before restoration.

The fourth DTB argument is optional for reinstalls that keep an already matching
DTB. Omitting it leaves the installed DTB alone and removes an unrelated DTB
`.prev`, so rollback cannot restore a DTB from an earlier update. For this
6.19.5 → 7.3.1 migration, always supply the new DTB.

Both scripts check free boot space for all temporary copies plus filesystem
overhead before writing, copy to temporary files on the same filesystem, sync,
and rename each completed file. Update stages all backups and replacement boot
files before replacing any destination; rollback stages all boot files before
restoring them. A copy failure leaves the existing files and backups intact.
This needs space for the staged copies as well as the installed files and any
existing backups. Individual renames are atomic; a power loss between renames
can still interrupt the set, so keep the known-good RAM image available.

Keep the boot files and modules from the same build together. There is one
rollback slot; each update replaces it. `ROOT=/path/to/offline-root` redirects
both scripts (its `/boot` must be mounted). Run `python3 install/test-kernel-scripts.py`
for the fake-root tests, including staged modules, same-release reinstalls,
legacy metadata, DTBs, invalid inputs, free-space checks and failed copies.

## Runtime evidence, risks and follow-ups

This repo's 7.3.1 build is **untested on the SM-T825**. Upstream's older migration
notes describe T820 testing only. Its [newer README at 9f81231](https://github.com/wh1ter0z3/gts3lwifi-mainline/blob/9f81231/README.md#needs-testing)
records one T825 tester's successful 7.3.1 boot, smooth UI, Wi-Fi and audio on
`t825-modem` (main plus modem work), not this exact build. Do not generalize it to
our device tree, Arch userspace or the rest of the hardware.

Upstream tested four consecutive 20-second s2idle cycles on the T820 with patches
0147 (keep PCIe link/Wi-Fi power) and 0148 (MDP5 resume pipe assignment), with
Wi-Fi traffic after resume. Suspend and Wi-Fi resume remain untested here on T825.

Upstream's migration notes report more `pclk0_clk_src: rcg didn't update its
configuration` warnings (picture still correct), intermittent Bluetooth
`Opcode 0x0c03 failed: -110` at boot (also present on 6.19), and occasional
`wcd9335: overflow error on TX port 1` at capture start (recordings played back).
A failed Bluetooth controller recovered upstream with `rmmod hci_uart; modprobe hci_uart`.
7.3.x is not a long-term base and will reach EOL; plan a later supported-kernel move.

Follow-ups: hardware validation above; evaluate the a5xx hangcheck backport
`65222fbe8` separately (out of scope here); track the clock, Bluetooth and WCD9335
issues; update published binaries only after tablet testing.
