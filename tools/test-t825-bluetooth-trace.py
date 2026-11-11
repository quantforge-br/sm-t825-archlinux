#!/usr/bin/env python3
"""Test readiness, rotated-log classification and host failure cleanup offline."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("trace", TOOLS / "t825-bluetooth-trace-evidence.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)

CONFIG = """Unconfigured index list with 1 item
hci0:\tUnconfigured controller
\tmanufacturer 29
\tsupported options: public-address
\tmissing options: public-address
"""


class TraceEvidence(unittest.TestCase):
    def test_missing_public_address_is_ready(self):
        self.assertTrue(trace.address_provisioning_ready(CONFIG))

    def test_configured_list_is_not_provisioning_readiness(self):
        for text in ("Index list with 0 items\n", "hci0:\tPrimary controller\n", "Configuration options\n"):
            self.assertFalse(trace.address_provisioning_ready(text))

    def test_other_controller_options_cannot_satisfy_hci0(self):
        self.assertFalse(trace.address_provisioning_ready(CONFIG.replace("hci0:", "hci1:")))
        self.assertFalse(trace.address_provisioning_ready(
            "hci0:\tUnconfigured controller\n\tmissing options: external-config\n" + CONFIG.replace("hci0:", "hci1:")))

    def test_unexpected_or_duplicate_options_fail_closed(self):
        for text in (CONFIG.replace("missing options: public-address", "missing options: "),
                     CONFIG.replace("missing options: public-address", "missing options: external-config public-address"),
                     CONFIG.replace("supported options: public-address", "supported options: external-config"),
                     CONFIG + CONFIG, CONFIG + "\tmissing options: public-address\n"):
            self.assertFalse(trace.address_provisioning_ready(text), text)

    def classify(self, before, after):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)
            if before is not None:
                (report / "kernel.before").write_text(before)
            (report / "kernel.after").write_text(after)
            return trace.classify_kernel(report)

    def test_rotating_out_an_old_timeout_cannot_hide_a_new_one(self):
        before = "[ 1.0] Opcode 0x0c03 failed: -110\n[ 2.0] anchor\n"
        after = "[ 2.0] anchor\n[ 3.0] Opcode 0x0c03 failed: -110\n"
        result = self.classify(before, after)
        self.assertEqual(result["classification"], "hci_reset_timeout")
        self.assertEqual(result["new_reset_timeouts"], 1)
        self.assertTrue(result["rotated"])

    def test_old_timeout_does_not_fail_a_clean_delta(self):
        before = "[ 1.0] Opcode 0x0c03 failed: -110\n[ 2.0] anchor\n"
        result = self.classify(before, before + "[ 3.0] ready\n")
        self.assertEqual(result["classification"], "no_new_hci_reset_timeout")

    def test_absent_empty_and_discontinuous_logs_cannot_pass(self):
        for before, after in ((None, "[ 2] after\n"), ("", "[ 2] after\n"),
                              ("[ 1] before\n", ""), ("[ 1] before\n", "[ 3] after\n"),
                              ("old\nanchor\n", "anchor\nanchor\nnew\n")):
            self.assertEqual(self.classify(before, after)["classification"], "kernel_continuity_unproven")


FAKE_SSH = r'''#!/usr/bin/python3
import io
import os
from pathlib import Path
import sys
import tarfile

root = Path(os.environ['FAKE_ROOT'])
scenario = os.environ['FAKE_SCENARIO']
command = sys.argv[-1]
with (root / 'commands').open('a') as log:
    log.write(command + '\n')
controller = 'hci0:\tPrimary controller\n\taddr 12:34:56:78:9A:BC version 8\nController 12:34:56:78:9A:BC (public)\n'
if command.startswith('systemctl is-system-running'):
    print('running\nLinux fake\n' + ('' if scenario == 'no_baseline' else controller))
elif 'tar -C ' in command:
    if scenario == 'archive_failure':
        sys.stdout.write('truncated archive')
        sys.exit(23)
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as tar:
        files = {} if scenario == 'missing_status' else {
            'collection.status': '1\n' if scenario == 'fault' else '0\n',
            'classification': 'hci_reset_timeout\n' if scenario == 'fault' else 'no_new_hci_reset_timeout\n',
        }
        for name, value in files.items():
            data = value.encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
elif command.startswith('systemctl is-active '):
    print('active\n' + (controller.replace('12:34:56:78:9A:BC', 'AA:BB:CC:DD:EE:FF') if scenario == 'wrong_address' else controller))
elif 'ActiveState --value' in command:
    print('inactive')
elif 'systemctl stop ' in command:
    if scenario == 'stop_failure':
        sys.exit(1)
elif 'systemd-run ' in command:
    if '--on-active=' in command and scenario == 'arm_failure':
        sys.exit(1)
elif 'tee ' in command:
    sys.stdin.buffer.read()
elif 'mkdir ' in command or " restore '" in command:
    pass
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
        for file in ("t825-bluetooth-trace.sh", "t825-bluetooth-trace-remote.sh",
                     "t825-bluetooth-trace-evidence.py", "t825-bluetooth-ibs-sample.py", "t825-validate.py"):
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
                   T825_BT_TRACE_REPORT=str(report), T825_RUNNER_SNAPSHOT="0")
        result = subprocess.run(["bash", str(scripts / "t825-bluetooth-trace.sh")], env=env,
                                capture_output=True, text=True, timeout=10)
        commands = (root / "commands").read_text()
        decision = dict(line.split("=", 1) for line in (report / "result.txt").read_text().splitlines())
        return result, commands, decision, report

    def test_complete_trace_passes_and_snapshots_protocol_helpers(self):
        result, commands, decision, report = self.run_host("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision["controller_restored"], "1")
        self.assertIn("t825-validate.py", (report / "runner.sha256").read_text())
        self.assertLess(commands.index("--on-active="), commands.index("--property=RuntimeMaxSec=120"))

    def test_archive_failure_still_restores_and_records_health(self):
        result, commands, decision, report = self.run_host("archive_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(decision["controller_restored"], "1")
        self.assertEqual(decision["archive_status"], "23")
        self.assertEqual(decision["classification"], "missing")
        self.assertIn(" restore '", commands)
        self.assertTrue((report / "SHA256SUMS").is_file())

    def test_wrong_restored_address_retains_independent_timer(self):
        result, commands, decision, _ = self.run_host("wrong_address")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(decision["controller_restored"], "0")
        self.assertNotIn("systemctl stop ", commands)

    def test_fault_and_missing_status_never_pass(self):
        for scenario in ("fault", "missing_status"):
            result, _, decision, _ = self.run_host(scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(decision["controller_restored"], "1")

    def test_failed_timer_cancellation_does_not_claim_success(self):
        result, _, decision, _ = self.run_host("stop_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(decision["recovery_timer_stopped"], "0")

    def test_ambiguous_arm_failure_does_not_launch_collector_or_cancel_timer(self):
        result, commands, decision, _ = self.run_host("arm_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("--property=RuntimeMaxSec=120", commands)
        self.assertNotIn("systemctl stop ", commands)
        self.assertIn(" restore '", commands)
        self.assertEqual(decision["finished"], "0")

    def test_missing_baseline_refuses_state_changes(self):
        result, commands, decision, _ = self.run_host("no_baseline")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("sudo", commands)
        self.assertEqual(decision["finished"], "0")


if __name__ == "__main__":
    unittest.main()
