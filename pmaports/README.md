# pmaports packages

Copy both package directories into `device/testing/` of a pmaports checkout at
`367abb3e17df1299380271c9e52c0824fc7378d3`, replacing the existing kernel directory.
This base is retained and used for both package builds. See the main README,
step 4, and [docs/kernel.md](../docs/kernel.md) for isolated builds and RAM testing.

- `linux-postmarketos-qcom-msm8996/`: **7.3.1-r2**, release `7.3.1-t825`.
  All 194 upstream patches (70 m-series and 124 numbered through 0182) match
  wh1ter0z3/gts3lwifi-mainline **9f81231**. Local additions are config deltas from
  6.19.5 r9–r11, 0201 GPU hang accounting, 0202 top speakers (formerly 0114),
  and 0204 A5xx hangcheck progress detection. The r2 package is built, but
  controlled GPU acceptance and validated normal-image recovery remain open.
  The optional `0203-...patch.disabled` is excluded from normal builds; set
  `T825_MSS_DIAGNOSTIC=1` only for a private GNSS/MSS diagnostic image. With
  pmbootstrap, create `.t825-enable-mss` in the package directory because
  arbitrary host environment variables are sanitized; the sentinel also gives
  the image the distinct module release `7.3.1-t825-mssdiag`.
  The separate `0205-...patch.disabled` and `0206-...patch.disabled` provide
  private WCD9335 and SLIMbus transaction instrumentation,
  enabled only by `T825_AUDIO_DIAGNOSTIC=1` or the package sentinel
  `.t825-enable-audio-diag`. It produces `7.3.1-t825-audiodiag`; diagnostic
  register reads/logs still require `snd_soc_wcd9335.port_diagnostics=1` at
  module load. SLIMbus logging separately requires
  `slimbus.transaction_diagnostics=1`, loaded before the codec dependencies.
  Private patch `0207-...patch.disabled` adds an experimental NGD remove-channel
  callback to that audio build, enabled only with
  `slim_qcom_ngd_ctrl.channel_removal=1`. The RAM builder additionally requires
  `T825_NGD_CHANNEL_REMOVAL=1` and transaction diagnostics. Its two manager
  requests check the firmware success bit; missing/negative callback evidence
  fails the capture. This is an unaccepted experiment, not a production fix.
  MSS and audio opt-ins cannot be combined. See
  [docs/audio-7.3.md](../docs/audio-7.3.md) for validation scope; this is not an
  accepted codec fix and must not replace the installed kernel/modules.
- `device-samsung-gts3lwifi/`: **1-r9**, with upstream headset/jack audio and
  the 12 Hz accelerometer rule and `61-gts3-keys.rules` from upstream 9f81231.
  The key rule sets the TC305K Back/Recent LEDs to the `input-events` trigger
  so they turn off after inactivity; the rootfs builder installs it too.
  `61-gts3-keys.hwdb` and `gts3-kglobalshortcutsrc` are deliberately excluded:
  the hwdb remaps Home to Meta and would break the Hyprland Home bind.
  GNSS/KDE/TrustZone integration is outside this move.
  Arch's UCM copy matches the package; its accelerometer override retains the
  Hyprland matrix and the same 12 Hz setting.
- `pmaports-367abb3e-kernel.diff`: APKBUILD and config against the pinned pmaports
  base, regenerated from these sources; patches are supplied by the directory.

The source version is newer than the previous 6.19.5-r13 binaries in `release/`.
The installed build now has a first SM-T825 runtime baseline; see
[`docs/baseline-7.3.md`](../docs/baseline-7.3.md) and the remaining hardware
checks in [docs/kernel.md](../docs/kernel.md).
