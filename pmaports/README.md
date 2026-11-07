# pmaports packages

Copy both package directories into `device/testing/` of a pmaports checkout at
`367abb3e17df1299380271c9e52c0824fc7378d3`, replacing the existing kernel directory.
This base is retained and used for both package builds. See the main README,
step 4, and [docs/kernel.md](../docs/kernel.md) for isolated builds and RAM testing.

- `linux-postmarketos-qcom-msm8996/`: **7.3.1-r0**, release `7.3.1-t825`.
  All 194 upstream patches (70 m-series and 124 numbered through 0182) match
  wh1ter0z3/gts3lwifi-mainline **9f81231**. Local additions are config deltas from
  6.19.5 r9–r11, 0201 GPU hang accounting and 0202 top speakers (formerly 0114).
- `device-samsung-gts3lwifi/`: **1-r8**, with upstream headset/jack audio and
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
This 7.3.1 build has no SM-T825 runtime validation yet; see the evidence and
pending hardware checks in [docs/kernel.md](../docs/kernel.md).
