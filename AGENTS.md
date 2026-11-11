# Project instructions

## Autonomous SM-T825 test execution

- Every test that may reboot the tablet, change its boot mode, or lose its
  connection must include a host-controlled recovery mechanism and continue
  without requiring the user to remain near the device.
- Prefer remote SSH/ADB commands that do not modify boot files, an early
  initramfs supervisor, a validated tablet hardware watchdog, and automatic
  polling of `fastboot`, USB, SSH and telnet. The authorized extlinux exception
  below permits a guarded replacement for the old `t825-reboot-fastboot`
  helper. For planned successful cycles, launch the
  next `fastboot boot` when the tablet enumerates again; stop and inspect
  evidence after diagnostic or recovery failure.
- Test scripts must have timeouts, record the final state, and leave the tablet
  recoverable. If diagnostic USB connectivity is lost, try the watchdog and
  automatic return to fastboot first; do not wait indefinitely or depend on
  manual intervention between cycles.
- If lk2nd is visible only as USB product `18d1:d00d`, the host may perform a
  bounded reset of that single USB device and retry `fastboot`; do not reset
  arbitrary USB devices or treat this as a substitute for a tablet watchdog.
- Long-running host orchestrators must be detached from the interactive shell
  (for example with `setsid`/`nohup`), write a timestamped log and retain a PID
  that can be polled after the operator leaves the workstation. A reconnecting
  USB device must be consumed automatically by the same process.
- Snapshot the orchestrator, collectors and protocol helpers into the private
  report directory before a hardware boot. Execute those copies and record
  their hashes. Never edit a script that a running test is still reading.
- Never use `fastboot flash`, `heimdall flash`, or alter EFS, modemst1/2, fsg,
  fsc, the bootloader, or other persistent partitions to automate a test,
  except for the narrowly authorized extlinux rename and restoration below.
  Kernel diagnostics must use `fastboot boot` only.
- RAM boot alone does not prevent filesystem writes. Disable installer
  deletion, resize and repair calls. Direct-init diagnostics must protect the
  root block device with a verified read-only flag before mounting, disable
  journal replay, and skip the installed boot volume. Never work around a
  failed read-only mount by mounting the installed root read-write.
- Request a manual reboot only when no remote route or functional watchdog can
  recover the device. Record evidence of the enumeration failure and why
  automation could not proceed in the report.
- Arm the recovery deadline immediately after proc/sys/dev/run mounting, before
  module loading, udev, remoteproc startup or diagnostic probes. A shell timer
  started after a potentially blocking operation does not satisfy this rule.
- Verify recovery across the real root transition. Files included in initramfs
  do not automatically exist after switch_root, and pmOS kills `sh` processes
  during cleanup. Carry runtime files through tmpfs and keep recovery independent
  of the discarded root, systemd startup and the diagnostic connection.
- A successful SSH marker must not permanently cancel recovery. Use bounded
  leases for longer work and observe the final reset even after a failed test.
  Distinguish transport/diagnostic failure from automatic reset success.
- Do not claim coverage of full kernel/SoC lockups from a software timeout test.
  Validate the tablet's hardware watchdog and reset destination separately;
  never operate the host computer's watchdog as a tablet recovery mechanism.

## Authorized extlinux exception (2026-11-11)

The user explicitly authorized remote Arch-to-lk2nd-fastboot entry by renaming
`/boot/extlinux/extlinux.conf` to `extlinux.conf.fastboot` and restoring it.
This authorization persists across sessions and does not require confirmation
for each cycle. It does not authorize flashing or other persistent changes.

- Before the rename, identify this SM-T825 and its ext2 `cache` filesystem,
  save the original file and SHA-256 on the host, reject symlinks/conflicting
  backup files, and validate and snapshot the RAM restoration image and tools.
- Run a detached, bounded host controller that records entry, diagnostic
  failures, restoration and final boot state. Keep the original bytes intact.
- A dedicated restoration step may mount only the identified boot filesystem,
  initially read-only, verify the saved hash, briefly remount it writable for
  the reverse rename, sync and unmount. Do not repair or rewrite the filesystem,
  alter other boot files, or mount the installed root writable for diagnostics.
- Preserve the independent RAM recovery deadline. A diagnostic failure must
  lead to bounded restoration when transport returns, not another experiment.
- Verify the restored hash, absence of the temporary filename and a new Arch
  boot ID. Report any restoration failure explicitly; never claim that a
  software timer covers a complete kernel/SoC lockup.
