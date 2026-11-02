# eMMC layout of the SM-T825

The eMMC (32 GB, HS400) keeps Samsung's 47-partition GPT. This install writes only the four
partitions marked below; everything else is bootloader, modem or calibration data. Leave it alone.

| Linux | Name | Size | Stock use | This install |
|---|---|---|---|---|
| p1-p26 | xbl, aboot, tz, rpm, modemst1/2, param, ... | | boot chain, TrustZone, modem state | **never write** |
| p27 | efs | 20 MiB | IMEI, Wi-Fi/BT addresses, sensor calibration | read once (sensor registry), never write; mount `ro,noload` |
| p28 | boot | 76 MiB | Android kernel | **lk2nd** (first 2.3 MiB) |
| p29 | recovery | 76 MiB | recovery | keep TWRP here |
| p30-p37 | frp, bota, fota, persist, keystore, ... | | | never write |
| p38 | dsp | 16 MiB | | never write |
| p39 | modem | 85 MiB | modem and ADSP firmware (FAT16) | read once (ADSP firmware) |
| p40 | apnhlos | 95 MiB | GPU zap, Venus, SLPI firmware (FAT16) | read once |
| p41-p43 | persdata, steady, reserved2 | | | never write |
| p44 | system | 3.9 GiB | Android system | **Arch root** (ext4), later second btrfs device |
| p45 | cache | 200 MiB | Android cache | **/boot**: plain ext2 that lk2nd reads |
| p46 | hidden | 40 MiB | Samsung preload | unused |
| p47 | userdata | 24.4 GiB | Android data | optional: **btrfs root** (docs/btrfs.md) |

lk2nd numbers partitions from 0 (`wrp0p46` is Linux `mmcblk0p47`) and adds a 4 MiB virtual
partition for itself.

## Why the partitions keep their sizes

Both ways to change the table were tried on this tablet and neither works:

- **GPT from Linux.** The eMMC rejects writes to LBA 0-33 (`I/O error, dev mmcblk0, sector 0 op
  0x1:(WRITE)`). sfdisk managed to write the backup GPT at the end of the disk and then failed on the
  primary one, which left the two copies different. The original backup GPT had to be written back
  with dd. Do not try this.
- **PIT through Download mode.** The PIT ends with a 256-byte RSA signature. S-Boot refuses an edited
  PIT (`ERROR: Failed to confirm end of PIT file transfer!`) and writes nothing.

So the root starts on `system` (3.9 GiB is enough for Arch plus a desktop) and can then grow over
`userdata` and `system` together as one btrfs (28.3 GiB, docs/btrfs.md).

## Recovery tools and the new layout

- TWRP keeps working from `recovery`. Its "Wipe" and "Format Data" actions and flashing `system`,
  `cache` or `userdata` with Odin/Heimdall erase the Linux root or /boot.
- An Odin firmware flash restores Android and its partitions; the table never changed.
