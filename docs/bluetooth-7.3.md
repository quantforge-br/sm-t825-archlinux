# Bluetooth reset investigation on the SM-T825

Updated: 2026-11-11. Bluetooth is operational, but intermittent HCI reset
timeouts remain unresolved. No r12 experiment is accepted for deployment.
The restored control is the r9 helper with the r11 eight-second service delay.

The next detached acceptance attempt configured a RAM fallback but exercised
only the direct installed-Linux reboot path. The fallback was not validated.
It stopped after cycle 1 because the first boot reproduced the fault:
`artifacts/roadmap-7.3/bluetooth-20boot-20261111T124000Z/`. The tablet returned
to Arch automatically and the controller/address were healthy, but the boot
log contains four QCA setup sequences and a second-setup
`Opcode 0x0c03 failed: -110` at 25.284 s. The service recovered the controller
after the timeout. This is a controlled diagnostic failure with automatic
recovery, not a 20-boot acceptance result.

A further bounded rebind after manual recovery is recorded at
`artifacts/roadmap-7.3/bluetooth-after-manual-recovery-20261110T225528Z/`.
The collector finished, restored the primary controller and retained the same
boot ID and payload hashes. It archived the evidence and stopped its independent
timer only after health checks. The verified kernel delta contains two frame
reassembly `-84` warnings and zero HCI Reset `-110` timeouts. This confirms a
restored control on that boot and does not satisfy the 20-boot acceptance gate.

## Evidence and rejected experiments

| Configuration | Observation | Decision |
|---|---|---|
| r11 control: r9 helper, eight-second delay | Historical 20/20 run, followed by 4/5 in a later software reboot run; the failure contained `Opcode 0x0c03 failed: -110` | Retain as the control; reopen acceptance |
| r9 helper, 20-second delay, original readiness collector | Five early collections saw no controller, often while the service was still sleeping | Cannot establish a steady-state failure rate |
| r10 HCI-only helper, 20-second delay | Five preliminary software reboot cycles passed; cycle 7 of the following run reproduced `-110` and the helper recovered by rebinding UART | Delay alone does not fix the timeout |
| Wait for a primary controller before setting its address | The initial QCA setup completed, but no primary controller appeared and the helper timed out | Reject: the wait blocks required address provisioning |
| Add `Wants=bluetooth.service` to the above experiment | The primary-controller prerequisite still failed | Reject as a remedy for that prerequisite; no independent causal conclusion about service ordering |

The long report `bluetooth-r10-delay20-20-20261110T102637Z/` contains live
payload changes after the initial failure. Its twenty rows are **not** twenty
repetitions of one configuration and must never be aggregated as an acceptance
gate. The lack of per-cycle payload hashes prevents assigning an exact revision
to every row. The directory names beginning `cold-boot-` refer to software
reboots; the tablet was not powered down between those tests.

Private evidence under `artifacts/roadmap-7.3/`:

- `cold-boot-5-20261110T100443Z/`: r11 failure control.
- `cold-boot-r12-5-20261110T101243Z/`: collections before readiness.
- `cold-boot-r10-delay20-5-20261110T101944Z/`: preliminary five-reboot run.
- `bluetooth-r10-delay20-20-20261110T102637Z/`: mixed experiment; not a gate.
- `bluetooth-r12-rejected-20261110T105803Z/`: experimental source snapshot and
  restored live helper/service hashes.
- `bluetooth-source-audit-20261110T105657Z/`: Linux 7.3.1 source excerpts.

## What the kernel source establishes

The packaged 7.3.1 source contains the following path; the repository patch
series does not modify these Bluetooth files:

1. `drivers/bluetooth/btqca.c:qca_check_bdaddr()` detects the firmware's default
   address and sets `HCI_QUIRK_USE_BDADDR_PROPERTY` when no public address has
   been supplied.
2. `net/bluetooth/hci_sync.c:hci_dev_setup_sync()` marks a controller
   `HCI_UNCONFIGURED` when that address cannot be resolved. Sysfs presence and
   a successful firmware download do not imply primary-controller enumeration.
3. `net/bluetooth/mgmt.c:set_public_address()` accepts the address for an
   unconfigured controller, sets `HCI_CONFIG` and queues asynchronous power-on.
   The command response does not prove that this later power-on/reset passed.
4. `drivers/bluetooth/hci_qca.c` enables `HCI_QUIRK_NON_PERSISTENT_SETUP` when
   power control is present. A later power-on can therefore perform another QCA
   setup. Two firmware downloads alone do not prove that a helper raced an
   unfinished first download.

Consequently, waiting for a primary controller before provisioning the address
is invalid for this tablet. Arbitrarily increasing a sleep also fails to explain
why HCI Reset `0x0c03` sometimes times out. The next useful diagnostic is an HCI
trace covering provisioning, the address command(s), IBS wake/ack and reset,
correlated with UART/power events. Preserve the original firmware; a modified
NVM is not accepted.

The QCA NVM format audit proves that the earlier address experiment changed the
intended field: the outer TLV is type 2, tag 2 is the six-byte BDADDR tag, and
its payload begins at offset `0x10`. The stock payload is `ad5a00000000`; the
candidate payload `7afa840da13c` is the firmware byte order for EFS address
`3C:A1:0D:84:FA:7A`, with all other bytes unchanged. The candidate boot still
showed the framing error, a second setup and HCI Reset `-110`, so the edit is
structurally valid but causally inconclusive. The parser and retained inputs
are in `artifacts/roadmap-7.3/qca-nvm-format-audit-20261111T130000Z/`; the
decision remains diagnostic-only and `production_fix_accepted: false`.

The corrected parser and source execution report supersede the initial format
audit: `artifacts/roadmap-7.3/qca-address-source-check-20261111T111509Z/`.
The tests cover wrapped type-4 headers (the inner header starts at byte 4),
displaced BDADDR tags, byte order, changes outside the address and malformed
inputs. They require neither a tablet nor files in `/tmp`.

More importantly, `qca_tlv_check_data()` copies the loaded tag into
`config.bdaddr`. With no pre-provisioned `hdev->public_addr`,
`qca_check_bdaddr()` compares the controller readback with that value, rather
than a fixed factory-address constant. If firmware reads back the edited tag,
the equality still sets `HCI_QUIRK_USE_BDADDR_PROPERTY`. A host C harness runs
the actual kernel function and proves this for both stock and edited tags,
plus the pre-provisioned-address bypass, differing readback and error paths.
Run `python3 tools/test-t825-qca-bdaddr-source.py --kernel-source /path/to/linux`.

Thus editing the NVM tag alone cannot bypass property-based provisioning in
the equal-readback case. The historical experiment has no captured initial
Read BD_ADDR response, so its actual branch and firmware selection remain
unproven. Investigate providing the board address through the normal property
path before controller initialization in a separate RAM candidate; keep stock
firmware intact and preserve packet/IBS capture at the post-setup Reset. This
source result does not establish the cause of `-110` or accept a driver fix.

## Legacy reboot runner containment

`tools/t825-bluetooth-auto-cycle.sh` now exits with
`BLOCKED_BLUETOOTH_RECOVERY` before report creation or device access. There is
no environment override. Its successful direct reboots and helper recovery did
not validate independent recovery from a hung installed boot. The configured
read-only direct-init fallback has no systemd/BlueZ startup and cannot satisfy
this runner's acceptance workload. Merely polling fastboot/SSH does not repair
these gaps. The latest attempt is retained as fault evidence, with recovery
coverage explicitly unproven, rather than accepted unattended infrastructure.

The historical script snapshots retained helper/service/udev hashes, stable
address probes, first-fault termination and build/route checks. Nine historical
fake-transport tests covered those behaviors, but never validated an independent
recovery backend. `tools/test-t825-bluetooth-auto-cycle-containment.py` verifies that
both normal and snapshot entry paths refuse transport calls and report creation.
The archived implementation below the guard is reference code only.

Before another repeated-boot run, integrate a Bluetooth workload into the
validated RAM controller, retain the independent supervisor through the tested
root transition, and observe reset/restoration after failures. Installed-system
boot acceptance remains distinct from a direct-init Bluetooth probe. Complete
kernel/SoC stalls still require the separate hardware-watchdog gate.

## Bounded HCI rebind trace

The host and tablet collectors now snapshot themselves into the private report,
arm an independent 140-second systemd restoration timer before touching the
UART, and run the collection in a bounded transient unit. The unconfigured
controller is polled with `btmgmt config`, requiring hci0 to support and lack
only the public-address configuration option. This is bounded by a 15-second
readiness deadline; a missing or unexpected configuration fails before the
helper is invoked. BlueZ 5.87 source confirms that `info` uses
`READ_INDEX_LIST` (configured controllers), while `config` uses
`READ_UNCONF_INDEX_LIST` and `READ_CONFIG_INFO`. Source excerpts are retained in
`artifacts/roadmap-7.3/bluetooth-config-source-20261110/`.
The trace uses `btmon -C 200 -c never` for untruncated text while retaining the
btsnoop file as the packet authority. IBS debugfs counters are captured before
and after the rebind. They belong to separate UART bindings and cannot be
subtracted as continuous counters. The collector reuses the frozen validator's
overlap-verified kernel-log delta: absent, empty or ambiguous logs cannot pass,
and rotating out an old timeout cannot hide a new one. Failures retain logs
and classifications. Host cleanup also checks restoration and writes a final
decision after archive-download failure; it cancels the independent timer only
after the collector is terminal and the baseline address is visible again.

Fourteen offline regression tests cover readiness parsing, wrong-controller
options, rotated-out timeouts, log gaps, archive failures, restoration address,
timer failures and missing results. Run `python3 tools/test-t825-bluetooth-trace.py`.

Report `artifacts/roadmap-7.3/bluetooth-hci-trace-20261110T112651Z/` is one
successful historical control rebind on the restored r11 payload. The helper
exited 0, the controller and BlueZ returned, boot ID and payload hashes were
unchanged, and the legacy timeout counter reported `before=0 after=0 new=0`.
The final TX/RX
states were asleep; counter differences across the rebind are not traffic
deltas. This is diagnostic evidence only: a rebind
success does not satisfy the unresolved repeated-boot acceptance gate.

A five-cycle frozen-payload series then passed all five rebinds, with every
cycle restoring the controller and BlueZ, preserving the r11 helper/service
hashes and reporting `new=0` HCI Reset timeouts using the legacy counter. The report is
`artifacts/roadmap-7.3/bluetooth-rebind-series-20261110T112943Z/`. The IBS
counters were reinitialized by each UART detach/attach (some values therefore
decreased between snapshots), while every final `tx_ibs_state` and
`rx_ibs_state` was `0`. This narrows the rebind behavior but still cannot stand
in for the unresolved 20 software-reboot acceptance test.

An offline audit of all six historical traces verified continuous, unrotated
kernel captures with no new HCI Reset timeout and unchanged payload/boot IDs:
`bluetooth-history-audit-20261110T122557Z/decision.json`. Their readiness
captures all contain `Index list with 0 items`: the old `info` poll always
exhausted its wait. Those successes establish rebind controls with a fixed
delay, not successful readiness detection.

The corrected collector passed one on-device control at
`bluetooth-config-trace-20261110T122454Z/`. `config` first saw zero entries,
then hci0 missing only `public-address`; the helper started immediately after
that verified state. It exited successfully, all four HCI Reset commands had
successful completions, and the baseline address, payload and boot ID remained
unchanged. The timer was cancelled after restoration. Two new
`Frame reassembly failed (-84)` messages accompanied successful setups, so that
line alone does not establish the cause of `-110`. The intermittent reset
failure and repeated-boot acceptance remain open.

A fresh bounded trace on the same r11 payload repeated the corrected readiness
check and restoration path. `btmgmt config` first returned no unconfigured
controller, then exposed hci0 with only `public-address` missing. The helper
completed successfully, the controller and BlueZ returned, and the independent
recovery timer was cancelled only after those final health probes. The kernel
delta contained two `Frame reassembly failed (-84)` messages and no new HCI
Reset `-110` timeout. This is a successful rebind control, not evidence that
software reboot acceptance is closed:
`artifacts/roadmap-7.3/bluetooth-hci-trace-followup-20261110T184909Z/`.

A read-only runtime snapshot of the restored r11 control found four QCA setup
sequences in the retained boot log at monotonic seconds `12.380118`,
`23.199581`, `2058.268627` and `2060.474058`. Each was followed by
`Frame reassembly failed (-84)`; no `Opcode 0x0c03 failed: -110` occurred in
this boot. The first pair belongs to initial boot and delayed address-service
sequencing. The later pair was caused by the deliberate Bluetooth trace
rebind: the journal shows Bluetooth Support stopping and endpoints being
unregistered before those two setups. The controller was primary, powered and
address-matched at collection time. This confirms repeated setup activity but
does not identify a reset cause or replace the repeated-boot gate. Evidence:
`artifacts/roadmap-7.3/bluetooth-runtime-audit-20261110b/` and
`artifacts/roadmap-7.3/bluetooth-runtime-followup-20261110T184556Z/`.

## Downstream power/UART comparison and reset boundary

The read-only comparison is retained in
`artifacts/roadmap-7.3/bluetooth-downstream-20261110T232224Z/`.
Samsung kernel sources are pinned to
`awesometic/android_kernel_samsung_msm8996` commit
`f48aec90fcebf4615fdee4a8abac7339930db856`. The MSM8996 Android userspace
reference is `LineageOS/android_hardware_qcom_bt` commit
`61fe455f3515e5b1ef4a2be60395ae556465c030`; it is not established as the
exact Samsung userspace shipped on this tablet. URLs and hashes are recorded
per source. No GPIO, regulator, UART or firmware setting was changed.

| Boundary | Downstream/reference behavior | Current mainline behavior |
|---|---|---|
| Supplies | `bluetooth-power.c` enables configured regulators before BT_EN; the board node supplies IO from PM8994 S4 and PA through GPIO9's fixed regulator | ROME `hci_qca` acquires BT_EN and sleep clock, with no regulator consumer; the 3.3 V rail is enabled through WLAN_EN/PCIe |
| BT_EN on | Drive low, wait 50 ms, drive high, wait 50 ms | Acquire low at probe; on power-up drive high and wait 150 ms |
| BT_EN off | Drive low and wait 100 ms before regulator teardown | ROME drives low without an explicit minimum low-time delay |
| UART wiring | BLSP1 UART2, TLMM 41..44; board pinctrl selects `blsp_uart2` | Same UART/pins with `uart-has-rtscts` |
| Baud change | Android reference flushes UART, gates flow, sends vendor baud command, changes host to 3 Mbaud, restores flow, waits for vendor/complete events | ROME queues vendor baud command, waits for transmission and 300 ms, then changes host rate; explicit flow gating applies to other SoCs |
| Firmware reset | Android reference downloads patch/NVM and issues HCI Reset | `qca_uart_setup()` downloads patch/NVM, completes a vendor-setup Reset and address handling; the HCI core later issues another Reset |

The live regulator summary confirms the current consumer chain:
`vreg_rome_3p3 -> vreg_wlan_en -> 600000.pcie-vddpe-3v3`, each with use count
1. The live Bluetooth DT has no supply properties. PCIe reported link-up at
2.145016 s and the first QCA setup began at 12.835726 s on this healthy boot.
That confirms a dependency gap, but not a rail failure during the historical
timeout. Do not power-cycle this shared rail or add guessed supply properties
to the ROME binding as a test. The stock DT also contains a generic root
`bt_qca6174` node with additional supplies; it must not be confused with the
board-specific `/soc/bluetooth` node when interpreting the board wiring.

The r11 failed boot provides a more specific next diagnostic boundary:
`QCA setup on UART is completed` at 24.818505 s precedes the Reset `-110`
at 26.851793 s by 2.033288 s. In the reviewed source, that completion message
comes only after the Reset inside `qca_uart_setup()` succeeds. After returning,
`qca_setup()` clears `QCA_IBS_DISABLED`; subsequent core commands can use the
IBS wake/ack queue. This supports investigating post-setup initialization,
including address programming and the core Reset. The failed boot has no
packet-level trace, so the exact caller and wire-level failure are unproven.

Two retained successful control traces were decoded from their btsnoop records,
checking capture type/version, untruncated records, zero reported drops and
paired command/completion opcodes. All four Resets per trace returned status 0:

| Control | Reset latencies in command order, milliseconds |
|---|---|
| Corrected configuration trace, 12:24 UTC | 64.828, 55.540, 63.605, 550.780 |
| After manual recovery, 22:55 UTC | 66.384, 55.786, 66.825, 550.626 |

The slower fourth Reset follows public-address provisioning in both controls.
It is still a successful response, not a timeout. HCI monitor timestamps
measure the host command/completion interval; they do not show physical UART
transmission or prove an IBS acknowledgment occurred. End-of-test IBS snapshots
cannot resolve a transient wake failure before the helper restores Bluetooth.

Before choosing a reset-delay, flow-control or firmware change, capture the
first failing post-setup Reset together with IBS TX/RX states and wake/ack
counters from the same UART binding, before recovery resets those counters.
Keep the software recovery timer independent. The source comparison is now
available; electrical timing, exact stock userspace behavior and the repeated
boot acceptance gate remain unverified. No change from this comparison is
promoted as a Bluetooth fix.

The new one-cycle report confirms the same boundary on the current restored
control: the second QCA setup completed at 23.281289 s and the HCI Reset timed
out at 25.284307 s, while a later rebind setup recovered the controller. The
log still lacks packet-level IBS state at the timeout, so it does not identify
whether the failure is UART framing, wake/ack sequencing, or controller state.

### IBS timeline control

The trace collector now snapshots and runs `t825-bluetooth-ibs-sample.py` before
unbind, sampling at roughly 100 ms intervals for at most 115 seconds. Each row
records monotonic start/end, debugfs directory device/inode identity, states,
wake/ack counters and explicit read errors. An open directory descriptor keeps
one sample tied to one binding even if the path is replaced. Counter deltas
across different identities are invalid; inode reuse and sub-100 ms events
also limit interpretation. Sequential reads are not an atomic snapshot.

One frozen run completed with automatic restoration, unchanged boot/payload,
continuous kernel logs and no new Reset timeout:
`artifacts/roadmap-7.3/bluetooth-ibs-timeline-20261110T232923Z/`.
It recorded 105 rows over 10.968 seconds: 24 from the old directory, 31 during
absence, and 50 from the replacement. The new binding was observed in TX state
2 (awake), with RX 0/1, then both asleep. No sampled TX-waking stall occurred;
this successful control cannot explain the failing software reboot.

The frozen run incorrectly parsed debugfs boolean vote files as integers,
retaining explicit errors for `tx_vote`/`rx_vote`; other states/counters remained
valid. The final sampler accepts `Y/N`. Four unit tests cover missing entries,
invalid values, boolean formatting and directory replacement during a sample;
a separate read-only live check parsed all four subsequent vote samples. The
frozen hardware artifact is preserved rather than rewritten. Fourteen existing
trace/restoration tests also pass. The independent restoration timer remains
separate from the sampler and is cancelled only after final controller health.
