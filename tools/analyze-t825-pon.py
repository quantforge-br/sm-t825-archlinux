#!/usr/bin/env python3
"""Decode a read-only PM8994 PON snapshot (tools/t825-pmic-pon-snapshot.sh)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PON_REASON1 = ["HARD_RESET", "SMPL", "RTC", "DC", "USB", "PON1", "CBL", "KPD"]
POFF_REASON1 = ["SOFT", "PS_HOLD", "PMIC_WD", "GP1", "GP2", "KPDPWR_AND_RESIN",
                "RESIN_N", "KPDPWR_N"]
REQUIRED = list(range(0x800, 0x810)) + list(range(0x854, 0x859))
GEN1_SUBTYPES = {0x01: "PON_PRIMARY", 0x02: "PON_SECONDARY", 0x03: "PON_1REG"}


def bits(value: int, names: list[str]) -> list[str]:
    return [name for index, name in enumerate(names) if value >> index & 1]


def decode(text: str) -> dict[str, object]:
    regs: dict[int, int] = {}
    for reg, val in re.findall(r"^([0-9a-f]{4}): ([0-9a-fX]{2})$", text, re.M):
        if "X" in val:
            raise ValueError(f"register {reg} is unreadable")
        if int(reg, 16) in regs:
            raise ValueError(f"duplicate register {reg}")
        regs[int(reg, 16)] = int(val, 16)
    missing = [hex(r) for r in REQUIRED if r not in regs]
    if missing or set(regs) - set(REQUIRED):
        raise ValueError(f"unexpected register set; missing {missing}")
    if regs[0x804] != 0x01:
        raise ValueError(f"PON peripheral type {regs[0x804]:#x} is not 0x01")
    boot = re.search(r"^boot_id=(\S+)$", text, re.M)
    if not boot:
        raise ValueError("boot_id missing")
    subtype = regs[0x805]
    poff = bits(regs[0x80C], POFF_REASON1)
    return {
        "boot_id": boot.group(1),
        "pon_revision2": hex(regs[0x801]),
        "pon_subtype": hex(subtype),
        "pon_generation": "gen1" if subtype in GEN1_SUBTYPES else "not-gen1",
        "pon_reason1": hex(regs[0x808]),
        "pon_reason1_bits": bits(regs[0x808], PON_REASON1),
        "poff_reason1": hex(regs[0x80C]),
        "poff_reason1_bits": poff,
        "poff_reason2": hex(regs[0x80D]),
        "last_poff_pmic_watchdog": "PMIC_WD" in poff,
        "last_poff_ps_hold": "PS_HOLD" in poff,
        "wd_s1_timer": regs[0x854],
        "wd_s2_timer": regs[0x855],
        "wd_s2_ctl_reset_type": hex(regs[0x856]),
        "wd_enabled": bool(regs[0x857] & 0x80),
        "wd_s2_ctl2": hex(regs[0x857]),
        "wd_pet": hex(regs[0x858]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = decode(args.snapshot.read_text())
    data = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(data)
    sys.stdout.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
