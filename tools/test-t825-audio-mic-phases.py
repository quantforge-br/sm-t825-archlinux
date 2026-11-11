#!/usr/bin/env python3
"""Exercise nonblocking capture failures and detached-runner cleanup offline."""
import ctypes
import errno
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mic", TOOLS / "t825-audio-mic-phases.py")
mic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mic)


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class FakeAlsa:
    def __init__(self, reads, state=3):
        self.reads = iter(reads)
        self.calls = []
        self.state = state
        self.functions = {}

    def __getattr__(self, name):
        def call(*args):
            self.calls.append(name)
            if name == "snd_pcm_readi":
                result = next(self.reads)
                if 0 < result <= args[-1]:
                    ctypes.memset(args[1], 0, result * 4)
                return result
            if name == "snd_pcm_state":
                return self.state
            return 0
        if name not in self.functions:
            self.functions[name] = Function(call)
        return self.functions[name]



class FakeEventRing:
    """Python model of the kernel ring: 256 records, 36 per page, cursor clamp."""
    def __init__(self, total, capacity=256, page=36, corrupt=False):
        self.total, self.capacity, self.page, self.corrupt, self.cursor = total, capacity, page, corrupt, 0
        self.records = self.Records(self)
        self.cursor_file = self.Cursor(self)

    class Cursor:
        def __init__(self, ring):
            self.ring = ring

        def write_text(self, text):
            self.ring.cursor = int(text)

    class Records:
        def __init__(self, ring):
            self.ring = ring

        def is_file(self):
            return True

        def read_text(self):
            ring = self.ring
            first = max(ring.total - ring.capacity, 0)
            start = min(max(ring.cursor, first), ring.total)
            count = min(ring.total - start, ring.page)
            lines = [f"enabled=1 count={count} total={ring.total} dropped={max(start - ring.cursor, 0)} "
                     f"first={start} next={start + count}"]
            for seq in range(start, start + count):
                lines.append(f"{seq + (1 if ring.corrupt and seq == start + 3 else 0)} {seq * 1000} ev {seq} {-seq}")
            return "\n".join(lines) + "\n"


class EventPagingTest(unittest.TestCase):
    def read(self, ring, cursor):
        return mic.read_event_pages(cursor, ring.records, ring.cursor_file)

    def test_pages_cover_every_record_after_cursor(self):
        text, cursor = self.read(FakeEventRing(300), 44)
        lines = text.splitlines()
        self.assertEqual(lines[0], "enabled=1 count=256 total=300 dropped=0 first=44 next=300")
        self.assertEqual([int(line.split()[0]) for line in lines[1:]], list(range(44, 300)))
        self.assertEqual(cursor, 300)

    def test_overwritten_records_are_counted_as_dropped(self):
        text, _ = self.read(FakeEventRing(300), 0)
        self.assertIn("dropped=44 first=44 next=300", text.splitlines()[0])

    def test_noncontiguous_page_is_rejected(self):
        with self.assertRaises(ValueError):
            self.read(FakeEventRing(20, corrupt=True), 0)

    def test_head_starts_after_existing_records(self):
        ring = FakeEventRing(123)
        self.assertEqual(mic.event_head(ring.records, ring.cursor_file), 123)
        text, cursor = self.read(ring, 123)
        self.assertEqual((text, cursor), ("enabled=1 count=0 total=123 dropped=0 first=123 next=123\n", 123))

class CaptureFailures(unittest.TestCase):
    def run_phase_sequence(self, fault):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            calls = [0]
            def execute(argv):
                self.assertEqual(argv, ['dmesg'])
                calls[0] += 1
                text = '[    0.000000] boot\n'
                if fault and calls[0] >= 7:
                    message = fault if isinstance(fault, str) else 'wcd9335: overflow error on TX port 1'
                    text += '[   10.000000] '+message+'\n'
                return {'stdout': text}
            original = Path.read_text
            def read_text(path, *args, **kwargs):
                if str(path) == '/proc/sys/kernel/random/boot_id': return 'same-boot\n'
                return original(path, *args, **kwargs)
            capture = Mock()
            capture.params.return_value = {'rate': 48000, 'channels': 2}
            with patch.object(mic.validate, 'execute', side_effect=execute), \
                 patch.object(mic.validate, 'UCM') as ucm, \
                 patch.object(mic, 'Capture', return_value=capture) as factory, \
                 patch.object(mic, 'read_then_drop', return_value={'frames': 48000}), \
                 patch.object(Path, 'read_text', read_text), \
                 patch.object(Path, 'glob', return_value=[]), \
                 patch.object(mic.time, 'sleep'):
                rc = mic.collect(out, 3)
                self.assertEqual(rc, int(bool(fault)))
                self.assertEqual(factory.call_count, 1 if fault else 3)
                self.assertEqual(capture.close.call_count, 1 if fault else 3)
                disables = [c for c in ucm.return_value.__enter__.return_value.set.call_args_list
                            if c.args == ('_disdev', 'Mic')]
                self.assertEqual(len(disables), 1 if fault else 3)
            result = __import__('json').loads((out/'decision.json').read_text())
            self.assertEqual(result['captures_completed'], 1 if fault else 3)
            self.assertEqual(result['requested'], 3)
            if fault:
                stages = __import__('json').loads((out/'stages.json').read_text())
                self.assertTrue(next(s for s in stages if s['phase'] == 'mic-1-active-interval')['kernel_faults'])

    def test_three_capture_sequence_stops_at_first_kernel_fault(self):
        self.run_phase_sequence(True)

    def test_negative_ngd_removal_return_stops_before_next_capture(self):
        self.run_phase_sequence('streamdiag stage=controller-disable mc=-1 rc=-5')

    def test_three_capture_sequence_completes_when_no_fault_observed(self):
        self.run_phase_sequence(False)

    def test_short_nonblocking_reads_are_accumulated_exactly(self):
        library = FakeAlsa([-errno.EAGAIN, 0, 3, 5])
        capture = mic.Capture(library)
        metrics = mic.validate.pcm_metrics(capture.read(frames=8))
        self.assertEqual(metrics["frames"], 8)
        self.assertEqual(metrics["channels"][0]["peak"], 0)
        self.assertEqual(library.calls.count("snd_pcm_wait"), 2)

    def test_xrun_is_reported_without_recovery(self):
        library = FakeAlsa([2, -errno.EPIPE])
        with self.assertRaisesRegex(RuntimeError, "no recovery attempted"):
            mic.Capture(library).read(frames=8)
        self.assertNotIn("snd_pcm_recover", library.calls)
        self.assertNotIn("snd_pcm_prepare", library.calls)

    def test_final_nonrunning_pcm_cannot_pass_on_frame_count(self):
        with self.assertRaisesRegex(RuntimeError, "not RUNNING"):
            mic.Capture(FakeAlsa([8], state=4)).read(frames=8)

    def test_capture_deadline_stops_an_unresponsive_pcm(self):
        with patch.object(mic.time, "monotonic", side_effect=[0, 6]):
            with self.assertRaisesRegex(RuntimeError, "capture deadline"):
                mic.Capture(FakeAlsa([])).read(frames=8)

    def test_impossible_frame_count_cannot_read_beyond_buffer(self):
        with self.assertRaisesRegex(RuntimeError, "more frames"):
            mic.Capture(FakeAlsa([9])).read(frames=8)

    def test_software_null_pcm_exercises_real_ctypes_abi_without_hardware(self):
        capture = mic.Capture()
        capture.call("open", ctypes.byref(capture.handle), b"null", 1, 1)
        capture.opened = True
        try:
            self.assertEqual(capture.params()["rate"], 48000)
            capture.prepare()
            self.assertEqual(mic.validate.pcm_metrics(capture.read())["frames"], 48000)
            capture.drop()
        finally:
            capture.close()

    def test_metric_reduction_runs_after_drop(self):
        calls = []
        capture = Mock()
        capture.read.side_effect = lambda: calls.append("read") or bytes(32)
        capture.drop.side_effect = lambda: calls.append("drop")
        operations = []
        with patch.object(mic.validate, "pcm_metrics", side_effect=lambda data: calls.append("metrics")):
            mic.read_then_drop(capture, "mic-1", operations)
        self.assertEqual(calls, ["read", "drop", "metrics"])
        self.assertEqual([row["operation"] for row in operations], ["mic-1-start-read", "mic-1-drop"])

    def test_read_failure_still_drops_and_retains_phase_error(self):
        capture = Mock()
        capture.read.side_effect = RuntimeError("read failed")
        operations = []
        with self.assertRaisesRegex(RuntimeError, "read failed"):
            mic.read_then_drop(capture, "mic-1", operations)
        capture.drop.assert_called_once_with()
        self.assertEqual(operations[0]["error"], "read failed")


FAKE_SSH = r'''#!/usr/bin/python3
import io
import json
import os
from pathlib import Path
import sys
import tarfile

root = Path(os.environ['FAKE_ROOT'])
scenario = os.environ['FAKE_SCENARIO']
command = sys.argv[-1]
with (root / 'commands').open('a') as log:
    log.write(command + '\n')
if command.startswith('systemctl is-system-running'):
    print('running\nLinux fake\nboot-id')
elif 'tar -C ' in command:
    if scenario == 'archive_failure':
        sys.exit(23)
    decision = {'status': 'FAIL' if scenario == 'fault' else 'PASS', 'boot_unchanged': scenario != 'boot_changed', 'captures_completed': 1, 'requested': 1}
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as tar:
        files = {} if scenario == 'missing_decision' else {'decision.json': json.dumps(decision)}
        for name, value in files.items():
            data = value.encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
elif 'ActiveState -p Result' in command:
    print('ActiveState=inactive\nResult=success')
elif command.startswith('systemctl is-active '):
    print('active')
elif 'systemctl stop ' in command:
    if scenario == 'stop_failure':
        sys.exit(1)
elif 'systemd-run ' in command:
    if '--on-active=' in command and scenario == 'arm_failure':
        sys.exit(1)
elif 'tee ' in command:
    sys.stdin.buffer.read()
elif 'mkdir ' in command or 'alsactl ' in command:
    pass
elif 't825-audio-mic-restore.sh' in command:
    if scenario == 'restore_failure':
        sys.exit(1)
else:
    print('Unexpected command: ' + command, file=sys.stderr)
    sys.exit(97)
'''


class HostCleanup(unittest.TestCase):
    def run_host(self, scenario):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        scripts = root / "tools"
        scripts.mkdir()
        for file in ("t825-audio-mic-phases.sh", "t825-audio-mic-phases.py",
                     "t825-audio-mic-restore.sh", "t825-validate.py"):
            shutil.copy2(TOOLS / file, scripts / file)
        bins = root / "bin"
        bins.mkdir()
        for name, code in {"ssh": FAKE_SSH, "sleep": "#!/bin/sh\nexit 0\n"}.items():
            path = bins / name
            path.write_text(code)
            path.chmod(0o755)
        report = root / "artifacts/roadmap-7.3/report"
        env = os.environ.copy()
        env.update(PATH=str(bins) + os.pathsep + env["PATH"], FAKE_ROOT=str(root),
                   FAKE_SCENARIO=scenario, T825_SOURCE_ROOT=str(root),
                   T825_MIC_REPORT=str(report), T825_RUNNER_SNAPSHOT="0")
        result = subprocess.run(["bash", str(scripts / "t825-audio-mic-phases.sh")], env=env,
                                capture_output=True, text=True, timeout=10)
        decision = dict(line.split("=", 1) for line in (report / "result.txt").read_text().splitlines())
        return result, (root / "commands").read_text(), decision

    def test_complete_capture_requires_restoration_before_timer_cancellation(self):
        result, commands, decision = self.run_host("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision["mixer_restored"], "1")
        self.assertLess(commands.index("--on-active="), commands.index("--property=RuntimeMaxSec=75"))
        self.assertLess(commands.index("sudo -n /bin/bash"), commands.index("systemctl stop "))

    def test_archive_failure_still_restores_and_fails(self):
        result, commands, decision = self.run_host("archive_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(decision["archive_status"], "23")
        self.assertEqual(decision["mixer_restored"], "1")

    def test_failed_restore_retains_independent_timer(self):
        result, commands, decision = self.run_host("restore_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(decision["mixer_restored"], "0")
        self.assertNotIn("systemctl stop ", commands)

    def test_fault_missing_evidence_and_changed_boot_cannot_pass(self):
        for scenario in ("fault", "missing_decision", "boot_changed", "stop_failure"):
            result, _, _ = self.run_host(scenario)
            self.assertNotEqual(result.returncode, 0, scenario)

    def test_ambiguous_arm_failure_cannot_launch_capture(self):
        result, commands, decision = self.run_host("arm_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("--property=RuntimeMaxSec=75", commands)
        self.assertNotIn("systemctl stop ", commands)
        self.assertEqual(decision["finished"], "0")


if __name__ == "__main__":
    unittest.main()
