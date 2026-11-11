#!/usr/bin/env python3
"""Regression checks for classification of hardware evidence; no hardware I/O."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("validate", Path(__file__).with_name("t825-validate.py"))
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


class KernelEvidence(unittest.TestCase):
    def test_negative_audio_diagnostic_returns_are_faults_even_without_overflow(self):
        for line in ('streamdiag stage=controller-disable mc=-1 rc=-5',
                     'portdiag stage=trigger-stop disable_rc=-110 unprepare_rc=0',
                     'portdiag stage=trigger-start prepare_rc=0 enable_rc=-12'):
            self.assertTrue(validate.FAULTS.findall(line))
        self.assertFalse(validate.FAULTS.findall('streamdiag stage=controller-enable mc=-1 rc=0'))
        self.assertFalse(validate.FAULTS.findall('portdiag stage=trigger-stop disable_rc=0 unprepare_rc=0'))

    def test_append_preserves_new_faults(self):
        before = "[ 1.0] old\n"
        new = "[ 2.0] wcd9335 overflow\n"
        self.assertEqual(validate.kernel_delta(before, before + new), (new, False))

    def test_rotation_excludes_historical_fault(self):
        before = "[ 1.0] boot\n[ 2.0] wcd9335 overflow\n[ 3.0] ready\n"
        after = "[ 2.0] wcd9335 overflow\n[ 3.0] ready\n[ 4.0] resumed\n"
        self.assertEqual(validate.kernel_delta(before, after), ("[ 4.0] resumed\n", True))

    def test_equal_timestamps_do_not_hide_new_fault(self):
        before = "[ 1.0] boot\n[ 2.0] ready\n"
        after = "[ 2.0] ready\n[ 2.0] wcd9335 overflow\n"
        self.assertIn("overflow", validate.kernel_delta(before, after)[0])

    def test_missing_overlap_blocks(self):
        with self.assertRaises(validate.Blocked):
            validate.kernel_delta("[ 1.0] boot\n[ 2.0] ready\n", "[ 4.0] later\n")

    def test_reordered_log_blocks(self):
        with self.assertRaises(validate.Blocked):
            validate.kernel_delta("[ 1.0] boot\n[ 2.0] ready\n", "[ 0.0] rebooted\n[ 2.0] ready\n")

    def test_duplicate_anchor_blocks(self):
        with self.assertRaises(validate.Blocked):
            validate.kernel_delta("old\nanchor\n", "anchor\nanchor\nnew\n")

    def test_classification_retains_functional_evidence_with_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = validate.Checks(Path(tmp))
            with patch.object(checks, "kernel_log", side_effect=["[ 1.0] before\n", "[ 5.0] later\n"]):
                self.assertFalse(checks.check("sleep", lambda: {"counter_after": 10}))
            result = checks.results[0]
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["evidence"]["counter_after"], 10)
            self.assertTrue((Path(tmp) / "sleep-kernel-full.txt").is_file())

    def test_rotation_still_fails_new_fault(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = validate.Checks(Path(tmp))
            logs = ["[ 1.0] boot\n[ 2.0] anchor\n", "[ 2.0] anchor\n[ 3.0] wcd9335 overflow\n"]
            with patch.object(checks, "kernel_log", side_effect=logs):
                self.assertFalse(checks.check("sleep", dict))
            self.assertEqual(checks.results[0]["status"], "FAIL")
            self.assertTrue(checks.results[0]["evidence"]["kernel_faults"])

    def test_complete_pcm_transfer_cannot_pass_with_codec_underflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = validate.Checks(Path(tmp))
            before = "[ 1.0] ready\n"
            after = before + "[ 2.0] wcd9335-slim: underflow error on TX port 1, value 2\n"
            with patch.object(checks, "kernel_log", side_effect=[before, after]):
                self.assertFalse(checks.check("mic", lambda: {"frames": 48000}))
            self.assertEqual(checks.results[0]["status"], "FAIL")
            self.assertEqual(checks.results[0]["evidence"]["frames"], 48000)


class BluetoothService(unittest.TestCase):
    def test_bdaddr_service_retries_transient_controller_failures(self):
        service = (
            Path(__file__).resolve().parents[1]
            / "pmaports/device-samsung-gts3lwifi/gts3-bdaddr.service"
        ).read_text()
        self.assertIn("Type=exec", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("RestartSec=5", service)
        self.assertIn("StartLimitIntervalSec=120", service)
        self.assertIn("StartLimitBurst=5", service)


if __name__ == "__main__":
    unittest.main()
