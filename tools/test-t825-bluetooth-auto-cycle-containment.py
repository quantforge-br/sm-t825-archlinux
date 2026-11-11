#!/usr/bin/env python3
"""Verify the legacy reboot gate cannot contact hardware or launch a runner."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

RUNNER = Path(__file__).resolve().with_name('t825-bluetooth-auto-cycle.sh')

class RecoveryContainment(unittest.TestCase):
    def test_entry_is_blocked_before_device_access_even_with_snapshot_env(self):
        for snapshot in ('0', '1'):
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bins = root / 'bin'; bins.mkdir()
                marker = root / 'contacted'
                for command in ('ssh', 'fastboot', 'timeout', 'setsid', 'flock', 'mkdir'):
                    path = bins / command
                    path.write_text('#!/bin/sh\ntouch "$CONTACT_MARKER"\nexit 97\n')
                    path.chmod(0o755)
                report = root / 'report'
                env = dict(os.environ, PATH=str(bins) + ':' + os.environ['PATH'],
                           CONTACT_MARKER=str(marker), T825_SOURCE_ROOT=str(root),
                           T825_BT_REPORT_DIR=str(report), T825_RUNNER_SNAPSHOT=snapshot,
                           T825_BT_CYCLES='20')
                result = subprocess.run(['/bin/bash', str(RUNNER), '/unused.img'],
                                        env=env, cwd=root, capture_output=True,
                                        text=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('BLOCKED_BLUETOOTH_RECOVERY', result.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse(report.exists())

if __name__ == '__main__': unittest.main()
