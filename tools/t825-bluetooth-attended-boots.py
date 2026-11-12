#!/usr/bin/env python3
"""Operator-attended Bluetooth reboot series on the installed kernel.

Installed boots have no independent recovery until the tablet watchdog is
validated, so this runner refuses to start without --operator-present and
stops (never retries) when a boot does not return within --return-timeout.
Each cycle reboots, waits for a new boot ID, waits for gts3-bdaddr to finish
and the controller to report the baseline address, then classifies the boot
from its kernel log. The series stops at the first fault, keeping evidence.
"""
import argparse
import fcntl
import json
import re
import subprocess
import sys
import time
from pathlib import Path

FAULT = re.compile(r'Opcode 0x0c03.*failed: -110|qca.*(timeout|fail)|firmware.*(fail|timeout)', re.I)
BOOT_ID = re.compile(r'^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
ADDR = re.compile(r'^Controller (([0-9A-F]{2}:){5}[0-9A-F]{2}) ', re.I | re.M)


def ssh(target, command, timeout=20):
    try:
        done = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                               '-o', 'ConnectionAttempts=1', target, command],
                              capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout
    except subprocess.TimeoutExpired:
        return 124, ''


def boot_id(target):
    rc, out = ssh(target, 'cat /proc/sys/kernel/random/boot_id', 12)
    out = out.strip()
    return out if rc == 0 and BOOT_ID.match(out) else None


def controller_ready(target, addr):
    rc, out = ssh(target, 'test "$(systemctl show gts3-bdaddr.service -p SubState --value)" = dead && '
                  'test "$(systemctl show gts3-bdaddr.service -p Result --value)" = success && '
                  'btmgmt --index 0 info && bluetoothctl show')
    ok = (rc == 0 and re.search(r'^hci0:.*Primary controller', out, re.M) is not None
          and f'Controller {addr} '.lower() in out.lower()
          and re.search(rf'^\s*addr {re.escape(addr)} ', out, re.M | re.I) is not None)
    return ok, out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--operator-present', action='store_true')
    parser.add_argument('--cycles', type=int, default=20)
    parser.add_argument('--return-timeout', type=int, default=240)
    parser.add_argument('--ready-timeout', type=int, default=90)
    parser.add_argument('--target', default='tabs3')
    args = parser.parse_args()
    if not args.operator_present:
        parser.error('installed-boot series need an operator; pass --operator-present')
    if not (1 <= args.cycles <= 30 and 60 <= args.return_timeout <= 600 and 30 <= args.ready_timeout <= 300):
        parser.error('bounded parameters required')
    args.out.mkdir(parents=True, exist_ok=True)
    lock = open('artifacts/roadmap-7.3/tablet-test.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('another hardware test holds the tablet lock', file=sys.stderr)
        return 2
    summary = {'status': 'RUNNING', 'cycles': [], 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}

    def save():
        (args.out/'summary.json').write_text(json.dumps(summary, indent=2) + '\n')

    current = boot_id(args.target)
    rc, before = ssh(args.target, 'uname -v; sha256sum /boot/vmlinuz-t825 /usr/sbin/gts3-bdaddr '
                     '/usr/lib/systemd/system/gts3-bdaddr.service /usr/lib/udev/rules.d/90-gts3-bdaddr.rules; '
                     'bluetoothctl show; btmgmt --index 0 info')
    (args.out/'baseline.txt').write_text(before)
    match = ADDR.search(before)
    if not current or rc != 0 or not match:
        summary['status'] = 'NO_BASELINE_CONTROLLER'
        save()
        return 1
    addr = summary['address'] = match.group(1)
    summary['baseline_boot_id'] = current
    save()
    for cycle in range(1, args.cycles + 1):
        entry = {'cycle': cycle, 'previous_boot_id': current, 'reboot_at': time.strftime('%H:%M:%S')}
        summary['cycles'].append(entry)
        save()
        ssh(args.target, 'sudo -n systemctl reboot', 15)
        time.sleep(20)
        deadline, new = time.monotonic() + args.return_timeout, None
        while time.monotonic() < deadline:
            new = boot_id(args.target)
            if new and new != current:
                break
            new = None
            time.sleep(5)
        if not new:
            entry['result'] = 'NO_RETURN'
            summary['status'] = 'ATTENTION_NO_RETURN_OPERATOR_NEEDED'
            save()
            return 1
        entry['boot_id'], entry['returned_at'] = new, time.strftime('%H:%M:%S')
        current = new
        deadline, ready, probe = time.monotonic() + args.ready_timeout, False, ''
        while time.monotonic() < deadline and not ready:
            ready, probe = controller_ready(args.target, addr)
            if not ready:
                time.sleep(5)
        _, kernel = ssh(args.target, 'uname -v; cat /proc/uptime; journalctl -k -b0 --no-pager -o short-monotonic | '
                        'grep -E "Bluetooth|hci0|Opcode 0x0c03|Frame reassembly|qca|serdev|uart" ; '
                        'journalctl -b0 -u gts3-bdaddr.service -u bluetooth.service --no-pager -o short-monotonic', 30)
        (args.out/f'boot-{cycle:02d}.txt').write_text(probe + '\n--- kernel ---\n' + kernel)
        faults = [line for line in kernel.splitlines() if FAULT.search(line)]
        entry.update({'controller_ready': ready, 'faults': faults,
                      'setup_completions': kernel.count('QCA setup on UART is completed'),
                      'frame_reassembly_84': kernel.count('Frame reassembly failed (-84)'),
                      'result': 'PASS' if ready and not faults else 'FAULT'})
        save()
        if entry['result'] != 'PASS':
            summary['status'] = 'FAULT_AT_CYCLE_%d' % cycle
            save()
            return 1
        time.sleep(5)
    summary['status'] = 'PASS_%d_OF_%d' % (args.cycles, args.cycles)
    save()
    return 0


if __name__ == '__main__':
    sys.exit(main())
