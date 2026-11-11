# GNSS EFS loader audit

The existing `msm-cros-efs-loader` package in pmaports at
`modem/msm-cros-efs-loader` was reviewed before copying anything into this
repository. The analysis used upstream script `v1.2.1`, downloaded on
2026-11-08, SHA-256
`f1f2c924bef5bbe72bcdef6baa59d6ff6bff58fdf60cb3a6905cc7416203e38f`.
It is not a generic SM-T825 package.

## Observed behavior

Version 1.2.1 of `msm-cros-efs-loader.sh`:

- reads the FSG hash from `/sys/bus/nvmem/devices/qfprom*/nvmem` at offset `0x750`;
- reads FSG directly from the first `/dev/mmcblk*boot0`;
- creates and replaces `/var/lib/rmtfs/modem_fsg` with `dd`, `mv` and `sync`;
- reads the first `/dev/mmcblk*boot0` without confirming that it matches the T825 layout;
- creates 2 MiB `modem_fs1`, `modem_fs2`, `modem_fsg` and `modem_fsc` files when they are missing;
- can delete `modem_fsg` after a hash mismatch, except in ChromeOS development mode (`crossystem cros_debug?1`).

The dangerous operations are visible in the script itself: `FSG_SOURCE="$(echo
/dev/mmcblk*boot0)"`, `dd ... of="${fsg_tmp_path}"`, `mv
"${fsg_tmp_path}" "${FSG_PATH}"` and `rm -f "${FSG_PATH}"`. The
`rmtfs_avoid_writing="true"` setting does not cover those loader operations.

The `rmtfs` subpackage sets `rmtfs_avoid_writing="true"`, but this controls the
`rmtfs` daemon and does not make the loader's reads and writes read-only. The init
script also registers the loader at boot when the OpenRC subpackage is installed.

The first real MSS boot confirmed that the daemon uses canonical names
`/run/rmtfs/modemst1`, `/run/rmtfs/modemst2`, `/run/rmtfs/fsg` and `/run/rmtfs/fsc`,
even when firmware requests `/boot/modem_fs1` and `/boot/modem_fs2`. The private
adapter keeps the source `modem_fs*` names only in the diagnostic tree and maps
them in memory without opening partitions.

## Decision for the T825

The package remains outside this repository's pmaports until these are proven:

1. the real `boot0` and fuse layout on the SM-T825;
2. the correct mapping of `fsg`/`fsc`/`modemst1`/`modemst2` for `rmtfs`;
3. a write policy that permits diagnostic boot without changing partitions;
4. a GNSS userspace service compatible with QRTR/QMI LOC on this device.

The preflight [`tools/t825-gnss-preflight.sh`](../tools/t825-gnss-preflight.sh)
checks dumps and firmware without starting this package. Until it returns
`READY`, do not install `msm-cros-efs-loader`, `rmtfs` or `tqftpserv` on the tablet.
