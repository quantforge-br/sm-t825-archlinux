#!/usr/bin/env python3
"""Exercise missing counters and binding replacement without tablet access."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "sampler", Path(__file__).with_name("t825-bluetooth-ibs-sample.py"))
sampler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sampler)


class IbsSampling(unittest.TestCase):
    def test_debugfs_boolean_votes_are_not_integer_parse_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tx_vote").write_text("Y\n")
            (root / "rx_vote").write_text("N\n")
            row = sampler.sample(root)
        self.assertEqual(row["values"], {"tx_vote": 1, "rx_vote": 0})

    def test_missing_directory_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = sampler.sample(Path(tmp) / "missing")
        self.assertEqual(row["values"], {})
        self.assertEqual(row["directory_error"], 2)
        self.assertGreaterEqual(row["end_monotonic_ns"], row["start_monotonic_ns"])

    def test_invalid_and_missing_values_are_not_zero_counters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tx_ibs_state").write_text("2\n")
            (root / "rx_ibs_state").write_text("invalid\n")
            (root / "ibs_sent_wakes").symlink_to(root / "tx_ibs_state")
            row = sampler.sample(root)
        self.assertEqual(row["values"], {"tx_ibs_state": 2})
        self.assertEqual(row["errors"]["rx_ibs_state"], "invalid_integer")
        self.assertIn("ibs_sent_wakes", row["errors"])
        self.assertEqual(row["errors"]["ibs_recv_wake_acks"], 2)

    def test_rebinding_during_sample_keeps_old_directory_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ibs"
            root.mkdir()
            (root / "tx_ibs_state").write_text("2\n")
            old_inode = root.stat().st_ino
            original_open = os.open

            def rebind(path, flags, **kwargs):
                fd = original_open(path, flags, **kwargs)
                if path == root:
                    root.rename(Path(tmp) / "retired")
                    root.mkdir()
                    (root / "tx_ibs_state").write_text("0\n")
                return fd

            with patch.object(sampler.os, "open", side_effect=rebind):
                before = sampler.sample(root)
            after = sampler.sample(root)
        self.assertEqual(before["directory_identity"][1], old_inode)
        self.assertNotEqual(before["directory_identity"], after["directory_identity"])
        self.assertEqual(before["values"]["tx_ibs_state"], 2)
        self.assertEqual(after["values"]["tx_ibs_state"], 0)


if __name__ == "__main__":
    unittest.main()
