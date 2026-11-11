#!/usr/bin/env python3
"""Audit ignored SLIMbus stream transaction returns in the pinned kernel source."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

PATTERNS = {
    "prepare_connect_return_ignored": r"\bslim_connect_port_channel\(rt, port\);",
    "enable_define_return_ignored": r"\bslim_define_channel\(stream, port\);",
    "enable_content_return_ignored": r"\bslim_define_channel_content\(stream, port\);",
    "enable_activate_return_ignored": r"\bslim_activate_channel\(stream, port\);",
    "disable_remove_return_ignored": r"\bslim_deactivate_remove_channel\(stream, &stream->ports\[i\]\);",
}

def audit(source: str) -> dict:
    lines = source.splitlines()
    findings = []
    for name, pattern in PATTERNS.items():
        rx = re.compile(pattern)
        matches = [i + 1 for i, line in enumerate(lines) if rx.search(line)]
        findings.append({"id": name, "count": len(matches), "lines": matches,
                         "return_checked": False})
    return {
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "findings": findings,
        "status": "ignored_slimbus_transaction_returns" if any(f["count"] for f in findings) else "no_matches",
        "production_fix_accepted": False,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.source.read_text(errors="replace"))
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0 if result["status"] != "no_matches" else 1

if __name__ == "__main__":
    raise SystemExit(main())
