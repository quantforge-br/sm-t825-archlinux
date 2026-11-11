# Display pixel-clock update investigation

Updated 2026-11-11. The four retained boot warnings have a demonstrated call
path, but the electrical cause and a corrective kernel change are unverified.
The latest read-only live capture is
`artifacts/roadmap-7.3/pclk-live-boundary-20261111T103933Z/`.
Its `analysis.json` records two `pclk0` and two `pclk1` warnings; every stack
contains the complete fbcon-to-DSI pixel-rate boundary and remains classified
with `cause_proven: false` and `hardware_fix_accepted: false`. The earlier
source-boundary report is retained for the source review:
`artifacts/roadmap-7.3/pclk-source-boundary-20261110T233238Z/`.

## Observed call boundary

The installed r1 kernel's full dmesg contains four complete warning stacks:

| Boot time, seconds | Clock | Request path |
|---|---|---|
| 4.711706 | pclk0 | `dev_pm_opp_set_rate()` during DSI byte-rate setup |
| 4.714642 | pclk1 | Same byte-rate propagation path |
| 4.716948 | pclk0 | Explicit pixel `clk_set_rate()` |
| 4.718877 | pclk1 | Same explicit pixel-rate path |

All four pass through `clk_pixel_set_rate()`, `clk_rcg2_configure()` and
`update_config()`. The lower stack identifies fbcon initial configuration via
`__drm_fb_helper_initial_config_and_unlock()`, rather than a suspend/resume
operation. This explains two update attempts per pixel source on this boot;
it does not establish that the warning can never happen at resume.

`dsi_link_clk_set_rate_6g()` first changes the byte clock through OPP, then
explicitly requests the pixel rate. `msm_dsi_host_power_on()` invokes that
function before `link_clk_enable()`. The current clock tree has both pixel
sources parented to `dsi0pll`, consistent with bonded DSI. It reports
148866500 Hz at both pclk sources, 111649875 Hz on `dsi0pllbyte`, and
1786398000 Hz at `dsi0vco_clk`. These are post-boot observations, not captured
parent/RCG state at the failure instant.

## Why visible output does not prove update success

`update_config()` sets CMD_UPDATE, polls it 500 times with a 1 us delay, then
warns and returns `-EBUSY` if the bit remains set. The clock provider propagates
that return through its pixel-rate operation. However, `clk_change_rate()` in
the reviewed common clock framework calls `ops->set_rate()` without checking
its return. It then recalculates the rate and continues to children. The DSI
caller's successful `clk_set_rate()` therefore cannot certify this RCG update.
Likewise, a frequency in `clk_summary` is not a measurement of the wire clock
or proof that CMD_UPDATE cleared.

Both pclk definitions use `clk_pixel_ops` with `CLK_SET_RATE_PARENT`, without
`CLK_OPS_PARENT_ENABLE`. The 14 nm DSI PLL starts and waits for lock in its
prepare callback. A rate update while the relevant clock is not running is a
specific hypothesis consistent with the call order. It is not proven: no
failure-time CMD/CFG, parent prepare/enable or PLL lock state was captured.
Do not simply increase the polling timeout, suppress the warning, force the
RCG on, or add parent-enable flags without validating the shared PLL lifecycle.

## Separate suspend fixes

Patch 0147 modifies PCIe D3cold handling to preserve the combo Wi-Fi/Bluetooth
supply. Patch 0148 changes MDP5 plane pipe reassignment after state restoration.
Neither modifies MMCC pixel-clock programming. Both changes are present in the
reviewed prepared kernel source; source presence alone does not prove which
binary is running or validate all suspend behavior.

The historical one-cycle and three-cycle captures found no new pclk warnings
after s2idle. They remain useful observations, not acceptance of a pixel-clock
fix. The first historical investigation incorrectly said clock debugfs was
unavailable; later captures, including this review, successfully read it.

## Next hardware evidence

Use a separate RAM diagnostic under the existing recovery gate to record
the selected pclk parent, parent prepare/enable state, RCG CMD/CFG and read
errors at the timeout, plus byte/pixel rate request order. Read only the
specific documented configuration/status registers; do not dump unrelated
MMIO or change clock control through debugfs. Check both bonded links and
retain the warning/error rather than replacing it with a success marker.

Evaluate a narrowly scoped parent-clock/RCG sequencing candidate only after
that evidence distinguishes missing clock activity from a different update
failure. Acceptance requires initial boot and repeated suspend/resume, correct
display timing, no new clock warnings, and observed automatic restoration.
The current standalone `t825-pclk-suspend-test.sh` predates the independent
recovery requirement and is disabled; an RTC alarm alone cannot recover a
kernel stall or establish that suspend actually occurred.

## Reproducible analysis

`tools/analyze-t825-pclk.py` parses complete warning windows and refuses to
classify an incomplete stack as the fbcon boundary. Its regression tests cover
both a complete six-function boundary and an unknown stack:
`python3 tools/test-t825-pclk-analysis.py`.
