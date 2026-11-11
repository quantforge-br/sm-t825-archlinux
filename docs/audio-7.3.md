# WCD9335 capture investigation on the SM-T825

Updated: 2026-11-11. Microphone PCM delivery works, but recurring TX1 overflow
interrupts remain unresolved. No codec correction is accepted for deployment.

## Evidence

The installed kernel is `7.3.1-t825 #2-postmarketos-qcom-msm8996` (r1).
The earlier single-UCM-context route matrix delivered 48,000 stereo frames
per capture but reported new TX1 overflow in 5/10 and later 10/20 cycles.
Those `arecord` transfer phases include stop and close, so they cannot
distinguish active recording from stream teardown.

The new `tools/t825-audio-mic-phases.sh` collector separates UCM enable,
PCM open, hardware parameters, prepare, active read/drop, close and UCM disable.
It records monotonic call boundaries for read and drop without inserting
log I/O, sleeps or PCM metric reduction between them. Actual PCM parameters
are retained; xrun recovery is never attempted silently. Samples remain in
memory and only frame counts and channel levels are saved.

The report `artifacts/roadmap-7.3/audio-mic-phases-20261110T165846Z/` contains:

| Evidence | Observation |
|---|---|
| Negotiated parameters | 48 kHz, S16_LE stereo, 960-frame period, 7,680-frame buffer |
| Capture | 48,000 frames; no ALSA error; PCM still RUNNING before drop |
| Read call | Monotonic 18488.062418 to 18488.920950 |
| New kernel fault | `[18488.860752] ... overflow error on TX port 1, value 5` |
| Drop call | Monotonic 18488.921021 to 18488.927411 |
| Close and route disable | No new fault observed |
| Restoration | Exact mixer snapshot match; boot ID unchanged; all PCM closed |

An offline audit verified log continuity for all eight phases, preserved input
hashes and measured the printk timestamp 60.269 ms before drop:
`artifacts/roadmap-7.3/audio-mic-timing-audit-20261110T170636Z/analysis.json`.
Use `CLOCK_MONOTONIC` for this comparison: `CLOCK_BOOTTIME` includes earlier
suspend time and has a different offset. Printk timing describes when the
driver reported an IRQ, not the precise hardware event time. Deferred IRQ
handling and the collector's negotiated geometry limit causal conclusions.

## Source findings

The retained source audit is
`artifacts/roadmap-7.3/audio-source-audit-20261110T123521Z/`.
`sound/soc/codecs/wcd9335.c` defines overflow as bit 0, underflow as bit 1
and port closed as bit 2. Status `5` therefore combines overflow and port
closed. The handler logs the fault, disables the affected port interrupt and
clears status; it does not restart the stream.

The source also ignores the result of `wcd9335_slim_set_hw_params` and the
SLIMbus prepare, enable, disable and unprepare calls. These error paths need
review, but no evidence yet shows that one of those calls failed during the
observed overflow. Propagating an error cannot by itself establish a fix for
the current fault.

The pinned SLIMbus stream implementation makes the gap more concrete:
`slim_stream_prepare()` discards each connect transaction result, while
`slim_stream_enable()` discards define/content/activate results and
`slim_stream_disable()` discards per-port deactivate/remove results. The
read-only audit records the exact source lines and hash in
`artifacts/roadmap-7.3/audio-slim-stream-audit-20261111T121500Z/analysis.json`.
This is an evidence-backed fix candidate for a later diagnostic build, not a
production change: the first-fault run must show whether any discarded return
is negative before error propagation is attempted.

Run `python3 tools/test-t825-slim-stream-audit.py` to verify the audit against
the pinned source. `tools/audit-t825-slim-stream.py` emits a structured report
and deliberately marks `production_fix_accepted` false.

Read-only inspection found ASoC DPCM state and mixer controls. The debugfs
regmap range files named `WCD9335` and `WCD9335-IFC-DEV` returned zero bytes;
their presence does not establish access to port registers. No direct MMIO
or unreviewed codec register writes were used.

The installed r1 kernel was also checked read-only for runtime instrumentation.
Debugfs is mounted, but it has neither `dynamic_debug/control` nor tracefs
audio/SLIMbus events. The loaded WCD9335, Q6 and SLIMbus modules therefore
cannot expose the first-fault register/API state without changing the kernel.
Evidence: `artifacts/roadmap-7.3/audio-runtime-trace-audit-20261110/`.

## Running the focused collector

Launch the host wrapper detached, with a new private report directory and
timestamped host log. It snapshots its scripts and shared validator, holds the
tablet test lock, saves the mixer and arms a separate 120-second restoration
timer before UCM changes. The collector has a 75-second service deadline and
an `ExecStopPost` mixer restore. The host retains PID and final status, restores
the mixer after failure and verifies exact snapshot equality before cancelling
the timer. A kernel fault stops further repetitions; failed or missing evidence
cannot pass. These are software recovery measures, not full kernel-stall
coverage.

The first prototype refused a too-small negotiated buffer before capture
(`audio-mic-phases-20261110T123215Z/`) and restored the mixer. A subsequent
launch stopped on systemd's degraded status without starting the collector
(`audio-mic-phases-20261110T123531Z/`); the wrapper now records that status
without treating a historical failed diagnostic unit as an audio prerequisite.
Neither run is capture acceptance.

Run `python3 tools/test-t825-audio-mic-phases.py` for offline lifecycle and
failure-cleanup tests. The shared validator rejects both codec overflow and
underflow even when every PCM frame was delivered. Acoustic validation of
both microphones, speakers and physical CTIA insertion remains a separate
roadmap gate.

## Private diagnostic kernel preparation

Patch `0205-asoc-wcd9335-port-diagnostics.patch.disabled` is included in the
package's source/checksum list but excluded from normal patch application.
`T825_AUDIO_DIAGNOSTIC=1`, or `.t825-enable-audio-diag` in an isolated package
directory for pmbootstrap, explicitly applies it and selects
`CONFIG_LOCALVERSION="-t825-audiodiag"`. Preparation refuses simultaneous MSS
and audio diagnostics before changing the source/config. Normal preparation
retains `-t825` and applies neither diagnostic patch.

The module parameter `snd_soc_wcd9335.port_diagnostics=1` enables additional
configuration reads and logs; it is off by default and read-only after module
load. Output is limited to 128 records per module load. Diagnostic records
include actual TX/RX port configuration, channel maps, interrupt-enable state,
each register-read result, requested watermark, SLIMbus API returns and decoded
fault source before the existing IRQ handler disables/clears the fault. The
original trigger call order, ignored returns and IRQ handling are preserved to
isolate observation from a proposed fix. Extra reads and logging perturb timing.
Budget exhaustion or missing records cannot establish absence of a fault.

Local validation is archived at
`artifacts/roadmap-7.3/audio-portdiag-build-20261110T175738Z/` (object scope) and
`artifacts/roadmap-7.3/audio-portdiag-full-build-20261110/` (complete ARM64
kernel, modules and T825 DTBs, with status 0):

- Patch application dry-run with zero fuzz against the prepared 7.3.1 source.
- ARM64 WCD9335 object compilation with `KCFLAGS=-Werror` and the distinct
  `7.3.1-t825-audiodiag` release.
- Complete `Image.gz`, modules and both T825 DTBs built from the private
  patched tree; the diagnostic candidate was subsequently loaded through the
  guarded RAM controller and remains excluded from production.
- Five package-preparation tests for production, separate opt-ins, mixed-mode
  refusal before edits, and checksum binding.
- A host stub harness running the actual patched helpers with real header
  address expressions: default-off does no reads, RX/TX select the correct
  configuration registers, read errors stay explicit and the 128-record cap
  stops further reads/logging.
- Checkpatch with no errors or warnings (sign-off check omitted for this
  private diagnostic patch).

To rerun the helper harness on a private patched tree, use
`python3 tools/test-t825-wcd-port-diagnostics.py --kernel-source /path/to/linux`.
Package isolation is checked by `python3 tools/test-t825-kernel-diagnostics.py`.
No diagnostic module has been installed or loaded on the tablet. A complete
kernel build now exists, but packaging it into an accepted boot image still
requires the same read-only RAM and independent-recovery gates. Preserve
overflow and port-closed reporting until the first-IRQ configuration and
SLIMbus return codes explain the failure.

An unaccepted audio RAM candidate was assembled from the read-only normal root.
It carries the `7.3.1-t825-audiodiag` module tree, the instrumented
`snd-soc-wcd9335.ko.zst`, and the command-line parameter
`snd_soc_wcd9335.port_diagnostics=1`. The LTE MSS node remains disabled, the
root member protections and direct PID 1 checks are retained, and the image
fits lk2nd with a 4,500,992-byte margin. Offline validation passed at
`artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261110b/`; it has not
been executed or run on the tablet. Its kernel/initramfs/DTB were nevertheless
accepted by the bounded legacy-kexec load/unload probe (`0 -> 1 -> 0`), with no
`kexec -e`; the tablet boot ID remained unchanged. Evidence is under
`artifacts/roadmap-7.3/kexec-route-audit-20261110/audio-repro-20261110/`.

## Downstream comparison and diagnostic RX address correction

The pinned downstream reference at
`awesometic/android_kernel_samsung_msm8996`, commit
`f48aec90fcebf4615fdee4a8abac7339930db856`, uses the same 12-byte watermark
and reports overflow together with port-closed status. This comparison does
not justify changing the watermark or suppressing status `5`. Its close path
waits for channel-close notifications; mainline uses a different SLIMbus stream
lifecycle. A sequencing hypothesis still needs first-fault hardware evidence.

The comparison exposed an error in private patch 0205's RX instrumentation:
SLIMbus stream ports are 16..28, while IRQ RX indices are 0..12. Register
macros expect the stream numbering, but interrupt-enable banks expect the
local numbering. The old helper used one value for both. IRQ RX2 therefore
read configuration at `0x32` instead of `0x42` and mapping at `0x148` instead
of `0x188`; stream RX2 selected the wrong interrupt-enable bank.

The corrected helper accepts RX-local indices, adds 16 for configuration and
mapping reads, and leaves the interrupt-enable index local. The stream caller
subtracts 16; the IRQ caller already supplies a local index. TX behavior is
unchanged. The test now executes both actual helper functions and checks
independent downstream address values, including RX2/RX12 stream-versus-IRQ
equivalence and the upper interrupt bank. It fails on the archived old patch
and passes on the correction. This repairs observation, not the microphone
overflow itself. The core `slim_stream_prepare()` also ignores individual
connect-operation returns, so a logged `prepare_rc=0` cannot prove every
underlying bus transaction succeeded.

Evidence, source URLs/hashes, regression failure, five package-isolation tests,
zero-fuzz patch application, checkpatch and the successful complete ARM64 build:
`artifacts/roadmap-7.3/audio-downstream-20261110T231416Z/`.

Use `artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261110d/` for the
next gated diagnostic, superseding candidate b's incorrect RX instrumentation.
Candidate c was rejected because unstripped debug modules exceeded the memory
budget. Candidate d strips module debug symbols and passes the image validator
with a 4,500,992-byte margin. Its image SHA-256 is
`66602d408d5fc38dc4e791a99a5a36893c59566d6df8e572d86951660d0a0a58`.
The packed codec module matches the rebuilt module byte-for-byte. The builder
now runs the image validator before writing a successful decision. No candidate
from this comparison has been loaded or booted; recovery and audio hardware
acceptance remain open.

## Bounded capture in the direct-init RAM image

The host runner now supports `--kind audio --audio-probe`. It snapshots
`t825-audio-ram-probe.py`, the existing microphone lifecycle collector and its
validation dependency before boot. After verifying the read-only handoff, it
requires the exact audiodiag kernel/boot ID, original supervisor PID/hash,
active codec instrumentation, both protected Btrfs members, a volatile `/run`
and at least 100 seconds remaining before the unchanged supervisor deadline.
No workload runs if any prerequisite fails.

The remote collector stores its files only in a private `/run` directory and
runs one existing `Mic` lifecycle capture with a 45-second process timeout.
It restores and compares the mixer afterward, including after a capture error
or timeout. The independent reset remains armed if the collector, restoration
or connection fails; no recovery lease is extended. PCM samples are processed
in memory and discarded. Saved outputs are metrics, mixer state and kernel
logs across UCM enable, open, parameters, prepare, active interval, close and
disable. An observed fault stops the probe; successful PCM transfer is not
acoustic acceptance or evidence that a codec warning was fixed.

This path does not require systemd, unlike the installed-system microphone
wrapper. Nine host-cycle tests, three remote-probe tests (including multiple
unsafe states and restoration failures) and thirteen existing capture tests
pass. The candidate image validator also passes. Evidence:
`artifacts/roadmap-7.3/audio-ram-probe-offline-20261111T003207Z/`.
Hardware execution is now demonstrated by candidate f in the instrumented
fault report below. Normal r2 also passed the same direct-root handoff and
returned automatically to installed r1.

## First audio RAM cycle: provider initialization gap

The above pending state was superseded by the 2026-11-11 00:47 UTC run:
`artifacts/roadmap-7.3/audio-ram-cycle-20261111T004744Z/`.
Candidate d booted the exact audiodiag kernel, passed the protected root/PID 1/
supervisor checks, then blocked the microphone probe before any mixer or PCM
operation: `/proc/asound/cards` reported no soundcards and the WCD9335 module
parameter was absent. The host recorded overall `FAIL`, diagnostic handoff
true, audio probe false and reset recovery true. Installed r1 returned in
266.664 seconds via USB SSH, boot ID `b95ff002-953e-4698-a868-a24e69a94dae`.
No first-fault codec evidence was produced, and reset returned to Linux rather
than fastboot.

The image omitted `qcom_q6v5_pas` (ADSP startup), `q6afe-dai` and the RT5508
amplifier provider. These are device-topology dependencies that a recursive
`modules.dep` walk starting from WCD9335/Q6ASM does not discover. The restored
installed system has these providers loaded, a running ADSP and an ALSA card;
its ADSP firmware is available in the installed root without a firmware mount.
This comparison identifies a diagnostic preparation defect, not an audio
driver fix or a proven complete startup sequence.

The builder now seeds all three providers and the validator checks them plus
every packaged module's dependency closure. It also writes the payload
manifest before invoking the validator, fixing the manifest ordering after
checksum validation was added. Candidate d now fails this strengthened check;
intermediate candidate e still lacked RT5508 and also fails. The new candidate
`artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261111f/` passes with image
SHA256 `b8c15dfdb285bdea7950253140fabbf4152679dfca570142e4436f3d1415ca82`.
It has not booted. Direct PID 1 does not start installed udev/systemd services;
the next run uses explicit provider loading as described below. Do not retry
unchanged candidate d.

## First instrumented hardware fault

The corrected candidate `audio-diagnostic-ram-candidate-20261111f` was loaded
through the authorized detached fastboot controller on 2026-11-11. The exact
diagnostic kernel reached the installed read-only root, retained the recovery
supervisor and started all audio providers. The first bounded capture delivered
48,000 stereo frames, then the active interval recorded:

```text
wcd9335_slimbus_irq: overflow
portdiag stage=irq dir=TX port=1 source=0x5 overflow=1 underflow
```

The probe stopped at capture 1 of the requested 3, restored the mixer byte for
byte and left the supervisor armed. The tablet reset to fastboot and the host
restored the original `extlinux.conf` before verifying a new Arch boot ID.
Evidence: `artifacts/roadmap-7.3/authorized-audio-three-captures-20261111T104500Z/`.
This is a controlled reproduction with phase and port diagnostics. It does not
yet establish the register-level cause or a safe driver fix; both microphones,
speaker paths and CTIA insertion remain separate acceptance work.

## Provider startup implementation

The probe now checks the original supervisor and protected root before any
module load, with at least 160 seconds remaining on its unchanged deadline.
It requires the candidate module tree to be a read-only tmpfs bind mount and
validates ELF32 MDT headers plus the size/presence of each nonempty split
firmware segment. ADSP and SLPI are both checked because the PAS driver binds
both enabled processors. A read-only check against the restored installed
firmware passed; file hashes are retained privately in
`artifacts/roadmap-7.3/audio-provider-preparation-20261111T005604Z/`.

The module allowlist is RT5508, WCD9335, APR, Q6AFE DAI, Q6ASM DAI, SLIMbus
NGD, APQ8096 machine and Q6v5 PAS, plus their symbol dependencies. Each command
has at most four seconds; total loading/readiness is bounded to 45 seconds.
`modprobe -C /dev/null --ignore-install` excludes installed configuration/hooks,
and WCD9335 receives `port_diagnostics=1` explicitly. The probe waits for card
ID `S3`, the codec diagnostic parameter and capture device `pcmC0D2c`, then
rechecks root/supervisor identity and requires 100 seconds before capture.
Startup logs survive as text under `/run`; no firmware files are copied or
persistent partitions mounted. MSS remains disabled.

Seven probe tests, eleven host-cycle tests and thirteen capture tests pass.
The tests cover absent firmware segments, invalid deadlines, failed loads,
readiness timeout, restoration failure and reset observation after failure.
Actual provider startup and first-fault capture are now demonstrated by the
instrumented hardware report below. An offline pass alone would not establish
DSP/codec readiness.

## Candidate f: first successful instrumented capture

The pending provider-startup check above is now satisfied by
`artifacts/roadmap-7.3/audio-ram-cycle-20261111T021714Z/`. The frozen runner
booted candidate f, verified the exact audiodiag kernel, protected root and
original supervisor, completed provider preparation, and captured 48,000
stereo S16_LE frames at 48 kHz. Both channels had zero clipped samples; RMS
levels were -67.51 and -69.09 dBFS. No raw samples were saved. Mixer restoration
matched the pre-capture state byte for byte.

All eight observed lifecycle phases completed without a matched kernel fault
or log rotation. Nineteen port diagnostic lines in the phase deltas show TX
ports 0/1, channel numbers 128/129, configuration `0x5`, mapping low `0x3`,
mapping high `0x0`, and interrupt enable changing from `0x0` after parameters
to `0x3` at trigger. Reported register-read, allocation, hardware-parameter,
prepare/enable and disable/unprepare return values were zero. As previously
noted, the aggregate SLIMbus prepare return does not validate each underlying
bus operation. See `port-diagnostics.txt` and `audio-summary.json` in the report.

The independent supervisor reset the tablet, and USB SSH observed installed
r1 with a new boot ID after 266.036 seconds. The terminal result is
`PASS_HANDOFF_AUDIO_PROBE_AND_RESET`, destination `linux`; the process exited.
There was no unattended next RAM cycle. This validates diagnostic startup,
one PCM transfer, restoration and software recovery. It does not establish
acoustic quality, individual microphone routing, repeated reliability or a
fix for the intermittent overflow: this capture did not reproduce the fault.
The next audio experiment must retain the first fault's configuration and
compare its lifecycle boundary with this passing control.

The authorized experiment used `--audio-probe --audio-repetitions 3` with the
same candidate f. It ran at most three lifecycle captures in one RAM boot,
stops at the first observed kernel fault or collection error, and retains the
existing 45-second collector timeout and 240-second recovery deadline. It does
not unload/reload the codec to renew its diagnostic log budget. The wrapper
requires the completed count to equal the requested count before reporting
PASS, then restores the mixer and observes the final reset regardless of the
capture result. The single-capture mode remains the default.

Thirty-six offline tests pass (12 host-cycle, 9 RAM-probe, 15 lifecycle tests),
including injection of a first-capture overflow into the actual lifecycle loop:
the PCM closes, Mic is disabled and no second capture starts. Evidence:
`artifacts/roadmap-7.3/audio-three-captures-offline-20261111T022504Z/`.
The hardware sequence stopped at the first reproduced fault (1/3), so it does
not satisfy the twenty-route-cycle or acoustic acceptance gates.


## SLIMbus transaction diagnostic: first hardware result

Patch `0206-slimbus-stream-transaction-diagnostics.patch.disabled` extends the
private audio build only. It is checksum-bound and applied after 0205 under the
existing audio opt-in, with production and MSS preparation unchanged. Its
`slimbus.transaction_diagnostics=1` parameter is default-off and read-only.
It records at most 128 transaction/callback results per module load, preserves
message order and returns, and captures the requested opcode before a
controller can rewrite it. No new bus transactions or register reads are added.

This corrects the scope of the earlier stream-source audit: MSM8996 NGD supplies
`ctrl->enable_stream`. The generic define/content/activate path is therefore
not the active enable path on this tablet. Connect and teardown transfers still
use the generic stream helpers; the NGD enable callback's aggregate return is
recorded separately. The earlier lexical audit identifies ignored returns but
cannot establish which branches execute, or that those returns caused overflow.

Offline evidence: `artifacts/roadmap-7.3/slimbus-transaction-diagnostics-20261111T112642Z/`.
The actual original/patched stream functions were compiled against host stubs
and compared across 126 combinations of bus failure, controller callback
failure and diagnostic enablement. Return values, transaction sequence/payloads
and states matched; default-off, exhausted-budget and rewritten-opcode checks
passed. ARM64 object and SLIMbus module builds passed with `-Werror`, together
with checkpatch, five package tests, twelve RAM-probe tests and fifteen capture
lifecycle tests. This was a module rebuild against the existing audio build,
not a complete new kernel build.

Candidate g uses the existing audio Image/DTBs and the rebuilt `slimbus.ko`:
`artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261111g/`, image SHA-256
`12437f0a95e37906d11f03ade4ffaa07064c7b2ec94cc324279f99c1da048c57`.
The builder's explicit `T825_SLIM_TRANSACTION_DIAGNOSTICS=1` adds the parameter;
the image validator checks its module parameter and release. The RAM probe
loads SLIMbus with that option before codec dependencies and refuses capture if
the requested parameter is not active. Historical codec-only images remain
supported. The validated lk2nd memory margin is 4,455,936 bytes.

The authorized hardware run is
`artifacts/roadmap-7.3/authorized-audio-transaction-diagnostic-20261111T134500Z/`.
It reproduced TX1 overflow on capture 1/3 after delivering 48,000 stereo frames.
All eleven transaction records report `rc=0`: two connects, one NGD enable,
begin/reconfigure teardown, four deactivate/remove and two disconnect calls.
The complete phase logs are continuous and the mixer restoration is identical.
The overflow printk timestamp is 20.688891 s; the monotonic drop call spans
20.389508689 to 20.701106814 s. Thus this report was emitted during drop, after
the logged disconnects, 299.382311 ms after entering drop.

No ignored negative stream return was observed in this reproduction, so error
propagation is not justified as its presumed fix. API return success is not
proof of firmware acknowledgements or wire-level state. Additional logging
perturbs timing, deferred IRQ service is possible, and earlier active-read
faults remain valid. Next compare codec/AFE/NGD teardown and port-close
acknowledgement with lower-overhead instrumentation; preserve both overflow and
port-closed bits. Acoustic and repeated-route acceptance remain open.

The complete authorized cycle finished with `FAIL_DIAGNOSTIC_ARCH_RESTORED`.
The diagnostic supervisor returned to fastboot after 254.588 seconds; the
dedicated restoration image reversed the guarded rename and reset autonomously.
Installed r1 returned over SSH with boot ID
`dc093cd4-ccbb-449a-8914-c2d4ebbd0b15`, original extlinux SHA-256
`03285dfe1f2016a4cf967fe22f9c68d8663801a61e1c07050eff6fa36ed2a397`
and no temporary filename. `after.json` and `result.json` record these checks.
No manual reboot was needed. Diagnostic failure and successful software
recovery remain separate results; this does not validate a hardware watchdog.

## NGD teardown dispatch and ownership

The built candidate's `qcom_slim_ngd_xfer_msg()` returns zero immediately for
CORE opcodes from `BEGIN_RECONFIGURATION` (`0x40`) through `RECONFIGURE_NOW`
(`0x5f`), before allocating a transport buffer. This includes the logged
deactivate (`0x55`) and remove (`0x58`) calls. All six such records in candidate
g therefore describe locally bypassed operations, not transmitted teardown
requests. NGD installs `enable_stream` but no `disable_stream` callback.

The four connect/disconnect records follow a different path: NGD rewrites
CORE connect-source/sink/disconnect to user messages `0x2c/0x2d/0x2e`, allocates
a transaction ID and waits for TX and response completions. The receive path
routes generic ACK payloads through `slim_msg_response()`, which copies the
reply and signals completion. The transfer function does not inspect the
contents of its local reply buffer. A zero result consequently establishes
completion of those waits, not a decoded firmware status or port-close IRQ.
The remaining enable record is the aggregate result of the controller's
define/activate and reconfigure user-message sequence.

`tools/test-t825-ngd-transfer-source.py` compiles the entire actual transfer
function with host transport stubs and the source's numeric constants. It
passes 1,024 combinations of message type/opcode (32 bypassed core opcodes)
and 18 connect/sink/disconnect cases covering buffer allocation, transaction
ID allocation, post failure, TX timeout, response timeout and success. The
enumerated-address rejection distinguishes fallthrough from early success.
The harness then classifies the eleven frozen hardware records as six bypassed,
four translated and one aggregate result. Evidence and source hashes:
`artifacts/roadmap-7.3/ngd-teardown-source-20261111/`. Stubs do not establish
DMA behavior, reply-payload semantics or real interrupt ordering.

The shutdown owners also differ from the downstream implementation:

- Current WCD9335 STOP calls `slim_stream_disable()` and then unprepare, which
  disconnects the codec ports. Its IRQ handler reports overflow/underflow and
  clears status, without a downstream-style per-DAI port-close waiter.
- Q6AFE's SLIMbus DAI has prepare/shutdown callbacks and no trigger callback.
  `q6afe_port_stop()` runs during shutdown (and re-prepare of an already started
  port), sends `AFE_PORT_CMD_DEVICE_STOP`, and awaits the APR response. The
  candidate g capture did not trace that call, so its position relative to
  the codec IRQ is still unmeasured.
- Downstream WCD9335 POST_PMD requests `SLIM_CH_REMOVE`, waits for `ch_mask`
  to clear via the `PORT_CLOSED` interrupt, and disconnects as a fallback on
  close failure. It still reports overflow when the closed bit is also set.
  This is evidence of a different close protocol, not a drop-in porting fix.

The downstream manager message format and ownership of channel removal were
resolved in the experiment below. A further bounded RAM capture should
timestamp Q6AFE stop, NGD response completion and codec port-close from a RAM
trace buffer, using already-read IRQ values and collecting after close.
This reduces synchronous printk perturbation and distinguishes scheduling
removal from port disconnect. Do not send generic reconfiguration messages to
NGD, add arbitrary delays, mask status `0x5`, or interpret all-zero stream
returns as proof of a completed channel teardown.

## Experimental NGD channel removal (0207)

The next source check resolved the downstream manager packet format. The
Samsung tree at commit `f48aec90fcebf4615fdee4a8abac7339930db856` implements
removal in `ngd_allocbw()`, through the controller's `allocbw` hook when
`slim_control_ch(..., SLIM_CH_REMOVE, true)` commits the removal list. Its core
reconfiguration commands are bypassed just like the current driver, but that
private callback sends the missing manager requests first:

| Request | Opcode | Payload |
| --- | --- | --- |
| Remove channels | `0x23` | `0x80 \| (client_laddr & 0x1f)`, TID, channel IDs |
| Commit reconfiguration | `0x24` | new TID, full client logical address |

`SLIM_CH_REMOVE` is enum value 2, encoded in bits 7:6 of the first byte. The
downstream generic ACK handler accepts bit `0x20` of the first reply byte and
sets `-EIO` when it is absent. This establishes source-level ownership and wire
format; the firmware's behavior still requires a protected hardware test.
Pinned downloads, URLs and hashes are in
`artifacts/roadmap-7.3/ngd-downstream-protocol-20261111/`.

Patch `0207-slimbus-ngd-channel-removal-experiment.patch.disabled` implements
those two requests as an experimental `disable_stream` callback. It registers
only when the read-only, default-false module parameter
`slim_qcom_ngd_ctrl.channel_removal=1` is enabled. Both requests use separate
transaction IDs, bounded completion waits and success-bit validation. Reply
buffers are cleared before each request so an empty second response cannot
reuse the first response's success. Invalid/oversized channel lists are
rejected, allocation/transport errors stop the sequence, and a negative
callback result now returns from the private stream-disable path. After a
successful callback, the existing generic state bookkeeping and NGD core
message bypass remain. No IRQ mask, arbitrary delay or retry is added.

The patch is included only in the separate audio build; production and MSS
preparation remain unchanged. Candidate h rebuilds `slimbus.ko` and
`slim-qcom-ngd-ctrl.ko` against the existing audio Image and module symbols.
It is not a full new kernel build. The builder requires both explicit
`T825_NGD_CHANNEL_REMOVAL=1` and `T825_SLIM_TRANSACTION_DIAGNOSTICS=1` flags.
The probe verifies the active NGD parameter and requires one successful
controller-disable record for each completed capture. Negative stream/codec
diagnostic returns now count as faults and stop the capture loop, even if no
overflow is reported. Mixer restoration and the independent reset are retained.

The actual removal and stream-disable functions pass 527 host cases, including
every possible ACK byte at both stages, exact two-channel payloads, buffer
bounds, allocation failures, transport failures, empty replies and callback
error propagation. The ARM64 module build passes with `-Werror`; checkpatch
passes with `--no-signoff` for this private experiment. Sixteen probe tests,
sixteen lifecycle tests, twelve read-only cycle tests, five package tests and
eleven evidence-classification tests pass.

Candidate: `artifacts/roadmap-7.3/audio-diagnostic-ram-candidate-20261111h/`.
Image SHA-256:
`5e9c181151edb1236cec02b2bd9068f72c2767eff90f3c836c64c71c38fd5492`.
Offline image validation preserves the read-only root, disabled MSS and original
240-second supervisor, with 4,455,936 bytes of lk2nd memory margin. Frozen cycle:
`artifacts/roadmap-7.3/authorized-audio-ngd-removal-20261111T120110Z/`.

Candidate h reproduced TX1 overflow on capture 1/3. It delivered 48,000 stereo
frames without clipping and restored the mixer exactly. The controller-disable
record returned zero at 19.815798 s, which means both manager replies passed
the success-bit checks in this compiled callback; raw ACK payloads were not
logged. Overflow was reported at 19.944565 s, during the drop call
(19.711619992–20.012073325 s), 232.945008 ms after drop entry and after both
disconnect records. The reported status remains `0x5` (overflow plus closed).
All twelve stream records have zero returns, and no second capture ran.

This run rejects explicit channel removal alone as a sufficient audio fix.
The experiment remains disabled in production and unaccepted for installation.
It establishes that this firmware accepts the removal protocol, while leaving
codec/AFE timing and IRQ service order unresolved. One run does not establish
that the additional requests improve or worsen timing. Synchronous diagnostics
remain a confounder; collect buffered events before changing close sequencing.
`hardware-analysis.json` verifies phase-log continuity and the timing above.
The host controller finished with `FAIL_DIAGNOSTIC_ARCH_RESTORED`: the
diagnostic reset returned to fastboot after 254.412 seconds, the restoration
image reversed the guarded rename, and Arch returned with boot ID
`3d22d218-b993-4a87-99ab-26651917a4ff`. The original extlinux hash remained
`03285dfe1f2016a4cf967fe22f9c68d8663801a61e1c07050eff6fa36ed2a397`, the
temporary filename was absent, and the installed kernel version was unchanged.
The audio failure and successful autonomous recovery are separate results.
