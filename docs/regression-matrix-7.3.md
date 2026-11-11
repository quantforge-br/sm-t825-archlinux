# Linux 7.3.1 attribution matrix for the SM-T825

This matrix distinguishes kernel, firmware and userspace evidence from the
installed `7.3.1-t825` system. Attribution can change after a controlled reproduction.

| Symptom | Current evidence | Working attribution | Next experiment |
|---|---|---|---|
| GPU rasterization/`gpuhang` hang | `offending task: gpuhang`; patch 0201 recovery kept Hyprland alive; Mesa 26.2.6 and Hyprland 0.57.1 recorded | Kernel detects and recovers selected synthetic hangs; command generation may involve Mesa/Chromium | Compare identical workloads with/without 0204; capture a real browser hang |
| Cameras deliver 30 fps without gaps | Three repetitions per camera; libcamera 0.7.2 and Venus firmware present | Kernel/CAMSS delivers frames; image quality and calibration remain separate | Measure image quality and Venus codecs |
| Default microphone 20/20 | 48,000 stereo frames per capture without clipping; PipeWire 1.6.10/WirePlumber 0.5.18 | PCM delivery works; these captures did not reproduce the codec warning | Test individual microphones, headset and post-suspend capture |
| `wcd9335_slimbus_irq` | Stage-aware validation attributed five overflows in ten cycles to `Mic` transfer; a later full route run reproduced overflow in ten of twenty cycles, with all PCM transfers completing; pinned SLIMbus source discards connect/define/activate/deactivate returns | Root cause remains open; discarded transaction errors are a fix candidate but no failing return has been observed | Capture first-fault SLIMbus return codes, then test narrowly scoped error propagation; compare micbias/TDM/AIF4 state and test individual microphones/post-suspend capture |
| Bluetooth `-84`/`-110` | r9 15/20; r10 18/20; r11 historical 20/20 followed by 4/5; longer delay also reproduced `-110`; r12 experiments were rejected and r11 restored | A second QCA setup can be expected during address provisioning; fixed delays have not fixed the timeout | Capture HCI/IBS/UART/power sequencing; see [investigation](bluetooth-7.3.md) |
| `bam-dma-engine ... -22` | Crypto BAM clock ID exists in DT but is absent from GCC provider; fallback requires missing channel/EE counts; neither crypto device nor BAM is bound | Unavailable crypto accelerator path; QCE is behind `BROKEN` on ARCH_QCOM due to secure-world races; separate from IPA BAM | Establish ownership before enabling hardware crypto; see [crypto BAM investigation](cryptobam-7.3.md) |
| `pclk0_clk_src`/`pclk1_clk_src` RCG warning | Latest live capture retains four complete stacks (two of each source), all through fbcon DSI pixel-rate setup; continuous logs from s2idle transitions show no new pclk messages and sampled rates remain 148866500 Hz | No root cause or fix established; one successful resume does not prove boot-only behavior | Capture failure-time parent/RCG/PLL state and compare a narrowly scoped sequencing candidate |
| Missing `board-2.bin` | ath10k uses private `board.bin` from `system` and Wi-Fi starts | Firmware dependency on this device | Preserve per-device board data and record regulatory country |
| GNSS unavailable in production | v17 RAM image ran MSS/rmtfs/TFTP and exposed QRTR Location/PDS v2 and QMI LOC; start/stop passed, no position/SV in 90 s | Transport through LOC demonstrated; antenna fix unproven | Acquire satellite/position reports outdoors with the diagnostic image |
| LTE production boundary | production DT MSS disabled; `CONFIG_GNSS`/`CONFIG_WWAN` disabled; `CONFIG_QCOM_IPA=m` but no IPA platform device; diagnostic v63 DT enables MSS | production data path is intentionally unavailable; no SIM/registration/data claim | use the MSS diagnostic image for staged QMI/SIM/registration and IPA validation |

A warning is not a demonstrated regression or a completed fix. Change a status
only after a controlled reproduction or a comparison testing one hypothesis.
