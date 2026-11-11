# Linux 7.3 baseline on the SM-T825

Collected on **2026-11-08** from the tablet connected as `tabs3`. This is the
first runtime evidence for the installed package; repeat it after each change.

## Installation identity

- Model: `Samsung Galaxy Tab S3 LTE`.
- Running kernel: `7.3.1-t825 #2-postmarketos-qcom-msm8996`.
- Toolchain in the banner: Alpine clang/LLD `23.1.5`.
- DTB selected by extlinux: `msm8996-samsung-gts3llte.dtb`.
- Selected initramfs: `initramfs-t825` (22,762,179 bytes).
- Active DTB: 86,382 bytes.
- Selected gzip kernel: 10,526,949 bytes; the previous kernel remains available as `vmlinuz-t825.prev`.
- Hashes of the three active artifacts are in the private collection's `boot-hashes.txt`; they are not repeated here to avoid confusing a future collection with this one.
- Loaded modules belong to `/usr/lib/modules/7.3.1-t825`.
- Available suspend mode: `[s2idle]`.

The complete record was collected with
[`install/collect-kernel-baseline.sh`](../install/collect-kernel-baseline.sh)
in a private tablet directory. It includes hashes, configuration, Device Tree,
kernel logs and userspace versions, but does not copy firmware, calibration or partitions.

## Observed results

| Area | Result | Evidence |
|---|---|---|
| Boot | PASS | `uname`, model and cmdline confirm 7.3; extlinux points to the matching DTB and initramfs |
| Display/DRM | Partial PASS | `card0-DSI-1` is `connected`; Hyprland stayed active after the GPU test |
| GPU/reset | Partial PASS | `gpuhang` produced `GL_GUILTY_CONTEXT_RESET`; the kernel identified `offending task: gpuhang`; Hyprland and `qs` continued running |
| Wi-Fi | Partial PASS | `wlp1s0` is `UP` with an IPv4 address; the log shows ath10k using `board.bin` because `board-2.bin` is absent |
| Bluetooth | PASS with noise | `hci0` starts, downloads rampatch/NVM and operates; two `Frame reassembly failed (-84)` messages occurred during initialization |
| Sensors | Enumeration PASS | SLPI starts and accel, gyro, magnetometer and light appear through `qcom-smgr` |
| Audio | Partial PASS | Twenty 1-second stereo microphone captures at 48 kHz delivered 48,000 frames without clipping; speakers and headset were not measured |
| Cameras/Venus | Partial PASS | Three 90-frame captures per camera at 1280×720; 30.00–30.16 fps with no gaps; quality and codecs were not measured |
| Suspend/resume | PASS | Ten 10-second s2idle cycles with RTC, ICMP traffic, Wi-Fi, Bluetooth, PipeWire and sensors returned; `dmesg` ring continuity was checked |
| GNSS/LTE | Installation: NOT IMPLEMENTED; diagnostic RAM: GNSS transport PASS | The installed kernel keeps `CONFIG_GNSS`/`CONFIG_WWAN` disabled and MSS disabled; a separate v17 RAM image enabled MSS/QRTR/QMI without touching partitions |

## Reproduced kernel warnings

The boot recorded:

- `pclk0_clk_src: rcg didn't update its configuration` twice;
- `Bluetooth: hci0: Frame reassembly failed (-84)` twice;
- `bam-dma-engine 644000.dma-controller: probe ... error -22`;
- corrected dependency cycles between CAMSS and both cameras;
- `psci` without PC/OSI mode support;
- ath10k fallback because `board-2.bin` is absent.

The final four-check deltas contained no `Opcode 0x0c03 failed: -110`,
`wcd9335 ... overflow` or `ME master split`. The WCD9335 overflow was reproduced
in earlier runs and remains an audio investigation item; its absence in one capture
does not prove it is fixed.

## Later controlled validation

Complete results are under `artifacts/roadmap-7.3/validation-final/`. The validator
stores metrics and logs, not image or audio samples. It confirmed:

- front and rear cameras: three repetitions of 90 frames, sequences 0–89 and 30.00–30.16 fps;
- default microphone: twenty repetitions with 48,000 stereo frames and no clipping;
- GPU: three synthetic resets with `offending task: gpuhang`, recovery and the same Hyprland process;
- suspend: three historical 20-second RTC/s2idle cycles, Wi-Fi ICMP return, Bluetooth, PipeWire and all four sensors; the final ten-cycle target is recorded below.

## Additional validation on 2026-11-08

An initial sequence of ten 10-second s2idle suspends found old
`wcd9335_slimbus_irq: overflow` lines after the `dmesg` ring rotated. The validator
was corrected to require continuous overlap and save the complete log when this
occurs. The repeat passed all ten cycles with RTC, ICMP on `wlp1s0`, Bluetooth,
PipeWire and sensors; results are in `artifacts/roadmap-7.3/suspend-10-fixed/`.

A dedicated 20-capture audio run delivered 48,000 stereo frames per capture,
without clipping or a new kernel overflow. This alone does not establish a resume
dependency. Later single-context UCM route validation reproduced five new overflows
in ten cycles, all during microphone transfer, without a suspend step. PCM delivery
still completed. Reports: `artifacts/roadmap-7.3/audio-20/results.json` and
`artifacts/roadmap-7.3/audio-validator-10-20261110T065155Z/`.

Log-filter regression cases are covered by `tools/test-t825-validate.py`; they verify
new failures, equal timestamps, missing and duplicate anchors, and ambiguous rotation
without accessing hardware.

After the diagnostic-cycle reboot, the installed system passed twenty audio captures,
3×90 frames per camera and ten s2idle cycles with RTC, ICMP/Wi-Fi, Bluetooth, PipeWire
and sensors. Metrics and hashes are in `artifacts/roadmap-7.3/audio-20-postreboot-20261109/`,
`cameras-postreboot-20261109/` and `suspend-10-postreboot-20261109/`.

## MSS/GNSS RAM evidence — 2026-11-09

The `t825-gnss-ram-boot-v17-hold.img` image was accepted by `fastboot boot` without
writing partitions. Diagnostic kernel `7.3.1-t825-mssdiag` put `2080000.remoteproc`
in `running`, created `/dev/qcom_rmtfs_mem1`, exposed QRTR Remote File System/TFTP
and Location (PDS v2), and QMI LOC returned `msb`. `rmtfs` logged no errors and
`tqftpserv` completed `server_check.txt`. `loc-start` and `loc-stop` passed; no
position or satellite information arrived in 10-second or 90-second windows. This
proves GNSS transport, not an antenna fix. The private report is
`artifacts/roadmap-7.3/gnss-ram-20261108/hardware-v17-20261109T173200Z/`.

## Next measurements

1. Reproduce any new overflow after suspend with audio/SLIMbus tracing and compare codec state before and after resume.
2. Include display, headset and a local graphical session in the next release matrix; the ten basic cycles already passed.
3. Repeat `gpuhang` in a diagnostic build with tracing enabled only if needed to distinguish kernel reset from Mesa behavior.
4. Investigate the two reproduced warnings before considering backports.
