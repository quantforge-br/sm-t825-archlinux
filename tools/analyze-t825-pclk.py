#!/usr/bin/env python3
"""Parse SM-T825 pclk warning stacks and classify their call boundary."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

CLOCK_RE = re.compile(r'\b(pclk[01]_clk_src): rcg didn.t update')
STACK_RE = re.compile(r'(?m)^\[\s*([0-9.]+)\] (?:Call trace:|pc : update_config)')
REQUIRED = ('update_config', 'clk_rcg2_configure', 'clk_pixel_set_rate',
            'dsi_link_clk_set_rate_6g', 'msm_dsi_host_power_on',
            '__drm_fb_helper_initial_config_and_unlock')

def classify(text: str) -> dict:
    lines = text.splitlines()
    warnings = []
    for i, line in enumerate(lines):
        m = CLOCK_RE.search(line)
        if not m:
            continue
        window = '\n'.join(lines[i:i+90])
        stack = [name for name in REQUIRED if name in window]
        warnings.append({'clock': m.group(1), 'line': i + 1,
                         'timestamp': line.split(']')[0].lstrip('['),
                         'required_frames': stack,
                         'complete_boundary': len(stack) == len(REQUIRED)})
    clocks = [w['clock'] for w in warnings]
    return {
        'warning_count': len(warnings),
        'warnings': warnings,
        'clock_counts': {c: clocks.count(c) for c in sorted(set(clocks))},
        'all_complete_boundary': bool(warnings) and all(w['complete_boundary'] for w in warnings),
        'classification': ('fbcon-dsi-pixel-rate-boundary' if warnings and
                           all(w['complete_boundary'] for w in warnings)
                           else 'incomplete-or-unknown'),
        'cause_proven': False,
        'hardware_fix_accepted': False,
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('dmesg', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    result = classify(args.dmesg.read_text(errors='replace'))
    encoded = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end='')
    return 0 if result['warning_count'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
