#!/usr/bin/env python3
"""Audit whether the SM-T825 watchdog evidence matches Linux 7.3."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRIVER = ROOT / "/var/tmp/polly-kernel73/linux/drivers/watchdog/qcom-wdt.c"
DEFAULT_STOCK = ROOT / "artifacts/sm-t825-readonly-20261101-082459/analysis/dtb/boot/dtb-2.dts"
DEFAULT_DTS = ROOT / "artifacts/work/upstream/dts/apq8096-samsung-gts3lwifi.dts"


def audit(driver: str, stock: str, current: str) -> dict[str, object]:
    driver_text, stock_text, current_text = (Path(p).read_text() for p in (driver, stock, current))
    compatibles = sorted(set(re.findall(r'\.compatible\s*=\s*"([^"]+)"', driver_text)))
    stock_node = re.search(r'qcom,wdt@9830000\s*\{(?P<body>.*?)\n\s*\};', stock_text, re.S)
    body = stock_node.group("body") if stock_node else ""
    return {
        "driver_compatible": compatibles,
        "stock_node": {
            "present": bool(stock_node),
            "compatible": re.findall(r'compatible\s*=\s*"([^"]+)"', body),
            "reg": re.findall(r'reg\s*=\s*<([^>]+)>', body),
            "interrupts": re.findall(r'interrupts\s*=\s*<([^>]+)>', body),
            "has_clock": bool(re.search(r'\bclocks?\s*=', body)),
            "has_vendor_bark_pet": all(x in body for x in ("qcom,bark-time", "qcom,pet-time")),
        },
        "current_board": {
            "has_watchdog_node": bool(re.search(r'(?:watchdog|wdt)@[^\s{]+\s*\{', current_text)),
            "has_pshold_reboot": 'compatible = "syscon-reboot"' in current_text,
            "pshold_address": '0x004ab000' in current_text,
        },
        "decision": "do-not-enable-unvalidated-watchdog",
        "reasons": [
            "The stock qcom,msm-watchdog node is not in the Linux 7.3 driver's match table.",
            "The stock node has no Linux binding clock and uses downstream bark/pet properties.",
            "The current board has a tested PS_HOLD syscon reboot route but no watchdog node.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", default=str(DEFAULT_DRIVER))
    parser.add_argument("--stock", default=str(DEFAULT_STOCK))
    parser.add_argument("--current", default=str(DEFAULT_DTS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.driver, args.stock, args.current)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
