#!/usr/bin/env python3
"""Test the read-only ROADMAP audit parser without touching hardware."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("roadmap_audit", REPO / "tools/audit-roadmap-7.3.py")
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


class RoadmapAudit(unittest.TestCase):
    def test_classifies_open_gates_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ROADMAP.md"
            path.write_text(
                "- [ ] Validate the tablet watchdog\n"
                "- [ ] Run the offline parser\n"
                "Evidence `artifacts/does-not-exist/report/`.\n"
            )
            result = audit_module.audit(path, collect_transport=False)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["open_gate_count"], 2)
        self.assertEqual([item["scope"] for item in result["open_gates"]],
                         ["hardware", "offline"])
        self.assertEqual(result["missing_artifacts"],
                         ["artifacts/does-not-exist/report/"])

    def test_clean_roadmap_is_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ROADMAP.md"
            path.write_text("- [x] Completed\n")
            result = audit_module.audit(path, collect_transport=False)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["open_gate_count"], 0)


if __name__ == "__main__":
    unittest.main()
