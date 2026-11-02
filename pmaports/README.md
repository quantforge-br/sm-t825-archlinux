# pmaports packages

Copy both directories into `device/testing/` of a pmaports checkout at commit
`367abb3e17df1299380271c9e52c0824fc7378d3` (replace the existing `linux-postmarketos-qcom-msm8996`).
See the main README, step 4, and [docs/kernel.md](../docs/kernel.md).

- `linux-postmarketos-qcom-msm8996/`: 6.19.5, pkgrel 13. Patches 0001-0113 and the base config are
  identical to wh1ter0z3/gts3lwifi-mainline commit `363ed94`; 0122-0123 come from upstream commit
  `007853c` (GPU faults with shared buffers); 0114, 0201 and the config changes are ours.
- `device-samsung-gts3lwifi/`: the device package of the same upstream commit (pkgrel 5).
- `pmaports-367abb3e-kernel.diff`: the kernel package against pmaports `367abb3e`.
