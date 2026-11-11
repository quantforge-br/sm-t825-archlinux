#!/usr/bin/env python3
"""Classify frozen Bluetooth trace evidence; never access hardware directly."""
import argparse
import importlib.util
import json
from pathlib import Path
import re


def address_provisioning_ready(text):
    """Require hci0's supported and missing public-address option together."""
    blocks = re.split(r"(?=^hci\d+:)", text, flags=re.MULTILINE)
    controllers = [b for b in blocks if re.match(r"hci0:\s+Unconfigured controller\s*\n", b)]
    if len(controllers) != 1:
        return False
    options = re.findall(r"^\s*(supported|missing) options:\s*([^\n]*)", controllers[0], re.MULTILINE)
    values = dict(options)
    return (len(options) == 2 and set(values) == {"supported", "missing"}
            and "public-address" in values["supported"].split()
            and values["missing"].split() == ["public-address"])


def classify_kernel(report):
    spec = importlib.util.spec_from_file_location("validate", Path(__file__).with_name("t825-validate.py"))
    validate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate)
    try:
        before = (report / "kernel.before").read_text()
        after = (report / "kernel.after").read_text()
        # The shared helper accepts an empty append baseline; a hardware trace
        # must establish a real baseline and a nonempty final capture first.
        if not before.strip() or not after.strip():
            raise validate.Blocked("empty kernel capture")
        delta, rotated = validate.kernel_delta(before, after)
    except (OSError, validate.Blocked) as exc:
        return {"classification": "kernel_continuity_unproven", "reason": str(exc)}
    (report / "kernel.delta").write_text(delta)
    faults = re.findall(r"^.*Opcode 0x0c03 failed: -110.*$", delta, re.MULTILINE | re.IGNORECASE)
    return {"classification": "hci_reset_timeout" if faults else "no_new_hci_reset_timeout",
            "new_reset_timeouts": len(faults), "rotated": rotated, "overlap_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["ready", "kernel"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.mode == "ready":
        return 0 if address_provisioning_ready(args.path.read_text()) else 1
    result = classify_kernel(args.path)
    (args.path / "kernel-evidence.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.path / "kernel.classification").write_text(result["classification"] + "\n")
    return 0 if result["classification"] == "no_new_hci_reset_timeout" else 1


if __name__ == "__main__":
    raise SystemExit(main())
