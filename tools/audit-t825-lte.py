#!/usr/bin/env python3
"""Audit the T825 LTE/GNSS production boundary without enabling the modem."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path("/tmp/t825-config")
DEFAULT_ACTIVE = ROOT / "artifacts/roadmap-7.3/package-inspection-20261110T083710Z/normal/boot/dtbs/qcom/msm8996-samsung-gts3llte.dtb"
DEFAULT_DIAG = ROOT / "artifacts/roadmap-7.3/gnss-ram-20261108/v63-mss-loc-retry-ro/dtbs/msm8996-samsung-gts3llte.dtb"


def dts_text(path: Path) -> str:
    # Normalize source fixtures as well as DTBs. This removes comments and
    # prevents a commented-out IPA node from counting as hardware description.
    return subprocess.run(
        ["dtc", "-I", "dtb" if path.suffix == ".dtb" else "dts", "-O", "dts", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout


def ipa_node_present(text: str) -> bool:
    """Detect an IPA node in normalized DTS, not a live platform device."""
    return bool(re.search(r'^\s*(?:[\w]+:\s*)?(?:qcom,)?ipa(?:@[\da-fA-F]+)?\s*\{', text, re.M))


def status(text: str) -> str:
    match = re.search(r"remoteproc@2080000\s*\{(?P<body>.*?)\n\s*\};", text, re.S)
    if not match:
        return "absent"
    found = re.search(r'\bstatus\s*=\s*"([^"]+)"', match.group("body"))
    return found.group(1) if found else "implicit-okay"


def config_state(config: str, symbol: str) -> str:
    if re.search(rf"^# CONFIG_{re.escape(symbol)} is not set$", config, re.M):
        return "disabled"
    match = re.search(rf"^CONFIG_{re.escape(symbol)}=(.*)$", config, re.M)
    return match.group(1) if match else "missing"


def audit(config_path: str, active_path: str, diagnostic_path: str) -> dict[str, object]:
    config = Path(config_path).read_text()
    active = dts_text(Path(active_path))
    diagnostic = dts_text(Path(diagnostic_path))
    states = {name: config_state(config, name) for name in ("GNSS", "WWAN", "QCOM_IPA", "QCOM_QMI_HELPERS")}
    result = {
        "production": {
            "mss_status": status(active),
            "config": states,
            "ipa_dt_node_present": ipa_node_present(active),
            "ipa_runtime_probe": "not-observed-by-offline-audit",
        },
        "diagnostic": {
            "mss_status": status(diagnostic),
            "dtb": diagnostic_path,
        },
        "decision": "transport-only-diagnostic; do-not-enable-production-LTE",
        "reasons": [
            "Production MSS DT status: " + status(active) + ".",
            "Production config: " + ", ".join(name + "=" + value for name, value in states.items()) + ".",
            "DT node presence does not prove a bound IPA driver or a working data path.",
            "A diagnostic DT with MSS enabled is available separately; it does not prove SIM registration or an IPA data path.",
        ],
        "next_steps": [
            "Run the MSS diagnostic image through qmicli service, SIM, registration and data-session stages.",
            "Validate IPA v2.5 against the modem firmware before enabling any production data path.",
        ],
    }
    if result["production"]["mss_status"] != "disabled":
        result["decision"] = "unexpected-production-MSS-state"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--active", default=str(DEFAULT_ACTIVE))
    parser.add_argument("--diagnostic", default=str(DEFAULT_DIAG))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(audit(args.config, args.active, args.diagnostic), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
