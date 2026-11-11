#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit", ROOT / "tools/audit-t825-watchdog.py")
audit = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(audit)


class WatchdogAudit(unittest.TestCase):
    def test_real_evidence_is_conservative(self):
        result = audit.audit(str(audit.DEFAULT_DRIVER), str(audit.DEFAULT_STOCK), str(audit.DEFAULT_DTS))
        self.assertIn("qcom,kpss-wdt", result["driver_compatible"])
        self.assertEqual(result["stock_node"]["compatible"], ["qcom,msm-watchdog"])
        self.assertFalse(result["stock_node"]["has_clock"])
        self.assertFalse(result["current_board"]["has_watchdog_node"])
        self.assertTrue(result["current_board"]["has_pshold_reboot"])
        self.assertEqual(result["decision"], "do-not-enable-unvalidated-watchdog")

    def test_output_is_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            self.assertEqual(audit.main.__name__, "main")
            result = audit.audit(str(audit.DEFAULT_DRIVER), str(audit.DEFAULT_STOCK), str(audit.DEFAULT_DTS))
            output.write_text(__import__("json").dumps(result))
            self.assertIn("decision", output.read_text())


if __name__ == "__main__":
    unittest.main()
