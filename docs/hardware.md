# Hardware status on the SM-T825

Tested on one SM-T825 (bootloader T825UBU3CUF1) with kernel 6.19.5-t825 r11 and Arch Linux ARM.
For the SM-T820 and for details of each driver, see upstream's
[status table](https://github.com/wh1ter0z3/gts3lwifi-mainline#status).

| Area | State on this tablet | Notes |
|---|---|---|
| Boot without a PC | works | S-Boot, lk2nd, extlinux on `cache` |
| CPU, eMMC (HS400), zram | works | |
| Display, GPU (Adreno 530, freedreno) | works | 2048x1536, Hyprland at scale 2 |
| Touchscreen, S-Pen | works | `synaptics-s5807`, `wacom-w9019-digitizer`; follow the rotation |
| Keys: power, volume, Home | works | Home opens the launcher, power toggles the panel (desktop/) |
| Wi-Fi (QCA6174, ath10k) | works | needs `board.bin` from your own `system` partition |
| Bluetooth | works | address from EFS (`gts3-bdaddr`); RFCOMM/BNEP since r10 |
| USB network gadget | works | 172.16.42.1 on the tablet, NCM, ID `04e8:6863` |
| Speakers (4) | works | top pair needs kernel r11 (patch 0114); top = left, bottom = right |
| Microphones (2) | works | |
| Headphone jack | not tested | no jack detection in the port yet |
| Cameras (front S5K5E3, rear IMX258) | works | libcamera software ISP, 1280x720 at 30 fps |
| Video decode/encode (Venus) | works | H.264/VP8/VP9 decode, H.264 encode, through GStreamer V4L2 |
| Accelerometer, gyroscope, magnetometer, light | works | through the SLPI (`qcom-smgr`); needs `sns.reg` from EFS |
| Auto-rotation | works | `iio-sensor-proxy` + `desktop/autorotate`; mount matrix in `rootfs/files/61-gts3-accel.rules` |
| Battery, charging | works | SM5705 gauge and charger: capacity, status, USB-C input online |
| microSD | works | an 8 GB SanDisk card runs at UHS DDR50; the controller goes up to SDR104 |
| LTE modem, SIM, GPS | **no** | not supported by the port |
| Suspend | not tested | upstream reports s2idle only |
| Book Cover Keyboard | not tested | needs upstream's newer patches for hot-plug |

Messages seen on every boot that do no harm: `qcrypto` probe errors, `bam-dma-engine 644000`
-22, `stmpe-i2c 7-0040` -6, ath10k missing `board-2.bin` (falls back to `board.bin`), two Bluetooth
"Frame reassembly failed (-84)", `MultiMedia1: ASoC: no backend DAIs enabled`,
`psci: [Firmware Bug]: failed to set PC/OSI mode`,
`[pmOS-rd]: Unable to resize root partition: failed to find qualifying partition`.
