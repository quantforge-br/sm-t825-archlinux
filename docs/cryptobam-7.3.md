# MSM8996 crypto BAM probe boundary

Read-only source/runtime investigation, 2026-11-11 UTC. Report:
`artifacts/roadmap-7.3/cryptobam-source-20261111T003515Z/`.
The installed r1 boot ID remained
`40c0ce08-7afd-4a29-9ee5-1c8331f47a91` throughout collection. No module,
clock, register or boot-mode changes were made.

The boot log reports `num-channels unspecified in dt`, followed by probe
failure `-22`, for `644000.dma-controller`. This is the crypto engine's BAM,
not the IPA BAM described at `0x684000` in the downstream modem reference.
It should not be used as evidence that IPA/LTE has probed or failed.

## Why the channel-count path is reached

The live DT and reviewed `msm8996.dtsi` contain `clocks` and `clock-names` for
this controller. The source specifies `GCC_CE1_CLK`, `bam_clk`, execution
environment 0 and `qcom,controlled-remotely`; it omits `num-channels` and
`qcom,num-ees`.

`GCC_CE1_CLK` is defined as ID 164 in the binding header, but there is no
corresponding clock entry in `gcc_msm8996_clocks[]`. CE1 AXI/AHB IDs 165/166
are also absent from that table. The QCOM clock provider returns NULL for an
unpopulated entry. In the BAM probe, the remote-control flag selects optional
clock lookup; a missing clock then requires the DT to supply both channel
and execution-environment counts. The first missing property produces the
observed error before BAM initialization or channel registration.

This explains why adding a clock property again would not help: the property
already exists. It also means a guessed channel count would merely advance
past this check without establishing power, ownership or reset behavior.
The DT binding permits either a clock description or the remote-controller
count properties, so schema validation alone does not establish that the
referenced provider implements its clock ID.

## Consumer and implementation decision

The DT crypto consumer at `67a000.crypto` references BAM channels 6 and 7.
Neither the BAM nor crypto device has a bound driver in the live system.
The installed config has BAM DMA enabled but no QCE configuration entry.
The reviewed 7.3 Kconfig explains why: `CRYPTO_DEV_QCE` depends on
`(BROKEN && ARCH_QCOM) || COMPILE_TEST`. Its help explicitly describes missing
hardware access control and races with the secure world, as well as worse
performance than CPU cryptography.

Do not remove the BROKEN dependency, invent channel/EE counts or add CE clock
register writes to silence this warning. The source/runtime evidence identifies
an unavailable crypto accelerator path; it does not demonstrate a failure of
an active peripheral or require hardware crypto for the current port.

If hardware crypto becomes a requirement, first establish secure-world
arbitration and ownership for the exact firmware, then reconcile CE clock
control and BAM resources. Only after that should a separate recovered RAM
diagnostic attempt driver binding and known-answer crypto tests. Disabling an
unused DT node could suppress the log but would not implement compatibility.
