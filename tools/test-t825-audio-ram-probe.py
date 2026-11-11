#!/usr/bin/env python3
"""Safety gates and restoration failures, entirely without tablet access."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('t825-audio-ram-probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

CONFIG = dict(version='Linux version 7.3.1-t825-audiodiag test', boot_id='candidate', pid='120', supervisor_hash='hash')
DATA = dict(CONFIG, supervisor_log='armed at 2 deadline 242', pid1='/run/t825-recovery/postpivot-init',
            mounts=['/dev/root / btrfs ro,rescue=nologreplay 0 0', 'run /run tmpfs rw 0 0'],
            member_ro=['1', '1'], port_diagnostics='Y')

class ProbeTests(unittest.TestCase):
    def test_removal_gate_rejects_inactive_experiment(self):
        for state in (None, 'N', '0'):
            with self.assertRaisesRegex(ValueError, 'NGD'):
                probe.check_gate(dict(DATA, removal_requested=True, channel_removal=state), CONFIG, 20)
        probe.check_gate(dict(DATA, removal_requested=True, channel_removal='Y'), CONFIG, 20)

    def test_event_trace_gate_rejects_inactive_trace(self):
        for state in (None, '', '0', 'N'):
            with self.assertRaisesRegex(ValueError, 'event trace'):
                probe.check_gate(dict(DATA, event_trace_requested=True, event_trace=state), CONFIG, 20)
        probe.check_gate(dict(DATA, event_trace_requested=True,
                              event_trace='enabled=1 count=2 total=2 dropped=0\n'), CONFIG, 20)

    def test_removal_module_option_and_failed_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for active in (False, True):
                calls = []
                def run(argv, directory, label, timeout):
                    calls.append((argv, label))
                    return 0
                with patch.object(probe, 'evidence', return_value=DATA), \
                     patch.object(probe.time, 'clock_gettime', return_value=20), \
                     patch.object(Path, 'read_text', return_value='run /usr/lib/modules tmpfs ro 0 0'), \
                     patch.object(probe, 'transaction_requested', return_value=True), \
                     patch.object(probe, 'transaction_active', return_value=True), \
                     patch.object(probe, 'removal_requested', return_value=True), \
                     patch.object(probe, 'removal_active', return_value=active), \
                     patch.object(probe, 'firmware_inventory', return_value={}), \
                     patch.object(probe, 'audio_ready', return_value=True), \
                     patch.object(probe, 'command', side_effect=run):
                    if active:
                        probe.prepare_audio(Path(tmp), CONFIG)
                    else:
                        with self.assertRaisesRegex(ValueError, 'NGD'):
                            probe.prepare_audio(Path(tmp), CONFIG)
                ngd = next(argv for argv, label in calls if label == 'load-slim_qcom_ngd_ctrl')
                self.assertEqual(ngd[-1], 'channel_removal=1')
                self.assertEqual(any(label == 'load-qcom_q6v5_pas' for _, label in calls), active)

    def test_removal_option_matches_exact_command_line_word(self):
        for line, expected in [('slim_qcom_ngd_ctrl.channel_removal=1', True),
                               ('slim_qcom_ngd_ctrl.channel_removal=0', False),
                               ('xslim_qcom_ngd_ctrl.channel_removal=1', False)]:
            with patch.object(Path, 'read_text', return_value=line):
                self.assertEqual(probe.removal_requested(), expected)

    def test_event_trace_option_matches_exact_command_line_word(self):
        for line, expected in [('slimbus.event_trace=1', True),
                               ('slimbus.event_trace=0', False),
                               ('xslimbus.event_trace=1', False)]:
            with patch.object(Path, 'read_text', return_value=line):
                self.assertEqual(probe.event_trace_requested(), expected)

    def test_gate_rejects_unsafe_states(self):
        probe.check_gate(DATA, CONFIG, 20)
        for key, value in [('version', 'Linux version installed'), ('boot_id', 'other'),
                ('pid', '121'), ('supervisor_hash', 'wrong'), ('pid1', '/sbin/init'),
                ('member_ro', ['1', '0']), ('member_ro', ['1']), ('port_diagnostics', 'N'),
                ('mounts', ['/dev/root / btrfs rw 0 0', 'run /run tmpfs rw 0 0']),
                ('mounts', DATA['mounts']+['/dev/boot /boot ext4 ro 0 0']),
                ('supervisor_log', 'armed at 2 deadline 9999')]:
            with self.subTest(key=key):
                data = copy.deepcopy(DATA); data[key] = value
                with self.assertRaises(ValueError): probe.check_gate(data, CONFIG, 20)
        with self.assertRaisesRegex(ValueError, 'deadline'): probe.check_gate(DATA, CONFIG, 150)

    def scenario(self, fault=None, repetitions=1, removal=False):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp); calls = []; printed = io.StringIO()
            data = copy.deepcopy(DATA)
            if fault == 'gate': data['member_ro'] = ['0', '0']
            def command(argv, directory, label, timeout):
                calls.append(label)
                if label == 'mixer-store': (out/'mixer-before.state').write_text('original')
                if label == 'collector':
                    self.assertEqual(argv[-2:], ['--repetitions', str(repetitions)])
                    self.assertEqual(timeout, 45)
                    (out/'decision.json').write_text(json.dumps(dict(status='PASS', captures_completed=1 if fault == 'partial' else repetitions,
                        requested=repetitions, boot_unchanged=fault != 'boot_changed', media_saved=False)))
                    if removal and fault != 'missing_removal':
                        rc_text = '-5' if fault == 'negative_removal' else '0'
                        for capture in range(1, repetitions + 1):
                            seq = capture * 10
                            (out/f'mic-{capture}-event-records.txt').write_text(
                                f'enabled=1 count=2 total={seq + 2} dropped=0 first={seq} next={seq + 2}\n'
                                f'{seq} 1000 codec-stop-result 0 0\n'
                                f'{seq + 1} 2000 controller-disable -1 {rc_text}\n')
                    if removal and fault == 'lost_records':
                        (out/'mic-1-event-records.txt').write_text(
                            'enabled=1 count=1 total=300 dropped=44 first=44 next=45\n'
                            '44 1000 controller-disable -1 0\n')
                    if fault == 'capture_timeout': return 124
                    if fault == 'capture': return 1
                if label == 'mixer-restored': (out/'mixer-restored.state').write_text('wrong' if fault == 'mixer' else 'original')
                if label == 'mixer-restore' and fault == 'restore': return 1
                return 0
            original = Path.read_bytes
            def read_bytes(path):
                if str(path) == '/proc/device-tree/compatible': return b'samsung,gts3llte\0'
                return original(path)
            with patch.object(probe, 'evidence', return_value=data), \
                 patch.object(probe.os, 'geteuid', return_value=0), \
                 patch.object(probe.time, 'clock_gettime', return_value=20), \
                 patch.object(probe.tempfile, 'mkdtemp', return_value=tmp) as mkdir, \
                 patch.object(probe, 'prepare_audio'), \
                 patch.object(probe, 'removal_requested', return_value=removal), \
                 patch.object(Path, 'read_bytes', read_bytes), \
                 patch.object(probe, 'command', side_effect=command), contextlib.redirect_stdout(printed):
                rc = probe.main(dict(CONFIG, repetitions=repetitions), {'t825-audio-mic-phases.py':'# frozen collector', 't825-validate.py':'# dependency'})
                result = json.loads(printed.getvalue())
                self.assertEqual(rc, 0 if fault is None else 1)
                if fault == 'gate':
                    mkdir.assert_not_called(); self.assertEqual(calls, [])
                else:
                    self.assertIn('mixer-restore', calls)
                    self.assertIn('mixer-restored', calls)
                self.assertFalse(result['media_saved'])

    def test_removal_acceptance_requires_success_record_for_every_capture(self):
        self.scenario(removal=True, repetitions=3)
        self.scenario(fault='missing_removal', removal=True)
        self.scenario(fault='negative_removal', removal=True)
        self.scenario(fault='lost_records', removal=True)

    def test_failure_paths_always_restore(self):
        for fault in [None, 'gate', 'capture', 'capture_timeout', 'restore', 'mixer', 'boot_changed']:
            with self.subTest(fault=fault): self.scenario(fault)

    def test_three_captures_require_all_three_without_extending_timeout(self):
        self.scenario(repetitions=3)
        self.scenario(fault='partial', repetitions=3)

    def test_invalid_counts_refused_before_device_access(self):
        for count in [0, 4, -1, True, '3']:
            with self.subTest(count=count), patch.object(probe, 'evidence') as ev, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(dict(CONFIG, repetitions=count), {}), 1)
                ev.assert_not_called()

    def test_command_timeout_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('collector', 45)):
            self.assertEqual(probe.command(['collector'], Path(tmp), 'collector', 45), 124)

    def test_preparation_allows_absent_codec_but_requires_larger_deadline(self):
        data = dict(DATA, port_diagnostics=None)
        probe.check_gate(data, CONFIG, 20, preparing=True)
        with self.assertRaisesRegex(ValueError, 'codec'): probe.check_gate(data, CONFIG, 20)
        with self.assertRaisesRegex(ValueError, 'deadline'): probe.check_gate(data, CONFIG, 100, preparing=True)

    def test_transaction_opt_in_requires_active_parameter_before_capture(self):
        for state in (None, 'N', '0'):
            data = dict(DATA, transaction_requested=True, transaction_diagnostics=state)
            probe.check_gate(data, CONFIG, 20, preparing=True)
            with self.assertRaisesRegex(ValueError, 'SLIMbus'):
                probe.check_gate(data, CONFIG, 20)
        probe.check_gate(dict(DATA, transaction_requested=True, transaction_diagnostics='Y'), CONFIG, 20)
        probe.check_gate(DATA, CONFIG, 20)  # Historical codec-only candidate.

    def test_transaction_provider_precedes_codec_and_refuses_inactive_or_failed_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            for failed, active in ((False, True), (True, True), (False, False)):
                calls = []
                def run(argv, directory, label, timeout):
                    calls.append((argv, label, timeout))
                    return int(failed and label == 'load-slimbus')
                with patch.object(probe, 'evidence', return_value=DATA), \
                     patch.object(probe.time, 'clock_gettime', return_value=20), \
                     patch.object(Path, 'read_text', return_value='run /usr/lib/modules tmpfs ro 0 0'), \
                     patch.object(probe, 'transaction_requested', return_value=True), \
                     patch.object(probe, 'transaction_active', return_value=active), \
                     patch.object(probe, 'firmware_inventory', return_value={}), \
                     patch.object(probe, 'audio_ready', return_value=True), \
                     patch.object(probe, 'command', side_effect=run):
                    if failed or not active:
                        with self.assertRaisesRegex(ValueError, 'SLIMbus'):
                            probe.prepare_audio(Path(tmp), CONFIG)
                    else:
                        probe.prepare_audio(Path(tmp), CONFIG)
                self.assertEqual(calls[0][0], ['modprobe', '-C', '/dev/null', '--ignore-install',
                                              'slimbus', 'transaction_diagnostics=1'])
                self.assertEqual(calls[-1][1], 'provider-kernel')
                loads = [row for row in calls if row[1].startswith('load-')]
                self.assertEqual(len(loads), 1 if failed or not active else 1+len(probe.MODULES))

    def test_transaction_opt_in_matches_a_complete_command_line_word(self):
        for line, expected in [('slimbus.transaction_diagnostics=1', True),
                               ('a slimbus.transaction_diagnostics=1 b', True),
                               ('slimbus.transaction_diagnostics=0', False),
                               ('xslimbus.transaction_diagnostics=1', False)]:
            with patch.object(Path, 'read_text', return_value=line):
                self.assertEqual(probe.transaction_requested(), expected)

    def test_firmware_requires_each_nonempty_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for stem in ('adsp', 'slpi'):
                data = bytearray(116); data[:6] = b'\x7fELF\x01\x01'
                struct.pack_into('<I', data, 28, 52)
                struct.pack_into('<HH', data, 42, 32, 2)
                struct.pack_into('<8I', data, 52, 1, 0, 0, 0, 4, 4, 0, 0)
                (base/(stem+'.mdt')).write_bytes(data)
                (base/(stem+'.b00')).write_bytes(b'test')
            self.assertEqual(len(probe.firmware_inventory(base)), 4)
            (base/'adsp.b00').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'size mismatch'): probe.firmware_inventory(base)
            (base/'adsp.b00').unlink()
            with self.assertRaises(FileNotFoundError): probe.firmware_inventory(base)

    def test_provider_failure_stops_loading_and_records_kernel(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for failure in (False, True):
                calls = []
                def run(argv, directory, label, timeout):
                    calls.append((argv, label, timeout))
                    return int(failure and label == 'load-snd_soc_wcd9335')
                with patch.object(probe, 'evidence', return_value=DATA), \
                     patch.object(probe.time, 'clock_gettime', return_value=20), \
                     patch.object(Path, 'read_text', return_value='run /usr/lib/modules tmpfs ro 0 0'), \
                     patch.object(probe, 'firmware_inventory', return_value={}), \
                     patch.object(probe, 'audio_ready', return_value=True), \
                     patch.object(probe, 'command', side_effect=run):
                    if failure:
                        with self.assertRaisesRegex(ValueError, 'load failed'): probe.prepare_audio(out, CONFIG)
                    else: probe.prepare_audio(out, CONFIG)
                loads = [row for row in calls if row[1].startswith('load-')]
                self.assertEqual(len(loads), 2 if failure else len(probe.MODULES))
                self.assertEqual(calls[-1][1], 'provider-kernel')
                self.assertTrue(all(row[0][1:4] == ['-C', '/dev/null', '--ignore-install'] for row in loads))
                self.assertTrue(all(row[2] <= 4 for row in loads))

    def test_readiness_timeout_never_proceeds_to_capture(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(probe, 'evidence', return_value=DATA), \
             patch.object(probe.time, 'clock_gettime', return_value=20), \
             patch.object(Path, 'read_text', return_value='run /usr/lib/modules tmpfs ro 0 0'), \
             patch.object(probe, 'firmware_inventory', return_value={}), \
             patch.object(probe, 'command', return_value=0), \
             patch.object(probe.time, 'monotonic', side_effect=[0]+[1]*len(probe.MODULES)+[46]):
            with self.assertRaisesRegex(ValueError, 'readiness deadline'): probe.prepare_audio(Path(tmp), CONFIG)

if __name__ == '__main__': unittest.main()
