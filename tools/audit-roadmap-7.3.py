#!/usr/bin/env python3
"""Audit unchecked ROADMAP gates and referenced local evidence.

This is a read-only host audit. It never boots, flashes or changes the tablet.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HARDWARE_WORDS = re.compile(
    r"hardware|tablet|boot|fastboot|adb|ssh|watchdog|microphone|speaker|ctia|"
    r"power|gpu|gnss|satellite|lte|sim|qmi|ipa|rollback|headphone|suspend",
    re.IGNORECASE,
)


def command(*args: str, timeout: float = 6.0) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout


def succeeds(*args: str, timeout: float = 6.0) -> bool:
    try:
        return subprocess.run(args, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout,
                              check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def transport_state() -> dict[str, object]:
    fastboot = command("fastboot", "devices")
    adb = command("adb", "devices")
    usb = command("lsusb")
    ncm = []
    net_root = Path("/sys/class/net")
    if net_root.is_dir():
        for interface in sorted(net_root.iterdir()):
            if interface.name.startswith(("usb", "enp120")):
                carrier = interface / "carrier"
                ncm.append({
                    "interface": interface.name,
                    "carrier": carrier.read_text().strip() if carrier.is_file() else None,
                })
    return {
        "fastboot": [line for line in fastboot.splitlines() if line.strip()],
        "adb": [line for line in adb.splitlines()
                if line.strip() and not line.startswith("List of devices")],
        "usb": [line for line in usb.splitlines()
                if re.search(r"04e8|18d1|Samsung|Google", line, re.I)],
        "ssh_reachable": succeeds("ssh", "-o", "BatchMode=yes",
                                   "-o", "ConnectTimeout=3", "tabs3", "true"),
        "ncm_interfaces": ncm,
    }


BLOCKED = re.compile(r"\*\*BLOCKED\*\*")
ARTIFACT = re.compile(r"`(artifacts/[^`]+)`")


def gate_body(lines: list[str], start: int) -> str:
    """Return a gate's text up to the next list item, heading or blank line."""
    body = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith(("- [", "#")):
            break
        body.append(line)
    return "\n".join(body)


def audit(roadmap: Path, *, collect_transport: bool = True) -> dict[str, object]:
    text = roadmap.read_text()
    lines = text.splitlines()
    open_items = []
    for index, line in enumerate(lines):
        match = re.match(r"^- \[ \] (.*)$", line)
        if match:
            item = match.group(1).strip()
            body = gate_body(lines, index)
            # A BLOCKED record counts only with local evidence attached.
            blocked = bool(BLOCKED.search(body)) and bool(ARTIFACT.search(body))
            open_items.append({
                "line": index + 1,
                "text": item,
                "scope": "hardware" if HARDWARE_WORDS.search(item) else "offline",
                "state": "blocked" if blocked else "open",
            })
    refs = sorted(set(ARTIFACT.findall(text)))
    evidence = [{"path": path, "exists": (ROOT / path).exists()} for path in refs]
    missing = [entry["path"] for entry in evidence if not entry["exists"]]
    unresolved = [item for item in open_items if item["state"] == "open"]
    if missing or unresolved:
        status = "INCOMPLETE"
    else:
        status = "PASS" if not open_items else "RESOLVED_WITH_BLOCKERS"
    return {
        "status": status,
        "roadmap": str(roadmap),
        "open_gate_count": len(unresolved),
        "blocked_gate_count": len(open_items) - len(unresolved),
        "open_gates": unresolved,
        "blocked_gates": [item for item in open_items if item["state"] == "blocked"],
        "artifact_reference_count": len(evidence),
        "missing_artifacts": missing,
        "transport": transport_state() if collect_transport else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roadmap", type=Path, default=ROOT / "ROADMAP.md")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.roadmap.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
