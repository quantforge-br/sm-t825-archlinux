# Unattended recovery audit

Updated 2026-11-10. Automatic tablet recovery is possible and has repeatedly
been observed in RAM-boot cycles without a manual reset. USB/SSH
handoff remains a separate compatibility failure.

## Hardware evidence

| Test | Cycles | Fastboot return | Result |
|---|---:|---|---|
| Minimal initramfs, no root/modem mounts, 30 s supervisor | 2 | 36 s, 37 s | Automatic reset and next boot passed |
| RAM-only switch_root, shell cleanup, retained supervisor and 60 s lease | 2 | 70 s, 68 s | Automatic reset across real root replacement passed |
| Full pmOS initramfs, MSS disabled, installed-root transition, 240 s supervisor | 1 | 248 s | Reset recovery passed; post-pivot SSH failed |
| Full v31 with inherited initramfs gadget and masked persistent gadget service | 1 | 249 s | Reset recovery passed; post-pivot SSH still failed |
| v59 read-only Arch direct-init control, both Btrfs members protected | 1 | 249 s | PID 1, SSH, read-only root and supervisor passed; MSS disabled |
| v60 MSS-enabled read-only Arch direct-init | 1 | 249 s | MSS remoteproc, QRTR/QMI, PID 1, SSH, read-only root and supervisor passed |

The first four cycles were driven by `tools/t825-recovery-proof.sh` using a
detached host process. The full image used `tools/t825-gnss-auto-cycle.sh`, also
detached, which waited for the final recovery after the collector failed.
All used `fastboot boot`. The tablet was left in fastboot. No partition was
flashed and no persistent boot file was renamed by these tests.

Private reports under `artifacts/roadmap-7.3/recovery-v31/`:

- `hardware-20261109T223727Z/`: first two timeout/reset cycles.
- `handoff-hardware-20261109T224237Z/`: actual RAM-only switch_root cycles.
- `system-hardware-20261109T224732Z/`: initial USB shell reached, native
  `pmos_continue_boot` accepted, SSH unavailable, autonomous fastboot return.
- `inherited-usb-v2b-hardware-20261109T233407Z/`: repeated with the
  historically successful inherited-gadget strategy; SSH still unavailable,
  autonomous fastboot return observed. Host USB/link snapshots are included.

The RAM-only handoff test issues its longer lease only after the new PID 1
checks that the original process is alive, its log survived the `/run` mount
move and its old binary has been removed by switch_root. The measured return
must exceed 55 s; an early 30 s recovery fails that acceptance gate.

Image SHA-256 values for these measured tests:

- Minimal: `1aa566073dbeae6ba6b64ab0755b6304ec4e87e21ce0abe375e1a6427b0be2bf`.
- RAM handoff: `9c2f685c4bee61d6a4095ffef11f08d5ec0138c1d2e0be1caebd794e9a582f55`.
- Full pmOS/MSS-disabled: `4cae6953495bbb703ff6cfcd2148db06af2cf8443db216c8f9a9ff7d8f132d31`.

## Why earlier recovery failed to provide a guarantee

1. Systemd units packed in initramfs do not automatically become available on
   the installed root after switch_root. `systemd.wants=` cannot load a missing
   unit. Copies in initramfs `.wants` directories do not solve this boundary.
2. The shell hold timer started after an unbounded remoteproc `state` write;
   modem startup could prevent it from ever arming.
3. pmOS `init_2nd.sh` kills `pidof sh` processes during cleanup. A background
   shell is not an independent recovery mechanism across this transition.
4. `systemctl reboot --force || ...` falls back only if the command fails,
   not if a successful shutdown request stalls later.
5. An SSH marker previously cancelled recovery permanently, and an unsuccessful
   SSH collector could still report success.
6. Iteration counts did not include probe time and could exceed advertised
   timeouts. Earlier runners also renamed extlinux files while describing the
   operation as touching no partitions; the replacement runner does not.

The v30 archive validation therefore did not establish autonomous recovery.
Missing USB alone also did not establish that automatic recovery was impossible.

## Implemented replacement

`tools/t825-recovery-supervisor.c` is a freestanding static AArch64 executable.
It has no shell, libc, dynamic-loader or systemd dependency. It uses
CLOCK_BOOTTIME and retained directory/log/SysRq descriptors, so recovery does
not need pathname lookup in the discarded root. Four QEMU tests exercise the
actual ARM64 binary, including expiry and directory/lease transfer, in dry-run
mode that never invokes a reboot syscall.

`install/prepare-t825-recovery.sh` arms it immediately after proc/sys/dev/run
mounting, before libcomposite, udev, debug hold, remoteproc and QRTR operations.
The full hardware image above armed after `mount_proc_sys_dev`; subsequent
source inspection found USB module loading inside that function, so the final
integration moves arming inside it, directly after the tmpfs mount. That final
earlier insertion is image-validated; the modem-enabled final image has not
been hardware-accepted.

The initial deadline is 240 seconds. Optional leases in
`/run/t825-recovery/lease` can extend it by at most 120 seconds ahead of the
current boot clock, with an absolute one-hour cap. Absence of a lease never
cancels expiry. The kernel reboot syscall is independent of systemd; a separate
child attempts SysRq `b` after ten seconds if reboot stalls and scheduling still
works. This emergency fallback itself has not been forced/tested in hardware.

The USB helper/unit are staged in RAM-backed `/run` before its move into the
new root, and a direct runtime wants link is created for the systemd host
manager. The extlinux restore unit is masked through `systemd.mask=`, whose
early generator output has higher priority than `/etc`; a plain unit in
`/run/systemd/system` would not override an `/etc` definition. The v31 image
also has a mode that masks the persistent gadget service and preserves the
initramfs gadget, matching the historical v17 run. Those historical modes
lost USB after the pivot, but v59 and v60 corrected the direct-root path: both
verified the replacement PID 1, read-only root, SSH and the original
supervisor, and v60 observed the Samsung NCM gadget after the pivot. The
accepted handoff is therefore closed for the read-only direct-root image; the
older transport failures remain historical evidence. The final hold image
also sets `panic=10`; its panic path has not been deliberately triggered.

The default v31 modem image passed structural validation:
`0d8207ba7ebed264ea6abb3ca562cf00d95625e4b569cd76a46f9ad7ff3d9484`.
Its initramfs is 22,970,967 bytes, decompressed kernel 23,966,208 bytes, lk2nd
kernel budget 27,324,416 bytes, and command line 500 bytes. The v32 candidate
`026b55651f08b8e167cd98deea760b1704d0c8ad0e6bee062ecec588396cfd89` adds a
preserved initramfs DHCP lease, an idempotent active-gadget check and transient
sshd wants. Its detached hardware run is recorded in
`artifacts/roadmap-7.3/recovery-v31/v32-preserve-dhcp-ssh-20261110T000612Z/`:
the initial shell and USB enumeration passed, post-release USB disappeared
before SSH (the host kernel saw the Samsung NCM/ACM device disconnect about
four seconds after enumeration), and autonomous fastboot recovery completed
in 248 seconds.
Neither image marks
MSS/pivot recovery acceptance complete.

A v33 follow-up additionally masked `NetworkManager.service`,
`systemd-networkd.service` and `unudhcpd@usb0.service`. The detached run
(`artifacts/roadmap-7.3/recovery-v31/v33-mask-network-20261110T001555Z/`)
produced the same result: no post-pivot SSH and autonomous fastboot recovery
in 248 seconds. The disconnect is therefore not explained by those root
network managers alone.

A v34 control boot also disabled the root USB helper entirely and retained
only the initramfs gadget. It still failed post-pivot SSH and returned to
fastboot in 249 seconds (`v34-inherited-only-20261110T002157Z`), which points
to the root handoff or kernel UDC lifecycle rather than one persistent network
service.

The v38–v40 direct-init traces showed that the process remained in
`/init_2nd.sh` with `handoff-stage=post-debug`; those variants had omitted or
overloaded root command-line parameters during early experiments. v41 restored
the verified root UUID and `subvol=/@` options while bypassing `check_keys` and
preserving NCM. It still did not reach post-pivot SSH and recovered to fastboot
in 249 seconds, so the remaining blocker is before or during `switch_root`.

The v42 trace retained those verified root parameters and bypassed the
debug-shell `check_keys` path. It still failed to expose the direct post-pivot
init and returned to fastboot in 250 seconds, narrowing the failure to the root
mount, cleanup hooks or `switch_root` itself.

The v44 direct-release run fixed the test helper so `pmos_continue_boot` exits
after stopping telnetd. It still produced no post-pivot SSH; the host recorded
a CDC NCM disconnect after a transmit-queue watchdog event, and the supervisor
returned the tablet to fastboot in 89 seconds. This is a transport failure with
early autonomous recovery, not a successful handoff.

The image generator is now hardened against a stale `init_2nd.sh` direct-init
branch that used `exit 0` after the debug shell. That branch skipped
`mount_root` and `switch_root`. The existing v45 direct-switchroot image was
validated and completed an unattended hardware cycle on 2026-11-10:
the initial debug shell and `pmos_continue_boot` were reachable, SSH after the
handoff was still unavailable, and the independent supervisor returned the
tablet to fastboot in 249 seconds. The result is a recovery pass and a
post-pivot compatibility failure. RAM boot does not itself prove absence of
filesystem writes; see the subsequent filesystem audit below.

## Root-handoff and filesystem audit, v46–v59

The original netcat collector could truncate terminal output. The replacement
`tools/t825-telnet.py` handles fragmented telnet negotiation, waits for a unique
remote completion marker, returns the remote status and enforces a deadline.
Host tests cover delayed output larger than 32 KiB and a failing remote command.
Per-hook TCP tracing uses a host listener on the USB address and a temporary
firewall rule restricted to this peer, destination and port 2324. The collector
removes its rule and listener on exit.

v50 exposed an unintended `btrfs filesystem resize max /sysroot` from the stock
initramfs and a reported resize of `/dev/mmcblk0p47`. All deletion and resize
calls are now suppressed in diagnostic stage 2. Earlier runs must not be
described as having made no persistent filesystem writes.

v51–v53 attempted a read-only mount with replay disabled and stopped at
`pre-mount-root`; no authoritative mount error was captured. v54–v57 reverted
to an initially writable root mount followed by a read-only remount. v54 reached
all cleanup hooks and `pre-switch-root`, but that workaround permits filesystem
writes and is no longer accepted. The reason the read-only attempts failed is
still unproven; replay requirements must not be assumed.

The installed root is Arch, whereas the build root is Alpine. Direct init now
resolves the installed sshd executable, mounts pseudo filesystems and creates
`/run/sshd`. It uses an existing host key or generates a transient one, and
stages only the host public key into `/run` for authentication without a mounted
home subvolume. v56 reached an SSH authentication rejection, but that experiment
used plain `switch_root` rather than `exec switch_root` and does not establish a
valid PID 1 handoff. The source and v57 restore `exec`; validation enforces it.

v57's collector crashed because its shell source was edited while Bash was
executing it. The report records diagnostic status 2 and automatic fastboot
recovery in 250 seconds:
`artifacts/roadmap-7.3/gnss-ram-20261108/auto-v57-20261110T041107Z/`.
The runner now snapshots and hashes its orchestrator, collector, validator and
telnet helper before boot, and executes those isolated copies.

The v58 candidate showed that this kernel rejects the older `nologreplay`
spelling (`btrfs: Unknown parameter 'nologreplay'`). A read-only manual mount
using `rescue=nologreplay` succeeded, and the v59 candidate applies that form.
It discovers every block device sharing the Btrfs UUID (this tablet has
`mmcblk0p44` and `mmcblk0p47`), sets each device read-only and verifies the
flag before mounting. It skips the installed boot volume entirely; there is no
writable fallback. The collector retains the initial telnet endpoint while
releasing the debug hold, so a failed mount can be inspected rather than hidden
by deliberately killing the diagnostic transport. A direct-root PASS requires
the replacement PID 1 identity, read-only `/` mount, SSH and the original
supervisor. v59 met all four checks and returned to fastboot automatically in
249 seconds:
`artifacts/roadmap-7.3/gnss-ram-20261108/auto-v59-20261110T042431Z/`.
This accepts the recovery-only control; MSS/GNSS still needs the same gate.

The v60 MSS-enabled cycle used the same read-only root protection and proved
the modem path survives the root handoff. `remoteproc0` was `2080000.remoteproc`
with firmware `qcom/msm8996/samsung/gts3/mba.mbn` and state `running`. QRTR
reported Location PDS v2, QMI LOC returned `msb` and all configured NMEA types,
and rmtfs/tqftpserv logged a successful `server_check.txt` transfer. A bounded
position and satellite request returned no fix before cancellation; that keeps
the acquisition item open. The full report, including the post-pivot identity,
mount table and automatic fastboot return, is:
`artifacts/roadmap-7.3/gnss-ram-20261108/auto-v60-20261110T044342Z/`.

A second v60 boot (v61 host collection) did not reach the debug shell and did
not return to fastboot within the 300-second host observation window. USB
enumerated transiently as Android `18d1:d00d`, then disappeared; no ADB,
fastboot or network route remained. The host therefore required a manual
reboot to restore the test state. This is recorded as a recovery failure and
keeps repeat MSS acceptance open:
`artifacts/roadmap-7.3/gnss-ram-20261108/auto-v61-20261110T045054Z/`.

The runner now recognizes the generic lk2nd USB product `18d1:d00d` and may
reset only that enumerated device before retrying `fastboot`. This is a bounded
transport recovery for stale host USB handles; it is not a watchdog and does
not change the tablet's boot or persistent partitions.

v62 added an explicit initramfs inspection hold to separate modem startup from
the root handoff. The MSS service registry and Location PDS v2 were present,
and rmtfs/tqftpserv again logged the TFTP calibration check. An immediate
`qmicli --loc-get-position-report` and SV query against `qrtr://0` returned
`node with id 0 not found` in the early initramfs window; the later post-pivot
QMI mode/NMEA queries from v60 remain the authoritative service evidence. v62
still passed the read-only root, SSH, PID 1, supervisor and 249-second
automatic fastboot gate:
`artifacts/roadmap-7.3/gnss-ram-20261108/auto-v62-20261110T050629Z/`.

The r9 Bluetooth package was exercised with the same unattended principle. The
host runner accepted both direct extlinux reboot and a fastboot return followed
by `fastboot boot`, retained a PID and snapshot, and completed twenty cycles
without a manual reset. The final tablet state remained a running 7.3.1 system.
The run recorded 15 PASS and 5 transient Bluetooth FAULT cycles; see
`artifacts/roadmap-7.3/bluetooth-auto-20261110T060000Z/`.

## Reset action and boot-mode selection

Current measured destination: the normal-r2 read-only RAM cycle at
`artifacts/roadmap-7.3/readonly-r2-cycle-20261111T002227Z/` passed direct-root
handoff and observed automatic return to installed r1 after 275.535 seconds.
The candidate boot ID was `bfc0d415-0b24-4521-b5d6-c8e53204b908`; the recovered
installed boot ID was `40c0ce08-7afd-4a29-9ee5-1c8331f47a91`. This is software
reset recovery to Linux, not a fastboot destination or permission to repeat
kexec. Consecutive unattended RAM boots remain unavailable in this state.

The generic runner now records reset destination separately and rejects an
unchanged boot ID as Linux recovery evidence. It uses USB SSH during direct-init
because Tailscale services are absent there, and the installed-system alias
only for recovery observation. Seven fake-transport tests cover the decision
logic; no hardware watchdog or complete kernel-lockup coverage is implied.

A later independently initiated reboot reached installed r1 with boot ID
`368b1c5c-5d01-4c78-8258-f18493abf5d5`: USB SSH responded while the Tailscale
alias initially timed out; both responded on the subsequent read-only check.
The runner now probes USB first and the installed-system alias second for
reset observation. Both require a valid boot ID different from the candidate;
an unchanged candidate, transport timeout or missing identity cannot pass.
Eleven host-cycle tests pass, including USB-only recovery and fallback paths.
Evidence: `artifacts/roadmap-7.3/recovery-network-fallback-20261111T004435Z/`.
No diagnostic boot was issued during this observation.

The read-only audit at
`artifacts/roadmap-7.3/reboot-route-source-audit-20261110T180230Z/` corrects an
earlier incomplete scan of `/sys/class`. The live symlink target
`/sys/class/reboot-mode/qcom-pon/reboot_modes` exposes `bootloader`, `recovery`
and `normal`, with DT values `0x02`, `0x01` and `0x14`. The qcom-pon driver
selects the reason; `syscon-reboot` PS_HOLD separately performs the reset.

The documented lk2nd base commit
`fd380ac637d1af38598e3f3c5321d4c962b96315` enables
`USE_PON_REBOOT_REG=1` for msm8996. Its aboot reads the PON reason and selects
fastboot for `0x02`. That same value already entered Samsung Download before
lk2nd on this tablet. Linux ignores unknown reboot-mode strings rather than
assigning a new code, so guessing `fastboot` is not a supported alternative.
The installed build contains dirty device additions that have not been
reconstructed; the source comparison covers only its documented base.

`CONFIG_KEXEC=y` and live `kexec_load_disabled=0` expose another investigation
path. The native aarch64 `kexec-tools` 2.0.32 package was inspected and a
bounded tablet probe loaded the read-only candidate through the legacy syscall
(`/sys/kernel/kexec/loaded: 0 -> 1`) and unloaded it (`1 -> 0`) without invoking
`kexec -e`; the tablet boot ID stayed unchanged. The probe is implemented by
`tools/t825-kexec-load-audit.sh` and archived at
`artifacts/roadmap-7.3/kexec-route-audit-20261110/`. It reported four valid
segments. The loader could not read `/proc/kcore` to resolve `_text`, but this
did not prevent a successful load. This proves only image admission and
cleanup: kernel handoff, reset destination, root transition, SSH and autonomous
recovery remain unvalidated. No kexec execution, PMIC/MMIO write or persistent
boot-file change was attempted in that probe. A subsequent guarded execution
attempt is recorded in
`artifacts/roadmap-7.3/kexec-cycle-20261110T191300Z/`: the load succeeded and
`kexec -e` was called, but the host observed no SSH, ADB or fastboot for 360
seconds. USB remained `04e8:6863` without carrier and repeated USB resets were
logged, so the candidate supervisor was not proven to run. Manual restoration
has since returned installed r1 and SSH. The runner is now disabled before
device access pending validated pre-entry recovery. Its preserved experimental
USB teardown also needs repair: it stops the gadget in one SSH command and
tries another connection to execute kexec, potentially removing its own route.

The review added `install/make-kexec-proof-bundle.sh`, which builds a minimal
candidate containing only BusyBox, the static supervisor and a tmpfs init. Its
offline validator is `tools/test-t825-kexec-proof-bundle.py`. The candidate
does not mount the installed root, boot, modem or EFS volumes. A fastboot return
alone cannot prove candidate entry or supervisor execution, because panic or an
old-kernel reset could produce the same observation. It must remain classified
as recovery observed with proof unobserved until a candidate marker is captured.
The minimal image also cannot recover a failure before its supervisor starts.
An independent pre-entry recovery mechanism remains required. The current
artifact is `artifacts/roadmap-7.3/kexec-proof-candidate-20261110b/`. It has
not yet been executed on hardware. Both `tools/t825-kexec-proof-cycle.sh` and
`tools/t825-kexec-cycle.sh` stop with `BLOCKED_PREENTRY_RECOVERY` before device
access, with no environment override. Fake-transport tests verify that the
entry points cannot reboot a tablet out of fastboot or launch the experimental
runner. Offline tests do not establish the missing recovery mechanism.

## Hardware watchdog investigation

The current LTE DTB has no watchdog node, although `CONFIG_QCOM_WDT=y`.
The PC's SP5100 `/dev/watchdog0` belongs to the host and must never be used as
a tablet recovery mechanism.

The original Samsung DTB has `qcom,wdt@9830000`, compatible
`qcom,msm-watchdog`, size `0x1000`, interrupts SPI 28/29, bark 15,000 ms,
pet 10,000 ms, `qcom,ipi-ping` and `qcom,wakeup-enable`. The local evidence is
`artifacts/sm-t825-readonly-20261101-082459/analysis/dtb/boot/dtb-2.dts`.

Linux 7.3.1 `drivers/watchdog/qcom-wdt.c` matches `qcom,kpss-wdt` and timer
variants, not that downstream compatible. Its KPSS register layout uses reset
`+0x4`, enable `+0x8`, status `+0xc`, bark `+0x10`, bite `+0x14`. The mainline
binding requires a clock; the stock node alone does not supply a validated
mainline clock/ownership/reset configuration. The driver also stops an active
watchdog during suspend, so suspend-stall coverage needs separate analysis.
Do not copy the stock node and assume a working safety mechanism.

The reproducible audit is saved as `artifacts/roadmap-7.3/watchdog-audit.json`
and generated by `tools/audit-t825-watchdog.py`. It checks the actual Linux
7.3 match table, the stock Samsung node and the current board DTS, and fails
closed with `do-not-enable-unvalidated-watchdog` until clock, ownership,
register semantics and reset destination are validated on hardware.

The board's reboot patch documents Samsung PSCI SYSTEM_RESET hanging and uses
PS_HOLD at `0x004ab000`, with PM8941 reset-type preparation, for normal reboot.
It also warns that the secure watchdog can leave the tablet needing a forced
restart. A Qualcomm watchdog bite must be tested for its actual reset result;
it is not interchangeable with the observed PS_HOLD route.

A separate [PM8994 source and lifecycle review](pm8994-watchdog-investigation.md)
finds matching downstream PON watchdog control offsets. Live identity confirms
PM8994 and a PM8916-compatible PON parent, but the watchdog driver is disabled.
The source review also identifies indefinite inherited-watchdog feeding with
the current core configuration and watchdog stopping during suspend. These
must be resolved before claiming early-boot or suspend coverage. No hardware
watchdog was enabled during the investigation.

## Remaining acceptance gates

1. [x] Repair/observe USB and SSH across the full installed-system transition,
   retaining the independent recovery deadline. v60 verified the replacement
   PID 1, read-only root, SSH and the original supervisor; v62 repeated the
   same gate with an explicit MSS inspection hold.
2. [x] Repeat the full test with MSS enabled after that prerequisite passes.
   v60 and v62 provide the MSS-enabled evidence; satellite acquisition remains
   open because no fix was observed.
3. Validate watchdog register layout, clock, non-secure access/ownership and
   reset route against matching downstream source and firmware, then test
   deliberate expiry without a kernel lockup before any harder failure test.
4. Test full-kernel and suspend stalls only after a working hardware route or
   external reset controller is established.

Software supervision covers failures while the scheduler and reset route work.
Earlier boot hangs and complete SoC lockups require an already armed hardware
watchdog or external control. USB power cycling alone cannot reliably reset a
tablet with an internal battery. An isolated button relay/actuator could emulate
the physical reset sequence, but no such controller is present in this setup.

Fastboot destination currently depends on the existing boot-selection state.
The supervisor performs a normal kernel reset; it does not alter persistent
boot selection. A detached host process survives terminal loss, while the
tablet deadline continues even if the host is disconnected or restarted. The
host must be running again to launch the next image.
