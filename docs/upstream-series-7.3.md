# Upstream series preparation (7.3)

Prepared on 2026-11-11 with `tools/t825-upstream-series.py`; nothing was sent.
Evidence: `artifacts/roadmap-7.3/upstream-series-20261111T151728Z/` (`manifest.json`, per-topic `series/`,
checkpatch output for every generic patch, `SHA256SUMS`).

## Classification

| Class | Count | Rule |
|---|---:|---|
| generic | 122 | kernel code, bindings or SoC-wide DTS |
| T825-specific | 1 | only `arch/arm64/boot/dts/qcom/*gts3l*` (0202) |
| mixed | 1 | board DTS plus generic files; must be split (0001) |
| excluded | 78 | `m*` patches carried from postmarketOS or other authors, private `.disabled` diagnostics, bring-up aids 0006/0007, upstream backport 0204 |

Generic topics: ASoC 16, media 17, power-supply 15, DRM panel 14, input 13,
DRM MSM 10, IIO 8, extcon 6, I2C 6, USB 6, MFD 4, arm64 DTS 2, clk, cpuidle,
DRM core, PCI and QRTR 1 each.

## Checkpatch (`--strict`, run outside the git work tree)

Only `0142-iio-qcom-smgr-push-every-sample.patch` is free of errors and
warnings. 35 generic patches have errors; the common causes are:

- 32 patches lack `Signed-off-by` (0002, 0038–0043, 0050–0055, 0058–0063,
  0065–0075, 0121, 0201);
- 38 use a `Co-Authored-By:` AI trailer, which the kernel's tool attribution
  rules do not accept in that form;
- 66 have the placeholder author `psigod@example.com`;
- four use the wrong commit reference style, one a malformed `Fixes:` tag and
  four cite commit IDs absent from the reference tree; the rest are line-length,
  `ENOTSUPP`, short `msleep` and Kconfig help warnings.

Running checkpatch inside this repository is invalid: it treats the `.patch`
file as a changed source file and reports every blank context line as trailing
whitespace. The tool runs it from `/`.

## Dependencies

The IIO `qcom_smgr` patches (0076–0077, 0140–0145) modify the out-of-tree
sensor manager carried as `m069`/`m070`; they cannot be submitted until that
driver is accepted. Patches touching the SM5705, S2MM005, RT5508, W9019,
STMPE1801 and AMS968HH01 drivers form new-driver series with their bindings.

## Why submission is blocked

Sending requires the author's real identity and DCO `Signed-off-by`, a
decision on AI attribution trailers, and the maintainer's explicit approval to
send. The current instruction is to prepare the series only. Each topic
directory is ready for rebasing on the target maintainer tree, checkpatch
cleanup and `scripts/get_maintainer.pl` once those decisions are made.
