# Linux 7.3 roadmap for the Galaxy Tab S3 (SM-T825)

Updated: 2026-11-11 UTC. The tablet already runs Linux 7.3.1. The installed baseline
is `7.3.1-t825 #2-postmarketos-qcom-msm8996` (r1). Normal r2 kernel and r11
device APKs exist. The tablet currently uses the r11 payload (r9 helper and
eight-second service delay); Bluetooth acceptance remains open after a later
software reboot reproduced `-110`. Experimental r12 payloads were rejected.
Diagnostic images use `7.3.1-t825-mssdiag` or `7.3.1-t825-audiodiag`
and `fastboot boot` only.

Current transport state after the audio transaction diagnostic (2026-11-11 UTC):
installed r1 boots normally and SSH responds. Boot ID is
`3d22d218-b993-4a87-99ab-26651917a4ff`,
`extlinux.conf` retains SHA-256
`03285dfe1f2016a4cf967fe22f9c68d8663801a61e1c07050eff6fa36ed2a397`,
and no temporary fastboot filename remains. The audio diagnostic reproduced
overflow; autonomous fastboot recovery and Arch restoration both passed.
Evidence:
`artifacts/roadmap-7.3/authorized-audio-ngd-removal-20261111T120110Z/`.
The previous Bluetooth attempt recovered after a Reset `-110`; its acceptance
remains open.
The legacy Bluetooth reboot runner is now disabled because its polling/fallback
did not establish independent recovery; use the validated RAM orchestration
for future diagnostic extensions. The authorized extlinux controller remains
available, subject to its validated image and recovery gates.

The user confirms normal restarts boot Arch directly. Do not assume the
supervisor's normal reset will return to fastboot under this boot-selection
state; prior fastboot recovery results were specific to their earlier state.
The authorized controller now establishes fastboot entry through a guarded
extlinux rename, keeps that destination during RAM diagnostics, and restores
normal Arch selection afterwards. This persistent-file exception is explicitly
authorized; it does not establish a working reboot-reason-only mechanism.

Accepted normal-r2 RAM cycle (2026-11-11 00:22 UTC): normal r2 booted from
RAM with exact `#3` identity, direct PID 1, both Btrfs members read-only and the
original supervisor. Its automatic reset returned to installed r1, boot ID
`40c0ce08-7afd-4a29-9ee5-1c8331f47a91`, observed after 275.535 seconds.
`readonly-r2-cycle-20261111T002227Z/cycle/result.json` records
`PASS_HANDOFF_AND_RESET`, destination `linux`, and no unattended next RAM cycle.

The latest audio diagnostic cycle entered through the authorized fastboot
controller, reproduced the WCD9335 TX1 overflow on capture 1/3, reset to
fastboot under the independent supervisor and returned to Arch after verified
extlinux restoration. This is a controlled fault reproduction, not a fix.

## First priority: unattended recovery

Repeated manual resets are a test-infrastructure defect. Prove recovery before
running another experiment that can lose USB, SSH, or modem responsiveness.

- [x] Audit the earlier v20–v30 recovery implementations. Their archive checks
  did not prove recovery: the shell timer started after modem startup, pmOS
  kills `sh` processes during cleanup, and initramfs systemd units did not
  automatically become available after `switch_root`.
- [x] Build a static AArch64 supervisor, independent of shells, systemd and
  pathnames in the discarded root. It uses `CLOCK_BOOTTIME`, retained directory
  descriptors, a bounded deadline and optional bounded host leases.
- [x] Test the real ARM64 binary under QEMU: expiry, invalid input, rejected
  oversized leases, and a lease/log directory moved while the process runs.
- [x] Prove two RAM-only automatic resets on the tablet, with no modem or root
  partition mounted. The same detached host process booted both images and
  observed fastboot return in **36 s and 37 s**.
- [x] Prove two further RAM-only cycles across an actual `switch_root`, deletion
  of the old supervisor binary and pmOS-style shell cleanup. A lease issued
  only by the new PID 1 extended recovery; fastboot returned in **70 s and 68 s**.
- [x] Integrate recovery arming immediately after `/run` is mounted, before
  `libcomposite` loading, udev, the debug shell, modem startup and QRTR probes.
  Diagnostic images also set `panic=10`; panic recovery still depends on a
  working kernel reset path.
- [x] Stage the transient USB helper/unit in `/run` for the installed system.
  Mask extlinux restoration through the diagnostic kernel command line.
  Remove the obsolete post-pivot shell watchdog and its misleading success
  marker. No boot-file rename is used by the new test orchestrator.
- [x] Observe automatic reset of the full pmOS image with MSS disabled after
  releasing the initial debug shell: fastboot returned in **248 s**, despite
  post-pivot SSH failure. Report: `system-hardware-20261109T224732Z/` under
  `artifacts/roadmap-7.3/recovery-v31/`.
- [x] Repair USB and verify post-pivot SSH to complete installed-system handoff
  acceptance. Record transport failure separately from reset recovery; do not
  mark a missing SSH session as PASS.
- [x] Build v32 handoff candidate `v32-preserve-dhcp-ssh/`: retain the initramfs
  `unudhcpd` lease across `switch_root`, make the USB helper idempotent when an
  active NCM/RNDIS function already exists, and enable `sshd.service` through
  `/run` only for the transient diagnostic boot. This is a hypothesis until a
  detached hardware cycle records post-pivot SSH and autonomous recovery.
- [x] Run one detached v32 hardware cycle. The initial debug shell and USB
  enumeration passed; after release, USB disappeared before SSH (transport
  failure), while the independent supervisor returned the tablet to fastboot
  in **248 s**. Report: `artifacts/roadmap-7.3/recovery-v31/v32-preserve-dhcp-ssh-20261110T000612Z/`.
- [x] With explicit user authorization, add a guarded Arch-to-lk2nd-fastboot
  controller. It snapshots and hashes `extlinux.conf`, enters fastboot through
  SSH, uses `fastboot boot` only, restores the original file from the RAM
  initramfs, and verifies the restored hash and a new Arch boot ID. The first
  run exposed the telnet line-length limit and recovered through the supervisor;
  the shortened payload then passed unattended end to end:
  `artifacts/roadmap-7.3/authorized-fastboot-roundtrip-20261111T101000Z/`.
- [x] Investigate the transient post-release UDC loss. The v32-v34 controls
  reproduced a `04e8:6863` disconnect before post-pivot SSH, including with
  network managers and the persistent USB helper masked. The later v59/v60
  read-only direct-init path retained the NCM gadget through the root handoff;
  v60 exposed `04e8:6863`, passed post-pivot SSH and verified the original
  supervisor before autonomous fastboot recovery. The earlier loss therefore
  belongs to the rejected handoff variants; the accepted direct-root path has
  a passing UDC/SSH control. Reports:
  `artifacts/roadmap-7.3/recovery-v31/v34-inherited-only-20261110T002157Z/`
  and `artifacts/roadmap-7.3/gnss-ram-20261108/auto-v60-20261110T044342Z/`.
- [x] Test v33 `v33-mask-network/`, which additionally masks persistent
  `NetworkManager.service`, `systemd-networkd.service` and
  `unudhcpd@usb0.service` for the RAM boot. It still lost post-pivot SSH and
  returned autonomously to fastboot in **248 s**. Report:
  `artifacts/roadmap-7.3/recovery-v31/v33-mask-network-20261110T001555Z/`.
- [x] Test v34 with the root USB helper disabled, leaving only the inherited
  initramfs gadget. It also lost post-pivot SSH and returned to fastboot in
  **249 s**, so the failure is not caused solely by the persistent helper.
  Report: `artifacts/roadmap-7.3/recovery-v31/v34-inherited-only-20261110T002157Z/`.
- [x] Trace the handoff through v38–v40. The persistent root was not reached:
  `handoff-stage` remained `post-debug`, and the debug-shell PID 1 stayed
  `/init_2nd.sh`. These runs also confirmed that the root UUID/options must be
  preserved when constructing a RAM image.
- [x] Run v41 with the real root UUID and Btrfs `subvol=/@` options, direct
  transient init and NCM preservation. It still returned autonomously to
  fastboot in **249 s**; post-pivot SSH was not reached. Report:
  `artifacts/roadmap-7.3/recovery-v31/v41-direct-real-root-20261110T011555Z/`.
- [x] Run v42 with the same verified root parameters and a persistent telnet
  trace during `pmos_continue_boot`. It still did not expose post-pivot SSH,
  and autonomous recovery returned to fastboot in **250 s**. Report:
  `artifacts/roadmap-7.3/recovery-v31/v42-direct-trace-20261110T012516Z/`.
- [x] Correct the direct-init release path and run v44. The tablet still
  returned to fastboot automatically, but the host saw a NCM disconnect after
  a transmit watchdog event and no post-pivot SSH; the run ended in **89 s**
  because recovery fired before the normal 240 s deadline. Report:
  `artifacts/roadmap-7.3/recovery-v31/v44-direct-pkill-20261110T014542Z/`.
- [x] Harden the image generator so a stale direct-init patch cannot insert
  `exit 0` after the debug shell and skip `mount_root`/`switch_root`. Validate
  the existing v45 image and run one detached cycle: post-pivot SSH still
  failed, while the supervisor returned the tablet to fastboot in **249 s**.
  Report: `artifacts/roadmap-7.3/gnss-ram-20261108/auto-v45-20261110T020821Z/`.
- [x] Add complete bounded telnet collection and per-hook TCP stage reports.
  v54 reached every cleanup hook and `pre-switch-root`. The host firewall
  requires a temporary rule restricted to the tablet/host USB IPs and port
  2324; the collector removes it on exit.
- [x] Correct the direct diagnostic init for the installed Arch root: resolve
  its sshd path, mount pseudo filesystems, create `/run/sshd`, and stage only
  the host public key into transient `/run`. Acceptance still requires the
  original supervisor, actual replacement PID 1, a read-only root and SSH.
- [x] Audit filesystem side effects: v50 revealed the upstream initramfs
  resizing Btrfs. v54–v57 initially mounted the root writable before remounting
  read-only. These runs do not prove absence of persistent filesystem writes.
  Disable deletion/resize calls and reject those older images in validation.
- [x] Snapshot the runner and collectors before each boot and hash the copies.
  v57's collector failed after its live source was edited, while automatic
  recovery still returned to fastboot in **250 s**. The script failure must
  remain a diagnostic FAIL, separately from recovery PASS.
- [x] Accept a strictly read-only direct-root transition. The v59 candidate
  verifies the read-only flag on both Btrfs member devices before mount, uses
  Btrfs `ro,rescue=nologreplay` (the 7.3 kernel rejects the older
  `ro,nologreplay` spelling), and skips the installed boot volume. One detached
  cycle reached the installed Arch root, verified the replacement PID 1,
  SSH and the original supervisor, then returned to fastboot automatically in
  **249 s**. Report:
  `artifacts/roadmap-7.3/gnss-ram-20261108/auto-v59-20261110T042431Z/`.
- [x] Repeat the accepted read-only handoff with MSS/GNSS enabled. v60 reached
  the installed Arch root with the MSS remoteproc running, QRTR/QMI services,
  read-only Btrfs, verified PID 1, SSH and the original supervisor, then
  returned to fastboot automatically in **249 s**. Report:
  `artifacts/roadmap-7.3/gnss-ram-20261108/auto-v60-20261110T044342Z/`.
- [x] Resolve the v61 recovery failure with a deterministic MSS inspection
  hold. The v61 transient remains recorded as a failed transport/recovery
  observation, while v62 using the same MSS image held the modem services,
  collected the early QRTR evidence and returned to fastboot automatically.
  v61 report:
  `artifacts/roadmap-7.3/gnss-ram-20261108/auto-v61-20261110T045054Z/`.
- [x] Repeat MSS acceptance with an explicit initramfs inspection hold (v62).
  QRTR still exposed Location PDS v2, rmtfs and TFTP before the pivot; the
  position/SV calls reported no node at the early `qrtr://0` endpoint, while
  the post-pivot service path remained valid. PID 1, read-only root, SSH,
  supervisor and automatic fastboot return passed in **249 s**. Report:
  `artifacts/roadmap-7.3/gnss-ram-20261108/auto-v62-20261110T050629Z/`.
- [ ] Validate a tablet hardware watchdog for complete kernel/SoC stalls. The
  current DTB has no watchdog node even though `CONFIG_QCOM_WDT=y`. The stock
  DTB contains `qcom,msm-watchdog` at `0x09830000`; binding, clock, ownership,
  register layout and reset destination must be checked before enabling it.
  Static audit: `artifacts/roadmap-7.3/watchdog-audit.json`. It confirms the
  stock `qcom,msm-watchdog` node is absent from the Linux 7.3 match table and
  lacks a binding clock; the tested PS_HOLD reset remains the only accepted
  automatic reset route.
  The [PM8994 investigation](docs/pm8994-watchdog-investigation.md) identifies
  a separate PMIC candidate with matching downstream control offsets. Its
  driver is disabled in the installed kernel. Register access, timeout/pet
  semantics, expiry and reset destination remain unvalidated. Bounded takeover
  is essential: the current watchdog core configuration can feed an inherited
  timer indefinitely before userspace opens it. Evidence:
  `artifacts/roadmap-7.3/pm8994-watchdog-source-20261110T230854Z/`.
  A read-only live PON snapshot shows a generation-1 PON, the PMIC watchdog
  disabled (`0x857=0x00`), bootloader timers `0x0f`/`0x03`, reset type `0x08`
  and last power-off reason PS_HOLD (`0x80c=0x02`). The decoder can attribute a
  later PMIC watchdog power-off; no expiry has been tested:
  `artifacts/roadmap-7.3/pm8994-pon-readonly-20261111T151136Z/`.
- [x] Separate reset action from boot-mode selection in a read-only audit.
  Live qcom-pon exposes `bootloader=0x02`, `recovery=0x01` and `normal=0x14`;
  PS_HOLD performs the reset. The documented lk2nd base reads PON `0x02` for
  fastboot, but Samsung has already intercepted that reason into Download.
  Unknown Linux mode strings do not define an alternate route. Report:
  `artifacts/roadmap-7.3/reboot-route-source-audit-20261110T180230Z/`.
- [x] Validate admission and cleanup for a nonpersistent route from installed
  Linux to a RAM kernel. Native aarch64 `kexec-tools` 2.0.32 loaded the
  read-only candidate (`loaded 0 -> 1`) and unloaded it (`1 -> 0`) without
  `kexec -e`; the boot ID and running kernel were unchanged. The probe found
  four load segments. Evidence and the reproducible bounded runner:
  `artifacts/roadmap-7.3/kexec-route-audit-20261110/` and
  `tools/t825-kexec-load-audit.sh`.
- [ ] Execute and validate a nonpersistent handoff from installed Linux to a
  RAM kernel. This remains gated on independent recovery, final reset
  destination evidence and a reviewed direct-root transition; loading alone
  is not a boot or compatibility result. The first guarded execution attempt
  loaded the candidate (`loaded=0 -> 1`) and invoked `kexec -e`, but exposed no
  SSH, ADB or fastboot within 360 seconds; USB remained `04e8:6863` without
  carrier and the supervisor was unobserved. It is recorded as a handoff
  failure and requires a pre-supervisor recovery route before another attempt.
  Reconstruct the installed dirty lk2nd additions before claiming source
  equivalence. Report:
  `artifacts/roadmap-7.3/kexec-cycle-20261110T191300Z/`.
  A follow-up host check still found no fastboot, ADB or SSH; only the Samsung
  `04e8:6863` NCM gadget remained, with `enp120s0u1` at carrier `0`. Bringing
  the interface up and assigning `172.16.42.2/24` did not restore a route. The
  permitted bounded USB reset does not apply to this product, so manual
  fastboot restoration is required before another test. Evidence:
  `artifacts/roadmap-7.3/transport-check-20261110T193821Z/`. A bounded
  unbind/rebind of the host `cdc_ncm` interfaces also left `enp120s0u1` at
  `NO-CARRIER`/carrier `0`; rebinding the host driver did not recover transport;
  evidence: `artifacts/roadmap-7.3/transport-check-20261110T195355Z/`.
  Manual recovery has since restored installed r1 and SSH. Read-only inspection
  still exposes no watchdog; pstore has no candidate-specific execution marker.
  Source review confirms that device shutdown, secondary-CPU shutdown and
  relocation precede the new initramfs supervisor. Another kexec execution
  remains gated on independent recovery covering that interval, not merely on
  restoring SSH or making the candidate smaller. Review and four host tests:
  `artifacts/roadmap-7.3/kexec-preentry-review-20261110T225843Z/`.
- [x] Add a minimal pre-supervisor kexec proof candidate. It contains only the
  static recovery supervisor, BusyBox and a tmpfs init. Fastboot return alone
  cannot distinguish its execution from a panic or old-kernel reset; the runner
  now reports `RECOVERY_PASS_PROOF_UNOBSERVED` for that case. The builder and
  offline validation are
  `install/make-kexec-proof-bundle.sh` and
  `tools/test-t825-kexec-proof-bundle.py`; the reproducible candidate is
  `artifacts/roadmap-7.3/kexec-proof-candidate-20261110b/`. This remains
  untested on hardware.
  Both `tools/t825-kexec-proof-cycle.sh` and `tools/t825-kexec-cycle.sh` now
  exit with `BLOCKED_PREENTRY_RECOVERY` before device access; there is no
  environment override. Their experimental bodies are retained for review.
  Before re-enabling them, validate independent recovery and repair the USB
  teardown followed by a second SSH dispatch, which can destroy its own route.
  Five host tests and shell checks pass in the PM8994 report above; these
  validate containment and classification, not a hardware handoff.
  Offline regression evidence for the builder, kexec runner guards, trusted
  initramfs preparation and read-only image is archived at
  `artifacts/roadmap-7.3/offline-checks-20261110T195045Z/`.

Evidence and limitations: [unattended recovery audit](docs/unattended-recovery-audit.md).
Private reports:

- `artifacts/roadmap-7.3/recovery-v31/hardware-20261109T223727Z/`
- `artifacts/roadmap-7.3/recovery-v31/handoff-hardware-20261109T224237Z/`

The proven software supervisor covers failures while the scheduler and reset
route still work. It cannot guarantee recovery from an earlier boot hang or a
complete SoC lockup. Fastboot return was observed with the tablet's existing
boot selection; the supervisor does not independently select fastboot.

## Working rules

1. Preserve the working kernel, DTB, initramfs and matching modules, plus a known
   recovery image outside the single `.prev` slot.
2. Follow [AGENTS.md](AGENTS.md): detached host orchestration, bounded waits,
   timestamped logs, a retained PID and automatic consumption of USB reconnects.
3. Use `fastboot boot`; never flash or modify EFS, modemst1/2, fsg, fsc, the
   bootloader or persistent boot files to automate tests.
4. Keep firmware, calibration, original dumps and identifiers private. Review
   logs before publication. Do not install `msm-cros-efs-loader` unchanged;
   its boot0/EFS assumptions do not match this diagnostic policy.
5. Record build identity/hashes, steps, expected/observed behavior, failure
   frequency and logs. Use PASS, FAIL, UNTESTED or BLOCKED precisely.
6. Diagnose one subsystem/hypothesis at a time. A warning without demonstrated
   impact is an investigation item, not proof of a kernel regression.
7. Sync source changes into the prepared build root before rebuilding. Inspect
   the actual resulting image, including its embedded archive and command line.

## Phase 0: identify and preserve the baseline

- [x] Collect the actual version, active DT, modules, boot parameters and logs
  with `install/collect-kernel-baseline.sh` and `tools/t825-check.sh`.
- [x] Confirm the production DT keeps MSS disabled; SLPI and ADSP are active.
- [x] Record the baseline and initial kernel/userspace/firmware distinctions in
  [baseline-7.3.md](docs/baseline-7.3.md) and
  [regression-matrix-7.3.md](docs/regression-matrix-7.3.md).
- [x] Record package revisions, Mesa, compositor, browser and firmware identities
  for each new comparison. The baseline records Mesa 26.2.6, Hyprland 0.57.1,
  PipeWire 1.6.10, WirePlumber 0.5.18, BlueZ 5.87 and libcamera 0.7.2;
  diagnostic/normal kernel APK hashes are recorded below.

## Phase 1: compatibility and regression matrix

The following results are bounded observations, not coverage of every route or
workload. Detailed hardware results remain in [docs/hardware.md](docs/hardware.md).

| Area | Observed evidence | Remaining acceptance work |
|---|---|---|
| Boot/display/input | Installed 7.3, LTE DT, touch, sensors and display enumerated | Five cold boots; rotation, S-Pen and keys in both orientations |
| Cameras | Three repetitions of 90 frames per camera, roughly 30 fps, no sequence gaps | Image quality and longer capture workloads |
| Microphone | Twenty 1 s stereo captures, 48,000 frames each, without clipping | Individual microphones, acoustic quality and route changes |
| Speakers/headset | Basic graphical-session audio works | All four speakers; CTIA insertion/removal and 20 route cycles |
| Suspend | Ten s2idle/RTC cycles with Wi-Fi, Bluetooth, PipeWire and sensors passed | Power measurements and repeated cold-boot comparisons |
| Bluetooth | r11: historical 20/20 followed by 4/5 in a later software reboot control; r10 + 20-second delay also reproduced `-110` | Diagnose the HCI reset failure, then pass 20 reboots and repeat 10 suspend cycles; cold boots are a separate gate |
| GPU | Three synthetic hangs recovered; Hyprland kept the same process | Controlled r1/r2 comparison and real browser workload |
| GNSS | MSS/QRTR/QMI LOC transport and start/stop demonstrated in RAM | Satellite reports, antenna acquisition and sustained position fix |
| LTE/SIM | Production MSS remains disabled | QMI enumeration, SIM, registration, data path and reconnect |
| Power/USB/microSD | Baseline enumeration and selected checks | Idle/suspend consumption; temporary-file hashes and stable USB handoff |

Repeat tests three times unless a specific count is given. Preserve timestamped
kernel/service logs. An SSH shell without the graphical user's PipeWire context
can report audio UNAVAILABLE; that alone does not establish an audio regression.
The suspend validator's old `dmesg` ring-wrap false positive was fixed and the
10-cycle run was repeated successfully.

Post-reboot evidence from 2026-11-09:
`audio-20-postreboot-20261109/`, `cameras-postreboot-20261109/`, and
`suspend-10-postreboot-20261109/` under `artifacts/roadmap-7.3/`.

## Phase 2: Bluetooth, audio and power

### Bluetooth

- [x] Reproduce `Opcode 0x0c03 failed: -110`. A sysfs `hci0` entry was present
  while `bluetoothctl` reported no controller; presence alone is insufficient.
- [x] Update `gts3-bdaddr` to require three consecutive controller/address
  probes, avoid reconfiguring an already ready controller and rebind QCA after
  an asynchronous reset failure. The r9 service restarts on transient failure.
- [x] Exercise the helper idempotently from `/tmp` and build the r9 device APK.
- [x] Validate deployment and unattended recovery of the corrected r9 package.
  The package contents were installed with a root-only backup of the previous
  helper and service, then exercised by a detached host runner that accepts
  either direct extlinux reboot or a fastboot return followed by `fastboot boot`.
  No manual reboot was required; the final cycle returned to the running system.
  Report: `artifacts/roadmap-7.3/bluetooth-auto-20261110T060000Z/`.
- [ ] Accept the corrected package's 20-boot test. The r9 run produced **15
  PASS and 5 FAULT** cycles. Faults were transient controller loss with
  `Frame reassembly failed (-84)` and/or `Opcode 0x0c03 failed: -110`; the
  service recovered the controller on later boots, but the failure rate is not
  acceptable for closure. A separate detached **10-cycle s2idle/RTC** run
  passed Bluetooth presence, Wi-Fi ICMP return, PipeWire and sensors after
  every suspend; report:
  `artifacts/roadmap-7.3/suspend-bt-10-20261110T065730Z/`.
  The r11 service-order candidate adds an 8-second pre-start delay and passed
  **20/20** detached boots with the EFS address present and no `-110` timeout;
  the known initial `-84` frame warning remained. The tested combination is the
  r9 helper plus the delayed service; its rebuilt r11 APK payload hashes match
  that control. A separate r10-helper + delay run failed 2/8 and was rejected.
  A later r11 software reboot control reproduced `-110` in **1/5** cycles:
  `artifacts/roadmap-7.3/cold-boot-5-20261110T100443Z/` (despite the historical
  directory name, this did not power-cycle the tablet). The earlier 20/20
  result is therefore insufficient for closure. The tablet was switched to
  the tested r11 payload without a reboot and
  verified running with the EFS address. Report and APK hashes:
  `artifacts/roadmap-7.3/bluetooth-delay-candidate-20261110T084940Z/`.
  The target root filesystem is Arch Linux (`pacman`), so it has no `apk`
  transaction database or executable. A package-manager install of the pmOS
  APK is therefore blocked on this image; the live files remain hash-verified
  against the r11 payload and the package archive is retained for the matching
  pmOS image. The r11 helper/service have been restored and verified after the
  rejected r12 experiments; see [Bluetooth investigation](docs/bluetooth-7.3.md).
  A subsequent detached 20-boot attempt stopped after cycle 1 because the
  current restored control reproduced a second-setup `Opcode 0x0c03 failed:
  -110` at 25.284307 s. The tablet returned to Arch automatically, Bluetooth
  recovered, and the runner retained the final healthy controller without
  manual intervention. This confirms controlled failure and leaves acceptance
  open. Report:
  `artifacts/roadmap-7.3/bluetooth-20boot-20261111T124000Z/`.
  The follow-up audit counted four setup completions and located the timeout
  2.003018 seconds after the second completion, with unchanged payload hashes.
  Recovery on that direct reboot succeeded, but the runner armed no independent
  supervisor and its configured direct-init fallback cannot run systemd/BlueZ
  acceptance. The entry point is now blocked before device access; no further
  installed-boot series is permitted until recovery and workload are integrated.
  Audit and containment tests:
  `artifacts/roadmap-7.3/qca-address-source-check-20261111T111509Z/`.
- [x] Reduce the boot fault rate after separating HCI readiness from BlueZ
  daemon readiness. The helper candidate now accepts a configured `btmgmt`
  controller while `bluetoothd` is stopped, avoiding an unnecessary
  `public-addr` write and UART rebind; the bounded live test produced no QCA
  setup delta and no reboot. Report:
  `artifacts/roadmap-7.3/bluetooth-helper-candidate-20261110T071635Z/`.
  A detached 20-cycle run with this r10 candidate recorded **18 PASS and 2
  FAULT**; both faults still showed a second QCA setup and `-110`, so the
  reduction is useful but insufficient by itself. The subsequent r11 service
  ordering candidate removed the observed `-110` faults in 20/20 boots. The r9
  helper was restored and verified after the run. Reports:
  `artifacts/roadmap-7.3/bluetooth-r10-auto-20261110T072338Z/`.
  `artifacts/roadmap-7.3/bluetooth-delay-candidate-20261110T084940Z/`.
- [ ] Validate the QCA NVM address hypothesis. A private candidate copied the
  EFS BDADDR into the placeholder bytes of `nvm_00440302.bin`; the next boot
  still showed `Frame reassembly failed (-84)`, a second QCA setup and
  `Opcode 0x0c03 failed: -110`. The candidate was removed immediately after
  collection; the controller and system remained healthy. The result is
  inconclusive because other reset failures remained present, so the
  modified blob remains rejected. Evidence and the removed binary are retained in
  `artifacts/roadmap-7.3/nvm-candidate-20261110T081749Z/`. This experiment is
  inconclusive and does not authorize shipping a modified firmware blob.
  A format audit now proves the edit targeted QCA NVM tag 2's six-byte BDADDR
  payload at offset `0x10`, used the correct little-endian EFS address, and
  changed no other bytes. The candidate nevertheless retained the framing
  error, second setup and HCI Reset timeout, so the address hypothesis remains
  causally unproven and no firmware change is accepted. Evidence and parser:
  `artifacts/roadmap-7.3/qca-nvm-format-audit-20261111T130000Z/` and
  `tools/analyze-t825-qca-nvm.py`.
  The corrected parser and an executable test of the actual
  `qca_check_bdaddr()` source establish a narrower conclusion: when no public
  address is supplied and the controller reads back the loaded NVM tag, editing
  that tag also changes the comparison value, so property-based provisioning
  is still requested. The historical candidate lacks initial readback evidence;
  its exact runtime branch and the Reset cause remain unproven. Preserve the
  stock firmware and investigate early address-property provisioning separately.
  Source execution, format tests and input hashes:
  `artifacts/roadmap-7.3/qca-address-source-check-20261111T111509Z/`.
- [x] Capture a read-only runtime snapshot of the restored r11 control. Four
  QCA setup sequences were visible at 12.380118, 23.199581, 2058.268627 and
  2060.474058 seconds, each followed by `Frame reassembly failed (-84)`; no
  HCI Reset `-110` occurred in this boot. The first pair belongs to initial
  boot and delayed address-service sequencing. The later pair was caused by
  the deliberate Bluetooth trace rebind: the journal shows Bluetooth Support
  stopping and endpoints being unregistered before the two setups. The
  controller was healthy and address-matched at collection. Reports:
  `artifacts/roadmap-7.3/bluetooth-runtime-audit-20261110b/` and
  `artifacts/roadmap-7.3/bluetooth-runtime-followup-20261110T184556Z/`.
- [ ] Compare power, BT_EN, UART and firmware sequencing with the Samsung driver
  if the reset timeout remains reproducible.
  The pinned downstream and live read-only comparison is now recorded in
  `artifacts/roadmap-7.3/bluetooth-downstream-20261110T232224Z/` and
  [Bluetooth investigation](docs/bluetooth-7.3.md). It identifies missing
  explicit ROME supply ownership, different BT_EN low-time/baud sequencing,
  and a historical Reset timeout 2.033288 s after vendor setup completed.
  Both reviewed successful btsnoop controls show a roughly 551 ms fourth Reset
  after address provisioning. The next measurement must retain IBS wake/ack
  state during the first failed post-setup Reset; end-of-test counters are
  insufficient. Electrical timing and exact Samsung userspace remain unverified,
  so no speculative reset, regulator or firmware change is accepted.
  A bounded IBS timeline collector is now integrated. One no-reboot rebind
  recorded 105 samples across distinct UART bindings and restored the controller
  automatically with unchanged boot/payload and no new Reset timeout:
  `artifacts/roadmap-7.3/bluetooth-ibs-timeline-20261110T232923Z/`.
  The final sampler's boolean-vote parsing was verified separately read-only;
  the frozen run retains its explicit vote-format errors. This adds diagnostic
  coverage, not repeated-boot acceptance.
  Source inspection shows that an invalid firmware address requires management
  `Set Public Address` before primary-controller enumeration; waiting for a
  primary controller first was rejected. A second QCA setup can follow from
  `HCI_QUIRK_NON_PERSISTENT_SETUP` and does not establish a userspace race.
  Do not promote a fixed service delay as a demonstrated reset fix.
  The bounded trace collector now records the complete HCI sequence and IBS
  snapshots while an independent timer restores the normal service. Its
  overlap-verified kernel delta rejects missing or ambiguous continuity, so a
  rotating dmesg buffer cannot turn an unproven result into PASS. One control
  rebind passed with no new timeout:
  `artifacts/roadmap-7.3/bluetooth-hci-trace-20261110T112651Z/`. Repeat the
  same frozen-payload trace until the first timeout, then compare its address
  writes, reset completion and IBS counters before changing the kernel.
  A five-cycle series completed with 5/5 restoration passes and no new HCI
  Reset timeout; the IBS states returned to sleep on every cycle. This is
  useful control evidence, but does not close the software-reboot gate:
  `artifacts/roadmap-7.3/bluetooth-rebind-series-20261110T112943Z/`.
  A fresh corrected trace then detected the expected unconfigured controller,
  completed the helper and restored the primary controller in one bounded
  cycle. It produced two `-84` frame warnings and no new `-110` timeout; the
  independent recovery timer was cancelled only after restoration and the
  final health probes passed:
  `artifacts/roadmap-7.3/bluetooth-hci-trace-followup-20261110T184909Z/`.
  A further bounded control after manual recovery completed with the same
  boot and payload, restored the primary controller, archived its trace and
  stopped the recovery timer only after health checks. Kernel log continuity
  passed, with two new frame reassembly `-84` warnings and no new HCI Reset
  `-110`. This is a rebind control, not repeated-boot acceptance:
  `artifacts/roadmap-7.3/bluetooth-after-manual-recovery-20261110T225528Z/`.
  A later offline audit verified continuous kernel captures for those six
  historical controls, but invalidated their readiness claim: every `info`
  capture had zero configured controllers and exhausted the fixed wait.
  The corrected collector uses bounded `btmgmt config`, requires hci0's missing
  public-address option, and stops before provisioning if readiness is absent.
  It snapshots the shared kernel-delta validator, refuses missing/ambiguous log
  continuity, and records restoration even after archive retrieval fails.
  Fourteen offline tests and one corrected on-device control passed:
  `artifacts/roadmap-7.3/bluetooth-config-trace-20261110T122454Z/`.
  All four resets completed successfully; two new `Frame reassembly failed
  (-84)` lines still occurred, so these lines alone do not explain `-110`.

- [x] Guard the reboot runner against mixed payloads and repeated failing tests.
  It snapshots itself, records deployed helper/service/udev hashes, checks them
  before and after each reboot, binds fastboot to serial `957be8c9`, waits for
  service completion and three ready probes, and stops on the first fault or
  identity change. It retains exit status and the final boot ID, and leaves
  the final running system without an extra unmeasured reboot. Nine mock
  transport tests cover successful completion, kernel failure, payload mutation,
  failed collection, missing baseline controller, exact kernel build identity
  and required RAM boot. A hardware check of the
  guarded runner passed in 45 seconds, preserving the payload and final running
  system: `artifacts/roadmap-7.3/bluetooth-runner-guard-20261110T110152Z/`.

Device r9 APK SHA-256:
`0ef62c991faf7b7dab23d70f0421e93d5d7e41dbec9d46a98b27dc17f5b12c5d`.
Historical 20-boot evidence: `artifacts/roadmap-7.3/bluetooth-20-20261109/`.

Baseline userspace identities: Mesa 26.2.6-1, Hyprland 0.57.1-1,
PipeWire 1.6.10-1, WirePlumber 0.5.18-1, BlueZ 5.87-2 and libcamera 0.7.2-4.
Normal r2 kernel APK SHA-256:
`22d4ceeadadce61c23751cec06067b220bff218212db509da6858bf4140e9edd`.
MSS diagnostic kernel APK SHA-256:
`a4e7a75559786b73073cd05349fb5c55dfdb6a46a8b6267e41239c5166cce237`.

### Audio, suspend and clocks

- [x] Exercise the installed UCM speaker, headphone and stereo microphone PCM
  routes for twenty bounded cycles without saving samples. All 60 route opens
  completed, and the mixer state was restored after every cycle. Report:
  `artifacts/roadmap-7.3/audio-routes-20261110T081500Z/`.
- [x] Reproduce any `wcd9335: overflow error on TX port 1` against a specific
  capture/route; compare SLIMbus, TDM, AIF4, micbias and UCM before codec changes.
  The corrected single-context validator reproduced the overflow in **5/10
  cycles**, and every new fault was attributed to the `Mic` **transfer** stage;
  speaker/headphone transfers and all PCM operations still completed. A fresh
  20-cycle route run reproduced the same fault in **10/20** cycles while all
  speaker, headphone and microphone opens passed. Evidence:
  `artifacts/roadmap-7.3/audio-validator-10-20261110T065155Z/` and
  `artifacts/roadmap-7.3/audio-mic-focused-20261110T094358Z/`.
  The 7.3.1 source handler only disables the affected interrupt and clears the
  status; it does not reset or reconfigure the SLIMbus port. Source bit masks
  show that `value 5` means overflow plus port closed, not overflow alone.
  Treat this as a
  transport hypothesis and collect TX channel/watermark state around
  `hw_params`/`trigger` before proposing a driver change.
  The phase-split collector then completed one 48,000-frame capture with the
  mixer restored and boot ID unchanged, while the new `TX1 value 5` appeared at
  `18488.860752` inside the active `start-read` interval (not `drop` or
  `close`). Its actual geometry was 48 kHz stereo, 960-frame periods and a
  7,680-frame buffer. This is stronger timing evidence, but the IRQ is deferred
  work and still does not establish register-level causation:
  `artifacts/roadmap-7.3/audio-mic-phases-20261110T165846Z/`.
  An offline audit verified all eight kernel-log phase boundaries and placed
  the printk timestamp 60.269 ms before drop. Use monotonic, not boottime,
  timestamps after suspend. See `docs/audio-7.3.md` for scope and recovery.
  Private patch 0205 now instruments configuration/mapping, API return values
  and the first fault source without changing the existing stream/IRQ handling.
  It is excluded from production, requires a separate audio opt-in and module
  parameter, uses `-t825-audiodiag`, and refuses the MSS opt-in combination.
  ARM64 object compilation with warnings as errors, five package-isolation
  tests and a helper stub harness passed. It has not been built into an accepted
  RAM image or run on the tablet:
  `artifacts/roadmap-7.3/audio-portdiag-build-20261110T175738Z/`.
- [x] Complete the private ARM64 audio-diagnostic kernel build with 0205 and
  0204, including `Image.gz`, modules and both T825 DTBs. Build status is 0;
  the module reports release `7.3.1-t825-audiodiag` and the opt-in parameter
  remains off by default. Report:
  `artifacts/roadmap-7.3/audio-portdiag-full-build-20261110/`.
- [x] Assemble and validate an unaccepted audio-diagnostic RAM candidate with
  the instrumented `snd-soc-wcd9335` module, release
  `7.3.1-t825-audiodiag`, and `snd_soc_wcd9335.port_diagnostics=1`. It keeps
  MSS disabled, preserves read-only direct-root and supervisor checks, and
  fits lk2nd with 4,500,992 bytes of margin. Report:
  `artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261110b/`.
- [x] Verify admission and cleanup of the audio candidate through legacy
  `kexec_load` (`loaded 0 -> 1 -> 0`) without executing it. Evidence:
  `artifacts/roadmap-7.3/kexec-route-audit-20261110/audio-repro-20261110/`.
- [x] Audit the installed r1 runtime for a no-reboot instrumentation path.
  Debugfs has no `dynamic_debug/control` and tracefs exposes no audio/SLIMbus
  events, so first-fault configuration requires the separate audiodiag image.
  Report: `artifacts/roadmap-7.3/audio-runtime-trace-audit-20261110/`.
- [x] Load the audio-diagnostic candidate on the tablet and capture the first
  WCD9335 fault configuration. This requires the accepted nonpersistent handoff
  and recovery gate; no module has been loaded on the installed system.
  The current candidate is
  `artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261111f/`.
  Candidate d's first RAM cycle passed exact kernel/read-only handoff and
  recovered to installed r1 in 266.664 seconds, but blocked capture before PCM:
  no ALSA card or active WCD9335 module was present. Report:
  `artifacts/roadmap-7.3/audio-ram-cycle-20261111T004744Z/`.
  The builder now includes ADSP PAS, Q6AFE DAI and RT5508 providers; the stricter
  archive check rejects d and intermediate e and passes f. Explicit provider
  startup after handoff is implemented with a 45-second deadline, protected
  module-tree checks, MDT/segment validation, an explicit module list and ALSA
  readiness checks. Read-only installed-firmware validation and 31 local tests
  pass in `artifacts/roadmap-7.3/audio-provider-preparation-20261111T005604Z/`.
  Actual provider startup subsequently passed in
  `artifacts/roadmap-7.3/audio-ram-cycle-20261111T021714Z/`: one 48,000-frame
  stereo capture completed with no clipping or matched kernel faults, nineteen
  port diagnostic lines were retained, mixer restoration matched byte for byte,
  and automatic reset returned to installed r1 in 266.036 seconds. The result
  is `PASS_HANDOFF_AUDIO_PROBE_AND_RESET`, destination Linux. No overflow was
  reproduced, so first-fault capture and compatibility acceptance remain open.
  A bounded follow-up is prepared: `--audio-repetitions 3` captures at most
  three times in the same RAM boot, stops at the first fault and keeps existing
  collector/recovery deadlines. Thirty-six offline tests pass, including
  first-fault termination and complete-count validation:
  `artifacts/roadmap-7.3/audio-three-captures-offline-20261111T022504Z/`.
  The authorized three-capture hardware run then entered fastboot remotely,
  reached the exact audiodiag handoff and reproduced the first fault during
  capture 1: `wcd9335_slimbus_irq: overflow` and
  `portdiag stage=irq dir=TX port=1 source=0x5 overflow=1 underflow`.
  The PCM capture delivered 48,000 stereo frames, mixer restoration matched
  byte-for-byte, and the probe stopped at `captures_completed=1/3` as required.
  The diagnostic reset returned to fastboot and the authorized controller
  restored Arch automatically. Report:
  `artifacts/roadmap-7.3/authorized-audio-three-captures-20261111T104500Z/`.
  This confirms reproducible transport failure and captures its phase/configuration;
  it does not claim a codec fix or acoustic acceptance.
  The generic read-only cycle now has an opt-in `--audio-probe` for one bounded
  microphone lifecycle capture after handoff, with frozen collectors, strict
  recovery/root/module gates, volatile output and mixer restoration. It keeps
  recovery active on capture/restoration failure and records audio status
  independently of handoff/reset. Offline checks pass in
  `artifacts/roadmap-7.3/audio-ram-probe-offline-20261111T003207Z/` (9 host-cycle,
  3 remote-probe and 13 capture tests plus image validation). This is prepared
  test infrastructure, not first-fault hardware evidence.
  Downstream comparison found and corrected mixed RX-local/SLIMbus indices
  in patch 0205's register reader. An independent-address regression fails
  on the old helper and passes on the correction; the full ARM64 rebuild and
  read-only image validation pass. Candidate c was rejected for exceeding the
  lk2nd memory budget with unstripped modules; the builder now validates before
  publishing success. Source comparison confirms the same watermark and
  overflow/port-closed reporting, so neither is changed as a speculative fix.
  See [audio investigation](docs/audio-7.3.md) and
  `artifacts/roadmap-7.3/audio-downstream-20261110T231416Z/`.
- [x] Audit the pinned SLIMbus stream transaction paths before proposing an
  audio fix. `slim_stream_prepare()` drops connect errors; enable drops
  define/content/activate errors; disable drops per-port deactivate/remove
  errors. The audit is read-only, records source hash and exact lines, and
  explicitly leaves `production_fix_accepted` false. Evidence:
  `artifacts/roadmap-7.3/audio-slim-stream-audit-20261111T121500Z/analysis.json`.
  A first-fault capture must still demonstrate a negative return before any
  error-propagation patch is built.
- [x] Add private SLIMbus transaction diagnostics (0206) and reproduce the
  codec fault with actual connect/NGD-enable/teardown return evidence. Candidate
  g passed read-only image validation and the 126-case differential host test;
  the module rebuild, package isolation and capture recovery tests passed.
  Hardware capture 1/3 delivered 48,000 stereo frames and reproduced TX1
  overflow during drop, with all eleven logged stream results equal to zero.
  The generic enable path is bypassed by NGD's controller callback, correcting
  the earlier lexical audit's attribution. Preserve error/IRQ behavior and
  investigate teardown sequencing; no audio correction is accepted. Evidence:
  `artifacts/roadmap-7.3/slimbus-transaction-diagnostics-20261111T112642Z/`,
  `artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261111g/` and
  `artifacts/roadmap-7.3/authorized-audio-transaction-diagnostic-20261111T134500Z/`.
- [x] Classify NGD teardown dispatch using the actual transfer function.
  The host harness passes 1,024 message-type/opcode combinations and 18
  translated connect/disconnect failure cases. Six observed teardown returns
  are from the early-return core-message range `0x40..0x5f`, before transport
  allocation; four connect/disconnect calls use translated user messages and
  completion waits, and one enable result is aggregate. This is source-bound
  dispatch evidence, not proof that the firmware removed the channels or that
  missing removal causes overflow. Record Q6AFE shutdown and downstream
  port-close ownership before changing scheduling. Evidence:
  `artifacts/roadmap-7.3/ngd-teardown-source-20261111/`.
- [x] Resolve the downstream NGD removal protocol and test private patch 0207.
  The Samsung manager callback sends `CHAN_CTRL` (`0x23`) with remove/client,
  TID and channel IDs, followed by `RECONFIG_NOW` (`0x24`); its ACK success bit
  is `0x20`. Candidate h implements that sequence behind a default-off option,
  checks both replies and propagates callback failure in the private stream
  path. The real functions pass 527 host cases, and both ARM64 modules compile
  with `-Werror`. Hardware returned success from the callback but still
  reproduced TX1 overflow on capture 1/3; mixer restoration passed and no next
  capture ran. Reject this as a sufficient audio fix; measure codec/AFE/IRQ
  ordering with buffered events before another sequencing change. Evidence:
  `artifacts/roadmap-7.3/ngd-downstream-protocol-20261111/`,
  `artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261111h/` and
  `artifacts/roadmap-7.3/authorized-audio-ngd-removal-20261111T120110Z/`.
- [x] Prepare and validate a normal-r2 read-only RAM candidate offline. It is
  pinned to normal-r2 image SHA256
  `252e0a8de12d0469e0e6218dfe159a0bc4a5bbfc53a5e26ce32750cab0af9d2c`, keeps
  the LTE MSS disabled, protects all Btrfs members before `ro,rescue=nologreplay`
  mount, skips the installed boot volume, retains the static supervisor across
  `switch_root`, and fits the lk2nd budget with 4,836,864 bytes margin.
  Offline result:
  `artifacts/roadmap-7.3/normal-r2-readonly-candidate-20261110d/`.
- [x] Boot the read-only normal-r2 candidate. Manual initial fastboot entry
  enabled a successful detached RAM cycle on 2026-11-11. Exact kernel `#3`,
  direct PID 1, original supervisor executable hash/PID, both Btrfs read-only
  flags and `ro,rescue=nologreplay` were verified; `/boot` was not mounted.
  Reset returned automatically to installed r1 in 275.535 seconds, not fastboot.
  Evidence: `artifacts/roadmap-7.3/readonly-r2-cycle-20261111T002227Z/`.
  This accepts the kernel handoff and software recovery only, not GPU/audio
  functionality, full-lockup recovery or consecutive unattended RAM cycles.
  The new `tools/t825-readonly-cycle.py` freezes the paired image inputs before
  validation, obtains supervisor identity from the embedded archive, checks the
  exact running kernel/PID 1 and both read-only Btrfs members, and observes the
  final reset even after diagnostic failure. Failed fastboot probes are unknown,
  not evidence of a disconnect. Seven fake-transport tests pass; normal-r2 and
  audio candidate d also pass offline validation. A detached normal-r2 attempt
  started at 23:43 UTC with a ten-minute initial-fastboot wait:
  `artifacts/roadmap-7.3/readonly-r2-cycle-20261110T234307Z/`.
  The attempt ended with `PREFLIGHT_FAILED`: fastboot did not appear during
  the ten-minute wait. No RAM boot or reboot command was dispatched; the
  tablet remained on installed r1 with its unchanged boot ID. The process
  exited, and `cycle/result.json` records that historical terminal result.
  The later successful cycle uses USB SSH (`172.16.42.1`) during direct-init;
  the `tabs3` alias uses Tailscale and is only suitable after installed Linux
  starts its services. A changed, valid boot ID distinguishes Linux reset
  recovery from a still-running diagnostic.
- [ ] Test both microphones, every speaker and CTIA insertion/removal, including
  twenty route cycles without audible or recurring kernel errors.
- [ ] Investigate `pclk0_clk_src: rcg didn't update its configuration` using
  before/after clock and power state; verify patches 0147 and 0148 on the T825.
  The installed kernel reproduces two `pclk0` and two `pclk1` warnings at boot,
  while the display remains functional. A bounded 15-second s2idle comparison
  captured `clk_summary` immediately before and after suspend: both sources
  remained at `148866500` Hz. An independent audit of the retained full logs
  found continuous dmesg, s2idle entry/exit and no new pclk messages. This is
  one transition without the warning, not proof that it is exclusive to boot;
  it does not validate patches 0147/0148 or explain the duplicate requests. Evidence:
  `artifacts/roadmap-7.3/pclk-investigation-20261110T082407Z/` and
  `artifacts/roadmap-7.3/pclk-suspend-20261110T095338Z/independent-audit.json`.
  A fresh three-cycle s2idle series again held both clocks at 148866500 Hz and
  added no pclk messages after wake:
  `artifacts/roadmap-7.3/pclk-suspend-series-20261110T115914Z/`. The boot-only
  warning and the 0147/0148 hypothesis remain unproven.
  Full current-boot stacks now attribute the two warning pairs to byte-rate
  OPP propagation and explicit pixel-rate setup during fbcon initialization,
  before DSI link-clock enable. The common clock framework ignores the provider
  set-rate error in this path, so visible output and reported rates are not
  proof of RCG update success. Patches 0147/0148 affect PCIe power and MDP5 pipe
  ownership, respectively; neither is a direct pixel-clock fix. Failure-time
  parent/RCG/PLL state is still required. See
  [display-clock investigation](docs/display-clock-7.3.md) and
  `artifacts/roadmap-7.3/pclk-source-boundary-20261110T233238Z/`.
  A fresh live capture independently retained all four complete stacks (two
  `pclk0`, two `pclk1`) and the analyzer classified every one as the same
  fbcon-to-DSI pixel-rate boundary. The report records `cause_proven: false`
  and `hardware_fix_accepted: false`; no warning suppression or speculative
  clock change is justified. Evidence:
  `artifacts/roadmap-7.3/pclk-live-boundary-20261111T103933Z/analysis.json`.
  The parser and regression test are `tools/analyze-t825-pclk.py` and
  `tools/test-t825-pclk-analysis.py`.
  The persistent journal shows the warning is intermittent: across 25 boots of
  the same installed kernel (identical Linux version line and command line),
  13 boots logged all four warnings and 12 logged none. Outside the warning
  stacks, display and clock messages are identical, and fbcon timing ranges
  overlap (8.64–10.92 s clean, 9.74–11.39 s warning). This excludes a fixed
  configuration error; the race itself is unidentified. Evidence:
  `artifacts/roadmap-7.3/pclk-boot-frequency-20261111T152337Z/`.
  A read-only collector (`tools/t825-pclk-state.sh`) run after authorized
  round trips found that the warning matches a register state in 5/5 distinct
  boots: in both warning boots pclk0 and pclk1 `CMD_RCGR` stay at
  `0x00000010` (DIRTY_CFG set, CMD_UPDATE clear) about 50 s after boot; in the
  three clean boots both read zero. CFG, M, N, D and rates are otherwise
  identical, and byte RCGs are never dirty. The pixel RCGs did not latch their
  configuration. Whether dsi0pll was not yet running at the update is untested.
  Evidence: `artifacts/roadmap-7.3/pclk-state-correlation-20261111T153349Z/`.
  The opt-in RAM trace (patch 0209, `clk_qcom.rcg_update_trace`) identifies the
  mechanism. In a warning boot the first pixel update starts with the RCG root
  running (`CMD_RCGR=0x000000f0`) and CMD_UPDATE never clears; in a clean boot it
  starts with the root off (`0x800000f0`) and latches at once. In both, CCF has
  dsi0pll unprepared and disabled. A running RCG cannot switch to a stopped
  source, so the warning depends on the inherited root state. A parent-enable
  fix is untested. Evidence: `artifacts/roadmap-7.3/rcg-trace-analysis-20261111/`.
- [ ] Compare charge/idle/suspend consumption under matched load and temperature.
  An exploratory profile sampled the SM5705 fuel gauge during idle,
  a fixed Python CPU loop and a window after 20-second s2idle, without changing
  charger policy. It does not sample current during suspend, and the fixed
  30-second loop does not match the configured 20-second sampling window.
  The first profile reported medians of `-96 mA`, `-102 mA` and `-74 mA`
  in the sampled windows at 44–46 °C:
  `artifacts/roadmap-7.3/power-profile-20261110T120423Z/`. Two repeats showed
  substantial charger/fuel-gauge variation (idle `-66/-78 mA`, load `-97/-70
  mA`, post-s2idle `-81/-74 mA`), so these are exploratory samples rather than an
  accepted consumption comparison. Its prototype runner was removed because
  it could pass without observing suspend success and provided no independent
  recovery timer. A calibrated external power measurement or
  charger-disconnected matched test is still required.

## Phase 3: GPU and compositor

- [x] Reproduce synthetic hangs with culprit identification and compositor
  survival. A fresh three-repetition run on the installed r1 kernel identified
  `gpuhang`, recovered normal drawing and kept the same Hyprland process. This
  proves selected recovery behavior, not the cause of browser hangs. Report:
  `artifacts/roadmap-7.3/gpu-r1-20261110T080117Z/`.
- [x] Apply the upstream A5xx hangcheck progress change `65222fbe8` as patch 0204
  after 0201 and build the normal r2 package. RAM acceptance remains open in
  the normal-r2 boot and r1/r2 comparison gates below; the earlier checkbox
  incorrectly combined the completed build with unproven hardware acceptance.
- [ ] Compare r1 and r2 using the same workload, changing only the stated
  hypothesis. Keep a control without 0201 as a separate experiment if needed.
  The normal r2 image at `normal-r2-boot-20261110/` lacks validated independent
  recovery. The attempted pairing in `normal-r2-recovery-20261110d/` is rejected
  (`REJECTED.json`): installer mutations and writable root/boot mounts remain,
  recovery across root replacement is unproven, and DTBs came from the diagnostic
  tree. Do not boot this candidate; its experimental builder was removed.
  `artifacts/roadmap-7.3/r2-ram-validation-20261110T114526Z/decision.json`
  corrects the earlier attribution: the report observed installed r1 (`#2`),
  not r2. No `fastboot boot` was recorded. The later GPU attempt also returned
  to installed r1, without testing r2:
  `artifacts/roadmap-7.3/gpu-r2-ram-20261110T115000Z/`.
  Build and validate a read-only root with RAM-backed graphical-session writes,
  assert the complete kernel build identity, and observe actual RAM boot plus
  independent reset before performing the GPU comparison.
- [ ] Capture DRM state, kernel logs and Hyprland crash reports from real hangs;
  distinguish kernel recovery, Mesa command generation and compositor reset handling.
  The bounded runner `tools/t825-chromium-gpu-test.sh` supports Chromium and the
  installed Brave-origin binary. A 10-second WebGL/Wayland run completed under
  Brave with Hyprland's PID unchanged and no new GPU reset lines; this is a
  workload baseline, not the required real-hang reproduction. Report:
  `artifacts/roadmap-7.3/chromium-gpu-20261110T084239Z/`.
- [ ] Require 20 controlled reproductions without compositor restart or a
  subsequent hangcheck cascade before calling the correction accepted.

Use `tools/gpuhang.c` only with recovery verified and work saved. Enable tracing
only as needed in diagnostic builds. Keep `--disable-gpu-rasterization` as a
mitigation until the browser workload is demonstrated fixed.

Normal r2 APK SHA-256:
`22d4ceeadadce61c23751cec06067b220bff218212db509da6858bf4140e9edd`.

## Phase 4: stock comparison, GNSS and LTE

Start with matching Samsung source, stock DTBs, configuration and downstream
sequencing. Original blobs can clarify service names, interfaces and protocols;
use a specific hypothesis before decompiling. Developer blogs provide leads
that need reproduction on this tablet. Signed firmware remains a dependency;
editing a blob does not imply that TrustZone will accept it.

Relevant earlier upstream findings: branch `t825-modem`, commits `96ec44f`
(MSS), `f7f688b` (checker), `fd38603` (Venus/7.3) and `10e01ae` (7.3 stack).
Pin revisions and review changes individually rather than importing a branch.

### GNSS first

- [x] Verify private original firmware and calibration backups with
  `tools/t825-gnss-preflight.sh`; owner-only files and manifests are required.
- [x] Keep patch 0203 disabled in normal builds. The diagnostic sentinel
  `.t825-enable-mss` changes both the DT and module release; remove it before
  normal builds. pmbootstrap sanitizes arbitrary environment variables.
- [x] Fit the private image into lk2nd's 50 MiB pool by mounting modem firmware
  read-only rather than embedding all `modem.b*` segments.
- [x] Map private calibration to the canonical volatile `modemst1`, `modemst2`,
  `fsg`, `fsc` files with `install/t825-prepare-rmtfs-calibration.sh`.
- [x] Demonstrate remoteproc `2080000.remoteproc`, `/dev/qcom_rmtfs_mem1`, QRTR
  Location (PDS v2), rmtfs without errors and TFTP `server_check.txt`.
- [x] Demonstrate QMI LOC `msb`, NMEA capabilities and `loc-start`/`loc-stop`.
  Position and satellite reports returned no data in 10 s and 90 s attempts.
- [x] Fix the USB/systemd handoff with unattended recovery proven first. v60
  kept the NCM gadget through the Arch transition and passed post-pivot SSH;
  the independent supervisor still reset the tablet and the host observed
  fastboot return.
- [ ] Acquire satellites and a sustained antenna fix, then check SSR, suspend
  and coexistence with Wi-Fi/audio. Transport success does not establish a fix.

Historical evidence: `artifacts/roadmap-7.3/gnss-ram-20261108/hardware-v17-20261109T173200Z/`.
Old images through v58 are historical diagnostics and fail the current
direct-root safety gate. The v59 recovery-only candidate remains the accepted
read-only control, and v60 is the first MSS-enabled image to pass the same
handoff and recovery gate.
See [GNSS/EFS audit](docs/gnss-efs-audit.md).

### LTE after GNSS

- [ ] Verify TrustZone dependencies, SIM, calibration and QMI service behavior.
- [ ] Enumerate services, detect SIM, register and establish a data session in
  separate stages with explicit evidence at each boundary.
- [ ] Investigate the IPA v2.5 data path; mainline IPA support starting at v3.0
  is a separate gap. Enabling MSS does not establish LTE data support.
  The pinned MSM8996 v2/v3 source describes IPA 2.5 with BAM/SPS transport,
  remote BAM ownership and a microcontroller pipe-reset workaround. Mainline
  uses GSI and different endpoint register layouts; a new compatible string
  is insufficient. The implementation sequence and source evidence are in
  [IPA 2.5 investigation](docs/ipa25-7.3.md). The offline LTE audit now detects
  ordinary DTS node names correctly and distinguishes DT presence from runtime
  binding; the production DT still has no IPA node. Driver implementation and
  hardware validation remain open.
- [ ] Require bidirectional traffic, signal-loss reconnect and suspend/resume.
  Voice and SMS need their own acceptance criteria if included later.

  Static audit: the production DT keeps MSS disabled, the installed config has
  `CONFIG_GNSS` and `CONFIG_WWAN` disabled, and no IPA platform device exists;
  `CONFIG_QCOM_IPA=m` alone is not a data path. The separate v63 diagnostic DT
  has MSS enabled. Report: `artifacts/roadmap-7.3/lte-audit-20261110T093608Z/`.

Do not assume USB `qmi_wwan` supports this internal modem. Do not enable the
complete modem stack in production before recovery and boot logs are established.

## Phase 5: package, release and upstream

- [ ] Finish acceptance for every changed area; preserve remaining UNTESTED items.
  The read-only audit tool `tools/audit-roadmap-7.3.py` now enumerates every
  unchecked gate, verifies referenced local artifacts and records current
  fastboot/ADB/USB state. The latest result is
  `artifacts/roadmap-7.3/roadmap-audit-20261110T200147Z.json` (22 hardware or
  offline gates remain open; no referenced artifact is missing; SSH and fastboot
  are unavailable and the NCM carrier is `0`).
  The detached kexec-proof launcher and WCD9335 artifact-layout validation are
  covered by `artifacts/roadmap-7.3/offline-checks-20261110T200510Z/`.
  The complete offline test suite and shell/static checks pass in
  `artifacts/roadmap-7.3/full-offline-suite-20261110T200645Z/`.
- [x] Build and inspect config, modules, DTBs and artifact hashes. Validate the
  actual image/header, archive identity, legacy command-line limit and lk2nd budget.
  A package inspection now records the normal r2 APK (`22d4…`) with MSS disabled
  and the separate diagnostic APK (`a4e7…`) with the MSS DT node enabled; both
  payloads and DTBs were hashed. Report:
  `artifacts/roadmap-7.3/package-inspection-20261110T083710Z/`.
  The v63 MSS/GNSS RAM image was also revalidated against its paired initramfs,
  DTB and kernel budget: 23,966,208-byte decompressed kernel under a
  27,734,016-byte lk2nd budget. Report:
  `artifacts/roadmap-7.3/ram-image-validation-20261110T084502Z/`.
- [x] Run relevant checks: supervisor QEMU tests, GNSS preflight/calibration
  tests, image validation, ShellCheck and shell syntax. The current suite also
  passes the handoff, Bluetooth trace and read-only initramfs checks; the kernel
  update/rollback regression suite passes 44 tests, and the guarded kexec
  runner passes its three host-only safety checks. Evidence:
  `artifacts/roadmap-7.3/final-checks-20261110T185843Z/` and
  `artifacts/roadmap-7.3/final-checks-20261110T192837Z/`.
- [x] Update hardware/kernel/troubleshooting documentation with measured
  results, including the accepted v59/v60 direct-root handoff, Bluetooth trace
  attribution, current v63 image validation default and the remaining open
  acceptance gates.
- [ ] Test rollback with the preserved working image before an installed update.
- [ ] Submit generic patches upstream separately from T825-specific changes.
  **BLOCKED** (2026-11-11): the series is prepared but not sent. 122 generic,
  1 board-only, 1 mixed and 78 excluded patches are classified; only one generic
  patch is checkpatch-clean, 32 lack Signed-off-by and 66 carry a placeholder
  author. Sending needs the author's real identity, DCO sign-off and explicit
  approval. See [upstream series](docs/upstream-series-7.3.md) and
  `artifacts/roadmap-7.3/upstream-series-20261111T151728Z/`.

Advance by reproducible hardware evidence. A successful build, archive inspection
or isolated RAM boot does not complete the compatibility roadmap.

Additional boot-warning attribution (2026-11-11): `644000.dma-controller` is
crypto BAM, distinct from the downstream IPA BAM. Its DT clock ID has no GCC
provider entry, triggering a fallback that requires absent channel/EE counts.
The QCE consumer is unbound and its kernel option is behind `BROKEN` because of
secure-world access races. No speculative clock/channel patch was applied.
See [crypto BAM investigation](docs/cryptobam-7.3.md) and
`artifacts/roadmap-7.3/cryptobam-source-20261111T003515Z/`.
