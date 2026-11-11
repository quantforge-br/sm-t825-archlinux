#!/usr/bin/env python3
"""Fake-transport tests; never connect to or reboot a tablet."""
import copy
import ast
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cycle', Path(__file__).with_name('t825-readonly-cycle.py'))
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)

def evidence():
    return dict(version='Linux version candidate', pid1='/bin/sh /run/t825-recovery/postpivot-init',
                cmdline='t825.ramdiag t825.direct-init panic=10',
                mounts=['/dev/mmcblk0p44 / btrfs ro,rescue=nologreplay 0 0'],
                devices=[dict(dev='259:12', ro='1'), dict(dev='259:15', ro='1')],
                supervisor_pid='42', supervisor_sha256='expected',
                supervisor_log='armed at 1 deadline 241', handoff_log='direct init start')

class Checks(unittest.TestCase):
    def test_handoff_rejects_wrong_identity_and_writable_members(self):
        cycle.verify_handoff(evidence(), 'Linux version candidate', 'expected', '42')
        for key, value in [('version', 'Linux version r1'), ('supervisor_pid', '43'),
                           ('supervisor_sha256', 'other'), ('pid1', '/sbin/init'),
                           ('devices', [dict(dev='259:12', ro='1')]),
                           ('devices', [dict(dev='259:12', ro='1'), dict(dev='259:15', ro='0')]),
                           ('mounts', ['/dev/mmcblk0p44 / btrfs ro 0 0']),
                           ('mounts', ['/dev/mmcblk0p44 / btrfs rw,rescue=nologreplay 0 0'])]:
            with self.subTest(key=key, value=value):
                data = copy.deepcopy(evidence()); data[key] = value
                with self.assertRaises(ValueError):
                    cycle.verify_handoff(data, 'Linux version candidate', 'expected', '42')

    def observe(self, states):
        tick = [0]
        def ready():
            value = states[tick[0]]; tick[0] += 1; return value
        return cycle.observe_reset(len(states), False, ready, lambda: tick[0], lambda _: None)

    def test_probe_error_is_not_disappearance(self):
        self.assertEqual(self.observe([None, True, True]), (False, False))
        self.assertEqual(self.observe([True, True]), (False, False))
        self.assertEqual(self.observe([False, None, True]), (True, True))

    def test_linux_recovery_requires_new_valid_boot_id(self):
        old = '157a7817-20f6-408d-8de1-f6ccc4adbf74'
        new = '7cbdcc2a-7407-4e00-a2fe-c8019659e476'
        for boot_id, version, accepted in [(old, 'Linux version candidate', False),
                (new, 'Linux version installed', True), ('bad', 'Linux version installed', False),
                (new, '', False)]:
            self.assertEqual(cycle.is_new_linux_boot(dict(boot_id=boot_id, version=version), old), accepted)
        self.assertEqual(cycle.observe_reset(1, False, ready=lambda: False,
            now=lambda: 0, linux_ready=lambda: True), (True, True))

    def test_missing_tool_and_timeout_are_unknown(self):
        for error in [FileNotFoundError('missing'), subprocess.TimeoutExpired('fastboot', 4)]:
            with patch.object(cycle.subprocess, 'run', side_effect=error):
                self.assertIsNone(cycle.fastboot_ready())

    def test_usb_recovery_does_not_require_tailscale(self):
        old = '157a7817-20f6-408d-8de1-f6ccc4adbf74'
        new = '7cbdcc2a-7407-4e00-a2fe-c8019659e476'
        with patch.object(cycle, 'run', return_value=subprocess.CompletedProcess([], 0, new+'\nLinux version installed\n', '')) as runner:
            result = cycle.probe_new_linux_boot(['usb', 'tailscale'], old)
            self.assertEqual(result['ssh_target'], 'usb')
            self.assertEqual(runner.call_count, 1)

    def test_network_fallback_rejects_unchanged_and_failed_probes(self):
        old = '157a7817-20f6-408d-8de1-f6ccc4adbf74'
        new = '7cbdcc2a-7407-4e00-a2fe-c8019659e476'
        for first in [subprocess.CompletedProcess([], 124, '', 'timeout'),
                      subprocess.CompletedProcess([], 0, old+'\nLinux version candidate\n', '')]:
            second = subprocess.CompletedProcess([], 0, new+'\nLinux version installed\n', '')
            with self.subTest(first=first.returncode), patch.object(cycle, 'run', side_effect=[first, second]):
                self.assertEqual(cycle.probe_new_linux_boot(['usb', 'tailscale'], old)['ssh_target'], 'tailscale')
        with patch.object(cycle, 'run', return_value=first) as runner:
            self.assertIsNone(cycle.probe_new_linux_boot(['usb', 'usb'], old))
            self.assertEqual(runner.call_count, 1)
        with patch.object(cycle, 'run') as runner:
            self.assertIsNone(cycle.probe_new_linux_boot(['usb'], None))
            runner.assert_not_called()

    def exercise_main(self, bad_handoff=False, present=True, audio_probe=False, audio_failed=False, repetitions=1):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); bundle = root/'input'; bundle.mkdir()
            (bundle/'dtbs').mkdir()
            (bundle/'vmlinuz').write_bytes(gzip.compress(b'Linux version candidate\0'))
            (bundle/'t825-audiodiag-ram.img').write_bytes(b'fake image, never booted')
            out = root/'report'; out.mkdir()
            (root/'artifacts/roadmap-7.3').mkdir(parents=True)
            called = []
            def fake_run(command, seconds=10, text=None):
                called.append(command)
                output = ''
                if 'getvar' in command: output = 'lk2nd:compatible: samsung,gts3llte'
                elif command[0] == 'ssh' and text and text.startswith('CONFIG = '):
                    config = ast.literal_eval(text.splitlines()[0].split(' = ', 1)[1])
                    self.assertEqual(config['repetitions'], repetitions)
                    output = json.dumps({'status': 'FAIL' if audio_failed else 'PASS'})
                elif command[0] == 'ssh':
                    data = evidence()
                    if bad_handoff: data['version'] = 'Linux version r1'
                    output = json.dumps(data)
                elif any('t825-telnet.py' in item for item in command):
                    output = 'T825_SUPERVISOR_PID=42\nT825_BOOT_ID=157a7817-20f6-408d-8de1-f6ccc4adbf74\n'
                return subprocess.CompletedProcess(command, 0, output, '')
            argv = ['cycle', str(bundle), str(out), '--kind', 'audio']
            if audio_probe: argv += ['--audio-probe', '--audio-repetitions', str(repetitions)]
            # First preflight is present; subsequent boot probes are absent.
            with patch.object(sys, 'argv', argv), patch.dict(os.environ, {
                    'T825_READONLY_SNAPSHOT':'1', 'T825_SOURCE_ROOT':str(root)}), \
                 patch.object(cycle, 'run', side_effect=fake_run), \
                 patch.object(cycle, 'archive_supervisor_hash', return_value='expected'), \
                 patch.object(cycle, 'fastboot_ready', side_effect=[present, False, False]), \
                 patch.object(cycle, 'observe_reset', return_value=(True, True)) as observer:
                if not present:
                    with self.assertRaisesRegex(ValueError, 'not in fastboot'): cycle.main()
                    self.assertFalse(any('boot' in command for command in called))
                    observer.assert_not_called()
                    return
                rc = cycle.main()
                observer.assert_called_once()
                result = json.loads((out/'result.json').read_text())
                self.assertTrue(result['reset_observed'])
                self.assertEqual(result['diagnostic_pass'], not bad_handoff)
                self.assertEqual(rc, int(bad_handoff or audio_failed))
                self.assertEqual(result['audio_probe_pass'], not audio_failed if audio_probe else None)
                if audio_failed: self.assertFalse(result['unattended_next_ram_cycle'])
                boots = [command for command in called if 'boot' in command]
                self.assertEqual(len(boots), 1)
                self.assertTrue(boots[0][-1].startswith(str(out/'bundle')))

    def test_successful_handoff_still_observes_reset(self): self.exercise_main()
    def test_failed_handoff_still_observes_reset(self): self.exercise_main(bad_handoff=True)
    def test_no_fastboot_never_dispatches_boot(self): self.exercise_main(present=False)
    def test_audio_probe_success_still_observes_reset(self): self.exercise_main(audio_probe=True)
    def test_audio_probe_failure_still_observes_reset(self): self.exercise_main(audio_probe=True, audio_failed=True)
    def test_three_captures_use_one_boot_and_one_reset_observer(self): self.exercise_main(audio_probe=True, repetitions=3)

if __name__ == '__main__': unittest.main()
