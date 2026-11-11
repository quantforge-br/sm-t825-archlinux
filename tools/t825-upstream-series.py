#!/usr/bin/env python3
"""Classify local kernel patches for upstream submission (prepare only, never send).

Generic patches touch kernel code, bindings or SoC-wide DTS; T825-specific
patches touch only the gts3l board DTS. Diagnostics (*.disabled), backports and
bring-up aids are excluded with a reason. Each candidate is checked with the
kernel tree's checkpatch.pl and grouped into per-subsystem series.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

EXCLUDED = {
    "0006": "bring-up aid (rgb_swap/defer_hs_clk module parameters)",
    "0007": "debugfs test-pattern trigger for bring-up only",
    "0204": "backport of upstream commit 65222fbe8; already upstream",
}
BOARD = re.compile(r"^arch/arm64/boot/dts/qcom/.*gts3l")


def paths(text: str) -> list[str]:
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/", text, re.M)))


def subject(text: str) -> str:
    match = re.search(r"^Subject: (.*(?:\n [^\n]*)*)", text, re.M)
    if not match:
        raise ValueError("missing Subject")
    value = " ".join(line.strip() for line in match.group(1).splitlines())
    return re.sub(r"^\[PATCH[^\]]*\]\s*", "", value)


def topic(files: list[str]) -> str:
    first = files[0]
    for prefix, name in (("drivers/gpu/drm/panel", "drm-panel"),
                         ("drivers/gpu/drm/msm", "drm-msm"),
                         ("drivers/gpu/drm", "drm"), ("sound/", "asoc"),
                         ("drivers/power/supply", "power-supply"),
                         ("drivers/extcon", "extcon"),
                         ("drivers/usb", "usb"), ("drivers/input", "input"),
                         ("drivers/media", "media"), ("drivers/iio", "iio"),
                         ("drivers/mfd", "mfd"), ("drivers/i2c", "i2c"),
                         ("drivers/clk", "clk"), ("drivers/cpuidle", "cpuidle"),
                         ("drivers/pci", "pci"), ("net/qrtr", "qrtr"),
                         ("arch/arm64/boot/dts", "arm64-dts")):
        if any(f.startswith(prefix) for f in files):
            return name
    if first.startswith("Documentation/devicetree/bindings/"):
        part = first.split("/")[3]
        return {"sound": "asoc", "display": "drm-panel",
                "power": "power-supply"}.get(part, part)
    return first.split("/")[0]


def classify(name: str, text: str) -> tuple[str, str]:
    prefix = name[:4]
    if name.endswith(".disabled"):
        return "excluded", "private opt-in diagnostic"
    if name.startswith("m"):
        return "excluded", "carried from postmarketOS/other authors"
    if prefix in EXCLUDED:
        return "excluded", EXCLUDED[prefix]
    files = paths(text)
    if not files:
        raise ValueError(f"{name}: no diff")
    if all(BOARD.match(f) for f in files):
        return "t825-specific", "board DTS only"
    if any(BOARD.match(f) for f in files):
        return "mixed", "mixes board DTS with generic files; split before sending"
    return "generic", "kernel code, bindings or SoC DTS"


def blockers(text: str) -> list[str]:
    """Return reasons a prepared patch cannot be sent as-is."""
    found = []
    author = re.search(r"^From: .*<([^>]+)>", text, re.M)
    if not author or author.group(1).endswith("@example.com"):
        found.append("placeholder author address")
    if re.search(r"^Signed-off-by: .*@example\.com>", text, re.M):
        found.append("placeholder Signed-off-by address")
    if re.search(r"^Co-Authored-By: ", text, re.M):
        found.append("AI co-author trailer must follow the kernel's tool attribution rules")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch_dir", type=Path)
    parser.add_argument("--kernel-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    checkpatch = args.kernel_source / "scripts/checkpatch.pl"
    args.output_dir.mkdir(parents=True, exist_ok=False)
    entries = []
    for patch in sorted(args.patch_dir.glob("[0-9m]*.patch*")):
        text = patch.read_text()
        kind, reason = classify(patch.name, text)
        entry = {"patch": patch.name, "subject": subject(text), "class": kind,
                 "reason": reason, "files": paths(text),
                 "sha256": hashlib.sha256(text.encode()).hexdigest()}
        if kind == "generic":
            entry["topic"] = topic(entry["files"])
            run = subprocess.run(
                ["perl", str(checkpatch), "--no-tree", "--terse", "--strict",
                 "--ignore", "FILE_PATH_CHANGES", str(patch.resolve())],
                # Inside a git work tree checkpatch treats the .patch file as
                # a changed source file, so run it from a neutral directory.
                cwd="/", capture_output=True, text=True, timeout=120, check=False)
            counts = re.search(r"total: (\d+) errors, (\d+) warnings, (\d+) checks",
                               run.stdout)
            entry["checkpatch"] = ({"errors": int(counts[1]), "warnings": int(counts[2]),
                                    "checks": int(counts[3])} if counts else
                                   {"unparsed": run.stdout[-400:]})
            series = args.output_dir / "series" / entry["topic"]
            series.mkdir(parents=True, exist_ok=True)
            shutil.copy2(patch, series / patch.name)
            if run.stdout.strip():
                (series / (patch.name + ".checkpatch.txt")).write_text(run.stdout)
            entry["blockers"] = blockers(text)
        entries.append(entry)
    generic = [e for e in entries if e["class"] == "generic"]
    clean = [e for e in generic if e["checkpatch"].get("errors") == 0
             and e["checkpatch"].get("warnings") == 0]
    summary = {
        "status": "PREPARED_NOT_SENT",
        "note": "Submission requires the maintainer's explicit decision; nothing was sent.",
        "counts": {k: sum(e["class"] == k for e in entries)
                   for k in ("generic", "t825-specific", "mixed", "excluded")},
        "checkpatch_clean_generic": len(clean),
        "send_blockers": sorted({b for e in generic for b in e["blockers"]}),
        "topics": {t: [e["patch"] for e in generic if e["topic"] == t]
                   for t in sorted({e["topic"] for e in generic})},
        "patches": entries,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("status", "counts",
                                              "checkpatch_clean_generic")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
