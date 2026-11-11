# PM8994 watchdog investigation

Source and read-only live review, 2026-11-10. The PMIC watchdog is a plausible
alternative to the SoC watchdog, but it is **not a validated recovery route**.
No PMIC registers were written, no driver was loaded and no reboot was issued.

Evidence is retained in
`artifacts/roadmap-7.3/pm8994-watchdog-source-20261110T230854Z/`, including
source snapshots, pinned download URLs, hashes, live configuration and tests.

## Compatibility evidence

The live SPMI device at USID 0 identifies as `qcom,pm8994`; its PON child at
`0x800` uses `qcom,pm8916-pon`. This agrees with mainline `pm8994.dtsi`.
The live kernel has `CONFIG_PM8916_WATCHDOG` disabled and exposes no watchdog.
A compatible PON parent does not establish compatibility of every child block.

The downstream reference is
[awesometic/android_kernel_samsung_msm8996 at f48aec90](https://github.com/awesometic/android_kernel_samsung_msm8996/tree/f48aec90fcebf4615fdee4a8abac7339930db856).
This pins a relevant source reference; it does not prove an exact match to the
tablet's installed Samsung bootloader or secure firmware.

| PON offset | Mainline `pm8916_wdt.c` | Downstream `qpnp-power-on.c` |
|---|---|---|
| `0x54`, `0x55` | S1 and S2 timers | Same offsets in watchdog bark diagnostics |
| `0x56` | S2 reset type; hard reset value 7 | Same reset-control offset defined |
| `0x57` | Enable bit 7 | `qpnp_pon_wd_config()` writes the same bit |
| `0x58` | Pet bit 0 | Not established by the reviewed downstream PON file |
| `0x0c`, bit 2 | PMIC watchdog power-off reason | Same generation-1 reason interpretation |

Downstream `msm-poweroff.c` explicitly disables the PMIC watchdog before
emergency download so that mode does not automatically reset. This supports
the existence of an autonomous PMIC timer, but proves neither non-secure
programming access in mainline nor the destination of a watchdog reset here.
The stock board DT does not configure a watchdog child or its bark interrupt.
The mainline watchdog binding names only `qcom,pm8916-wdt`, requires an
interrupt, and does not explicitly list PM8994.

## Recovery lifecycle findings

1. The driver changes the reset mode and timers during probe, even before a
   userspace open. Binding it is a hardware mutation, not a read-only probe.
   Probe also ignores the return from `pm8916_wdt_configure_timers()` in this
   source version; successful registration alone cannot prove configuration.
2. The driver has no shutdown callback and does not request
   `watchdog_stop_on_reboot()`. The watchdog core defaults `stop_on_reboot` to
   `-1`, also observed live. This leaves a possible path to retain an armed
   timer through kexec, but firmware/SPMI behavior still needs measurement.
3. An inherited running timer sets `WDOG_HW_RUNNING`. With
   `CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED=y` and `CONFIG_WATCHDOG_OPEN_TIMEOUT=0`,
   the core can feed it indefinitely before userspace opens the watchdog.
   Both values are present in the installed kernel. A future diagnostic kernel
   must use a bounded takeover policy; merely enabling the driver could defeat
   recovery from an initramfs failure while the watchdog worker still runs.
4. Driver suspend stops an active timer, and resume restarts it. That behavior
   does not cover a hang between suspend and resume. Suspend acceptance needs
   a separate solution.
5. The source kernel must arm the watchdog before a transition. A watchdog
   first armed by the candidate cannot cover device shutdown, CPU teardown,
   relocation or early entry. A smaller initramfs does not fix that gap.

## Live PON register state

A read-only snapshot on 2026-11-11 (Arch boot
`a653fa6f-fa9b-4c1d-8a75-d2af4138f407`) read only PON `0x800-0x80f` and
`0x854-0x858` through regmap debugfs at fixed offsets; no register was written,
no driver was loaded and the tablet was not rebooted. Evidence:
`artifacts/roadmap-7.3/pm8994-pon-readonly-20261111T151136Z/`, collector
`tools/t825-pmic-pon-snapshot.sh` and decoder `tools/analyze-t825-pon.py`.

| Register | Value | Interpretation |
|---|---|---|
| `0x804`/`0x805` | `0x01`/`0x01` | PON peripheral, subtype `PON_PRIMARY`: generation 1 |
| `0x808` | `0x41` | PON reason: hard reset and external power |
| `0x80c` | `0x02` | Last power-off: PS_HOLD (not PMIC_WD, bit 2) |
| `0x854`/`0x855` | `0x0f`/`0x03` | Bootloader-programmed S1/S2 timers; units unverified |
| `0x856` | `0x08` | S2 reset type not defined by the pinned downstream enum |
| `0x857` | `0x00` | Watchdog disabled (bit 7 clear) |

Consequences: the running boot has no inherited armed PMIC timer, so the
`WDOG_HW_RUNNING` takeover concern does not apply to this boot. The mainline
probe would replace the bootloader's reset type `0x08` with `0x07` and cannot
restore it. `POFF_REASON1` distinguishes a PMIC watchdog power-off from PS_HOLD,
so a future expiry can be attributed by reading it on the next boot. Expiry,
pet semantics, timer units and reset destination remain unvalidated.

## Required validation sequence

First establish the PM8994 PON revision, timer units, pet semantics, register
ownership and bark IRQ routing from matching hardware documentation or source.
Do not infer them solely from the PM8916 compatible string. Prepare a separate
RAM diagnostic with explicit error handling and bounded watchdog takeover;
keep the production DT and installed boot files unchanged.

Use a known-good `fastboot boot` control with the already validated software
supervisor armed first. Test watchdog start, keepalive and stop without inducing
a kernel fault. Then test deliberate expiry with the software supervisor set
later as fallback. Capture elapsed time, reset reason, boot identity, USB mode
and installed-system recovery. Distinguish the watchdog expiry from a software
fallback; a reset without attribution is not a watchdog acceptance result.

Validate retention and destination across a normal transition separately.
Only after independent pre-entry recovery works should early-entry failures be
tested. Suspend and complete SoC stalls remain separate gates. No new kexec
execution is justified by this source review.

## Experimental runner containment

Both `t825-kexec-cycle.sh` and `t825-kexec-proof-cycle.sh` now stop with
`BLOCKED_PREENTRY_RECOVERY` before any device access. There is no environment
override. The preserved implementation is reference code, not an enabled test
route. A host-only fake-transport regression verifies that neither entry point
contacts SSH/fastboot, spawns a runner or creates a report directory.

Before re-enabling it, also repair the dispatch design: the preserved runner
stops the USB gadget through one SSH connection, then tries a second SSH
connection to execute kexec. That can remove its own execution route. Any future
dispatch must use one detached tablet-side process with validated independent
recovery and stage evidence before transport teardown. Fixing dispatch alone
does not establish that recovery.
