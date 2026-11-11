#!/usr/bin/env python3
"""Run the same gpuhang workload on the running kernel for an r1/r2 comparison.

Run as the graphical user on installed Arch with passwordless sudo for
journalctl. Each repeat runs a short finite draw, long finite draws that keep
the GPU busy past the hangcheck period, and one infinite draw. A kernel with
a5xx hangcheck progress detection (patch 0204) should let finite draws
finish and still reset the infinite one. Hyprland's PID must not change.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

DRAWS = (('short', 2000), ('long', 60000000), ('longer', 120000000), ('hang', 1))


def kernel_lines(since):
    out = subprocess.run(['sudo', '-n', 'journalctl', '-k', '--no-pager', '-o', 'short-monotonic',
                          '--since', since], capture_output=True, text=True, timeout=30).stdout
    return [line for line in out.splitlines() if re.search(r'msm|adreno|gpu|hangcheck|recover', line, re.I)]


def hyprland():
    out = subprocess.run(['pgrep', '-x', 'Hyprland'], capture_output=True, text=True).stdout.split()
    return out[0] if out else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('out')
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5:
        parser.error('repeats must be 1..5')
    binary = os.path.abspath(args.binary)
    summary = {'uname': list(os.uname()), 'boot_id': open('/proc/sys/kernel/random/boot_id').read().strip(),
               'binary_sha256': hashlib.sha256(open(binary, 'rb').read()).hexdigest(),
               'msm_module': subprocess.run(['sh', '-c', 'sha256sum $(modinfo -n msm)'], capture_output=True,
                                            text=True).stdout.split()[:1],
               'hyprland_before': hyprland(), 'runs': []}
    for repeat in range(1, args.repeats + 1):
        for name, iters in DRAWS:
            since = time.strftime('%Y-%m-%d %H:%M:%S')
            time.sleep(1.1)
            try:
                proc = subprocess.run([binary, str(iters)], capture_output=True, text=True, timeout=60)
                rc, stdout = proc.returncode, proc.stdout
            except subprocess.TimeoutExpired as exc:
                rc, stdout = 'timeout', (exc.stdout or b'').decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            time.sleep(3)
            lines = kernel_lines(since)
            elapsed = re.search(r'elapsed ([0-9.]+) s', stdout)
            status = re.search(r'reset status (0x[0-9a-f]+)', stdout)
            summary['runs'].append({'repeat': repeat, 'draw': name, 'iters': iters, 'rc': rc,
                                    'elapsed_s': float(elapsed.group(1)) if elapsed else None,
                                    'reset_status': status.group(1) if status else None,
                                    'guilty': 'GUILTY' in stdout,
                                    'kernel_hangcheck': any('hangcheck' in line for line in lines),
                                    'kernel_lines': lines[:12], 'stdout': stdout})
            time.sleep(2)
    summary['hyprland_after'] = hyprland()
    summary['hyprland_same_process'] = summary['hyprland_before'] is not None and \
        summary['hyprland_before'] == summary['hyprland_after']
    with open(args.out, 'w') as handle:
        json.dump(summary, handle, indent=2)
    for run in summary['runs']:
        print(run['repeat'], run['draw'], run['rc'], run['elapsed_s'], run['reset_status'], run['guilty'],
              run['kernel_hangcheck'])
    print('hyprland_same_process', summary['hyprland_same_process'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
