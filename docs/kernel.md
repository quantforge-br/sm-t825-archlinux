# Kernel

The source package is `linux-postmarketos-qcom-msm8996` **7.3.1-r2**, with release
string **7.3.1-t825** and modules in `/usr/lib/modules/7.3.1-t825` on Arch
(`/lib/modules/7.3.1-t825` inside the APK). It replaces the previous 6.19.5-r13
source package. The files in `release/` remain the previous 6.19.5 release; the
tablet currently still boots the already-installed `7.3.1-t825` r1 image.

## Sources and relation to upstream

The baseline is [wh1ter0z3/gts3lwifi-mainline at 9f81231ac11893d46d4b6a8af7abe8e3c863ad05](https://github.com/wh1ter0z3/gts3lwifi-mainline/tree/9f81231ac11893d46d4b6a8af7abe8e3c863ad05).
All 194 upstream patches are byte-identical: 70 `m001`–`m071` patches (no m056),
and 124 numbered patches from `0001` through `0182`, with upstream's gaps and
APKBUILD order. The package uses the kernel.org 7.3.1 tarball; msm8996-mainline's
last base tag was 6.19.5. Upstream's `APKBUILD.pmaports` is named `APKBUILD` here,
with our package revision, config checksum, production patches 0201, 0202 and
0204, and four opt-in private patches (0203 MSS, 0205 codec diagnostics,
0206 SLIMbus diagnostics and 0207 experimental NGD channel removal).
The package also carries 0204, the upstream A5xx hangcheck progress detection
backport from `65222fbe8`. It is applied after 0201 and 0202, and was checked
against vanilla Linux 7.3.1 and the 0201 tree. The normal r2 payload now has an
exact `#3` RAM-boot identity check, a verified read-only root transition and
an observed automatic return to installed r1 in 275.535 seconds. Evidence:
`artifacts/roadmap-7.3/readonly-r2-cycle-20261111T002227Z/`. This does not run a
graphical session; use the controlled GPU workload before installing r2
persistently. Reset returned to Linux, so another unattended fastboot cycle
was not available.

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
| Kernel 7.3.1 | r1 | Trim tracing to fit persistent boot; enforce the lk2nd size budget during build/install |
| Kernel 7.3.1 | r2 | 0204 A5xx hangcheck progress detection; normal `#3` RAM handoff and automatic return to installed r1 accepted; controlled GPU recovery comparison remains open |
| Device 1 | r6 | Upstream headset microphone, jack controls and WirePlumber ACP/jack setup |
| Device 1 | r7 | Upstream accelerometer matrix and 12 Hz request, enabled by kernel patch 0143 |
| Device 1 | r8 | Upstream TC305K Back/Recent input-events LED timeout rule |
| Device 1 | r10 candidate | HCI readiness no longer waits for delayed BlueZ daemon exposure; the combined r10 helper test was rejected after 2/8 faults |
| Device 1 | r11 control | r9 helper plus eight-second delay; earlier 20/20 was contradicted by a later 1/5 timeout control. r12 experiments were rejected and r11 restored; see [investigation](bluetooth-7.3.md) |

| Origin | Retained in 7.3.1-r2 | Purpose |
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

### Size-focused configuration changes in r1

The r13 config in commit `8d6a3e4` (unchanged since `b915c97`) was compared
with the 7.3.1-r0 config at `a1fd48d`. The Image grew by **1,910,784 bytes**.
The config adds built-in pinctrl drivers for Eliza, Hawi, IPQ5210, IPQ9650,
Maili, Nord and Shikra, and GCC drivers for Eliza, Kaanapali, Nord, Shikra,
Hawi, IPQ5210 and IPQ9650. Other additions include scheduler/arm64 features,
Kerberos/Camellia crypto and promoted crypto/netfilter dependencies. Compiler
and kernel code also changed; the config diff alone cannot assign byte counts
to those sources of growth.

Non-QCOM platforms, `KALLSYMS_ALL`, BTF and KUnit/selftests were already off.
DWARF debug information lives outside the raw Image, so disabling it would
not address this limit. The final trim disables `CONFIG_FTRACE`, including
function/function-graph tracing, event tracing and kprobe/uprobe/BPF trace
attachments selected through that menu. This gives measured savings without
changing any hardware-driver selection or converting built-ins to modules.

Measured with the same isolated Alpine clang 23.1.5 build setup:

| Measurement | Decompressed Image / lk2nd metric | Gzip bytes | Incremental Image savings |
|---|---:|---:|---:|
| 6.19.5-r13 reference | 27,445,760 | 11,324,059 | — |
| 7.3.1-r0 baseline | 29,356,544 | 11,925,603 | — |
| Disable function/function-graph tracing (trial) | 28,434,944 | 11,705,043 | 921,600 |
| Disable remaining ftrace/event infrastructure (r1) | 23,966,208 | 10,526,949 | 4,468,736 |

Total Image savings are **5,390,336 bytes**; headroom is **4,140,544 bytes**
against 28,106,752. The final arm64 header `image_size` is **24,707,072**,
which is deliberately not used as the metric. Gzip byte counts can vary with
build timestamps. A broad exploratory debug trim was discarded in favor of
this tracing-only change.

Kept: `-t825`, Landlock-first LSM, SELinux off, CONNMARK, RFCOMM/BNEP, MGLRU,
THP madvise; MDP5/DSI/panel, Adreno a5xx, WCD9335/ADSP, SLPI/SMGR, ath10k,
Bluetooth, Venus/cameras, NCM gadget, touchscreen/S Pen/touch keys/gpio-keys,
SM5705, thermal, btrfs, ext4's ext2 support, Tailscale netfilter, rmtfs/qrtr
and remoteproc. `modules-initfs` still contains `msm` and
`panel-samsung-ams968hh01`; no initramfs module requirement changes.
Kallsyms, perf hardware/software counters, BPF networking/syscalls, debugfs, dynamic debug, pstore/ramoops
and the embedded config remain available for runtime diagnosis.

The tracing trim removes these runtime diagnostics:

- Perf tracepoint workloads, including `perf trace`, `perf sched` and
  `perf record -e sched:*`; retained perf counters do not restore them.
- Kprobe/uprobe events and tracing-based bpftrace/BCC workflows.
- The tracefs interface at `/sys/kernel/tracing` (or debugfs `tracing/`),
  and trace-cmd recording. Keeping debugfs does not keep its tracing interface.
- MSM GPU and DRM tracepoints. Powertop loses tracepoint-based accounting and
  is degraded, even though some non-tracing measurements remain available.

A repository scan of `pmaports/device-samsung-gts3lwifi/`, `rootfs/` and `tools/`
found no tracefs, perf, debugfs-tracing, bpftrace/BCC, trace-cmd or powertop
consumers. `tools/gpuhang.c` uses EGL/GLES reset status and dmesg, not tracing.
However, the historical frame-counting method in [performance.md](performance.md)
uses `drm_msm_atomic` and `drm` tracepoints on 6.19.5-r13. That measurement method
cannot be repeated with the trimmed r1 kernel. No config change is made to
restore these diagnostic features.

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
bottom right in landscape with Home on the right); the 7.3.1 baseline has not yet
remeasured speaker acoustics or headset routing.

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

The patch is retained unchanged and compiles on 7.3.1. The installed SM-T825 build
ran three synthetic resets: each identified `gpuhang` as guilty, recovered normal
drawing and kept the same Hyprland process. This validates reset handling, not the
root cause of Chromium/Mesa hangs.
The repeat on the installed r1 kernel is archived at
`artifacts/roadmap-7.3/gpu-r1-20261110T080117Z/`; all three runs passed with the
same Hyprland process. A matching r2 run remains pending because this tablet's
remote bootloader command currently enters Samsung Download mode rather than
lk2nd fastboot, and no flashing path is permitted.
The normal r2 RAM image is retained at
`artifacts/roadmap-7.3/normal-r2-boot-20261110/t825-normal-r2.img`; it lacks
validated independent recovery. The later candidate in
`normal-r2-recovery-20261110d/` is **rejected: do not boot it**. Merely adding
a supervisor does not disable installer mutations, protect the root block
devices or prove survival across `switch_root`. Its construction also used
DTBs from the MSS diagnostic tree without validating the production state.
The unsafe experimental builder has been removed.

The report `artifacts/roadmap-7.3/r2-ram-validation-20261110T114526Z/` actually
observed installed r1 (`#2-postmarketos-qcom-msm8996`), and contains no fastboot
boot transcript. Its `decision.json` rejects r2 and supervisor acceptance; only
one installed-r1 software reboot with Bluetooth readiness passed. A new
comparison requires verified r2 identity and a validated read-only diagnostic
root with RAM-backed writable paths for the graphical session.
The real-browser collector `tools/t825-chromium-gpu-test.sh` was added with a
bounded Wayland/WebGL workload and DRM/kernel/Hyprland capture. The tablet has
Brave-origin rather than a `chromium` executable; a 10-second run completed with
Hyprland's PID unchanged and no new GPU reset lines. This is a workload baseline,
not the required real-hang reproduction. Evidence:
`artifacts/roadmap-7.3/chromium-gpu-20261110T084239Z/`.

The first attempt to chain that workload onto the recovery-capable r2 image is
recorded at `artifacts/roadmap-7.3/gpu-r2-ram-20261110T115000Z/`. The tablet's
normal reboot path returned directly to installed r1, so the guarded host
runner correctly stopped before issuing `fastboot boot`; the tablet remained
healthy and no r2 GPU result was claimed. A future comparison needs a remote
boot-mode transition that exposes lk2nd fastboot without renaming persistent
boot files.
The reset action and boot-mode selection are separate. The live kernel exposes
`bootloader`, `recovery` and `normal` through
`/sys/class/reboot-mode/qcom-pon/reboot_modes`; PS_HOLD (`syscon-reboot`)
performs the reset. The documented lk2nd base enables `USE_PON_REBOOT_REG=1`
and interprets PON reason `0x02` as fastboot. That is also Linux's `bootloader`
value, already observed to select Samsung Download before lk2nd. Unknown
strings such as `fastboot` do not supply an alternate mode in Linux's
`reboot-mode` driver. The previously used `t825-reboot-fastboot` helper remains
installed: it renames `/boot/extlinux/extlinux.conf` to `extlinux.conf.fastboot`
and requests a normal reboot. This changes the persistent `cache` filesystem
mounted at `/boot`, although it does not flash the partition named `boot`.
The unattended test policy explicitly forbids that mutation. Its restore
service requires a writable `/boot` and systemd; the direct-init read-only
diagnostics do not run it. Reusing this route requires an explicit policy
exception and a verified restoration path after the test session.
The read-only source/live audit is retained at
`artifacts/roadmap-7.3/reboot-route-source-audit-20261110T180230Z/`.
After explicit authorization for the persistent extlinux exception, a detached
round-trip controller was validated. It entered lk2nd fastboot remotely,
restored the original 919-byte configuration from a validated RAM image, and
returned to Arch with a new boot ID and the original SHA-256. Evidence is in
`artifacts/roadmap-7.3/authorized-fastboot-roundtrip-20261111T101000Z/`.
It establishes no new tested route: the dirty installed lk2nd device additions
were not reconstructed. Kexec is configured and not disabled. A native aarch64
`kexec-tools` 2.0.32 probe loaded and unloaded the read-only candidate through
the legacy syscall, with `/sys/kernel/kexec/loaded` returning to zero and no
`kexec -e`; this is recorded at
`artifacts/roadmap-7.3/kexec-route-audit-20261110/`. A nonpersistent handoff
route remains a prerequisite for the r2 RAM comparison from installed Linux,
and execution still requires independent reset recovery. The first guarded
execution attempt is recorded at
`artifacts/roadmap-7.3/kexec-cycle-20261110T191300Z/`: load succeeded and
`kexec -e` was invoked, but no SSH, ADB or fastboot appeared for 360 seconds.
The host saw the Samsung NCM product without carrier and repeated USB resets;
the candidate supervisor was therefore unobserved. The runner now stops the
installed USB gadget immediately before a future execution, but another cycle
must wait for manual fastboot recovery and a reviewed pre-supervisor route.

## Device files

The headset UCM and `51-gts3lwifi-audio.conf` match upstream 9f81231. The Arch
`rootfs/files/ucm-HiFi.conf` is identical to the device UCM; routing the top pair
remains conditional on its controls. The device accelerometer rule matches
upstream, including `in_accel_sampling_frequency="12"` (about 12.5 Hz).
Arch's `/etc` override retains this repo's Hyprland matrix and repeats the same
rate rule, because `/etc` replaces the entire `/usr/lib` rule of the same name.
The rootfs builder already copies the device's WirePlumber audio config into
`/etc/wireplumber/wireplumber.conf.d/51-gts3lwifi-audio.conf`.

The device package and rootfs builder also install upstream `61-gts3-keys.rules`:
TC305K Back/Recent LEDs use the `input-events` trigger and turn off after five
seconds without input. This is independent of KDE key mappings. We exclude
`61-gts3-keys.hwdb` (it maps Home to Meta, breaking the Hyprland Home bind) and
`gts3-kglobalshortcutsrc`.

Upstream's newer GNSS services/dependencies, TrustZone firmware extraction and
KDE key mappings are not needed for this SM-T825 kernel migration and are not
imported. The LTE modem DSP is still disabled in this tree; GNSS/LTE enablement
is a separate task. Arch retains its firmware extraction and desktop key policy.

## Persistent-boot size budget

lk2nd **23.1-next-fd380ac6** rejects a gzip kernel using its **actual decompressed
byte count**, not the arm64 header's `image_size`. At revision
[fd380ac637d1af38598e3f3c5321d4c962b96315](https://github.com/msm8916-mainline/lk2nd/tree/fd380ac637d1af38598e3f3c5321d4c962b96315):

- [`lib/zlib_inflate/decompress.c:133–134`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lib/zlib_inflate/decompress.c#L133) returns `stream->total_out`.
- [`lk2nd/boot/extlinux.c:578–595`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lk2nd/boot/extlinux.c#L578) stores that count in `kernel_size` and compares it with `kernel_max_size`.
- [`extlinux.c:479–531`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lk2nd/boot/extlinux.c#L479) computes `rounddown(boot_memory - initramfs_bytes, 4096) - 2097152 - kernel_offset`.
  [`lk2nd/boot/rules.mk:15`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lk2nd/boot/rules.mk#L15) defaults boot memory to `0x03200000` (50 MiB).

For the failed install, the initramfs is **22,222,608 bytes** and the arm64
`text_offset` is **0**. Thus `rounddown(52428800 - 22222608, 4096) - 2097152 - 0`
is **28,106,752 bytes**. This is a budget for that boot layout, not a universal
lk2nd maximum: a larger initramfs reduces it. The nonzero header `image_size`
only selects use of `text_offset`; it is not the size being compared.
For an arm64 header with zero `image_size`, the offset is `0x80000`; an
arm64 `text_offset` greater than 2 MiB forces offset zero even in that case.
Without ARM64 magic, the offset is `0x8000`. The installer decodes the first
64 bytes without binutils and applies these same rules. For raw,
uncompressed kernels, extlinux instead uses `(file_bytes / 16 + 1) * 16`.
This package and installer use gzip kernels.

lk2nd's inflate stops at the first gzip member
([`decompress.c:119–134`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lib/zlib_inflate/decompress.c#L119)),
whereas `gzip -dc` concatenates all members. The installer's byte count is
therefore conservative for concatenated gzip streams; it also rejects CRC
errors and truncation even when a Linux version banner was already decoded.

The DTB must be **strictly smaller than 2,097,152 bytes** (`MAX_TAGS_SIZE`):
[`extlinux.c:600–607`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/lk2nd/boot/extlinux.c#L600)
rejects a load that fills the reservation. The reservation is already subtracted
in the formula; actual DTB bytes do not further consume the kernel budget.
The installer rejects a DTB at or above that size when the fourth argument is
provided; an existing DTB retained by omitting it still needs to satisfy this rule.

Measure without binutils, checking the complete gzip stream for corruption:

```bash
set -o pipefail
gzip -dc -- vmlinuz | wc -c       # lk2nd metric
stat -c %s vmlinuz               # compressed size
wc -c < arch/arm64/boot/Image    # same metric in the build tree
```

`install/update-kernel.sh` is the actual boot-layout size guarantee: before any
mutation, it uses the size of the initramfs passed as argument 3 and the kernel's
header to compute the budget. `LK2ND_BOOT_MEM_SIZE` defaults to **52,428,800**
bytes; override it only to match the bootloader's configured pool. The optional
`LK2ND_MAX_KERNEL_SIZE` is an extra cap with no default in the installer:
`effective = min(computed_budget, cap)` when provided. A cap can never enlarge
the computed budget. The installer prints the arithmetic and refuses an
initramfs at or above boot memory, or a nonpositive budget, instead of allowing
lk2nd's uint32 arithmetic to wrap. Overrides must be positive decimal byte
counts no larger than 4,294,967,295.

The APKBUILD check is only an **early warning for the reference layout**:
22,222,608-byte initramfs, 50 MiB pool, 2 MiB tags and zero text offset. It
fails if `Image` exceeds `LK2ND_MAX_KERNEL_SIZE` (build default **28,106,752**).
It cannot guarantee that a later initramfs fits. pmbootstrap may not forward
that environment override into its build chroot; do not assume a host-side
assignment changes the build limit. The installer independently checks the
actual artifacts.

**At most 27,000,000 Image bytes is a manual release goal**, not an additional
automated build limit. It leaves at least 1,106,752 bytes of headroom against
the reference layout. Measure it with the commands above for each release.
With r1's **23,966,208-byte Image** and zero text offset, the largest fitting
initramfs is **26,361,856 bytes**: the budget is then 23,969,792. One more
initramfs byte drops the rounded budget to 23,965,696, below the Image size.
The unrounded figure 26,365,440 does not fit after 4096-byte rounding.

A successful **RAM `fastboot boot` test cannot validate this limit**. Its
[`app/aboot/aboot.c:3354–3395`](https://github.com/msm8916-mainline/lk2nd/blob/fd380ac637d1af38598e3f3c5321d4c962b96315/app/aboot/aboot.c#L3354)
path decompresses into scratch memory and uses boot-image load addresses;
it does not run extlinux's `choose_addrs()` budget check. The 7.3.1-r0 RAM
success therefore did not predict persistent-boot success. Keep the RAM test
for hardware validation, and perform this size check before persistent install.
The r1 build is installed on the SM-T825; its runtime baseline is recorded in
[baseline-7.3.md](baseline-7.3.md). This size calculation still must be repeated
for every new initramfs before persistent installation.

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
2. **Test from RAM first.** Start with the tablet already in lk2nd fastboot.
   Do not use `t825-reboot-fastboot` under the current diagnostic policy: it
   mutates persistent `/boot` as explained above. On the host:

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
3. After the RAM test passes, verify the decompressed-size budget above, then
   boot the old installed kernel before updating.
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

Update checks its required commands up front and validates the incoming gzip
kernel's release against `KVER` before writing anything to `/boot`. It scans the
binary banner with `grep -a`, so `strings`/binutils is not required. Both scripts
report missing commands explicitly; update consumes the entire gzip stream to
check for corruption or truncation. To decide whether to archive modules, it reads the release
from the **installed kernel that will become `.prev`**. This also works after a
RAM test or with an offline root; the host's running kernel is irrelevant.
When that release equals `KVER` and its module directory exists, update saves
`/var/tmp/t825-kernel/modules-prev.tar` and writes `modules-version`. Rollback
restores the archive using that recorded release.

On a release transition, even when `/usr/lib/modules/7.3.1-t825` was staged for
the RAM test, update treats it as a fresh install: it removes any stale archive
and `modules-version`, leaves the 6.19.5 modules intact, and installs the new
modules. A legacy 6.19.5 archive without metadata needs
`sudo ALLOW_LEGACY_MODULES=1 KVER=6.19.5-t825 install/rollback-kernel.sh` after
verifying the archive belongs to the saved kernel; a mismatched archive produces
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

Module extraction in both scripts goes into `/usr/lib/modules/.$KVER.new` using
a private `lib/modules/$KVER` layout. `depmod` runs against that staged tree before
any installed modules move. After successful extraction/indexing, the current
directory moves to `.$KVER.old`, the new directory takes its place, and the old
directory is removed. If removal of `.old` fails, the script warns and continues
publishing the matching boot files. Inspect the leftover directory before another
update or rollback; subsequent swaps refuse to overwrite it.
Failed extraction or indexing leaves the installed modules
untouched; a failed second rename restores the old directory. Rollback prints
the release and destination path before swapping. Staging needs enough free
space on the module filesystem for both trees. An unfinished `.new`/`.old` from
a hard interruption requires inspection before retrying.

Update stages the module backup archive and metadata, then publishes them
immediately after the matching boot backups; cross-release archive removal also
happens after boot backup publication. These steps span filesystems and are not
an atomic transaction across the entire rollback slot. `modules-binding` records
three lines: release, SHA-256 of the saved kernel, and SHA-256 of the module archive.
Rollback checks both hashes before changing anything and refuses mismatched or
malformed binding metadata. This catches interrupted publication in either direction,
including a stale archive after a cross-release boot backup. Legacy archives with
no binding require `ALLOW_LEGACY_MODULES=1` after manual verification and print an
unverified-backup warning. That option never bypasses a present but invalid binding.

Keep the boot files and modules from the same build together. There is one
rollback slot; **running update-kernel.sh twice replaces that slot twice**.
After the first 6.19.5 → 7.3.1 update, `.prev` contains 6.19.5. A second run,
even with identical inputs, makes 7.3.1 the `.prev` kernel and saves its modules;
rollback then returns to 7.3.1. Keep a separate recovery image if you need 6.19.5.
`ROOT=/path/to/offline-root` redirects
both scripts (its `/boot` must be mounted). Run `python3 install/test-kernel-scripts.py`
for the fake-root tests, including staged modules, same-release reinstalls,
legacy metadata, DTBs, invalid inputs, free-space checks and failed copies.

## Runtime evidence, risks and follow-ups

This repo's installed 7.3.1 build now has a bounded SM-T825 baseline; see
[baseline-7.3.md](baseline-7.3.md). Upstream's migration notes describe T820
testing and one T825 tester's modem branch. Do not generalize those results to
the production DT or to LTE functionality. The MSS/GNSS path remains an opt-in
diagnostic build and has not been installed persistently.

Upstream tested four consecutive 20-second s2idle cycles on the T820 with patches
0147 (keep PCIe link/Wi-Fi power) and 0148 (MDP5 resume pipe assignment), with
Wi-Fi traffic after resume. The installed T825 build passed ten 10-second cycles
with RTC wake, Wi-Fi ICMP, Bluetooth, PipeWire and sensors; a post-reboot repeat
passed ten additional cycles. See the baseline for the log-continuity guard.

Upstream's migration notes report more `pclk0_clk_src: rcg didn't update its
configuration` warnings (picture still correct), intermittent Bluetooth
`Opcode 0x0c03 failed: -110` at boot (also present on 6.19), and occasional
`wcd9335: overflow error on TX port 1` at capture start (recordings played back).
A failed Bluetooth controller recovered upstream with `rmmod hci_uart; modprobe hci_uart`.
The private r9 device package was then deployed with a read-only EFS read, three
consecutive controller/address probes, and one bounded QCA UART rebind. A detached
20-cycle reboot run required no manual reset and recorded 15 PASS and 5 FAULT
cycles. The faults remained the same transient `Frame reassembly failed (-84)` /
`Opcode 0x0c03 failed: -110` sequence, so r9 recovery is useful but the Bluetooth
compatibility item remains open. Evidence: `artifacts/roadmap-7.3/bluetooth-auto-20261110T060000Z/`.
A detached ten-cycle s2idle/RTC coexistence run then passed Bluetooth presence,
Wi-Fi ICMP return, PipeWire and sensors after every wake. This closes the
suspend coexistence sub-gate while the repeated-boot fault rate remains open.
Evidence: `artifacts/roadmap-7.3/suspend-bt-10-20261110T065730Z/`.
The r9 boot logs show the helper's BlueZ readiness check waiting through a
completed HCI setup and then causing another UART rebind. The candidate helper
now gates only on `btmgmt` primary-controller/address state. With `bluetoothd`
stopped on the running tablet, the candidate exited successfully without a
QCA setup delta; only the expected read-only EFS mount appeared in the kernel
delta. A fresh detached boot run is still required to quantify the reduction.
Evidence: `artifacts/roadmap-7.3/bluetooth-helper-candidate-20261110T071635Z/`.
The detached r10 run produced 18 PASS and 2 FAULT cycles. The two faults still
showed a second QCA firmware setup followed by `Opcode 0x0c03 failed: -110`,
so the daemon-readiness fix reduces the observed rate but does not close the
boot compatibility gate. The package-installed r9 helper was restored after
the test and its hash was verified. Evidence:
`artifacts/roadmap-7.3/bluetooth-r10-auto-20261110T072338Z/`.
The follow-up r11 service-order candidate keeps the r9 helper and adds an
eight-second pre-start delay, allowing the initial QCA setup to settle before
the address helper runs. A detached 20-cycle run passed every cycle with the
EFS address present and no `Opcode 0x0c03 failed: -110`; the known initial
`Frame reassembly failed (-84)` warning remained. The rebuilt r11 APK payload
hashes match that tested control. A separate r10-helper plus delay run failed
2/8 and was rejected. The tested r11 payload was installed after the experiment
without a reboot. A later five-reboot control reproduced `-110` once, so the
delay cannot be described as a proven fix. r12 experiments (longer delay and
waiting for a primary controller) were rejected and the r11 control restored.
See [Bluetooth investigation](bluetooth-7.3.md). Historical evidence and APK hashes are in
`artifacts/roadmap-7.3/bluetooth-delay-candidate-20261110T084940Z/`.
An EFS-BDADDR NVM candidate was then tested by replacing the placeholder address
bytes in `nvm_00440302.bin`. The following boot still emitted `Frame reassembly
failed (-84)`, performed a second QCA setup and reported `Opcode 0x0c03 failed:
-110`; the controller later became usable. The candidate was removed immediately
and no modified firmware remains installed. Evidence, hashes and the removed
candidate are in `artifacts/roadmap-7.3/nvm-candidate-20261110T081749Z/`.
The direct ALSA/UCM route matrix also passed twenty repetitions each for the
speaker PCM (`hw:0,0`), headphone PCM (`hw:0,1`) and stereo microphone PCM
(`hw:0,2`), with mixer state restored after every repetition. The kernel still
reported `wcd9335_slimbus_irq: overflow error on TX port 1, value 5` in 12/20
cycles; route functionality therefore does not close the codec regression.
Evidence: `artifacts/roadmap-7.3/audio-routes-20261110T081500Z/`.
The stage-aware validator then kept one UCM context for ten repetitions and
reproduced five new overflows. Every one occurred during `route-N-mic-transfer`;
no speaker/headphone stage reported a new fault, all captures delivered 48,000
frames, and the mixer state matched its pre-test snapshot. This narrows the
remaining hypothesis to the WCD9335 microphone/SLIMbus capture transfer while
leaving the codec fix unaccepted. Evidence:
`artifacts/roadmap-7.3/audio-validator-10-20261110T065155Z/`.
Source inspection of `sound/soc/codecs/wcd9335.c` shows that the interrupt
handler logs the TX port status, disables that port's overflow/underflow
interrupt bit, and clears the status. It does not reset the SLIMbus port or
rebuild the stream. The repeated `TX1 value 5` therefore cannot be treated as
a harmless logging artifact, but changing the handler without register-level
evidence could hide a transport fault. Keep the next experiment focused on
capturing the configured TX port, watermark and channel map around `hw_params`
and `trigger`; no codec patch is accepted yet. The source defines bit 0 as
overflow, bit 1 as underflow and bit 2 as port closed, so value `5` means
**overflow plus port closed**. It is not an overflow-only code.

The phase-split microphone collector (`tools/t825-audio-mic-phases.sh`) keeps
`start/read` and `drop` in one no-I/O interval and samples `close` separately.
Its first hardware run delivered all 48,000 frames but observed `TX1 value 5`
at `18488.860752` during the active read interval. The stream used 48 kHz
stereo, 960-frame periods and a 7,680-frame buffer; the mixer and boot ID were
restored unchanged. The report is
`artifacts/roadmap-7.3/audio-mic-phases-20261110T165846Z/`. Since the IRQ is
deferred and the collector does not read codec registers, this narrows timing
without proving whether SLIMbus or codec configuration caused the overflow.
7.3.x is not a long-term base and will reach EOL; plan a later supported-kernel move.

Follow-ups: compare the controlled GPU workload before/after 0204; track the
clock, Bluetooth and WCD9335 issues; obtain an outdoor GNSS fix; update
published binaries only after tablet testing.
`T825_MSS_DIAGNOSTIC=1`
works with direct `abuild`; with `pmbootstrap`, create the private
`.t825-enable-mss` sentinel because arbitrary host variables are sanitized.

The diagnostic RAM image must account for the lk2nd boot pool too. Embedding all
20 modem segments makes the initramfs about 61.5 MiB and cannot fit the 50 MiB
pool used by the T825 boot layout. `install/make-gnss-ram-boot.sh` therefore
mounts the signed `modem` partition read-only in initramfs and binds its
`image/` directory over the firmware path. The current private v17 image has a
22,969,562-byte initramfs and a calculated kernel budget of 27,328,512 bytes,
leaving 3,362,304 bytes below the 23,966,208-byte decompressed kernel. This
layout is still a RAM-only diagnostic: it does not write the modem partition or
the calibration images.

The first SM-T825 v7 boot reached the initramfs debug shell and exposed
`2080000.remoteproc`, but `pmos_continue_boot` dropped the USB gadget during
the rootfs hand-off before post-pivot logs could be collected. Diagnostic
images mask `t825-usb-gadget.service` and `gts3-firmware.service` through
transient `systemd.mask=` parameters; v32 additionally preserves the initramfs
DHCP lease, makes the USB helper idempotent and stages transient sshd wants.
The historical v32 hardware run still lost USB after release, so that image's
post-pivot SSH remained unverified. It did, however, return autonomously to
fastboot in 248 seconds.

The persistent tablet root does not contain the diagnostic `rmtfs` and
`tqftpserv` packages, so starting them only through systemd drop-ins in the
build root cannot work after a RAM boot. The v17 image includes those daemons,
`qrtr-lookup`, `qmicli` and their runtime libraries in initramfs. A hook starts
`tqftpserv`, prepares the private calibration, starts the MSS before waiting
for `qcom_rmtfs_mem1`, and then starts `rmtfs`; another cleanup hook moves
`/run` into the mounted root so the daemons, QRTR sockets and logs survive
`switch_root`. The v17 initramfs runs read-only QRTR/QMI probes before the
pivot and preserves their logs under `/run/t825-mssdiag`; its cmdline also
masks the persistent USB, firmware and duplicate QRTR service units for that
boot.

When packing a diagnostic image manually, set
`T825_MSS_DIAGNOSTIC_BOOT=1` alongside `CMDLINE_EXTRA`; the image packer then
adds both transient `systemd.mask=` parameters automatically.

Unattended recovery is now handled by the v31 static AArch64 supervisor,
not the earlier initramfs shell/systemd watchdog. The old v20–v30 archive checks
were insufficient: the timer could start after a blocked modem operation, the
shell could be killed by pmOS cleanup, and units packed in initramfs were not
available in the installed root after `switch_root`.

`install/prepare-t825-recovery.sh` installs the supervisor in the host build
root and inserts arming immediately after the `/run` tmpfs mount, before USB
module loading and stage 2. It is gated by `t825.mssdiag.hold`, expires after
240 seconds and retains file descriptors across root replacement. An optional
`/run/t825-recovery/lease` contains an absolute integer CLOCK_BOOTTIME expiry;
each accepted extension is at most 120 seconds ahead, with a one-hour overall
cap. A successful SSH marker does not disable recovery. The supervisor invokes
the kernel reboot syscall and schedules an independent SysRq fallback for a
stalled shutdown. This still requires a working scheduler/reset route.
Diagnostic hold images also set `panic=10`; this does not cover an arbitrary
kernel lockup.

The cleanup hook stages the USB helper and unit in `/run`, then moves that
tmpfs into the new root. The command line requests the USB unit and masks the
extlinux restore service. The runner never renames persistent boot files and
requires the tablet to be in fastboot initially. Returning to fastboot depends
on the existing boot selection; it is not selected by the supervisor itself.

On 2026-11-09/10, the tablet completed two minimal RAM-only recovery cycles in
36/37 seconds and two RAM-only `switch_root`/lease cycles in 70/68 seconds.
The v32-v34 handoff controls lost SSH after release but returned autonomously to
fastboot in 248/249 seconds; those historical failures are retained as
transport evidence. The later v59 read-only direct-root control reached the
installed Arch root, replacement PID 1 and SSH while retaining the original
supervisor, then returned to fastboot in 249 seconds. The MSS-enabled v60
control repeated that result and exposed the `04e8:6863` NCM gadget after the
pivot. The accepted direct-root path therefore passes the USB/systemd handoff;
the earlier UDC loss belongs to rejected image variants.
See
[the recovery audit](unattended-recovery-audit.md) for reports and limitations.

Build an acceptance variant with `T825_RECOVERY_ONLY=1` when invoking
`install/make-gnss-ram-boot.sh`: it skips modem hooks and disables the MSS DT
node. Validate the actual paired archive/image using
`T825_RAM_IMAGE=... T825_RAM_BUNDLE=... python3 tools/test-t825-gnss-ram-image.py`.
The validator checks header addresses, embedded archive identity, static ARM64
recovery, early arming, transient units and the lk2nd memory budget. Its
default bundle is the current v63 MSS/GNSS candidate
(`v63-mss-loc-retry-ro/t825-v63.img`); obsolete v31 images are historical and
must be passed explicitly when auditing their old evidence. The packer refuses
command lines longer than the legacy 511-byte field.

Launch an unattended cycle from an existing fastboot session with:

```sh
nohup setsid tools/t825-gnss-auto-cycle.sh PATH_TO_VALIDATED_IMAGE \
  > artifacts/roadmap-7.3/gnss-host.log 2>&1 < /dev/null &
printf '%s\n' "$!" > artifacts/roadmap-7.3/gnss-host.pid
```

The runner validates the bundle, pins the SM-T825 serial, takes a hardware-test
lock, records separate diagnostic/recovery results and observes the final
reset even after a collector failure. It stops further boots on failed recovery
or diagnostic failure. `tools/t825-gnss-ram-test.sh` delegates to this runner;
it no longer falls back to old images. Full-kernel/SoC recovery remains a
separate hardware-watchdog acceptance gate.
