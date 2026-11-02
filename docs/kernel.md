# Kernel

The kernel is postmarketOS' `linux-postmarketos-qcom-msm8996` 6.19.5 with the Galaxy Tab S3
patches from [wh1ter0z3/gts3lwifi-mainline](https://github.com/wh1ter0z3/gts3lwifi-mainline),
built with pmbootstrap. It reports itself as `6.19.5-t825`.

## Sources in this repository

- `pmaports/linux-postmarketos-qcom-msm8996/`: the complete package (APKBUILD, config, patches
  0001-0114, 0122-0123 and 0201). Copy it over `device/testing/linux-postmarketos-qcom-msm8996` of a pmaports checkout
  at commit `367abb3e17df1299380271c9e52c0824fc7378d3` (2026-11-01).
- `pmaports/device-samsung-gts3lwifi/`: the device package (deviceinfo, UCM, udev rules,
  gts3-bdaddr, gts3-firmware). It covers both the SM-T820 and the SM-T825.
- `pmaports/pmaports-367abb3e-kernel.diff`: APKBUILD and config against that pmaports commit.

## Relation to upstream

Patches 0001-0113 and the base config are byte-identical to upstream commit
`363ed942cc761d7be7cf16ebc8b3d1dc358998d1` (2026-11-01, "kernel r8"). On top of that:

| pkgrel | Change | Why |
|---|---|---|
| r9 | `CONFIG_LOCALVERSION="-t825"` | modules go to `/usr/lib/modules/6.19.5-t825` and do not clash with an older 6.19.5 |
| r9 | `CONFIG_SECURITY_LANDLOCK=y`, first in `CONFIG_LSM` | pacman 7 sandboxes its downloads with Landlock |
| r9 | `CONFIG_NETFILTER_XT_CONNMARK`, `_MATCH_CONNMARK`, `_TARGET_CONNMARK` (=m) | Tailscale's rp_filter workaround |
| r10 | `CONFIG_BT_RFCOMM` (+TTY), `CONFIG_BT_BNEP` (+filters) (=m) | Bluetooth hands-free profiles and PAN |
| r10 | `# CONFIG_SECURITY_SELINUX is not set` | the symbol was missing and the build stopped to ask |
| r11 | `CONFIG_LRU_GEN=y`, `CONFIG_LRU_GEN_ENABLED=y` | Multi-Gen LRU: better reclaim with 3.5 GiB RAM, thrashing protection (`min_ttl_ms`) |
| r11 | `CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y` (was ALWAYS) | huge pages only where requested |
| r11 | patch `0114-arm64-dts-qcom-gts3llte-top-speakers.patch` | enables the top speaker pair on the SM-T825 (below) |
| r12 | patches `0122` and `0123` from upstream commit `007853c` | GPU mappings of a shared buffer stay until the last reference goes; fixes TRANSLATION faults when a buffer is shared between processes |
| r13 | patch `0201-drm-msm-shared-vm-hang-accounting.patch` | a GPU hang no longer looks like a reset to every other process (below) |

### Top speakers (patch 0114)

Upstream's gts3llte device tree leaves the top speaker pair out ("until checked") and reserves TLMM
GPIOs 58-61. The stock SM-T825 device trees show that those pins are the quaternary TDM bus there as
well, so 0114 drops the reservation and adds the quaternary TDM link and both RT5508 amplifiers
(0x34, 0x35). Checked on hardware: four speakers play, top pair left channel, bottom pair right
(landscape, Home on the right).

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
what GPUs with per-process page tables already do. Tested with `tools/gpuhang.c`, a shader
that never ends: with r12 Hyprland restarted at the first hang, with r13 it kept running.

What 0201 cannot fix: the A530 does not always come back cleanly from a reset. Sometimes the next
submits hang as well (the kernel log shows "ME master split" and another "hangcheck detected gpu
lockup"), and if one of them is Hyprland's, Hyprland is the guilty one and still exits. So the
browser flag in `desktop/browser/chromium-flags.conf` matters more: it removes the hangs.

### Upstream since then

Upstream has moved on (patches 0114-0148 there: Book Cover Keyboard hot-plug, SLPI sensor
timestamps, GPU fault fixes, display resume). Only the GPU fault fix (0122-0123) is in this kernel.
Note that upstream's 0114 is a different patch from ours, and 0201 is our number for a patch
upstream does not have.

## Building

    pmbootstrap build --force linux-postmarketos-qcom-msm8996

About 5 minutes on a 16-core x86_64 host (cross-compiled with clang). The package lands in
`$(pmbootstrap config work)/packages/edge/aarch64/`. `release/` has the r13 package and its
`vmlinuz` and device trees for reference.

## Updating the kernel on the tablet

The kernel lives in `/boot` (the ext2 on `cache`), which pacman never touches.

1. Build the package and refresh the initramfs: `FIRMWARE_DIR=... install/make-initramfs.sh out/boot`.
2. Test from RAM: run `t825-reboot-fastboot` on the tablet, then
   `KERNEL=out/boot/vmlinuz INITRAMFS=out/boot/initramfs DTB_DIR=out/boot/dtbs
   CMDLINE_EXTRA="pmos_root_uuid=<root uuid> pmos_rootfsopts=<options>" install/make-boot-image.sh test.img`
   and `fastboot boot test.img`. Use the `append` line of your extlinux.conf for the two values.
3. Install: copy the modules tar (`tar -C <pkg>/lib/modules -cf modules.tar 6.19.5-t825`), vmlinuz,
   initramfs and, if it changed, `dtbs/qcom/msm8996-samsung-gts3llte.dtb` to the tablet, then
   `sudo install/update-kernel.sh modules.tar vmlinuz initramfs`. `install/rollback-kernel.sh`
   restores the previous set.

Every build has the same release string, so modules, `vmlinuz-t825` and `initramfs-t825` must be
changed together.
