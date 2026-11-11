#!/usr/bin/env python3
"""Exercise reboot orchestration with fake transports; never contact hardware."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LEGACY_RUNNER = Path(__file__).resolve().parents[1] / 'artifacts/roadmap-7.3/bluetooth-20boot-20261111T124000Z/historical-runner-current.sh'

FAKE_SSH = r'''#!/usr/bin/python3
import os
from pathlib import Path
import sys
import uuid

root = Path(os.environ['FAKE_ROOT'])
state = root / 'reboots'
count = int(state.read_text()) if state.exists() else 0
cmd = sys.argv[-1]
mode = os.environ['FAKE_SCENARIO']
controller = 'Controller 12:34:56:78:9A:BC (public)\n'
hci = 'hci0:\tPrimary controller\n\taddr 12:34:56:78:9A:BC version 8\n'
if cmd == 'sudo -n systemctl reboot':
    state.write_text(str(count + 1))
elif cmd == 'cat /proc/sys/kernel/random/boot_id':
    print(uuid.UUID(int=count + 1))
elif cmd == 'uname -v':
    print('#2-postmarketos-qcom-msm8996 SMP PREEMPT installed-r1')
elif cmd.startswith('sha256sum '):
    for filename in cmd.split()[1:]:
        changed = mode == 'mutation' and count > 0 and filename.endswith('.service')
        print(('b' if changed else 'a') * 64, filename)
elif cmd == 'bluetoothctl show; btmgmt --index 0 info':
    if mode != 'no_baseline':
        print(controller + hci)
elif cmd.startswith('test "$(systemctl show'):
    print(hci + controller)
elif cmd.startswith('set +e\n'):
    print('--- boot_id ---')
    print(uuid.UUID(int=count + 1))
    print(controller + hci)
    if mode == 'fault':
        print('Bluetooth: hci0: Opcode 0x0c03 failed: -110')
    if mode == 'collection_failure':
        sys.exit(1)
else:
    print('Unexpected fake SSH command: ' + cmd, file=sys.stderr)
    sys.exit(97)
'''


class RebootGate(unittest.TestCase):
    def run_gate(self, scenario, **overrides):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'tools').mkdir()
        shutil.copy2(LEGACY_RUNNER, root / 'tools/t825-bluetooth-auto-cycle.sh')
        bins = root / 'bin'
        bins.mkdir()
        for name, code in {
            'ssh': FAKE_SSH,
            'sleep': '#!/bin/sh\nexit 0\n',
            'fastboot': '#!/bin/sh\necho "unexpected fastboot" >&2\nexit 97\n',
        }.items():
            path = bins / name
            path.write_text(code)
            path.chmod(0o755)
        image = root / 'normal.img'
        image.write_bytes(b'fake image, never sent to hardware')
        report = root / 'artifacts/roadmap-7.3/report'
        report.parent.mkdir(parents=True)
        env = os.environ.copy()
        env.update(PATH=str(bins) + os.pathsep + env['PATH'], FAKE_ROOT=str(root),
                   FAKE_SCENARIO=scenario, T825_SOURCE_ROOT=str(root),
                   T825_BT_REPORT_DIR=str(report), T825_BT_CYCLES='2',
                   T825_RUNNER_SNAPSHOT='0')
        env.pop('T825_EXPECTED_UNAME_V', None)
        env.pop('T825_BT_REQUIRE_RAM_BOOT', None)
        env.update(overrides)
        result = subprocess.run(['bash', str(root / 'tools/t825-bluetooth-auto-cycle.sh'), str(image)],
                                env=env, capture_output=True, text=True, timeout=10)
        reboots = int((root / 'reboots').read_text()) if (root / 'reboots').exists() else 0
        return result, reboots, report

    def test_success_finishes_running_without_extra_final_reboot(self):
        result, reboots, report = self.run_gate('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(reboots, 2)
        self.assertEqual((report / 'results.tsv').read_text().count('\tPASS\tRUNNING\t'), 2)
        self.assertTrue((report / 'runner.sha256').is_file())
        self.assertEqual((report / 'exit-status.txt').read_text().strip(), '0')

    def test_kernel_fault_stops_before_another_reboot(self):
        result, reboots, report = self.run_gate('fault')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(reboots, 1)
        self.assertIn('\tFAULT\t', (report / 'results.tsv').read_text())
        self.assertTrue((report / 'final-boot-id.txt').read_text().strip())

    def test_payload_change_invalidates_cycle_and_stops(self):
        result, reboots, report = self.run_gate('mutation')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(reboots, 1)
        self.assertIn('\tIDENTITY_CHANGED\t', (report / 'results.tsv').read_text())
        self.assertTrue((report / 'payload-1-postboot.sha256').is_file())

    def test_failed_collection_cannot_pass_on_partial_controller_output(self):
        result, reboots, report = self.run_gate('collection_failure')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(reboots, 1)
        self.assertIn('\tFAULT\t', (report / 'results.tsv').read_text())

    def test_missing_baseline_controller_refuses_reboot(self):
        result, reboots, report = self.run_gate('no_baseline')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(reboots, 0)
        self.assertIn('No baseline controller', result.stderr)
        self.assertTrue((report / 'exit-status.txt').is_file())

    def test_r1_must_not_pass_as_r2_when_release_is_identical(self):
        result, reboots, report = self.run_gate(
            'success', T825_EXPECTED_UNAME_V='#3-postmarketos-qcom-msm8996 SMP PREEMPT candidate-r2')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(reboots, 1)
        self.assertIn('\tKERNEL_IDENTITY_MISMATCH\t', (report / 'results.tsv').read_text())
        self.assertIn('installed-r1', (report / 'kernel-version-1.txt').read_text())

    def test_requested_ram_boot_cannot_pass_on_direct_reboot(self):
        result, reboots, report = self.run_gate('success', T825_BT_REQUIRE_RAM_BOOT='1')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(reboots, 1)
        self.assertIn('\tRAM_BOOT_NOT_USED\t', (report / 'results.tsv').read_text())
        self.assertEqual((report / 'boot-route-1.txt').read_text(), 'DIRECT_REBOOT\n')

    def test_matching_complete_build_identity_can_pass(self):
        result, reboots, report = self.run_gate(
            'success', T825_EXPECTED_UNAME_V='#2-postmarketos-qcom-msm8996 SMP PREEMPT installed-r1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(reboots, 2)

    def test_invalid_ram_boot_option_refuses_reboot(self):
        result, reboots, report = self.run_gate('success', T825_BT_REQUIRE_RAM_BOOT='yes')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(reboots, 0)


if __name__ == '__main__':
    unittest.main()
